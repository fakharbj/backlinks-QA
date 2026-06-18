"""Object storage (S3 / MinIO) — raw snapshots, report files, import uploads.

Large blobs never touch Postgres (Arch §10); only the object key is stored. boto3
is synchronous, so async callers use ``asyncio.to_thread`` wrappers.
"""

from __future__ import annotations

import asyncio
import uuid
from functools import lru_cache

import boto3
from botocore.config import Config

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)
_buckets_ready = False

ALL_BUCKETS = (
    settings.S3_BUCKET_SNAPSHOTS,
    settings.S3_BUCKET_REPORTS,
    settings.S3_BUCKET_IMPORTS,
)


@lru_cache
def _client():
    return boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT_URL,
        region_name=settings.S3_REGION,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        config=Config(
            s3={"addressing_style": "path" if settings.S3_FORCE_PATH_STYLE else "auto"},
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


def ensure_buckets() -> None:
    global _buckets_ready
    if _buckets_ready:
        return
    client = _client()
    ready = True
    for bucket in ALL_BUCKETS:
        try:
            client.head_bucket(Bucket=bucket)
        except Exception:
            try:
                client.create_bucket(Bucket=bucket)
                log.info("bucket_created", bucket=bucket)
            except Exception as exc:  # noqa: BLE001
                ready = False
                log.warning("bucket_create_failed", bucket=bucket, error=str(exc))
    _buckets_ready = ready


def put_bytes(bucket: str, key: str, data: bytes, content_type: str) -> str:
    ensure_buckets()
    _client().put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
    return key


def get_bytes(bucket: str, key: str) -> bytes:
    return _client().get_object(Bucket=bucket, Key=key)["Body"].read()


def presigned_url(bucket: str, key: str, *, expires: int | None = None) -> str:
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires or settings.SIGNED_URL_TTL_SECONDS,
    )


def snapshot_key(backlink_id: str, kind: str = "raw") -> str:
    return f"{backlink_id}/{kind}/{uuid.uuid4().hex}.html"


# ── Async wrappers ──────────────────────────────────────────────────────────────
async def put_bytes_async(bucket: str, key: str, data: bytes, content_type: str) -> str:
    return await asyncio.to_thread(put_bytes, bucket, key, data, content_type)


async def get_bytes_async(bucket: str, key: str) -> bytes:
    return await asyncio.to_thread(get_bytes, bucket, key)


async def presigned_url_async(bucket: str, key: str, *, expires: int | None = None) -> str:
    return await asyncio.to_thread(presigned_url, bucket, key, expires=expires)
