from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Server-side settings loaded from environment variables."""

    database_url: str
    web_origin: str = "http://localhost:3000"
    supabase_url: str
    supabase_jwt_audience: str = "authenticated"
    supabase_storage_bucket: str = "application-documents"
    supabase_service_role_key: str

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
