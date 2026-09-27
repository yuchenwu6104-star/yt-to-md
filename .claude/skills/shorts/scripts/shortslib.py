"""Shared engine for podcast Shorts: cue-based audio EDL, subtitles, layout, rendering.

A Short spec calls configure(src, srt, badge) once, builds a Short(...) from SRT cue ranges,
and passes a visual(S, frame, t) function to S.render(). See ../examples/.
"""
import json, os, re, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1080, 1920, 30
# Noto Sans CJK (face index 3 = Traditional Chinese). Override with SHORTS_FONT_BOLD / SHORTS_FONT_REGULAR /
# SHORTS_FONT_INDEX, e.g. on macOS after `brew install --cask font-noto-sans-cjk`.
_FONT_DIRS = ["/usr/share/fonts/opentype/noto", "/usr/share/fonts/noto-cjk", os.path.expanduser("~/Library/Fonts"),
              "/Library/Fonts", "C:/Windows/Fonts"]
def _find_font(name):
    for d in _FONT_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return name
FONT_B = os.environ.get("SHORTS_FONT_BOLD") or _find_font("NotoSansCJK-Bold.ttc")
FONT_R = os.environ.get("SHORTS_FONT_REGULAR") or _find_font("NotoSansCJK-Regular.ttc")
TC = int(os.environ.get("SHORTS_FONT_INDEX", 3))
BG = (14, 20, 30)
CARD = (26, 34, 48)
CARD2 = (40, 50, 68)
FG = (245, 245, 240)
ACCENT = (255, 206, 64)
RED = (235, 72, 72)
GREEN = (80, 200, 120)
MUTED = (150, 160, 175)
PANEL = (0, 470, W, 1310)
PW, PH = PANEL[2] - PANEL[0], PANEL[3] - PANEL[1]
SRC = None     # episode audio (set by configure)
SRT = None     # corrected subtitles for the episode (set by configure)
BADGE = ""     # e.g. "停損王 EP171"
CUES = {}      # cue number -> (start_s, end_s, text)

_fonts = {}
def font(size, bold=True):
    k = (size, bold)
    if k not in _fonts:
        _fonts[k] = ImageFont.truetype(FONT_B if bold else FONT_R, size, index=TC)
    return _fonts[k]

def ease(x):
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3

# ---------------- SRT ----------------
def _ts(s):
    h, m, rest = s.split(":")
    sec, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000

def load_srt(path):
    cues = {}
    for b in open(path, encoding="utf-8-sig").read().replace("\r\n", "\n").strip().split("\n\n"):
        l = b.strip().split("\n")
        a, z = l[1].split(" --> ")
        cues[int(l[0])] = (_ts(a), _ts(z), " ".join(l[2:]).strip())
    return cues

def configure(src, srt, badge=""):
    """Point the engine at one episode: audio file, its SRT, and the badge shown top-left."""
    global SRC, SRT, BADGE
    SRC, SRT, BADGE = src, srt, badge
    CUES.clear()
    CUES.update(load_srt(srt))

# ---------------- audio analysis ----------------
def load_mono(a, b, sr=16000, pre=0.5):
    # decode from a bit earlier and drop the lead-in: mp3 seeking yields a few ms of silence at the start
    a0 = max(a - pre, 0)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{a0:.3f}", "-to", f"{b:.3f}", "-i", SRC,
                          "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(raw, np.float32)
    return x[int(round((a - a0) * sr)):]

def frames_rms(a, b, hop=0.01, sr=16000):
    x = load_mono(a, b, sr)
    n = int(hop * sr)
    return np.array([np.sqrt(np.mean(x[i:i + n] ** 2) + 1e-12) for i in range(0, max(len(x) - n + 1, 1), n)])

def silence_thr(t):
    r = frames_rms(t - 1.0, t + 1.0)
    return max(np.percentile(r, 90) * 0.06, np.percentile(r, 5) * 1.8)

