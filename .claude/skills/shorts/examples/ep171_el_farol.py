"""Short #5: 酒吧問題 — 大家都算對，結果全錯 — 停損王 EP171."""
import os, sys, json, math, random
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
from shortslib import *
from commons import credit

# run from the work dir:  SRT=<episode.srt> python <this file>   (audio at ./ep171.mp3, photos in ./img)
configure(os.environ.get("SRC", "ep171.mp3"), os.environ["SRT"], "停損王 EP171")

S = Short(
    "short5_el_farol", "酒吧問題：", "大家都算對，結果全錯",
    [
        (1223, 1224, "intro"),
        (1230, 1239, "crowd"),
        (1318, 1320, "rule60"),
        (1325, 1330, "rule60"),
        (1344, 1354, "data"),
        (1356, 1370, "dots"),
        (1371, 1376, "dots"),
        (1377, 1382, "dots"),
        (1582, 1590, "sim"),
        (1593, 1594, "sim"),
        (1595, 1598, "cas"),
        (1481, 1486, "moral"),
    ],
    highlights=["一百個人", "100個人", "60個人", "太擠", "比較聰明", "模擬市場行為", "出席人數", "回測", "想劇本",
                "立刻爆滿", "預測本身是對的", "回測也都對了", "策略也對", "預測就錯了", "一個人都沒有", "預測又錯了",
                "反向操作", "又錯了", "失效", "變準", "落在60", "固定的正確答案", "複雜適應系統", "影響答案",
                "所有人的模型", "共同在決定"],
)

# ---------- El Farol simulation (Arthur 1994 style) ----------
def el_farol(weeks=90, n=100, cap=60, k=6, seed=7):
    rnd = random.Random(seed)
    hist = [rnd.randint(30, 90) for _ in range(12)]
    def make():
        kind = rnd.choice(["same", "avg", "mirror", "trend", "cycle", "fixed"])
        p = rnd.randint(1, 8)
        f = rnd.randint(35, 85)
        def pred(h):
            if kind == "same": return h[-p]
            if kind == "avg": return sum(h[-p:]) / p
            if kind == "mirror": return 100 - h[-p]
            if kind == "trend": return min(100, max(0, h[-1] + (h[-1] - h[-1 - p]) / p))
            if kind == "cycle": return h[-min(p + 1, len(h))]
            return f
        return pred
    agents = [[make() for _ in range(k)] for _ in range(n)]
    scores = [[0.0] * k for _ in range(n)]
    for _ in range(weeks):
        go = 0
        preds = []
        for i in range(n):
            ps = [f(hist) for f in agents[i]]
            best = max(range(k), key=lambda j: scores[i][j])
            preds.append(ps)
            go += ps[best] < cap
        for i in range(n):
            for j in range(k):
                scores[i][j] = 0.8 * scores[i][j] - abs(preds[i][j] - go)
        hist.append(go)
    return hist[12:]

SIM = el_farol()

BAR = CROWD = EMPTY = None
def pick(tag, idx):
    p = f"img/{tag}_{idx}.jpg"
    try:
        m = json.load(open(f"img/{tag}.json"))[idx]
        return load_cover(p), credit(m)
    except Exception:
        return None
CROWD = pick("bar", int(os.environ.get("BAR_PICK", 1)))
EMPTY = None  # Commons search returned no suitable empty-bar photo; drawn card instead

# ---------- 100 people ----------
BAR_BOX = (90, 700, 500, 1150)
HOME_BOX = (580, 700, 990, 1150)
def slot(box, i):
    x0, y0, x1, y1 = box
    r, c = divmod(i, 10)
    return (x0 + 30 + c * (x1 - x0 - 60) / 9, y0 + 90 + r * (y1 - y0 - 120) / 9)

def events():
    ev = [(0, lambda i: 0.0)]
    ev.append((S.cue_time(1361), lambda i: 1.0))
    ev.append((S.cue_time(1374), lambda i: 0.0))
    ev.append((S.cue_time(1380), lambda i: 1.0 if i % 10 < 7 else 0.0))
    return ev

