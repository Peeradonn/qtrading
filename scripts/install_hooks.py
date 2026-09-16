"""Install the repo's git hooks. Run once after cloning:

  .venv\\Scripts\\python.exe scripts\\install_hooks.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = """#!/bin/sh
# Installed by scripts/install_hooks.py — blocks commits containing credentials.
if [ -x "$(git rev-parse --show-toplevel)/.venv/Scripts/python.exe" ]; then
    PY="$(git rev-parse --show-toplevel)/.venv/Scripts/python.exe"
elif [ -x "$(git rev-parse --show-toplevel)/.venv/bin/python" ]; then
    PY="$(git rev-parse --show-toplevel)/.venv/bin/python"
else
    PY=python3
fi
exec "$PY" "$(git rev-parse --show-toplevel)/scripts/check_secrets.py"
"""


def main() -> int:
    hooks = ROOT / ".git" / "hooks"
    if not hooks.is_dir():
        print("no .git/hooks directory — is this a git repo?", file=sys.stderr)
        return 1
    path = hooks / "pre-commit"
    path.write_text(HOOK, encoding="utf-8", newline="\n")
    path.chmod(0o755)
    print(f"installed {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
