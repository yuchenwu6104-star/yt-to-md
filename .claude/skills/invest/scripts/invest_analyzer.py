"""invest_analyzer.py

分析投資備忘錄或文章，透過 MiniMax M2.7 進行七維度評估並給出投資評級。
支援輸入：MD/TXT 文字檔、PDF、網址
輸出：直接顯示於終端機
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import warnings
from pathlib import Path

import httpx

# UTF-8 output on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Load .env
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
MAX_CONTENT_CHARS = 30_000

# ---------------------------------------------------------------------------
# 1. Input detection & extraction
# ---------------------------------------------------------------------------

def detect_input_type(s: str) -> str:
    s = s.strip()
    if s.startswith("http://") or s.startswith("https://"):
        return "url"
    if s.lower().endswith(".pdf"):
        return "pdf"
    return "text"


def extract_from_url(url: str) -> str:
    from bs4 import BeautifulSoup
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        r = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    # Remove nav/footer/scripts
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    # Try article body first, then fall back to body
    article = soup.find("article") or soup.find("main") or soup.body
    text = article.get_text(separator="\n", strip=True) if article else soup.get_text()
    # Collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_from_pdf(path: str) -> str:
    import pdfplumber
    pages = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                pages.append(t)
    return "\n\n".join(pages)


def extract_from_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="ignore")


# ---------------------------------------------------------------------------
# 2. MiniMax analysis
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
你是一位融合 River 框架（期望值思維、邊際優勢、方差意識）與價值投資視角的批判性投資分析師。
你的任務是對投資備忘錄或文章進行嚴格的七維度分析，並給出四級評級。

你必須嚴格輸出以下 JSON 格式（不輸出其他任何內容）：
{
  "subject": "公司名稱或投資主題",
  "rating": "強烈關注",
  "rating_reason": "一句話說明評級理由（30字以內）",
  "moat": "護城河評估：競爭優勢的本質（轉換成本/網路效應/成本優勢/無形資產/規模優勢）、寬度（寬/窄/無）、持久性分析",
  "valuation": "估值安全邊際：當前定價隱含的期望報酬、與合理估值的差距、是否有足夠安全邊際",
  "ev_structure": {
    "bull": {"scenario": "牛市情境描述", "probability": "30%", "return": "+80%"},
    "base": {"scenario": "基本情境描述", "probability": "50%", "return": "+25%"},
    "bear": {"scenario": "熊市情境描述", "probability": "20%", "return": "-40%"},
    "weighted_ev": "加權期望報酬：+X%（說明計算邏輯）"
  },
  "edge": "邊際優勢：這份分析/投資機會的資訊優勢來源是什麼，市場是否已充分反映",
  "variance_warning": "方差警示：最壞情況下可能損失多少、觸發條件是什麼、是否在可承受範圍",
  "bias_scan": [
    "最可能扭曲此分析的認知偏差1及原因",
    "認知偏差2及原因"
  ],
  "invalidation_triggers": [
    "論點失效觸發點1：具體事件或數據",
    "論點失效觸發點2",
    "論點失效觸發點3"
  ]
}

評級定義：
- 強烈關注：護城河清晰、估值有安全邊際、EV 明顯為正
- 值得研究：有部分優勢但需更多資訊或等待更好買點
- 中性觀望：論點存在但 EV 不夠吸引，或不確定性太高
- 不符標準：護城河薄弱、估值不合理、或風險報酬不對稱

分析要求：
1. 誠實批判，不為文章的樂觀論點背書，主動尋找反駁論點
2. 護城河和估值兩個維度加倍嚴格
3. 如果文章資訊不足以分析某個維度，明確說明資訊缺口而非猜測"""


def analyze_investment(content: str, source_desc: str) -> dict:
    if not MINIMAX_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY 環境變數未設定。")

    if len(content) > MAX_CONTENT_CHARS:
        print(f"  [提示] 內容較長（{len(content):,} 字元），已截斷至 {MAX_CONTENT_CHARS:,} 字元")
        content = content[:MAX_CONTENT_CHARS] + "\n\n[... 內容已截斷 ...]"

    user_prompt = f"""來源：{source_desc}

以下是投資分析文章或備忘錄的內容，請進行七維度分析並給出評級：

{content}

請嚴格按照 JSON 格式輸出分析結果。"""

    import time
    for attempt in range(3):
        with httpx.Client(timeout=120) as client:
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
                    "system": SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": user_prompt}],
                },
            )
        if r.status_code == 500 and attempt < 2:
            print(f"  [重試 {attempt+1}/2] MiniMax 500，等待 5 秒...")
            time.sleep(5)
            continue
        r.raise_for_status()
        break
    data = r.json()

    raw = ""
    for block in data.get("content", []):
        if block.get("type") == "text":
            raw = block["text"]
            break

    # Strip markdown fences if present
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"subject": source_desc, "rating": "解析失敗", "rating_reason": "API 回傳格式錯誤",
                "raw": raw}


# ---------------------------------------------------------------------------
# 3. Display
# ---------------------------------------------------------------------------

