# Social Media Content Assistant

A small, self-hosted **post bank** for social media. You set up a brand, generate on-brand posts (AI captions + images + video briefs), approve them, then copy the caption and download images when you publish manually.

No scheduling, no auto-posting to Instagram. Runs on a **Linux VPS** with Python, SQLite, Nginx, and Certbot — same pattern as [fay-vpn](https://github.com/fayonation/fay-vpn).

---

## Run on your server

You need: Ubuntu VPS, **Nginx** (or Apache) + Certbot, and a subdomain (e.g. `social.example.com`).

**Not sure what your VPS uses?** Run `./diagnose.sh` first.

**Before you start (Hostinger hPanel DNS):**

- **A record** → your VPS **IPv4**
- **AAAA** → your VPS IPv6 (`ip -6 addr show scope global`) **or delete AAAA**
- Wrong AAAA (Hostinger parking) breaks certbot with **404** on acme-challenge
- Wait 5–30 minutes after DNS changes

**On the VPS:**

1. **System packages** (`python3-venv` is required — without it `setup.sh` cannot create `.venv`)
   ```bash
   apt update
   apt install -y python3 python3-venv python3-pip git curl nginx certbot python3-certbot-nginx
   ```

2. **Clone**
   ```bash
   git clone https://github.com/fayonation/social-media-content-assistant.git
   cd social-media-content-assistant
   ```

3. **Configure**
   ```bash
   cp .env.example .env
   nano .env
   ```

   If `cp` gives an empty `.env` (`.env.example` missing after an old clone), create `.env` yourself:
   ```bash
   nano .env
   ```
   Paste this and edit the two values:
   ```bash
   APP_HOST=your-subdomain.example.com
   PORT=8000
   REPLICATE_API_TOKEN=r8_your_real_token_here
   ```

   - `APP_HOST` — your subdomain (no `https://`)
   - `PORT` — leave `8000` (localhost only; nginx proxies 443 → 8000)
   - `REPLICATE_API_TOKEN` — from [replicate.com/account/api-tokens](https://replicate.com/account/api-tokens)
   - Optional: `REVERSE_PROXY=nginx`

4. **Check port 8000** (should be free — not in your Docker list)
   ```bash
   chmod +x diagnose.sh fix-nginx-before-certbot.sh setup.sh
   ./diagnose.sh
   ss -tlnp | grep 8000
   ```

5. **HTTPS certificate first** (DNS A record → **this VPS** IP, not Hostinger parking page)

   If certbot says **nginx config test failed** (broken SSL vhost from an earlier attempt):
   ```bash
   sudo ./fix-nginx-before-certbot.sh
   ```

   Then:
   ```bash
   sudo certbot certonly --nginx -d YOUR_SUBDOMAIN_HERE
   ```
   Use `--apache` instead of `--nginx` only if `diagnose.sh` shows Apache, not Nginx.

   Alternative if nginx still fails:
   ```bash
   sudo systemctl stop nginx
   sudo certbot certonly --standalone -d YOUR_SUBDOMAIN_HERE
   sudo systemctl start nginx
   ```

6. **Install and start** (run once, **after** certbot — installs app + nginx + systemd)
   ```bash
   sudo ./setup.sh
   ```

7. **Use**
   - Browser: `https://YOUR_SUBDOMAIN_HERE`
   - **Models** (first visit): activate a **text** model and an **image** model
   - Then: **Brands** → **Generate** → elevate idea → generate full post

8. **Logs / restart**
   ```bash
   journalctl -u social-media-content-assistant -f
   sudo systemctl restart social-media-content-assistant
   ```

### Updating the app

```bash
cd social-media-content-assistant
git pull
sudo ./setup.sh
```

(`setup.sh` reinstalls deps and restarts the service.)

### Local development (optional)

```bash
cp config.example.json config.json   # or export REPLICATE_API_TOKEN
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./serve.sh
```

`./serve.sh` uses `--reload`. Open **http://localhost:8000**.

---

## Details

### Ports

| Port | Exposure | Purpose |
|------|----------|---------|
| 8000/tcp | 127.0.0.1 only | FastAPI app (uvicorn) |
| 443/tcp | Public (Nginx) | HTTPS UI at `https://APP_HOST` |

Port **8000** avoids your existing Docker bindings (3001, 3002, 4000, 5432, 8080, …).

### Will this break my other apps?

No — adds one systemd service and one Nginx site. Run certbot **before** `setup.sh`.

### Troubleshooting

| Problem | Fix |
|---------|-----|
| certbot nginx test failed | `sudo ./fix-nginx-before-certbot.sh` |
| certbot unauthorized / 404 | Fix DNS AAAA → VPS IPv6 or remove AAAA |
| Hostinger default page on subdomain | A record must point to VPS, not Hostinger hosting |
| App not responding on 8000 | `journalctl -u social-media-content-assistant -n 50` |
| Generate / elevate hangs behind nginx | SSE timeouts are in `nginx/vhost.conf.template` — re-run `sudo ./setup.sh` |
| Missing Replicate token | Set `REPLICATE_API_TOKEN` in `.env` |

### Deploy files

| File | Purpose |
|------|---------|
| `setup.sh` | Deploy after certbot (venv, systemd, nginx) |
| `fix-nginx-before-certbot.sh` | Repair nginx before certbot |
| `diagnose.sh` | Ports + web server + app check |
| `nginx/vhost.conf.template` | HTTPS reverse proxy to localhost:8000 |
| `.env.example` | `APP_HOST`, `PORT`, `REPLICATE_API_TOKEN` |

Do not commit `.env`, `config.json`, `*.db`, or `media/*`.

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
| `config.json` | Your Replicate API token (or use `REPLICATE_API_TOKEN` env var) |
| `.env` | Same — never commit local env files |
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

`config.json` holds `replicate_api_token` and optional default model slugs. You can also set **`REPLICATE_API_TOKEN`** in the environment (it overrides the config file). Ollama settings are only used when **Ollama (local)** is the active text model.

**Fonts:** `assets/fonts/` ships Noto Sans + Noto Naskh Arabic for Arabic/Latin headline overlays. If missing, `./serve.sh` runs `./scripts/download-fonts.sh` automatically.

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
setup.sh                — Production deploy (after certbot)
fix-nginx-before-certbot.sh — HTTP vhost before certbot
diagnose.sh             — Ports and service check
nginx/vhost.conf.template — HTTPS proxy (SSE-friendly)
media/                  — Generated images and uploaded brand assets
```

### Tech stack

Python 3, FastAPI, Uvicorn, SQLite, Jinja2 templates, vanilla JS (SSE for long-running generation), Replicate API (optional Ollama for text).
