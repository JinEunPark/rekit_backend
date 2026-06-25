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

from email.message import EmailMessage


class GmailSmtpEmailSender:
    """EmailSender Protocol 구현. STARTTLS 587 포트로 Gmail SMTP 발송.

    html_body 가 전달되면 multipart/alternative 로 text + HTML 동시 발송.
    이메일 클라이언트가 HTML 지원 시 HTML 렌더링, 미지원 시 text fallback.
    """

    def __init__(self, *, user: str, password: str, from_addr: str | None = None) -> None:
        self.user = user
        self.password = password
        self.from_addr = from_addr or user

    async def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        html_body: str | None = None,
    ) -> None:
        import aiosmtplib

        msg = EmailMessage()
        msg["From"] = self.from_addr
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        if html_body:
            msg.add_alternative(html_body, subtype="html")

        await aiosmtplib.send(
            msg,
            hostname="smtp.gmail.com",
            port=587,
            start_tls=True,
            username=self.user,
            password=self.password,
        )
