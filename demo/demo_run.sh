#!/usr/bin/env bash
# carelog/demo/demo_run.sh -- the whole handling pipeline, synthetic, in a temp dir.
#
# Generates synthetic objects, ingests, encrypts at rest, backs up 3-2-1, scrubs
# for corruption, and runs a restore drill -- then prints where the receipts are.
# Touches nothing in the repo; everything lives under a fresh mktemp dir.
#
#   bash demo/demo_run.sh
#
set -euo pipefail

# Repo root = parent of this script's dir, so it runs from anywhere.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
cd "$REPO"

WORK="$(mktemp -d -t carelog_demo_XXXXXX)"
SRC="$WORK/capture"          # stands in for the phone's recordings
RUN="$WORK/run"              # the run root
LOCAL="$WORK/backup_local"   # 3-2-1: on-site copy
OFFSITE="$WORK/backup_offsite" # 3-2-1: off-site copy
mkdir -p "$RUN"

echo "== carelog demo (synthetic only) =="
echo "work dir: $WORK"
echo

echo "-- generate synthetic objects --"
python3 demo/make_synthetic.py "$SRC" --count 3 --seed 3
echo

echo "-- ingest (hash, canonical-name, verify before trust) --"
python3 ingest.py "$SRC" "$RUN"
echo

echo "-- store (encrypt at rest, round-trip verified) --"
python3 store.py "$RUN"
echo

echo "-- backup 3-2-1 (local + off-site, each verified) --"
python3 backup.py "$RUN" "$LOCAL" "$OFFSITE"
echo

echo "-- scrub (shallow, then deep) --"
python3 scrub.py "$RUN"
python3 scrub.py "$RUN" --deep
echo

echo "-- restore drill (from off-site copy) --"
python3 restore_drill.py "$RUN" "$OFFSITE"
echo

echo "== receipts =="
echo "manifest:     $RUN/manifest.jsonl"
echo "store index:  $RUN/store_index.jsonl"
echo "restore log:  $RUN/restore_log.jsonl"
echo
echo "at-rest state (ciphertext only):"
ls -1 "$RUN/store"
echo
echo "done. remove the demo tree with:  rm -rf \"$WORK\""
