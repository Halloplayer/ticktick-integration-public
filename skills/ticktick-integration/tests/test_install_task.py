"""Tests for the scheduled-task installer.

The task used to run through powershell.exe: `-WindowStyle Hidden -File
run.ps1`. powershell.exe allocates its console BEFORE -WindowStyle Hidden
takes effect, so a black window flashed on the owner's screen every five
minutes for hours -- "must not slow down or interrupt my normal work" is one
of this project's fixed constraints, and a window blinking twelve times an
hour violates it more than anything else could.

The fix replaces the PowerShell wrapper with pythonw.exe running a small
Python launcher (launcher.pyw) directly. pythonw.exe never allocates a
console at all, so there is nothing to flash regardless of any
-WindowStyle-like setting -- there is no window to hide in the first place.
"""
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "lib"))

from launcher_support import newest_version_dir  # noqa: E402

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "install_task.ps1")


class InstallTaskScriptTest(unittest.TestCase):
    def setUp(self):
        with open(SCRIPT, encoding="utf-8") as handle:
            self.text = handle.read()


class WritesLauncherNotRunPsTest(InstallTaskScriptTest):
    def test_the_installer_writes_launcher_pyw(self):
        self.assertRegex(self.text, r'Set-Content\s+-Path\s+"\$dataDir\\launcher\.pyw"',
                          "the installer must write launcher.pyw into the data directory")

    def test_the_installer_no_longer_writes_run_ps1(self):
        self.assertNotIn("run.ps1", self.text,
                          "run.ps1 generation is dead -- the launcher replaced it entirely, "
                          "and no reference to it should remain in the installer")


class RegisteredActionTest(InstallTaskScriptTest):
    def test_the_execute_variable_points_at_pythonw(self):
        match = re.search(r'\$pythonw\s*=\s*"([^"]+)"', self.text)
        self.assertIsNotNone(match, "install_task.ps1 must define a $pythonw variable")
        self.assertTrue(match.group(1).lower().endswith("pythonw.exe"))

    def test_the_scheduled_task_action_executes_pythonw(self):
        match = re.search(r"New-ScheduledTaskAction\s+-Execute\s+(\S+)", self.text)
        self.assertIsNotNone(match, "install_task.ps1 must define the scheduled task action's -Execute")
        self.assertEqual("$pythonw", match.group(1),
                          "the registered Execute must be the pythonw.exe path, not powershell.exe")

    def test_the_arguments_name_launcher_pyw_and_pass_quiet(self):
        match = re.search(r'-Argument\s+"(.*)"\s*$', self.text, re.MULTILINE)
        self.assertIsNotNone(match, "install_task.ps1 must define the scheduled task action's -Argument")
        self.assertIn("launcher.pyw", match.group(1))
        self.assertIn("--quiet", match.group(1))


class NoPowershellExecutableTest(InstallTaskScriptTest):
    def test_no_line_registers_powershell_exe_as_the_task_executable(self):
        """The regression guard: this is the one that matters."""
        for line in self.text.splitlines():
            if "-Execute" in line:
                self.assertNotRegex(
                    line, r"powershell\.exe",
                    "the scheduled task's executable must never be powershell.exe again -- "
                    "that is exactly the console-before-hidden bug this fix exists to prevent")


class VersionResolutionIsNumericTest(unittest.TestCase):
    """The launcher's own resolution function, tested directly by import --
    not by shelling out to pythonw.exe."""

    def test_a_double_digit_minor_beats_a_single_digit_one_numerically(self):
        with tempfile.TemporaryDirectory() as root:
            for name in ("0.9.0", "0.10.0"):
                os.mkdir(os.path.join(root, name))
            newest = newest_version_dir(root)
            self.assertEqual("0.10.0", os.path.basename(str(newest)),
                              "0.10.0 must be selected over 0.9.0 -- numeric, not lexical, comparison")

    def test_a_lexical_sort_would_have_picked_the_wrong_one(self):
        # Sanity check on the fixture itself, proving the test is meaningful:
        # a plain string sort puts "0.9.0" after "0.10.0".
        self.assertEqual(sorted(["0.9.0", "0.10.0"])[-1], "0.9.0")

    def test_an_empty_directory_raises_rather_than_silently_doing_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(SystemExit):
                newest_version_dir(root)


class LauncherPywCallsTheSharedResolutionFunctionTest(InstallTaskScriptTest):
    def _launcher_body(self):
        match = re.search(r"\$launcher = @'\r?\n(.*?)\r?\n'@", self.text, re.DOTALL)
        self.assertIsNotNone(match, "install_task.ps1 must define $launcher as a here-string")
        return match.group(1)

    def test_the_generated_launcher_imports_the_shared_resolution_function(self):
        body = self._launcher_body()
        self.assertIn("newest_version_dir", body,
                       "the generated launcher must call the same resolution function that is "
                       "unit-tested in lib/launcher_support.py, not reimplement it")

    def test_the_generated_launcher_does_not_reimplement_the_numeric_parsing(self):
        body = self._launcher_body()
        self.assertNotIn("tuple(int(n) for n in", body,
                          "the numeric-parsing logic must live in launcher_support.py only -- a "
                          "second copy inside the generated file is exactly the kind of drift the "
                          "extraction exists to prevent")

    def test_the_installer_stages_launcher_support_alongside_the_launcher(self):
        self.assertIn("launcher_support.py", self.text,
                       "the installer must place launcher_support.py in the data directory so the "
                       "generated launcher.pyw can import it at run time")


class LauncherTargetsTheNewEntryPointTest(InstallTaskScriptTest):
    """sync.py moved from the plugin root to skills/ticktick-integration/scripts/ when
    the repo adopted the skill layout. The generated launcher must
    follow it there -- and must not silently fall back to the old root path,
    which is exactly the kind of drift that would leave the 5-minute job
    dying quietly on a path that no longer exists."""

    def _launcher_body(self):
        match = re.search(r"\$launcher = @'\r?\n(.*?)\r?\n'@", self.text, re.DOTALL)
        self.assertIsNotNone(match, "install_task.ps1 must define $launcher as a here-string")
        return match.group(1)

    def test_the_generated_launcher_targets_the_new_entry_point_path(self):
        body = self._launcher_body()
        self.assertIn("skills/ticktick-integration/scripts/sync.py", body,
                       "the generated launcher must resolve sync.py under the new "
                       "skills/ticktick-integration/scripts/ location")

    def test_the_generated_launcher_does_not_reference_a_bare_root_sync_py(self):
        """The regression guard: no fallback to the pre-restructure path. A quoted
        bare 'sync.py' (not prefixed by its scripts/ directory) is exactly what a
        reintroduced old-layout fallback would look like."""
        body = self._launcher_body()
        self.assertNotRegex(body, r'["\']sync\.py["\']',
                             "the launcher must not reference a bare <root>/sync.py -- "
                             "that path no longer exists after the restructure")

    def test_the_generated_launcher_raises_loudly_when_sync_py_is_absent(self):
        body = self._launcher_body()
        self.assertIn("raise SystemExit", body,
                       "a missing sync.py must fail loudly, not disappear silently under "
                       "pythonw.exe where there is no console and logging is not set up yet")
        self.assertIn("entry", body)


if __name__ == "__main__":
    unittest.main()
