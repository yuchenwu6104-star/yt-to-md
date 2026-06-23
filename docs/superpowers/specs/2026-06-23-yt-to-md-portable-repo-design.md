# yt-to-md 可移植 repo 打包設計

**日期：** 2026-06-23
**狀態：** 已核准，待實作
**目標：** 把現有「YouTube → 深度文章 → humanizer 編修 → HackMD」整套 pipeline 打包成單一可 clone 的 repo，讓使用者在另一台 MacBook（Apple Silicon）`git clone` + 跑安裝腳本後，即獲得完整 knowhow，路徑與金鑰皆參數化、不綁特定機器。

---

## 1. 背景與問題

現有狀態（`訪談摘要` 資料夾本身就是 git repo `yt-to-md`，origin = github.com/yuchenwu6104-star/yt-to-md）可移植性極差：

- **技能散在多處且重複**：`.claude/skills/yt/`（完整版）、`yt/`（半殘副本，只有 `yt_to_article.py`）、`~/.claude/skills/humanizer-zh/`（**完全不在 repo 內，clone 帶不走**）。
- **綁死 Windows / 本機路徑**：
  1. `yt_to_article.py` 的 MiniMax 金鑰去讀另一個專案的 `...taiwan_stock_dashboard\美股資料\.env`，Mac 上不存在 → 必爆。
  2. `OUTPUT_DIR` 寫死 `C:\Users\wukee\...\Obsidian Vault\...\每日研究`。
  3. `transcribe.py` 寫死 `device="cuda"` + 載 NVIDIA CUDA DLL → MacBook 沒 NVIDIA GPU，整段跑不動。
  4. `humanizer-zh/SKILL.md` 內呼叫腳本用寫死的 `C:\Users\wukee\...` 絕對路徑。
- **根目錄垃圾**：`_whisper_*.txt`、`_tmp_yt_whisper.py`、`_m3_test/`、`watcher.log`、`sync_channels.ps1`。

## 2. 已確認的需求決策

| 項目 | 決定 |
|---|---|
| 打包形式 | Claude Code 技能包 **＋** yt 主流程也能純 CLI 跑（humanizer 仍需 Claude 執行其 prompt）|
| 落檔位置 | Mac 一樣落 Obsidian，但路徑不同 → 做成每台機器可設定（`YT_OUTPUT_DIR`）。HackMD 上傳邏輯不變 |
| Whisper（Mac）| Apple Silicon，要能本地轉錄 → 加 `mlx-whisper`，裝置自動偵測（Windows 走 CUDA、Mac 走 MLX）|
| 金鑰位置 | repo 根目錄 `.env`（HackMD 仍相容舊的 `~/.claude/.env` 作為回退）|
| 範圍 | 含頻道監看，但不用 cron/launchd，做成可手動啟動的輪巡 |
| 打包路線 | 路線 A：單一來源 repo ＋ 安裝腳本 symlink 技能進 `~/.claude/skills`（`--copy` 為退路）|

## 3. 目標目錄結構

```
yt-to-md/
├── README.md              整套 knowhow + 安裝步驟（重寫）
├── .env.example           所有金鑰/路徑範本
├── .gitignore             忽略 .env、output/、*.log、__pycache__、執行期狀態
├── install.sh             Mac/Linux：檢查依賴 + symlink 技能進 ~/.claude/skills
├── install.ps1            Windows 對應版（symlink，--copy 退路）
├── requirements.txt       共用依賴
├── ytkit/
│   ├── __init__.py
│   └── config.py          共用設定載入器
└── skills/
    ├── yt/
    │   ├── SKILL.md
    │   └── scripts/
    │       ├── yt_to_article.py
    │       ├── transcribe.py
    │       ├── yt_channel_watcher.py
    │       ├── channels.json
    │       └── md_to_fb.py
    └── humanizer-zh/
        ├── SKILL.md
        └── scripts/
            └── upload_hackmd.py
```

