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
    p.add_argument("--state", default="state.json", help="Path to state JSON file.")
    p.add_argument("--dry-run", action="store_true", help="Print results, don't send webhook or write state.")
    return p.parse_args()


def issue_age_hours(created_at: str) -> float:
    created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - created).total_seconds() / 3600


def passes_filters(issue_node: dict, filters: dict) -> bool:
    if issue_age_hours(issue_node["createdAt"]) < filters.get("min_age_hours", 0):
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
    args = parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    webhook_url = os.environ.get("WEBHOOK_URL")
    if not token:
        sys.exit("ERROR: set GITHUB_TOKEN env var (needs 'repo' scope for private repos, or no scope for public-only).")
    if not webhook_url and not args.dry_run:
        sys.exit("ERROR: set WEBHOOK_URL env var, or pass --dry-run.")

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
                if not GitHubClient.is_unassigned(issue):
                    continue
                if GitHubClient.has_open_linked_pr(issue):
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
                notify(webhook_url, full_name, matches)
        else:
            print("  No new matches.")

    if not args.dry_run:
        save_state(state, args.state)

    print(f"\nDone. {total_matches} total new match(es) across {len(repos)} repo(s).")


if __name__ == "__main__":
    main()
