"""Allow ``python -m agentpulse``."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
