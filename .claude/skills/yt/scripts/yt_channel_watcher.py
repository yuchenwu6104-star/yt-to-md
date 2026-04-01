#!/usr/bin/env python3
"""
yt_channel_watcher.py
自動輪巡 YouTube 頻道，對新影片執行 yt_to_article.py。
每日排程執行，不依賴 Claude Code 是否在線。
"""

import json
import subprocess
import sys
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Windows cp950 終端機支援 emoji
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

SCRIPT_DIR = Path(__file__).parent
CHANNELS_FILE = SCRIPT_DIR / "channels.json"
PROCESSED_FILE = SCRIPT_DIR / "processed_videos.json"
ARTICLE_SCRIPT = SCRIPT_DIR / "yt_to_article.py"
LOG_FILE = SCRIPT_DIR / "watcher.log"


def log(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_channels() -> dict:
    with open(CHANNELS_FILE, encoding="utf-8") as f:
        return json.load(f)


def load_processed() -> set:
    if not PROCESSED_FILE.exists():
        return set()
    with open(PROCESSED_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return set(data.get("video_ids", []))


def save_processed(video_ids: set):
    with open(PROCESSED_FILE, "w", encoding="utf-8") as f:
        json.dump({"video_ids": sorted(video_ids)}, f, indent=2, ensure_ascii=False)


def fetch_channel_videos(handle: str, lookback_days: int, max_videos: int) -> list[dict]:
    """
    用 yt-dlp 抓取頻道最新影片清單（含 duration）。
    回傳 list of {video_id, title, duration_seconds}
    注意：flat-playlist 模式不回傳 upload_date，改靠 processed_videos.json 防重複。
    """
    url = f"https://www.youtube.com/{handle}/videos"
    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--dump-json",
        "--playlist-end", str(max_videos * 3),  # 多抓一些，之後再篩
        "--no-warnings",
        "--quiet",
        url,
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60, encoding="utf-8"
        )
    except subprocess.TimeoutExpired:
        log(f"  ⚠️  {handle} 取得影片清單逾時")
        return []
    except Exception as e:
        log(f"  ⚠️  {handle} 執行 yt-dlp 失敗: {e}")
        return []

    if result.returncode != 0 and not result.stdout.strip():
        log(f"  ⚠️  {handle} yt-dlp 錯誤: {result.stderr[:200]}")
        return []

    videos = []
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue

        video_id = item.get("id") or item.get("video_id")
        if not video_id:
            continue

        duration = item.get("duration") or 0  # 秒數
        title = item.get("title") or ""

        videos.append({
            "video_id": video_id,
            "title": title,
            "duration_seconds": duration,
        })

    return videos


def process_video(video_id: str, title: str) -> bool:
    """呼叫 yt_to_article.py 處理單部影片，回傳是否成功。"""
    url = f"https://www.youtube.com/watch?v={video_id}"
    cmd = [sys.executable, str(ARTICLE_SCRIPT), url]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300,
            encoding="utf-8", env=env
        )
        if result.returncode == 0:
            return True
        else:
            log(f"    ✗ 生成失敗: {result.stderr[-300:].strip()}")
            return False
    except subprocess.TimeoutExpired:
        log(f"    ✗ 逾時（300s）")
        return False
    except Exception as e:
        log(f"    ✗ 例外: {e}")
        return False


def main():
    log("=" * 60)
    log("YouTube 頻道輪巡開始")

    config = load_channels()
    settings = config["settings"]
    min_duration_sec = settings["min_duration_minutes"] * 60
    lookback_days = settings["lookback_days"]
    max_per_channel = settings["max_per_channel"]

    processed = load_processed()
    log(f"已處理影片紀錄：{len(processed)} 部")

    total_new = 0
    total_skipped = 0
    total_failed = 0

    for ch in config["channels"]:
        if not ch.get("enabled", True):
            continue

        name = ch["name"]
        handle = ch["handle"]
        log(f"\n📡 {name} ({handle})")

        videos = fetch_channel_videos(handle, lookback_days, max_per_channel)
        if not videos:
            log(f"  → 無影片或取得失敗")
            continue

        # 篩選長度 + 去重
        candidates = [
            v for v in videos
            if v["duration_seconds"] >= min_duration_sec
            and v["video_id"] not in processed
        ][:max_per_channel]

        skipped_duration = sum(1 for v in videos if v["duration_seconds"] < min_duration_sec)
        skipped_dup = sum(1 for v in videos if v["video_id"] in processed)
        log(f"  → 取得 {len(videos)} 部｜長度不足跳過 {skipped_duration}｜已處理跳過 {skipped_dup}｜待處理 {len(candidates)} 部")
        total_skipped += skipped_dup

        for v in candidates:
            vid = v["video_id"]
            title = v["title"][:60]
            dur_min = v["duration_seconds"] // 60
            log(f"  ▶ [{dur_min}min] {title}")
            success = process_video(vid, title)
            if success:
                processed.add(vid)
                save_processed(processed)
                log(f"    ✓ 完成")
                total_new += 1
            else:
                total_failed += 1

    log(f"\n{'=' * 60}")
    log(f"輪巡完成｜新增 {total_new} 篇文章｜跳過 {total_skipped} 部｜失敗 {total_failed} 部")


if __name__ == "__main__":
    main()
