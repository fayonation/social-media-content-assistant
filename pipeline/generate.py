"""Orchestrator: turns brand + format into a draft post.

Flow: idea_engine -> captioner -> imager (+ videobrief for video) -> insert draft post.
"""

import json
from collections.abc import Callable

import db
from pipeline import captioner, idea_engine, imager, videobrief
from providers.text import text_provider_label

ProgressFn = Callable[[str, str], None]


def _slot_context(format: str, topic_hint: str) -> dict:
    return {"format": format, "topic_hint": topic_hint or ""}


def _progress(on_progress: ProgressFn | None, step: str, detail: str) -> None:
    if on_progress:
        on_progress(step, detail)


def _resolve_plan(
    brand,
    ctx: dict,
    selected_assets: list[dict],
    *,
    audience: str = "",
    preset: str = "",
    on_progress: ProgressFn | None = None,
    on_step=None,
    refined_plan: dict | None = None,
    idea_brief: dict | None = None,
) -> tuple[dict, dict]:
    if refined_plan:
        _progress(on_progress, "anchor", "Using your edited concept…")
        return idea_engine.refine(
            brand,
            ctx,
            selected_assets,
            audience=audience,
            preset=preset,
            on_progress=on_progress,
            on_step=on_step,
            skip_engine=True,
            refined_plan=refined_plan,
            idea_brief=idea_brief,
        )
    return idea_engine.refine(
        brand,
        ctx,
        selected_assets,
        audience=audience,
        preset=preset,
        on_progress=on_progress,
        on_step=on_step,
    )


def _build_post(
    brand,
    ctx: dict,
    selected_assets: list[dict],
    on_progress: ProgressFn | None = None,
    *,
    audience: str = "",
    preset: str = "",
    refined_plan: dict | None = None,
    idea_brief: dict | None = None,
) -> dict:
    text_label = text_provider_label()

    plan, brief = _resolve_plan(
        brand,
        ctx,
        selected_assets,
        audience=audience,
        preset=preset,
        on_progress=on_progress,
        refined_plan=refined_plan,
        idea_brief=idea_brief,
    )

    _progress(on_progress, "caption", f"Writing caption and hashtags with {text_label}…")
    caption = captioner.write_caption(brand, plan, selected_assets, idea_brief=brief)
    _progress(on_progress, "caption", "Caption draft complete")

    count = imager.FORMAT_COUNTS.get(ctx["format"], 1)
    _progress(on_progress, "images", f"Generating {count} image(s) with Replicate…")
    images = imager.make_images(
        brand,
        plan,
        ctx["format"],
        reference_assets=selected_assets,
        on_progress=on_progress,
    )
    _progress(on_progress, "images", f"{len(images)} image(s) saved")

    brief_obj = None
    if ctx["format"] == "video":
        _progress(on_progress, "video", "Building video brief and scene list…")
        brief_obj = videobrief.build_brief(brand, plan, images, selected_assets)
        _progress(on_progress, "video", "Video brief ready")

    asset_ids = [a["id"] for a in selected_assets]
    return {
        "caption": caption.get("caption", ""),
        "hashtags": caption.get("hashtags", ""),
        "image_paths": images,
        "video_brief": brief_obj,
        "plan": plan,
        "idea_brief": brief,
        "attachments_used": asset_ids,
    }


def _insert_post(brand_id: int, format: str, topic_hint: str, fields: dict) -> int:
    with db.db() as conn:
        cur = conn.execute(
            """INSERT INTO post (brand_id, format, topic_hint, caption, hashtags, media_paths,
                                 video_brief, plan, idea_brief, attachments_used, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft')""",
            (
                brand_id,
                format,
                topic_hint or None,
                fields["caption"],
                fields["hashtags"],
                "[]",
                json.dumps(fields["video_brief"], ensure_ascii=False) if fields.get("video_brief") else None,
                json.dumps(fields["plan"], ensure_ascii=False),
                json.dumps(fields.get("idea_brief") or {}, ensure_ascii=False),
                json.dumps(fields["attachments_used"], ensure_ascii=False),
            ),
        )
        post_id = cur.lastrowid
        for path in fields.get("image_paths") or []:
            db.add_post_media(conn, post_id, path, "image", "generate", selected=True)
    return post_id


def _load_brand_context(brand_id: int, asset_ids: list[int] | None) -> tuple[dict, list[dict]]:
    with db.db() as conn:
        row = conn.execute("SELECT * FROM brand WHERE id=?", (brand_id,)).fetchone()
        if not row:
            raise ValueError(f"Brand {brand_id} not found")
        brand = dict(row)
        selected = db.get_assets_by_ids(conn, brand_id, asset_ids or [])
    return brand, selected


def elevate_idea(
    brand_id: int,
    format: str = "post",
    topic_hint: str = "",
    asset_ids: list[int] | None = None,
    *,
    audience: str = "",
    preset: str = "",
    on_progress: ProgressFn | None = None,
    on_step=None,
) -> tuple[dict, dict]:
    _progress(on_progress, "load", "Loading brand identity and selected assets…")
    brand, selected = _load_brand_context(brand_id, asset_ids)
    ctx = _slot_context(format, topic_hint)
    return _resolve_plan(
        brand,
        ctx,
        selected,
        audience=audience,
        preset=preset,
        on_progress=on_progress,
        on_step=on_step,
    )


