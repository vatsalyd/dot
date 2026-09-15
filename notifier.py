"""
Sends a batched notification to Slack or Discord via incoming webhook.
Auto-detects which format to use from the webhook URL.
"""

import requests


def _is_discord(webhook_url: str) -> bool:
    return "discord.com/api/webhooks" in webhook_url


def _format_slack(repo_full_name: str, issues: list[dict]) -> dict:
    lines = [f"*<{i['url']}|#{i['number']}> {i['title']}*" for i in issues]
    text = f"*{repo_full_name}* - {len(issues)} unassigned issue(s) with no open PR:\n" + "\n".join(lines)
    return {"text": text}


def _format_discord(repo_full_name: str, issues: list[dict]) -> dict:
    lines = [f"[#{i['number']}]({i['url']}) {i['title']}" for i in issues]
    content = f"**{repo_full_name}** - {len(issues)} unassigned issue(s) with no open PR:\n" + "\n".join(lines)
    return {"content": content}


def notify(webhook_url: str, repo_full_name: str, issues: list[dict]) -> None:
    if not issues:
        return
    payload = _format_discord(repo_full_name, issues) if _is_discord(webhook_url) else _format_slack(repo_full_name, issues)

    # Slack/Discord messages have a length cap; chunk into batches of 20 issues.
    for i in range(0, len(issues), 20):
        chunk = issues[i : i + 20]
        payload = _format_discord(repo_full_name, chunk) if _is_discord(webhook_url) else _format_slack(repo_full_name, chunk)
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
