"""Video brief: scene-by-scene plan + a ready-to-use video prompt.

We don't generate video locally (too slow). We always produce keyframe images, scene
descriptions, and a consolidated prompt. Depending on config, providers.video may also
generate the clip on Replicate (video_model) or POST the brief to a custom URL
(video_api); otherwise the brief is returned as-is for a manual video editor.
"""

from config import slugify
from providers import text, video
from pipeline.brand_context import build_full_context

SYSTEM = "You are a short-form video director planning a 15-30s social video."


def build_brief(
    brand,
    plan: dict,
    keyframes: list[str],
    selected_assets: list[dict] | None = None,
) -> dict:
    context = build_full_context(brand, selected_assets or [])
    prompt = f"""Brand: {brand['name']}
Voice & tone: {brand['voice_tone'] or 'n/a'}
Visual style: {brand['visual_style'] or 'n/a'}
Concept: topic={plan.get('topic')}, angle={plan.get('angle')}, hook={plan.get('hook')}, cta={plan.get('cta')}

{context}

Plan a short-form vertical video. Respond ONLY as JSON with keys:
- scenes: array of objects, each with: description (what happens on screen),
  duration_seconds (number), on_screen_text (always empty string — no on-screen text)
- video_prompt: a single consolidated text-to-video prompt in English describing
  the full clip (camera, motion, mood, pacing). No on-screen text or typography.
"""
    result = text.generate_json(prompt, system=SYSTEM)
    brief = {
        "keyframes": keyframes,
        "scenes": result.get("scenes", []),
        "video_prompt": result.get("video_prompt", ""),
    }
    return video.build_or_send_brief(
        brief,
        brand_slug=slugify(brand["name"]),
        reference_assets=selected_assets,
    )
