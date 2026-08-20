#!/usr/bin/env python3
"""
carelog/store.py  --  encrypt every ingested object at rest, verified.

For each object recorded in the manifest:
    1. encrypt run_root/objects/<canonical> -> run_root/store/<canonical>.<ext>
       backend: `age` if present (preferred), else `gpg` symmetric (fallback)
    2. ROUND-TRIP VERIFY: decrypt the ciphertext to a temp file, sha256 it, and
       compare to the plaintext GROUND TRUTH in the manifest. Mismatch -> raise.
    3. record cipher path + ciphertext sha256 (cheap at-rest integrity for scrub)
    4. only after a verified round-trip, remove the plaintext object, so the
       persistent at-rest state is ciphertext-only.

Secrets (demo):
    gpg  -- symmetric passphrase from $CARELOG_PASSPHRASE, else a demo constant.
    age  -- an identity file generated in the run root on first use.
DEMO ONLY. The real home system uses a real passphrase / real age keys and never
this constant. The synthetic data here does not warrant secret hygiene; the
pipeline shape is what's being demonstrated.

Usage:
    python3 store.py RUN_ROOT
"""

import os
import sys
import shutil
import tempfile
import subprocess

import carelib as cl

# DEMO passphrase only. Never used for real data (see module docstring).
_DEMO_PASSPHRASE = "carelog-synthetic-demo-passphrase"


def _passphrase():
    return os.environ.get("CARELOG_PASSPHRASE", _DEMO_PASSPHRASE)


# --------------------------------------------------------------------------
# age (preferred).  Written faithfully; exercised only where `age` is installed.
# --------------------------------------------------------------------------
def _age_identity(run_root):
    ident = os.path.join(run_root, "age_identity.txt")
    if not os.path.exists(ident):
        subprocess.run(["age-keygen", "-o", ident], check=True,
                       capture_output=True)
    # recipient (public key) is embedded as a comment line in the identity file
    recipient = None
    with open(ident) as fh:
        for ln in fh:
            if ln.startswith("# public key:"):
                recipient = ln.split(":", 1)[1].strip()
    if not recipient:
        raise cl.BackendError("could not read age recipient from identity file")
    return ident, recipient


def _age_encrypt(src, dest, run_root):
    _, recipient = _age_identity(run_root)
    subprocess.run(["age", "-r", recipient, "-o", dest, src],
                   check=True, capture_output=True)


def _age_decrypt(src, dest, run_root):
    ident, _ = _age_identity(run_root)
    subprocess.run(["age", "-d", "-i", ident, "-o", dest, src],
                   check=True, capture_output=True)


# --------------------------------------------------------------------------
# gpg symmetric (fallback).  Fully exercised by the tests.
# --------------------------------------------------------------------------
def _gpg_encrypt(src, dest):
    subprocess.run(
        ["gpg", "--batch", "--yes", "--pinentry-mode", "loopback",
         "--passphrase", _passphrase(), "-c", "-o", dest, src],
        check=True, capture_output=True)


def _gpg_decrypt(src, dest):
    subprocess.run(
        ["gpg", "--batch", "--yes", "--pinentry-mode", "loopback",
         "--passphrase", _passphrase(), "-d", "-o", dest, src],
        check=True, capture_output=True)


def _encrypt(src, dest, backend, run_root):
    if backend == "age":
        _age_encrypt(src, dest, run_root)
    else:
        _gpg_encrypt(src, dest)


def _decrypt(src, dest, backend, run_root):
    if backend == "age":
        _age_decrypt(src, dest, run_root)
    else:
        _gpg_decrypt(src, dest)


_EXT = {"age": ".age", "gpg": ".gpg"}


def store(run_root):
    backend = cl.encrypt_backend()
    objects_dir = os.path.join(run_root, "objects")
    store_dir = cl.ensure_dir(os.path.join(run_root, "store"))
    index_path = os.path.join(run_root, cl.STORE_INDEX)

    manifest = cl.manifest_by_sha(run_root)
    if not manifest:
        raise FileNotFoundError("nothing to store: manifest is empty (run ingest)")

    already = cl.store_by_sha(run_root)
    stored = []
    for sha, row in manifest.items():
        if sha in already:
            continue  # already stored; not a drop
        plaintext = os.path.join(objects_dir, row["canonical"])
        cl.require_within(plaintext, run_root)
        cipher = os.path.join(store_dir, row["canonical"] + _EXT[backend])
        cl.require_within(cipher, run_root)

        _encrypt(plaintext, cipher, backend, run_root)

        # ROUND-TRIP VERIFY against ground truth before we trust the ciphertext.
        with tempfile.TemporaryDirectory() as td:
            check = os.path.join(td, "check")
            _decrypt(cipher, check, backend, run_root)
            if cl.sha256_file(check) != sha:
                raise cl.IntegrityError(
                    f"round-trip failed for {row['canonical']}: "
                    f"decrypted content != manifest sha256")

        cipher_sha = cl.sha256_file(cipher)
        idx = {
            "ts": cl.now_iso(),
            "sha256": sha,                       # plaintext ground truth
            "canonical": row["canonical"],
            "cipher_name": os.path.basename(cipher),
            "cipher_sha256": cipher_sha,         # at-rest integrity for scrub
            "backend": backend,
        }
        cl.append_jsonl(index_path, idx)

        # At-rest state is ciphertext-only: drop the verified plaintext.
        os.remove(plaintext)
        stored.append(idx)

    return backend, stored


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    backend, stored = store(argv[1])
    print(f"stored {len(stored)} object(s) at rest via {backend}, "
          f"each round-trip verified")
    for s in stored:
        print(f"  {s['canonical']} -> {s['cipher_name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
