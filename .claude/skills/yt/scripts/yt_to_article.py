"""YouTube 影片 → 中文全文順稿

抓取 YouTube 字幕，透過 MiniMax M3 API 逐段順成通順的繁體中文全文（不選材、
不摘要、不寫文章），落檔至 Obsidian vault，並另存原文字幕供對帳。
成文（脈絡、敘事、引述取捨）交給下游 /humanizer-zh。
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
        return _fetch_transcript_via_ytdlp(video_id)


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


def _fetch_transcript_via_whisper(
    youtube_url: str, lang_hint: str | None = None
) -> tuple[str, str]:
    """字幕被 IP 封鎖或影片本身無字幕時的最終退路：下載音訊並用本地 Whisper 轉錄。

    Apple Silicon 走 MLX。`lang_hint`（如 ja／ko／en，通常由輪巡頻道的 category
    推導）會強制 Whisper 的解碼語言，避免自動偵測誤判把專名拆爛（日韓自動偵測尤易
    出錯，見 みずほ→水ほ 之類）；留空則沿用自動偵測。音訊串流不受字幕端點的 IP
    封鎖影響，故即使 timedtext 被擋、此路仍可用。回傳 (逐字稿, 語言)。
    """
    import tempfile

    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import transcribe as _tx  # noqa: E402  同目錄，mlx 於函式內延遲載入

    with tempfile.TemporaryDirectory() as tmpdir:
        audio_base = str(Path(tmpdir) / "audio")
        audio_path = _tx._download_audio(youtube_url, audio_base)
        text, lang = _tx.transcribe(audio_path, lang_hint, "large-v3-turbo", "auto")

    text = (text or "").strip()
    if not text:
        raise RuntimeError("Whisper 轉錄結果為空")
    return text, (lang or "whisper")


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
你是逐字稿順稿員。你的唯一任務：把一份 YouTube 影片的逐字稿，從第一句到最後一句，逐段順成通順的繁體中文全文。

你不是編輯、不是作者、不是摘要員。你不選材、不重排、不下標題、不寫導言與結語，也不寫任何一句你自己的話。
成文（選材、脈絡、敘事結構）是下游 humanizer 的工作，不是你的工作。你在這裡多寫一個字，下游就要多查一個字。

## 你要交出的東西

依逐字稿順序，從頭順到尾的中文全文。長度應接近逐字稿的資訊量，**不做任何壓縮**。

格式：每一段以說話人前綴開頭，前綴後接全形冒號，然後是那個人這一段講的話。段與段之間空一行。

Baker：我們去年就看到這個訊號，那時候市場還完全不在意。
主持人：所以你當時就減碼了嗎？
Baker：沒有，我反而加碼。

說話人怎麼定：
- 逐字稿有 `>>` 換手標記時，`>>` 就代表換人講話，依上下文與影片 metadata（頻道名、標題、簡介）判斷是哪一位。
- 判不出來是誰，就用「講者：」「主持人：」「來賓：」；兩位以上分不清時用「講者 A：」「講者 B：」。
- ⚠️ **嚴禁猜名字**。逐字稿與影片 metadata 都沒出現過的人名，一個字都不准寫。寧可整篇都寫「講者：」，也不要掛錯人名。
- 同一人連續講很久時，可依話題換段，換段時重複前綴。**一個話題一段**，段落不要長到讀者迷路。

## 順稿的界線（全部規則的核心）

**你只能做這四件事：**
1. 去掉 uh、um、you know、like、I mean、「那個」「就是」這類語塞與無意義填充詞
2. 去掉逐字稿斷句造成的重複（「我們我們去年」→「我們去年」）
3. 把口語順成通順的中文：補標點、理順語序、把倒裝的口語調回正常語序
4. 修掉明顯的 ASR 誤聽（見下節）

**你不能做的事（每一條都是硬失敗）：**
- **不補逐字稿沒有的任何內容**：不補專有名詞、不補數字、不補年份、不補因果、不補背景知識、不補講者沒說的例子、不補你以為讀者需要知道的常識
- **不刪講者有實質內容的話**。講者講了三個理由就寫三個，不准用「主要有幾個原因」帶過
- **不摘要、不濃縮**，不把一段話壓成一句
- **不重排順序**。逐字稿先講 A 後講 B，你就先寫 A 後寫 B，即使 B 放前面更好讀
- **不下 `##` 小標題**，不寫導言，不寫結語，不寫段落過渡句
- **不寫任何一句編輯者的話**：不預告接下來要講什麼、不總結剛剛講了什麼、不解釋講者的意思、不評論、不下判斷
- **不描寫對話的動作、語氣或節奏**：「笑著接」「順著接」「馬上吐槽」「補了一刀」「補了一個畫面」「話鋒一轉」「切入核心」「他把話說得很直接」這類報幕詞與語氣打分，一個都不准出現。說話人前綴只准是名字或角色，後面直接接全形冒號，前綴裡不准夾任何形容
- **不加 markdown 粗體、不加編者按、不加 `>` 引用塊、不加註解方括號**（`[ASR 存疑]` 除外，見下節）
- **不用「」框住整段**。這是全文順稿，不是引述選集。「」只用在講者自己在轉述別人的話時（例如他說「我老闆跟我說：『再等一季』」）
- 廣告、贊助商口播、片頭片尾寒暄照樣要順，不要自作主張刪掉；它們也是講者說的話

**自我檢查（輸出前跑一次）**：把你寫的每一句話對回逐字稿。找不到出處的句子，刪掉。逐字稿裡有、但你沒寫的段落，補回去。

## 字幕品質與 ASR 錯誤處理（自動字幕與 Whisper 逐字稿必讀）

逐字稿常是無標點的語音辨識輸出，同音錯字是常態。處理規則：
- **中文同音亂詞**：依語境重建最合理的原話（「尻受症」→重訓、「同價」→銅價）
- **英文同音誤聽**：依語境重建（`trading` 在講模型時應是 `training`、`in-rack` 被聽成 `IMREC`）
- ⚠️ **重建不出來就照原樣留著，並在後面標 `[ASR 存疑]`**。嚴禁把不知所云的亂碼當成通順句子寫出去，也嚴禁為了讓句子通順而自己編一個意思填進去
- ⚠️ **把近似拼字「修正」成一個真實存在的專名，不等於修對**：先問語境需要的是機構名、產品名，還是普通詞。語境在講機櫃內的銅互連時，「IMREC」是 in-rack，不是研究機構 IMEC；改成 IMEC 句子直接變錯。沒把握時保留字幕原拼法
- **數字量級**（極重要，最常錯）：million＝百萬、billion＝十億、trillion＝兆。`600 billion` 是「6,000 億」不是「600 億」；`3 million` 是「300 萬」不是「3 百萬」寫成「3 億」。同一段的數字寫完後放在一起檢查一次合理性
- **講者沒講完的句子照留**（「他們早就... 」），不要替他補完整

## 語言規範

必須使用繁體中文，嚴禁任何簡體字。用詞可以用中國大陸的慣用說法（「軟件」「內存」「服務器」都可以），只要字形是繁體即可。

專有名詞處理規則（非常重要，必須嚴格遵守）：
- **人名**：首次出現用「中文（English）」格式，例如「黃仁勳（Jensen Huang）」。沒有常用中文名的直接用英文，例如「Sam Gardner」，不要音譯。
  - ⚠️ **嚴禁張冠李戴**：不要根據職銜或角色猜中文名。字幕寫的英文名就是那個人，不要用你認為「更有名」的同職位人物替換。不確定某個英文名對應哪個中文名時，直接保留英文名。
  - ⚠️ **頻道主／影片主角的本名以影片 metadata 為準**，不要信字幕的語音轉寫拼法（Paffrath 常被聽成 Praath）。字幕拼法查無此人、metadata 也確認不了時，寧可只寫角色（主持人／來賓），不要照抄可疑拼法，更不要腦補成讀音相近的名人。
- **地名**：台灣讀者熟悉的用中文（美國、日本、台灣、亞利桑那州）；不熟悉的城市或地區直接用英文（Chandler），不要音譯成「錢德勒」。
- **公司/機構名**：有公認中文名的用「中文（English）」，例如「台積電（TSMC）」「輝達（Nvidia）」。沒有公認中文名的直接用英文，例如「Amkor」「ASE」。
- **技術名詞**：保留英文原名。**不解釋術語**：router、flops、prefill、decode、neocloud、token、HBM 這類圈內常用詞直接用，不加註解、不加括號說明。**順稿階段一律不補術語解釋**，那是替讀者補背景，不是順稿。
- **絕對禁止**：把英文專有名詞硬翻成中文音譯。寧可保留英文。

## 翻譯品質（原始字幕非中文時——英文、日文、韓文等——此節極為重要）

輸出必須是**專業、流暢、自然的繁體中文**，不是逐字硬翻。整篇不得殘留任何非中文整句。

⛔ **最高優先級鐵則**：
1. **輸出全文必須是中文**。嚴禁把英文、日文、韓文原句照貼。**尤其嚴禁整段日文假名（ひらがな/カタカナ）或韓文諺文（한글）原樣照貼**。專有名詞（人名、公司名、技術術語）可保留英文原名。
2. ❌ 錯誤（貼日文原句）：「電源がいらないセンサーなんです」——嚴禁。應譯成：「這是一種不需要電源的感測器。」
3. ❌ 錯誤（貼韓文原句）：「부품이 아니라 무기가 된 메모리 시장」——嚴禁。應譯成：「記憶體已從零件變成武器。」
4. ❌ 也是錯誤（過度翻譯）：「密索斯的網路戰能力」——Mythos 不應音譯。

翻譯原則：
1. **意譯優先，不逐字直譯**：英中句構不同，翻譯時重組句子結構讓中文自然。"The amount of silicon they can put into a data center is limited by the amount of power" 譯成「資料中心能容納多少晶片，取決於可用的電力」，不是「他們可以放進資料中心的矽數量受到他們可用功率的限制」。**重組句構不等於刪內容**：原句的每個資訊點都要在中文裡。
2. **避免翻譯腔**：不要出現「這是一個...的問題」「在...的情況下」「基於...的原因」這類生硬句式。用台灣人日常會說的方式表達。
3. **技術語境要準確**：silicon 在半導體語境是「晶片」不是「矽」；package 是「封裝」不是「包裝」；die 是「晶粒」；bump 是「凸塊」；power 在晶片語境是「功耗」，在資料中心語境是「電力」。
4. **譯成人講話的樣子，不要升格成分析報告**：白話優先於書面語。「市場百分之百認為他們現在賺得太多」不是「市場認定公司的獲利高峰難以持續」；「狠得不得了」不是「工作極為勤奮」。講者講得直白就譯得直白，不要替他潤色成正式書面語，也不要替他降溫。
5. **專有名詞保留英文**：這條優先於翻譯規則。寧可在中文句子裡夾英文專名，也不要創造讀者看不懂的音譯。

## 破折號零容忍

**一律不使用破折號（—、–、——）**，一個都不准出現，改用逗號或句號。

## 覆蓋鐵則（與格式鐵則同級，漏段＝失敗）

- **從第一句順到最後一句**，禁止跳過逐字稿中任何一段連續內容。**沒有「次要內容」這回事**：寒暄、廣告、閒聊、聽眾 QA、片尾致謝，全部照順
- 你的輸出長度應接近逐字稿的資訊量。輸出明顯比逐字稿短，就是你漏了段落，不是你寫得精簡
- 四種內容最常被模型當枝節丟掉，**必收**：
  1. 講者的個人部位／利益揭露（「我早就下車了」「我自己沒有投入資金」「這是業配／不是業配」）
  2. 反方例證與迷思澄清
  3. 時事背景（某政策研議中、某事件剛發生）
  4. 具體標的名、數據、時間表

## 輸出 JSON 格式（不要輸出任何其他內容）

{
  "title": "一句話說明這支影片在談什麼，不超過 30 字，例如：Gavin Baker 談 AI 賣壓、GPU 定價與信貸風險",
  "tags": ["標籤1", "標籤2", "標籤3"],
  "filename_keywords": "2到3個關鍵字用底線連接，例如：AI賣壓_GPU定價_信貸風險",
  "article": "中文全文順稿（純文字段落，每段以說話人前綴開頭，段間空一行；不含標題、不含 markdown 小標）"
}
"""


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


