---
name: yt
description: "把 YouTube 影片字幕轉成地圖版三件組（中文分流稿＋查證地圖＋帶行號英文逐字稿），供 /humanizer-zh 據以寫成文章；模型不寫文章。當用戶貼上 YouTube 網址、提到要摘要 YouTube 影片、想把影片內容轉成文章、或使用 /yt 指令時觸發此技能。適用於任何 YouTube 訪談、演講、Podcast、分析影片。"
---

# /yt — YouTube 影片轉地圖版三件組

⚠️ **`/yt` 不寫文章。** 它把字幕拆成三個下游可以逐句回對的檔案，成文的工作全部交給 `/humanizer-zh`。

為什麼這樣分工：舊版一次要模型同時做翻譯、結構、歸屬、專名、文筆五件事，於是專名就用記憶填了。同一集跑兩次的天然對照顯示，三整段虛構全部出現在「寫文章」那一步，而分段索引、專名標記這些窄任務它做得對。把模型的任務縮窄，錯就少了。

四層分工，每層只做自己最不會錯的事：

| 層 | 誰做 | 做什麼 |
|---|---|---|
| 確定性 | 純 Python | 數字表、拼字變體分群、廣告偵測、未完成句。不呼叫模型，不會幻覺 |
| 苦力 | MiniMax M3 | 分段、輪次、論點、引述候選、可疑專名。**跑兩次取交集** |
| 分流 | 使用者 | 讀分流稿決定這集要不要做 |
| 寫作 | `/humanizer-zh` | 讀英文逐字稿＋地圖寫文章。**中文只產生一次，出自最會寫中文的那層** |

## 使用方式

```
/yt <YouTube URL>
```

## 執行流程

### Step 1: 執行主腳本

**一定要用 venv 那支 python。** 這台機器沒有 `python`，系統 `python3` 缺 `httpx`，只有 venv 能跑：

```bash
/Users/slking/Documents/訪談摘要/.venv/bin/python \
  "<skill-path>/scripts/ytmap/yt_triage.py" "<YouTube URL>"
```

`yt_triage.py` 介面跟舊版相容（同樣吃 URL 與 `--lang`）。它 `import yt_to_article` 重用抓字幕那一段（Whisper fallback、yt-dlp 退路、VTT 解析都沿用，不重寫），只換掉「叫模型寫文章」那一段；同時這個 import 會載入 `ytkit.config`，把 repo 根 `.env` 灌進 `os.environ`，子行程才拿得到 API key。

腳本會自動：
1. 解析 URL 取 video_id，用 `youtube-transcript-api` 抓字幕（優先 zh-TW → zh → en → 任何可用；字幕不可用時退到本地 Whisper 轉錄）
2. 用 `yt-dlp --dump-json` 取 metadata（標題、頻道、日期）
3. **原文逐字稿一律另存 `<base>_transcript.txt`**（`final_gate.py` 與 humanizer 對帳的 ground truth）
4. 把逐字稿與 metadata 交給 `ytmap/run_pipeline.py` 跑六步（下節）

### Step 2: 確認結果

告知使用者三件組路徑與體檢表（`health`）。三件組不是成品，是給人分流、給 humanizer 寫作用的中間產物。要拿到文章，接著跑 `/humanizer-zh <分流稿路徑>`（走 C 路）。

## 六步管線（`ytmap/run_pipeline.py`）

```
[1/6] normalize_transcript  單行字幕 → 一句一行。行號在這裡固定，是全流程的錨點
[2/6] build_index           純 Python：數字表、拼字變體群、廣告、未完成句
[3/6] map_minimax ×2        跑 A、B 兩份獨立地圖，各自再跑 dedupe_claims 合併重複論點
[4/6] merge_maps            兩份合流，產體檢表
[5/6] triage_minimax        寫中文分流稿
[6/6] strip_markers         把查證標記從正文抽進 JSON
```

**為什麼跑兩次**：模型的錯是隨機的，規則管不了隨機性，但便宜的重複可以。兩份都標到的進 `claims_confirmed`，只有一邊標到的進 `claims_single` 並註明可靠度低。

**chunk 是 150 行，不要為了省呼叫次數放大。** 實測不是輸出吐不完（`max_tokens` 開到 65536 只用了 4000），是**輸入越長模型抽得越少**：150 行給 25 條論點，500 行給 24 條，800 行給 32 條。放大 chunk 會得到一份看起來完整、實際只抓到四分之一的地圖，而且從外觀看不出來。

