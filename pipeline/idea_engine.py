"""4-pass idea refinement: diverge → critique → polish → anchor.

Turns a boring seed into a bold, intent-preserving creative concept.
"""

from collections.abc import Callable

from pipeline import memory, planner
from pipeline.brand_context import build_full_context
from pipeline.presets import preset_prompt
from providers import text

ProgressFn = Callable[[str, str], None]
StepDataFn = Callable[[str, dict], None]

PLAN_KEYS = ("topic", "angle", "hook", "visual_style", "cta", "image_prompt_en", "keywords")

DIVERGE_SYSTEM = (
    "You are a senior social strategist and creative director. You think in layers: audience "
    "psychology, brand fit, scroll-stopping tension, and factual integrity. Shallow one-liner "
    "ideas are failures. Every concept must explain WHY it works, not just WHAT it is."
)

CRITIQUE_SYSTEM = (
    "You are a ruthless creative director running a formal review. Write substantive analysis — "
    "never generic praise. Reject stock-photo concepts, interchangeable hooks, and ideas that "
    "could belong to any brand. Score honestly; justify every score in full sentences."
)

POLISH_SYSTEM = (
    "You are a senior creative producer turning a winning concept into a production-ready brief. "
    "Preserve the strategic depth of the winner — do not flatten it into generic marketing copy."
)

ANCHOR_SYSTEM = (
    "You verify that a creative concept still fulfills the user's original educational or "
    "marketing intent. Be strict about intent fidelity and depth of substance, not just tone."
)


def _progress(on_progress: ProgressFn | None, step: str, detail: str) -> None:
    if on_progress:
        on_progress(step, detail)


def _base_context(brand, ctx: dict, selected_assets: list[dict], audience: str, preset: str) -> str:
    parts = [
        f"Brand: {brand['name']}",
        f"Voice & tone: {brand.get('voice_tone') or 'n/a'}",
        f"Visual style: {brand.get('visual_style') or 'n/a'}",
        f"Language: {brand.get('language') or 'en'}",
        f"Post format: {ctx.get('format', 'post')}",
        build_full_context(brand, selected_assets),
        memory.avoid_context(brand["id"]),
    ]
    seed = (ctx.get("topic_hint") or "").strip()
    if seed:
        parts.append(f"User seed idea (MUST preserve intent and facts): {seed}")
    if audience.strip():
        parts.append(f"Target audience: {audience.strip()}")
    preset_block = preset_prompt(preset)
    if preset_block:
        parts.append(preset_block)
    return "\n\n".join(p for p in parts if p)


def _normalize_concepts(result) -> list[dict]:
    """Accept varied JSON shapes from different LLMs."""
    if isinstance(result, list):
        return [c for c in result if isinstance(c, dict) and (c.get("title") or c.get("hook"))]

    if not isinstance(result, dict):
        return []

    for key in ("concepts", "ideas", "candidates", "results", "items", "options", "posts"):
        val = result.get(key)
        if isinstance(val, list):
            items = [c for c in val if isinstance(c, dict)]
            if items:
                return items

    for val in result.values():
        if isinstance(val, list) and val and isinstance(val[0], dict):
            if val[0].get("title") or val[0].get("hook") or val[0].get("visual_gag"):
                return val

    if result.get("title") or result.get("hook"):
        return [result]
    return []


