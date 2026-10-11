"""Tests for the YAML-subset parser and semantic rules."""
import unittest

from frontmatter_guard.schema import (
    extract_md_frontmatter,
    lint_frontmatter,
    parse_yaml_subset,
)


def lint_text(frontmatter_block, path="SKILL.md"):
    """Parse + lint a raw frontmatter block (without --- fences)."""
    data, key_lines, warnings = parse_yaml_subset(frontmatter_block)
    findings = lint_frontmatter(data, key_lines, path)
    return data, warnings, findings


def rules(findings):
    return [(f["rule"], f["severity"]) for f in findings]


class ParserTest(unittest.TestCase):
    def test_simple_map_and_line_numbers(self):
        data, key_lines, warnings = parse_yaml_subset(
            "name: my-skill\ndescription: does things\n")
        self.assertEqual(data, {"name": "my-skill", "description": "does things"})
        self.assertEqual(key_lines, {"name": 1, "description": 2})
        self.assertEqual(warnings, [])

    def test_quoted_and_typed_scalars(self):
        data, _, _ = parse_yaml_subset(
            'a: "1"\nb: 2\nc: true\nd: 1.5\ne:\n')
        self.assertEqual(data, {"a": "1", "b": 2, "c": True, "d": 1.5,
                                "e": None})

    def test_nested_hooks_block_parses_cleanly(self):
        block = (
            "name: s\n"
            "description: d\n"
            "hooks:\n"
            "  PreToolUse:\n"
            "    - matcher: \"Bash\"\n"
            "      hooks:\n"
            "        - type: command\n"
            "          command: \"echo hi\"\n"
        )
        data, key_lines, warnings = parse_yaml_subset(block)
        self.assertEqual(warnings, [])
        self.assertEqual(key_lines["hooks"], 3)
        hooks = data["hooks"]
        self.assertIn("PreToolUse", hooks)
        self.assertEqual(hooks["PreToolUse"][0]["matcher"], "Bash")
        self.assertEqual(hooks["PreToolUse"][0]["hooks"][0]["type"], "command")

    def test_block_list_and_inline_flow(self):
        data, _, warnings = parse_yaml_subset(
            "keywords: [a, b]\nallowed-tools:\n  - Bash\n  - Read\n")
        self.assertEqual(warnings, [])
        self.assertEqual(data["keywords"], ["a", "b"])
        self.assertEqual(data["allowed-tools"], ["Bash", "Read"])

    def test_literal_block(self):
        data, _, warnings = parse_yaml_subset(
            "description: |\n  line one\n  line two\nname: s\n")
        self.assertEqual(warnings, [])
        self.assertEqual(data["description"], "line one\nline two")
        self.assertEqual(data["name"], "s")

    def test_anchor_warns_not_crash(self):
        data, _, warnings = parse_yaml_subset("a: &x 1\nb: *x\n")
        self.assertTrue(any("unsupported" in w for w in warnings))
        self.assertIn("a", data)

    def test_comments_and_blanks_ignored(self):
        data, key_lines, warnings = parse_yaml_subset(
            "# comment\n\nname: s # trailing?\n")
        # trailing comment stays part of the scalar in this subset
        self.assertEqual(key_lines["name"], 3)
        self.assertEqual(warnings, [])

    def test_duplicate_key_warns(self):
        _, _, warnings = parse_yaml_subset("name: a\nname: b\n")
        self.assertTrue(any("duplicate" in w for w in warnings))

    def test_frontmatter_extraction(self):
        text = "---\nname: s\ndescription: d\n---\n\n# body\n"
        data, key_lines, start, warnings = extract_md_frontmatter(text)
        self.assertEqual(data, {"name": "s", "description": "d"})
        self.assertEqual(key_lines["name"], 2)
        self.assertEqual(start, 1)

    def test_no_frontmatter_returns_none(self):
        self.assertIsNone(extract_md_frontmatter("# no fences\n"))


class RulesTest(unittest.TestCase):
    def test_clean_skill_has_no_findings(self):
        _, _, findings = lint_text(
            "name: my-skill\ndescription: does things\nlicense: MIT\n")
        self.assertEqual(findings, [])

    def test_missing_required(self):
        _, _, findings = lint_text("name: s\n")
        self.assertIn(("missing-required", "error"), rules(findings))
        self.assertTrue(any("description" in f["message"] for f in findings))

    def test_empty_required_value_counts_as_missing(self):
        _, _, findings = lint_text("name: s\ndescription:\n")
        self.assertIn(("missing-required", "error"), rules(findings))

    def test_unknown_key_typo_suggests(self):
        _, _, findings = lint_text(
            "name: s\ndescription: d\ndescripton: x\n")
        hit = [f for f in findings if f["rule"] == "unknown-key"]
        self.assertEqual(len(hit), 1)
        self.assertIn("description", hit[0]["message"])
        self.assertEqual(hit[0]["line"], 3)
        self.assertEqual(hit[0]["severity"], "error")

    def test_unknown_key_effort_no_crash(self):
        _, _, findings = lint_text("name: s\ndescription: d\neffort: high\n")
        hit = [f for f in findings if f["rule"] == "unknown-key"]
        self.assertEqual(len(hit), 1)
        self.assertIn("silently ignored", hit[0]["fix"])

    def test_unknown_hook_event_suggests(self):
        data, _, findings = lint_text(
            "name: s\ndescription: d\nhooks:\n  PreToolUs:\n    - x\n")
        hit = [f for f in findings if f["rule"] == "unknown-hook-event"]
        self.assertEqual(len(hit), 1)
        self.assertIn("PreToolUse", hit[0]["message"])
        self.assertEqual(hit[0]["severity"], "error")

    def test_known_hook_events_pass(self):
        block = ("name: s\ndescription: d\nhooks:\n"
                 "  PreToolUse:\n    - x\n  SessionStart:\n    - y\n")
        _, _, findings = lint_text(block)
        self.assertNotIn("unknown-hook-event",
                         [f["rule"] for f in findings])

    def test_bad_version_warns(self):
        _, _, findings = lint_text(
            "name: s\ndescription: d\nversion: latest\n")
        hit = [f for f in findings if f["rule"] == "bad-version"]
        self.assertEqual(len(hit), 1)
        self.assertEqual(hit[0]["severity"], "warning")

    def test_good_versions_pass(self):
        for version in ("1.2.3", "v0.1", "2", "1.0.0-beta.1"):
            _, _, findings = lint_text(
                "name: s\ndescription: d\nversion: %s\n" % version)
            self.assertNotIn("bad-version", [f["rule"] for f in findings],
                             version)

    def test_hooks_wrong_type_warns(self):
        _, _, findings = lint_text(
            "name: s\ndescription: d\nhooks: sometimes\n")
        hit = [f for f in findings if f["rule"] == "bad-type"]
        self.assertEqual(len(hit), 1)
        self.assertEqual(hit[0]["severity"], "warning")

    def test_name_wrong_type_warns(self):
        _, _, findings = lint_text("name: 42\ndescription: d\n")
        hit = [f for f in findings if f["rule"] == "bad-type"]
        self.assertEqual(len(hit), 1)

    def test_non_mapping_data(self):
        findings = lint_frontmatter(["not", "a", "map"], {}, "SKILL.md")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["rule"], "bad-type")


if __name__ == "__main__":
    unittest.main()
