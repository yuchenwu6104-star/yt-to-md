# Mac 本機設定（此台機器）

分支：**master**（完整可移植版）。設定由 Claude 於 2026-06-23 完成。

## 已安裝
- Homebrew：`yt-dlp`、`ffmpeg`
- Python venv：`/Users/slking/Documents/訪談摘要/.venv`
  - 套件：youtube-transcript-api, yt-dlp, httpx, **opencc**（/yt 簡轉繁必需）, ebooklib, beautifulsoup4, lxml, pdfplumber
  - `mlx-whisper`：✅ 已裝（無字幕影片本地轉錄；模型 `mlx-community/whisper-large-v3-turbo` 首次轉錄自動下載 ~1.5GB）

## 設定檔
`<repo>/.env`（即 `yt-to-md/.env`）— `ytkit/config.py` 會自動讀取。
- `ANTHROPIC_API_KEY`：MiniMax key（已填）
- `YT_OUTPUT_DIR`：Obsidian 落檔路徑（已填）
- `HACKMD_API_TOKEN`：**未填**，要 humanizer 自動上傳 HackMD 才需要
- `WHISPER_DEVICE=auto`：Mac 會自動走 MLX

## 技能（從 repo .claude/skills 自動偵測）
- `/yt`、`/epub`、`/invest`、`/humanizer-zh`
- `/fb` 已在 master 退役

## 執行（用 venv python；scripts 會自己用 ytkit.config 讀 .env）
```bash
PY=/Users/slking/Documents/訪談摘要/.venv/bin/python
$PY .claude/skills/yt/scripts/yt_to_article.py "<YouTube URL>"
$PY .claude/skills/yt/scripts/transcribe.py "<URL>"          # 無字幕備援（需 mlx-whisper）
$PY .claude/skills/yt/scripts/yt_channel_watcher.py          # 頻道輪巡
$PY .claude/skills/invest/scripts/invest_analyzer.py "<檔案/URL>"
$PY .claude/skills/epub/scripts/epub_to_articles.py "<epub>"
$PY .claude/skills/humanizer-zh/scripts/upload_hackmd.py "<md>"   # 需 HACKMD_API_TOKEN
```

## 狀態：全部就緒 ✅
- ✅ MiniMax：必須用 **Token Plan 的 Subscription Key（`sk-cp-...`）**，不是 pay-as-you-go 的 `sk-api-...`（兩者錢包不互通，用錯會回 402 insufficient_balance）。Subscription Key 來源：https://platform.minimax.io/user-center/payment/token-plan
- ✅ HackMD token 已設並驗證（帳號「停損王SLKing」，團隊 `slking`；上傳可加 `--team slking`）。
- ✅ mlx-whisper 已裝（無字幕影片本地轉錄）。

## 重要：設定檔只有一個
- 真正生效的是 **repo 根 `.env`**（`yt-to-md/.env`）。
- `~/.config/yt-to-md/.env` 已改成指向它的 **symlink**，編輯哪邊都一樣，不會再放錯。
- GitHub 預設分支仍是舊的 `main`；完整版在 `master`。