def _diverge_once(context: str, *, simplified: bool = False) -> list[dict]:
    if simplified:
        prompt = f"""{context}

Generate 4 bold, distinct social post concepts with substantive depth (not one-liners).
Each must include title, strategic_rationale (2 sentences), hook, visual_gag (3 sentences),
caption_arc (3 beats). Preserve facts from the user seed.

Return JSON only:
{{"concepts": [{{"title": "...", "strategic_rationale": "...", "hook": "...", "visual_gag": "...", "caption_arc": ["..."], "caption_angle": "...", "facts_to_keep": [], "risk_level": "medium"}}]}}
"""
    else:
        prompt = f"""{context}

Generate exactly 8 DISTINCT post concepts. Requirements:
- At least half must be unexpected (pop culture, dark humor, absurd visuals, paradoxes, myth-busting).
- Each concept must be SUBSTANTIVE: explain strategy and audience psychology, not just a catchy line.
- No generic product-on-marble, no interchangeable wellness clichés.
- Every concept must tie back to specific facts or intent from the user seed.

For EACH concept, write DEPTH — minimum lengths:
- strategic_rationale: 2–4 sentences on why this angle works for this audience and brand
- scroll_stop_moment: 1–2 sentences on the exact beat that stops the scroll
- hook: opening line or gag (memorable, specific to this brand)
- visual_gag: 3–5 sentences — who/what/where/lighting/pose/props; a director's shot note
- caption_arc: 3–5 bullet beats for how the caption unfolds (not one vague sentence)
- differentiation: 1–2 sentences on what makes this unlike typical posts in this category

Respond ONLY as JSON with a top-level "concepts" array:
{{
  "concepts": [
    {{
      "title": "short memorable name",
      "strategic_rationale": "...",
      "scroll_stop_moment": "...",
      "hook": "...",
      "visual_gag": "...",
      "caption_arc": ["beat 1", "beat 2", "beat 3"],
      "caption_angle": "one-line summary of caption strategy",
      "differentiation": "...",
      "facts_to_keep": ["fact from seed that must survive"],
      "risk_level": "low|medium|high"
    }}
  ]
}}
"""
    result = text.generate_json(prompt, system=DIVERGE_SYSTEM)
    return _normalize_concepts(result)


def diverge(context: str) -> list[dict]:
    concepts = _diverge_once(context)
    if concepts:
        return concepts
    return _diverge_once(context, simplified=True)


def critique(context: str, concepts: list[dict]) -> dict:
    import json

    prompt = f"""{context}

Candidates:
{json.dumps(concepts, ensure_ascii=False, indent=2)}

Run a DEEP creative review. For EVERY concept, score 1–10 on each dimension AND write 2+ sentence
justification per dimension (not one-word notes):
- engagement: scroll-stop power, shareability, comment bait
- intent_fidelity: preserves seed facts and user intent
- brand_fit: voice, visual style, audience match
- depth: substantive value beyond a gimmick
- visual_feasibility: can we actually shoot/generate this?

Compute overall score as rounded average of the five dimensions.
Reject boring/generic ideas explicitly. Pick ONE winner to polish.

Also write:
- winner_rationale: 3–5 sentences explaining WHY this concept won over the others
- runner_up_title: title of the closest alternative
- runner_up_gap: 2–3 sentences on what the winner does better than the runner-up
- polish_directives: specific, actionable notes for the polish step (what to sharpen, keep, or fix)

Respond ONLY as JSON:
{{
  "ranked": [
    {{
      "title": "...",
      "overall_score": 8,
      "scores": {{
        "engagement": 8,
        "intent_fidelity": 9,
        "brand_fit": 7,
        "depth": 8,
        "visual_feasibility": 8
      }},
      "dimension_notes": {{
        "engagement": "2+ sentences…",
        "intent_fidelity": "2+ sentences…",
        "brand_fit": "2+ sentences…",
        "depth": "2+ sentences…",
        "visual_feasibility": "2+ sentences…"
      }},
      "reject_reason": "null if top pick, else why not chosen",
      "improve_notes": "what would make this concept stronger"
    }}
  ],
  "winner_title": "exact title of winner",
  "winner_rationale": "3–5 sentences…",
  "runner_up_title": "...",
  "runner_up_gap": "2–3 sentences…",
  "winner_improvements": "same as polish_directives — kept for compatibility",
  "polish_directives": "actionable polish notes"
}}
"""
    return text.generate_json(prompt, system=CRITIQUE_SYSTEM)


