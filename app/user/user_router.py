"""user 모듈 Router — /users prefix.

JPA 비유: @RestController + @RequestMapping("/users").

api.md §4 와 1:1 매핑:
- POST /users/me/password : 비밀번호 변경 (본인) — 본 Phase 에서 구현
- GET /users/me           : 프로필 조회 — 후속
- PATCH /users/me         : 프로필 수정 — 후속
- DELETE /users/me        : 회원탈퇴 — 후속
"""

from fastapi import APIRouter, Depends, status

from app.core.deps import get_current_user, get_user_service
from app.user.models import User
from app.user.user_schemas import ChangePasswordRequest
from app.user.user_service import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.post(
    "/me/password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="비밀번호 변경 (본인)",
)
async def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
) -> None:
    """현재 비번 확인 후 새 비번으로 교체. api.md §4.3.

    Auth required (Bearer access token). 임시 비번 발급 상태(must_change_password=True)
    여도 이 endpoint 만은 호출 가능 — 변경 후 자동으로 False 로 풀린다 (Phase E 가드).

    Errors → exception_handler 가 표준 포맷으로 변환:
    - InvalidCredentials (401, INVALID_CREDENTIALS): 현재 비번 불일치
    - 검증 실패 (422, VALIDATION_ERROR): 새 비번 정책 위반
    - 토큰 만료/누락 (401, TOKEN_EXPIRED)
    """
    service.change_password(
        user=user,
        current_password=body.current_password,
        new_password=body.new_password,
    )
