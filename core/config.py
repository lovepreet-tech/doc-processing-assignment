"""App-wide settings, loaded from environment variables / .env file."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # postgres
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/extraction"

    # redis - celery broker/result backend and progress pub/sub
    redis_url: str = "redis://localhost:6379/0"

    # openai
    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4o-mini"
    # model for the single cross-file review pass; empty means openai_chat_model
    openai_review_model: str = ""
    openai_embedding_model: str = "text-embedding-3-small"
    openai_embedding_dim: int = 1536
    # max wait for any OpenAI call (chat or embeddings)
    openai_request_timeout_seconds: float = 30.0

    # file storage - local disk path for raw uploads
    storage_dir: str = "./uploaded_files"

    # default session retention window
    default_retention_ttl_days: int = 90


@lru_cache
def get_settings() -> Settings:
    return Settings()
