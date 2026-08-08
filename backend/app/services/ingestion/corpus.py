"""NIST 800-53 Rev 5 control keyword screening corpus.

A compact, machine-readable keyword index used by the screener for
lightweight first-pass relevance detection. Each entry maps a control ID
to a set of keywords/phrases that strongly indicate relevance.

This corpus covers all 20 control families (AC, AT, AU, CA, CM, CP, IA,
IR, MA, MP, PE, PL, PM, PS, PT, RA, SA, SC, SI, SR) and selected
enhancements. It is intentionally broad — false positives are expected
and resolved by downstream reasoning classification.

The corpus can be updated without code changes by replacing this module.
"""
from __future__ import annotations

# Control family descriptions — used to build family-level keyword set
FAMILY_KEYWORDS: dict[str, list[str]] = {
    "AC": ["access control", "access policy", "least privilege", "separation of duties",
           "account management", "access enforcement", "information flow", "remote access",
           "wireless access", "use of external systems", "publicly accessible content",
           "access restrictions", "session management", "login", "logout", "privilege",
           "permission", "authorization", "role", "user account", "group", "admin"],
    "AT": ["awareness", "training", "security training", "role-based training",
           "insider threat", "security literacy", "annual training", "completion record",
           "training record", "security awareness program", "educated", "curriculum"],
    "AU": ["audit", "audit log", "event log", "logging", "audit record", "log review",
           "audit reduction", "time stamps", "protection of audit information",
           "non-repudiation", "session audit", "cross-organization audit", "siem",
           "syslog", "event monitoring", "log retention", "log management"],
    "CA": ["assessment", "authorization", "plan of action", "poam", "security assessment",
           "continuous monitoring", "penetration test", "pen test", "red team",
           "information exchange", "supply chain risk", "authorization boundary",
           "system interconnection", "isa", "mou", "ato", "security control assessment"],
    "CM": ["configuration management", "baseline configuration", "configuration change",
           "configuration settings", "least functionality", "software usage",
           "user-installed software", "configuration inventory", "asset inventory",
           "change control", "change management", "patch", "hardening", "cis benchmark",
           "stig", "ccb", "configuration control board", "software inventory"],
    "CP": ["contingency plan", "contingency planning", "backup", "recovery",
           "disaster recovery", "business continuity", "failover", "restore",
           "alternate processing", "alternate storage", "system backup", "rto", "rpo",
           "continuity of operations", "coop", "contingency training", "contingency test"],
    "IA": ["identification", "authentication", "multi-factor", "mfa", "password",
           "credential", "token", "certificate", "pki", "identity", "authenticator",
           "device identification", "service identification", "re-authentication",
           "cryptographic module", "identity management", "biometric", "smart card",
           "account lockout", "failed login", "password policy", "complexity"],
    "IR": ["incident response", "incident handling", "incident reporting",
           "incident monitoring", "incident testing", "information spillage",
           "security incident", "breach", "contain", "eradicate", "recover",
           "lessons learned", "incident log", "cirt", "csirt", "cert"],
    "MA": ["maintenance", "controlled maintenance", "maintenance tools",
           "nonlocal maintenance", "maintenance personnel", "timely maintenance",
           "preventive maintenance", "maintenance record", "service contract"],
    "MP": ["media protection", "media access", "media marking", "media storage",
           "media transport", "media sanitization", "media disposal", "media use",
           "removable media", "usb", "portable storage", "data destruction",
           "degauss", "wipe", "purge", "sanitize"],
    "PE": ["physical", "physical access", "facility", "physical protection",
           "visitor", "badge", "camera", "surveillance", "emergency power",
           "fire protection", "temperature", "humidity", "delivery", "power equipment",
           "physical access control", "data center", "server room", "locked cabinet"],
    "PL": ["plan", "system security plan", "ssp", "rules of behavior",
           "privacy plan", "concept of operations", "conops", "security architecture",
           "central management", "operational planning"],
    "PM": ["program management", "information security program", "enterprise architecture",
           "risk management strategy", "authorization process", "mission and business process",
           "insider threat program", "security workforce", "testing and evaluation",
           "threat awareness", "security operations center", "soc"],
    "PS": ["personnel security", "position risk", "screening", "background check",
           "personnel termination", "personnel transfer", "access agreements",
           "third-party personnel", "workforce", "employee", "contractor",
           "separation", "onboarding", "offboarding", "nda", "rules of behavior signed"],
    "PT": ["personally identifiable information", "pii", "privacy", "consent",
           "privacy notice", "individual access", "privacy impact assessment",
           "pia", "records management", "data subject", "privacy act"],
    "RA": ["risk assessment", "vulnerability scan", "vulnerability assessment",
           "risk response", "criticality analysis", "privacy risk", "supply chain risk",
           "threat model", "risk register", "cvss", "cvss score", "cve",
           "penetration test", "security scan", "nessus", "qualys", "tenable"],
    "SA": ["system and services acquisition", "acquisition", "developer",
           "supply chain", "external services", "developer testing",
           "developer security architecture", "tamper resistance", "developer configuration",
           "unsupported components", "critical components", "software bill of materials",
           "sbom", "flaw remediation"],
    "SC": ["system communications", "network", "encryption", "cryptographic",
           "tls", "ssl", "https", "vpn", "firewall", "dmz", "network segmentation",
           "boundary protection", "transmission confidentiality", "network disconnect",
           "denial of service", "dos", "ddos", "mobile code", "voice over ip", "voip",
           "session authenticity", "fail in known state", "key management"],
    "SI": ["system integrity", "flaw remediation", "malicious code", "antivirus",
           "anti-malware", "spam", "security alerts", "security function verification",
           "software firmware integrity", "information input validation",
           "error handling", "information handling", "memory protection",
           "fail-safe procedures", "information management and retention",
           "intrusion detection", "ids", "ips", "patch management"],
    "SR": ["supply chain", "supply chain risk management", "scrm", "provenance",
           "acquisition strategies", "supplier assessment", "notification agreements",
           "anti-counterfeit", "vendor", "third party", "software authenticity",
           "component authenticity", "component disposal", "inspection and review"],
}

