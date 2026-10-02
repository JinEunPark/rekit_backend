"""SVG 안전성 검사 — 카테고리 이미지 업로드로 허용한 SVG 가 스크립트를 품지 않는지 확인.

<img> 태그로만 노출한다면 브라우저가 SVG 내 스크립트를 실행하지 않지만, 누군가 업로드된
SVG URL을 새 탭에서 직접 열면(top-level navigation) 스토리지 도메인 컨텍스트에서 그대로
실행된다. 그 경로를 막기 위해 confirm 시점에 1회 검사 — 위험 요소가 하나라도 있으면
"정리해서 통과"가 아니라 통째로 거부(fail-closed)한다. 부분 제거는 우회 여지가 남는다.
"""

from __future__ import annotations

from xml.etree.ElementTree import Element

import defusedxml.ElementTree as safe_ET

_DANGEROUS_TAGS = {
    "script",
    "foreignobject",
    "iframe",
    "embed",
    "object",
    "use",
    # SMIL — <animate attributeName="href" to="javascript:…"/> 로 멀쩡한 <a> 의 href 를
    # 런타임에 갈아끼울 수 있다. 속성 이름이 href 가 아니라 attributeName 이라
    # 아래 _attr_is_dangerous 로는 안 걸리므로 태그 자체를 막는다.
    "animate",
    "set",
    "animatetransform",
    "animatemotion",
    "handler",
}

_URL_ATTRS = {"href", "src"}
_DANGEROUS_SCHEMES = ("javascript:", "data:text/html")


def _local_name(tag: str) -> str:
    """'{namespace}tag' 형태에서 네임스페이스를 떼고 tag 만 반환."""
    return tag.rsplit("}", 1)[-1]


def _normalize_url(value: str) -> str:
    """브라우저가 URL 스킴을 해석하는 방식에 맞춰 정규화.

    브라우저는 스킴 중간의 공백·제어문자를 무시하므로 `java&#10;script:` 도 실행된다.
    단순 strip 만으로는 그 우회를 못 잡아서, 공백·제어문자를 전부 제거한 뒤 비교한다.
    """
    return "".join(
        ch for ch in value if not ch.isspace() and 0x20 <= ord(ch) != 0x7F
    ).lower()


def _attr_is_dangerous(name: str, value: str) -> bool:
    local = _local_name(name).lower()
    is_event_handler = local.startswith("on")  # onload, onclick 등
    is_script_url = local in _URL_ATTRS and _normalize_url(value).startswith(
        _DANGEROUS_SCHEMES
    )
    return is_event_handler or is_script_url


def _element_is_dangerous(el: Element) -> bool:
    if _local_name(el.tag).lower() in _DANGEROUS_TAGS:
        return True
    return any(_attr_is_dangerous(name, value) for name, value in el.attrib.items())


def is_svg_safe(data: bytes) -> bool:
    """스크립트/이벤트 핸들러/외부 임베드가 없는 순수 SVG 인지 검사.

    파싱 실패나 루트가 svg 가 아닌 경우도 안전하다고 단정할 수 없으므로 거부한다.
    """
    try:
        root = safe_ET.fromstring(data)
    except Exception:  # 파싱 실패는 전부 "안전하지 않음"으로 취급 (fail-closed)
        return False

    if _local_name(root.tag).lower() != "svg":
        return False

    return not any(_element_is_dangerous(el) for el in root.iter())
