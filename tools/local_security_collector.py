from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import platform
import secrets
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _cmd(name: str) -> str:
    if platform.system().lower() == "windows" and not name.lower().endswith(".cmd"):
        return f"{name}.cmd"
    return name


def _run(command: list[str], *, cwd: Path | None = None) -> tuple[int, str, str]:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        cwd=str(cwd) if cwd else None,
    )
    return result.returncode, (result.stdout or "").strip(), (result.stderr or "").strip()


def _powershell(script: str) -> str:
    code, stdout, _stderr = _run(["powershell", "-NoProfile", "-Command", script])
    return stdout if code == 0 else ""


def _collect_host_posture() -> dict:
    hostname = platform.node()
    payload = {
        "hostname": hostname,
        "platform": platform.system().lower(),
        "os_version": platform.platform(),
        "kernel_version": platform.version(),
    }
    if payload["platform"] == "windows":
        os_version = _powershell("([System.Environment]::OSVersion.VersionString)")
        missing_updates = _powershell(
            "$s=New-Object -ComObject Microsoft.Update.Session; "
            "$u=$s.CreateUpdateSearcher().Search(\"IsInstalled=0 and Type='Software' and IsHidden=0\"); "
            "$u.Updates.Count"
        )
        reboot_required = _powershell(
            "if (Test-Path 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\WindowsUpdate\\Auto Update\\RebootRequired') "
            "{ 'true' } else { 'false' }"
        )
        payload["os_version"] = os_version or payload["os_version"]
        payload["missing_security_updates"] = int(missing_updates or 0)
        payload["reboot_required"] = (reboot_required or "").strip().lower() == "true"
    else:
        payload["missing_security_updates"] = 0
        payload["reboot_required"] = False
    return payload


def _docker_container_names(prefix: str) -> list[str]:
    code, stdout, _stderr = _run(["docker", "ps", "--format", "{{.Names}}"])
    if code != 0:
        return []
    return [line.strip() for line in stdout.splitlines() if line.strip() and line.strip().startswith(prefix)]


def _container_pid1_uid(name: str) -> int | None:
    code, stdout, _stderr = _run(["docker", "exec", name, "sh", "-c", "grep '^Uid:' /proc/1/status"])
    if code != 0 or not stdout:
        return None
    try:
        parts = stdout.split()
        if len(parts) < 2:
            return None
        return int(parts[1])
    except Exception:
        return None


def _inspect_container(name: str) -> dict | None:
    code, stdout, _stderr = _run(["docker", "inspect", name])
    if code != 0 or not stdout:
        return None
    try:
        raw = json.loads(stdout)[0]
    except Exception:
        return None
    host_config = raw.get("HostConfig") or {}
    config = raw.get("Config") or {}
    health = config.get("Healthcheck") or {}
    network_settings = raw.get("NetworkSettings") or {}
    ports = []
    published_ports = network_settings.get("Ports") or {}
    for container_port, bindings in published_ports.items():
        if not bindings:
            continue
        for binding in bindings:
            host_ip = binding.get("HostIp") or ""
            host_port = binding.get("HostPort") or ""
            ports.append(f"{host_ip}:{host_port}:{container_port}")
    cap_drop = host_config.get("CapDrop") or []
    pid1_uid = _container_pid1_uid(name)
    config_user = str(config.get("User") or "").strip()
    return {
        "name": raw.get("Name", "").lstrip("/") or name,
        "image": config.get("Image"),
        "digest": (raw.get("Image") or "").strip(),
        "config_user": config_user,
        "pid1_uid": pid1_uid,
        "non_root": pid1_uid is not None and pid1_uid != 0,
        "read_only_rootfs": bool(host_config.get("ReadonlyRootfs")),
        "privileged": bool(host_config.get("Privileged")),
        "cap_drop": cap_drop,
        "healthcheck": bool(health),
        "published_ports": ports,
    }


def _collect_containers(prefix: str) -> list[dict]:
    names = _docker_container_names(prefix)
    items: list[dict] = []
    for name in names:
        item = _inspect_container(name)
        if item:
            items.append(item)
    return items


def _safe_json(stdout: str) -> dict | None:
    try:
        return json.loads(stdout)
    except Exception:
        return None


