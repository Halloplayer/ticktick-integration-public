# skills/sync/scripts/install_task.ps1
# Registers the background job: every 5 minutes, no window.
#
# The task does not point at sync.py directly. It executes a stable Python
# launcher in the data directory (%LOCALAPPDATA%\ticktick-integration\launcher.pyw)
# that resolves the newest cached plugin version at RUN time. The cached
# plugin path is version-scoped and a plugin update replaces it wholesale --
# without this indirection the scheduled task would point into a folder the
# next update removes, and the mirror would go quietly stale while the list
# kept looking plausible.
#
# The SAME launcher is also what the ticktick-integration skill runs (see
# skills/sync/SKILL.md) -- that is the whole point of having it: a
# skill invocation resolves `${CLAUDE_PLUGIN_ROOT}` once, when the session
# LOADED the plugin, so a plugin update during a long session leaves it
# pointing at a stale version. The launcher has no such binding; it looks
# the cache up fresh on every call.
#
# Why pythonw.exe and not a PowerShell wrapper around it: powershell.exe
# allocates its console BEFORE -WindowStyle Hidden takes effect, so a black
# window flashed on screen every five minutes for hours before this fix --
# "must not slow down or interrupt normal work" is a fixed constraint of this
# project, and a window blinking twelve times an hour violated it more than
# anything else could. pythonw.exe never allocates a console at all, so
# there is nothing to flash regardless of any -WindowStyle-like setting --
# there is no window to hide in the first place. Do not "simplify" this back
# to a PowerShell wrapper; that is exactly the bug this file exists to avoid
# reintroducing. See README.md for the full story.
$ErrorActionPreference = "Stop"

$pythonw  = "C:\Program Files\Python311\pythonw.exe"
$name     = "TickTickIntegration"
$dataDir  = "$env:LOCALAPPDATA\ticktick-integration"
# scripts/ sits three levels under the plugin root: skills/sync/scripts.
$repoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))

if (-not (Test-Path $pythonw)) { throw "pythonw.exe not found: $pythonw" }

New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

# The numeric-vs-lexical version comparison (0.10.0 must beat 0.9.0 -- a
# lexical sort gets that backwards) lives in lib/launcher_support.py, tested
# like everything else. Stage a copy in the data directory -- not
# version-scoped, so it survives a plugin update exactly like launcher.pyw
# itself -- and the launcher imports it from there instead of reimplementing
# it.
Copy-Item -Path (Join-Path $repoRoot "lib\launcher_support.py") `
    -Destination "$dataDir\launcher_support.py" -Force

# A stable launcher in the data directory that finds the newest cached version
# on EVERY run. Without this indirection the scheduled task points at a version
# folder that the next plugin update removes, and the mirror goes quietly stale.
# It forwards its own arguments through to sync.py rather than hardcoding
# --quiet, so the same launcher serves both the silent scheduled task and a
# human running the skill, who needs to see the output. Being run directly by
# pythonw.exe / python.exe (never through powershell.exe), it never allocates
# a console of its own -- there is nothing for -WindowStyle to hide.
$launcher = @'
import os
import pathlib
import runpy
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from launcher_support import newest_version_dir

CACHE = pathlib.Path(os.environ["USERPROFILE"]) / ".claude" / "plugins" / "cache" / "ticktick-integration" / "ticktick-integration"
target = newest_version_dir(CACHE)

# Where sync.py sits inside the plugin (moved here from the plugin root when
# the repo adopted the skill layout). This launcher lives in the data
# directory and deliberately OUTLIVES plugin updates and runs under
# pythonw.exe -- no console, and BEFORE sync.py has set up its own logging --
# so a silent runpy.run_path() failure on a path that moved again would kill
# the five-minute job with nothing anywhere, not even sync.log, to say why.
# Fail loudly instead: name the exact path this looked for.
entry = target / "skills/sync/scripts/sync.py"
if not entry.is_file():
    raise SystemExit("sync.py not found at %s -- the plugin layout moved and "
                      "this launcher was not updated to match" % entry)

sys.path.insert(0, str(target))
sys.argv = [str(entry)] + sys.argv[1:]
runpy.run_path(str(entry), run_name="__main__")
'@
Set-Content -Path "$dataDir\launcher.pyw" -Value $launcher -Encoding utf8

$action = New-ScheduledTaskAction -Execute $pythonw `
    -Argument "`"$dataDir\launcher.pyw`" --quiet"

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 4)

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
    -Settings $settings -Description "Mirrors open work into TickTick." -Force

Write-Output "Registered: $name (every 5 minutes, no window, launcher: $dataDir\launcher.pyw)"
