#!/usr/bin/env python3
"""從帶行號錨點的草稿產生稽核待查清單。

用途：把「漏段」與「段落尾巴被切斷」這兩種佔絕大多數的缺陷，從人肉通讀
改成機械偵測。稽核員不必再從頭讀完整份逐字稿，只看本腳本標出來的點。

前提是關 1 寫作員在 <base>_draft.md 裡逐段掛了錨點：
    「引述原話」[L212-218]
    編輯者敘述段落。[L200-211]

用法：
    audit_worklist.py <draft.md> <lines.txt> [--min-gap N] [--max-span N]

輸出四區：
    [A] 錨點體檢       錨點數、認領率、超寬錨點、無效範圍
    [B] 未認領區間     連續 N 行以上沒有任何錨點認領 → 疑似漏段
    [C] 疑似尾巴被切斷 錨點結束後緊接轉折／限定句，且那幾行沒被認領
    [D] 疑似壓縮過度   引述的中文字數相對來源英文字數過少

exit 1 = 錨點本身不可信（沒有錨點／認領率過低／有無效範圍），稽核無法進行。
exit 0 = 錨點可信，清單已印出；[B][C][D] 是待查項不是判定，逐項三分類。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ANCHOR_RE = re.compile(r"\[L(\d+)(?:\s*[-–~]\s*L?(\d+))?(?:\s*#\d+(?:\s*,\s*#?\d+)*)?\]")
FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
QUOTE_RE = re.compile(r"「([^」]*)」")
CJK_RE = re.compile(r"[一-鿿]")
EN_WORD_RE = re.compile(r"[A-Za-z]+")

# 講者講完主論點後，下一句常以這些開頭：自我限定、反向條件、收束。
# 這正是最常被切掉的東西，所以只要它落在未認領行上就值得回頭看一眼。
TAIL_MARKERS_EN = (
    "but ", "but,", "although", "though", "however", "that said", "having said that",
    "at least", "the good news", "the bad news", "on the other hand", "unless",
    "to be fair", "in fairness", "admittedly", "granted", "mind you", "then again",
    "that's not to say", "thats not to say", "it's not that", "its not that",
    "i'm not saying", "im not saying", "i should say", "i should add", "i would add",
    "the caveat", "my caveat", "the catch", "the problem is", "the flip side",
    "the other side", "in practice", "in reality", "and the reason", "the reason is",
    "so the good", "of course", "now, the", "and yet", "and still", "except",
)
TAIL_MARKERS_CJK = (
    "但", "不過", "可是", "只是", "話雖", "雖然", "然而", "當然",
    "でも", "ただ", "しかし", "とはいえ", "もっとも",
    "하지만", "다만", "그런데", "물론",
)


def load_lines(path: Path) -> dict:
    """<行號> -> <該行文字>，沿用 final_gate 的解析慣例。"""
    out = {}
    for physical, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        m = re.match(r"^\s*(?:L)?(\d+)\s{1,2}(.*)$", raw)
        if m:
            out[int(m.group(1))] = m.group(2)
        else:
            out[physical] = raw
    return out


def body_of(draft: str) -> str:
    return FRONTMATTER_RE.sub("", draft, count=1)


def parse_units(body: str) -> list:
    """切成 (單元文字, 起行, 迄行, 錨點原文) 清單。

    單元文字＝上一個錨點結束到這個錨點開始之間的字，也就是這個錨點在認領的內容。
    """
    units = []
    cursor = 0
    for m in ANCHOR_RE.finditer(body):
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else start
        units.append({
            "text": body[cursor:m.start()],
            "start": start,
            "end": end,
            "raw": m.group(0),
        })
        cursor = m.end()
    return units


def cjk_len(text: str) -> int:
    return len(CJK_RE.findall(text))


def spans_to_ranges(claimed: set) -> list:
    """把認領到的行號集合壓成連續區間。"""
    out = []
    for n in sorted(claimed):
        if out and n == out[-1][1] + 1:
            out[-1][1] = n
        else:
            out.append([n, n])
    return [tuple(r) for r in out]


def gaps(claimed: set, total: int) -> list:
    missing = [n for n in range(1, total + 1) if n not in claimed]
    return spans_to_ranges(set(missing))


def starts_with_marker(text: str) -> "str | None":
    low = text.strip().lower()
    for mk in TAIL_MARKERS_EN:
        if low.startswith(mk):
            return mk.strip()
    stripped = text.strip()
    for mk in TAIL_MARKERS_CJK:
        if stripped.startswith(mk):
            return mk
    return None


def _verdict(invalid, wide, rate, unclaimed_gaps, tail_hits, ratio_hits) -> int:
    hard = []
    if invalid:
        hard.append(f"無效範圍 {len(invalid)} 個")
    if wide:
        hard.append(f"超寬錨點 {len(wide)} 個")
    if rate < 0.5:
        hard.append(f"認領率僅 {rate:.0%}")
    if hard:
        print("== 錨點不可信：" + "、".join(hard) + "，退回關 1 補錨點 ==")
        return 1
    print(f"== 錨點可信。待查 {len(unclaimed_gaps)} 處未認領、{tail_hits} 處疑似斷尾、"
          f"{ratio_hits} 處疑似壓縮，逐項三分類 ==")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("draft")
    ap.add_argument("lines")
    ap.add_argument("--min-gap", type=int, default=4,
                    help="未認領連續行數達幾行才報（預設 4）")
    ap.add_argument("--max-span", type=int, default=30,
                    help="單一錨點涵蓋幾行以上算超寬（預設 30）")
    ap.add_argument("--lookahead", type=int, default=3,
                    help="錨點結束後往下看幾行找轉折句（預設 3）")
    ap.add_argument("--min-ratio", type=float, default=0.55,
                    help="引述中文字數 ÷ 來源英文字數，低於此值報疑似壓縮（預設 0.55）")
    args = ap.parse_args()

    draft_path, lines_path = Path(args.draft), Path(args.lines)
    for p in (draft_path, lines_path):
        if not p.exists():
            print(f"找不到檔案：{p}", file=sys.stderr)
            return 2

    line_map = load_lines(lines_path)
    total = max(line_map) if line_map else 0

    # 來源體質決定哪幾區偵測得動。這裡算出來是為了在不適用時明說「沒得查」，
    # 而不是印「無」——印「無」會被讀成「查過沒問題」，那是假保證。
    src_text = "\n".join(line_map.values())
    src_cjk = len(CJK_RE.findall(src_text))
    src_en = len(EN_WORD_RE.findall(src_text))
    cjk_source = src_cjk > src_en
    avg_chars = len(src_text) / total if total else 0
    coarse = avg_chars > 120
    if coarse:
        args.min_gap = min(args.min_gap, 1)
    body = body_of(draft_path.read_text(encoding="utf-8"))
    units = parse_units(body)

    if not units:
        print("[A] 錨點體檢：草稿裡找不到任何 [L###] 錨點。", file=sys.stderr)
        print("    稽核無法進行。關 1 寫作員必須逐段掛錨點後才能交件。", file=sys.stderr)
        return 1

    invalid, wide, claimed = [], [], set()
    for u in units:
        if u["end"] < u["start"] or u["start"] < 1 or u["end"] > total:
            invalid.append(u)
            continue
        span = u["end"] - u["start"] + 1
        if span > args.max_span:
            wide.append((u, span))
        claimed.update(range(u["start"], u["end"] + 1))

    rate = len(claimed) / total if total else 0.0

    print(f"[A] 錨點體檢")
    print(f"    逐字稿 {total} 行｜錨點 {len(units)} 個｜認領 {len(claimed)} 行"
          f"（{rate:.0%}）")
    print(f"    來源體質：{'中文' if cjk_source else '英文／其他'}"
          f"｜平均每行 {avg_chars:.0f} 字元{'（長行，行號解析度低）' if coarse else ''}")
    if coarse:
        print(f"    ⚠ 長行來源：一行就是一段，錨點對不到句子邊界。認領率會虛高，"
              f"[B] 門檻已自動降到 1 行，[C] 可信度低。**覆蓋要靠逐行比對，不能只信這張表。**")
    if invalid:
        print(f"    無效範圍 {len(invalid)} 個：" +
              "、".join(u["raw"] for u in invalid[:8]))
    if wide:
        print(f"    超寬錨點 {len(wide)} 個（單一錨點涵蓋 >{args.max_span} 行，"
              f"等於沒有真的逐段認領）：")
        for u, span in wide[:8]:
            print(f"      {u['raw']}（{span} 行）")

    unclaimed_gaps = [g for g in gaps(claimed, total) if g[1] - g[0] + 1 >= args.min_gap]
    print()
    print(f"[B] 未認領區間（連續 ≥{args.min_gap} 行）：{len(unclaimed_gaps)} 處")
    for a, b in unclaimed_gaps:
        head = (line_map.get(a, "") or "").strip()[:60]
        print(f"    L{a}-L{b}（{b - a + 1} 行）｜{head}")
    if not unclaimed_gaps:
        print("    無")

    print()
    print(f"[C] 疑似尾巴被切斷（錨點結束後緊接轉折／限定句，且那行沒被認領）")
    tail_hits = 0
    for u in units:
        if u in invalid:
            continue
        for offset in range(1, args.lookahead + 1):
            nxt = u["end"] + offset
            if nxt > total or nxt in claimed:
                continue
            text = line_map.get(nxt, "")
            mk = starts_with_marker(text)
            if mk:
                tail_hits += 1
                print(f"    {u['raw']} 之後 L{nxt}「{mk}」｜{text.strip()[:70]}")
                break
    if not tail_hits:
        print("    無命中" + ("（長行來源，本區偵測力低，不代表沒有斷尾）"
                             if coarse else ""))

    print()
    print(f"[D] 疑似壓縮過度的引述（引述中文字數 ÷ 來源英文字數 < {args.min_ratio}）")
    if cjk_source:
        print("    不適用：本集是中文來源，中英字數比法量不出壓縮，本區未檢查。")
        print("    引述有沒有掉半截，只能靠盲審逐行比對。")
        ratio_hits = 0
        print()
        return _verdict(invalid, wide, rate, unclaimed_gaps, tail_hits, ratio_hits)
    ratio_hits = 0
    for u in units:
        if u in invalid:
            continue
        quoted = "".join(QUOTE_RE.findall(u["text"]))
        if not quoted:
            continue
        zh = cjk_len(quoted)
        # 敘述為主、只夾一小句引述的單元不算「引述被壓縮」，那是正常的串接段。
        if zh < 0.6 * cjk_len(u["text"]):
            continue
        en = sum(len(EN_WORD_RE.findall(line_map.get(n, "")))
                 for n in range(u["start"], u["end"] + 1))
        if en < 12:
            continue
        ratio = zh / en if en else 0
        if ratio < args.min_ratio:
            ratio_hits += 1
            print(f"    {u['raw']}｜中文 {zh} 字 ÷ 英文 {en} 字 = {ratio:.2f}"
                  f"｜{quoted.strip()[:40]}")
    if not ratio_hits:
        print("    無")

    print()
    return _verdict(invalid, wide, rate, unclaimed_gaps, tail_hits, ratio_hits)


if __name__ == "__main__":
    sys.exit(main())
