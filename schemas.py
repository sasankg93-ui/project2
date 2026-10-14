from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class MediaType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"


ALLOWED_CONTENT_TYPES = {
    "image/jpeg": MediaType.IMAGE,
    "image/png": MediaType.IMAGE,
    "image/webp": MediaType.IMAGE,
    "video/mp4": MediaType.VIDEO,
    "video/quicktime": MediaType.VIDEO,
    "video/webm": MediaType.VIDEO,
}


class PresignRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str
    size_bytes: int = Field(gt=0)


class PresignResponse(BaseModel):
    source_key: str
    upload_url: str
    method: Literal["PUT"] = "PUT"
    headers: dict[str, str]
    expires_in: int


class ImageOptions(BaseModel):
    width: int | None = Field(default=None, gt=0, le=8000)
    height: int | None = Field(default=None, gt=0, le=8000)
    quality: int = Field(default=82, ge=1, le=100)
    watermark: bool = False


class VideoOptions(BaseModel):
    max_height: int = Field(default=720, gt=0, le=2160)
    thumbnail: bool = True
    watermark: bool = False


class JobCreate(BaseModel):
    source_key: str
    media_type: MediaType
    image: ImageOptions | None = None
    video: VideoOptions | None = None
    callback_url: str | None = None


class JobOut(BaseModel):
    job_id: str
    status: JobStatus
    media_type: MediaType
    source_key: str
    created_at: datetime
    updated_at: datetime
    result_urls: list[str] = []
    error: str | None = None
