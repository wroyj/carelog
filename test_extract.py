#!/usr/bin/env python3
"""
carelog/test_extract.py  --  asserts the extraction disciplines hold.

Run:  python3 test_extract.py            (or:  python3 -m unittest -v)

These tests exist to protect the four commitments, not to check that regex
matches. If a future change makes the extractor start GUESSING, smoothing, or
inventing values, one of these fails loudly. That is their whole job.
"""

import unittest
import datetime as _dt
from extract import extract, derive_sleep_duration, field


def f(rec, name):
    return rec["fields"][name]


class EvidenceSpans(unittest.TestCase):
    """Commitment 1: every populated value carries its verbatim source."""

    def test_every_populated_value_has_evidence_or_says_why_not(self):
        # The real rule: a populated value must EITHER carry a verbatim span
        # OR carry a flag explaining why it can't (assumed / derived). A value
        # with neither would be an unsourced guess -- the thing we forbid.
        rec = extract("She weighed 181 pounds. 1400 calories. Woke at 6:30 am.")
        for name, fld in rec["fields"].items():
            if fld["value"] is not None:
                has_evidence = fld["evidence"] is not None
                explains_absence = any(
                    x.startswith(("date_assumed", "derived"))
                    for x in fld["flags"])
                self.assertTrue(
                    has_evidence or explains_absence,
                    f"{name} has a value but neither evidence nor a flag")

    def test_evidence_is_a_real_substring(self):
        t = "She weighed 181 pounds this morning."
        rec = extract(t)
        self.assertIn(f(rec, "weight_lb")["evidence"], t)


class ExplicitNulls(unittest.TestCase):
    """Commitment 2: unmentioned fields are null, never inferred."""

    def test_unmentioned_field_is_null(self):
        rec = extract("She weighed 181 pounds.")  # nothing about calories
        self.assertIsNone(f(rec, "calories")["value"])
        self.assertIsNone(f(rec, "calories")["evidence"])

    def test_spelled_out_number_is_refused_not_guessed(self):
        # "one thousand two hundred" must NOT become 1200.
        rec = extract("Calories one thousand two hundred today.")
        self.assertIsNone(f(rec, "calories")["value"])
        self.assertTrue(any("not_parsed" in x
                            for x in f(rec, "calories")["flags"]))

    def test_spelled_out_weight_is_refused_not_guessed(self):
        rec = extract("She weighed one eighty-one this morning.")
        self.assertIsNone(f(rec, "weight_lb")["value"])
        self.assertIn("needs_review:weight_mentioned_not_parsed",
                      f(rec, "weight_lb")["flags"])


class FlagDontFix(unittest.TestCase):
    """Commitment 3: implausible values are FLAGGED, never corrected."""

    def test_implausible_weight_is_kept_and_flagged(self):
        rec = extract("She weighed 810 pounds this morning.")
        # value is preserved exactly, NOT clamped or 'corrected'
        self.assertEqual(f(rec, "weight_lb")["value"], 810.0)
        self.assertIn("needs_review:out_of_range", f(rec, "weight_lb")["flags"])

    def test_review_summary_surfaces_flags(self):
        rec = extract("She weighed 810 pounds.")
        self.assertIn("weight_lb", rec["needs_review"])


class KeepThePhrase(unittest.TestCase):
    """Commitment 4: approximate I/O keeps the raw words."""

    def test_io_phrase_preserved_when_no_number(self):
        rec = extract("Intake about a cup and a half of water.")
        intake = f(rec, "intake")
        self.assertIsNone(intake["value"])            # no clean number -> null
        self.assertIn("cup and a half", intake["evidence"])  # phrase kept
        self.assertIn("approximate", intake["flags"])

    def test_io_number_parsed_when_present(self):
        rec = extract("Intake 500 ml of water.")
        self.assertEqual(f(rec, "intake")["value"], 500)
        self.assertIn("approximate", f(rec, "intake")["flags"])


class DerivationHonesty(unittest.TestCase):
    """Derived values never invent their inputs."""

    def test_sleep_duration_from_endpoints(self):
        rec = extract("Woke at 6:30 am, went to bed around 10:45 pm.")
        # 22:45 -> 06:30 = 7h45m = 465 min
        self.assertEqual(f(rec, "sleep_minutes")["value"], 465)
        self.assertIn("derived", f(rec, "sleep_minutes")["flags"])

    def test_missing_endpoint_yields_null_not_invention(self):
        rec = extract("Woke at 6:30 am.")  # no bedtime
        self.assertIsNone(f(rec, "sleep_minutes")["value"])
        self.assertIn("derived:missing_endpoint",
                      f(rec, "sleep_minutes")["flags"])


class DateHandling(unittest.TestCase):
    def test_explicit_date_wins(self):
        rec = extract("Log for 2025-08-02. She weighed 181 pounds.")
        self.assertEqual(f(rec, "date")["value"], "2025-08-02")
        self.assertEqual(f(rec, "date")["flags"], [])

    def test_missing_date_defaults_today_but_flags_the_assumption(self):
        rec = extract("She weighed 181 pounds.")
        self.assertEqual(f(rec, "date")["value"], _dt.date.today().isoformat())
        self.assertIn("date_assumed_today", f(rec, "date")["flags"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
