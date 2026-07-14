#!/usr/bin/env python3
"""交付前機械清掃閘門（humanizer-zh 處理流程第 13 步 c）。

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
    "開門見山", "先解釋為什麼", "點出另外",
    "另一個更即時的問題", "她的重點是", "他的重點是",
)
TONE_WORDS = (
    "尖銳", "犀利", "一針見血", "毫不留情", "不留情面", "不客氣",
    "火力全開", "很簡潔", "很乾脆", "語帶保留", "語重心長", "意味深長",
    "暗示了", "透露了",
)
NONNEUTRAL_VERBS = ("坦言", "坦承", "直言", "不諱言", "爆料")
# /yt 分段後台資訊滲入成稿（chunk meta 洩漏）；引號內講者原話豁免
META_LEAK_RE = re.compile(
    r"逐字稿的(?:第[一1壹\d]|最後一|中間)段|後續段落|具體內容要等|這是完整逐字稿"
)
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


def representative_quote_coverage(article: str) -> tuple[int, int]:
    """Count sections with one long quote or a substantive short exchange."""
    sections = re.split(r"(?m)^##\s+", article)[1:]
    main_sections = []
    for section in sections:
        heading = section.splitlines()[0].strip() if section.splitlines() else ""
        if heading in {"導言", "結語"}:
            continue
        main_sections.append(section)
    covered = 0
    for section in main_sections:
        quotes = re.findall(r"「([^「」]+)」", section)
        quote_lengths = [len(re.findall(r"[一-鿿]", quote)) for quote in quotes]
        dialogue_lengths = [length for length in quote_lengths if length >= 6]
        if any(length >= 30 for length in quote_lengths) or (
            len(dialogue_lengths) >= 2 and sum(dialogue_lengths) >= 30
        ):
            covered += 1
    return covered, len(main_sections)


def restatement_candidates(paras: list) -> list:
    """逐句版引述前預告與引述後解說偵測（模式 33）。

    與 /yt 的 _redundant_narration 同邏輯：逐句比較引述前後相鄰敘述，任一句的
    CJK 2-gram 過半被引述涵蓋、或與引述共用至少兩個帶單位數字，即為複述候選。
    """
    hits = []
    for i, cur in enumerate(paras):
        if cur.startswith("#") or not _is_quote_para(cur):
            continue
        quote = " ".join(re.findall(r"「([^「」]+)」", cur))
        qgrams, qnums = _bigrams(quote), _nums(quote)
        neighbors = []
        if i > 0 and not paras[i - 1].startswith("#") and not _is_quote_para(paras[i - 1]):
            neighbors.append(("引述前", paras[i - 1]))
        if i + 1 < len(paras) and not paras[i + 1].startswith("#") and not _is_quote_para(paras[i + 1]):
            neighbors.append(("引述後", paras[i + 1]))
        for position, paragraph in neighbors:
            for sent in re.split(r"[。！？；]", _strip_quotes(paragraph)):
                sg = _bigrams(sent)
                if len(sg) < 6:
                    continue
                contain = len(sg & qgrams) / len(sg)
                if contain >= 0.5 or len(_nums(sent) & qnums) >= 2:
                    hits.append(f"{position}：{sent.strip()[:55]}")
    return list(dict.fromkeys(hits))


_ENTITY_STOPWORDS = frozenset({
    "the", "and", "for", "with", "that", "this", "from", "into", "your",
    "ai", "agi", "ml", "llm", "llms", "gpu", "gpus", "cpu", "tpu", "api", "apis",
    "ceo", "cfo", "cto", "coo", "gdp", "ipo", "etf", "roi", "kpi", "okr",
    "saas", "b2b", "b2c", "iot", "faq", "crm", "erp", "seo", "vc", "pe",
    "usa", "us", "uk", "eu", "un", "ok", "ux", "ui", "ev", "evs", "vr", "ar",
    "q1", "q2", "q3", "q4", "r&d", "ceos", "cios", "kyc", "wto", "wef",
    "youtube", "podcast", "podcasts", "inferencing", "token", "tokens",
    "margin", "floor", "double", "down", "reasoning", "scale", "out", "across",
    "wide", "slow", "narrow", "fast", "lead", "time",
})


def _find_transcript(article_path: str) -> "str | None":
    """自動尋找同名 `_transcript.txt`（與 SKILL.md 處理流程第 2 步同規則）。
    `xxx_humanized.md` 與 `xxx.md` 都對應 `xxx_transcript.txt`。"""
    import os
    base = re.sub(r"\.md$", "", article_path)
    base = re.sub(r"_humanized$", "", base)
    p = base + "_transcript.txt"
    if os.path.exists(p):
        return open(p, encoding="utf-8").read()
    return None


def transcript_checks(article: str, transcript: str) -> "tuple[list, list]":
    """拿字幕當 ground truth 的機械檢查。回傳 (hard, soft)。

    1. 覆蓋率粗檢（[候選]）：成文 CJK 字數對逐字稿比例過低＝疑似漏段，
       覆蓋對帳（處理流程第 3 步）必須逐主題補查。
    2. 英文專名交叉核對（[候選]）：文章裡的英文專名在字幕完全對不上（含模糊
       比對），可能是捏造、也可能是把聽錯的字修成錯的專名（IMREC→IMEC 案）。
       與 /yt yt_to_article.py 的 _fabricated_english_entities 同源簡化版。
    """
    import difflib
    hard, soft = [], []

    art_cjk = len(re.findall(r"[一-鿿]", article))
    src_cjk = len(re.findall(r"[一-鿿]", transcript))
    if src_cjk > len(transcript) * 0.3:
        ratio, floor = art_cjk / max(src_cjk, 1), 0.35
    else:
        ratio, floor = art_cjk / max(len(transcript), 1), 0.08
    if ratio < floor:
        soft.append(
            f"覆蓋率偏低（第 3 步覆蓋對帳加嚴）｜全文｜成文 {art_cjk} CJK 字 vs "
            f"逐字稿 {len(transcript)} 字元，比例 {ratio:.2f} < 門檻 {floor}，疑似漏段"
        )

    tl = transcript.lower()
    twords = set(re.findall(r"[a-z0-9]+", tl))
    tl_squashed = re.sub(r"[^a-z0-9]", "", tl)
    # frontmatter 的 channel／video_title 是已知 metadata，其 token 一律豁免
    exempt = set()
    fm = re.match(r"\A---\n(.*?)\n---\n", article, flags=re.DOTALL)
    if fm:
        for m in re.finditer(r'(?m)^(?:channel|video_title):\s*"?(.+?)"?\s*$', fm.group(1)):
            exempt.update(re.findall(r"[a-z0-9]+", m.group(1).lower()))
    body = re.sub(r"\A---\n.*?\n---\n", "", article, count=1, flags=re.DOTALL)
    body = re.sub(r"https?://\S+", "", body)
    scan = "\n".join(l for l in body.splitlines() if "原始影片" not in l)
    seen = set()
    for tok in re.findall(r"[A-Z][A-Za-z0-9]*(?:[-'.&][A-Za-z0-9]+)*", scan):
        norm = tok.lower()
        bare = re.sub(r"[-'.&]", "", norm)
        if norm in seen or len(bare) < 4 or norm in _ENTITY_STOPWORDS:
            continue
        seen.add(norm)
        if norm in exempt or bare in exempt:
            continue
        if norm in tl or bare in tl_squashed:
            continue
        parts = [p for p in re.split(r"[-'.&]", norm) if p]
        if parts and all(p in tl for p in parts):
            continue
        best = max(
            (difflib.SequenceMatcher(None, bare, w).ratio()
             for w in twords if abs(len(w) - len(bare)) <= 2),
            default=0.0,
        )
        if best >= 0.80:
            continue
        soft.append(
            f"英文專名字幕查無（查證講者意圖，勿只查『詞存不存在』）｜｜{tok}"
        )
    return hard, soft


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
        m = META_LEAK_RE.search(stripped)
        if m:
            hard.append(f"分段後台資訊洩漏｜L{n}｜「{m.group(0)}」：{stripped.strip()[:50]}")
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
        soft.append(f"引述前後複述候選（模式33，逐對遮字測試）｜｜{r}…")

    quote_sections, main_sections = representative_quote_coverage(body)
    required_quote_sections = min(
        main_sections,
        max(1, (main_sections + 1) // 2),
    )
    if main_sections and quote_sections < required_quote_sections:
        hard.append(
            f"講者聲音不足｜全文｜只有 {quote_sections}/{main_sections} 個主要章節含實質直接引述，"
            f"至少需要 {required_quote_sections} 個；每章可用單段 30 字，或至少兩段各 6 字以上、"
            "合計 30 字的短對話，名詞碎片不計；這是章節覆蓋下限，不是引述字數配額"
        )

    transcript = _find_transcript(sys.argv[1])
    if transcript:
        t_hard, t_soft = transcript_checks(text, transcript)
        hard.extend(t_hard)
        soft.extend(t_soft)
    else:
        soft.append("找不到同名 _transcript.txt｜｜無法做覆蓋率與專名交叉核對，"
                    "確認字幕檔存在或於交付清單註明")

    for item in hard:
        print(f"[硬性] {item}")
    for item in soft:
        print(f"[候選] {item}")
    print(f"\n== 共 [硬性] {len(hard)} 筆（須清零重跑）、[候選] {len(soft)} 筆（逐筆三分類）==")
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
