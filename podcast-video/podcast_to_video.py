"""捲軸式逐句字幕影片：目前這句是墨黑色，前後幾句淡灰，畫面一次露出一大段方便截圖。

用法：
  python3 podcast_to_video.py 字幕.srt 音檔.mp3 封面.png 字型.otf 輸出.mp4 --ep "第 173 集"
  # 先試 60 秒：加 --start 1395 --dur 60
"""
import re, sys, subprocess, argparse
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ap = argparse.ArgumentParser()
ap.add_argument("srt"); ap.add_argument("audio"); ap.add_argument("cover"); ap.add_argument("font"); ap.add_argument("out")
ap.add_argument("--title", default="停損王"); ap.add_argument("--ep", default="")
ap.add_argument("--start", type=float, default=0); ap.add_argument("--dur", type=float, default=None)
ap.add_argument("--fps", type=int, default=30)
a = ap.parse_args()

W, H = 1920, 1080
BG = np.array([244, 239, 228], np.float32)
INK = np.array([28, 28, 28], np.float32)
PAST = np.array([165, 158, 145], np.float32)
NEXT = np.array([128, 122, 111], np.float32)
FS, LH, GAP = 64, 94, 30          # 字級、行高、句與句之間距
X0, TEXT_W = 230, 1460
ANCHOR = 400                        # 目前句子頂端停在畫面的 y
TOP, BOT = 250, 985                # 文字可見範圍

# ---------- 讀字幕、合併成「句」 ----------
def ts(s):
    h, m, r = s.strip().split(":"); sec, ms = r.split(",")
    return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000
cues = []
for b in re.split(r"\n\s*\n", open(a.srt, encoding="utf-8-sig").read().replace("\r", "").strip()):
    p = b.split("\n")
    if len(p) >= 3 and "-->" in p[1]:
        s, e = p[1].split("-->"); t = "".join(p[2:]).strip()
        if cues and cues[-1][2] == t:          # 語音辨識重複的句子直接併掉
            cues[-1][1] = ts(e); continue
        cues.append([ts(s), ts(e), t])
units = []                                     # [start, text]
for s, e, t in cues:
    if units and len(units[-1][1]) < 16 and s - units[-1][2] < 0.6 and len(units[-1][1]) + len(t) <= 34:
        units[-1][1] += "，" + t; units[-1][2] = e
    else:
        units.append([s, t, e])

font = ImageFont.truetype(a.font, FS)
def wrap(t):
    toks = re.findall(r"[A-Za-z0-9%.$'\-]+|\s+|.", t)
    lines, cur = [], ""
    for tok in toks:
        if font.getlength(cur + tok) > TEXT_W and cur:
            lines.append(cur.rstrip()); cur = tok.lstrip()
        else:
            cur += tok
    lines.append(cur); return lines
ys, y = [], 0
for u in units:
    u.append(wrap(u[1])); ys.append(y); y += len(u[3]) * LH + GAP

cache = {}
def mask(i):                                   # 句子的 alpha 遮罩，用到才畫
    if i not in cache:
        if len(cache) > 80: cache.pop(next(iter(cache)))
        ls = units[i][3]; im = Image.new("L", (TEXT_W + 40, len(ls) * LH), 0); d = ImageDraw.Draw(im)
        for k, l in enumerate(ls): d.text((0, k * LH + (LH - FS) // 2 - 6), l, font=font, fill=255)
        cache[i] = np.asarray(im, np.float32)[..., None] / 255
    return cache[i]

# ---------- 底圖 ----------
bg = Image.new("RGB", (W, H), tuple(int(v) for v in BG)); d = ImageDraw.Draw(bg)
c = Image.open(a.cover).convert("RGB"); ch = 130; cw = round(c.width * ch / c.height)
bg.paste(c.resize((cw, ch), Image.LANCZOS), (X0, 60))
d.text((X0 + cw + 32, 82), a.title, font=ImageFont.truetype(a.font, 46), fill=(28, 28, 28))
d.text((X0 + cw + 32, 145), a.ep, font=ImageFont.truetype(a.font, 32), fill=(160, 40, 40))
base = np.asarray(bg, np.float32)
# 上下邊緣漸層淡出
fade = np.ones((H, 1, 1), np.float32)
for yy in range(H):
    if yy < TOP + 90: fade[yy] = max(0, (yy - TOP) / 90)
    if yy > BOT - 160: fade[yy] = min(fade[yy], max(0, (BOT - yy) / 160))

def ease(p): return 1 - (1 - p) ** 3
starts = np.array([u[0] for u in units])
total = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", a.audio]))
dur = a.dur or total - a.start
# ---------- 右下角進度條＋時間 ----------
f_time = ImageFont.truetype(a.font, 28)
def hms(x):
    x = int(x); h, m, s = x // 3600, x % 3600 // 60, x % 60
    return f"{h}:{m:02d}:{s:02d}" if h or total >= 3600 else f"{m:02d}:{s:02d}"
RIGHT, PY, BAR_W = X0 + TEXT_W, 1022, 300
TOTAL_TXT = hms(total)
def draw_progress(fr, t):
    im = Image.fromarray(fr.astype(np.uint8)); d = ImageDraw.Draw(im)
    txt = f"{hms(t)} / {TOTAL_TXT}"
    tw = f_time.getlength(txt); d.text((RIGHT, PY), txt, font=f_time, fill=(120, 114, 103), anchor="rm")
    bx1 = RIGHT - tw - 28; bx0 = bx1 - BAR_W
    d.rounded_rectangle((bx0, PY - 3, bx1, PY + 3), 3, fill=(222, 214, 200))
    d.rounded_rectangle((bx0, PY - 3, bx0 + max(6, BAR_W * t / total), PY + 3), 3, fill=(160, 40, 40))
    return np.asarray(im, np.float32)
N = int(dur * a.fps)
ff = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(a.fps), "-i", "-",
    "-ss", str(a.start), "-t", str(dur), "-i", a.audio, "-map", "0:v", "-map", "1:a",
    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
    "-shortest", "-movflags", "+faststart", a.out], stdin=subprocess.PIPE)
prev_key, prev_buf = None, None
for f in range(N):
    t = a.start + f / a.fps
    i = max(0, int(np.searchsorted(starts, t, side="right")) - 1)
    p = min(1.0, (t - units[i][0]) / 0.45) if i > 0 else 1.0
    scroll = ys[i - 1] + (ys[i] - ys[i - 1]) * ease(p) if i > 0 else ys[0]
    key = (i, round(scroll), int(t))
    if key != prev_key:
        fr = base.copy(); off = ANCHOR - scroll
        j = i
        while j > 0 and ys[j] + off > TOP - 200: j -= 1
        while j < len(units) and ys[j] + off < BOT:
            m = mask(j); top = int(round(ys[j] + off)); h = m.shape[0]
            y0, y1 = max(top, TOP), min(top + h, BOT)
            if y1 > y0:
                col = INK if j == i else (PAST if j < i else NEXT)
                mm = m[y0 - top:y1 - top] * fade[y0:y1]
                reg = fr[y0:y1, X0:X0 + m.shape[1]]
                reg += (col - reg) * mm
            j += 1
        fr = draw_progress(fr, t)
        prev_buf = fr.astype(np.uint8).tobytes(); prev_key = key
    ff.stdin.write(prev_buf)
    if f % (a.fps * 60) == 0: print(f"{t/60:.0f} min", file=sys.stderr, flush=True)
ff.stdin.close(); ff.wait()
