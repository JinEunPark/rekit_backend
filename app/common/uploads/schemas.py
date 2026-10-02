from typing import Literal

from pydantic import BaseModel, Field

ImageContentType = Literal["image/jpeg", "image/png", "image/webp"]
UploadPurpose = Literal["product_image", "category_image"]


class PresignRequest(BaseModel):
    """presign 은 래스터 이미지 전용.

    SVG 는 본문에 스크립트를 품을 수 있어 저장 전 검사가 필요한데, presign 방식은
    클라이언트가 스토리지로 직접 PUT 하므로 서버가 본문을 가로챌 지점이 없다
    (confirm 을 호출하지 않으면 검사가 아예 실행되지 않은 채 공개된다).
    그래서 SVG 는 서버 경유 업로드인 POST /uploads/svg 로만 받는다.
    """

    content_type: ImageContentType
    purpose: UploadPurpose = "product_image"


class PresignResponse(BaseModel):
    upload_url: str
    method: Literal["PUT"] = "PUT"
    key: str
    public_url: str
    expires_in: int
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="PUT 업로드 시 반드시 포함해야 하는 헤더 (Content-Type 등)",
    )


class ConfirmRequest(BaseModel):
    key: str = Field(min_length=1, max_length=500)


class ConfirmResponse(BaseModel):
    key: str
    public_url: str
    size: int
    content_type: str
