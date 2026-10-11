"""Known vocabulary and semantic lint rules for skill/plugin frontmatter.

Covers two morphologies:
  * SKILL.md (and command) frontmatter -- YAML block between --- fences
  * plugin.json -- JSON object at the repo root

The YAML parser below handles a small, well-defined subset of YAML:
scalars (quoted/unquoted/numbers/booleans), block maps, block sequences,
inline flow collections, and literal blocks (|, >). Anything beyond that
(anchors, aliases, tags, tabs) produces a warning, never a crash.
"""

import difflib
import re

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"

# ---------------------------------------------------------------------------
# Known vocabulary
# ---------------------------------------------------------------------------

# Frontmatter keys recognized in SKILL.md / command .md files.
SKILL_KEYS = frozenset({
    "name",
    "description",
    "license",
    "allowed-tools",
    "argument-hint",
    "disable-model-invocation",
    "user-invocable",
    "context",
    "agent",
    "model",
    "hooks",
    "metadata",
})

# Keys recognized in plugin.json / marketplace plugin descriptors.
PLUGIN_KEYS = frozenset({
    "name",
    "description",
    "version",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
    "hooks",
    "mcpServers",
    "commands",
    "agents",
    "skills",
    "dependencies",
    "installPath",
    "scripts",
    "engines",
    "funding",
    "permissions",
})

KNOWN_KEYS = SKILL_KEYS | PLUGIN_KEYS

# Claude Code hook events (settings.json `hooks` + skill frontmatter).
HOOK_EVENTS = frozenset({
    "PreToolUse",
    "PostToolUse",
    "Notification",
    "UserPromptSubmit",
    "Stop",
    "SubagentStop",
    "SessionStart",
    "SessionEnd",
    "PreCompact",
})

REQUIRED_KEYS = ("name", "description")

# Acceptable Python types per key, as type-name strings.
KEY_TYPES = {
    "name": ("str",),
    "description": ("str",),
    "version": ("str", "int", "float"),
    "author": ("str", "dict"),
    "homepage": ("str",),
    "repository": ("str", "dict"),
    "license": ("str",),
    "keywords": ("list",),
    "hooks": ("dict", "list"),
    "mcpServers": ("dict", "list"),
    "commands": ("list",),
    "agents": ("list",),
    "skills": ("list",),
    "dependencies": ("list", "dict"),
    "installPath": ("str",),
    "scripts": ("dict", "list"),
    "engines": ("dict",),
    "funding": ("str", "list", "dict"),
    "allowed-tools": ("str", "list"),
    "argument-hint": ("str",),
    "model": ("str",),
    "context": ("str", "list", "dict"),
    "agent": ("str", "dict"),
    "metadata": ("dict",),
    "disable-model-invocation": ("bool",),
    "user-invocable": ("bool",),
}

SEMVER_RE = re.compile(r"^v?\d+(\.\d+){0,2}([-+][0-9A-Za-z.\-]+)?$")

# Keys that look plausible but are silently ignored by Claude Code.
# Kept as documentation of the pain point; difflib handles suggestions.
NOT_A_KEY = {
    "effort",  # Codex concept; does nothing in Claude Code frontmatter
}

# ---------------------------------------------------------------------------
# Small YAML-subset parser
# ---------------------------------------------------------------------------

_MAP_KEY_RE = re.compile(
    r"""^("([^"]*)"|'([^']*)'|([A-Za-z0-9_][A-Za-z0-9_\-\.]*))\s*:(?:\s+(.*))?$"""
)

_WARNING_UNSUPPORTED = (
    "unsupported YAML construct; only simple maps, sequences, scalars, "
    "inline flow collections and literal blocks are supported"
)


def _looks_like_map_entry(text):
    return bool(_MAP_KEY_RE.match(text))


def _split_map_entry(text):
    m = _MAP_KEY_RE.match(text)
    key = m.group(2) or m.group(3) or m.group(4)
    rest = m.group(5)
    return key, ("" if rest is None else rest.strip())


