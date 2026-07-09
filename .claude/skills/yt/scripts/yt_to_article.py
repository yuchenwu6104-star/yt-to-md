"""YouTube 影片 → 深度洞察文章

抓取 YouTube 字幕，透過 MiniMax M3 API 生成繁體中文深度分析文章，
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

# CJK ideograph ranges for pangu spacing (excludes punctuation like 「」，。)
_CJK = (
    r"一-鿿"    # CJK Unified Ideographs
    r"㐀-䶿"    # CJK Extension A
)
_RE_CJK_THEN_ASCII = re.compile(f"([{_CJK}])([A-Za-z0-9`$%])")
_RE_ASCII_THEN_CJK = re.compile(f"([A-Za-z0-9`%!?.)])([{_CJK}])")


def _add_pangu_spacing(text: str) -> str:
    """Add a space between CJK and ASCII characters for better readability.

    Skips lines that are YAML frontmatter or markdown links.
    """
    lines = text.split("\n")
    result = []
    in_frontmatter = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if i == 0 and stripped == "---":
            in_frontmatter = True
            result.append(line)
            continue
        if in_frontmatter:
            if stripped == "---":
                in_frontmatter = False
            result.append(line)
            continue
        line = _RE_CJK_THEN_ASCII.sub(r"\1 \2", line)
        line = _RE_ASCII_THEN_CJK.sub(r"\1 \2", line)
        result.append(line)
    return "\n".join(result)

# ---------------------------------------------------------------------------
# 設定：載入 ytkit.config（單一來源；import 時即載入 repo 根 .env）
# ---------------------------------------------------------------------------

for _p in Path(__file__).resolve().parents:
    if (_p / "ytkit" / "config.py").exists():
        sys.path.insert(0, str(_p))
        break
from ytkit import config  # noqa: E402

# 舊機器相容回退：原本綁死讀的 taiwan_stock_dashboard .env（Mac 無此檔即略過）
config.load_env_file(
    Path(r"C:\Users\wukee\OneDrive\文件\clon資料\taiwan_stock_dashboard\美股資料\.env")
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MINIMAX_BASE_URL = config.minimax_base_url()
MINIMAX_API_KEY = config.minimax_api_key()
MINIMAX_MODEL = config.minimax_model()

# 落檔位置：YT_OUTPUT_DIR 優先，未設則回退 <repo>/output/
OUTPUT_DIR = config.output_dir()

# Max transcript characters per MiniMax call
MAX_TRANSCRIPT_CHARS = 60_000

# Directory for saving English transcripts alongside articles
TRANSCRIPT_DIR = OUTPUT_DIR

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
        r"(?:live/)([a-zA-Z0-9_-]{11})",
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
    """Fetch transcript using youtube-transcript-api with yt-dlp fallback.

    Returns (transcript_text, language_code).
    Tries zh-TW → zh-Hant → zh → en → first available.
    Falls back to yt-dlp auto-captions when the API rejects the request.
    """
    from youtube_transcript_api import YouTubeTranscriptApi

    ytt_api = YouTubeTranscriptApi()

    preferred_langs = ["zh-TW", "zh-Hant", "zh", "en"]

    try:
        try:
            fetched = ytt_api.fetch(video_id, languages=preferred_langs)
            lang = fetched.language_code if hasattr(fetched, "language_code") else "unknown"
        except Exception:
            transcript_list = ytt_api.list(video_id)
            available = list(transcript_list)
            if not available:
                raise RuntimeError(f"影片 {video_id} 沒有可用的字幕")
            fetched = available[0].fetch()
            lang = available[0].language_code if hasattr(available[0], "language_code") else "unknown"

        lines = []
        for snippet in fetched:
            text = snippet.text if hasattr(snippet, "text") else snippet.get("text", "")
            lines.append(text)
        return "\n".join(lines), lang
    except Exception as api_err:
        print(f"[warn] youtube-transcript-api 失敗 ({type(api_err).__name__})，改用 yt-dlp fallback", file=sys.stderr)
        try:
            return _fetch_transcript_via_ytdlp(video_id)
        except Exception as ytdlp_err:
            print(f"[warn] yt-dlp 字幕失敗 ({ytdlp_err})，改用本地 Whisper 轉錄", file=sys.stderr)
            return _fetch_transcript_via_whisper(video_id)


def _fetch_transcript_via_ytdlp(video_id: str) -> tuple[str, str]:
    """Fallback: download auto/manual captions via yt-dlp and parse VTT."""
    import tempfile
    import glob

    url = f"https://www.youtube.com/watch?v={video_id}"
    preferred_langs = ["zh-TW", "zh-Hant", "zh", "en"]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        for lang in preferred_langs:
            for sub_flag in ("--write-subs", "--write-auto-subs"):
                subprocess.run(
                    [
                        "yt-dlp",
                        sub_flag,
                        "--sub-langs", lang,
                        "--sub-format", "vtt",
                        "--skip-download",
                        "--no-warnings",
                        "-o", str(tmp_path / "%(id)s.%(ext)s"),
                        url,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                # yt-dlp may print errors yet still write the VTT — check the file
                vtts = glob.glob(str(tmp_path / f"{video_id}*.vtt"))
                if vtts:
                    text = _parse_vtt(Path(vtts[0]).read_text(encoding="utf-8", errors="replace"))
                    if text.strip():
                        return text, lang
                    Path(vtts[0]).unlink(missing_ok=True)

    raise RuntimeError(f"影片 {video_id} 沒有可用的字幕（API 與 yt-dlp 均失敗）")


def _fetch_transcript_via_whisper(video_id: str) -> tuple[str, str]:
    """Last-resort fallback: download audio and transcribe with local Whisper.

    Covers both「影片真的沒字幕」and「YouTube 字幕端點被封（IpBlocked / 429）」——
    音訊走 googlevideo CDN，字幕端點被封時通常仍可下載。
    """
    import tempfile

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import transcribe as local_whisper

    url = f"https://www.youtube.com/watch?v={video_id}"
    with tempfile.TemporaryDirectory() as tmpdir:
        audio = local_whisper._download_audio(url, str(Path(tmpdir) / video_id))
        text, lang = local_whisper.transcribe(
            audio, None, "large-v3-turbo", config.whisper_device()
        )
    if not text.strip():
        raise RuntimeError(f"影片 {video_id} Whisper 轉錄結果為空")
    return text, lang or "whisper"


def _parse_vtt(vtt_text: str) -> str:
    """Strip VTT timestamps and tags, return plain transcript text."""
    lines = []
    seen = set()
    for raw in vtt_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:") or line.startswith("NOTE"):
            continue
        if "-->" in line:
            continue
        if re.match(r"^\d+$", line):
            continue
        line = re.sub(r"<[^>]+>", "", line)
        line = re.sub(r"&amp;", "&", line)
        line = re.sub(r"&lt;", "<", line)
        line = re.sub(r"&gt;", ">", line)
        line = line.strip()
        if not line or line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 2b. Fetch English transcript for reference (always saved alongside article)
# ---------------------------------------------------------------------------

def fetch_english_transcript(video_id: str) -> str | None:
    """Always fetch English transcript for cross-referencing. Returns None if unavailable."""
    from youtube_transcript_api import YouTubeTranscriptApi

    ytt_api = YouTubeTranscriptApi()
    try:
        fetched = ytt_api.fetch(video_id, languages=["en"])
        lines = []
        for snippet in fetched:
            text = snippet.text if hasattr(snippet, "text") else snippet.get("text", "")
            lines.append(text)
        return "\n".join(lines)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 2c. Split helper for long transcripts
# ---------------------------------------------------------------------------

def _find_split_point(text: str, target: int, window: int = 2000) -> int:
    """Find nearest paragraph break to target position."""
    for offset in range(0, window):
        for pos in (target + offset, target - offset):
            if 0 < pos < len(text) and text[pos:pos + 2] == "\n\n":
                return pos
    for offset in range(0, window):
        for pos in (target + offset, target - offset):
            if 0 < pos < len(text) and text[pos] == "\n":
                return pos
    return target


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

        chapters = data.get("chapters") or []
        chapters_text = ""
        if chapters:
            parts = []
            for ch in chapters:
                start = int(ch.get("start_time", 0))
                mm, ss = divmod(start, 60)
                parts.append(f"{mm:02d}:{ss:02d} {ch.get('title', '')}")
            chapters_text = "\n".join(parts)

        return {
            "title": data.get("title", "Unknown"),
            "channel": data.get("channel") or data.get("uploader") or "Unknown",
            "upload_date": upload_date,
            "duration_seconds": data.get("duration", 0),
            "description": (data.get("description", "") or "")[:1000],
            "chapters": chapters_text,
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
  - ⚠️ **嚴禁張冠李戴**：不要根據職銜或角色猜測中文名。字幕裡寫的英文名就是那個人，不要用你認為「更有名」的同職位人物替換。例如字幕寫 "Ambassador Alexander Yui" 就是俞大㵢，不是吳釗燮；字幕寫 "CEO John Smith" 就用 John Smith，不要換成你知道的另一位 CEO。如果你不確定某個英文名對應哪個中文名，直接保留英文名。
  - ⚠️ **頻道主／影片主角的本名以影片 metadata（頻道名、影片標題、描述）為準，不要信字幕的語音轉寫拼法**：自動字幕常把人名聽走樣（Paffrath 聽成 Praath、Cembalest 聽成 Semlas）。字幕拼法查無此人、又無法從 metadata 確認時，寧可只寫頻道名或「主持人／來賓」，不要照抄可疑拼法，更不要腦補成讀音相近的名人。
- **地名**：台灣讀者熟悉的用中文（美國、日本、台灣、亞利桑那州）；不熟悉的城市或地區直接用英文，例如「Chandler」「Hsinchu」，不要音譯成「錢德勒」「新竹」。
- **公司/機構名**：有公認中文名的用「中文（English）」，例如「台積電（TSMC）」「輝達（Nvidia）」。沒有公認中文名的直接用英文，例如「Amkor」「ASE」。
- **技術名詞**：保留英文原名，可在首次出現時加中文解釋，例如「CoWoS（Chip on Wafer on Substrate，一種 2.5D 封裝技術）」。之後直接用英文縮寫。
- **絕對禁止**：不要把英文專有名詞硬翻成中文音譯。寧可保留英文，也不要創造讀者看不懂的音譯。

## 翻譯品質（當原始字幕非中文時——英文、日文、韓文等——此節極為重要）

你的讀者是台灣的投資研究者，他們期待的是**專業、流暢、自然的繁體中文**，不是逐字硬翻。

⚠️ **引述翻譯規則**：講者的直接引述必須翻譯為中文，「」框住的內容必須是中文句子，禁止直接貼上原文整句（英文、日文、韓文等任何非中文）。但句中的專有名詞（人名、公司名、技術術語）保留英文，不要硬翻。
- ✅ 正確：「Mythos 的網路戰能力已經危險到，每次你要求它逃離安全沙箱並想辦法傳訊息給你，它幾乎都能做到。」
- ❌ 錯誤（貼英文原句）：「『anytime they try and give it a task like, "Hey, escape this secure sandbox and find a way to send me a message." It will almost always do so.』」
- ❌ 錯誤（貼日文原句）：「電源がいらないセンサーなんです。どんなセンサーでもぶつけようとしてるんですけども」——整段日文假名沒翻，嚴禁。應譯成：「這是一種不需要電源的感測器，基本上想對應任何一種感測器。」
- ❌ 錯誤（貼韓文原句）：「부품이 아니라 무기가 된 메모리 시장」——韓文諺文沒翻，嚴禁。應譯成：「記憶體已從零件變成武器。」
- ❌ 也是錯誤（過度翻譯）：「密索斯的網路戰能力已經危險到...」（Mythos 不應音譯）

翻譯原則：
1. **意譯優先，不要逐字直譯**：英文的句構和中文不同，翻譯時必須重組句子結構，讓中文讀起來自然。例如 "The amount of silicon they can put into a data center is limited by the amount of power" 不要譯成「他們可以放進資料中心的矽數量受到他們可用功率的限制」，而應該譯成「資料中心能容納多少晶片，取決於可用的電力」。
2. **避免翻譯腔**：不要出現「這是一個...的問題」「在...的情況下」「基於...的原因」這類生硬的翻譯句式。用台灣人日常會說的方式表達。
3. **技術語境要準確**：silicon 在半導體語境下是「矽晶片」或「晶片」，不是「矽」；package 是「封裝」不是「包裝」；die 是「晶粒」或「晶片」；bump 是「凸塊」；power 在晶片語境是「功耗」，在資料中心語境是「電力」。根據上下文選擇正確的翻譯。
4. **引述的翻譯要自然**：講者的原話翻成中文後，要讀起來像一個中文母語者在說話，不是像在讀翻譯稿。可以適度調整語序和用詞，但不能改變原意。
5. **專有名詞保留英文**：人名、公司名、技術術語保留英文原名，不要音譯。這條規則優先於翻譯規則——寧可在中文句子裡夾帶英文專有名詞，也不要創造讀者看不懂的音譯。



⛔ **最高優先級格式鐵則（凌駕「保留原話」原則）**：
1. 所有講者引述一律翻成自然繁體中文，用「」框住。**即使為了保留原意，也嚴禁輸出任何非中文整句（英文、日文、韓文等外語一律禁止）**；「」內只能是中文（人名、公司名、技術術語等專有名詞除外）。**尤其嚴禁整段日文假名（ひらがな/カタカナ）或韓文諺文（한글）原樣照貼**。
2. **嚴禁使用 `>` markdown 引用塊**呈現講者原話。講者原話只能用「」。`>` 僅保留給極少數編者摘要。
3. 若原話是英文、日文、韓文等任何外語，一律先在腦中翻成中文再寫進「」，不要先貼原文整句。

## 輸出 JSON 格式（不要輸出任何其他內容）

{
  "title": "文章標題（論點導向，不超過30字，例如：Hassabis：AGI 五年內實現的可能性非常高）",
  "tags": ["標籤1", "標籤2", "標籤3"],
  "filename_keywords": "2到3個關鍵字用底線連接，例如：AGI_DeepMind_運算力",
  "topics": ["主題段落1", "主題段落2", "..."],
  "article": "完整的 markdown 文章內容（不包含標題，從導言開始）"
}

## 文章結構要求

### 主題盤點（寫 article 之前先填 topics 欄位）
- 動筆寫文章之前，先盤點這部影片談了哪些主題段落，列進 topics：影片資訊有章節標記時直接以章節為基準（瑣碎章節可合併），沒有章節就通讀逐字稿自行歸納
- article 正文必須讓 topics 裡的每個主題至少有一個對應段落。不可以挑幾個主題寫、其他略過
- 次要主題可以合併成一段簡短處理，但不能整個消失

### 導言（1-2 段）
- 第一段：介紹講者/受訪者是誰——身份、職位、代表性成就。讓讀者知道「這個人是誰、為什麼該聽他說話」。
- 第二段：用 1-3 句話說明這個影片的核心問題或投資啟示，直接切入主題。
- ⚠️ 導言的背景資訊（本名、職稱、頭銜、訂閱數、成就）只能寫字幕或影片 metadata 撐得起的內容；不確定的背景寧可不寫，禁止憑記憶補。導言是憑空捏造的高發區，這裡的每個事實都要能指出出處。

### 正文（6-15 個 ## 小標題段落）

小標題必須是「論點式」，直接點出該段的核心觀點（例如：`## Scaling Laws 尚未觸頂`、`## 運算力仍是最大瓶頸`），不要用文學式標題（例如：`## 一場沒有將軍的圍棋`）。段落核心若有具體數字（目標價、漲幅、估值），把數字放進小標題，數字比形容詞更有力。

每段基本結構：串接句 → 講者原話（大段引述）→ 如有必要再補 1 句脈絡。串接句是「帶讀者進入引述的背景」，不是「引述的預告」——當串接要補的對照數字／背景跟這段引述講的不是同一件事時，串接只講那個對照／背景，然後直接「他說：」，**不要在串接裡順便把引述的論點也講一遍**（那就是下面禁止的複述）。

**選材原則（文章精不精彩，九成取決於你選了哪些原話）：**
- **引述比例必須達到 60-70%**：每段的主體是講者的直接引述，用「」框住
- 同一個論點，講者有平淡的說法也有生動的說法時，引生動的那段。講者的比喻、具體故事、反問、俏皮話是原文的一部分，必須收進來，不是可刪的裝飾
- 訪談中的關鍵問答保留一來一往的形式：主持人問：「……」來賓答：「……」。不要把對話壓成單人陳述，訪談的張力常在問答之間
- 引述要盡量完整，不要把講者一段完整的論述拆成碎片或用自己的話重新包裝
- 講者對同一主題有多段發言，依序完整呈現，中間用簡短串接語連接

**串接原則（你自己寫的句子只能載「事實」，不能載「演出」）：**
- 串接句的正當功能是「事實性鋪陳」：交代背景、點出這段話在回應什麼問題、補上對照數字。有資訊量的串接讓引述之間有敘事連貫，應該寫
  - ✅「主持人接著問到點陣圖可能的變化。她回答：」
  - ✅「三月的點陣圖還顯示今年降息一碼，他的判斷不同。他說：」
  - ✅ 最簡形式「Peter 說：」「程凱補充：」永遠可用
- **禁止複述緊接引述的內容（同話講兩遍，最常犯，務必根除）**：串接句不可以把它下面那句「」引述的內容用第三人稱先講一遍。串接句只交代「背景、在回應什麼問題、對照數字」，講者說了什麼留給引述本身講。若串接句和緊接的引述講的是同一組要點、同樣的數字、同樣的順序，就是複述——刪掉複述的部分，只留脈絡或提問，或直接用最簡形式「他說：」。
  - ❌（串接複述了引述）：`Ritter 指出，當估值逼近 2 兆美元，未來每年需要約 1,000 億美元稅後淨利才能在 20 倍本益比下支撐。他說：「……當估值逼近 2 兆美元，要在 20 倍本益比下撐住，公司每年要有 1,000 億美元的稅後淨利……」`
  - ✅（串接只給脈絡）：`談到 SpaceX 逼近 2 兆美元的估值該如何支撐，Ritter 說：「……當估值逼近 2 兆美元，要在 20 倍本益比下撐住，公司每年要有 1,000 億美元的稅後淨利……」`
  - 判準要**逐句**跑，不是整段一起看：把串接句和緊接引述並排，串接裡**任何一句／子句**只要它的內容（要點、數字、順序）在下面引述裡已經有了，那一句就是複述，單獨砍掉。
  - ⚠️ **混血串接是最大漏洞（務必根除）**：就算串接同段還有合法的獨有資訊（對照數字、背景），也不代表沒有複述——只要其中有一句在預告引述的論點，就砍那一句、只留獨有的那部分。整段因為含真數字而通過「刪了會少資訊」測試，會讓複述那一句搭便車過關，這正是過去漏抓的原因。
  - ❌（混血：盈餘數字合法，但又預告了引述的季節性論點）：`Lee 回顧 2026 是連續第四年雙位數漲幅，歷史上連漲三年後第四年通常仍偏強。年初盈餘估 350，如今上修到 400，本益比反而降到 18.4。他說：「2026 正成為第四個雙位數漲幅的年份……連漲三年後第四年通常仍相當穩健……」`
  - ✅（串接只留盈餘對照，季節性論點整個交給引述）：`年初 S&P 2027 盈餘估約 350 美元，如今上修到 400，本益比反而從 19.4 降到 18.4，漲了 9% 後更便宜。他說：「2026 正成為第四個雙位數漲幅的年份……連漲三年後第四年通常仍相當穩健……」`
- **禁止在引述前加描述性過渡句或語氣評價**，例如「他把話說得很直接」「她用一個生動的比喻說明」「Peter 強調」「Clark 特別指出」。串接句不可以替講者的話打分、形容語氣、預告精彩度
- **禁止「舞台指示／旁白」式串接（最常犯，務必根除）**：不要描寫對話的動作、節奏、戲劇性，或你自己的導演視角。鬥嘴段最容易犯，因為沒有事實可補，模型就改去報幕。以下這類一律禁止：
  - ❌ 描寫語氣／動作：「Ian 笑著接：」「Ian 順著接：」「Tobias 馬上搭腔：」「Tobias 馬上吐槽：」「Tobias 再補一刀：」「Tobias 馬上接梗：」「Ian 苦笑：」
  - ❌ 戲劇性／畫面感：「Ian 補了最後一刀：」「Ian 補了一個畫面：」「Tobias 補了一個細節：」
  - ❌ 描寫對話走位：「Ian 接著把方向拉回科技業：」「Ian 又把梗接到 F1：」
  - ❌ 替講者的表達打分：「Tobias 把數字講得更具體：」「Tobias 幫忙把這句話講得更直白：」
  - ❌ 報幕用語（使用者明令零容忍，最常復發）：「補了一句」「補了一個」「補一刀」「笑著接」「順著接」「馬上吐槽」「話鋒一轉」「切入核心」這類描寫對話動作／節奏的旁白一律禁止，改用中性「說／接著說」或最簡並列
  - ❌ 用「很直白／很直接／相當直接／講得更白」形容講者怎麼講話：直接寫他說了什麼，不要先替語氣打分
  - 判準：把串接句遮起來只看引號內的話，笑點和張力還在嗎？在，那旁白就是多餘的。鬥嘴的喜感住在引號裡，不是旁白裡。
- **引述動詞只能用中性詞**：引述前的動詞只准用「說、表示、指出、提到、認為、補充、回答、問、接著說」這幾個。**嚴禁使用帶評價、形容語氣或描寫動作的引述動詞**，包括但不限於：坦言、坦承、坦率地說、講得很坦白、直言、更直接地說、講得更白、一針見血、透露、爆料、強調、不諱言、語重心長地說、意味深長地說、笑著接、順著接、馬上搭腔、馬上吐槽、再補一刀、補了最後一刀、補了一個畫面、把數字講得更具體、把這句話講得更直白、把方向拉回、開玩笑、笑說、打趣、話鋒一轉、切入核心。這些動詞等於先替講者的話打分或替畫面加戲，再讓讀者看引述，會擋在讀者和原話之間。讓引述自己說話。
- **快速來回的鬥嘴用「對話直述模式」**：當一段是純粹你來我往、沒有事實脈絡可補時，不要硬塞串接句，改用最簡並列讓兩句話自己對撞：
  - ❌（加戲）`Ian 笑著接：「我想說全是 SAP HANA。」Tobias 馬上搭腔：「我本來也要說俄羅斯人和 SAP HANA。」`
  - ✅（直述）`Ian 說：「我想說全是 SAP HANA。」Tobias 接著說：「我本來也要說俄羅斯人和 SAP HANA。」`
  - 同一段密集對話時，連「說」都可省的更乾淨形式：`Ian：「……」Tobias：「……」`
- **多人對談的歸屬紀律（歸屬錯誤是硬失敗，與數字錯誤同級）**：每句引述掛在誰名下，只能依字幕裡的說話者線索判定——`>>` 交替標記、講者自稱、互相稱名、上下文接話——嚴禁依「誰比較有名」「誰常講這類話」腦補。字幕線索不足、無法確定是誰說的，就寫「節目中提到」「兩人都同意」這類不指名的寫法，禁止硬掛人名。**嚴禁把兩位講者的話縫成同一段「」引述**：對話中一人接話，就拆成兩段引述各自具名。引述內若出現第三人稱線索（"he's saying"、「Elon 說會的」），代表這段是某人在轉述別人，不是被轉述者本人在說話，不要標成本人引述。
- **禁止形容講者的問題或觀點**：不要寫「他丟出一個很尖的問題」「這是一個饒有深意的觀點」「他描述了一個令人不寒而慄的場景」這類評價。直接寫「他問：」「他的觀點是：」「他舉了一個例子：」

### 結語（1 段）
- 2-3 句平實語句收尾，不要寫金句式總結（「X 不僅是 A，更是 B」這類否定式排比）
- 不要用「首先...其次...第三」的三段式結構
- ⚠️ 結語只准總結正文已經出現的內容，嚴禁引入正文沒有的數據、主題或論點。結語提到的每個事實都必須能在上文找到；想放進結語的內容若正文沒有，先回頭補正文段落，不要只在結語出現。

### 格式規範
- 總字數：3000-8000 字（視原始內容長度而定，寧可多寫也不要遺漏重要觀點）
- 不要使用粗體標記短語或概念。只在數據列表中使用粗體（例如指數名稱、金額）
- 講者原話用「」呈現，不使用 > 引用塊（引用塊保留給編者評論或特別重要的一句話摘要）

### 風格禁忌（非常重要，每一條都必須遵守）
以下禁令管的是你自己寫的文字（導言、串接句、小標題、結語）。講者原話裡出現這些詞照譯，不要替講者降溫。
- 不要大量使用破折號（——），改用逗號或句號
- 不要用誇大形容詞：「前所未有的」「令人震驚的」「天壤之別」「至關重要」「開創性的」「驚人的」一律禁用
- 不要用三段式列舉（A、B、C 三項並列），改為兩項或四項；但講者真的列了三項就照寫三項，嚴禁為了湊格式增刪內容
- 不要用「此外」「值得注意的是」「更重要的是」等 AI 填充短語
- 不要用「重新框定」句型當推進手段：「不是 A，而是 B」「不僅是 A，更是 B」「表面上是 A，深層是 B」「看似 A，其實 B」「你以為 A，其實 B」「真正的問題不是 A，而是 B」「關鍵不在於 A，而在於 B」「與其說 A，不如說 B」。這些句子多半是把同一件事換個框架再講一遍，沒有新資訊。判準：把前半句遮掉只留 B，讀者沒有任何損失，就直接講 B；只有前半句真的在糾正讀者會有的誤解（範圍限定、機制對比，例如「這並非所有變壓器都拉到這個長度，而是大型發電設施的某些核心設備」）才可以用。講者親口說的照譯，不受此限
- 不要寫場景描寫式的開場（「在矽谷某棟不起眼的辦公樓裡...」「2026 年的某個清晨...」）"""


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