def find_winner(concepts: list[dict], critique: dict, *, winner_title: str = "") -> dict:
    title = (winner_title or critique.get("winner_title") or "").strip()
    if not title:
        return concepts[0] if concepts else {}
    for c in concepts:
        if (c.get("title") or "").strip() == title:
            return c
    title_lower = title.lower()
    for c in concepts:
        ct = (c.get("title") or "").strip()
        if ct.lower() == title_lower:
            return c
    for c in concepts:
        ct = (c.get("title") or "").strip().lower()
        if title_lower in ct or ct in title_lower:
            return c
    return concepts[0] if concepts else {}


def polish(context: str, winner: dict, critique: dict, *, fix_notes: str = "") -> dict:
    import json

    extra = f"\nFix these issues from anchor check: {fix_notes}" if fix_notes else ""
    polish_notes = (
        critique.get("polish_directives")
        or critique.get("winner_improvements")
        or "none"
    )
    winner_why = critique.get("winner_rationale") or ""

    prompt = f"""{context}

Winning concept (preserve its strategic depth — do not genericize):
{json.dumps(winner, ensure_ascii=False, indent=2)}

Why this concept won:
{winner_why or "n/a"}

Polish directives from critique:
{polish_notes}
{extra}

Produce ONE production-ready brief. Keep the hook tied to the visual. The image must be text-free
(no words, logos, typography). Caption structure should reflect the original caption_arc depth.

Respond ONLY as JSON:
{{
  "creative_title": "memorable campaign title",
  "topic": "short subject",
  "angle": "creative angle with strategic rationale (2 sentences)",
  "hook": "punchy hook",
  "visual_style": "palette, mood, composition",
  "visual_concept": "full scene description (3+ sentences)",
  "cta": "call to action",
  "image_prompt_en": "detailed English text-to-image prompt, text-free scene",
  "caption_structure": ["beat 1", "beat 2", "beat 3", "beat 4"],
  "facts_to_include": ["must appear in caption"],
  "keywords": ["keyword1", "keyword2"],
  "source_concept_title": "title of the brainstorm concept this came from"
}}
"""
    return text.generate_json(prompt, system=POLISH_SYSTEM)


def to_plan(polished: dict) -> dict:
    plan = {
        "topic": polished.get("topic") or polished.get("creative_title", ""),
        "angle": polished.get("angle", ""),
        "hook": polished.get("hook", ""),
        "visual_style": polished.get("visual_style") or polished.get("visual_concept", ""),
        "cta": polished.get("cta", ""),
        "image_prompt_en": polished.get("image_prompt_en", ""),
        "keywords": polished.get("keywords") or [],
    }
    if not isinstance(plan["keywords"], list):
        plan["keywords"] = []
    return plan


def anchor(context: str, seed: str, polished: dict) -> dict:
    import json

    prompt = f"""Original user seed: {seed or '(none — AI chose topic)'}

Polished concept:
{json.dumps(polished, ensure_ascii=False, indent=2)}

Does this concept still fulfill the seed's intent and facts? Is the hook tied to the visual?

Respond ONLY as JSON:
{{
  "passed": true,
  "notes": "why it passes or what is missing",
  "missing_facts": ["any seed facts not covered"]
}}
"""
    return text.generate_json(prompt, system=ANCHOR_SYSTEM)


def validate_plan(plan: dict) -> dict:
    """Ensure plan has required keys; fill defaults for missing."""
    out = dict(plan)
    for key in PLAN_KEYS:
        if key not in out:
            out[key] = [] if key == "keywords" else ""
    if not isinstance(out.get("keywords"), list):
        out["keywords"] = []
    if not out.get("image_prompt_en") and out.get("topic"):
        out["image_prompt_en"] = out["topic"]
    return out


def make_context(brand, ctx: dict, selected_assets: list[dict], audience: str, preset: str) -> str:
    return _base_context(brand, ctx, selected_assets, audience, preset)


