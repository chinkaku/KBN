# 组合麻将 — 本地打包脚本（用于 scp 到服务器 / , 需 PowerShell 5+ / Windows 自带 tar）
# 用法: pwsh -File deploy/package.ps1
$ErrorActionPreference = "Stop"
$src = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent   # Q:\openai
$stage = Join-Path $env:TEMP "comb_deploy"
$out = Join-Path $PSScriptRoot "comb_deploy.tar.gz"

if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage | Out-Null

foreach ($item in @("game_engine.py", "branches", "static", "story", "deploy", "RULES_GAP.md", "dev_notes.md")) {
    Copy-Item (Join-Path $src $item) (Join-Path $stage $item) -Recurse
}

# 运行时数据/缓存不进包
@("users.json", "player_seq.txt", "forum.db", "replays.db", "comb_deploy.tar.gz") | ForEach-Object {
    $p = Join-Path $stage (Join-Path "branches\networking" $_)
    if (Test-Path $p) { Remove-Item $p -Force }
}
Get-ChildItem $stage -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force

if (Test-Path $out) { Remove-Item $out -Force }
tar -czf $out -C $stage .
$kb = [math]::Round((Get-Item $out).Length / 1KB)
Write-Output "打包完成: $out (${kb} KB)"
