"""Incident Response Plan (IRP) artifact generator."""
from __future__ import annotations

from app.services.artifact_generator.base import build_word_doc, gap


async def generate_incident_response_plan(
    system_name: str,
    system_context: str,
    ir_findings: list[dict],
    assessment_id: int,
) -> str:
    """Generate a system-specific Incident Response Plan."""
    sections = [
        {
            "heading": "1. Purpose and Scope",
            "level": 1,
            "content": (
                f"This Incident Response Plan (IRP) establishes procedures for detecting, "
                f"reporting, containing, and recovering from security incidents affecting {system_name}. "
                f"This plan implements NIST SP 800-61 Rev 2 and satisfies NIST SP 800-53 Rev 5 "
                f"Incident Response (IR) control family requirements."
            ),
        },
        {
            "heading": "2. System Description",
            "level": 1,
            "content": system_context[:1500] if system_context else gap(
                "Provide system description: purpose, data types processed, interconnections, and criticality"
            ),
        },
        {
            "heading": "3. Incident Response Team",
            "level": 1,
            "content": [
                "Incident Response Coordinator",
                gap("Name, title, phone, email, and alternate contact for IR Coordinator"),
                "System Owner",
                gap("Name, title, phone, email for System Owner"),
                "ISSM / ISSO",
                gap("Name, title, phone, email for Information System Security Manager/Officer"),
                "IT Operations Lead",
                gap("Name, title, phone, and alternate for IT Operations"),
                "Legal / Counsel",
                gap("Contact information for legal counsel (privacy breach, law enforcement coordination)"),
                "External CSIRT",
                gap("Name and contact for external CSIRT/US-CERT reporting if applicable"),
            ],
        },
        {
            "heading": "4. Incident Classification",
            "level": 1,
            "content": [
                "Critical: Confirmed breach of sensitive data, ransomware, or system-wide outage",
                "High: Suspected unauthorized access, malware detected, significant service degradation",
                "Medium: Policy violation, failed intrusion attempt, unusual access pattern",
                "Low: Nuisance activity, minor policy violation, informational event",
            ],
        },
        {
            "heading": "5. Incident Response Phases",
            "level": 1,
            "content": "",
        },
        {
            "heading": "5.1 Preparation",
            "level": 2,
            "content": (
                "Incident response capabilities shall be maintained through:\n"
                "- Annual IR training for all system personnel (IR-2)\n"
                "- Annual IR testing/exercises (IR-3)\n"
                "- Maintained IR contact list and escalation procedures\n"
                + gap("Describe IR tools, forensic capabilities, and jump bag contents available to the team")
            ),
        },
        {
            "heading": "5.2 Detection and Analysis",
            "level": 2,
            "content": [
                gap("List monitoring tools and log sources used to detect incidents (SIEM, IDS/IPS, audit logs)"),
                "Analyze indicators of compromise (IoCs) from alerts and logs",
                "Correlate events across multiple sources to confirm incident",
                "Document initial findings in incident ticket",
                gap("Specify ticketing system used for incident tracking"),
            ],
        },
        {
            "heading": "5.3 Containment",
            "level": 2,
            "content": [
                "Short-term containment: Isolate affected systems from network",
                "Preserve evidence before system changes (memory dumps, disk images)",
                "Document all containment actions with timestamps",
                gap("Describe network isolation procedures specific to system architecture"),
                "Notify System Owner and ISSO within 1 hour of confirmed incident",
            ],
        },
        {
            "heading": "5.4 Eradication",
            "level": 2,
            "content": [
                "Identify root cause of incident",
                "Remove malware, unauthorized accounts, or vulnerabilities exploited",
                "Patch or reconfigure affected systems",
                gap("Describe system-specific eradication steps for likely incident types"),
            ],
        },
        {
            "heading": "5.5 Recovery",
            "level": 2,
            "content": [
                "Restore systems from known-good backups or clean images",
                "Validate system integrity before returning to production",
                "Implement enhanced monitoring post-incident",
                gap("Reference contingency plan recovery procedures for system restoration steps"),
            ],
        },
        {
            "heading": "5.6 Post-Incident Activity",
            "level": 2,
            "content": [
                "Conduct lessons-learned review within 2 weeks of incident closure",
                "Update IR plan with findings and improvements",
                "Report to US-CERT/CISA within required timeframes if federal system",
                gap("Define organization-specific reporting requirements and timeframes"),
            ],
        },
        {
            "heading": "6. Reporting Requirements",
            "level": 1,
            "content": (
                "Incidents shall be reported per organizational policy and IR-6:\n\n"
                + gap(
                    "Specify: internal reporting chain, external reporting (US-CERT, IG, Congress), "
                    "timeframes for each severity level, and breach notification requirements"
                )
            ),
        },
        {
            "heading": "7. Plan Testing and Maintenance",
            "level": 1,
            "content": (
                "This plan shall be tested annually (IR-3) and updated when the system or "
                "organizational requirements change (IR-8).\n\n"
                + gap("Document test schedule, test type (tabletop/functional), and last test date/results")
            ),
        },
    ]

    return build_word_doc(
        sections=sections,
        title=f"Incident Response Plan — {system_name}",
        output_filename=f"incident_response_plan_{system_name.replace(' ', '_')}.docx",
    )
