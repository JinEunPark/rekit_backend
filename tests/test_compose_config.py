"""docker-compose 설정 회귀 — 운영 동작을 좌우하는데 코드 테스트로는 안 잡히는 값.

- app command 가 `exec gunicorn` 이 아니면 sh 가 PID 1 로 남아 SIGTERM 을 gunicorn 에 전달하지
  않는다 → graceful_timeout 이 무의미해지고 docker stop 유예(10초) 후 SIGKILL 로
  처리 중 요청이 끊긴다.
- pg_stat_statements 는 shared_preload_libraries 에 없으면 CREATE EXTENSION 후에도 조회가 실패한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]


def _service(compose_file: str, name: str) -> dict[str, Any]:
    compose = yaml.safe_load((_ROOT / compose_file).read_text(encoding="utf-8"))
    service: dict[str, Any] = compose["services"][name]
    return service


def test_prod_app_command_execs_gunicorn_so_sigterm_reaches_it() -> None:
    """마이그레이션 뒤 exec 로 sh 를 gunicorn 으로 교체해야 SIGTERM 을 gunicorn 이 직접 받는다."""
    command = " ".join(_service("docker-compose.prod.yml", "app")["command"].split())

    assert "alembic upgrade head && exec gunicorn -c gunicorn.conf.py app.main:app" in command


@pytest.mark.parametrize("compose_file", ["docker-compose.prod.yml", "docker-compose.yml"])
def test_postgres_command_preloads_pg_stat_statements(compose_file: str) -> None:
    """쿼리별 호출 수·시간 수집 — 로컬도 켜 둬야 로컬 부하테스트에서 같은 분석이 가능하다."""
    command = _service(compose_file, "postgres")["command"]

    assert command[0] == "postgres"
    assert "shared_preload_libraries=pg_stat_statements" in command
    assert "pg_stat_statements.track=all" in command
