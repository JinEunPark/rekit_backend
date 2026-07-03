"""이메일 HTML 템플릿 모음.

table 기반 레이아웃 — Gmail, Apple Mail, Outlook 호환.
rekit 디자인 시스템: #FAFAFA 배경, #4FA88B 틸-그린 액센트, Pretendard 폴백.
"""

_VERIFICATION_HTML = """\
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="X-UA-Compatible" content="IE=edge">
<title>rekit 이메일 인증</title>
</head>
<body style="margin:0;padding:0;background:#FAFAFA;
             font-family:-apple-system,'Apple SD Gothic Neo','Noto Sans KR',system-ui,sans-serif;">

<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#FAFAFA;">
<tr><td align="center" style="padding:40px 16px 56px;">

  <!-- Logo -->
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;">
  <tr><td align="center" style="padding-bottom:28px;">
    <table cellpadding="0" cellspacing="0" border="0">
    <tr>
      <td valign="middle" style="padding-right:9px;">
        <svg width="25" height="25" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M5 19c0-8 6-14 16-14 0 10-6 16-14 16-1.5 0-2-1-2-2z"
                stroke="#4FA88B" stroke-width="1.8" fill="#E5F2EC"/>
          <path d="M5 19c3-3 6-6 11-11"
                stroke="#4FA88B" stroke-width="1.8" stroke-linecap="round"/>
        </svg>
      </td>
      <td valign="middle">
        <span style="font-size:21px;font-weight:800;letter-spacing:-0.04em;color:#1A1A17;">rekit</span>
      </td>
    </tr>
    </table>
  </td></tr>
  </table>

  <!-- Card -->
  <table width="100%" cellpadding="0" cellspacing="0" border="0"
         style="max-width:560px;background:#ffffff;border:1px solid #E8E8EA;border-radius:14px;overflow:hidden;">

    <!-- Accent bar -->
    <tr><td height="4" style="background:#4FA88B;font-size:0;line-height:0;">&nbsp;</td></tr>

    <!-- Body -->
    <tr><td style="padding:44px 48px 40px;">

      <p style="font-size:22px;font-weight:700;color:#1A1A17;letter-spacing:-0.02em;
                line-height:1.3;margin:0 0 14px;">이메일 인증 코드</p>

      <p style="font-size:15px;color:#5C5C55;line-height:1.7;margin:0 0 32px;">
        rekit 회원가입을 위한 인증 코드입니다.<br>
        아래 6자리 코드를 인증 화면에 입력해 주세요.
      </p>

      <!-- Code box -->
      <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:12px;">
      <tr><td align="center"
              style="background:#E5F2EC;border-radius:10px;padding:28px 24px;">
        <span style="font-family:'Courier New',Courier,monospace;
                     font-size:44px;font-weight:700;letter-spacing:14px;
                     color:#2D7A60;text-indent:14px;display:inline-block;">
          {code}
        </span>
      </td></tr>
      </table>

      <p style="font-size:13px;color:#8E8E85;text-align:center;margin:0 0 36px;">
        이 코드는 <strong style="color:#4FA88B;font-weight:600;">10분간</strong> 유효합니다.
      </p>

      <!-- Divider -->
      <table width="100%" cellpadding="0" cellspacing="0" border="0">
      <tr><td height="1" style="background:#E8E8EA;font-size:0;line-height:0;">&nbsp;</td></tr>
      </table>

      <p style="font-size:13px;color:#8E8E85;margin:24px 0 0;line-height:1.7;">
        본인이 요청하지 않은 메일이라면 무시하셔도 됩니다.<br>
        rekit은 인증 코드를 유선으로 요청하지 않습니다.
      </p>

    </td></tr>

    <!-- Footer -->
    <tr><td style="padding:20px 48px 24px;background:#F4F4F5;border-top:1px solid #E8E8EA;">
      <p style="font-size:12px;color:#B5B5AB;line-height:1.7;margin:0;">
        이 메일은 발송 전용입니다. 문의는
        <a href="mailto:help@rekit.kr"
           style="color:#4FA88B;text-decoration:none;">help@rekit.kr</a>로 연락해 주세요.<br>
        &copy; 2025 rekit. 폐업 가전 직거래 플랫폼.
      </p>
    </td></tr>

  </table>

</td></tr>
</table>
</body>
</html>
"""


def render_verification_email(code: str) -> str:
    """6자리 인증 코드를 삽입한 HTML 이메일 문자열을 반환한다."""
    return _VERIFICATION_HTML.format(code=code)


# ── 문의 접수 확인 (고객용) ──────────────────────────────────────────

