---
name: yt
description: "將 YouTube 影片轉為深度洞察文章。當用戶貼上 YouTube 網址、提到要摘要 YouTube 影片、想把影片內容轉成文章、或使用 /yt 指令時觸發此技能。適用於任何 YouTube 訪談、演講、Podcast、分析影片的內容搬運與深度改寫。"
---

# /yt — YouTube 影片轉深度洞察文章

將 YouTube 影片的字幕內容，透過 MiniMax M2.7 API 轉化為一篇有故事性、有分析觀點的繁體中文深度文章，並自動存入 Obsidian vault。

## 使用方式

```
/yt <YouTube URL>
```

## 執行流程

收到 YouTube URL 後，依序執行以下步驟：

### Step 1: 執行主腳本

運行 bundled script 完成整個流程：

```bash
python "<skill-path>/scripts/yt_to_article.py" "<YouTube URL>"
```

腳本會自動：
1. 解析 URL 提取 video_id
2. 用 `youtube-transcript-api` 抓取字幕（優先：zh-TW → zh → en → 任何可用）
3. 用 `yt-dlp --dump-json` 取得影片 metadata（標題、頻道、日期）
4. 將字幕 + metadata 送入 MiniMax M2.7 API，生成結構化的深度洞察文章
5. 格式化為 markdown（含 YAML frontmatter）並存入 Obsidian vault

### Step 2: 確認結果

腳本執行完畢後，告知用戶：
- 文章標題
- 儲存路徑
- 字幕語言與長度

如果用戶對文章不滿意，可以：
- 要求調整特定段落
- 要求重新生成（加入額外指示）
- 手動在 Obsidian 中編輯

## 輸出格式

文章存入：`C:\Users\wukee\OneDrive\文件\Obsidian Vault\投資筆記\每週總結\每日研究`

檔名格式：`YYYY-MM-DD_yt_頻道名_主題關鍵字.md`

文章結構：
```markdown
---
type: yt_article
date: YYYY-MM-DD
source: YouTube
youtube_url: <URL>
channel: <頻道名>
video_title: <影片標題>
tags: [標籤]
---

# <洞察文章標題>

> 原始影片：[標題](URL) | 頻道 | 日期

<導言 2-3 段>

## <小標題 1>
<深度分析內容>

## <小標題 2-6>
...

## 結語
<總結洞察>

---
*本文由 AI 根據 YouTube 影片內容生成，僅供參考。*
```

## 環境需求

- Python 3.10+
- 套件：`youtube-transcript-api`, `yt-dlp`, `httpx`
- 環境變數：`ANTHROPIC_API_KEY`（MiniMax Token Plan key, sk-cp-...）、`ANTHROPIC_BASE_URL`（預設 https://api.minimax.io/anthropic）

## 錯誤處理

- **無字幕**：告知用戶該影片沒有可用字幕，建議選擇有字幕的影片
- **API 失敗**：檢查 API key 是否正確、餘額是否充足
- **字幕太長**：自動截斷至 60,000 字元，不影響文章品質
