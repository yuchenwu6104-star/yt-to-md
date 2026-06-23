#!/usr/bin/env bash
# yt-to-md 安裝器（Mac / Linux）。
# 檢查依賴 → pip install → symlink 技能進 ~/.claude/skills → 備好 .env。
# 用法：./install.sh            （symlink 技能，推薦）
#       ./install.sh --copy     （複製技能而非 symlink；Claude Code 更新後不會自動同步）
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COPY_MODE=0
[ "${1:-}" = "--copy" ] && COPY_MODE=1

echo "==> yt-to-md installer（repo: $REPO_ROOT）"

# 1. 系統依賴
missing=0
for cmd in python3 ffmpeg yt-dlp; do
  if command -v "$cmd" >/dev/null 2>&1; then
    echo "  ✓ $cmd"
  else
    echo "  ✗ 缺少 $cmd"
    missing=1
  fi
done
if [ "$missing" = 1 ]; then
  echo
  echo "請先安裝缺少的工具再重跑："
  echo "  Mac:   brew install python ffmpeg yt-dlp"
  echo "  Linux: 用你的套件管理員安裝 python3 / ffmpeg / yt-dlp"
  exit 1
fi

# 2. Python 依賴
echo "==> pip install 核心依賴"
python3 -m pip install -r "$REPO_ROOT/requirements.txt"

if [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ]; then
  echo "==> 偵測到 Apple Silicon，安裝 mlx-whisper（無字幕影片本地轉錄，跑 Mac 晶片）"
  python3 -m pip install mlx-whisper \
    || echo "  ! mlx-whisper 安裝失敗，之後可手動 'pip install mlx-whisper'（不影響有字幕影片）"
fi

# 3. symlink 技能進 ~/.claude/skills
SKILLS_DST="$HOME/.claude/skills"
mkdir -p "$SKILLS_DST"
shopt -s nullglob
for src in "$REPO_ROOT"/.claude/skills/*/; do
  [ -f "${src}SKILL.md" ] || continue
  name="$(basename "$src")"
  dst="$SKILLS_DST/$name"
  if [ -e "$dst" ] || [ -L "$dst" ]; then
    echo "  既有 $name → 備份成 $name.bak"
    rm -rf "$dst.bak"
    mv "$dst" "$dst.bak"
  fi
  if [ "$COPY_MODE" = 1 ]; then
    cp -R "${src%/}" "$dst"
    echo "  複製 $name"
  else
    ln -s "${src%/}" "$dst"
    echo "  symlink $name"
  fi
done
shopt -u nullglob

# 4. .env
if [ ! -f "$REPO_ROOT/.env" ]; then
  cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"
  echo "==> 已從 .env.example 建立 .env"
else
  echo "==> .env 已存在，保留不動"
fi

cat <<EOF

完成。後續步驟：
  1. 編輯 $REPO_ROOT/.env：
       ANTHROPIC_API_KEY = MiniMax key（sk-cp-...）
       YT_OUTPUT_DIR     = 你 Mac 上的 Obsidian 落檔路徑（留空則落到 <repo>/output/）
       HACKMD_API_TOKEN  = 選填，要自動上傳 HackMD 才需要
  2. 在 Claude Code 內用 /yt <YouTube URL>、/humanizer-zh <檔案>
  3. 無字幕影片會自動走 MLX 在本地轉錄（首次會下載 Whisper 模型）
EOF
