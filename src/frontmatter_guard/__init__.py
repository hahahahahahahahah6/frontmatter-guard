"""frontmatter-guard: semantic linter for Claude Code skill/plugin frontmatter."""

__version__ = "0.2.0"

from .schema import lint_frontmatter  # noqa: F401
from .manifest import audit_manifest, audit_manifest_file  # noqa: F401
