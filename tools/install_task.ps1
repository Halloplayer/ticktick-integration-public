# tools/install_task.ps1
# Registers the background job: every 5 minutes, no window.
# pythonw.exe rather than python.exe -- otherwise a console flashes up every
# 5 minutes, which is exactly the disruption this project must avoid.
$ErrorActionPreference = "Stop"

$repo    = "C:\Users\you\workspace\ticktick-sync"
$pythonw = "C:\Program Files\Python311\pythonw.exe"
$name    = "TickTickSync"

if (-not (Test-Path $pythonw)) { throw "pythonw.exe not found: $pythonw" }
if (-not (Test-Path "$repo\sync.py")) { throw "sync.py not found in $repo" }

$action = New-ScheduledTaskAction -Execute $pythonw `
    -Argument "`"$repo\sync.py`" --quiet" -WorkingDirectory $repo

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 4)

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
    -Settings $settings -Description "Mirrors open work into TickTick." -Force

Write-Output "Registered: $name (every 5 minutes, no window)"
