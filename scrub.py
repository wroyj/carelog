#!/usr/bin/env python3
"""
carelog/scrub.py  --  detect corruption at rest. Flag, never fix.

Shallow (default): recompute each ciphertext object's sha256 and compare to the
    cipher_sha256 recorded at store time. Catches bit-rot without needing the
    passphrase.
Deep (--deep): also decrypt each object and compare the plaintext sha256 to the
    manifest GROUND TRUTH. Catches corruption that survived as valid ciphertext
    but decrypts wrong (and confirms the object is still recoverable).

scrub NEVER edits, re-encrypts, or "repairs" anything. It reports. A human
decides what to do with a flagged object -- exactly as the extractor flags
rather than fixes.

Usage:
    python3 scrub.py RUN_ROOT [--deep]
"""

import os
import sys
import tempfile

import carelib as cl
import store as store_mod


def scrub(run_root, deep=False):
    index = cl.store_by_sha(run_root)
    manifest = cl.manifest_by_sha(run_root)
    store_dir = os.path.join(run_root, "store")
    findings = []

    for sha, idx in index.items():
        cipher = os.path.join(store_dir, idx["cipher_name"])
        if not os.path.exists(cipher):
            findings.append({"object": idx["cipher_name"],
                             "flag": "missing", "detail": "ciphertext absent"})
            continue
        if cl.sha256_file(cipher) != idx["cipher_sha256"]:
            findings.append({"object": idx["cipher_name"],
                             "flag": "cipher_bitrot",
                             "detail": "ciphertext sha256 != stored"})
            continue  # don't attempt deep-decrypt a known-rotten object

        if deep:
            try:
                with tempfile.TemporaryDirectory() as td:
                    out = os.path.join(td, "pt")
                    store_mod._decrypt(cipher, out, idx["backend"], run_root)
                    if cl.sha256_file(out) != sha:
                        findings.append({"object": idx["cipher_name"],
                                         "flag": "plaintext_mismatch",
                                         "detail": "decrypted content != manifest"})
            except Exception as e:  # decrypt failed entirely
                findings.append({"object": idx["cipher_name"],
                                 "flag": "undecryptable",
                                 "detail": str(e).splitlines()[0][:80]})

    # Cross-check: every manifest object should have a store entry (no drops).
    for sha in manifest:
        if sha not in index:
            findings.append({"object": manifest[sha]["canonical"],
                             "flag": "unstored",
                             "detail": "in manifest but never stored"})
    return findings


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    deep = "--deep" in argv
    findings = scrub(argv[1], deep=deep)
    mode = "deep" if deep else "shallow"
    if not findings:
        print(f"scrub ({mode}): all objects intact")
        return 0
    print(f"scrub ({mode}): {len(findings)} FLAGGED (not repaired)")
    for f in findings:
        print(f"  [{f['flag']}] {f['object']}: {f['detail']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
