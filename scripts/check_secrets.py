"""Block commits that contain credentials. Installed as .git/hooks/pre-commit by scripts/install_hooks.py.

  .venv\\Scripts\\python.exe scripts\\check_secrets.py            # scan what is staged
  .venv\\Scripts\\python.exe scripts\\check_secrets.py --all      # scan every tracked file

Mark a deliberate exception with a trailing `# pragma: allowlist secret`.
"""
import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from qtrading.secrets import scan_text  # noqa: E402

SKIP_SUFFIXES = {".parquet", ".png", ".jpg", ".pdf", ".zip", ".gz"}


def git(*args) -> str:
    return subprocess.check_output(["git", *args], text=True, errors="replace")


def staged_files() -> list[str]:
    return [f for f in git("diff", "--cached", "--name-only", "--diff-filter=ACM").splitlines() if f]


def content(path: str, staged: bool) -> str:
    if staged:
        return git("show", f":{path}")
    return Path(path).read_text(encoding="utf-8", errors="replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="scan every tracked file instead of the staged changes")
    args = ap.parse_args()

    files = git("ls-files").splitlines() if args.all else staged_files()
    findings = []
    for path in files:
        if Path(path).suffix in SKIP_SUFFIXES:
            continue
        try:
            findings.extend(scan_text(path, content(path, staged=not args.all)))
        except (subprocess.CalledProcessError, OSError, UnicodeDecodeError):
            continue

    if findings:
        print("BLOCKED: possible credentials found\n", file=sys.stderr)
        for f in findings:
            print(f"  {f.path}:{f.line}  {f.reason}", file=sys.stderr)
        print("\nMove the value into .env (git-ignored), or mark the line `# pragma: allowlist secret` "
              "if it is deliberately public.", file=sys.stderr)
        return 1
    print(f"no credentials found in {len(files)} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
