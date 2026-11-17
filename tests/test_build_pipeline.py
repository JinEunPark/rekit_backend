"""빌드 파이프라인 회귀 — 테스트를 통과한 코드만 운영 이미지가 되는지.

배포 잡(deploy-was)은 registry 에 있는 태그 이미지만 띄운다. 그래서 빌드 잡(build-was)이
검사 실패 시 이미지를 push 하지 않으면, 검사를 통과하지 못한 태그는 배포할 이미지 자체가 없다.

- Dockerfile 의 test 단계가 ruff · mypy · 단위 테스트를 실행해야 한다
- 마지막 단계는 운영 이미지여야 한다 — 기본 build 대상이 test 가 되면 운영 이미지에 dev 도구가 들어간다
- Jenkinsfile.build 는 Build & Push 앞에서 test 단계를 빌드해야 한다
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _stages(dockerfile: str) -> list[str]:
    return re.findall(r"^FROM\s+\S+\s+AS\s+(\S+)", dockerfile, flags=re.MULTILINE | re.IGNORECASE)


def _stage_body(dockerfile: str, name: str) -> str:
    match = re.search(
        rf"^FROM\s+\S+\s+AS\s+{name}\s*$(.*?)(?=^FROM\s|\Z)",
        dockerfile,
        flags=re.MULTILINE | re.IGNORECASE | re.DOTALL,
    )
    assert match, f"Dockerfile 에 {name} 단계가 없다"
    return match.group(1)


def test_dockerfile_test_stage_runs_lint_type_and_unit_tests() -> None:
    """test 단계 하나만 빌드해도 세 가지 게이트가 모두 돈다."""
    body = _stage_body((_ROOT / "Dockerfile").read_text(encoding="utf-8"), "test")

    assert "ruff check app tests" in body
    assert "mypy app" in body
    assert "pytest" in body
    assert "--ignore=tests/integration" in body  # 통합 테스트는 PostgreSQL 이 필요해 2단계
    assert '-m "not infra"' in body  # 폴더 밖에 있지만 실제 DB·Redis 에 붙는 테스트도 제외


def test_infra_marker_is_registered() -> None:
    """등록 안 된 마커는 오타여도 조용히 통과한다 — 등록해 두어야 -m 필터가 의미를 가진다."""
    pyproject = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert re.search(r'markers\s*=\s*\[[^\]]*"infra:', pyproject, flags=re.DOTALL)


def test_tests_that_connect_to_real_infra_are_marked() -> None:
    """integration 폴더 밖에서 실제 DB·Redis 에 붙는 테스트는 infra 마커가 있어야 빌드 게이트에서 빠진다."""
    unmarked: list[str] = []
    for path in (_ROOT / "tests").glob("test_*.py"):
        if path.name == Path(__file__).name:  # 이 파일은 검사 문자열을 담고 있다
            continue
        source = path.read_text(encoding="utf-8")
        # 최상위 정의 단위로 자른다: (데코레이터들, 이름, 본문)
        chunks = re.split(r"\n(?=@|(?:async )?def |class )", source)
        decorators = ""
        for chunk in chunks:
            if chunk.startswith("@"):
                decorators += chunk
                continue
            name = re.match(r"(?:async )?def (test_\w+)\(", chunk)
            if name:
                touches_infra = (
                    "engine.connect()" in chunk
                    or "_pg_setting_ms(" in chunk
                    or "real_database" in name.group(1)
                )
                if touches_infra and "pytest.mark.infra" not in decorators:
                    unmarked.append(f"{path.name}::{name.group(1)}")
            decorators = ""

    assert unmarked == []


def test_dockerfile_last_stage_is_runtime_not_test() -> None:
    """기본 build 대상(마지막 단계)이 운영 이미지여야 dev 도구가 운영 이미지에 들어가지 않는다."""
    stages = _stages((_ROOT / "Dockerfile").read_text(encoding="utf-8"))

    assert stages[-1] == "runtime"
    assert stages.index("test") < stages.index("runtime")


def test_jenkins_build_runs_test_stage_before_push() -> None:
    """검사가 실패하면 Build & Push 에 도달하지 않아 registry 에 이미지가 생기지 않는다."""
    jenkinsfile = (_ROOT / "Jenkinsfile.build").read_text(encoding="utf-8")

    test_at = jenkinsfile.find("stage('Test')")
    push_at = jenkinsfile.find("stage('Build & Push')")
    assert test_at != -1, "Jenkinsfile.build 에 Test 단계가 없다"
    assert test_at < push_at
    assert "--target test" in jenkinsfile
    assert "--target runtime" in jenkinsfile
