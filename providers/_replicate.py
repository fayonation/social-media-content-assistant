"""Shared Replicate helpers used by both image and video providers."""

import httpx
import replicate

from config import get_replicate_api_token, web_to_fs
from providers.text import ProviderError

IMAGE_INPUT_HINTS = (
    "image",
    "input_image",
    "image_input",
    "start_image",
    "init_image",
    "reference_image",
    "input_images",
)


def get_client() -> replicate.Client:
    token = get_replicate_api_token()
    if not token or token.startswith("r8_paste"):
        raise ProviderError(
            "Missing Replicate API token. Set replicate_api_token in config.json "
            "or REPLICATE_API_TOKEN in the environment. Get one at "
            "https://replicate.com/account/api-tokens."
        )
    return replicate.Client(api_token=token)


def _status(exc: replicate.exceptions.ReplicateError) -> int | None:
    return getattr(exc, "status", None)


def run(model: str, inp: dict):
    """Run a Replicate model, resolving a version for community models.

    Official models run by 'owner/name'. Community models require a version hash;
    if 'owner/name' 404s, we look up the latest version and retry as 'owner/name:hash'.
    """
    client = get_client()
    try:
        return client.run(model, input=inp)
    except replicate.exceptions.ReplicateError as exc:
        if _status(exc) == 404 and ":" not in model:
            owner, _, name = model.partition("/")
            latest = client.models.get(owner, name).latest_version
            if not latest:
                raise ProviderError(
                    f"Model '{model}' has no runnable version on Replicate."
                ) from exc
            return client.run(f"{model}:{latest.id}", input=inp)
        raise


def to_bytes(item) -> bytes:
    """Normalize a Replicate output item (FileOutput, bytes, or URL) to bytes."""
    if hasattr(item, "read"):
        return item.read()
    if isinstance(item, (bytes, bytearray)):
        return bytes(item)
    url = str(item)
    if url.startswith("http"):
        with httpx.Client(timeout=600) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.content
    raise ProviderError(f"Unexpected output from Replicate: {url[:80]}")


def _schema_field_names(schema_summary: list) -> set[str]:
    return {row.get("name", "") for row in (schema_summary or [])}


def find_image_input_key(schema_summary: list) -> str | None:
    """Pick the best image URI field from a model's stored schema summary."""
    if not schema_summary:
        return None
    by_name = {row.get("name", ""): row for row in schema_summary}
    for hint in IMAGE_INPUT_HINTS:
        if hint in by_name:
            row = by_name[hint]
            if row.get("format") == "uri" or row.get("type") == "string" or "image" in hint:
                return hint
    for row in schema_summary:
        name = row.get("name", "")
        if row.get("format") == "uri" and "image" in name.lower():
            return name
    return None


def merge_square_params(inp: dict, schema_summary: list) -> dict:
    """Force 1:1 square output based on what the model schema supports."""
    names = _schema_field_names(schema_summary)
    out = dict(inp)
    if "aspect_ratio" in names:
        out["aspect_ratio"] = "1:1"
    elif "width" in names and "height" in names:
        out["width"] = 1024
        out["height"] = 1024
    return out


def attach_reference_image(inp: dict, schema_summary: list, web_path: str) -> dict:
    """Attach a local brand asset as a Replicate image input when the schema allows."""
    key = find_image_input_key(schema_summary)
    if not key:
        return inp
    fs_path = web_to_fs(web_path)
    out = dict(inp)
    out[key] = open(fs_path, "rb")
    return out
