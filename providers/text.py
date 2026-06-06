"""Text generation for planner, captioner, and video brief.

Uses the active text model from the Models UI (Replicate LLM) or Ollama when
explicitly selected there. Ollama is never required unless you activate it.
"""

import json
import re

import httpx
import replicate

from config import get_config
from providers import _replicate


class ProviderError(RuntimeError):
    """User-friendly provider failure."""


def _registry():
    import model_registry

    return model_registry


def text_provider_label() -> str:
    reg = _registry()
    if reg.is_ollama_text_active():
        cfg = get_config()
        return f"Ollama ({cfg.get('ollama_model', 'local')})"
    active = reg.get_active("text")
    if active:
        return active.get("label") or active.get("slug", "Replicate")
    return "AI"


def _require_text_route() -> tuple[str, dict | None]:
    reg = _registry()
    if reg.is_ollama_text_active():
        return "ollama", None
    active = reg.get_active("text")
    if active:
        return "replicate", active
    raise ProviderError(
        "No text model configured. Open Models, add a text model (Replicate LLM) "
        "and click Use this — or activate Ollama (local) if you prefer running locally."
    )


def _active_schema() -> list:
    reg = _registry()
    model_id = reg.get_active_id("text")
    if model_id:
        model = reg.get_model(model_id)
        if model:
            return model.get("schema_summary") or []
    return []


def _ollama_endpoint() -> tuple[str, str]:
    cfg = get_config()
    return cfg["ollama_url"].rstrip("/"), cfg["ollama_model"]


def _ollama_chat(prompt: str, system: str | None = None, json_mode: bool = False) -> str:
    url, model = _ollama_endpoint()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload: dict = {"model": model, "messages": messages, "stream": False}
    if json_mode:
        payload["format"] = "json"

    try:
        with httpx.Client(timeout=180) as client:
            resp = client.post(f"{url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.ConnectError as exc:
        raise ProviderError(
            f"Could not reach Ollama at {url}. Is it running? Try 'ollama serve'."
        ) from exc
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:200]
        if exc.response.status_code == 404:
            raise ProviderError(
                f"Ollama model '{model}' not found. Run 'ollama pull {model}'."
            ) from exc
        raise ProviderError(f"Ollama error ({exc.response.status_code}): {detail}") from exc

    return (data.get("message") or {}).get("content", "").strip()


def _schema_field_names(schema_summary: list) -> set[str]:
    return {row.get("name", "") for row in (schema_summary or [])}


def _build_replicate_input(
    prompt: str,
    system: str | None,
    defaults: dict,
    schema_summary: list,
    *,
    json_mode: bool,
) -> dict:
    inp = dict(defaults)
    names = _schema_field_names(schema_summary)
    user_content = prompt
    if json_mode:
        user_content = f"{prompt}\n\nRespond with valid JSON only."

    if json_mode:
        if "response_format" in names and not inp.get("response_format"):
            inp["response_format"] = {"type": "json_object"}
        if "max_completion_tokens" in names and not inp.get("max_completion_tokens"):
            inp["max_completion_tokens"] = 8192
        elif "max_tokens" in names and not inp.get("max_tokens"):
            inp["max_tokens"] = 8192
        if "temperature" in names and inp.get("temperature") in (None, "", 0):
            inp["temperature"] = 0.7

    if "messages" in names:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user_content})
        inp["messages"] = messages
    elif "system_prompt" in names and system:
        inp["system_prompt"] = system
        inp["prompt"] = user_content
    elif "prompt" in names or not names:
        full = user_content
        if system and "prompt" in names:
            full = f"{system}\n\n{user_content}"
        elif system and "prompt" not in names:
            full = f"{system}\n\n{user_content}"
        inp["prompt"] = full
    else:
        inp["prompt"] = f"{system}\n\n{user_content}" if system else user_content

    return inp


def _normalize_replicate_output(output) -> str:
    if output is None:
        return ""
    if isinstance(output, str):
        return output.strip()
    if isinstance(output, (bytes, bytearray)):
        return bytes(output).decode("utf-8", errors="replace").strip()
    if hasattr(output, "read"):
        data = output.read()
        if isinstance(data, bytes):
            return data.decode("utf-8", errors="replace").strip()
        return str(data).strip()
    if isinstance(output, list):
        parts = []
        for item in output:
            parts.append(_normalize_replicate_output(item))
        return "".join(parts).strip()
    return str(output).strip()


def _replicate_chat(
    prompt: str,
    system: str | None = None,
    json_mode: bool = False,
    *,
    active: dict,
) -> str:
    schema = _active_schema()
    inp = _build_replicate_input(
        prompt,
        system,
        active.get("defaults") or {},
        schema,
        json_mode=json_mode,
    )
    try:
        output = _replicate.run(active["slug"], inp)
    except replicate.exceptions.ReplicateError as exc:
        raise ProviderError(f"Replicate text generation failed: {exc}") from exc
    text = _normalize_replicate_output(output)
    if not text:
        raise ProviderError("Replicate returned empty text.")
    return text


def chat(prompt: str, system: str | None = None, json_mode: bool = False) -> str:
    provider, active = _require_text_route()
    if provider == "ollama":
        return _ollama_chat(prompt, system=system, json_mode=json_mode)
    return _replicate_chat(prompt, system=system, json_mode=json_mode, active=active)


def _parse_json_value(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|```\s*$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for pattern in (r"\{[\s\S]*\}", r"\[[\s\S]*\]"):
        match = re.search(pattern, text)
        if not match:
            continue
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
    raise ProviderError(f"Model did not return valid JSON. Preview: {text[:300]}")


def _extract_json(text: str) -> dict:
    data = _parse_json_value(text)
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        return {"items": data}
    raise ProviderError(f"Model returned unexpected JSON type: {type(data).__name__}")


def generate_json(prompt: str, system: str | None = None) -> dict:
    raw = chat(prompt, system=system, json_mode=True)
    return _extract_json(raw)
