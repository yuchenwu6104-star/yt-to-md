#!/usr/bin/env python3
"""把分流稿裡的查證標記抽出來搬進 JSON，正文只留「說了什麼」。

使用者讀分流稿只為了判斷這集要不要深做，查證標記對這個判斷零貢獻，
是雜訊。但標記本身是 humanizer 的關鍵輸入，不能丟，只能搬家。

抽取是子句層級不是括號層級：`（variant perception，他說這詞是 X 帶紅的，
字幕拼法可疑，應為 Y）` 裡前兩句是內容、後兩句是查證，整個括號砍掉會
連英文術語一起賠進去。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# 命中任一詞就判定這個子句在談查證，不是在談內容。
VERIFY_HINT = re.compile(
    r"字幕|拼法|未查證|查證|存疑|判讀|量級|語意不明|缺姓氏|"
    r"缺完整|缺公司|疑為|疑似|應為|誤聽|聽寫|行作|行才出現|行只有|不代為"
)
# 模型會混用全形與半形括號、全形與半形逗號，兩種都要吃，
# 只認一種等於漏抽一半的標記。
PAREN_RE = re.compile(r"[（(]([^（）()]*)[）)]")
CLAUSE_SEP = re.compile(r"[，；,;]")


def process_paren(inner: str) -> tuple[str | None, str | None]:
    """回傳（保留下來的括號內容, 抽走的查證文字）。"""
    clauses = [c for c in CLAUSE_SEP.split(inner) if c.strip()]
    keep = [c for c in clauses if not VERIFY_HINT.search(c)]
    drop = [c for c in clauses if VERIFY_HINT.search(c)]
    if not drop:
        return inner, None
    return ("，".join(keep) if keep else None), "，".join(drop)


def main() -> None:
    if len(sys.argv) < 4:
        sys.exit("用法：strip_markers.py 分流稿.md 輸出.md 輸出_notes.json")
    src, out_md, out_json = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])

    notes: list[dict] = []
    section = ""
    out_lines: list[str] = []

    for line in src.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            out_lines.append(line)
            continue

        def repl(m: re.Match) -> str:
            keep, dropped = process_paren(m.group(1))
            if dropped:
                notes.append({"section": section, "note": dropped})
            return f"（{keep}）" if keep else ""

        out_lines.append(PAREN_RE.sub(repl, line))

    text = "\n".join(out_lines)
    # 抽掉整個括號後常留下「字」「，」貼在一起或連續空白，收乾淨。
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"，，+", "，", text)
    text = re.sub(r"，(。|、)", r"\1", text)

    out_md.write_text(text + "\n", encoding="utf-8")
    out_json.write_text(json.dumps(notes, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"正文 {len(text)} 字元（原 {len(src.read_text(encoding='utf-8'))}）")
    print(f"抽出查證註記 {len(notes)} 條")


if __name__ == "__main__":
    main()