def _looks_like_list_item(text):
    return text == "-" or text.startswith("- ")


def _split_flow(inner):
    """Split flow-collection contents on top-level commas."""
    parts, depth, quote, current = [], 0, None, []
    for ch in inner:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote, current = ch, current + [ch]
        elif ch in ("[", "{"):
            depth += 1
            current.append(ch)
        elif ch in ("]", "}"):
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return parts


def _scalar(text, warnings, line):
    t = text.strip()
    if t == "" or t in ("~", "null", "Null", "NULL"):
        return None
    if len(t) >= 2 and t[0] == t[-1] and t[0] in ("'", '"'):
        return t[1:-1]
    if t.startswith("&") or t.startswith("*"):
        warnings.append(
            "line %d: %s (anchors/aliases)" % (line, _WARNING_UNSUPPORTED))
        return t
    if t.startswith("!"):
        warnings.append("line %d: %s (tags)" % (line, _WARNING_UNSUPPORTED))
        return t
    if t.startswith("[") and t.endswith("]"):
        inner = t[1:-1].strip()
        if not inner:
            return []
        return [_scalar(p, warnings, line) for p in _split_flow(inner)]
    if t.startswith("{") and t.endswith("}"):
        inner = t[1:-1].strip()
        if not inner:
            return {}
        result = {}
        for part in _split_flow(inner):
            k, _, v = part.partition(":")
            result[_scalar(k.strip(), warnings, line)] = _scalar(v.strip(), warnings, line)
        return result
    low = t.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        pass
    return t


def _clean_lines(block_text, base_line):
    """Drop blanks/comments, compute indent; warn on tabs."""
    lines, warnings = [], []
    for i, raw in enumerate(block_text.splitlines()):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "\t" in raw[:len(raw) - len(raw.lstrip())]:
            warnings.append("line %d: tab indentation is not valid YAML"
                            % (base_line + i))
        indent = len(raw) - len(raw.lstrip(" "))
        lines.append((indent, stripped, base_line + i))
    return lines, warnings


def _skip_block(lines, idx, indent, warnings):
    while idx < len(lines) and lines[idx][0] > indent:
        idx += 1
    return idx


def _parse_block(lines, idx, indent, warnings):
    """Parse one mapping or sequence block. Returns (value, next_idx)."""
    if idx >= len(lines) or lines[idx][0] != indent:
        return None, idx
    if _looks_like_list_item(lines[idx][1]):
        return _parse_seq(lines, idx, indent, warnings)
    if _looks_like_map_entry(lines[idx][1]):
        value, _, next_idx = _parse_map(lines, idx, indent, warnings)
        return value, next_idx
    warnings.append("line %d: %s" % (lines[idx][2], _WARNING_UNSUPPORTED))
    return _scalar(lines[idx][1], warnings, lines[idx][2]), idx + 1


def _consume_literal(lines, idx, indent, warnings):
    """Consume a | or > literal block as one string."""
    chunks = []
    base_indent = None
    while idx < len(lines) and lines[idx][0] > indent:
        if base_indent is None:
            base_indent = lines[idx][0]
        if lines[idx][0] < base_indent:
            break
        chunks.append(lines[idx][1])
        idx += 1
    return "\n".join(chunks), idx


def _parse_map(lines, idx, indent, warnings, first_entry=None):
    result, key_lines = {}, {}
    if first_entry is not None:
        key, rest, line_no = first_entry
        value, idx = _map_value(lines, idx, indent, rest, line_no, warnings)
        result[key] = value
        key_lines[key] = line_no
    while idx < len(lines) and lines[idx][0] == indent \
            and _looks_like_map_entry(lines[idx][1]):
        key, rest = _split_map_entry(lines[idx][1])
        line_no = lines[idx][2]
        if key in result:
            warnings.append("line %d: duplicate key '%s'" % (line_no, key))
        value, idx = _map_value(lines, idx + 1, indent, rest, line_no, warnings)
        result[key] = value
        key_lines[key] = line_no
    return result, key_lines, idx