def in_bar(t, i):
    ev = events()
    prev, cur, t_ev = 0.0, 0.0, 0.0
    for te, f in ev:
        if t >= te:
            prev, cur, t_ev = cur, f(i), te
    return prev + (cur - prev) * ease((t - t_ev - (i % 17) * 0.025) / 0.7)

def dots_scene(d, t):
    for box, lab in ((BAR_BOX, "酒吧"), (HOME_BOX, "在家")):
        d.rounded_rectangle(box, 28, fill=CARD2)
        text_c(d, ((box[0] + box[2]) / 2, box[1] + 45), lab, 44)
    n_bar = 0
    for i in range(100):
        k = in_bar(t, i)
        n_bar += k > 0.5
        (x0, y0), (x1, y1) = slot(HOME_BOX, i), slot(BAR_BOX, i)
        x, y = x0 + (x1 - x0) * k, y0 + (y1 - y0) * k - math.sin(k * math.pi) * 60
        d.ellipse((x - 13, y - 13, x + 13, y + 13), fill=ACCENT if k > 0.5 else (170, 180, 195))
    col = RED if n_bar > 60 else (GREEN if n_bar > 0 else MUTED)
    d.text((BAR_BOX[0] + 20, BAR_BOX[3] + 55), f"{n_bar} 人", font=font(56), fill=col, anchor="lm")
    d.text((BAR_BOX[2], BAR_BOX[3] + 55), "上限舒適 60", font=font(30, False), fill=MUTED, anchor="rm")
    return n_bar

def stamp(d, text, k, y=620, col=RED):
    if k <= 0:
        return
    w = d.textlength(text, font=font(60)) + 60
    d.rounded_rectangle((540 - w / 2, y - 50, 540 + w / 2, y + 50), 20, fill=col + (int(235 * k),))
    text_c(d, (540, y), text, 60, fill=(255, 255, 255, int(255 * k)))

def line_chart(d, data, t_prog, box, y_max=100, cap=60, label=None):
    x0, y0, x1, y1 = box
    d.line((x0, y0, x0, y1, x1, y1), fill=(80, 90, 110), width=3)
    yc = y1 - (y1 - y0) * cap / y_max
    for xx in range(int(x0), int(x1), 24):
        d.line((xx, yc, xx + 12, yc), fill=RED, width=4)
    d.text((x0 - 12, yc), "60", font=font(30), fill=RED, anchor="rm")
    n = max(2, int(len(data) * t_prog))
    pts = [(x0 + (x1 - x0) * i / (len(data) - 1), y1 - (y1 - y0) * data[i] / y_max) for i in range(n)]
    d.line(pts, fill=ACCENT, width=6, joint="curve")
    if label:
        d.text((x0, y1 + 36), label, font=font(30, False), fill=MUTED, anchor="lm")

