from contextlib import asynccontextmanager
from typing import AsyncIterator
from uuid import uuid4

import aioboto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import Settings
from app.core.config import settings as default_settings

ALLOWED_IMAGE_TYPES: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


class ObjectMeta:
    __slots__ = ("size", "content_type", "etag")

    def __init__(self, size: int, content_type: str, etag: str) -> None:
        self.size = size
        self.content_type = content_type
        self.etag = etag


class StorageService:
    """SeaweedFS / S3 호환 스토리지 어댑터.

    presigned PUT URL 발급 + head/delete만 담당. 실제 파일 본문은
    프런트엔드가 SeaweedFS로 직접 업로드 → /uploads/confirm 으로 검증.
    """

    def __init__(self, settings: Settings = default_settings) -> None:
        self.settings = settings
        self._session = aioboto3.Session()

    @asynccontextmanager
    async def _client(self) -> AsyncIterator:
        async with self._session.client(
            "s3",
            endpoint_url=self.settings.s3_endpoint_url,
            region_name=self.settings.s3_region,
            aws_access_key_id=self.settings.s3_access_key,
            aws_secret_access_key=self.settings.s3_secret_key,
            config=Config(
                signature_version="s3v4",
                s3={
                    "addressing_style": "path"
                    if self.settings.s3_force_path_style
                    else "auto"
                },
            ),
        ) as client:
            yield client

    @staticmethod
    def generate_product_image_key(content_type: str) -> str:
        ext = ALLOWED_IMAGE_TYPES[content_type]
        return f"products/{uuid4()}.{ext}"

    async def presigned_put_url(self, key: str, content_type: str) -> str:
        async with self._client() as s3:
            return await s3.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self.settings.s3_bucket,
                    "Key": key,
                    "ContentType": content_type,
                },
                ExpiresIn=self.settings.s3_presign_expire_seconds,
            )

    async def head(self, key: str) -> ObjectMeta | None:
        async with self._client() as s3:
            try:
                response = await s3.head_object(
                    Bucket=self.settings.s3_bucket, Key=key
                )
            except ClientError as exc:
                if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                    return None
                raise
            return ObjectMeta(
                size=int(response["ContentLength"]),
                content_type=response.get("ContentType", "application/octet-stream"),
                etag=response["ETag"].strip('"'),
            )

    async def delete(self, key: str) -> None:
        async with self._client() as s3:
            await s3.delete_object(Bucket=self.settings.s3_bucket, Key=key)

    async def ensure_bucket(self) -> None:
        """앱 부팅 시 1회 호출 — SeaweedFS는 버킷이 없으면 PUT이 실패."""
        async with self._client() as s3:
            try:
                await s3.head_bucket(Bucket=self.settings.s3_bucket)
            except ClientError as exc:
                code = exc.response["Error"]["Code"]
                if code in ("404", "NoSuchBucket", "NotFound"):
                    await s3.create_bucket(Bucket=self.settings.s3_bucket)
                else:
                    raise

    def public_url(self, key: str) -> str:
        return f"{self.settings.s3_public_url_base.rstrip('/')}/{key}"


storage_service = StorageService()
