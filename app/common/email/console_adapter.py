"""콘솔 출력 어댑터 — dev / 테스트 용.

실제 발송은 하지 않고 stdout 에 출력 + 인스턴스 sent 리스트에 누적한다.
- dev 단계에선 메일 도착을 콘솔에서 확인 (App Password 발급 전 / 외부망 차단 환경)
- 테스트에선 `dependency_overrides[get_email_sender] = lambda: ConsoleEmailSender()`
  로 주입해 sent 리스트로 호출 검증
"""

from __future__ import annotations

from app.common.email.ports import EmailMessage


class ConsoleEmailSender:
    """EmailSender Protocol 구현. send 호출을 stdout + 메모리에 기록."""

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    async def send(self, *, to: str, subject: str, body: str) -> None:
        msg = EmailMessage(to=to, subject=subject, body=body)
        self.sent.append(msg)
        # 한 번에 알아보기 쉽도록 구분선 + 메타 + 본문.
        print(
            "\n[EMAIL ─────────────────────────────────────]\n"
            f"To: {to}\nSubject: {subject}\n\n{body}\n"
            "[──────────────────────────────────── /EMAIL]\n"
        )
