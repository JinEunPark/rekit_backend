"""오브젝트 스토리지 port.

상품 이미지·환불 첨부 등 바이너리 자산은 service 가 이 Protocol 에만 의존한다.
구현체는 `s3_adapter.py` (SeaweedFS / S3 / R2 등) 에 둔다.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ObjectMeta:
    size: int
    content_type: str
    etag: str


class ObjectStorage(Protocol):
    """presigned PUT 발급 + head/delete 만 노출. 실제 본문은 클라이언트 ↔ 스토리지 직접."""

    @staticmethod
    def generate_product_image_key(content_type: str) -> str: ...

    async def presigned_put_url(self, key: str, content_type: str) -> str: ...

    async def head(self, key: str) -> ObjectMeta | None: ...

    async def delete(self, key: str) -> None: ...

    async def ensure_bucket(self) -> None: ...

    def public_url(self, key: str) -> str: ...
