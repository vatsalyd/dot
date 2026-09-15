"""
Notification dispatcher supporting:
1. Direct Slack Web API with automatic per-repository channel creation and routing.
2. Incoming webhooks for Slack or Discord.
"""

from datetime import datetime, timezone
import re
import requests

SLACK_API_BASE = "https://slack.com/api"


def format_issue_meta(issue: dict) -> str:
    """Formats inline metadata: age, comments count, and thumbs up count."""
    parts = []
    created_at = issue.get("createdAt")
    if created_at:
        try:
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
            if age_hours < 24:
                parts.append(f"{max(0, int(age_hours))}h old")
            else:
                parts.append(f"{max(0, int(age_hours / 24))}d old")
        except Exception:
            pass

    comments = issue.get("comments", {}).get("totalCount", 0)
    parts.append(f"{comments} comment{'s' if comments != 1 else ''}")

    reactions = issue.get("reactions", {}).get("totalCount", 0)
    if reactions > 0:
        parts.append(f"+{reactions} upvote{'s' if reactions != 1 else ''}")

    return f" ({' | '.join(parts)})" if parts else ""


def sanitize_channel_name(name: str) -> str:
    """
    Converts a repository or custom name into a valid Slack channel name:
    - Lowercase only
    - Letters, numbers, hyphens, and underscores only
    - Max 80 characters
    """
    clean = re.sub(r"[/ \t]+", "-", name.lower())
    clean = re.sub(r"[^a-z0-9_-]", "", clean)
    clean = re.sub(r"-+", "-", clean).strip("-")
    return clean[:80] or "unclaimed-issues"


def _is_discord(webhook_url: str) -> bool:
    return "discord.com/api/webhooks" in webhook_url


def _format_slack(repo_full_name: str, issues: list[dict]) -> dict:
    lines = []
    for i in issues:
        meta = format_issue_meta(i)
        suffix = f" _{meta.strip()}_" if meta else ""
        lines.append(f"*<{i['url']}|#{i['number']}> {i['title']}*{suffix}")
    text = f"*{repo_full_name}* - {len(issues)} unassigned issue(s) with no open PR:\n" + "\n".join(lines)
    return {"text": text}


def _format_discord(repo_full_name: str, issues: list[dict]) -> dict:
    lines = []
    for i in issues:
        meta = format_issue_meta(i)
        suffix = f" *{meta.strip()}*" if meta else ""
        lines.append(f"[#{i['number']}]({i['url']}) {i['title']}{suffix}")
    content = f"**{repo_full_name}** - {len(issues)} unassigned issue(s) with no open PR:\n" + "\n".join(lines)
    return {"content": content}


class SlackClient:
    """Slack Web API client for dynamic per-repository channel management and posting."""

    def __init__(self, bot_token: str, session: requests.Session | None = None):
        self.bot_token = bot_token
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {bot_token}",
                "Content-Type": "application/json; charset=utf-8",
            }
        )
        self._channel_cache: dict[str, str] = {}

    def get_or_create_channel(self, channel_name: str) -> str:
        """Finds or creates a public Slack channel, returning the channel ID."""
        clean_name = sanitize_channel_name(channel_name)
        if clean_name in self._channel_cache:
            return self._channel_cache[clean_name]

        # 1. Search existing channels
        cursor = None
        while True:
            params = {
                "types": "public_channel",
                "exclude_archived": "true",
                "limit": 200,
            }
            if cursor:
                params["cursor"] = cursor
            resp = self.session.get(f"{SLACK_API_BASE}/conversations.list", params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    for ch in data.get("channels", []):
                        self._channel_cache[ch["name"]] = ch["id"]
                        if ch["name"] == clean_name:
                            self._ensure_joined(ch["id"])
                            return ch["id"]
                    cursor = data.get("response_metadata", {}).get("next_cursor")
                    if not cursor:
                        break
                else:
                    break
            else:
                break

        # 2. Channel doesn't exist, create it
        resp = self.session.post(
            f"{SLACK_API_BASE}/conversations.create",
            json={"name": clean_name, "is_private": False},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("ok"):
                channel_id = data["channel"]["id"]
                self._channel_cache[clean_name] = channel_id
                self._ensure_joined(channel_id)
                return channel_id
            if data.get("error") == "name_taken":
                # Fetch ID from public list
                cursor = None
                while True:
                    p = {"types": "public_channel", "limit": 200}
                    if cursor:
                        p["cursor"] = cursor
                    r = self.session.get(f"{SLACK_API_BASE}/conversations.list", params=p, timeout=10)
                    if r.status_code == 200 and r.json().get("ok"):
                        for ch in r.json().get("channels", []):
                            if ch["name"] == clean_name:
                                self._channel_cache[clean_name] = ch["id"]
                                self._ensure_joined(ch["id"])
                                return ch["id"]
                        cursor = r.json().get("response_metadata", {}).get("next_cursor")
                        if not cursor:
                            break
                    else:
                        break
                return clean_name
            raise RuntimeError(f"Failed to create Slack channel #{clean_name}: {data.get('error')}")

        resp.raise_for_status()
        return clean_name

    def _ensure_joined(self, channel_id: str) -> None:
        try:
            self.session.post(
                f"{SLACK_API_BASE}/conversations.join",
                json={"channel": channel_id},
                timeout=10,
            )
        except Exception:
            pass

    def post_issues(self, channel_id: str, repo_full_name: str, issues: list[dict]) -> None:
        """Sends issues to the designated channel in chunks of 20."""
        for i in range(0, len(issues), 20):
            chunk = issues[i : i + 20]
            payload = _format_slack(repo_full_name, chunk)
            resp = self.session.post(
                f"{SLACK_API_BASE}/chat.postMessage",
                json={"channel": channel_id, "text": payload["text"]},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                raise RuntimeError(f"Slack postMessage to #{channel_id} failed: {data.get('error')}")


def notify(
    webhook_url: str | None,
    repo_full_name: str,
    issues: list[dict],
    slack_bot_token: str | None = None,
    channel_override: str | None = None,
) -> None:
    """
    Dispatches notifications:
    - If slack_bot_token is provided, dynamically creates/targets a separate channel per repo.
    - Otherwise falls back to webhook_url (Slack or Discord).
    """
    if not issues:
        return

    # Direct Slack Web API with dynamic per-repo channel creation
    if slack_bot_token:
        client = SlackClient(slack_bot_token)
        target_name = channel_override or repo_full_name.split("/")[-1]
        channel_id = client.get_or_create_channel(target_name)
        client.post_issues(channel_id, repo_full_name, issues)
        return

    if not webhook_url:
        raise ValueError("Either SLACK_BOT_TOKEN or WEBHOOK_URL must be configured to send notifications.")

    # Fallback to single webhook URL
    for i in range(0, len(issues), 20):
        chunk = issues[i : i + 20]
        payload = _format_discord(repo_full_name, chunk) if _is_discord(webhook_url) else _format_slack(repo_full_name, chunk)
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
