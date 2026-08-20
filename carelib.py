#!/usr/bin/env python3
"""
carelog/carelib.py  --  shared primitives for the handling pipeline.

Everything the ingest/store/backup/scrub/restore stages rely on lives here so
the guarantees are defined once, in one place:

  * require_within  -- a hard path guard. No stage may read or write outside the
                       sanctioned run root. Escapes raise, they do not warn.
  * sha256_file     -- streaming content hash. The plaintext sha256 is the
                       GROUND TRUTH for every object; every later check compares
                       against it.
  * append-only manifest / store-index (JSONL) -- receipts. Rows are appended,
                       never rewritten. A missing row is a loud absence, never a
                       silent drop.
  * backend detection -- prefer `age`+`restic`; fall back to `gpg`+`tar` so the
                       synthetic demo runs anywhere. The chosen backend is
                       always recorded, never assumed.

Stdlib only. No network. Synthetic data only in this repo (Invariant 0).
"""

import os
import json
import hashlib
import shutil
import datetime as _dt


# --------------------------------------------------------------------------
# Errors -- explicit types so callers (and tests) can assert on the failure.
# --------------------------------------------------------------------------
class PathGuardError(Exception):
    """A path resolved to somewhere outside its sanctioned root."""


class IntegrityError(Exception):
    """A hash did not match its ground-truth manifest entry."""


class BackendError(Exception):
    """No usable encryption or backup backend is available."""


# --------------------------------------------------------------------------
# Path guard -- the mechanical half of Invariant 0's "no stray paths" rule.
# --------------------------------------------------------------------------
def require_within(path, root):
    """Return the real path of `path` iff it lies within `root`. Else raise.

    Resolves symlinks and `..` first, so `root/../etc/passwd` cannot slip
    through. This is a guard, not a suggestion: it raises PathGuardError.
    """
    root_r = os.path.realpath(root)
    path_r = os.path.realpath(path)
    if path_r != root_r and not path_r.startswith(root_r + os.sep):
        raise PathGuardError(f"{path!r} resolves outside sanctioned root {root!r}")
    return path_r


# --------------------------------------------------------------------------
# Hashing -- the ground truth.
# --------------------------------------------------------------------------
def sha256_file(path, _chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(_chunk), b""):
            h.update(block)
    return h.hexdigest()


# --------------------------------------------------------------------------
# Naming -- content-addressed, deterministic, no real-world identifiers.
# --------------------------------------------------------------------------
def canonical_name(sha256, ext, when=None):
    """`YYYY-MM-DD__<sha8><ext>` -- date for humans, sha8 for uniqueness."""
    day = (when or _dt.date.today()).isoformat()
    ext = ext if ext.startswith(".") else ("." + ext if ext else "")
    return f"{day}__{sha256[:8]}{ext}"


# --------------------------------------------------------------------------
# Append-only JSONL receipts.  Append; never rewrite.
# --------------------------------------------------------------------------
def now_iso():
    return _dt.datetime.now().isoformat(timespec="seconds")


def append_jsonl(path, row):
    """Append one row. fsync so a receipt survives a crash mid-run."""
    line = json.dumps(row, sort_keys=True)
    with open(path, "a") as fh:
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path) as fh:
        for ln in fh:
            ln = ln.strip()
            if ln:
                out.append(json.loads(ln))
    return out


# Canonical filenames for the two receipts.
MANIFEST = "manifest.jsonl"          # written by ingest, one row per object in
STORE_INDEX = "store_index.jsonl"    # written by store, one row per object encrypted
RESTORE_LOG = "restore_log.jsonl"    # written by restore_drill, PASS/FAIL per drill


def manifest_by_sha(run_root):
    """Fold the ingest manifest into {sha256: row}. Last write wins only if a
    genuine duplicate object was ingested twice (same content) -- which is fine,
    it's the same bytes."""
    return {r["sha256"]: r for r in read_jsonl(os.path.join(run_root, MANIFEST))}


def store_by_sha(run_root):
    return {r["sha256"]: r for r in read_jsonl(os.path.join(run_root, STORE_INDEX))}


# --------------------------------------------------------------------------
# Backend detection.  Preferred first, fallback second, else fail loudly.
# --------------------------------------------------------------------------
def encrypt_backend():
    if shutil.which("age"):
        return "age"
    if shutil.which("gpg"):
        return "gpg"
    raise BackendError("no encryption backend: install `age` (preferred) or `gpg`")


def backup_backend():
    if shutil.which("restic"):
        return "restic"
    if shutil.which("tar"):
        return "tar"
    raise BackendError("no backup backend: install `restic` (preferred) or `tar`")


# --------------------------------------------------------------------------
# Small helpers.
# --------------------------------------------------------------------------
def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def list_files(directory):
    """Immediate files (not dirs) in `directory`, sorted for determinism."""
    if not os.path.isdir(directory):
        return []
    return sorted(
        os.path.join(directory, n)
        for n in os.listdir(directory)
        if os.path.isfile(os.path.join(directory, n))
    )
