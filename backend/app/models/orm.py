"""SQLAlchemy ORM models."""
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.model_base import Base


# ── Auth & Access ─────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="viewer")
    mfa_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="user")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(512), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    request_body_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["User | None"] = relationship(back_populates="audit_logs")


# ── Projects & Documents ──────────────────────────────────────────────────────

class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    impact_baseline: Mapped[str] = mapped_column(String(16), nullable=False, default="moderate")  # low|moderate|high
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    system_owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    owner: Mapped["User"] = relationship(foreign_keys=[owner_id])
    system_owner: Mapped["User | None"] = relationship(foreign_keys=[system_owner_id])
    documents: Mapped[list["Document"]] = relationship(
        back_populates="project", cascade="all, delete-orphan",
        foreign_keys="Document.project_id",
    )
    assessments: Mapped[list["Assessment"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    common_providers: Mapped[list["ProjectCommonProvider"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    provider_responsibilities: Mapped[list["ProjectProviderResponsibility"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class AssessmentPolicy(Base):
    __tablename__ = "assessment_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")  # draft|active|retired
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_thresholds_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    mapping_rules_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    buckets: Mapped[list["AssessmentPolicyBucket"]] = relationship(
        back_populates="policy", cascade="all, delete-orphan"
    )
    assessments: Mapped[list["Assessment"]] = relationship(back_populates="policy")


class AssessmentPolicyBucket(Base):
    __tablename__ = "assessment_policy_buckets"
    __table_args__ = (
        UniqueConstraint("policy_id", "bucket_key", name="uq_assessment_policy_bucket_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy_id: Mapped[int] = mapped_column(
        ForeignKey("assessment_policies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bucket_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    objective_weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    critical_by_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    minimum_evidence_strength: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    negative_evidence_penalty: Mapped[float] = mapped_column(Float, nullable=False, default=0.25)
    contradiction_penalty: Mapped[float] = mapped_column(Float, nullable=False, default=0.20)
    future_state_cap: Mapped[float] = mapped_column(Float, nullable=False, default=0.40)
    inheritance_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    compensating_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    confidence_cap_if_only_weak_evidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_cap_if_compensating_only: Mapped[float | None] = mapped_column(Float, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    policy: Mapped["AssessmentPolicy"] = relationship(back_populates="buckets")


class ProcedureLibrary(Base):
    """Enterprise procedure library — organizes procedure documents by category.

    Libraries are auto-created by the LLM categorizer (created_by=None) or
    manually by an admin. One library per category is the standard pattern.
    """
    __tablename__ = "procedure_libraries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="general")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    documents: Mapped[list["Document"]] = relationship(
        back_populates="procedure_library", cascade="all, delete-orphan",
        foreign_keys="Document.procedure_library_id",
    )


class PolicyLibrary(Base):
    """Enterprise policy library — organizes policy documents by category."""
    __tablename__ = "policy_libraries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="general")
    # e.g. general | information_security | access_control | configuration_management |
    #       incident_response | contingency_planning | personnel_security |
    #       risk_management | supply_chain | privacy
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)

    documents: Mapped[list["Document"]] = relationship(
        back_populates="policy_library", cascade="all, delete-orphan",
        foreign_keys="Document.policy_library_id",
    )


class CommonControlProvider(Base):
    """Enterprise-level common control providers (FedRAMP packages, shared services, etc.)."""
    __tablename__ = "common_control_providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    org_level: Mapped[str] = mapped_column(String(64), nullable=False, default="enterprise")
    # NIST control families covered (JSON list, e.g. ["AC","AU","PE"])
    control_families: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)

    documents: Mapped[list["Document"]] = relationship(
        back_populates="provider", cascade="all, delete-orphan",
        foreign_keys="Document.provider_id",
    )
    project_links: Mapped[list["ProjectCommonProvider"]] = relationship(
        back_populates="provider", cascade="all, delete-orphan"
    )
    responsibility_mappings: Mapped[list["ProjectProviderResponsibility"]] = relationship(
        back_populates="provider", cascade="all, delete-orphan"
    )


class ProjectCommonProvider(Base):
    """Many-to-many link: projects inherit common controls from providers."""
    __tablename__ = "project_common_providers"

    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("common_control_providers.id", ondelete="CASCADE"), primary_key=True
    )
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    linked_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)

    project: Mapped["Project"] = relationship(back_populates="common_providers")
    provider: Mapped["CommonControlProvider"] = relationship(back_populates="project_links")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Exactly one of project_id, provider_id, policy_library_id, or procedure_library_id is set
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    provider_id: Mapped[int | None] = mapped_column(
        ForeignKey("common_control_providers.id", ondelete="CASCADE"), nullable=True
    )
    policy_library_id: Mapped[int | None] = mapped_column(
        ForeignKey("policy_libraries.id", ondelete="CASCADE"), nullable=True, index=True
    )
    procedure_library_id: Mapped[int | None] = mapped_column(
        ForeignKey("procedure_libraries.id", ondelete="CASCADE"), nullable=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_type: Mapped[str] = mapped_column(String(64), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    parse_status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|processing|complete|indexing|indexed|failed|index_failed
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Auto-generation tracking
    autogenerated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_assessment_id: Mapped[int | None] = mapped_column(ForeignKey("assessments.id", ondelete="SET NULL"), nullable=True, index=True)
    source_remediation_report_id: Mapped[int | None] = mapped_column(ForeignKey("remediation_reports.id", ondelete="SET NULL"), nullable=True, index=True)
    # Fix 4: explicit control IDs this autogenerated doc addresses — used by control_tagger to apply forced tags
    # instead of LLM-guessing, preventing incidental tag dilution across unrelated controls
    artifact_controls: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Stage 2 metadata: LLM-classified type and intent, stored during indexing so the
    # assessment engine can tell the gap-analysis LLM what kind of document it's reading.
    document_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    document_intent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    artifact_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evidence_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    artifact_approved_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    artifact_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped["Project | None"] = relationship(back_populates="documents", foreign_keys=[project_id])
    provider: Mapped["CommonControlProvider | None"] = relationship(
        back_populates="documents", foreign_keys="Document.provider_id"
    )
    policy_library: Mapped["PolicyLibrary | None"] = relationship(
        back_populates="documents", foreign_keys="Document.policy_library_id"
    )
    procedure_library: Mapped["ProcedureLibrary | None"] = relationship(
        back_populates="documents", foreign_keys="Document.procedure_library_id"
    )
    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    section_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedding: Mapped[Any | None] = mapped_column(Vector(768), nullable=True)  # nomic-embed-text dim

    document: Mapped["Document"] = relationship(back_populates="chunks")
    control_tags: Mapped[list["DocumentChunkControlTag"]] = relationship(
        back_populates="chunk", cascade="all, delete-orphan"
    )


class DocumentChunkControlTag(Base):
    """LLM-generated tags linking a document chunk to NIST 800-53 control IDs."""
    __tablename__ = "document_chunk_control_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chunk_id: Mapped[int] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    control_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # e.g. "AC-2" or "AC-2(1)"
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    relevance_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tagged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    chunk: Mapped["DocumentChunk"] = relationship(back_populates="control_tags")


# ── Assessments & Findings ────────────────────────────────────────────────────

class Assessment(Base):
    __tablename__ = "assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    project_run_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|running|paused|complete|failed
    llm_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="ollama")
    llm_model: Mapped[str] = mapped_column(String(128), nullable=False)
    context_strategy: Mapped[str] = mapped_column(String(16), default="rag")
    ollama_num_ctx: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skip_stage3: Mapped[bool] = mapped_column(Boolean, default=False)
    carry_forward_compliant: Mapped[bool] = mapped_column(Boolean, default=False)
    controls_total: Mapped[int] = mapped_column(Integer, default=0)
    controls_complete: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    progress_detail: Mapped[str | None] = mapped_column(String(512), nullable=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    policy_id: Mapped[int | None] = mapped_column(
        ForeignKey("assessment_policies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    policy_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    finalization_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_ready")
    finalized_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped["Project"] = relationship(back_populates="assessments")
    findings: Mapped[list["ControlFinding"]] = relationship(back_populates="assessment", cascade="all, delete-orphan")
    remediation_reports: Mapped[list["RemediationReport"]] = relationship(back_populates="assessment", cascade="all, delete-orphan")
    policy: Mapped["AssessmentPolicy | None"] = relationship(back_populates="assessments")


class AssessmentPlan(Base):
    """Pre-execution scope, procedure, and approval record for an assessment."""
    __tablename__ = "assessment_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    scope_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    control_selection_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    methods_json: Mapped[list] = mapped_column(JSON, nullable=False)
    objects_json: Mapped[list] = mapped_column(JSON, nullable=False)
    depth: Mapped[str] = mapped_column(String(32), nullable=False)
    coverage: Mapped[str] = mapped_column(String(32), nullable=False)
    assessor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AssessmentActivity(Base):
    """Recorded EXAMINE, INTERVIEW, or TEST activity performed during an assessment."""
    __tablename__ = "assessment_activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("assessment_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    control_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    objective_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    method: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    assessment_objects: Mapped[list] = mapped_column(JSON, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="planned")
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_refs: Mapped[list | None] = mapped_column(JSON, nullable=True)
    performed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    performed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssessmentTailoringDecision(Base):
    """Approved ODP, inheritance, compensating-control, or N/A decision."""
    __tablename__ = "assessment_tailoring_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    control_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    decision_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    parameter_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    value_json: Mapped[dict | list | str | None] = mapped_column(JSON, nullable=True)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssessmentApproval(Base):
    """Append-only assessor or independent-reviewer approval event."""
    __tablename__ = "assessment_approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    approval_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssessmentRetryJob(Base):
    """Durable request to retry failed findings without tying work to the API process."""
    __tablename__ = "assessment_retry_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    control_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RemediationReport(Base):
    __tablename__ = "remediation_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True)
    report_type: Mapped[str] = mapped_column(String(32), nullable=False)  # "guide" | "artifacts"
    status: Mapped[str] = mapped_column(String(32), default="pending")   # pending|running|complete|failed
    progress_detail: Mapped[str | None] = mapped_column(Text, nullable=True)  # live "currently doing..." text
    content_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    generated_doc_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)  # list of Document.id created
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)

    assessment: Mapped["Assessment"] = relationship(back_populates="remediation_reports")


class ControlFinding(Base):
    __tablename__ = "control_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True)
    control_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # e.g. "AC-1"
    control_family: Mapped[str] = mapped_column(String(8), nullable=False)           # e.g. "AC"
    control_title: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_reviewed")
    # compliant|partially_compliant|non_compliant|not_applicable|not_reviewed
    implementation_statement: Mapped[str | None] = mapped_column(Text, nullable=True)
    gaps: Mapped[list | None] = mapped_column(JSON, nullable=True)
    evidence_citations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    remediation_plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    rule_signal: Mapped[str | None] = mapped_column(String(32), nullable=True)       # keyword match result
    raw_llm_response: Mapped[str | None] = mapped_column(Text, nullable=True)       # stored on parse failure
    needs_manual_review: Mapped[bool] = mapped_column(Boolean, default=False)       # set after retry still fails
    retry_count: Mapped[int] = mapped_column(Integer, default=0)                    # number of automated retries
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)                   # analyst notes on this control
    tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # when LLM assessed it
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer_status: Mapped[str | None] = mapped_column(String(32), nullable=True)   # accepted|override|revision_requested
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    carried_forward: Mapped[bool] = mapped_column(Boolean, default=False)       # finding copied from prev run (satisfied)
    applicability_changed: Mapped[bool] = mapped_column(Boolean, default=False) # N/A status differs from prev run
    prev_status: Mapped[str | None] = mapped_column(String(32), nullable=True)  # previous run's status
    override_applied: Mapped[str | None] = mapped_column(String(32), nullable=True)  # which override: satisfied|not_applicable|applicable|inherited
    # Option C: LLM challenge note — recorded when the stage-2.5 reviewer disputes the
    # code-calculated verdict.  The code verdict remains authoritative; this note surfaces
    # reviewer disagreement for the human assessor without silently overriding the score.
    llm_challenge_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Issue 5: True when implementation_statement was auto-synthesized from Stage 2 gap
    # analysis without a full Stage 3 LLM narrative pass (skip_stage3=True or LLM failure).
    # Surfaced in the UI and reports so analysts know a full re-assessment may improve quality.
    synthesized_narrative: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    assessment: Mapped["Assessment"] = relationship(back_populates="findings")


class AssessmentCriteriaPackage(Base):
    """Canonical assessment criteria snapshot for one control in one assessment."""
    __tablename__ = "assessment_criteria_packages"
    __table_args__ = (
        UniqueConstraint("assessment_id", "control_id", name="uq_assessment_criteria_control"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    control_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    control_family: Mapped[str] = mapped_column(String(8), nullable=False)
    control_title: Mapped[str] = mapped_column(String(512), nullable=False)
    control_statement: Mapped[str] = mapped_column(Text, nullable=False)
    supplemental_guidance: Mapped[str | None] = mapped_column(Text, nullable=True)
    assessment_objectives: Mapped[list | None] = mapped_column(JSON, nullable=True)
    criteria_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssessmentEvidenceTriage(Base):
    """Evidence-unit triage record for one control within one assessment."""
    __tablename__ = "assessment_evidence_triage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    control_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    unit_id: Mapped[int | None] = mapped_column(
        ForeignKey("evidence_units.id", ondelete="SET NULL"), nullable=True, index=True
    )
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    artifact_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_strength: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evidence_language_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    document_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    document_intent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    triage_role: Mapped[str] = mapped_column(String(32), nullable=False, default="supporting")
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    citation_label: Mapped[str | None] = mapped_column(String(512), nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ObjectiveEvidenceReview(Base):
    """Persisted evidence review assignment for one objective within one assessment."""
    __tablename__ = "objective_evidence_reviews"
    __table_args__ = (
        UniqueConstraint("assessment_id", "control_id", "objective_id", "unit_id", name="uq_objective_evidence_review"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    control_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    objective_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    objective_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit_id: Mapped[int | None] = mapped_column(
        ForeignKey("evidence_units.id", ondelete="SET NULL"), nullable=True, index=True
    )
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    artifact_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_strength: Mapped[str | None] = mapped_column(String(32), nullable=True)
    document_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    document_intent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    review_role: Mapped[str] = mapped_column(String(32), nullable=False, default="context")
    used_in_prompt: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    packet_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    objective_relevance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    keyword_hits: Mapped[list | None] = mapped_column(JSON, nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ObjectiveDetermination(Base):
    """Persisted assessment result for one 800-53A objective."""
    __tablename__ = "objective_determinations"
    __table_args__ = (
        UniqueConstraint("assessment_id", "control_id", "objective_id", name="uq_objective_determination"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    control_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    objective_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    objective_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    supporting_citations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    contradictory_citations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    missing_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_llm_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    adjudication_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ControlDetermination(Base):
    """Persisted control-level rollup built from objective determinations."""
    __tablename__ = "control_determinations"
    __table_args__ = (
        UniqueConstraint("assessment_id", "control_id", name="uq_control_determination"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    control_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    objective_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    deficiency_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssessmentChallenge(Base):
    """Second-pass reviewer challenge record for one control determination."""
    __tablename__ = "assessment_challenges"
    __table_args__ = (
        UniqueConstraint("assessment_id", "control_id", name="uq_assessment_challenge"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    control_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    concur: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    dissent_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    challenged_objectives: Mapped[list | None] = mapped_column(JSON, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolution_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_required")
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssessmentRollup(Base):
    """Persisted ATO-support summary for one assessment run."""
    __tablename__ = "assessment_rollups"
    __table_args__ = (
        UniqueConstraint("assessment_id", name="uq_assessment_rollup"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    readiness: Mapped[str] = mapped_column(String(32), nullable=False, default="insufficient_evidence")
    summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    residual_risk_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ControlOverride(Base):
    __tablename__ = "control_overrides"
    __table_args__ = (
        __import__('sqlalchemy').UniqueConstraint('project_id', 'control_id', name='uq_override_project_control'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    control_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    # Applicability override: "applicable" | "not_applicable" | "inherited" | None (auto)
    applicability: Mapped[str | None] = mapped_column(String(32), nullable=True)
    applicability_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    applicability_set_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    applicability_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Satisfied: skip future LLM runs, carry forward last finding
    satisfied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    satisfied_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    satisfied_set_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    satisfied_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    satisfied_finding_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # last finding to carry forward

    # Accepted risk
    risk_accepted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    risk_acceptance_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_accepted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    risk_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    risk_acceptance_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Manual status override — LLM cannot change this once set
    manual_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    manual_status_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    manual_status_set_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    manual_status_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ── Control Activity Log ──────────────────────────────────────────────────────

class ControlActivityLog(Base):
    """Immutable per-control audit trail. One row per action — never updated, only inserted."""
    __tablename__ = "control_activity_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    assessment_id: Mapped[int | None] = mapped_column(ForeignKey("assessments.id", ondelete="SET NULL"), nullable=True)
    control_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    control_family: Mapped[str] = mapped_column(String(8), nullable=False)
    control_title: Mapped[str] = mapped_column(String(512), nullable=False)

    # Action type — one of the constants documented below
    action_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # llm_assessed | carried_forward | override_not_applicable | override_applicable
    # override_inherited | override_cleared | marked_satisfied | satisfied_removed
    # risk_accepted | risk_acceptance_removed | notes_updated | manual_resolved
    # reviewer_accepted | reviewer_override | reviewer_revision | retry_queued

    action_summary: Mapped[str] = mapped_column(String(512), nullable=False)  # plain-English one-liner shown in UI
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)          # structured context (old/new values etc.)

    performed_by: Mapped[str] = mapped_column(String(64), nullable=False)      # username
    performed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


# ── Security / cATO ───────────────────────────────────────────────────────────

class InternalControlStatus(Base):
    __tablename__ = "internal_control_statuses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    control_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    control_family: Mapped[str] = mapped_column(String(8), nullable=False)
    control_title: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="not_implemented")
    # implemented|partially_implemented|not_implemented|inherited|not_applicable
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    auto_collected: Mapped[bool] = mapped_column(Boolean, default=False)
    last_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class SecurityEvent(Base):
    __tablename__ = "security_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # failed_login|account_locked|privilege_escalation|bulk_download|off_hours_access|config_change|mfa_bypass_attempt
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")  # low|medium|high|critical
    description: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    source_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class POAM(Base):
    __tablename__ = "poam_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    poam_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)  # e.g. "POAM-001"
    control_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    finding: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)  # critical|high|medium|low
    weakness: Mapped[str | None] = mapped_column(Text, nullable=True)
    remediation_plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    milestones: Mapped[list | None] = mapped_column(JSON, nullable=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    owner_role: Mapped[str | None] = mapped_column(String(128), nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_completion_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    likelihood: Mapped[str | None] = mapped_column(String(16), nullable=True)
    impact: Mapped[str | None] = mapped_column(String(16), nullable=True)
    residual_risk: Mapped[str | None] = mapped_column(String(16), nullable=True)
    response_strategy: Mapped[str | None] = mapped_column(String(32), nullable=True)
    acceptance_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    accepted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="open")  # open|in_progress|completed|accepted_risk|closed
    assessment_id: Mapped[int | None] = mapped_column(ForeignKey("assessments.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class OscalExportRun(Base):
    __tablename__ = "oscal_export_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True)
    export_kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)  # assessment-results | poam
    oscal_version: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_source: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    output_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="generated")  # generated|valid|invalid|error
    validation_errors: Mapped[list | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TestDatasetJob(Base):
    """Tracks a standalone test ATO package generation run at the project level.
    Not tied to any specific assessment — generates a complete evidence package
    for all controls in the project's baseline."""
    __tablename__ = "test_dataset_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="pending")
    # pending | running | complete | failed | cancelled
    progress_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    generated_doc_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ArtifactValidationRun(Base):
    """Validation pass over a generated artifact package."""
    __tablename__ = "artifact_validation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_mode: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_run_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ArtifactValidationResult(Base):
    """Per-document validation result for generated artifacts."""
    __tablename__ = "artifact_validation_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    validation_run_id: Mapped[int] = mapped_column(
        ForeignKey("artifact_validation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    integrity_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    ingestion_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    retrieval_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    control_mapping_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    details_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PackageViabilityRun(Base):
    """Package-level viability scoring for generated artifact packages."""
    __tablename__ = "package_viability_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_mode: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_run_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    expected_profile: Mapped[str | None] = mapped_column(String(64), nullable=True)
    viability_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SystemKnowledgeRun(Base):
    """One extraction pass that derives architecture/tool assertions from evidence."""
    __tablename__ = "system_knowledge_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_mode: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_run_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SystemKnowledgeAssertion(Base):
    """Reviewable system/tool/architecture fact derived from evidence."""
    __tablename__ = "system_knowledge_assertions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("system_knowledge_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    value_json: Mapped[dict | list | str | None] = mapped_column(JSON, nullable=True)
    normalized_value: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="proposed", nullable=False, index=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    provenance_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ToolInventory(Base):
    """Project-level detected or confirmed tool inventory."""
    __tablename__ = "tool_inventory"
    __table_args__ = (
        UniqueConstraint("project_id", "tool_name", name="uq_tool_inventory_project_tool"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tool_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    tool_category: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    vendor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    deployment_scope: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="proposed", nullable=False, index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    provenance_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProjectProviderResponsibility(Base):
    """Project/provider inheritance and shared-responsibility mapping."""
    __tablename__ = "project_provider_responsibilities"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "provider_id",
            "scope_type",
            "scope_id",
            name="uq_project_provider_scope",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("common_control_providers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="family")
    scope_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    inheritance_type: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True, default="shared"
    )  # inherited|shared|system_specific
    provider_coverage_status: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True, default="partial"
    )  # supported|partial|planned|none
    system_responsibility: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    provenance_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True, default="proposed"
    )  # proposed|confirmed|rejected
    reviewed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="provider_responsibilities")
    provider: Mapped["CommonControlProvider"] = relationship(back_populates="responsibility_mappings")


class IntegrationAccount(Base):
    """Configured live-data connector for a project."""
    __tablename__ = "integration_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connector_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    auth_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="dry_run")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="configured", index=True)
    config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class IntegrationRun(Base):
    """One connector execution against a configured account."""
    __tablename__ = "integration_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_id: Mapped[int] = mapped_column(
        ForeignKey("integration_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trigger_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    records_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    assertions_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TelemetrySnapshot(Base):
    """Normalized summary captured from an integration run."""
    __tablename__ = "telemetry_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_id: Mapped[int] = mapped_column(
        ForeignKey("integration_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("integration_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    snapshot_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    freshness_status: Mapped[str] = mapped_column(String(32), nullable=False, default="fresh")
    summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ControlTelemetryPosture(Base):
    """Live or planned control support derived from connector telemetry."""
    __tablename__ = "control_telemetry_posture"
    __table_args__ = (
        UniqueConstraint("project_id", "control_id", "source_kind", "source_ref", name="uq_control_telemetry_posture"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    control_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    support_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown", index=True)
    freshness_status: Mapped[str] = mapped_column(String(32), nullable=False, default="fresh", index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DriftRecord(Base):
    """Current or historical drift item produced by live telemetry evaluation."""
    __tablename__ = "drift_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("integration_accounts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("integration_runs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="integration", index=True)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False, default="project", index=True)
    scope_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="low", index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    details_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SecurityCollector(Base):
    """Project-scoped local or external security telemetry collector."""
    __tablename__ = "security_collectors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    collector_type: Mapped[str] = mapped_column(String(64), nullable=False, default="local_runtime", index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    secret_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SecurityCollectorNonce(Base):
    """Replay protection for signed collector submissions."""
    __tablename__ = "security_collector_nonces"
    __table_args__ = (
        UniqueConstraint("collector_id", "nonce", name="uq_security_collector_nonce"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    collector_id: Mapped[int] = mapped_column(
        ForeignKey("security_collectors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    nonce: Mapped[str] = mapped_column(String(128), nullable=False)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class SecurityAsset(Base):
    """Normalized security-monitored asset."""
    __tablename__ = "security_assets"
    __table_args__ = (
        UniqueConstraint("project_id", "asset_type", "name", name="uq_security_asset_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    criticality: Mapped[str] = mapped_column(String(32), nullable=False, default="medium")
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SecurityScan(Base):
    """One security telemetry collection or scan execution."""
    __tablename__ = "security_scans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    collector_id: Mapped[int | None] = mapped_column(
        ForeignKey("security_collectors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    scan_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SecurityFinding(Base):
    """Normalized tactical security finding."""
    __tablename__ = "security_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("security_assets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    scan_id: Mapped[int | None] = mapped_column(
        ForeignKey("security_scans.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open", index=True)
    fix_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cvss: Mapped[float | None] = mapped_column(Float, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class SecurityRecommendation(Base):
    """Actionable tactical recommendation synthesized from current findings."""
    __tablename__ = "security_recommendations"
    __table_args__ = (
        UniqueConstraint("project_id", "key", name="uq_security_recommendation_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium", index=True)
    score_impact: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open", index=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SecurityBuildSnapshot(Base):
    """Immutable build-time software factory security snapshot."""
    __tablename__ = "security_build_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    collector_id: Mapped[int | None] = mapped_column(
        ForeignKey("security_collectors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    label: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    commit_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="local_build", index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed", index=True)
    build_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    security_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SecurityRuntimeSnapshot(Base):
    """Near-real-time runtime security snapshot collected from the live system."""
    __tablename__ = "security_runtime_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    collector_id: Mapped[int | None] = mapped_column(
        ForeignKey("security_collectors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="collector", index=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    security_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VerificationCheck(Base):
    """Deterministic verification definition used to prove a security claim."""
    __tablename__ = "verification_checks"
    __table_args__ = (
        UniqueConstraint("check_key", name="uq_verification_check_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    check_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    control_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    source_scope: Mapped[str] = mapped_column(String(32), nullable=False, default="live", index=True)
    verifier_type: Mapped[str] = mapped_column(String(32), nullable=False, default="deterministic")
    freshness_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VerificationResult(Base):
    """Stored result for a project-scoped verification execution."""
    __tablename__ = "verification_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    check_id: Mapped[int] = mapped_column(
        ForeignKey("verification_checks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("security_assets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    result: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False, default="high")
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    evidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class SecurityTrackedSetting(Base):
    """Current normalized security-relevant setting for an asset."""
    __tablename__ = "security_tracked_settings"
    __table_args__ = (
        UniqueConstraint("project_id", "asset_id", "setting_key", name="uq_security_tracked_setting"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("security_assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    setting_key: Mapped[str] = mapped_column(String(128), nullable=False)
    setting_label: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    current_value_json: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON, nullable=True)
    current_value_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)


class SecuritySettingHistory(Base):
    """Historical observed values for tracked settings across snapshots."""
    __tablename__ = "security_setting_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tracked_setting_id: Mapped[int] = mapped_column(
        ForeignKey("security_tracked_settings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    snapshot_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    snapshot_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    value_json: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON, nullable=True)
    value_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class SecurityChangeEvent(Base):
    """Detected change between security snapshots for a tracked setting."""
    __tablename__ = "security_change_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("security_assets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tracked_setting_id: Mapped[int | None] = mapped_column(
        ForeignKey("security_tracked_settings.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    old_value_json: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON, nullable=True)
    new_value_json: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    source_snapshot_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_snapshot_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    impact_level: Mapped[str] = mapped_column(String(16), nullable=False, default="low", index=True)
    impact_direction: Mapped[str] = mapped_column(String(16), nullable=False, default="neutral", index=True)
    change_status: Mapped[str] = mapped_column(String(32), nullable=False, default="observed", index=True)
    summary: Mapped[str] = mapped_column(String(255), nullable=False)
    details_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class CalibrationSuite(Base):
    """Named library of expected control outcomes for calibration."""
    __tablename__ = "calibration_suites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CalibrationCase(Base):
    """Expected outcome case for one control inside a calibration suite."""
    __tablename__ = "calibration_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    suite_id: Mapped[int] = mapped_column(
        ForeignKey("calibration_suites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    control_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    expected_status: Mapped[str] = mapped_column(String(32), nullable=False)
    expected_objectives_json: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    expected_citations_json: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CalibrationRun(Base):
    """Persistent calibration harness run against a synthetic or benchmark source."""
    __tablename__ = "calibration_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_run_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    runtime_snapshot_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CalibrationCaseResult(Base):
    """Per-control result within one calibration harness run."""
    __tablename__ = "calibration_case_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("calibration_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    control_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    expected_status: Mapped[str] = mapped_column(String(32), nullable=False)
    actual_status: Mapped[str] = mapped_column(String(32), nullable=False)
    match_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    delta_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PromptOverride(Base):
    """Admin-editable overrides for LLM system prompts."""
    __tablename__ = "prompt_overrides"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)   # e.g. "assessment_system"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False)


class AssistantConversation(Base):
    __tablename__ = "assistant_conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="general")
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    assessment_id: Mapped[int | None] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AssistantContextAttachment(Base):
    __tablename__ = "assistant_context_attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("assistant_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attachment_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    context_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AssistantMessage(Base):
    __tablename__ = "assistant_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("assistant_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ── Control Closure Workflow ───────────────────────────────────────────────────

class ControlClosureSession(Base):
    """Interactive closure workflow for a single partial/non-compliant control."""
    __tablename__ = "control_closure_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    control_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    control_family: Mapped[str] = mapped_column(String(8), nullable=False)
    control_title: Mapped[str] = mapped_column(String(255), nullable=False)
    current_status: Mapped[str] = mapped_column(String(32), nullable=False)  # non_compliant | partially_compliant
    # active → artifact_pending → in_approval → closed
    session_status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    # JSON list of {role:"ai"|"user", step_type:"question"|"answer"|"summary"|"plan", content, timestamp}
    steps: Mapped[list | None] = mapped_column(JSON, nullable=True)
    context_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    implementation_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_artifacts: Mapped[list | None] = mapped_column(JSON, nullable=True)
    generated_artifact_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    closure_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    approvals: Mapped[list["ArtifactApproval"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class ArtifactApproval(Base):
    """Approval workflow record for an artifact generated during closure."""
    __tablename__ = "artifact_approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("control_closure_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    control_id: Mapped[str] = mapped_column(String(32), nullable=False)
    artifact_title: Mapped[str] = mapped_column(String(255), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False, default="policy_procedure")
    # JSON list of approval steps:
    # [{step:int, role:"preparer"|"reviewer"|"isso"|"system_owner",
    #   label:str, name:str, title:str, organization:str,
    #   status:"pending"|"approved"|"rejected", comments:str, completed_at:str}]
    approval_chain: Mapped[list] = mapped_column(JSON, nullable=False)
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    # pending_review | in_review | approved | rejected
    overall_status: Mapped[str] = mapped_column(String(32), default="pending_review", nullable=False)
    evidence_eligibility: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    eligibility_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    eligibility_decided_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    eligibility_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    session: Mapped["ControlClosureSession"] = relationship(back_populates="approvals")


class SystemProfile(Base):
    """System characteristics that drive automatic N/A applicability determinations."""
    __tablename__ = "system_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    # Deployment
    deployment_model: Mapped[str] = mapped_column(String(32), nullable=False)
    # saas | paas | iaas | on_premise | hybrid
    infrastructure_ownership: Mapped[str] = mapped_column(String(32), nullable=False, default="org_owned")
    # org_owned | fedramp_inherited | third_party | mixed
    # Network
    has_wireless_networking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    has_external_connections: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Devices & facilities
    has_physical_facilities: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    has_mobile_devices: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    has_removable_media: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Users
    user_population: Mapped[str] = mapped_column(String(32), nullable=False, default="mixed")
    # internal_only | external_users | automated_only | mixed
    publicly_accessible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Notes
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, default="system")


# ── New Ingestion Pipeline (v2) ────────────────────────────────────────────────

class IngestionConfig(Base):
    """Admin-managed configuration for the ingestion pipeline."""
    __tablename__ = "ingestion_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    # Non-secret values stored here; secret values stored encrypted in value_encrypted
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_encrypted: Mapped[bytes | None] = mapped_column(
        # LargeBinary stores encrypted bytes for secrets like API keys
        LargeBinary, nullable=True
    )
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class IngestionConfigAudit(Base):
    """Audit trail for ingestion configuration changes."""
    __tablename__ = "ingestion_config_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    config_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # Secret values are never written here — we store "<secret changed>" instead
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ControlCorpusVersion(Base):
    """Machine-readable control corpus versions used by ingestion screening."""
    __tablename__ = "control_corpus_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    corpus_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    corpus_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ParsedDocumentRecord(Base):
    """Persistent parser output metadata for one document within one ingestion run."""
    __tablename__ = "parsed_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parser_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parser_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    file_type: Mapped[str] = mapped_column(String(64), nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class IngestionRun(Base):
    """Tracks one complete ingestion pipeline run for a document.

    A document may have multiple runs (after reprocessing). Each run
    keeps its own ParsedLine/ScreeningResult/EvidenceUnit/etc records
    so historical runs are preserved for audit.
    """
    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Snapshot of ingestion config at time of run (JSON object)
    config_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    corpus_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Overall run state: pending | running | complete | failed | cancelled
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    # Current active stage
    current_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Stage-level status (pending|running|complete|failed|skipped)
    stage_parse: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    stage_screen: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    stage_expand: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    stage_classify: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    stage_embed: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    quality_status: Mapped[str] = mapped_column(String(32), default="passed", nullable=False)
    fallback_stages: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    readiness_eligible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Progress counts
    lines_parsed: Mapped[int] = mapped_column(Integer, default=0)
    lines_screened: Mapped[int] = mapped_column(Integer, default=0)
    evidence_units_created: Mapped[int] = mapped_column(Integer, default=0)
    units_classified: Mapped[int] = mapped_column(Integer, default=0)
    units_embedded: Mapped[int] = mapped_column(Integer, default=0)
    # Error capture (no secrets in here)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    triggered_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    parsed_lines: Mapped[list["ParsedLine"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    parsed_documents: Mapped[list["ParsedDocumentRecord"]] = relationship(
        cascade="all, delete-orphan"
    )
    evidence_units: Mapped[list["EvidenceUnit"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class ParsedLine(Base):
    """A single atomic text unit extracted from a parsed document.

    This is the canonical source-level record. Every downstream object
    (ScreeningResult, EvidenceUnit) traces back to one or more ParsedLines.
    """
    __tablename__ = "parsed_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Sequential line number within the document (1-based)
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Full heading path: e.g. "3 Access Control > 3.1 Account Management > 3.1.2 Procedures"
    section_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    block_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    block_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Table provenance (null for non-table content)
    table_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    row_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    col_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cell_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Structural type
    content_type: Mapped[str] = mapped_column(
        String(32), default="text", nullable=False
    )
    # text | heading | list_item | table_cell | caption | footnote
    # The raw extracted text — preserved exactly as parsed
    content: Mapped[str] = mapped_column(Text, nullable=False)

    run: Mapped["IngestionRun"] = relationship(back_populates="parsed_lines")
    screening_result: Mapped["ScreeningResult | None"] = relationship(
        back_populates="line", uselist=False, cascade="all, delete-orphan"
    )


class ScreeningResult(Base):
    """First-pass relevance screening result for a single ParsedLine.

    Lightweight keyword/heuristic pass — NOT a final assessment decision.
    Purpose: identify candidate controls for context expansion.
    """
    __tablename__ = "screening_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    line_id: Mapped[int] = mapped_column(
        ForeignKey("parsed_lines.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 0.0–1.0 relevance score from keyword screening
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # JSON array of control ID strings: ["AC-2", "AC-3", ...]
    candidate_controls: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # JSON array of enhancement IDs: ["AC-2(1)", "AC-2(3)", ...]
    candidate_enhancements: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Short human-readable rationale (no secrets)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Whether this line crossed the configured threshold for context expansion
    above_threshold: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    screened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    line: Mapped["ParsedLine"] = relationship(back_populates="screening_result")


class EvidenceUnit(Base):
    """An expanded contextual excerpt built from one or more parsed lines.

    Created when a ParsedLine's screening result crosses the threshold.
    Represents the actual evidence object used for classification and retrieval.
    """
    __tablename__ = "evidence_units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The line that triggered expansion
    trigger_line_id: Mapped[int] = mapped_column(
        ForeignKey("parsed_lines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # JSON array of ParsedLine IDs included in this unit
    source_line_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    # The full expanded content (combination of triggering + surrounding lines)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # JSON array of page numbers covered: [1, 2]
    page_numbers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Section path from the trigger line
    section_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Table coords if the unit spans table content: {"table_id":..., "rows":[...], "cols":[...]}
    table_coordinates: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Approximate token count
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    run: Mapped["IngestionRun"] = relationship(back_populates="evidence_units")
    classification: Mapped["EvidenceClassification | None"] = relationship(
        back_populates="unit", uselist=False, cascade="all, delete-orphan"
    )
    embedding: Mapped["EvidenceEmbedding | None"] = relationship(
        back_populates="unit", uselist=False, cascade="all, delete-orphan"
    )


class EvidenceClassification(Base):
    """Ollama reasoning model output for an EvidenceUnit.

    Stored as derived metadata — never overwrites source data.
    """
    __tablename__ = "evidence_classifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    unit_id: Mapped[int] = mapped_column(
        ForeignKey("evidence_units.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # JSON arrays of control/enhancement IDs identified by reasoning model
    control_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    enhancement_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # policy|procedure|implementation_statement|technical_config|operational|
    # test_evidence|management|diagram_narrative|audit_artifact|other
    artifact_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # weak|moderate|strong|insufficient
    evidence_strength: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # policy_language|implementation_language|procedural_language|objective_evidence|mixed
    evidence_language_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Concise explanation from reasoning model
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Which model was used (e.g. "deepseek-r1:32b")
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Model-reported confidence if available (0.0–1.0)
    model_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    classified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    unit: Mapped["EvidenceUnit"] = relationship(back_populates="classification")


class EvidenceEmbedding(Base):
    """Voyage embedding vector for an EvidenceUnit.

    Embeddings are generated only for expanded evidence units (not raw lines).
    The vector dimension depends on the Voyage model used.
    """
    __tablename__ = "evidence_embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    unit_id: Mapped[int] = mapped_column(
        ForeignKey("evidence_units.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Name of the Voyage model used (e.g. "voyage-3", "voyage-3-lite")
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # 1024-dim for voyage-3 / voyage-3-large, 512-dim for voyage-3-lite
    # We use Vector(1024) as the standard column — lite models are padded to 1024 if needed
    # Store as pgvector column
    embedding: Mapped[Any] = mapped_column(Vector(1024), nullable=True)
    embedded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    unit: Mapped["EvidenceUnit"] = relationship(back_populates="embedding")
