from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Application
    app_name: str = "ATO Bot"
    app_env: str = "development"
    app_role: str = "web"
    api_base_url: str = "http://localhost:8000"
    frontend_base_url: str = "http://localhost:3001"
    oscal_namespace: str = "urn:ato-bot:oscal"
    secret_key: str
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    max_active_refresh_sessions_per_user: int = 5
    stale_refresh_session_days: int = 3
    stale_ingestion_run_hours: int = 1
    algorithm: str = "HS256"

    # Database
    database_url: str

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # File storage
    upload_dir: str = "./uploads"
    output_dir: str = "./outputs"
    max_upload_size_mb: int = 200

    # LLM — Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:70b"
    ollama_num_ctx: int = 4096
    ollama_embedding_model: str = "nomic-embed-text"
    # Reasoning depth: none | low | medium | high
    # "high" enables chain-of-thought (think:true) on supported models.
    # Overridden at runtime by the DB ingestion config value when available.
    ollama_reasoning_effort: str = "medium"

    # LLM — Claude
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"

    # LLM — Bedrock
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"
    bedrock_model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"

    # Assessment
    assessment_concurrency: int = 20
    default_context_strategy: str = "rag"
    default_llm_provider: str = "ollama"
    remediation_parallel_controls: int = 3
    enable_experimental_cato: bool = False

    # Background worker
    worker_poll_interval_secs: float = 1.0
    worker_assessment_slots: int = 1
    worker_report_slots: int = 1
    worker_test_dataset_slots: int = 1
    worker_ingestion_slots: int = 2

    # Security
    allowed_origins: str = "http://localhost:5173,http://localhost:3000"
    max_login_attempts: int = 5
    lockout_minutes: int = 15
    cors_allow_credentials: bool = True

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]

    def validate_security_posture(self) -> None:
        if self.app_env != "production":
            return
        weak_secrets = {"changeme", "secret", "dev-secret", "development", "ato-bot-secret"}
        if len(self.secret_key or "") < 32 or self.secret_key.lower() in weak_secrets:
            raise ValueError("Production SECRET_KEY must be at least 32 characters and not use a weak default value.")
        if not self.allowed_origins_list:
            raise ValueError("Production ALLOWED_ORIGINS must not be empty.")
        if "*" in self.allowed_origins_list and self.cors_allow_credentials:
            raise ValueError("Wildcard CORS origins cannot be used with credentials enabled in production.")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_security_posture()
    return settings
