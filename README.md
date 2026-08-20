# carelog — care-logging infrastructure (synthetic reference)

> ## Invariant 0 — Rule One
> **No data describing a real human being comes anywhere near this repository.**
> Not in the code, not in a recording, transcript, manifest, log, or example.
> Every byte here is procedurally generated. This ranks above the spec, the
> class deliverable, and convenience.

## Two systems, kept apart

This repo is **infrastructure**, not an operational log: the software and the
tested safe-handling pipeline for a care-logging system — developed, tested, and
demonstrated **entirely on synthetic data**. It is the vibe-coding-class
deliverable.

The **actual care-logging system** — the one that ever touches a real person's
recordings — is a **separate deployment kept in the home**: offline, air-gapped,
private. It is not this repo, does not sync to it, and no real recording,
transcript, or derived value ever crosses into it.

```
   this repo (public, synthetic)          home system (private, real data)
   ─────────────────────────────         ────────────────────────────────
   code + tested pipeline    ───────▶     runs the same code on real notes
   never receives real data  ◀──✗──       real data stays here, offline
```

Software flows out. **Real data never flows back.** Anything a grader, a
stranger cloning the repo, or an AI assistant can see is synthetic by
construction.

## What the infrastructure does

A recording is treated as **opaque bytes** and carried safely end to end. Every
stage below is a real, runnable module in this repo:

| Stage | Module | What it guarantees |
|-------|--------|--------------------|
| **Capture** | `demo/make_synthetic.py` | The only source of objects here. Procedural, seeded 16 kHz mono WAVs. No real-input code path exists. |
| **Ingest** | `ingest.py` | Copy → sha256 → canonical name → manifest row → **re-read & verify before trusting the copy**. No silent drops. |
| **Store** | `store.py` | Encrypt at rest (age/gpg), **round-trip verified** against the manifest hash; plaintext removed after verify. |
| **Backup** | `backup.py` | 3-2-1 to local + off-site (restic/tar), each copy **restored to a temp area and integrity-checked**. |
| **Scrub** | `scrub.py` | Recompute hashes vs the receipts; **flag** bit-rot/corruption, never auto-repair. |
| **Restore** | `restore_drill.py` | Restore → decrypt → verify every object vs manifest → append PASS/FAIL to a restore log. |
| **Extract** | `extract.py` | Transcript → structured record. Deterministic, stdlib-only, no network. |
| **Shared** | `carelib.py` | Path guard, hashing, append-only receipts, backend detection — the guarantees, defined once. |

Preferred backends `age` + `restic` are used when installed; `gpg` + `tar`
fallbacks let the demo run anywhere. There is **no** documented way to run any of
this against real input — that happens only on the separate home system.

Hardware, the operational deployment, and open build decisions are described in
`INFRASTRUCTURE.md` (reference architecture — no real data).

## The discipline (shared across every stage)

Care logs get used to make real decisions, so nothing in the pipeline may guess:

1. **Evidence / verbatim** — a parsed value keeps the raw phrase it came from; the phrase is the truth, the number is convenience.
2. **Explicit nulls** — anything not stated stays null. No inference, no backfill.
3. **Flag, don't fix** — implausible or unparseable input is flagged for human review, never silently corrected.
4. **Verify before trust** — every copy, encryption, and restore is re-read and checked against a sha256 ground truth.
5. **No silent drops** — the manifest is the receipt for every object; counts are conserved end to end.

## Run it (synthetic only)

```bash
bash demo/demo_run.sh            # full handling pipeline, temp dir, synthetic data
python3 extract.py --demo --csv  # extraction on the built-in synthetic note

python3 test_no_real_data.py     # Invariant 0 guards
python3 test_pipeline.py         # end-to-end + corruption/tamper caught
python3 test_extract.py          # extraction discipline tests
```

`demo/demo_run.sh` needs `gpg` and `tar` (the fallbacks), present on most
systems. `test_pipeline.py` skips cleanly if they're absent.

## Invariant 0 enforcement (structural, not a promise)

- **Single synthetic source** — `demo/make_synthetic.py` computes its objects
  from a seed; no code path reads a phone, an SD card, or a real folder.
  `test_no_real_data.py` asserts the generator is deterministic (computed, not
  recorded).
- **Path guard** — `carelib.require_within` refuses any path outside the
  sanctioned run root, symlinks and `..` resolved. Tested against escapes.
- **Default-deny `.gitignore`** — an allowlist. Stray recordings, transcripts,
  receipts, and encrypted objects can't be `git add .`-ed by accident.
- **`test_no_real_data.py`** — fails the build if any of these properties break.

**Honest limit:** a guard test makes the compliant path the *only wired* path and
adds loud tripwires; it cannot stop a human pasting real text by hand. The real
guarantee is the physical separation above — the system that sees real data is a
different machine in a different place.