**可續跑**：地圖與分流稿是最貴的兩步（一集長談的 API 呼叫以十分鐘計），每步檢查產物存在就跳過。要重做就刪工作目錄 `.{base}_work/`。

## 輸出格式

存入 `.env` 的 `YT_OUTPUT_DIR`（本機為 `/Users/slking/Documents/Obsidian Vault/投資筆記/每週總結/每日研究`）。

```
<base>_分流稿.md     中文分流稿，給人讀，用來決定這集要不要做
<base>_map.json      地圖，查證資訊全在這，給 humanizer
<base>_lines.txt     帶行號的英文逐字稿，行號是全流程錨點
<base>_transcript.txt 原始字幕
.{base}_work/        中間產物（可續跑用）
```

分流稿的 frontmatter：

```yaml
---
type: yt_triage
date: YYYY-MM-DD
source: YouTube
youtube_url: <URL>
channel: <頻道名>
video_title: <未經檔名截斷的原標題>
upload_date: YYYYMMDD
map: <base>_map.json
transcript_lines: <base>_lines.txt
note: 分流稿。用途是判斷這集要不要進 humanizer。查證資訊全在 map JSON，不在正文。
---
```

**metadata 那幾行不是裝飾。** C 路的 humanizer 只讀分流稿與 `_lines.txt`，metadata 不進 frontmatter 就等於整條線遺失了原始連結與真標題，成品只能從檔名回推（檔名為了避開 Windows 路徑上限已經截斷過），HackMD 上就沒有出處可點。欄位名刻意跟舊版 `yt_article` 一致，下游兩條路才不必各寫一套讀法。實際踩過：2026-08-07 那批 16 集全部沒有 URL，工作目錄裡也沒留 video_id，事後救不回來。

分流稿的規格**跟成品相反**：寧可長寧可雜、具體細節一律保留，而且是機器翻的。它不是寫作素材，下游不得拿它當底稿，也不得編輯它。

## 退回舊版

watcher 用環境變數 `YT_MODE` 切換，預設 `triage`：

```bash
YT_MODE=article   # 走 yt_to_article.py
```

⚠️ **這台的 `yt_to_article.py` 是順稿版（中文全文順稿，`type: yt_transcript_zh`），不是更早的文章版。** 退回去得到的是依字幕順序、說話人前綴、無小標的全文順稿，humanizer 對它走的是另一條路。順稿版自己的機械閘門（覆蓋率下限、`##` 小標、`>>` 殘留、說話人標籤種類數、舞台指示、破折號、假名／諺文殘留等，違規即重生最多 3 次）只在 `YT_MODE=article` 時才會作用，地圖版沒有那一層，它的品質靠「兩份地圖取交集」與下游回原文核對。

## 排程

`yt_channel_watcher.py` 依 `channels.json` / `channels_intl.json` 輪巡，本機的國際輪巡由 launchd `com.slking.yt-intl-watcher` 每天 07:00 觸發，跑的是**工作目錄當下 checkout 的分支**。切分支會連帶換掉實際上線的腳本，而且沒有任何提示。單支影片的 timeout 是 5400 秒。

## 環境需求

- **Python 3.9.6（venv）**。ytmap 全部腳本都有 `from __future__ import annotations`，3.9 可跑；系統 `python3` 缺 `httpx`，不能用
- 套件：`youtube-transcript-api`, `yt-dlp`, `httpx`；Whisper fallback 另需 `mlx-whisper`
- 環境變數：`ANTHROPIC_API_KEY`（MiniMax Token Plan key，`sk-cp-` 開頭；用 `sk-api-` 會回 402）、`ANTHROPIC_BASE_URL`（預設 https://api.minimax.io/anthropic）、`MINIMAX_MODEL`（預設 MiniMax-M3）。由 repo 根 `.env` 經 `ytkit/config.py` 載入

## 錯誤處理

- **無字幕**：自動退到本地 Whisper 轉錄。多支影片不要同時轉錄，單機 MLX 記憶體會搶，逐支跑
- **全部影片同報「沒字幕」**：多半是 YouTube 對這個 IP 的封鎖（IpBlocked/429），不是影片真的沒字幕。要真的下載一次才驗得出來，只 list 看不出來
- **API 失敗**：檢查 key 開頭是不是 `sk-cp-`、餘額是否充足
- **中途壞掉**：直接重跑，六步各自會沿用既有產物；要整集重做就刪 `.{base}_work/`
