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


def download(client, s: Settings, key: str, dest) -> None:
    client.download_file(s.s3_bucket, key, str(dest))


def upload(client, s: Settings, key: str, path, content_type: str) -> None:
    client.upload_file(
        str(path),
        s.s3_bucket,
        key,
        ExtraArgs={
            "ContentType": content_type,
            # Keys include the job id, so each URL is immutable and safe to cache forever.
            "CacheControl": "public, max-age=31536000, immutable",
        },
    )


def result_url(client, s: Settings, key: str) -> str:
    if s.cdn_domain:
        return f"https://{s.cdn_domain}/{key}"
    return client.generate_presigned_url(
        "get_object", Params={"Bucket": s.s3_bucket, "Key": key}, ExpiresIn=7 * 24 * 3600
    )
