#!/usr/bin/env bash
# docs/testcase2.md 의 남은 Task를 claude code 헤드리스 모드로 하나씩 처리하는 루프.
#
# 사용법:
#   scripts/run_testcase2_loop.sh
#
# 종료 조건: testcase2.md 에 미체크(- [ ]) 항목이 하나도 안 남으면 자동 종료.
# 레이트리밋/사용량 초과 감지 시 WAIT_SECONDS 만큼 대기 후 같은 Task 를 재시도.
set -uo pipefail   # -e 는 claude 비정상 종료 시 스크립트 전체가 죽으므로 뺀다

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOC="$REPO_DIR/docs/testcase2.md"
LOG_DIR="$REPO_DIR/.claude-loop-logs"
WAIT_SECONDS="${WAIT_SECONDS:-1200}"   # 레이트리밋 감지 시 대기 (기본 20분)
ERROR_WAIT_SECONDS="${ERROR_WAIT_SECONDS:-60}"
IDLE_SECONDS="${IDLE_SECONDS:-10}"     # 정상 반복 사이 대기

mkdir -p "$LOG_DIR"

read -r -d '' PROMPT <<'EOF'
docs/testcase2.md 를 읽고, 체크되지 않은 [ ] 항목 중 우선순위가 가장 높은
미완료 Task(또는 그 안의 서브태스크) 하나만 골라 CLAUDE.md 의 TDD 사이클
(Red -> Green -> Refactor)로 구현해라.

규칙:
- 한 번 호출당 Task/서브태스크 하나만 완결짓는다. 여러 개를 한 번에 진행하지 않는다.
- 실패하는 테스트부터 작성(Red) -> 최소 구현(Green) -> 정리(Refactor) 순서를 지킨다.
- 구현 완료 후 반드시 아래 3개를 전부 실행해서 통과를 확인한다 (app 전체 기준):
  .venv/bin/pytest -v
  .venv/bin/ruff check app tests
  .venv/bin/mypy app
- 전부 통과하면 docs/testcase2.md 의 해당 체크박스를 [x] 로 갱신하고,
  실제 구현 파일/라인 정보를 그 옆에 짧게 남긴다.
- 절대 git commit 이나 git push 를 하지 않는다. 사용자가 나중에 직접 리뷰 후
  커밋한다 (세션 규칙).
- docs/testcase2.md 의 모든 체크박스가 이미 [x] 라면 다른 작업을 하지 말고
  정확히 "ALL_DONE" 이라고만 출력하고 종료해라.
EOF

cd "$REPO_DIR" || exit 1

echo "[$(date '+%F %T')] 루프 시작 — 로그: $LOG_DIR"

while true; do
  if ! grep -qE '^\s*-\s\[ \]' "$DOC"; then
    echo "[$(date '+%F %T')] testcase2.md 에 미완료 항목 없음 — 루프 종료"
    break
  fi

  TS="$(date '+%Y%m%d_%H%M%S')"
  LOG_FILE="$LOG_DIR/run_${TS}.log"

  echo "[$(date '+%F %T')] claude 실행 시작 (log: $LOG_FILE)"

  claude -p "$PROMPT" \
    --dangerously-skip-permissions \
    --output-format text \
    > "$LOG_FILE" 2>&1
  EXIT_CODE=$?

  if grep -qiE 'rate limit|usage limit|429 |quota exceeded|overloaded' "$LOG_FILE"; then
    echo "[$(date '+%F %T')] 토큰/레이트리밋 감지 — ${WAIT_SECONDS}초 대기 후 같은 Task 재시도"
    sleep "$WAIT_SECONDS"
    continue
  fi

  if [ "$EXIT_CODE" -ne 0 ]; then
    echo "[$(date '+%F %T')] claude 비정상 종료(exit=$EXIT_CODE) — ${ERROR_WAIT_SECONDS}초 후 재시도"
    tail -n 20 "$LOG_FILE"
    sleep "$ERROR_WAIT_SECONDS"
    continue
  fi

  if grep -q "ALL_DONE" "$LOG_FILE"; then
    echo "[$(date '+%F %T')] ALL_DONE 신호 수신 — 루프 종료"
    break
  fi

  echo "[$(date '+%F %T')] 이번 반복 완료 — ${IDLE_SECONDS}초 대기 후 다음 Task"
  sleep "$IDLE_SECONDS"
done

echo "[$(date '+%F %T')] 루프 종료. 변경사항은 커밋되지 않았습니다 — git status/diff 로 직접 리뷰하세요."
