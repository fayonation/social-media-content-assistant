"""Imager: turns a plan's English image prompt into one or more saved images.

Counts per format:
- post     -> 1 image (1:1, text-free)
- carousel -> 3 images (1:1, text-free)
- video    -> 2 keyframes (video model ratio, text-free)
"""

from config import slugify
from providers import image

FORMAT_COUNTS = {"post": 1, "carousel": 3, "video": 2}

STYLE_SUFFIX = "high quality, professional social media visual, balanced composition"
NO_TEXT_SUFFIX = "no text, no typography, no words, no logos, no watermarks"
SQUARE_SUFFIX = "square 1:1 composition, Instagram feed format"


def _full_prompt(plan: dict, brand, slide: int, total: int, *, square: bool) -> str:
    base = plan.get("image_prompt_en", plan.get("topic", ""))
    style = brand["visual_style"] or ""
    variation = f" (variation {slide + 1} of {total}, distinct composition)" if total > 1 else ""
    parts = [f"{base}{variation}", style, STYLE_SUFFIX, NO_TEXT_SUFFIX]
    if square:
        parts.append(SQUARE_SUFFIX)
    return ". ".join(p for p in parts if p).strip()


def make_images(
    brand,
    plan: dict,
    fmt: str,
    reference_assets: list[dict] | None = None,
    on_progress=None,
) -> list[str]:
    count = FORMAT_COUNTS.get(fmt, 1)
    slug = slugify(brand["name"])
    square = fmt in ("post", "carousel")
    paths: list[str] = []
    for i in range(count):
        if on_progress:
            on_progress("image", f"Generating image {i + 1} of {count}…")
        prompt = _full_prompt(plan, brand, i, count, square=square)
        paths.append(
            image.generate_image(
                prompt,
                slug,
                reference_assets=reference_assets,
                square=square,
            )
        )
    return paths