# Per-control refined keywords (highest-signal phrases for individual controls)
# Format: control_id -> list of phrases
CONTROL_KEYWORDS: dict[str, list[str]] = {
    # Access Control
    "AC-1":  ["access control policy", "access control procedures", "disseminated", "reviewed and updated"],
    "AC-2":  ["account management", "account types", "account creation", "account modification",
              "account removal", "account review", "shared accounts", "service accounts",
              "temporary accounts", "emergency accounts", "account monitoring"],
    "AC-3":  ["access enforcement", "access control decisions", "discretionary access",
              "mandatory access", "role-based access", "attribute-based access"],
    "AC-4":  ["information flow", "flow control", "data flow", "cross-domain",
              "security label", "information flow enforcement"],
    "AC-5":  ["separation of duties", "segregation of duties", "conflicting roles",
              "dual authorization"],
    "AC-6":  ["least privilege", "need-to-know", "need to know", "privileged accounts",
              "privileged functions", "non-privileged"],
    "AC-7":  ["unsuccessful logon", "account lockout", "lockout policy",
              "failed login attempts", "delay next logon"],
    "AC-8":  ["system use notification", "banner", "use notification", "warning banner",
              "terms of use"],
    "AC-11": ["session lock", "screen lock", "inactivity timeout", "screen saver"],
    "AC-12": ["session termination", "session timeout", "automatic termination"],
    "AC-14": ["permitted actions", "without identification", "without authentication"],
    "AC-17": ["remote access", "vpn", "remote work", "telework", "remote session",
              "remote connection"],
    "AC-18": ["wireless access", "wifi", "wpa", "802.11", "wireless policy",
              "wireless encryption"],
    "AC-19": ["mobile device", "mobile access", "byod", "bring your own device",
              "mobile policy"],
    "AC-20": ["external systems", "external information systems", "personally owned"],
    "AC-21": ["information sharing", "sharing decision", "automated sharing"],
    "AC-22": ["publicly accessible", "public website", "public content", "designated individual"],
    # Awareness and Training
    "AT-1":  ["awareness and training policy", "training policy", "training procedures"],
    "AT-2":  ["literacy training", "awareness training", "general security awareness",
              "social engineering", "phishing awareness"],
    "AT-3":  ["role-based training", "role-based security training", "privileged users training"],
    "AT-4":  ["training records", "training documentation", "training completion"],
    # Audit
    "AU-1":  ["audit policy", "audit procedures", "audit and accountability policy"],
    "AU-2":  ["event logging", "auditable events", "audit events", "events to audit"],
    "AU-3":  ["content of audit records", "audit record content", "user id in logs",
              "timestamp in logs", "event outcome"],
    "AU-4":  ["audit log storage", "audit storage capacity"],
    "AU-5":  ["audit processing failure", "audit failure response", "alert on audit failure"],
    "AU-6":  ["audit review", "log review", "audit analysis", "audit reporting",
              "log analysis"],
    "AU-7":  ["audit reduction", "report generation", "audit tools"],
    "AU-8":  ["time stamps", "time synchronization", "ntp", "utc", "granularity"],
    "AU-9":  ["protection of audit information", "audit protection", "read-only audit"],
    "AU-10": ["non-repudiation", "proof of origin", "digital signature"],
    "AU-11": ["audit record retention", "log retention", "retain audit"],
    "AU-12": ["audit record generation", "generate audit records", "audit capability"],
    # Assessment Authorization and Monitoring
    "CA-1":  ["assessment authorization policy", "ca policy", "ca procedures"],
    "CA-2":  ["security assessments", "security control assessments", "assessment plan",
              "assessment frequency"],
    "CA-3":  ["information exchange", "system interconnection agreement", "isa",
              "memorandum of understanding", "mou"],
    "CA-5":  ["plan of action", "poam", "plan of action and milestones",
              "weakness", "deficiency tracking"],
    "CA-6":  ["authorization", "authorizing official", "ao", "authority to operate",
              "ato decision", "authorization decision"],
    "CA-7":  ["continuous monitoring", "ongoing monitoring", "monitoring program",
              "security status"],
    "CA-8":  ["penetration testing", "pen test", "red team exercise"],
    "CA-9":  ["internal system connections", "internal connections"],
    # Configuration Management
    "CM-1":  ["configuration management policy", "cm policy"],
    "CM-2":  ["baseline configuration", "configuration baseline", "document baseline"],
    "CM-3":  ["configuration change control", "change control", "change management board",
              "configuration change", "approval for change"],
    "CM-4":  ["impact analyses", "security impact analysis", "impact analysis"],
    "CM-5":  ["access restrictions for change", "access restriction changes"],
    "CM-6":  ["configuration settings", "security configuration", "hardening",
              "stig", "cis benchmark", "configuration guide"],
    "CM-7":  ["least functionality", "prohibited functions", "prohibited ports",
              "unnecessary functionality", "disable unused"],
    "CM-8":  ["information system component inventory", "asset inventory",
              "software inventory", "hardware inventory", "component inventory"],
    "CM-9":  ["configuration management plan", "cm plan"],
    "CM-10": ["software usage restrictions", "license", "copyright", "software license"],
    "CM-11": ["user-installed software", "unauthorized software", "whitelist",
              "software installation policy"],
    # Contingency Planning
    "CP-1":  ["contingency planning policy", "cp policy"],
    "CP-2":  ["contingency plan", "business continuity plan", "disaster recovery plan",
              "recovery objectives", "rto", "rpo"],
    "CP-3":  ["contingency training", "contingency personnel training"],
    "CP-4":  ["contingency plan testing", "tabletop exercise", "disaster recovery test",
              "failover test"],
    "CP-6":  ["alternate storage site", "offsite storage", "backup site"],
    "CP-7":  ["alternate processing site", "alternate site", "failover site"],
    "CP-8":  ["telecommunications services", "alternate telecom"],
    "CP-9":  ["information system backup", "data backup", "backup frequency",
              "backup testing", "backup verification"],
    "CP-10": ["system recovery", "reconstitution", "restore from backup"],
    # Identification and Authentication
    "IA-1":  ["identification authentication policy", "ia policy"],
    "IA-2":  ["identification and authentication", "user authentication", "multi-factor",
              "mfa", "two-factor", "2fa"],
    "IA-3":  ["device identification", "device authentication", "mac address",
              "certificate-based device"],
    "IA-4":  ["identifier management", "user id management", "reuse of identifiers",
              "identifier lifecycle"],
    "IA-5":  ["authenticator management", "password management", "password policy",
              "password complexity", "password expiration", "password history",
              "credential management", "default credentials"],
    "IA-6":  ["authenticator feedback", "obscure feedback", "mask password"],
    "IA-7":  ["cryptographic module authentication", "fips 140"],
    "IA-8":  ["non-organizational users", "external user authentication", "public users"],
    "IA-11": ["re-authentication", "reauthentication"],
    "IA-12": ["identity proofing", "identity verification", "proof of identity"],
    # Incident Response
    "IR-1":  ["incident response policy", "ir policy"],
    "IR-2":  ["incident response training", "incident handling training"],
    "IR-3":  ["incident response testing", "incident exercise", "tabletop exercise ir"],
    "IR-4":  ["incident handling", "incident containment", "incident eradication",
              "incident recovery", "incident documentation"],
    "IR-5":  ["incident monitoring", "incident tracking", "incident database"],
    "IR-6":  ["incident reporting", "report incident", "reporting requirements"],
    "IR-7":  ["incident response assistance", "cirt", "csirt"],
    "IR-8":  ["incident response plan", "ir plan"],
    # Maintenance
    "MA-1":  ["maintenance policy", "ma policy"],
    "MA-2":  ["controlled maintenance", "scheduled maintenance", "maintenance records"],
    "MA-3":  ["maintenance tools", "maintenance equipment", "tool authorization"],
    "MA-4":  ["nonlocal maintenance", "remote maintenance", "out-of-band maintenance"],
    "MA-5":  ["maintenance personnel", "maintenance authorization", "escorted maintenance"],
    "MA-6":  ["timely maintenance", "spare parts", "maintenance support"],
    # Media Protection
    "MP-1":  ["media protection policy", "mp policy"],
    "MP-2":  ["media access", "media access restriction"],
    "MP-3":  ["media marking", "label media", "media classification label"],
    "MP-4":  ["media storage", "media library", "controlled area"],
    "MP-5":  ["media transport", "media in transit", "encrypt media", "media courier"],
    "MP-6":  ["media sanitization", "media disposal", "data destruction", "degauss",
              "overwrite", "purge media", "nist 800-88"],
    "MP-7":  ["media use", "prohibit media", "restrict media use"],
    # Physical and Environmental
    "PE-1":  ["physical protection policy", "pe policy"],
    "PE-2":  ["physical access authorizations", "physical access list",
              "physical access records"],
    "PE-3":  ["physical access control", "badge reader", "key card",
              "physical access points", "door lock"],
    "PE-4":  ["access control for transmission", "transmission medium access"],
    "PE-5":  ["access control for output devices", "printer access", "output device"],
    "PE-6":  ["monitoring physical access", "physical surveillance", "camera",
              "physical intrusion detection"],
    "PE-8":  ["visitor access records", "visitor log", "visitor escort"],
    "PE-9":  ["power equipment", "ups", "power redundancy", "electrical power"],
    "PE-10": ["emergency shutoff", "emergency power off", "epo"],
    "PE-11": ["emergency power", "backup power", "generator"],
    "PE-12": ["emergency lighting", "backup lighting"],
    "PE-13": ["fire protection", "fire suppression", "fire detection", "sprinkler"],
    "PE-14": ["temperature and humidity", "environmental controls", "hvac"],
    "PE-15": ["water damage protection", "water detection", "master shutoff"],
    "PE-16": ["delivery and removal", "receiving area", "loading dock"],
    "PE-17": ["alternate work site", "telework", "home office security"],
    # Planning
    "PL-1":  ["planning policy", "pl policy"],
    "PL-2":  ["system security plan", "ssp", "security plan"],
    "PL-4":  ["rules of behavior", "acceptable use policy", "aup", "rules of behavior signed"],
    "PL-8":  ["security and privacy architectures", "security architecture",
              "enterprise architecture", "security design"],
    # Risk Assessment
    "RA-1":  ["risk assessment policy", "ra policy"],
    "RA-2":  ["security categorization", "fips 199", "impact level",
              "categorization", "high water mark"],
    "RA-3":  ["risk assessment", "threat identification", "vulnerability identification",
              "likelihood", "impact determination", "risk level"],
    "RA-5":  ["vulnerability scanning", "vulnerability scan", "scan results",
              "authenticated scan", "nessus", "qualys", "tenable", "rapid7"],
    "RA-7":  ["risk response", "risk treatment", "accept risk", "mitigate risk"],
    # System and Services Acquisition
    "SA-1":  ["sa policy", "acquisition policy"],
    "SA-4":  ["acquisition process", "security requirements in acquisitions",
              "security functional requirements", "contract security requirements"],
    "SA-8":  ["security engineering principles", "least privilege design",
              "fail-safe defaults", "complete mediation"],
    "SA-9":  ["external system services", "third-party services", "cloud services",
              "managed services", "fedramp"],
    "SA-11": ["developer testing", "developer security assessment", "security testing",
              "penetration testing sa", "developer code review"],
    "SA-15": ["development process standards", "sdlc", "software development lifecycle"],
    "SA-17": ["developer security architecture", "security architecture design"],
    # System and Communications Protection
    "SC-1":  ["sc policy", "communications protection policy"],
    "SC-5":  ["denial of service", "dos protection", "availability protection"],
    "SC-7":  ["boundary protection", "firewall", "dmz", "gateway",
              "network boundary", "perimeter"],
    "SC-8":  ["transmission confidentiality", "encryption in transit", "tls", "ssl",
              "https", "ipsec", "in-transit encryption"],
    "SC-12": ["cryptographic key management", "key management", "key generation",
              "key distribution", "pki", "certificate authority"],
    "SC-13": ["cryptographic protection", "fips-validated", "nsa-approved",
              "encryption algorithm", "aes", "rsa"],
    "SC-17": ["pki certificates", "certificate policy", "ca certificate"],
    "SC-18": ["mobile code", "mobile code policy", "javascript policy"],
    "SC-20": ["secure name address resolution", "dns security", "dnssec"],
    "SC-28": ["protection of information at rest", "encryption at rest",
              "at-rest encryption", "database encryption", "disk encryption"],
    "SC-39": ["process isolation", "separate execution domains"],
    # System and Information Integrity
    "SI-1":  ["si policy", "integrity policy"],
    "SI-2":  ["flaw remediation", "patch management", "security patches",
              "vulnerability remediation", "patch cycle"],
    "SI-3":  ["malicious code protection", "antivirus", "anti-malware",
              "malware detection", "endpoint protection", "edr"],
    "SI-4":  ["system monitoring", "intrusion detection", "ids", "ips",
              "siem monitoring", "anomaly detection"],
    "SI-5":  ["security alerts", "threat intelligence", "advisories",
              "us-cert", "cisa alerts"],
    "SI-7":  ["software firmware integrity", "integrity verification",
              "hash verification", "digital signature verification"],
    "SI-10": ["information input validation", "input validation", "sanitize input",
              "injection prevention", "xss prevention"],
    "SI-12": ["information management and retention", "data retention",
              "records retention", "information lifecycle"],
    # Supply Chain Risk Management
    "SR-1":  ["supply chain policy", "scrm policy"],
    "SR-2":  ["supply chain risk management plan", "scrm plan"],
    "SR-3":  ["supply chain controls", "supply chain safeguards"],
    "SR-5":  ["acquisition strategies", "supplier evaluation"],
    "SR-6":  ["supplier assessments", "vendor assessment", "third-party assessment"],
    "SR-10": ["inspection of systems or components", "receiving inspection",
              "component inspection"],
    "SR-11": ["component authenticity", "counterfeit protection",
              "anti-counterfeit", "component verification"],
}