def snap_min(t, win=0.12):
    r = frames_rms(t - win, t + win)
    return t - win + (int(np.argmin(r)) + 0.5) * 0.01

def refine_start(s, before=0.10, after=0.18):
    """Cue start -> the quietest 10 ms around it (SRT boundaries can sit inside the previous word's tail)."""
    r = frames_rms(s - before, s + after)
    return s - before + int(np.argmin(r)) * 0.01

def refine_end(e, pad=0.10, need=0.07, cap=0.45):
    """Walk forward from the cue end until the voice decays into silence (keeps trailing sounds),
    then add a little room, but stop before the next word starts."""
    thr = silence_thr(e)
    r = frames_rms(e - 0.10, e + cap + 0.4)
    ts = None
    quiet = 0
    for i, v in enumerate(r):
        t = e - 0.10 + i * 0.01
        quiet = quiet + 1 if v < thr else 0
        if t >= e - 0.02 and quiet * 0.01 >= need:
            ts, i0 = t - need + 0.01, i
            break
    if ts is None or ts > e + cap:
        return e + 0.05
    tv = next((e - 0.10 + j * 0.01 for j in range(i0, len(r)) if r[j] >= thr), ts + 1.0)
    return min(ts + pad, tv - 0.03)

# ---------------- word-level anchoring ----------------
_model = None
_PUNCT = re.compile(r"[\s，。！？、,.!?：:；;「」『』（）()…\-]")

def _norm(s):
    return _PUNCT.sub("", s).lower()

def local_chars(a, b):
    """Transcribe [a, b] and return [(char, start, end)] with per-character times."""
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel("small", device="cpu", compute_type="int8")
    x = load_mono(a, b)
    segs, _ = _model.transcribe(x, language="zh", word_timestamps=True, initial_prompt="以下是繁體中文的播客。")
    out = []
    for sg in segs:
        for w in sg.words:
            cs = _norm(w.word)
            for i, ch in enumerate(cs):
                d = (w.end - w.start) / max(len(cs), 1)
                out.append((ch, a + w.start + i * d, a + w.start + (i + 1) * d))
    return out

def _find(chars, key, expect, use_end):
    best = None
    for i in range(len(chars) - len(key) + 1):
        if "".join(c[0] for c in chars[i:i + len(key)]) == key:
            t = chars[i + len(key) - 1][2] if use_end else chars[i][1]
            if best is None or abs(t - expect) < abs(best - expect):
                best = t
    return best if best is not None and abs(best - expect) < 1.2 else None

def word_start(n):
    s0, _, txt = CUES[n]
    chars = local_chars(max(s0 - 1.5, 0), s0 + 2.0)
    t = _norm(txt)
    for k in (3, 2, 1):
        hit = _find(chars, t[:k], s0, False)
        if hit is not None:
            return hit
    return None

def word_end(n):
    _, e0, txt = CUES[n]
    chars = local_chars(max(e0 - 2.0, 0), e0 + 1.5)
    t = _norm(txt)
    for k in (3, 2, 1):
        hit = _find(chars, t[-k:], e0, True)
        if hit is not None:
            return hit
    return None

def clip_start(n):
    ws = word_start(n)
    if ws is None:
        return refine_start(CUES[n][0])
    r = frames_rms(ws - 0.08, ws + 0.04)
    return ws - 0.08 + int(np.argmin(r)) * 0.01

def clip_end(n):
    we = word_end(n)
    return refine_end(we if we is not None else CUES[n][1])

