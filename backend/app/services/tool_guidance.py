"""Tool-aware evidence collection guidance for real remediation workflows."""
from __future__ import annotations

from typing import Any


FAMILY_EVIDENCE_DOMAINS: dict[str, list[str]] = {
    "AC": ["identity", "logging"],
    "AT": ["training", "workflow"],
    "AU": ["logging"],
    "CA": ["assessment", "workflow"],
    "CM": ["configuration", "endpoint"],
    "CP": ["backup_recovery", "workflow"],
    "IA": ["identity"],
    "IR": ["workflow", "logging"],
    "MA": ["endpoint", "workflow"],
    "MP": ["endpoint", "configuration"],
    "PE": ["physical", "workflow"],
    "PL": ["governance"],
    "PM": ["governance", "workflow"],
    "PS": ["workflow"],
    "RA": ["assessment", "vulnerability_management"],
    "SA": ["vendor_management", "workflow"],
    "SC": ["configuration", "network", "logging"],
    "SI": ["endpoint", "logging", "vulnerability_management"],
    "SR": ["vendor_management", "workflow"],
}


GENERIC_DOMAIN_GUIDANCE: dict[str, dict[str, Any]] = {
    "identity": {
        "where_to_go": ["Identity platform admin console", "Access review or MFA policy screen"],
        "collect": ["Export the applied access policy", "Capture MFA and role assignment screenshots", "Pull access review records"],
        "look_for": ["Named roles/groups", "Applied MFA settings", "Recent review or approval dates"],
    },
    "logging": {
        "where_to_go": ["Central logging or SIEM console", "Alerting dashboards or saved searches"],
        "collect": ["Export recent relevant log searches", "Capture retention and alerting settings", "Pull review or analyst sign-off records"],
        "look_for": ["Timestamps", "Alert routing", "Retention period", "Named reviewers"],
    },
    "training": {
        "where_to_go": ["Learning management system", "Training completion reports"],
        "collect": ["Export role-based completion reports", "Capture course assignments", "Pull acknowledgement records"],
        "look_for": ["User completion dates", "Role-specific modules", "Annual cadence"],
    },
    "workflow": {
        "where_to_go": ["Ticketing/workflow platform", "Approval workflow or task history"],
        "collect": ["Export representative tickets", "Capture approval chains", "Pull workflow timestamps"],
        "look_for": ["Approver names", "Closure evidence", "Status transitions", "Linked tasks"],
    },
    "assessment": {
        "where_to_go": ["Assessment repository", "POA&M tracker", "Audit results"],
        "collect": ["Pull the latest assessment report", "Export POA&M entries", "Capture closure evidence"],
        "look_for": ["Finding identifiers", "Closure dates", "Responsible parties"],
    },
    "configuration": {
        "where_to_go": ["Configuration management console", "System administration portal"],
        "collect": ["Export current baseline settings", "Capture policy enforcement screenshots", "Pull recent configuration review records"],
        "look_for": ["Applied baseline version", "Enforcement scope", "Review date and owner"],
    },
    "endpoint": {
        "where_to_go": ["Endpoint security or device management console", "Host inventory or policy pages"],
        "collect": ["Capture device policy screenshots", "Export host or policy assignment reports", "Pull enforcement or health status data"],
        "look_for": ["Policy applied to target hosts", "Enforcement status", "Last check-in date"],
    },
    "backup_recovery": {
        "where_to_go": ["Backup console", "Recovery test records", "DR runbook repository"],
        "collect": ["Export backup policy settings", "Capture recent restore test results", "Pull retention configuration"],
        "look_for": ["Successful backup jobs", "Restore validation dates", "Recovery owner"],
    },
    "physical": {
        "where_to_go": ["Physical access system", "Visitor log repository", "Facility control records"],
        "collect": ["Capture access roster and badge controls", "Pull visitor logs", "Export recent access reviews"],
        "look_for": ["Authorized personnel", "Review cadence", "Badge or door policy"],
    },
    "vulnerability_management": {
        "where_to_go": ["Scanner dashboard", "Vulnerability ticket queue", "Exception register"],
        "collect": ["Export latest scan results", "Capture remediation workflow", "Pull exception approvals"],
        "look_for": ["Severity ratings", "Remediation due dates", "Accepted risk approvals"],
    },
    "network": {
        "where_to_go": ["Firewall, WAF, or network management console", "Architecture diagrams"],
        "collect": ["Capture rule or policy exports", "Pull current network diagrams", "Export recent review or change approvals"],
        "look_for": ["Protected segments", "Inbound/outbound restrictions", "Named approvers"],
    },
    "vendor_management": {
        "where_to_go": ["Vendor management repository", "Contract or interconnection records"],
        "collect": ["Pull active contracts or agreements", "Capture due diligence reviews", "Export provider security requirements"],
        "look_for": ["Signed approvals", "Review dates", "Security obligations"],
    },
    "governance": {
        "where_to_go": ["Policy repository", "SSP or governance workbook"],
        "collect": ["Capture approved policy revisions", "Pull review minutes", "Export approval metadata"],
        "look_for": ["Approval date", "Owner", "Review cadence", "Mapped requirement language"],
    },
}