def _strip_model_artifacts(text: str) -> str:
    """Remove model artifacts that can leak into the article via the regex
    extraction fallback: <think>/<thinking> blocks and stray fragments before
    the first heading when an unclosed think tag swallows the prefix."""
    text = re.sub(
        r"<think(?:ing)?>.*?</think(?:ing)?>\s*", "", text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    m = re.search(r"<think(?:ing)?>", text, re.IGNORECASE)
    if m:
        # Unclosed think tag: drop from the tag to the first markdown heading
        rest = text[m.start():]
        h = re.search(r"(?m)^#{1,6} ", rest)
        text = text[:m.start()] + (rest[h.start():] if h else "")
    return text.strip()


def _ascii_letter_ratio(s: str) -> float:
    letters = sum(1 for c in s if c.isascii() and c.isalpha())
    return letters / max(len(s), 1)


# 通用英文縮寫／詞彙（是術語不是專名），實體對帳閘門略過，避免誤報。
_ENTITY_STOPWORDS = frozenset({
    "the", "and", "for", "with", "that", "this", "from", "into", "your",
    "ai", "agi", "ml", "llm", "llms", "gpu", "gpus", "cpu", "tpu", "api", "apis",
    "ceo", "cfo", "cto", "coo", "gdp", "ipo", "etf", "roi", "kpi", "okr",
    "saas", "b2b", "b2c", "iot", "faq", "crm", "erp", "seo", "vc", "pe",
    "usa", "us", "uk", "eu", "un", "ok", "ux", "ui", "ev", "evs", "vr", "ar",
    "q1", "q2", "q3", "q4", "r&d", "ceos", "cios", "kyc", "wto", "wef",
    "youtube", "podcast", "podcasts",  # 平台/頁尾用語，非專名
})


def _fabricated_english_entities(article: str, transcript: str, exempt: str = "") -> list:
    """找出文章裡有、但字幕完全對不上的英文專名（疑似 /yt 憑記憶捏造）。

    中文文章裡成串的大寫英文幾乎必是專名（人名/機構/benchmark/產品），不像
    英文文章會有句首大寫的普通字，所以這裡只掃英文 token。三層放行把誤報壓低：
    子字串命中、連字號/點分段逐段命中、difflib 模糊命中（容忍 whisper 同音誤字）。
    近未來情境的虛構產品名（GLM 5.2、Mythos）只要字幕對得上就放行；要擋的是
    連字幕都沒有的（Iridium、SWE-bench）。見記憶 yt-fabricates-proper-nouns。

    exempt：頻道名＋影片標題等已知 metadata，這些 token（含其首字母縮寫，如
    Special Competitive Studies Project→SCSP）一律放行，免得頻道名自己警告自己。
    """
    import difflib

    tl = transcript.lower()
    twords = set(re.findall(r"[a-z0-9]+", tl))
    # 已知 metadata 豁免集：各 token + 整串去空格 + 每個多詞片語的首字母縮寫。
    ex_words = set(re.findall(r"[a-z0-9]+", exempt.lower()))
    ex_squashed = re.sub(r"[^a-z0-9]", "", exempt.lower())
    for phrase in re.findall(r"[A-Za-z][A-Za-z .&'-]+", exempt):
        ws = re.findall(r"[A-Za-z]+", phrase)
        if len(ws) >= 2:
            ex_words.add("".join(w[0] for w in ws).lower())  # 首字母縮寫 SCSP
    # 去空格版：字幕常被逐字稿/自動字幕切開（chat gpt、tik tok、co wos），
    # 比對去掉所有非英數字元的連續字串，才不會把 ChatGPT/TikTok/CoWoS 誤判成捏造。
    tl_squashed = re.sub(r"[^a-z0-9]", "", tl)
    # 掃描前先剝掉 YAML frontmatter（youtube_url、video_title 等 metadata 不該比對）、
    # 「原始影片」參照行、以及所有 URL（網址裡的 youtube、影片 ID 都是雜訊）。
    body = re.sub(r"\A---\n.*?\n---\n", "", article, count=1, flags=re.DOTALL)
    body = re.sub(r"https?://\S+", "", body)
    scan = "\n".join(l for l in body.splitlines() if "原始影片" not in l)
    flagged, seen = [], set()
    for tok in re.findall(r"[A-Z][A-Za-z0-9]*(?:[-'.&][A-Za-z0-9]+)*", scan):
        norm = tok.lower()
        bare = re.sub(r"[-'.&]", "", norm)
        if norm in seen or len(bare) < 4 or norm in _ENTITY_STOPWORDS:
            continue
        seen.add(norm)
        if norm in ex_words or (bare and bare in ex_squashed):  # 頻道名/標題 metadata
            continue
        if norm in tl or bare in tl_squashed:           # ① 子字串／去空格命中
            continue
        parts = [p for p in re.split(r"[-'.&]", norm) if p]
        if parts and all(p in tl for p in parts):       # ② 分段逐段命中
            continue
        best = max(                                     # ③ 模糊命中（whisper 誤字）
            (difflib.SequenceMatcher(None, bare, w).ratio()
             for w in twords if abs(len(w) - len(bare)) <= 2),
            default=0.0,
        )
        # 0.80 容忍 whisper 同音誤字（DeepSeek/DeepSeq=0.80、Cerebras/Cerebrus=0.88），
        # 真捏造（Iridium/Fidelity=0.40、SWE-bench/benchmark=0.59）離這條線還很遠。
        if best >= 0.80:
            continue
        flagged.append(tok)
    return flagged


def format_violations(article: str) -> list:
    """Check a generated article against the SYSTEM_PROMPT 格式鐵則.

    Returns human-readable violation descriptions (empty list = pass).
    Mirrors the checks previously only run in _m3_test/ab_test_v3.py.
    """
    issues = []
    # An offending quote is English-majority AND contains a run of 4+
    # space-separated English words (i.e. an English clause, not a list of
    # proper nouns like 「Sam、Dario、Demis」 or a term like 「vibe coding」).
    eng_clause = re.compile(r"(?:[A-Za-z][A-Za-z'.,]*\s+){3,}[A-Za-z]")
    eng_quotes = [
        q for q in re.findall(r"「([^「」]{10,})」", article)
        if _ascii_letter_ratio(q) > 0.5 and eng_clause.search(q)
    ]
    if len(eng_quotes) >= 3:
        issues.append(
            f"{len(eng_quotes)} 段「」引述以英文為主（鐵則 1：引述必須翻成中文），"
            f"例如：「{eng_quotes[0][:40]}...」"
        )
    # 未翻譯的日文假名／韓文諺文引述：翻好的中文不可能含假名或諺文，故為「沒翻」的鐵證。
    # （中日共用漢字無法判別，但假名 U+3040–30FF 與諺文 U+AC00–D7A3 是非中文來源的明確標記。）
    kana_hangul = re.compile(r"[぀-ゟ゠-ヿ가-힣]")
    foreign_quotes = [
        q for q in re.findall(r"「([^「」]{10,})」", article)
        if len(kana_hangul.findall(q)) >= 3
    ]
    if foreign_quotes:
        issues.append(
            f"{len(foreign_quotes)} 段「」引述含未翻譯的日文假名／韓文諺文"
            f"（鐵則 1：引述必須翻成中文），例如：「{foreign_quotes[0][:40]}...」"
        )
    # 全文語言稽核：翻好的繁中文章不該大量含假名/諺文。
    # 這條不限「」內——也涵蓋 "…" 直引號、段落內文、標題（捕捉整篇鏡像輸出的情形，
    # 例如模型把韓文影片整篇照寫韓文）。排除「原始影片」參照行（本就保留原文標題）。
    lang_scan = "\n".join(l for l in article.splitlines() if "原始影片" not in l)
    body_kana = len(re.findall(r"[぀-ゟ゠-ヿ]", lang_scan))
    body_hangul = len(re.findall(r"[가-힣]", lang_scan))
    if body_hangul >= 5 or body_kana >= 12:
        issues.append(
            f"全文含大量未翻譯外語（諺文 {body_hangul} 字、假名 {body_kana} 字；"
            f"繁中文章應趨近 0，疑似標題/段落/直引號整段未翻譯）"
        )
    blockquotes = re.findall(r"(?m)^>\s", article)
    if len(blockquotes) > 3:
        issues.append(f"{len(blockquotes)} 行 > 引用塊（鐵則 2：講者原話只能用「」）")
    if re.search(r"[А-Яа-я]", article):
        issues.append("文章含西里爾字母（模型輸出異常）")
    if re.search(r"<think(?:ing)?>", article, re.IGNORECASE):
        issues.append("文章含 <think> 思考區塊殘留")
    if re.search(r'"(?:title|article|tags)"\s*:\s*["\[]', article):
        issues.append("文章含原始 JSON 殘留")
    from collections import Counter
    paras = Counter(
        p.strip() for p in article.split("\n\n") if len(p.strip()) >= 80
    )
    dupes = sum(1 for c in paras.values() if c > 1)
    if dupes:
        issues.append(f"{dupes} 個長段落重複出現（疑似內容拼接異常）")
    # 串接區舞台指示／替講者語氣打分（引號內講者原話豁免：先剔除「」再檢查）
    narration = re.sub(r"「[^「」]*」", "", article)
    # 報幕用語：描寫對話的動作／節奏／戲劇性，使用者明令零容忍、最常復發
    stage_phrases = (
        "補了一句", "補了一個", "補一句", "補一刀", "補了一刀",
        "補了最後一刀", "補了一個畫面", "補了一個細節",
        "補上", "補了一段", "補述", "再補一句", "再補一個",
        "笑著接", "順著接", "馬上搭腔", "馬上吐槽", "再補一刀",
        "把方向拉回", "把梗接到", "話鋒一轉", "切入核心",
        "苦笑著說", "笑著說", "笑說", "打趣", "搶話",
    )
    hit = next((p for p in stage_phrases if p in narration), None)
    if hit:
        issues.append(
            f"串接區出現舞台指示／旁白（出現「{hit}」，禁止替對話報幕，改用中性「說／接著說」）"
        )
    # 替講者語氣打分：把講者的話形容成「很直接／很直白／相當直接／講得更白」等
    editorial = re.findall(r"(?:很|相當|非常|十分|更)(?:直接|直白)", narration)
    if editorial:
        issues.append(
            f"串接區替講者語氣打分（出現「{editorial[0]}」，禁止形容講者怎麼講話，讓引述自己說話）"
        )
    # 形容講者語氣的銳利／簡潔／態度（藏在引號前那句裡）。
    # 注意：以下黑名單只是安全網；真正的規則是 system prompt 的「中性引述動詞白名單」，
    # 模型寫的當下就該只用 說／表示／指出／提到／認為／補充／回答／問／接著說。
    tone_words = (
        "尖銳", "犀利", "一針見血", "毫不留情", "不留情面", "不客氣",
        "火力全開", "很簡潔", "很乾脆", "語帶保留", "語重心長", "意味深長",
    )
    tone_hit = next((w for w in tone_words if w in narration), None)
    if tone_hit:
        issues.append(
            f"串接區替講者語氣打分（出現「{tone_hit}」，禁止形容講者語氣，讓引述自己說話）"
        )
    # 白名單外的非中性引述動詞（system prompt 已明列禁用）
    nonneutral_verbs = ("坦言", "坦承", "直言", "不諱言", "爆料")
    verb_hit = next((v for v in nonneutral_verbs if v in narration), None)
    if verb_hit:
        issues.append(
            f"串接區用了白名單外的引述動詞（出現「{verb_hit}」，"
            "只准用 說／表示／指出／提到／認為／補充／回答／問／接著說）"
        )
    return issues


def _redundant_narration(article: str) -> list:
    """找出「串接句複述了緊接引述」的段落（同話講兩遍）。

    每個小節常是「串接(轉述) →「引述」」；若串接句把下面引述的內容先講一遍，
    讀者會覺得同一段話講兩次。以 CJK 2-gram 重疊 + 共同帶單位數字判定，門檻刻意
    偏高，只抓明顯複述——交代脈絡／提問的 additive 串接不該中。純警告、不觸發重生
    （複述屬內容結構問題，重生風險高，交由 humanizer 刪成純脈絡）。回傳串接句預覽。
    """
    def _bigrams(s: str) -> set:
        s = re.sub(r"[^一-鿿]", "", s)
        return {s[i:i + 2] for i in range(len(s) - 1)}

    def _nums(s: str) -> set:
        return set(re.findall(r"[0-9][0-9,.]*\s*(?:兆|億|倍|%|萬)", s))

    def _is_quote_para(p: str) -> bool:
        qs = re.findall(r"「([^「」]{15,})」", p)
        return bool(qs) and sum(len(x) for x in qs) > len(p) * 0.5

    paras = [p.strip() for p in article.split("\n\n") if p.strip()]
    hits = []
    for i in range(1, len(paras)):
        cur, prev = paras[i], paras[i - 1]
        if cur.startswith("#") or prev.startswith("#"):
            continue
        if not _is_quote_para(cur) or _is_quote_para(prev):
            continue
        quote = " ".join(re.findall(r"「([^「」]+)」", cur))
        shared_nums = _nums(prev) & _nums(quote)
        bp, bq = _bigrams(prev), _bigrams(quote)
        jac = len(bp & bq) / max(1, len(bp | bq))
        if len(shared_nums) >= 2 or jac >= 0.30:
            hits.append(prev[:50])
    return hits


def call_minimax(transcript: str, metadata: dict, part_info: str = "") -> dict:
    """Generate an article from a transcript, enforcing the format gate.

    Calls MiniMax once, runs format_violations() on the result; on failure,
    retries once with the violation list appended to the prompt, then keeps
    whichever attempt has fewer violations.

    Args:
        part_info: If non-empty, appended to the user prompt to guide split handling.
    """
    if not MINIMAX_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY 環境變數未設定。"
            "請在 .env 中設定 MiniMax Token Plan key (sk-cp-...)"
        )

    # Safety-net truncation (each split half should already be under limit)
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        print(f"[warn] 字幕仍超過 {MAX_TRANSCRIPT_CHARS} 字元，截斷尾部", file=sys.stderr)
        transcript = transcript[:MAX_TRANSCRIPT_CHARS] + "\n\n[... 字幕已截斷 ...]"

    duration_min = metadata.get("duration_seconds", 0) // 60
    part_note = f"\n\n{part_info}" if part_info else ""

    chapters_section = ""
    chapters_text = metadata.get("chapters", "")
    if chapters_text:
        chapters_section = f"\n- 章節標記：\n{chapters_text}"

    user_prompt = f"""以下是一部 YouTube 影片的逐字稿，請根據內容撰寫一篇深度洞察文章。

影片資訊：
- 標題：{metadata.get('title', 'Unknown')}
- 頻道：{metadata.get('channel', 'Unknown')}
- 發布日期：{metadata.get('upload_date', '未知')}
- 時長：約 {duration_min} 分鐘
- 簡介：{metadata.get('description', '')[:800]}{chapters_section}

逐字稿內容：
{transcript}{part_note}

請用 JSON 格式輸出（嚴格遵守 system prompt 中的格式要求）。"""

    # 初次 + 最多 2 次重試。日韓來源 MiniMax 有時整篇鏡像輸出原文，單次重試不夠，
    # 故迴路重試並保留「違規最少」的一版。
    def _finalize(result: dict) -> dict:
        # 英文專名實體對帳：純警告、不觸發重生。自動字幕對人名拼寫常很爛
        # （Calacanis、Klarman 都會對不上），若用來重生會誤刪真名；故只把「字幕
        # 查無對應」的英文專名印到 stderr，供 humanizer/監督核對。見記憶
        # yt-fabricates-proper-nouns（撈得到 Iridium、SWE-bench 這類真捏造）。
        if transcript and result:
            # 換行分隔，讓頻道名與標題各自算首字母縮寫（否則 SCSP 會併成 scspcwa…）
            exempt = f"{metadata.get('channel', '')}\n{metadata.get('title', '')}"
            sus = _fabricated_english_entities(result.get("article", ""), transcript, exempt)
            if sus:
                print(
                    "[note] 下列英文專名在逐字稿裡找不到對應，humanizer 請逐一查證"
                    "（可能是憑記憶捏造，也可能只是字幕把名字拼錯）："
                    + "、".join(sus[:12]) + ("…" if len(sus) > 12 else ""),
                    file=sys.stderr,
                )
        # 串接句複述緊接引述（同話講兩遍）：純警告、不觸發重生，交由 humanizer
        # 刪成純脈絡或最簡「他說：」。見 humanizer-zh 模式 33。
        red = _redundant_narration(result.get("article", "")) if result else []
        if red:
            print(
                "[note] 下列串接句疑似複述了緊接的引述（同話講兩遍），humanizer 請刪成純脈絡或最簡「他說：」："
                + "；".join(f"「{r}…」" for r in red[:6]) + ("…" if len(red) > 6 else ""),
                file=sys.stderr,
            )
        return result

    MAX_ATTEMPTS = 3
    best = None
    best_issues = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if attempt == 1:
            prompt = user_prompt
        else:
            prompt = user_prompt + (
                "\n\n⚠️ 你上一次的輸出違反了格式鐵則：" + "；".join(best_issues) + "。"
                "請重新輸出完整 JSON。最重要：**整篇文章（標題、導言、所有段落、引述）必須是繁體中文**，"
                "嚴禁任何非中文整句或段落（英文、日文、韓文等外語，尤其嚴禁整段日文假名或韓文諺文原樣照貼，"
                "也嚴禁用 \"…\" 或「」貼外語原句）；嚴禁 > 引用塊。"
                "專有名詞（人名、公司名、技術術語）可保留英文，"
                "但**只能用逐字稿裡實際出現的名字**——嚴禁憑記憶補出字幕沒有的"
                "機構名、benchmark、產品名（例如把講者背景、公司、評測名「腦補」成你以為的那個）；"
                "字幕沒提到確切名字時，用中性描述（如「一項評測」「一家資產管理公司」）帶過。"
            )
        cand = _request_article(prompt, metadata)
        cand["article"] = _strip_model_artifacts(cand.get("article", ""))
        cand_issues = format_violations(cand.get("article", ""))
        if not cand_issues:
            return _finalize(cand)
        if best_issues is None or len(cand_issues) < len(best_issues):
            best, best_issues = cand, cand_issues
        print(f"[warn] 第 {attempt}/{MAX_ATTEMPTS} 次格式鐵則未通過：{'；'.join(cand_issues)}",
              file=sys.stderr)
    print(f"[warn] {MAX_ATTEMPTS} 次後仍未完全通過，保留違規最少的一版", file=sys.stderr)
    return _finalize(best)