def _trim_text(value: str | None, limit: int = 400) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _collect_container_package_inventory(container_name: str) -> dict:
    code, stdout, _stderr = _run(
        ["docker", "exec", container_name, "sh", "-lc", "python -m pip list --format json"]
    )
    if code == 0:
        data = _safe_json(stdout) or []
        packages = [
            {"name": item.get("name"), "version": item.get("version")}
            for item in data
            if item.get("name")
        ]
        return {
            "available": True,
            "package_manager": "pip",
            "package_count": len(packages),
            "packages": packages[:50],
        }

    package_commands = [
        (
            "apk",
            ["docker", "exec", container_name, "sh", "-lc", "apk info -v"],
            lambda output: [
                {"name": line.strip(), "version": None}
                for line in output.splitlines()
                if line.strip()
            ],
        ),
        (
            "dpkg",
            ["docker", "exec", container_name, "sh", "-lc", "dpkg-query -W -f='${Package}\\t${Version}\\n'"],
            lambda output: [
                {"name": parts[0].strip(), "version": parts[1].strip() if len(parts) > 1 else None}
                for parts in (line.split("\t", 1) for line in output.splitlines() if line.strip())
                if parts and parts[0].strip()
            ],
        ),
        (
            "rpm",
            ["docker", "exec", container_name, "sh", "-lc", "rpm -qa --qf '%{NAME}\\t%{VERSION}-%{RELEASE}\\n'"],
            lambda output: [
                {"name": parts[0].strip(), "version": parts[1].strip() if len(parts) > 1 else None}
                for parts in (line.split("\t", 1) for line in output.splitlines() if line.strip())
                if parts and parts[0].strip()
            ],
        ),
    ]

    for package_manager, command, parser in package_commands:
        code, stdout, _stderr = _run(command)
        if code != 0 or not stdout.strip():
            continue
        packages = parser(stdout)
        if not packages:
            continue
        return {
            "available": True,
            "package_manager": package_manager,
            "package_count": len(packages),
            "packages": packages[:50],
        }

    return {
        "available": False,
        "package_manager": None,
        "package_count": 0,
        "packages": [],
    }


def _collect_local_image_inventory(images: list[dict]) -> dict:
    results = []
    for item in images:
        container_name = item.get("name")
        image_name = item.get("image")
        if not container_name or not image_name:
            continue
        inventory = _collect_container_package_inventory(container_name)
        if not inventory.get("available"):
            continue
        results.append(
            {
                "image": image_name,
                "container": container_name,
                "package_manager": inventory.get("package_manager"),
                "package_count": int(inventory.get("package_count") or 0),
                "packages": inventory.get("packages") or [],
            }
        )
    return {
        "available": bool(results),
        "detail": "Local container package inventory completed" if results else "Local package inventory unavailable",
        "images": results,
    }


def _collect_npm_audit(project_root: Path) -> dict:
    code, stdout, stderr = _run([_cmd("npm"), "audit", "--json", "--omit=dev"], cwd=project_root)
    if code not in {0, 1}:
        return {"available": False, "detail": stderr or stdout or "npm audit failed"}
    data = _safe_json(stdout)
    if not data:
        return {"available": False, "detail": "npm audit returned invalid JSON"}
    vuln = ((data.get("metadata") or {}).get("vulnerabilities") or {})
    package_entries = []
    vuln_entries = []
    vulnerabilities = data.get("vulnerabilities") or {}
    for package_name, package_data in vulnerabilities.items():
        via = package_data.get("via") or []
        package_vulns = []
        for item in via:
            if not isinstance(item, dict):
                continue
            vuln = {
                "package": package_name,
                "id": str(item.get("source") or item.get("url") or item.get("name") or "npm-advisory"),
                "title": item.get("title") or item.get("name") or package_name,
                "severity": (item.get("severity") or package_data.get("severity") or "medium").lower(),
                "url": item.get("url"),
                "range": item.get("range"),
                "fix_version": (
                    package_data.get("fixAvailable", {}).get("name")
                    if isinstance(package_data.get("fixAvailable"), dict)
                    else None
                ),
                "description": _trim_text(item.get("title") or item.get("name") or ""),
            }
            package_vulns.append(vuln)
            vuln_entries.append(vuln)
        if package_vulns:
            package_entries.append(
                {
                    "name": package_name,
                    "severity": (package_data.get("severity") or "medium").lower(),
                    "direct": bool(package_data.get("isDirect")),
                    "vulnerability_count": len(package_vulns),
                    "vulnerabilities": package_vulns,
                }
            )
    return {
        "available": True,
        "detail": "npm audit completed",
        "counts": {
            "critical": int(vuln.get("critical") or 0),
            "high": int(vuln.get("high") or 0),
            "moderate": int(vuln.get("moderate") or 0),
            "low": int(vuln.get("low") or 0),
            "total": int(vuln.get("total") or 0),
        },
        "packages": package_entries[:25],
        "vulnerabilities": vuln_entries[:50],
    }