TOOL_GUIDANCE_LIBRARY: dict[str, dict[str, Any]] = {
    "CrowdStrike Falcon": {
        "endpoint": {
            "where_to_go": ["Falcon Console > Hosts > Host Management", "Falcon Console > Configuration > Prevention Policies"],
            "collect": ["Export policy assignment details", "Capture prevention policy screenshots", "Pull host group membership and sensor health evidence"],
            "look_for": ["Applied prevention policy", "Target host scope", "Sensor healthy/enforced"],
        },
        "logging": {
            "where_to_go": ["Falcon Console > Activity > Detections", "Falcon Console > Activity > Audit Trail"],
            "collect": ["Export recent detection activity", "Capture audit trail entries for policy changes", "Pull investigation workflow evidence"],
            "look_for": ["Detection timestamps", "Policy change approvals", "Named analyst actions"],
        },
    },
    "Splunk": {
        "logging": {
            "where_to_go": ["Splunk Search & Reporting", "Splunk ES dashboards or saved searches"],
            "collect": ["Export saved searches", "Capture alert configuration", "Pull log review evidence"],
            "look_for": ["Search window", "Retention-backed events", "Alert routing", "Reviewer sign-off"],
        },
        "assessment": {
            "where_to_go": ["Splunk dashboards supporting audit or incident review"],
            "collect": ["Capture compliance dashboards", "Export notable event summaries"],
            "look_for": ["Named detections", "Severity", "Disposition workflow"],
        },
    },
    "Tenable": {
        "vulnerability_management": {
            "where_to_go": ["Tenable Dashboard > Vulnerabilities", "Tenable Dashboard > Scans"],
            "collect": ["Export current scan results", "Capture scan schedules and targets", "Pull remediation status reports"],
            "look_for": ["Last scan date", "Coverage scope", "Severity counts", "Assigned remediation owners"],
        },
    },
    "Qualys": {
        "vulnerability_management": {
            "where_to_go": ["Qualys VMDR > Findings", "Qualys VMDR > Scans"],
            "collect": ["Export finding summaries", "Capture scan policy configuration", "Pull remediation workflow screenshots"],
            "look_for": ["Severity", "Asset scope", "Verification date", "Ticket linkage"],
        },
    },
    "AWS Config": {
        "configuration": {
            "where_to_go": ["AWS Console > AWS Config > Rules", "AWS Console > Resource timeline"],
            "collect": ["Export Config rule compliance", "Capture rule definitions", "Pull resource timeline evidence"],
            "look_for": ["Rule enabled", "Compliant/noncompliant state", "Remediation action linkage"],
        },
    },
    "AWS CloudTrail": {
        "logging": {
            "where_to_go": ["AWS Console > CloudTrail > Trails", "AWS Console > CloudTrail Lake / Event history"],
            "collect": ["Capture trail configuration", "Export event history relevant to the control", "Pull retention settings"],
            "look_for": ["Multi-region trail", "Log file validation", "Recent administrative activity"],
        },
    },
    "Okta": {
        "identity": {
            "where_to_go": ["Okta Admin Console > Applications / Security / Reports"],
            "collect": ["Export MFA or sign-on policy configuration", "Capture group assignment evidence", "Pull access review or lifecycle events"],
            "look_for": ["Applied policy", "User/group scope", "Recent review or deprovisioning activity"],
        },
    },
    "Microsoft Entra ID": {
        "identity": {
            "where_to_go": ["Entra Admin Center > Conditional Access / Users / Audit Logs"],
            "collect": ["Capture conditional access policies", "Export user or group assignments", "Pull audit log evidence"],
            "look_for": ["MFA enforcement", "Privileged role assignment", "Lifecycle activity"],
        },
    },
    "ServiceNow": {
        "workflow": {
            "where_to_go": ["ServiceNow > Incidents / Changes / Requests", "ServiceNow > Knowledge or task workflows"],
            "collect": ["Export representative tickets", "Capture approval workflow history", "Pull closure evidence and comments"],
            "look_for": ["Approver chain", "Resolution timestamps", "Linked evidence artifacts"],
        },
    },
    "Jamf": {
        "endpoint": {
            "where_to_go": ["Jamf Pro > Computers / Policies / Configuration Profiles"],
            "collect": ["Capture applied policies", "Export inventory evidence", "Pull recent compliance or health status"],
            "look_for": ["Target scope", "Profile status", "Last inventory update"],
        },
    },
    "Microsoft Intune": {
        "endpoint": {
            "where_to_go": ["Intune Admin Center > Devices / Configuration profiles / Compliance policies"],
            "collect": ["Capture device compliance policies", "Export assignment details", "Pull device compliance reports"],
            "look_for": ["Assigned groups", "Compliant state", "Last check-in"],
        },
    },
}