def _map_value(lines, idx, indent, rest, line_no, warnings):
    if rest in ("|", ">", "|-", ">-", "|+", ">+"):
        if idx < len(lines) and lines[idx][0] > indent:
            return _consume_literal(lines, idx, indent, warnings)
        return "", idx
    if rest == "":
        if idx < len(lines) and lines[idx][0] > indent:
            value, idx = _parse_block(lines, idx, lines[idx][0], warnings)
            return value, idx
        return None, idx
    if rest.startswith("&") or rest.startswith("*") or rest.startswith("!"):
        warnings.append("line %d: %s" % (line_no, _WARNING_UNSUPPORTED))
        return rest, idx
    return _scalar(rest, warnings, line_no), idx


def _parse_seq(lines, idx, indent, warnings):
    result = []
    while idx < len(lines) and lines[idx][0] == indent \
            and _looks_like_list_item(lines[idx][1]):
        content = lines[idx][1][1:].strip()  # after '-'
        line_no = lines[idx][2]
        next_idx = idx + 1
        child_deeper = (next_idx < len(lines)
                        and lines[next_idx][0] > indent)
        if content == "":
            if child_deeper:
                value, next_idx = _parse_block(
                    lines, next_idx, lines[next_idx][0], warnings)
            else:
                value = None
            result.append(value)
        elif _looks_like_map_entry(content) and child_deeper:
            # "- key: value" followed by more indented map entries
            key, rest = _split_map_entry(content)
            item, _, next_idx = _parse_map(
                lines, next_idx, lines[next_idx][0], warnings,
                first_entry=(key, rest, line_no))
            result.append(item)
        else:
            if child_deeper:
                warnings.append(
                    "line %d: unexpected indented block after scalar "
                    "list item" % line_no)
                next_idx = _skip_block(lines, next_idx, indent, warnings)
            value = _scalar(content, warnings, line_no)
            if _looks_like_map_entry(content):
                # "- key: value" with no children -> single-pair map
                key, rest = _split_map_entry(content)
                value = {key: _scalar(rest, warnings, line_no)}
            result.append(value)
        idx = next_idx
    return result, idx


def parse_yaml_subset(block_text, base_line=1):
    """Parse a YAML subset. Returns (value, key_lines, warnings).

    key_lines maps top-level keys to 1-based source line numbers.
    """
    lines, warnings = _clean_lines(block_text, base_line)
    if not lines:
        return {}, {}, warnings
    value, key_lines, idx = _parse_map(lines, 0, lines[0][0], warnings)
    if idx < len(lines):
        warnings.append(
            "line %d: trailing content could not be parsed (%s)"
            % (lines[idx][2], _WARNING_UNSUPPORTED))
    return value, key_lines, warnings


# ---------------------------------------------------------------------------
# Frontmatter extraction
# ---------------------------------------------------------------------------

