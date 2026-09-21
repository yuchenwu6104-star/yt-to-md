#!/usr/bin/env python3
"""交付前機械清掃閘門（humanizer-zh 流程第 4 步：fresh review ＋ gate ＋ 上傳）。

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
from pathlib import Path

# ---- 黑名單（與 /yt yt_to_article.py 的 format_violations 同源，改一邊記得改另一邊）----

STAGE_PHRASES = (
    "補了一句", "補了一個", "補一句", "補一刀", "補了一刀", "補刀",
    "補了最後一刀", "補了一個畫面", "補了一個細節",
    "補上", "補了一段", "補述", "再補一句", "再補一個",
    "笑著接", "順著接", "馬上搭腔", "馬上吐槽", "再補一刀",
    "把方向拉回", "把梗接到", "話鋒一轉", "切入核心",
    "苦笑著說", "笑著說", "笑說", "打趣", "搶話",
    "開門見山", "先解釋為什麼", "點出另外",
    "另一個更即時的問題", "她的重點是", "他的重點是",
)
# 字面清單收不到「補了細節」或「補了一項事實」這類任意變體。
# 「補充」不含這些後續字樣，仍是允許的中性引述動詞。
SUPPLEMENT_RE = re.compile(r"補了|再補一|補上|補述")
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
# [硬性] 編輯稽核口吻／免責平衡句：查核過程與免責聲明寫進正文，讀者要的是講者說了
# 什麼，不是編輯替講者的話加註「這不算證據」。樣式刻意窄，且只掃引號外的串接區
# （main() 先 _strip_quotes，講者自己說的限定語一律豁免）。
# 來源：2026-08-05 Invest Like The Best 篇實際從成品刪掉的句子。
AUDIT_TONE_RE = re.compile(
    r"並非已(?:經)?落地的?(?:確定)?預測|"
    r"不是(?:公司|官方)?財測|"
    r"不代表每個.{0,12}都會|"
    r"不是證明|"
    r"這是.{0,8}轉述的.{0,8}假設|"
    r"[只不]能證明|"
    r"兩者是不同(?:指標|口徑)|"
    r"屬於.{0,6}個人觀點|"
    r"是.{0,8}的說法，不是"
)
AUDIT_PROSE_RE = re.compile(
    r"這段話的主體是|"
    r"(?:節目|影片|逐字稿|公司|官方(?:公告|文件|新聞稿)?)(?:中|裡|所)?"
    r"[^。；\n]{0,24}(?:沒有|未)(?:提供|交代|公布|列出|說明)|"
    r"[^。；\n]{1,24}(?:沒有|未)(?:提供|交代|公布|列出|說明)"
    r"(?:這|該|其)?(?:項|個)?(?:財測|數據|算法|公式|範圍|細節|資料)|"
    r"(?:SEC|官方|公司|財報|文件)[^。；\n]{0,20}(?:可確認|可核對)|"
    r"逐字稿中|"
    r"(?:出自|來自)[^。；\n]{0,18}(?:的說法|的口述|口徑)"
)
# 已升級為 [硬性] 的字樣（只能證明／不能證明／兩者是不同指標）不重複列在 [候選]
DEFENSIVE_HEDGE_RE = re.compile(
    r"只代表|不足以證明|不能因此|並不意味|"
    r"不等於|不構成|不可視為|不能當成|很難被描述|"
    r"仍待(?:後續)?(?:驗證|回答|實現)"
)
# 連續 4 個以上英文詞（非專名殘留候選；單一術語/人名不報）
ENGLISH_RUN_RE = re.compile(r"[A-Za-z][A-Za-z'’\-]*(?:\s+[A-Za-z][A-Za-z'’\-]*){3,}")

KANA_RE = re.compile(r"[぀-ゟ゠-ヿ]")
HANGUL_RE = re.compile(r"[가-힣]")

# ---- 引述計數口徑（本檔唯一實作；/yt yt_to_article.py 的 quote_metrics 同源，改一邊記得改另一邊）----
# 黃金範本 references/golden-sample.md 實測 63%（含開頭說明段），現行交付版 54%，退化版 9%。
CJK_RE = re.compile(r"[㐀-鿿]")
QUOTE_RE = re.compile(r"「([^「」]*)」")
QUOTE_MIN_CJK = 6          # 引述則數只算引號內 CJK ≥ 6 字者，名詞碎片不算一則
# 2026-09-21 政策反轉：下限改上限。
# 舊政策「預設一律直接引述」把體裁鎖死在引述串，下游怎麼潤都潤不成說明文
# （實測同一篇 humanized 0.902 → 下游 final 0.834，只降 0.07）。新政策要的是
# 重新編排過的第三人稱說明文，原話只留態度、比喻、自我否定、精確限定四種。
# 上限抓 0.55（硬性）：超過就代表選材與重組根本沒做，還是一份翻譯稿。
QUOTE_RATIO_CEIL_HARD = 0.55
QUOTE_RATIO_CEIL_SOFT = 0.30
# 下限不再設硬性。一篇完全沒有直接引述的說明文是合格的；引述是選配不是義務。
QUOTE_RATIO_FLOOR_SOFT = 0.03
# 註：曾有「成品引述數 ≥ 原稿 × 0.7」的 [硬性]，前提是 /yt 原稿也是文章。/yt 改成產出
# 中文全文順稿後（可能完全沒有「」或引號用法不同），這條必然誤判，已整條移除。


def strip_frontmatter(text: str) -> str:
    return re.sub(r"\A---\n.*?\n---\n", "", text, count=1, flags=re.DOTALL)


def quote_metrics(text: str) -> "tuple[int, int, int]":
    """統一口徑：回傳 (全文 CJK 字數, 引號內 CJK 字數, 引述則數)。

    先剝 YAML frontmatter，再用 CJK_RE / QUOTE_RE 計數。全檔只此一處實作，
    不要在別處重寫（口徑不一致曾造成 20 vs 22 的爭議）。
    """
    body = strip_frontmatter(text)
    total = len(CJK_RE.findall(body))
    quoted = count = 0
    for quote in QUOTE_RE.findall(body):
        n = len(CJK_RE.findall(quote))
        quoted += n
        if n >= QUOTE_MIN_CJK:
            count += 1
    return total, quoted, count


def _strip_quotes(s: str) -> str:
    """剔除「」內講者原話（引述區豁免串接區黑名單）。"""
    return re.sub(r"「[^「」]*」", "", s)


def _bigrams(s: str) -> set:
    s = re.sub(r"[^一-鿿]", "", s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _nums(s: str) -> set:
    return set(re.findall(r"[0-9][0-9,.]*\s*(?:兆|億|倍|%|萬)", s))


def _english_tokens(s: str) -> set:
    stop = {"the", "and", "or", "to", "of", "in", "on", "for", "ai"}
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9'-]+", s)
        if token.lower() not in stop
    }


def _same_claim(sentence: str, reference: str) -> bool:
    """Broadly recall repeated claims, including English-heavy proper nouns."""
    sentence_grams = _bigrams(sentence)
    reference_grams = _bigrams(reference)
    contain = (
        len(sentence_grams & reference_grams) / len(sentence_grams)
        if len(sentence_grams) >= 4 and len(reference_grams) >= 4
        else 0.0
    )
    shared_english = _english_tokens(sentence) & _english_tokens(reference)
    return (
        contain >= 0.5
        or len(_nums(sentence) & _nums(reference)) >= 2
        or len(shared_english) >= 3
        or (
            len(shared_english) >= 2
            and len(sentence_grams & reference_grams) >= 1
        )
    )


def _is_quote_para(p: str) -> bool:
    qs = re.findall(r"「([^「」]{15,})」", p)
    return bool(qs) and sum(len(x) for x in qs) > len(p) * 0.5


def _has_substantive_quote(p: str) -> bool:
    return any(len(quote) >= 15 for quote in re.findall(r"「([^「」]+)」", p))


def restatement_candidates(paras: list) -> list:
    """逐句版引述前預告與引述後解說偵測（模式 33）。

    與 /yt 的 _redundant_narration 同邏輯：逐句比較引述前後相鄰敘述，任一句的
    CJK 2-gram 過半被引述涵蓋、或與引述共用至少兩個帶單位數字，即為複述候選。
    """
    hits = []
    for i, cur in enumerate(paras):
        if cur.startswith("#") or not _has_substantive_quote(cur):
            continue
        quotes = re.findall(r"「([^「」]+)」", cur)
        quote = " ".join(quotes)
        qgrams, qnums = _bigrams(quote), _nums(quote)
        neighbors = []
        same_paragraph_narration = _strip_quotes(cur)
        if same_paragraph_narration.strip():
            neighbors.append(("同段串接", same_paragraph_narration))
        if i > 0 and not paras[i - 1].startswith("#") and not _is_quote_para(paras[i - 1]):
            neighbors.append(("引述前", paras[i - 1]))
        if i + 1 < len(paras) and not paras[i + 1].startswith("#") and not _is_quote_para(paras[i + 1]):
            neighbors.append(("引述後", paras[i + 1]))
        for position, paragraph in neighbors:
            for sent in re.split(r"[。！？；]", _strip_quotes(paragraph)):
                sg = _bigrams(sent)
                same_claim = _same_claim(sent, quote)
                if len(sg) < 6 and not same_claim:
                    continue
                contain = len(sg & qgrams) / len(sg) if sg else 0.0
                if (
                    contain >= 0.5
                    or len(_nums(sent) & qnums) >= 2
                    or same_claim
                ):
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


def _companion_path(article_path: str, suffix: str) -> Path:
    """Return a same-base companion path without guessing from directory state."""
    base = re.sub(r"\.md$", "", article_path)
    base = re.sub(r"_humanized$", "", base)
    return Path(base + suffix)


def _read_companion(article_path: str, suffix: str) -> "str | None":
    path = _companion_path(article_path, suffix)
    return path.read_text(encoding="utf-8") if path.exists() else None


def _find_transcript(article_path: str) -> "str | None":
    """自動尋找同名 `_transcript.txt`（與 SKILL.md 備齊來源規則一致）。"""
    return _read_companion(article_path, "_transcript.txt")


def transcript_checks(article: str, transcript: str) -> "tuple[list, list]":
    """拿字幕當 ground truth 的機械檢查。回傳 (hard, soft)。

    1. 覆蓋率粗檢（[候選]）：成文 CJK 字數對逐字稿比例過低＝疑似漏段，
       覆蓋（流程第 2 步對著逐字稿改稿）必須逐主題補查。
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
            f"覆蓋率偏低（第 2 步覆蓋加嚴，逐字稿→文章方向再走一遍）｜全文｜成文 {art_cjk} CJK 字 vs "
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


