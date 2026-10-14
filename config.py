from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_api_key: str = "change-me"
    aws_region: str = "ap-south-1"
    s3_bucket: str
    s3_upload_prefix: str = "uploads/"
    s3_presign_expires: int = 900
    s3_endpoint_url: str | None = None
    redis_url: str = "redis://localhost:6379/0"
    job_ttl_seconds: int = 7 * 24 * 3600
    max_upload_bytes: int = 2 * 1024**3


@lru_cache
def get_settings() -> Settings:
    return Settings()
