#!/usr/bin/env python3
"""
md_to_fb.py
將 Obsidian 落檔的深度文章改寫為 Facebook 貼文格式，存入 FB文章候選 目錄。

用法：
    python md_to_fb.py <文章路徑>
    python md_to_fb.py 2026-03-31_yt_GQ_Taiwan_華爾街交易員.md   # 自動在每日研究查找
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# 路徑設定
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent
DAILY_DIR = Path(
    r"C:\Users\wukee\OneDrive\文件\Obsidian Vault\投資筆記\每週總結\每日研究"
)
OUTPUT_DIR = Path(
    r"C:\Users\wukee\OneDrive\文件\Obsidian Vault\投資筆記\每週總結\FB文章候選"
)

# 讀取 .env（與 yt_to_article.py 共用同一個 .env）
_ENV_FILE = Path(
    r"C:\Users\wukee\OneDrive\文件\clon資料\taiwan_stock_dashboard\美股資料\.env"
)
if not os.getenv("ANTHROPIC_API_KEY") and _ENV_FILE.exists():
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

MINIMAX_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.minimax.io/anthropic")
MINIMAX_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MINIMAX_MODEL = "MiniMax-M2.7"

# ---------------------------------------------------------------------------
# Facebook 格式說明與 few-shot 樣板
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
你是一位擅長將深度文章改寫為 Facebook 貼文的內容寫手。
你的任務是分享洞察、引發思考，不是教育觀眾。

Facebook 貼文格式規則：
1. 開場 1-2 段純文字，點出講者/受訪者背景與核心論點，不加任何 # 標籤
2. 正文用 #標題 作為段落開頭，同時 #重要概念 可嵌入段落內文做強調
3. 每段約 100-150 字，純文字，不使用任何 markdown 符號（無 **、無 -、無 ##）
4. 總長度 600-900 字
5. 結尾段落不加標題，自然收束，可呼籲或總結
6. 不加 emoji
7. 不在文末列出 hashtag 清單

以下是一個完整的格式樣板，請嚴格遵照此風格輸出：

---
CrowdStrike 執行長 George Kurtz 在 RSAC 2026 帶來的演講，揭示了網路安全公司在面對 AI 爆炸式發展時的策略轉型。
他強調，我們已經度過了對 AI 充滿好奇的「碰撞測試」階段，現在必須建立一套真正的「指揮標準」來治理這些具有自主能力的系統。

#24個月內的質變：機器將成為組織內「最聰明的員工」
George Kurtz 在開場就拋出一個大膽的預測：「在未來 24 個月內，你組織中最聰明的員工實際上會是一台機器。」這不僅是技術能力的提升，更是組織結構的根本改變。
他認為，目前的網路安全已經不再只是防禦外部攻擊，而是要管理內部那些具備高度自主權的 AI。他指出：「AI 系統在短期內往往會被過度神化，但我們卻嚴重低估了它在中長期對企業運作模式的顛覆性影響。」

#AI是新的作業系統：重塑防禦架構
Kurtz 指出，我們正處於一個作業系統轉型的時代。過去我們保護 Windows 或 Linux，但現在，AI 模型本身就是一種新的作業系統。「就像早期的作業系統充滿漏洞一樣，現在的 AI 系統也正處於脆弱期。」

#企業大規模部署 AI 的三大核心障礙
根據與多位 CEO 及 AI 實驗室的交流，Kurtz 歸納出三個主要問題。
第一是 #隱形推理：AI 的決策過程往往是黑盒子，缺乏可追蹤的思維鏈。
第二是缺失的 #斷路器（Circuit Breaker）：當 AI 開始執行錯誤或具威脅性的操作時，缺乏即時阻斷機制。
第三是 #速度錯配（Speed Mismatch）：威脅移動與 AI 演進的速度已遠超人類處理的能力。

#安全是為了開得更快
最後，Kurtz 用賽車做了一個生動的比喻：「很多人認為安全措施是阻礙成長的絆腳石，但事實上，賽車之所以能開到時速 300 公里，是因為它有全世界最好的煞車和防滾籠。安全帶的存在不是為了限制你，而是為了讓你安全地跑得比對手更快。」
他呼籲企業主不應因為恐懼而禁用 AI，而是應該建立起一套包含「營運可視性」、「人類控制」與「集體韌性」的指揮標準，在確保安全的基礎上全力加速。
---

請完全按照此風格輸出，不要加任何額外說明或前言。"""


