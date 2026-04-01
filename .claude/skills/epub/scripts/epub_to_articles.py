"""epub_to_articles.py

將 epub 電子書拆解為章節，透過 MiniMax M2.7 API 生成：
  1. 子彈式重點筆記（_bullets.md）
  2. 深度洞察文章（_article.md）

每章各一份，落檔至 Obsidian 書籍目錄。
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import warnings
from datetime import datetime
from pathlib import Path

import httpx

# Ensure UTF-8 output on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# Suppress BS4 XML warning
warnings.filterwarnings("ignore")

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

OUTPUT_BASE = Path(
    r"C:\Users\wukee\OneDrive\文件\Obsidian Vault\投資筆記\書籍"
)

SEGMENT_SIZE      = 20_000   # 每段最大字元數（分段摘要用）
DIRECT_THRESHOLD  = 25_000   # 低於此值直接送最終生成，跳過分段
MIN_INCLUDE_CHARS = 300      # 低於此值視為非內容章節跳過
MERGE_THRESHOLD   = 800      # 低於此值的章節合併至下一章

# 跳過的章節關鍵字（小寫比對）
SKIP_KEYWORDS = {
    "cover", "also by", "title page", "copyright", "contents",
    "dedication", "acknowledgments", "notes", "index",
    "about the author", "glossary", "bibliography",
    "封面", "版權", "目錄", "致謝", "索引", "參考書目",
}

# ---------------------------------------------------------------------------
# 1. Parse epub
# ---------------------------------------------------------------------------

def _html_to_text(html_bytes: bytes) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_bytes, "lxml")
    # Remove script/style
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)


def _should_skip(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in SKIP_KEYWORDS)


def _iter_toc_links(items):
    """Flatten TOC (handles nested sections)."""
    import ebooklib
    from ebooklib import epub
    for item in items:
        if isinstance(item, epub.Link):
            yield item
        elif isinstance(item, tuple):
            _section, children = item
            yield from _iter_toc_links(children)


def parse_epub(path: str) -> tuple[str, str, list[dict]]:
    """Parse epub, return (book_title, author, chapters).

    Each chapter: {title, text, char_count}
    """
    import ebooklib
    from ebooklib import epub

    book = epub.read_epub(path)
    title = book.title or Path(path).stem
    authors = book.get_metadata("DC", "creator")
    author = authors[0][0] if authors else "Unknown"

    chapters = []

    toc_links = list(_iter_toc_links(book.toc))

    if toc_links:
        for link in toc_links:
            if _should_skip(link.title):
                continue
            href = link.href.split("#")[0]
            item = book.get_item_with_href(href)
            if not item:
                continue
            text = _html_to_text(item.get_content())
            if len(text) < MIN_INCLUDE_CHARS:
                continue
            chapters.append({"title": link.title, "text": text, "char_count": len(text)})
    else:
        # Fallback: spine order
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            text = _html_to_text(item.get_content())
            if len(text) < MIN_INCLUDE_CHARS:
                continue
            chapters.append({"title": item.get_name(), "text": text, "char_count": len(text)})

    return title, author, chapters


# ---------------------------------------------------------------------------
# 2. Merge short chapters
# ---------------------------------------------------------------------------

def merge_short_chapters(chapters: list[dict], threshold: int = MERGE_THRESHOLD) -> list[dict]:
    """Merge chapters below threshold into the next chapter."""
    if not chapters:
        return chapters

    result = []
    pending: dict | None = None

    for ch in chapters:
        if pending is not None:
            # Merge pending into current
            merged = {
                "title": f"{pending['title']} / {ch['title']}",
                "text": pending["text"] + "\n\n" + ch["text"],
                "char_count": pending["char_count"] + ch["char_count"],
            }
            if merged["char_count"] < threshold:
                pending = merged  # Still short, keep accumulating
            else:
                result.append(merged)
                pending = None
        else:
            if ch["char_count"] < threshold:
                pending = ch
            else:
                result.append(ch)

    if pending is not None:
        # Last chapter was short — just append it
        result.append(pending)

    return result


# ---------------------------------------------------------------------------
# 3. Segment & condense long chapters
# ---------------------------------------------------------------------------

def split_into_segments(text: str, segment_size: int = SEGMENT_SIZE) -> list[str]:
    """Split text into segments of ~segment_size chars, breaking at paragraph boundaries."""
    if len(text) <= segment_size:
        return [text]

    segments = []
    start = 0
    while start < len(text):
        end = start + segment_size
        if end >= len(text):
            segments.append(text[start:])
            break
        # Try to break at a paragraph boundary (\n\n) within the last 2000 chars
        boundary = text.rfind("\n\n", start + segment_size - 2000, end)
        if boundary == -1:
            # Fall back to last sentence boundary
            boundary = text.rfind(". ", start + segment_size - 1000, end)
        if boundary == -1:
            boundary = end
        else:
            boundary += 2  # include the newlines/period+space
        segments.append(text[start:boundary])
        start = boundary

    return segments


SEGMENT_SUMMARY_SYSTEM = """\
你是一位精準的內容分析師。你的任務是將書籍章節的一個段落提煉為一份結構化的中文摘要，
保留所有重要論點、案例、數字和關鍵洞察，供後續生成完整分析文章使用。