def run_from_step(
    brand,
    ctx: dict,
    selected_assets: list[dict],
    *,
    audience: str = "",
    preset: str = "",
    from_step: str,
    state: dict,
    on_progress: ProgressFn | None = None,
    on_step: StepDataFn | None = None,
) -> tuple[dict, dict]:
    """Re-run from diverge, critique, polish, or anchor using client-edited state."""
    seed = (ctx.get("topic_hint") or "").strip()
    context = make_context(brand, ctx, selected_assets, audience, preset)

    concepts = state.get("diverge_candidates") or []
    critique_data = state.get("critique") or {}
    winner = state.get("winner") or find_winner(concepts, critique_data, winner_title=state.get("winner_title", ""))
    polished = state.get("polished_concept") or {}

    def emit(step: str, payload: dict) -> None:
        if on_step:
            on_step(step, payload)

    if from_step == "diverge":
        _progress(on_progress, "diverge", "Brainstorming concepts…")
        concepts = diverge(context)
        if not concepts:
            raise RuntimeError("Diverge returned no concepts.")
        emit("diverge", {"concepts": concepts})
        from_step = "critique"

    if from_step == "critique":
        if not concepts:
            raise ValueError("Need concepts before critique.")
        _progress(on_progress, "critique", "Critiquing concepts…")
        critique_data = critique(context, concepts)
        winner = find_winner(concepts, critique_data, winner_title=state.get("winner_title", ""))
        emit("critique", {"critique": critique_data, "winner": winner})
        from_step = "polish"

    if from_step == "polish":
        if not winner:
            raise ValueError("Need a winning concept before polish.")
        _progress(on_progress, "polish", "Polishing brief…")
        polished = polish(context, winner, critique_data)
        emit("polish", {"polished_concept": polished, "plan": to_plan(polished)})
        from_step = "anchor"

    if from_step == "anchor":
        if not polished:
            raise ValueError("Need polished concept before anchor.")
        _progress(on_progress, "anchor", "Checking intent…")
        anchor_result = anchor(context, seed, polished)
        if not anchor_result.get("passed"):
            polished = polish(context, winner, critique_data, fix_notes=anchor_result.get("notes", ""))
            anchor_result = anchor(context, seed, polished)
        plan = to_plan(polished)
        brief = {
            "seed": seed,
            "audience": audience,
            "preset": preset,
            "diverge_candidates": concepts,
            "critique": critique_data,
            "winner": winner,
            "polished_concept": polished,
            "anchor": anchor_result,
        }
        emit("anchor", {"anchor": anchor_result, "plan": plan, "idea_brief": brief})
        return validate_plan(plan), brief

    raise ValueError(f"Unknown step: {from_step}")


def refine(
    brand,
    ctx: dict,
    selected_assets: list[dict] | None = None,
    *,
    audience: str = "",
    preset: str = "",
    on_progress: ProgressFn | None = None,
    on_step: StepDataFn | None = None,
    skip_engine: bool = False,
    refined_plan: dict | None = None,
    idea_brief: dict | None = None,
) -> tuple[dict, dict]:
    """Return (plan, idea_brief). Uses planner fallback when seed is empty."""
    seed = (ctx.get("topic_hint") or "").strip()
    assets = selected_assets or []

    if skip_engine and refined_plan:
        plan = validate_plan(refined_plan)
        brief = idea_brief or {"seed": seed, "audience": audience, "preset": preset, "skipped_engine": True}
        return plan, brief

    if not seed:
        _progress(on_progress, "diverge", "No seed — using standard planner…")
        plan = planner.plan_slot(brand, ctx, assets)
        brief = {"seed": "", "audience": audience, "preset": preset, "used_planner_fallback": True}
        return plan, brief

    def emit(step: str, payload: dict) -> None:
        if on_step:
            on_step(step, payload)

    plan, brief = run_from_step(
        brand,
        ctx,
        assets,
        audience=audience,
        preset=preset,
        from_step="diverge",
        state={},
        on_progress=on_progress,
        on_step=emit,
    )
    title = (brief.get("polished_concept") or {}).get("creative_title") or plan.get("topic", "")
    _progress(on_progress, "anchor", f"Concept locked — {title[:80]}")
    return plan, brief
