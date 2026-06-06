"""Replicate model registry: store multiple image/video models, pick active ones.

Models live in SQLite. Providers read the active model for each kind; config.json
is only a fallback and for the API token.
"""

import json
import re
from urllib.parse import urlparse

import replicate

import db
from config import ConfigError, get_config
from providers._replicate import get_client
from providers.text import ProviderError

SLUG_RE = re.compile(r"^[a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+$")


def parse_slug(text: str) -> str:
    """Extract owner/name from a Replicate URL or bare slug."""
    text = (text or "").strip()
    if not text:
        raise ProviderError("Paste a Replicate model URL or owner/name slug.")
    if "replicate.com" in text:
        path = urlparse(text).path.strip("/")
        parts = [p for p in path.split("/") if p and p not in ("api", "examples", "readme", "versions")]
        if len(parts) >= 2:
            return f"{parts[0]}/{parts[1]}"
    if SLUG_RE.match(text):
        return text
    raise ProviderError(
        "Could not parse model slug. Paste e.g. https://replicate.com/owner/model or owner/model."
    )


def coerce_value(raw: str):
    s = (raw or "").strip()
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    if s.lower() == "null":
        return None
    if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass
    try:
        return int(s) if "." not in s else float(s)
    except ValueError:
        return s


def defaults_from_form(field_keys: list[str], field_values: list[str]) -> dict:
    out: dict = {}
    for key, val in zip(field_keys, field_values):
        key = (key or "").strip()
        if not key:
            continue
        out[key] = coerce_value(val)
    return out


def defaults_from_raw(raw: str) -> dict:
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"Invalid JSON for defaults: {exc}") from exc
    if not isinstance(data, dict):
        raise ProviderError("Defaults JSON must be an object, e.g. {\"duration\": 5}.")
    return data


def _schema_inputs(model_obj) -> list[dict]:
    lv = getattr(model_obj, "latest_version", None)
    if not lv:
        return []
    schema = getattr(lv, "openapi_schema", None) or {}
    props = schema.get("components", {}).get("schemas", {}).get("Input", {}).get("properties", {})
    defs = schema.get("components", {}).get("schemas", {})
    rows = []
    for name, spec in sorted(props.items(), key=lambda kv: kv[1].get("x-order", 999)):
        if name == "prompt":
            continue
        default = spec.get("default", "")
        enum = spec.get("enum")
        if not enum and spec.get("allOf"):
            ref = spec["allOf"][0].get("$ref", "")
            enum = defs.get(ref.split("/")[-1], {}).get("enum")
        rows.append({
            "name": name,
            "default": default,
            "enum": enum,
            "type": spec.get("type", ""),
            "format": spec.get("format", ""),
        })
    return rows


def validate_model(slug: str) -> dict:
    slug = parse_slug(slug)
    owner, _, name = slug.partition("/")
    try:
        model = get_client().models.get(owner, name)
    except replicate.exceptions.ReplicateError as exc:
        raise ProviderError(f"Replicate could not find '{slug}': {exc}") from exc
    if not model.latest_version:
        raise ProviderError(f"Model '{slug}' has no runnable version.")
    return {
        "slug": slug,
        "description": getattr(model, "description", "") or "",
        "inputs": _schema_inputs(model),
    }