# ---------------- EDL ----------------
class Short:
    def __init__(self, name, title1, title2, segments, highlights=(), gap=0.12, tail=1.8, sub_override=None):
        """segments: list of (first_cue, last_cue, scene) — inclusive cue ranges from the SRT.
        Adjacent ranges are played as one continuous clip; out-of-order ranges become jump cuts."""
        assert CUES, "call configure(src, srt, badge) first"
        self.name, self.title1, self.title2 = name, title1, title2
        self.gap, self.tail = gap, tail
        self.hl = sorted(set(highlights), key=len, reverse=True)
        self.sub_override = sub_override or {}
        # adjacent cue ranges play as one continuous audio clip; only the visual scene changes
        runs = []
        for a, z, scene in segments:
            if runs and runs[-1]["z"] + 1 == a:
                runs[-1]["z"] = z
                runs[-1]["scenes"].append((a, scene))
            else:
                runs.append(dict(a=a, z=z, scenes=[(a, scene)]))
        self.clips, self.scenes = [], []
        t = 0.0
        for r in runs:
            s = clip_start(r["a"])
            e_raw = CUES[r["z"]][1]
            e = clip_end(r["z"])
            c = dict(a=r["a"], z=r["z"], s=s, e=e, t0=t, t1=t + e - s)
            self.clips.append(c)
            for j, (ca, scene) in enumerate(r["scenes"]):
                st = t if j == 0 else t + CUES[ca][0] - s
                en = c["t1"] + gap if j == len(r["scenes"]) - 1 else t + CUES[r["scenes"][j + 1][0]][0] - s
                self.scenes.append(dict(scene=scene, t0=st, t1=en))
            print(f"{name} {'/'.join(x[1] for x in r['scenes']):22s} cues {r['a']}-{r['z']}  {s:8.2f}->{e:8.2f}  (tail {e - e_raw:+.2f}s)")
            t = c["t1"] + gap
        self.dur = self.clips[-1]["t1"] + tail
        self.subs = []
        for c in self.clips:
            for n in range(c["a"], c["z"] + 1):
                cs, ce, txt = CUES[n]
                txt = self.sub_override.get(n, txt)
                if not txt:
                    continue
                a = c["t0"] + max(cs - c["s"], 0)
                b = c["t0"] + min(ce, c["e"]) - c["s"]
                self.subs.append([a, b, self.mark(txt)])
        for i in range(len(self.subs) - 1):  # hold each line until the next one if the gap is short
            if self.subs[i + 1][0] - self.subs[i][1] < 0.35:
                self.subs[i][1] = self.subs[i + 1][0]

    def mark(self, txt):
        for h in self.hl:
            txt = re.sub(r"(?<!\[)" + re.escape(h) + r"(?![^\[]*\])", "[" + h + "]", txt, count=1)
        return txt

    def clip_at(self, t):
        """The scene segment active at timeline time t: dict(scene, t0, t1)."""
        for c in self.scenes:
            if c["t0"] <= t < c["t1"]:
                return c
        return self.scenes[-1]

    def span(self, *scenes):
        cs = [c for c in self.scenes if c["scene"] in scenes]
        return cs[0]["t0"], cs[-1]["t1"]

    def cue_time(self, n):
        """Timeline time at which SRT cue n starts."""
        for c in self.clips:
            if c["a"] <= n <= c["z"]:
                return c["t0"] + max(CUES[n][0] - c["s"], 0)
        raise KeyError(n)

    # ---- audio ----
    def build_audio(self, out):
        filt, labels = [], []
        for i, c in enumerate(self.clips):
            d = c["e"] - c["s"]
            filt.append(f"[0:a]atrim={c['s']:.3f}:{c['e']:.3f},asetpts=PTS-STARTPTS,"
                        f"afade=t=in:d=0.01,afade=t=out:st={d - 0.06:.3f}:d=0.06,apad=pad_dur={self.gap}[a{i}]")
            labels.append(f"[a{i}]")
        filt.append("".join(labels) + f"concat=n={len(self.clips)}:v=0:a=1,apad=pad_dur={self.tail},"
                    f"atrim=0:{self.dur:.3f},loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[aout]")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", SRC, "-filter_complex", ";".join(filt),
                        "-map", "[aout]", "-c:a", "pcm_s16le", out], check=True)

    # ---- chrome ----
    def base(self):
        im = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(im)
        if BADGE:
            bw = d.textlength(BADGE, font=font(34)) + 56
            d.rounded_rectangle((60, 92, 60 + bw, 150), 29, fill=ACCENT)
            d.text((60 + bw / 2, 121), BADGE, font=font(34), fill=BG, anchor="mm")
        fs = 92 if max(d.textlength(self.title1, font=font(92)), d.textlength(self.title2, font=font(92))) < W - 120 else 80
        d.text((60, 205), self.title1, font=font(fs), fill=FG, anchor="lm")
        d.text((60, 330), self.title2, font=font(fs), fill=ACCENT, anchor="lm")
        return im

    def draw_subs(self, frame, t):
        cur = [s for s in self.subs if s[0] <= t < s[1]]
        if not cur:
            return
        a, b, txt = cur[0]
        d = ImageDraw.Draw(frame)
        k = ease((t - a) / 0.12)
        size = int(68 * (0.92 + 0.08 * k))
        lines = wrap_rich(d, txt, size, W - 120)
        y0 = 1500 - (len(lines) - 1) * 46
        for i, ln in enumerate(lines):
            rich(d, (W / 2, y0 + i * 94), ln, size, stroke=7)

    def draw_progress(self, frame, t):
        d = ImageDraw.Draw(frame)
        d.rectangle((0, H - 14, W, H), fill=(35, 44, 60))
        d.rectangle((0, H - 14, W * t / self.dur, H), fill=ACCENT)

    # ---- render ----
    def render(self, draw_visual):
        base = self.base()
        def frame_at(t):
            fr = base.copy()
            draw_visual(self, fr, t)
            self.draw_subs(fr, t)
            self.draw_progress(fr, t)
            return fr
        if os.environ.get("PREVIEW"):
            ts = [float(x) for x in os.environ["PREVIEW"].split(",")]
            tiles = [frame_at(t).resize((W // 3, H // 3)) for t in ts]
            sheet = Image.new("RGB", (W // 3 * len(tiles), H // 3), "white")
            for i, tl in enumerate(tiles):
                sheet.paste(tl, (i * W // 3, 0))
            sheet.save(f"preview_{self.name}.jpg")
            print("DUR", round(self.dur, 1), "preview_" + self.name + ".jpg")
            return
        wav = f"audio_{self.name}.wav"
        self.build_audio(wav)
        out = f"{self.name}.mp4"
        enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                                "-r", str(FPS), "-i", "-", "-i", wav, "-c:v", "libx264", "-preset", "medium",
                                "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest",
                                "-movflags", "+faststart", out], stdin=subprocess.PIPE)
        n = int(self.dur * FPS)
        for i in range(n):
            enc.stdin.write(frame_at(i / FPS).tobytes())
        enc.stdin.close()
        enc.wait()
        json.dump(dict(duration=self.dur, clips=self.clips, scenes=self.scenes, subs=self.subs), open(f"{self.name}_edl.json", "w"),
                  ensure_ascii=False, indent=1)
        print("done", out, f"{self.dur:.1f}s")

# ---------------- text helpers ----------------
def rich(draw, xy, text, size, color=FG, hi=ACCENT, stroke=6, bold=True):
    f = font(size, bold)
    parts, cur = [], ""
    for ch in text:
        if ch in "[]":
            parts.append((cur, ch == "]"))
            cur = ""
        else:
            cur += ch
    parts.append((cur, False))
    parts = [(p, h) for p, h in parts if p]
    widths = [draw.textlength(p, font=f) for p, _ in parts]
    x = xy[0] - sum(widths) / 2
    for (p, h), w in zip(parts, widths):
        draw.text((x, xy[1]), p, font=f, fill=hi if h else color, anchor="lm", stroke_width=stroke, stroke_fill=(0, 0, 0))
        x += w

def wrap_rich(draw, text, size, maxw):
    plain = text.replace("[", "").replace("]", "")
    if draw.textlength(plain, font=font(size)) <= maxw:
        return [text]
    best, depth = None, 0
    for i, ch in enumerate(text):
        if ch == "[":
            depth += 1
        if ch == "]":
            depth -= 1
        if depth == 0 and 0 < i < len(text) - 1 and not (text[i].isascii() and text[i - 1].isascii() and text[i].isalnum() and text[i - 1].isalnum()):
            # prefer natural break points: before a highlight, after particles / punctuation
            bonus = 3 if text[i] == "[" or text[i - 1] in "的了是就在有和跟說，、 ]" else 0
            score = abs(i - len(text) / 2) - bonus
            if best is None or score < best[0]:
                best = (score, i)
    i = best[1]
    return [text[:i].strip(), text[i:].strip()]

def text_c(d, xy, s, size, fill=FG, bold=True, anchor="mm"):
    d.text(xy, s, font=font(size, bold), fill=fill, anchor=anchor)

def chip(d, xy, text, fill=(0, 0, 0, 180), color=FG, size=38):
    w = d.textlength(text, font=font(size))
    x, y = xy
    d.rounded_rectangle((x, y, x + w + 44, y + size + 30), 16, fill=fill)
    d.text((x + 22, y + (size + 30) / 2), text, font=font(size), fill=color, anchor="lm")

def card(frame):
    d = ImageDraw.Draw(frame, "RGBA")
    d.rounded_rectangle((40, PANEL[1], W - 40, PANEL[3]), 36, fill=CARD)
    return d

def xmark(d, cx, cy, r=38, fill=RED):
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill)
    k = r * 0.47
    d.line((cx - k, cy - k, cx + k, cy + k), fill=(255, 255, 255), width=9)
    d.line((cx + k, cy - k, cx - k, cy + k), fill=(255, 255, 255), width=9)

def check(d, cx, cy, r=38, fill=GREEN):
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill)
    d.line((cx - r * 0.45, cy, cx - r * 0.1, cy + r * 0.35, cx + r * 0.5, cy - r * 0.35), fill=(255, 255, 255), width=9, joint="curve")

def arrow(d, p0, p1, fill=MUTED, width=8, head=22):
    import math
    d.line((p0, p1), fill=fill, width=width)
    ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
    a1, a2 = ang + 2.6, ang - 2.6
    d.polygon([p1, (p1[0] + head * math.cos(a1), p1[1] + head * math.sin(a1)),
               (p1[0] + head * math.cos(a2), p1[1] + head * math.sin(a2))], fill=fill)

# ---------------- photos ----------------
def load_cover(path, crop=(0, 0, 0, 0)):
    im = Image.open(path).convert("RGB")
    l, t, r, b = crop
    im = im.crop((int(im.width * l), int(im.height * t), int(im.width * (1 - r)), int(im.height * (1 - b))))
    tw, th = int(PW * 1.18), int(PH * 1.18)
    s = max(tw / im.width, th / im.height)
    return im.resize((int(im.width * s) + 1, int(im.height * s) + 1), Image.LANCZOS)

def kenburns(im, p, zoom=(1.0, 1.12), pan=(0.5, 0.5, 0.5, 0.5)):
    p = min(max(p, 0), 1)
    z = zoom[0] + (zoom[1] - zoom[0]) * p
    cw, ch = min(PW * 1.18 / z, im.width), min(PH * 1.18 / z, im.height)
    cx = (pan[0] + (pan[2] - pan[0]) * p) * im.width
    cy = (pan[1] + (pan[3] - pan[1]) * p) * im.height
    x0 = min(max(cx - cw / 2, 0), im.width - cw)
    y0 = min(max(cy - ch / 2, 0), im.height - ch)
    return im.resize((PW, PH), Image.BILINEAR, box=(x0, y0, x0 + cw, y0 + ch))

def photo(frame, im, credit, p, **kw):
    frame.paste(kenburns(im, p, **kw), PANEL[:2])
    d = ImageDraw.Draw(frame, "RGBA")
    d.text((PANEL[2] - 16, PANEL[3] - 12), credit, font=font(20, False), fill=(230, 230, 230),
           anchor="rd", stroke_width=2, stroke_fill=(0, 0, 0))
    return d
