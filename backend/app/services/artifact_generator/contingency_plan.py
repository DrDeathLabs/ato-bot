"""Contingency Plan (CP) artifact generator."""
from __future__ import annotations

from app.services.artifact_generator.base import build_word_doc, gap


async def generate_contingency_plan(
    system_name: str,
    system_context: str,
    cp_findings: list[dict],
    assessment_id: int,
) -> str:
    """Generate a system-specific Contingency Plan document."""
    rto = _extract_rto(system_context, cp_findings)
    rpo = _extract_rpo(system_context, cp_findings)
    backup_proc = _extract_backup_procedures(system_context, cp_findings)
    alternate_site = _extract_alternate_site(system_context, cp_findings)

    sections = [
        {
            "heading": "1. Introduction",
            "level": 1,
            "content": (
                f"This Contingency Plan (CP) has been developed for {system_name} in accordance "
                f"with NIST SP 800-34 Rev 1 and addresses the requirements of NIST SP 800-53 Rev 5 "
                f"Contingency Planning (CP) control family.\n\n"
                f"This plan defines procedures to recover {system_name} in the event of an outage, "
                f"disruption, or disaster."
            ),
        },
        {
            "heading": "2. System Overview",
            "level": 1,
            "content": system_context[:2000] if system_context else gap(
                "Provide a description of the system, its components, data sensitivity, and operational role"
            ),
        },
        {
            "heading": "3. Recovery Objectives",
            "level": 1,
            "content": (
                f"Recovery Time Objective (RTO): {rto}\n\n"
                f"Recovery Point Objective (RPO): {rpo}"
            ),
        },
        {
            "heading": "4. Roles and Responsibilities",
            "level": 1,
            "content": gap("List contingency team members, roles, contact information, and alternates"),
        },
        {
            "heading": "5. Notification and Activation",
            "level": 1,
            "content": [
                "Criteria for plan activation",
                gap("Define specific outage conditions that trigger this plan"),
                "Notification procedures",
                gap("Define notification chain: who to call, in what order, how quickly"),
                "Damage assessment procedures",
                gap("Describe how initial damage assessment is conducted and documented"),
            ],
        },
        {
            "heading": "6. Recovery Procedures",
            "level": 1,
            "content": backup_proc or gap(
                "Provide step-by-step recovery procedures for each major system component"
            ),
        },
        {
            "heading": "7. Alternate Site and Processing",
            "level": 1,
            "content": alternate_site or gap(
                "Describe alternate processing site, agreements in place, and activation steps"
            ),
        },
        {
            "heading": "8. Backup and Restoration",
            "level": 1,
            "content": [
                _extract_backup_schedule(system_context, cp_findings),
                "Restoration procedures",
                gap("Describe step-by-step data and system restoration process"),
                "Backup testing schedule",
                gap("Define frequency of backup restore testing and documentation requirements"),
            ],
        },
        {
            "heading": "9. Testing and Exercises",
            "level": 1,
            "content": (
                "This contingency plan shall be tested annually in accordance with CP-4.\n\n"
                + gap("Describe planned test types: tabletop, functional, full-scale. Document last test date and results.")
            ),
        },
        {
            "heading": "10. Plan Maintenance",
            "level": 1,
            "content": (
                "This plan shall be reviewed and updated annually or when significant changes occur "
                "to the system, in accordance with CP-2.\n\n"
                + gap("Record plan version history, review dates, and approving officials")
            ),
        },
    ]

    return build_word_doc(
        sections=sections,
        title=f"Contingency Plan — {system_name}",
        output_filename=f"contingency_plan_{system_name.replace(' ', '_')}.docx",
    )


def _extract_rto(context: str, findings: list[dict]) -> str:
    import re
    combined = context + " ".join(str(f) for f in findings)
    match = re.search(r"rto[:\s]+(\d+\s*(?:hours?|days?|minutes?))", combined, re.IGNORECASE)
    return match.group(0) if match else gap("Define Recovery Time Objective (e.g., 4 hours, 24 hours)")


def _extract_rpo(context: str, findings: list[dict]) -> str:
    import re
    combined = context + " ".join(str(f) for f in findings)
    match = re.search(r"rpo[:\s]+(\d+\s*(?:hours?|days?|minutes?))", combined, re.IGNORECASE)
    return match.group(0) if match else gap("Define Recovery Point Objective (e.g., 1 hour, 24 hours)")


def _extract_backup_procedures(context: str, findings: list[dict]) -> str:
    if "backup" in context.lower():
        # Try to extract relevant sentences
        import re
        sentences = re.findall(r"[^.!?]*backup[^.!?]*[.!?]", context, re.IGNORECASE)
        if sentences:
            return " ".join(sentences[:3])
    return ""


def _extract_alternate_site(context: str, findings: list[dict]) -> str:
    keywords = ["alternate site", "disaster recovery site", "secondary site", "failover"]
    for kw in keywords:
        if kw.lower() in context.lower():
            return f"Alternate processing site information extracted from system documentation. " + gap(
                "Confirm alternate site details: location, capacity, activation agreement number"
            )
    return ""


def _extract_backup_schedule(context: str, findings: list[dict]) -> str:
    import re
    combined = context + " ".join(str(f) for f in findings)
    if "daily backup" in combined.lower():
        return "Daily backups are performed as documented in the system security plan."
    if "weekly backup" in combined.lower():
        return "Weekly backups are performed as documented in the system security plan."
    return gap("Define backup schedule: daily/weekly/monthly, retention period, backup media type")
