"""gunicorn 설정 — Dockerfile CMD / docker-compose.prod.yml command 가 `-c` 로 사용.

워커(앱) 로그는 create_app 의 configure_logging 이 맡고, 여기선 앱 import 전에 도는 master
프로세스 로그(Booting worker 등)를 같은 JSON·UTC 포맷으로 맞춘다.
FORWARDED_ALLOW_IPS 는 gunicorn 이 환경변수로 직접 읽는다 (docker-compose.prod.yml 참고).
"""

import os
import shutil
from typing import Any

from app.core.config import settings
from app.core.logging import gunicorn_logconfig_dict

# 워커 4개는 메모리가 분리돼 있어 Prometheus 메트릭을 이 디렉터리의 파일로 공유하고, /metrics 가
# 합산한다 (app.core.metrics.render_latest). 로컬 uvicorn 은 단일 프로세스라 설정하지 않는다.
_DEFAULT_PROMETHEUS_MULTIPROC_DIR = "/tmp/prometheus_multiproc"

worker_class = "uvicorn_worker.UvicornWorker"
workers = 4
bind = "0.0.0.0:8000"
errorlog = "-"
# accesslog 미설정 — 액세스 로그는 RequestContextMiddleware 가 템플릿 경로·request_id 로 남긴다
loglevel = settings.log_level.lower()
logconfig_dict = gunicorn_logconfig_dict(level=settings.log_level, json_logs=settings.json_logs)


def on_starting(server: Any) -> None:
    """master 가 워커를 띄우기 전 — 워커가 상속할 환경변수 설정 + 이전 실행의 메트릭 파일 삭제.

    파일 최상단이 아니라 여기서 설정하는 이유: conf 를 읽기만 하는 곳(테스트 등)까지 멀티프로세스
    모드로 바꾸지 않기 위해. 워커는 fork 후 앱을 import 하므로 prometheus_client 가 이 값을 본다.
    """
    multiproc_dir = os.environ.setdefault(
        "PROMETHEUS_MULTIPROC_DIR", _DEFAULT_PROMETHEUS_MULTIPROC_DIR
    )
    shutil.rmtree(multiproc_dir, ignore_errors=True)
    os.makedirs(multiproc_dir, exist_ok=True)


def child_exit(server: Any, worker: Any) -> None:
    """죽은 워커의 livesum Gauge(처리 중 요청 수 등) 파일 정리 — 안 하면 그 값이 계속 합산된다."""
    from prometheus_client import multiprocess

    multiprocess.mark_process_dead(worker.pid)
