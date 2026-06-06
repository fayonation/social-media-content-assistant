"""Captioner: writes the final caption and hashtags.

Language-aware. For Moroccan Darija (ar-MA) it writes in Darija using Arabic script.
All post copy lives in the caption — images are text-free.
"""

from providers import text
from pipeline.brand_context import build_full_context

LANGUAGE_NAMES = {
    "en": "English",
    "ar-MA": "Moroccan Arabic (Darija), written in Arabic script",
    "ar": "Modern Standard Arabic",
    "fr": "French",
}

SYSTEM = "You are a native-fluent social media copywriter who matches brand voice exactly."


def write_caption(
    brand,
    plan: dict,
    selected_assets: list[dict] | None = None,
    *,
    idea_brief: dict | None = None,
) -> dict:
    language = LANGUAGE_NAMES.get(brand["language"], brand["language"])
    context = build_full_context(brand, selected_assets or [])
    brief = idea_brief or {}
    polished = brief.get("polished_concept") or {}
    structure = polished.get("caption_structure") or []
    facts = polished.get("facts_to_include") or []
    structure_block = ""
    if structure:
        structure_block = "Caption structure (follow this flow):\n" + "\n".join(
            f"- {s}" for s in structure
        )
    facts_block = ""
    if facts:
        facts_block = "Facts that MUST appear in the caption:\n" + "\n".join(f"- {f}" for f in facts)

    prompt = f"""Brand: {brand['name']}
Voice & tone: {brand['voice_tone'] or 'n/a'}
Default hashtags to consider: {brand['hashtags'] or 'none'}
Write everything in: {language}

{context}

Post concept:
- topic: {plan.get('topic')}
- angle: {plan.get('angle')}
- hook: {plan.get('hook')}
- cta: {plan.get('cta')}
- visual concept: {polished.get('visual_concept') or plan.get('visual_style') or 'n/a'}

{structure_block}
{facts_block}

Respond ONLY as JSON with keys:
- caption: the full post caption in {language}, on-brand, engaging, with line breaks.
  This is the only place for post copy — images have no text.
- hashtags: a single string of relevant hashtags
"""
    result = text.generate_json(prompt, system=SYSTEM)
    return {
        "caption": result.get("caption", ""),
        "hashtags": result.get("hashtags", brand["hashtags"] or ""),
    }
