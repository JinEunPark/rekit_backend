"""user 모듈 Service — 사용자 본인 정보 변경 도메인 로직.

JPA 비유: @Service. router(@RestController) 와 모델(@Entity) 사이의 비즈니스 규칙.

원칙:
- get_current_user 가 반환한 User 엔티티는 이미 세션에 attached. 속성 수정 시
  SQLAlchemy 가 dirty 추적 → router 의 db_session dependency 가 commit 시 UPDATE
  자동 발송. repository 에 별도 update 메서드 두지 않음 (단순 속성 수정 한정).
- 비즈니스 예외만 raise. router 는 try/except 하지 않음 — exception_handler 가
  표준 응답 포맷으로 변환.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.core.exceptions import InvalidCredentialsError, OtpInvalidError, OtpRateLimitedError
from app.core.security import hash_password, verify_password
from app.user.models import User, UserStatus
from app.user.user_repository import UserRepository
from app.user.user_schemas import UpdateProfileRequest

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from app.auth.adapters.ports import SmsSender

_PHONE_OTP_KEY = "sms:verify:{}"
_PHONE_OTP_RATE_KEY = "sms:verify:rate:{}"
_PHONE_OTP_TTL = 300  # 5분
_PHONE_OTP_RATE_TTL = 60  # 1분 (재발송 제한)


class UserService:
    def __init__(
        self,
        repo: UserRepository,
        *,
        sms_sender: SmsSender | None = None,
        redis: Redis | None = None,
    ) -> None:
        self.repo = repo
        self._sms_sender = sms_sender
        self._redis = redis

    def update_profile(self, *, user: User, data: UpdateProfileRequest) -> None:
        """username / phone 을 부분 업데이트한다. None 필드는 건드리지 않음."""
        if data.username is not None:
            user.username = data.username
        if data.phone is not None:
            user.phone = data.phone

    def _assert_password(self, raw: str, hashed: str) -> None:
        if not verify_password(raw, hashed):
            raise InvalidCredentialsError()

    async def withdraw(self, *, user: User, password: str) -> None:
        """비밀번호 확인 후 PII 전체 익명화 + 소셜 계정 삭제.

        - 재가입 가능하도록 email·login_id 를 unique 안전한 값으로 교체
        - 주문 데이터는 전자상거래법 5년 보존 의무로 유지 (orders 스냅샷은 별도 배치로 익명화)
        - 소셜 계정(email_at_link PII 포함)은 즉시 삭제
        """
        self._assert_password(password, user.password_hash)
        user.email = f"withdrawn_{user.id}@deleted"
        user.login_id = f"withdrawn_{user.id}"
        user.username = "(탈퇴한 사용자)"
        user.phone = None
        user.password_hash = ""
        user.birth_date = None
        user.gender = None
        user.ci = None
        user.di = None
        user.is_active = False
        user.status = UserStatus.WITHDRAWN
        user.withdrawn_at = datetime.now(UTC)
        await self.repo.delete_social_accounts(user.id)

    async def send_phone_verification(self, *, phone: str) -> None:
        """6자리 OTP 를 생성해 Redis 에 저장하고 SMS 발송. rate-limit: 60초.

        Raises:
            OtpRateLimitedError (429): 60초 이내 재요청.
        """
        assert self._redis is not None and self._sms_sender is not None

        locked = await self._redis.set(
            _PHONE_OTP_RATE_KEY.format(phone), "1", nx=True, ex=_PHONE_OTP_RATE_TTL
        )
        if locked is None:
            raise OtpRateLimitedError()

        code = "".join(secrets.choice("0123456789") for _ in range(6))
        await self._redis.set(_PHONE_OTP_KEY.format(phone), code, ex=_PHONE_OTP_TTL)
        await self._sms_sender.send(phone, f"[Rekle] 인증번호: {code}")

    async def verify_phone(self, *, user: User, phone: str, code: str) -> None:
        """OTP 검증 후 phone / phone_verified_at 업데이트.

        Raises:
            OtpInvalidError (422): 코드 불일치 또는 만료.
        """
        assert self._redis is not None

        stored = await self._redis.get(_PHONE_OTP_KEY.format(phone))
        if stored != code:
            raise OtpInvalidError()

        await self._redis.delete(_PHONE_OTP_KEY.format(phone))
        user.phone = phone
        user.phone_verified_at = datetime.now(UTC)

    def change_password(
        self,
        *,
        user: User,
        current_password: str,
        new_password: str,
    ) -> None:
        """현재 비번 검증 후 새 비번으로 갱신. 임시 비번 강제 변경도 이 메서드로.

        Raises:
            InvalidCredentialsError (401): 현재 비번이 일치하지 않을 때.

        Side effects:
            - user.password_hash 갱신 (bcrypt re-hash)
            - user.must_change_password = False (임시 비번 발급 상태였다면 해제)
        """
        self._assert_password(current_password, user.password_hash)

        user.password_hash = hash_password(new_password)
        # SQLAlchemy 가 dirty 추적을 attribute touch 기준으로 하므로 — 이미 False 면
        # 굳이 다시 쓰지 않아 일반 비번 변경 케이스에 불필요한 UPDATE column 을 만들지 않음.
        if user.must_change_password:
            user.must_change_password = False
