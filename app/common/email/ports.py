"""이메일 발송 port.

service 는 이 Protocol 에만 의존한다. 어댑터(console/gmail/SES/Resend) 교체 시
service / router 코드는 변경 없음.

JPA 비유: `MailSender` 인터페이스 — 구현체는 JavaMailSenderImpl 또는 fake.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EmailMessage:
    """발송된 메시지 스냅샷. 테스트 검증과 디버깅용 — 어댑터별로 동일 형태."""

    to: str
    subject: str
    body: str


class EmailSender(Protocol):
    """이메일 발송 인터페이스. 구현체는 동기/비동기 어느 백엔드든 OK."""

    async def send(self, *, to: str, subject: str, body: str) -> None: ...
