"""Allow `python -m frontmatter_guard`."""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
