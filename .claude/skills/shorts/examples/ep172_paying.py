"""Short: 付錢用 AI 的人只有 4.5% — 停損王 EP172."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
from shortslib import *

# run from the work dir:  SRT=<episode.srt> python <this file>   (audio at ./ep172.mp3, photos in ./img)
configure(os.environ.get("SRC", "ep172.mp3"), os.environ["SRT"], "停損王 EP172")

S = Short(
    "short_paying", "付錢用 AI 的人只有 4.5%", "前 1% 每月花 900 美元",
    [
        (1175, 1183, "funnel"),
        (1185, 1195, "growth"),
        (1204, 1212, "dist"),
        (1223, 1228, "dist"),
        (1235, 1243, "spend"),
        (1255, 1260, "end"),
    ],
    highlights=["50%", "25%", "4.5%", "兩倍", "1%", "2%", "20%", "一半", "超過50%", "16%", "900塊美元", "900美金",
                "25美元", "極端不平衡", "10%"],
)

def visual(S, fr, t):
    c = S.clip_at(t)
    sc, lt = c["scene"], t - c["t0"]
    d = card(fr)
    if sc == "funnel":
        k = ease((t - 0.2) / 0.3)  # hook from the first second
        text_c(d, (540, 560), "100 個美國人裡", 54, fill=(245, 245, 240, int(255 * k)))
        text_c(d, (540, 640), "幾個人付錢用 AI？", 54, fill=(255, 206, 64, int(255 * k)))
        t50, t25, t45 = S.cue_time(1175), S.cue_time(1177), S.cue_time(1180) + 0.3
        x0, y0, step, r = 288, 700, 56, 20
        for i in range(100):
            row_, col_ = divmod(i, 10)
            cx, cy = x0 + col_ * step, y0 + row_ * step
            fill = (55, 66, 86)
            if t >= t50 and i < 50:
                fill = (95, 110, 135)
            if t >= t25 and i < 25:
                fill = (150, 165, 190)
            if t >= t45 and i < 4:
                fill = ACCENT
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill)
            if t >= t45 and i == 4:  # half a person
                d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(150, 165, 190))
                d.pieslice((cx - r, cy - r, cx + r, cy + r), 90, 270, fill=ACCENT)
        legend = [("用過 AI", "50%", (95, 110, 135), t50), ("每天用", "25%", (150, 165, 190), t25), ("有付錢", "4.5%", ACCENT, t45)]
        for j, (lab, v, col, st) in enumerate(legend):
            kk = ease((t - st) / 0.3)
            if kk > 0:
                x = 150 + j * 270
                d.ellipse((x, 1255, x + 30, 1285), fill=col)
                d.text((x + 44, 1270), f"{lab} {v}", font=font(36), fill=(245, 245, 240, int(255 * kk)), anchor="lm")
    elif sc == "growth":
        text_c(d, (540, 570), "付費比例：一年翻一倍", 56)
        bars = [("2024", 0.9, "不到 1%", S.cue_time(1190)), ("2025", 2.0, "約 2%", S.cue_time(1192)), ("2026", 4.5, "4.5%", S.cue_time(1195))]
        base_y, maxh = 1200, 500
        for i, (yr, v, lab, st) in enumerate(bars):
            k = ease((t - st) / 0.5) if i else ease((t - S.cue_time(1187)) / 0.5)
            x = 210 + i * 250
            text_c(d, (x + 80, base_y + 50), yr, 42, fill=MUTED)
            if k > 0:
                h = maxh * v / 4.5 * k
                col = ACCENT if i == 2 else (120, 135, 160)
                d.rounded_rectangle((x, base_y - h, x + 160, base_y), 16, fill=col)
                text_c(d, (x + 80, base_y - h - 45), lab, 44, fill=col)
        d.line((150, base_y, 930, base_y), fill=(70, 80, 100), width=4)
    elif sc == "dist":
        text_c(d, (540, 565), "AI 付費收入，集中在誰身上？", 52)
        text_c(d, (540, 630), "統計範圍：所有 AI app 與網頁（a16z）", 32, fill=MUTED, bold=False)
        rows = [("前 1% 付費用戶", 20, "20%", S.cue_time(1212), ACCENT),
                ("前 10% 付費用戶", 52, "超過 50%", S.cue_time(1224), ACCENT),
                ("後 50% 付費用戶", 16, "16%", S.cue_time(1228), (120, 135, 160))]
        for i, (lab, v, txt, st, col) in enumerate(rows):
            k = ease((t - st) / 0.5)
            y = 760 + i * 180
            d.text((110, y), lab, font=font(44), fill=FG if k > 0 else MUTED, anchor="lm")
            d.rounded_rectangle((110, y + 40, 970, y + 110), 16, fill=CARD2)
            if k > 0:
                wv = 860 * v / 100 * k
                d.rounded_rectangle((110, y + 40, 110 + max(wv, 24), y + 110), 16, fill=col)
                d.text((110 + max(wv, 24) + 20, y + 75), txt, font=font(44), fill=col, anchor="lm")
        text_c(d, (540, 1270), "貢獻收入佔比", 32, fill=MUTED, bold=False)
    elif sc == "spend":
        text_c(d, (540, 570), "每月花在 AI 的錢", 56)
        k1 = ease((t - S.cue_time(1237)) / 0.6)
        k2 = ease((t - S.cue_time(1240)) / 0.4)
        k3 = ease((t - S.cue_time(1242)) / 0.4)
        d.text((110, 700), "最頂端 1%", font=font(44), fill=FG, anchor="lm")
        if k1 > 0:
            d.rounded_rectangle((110, 740, 110 + 860 * k1, 840), 18, fill=ACCENT)
            d.text((940, 790), f"${int(900 * k1)}", font=font(64), fill=BG, anchor="rm")
        d.text((110, 930), "付費者中位數", font=font(44), fill=FG if k2 > 0 else MUTED, anchor="lm")
        if k2 > 0:
            d.rounded_rectangle((110, 970, 110 + 860 * 25 / 900 + 6, 1070), 10, fill=(120, 135, 160))
            d.text((170, 1020), "$25", font=font(64), fill=(245, 245, 240, int(255 * k2)), anchor="lm")
            text_c(d, (720, 1020), "差 36 倍", 60, fill=(235, 72, 72, int(255 * k2)))
        if k3 > 0:
            text_c(d, (540, 1200), "$25 ≈ 一個 ChatGPT 基本方案", 42, fill=(150, 160, 175, int(255 * k3)), bold=False)
    elif sc == "end":
        k1 = ease((t - S.cue_time(1259)) / 0.4)
        k2 = ease((t - S.cue_time(1260)) / 0.4)
        text_c(d, (540, 640), "重度用戶付的錢", 54)
        text_c(d, (540, 720), "比大部分人多非常多", 54)
        if k1 > 0:
            text_c(d, (540, 900), "極端不平衡", 120, fill=(235, 72, 72, int(255 * k1)))
        if k2 > 0:
            text_c(d, (540, 1060), "集中在最前面的 10%", 60, fill=(255, 206, 64, int(255 * k2)))
        if t > S.clips[-1]["t1"]:
            text_c(d, (540, 1270), "完整內容：停損王 EP172", 32, fill=MUTED, bold=False)

S.render(visual)
