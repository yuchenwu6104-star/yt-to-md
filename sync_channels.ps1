# sync_channels.ps1
# 把「主檔」channels.json 同步到所有其他副本(skill 用的 .claude/.agents、排程用的 yt-insight-bot)。
# 用法:改完主檔後,在本資料夾執行  .\sync_channels.ps1
# 唯一真實來源 = 工作目錄的 .claude 那份。

$ErrorActionPreference = "Stop"

# === 唯一主檔(single source of truth) ===
$Master = "C:\Users\wukee\OneDrive\文件\clon資料\訪談摘要\.claude\skills\yt\scripts\channels.json"

if (-not (Test-Path $Master)) {
    Write-Error "找不到主檔: $Master"
    exit 1
}

# 驗證主檔是合法 JSON,壞掉就不要污染其他副本
try {
    $null = Get-Content $Master -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
    Write-Error "主檔不是合法 JSON,已中止同步: $Master`n$($_.Exception.Message)"
    exit 1
}

# === 搜尋所有副本的根目錄 ===
# 注意:不含 Downloads\訪談摘要(那是另一邊的獨立 clone,不歸這裡管)
$Roots = @(
    "C:\Users\wukee\OneDrive\文件\clon資料\訪談摘要",
    "C:\Users\wukee\yt-insight-bot"
)

$MasterFull = (Resolve-Path $Master).Path
$count = 0

foreach ($root in $Roots) {
    if (-not (Test-Path $root)) { continue }
    Get-ChildItem -Path $root -Recurse -Filter channels.json -File -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.FullName -eq $MasterFull) { return }              # 跳過主檔自己
        Copy-Item -Path $Master -Destination $_.FullName -Force
        Write-Host "  synced -> $($_.FullName)"
        $script:count++
    }
}

Write-Host ""
Write-Host "完成:主檔已同步到 $count 份副本。" -ForegroundColor Green
