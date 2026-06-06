"""Shared brand identity + selected asset blocks for all AI prompts."""

ASSET_KIND_LABELS = {
    "logo": "logo",
    "symbol": "symbol",
    "character": "character",
    "product": "product",
    "other": "reference",
}


def _brand_dict(brand) -> dict:
    return brand if isinstance(brand, dict) else dict(brand)


def build_identity_block(brand) -> str:
    ctx = (_brand_dict(brand).get("identity_context") or "").strip()
    if not ctx:
        return ""
    return f"Brand identity (always follow):\n{ctx}"


def build_assets_block(assets: list[dict]) -> str:
    if not assets:
        return ""
    lines = ["Reference assets for this post:"]
    for asset in assets:
        kind = ASSET_KIND_LABELS.get(asset.get("kind", ""), asset.get("kind", "reference"))
        label = asset.get("label") or kind
        desc = (asset.get("description") or "").strip()
        detail = desc if desc else label
        lines.append(f"- [{kind}] {label}: {detail}")
    return "\n".join(lines)


def build_full_context(brand, selected_assets: list[dict]) -> str:
    parts = [build_identity_block(brand), build_assets_block(selected_assets)]
    return "\n\n".join(p for p in parts if p)


def asset_prompt_suffix(assets: list[dict]) -> str:
    """English suffix for image/video prompts describing checked assets."""
    if not assets:
        return ""
    lines = ["Reference assets for this post:"]
    for asset in assets:
        kind = ASSET_KIND_LABELS.get(asset.get("kind", ""), asset.get("kind", "reference"))
        label = asset.get("label") or kind
        desc = (asset.get("description") or "").strip()
        detail = desc if desc else label
        lines.append(f"- [{kind}] {label}: {detail}")
    return "\n".join(lines)
