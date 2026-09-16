"""Credential scanner used by the pre-commit hook.

The competition repo is published for judging, so a credential that reaches a commit is public. This scans
content for the shapes of the credentials this project actually handles, and allows deliberate exceptions
(short test fixtures, and anything marked `# pragma: allowlist secret` — e.g. the API docs' published vector).
"""
import re
from dataclasses import dataclass

ALLOWLIST_PRAGMA = "pragma: allowlist secret"

# Placeholder values that appear in .env.example and in code that reads from the environment.
PLACEHOLDER = re.compile(r"^(your[-_]|<|\$|os\.environ|getenv|\"\"|''|$)", re.I)

PATTERNS = [
    ("Discord webhook URL", re.compile(r"https://(?:discord|discordapp)\.com/api/webhooks/\d{10,}/[\w-]{20,}")),
    ("Slack webhook URL", re.compile(r"https://hooks\.slack\.com/services/T\w+/B\w+/\w{20,}")),
    ("Telegram bot token", re.compile(r"\b\d{8,12}:AA[\w-]{30,}")),
    ("healthchecks.io ping URL", re.compile(r"https://hc-ping\.com/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
                                            r"[0-9a-f]{4}-[0-9a-f]{12}")),
    ("AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
]

# KEY=value or key = "value" where the name smells like a credential and the value is long and unquoted-random.
ASSIGNMENT = re.compile(r"""(?ix)
    \b(?P<name>[\w.]*(?:secret|api[_-]?key|token|passwd|password)[\w.]*)\s*[:=]\s*
    (?P<quote>["']?)(?P<value>[A-Za-z0-9+/_=-]{28,})(?P=quote)
""")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    reason: str


def scan_text(path: str, text: str) -> list[Finding]:
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        if ALLOWLIST_PRAGMA in line:
            continue
        for reason, pattern in PATTERNS:
            if pattern.search(line):
                found.append(Finding(path, number, reason))
                break
        else:
            m = ASSIGNMENT.search(line)
            if m and not PLACEHOLDER.match(m.group("value")):
                found.append(Finding(path, number, "assignment to a secret-looking name"))
    return found
