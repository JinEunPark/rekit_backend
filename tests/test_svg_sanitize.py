"""SVG 안전성 검사 단위 테스트.

카테고리 이미지로 SVG 업로드를 허용하면서, <img> 태그가 아닌 직접 네비게이션으로
열렸을 때 스크립트가 실행되는 걸 막기 위한 최소 allowlist 검사.
완전한 sanitize(제거 후 재구성)가 아니라 "위험 요소가 있으면 통째로 거부"하는 fail-closed 방식.
"""

from __future__ import annotations

import pytest

from app.common.uploads.svg_sanitize import is_svg_safe


def test_plain_svg_is_safe() -> None:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><circle cx="5" cy="5" r="4" /></svg>'
    assert is_svg_safe(svg) is True


def test_svg_with_script_tag_is_unsafe() -> None:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    assert is_svg_safe(svg) is False


def test_svg_with_on_event_attribute_is_unsafe() -> None:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><circle /></svg>'
    assert is_svg_safe(svg) is False


def test_svg_with_javascript_href_is_unsafe() -> None:
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
        b'<a xlink:href="javascript:alert(1)"><circle /></a></svg>'
    )
    assert is_svg_safe(svg) is False


def test_svg_with_foreign_object_is_unsafe() -> None:
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg">'
        b"<foreignObject><div xmlns='http://www.w3.org/1999/xhtml'>x</div></foreignObject>"
        b"</svg>"
    )
    assert is_svg_safe(svg) is False


def test_svg_with_iframe_is_unsafe() -> None:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><iframe src="https://evil.example"></iframe></svg>'
    assert is_svg_safe(svg) is False


def test_malformed_xml_is_unsafe() -> None:
    """파싱 자체가 안 되면 안전하다고 단정할 수 없으니 거부 (fail-closed)."""
    assert is_svg_safe(b"<svg><unclosed></svg>") is False


def test_not_svg_root_tag_is_unsafe() -> None:
    """루트 태그가 svg 가 아니면(= content-type 과 실제 내용 불일치) 거부."""
    assert is_svg_safe(b"<html><body>x</body></html>") is False


@pytest.mark.parametrize("tag", ["animate", "set", "animateTransform", "animateMotion"])
def test_smil_animation_tags_are_unsafe(tag: str) -> None:
    """SMIL 은 <a> 의 href 를 런타임에 javascript: 로 갈아끼울 수 있다.

    속성 이름이 href 가 아니라 attributeName 이라 URL 속성 검사로는 안 잡히므로
    태그 자체를 거부한다.
    """
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg"><a>'
        b"<" + tag.encode() + b' attributeName="href" to="javascript:alert(1)"/>'
        b"<text>click</text></a></svg>"
    )
    assert is_svg_safe(svg) is False


@pytest.mark.parametrize(
    "entity",
    ["&#10;", "&#9;", "&#13;", "&#0;"],
    ids=["newline", "tab", "carriage-return", "null"],
)
def test_control_chars_inside_scheme_are_unsafe(entity: str) -> None:
    """브라우저는 스킴 중간의 제어문자를 무시하고 실행한다 — 정규화 후 검사해야 잡힌다."""
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg"><a href="java'
        + entity.encode()
        + b'script:alert(1)"><text>x</text></a></svg>'
    )
    assert is_svg_safe(svg) is False


def test_ordinary_https_link_stays_safe() -> None:
    """정상 링크까지 막으면 과잉 — https 링크는 통과해야 한다."""
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg">'
        b'<a href="https://rekit.co.kr"><text>link</text></a></svg>'
    )
    assert is_svg_safe(svg) is True
