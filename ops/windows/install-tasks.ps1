# Registers Harbinger's scheduled tasks. All run through hidden_run.vbs (no console flash).
#   "Harbinger Watchdog"  every 5 min: restart the server / tunnel if down
#   "Harbinger Ingest"    06:30, 09:30, 12:30, 15:30, 18:30 with --if-due: the first tick each day
#                         always runs; later ticks run only while a leaving list is expected
#                         ([waves] notice_window). Pushes only newly confirmed leavers.
#                         Lists have landed 05:15-17:00 Eastern (.claude/docs/ops.md).
# It also removes the old "Harbinger Steam" task: the daily ingest syncs Steam itself.
#
# This machine:  .\install-tasks.ps1 -Controller C:\Development\server.ps1
# Times are the machine's local time (Eastern here, so America/Toronto).
# Register-ScheduledTask can need elevation; the watchdog falls back to schtasks unelevated.
param(
    [int]$Port = 5006,
    [string]$Tunnel = 'harbinger',
    [string]$Controller = '',
    [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'

$watchdog = Join-Path $PSScriptRoot 'watchdog.ps1'
$runJob = Join-Path $PSScriptRoot 'run-job.ps1'
$vbs = Join-Path $PSScriptRoot 'hidden_run.vbs'
if ($Controller -and -not (Test-Path $Controller)) { throw "controller not found at $Controller" }

function Quote([string[]]$parts) { ($parts | ForEach-Object { "`"$_`"" }) -join ' ' }

# Only non-default args, so the command stays under schtasks' 261-char /tr limit.
$wdArgs = @()
if ($Port -ne 5006) { $wdArgs += @('-Port', $Port) }
if ($Tunnel -ne 'harbinger') { $wdArgs += @('-Tunnel', $Tunnel) }
if ($Python -ne 'python') { $wdArgs += @('-Python', $Python) }
if ($Controller) { $wdArgs += @('-Controller', (Resolve-Path $Controller).Path) }
$wdLine = "//B //Nologo `"$vbs`" " + (Quote (@('powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $watchdog) + $wdArgs))

try {
    $action = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument $wdLine
    $triggers = @(
        (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
            -RepetitionInterval (New-TimeSpan -Minutes 5) `
            -RepetitionDuration (New-TimeSpan -Days 3650)),
        (New-ScheduledTaskTrigger -AtLogOn)
    )
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
    Register-ScheduledTask -TaskName 'Harbinger Watchdog' -Action $action `
        -Trigger $triggers -Settings $settings -Force -ErrorAction Stop | Out-Null
    Write-Host 'Registered task: Harbinger Watchdog (every 5 min + at logon)'
} catch {
    Write-Host "Register-ScheduledTask failed ($($_.Exception.Message.Trim())) - falling back to schtasks"
    schtasks /create /tn "Harbinger Watchdog" /sc minute /mo 5 /tr "wscript.exe $wdLine" /f
    if ($LASTEXITCODE -ne 0) { throw "schtasks fallback failed with exit code $LASTEXITCODE" }
    Write-Host 'Registered task: Harbinger Watchdog (every 5 min, current user)'
}

# XML rather than schtasks /sc daily for StartWhenAvailable (a missed tick runs once the
# machine is back) and the 1 h time limit.
$ingestArgs = "//B //Nologo `"$vbs`" " + (Quote @('powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $runJob, '-Job', 'ingest'))
$day = Get-Date -Format 'yyyy-MM-dd'
$triggers = ('06:30', '09:30', '12:30', '15:30', '18:30' | ForEach-Object {
    "<CalendarTrigger><StartBoundary>${day}T${_}:00</StartBoundary><Enabled>true</Enabled>" +
    "<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger>"
}) -join "`n    "
$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Harbinger: sheet, forecast and Steam refresh, push on newly confirmed leavers</Description></RegistrationInfo>
  <Triggers>
    $triggers
  </Triggers>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec><Command>wscript.exe</Command><Arguments>$([System.Security.SecurityElement]::Escape($ingestArgs))</Arguments></Exec>
  </Actions>
</Task>
"@
$xmlPath = Join-Path $env:TEMP 'harbinger-ingest-task.xml'
[System.IO.File]::WriteAllText($xmlPath, $xml, [System.Text.Encoding]::Unicode)
schtasks /create /tn "Harbinger Ingest" /xml $xmlPath /f
if ($LASTEXITCODE -ne 0) { throw "Harbinger Ingest: schtasks exit $LASTEXITCODE" }
Remove-Item $xmlPath -ErrorAction SilentlyContinue
Write-Host 'Registered task: Harbinger Ingest (5 ticks a day, --if-due)'

schtasks /query /tn "Harbinger Steam" 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    schtasks /delete /tn "Harbinger Steam" /f | Out-Null
    Write-Host 'Removed old task: Harbinger Steam (the daily ingest covers it)'
}