# ---- 引述計數口徑（與 humanizer-zh final_gate.py 的 quote_metrics 同源，改一邊記得改另一邊）----
# ⚠️ 2026-08-06 起 /yt 產出的是「中文全文順稿」，通篇沒有「」引號，所以下面的
# quote_metrics／_representative_quote_coverage／QUOTE_RATIO_FLOOR 已**不再**參與
# format_violations。保留它們只為兩件事：(a) tests/test_yt_retry_selection.py 對
# humanizer-zh final_gate.py 的同源口徑做 parity 驗證；(b) 下游 humanizer 成文階段
# 仍以此口徑計算引述佔比。不要在 /yt 的閘門裡重新啟用。
# 黃金範本（使用者手改）實測 63%，現行 humanizer 交付版 54%，舊 /yt 文章版 39%。
_CJK_RE = re.compile(r"[㐀-鿿]")
_QUOTE_RE = re.compile(r"「([^「」]*)」")
_QUOTE_MIN_CJK = 6          # 引述則數只算引號內 CJK ≥ 6 字者，名詞碎片不算一則
QUOTE_RATIO_FLOOR = 0.45    # 低於此值列為格式違規並觸發重生；目標是六成左右


def quote_metrics(text: str) -> tuple[int, int, int]:
    """統一口徑：回傳 (全文 CJK 字數, 引號內 CJK 字數, 引述則數)。

    先剝 YAML frontmatter，再計數。本檔只此一處實作，不要在別處重寫。
    """
    body = re.sub(r"\A---\n.*?\n---\n", "", text, count=1, flags=re.DOTALL)
    total = len(_CJK_RE.findall(body))
    quoted = count = 0
    for quote in _QUOTE_RE.findall(body):
        n = len(_CJK_RE.findall(quote))
        quoted += n
        if n >= _QUOTE_MIN_CJK:
            count += 1
    return total, quoted, count


