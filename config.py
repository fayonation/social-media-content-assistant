"""Loads runtime configuration from config.json (gitignored).

Copy config.example.json -> config.json and fill in your values.
Replicate token can also be set via REPLICATE_API_TOKEN (env var wins over config.json).
"""

import json
import os
import re
import uuid
from functools import lru_cache

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
EXAMPLE_PATH = os.path.join(BASE_DIR, "config.example.json")
MEDIA_DIR = os.path.join(BASE_DIR, "media")
FONTS_DIR = os.path.join(BASE_DIR, "assets", "fonts")
ARABIC_FONT = os.path.join(FONTS_DIR, "NotoNaskhArabic.ttf")
LATIN_FONT = os.path.join(FONTS_DIR, "NotoSans.ttf")

APP_NAME = "Social Media Content Assistant"

DEFAULTS = {
    "replicate_api_token": "",
    "image_model": "openai/gpt-image-2",
    # Extra inputs merged into the Replicate call. Adjust to match the model's
    # schema on its Replicate page if it rejects a field.
    "image_defaults": {"aspect_ratio": "1:1", "quality": "low", "output_format": "png"},
    "ollama_url": "http://localhost:11434",
    "ollama_model": "llama3.1",
    # Optional Replicate LLM for planner/captioner/brief (also add under Models → Text).
    "text_model": None,
    "text_defaults": {},
    # Video generation. Set video_model to a Replicate text-to-video slug to
    # generate clips, or leave null and use video_api (a custom POST URL), or
    # leave both null to just get a brief to take to a video editor.
    "video_model": None,
    "video_defaults": {},
    "video_api": None,
}


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug or "brand"


def new_media_path(brand_slug: str, ext: str = "png") -> tuple[str, str]:
    """Return (filesystem_path, web_path) for a fresh generated media file."""
    folder = os.path.join(MEDIA_DIR, brand_slug)
    os.makedirs(folder, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{ext}"
    fs_path = os.path.join(folder, name)
    web_path = f"/media/{brand_slug}/{name}"
    return fs_path, web_path


def new_asset_path(brand_slug: str, ext: str = "png") -> tuple[str, str]:
    """Return (filesystem_path, web_path) for a brand library asset upload."""
    folder = os.path.join(MEDIA_DIR, brand_slug, "assets")
    os.makedirs(folder, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{ext}"
    fs_path = os.path.join(folder, name)
    web_path = f"/media/{brand_slug}/assets/{name}"
    return fs_path, web_path


def web_to_fs(web_path: str) -> str:
    """Convert a stored /media/... web path back to a filesystem path."""
    rel = web_path.lstrip("/").split("/", 1)[1] if web_path.startswith("/media/") else web_path
    return os.path.join(MEDIA_DIR, rel)


class ConfigError(RuntimeError):
    """Raised when configuration is missing or invalid."""


def get_replicate_api_token() -> str:
    """Replicate token: REPLICATE_API_TOKEN env var overrides config.json."""
    env_token = (os.environ.get("REPLICATE_API_TOKEN") or "").strip()
    if env_token:
        return env_token
    return (get_config().get("replicate_api_token") or "").strip()


def fonts_available() -> bool:
    return os.path.isfile(ARABIC_FONT) and os.path.isfile(LATIN_FONT)


@lru_cache(maxsize=1)
def get_config() -> dict:
    data = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data.update(json.load(f))

    env_token = (os.environ.get("REPLICATE_API_TOKEN") or "").strip()
    if env_token:
        data["replicate_api_token"] = env_token

    token = (data.get("replicate_api_token") or "").strip()
    if not os.path.exists(CONFIG_PATH) and not token:
        raise ConfigError(
            "config.json not found and REPLICATE_API_TOKEN is not set. "
            "Copy config.example.json to config.json, or export REPLICATE_API_TOKEN."
        )
    return data


def require(key: str) -> str:
    if key == "replicate_api_token":
        value = get_replicate_api_token()
    else:
        value = get_config().get(key)
    if not value:
        raise ConfigError(f"Missing '{key}' in config.json.")
    return value
