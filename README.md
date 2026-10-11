# frontmatter-guard

A semantic linter for Claude Code skill/plugin frontmatter. Catches the silent
mistakes the official validator waves through.

## The problem

`claude plugin validate` checks that your plugin is structurally compatible.
It does **not** check that your frontmatter keys actually mean anything. I
found this out the embarrassing way: I had written `effort: high` in a command
frontmatter, expecting it to constrain the model. `claude plugin validate`
passed it without a word. In reality `effort` is not a Claude Code frontmatter
key at all — it is a Codex concept — so my setting silently fell back to the
session default and I had no idea.

Misspelled keys and misspelled hook events fail the same silent way:
`PreToolUs` never fires, `licence` never licenses anything, and nothing ever
tells you.

frontmatter-guard closes that gap: it knows the real key vocabulary and the
real hook event list, and it tells you — with `file:line`, a rule name, and a
fix suggestion — when something you wrote does nothing.

## Install

```bash
pip install frontmatter-guard
```

Zero dependencies. Python 3.9+. Works anywhere, including pre-commit and CI.

## Quickstart

```bash
# lint one file or a whole directory
frontmatter-guard check SKILL.md
frontmatter-guard check .claude/ --strict

# machine-readable output for CI
frontmatter-guard check . --format json
```

Example output:

```
commands/deploy.md:4: error [unknown-key] Unknown key 'effort'.
    fix: Remove the key -- unknown keys are silently ignored, so it currently does nothing.
commands/deploy.md:5: error [unknown-key] Unknown key 'licence'. Did you mean 'license'?
    fix: Rename 'licence' to 'license'. Unknown keys are silently ignored, so fix the typo or remove the key.
commands/deploy.md:7: error [unknown-hook-event] Unknown hook event 'PreToolUs'. Did you mean 'PreToolUse'?
    fix: Rename 'PreToolUs' to 'PreToolUse'. Unknown hook events never fire.
frontmatter-guard: 3 error(s), 0 warning(s) in 1 file(s)
```

Exit codes are CI-ready: exit `1` when any error-level finding exists (or any
warning under `--strict`); exit `0` when clean; exit `2` on usage errors.

## Rules

| Rule | Severity | What it catches |
|------|----------|-----------------|
| `unknown-key` | error | Top-level key not in the known skill/plugin vocabulary. Suggests the closest real key via difflib ("Did you mean 'license'?"). |
| `unknown-hook-event` | error | Hook event name not in Claude Code's event list (`PreToolUse`, `PostToolUse`, `SessionStart`, …). Unknown events never fire. |
| `missing-required` | error | `name` or `description` absent or empty. |
| `bad-version` | warning | `version` that isn't semver-ish (`1.2.3`, `v0.1`, `2.0.0-beta`). |
| `bad-type` | warning | Value of the wrong type (`hooks:` as a string, `name:` as a number, …). |
| `parse-warning` | warning | Frontmatter uses YAML beyond the supported subset — the file is still linted, not crashed. |

Scans `*.md` frontmatter (`---` fences) and `plugin.json` files. The built-in
YAML parser is stdlib-only and covers the shapes frontmatter actually uses:
scalars, block maps/sequences, inline flow collections, literal blocks.
Anything fancier gets a warning, never an exception.

## How it differs

- **vs `claude plugin validate` (official):** the official validator checks
  compatibility and structure — "will this plugin load?" frontmatter-guard
  checks semantic strictness — "does everything you wrote actually do
  something?" Unknown keys sail through the official check silently; they
  fail here.
- **vs damson/skill-lint:** that project is a CI action doing structural
  checks on skills. frontmatter-guard is a local, stdlib-only CLI doing
  *semantic* checks (typo suggestions, event-name validation, type/format
  checks). Use it in pre-commit for instant feedback *and* in CI for
  enforcement — same command, both places.

## CI integration

GitHub Actions:

```yaml
- name: Lint skill/plugin frontmatter
  run: |
    pip install frontmatter-guard
    frontmatter-guard check . --strict
```

pre-commit:

```yaml
repos:
  - repo: local
    hooks:
      - id: frontmatter-guard
        name: frontmatter-guard
        entry: frontmatter-guard check
        language: system
        types: [markdown]
        args: [--strict]
```

## Development

```bash
python3 -m unittest discover -s tests   # 34 tests, stdlib only
```

## License

MIT. See [LICENSE](LICENSE).
