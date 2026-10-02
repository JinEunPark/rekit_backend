from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.common.storage import storage_service
from app.common.uploads.schemas import (
    ConfirmRequest,
    ConfirmResponse,
    PresignRequest,
    PresignResponse,
)
from app.common.uploads.svg_sanitize import is_svg_safe
from app.core.config import settings
from app.core.deps import get_admin_user
from app.user.models import User

router = APIRouter(prefix="/uploads", tags=["uploads"])

SVG_CONTENT_TYPE = "image/svg+xml"


@router.post("/presign", response_model=PresignResponse)
async def presign_upload(
    payload: PresignRequest,
    _: User = Depends(get_admin_user),
) -> PresignResponse:
    key = (
        storage_service.generate_category_image_key(payload.content_type)
        if payload.purpose == "category_image"
        else storage_service.generate_product_image_key(payload.content_type)
    )
    upload_url = await storage_service.presigned_put_url(key, payload.content_type)
    return PresignResponse(
        upload_url=upload_url,
        key=key,
        public_url=storage_service.public_url(key),
        expires_in=settings.s3_presign_expire_seconds,
        headers={"Content-Type": payload.content_type},
    )


@router.post("/svg", response_model=ConfirmResponse)
async def upload_svg(
    file: UploadFile = File(...),
    _: User = Depends(get_admin_user),
) -> ConfirmResponse:
    """SVG 전용 서버 경유 업로드 — 검사를 통과한 본문만 스토리지에 올린다.

    presign 경로를 쓰지 않는 이유는 PresignRequest 독스트링 참고. 여기서는 바이트가
    서버를 거치므로, 안전하지 않은 SVG 는 스토리지에 아예 도달하지 못한다.
    """
    body = await file.read(settings.s3_max_upload_size + 1)
    if len(body) > settings.s3_max_upload_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "code": "FILE_TOO_LARGE",
                "message": f"최대 업로드 크기({settings.s3_max_upload_size} bytes)를 초과했습니다.",
            },
        )
    if not is_svg_safe(body):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "SVG_UNSAFE_CONTENT",
                "message": "스크립트나 이벤트 핸들러가 포함된 SVG는 업로드할 수 없습니다.",
            },
        )
    key = storage_service.generate_category_image_key(SVG_CONTENT_TYPE)
    await storage_service.put_object(key, body, SVG_CONTENT_TYPE)
    return ConfirmResponse(
        key=key,
        public_url=storage_service.public_url(key),
        size=len(body),
        content_type=SVG_CONTENT_TYPE,
    )


@router.post("/confirm", response_model=ConfirmResponse)
async def confirm_upload(
    payload: ConfirmRequest,
    _: User = Depends(get_admin_user),
) -> ConfirmResponse:
    meta = await storage_service.head(payload.key)
    if meta is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "OBJECT_NOT_FOUND",
                "message": "업로드된 파일을 찾을 수 없습니다.",
            },
        )
    if meta.size > settings.s3_max_upload_size:
        await storage_service.delete(payload.key)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "code": "FILE_TOO_LARGE",
                "message": f"최대 업로드 크기({settings.s3_max_upload_size} bytes)를 초과했습니다.",
            },
        )
    if meta.content_type == "image/svg+xml":
        body = await storage_service.get_object(payload.key)
        if not is_svg_safe(body):
            await storage_service.delete(payload.key)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": "SVG_UNSAFE_CONTENT",
                    "message": "스크립트나 이벤트 핸들러가 포함된 SVG는 업로드할 수 없습니다.",
                },
            )
    return ConfirmResponse(
        key=payload.key,
        public_url=storage_service.public_url(payload.key),
        size=meta.size,
        content_type=meta.content_type,
    )