_CONTACT_CONFIRM_HTML = """\
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>rekit 문의 접수 확인</title>
</head>
<body style="margin:0;padding:0;background:#FAFAFA;
             font-family:-apple-system,'Apple SD Gothic Neo','Noto Sans KR',system-ui,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#FAFAFA;">
<tr><td align="center" style="padding:40px 16px 56px;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;background:#ffffff;border:1px solid #E8E8EA;border-radius:14px;overflow:hidden;">
    <tr><td height="4" style="background:#4FA88B;font-size:0;line-height:0;">&nbsp;</td></tr>
    <tr><td style="padding:44px 48px 40px;">
      <p style="font-size:22px;font-weight:700;color:#1A1A17;letter-spacing:-0.02em;margin:0 0 14px;">문의가 접수되었습니다</p>
      <p style="font-size:15px;color:#5C5C55;line-height:1.7;margin:0 0 24px;">
        안녕하세요, <strong>{name}</strong>님.<br>
        아래 문의가 정상적으로 접수되었습니다.<br>
        영업일 기준 1~2일 내에 답변드리겠습니다.
      </p>
      <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#F4F4F5;border-radius:10px;padding:20px 24px;margin-bottom:32px;">
      <tr><td>
        <p style="font-size:13px;color:#8E8E85;margin:0 0 6px;">문의 제목</p>
        <p style="font-size:15px;color:#1A1A17;font-weight:600;margin:0;">{title}</p>
      </td></tr>
      </table>
      <table width="100%" cellpadding="0" cellspacing="0" border="0">
      <tr><td height="1" style="background:#E8E8EA;font-size:0;line-height:0;">&nbsp;</td></tr>
      </table>
      <p style="font-size:13px;color:#8E8E85;margin:24px 0 0;line-height:1.7;">
        본인이 요청하지 않은 메일이라면 무시하셔도 됩니다.
      </p>
    </td></tr>
    <tr><td style="padding:20px 48px 24px;background:#F4F4F5;border-top:1px solid #E8E8EA;">
      <p style="font-size:12px;color:#B5B5AB;line-height:1.7;margin:0;">
        &copy; 2025 rekit. 폐업 가전 직거래 플랫폼.
      </p>
    </td></tr>
  </table>
</td></tr>
</table>
</body>
</html>
"""

# ── 문의 알림 (관리자용) ─────────────────────────────────────────────

_CONTACT_NOTIFY_HTML = """\
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>rekit 새 문의 알림</title>
</head>
<body style="margin:0;padding:0;background:#FAFAFA;
             font-family:-apple-system,'Apple SD Gothic Neo','Noto Sans KR',system-ui,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#FAFAFA;">
<tr><td align="center" style="padding:40px 16px 56px;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;background:#ffffff;border:1px solid #E8E8EA;border-radius:14px;overflow:hidden;">
    <tr><td height="4" style="background:#E87A4F;font-size:0;line-height:0;">&nbsp;</td></tr>
    <tr><td style="padding:44px 48px 40px;">
      <p style="font-size:22px;font-weight:700;color:#1A1A17;letter-spacing:-0.02em;margin:0 0 24px;">[관리자] 새 문의가 접수되었습니다</p>
      <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#F4F4F5;border-radius:10px;padding:20px 24px;margin-bottom:24px;">
      <tr><td>
        <p style="font-size:13px;color:#8E8E85;margin:0 0 4px;">이름</p>
        <p style="font-size:14px;color:#1A1A17;margin:0 0 14px;">{name}</p>
        <p style="font-size:13px;color:#8E8E85;margin:0 0 4px;">이메일</p>
        <p style="font-size:14px;color:#1A1A17;margin:0 0 14px;">{email}</p>
        <p style="font-size:13px;color:#8E8E85;margin:0 0 4px;">연락처</p>
        <p style="font-size:14px;color:#1A1A17;margin:0 0 14px;">{phone}</p>
        <p style="font-size:13px;color:#8E8E85;margin:0 0 4px;">제목</p>
        <p style="font-size:14px;color:#1A1A17;font-weight:600;margin:0 0 14px;">{title}</p>
        <p style="font-size:13px;color:#8E8E85;margin:0 0 4px;">내용</p>
        <p style="font-size:14px;color:#1A1A17;white-space:pre-wrap;margin:0;">{content}</p>
      </td></tr>
      </table>
    </td></tr>
  </table>
</td></tr>
</table>
</body>
</html>
"""


def render_contact_confirm_email(*, name: str, title: str) -> str:
    """문의 접수 확인 이메일 (고객 수신용)."""
    return _CONTACT_CONFIRM_HTML.format(name=name, title=title)


def render_contact_notify_email(
    *, name: str, email: str, phone: str | None, title: str, content: str
) -> str:
    """문의 알림 이메일 (관리자 수신용)."""
    return _CONTACT_NOTIFY_HTML.format(
        name=name,
        email=email,
        phone=phone or "미입력",
        title=title,
        content=content,
    )
