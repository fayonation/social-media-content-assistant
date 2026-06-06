"""Overlay: composites a headline (RTL-aware) and logo onto a base image.

Arabic is never rendered by the image model. Here we shape it correctly with
arabic-reshaper + python-bidi and draw it with a bundled Arabic font.
"""

import os

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

from config import ARABIC_FONT, LATIN_FONT, MEDIA_DIR, new_media_path, web_to_fs


def _slug_from_web(web_path: str) -> str:
    parts = web_path.strip("/").split("/")
    return parts[1] if len(parts) >= 3 and parts[0] == "media" else "brand"


def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(path, size)
    for name in ("Bold", "SemiBold", "Medium", "Regular"):
        try:
            font.set_variation_by_name(name)
            break
        except (OSError, AttributeError, ValueError):
            continue
    return font


def _shape(text: str, rtl: bool) -> str:
    if not rtl:
        return text
    return get_display(arabic_reshaper.reshape(text))


def _wrap(draw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def apply_overlay(base_web_path: str, headline: str, logo_web_path: str | None, rtl: bool) -> str:
    base = Image.open(web_to_fs(base_web_path)).convert("RGBA")
    W, H = base.size
    draw = ImageDraw.Draw(base)

    if headline:
        font = _load_font(ARABIC_FONT if rtl else LATIN_FONT, max(W // 14, 28))
        shaped = _shape(headline, rtl)
        lines = _wrap(draw, shaped, font, int(W * 0.86))
        ascent, descent = font.getmetrics()
        line_h = ascent + descent
        block_h = line_h * len(lines)
        pad = int(W * 0.05)

        band = Image.new("RGBA", (W, block_h + pad * 2), (0, 0, 0, 140))
        base.alpha_composite(band, (0, H - block_h - pad * 2))

        y = H - block_h - pad
        for line in lines:
            line_w = draw.textlength(line, font=font)
            draw.text(((W - line_w) / 2, y), line, font=font, fill=(255, 255, 255, 255))
            y += line_h

    if logo_web_path:
        logo_fs = web_to_fs(logo_web_path)
        if os.path.exists(logo_fs):
            logo = Image.open(logo_fs).convert("RGBA")
            target_w = int(W * 0.18)
            ratio = target_w / logo.width
            logo = logo.resize((target_w, int(logo.height * ratio)))
            margin = int(W * 0.03)
            base.alpha_composite(logo, (margin, margin))

    slug = _slug_from_web(base_web_path)
    fs_path, web_path = new_media_path(slug, "png")
    base.convert("RGB").save(fs_path, "PNG")
    return web_path
