"""Load KEY=VALUE lines from the project's .env file into the environment.

No extra package needed. Values already set in the shell win, so
`$env:ANTHROPIC_API_KEY = "..."` still works. .env is git-ignored: never commit it.
"""
from __future__ import annotations

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_env(path: Path = ENV_FILE) -> None:
    if not path.exists() or os.getenv("CAREER_NO_DOTENV") == "1":   # tests switch it off
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and "your-key-here" not in value:
            os.environ.setdefault(key, value)
