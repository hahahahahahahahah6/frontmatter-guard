"""Plugin manifest (.claude-plugin/plugin.json) audit -- the v2 layer.

v1 linted frontmatter vocabulary: does every key you wrote actually do
something? v2 audits the manifest itself: the identity and capability claims
a plugin makes about itself, checked against what is on disk.

Motivation: ``claude plugin validate`` (without ``--strict``) exits 0 on a
broken skill. A green validate is not evidence the plugin works -- and it is
not evidence the plugin is safe either. frontmatter-guard v2 adds the second
layer the official check skips: the manifest dimension.
"""

import difflib
import json
import os
import re

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"

VERDICT_PASS = "pass"
VERDICT_REVIEW = "review"
VERDICT_FAIL = "fail"

# Names that would imply an official/blessed plugin. A community plugin
# shipping one of these (or a lookalike) is either confused or impersonating.
OFFICIAL_NAMES = frozenset({
    "claude",
    "claude-code",
    "claude-plugin",
    "claude-plugins",
    "anthropic",
    "anthropic-plugins",
    "official",
    "official-plugins",
    "plugin-marketplace",
    "plugins",
    "verified",
    "verified-plugins",
})

# Prefixes whose only job is to borrow authority.
SUSPICIOUS_PREFIXES = (
    "official-",
    "official_",
    "anthropic-",
    "anthropic_",
    "claude-official",
    "verified-",
    "verified_",
)

# Fields that establish who stands behind a plugin. A manifest with none of
# these is unauditable -- you cannot even ask the author what a hook does.
PROVENANCE_FIELDS = ("author", "repository", "license", "homepage")

# Capability names the audit can observe on disk.
CAP_SHELL = "shell"
CAP_NETWORK = "network"

# Maps declared permission tokens (manifest "permissions") to capabilities.
PERMISSION_ALIASES = {
    "bash": CAP_SHELL,
    "shell": CAP_SHELL,
    "command": CAP_SHELL,
    "exec": CAP_SHELL,
    "run": CAP_SHELL,
    "script": CAP_SHELL,
    "webfetch": CAP_NETWORK,
    "fetch": CAP_NETWORK,
    "websearch": CAP_NETWORK,
    "curl": CAP_NETWORK,
    "http": CAP_NETWORK,
    "network": CAP_NETWORK,
    "internet": CAP_NETWORK,
    "mcp": CAP_NETWORK,
}

_NETWORK_COMMAND_RE = re.compile(
    r"\b(curl|wget|ssh|scp|ftp|http://|https://|socket)\b", re.IGNORECASE)


def _finding(path, line, rule, severity, message, fix):
    return {
        "file": path,
        "line": line,
        "rule": rule,
        "severity": severity,
        "message": message,
        "fix": fix,
    }


def _normalize_name(name):
    return str(name).strip().lower()


def check_name(manifest, path):
    """Flag official-sounding or typosquatted plugin names."""
    findings = []
    name = manifest.get("name")
    if not name:
        return findings  # missing-required is a v1 rule
    norm = _normalize_name(name)

    if norm in OFFICIAL_NAMES:
        findings.append(_finding(
            path, 1, "impersonating-name", SEVERITY_ERROR,
            "Plugin name '%s' claims an official/blessed identity."
            % name,
            "Rename the plugin to a name that is clearly yours. Shipping "
            "an official-sounding name is impersonation whether or not it "
            "was intentional."))
        return findings

    for prefix in SUSPICIOUS_PREFIXES:
        if norm.startswith(prefix):
            findings.append(_finding(
                path, 1, "impersonating-name", SEVERITY_ERROR,
                "Plugin name '%s' uses the authority-borrowing prefix "
                "'%s'." % (name, prefix.rstrip("-_") or prefix),
                "Drop the prefix and pick a name that does not borrow "
                "authority from Anthropic or from 'official' status."))
            return findings

    # Typosquat: close to an official name but not containing it as a clean
    # component (e.g. "claaude-code" vs the fine "claude-helper").
    for official in OFFICIAL_NAMES:
        if official in norm.replace("-", " ").split():
            continue
        ratio = difflib.SequenceMatcher(None, norm, official).ratio()
        if ratio >= 0.85:
            findings.append(_finding(
                path, 1, "typosquat-name", SEVERITY_WARNING,
                "Plugin name '%s' looks like a typosquat of '%s'."
                % (name, official),
                "If the resemblance is accidental, rename it further away "
                "from '%s'. If it is deliberate, rename it anyway."
                % official))
            break
    return findings