_SPEECH_VERBS = ("說道", "說", "表示", "回答", "回應", "回他", "反駁", "補充", "提醒",
                 "指出", "認為", "強調", "解釋", "形容", "追問", "接話", "問")
_ATTR_LEAD = (r"(?:也|還|又|先|再|就|才|則|接著|後來|最後|立刻|馬上|隨即|一|直接|"
              r"乾脆|只|甚至|卻|倒是|曾|曾經)*")
_NAME = r"([A-Z][A-Za-z'’\-]*(?:\s+[A-Z][A-Za-z'’\-]*){0,2})"
_ATTR_RE = re.compile(_NAME + r"\s*" + _ATTR_LEAD + r"\s*(?:" + "|".join(_SPEECH_VERBS) + r")")
_ATTR_COLON_RE = re.compile(_NAME + r"[^。！？\n「，、；：]{0,5}：「")
# 講者名不會是這些：機構、產品、模型、常見大寫詞（避免「Google 說」之類誤判為人）
_NOT_A_PERSON = frozenset({
    "gpu", "gpus", "cpu", "tpu", "tpus", "api", "apis", "llm", "llms", "ai", "agi",
    "google", "openai", "anthropic", "nvidia", "meta", "microsoft", "amazon", "apple",
    "tesla", "spacex", "claude", "gemini", "gpt", "codex", "opus", "sonnet", "haiku",
    "youtube", "podcast", "twitter", "slack", "gmail", "linux", "kubernetes", "python",
    "matrix", "apollo", "wall", "street", "the", "this", "that", "and", "but",
    "nba", "nfl", "etf", "ceo", "cfo", "cto", "iaas", "saas", "hbm", "dram",
})


