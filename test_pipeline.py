#!/usr/bin/env python3
"""
carelog/test_pipeline.py  --  the handling pipeline keeps its promises.

These tests run the whole chain on synthetic data in a temp dir, then actively
BREAK things to prove the guards fire:
  * no silent drops   -- counts are conserved end to end
  * verify before trust -- store round-trips against the manifest
  * at rest = encrypted -- plaintext is gone after store
  * flag don't fix     -- scrub flags bit-rot, changes nothing
  * backups are real   -- a tampered backup FAILS the restore drill

Requires a working `gpg` and `tar` (the fallbacks). Skips cleanly if absent.
"""

import os
import shutil
import tempfile
import unittest

import carelib as cl
from demo.make_synthetic import make_synthetic
import ingest as ingest_mod
import store as store_mod
import backup as backup_mod
import scrub as scrub_mod
import restore_drill as drill_mod

_HAVE_GPG = shutil.which("gpg") is not None
_HAVE_TAR = shutil.which("tar") is not None


@unittest.skipUnless(_HAVE_GPG and _HAVE_TAR, "needs gpg + tar")
class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="carelog_test_")
        self.src = os.path.join(self.tmp, "src")
        self.run = os.path.join(self.tmp, "run")
        os.makedirs(self.run)
        make_synthetic(self.src, count=3, seed=7)
        ingest_mod.ingest(self.src, self.run)
        store_mod.store(self.run)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- conservation: no silent drops -------------------------------------
    def test_counts_conserved_source_to_store(self):
        n_src = len(cl.list_files(self.src))
        n_manifest = len(cl.read_jsonl(os.path.join(self.run, cl.MANIFEST)))
        n_store = len(cl.read_jsonl(os.path.join(self.run, cl.STORE_INDEX)))
        self.assertEqual(n_src, 3)
        self.assertEqual(n_manifest, 3)
        self.assertEqual(n_store, 3)

    # -- at rest = encrypted -----------------------------------------------
    def test_plaintext_removed_after_store(self):
        objects = os.path.join(self.run, "objects")
        leftover = cl.list_files(objects)
        self.assertEqual(leftover, [], "plaintext must not persist at rest")
        # and the ciphertext exists
        self.assertEqual(len(cl.list_files(os.path.join(self.run, "store"))), 3)

    # -- verify before trust: store round-trips to ground truth ------------
    def test_store_roundtrips_to_manifest_truth(self):
        # deep scrub decrypts and checks plaintext == manifest sha256
        findings = scrub_mod.scrub(self.run, deep=True)
        self.assertEqual(findings, [])

    # -- flag don't fix: scrub flags bit-rot, repairs nothing --------------
    def test_scrub_flags_cipher_bitrot_and_does_not_fix(self):
        store_dir = os.path.join(self.run, "store")
        victim = cl.list_files(store_dir)[0]
        before = os.path.getsize(victim)
        with open(victim, "r+b") as fh:      # flip one byte in the ciphertext
            fh.seek(before // 2)
            b = fh.read(1)
            fh.seek(before // 2)
            fh.write(bytes([b[0] ^ 0xFF]))
        findings = scrub_mod.scrub(self.run, deep=False)
        flags = {f["flag"] for f in findings}
        self.assertIn("cipher_bitrot", flags)
        # scrub must not have touched the file (still corrupt, same size)
        self.assertEqual(os.path.getsize(victim), before)

    # -- backups are real: tampered backup fails the drill -----------------
    def test_restore_drill_passes_clean_backup(self):
        dest = os.path.join(self.tmp, "bk_clean")
        backup_mod.backup(self.run, [dest])
        rec = drill_mod.restore_drill(self.run, dest)
        self.assertEqual(rec["verdict"], "PASS")
        self.assertEqual(rec["passed"], 3)

    def test_restore_drill_catches_tampered_backup(self):
        # make a good backup, then rebuild a tampered copy of the archive
        good = os.path.join(self.tmp, "bk_good")
        backup_mod.backup(self.run, [good])
        archive = os.path.join(good, backup_mod._ARCHIVE)

        bad_dir = os.path.join(self.tmp, "bk_bad")
        os.makedirs(bad_dir)
        with tempfile.TemporaryDirectory() as td:
            backup_mod._tar_extract(archive, td)
            store_in_bk = os.path.join(td, "store")
            victim = cl.list_files(store_in_bk)[0]
            with open(victim, "r+b") as fh:      # corrupt a ciphertext object
                fh.seek(10)
                fh.write(b"\x00\x00\x00\x00")
            # re-tar the tampered tree into bad_dir
            import subprocess
            subprocess.run(
                ["tar", "-czf", os.path.join(bad_dir, backup_mod._ARCHIVE),
                 "-C", td, "store", cl.MANIFEST, cl.STORE_INDEX],
                check=True, capture_output=True)

        rec = drill_mod.restore_drill(self.run, bad_dir)
        self.assertEqual(rec["verdict"], "FAIL")
        self.assertGreaterEqual(rec["failed"], 1)

    # -- the drill leaves an audit trail -----------------------------------
    def test_restore_drill_appends_log(self):
        dest = os.path.join(self.tmp, "bk_log")
        backup_mod.backup(self.run, [dest])
        drill_mod.restore_drill(self.run, dest)
        log = cl.read_jsonl(os.path.join(self.run, cl.RESTORE_LOG))
        self.assertTrue(log and log[-1]["verdict"] in ("PASS", "FAIL"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
