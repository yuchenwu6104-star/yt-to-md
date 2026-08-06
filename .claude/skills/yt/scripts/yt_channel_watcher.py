#!/usr/bin/env python3
"""
yt_channel_watcher.py
自動輪巡 YouTube 頻道，對新影片執行 yt_to_article.py。
每日排程執行，不依賴 Claude Code 是否在線。
"""
from __future__ import annotations

import json
import re
import argparse
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
# 兩種產出模式，用環境變數切換（要退回舊版：把 YT_MODE 設成 article 或刪掉）：
#   triage（預設）  ytmap/yt_triage.py：分流稿＋地圖＋帶行號逐字稿，不由模型寫文章
#   article         yt_to_article.py：舊版，模型一次做完翻譯／結構／歸屬／專名／文筆
# 換掉舊版的理由：同一集跑兩次，三整段虛構全部出現在「寫文章」那一步，
# 而分段索引與專名標記那些工作它做得對。把模型的任務縮窄，錯就少了。
_YT_MODE = os.environ.get("YT_MODE", "triage").strip().lower()
ARTICLE_SCRIPT = (
    SCRIPT_DIR / "yt_to_article.py" if _YT_MODE == "article"
    else SCRIPT_DIR / "ytmap" / "yt_triage.py"
)
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


def fetch_channel_videos(handle: str, lookback_days: int, max_videos: int,
                         lookback_hours: float = None) -> list[dict]:
    """
    用 yt-dlp 抓取頻道最新影片清單（含 duration、upload_date）。
    回傳 list of {video_id, title, duration_seconds}
    不使用 --flat-playlist，確保 upload_date 可用，讓 --dateafter 真正生效。
    Python 端再做第二層日期過濾作為保險。
    lookback_hours 若提供，優先生效並做「小時級」精準過濾（首跑只抓 48hr 用）。
    """
    url = f"https://www.youtube.com/{handle}/videos"
    if lookback_hours is not None:
        cutoff = datetime.now() - timedelta(hours=lookback_hours)
    else:
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

        # 第二層日期過濾：優先用精準 timestamp（epoch 秒），否則退回 upload_date（日級）
        ts = item.get("timestamp")
        if ts:
            try:
                if datetime.fromtimestamp(ts) < cutoff:
                    continue
            except (ValueError, OverflowError, OSError):
                pass
        else:
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


# 頻道 category 前綴 → Whisper 語言碼。只在落到本地 Whisper fallback（無字幕）時
# 生效，強制解碼語言可大幅降低日韓專名誤判。未知/無前綴 → None（沿用自動偵測），
# 故無語言前綴的 master channels.json 行為完全不變。
_CATEGORY_LANG = {
    "JP": "ja", "JA": "ja",
    "KR": "ko", "KO": "ko",
    "EN": "en",
    "CN": "zh", "ZH": "zh", "TW": "zh",
}


def lang_from_category(category: str | None) -> str | None:
    """從頻道 category（如 "JP/Markets"）取語言前綴並映射成 Whisper 語言碼。"""
    if not category:
        return None
    prefix = category.split("/", 1)[0].strip().upper()
    return _CATEGORY_LANG.get(prefix)


def process_video(video_id: str, title: str, lang: str | None = None) -> bool:
    """呼叫 yt_to_article.py 處理單部影片，回傳是否成功。

    lang 若提供（由頻道 category 推導），會以 --lang 傳給下游，只在無字幕、
    落到本地 Whisper 轉錄時生效。
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    cmd = [sys.executable, str(ARTICLE_SCRIPT), url]
    if lang:
        cmd += ["--lang", lang]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=5400,
            encoding="utf-8", env=env
        )
        # 撈出翻譯修補 pass 的觸發紀錄（日韓來源殘留假名/諺文時才有），成功也記
        for line in (result.stderr or "").splitlines():
            if "翻譯修補 pass" in line or "修補後降為" in line or "改用本地 Whisper 轉錄" in line:
                log(f"    {line.split(']', 1)[-1].strip() or line.strip()}")
        if result.returncode == 0:
            return True
        else:
            log(f"    ✗ 生成失敗: {result.stderr[-300:].strip()}")
            return False
    except subprocess.TimeoutExpired:
        log(f"    ✗ 逾時（1800s）")
        return False
    except Exception as e:
        log(f"    ✗ 例外: {e}")
        return False


def main():
    global CHANNELS_FILE, PROCESSED_FILE, LOG_FILE

    parser = argparse.ArgumentParser(description="YouTube 頻道輪巡")
    parser.add_argument("--config", default=str(CHANNELS_FILE), help="頻道名單 json")
    parser.add_argument("--processed", default=str(PROCESSED_FILE), help="已處理記錄 json")
    parser.add_argument("--log", default=str(LOG_FILE), help="log 檔")
    parser.add_argument("--lookback-hours", type=float, default=None,
                        help="只抓最近 N 小時內影片（覆蓋 settings.lookback_days，首跑 48 用）")
    args = parser.parse_args()

    CHANNELS_FILE = Path(args.config)
    PROCESSED_FILE = Path(args.processed)
    LOG_FILE = Path(args.log)
    lookback_hours = args.lookback_hours

    log("=" * 60)
    log("YouTube 頻道輪巡開始")
    if lookback_hours is not None:
        log(f"⏱ 本次只抓最近 {lookback_hours:.0f} 小時內影片")

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
        mpc = ch.get("max_per_channel", max_per_channel)
        ch_lang = lang_from_category(ch.get("category"))
        log(f"\n📡 {name} ({handle})" + (f" · Whisper 語言={ch_lang}" if ch_lang else ""))

        videos = fetch_channel_videos(handle, lookback_days, mpc, lookback_hours)
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
        candidates = candidates[:mpc]

        log(f"  → 取得 {len(videos)} 部｜長度不足 {skipped_duration}｜已處理 {skipped_dup}｜標題重複 {skipped_title_dup}｜待處理 {len(candidates)} 部")
        total_skipped += skipped_dup + skipped_title_dup

        for v in candidates:
            vid = v["video_id"]
            title = v["title"][:60]
            dur_min = v["duration_seconds"] // 60
            log(f"  ▶ [{dur_min}min] {title}")
            success = process_video(vid, title, ch_lang)
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