def _looks_like_person(name: str) -> bool:
    """全大寫縮寫（GCP、NBA、MW）與過短的 token 不是人名。"""
    parts = name.split()
    if any(len(p) < 3 for p in parts):
        return False
    return not all(p.isupper() for p in parts)


def _speaker_counts(article: str) -> dict[str, int]:
    body = re.sub(r"\A---\n.*?\n---\n", "", article, count=1, flags=re.DOTALL)
    body = "\n".join(l for l in body.splitlines() if "原始影片" not in l)
    counts: dict = {}
    for m in _ATTR_RE.finditer(_strip_quotes(body)):
        counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    for m in _ATTR_COLON_RE.finditer(body):
        counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    return counts


def speaker_name_checks(article: str, transcript: str) -> "tuple[list, list]":
    """Require an attendance signal before an English name may attribute speech."""
    hard, soft = [], []
    # 中文／日文逐字稿沒有英文直呼樣式（「珍妮，妳怎麼看」不會寫成 "Jenny,"），
    # 這條規則只對以英文為主的逐字稿有效；其餘一律降級為候選。
    latin_source = len(re.findall(r"[一-鿿]", transcript)) < len(transcript) * 0.3
    counts = _speaker_counts(article)

    tl = transcript.lower()
    for name, cnt in sorted(counts.items(), key=lambda x: -x[1]):
        parts = name.split()
        if any(p.lower() in _NOT_A_PERSON for p in parts) or not _looks_like_person(name):
            continue
        n = re.escape(name.lower())
        present = name.lower() in tl or (len(parts) > 1 and parts[-1].lower() in tl)
        # 在場訊號分兩族：被直呼（vocative）與被介紹／自報（introduction）。
        # 兩者都沒有，才算「字幕完全沒有他在場的證據」。
        tail = r"(?:\s+[a-z][a-z'’\-]*)?"      # tl 已轉小寫；容許中間名：「Sarah G, how are you」
        mid = r"(?:\s+[a-z][a-z'’\-]*){0,2}"   # 介紹語與姓名之間的名字：「here with me is Rob Hamilton」
        present_sig = any(re.search(p, tl) for p in (
            rf"[,;]\s*{n}\b",
            rf"(?m)^\s*{n}{tail}\s*,",
            rf"\b{n}{tail}\s*,",
            rf"\b(?:hey|hi|hello|thanks|thank you|so|well|okay|ok|yeah|alright|"
            rf"all right|look|sorry|welcome|congrats)\s+{n}\b",
            rf"\b(?:i'm|i am|this is|my name is)\s+{n}\b",
            rf"\b{n}\s+here\b",
            rf"\b(?:talking to|talking with|joined by|joining us|here with me is|"
            rf"with me is|my guest is|guest today is|i'm here with|speaking with|"
            rf"chatting with|welcome back|we've got|we got|that's)"
            rf"{mid}\s+{n}\b",
        ))
        if present_sig:
            continue
        if latin_source:
            where = "字幕只在第三人稱脈絡提到此名" if present else "字幕查無此拼法"
            hard.append(
                f"講者名無在場證據｜｜{name}：成品當講者 {cnt} 次；{where}，"
                "沒有被直呼、被介紹或自報。改用主持人／另一位主持人／有人"
            )
        else:
            soft.append(
                f"講者名無在場訊號｜｜{name}：成品當講者 {cnt} 次；字幕有此名，"
                "但非英文逐字稿無法可靠套用英文直呼句型，需人工核對"
            )
    return hard, soft


