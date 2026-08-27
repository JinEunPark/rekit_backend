"""pytest 공용 부트스트랩 + 팩토리, 공용 테스트 더블.

여기서 app.db.registry 를 import 해서 모든 SQLAlchemy 모델을 메타데이터에
등록한다. User.relationship("Address", ...) 같은 string ref 는 mapper configure
시점(첫 인스턴스화/쿼리)에 resolve 되는데, 그 시점에 모든 모델 클래스가
메모리에 로드돼 있어야 한다 — 안 그러면 InvalidRequestError 가 난다.

이 파일은 pytest 가 테스트 수집 직전에 자동 import 하므로 (pytest 관례),
모든 테스트가 영향을 받는다 — 한 도메인만 테스트해도 전체 모델이 로드된다.
"""

from datetime import UTC, datetime

from app.core.security import hash_password
from app.db import registry  # noqa: F401
from app.user.models import User, UserRole


class FakeRedis:
    """인메모리 Redis 대역. TTL·NX 의미론 단순화 — 도메인 로직 단위 테스트 전용.

    NX: 키가 없을 때만 쓴다. 있으면 None 반환 (Redis SET NX 와 동일 의미론).
    TTL 은 저장하지 않는다 (단위 테스트에서 만료 시뮬레이션 필요 시 직접 delete 사용).
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool | None:
        del ex  # TTL 미구현 — 테스트에서 만료 시뮬레이션 필요 시 직접 delete 사용
        if nx and key in self._store:
            return None
        self._store[key] = value
        return True

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def exists(self, key: str) -> int:
        return 1 if key in self._store else 0


def make_user(
    *,
    user_id: int = 1,
    login_id: str = "testuser",
    username: str = "테스트",
    email: str = "user@example.com",
    plain_password: str | None = None,
    password_hash: str = "$2b$12$dummy",
    is_active: bool = True,
    must_change_password: bool = False,
    has_password: bool = True,
) -> User:
    """테스트용 User 인스턴스 팩토리. DB 저장 없이 메모리에서만 사용.

    `plain_password` 가 주어지면 bcrypt 해싱을 수행 (`verify_password` 검증이
    필요한 케이스). 아니면 더미 hash 그대로 — bcrypt 호출(~100ms) 비용 회피.
    """
    now = datetime.now(UTC)
    user = User(
        login_id=login_id,
        username=username,
        email=email,
        password_hash=hash_password(plain_password) if plain_password else password_hash,
        role=UserRole.USER,
        is_active=is_active,
        must_change_password=must_change_password,
        has_password=has_password,
        agreed_terms_at=now,
        agreed_privacy_at=now,
    )
    user.id = user_id
    return user
