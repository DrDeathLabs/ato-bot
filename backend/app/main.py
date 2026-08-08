"""ATO Bot — FastAPI application entry point."""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api import auth, users
from app.api.projects import router as projects_router
from app.api.documents import router as documents_router
from app.api.assessments import router as assessments_router
from app.api.reports import router as reports_router
from app.api.artifacts import router as artifacts_router
from app.api.security.audit_log import router as audit_log_router
from app.api.security.scorecard import router as scorecard_router
from app.api.security.events import router as events_router
from app.api.security.poam import router as poam_router
from app.api.security.telemetry import router as security_telemetry_router
from app.api.admin import router as admin_router
from app.api.llm import router as llm_router
from app.api.overrides import router as overrides_router
from app.api.activity_log import router as activity_log_router
from app.api.ai_assist import router as ai_assist_router
from app.api.assistant import router as assistant_router
from app.api.admin_prompts import router as admin_prompts_router
from app.api.common_controls import router as common_controls_router
from app.api.system_profile import router as system_profile_router
from app.api.enterprise_policies import router as enterprise_policies_router
from app.api.enterprise_procedures import router as enterprise_procedures_router
from app.api.remediation import router as remediation_router
from app.api.closure import router as closure_router
from app.api.test_dataset import router as test_dataset_router
from app.api.ingestion_config import router as ingestion_config_router
from app.api.control_catalog import router as control_catalog_router
from app.api.system_knowledge import router as system_knowledge_router
from app.api.integrations import router as integrations_router
from app.api.calibration import router as calibration_router
from app.api.assessment_policy import router as assessment_policy_router
from app.api.ssp import router as ssp_router
from app.core.config import get_settings
from app.core.database import Base, engine
from app.core.rate_limit import limiter
from app.middleware.audit import audit_middleware
from app.middleware.security_headers import security_headers_middleware

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create upload/output directories
    os.makedirs(settings.upload_dir, exist_ok=True)
    os.makedirs(settings.output_dir, exist_ok=True)
    # Seed internal control statuses on startup
    try:
        from app.core.database import AsyncSessionLocal
        from app.services.scorecard.seeder import seed_internal_controls
        from app.services.assessment_policy import seed_default_assessment_policy
        async with AsyncSessionLocal() as db:
            await seed_internal_controls(db)
            await seed_default_assessment_policy(db)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Control seeder failed: %s", exc)

    if settings.app_role == "worker":
        try:
            from app.services.job_worker import _recover_interrupted_work

            await _recover_interrupted_work()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Worker recovery failed: %s", exc)

    # Ensure artifact_controls column exists (added for Fix 4 — per-control tagging)
    try:
        from app.core.database import AsyncSessionLocal
        from sqlalchemy import text as _text3
        async with AsyncSessionLocal() as db:
            await db.execute(_text3(
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS artifact_controls JSONB"
            ))
            closure_table_exists = await db.scalar(
                _text3("SELECT to_regclass('public.control_closure_sessions')")
            )
            if closure_table_exists:
                await db.execute(_text3(
                    "ALTER TABLE control_closure_sessions ADD COLUMN IF NOT EXISTS updated_at "
                    "TIMESTAMP WITH TIME ZONE DEFAULT now()"
                ))
            await db.commit()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Schema migration failed: %s", exc)

    # Ensure document_type / document_intent columns exist (Stage 2 metadata)
    try:
        from app.core.database import AsyncSessionLocal
        from sqlalchemy import text as _text4
        async with AsyncSessionLocal() as db:
            await db.execute(_text4(
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS document_type VARCHAR(64)"
            ))
            await db.execute(_text4(
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS document_intent VARCHAR(64)"
            ))
            await db.commit()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Stage 2 column migration failed: %s", exc)

    # Ensure llm_challenge_note column exists (Option C — verdict challenge note)
    try:
        from app.core.database import AsyncSessionLocal
        from sqlalchemy import text as _text5
        async with AsyncSessionLocal() as db:
            await db.execute(_text5(
                "ALTER TABLE control_findings ADD COLUMN IF NOT EXISTS llm_challenge_note TEXT"
            ))
            await db.commit()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Option C column migration failed: %s", exc)

    # Create test_dataset_jobs table (standalone test ATO package generator)
    try:
        from app.core.database import AsyncSessionLocal
        from sqlalchemy import text as _text_td
        async with AsyncSessionLocal() as db:
            await db.execute(_text_td("""
                CREATE TABLE IF NOT EXISTS test_dataset_jobs (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    progress_detail TEXT,
                    error_message TEXT,
                    content_json JSONB,
                    generated_doc_ids JSONB,
                    created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_td(
                "CREATE INDEX IF NOT EXISTS ix_test_dataset_jobs_project_id "
                "ON test_dataset_jobs(project_id)"
            ))
            await db.commit()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("test_dataset_jobs migration failed: %s", exc)

    # Create assistant conversation tables
    try:
        from app.core.database import AsyncSessionLocal
        from sqlalchemy import text as _text_assistant
        async with AsyncSessionLocal() as db:
            await db.execute(_text_assistant("""
                CREATE TABLE IF NOT EXISTS assistant_conversations (
                    id SERIAL PRIMARY KEY,
                    mode VARCHAR(32) NOT NULL DEFAULT 'general',
                    title VARCHAR(255),
                    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
                    assessment_id INTEGER REFERENCES assessments(id) ON DELETE CASCADE,
                    created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_assistant(
                "CREATE INDEX IF NOT EXISTS ix_assistant_conversations_project_id ON assistant_conversations(project_id)"
            ))
            await db.execute(_text_assistant(
                "CREATE INDEX IF NOT EXISTS ix_assistant_conversations_assessment_id ON assistant_conversations(assessment_id)"
            ))
            await db.execute(_text_assistant("""
                CREATE TABLE IF NOT EXISTS assistant_context_attachments (
                    id SERIAL PRIMARY KEY,
                    conversation_id INTEGER NOT NULL REFERENCES assistant_conversations(id) ON DELETE CASCADE,
                    attachment_type VARCHAR(32) NOT NULL,
                    resource_id VARCHAR(128) NOT NULL,
                    label VARCHAR(255),
                    context_json JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_assistant(
                "CREATE INDEX IF NOT EXISTS ix_assistant_context_attachments_conversation_id "
                "ON assistant_context_attachments(conversation_id)"
            ))
            await db.execute(_text_assistant(
                "CREATE INDEX IF NOT EXISTS ix_assistant_context_attachments_type "
                "ON assistant_context_attachments(attachment_type)"
            ))
            await db.execute(_text_assistant("""
                CREATE TABLE IF NOT EXISTS assistant_messages (
                    id SERIAL PRIMARY KEY,
                    conversation_id INTEGER NOT NULL REFERENCES assistant_conversations(id) ON DELETE CASCADE,
                    role VARCHAR(16) NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_assistant(
                "CREATE INDEX IF NOT EXISTS ix_assistant_messages_conversation_id ON assistant_messages(conversation_id)"
            ))
            await db.commit()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("assistant conversation migration failed: %s", exc)

    # Ensure synthesized_narrative column exists (Obs 5 — skip_stage3 / synthesis flag)
    try:
        from app.core.database import AsyncSessionLocal
        from sqlalchemy import text as _text6
        async with AsyncSessionLocal() as db:
            await db.execute(_text6(
                "ALTER TABLE control_findings ADD COLUMN IF NOT EXISTS synthesized_narrative BOOLEAN DEFAULT FALSE"
            ))
            await db.commit()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("synthesized_narrative column migration failed: %s", exc)

    # Create validation + system knowledge tables
    try:
        from app.core.database import AsyncSessionLocal
        from sqlalchemy import text as _text_knowledge
        async with AsyncSessionLocal() as db:
            await db.execute(_text_knowledge("""
                CREATE TABLE IF NOT EXISTS artifact_validation_runs (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    source_mode VARCHAR(32) NOT NULL,
                    source_run_id INTEGER NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    summary_json JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_knowledge(
                "CREATE INDEX IF NOT EXISTS ix_artifact_validation_runs_project_id ON artifact_validation_runs(project_id)"
            ))
            await db.execute(_text_knowledge("""
                CREATE TABLE IF NOT EXISTS artifact_validation_results (
                    id SERIAL PRIMARY KEY,
                    validation_run_id INTEGER NOT NULL REFERENCES artifact_validation_runs(id) ON DELETE CASCADE,
                    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    integrity_status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    ingestion_status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    retrieval_status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    control_mapping_status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    details_json JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_knowledge(
                "CREATE INDEX IF NOT EXISTS ix_artifact_validation_results_validation_run_id ON artifact_validation_results(validation_run_id)"
            ))
            await db.execute(_text_knowledge("""
                CREATE TABLE IF NOT EXISTS package_viability_runs (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    source_mode VARCHAR(32) NOT NULL,
                    source_run_id INTEGER NOT NULL,
                    expected_profile VARCHAR(64),
                    viability_score DOUBLE PRECISION,
                    status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    summary_json JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_knowledge(
                "CREATE INDEX IF NOT EXISTS ix_package_viability_runs_project_id ON package_viability_runs(project_id)"
            ))
            await db.execute(_text_knowledge("""
                CREATE TABLE IF NOT EXISTS system_knowledge_runs (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    source_mode VARCHAR(32) NOT NULL,
                    source_run_id INTEGER NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    summary_json JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    completed_at TIMESTAMP WITH TIME ZONE
                )
            """))
            await db.execute(_text_knowledge(
                "CREATE INDEX IF NOT EXISTS ix_system_knowledge_runs_project_id ON system_knowledge_runs(project_id)"
            ))
            await db.execute(_text_knowledge("""
                CREATE TABLE IF NOT EXISTS system_knowledge_assertions (
                    id SERIAL PRIMARY KEY,
                    run_id INTEGER NOT NULL REFERENCES system_knowledge_runs(id) ON DELETE CASCADE,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    category VARCHAR(64) NOT NULL,
                    key VARCHAR(128) NOT NULL,
                    value_json JSONB,
                    normalized_value VARCHAR(255),
                    confidence DOUBLE PRECISION,
                    status VARCHAR(32) NOT NULL DEFAULT 'proposed',
                    rationale TEXT,
                    provenance_json JSONB,
                    reviewed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    reviewed_at TIMESTAMP WITH TIME ZONE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_knowledge(
                "CREATE INDEX IF NOT EXISTS ix_system_knowledge_assertions_project_id ON system_knowledge_assertions(project_id)"
            ))
            await db.execute(_text_knowledge("""
                CREATE TABLE IF NOT EXISTS tool_inventory (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    tool_name VARCHAR(255) NOT NULL,
                    tool_category VARCHAR(64),
                    vendor VARCHAR(128),
                    deployment_scope VARCHAR(128),
                    status VARCHAR(32) NOT NULL DEFAULT 'proposed',
                    confidence DOUBLE PRECISION,
                    provenance_json JSONB,
                    reviewed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    reviewed_at TIMESTAMP WITH TIME ZONE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_knowledge(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_tool_inventory_project_tool ON tool_inventory(project_id, tool_name)"
            ))
            await db.execute(_text_knowledge("""
                CREATE TABLE IF NOT EXISTS project_provider_responsibilities (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    provider_id INTEGER NOT NULL REFERENCES common_control_providers(id) ON DELETE CASCADE,
                    scope_type VARCHAR(32) NOT NULL DEFAULT 'family',
                    scope_id VARCHAR(64) NOT NULL,
                    inheritance_type VARCHAR(32) NOT NULL DEFAULT 'shared',
                    provider_coverage_status VARCHAR(32) NOT NULL DEFAULT 'partial',
                    system_responsibility TEXT,
                    rationale TEXT,
                    provenance_json JSONB,
                    status VARCHAR(32) NOT NULL DEFAULT 'proposed',
                    reviewed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    reviewed_at TIMESTAMP WITH TIME ZONE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_knowledge(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_project_provider_scope ON project_provider_responsibilities(project_id, provider_id, scope_type, scope_id)"
            ))
            await db.execute(_text_knowledge(
                "CREATE INDEX IF NOT EXISTS ix_project_provider_responsibilities_project_id ON project_provider_responsibilities(project_id)"
            ))
            await db.execute(_text_knowledge("""
                CREATE TABLE IF NOT EXISTS integration_accounts (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    connector_type VARCHAR(64) NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    auth_mode VARCHAR(32) NOT NULL DEFAULT 'dry_run',
                    status VARCHAR(32) NOT NULL DEFAULT 'configured',
                    config_json JSONB,
                    last_error TEXT,
                    last_tested_at TIMESTAMP WITH TIME ZONE,
                    last_run_at TIMESTAMP WITH TIME ZONE,
                    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_knowledge(
                "CREATE INDEX IF NOT EXISTS ix_integration_accounts_project_id ON integration_accounts(project_id)"
            ))
            await db.execute(_text_knowledge("""
                CREATE TABLE IF NOT EXISTS integration_runs (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    account_id INTEGER NOT NULL REFERENCES integration_accounts(id) ON DELETE CASCADE,
                    trigger_mode VARCHAR(32) NOT NULL DEFAULT 'manual',
                    status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    records_seen INTEGER NOT NULL DEFAULT 0,
                    assertions_created INTEGER NOT NULL DEFAULT 0,
                    summary_json JSONB,
                    error_message TEXT,
                    started_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    completed_at TIMESTAMP WITH TIME ZONE
                )
            """))
            await db.execute(_text_knowledge(
                "CREATE INDEX IF NOT EXISTS ix_integration_runs_project_id ON integration_runs(project_id)"
            ))
            await db.execute(_text_knowledge("""
                CREATE TABLE IF NOT EXISTS telemetry_snapshots (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    account_id INTEGER NOT NULL REFERENCES integration_accounts(id) ON DELETE CASCADE,
                    run_id INTEGER NOT NULL REFERENCES integration_runs(id) ON DELETE CASCADE,
                    snapshot_type VARCHAR(64) NOT NULL,
                    freshness_status VARCHAR(32) NOT NULL DEFAULT 'fresh',
                    summary_json JSONB,
                    collected_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_knowledge(
                "CREATE INDEX IF NOT EXISTS ix_telemetry_snapshots_project_id ON telemetry_snapshots(project_id)"
            ))
            await db.execute(_text_knowledge("""
                CREATE TABLE IF NOT EXISTS control_telemetry_posture (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    control_id VARCHAR(32) NOT NULL,
                    source_kind VARCHAR(32) NOT NULL DEFAULT 'integration',
                    source_ref VARCHAR(128) NOT NULL,
                    support_status VARCHAR(32) NOT NULL DEFAULT 'unknown',
                    freshness_status VARCHAR(32) NOT NULL DEFAULT 'fresh',
                    confidence DOUBLE PRECISION,
                    evidence_json JSONB,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_knowledge(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_control_telemetry_posture ON control_telemetry_posture(project_id, control_id, source_kind, source_ref)"
            ))
            await db.execute(_text_knowledge(
                "CREATE INDEX IF NOT EXISTS ix_control_telemetry_posture_project_id ON control_telemetry_posture(project_id)"
            ))
            await db.execute(_text_knowledge("""
                CREATE TABLE IF NOT EXISTS drift_records (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    account_id INTEGER REFERENCES integration_accounts(id) ON DELETE CASCADE,
                    run_id INTEGER REFERENCES integration_runs(id) ON DELETE CASCADE,
                    source_kind VARCHAR(32) NOT NULL DEFAULT 'integration',
                    scope_type VARCHAR(32) NOT NULL DEFAULT 'project',
                    scope_id VARCHAR(128) NOT NULL,
                    severity VARCHAR(16) NOT NULL DEFAULT 'low',
                    status VARCHAR(16) NOT NULL DEFAULT 'active',
                    title VARCHAR(255) NOT NULL,
                    details_json JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_knowledge(
                "CREATE INDEX IF NOT EXISTS ix_drift_records_project_id ON drift_records(project_id)"
            ))
            await db.execute(_text_knowledge(
                "CREATE INDEX IF NOT EXISTS ix_drift_records_status ON drift_records(status)"
            ))
            await db.execute(_text_knowledge("""
                CREATE TABLE IF NOT EXISTS security_collectors (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    name VARCHAR(255) NOT NULL,
                    collector_type VARCHAR(64) NOT NULL DEFAULT 'local_runtime',
                    status VARCHAR(32) NOT NULL DEFAULT 'active',
                    secret_encrypted BYTEA NOT NULL,
                    metadata_json JSONB,
                    last_seen_at TIMESTAMP WITH TIME ZONE,
                    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_knowledge(
                "CREATE INDEX IF NOT EXISTS ix_security_collectors_project_id ON security_collectors(project_id)"
            ))
            await db.execute(_text_knowledge("""
                CREATE TABLE IF NOT EXISTS security_collector_nonces (
                    id SERIAL PRIMARY KEY,
                    collector_id INTEGER NOT NULL REFERENCES security_collectors(id) ON DELETE CASCADE,
                    nonce VARCHAR(128) NOT NULL,
                    seen_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_knowledge(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_security_collector_nonce ON security_collector_nonces(collector_id, nonce)"
            ))
            await db.execute(_text_knowledge("""
                CREATE TABLE IF NOT EXISTS security_assets (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    asset_type VARCHAR(64) NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    external_id VARCHAR(255),
                    criticality VARCHAR(32) NOT NULL DEFAULT 'medium',
                    metadata_json JSONB,
                    last_seen_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_knowledge(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_security_asset_name ON security_assets(project_id, asset_type, name)"
            ))
            await db.execute(_text_knowledge(
                "CREATE INDEX IF NOT EXISTS ix_security_assets_project_id ON security_assets(project_id)"
            ))
            await db.execute(_text_knowledge("""
                CREATE TABLE IF NOT EXISTS security_scans (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    collector_id INTEGER REFERENCES security_collectors(id) ON DELETE SET NULL,
                    source VARCHAR(64) NOT NULL,
                    scan_type VARCHAR(64) NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    summary_json JSONB,
                    started_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    completed_at TIMESTAMP WITH TIME ZONE
                )
            """))
            await db.execute(_text_knowledge(
                "CREATE INDEX IF NOT EXISTS ix_security_scans_project_id ON security_scans(project_id)"
            ))
            await db.execute(_text_knowledge("""
                CREATE TABLE IF NOT EXISTS security_findings (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    asset_id INTEGER REFERENCES security_assets(id) ON DELETE SET NULL,
                    scan_id INTEGER REFERENCES security_scans(id) ON DELETE SET NULL,
                    source VARCHAR(64) NOT NULL,
                    category VARCHAR(64) NOT NULL,
                    severity VARCHAR(16) NOT NULL DEFAULT 'medium',
                    title VARCHAR(255) NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'open',
                    fix_available BOOLEAN NOT NULL DEFAULT FALSE,
                    cvss DOUBLE PRECISION,
                    detected_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    resolved_at TIMESTAMP WITH TIME ZONE,
                    metadata_json JSONB
                )
            """))
            await db.execute(_text_knowledge(
                "CREATE INDEX IF NOT EXISTS ix_security_findings_project_id ON security_findings(project_id)"
            ))
            await db.execute(_text_knowledge(
                "CREATE INDEX IF NOT EXISTS ix_security_findings_status ON security_findings(status)"
            ))
            await db.execute(_text_knowledge("""
                CREATE TABLE IF NOT EXISTS security_recommendations (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    key VARCHAR(128) NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    domain VARCHAR(64) NOT NULL,
                    severity VARCHAR(16) NOT NULL DEFAULT 'medium',
                    score_impact INTEGER NOT NULL DEFAULT 0,
                    status VARCHAR(32) NOT NULL DEFAULT 'open',
                    summary TEXT,
                    action TEXT,
                    metadata_json JSONB,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_knowledge(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_security_recommendation_key ON security_recommendations(project_id, key)"
            ))
            await db.execute(_text_knowledge(
                "CREATE INDEX IF NOT EXISTS ix_security_recommendations_project_id ON security_recommendations(project_id)"
            ))
            await db.execute(_text_knowledge("""
                CREATE TABLE IF NOT EXISTS security_build_snapshots (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    collector_id INTEGER REFERENCES security_collectors(id) ON DELETE SET NULL,
                    label VARCHAR(128) NOT NULL,
                    version VARCHAR(128),
                    commit_ref VARCHAR(128),
                    source VARCHAR(64) NOT NULL DEFAULT 'local_build',
                    status VARCHAR(32) NOT NULL DEFAULT 'completed',
                    build_date TIMESTAMP WITH TIME ZONE NOT NULL,
                    security_score INTEGER,
                    summary_json JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_knowledge(
                "CREATE INDEX IF NOT EXISTS ix_security_build_snapshots_project_id ON security_build_snapshots(project_id)"
            ))
            await db.execute(_text_knowledge(
                "CREATE INDEX IF NOT EXISTS ix_security_build_snapshots_build_date ON security_build_snapshots(build_date)"
            ))
            await db.execute(_text_knowledge("""
                CREATE TABLE IF NOT EXISTS security_runtime_snapshots (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    collector_id INTEGER REFERENCES security_collectors(id) ON DELETE SET NULL,
                    source VARCHAR(64) NOT NULL DEFAULT 'collector',
                    collected_at TIMESTAMP WITH TIME ZONE NOT NULL,
                    security_score INTEGER,
                    summary_json JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_knowledge(
                "CREATE INDEX IF NOT EXISTS ix_security_runtime_snapshots_project_id ON security_runtime_snapshots(project_id)"
            ))
            await db.execute(_text_knowledge(
                "CREATE INDEX IF NOT EXISTS ix_security_runtime_snapshots_collected_at ON security_runtime_snapshots(collected_at)"
            ))
            await db.execute(_text_knowledge("""
                CREATE TABLE IF NOT EXISTS security_tracked_settings (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    asset_id INTEGER NOT NULL REFERENCES security_assets(id) ON DELETE CASCADE,
                    setting_key VARCHAR(128) NOT NULL,
                    setting_label VARCHAR(255) NOT NULL,
                    category VARCHAR(64) NOT NULL,
                    current_value_json JSONB,
                    current_value_hash VARCHAR(64) NOT NULL,
                    first_seen_at TIMESTAMP WITH TIME ZONE NOT NULL,
                    last_seen_at TIMESTAMP WITH TIME ZONE NOT NULL,
                    last_changed_at TIMESTAMP WITH TIME ZONE NOT NULL,
                    source VARCHAR(64) NOT NULL
                )
            """))
            await db.execute(_text_knowledge(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_security_tracked_setting ON security_tracked_settings(project_id, asset_id, setting_key)"
            ))
            await db.execute(_text_knowledge(
                "CREATE INDEX IF NOT EXISTS ix_security_tracked_settings_project_id ON security_tracked_settings(project_id)"
            ))
            await db.execute(_text_knowledge("""
                CREATE TABLE IF NOT EXISTS security_setting_history (
                    id SERIAL PRIMARY KEY,
                    tracked_setting_id INTEGER NOT NULL REFERENCES security_tracked_settings(id) ON DELETE CASCADE,
                    snapshot_type VARCHAR(32) NOT NULL,
                    snapshot_id INTEGER NOT NULL,
                    value_json JSONB,
                    value_hash VARCHAR(64) NOT NULL,
                    observed_at TIMESTAMP WITH TIME ZONE NOT NULL
                )
            """))
            await db.execute(_text_knowledge(
                "CREATE INDEX IF NOT EXISTS ix_security_setting_history_tracked_setting_id ON security_setting_history(tracked_setting_id)"
            ))
            await db.execute(_text_knowledge("""
                CREATE TABLE IF NOT EXISTS security_change_events (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    asset_id INTEGER REFERENCES security_assets(id) ON DELETE SET NULL,
                    tracked_setting_id INTEGER REFERENCES security_tracked_settings(id) ON DELETE SET NULL,
                    event_type VARCHAR(64) NOT NULL,
                    category VARCHAR(64) NOT NULL,
                    old_value_json JSONB,
                    new_value_json JSONB,
                    detected_at TIMESTAMP WITH TIME ZONE NOT NULL,
                    source_snapshot_type VARCHAR(32) NOT NULL,
                    source_snapshot_id INTEGER NOT NULL,
                    impact_level VARCHAR(16) NOT NULL DEFAULT 'low',
                    impact_direction VARCHAR(16) NOT NULL DEFAULT 'neutral',
                    change_status VARCHAR(32) NOT NULL DEFAULT 'observed',
                    summary VARCHAR(255) NOT NULL,
                    details_json JSONB
                )
            """))
            await db.execute(_text_knowledge(
                "CREATE INDEX IF NOT EXISTS ix_security_change_events_project_id ON security_change_events(project_id)"
            ))
            await db.execute(_text_knowledge(
                "CREATE INDEX IF NOT EXISTS ix_security_change_events_detected_at ON security_change_events(detected_at)"
            ))
            await db.execute(_text_knowledge("""
                CREATE TABLE IF NOT EXISTS calibration_suites (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    name VARCHAR(255) NOT NULL,
                    description TEXT,
                    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_knowledge(
                "CREATE INDEX IF NOT EXISTS ix_calibration_suites_project_id ON calibration_suites(project_id)"
            ))
            await db.execute(_text_knowledge("""
                CREATE TABLE IF NOT EXISTS calibration_cases (
                    id SERIAL PRIMARY KEY,
                    suite_id INTEGER NOT NULL REFERENCES calibration_suites(id) ON DELETE CASCADE,
                    control_id VARCHAR(32) NOT NULL,
                    expected_status VARCHAR(32) NOT NULL,
                    expected_objectives_json JSONB,
                    expected_citations_json JSONB,
                    notes TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_knowledge(
                "CREATE INDEX IF NOT EXISTS ix_calibration_cases_suite_id ON calibration_cases(suite_id)"
            ))
            await db.execute(_text_knowledge("""
                CREATE TABLE IF NOT EXISTS calibration_runs (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    source_type VARCHAR(32) NOT NULL,
                    source_run_id INTEGER NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    summary_json JSONB,
                    runtime_snapshot_json JSONB,
                    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    completed_at TIMESTAMP WITH TIME ZONE
                )
            """))
            await db.execute(_text_knowledge(
                "CREATE INDEX IF NOT EXISTS ix_calibration_runs_project_id ON calibration_runs(project_id)"
            ))
            await db.execute(_text_knowledge(
                "CREATE INDEX IF NOT EXISTS ix_calibration_runs_source ON calibration_runs(source_type, source_run_id)"
            ))
            await db.execute(_text_knowledge("""
                CREATE TABLE IF NOT EXISTS calibration_case_results (
                    id SERIAL PRIMARY KEY,
                    run_id INTEGER NOT NULL REFERENCES calibration_runs(id) ON DELETE CASCADE,
                    control_id VARCHAR(32) NOT NULL,
                    expected_status VARCHAR(32) NOT NULL,
                    actual_status VARCHAR(32) NOT NULL,
                    match_status VARCHAR(32) NOT NULL,
                    delta_json JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_knowledge(
                "CREATE INDEX IF NOT EXISTS ix_calibration_case_results_run_id ON calibration_case_results(run_id)"
            ))
            await db.commit()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("system knowledge migration failed: %s", exc)

    # Create new ingestion pipeline v2 tables
    try:
        from app.core.database import AsyncSessionLocal
        from sqlalchemy import text as _text_ing
        async with AsyncSessionLocal() as db:
            # ingestion_config — admin-managed pipeline settings
            await db.execute(_text_ing("""
                CREATE TABLE IF NOT EXISTS ingestion_config (
                    id SERIAL PRIMARY KEY,
                    key VARCHAR(128) UNIQUE NOT NULL,
                    value_text TEXT,
                    value_encrypted BYTEA,
                    is_secret BOOLEAN NOT NULL DEFAULT FALSE,
                    description TEXT,
                    updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_ing(
                "CREATE INDEX IF NOT EXISTS ix_ingestion_config_key ON ingestion_config(key)"
            ))
            # ingestion_config_audit — change log (no secret values stored here)
            await db.execute(_text_ing("""
                CREATE TABLE IF NOT EXISTS ingestion_config_audit (
                    id SERIAL PRIMARY KEY,
                    config_key VARCHAR(128) NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    changed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    changed_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_ing(
                "CREATE INDEX IF NOT EXISTS ix_ingestion_config_audit_key ON ingestion_config_audit(config_key)"
            ))
            await db.execute(_text_ing("""
                CREATE TABLE IF NOT EXISTS control_corpus_versions (
                    id SERIAL PRIMARY KEY,
                    corpus_key VARCHAR(128) UNIQUE NOT NULL,
                    display_name VARCHAR(255) NOT NULL,
                    version VARCHAR(128) NOT NULL,
                    description TEXT,
                    corpus_json JSONB NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT FALSE,
                    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_ing(
                "CREATE INDEX IF NOT EXISTS ix_control_corpus_versions_active ON control_corpus_versions(is_active)"
            ))
            # ingestion_runs — one run per document-processing event
            await db.execute(_text_ing("""
                CREATE TABLE IF NOT EXISTS ingestion_runs (
                    id SERIAL PRIMARY KEY,
                    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    config_snapshot JSONB,
                    status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    current_stage VARCHAR(32),
                    stage_parse VARCHAR(32) NOT NULL DEFAULT 'pending',
                    stage_screen VARCHAR(32) NOT NULL DEFAULT 'pending',
                    stage_expand VARCHAR(32) NOT NULL DEFAULT 'pending',
                    stage_classify VARCHAR(32) NOT NULL DEFAULT 'pending',
                    stage_embed VARCHAR(32) NOT NULL DEFAULT 'pending',
                    lines_parsed INTEGER NOT NULL DEFAULT 0,
                    lines_screened INTEGER NOT NULL DEFAULT 0,
                    evidence_units_created INTEGER NOT NULL DEFAULT 0,
                    units_classified INTEGER NOT NULL DEFAULT 0,
                    units_embedded INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    error_stage VARCHAR(32),
                    started_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    completed_at TIMESTAMP WITH TIME ZONE,
                    triggered_by INTEGER REFERENCES users(id) ON DELETE SET NULL
                )
            """))
            await db.execute(_text_ing(
                "CREATE INDEX IF NOT EXISTS ix_ingestion_runs_document_id ON ingestion_runs(document_id)"
            ))
            await db.execute(_text_ing(
                "CREATE INDEX IF NOT EXISTS ix_ingestion_runs_status ON ingestion_runs(status)"
            ))
            await db.execute(_text_ing(
                "ALTER TABLE ingestion_runs ADD COLUMN IF NOT EXISTS corpus_version VARCHAR(128)"
            ))
            await db.execute(_text_ing("""
                CREATE TABLE IF NOT EXISTS parsed_documents (
                    id SERIAL PRIMARY KEY,
                    run_id INTEGER NOT NULL REFERENCES ingestion_runs(id) ON DELETE CASCADE,
                    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    parser_name VARCHAR(128),
                    parser_version VARCHAR(128),
                    parser_metadata JSONB,
                    source_filename VARCHAR(512) NOT NULL,
                    file_type VARCHAR(64) NOT NULL,
                    page_count INTEGER,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_ing(
                "CREATE INDEX IF NOT EXISTS ix_parsed_documents_run_id ON parsed_documents(run_id)"
            ))
            # parsed_lines — line-level source records
            await db.execute(_text_ing("""
                CREATE TABLE IF NOT EXISTS parsed_lines (
                    id SERIAL PRIMARY KEY,
                    run_id INTEGER NOT NULL REFERENCES ingestion_runs(id) ON DELETE CASCADE,
                    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    line_number INTEGER NOT NULL,
                    page_number INTEGER,
                    section_path TEXT,
                    table_id VARCHAR(128),
                    row_index INTEGER,
                    col_index INTEGER,
                    cell_label VARCHAR(255),
                    content_type VARCHAR(32) NOT NULL DEFAULT 'text',
                    content TEXT NOT NULL
                )
            """))
            await db.execute(_text_ing(
                "CREATE INDEX IF NOT EXISTS ix_parsed_lines_run_id ON parsed_lines(run_id)"
            ))
            await db.execute(_text_ing(
                "CREATE INDEX IF NOT EXISTS ix_parsed_lines_document_id ON parsed_lines(document_id)"
            ))
            await db.execute(_text_ing(
                "ALTER TABLE parsed_lines ADD COLUMN IF NOT EXISTS block_id VARCHAR(128)"
            ))
            await db.execute(_text_ing(
                "ALTER TABLE parsed_lines ADD COLUMN IF NOT EXISTS block_type VARCHAR(64)"
            ))
            # screening_results
            await db.execute(_text_ing("""
                CREATE TABLE IF NOT EXISTS screening_results (
                    id SERIAL PRIMARY KEY,
                    line_id INTEGER NOT NULL UNIQUE REFERENCES parsed_lines(id) ON DELETE CASCADE,
                    run_id INTEGER NOT NULL REFERENCES ingestion_runs(id) ON DELETE CASCADE,
                    relevance_score FLOAT NOT NULL DEFAULT 0.0,
                    candidate_controls JSONB,
                    candidate_enhancements JSONB,
                    rationale TEXT,
                    above_threshold BOOLEAN NOT NULL DEFAULT FALSE,
                    screened_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_ing(
                "CREATE INDEX IF NOT EXISTS ix_screening_results_run_id ON screening_results(run_id)"
            ))
            await db.execute(_text_ing(
                "CREATE INDEX IF NOT EXISTS ix_screening_results_line_id ON screening_results(line_id)"
            ))
            # evidence_units
            await db.execute(_text_ing("""
                CREATE TABLE IF NOT EXISTS evidence_units (
                    id SERIAL PRIMARY KEY,
                    run_id INTEGER NOT NULL REFERENCES ingestion_runs(id) ON DELETE CASCADE,
                    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    trigger_line_id INTEGER NOT NULL REFERENCES parsed_lines(id) ON DELETE CASCADE,
                    source_line_ids JSONB NOT NULL,
                    content TEXT NOT NULL,
                    page_numbers JSONB,
                    section_path TEXT,
                    table_coordinates JSONB,
                    token_count INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_ing(
                "CREATE INDEX IF NOT EXISTS ix_evidence_units_run_id ON evidence_units(run_id)"
            ))
            await db.execute(_text_ing(
                "CREATE INDEX IF NOT EXISTS ix_evidence_units_document_id ON evidence_units(document_id)"
            ))
            # evidence_classifications
            await db.execute(_text_ing("""
                CREATE TABLE IF NOT EXISTS evidence_classifications (
                    id SERIAL PRIMARY KEY,
                    unit_id INTEGER NOT NULL UNIQUE REFERENCES evidence_units(id) ON DELETE CASCADE,
                    run_id INTEGER NOT NULL REFERENCES ingestion_runs(id) ON DELETE CASCADE,
                    control_ids JSONB,
                    enhancement_ids JSONB,
                    artifact_type VARCHAR(64),
                    evidence_strength VARCHAR(32),
                    evidence_language_type VARCHAR(64),
                    explanation TEXT,
                    model_name VARCHAR(128),
                    model_confidence FLOAT,
                    classified_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_ing(
                "CREATE INDEX IF NOT EXISTS ix_evidence_classifications_run_id ON evidence_classifications(run_id)"
            ))
            # evidence_embeddings — Voyage vectors
            await db.execute(_text_ing("""
                CREATE TABLE IF NOT EXISTS evidence_embeddings (
                    id SERIAL PRIMARY KEY,
                    unit_id INTEGER NOT NULL UNIQUE REFERENCES evidence_units(id) ON DELETE CASCADE,
                    run_id INTEGER NOT NULL REFERENCES ingestion_runs(id) ON DELETE CASCADE,
                    model_name VARCHAR(128) NOT NULL,
                    embedding vector(1024),
                    embedded_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_ing(
                "CREATE INDEX IF NOT EXISTS ix_evidence_embeddings_run_id ON evidence_embeddings(run_id)"
            ))
            await db.execute(_text_ing(
                "ALTER TABLE document_chunks ALTER COLUMN section_title TYPE TEXT"
            ))
            from app.services.ingestion.corpus_store import ensure_default_corpus
            await ensure_default_corpus(db)
            await db.commit()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Ingestion pipeline v2 migration failed: %s", exc)

    # Create staged assessment pipeline tables
    try:
        from app.core.database import AsyncSessionLocal
        from sqlalchemy import text as _text_assess
        async with AsyncSessionLocal() as db:
            await db.execute(_text_assess("""
                CREATE TABLE IF NOT EXISTS assessment_criteria_packages (
                    id SERIAL PRIMARY KEY,
                    assessment_id INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
                    control_id VARCHAR(32) NOT NULL,
                    control_family VARCHAR(8) NOT NULL,
                    control_title VARCHAR(512) NOT NULL,
                    control_statement TEXT NOT NULL,
                    supplemental_guidance TEXT,
                    assessment_objectives JSONB,
                    criteria_metadata JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    CONSTRAINT uq_assessment_criteria_control UNIQUE (assessment_id, control_id)
                )
            """))
            await db.execute(_text_assess(
                "CREATE INDEX IF NOT EXISTS ix_assessment_criteria_packages_assessment_id "
                "ON assessment_criteria_packages(assessment_id)"
            ))
            await db.execute(_text_assess(
                "CREATE INDEX IF NOT EXISTS ix_assessment_criteria_packages_control_id "
                "ON assessment_criteria_packages(control_id)"
            ))
            await db.execute(_text_assess("""
                CREATE TABLE IF NOT EXISTS assessment_evidence_triage (
                    id SERIAL PRIMARY KEY,
                    assessment_id INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
                    control_id VARCHAR(32) NOT NULL,
                    unit_id INTEGER REFERENCES evidence_units(id) ON DELETE SET NULL,
                    document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
                    source_type VARCHAR(32),
                    artifact_type VARCHAR(64),
                    evidence_strength VARCHAR(32),
                    evidence_language_type VARCHAR(64),
                    document_type VARCHAR(64),
                    document_intent VARCHAR(64),
                    triage_role VARCHAR(32) NOT NULL DEFAULT 'supporting',
                    relevance_score FLOAT NOT NULL DEFAULT 0.0,
                    citation_label VARCHAR(512),
                    rationale TEXT,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """))
            await db.execute(_text_assess(
                "CREATE INDEX IF NOT EXISTS ix_assessment_evidence_triage_assessment_id "
                "ON assessment_evidence_triage(assessment_id)"
            ))
            await db.execute(_text_assess(
                "CREATE INDEX IF NOT EXISTS ix_assessment_evidence_triage_control_id "
                "ON assessment_evidence_triage(control_id)"
            ))
            await db.execute(_text_assess("""
                CREATE TABLE IF NOT EXISTS objective_determinations (
                    id SERIAL PRIMARY KEY,
                    assessment_id INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
                    control_id VARCHAR(32) NOT NULL,
                    objective_id VARCHAR(128) NOT NULL,
                    objective_text TEXT,
                    status VARCHAR(32) NOT NULL,
                    rationale TEXT,
                    supporting_citations JSONB,
                    contradictory_citations JSONB,
                    missing_evidence TEXT,
                    confidence_score FLOAT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    CONSTRAINT uq_objective_determination UNIQUE (assessment_id, control_id, objective_id)
                )
            """))
            await db.execute(_text_assess(
                "CREATE INDEX IF NOT EXISTS ix_objective_determinations_assessment_id "
                "ON objective_determinations(assessment_id)"
            ))
            await db.execute(_text_assess(
                "CREATE INDEX IF NOT EXISTS ix_objective_determinations_control_id "
                "ON objective_determinations(control_id)"
            ))
            await db.execute(_text_assess("""
                CREATE TABLE IF NOT EXISTS control_determinations (
                    id SERIAL PRIMARY KEY,
                    assessment_id INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
                    control_id VARCHAR(32) NOT NULL,
                    status VARCHAR(32) NOT NULL,
                    confidence_score FLOAT,
                    objective_summary JSONB,
                    deficiency_summary TEXT,
                    evidence_summary TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    CONSTRAINT uq_control_determination UNIQUE (assessment_id, control_id)
                )
            """))
            await db.execute(_text_assess(
                "CREATE INDEX IF NOT EXISTS ix_control_determinations_assessment_id "
                "ON control_determinations(assessment_id)"
            ))
            await db.execute(_text_assess(
                "CREATE INDEX IF NOT EXISTS ix_control_determinations_control_id "
                "ON control_determinations(control_id)"
            ))
            await db.execute(_text_assess("""
                CREATE TABLE IF NOT EXISTS assessment_challenges (
                    id SERIAL PRIMARY KEY,
                    assessment_id INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
                    control_id VARCHAR(32) NOT NULL,
                    concur BOOLEAN NOT NULL DEFAULT TRUE,
                    dissent_note TEXT,
                    challenged_objectives JSONB,
                    model_name VARCHAR(128),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    CONSTRAINT uq_assessment_challenge UNIQUE (assessment_id, control_id)
                )
            """))
            await db.execute(_text_assess(
                "CREATE INDEX IF NOT EXISTS ix_assessment_challenges_assessment_id "
                "ON assessment_challenges(assessment_id)"
            ))
            await db.execute(_text_assess(
                "CREATE INDEX IF NOT EXISTS ix_assessment_challenges_control_id "
                "ON assessment_challenges(control_id)"
            ))
            await db.execute(_text_assess("""
                CREATE TABLE IF NOT EXISTS assessment_rollups (
                    id SERIAL PRIMARY KEY,
                    assessment_id INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
                    readiness VARCHAR(32) NOT NULL DEFAULT 'insufficient_evidence',
                    summary_json JSONB,
                    residual_risk_summary TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    CONSTRAINT uq_assessment_rollup UNIQUE (assessment_id)
                )
            """))
            await db.execute(_text_assess(
                "CREATE INDEX IF NOT EXISTS ix_assessment_rollups_assessment_id "
                "ON assessment_rollups(assessment_id)"
            ))
            await db.commit()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Assessment pipeline migration failed: %s", exc)

    yield


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    docs_url="/docs" if settings.app_env == "development" else None,
    redoc_url="/redoc" if settings.app_env == "development" else None,
    openapi_url="/openapi.json" if settings.app_env == "development" else None,
    lifespan=lifespan,
)

# ── Middleware (order matters — outermost runs first) ──────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Custom middleware (registered via add_middleware using starlette BaseHTTPMiddleware)
from starlette.middleware.base import BaseHTTPMiddleware
app.add_middleware(BaseHTTPMiddleware, dispatch=security_headers_middleware)
app.add_middleware(BaseHTTPMiddleware, dispatch=audit_middleware)

# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(auth.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(projects_router, prefix="/api")
app.include_router(documents_router, prefix="/api")
app.include_router(assessments_router, prefix="/api")
app.include_router(reports_router, prefix="/api")
app.include_router(artifacts_router, prefix="/api")
app.include_router(audit_log_router, prefix="/api")
app.include_router(scorecard_router, prefix="/api")
app.include_router(events_router, prefix="/api")
app.include_router(poam_router, prefix="/api")
app.include_router(security_telemetry_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(llm_router, prefix="/api")
app.include_router(overrides_router, prefix="/api")
app.include_router(activity_log_router, prefix="/api")
app.include_router(ai_assist_router, prefix="/api")
app.include_router(assistant_router, prefix="/api")
app.include_router(admin_prompts_router, prefix="/api")
app.include_router(common_controls_router, prefix="/api")
app.include_router(system_profile_router, prefix="/api")
app.include_router(enterprise_policies_router, prefix="/api")
app.include_router(enterprise_procedures_router, prefix="/api")
app.include_router(remediation_router, prefix="/api")
app.include_router(closure_router, prefix="/api")
app.include_router(test_dataset_router, prefix="/api")
app.include_router(ingestion_config_router, prefix="/api")
app.include_router(control_catalog_router, prefix="/api")
app.include_router(system_knowledge_router, prefix="/api")
if settings.enable_experimental_cato:
    app.include_router(integrations_router, prefix="/api")
app.include_router(calibration_router, prefix="/api")
app.include_router(assessment_policy_router, prefix="/api")
app.include_router(ssp_router, prefix="/api")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "app": settings.app_name}
