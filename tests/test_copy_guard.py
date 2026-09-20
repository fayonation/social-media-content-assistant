"""Tests for the Beldi publish-time banned-wording guard."""

import unittest

from pipeline import copy_guard
from pipeline.copy_guard import CopyRejected

# Banned everywhere (hard rule).
HARD = "شحم البقر"
# Front-facing banned only (hook / on-image / CTA / hashtags / first line).
FRONT = "دهن البقر"

CLEAN_CAPTION = (
    "بشرتك ناشفة وكتحس بالشد فهاد البرد؟\n"
    "البلسم البلدي كيرطب البشرة وكيحميها من فقدان الرطوبة.\n"
    "اكتشفو التفاصيل فالموقع ديالنا"
)


class HardRuleTests(unittest.TestCase):
    def test_banned_in_caption(self):
        violations = copy_guard.check_caption(f"جرب {HARD} الجديد ديالنا")
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].rule, copy_guard.HARD_RULE)
        self.assertIn(HARD, violations[0].message)

    def test_hard_rule_applies_on_every_surface(self):
        for surface in ("caption", "caption_hook", "hook", "on_image", "hashtags", "cta", "alt_text"):
            with self.subTest(surface=surface):
                self.assertTrue(copy_guard.check_text(HARD, surface))

    def test_diacritics_and_tatweel_cannot_dodge(self):
        for variant in ("شَحم البقر", "شـحم البقر", "شحم  البقر", "شحم\u200b البقر"):
            with self.subTest(variant=variant):
                self.assertTrue(copy_guard.check_text(variant, "caption"))

    def test_alef_variants_normalized(self):
        # Alef wasla normalizes to plain alef before matching.
        self.assertTrue(copy_guard.check_text("شحم ٱلبقر", "caption"))


class FrontFacingRuleTests(unittest.TestCase):
    def test_front_facing_banned_in_hook(self):
        violations = copy_guard.check_text(f"{FRONT} للبشرة", "hook")
        self.assertEqual([v.rule for v in violations], [copy_guard.FRONT_FACING_RULE])

    def test_front_facing_banned_in_on_image(self):
        self.assertTrue(copy_guard.check_text(f"{FRONT} — الروتين كيبدا دابا", "on_image"))

    def test_front_facing_banned_in_caption_first_line(self):
        caption = f"{FRONT} للبشرة\nهاد البلسم كيرطب وكنعّم."
        violations = copy_guard.check_caption(caption)
        self.assertEqual([v.rule for v in violations], [copy_guard.FRONT_FACING_RULE])

    def test_front_facing_allowed_in_caption_body(self):
        caption = "روتين البشرة فهاد البرد\nهاد البلسم مبني على دهن البقر وكيرطب بعمق."
        self.assertEqual(copy_guard.check_caption(caption), [])

    def test_front_facing_banned_in_hashtags(self):
        self.assertTrue(copy_guard.check_caption(CLEAN_CAPTION, hashtags=f"#بشرة #{FRONT}"))

    def test_front_facing_banned_in_plan_hook(self):
        violations = copy_guard.check_plan({"hook": FRONT, "cta": "اكتشفو التفاصيل"})
        self.assertEqual([v.rule for v in violations], [copy_guard.FRONT_FACING_RULE])


class CleanCopyTests(unittest.TestCase):
    def test_clean_copy_accepted(self):
        result = copy_guard.check_post_copy(
            plan={"hook": "حضّر البشرة قبل البرد", "cta": "اكتشفو التفاصيل فالموقع ديالنا"},
            caption=CLEAN_CAPTION,
            hashtags="#بشرة #ترطيب",
        )
        self.assertEqual(result, [])

    def test_verdict_reason_is_clear(self):
        verdict = copy_guard.Verdict(copy_guard.check_caption(f"{HARD} الجديد"))
        self.assertFalse(verdict.ok)
        self.assertIn("REJECTED", f"REJECTED: {verdict.reason}")
        self.assertIn(HARD, verdict.reason)
        self.assertIn(copy_guard.HARD_RULE, verdict.reason)


class AssertionTests(unittest.TestCase):
    def test_assert_copy_clean_raises_with_reason(self):
        with self.assertRaises(CopyRejected) as ctx:
            copy_guard.assert_copy_clean(f"جرب {HARD} الجديد")
        self.assertIn(HARD, str(ctx.exception))
        self.assertIn(copy_guard.HARD_RULE, str(ctx.exception))

    def test_assert_plan_clean_raises(self):
        with self.assertRaises(CopyRejected):
            copy_guard.assert_plan_clean({"hook": FRONT})

    def test_assert_text_clean_passes_clean_copy(self):
        copy_guard.assert_text_clean(CLEAN_CAPTION, "caption")


if __name__ == "__main__":
    unittest.main()
