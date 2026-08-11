"""Guard: the plugin's version and CHANGELOG.md must agree.

CHANGELOG.md fell behind for a stretch -- entries were written when convenient
rather than as part of each version bump, and the file itself was not even
tracked in git for a while, so backfilling four releases at once was needed to
catch it up (see the [4.0.0] entry). A version bump with no matching changelog
heading is exactly the failure mode that produced that gap; this test turns it
into a build failure instead of a silent omission the next person has to
notice by hand.
"""
import json
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..", "..")
PLUGIN_JSON = os.path.join(ROOT, ".claude-plugin", "plugin.json")
CHANGELOG = os.path.join(ROOT, "CHANGELOG.md")


class ChangelogMatchesPluginVersionTest(unittest.TestCase):
    def test_the_changelog_has_a_heading_for_the_current_plugin_version(self):
        with open(PLUGIN_JSON, encoding="utf-8") as handle:
            version = json.load(handle)["version"]

        with open(CHANGELOG, encoding="utf-8") as handle:
            changelog = handle.read()

        heading = "## [%s]" % version
        self.assertIn(
            heading, changelog,
            "plugin.json is at version %r but CHANGELOG.md has no %r heading -- "
            "a version bump needs a changelog entry in the same commit" % (version, heading))


if __name__ == "__main__":
    unittest.main()
