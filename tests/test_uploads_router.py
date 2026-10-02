"""uploads 라우터 단위 테스트.

실제 S3 PUT/HEAD/GET 호출 없이 storage_service 를 monkeypatch 로 치환한다.

- presign: purpose 별 키 생성 분기, SVG 는 presign 자체가 불가(서버 경유 전용)
- /uploads/svg: 검사를 통과한 본문만 스토리지에 도달
- confirm: 크기 초과 거부
- 세 엔드포인트 모두 관리자 가드 필요
"""

from __future__ import annotations

import importlib
from io import BytesIO

import pytest
from fastapi import UploadFile
from pydantic import ValidationError

from app.common.storage.ports import ObjectMeta
from app.common.uploads.schemas import ConfirmRequest, PresignRequest

# app.common.uploads.__init__ 가 `router` 이름으로 APIRouter 인스턴스를 재노출하므로
# `from app.common.uploads import router`는 모듈이 아닌 그 인스턴스를 가져온다.
# storage_service 를 monkeypatch 하려면 서브모듈 자체를 import 해야 한다.
uploads_router = importlib.import_module("app.common.uploads.router")


class _FakeStorage:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.deleted: list[str] = []
        self.objects: dict[str, tuple[bytes, str]] = {}

    def generate_product_image_key(self, content_type: str) -> str:
        self.calls.append("product")
        return "products/fake.jpg"

    def generate_category_image_key(self, content_type: str) -> str:
        self.calls.append("category")
        return "categories/fake.svg" if content_type == "image/svg+xml" else "categories/fake.jpg"

    async def presigned_put_url(self, key: str, content_type: str) -> str:
        return f"https://upload.example.com/{key}"

    def public_url(self, key: str) -> str:
        return f"https://cdn.example.com/{key}"

    async def head(self, key: str) -> ObjectMeta | None:
        if key not in self.objects:
            return None
        body, content_type = self.objects[key]
        return ObjectMeta(size=len(body), content_type=content_type, etag="fake-etag")

    async def get_object(self, key: str) -> bytes:
        return self.objects[key][0]

    async def put_object(self, key: str, body: bytes, content_type: str) -> None:
        self.objects[key] = (body, content_type)

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.objects.pop(key, None)


@pytest.fixture
def fake_storage(monkeypatch: pytest.MonkeyPatch) -> _FakeStorage:
    fake = _FakeStorage()
    monkeypatch.setattr(uploads_router, "storage_service", fake)
    return fake


# ── presign ──────────────────────────────────────────────────


async def test_presign_defaults_to_product_image_key(fake_storage: _FakeStorage) -> None:
    result = await uploads_router.presign_upload(
        PresignRequest(content_type="image/jpeg")
    )

    assert fake_storage.calls == ["product"]
    assert result.key == "products/fake.jpg"


async def test_presign_category_image_uses_category_key(fake_storage: _FakeStorage) -> None:
    result = await uploads_router.presign_upload(
        PresignRequest(content_type="image/png", purpose="category_image")
    )

    assert fake_storage.calls == ["category"]
    assert result.key == "categories/fake.jpg"


@pytest.mark.parametrize("purpose", ["product_image", "category_image"])
def test_presign_rejects_svg_for_every_purpose(purpose: str) -> None:
    """SVG 는 presign 으로 올릴 수 없다 — purpose 와 무관하게 요청 단계에서 거부.

    presign 은 클라이언트가 스토리지로 직접 PUT 하는 방식이라 서버가 본문을 검사할
    지점이 없다. confirm 을 호출하지 않으면 검사가 아예 실행되지 않은 채 파일이
    공개되므로, SVG 는 서버 경유(POST /uploads/svg)로만 받는다.
    """
    with pytest.raises(ValidationError):
        PresignRequest(content_type="image/svg+xml", purpose=purpose)  # type: ignore[arg-type]


# ── /uploads/svg (서버 경유) ─────────────────────────────────


def _svg_upload(body: bytes) -> UploadFile:
    return UploadFile(file=BytesIO(body), filename="icon.svg")


async def test_upload_svg_stores_safe_file(fake_storage: _FakeStorage) -> None:
    body = b'<svg xmlns="http://www.w3.org/2000/svg"><circle r="4" /></svg>'

    result = await uploads_router.upload_svg(file=_svg_upload(body))

    assert result.key == "categories/fake.svg"
    assert result.content_type == "image/svg+xml"
    assert result.size == len(body)
    assert fake_storage.objects[result.key] == (body, "image/svg+xml")


async def test_upload_svg_rejects_script_without_storing(
    fake_storage: _FakeStorage,
) -> None:
    """핵심 — 안전하지 않은 SVG 는 스토리지에 도달조차 하지 않는다."""
    body = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'

    with pytest.raises(Exception) as exc_info:
        await uploads_router.upload_svg(file=_svg_upload(body))

    assert getattr(exc_info.value, "status_code", None) == 422
    assert fake_storage.objects == {}


async def test_upload_svg_rejects_oversized_file(
    fake_storage: _FakeStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(uploads_router.settings, "s3_max_upload_size", 10)

    with pytest.raises(Exception) as exc_info:
        await uploads_router.upload_svg(file=_svg_upload(b"<svg" + b"x" * 50))

    assert getattr(exc_info.value, "status_code", None) == 413
    assert fake_storage.objects == {}


# ── 관리자 가드 ──────────────────────────────────────────────


def test_every_upload_route_requires_admin() -> None:
    """업로드 3종은 전부 관리자 전용 — 무인증 업로드 경로가 다시 생기지 않도록 고정."""
    from app.core.deps import get_admin_user

    paths = {
        route.path: [dep.call for dep in route.dependant.dependencies]
        for route in uploads_router.router.routes
    }

    assert paths, "uploads 라우터에 등록된 경로가 없다"
    for path, deps in paths.items():
        assert get_admin_user in deps, f"{path} 에 관리자 가드가 없다"


# ── confirm ──────────────────────────────────────────────────


async def test_confirm_safe_svg_succeeds(fake_storage: _FakeStorage) -> None:
    key = "categories/safe.svg"
    fake_storage.objects[key] = (
        b'<svg xmlns="http://www.w3.org/2000/svg"><circle r="4" /></svg>',
        "image/svg+xml",
    )

    result = await uploads_router.confirm_upload(ConfirmRequest(key=key))

    assert result.key == key
    assert key not in fake_storage.deleted


async def test_confirm_svg_with_script_is_rejected_and_deleted(
    fake_storage: _FakeStorage,
) -> None:
    key = "categories/evil.svg"
    fake_storage.objects[key] = (
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        "image/svg+xml",
    )

    with pytest.raises(Exception) as exc_info:
        await uploads_router.confirm_upload(ConfirmRequest(key=key))

    assert getattr(exc_info.value, "status_code", None) == 422
    assert key in fake_storage.deleted


async def test_confirm_non_svg_skips_svg_check(fake_storage: _FakeStorage) -> None:
    key = "products/fake.jpg"
    fake_storage.objects[key] = (b"\xff\xd8\xff", "image/jpeg")

    result = await uploads_router.confirm_upload(ConfirmRequest(key=key))

    assert result.key == key
    assert key not in fake_storage.deleted
