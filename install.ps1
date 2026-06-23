<#
  yt-to-md 安裝器（Windows）。
  檢查依賴 → pip install → 連結技能進 ~/.claude/skills → 備好 .env。

  用法：
    powershell -ExecutionPolicy Bypass -File .\install.ps1          # symlink（需開發者模式或系統管理員）
    powershell -ExecutionPolicy Bypass -File .\install.ps1 -Copy    # 改用複製（無權限時的退路）

  註：這個腳本是手動安裝用，不會在平常使用時自動執行。既有的同名技能會先備份成 .bak。
#>
param([switch]$Copy)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "==> yt-to-md installer (repo: $RepoRoot)"

# 1. 系統依賴
$missing = $false
foreach ($cmd in @("python", "ffmpeg", "yt-dlp")) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        Write-Host "  OK  $cmd"
    } else {
        Write-Host "  X   缺少 $cmd"
        $missing = $true
    }
}
if ($missing) {
    Write-Host ""
    Write-Host "請先安裝缺少的工具再重跑（例：winget install Gyan.FFmpeg yt-dlp.yt-dlp、python.org 裝 Python）。"
    exit 1
}

# 2. Python 依賴
Write-Host "==> pip install 核心依賴"
python -m pip install -r (Join-Path $RepoRoot "requirements.txt")
Write-Host "==> Windows + NVIDIA 若要無字幕轉錄，另執行："
Write-Host "      pip install faster-whisper nvidia-cublas-cu12 nvidia-cudnn-cu12 nvidia-cuda-runtime-cu12"

# 3. 連結技能進 ~/.claude/skills
$SkillsDst = Join-Path $HOME ".claude\skills"
New-Item -ItemType Directory -Force -Path $SkillsDst | Out-Null
Get-ChildItem -Directory (Join-Path $RepoRoot ".claude\skills") | ForEach-Object {
    $src = $_.FullName
    if (-not (Test-Path (Join-Path $src "SKILL.md"))) { return }
    $name = $_.Name
    $dst = Join-Path $SkillsDst $name
    if (Test-Path $dst) {
        Write-Host "  既有 $name -> 備份成 $name.bak"
        if (Test-Path "$dst.bak") { Remove-Item "$dst.bak" -Recurse -Force }
        Move-Item $dst "$dst.bak"
    }
    if ($Copy) {
        Copy-Item $src $dst -Recurse
        Write-Host "  複製 $name"
    } else {
        try {
            New-Item -ItemType SymbolicLink -Path $dst -Target $src | Out-Null
            Write-Host "  symlink $name"
        } catch {
            Copy-Item $src $dst -Recurse
            Write-Host "  symlink 失敗（缺權限），改用複製 $name"
        }
    }
}

# 4. .env
$envFile = Join-Path $RepoRoot ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $RepoRoot ".env.example") $envFile
    Write-Host "==> 已從 .env.example 建立 .env"
} else {
    Write-Host "==> .env 已存在，保留不動"
}

Write-Host ""
Write-Host "完成。後續：編輯 $envFile 填 ANTHROPIC_API_KEY / YT_OUTPUT_DIR / HACKMD_API_TOKEN，"
Write-Host "再到 Claude Code 用 /yt、/humanizer-zh。"
