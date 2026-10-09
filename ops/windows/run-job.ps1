# Runs one Harbinger job from Task Scheduler and logs it.
#   -Job ingest  sheet + forecast subagent + Steam + rebuild; pushes newly confirmed leavers (daily)
#   -Job steam   Steam progress + rebuild from cached inputs (manual)
# A failed run pages through Pharos (if it sits next to this repo, or -PharosModule points at it)
# so a dead schedule doesn't go unnoticed.
param(
    [ValidateSet('ingest', 'steam')][string]$Job = 'ingest',
    [string]$PharosModule = ''
)

$ErrorActionPreference = 'Continue'
$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$LogDir = Join-Path $PSScriptRoot 'logs'
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
$Log = Join-Path $LogDir "$Job.log"

if ((Test-Path $Log) -and ((Get-Item $Log).Length -gt 512KB)) {
    Set-Content -Path $Log -Value (Get-Content $Log -Tail 1500)
}

$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $Root
$jobArgs = @('-3.11', '-m', 'harbinger', $Job)
if ($Job -eq 'ingest') { $jobArgs += '--push' }

Add-Content -Path $Log -Encoding UTF8 -Value ("==== {0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Job)
$out = & py @jobArgs 2>&1
$code = $LASTEXITCODE
$out | ForEach-Object { Add-Content -Path $Log -Encoding UTF8 -Value "$_" }
Add-Content -Path $Log -Value "exit $code"

if ($code -ne 0) {
    if (-not $PharosModule) { $PharosModule = Join-Path (Split-Path $Root -Parent) 'Pharos\Pharos.psm1' }
    if (-not (Test-Path $PharosModule)) { exit $code }
    try {
        Import-Module $PharosModule -ErrorAction Stop
        $what = if ($Job -eq 'ingest') { 'Game Pass radar refresh failed' } else { 'Game Pass radar Steam sync failed' }
        Send-Pharos -Title $what -Message "exit $code" -Source 'harbinger' | Out-Null
    } catch { Add-Content -Path $Log -Value "pharos unavailable: $($_.Exception.Message)" }
}
exit $code
