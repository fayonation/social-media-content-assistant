"""Social Media Content Assistant — FastAPI app serving plain HTML pages."""

import asyncio
import json
import os
import queue
import threading

from fastapi import FastAPI, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import db
from config import APP_NAME, BASE_DIR, MEDIA_DIR, new_asset_path, slugify, web_to_fs
from db import ASSET_KINDS
from model_registry import (
    create_model,
    defaults_from_form,
    defaults_from_raw,
    delete_model,
    get_active_id,
    get_model,
    is_ollama_text_active,
    list_models,
    set_active,
    set_active_ollama_text,
    update_model,
    validate_model,
)
from providers.text import ProviderError

app = FastAPI(title=APP_NAME)
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

os.makedirs(MEDIA_DIR, exist_ok=True)
static_dir = os.path.join(BASE_DIR, "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")

db.init_db()


def render(request: Request, template: str, **ctx) -> HTMLResponse:
    return templates.TemplateResponse(
        template,
        {"request": request, "app_name": APP_NAME, **ctx},
    )


POST_SELECT = """
    SELECT p.*, b.name AS brand_name, b.language AS brand_language,
           COALESCE(p.format, s.format, 'post') AS format
    FROM post p
    JOIN brand b ON b.id = p.brand_id
    LEFT JOIN slot s ON s.id = p.slot_id
"""


def _post_view(row, conn=None) -> dict:
    data = dict(row)
    data["brief"] = json.loads(data["video_brief"]) if data.get("video_brief") else None
    data["plan_data"] = json.loads(data["plan"]) if data.get("plan") else None
    data["idea_brief_data"] = json.loads(data["idea_brief"]) if data.get("idea_brief") else None
    data["attachment_ids"] = json.loads(data["attachments_used"] or "[]")
    data["is_posted"] = bool(data.get("posted"))
    if conn:
        data["media_variants"] = db.list_post_media(conn, data["id"])
        data["media_list"] = [m["path"] for m in data["media_variants"] if m["selected"]]
    else:
        data["media_list"] = json.loads(data["media_paths"]) if data.get("media_paths") else []
        data["media_variants"] = []
    return data


def _remove_post_media_files(post: dict) -> None:
    paths = {m["path"] for m in post.get("media_variants") or []}
    paths.update(post.get("media_list") or [])
    for web_path in paths:
        fs_path = web_to_fs(web_path)
        if os.path.exists(fs_path):
            os.remove(fs_path)
    brief = post.get("brief") or {}
    video_path = brief.get("video_path")
    if video_path:
        fs_path = web_to_fs(video_path)
        if os.path.exists(fs_path):
            os.remove(fs_path)


def _load_post_detail(conn, post_id: int) -> dict | None:
    row = conn.execute(f"{POST_SELECT} WHERE p.id=?", (post_id,)).fetchone()
    if not row:
        return None
    post = _post_view(row, conn)
    post["attachments"] = db.get_assets_by_ids(conn, row["brand_id"], post["attachment_ids"])
    return post


def _optional_int(value: str | None) -> int | None:
    if not value or not str(value).strip():
        return None
    return int(value)


def _list_posts(conn, brand_id: int | None, status: str, posted: str) -> list[dict]:
    sql = f"{POST_SELECT} WHERE 1=1"
    params: list = []
    if brand_id:
        sql += " AND p.brand_id=?"
        params.append(brand_id)
    if status and status != "all":
        sql += " AND p.status=?"
        params.append(status)
    else:
        sql += " AND p.status != 'rejected'"
    if posted == "posted":
        sql += " AND p.posted = 1"
    elif posted == "not_posted":
        sql += " AND p.posted = 0"
    sql += " ORDER BY p.created_at DESC"
    rows = conn.execute(sql, params).fetchall()
    return [_post_view(r, conn) for r in rows]


# ----------------------------- Post bank (home) -----------------------------

@app.get("/", response_class=HTMLResponse)
def posts_bank(request: Request, status: str = "", posted: str = ""):
    brand_id = _optional_int(request.query_params.get("brand_id"))
    with db.db() as conn:
        brands = conn.execute("SELECT * FROM brand ORDER BY name").fetchall()
        brand_list = [dict(b) for b in brands]
        posts = _list_posts(conn, brand_id, status, posted)
    return render(
        request,
        "posts.html",
        brands=brand_list,
        posts=posts,
        filters={"brand_id": brand_id, "status": status, "posted": posted},
    )


