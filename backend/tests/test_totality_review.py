import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.assessment_policy import resolve_bucket_context
from app.core.security import create_refresh_token, decode_token
from app.services.implementation_statements import (
    build_control_statement_generation_guidance,
    synthesize_control_implementation_statement,
)
from app.services.assessment_pipeline import (
    _SOURCE_QUALITY_SCORE,
    _SOURCE_WEIGHT,
    _build_gaps_from_objective_rows,
    _build_objective_evidence_maps,
    _policy_based_verdict,
    _resolve_objective_packet,
)
from app.services.closure_guidance import build_control_closure_guidance, build_contract_sections
from app.services.controls.catalog import Control
from app.services.human_artifact_generator import (
    HumanArtifactPlan,
    build_human_fallback_sections,
    lint_human_artifact,
)
from app.services.multistage_engine import _clean_implementation_statement


def _packet(
    *,
    unit_id,
    document_id,
    filename,
    content,
    triage_role="supporting",
    source_type="project",
    artifact_type="technical_config",
    evidence_strength="strong",
    document_intent="implements",
    relevance_score=0.75,
):
    return {
        "unit_id": unit_id,
        "document_id": document_id,
        "filename": filename,
        "content": content,
        "triage_role": triage_role,
        "source_type": source_type,
        "artifact_type": artifact_type,
        "evidence_strength": evidence_strength,
        "document_intent": document_intent,
        "relevance_score": relevance_score,
        "classification_confidence": 0.95,
        "token_count": 220,
        "control_ids": ["CM-6", "AC-2"],
        "enhancement_ids": [],
        "classification_explanation": "Tagged during ingestion",
        "document_type": "ssp",
        "section_path": "Section 3",
    }


