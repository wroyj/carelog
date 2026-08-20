#!/usr/bin/env python3
"""
carelog/demo/make_synthetic.py  --  the ONLY source of audio objects in this repo.

Generates procedural 16 kHz mono WAV files from a seed. There is deliberately no
code path here that reads a microphone, a phone, an SD card, or any real folder.
Every byte it emits is arithmetic. This is Invariant 0 made mechanical at the
source: the pipeline can only ever ingest things that were computed, never
things that were recorded.

The audio is meaningless tones -- it exists to be an *object* the handling
pipeline carries, hashes, encrypts, backs up, and restores. Nothing transcribes
it; content is irrelevant, provenance is the point.

Usage:
    python3 demo/make_synthetic.py OUTDIR [--count N] [--seed S]
"""

import os
import sys
import wave
import math
import struct
import random

SAMPLE_RATE = 16000   # matches the capture spec (16 kHz mono)
DURATION_S = 0.25     # short: these are placeholders, not real notes


def _write_tone(path, freq, seed):
    """Write one deterministic mono 16 kHz WAV of a seeded pseudo-tone."""
    rng = random.Random(seed)
    n = int(SAMPLE_RATE * DURATION_S)
    frames = bytearray()
    for i in range(n):
        # tone + a little seeded jitter so distinct seeds -> distinct bytes/hashes
        v = 0.6 * math.sin(2 * math.pi * freq * (i / SAMPLE_RATE))
        v += 0.05 * (rng.random() - 0.5)
        frames += struct.pack("<h", max(-32767, min(32767, int(v * 32767))))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(bytes(frames))


def make_synthetic(outdir, count=3, seed=1):
    """Create `count` distinct synthetic WAVs in outdir. Returns their paths."""
    os.makedirs(outdir, exist_ok=True)
    paths = []
    for i in range(count):
        freq = 220 + 55 * i                       # distinct pitch per file
        name = f"synthetic_note_{i:03d}.wav"
        p = os.path.join(outdir, name)
        _write_tone(p, freq, seed=seed * 1000 + i)
        paths.append(p)
    return paths


def main(argv):
    if len(argv) < 2 or argv[1].startswith("--"):
        print(__doc__)
        return 0
    outdir = argv[1]
    count = 3
    seed = 1
    if "--count" in argv:
        count = int(argv[argv.index("--count") + 1])
    if "--seed" in argv:
        seed = int(argv[argv.index("--seed") + 1])
    paths = make_synthetic(outdir, count=count, seed=seed)
    for p in paths:
        print(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
