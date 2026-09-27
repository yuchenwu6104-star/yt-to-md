"""Short #1: 賣股抽漢測，你已經先少賺 7.5 萬 — 停損王 EP171."""
import os, sys, json, math, random
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
from shortslib import *
from commons import credit

# run from the work dir:  SRT=<episode.srt> python <this file>   (audio at ./ep171.mp3, photos in ./img)
configure(os.environ.get("SRC", "ep171.mp3"), os.environ["SRT"], "停損王 EP171")

S = Short(
    "short1_ipo_lottery", "賣股去抽漢測", "你已經先少賺 7.5 萬",
    [
        (2180, 2186, "hook"),
        (2189, 2192, "idle"),
        (2194, 2201, "lock"),
        (2202, 2209, "calc"),
        (2210, 2214, "moment"),
        (2229, 2232, "costs"),
        (2237, 2241, "ev"),
        (2259, 2267, "who"),
        (2270, 2272, "who"),
        (2295, 2302, "unfair"),
        (2308, 2317, "loop"),
    ],
    highlights=["不是零成本", "零成本", "閒錢", "250萬", "三天", "3%", "75000", "7萬5", "20塊", "0.29%", "2.5%",
                "300萬", "不公平的比賽", "正回饋", "機會成本"],
)

# Optional hook photo: `python commons.py tse "<query>"` then TSE_PICK=<i>. EP171 found none, so the hook is a card.
TSE = None
if "TSE_PICK" in os.environ:
    PICK = int(os.environ["TSE_PICK"])
    TSE = (load_cover(f"img/tse_{PICK}.jpg"), credit(json.load(open("img/tse.json"))[PICK]))

def row(d, y, left, right=None, k=1.0, mark=None, rcol=ACCENT, size=50):
    x = 100 + (1 - k) * 60
    d.rounded_rectangle((x, y - 62, W - 100, y + 62), 24, fill=CARD2)
    tx = x + 40
    if mark == "x":
        xmark(d, x + 68, y); tx = x + 130
    elif mark == "v":
        check(d, x + 68, y); tx = x + 130
    d.text((tx, y), left, font=font(size), fill=FG, anchor="lm")
    if right:
        d.text((W - 140, y), right, font=font(size), fill=rcol, anchor="rm")