def _discover_hooks(plugin_root):
    """Return (hooks_present, hook_commands) found on disk."""
    commands = []
    present = False

    hooks_json = os.path.join(plugin_root, ".claude-plugin", "hooks.json")
    if os.path.isfile(hooks_json):
        present = True
        try:
            with open(hooks_json, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            commands.extend(_collect_commands(data))
        except (OSError, ValueError):
            pass

    for subdir in ("hooks", "scripts"):
        full = os.path.join(plugin_root, subdir)
        if os.path.isdir(full):
            try:
                entries = [e for e in os.listdir(full)
                           if os.path.isfile(os.path.join(full, e))]
            except OSError:
                entries = []
            if entries:
                present = True
    return present, commands


def _collect_commands(node):
    """Recursively collect string values of 'command' keys."""
    found = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "command" and isinstance(value, str):
                found.append(value)
            else:
                found.extend(_collect_commands(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_collect_commands(item))
    return found


def observed_capabilities(manifest, plugin_root):
    """Capabilities actually observable: hooks/scripts on disk, mcpServers."""
    caps = set()
    hooks_present, commands = _discover_hooks(plugin_root)
    if hooks_present:
        caps.add(CAP_SHELL)
    for command in commands:
        if _NETWORK_COMMAND_RE.search(command):
            caps.add(CAP_NETWORK)
            break
    mcp = manifest.get("mcpServers")
    if mcp:
        caps.add(CAP_NETWORK)
    return caps


def declared_capabilities(manifest):
    """Capabilities the manifest claims via the 'permissions' key."""
    declared = manifest.get("permissions")
    if declared is None:
        return set()
    if isinstance(declared, str):
        declared = [declared]
    if not isinstance(declared, (list, tuple)):
        return set()
    caps = set()
    for token in declared:
        caps.add(PERMISSION_ALIASES.get(str(token).strip().lower(),
                                       str(token).strip().lower()))
    return caps


def check_hooks_declared(manifest, path, plugin_root):
    """Hooks on disk must be declared in the manifest 'hooks' key."""
    findings = []
    hooks_present, _ = _discover_hooks(plugin_root)
    if hooks_present and not manifest.get("hooks"):
        findings.append(_finding(
            path, 1, "undeclared-hooks", SEVERITY_ERROR,
            "Hook scripts exist on disk but the manifest declares no "
            "'hooks'.",
            "Declare every hook in the manifest 'hooks' key (event -> "
            "commands), or remove the hook files. Undeclared hooks run "
            "code the manifest never admits to."))
    return findings


def check_permission_match(manifest, path, plugin_root):
    """Declared permissions must match observable capabilities, both ways."""
    findings = []
    observed = observed_capabilities(manifest, plugin_root)
    declared = declared_capabilities(manifest)

    hidden = observed - declared
    if hidden:
        findings.append(_finding(
            path, 1, "undeclared-capability", SEVERITY_ERROR,
            "Plugin can do %s but declares no matching permission."
            % ", ".join(sorted(hidden)),
            "Add the capability to the manifest 'permissions' list "
            "(e.g. \"permissions\": [\"Bash\"]), or remove the code that "
            "needs it. Hidden capabilities are the classic supply-chain "
            "move."))

    excess = declared - observed
    # 'shell' declared while only network observed (or vice versa) is still
    # worth flagging, but an empty observation set with declarations is the
    # common case: permissions claimed for code that is not even there.
    if excess:
        findings.append(_finding(
            path, 1, "over-declared-permissions", SEVERITY_WARNING,
            "Manifest declares permission(s) %s with no observable "
            "capability to justify them." % ", ".join(sorted(excess)),
            "Remove unused permissions, or ship the hooks/scripts that "
            "need them. Over-broad permissions train users to click "
            "through real warnings."))
    return findings


def check_provenance(manifest, path):
    """A manifest nobody stands behind cannot be audited."""
    findings = []
    missing = [f for f in PROVENANCE_FIELDS if not manifest.get(f)]
    if missing:
        findings.append(_finding(
            path, 1, "missing-provenance", SEVERITY_WARNING,
            "Manifest is missing provenance field(s): %s."
            % ", ".join(missing),
            "Fill in %s so users can judge who ships this plugin and "
            "where it comes from." % ", ".join(missing)))
    return findings


def audit_manifest(manifest, path, plugin_root):
    """Audit one parsed plugin.json manifest.

    Returns (findings, verdict) where verdict is one of
    "pass" / "review" / "fail".
    """
    findings = []
    findings.extend(check_name(manifest, path))
    findings.extend(check_hooks_declared(manifest, path, plugin_root))
    findings.extend(check_permission_match(manifest, path, plugin_root))
    findings.extend(check_provenance(manifest, path))

    verdict = VERDICT_PASS
    for finding in findings:
        if finding["severity"] == SEVERITY_ERROR:
            verdict = VERDICT_FAIL
            break
        verdict = VERDICT_REVIEW
    return findings, verdict


def audit_manifest_file(plugin_json_path):
    """Audit the manifest at plugin_json_path (a .claude-plugin/plugin.json).

    Returns (findings, verdict). Unparseable files yield an error finding
    with verdict "fail".
    """
    try:
        with open(plugin_json_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError) as exc:
        return ([_finding(
            plugin_json_path, 1, "parse-warning", SEVERITY_ERROR,
            "Invalid plugin.json: %s" % exc,
            "Fix the JSON syntax.")], VERDICT_FAIL)
    if not isinstance(manifest, dict):
        return ([_finding(
            plugin_json_path, 1, "bad-type", SEVERITY_ERROR,
            "Top-level JSON value must be an object.",
            "Make the top level a JSON object with plugin keys.")]
                , VERDICT_FAIL)
    # plugin.json lives at <root>/.claude-plugin/plugin.json
    plugin_root = os.path.dirname(os.path.dirname(
        os.path.abspath(plugin_json_path)))
    return audit_manifest(manifest, plugin_json_path, plugin_root)
