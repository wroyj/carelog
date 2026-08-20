#!/usr/bin/env python3
"""
carelog/test_no_real_data.py  --  Invariant 0, asserted mechanically.

These tests fail the build if the structural guarantees that keep real data out
of this repo are weakened:
  * the path guard actually refuses escapes
  * the only object source is procedural (deterministic from a seed -> it is
    computed, not recorded)
  * .gitignore is default-deny for real-data shapes

Honest limit (stated in the README too): none of this can stop a human pasting
real text by hand. The real guarantee is physical separation -- the machine that
sees real data is a different machine. These tests guard the wired paths.
"""

import os
import unittest

import carelib as cl
from demo.make_synthetic import make_synthetic
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))


class PathGuard(unittest.TestCase):
    def test_within_is_allowed(self):
        with tempfile.TemporaryDirectory() as root:
            inside = os.path.join(root, "sub", "file")
            os.makedirs(os.path.dirname(inside))
            open(inside, "w").close()
            self.assertEqual(cl.require_within(inside, root),
                             os.path.realpath(inside))

    def test_escape_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(cl.PathGuardError):
                cl.require_within(os.path.join(root, "..", "etc_passwd"), root)

    def test_sibling_prefix_is_refused(self):
        # /tmp/rootX must not count as inside /tmp/root
        with tempfile.TemporaryDirectory() as base:
            root = os.path.join(base, "root")
            os.makedirs(root)
            sibling = os.path.join(base, "rootX")
            os.makedirs(sibling)
            with self.assertRaises(cl.PathGuardError):
                cl.require_within(sibling, root)


class ProceduralSource(unittest.TestCase):
    """The only object source is computed, not recorded -> same seed, same bytes."""

    def test_generator_is_deterministic(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            make_synthetic(a, count=2, seed=42)
            make_synthetic(b, count=2, seed=42)
            ha = [cl.sha256_file(p) for p in cl.list_files(a)]
            hb = [cl.sha256_file(p) for p in cl.list_files(b)]
            self.assertEqual(ha, hb)

    def test_distinct_seeds_differ(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            make_synthetic(a, count=1, seed=1)
            make_synthetic(b, count=1, seed=2)
            self.assertNotEqual(cl.sha256_file(cl.list_files(a)[0]),
                                cl.sha256_file(cl.list_files(b)[0]))


class GitignoreDefaultDeny(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(_HERE, ".gitignore")) as fh:
            self.patterns = [l.strip() for l in fh
                             if l.strip() and not l.startswith("#")]

    def test_denies_real_data_shapes(self):
        for needed in ("*.wav", "*.mp3", "*.m4a", "transcripts/",
                       "*.jsonl", "day_log*.json", "*.txt"):
            self.assertIn(needed, self.patterns,
                          f".gitignore must deny {needed}")

    def test_denies_pipeline_artifacts(self):
        for needed in ("*.gpg", "*.age", "store/", "objects/"):
            self.assertIn(needed, self.patterns,
                          f".gitignore must deny {needed}")

    def test_demo_output_is_allowlisted(self):
        self.assertIn("!demo_output.txt", self.patterns)


if __name__ == "__main__":
    unittest.main(verbosity=2)
