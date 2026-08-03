#!/usr/bin/env python3
"""
carelog/extract.py  --  daily caregiving-log extractor

Takes a Whisper transcript (plain text) of one day's voice note and emits a
single structured day-record. Runs fully offline, stdlib only, on the T410.

Design commitments (deliberate, not incidental):
  1. EVIDENCE SPANS   every populated value carries the verbatim transcript
                      substring that produced it. No value without a source.
  2. EXPLICIT NULLS   fields you didn't mention are null, never inferred.
  3. FLAG DON'T FIX   implausible / unparseable values are flagged for your
                      review, never silently corrected or smoothed.
  4. KEEP THE PHRASE  approximate I/O keeps the raw words AND a parsed number;
                      the phrase is the truth, the number is convenience.

Usage:
    python3 extract.py transcript.txt          # extract one file -> stdout JSON
    python3 extract.py transcript.txt --log day_log.jsonl   # also append
    python3 extract.py --demo                   # run on a built-in synthetic note
    python3 extract.py --demo --csv             # demo + show the flattened CSV row
"""

import re
import sys
import json
import datetime as _dt

# --------------------------------------------------------------------------
# CONFIG  -- edit these; they are the only "opinions" in the file.
# Units are stated here so they are never silently assumed elsewhere.
# --------------------------------------------------------------------------
UNITS = {"weight": "lb", "io": "mL", "calories": "kcal"}

# Plausibility ranges. Values OUTSIDE these are FLAGGED, not changed.
# Tune to her actual baseline; these are deliberately wide.
PLAUSIBLE = {
    "weight_lb":  (60, 400),
    "calories":   (0, 6000),
    "intake_mL":  (0, 6000),
    "output_mL":  (0, 6000),
}


# --------------------------------------------------------------------------
# Field container -- the shape every extracted field takes.
# --------------------------------------------------------------------------
def field(value=None, evidence=None, flags=None, **extra):
    f = {"value": value, "evidence": evidence, "flags": list(flags or [])}
    f.update(extra)
    return f


def _flag_if_implausible(f, key):
    """Attach needs_review if a numeric value falls outside its plausible range."""
    if f["value"] is None or key not in PLAUSIBLE:
        return f
    lo, hi = PLAUSIBLE[key]
    if not (lo <= f["value"] <= hi):
        f["flags"].append("needs_review:out_of_range")
    return f


# --------------------------------------------------------------------------
# Individual parsers. Each returns a field(). Each is deterministic.
# --------------------------------------------------------------------------
def parse_weight(t):
    # "181", "181.4", "one eighty-one" -> we parse DIGITS only. Word-forms are
    # flagged for review rather than risk mis-hearing "one eighty-one" as 180.
    m = re.search(r"(\d{2,3}(?:\.\d)?)\s*(?:lb|lbs|pounds?)\b", t, re.I)
    if not m:
        m = re.search(r"\bweigh(?:ed|s|t)?\b[^.\d]{0,15}(\d{2,3}(?:\.\d)?)", t, re.I)
    if m:
        f = field(float(m.group(1)), m.group(0).strip())
        return _flag_if_implausible(f, "weight_lb")
    # A spelled-out number near "weigh" is real signal but risky -> flag, don't parse.
    if re.search(r"\bweigh", t, re.I):
        return field(None, None, ["needs_review:weight_mentioned_not_parsed"])
    return field()


def parse_calories(t):
    m = re.search(r"(\d{3,4})\s*(?:cal|cals|calories|kcal)\b", t, re.I)
    if m:
        return _flag_if_implausible(field(int(m.group(1)), m.group(0).strip()), "calories")
    if re.search(r"\bcalorie", t, re.I):
        return field(None, None, ["needs_review:calories_mentioned_not_parsed"])
    return field()


_TIME_RE = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?", re.I)


def _parse_clock(span):
    """Parse a single clock time to 'HH:MM' 24h, or None if ambiguous."""
    m = _TIME_RE.search(span)
    if not m:
        return None
    h = int(m.group(1))
    mn = int(m.group(2) or 0)
    ap = (m.group(3) or "").lower().replace(".", "")
    if ap == "pm" and h != 12:
        h += 12
    elif ap == "am" and h == 12:
        h = 0
    if not (0 <= h <= 23 and 0 <= mn <= 59):
        return None
    return f"{h:02d}:{mn:02d}"


def parse_rise(t):
    m = re.search(r"\b(?:woke|got up|rose|up at|rise)\b[^.\d]{0,12}"
                  r"(\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?)", t, re.I)
    if m:
        clock = _parse_clock(m.group(1))
        if clock:
            return field(clock, m.group(0).strip())
        return field(None, m.group(0).strip(), ["needs_review:rise_unparseable"])
    return field()


def parse_bed(t):
    m = re.search(r"\b(?:bed|went to bed|turned in|asleep|lights out)\b[^.\d]{0,12}"
                  r"(\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?)", t, re.I)
    if m:
        clock = _parse_clock(m.group(1))
        if clock:
            return field(clock, m.group(0).strip())
        return field(None, m.group(0).strip(), ["needs_review:bedtime_unparseable"])
    return field()


