"""이메일 어댑터 단위 테스트.

Port `EmailSender` 의 두 구현체를 검증:
- ConsoleEmailSender: dev 용. stdout 출력 + 인스턴스 sentbox 에 누적
- GmailSmtpEmailSender: prod 용. 외부 SMTP 호출이라 단위 테스트는 안 함
  (라이브 검증으로 대체) — 본 파일에선 클래스가 EmailSender 시그니처를
  만족(Protocol structural typing) 하는지만 확인
"""

from __future__ import annotations

import pytest

from app.common.email import ConsoleEmailSender, EmailSender, GmailSmtpEmailSender


@pytest.mark.asyncio
async def test_console_email_sender_records_sent_messages() -> None:
    """ConsoleEmailSender 는 호출된 메시지를 sent 리스트에 기록한다 (테스트 검증용)."""
    # Arrange
    sender = ConsoleEmailSender()

    # Act
    await sender.send(
        to="user@example.com",
        subject="[Rekit] 임시 비밀번호",
        body="임시 비밀번호: x9k2Lm",
    )

    # Assert
    assert len(sender.sent) == 1
    msg = sender.sent[0]
    assert msg.to == "user@example.com"
    assert msg.subject == "[Rekit] 임시 비밀번호"
    assert "x9k2Lm" in msg.body


@pytest.mark.asyncio
async def test_console_email_sender_appends_multiple_sends() -> None:
    """여러 번 보내면 모두 누적된다 — service 단위 테스트가 호출 횟수를 검증할 수 있게."""
    # Arrange
    sender = ConsoleEmailSender()

    # Act
    await sender.send(to="a@example.com", subject="s1", body="b1")
    await sender.send(to="b@example.com", subject="s2", body="b2")

    # Assert
    assert [m.to for m in sender.sent] == ["a@example.com", "b@example.com"]


def test_console_email_sender_satisfies_email_sender_protocol() -> None:
    """ConsoleEmailSender 는 EmailSender Protocol 을 만족해야 한다 (structural typing 체크)."""
    # Arrange / Act
    sender: EmailSender = ConsoleEmailSender()

    # Assert
    assert callable(sender.send)


def test_gmail_email_sender_satisfies_email_sender_protocol() -> None:
    """GmailSmtpEmailSender 도 EmailSender Protocol 을 만족해야 한다."""
    # Arrange / Act
    sender: EmailSender = GmailSmtpEmailSender(
        user="rekit-dev@gmail.com",
        password="dummy-app-password",
        from_addr="Rekit <noreply@rekit.kr>",
    )

    # Assert
    assert callable(sender.send)