def _representative_quote_coverage(article: str) -> tuple[int, int]:
    """Count sections with one long quote or a substantive short exchange."""
    sections = re.split(r"(?m)^##\s+", article)[1:]
    main_sections = []
    for section in sections:
        heading = section.splitlines()[0].strip() if section.splitlines() else ""
        if heading in {"導言", "結語"}:
            continue
        main_sections.append(section)
    covered = 0
    for section in main_sections:
        quotes = re.findall(r"「([^「」]+)」", section)
        quote_lengths = [len(re.findall(r"[一-鿿]", quote)) for quote in quotes]
        dialogue_lengths = [length for length in quote_lengths if length >= 6]
        if any(length >= 30 for length in quote_lengths) or (
            len(dialogue_lengths) >= 2 and sum(dialogue_lengths) >= 30
        ):
            covered += 1
    return covered, len(main_sections)


# ---------------------------------------------------------------------------
# 順稿專用閘門：說話人前綴、編輯者的話、覆蓋率
# ---------------------------------------------------------------------------

# 說話人前綴：段首 24 字內的第一個全形/半形冒號之前那一段（「Baker：」「主持人：」）。
# 排除引號與句末標點，避免把講者句子裡的冒號誤判成前綴。
_SPEAKER_PREFIX_RE = re.compile(r"^([^：:\n「」，。？！；]{1,24})[：:]")


def _narration_scope(article: str) -> str:
    """順稿模式下「編輯者的話」的掃描範圍。

    /yt 舊版是文章，講者原話都在「」裡，所以旁白掃描只要剔除「」即可。順稿沒有
    「」——整篇都是講者的話——若照舊掃全文，講者自己講的「補上」「笑說」會被誤判
    成報幕詞。故改成：有說話人前綴的段落只留前綴本身（抓「Baker 笑著接：」這種
    夾在前綴裡的舞台指示），沒有前綴的段落＝編輯者插入的話或標題，整段掃。
    """
    out = []
    for raw in article.split("\n"):
        s = raw.strip()
        if not s:
            continue
        m = _SPEAKER_PREFIX_RE.match(s)
        out.append(m.group(1) if m else s)
    return "\n".join(out)


def _speaker_prefix_ratio(article: str) -> tuple[int, int]:
    """回傳 (有說話人前綴的段落數, 總段落數)；用來抓「整篇寫成文章」。"""
    paras = [p.strip() for p in re.split(r"\n\s*\n", article) if p.strip()]
    prefixed = sum(1 for p in paras if _SPEAKER_PREFIX_RE.match(p))
    return prefixed, len(paras)


