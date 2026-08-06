#!/usr/bin/env python3
"""把單行的英文字幕切成一句一行，行號成為穩定錨點。

/yt 目前產出的 _transcript.txt 是一整行（Mike Kelly 那集 73KB 零換行），
所有「行號區間」的設計都無從談起。這一步必須在最前面，而且必須是
確定性的：同一份輸入永遠切出同樣的行號，否則地圖與文章對不上。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# 縮寫後面的句點不是句尾，切在這裡會讓行號漂移。
ABBREV = r"(?<!\bMr)(?<!\bMrs)(?<!\bMs)(?<!\bDr)(?<!\bSt)(?<!\bJr)(?<!\bSr)(?<!\bvs)(?<!\bU\.S)(?<!\bInc)(?<!\bCo)(?<!\bLtd)(?<!\betc)(?<!\bi\.e)(?<!\be\.g)"
SPLIT_RE = re.compile(ABBREV + r"(?<=[.!?])\s+(?=[A-Z\"'“])")


MAX_LEN = 200


def _wrap(s: str) -> list[str]:
    """句點稀少的生字幕會切出幾百字元的長行，行號就失去定位能力。

    在逗號或空白處硬切，切點不必語意正確，只要確定性即可。
    """
    out = []
    while len(s) > MAX_LEN:
        cut = s.rfind(", ", 0, MAX_LEN)
        if cut < MAX_LEN // 2:
            cut = s.rfind(" ", 0, MAX_LEN)
        if cut <= 0:
            cut = MAX_LEN
        out.append(s[: cut + 1].strip())
        s = s[cut + 1 :].strip()
    if s:
        out.append(s)
    return out


def normalize(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    # 生自動字幕用 >> 標換手，這是確定性訊號，比模型判斷可靠得多，
    # 一定要保留成行首標記給下游用。已清理過的稿子沒有這個標記。
    chunks = re.split(r"\s*>>\s*", text)
    lines = []
    for k, chunk in enumerate(chunks):
        for j, sent in enumerate(SPLIT_RE.split(chunk)):
            sent = sent.strip()
            if not sent:
                continue
            if k > 0 and j == 0:
                sent = ">> " + sent
            lines.extend(_wrap(sent))
    return lines


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("用法：normalize_transcript.py <_transcript.txt> [輸出]")
    src = Path(sys.argv[1])
    lines = normalize(src.read_text(encoding="utf-8", errors="replace"))
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_name(
        src.stem + "_lines.txt"
    )
    # 寫兩份：純文字給下游程式吃，帶行號給模型讀（模型自己數行會數錯）。
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    numbered = out.with_name(out.stem + "_numbered.txt")
    numbered.write_text(
        "\n".join(f"{i:>5}  {l}" for i, l in enumerate(lines, 1)) + "\n",
        encoding="utf-8",
    )
    print(f"已寫入 {out}（{len(lines)} 行）")
    print(f"已寫入 {numbered}")
    lengths = sorted(len(l) for l in lines)
    print(f"  行長中位數 {lengths[len(lengths)//2]} 字元，最長 {lengths[-1]}")


if __name__ == "__main__":
    main()
