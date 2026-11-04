"""gunicorn 설정 — Dockerfile CMD / docker-compose.prod.yml command 가 `-c` 로 사용.

워커(앱) 로그는 create_app 의 configure_logging 이 맡고, 여기선 앱 import 전에 도는 master
프로세스 로그(Booting worker 등)를 같은 JSON·UTC 포맷으로 맞춘다.
FORWARDED_ALLOW_IPS 는 gunicorn 이 환경변수로 직접 읽는다 (docker-compose.prod.yml 참고).
"""

from app.core.config import settings
from app.core.logging import gunicorn_logconfig_dict

worker_class = "uvicorn_worker.UvicornWorker"
workers = 4
bind = "0.0.0.0:8000"
errorlog = "-"
# accesslog 미설정 — 액세스 로그는 RequestContextMiddleware 가 템플릿 경로·request_id 로 남긴다
loglevel = settings.log_level.lower()
logconfig_dict = gunicorn_logconfig_dict(level=settings.log_level, json_logs=settings.json_logs)
