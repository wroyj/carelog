#!/usr/bin/env python3
"""
carelog/restore_drill.py  --  prove a backup is recoverable, and log it.

    "A backup you have never restored is a hypothesis, not a backup."

Given a backup directory, this:
    1. restores it to a temp area (tar extract, or restic restore)
    2. decrypts every object
    3. verifies each plaintext sha256 against the manifest GROUND TRUTH
    4. appends one PASS/FAIL record per drill to restore_log.jsonl

A tampered or rotten backup surfaces here as FAIL, per object -- the drill is the
tripwire, so it must actually catch corruption, not wave it through. The tests
flip a byte in a backed-up object and assert this reports FAIL.

Usage:
    python3 restore_drill.py RUN_ROOT BACKUP_DIR
"""

import os
import sys
import tempfile

import carelib as cl
import store as store_mod
import backup as backup_mod


def _locate(backup_dir):
    """Return (kind, handle) for the artifact in backup_dir."""
    archive = os.path.join(backup_dir, backup_mod._ARCHIVE)
    repo = os.path.join(backup_dir, "restic-repo")
    if os.path.exists(archive):
        return "tar", archive
    if os.path.isdir(repo):
        return "restic", repo
    raise FileNotFoundError(f"no recognizable backup in {backup_dir!r}")


def restore_drill(run_root, backup_dir):
    kind, handle = _locate(backup_dir)
    manifest = cl.manifest_by_sha(run_root)
    index = cl.store_by_sha(run_root)
    results = []

    with tempfile.TemporaryDirectory() as td:
        if kind == "tar":
            restored = backup_mod._tar_extract(handle, td)
        else:
            restored = backup_mod._restic_restore(handle, td)
        rstore = os.path.join(restored, "store")

        for sha, idx in index.items():
            cipher = os.path.join(rstore, idx["cipher_name"])
            obj = idx["cipher_name"]
            if not os.path.exists(cipher):
                results.append((obj, "FAIL", "object missing from backup"))
                continue
            try:
                out = os.path.join(td, "pt")
                store_mod._decrypt(cipher, out, idx["backend"], run_root)
                if cl.sha256_file(out) == sha:
                    results.append((obj, "PASS", ""))
                else:
                    results.append((obj, "FAIL", "restored content != manifest"))
            except Exception as e:
                results.append((obj, "FAIL", f"decrypt failed: "
                                f"{str(e).splitlines()[0][:60]}"))

    # No silent drops: every stored object must appear in the drill.
    for sha, idx in index.items():
        if not any(r[0] == idx["cipher_name"] for r in results):
            results.append((idx["cipher_name"], "FAIL", "not attempted"))

    passed = sum(1 for _, v, _ in results if v == "PASS")
    record = {
        "ts": cl.now_iso(),
        "backup_dir": backup_dir,
        "kind": kind,
        "objects": len(index),
        "passed": passed,
        "failed": len(results) - passed,
        "verdict": "PASS" if passed == len(index) and index else "FAIL",
        "detail": [{"object": o, "result": v, "note": n} for o, v, n in results],
    }
    cl.append_jsonl(os.path.join(run_root, cl.RESTORE_LOG), record)
    return record


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    rec = restore_drill(argv[1], argv[2])
    print(f"restore drill [{rec['verdict']}]: "
          f"{rec['passed']}/{rec['objects']} objects recovered and verified")
    for d in rec["detail"]:
        if d["result"] != "PASS":
            print(f"  {d['result']} {d['object']}: {d['note']}")
    print(f"  logged to {cl.RESTORE_LOG}")
    return 0 if rec["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