def _parse_refined_plan(raw: str) -> dict | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        from pipeline.idea_engine import validate_plan

        return validate_plan(json.loads(raw))
    except (json.JSONDecodeError, TypeError):
        return None


def _parse_idea_brief(raw: str) -> dict | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _sse_response(worker) -> StreamingResponse:
    events: queue.Queue = queue.Queue()

    def run() -> None:
        try:
            worker(events)
        except (ProviderError, ValueError) as exc:
            events.put({"type": "error", "message": str(exc)})
        except Exception as exc:
            events.put({"type": "error", "message": str(exc)})
        finally:
            events.put(None)

    threading.Thread(target=run, daemon=True).start()

    async def event_stream():
        while True:
            item = await asyncio.to_thread(events.get)
            if item is None:
                break
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/generate", response_class=HTMLResponse)
def generate_form(request: Request, format: str = "post"):
    from pipeline.presets import preset_choices

    brand_id = _optional_int(request.query_params.get("brand_id"))
    with db.db() as conn:
        brands = conn.execute("SELECT * FROM brand ORDER BY name").fetchall()
        brand_list = [dict(b) for b in brands]
        assets_by_brand = {
            b["id"]: db.list_brand_assets(conn, b["id"]) for b in brand_list
        }
    if brand_id is None and brand_list:
        brand_id = brand_list[0]["id"]
    return render(
        request,
        "generate.html",
        brands=brand_list,
        assets_by_brand=assets_by_brand,
        selected_brand_id=brand_id,
        selected_format=format if format in ("post", "carousel", "video") else "post",
        preset_choices=preset_choices(),
    )


@app.post("/api/elevate-idea")
async def elevate_idea_stream(
    brand_id: int = Form(...),
    format: str = Form("post"),
    topic_hint: str = Form(""),
    audience: str = Form(""),
    preset: str = Form(""),
    asset_ids: list[int] = Form(default=[]),
):
    from pipeline.generate import elevate_idea

    def worker(events: queue.Queue) -> None:
        def on_progress(step: str, detail: str) -> None:
            events.put({"type": "progress", "step": step, "detail": detail})

        def on_step(step: str, data: dict) -> None:
            events.put({"type": "step_done", "step": step, **data})

        plan, idea_brief = elevate_idea(
            brand_id,
            format,
            topic_hint,
            asset_ids,
            audience=audience,
            preset=preset,
            on_progress=on_progress,
            on_step=on_step,
        )
        events.put({"type": "done", "plan": plan, "idea_brief": idea_brief})

    return _sse_response(worker)


@app.post("/api/idea-step")
async def idea_step_stream(
    brand_id: int = Form(...),
    format: str = Form("post"),
    topic_hint: str = Form(""),
    audience: str = Form(""),
    preset: str = Form(""),
    asset_ids: list[int] = Form(default=[]),
    from_step: str = Form(...),
    idea_state: str = Form("{}"),
):
    from pipeline.generate import run_idea_step

    try:
        state = json.loads(idea_state or "{}")
        if not isinstance(state, dict):
            state = {}
    except json.JSONDecodeError:
        state = {}

    allowed = {"diverge", "critique", "polish", "anchor"}
    if from_step not in allowed:
        raise ValueError(f"from_step must be one of: {', '.join(sorted(allowed))}")

    def worker(events: queue.Queue) -> None:
        def on_progress(step: str, detail: str) -> None:
            events.put({"type": "progress", "step": step, "detail": detail})

        def on_step(step: str, data: dict) -> None:
            events.put({"type": "step_done", "step": step, **data})

        plan, idea_brief = run_idea_step(
            brand_id,
            format,
            topic_hint,
            asset_ids,
            audience=audience,
            preset=preset,
            from_step=from_step,
            state=state,
            on_progress=on_progress,
            on_step=on_step,
        )
        events.put({"type": "done", "plan": plan, "idea_brief": idea_brief})

    return _sse_response(worker)


