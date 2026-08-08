#!/usr/bin/env python3
"""從英文字幕產出證據索引（_index.json）。

設計原則：這一層完全不呼叫模型。數字抽取、拼字變體分群、廣告偵測都是
確定性的工作，用純 Python 做又快又不會幻覺。需要語意判斷的部分
（輪次切分、重複論點）留給上游的 MiniMax，判斷留給 humanizer。

產出的 index 讓下游三件事從「靠正則猜」變成「查表」：
  1. 文章裡的數字不在 numbers 表上 → 捏造嫌疑
  2. 同一專名有多種拼法 → ASR 壞掉，humanizer 必須查證
  3. 論點認領表每列指得出行號 → 沒出處就寫不出那一節
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

# ---------------------------------------------------------------- 數字

SCALE = {
    "trillion": 1_000_000_000_000,
    "billion": 1_000_000_000,
    "million": 1_000_000,
    "thousand": 1_000,
    "k": 1_000,
}
NUM_RE = re.compile(
    r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*"
    r"(trillion|billion|million|thousand|k)?\b",
    re.I,
)
# 帳戶與法條的代號長得像「數字＋單位」，會被當成 401,000 之類的量級，
# 進了量級對帳就是穩定誤報（Kelly 那集三個疑點有兩個是 401k）。
NOT_A_QUANTITY = {"401k", "403b", "457b", "1031", "1099", "529", "10k", "10q", "8k"}


def extract_numbers(lines: list[str]) -> list[dict]:
    out = []
    for i, line in enumerate(lines, 1):
        for m in NUM_RE.finditer(line):
            raw, scale = m.group(1), (m.group(2) or "").lower()
            if m.group(0).replace(" ", "").replace(",", "").lower() in NOT_A_QUANTITY:
                continue
            try:
                value = float(raw.replace(",", ""))
            except ValueError:
                continue
            if scale:
                value *= SCALE[scale]
            start = max(0, m.start() - 45)
            out.append(
                {
                    "line": i,
                    "raw": m.group(0).strip(),
                    "value": value,
                    "scale": scale or None,
                    "context": line[start : m.end() + 45].strip(),
                }
            )
    return out


# ---------------------------------------------------------------- 專名

STOP = {
    "the", "a", "an", "and", "but", "or", "so", "then", "now", "well", "yeah",
    "i", "you", "he", "she", "it", "we", "they", "this", "that", "these",
    "there", "here", "what", "when", "where", "why", "how", "if", "is", "was",
    "and", "no", "not", "in", "on", "at", "to", "of", "for", "with", "like",
    "just", "really", "very", "okay", "ok", "um", "uh", "oh", "right", "yes",
    "let", "look", "think", "know", "mean", "say", "said", "get", "got", "one",
    "two", "three", "first", "last", "next", "because", "about", "from", "all",
    "my", "your", "his", "her", "its", "our", "their", "me", "him", "them",
    "us", "do", "does", "did", "have", "has", "had", "be", "been", "am", "are",
    "were", "will", "would", "can", "could", "should", "may", "might", "must",
}
# 句首的大寫字無法區分「專名」與「句子開頭」，所以只收句中的大寫詞。
PROPER_RE = re.compile(r"(?<![.!?]\s)(?<!^)\b([A-Z][a-zA-Z]{2,}(?:\s+[A-Z][a-zA-Z]{2,})?)\b")


def extract_propers(lines: list[str]) -> dict[str, list[int]]:
    hits: dict[str, list[int]] = defaultdict(list)
    for i, line in enumerate(lines, 1):
        for m in PROPER_RE.finditer(line):
            tok = m.group(1).strip()
            if tok.lower() in STOP:
                continue
            hits[tok].append(i)
    return dict(hits)


# --------------------------------------------- ASR 拼字變體分群（核心）

def skeleton(word: str) -> str:
    """壓成骨架：小寫、去母音（保留首字）、收合重複字母。

    ASR 走音幾乎都發生在母音與重複子音上，骨架相同代表很可能是同一個詞。
    Kimmy/Kimi -> km；Neatron/Neotron -> ntrn；Curser/Cursor -> crsr。
    """
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return ""
    head, tail = w[0], re.sub(r"[aeiou]", "", w[1:])
    out = head + tail
    return re.sub(r"(.)\1+", r"\1", out)


def cluster_variants(propers: dict[str, list[int]]) -> list[dict]:
    """把骨架相同、或字面極相近的拼法歸成一群。

    一群裡出現兩種以上拼法，就是 ASR 失敗的機械證據，
    不需要任何外部知識就能判定「這裡要查證」。
    """
    by_skeleton: dict[str, list[str]] = defaultdict(list)
    for word in propers:
        first = word.split()[0]
        key = skeleton(first)
        if len(key) >= 2:
            by_skeleton[key].append(word)

    clusters = []
    for key, words in by_skeleton.items():
        if len(words) < 2:
            continue
        # 骨架相同還不夠，字面也要夠像，避免把不相干的詞湊成一群。
        keep = []
        for w in words:
            if any(
                SequenceMatcher(None, w.lower(), o.lower()).ratio() >= 0.6
                for o in words
                if o != w
            ):
                keep.append(w)
        # 「X」與「X Y」是同一個詞的長短寫法，不是走音（Silicon / Silicon Valley、
        # Starlink / Starlink Direct）。整群互為前綴時剔除，這是最大宗的誤報來源。
        lowered = [w.lower() for w in keep]
        keep = [
            w
            for w, lw in zip(keep, lowered)
            if not any(o != lw and (o.startswith(lw) or lw.startswith(o)) for o in lowered)
        ]
        if len(keep) < 2:
            continue
        clusters.append(
            {
                "skeleton": key,
                "variants": sorted(
                    ({"spelling": w, "count": len(propers[w]),
                      "lines": propers[w][:8]} for w in keep),
                    key=lambda d: -d["count"],
                ),
            }
        )
    return sorted(clusters, key=lambda c: -sum(v["count"] for v in c["variants"]))


# ---------------------------------------------------------------- 廣告

SPONSOR_HINT = re.compile(
    r"\b(sponsor|sponsored by|brought to you by|promo code|\.com/[a-z]+\b|"
    r"learn more at|visit\s+\w+\.com|get a special offer|free trial)\b",
    re.I,
)


def find_ad_spans(lines: list[str], window: int = 12) -> list[dict]:
    """廣告口播的訊號密集且集中，用滑窗抓連續區段。"""
    flagged = [i for i, l in enumerate(lines, 1) if SPONSOR_HINT.search(l)]
    if not flagged:
        return []
    spans, start, prev = [], flagged[0], flagged[0]
    for i in flagged[1:]:
        if i - prev > window:
            spans.append((start, prev))
            start = i
        prev = i
    spans.append((start, prev))
    return [
        {"start": max(1, s - 4), "end": min(len(lines), e + 4)}
        for s, e in spans
    ]


# ------------------------------------------------------------ 未完成句

TRAILING = re.compile(
    r"\b(and|but|or|so|that|which|because|if|when|to|of|for|with|the|a|an|"
    r"they|we|it|is|was|would|could)\s*$",
    re.I,
)


def find_unfinished(lines: list[str]) -> list[int]:
    """句尾停在連接詞或介系詞，多半是被打斷。

    這類地方最容易被下游「順手補完」，補完就是捏造，先標出來。
    """
    return [
        i
        for i, l in enumerate(lines, 1)
        if l.strip() and TRAILING.search(l.strip())
    ]


# ---------------------------------------------------------------- main


def build(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    propers = extract_propers(lines)
    return {
        "source": path.name,
        "line_count": len(lines),
        "numbers": extract_numbers(lines),
        "propers": {
            w: {"count": len(ls), "lines": ls[:12]}
            for w, ls in sorted(propers.items(), key=lambda kv: -len(kv[1]))
        },
        "asr_variant_clusters": cluster_variants(propers),
        "ad_spans": find_ad_spans(lines),
        "unfinished_lines": find_unfinished(lines),
    }


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("用法：build_index.py <_transcript.txt> [輸出.json]")
    src = Path(sys.argv[1])
    if not src.exists():
        sys.exit(f"找不到字幕檔：{src}")
    index = build(src)
    out = (
        Path(sys.argv[2])
        if len(sys.argv) > 2
        else src.with_name(re.sub(r"_transcript$", "_index", src.stem) + ".json")
    )
    out.write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"已寫入 {out}")
    print(f"  數字 {len(index['numbers'])} 筆")
    print(f"  專名候選 {len(index['propers'])} 個")
    print(f"  ASR 拼字變體群 {len(index['asr_variant_clusters'])} 組")
    print(f"  廣告區段 {len(index['ad_spans'])} 段")
    print(f"  未完成句 {len(index['unfinished_lines'])} 行")


if __name__ == "__main__":
    main()
