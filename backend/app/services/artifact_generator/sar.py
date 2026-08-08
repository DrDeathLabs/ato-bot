"""Security Assessment Report (SAR) generator."""
from __future__ import annotations

from app.services.artifact_generator.base import build_word_doc, gap


async def generate_sar(
    system_name: str,
    impact_baseline: str,
    findings: list,
    assessment_id: int,
) -> str:
    """Generate a formal Security Assessment Report."""
    total = len(findings)
    compliant = sum(1 for f in findings if f.status == "compliant")
    partial = sum(1 for f in findings if f.status == "partially_compliant")
    non = sum(1 for f in findings if f.status == "non_compliant")
    na = sum(1 for f in findings if f.status == "not_applicable")
    score = round((compliant + na) / max(total, 1) * 100, 1)

    # Group non/partial by family for executive section
    high_risk = [f for f in findings if f.status == "non_compliant"]
    medium_risk = [f for f in findings if f.status == "partially_compliant"]

    sections = [
        {
            "heading": "1. Executive Summary",
            "level": 1,
            "content": (
                f"An automated security assessment of {system_name} was conducted against the "
                f"NIST SP 800-53 Rev 5 {impact_baseline.upper()} baseline ({total} controls).\n\n"
                f"Assessment Results:\n"
                f"  - Compliant: {compliant} ({compliant/total*100:.0f}%)\n"
                f"  - Partially Compliant: {partial}\n"
                f"  - Non-Compliant: {non}\n"
                f"  - Not Applicable: {na}\n"
                f"  - Overall Compliance Score: {score}%\n\n"
                f"{'The system demonstrates adequate security controls for ATO consideration.' if score >= 70 else 'Significant control gaps exist. Remediation is required before ATO can be recommended.'}"
            ),
        },
        {
            "heading": "2. Assessment Scope and Methodology",
            "level": 1,
            "content": (
                f"This assessment evaluated {system_name} against {total} controls from the "
                f"NIST SP 800-53 Rev 5 {impact_baseline.upper()} baseline.\n\n"
                f"Methodology: Document review and automated analysis of system security artifacts "
                f"using AI-assisted control assessment (ATO Bot). Evidence was extracted from "
                f"uploaded security documentation and assessed against each applicable control.\n\n"
                + gap("List specific documents reviewed: SSP version, policies, SOPs, diagrams reviewed")
            ),
        },
        {
            "heading": "3. System Description",
            "level": 1,
            "content": gap(
                "Provide system name, purpose, FIPS 199 categorization, data types, user population, "
                "interconnections, and authorization boundary"
            ),
        },
        {
            "heading": "4. Assessment Results",
            "level": 1,
            "content": "",
        },
        {
            "heading": "4.1 High-Risk Findings (Non-Compliant Controls)",
            "level": 2,
            "content": _format_findings_list(high_risk, "Non-Compliant") if high_risk else "No non-compliant controls identified.",
        },
        {
            "heading": "4.2 Medium-Risk Findings (Partially Compliant Controls)",
            "level": 2,
            "content": _format_findings_list(medium_risk, "Partially Compliant") if medium_risk else "No partially compliant controls identified.",
        },
        {
            "heading": "4.3 Compliant Controls Summary",
            "level": 2,
            "content": (
                f"{compliant} controls were assessed as compliant based on available documentation evidence.\n"
                + gap("Assessor should verify automated findings through manual review of high-impact controls")
            ),
        },
        {
            "heading": "5. Risk Summary",
            "level": 1,
            "content": (
                f"Overall Risk Posture: {'Low' if score >= 85 else 'Moderate' if score >= 70 else 'High'}\n\n"
                f"Critical gaps identified: {len([f for f in high_risk if f.control_family in ['IA', 'AC', 'AU', 'SC']])}\n\n"
                + gap(
                    "Assessor should provide narrative risk determination including residual risk, "
                    "threat environment, and recommendation for authorization decision"
                )
            ),
        },
        {
            "heading": "6. Recommendations",
            "level": 1,
            "content": [
                f"Address {len(high_risk)} non-compliant controls before ATO decision" if high_risk else "No critical gaps identified",
                f"Remediate {len(medium_risk)} partially compliant controls per POAM schedule" if medium_risk else "",
                gap("Assessor recommendation: Authorize / Authorize with Conditions / Deny Authorization"),
                gap("Specify any conditions that must be met within 90 days for conditional authorization"),
            ],
        },
        {
            "heading": "7. Assessor Certification",
            "level": 1,
            "content": (
                gap("Assessor name, organization, date of assessment, and signature block") + "\n\n"
                "Note: This report was generated with AI assistance. All findings should be reviewed "
                "and validated by a qualified security assessor before submission for authorization."
            ),
        },
    ]

    return build_word_doc(
        sections=sections,
        title=f"Security Assessment Report — {system_name}",
        output_filename=f"sar_{assessment_id}_{system_name.replace(' ', '_')}.docx",
    )


def _format_findings_list(findings: list, label: str) -> list:
    result = []
    for f in findings[:20]:  # cap at 20 per section
        result.append(f"{f.control_id} ({f.control_family}): {f.control_title}")
        if hasattr(f, "gaps") and f.gaps:
            result.append(f"  Gap: {f.gaps[0][:200]}")
        if hasattr(f, "remediation_plan") and f.remediation_plan:
            result.append(f"  Remediation: {f.remediation_plan[:200]}")
    if len(findings) > 20:
        result.append(f"... and {len(findings) - 20} additional {label.lower()} controls (see Excel report)")
    return result
