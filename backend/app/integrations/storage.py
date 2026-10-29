"""S3-compatible object storage (MinIO in development, AWS S3/GCS gateway in production)."""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, BinaryIO

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings
from app.core.exceptions import UpstreamError
from app.core.logging import get_logger

log = get_logger("ofme.storage")


@dataclass(slots=True)
class StoredObject:
    key: str
    bucket: str
    size: int
    checksum_sha256: str
    etag: str | None


class ObjectStorage:
    def __init__(self) -> None:
        self.buckets = {"backups": settings.S3_BUCKET_BACKUPS, "artifacts": settings.S3_BUCKET_ARTIFACTS}
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT or None,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            region_name=settings.S3_REGION,
            use_ssl=settings.S3_USE_SSL,
            config=Config(
                signature_version="s3v4", s3={"addressing_style": "path"}, retries={"max_attempts": 5}
            ),
        )

    # ------------------------------------------------------------------ buckets
    def healthcheck(self) -> bool:
        """Round-trip to the object store; used by readiness probes."""
        try:
            self._client.list_buckets()
            return True
        except (ClientError, BotoCoreError):
            return False

    def ensure_buckets(self, *, attempts: int = 10, delay_seconds: float = 2.0) -> None:
        """Create the buckets and keep versioning enabled.

        The object store may still be starting when the API process boots (the
        compose stack and Kubernetes both start containers concurrently), so the
        bootstrap is retried with a short backoff instead of giving up on the
        first connection error.
        """
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                existing = {b["Name"] for b in self._client.list_buckets().get("Buckets", [])}
                for bucket in self.buckets.values():
                    if bucket not in existing:
                        self._client.create_bucket(Bucket=bucket)
                        log.info("storage.bucket_created", bucket=bucket)
                    # Idempotent: re-asserting versioning also repairs a bucket
                    # that was created out-of-band without it.
                    self._client.put_bucket_versioning(
                        Bucket=bucket, VersioningConfiguration={"Status": "Enabled"}
                    )
                return
            except (ClientError, BotoCoreError) as exc:
                last_error = exc
                if attempt == attempts:
                    break
                log.warning("storage.bucket_bootstrap_retry", attempt=attempt, error=str(exc))
                time.sleep(delay_seconds)
        log.error("storage.bucket_bootstrap_failed", error=str(last_error))

    # ------------------------------------------------------------------ objects
    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        bucket: str | None = None,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> StoredObject:
        target = bucket or self.buckets["backups"]
        checksum = hashlib.sha256(data).hexdigest()
        extra: dict[str, Any] = {
            "ContentType": content_type,
            "Metadata": {**(metadata or {}), "sha256": checksum},
        }
        if settings.S3_SERVER_SIDE_ENCRYPTION:
            extra["ServerSideEncryption"] = settings.S3_SERVER_SIDE_ENCRYPTION
            if settings.S3_SERVER_SIDE_ENCRYPTION == "aws:kms" and settings.S3_KMS_KEY_ID:
                extra["SSEKMSKeyId"] = settings.S3_KMS_KEY_ID
        try:
            response = self._client.put_object(Bucket=target, Key=key, Body=data, **extra)
        except (ClientError, BotoCoreError) as exc:
            raise UpstreamError(f"Object storage write failed: {exc}") from exc
        return StoredObject(
            key=key,
            bucket=target,
            size=len(data),
            checksum_sha256=checksum,
            etag=response.get("ETag", "").strip('"') or None,
        )

    def put_stream(self, key: str, stream: BinaryIO, *, bucket: str | None = None) -> StoredObject:
        return self.put_bytes(key, stream.read(), bucket=bucket)

    def get_bytes(self, key: str, *, bucket: str | None = None) -> bytes:
        target = bucket or self.buckets["backups"]
        try:
            response = self._client.get_object(Bucket=target, Key=key)
            return response["Body"].read()
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
                raise UpstreamError(f"Object {key} not found in {target}") from exc
            raise UpstreamError(f"Object storage read failed: {exc}") from exc

    def presign(self, key: str, *, bucket: str | None = None, expires_seconds: int = 900) -> str:
        target = bucket or self.buckets["backups"]
        try:
            return self._client.generate_presigned_url(
                "get_object", Params={"Bucket": target, "Key": key}, ExpiresIn=expires_seconds
            )
        except (ClientError, BotoCoreError) as exc:
            raise UpstreamError(f"Unable to presign object: {exc}") from exc

    def delete(self, key: str, *, bucket: str | None = None) -> None:
        target = bucket or self.buckets["backups"]
        try:
            self._client.delete_object(Bucket=target, Key=key)
        except (ClientError, BotoCoreError) as exc:
            raise UpstreamError(f"Object storage delete failed: {exc}") from exc

    def exists(self, key: str, *, bucket: str | None = None) -> bool:
        target = bucket or self.buckets["backups"]
        try:
            self._client.head_object(Bucket=target, Key=key)
            return True
        except ClientError:
            return False

    def list_keys(self, prefix: str, *, bucket: str | None = None, limit: int = 1000) -> list[str]:
        target = bucket or self.buckets["backups"]
        response = self._client.list_objects_v2(Bucket=target, Prefix=prefix, MaxKeys=limit)
        return [item["Key"] for item in response.get("Contents", [])]

    async def aput_bytes(self, key: str, data: bytes, **kwargs: Any) -> StoredObject:
        return await asyncio.to_thread(self.put_bytes, key, data, **kwargs)

    async def aget_bytes(self, key: str, **kwargs: Any) -> bytes:
        return await asyncio.to_thread(self.get_bytes, key, **kwargs)

    async def apresign(self, key: str, **kwargs: Any) -> str:
        return await asyncio.to_thread(self.presign, key, **kwargs)


@lru_cache(maxsize=1)
def get_storage() -> ObjectStorage:
    return ObjectStorage()
