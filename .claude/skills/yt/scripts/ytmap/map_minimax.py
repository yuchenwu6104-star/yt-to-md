#!/usr/bin/env python3
"""用 MiniMax 產出逐字稿地圖（苦力層）。

這一層的產出是**索引不是內容**：行號區間、論點清單、可疑專名清單。
指標錯了下游一瞥就知道，內容錯了得整篇回對——所以苦力活該做成指標。

刻意跑兩次取交集／聯集（見 merge_maps.py）：模型的錯是隨機的，規則管不了
隨機性，但便宜的重複可以。兩次獨立標記對同一段給出不同說話人，這件事本身
就是告警，而且不需要任何人判斷誰對。

紀律用程式執行不靠 prompt 求它守：propers 的 name 若沒有逐字出現在它引用的
行裡，直接丟棄。實測 M3 即使被明令「照抄字幕拼法」，仍會多列一筆它認為正確
的拼法並在 note 裡寫答案，那正是我們要擋掉的東西（拼法還原是下游查證的工作）。
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

BASE = os.getenv("ANTHROPIC_BASE_URL", "https://api.minimax.io/anthropic")
KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL = os.getenv("MINIMAX_MODEL", "MiniMax-M3")
CHUNK = 150

SYSTEM = """你是逐字稿索引員。讀一段帶行號的英文逐字稿，輸出 JSON 索引。不寫文章、不翻譯成文、不評論。

只輸出 JSON，不要任何說明文字，不要 markdown code fence。格式：
{"segments":[{"lines":[起,迄],"topic":"一句話主題(繁體中文)"}],
 "turns":[{"lines":[起,迄],"speaker":"說話人","confidence":"高|中|低","evidence":"字幕裡的換手訊號原文"}],
 "claims":[{"claim":"一句話論點(繁體中文)","lines":[起,迄]}],
 "quote_candidates":[{"lines":[起,迄],"why":"數字|比喻|第一人稱立場|語氣強|具體場景","gist":"一句話(繁體中文)"}],
 "propers":[{"name":"原文拼法","lines":[行號],"flag":"完整|不完整|拼法可疑","note":"客觀描述"}],
 "skip_spans":[{"lines":[起,迄],"kind":"廣告|寒暄|離題|口誤重啟"}],
 "hard_to_translate":[{"lines":[起,迄],"why":"雙關|慣用語|省略|語意不完整","note":"簡述"}]}

規則：
- 行號一律照原文行首的數字，不要自己數。所有行號都必須落在本段給你的範圍內。
- `>>` 是字幕的換手標記，當第一線索但不是判決（實測約一成是誤插，同一人續講被切開）。
- **claims 要細：每 8 到 15 行至少抽出一條論點。** 講者換一個理由、換一個角度、給一個新事實，就是一條新論點。寧可切太細，不要合併成籠統的大論點。
- **propers 的 `name` 必須逐字照抄逐字稿裡出現的拼法**，即使你認得那個人、知道正確拼法也不准寫正確的。同一實體有多種拼法就分別列成多筆。**修正拼法是下游查證的工作，你只負責指出哪裡可疑。**
- flag：只有名沒有姓、或「名字＋機構」形態 → 不完整；拼法不像正常英文、或前後不一致 → 拼法可疑。note 只寫客觀描述（缺姓氏、第 N 行作另一種拼法），不要寫你猜的正確答案。
- quote_candidates 標準是「轉述做不到」：具體數字、比喻、第一人稱立場揭露、具體場景細節、語氣強烈的判斷。寧可多標不要少標，取捨是下游的工作。
- 拿不準就標低信心或不填，不要猜、不要補完、不要用背景知識填空。"""

KEYS = ("segments", "turns", "claims", "quote_candidates",
        "propers", "skip_spans", "hard_to_translate")


def _call(user: str, retries: int = 3) -> dict:
    with httpx.Client(timeout=httpx.Timeout(600.0, connect=30.0)) as c:
        for i in range(retries):
            try:
                r = c.post(
                    f"{BASE}/v1/messages",
                    headers={"x-api-key": KEY,
                             "anthropic-version": "2023-06-01",
                             "content-type": "application/json"},
                    json={"model": MODEL, "thinking": {"type": "disabled"},
                          "max_tokens": 16384, "system": SYSTEM,
                          "messages": [{"role": "user", "content": user}]},
                )
            except (httpx.TimeoutException, httpx.NetworkError):
                if i == retries - 1:
                    raise
                time.sleep(10 * (i + 1))
                continue
            if r.status_code >= 500 and i < retries - 1:
                time.sleep(5 * (i + 1))
                continue
            r.raise_for_status()
            txt = "".join(b.get("text", "") for b in r.json().get("content", []))
            txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
            try:
                return json.loads(txt)
            except ValueError:
                # 截斷或多餘尾巴時，取最外層大括號再試一次。
                m = re.search(r"\{.*\}", txt, re.S)
                if m:
                    try:
                        return json.loads(m.group(0))
                    except ValueError:
                        pass
                if i == retries - 1:
                    return {}
    return {}


def _in_range(entry: dict, lo: int, hi: int) -> bool:
    v = entry.get("lines")
    if isinstance(v, list) and v:
        nums = [x for x in v if isinstance(x, int)]
        return bool(nums) and all(lo <= n <= hi for n in nums)
    return False


def _drop_invented_propers(propers: list, lines: list[str]) -> tuple[list, int]:
    """name 沒有逐字出現在它引用的行裡就丟掉。

    模型會擅自補上「它認為正確」的拼法，那正是這一層不該做的事。
    用程式擋比用 prompt 求它守可靠。
    """
    keep, dropped = [], 0
    for p in propers:
        name = str(p.get("name", "")).strip()
        nums = [n for n in p.get("lines", []) if isinstance(n, int)]
        if not name or not nums:
            dropped += 1
            continue
        hay = " ".join(lines[n - 1] for n in nums if 1 <= n <= len(lines)).lower()
        if name.lower() in hay:
            keep.append(p)
        else:
            dropped += 1
    return keep, dropped


def build(lines: list[str], context: str, tag: str) -> dict:
    out = {k: [] for k in KEYS}
    total = len(lines)
    for start in range(0, total, CHUNK):
        lo, hi = start + 1, min(start + CHUNK, total)
        body = "\n".join(f"{i:>5}  {lines[i - 1]}" for i in range(lo, hi + 1))
        print(f"  [{tag}] {lo}-{hi}/{total}", flush=True)
        data = _call(f"{context}\n\n逐字稿第 {lo} 到 {hi} 行：\n\n{body}")
        for k in KEYS:
            v = data.get(k)
            if isinstance(v, list):
                out[k].extend(e for e in v if isinstance(e, dict) and _in_range(e, lo, hi))
    out["propers"], dropped = _drop_invented_propers(out["propers"], lines)
    if dropped:
        print(f"  [{tag}] 丟棄 {dropped} 筆模型自行補入或行號對不上的專名", flush=True)
    return out


def main() -> None:
    if not KEY:
        sys.exit("ANTHROPIC_API_KEY 未設定")
    if len(sys.argv) < 4:
        sys.exit("用法：map_minimax.py <lines.txt> <輸出.json> <節目脈絡說明> [tag]")
    lines = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
    m = build(lines, sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "map")
    Path(sys.argv[2]).write_text(json.dumps(m, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
    print("  " + "｜".join(f"{k} {len(m[k])}" for k in KEYS))


if __name__ == "__main__":
    main()
