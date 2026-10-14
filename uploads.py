from fastapi import APIRouter, Depends, HTTPException

from ..config import Settings, get_settings
from ..deps import get_s3, require_api_key
from ..schemas import ALLOWED_CONTENT_TYPES, PresignRequest, PresignResponse
from ..storage import new_source_key, presign_put

router = APIRouter(prefix="/v1/uploads", tags=["uploads"], dependencies=[Depends(require_api_key)])


@router.post("/presign", response_model=PresignResponse)
def presign(body: PresignRequest, s: Settings = Depends(get_settings), s3=Depends(get_s3)):
    if body.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(415, f"Unsupported content type: {body.content_type}")
    if body.size_bytes > s.max_upload_bytes:
        raise HTTPException(413, "File too large")
    key = new_source_key(s, body.filename)
    url = presign_put(s3, s, key, body.content_type)
    return PresignResponse(
        source_key=key,
        upload_url=url,
        headers={"Content-Type": body.content_type},
        expires_in=s.s3_presign_expires,
    )
