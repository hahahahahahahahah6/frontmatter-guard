"""End-to-end tests for the frontmatter-guard CLI."""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout

from frontmatter_guard.cli import main


def run_cli(args):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(args)
    return code, buf.getvalue()


def write(tmp, name, content):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    return path


CLEAN_SKILL = """---
name: clean-skill
description: A tidy skill.
license: MIT
hooks:
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "echo hi"
---
"""

DIRTY_SKILL = """---
name: dirty-skill
descripton: oops typo
effort: high
hooks:
  PreToolUs:
    - matcher: "Bash"
---
"""

WARN_ONLY_SKILL = """---
name: warn-skill
description: has a bad version
version: someday
---
"""


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_clean_file_exits_zero(self):
        path = write(self.tmp.name, "SKILL.md", CLEAN_SKILL)
        code, out = run_cli(["check", path])
        self.assertEqual(code, 0, out)
        self.assertIn("0 error(s)", out)

    def test_dirty_file_exits_one_with_file_line(self):
        path = write(self.tmp.name, "SKILL.md", DIRTY_SKILL)
        code, out = run_cli(["check", path])
        self.assertEqual(code, 1, out)
        self.assertIn("unknown-key", out)
        self.assertIn("unknown-hook-event", out)
        self.assertIn("missing-required", out)  # description typo'd away
        self.assertIn("%s:" % path, out)
        self.assertIn("[unknown-key]", out)

    def test_typo_suggestion_in_output(self):
        path = write(self.tmp.name, "SKILL.md", DIRTY_SKILL)
        _, out = run_cli(["check", path])
        self.assertIn("Did you mean 'description'?", out)

    def test_warnings_only_exit_zero_by_default(self):
        path = write(self.tmp.name, "SKILL.md", WARN_ONLY_SKILL)
        code, out = run_cli(["check", path])
        self.assertEqual(code, 0, out)
        self.assertIn("1 warning(s)", out)

    def test_strict_turns_warnings_into_failure(self):
        path = write(self.tmp.name, "SKILL.md", WARN_ONLY_SKILL)
        code, _ = run_cli(["check", path, "--strict"])
        self.assertEqual(code, 1)

    def test_json_format(self):
        path = write(self.tmp.name, "SKILL.md", DIRTY_SKILL)
        code, out = run_cli(["check", path, "--format", "json"])
        self.assertEqual(code, 1)
        payload = json.loads(out)
        self.assertEqual(payload["summary"]["errors"], 4)
        rules = {f["rule"] for f in payload["findings"]}
        self.assertTrue({"unknown-key", "unknown-hook-event",
                         "missing-required"} <= rules)
        for finding in payload["findings"]:
            self.assertIn("file", finding)
            self.assertIn("line", finding)
            self.assertIn("fix", finding)

    def test_directory_scan(self):
        write(self.tmp.name, "SKILL.md", CLEAN_SKILL)
        sub = os.path.join(self.tmp.name, "commands")
        os.makedirs(sub)
        write(sub, "deploy.md", DIRTY_SKILL)
        code, out = run_cli(["check", self.tmp.name])
        self.assertEqual(code, 1, out)
        self.assertIn("2 file(s)", out)

    def test_plugin_json_linted(self):
        payload = json.dumps({
            "name": "my-plugin",
            "descripton": "typo",
            "version": "not-a-version",
        })
        path = write(self.tmp.name, "plugin.json", payload)
        code, out = run_cli(["check", path])
        self.assertEqual(code, 1, out)
        self.assertIn("unknown-key", out)
        self.assertIn("bad-version", out)
        self.assertIn("missing-required", out)

    def test_plugin_json_invalid(self):
        path = write(self.tmp.name, "plugin.json", "{oops")
        code, out = run_cli(["check", path])
        self.assertEqual(code, 1, out)
        self.assertIn("Invalid JSON", out)

    def test_missing_path_exits_two(self):
        code, _ = run_cli(["check", os.path.join(self.tmp.name, "nope")])
        self.assertEqual(code, 2)

    def test_skill_md_without_frontmatter_warns(self):
        path = write(self.tmp.name, "SKILL.md", "# no frontmatter\n")
        code, out = run_cli(["check", path])
        self.assertEqual(code, 0, out)
        self.assertIn("no-frontmatter", out)
        code, _ = run_cli(["check", path, "--strict"])
        self.assertEqual(code, 1)

    def test_non_skill_md_without_frontmatter_skipped(self):
        path = write(self.tmp.name, "notes.md", "# just notes\n")
        code, out = run_cli(["check", path])
        self.assertEqual(code, 0, out)
        self.assertIn("0 error(s), 0 warning(s)", out)


if __name__ == "__main__":
    unittest.main()