def _collect_pip_audit(project_root: Path) -> dict:
    commands = [
        ["python", "-m", "pip_audit", "-r", str(project_root / "backend" / "requirements.txt"), "-f", "json"],
        [
            "docker", "exec", "atobot_backend", "sh", "-c",
            "XDG_CACHE_HOME=/tmp PIP_AUDIT_CACHE_DIR=/tmp/pip-audit python -m pip_audit -f json",
        ],
    ]
    data = None
    detail = "pip-audit not available"
    for command in commands:
        code, stdout, stderr = _run(command)
        if code not in {0, 1}:
            detail = stderr or stdout or detail
            continue
        data = _safe_json(stdout)
        if data is None:
            detail = "pip-audit returned invalid JSON"
            continue
        detail = "pip-audit completed"
        break
    if data is None:
        return {"available": False, "detail": detail}
    dependencies = data.get("dependencies") if isinstance(data, dict) else data
    dependencies = dependencies or []
    vuln_total = 0
    high_like = 0
    package_entries = []
    vuln_entries = []
    for dep in dependencies:
        vulns = dep.get("vulns") or []
        vuln_total += len(vulns)
        high_like += len(vulns)
        if not vulns:
            continue
        package_vulns = []
        for vuln in vulns:
            vuln_item = {
                "package": dep.get("name"),
                "installed_version": dep.get("version"),
                "id": vuln.get("id"),
                "aliases": vuln.get("aliases") or [],
                "fix_versions": vuln.get("fix_versions") or [],
                "description": _trim_text(vuln.get("description")),
            }
            package_vulns.append(vuln_item)
            vuln_entries.append(vuln_item)
        package_entries.append(
            {
                "name": dep.get("name"),
                "version": dep.get("version"),
                "vulnerability_count": len(package_vulns),
                "vulnerabilities": package_vulns,
            }
        )
    return {
        "available": True,
        "detail": "pip-audit completed",
        "counts": {
            "critical": 0,
            "high": high_like,
            "moderate": 0,
            "low": 0,
            "total": vuln_total,
        },
        "packages": package_entries[:25],
        "vulnerabilities": vuln_entries[:50],
    }


def _collect_docker_scout(images: list[dict]) -> dict:
    image_names = [item.get("image") for item in images if item.get("image")]
    inventory = _collect_local_image_inventory(images)
    code, stdout, stderr = _run(["docker", "scout", "version"])
    if code != 0:
        return {
            "available": False,
            "authenticated": False,
            "coverage_mode": "inventory_only" if inventory.get("available") else "none",
            "detail": stderr or stdout or "docker scout unavailable",
            "images": [],
            "inventory": inventory,
        }

    results = []
    authenticated = True
    for image in image_names:
        code, stdout, stderr = _run(["docker", "scout", "cves", f"local://{image}", "--format", "sarif"])
        if code not in {0, 2}:
            detail = stderr or stdout or "docker scout failed"
            if "Log in with your Docker ID" in detail:
                authenticated = False
                return {
                    "available": True,
                    "authenticated": False,
                    "coverage_mode": "inventory_only" if inventory.get("available") else "none",
                    "detail": "Docker Scout is installed but not authenticated.",
                    "images": [],
                    "inventory": inventory,
                }
            results.append({"image": image, "detail": detail, "available": False})
            continue
        data = _safe_json(stdout)
        if not data:
            results.append({"image": image, "detail": "Docker Scout returned invalid JSON", "available": False})
            continue
        runs = data.get("runs") or []
        findings = 0
        severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for run in runs:
            for result in run.get("results") or []:
                findings += 1
                level = str(result.get("level") or "").lower()
                if level == "error":
                    severity_counts["high"] += 1
                elif level == "warning":
                    severity_counts["medium"] += 1
                elif level == "note":
                    severity_counts["low"] += 1
        results.append({
            "image": image,
            "available": True,
            "finding_count": findings,
            "severity_counts": severity_counts,
        })
    return {
        "available": True,
        "authenticated": authenticated,
        "coverage_mode": "authenticated_cve_scan" if authenticated else ("inventory_only" if inventory.get("available") else "none"),
        "detail": "Docker Scout completed" if authenticated else "Docker Scout authentication required",
        "images": results,
        "inventory": inventory,
    }