_AUDIT_SELF_CERT_RE = re.compile(
    r"(?:已確認|確認無誤|看起來正確|均(?:已)?正確|重建(?:完成|無誤)|已完成.{0,12}(?:核對|確認))"
)
_AUDIT_NUMBER_RE = re.compile(r"(?:ASR|數字|金額|價格|時程|百分比|倍數|日期|單位)")
_AUDIT_CHANGE_RE = re.compile(r"(?:改為|改成|修正|更正|重建)")
_AUDIT_NO_CHANGE_RE = re.compile(
    r"(?:無|未|沒有|並未).{0,8}(?:ASR|數字|金額|價格|時程|百分比|倍數|日期|單位).{0,8}(?:改為|改成|修正|更正|重建)"
)
_AUDIT_UNFINISHED_RE = re.compile(
    r"(?:TODO|待盲審|待\s*fresh\s*reviewer|未完成|尚待處理)", re.IGNORECASE
)
_LINE_REF_RE = re.compile(r"\bL(\d+)\b", re.IGNORECASE)


def audit_contract_checks(audit: str) -> list:
    """Check that audit prose is evidence, not an untraceable self-certification."""
    hard = []
    missing = [
        str(n)
        for n in (1, 2, 3)
        if not re.search(rf"(?m)^\s*##\s*{n}\s*[.、．]", audit)
    ]
    if missing:
        hard.append(f"audit 缺固定章節｜｜{','.join(missing)}")
    for n, line in enumerate(audit.splitlines(), 1):
        m = _AUDIT_SELF_CERT_RE.search(line)
        if m:
            hard.append(f"audit 自證詞｜L{n}｜{m.group(0)}")
        unfinished = _AUDIT_UNFINISHED_RE.search(line)
        if unfinished:
            hard.append(f"audit 未完成字樣｜L{n}｜{unfinished.group(0)}")
        if (_AUDIT_NUMBER_RE.search(line) and _AUDIT_CHANGE_RE.search(line)
                and not _AUDIT_NO_CHANGE_RE.search(line)):
            refs = set(_LINE_REF_RE.findall(line))
            if len(refs) < 2:
                hard.append(
                    f"ASR 數字修正缺逐字稿內第二來源｜L{n}｜需同列附兩個不同 L 行號"
                )
    if not _LINE_REF_RE.search(audit):
        hard.append("audit 無逐字稿行號｜｜至少附一個 L 行號")
    if not re.search(r"\d+\s*(?:行|筆|則|處)", audit):
        hard.append("audit 無筆數｜｜記錄掃描行數、檢查筆數或改動處數")
    return hard


