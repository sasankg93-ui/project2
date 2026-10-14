import asyncio
import re
import uuid

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .config import Settings


def make_s3_client(s: Settings):
    return boto3.client(
        "s3",
        region_name=s.aws_region,
        endpoint_url=s.s3_endpoint_url or None,
        config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
    )


def safe_filename(name: str) -> str:
    name = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:100] or "file"


def new_source_key(s: Settings, filename: str) -> str:
    return f"{s.s3_upload_prefix}{uuid.uuid4().hex}/{safe_filename(filename)}"


def presign_put(client, s: Settings, key: str, content_type: str) -> str:
    # ContentType is signed, so the client must send the same header.
    return client.generate_presigned_url(
        "put_object",
        Params={"Bucket": s.s3_bucket, "Key": key, "ContentType": content_type},
        ExpiresIn=s.s3_presign_expires,
    )


def _head(client, bucket: str, key: str) -> dict | None:
    try:
        return client.head_object(Bucket=bucket, Key=key)
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


async def head_object(client, s: Settings, key: str) -> dict | None:
    # boto3 is blocking; keep it off the event loop.
    return await asyncio.to_thread(_head, client, s.s3_bucket, key)
