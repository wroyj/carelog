#!/usr/bin/env python3
"""
carelog/ingest.py  --  bring synthetic objects into the run root, safely.

For every file in the source directory:
    1. guard the source path (must be within the source dir)
    2. sha256 the source  -> this becomes the object's GROUND TRUTH
    3. copy to run_root/objects/ under a content-addressed canonical name
    4. RE-READ the copy and sha256 it; if it differs from the source hash, the
       copy is corrupt -> raise. We verify before we trust.
    5. append one manifest row (the receipt)

No silent drops: the run ends with exactly one manifest row per source file, or
it raises. A file that cannot be ingested stops the run; it is never quietly
skipped.

Usage:
    python3 ingest.py SOURCE_DIR RUN_ROOT
"""

import os
import sys
import shutil

import carelib as cl


def ingest(source_dir, run_root):
    objects_dir = cl.ensure_dir(os.path.join(run_root, "objects"))
    manifest_path = os.path.join(run_root, cl.MANIFEST)

    sources = cl.list_files(source_dir)
    if not sources:
        raise FileNotFoundError(f"no source objects in {source_dir!r}")

    already = cl.manifest_by_sha(run_root)   # content-addressed idempotency
    rows = []
    for src in sources:
        cl.require_within(src, source_dir)
        src_hash = cl.sha256_file(src)

        if src_hash in already:
            # Same bytes already ingested -> not a drop, a dedupe. Record it.
            rows.append({**already[src_hash], "note": "duplicate_content_skipped"})
            continue

        ext = os.path.splitext(src)[1]
        canonical = cl.canonical_name(src_hash, ext)
        dest = os.path.join(objects_dir, canonical)
        cl.require_within(dest, run_root)

        shutil.copy2(src, dest)

        # VERIFY BEFORE TRUST: re-read the copy, compare to ground truth.
        copy_hash = cl.sha256_file(dest)
        if copy_hash != src_hash:
            raise cl.IntegrityError(
                f"copy of {src!r} corrupted on write: "
                f"{copy_hash} != {src_hash}")

        row = {
            "ts": cl.now_iso(),
            "orig_name": os.path.basename(src),
            "canonical": canonical,
            "sha256": src_hash,
            "bytes": os.path.getsize(dest),
        }
        cl.append_jsonl(manifest_path, row)
        rows.append(row)

    return rows


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    rows = ingest(argv[1], argv[2])
    new = [r for r in rows if "note" not in r]
    dup = [r for r in rows if r.get("note")]
    print(f"ingested {len(new)} object(s), {len(dup)} duplicate(s), "
          f"{len(rows)} source file(s) accounted for")
    for r in rows:
        print(f"  {r['orig_name']} -> {r['canonical']}  {r['sha256'][:12]}"
              + ("  [dup]" if r.get("note") else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
