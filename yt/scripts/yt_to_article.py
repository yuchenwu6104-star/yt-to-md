"""YouTube 影片 → 深度洞察文章

抓取 YouTube 字幕，透過 MiniMax M2.7 API 生成繁體中文深度分析文章，
落檔至 Obsidian vault。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Load .env if env vars not already set
# ---------------------------------------------------------------------------

_ENV_FILE = Path(
    r"C:\Users\wukee\OneDrive\文件\clon資料\taiwan_stock_dashboard\美股資料\.env"
)
if not os.getenv("ANTHROPIC_API_KEY") and _ENV_FILE.exists():
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MINIMAX_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.minimax.io/anthropic")
MINIMAX_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MINIMAX_MODEL = "MiniMax-M2.7"

OUTPUT_DIR = Path(
    r"C:\Users\wukee\OneDrive\文件\Obsidian Vault\投資筆記\每週總結\每日研究"
)

# Max transcript characters to send (avoid token overflow)
MAX_TRANSCRIPT_CHARS = 60_000

# ---------------------------------------------------------------------------
# 1. Parse YouTube URL
# ---------------------------------------------------------------------------

def extract_video_id(url: str) -> str:
    """Extract video ID from various YouTube URL formats."""
    patterns = [
        r"(?:v=|/v/)([a-zA-Z0-9_-]{11})",
        r"(?:youtu\.be/)([a-zA-Z0-9_-]{11})",
        r"(?:embed/)([a-zA-Z0-9_-]{11})",
        r"(?:shorts/)([a-zA-Z0-9_-]{11})",
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    raise ValueError(f"無法從 URL 中提取影片 ID: {url}")


# ---------------------------------------------------------------------------
# 2. Fetch transcript
# ---------------------------------------------------------------------------

def fetch_transcript(video_id: str) -> tuple[str, str]:
    """Fetch transcript using youtube-transcript-api.

    Returns (transcript_text, language_code).
    Tries zh-TW → zh-Hant → zh → en → first available.
    """
    from youtube_transcript_api import YouTubeTranscriptApi

    ytt_api = YouTubeTranscriptApi()

    preferred_langs = ["zh-TW", "zh-Hant", "zh", "en"]

    try:
        fetched = ytt_api.fetch(video_id, languages=preferred_langs)
        lang = fetched.language_code if hasattr(fetched, "language_code") else "unknown"
    except Exception:
        # Fallback: list available transcripts and pick first
        transcript_list = ytt_api.list(video_id)
        available = list(transcript_list)
        if not available:
            raise RuntimeError(f"影片 {video_id} 沒有可用的字幕")
        fetched = available[0].fetch()
        lang = available[0].language_code if hasattr(available[0], "language_code") else "unknown"

    # Combine all snippets into plain text
    lines = []
    for snippet in fetched:
        text = snippet.text if hasattr(snippet, "text") else snippet.get("text", "")
        lines.append(text)

    transcript_text = "\n".join(lines)
    return transcript_text, lang


# ---------------------------------------------------------------------------
# 3. Fetch video metadata via yt-dlp
# ---------------------------------------------------------------------------

def fetch_metadata(video_id: str) -> dict:
    """Get video metadata (title, channel, upload_date, duration) via yt-dlp."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        result = subprocess.run(
            ["yt-dlp", "--dump-json", "--no-download", url],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            print(f"[warn] yt-dlp failed: {result.stderr[:200]}", file=sys.stderr)
            return _fallback_metadata(video_id)

        data = json.loads(result.stdout)
        upload_date = data.get("upload_date", "")
        if upload_date and len(upload_date) == 8:
            upload_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"

        return {
            "title": data.get("title", "Unknown"),
            "channel": data.get("channel", data.get("uploader", "Unknown")),
            "upload_date": upload_date,
            "duration_seconds": data.get("duration", 0),
            "description": (data.get("description", "") or "")[:500],
        }
    except Exception as e:
        print(f"[warn] yt-dlp metadata failed: {e}", file=sys.stderr)
        return _fallback_metadata(video_id)


