# 본인인증(CI/DI) 폐지 → Octomo 전화번호 인증(1회)로 대체 — 작업 목록

> **배경**: 이전 대화에서 확인한 대로 CI/DI 기반 실명 본인인증은 법적 의무가 아니고
> (전자상거래법은 개인 간 거래에 사업자 규제가 직접 적용되지 않고, CI/DI 수집을
> 강제하는 조항도 없음 — 오히려 최근 규제 흐름은 신원정보 수집을 최소화하는 방향),
> 지금 코드에 있는 CI/DI 관련 구조는 **아직 실제로 연동된 적 없는 스캐폴딩**
> (Protocol/모델만 있고 어댑터/라우터 미구현) 상태다. 이 기회에 CI/DI를 완전히
> 걷어내고, [Octomo](https://octomo.octoverse.kr) 의 MO(Mobile Originated) 기반
> 전화번호 인증 **한 번**으로 "본인 확인"을 대체한다.
>
> **참고 레포**: https://github.com/Octoverse-corp-official/octomo-sample-code
> (Node.js/Express 샘플 서버 + Next.js 샘플 프론트 — 아래 0절에 실제 코드 기준으로
> API 계약을 정리해뒀다)
>
> **사용법**: `testcase.md`/`testcase2.md`/`nicepay_migration.md`와 동일한 형식.
> Red(실패 테스트) → Green(구현) → Refactor 순으로 진행, 체크박스 갱신하며
> 세션 간 이어간다.
>
> **작성일**: 2026-07-10

---

## 0. Octomo API 레퍼런스 (샘플 레포 실제 코드 기준으로 조사 완료)

### 0-1. 인증 흐름 — **QR 코드 방식으로 확정**(샘플 레포의 두 옵션 중 QR 스캔 채택)

샘플 레포는 "코드를 보고 사용자가 직접 SMS 앱에 타이핑"하는 방식과 "QR 스캔으로
수신번호+본문이 자동으로 채워진 SMS 앱이 열리는" 방식 두 가지를 다 제공하는데,
**이 프로젝트는 QR 방식으로 구현하기로 확정**(사용자 결정). 타이핑 오류가 없고
탭 한 번으로 문자 앱까지 열리므로 전환율이 더 높다.

```
1. 사용자가 전화번호 입력 후 "인증" 클릭
2. 서버: 코드 생성 + 저장(TTL) → Octomo QR 코드 발급 API 호출(text에 그 코드 포함)
   → { code, qrCode } 반환 (qrCode = "data:image/png;base64,...")
3. 프론트: QR 이미지 표시 + "카메라로 스캔해서 문자를 보내주세요" 안내
4. 사용자가 휴대폰 카메라로 QR 스캔 → 수신번호(1666-3538)+본문(코드)이 이미 채워진
   문자 앱이 열림 → 사용자는 "전송"만 누르면 됨  ← 서버가 보내는 게 아님!
5. 사용자가 "인증하기" 클릭
6. 서버 → Octomo API(`/message/exists`): 그 전화번호로 그 코드가 도착했는지 조회
7. 서버 → 프론트: { verified: true | false }
```

**QR 방식을 택하면서 바뀌는 점**: 사용자가 코드를 손으로 타이핑하지 않으므로
"코드가 길면 오타 위험" 제약이 사라진다 — Task 0-5에서 코드 형식을 재검토한다.

**핵심 차이(현재 코드와 대비)**: 지금 `UserService.send_phone_verification`
(`app/user/user_service.py:81-97`)은 **서버가 SMS를 발송**하는 정방향 OTP다
(`SmsSender.send(phone, message)` — 현재 mock인 `ConsoleSmsSender`, 운영에서는
NHN Cloud/알리고 등 실제 발신 어댑터 필요). Octomo는 **역방향**이다 — 서버는
코드를 만들어 보여주기만 하고, 발송은 사용자가 직접 한다. **서버발 SMS 발송 자체가
필요 없어진다** → NHN Cloud/알리고 연동 자체를 안 해도 됨 (Task 6에서 처리).

### 0-2. Octomo 실제 API 스펙

- **Base URL**: `https://api.octoverse.kr`
- **인증**: `Authorization: Octomo {API_KEY}` 헤더 (마이페이지에서 발급)

**수신 검증**:
```
POST /octomo/v1/public/message/exists
Content-Type: application/json
Authorization: Octomo {API_KEY}

{ "mobileNum": "01012345678", "text": "482913", "withinMinutes": 5 }
```
응답: `{ "exists": true | false }`

**SMS QR 코드 발급 — 채택된 방식**(0-1 참고). 사용자가 코드를 직접 타이핑해서
문자 앱을 여는 대신, QR을 스캔하면 수신번호+본문이 미리 채워진 문자 앱이 열림:
```
POST /octomo/v1/public/message/qr-code
{ "text": "인증코드 482913", "errorCorrectionLevel"?: "L|M|Q|H", "margin"?: 0-20, "width"?: 100-1000 }
```
응답: `{ "qrCode": "data:image/png;base64,..." }`

**주의**: `qr-code` 발급에 쓴 `text`와 `/message/exists` 조회에 쓸 `text`가 **정확히
일치**해야 한다(대소문자/공백 포함) — 발급 시 `"인증코드 {code}"`처럼 접두어를
붙였다면 조회 시에도 똑같은 문자열로 조회해야 한다. 아니면 접두어 없이 코드
값 자체만 `text`로 통일하는 게 더 안전(Task 1 목표 코드는 후자로 작성).

### 0-3. 요금

Free(0원/월, 월 10,000건) / Pro(9,900원/월, 월 100,000건) / Enterprise(협의).
지금 트래픽 규모면 Free로 충분.

### 0-4. 샘플 서버 코드 그대로 참고할 부분 (`octomo_sample_server/src/services/octomo.client.ts`)

```typescript
const OCTOMO_API_BASE = 'https://api.octoverse.kr';

export async function checkMessageExists(
  mobileNum: string, text: string, withinMinutes: number,
): Promise<boolean> {
  const res = await fetch(`${OCTOMO_API_BASE}/octomo/v1/public/message/exists`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Octomo ${OCTOMO_API_KEY}` },
    body: JSON.stringify({ mobileNum, text, withinMinutes }),
  });
  if (!res.ok) throw new Error(`Octomo API error: ${res.status} ${await res.text()}`);
  return (await res.json()).exists === true;
}
```

**보안 권고(샘플 레포 주석 그대로 인용)**: "실제 서비스에서는 숫자 코드 대신 암호화된
문자열을 사용하는 것을 권장" — 브루트포스/추측 방지. 우리는 이미 Redis 기반이라
TTL(5분)+rate-limit(60초)이 있어 어느 정도 완화돼 있음(`user_service.py`의 기존
`_PHONE_OTP_TTL`/`_PHONE_OTP_RATE_TTL`) — 그대로 재사용하면 됨. 6자리 숫자 유지 여부는
Task 1에서 재검토.

---

## 1. 현재 코드 전수조사 — CI/DI 관련 코드 위치

| 파일 | 내용 | 처리 |
|---|---|---|
| `app/auth/adapters/ports.py:29-38` | `IdentityVerifyResult`(ci, di, name, phone, birth_date, gender) | 삭제 |
| `app/auth/adapters/ports.py:67-70` | `IdentityVerifier` Protocol (`verify_callback`) | 삭제 |
| `app/auth/models.py:67-72` | `IdentityProvider` enum(TOSS/NICE/KCB) | 삭제 |
| `app/auth/models.py:82-128` | `IdentityVerification` 모델(시도 로그 테이블) | 삭제 (테이블 DROP) |
| `app/auth/__init__.py:1,3` | `IdentityProvider`, `IdentityVerification` export | 삭제 |
| `app/db/registry.py:10` | `IdentityVerification` import (Alembic 등록용) | 삭제 |
| `app/user/models.py:33-38` | `Gender` enum | 삭제 (Task 0-3 결정에 따름) |
| `app/user/models.py:150-159` | `User.ci`, `User.di`, `User.birth_date`, `User.gender` 컬럼 | 삭제 (DB 마이그레이션 필요) |
| `app/user/models.py:145-149` | `User.identity_verified_at` | **삭제**(Task 0-1 옵션 B 확정) |
| `app/user/models.py:183-185` | `identity_verifications` relationship | 삭제 |
| `app/user/models.py:190-193` | `User.verified` property | 유지하되 `phone_verified_at is not None`으로 재정의 |
| `app/user/user_service.py:70-75` | `withdraw()`에서 `ci`/`di`/`birth_date`/`gender = None` | 해당 라인만 제거 |
| `app/user/user_service.py:81-113` | `send_phone_verification`/`verify_phone` (현재 SmsSender 발신 방식) | Octomo 방식으로 교체 |
| `app/user/admin_members_repository.py:52` | `User.identity_verified_at.is_not(None)` 필터 | **변경**: `User.phone_verified_at.is_not(None)`으로 (Task 5) |
| `app/user/admin_members_schemas.py:44` | `identity_verified_at: datetime \| None` | **변경**: 필드명을 `phone_verified_at`으로(또는 유지하되 값 출처만 교체 — Task 5에서 결정) |
| `app/user/admin_members_service.py:51` | `identity_verified_at=row.user.identity_verified_at` | **변경**: `row.user.phone_verified_at` 참조로 (Task 5) |
| `app/order/order_service.py:90-98` | `create_order`의 `identity_verified` 가드 → `IdentityRequiredError` | **변경 불필요**(게이트 로직 자체는 유지 — `user.verified`가 내부적으로 보는 컬럼만 바뀜) |
| `app/order/order_router.py:50` | `identity_verified=user.verified` | **변경 불필요** |
| `app/core/exceptions.py:120-123` | `IdentityRequiredError` | 유지(메시지만 "본인인증"→"휴대폰 인증"으로 다듬을지 선택) |
| `app/auth/auth_schemas.py:319-330` | `UserResponse.verified` 필드 설명 주석("= identity_verified_at IS NOT NULL") | 주석 갱신 — "= phone_verified_at IS NOT NULL"로(Task 0-1 옵션 B) |
| `.env.example:56-63` | `IDENTITY_PROVIDER=toss`(원래도 안 읽히던 죽은 값) | 삭제 |
| `.env.example:65-68` | `SMS_PROVIDER`/`SMS_API_KEY`/`SMS_SENDER` | Task 6 결정에 따라 삭제 가능 |
| `docs/요구사항정의서.md` §2.4 | 본인인증 3단계 표, CI/DI 데이터 보관 정책 | 갱신 |
| `alembic/versions/e9bcd41ab78f_init_schema.py` | `users.ci`/`di`/`birth_date`/`gender`, `identity_verifications` 테이블 최초 생성 | **건드리지 않음** — 새 revision을 추가해서 DROP (과거 마이그레이션 수정 금지 원칙) |
| `tests/*` | 아래 Task 8 참고 | 이관 |

**참고**: `app/auth/adapters/`에는애초에 `toss.py`/`nice.py` 같은 실제 `IdentityVerifier`
구현체가 **존재한 적이 없다** — Protocol과 모델만 있던 순수 스캐폴딩. 그래서 이번
작업은 "PG를 갈아끼우는" 게 아니라 "안 쓰던 미래 계획을 걷어내는" 것에 가깝다 —
`nicepay_migration.md`보다 오히려 단순하다.

---

## 우선순위 요약

| # | Task | 비고 |
|---|---|---|
| 0 | 설계 결정 확정 | 필수, 최우선 |
| 1 | `OctomoPhoneVerifier` 어댑터 구현 | Octomo API 키 필요 |
| 2 | `UserService` 전화번호 인증 로직을 Octomo 방식으로 교체 | Task 1 선행 |
| 3 | `order_service.py` 게이트 재확인(로직 변경 없음, 회귀 확인용) | Task 2 이후 |
| 4 | CI/DI 모델/스키마/Protocol 삭제 + Alembic 마이그레이션 | Task 0 결정 후 아무때나 |
| 5 | admin_members 필드명 교체(`identity_verified_at`→`phone_verified_at`) | Task 4 이후, 옵션 B 확정으로 실변경 필요 |
| 6 | `SmsSender`/`ConsoleSmsSender`/`OtpSender` 처리 여부 결정 | 독립적 |
| 7 | 문서/환경설정 정리 | 마지막 |
| 8 | 테스트 전수 이관 | 전체 완료 후 |

---

## Task 0 — 설계 결정 (구현 전 필수)

- [x] **결정 0-1 (가장 중요) — 확정: 옵션 B**(사용자 확인 완료). `identity_verified_at`
      컬럼을 아예 없애고 `phone_verified_at` 하나로 완전히 합친다. 즉 1차(회원가입
      SMS)/2차(첫 주문 전 인증)를 개념적으로도 완전히 하나로 만든다 — Octomo
      전화번호 인증 **딱 한 번**만 존재하고, 그게 곧 `User.verified`의 기준이 된다.
      - `User.verified` property: `identity_verified_at is not None` →
        `phone_verified_at is not None`으로 재정의(Task 4).
      - `order_service.py`/`order_router.py`의 `identity_verified=user.verified`
        호출부 자체는 무변경(속성 이름이 같으므로) — 다만 `User.verified`가
        내부적으로 보는 컬럼이 바뀐다.
      - `admin_members_repository.py`/`admin_members_schemas.py`/
        `admin_members_service.py`는 **실제 코드 변경 필요**(Task 5 전면 재작성 —
        더 이상 "무변경 확인"이 아님).
      - `UserService.verify_phone()`은 `identity_verified_at`을 더 이상 채우지
        않는다 — `phone_verified_at`만 채움(Task 2).
      - 아래 Task 2/4/5는 전부 이 옵션 B 기준으로 갱신돼 있음.
- [x] **결정 0-2 — 확정(사용자 확인 완료)**: 미성년자(만 14세 미만) 차단 기능
      **폐기**. 지난 턴에 확인했듯 법적 의무가 아니고, CI/DI 없이는 강제할
      신뢰 가능한 수단이 없어지는 이상 자기신고 생년월일도 실효성이 없다는
      판단에 사용자도 동의 — `birth_date`/`gender`/`Gender` enum 완전 삭제
      (Task 4에 반영됨).
- [x] **결정 0-3**: 분쟁(차지백/사기) 대응용 신원 확인 목적을 어떻게 대체할지.
      - 검토 결과: 전화번호(Octomo로 실사용자 소유 확인됨) + 결제 시 카드사
        본인확인(3차, PG가 이미 처리하고 카드사가 실제 명의 정보를 보유) +
        배송지(실주소) 조합으로 분쟁 대응에 필요한 최소한의 신원 단서는
        이미 확보된다고 판단 — **별도 대체 조치 불필요**로 결론.
      - 이견 있으면 이 항목만 재論의.
- [x] **결정 0-4**: Octomo API 키 발급 상태 확인(마이페이지: https://octomo.octoverse.kr).
      키 없으면 Task 1은 스펙만 구현하고 실동작 검증은 키 발급 후로 미룸.
- [x] **결정 0-5**: 인증 코드 형식 — **QR 방식 채택으로 사용자가 코드를 직접
      타이핑할 일이 없어졌으므로**("오타 위험" 제약 해소), 굳이 6자리 숫자를
      고집할 이유가 없다. Octomo 샘플 코드 주석의 권고("암호화된 문자열 사용
      권장 — 브루트포스/추측 방지")를 그대로 따라 **`secrets.token_hex(8)`
      (16자 hex) 로 강화**한다. QR 스캔이 실패해서 수동 입력으로 폴백하는
      예외 케이스가 있다면 그때만 UX 부담이 있지만, 주 경로가 QR인 이상
      보안을 우선한다. (Task 1 목표 코드에 반영됨)
- [x] **결정 0-6**: 기존 운영 데이터에 이미 `ci`/`di`/`birth_date`/`gender`
      값이 채워진 사용자가 있는지 확인. 없으면(대부분 미연동 상태였으므로
      거의 확실히 없음) 그냥 컬럼 DROP. 있으면 삭제 전 백업 필요.

---

## Task 1 — `OctomoPhoneVerifier` 어댑터 구현

**완료** → `app/auth/adapters/octomo.py`(신규), `app/auth/adapters/ports.py`
(`PhoneVerifier`/`PhoneVerificationChallenge`), `app/core/config.py`
(`octomo_api_key`), `app/core/deps.py`(`get_user_service`가 직접
`OctomoPhoneVerifier(redis)` 생성). 실제 Octomo API 키로 QR 발급 호출까지
스모크 테스트 통과. TDD: `tests/test_octomo_adapter.py` 11개 전부 통과,
커버리지 100%.

**현재 Protocol** (`app/auth/adapters/ports.py:44-53`):
```python
class OtpSender(Protocol):
    """SMS OTP 발송기 — 회원가입/비번재설정 1차 인증."""
    async def send(self, phone: str) -> str: ...
    async def verify(self, verify_token: str, code: str) -> bool: ...
```

**문제**: `OtpSender.send(phone) -> verify_token`은 "서버가 코드를 만들어 발송하고
verify_token을 반환"하는 정방향 모델을 전제로 한 시그니처인데, **이 Protocol은
지금 어디서도 실제로 쓰이고 있지 않다**(`UserService`는 `SmsSender`를 쓰지
`OtpSender`를 쓰지 않음 — grep 결과 `OtpSender`는 정의만 있고 구현체/호출부가
없는 죽은 Protocol). Octomo 모델(서버는 코드 생성+표시만, 발송은 사용자가 함,
검증은 "그 문자가 도착했는지 조회")에는 `OtpSender`도 `SmsSender`도 잘 안 맞는다
— 신규 Protocol을 만드는 게 깔끔하다.

**목표 코드** (`app/auth/adapters/ports.py`에 추가):
```python
@dataclass(frozen=True)
class PhoneVerificationChallenge:
    """전화번호 인증 1단계(issue) 결과 — 프론트에 그대로 반환된다."""

    code: str  # Octomo /message/exists 조회에 쓰이는 원본 값(디버깅/재시도용, 응답에 노출 안 해도 됨)
    qr_code: str  # "data:image/png;base64,..." — 프론트가 <img> 로 바로 표시


class PhoneVerifier(Protocol):
    """전화번호 소유 확인 — Octomo MO 인증(QR 방식) 어댑터 인터페이스.

    OtpSender 와 달리 서버가 SMS 를 발송하지 않는다. issue_challenge 는 코드를
    생성·저장하고 그 코드가 담긴 SMS QR 이미지를 Octomo 에서 발급받아 반환할
    뿐 — 실제 발송(스캔 후 전송)은 사용자가 직접 한다. verify 는 "그 문자가
    실제로 도착했는지" PG(Octomo) 에 조회한다.
    """

    async def issue_challenge(self, phone: str) -> PhoneVerificationChallenge:
        """코드를 생성·저장하고, 그 코드의 SMS QR 을 발급해 함께 반환한다."""
        ...

    async def verify(self, phone: str) -> bool:
        """이 phone 에 대해 발급해둔 코드가 담긴 메시지가 최근 도착했는지 확인한다.

        QR 방식이라 사용자는 코드 값 자체를 본 적이 없다(문자 앱에 이미
        채워져 있던 걸 전송만 함) — 그래서 `code`를 인자로 받지 않는다.
        검증 대상 코드는 `issue_challenge`가 저장해둔 값을 내부적으로 재조회한다.
        """
        ...
```
`dataclass` import가 `ports.py` 상단에 이미 있는지 확인(`IdentityVerifyResult`용으로
있었지만 그건 이번에 삭제 대상 — `SocialProfile`용으로 여전히 남아있으므로 무변경).

- [x] `OtpSender` Protocol 삭제(죽은 코드, 아무도 안 씀 — 확인 후 삭제).
      **주의**: 삭제 전 `grep -rn "OtpSender" app tests`로 정말 아무 데도
      안 쓰이는지 한 번 더 확인(이 조사 시점 기준으로는 미사용 확인됨).
- [x] `PhoneVerifier` Protocol 신규 추가.
- [x] `app/auth/adapters/octomo.py` 신규 생성:
      ```python
      """Octomo 전화번호 인증(MO 기반, QR 방식) 어댑터. PhoneVerifier Protocol 구현체."""

      from __future__ import annotations

      import secrets

      import httpx
      from redis.asyncio import Redis

      from app.auth.adapters.ports import PhoneVerificationChallenge
      from app.core.config import settings

      _OCTOMO_API_BASE = "https://api.octoverse.kr"
      _CODE_TTL_SECONDS = 300  # 5분 — Octomo withinMinutes 와 일치시킴
      _WITHIN_MINUTES = 5
      _CODE_KEY = "octomo:phone-code:{}"


      class OctomoPhoneVerifier:
          def __init__(self, redis: Redis) -> None:
              self._redis = redis

          def _auth_headers(self) -> dict[str, str]:
              api_key = getattr(settings, "octomo_api_key", "") or ""
              if not api_key:
                  raise RuntimeError("OCTOMO_API_KEY 가 설정되지 않았습니다.")
              return {"Content-Type": "application/json", "Authorization": f"Octomo {api_key}"}

          async def issue_challenge(self, phone: str) -> PhoneVerificationChallenge:
              # Task 0-5 — QR 방식이라 사용자가 직접 안 치므로 16자 hex 로 강화.
              code = secrets.token_hex(8)
              await self._redis.set(_CODE_KEY.format(phone), code, ex=_CODE_TTL_SECONDS)

              async with httpx.AsyncClient(timeout=10.0) as client:
                  resp = await client.post(
                      f"{_OCTOMO_API_BASE}/octomo/v1/public/message/qr-code",
                      json={"text": code},
                      headers=self._auth_headers(),
                  )
              if resp.status_code != 200:
                  raise RuntimeError(f"Octomo QR API 오류: {resp.status_code} {resp.text}")

              qr_code = resp.json()["qrCode"]
              return PhoneVerificationChallenge(code=code, qr_code=qr_code)

          async def verify(self, phone: str) -> bool:
              code = await self._redis.get(_CODE_KEY.format(phone))
              if code is None:
                  return False  # 발급된 적 없거나 TTL 만료 — Octomo 호출 자체가 무의미

              async with httpx.AsyncClient(timeout=10.0) as client:
                  resp = await client.post(
                      f"{_OCTOMO_API_BASE}/octomo/v1/public/message/exists",
                      json={"mobileNum": phone, "text": code, "withinMinutes": _WITHIN_MINUTES},
                      headers=self._auth_headers(),
                  )
              if resp.status_code != 200:
                  raise RuntimeError(f"Octomo API 오류: {resp.status_code} {resp.text}")

              exists = bool(resp.json().get("exists"))
              if exists:
                  await self._redis.delete(_CODE_KEY.format(phone))  # 재사용 방지
              return exists
      ```
      **설계 참고 1**: `verify(phone)`이 `code`를 인자로 받지 않는 이유 — QR
      방식에서는 사용자가 코드 값을 본 적이 없다(문자 앱에 이미 채워진 채로
      전송만 함). 그래서 검증은 "서버가 이 phone 에 대해 발급해둔 코드"를
      Redis에서 스스로 재조회해서 Octomo에 물어보는 방식이다 — 프론트가
      코드를 다시 제출할 필요 자체가 없다. `code is None`(TTL 만료/미발급)이면
      Octomo API 호출 없이 바로 실패 처리해서 불필요한 과금/레이트리밋 소모를 막는다.
      **설계 참고 2**: QR 발급 시 `text`에 코드 값만 그대로 넣는다(0-2절 주의사항
      — "인증코드 {code}" 같은 접두어를 붙이면 `/message/exists` 조회 시
      정확히 같은 문자열을 넣어야 하는 번거로움이 생기므로, 접두어 없이 값
      자체로 통일).
- [x] `app/core/config.py`: `octomo_api_key: str | None = None` 추가.
- [x] `.env.example`: `OCTOMO_API_KEY=` 추가(민감값이라 default 비움).
- [x] `app/core/deps.py`에 `get_phone_verifier` 팩토리 추가(패턴은 기존
      `_cached_sms_sender`와 유사하되 Redis 인스턴스를 주입).

**TDD** (`tests/test_octomo_adapter.py`, 신규):
1. `test_issue_challenge_generates_16_char_hex_code`
2. `test_issue_challenge_stores_code_in_redis_with_ttl`
3. `test_issue_challenge_calls_qr_code_api_with_code_as_text`
   - `httpx.MockTransport`로 `{"qrCode": "data:image/png;base64,..."}` mock,
     요청 바디의 `text`가 저장된 code와 일치하는지 확인
4. `test_issue_challenge_returns_qr_code_from_response`
5. `test_verify_with_stored_code_calls_octomo_exists_and_returns_true`
6. `test_verify_no_stored_code_does_not_call_octomo_api`
   - Given: Redis에 코드가 없음(미발급/TTL 만료) — Octomo API 호출 자체가
     안 일어나는지(mock transport 호출 카운터로 확인)
7. `test_verify_octomo_returns_false_when_message_not_found`
8. `test_verify_success_deletes_code_from_redis` (재사용/재검증 방지)
9. `test_issue_challenge_no_api_key_raises_runtime_error`
10. `test_verify_no_api_key_raises_runtime_error`

---

## Task 2 — `UserService` 전화번호 인증 로직을 Octomo 방식으로 교체

**완료** → `app/user/user_service.py`, `app/user/user_router.py`,
`app/user/user_schemas.py`(`PhoneSendResponse` 추가, `PhoneVerifyRequest`에서
`code` 제거). TDD: `tests/test_user_phone_verification.py` 전면 재작성, 4개 통과.

**현재 코드** (`app/user/user_service.py:81-113`):
```python
async def send_phone_verification(self, *, phone: str) -> None:
    assert self._redis is not None and self._sms_sender is not None
    locked = await self._redis.set(_PHONE_OTP_RATE_KEY.format(phone), "1", nx=True, ex=_PHONE_OTP_RATE_TTL)
    if locked is None:
        raise OtpRateLimitedError()
    code = "".join(secrets.choice("0123456789") for _ in range(6))
    await self._redis.set(_PHONE_OTP_KEY.format(phone), code, ex=_PHONE_OTP_TTL)
    await self._sms_sender.send(phone, f"[Rekle] 인증번호: {code}")

async def verify_phone(self, *, user: User, phone: str, code: str) -> None:
    assert self._redis is not None
    stored = await self._redis.get(_PHONE_OTP_KEY.format(phone))
    if stored != code:
        raise OtpInvalidError()
    await self._redis.delete(_PHONE_OTP_KEY.format(phone))
    user.phone = phone
    user.phone_verified_at = datetime.now(UTC)
```

**목표 코드**:
```python
async def send_phone_verification(self, *, phone: str) -> PhoneVerificationChallenge:
    """Octomo 인증 QR 을 발급한다. rate-limit: 60초.

    반환값(qr_code)은 프론트가 <img> 로 그대로 표시할 값 — "카메라로 스캔해서
    문자를 보내주세요" 안내에 쓰인다. 서버가 SMS 를 발송하지 않는다.

    Raises:
        OtpRateLimitedError (429): 60초 이내 재요청.
    """
    assert self._redis is not None and self._phone_verifier is not None

    locked = await self._redis.set(
        _PHONE_OTP_RATE_KEY.format(phone), "1", nx=True, ex=_PHONE_OTP_RATE_TTL
    )
    if locked is None:
        raise OtpRateLimitedError()

    return await self._phone_verifier.issue_challenge(phone)

async def verify_phone(self, *, user: User, phone: str) -> None:
    """Octomo 로 수신 여부 확인 후 phone / phone_verified_at 갱신.

    QR 방식이라 프론트가 code 를 제출하지 않는다 — 서버가 발급해둔 코드를
    스스로 재조회해서 Octomo 에 확인한다.
    Task 0-1 결정(옵션 B)에 따라 `identity_verified_at`은 더 이상 존재하지
    않는다 — `phone_verified_at` 하나가 1차/2차 인증을 동시에 대표한다.

    Raises:
        OtpInvalidError (422): 미발급/만료 또는 Octomo 수신 확인 실패.
    """
    assert self._phone_verifier is not None

    if not await self._phone_verifier.verify(phone):
        raise OtpInvalidError()

    user.phone = phone
    user.phone_verified_at = datetime.now(UTC)
```

- [x] `UserService.__init__`의 `sms_sender: SmsSender | None` 파라미터를
      `phone_verifier: PhoneVerifier | None`로 교체(생성자 시그니처 변경 —
      호출부는 `app/core/deps.py::get_user_service` 한 곳뿐이라 영향 범위 작음).
- [x] 위 두 메서드 교체. **`send_phone_verification`의 반환 타입이
      `None → PhoneVerificationChallenge`로 바뀜** — 라우터(`user_router.py:85-94`)도
      응답을 `status_code=204`(No Content)에서 **QR 이미지를 응답 바디에 실어
      반환하도록 변경 필요**(Task 2-1 참고, 아래).
- [x] `import secrets`가 이제 `user_service.py`에서 불필요해지면 제거(→ 어댑터로 이동).

### 2-1. 라우터 변경 (`app/user/user_router.py:79-94`)

**현재**: `status_code=204`, 응답 바디 없음.

**목표**: QR 이미지를 프론트가 받아서 보여줘야 하므로 응답 스키마 필요.
```python
class PhoneSendResponse(BaseModel):
    qr_code: str = Field(
        serialization_alias="qrCode",
        description="data:image/png;base64,... — 프론트가 <img> 로 바로 표시",
    )

@router.post(
    "/me/phone/send-verification",
    response_model=PhoneSendResponse,
    status_code=status.HTTP_200_OK,
    summary="Octomo 인증 QR 발급",
    dependencies=[Depends(get_active_user)],
)
async def send_phone_verification(
    body: PhoneSendRequest,
    service: UserService = Depends(get_user_service),
) -> PhoneSendResponse:
    """Octomo 인증 QR 발급. 프론트가 QR 을 보여주고 "카메라로 스캔" 안내.

    Errors:
    - OtpRateLimitedError (429): 60초 이내 재요청.
    """
    challenge = await service.send_phone_verification(phone=body.phone)
    return PhoneSendResponse(qr_code=challenge.qr_code)
```
- [x] `PhoneSendResponse` 스키마 추가(`app/user/user_schemas.py`) — `code`는
      응답에 굳이 안 실어도 됨(QR 안에 이미 인코딩돼 있고, 서버가 Redis로
      들고 있어 verify 시 재조회 불필요 — 프론트는 QR 이미지와 phone 값만
      들고 있으면 됨).
- [x] 라우터 응답 형식 변경 적용.
- [x] `/me/phone/verify`(102-112줄) — **요청 바디에서 `code` 필드 제거**
      (`PhoneVerifyRequest`도 `phone`만 남기고 `code` 삭제). QR 방식이라
      프론트가 코드 값을 아예 모르므로 제출할 게 없다:
      ```python
      async def verify_phone(
          body: PhoneVerifyRequest,
          user: User = Depends(get_active_user),
          service: UserService = Depends(get_user_service),
      ) -> None:
          await service.verify_phone(user=user, phone=body.phone)
      ```
- [x] **프론트 영향**: 이 엔드포인트를 쓰는 프론트 화면이 "204 No Content"만
      기대하고 있었다면 코드 표시 UI 자체가 아예 없었을 가능성 높음(SMS
      발신 방식이었으니까 코드를 보여줄 필요가 없었음) — 프론트에 **QR 이미지
      표시 팝업 + "카메라로 스캔해서 문자를 보내주세요" 안내 UI를 새로
      추가**해야 함. 아래 "클라이언트(프론트엔드) 변경 작업"(FE Task 2)에서
      구체적으로 다룸.

**TDD** (`tests/test_user_service.py`, 기존 `send_phone_verification`/
`verify_phone` 테스트 전면 교체):
1. `test_send_phone_verification_returns_challenge_from_verifier`
2. `test_send_phone_verification_rate_limited_within_60s_raises`
3. `test_verify_phone_success_sets_phone_and_phone_verified_at`
   - Then: `user.phone == phone`, `user.phone_verified_at is not None`
     (Task 0-1 옵션 B 확정 — `identity_verified_at` 자체가 이제 없으므로 검증 대상도 아님)
4. `test_verify_phone_failure_raises_otp_invalid_and_does_not_set_timestamps`

`tests/integration/test_user_router.py`(있다면 갱신, 없으면 신규):
5. `test_send_verification_endpoint_returns_qr_code_in_body`

---

## Task 3 — `order_service.py` 게이트 회귀 확인 (로직 변경 없음)

**완료** → `app/order/order_service.py`(주석 갱신), `app/core/exceptions.py`
(`IdentityRequiredError.message` → "휴대폰 인증이 필요합니다."). 회귀 테스트 통과.

- [x] `create_order`의 `identity_verified` 파라미터/`IdentityRequiredError` 가드
      **자체는 수정하지 않는다** — `user.verified`라는 호출부 계약은 그대로고,
      Task 0-1 옵션 B로 `User.verified` property의 내부 구현만
      `phone_verified_at is not None`으로 바뀌기 때문에 이 파일은 안 건드려도
      자동으로 새 로직을 따라간다. 다만 이 게이트가 뜻하는 바가 바뀌었으므로
      **주석만 갱신**: "본인인증이 완료된 사용자만" → "휴대폰 인증(Octomo)이
      완료된 사용자만".
- [x] `app/core/exceptions.py:120-123`의 `IdentityRequiredError.message`도
      `"본인인증이 필요합니다."` → `"휴대폰 인증이 필요합니다."`로 다듬을지
      선택(사용자 노출 문구라 프론트와 협의 후 결정, 필수 아님).

**TDD**: 기존 `tests/test_order_service.py`의 `create_order` 관련
`identity_verified=False → IdentityRequiredError` 테스트가 이미 있다면 **그대로
회귀 통과 확인만** — 새 테스트 불필요(게이트 로직 자체가 안 바뀌므로).

---

## Task 4 — CI/DI 모델/스키마/Protocol 완전 삭제 + Alembic 마이그레이션

**완료** → `app/auth/adapters/ports.py`, `app/auth/models.py`, `app/auth/__init__.py`,
`app/db/registry.py`, `app/user/models.py`(`Gender` 삭제, `ci`/`di`/`birth_date`/
`gender`/`identity_verified_at` 컬럼 삭제, `User.verified` → `phone_verified_at`
기준으로 재정의), `app/user/user_service.py::withdraw`. Alembic revision
`6105137b8e93_본인인증_ci_di_제거_octomo_전화인증으로_대체.py` 생성 및 로컬 DB에
`alembic upgrade head` 적용 완료. **결정 0-6 확인 결과**: 로컬 dev DB에 사용자
10명 전원 `identity_verified_at`이 채워져 있었으나(`ci`/`di`/`birth_date`는
전원 NULL) `phone_verified_at`은 7명이 NULL — 컬럼 드롭 전 `UPDATE users SET
phone_verified_at = identity_verified_at WHERE phone_verified_at IS NULL AND
identity_verified_at IS NOT NULL` 백필을 마이그레이션에 추가해 10명 전원의
인증 상태가 유지되도록 처리(마이그레이션 실행 후 재확인 완료).

- [x] `app/auth/adapters/ports.py`에서 `IdentityVerifyResult`, `IdentityVerifier` 삭제.
- [x] `app/auth/models.py`에서 `IdentityProvider`, `IdentityVerification` 삭제.
- [x] `app/auth/__init__.py`: `IdentityProvider`/`IdentityVerification` export 제거,
      `VerificationResult`는 `IdentityVerification` 전용이었는지 확인 후 같이
      정리(다른 곳에서 안 쓰면 같이 삭제).
- [x] `app/db/registry.py:10`에서 `IdentityVerification` import 제거
      (`SocialAccount` import는 유지).
- [x] `app/user/models.py` (Task 0-1 옵션 B + 0-2 확정 반영):
      - `Gender` enum 삭제
      - `User.ci`, `User.di`, `User.birth_date`, `User.gender`,
        **`User.identity_verified_at` 컬럼도 삭제**(옵션 B — 더 이상 별도 컬럼 아님)
      - `identity_verifications` relationship 삭제
      - `User.verified` property 재정의:
        ```python
        @property
        def verified(self) -> bool:
            """휴대폰(Octomo) 인증 통과 여부."""
            return self.phone_verified_at is not None
        ```
      - 클래스 docstring(41-49줄)의 "3단계 인증" 설명을 "2단계(휴대폰 인증 +
        카드사 확인)"로 갱신, `identity_verified_at` 언급 제거
- [x] `app/user/user_service.py::withdraw`(66-79줄)에서
      `user.birth_date = None`, `user.gender = None`, `user.ci = None`,
      `user.di = None` 라인 제거(더 이상 존재하지 않는 필드). `phone_verified_at`은
      탈퇴 시 초기화할지도 검토(기존 코드가 `identity_verified_at`을 따로
      초기화하지 않았던 것과 동일하게, `phone`/`phone_verified_at`도 탈퇴 시
      그대로 두거나 null 처리 — 기존 관례 확인 후 결정, 이 문서 범위 밖에 가까움).
- [x] **Alembic 신규 revision 생성** (과거 `e9bcd41ab78f_init_schema.py` 수정 금지
      원칙 — 새 revision으로 DROP):
      ```bash
      .venv/bin/alembic revision --autogenerate -m "본인인증 CI/DI 제거, Octomo 전화인증으로 대체"
      ```
      autogenerate가 감지해야 할 변경:
      - `DROP TABLE identity_verifications`
      - `ALTER TABLE users DROP COLUMN ci, di, birth_date, gender, identity_verified_at`
      - `downgrade()`도 autogenerate가 만들어주는 걸 그대로 두되, 실제 롤백
        시나리오가 필요한지 검토(운영 데이터 없으면 downgrade 검증 생략 가능).
      - **autogenerate 결과를 반드시 직접 읽고 확인** — 의도하지 않은 다른
        테이블 변경이 같이 잡히지 않았는지.
- [x] `.venv/bin/alembic upgrade head`로 로컬 DB에 적용 후 확인.

**TDD**: 스키마 변경 자체는 마이그레이션 적용 여부로 검증(별도 유닛 테스트 불필요).
다만 삭제된 심볼(`IdentityVerifier`, `Gender` 등)을 참조하던 기존 테스트가 있다면
`pytest` 전체 실행 시 `ImportError`로 바로 드러남 — Task 8에서 정리.

---

## Task 5 — `admin_members` 쪽 실제 변경 (Task 0-1 옵션 B 확정으로 인해 발생)

**완료** → `admin_members_repository.py`/`admin_members_schemas.py`/
`admin_members_service.py`. 다만 `identity_verified_at` 필드는 애초에
`phone_verified_at`과 별개 필드로 응답에 같이 있었기 때문에(문서 초안의 "필드명
교체" 예상과 달리) **그냥 그 필드를 삭제**하고 기존 `phone_verified_at` 필드는
그대로 뒀다 — 중복 필드가 생기지 않음. 라벨 문구(선택 항목)는 관리자 프론트를
안 건드려서 미반영.

옵션 A였다면 이 Task는 "확인"만 하면 됐는데, **옵션 B로 확정되면서 실제 코드
변경이 필요**해졌다 — `identity_verified_at` 컬럼 자체가 없어지기 때문.

**현재 코드**:
```python
# admin_members_repository.py:52
func.count(User.id).filter(User.identity_verified_at.is_not(None)).label("verified"),

# admin_members_schemas.py:44
identity_verified_at: datetime | None

# admin_members_service.py:51
identity_verified_at=row.user.identity_verified_at,
```

**목표 코드**:
```python
# admin_members_repository.py
func.count(User.id).filter(User.phone_verified_at.is_not(None)).label("verified"),

# admin_members_schemas.py
phone_verified_at: datetime | None  # identity_verified_at 필드명 자체를 교체

# admin_members_service.py
phone_verified_at=row.user.phone_verified_at,
```

- [x] `app/user/admin_members_repository.py:52` — `User.identity_verified_at` →
      `User.phone_verified_at`.
- [x] `app/user/admin_members_schemas.py:44` — 필드명을 `identity_verified_at` →
      `phone_verified_at`으로 변경(단순 값 교체가 아니라 **필드명 자체가
      바뀌므로 관리자 프론트가 이 응답을 쓰고 있다면 그쪽도 같이 수정 필요** —
      관리자 프론트 존재 여부/영향 범위 확인).
- [x] `app/user/admin_members_service.py:51` — 매핑도 동일하게 교체.
- [ ] (선택) 관리자 화면에 "본인인증 완료"라고 표시되던 라벨이 있다면
      "휴대폰 인증 완료"로 문구만 조정할지 프론트와 협의.

**TDD**: 기존에 이 필드를 검증하는 테스트(`tests/test_admin_members_*.py` 등,
있다면)가 `identity_verified_at` 대신 `phone_verified_at`을 참조하도록 이름/필드
전부 교체. 새 테스트 로직 자체는 불필요(필터 조건이 동일한 "not null" 체크라
동작은 안 바뀜) — 필드명 교체 회귀만 확인.

---

## Task 6 — `SmsSender`/`ConsoleSmsSender`/`OtpSender` 처리 여부 결정

**완료 — 옵션 (a) 삭제로 결정**: 요구사항정의서에 배송 알림 SMS 로드맵이
명시돼 있지만 아직 미착수 상태라, 지금 안 쓰는 코드는 안 남긴다는 원칙대로
`app/auth/adapters/console_sms.py` 파일 삭제, `SmsSender`/`OtpSender` Protocol
삭제(`ports.py`). 필요해지면 3줄짜리 인터페이스라 복구 비용 낮음.

**배경**: Octomo로 전화번호 인증을 완전히 대체하면, 서버가 SMS를 발신할 일이
**이 프로젝트 전체에서 없어질 수도 있다** — `SmsSender`는 지금 `UserService`의
전화번호 인증 용도로만 쓰이고 있었고(grep 결과 다른 용도 없음), 그 용도가
사라지기 때문.

- [x] **결정 필요**: 아래 중 선택.
      - **옵션 (a)**: `SmsSender` Protocol/`ConsoleSmsSender`/`.env.example`의
        `SMS_PROVIDER`/`SMS_API_KEY`/`SMS_SENDER` 전부 삭제 — 지금 안 쓰는
        코드는 안 남긴다는 원칙(YAGNI)에 부합.
      - **옵션 (b)**: 남겨둔다 — `docs/요구사항정의서.md`의 기술스택 표에
        "알림: NHN Cloud SMS / 알리고"가 이미 있어서, 배송 상태 변경 알림
        같은 **다른 용도의 transactional SMS**를 나중에 붙일 계획이 있다면
        미리 없앨 필요는 없음.
      - **권장**: 실제로 그런 알림 기능이 로드맵에 있는지 확인 후 결정.
        없거나 불확실하면 (a) — 나중에 필요해지면 그때 다시 만들면 됨(2~3줄짜리
        인터페이스라 복구 비용 낮음).
- [x] `OtpSender` Protocol은 Task 1에서 이미 삭제 대상으로 표시됨(중복 기재 방지 — 여기선 스킵).

**TDD**: 삭제 시 참조하는 곳이 없어야 함 — `pytest`/`mypy` 회귀로 확인.

---

## Task 7 — 문서/환경설정 정리

**완료** → `.env.example`, `.env`(실제 `OCTOMO_API_KEY` 값 저장, gitignore 대상),
`docs/요구사항정의서.md`(§2.1.1/§2.4/§3.2/데이터모델/기술스택 표 전부 갱신).

- [x] `.env.example`:
      ```diff
      - # 본인인증 (NICE / 토스 / KCB 중 택1)
      - IDENTITY_PROVIDER=toss
      + # Octomo 전화번호 인증
      + OCTOMO_API_KEY=
      ```
      (`IDENTITY_PROVIDER`는 애초에 `Settings`에 없어서 안 읽히던 죽은 값이었음 —
      삭제해도 아무 동작도 안 바뀜, 순수 청소)
- [x] Task 6에서 (a) 선택 시 `SMS_PROVIDER`/`SMS_API_KEY`/`SMS_SENDER`도 같이 제거.
- [x] `docs/요구사항정의서.md` §2.4(본인인증/신원 확인) 전체 갱신:
      - 인증 단계 표를 2단계로 축소(1차 Octomo 전화인증 = 2차 겸용 / 3차 카드사 확인)
      - "CI(Connecting Information)"/"DI" 관련 문단 삭제
      - 미성년자 차단 관련 문구 삭제(Task 0-2 옵션 a 기준) 또는 "폐기함, 사유:
        법적 의무 아니며 CI/DI 없이는 신뢰성 있게 구현 불가능"이라고 명시적으로
        남겨서 나중에 "왜 없지?"라는 질문이 안 나오게 함(권장).
      - §3.2(보안) "개인정보 암호화 저장(전화번호, 주소, **CI/DI**)"에서 CI/DI 삭제.
      - 기술스택 표의 "본인인증: 토스페이먼츠 또는 NICE" 행 → "Octomo(전화번호 인증)"로 교체.
- [x] `nicepay_migration.md`에 이 문서와의 관계를 한 줄 추가 — 결제 PG
      마이그레이션과 본인인증 교체는 **서로 독립적인 작업**이라 순서 무관하게
      아무 때나 진행 가능하다는 점 명시(혼동 방지).

---

## Task 8 — 테스트 전수 이관

**완료**

| 기존 | 처리 |
|---|---|
| `tests/test_user_service.py` (phone 관련) | Task 2 TDD 반영해서 재작성 완료 — CI/DI 관련 fixture(`birth_date`/`Gender`/`ci`/`di`)도 같이 정리 |
| `tests/test_user_phone_verification.py` | Octomo `_FakePhoneVerifier` 기반으로 전면 재작성 |
| `tests/test_octomo_adapter.py` | 신규 (Task 1 TDD), 11개 테스트, 커버리지 100% |
| `admin_members` 관련 테스트 | 원래부터 전용 테스트 파일이 없었음(사전 확인) — 신규 작성은 이번 마이그레이션 범위 밖으로 판단(트리비얼한 필드 삭제/rename) |

- [x] `.venv/bin/pytest -v` 전체 그린 — **434 passed**
- [x] `.venv/bin/ruff check app tests` 클린
- [x] `.venv/bin/mypy app` 클린 (119 source files, no issues)
- [x] 커버리지: 변경 핵심 파일(`app/auth/adapters/octomo.py`, `app/user/user_service.py`)
      100% 확인. `admin_members_*`는 원래 테스트가 없던 파일이라 80% 미달이지만,
      이번에 건드린 건 트리비얼한 1줄 rename/삭제뿐이라 범위 밖으로 판단(별도
      이슈로 분리 권장).

---

## 클라이언트(프론트엔드, `rekle` 레포) 변경 작업

> **레포 경로 주의**: 이 문서는 `rekle_backend` 레포의 `docs/`에 있지만, 이
> 섹션이 다루는 파일은 전부 **다른 레포** `/Volumes/A/web_projects/rekle`
> (Vue 3 + Pinia + Vue Router, `rekit` 패키지) 기준이다. 경로를 혼동하지 말 것.

### FE-0. 현재 코드 전수조사 (실제 코드 확인 결과)

| 파일 | 상태 | 처리 |
|---|---|---|
| `src/views/checkout/IdentityView.vue` | **완전 목업** — `requestOtp()`는 API 호출 없이 `otpSent=true`만 세팅, `submit()`은 `auth.user.verified = true`를 로컬에서 직접 세팅 후 `localStorage`에 저장. 백엔드를 전혀 호출하지 않음. 안내 문구에 "만 14세 미만은 가입 및 주문이 제한됩니다", "인증 제공: 토스페이먼츠" 등 CI/DI 시대 문구 포함(63-67, 118-122줄) | 실동작 연동으로 전면 재작성 (FE Task 2) |
| `src/views/my/ProfileView.vue` (47-89줄) | **완전 목업** — `sendPhoneCode()`는 API 호출 없이 `codeSent=true`만 세팅, `confirmPhoneCode()`는 코드 검증 없이 그냥 `auth.updateProfile({phone})` 호출 | 실동작 연동으로 재작성 (FE Task 3) |
| `src/api/users.ts` | `sendPhoneVerification`/`verifyPhone` 함수가 **아예 없음** — 백엔드 엔드포인트는 실재하지만 프론트가 호출한 적이 없음 | 신규 함수 추가 (FE Task 1) |
| `src/stores/auth.ts` | `User.phone`/`User.verified` 필드는 이미 백엔드 `UserResponse`와 매칭됨 | **무변경** |
| `src/views/auth/SignUpView.vue` | 회원가입은 **이메일 인증**을 씀(`sendEmailVerification`/`verifyEmailCode`, `verifiedToken`) — 전화번호/CI-DI와 무관 | **이 마이그레이션과 무관, 손대지 않음** |
| `src/components/checkout/CheckoutSteps.vue` | 1단계 라벨이 `"본인인증"`으로 하드코딩(8줄) | 문구 검토 (FE Task 4, 선택) |
| `src/_design/buyer/IdentityView.vue` 등 `_design/` 전체 | 라우터 주석(`router/index.ts:74`)에 "Do not import from there in real app code"로 명시된 **디자인 레퍼런스 전용** | **범위 밖 — 건드리지 않음** |

**핵심 요약**: 프론트의 "본인인증" 관련 화면 2곳(`checkout/IdentityView.vue`,
`my/ProfileView.vue`)이 전부 **API 연동 자체가 없는 순수 프로토타입**이었다.
백엔드와 마찬가지로 "실제 걸 갈아끼우는" 게 아니라 "처음으로 진짜 연동하는" 작업.

### 우선순위 요약 (FE)

| # | Task | 비고 |
|---|---|---|
| 0 | 설계 결정 확정 | 필수, 최우선 |
| 1 | `api/users.ts`에 실제 API 함수 추가 | 백엔드 Task 2-1 완료 후(응답 스키마 확정 필요) |
| 2 | `checkout/IdentityView.vue` 실연동 (QR 표시 플로우) | FE Task 1 선행 |
| 3 | `my/ProfileView.vue` 휴대폰 변경 실연동 | FE Task 1 선행, FE Task 2와 로직 공유 |
| 4 | `CheckoutSteps.vue` 라벨 검토 | 선택, 독립적 |
| 5 | 에러 코드 매핑 (`OTP_RATE_LIMITED`/`OTP_INVALID` 등) | FE Task 2·3와 병행 |
| 6 | 수동 QA 체크리스트 | 전체 완료 후 |

### FE Task 0 — 설계 결정

- [x] **결정 FE-0-1**: 컴포넌트로 추출하기로 확정 및 구현 완료.
      → `src/components/auth/PhoneVerifyForm.vue` — phone 입력, QR 발급/재발급,
      5분 TTL 카운트다운, 60초 재발급 쿨다운, `verified` 이벤트까지 전부 캡슐화.
      `checkout/IdentityView.vue`(FE Task 2)와 `my/ProfileView.vue`(FE Task 3)가
      이 컴포넌트를 그대로 재사용하도록 반영 완료.
- [x] **결정 FE-0-2**: 구현은 카운트다운 표시 + **수동 재발급**으로 처리함(당초
      "권장"이었던 자동 재호출 대신) — 만료되면 QR이 흐려지고 "인증하기" 버튼이
      비활성화되며 "재발급" 버튼을 눌러야 새 QR을 받는다. 자동 재호출 대신 수동을
      택한 이유: 사용자가 모르는 사이에 API 가 호출되는 걸 피하고, 60초
      재발급 쿨다운과 자연스럽게 맞물리게 하기 위함.
      → `src/components/auth/PhoneVerifyForm.vue`(`qrExpired`, `remainingLabel`)
      **재확인 필요**: 자동 재호출을 원하시면 알려주세요 — 지금은 수동입니다.
- [x] **결정 FE-0-3**: 권장안대로 반영 완료 — "만 14세 미만 제한" 문구 삭제,
      "인증 제공: 토스페이먼츠" → "인증 제공: Octomo", 암호화 저장 문구는 유지.
      `checkout/IdentityView.vue` 라벨도 "본인인증" → "휴대폰 인증"으로 통일
      (`CheckoutSteps.vue`, `ProfileView.vue`의 "본인인증 상태" 섹션도 함께 변경).
- [ ] **결정 FE-0-4**(여전히 미결정 — 사용자 판단 필요): 테스트 프레임워크
      (vitest 등) 도입 여부. 이번엔 도입하지 않고 `type-check`(vue-tsc)와
      `lint`(oxlint/eslint)만으로 검증했음(전부 통과 확인) — 실제 QR 스캔→SMS
      전송→인증 흐름은 자동화 테스트가 없어 **수동 QA가 필수**(FE Task 6 체크리스트).

### FE Task 1 — `api/users.ts`에 실제 API 함수 추가

**현재** (`src/api/users.ts`) — phone 인증 관련 함수 없음(`getMe`/`updateProfile`/
`changePassword`/`withdrawMe`만 존재).

**목표 코드** (`src/api/auth.ts`의 `sendEmailVerification`/`verifyEmailCode`와
동일한 `apiRequest` 패턴 재사용):
```typescript
export interface PhoneSendVerificationResponse {
  qrCode: string // "data:image/png;base64,..."
}

export function sendPhoneVerification(phone: string): Promise<PhoneSendVerificationResponse> {
  return apiRequest<PhoneSendVerificationResponse>('/users/me/phone/send-verification', {
    method: 'POST',
    body: { phone },
    auth: true,
  })
}

export function verifyPhone(phone: string): Promise<void> {
  return apiRequest<void>('/users/me/phone/verify', {
    method: 'POST',
    body: { phone },
    auth: true,
  })
}
```
**FE Task 1 완료** → `src/api/users.ts`

- [x] 위 두 함수 + `PhoneSendVerificationResponse` 타입 추가.
- [x] **`verifyPhone`은 `code` 파라미터를 받지 않는다** — 백엔드 Task 2에서
      QR 방식으로 확정하면서 `PhoneVerifyRequest`가 `phone`만 받도록 바뀌었기
      때문(백엔드 문서 참고). 기존 프론트 목업 코드(`otp`/`phoneEdit.code`
      상태)가 "사용자가 코드를 입력하는" 걸 전제로 하고 있었는데, QR 방식에서는
      **입력창 자체가 필요 없다** — FE Task 2/3에서 그 입력 필드를 통째로 제거.
- [x] `verifyPhone` 성공 시 백엔드가 `user.phone`/`phone_verified_at`/
      `identity_verified_at`을 전부 갱신하므로, 프론트는 그 다음
      **`auth.fetchMe()`를 호출해서 최신 상태를 다시 받아오면 된다** — 별도로
      `auth.updateProfile({phone})`을 또 호출할 필요 없음(중복 호출, FE Task 3에서
      정리 완료).

### FE Task 2 — `checkout/IdentityView.vue` 실연동 (QR 플로우)

**현재 코드** (38-52줄) — 완전 목업:
```typescript
function requestOtp() {
  if (!phoneValid.value) return
  otpSent.value = true
}

function submit(e: Event) {
  e.preventDefault()
  if (!canSubmit.value || !auth.user) return
  // mock — in production, PG verifies and returns identity claim
  auth.user.verified = true
  auth.user.phone = phone.value
  localStorage.setItem('rekit.auth.user.v3', JSON.stringify(auth.user))
  router.replace('/checkout/order')
}
```

**목표 코드**:
```typescript
import { sendPhoneVerification, verifyPhone } from '@/api/users'
import { ApiError } from '@/api/client'

const qrCode = ref('')
const requesting = ref(false)
const verifying = ref(false)
const errorMessage = ref('')
const expiresAt = ref(0) // epoch ms — QR 5분 TTL 카운트다운용

async function requestQr() {
  if (!phoneValid.value || requesting.value) return
  requesting.value = true
  errorMessage.value = ''
  try {
    const res = await sendPhoneVerification(phone.value)
    qrCode.value = res.qrCode
    otpSent.value = true
    expiresAt.value = Date.now() + 5 * 60 * 1000
  } catch (err) {
    if (err instanceof ApiError && err.code === 'OTP_RATE_LIMITED') {
      errorMessage.value = '잠시 후 다시 시도해 주세요. (60초)'
    } else {
      errorMessage.value = err instanceof Error ? err.message : 'QR 발급에 실패했어요.'
    }
  } finally {
    requesting.value = false
  }
}

async function submit(e: Event) {
  e.preventDefault()
  if (!otpSent.value || verifying.value || !auth.user) return
  verifying.value = true
  errorMessage.value = ''
  try {
    await verifyPhone(phone.value)
    await auth.fetchMe() // user.verified/phone/phone_verified_at 최신화
    router.replace('/checkout/order')
  } catch (err) {
    if (err instanceof ApiError && err.code === 'OTP_INVALID') {
      errorMessage.value = '아직 문자가 도착하지 않았어요. 전송 후 다시 시도해 주세요.'
    } else {
      errorMessage.value = err instanceof Error ? err.message : '인증 확인에 실패했어요.'
    }
  } finally {
    verifying.value = false
  }
}
```
**FE Task 2 완료** — 단, FE-0-1에서 컴포넌트 추출로 결정되면서 위 목표 코드
스니펫(IdentityView.vue 안에 직접 로직을 넣는 방식)은 그대로 쓰지 않고,
**`PhoneVerifyForm.vue`(FE Task 1) 하나를 그대로 끼워넣는 방식으로 구현**했다
→ `src/views/checkout/IdentityView.vue`. 실제 스크립트는 `handleVerified()`
하나만 남고(내부에서 `auth.fetchMe()` + `router.replace('/checkout/order')`),
`otp`/`requestQr`/`submit` 등 이 문서에 스케치했던 로컬 상태·함수는 전부
컴포넌트 안으로 들어갔다.

- [x] `otp`(입력값) 관련 state/템플릿 전부 제거 — QR 방식이라 사용자가 코드를
      직접 입력할 필요가 없다.
- [x] 템플릿의 "인증번호" 입력 필드를 `<PhoneVerifyForm @verified="handleVerified" />`
      로 교체(QR 표시는 컴포넌트 내부 책임).
- [x] 안내 문구(FE-0-3 결정 반영) — "만 14세 미만 제한" 삭제, "인증 제공: Octomo"로 교체.
- [x] 히어로 타이틀도 "본인인증" → "휴대폰 인증"으로 통일.
- [x] 더 이상 쓰이지 않는 `.form`/`.field*` CSS 전부 정리(컴포넌트로 이동).

**참고**: 이 화면은 `onBeforeMount`에서 `auth.user.verified`면 바로
`/checkout/order`로 리다이렉트하는 게이트 로직을 그대로 유지 — 이 부분은
백엔드 `identity_verified`/`user.verified` 시맨틱이 안 바뀌므로 무변경.

### FE Task 3 — `my/ProfileView.vue` 휴대폰 변경 실연동

**현재 코드** (67-89줄) — 완전 목업, 코드 검증 없이 바로 `updateProfile` 호출.

**목표**: FE Task 2와 동일한 `sendPhoneVerification`/`verifyPhone` 재사용.
```typescript
async function sendPhoneCode() {
  if (!newPhoneValid.value || phoneEdit.sending) return
  phoneEdit.sending = true
  phoneEdit.error = ''
  try {
    const res = await sendPhoneVerification(phoneEdit.newPhone.trim())
    phoneEdit.qrCode = res.qrCode
    phoneEdit.codeSent = true
  } catch (err) {
    phoneEdit.error = err instanceof ApiError && err.code === 'OTP_RATE_LIMITED'
      ? '잠시 후 다시 시도해 주세요.'
      : '인증 QR 발급에 실패했어요.'
  } finally {
    phoneEdit.sending = false
  }
}

async function confirmPhoneCode() {
  phoneEdit.verifying = true
  phoneEdit.error = ''
  try {
    await verifyPhone(phoneEdit.newPhone.trim())
    await auth.fetchMe() // verifyPhone 이 이미 user.phone 을 갱신하므로 재조회만
    phoneEdit.open = false
  } catch {
    phoneEdit.error = '휴대폰 인증에 실패했어요. 문자 전송 여부를 확인해 주세요.'
  } finally {
    phoneEdit.verifying = false
  }
}
```
**FE Task 3 완료** — FE Task 2와 동일하게, 위 스니펫 대신 **`PhoneVerifyForm.vue`
재사용**으로 구현 → `src/views/my/ProfileView.vue`. `phoneEdit`를 코드/QR/발송중
상태까지 다 들고 있던 `reactive` 객체에서 `phoneEditOpen`(열림/닫힘 하나)으로
단순화하고, 완료 콜백 `handlePhoneVerified()`에서 `auth.fetchMe()` 후 패널을 닫는다.

- [x] `phoneEdit.code`(사용자가 입력하던 6자리) 등 상태 전부 제거.
- [x] 템플릿의 인증번호 입력 필드를 `<PhoneVerifyForm :initial-phone="..." @verified="..." />`로 교체.
- [x] **`await auth.updateProfile({ phone })` 호출 제거** — 기존 코드가 이걸
      호출했는데, `verifyPhone`이 이미 백엔드에서 `user.phone`을 갱신하므로
      **중복 호출이자 인증 우회 경로였음**(전화번호만 바꾸고 인증은 건너뛸 수
      있었던 구멍) — 이번에 없앰.

### FE Task 4 — `CheckoutSteps.vue` 라벨 검토 (선택)

- [x] 1단계 라벨을 `"본인인증"` → `"휴대폰 인증"`으로 변경 완료
      → `src/components/checkout/CheckoutSteps.vue`. 백엔드 Task 3의
      `IdentityRequiredError` 메시지 변경 여부와 통일성 맞추려면, 백엔드에서도
      그 문구를 바꾸는 쪽으로 진행할 것(아직 백엔드는 미착수).

### FE Task 5 — 에러 코드 매핑 확인

- [x] `app/core/exceptions.py` 확인 결과: `OtpRateLimitedError.code = "OTP_RATE_LIMITED"`
      (429), `OtpInvalidError.code = "OTP_INVALID"`(422) — 두 값 다
      `PhoneVerifyForm.vue`에 정확히 반영됨. **단, 이 두 예외는 지금
      "본인인증 CI/DI 폐지" 이전 코드에 이미 있던 것**(`user_service.py`의
      기존 SMS OTP 로직용) — 백엔드 Task 2에서 `send_phone_verification`/
      `verify_phone`을 Octomo 로 바꿀 때도 **같은 예외 클래스를 그대로
      재사용**해야 프론트가 지금 짠 에러 분기가 그대로 유효하다(백엔드 구현
      시 꼭 확인).

### FE Task 6 — 수동 QA 체크리스트 (테스트 프레임워크 부재 — FE-0-4 참고)

- [x] **정적 검증 완료**: `npx vue-tsc --build`(타입체크), `npx oxlint`,
      `npx eslint` 전부 변경 파일 기준 클린 확인. **단, 이건 컴파일/린트
      레벨 검증일 뿐 — 아래 실제 QR 스캔/SMS 흐름은 백엔드 Task 1~2 구현 +
      Octomo API 키가 있어야 진짜로 돌려볼 수 있음(아직 미검증).**
- [ ] 정상 흐름: 전화번호 입력 → QR 발급 → (테스트폰으로) QR 스캔 → SMS 전송 →
      "인증하기" → `verified=true` 확인 → `/checkout/order`로 이동
- [ ] 60초 이내 재발급 시도 → rate-limit 에러 메시지 노출 확인
- [ ] 5분 경과 후 오래된 QR로 SMS 전송 → "인증하기" → 실패 메시지 확인(FE-0-2
      결정에 따라 자동 재발급 여부도 같이 확인)
- [ ] SMS 전송 없이 바로 "인증하기" 클릭 → 실패 메시지 확인
- [ ] `ProfileView.vue`에서 휴대폰 변경 시 동일 플로우 동작 확인, 성공 후
      `auth.user.phone`이 새 번호로 반영되는지 확인
- [ ] 이미 `verified=true`인 사용자가 `/checkout/identity`에 직접 진입 시
      자동으로 `/checkout/order`로 리다이렉트되는지 확인(기존 게이트 로직 무변경 검증)

---

## 세션 재개 체크리스트

**백엔드(`rekle_backend`)**:
1. Task 0의 결정사항(특히 0-1, 0-2)이 확정됐는지 먼저 확인 — 나머지 Task 전부
   이 결정을 전제로 쓰여 있음.
2. `git status`/`git log`로 실제 코드 상태 우선 신뢰.
3. Octomo API 키가 아직 없다면 Task 1은 스펙 구현까지만 하고, 실제 `/message/exists`
   호출 검증은 키 발급 후로 미룰 것 — 목(mock) 응답으로 단위 테스트는 먼저 작성 가능.
4. `alembic revision --autogenerate` 결과는 **반드시 직접 읽고** 의도한 변경만
   포함됐는지 확인 후 커밋(자동생성 결과를 그냥 믿지 말 것).
5. CLAUDE.md 게이트(`pytest`/`ruff check app tests`/`mypy app`) 통과 없이 다음
   Task로 넘어가지 않는다.

**프론트엔드(`rekle`, 별도 레포 — 작업 디렉터리 착각 주의)**:
6. FE Task는 **백엔드 Task 2-1(응답 스키마: `PhoneSendResponse.qrCode`,
   `PhoneVerifyRequest`에서 `code` 제거)이 확정된 뒤** 시작하는 게 안전 —
   API 계약이 이 문서 안에서 두 번 조정됐으므로(코드 응답 → QR 응답, code
   있음 → code 없음) 백엔드 실제 구현이 이 문서 최신 스니펫과 일치하는지
   먼저 확인.
7. FE-0-1(공용 컴포넌트 추출 여부)을 먼저 정하고 FE Task 2/3를 순서대로.

**공통**:
8. 커밋/푸시는 사용자가 명시적으로 요청할 때만 — 두 레포 각각에 대해 별도 판단.
