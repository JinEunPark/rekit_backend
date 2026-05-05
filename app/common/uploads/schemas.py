from typing import Literal

from pydantic import BaseModel, Field

ImageContentType = Literal["image/jpeg", "image/png", "image/webp"]


class PresignRequest(BaseModel):
    content_type: ImageContentType
    purpose: Literal["product_image"] = "product_image"


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
