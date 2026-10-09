# Harbinger watchdog - keeps the server (and its tunnel, if you run one) alive on Windows.
# Registered by install-tasks.ps1 as "Harbinger Watchdog" (every 5 min + at logon).
#
# Probe cheaply FIRST, act only on pieces that are actually down. Two modes:
#   -Controller <script>  hand restarts to your own service controller, called as
#                         `<script> start -Service harbinger-api|harbinger-tunnel`
#   (no controller)       start `python -m harbinger serve` and, when
#                         ops\cloudflared-config.yml exists, `cloudflared tunnel run`
# Never capture controller output: its Start-Process children hold inherited
# pipes open (the '| Out-Null' form once wedged a watchdog task for 8+ hours).
#
# Safe to run by hand:  powershell -ExecutionPolicy Bypass -File watchdog.ps1

param(
    [int]$Port = 5006,
    [string]$Tunnel = 'harbinger',
    [string]$Controller = '',
    [string]$Python = 'python'
)

$ErrorActionPreference = 'Continue'

$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$TunnelConfig = Join-Path $Root 'ops\cloudflared-config.yml'
$LogDir = Join-Path $PSScriptRoot 'logs'
$LogFile = Join-Path $LogDir 'watchdog.log'

function Write-Log {
    param([string]$Message)
    if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
    Add-Content -Path $LogFile -Value ("{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message)
}

function Rotate-Log {
    if ((Test-Path $LogFile) -and ((Get-Item $LogFile).Length -gt 512KB)) {
        $tail = Get-Content $LogFile -Tail 1500
        Set-Content -Path $LogFile -Value $tail
    }
}

function Test-App {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 8
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

function Test-Tunnel {
    return [bool](Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "run\s+$([regex]::Escape($Tunnel))(\s|$)" })
}

function Start-Piece {
    param([string]$Svc)
    if ($Controller) {
        Start-Process powershell.exe -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', $Controller, 'start', '-Service', $Svc -WindowStyle Hidden -Wait
    } elseif ($Svc -eq 'harbinger-api') {
        Start-Process $Python -ArgumentList '-u', '-m', 'harbinger', 'serve' `
            -WorkingDirectory $Root -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $LogDir 'app.log') -RedirectStandardError (Join-Path $LogDir 'app.err.log')
    } else {
        Start-Process cloudflared -ArgumentList 'tunnel', '--config', $TunnelConfig, 'run', $Tunnel `
            -WorkingDirectory $Root -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $LogDir 'tunnel.log') -RedirectStandardError (Join-Path $LogDir 'tunnel.err.log')
    }
}

Rotate-Log

# The tunnel is optional: without a config (and no controller owning it) it isn't watched.
$watchTunnel = [bool]$Controller -or (Test-Path $TunnelConfig)

$down = @()
if (-not (Test-App)) { $down += 'harbinger-api' }
if ($watchTunnel -and -not (Test-Tunnel)) { $down += 'harbinger-tunnel' }

if (-not $down) {
    Write-Log 'all up'
} else {
    foreach ($svc in $down) {
        Write-Log "$svc DOWN -> start"
        Start-Piece $svc
    }
    Start-Sleep -Seconds 20
    Write-Log ("post-start: app={0} tunnel={1}" -f (Test-App), $(if ($watchTunnel) { Test-Tunnel } else { 'n/a' }))
}