def _fallback_metadata(video_id: str) -> dict:
    """Minimal fallback when yt-dlp fails."""
    return {
        "title": f"YouTube Video {video_id}",
        "channel": "Unknown",
        "upload_date": "",
        "duration_seconds": 0,
        "description": "",
    }


# ---------------------------------------------------------------------------
# 4. Call MiniMax API to generate article
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
你是一位頂尖的深度洞察文章寫手，專門將 YouTube 訪談或演講內容轉化為高品質的繁體中文分析文章。

你的文章風格特色：
- 有故事性：不是乾巴巴的摘要，而是用敘事手法帶讀者進入主題
- 有觀點：不只是轉述，要提煉出核心洞察並加入分析評論
- 結構清晰：用吸引人的小標題將內容分為 4-6 個段落
- 語言流暢：繁體中文為主，專有名詞保留英文（格式：中文（English））
- 深度適中：讓非專業讀者也能理解，但不失專業深度

你的輸出必須嚴格遵守以下 JSON 格式（不要輸出任何其他內容）：
{
  "title": "文章標題（吸引人、有洞察力，不超過30字）",
  "tags": ["標籤1", "標籤2", "標籤3"],
  "filename_keywords": "2到3個關鍵字用底線連接，例如：AI公司_利潤_軟體業",
  "article": "完整的 markdown 文章內容（不包含標題，從導言開始）"
}

文章內容要求：
1. 導言（2-3 段）：開頭第一段必須先介紹講者/受訪者是誰——他的身份、職位、代表性成就、以及為什麼他的觀點值得關注。讀者需要先知道「這個人是誰、為什麼我該聽他說話」，才會有動力往下讀。接著再帶出本次訪談的核心論點和背景脈絡。
2. 正文（4-6 個 ## 小標題段落）：每段 300-500 字，每個小標題要有吸引力
3. 結語（1 段）：總結核心洞察，給讀者留下思考空間
4. 總字數：3000-5000 字
5. 適當使用 **粗體** 標記關鍵概念和重要數據
6. 使用 > 引用塊呈現講者的重要原話或核心論述"""


def call_minimax(transcript: str, metadata: dict) -> dict:
    """Send transcript to MiniMax and get structured article response."""
    if not MINIMAX_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY 環境變數未設定。"
            "請在 .env 中設定 MiniMax Token Plan key (sk-cp-...)"
        )

    # Truncate if too long
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        transcript = transcript[:MAX_TRANSCRIPT_CHARS] + "\n\n[... 字幕已截斷 ...]"

    duration_min = metadata.get("duration_seconds", 0) // 60

    user_prompt = f"""以下是一部 YouTube 影片的逐字稿，請根據內容撰寫一篇深度洞察文章。

影片資訊：
- 標題：{metadata.get('title', 'Unknown')}
- 頻道：{metadata.get('channel', 'Unknown')}
- 發布日期：{metadata.get('upload_date', '未知')}
- 時長：約 {duration_min} 分鐘
- 簡介：{metadata.get('description', '')[:300]}

逐字稿內容：
{transcript}