def run_idea_step(
    brand_id: int,
    format: str,
    topic_hint: str,
    asset_ids: list[int] | None,
    *,
    audience: str = "",
    preset: str = "",
    from_step: str,
    state: dict,
    on_progress: ProgressFn | None = None,
    on_step=None,
) -> tuple[dict, dict]:
    from pipeline import idea_engine

    brand, selected = _load_brand_context(brand_id, asset_ids)
    ctx = _slot_context(format, topic_hint)
    return idea_engine.run_from_step(
        brand,
        ctx,
        selected,
        audience=audience,
        preset=preset,
        from_step=from_step,
        state=state,
        on_progress=on_progress,
        on_step=on_step,
    )


def generate_for_brand(
    brand_id: int,
    format: str = "post",
    topic_hint: str = "",
    asset_ids: list[int] | None = None,
    on_progress: ProgressFn | None = None,
    *,
    audience: str = "",
    preset: str = "",
    refined_plan: dict | None = None,
    idea_brief: dict | None = None,
) -> int:
    _progress(on_progress, "load", "Loading brand identity and selected assets…")
    brand, selected = _load_brand_context(brand_id, asset_ids)

    asset_note = f"{len(selected)} asset(s) attached" if selected else "identity only (no assets attached)"
    _progress(on_progress, "load", f"Brand “{brand['name']}” — {asset_note}")

    ctx = _slot_context(format, topic_hint)
    fields = _build_post(
        brand,
        ctx,
        selected,
        on_progress,
        audience=audience,
        preset=preset,
        refined_plan=refined_plan,
        idea_brief=idea_brief,
    )
    _progress(on_progress, "save", "Saving draft to post bank…")
    post_id = _insert_post(brand_id, format, topic_hint, fields)
    _progress(on_progress, "save", f"Draft post #{post_id} created")
    return post_id


def _load_post_for_regen(post_id: int) -> dict:
    with db.db() as conn:
        row = conn.execute("SELECT * FROM post WHERE id=?", (post_id,)).fetchone()
        if not row:
            raise ValueError(f"Post {post_id} not found")
        post = dict(row)
        post["plan_data"] = json.loads(post["plan"] or "{}")
        post["idea_brief_data"] = json.loads(post["idea_brief"] or "{}")
        post["attachment_ids"] = json.loads(post["attachments_used"] or "[]")
        post["attachments"] = db.get_assets_by_ids(conn, post["brand_id"], post["attachment_ids"])
    return post


def regenerate_post_idea(post_id: int, on_progress: ProgressFn | None = None) -> None:
    post = _load_post_for_regen(post_id)
    brand, _ = _load_brand_context(post["brand_id"], post["attachment_ids"])
    ctx = _slot_context(post["format"] or "post", post["topic_hint"] or "")
    brief_data = post.get("idea_brief_data") or {}
    audience = brief_data.get("audience", "")
    preset = brief_data.get("preset", "")

    plan, idea_brief = idea_engine.refine(
        brand,
        ctx,
        post["attachments"],
        audience=audience,
        preset=preset,
        on_progress=on_progress,
    )
    caption = captioner.write_caption(brand, plan, post["attachments"], idea_brief=idea_brief)

    with db.db() as conn:
        conn.execute(
            """UPDATE post SET plan=?, idea_brief=?, caption=?, hashtags=?
               WHERE id=?""",
            (
                json.dumps(plan, ensure_ascii=False),
                json.dumps(idea_brief, ensure_ascii=False),
                caption.get("caption", ""),
                caption.get("hashtags", ""),
                post_id,
            ),
        )


def regenerate_post_caption(post_id: int) -> None:
    post = _load_post_for_regen(post_id)
    brand, _ = _load_brand_context(post["brand_id"], post["attachment_ids"])
    caption = captioner.write_caption(
        brand,
        post["plan_data"],
        post["attachments"],
        idea_brief=post.get("idea_brief_data"),
    )
    with db.db() as conn:
        conn.execute(
            "UPDATE post SET caption=?, hashtags=? WHERE id=?",
            (caption.get("caption", ""), caption.get("hashtags", ""), post_id),
        )


def regenerate_post_images(post_id: int, on_progress: ProgressFn | None = None) -> None:
    post = _load_post_for_regen(post_id)
    brand, _ = _load_brand_context(post["brand_id"], post["attachment_ids"])
    fmt = post["format"] or "post"
    count = imager.FORMAT_COUNTS.get(fmt, 1)
    _progress(on_progress, "images", f"Generating {count} more image(s)…")
    images = imager.make_images(
        brand,
        post["plan_data"],
        fmt,
        reference_assets=post["attachments"],
        on_progress=on_progress,
    )
    with db.db() as conn:
        for path in images:
            db.add_post_media(conn, post_id, path, "image", "regenerate", selected=True)
