from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "insights-collect"
    app_env: str = "dev"
    log_level: str = "INFO"

    database_url: str = Field(
        default="postgresql+asyncpg://insights:insights@localhost:5432/insights_collect"
    )
    database_url_sync: str = Field(
        default="postgresql://insights:insights@localhost:5432/insights_collect"
    )

    storage_dir: Path = Path("./storage")
    reports_dir: Path = Path("./storage/reports")
    pdfs_dir: Path = Path("./storage/pdfs")
    outlines_dir: Path = Path("./storage/outlines")

    anthropic_api_key: str = ""
    google_api_key: str = ""
    openai_api_key: str = ""
    xai_api_key: str = ""
    perplexity_api_key: str = ""
    dashscope_api_key: str = ""
    deepseek_api_key: str = ""

    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536

    langsmith_api_key: str = ""
    langsmith_project: str = "insights-collect"

    max_tokens_per_run: int = 2_000_000
    max_provider_calls_per_run: int = 300
    cost_cap_usd_per_run: float = 10.0
    max_reflection_rounds: int = 3
    provider_call_timeout_s: int = 90
    smoke_call_timeout_s: int = 60

    frontend_url: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