_PLAN_HEADERS = ("成品稱呼", "在場證據", "行號", "證據原文", "英文拼寫來源")
_ATTENDANCE_TYPES = ("被直呼", "被介紹", "自報")


def _plan_speaker_rows(plan: str) -> "tuple[dict[str, dict[str, str]], list]":
    """Parse the one machine-facing table in `<base>_plan.md`."""
    lines = plan.splitlines()
    for i, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not all(header in cells for header in _PLAN_HEADERS):
            continue
        indexes = {header: cells.index(header) for header in _PLAN_HEADERS}
        rows: dict[str, dict[str, str]] = {}
        errors = []
        for raw in lines[i + 2:]:
            if not raw.lstrip().startswith("|"):
                break
            values = [c.strip() for c in raw.strip().strip("|").split("|")]
            if len(values) < len(cells):
                errors.append("plan 講者地圖欄位不足")
                continue
            row = {header: values[indexes[header]] for header in _PLAN_HEADERS}
            if row["成品稱呼"]:
                rows[row["成品稱呼"].lower()] = row
        return rows, errors
    return {}, ["plan 缺可機械解析的講者地圖表"]


def _source_line_map(text: str) -> dict[int, str]:
    out = {}
    for physical, raw in enumerate(text.splitlines(), 1):
        m = re.match(r"^\s*(?:L)?(\d+)\s{1,2}(.*)$", raw)
        if m:
            out[int(m.group(1))] = m.group(2)
        else:
            out[physical] = raw
    return out


_ROLE_WORDS = (
    r"(?:chief|officer|founder|co-founder|director|president|professor|author|editor|"
    r"partner|researcher|columnist|correspondent|reporter|writer|journalist|analyst|"
    r"strategist|economist|senator|congress(?:man|woman)|representative|governor|"
    r"secretary|candidate|fellow|anchor|contributor|executive)"
)

# 職稱在名字前的同位語。比對原字串而非小寫版，靠大寫才認得出人名。
_TITLE_FIRST_RE = re.compile(
    r"\b(?:CEO|CFO|CTO|COO|[Cc]hief|[Pp]resident|[Ff]ounder|[Cc]o-founder|[Dd]irector|"
    r"[Pp]rofessor|[Aa]uthor|[Ee]ditor|[Pp]artner|[Rr]esearcher|[Cc]olumnist|"
    r"[Cc]orrespondent|[Rr]eporter|[Ww]riter|[Jj]ournalist|[Aa]nalyst|[Ss]trategist|"
    r"[Ee]conomist|[Ss]enator|[Cc]ongress(?:man|woman)|[Rr]epresentative|[Gg]overnor|"
    r"[Ss]ecretary|[Cc]andidate|[Ff]ellow|[Aa]nchor|[Cc]ontributor)\b"
    r"(?:\s+[a-z][a-z'’\-]*){0,3}\s+[A-Z][a-zA-Z'’\-]+\s+[A-Z][a-zA-Z'’\-]+"
)


