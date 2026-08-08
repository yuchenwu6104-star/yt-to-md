#!/usr/bin/env python3
"""地圖版 /yt 的入口：吃 YouTube URL，產出分流稿＋地圖＋帶行號逐字稿。

介面刻意跟 `yt_to_article.py` 相容（同樣吃 URL 與 `--lang`），
watcher 只要改 `ARTICLE_SCRIPT` 指向這一支就能切換，要退回也是改回去而已。

抓字幕與 metadata 直接重用 `yt_to_article` 的函式，不重寫：那些程式碼扛過
Whisper fallback、yt-dlp 退路、VTT 解析等一堆邊界情況，重寫只會把踩過的
坑再踩一次。這支只負責換掉「叫模型寫文章」那一段。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
YT_SCRIPTS = HERE.parent
if str(YT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(YT_SCRIPTS))

import yt_to_article as yta  # noqa: E402


def _slug(metadata: dict) -> str:
    """檔名沿用舊版規則：日期_yt_頻道_關鍵字。

    關鍵字舊版是由模型給的 tags 組出來的，這一版沒有模型寫文章那一步，
    改用影片標題取前幾個詞——分流稿的檔名只要能認得出是哪一集就夠了。
    """
    import datetime
    # 排程改到 23:00 之後，跑出來的檔案是隔天早上讀的。晚間跑就掛隔天日期，
    # 讓檔名跟「哪一天的功課」對齊。影片本身的日期不受影響（frontmatter 與
    # 逐字稿都還在），這裡只是檔名。
    now = datetime.datetime.now()
    day = now.date() + datetime.timedelta(days=1) if now.hour >= 22 else now.date()
    today = day.isoformat()
    # 頻道名有的很長（含副標與引號），不截的話整條路徑會逼近 Windows 的
    # 260 字元上限，工作目錄還要再往下疊一層。
    channel = re.sub(r"[^\w一-鿿]+", "_", metadata.get("channel", "Unknown")).strip("_")[:40]
    title = metadata.get("title", "")
    words = re.findall(r"[\w一-鿿]+", title)
    keywords = "_".join(words[:6])[:60].strip("_") or "untitled"
    return f"{today}_yt_{channel}_{keywords}"


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="YouTube → 分流稿＋地圖")
    ap.add_argument("youtube_url")
    ap.add_argument("--lang", default=None, help="無字幕時 Whisper 轉錄的語言提示")
    ap.add_argument("--outdir", default=None)
    args = ap.parse_args()

    vid = yta.extract_video_id(args.youtube_url)
    metadata = yta.fetch_metadata(vid)

    en = yta.fetch_english_transcript(vid)
    if not en:
        # 沒有英文字幕就退回原字幕（日韓節目常見）。地圖層不要求英文，
        # 只要求「有一份可以掛行號的原文」。
        try:
            en, _ = yta.fetch_transcript(vid)
        except Exception as e:  # noqa: BLE001
            sys.exit(f"抓不到字幕：{e}")
    if not en or len(en) < 500:
        sys.exit("字幕過短或為空，跳過")

    outdir = Path(args.outdir) if args.outdir else Path(yta.OUTPUT_DIR)
    outdir.mkdir(parents=True, exist_ok=True)
    base = _slug(metadata)
    transcript_path = outdir / f"{base}_transcript.txt"
    transcript_path.write_text(en, encoding="utf-8")

    context = (
        f"節目：{metadata.get('channel', '')}，影片標題：{metadata.get('title', '')}。"
        "字幕可能是自動生成的，人名常被聽錯。"
    )
    # metadata 除了餵給模型當脈絡，也要落進分流稿 frontmatter：C 路的下游只讀
    # 分流稿，這裡不傳，成品就沒有原始連結可掛，標題也只能從截斷過的檔名回推。
    canonical_url = f"https://www.youtube.com/watch?v={vid}"
    cmd = [sys.executable, str(HERE / "run_pipeline.py"),
           str(transcript_path), str(outdir), context,
           "--url", canonical_url,
           "--title", metadata.get("title", ""),
           "--channel", metadata.get("channel", ""),
           "--upload-date", metadata.get("upload_date", "")]
    raise SystemExit(subprocess.run(cmd, text=True).returncode)


if __name__ == "__main__":
    main()
