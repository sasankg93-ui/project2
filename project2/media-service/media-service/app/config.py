from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_api_key: str = "change-me"

    # AWS
    aws_region: str = "ap-south-1"
    s3_bucket: str
    s3_upload_prefix: str = "uploads/"
    s3_output_prefix: str = "processed/"
    s3_presign_expires: int = 900
    s3_endpoint_url: str | None = None
    # CloudFront domain (e.g. d123.cloudfront.net). If empty, results are presigned S3 GET URLs.
    cdn_domain: str = ""

    # Brokers / cache
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672//"
    redis_url: str = "redis://localhost:6379/0"
    job_ttl_seconds: int = 7 * 24 * 3600

    # Limits
    max_upload_bytes: int = 2 * 1024**3
    max_image_pixels: int = 60_000_000
    max_video_seconds: int = 1800

    # Processing
    work_dir: str = "/tmp/media-work"
    watermark_text: str = ""
    watermark_font_path: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    ffmpeg_threads: int = 2
    ffmpeg_timeout_seconds: int = 1300

    # Worker metrics exporter (0 = disabled)
    worker_metrics_port: int = 0


@lru_cache
def get_settings() -> Settings:
    return Settings()
