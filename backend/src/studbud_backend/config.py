from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "StudBud API"
    environment: str = "development"
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = 0.1

    database_url: str = "postgresql+asyncpg://studbud:studbud@localhost:5432/studbud"

    admin_api_secret: str | None = None
    key_pepper: str = "dev-only-pepper-change-me"

    session_cookie_name: str = "sb_session"
    csrf_cookie_name: str = "sb_csrf"
    session_ttl_days: int = 7
    access_key_ttl_days: int = 30
    cookie_secure: bool = False
    cookie_samesite: str = "lax"
    cookie_domain: str | None = None

    frontend_origins: str = "http://localhost:4200"

    auto_create_tables: bool = True
    worker_enabled: bool = True

    max_upload_mb: int = 25
    max_pages: int = 200

    user_max_documents: int = 50
    user_max_pages: int = 5000
    user_max_storage_mb: int = 1024
    user_daily_uploads: int = 20
    user_daily_explanations: int = 100

    sign_in_rate_limit: int = 10
    admin_rate_limit: int = 60
    chat_rate_limit: int = 20

    storage_backend: str = "auto"  # auto | local | r2
    storage_dir: str = "storage"
    r2_endpoint: str | None = None
    r2_bucket: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None

    groq_api_key: str | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_chat_model: str = "openai/gpt-oss-120b"
    groq_vision_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"
    vision_provider: str = "auto"  # auto | gemini | groq | none
    gemini_api_key: str | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_vision_model: str = "gemini-3.5-flash-lite"
    gemini_embedding_model: str = "gemini-embedding-001"
    embedding_model: str = "nomic-embed-text-v1_5"
    embedding_dim: int = 768
    embedding_provider: str = "auto"  # auto | fastembed | groq | hash
    local_embedding_model: str = "nomic-ai/nomic-embed-text-v1.5-Q"
    fastembed_cache_dir: str | None = None
    embedding_threads: int = 2

    chunk_target_tokens: int = 650
    chunk_overlap_tokens: int = 100
    max_figures_per_page: int = 8
    max_figure_captions: int = 24
    page_preview_dpi: int = 100
    figure_captioning_enabled: bool = True

    ocr_enabled: bool = True
    ocr_language: str = "eng"
    ocr_dpi: int = 200

    @property
    def frontend_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.frontend_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
