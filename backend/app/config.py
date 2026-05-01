from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "local"
    app_name: str = "Manage AI"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    database_url: str = "postgresql+asyncpg://app:app@localhost:5432/manage_ai"
    sync_database_url: str = "postgresql://app:app@localhost:5432/manage_ai"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret_key: str = Field(default="change-me")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    cors_origins: str = "http://localhost:3010,http://127.0.0.1:3010"

    seed_admin_email: str = "admin@example.com"
    seed_admin_password: str = "change-this-password"
    seed_admin_name: str = "Admin User"

    llm_provider: str = "groq"
    groq_api_key: str | None = Field(default=None, strip_whitespace=True)
    groq_model_orchestrator: str = "llama-3.3-70b-versatile"
    groq_model_learner: str = "llama-3.1-8b-instant"
    groq_model_decision_maker: str = "llama-3.3-70b-versatile"
    groq_model_task_generator: str = "llama-3.1-8b-instant"

    anthropic_api_key: str | None = None
    anthropic_model_orchestrator: str = "claude-sonnet-4-6"
    anthropic_model_decision_maker: str = "claude-sonnet-4-6"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model_learner: str = "llama3"
    ollama_model_task_generator: str = "llama3"
    ollama_embedding_model: str = "nomic-embed-text"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
