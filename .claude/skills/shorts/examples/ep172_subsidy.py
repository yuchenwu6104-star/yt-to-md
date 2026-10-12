"""Short: 月費 200 美元用出 12000，AI 公司其實還在賺 — 停損王 EP172."""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
from shortslib import *
from commons import credit

# run from the work dir:  SRT=<episode.srt> python <this file>   (audio at ./ep172.mp3, photos in ./img)
configure(os.environ.get("SRC", "ep172.mp3"), os.environ["SRT"], "停損王 EP172")

S = Short(
    "short_subsidy", "月費 200 美元用出 12000", "AI 公司其實還在賺",
    [
        (1709, 1712, "hook"),
        (1713, 1726, "api"),
        (1740, 1753, "buffet"),
        (1754, 1762, "omakase"),
        (1763, 1769, "basis"),
        (1797, 1800, "notreally"),
        (1809, 1821, "gym"),
        (1822, 1834, "empty"),
        (1853, 1858, "ten"),
        (1859, 1870, "margin"),
    ],
    highlights=["200塊美金", "12000美金", "API", "60倍", "吃到飽", "無菜單日本料理", "其實沒有", "健身房", "用回本",
                "空置率", "賭你不會", "10%", "50%", "60%的毛利率", "有賺頭"],
)

def pic(tag, i):
    return load_cover(f"img/{tag}_{i}.jpg"), credit(json.load(open(f"img/{tag}.json"))[i])
BUF, OMA, GYM = pic("buffet", 3), pic("omakase", 4), pic("gym2", 2)

def money(d, xy, s, size, col):
    text_c(d, xy, s, size, fill=col)

