"""address 라우터 통합 테스트 — 서비스/인증 fake로 교체.

DB를 직접 호출하지 않는다. AddressService 와 get_active_user 를 dependency_overrides
로 교체해 라우터 레이어(경로, 상태 코드, 에러 포맷, 입력 검증)만 검증한다.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.address.address_schemas import AddressCreate, AddressUpdate
from app.address.models import Address
from app.core.deps import get_active_user, get_address_service
from app.core.exceptions import AddressLimitExceeded, AddressNotFound
from app.main import app
from tests.conftest import make_user

# ── fake 구현체 ────────────────────────────────────────


def _make_addr(address_id: int = 1, *, is_default: bool = False) -> Address:
    addr = Address(
        user_id=1,
        recipient="홍길동",
        phone="01012345678",
        zipcode="12345",
        address1="서울시 강남구",
        is_default=is_default,
    )
    addr.id = address_id
    return addr


class _FakeService:
    def __init__(self, addresses: list[Address] | None = None) -> None:
        self._addresses = list(addresses or [])

    async def list_addresses(self, user_id: int) -> list[Address]:
        return self._addresses

    async def create_address(self, user_id: int, data: AddressCreate) -> Address:
        if len(self._addresses) >= 10:
            raise AddressLimitExceeded()
        addr = _make_addr(len(self._addresses) + 1, is_default=data.is_default)
        self._addresses.append(addr)
        return addr

    async def update_address(self, user_id: int, address_id: int, data: AddressUpdate) -> Address:
        for addr in self._addresses:
            if addr.id == address_id:
                return addr
        raise AddressNotFound()

    async def delete_address(self, user_id: int, address_id: int) -> None:
        for addr in self._addresses:
            if addr.id == address_id:
                self._addresses.remove(addr)
                return
        raise AddressNotFound()


_FAKE_USER = make_user()
_VALID_BODY = {
    "recipient": "홍길동",
    "phone": "01012345678",
    "zipcode": "12345",
    "address1": "서울시 강남구 테헤란로 1",
}


@pytest.fixture
def client() -> Iterator[TestClient]:
    """기본 빈 서비스 + fake user 로 교체된 TestClient.

    lifespan(storage ensure_bucket)은 테스트 불필요 — 컨텍스트 매니저 없이 사용.
    """
    app.dependency_overrides[get_active_user] = lambda: _FAKE_USER
    app.dependency_overrides[get_address_service] = lambda: _FakeService()
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client_with_one_address() -> Iterator[TestClient]:
    app.dependency_overrides[get_active_user] = lambda: _FAKE_USER
    app.dependency_overrides[get_address_service] = lambda: _FakeService(
        [_make_addr(1, is_default=True)]
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client_at_limit() -> Iterator[TestClient]:
    app.dependency_overrides[get_active_user] = lambda: _FAKE_USER
    app.dependency_overrides[get_address_service] = lambda: _FakeService(
        [_make_addr(i) for i in range(1, 11)]
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


# ── GET /addresses ─────────────────────────────────────


class TestGetAddresses:
    def test_empty_list_returns_200_with_empty_array(self, client: TestClient) -> None:
        res = client.get("/api/v1/addresses")
        assert res.status_code == 200
        assert res.json() == []

    def test_list_returns_addresses_with_is_default_alias(
        self, client_with_one_address: TestClient
    ) -> None:
        res = client_with_one_address.get("/api/v1/addresses")
        assert res.status_code == 200
        body = res.json()
        assert len(body) == 1
        assert "isDefault" in body[0]

    def test_unauthenticated_returns_4xx(self) -> None:
        """dependency_overrides 없는 상태에서 호출 → 토큰 없어 401/403."""
        res = TestClient(app).get("/api/v1/addresses")
        assert res.status_code in (401, 403)


# ── POST /addresses ─────────────────────────────────────


class TestPostAddresses:
    def test_valid_body_returns_201(self, client: TestClient) -> None:
        res = client.post("/api/v1/addresses", json=_VALID_BODY)
        assert res.status_code == 201
        assert res.json()["recipient"] == "홍길동"

    def test_invalid_phone_returns_422_validation_error(self, client: TestClient) -> None:
        res = client.post("/api/v1/addresses", json={**_VALID_BODY, "phone": "02-bad"})
        assert res.status_code == 422
        assert res.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_invalid_zipcode_returns_422(self, client: TestClient) -> None:
        res = client.post("/api/v1/addresses", json={**_VALID_BODY, "zipcode": "9999"})
        assert res.status_code == 422

    def test_missing_required_field_returns_422(self, client: TestClient) -> None:
        res = client.post("/api/v1/addresses", json={"recipient": "홍길동"})
        assert res.status_code == 422

    def test_over_limit_returns_422_address_limit_exceeded(
        self, client_at_limit: TestClient
    ) -> None:
        res = client_at_limit.post("/api/v1/addresses", json=_VALID_BODY)
        assert res.status_code == 422
        assert res.json()["error"]["code"] == "ADDRESS_LIMIT_EXCEEDED"


# ── PATCH /addresses/{id} ──────────────────────────────


class TestPatchAddress:
    def test_update_existing_returns_200(self, client_with_one_address: TestClient) -> None:
        res = client_with_one_address.patch(
            "/api/v1/addresses/1", json={"recipient": "김철수"}
        )
        assert res.status_code == 200

    def test_update_not_found_returns_404(self, client: TestClient) -> None:
        res = client.patch("/api/v1/addresses/999", json={"recipient": "김철수"})
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "ADDRESS_NOT_FOUND"

    def test_invalid_phone_in_patch_returns_422(self, client_with_one_address: TestClient) -> None:
        res = client_with_one_address.patch(
            "/api/v1/addresses/1", json={"phone": "02-invalid"}
        )
        assert res.status_code == 422
        assert res.json()["error"]["code"] == "VALIDATION_ERROR"


# ── DELETE /addresses/{id} ─────────────────────────────


class TestDeleteAddress:
    def test_delete_existing_returns_204(self, client_with_one_address: TestClient) -> None:
        res = client_with_one_address.delete("/api/v1/addresses/1")
        assert res.status_code == 204

    def test_delete_not_found_returns_404(self, client: TestClient) -> None:
        res = client.delete("/api/v1/addresses/999")
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "ADDRESS_NOT_FOUND"
