#!/usr/bin/env python3
"""命題認領檢查：plan (c) 的每一條命題，成文裡有沒有人認領。

為什麼需要這支：2026-09-21 政策改版後，成文不再是「照訪談順序的引述串」，
而是重新編排過的說明文。重排一旦開始，漏掉某條主張就不再看得出來 ——
錨點只證明「這段有依據」，不證明「那條主張還活著」。

所以 plan (c) 從「主張與反證清單」升級成**不可遺失清單**：每條編號，
draft 的錨點寫成 `[L81-84 #7]`，本腳本比對兩邊。

    check_claims.py <base>_draft.md <base>_plan.md

exit 1：有命題完全沒被認領（硬性，退回寫作員）
exit 0：全部認領（不代表寫對，只代表沒整條蒸發）
"""
import io
import re
import sys

# plan (c) 的命題行：以 #<數字> 開頭的表格列或清單列都認
CLAIM_RE = re.compile(r"^\s*(?:[-*|]\s*)?#(\d+)\b[^\n]*", re.M)
SECTION_C_RE = re.compile(r"^#+\s*\(?c\)?[^\n]*$", re.M | re.I)
ANCHOR_CLAIM_RE = re.compile(r"\[L\d+(?:\s*[-–~]\s*L?\d+)?\s*#(\d+(?:\s*,\s*#?\d+)*)\]")


def plan_claims(plan_text):
    """只掃 (c) 小節，避免把 (d) 的編號當成命題。"""
    m = SECTION_C_RE.search(plan_text)
    seg = plan_text[m.end():] if m else plan_text
    nxt = re.search(r"^#+\s*\(?d\)?[^\n]*$", seg, re.M | re.I)
    if nxt:
        seg = seg[:nxt.start()]
    out = {}
    for m in CLAIM_RE.finditer(seg):
        n = int(m.group(1))
        out.setdefault(n, m.group(0).strip()[:70])
    return out


def draft_claims(draft_text):
    got = set()
    for m in ANCHOR_CLAIM_RE.finditer(draft_text):
        for part in m.group(1).split(","):
            got.add(int(part.strip().lstrip("#")))
    return got


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    draft = io.open(sys.argv[1], encoding="utf-8").read()
    plan = io.open(sys.argv[2], encoding="utf-8").read()

    claims = plan_claims(plan)
    if not claims:
        print("[硬性] plan (c) 找不到編號命題（格式應為 `#7 | 命題 | …`）；"
              "重排政策下沒有編號就無法機械確認有沒有漏掉主張")
        return 1

    got = draft_claims(draft)
    missing = sorted(set(claims) - got)
    stray = sorted(got - set(claims))

    print(f"[A] plan (c) 命題 {len(claims)} 條｜draft 認領 {len(got & set(claims))} 條")
    for n in stray:
        print(f"    [候選] draft 認領了 plan 沒有的 #{n}（編號打錯，或 plan 漏登）")
    if missing:
        print(f"[B] 未被認領的命題 {len(missing)} 條（硬性）：")
        for n in missing:
            print(f"    #{n}｜{claims[n]}")
        print("== 重排時整條蒸發是這條政策最大的風險，退回補寫或在 audit 第 3 節寫明捨棄理由 ==")
        return 1
    print("== plan (c) 全數認領。認領不等於寫對，限定與歸屬仍由盲審逐條驗 ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
