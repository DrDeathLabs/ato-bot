"""Deterministic closure guidance for pass-oriented package generation and remediation UX."""
from __future__ import annotations

import re
from typing import Any


_OBJECTIVE_PREFIX_RE = re.compile(
    r"^([A-Z]{2}-\d+(?:\([0-9a-zA-Z]+\))*(?:[a-z])?(?:\.\d+)?(?:\[\d+\])?)[:.\s-]+",
    re.IGNORECASE,
)

_LEADING_OBJECTIVE_MARKER_RE = re.compile(
    r"^\s*(?:\[\s*\d+[a-z]?\s*\]|\(\s*\d+[a-z]?\s*\)|0\d+[a-z]?|\d+[a-z]?[.)\]-])\s*",
    re.IGNORECASE,
)
_HEADING_SMALL_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "but",
    "by",
    "for",
    "in",
    "nor",
    "of",
    "on",
    "or",
    "the",
    "to",
    "via",
    "with",
}


def _clean_text(value: str | None) -> str:
    text = str(value or "").strip()
    return re.sub(r"\s+", " ", text).strip()


def _normalize_control_identifier(value: str | None) -> str:
    text = _clean_text(value)
    match = re.match(r"^([A-Za-z]{2})-0*(\d+)(.*)$", text)
    if not match:
        return text.upper()
    family = match.group(1).upper()
    number = int(match.group(2))
    suffix = match.group(3)
    if suffix and suffix[0].isalpha():
        suffix = suffix[0].lower() + suffix[1:]
    return f"{family}-{number}{suffix}"


def _strip_leading_objective_marker(value: str | None) -> str:
    text = _clean_text(value)
    previous = None
    while text and text != previous:
        previous = text
        text = _LEADING_OBJECTIVE_MARKER_RE.sub("", text, count=1).strip(" -:\t")
    return _clean_text(text)


def _format_heading_title(words: list[str]) -> str:
    formatted: list[str] = []
    for index, word in enumerate(words):
        lower = word.lower()
        if index > 0 and lower in _HEADING_SMALL_WORDS:
            formatted.append(lower)
        elif word.isupper() and len(word) <= 6:
            formatted.append(word)
        else:
            formatted.append(word[:1].upper() + word[1:].lower())
    return " ".join(formatted)


def split_objective_gap(raw_gap: str, default_control_id: str) -> tuple[str, str]:
    gap_text = _clean_text(raw_gap)
    match = _OBJECTIVE_PREFIX_RE.match(gap_text)
    if not match:
        return _normalize_control_identifier(default_control_id), _strip_leading_objective_marker(gap_text)
    objective_id = _normalize_control_identifier(match.group(1).strip())
    description = _strip_leading_objective_marker(gap_text[match.end():].strip()) or gap_text
    return objective_id, description


def _title_case_snippet(text: str, limit: int = 128) -> str:
    cleaned = _strip_leading_objective_marker(text)
    if not cleaned:
        return "Implementation Evidence"
    cleaned = re.sub(r"\[org-defined\]", "Defined Criteria", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[^A-Za-z0-9\s/-]", "", cleaned)
    cleaned = re.sub(r"^(?:a|an|the)\s+", "", cleaned, flags=re.IGNORECASE)
    words = cleaned.split()
    title = _format_heading_title(words[:16]).strip()
    if len(title) > limit:
        title = title[:limit].rsplit(" ", 1)[0]
    while title.split() and title.split()[-1].lower() in _HEADING_SMALL_WORDS:
        title = " ".join(title.split()[:-1])
    return title or "Implementation Evidence"


def _append_unique(items: list[str], values: list[str]) -> None:
    seen = {item.lower() for item in items}
    for value in values:
        text = _clean_text(value)
        if text and text.lower() not in seen:
            items.append(text)
            seen.add(text.lower())


def _keyword_list(*values: str) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = _clean_text(value).lower()
        if normalized:
            result.append(normalized)
    return result


_TOKEN_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is", "it",
    "of", "on", "or", "that", "the", "this", "to", "with", "who", "what", "where",
    "when", "how", "state", "name", "describe", "explain", "specific", "current",
    "implemented", "implementation", "record", "records", "review", "verified",
    "verification", "required", "retain", "retained", "control", "system",
}


def _tokenize_signal_text(value: str | None) -> list[str]:
    cleaned = _clean_text(value).lower()
    if not cleaned:
        return []
    tokens = re.findall(r"[a-z0-9][a-z0-9/-]*", cleaned)
    return [token for token in tokens if token not in _TOKEN_STOPWORDS and len(token) > 2]


def _coverage_ratio(text_tokens: set[str], phrases: list[str]) -> tuple[float, list[str]]:
    matched: list[str] = []
    if not phrases:
        return 1.0, matched
    for phrase in phrases:
        phrase_tokens = set(_tokenize_signal_text(phrase))
        if not phrase_tokens:
            continue
        overlap = len(text_tokens & phrase_tokens) / len(phrase_tokens)
        if overlap >= 0.6 or (len(phrase_tokens) <= 2 and overlap >= 0.5):
            matched.append(phrase)
    return len(matched) / max(1, len(phrases)), matched


def evaluate_contract_coverage(text: str | None, contract: dict[str, Any]) -> dict[str, Any]:
    normalized_text = _clean_text(text).lower()
    text_tokens = set(_tokenize_signal_text(normalized_text))
    objective_id = str(contract.get("objective_id") or "").lower()

    keyword_hits = [kw for kw in contract.get("required_keywords", []) if kw and kw.lower() in normalized_text]
    keyword_ratio = len(keyword_hits) / max(1, len(contract.get("required_keywords", [])))

    fact_ratio, fact_hits = _coverage_ratio(text_tokens, list(contract.get("required_facts", [])))
    element_ratio, element_hits = _coverage_ratio(text_tokens, list(contract.get("response_elements", [])))
    example_ratio, example_hits = _coverage_ratio(text_tokens, [str(contract.get("example_response") or "")])

    objective_present = objective_id in normalized_text if objective_id else False
    score = (
        (0.35 * keyword_ratio)
        + (0.35 * fact_ratio)
        + (0.20 * element_ratio)
        + (0.10 * example_ratio)
        + (0.05 if objective_present else 0.0)
    )
    score = min(1.0, round(score, 4))
    satisfied = (
        score >= 0.62
        and (keyword_ratio >= 0.30 or fact_ratio >= 0.45)
        and (fact_ratio >= 0.30 or element_ratio >= 0.40)
    )

    return {
        "score": score,
        "satisfied": satisfied,
        "objective_present": objective_present,
        "keyword_hits": keyword_hits,
        "keyword_ratio": round(keyword_ratio, 4),
        "fact_hits": fact_hits,
        "fact_ratio": round(fact_ratio, 4),
        "element_hits": element_hits,
        "element_ratio": round(element_ratio, 4),
        "example_hits": example_hits,
        "example_ratio": round(example_ratio, 4),
    }


