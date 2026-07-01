"""SMS 발송 Mock 어댑터 — 실제 발송 대신 콘솔(로그)에 출력.

운영 환경에서는 NHN Cloud / Aligo 등 실 SMS 어댑터로 교체한다.
와이어링은 app.core.deps.get_sms_sender 에서 담당.
"""

import logging

_log = logging.getLogger(__name__)


class ConsoleSmsSender:
    """개발·테스트용 Mock. SMS 대신 INFO 로그에 출력한다."""

    async def send(self, phone: str, message: str) -> None:
        _log.info("[SMS mock] to=%s → %s", phone, message)
