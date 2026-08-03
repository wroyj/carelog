# Carelog — Milestone 1

*Built to track an elderly care-pair's journey (the person receiving care and their caregiver).*

## The idea

A local pipeline that turns a caregiver's spoken daily notes into a structured,
auditable health log. I record a short voice note → transcribe it locally with
Whisper → and an extraction module pulls out the day's numbers (weight,
intake/output, calories, sleep, rise/bed times) into a structured record. It
runs fully offline on modest hardware — nothing leaves my machines.

## Why it's built this way

Caregiving logs get used to make real decisions, so the extraction can't guess.
Three commitments are baked into the code:

1. **Evidence spans** — every value carries the verbatim transcript phrase it
   came from.
2. **Explicit nulls** — anything I didn't say stays null. No inference.
3. **Flag, don't fix** — implausible or unparseable values are flagged for my
   review, never silently corrected.

A fourth commitment falls out of the third: approximate fluid intake keeps the
*raw phrase* ("about a cup and a half") alongside any parsed number — the phrase
is the truth, the number is convenience.

## The working piece

`extract.py` — the extraction step. Transcript in → structured JSON out.
Deterministic, Python standard library only, no dependencies, no network.

## Run it

```
python3 extract.py --demo --csv                     # built-in synthetic note
python3 extract.py transcript.txt --log day_log.jsonl   # a real transcript
python3 test_extract.py                             # the discipline tests
```

`--demo` needs zero setup and shows the whole thing end to end.

## Proof it runs

See `demo_output.txt` for a captured run. On a clean note the extractor parsed
weight, calories, and times, kept the raw phrase for approximate intake, and
derived sleep duration from bed→rise. On a deliberately bad note it did the
important thing: an implausible 810 lb weight was flagged, not corrected; a
spelled-out "one thousand two hundred" calories was refused rather than guessed;
a missing bedtime stayed null.

`test_extract.py` (13 tests, all passing) exists specifically to protect the
commitments above — if a future change makes the extractor start guessing,
smoothing, or inventing values, a test fails loudly.

## Where this sits in the larger pipeline

1. Capture — voice note on phone *(done)*
2. Transcribe — Whisper local → transcript.txt *(done)*
3. **Extract — `extract.py` → structured JSON  ← this milestone**
4. Store — append records to `day_log.jsonl`
5. Render — flatten to printable daily sheet + CSV *(next)*

Two separate instruments planned but deliberately kept distinct: a task-duration
log, and phone-side reminders. Neither is folded into the health-log pipeline.

## Next

Render step (structured log → printable daily sheet), then hardening the parser
against real transcripts.
