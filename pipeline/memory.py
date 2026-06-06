"""Anti-repetition engine.

- avoid_context(): a text block of what a brand has already done, fed to the planner.
- is_duplicate(): cheap similarity gate (difflib + keyword overlap), no embeddings.
- record_post(): on approval, log the post's plan so it is never repeated.
"""

import json
from difflib import SequenceMatcher

import db

SIMILARITY_THRESHOLD = 0.72


def _memory_rows(brand_id: int):
    with db.db() as conn:
        return conn.execute(
            "SELECT topic, hook, visual_style, cta, keywords FROM creative_memory WHERE brand_id=?",
            (brand_id,),
        ).fetchall()


def avoid_context(brand_id: int) -> str:
    rows = _memory_rows(brand_id)
    with db.db() as conn:
        brand = conn.execute("SELECT forbidden_seeds FROM brand WHERE id=?", (brand_id,)).fetchone()

    parts: list[str] = []
    seeds = (brand["forbidden_seeds"] if brand else "") or ""
    if seeds.strip():
        parts.append(f"Hard rules - never use these: {seeds.strip()}")

    if rows:
        used = []
        for r in rows:
            kw = ", ".join(json.loads(r["keywords"])) if r["keywords"] else ""
            used.append(
                f"- topic: {r['topic']}; hook: {r['hook']}; visual: {r['visual_style']}; "
                f"cta: {r['cta']}; keywords: {kw}"
            )
        parts.append("Already used (pick a clearly DIFFERENT direction):\n" + "\n".join(used))

    return "\n\n".join(parts) if parts else "Nothing used yet - be original and on-brand."


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()


def _keyword_overlap(a: list[str], b: list[str]) -> float:
    sa, sb = {x.lower() for x in a}, {x.lower() for x in b}
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def is_duplicate(plan: dict, brand_id: int) -> bool:
    candidate = f"{plan.get('topic', '')} {plan.get('hook', '')}".strip()
    cand_kw = [str(k) for k in plan.get("keywords", [])]
    for r in _memory_rows(brand_id):
        existing = f"{r['topic']} {r['hook']}"
        if _ratio(candidate, existing) >= SIMILARITY_THRESHOLD:
            return True
        existing_kw = json.loads(r["keywords"]) if r["keywords"] else []
        if _keyword_overlap(cand_kw, existing_kw) >= SIMILARITY_THRESHOLD:
            return True
    return False


def record_post(post_id: int) -> None:
    with db.db() as conn:
        post = conn.execute("SELECT * FROM post WHERE id=?", (post_id,)).fetchone()
        if not post or not post["plan"]:
            return
        plan = json.loads(post["plan"])
        conn.execute(
            """INSERT INTO creative_memory (brand_id, topic, hook, visual_style, cta, keywords, post_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                post["brand_id"],
                plan.get("topic", ""),
                plan.get("hook", ""),
                plan.get("visual_style", ""),
                plan.get("cta", ""),
                json.dumps(plan.get("keywords", []), ensure_ascii=False),
                post_id,
            ),
        )
