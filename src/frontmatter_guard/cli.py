"""Command-line interface for frontmatter-guard."""

import argparse
import json
import os
import sys

from . import __version__
from .schema import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    extract_md_frontmatter,
    lint_frontmatter,
)

SCAN_EXTENSIONS = (".md",)
SCAN_FILENAMES = ("plugin.json",)


def iter_target_files(path):
    """Yield (path) for every scannable file under path."""
    if os.path.isfile(path):
        yield path
        return
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs
                   if d not in (".git", "__pycache__", "node_modules",
                                ".venv", "venv", "dist", "build")]
        for name in sorted(files):
            full = os.path.join(root, name)
            if name.endswith(SCAN_EXTENSIONS) or name in SCAN_FILENAMES:
                yield full


def lint_file(path):
    """Lint one file. Returns a list of finding dicts."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        return [{
            "file": path,
            "line": 1,
            "rule": "unreadable",
            "severity": SEVERITY_ERROR,
            "message": "Could not read file: %s" % exc,
            "fix": "Check file permissions and encoding (UTF-8 expected).",
        }]

    findings = []
    name = os.path.basename(path)

    if name.endswith(".md"):
        extracted = extract_md_frontmatter(text)
        if extracted is None:
            if name == "SKILL.md":
                findings.append({
                    "file": path,
                    "line": 1,
                    "rule": "no-frontmatter",
                    "severity": SEVERITY_WARNING,
                    "message": "SKILL.md has no frontmatter block.",
                    "fix": "Add a --- fenced frontmatter block with at "
                           "least name and description.",
                })
            return findings
        data, key_lines, start_line, parse_warnings = extracted
        for warning in parse_warnings:
            findings.append({
                "file": path,
                "line": start_line,
                "rule": "parse-warning",
                "severity": SEVERITY_WARNING,
                "message": "Frontmatter YAML: %s." % warning,
                "fix": "Simplify the frontmatter to plain key: value pairs, "
                       "lists and nested maps.",
            })
        findings.extend(lint_frontmatter(data, key_lines, path, start_line))
        return findings

    # plugin.json and friends: JSON object, same key vocabulary
    try:
        data = json.loads(text)
    except ValueError as exc:
        return [{
            "file": path,
            "line": 1,
            "rule": "parse-warning",
            "severity": SEVERITY_ERROR,
            "message": "Invalid JSON: %s" % exc,
            "fix": "Fix the JSON syntax.",
        }]
    if not isinstance(data, dict):
        return [{
            "file": path,
            "line": 1,
            "rule": "bad-type",
            "severity": SEVERITY_ERROR,
            "message": "Top-level JSON value must be an object.",
            "fix": "Make the top level a JSON object with plugin keys.",
        }]
    key_lines = {key: 1 for key in data}
    return lint_frontmatter(data, key_lines, path, start_line=1)


def check_targets(targets):
    findings = []
    files = []
    for target in targets:
        if not os.path.exists(target):
            return None, ["no such file or directory: %s" % target]
        for path in iter_target_files(target):
            files.append(path)
            findings.extend(lint_file(path))
    return (files, findings), []


def format_text(files, findings):
    out = []
    for finding in findings:
        out.append("%s:%s: %s [%s] %s"
                   % (finding["file"], finding["line"],
                      finding["severity"], finding["rule"],
                      finding["message"]))
        if finding.get("fix"):
            out.append("    fix: %s" % finding["fix"])
    errors = sum(1 for f in findings if f["severity"] == SEVERITY_ERROR)
    warnings = sum(1 for f in findings if f["severity"] == SEVERITY_WARNING)
    out.append("frontmatter-guard: %d error(s), %d warning(s) in %d file(s)"
               % (errors, warnings, len(files)))
    return "\n".join(out)


def format_json(files, findings):
    errors = sum(1 for f in findings if f["severity"] == SEVERITY_ERROR)
    warnings = sum(1 for f in findings if f["severity"] == SEVERITY_WARNING)
    return json.dumps({
        "tool": "frontmatter-guard",
        "version": __version__,
        "files": files,
        "findings": findings,
        "summary": {
            "files": len(files),
            "errors": errors,
            "warnings": warnings,
        },
    }, indent=2)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="frontmatter-guard",
        description="Semantic linter for Claude Code skill/plugin "
                    "frontmatter.")
    parser.add_argument("--version", action="version",
                        version="frontmatter-guard %s" % __version__)
    sub = parser.add_subparsers(dest="command")
    check = sub.add_parser("check", help="Lint frontmatter in a file or "
                                         "directory.")
    check.add_argument("targets", nargs="+",
                       help="File(s) or directorie(s) to scan.")
    check.add_argument("--format", choices=("text", "json"), default="text",
                       help="Output format (default: text).")
    check.add_argument("--strict", action="store_true",
                       help="Treat warnings as failures (exit 1).")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command != "check":
        parser.print_help()
        return 2

    result, errors = check_targets(args.targets)
    if result is None:
        for error in errors:
            print("frontmatter-guard: error: %s" % error, file=sys.stderr)
        return 2
    files, findings = result

    if args.format == "json":
        print(format_json(files, findings))
    else:
        print(format_text(files, findings))

    error_count = sum(1 for f in findings
                      if f["severity"] == SEVERITY_ERROR)
    warning_count = sum(1 for f in findings
                        if f["severity"] == SEVERITY_WARNING)
    if error_count > 0:
        return 1
    if args.strict and warning_count > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
