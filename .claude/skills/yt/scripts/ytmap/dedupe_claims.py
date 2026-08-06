#!/usr/bin/env python3
"""把分段抽出的論點合併成「同一論點的多次出現」。

地圖是分段跑的，跨段看不到重複。但重複偵測正是這一層最有價值的產出：
長談節目會不斷回頭重提同一件事，照對話順序寫就會講五六次，那是成品被
退件的頭號原因。合併只需要論點文字，不需要逐字稿，所以整份一次送得完。

輸出的每條有 occurrences（全部出現位置）與 strongest（講得最完整的那次），
下游據此做到「每個論點只留一次，而那一次用原話」。
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

SYSTEM = """你會收到一份編號的論點清單，每條附行號區間。把講的是同一件事的論點併成一組。

只輸出 JSON，不要說明文字，不要 markdown code fence：
{"groups":[{"ids":[1,7,23],"claim":"合併後的一句話論點(繁體中文)","strongest":7}]}

規則：
- **每一條都必須恰好出現在一個 group 裡**，不可遺漏、不可重複認領。只出現一次的論點也要自成一組。
- 「同一件事」指的是同一個主張、同一個事實、同一個比喻。換個角度講同一個主張＝同一組；相關但不同的主張＝不同組。
- `strongest` 填該組裡講得最完整、最有力的那一條的編號。
- 寧可分開也不要亂併。併錯會讓下游漏掉一個論點，比多留一條重複嚴重。"""


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
                m = re.search(r"\{.*\}", txt, re.S)
                if m:
                    try:
                        return json.loads(m.group(0))
                    except ValueError:
                        pass
    return {}


def dedupe(claims: list) -> list:
    if len(claims) < 2:
        return [{"claim": c.get("claim", ""), "occurrences": [c.get("lines", [])],
                 "strongest": c.get("lines", [])} for c in claims]
    listing = "\n".join(
        f"{i}. [{c.get('lines', [0, 0])[0]}-{c.get('lines', [0, 0])[-1]}] {c.get('claim','')}"
        for i, c in enumerate(claims, 1)
    )
    data = _call(f"論點清單（共 {len(claims)} 條）：\n\n{listing}")
    groups = data.get("groups") if isinstance(data, dict) else None
    if not isinstance(groups, list) or not groups:
        # 併不出來就退回「每條各自一組」，寧可不去重也不要弄丟論點。
        print("  [dedupe] 合併失敗，退回不去重", file=sys.stderr)
        return [{"claim": c.get("claim", ""), "occurrences": [c.get("lines", [])],
                 "strongest": c.get("lines", [])} for c in claims]

    out, claimed = [], set()
    for g in groups:
        ids = [i for i in g.get("ids", [])
               if isinstance(i, int) and 1 <= i <= len(claims) and i not in claimed]
        if not ids:
            continue
        claimed.update(ids)
        occ = [claims[i - 1]["lines"] for i in ids if claims[i - 1].get("lines")]
        s = g.get("strongest")
        best = claims[s - 1]["lines"] if isinstance(s, int) and s in ids else (occ[0] if occ else [])
        out.append({"claim": g.get("claim") or claims[ids[0]].get("claim", ""),
                    "occurrences": sorted(occ), "strongest": best})
    # 沒被任何 group 認領的一律補回，漏論點比留重複嚴重。
    for i, c in enumerate(claims, 1):
        if i not in claimed:
            out.append({"claim": c.get("claim", ""),
                        "occurrences": [c.get("lines", [])],
                        "strongest": c.get("lines", [])})
    return out


def main() -> None:
    if not KEY:
        sys.exit("ANTHROPIC_API_KEY 未設定")
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    m = json.loads(src.read_text(encoding="utf-8"))
    claims = m.get("claims", [])
    # 續跑時會拿到已經合併過的地圖（claims 已是 occurrences 形態），直接放行，
    # 不然會拿合併結果再合併一次，而且 KeyError。
    if claims and all("occurrences" in c for c in claims):
        if src != dst:
            dst.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  論點已是合併形態（{len(claims)} 組），跳過")
        return
    before = len(claims)
    m["claims"] = dedupe(m.get("claims", []))
    dst.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    dup = sum(1 for c in m["claims"] if len(c["occurrences"]) > 1)
    print(f"  論點 {before} → {len(m['claims'])} 組，其中 {dup} 組重複出現")


if __name__ == "__main__":
    main()
