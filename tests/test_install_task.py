"""Both triggers must resolve the plugin version through the SAME launcher.

Before this fix the launcher hardcoded `--quiet`, which the scheduled task
needs but a human running the skill by hand does not -- the skill wants to
SEE the output. Hardcoding one flag for both triggers is exactly the kind of
drift the launcher indirection exists to prevent (see the file's own header
comment), so the launcher must forward whatever arguments it is given
instead of deciding for its caller.
"""
import os
import re
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "install_task.ps1")


class InstallTaskScriptTest(unittest.TestCase):
    def setUp(self):
        with open(SCRIPT, encoding="utf-8") as handle:
            self.text = handle.read()
        match = re.search(r"\$launcher = @'\r?\n(.*?)\r?\n'@", self.text, re.DOTALL)
        self.assertIsNotNone(match, "install_task.ps1 must define $launcher as a here-string")
        self.launcher_body = match.group(1)


class LauncherPassesArgumentsThroughTest(InstallTaskScriptTest):
    def test_the_launcher_forwards_its_own_arguments_to_sync_py(self):
        self.assertIn("@args", self.launcher_body,
                      "the launcher must splat its own arguments through to sync.py, "
                      "not decide on its caller's behalf")

    def test_the_sync_py_invocation_does_not_hardcode_quiet(self):
        invocation = next(line for line in self.launcher_body.splitlines()
                          if "sync.py" in line)
        self.assertNotIn("--quiet", invocation,
                         "the line invoking sync.py must not hardcode --quiet -- that is the "
                         "bug: it made the skill's invocation indistinguishable from the "
                         "scheduled task's. (--quiet may still appear elsewhere in the "
                         "launcher, e.g. the branch that CHECKS for it.)")
        self.assertIn("@args", invocation,
                      "the sync.py invocation itself must forward @args")


class LauncherPicksTheRightPythonTest(InstallTaskScriptTest):
    def test_pythonw_is_only_used_when_quiet_was_requested(self):
        self.assertIn("pythonw.exe", self.launcher_body)
        self.assertIn('$args -contains "--quiet"', self.launcher_body,
                      "pythonw.exe (no console at all) must be gated on --quiet being among "
                      "the forwarded arguments, so a human's visible-output run never goes "
                      "through it")

    def test_python_exe_is_available_for_a_visible_run(self):
        self.assertIn("python.exe", self.launcher_body,
                      "a run with no --quiet (the skill, run by a human) needs an "
                      "interpreter that actually has a console to print to")


class ScheduledTaskStillPassesQuietTest(unittest.TestCase):
    def setUp(self):
        with open(SCRIPT, encoding="utf-8") as handle:
            self.text = handle.read()

    def test_the_scheduled_task_action_passes_quiet_to_the_launcher(self):
        match = re.search(r'-Argument\s+"(.*)"\s*$', self.text, re.MULTILINE)
        self.assertIsNotNone(match, "install_task.ps1 must define the scheduled task action's "
                                    "-Argument string")
        self.assertIn("--quiet", match.group(1),
                      "the scheduled task must explicitly pass --quiet to run.ps1 now that "
                      "the launcher no longer hardcodes it")


if __name__ == "__main__":
    unittest.main()