class TotalityReviewTests(unittest.TestCase):
    def test_gap_summary_prefers_missing_evidence_over_scoring_rationale(self):
        gaps = _build_gaps_from_objective_rows(
            [{
                "objective_id": "AC-02b.",
                "objective_text": "account types allowed for use are identified.",
                "status": "not_met",
                "missing_evidence": "The artifacts do not identify prohibited or approved account types.",
                "rationale": "Bucket=identity_and_access_enforcement; weight=1.40; effective_support=0.92; evidence_quality=0.18; critical=true",
            }],
            "partially_compliant",
        )

        self.assertEqual(
            gaps,
            ["AC-02b. (Not met): The artifacts do not identify prohibited or approved account types."],
        )
        self.assertNotIn("Bucket=", gaps[0])
        self.assertNotIn("effective_support", gaps[0])

    def test_refresh_tokens_are_unique_even_for_same_subject(self):
        first = create_refresh_token("1")
        second = create_refresh_token("1")

        self.assertNotEqual(first, second)

        first_payload = decode_token(first)
        second_payload = decode_token(second)
        self.assertEqual(first_payload["sub"], "1")
        self.assertEqual(second_payload["sub"], "1")
        self.assertEqual(first_payload["type"], "refresh")
        self.assertEqual(second_payload["type"], "refresh")
        self.assertNotEqual(first_payload["jti"], second_payload["jti"])

    def test_clean_implementation_statement_genericizes_vendor_heavy_ssp_text(self):
        cleaned = _clean_implementation_statement(
            (
                'Part a: The system enforces approved authorizations using AWS Identity and Access Management (IAM) '
                'policies, PostgreSQL role-based access control, Redis ACLs, and Django permission classes. '
                'All IAM roles are defined in the Terraform module "ksf-iam-roles" and are validated quarterly '
                'through automated compliance scans in Tenable.io.'
            ),
            gap_analysis=[{"objective_id": "AC-2[a]", "met": "yes", "gap": None}],
        )

        self.assertNotIn("AWS Identity and Access Management", cleaned)
        self.assertNotIn("PostgreSQL", cleaned)
        self.assertNotIn("Redis ACLs", cleaned)
        self.assertNotIn("Django permission classes", cleaned)
        self.assertNotIn("Terraform module", cleaned)
        self.assertNotIn("Tenable.io", cleaned)
        self.assertIn("centralized identity and access management", cleaned.lower())
        self.assertIn("database role-based access control", cleaned.lower())
        self.assertIn("application authorization controls", cleaned.lower())
        self.assertNotIn("Part a:", cleaned)

    def test_control_statement_guidance_uses_objectives_as_coverage_contract(self):
        guidance = build_control_statement_generation_guidance(
            "AC-1",
            "Policy and Procedures",
            [
                "AC-01a.[01]: an access control policy is developed and documented",
                "AC-01a.[02]: the access control policy is disseminated to [org-defined]",
            ],
        )

        self.assertIn("CONTROL-LEVEL IMPLEMENTATION STATEMENT STANDARD FOR AC-1 - Policy and Procedures", guidance)
        self.assertIn("integrated control-level implementation statement", guidance)
        self.assertIn("AC-01a.[01]: An access control policy is developed and documented.", guidance)
        self.assertIn("defined organizational criteria", guidance)

    def test_synthesized_control_statement_draws_from_objective_text(self):
        statement = synthesize_control_implementation_statement(
            control_id="AC-1",
            control_title="Policy and Procedures",
            status="compliant",
            objectives=[
                "AC-01a.[01]: an access control policy is developed and documented",
                "AC-01a.[02]: the access control policy is disseminated to defined recipients",
                "AC-01a.[03]: access control procedures to facilitate implementation are developed and documented",
                "AC-01a.[05]: the current access control is reviewed and updated annually",
            ],
            gap_analysis=[
                {"objective_id": "AC-01a.[01]", "met": "yes", "gap": None},
                {"objective_id": "AC-01a.[02]", "met": "yes", "gap": None},
                {"objective_id": "AC-01a.[03]", "met": "yes", "gap": None},
                {"objective_id": "AC-01a.[05]", "met": "yes", "gap": None},
            ],
        )

        self.assertIn("For AC-1, Policy and Procedures is addressed through the current control implementation.", statement)
        self.assertIn("access control policy is developed and documented", statement.lower())
        self.assertIn("disseminated to defined recipients", statement.lower())
        self.assertIn("review and maintenance expectations", statement.lower())

    def test_clean_implementation_statement_replaces_thin_repetitive_text_with_objective_based_summary(self):
        cleaned = _clean_implementation_statement(
            (
                "Reviewed evidence indicates the system addresses this requirement through documented and currently "
                "implemented control activities.\n\n"
                "Reviewed evidence indicates the system addresses this requirement through documented and currently "
                "implemented control activities."
            ),
            gap_analysis=[
                {"objective_id": "AC-01a.[01]", "met": "yes", "gap": None},
                {"objective_id": "AC-01a.[02]", "met": "yes", "gap": None},
                {"objective_id": "AC-01a.[03]", "met": "partial", "gap": "Procedure dissemination evidence is not fully described."},
            ],
            control_id="AC-1",
            control_title="Policy and Procedures",
            status="partially_compliant",
            objectives=[
                "AC-01a.[01]: an access control policy is developed and documented",
                "AC-01a.[02]: the access control policy is disseminated to defined recipients",
                "AC-01a.[03]: access control procedures are disseminated to defined recipients",
            ],
        )

        self.assertNotIn("Reviewed evidence indicates the system addresses this requirement", cleaned)
        self.assertIn("For AC-1, Policy and Procedures is addressed through the current control implementation.", cleaned)
        self.assertIn("Current evidence does not yet fully demonstrate", cleaned)

    def test_inherited_objectives_keep_real_bucket_types(self):
        policy_context = resolve_bucket_context(
            "PL",
            "The organization inherits common control policy oversight responsibilities from a shared service provider.",
            "Planning Rules",
        )
        technical_context = resolve_bucket_context(
            "CM",
            "The organization inherits shared service configuration enforcement and secure baseline settings.",
            "Configuration Settings",
        )
        identity_context = resolve_bucket_context(
            "AC",
            "Inherited provider authentication and privileged account access enforcement must be monitored.",
            "Access Enforcement",
        )

        self.assertTrue(policy_context["inherited_context"])
        self.assertEqual(policy_context["primary_bucket_key"], "policy_governance")
        self.assertEqual(technical_context["primary_bucket_key"], "technical_enforcement")
        self.assertEqual(identity_context["primary_bucket_key"], "identity_and_access_enforcement")

    def test_common_control_source_scores_match_project_scores(self):
        self.assertEqual(_SOURCE_WEIGHT["common_control"], _SOURCE_WEIGHT["project"])
        self.assertEqual(_SOURCE_QUALITY_SCORE["common_control"], _SOURCE_QUALITY_SCORE["project"])

    def test_objective_evidence_maps_include_supporting_and_contradictory_packets_per_objective(self):
        control = SimpleNamespace(display_id="CM-6", family_id="CM", title="Safeguard Review")
        objectives = [
            "CM-6[a]: Enforce secure configuration baselines on application servers.",
            "AC-2[a]: Require multifactor authentication for privileged accounts.",
        ]
        candidate_packets = [
            _packet(
                unit_id=1,
                document_id=101,
                filename="cm-baseline.md",
                content="Configuration baseline standards define secure settings for application servers and production hosts.",
                triage_role="supporting",
                source_type="project",
            ),
            _packet(
                unit_id=2,
                document_id=102,
                filename="config-audit.md",
                content="Audit finding: configuration baselines are not consistently enforced on several application servers.",
                triage_role="contradictory",
                source_type="project",
                artifact_type="audit_artifact",
                document_intent="evaluates",
                relevance_score=0.18,
            ),
            _packet(
                unit_id=3,
                document_id=103,
                filename="iam-standard.md",
                content="Privileged accounts require multifactor authentication and hardware-backed tokens for administrator access.",
                triage_role="supporting",
                source_type="common_control",
            ),
        ]

        objective_maps = _build_objective_evidence_maps(control, objectives, candidate_packets)

        config_map = objective_maps["CM-6[a]"]
        access_map = objective_maps["AC-2[a]"]

        self.assertGreaterEqual(config_map["evidence_summary"]["supporting_packets"], 1)
        self.assertGreaterEqual(config_map["evidence_summary"]["contradictory_packets"], 1)
        self.assertEqual(access_map["evidence_summary"]["contradictory_packets"], 0)
        self.assertGreaterEqual(access_map["evidence_summary"]["supporting_packets"], 1)
        self.assertGreater(len(config_map["prompt_packets"]), 0)
        self.assertGreater(len(access_map["prompt_packets"]), 0)

    def test_base_control_objective_prefers_exact_objective_branch_over_sibling_enhancement(self):
        control = SimpleNamespace(
            display_id="IA-2",
            family_id="IA",
            title="Identification and Authentication (Organizational Users)",
        )
        objectives = [
            "IA-02[02]: the unique identification of authenticated organizational users is associated with processes acting on behalf of those users.",
        ]
        sibling_packet = _packet(
            unit_id=81,
            document_id=801,
            filename="ia-2-2-mfa.md",
            content=(
                "IA-2(2) - Multi-factor authentication for non-privileged accounts is enforced through "
                "Duo MFA, Active Directory security groups, and monthly access reviews."
            ),
            relevance_score=0.92,
        )
        sibling_packet.update({
            "control_ids": ["IA-2"],
            "enhancement_ids": ["IA-2(2)"],
        })
        target_packet = _packet(
            unit_id=82,
            document_id=802,
            filename="ia-2-objective-02.md",
            content=(
                "IA-2[02] - Unique identification of authenticated organizational users is associated with "
                "processes acting on behalf of those users. Every transaction log entry records the "
                "authenticated user's unique identifier for workflow actions and delegated process execution."
            ),
            relevance_score=0.74,
        )
        target_packet.update({
            "control_ids": ["IA-2"],
            "enhancement_ids": [],
        })

        objective_maps = _build_objective_evidence_maps(control, objectives, [sibling_packet, target_packet])
        objective_map = objective_maps["IA-02[02]"]
        ranked_packets = objective_map["considered_packets"]

        self.assertEqual(ranked_packets[0]["filename"], "ia-2-objective-02.md")
        self.assertGreater(
            ranked_packets[0]["objective_relevance_score"],
            ranked_packets[1]["objective_relevance_score"],
        )

    def test_enhancement_objective_prefers_exact_enhancement_branch_over_sibling_enhancement(self):
        control = SimpleNamespace(
            display_id="IA-2(1)",
            family_id="IA",
            title="Multi-factor Authentication to Privileged Accounts",
        )
        objectives = [
            "IA-02(01): multi-factor authentication is implemented for access to privileged accounts.",
        ]
        sibling_packet = _packet(
            unit_id=83,
            document_id=803,
            filename="ia-2-2-mfa.md",
            content=(
                "IA-2(2) - Multi-factor authentication for non-privileged accounts is enforced through "
                "Duo MFA and SSO conditional access."
            ),
            relevance_score=0.90,
        )
        sibling_packet.update({
            "control_ids": ["IA-2"],
            "enhancement_ids": ["IA-2(2)"],
        })
        target_packet = _packet(
            unit_id=84,
            document_id=804,
            filename="ia-2-1-privileged-mfa.md",
            content=(
                "IA-2(1) - Multi-factor authentication to privileged accounts. Administrative access requires "
                "phishing-resistant MFA and privileged session logging before elevation is granted."
            ),
            relevance_score=0.72,
        )
        target_packet.update({
            "control_ids": ["IA-2"],
            "enhancement_ids": ["IA-2(1)"],
        })

        objective_maps = _build_objective_evidence_maps(control, objectives, [sibling_packet, target_packet])
        objective_map = objective_maps["IA-02(01)"]
        ranked_packets = objective_map["considered_packets"]

        self.assertEqual(ranked_packets[0]["filename"], "ia-2-1-privileged-mfa.md")
        self.assertGreater(
            ranked_packets[0]["objective_relevance_score"],
            ranked_packets[1]["objective_relevance_score"],
        )

    def test_policy_based_verdict_uses_objective_specific_contradiction(self):
        control = SimpleNamespace(display_id="CM-6", family_id="CM", title="Configuration Settings")
        objectives = [
            "CM-6[a]: Enforce secure configuration baselines on application servers.",
            "CM-6[b]: Track approved configuration changes for production systems.",
        ]
        support_packet = _packet(
            unit_id=11,
            document_id=201,
            filename="cm-baseline.md",
            content="Approved secure configuration baselines are enforced on production application servers.",
            triage_role="supporting",
        )
        contradiction_packet = _packet(
            unit_id=12,
            document_id=202,
            filename="cm-gap-report.md",
            content="Gap report shows several application servers drift from the approved secure baseline.",
            triage_role="contradictory",
            artifact_type="audit_artifact",
            document_intent="evaluates",
            relevance_score=0.58,
        )
        tracking_packet = _packet(
            unit_id=13,
            document_id=203,
            filename="cm-change-log.md",
            content="Production configuration changes are tracked and approved in the change management workflow.",
            triage_role="supporting",
        )

        objective_maps = {
            "CM-6[a]": {
                "considered_packets": [support_packet, contradiction_packet],
                "prompt_packets": [support_packet, contradiction_packet],
                "corroboration": {"supporting_documents": 1, "total_documents": 2},
                "contradiction_ratio": 0.5,
                "evidence_summary": {"considered_packets": 2, "prompt_packets": 2},
            },
            "CM-6[b]": {
                "considered_packets": [tracking_packet],
                "prompt_packets": [tracking_packet],
                "corroboration": {"supporting_documents": 1, "total_documents": 1},
                "contradiction_ratio": 0.0,
                "evidence_summary": {"considered_packets": 1, "prompt_packets": 1},
            },
        }
        gap_analysis = [
            {
                "objective_id": "CM-6[a]",
                "met": "yes",
                "evidence_quote": "Approved secure configuration baselines are enforced on production application servers.",
                "source": "cm-baseline.md",
                "gap": None,
            },
            {
                "objective_id": "CM-6[b]",
                "met": "yes",
                "evidence_quote": "Production configuration changes are tracked and approved in the change management workflow.",
                "source": "cm-change-log.md",
                "gap": None,
            },
        ]

        verdict = _policy_based_verdict(
            assessment_id=999,
            control=control,
            objectives=objectives,
            gap_analysis=gap_analysis,
            objective_evidence_maps=objective_maps,
            corroboration={"supporting_documents": 2, "supporting_units": 2},
            policy_runtime=None,
        )

        objective_details = {
            row["objective_id"]: row
            for row in verdict["objective_details"]
        }
        self.assertEqual(objective_details["CM-6[a]"]["bucket_key"], "technical_enforcement")
        self.assertAlmostEqual(objective_details["CM-6[a]"]["contradiction_ratio"], 0.5)
        self.assertAlmostEqual(objective_details["CM-6[b]"]["contradiction_ratio"], 0.0)
        self.assertIn("contradictory_evidence", verdict["manual_review_reasons"])
        self.assertEqual(
            verdict["objective_summary"]["review_mode"],
            "objective_totality_ingested_evidence_v2",
        )
        self.assertEqual(
            verdict["objective_summary"]["totality_review"]["total_considered_packet_assignments"],
            3,
        )

    def test_policy_verdict_marks_inherited_common_control_as_context_not_penalty_bucket(self):
        control = SimpleNamespace(display_id="CM-6", family_id="CM", title="Configuration Settings")
        objectives = [
            "CM-6[a]: Inherited shared-service configuration enforcement must maintain secure baseline settings.",
        ]
        inherited_packet = _packet(
            unit_id=21,
            document_id=301,
            filename="provider-cm-baseline.md",
            content="The shared service enforces secure baseline settings across inherited managed hosts.",
            source_type="common_control",
        )
        objective_maps = {
            "CM-6[a]": {
                "considered_packets": [inherited_packet],
                "prompt_packets": [inherited_packet],
                "corroboration": {"supporting_documents": 1, "total_documents": 1},
                "contradiction_ratio": 0.0,
                "evidence_summary": {"considered_packets": 1, "prompt_packets": 1},
            },
        }
        gap_analysis = [
            {
                "objective_id": "CM-6[a]",
                "met": "yes",
                "evidence_quote": "The shared service enforces secure baseline settings across inherited managed hosts.",
                "source": "provider-cm-baseline.md",
                "gap": None,
            },
        ]

        verdict = _policy_based_verdict(
            assessment_id=1000,
            control=control,
            objectives=objectives,
            gap_analysis=gap_analysis,
            objective_evidence_maps=objective_maps,
            corroboration={"supporting_documents": 1, "supporting_units": 1},
            policy_runtime=None,
        )

        detail = verdict["objective_details"][0]
        self.assertEqual(detail["bucket_key"], "technical_enforcement")
        self.assertEqual(detail["bucket_modifier"], "inherited")
        self.assertTrue(detail["inherited_context"])

    def test_packet_source_resolution_does_not_treat_control_ids_as_document_numbers(self):
        packets = [
            {"packet_id": "PKT-AC-5-AC-05B-d10-u1", "filename": "first.docx", "content": "first"},
            {"packet_id": "PKT-AC-5-AC-05B-d20-u2", "filename": "AC-5 evidence.docx", "content": "second"},
        ]

        resolved = _resolve_objective_packet(
            {"source": "AC-5 evidence.docx", "packet_id": None, "evidence_quote": None},
            packets,
        )

        self.assertEqual(resolved["filename"], "AC-5 evidence.docx")

    def test_strong_current_packet_closes_objective_even_with_fuzzy_llm_citation(self):
        control = SimpleNamespace(display_id="AC-5", family_id="AC", title="Separation of Duties")
        objectives = ["AC-05b.: system access authorizations to support separation of duties are defined."]
        strong_packet = _packet(
            unit_id=31,
            document_id=401,
            filename="AC-5 Evidence.docx",
            content=(
                "The access authorization catalog defines permission boundaries that enforce the separation "
                "of duties matrix. Privileged access requests require dual approval and are provisioned through "
                "role-based groups."
            ),
            artifact_type="technical_config",
            evidence_strength="strong",
        )
        objective_maps = _build_objective_evidence_maps(control, objectives, [strong_packet])

        verdict = _policy_based_verdict(
            assessment_id=1001,
            control=control,
            objectives=objectives,
            gap_analysis=[{
                "objective_id": "AC-05b.",
                "met": "partial",
                "evidence_quote": None,
                "source": None,
                "packet_id": None,
                "gap": "Citation was not specific enough.",
            }],
            objective_evidence_maps=objective_maps,
            corroboration={"supporting_documents": 1, "supporting_units": 1},
            policy_runtime=None,
        )

        self.assertEqual(verdict["status"], "compliant")
        detail = verdict["objective_details"][0]
        self.assertEqual(detail["effective_status"], "met")
        self.assertTrue(detail["citation_fallback_applied"])
        self.assertEqual(detail["deterministic_support"]["status"], "met")

    def test_strong_objective_map_can_resolve_fallback_packet_even_when_llm_returns_no(self):
        control = SimpleNamespace(display_id="IA-5", family_id="IA", title="Authenticator Management")
        objectives = [
            "IA-05f.: system authenticators are managed through the change or refreshment of authenticators when organization-defined events occur."
        ]
        strong_packet = _packet(
            unit_id=32,
            document_id=402,
            filename="IA-5 Credential Rotation.docx",
            content=(
                "Authenticator changes are triggered by personnel separation, role transfer, suspected compromise, "
                "and scheduled 90-day privileged credential rotation. The identity administration team performs the "
                "refresh through the credential management workflow and records the action in the credential reset ticket."
            ),
            artifact_type="technical_config",
            evidence_strength="strong",
        )
        objective_maps = _build_objective_evidence_maps(control, objectives, [strong_packet])
        objective_maps["IA-05f."]["considered_packets"][0]["contract_coverage_score"] = 0.61
        objective_maps["IA-05f."]["prompt_packets"][0]["contract_coverage_score"] = 0.61
        objective_maps["IA-05f."]["contract_coverage"]["score"] = 0.61

        verdict = _policy_based_verdict(
            assessment_id=1005,
            control=control,
            objectives=objectives,
            gap_analysis=[{
                "objective_id": "IA-05f.",
                "met": "no",
                "evidence_quote": None,
                "source": None,
                "packet_id": None,
                "gap": "LLM citation was not resolved.",
            }],
            objective_evidence_maps=objective_maps,
            corroboration={"supporting_documents": 1, "supporting_units": 1},
            policy_runtime=None,
        )

        detail = verdict["objective_details"][0]
        self.assertTrue(detail["citation_fallback_applied"])
        self.assertEqual(detail["effective_status"], "met")
        self.assertEqual(detail["deterministic_support"]["status"], "met")

    def test_closure_guidance_adds_explicit_scope_coordination_and_account_management_elements(self):
        guidance = build_control_closure_guidance(
            control_id="AC-2",
            control_title="Account Management",
            gaps=[
                {"objective_id": "AC-02a.[02]", "description": "account types specifically prohibited for use within the system are defined and documented"},
                {"objective_id": "AC-02h.02", "description": "account managers and [org-defined] are notified within [org-defined] when users are terminated or transferred"},
                {"objective_id": "AC-02k.[01]", "description": "a process is established for changing shared or group account authenticators (if deployed) when individuals are removed from the group"},
                {"objective_id": "AC-02l.[01]", "description": "account management processes are aligned with personnel termination processes"},
            ],
            system_name="ATO BOT",
            mode="synthetic",
        )

        merged_elements = {
            element
            for contract in guidance["objective_contracts"]
            for element in contract["response_elements"]
        }
        self.assertIn("Prohibited account types", merged_elements)
        self.assertIn("Notification timeframe", merged_elements)
        self.assertIn("Shared account authenticator process", merged_elements)
        self.assertIn("Account management alignment", merged_elements)

    def test_contract_sections_emit_explicit_scope_and_change_board_language(self):
        contracts = build_control_closure_guidance(
            control_id="CM-3",
            control_title="Configuration Change Control",
            gaps=[
                {"objective_id": "CM-03g.[02]", "description": "the configuration control element convenes [org-defined]."},
                {"objective_id": "SR-01a.01(a)[02]", "description": "the [org-defined] supply chain risk management policy addresses scope"},
            ],
            system_name="ATO BOT",
            mode="synthetic",
        )["objective_contracts"]
        sections = build_contract_sections(
            contracts=contracts,
            system_name="ATO BOT",
            document_type="policy",
            intro_title="Test",
            intro_text="Test intro.",
        )
        full_text = " ".join(
            str(part)
            for section in sections
            for part in (
                [section.get("text")]
                + (section.get("items") or [])
                + [item for row in (section.get("rows") or []) for item in (row if isinstance(row, list) else [row])]
            )
            if part
        )

        self.assertIn("Change Advisory Board", full_text)
        self.assertIn("weekly", full_text.lower())
        self.assertIn("production environment", full_text.lower())

    def test_verbose_llm_objective_id_resolves_to_catalog_objective_packet(self):
        control = SimpleNamespace(display_id="PL-10", family_id="PL", title="Baseline Selection")
        packet = _packet(
            unit_id=41,
            document_id=501,
            filename="PL-10 Baseline Policy.docx",
            content="The FedRAMP Moderate baseline was selected as the control baseline for ATO BOT.",
            artifact_type="policy",
            evidence_strength="strong",
        )
        packet.update({
            "packet_id": "PKT-PL-10-PL-10-d501-u41",
            "objective_relevance_score": 2.9,
            "contract_coverage_score": 0.82,
            "contract_satisfied": True,
        })
        objective_maps = {
            "PL-10": {
                "considered_packets": [packet],
                "prompt_packets": [packet],
                "corroboration": {"supporting_documents": 1, "total_documents": 1},
                "contradiction_ratio": 0.0,
                "contract_coverage": {"score": 0.82, "satisfied": True},
                "evidence_summary": {"considered_packets": 1, "prompt_packets": 1},
            },
        }

        verdict = _policy_based_verdict(
            assessment_id=1002,
            control=control,
            objectives=["PL-10: a control baseline for the system is selected."],
            gap_analysis=[{
                "objective_id": "PL-10: a control baseline for the system is selected.",
                "met": "yes",
                "evidence_quote": "The FedRAMP Moderate baseline was selected as the control baseline for ATO BOT.",
                "source": "PL-10 Baseline Policy.docx",
                "packet_id": "PKT-PL-10-PL-10-d501-u41",
                "gap": None,
            }],
            objective_evidence_maps=objective_maps,
            corroboration={"supporting_documents": 1, "supporting_units": 1},
            policy_runtime=None,
        )

        self.assertEqual(verdict["status"], "compliant")
        self.assertEqual(verdict["objective_rows"][0]["objective_id"], "PL-10")
        self.assertEqual(verdict["objective_rows"][0]["status"], "met")
        self.assertEqual(verdict["objective_rows"][0]["adjudication_json"]["packet_id"], "PKT-PL-10-PL-10-d501-u41")
        self.assertEqual(verdict["objective_rows"][0]["adjudication_json"]["packet_resolution_scope"], "objective")
        self.assertEqual(
            verdict["objective_rows"][0]["adjudication_json"]["raw_objective_id"],
            "PL-10: a control baseline for the system is selected.",
        )

    def test_objective_id_alias_handles_missing_trailing_punctuation(self):
        control = SimpleNamespace(display_id="IA-4", family_id="IA", title="Identifier Management")
        packet = _packet(
            unit_id=42,
            document_id=502,
            filename="IA-4 Identifier Evidence.docx",
            content="System identifiers are managed by preventing reuse after deprovisioning.",
            artifact_type="technical_config",
            evidence_strength="strong",
        )
        packet.update({
            "packet_id": "PKT-IA-4-IA-04D-d502-u42",
            "objective_relevance_score": 3.0,
            "contract_coverage_score": 0.76,
            "contract_satisfied": True,
        })
        objective_maps = {
            "IA-04d.": {
                "considered_packets": [packet],
                "prompt_packets": [packet],
                "corroboration": {"supporting_documents": 1, "total_documents": 1},
                "contradiction_ratio": 0.0,
                "contract_coverage": {"score": 0.76, "satisfied": True},
                "evidence_summary": {"considered_packets": 1, "prompt_packets": 1},
            },
        }

        verdict = _policy_based_verdict(
            assessment_id=1003,
            control=control,
            objectives=["IA-04d.: system identifiers are managed by preventing reuse."],
            gap_analysis=[{
                "objective_id": "IA-04d",
                "met": "yes",
                "evidence_quote": "System identifiers are managed by preventing reuse after deprovisioning.",
                "source": "IA-4 Identifier Evidence.docx",
                "packet_id": "PKT-IA-4-IA-04D-d502-u42",
                "gap": None,
            }],
            objective_evidence_maps=objective_maps,
            corroboration={"supporting_documents": 1, "supporting_units": 1},
            policy_runtime=None,
        )

        self.assertEqual(verdict["status"], "compliant")
        self.assertEqual(verdict["objective_rows"][0]["objective_id"], "IA-04d.")
        self.assertEqual(verdict["objective_rows"][0]["status"], "met")
        self.assertEqual(verdict["objective_rows"][0]["adjudication_json"]["packet_id"], "PKT-IA-4-IA-04D-d502-u42")

    def test_unresolved_objective_blocks_compliant_rollup(self):
        control = SimpleNamespace(display_id="PL-1", family_id="PL", title="Policy and Procedures")
        strong_packet = _packet(
            unit_id=51,
            document_id=601,
            filename="PL-1 Planning Policy.docx",
            content="The planning policy is approved, disseminated, reviewed annually, and assigned to the ISSO.",
            artifact_type="policy",
            evidence_strength="strong",
        )
        strong_packet.update({
            "packet_id": "PKT-PL-1-PL-01A-01-d601-u51",
            "objective_relevance_score": 3.0,
            "contract_coverage_score": 0.92,
            "contract_satisfied": True,
        })
        objective_maps = {
            "PL-01a.01(a)[01]": {
                "considered_packets": [strong_packet],
                "prompt_packets": [strong_packet],
                "corroboration": {"supporting_documents": 1, "total_documents": 1},
                "contradiction_ratio": 0.0,
                "contract_coverage": {"score": 0.92, "satisfied": True},
                "evidence_summary": {"considered_packets": 1, "prompt_packets": 1},
            },
            "PL-01a.01(a)[02]": {
                "considered_packets": [],
                "prompt_packets": [],
                "corroboration": {"supporting_documents": 0, "total_documents": 0},
                "contradiction_ratio": 0.0,
                "contract_coverage": {"score": 0.0, "satisfied": False},
                "evidence_summary": {"considered_packets": 0, "prompt_packets": 0},
            },
        }

        verdict = _policy_based_verdict(
            assessment_id=1004,
            control=control,
            objectives=[
                "PL-01a.01(a)[01]: planning policy purpose is documented.",
                "PL-01a.01(a)[02]: planning policy scope is documented.",
            ],
            gap_analysis=[
                {
                    "objective_id": "PL-01a.01(a)[01]",
                    "met": "yes",
                    "evidence_quote": "The planning policy is approved, disseminated, reviewed annually, and assigned to the ISSO.",
                    "source": "PL-1 Planning Policy.docx",
                    "packet_id": "PKT-PL-1-PL-01A-01-d601-u51",
                    "gap": None,
                },
                {
                    "objective_id": "PL-01a.01(a)[02]",
                    "met": "no",
                    "evidence_quote": None,
                    "source": None,
                    "packet_id": None,
                    "gap": "Planning policy scope is not documented.",
                },
            ],
            objective_evidence_maps=objective_maps,
            corroboration={"supporting_documents": 1, "supporting_units": 1},
            policy_runtime={
                "thresholds": {
                    "compliant_threshold": 0.40,
                    "minimum_evidence_quality_for_compliant": 0.20,
                },
                "buckets": {},
            },
        )

        self.assertEqual(verdict["status"], "partially_compliant")
        self.assertEqual(verdict["objective_summary"]["unresolved_objectives"], ["PL-01a.01(a)[02]"])
        self.assertEqual(verdict["objective_summary"]["not_met"], 1)

    def test_clean_implementation_statement_removes_evidence_inventory_style_output(self):
        raw = (
            "Part a: The organization has developed and documented an Access Control Policy "
            "(TESTPKG_AC_Access_Control_Technical_Validation_and_Verification_Record_Part_1.docx) "
            "stored in the AWS GovCloud S3 bucket and version-controlled in GitLab. "
            "Portal access logs confirm 112 recipients. "
            "Part b: Legal review performed on 2024-01-15 confirmed alignment with FISMA "
            "(TESTPKG_AC_Access_Control_Technical_Validation_and_Verification_Record_Part_1.docx)."
        )
        gap_analysis = [
            {"objective_id": "AC-1[a]", "met": "yes", "gap": None},
            {"objective_id": "AC-1[b]", "met": "partial", "gap": "review cadence is not formally defined"},
        ]

        cleaned = _clean_implementation_statement(raw, gap_analysis=gap_analysis)

        self.assertNotIn("TESTPKG_AC_Access_Control_Technical_Validation_and_Verification_Record_Part_1.docx", cleaned)
        self.assertNotIn("AWS GovCloud S3 bucket", cleaned)
        self.assertIn("review cadence is not formally defined", cleaned)

    def test_human_artifact_lint_rejects_assessor_meta_language_and_objective_ids(self):
        control = Control(
            id="ac-1",
            label="AC-1",
            family_id="ac",
            family_title="Access Control",
            title="Policy and Procedures",
            statement="The organization develops and disseminates access control policy and procedures.",
            supplemental_guidance="",
            assessment_objectives=[
                "AC-01a.[01]: an access control policy is developed and documented",
                "AC-01a.[02]: the access control policy is disseminated to defined recipients",
            ],
        )
        plan = HumanArtifactPlan(
            control_id="AC-1",
            control_title="Policy and Procedures",
            artifact_type="policy_standard",
            document_type="policy",
            title="ATO BOT Access Control Policy",
            filename="HUMAN_AC1.docx",
            outline=[
                "Purpose",
                "Scope",
                "Roles and Responsibilities",
                "Policy",
                "Procedures",
                "Review and Document Control",
            ],
        )
        sections = [
            {"type": "heading", "level": 1, "text": "Purpose"},
            {
                "type": "paragraph",
                "text": "This section satisfies NIST 800-53A assessment objective AC-01a.[01].",
            },
            {"type": "heading", "level": 1, "text": "Scope"},
            {"type": "paragraph", "text": "The access control policy is disseminated to defined recipients."},
        ]

        issues = lint_human_artifact(title=plan.title, sections=sections, control=control, plan=plan)

        self.assertTrue(any("forbidden assessor/meta phrase" in issue.lower() for issue in issues))
        self.assertTrue(any("identifiers" in issue.lower() for issue in issues))

    def test_human_fallback_sections_read_like_normal_document_structure(self):
        control = Control(
            id="sr-1",
            label="SR-1",
            family_id="sr",
            family_title="Supply Chain Risk Management",
            title="Policy and Procedures",
            statement="The organization develops, disseminates, and reviews supply chain risk policy and procedures.",
            supplemental_guidance="",
            assessment_objectives=[
                "SR-01a.[01]: a supply chain risk management policy is developed and documented",
                "SR-01a.[02]: the supply chain risk management policy is disseminated to defined recipients",
            ],
        )
        plan = HumanArtifactPlan(
            control_id="SR-1",
            control_title="Policy and Procedures",
            artifact_type="policy_standard",
            document_type="policy",
            title="ATO BOT Supply Chain Risk Management Policy",
            filename="HUMAN_SR1.docx",
            outline=[
                "Purpose",
                "Scope",
                "Roles and Responsibilities",
                "Policy",
                "Procedures",
                "Review and Document Control",
            ],
        )
        context = SimpleNamespace(
            system_name="ATO BOT",
            impact_baseline="moderate",
            context_label="ATO BOT | Moderate baseline",
        )

        sections = build_human_fallback_sections(control, plan, context)
        headings = [section["text"] for section in sections if section["type"] == "heading"]
        combined = "\n".join(
            section.get("text", "") for section in sections if section["type"] in {"heading", "paragraph"}
        )

        self.assertEqual(
            headings,
            ["Purpose", "Scope", "Roles and Responsibilities", "Policy", "Procedures", "Review and Document Control"],
        )
        self.assertNotRegex(combined, r"AC-01|SR-01")
        self.assertNotIn("This section satisfies", combined)


if __name__ == "__main__":
    unittest.main()
