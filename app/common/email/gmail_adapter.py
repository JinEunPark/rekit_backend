"""Gmail SMTP 어댑터 — dev/staging 발송용 (일일 500건 한도).

Gmail App Password 가 필요. 운영 단계에선 SES/Resend 등으로 갈아끼운다.

설정 절차:
1) Google 계정 → 보안 → 2단계 인증 활성화
2) https://myaccount.google.com/apppasswords 에서 App Password 발급 (16자리)
3) .env 의 GMAIL_USER / GMAIL_APP_PASSWORD / EMAIL_FROM 채우기
4) settings.email_provider = "gmail"

aiosmtplib 는 lazy import — console 어댑터만 쓰는 dev 환경에선 미설치여도 OK.
"""

from __future__ import annotations

from email.message import EmailMessage as MimeMessage


class GmailSmtpEmailSender:
    """EmailSender Protocol 구현. STARTTLS 587 포트로 Gmail SMTP 발송."""

    def __init__(self, *, user: str, password: str, from_addr: str | None = None) -> None:
        self.user = user
        self.password = password
        # from_addr 미지정 시 user(gmail 주소) 그대로 — 일관성을 위해 .env 의 EMAIL_FROM 권장
        self.from_addr = from_addr or user

    async def send(self, *, to: str, subject: str, body: str) -> None:
        # lazy import: console 어댑터만 쓰는 환경에서 aiosmtplib 미설치 허용
        import aiosmtplib

        msg = MimeMessage()
        msg["From"] = self.from_addr
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)

        await aiosmtplib.send(
            msg,
            hostname="smtp.gmail.com",
            port=587,
            start_tls=True,
            username=self.user,
            password=self.password,
        )