RATING_ICONS = {
    "強烈關注": "★★★★",
    "值得研究": "★★★☆",
    "中性觀望": "★★☆☆",
    "不符標準": "★☆☆☆",
}


def display_result(data: dict, source: str) -> None:
    if "raw" in data:
        print("\n[分析失敗] 原始回傳：")
        print(data["raw"])
        return

    subject = data.get("subject", source)
    rating = data.get("rating", "未知")
    rating_icon = RATING_ICONS.get(rating, "")
    rating_reason = data.get("rating_reason", "")
    ev = data.get("ev_structure", {})
    bull = ev.get("bull", {})
    base = ev.get("base", {})
    bear = ev.get("bear", {})
    bias_list = data.get("bias_scan", [])
    triggers = data.get("invalidation_triggers", [])

    sep = "=" * 56

    print(f"\n{sep}")
    print(f"  投資分析：{subject}")
    print(f"  評級：{rating_icon} {rating}")
    print(f"  {rating_reason}")
    print(sep)

    print(f"\n【護城河】")
    print(f"  {data.get('moat', 'N/A')}")

    print(f"\n【估值安全邊際】")
    print(f"  {data.get('valuation', 'N/A')}")

    print(f"\n【EV 結構】")
    if bull:
        print(f"  牛市 ({bull.get('probability','?')})：{bull.get('scenario','')} → {bull.get('return','')}")
    if base:
        print(f"  基本 ({base.get('probability','?')})：{base.get('scenario','')} → {base.get('return','')}")
    if bear:
        print(f"  熊市 ({bear.get('probability','?')})：{bear.get('scenario','')} → {bear.get('return','')}")
    print(f"  加權期望值：{ev.get('weighted_ev', 'N/A')}")

    print(f"\n【邊際優勢】")
    print(f"  {data.get('edge', 'N/A')}")

    print(f"\n【方差警示】")
    print(f"  {data.get('variance_warning', 'N/A')}")

    if bias_list:
        print(f"\n【認知偏差掃描】")
        for b in bias_list:
            print(f"  - {b}")

    if triggers:
        print(f"\n【論點失效觸發點】")
        for t in triggers:
            print(f"  - {t}")

    print(f"\n{sep}\n")


# ---------------------------------------------------------------------------
# Append analysis to source file (local files only)
# ---------------------------------------------------------------------------

def append_to_file(filepath: str, data: dict) -> None:
    """Append formatted analysis block to the end of the source MD file."""
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    ev = data.get("ev_structure", {})
    bull = ev.get("bull", {})
    base = ev.get("base", {})
    bear = ev.get("bear", {})
    bias_list = data.get("bias_scan", [])
    triggers = data.get("invalidation_triggers", [])
    rating = data.get("rating", "")
    rating_icon = RATING_ICONS.get(rating, "")

    bias_md = "\n".join(f"- {b}" for b in bias_list)
    triggers_md = "\n".join(f"- {t}" for t in triggers)

    block = f"""

---

## AI 投資分析｜{today}

**評級：{rating_icon} {rating}**｜{data.get('rating_reason', '')}

### 護城河
{data.get('moat', '')}

### 估值安全邊際
{data.get('valuation', '')}

### EV 結構
| 情境 | 機率 | 報酬 | 說明 |
|------|------|------|------|
| 牛市 | {bull.get('probability','')} | {bull.get('return','')} | {bull.get('scenario','')} |
| 基本 | {base.get('probability','')} | {base.get('return','')} | {base.get('scenario','')} |
| 熊市 | {bear.get('probability','')} | {bear.get('return','')} | {bear.get('scenario','')} |

**加權期望值**：{ev.get('weighted_ev', '')}

### 邊際優勢
{data.get('edge', '')}

### 方差警示
{data.get('variance_warning', '')}

### 認知偏差掃描
{bias_md}

### 論點失效觸發點
{triggers_md}

> *AI 分析由 MiniMax M2.7 生成，僅供參考。*
"""
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(block)
    print(f"  已補充至：{Path(filepath).name}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(input_str: str) -> None:
    input_type = detect_input_type(input_str)

    print(f"[1/3] 偵測輸入類型：{input_type.upper()}")

    print(f"[2/3] 萃取內容...")
    if input_type == "url":
        content = extract_from_url(input_str)
        source_desc = input_str
        local_path = None
    elif input_type == "pdf":
        content = extract_from_pdf(input_str)
        source_desc = Path(input_str).name
        local_path = None  # PDF 不寫回
    else:
        content = extract_from_text(input_str)
        source_desc = Path(input_str).name
        local_path = input_str

    print(f"      萃取完成：{len(content):,} 字元")

    print(f"[3/3] 呼叫 MiniMax 分析中...")
    result = analyze_investment(content, source_desc)

    display_result(result, source_desc)

    if local_path and "raw" not in result:
        append_to_file(local_path, result)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python invest_analyzer.py <file_path_or_URL>")
        sys.exit(1)
    main(sys.argv[1])
