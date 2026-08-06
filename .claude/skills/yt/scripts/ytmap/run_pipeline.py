#!/usr/bin/env python3
"""地圖版 /yt：英文字幕 → 分流稿 ＋ 地圖 ＋ 帶行號逐字稿。

跟舊版 /yt 的差別是**不再由模型寫文章**。舊版一次要模型同時做翻譯、結構、
歸屬、專名、文筆五件事，於是專名就用記憶填了——同一集跑兩次，三整段虛構
全部出現在「寫文章」那一步。這一版把模型的工作縮成三件互不重疊的：

  Python   數字、拼字變體、廣告、繁簡（確定性，不會幻覺）
  MiniMax  分段、輪次、論點、引述候選、可疑專名（苦力，跑兩次取交集）
  使用者   讀分流稿決定要不要進 humanizer
  humanizer 讀英文字幕＋地圖寫文章（中文只出現一次，出自最會寫中文的那層）

產出三個檔給下游：
  <base>_分流稿.md      給人讀，frontmatter 指向另外兩個檔
  <base>_map.json       給 humanizer，查證資訊全在這
  <base>_lines.txt      帶行號的英文逐字稿，行號是全流程的錨點

用法：run_pipeline.py <_transcript.txt> <輸出目錄> [節目脈絡說明]
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(script: str, *args: str, produces: "Path | None" = None) -> None:
    """produces 已存在就跳過。

    地圖與分流稿是整條線最貴的兩步（一集長談的 API 呼叫以十分鐘計），
    中途壞掉重跑一次代價太高，所以做成可續跑。要重做就刪掉工作目錄。
    """
    if produces is not None and produces.exists() and produces.stat().st_size > 0:
        print(f"      （沿用既有 {produces.name}）")
        return
    cmd = [sys.executable, str(HERE / script), *args]
    p = subprocess.run(cmd, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise SystemExit(f"{script} 失敗（exit {p.returncode}）")


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    src = Path(sys.argv[1])
    outdir = Path(sys.argv[2])
    context = sys.argv[3] if len(sys.argv) > 3 else ""
    if not src.exists():
        sys.exit(f"找不到字幕檔：{src}")
    outdir.mkdir(parents=True, exist_ok=True)

    base = re.sub(r"_transcript$", "", src.stem)
    work = outdir / f".{base}_work"
    work.mkdir(exist_ok=True)

    lines_txt = work / "lines.txt"
    numbered = work / "lines_numbered.txt"

    print("[1/6] 正規化逐字稿")
    run("normalize_transcript.py", str(src), str(lines_txt), produces=numbered)

    print("[2/6] 確定性索引")
    run("build_index.py", str(lines_txt), str(work / "index.json"),
        produces=work / "index.json")

    # 兩次獨立跑：模型的錯是隨機的，規則管不了隨機性，便宜的重複可以。
    for tag in ("A", "B"):
        print(f"[3/6] 地圖 {tag}")
        run("map_minimax.py", str(numbered), str(work / f"map_{tag}.json"), context, tag,
            produces=work / f"map_{tag}.json")
        run("dedupe_claims.py", str(work / f"map_{tag}.json"),
            str(work / f"map_{tag}.json"), produces=work / f"map_{tag}.done")
        (work / f"map_{tag}.done").write_text("ok", encoding="utf-8")

    print("[4/6] 合流")
    merged = work / "map_merged.json"
    run("merge_maps.py", str(work / "map_A.json"), str(work / "map_B.json"),
        str(work / "index.json"), str(merged), produces=merged)

    print("[5/6] 分流稿")
    raw_triage = work / "triage_raw.md"
    run("triage_minimax.py", str(numbered), str(merged), str(raw_triage), context,
        produces=raw_triage)

    print("[6/6] 抽出查證標記、落檔")
    clean = work / "triage_clean.md"
    notes = work / "triage_notes.json"
    run("strip_markers.py", str(raw_triage), str(clean), str(notes), produces=clean)

    m = json.loads(merged.read_text(encoding="utf-8"))
    m["triage_notes"] = json.loads(notes.read_text(encoding="utf-8"))
    (outdir / f"{base}_map.json").write_text(
        json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    (outdir / f"{base}_lines.txt").write_text(
        numbered.read_text(encoding="utf-8"), encoding="utf-8")

    front = (
        "---\n"
        "type: yt_triage\n"
        f"map: {base}_map.json\n"
        f"transcript_lines: {base}_lines.txt\n"
        "note: 分流稿。用途是判斷這集要不要進 humanizer。查證資訊全在 map JSON，不在正文。\n"
        "---\n\n"
    )
    (outdir / f"{base}_分流稿.md").write_text(
        front + clean.read_text(encoding="utf-8"), encoding="utf-8")

    print(f"\n完成：{base}")
    print(f"  {base}_分流稿.md")
    print(f"  {base}_map.json")
    print(f"  {base}_lines.txt")
    print(m.get("health", ""))


if __name__ == "__main__":
    main()
