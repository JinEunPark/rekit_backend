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
    """presigned PUT 발급 + head/delete 만 노출. 실제 본문은 클라이언트 ↔ 스토리지 직접.

    get_object 은 예외 — SVG 안전성 검사처럼 서버가 본문을 직접 들여다봐야 하는
    극히 제한된 용도로만 쓴다. 호출 전 head() 로 size 를 확인해 메모리에 통째로
    올려도 안전한 크기인지 먼저 검증할 것.
    """

    @staticmethod
    def generate_product_image_key(content_type: str) -> str: ...

    @staticmethod
    def generate_category_image_key(content_type: str) -> str: ...

    async def presigned_put_url(self, key: str, content_type: str) -> str: ...

    async def head(self, key: str) -> ObjectMeta | None: ...

    async def get_object(self, key: str) -> bytes: ...

    async def put_object(self, key: str, body: bytes, content_type: str) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def ensure_bucket(self) -> None: ...

    def public_url(self, key: str) -> str: ...