# ---------------------------------------------------------------------------
# 解析輸入文章
# ---------------------------------------------------------------------------

def resolve_path(arg: str) -> Path:
    """支援完整路徑或只傳檔名（自動在 DAILY_DIR 查找）。"""
    p = Path(arg)
    if p.is_absolute() and p.exists():
        return p
    candidate = DAILY_DIR / p.name if not p.is_absolute() else p
    if candidate.exists():
        return candidate
    # 模糊查找（不含副檔名）
    name = p.stem
    matches = list(DAILY_DIR.glob(f"*{name}*.md"))
    if matches:
        return matches[0]
    raise FileNotFoundError(f"找不到文章：{arg}")


def parse_article(filepath: Path) -> tuple[dict, str]:
    """解析 markdown 文章，回傳 (frontmatter_dict, body_text)。"""
    content = filepath.read_text(encoding="utf-8")

    frontmatter = {}
    body = content

    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            fm_text = content[3:end].strip()
            body = content[end + 3:].strip()
            for line in fm_text.splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    frontmatter[k.strip()] = v.strip().strip('"')

    return frontmatter, body


# ---------------------------------------------------------------------------
# 呼叫 MiniMax API
# ---------------------------------------------------------------------------

def call_minimax(body: str, frontmatter: dict) -> str:
    if not MINIMAX_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY 環境變數未設定。"
        )

    title = frontmatter.get("video_title", "")
    channel = frontmatter.get("channel", "")
    youtube_url = frontmatter.get("youtube_url", "")

    user_prompt = f"""請將以下深度文章改寫為 Facebook 貼文。

原始影片資訊：
- 標題：{title}
- 頻道：{channel}
- 連結：{youtube_url}

原文內容：
{body}

請按照 system prompt 中的格式樣板，輸出一篇 600-900 字的 Facebook 貼文。
直接輸出貼文內容，不要加任何說明或前言。"""

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
        r.raise_for_status()
        data = r.json()

    for block in data.get("content", []):
        if block.get("type") == "text":
            return block["text"].strip()
    return data.get("content", [{}])[-1].get("text", "").strip()


# ---------------------------------------------------------------------------
# 儲存
# ---------------------------------------------------------------------------

def save_fb_post(text: str, source_path: Path) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")

    # 從原檔名提取關鍵字（去掉日期和 _yt_ 前綴）
    stem = source_path.stem
    stem = re.sub(r"^\d{4}-\d{2}-\d{2}_yt_", "", stem)
    stem = stem[:60]

    filename = f"{today}_fb_{stem}.md"
    filepath = OUTPUT_DIR / filename
    filepath.write_text(text, encoding="utf-8")
    return filepath


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(arg: str):
    print(f"[1/4] 解析文章路徑...")
    filepath = resolve_path(arg)
    print(f"      來源：{filepath.name}")

    print(f"[2/4] 讀取文章內容...")
    frontmatter, body = parse_article(filepath)
    print(f"      標題：{frontmatter.get('video_title', '未知')[:50]}")
    print(f"      字數：{len(body)} 字元")

    print(f"[3/4] 呼叫 MiniMax 改寫為 FB 格式...")
    fb_text = call_minimax(body, frontmatter)
    print(f"      生成長度：{len(fb_text)} 字元")

    print(f"[4/4] 儲存...")
    out_path = save_fb_post(fb_text, filepath)
    print(f"      已儲存：{out_path}")

    return str(out_path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python md_to_fb.py <文章路徑或檔名>")
        sys.exit(1)
    result = main(sys.argv[1])
    print(f"\n完成！FB 貼文已儲存至：{result}")
