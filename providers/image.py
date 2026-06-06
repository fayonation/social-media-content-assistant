"""Image generation via a Replicate model (selected in the Models UI).

generate_image() returns the web path (/media/...) of the saved image.
"""

import replicate

from config import new_media_path
from model_registry import get_active, get_active_id, get_model
from providers import _replicate
from pipeline.brand_context import asset_prompt_suffix
from providers.text import ProviderError


def _active_schema() -> list:
    model_id = get_active_id("image")
    if model_id:
        model = get_model(model_id)
        if model:
            return model.get("schema_summary") or []
    return []


def generate_image(
    prompt: str,
    brand_slug: str,
    reference_assets: list[dict] | None = None,
    *,
    square: bool = True,
) -> str:
    active = get_active("image")
    if not active:
        raise ProviderError(
            "No image model configured. Add one under Models in the app, or set image_model in config.json."
        )
    model = active["slug"]
    schema = _active_schema()

    full_prompt = prompt
    assets = reference_assets or []
    suffix = asset_prompt_suffix(assets)
    if suffix:
        full_prompt = f"{prompt}\n\n{suffix}"

    inp: dict = {**active.get("defaults", {}), "prompt": full_prompt}
    if square:
        inp = _replicate.merge_square_params(inp, schema)
    if assets:
        inp = _replicate.attach_reference_image(inp, schema, assets[0]["file_path"])

    try:
        output = _replicate.run(model, inp)
    except replicate.exceptions.ReplicateError as exc:
        raise ProviderError(f"Replicate image generation failed: {exc}") from exc

    items = output if isinstance(output, list) else [output]
    if not items:
        raise ProviderError("Replicate returned no image.")

    data = _replicate.to_bytes(items[0])
    fs_path, web_path = new_media_path(brand_slug, "png")
    with open(fs_path, "wb") as f:
        f.write(data)
    return web_path
