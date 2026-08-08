"""ATO Bot â€” FastAPI application entry point."""
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
        from app.services.ingestion.corpus_store import ensure_default_corpus
        from app.services.scorecard.seeder import seed_internal_controls
        from app.services.assessment_policy import seed_default_assessment_policy
        async with AsyncSessionLocal() as db:
            await seed_internal_controls(db)
            await seed_default_assessment_policy(db)
            await ensure_default_corpus(db)
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

    # Schema changes are owned by Alembic and run before this process starts.
    yield


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    docs_url="/docs" if settings.app_env == "development" else None,
    redoc_url="/redoc" if settings.app_env == "development" else None,
    openapi_url="/openapi.json" if settings.app_env == "development" else None,
    lifespan=lifespan,
)

# â”€â”€ Middleware (order matters â€” outermost runs first) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

# â”€â”€ Routers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
