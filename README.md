# Social Media Content Assistant

A small, self-hosted **post bank** for social media (internal codename: Social Studio). You set up a brand, generate on-brand posts (AI captions + images + video briefs), approve them, then copy the caption and download images when you publish manually.

No scheduling, no auto-posting to Instagram, no Docker. Just Python, a local database (SQLite), and a web page in your browser.

---

## How to run the project (step by step)

Follow these steps **in order**. You only do the **one-time setup** once. After that, jump to **“Every time you want to use the app”**.

### What you need first

1. **A Mac or Linux computer** (these instructions use the Terminal app).
2. **Python 3** — on Mac, open Terminal and type `python3 --version`. You should see something like `Python 3.12`. If not, install Python from [python.org](https://www.python.org/downloads/).
3. **A Replicate account** — sign up at [replicate.com](https://replicate.com), then create an API token at [replicate.com/account/api-tokens](https://replicate.com/account/api-tokens). It looks like `r8_...`. You will paste this into a config file below.

### One-time setup

**Step 1 — Open Terminal**

- **Mac:** press `Cmd + Space`, type `Terminal`, press Enter.
- A window with a command prompt appears. That is where you type the commands below (one line at a time, then press Enter).

**Step 2 — Go to the project folder**

Replace the path below with wherever you cloned this repo (folder name is usually `social-media-content-assistant`):

```bash
cd path/to/social-media-content-assistant
```

**Step 3 — Create your config file**

```bash
cp config.example.json config.json
```

**Step 4 — Add your Replicate API token**

Open `config.json` in any text editor (TextEdit, VS Code, etc.). Find this line:

```json
"replicate_api_token": "r8_paste_your_token_here",
```

Replace `r8_paste_your_token_here` with your real token. Save the file.

**Step 5 — Create a Python environment and install dependencies**

Copy and paste these two commands, one after the other:

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

Wait until the second command finishes (no errors).

**Step 6 — Start the app**

```bash
./serve.sh
```

You should see something like:

```text
Uvicorn running on http://127.0.0.1:8000
```

**Step 7 — Open the app in your browser**

Go to: **http://localhost:8000**

**Step 8 — Turn on AI models (required before generating posts)**

1. In the app, click **Models** in the top menu.
2. Activate a **text** model (for ideas and captions) — click **Use this** on one Replicate LLM.
3. Activate an **image** model the same way.
4. (Optional) Activate a **video** model if you plan to generate video briefs.

Ollama (local AI on your machine) is optional — only use it if you explicitly choose **Ollama (local)** on the Models page.

---

### Every time you want to use the app

1. Open **Terminal**.
2. Go to the project folder:

   ```bash
   cd path/to/social-media-content-assistant
   ```

3. Start the server:

   ```bash
   ./serve.sh
   ```

4. Open **http://localhost:8000** in your browser.

**To stop the server:** click the Terminal window and press `Ctrl + C`.

**Different port** (if 8000 is busy):

```bash
PORT=3000 ./serve.sh
```

Then open **http://localhost:3000** instead.

---

### First-time usage (after the app is running)

1. **Brands** → create a brand (name, language, identity paragraph, voice, visual style).
2. Open the brand → upload logos, product photos, characters (optional but helps the AI).
3. **Generate** → pick brand, enter a **seed idea**, click **Elevate idea** to refine it, then **Generate full post**.
4. Open the new post → pick images from the media pool if needed → **Approve**.
5. When you publish on Instagram (or elsewhere) manually → **Copy caption**, **Download** images, then **Mark posted**.

---

## Git repo — what never goes in git

These stay **on your machine only** (already listed in `.gitignore`):

| Ignored | Why |
|---------|-----|
| `config.json` | Your Replicate API token |
| `*.db` | SQLite database (brands, posts, models you configured) |
| `media/*` | AI-generated images and brand uploads |
| `.venv/` | Python packages (reinstall with `pip install -r requirements.txt`) |

After cloning on a new machine: copy `config.example.json` → `config.json`, add your token, run `./serve.sh`.

**Before pushing**, run:

```bash
git status
```

You should **not** see `config.json`, `social_studio.db`, or files under `media/` (except `media/.gitkeep`).

If a secret or image was committed by mistake, rotate your Replicate token and remove it from git history before pushing again.

---

## For developers and AI agents

### What this app does (workflow)

```text
Brand hub → Seed idea → Elevate (idea pipeline) → Generate full post → Draft
  → Pick media from pool → Approve → Copy / Download → Mark posted
```

- **Idea engine** (`pipeline/idea_engine.py`): `diverge → critique → polish → anchor` turns a seed into a production-ready concept.
- **Elevate** on `/generate` runs the pipeline with a **timeline UI** — see all 8 brainstormed concepts, critique scores, winner, polish brief, and anchor check. Edit any step and regenerate from that point (`POST /api/idea-step`).
- **Media pool**: regenerating images **appends** variants; post detail uses checkboxes to select which files are included.
- **Split regenerate** on drafts: re-run idea, caption, or images independently without throwing away the whole post.

### Pages and routes

| URL | Page | Purpose |
|-----|------|---------|
| `/` | **Post bank** | List all posts. Filter by brand, status (draft / approved / rejected), posted (yes / no). |
| `/generate` | **Generate** | Create new content. Seed idea, optional audience/preset, attach brand assets. **Elevate idea** (SSE `/api/elevate-idea`) or **Generate full post** (SSE `/api/generate`). Timeline shows pipeline steps and editable intermediate results. |
| `/posts/{id}` | **Post detail** | View/edit caption, media pool (select variants), idea trace, approve/reject, copy caption, download images/video, mark posted, delete post, split regenerate (idea / caption / images). |
| `/brands` | **Brands list** | All brands; link to create or open each brand. |
| `/brands/new` | **New brand** | Create brand form. |
| `/brands/{id}` | **Brand hub** | Brand assets (upload images with labels/descriptions), link to edit brand or generate for this brand. |
| `/brands/{id}/edit` | **Edit brand** | Identity paragraph, voice, visual style, language. |
| `/models` | **Models** | Manage Replicate text/image/video models; activate which model is used for each task. Optional Ollama text mode. |
| `/models/new`, `/models/{id}/edit` | **Model forms** | Add or edit a model entry (slug, defaults, schema). |
| `/review` | Redirect | → `/?status=draft` |
| `/calendar`, `/brands/{id}/schedule` | Redirect | → post bank or generate (legacy URLs) |

### API endpoints (SSE and actions)

| Endpoint | Method | Role |
|----------|--------|------|
| `/api/elevate-idea` | POST | Full idea pipeline from seed; streams `progress`, `step_done`, `done`. |
| `/api/idea-step` | POST | Re-run from `diverge`, `critique`, `polish`, or `anchor` with client-edited `idea_state` JSON. |
| `/api/generate` | POST | Full post generation (uses optional `refined_plan` + `idea_brief` from elevate). |
| `/posts/{id}/regenerate-idea` | POST | Re-run idea engine on existing draft. |
| `/posts/{id}/regenerate-caption` | POST | Re-write caption only. |
| `/posts/{id}/regenerate-images` | POST | Generate more images (appended to media pool). |
| `/posts/{id}/media/select` | POST | Set which media files are selected for the post. |

### Features summary

- **Brands** with identity context always injected into prompts.
- **Brand assets** as optional reference images for generation.
- **Post formats:** single post (1 image), carousel (3 images), video (2 keyframes + scene brief).
- **Campaign presets** and optional **audience** field on generate.
- **Post statuses:** draft → approved / rejected; **posted** flag for manual publishing tracking.
- **Idea brief** stored on each post for traceability (seed, concepts, critique, winner, polish, anchor).
- **Models UI** — no hard dependency on Ollama; Replicate is the default path.
- **Delete posts** and clean up associated media files.

### AI providers

| Kind | Used for | Default |
|------|----------|---------|
| **Text** | Idea engine, captions, video brief | Active model on `/models` (Replicate LLM) |
| **Image** | Post/carousel visuals | Active image model on `/models` |
| **Video** | Clip generation | Active video model on `/models` |

`config.json` holds `replicate_api_token` and optional default model slugs. Ollama settings are only used when **Ollama (local)** is the active text model.

### Project layout (key files)

```text
app.py                  — FastAPI routes, SSE helpers
db.py                   — SQLite schema, post_media, migrations
config.py / config.json — App configuration (token, model defaults)
model_registry.py       — Active text/image/video model selection
pipeline/
  idea_engine.py        — 4-pass idea refinement + run_from_step
  generate.py           — Orchestration, elevate, split regenerate
  captioner.py          — Caption + hashtags
  imager.py             — Image generation via Replicate
  videobrief.py         — Video keyframes + brief
  presets.py            — Campaign preset prompts
  brand_context.py      — Brand + asset context for prompts
providers/
  text.py               — Text LLM (Replicate or Ollama)
  image.py / video.py   — Replicate image/video
templates/              — Jinja HTML pages
static/                 — CSS, generate.js (timeline + SSE), posts.js
serve.sh                — Start dev server (uvicorn --reload)
media/                  — Generated images and uploaded brand assets
```

### Tech stack

Python 3, FastAPI, Uvicorn, SQLite, Jinja2 templates, vanilla JS (SSE for long-running generation), Replicate API (optional Ollama for text).
