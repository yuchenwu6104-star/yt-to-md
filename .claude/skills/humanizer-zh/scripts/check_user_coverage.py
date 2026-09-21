#!/usr/bin/env python3
"""
SLK 個人覆蓋率檢查(搭配 final_gate.py 使用)。

final_gate.py 的 [候選] 覆蓋率偏低只標不擋。這支腳本把覆蓋率升為 [硬性],
達不到就 exit 1 阻擋上傳/HackMD 流程。

判斷基準:
- 中文字數下限:跟影片時長成正比(唯一的 [硬性] 條件)
- segments 數只印出來參考,不擋(2026-08-15 移除:小節數度量的是分段習慣不是覆蓋,
  且與 SKILL.md「小標少而短」互相打架)

執行:
  .venv/bin/python scripts/check_user_coverage.py <humanized.md> [transcript.txt] [map.json]

退出碼:
  0 = 通過
  1 = [硬性] 不過,列出缺的條件
  2 = 缺來源,不能跑
"""

import sys
import re
import json
from pathlib import Path


def count_cjk(text: str) -> int:
    """計算 CJK 字元數(不含英文/數字/標點)。"""
    return sum(1 for c in text if '\u4e00' <= c <= '\u9fff')


def estimate_duration_from_transcript(path: Path) -> float:
    """從 transcript 推算影片分鐘數(粗估:每 75 英文字 = 1 秒,3.5 字/秒)。"""
    if not path.exists():
        return 0.0
    text = path.read_text(encoding='utf-8')
    # 算英文字數(空格分隔的 token)
    en_words = len(re.findall(r'[A-Za-z]+', text))
    # 英文 podcast 約 150 words/min,這裡保守一點用 130
    minutes = en_words / 130.0
    return minutes


def required_cjk_chars(duration_min: float) -> int:
    """對應影片時長的最低 CJK 字數。

    標準:
    - 30 分鐘以下:3,000 字
    - 30-60 分鐘:4,500 字
    - 60-90 分鐘:6,500 字
    - 90-120 分鐘:7,500 字
    - 120-180 分鐘:9,000 字
    - 180 分鐘以上:10,500 字

    1.5-2 小時 podcast 落在 7,500-9,000 區間。
    """
    if duration_min < 30:
        return 3000
    if duration_min < 60:
        return 4500
    if duration_min < 90:
        return 6500
    if duration_min < 120:
        return 7500
    if duration_min < 180:
        return 9000
    return 10500


def count_sections(humanized_path: Path) -> int:
    """計算 humanized 檔的 `## ` 小節數。"""
    text = humanized_path.read_text(encoding='utf-8')
    # 排除 frontmatter
    if text.startswith('---'):
        end = text.find('\n---\n', 4)
        if end != -1:
            text = text[end + 5:]
    return len(re.findall(r'^## ', text, re.MULTILINE))


def count_segments_from_map(map_path: Path) -> int:
    """從 map.json 取 segments 數量。"""
    if not map_path.exists():
        return 0
    data = json.loads(map_path.read_text(encoding='utf-8'))
    if isinstance(data, dict) and 'segments' in data:
        return len(data['segments'])
    return 0


def main():
    if len(sys.argv) < 2:
        print("用法: check_user_coverage.py <humanized.md> [transcript.txt] [map.json]", file=sys.stderr)
        sys.exit(2)

    humanized = Path(sys.argv[1])
    if not humanized.exists():
        print(f"[硬性] 找不到 humanized 檔: {humanized}", file=sys.stderr)
        sys.exit(2)

    transcript = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    map_json = Path(sys.argv[3]) if len(sys.argv) > 3 else None

    # 自動找同目錄的 transcript / map
    base = humanized.parent
    # 從 humanized 檔名推算 base(去掉 _humanized.md)
    stem = humanized.stem.replace('_humanized', '')
    if transcript is None:
        for cand in [f'{stem}_transcript.txt', f'{stem}_transcript_full.txt', '_transcript.txt']:
            p = base / cand
            if p.exists():
                transcript = p
                break
    if map_json is None:
        for cand in [f'{stem}_map.json', f'{stem}_分流稿.md']:
            p = base / cand
            if p.exists():
                map_json = p
                break

    text = humanized.read_text(encoding='utf-8')
    # 跳過 frontmatter
    if text.startswith('---'):
        end = text.find('\n---\n', 4)
        if end != -1:
            text = text[end + 5:]

    cjk = count_cjk(text)
    sections = count_sections(humanized)

    # 估時長
    if transcript and transcript.exists():
        duration = estimate_duration_from_transcript(transcript)
    else:
        # 沒有 transcript 就用最保守的 60 分鐘標準
        duration = 60.0

    required = required_cjk_chars(duration)

    # 算 segments 對應率
    if map_json and map_json.exists() and map_json.suffix == '.json':
        segs = count_segments_from_map(map_json)
    else:
        segs = 0

    failures = []

    if cjk < required:
        failures.append(
            f"[硬性] CJK 字數不足: {cjk} < 最低 {required} "
            f"(對應約 {duration:.0f} 分鐘影片;humanized 應該寫到至少 {required} 中文字)"
        )

    # 2026-08-15 拿掉「小節數 / segments ≥ 30%」那條硬性。理由:小節數根本不度量覆蓋,
    # 它只度量分段習慣,而且跟 SKILL.md 的「小標少而短,沒有合適小標就不要硬給」直接打架。
    # 實測:66 segments 的集數寫成 18 個小標(文體上正確)就被判硬性,只能回頭拆標題湊數,
    # 正文一個字都沒變卻多花一輪。覆蓋改由關 3 盲審的「逐字稿→文章」方向對帳把關。
    if segs > 0:
        print(f"參考: {sections} 小節 / {segs} segments(僅供參考,不作為通過條件)")

    if failures:
        print(f"\n=== SLK 覆蓋率檢查不通過(共 {len(failures)} 項) ===\n", file=sys.stderr)
        for f in failures:
            print(f, file=sys.stderr)
        print(f"\n當前 CJK: {cjk} | 小節數: {sections} | 估時長: {duration:.0f} 分鐘\n", file=sys.stderr)
        sys.exit(1)

    print(f"OK: CJK {cjk} | 小節 {sections} | 估時長 {duration:.0f} 分鐘 | 最低 {required} 字")


if __name__ == '__main__':
    main()
