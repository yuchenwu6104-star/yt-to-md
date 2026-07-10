#!/usr/bin/env python3
"""交付前機械清掃閘門（humanizer-zh 處理流程第 12 步 c）。

用法：python3 final_gate.py <文章路徑>

把 SKILL.md 裡散落各處的 grep 樣式收斂成一支腳本，人只負責判斷，不手動 grep。
輸出分兩類：

  [硬性] 必須清零——修完重跑，直到無任何 [硬性] 輸出才可交付／上傳。
  [候選] 寬召回是設計、禁止見詞就改——逐筆三分類（講者原話／有依據／該改），
         去留由判斷決定，處置結果記進交付清單。

exit code：有 [硬性]＝1；只有 [候選] 或全乾淨＝0。
只用標準庫，任何 Python 3 直譯器可跑。
"""
from __future__ import annotations

import re
import sys

# ---- 黑名單（與 /yt yt_to_article.py 的 format_violations 同源，改一邊記得改另一邊）----

STAGE_PHRASES = (
    "補了一句", "補了一個", "補一句", "補一刀", "補了一刀",
    "補了最後一刀", "補了一個畫面", "補了一個細節",
    "補上", "補了一段", "補述", "再補一句", "再補一個",
    "笑著接", "順著接", "馬上搭腔", "馬上吐槽", "再補一刀",
    "把方向拉回", "把梗接到", "話鋒一轉", "切入核心",
    "苦笑著說", "笑著說", "笑說", "打趣", "搶話",
)
TONE_WORDS = (
    "尖銳", "犀利", "一針見血", "毫不留情", "不留情面", "不客氣",
    "火力全開", "很簡潔", "很乾脆", "語帶保留", "語重心長", "意味深長",
    "暗示了", "透露了",
)
NONNEUTRAL_VERBS = ("坦言", "坦承", "直言", "不諱言", "爆料")
EDITORIAL_RE = re.compile(r"(?:很|相當|非常|十分|更)(?:直接|直白)")
DASH_RE = re.compile(r"[—–]")
REFRAME_RE = re.compile(r"而是|並非|而在於|與其說|表面上|更深層|你以為|看似|真正的")
# 連續 4 個以上英文詞（非專名殘留候選；單一術語/人名不報）
ENGLISH_RUN_RE = re.compile(r"[A-Za-z][A-Za-z'’\-]*(?:\s+[A-Za-z][A-Za-z'’\-]*){3,}")

KANA_RE = re.compile(r"[぀-ゟ゠-ヿ]")
HANGUL_RE = re.compile(r"[가-힣]")


def _strip_quotes(s: str) -> str:
    """剔除「」內講者原話（引述區豁免串接區黑名單）。"""
    return re.sub(r"「[^「」]*」", "", s)


def _bigrams(s: str) -> set:
    s = re.sub(r"[^一-鿿]", "", s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _nums(s: str) -> set:
    return set(re.findall(r"[0-9][0-9,.]*\s*(?:兆|億|倍|%|萬)", s))


def _is_quote_para(p: str) -> bool:
    qs = re.findall(r"「([^「」]{15,})」", p)
    return bool(qs) and sum(len(x) for x in qs) > len(p) * 0.5


def restatement_candidates(paras: list) -> list:
    """逐句版串接複述偵測（模式 33）。

    與 /yt 的 _redundant_narration 同邏輯：串接段按句切開，任一句的 CJK 2-gram
    過半被緊接引述涵蓋、或與引述共用 ≥2 個帶單位數字，即為複述候選。逐句而非
    整段，是為了抓混血串接（一句複述焊在有合法背景的段落裡，整段比對會被稀釋）。
    """
    hits = []
    for i in range(1, len(paras)):
        cur, prev = paras[i], paras[i - 1]
        if cur.startswith("#") or prev.startswith("#"):
            continue
        if not _is_quote_para(cur) or _is_quote_para(prev):
            continue
        quote = " ".join(re.findall(r"「([^「」]+)」", cur))
        qgrams, qnums = _bigrams(quote), _nums(quote)
        for sent in re.split(r"[。！？；]", _strip_quotes(prev)):
            sg = _bigrams(sent)
            if len(sg) < 6:
                continue
            contain = len(sg & qgrams) / len(sg)
            if contain >= 0.5 or len(_nums(sent) & qnums) >= 2:
                hits.append(sent.strip()[:60])
    return hits


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    text = open(sys.argv[1], encoding="utf-8").read()

    # 豁免區：YAML frontmatter 與「原始影片」參照行（本就保留原文標題）
    body = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.DOTALL)
    lines = [(n, l) for n, l in enumerate(body.splitlines(), 1) if "原始影片" not in l]

    hard, soft = [], []

    for n, line in lines:
        if DASH_RE.search(line):
            hard.append(f"破折號｜L{n}｜{line.strip()[:60]}")
        stripped = _strip_quotes(line)
        for kind, words in (("舞台指示／報幕詞", STAGE_PHRASES),
                            ("語氣打分", TONE_WORDS),
                            ("白名單外引述動詞", NONNEUTRAL_VERBS)):
            w = next((w for w in words if w in stripped), None)
            if w:
                hard.append(f"{kind}｜L{n}｜「{w}」：{stripped.strip()[:50]}")
        m = EDITORIAL_RE.search(stripped)
        if m:
            hard.append(f"語氣打分｜L{n}｜「{m.group(0)}」：{stripped.strip()[:50]}")
        m = REFRAME_RE.search(stripped)
        if m:
            soft.append(f"重新框定句型（模式9/35，三分類）｜L{n}｜「{m.group(0)}」：{stripped.strip()[:50]}")
        m = ENGLISH_RUN_RE.search(line)
        if m:
            soft.append(f"連續英文串（漏翻候選，模式29）｜L{n}｜{m.group(0)[:60]}")

    scan = "\n".join(l for _, l in lines)
    kana, hangul = len(KANA_RE.findall(scan)), len(HANGUL_RE.findall(scan))
    if hangul >= 5 or kana >= 12:
        hard.append(f"未翻譯外語｜全文｜假名 {kana} 字、諺文 {hangul} 字（繁中文章應趨近 0）")

    paras = [p.strip() for p in body.split("\n\n") if p.strip()]
    from collections import Counter
    dupes = [p[:50] for p, c in Counter(p for p in paras if len(p) >= 80).items() if c > 1]
    for d in dupes:
        hard.append(f"整段重複｜｜{d}…")
    for r in restatement_candidates(paras):
        soft.append(f"串接複述候選（模式33，逐對遮字測試）｜｜{r}…")

    for item in hard:
        print(f"[硬性] {item}")
    for item in soft:
        print(f"[候選] {item}")
    print(f"\n== 共 [硬性] {len(hard)} 筆（須清零重跑）、[候選] {len(soft)} 筆（逐筆三分類）==")
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