@app.post("/api/generate")
async def generate_stream(
    brand_id: int = Form(...),
    format: str = Form("post"),
    topic_hint: str = Form(""),
    audience: str = Form(""),
    preset: str = Form(""),
    asset_ids: list[int] = Form(default=[]),
    refined_plan: str = Form(""),
    idea_brief: str = Form(""),
):
    from pipeline.generate import generate_for_brand

    plan = _parse_refined_plan(refined_plan)
    brief = _parse_idea_brief(idea_brief)

    def worker(events: queue.Queue) -> None:
        def on_progress(step: str, detail: str) -> None:
            events.put({"type": "progress", "step": step, "detail": detail})

        post_id = generate_for_brand(
            brand_id,
            format,
            topic_hint,
            asset_ids,
            on_progress=on_progress,
            audience=audience,
            preset=preset,
            refined_plan=plan,
            idea_brief=brief,
        )
        events.put({"type": "done", "post_id": post_id})

    return _sse_response(worker)


# ----------------------------- Brands -----------------------------

@app.get("/brands", response_class=HTMLResponse)
def brands_index(request: Request):
    with db.db() as conn:
        brands = conn.execute("SELECT * FROM brand ORDER BY created_at DESC").fetchall()
    return render(request, "brands.html", brands=brands)


@app.get("/brands/new", response_class=HTMLResponse)
def brand_new_form(request: Request):
    return render(request, "brand_form.html", brand=None)


