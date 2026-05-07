"""get_email_sender DI 단위 테스트.

settings.email_provider 값에 따라 적절한 어댑터 인스턴스를 반환하는지 검증.
실제 SMTP 호출은 하지 않음 — 인스턴스 타입만 확인.
"""

from __future__ import annotations

from app.common.email import ConsoleEmailSender, GmailSmtpEmailSender
from app.core.config import Settings
from app.core.deps import build_email_sender


def test_build_email_sender_returns_console_for_console_provider() -> None:
    # Arrange
    settings = Settings.model_construct(email_provider="console")

    # Act
    sender = build_email_sender(settings)

    # Assert
    assert isinstance(sender, ConsoleEmailSender)


def test_build_email_sender_returns_gmail_for_gmail_provider() -> None:
    # Arrange — App Password 가짜값
    settings = Settings.model_construct(
        email_provider="gmail",
        gmail_user="dev@gmail.com",
        gmail_app_password="abcd efgh ijkl mnop",
        email_from="Rekit <noreply@rekit.kr>",
    )

    # Act
    sender = build_email_sender(settings)

    # Assert
    assert isinstance(sender, GmailSmtpEmailSender)
    assert sender.user == "dev@gmail.com"
    assert sender.from_addr == "Rekit <noreply@rekit.kr>"


def test_build_email_sender_raises_when_gmail_credentials_missing() -> None:
    """provider=gmail 인데 GMAIL_USER 없으면 명시적으로 실패."""
    # Arrange
    settings = Settings.model_construct(email_provider="gmail", gmail_user=None)

    # Act / Assert
    import pytest

    with pytest.raises(RuntimeError, match="Gmail"):
        build_email_sender(settings)
