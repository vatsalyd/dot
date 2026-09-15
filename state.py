"""
Tiny JSON-backed state store so re-running the bot doesn't spam Slack with
issues you were already told about.

Format of state.json:
{
  "owner/repo#123": {"first_seen": "2026-09-10T12:00:00Z", "last_notified": "2026-09-10T12:00:00Z"}
}
"""

import json
import os
from datetime import datetime, timezone

DEFAULT_STATE_PATH = "state.json"


def load_state(path: str = DEFAULT_STATE_PATH) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)


def save_state(state: dict, path: str = DEFAULT_STATE_PATH) -> None:
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp_path, path)  # atomic write, avoids corrupt file on crash


def should_notify(state: dict, key: str, renotify_after_days: int) -> bool:
    entry = state.get(key)
    if entry is None:
        return True
    if renotify_after_days <= 0:
        return False
    last = datetime.fromisoformat(entry["last_notified"].replace("Z", "+00:00"))
    age_days = (datetime.now(timezone.utc) - last).total_seconds() / 86400
    return age_days >= renotify_after_days


def mark_notified(state: dict, key: str) -> None:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    entry = state.setdefault(key, {"first_seen": now})
    entry["last_notified"] = now
