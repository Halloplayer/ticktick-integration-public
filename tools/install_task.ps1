# tools/install_task.ps1
# Registers the background job: every 5 minutes, no window.
#
# The task does not point at sync.py directly. It executes a stable launcher
# in the data directory (%LOCALAPPDATA%\ticktick-sync\run.ps1) that resolves
# the newest cached plugin version at RUN time. The cached plugin path is
# version-scoped and a plugin update replaces it wholesale -- without this
# indirection the scheduled task would point into a folder the next update
# removes, and the mirror would go quietly stale while the list kept looking
# plausible.
#
# The SAME launcher is also what the ticktick-sync skill runs (see
# skills/ticktick-sync/SKILL.md) -- that is the whole point of having it: a
# skill invocation resolves `${CLAUDE_PLUGIN_ROOT}` once, when the session
# LOADED the plugin, so a plugin update during a long session leaves it
# pointing at a stale version. The launcher has no such binding; it looks
# the cache up fresh on every call.
#
# Because both triggers now share one launcher, the launcher must not decide
# --quiet on their behalf -- it forwards whatever arguments it is called
# with. The scheduled task below passes --quiet explicitly; a human running
# the skill passes none and gets output. The choice of pythonw.exe (no
# console at all, so nothing flashes up every 5 minutes) vs. python.exe
# (has a console, so the skill's output is actually visible) follows from
# that same flag, inside the launcher.
$ErrorActionPreference = "Stop"

$pythonw = "C:\Program Files\Python311\pythonw.exe"
$name    = "TickTickSync"
$dataDir = "$env:LOCALAPPDATA\ticktick-sync"

if (-not (Test-Path $pythonw)) { throw "pythonw.exe not found: $pythonw" }

New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

# A stable launcher in the data directory that finds the newest cached version
# on EVERY run. Without this indirection the scheduled task points at a version
# folder that the next plugin update removes, and the mirror goes quietly stale.
# It forwards its own arguments through to sync.py rather than hardcoding
# --quiet, so the same launcher serves both the silent scheduled task and a
# human running the skill, who needs to see the output.
$launcher = @'
$cache = "$env:USERPROFILE\.claude\plugins\cache\ticktick-sync\ticktick-sync"
$newest = Get-ChildItem $cache -Directory | Sort-Object Name -Descending | Select-Object -First 1
if ($args -contains "--quiet") {
    $python = "C:\Program Files\Python311\pythonw.exe"
} else {
    $python = "C:\Program Files\Python311\python.exe"
}
& $python "$($newest.FullName)\sync.py" @args
'@
Set-Content -Path "$dataDir\run.ps1" -Value $launcher -Encoding utf8

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$dataDir\run.ps1`" --quiet"

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 4)

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
    -Settings $settings -Description "Mirrors open work into TickTick." -Force

Write-Output "Registered: $name (every 5 minutes, no window, launcher: $dataDir\run.ps1)"