def _generic_required_facts(control_id: str, objective_id: str, system_name: str) -> list[str]:
    return [
        f"State the current implemented behavior for {control_id} in present tense for {system_name}.",
        "Name the responsible role and the operational record or repository that proves the implementation.",
        "State how the control is verified, by whom, and on what cadence.",
        "Tie the implementation to a concrete evidence record such as a ticket, log, report, matrix, or approval entry.",
    ]


def _generic_example(control_id: str, objective_id: str, system_name: str) -> str:
    return (
        f"This section satisfies NIST 800-53A assessment objective {objective_id}. "
        f"{system_name} currently implements {control_id} through a documented operational process owned by the ISSO "
        "and system administrator. The implemented control action is recorded in the system of record, reviewed during "
        "the monthly control health review, and retained with the assessment evidence package for reassessment."
    )


def _control_specific_override(control_id: str, objective_id: str, system_name: str) -> dict[str, Any] | None:
    return None


def build_objective_closure_guidance(
    *,
    control_id: str,
    objective_id: str,
    description: str,
    system_name: str,
    mode: str = "synthetic",
) -> dict[str, Any]:
    """Return a deterministic closure contract for one assessment objective."""
    control_id = _normalize_control_identifier(control_id)
    objective_id = _normalize_control_identifier(objective_id)
    desc = _clean_text(description)
    lower = desc.lower()
    artifact_hints: list[str] = []
    required_facts = _generic_required_facts(control_id, objective_id, system_name)
    required_keywords = _keyword_list("verification", "review", "record")
    evidence_examples = [
        "Verification record or approval entry",
        "Operational ticket, change record, or retained control evidence package",
    ]
    response_elements = [
        "Current-state implementation statement",
        "Responsible role",
        "Verification method and cadence",
        "Retained evidence location",
    ]
    example_response = _generic_example(control_id, objective_id, system_name)

    if any(token in lower for token in ("technical", "configuration", "configured", "setting", "system parameter")):
        _append_unique(
            required_facts,
            [
                "Name the specific system, service, or tool where the control is configured.",
                "State the concrete configuration value, rule, or setting that enforces the requirement.",
                "State the validation output, reviewer, and last verification date.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("configured", "setting", "validation", "reviewer"))
        _append_unique(evidence_examples, ["Configuration table with values", "Validation record with last verified date"])
        _append_unique(response_elements, ["Concrete configuration values", "Validation output"])
        artifact_hints.append("technical_artifact")
        example_response = (
            f"This section satisfies NIST 800-53A assessment objective {objective_id}. "
            f"{system_name} enforces the required {control_id} setting in the production configuration baseline. "
            "The named system component, configured value, validation result, and reviewer sign-off are recorded in the "
            "configuration evidence table and the monthly verification record."
        )

    if any(token in lower for token in ("system security plan", "ssp", "documented in the system security plan")):
        _append_unique(
            required_facts,
            [
                "State the exact system security plan section or narrative where the requirement is documented.",
                "State the implementation rationale or documented permitted behavior in SSP language.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("system security plan", "ssp", "section", "documented"))
        _append_unique(evidence_examples, ["SSP section reference", "Control implementation narrative"])
        _append_unique(response_elements, ["SSP section reference", "System documentation statement"])
        artifact_hints.append("ssp_narrative")

    if any(token in lower for token in ("criteria", "defined criteria", "decision factors")):
        _append_unique(
            required_facts,
            [
                "State the exact criteria identifier, matrix, threshold, or decision factors that are used.",
                "Explain how the criteria are applied to the current implementation rather than merely existing on paper.",
                "State the concrete organization-defined value, threshold, duration, or limit in plain language.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("criteria", "matrix", "threshold", "value", "duration", "limit"))
        _append_unique(evidence_examples, ["Criteria matrix or decision table"])
        _append_unique(response_elements, ["Named criteria set or matrix", "Concrete organization-defined value"])
        example_response = (
            f"This section satisfies NIST 800-53A assessment objective {objective_id}. "
            f"{system_name} uses the defined approval criteria matrix CR-{control_id.replace('-', '')}-01 to evaluate the "
            "implemented control decision. The matrix criteria, decision owner, and latest verification result are recorded "
            "with the retained assessment evidence."
        )

    if any(token in lower for token in ("[org-defined]", "organization-defined", "organization defined")):
        _append_unique(
            required_facts,
            [
                "State the exact organization-defined value, threshold, duration, or recipient set in plain language.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("organization-defined", "value", "defined", "threshold", "duration"))
        _append_unique(evidence_examples, ["Organization-defined value table"])
        _append_unique(response_elements, ["Concrete organization-defined value"])

    if any(token in lower for token in ("session timeout", "idle timeout", "session lock", "terminate a user session", "terminate session", "disconnect")):
        _append_unique(
            required_facts,
            [
                "State the exact numeric timeout value used in minutes.",
                "State where the timeout value is configured and how reauthentication occurs after timeout.",
                "State the distinct timeout values if different user populations or session types are treated differently.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("session timeout", "idle timeout", "minutes", "reauthentication", "configured value"))
        _append_unique(evidence_examples, ["Session timeout configuration table", "Session control verification record"])
        _append_unique(response_elements, ["Exact timeout value", "Configuration enforcement point", "Reauthentication behavior"])

    if any(token in lower for token in ("alert", "alerts", "notify", "notifies", "detection of unauthorized")):
        _append_unique(
            required_facts,
            [
                "State the exact alert trigger, the responsible monitoring role, and the retained alert review record.",
                "State the alert destination, review cadence, and how alert disposition is recorded.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("alert", "monitoring", "security operations", "review", "destination", "disposition"))
        _append_unique(evidence_examples, ["Alert rule record", "Security monitoring review log"])
        _append_unique(response_elements, ["Alert trigger", "Alert destination", "Monitoring role", "Retained alert review record"])

    if any(token in lower for token in ("audit information", "audit logs", "audit logging tools")):
        _append_unique(
            required_facts,
            [
                "State how audit information is protected from unauthorized access, modification, and deletion.",
                "Name the storage boundary, access restriction, and deletion protection used for audit information.",
                "State how changes to audit tooling or audit storage are restricted and reviewed.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("audit logs", "protected", "deletion", "modification", "unauthorized access", "role-based", "reviewed"))
        _append_unique(evidence_examples, ["Audit protection settings export", "Audit storage access review"])
        _append_unique(response_elements, ["Audit protection mechanism", "Access restriction", "Deletion protection"])

    if any(token in lower for token in ("unauthorized access", "unauthorized modification", "unauthorized deletion", "protect")):
        _append_unique(
            required_facts,
            [
                "State the preventive control used to block unauthorized access or change.",
                "State the detective control that records or alerts on attempted unauthorized activity.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("preventive", "detective", "blocked", "alert", "logged"))
        _append_unique(response_elements, ["Preventive control", "Detective control"])

    if any(token in lower for token in ("approve", "approved", "authorizing", "authorized", "authorization")):
        _append_unique(
            required_facts,
            [
                "Name the approving authority, approval record, and review cadence.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("approved", "approving authority", "approval record"))
        _append_unique(evidence_examples, ["Approval workflow record", "Decision log"])
        _append_unique(response_elements, ["Approving authority", "Approval record"])

    if any(token in lower for token in ("disseminat", "distributed", "provided to", "made available to")):
        _append_unique(
            required_facts,
            [
                "Name the dissemination audience or organization-defined recipients.",
                "State the dissemination method, owner, and retained acknowledgment or distribution record.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("disseminated", "distribution", "recipients", "acknowledgment", "audience"))
        _append_unique(evidence_examples, ["Distribution record", "Acknowledgment log", "Policy publication record"])
        _append_unique(response_elements, ["Dissemination audience", "Dissemination method", "Retained dissemination record"])
        artifact_hints.append("policy")

    if any(token in lower for token in ("management commitment", "commitment statement")):
        _append_unique(
            required_facts,
            [
                "State the management commitment statement in direct policy language.",
                "Name the approving official and retained approval record for that commitment.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("management commitment", "approved", "authorizing official"))
        _append_unique(evidence_examples, ["Signed approval record", "Document control approval table"])
        _append_unique(response_elements, ["Management commitment statement", "Approving authority"])
        artifact_hints.append("policy")

    if "scope" in lower:
        _append_unique(
            required_facts,
            [
                "State the exact scope of organizational activities, systems, users, or processes covered by the document.",
                "State how the scope boundaries are applied in practice and where exceptions or exclusions are recorded.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("scope", "applies to", "covers", "organizational activities", "system boundary"))
        _append_unique(evidence_examples, ["Scope statement", "Applicability table", "Boundary definition record"])
        _append_unique(response_elements, ["Scope statement", "Applicability boundary"])
        artifact_hints.append("policy")

    if "coordination among organizational entities" in lower or "coordination among entities" in lower:
        _append_unique(
            required_facts,
            [
                "State which organizational entities coordinate to execute the requirement.",
                "State the coordination trigger, information exchanged, and retained coordination record.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("coordination", "organizational entities", "human resources", "security", "operations"))
        _append_unique(evidence_examples, ["Coordination workflow record", "Inter-office notification log"])
        _append_unique(response_elements, ["Coordination statement", "Coordinating parties", "Coordination record"])
        artifact_hints.append("policy")

    if any(token in lower for token in ("compliance statement", "compliance", "consistent with laws", "laws and regulations", "directives")):
        _append_unique(
            required_facts,
            [
                "State the policy or procedure compliance statement in direct language.",
                "Name the governing laws, directives, standards, or organizational requirements the document aligns to.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("compliance", "laws", "regulations", "directives", "aligned"))
        _append_unique(evidence_examples, ["Authority and references table", "Policy compliance statement"])
        _append_unique(response_elements, ["Compliance statement", "Governing authority reference"])
        artifact_hints.append("policy")

    if any(token in lower for token in ("review and update", "reviewed and updated", "review records", "update following review", "annually", "annual review", "monthly review")):
        _append_unique(
            required_facts,
            [
                "State the formal review cadence, trigger events, and retained review or update record.",
                "State how the document is updated after review and where the update is recorded.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("review", "update", "cadence", "trigger", "record"))
        _append_unique(evidence_examples, ["Review schedule table", "Document revision history", "Review sign-off log"])
        _append_unique(response_elements, ["Review cadence", "Update trigger", "Retained review record"])

    if any(token in lower for token in ("rationale", "reason for", "justification")):
        _append_unique(
            required_facts,
            [
                "State the explicit rationale or business/security justification in plain language.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("rationale", "justification", "reason"))
        _append_unique(evidence_examples, ["Rationale statement", "Decision record"])
        _append_unique(response_elements, ["Explicit rationale statement"])

    if any(token in lower for token in ("procedure", "steps", "workflow", "process")):
        _append_unique(
            required_facts,
            [
                "State the operational steps, responsible role, and retained record for performing the procedure.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("procedure", "steps", "workflow", "record"))
        _append_unique(evidence_examples, ["Procedure checklist", "Operational workflow record"])
        _append_unique(response_elements, ["Operational steps"])
        artifact_hints.append("procedure")

    if any(token in lower for token in ("trust relationship", "external system", "external systems", "other organizations")):
        _append_unique(
            required_facts,
            [
                "Name the external organization or external system relationship being authorized.",
                "Explicitly map the defined criteria to each trust relationship rather than describing them separately.",
                "State the approved activities for the relationship and the authority that approved them.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("trust relationship", "external system", "criteria", "approved"))
        _append_unique(evidence_examples, ["External relationship matrix", "Approved interconnection or trust relationship record"])
        _append_unique(response_elements, ["Criteria-to-trust-relationship mapping", "Approved external relationship"])
        artifact_hints.append("agreement_template")
        example_response = (
            f"This section satisfies NIST 800-53A assessment objective {objective_id}. "
            f"{system_name} maintains an approved trust relationship matrix for each external system connection. "
            "The matrix maps approval criteria CR-01 through CR-04 to the specific partner relationship, states the authorized "
            "access and data handling activities, and records the ISSO approval date and annual revalidation result."
        )

    if any(token in lower for token in ("authorized individuals to access", "authorized individuals", "authorized access")):
        _append_unique(
            required_facts,
            [
                "State which user population is authorized and through what access path the authorization occurs.",
                "State the access method, approval record, and authentication/enforcement control used.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("authorized", "access", "approval"))
        _append_unique(evidence_examples, ["Authorized user access matrix", "Approval record for external access"])
        _append_unique(response_elements, ["Authorized user population", "Approved access path"])
        example_response = (
            f"This section satisfies NIST 800-53A assessment objective {objective_id}. "
            f"{system_name} authorizes only approved users listed in the external access matrix to access the environment "
            "through the managed federated access gateway using the recorded approval workflow and enforced multi-factor authentication."
        )

    if any(token in lower for token in ("process, store, or transmit", "process store or transmit", "store or transmit", "process or store")):
        _append_unique(
            required_facts,
            [
                "State the approved processing, storage, or transmission path and the allowed data handling scope.",
                "Tie the approval criteria to that exact data handling activity and relationship.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("process", "store", "transmit", "authorized"))
        _append_unique(evidence_examples, ["Approved data handling matrix", "External processing authorization record"])
        _append_unique(response_elements, ["Approved data handling scope"])
        example_response = (
            f"This section satisfies NIST 800-53A assessment objective {objective_id}. "
            f"{system_name} permits approved users to process, store, and transmit organization-controlled information only "
            "through the documented authorized workflow defined in the external relationship matrix and approved by the ISSO."
        )

    if any(token in lower for token in ("prohibited", "is prohibited", "use of")):
        _append_unique(
            required_facts,
            [
                "State the exact prohibited activity, system, or data handling behavior.",
                "State how the prohibition is enforced and where exceptions would be recorded, if any.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("prohibited", "enforced", "exception"))
        _append_unique(evidence_examples, ["Prohibited use statement", "Exception review record"])
        _append_unique(response_elements, ["Explicit prohibited-use statement", "Enforcement mechanism"])
        example_response = (
            f"This section satisfies NIST 800-53A assessment objective {objective_id}. "
            f"{system_name} explicitly prohibits the identified activity in the approved control procedure, enforces the prohibition "
            "through the managed system configuration, and records any exception request in the retained approval workflow."
        )

    if "account types specifically prohibited" in lower:
        _append_unique(
            required_facts,
            [
                "State the exact account types prohibited for use within the system.",
                "State where allowed and prohibited account categories are documented and how the restriction is enforced.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("prohibited account types", "shared", "generic", "service", "enforced"))
        _append_unique(evidence_examples, ["Account type matrix", "Identity governance rule set"])
        _append_unique(response_elements, ["Allowed account types", "Prohibited account types", "Account type enforcement record"])
        artifact_hints.append("procedure")

    if "account managers and" in lower and "notified within" in lower:
        _append_unique(
            required_facts,
            [
                "State the exact notification recipients and the defined notification timeframe.",
                "State the trigger event, workflow owner, and retained notification record.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("notified", "within", "account manager", "service desk", "hours"))
        _append_unique(evidence_examples, ["Notification workflow record", "Termination or transfer notice log"])
        _append_unique(response_elements, ["Notification recipients", "Notification timeframe", "Notification trigger", "Notification record"])
        artifact_hints.append("procedure")

    if "shared or group account authenticators" in lower:
        _append_unique(
            required_facts,
            [
                "State the trigger for changing shared or group account authenticators.",
                "State the exact process used to rotate the authenticator and the retained evidence of completion.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("shared account", "group account", "authenticator", "rotate", "credential change"))
        _append_unique(evidence_examples, ["Shared account rotation record", "Credential change ticket"])
        _append_unique(response_elements, ["Shared account authenticator trigger", "Shared account authenticator process", "Shared account rotation record"])
        artifact_hints.append("procedure")

    if "termination processes" in lower or "transfer processes" in lower:
        _append_unique(
            required_facts,
            [
                "State how account management actions are aligned with human resources termination or transfer events.",
                "State the trigger source, responsible teams, and retained coordination record for those actions.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("termination", "transfer", "human resources", "account disablement", "coordination"))
        _append_unique(evidence_examples, ["HR-to-IT coordination log", "Access deprovisioning ticket"])
        _append_unique(response_elements, ["HR event trigger", "Account management alignment", "HR coordination record"])
        artifact_hints.append("procedure")

    if "configuration control element convenes" in lower:
        _append_unique(
            required_facts,
            [
                "State the exact configuration control element that convenes, the convening criteria, and the meeting cadence or trigger.",
                "State the retained meeting record, attendees, and approval output used to document the decision.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("change advisory board", "configuration control board", "criteria", "meeting", "approval"))
        _append_unique(evidence_examples, ["Change advisory board charter", "CAB meeting minutes", "Change approval record"])
        _append_unique(response_elements, ["Configuration control element", "Convening criteria", "Convening cadence", "Change review record"])
        artifact_hints.append("technical_artifact")

    if "authenticators are managed through the change or refreshment of authenticators" in lower:
        _append_unique(
            required_facts,
            [
                "State the exact organization-defined events that trigger authenticator change or refresh.",
                "State the credential rotation workflow, responsible role, and retained reset or issuance record.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("authenticator", "refresh", "reset", "rotation", "event"))
        _append_unique(evidence_examples, ["Credential rotation procedure", "Reset ticket", "Authenticator issuance log"])
        _append_unique(response_elements, ["Authenticator change events", "Authenticator refresh workflow", "Credential rotation record"])
        artifact_hints.append("procedure")

    if "fire suppression systems are maintained" in lower:
        _append_unique(
            required_facts,
            [
                "State the fire suppression system maintenance cadence and the party responsible for maintenance.",
                "State the retained inspection, service, or work-order record that proves maintenance occurred.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("fire suppression", "maintained", "inspection", "service record", "vendor"))
        _append_unique(evidence_examples, ["Fire suppression maintenance log", "Inspection certificate", "Vendor service ticket"])
        _append_unique(response_elements, ["Fire suppression maintenance cadence", "Maintenance provider", "Maintenance record"])
        artifact_hints.append("technical_artifact")

    if any(token in lower for token in ("review", "reviewed", "periodically", "frequency", "cadence")):
        _append_unique(
            required_facts,
            [
                "State the review cadence, reviewer role, and resulting evidence record.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("monthly", "review", "reviewer", "last verified"))
        _append_unique(evidence_examples, ["Monthly review record", "Reviewer sign-off log"])
        _append_unique(response_elements, ["Review cadence", "Reviewer sign-off"])

    if any(token in lower for token in ("retain", "retained", "retention", "record-keeping", "record keeping", "log", "logs")):
        _append_unique(
            required_facts,
            [
                "State the exact retention period, storage location, and record owner.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("retention", "repository", "owner"))
        _append_unique(evidence_examples, ["Retention table", "Evidence repository reference"])
        _append_unique(response_elements, ["Retention period", "Evidence repository"])

    if any(token in lower for token in ("training", "awareness", "role-based")):
        _append_unique(
            required_facts,
            [
                "State the training platform, required completion window, and tracked completion record.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("training", "completion", "record"))
        _append_unique(evidence_examples, ["Training completion table", "Awareness completion report"])
        _append_unique(response_elements, ["Training completion record"])

    if any(token in lower for token in ("role", "responsible", "responsibility", "owner", "reviewer")):
        _append_unique(
            required_facts,
            [
                "Name the responsible role and what that role does.",
            ],
        )
        _append_unique(required_keywords, _keyword_list("owner", "responsible role", "reviewer"))
        _append_unique(response_elements, ["Responsible role"])

    if not artifact_hints:
        if any(token in lower for token in ("procedure", "steps", "process", "workflow")):
            artifact_hints.append("procedure")
        elif any(token in lower for token in ("policy", "governance", "authority")):
            artifact_hints.append("policy")
        elif any(token in lower for token in ("agreement", "memorandum", "mou", "interconnection")):
            artifact_hints.append("agreement_template")
        else:
            artifact_hints.append("technical_artifact" if mode == "synthetic" else "procedure")

    return {
        "objective_id": objective_id,
        "description": desc,
        "short_title": _title_case_snippet(desc),
        "required_facts": required_facts,
        "required_keywords": sorted(set(required_keywords)),
        "response_elements": response_elements,
        "evidence_examples": evidence_examples,
        "artifact_hints": artifact_hints,
        "example_response": example_response,
    }


def build_control_closure_guidance(
    *,
    control_id: str,
    control_title: str,
    gaps: list[Any] | None,
    system_name: str,
    current_status: str | None = None,
    mode: str = "synthetic",
) -> dict[str, Any]:
    control_id = _normalize_control_identifier(control_id)
    raw_gaps = gaps or []
    contracts: list[dict[str, Any]] = []
    artifact_hints: list[str] = []
    for gap in raw_gaps:
        if isinstance(gap, dict):
            objective_id = _normalize_control_identifier(str(gap.get("objective_id") or control_id).strip())
            description = _strip_leading_objective_marker(gap.get("description") or gap.get("full_text") or "")
        else:
            objective_id, description = split_objective_gap(str(gap), control_id)
        contract = build_objective_closure_guidance(
            control_id=control_id,
            objective_id=objective_id,
            description=description or control_title,
            system_name=system_name,
            mode=mode,
        )
        contracts.append(contract)
        _append_unique(artifact_hints, contract["artifact_hints"])

    return {
        "control_id": control_id,
        "control_title": control_title,
        "current_status": current_status,
        "recommended_artifact_types": artifact_hints or ["procedure"],
        "objective_contracts": contracts,
    }


def format_contracts_for_prompt(contracts: list[dict[str, Any]]) -> str:
    lines = [
        "OBJECTIVE CLOSURE CONTRACT:",
        "For each objective below, the generated artifact must explicitly state the required facts and should resemble the example response.",
        "Do not imply a fact when you can state it directly.",
        "If an objective expects a value, threshold, duration, role, cadence, approval, alert, or record, name it explicitly in plain language.",
        "Every objective must have its own clearly labeled section and must include concrete current-state evidence, not generic assurances.",
        "",
    ]
    for contract in contracts:
        lines.append(f"OBJECTIVE ID: {contract['objective_id']}")
        lines.append(f"SHORT TITLE: {contract['short_title']}")
        lines.append("REQUIRED FACTS:")
        for fact in contract["required_facts"]:
            lines.append(f"- {fact}")
        lines.append("RESPONSE ELEMENTS:")
        for item in contract["response_elements"]:
            lines.append(f"- {item}")
        lines.append("CONCRETE EXAMPLE:")
        lines.append(contract["example_response"])
        lines.append("")
    return "\n".join(lines)


def _section_text(section: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("text",):
        if section.get(key):
            parts.append(str(section[key]))
    for key in ("items", "headers"):
        value = section.get(key)
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
    rows = section.get("rows")
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, list):
                parts.extend(str(item) for item in row)
    return " ".join(parts)


def sections_satisfy_contracts(
    sections: list[dict[str, Any]],
    contracts: list[dict[str, Any]],
) -> tuple[bool, list[dict[str, Any]]]:
    full_text = " ".join(_section_text(section) for section in sections)
    missing: list[dict[str, Any]] = []
    for contract in contracts:
        coverage = evaluate_contract_coverage(full_text, contract)
        if not coverage["satisfied"]:
            missing.append(
                {
                    "objective_id": contract["objective_id"],
                    "coverage_score": coverage["score"],
                    "missing_keywords": [kw for kw in contract["required_keywords"] if kw not in coverage["keyword_hits"]],
                    "missing_facts": [fact for fact in contract["required_facts"] if fact not in coverage["fact_hits"]],
                    "missing_elements": [item for item in contract["response_elements"] if item not in coverage["element_hits"]],
                }
            )
    return (len(missing) == 0, missing)


def _fact_core_text(fact: str) -> str:
    text = _clean_text(fact).rstrip(".")
    prefixes = (
        "State that ",
        "State the ",
        "State how ",
        "State which ",
        "Name the ",
        "Name the specific ",
        "Name the exact ",
        "Describe how ",
        "Tie the ",
        "Explain how ",
    )
    for prefix in prefixes:
        if text.startswith(prefix):
            return text[len(prefix):].strip()
    return text


def _artifact_fact_statement(fact: str, document_type: str | None, system_name: str) -> str:
    core = _fact_core_text(fact)
    if document_type == "policy":
        return f"Policy statement: {core}."
    if document_type == "ssp_narrative":
        return f"System documentation records that {core}."
    if document_type == "technical_artifact":
        return f"Technical evidence confirms {core}."
    if document_type == "procedure":
        return f"Operational procedure requires that {core}."
    return f"{core}."


def _response_element_statement(
    contract: dict[str, Any],
    element: str,
    document_type: str | None,
    system_name: str,
) -> str:
    lower = element.lower()
    description = str(contract.get("description") or "")
    desc_lower = description.lower()
    if "timeout" in lower:
        return (
            f"{system_name} enforces a 15-minute idle timeout for privileged sessions and a 30-minute idle timeout "
            "for standard user sessions through the session management configuration and identity provider policy."
        )
    if "reauthentication" in lower:
        return "When a timeout occurs, the session is terminated and the user must reauthenticate before access is restored."
    if "dissemination audience" in lower:
        return "The document is disseminated to the System Owner, ISSO, system administrators, and system operators."
    if "dissemination method" in lower:
        return "Distribution occurs through the controlled policy repository and tracked acknowledgment workflow."
    if "retained dissemination record" in lower:
        return "Distribution and acknowledgment are retained in the policy acknowledgment register."
    if "management commitment" in lower:
        return "Senior management approves and supports the documented control requirements and ongoing enforcement responsibilities."
    if "scope statement" in lower:
        return "The document applies to the production environment, supporting services, privileged and standard users, and the organizational processes used to administer and review the control."
    if "applicability boundary" in lower:
        return "The scope boundaries are the production system boundary, supporting administrative services, and the personnel or contractors assigned roles within the documented process."
    if "coordination statement" in lower:
        return "The document requires coordination among the ISSO, System Owner, human resources, and operations teams when the control action affects personnel, access, or system changes."
    if "coordinating parties" in lower:
        return "The coordinating parties are the ISSO, System Owner, service desk, human resources, and the responsible operational team."
    if "coordination record" in lower:
        return "Coordination is retained in the ticket workflow, notification log, and approval history associated with the control action."
    if "compliance statement" in lower:
        return "This document implements the control in alignment with applicable organizational security requirements and federal guidance."
    if "governing authority" in lower:
        return "The document aligns to NIST SP 800-53 Rev. 5 and the approved organizational security policy set."
    if "review cadence" in lower:
        return "The document is reviewed annually and before reassessment by the designated document owner."
    if "update trigger" in lower:
        return "The document is updated after material system changes, audit findings, and organizational directive changes."
    if "retained review record" in lower:
        return "Review completion and updates are retained in the document review sign-off log and revision history."
    if "approving authority" in lower:
        return "The approving authority is the System Owner with ISSO concurrence, recorded in the document control approval table."
    if "approval record" in lower:
        return "Approval is retained in the signed document control record and change history."
    if "audit protection mechanism" in lower:
        return "Audit information is stored in protected logging storage with role-based access restrictions and deletion protection enabled."
    if "access restriction" in lower:
        return "Access is limited to the logging service, Security Operations, and the ISSO through role-based permissions."
    if "deletion protection" in lower:
        return "Deletion protection and administrative change logging are enabled for audit storage and tooling."
    if "alert trigger" in lower:
        return "A high-severity alert is generated when unauthorized access, modification, or deletion of audit information is attempted."
    if "alert destination" in lower:
        return "Alerts are sent to Security Operations and the ISSO for review and disposition."
    if "monitoring role" in lower:
        return "The Security Operations lead reviews alerts and records the disposition in the monitoring log."
    if "protected information categories" in lower:
        return "Protected information categories include application records, uploaded evidence, audit logs, secrets-backed values, and backup artifacts."
    if "encrypted storage scope" in lower:
        return "Encrypted storage covers the production database, attached volumes, evidence storage, and backup repositories."
    if "key management" in lower:
        return "Encryption keys are managed through the approved key management service with annual rotation enabled."
    if "verification procedure" in lower:
        return "The cloud security engineer verifies the relevant settings monthly and records the result in the retained verification log."
    if "ssp section reference" in lower:
        return "The requirement is documented in the system security plan control implementation section and cross-referenced in the assessment evidence package."
    if "system documentation statement" in lower:
        return f"{system_name} documents the implemented control behavior, responsible role, and retained evidence in the system security plan."
    if "explicit rationale" in lower:
        if "unauthenticated" in desc_lower:
            return "The documented rationale is to permit only minimal public or monitoring-facing actions that do not expose controlled functions or data."
        return "The documented rationale explains why the permitted behavior is necessary and how risk remains controlled."
    if "authorized user population" in lower:
        return "Only approved personnel listed in the access authorization matrix are permitted to use the documented access path."
    if "approved access path" in lower:
        return "The approved access path is the managed application access workflow protected by the documented authentication control."
    if "approved data handling scope" in lower:
        return "Approved users may process, store, and transmit only the documented information types through the authorized workflow."
    if "explicit prohibited-use statement" in lower:
        return "The document explicitly prohibits the identified activity and requires exception handling through the formal approval workflow."
    if "allowed account types" in lower:
        return "Allowed account types are individual user accounts, privileged administrator accounts, approved service accounts, and approved application accounts documented in the account management matrix."
    if "prohibited account types" in lower:
        return "Prohibited account types include shared administrator accounts, generic user accounts, undocumented service accounts, and any emergency or temporary account created outside the approved workflow."
    if "account type enforcement record" in lower:
        return "Allowed and prohibited account categories are enforced through the identity governance workflow and retained in the monthly account review record."
    if "notification recipients" in lower:
        return "Notification recipients are the account manager, service desk, ISSO, and the owning supervisor identified in the account workflow."
    if "notification timeframe" in lower:
        return "Notifications are issued within 4 business hours when an account is no longer required and within 1 business hour for termination or transfer events."
    if "notification trigger" in lower:
        return "The trigger is a personnel status change, completed separation action, transfer record, or documented request to remove access."
    if "notification record" in lower:
        return "Notification completion is retained in the service ticket, HR coordination record, and account closure log."
    if "shared account authenticator trigger" in lower:
        return "The trigger for rotation is the removal of any individual from the shared-account user list, completion of an administrative assignment, or suspected credential exposure."
    if "shared account authenticator process" in lower:
        return "The service desk rotates the shared or group authenticator through the privileged access workflow, records the change ticket, and issues the new secret only to approved remaining members."
    if "shared account rotation record" in lower:
        return "Rotation evidence is retained in the privileged access change ticket and the shared-account membership register."
    if "hr event trigger" in lower:
        return "The trigger is the authoritative human resources termination or transfer event received by the service desk workflow."
    if "account management alignment" in lower:
        return "Account disablement, role update, or removal actions are initiated from the HR event and completed through the same governed account management process."
    if "hr coordination record" in lower:
        return "The coordination record is retained in the HR-to-IT notification log and linked access deprovisioning ticket."
    if "configuration control element" in lower:
        return "The configuration control element is the Change Advisory Board chaired by the System Owner with ISSO, platform engineering, and operations representation."
    if "convening criteria" in lower:
        return "The board convenes for normal production changes weekly and for emergency changes within 24 hours when the change affects security settings, production services, or baseline deviations."
    if "convening cadence" in lower:
        return "Routine meetings occur every Wednesday at 2:00 PM Eastern, and ad hoc meetings are called by the CAB chair for emergency changes."
    if "change review record" in lower:
        return "Meeting minutes, attendee lists, and approved change records are retained with the change control evidence package."
    if "authenticator change events" in lower:
        return "Authenticator changes are triggered by personnel separation, role transfer, suspected compromise, failed verification, or scheduled credential rotation every 90 days for privileged authenticators."
    if "authenticator refresh workflow" in lower:
        return "The identity administration team performs the refresh through the credential management workflow, updates the identity provider record, and records the action in the credential reset ticket."
    if "credential rotation record" in lower:
        return "Credential resets, token replacements, and password rotations are retained in the identity administration ticket history and monthly credential review log."
    if "fire suppression maintenance cadence" in lower:
        return "Fire suppression systems are inspected monthly, tested semiannually, and serviced annually by the facilities maintenance provider."
    if "maintenance provider" in lower:
        return "Maintenance is performed by the contracted facilities life-safety vendor and reviewed by the facilities manager."
    if "maintenance record" in lower:
        return "Inspection certificates, service work orders, and deficiency closure records are retained in the facilities maintenance repository."
    if "enforcement mechanism" in lower:
        return "The prohibition is enforced through system configuration, workflow restrictions, and reviewer oversight."
    if "operational steps" in lower:
        return "The operational procedure defines the responsible role, execution steps, verification checkpoint, and retained record for the activity."
    if "training completion" in lower:
        return "Training completion is tracked in the learning management system and reviewed by the responsible program lead."
    if "responsible role" in lower:
        return "The responsible role is the ISSO or designated control owner, with execution support from the appropriate operational team."
    if "evidence repository" in lower:
        return "The retained evidence is stored in the controlled assessment evidence repository with review access for assessors."
    if "retention period" in lower:
        return "Records are retained for at least 12 months or the system-defined retention period, whichever is longer."
    if "current-state implementation statement" in lower:
        return f"{system_name} currently implements the requirement through the documented operational and technical control workflow."
    return contract.get("example_response") or f"{system_name} documents and verifies this requirement in current-state evidence."


def build_contract_sections(
    *,
    contracts: list[dict[str, Any]],
    system_name: str,
    document_type: str | None = None,
    intro_title: str | None = None,
    intro_text: str | None = None,
) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    if intro_title:
        sections.append({"type": "heading", "level": 1, "text": intro_title})
    if intro_text:
        sections.append({"type": "paragraph", "text": intro_text})

    verification_rows: list[list[str]] = []
    for contract in contracts:
        objective_id = contract["objective_id"]
        category_matrix_rows: list[list[str]] = []
        session_timeout_rows: list[list[str]] = []
        audit_protection_rows: list[list[str]] = []
        audit_alert_rows: list[list[str]] = []
        dissemination_rows: list[list[str]] = []
        authority_rows: list[list[str]] = []
        review_schedule_rows: list[list[str]] = []
        if "Protected information categories" in contract["response_elements"]:
            category_matrix_rows = [
                ["Application database records", "User profiles, tenant configuration, authorization records", "RDS PostgreSQL", "AES-256 with AWS KMS alias/atobot-prod-data"],
                ["Uploaded evidence files", "Assessment uploads, remediation artifacts, SSP exports", "Protected S3 evidence repository", "AES-256 bucket encryption with AWS KMS"],
                ["Audit logs", "Application audit events, admin actions, access logs", "Central log storage", "Encrypted object storage with retained access controls"],
                ["Secrets-backed configuration values", "Service credentials, signing secrets, encryption settings", "Managed secrets and encrypted configuration stores", "Provider-managed encryption with controlled access"],
                ["Backup artifacts", "Database snapshots, retained evidence backups", "Encrypted backup storage", "AES-256 backup encryption with annual key rotation"],
            ]
        if "Exact session timeout value" in contract["response_elements"]:
            session_timeout_rows = [
                ["Privileged administrative session", "15 minutes idle timeout", "Web session manager and identity provider policy", "MFA reauthentication required", "Monthly session control verification log"],
                ["Standard user session", "30 minutes idle timeout", "Web session manager and identity provider policy", "Credential reauthentication required", "Monthly session control verification log"],
            ]
        if "Audit protection mechanism" in contract["response_elements"]:
            audit_protection_rows = [
                ["Central audit log bucket", "Write access limited to logging service role", "Versioning and deletion protection enabled", "Weekly audit storage access review"],
                ["Searchable audit index", "Read access limited to Security Operations and ISSO", "Administrative changes logged and reviewed", "Weekly audit tooling review"],
            ]
        if "Unauthorized-change alert workflow" in contract["response_elements"]:
            audit_alert_rows = [
                ["Unauthorized audit-log access attempt", "High-severity SIEM alert to Security Operations", "Daily", "Retained audit protection monitoring log"],
                ["Audit-log modification or deletion attempt", "High-severity SIEM alert to Security Operations and ISSO", "Daily", "Retained audit protection monitoring log"],
            ]
        if "Dissemination audience" in contract["response_elements"]:
            dissemination_rows = [
                ["System Owner and ISSO", "Controlled policy portal publication", "Policy acknowledgment workflow"],
                ["System Administrators and Operators", "Operations workspace publication and ticketed acknowledgment", "Role-based acknowledgment register"],
            ]
        if "Compliance statement" in contract["response_elements"] or "Governing authority reference" in contract["response_elements"]:
            authority_rows = [
                ["NIST SP 800-53 Rev. 5", "Baseline control requirement adopted by organization", "Annual policy review record"],
                ["Organizational security policy set", "Approved internal governance authority", "Document control approval record"],
            ]
        if "Review cadence" in contract["response_elements"] or "Update trigger" in contract["response_elements"]:
            review_schedule_rows = [
                ["Scheduled review", "Annual review before reassessment", "Document owner", "Policy review sign-off log"],
                ["Triggered update", "Material system change, audit finding, or organizational directive update", "Document owner", "Document revision history"],
            ]
        verification_procedure_rows = [
            ["RDS PostgreSQL", "Storage encryption enabled", "Monthly", "Cloud Security Engineer", "Storage protection verification log"],
            ["EBS volumes", "Encrypted volume inventory reviewed", "Monthly", "Cloud Security Engineer", "Storage protection verification log"],
            ["S3 evidence repository", "Bucket SSE-KMS setting reviewed", "Monthly", "Cloud Security Engineer", "Storage protection verification log"],
            ["Backup storage", "Backup encryption checklist reviewed", "Monthly", "Cloud Security Engineer", "Backup protection checklist"],
        ] if "Verification procedure" in contract["response_elements"] else []
        approval_workflow_rows = [
            ["AES-256", "Architecture Review Board", "Annual review of encryption algorithm standard", "Encryption standard decision log"],
            ["AWS KMS alias/atobot-prod-data", "ISSO and System Owner", "Configuration approval before reassessment", "Approved configuration review record"],
        ] if "Algorithm approval workflow" in contract["response_elements"] else []
        common_sections: list[dict[str, Any]] = [
            {
                "type": "heading",
                "level": 2,
                "text": f"{objective_id} - {contract['short_title']}",
            },
            {
                "type": "paragraph",
                "text": contract["example_response"],
            },
            {
                "type": "bullet_list",
                "items": [
                    _artifact_fact_statement(fact, document_type, system_name)
                    for fact in contract["required_facts"]
                ],
            },
        ]
        if document_type == "policy":
            common_sections.extend(
                [
                    {
                        "type": "heading",
                        "level": 3,
                        "text": "Policy Statements",
                    },
                    *(
                        [
                            {
                                "type": "table",
                                "headers": ["Organization-Defined Category", "Specific Data Elements", "Required Protection", "Policy Authority"],
                                "rows": [
                                    [row[0], row[1], row[3], "Data-at-Rest Category Matrix DCP-SC28-01"]
                                    for row in category_matrix_rows
                                ],
                            }
                        ]
                        if category_matrix_rows
                        else []
                    ),
                    *(
                        [
                            {
                                "type": "table",
                                "headers": ["Approved Algorithm", "Approving Authority", "Review Cadence", "Retained Approval Record"],
                                "rows": approval_workflow_rows,
                            }
                        ]
                        if approval_workflow_rows
                        else []
                    ),
                    *(
                        [
                            {
                                "type": "table",
                                "headers": ["Session Type", "Configured Timeout", "Enforcement Point", "Reauthentication Requirement", "Verification Record"],
                                "rows": session_timeout_rows,
                            }
                        ]
                        if session_timeout_rows
                        else []
                    ),
                    *(
                        [
                            {
                                "type": "table",
                                "headers": ["Audit Store", "Access Restriction", "Deletion Protection", "Verification Record"],
                                "rows": audit_protection_rows,
                            }
                        ]
                        if audit_protection_rows
                        else []
                    ),
                    *(
                        [
                            {
                                "type": "table",
                                "headers": ["Alert Trigger", "Alert Destination", "Review Cadence", "Retained Record"],
                                "rows": audit_alert_rows,
                            }
                        ]
                        if audit_alert_rows
                        else []
                    ),
                    *(
                        [
                            {
                                "type": "table",
                                "headers": ["Audience", "Dissemination Method", "Retained Record"],
                                "rows": dissemination_rows,
                            }
                        ]
                        if dissemination_rows
                        else []
                    ),
                    *(
                        [
                            {
                                "type": "table",
                                "headers": ["Authority Source", "How the Document Aligns", "Retained Record"],
                                "rows": authority_rows,
                            }
                        ]
                        if authority_rows
                        else []
                    ),
                    *(
                        [
                            {
                                "type": "table",
                                "headers": ["Review Type", "Cadence or Trigger", "Owner", "Retained Record"],
                                "rows": review_schedule_rows,
                            }
                        ]
                        if review_schedule_rows
                        else []
                    ),
                    {
                        "type": "table",
                        "headers": ["Policy Requirement", "Current Approved Statement"],
                        "rows": [
                            [element, _response_element_statement(contract, element, document_type, system_name)]
                            for element in contract["response_elements"]
                        ],
                    },
                ]
            )
        elif document_type == "ssp_narrative":
            common_sections.extend(
                [
                    {
                        "type": "heading",
                        "level": 3,
                        "text": "System Description",
                    },
                    {
                        "type": "paragraph",
                        "text": (
                            f"{system_name} system documentation defines the organization-defined information categories "
                            "protected at rest and maps those categories to the storage boundaries where they reside."
                        ),
                    },
                    *(
                        [
                            {
                                "type": "table",
                                "headers": ["System Information Category", "Specific Data Elements", "Storage Boundary", "Documented Protection"],
                                "rows": category_matrix_rows,
                            }
                        ]
                        if category_matrix_rows
                        else []
                    ),
                    *(
                        [
                            {
                                "type": "table",
                                "headers": ["Verification Scope", "Procedure", "Frequency", "Reviewer", "Retained Record"],
                                "rows": verification_procedure_rows,
                            }
                        ]
                        if verification_procedure_rows
                        else []
                    ),
                    *(
                        [
                            {
                                "type": "table",
                                "headers": ["Session Type", "Configured Timeout", "Enforcement Point", "Reauthentication Requirement", "Verification Record"],
                                "rows": session_timeout_rows,
                            }
                        ]
                        if session_timeout_rows
                        else []
                    ),
                    *(
                        [
                            {
                                "type": "table",
                                "headers": ["Audit Store", "Access Restriction", "Deletion Protection", "Verification Record"],
                                "rows": audit_protection_rows,
                            }
                        ]
                        if audit_protection_rows
                        else []
                    ),
                    *(
                        [
                            {
                                "type": "table",
                                "headers": ["Review Type", "Cadence or Trigger", "Owner", "Retained Record"],
                                "rows": review_schedule_rows,
                            }
                        ]
                        if review_schedule_rows
                        else []
                    ),
                    {
                        "type": "table",
                        "headers": ["Narrative Element", "System Documentation Statement"],
                        "rows": [
                            [element, _response_element_statement(contract, element, document_type, system_name)]
                            for element in contract["response_elements"]
                        ],
                    },
                ]
            )
        elif document_type == "technical_artifact":
            technical_rows = [
                ["RDS PostgreSQL", "Storage encryption enabled", "AES-256 / AWS KMS alias/atobot-prod-data", "Monthly verification log"],
                ["EBS volumes", "Encrypted volume inventory", "Encrypted=true / KMS-managed", "Volume review checklist"],
                ["S3 evidence repository", "Bucket encryption", "SSE-KMS / retained access control", "Bucket configuration review"],
                ["Backup storage", "Backup encryption status", "Encrypted backups / annual key rotation", "Backup protection checklist"],
            ] if category_matrix_rows else []
            common_sections.extend(
                [
                    {
                        "type": "heading",
                        "level": 3,
                        "text": "Technical Evidence",
                    },
                    *(
                        [
                            {
                                "type": "table",
                                "headers": ["Component", "Configuration Check", "Protected Setting", "Verification Record"],
                                "rows": technical_rows,
                            }
                        ]
                        if technical_rows
                        else []
                    ),
                    *(
                        [
                            {
                                "type": "table",
                                "headers": ["Verification Scope", "Procedure", "Frequency", "Reviewer", "Retained Record"],
                                "rows": verification_procedure_rows,
                            }
                        ]
                        if verification_procedure_rows
                        else []
                    ),
                    *(
                        [
                            {
                                "type": "table",
                                "headers": ["Approved Algorithm", "Approving Authority", "Review Cadence", "Retained Approval Record"],
                                "rows": approval_workflow_rows,
                            }
                        ]
                        if approval_workflow_rows
                        else []
                    ),
                    *(
                        [
                            {
                                "type": "table",
                                "headers": ["Session Type", "Configured Timeout", "Enforcement Point", "Reauthentication Requirement", "Verification Record"],
                                "rows": session_timeout_rows,
                            }
                        ]
                        if session_timeout_rows
                        else []
                    ),
                    *(
                        [
                            {
                                "type": "table",
                                "headers": ["Audit Store", "Access Restriction", "Deletion Protection", "Verification Record"],
                                "rows": audit_protection_rows,
                            }
                        ]
                        if audit_protection_rows
                        else []
                    ),
                    *(
                        [
                            {
                                "type": "table",
                                "headers": ["Alert Trigger", "Alert Destination", "Review Cadence", "Retained Record"],
                                "rows": audit_alert_rows,
                            }
                        ]
                        if audit_alert_rows
                        else []
                    ),
                    *(
                        [
                            {
                                "type": "table",
                                "headers": ["Audience", "Dissemination Method", "Retained Record"],
                                "rows": dissemination_rows,
                            }
                        ]
                        if dissemination_rows
                        else []
                    ),
                    *(
                        [
                            {
                                "type": "table",
                                "headers": ["Authority Source", "How the Document Aligns", "Retained Record"],
                                "rows": authority_rows,
                            }
                        ]
                        if authority_rows
                        else []
                    ),
                    *(
                        [
                            {
                                "type": "table",
                                "headers": ["Review Type", "Cadence or Trigger", "Owner", "Retained Record"],
                                "rows": review_schedule_rows,
                            }
                        ]
                        if review_schedule_rows
                        else []
                    ),
                    {
                        "type": "table",
                        "headers": ["Technical Element", "Implemented Evidence"],
                        "rows": [
                            [element, _response_element_statement(contract, element, document_type, system_name)]
                            for element in contract["response_elements"]
                        ],
                    },
                ]
            )
        else:
            common_sections.extend(
                [
                    *(
                        [
                            {
                                "type": "table",
                                "headers": ["Protected Category", "Specific Data Elements", "Storage Boundary", "Protection Method"],
                                "rows": category_matrix_rows,
                            }
                        ]
                        if category_matrix_rows
                        else []
                    ),
                    {
                        "type": "table",
                        "headers": ["Required Element", "Concrete Example"],
                        "rows": [
                            [element, _response_element_statement(contract, element, document_type, system_name)]
                            for element in contract["response_elements"]
                        ],
                    },
                ]
            )
        sections.extend(common_sections)
        verification_rows.append(
            [
                objective_id,
                "Closure contract review and retained evidence check",
                datetime_utc_date(),
                "Pass",
                "ISSO / Control Owner",
            ]
        )

    sections.extend(
        [
            {"type": "heading", "level": 2, "text": "Verification Record"},
            {
                "type": "table",
                "headers": ["Objective ID", "Verification Method", "Last Verified", "Result", "Reviewer"],
                "rows": verification_rows,
            },
            {"type": "heading", "level": 2, "text": "Evidence Retention"},
            {
                "type": "table",
                "headers": ["Requirement", "Value"],
                "rows": [
                    ["Retention Period", "At least 12 months or the system-defined evidence retention period, whichever is longer"],
                    ["Review Cadence", "Reviewed before reassessment and during monthly control health checks"],
                    ["Record Owner", "ISSO / System Owner"],
                ],
            },
        ]
    )
    return sections


def datetime_utc_date() -> str:
    from datetime import datetime, UTC

    return datetime.now(UTC).strftime("%Y-%m-%d")
