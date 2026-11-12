"""scripts/generate_product_thumbnails.py 의 순수 함수 단위 테스트 (스토리지·DB 불필요)."""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path
from types import ModuleType

import pytest

PIL = pytest.importorskip("PIL")  # scripts extra — 없으면 건너뜀
from PIL import Image  # noqa: E402


def _load() -> ModuleType:
    path = Path(__file__).parent.parent / "scripts" / "generate_product_thumbnails.py"
    spec = importlib.util.spec_from_file_location("generate_product_thumbnails", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = _load()


def _jpeg(w: int, h: int, orientation: int | None = None) -> bytes:
    buf = io.BytesIO()
    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation
    Image.new("RGB", (w, h), (120, 160, 140)).save(buf, "JPEG", exif=exif.tobytes())
    return buf.getvalue()


def test_thumb_key_for_rejects_key_outside_products() -> None:
    with pytest.raises(ValueError):
        gen.thumb_key_for("categories/a.png")


def test_thumb_key_for_appends_suffix_and_webp_ext() -> None:
    assert gen.thumb_key_for("products/abc.jpg") == "products/abc_thumb.webp"


def test_key_from_url_rejects_foreign_url() -> None:
    with pytest.raises(ValueError):
        gen.key_from_url("https://evil.example.com/x/products/a.jpg", "https://cdn/rekle-images")


def test_key_from_url_strips_public_base() -> None:
    url = "https://cdn/rekle-images/products/abc.jpg"

    assert gen.key_from_url(url, "https://cdn/rekle-images") == "products/abc.jpg"


def test_make_thumbnail_limits_long_edge_and_encodes_webp() -> None:
    out = Image.open(io.BytesIO(gen.make_thumbnail(_jpeg(1600, 1200))))

    assert out.format == "WEBP"
    assert out.size == (480, 360)


def test_make_thumbnail_applies_exif_rotation() -> None:
    """orientation=6 (세로로 찍은 사진) → 픽셀이 세로로 회전된 썸네일."""
    out = Image.open(io.BytesIO(gen.make_thumbnail(_jpeg(1600, 1200, orientation=6))))

    assert out.size == (360, 480)


def test_make_thumbnail_does_not_upscale_small_image() -> None:
    out = Image.open(io.BytesIO(gen.make_thumbnail(_jpeg(300, 200))))

    assert out.size == (300, 200)


def test_update_sql_escapes_quote_and_guards_existing_thumb() -> None:
    sql = gen.update_sql(7, "https://cdn/products/a'b_thumb.webp")

    assert sql == (
        "UPDATE product_images SET thumb_url = 'https://cdn/products/a''b_thumb.webp' "
        "WHERE id = 7 AND thumb_url IS NULL;"
    )