def list_models(kind: str | None = None):
    with db.db() as conn:
        if kind:
            rows = conn.execute(
                "SELECT * FROM replicate_model WHERE kind=? ORDER BY created_at DESC", (kind,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM replicate_model ORDER BY kind, created_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_active(kind: str) -> dict | None:
    with db.db() as conn:
        row = conn.execute(
            """SELECT m.* FROM replicate_model m
               JOIN app_setting s ON s.value = CAST(m.id AS TEXT)
               WHERE s.key=?""",
            (f"active_{kind}_model_id",),
        ).fetchone()
    if row:
        data = dict(row)
        data["defaults"] = json.loads(data["defaults"] or "{}")
        return data
    return _fallback_from_config(kind)


def _fallback_from_config(kind: str) -> dict | None:
    cfg = get_config()
    if kind == "image" and cfg.get("image_model"):
        return {
            "slug": cfg["image_model"],
            "defaults": cfg.get("image_defaults") or {},
            "from_config": True,
        }
    if kind == "video" and cfg.get("video_model"):
        return {
            "slug": cfg["video_model"],
            "defaults": cfg.get("video_defaults") or {},
            "from_config": True,
        }
    if kind == "text" and cfg.get("text_model"):
        return {
            "slug": cfg["text_model"],
            "defaults": cfg.get("text_defaults") or {},
            "from_config": True,
        }
    return None


def is_ollama_text_active() -> bool:
    with db.db() as conn:
        row = conn.execute(
            "SELECT value FROM app_setting WHERE key='active_text_source'"
        ).fetchone()
    return bool(row and row["value"] == "ollama")


def set_active_ollama_text() -> None:
    with db.db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO app_setting (key, value) VALUES ('active_text_source', 'ollama')"
        )
        conn.execute("DELETE FROM app_setting WHERE key='active_text_model_id'")


def set_active(model_id: int) -> None:
    with db.db() as conn:
        row = conn.execute("SELECT kind FROM replicate_model WHERE id=?", (model_id,)).fetchone()
        if not row:
            raise ProviderError("Model not found.")
        conn.execute(
            "INSERT OR REPLACE INTO app_setting (key, value) VALUES (?, ?)",
            (f"active_{row['kind']}_model_id", str(model_id)),
        )
        if row["kind"] == "text":
            conn.execute(
                "INSERT OR REPLACE INTO app_setting (key, value) VALUES ('active_text_source', 'replicate')"
            )


def create_model(kind: str, slug: str, label: str, defaults: dict, validated: dict | None = None) -> int:
    slug = parse_slug(slug)
    info = validated or validate_model(slug)
    with db.db() as conn:
        conn.execute(
            """INSERT INTO replicate_model (kind, slug, label, defaults, validated_at, schema_summary)
               VALUES (?, ?, ?, ?, datetime('now'), ?)
               ON CONFLICT(kind, slug) DO UPDATE SET
                 label=excluded.label,
                 defaults=excluded.defaults,
                 validated_at=excluded.validated_at,
                 schema_summary=excluded.schema_summary""",
            (
                kind,
                slug,
                label or slug,
                json.dumps(defaults, ensure_ascii=False),
                json.dumps(info.get("inputs", []), ensure_ascii=False),
            ),
        )
        model_id = conn.execute(
            "SELECT id FROM replicate_model WHERE kind=? AND slug=?", (kind, slug)
        ).fetchone()["id"]
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM replicate_model WHERE kind=?", (kind,)
        ).fetchone()["c"]
        if count == 1:
            conn.execute(
                "INSERT OR REPLACE INTO app_setting (key, value) VALUES (?, ?)",
                (f"active_{kind}_model_id", str(model_id)),
            )
        return model_id


def get_active_id(kind: str) -> int | None:
    with db.db() as conn:
        row = conn.execute(
            "SELECT value FROM app_setting WHERE key=?", (f"active_{kind}_model_id",)
        ).fetchone()
    return int(row["value"]) if row else None


def get_model(model_id: int) -> dict | None:
    with db.db() as conn:
        row = conn.execute("SELECT * FROM replicate_model WHERE id=?", (model_id,)).fetchone()
    if not row:
        return None
    data = dict(row)
    data["defaults"] = json.loads(data["defaults"] or "{}")
    data["schema_summary"] = json.loads(data["schema_summary"] or "[]")
    return data


def update_model(model_id: int, label: str, defaults: dict) -> None:
    with db.db() as conn:
        conn.execute(
            "UPDATE replicate_model SET label=?, defaults=? WHERE id=?",
            (label, json.dumps(defaults, ensure_ascii=False), model_id),
        )


def delete_model(model_id: int) -> None:
    with db.db() as conn:
        row = conn.execute("SELECT kind FROM replicate_model WHERE id=?", (model_id,)).fetchone()
        if not row:
            return
        key = f"active_{row['kind']}_model_id"
        active = conn.execute("SELECT value FROM app_setting WHERE key=?", (key,)).fetchone()
        conn.execute("DELETE FROM replicate_model WHERE id=?", (model_id,))
        if active and active["value"] == str(model_id):
            conn.execute("DELETE FROM app_setting WHERE key=?", (key,))


def seed_from_config() -> None:
    with db.db() as conn:
        if conn.execute("SELECT COUNT(*) AS c FROM replicate_model").fetchone()["c"]:
            return
    try:
        cfg = get_config()
    except ConfigError:
        return
    try:
        if cfg.get("image_model"):
            create_model("image", cfg["image_model"], cfg["image_model"], cfg.get("image_defaults") or {})
        if cfg.get("video_model"):
            create_model("video", cfg["video_model"], cfg["video_model"], cfg.get("video_defaults") or {})
        if cfg.get("text_model"):
            create_model("text", cfg["text_model"], cfg["text_model"], cfg.get("text_defaults") or {})
    except ProviderError:
        pass
