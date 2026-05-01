from fastapi import APIRouter, HTTPException, status

from app.core.config import settings
from app.schemas.upload import (
    ConfirmRequest,
    ConfirmResponse,
    PresignRequest,
    PresignResponse,
)
from app.services.storage import storage_service

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("/presign", response_model=PresignResponse)
async def presign_upload(payload: PresignRequest) -> PresignResponse:
    # TODO: auth 복구 후 Depends(get_current_admin) 가드 추가
    key = storage_service.generate_product_image_key(payload.content_type)
    upload_url = await storage_service.presigned_put_url(key, payload.content_type)
    return PresignResponse(
        upload_url=upload_url,
        key=key,
        public_url=storage_service.public_url(key),
        expires_in=settings.s3_presign_expire_seconds,
        headers={"Content-Type": payload.content_type},
    )


@router.post("/confirm", response_model=ConfirmResponse)
async def confirm_upload(payload: ConfirmRequest) -> ConfirmResponse:
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
    return ConfirmResponse(
        key=payload.key,
        public_url=storage_service.public_url(payload.key),
        size=meta.size,
        content_type=meta.content_type,
    )
