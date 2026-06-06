"""Video handling, chosen by config:

- video_model set (a Replicate slug): generate the clip on Replicate and save the mp4.
- video_api set (a URL): POST the brief to a custom endpoint.
- neither: passthrough; take the brief (keyframes + prompt) to a video editor manually.
"""

import httpx
import replicate

from config import get_config, new_media_path
from model_registry import get_active, get_active_id, get_model
from pipeline.brand_context import asset_prompt_suffix
from providers import _replicate
from providers.text import ProviderError


def _active_video_schema() -> list:
    model_id = get_active_id("video")
    if model_id:
        model = get_model(model_id)
        if model:
            return model.get("schema_summary") or []
    return []


def _generate_with_replicate(
    brief: dict,
    brand_slug: str,
    reference_assets: list[dict] | None = None,
) -> dict:
    active = get_active("video")
    if not active:
        raise ProviderError(
            "No video model configured. Add one under Models in the app, or set video_model in config.json."
        )
    model = active["slug"]
    schema = _active_video_schema()

    prompt = brief.get("video_prompt", "")
    assets = reference_assets or []
    suffix = asset_prompt_suffix(assets)
    if suffix:
        prompt = f"{prompt}\n\n{suffix}"

    inp: dict = {**active.get("defaults", {}), "prompt": prompt}
    if assets:
        inp = _replicate.attach_reference_image(inp, schema, assets[0]["file_path"])

    try:
        output = _replicate.run(model, inp)
    except replicate.exceptions.ReplicateError as exc:
        raise ProviderError(f"Replicate video generation failed: {exc}") from exc

    items = output if isinstance(output, list) else [output]
    if not items:
        raise ProviderError("Replicate returned no video.")

    data = _replicate.to_bytes(items[0])
    fs_path, web_path = new_media_path(brand_slug, "mp4")
    with open(fs_path, "wb") as f:
        f.write(data)
    return {**brief, "sent": True, "video_path": web_path}


def _post_to_url(brief: dict, api: str) -> dict:
    try:
        with httpx.Client(timeout=600) as client:
            resp = client.post(api, json=brief)
            resp.raise_for_status()
            ctype = resp.headers.get("content-type", "")
            result = resp.json() if ctype.startswith("application/json") else {}
    except httpx.HTTPError as exc:
        raise ProviderError(f"Video API call failed: {exc}") from exc
    return {**brief, "sent": True, "result": result}


def build_or_send_brief(
    brief: dict,
    brand_slug: str = "brand",
    reference_assets: list[dict] | None = None,
) -> dict:
    cfg = get_config()
    if get_active("video"):
        return _generate_with_replicate(brief, brand_slug, reference_assets)
    if cfg.get("video_api"):
        return _post_to_url(brief, cfg["video_api"])
    return {**brief, "sent": False}
