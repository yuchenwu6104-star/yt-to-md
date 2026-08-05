---
name: yt
description: "將 YouTube 影片字幕順成中文全文順稿（依字幕順序、說話人前綴、不選材不摘要），供 /humanizer-zh 據以寫成文章。當用戶貼上 YouTube 網址、提到要摘要 YouTube 影片、想把影片內容轉成文章、或使用 /yt 指令時觸發此技能。適用於任何 YouTube 訪談、演講、Podcast、分析影片。"
---

# /yt — YouTube 影片轉中文全文順稿

把 YouTube 影片的字幕，透過 MiniMax M3 API 順成一份**忠實、完整、通順的繁體中文全文**，並自動存入 Obsidian vault。

⚠️ **`/yt` 不寫文章。** 它的職責只有兩件事：**不漏、不編**。選材、脈絡、敘事結構、引述取捨這些「成文」的工作，全部交給下游 `/humanizer-zh`。

為什麼這樣分工：`/yt` 同時做搬運與寫作時，兩種錯誤會互相掩護——實測 Gavin Baker 篇，72k 字元英文字幕被壓成 3.3 萬中文字的文章，其中長出一整段字幕查無的捏造內容（H20 清庫存、6,000 億 capex 之類），而講者原話只佔 39%。把順稿與成文拆開後，humanizer 拿到的是一份可以逐句對回字幕的中間產物，幻覺無處藏。

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
4. 將字幕 + metadata 送入 MiniMax M3 API **順稿**：依字幕順序從頭順到尾，去語塞、修 ASR 誤聽、譯成自然繁中，**不選材、不摘要、不重排、不下小標、不補任何字幕沒有的內容**。長字幕依語言切段（英文 ~16k、中文 ~8k、日韓 ~12k 字元／段，最多 16 段），確保單段輸出不撞上 16,384 token 上限被截斷
5. 格式化為 markdown（含 YAML frontmatter）並存入 Obsidian vault
6. **原文逐字稿一律另存 `<檔名>_transcript.txt`**（humanizer 對帳的 ground truth）

### Step 2: 確認結果

腳本執行完畢後，告知用戶：
- 順稿標題
- 儲存路徑
- 字幕語言與長度

順稿只是中間產物，不是成品。要拿到可讀的文章，接著跑 `/humanizer-zh <順稿路徑>`。

## 順稿規格

`<basename>.md` 的正文是**中文全文順稿**，不是文章：

- 依字幕順序**從頭順到尾**，不選材、不摘要、不重排、不下小標、不寫串接句、不寫導言與結語
- 用**說話人前綴行**呈現：`Baker：……` / `主持人：……`。說話人不明時用 `講者：`，或依字幕的 `>>` 換手標記處理。**禁止猜名字**
- 把口語順成通順繁中：去掉 uh/um、重複語塞，修掉 ASR 明顯亂詞（`training` 被聽成 `trading` 之類），但**不增刪講者的意思**
- 逐段對應字幕，一個話題一段。長度**接近字幕的資訊量，不做壓縮**
- **絕對不補字幕沒有的內容**：不補專名、不補數字、不補因果、不補背景知識。ASR 亂碼重建不出來就照原樣留著並標 `[ASR 存疑]`
- 量級照樣要換算正確：million＝百萬、billion＝十億、trillion＝兆
- 破折號零容忍

## 機械閘門（`format_violations()`，違規即重生，最多 3 次）

順稿最重要的一關是**覆蓋率**：成稿中文字數 ÷ 字幕字元數低於下限即判違規並重生。門檻依來源語言分三段（英文 0.18／中文 0.42／日韓 0.32，期望值約 0.30／0.72／0.55），校準依據寫在 `_coverage_floor()` 上方註解。其餘閘門：`##` 小標題、說話人前綴覆蓋率（< 60% 判為又寫成文章了）、舞台指示／報幕詞／語氣打分、非中性引述動詞、破折號、假名／諺文殘留、西里爾字母、`<think>` 殘留、JSON 殘留、長段落重複、分段後台資訊洩漏。

stderr 的 `[note]` 保留兩類需要人／下游裁決的訊號：字幕查無對應的英文專名（可能是捏造，也可能只是字幕拼錯），以及覆蓋率雖未觸發重生但偏低的提醒。

## 輸出格式

順稿存入：`.env` 的 `YT_OUTPUT_DIR`（本機為 `/Users/slking/Documents/Obsidian Vault/投資筆記/每週總結/每日研究`）

檔名格式：`YYYY-MM-DD_yt_頻道名_主題關鍵字.md`

```markdown
---
type: yt_transcript_zh
date: YYYY-MM-DD
source: YouTube
youtube_url: <URL>
channel: <頻道名>
video_title: <影片標題>
tags: [標籤]
---

# <一句話說明這支影片在談什麼>

> 原始影片：[標題](URL) | 頻道 | 日期

主持人：<這一段他說的話>

Baker：<這一段他說的話>

主持人：<……依字幕順序一路到最後>

---
*本檔為 YouTube 影片字幕的中文全文順稿（AI 生成，未做編輯取捨），僅供參考。*
```

## 環境需求

- Python 3.10+
- 套件：`youtube-transcript-api`, `yt-dlp`, `httpx`
- 環境變數：`ANTHROPIC_API_KEY`（MiniMax Token Plan key, sk-cp-...）、`ANTHROPIC_BASE_URL`（預設 https://api.minimax.io/anthropic）

## 錯誤處理

- **無字幕**：告知用戶該影片沒有可用字幕，建議選擇有字幕的影片
- **API 失敗**：檢查 API key 是否正確、餘額是否充足
- **字幕太長**：自動依語言切段多次順稿後合併（不是截斷）；單段 60,000 字元只是最後安全網
