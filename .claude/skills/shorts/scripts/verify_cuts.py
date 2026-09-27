"""Re-transcribe a rendered Short and print what is heard at the start and end of every clip.

Usage (from the work dir, after rendering):
    python verify_cuts.py <short_name>

Reads <short_name>_edl.json and audio_<short_name>.wav. A clean cut shows the clip's own first words on the
left and its own last words on the right. Whisper often files the *next* clip's first word (因為 / 可是 / 我們)
under the previous clip's end because of the 0.12 s gap — check that against the next line's start before
treating it as a leak.
"""
import json, sys
from faster_whisper import WhisperModel

name = sys.argv[1]
edl = json.load(open(f"{name}_edl.json"))
m = WhisperModel("small", device="cpu", compute_type="int8")
segs, _ = m.transcribe(f"audio_{name}.wav", language="zh", initial_prompt="以下是繁體中文的播客。", word_timestamps=True)
words = [w for s in segs for w in s.words]
for c in edl["clips"]:
    before = "".join(w.word for w in words if c["t1"] - 1.2 <= w.start < c["t1"] + 0.05)
    after = "".join(w.word for w in words if c["t0"] - 0.05 <= w.start < c["t0"] + 1.0)
    print(f"{c['t0']:6.1f}-{c['t1']:6.1f}  cues {c['a']}-{c['z']}  starts: {after:18s} | ends: {before}")
