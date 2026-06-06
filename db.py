"""SQLite storage. Single file DB, stdlib only.

JSON-shaped columns (media_paths, video_brief, keywords) are stored as TEXT
and (de)serialized by callers via json.dumps / json.loads.
"""

import json
import os
import sqlite3
from contextlib import contextmanager

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "social_studio.db")

ASSET_KINDS = ("logo", "symbol", "character", "product", "other")

SCHEMA = """
CREATE TABLE IF NOT EXISTS brand (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'en',
    logo_path TEXT,
    visual_style TEXT,
    voice_tone TEXT,
    hashtags TEXT,
    forbidden_seeds TEXT,
    identity_context TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS brand_asset (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand_id INTEGER NOT NULL REFERENCES brand(id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'other',
    label TEXT NOT NULL,
    description TEXT,
    file_path TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS slot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand_id INTEGER NOT NULL REFERENCES brand(id) ON DELETE CASCADE,
    scheduled_at TEXT NOT NULL,
    format TEXT NOT NULL DEFAULT 'post',
    topic_hint TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS post (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slot_id INTEGER REFERENCES slot(id) ON DELETE SET NULL,
    brand_id INTEGER NOT NULL REFERENCES brand(id) ON DELETE CASCADE,
    format TEXT NOT NULL DEFAULT 'post',
    topic_hint TEXT,
    caption TEXT,
    hashtags TEXT,
    media_paths TEXT,
    video_brief TEXT,
    plan TEXT,
    attachments_used TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    posted INTEGER NOT NULL DEFAULT 0,
    posted_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS creative_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand_id INTEGER NOT NULL REFERENCES brand(id) ON DELETE CASCADE,
    topic TEXT,
    hook TEXT,
    visual_style TEXT,
    cta TEXT,
    keywords TEXT,
    post_id INTEGER REFERENCES post(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS replicate_model (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    slug TEXT NOT NULL,
    label TEXT,
    defaults TEXT NOT NULL DEFAULT '{}',
    validated_at TEXT,
    schema_summary TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(kind, slug)
);

CREATE TABLE IF NOT EXISTS app_setting (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS post_media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL REFERENCES post(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'image',
    source TEXT NOT NULL DEFAULT 'generate',
    selected INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def _migrate(conn: sqlite3.Connection) -> None:
    if not _column_exists(conn, "brand", "identity_context"):
        conn.execute("ALTER TABLE brand ADD COLUMN identity_context TEXT")
    if not _column_exists(conn, "post", "attachments_used"):
        conn.execute("ALTER TABLE post ADD COLUMN attachments_used TEXT")
    if not _column_exists(conn, "post", "format"):
        conn.execute("ALTER TABLE post ADD COLUMN format TEXT NOT NULL DEFAULT 'post'")
    if not _column_exists(conn, "post", "topic_hint"):
        conn.execute("ALTER TABLE post ADD COLUMN topic_hint TEXT")
    if not _column_exists(conn, "post", "posted"):
        conn.execute("ALTER TABLE post ADD COLUMN posted INTEGER NOT NULL DEFAULT 0")
    if not _column_exists(conn, "post", "posted_at"):
        conn.execute("ALTER TABLE post ADD COLUMN posted_at TEXT")
    if not _column_exists(conn, "post", "idea_brief"):
        conn.execute("ALTER TABLE post ADD COLUMN idea_brief TEXT")

    conn.execute(
        """CREATE TABLE IF NOT EXISTS post_media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL REFERENCES post(id) ON DELETE CASCADE,
            path TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'image',
            source TEXT NOT NULL DEFAULT 'generate',
            selected INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )"""
    )

    _backfill_post_media(conn)

    # Backfill format/topic_hint from linked slots
    conn.execute(
        """UPDATE post SET format = (
               SELECT s.format FROM slot s WHERE s.id = post.slot_id
           ), topic_hint = (
               SELECT s.topic_hint FROM slot s WHERE s.id = post.slot_id
           )
           WHERE slot_id IS NOT NULL AND (format IS NULL OR format = 'post')"""
    )

    # Migrate legacy logo_path into brand_asset (once per brand)
    brands = conn.execute(
        "SELECT id, logo_path FROM brand WHERE logo_path IS NOT NULL AND logo_path != ''"
    ).fetchall()
    for brand in brands:
        exists = conn.execute(
            "SELECT 1 FROM brand_asset WHERE brand_id=? AND kind='logo' LIMIT 1",
            (brand["id"],),
        ).fetchone()
        if not exists:
            conn.execute(
                """INSERT INTO brand_asset (brand_id, kind, label, description, file_path)
                   VALUES (?, 'logo', 'Logo', NULL, ?)""",
                (brand["id"], brand["logo_path"]),
            )


def get_brand(conn: sqlite3.Connection, brand_id: int):
    return conn.execute("SELECT * FROM brand WHERE id=?", (brand_id,)).fetchone()


def list_brand_assets(conn: sqlite3.Connection, brand_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM brand_asset WHERE brand_id=? ORDER BY created_at",
        (brand_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _backfill_post_media(conn: sqlite3.Connection) -> None:
    """Migrate legacy post.media_paths JSON into post_media rows (once)."""
    posts = conn.execute(
        "SELECT id, media_paths FROM post WHERE media_paths IS NOT NULL AND media_paths != ''"
    ).fetchall()
    for post in posts:
        has_rows = conn.execute(
            "SELECT 1 FROM post_media WHERE post_id=? LIMIT 1", (post["id"],)
        ).fetchone()
        if has_rows:
            continue
        try:
            paths = json.loads(post["media_paths"])
        except json.JSONDecodeError:
            continue
        if not isinstance(paths, list):
            continue
        for path in paths:
            if path:
                add_post_media(conn, post["id"], path, "image", "generate", selected=True)


def list_post_media(conn: sqlite3.Connection, post_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM post_media WHERE post_id=? ORDER BY created_at, id",
        (post_id,),
    ).fetchall()
    return [_media_row(r) for r in rows]


def _media_row(row) -> dict:
    data = dict(row)
    data["selected"] = bool(data.get("selected"))
    return data


def add_post_media(
    conn: sqlite3.Connection,
    post_id: int,
    path: str,
    kind: str = "image",
    source: str = "generate",
    *,
    selected: bool = True,
) -> int:
    cur = conn.execute(
        """INSERT INTO post_media (post_id, path, kind, source, selected)
           VALUES (?, ?, ?, ?, ?)""",
        (post_id, path, kind, source, 1 if selected else 0),
    )
    sync_media_paths_cache(conn, post_id)
    return cur.lastrowid


def set_media_selected(conn: sqlite3.Connection, media_id: int, selected: bool) -> None:
    row = conn.execute("SELECT post_id FROM post_media WHERE id=?", (media_id,)).fetchone()
    if not row:
        return
    conn.execute(
        "UPDATE post_media SET selected=? WHERE id=?",
        (1 if selected else 0, media_id),
    )
    sync_media_paths_cache(conn, row["post_id"])


def set_media_selection(
    conn: sqlite3.Connection, post_id: int, selected_ids: list[int]
) -> None:
    selected_set = {int(i) for i in selected_ids}
    rows = conn.execute("SELECT id FROM post_media WHERE post_id=?", (post_id,)).fetchall()
    for row in rows:
        conn.execute(
            "UPDATE post_media SET selected=? WHERE id=?",
            (1 if row["id"] in selected_set else 0, row["id"]),
        )
    sync_media_paths_cache(conn, post_id)


def selected_media_paths(conn: sqlite3.Connection, post_id: int) -> list[str]:
    rows = conn.execute(
        """SELECT path FROM post_media
           WHERE post_id=? AND selected=1
           ORDER BY created_at, id""",
        (post_id,),
    ).fetchall()
    return [r["path"] for r in rows]


def sync_media_paths_cache(conn: sqlite3.Connection, post_id: int) -> None:
    paths = selected_media_paths(conn, post_id)
    conn.execute(
        "UPDATE post SET media_paths=? WHERE id=?",
        (json.dumps(paths, ensure_ascii=False), post_id),
    )


def get_post_media(conn: sqlite3.Connection, media_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM post_media WHERE id=?", (media_id,)).fetchone()
    return _media_row(row) if row else None


def delete_post_media(conn: sqlite3.Connection, media_id: int) -> str | None:
    row = conn.execute("SELECT post_id, path FROM post_media WHERE id=?", (media_id,)).fetchone()
    if not row:
        return None
    conn.execute("DELETE FROM post_media WHERE id=?", (media_id,))
    sync_media_paths_cache(conn, row["post_id"])
    return row["path"]


def delete_all_post_media(conn: sqlite3.Connection, post_id: int) -> list[str]:
    rows = conn.execute("SELECT path FROM post_media WHERE post_id=?", (post_id,)).fetchall()
    paths = [r["path"] for r in rows]
    conn.execute("DELETE FROM post_media WHERE post_id=?", (post_id,))
    conn.execute("UPDATE post SET media_paths=NULL WHERE id=?", (post_id,))
    return paths


def get_assets_by_ids(conn: sqlite3.Connection, brand_id: int, asset_ids: list[int]) -> list[dict]:
    if not asset_ids:
        return []
    placeholders = ",".join("?" * len(asset_ids))
    rows = conn.execute(
        f"""SELECT * FROM brand_asset
            WHERE brand_id=? AND id IN ({placeholders})
            ORDER BY id""",
        [brand_id, *asset_ids],
    ).fetchall()
    return [dict(r) for r in rows]


def init_db() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
    from model_registry import seed_from_config

    seed_from_config()