安裝器把 `~/.claude/skills/yt`、`~/.claude/skills/humanizer-zh` symlink 到 repo 內對應目錄。`Path(__file__).resolve()` 穿過 symlink 找回真實 repo 路徑，腳本據此定位 repo 根、讀 `.env`。

## 4. 元件設計

### 4.1 `ytkit/config.py`（設定載入器）

**職責：** 單一入口提供所有設定，取代散落的寫死路徑與外部 `.env` 讀取。

**行為：**
- 從 `Path(__file__).resolve()` 往上找 repo 根（遇到 `.git` 或 `.env` 為止）。
- 載入 repo 根 `.env`（若存在）到 `os.environ`（不覆蓋既有環境變數）。
- 對找不到的鍵，回退讀取 `~/.claude/.env`（讓 `HACKMD_API_TOKEN` 維持舊行為相容）。
- 提供取值函式 / 常數：
  - `minimax_api_key()` → `ANTHROPIC_API_KEY`
  - `minimax_base_url()` → `ANTHROPIC_BASE_URL`（預設 `https://api.minimax.io/anthropic`）
  - `minimax_model()` → `MINIMAX_MODEL`（預設 `MiniMax-M3`）
  - `output_dir()` → `YT_OUTPUT_DIR`，未設定則回退 `<repo>/output/`（並確保目錄存在）
  - `hackmd_token()` → `HACKMD_API_TOKEN`
  - `whisper_device()` → `WHISPER_DEVICE`（預設 `auto`）

**介面：** 其他腳本 `from ytkit import config`（透過 `sys.path` 注入 repo 根，或腳本開頭 `sys.path.insert`）。

### 4.2 `.env.example`

```
# MiniMax（Anthropic 相容端點）— 必填
ANTHROPIC_API_KEY=sk-cp-xxxx
ANTHROPIC_BASE_URL=https://api.minimax.io/anthropic
MINIMAX_MODEL=MiniMax-M3

# 文章落檔位置（每台機器不同，填你的 Obsidian 路徑；留空則落到 <repo>/output/）
YT_OUTPUT_DIR=

# HackMD（選填，要自動上傳才需要）
HACKMD_API_TOKEN=

# Whisper 後端：auto | cuda | mlx | cpu
WHISPER_DEVICE=auto
```

### 4.3 `yt_to_article.py` 改動

- 刪除讀 `taiwan_stock_dashboard\.env` 的程式區塊（第 57–68 行附近）。
- `MINIMAX_BASE_URL` / `MINIMAX_API_KEY` / `MINIMAX_MODEL` / `OUTPUT_DIR` 改為呼叫 `config`。
- 其餘邏輯（抓字幕、生成、簡轉繁後處理、存檔、存英文字幕）不變。
- 保留 `main(youtube_url)` CLI 介面。

### 4.4 `transcribe.py` 後端抽象（跨平台關鍵）

**職責：** 同一 CLI 介面（`transcribe.py <url|audio> [--lang] [--out] [--model]`），依設定自動選後端。

**後端選擇（`WHISPER_DEVICE`）：**
- `cuda`：faster-whisper `WhisperModel(device="cuda", compute_type="int8")` + 現有 Windows CUDA DLL 載入（`_enable_cuda_dlls` 只在 Windows 執行）。
- `mlx`：`mlx_whisper.transcribe(audio, path_or_hf_repo="mlx-community/whisper-large-v3-turbo")`（Apple Silicon 最佳化）。
- `cpu`：faster-whisper `device="cpu", compute_type="int8"`。
- `auto`：偵測到 CUDA 可用 → cuda；否則 Apple Silicon（`platform.machine()=="arm64"` 且 `mlx_whisper` 可 import）→ mlx；否則 cpu。

**輸出：** 三後端統一回傳 `(text, detected_lang)`，寫入 `--out`。下游 humanizer 負責簡轉繁。

### 4.5 `yt_channel_watcher.py`（手動輪巡）