# ---- 順稿覆蓋率閘門（順稿最重要的一關）----
#
# 校準依據（2026-08-06，實測樣本
# `2026-08-05_yt_Invest_Like_The_Best_AI_Selloff_GPU定價_信貸風險_transcript.txt`）：
#   英文字幕 71,862 字元 / 13,329 英文詞 / 2,064 行。
#   忠實中文順稿一般是 1.5–1.8 個中文字承載一個英文詞（去掉 uh/um 後取偏保守的
#   1.6）→ 約 21,300 個中文字 → 中文字數 ÷ 字幕字元數 ≈ 0.30。
#   下限取期望值的 60%（0.18）：漏掉四成以上內容才會被判違規並重生，正常輸出
#   （0.26–0.34）離門檻還有很大距離；「只順了前三分之一」落在 0.10 左右，穩穩被抓。
# 中文來源：順稿去掉語塞後約留 80–90% 的中文字，而中文字幕本身的 CJK 佔字元數
#   約 85% → 期望比值 ≈ 0.72，下限同樣取六成 → 0.42。
# 日韓來源：日／韓文譯成中文字數會縮，經驗值約原文字元數的 0.55 → 下限 0.32。
# 分段太短時比例波動大（開場寒暄、廣告段），故 3,000 字元以下不檢查。
COVERAGE_MIN_TRANSCRIPT_CHARS = 3_000


def _coverage_floor(transcript: str) -> tuple[float, float, str]:
    """回傳 (期望比值, 違規下限, 來源語言標籤)。比值＝成稿中文字數 ÷ 字幕字元數。"""
    if len(_KANA_HANGUL_RE.findall(transcript)) >= 200:
        return 0.55, 0.32, "日韓"
    if len(re.findall(r"[一-鿿]", transcript)) > len(transcript) * 0.3:
        return 0.72, 0.42, "中文"
    return 0.30, 0.18, "英文"