def _build_payload(prefix: str, backend_health_url: str) -> dict:
    project_root = Path(__file__).resolve().parents[1]
    host = _collect_host_posture()
    containers = _collect_containers(prefix)
    npm_audit = _collect_npm_audit(project_root / "frontend")
    pip_audit = _collect_pip_audit(project_root)
    docker_scout = _collect_docker_scout(containers)
    return {
        "scan_type": "local_runtime",
        "collected_at": datetime.now(UTC).isoformat(),
        "host": {
            "hostname": host["hostname"],
            "platform": host["platform"],
            "os_version": host["os_version"],
            "kernel_version": host["kernel_version"],
        },
        "containers": containers,
        "patch_posture": {
            "missing_security_updates": int(host.get("missing_security_updates") or 0),
            "reboot_required": bool(host.get("reboot_required")),
        },
        "software_supply_chain": {
            "npm_audit": npm_audit,
            "pip_audit": pip_audit,
            "docker_scout": docker_scout,
        },
        "app_security": {
            "privileged_accounts_without_mfa": 0,
            "failed_ingestion_24h": 0,
            "failed_assessments_7d": 0,
            "unresolved_critical_events": 0,
            "backend_health_url": backend_health_url,
        },
    }


def _sign(secret: str, timestamp: str, nonce: str, body: bytes) -> str:
    message = timestamp.encode("utf-8") + b"\n" + nonce.encode("utf-8") + b"\n" + body
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _post_payload(
    base_url: str,
    project_id: int,
    collector_id: int,
    collector_secret: str,
    payload: dict,
    timeout_seconds: int = 180,
) -> tuple[int, str]:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    timestamp = datetime.now(UTC).isoformat()
    nonce = secrets.token_hex(16)
    signature = _sign(collector_secret, timestamp, nonce, body)
    request = Request(
        url=f"{base_url.rstrip('/')}/api/projects/{project_id}/security/ingest",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Collector-Id": str(collector_id),
            "X-Collector-Timestamp": timestamp,
            "X-Collector-Nonce": nonce,
            "X-Collector-Signature": signature,
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return response.status, response.read().decode("utf-8")
    except HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")
    except URLError as exc:
        return 0, str(exc)


def main() -> int:
    parser = argparse.ArgumentParser(description="Local ATO Bot security collector")
    parser.add_argument("--base-url", required=True, help="ATO Bot base URL, for example http://localhost:8000")
    parser.add_argument("--project-id", required=True, type=int)
    parser.add_argument("--collector-id", required=True, type=int)
    parser.add_argument("--collector-secret", required=True)
    parser.add_argument("--container-prefix", default="atobot_")
    parser.add_argument("--backend-health-url", default="http://localhost:8000/health")
    parser.add_argument("--dump-payload", action="store_true")
    args = parser.parse_args()

    payload = _build_payload(args.container_prefix, args.backend_health_url)
    if args.dump_payload:
        print(json.dumps(payload, indent=2))

    status_code, response_text = _post_payload(
        args.base_url,
        args.project_id,
        args.collector_id,
        args.collector_secret,
        payload,
    )
    print(response_text)
    return 0 if 200 <= status_code < 300 else 1


if __name__ == "__main__":
    sys.exit(main())
