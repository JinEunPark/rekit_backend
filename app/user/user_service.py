"""user 모듈 Service — 사용자 본인 정보 변경 도메인 로직.

JPA 비유: @Service. router(@RestController) 와 모델(@Entity) 사이의 비즈니스 규칙.

원칙:
- get_current_user 가 반환한 User 엔티티는 이미 세션에 attached. 속성 수정 시
  SQLAlchemy 가 dirty 추적 → router 의 db_session dependency 가 commit 시 UPDATE
  자동 발송. repository 에 별도 update 메서드 두지 않음 (단순 속성 수정 한정).
- 비즈니스 예외만 raise. router 는 try/except 하지 않음 — exception_handler 가
  표준 응답 포맷으로 변환.
"""

from app.core.exceptions import InvalidCredentials
from app.core.security import hash_password, verify_password
from app.user.models import User


class UserService:
    """사용자 본인 정보 변경. 인스턴스 상태 없음 — 단순 도메인 함수 묶음."""

    def change_password(
        self,
        *,
        user: User,
        current_password: str,
        new_password: str,
    ) -> None:
        """현재 비번 검증 후 새 비번으로 갱신. 임시 비번 강제 변경도 이 메서드로.

        Raises:
            InvalidCredentials (401): 현재 비번이 일치하지 않을 때.

        Side effects:
            - user.password_hash 갱신 (bcrypt re-hash)
            - user.must_change_password = False (임시 비번 발급 상태였다면 해제)
        """
        if not verify_password(current_password, user.password_hash):
            raise InvalidCredentials()

        user.password_hash = hash_password(new_password)
        # SQLAlchemy 가 dirty 추적을 attribute touch 기준으로 하므로 — 이미 False 면
        # 굳이 다시 쓰지 않아 일반 비번 변경 케이스에 불필요한 UPDATE column 을 만들지 않음.
        if user.must_change_password:
            user.must_change_password = False
