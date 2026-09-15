#!/usr/bin/env python3
"""
Scans a configurable list of GitHub repos for open issues that have:
  - no assignee, AND
  - no open pull request referencing them

and posts new/re-eligible matches to Slack or Discord.

Usage:
    export GITHUB_TOKEN=ghp_xxx
    export WEBHOOK_URL=https://hooks.slack.com/services/xxx
    python main.py --config config.yaml
"""

import argparse
import os
import sys
from datetime import datetime, timezone

import yaml

from github_client import GitHubClient
from notifier import notify
from state import load_state, save_state, should_notify, mark_notified


def parse_args():
    p = argparse.ArgumentParser(description="Find unassigned, unclaimed GitHub issues.")
    p.add_argument("--config", default="config.yaml", help="Path to config YAML file.")
    p.add_argument("--repo", help="Scan a single repository ad-hoc (format: owner/name).")
    p.add_argument("--max-age-days", type=int, default=None, help="Ignore issues older than this many days (0 = no limit).")
    p.add_argument("--ignore-draft-prs", action="store_true", help="Do not count draft PRs as claiming an issue.")
    p.add_argument("--uncommented-only", action="store_true", help="Only alert on issues with zero comments.")
    p.add_argument("--max-comments", type=int, default=None, help="Only alert on issues with at most this many comments.")
    p.add_argument("--state", default="state.json", help="Path to state JSON file.")
    p.add_argument("--dry-run", action="store_true", help="Print results, don't send webhook or write state.")
    return p.parse_args()


def issue_age_hours(created_at: str) -> float:
    created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - created).total_seconds() / 3600


def passes_filters(issue_node: dict, filters: dict) -> bool:
    age_hours = issue_age_hours(issue_node["createdAt"])
    if age_hours < filters.get("min_age_hours", 0):
        return False

    max_age_days = filters.get("max_age_days", 0)
    if max_age_days and max_age_days > 0 and (age_hours / 24) > max_age_days:
        return False

    # Staleness tier: comment count filtering
    comments = GitHubClient.comment_count(issue_node)
    if filters.get("uncommented_only") and comments > 0:
        return False
    if filters.get("max_comments") is not None and comments > filters["max_comments"]:
        return False

    labels = {l["name"].lower() for l in issue_node["labels"]["nodes"]}
    exclude = {l.lower() for l in filters.get("exclude_labels", [])}
    if labels & exclude:
        return False

    include = {l.lower() for l in filters.get("include_labels", [])}
    if include and not (labels & include):
        return False

    return True


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    args = parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    webhook_url = os.environ.get("WEBHOOK_URL")
    slack_bot_token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        sys.exit("ERROR: set GITHUB_TOKEN env var (needs 'repo' scope for private repos, or no scope for public-only).")
    if not webhook_url and not slack_bot_token and not args.dry_run:
        sys.exit("ERROR: set either SLACK_BOT_TOKEN (to auto-create per-repo channels) or WEBHOOK_URL env var, or pass --dry-run.")

    config = {}
    if os.path.exists(args.config):
        with open(args.config) as f:
            config = yaml.safe_load(f) or {}
    elif not args.repo:
        sys.exit(f"ERROR: config file '{args.config}' not found. Copy config.example.yaml to config.yaml or pass --repo owner/name.")

    if args.repo:
        if "/" not in args.repo:
            sys.exit(f"ERROR: invalid --repo format '{args.repo}'. Expected 'owner/name'.")
        owner, name = args.repo.split("/", 1)
        repos = [{"owner": owner.strip(), "name": name.strip()}]
    else:
        repos = config.get("repos", [])
        if not repos:
            sys.exit("ERROR: no repositories configured in config file.")

    filters = config.get("filters", {})
    if args.max_age_days is not None:
        filters["max_age_days"] = args.max_age_days
    if args.ignore_draft_prs:
        filters["ignore_draft_prs"] = True
    if args.uncommented_only:
        filters["uncommented_only"] = True
    if args.max_comments is not None:
        filters["max_comments"] = args.max_comments

    ignore_draft_prs = filters.get("ignore_draft_prs", False)
    max_age_days = filters.get("max_age_days", 0)
    page_size = config.get("page_size", 50)
    renotify_after_days = filters.get("renotify_after_days", 7)

    client = GitHubClient(token)
    state = load_state(args.state)

    total_matches = 0
    for repo in repos:
        owner, name = repo["owner"], repo["name"]
        full_name = f"{owner}/{name}"
        print(f"Scanning {full_name}...", file=sys.stderr)

        matches = []
        try:
            for issue in client.fetch_open_issues(owner, name, page_size):
                # Early termination: GitHub returns issues ordered by CREATED_AT DESC (newest first).
                # Once an issue exceeds max_age_days, all subsequent issues will also exceed it.
                if max_age_days and max_age_days > 0 and (issue_age_hours(issue["createdAt"]) / 24) > max_age_days:
                    break

                if not GitHubClient.is_unassigned(issue):
                    continue
                if GitHubClient.has_open_linked_pr(issue, ignore_draft_prs=ignore_draft_prs):
                    continue
                if not passes_filters(issue, filters):
                    continue

                key = f"{full_name}#{issue['number']}"
                if not should_notify(state, key, renotify_after_days):
                    continue

                matches.append(issue)
                mark_notified(state, key)
        except Exception as e:
            print(f"  Failed to scan {full_name}: {e}", file=sys.stderr)
            continue

        total_matches += len(matches)
        if matches:
            print(f"  Found {len(matches)} matching issue(s).")
            if args.dry_run:
                for m in matches:
                    print(f"    #{m['number']} {m['title']} -> {m['url']}")
            else:
                notify(
                    webhook_url=webhook_url,
                    repo_full_name=full_name,
                    issues=matches,
                    slack_bot_token=slack_bot_token,
                    channel_override=repo.get("channel"),
                )
        else:
            print("  No new matches.")

    if not args.dry_run:
        save_state(state, args.state)

    print(f"\nDone. {total_matches} total new match(es) across {len(repos)} repo(s).")


if __name__ == "__main__":
    main()
