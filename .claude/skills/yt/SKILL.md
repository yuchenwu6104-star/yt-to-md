---
name: yt
description: "將 YouTube 影片轉為深度洞察文章。當用戶貼上 YouTube 網址、提到要摘要 YouTube 影片、想把影片內容轉成文章、或使用 /yt 指令時觸發此技能。適用於任何 YouTube 訪談、演講、Podcast、分析影片的內容搬運與深度改寫。"
---

# /yt — YouTube 影片轉深度洞察文章

將 YouTube 影片的字幕內容，透過 MiniMax M3 API 編輯成一篇完整、好讀、有講者聲音的繁體中文長文，並自動存入 Obsidian vault。原稿本身就要值得閱讀，不能把報幕句、內容預告、引述複述或僵硬段落留給 humanizer 收拾。

## 使用方式

```
/yt <YouTube URL>
```

## 執行流程

收到 YouTube URL 後，依序執行以下步驟：

### Step 1: 執行主腳本

運行 bundled script 完成整個流程：

```bash
/Users/slking/Documents/訪談摘要/.venv/bin/python \
  "<skill-path>/scripts/yt_to_article.py" "<YouTube URL>"
```

腳本會自動：
1. 解析 URL 提取 video_id
2. 用 `youtube-transcript-api` 抓取字幕（優先：zh-TW → zh → en → 任何可用；字幕不可用時自動退到本地 Whisper 轉錄）
3. 用 `yt-dlp --dump-json` 取得影片 metadata（標題、頻道、日期）
4. 將字幕 + metadata 送入 MiniMax M3 API，完成主題盤點、選材、敘事結構、引述取捨與中文寫作。M3 只可轉述低歧義、語氣普通的連續資訊；數字、否定、因果、比較、條件、利益揭露與立場強度優先保留為引述。每個主要主題至少選一段最能代表講者語氣或論證方式的直接引述，不能把全文磨成第三人稱摘要。長逐字稿依語言切段（中文 ~12k、英文 ~20k、日韓 ~18k 字元／段），確保重要內容完整承載
5. 格式化為 markdown（含 YAML frontmatter）並存入 Obsidian vault
6. **原文逐字稿一律另存 `<檔名>_transcript.txt`**（humanizer 對帳的 ground truth）。`$yt` 自己負責消除已偵測到的串接複述；stderr 的 `[note]` 僅保留需要逐字稿或外部查證才能裁決的專名與覆蓋風險

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

文章存入：`.env` 的 `YT_OUTPUT_DIR`（本機為 `/Users/slking/Documents/Obsidian Vault/投資筆記/每週總結/每日研究`）

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

<精簡導言>

## <小標題 1>
<深度分析內容>

## <依內容需要安排的小標題>
...

## 結語
<總結洞察>

---
*本文根據 YouTube 影片內容由 AI 整理生成，僅供參考。*
```

## 環境需求

- Python 3.10+
- 套件：`youtube-transcript-api`, `yt-dlp`, `httpx`
- 環境變數：`ANTHROPIC_API_KEY`（MiniMax Token Plan key, sk-cp-...）、`ANTHROPIC_BASE_URL`（預設 https://api.minimax.io/anthropic）

## 錯誤處理

- **無字幕**：告知用戶該影片沒有可用字幕，建議選擇有字幕的影片
- **API 失敗**：檢查 API key 是否正確、餘額是否充足
- **字幕太長**：自動依語言切段多次生成後合併（不是截斷）；單段 60,000 字元只是最後安全網