def visual(S, fr, t):
    c = S.clip_at(t)
    sc, lt = c["scene"], t - c["t0"]
    if sc == "hook":
        if TSE:
            a, b = S.span("hook")
            d = photo(fr, TSE[0], TSE[1], (t - a) / (b - a), zoom=(1.0, 1.12))
            d.rectangle(PANEL, fill=(0, 0, 0, 90))
        else:
            d = card(fr)
        k = ease((t - 0.3) / 0.4)  # hook text from the first second — a blank opening loses viewers
        if k > 0:
            d.rounded_rectangle((120, 700, 960, 1080), 36, fill=(14, 20, 30, int(225 * k)))
            text_c(d, (540, 810), "賣股去抽籤", 72, fill=(255, 255, 255, int(255 * k)))
            text_c(d, (540, 950), "真的是零成本？", 72, fill=(255, 206, 64, int(255 * k)))
    elif sc == "idle":
        d = card(fr)
        text_c(d, (540, 580), "什麼情況才算「幾乎零成本」？", 50)
        row(d, 760, "用閒錢抽籤", "幾乎零成本", ease(lt / 0.3), "v", GREEN)
        k = ease((lt - 3.5) / 0.3)
        if k > 0:
            row(d, 950, "賣股票去抽籤", "？", k, "x", RED)
        text_c(d, (540, 1180), "閒錢：本來就要放在那裡的現金", 36, fill=MUTED, bold=False)
    elif sc == "lock":
        d = card(fr)
        text_c(d, (540, 590), "假設抽籤要準備", 44, fill=MUTED, bold=False)
        text_c(d, (540, 690), "250 萬", 110, fill=ACCENT)
        k = ease((t - S.cue_time(2196)) / 0.3)
        if k > 0:
            text_c(d, (540, 830), "資金最少綁住 3 天", 50)
            for i in range(3):
                kk = ease((t - S.cue_time(2196) - 0.4 * i) / 0.3)
                x0 = 300 + i * 170
                d.rounded_rectangle((x0, 890, x0 + 140, 1000), 18, fill=CARD2, outline=ACCENT if kk > 0.5 else CARD2, width=5)
                text_c(d, (x0 + 70, 945), f"Day {i + 1}", 34, fill=ACCENT if kk > 0.5 else MUTED)
        k = ease((t - S.cue_time(2199)) / 0.5)
        if k > 0:
            pts = [(260 + 560 * i / 20, 1200 - 110 * (i / 20) ** 1.2 - 12 * math.sin(i * 1.3)) for i in range(int(20 * k) + 1)]
            if len(pts) > 1:
                d.line(pts, fill=GREEN, width=8)
            d.text((830, 1110), "大盤 +3%", font=font(48), fill=GREEN, anchor="lm") if k > 0.9 else None
            d.text((260, 1240), "這 3 天", font=font(32, False), fill=MUTED, anchor="lm")
    elif sc == "calc":
        d = card(fr)
        text_c(d, (540, 600), "錢被綁住，又沒抽到", 54)
        text_c(d, (540, 670), "（而且沒抽到是機率最高的結果）", 36, fill=MUTED, bold=False)
        k1 = ease((t - S.cue_time(2206)) / 0.3)
        k2 = ease((t - S.cue_time(2208)) / 0.3)
        k3 = ease((t - S.cue_time(2209)) / 0.3)
        if k1 > 0:
            text_c(d, (540, 820), "250 萬  ×  3%", 88, fill=(245, 245, 240, int(255 * k1)))
        if k2 > 0:
            text_c(d, (540, 940), "=", 80, fill=(150, 160, 175, int(255 * k2)))
        if k3 > 0:
            text_c(d, (540, 1080), f"少賺 {7.5 * k3:.1f} 萬", 110, fill=(235, 72, 72, int(255 * k3)))
    elif sc == "moment":
        d = card(fr)
        text_c(d, (540, 580), "你以為抽到就沒少賺？", 54)
        k = ease((t - S.cue_time(2212)) / 0.4)
        if k > 0:
            d.rounded_rectangle((330, 660, 750, 770), 26, fill=ACCENT)
            text_c(d, (540, 715), "賣股的那一刻", 50, fill=BG)
            arrow(d, (470, 780), (300, 900), fill=MUTED)
            arrow(d, (610, 780), (780, 900), fill=MUTED)
            for i, (lab, x) in enumerate([("抽到了", 270), ("沒抽到", 810)]):
                d.rounded_rectangle((x - 200, 910, x + 200, 1130), 26, fill=CARD2)
                text_c(d, (x, 970), lab, 50)
                kk = ease((t - S.cue_time(2214)) / 0.3)
                if kk > 0:
                    text_c(d, (x, 1065), "−3% 漲幅", 56, fill=(235, 72, 72, int(255 * kk)))
        k = ease((t - S.cue_time(2214)) / 0.3)
        if k > 0:
            text_c(d, (540, 1210), "錯過的 3% 在賣出時就確定了", 42, fill=(255, 206, 64, int(255 * k)))
    elif sc == "costs":
        d = card(fr)
        text_c(d, (540, 580), "賣股抽籤的成本", 56)
        row(d, 740, "沒抽到的失落感", None, ease(lt / 0.3), "x")
        k = ease((t - S.cue_time(2230)) / 0.3)
        if k > 0:
            row(d, 900, "抽籤手續費", "20 元", k, "x", MUTED)
        k = ease((t - S.cue_time(2231)) / 0.4)
        if k > 0:
            d.rounded_rectangle((100, 1000, W - 100, 1260), 28, fill=(60, 30, 36))
            text_c(d, (540, 1060), "這次的中籤率", 42, fill=MUTED, bold=False)
            text_c(d, (540, 1170), f"{0.29 * k:.2f}%", 120, fill=RED)
    elif sc == "ev":
        d = card(fr)
        text_c(d, (540, 590), "賣股抽籤要划算，中籤率要多少？", 50)
        text_c(d, (540, 660), "7.5 萬 ÷ 300 萬 = 2.5%", 40, fill=MUTED, bold=False)
        maxw = 640
        bars = [("打平所需", 2.5, ACCENT, S.cue_time(2240)), ("這次實際", 0.29, RED, S.cue_time(2240) + 1.0)]
        for i, (lab, v, col, st) in enumerate(bars):
            k = ease((t - st) / 0.6)
            y = 830 + i * 200
            d.text((110, y - 50), lab, font=font(42), fill=FG, anchor="lm")
            if k > 0:
                wv = max(maxw * v / 2.5 * k, 20)
                d.rounded_rectangle((110, y, 110 + wv, y + 90), 18, fill=col)
                d.text((110 + wv + 24, y + 45), f"{v * k:.2f}%", font=font(56), fill=col, anchor="lm")
        text_c(d, (540, 1250), "而且下單當下，你還不知道中籤率", 38, fill=MUTED, bold=False)
    elif sc == "who":
        d = card(fr)
        text_c(d, (540, 580), "你是哪一種人？", 58)
        for i, (x, head, col) in enumerate([(290, "有閒錢", GREEN), (790, "要賣股才能抽", RED)]):
            st = S.cue_time(2262) if i == 0 else S.cue_time(2266)
            k = ease((t - st) / 0.35) if i == 1 else max(ease((t - st) / 0.35), 0.35)
            a = int(255 * k)
            d.rounded_rectangle((x - 230, 680, x + 230, 1250), 30, fill=(40, 50, 68, a), outline=col + (a,), width=6)
            text_c(d, (x, 760), head, 52, fill=col + (a,))
            if i == 0:
                check(d, x, 900, 50)
                text_c(d, (x, 1020), "不用算", 50, fill=(245, 245, 240, a))
                text_c(d, (x, 1100), "抽就對了", 50, fill=(245, 245, 240, a))
            else:
                text_c(d, (x, 880), "不管有沒有抽到", 40, fill=(245, 245, 240, a), bold=False)
                kk = ease((t - S.cue_time(2271)) / 0.3)
                if kk > 0:
                    text_c(d, (x, 1000), "都少賺", 52, fill=(245, 245, 240, int(255 * kk)))
                    text_c(d, (x, 1110), "7.5 萬", 84, fill=(235, 72, 72, int(255 * kk)))
    elif sc == "unfair":
        d = card(fr)
        text_c(d, (540, 590), "一場不公平的比賽", 60)
        k = ease((t - S.cue_time(2299)) / 0.35)
        if k > 0:
            row(d, 790, "拿閒錢抽，沒抽中", "−20 元", k, None, MUTED, 46)
        k = ease((t - S.cue_time(2302)) / 0.35)
        if k > 0:
            d.rounded_rectangle((100, 920, W - 100, 1180), 24, fill=(60, 30, 36))
            d.text((140, 990), "賣股去抽，沒抽中", font=font(46), fill=FG, anchor="lm")
            d.text((W - 140, 990), "−20 元", font=font(46), fill=MUTED, anchor="rm")
            d.text((W - 140, 1100), "−7.5 萬", font=font(76), fill=RED, anchor="rm")
            d.text((140, 1100), "還要加上", font=font(40, False), fill=MUTED, anchor="lm")
    elif sc == "loop":
        d = card(fr)
        text_c(d, (540, 545), "正回饋", 60, fill=ACCENT if t >= S.cue_time(2310) else MUTED)
        nodes = [("親友互揪：為什麼不抽？", 2311), ("抽到就有 300 萬！", 2314), ("更多人賣股去抽", 2316)]
        ys = [680, 850, 1020]
        for i, (lab, n) in enumerate(nodes):
            lit = t >= S.cue_time(n)
            d.rounded_rectangle((170, ys[i] - 55, 830, ys[i] + 55), 26, fill=ACCENT if lit else CARD2)
            text_c(d, (500, ys[i]), lab, 44, fill=BG if lit else MUTED)
            if i < 2:
                arrow(d, (500, ys[i] + 60), (500, ys[i + 1] - 62), fill=ACCENT if t >= S.cue_time(nodes[i + 1][1]) else (70, 80, 100), width=7)
        loop_on = t >= S.cue_time(2316)
        col = ACCENT if loop_on else (70, 80, 100)
        d.line(((835, ys[2]), (930, ys[2]), (930, ys[0])), fill=col, width=7)
        arrow(d, (930, ys[0]), (838, ys[0]), fill=col, width=7)
        k = ease((t - S.cue_time(2317)) / 0.4)
        if k > 0:
            arrow(d, (500, ys[2] + 60), (500, 1130), fill=RED, width=7)
            d.rounded_rectangle((170, 1140, 830, 1250), 26, fill=(235, 72, 72, int(255 * k)))
            text_c(d, (500, 1195), "中籤率被壓到 0.29%", 46, fill=(255, 255, 255, int(255 * k)))
        if t > S.clips[-1]["t1"]:
            text_c(d, (540, 1285), "完整內容：停損王 EP171", 30, fill=MUTED, bold=False)

S.render(visual)