def _family_from_control_id(control_id: str | None) -> str:
    if not control_id:
        return ""
    return control_id.split("-")[0].upper()


def get_domains_for_control(control_id: str | None) -> list[str]:
    family = _family_from_control_id(control_id)
    return FAMILY_EVIDENCE_DOMAINS.get(family, ["governance"])


def _default_steps(tool_name: str | None, domain: str, domain_guidance: dict[str, Any]) -> list[str]:
    target = tool_name or domain.replace("_", " ")
    where_to_go = domain_guidance.get("where_to_go") or []
    collect = domain_guidance.get("collect") or []
    look_for = domain_guidance.get("look_for") or []
    steps: list[str] = []
    if where_to_go:
        steps.append(f"Open {target} and navigate to {where_to_go[0]}.")
    if len(where_to_go) > 1:
        steps.append(f"If needed, also review {where_to_go[1]} for supporting context or settings.")
    if collect:
        steps.append(f"Export or capture {collect[0]}.")
    if len(collect) > 1:
        steps.append(f"Also gather {collect[1]} so the assessor can corroborate the control.")
    if look_for:
        steps.append(f"Verify the evidence shows {look_for[0]}.")
    return steps


def _default_examples(domain_guidance: dict[str, Any]) -> list[str]:
    collect = domain_guidance.get("collect") or []
    look_for = domain_guidance.get("look_for") or []
    examples: list[str] = []
    if collect:
        examples.append(collect[0])
    if len(collect) > 1:
        examples.append(collect[1])
    if look_for:
        examples.append(f"Evidence should visibly include {look_for[0]}.")
    return examples[:3]


def _default_search_terms(tool_name: str | None, domain: str, control_id: str | None) -> list[str]:
    terms = []
    if tool_name:
        terms.append(tool_name)
    terms.append(domain.replace("_", " "))
    if control_id:
        terms.append(control_id)
        terms.append(f"{control_id} evidence")
    return [term for term in terms if term]


def _enrich_guidance_entry(
    *,
    control_id: str | None,
    tool_name: str | None,
    tool_category: str | None,
    domain: str,
    domain_guidance: dict[str, Any],
    why_relevant: str,
    detected: bool,
) -> dict[str, Any]:
    return {
        "control_id": control_id,
        "tool_name": tool_name,
        "tool_category": tool_category,
        "domain": domain,
        "where_to_go": domain_guidance.get("where_to_go", []),
        "collect": domain_guidance.get("collect", []),
        "look_for": domain_guidance.get("look_for", []),
        "collection_steps": domain_guidance.get("collection_steps") or _default_steps(tool_name, domain, domain_guidance),
        "evidence_examples": domain_guidance.get("evidence_examples") or _default_examples(domain_guidance),
        "search_terms": domain_guidance.get("search_terms") or _default_search_terms(tool_name, domain, control_id),
        "missing_artifact_signal": domain_guidance.get("missing_artifact_signal")
            or f"If you cannot find this in {tool_name or domain}, the package likely needs an additional artifact or the tool inventory is incomplete.",
        "why_relevant": why_relevant,
        "detected": detected,
    }


def build_action_collection_guidance(
    action: dict[str, Any],
    detected_tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    control_id = action.get("control_id")
    domains = get_domains_for_control(control_id)
    entries: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for tool in detected_tools:
        tool_name = tool.get("tool_name")
        spec = TOOL_GUIDANCE_LIBRARY.get(tool_name, {})
        for domain in domains:
            if domain not in spec:
                continue
            key = (tool_name, domain)
            if key in seen:
                continue
            seen.add(key)
            domain_guidance = spec[domain]
            entries.append(
                _enrich_guidance_entry(
                    control_id=control_id,
                    tool_name=tool_name,
                    tool_category=tool.get("tool_category"),
                    domain=domain,
                    domain_guidance=domain_guidance,
                    why_relevant=f"{tool_name} is relevant to {control_id} evidence collection.",
                    detected=True,
                )
            )

    if entries:
        return entries

    for domain in domains[:2]:
        generic = GENERIC_DOMAIN_GUIDANCE.get(domain)
        if not generic:
            continue
        entries.append(
            _enrich_guidance_entry(
                control_id=control_id,
                tool_name=None,
                tool_category=domain,
                domain=domain,
                domain_guidance=generic,
                why_relevant=f"No matching product was detected for {control_id}; collect generic {domain.replace('_', ' ')} evidence.",
                detected=False,
            )
        )
    return entries


def build_collection_playbook(
    actions: list[dict[str, Any]],
    detected_tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    playbook: list[dict[str, Any]] = []
    for action in actions:
        for item in build_action_collection_guidance(action, detected_tools):
            playbook.append(
                {
                    "control_id": action.get("control_id"),
                    "control_title": action.get("control_title"),
                    "gap": action.get("gap"),
                    **item,
                }
            )
    return playbook
