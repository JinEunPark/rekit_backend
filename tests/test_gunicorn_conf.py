"""gunicorn.conf.py 의 Prometheus 멀티프로세스 hook.

gunicorn 워커는 프로세스마다 메모리가 분리돼 메트릭을 파일로 공유한다. master 가 워커를 띄우기
전에 디렉터리를 비우고(이전 실행 값 합산 방지), 워커가 죽으면 그 워커 파일을 정리해야 한다.
"""

import runpy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_CONF_PATH = Path(__file__).resolve().parents[1] / "gunicorn.conf.py"


def _conf() -> dict[str, Any]:
    return runpy.run_path(str(_CONF_PATH))


def test_loading_conf_does_not_switch_process_to_multiprocess_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """conf 파일을 읽기만 해선 환경변수가 바뀌지 않는다 — 설정은 master hook(on_starting)에서만."""
    monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)

    _conf()

    import os

    assert "PROMETHEUS_MULTIPROC_DIR" not in os.environ


def test_on_starting_empties_stale_multiprocess_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """이전 실행이 남긴 메트릭 파일은 지운다 — 남으면 재시작 후에도 옛 값이 합산된다."""
    multiproc_dir = tmp_path / "prometheus_multiproc"
    multiproc_dir.mkdir()
    (multiproc_dir / "counter_123.db").write_bytes(b"stale")
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(multiproc_dir))

    _conf()["on_starting"](SimpleNamespace())

    assert multiproc_dir.is_dir()
    assert list(multiproc_dir.iterdir()) == []


def test_child_exit_marks_dead_worker_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """워커가 죽으면 그 pid 의 livesum Gauge(처리 중 요청 수 등) 파일을 정리한다."""
    from prometheus_client import multiprocess

    marked: list[int] = []
    monkeypatch.setattr(
        multiprocess, "mark_process_dead", lambda pid, path=None: marked.append(pid)
    )

    _conf()["child_exit"](SimpleNamespace(), SimpleNamespace(pid=4242))

    assert marked == [4242]