def _request_article(user_prompt: str, metadata: dict) -> dict:
    """Single MiniMax API call + JSON parsing (no format gate)."""
    import time as _time

    max_retries = 3
    with httpx.Client(timeout=httpx.Timeout(600.0, connect=30.0)) as client:
        for attempt in range(max_retries):
            try:
                r = client.post(
                    f"{MINIMAX_BASE_URL}/v1/messages",
                    headers={
                        "x-api-key": MINIMAX_API_KEY,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": MINIMAX_MODEL,
                        "thinking": {"type": "disabled"},
                        "max_tokens": 16384,
                        "system": SYSTEM_PROMPT,
                        "messages": [{"role": "user", "content": user_prompt}],
                    },
                )
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                if attempt < max_retries - 1:
                    wait = 10 * (attempt + 1)
                    print(f"[warn] MiniMax {type(e).__name__}: {e}，{wait}秒後重試 ({attempt+1}/{max_retries})...", file=sys.stderr)
                    _time.sleep(wait)
                    continue
                raise
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
# 4b. Generate article with auto-split for long transcripts
# ---------------------------------------------------------------------------

# 重試耗盡後，成稿仍含這麼多未翻譯外語（假名+諺文）即視為「翻譯失敗」，不存檔。
# 校準：乾淨繁中文章趨近 0；少量片假名專名（キオクシア 等）約 10–20；
# 整段或半篇未翻譯則動輒上百～上千。80 是「零星專名」與「成段未翻」之間的界線。
CATASTROPHIC_FOREIGN_CHARS = 80
_KANA_HANGUL_RE = re.compile(r"[぀-ゟ゠-ヿ가-힣]")


