#!/usr/bin/env python3
"""產出中文分流稿：讓人三分鐘內判斷這集要不要進 humanizer。

定位很重要，寫錯就沒用：這份的讀者是使用者本人，讀完只做一個決定。
它不發表，也不當 humanizer 的素材。所以它的規格跟摘要相反——

  摘要   精煉、可發表、具體細節可丟
  分流稿 寧可長寧可雜，具體細節一律保留，因為有沒有料就是看這個

唯一真正的失敗是寫得太乾，讓使用者以為這集沒料而跳過（假陰性）。
多讀幾行只是小麻煩，錯過一集好的沒有補救。

查證標記寫在正文，之後由 strip_markers.py 抽進 JSON，正文只留「說了什麼」。
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

SYSTEM = """你在寫一份中文分流稿的其中一段。這不是文章，是給人快速判斷「這集值不值得深做」的閱讀稿。

它不會發表，也不會被拿去當寫文章的素材。所以：

- **寧可長、寧可雜，不可抽象。** 具體的東西一律保留：數字、年份、人名、地名、比喻、故事、場景細節。「他談到私募信貸的成長」是失敗的寫法；把講者實際講的數字和場景原原本本寫出來才對。
- **不確定的地方明白標出來**，不要藏。
- 通順可讀即可，不必雕琢文筆。

寫法：
- 段落式，不要條列。開頭直接寫內容，不要導言、不要結語、不要「本段將談到」這類鋪陳。
- 說話人一律標清楚（誰問、誰答）。
- 引述講者原話用「」，只寫中文，不附英文原句（少數雙關或關鍵術語可在括號附英文單詞）。
- 全篇繁體中文。**不要用破折號（——）**，改用逗號、句號或括號。
- 語助詞（um、uh、like）不用翻出來。

查證標記（用全形括號，之後會被程式抽走）：
- `（字幕：xxx，拼法可疑，未查證）` 專名拼法可疑或不完整時，寫出字幕原文拼法。**不要替它補上你認為正確的拼法或全名。**
- `（語意不明）` 你讀不懂那句英文在講什麼時直接標。**不要硬翻成一句通順但空洞的中文。**
- `（量級可疑：…）` 同一段裡數字量級懸殊時照抄原文數字並標記，不要自己換算或修正。

只輸出這一段的中文內容本身，不要標題、不要說明、不要 markdown code fence。"""


def _call(user: str, retries: int = 3) -> str:
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
            return "".join(b.get("text", "") for b in r.json().get("content", [])).strip()
    return ""


def _covered(span: list, skips: list) -> bool:
    a, b = span
    for s in skips:
        x, y = s.get("lines", [0, -1])[:2]
        if x <= a and b <= y:
            return True
    return False


def main() -> None:
    if not KEY:
        sys.exit("ANTHROPIC_API_KEY 未設定")
    if len(sys.argv) < 5:
        sys.exit("用法：triage_minimax.py <lines.txt> <map.json> <輸出.md> <節目脈絡>")
    lines = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
    m = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    context = sys.argv[4]

    segs = sorted(m.get("segments", []), key=lambda s: s["lines"][0])
    skips = m.get("skip_spans", [])
    out = ["```", m.get("health", "").strip(), "```", ""]

    for i, seg in enumerate(segs, 1):
        a, b = seg["lines"][0], seg["lines"][1]
        topic = seg.get("topic", "")
        print(f"  [{i}/{len(segs)}] L{a}-{b} {topic[:30]}", flush=True)
        if _covered([a, b], skips):
            out.append(f"## {topic}（L{a}-L{b}）\n\n（廣告或寒暄，略）\n")
            continue
        body = "\n".join(f"{n:>5}  {lines[n - 1]}" for n in range(a, min(b, len(lines)) + 1))
        hints = [p for p in m.get("propers", [])
                 if p.get("flag") != "完整" and any(a <= n <= b for n in p.get("lines", []))]
        hint = ""
        if hints:
            hint = "\n\n本段拼法可疑或不完整的專名（照字幕原樣寫並標記，不要補正）：" + \
                   "、".join(f"{p['name']}（{p.get('flag')}）" for p in hints[:12])
        text = _call(f"{context}\n\n本段主題：{topic}{hint}\n\n逐字稿第 {a} 到 {b} 行：\n\n{body}")
        out.append(f"## {topic}（L{a}-L{b}）\n\n{text}\n")

    Path(sys.argv[3]).write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"  已寫入 {sys.argv[3]}")


if __name__ == "__main__":
    main()