- 維持以 `channels.json` 為輸入、`processed_videos.json` 為去重狀態。
- 移除任何 Windows 排程相依；改為可手動 `python yt_channel_watcher.py` 單次掃描，或加 `--loop [秒數]` 自行輪巡（不依賴 cron/launchd）。
- 路徑改用 `config`；`processed_videos.json` 與 `watcher.log` 視為執行期狀態，gitignore。

### 4.6 `humanizer-zh/SKILL.md` 與 `upload_hackmd.py`

- SKILL.md 內 `python "C:\Users\wukee\.claude\skills\humanizer-zh\scripts\upload_hackmd.py"` → 改為相對技能目錄（`<skill-dir>/scripts/upload_hackmd.py`，由 Claude 以 base directory 代入）。
- `upload_hackmd.py` 邏輯不變；token 讀取改為先 repo `.env` 後回退 `~/.claude/.env`（透過 config 或保留自身 loader 並加 repo `.env` 檢查）。

### 4.7 `install.sh` / `install.ps1`

流程：
1. 檢查 `python3`、`ffmpeg`、`yt-dlp`；缺則印出對應安裝指令（Mac：`brew install ffmpeg yt-dlp`）。
2. `pip install -r requirements.txt`；偵測到 arm Mac 額外 `pip install mlx-whisper`。
3. 建立 `~/.claude/skills`（若不存在）；symlink `skills/yt`、`skills/humanizer-zh` 進去（目標已存在則先備份成 `.bak`）。`--copy` 旗標改為複製。
4. 若 repo 根無 `.env`，從 `.env.example` 複製並提示填 `ANTHROPIC_API_KEY`、`YT_OUTPUT_DIR`。
5. 印出後續步驟（填 `.env`、在 Claude Code 用 `/yt`、`/humanizer-zh`）。

## 5. 既有 repo 清理（用 `git mv` 保留歷史）

- `.claude/skills/yt/` 內容 → `skills/yt/`。
- `~/.claude/skills/humanizer-zh/` → 複製進 repo `skills/humanizer-zh/`（首次納入版控）。
- 刪：重複的 `yt/`、`_whisper_*.txt`、`_tmp_yt_whisper.py`、`_m3_test/`、`watcher.log`、`sync_channels.ps1`。
- `processed_videos.json` → 移出版控、加 `.gitignore`。
- 更新 `.gitignore`：`.env`、`output/`、`*.log`、`__pycache__/`、`processed_videos.json`、`_whisper_*.txt`、`_m3_test/`。
- README 重寫（見 §6）。

## 6. README / knowhow 文件範圍

涵蓋：架構總覽；pipeline 五步（抓字幕 → Whisper 備援 → MiniMax 生成 → 簡轉繁後處理 → humanizer 編修 → HackMD 上傳）；安裝步驟；`.env` 設定說明；`/yt` 與 `/humanizer-zh` 用法；頻道手動輪巡用法；跨平台注意事項（Windows CUDA vs Mac MLX）。

## 7. 風險與待確認

- **線上排程**：使用者 Windows 上的即時排程跑的是另一份 `yt-insight-bot`（非本 repo），故重構本 repo 理論上不影響線上 bot；**實作前需使用者確認**此假設。
- **Windows symlink**：需開發者模式或管理員權限；`install.ps1` 提供 `--copy` 退路。Mac 不受影響（主要目標機）。
- **mlx-whisper 模型下載**：首次轉錄會自 HuggingFace 下載 `whisper-large-v3-turbo`，需網路與磁碟空間。

## 8. 成功標準

在一台乾淨的 Apple Silicon MacBook 上：
1. `git clone` → `./install.sh` → 填 `.env`（MiniMax key + Obsidian 路徑）。
2. Claude Code 內 `/yt <url>` 能對「有字幕」影片產出文章並落到指定 Obsidian 路徑。
3. 對「無字幕」影片，`transcribe.py` 走 MLX 後端在本地轉錄成功，再生成文章。
4. `/humanizer-zh <檔案>` 能編修並（有 token 時）上傳 HackMD。
5. 全程無任何寫死的 `C:\Users\...` 路徑被觸發。