def parse_io(t, kind):
    """Intake / output. These are APPROXIMATE by design: keep the phrase,
    attach a parsed mL estimate only when a clear number+unit is present."""
    if kind == "intake":
        cue = r"(?:intake|drank|fluids?\s+in|took in|\bin\b)"
    else:
        cue = r"(?:output|urine|void(?:ed)?|\bout\b)"
    m = re.search(cue + r"[^.]{0,40}", t, re.I)
    if not m:
        return field()
    phrase = m.group(0).strip()
    flags = ["approximate"]
    num = re.search(r"(\d{2,4})\s*(?:ml|mls|cc)\b", phrase, re.I)
    if num:
        f = field(int(num.group(1)), phrase, flags, phrase=phrase)
        return _flag_if_implausible(f, f"{kind}_mL")
    # phrase present but no clean number -> value null, phrase preserved, review it
    flags.append("needs_review:io_phrase_only")
    return field(None, phrase, flags, phrase=phrase)


def parse_sleep(t):
    """Free-text sleep QUALITY. This is the one field where a phrase, not a
    number, is the real content. Duration is derived separately from bed->rise."""
    m = re.search(r"\bslept\b[^.]{0,50}", t, re.I)
    if not m:
        m = re.search(r"\bsleep\b[^.]{0,50}", t, re.I)
    if m:
        return field(m.group(0).strip(), m.group(0).strip())
    return field()


def derive_sleep_duration(bed, rise):
    """Duration from bedtime -> rise time, in minutes. Flags if it can't be
    derived. Does NOT invent either endpoint."""
    if not (bed["value"] and rise["value"]):
        return field(None, None, ["derived:missing_endpoint"]
                     if (bed["value"] or rise["value"]) else [])
    b = _dt.datetime.strptime(bed["value"], "%H:%M")
    r = _dt.datetime.strptime(rise["value"], "%H:%M")
    minutes = int(((r - b).seconds if r > b else
                   (r + _dt.timedelta(days=1) - b).seconds) / 60)
    flags = ["derived"]
    if not (120 <= minutes <= 900):  # <2h or >15h -> look again
        flags.append("needs_review:duration_implausible")
    return field(minutes, f"{bed['value']}->{rise['value']}", flags)


def parse_date(t):
    # Explicit ISO date wins.
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", t)
    if m:
        return field(m.group(1), m.group(1))
    # No date stated -> default to today, but FLAG the assumption (not silent).
    today = _dt.date.today().isoformat()
    return field(today, None, ["date_assumed_today"])


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------
def extract(transcript, source=None):
    t = transcript.strip()
    bed = parse_bed(t)
    rise = parse_rise(t)
    rec = {
        "source": source,
        "extracted_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "units": UNITS,
        "transcript": t,
        "fields": {
            "date":       parse_date(t),
            "weight_lb":  parse_weight(t),
            "intake":     parse_io(t, "intake"),
            "output":     parse_io(t, "output"),
            "calories":   parse_calories(t),
            "rise_time":  rise,
            "bedtime":    bed,
            "sleep_quality":  parse_sleep(t),
            "sleep_minutes":  derive_sleep_duration(bed, rise),
        },
    }
    # Roll a review summary up to the top so flags aren't buried.
    review = {k: v["flags"] for k, v in rec["fields"].items()
              if any(fl.startswith("needs_review") for fl in v["flags"])}
    rec["needs_review"] = review
    return rec


CSV_COLUMNS = ["date", "weight_lb", "intake", "output", "calories",
               "rise_time", "bedtime", "sleep_minutes", "sleep_quality",
               "flags"]


def to_csv_row(rec):
    f = rec["fields"]
    def v(k): return "" if f[k]["value"] is None else f[k]["value"]
    flags = ";".join(f"{k}:{','.join(fl)}" for k, fl in rec["needs_review"].items())
    cells = [v("date"), v("weight_lb"), v("intake"), v("output"),
             v("calories"), v("rise_time"), v("bedtime"),
             v("sleep_minutes"), v("sleep_quality"), flags]
    return ",".join('"%s"' % str(c).replace('"', '""') if "," in str(c) or '"' in str(c)
                    else str(c) for c in cells)


DEMO = ("Log for 2025-08-02. She weighed 181 pounds this morning. "
        "Intake about a cup and a half of water, output looked low. "
        "Roughly 1400 calories today. Woke at 6:30 am, went to bed around 10:45 pm. "
        "Slept poorly, up a couple of times.")


def main(argv):
    args = argv[1:]
    csv_flag = "--csv" in args
    log_path = None
    if "--log" in args:
        log_path = args[args.index("--log") + 1]

    if "--demo" in args:
        rec = extract(DEMO, source="demo")
    elif args and not args[0].startswith("--"):
        with open(args[0]) as fh:
            rec = extract(fh.read(), source=args[0])
    else:
        print(__doc__)
        return 0

    print(json.dumps(rec, indent=2))
    if csv_flag:
        print("\n# CSV row (" + ",".join(CSV_COLUMNS) + "):")
        print(to_csv_row(rec))
    if log_path:
        with open(log_path, "a") as fh:
            fh.write(json.dumps(rec) + "\n")
        print(f"\n# appended to {log_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