def visual(S, fr, t):
    c = S.clip_at(t)
    sc, lt = c["scene"], t - c["t0"]
    if sc in ("buffet", "omakase", "empty"):
        im, cr = {"buffet": BUF, "omakase": OMA, "empty": GYM}[sc]
        a, b = c["t0"], c["t1"]
        d = photo(fr, im, cr, (t - a) / max(b - a, 0.1))
        d.rectangle((0, 470, W, 640), fill=(0, 0, 0, 120))
        if sc == "buffet":
            chip(d, (70, 500), "吃到飽餐廳：付 $200", fill=(14, 20, 30, 220), size=50)
            if t >= S.cue_time(1747):
                chip(d, (70, 1150), "吃了什麼、吃多少，全部記下來", fill=(14, 20, 30, 220), size=42)
        elif sc == "omakase":
            chip(d, (70, 500), "同樣的量，照無菜單日料單點", fill=(14, 20, 30, 220), size=46)
            k = ease((t - S.cue_time(1760)) / 0.4)
            if k > 0:
                d.rounded_rectangle((200, 900, 880, 1100), 30, fill=(14, 20, 30, int(230 * k)))
                text_c(d, (540, 1000), "$12,000", 120, fill=(255, 206, 64, int(255 * k)))
        else:
            chip(d, (70, 500), "會員很多，但每天都很空", fill=(14, 20, 30, 220), size=48)
            k = ease((t - S.cue_time(1832)) / 0.4)
            if k > 0:
                d.rounded_rectangle((120, 1000, 960, 1180), 30, fill=(14, 20, 30, int(230 * k)))
                text_c(d, (540, 1090), "賭你不會全部都來", 72, fill=(255, 206, 64, int(255 * k)))
        return
    d = card(fr)
    if sc == "hook":
        k = ease((t - 0.2) / 0.35)  # hook from the first second
        text_c(d, (540, 600), "Claude Code 月費", 52, fill=(150, 160, 175, int(255 * k)), bold=False)
        text_c(d, (540, 720), "$200", 140, fill=(245, 245, 240, int(255 * k)))
        k2 = ease((t - S.cue_time(1711)) / 0.4)
        if k2 > 0:
            arrow(d, (540, 820), (540, 940), fill=ACCENT, width=10, head=30)
            text_c(d, (540, 1060), "$12,000", 150, fill=(255, 206, 64, int(255 * k2)))
            text_c(d, (540, 1200), "的等值價值", 48, fill=(245, 245, 240, int(255 * k2)))
    elif sc == "api":
        text_c(d, (540, 560), "同樣的用量，兩種算法", 54)
        for i, (x, head, val, st, col) in enumerate([(290, "訂閱吃到飽", "$200", c["t0"], FG),
                                                      (790, "改買 API", "$12,000", S.cue_time(1719), ACCENT)]):
            k = max(ease((t - st) / 0.4), 0.0)
            a = int(255 * max(k, 0.25))
            d.rounded_rectangle((x - 230, 650, x + 230, 1000), 30, fill=(40, 50, 68, a))
            text_c(d, (x, 730), head, 48, fill=(245, 245, 240, a))
            if k > 0:
                text_c(d, (x, 870), val, 96, fill=col + (int(255 * k),))
        k = ease((t - S.cue_time(1726)) / 0.4)
        if k > 0:
            text_c(d, (540, 1130), "差 60 倍", 110, fill=(235, 72, 72, int(255 * k)))
        if t >= S.cue_time(1721):
            text_c(d, (540, 1260), "資料：SemiAnalysis", 32, fill=MUTED, bold=False)
    elif sc == "basis":
        text_c(d, (540, 580), "兩個數字，計價基礎不同", 54)
        rows = [("$12,000", "照 API 價（日料單點）", ACCENT, S.cue_time(1763)),
                ("$200", "照訂閱價（吃到飽）", FG, S.cue_time(1767))]
        for i, (v, lab, col, st) in enumerate(rows):
            k = ease((t - st) / 0.35)
            if k > 0:
                y = 760 + i * 230
                d.rounded_rectangle((100, y - 90, W - 100, y + 90), 28, fill=CARD2)
                d.text((150, y), v, font=font(80), fill=col, anchor="lm")
                d.text((W - 150, y), lab, font=font(40, False), fill=FG, anchor="rm")
        text_c(d, (540, 1230), "老闆不會真的去日料店買來擺給你夾", 36, fill=MUTED, bold=False)
    elif sc == "notreally":
        text_c(d, (540, 700), "AI 公司真的要花", 60)
        text_c(d, (540, 820), "$12,000 補貼你？", 80, fill=ACCENT)
        k = ease((t - S.cue_time(1800)) / 0.3)
        if k > 0:
            d.rounded_rectangle((260, 950, 820, 1110), 30, fill=(235, 72, 72, int(255 * k)))
            text_c(d, (540, 1030), "其實沒有", 90, fill=(255, 255, 255, int(255 * k)))
    elif sc == "gym":
        text_c(d, (540, 580), "AI 訂閱，其實像健身房", 58, fill=ACCENT)
        k = ease((t - S.cue_time(1812)) / 0.35)
        if k > 0:
            d.rounded_rectangle((100, 690, W - 100, 840), 28, fill=CARD2)
            text_c(d, (540, 765), "繳的會費，能用回本嗎？", 52, fill=(245, 245, 240, int(255 * k)))
        k = ease((t - S.cue_time(1817)) / 0.35)
        if k > 0:
            check(d, 190, 950)
            d.text((260, 950), "每次都去、用好用滿", font=font(48), fill=FG, anchor="lm")
        k = ease((t - S.cue_time(1819)) / 0.35)
        if k > 0:
            arrow(d, (540, 1010), (540, 1080), fill=MUTED)
            text_c(d, (540, 1160), "也只是省一點錢，賺不到錢", 46, fill=(150, 160, 175, int(255 * k)))
    elif sc == "ten":
        text_c(d, (540, 590), "訂閱的人，平均用掉多少額度？", 52)
        d.rounded_rectangle((110, 760, 970, 900), 24, outline=(90, 100, 120), width=5)
        text_c(d, (540, 950), "每月最大額度", 36, fill=MUTED, bold=False)
        k = ease((t - S.cue_time(1857)) / 0.6)
        if k > 0:
            d.rounded_rectangle((116, 766, 116 + 848 * 0.10 * k + 1, 894), 20, fill=ACCENT)
            text_c(d, (540, 1110), f"只用 {10 * k:.0f}%", 120, fill=(255, 206, 64, int(255 * k)))
    elif sc == "margin":
        text_c(d, (540, 590), "訂閱業務的毛利率（估算）", 52)
        k0 = 1 - ease((t - S.cue_time(1864)) / 0.3)
        if k0 > 0:
            text_c(d, (540, 740), "Token 給得再多", 56, fill=(150, 160, 175, int(255 * k0)))
            text_c(d, (540, 830), "平均也只用掉 10%", 56, fill=(255, 206, 64, int(255 * k0)))
        k = ease((t - S.cue_time(1864)) / 0.5)
        if k > 0:
            text_c(d, (540, 790), f"{int(50 * k)}–{int(60 * k)}%", 170, fill=(80, 200, 120, int(255 * k)))
        k = ease((t - S.cue_time(1868)) / 0.35)
        if k > 0:
            row_y = 1010
            d.rounded_rectangle((100, row_y - 60, W - 100, row_y + 60), 24, fill=CARD2)
            xmark(d, 170, row_y)
            d.text((235, row_y), "看起來在虧錢補貼", font=font(46), fill=MUTED, anchor="lm")
        k = ease((t - S.cue_time(1869)) / 0.35)
        if k > 0:
            row_y = 1150
            d.rounded_rectangle((100, row_y - 60, W - 100, row_y + 60), 24, fill=(30, 70, 50))
            check(d, 170, row_y)
            d.text((235, row_y), "其實還蠻有賺頭", font=font(46), fill=FG, anchor="lm")
        if t > S.clips[-1]["t1"]:
            text_c(d, (540, 1270), "完整內容：停損王 EP172", 32, fill=MUTED, bold=False)

S.render(visual)