請用 JSON 格式輸出（嚴格遵守 system prompt 中的格式要求）。"""

    with httpx.Client(timeout=300) as client:
        r = client.post(
            f"{MINIMAX_BASE_URL}/v1/messages",
            headers={
                "x-api-key": MINIMAX_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": MINIMAX_MODEL,
                "max_tokens": 16384,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_prompt}],
            },
        )
        r.raise_for_status()
        data = r.json()

    # Extract text from response
    raw_text = ""
    for block in data.get("content", []):
        if block.get("type") == "text":
            raw_text = block["text"]
            break
    if not raw_text:
        raw_text = data.get("content", [{}])[-1].get("text", "")

    # Parse JSON from response (handle markdown code fences)
    json_text = raw_text.strip()
    if json_text.startswith("```"):
        json_text = re.sub(r"^```(?:json)?\s*\n?", "", json_text)
        json_text = re.sub(r"\n?```\s*$", "", json_text)

    try:
        return json.loads(json_text)
    except json.JSONDecodeError:
        # If JSON parsing fails, return raw text as article
        print("[warn] MiniMax 回傳非 JSON 格式，使用原始文字", file=sys.stderr)
        return {
            "title": metadata.get("title", "YouTube 影片摘要"),
            "tags": [],
            "filename_keywords": "影片摘要",
            "article": raw_text,
        }


# ---------------------------------------------------------------------------
# 5. Format and save article
# ---------------------------------------------------------------------------

def sanitize_filename(s: str) -> str:
    """Remove or replace characters that are invalid in filenames."""
    s = re.sub(r'[<>:"/\\|?*]', "", s)
    s = re.sub(r"\s+", "_", s.strip())
    return s[:50]  # keep it reasonable


def save_article(
    article_data: dict,
    metadata: dict,
    youtube_url: str,
    output_dir: Path,
) -> Path:
    """Format markdown with frontmatter and save to output directory."""
    today = datetime.now().strftime("%Y-%m-%d")
    channel_clean = sanitize_filename(metadata.get("channel", "Unknown"))
    keywords = sanitize_filename(article_data.get("filename_keywords", "摘要"))

    filename = f"{today}_yt_{channel_clean}_{keywords}.md"
    filepath = output_dir / filename

    tags_yaml = json.dumps(article_data.get("tags", []), ensure_ascii=False)

    frontmatter = f"""---
type: yt_article
date: {today}
source: YouTube
youtube_url: {youtube_url}
channel: "{metadata.get('channel', 'Unknown')}"
video_title: "{metadata.get('title', 'Unknown')}"
tags: {tags_yaml}
---"""

    video_title = metadata.get("title", "YouTube 影片")
    upload_date = metadata.get("upload_date", "")
    channel = metadata.get("channel", "")

    source_line = f"> 原始影片：[{video_title}]({youtube_url})"
    if channel:
        source_line += f" | {channel}"
    if upload_date:
        source_line += f" | {upload_date}"

    full_content = f"""{frontmatter}

# {article_data.get('title', video_title)}

{source_line}

{article_data.get('article', '')}

---
*本文由 AI 根據 YouTube 影片內容生成，僅供參考。*
"""

    output_dir.mkdir(parents=True, exist_ok=True)
    filepath.write_text(full_content, encoding="utf-8")
    return filepath


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(youtube_url: str) -> str:
    """Full pipeline: URL → transcript → article → saved file.

    Returns the path of the saved file.
    """
    print(f"[1/5] 解析 YouTube URL...")
    video_id = extract_video_id(youtube_url)
    print(f"      影片 ID: {video_id}")

    print(f"[2/5] 抓取字幕...")
    transcript, lang = fetch_transcript(video_id)
    print(f"      字幕語言: {lang} | 長度: {len(transcript)} 字元")

    print(f"[3/5] 取得影片資訊...")
    metadata = fetch_metadata(video_id)
    print(f"      標題: {metadata['title']}")
    print(f"      頻道: {metadata['channel']}")

    print(f"[4/5] 呼叫 MiniMax API 生成文章...")
    article_data = call_minimax(transcript, metadata)
    print(f"      文章標題: {article_data.get('title', 'N/A')}")

    print(f"[5/5] 儲存文章...")
    filepath = save_article(article_data, metadata, youtube_url, OUTPUT_DIR)
    print(f"      已儲存: {filepath}")

    return str(filepath)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python yt_to_article.py <YouTube URL>")
        sys.exit(1)
    result = main(sys.argv[1])
    print(f"\n完成！文章已儲存至：{result}")
