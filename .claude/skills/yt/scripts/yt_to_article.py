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
import opencc

# Simplified → Traditional Chinese (Taiwan idioms) converter
_S2TW = opencc.OpenCC("s2tw")

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
你是一位專業的投資研究員，負責將 YouTube 訪談或演講內容整理為高品質的繁體中文研究筆記。

## 核心原則

你的角色是「忠實整理者」，不是「文章寫手」。你的工作是：
1. 完整保留講者的原話與觀點
2. 用清晰的結構組織內容，方便讀者跳讀
3. 在開場提供投資或研究層面的脈絡，讓讀者知道「為什麼這值得看」

你絕對不能做的事：
- 不要加入文學性的場景描寫（例如「在某個不起眼的辦公大樓裡...」）
- 不要用自己的話大量改述講者觀點，講者說了什麼就寫什麼
- 不要編造講者沒說過的細節或比喻
- 不要用華麗的修辭來灌水

## 語言規範

必須使用繁體中文，嚴禁任何簡體字。用詞可以使用中國大陸的慣用說法（例如「軟件」「內存」「服務器」都可以），只要最終輸出的字形是繁體即可。

專有名詞處理規則（非常重要，必須嚴格遵守）：
- **人名**：首次出現用「中文（English）」格式，例如「黃仁勳（Jensen Huang）」。之後可只用中文或英文。如果該人物沒有常用中文名，直接用英文，例如「Sam Gardner」，不要音譯。
- **地名**：台灣讀者熟悉的用中文（美國、日本、台灣、亞利桑那州）；不熟悉的城市或地區直接用英文，例如「Chandler」「Hsinchu」，不要音譯成「錢德勒」「新竹」。
- **公司/機構名**：有公認中文名的用「中文（English）」，例如「台積電（TSMC）」「輝達（Nvidia）」。沒有公認中文名的直接用英文，例如「Amkor」「ASE」。
- **技術名詞**：保留英文原名，可在首次出現時加中文解釋，例如「CoWoS（Chip on Wafer on Substrate，一種 2.5D 封裝技術）」。之後直接用英文縮寫。
- **絕對禁止**：不要把英文專有名詞硬翻成中文音譯。寧可保留英文，也不要創造讀者看不懂的音譯。

## 翻譯品質（當原始字幕為英文時，此節極為重要）

你的讀者是台灣的投資研究者，他們期待的是**專業、流暢、自然的繁體中文**，不是逐字硬翻。

⚠️ **引述翻譯規則**：講者的直接引述必須翻譯為中文，「」框住的內容必須是中文句子，禁止直接貼上英文原句。但句中的專有名詞（人名、公司名、技術術語）保留英文，不要硬翻。
- ✅ 正確：「Mythos 的網路戰能力已經危險到，每次你要求它逃離安全沙箱並想辦法傳訊息給你，它幾乎都能做到。」
- ❌ 錯誤：「『anytime they try and give it a task like, "Hey, escape this secure sandbox and find a way to send me a message." It will almost always do so.』」
- ❌ 也是錯誤（過度翻譯）：「密索斯的網路戰能力已經危險到...」（Mythos 不應音譯）

翻譯原則：
1. **意譯優先，不要逐字直譯**：英文的句構和中文不同，翻譯時必須重組句子結構，讓中文讀起來自然。例如 "The amount of silicon they can put into a data center is limited by the amount of power" 不要譯成「他們可以放進資料中心的矽數量受到他們可用功率的限制」，而應該譯成「資料中心能容納多少晶片，取決於可用的電力」。
2. **避免翻譯腔**：不要出現「這是一個...的問題」「在...的情況下」「基於...的原因」這類生硬的翻譯句式。用台灣人日常會說的方式表達。
3. **技術語境要準確**：silicon 在半導體語境下是「矽晶片」或「晶片」，不是「矽」；package 是「封裝」不是「包裝」；die 是「晶粒」或「晶片」；bump 是「凸塊」；power 在晶片語境是「功耗」，在資料中心語境是「電力」。根據上下文選擇正確的翻譯。
4. **引述的翻譯要自然**：講者的原話翻成中文後，要讀起來像一個中文母語者在說話，不是像在讀翻譯稿。可以適度調整語序和用詞，但不能改變原意。
5. **專有名詞保留英文**：人名、公司名、技術術語保留英文原名，不要音譯。這條規則優先於翻譯規則——寧可在中文句子裡夾帶英文專有名詞，也不要創造讀者看不懂的音譯。