def _attendance_signal(kind: str, source: str) -> bool:
    lower = source.lower()
    if kind == "被直呼":
        return bool(re.search(r"\b[a-z][a-z'’\-]*(?:\s+[a-z][a-z'’\-]*)?\s*,|,\s*[a-z][a-z'’\-]*\b", lower))
    if kind == "被介紹":
        return (
            bool(re.search(
                r"\b(?:talking to|talking with|joined\s+(?:\w+\s+){0,2}by|joined us|"
                r"joining us|here with me is|"
                r"with me is|my guest is|guest today is|guest was|guest is|my co-host|"
                r"we spoke with|i spoke with|spoke with|you spoke to|i'm here with|"
                r"speaking with|chatting with|welcome)\b", lower
            ))
            # 播放錄音片段也是引介：「play a bit of sound here from Jeff Currie」
            or bool(re.search(r"\bsound\b[^.]{0,40}\bfrom\b", lower))
            # 名字在前：「Gautam Mukunda is an opinion columnist」
            or bool(re.search(
                rf"\b[a-z][a-z'’\-]+\s+[a-z][a-z'’\-]+\s+is\s+.{{0,60}}?\b{_ROLE_WORDS}\b",
                lower
            ))
            # 代名詞在前：「He is an opinion columnist for Bloomberg」
            or bool(re.search(
                rf"\b(?:he|she|they)\s+(?:is|are|was|were)\s+"
                rf"(?:an?\s+|the\s+)?(?:[a-z][a-z'’\-]+\s+){{0,3}}{_ROLE_WORDS}\b",
                lower
            ))
            # 職稱在前：「anthropic CEO Dario Amodei」「Senator Chris Coons」
            # 「Bloomberg Weekend senior writer Morgan Meeker」。這一族在
            # 2026-09-13 擴充時漏掉，Bloomberg 週末節目 25 位來賓撞掉 10 位。
            or bool(_TITLE_FIRST_RE.search(source))
        )
    if kind == "自報":
        return bool(re.search(r"\b(?:i'm|i am|my name is)\s+[a-z]|\b[a-z][a-z'’\-]*\s+here\b", lower))
    return False


