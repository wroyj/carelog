#!/usr/bin/env python3
"""
carelog/backup.py  --  3-2-1 backups of the at-rest set, each copy verified.

The protected set is the ciphertext store plus its receipts:
    store/  manifest.jsonl  store_index.jsonl
Plaintext is never in the set (store.py already removed it).

For each destination given (e.g. a local drive and an off-site drive -> the "2"
media and the "1" off-site of 3-2-1):
    backend `restic` if present (preferred), else `tar` (fallback)
    after writing, VERIFY the copy: extract/restore it to a temp area and confirm
    every ciphertext object's sha256 matches store_index, and both receipts are
    present. A backup that doesn't verify is reported as FAILED, never assumed
    good.

Usage:
    python3 backup.py RUN_ROOT DEST_DIR [DEST_DIR ...]
"""

import os
import sys
import shutil
import tempfile
import subprocess

import carelib as cl

_PROTECTED = ["store", cl.MANIFEST, cl.STORE_INDEX]
_ARCHIVE = "carelog_backup.tar.gz"


def _tar_write(run_root, dest_dir):
    cl.ensure_dir(dest_dir)
    archive = os.path.join(dest_dir, _ARCHIVE)
    present = [p for p in _PROTECTED if os.path.exists(os.path.join(run_root, p))]
    subprocess.run(["tar", "-czf", archive, "-C", run_root, *present],
                   check=True, capture_output=True)
    return archive


def _tar_extract(archive, target):
    cl.ensure_dir(target)
    subprocess.run(["tar", "-xzf", archive, "-C", target],
                   check=True, capture_output=True)
    return target


# restic (preferred) -- written faithfully; exercised where restic is installed.
def _restic_env():
    env = dict(os.environ)
    env.setdefault("RESTIC_PASSWORD",
                   os.environ.get("CARELOG_PASSPHRASE",
                                  "carelog-synthetic-demo-passphrase"))
    return env


def _restic_write(run_root, dest_dir):
    env = _restic_env()
    repo = os.path.join(dest_dir, "restic-repo")
    if not os.path.isdir(repo):
        subprocess.run(["restic", "-r", repo, "init"], check=True,
                       capture_output=True, env=env)
    paths = [os.path.join(run_root, p) for p in _PROTECTED
             if os.path.exists(os.path.join(run_root, p))]
    subprocess.run(["restic", "-r", repo, "backup", *paths],
                   check=True, capture_output=True, env=env)
    subprocess.run(["restic", "-r", repo, "check"], check=True,
                   capture_output=True, env=env)
    return repo


def _restic_restore(repo, target):
    env = _restic_env()
    cl.ensure_dir(target)
    subprocess.run(["restic", "-r", repo, "restore", "latest",
                    "--target", target], check=True,
                   capture_output=True, env=env)
    # restic restores absolute paths under target; find the store dir it made
    for root, dirs, _ in os.walk(target):
        if os.path.basename(root) == "store":
            return os.path.dirname(root)
    return target


def _verify_copy(restored_root, run_root):
    """Confirm the restored set matches store_index and carries both receipts."""
    problems = []
    for name in (cl.MANIFEST, cl.STORE_INDEX):
        if not os.path.exists(os.path.join(restored_root, name)):
            problems.append(f"missing receipt: {name}")
    index = cl.store_by_sha(run_root)
    rstore = os.path.join(restored_root, "store")
    for sha, idx in index.items():
        cipher = os.path.join(rstore, idx["cipher_name"])
        if not os.path.exists(cipher):
            problems.append(f"missing object in backup: {idx['cipher_name']}")
            continue
        if cl.sha256_file(cipher) != idx["cipher_sha256"]:
            problems.append(f"ciphertext hash mismatch: {idx['cipher_name']}")
    return problems


def backup(run_root, dest_dirs):
    backend = cl.backup_backend()
    results = []
    for dest in dest_dirs:
        if backend == "restic":
            handle = _restic_write(run_root, dest)
        else:
            handle = _tar_write(run_root, dest)

        with tempfile.TemporaryDirectory() as td:
            if backend == "restic":
                restored = _restic_restore(handle, td)
            else:
                restored = _tar_extract(handle, td)
            problems = _verify_copy(restored, run_root)

        results.append({"dest": dest, "backend": backend,
                        "handle": handle, "ok": not problems,
                        "problems": problems})
    return results


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    results = backup(argv[1], argv[2:])
    all_ok = all(r["ok"] for r in results)
    for r in results:
        tag = "OK " if r["ok"] else "FAIL"
        print(f"[{tag}] {r['backend']} -> {r['dest']}")
        for p in r["problems"]:
            print(f"        - {p}")
    print(f"{sum(r['ok'] for r in results)}/{len(results)} copies verified")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