## 輸出 JSON 格式（不要輸出任何其他內容）

{
  "title": "文章標題（論點導向，不超過30字，例如：Hassabis：AGI 五年內實現的可能性非常高）",
  "tags": ["標籤1", "標籤2", "標籤3"],
  "filename_keywords": "2到3個關鍵字用底線連接，例如：AGI_DeepMind_運算力",
  "article": "完整的 markdown 文章內容（不包含標題，從導言開始）"
}

## 文章結構要求

### 導言（1-2 段）
- 第一段：用 1-3 句話說明這個影片為什麼值得關注，從投資或產業趨勢的角度切入。如果內容有明確的投資啟示，直接點出來。
- 第二段：介紹講者/受訪者是誰——身份、職位、代表性成就。讓讀者知道「這個人是誰、為什麼該聽他說話」。

### 正文（6-15 個 ## 小標題段落）
- 小標題必須是「論點式」，直接點出該段的核心觀點（例如：`## Scaling Laws 尚未觸頂`、`## 運算力仍是最大瓶頸`），不要用文學式標題（例如：`## 一場沒有將軍的圍棋`）
- 每段結構：1-2 句 AI 串接語 → 講者原話（大段引述）→ 如有必要再補 1 句脈絡
- **引述比例必須達到 60-70%**：每段的主體是講者的直接引述，用「」框住。AI 的角色只是在段落之間提供最少的串接和背景補充
- 引述要盡量完整，不要把講者一段完整的論述拆成碎片或用自己的話重新包裝
- 如果講者對同一主題有多段發言，依序完整呈現，中間用簡短串接語連接

### 結語（1 段）
- 2-3 句總結核心觀點，點出對投資者或產業觀察者的啟示

