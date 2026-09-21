#!/usr/bin/env python3
"""把草稿的行號錨點剝掉，產生交付用的 _humanized.md。

錨點只服務稽核（audit_worklist.py），不進成品。剝除是機械步驟，由 root 執行，
不派 agent，也不需要讀正文。

用法：
    strip_anchors.py <base>_draft.md            # 寫成同 base 的 _humanized.md
    strip_anchors.py <draft.md> -o <out.md>
    strip_anchors.py <draft.md> --check         # 只檢查殘留，不寫檔

會一併處理錨點拿掉後留下的多餘空白：句末的「 。」、行尾空白、
以及錨點獨佔一行時留下的空行。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ANCHOR_RE = re.compile(r"\s*\[L\d+(?:\s*[-–~]\s*L?\d+)?(?:\s*#\d+(?:\s*,\s*#?\d+)*)?\]")


_CJK = r"\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff01-\uff65"
_HALF_TO_FULL = {",": "，", ";": "；", ":": "：", "?": "？", "!": "！"}
_HALF_NEXT_CJK = re.compile(rf"([,;:?!])(?=[{_CJK}])")
_HALF_PREV_CJK = re.compile(rf"(?<=[{_CJK}])([,;:?!])")
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
_FENCE_RE = re.compile(r"^\s*(?:```|~~~)")


def _widen_line(line: str) -> str:
    """半形標點只有在緊鄰中文時才轉全形。

    使用者明確要求中文行不得出現半形標點，但參考檔自己是半形，模型會照抄
    （2026 多批實測）。只看前後一個字元是不是 CJK，所以 frontmatter 的
    `type: yt_article`、URL 的 `https:`、英文句子裡的逗號都不會被動到。
    """
    def repl(m):
        return _HALF_TO_FULL[m.group(1)]
    # 行內 code 原樣保留，其餘才轉。
    parts, last = [], 0
    for m in _INLINE_CODE_RE.finditer(line):
        seg = line[last:m.start()]
        parts.append(_HALF_NEXT_CJK.sub(repl, _HALF_PREV_CJK.sub(repl, seg)))
        parts.append(m.group(0))
        last = m.end()
    seg = line[last:]
    parts.append(_HALF_NEXT_CJK.sub(repl, _HALF_PREV_CJK.sub(repl, seg)))
    return "".join(parts)


def widen_punct(text: str) -> str:
    lines = text.split("\n")
    out, in_fence = [], False
    # frontmatter 整塊跳過：欄位值可能是英文標題，不該被動到。
    fm_end = -1
    if lines and lines[0].strip() == "---":
        for i, l in enumerate(lines[1:], 1):
            if l.strip() == "---":
                fm_end = i
                break
    for i, line in enumerate(lines):
        if i <= fm_end:
            out.append(line)
            continue
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        out.append(line if in_fence else _widen_line(line))
    return "\n".join(out)


def strip(text: str) -> str:
    out = ANCHOR_RE.sub("", text)
    out = widen_punct(out)
    out = re.sub(r"[ \t]+([。，、；：？！」）])", r"\1", out)
    out = re.sub(r"[ \t]+$", "", out, flags=re.MULTILINE)
    out = re.sub(r"\n{4,}", "\n\n\n", out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("draft")
    ap.add_argument("-o", "--out")
    ap.add_argument("--check", action="store_true",
                    help="只回報錨點數量，不寫檔")
    args = ap.parse_args()

    src = Path(args.draft)
    if not src.exists():
        print(f"找不到檔案：{src}", file=sys.stderr)
        return 2

    text = src.read_text(encoding="utf-8")
    n = len(ANCHOR_RE.findall(text))

    if args.check:
        print(f"{src.name}：錨點 {n} 個")
        return 0

    if args.out:
        dest = Path(args.out)
    elif src.name.endswith("_draft.md"):
        dest = src.with_name(src.name[: -len("_draft.md")] + "_humanized.md")
    else:
        print("檔名不是 _draft.md，請用 -o 指定輸出路徑。", file=sys.stderr)
        return 2

    if n == 0:
        print(f"警告：{src.name} 裡沒有任何錨點，草稿可能沒照契約寫。", file=sys.stderr)

    dest.write_text(strip(text), encoding="utf-8")
    print(f"剝除 {n} 個錨點 → {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