def _foreign_char_count(article: str) -> int:
    """成稿中未翻譯的日文假名／韓文諺文字數（排除保留原文的「原始影片」參照行）。"""
    scan = "\n".join(l for l in article.splitlines() if "原始影片" not in l)
    return len(_KANA_HANGUL_RE.findall(scan))


def _split_into_n(text: str, n: int) -> list[str]:
    """把逐字稿切成 n 段，盡量落在段落／換行邊界上。"""
    if n <= 1:
        return [text]
    parts = []
    start = 0
    for i in range(1, n):
        cut = _find_split_point(text, len(text) * i // n)
        if cut <= start:          # 安全：避免空段或回頭切
            cut = len(text) * i // n
        parts.append(text[start:cut])
        start = cut
    parts.append(text[start:])
    return [p for p in parts if p.strip()]


def _repair_translation(article: str, metadata: dict) -> "str | None":
    """日韓來源最後補救：把成稿殘留的假名／諺文整句翻成繁中，其餘逐字不動。
    只在硬閘門即將擋下時觸發。回傳修補後全文；失敗回 None。"""
    import time as _time
    if not MINIMAX_API_KEY:
        return None
    sys_prompt = (
        "你是繁體中文編輯。使用者給你的文章大致已是繁中，但仍殘留未翻譯的日文假名"
        "（ひらがな／カタカナ）或韓文諺文（한글）。你的唯一任務：把所有殘留的假名／"
        "諺文整句翻成自然的繁體中文，其餘內容（文章架構、標點、已是中文的部分、"
        "Markdown 標題、「」引號、英文專有名詞）逐字不動。直接輸出修好的完整文章，"
        "不要任何前言、說明、JSON 或程式碼框。"
    )
    user = f"文章如下，請把所有假名／諺文翻成繁中後，輸出完整全文：\n\n{article}"
    try:
        with httpx.Client(timeout=httpx.Timeout(600.0, connect=30.0)) as client:
            for attempt in range(2):
                try:
                    r = client.post(
                        f"{MINIMAX_BASE_URL}/v1/messages",
                        headers={
                            "x-api-key": MINIMAX_API_KEY,
                            "anthropic-version": "2023-06-01",
                            "content-type": "application/json",
                        },
                        json={
                            "model": MINIMAX_MODEL,
                            "thinking": {"type": "disabled"},
                            "max_tokens": 16384,
                            "system": sys_prompt,
                            "messages": [{"role": "user", "content": user}],
                        },
                    )
                except (httpx.TimeoutException, httpx.NetworkError):
                    if attempt == 0:
                        _time.sleep(10)
                        continue
                    return None
                if r.status_code >= 500 and attempt == 0:
                    _time.sleep(5)
                    continue
                r.raise_for_status()
                break
        data = r.json()
        text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                text = block["text"]
                break
        text = re.sub(r"^```(?:\w+)?\s*\n?", "", text.strip())
        text = re.sub(r"\n?```\s*$", "", text.strip()).strip()
        return text or None
    except Exception as e:
        print(f"[warn] 翻譯修補 pass 失敗：{e}", file=sys.stderr)
        return None


def generate_article(transcript: str, metadata: dict) -> dict:
    """生成文章。長逐字稿拆成多次 MiniMax 呼叫；日韓來源用較小的分段
    （短段落能讓 M3 不偷懶整段照貼原文）。最後對殘留假名／諺文做翻譯修補。"""
    # 來源語言偵測：原始逐字稿含大量假名／諺文 → 日韓來源
    is_jp_kr = len(_KANA_HANGUL_RE.findall(transcript)) >= 200
    # 分段目標字數：日韓來源切小段（~18k），英／中維持原本 60k 門檻
    chunk_target = 18_000 if is_jp_kr else MAX_TRANSCRIPT_CHARS
    n_parts = ((len(transcript) - 1) // chunk_target + 1) if transcript else 1
    n_parts = max(1, min(n_parts, 5))

    if n_parts == 1:
        result = call_minimax(transcript, metadata)
    else:
        print(f"      字幕共 {len(transcript)} 字元"
              f"{'（日韓來源，切小段）' if is_jp_kr else f'，超過 {MAX_TRANSCRIPT_CHARS}'}"
              f"，拆為 {n_parts} 段...")
        segments = _split_into_n(transcript, n_parts)
        n = len(segments)
        chunks = []
        for i, seg in enumerate(segments):
            if i == 0:
                info = (f"【重要】這是完整逐字稿的第 1 段（共 {n} 段）。請正常撰寫文章，"
                        "包含導言和正文段落。不要寫結語，後續段落會接在你的輸出之後。")
            elif i == n - 1:
                info = (f"【重要】這是完整逐字稿的最後一段（第 {i+1}／{n} 段）。請直接從新的 "
                        "## 段落標題開始，不要重複導言、不要再次介紹講者；可以寫結語。"
                        "這些內容會接在前面段落之後。")
            else:
                info = (f"【重要】這是完整逐字稿的中間段（第 {i+1}／{n} 段）。請直接從新的 "
                        "## 段落標題開始，不要導言、不要結語、不要重複介紹講者。"
                        "這些內容會接在前面段落之後。")
            chunks.append(call_minimax(seg, metadata, part_info=info))
            print(f"      第 {i+1}/{n} 段完成")

        merged_article = "\n\n".join(c.get("article", "") for c in chunks)
        all_tags = list(dict.fromkeys(t for c in chunks for t in c.get("tags", [])))
        result = {
            "title": chunks[0].get("title", metadata.get("title", "")),
            "tags": all_tags,
            "filename_keywords": chunks[0].get("filename_keywords", ""),
            "article": merged_article,
        }

    # 硬閘門前的補救：成稿若仍殘留大量假名／諺文，先做一次翻譯修補 pass。
    foreign = _foreign_char_count(result.get("article", ""))
    if foreign >= CATASTROPHIC_FOREIGN_CHARS:
        print(f"      [info] 成稿殘留 {foreign} 假名／諺文，啟動翻譯修補 pass...",
              file=sys.stderr)
        repaired = _repair_translation(result.get("article", ""), metadata)
        if repaired:
            rep_foreign = _foreign_char_count(repaired)
            if rep_foreign < foreign:
                result["article"] = repaired
                foreign = rep_foreign
                print(f"      [info] 修補後降為 {foreign} 假名／諺文", file=sys.stderr)

    # 硬失敗閘門：重試＋修補後仍有大量未翻譯外語 → 拋錯不存檔，留待下次重抓。
    if foreign >= CATASTROPHIC_FOREIGN_CHARS:
        raise RuntimeError(
            f"翻譯失敗：重試＋修補後成稿仍含 {foreign} 個未翻譯日文假名/韓文諺文字元"
            f"（門檻 {CATASTROPHIC_FOREIGN_CHARS}）。不存檔，本片留待下次輪巡重抓。"
        )
    return result


# ---------------------------------------------------------------------------
# 5. Format and save article
# ---------------------------------------------------------------------------

def sanitize_filename(s: str) -> str:
    """Remove or replace characters that are invalid in filenames."""
    s = s or "Unknown"
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
*本文根據 YouTube 影片內容由 AI 整理生成，僅供參考。*
"""

    output_dir.mkdir(parents=True, exist_ok=True)
    filepath.write_text(full_content, encoding="utf-8")
    return filepath


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(youtube_url: str, transcript_file: str | None = None) -> str:
    """Full pipeline: URL → transcript → article → saved file.

    If transcript_file is given (e.g. a Whisper transcript for a video whose
    subtitles are disabled), it is used directly instead of fetching subtitles,
    and is also saved alongside the article as the cross-reference 原文字幕.

    Returns the path of the saved file.
    """
    print(f"[1/6] 解析 YouTube URL...")
    video_id = extract_video_id(youtube_url)
    print(f"      影片 ID: {video_id}")

    if transcript_file:
        print(f"[2/6] 讀取本地逐字稿（whisper fallback）...")
        transcript = Path(transcript_file).read_text(encoding="utf-8").strip()
        print(f"      逐字稿長度: {len(transcript)} 字元 | 來源: {transcript_file}")
        print(f"[3/6] 以 whisper 逐字稿作為原文字幕保留...")
        en_transcript = transcript
        print(f"      原文字幕: {len(en_transcript)} 字元（完整保留，不截斷）")
    else:
        print(f"[2/6] 抓取字幕...")
        transcript, lang = fetch_transcript(video_id)
        print(f"      字幕語言: {lang} | 長度: {len(transcript)} 字元")

        print(f"[3/6] 儲存英文原文字幕...")
        en_transcript = fetch_english_transcript(video_id) if lang != "en" else transcript
        if en_transcript:
            print(f"      英文字幕: {len(en_transcript)} 字元（完整保留，不截斷）")
        else:
            print(f"      無法取得英文字幕，跳過")

    print(f"[4/6] 取得影片資訊...")
    metadata = fetch_metadata(video_id)
    print(f"      標題: {metadata['title']}")
    print(f"      頻道: {metadata['channel']}")

    print(f"[5/6] 呼叫 MiniMax API 生成文章...")
    article_data = generate_article(transcript, metadata)
    print(f"      文章標題: {article_data.get('title', 'N/A')}")

    print(f"[6/6] 簡轉繁 + 儲存文章...")
    # OpenCC s2tw: 簡體→繁體（字形轉換）
    article_data["title"] = _S2TW.convert(article_data.get("title", ""))
    article_data["article"] = _S2TW.convert(article_data.get("article", ""))
    article_data["tags"] = [_S2TW.convert(t) for t in article_data.get("tags", [])]
    # OpenCC 後處理：修正台灣慣用譯名、異體字、中英文間距
    for key in ("title", "article"):
        article_data[key] = article_data[key].replace("臺", "台")
        article_data[key] = article_data[key].replace("伯克希爾", "波克夏")
        article_data[key] = article_data[key].replace("俬", "私")
        article_data[key] = _add_pangu_spacing(article_data[key])
    filepath = save_article(article_data, metadata, youtube_url, OUTPUT_DIR)
    print(f"      文章已儲存: {filepath}")

    # Save English transcript alongside the article
    if en_transcript:
        transcript_path = filepath.with_name(filepath.stem + "_transcript.txt")
        transcript_path.write_text(en_transcript, encoding="utf-8")
        print(f"      英文字幕已儲存: {transcript_path}")

    return str(filepath)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="YouTube 影片 → 深度洞察文章")
    ap.add_argument("youtube_url", help="YouTube URL")
    ap.add_argument(
        "--transcript-file",
        default=None,
        help="本地逐字稿 .txt（無字幕影片的 whisper fallback，跳過抓字幕步驟）",
    )
    cli_args = ap.parse_args()
    result = main(cli_args.youtube_url, cli_args.transcript_file)
    print(f"\n完成！文章已儲存至：{result}")