def extract_md_frontmatter(text):
    """Extract a --- fenced frontmatter block. Returns (data, key_lines,
    start_line, warnings) or None when there is no frontmatter."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            end = i
            break
    if end is None:
        return None
    block = "\n".join(lines[1:end])
    data, key_lines, warnings = parse_yaml_subset(block, base_line=2)
    return data, key_lines, 1, warnings


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def _suggest(word, candidates, cutoff=0.6):
    matches = difflib.get_close_matches(word, sorted(candidates), n=1,
                                        cutoff=cutoff)
    return matches[0] if matches else None


def _finding(path, line, rule, severity, message, fix):
    return {
        "file": path,
        "line": line,
        "rule": rule,
        "severity": severity,
        "message": message,
        "fix": fix,
    }


def lint_frontmatter(data, key_lines, path, start_line=1):
    """Run semantic rules over a parsed frontmatter mapping."""
    findings = []
    if not isinstance(data, dict):
        return [_finding(
            path, start_line, "bad-type", SEVERITY_WARNING,
            "Frontmatter did not parse to a mapping; semantic checks skipped.",
            "Make sure the frontmatter block is a flat key: value mapping.")]
    data = data or {}

    # missing-required
    for key in REQUIRED_KEYS:
        if key not in data or data[key] in (None, ""):
            findings.append(_finding(
                path, start_line, "missing-required", SEVERITY_ERROR,
                "Required key '%s' is missing or empty." % key,
                "Add '%s: <value>' to the frontmatter block." % key))

    # unknown-key
    for key in data:
        if key not in KNOWN_KEYS:
            suggestion = _suggest(key, KNOWN_KEYS)
            msg = "Unknown key '%s'." % key
            fix = ("Remove the key -- unknown keys are silently ignored, "
                   "so it currently does nothing.")
            if suggestion:
                msg += " Did you mean '%s'?" % suggestion
                fix = ("Rename '%s' to '%s'. Unknown keys are silently "
                       "ignored, so fix the typo or remove the key."
                       % (key, suggestion))
            findings.append(_finding(
                path, key_lines.get(key, start_line), "unknown-key",
                SEVERITY_ERROR, msg, fix))

    # bad-type
    for key, value in data.items():
        if key not in KEY_TYPES or value is None:
            continue
        type_name = type(value).__name__
        if type_name == "bool":
            ok = "bool" in KEY_TYPES[key]
        else:
            ok = type_name in KEY_TYPES[key]
        if not ok:
            findings.append(_finding(
                path, key_lines.get(key, start_line), "bad-type",
                SEVERITY_WARNING,
                "Key '%s' should be %s, got %s."
                % (key, " or ".join(KEY_TYPES[key]), type_name),
                "Change the value of '%s' to the expected type." % key))

    # bad-version
    if "version" in data and data["version"] is not None:
        version = str(data["version"])
        if not SEMVER_RE.match(version):
            findings.append(_finding(
                path, key_lines.get("version", start_line), "bad-version",
                SEVERITY_WARNING,
                "Version '%s' is not semver-ish (expected like 1.2.3)."
                % version,
                "Use a semver-ish version such as '0.1.0'."))

    # hooks: container type + known event names
    if "hooks" in data and data["hooks"] is not None:
        hooks = data["hooks"]
        if isinstance(hooks, dict):
            for event in hooks:
                if event not in HOOK_EVENTS:
                    suggestion = _suggest(event, HOOK_EVENTS)
                    msg = "Unknown hook event '%s'." % event
                    fix = ("Remove it -- unknown hook events never fire, "
                           "so the hook currently does nothing.")
                    if suggestion:
                        msg += " Did you mean '%s'?" % suggestion
                        fix = ("Rename '%s' to '%s'. Unknown hook events "
                               "never fire." % (event, suggestion))
                    findings.append(_finding(
                        path, key_lines.get("hooks", start_line),
                        "unknown-hook-event", SEVERITY_ERROR, msg, fix))
        elif isinstance(hooks, list):
            for i, entry in enumerate(hooks):
                if isinstance(entry, dict):
                    for event in entry:
                        if event not in HOOK_EVENTS:
                            suggestion = _suggest(event, HOOK_EVENTS)
                            msg = ("Unknown hook event '%s' in hooks[%d]."
                                   % (event, i))
                            fix = ("Remove it -- unknown hook events never "
                                   "fire.")
                            if suggestion:
                                msg += " Did you mean '%s'?" % suggestion
                                fix = ("Rename '%s' to '%s'." % (event, suggestion))
                            findings.append(_finding(
                                path, key_lines.get("hooks", start_line),
                                "unknown-hook-event", SEVERITY_ERROR,
                                msg, fix))

    return findings
