"""Publish-time banned-wording guard (Beldi Wellness).

Deterministic, dependency-free check that rejects customer-facing copy
containing banned wording *before* it is generated, approved, or published.

Rules (board direction 2026-09-19, `beldi-wellness-brand` skill):

- ``شحم البقر`` is an absolute NO-GO on every customer-facing surface
  (caption, hook, on-image text, alt text, hashtags, CTAs, first comment).
- ``دهن البقر`` is not banned outright, but it is **front-facing banned**:
  it must not lead copy (hook / headline / on-image text / CTA / hashtags /
  first line of the caption). It may appear once in detailed, educational,
  ingredient or FAQ context inside the caption body.

Anything that matches is rejected with a stable reason string that names the
term, the rule, and the surface, so the caller (generation pipeline or publish
gate) can surface it to the operator.

Usage as a library::

    from pipeline import copy_guard

    copy_guard.assert_plan_clean(plan)          # raises CopyRejected
    copy_guard.assert_copy_clean(caption, hashtags)

Usage as a CLI (dry run / CI)::

    python -m pipeline.copy_guard --surface caption --text "…"
    printf '%s' "$copy" | python -m pipeline.copy_guard --surface on_image

Exit code is ``0`` when clean and ``1`` when copy is rejected.
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from dataclasses import dataclass, field

# --- canonical banned wording -------------------------------------------------

#: Banned on every customer-facing surface, no exceptions.
HARD_BANNED = ("شحم البقر",)

#: Banned only on front-facing surfaces (see FRONT_FACING_SURFACES).
FRONT_FACING_BANNED = ("دهن البقر",)

#: Surfaces where copy leads the reader — the literal animal source is not
#: allowed here. Everything else is treated as detailed/educational context.
FRONT_FACING_SURFACES = frozenset(
    {
        "hook",
        "headline",
        "on_image",
        "on_image_text",
        "caption_hook",
        "cta",
        "alt_text",
        "hashtag",
        "hashtags",
        "first_comment",
        "product_name",
        "title",
    }
)

DEFAULT_SURFACE = "caption"

# --- reason strings -----------------------------------------------------------

HARD_RULE = "banned_wording"
FRONT_FACING_RULE = "front_facing_banned_wording"

_HARD_REASON = (
    "`{term}` is banned in all Beldi customer-facing copy. Use product language "
    "such as `البلسم البلدي` / `الدهن البلدي` instead."
)
_FRONT_FACING_REASON = (
    "`{term}` is front-facing banned: it must not lead copy (hook, on-image text, "
    "CTA, hashtags, or the caption's first line). Lead with the finished product; "
    "keep the literal source for detailed/educational/ingredient context only."
)

_MESSAGE = (
    "Banned wording rejected on the {surface} surface: `{term}` (rule: {rule}). {reason}"
)

# --- normalization ------------------------------------------------------------

# Harakat, Quranic marks, and tatweel (kashida). Stripping them means
# `شَحـم` matches `شحم`.
_ARABIC_MARKS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")
_ALEF_VARIANTS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي"})
_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
_WHITESPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Normalize Arabic copy so diacritics/whitespace cannot dodge the guard."""

    if not text:
        return ""
    text = unicodedata.normalize("NFKC", str(text))
    text = _ZERO_WIDTH.sub("", text)
    text = _ARABIC_MARKS.sub("", text)
    text = text.translate(_ALEF_VARIANTS)
    return _WHITESPACE.sub(" ", text).strip()


# --- verdict ------------------------------------------------------------------


@dataclass(frozen=True)
class Violation:
    """One rejected term on one surface."""

    term: str
    rule: str
    surface: str
    reason: str

    @property
    def message(self) -> str:
        return _MESSAGE.format(term=self.term, surface=self.surface, rule=self.rule, reason=self.reason)


