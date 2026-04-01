# yt-to-md — YouTube 訪談轉深度洞察文章

將 YouTube 影片字幕透過 MiniMax M2.7（或任何 Anthropic 相容 API）轉換為繁體中文深度分析文章，並自動落檔至 Obsidian vault。支援每日自動輪巡多個頻道、Facebook 貼文改寫、ePub 電子書摘要、投資備忘錄分析。

---

## 功能一覽

| 腳本 | 功能 |
|------|------|
| `yt_to_article.py` | 單支影片 URL → 深度洞察文章（Markdown） |
| `yt_channel_watcher.py` | 每日自動輪巡頻道，批次處理新影片 |
| `md_to_fb.py` | 深度文章 → Facebook 貼文格式 |

---

## 環境需求

- Python 3.10+
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- MiniMax API key（或其他 Anthropic 相容 API）

```bash
pip install youtube-transcript-api yt-dlp httpx
```

---

## 設定

### 1. 環境變數

建立 `.env` 檔案（或直接設定環境變數）：

```env
ANTHROPIC_API_KEY=sk-cp-xxxxxxxxxxxxxxxx
ANTHROPIC_BASE_URL=https://api.minimax.io/anthropic
```

- **MiniMax**：API key 格式為 `sk-cp-...`，Base URL 為 `https://api.minimax.io/anthropic`
- **其他 Anthropic 相容 API**：替換對應的 key 與 base URL 即可

### 2. 修改輸出路徑

在 `yt_to_article.py` 和 `md_to_fb.py` 中，將 `OUTPUT_DIR` 改為你的 Obsidian vault 路徑：

```python
# yt_to_article.py
OUTPUT_DIR = Path(r"C:\path\to\your\Obsidian Vault\每日研究")

# md_to_fb.py
FB_OUTPUT_DIR = Path(r"C:\path\to\your\Obsidian Vault\FB文章候選")
```

### 3. 設定輪巡頻道

編輯 `channels.json`：

```json
{
  "settings": {
    "min_duration_minutes": 15,
    "max_per_channel": 5
  },
  "channels": [
    {"name": "a16z", "handle": "@a16z", "category": "VC", "enabled": true},
    {"name": "Lex Fridman", "handle": "@lexfridman", "category": "Tech", "enabled": true}
  ]
}
```

---

## 使用方式

### 單支影片

```bash
python yt_to_article.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

### 批次輪巡所有頻道

```bash
python yt_channel_watcher.py
```

處理過的影片 ID 記錄於 `processed_videos.json`，重複執行不會重複處理。

### 文章轉 Facebook 貼文

```bash
python md_to_fb.py "path/to/article.md"
```

---

## 每日自動排程（Windows）

使用工作排程器，每天早上 8:00 執行：

1. 開啟「工作排程器」→「建立基本工作」
2. 觸發程序：每天 08:00
3. 動作：執行程式
   - 程式：`python`
   - 引數：`"C:\path\to\scripts\yt_channel_watcher.py"`
   - 起始位置：`C:\path\to\scripts\`

---

## 輸出格式

文章以 YAML frontmatter + Markdown 儲存：

```markdown
---
type: yt_article
date: 2026-04-01
source: YouTube
youtube_url: https://www.youtube.com/watch?v=...
channel: "Lex Fridman"
video_title: "..."
tags: ["AI", "科技"]
---

# 文章標題

> 原始影片：[標題](URL) | 頻道 | 日期

導言...

## 小標題

分析內容...
```

---

## 預設追蹤頻道

| 頻道 | Handle | 類別 |
|------|--------|------|
| a16z | @a16z | VC |
| All-In Podcast | @allin | VC |
| Y Combinator | @ycombinator | Tech |
| Lex Fridman | @lexfridman | Tech |
| 20VC | @20VC | VC |
| Acquired | @AcquiredFM | VC |
| Invest Like the Best | @joincolossus | VC |
| BG2 Pod | @BG2Pod | VC |
| Dwarkesh Podcast | @DwarkeshPatel | Tech |
| Odd Lots | @BloombergPodcasts | Macro |
| In Good Company | @NorgesBankInvestmentManagement | Macro |

---

## 注意事項

- `processed_videos.json` 與 `watcher.log` 為本地執行狀態，已加入 `.gitignore`，clone 後首次執行會自動建立
- Windows 使用者若遇到中文編碼問題，請確保以 `PYTHONIOENCODING=utf-8` 執行，或腳本已內建 `sys.stdout.reconfigure`
- YouTube 字幕優先順序：zh-TW → zh → en → 任何可用語言