輸出純文字摘要，不要 JSON 格式，不要標題，直接輸出內容。
長度約 800-1500 字，完整保留原文的論證脈絡和具體細節。"""


def summarize_segment(segment: str, book_title: str, chapter_title: str,
                      seg_num: int, total_segs: int) -> str:
    """First-pass: condense one segment into a plain-text summary."""
    user_prompt = f"""書名：{book_title}
章節：{chapter_title}（第 {seg_num}/{total_segs} 段）

以下是本段落的原文，請提煉為結構化摘要：

{segment}"""

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
                "max_tokens": 4096,
                "system": SEGMENT_SUMMARY_SYSTEM,
                "messages": [{"role": "user", "content": user_prompt}],
            },
        )
        r.raise_for_status()
        data = r.json()

    for block in data.get("content", []):
        if block.get("type") == "text":
            return block["text"]
    return ""


def condense_chapter(text: str, book_title: str, chapter_title: str) -> tuple[str, int]:
    """
    If chapter is long, split into segments and summarize each.
    Returns (condensed_text, num_segments).
    Short chapters pass through directly.
    """
    if len(text) <= DIRECT_THRESHOLD:
        return text, 1

    segments = split_into_segments(text)
    total = len(segments)
    print(f"      分成 {total} 段分別摘要...")

    summaries = []
    for i, seg in enumerate(segments, 1):
        print(f"      段落 {i}/{total}（{len(seg):,} 字元）→ 摘要中...")
        summary = summarize_segment(seg, book_title, chapter_title, i, total)
        summaries.append(f"【第 {i} 段摘要】\n{summary}")

    combined = "\n\n".join(summaries)
    return combined, total


# ---------------------------------------------------------------------------
# 4. MiniMax API — final generation
# ---------------------------------------------------------------------------

BULLETS_SYSTEM = """\
你是一位精準的知識萃取專家，專門將書籍章節的核心內容提煉為結構化的子彈式筆記。

你的輸出必須嚴格遵守以下 JSON 格式（不要輸出任何其他內容）：
{
  "bullets": [
    "**概念名稱**：清晰說明，保留重要數字或引用",
    ...
  ],
  "tags": ["標籤1", "標籤2", "標籤3"],
  "filename_keyword": "2到3個關鍵字用底線連接"
}

筆記要求：
1. 8-12 條，每條以 **粗體概念** 開頭後接冒號和說明
2. 優先保留：核心論點、反直覺洞察、重要數字/統計、實用框架、關鍵案例
3. 每條控制在 30-80 字，精煉不冗長
4. 繁體中文為主，專有名詞保留英文（格式：中文（English））
5. 按重要性排序，最關鍵的放前面"""

ARTICLE_SYSTEM = """\
你是一位頂尖的深度洞察文章寫手，專門將書籍章節內容轉化為高品質的繁體中文分析文章。

你的文章風格特色：
- 有故事性：用敘事手法帶讀者進入主題
- 有觀點：不只是轉述，要提煉核心洞察並加入分析評論
- 結構清晰：4-6 個吸引人的小標題
- 語言流暢：繁體中文為主，專有名詞保留英文（格式：中文（English））
- 深度適中：讓非專業讀者理解但不失專業深度

你的輸出必須嚴格遵守以下 JSON 格式（不要輸出任何其他內容）：
{
  "title": "文章標題（吸引人、有洞察力，不超過30字）",
  "tags": ["標籤1", "標籤2", "標籤3"],
  "filename_keyword": "2到3個關鍵字用底線連接",
  "article": "完整的 markdown 文章內容（不包含標題，從導言開始）"
}

文章內容要求：
1. 導言（2-3 段）：先點出本章的核心論點是什麼、為什麼重要、它挑戰了哪些常識
2. 正文（4-6 個 ## 小標題段落）：每段 200-400 字，每個小標題要有吸引力
3. 結語（1 段）：總結核心洞察，給讀者留下思考空間
4. 總字數：2000-4000 字
5. 適當使用 **粗體** 標記關鍵概念和重要數據
6. 使用 > 引用塊呈現書中重要論述或金句"""


def _parse_json_response(raw_text: str, fallback_title: str) -> dict:
    """Extract JSON from MiniMax response, handling markdown fences."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"title": fallback_title, "tags": [], "filename_keyword": "摘要",
                "bullets": [raw_text], "article": raw_text}


def call_minimax(content: str, book_title: str, chapter_title: str, mode: str) -> dict:
    """Call MiniMax API for final generation. mode: 'bullets' or 'article'.
    Expects pre-condensed content (no truncation applied here).
    """
    if not MINIMAX_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY 環境變數未設定。")

    system = BULLETS_SYSTEM if mode == "bullets" else ARTICLE_SYSTEM

    if mode == "bullets":
        user_prompt = f"""書名：{book_title}
章節：{chapter_title}

以下是本章節的內容，請提取核心重點：

{content}

請用 JSON 格式輸出子彈式筆記。"""
    else:
        user_prompt = f"""書名：{book_title}
章節：{chapter_title}

以下是本章節的內容，請撰寫深度洞察文章：

{content}

請用 JSON 格式輸出文章。"""

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
                "max_tokens": 8192,
                "system": system,
                "messages": [{"role": "user", "content": user_prompt}],
            },
        )
        r.raise_for_status()
        data = r.json()

    raw_text = ""
    for block in data.get("content", []):
        if block.get("type") == "text":
            raw_text = block["text"]
            break
    if not raw_text:
        raw_text = str(data)

    return _parse_json_response(raw_text, chapter_title)


