# frontmatter-guard

A semantic linter for Claude Code skill/plugin frontmatter — and, since v0.2,
a manifest auditor for `.claude-plugin/plugin.json`. Catches the silent
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

And the official check has a second blind spot. Real-world probing
(non-strict `claude plugin validate` exits `0` on a broken skill) shows the
pattern clearly: **a green validate is not evidence the plugin works — and it
is certainly not evidence the plugin is safe.** A manifest can claim an
official-sounding name, declare no permissions, and ship hooks the manifest
never mentions, and the official validator will still smile and wave it
through.

frontmatter-guard closes both gaps:

- **v1 — frontmatter vocabulary:** it knows the real key vocabulary and the
  real hook event list, and tells you — with `file:line`, a rule name, and a
  fix suggestion — when something you wrote does nothing.
- **v2 — manifest audit (new):** for every `.claude-plugin/plugin.json` it
  audits the manifest's identity and capability claims against what is
  actually on disk — name impersonation, declared permissions vs. real
  hook/script capabilities, undeclared hooks, missing provenance — and emits
  a verdict (`pass` / `review` / `fail`) plus fix suggestions.

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

# audit a plugin directory (frontmatter + manifest layers)
frontmatter-guard check ./my-plugin

# machine-readable output for CI (includes the manifest verdict)
frontmatter-guard check . --format json
```

Frontmatter example output:

```
commands/deploy.md:4: error [unknown-key] Unknown key 'effort'.
    fix: Remove the key -- unknown keys are silently ignored, so it currently does nothing.
commands/deploy.md:5: error [unknown-key] Unknown key 'licence'. Did you mean 'license'?
    fix: Rename 'licence' to 'license'. Unknown keys are silently ignored, so fix the typo or remove the key.
commands/deploy.md:7: error [unknown-hook-event] Unknown hook event 'PreToolUs'. Did you mean 'PreToolUse'?
    fix: Rename 'PreToolUs' to 'PreToolUse'. Unknown hook events never fire.
frontmatter-guard: 3 error(s), 0 warning(s) in 1 file(s)
```

Manifest audit example output:

```
my-plugin/.claude-plugin/plugin.json:1: error [impersonating-name] Plugin name 'official-superpowers' uses the authority-borrowing prefix 'official'.
    fix: Drop the prefix and pick a name that does not borrow authority from Anthropic or from 'official' status.
my-plugin/.claude-plugin/plugin.json:1: error [undeclared-hooks] Hook scripts exist on disk but the manifest declares no 'hooks'.
    fix: Declare every hook in the manifest 'hooks' key (event -> commands), or remove the hook files. Undeclared hooks run code the manifest never admits to.
my-plugin/.claude-plugin/plugin.json:1: error [undeclared-capability] Plugin can do network, shell but declares no matching permission.
    fix: Add the capability to the manifest 'permissions' list (e.g. "permissions": ["Bash"]), or remove the code that needs it. Hidden capabilities are the classic supply-chain move.
my-plugin/.claude-plugin/plugin.json:1: warning [missing-provenance] Manifest is missing provenance field(s): author, repository, license, homepage.
    fix: Fill in author, repository, license, homepage so users can judge who ships this plugin and where it comes from.
frontmatter-guard: 3 error(s), 1 warning(s) in 1 file(s)
frontmatter-guard: manifest verdict: fail
```

Exit codes are CI-ready: exit `1` when any error-level finding exists (or any
warning under `--strict`); exit `0` when clean; exit `2` on usage errors. A
`fail` manifest verdict always means at least one error-level finding, so it
fails the build on its own.

## Rules

### Frontmatter (v1)

| Rule | Severity | What it catches |
|------|----------|-----------------|
| `unknown-key` | error | Top-level key not in the known skill/plugin vocabulary. Suggests the closest real key via difflib ("Did you mean 'license'?"). |
| `unknown-hook-event` | error | Hook event name not in Claude Code's event list (`PreToolUse`, `PostToolUse`, `SessionStart`, …). Unknown events never fire. |
| `missing-required` | error | `name` or `description` absent or empty. |
| `bad-version` | warning | `version` that isn't semver-ish (`1.2.3`, `v0.1`, `2.0.0-beta`). |
| `bad-type` | warning | Value of the wrong type (`hooks:` as a string, `name:` as a number, …). |
| `parse-warning` | warning | Frontmatter uses YAML beyond the supported subset — the file is still linted, not crashed. |

### Manifest audit (v2, `.claude-plugin/plugin.json` only)

| Rule | Severity | What it catches |
|------|----------|-----------------|
| `impersonating-name` | error | Name claims an official/blessed identity (`claude-code`, `anthropic-*`, `official-*`, `verified-*`). |
| `typosquat-name` | warning | Name is suspiciously close to an official name (`claaude-code`). |
| `undeclared-hooks` | error | Hook scripts exist on disk (`hooks.json`, `hooks/`, `scripts/`) but the manifest declares no `hooks`. |
| `undeclared-capability` | error | Observable capability (shell from hooks/scripts, network from hook commands or `mcpServers`) with no matching declared `permissions`. |
| `over-declared-permissions` | warning | Declared `permissions` with no observable capability to justify them. |
| `missing-provenance` | warning | `author` / `repository` / `license` / `homepage` missing — nobody to hold accountable. |

The manifest verdict rolls the findings up: `pass` (clean), `review`
(warnings only), `fail` (any error).

Scans `*.md` frontmatter (`---` fences) and `plugin.json` files. The built-in
YAML parser is stdlib-only and covers the shapes frontmatter actually uses:
scalars, block maps/sequences, inline flow collections, literal blocks.
Anything fancier gets a warning, never an exception.

## How it differs

- **vs `claude plugin validate` (official):** the official validator checks
  compatibility and structure — "will this plugin load?" frontmatter-guard
  checks semantic strictness — "does everything you wrote actually do
  something?" Unknown keys sail through the official check silently; they
  fail here. And the official check is neither a working guarantee nor a
  security guarantee: non-strict validate exits `0` on broken skills, and it
  never looks at whether the manifest's claims match reality. The v2 manifest
  layer is a second dimension on top of the v1 frontmatter dimension —
  identity and capability claims audited against disk.
- **vs damson/skill-lint:** that project is a CI action doing structural
  checks on skills. frontmatter-guard is a local, stdlib-only CLI doing
  *semantic* checks (typo suggestions, event-name validation, type/format
  checks, manifest audits). Use it in pre-commit for instant feedback *and*
  in CI for enforcement — same command, both places.

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
python3 -m unittest discover -s tests   # 51 tests, stdlib only
```

## License

MIT. See [LICENSE](LICENSE).
