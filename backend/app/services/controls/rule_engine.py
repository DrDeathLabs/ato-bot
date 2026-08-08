"""Rule-based pre-screening for NIST 800-53 controls.

Each control family has keyword/phrase patterns. The rule engine scans document
chunks and returns a RuleSignal that informs the LLM prompt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class RuleSignal:
    control_id: str
    matched_keywords: list[str] = field(default_factory=list)
    matched_snippets: list[str] = field(default_factory=list)
    signal: str = "unknown"  # found | partial | not_found | unknown


# ── Family-level keyword maps ─────────────────────────────────────────────────
# Each entry: control_id_prefix -> list of keyword patterns
# More specific overrides for individual controls can be added.

FAMILY_KEYWORDS: dict[str, list[str]] = {
    # AC — Access Control
    "ac": [
        "access control", "least privilege", "role.based", "rbac", "account management",
        "session lock", "session timeout", "remote access", "wireless access",
        "privileged account", "separation of duties", "access enforcement",
        "information flow", "permitted actions", "unsuccessful logon",
    ],
    # AT — Awareness & Training
    "at": [
        "security awareness", "security training", "role.based training",
        "insider threat awareness", "phishing", "training records", "training program",
    ],
    # AU — Audit
    "au": [
        "audit log", "audit record", "event log", "logging", "log management",
        "audit review", "audit reduction", "time stamp", "log retention",
        "siem", "security information.*event", "non.repudiation",
    ],
    # CA — Assessment & Authorization
    "ca": [
        "security assessment", "authorization", "ato", "authority to operate",
        "continuous monitoring", "penetration test", "pen test", "control assessment",
        "interconnection", "system interconnect", "information exchange",
    ],
    # CM — Configuration Management
    "cm": [
        "configuration management", "baseline configuration", "configuration settings",
        "change control", "change management", "software usage", "user.installed software",
        "cmdb", "asset inventory", "component inventory", "least functionality",
    ],
    # CP — Contingency Planning
    "cp": [
        "contingency plan", "disaster recovery", "backup", "rto", "rpo",
        "recovery time objective", "recovery point objective", "alternate.*site",
        "backup.*site", "system backup", "information system recovery",
        "alternate storage", "alternate processing", "contingency training",
    ],
    # IA — Identification & Authentication
    "ia": [
        "multi.factor", "mfa", "two.factor", "2fa", "password", "credential",
        "authenticator", "authentication", "identity", "identification",
        "pki", "certificate", "token", "smart card", "biometric",
        "account lockout", "password complexity", "password history",
    ],
    # IR — Incident Response
    "ir": [
        "incident response", "incident handling", "incident report",
        "security incident", "breach", "intrusion", "incident management",
        "response team", "csirt", "cert", "incident tracking",
    ],
    # MA — Maintenance
    "ma": [
        "maintenance", "system maintenance", "remote maintenance",
        "maintenance tool", "sanitization", "maintenance personnel",
        "controlled maintenance", "timely maintenance",
    ],
    # MP — Media Protection
    "mp": [
        "media protection", "removable media", "media sanitization",
        "media destruction", "media access", "media marking", "media storage",
        "media transport", "data destruction", "degauss",
    ],
    # PE — Physical & Environmental
    "pe": [
        "physical access", "physical security", "access badge", "badge",
        "visitor", "data center", "server room", "environmental.*control",
        "power", "ups", "humidity", "temperature", "fire suppression",
        "emergency power", "cctv", "surveillance",
    ],
    # PL — Planning
    "pl": [
        "security plan", "system security plan", "ssp", "privacy.*plan",
        "rules of behavior", "acceptable use", "security concept",
        "information security.*architecture",
    ],
    # PM — Program Management
    "pm": [
        "information security program", "risk management", "security governance",
        "information security.*officer", "senior.*official", "risk executive",
        "plan of action", "poam",
    ],
    # PS — Personnel Security
    "ps": [
        "personnel security", "background check", "background investigation",
        "position risk", "screening", "termination", "transfer",
        "personnel sanctions",
    ],
    # PT — Privacy
    "pt": [
        "personally identifiable information", "pii", "privacy", "consent",
        "privacy notice", "data minimization", "privacy act",
    ],
    # RA — Risk Assessment
    "ra": [
        "risk assessment", "vulnerability scan", "vulnerability assessment",
        "risk categorization", "threat modeling", "criticality analysis",
        "penetration test", "risk.*report",
    ],
    # SA — System Acquisition
    "sa": [
        "system development", "sdlc", "software development.*life cycle",
        "acquisition", "supply chain", "developer.*testing", "developer.*security",
        "security requirements", "external.*service", "third.party",
    ],
    # SC — System & Communications
    "sc": [
        "encryption", "cryptography", "tls", "ssl", "https", "vpn",
        "network.*segmentation", "dmz", "firewall", "boundary.*protection",
        "transmission.*confidentiality", "key.*management", "denial.*service",
        "intrusion.*detection", "ids", "ips",
    ],
    # SI — System Integrity
    "si": [
        "malware", "antivirus", "anti.malware", "patch management", "patching",
        "vulnerability.*remediation", "flaw remediation", "input validation",
        "integrity.*check", "spam.*protection", "file.*integrity",
        "software.*integrity", "security.*alert", "threat.*intelligence",
    ],
    # SR — Supply Chain
    "sr": [
        "supply chain", "supplier", "vendor", "third.party.*component",
        "provenance", "component.*authenticity", "counterfeit",
        "acquisition.*strategy", "supply chain risk",
    ],
}


def _build_pattern(keywords: list[str]) -> re.Pattern:
    escaped = [kw.replace(".", r"\.").replace("*", ".*") for kw in keywords]
    pattern = "|".join(f"(?:{kw})" for kw in escaped)
    return re.compile(pattern, re.IGNORECASE)


# Pre-compile patterns
_COMPILED: dict[str, re.Pattern] = {
    family: _build_pattern(keywords)
    for family, keywords in FAMILY_KEYWORDS.items()
}


def evaluate(control_id: str, chunks: list[str]) -> RuleSignal:
    """Evaluate document chunks against a control using keyword matching."""
    family = control_id.split("-")[0].lower()
    pattern = _COMPILED.get(family)
    if pattern is None:
        return RuleSignal(control_id=control_id, signal="unknown")

    matched_keywords: list[str] = []
    matched_snippets: list[str] = []

    for chunk in chunks:
        for match in pattern.finditer(chunk):
            kw = match.group(0).lower()
            if kw not in matched_keywords:
                matched_keywords.append(kw)
            # Extract a short surrounding snippet
            start = max(0, match.start() - 60)
            end = min(len(chunk), match.end() + 60)
            snippet = f"...{chunk[start:end].strip()}..."
            if snippet not in matched_snippets:
                matched_snippets.append(snippet)

    if not matched_keywords:
        signal = "not_found"
    elif len(matched_keywords) >= 3:
        signal = "strong"   # sufficient keyword coverage — compliant is possible
    else:
        signal = "partial"  # weak coverage — at most partially_compliant

    return RuleSignal(
        control_id=control_id,
        matched_keywords=matched_keywords[:10],
        matched_snippets=matched_snippets[:5],
        signal=signal,
    )
