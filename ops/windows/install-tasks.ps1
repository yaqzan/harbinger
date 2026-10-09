# Registers Harbinger's three scheduled tasks. All run through hidden_run.vbs (no console flash).
#   "Harbinger Watchdog"  every 5 min: restart the server / tunnel if down
#   "Harbinger Ingest"    3rd and 18th at 08:46: sheet + forecast + Steam, then the summary push
#                         (the 3rd and 18th dodge weekend postings on the 1st and 15th)
#   "Harbinger Steam"     daily at 06:30: Steam progress, rebuild from cached inputs
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

# schtasks /sc monthly takes one day only, so the ingest task comes from XML (two days,
# every month). StartWhenAvailable runs a missed tick once the machine is back.
$ingestArgs = "//B //Nologo `"$vbs`" " + (Quote @('powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $runJob, '-Job', 'ingest'))
$months = (('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September',
    'October', 'November', 'December') | ForEach-Object { "<$_ />" }) -join ''
$start = (Get-Date -Format 'yyyy-MM-dd') + 'T08:46:00'
$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Harbinger: sheet, forecast and Steam refresh, then the summary push</Description></RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>$start</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByMonth><DaysOfMonth><Day>3</Day><Day>18</Day></DaysOfMonth><Months>$months</Months></ScheduleByMonth>
    </CalendarTrigger>
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
Write-Host 'Registered task: Harbinger Ingest (3rd and 18th, 08:46)'

$steamLine = "//B //Nologo `"$vbs`" " + (Quote @('powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $runJob, '-Job', 'steam'))
schtasks /create /tn "Harbinger Steam" /sc daily /st 06:30 /tr "wscript.exe $steamLine" /f
if ($LASTEXITCODE -ne 0) { throw "Harbinger Steam: schtasks exit $LASTEXITCODE" }
Write-Host 'Registered task: Harbinger Steam (daily, 06:30)'