@dataclass
class Verdict:
    """Result of a copy check; truthy when clean."""

    violations: list[Violation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    @property
    def reason(self) -> str:
        """Single clear reason string (first violation), or '' when clean."""
        return self.violations[0].message if self.violations else ""

    @property
    def reasons(self) -> list[str]:
        return [v.message for v in self.violations]


class CopyRejected(ValueError):
    """Raised when copy contains banned wording.

    Subclasses ``ValueError`` so existing pipeline/UI error handling catches it.
    """

    def __init__(self, violations: list[Violation]):
        self.violations = list(violations)
        super().__init__(self.reason)

    @property
    def reason(self) -> str:
        if not self.violations:
            return "Copy rejected."
        first = self.violations[0]
        extra = len(self.violations) - 1
        suffix = f" (+{extra} more)" if extra else ""
        return f"{first.message}{suffix}"


# --- core check ---------------------------------------------------------------


def _matches(haystack_norm: str, term: str) -> bool:
    return normalize(term) in haystack_norm


def check_text(text: str | None, surface: str = DEFAULT_SURFACE) -> list[Violation]:
    """Return every banned-wording violation in ``text`` for ``surface``."""

    haystack = normalize(text or "")
    if not haystack:
        return []

    front_facing = surface in FRONT_FACING_SURFACES
    violations: list[Violation] = []

    for term in HARD_BANNED:
        if _matches(haystack, term):
            violations.append(
                Violation(term=term, rule=HARD_RULE, surface=surface, reason=_HARD_REASON.format(term=term))
            )

    if front_facing:
        for term in FRONT_FACING_BANNED:
            if _matches(haystack, term):
                violations.append(
                    Violation(
                        term=term,
                        rule=FRONT_FACING_RULE,
                        surface=surface,
                        reason=_FRONT_FACING_REASON.format(term=term),
                    )
                )

    return violations


def _dedupe(violations: list[Violation]) -> list[Violation]:
    seen: set[tuple[str, str]] = set()
    out: list[Violation] = []
    for v in violations:
        key = (v.term, v.rule)
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out


def first_line(text: str | None) -> str:
    """First non-empty line of a caption — the front-facing hook."""

    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def check_caption(caption: str | None, hashtags: str | None = None) -> list[Violation]:
    """Check a caption: hard terms anywhere, front-facing terms in line 1."""

    violations = list(check_text(caption, "caption"))
    violations += check_text(first_line(caption), "caption_hook")
    if hashtags:
        violations += check_text(hashtags, "hashtags")
    return _dedupe(violations)


def check_plan(plan: dict | None) -> list[Violation]:
    """Check the front-facing fields of a creative plan (hook, CTA)."""

    plan = plan or {}
    violations: list[Violation] = []
    for key in ("hook", "cta", "title", "creative_title"):
        value = plan.get(key)
        if value:
            violations += check_text(str(value), key if key in {"hook", "cta"} else "headline")
    return _dedupe(violations)


def check_post_copy(
    plan: dict | None = None,
    caption: str | None = None,
    hashtags: str | None = None,
) -> list[Violation]:
    """Check every customer-facing surface of a post at once."""

    violations = list(check_plan(plan))
    violations += check_caption(caption, hashtags)
    return _dedupe(violations)


def assert_plan_clean(plan: dict | None) -> None:
    """Raise :class:`CopyRejected` if a plan has front-facing banned wording."""

    violations = check_plan(plan)
    if violations:
        raise CopyRejected(violations)


def assert_copy_clean(
    caption: str | None,
    hashtags: str | None = None,
    *,
    plan: dict | None = None,
) -> None:
    """Raise :class:`CopyRejected` if post copy has banned wording."""

    violations = list(check_plan(plan)) if plan else []
    violations += check_caption(caption, hashtags)
    violations = _dedupe(violations)
    if violations:
        raise CopyRejected(violations)


def assert_text_clean(text: str | None, surface: str = DEFAULT_SURFACE) -> None:
    """Raise :class:`CopyRejected` if ``text`` has banned wording."""

    violations = check_text(text, surface)
    if violations:
        raise CopyRejected(violations)


# --- CLI ----------------------------------------------------------------------


def _read_text(args: argparse.Namespace) -> str:
    if args.text is not None:
        return args.text
    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            return fh.read()
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return ""


def _surface_label(args: argparse.Namespace) -> str:
    if args.surface:
        return args.surface
    return "caption_hook" if args.front_facing else DEFAULT_SURFACE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reject Beldi copy with banned wording.")
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--text", help="copy to check (quote it)")
    src.add_argument("--file", help="read copy from a file")
    parser.add_argument(
        "--surface",
        default="",
        help="surface being checked (hook, on_image, caption, hashtags, …)",
    )
    parser.add_argument(
        "--front-facing",
        action="store_true",
        help="treat the input as the front-facing hook (default when no --surface)",
    )
    args = parser.parse_args(argv)

    text = _read_text(args)
    violations = check_text(text, _surface_label(args))
    if violations:
        for message in Verdict(violations).reasons:
            print(f"REJECTED: {message}", file=sys.stderr)
        return 1
    print("ACCEPTED: no banned wording found.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