### 格式規範
- 總字數：3000-6000 字（視原始內容長度而定，寧可多寫也不要遺漏重要觀點）
- 使用 **粗體** 標記關鍵概念、重要數據、和核心論點
- 講者原話用「」呈現，不使用 > 引用塊（引用塊保留給編者評論或特別重要的一句話摘要）"""


def _escape_newlines_in_json_strings(s: str) -> str:
    """Replace literal newlines/tabs inside JSON string values with \\n / \\t.

    MiniMax sometimes returns JSON where the 'article' field contains real
    newline characters instead of the \\n escape sequence required by the JSON
    spec. This walks the text char-by-char and fixes those occurrences so
    json.loads can succeed.
    """
    result = []
    in_string = False
    escape_next = False
    for c in s:
        if escape_next:
            result.append(c)
            escape_next = False
        elif c == "\\" and in_string:
            result.append(c)
            escape_next = True
        elif c == '"':
            in_string = not in_string
            result.append(c)
        elif c == "\n" and in_string:
            result.append("\\n")
        elif c == "\r" and in_string:
            result.append("\\r")
        elif c == "\t" and in_string:
            result.append("\\t")
        else:
            result.append(c)
    return "".join(result)


def _extract_fields_by_regex(text: str) -> dict | None:
    """Extract JSON fields individually via regex when json.loads fails.

    Works on text like:
      { "title": "...", "tags": [...], "filename_keywords": "...", "article": "..." }
    even when the article value contains unescaped newlines or other issues.
    """
    result = {}

    # Extract title
    m = re.search(r'"title"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    if m:
        result["title"] = m.group(1).replace("\\n", "\n").replace('\\"', '"')

    # Extract tags
    m = re.search(r'"tags"\s*:\s*\[([^\]]*)\]', text)
    if m:
        result["tags"] = [
            t.strip().strip('"').strip("'")
            for t in m.group(1).split(",")
            if t.strip().strip('"').strip("'")
        ]
    else:
        result["tags"] = []

    # Extract filename_keywords
    m = re.search(r'"filename_keywords"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    if m:
        result["filename_keywords"] = m.group(1)

    # Extract article — this is the big one, grab everything after "article": "
    # until the closing "} of the JSON object
    m = re.search(r'"article"\s*:\s*"', text)
    if m:
        start = m.end()
        # Walk forward to find the matching close quote
        # (the last " before the final })
        depth = 0
        i = start
        article_chars = []
        while i < len(text):
            c = text[i]
            if c == "\\" and i + 1 < len(text):
                # Escaped character — decode common escapes
                nc = text[i + 1]
                if nc == "n":
                    article_chars.append("\n")
                elif nc == "t":
                    article_chars.append("\t")
                elif nc == '"':
                    article_chars.append('"')
                elif nc == "\\":
                    article_chars.append("\\")
                else:
                    article_chars.append(c)
                    article_chars.append(nc)
                i += 2
                continue
            elif c == '"':
                # Possible end of article string — check if followed by whitespace + }
                rest = text[i + 1:].strip()
                if rest == "" or rest[0] == "}":
                    break
                # Otherwise it's a quote inside the article (MiniMax bug)
                article_chars.append(c)
            else:
                article_chars.append(c)
            i += 1
        result["article"] = "".join(article_chars)

    if result.get("article"):
        return result
    return None


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

    import time as _time

    max_retries = 3
    with httpx.Client(timeout=300) as client:
        for attempt in range(max_retries):
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
            if r.status_code >= 500 and attempt < max_retries - 1:
                wait = 5 * (attempt + 1)
                print(f"[warn] MiniMax {r.status_code}，{wait}秒後重試 ({attempt+1}/{max_retries})...", file=sys.stderr)
                _time.sleep(wait)
                continue
            r.raise_for_status()
            break
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
    # Strip code fences (multiline safe)
    json_text = re.sub(r"^```(?:json)?\s*\n?", "", json_text, flags=re.MULTILINE)
    json_text = re.sub(r"\n?```\s*$", "", json_text.strip())
    json_text = json_text.strip()

    try:
        return json.loads(json_text)
    except json.JSONDecodeError:
        pass

    # Strategy 2: MiniMax sometimes returns literal newlines inside JSON strings.
    # Walk char-by-char and escape them so json.loads can succeed.
    try:
        fixed = _escape_newlines_in_json_strings(json_text)
        return json.loads(fixed)
    except (json.JSONDecodeError, Exception):
        pass

    # Strategy 3: try to extract the outermost JSON object
    m = re.search(r"\{.*\}", json_text, re.DOTALL)
    if m:
        try:
            fixed = _escape_newlines_in_json_strings(m.group())
            return json.loads(fixed)
        except (json.JSONDecodeError, Exception):
            pass

    # Strategy 4: missing closing quote on the last string field before '}'
    # MiniMax sometimes truncates the response and drops the final '"}'
    try:
        stripped = json_text.rstrip()
        if stripped.endswith("}") and not stripped.endswith('"}'):
            candidate = stripped[:-1].rstrip() + '"}'
            fixed = _escape_newlines_in_json_strings(candidate)
            return json.loads(fixed)
    except (json.JSONDecodeError, Exception):
        pass

    # Strategy 5: regex-based field extraction — pull out individual fields
    # when json.loads fails on the whole object
    result = _extract_fields_by_regex(json_text)
    if result and result.get("article"):
        print("[info] 使用 regex 提取 JSON 欄位", file=sys.stderr)
        return result

    # Last resort: treat entire raw_text as article body
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
    channel_yaml = metadata.get('channel', 'Unknown').replace('"', '\\"')
    title_yaml = metadata.get('title', 'Unknown').replace('"', '\\"')

    frontmatter = f"""---
type: yt_article
date: {today}
source: YouTube
youtube_url: {youtube_url}
channel: "{channel_yaml}"
video_title: "{title_yaml}"
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

    print(f"[5/5] 簡轉繁 + 儲存文章...")
    # OpenCC s2tw: 簡體→繁體（字形轉換）
    article_data["title"] = _S2TW.convert(article_data.get("title", ""))
    article_data["article"] = _S2TW.convert(article_data.get("article", ""))
    article_data["tags"] = [_S2TW.convert(t) for t in article_data.get("tags", [])]
    # OpenCC 會把「台」轉成「臺」，但台灣日常用「台」
    for key in ("title", "article"):
        article_data[key] = article_data[key].replace("臺", "台")
    filepath = save_article(article_data, metadata, youtube_url, OUTPUT_DIR)
    print(f"      已儲存: {filepath}")

    return str(filepath)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python yt_to_article.py <YouTube URL>")
        sys.exit(1)
    result = main(sys.argv[1])
    print(f"\n完成！文章已儲存至：{result}")
