from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from local_security_collector import (
    _collect_docker_scout,
    _collect_npm_audit,
    _collect_pip_audit,
    _docker_container_names,
    _inspect_container,
    _sign,
)


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


def _git_value(args: list[str]) -> str | None:
    code, stdout, _stderr = _run(["git", *args], cwd=Path(__file__).resolve().parents[1])
    return stdout if code == 0 and stdout else None


def _build_payload(label: str, version: str | None, commit_ref: str | None, container_prefix: str) -> dict:
    project_root = Path(__file__).resolve().parents[1]
    containers = []
    for name in _docker_container_names(container_prefix):
        item = _inspect_container(name)
        if item:
            containers.append(item)
    return {
        "label": label,
        "version": version or label,
        "commit_ref": commit_ref or _git_value(["rev-parse", "HEAD"]),
        "source": "local_build",
        "collected_at": datetime.now(UTC).isoformat(),
        "build_metadata": {
            "branch": _git_value(["rev-parse", "--abbrev-ref", "HEAD"]),
            "generated_at": datetime.now(UTC).isoformat(),
        },
        "software_supply_chain": {
            "npm_audit": _collect_npm_audit(project_root / "frontend"),
            "pip_audit": _collect_pip_audit(project_root),
            "docker_scout": _collect_docker_scout(containers),
        },
    }


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
    nonce = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    signature = _sign(collector_secret, timestamp, nonce, body)
    request = Request(
        url=f"{base_url.rstrip('/')}/api/projects/{project_id}/security/build-snapshots/ingest",
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
    parser = argparse.ArgumentParser(description="Build-time software factory security snapshot")
    parser.add_argument("--base-url", required=True, help="ATO Bot base URL, for example http://localhost:8000")
    parser.add_argument("--project-id", required=True, type=int)
    parser.add_argument("--collector-id", required=True, type=int)
    parser.add_argument("--collector-secret", required=True)
    parser.add_argument("--label", default=datetime.now().strftime("%Y.%m.%d.%H%M"))
    parser.add_argument("--version")
    parser.add_argument("--commit-ref")
    parser.add_argument("--container-prefix", default="atobot_")
    parser.add_argument("--dump-payload", action="store_true")
    args = parser.parse_args()

    payload = _build_payload(args.label, args.version, args.commit_ref, args.container_prefix)
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
