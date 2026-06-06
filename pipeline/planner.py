"""Planner: chooses a fresh, on-brand creative direction for a slot.

Returns a plan dict: {topic, angle, hook, visual_style, cta, image_prompt_en, keywords}.
Retries against the creative-memory similarity gate to avoid repetition.
"""

from providers import text
from pipeline import memory
from pipeline.brand_context import build_full_context

MAX_ATTEMPTS = 4

SYSTEM = (
    "You are a senior social media creative strategist. You invent distinctive, "
    "scroll-stopping post concepts that fit a brand's identity. You never repeat "
    "angles, hooks, or visual styles that were used before."
)


def _prompt(brand, slot, avoid: str, extra_avoid: str, context: str) -> str:
    return f"""Brand: {brand['name']}
Voice & tone: {brand['voice_tone'] or 'n/a'}
Visual style: {brand['visual_style'] or 'n/a'}
Target language of the audience: {brand['language']}
Post format: {slot['format']}
Topic hint (optional): {slot['topic_hint'] or 'none - you choose'}

{context}

{avoid}
{extra_avoid}

Produce ONE fresh post concept. Respond ONLY as JSON with these keys:
- topic: short subject of the post
- angle: the specific creative angle / point of view
- hook: a punchy idea for the opening line (concept, not final copy)
- visual_style: short description of the image look (palette, composition, mood)
- cta: the call to action
- image_prompt_en: a detailed ENGLISH text-to-image prompt describing a creative product
  or reference-asset visual (subjects, setting, lighting, mood, composition). The image
  must be text-free: no words, typography, logos, watermarks, or labels in the scene.
- keywords: array of 4-7 lowercase keywords summarizing this concept

Make it clearly different from anything already used."""


def plan_slot(brand, slot, selected_assets: list[dict] | None = None) -> dict:
    avoid = memory.avoid_context(brand["id"])
    context = build_full_context(brand, selected_assets or [])
    extra_avoid = ""
    last: dict = {}
    for _ in range(MAX_ATTEMPTS):
        plan = text.generate_json(_prompt(brand, slot, avoid, extra_avoid, context), system=SYSTEM)
        plan.setdefault("keywords", [])
        last = plan
        if not memory.is_duplicate(plan, brand["id"]):
            return plan
        extra_avoid = (
            "Your previous idea was too similar to past posts. Choose a completely "
            "different topic, angle, hook, and visual style."
        )
    return last