# ---------------------------------------------------------------------------
# 4. Save markdown
# ---------------------------------------------------------------------------

def sanitize_filename(s: str) -> str:
    s = re.sub(r'[<>:"/\\|?*]', "", s)
    s = re.sub(r"\s+", "_", s.strip())
    return s[:50]


def save_bullets(data: dict, output_dir: Path, chapter_num: int,
                 book_title: str, chapter_title: str) -> Path:
    today = datetime.now().strftime("%Y-%m-%d")
    keyword = sanitize_filename(data.get("filename_keyword", "重點"))
    filename = f"{chapter_num:02d}_{keyword}_bullets.md"
    filepath = output_dir / filename

    tags_yaml = json.dumps(data.get("tags", []), ensure_ascii=False)
    bullets_text = "\n".join(f"- {b}" for b in data.get("bullets", []))

    content = f"""---
type: book_bullets
date: {today}
source: epub
book_title: "{book_title}"
chapter_num: "{chapter_num:02d}"
chapter_title: "{chapter_title}"
tags: {tags_yaml}
---

# 📌 重點筆記：{chapter_title}

> 來源：{book_title} | 第 {chapter_num:02d} 章

{bullets_text}

---
*本文由 AI 根據電子書內容生成，僅供參考。*
"""
    filepath.write_text(content, encoding="utf-8")
    return filepath


def save_article(data: dict, output_dir: Path, chapter_num: int,
                 book_title: str, chapter_title: str) -> Path:
    today = datetime.now().strftime("%Y-%m-%d")
    keyword = sanitize_filename(data.get("filename_keyword", "洞察"))
    filename = f"{chapter_num:02d}_{keyword}_article.md"
    filepath = output_dir / filename

    tags_yaml = json.dumps(data.get("tags", []), ensure_ascii=False)
    article_title = data.get("title", chapter_title)
    article_body = data.get("article", "")

    content = f"""---
type: book_article
date: {today}
source: epub
book_title: "{book_title}"
chapter_num: "{chapter_num:02d}"
chapter_title: "{chapter_title}"
tags: {tags_yaml}
---

# {article_title}

> 來源：{book_title} | 第 {chapter_num:02d} 章《{chapter_title}》

{article_body}

---
*本文由 AI 根據電子書內容生成，僅供參考。*
"""
    filepath.write_text(content, encoding="utf-8")
    return filepath


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(epub_path: str) -> None:
    print(f"[1/5] 解析 epub...")
    book_title, author, chapters_raw = parse_epub(epub_path)
    print(f"      書名: {book_title} | 作者: {author} | 原始章節數: {len(chapters_raw)}")

    print(f"[2/5] 合併短章...")
    chapters = merge_short_chapters(chapters_raw)
    merged_count = len(chapters_raw) - len(chapters)
    print(f"      合併後: {len(chapters)} 章（合併了 {merged_count} 個短章）")

    output_dir = OUTPUT_BASE / sanitize_filename(book_title)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[3/5] 開始處理章節...")
    total = len(chapters)
    success = 0
    failed = 0

    for i, ch in enumerate(chapters, start=1):
        title = ch["title"]
        chars = ch["char_count"]
        print(f"  [{i:02d}/{total}] {title}（{chars:,} 字元）")

        # Step A: condense (multi-segment summarization if long)
        try:
            condensed, num_segs = condense_chapter(ch["text"], book_title, title)
            if num_segs > 1:
                print(f"      壓縮完成（{len(condensed):,} 字元）")
        except Exception as e:
            print(f"    → 壓縮失敗，跳過此章 ({e})")
            failed += 2
            continue

        # Step B: generate bullets + article from condensed text
        try:
            bullets_data = call_minimax(condensed, book_title, title, "bullets")
            save_bullets(bullets_data, output_dir, i, book_title, title)
            print(f"    → 子彈筆記 OK")
        except Exception as e:
            print(f"    → 子彈筆記 FAIL ({e})")
            failed += 1

        try:
            article_data = call_minimax(condensed, book_title, title, "article")
            save_article(article_data, output_dir, i, book_title, title)
            print(f"    → 洞察文章 OK")
            success += 1
        except Exception as e:
            print(f"    → 洞察文章 FAIL ({e})")
            failed += 1

    print(f"[4/5] 儲存完成")
    print(f"      目錄: {output_dir}")
    print(f"[5/5] 完成！")
    print(f"      成功: {success * 2} 個 MD | 失敗: {failed} 個 | 共 {total} 章")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python epub_to_articles.py <epub_path>")
        sys.exit(1)
    main(sys.argv[1])