def plan_contract_checks(
    article: str,
    plan: "str | None",
    source_lines: "str | None" = None,
    metadata: "str | None" = None,
) -> list:
    """Validate the persisted speaker map and spelling provenance used by the gate."""
    if plan is None:
        return ["缺 plan 檔｜｜找不到同名 _plan.md，關 1 未落檔"]
    rows, hard = _plan_speaker_rows(plan)
    for marker in ("(a)", "(b)", "(c)", "(d)"):
        if marker not in plan:
            hard.append(f"plan 缺固定區塊｜｜{marker}")
    for n, line in enumerate(plan.splitlines(), 1):
        if (_AUDIT_NUMBER_RE.search(line) and _AUDIT_CHANGE_RE.search(line)
                and not _AUDIT_NO_CHANGE_RE.search(line)):
            if len(set(_LINE_REF_RE.findall(line))) < 2:
                hard.append(
                    f"plan ASR 數字修正缺第二來源｜L{n}｜需同列附兩個不同 L 行號"
                )
    line_map = _source_line_map(source_lines or "")
    for name in _speaker_counts(article):
        parts = name.split()
        if any(p.lower() in _NOT_A_PERSON for p in parts) or not _looks_like_person(name):
            continue
        row = rows.get(name.lower())
        if row is None:
            hard.append(f"plan 無講者列｜｜{name}")
            continue
        kind = row["在場證據"]
        if kind not in _ATTENDANCE_TYPES:
            hard.append(f"plan 在場證據無效｜｜{name}：{kind or '空白'}")
        refs = [int(x) for x in _LINE_REF_RE.findall(row["行號"])]
        if not refs:
            hard.append(f"plan 在場證據無行號｜｜{name}")
        elif line_map:
            missing = [ref for ref in refs if ref not in line_map]
            if missing:
                hard.append(f"plan 行號超出來源｜｜{name}：{','.join('L' + str(x) for x in missing)}")
            cited = " ".join(line_map.get(ref, "") for ref in refs)
            if kind in _ATTENDANCE_TYPES and not _attendance_signal(kind, cited):
                hard.append(f"plan 行號不支持在場證據｜｜{name}：{kind} {row['行號']}")
            excerpt = re.sub(r"\s+", " ", row["證據原文"].strip("` ").lower())
            cited_norm = re.sub(r"\s+", " ", cited.lower())
            if not excerpt or excerpt not in cited_norm:
                hard.append(f"plan 證據原文不在引用行｜｜{name}：{row['行號']}")
        source = row["英文拼寫來源"].strip("` ")
        # 「搜尋 <URL>」是 2026-08-15 新增的第四種來源，只給人名校拼字用：
        # description 常只有 x.com/DavidSacks 這種無空格 handle，正確全名反而過不了，
        # 而畫面那條在 YouTube 擋下載時完全不可達。授權層級寫在 SKILL.md：
        # 只有關 1（查證層）與關 3（稽核層）可以查，關 2 寫作員不行；
        # 且該人必須先由標題／description／字幕確認在場，搜尋不得用來新增一個人。
        if not (source == "影片標題" or source.lower() == "description"
                or re.fullmatch(r"畫面\s+\d{1,2}:\d{2}", source)
                or re.fullmatch(r"搜尋\s+https?://\S+", source)):
            hard.append(
                f"英文拼寫來源無效｜｜{name}：只能填影片標題、description、畫面時間碼"
                "或「搜尋 <URL>」（搜尋僅限人名拼字，且人須另有在場證據）"
            )
        elif source == "影片標題":
            titles = " ".join(re.findall(
                r'(?mi)^video_title:\s*"?(.+?)"?\s*$', metadata or ""
            )).lower()
            if name.lower() not in titles:
                hard.append(f"影片標題查無成品拼法｜｜{name}")
        elif source.lower() == "description":
            description = re.split(
                r"(?mi)^---\s*description\s*---\s*$", metadata or "", maxsplit=1
            )
            description_text = description[1].lower() if len(description) == 2 else ""
            if name.lower() not in description_text:
                hard.append(f"description 查無成品拼法｜｜{name}")
    return hard


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
        m = SUPPLEMENT_RE.search(stripped)
        if m:
            hard.append(
                "「補」字引述動詞（只准用「補充」）"
                f"｜L{n}｜「{m.group(0)}」：{stripped.strip()[:50]}"
            )
        m = EDITORIAL_RE.search(stripped)
        if m:
            # 2026-09-21 降級成 [候選]：「很直接／很直白」比 TONE_WORDS 溫和得多，
            # 重排政策下第三人稱敘述本來就會描述講者怎麼回答，當硬性會為了過關把
            # 不難看的句子改掉。真正替講者加態度的字仍在 TONE_WORDS 裡擋著。
            soft.append(f"語氣打分（輕）｜L{n}｜「{m.group(0)}」：{stripped.strip()[:50]}")
        m = META_LEAK_RE.search(stripped)
        if m:
            hard.append(f"分段後台資訊洩漏｜L{n}｜「{m.group(0)}」：{stripped.strip()[:50]}")
        m = AUDIT_TONE_RE.search(stripped)
        if m:
            hard.append(
                f"編輯稽核口吻／免責句（正文不放查核結論，整句刪）｜L{n}｜"
                f"「{m.group(0)}」：{stripped.strip()[:60]}"
            )
        m = REFRAME_RE.search(stripped)
        if m:
            soft.append(f"重新框定句型（模式9/35，三分類）｜L{n}｜「{m.group(0)}」：{stripped.strip()[:50]}")
        m = AUDIT_PROSE_RE.search(stripped)
        if m:
            soft.append(f"查證報告侵入正文（模式36，刪句測試）｜L{n}｜「{m.group(0)}」：{stripped.strip()[:70]}")
        m = DEFENSIVE_HEDGE_RE.search(stripped)
        if m:
            soft.append(f"編輯護欄／段尾辯護（模式36，三分類）｜L{n}｜「{m.group(0)}」：{stripped.strip()[:70]}")
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

    total_cjk, quoted_cjk, _ = quote_metrics(text)
    ratio = quoted_cjk / total_cjk if total_cjk else 0.0
    if total_cjk and ratio > QUOTE_RATIO_CEIL_HARD:
        hard.append(
            f"引述佔比過高，還是一份翻譯稿｜全文｜引號內 {quoted_cjk}／全文 {total_cjk} CJK 字"
            f"＝{ratio:.0%}（上限 {QUOTE_RATIO_CEIL_HARD:.0%}）；重新編排與去冗贅沒有做，"
            "原話預設要改寫成第三人稱敘述，只有態度、比喻、自我否定、精確限定值得留原話"
        )
    elif total_cjk and ratio > QUOTE_RATIO_CEIL_SOFT:
        soft.append(
            f"引述佔比偏高｜全文｜引號內 {quoted_cjk}／全文 {total_cjk} CJK 字＝{ratio:.0%}"
            f"（提示上限 {QUOTE_RATIO_CEIL_SOFT:.0%}）；逐則問「這則非原話不可嗎」，"
            "技術定義、數字、流程描述、客戶案例、歷史背景一律改寫"
        )
    elif total_cjk and ratio < QUOTE_RATIO_FLOOR_SOFT:
        soft.append(
            f"全篇幾乎沒有原話｜全文｜引號內 {quoted_cjk}／全文 {total_cjk} CJK 字＝{ratio:.0%}；"
            "不是硬性，但通篇沒有一句講者的原話時，回頭確認有沒有哪句態度、比喻或精確限定"
            "被改寫掉了方向"
        )

    # 連續兩段以引述為主＝還沒編輯完（下游編輯實務判準，非字數比例）
    run, runs = 0, []
    for p in paras:
        pc = len(CJK_RE.findall(p))
        qc = sum(len(CJK_RE.findall(q)) for q in QUOTE_RE.findall(p))
        if pc >= 20 and qc / pc > 0.7:
            run += 1
            if run >= 2:
                runs.append(p[:40])
        else:
            run = 0
    for r in runs[:5]:
        soft.append(f"連續兩段都以原話為主（編輯未完成）｜｜{r}…")
    if len(runs) > 5:
        soft.append(f"連續原話段落另有 {len(runs) - 5} 處未列出｜全文｜")

    # 編輯者自行寫下的因果與強斷言：重排政策下最容易偷渡超譯的地方
    stripped = QUOTE_RE.sub("", body)
    causal = [w for w in ("因此", "所以", "導致", "促使", "使得", "證明", "顯然",
                          "勢必", "核心原因", "最大問題", "真正意義")
              if w in stripped]
    if causal:
        n = sum(stripped.count(w) for w in causal)
        soft.append(
            f"編輯者敘述裡的因果與強斷言｜全文｜{'、'.join(causal)} 共 {n} 處；"
            "逐處問「來源真的表達了因果，還是只是先後或相關」，只是先後就改成接著／同時／"
            "在這個背景下"
        )

    is_humanized = sys.argv[1].endswith("_humanized.md")
    plan = _read_companion(sys.argv[1], "_plan.md") if is_humanized else None
    audit = _read_companion(sys.argv[1], "_audit.md") if is_humanized else None
    transcript = _find_transcript(sys.argv[1])
    if transcript:
        t_hard, t_soft = transcript_checks(text, transcript)
        hard.extend(t_hard)
        soft.extend(t_soft)
        source_lines = _read_companion(sys.argv[1], "_lines.txt") or transcript
        metadata = "\n".join(filter(None, (
            _read_companion(sys.argv[1], "_meta.txt"),
            re.match(r"\A---\n(.*?)\n---\n", text, flags=re.DOTALL).group(1)
            if re.match(r"\A---\n(.*?)\n---\n", text, flags=re.DOTALL) else None,
        )))
        if is_humanized:
            hard.extend(plan_contract_checks(text, plan, source_lines, metadata))
        else:
            s_hard, s_soft = speaker_name_checks(text, transcript)
            hard.extend(s_hard)
            soft.extend(s_soft)
    else:
        message = "找不到同名 _transcript.txt｜｜無法做覆蓋率、歸屬與專名交叉核對"
        (hard if is_humanized else soft).append(message)

    if is_humanized:
        if audit is None:
            hard.append("缺 audit 檔｜｜找不到同名 _audit.md")
        else:
            hard.extend(audit_contract_checks(audit))

    for item in hard:
        print(f"[硬性] {item}")
    for item in soft:
        print(f"[候選] {item}")
    print(f"\n== 共 [硬性] {len(hard)} 筆（須清零重跑）、[候選] {len(soft)} 筆（逐筆三分類）==")
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
