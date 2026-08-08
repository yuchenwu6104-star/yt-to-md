#!/usr/bin/env python3
"""把兩份獨立跑出的地圖合流，並產出體檢表。

用兩次獨立產出買確定性：兩邊都標到的才算數（論點），只有一邊標到的
當候選（引述）。合流一律靠**行號區間重疊**，不靠文字比對——兩隻各自
用不同措辭描述同一個論點是常態，文字比對會全部漏掉。

不同欄位的合流方向不同，因為錯誤成本不對稱：
  論點  取交集：多列一條假論點會害下游多寫一節，貴
  引述  取聯集：漏標一段好引述就永遠不見了，更貴
  歸屬  取歧異：兩邊不一致的地方正是要人去看的地方
  專名  取聯集：漏列一個待查專名等於放它過關
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _span(v) -> list[int]:
    """把任何形態的行號欄位壓成 [起, 迄]。

    模型會回 `[25]`（單行）、`[25, 25]`、偶爾多於兩個元素，全部收斂，
    否則下游每個比對都要各自防禦。
    """
    nums = [x for x in (v or []) if isinstance(x, int)]
    if not nums:
        return [0, -1]
    return [min(nums), max(nums)]


def normalize_map(m: dict) -> dict:
    for key in ("segments", "turns", "quote_candidates", "skip_spans",
                "hard_to_translate"):
        for e in m.get(key, []) or []:
            e["lines"] = _span(e.get("lines"))
    for c in m.get("claims", []) or []:
        c["strongest"] = _span(c.get("strongest"))
        c["occurrences"] = [_span(o) for o in (c.get("occurrences") or [])] or [c["strongest"]]
    for p in m.get("propers", []) or []:
        p["lines"] = [x for x in (p.get("lines") or []) if isinstance(x, int)]
    return m


def overlap(a: list[int], b: list[int]) -> int:
    """兩個行號區間重疊幾行。"""
    return max(0, min(a[1], b[1]) - max(a[0], b[0]) + 1)


def spans_match(a: list[int], b: list[int], ratio: float = 0.4) -> bool:
    """重疊超過較短那段的 ratio 就算同一件事。"""
    ov = overlap(a, b)
    shorter = min(a[1] - a[0] + 1, b[1] - b[0] + 1)
    return shorter > 0 and ov / shorter >= ratio


# ------------------------------------------------------------------ 論點

def merge_claims(ca: list[dict], cb: list[dict]) -> tuple[list[dict], list[dict]]:
    confirmed, single = [], []
    used_b: set[int] = set()
    for x in ca:
        hit = None
        for j, y in enumerate(cb):
            if j in used_b:
                continue
            if spans_match(x["strongest"], y["strongest"]):
                hit = j
                break
        if hit is None:
            single.append({**x, "來源": "A"})
            continue
        used_b.add(hit)
        y = cb[hit]
        # 重複出現次數兩邊常不一致，取聯集比較安全：漏抓重複會讓
        # 同一件事在文章裡講兩次，那正是上一版被退件的原因。
        occ = _merge_occurrences(x.get("occurrences", []), y.get("occurrences", []))
        confirmed.append(
            {
                "claim": x["claim"],
                "claim_alt": y["claim"],
                "strongest": x["strongest"],
                "occurrences": occ,
                "重複次數分歧": len(x.get("occurrences", [])) != len(y.get("occurrences", [])),
            }
        )
    single += [{**y, "來源": "B"} for j, y in enumerate(cb) if j not in used_b]
    return confirmed, single


def _merge_occurrences(oa: list, ob: list) -> list:
    out = [list(s) for s in oa]
    for s in ob:
        if not any(spans_match(list(s), t) for t in out):
            out.append(list(s))
    return sorted(out)


# ------------------------------------------------------------------ 歸屬

def turn_conflicts(ta: list[dict], tb: list[dict]) -> list[dict]:
    """兩邊對同一段話標了不同說話人 → 一定要人工看。"""
    out = []
    for x in ta:
        for y in tb:
            if spans_match(x["lines"], y["lines"], 0.5) and x["speaker"] != y["speaker"]:
                out.append(
                    {
                        "lines": x["lines"],
                        "A說": x["speaker"],
                        "B說": y["speaker"],
                        "A依據": x.get("evidence", ""),
                        "B依據": y.get("evidence", ""),
                    }
                )
                break
    return out


def low_confidence(turns: list[dict]) -> list[dict]:
    return [t for t in turns if t.get("confidence") == "低"]


def long_turns(turns: list[dict], threshold: int = 30) -> list[dict]:
    """異常長的輪次是「主持人長段被吸進受訪者」的物理特徵。"""
    return [t for t in turns if t["lines"][1] - t["lines"][0] + 1 >= threshold]


# ------------------------------------------------------------ 引述與專名

def union_spans(qa: list[dict], qb: list[dict]) -> list[dict]:
    out = [dict(q, 來源="A") for q in qa]
    for q in qb:
        if not any(spans_match(q["lines"], o["lines"]) for o in out):
            out.append(dict(q, 來源="B"))
        else:
            for o in out:
                if spans_match(q["lines"], o["lines"]):
                    o["來源"] = "A+B"
                    break
    return sorted(out, key=lambda d: d["lines"][0])


def intersect_spans(sa: list[dict], sb: list[dict]) -> list[dict]:
    """略過區段取交集：兩邊都說可略才略。

    聯集是錯方向。過度略過會讓使用者以為這集沒料而跳過整集，那是
    整條流程唯一有實質代價的失誤；多讀幾行只是小麻煩。
    """
    out = []
    for x in sa:
        for y in sb:
            lo, hi = max(x["lines"][0], y["lines"][0]), min(x["lines"][1], y["lines"][1])
            if lo <= hi:
                out.append({"lines": [lo, hi], "kind": x.get("kind", ""), "來源": "A+B"})
                break
    return sorted(out, key=lambda d: d["lines"][0])


def union_propers(pa: list[dict], pb: list[dict]) -> list[dict]:
    by_name: dict[str, dict] = {}
    for p in list(pa) + list(pb):
        key = p["name"].strip()
        cur = by_name.setdefault(key, {"name": key, "lines": [], "flags": set(), "notes": []})
        cur["lines"] = sorted(set(cur["lines"]) | set(p.get("lines", [])))
        if p.get("flag"):
            cur["flags"].add(p["flag"])
        if p.get("note"):
            cur["notes"].append(p["note"])
    out = []
    for v in by_name.values():
        flags = v["flags"]
        # 只要有一邊覺得有問題就當有問題，寧可多查不要放過。
        flag = "不完整" if "不完整" in flags else "拼法可疑" if "拼法可疑" in flags else "完整"
        out.append({"name": v["name"], "lines": v["lines"], "flag": flag,
                    "note": "；".join(dict.fromkeys(v["notes"]))})
    return sorted(out, key=lambda d: (d["flag"] == "完整", d["name"].lower()))


# ------------------------------------------------------------ 量級對帳

def magnitude_suspects(index: dict, window: int = 3) -> list[dict]:
    """同一小段裡，帶 scale 的數字量級差 100 倍以上 → 候選，不是硬擋。

    真實世界有合法的巨大落差（槓桿、佔比），所以只報不擋。
    """
    nums = [n for n in index.get("numbers", []) if n.get("scale")]
    out = []
    for i, a in enumerate(nums):
        for b in nums[i + 1 :]:
            if b["line"] - a["line"] > window:
                break
            if a["value"] <= 0 or b["value"] <= 0:
                continue
            ratio = max(a["value"], b["value"]) / min(a["value"], b["value"])
            if ratio >= 100:
                out.append({"lines": [a["line"], b["line"]], "a": a["raw"],
                            "b": b["raw"], "倍數": round(ratio)})
    return out


# ---------------------------------------------------------------- 體檢表

def health(merged: dict, index: dict, line_count: int) -> str:
    c = merged["claims_confirmed"]
    dup = [x for x in c if len(x["occurrences"]) > 1]
    propers = merged["propers"]
    bad = [p for p in propers if p["flag"] != "完整"]
    skip = sum(s["lines"][1] - s["lines"][0] + 1 for s in merged["skip_spans"])
    return "\n".join(
        [
            f"全長 {line_count} 行｜可略過 {skip} 行（{skip*100//max(1,line_count)}%）",
            f"論點 {len(c)} 條（兩邊一致），其中 {len(dup)} 條在訪談中重複出現",
            f"單邊論點 {len(merged['claims_single'])} 條（僅一邊標到，可靠度低）",
            f"引述候選 {len(merged['quote_candidates'])} 段"
            f"（兩邊都標 {sum(1 for q in merged['quote_candidates'] if q['來源']=='A+B')} 段）",
            f"專名 {len(propers)} 個：不完整 {sum(1 for p in bad if p['flag']=='不完整')}、"
            f"拼法可疑 {sum(1 for p in bad if p['flag']=='拼法可疑')}",
            f"歸屬歧異 {len(merged['turn_conflicts'])} 處、低信心 {len(merged['turns_low_confidence'])} 處、"
            f"超長輪次 {len(merged['turns_long'])} 處",
            f"數字 {len(index.get('numbers', []))} 筆，量級疑點 {len(merged['magnitude_suspects'])} 處",
            f"難譯標記 {len(merged['hard_to_translate'])} 處",
        ]
    )


def main() -> None:
    if len(sys.argv) < 5:
        sys.exit("用法：merge_maps.py map_A.json map_B.json index.json 輸出.json")
    a = normalize_map(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    b = normalize_map(json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")))
    index = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))

    confirmed, single = merge_claims(a.get("claims", []), b.get("claims", []))
    merged = {
        "segments": a.get("segments", []),
        "segments_alt": b.get("segments", []),
        "claims_confirmed": confirmed,
        "claims_single": single,
        "quote_candidates": union_spans(a.get("quote_candidates", []), b.get("quote_candidates", [])),
        "skip_spans": intersect_spans(a.get("skip_spans", []), b.get("skip_spans", [])),
        "propers": union_propers(a.get("propers", []), b.get("propers", [])),
        "turn_conflicts": turn_conflicts(a.get("turns", []), b.get("turns", [])),
        "turns_low_confidence": low_confidence(a.get("turns", [])) + low_confidence(b.get("turns", [])),
        "turns_long": long_turns(a.get("turns", [])),
        "magnitude_suspects": magnitude_suspects(index),
        "hard_to_translate": union_spans(a.get("hard_to_translate", []), b.get("hard_to_translate", [])),
    }
    table = health(merged, index, index.get("line_count", 0))
    merged["health"] = table
    Path(sys.argv[4]).write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    print(table)


if __name__ == "__main__":
    main()
