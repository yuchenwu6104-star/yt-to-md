#!/usr/bin/env python3
"""
yt_channel_watcher.py
自動輪巡 YouTube 頻道，對新影片執行 yt_to_article.py。
每日排程執行，不依賴 Claude Code 是否在線。
"""

import json
import re
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


def load_processed() -> dict:
    """回傳 {"video_ids": set, "titles": set}"""
    if not PROCESSED_FILE.exists():
        return {"video_ids": set(), "titles": set()}
    with open(PROCESSED_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return {
        "video_ids": set(data.get("video_ids", [])),
        "titles": set(data.get("titles", [])),
    }


def save_processed(processed: dict):
    with open(PROCESSED_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "video_ids": sorted(processed["video_ids"]),
            "titles": sorted(processed["titles"]),
        }, f, indent=2, ensure_ascii=False)


def normalize_title(title: str) -> str:
    """正規化標題用於跨頻道去重：去除空白、標點、轉小寫。"""
    t = re.sub(r'[\s\-_|｜#＃:：.。,，!！?？\[\]【】()（）]+', '', title)
    return t.lower()


def fetch_channel_videos(handle: str, lookback_days: int, max_videos: int) -> list[dict]:
    """
    用 yt-dlp 抓取頻道最新影片清單（含 duration、upload_date）。
    回傳 list of {video_id, title, duration_seconds}
    不使用 --flat-playlist，確保 upload_date 可用，讓 --dateafter 真正生效。
    Python 端再做第二層日期過濾作為保險。
    """
    url = f"https://www.youtube.com/{handle}/videos"
    cutoff = datetime.now() - timedelta(days=lookback_days)
    dateafter = cutoff.strftime("%Y%m%d")
    cmd = [
        "yt-dlp",
        "--dump-json",
        "--playlist-end", str(max_videos * 3),  # 多抓一些，之後再篩
        "--dateafter", dateafter,
        "--no-warnings",
        "--quiet",
        url,
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, encoding="utf-8"
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

        # 第二層日期過濾：upload_date 格式為 YYYYMMDD
        upload_date_str = item.get("upload_date") or ""
        if upload_date_str:
            try:
                upload_date = datetime.strptime(upload_date_str, "%Y%m%d")
                if upload_date < cutoff:
                    continue
            except ValueError:
                pass

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
    log(f"已處理影片紀錄：{len(processed['video_ids'])} 部")

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

        # 篩選長度 + video_id 去重 + 標題去重（跨頻道）
        candidates = []
        skipped_duration = 0
        skipped_dup = 0
        skipped_title_dup = 0
        for v in videos:
            if v["duration_seconds"] < min_duration_sec:
                skipped_duration += 1
            elif v["video_id"] in processed["video_ids"]:
                skipped_dup += 1
            elif normalize_title(v["title"]) in processed["titles"]:
                skipped_title_dup += 1
                log(f"  ⏭ 標題重複跳過: {v['title'][:50]}")
            else:
                candidates.append(v)
        candidates = candidates[:max_per_channel]

        log(f"  → 取得 {len(videos)} 部｜長度不足 {skipped_duration}｜已處理 {skipped_dup}｜標題重複 {skipped_title_dup}｜待處理 {len(candidates)} 部")
        total_skipped += skipped_dup + skipped_title_dup

        for v in candidates:
            vid = v["video_id"]
            title = v["title"][:60]
            dur_min = v["duration_seconds"] // 60
            log(f"  ▶ [{dur_min}min] {title}")
            success = process_video(vid, title)
            if success:
                processed["video_ids"].add(vid)
                processed["titles"].add(normalize_title(v["title"]))
                save_processed(processed)
                log(f"    ✓ 完成")
                total_new += 1
            else:
                total_failed += 1

    log(f"\n{'=' * 60}")
    log(f"輪巡完成｜新增 {total_new} 篇文章｜跳過 {total_skipped} 部｜失敗 {total_failed} 部")


if __name__ == "__main__":
    main()