@app.post("/brands/new")
async def brand_create(
    name: str = Form(...),
    language: str = Form("en"),
    visual_style: str = Form(""),
    voice_tone: str = Form(""),
    hashtags: str = Form(""),
    forbidden_seeds: str = Form(""),
    identity_context: str = Form(""),
):
    with db.db() as conn:
        conn.execute(
            """INSERT INTO brand (name, language, visual_style, voice_tone,
                                  hashtags, forbidden_seeds, identity_context)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (name, language, visual_style, voice_tone, hashtags, forbidden_seeds, identity_context),
        )
    return RedirectResponse("/brands", status_code=303)


@app.get("/brands/{brand_id}", response_class=HTMLResponse)
def brand_hub(request: Request, brand_id: int):
    with db.db() as conn:
        brand = db.get_brand(conn, brand_id)
        if not brand:
            return RedirectResponse("/brands", status_code=303)
        assets = db.list_brand_assets(conn, brand_id)
    return render(request, "brand_hub.html", brand=dict(brand), assets=assets, asset_kinds=ASSET_KINDS)


@app.get("/brands/{brand_id}/edit", response_class=HTMLResponse)
def brand_edit_form(request: Request, brand_id: int):
    with db.db() as conn:
        brand = db.get_brand(conn, brand_id)
        if not brand:
            return RedirectResponse("/brands", status_code=303)
    return render(request, "brand_form.html", brand=dict(brand))


@app.post("/brands/{brand_id}/edit")
def brand_update(
    brand_id: int,
    name: str = Form(...),
    language: str = Form("en"),
    visual_style: str = Form(""),
    voice_tone: str = Form(""),
    hashtags: str = Form(""),
    forbidden_seeds: str = Form(""),
    identity_context: str = Form(""),
):
    with db.db() as conn:
        conn.execute(
            """UPDATE brand SET name=?, language=?, visual_style=?, voice_tone=?,
               hashtags=?, forbidden_seeds=?, identity_context=? WHERE id=?""",
            (name, language, visual_style, voice_tone, hashtags, forbidden_seeds, identity_context, brand_id),
        )
    return RedirectResponse(f"/brands/{brand_id}", status_code=303)


@app.post("/brands/{brand_id}/assets")
async def brand_asset_upload(
    brand_id: int,
    kind: str = Form("other"),
    label: str = Form(...),
    description: str = Form(""),
    file: UploadFile = Form(...),
):
    if kind not in ASSET_KINDS:
        kind = "other"
    with db.db() as conn:
        brand = db.get_brand(conn, brand_id)
        if not brand:
            return RedirectResponse("/brands", status_code=303)
        slug = slugify(brand["name"])
        ext = (file.filename.rsplit(".", 1)[-1] or "png").lower() if file.filename else "png"
        fs_path, web_path = new_asset_path(slug, ext)
        with open(fs_path, "wb") as f:
            f.write(await file.read())
        conn.execute(
            """INSERT INTO brand_asset (brand_id, kind, label, description, file_path)
               VALUES (?, ?, ?, ?, ?)""",
            (brand_id, kind, label, description or None, web_path),
        )
    return RedirectResponse(f"/brands/{brand_id}", status_code=303)


@app.post("/brands/{brand_id}/assets/{asset_id}/delete")
def brand_asset_delete(brand_id: int, asset_id: int):
    with db.db() as conn:
        row = conn.execute(
            "SELECT file_path FROM brand_asset WHERE id=? AND brand_id=?",
            (asset_id, brand_id),
        ).fetchone()
        if row:
            fs_path = web_to_fs(row["file_path"])
            if os.path.exists(fs_path):
                os.remove(fs_path)
            conn.execute("DELETE FROM brand_asset WHERE id=? AND brand_id=?", (asset_id, brand_id))
    return RedirectResponse(f"/brands/{brand_id}", status_code=303)


# ----------------------------- Legacy redirects -----------------------------

@app.get("/brands/{brand_id}/schedule")
def schedule_redirect(brand_id: int):
    return RedirectResponse(f"/generate?brand_id={brand_id}", status_code=303)


@app.get("/review")
def review_redirect():
    return RedirectResponse("/?status=draft", status_code=303)


@app.get("/calendar")
def calendar_redirect():
    return RedirectResponse("/", status_code=303)


# ----------------------------- Post detail -----------------------------

@app.get("/posts/{post_id}", response_class=HTMLResponse)
def post_detail(request: Request, post_id: int):
    with db.db() as conn:
        post = _load_post_detail(conn, post_id)
    if not post:
        return RedirectResponse("/", status_code=303)
    caption_copy = post["caption"] or ""
    if post.get("hashtags"):
        caption_copy = f"{caption_copy}\n\n{post['hashtags']}".strip()
    return render(request, "post_detail.html", post=post, caption_copy=caption_copy)


@app.get("/posts/{post_id}/download/{index}")
def post_download(post_id: int, index: int):
    with db.db() as conn:
        post = _load_post_detail(conn, post_id)
    if not post or index < 0 or index >= len(post["media_list"]):
        return RedirectResponse("/", status_code=303)
    web_path = post["media_list"][index]
    fs_path = web_to_fs(web_path)
    if not os.path.exists(fs_path):
        return RedirectResponse(f"/posts/{post_id}", status_code=303)
    filename = os.path.basename(fs_path)
    return FileResponse(fs_path, filename=filename, media_type="application/octet-stream")


@app.get("/posts/{post_id}/download-media/{media_id}")
def post_download_media(post_id: int, media_id: int):
    with db.db() as conn:
        row = conn.execute(
            "SELECT path FROM post_media WHERE id=? AND post_id=?",
            (media_id, post_id),
        ).fetchone()
    if not row:
        return RedirectResponse(f"/posts/{post_id}", status_code=303)
    fs_path = web_to_fs(row["path"])
    if not os.path.exists(fs_path):
        return RedirectResponse(f"/posts/{post_id}", status_code=303)
    return FileResponse(
        fs_path,
        filename=os.path.basename(fs_path),
        media_type="application/octet-stream",
    )


@app.get("/posts/{post_id}/download-video")
def post_download_video(post_id: int):
    with db.db() as conn:
        post = _load_post_detail(conn, post_id)
    if not post or not post.get("brief") or not post["brief"].get("video_path"):
        return RedirectResponse(f"/posts/{post_id}", status_code=303)
    fs_path = web_to_fs(post["brief"]["video_path"])
    if not os.path.exists(fs_path):
        return RedirectResponse(f"/posts/{post_id}", status_code=303)
    return FileResponse(fs_path, filename=os.path.basename(fs_path), media_type="video/mp4")


@app.post("/posts/{post_id}/approve")
def post_approve(post_id: int, next: str = Form("")):
    from pipeline.memory import record_post

    with db.db() as conn:
        conn.execute("UPDATE post SET status='approved' WHERE id=?", (post_id,))
    record_post(post_id)
    if next == "detail":
        return RedirectResponse(f"/posts/{post_id}", status_code=303)
    return RedirectResponse("/", status_code=303)


@app.post("/posts/{post_id}/reject")
def post_reject(post_id: int):
    with db.db() as conn:
        conn.execute("UPDATE post SET status='rejected' WHERE id=?", (post_id,))
    return RedirectResponse("/", status_code=303)


@app.post("/posts/{post_id}/mark-posted")
def post_mark_posted(post_id: int):
    with db.db() as conn:
        post = conn.execute("SELECT status FROM post WHERE id=?", (post_id,)).fetchone()
        if not post or post["status"] != "approved":
            return RedirectResponse(f"/posts/{post_id}", status_code=303)
        conn.execute(
            "UPDATE post SET posted=1, posted_at=datetime('now') WHERE id=?",
            (post_id,),
        )
    return RedirectResponse(f"/posts/{post_id}", status_code=303)


@app.post("/posts/{post_id}/unmark-posted")
def post_unmark_posted(post_id: int):
    with db.db() as conn:
        conn.execute("UPDATE post SET posted=0, posted_at=NULL WHERE id=?", (post_id,))
    return RedirectResponse(f"/posts/{post_id}", status_code=303)


@app.post("/posts/{post_id}/edit")
def post_edit(post_id: int, caption: str = Form(""), hashtags: str = Form(""), next: str = Form("")):
    with db.db() as conn:
        conn.execute(
            "UPDATE post SET caption=?, hashtags=? WHERE id=?", (caption, hashtags, post_id)
        )
    if next == "detail":
        return RedirectResponse(f"/posts/{post_id}", status_code=303)
    return RedirectResponse("/", status_code=303)


@app.post("/posts/{post_id}/delete")
def post_delete(post_id: int):
    with db.db() as conn:
        post = _load_post_detail(conn, post_id)
        if post:
            _remove_post_media_files(post)
            db.delete_all_post_media(conn, post_id)
            conn.execute("DELETE FROM post WHERE id=?", (post_id,))
    return RedirectResponse("/", status_code=303)


@app.post("/posts/{post_id}/media/select")
def post_media_select(post_id: int, media_ids: list[int] = Form(default=[])):
    with db.db() as conn:
        if not conn.execute("SELECT 1 FROM post WHERE id=?", (post_id,)).fetchone():
            return RedirectResponse("/", status_code=303)
        db.set_media_selection(conn, post_id, media_ids)
    return RedirectResponse(f"/posts/{post_id}", status_code=303)


@app.post("/posts/{post_id}/media/{media_id}/delete")
def post_media_variant_delete(post_id: int, media_id: int):
    with db.db() as conn:
        row = conn.execute(
            "SELECT post_id, path FROM post_media WHERE id=? AND post_id=?",
            (media_id, post_id),
        ).fetchone()
        if row:
            fs_path = web_to_fs(row["path"])
            if os.path.exists(fs_path):
                os.remove(fs_path)
            db.delete_post_media(conn, media_id)
    return RedirectResponse(f"/posts/{post_id}", status_code=303)


@app.post("/posts/{post_id}/regenerate-idea")
def post_regenerate_idea(post_id: int):
    from pipeline.generate import regenerate_post_idea

    try:
        regenerate_post_idea(post_id)
    except (ProviderError, ValueError, RuntimeError):
        pass
    return RedirectResponse(f"/posts/{post_id}", status_code=303)


@app.post("/posts/{post_id}/regenerate-caption")
def post_regenerate_caption(post_id: int):
    from pipeline.generate import regenerate_post_caption

    try:
        regenerate_post_caption(post_id)
    except (ProviderError, ValueError, RuntimeError):
        pass
    return RedirectResponse(f"/posts/{post_id}", status_code=303)


@app.post("/posts/{post_id}/regenerate-images")
def post_regenerate_images(post_id: int):
    from pipeline.generate import regenerate_post_images

    try:
        regenerate_post_images(post_id)
    except (ProviderError, ValueError, RuntimeError):
        pass
    return RedirectResponse(f"/posts/{post_id}", status_code=303)


# ----------------------------- Replicate models -----------------------------

def _parse_defaults(input_mode: str, defaults_json: str, field_keys: list[str], field_values: list[str]) -> dict:
    if input_mode == "json":
        return defaults_from_raw(defaults_json)
    return defaults_from_form(field_keys, field_values)


@app.get("/models", response_class=HTMLResponse)
def models_index(request: Request):
    image_models = list_models("image")
    video_models = list_models("video")
    text_models = list_models("text")
    active_image = get_active_id("image")
    active_video = get_active_id("video")
    active_text = get_active_id("text")
    return render(
        request,
        "models.html",
        image_models=image_models,
        video_models=video_models,
        text_models=text_models,
        active_image=active_image,
        active_video=active_video,
        active_text=active_text,
        ollama_text_active=is_ollama_text_active(),
    )


@app.get("/models/new", response_class=HTMLResponse)
def model_new_form(request: Request, kind: str = "image"):
    return render(request, "model_form.html", kind=kind, model=None, validation=None)


@app.post("/models/check", response_class=HTMLResponse)
def model_check(
    request: Request,
    kind: str = Form("image"),
    slug_or_url: str = Form(...),
    label: str = Form(""),
    input_mode: str = Form("fields"),
    defaults_json: str = Form(""),
    field_key: list[str] = Form([]),
    field_value: list[str] = Form([]),
):
    try:
        validation = validate_model(slug_or_url)
        defaults = _parse_defaults(input_mode, defaults_json, field_key, field_value)
        validation["defaults_preview"] = defaults
        validation["ok"] = True
        message = f"Model OK: {validation['slug']}"
    except ProviderError as exc:
        validation = {"ok": False, "error": str(exc)}
        message = str(exc)
    return render(
        request,
        "model_form.html",
        kind=kind,
        model=None,
        validation=validation,
        form={
            "slug_or_url": slug_or_url,
            "label": label,
            "input_mode": input_mode,
            "defaults_json": defaults_json,
            "field_keys": field_key,
            "field_values": field_value,
        },
        message=message,
    )


@app.post("/models/new")
def model_create(
    request: Request,
    kind: str = Form("image"),
    slug_or_url: str = Form(...),
    label: str = Form(""),
    input_mode: str = Form("fields"),
    defaults_json: str = Form(""),
    field_key: list[str] = Form([]),
    field_value: list[str] = Form([]),
):
    try:
        validation = validate_model(slug_or_url)
        defaults = _parse_defaults(input_mode, defaults_json, field_key, field_value)
        create_model(kind, slug_or_url, label, defaults, validated=validation)
    except ProviderError as exc:
        return render(
            request,
            "model_form.html",
            kind=kind,
            model=None,
            validation={"ok": False, "error": str(exc)},
            form={
                "slug_or_url": slug_or_url,
                "label": label,
                "input_mode": input_mode,
                "defaults_json": defaults_json,
                "field_keys": field_key,
                "field_values": field_value,
            },
            message=str(exc),
        )
    return RedirectResponse("/models", status_code=303)


@app.get("/models/{model_id}/edit", response_class=HTMLResponse)
def model_edit_form(request: Request, model_id: int):
    model = get_model(model_id)
    if not model:
        return RedirectResponse("/models", status_code=303)
    return render(request, "model_form.html", kind=model["kind"], model=model, validation=None)


@app.post("/models/{model_id}/edit")
def model_edit(
    model_id: int,
    label: str = Form(""),
    input_mode: str = Form("fields"),
    defaults_json: str = Form(""),
    field_key: list[str] = Form([]),
    field_value: list[str] = Form([]),
):
    try:
        defaults = _parse_defaults(input_mode, defaults_json, field_key, field_value)
        update_model(model_id, label, defaults)
    except ProviderError:
        return RedirectResponse(f"/models/{model_id}/edit", status_code=303)
    return RedirectResponse("/models", status_code=303)


@app.post("/models/{model_id}/activate")
def model_activate(model_id: int):
    try:
        set_active(model_id)
    except ProviderError as exc:
        return RedirectResponse(f"/models?error={exc}", status_code=303)
    return RedirectResponse("/models", status_code=303)


@app.post("/models/use-ollama-text")
def model_activate_ollama_text():
    set_active_ollama_text()
    return RedirectResponse("/models", status_code=303)


@app.post("/models/{model_id}/delete")
def model_delete(model_id: int):
    delete_model(model_id)
    return RedirectResponse("/models", status_code=303)
