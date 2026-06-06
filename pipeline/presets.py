"""Optional campaign presets for idea generation."""

PRESETS = {
    "educate": {
        "label": "Educate",
        "prompt": (
            "Campaign preset: EDUCATE. Teach something surprising and specific. "
            "Use a hook that makes people feel smarter. Include at least one concrete fact "
            "or myth-bust. Avoid generic wellness fluff."
        ),
    },
    "product_launch": {
        "label": "Product launch",
        "prompt": (
            "Campaign preset: PRODUCT LAUNCH. Build desire and urgency without being spammy. "
            "Highlight what is new, different, or limited. Strong visual hero moment."
        ),
    },
    "myth_bust": {
        "label": "Myth bust",
        "prompt": (
            "Campaign preset: MYTH BUST. Start with a common misconception, then flip it. "
            "Be bold and memorable. The visual should dramatize the before/after belief."
        ),
    },
    "ugc_style": {
        "label": "UGC style",
        "prompt": (
            "Campaign preset: UGC STYLE. Feel like a real person discovered something, "
            "not a brand ad. Casual, authentic, slightly imperfect energy."
        ),
    },
}


def preset_prompt(preset_id: str) -> str:
    entry = PRESETS.get((preset_id or "").strip())
    return entry["prompt"] if entry else ""


def preset_choices() -> list[tuple[str, str]]:
    return [("", "None")] + [(k, v["label"]) for k, v in PRESETS.items()]
