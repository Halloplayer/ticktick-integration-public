# tools/install_task.ps1
# Registers the background job: every 5 minutes, no window.
#
# The task does not point at sync.py directly. It executes a stable launcher
# in the data directory (%LOCALAPPDATA%\ticktick-sync\run.ps1) that resolves
# the newest cached plugin version at RUN time. The cached plugin path is
# version-scoped and a plugin update replaces it wholesale -- without this
# indirection the scheduled task would point into a folder the next update
# removes, and the mirror would go quietly stale while the list kept looking
# plausible. pythonw.exe rather than python.exe -- otherwise a console
# flashes up every 5 minutes, which is exactly the disruption this project
# must avoid.
$ErrorActionPreference = "Stop"

$pythonw = "C:\Program Files\Python311\pythonw.exe"
$name    = "TickTickSync"
$dataDir = "$env:LOCALAPPDATA\ticktick-sync"

if (-not (Test-Path $pythonw)) { throw "pythonw.exe not found: $pythonw" }

New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

# A stable launcher in the data directory that finds the newest cached version
# on EVERY run. Without this indirection the scheduled task points at a version
# folder that the next plugin update removes, and the mirror goes quietly stale.
$launcher = @'
$cache = "$env:USERPROFILE\.claude\plugins\cache\ticktick-sync\ticktick-sync"
$newest = Get-ChildItem $cache -Directory | Sort-Object Name -Descending | Select-Object -First 1
& "C:\Program Files\Python311\pythonw.exe" "$($newest.FullName)\sync.py" --quiet
'@
Set-Content -Path "$dataDir\run.ps1" -Value $launcher -Encoding utf8

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$dataDir\run.ps1`""

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 4)

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
    -Settings $settings -Description "Mirrors open work into TickTick." -Force

Write-Output "Registered: $name (every 5 minutes, no window, launcher: $dataDir\run.ps1)"