def visual(S, fr, t):
    c = S.clip_at(t)
    sc, lt = c["scene"], t - c["t0"]
    if sc == "intro":
        if CROWD:
            d = photo(fr, CROWD[0], CROWD[1], lt / 6, zoom=(1.0, 1.1))
        else:
            d = card(fr)
        chip(d, (60, PANEL[1] + 30), "思想實驗：艾法羅酒吧問題", fill=(0, 0, 0, 190))
        d.rounded_rectangle((290, 1060, 790, 1220), 30, fill=(14, 20, 30, 225))
        text_c(d, (540, 1140), "今晚去不去？", 64, fill=ACCENT)
    elif sc == "crowd":
        empty_t = S.cue_time(1237)
        if t < empty_t:
            d = photo(fr, CROWD[0], CROWD[1], 0.4 + (t - c["t0"]) / 30, zoom=(1.05, 1.2)) if CROWD else card(fr)
            chip(d, (60, PANEL[1] + 30), "人很多：花一樣的錢，體驗很差", fill=(160, 40, 40, 220))
        else:
            if EMPTY:
                d = photo(fr, EMPTY[0], EMPTY[1], (t - empty_t) / 5, zoom=(1.0, 1.1))
            else:
                d = card(fr)
                d.rounded_rectangle((140, 620, 940, 1240), 30, fill=CARD2)
                text_c(d, (540, 690), "酒吧", 48)
                for j, (x, y) in enumerate([(300, 900), (520, 1000), (760, 860), (420, 1120), (820, 1100)]):
                    k = ease((t - empty_t - j * 0.12) / 0.3)
                    d.ellipse((x - 26 * k, y - 26 * k, x + 26 * k, y + 26 * k), fill=ACCENT)
            chip(d, (60, PANEL[1] + 30), "人很少：賓至如歸", fill=(30, 120, 70, 220))
    elif sc == "rule60":
        d = card(fr)
        text_c(d, (540, 560), "遊戲規則", 56)
        # attendance gauge
        gx0, gx1, gy = 120, 960, 700
        d.rounded_rectangle((gx0, gy - 26, gx1, gy + 26), 26, fill=CARD2)
        d.rounded_rectangle((gx0, gy - 26, gx0 + (gx1 - gx0) * 0.6, gy + 26), 26, fill=(50, 120, 80))
        d.rounded_rectangle((gx0 + (gx1 - gx0) * 0.6, gy - 26, gx1, gy + 26), 26, fill=(130, 50, 55))
        for v in (0, 60, 100):
            d.text((gx0 + (gx1 - gx0) * v / 100, gy + 60), f"{v}", font=font(34), fill=FG, anchor="mm")
        d.text((gx0 + (gx1 - gx0) * 0.6, gy - 62), "60 人", font=font(36), fill=ACCENT, anchor="mm")
        k1 = ease((t - S.cue_time(1319)) / 0.35)
        if k1 > 0:
            d.rounded_rectangle((120, 820, 960, 960), 26, fill=(40, 70, 55, int(255 * k1)))
            check(d, 190, 890)
            d.text((250, 890), "不到 60 人：去的人贏", font=font(48), fill=(245, 245, 240, int(255 * k1)), anchor="lm")
        k2 = ease((t - S.cue_time(1326)) / 0.35)
        if k2 > 0:
            d.rounded_rectangle((120, 990, 960, 1130), 26, fill=(75, 40, 45, int(255 * k2)))
            check(d, 190, 1060, fill=(80, 150, 230))
            d.text((250, 1060), "超過 60 人：在家的人贏", font=font(48), fill=(245, 245, 240, int(255 * k2)), anchor="lm")
        k3 = ease((t - S.cue_time(1330)) / 0.35)
        if k3 > 0:
            text_c(d, (540, 1225), "把酒吧換成股市，就是市場", 44, fill=(255, 206, 64, int(255 * k3)))
    elif sc == "data":
        d = card(fr)
        text_c(d, (540, 560), "每個人都看得到：過去每週出席人數", 46)
        line_chart(d, SIM[:30], 1.0, (130, 650, 950, 1060), label="第 1 週 → 第 30 週")
        for j, (lab, n) in enumerate([("逼明牌", 1350), ("回測", 1351), ("想劇本", 1352), ("預測今晚", 1353)]):
            k = ease((t - S.cue_time(n)) / 0.3)
            if k > 0:
                x = 110 + j * 218
                d.rounded_rectangle((x, 1150, x + 200, 1240), 22, fill=(255, 206, 64, int(255 * k)))
                text_c(d, (x + 100, 1195), lab, 40, fill=BG)
    elif sc == "dots":
        d = card(fr)
        n_bar = dots_scene(d, t)
        if t < S.cue_time(1371):
            k = ease((t - S.cue_time(1359)) / 0.3)
            if k > 0 and t < S.cue_time(1362):
                stamp(d, "大家都預測：今晚人很少 → 去！", k, col=(60, 90, 140))
            stamp(d, "立刻爆滿", ease((t - S.cue_time(1362)) / 0.3) if t < S.cue_time(1363) else 0)
            if S.cue_time(1363) <= t:
                items = [("預測", 1363), ("回測", 1364), ("策略", 1365)]
                x = 170
                for lab, n in items:
                    k = ease((t - S.cue_time(n)) / 0.25)
                    if k > 0:
                        check(d, x, 600, 30)
                        d.text((x + 45, 600), lab + "都對", font=font(38), fill=FG, anchor="lm")
                    x += 250
            if t >= S.cue_time(1370):
                stamp(d, "結果：預測錯了", ease((t - S.cue_time(1370)) / 0.3), y=1260)
        elif t < S.cue_time(1377):
            k = ease((t - S.cue_time(1371)) / 0.3)
            if t < S.cue_time(1375):
                stamp(d, "大家都預測：今晚會很擠 → 不去", k, col=(60, 90, 140))
            else:
                stamp(d, "一個人都沒有：預測又錯了", ease((t - S.cue_time(1375)) / 0.3))
        else:
            if t < S.cue_time(1381):
                stamp(d, "那我反向操作？", ease((t - S.cue_time(1377)) / 0.3), col=(60, 90, 140))
            else:
                stamp(d, "反向的人太多 → 一起錯", ease((t - S.cue_time(1381)) / 0.3))
    elif sc == "sim":
        d = card(fr)
        text_c(d, (540, 560), "模擬 90 週：100 人各用自己的預測指標", 42)
        a, b = S.span("sim")
        line_chart(d, SIM, ease((t - a) / (b - a - 2)), (130, 640, 950, 1060), label="每週出席人數（依本集的規則模擬）")
        avg = sum(SIM) / len(SIM)
        k = ease((t - S.cue_time(1590)) / 0.4)
        if k > 0:
            d.rounded_rectangle((250, 1150, 830, 1250), 24, fill=(255, 206, 64, int(255 * k)))
            text_c(d, (540, 1200), f"長期平均 ≈ {avg:.0f} 人", 50, fill=BG)
    elif sc == "cas":
        d = card(fr)
        text_c(d, (540, 600), "為什麼沒有標準答案？", 58)
        k = ease((t - S.cue_time(1596)) / 0.35)
        if k > 0:
            text_c(d, (540, 740), "複雜適應系統", 84, fill=(255, 206, 64, int(255 * k)))
        for j, (lab, n) in enumerate([("每個人一直在猜", 1597), ("猜的結果又改變答案", 1598)]):
            k = ease((t - S.cue_time(n)) / 0.3)
            if k > 0:
                y = 920 + j * 160
                d.rounded_rectangle((170, y - 60, 910, y + 60), 26, fill=CARD2)
                text_c(d, (540, y), lab, 50, fill=(245, 245, 240, int(255 * k)))
    elif sc == "moral":
        d = card(fr)
        k = ease((t - S.cue_time(1481)) / 0.4)
        text_c(d, (540, 640), "我們以為：", 44, fill=(150, 160, 175, int(255 * k)), bold=False)
        text_c(d, (540, 730), "我用模型預測結果", 64, fill=(245, 245, 240, int(255 * k)))
        k = ease((t - S.cue_time(1484)) / 0.4)
        if k > 0:
            text_c(d, (540, 900), "實際上：", 44, fill=(150, 160, 175, int(255 * k)), bold=False)
            text_c(d, (540, 995), "所有人的模型", 72, fill=(255, 206, 64, int(255 * k)))
            text_c(d, (540, 1095), "共同決定了結果", 72, fill=(255, 206, 64, int(255 * k)))
        if t > S.clips[-1]["t1"]:
            text_c(d, (540, 1250), "完整內容：停損王 EP171", 32, fill=MUTED, bold=False)

if __name__ == "__main__":
    print("SIM mean", sum(SIM) / len(SIM), "min", min(SIM), "max", max(SIM))
    S.render(visual)
