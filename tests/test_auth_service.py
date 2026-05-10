"""AuthService 단위 테스트 (sign_in / sign_up / refresh_token / is_login_id_available).

DB 없이 fake repository 로 도메인 로직만 검증.
실제 DB 연동 검증(통합 테스트) 은 별도 사이클(tests/integration/) 에서 한다.

원칙 (CLAUDE.md TDD §5):
- fake 는 Protocol 상속 안 해도 OK — service 가 호출하는 메서드만 갖추면 됨 (duck typing).
- 실패 케이스 → 성공 케이스 → 부수 동작 순.
- AAA 패턴: Arrange (준비) / Act (실행) / Assert (검증) 구분.
"""

from datetime import timedelta

import pytest
from fastapi import BackgroundTasks

from app.auth.auth_service import (
    AuthService,
    _bg_apply_temp_password,
    _bg_send_login_id_email,
)
from app.common.email import ConsoleEmailSender
from app.core.exceptions import (
    EmailTaken,
    InvalidCredentials,
    TokenExpired,
    UsernameTaken,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.user.models import User
from tests.conftest import make_user

# ── 테스트 헬퍼 ────────────────────────────────────────


class _FakeAuthRepo:
    """AuthRepository 의 fake. service 가 호출하는 모든 메서드 구현."""

    def __init__(self, user: User | None = None) -> None:
        self._user = user
        self.added: list[User] = []  # add() 호출 검증용

    async def get_by_login_id(self, login_id: str) -> User | None:
        if self._user is None:
            return None
        return self._user if self._user.login_id == login_id else None

    async def get_by_id(self, user_id: int) -> User | None:
        if self._user is None:
            return None
        return self._user if self._user.id == user_id else None

    async def exists_by_login_id(self, login_id: str) -> bool:
        return self._user is not None and self._user.login_id == login_id

    async def exists_by_email(self, email: str) -> bool:
        return self._user is not None and self._user.email == email

    async def get_by_email(self, email: str) -> User | None:
        if self._user is None:
            return None
        return self._user if self._user.email == email else None

    async def get_by_login_id_and_email(
        self, login_id: str, email: str
    ) -> User | None:
        if self._user is None:
            return None
        match = self._user.login_id == login_id and self._user.email == email
        return self._user if match else None

    async def add(self, user: User) -> User:
        # 메모리 fake: PK 만 채워주고 보관
        user.id = (self._user.id + 1) if self._user else 1
        self.added.append(user)
        return user


def _make_user(*, password: str = "correct-pw", **kwargs: object) -> User:
    """auth_service 테스트 전용 어댑터 — conftest.make_user 의 password 키워드 alias.

    `_make_user(password="X", ...)` 호출 패턴을 유지하면서 실제 객체 생성은
    conftest 헬퍼에 위임. login_id/email 등 kwargs 는 그대로 전달.
    """
    return make_user(plain_password=password, **kwargs)  # type: ignore[arg-type]


def _make_service(repo: object) -> AuthService:
    """AuthService 인스턴스화 헬퍼. 시그니처가 바뀌어도 한 곳만 고치면 됨.

    EmailSender 는 ConsoleEmailSender (sent 리스트 보관) 를 기본 주입 — find-id /
    find-password 등 메일 발송 검증이 필요한 테스트는 이 인스턴스를 직접 넘겨 받는다.
    """
    return AuthService(repo, email_sender=ConsoleEmailSender())  # type: ignore[arg-type]


# ── sign_in: 실패 케이스 ──────────────────────────────


async def test_sign_in_with_unknown_login_id_raises_invalid_credentials() -> None:
    """존재하지 않는 아이디 → InvalidCredentials."""
    service = _make_service(_FakeAuthRepo())
    with pytest.raises(InvalidCredentials):
        await service.sign_in(login_id="nobody", password="any")


async def test_sign_in_with_wrong_password_raises_invalid_credentials() -> None:
    """비밀번호 불일치 → InvalidCredentials (아이디 존재 여부 노출 X)."""
    user = _make_user(password="correct-pw")
    service = _make_service(_FakeAuthRepo(user=user))
    with pytest.raises(InvalidCredentials):
        await service.sign_in(login_id=user.login_id, password="wrong-pw")


async def test_sign_in_with_inactive_user_raises_invalid_credentials() -> None:
    user = _make_user(is_active=False)
    service = _make_service(_FakeAuthRepo(user=user))
    with pytest.raises(InvalidCredentials):
        await service.sign_in(login_id=user.login_id, password="correct-pw")


# ── sign_in: 정상 ────────────────────────────────────


async def test_sign_in_returns_access_and_refresh_tokens_on_success() -> None:
    user = _make_user(password="correct-pw")
    service = _make_service(_FakeAuthRepo(user=user))

    access, refresh, must_change = await service.sign_in(
        login_id=user.login_id, password="correct-pw"
    )

    access_payload = decode_token(access, expected_type="access")
    refresh_payload = decode_token(refresh, expected_type="refresh")
    assert access_payload["sub"] == "1"
    assert refresh_payload["sub"] == "1"
    assert access_payload["role"] == "USER"
    assert must_change is False  # 정상 사용자


async def test_sign_in_returns_must_change_password_true_for_temp_password_user() -> None:
    """임시 비번 발급 후 로그인 — must_change_password=True 가 반환된다."""
    # Arrange
    user = _make_user(password="temp-pw-1")
    user.must_change_password = True
    service = _make_service(_FakeAuthRepo(user=user))

    # Act
    _, _, must_change = await service.sign_in(
        login_id=user.login_id, password="temp-pw-1"
    )

    # Assert
    assert must_change is True


# ── sign_up ──────────────────────────────────────────


async def test_sign_up_creates_user_and_returns_it() -> None:
    """정상 가입 → repo.add 1회 + user 반환. 토큰은 별도 sign-in 으로 분리."""
    repo = _FakeAuthRepo()
    service = _make_service(repo)

    user = await service.sign_up(
        login_id="newuser",
        username="새사용자",
        password="abc12345",
        email="new@example.com",
        agreed_marketing=False,
    )

    assert len(repo.added) == 1
    assert user.login_id == "newuser"
    assert user.username == "새사용자"
    assert user.email == "new@example.com"
    assert user.agreed_terms_at is not None
    assert user.agreed_privacy_at is not None
    assert user.agreed_marketing_at is None  # 선택 미동의 → NULL


async def test_sign_up_with_marketing_consent_sets_timestamp() -> None:
    """marketing=True 면 agreed_marketing_at 도 채워진다."""
    repo = _FakeAuthRepo()
    service = _make_service(repo)

    user = await service.sign_up(
        login_id="newuser",
        username="새사용자",
        password="abc12345",
        email="new@example.com",
        agreed_marketing=True,
    )
    assert user.agreed_marketing_at is not None


async def test_sign_up_normalizes_email_to_lowercase() -> None:
    """대문자 이메일 입력해도 소문자로 저장."""
    repo = _FakeAuthRepo()
    service = _make_service(repo)

    user = await service.sign_up(
        login_id="newuser",
        username="새사용자",
        password="abc12345",
        email="NEW@Example.COM",
        agreed_marketing=False,
    )
    assert user.email == "new@example.com"


async def test_sign_up_rejects_duplicate_login_id() -> None:
    existing = _make_user(login_id="taken")
    service = _make_service(_FakeAuthRepo(user=existing))

    with pytest.raises(UsernameTaken):
        await service.sign_up(
            login_id="taken",
            username="아무개",
            password="abc12345",
            email="x@y.com",
            agreed_marketing=False,
        )


async def test_sign_up_rejects_duplicate_email() -> None:
    existing = _make_user(login_id="other", email="dup@example.com")
    service = _make_service(_FakeAuthRepo(user=existing))

    with pytest.raises(EmailTaken):
        await service.sign_up(
            login_id="newuser",
            username="아무개",
            password="abc12345",
            email="DUP@example.com",  # 정규화 후 비교되는지 검증
            agreed_marketing=False,
        )


# ── is_login_id_available ─────────────────────────────


async def test_is_login_id_available_returns_true_when_free() -> None:
    service = _make_service(_FakeAuthRepo())
    assert await service.is_login_id_available("anything") is True


async def test_is_login_id_available_returns_false_when_taken() -> None:
    user = _make_user(login_id="taken")
    service = _make_service(_FakeAuthRepo(user=user))
    assert await service.is_login_id_available("taken") is False


# ── refresh_token ────────────────────────────────────


async def test_refresh_token_with_expired_token_raises_token_expired() -> None:
    user = _make_user()
    service = _make_service(_FakeAuthRepo(user=user))
    expired = create_refresh_token(sub="1", expires_in=timedelta(seconds=-10))
    with pytest.raises(TokenExpired):
        await service.refresh_token(expired)


async def test_refresh_token_rejects_access_token() -> None:
    """access 토큰을 refresh 자리에 넣으면 거부 — type 가드."""
    user = _make_user()
    service = _make_service(_FakeAuthRepo(user=user))
    access = create_access_token(sub="1", claims={})
    with pytest.raises(TokenExpired):
        await service.refresh_token(access)


async def test_refresh_token_with_unknown_user_raises_invalid_credentials() -> None:
    service = _make_service(_FakeAuthRepo())
    valid = create_refresh_token(sub="999")
    with pytest.raises(InvalidCredentials):
        await service.refresh_token(valid)


async def test_refresh_token_with_inactive_user_raises_invalid_credentials() -> None:
    user = _make_user(is_active=False)
    service = _make_service(_FakeAuthRepo(user=user))
    valid = create_refresh_token(sub="1")
    with pytest.raises(InvalidCredentials):
        await service.refresh_token(valid)


async def test_refresh_token_returns_new_access_and_refresh_pair() -> None:
    user = _make_user()
    service = _make_service(_FakeAuthRepo(user=user))
    old_refresh = create_refresh_token(sub="1")

    new_access, new_refresh, must_change = await service.refresh_token(old_refresh)

    access_payload = decode_token(new_access, expected_type="access")
    refresh_payload = decode_token(new_refresh, expected_type="refresh")
    assert access_payload["sub"] == "1"
    assert refresh_payload["sub"] == "1"
    assert access_payload["role"] == "USER"
    assert must_change is False


async def test_refresh_token_carries_must_change_password_for_temp_user() -> None:
    """임시 비번 사용자는 refresh 사이클에도 must_change_password=True 가 유지된다."""
    user = _make_user()
    user.must_change_password = True
    service = _make_service(_FakeAuthRepo(user=user))
    old_refresh = create_refresh_token(sub="1")

    _, _, must_change = await service.refresh_token(old_refresh)

    assert must_change is True


# ── find_login_id_by_email ──────────────────────────────
# 실제 메일 발송은 BG task 가 응답 후 처리. service 는 큐잉만 검증.


async def test_find_login_id_queues_bg_task_when_user_exists() -> None:
    """가입 사용자 — BG task 가 큐잉되며 즉시 발송은 안 함."""
    # Arrange
    user = _make_user(login_id="abc123", email="user@example.com")
    repo = _FakeAuthRepo(user=user)
    sender = ConsoleEmailSender()
    service = AuthService(repo, email_sender=sender)  # type: ignore[arg-type]
    bg = BackgroundTasks()

    # Act
    await service.find_login_id_by_email("user@example.com", bg)

    # Assert — service 가 즉시 send 하지 않음
    assert sender.sent == []
    # BG task 1개 큐잉됨 (login_id / email 이 kwargs 에 들어감)
    assert len(bg.tasks) == 1
    task = bg.tasks[0]
    assert task.kwargs["to"] == "user@example.com"
    assert task.kwargs["login_id"] == "abc123"


async def test_find_login_id_does_not_queue_when_user_not_found() -> None:
    """미가입 이메일 — BG task 큐잉도 안 함 (enumeration 방어 + 비용 절감)."""
    repo = _FakeAuthRepo()
    sender = ConsoleEmailSender()
    service = AuthService(repo, email_sender=sender)  # type: ignore[arg-type]
    bg = BackgroundTasks()

    await service.find_login_id_by_email("nobody@example.com", bg)

    assert bg.tasks == []
    assert sender.sent == []


async def test_find_login_id_normalizes_email_to_lowercase() -> None:
    """대소문자 섞인 이메일 입력해도 소문자로 매칭."""
    user = _make_user(email="user@example.com")
    repo = _FakeAuthRepo(user=user)
    sender = ConsoleEmailSender()
    service = AuthService(repo, email_sender=sender)  # type: ignore[arg-type]
    bg = BackgroundTasks()

    await service.find_login_id_by_email("USER@Example.COM", bg)

    assert len(bg.tasks) == 1


# ── BG task 본체 (find-id) ─────────────────────────────


async def test_bg_send_login_id_email_dispatches_to_email_sender() -> None:
    """_bg_send_login_id_email 직접 호출 — sender.sent 에 메시지 누적."""
    sender = ConsoleEmailSender()

    await _bg_send_login_id_email(
        to="user@example.com",
        username="홍길동",
        login_id="abc123",
        email_sender=sender,
    )

    assert len(sender.sent) == 1
    msg = sender.sent[0]
    assert msg.to == "user@example.com"
    assert "abc123" in msg.body
    assert "홍길동" in msg.body


async def test_bg_send_login_id_email_swallows_email_failures() -> None:
    """이메일 발송 실패해도 raise 안 함 — BG task 는 응답 후 실행되니
    예외가 사용자 경험에 영향 X. 로그만 남김."""

    class _FailingSender:
        async def send(self, *, to: str, subject: str, body: str) -> None:
            raise RuntimeError("SMTP down")

    # Should not raise
    await _bg_send_login_id_email(
        to="x@y.com", username="u", login_id="lid", email_sender=_FailingSender()  # type: ignore[arg-type]
    )


# ── issue_temp_password (find-password) ─────────────────
# service 는 BG task 큐잉만. 임시 비번 생성 + DB UPDATE 는 BG task 가 응답 후 처리.


async def test_issue_temp_password_queues_bg_task_with_16char_password() -> None:
    """매칭 사용자 — BG task 큐잉 + kwargs 의 temp_password 가 16자 영문+숫자."""
    user = _make_user(login_id="abc123", email="user@example.com")
    repo = _FakeAuthRepo(user=user)
    sender = ConsoleEmailSender()
    service = AuthService(repo, email_sender=sender)  # type: ignore[arg-type]
    bg = BackgroundTasks()

    await service.issue_temp_password(
        login_id="abc123", email="user@example.com", background_tasks=bg
    )

    assert len(bg.tasks) == 1
    task = bg.tasks[0]
    pw: str = task.kwargs["temp_password"]
    assert len(pw) == 16
    assert any(c.isalpha() for c in pw)
    assert any(c.isdigit() for c in pw)
    # 즉시 DB 변경 X
    assert user.must_change_password is False


async def test_issue_temp_password_does_not_queue_on_login_id_mismatch() -> None:
    """이메일은 맞고 loginId 가 틀리면 큐잉도 안 함."""
    user = _make_user(login_id="abc123", email="user@example.com")
    repo = _FakeAuthRepo(user=user)
    service = AuthService(repo, email_sender=ConsoleEmailSender())  # type: ignore[arg-type]
    bg = BackgroundTasks()

    await service.issue_temp_password(
        login_id="wrong_id", email="user@example.com", background_tasks=bg
    )

    assert bg.tasks == []
    assert user.must_change_password is False


async def test_issue_temp_password_does_not_queue_on_email_mismatch() -> None:
    user = _make_user(login_id="abc123", email="user@example.com")
    repo = _FakeAuthRepo(user=user)
    service = AuthService(repo, email_sender=ConsoleEmailSender())  # type: ignore[arg-type]
    bg = BackgroundTasks()

    await service.issue_temp_password(
        login_id="abc123", email="other@example.com", background_tasks=bg
    )

    assert bg.tasks == []


async def test_issue_temp_password_normalizes_email_lowercase() -> None:
    user = _make_user(login_id="abc123", email="user@example.com")
    repo = _FakeAuthRepo(user=user)
    service = AuthService(repo, email_sender=ConsoleEmailSender())  # type: ignore[arg-type]
    bg = BackgroundTasks()

    await service.issue_temp_password(
        login_id="abc123", email="USER@Example.com", background_tasks=bg
    )

    assert len(bg.tasks) == 1


# ── BG task 본체 (find-password) ───────────────────────


async def test_bg_apply_temp_password_skips_db_when_email_fails() -> None:
    """이메일 발송 실패 시 DB 업데이트 안 함 — 사용자 비번 그대로 유지.

    DB 접근 자체를 안 해야 함 (요청 트랜잭션 끝난 뒤 BG task 가 자체 세션을
    여는데, 이메일이 raise 하면 그 코드까지 도달 안 함).
    """

    class _FailingSender:
        async def send(self, *, to: str, subject: str, body: str) -> None:
            raise RuntimeError("SMTP down")

    # Should not raise — user_id=99999 (없는 ID) 라도 DB 손대지 않으니 안전
    await _bg_apply_temp_password(
        user_id=99999,
        username="아무개",
        email="x@y.com",
        temp_password="ShouldNotBeApplied99",
        email_sender=_FailingSender(),  # type: ignore[arg-type]
    )