def get_all_control_ids(corpus_payload: dict | None = None) -> list[str]:
    """Return a flat list of all control IDs in the screening corpus."""
    control_keywords = (corpus_payload or {}).get("control_keywords", CONTROL_KEYWORDS)
    return list(control_keywords.keys())


def get_keywords_for_control(control_id: str, corpus_payload: dict | None = None) -> list[str]:
    """Return all keywords for a control (family + specific)."""
    family_keywords = (corpus_payload or {}).get("family_keywords", FAMILY_KEYWORDS)
    control_keywords = (corpus_payload or {}).get("control_keywords", CONTROL_KEYWORDS)
    family = control_id.split("-")[0] if "-" in control_id else control_id
    family_kw = family_keywords.get(family, [])
    control_kw = control_keywords.get(control_id, [])
    return list(set(family_kw + control_kw))


def screen_line(content: str, threshold: float = 0.15, corpus_payload: dict | None = None) -> dict:
    """Lightweight keyword screening of a single line of text.

    Returns:
        {
            "relevance_score": float,
            "candidate_controls": list[str],
            "candidate_enhancements": list[str],
            "rationale": str,
            "above_threshold": bool,
        }
    """
    if not content or not content.strip():
        return {
            "relevance_score": 0.0,
            "candidate_controls": [],
            "candidate_enhancements": [],
            "rationale": "Empty line",
            "above_threshold": False,
        }

    content_lower = content.lower()
    family_keywords = (corpus_payload or {}).get("family_keywords", FAMILY_KEYWORDS)
    control_keywords = (corpus_payload or {}).get("control_keywords", CONTROL_KEYWORDS)

    # Score each control
    control_scores: dict[str, float] = {}
    matched_phrases: dict[str, list[str]] = {}

    # Family-level pass first
    family_matches: dict[str, list[str]] = {}
    for family, keywords in family_keywords.items():
        hits = [kw for kw in keywords if kw in content_lower]
        if hits:
            family_matches[family] = hits

    # Control-specific pass
    for control_id, keywords in control_keywords.items():
        family = control_id.split("-")[0]
        family_bonus = 0.05 if family in family_matches else 0.0

        hits = [kw for kw in keywords if kw in content_lower]
        if not hits and family not in family_matches:
            continue

        # Score = hits/total_keywords, normalized + family bonus
        specific_score = len(hits) / max(len(keywords), 1)
        total_score = min(1.0, specific_score * 2.0 + family_bonus)

        if total_score > 0.05:  # minimum signal
            control_scores[control_id] = total_score
            matched_phrases[control_id] = hits

    if not control_scores:
        # Check if any family keywords matched even without specific control match
        if family_matches:
            # Map family matches to all controls in that family
            for family, hits in family_matches.items():
                for cid in control_keywords:
                    if cid.startswith(family + "-") and cid not in control_scores:
                        control_scores[cid] = 0.06
                        matched_phrases[cid] = hits

    if not control_scores:
        return {
            "relevance_score": 0.0,
            "candidate_controls": [],
            "candidate_enhancements": [],
            "rationale": "No keyword matches found",
            "above_threshold": False,
        }

    # Sort by score descending, take top 10
    sorted_controls = sorted(control_scores.items(), key=lambda x: x[1], reverse=True)[:10]
    top_score = sorted_controls[0][1] if sorted_controls else 0.0
    candidates = [cid for cid, _ in sorted_controls]

    # Build rationale from top matches
    top_phrases = []
    for cid, _ in sorted_controls[:3]:
        phrases = matched_phrases.get(cid, [])
        if phrases:
            top_phrases.extend(phrases[:2])
    rationale_phrases = list(dict.fromkeys(top_phrases))[:5]  # unique, max 5
    rationale = f"Matched: {', '.join(rationale_phrases)}" if rationale_phrases else "Family-level match"

    # Separate base controls from enhancements
    base_controls = [c for c in candidates if "(" not in c]
    enhancements = [c for c in candidates if "(" in c]

    return {
        "relevance_score": round(top_score, 4),
        "candidate_controls": base_controls,
        "candidate_enhancements": enhancements,
        "rationale": rationale,
        "above_threshold": top_score >= threshold,
    }