def format_violations(article: str, transcript: str = "") -> list:
    """Check a generated 中文全文順稿 against the SYSTEM_PROMPT 鐵則.

    Returns human-readable violation descriptions (empty list = pass).

    `transcript`：對應這段輸出的原始字幕（多段生成時是該 chunk 的字幕）。給了才會
    跑覆蓋率閘門——順稿最重要的一關，抓「整段跳過」。留空則略過該項。
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
        issues.append(
            f"{len(blockquotes)} 行 > 引用塊（順稿只用「說話人：內容」的段落，不用引用塊）"
        )
    # 破折號零容忍（與 humanizer-zh final_gate.py 的 DASH_RE 同源）。
    # 只掃全形破折號與 en dash；ASCII `-` 是 markdown 清單與英文複合詞的合法字元，不列入。
    dashes = re.findall(r"[—–]", article)
    if dashes:
        sample = next(
            (l.strip()[:50] for l in article.splitlines() if re.search(r"[—–]", l)), ""
        )
        issues.append(
            f"{len(dashes)} 處破折號（一律不使用破折號，改用逗號或句號），例如：{sample}"
        )
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
    # 舞台指示／替講者語氣打分。掃描範圍見 _narration_scope：有說話人前綴的段落
    # 只掃前綴本身（講者自己說的「補上」「笑說」不算違規），沒有前綴的段落整段掃。
    narration = _narration_scope(article)
    # 分段後台資訊滲入成稿（chunk meta 洩漏）：模型把 part_info 的分段說明寫進文章
    meta_leak = re.search(
        r"逐字稿的(?:第[一1壹\d]|最後一|中間)段|後續段落|具體內容要等|這是完整逐字稿",
        narration,
    )
    if meta_leak:
        issues.append(
            f"文章洩漏分段後台資訊（出現「{meta_leak.group(0)}」，嚴禁提及逐字稿分段或預告未見內容）"
        )
    # 報幕用語：描寫對話的動作／節奏／戲劇性，使用者明令零容忍、最常復發
    stage_phrases = (
        "補了一句", "補了一個", "補一句", "補一刀", "補了一刀", "補刀",
        "補了最後一刀", "補了一個畫面", "補了一個細節",
        "補上", "補了一段", "補述", "再補一句", "再補一個",
        "笑著接", "順著接", "馬上搭腔", "馬上吐槽", "再補一刀",
        "把方向拉回", "把梗接到", "話鋒一轉", "切入核心",
        "苦笑著說", "笑著說", "笑說", "打趣", "搶話",
        "開門見山", "先解釋為什麼", "點出另外",
        "另一個更即時的問題", "她的重點是", "他的重點是",
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
    # 順稿不下小標：`##` 標題是「編輯者在分章」的鐵證。
    headings = re.findall(r"(?m)^#{1,6}\s+\S", article)
    if headings:
        issues.append(
            f"{len(headings)} 個 markdown 小標題（順稿不下小標、不分章，"
            "只依字幕順序輸出「說話人：內容」段落）"
        )
    # 說話人前綴覆蓋：大多數段落都沒有前綴＝又寫成文章了。
    prefixed, total_paras = _speaker_prefix_ratio(article)
    if total_paras >= 5 and prefixed / total_paras < 0.6:
        issues.append(
            f"只有 {prefixed}/{total_paras} 段以說話人前綴開頭（低於 60%）；"
            "順稿每段都要用「Baker：」「主持人：」這種前綴，"
            "沒有前綴的段落多半是編輯者自己寫的導言、串接或總結，必須刪除"
        )
    # ---- 覆蓋率閘門：順稿最重要的一關，抓「整段跳過」（校準見 _coverage_floor 上方註解）----
    if transcript and len(transcript) >= COVERAGE_MIN_TRANSCRIPT_CHARS:
        art_cjk = len(re.findall(r"[一-鿿]", article))
        expected, floor, label = _coverage_floor(transcript)
        ratio = art_cjk / len(transcript)
        if ratio < floor:
            issues.append(
                f"覆蓋率不足：成稿只有 {art_cjk} 個中文字，字幕 {len(transcript)} 字元"
                f"（比值 {ratio:.2f}，{label}來源期望約 {expected:.2f}、下限 {floor:.2f}）。"
                "這代表你跳過了大段字幕。請從字幕第一句重新順到最後一句，"
                "不要摘要、不要選材、不要壓縮，每一段講者說過的話都要有對應輸出"
            )
    return issues


def _candidate_content_metrics(result: dict, transcript: str) -> dict[str, int]:
    """Return conservative proxies used only when choosing among retries.

    These metrics do not prove semantic coverage.  They prevent a cosmetically
    cleaner retry from winning after it drops a material amount of article text,
    transcript-backed numbers, and topic coverage at the same time.
    """
    article = result.get("article", "") if result else ""
    topics = result.get("topics", []) if result else []

    def _numbers(text: str) -> set[str]:
        raw = re.findall(
            r"(?<![A-Za-z0-9])[0-9][0-9,.]*(?:\s*(?:%|兆|億|萬|倍|美元|年|月|日|碼|點|MW|GW|GB))?",
            text,
            flags=re.IGNORECASE,
        )
        return {re.sub(r"[\s,]", "", n).lower() for n in raw}

    transcript_numbers = _numbers(transcript)
    article_numbers = _numbers(article)
    return {
        "cjk": len(re.findall(r"[一-鿿]", article)),
        "topics": len([t for t in topics if str(t).strip()]),
        "numbers": len(transcript_numbers & article_numbers),
    }


def _content_regressions(candidate: dict, incumbent: dict, transcript: str) -> list[str]:
    """Describe material content-proxy regressions between retry candidates."""
    new = _candidate_content_metrics(candidate, transcript)
    old = _candidate_content_metrics(incumbent, transcript)
    signals = []
    if old["cjk"] >= 400 and new["cjk"] < old["cjk"] * 0.65:
        signals.append(f"正文 CJK 字數 {old['cjk']}→{new['cjk']}")
    if old["topics"] >= 3 and new["topics"] + 1 < old["topics"]:
        signals.append(f"topics {old['topics']}→{new['topics']}")
    if old["numbers"] >= 3 and new["numbers"] < old["numbers"] * 0.70:
        signals.append(f"逐字稿數字承載 {old['numbers']}→{new['numbers']}")
    # One proxy can fluctuate legitimately.  Require two independent loss
    # signals before refusing an otherwise cleaner retry.
    return signals if len(signals) >= 2 else []


def _issue_score(issues: list) -> int:
    """Weight content-integrity failures above cosmetic style failures."""
    score = 0
    for issue in issues:
        if any(
            marker in issue
            for marker in (
                "覆蓋率不足",
                "說話人前綴",
                "未翻譯",
                "大量未翻譯外語",
                "長段落重複",
                "分段後台資訊",
                "西里爾字母",
                "原始 JSON",
            )
        ):
            score += 4
        elif "複述" in issue:
            score += 2
        else:
            score += 1
    return score


def _prefer_retry_candidate(
    candidate: dict,
    candidate_issues: list,
    incumbent: dict | None,
    incumbent_issues: list | None,
    transcript: str,
) -> tuple[bool, list[str]]:
    """Choose a retry using both rule compliance and content-retention proxies."""
    if incumbent is None or incumbent_issues is None:
        return True, []
    regressions = _content_regressions(candidate, incumbent, transcript)
    if regressions:
        return False, regressions
    candidate_score = _issue_score(candidate_issues)
    incumbent_score = _issue_score(incumbent_issues)
    if candidate_score != incumbent_score:
        return candidate_score < incumbent_score, []
    new = _candidate_content_metrics(candidate, transcript)
    old = _candidate_content_metrics(incumbent, transcript)
    new_tiebreak = (new["topics"], new["numbers"], new["cjk"])
    old_tiebreak = (old["topics"], old["numbers"], old["cjk"])
    return new_tiebreak > old_tiebreak, []


def _redundant_narration(article: str) -> list:
    """找出引述前的內容預告與引述後的同義解說。

    逐句比較引述前後相鄰的敘述段。任一句的 CJK 2-gram 過半被引述涵蓋，或與
    引述共用至少兩個帶單位數字，即視為同一內容重複表達。這項檢查會參與生成重試，
    殘留命中才交給 humanizer 判斷。與 humanizer-zh scripts/final_gate.py 同邏輯。
    """
    def _bigrams(s: str) -> set:
        s = re.sub(r"[^一-鿿]", "", s)
        return {s[i:i + 2] for i in range(len(s) - 1)}

    def _nums(s: str) -> set:
        return set(re.findall(r"[0-9][0-9,.]*\s*(?:兆|億|倍|%|萬)", s))

    def _english_tokens(s: str) -> set:
        stop = {"the", "and", "or", "to", "of", "in", "on", "for", "ai"}
        return {
            token.lower()
            for token in re.findall(r"[A-Za-z][A-Za-z0-9'-]+", s)
            if token.lower() not in stop
        }

    def _same_claim(sentence: str, reference: str) -> bool:
        sentence_grams = _bigrams(sentence)
        reference_grams = _bigrams(reference)
        contain = (
            len(sentence_grams & reference_grams) / len(sentence_grams)
            if len(sentence_grams) >= 4 and len(reference_grams) >= 4
            else 0.0
        )
        shared_english = _english_tokens(sentence) & _english_tokens(reference)
        return (
            contain >= 0.5
            or len(_nums(sentence) & _nums(reference)) >= 2
            or len(shared_english) >= 3
            or (
                len(shared_english) >= 2
                and len(sentence_grams & reference_grams) >= 1
            )
        )

    def _is_quote_para(p: str) -> bool:
        qs = re.findall(r"「([^「」]{15,})」", p)
        return bool(qs) and sum(len(x) for x in qs) > len(p) * 0.5

    def _has_substantive_quote(p: str) -> bool:
        return any(len(quote) >= 15 for quote in re.findall(r"「([^「」]+)」", p))

    paras = [p.strip() for p in article.split("\n\n") if p.strip()]
    hits = []
    for i, cur in enumerate(paras):
        if cur.startswith("#") or not _has_substantive_quote(cur):
            continue
        quotes = re.findall(r"「([^「」]+)」", cur)
        quote = " ".join(quotes)
        qgrams, qnums = _bigrams(quote), _nums(quote)
        neighbors = []
        same_paragraph_narration = re.sub(r"「[^「」]*」", "", cur)
        if same_paragraph_narration.strip():
            neighbors.append(("同段串接", same_paragraph_narration))
        if i > 0 and not paras[i - 1].startswith("#") and not _is_quote_para(paras[i - 1]):
            neighbors.append(("引述前", paras[i - 1]))
        if i + 1 < len(paras) and not paras[i + 1].startswith("#") and not _is_quote_para(paras[i + 1]):
            neighbors.append(("引述後", paras[i + 1]))
        for position, paragraph in neighbors:
            narration = re.sub(r"「[^「」]*」", "", paragraph)
            for sent in re.split(r"[。！？；]", narration):
                sg = _bigrams(sent)
                same_claim = _same_claim(sent, quote)
                if len(sg) < 6 and not same_claim:
                    continue
                contain = len(sg & qgrams) / len(sg) if sg else 0.0
                if (
                    contain >= 0.5
                    or len(_nums(sent) & qnums) >= 2
                    or same_claim
                ):
                    hits.append(f"{position}：{sent.strip()[:50]}")
        for quoted in quotes:
            sentences = [
                sent.strip()
                for sent in re.split(r"[。！？；]", quoted)
                if sent.strip()
            ]
            for left, right in zip(sentences, sentences[1:]):
                if _same_claim(left, right):
                    hits.append(
                        f"引述內自我複述：{left[:24]} ↔ {right[:24]}"
                    )
    return list(dict.fromkeys(hits))


def call_minimax(transcript: str, metadata: dict, part_info: str = "") -> dict:
    """把一段逐字稿順成中文全文，並在生成迴路裡執行順稿閘門。

    Calls MiniMax once, runs format_violations() on the result (含覆蓋率閘門，
    以本段字幕為分母)；on failure, retries with the violation list appended to the
    prompt.  Selection considers both rule compliance and content-retention
    proxies so a shorter, cleaner retry cannot win after materially dropping
    transcript-backed data.

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

    user_prompt = f"""以下是一部 YouTube 影片的逐字稿，請把它順成通順的繁體中文全文。

不要寫文章、不要選材、不要下小標、不要摘要。依字幕順序從第一句順到最後一句，
每段以說話人前綴開頭（例如「主持人：」「講者：」）。

影片資訊（只用來判斷說話人是誰、專名怎麼拼，不要拿來補背景知識）：
- 標題：{metadata.get('title', 'Unknown')}
- 頻道：{metadata.get('channel', 'Unknown')}
- 發布日期：{metadata.get('upload_date', '未知')}
- 時長：約 {duration_min} 分鐘
- 簡介：{metadata.get('description', '')[:800]}{chapters_section}

逐字稿內容：
{transcript}{part_note}

請用 JSON 格式輸出（嚴格遵守 system prompt 中的順稿規格）。"""

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
        # 覆蓋率諮詢：硬閘門（format_violations）用的是「跳大段」的下限，這裡再印一次
        # 實際比值，即使沒觸發重生，比值貼近下限也代表順稿偏薄，humanizer 覆蓋對帳
        # （處理流程第 3 步）要逐段回字幕嚴查。
        if transcript and result and len(transcript) >= COVERAGE_MIN_TRANSCRIPT_CHARS:
            art_cjk = len(re.findall(r"[一-鿿]", result.get("article", "")))
            expected, floor, label = _coverage_floor(transcript)
            ratio = art_cjk / max(len(transcript), 1)
            if ratio < expected * 0.85:
                print(
                    f"[note] 順稿覆蓋率偏低：成稿 {art_cjk} 中文字 vs 字幕 "
                    f"{len(transcript)} 字元（比值 {ratio:.2f}，{label}來源期望約 "
                    f"{expected:.2f}、重生下限 {floor:.2f}），疑似有跳段。"
                    "humanizer 覆蓋對帳請逐段回字幕核對並補回。",
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
            coverage_repair = ""
            if any("覆蓋率不足" in issue for issue in best_issues):
                coverage_repair = (
                    "上一版跳過了大段字幕。這次請把字幕當成清單：從第一行開始，"
                    "每一段講者說過的話都要有對應的中文輸出，順到最後一行為止。"
                    "不要摘要、不要選材、不要只挑精華段，長度應接近字幕的資訊量。"
                )
            prompt = user_prompt + (
                "\n\n⚠️ 你上一次的輸出違反了順稿鐵則：" + "；".join(best_issues) + "。"
                + coverage_repair
                + "請重新輸出完整 JSON。提醒："
                "① 這是**中文全文順稿**，不是文章：不下 `##` 小標、不寫導言與結語、"
                "不寫任何一句編輯者自己的話，每段以說話人前綴（「講者：」「主持人：」）開頭；"
                "② **整篇必須是繁體中文**，嚴禁任何非中文整句或段落（英文、日文、韓文等外語，"
                "尤其嚴禁整段日文假名或韓文諺文原樣照貼）；"
                "③ 專有名詞（人名、公司名、技術術語）可保留英文，"
                "但**只能用逐字稿裡實際出現的名字**——嚴禁憑記憶補出字幕沒有的"
                "機構名、benchmark、產品名，也嚴禁猜說話人的名字；"
                "字幕沒提到確切名字時，用中性描述（如「一項評測」「一家資產管理公司」「講者」）帶過。"
            )
        cand = _request_article(prompt, metadata)
        cand["article"] = _strip_model_artifacts(cand.get("article", ""))
        cand_issues = format_violations(cand.get("article", ""), transcript)
        prefer, regressions = _prefer_retry_candidate(
            cand, cand_issues, best, best_issues, transcript
        )
        if prefer:
            best, best_issues = cand, cand_issues
        elif regressions:
            print(
                "[warn] 本次重試雖可能較乾淨，但內容代理指標明顯退化，不取代目前最佳版："
                + "；".join(regressions),
                file=sys.stderr,
            )
        if not cand_issues and best is cand:
            return _finalize(cand)
        if cand_issues:
            print(
                f"[warn] 第 {attempt}/{MAX_ATTEMPTS} 次格式鐵則未通過："
                + "；".join(cand_issues),
                file=sys.stderr,
            )
    print(
        f"[warn] {MAX_ATTEMPTS} 次後仍未完全通過，保留規則遵循與內容承載綜合較佳的一版",
        file=sys.stderr,
    )
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
                        "max_tokens": OUTPUT_TOKEN_BUDGET,
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
                            "max_tokens": OUTPUT_TOKEN_BUDGET,
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


# 單次呼叫的輸出預算（_request_article 的 max_tokens）。chunk 大小以它回推。
OUTPUT_TOKEN_BUDGET = 16_384


def _chunk_target_for(transcript: str) -> int:
    """依來源語言決定單次 MiniMax 呼叫的逐字稿長度上限。

    實測教訓（2026-07-11）：M3 的輸出預算（max_tokens 16384）撐不起大 chunk 的
    完整覆蓋——股癌 20.7k 中文單次呼叫只承載一半論點、Gavin Baker 2×33k 英文掉了
    8 個主題段。chunk 一大，模型必然壓縮取捨，「跳段偷懶」是結構性結果，不是
    prompt 勸得回來的。

    2026-08-06 改順稿後重新校準（輸出長度不再被壓縮，會逼近輸入的資訊量，所以
    舊的 chunk 值會撞上 16384 token 天花板被截斷）。以 1 個中文字 ≈ 1 token 保守估：

      英文來源：實測樣本 71,862 字元 / 13,329 詞 → 5.39 字元/詞。順稿約 1.6 個中文字
        承載 1 個英文詞。16,000 字元 ≈ 2,970 詞 → 約 4,750 中文字 → 連同 JSON 跳脫、
        說話人前綴、title/tags 約 6,000–6,500 token，只用掉預算的 40%。（舊值 20,000
        字元 → 約 5,940 中文字 → 7,500–8,000 token，仍安全但餘裕不足，翻譯偏長時會擦線。）
      中文來源：順稿去掉語塞後留 80–90% 的中文字，幾乎 1:1。舊值 12,000 字元
        → 約 10,000 中文字 → 11,000+ token，離 16,384 太近，必須下修。8,000 字元
        → 約 6,800 中文字 → 約 7,500 token，餘裕 54%。
      日韓來源：譯成中文約原文字元數的 0.55–0.6。舊值 18,000 → 約 10,000 中文字
        → 11,000 token，同樣太近。12,000 字元 → 約 7,000 中文字 → 約 8,000 token。
    """
    if len(_KANA_HANGUL_RE.findall(transcript)) >= 200:
        return 12_000          # 日韓來源
    cjk = len(re.findall(r"[一-鿿]", transcript))
    if cjk > len(transcript) * 0.3:
        return 8_000           # 中文來源：資訊密度最高（字＝詞），切最小
    return 16_000              # 英文等其他來源


# 分段上限。順稿的 chunk 比舊版小（英文 16k／中文 8k／日韓 12k 字元），舊的上限 8
# 會讓長影片被迫回到大 chunk（例：3 小時英文 podcast 約 150k 字元 ÷ 8 = 18.7k／段，
# 超過目標）。放寬到 16 段：英文可覆蓋到 256k 字元、中文 128k，仍在單次 API 成本可控範圍。
MAX_PARTS = 16


def generate_article(transcript: str, metadata: dict) -> dict:
    """生成中文全文順稿。長逐字稿拆成多次 MiniMax 呼叫；chunk 大小依語言校準
    （見 _chunk_target_for）。最後對殘留假名／諺文做翻譯修補。"""
    chunk_target = _chunk_target_for(transcript)
    n_parts = ((len(transcript) - 1) // chunk_target + 1) if transcript else 1
    n_parts = max(1, min(n_parts, MAX_PARTS))

    if n_parts == 1:
        result = call_minimax(transcript, metadata)
    else:
        print(f"      字幕共 {len(transcript)} 字元（chunk 上限 {chunk_target}），拆為 {n_parts} 段...")
        segments = _split_into_n(transcript, n_parts)
        n = len(segments)
        # 分段是後台資訊，嚴禁滲入成稿：2026-07-11 停損王篇 M3 曾把「因為這是逐字稿
        # 的第一段，具體內容要等後續段落才會揭曉」寫進順稿還自行推測未見的內容。
        meta_ban = ("⚠️ 分段是後台資訊：輸出裡嚴禁提及「逐字稿」「分段」「第 N 段」"
                    "「後續段落」等字眼（講者親口說的除外），嚴禁替你沒看到的段落"
                    "寫預告或推測內容——只寫這段逐字稿裡實際有的東西。")
        chunks = []
        for i, seg in enumerate(segments):
            info = (
                f"【重要】這是完整逐字稿的第 {i+1}／{n} 段。"
                "只順這一段，從這段的第一句順到最後一句，"
                "不要導言、不要結語、不要總結、不要重複介紹講者。"
                "你的輸出會直接接在前一段的輸出之後，所以第一段就從說話人前綴開始寫。"
                + meta_ban
            )
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
    """Format the 順稿 as markdown with frontmatter and save to output directory."""
    today = datetime.now().strftime("%Y-%m-%d")
    channel_clean = sanitize_filename(metadata.get("channel", "Unknown"))
    keywords = sanitize_filename(article_data.get("filename_keywords", "摘要"))

    filename = f"{today}_yt_{channel_clean}_{keywords}.md"
    filepath = output_dir / filename

    tags_yaml = json.dumps(article_data.get("tags", []), ensure_ascii=False)
    channel_yaml = metadata.get('channel', 'Unknown').replace('"', '\\"')
    title_yaml = metadata.get('title', 'Unknown').replace('"', '\\"')

    frontmatter = f"""---
type: yt_transcript_zh
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
*本檔為 YouTube 影片字幕的中文全文順稿（AI 生成，未做編輯取捨），僅供參考。*
"""

    output_dir.mkdir(parents=True, exist_ok=True)
    filepath.write_text(full_content, encoding="utf-8")
    return filepath


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(
    youtube_url: str,
    transcript_file: str | None = None,
    lang_hint: str | None = None,
) -> str:
    """Full pipeline: URL → transcript → 中文全文順稿 → saved file.

    If transcript_file is given (e.g. a Whisper transcript for a video whose
    subtitles are disabled), it is used directly instead of fetching subtitles,
    and is also saved alongside the article as the cross-reference 原文字幕.

    lang_hint（如 ja／ko／en）只在字幕不可用、落到本地 Whisper 轉錄時生效，用來
    強制解碼語言、降低專名誤判；留空則自動偵測。

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
        try:
            transcript, lang = fetch_transcript(video_id)
        except Exception as cap_err:
            # 字幕被 IP 封鎖或影片無字幕 → 自動改用本地 Whisper 轉錄（音訊不受封鎖）
            print(
                f"      ⚠️ 字幕取得失敗（{type(cap_err).__name__}），改用本地 Whisper 轉錄"
                f"（下載音訊，可能數分鐘）...",
                file=sys.stderr,
            )
            hint_note = f"（指定語言 {lang_hint}）" if lang_hint else "（語言自動偵測）"
            print(f"[2/6] 字幕不可用，改用本地 Whisper 轉錄{hint_note}（下載音訊，可能數分鐘）...")
            transcript, lang = _fetch_transcript_via_whisper(youtube_url, lang_hint)
            print(f"      Whisper 逐字稿: {len(transcript)} 字元 | 語言: {lang}")
            en_transcript = transcript
        else:
            print(f"      字幕語言: {lang} | 長度: {len(transcript)} 字元")

            print(f"[3/6] 保留原文字幕供對帳...")
            # 一律保存「實際餵給模型」的原文逐字稿：它才是 humanizer 對帳的
            # ground truth。舊邏輯只存英文軌，中／日／韓來源沒有英文軌時
            # _transcript.txt 根本不會落地，humanizer 連對帳材料都沒有。
            en_transcript = transcript
            print(f"      原文字幕: {len(en_transcript)} 字元（完整保留，不截斷）")

    print(f"[4/6] 取得影片資訊...")
    metadata = fetch_metadata(video_id)
    print(f"      標題: {metadata['title']}")
    print(f"      頻道: {metadata['channel']}")

    print(f"[5/6] 呼叫 MiniMax API 順稿...")
    article_data = generate_article(transcript, metadata)
    print(f"      順稿標題: {article_data.get('title', 'N/A')}")

    print(f"[6/6] 簡轉繁 + 儲存順稿...")
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
    print(f"      順稿已儲存: {filepath}")

    # Save English transcript alongside the article
    if en_transcript:
        transcript_path = filepath.with_name(filepath.stem + "_transcript.txt")
        transcript_path.write_text(en_transcript, encoding="utf-8")
        print(f"      原文字幕已儲存: {transcript_path}")

    return str(filepath)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="YouTube 影片 → 中文全文順稿")
    ap.add_argument("youtube_url", help="YouTube URL")
    ap.add_argument(
        "--transcript-file",
        default=None,
        help="本地逐字稿 .txt（無字幕影片的 whisper fallback，跳過抓字幕步驟）",
    )
    ap.add_argument(
        "--lang",
        default=None,
        help="Whisper 轉錄語言（ja/ko/en…），僅在落到本地 Whisper fallback 時生效，"
        "用來強制解碼語言、降低專名誤判；留空則自動偵測",
    )
    cli_args = ap.parse_args()
    result = main(cli_args.youtube_url, cli_args.transcript_file, cli_args.lang)
    print(f"\n完成！順稿已儲存至：{result}")
