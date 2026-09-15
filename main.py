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
import collections
import os
import sys
from datetime import datetime, timezone

import yaml

from github_client import GitHubClient
from notifier import notify, format_issue_meta
from state import load_state, save_state, should_notify, mark_notified, is_known


def parse_args():
    p = argparse.ArgumentParser(description="Find unassigned, unclaimed GitHub issues.")
    p.add_argument("--config", default="config.yaml", help="Path to config YAML file.")
    p.add_argument("--repo", help="Scan a single repository ad-hoc (format: owner/name).")
    p.add_argument("--org", help="Scan an entire organization ad-hoc via search (e.g. anthropics).")
    p.add_argument("--max-age-days", type=int, default=None, help="Ignore issues older than this many days (0 = no limit).")
    p.add_argument("--ignore-draft-prs", action="store_true", help="Do not count draft PRs as claiming an issue.")
    p.add_argument("--uncommented-only", action="store_true", help="Only alert on issues with zero comments.")
    p.add_argument("--max-comments", type=int, default=None, help="Only alert on issues with at most this many comments.")
    p.add_argument("--priority-labels-only", action="store_true", help="Only alert on issues matching priority labels; log others.")
    p.add_argument("--sort-by", choices=["created", "reactions", "comments", "oldest"], default=None, help="Sort matched issues before notifying.")
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


def matches_priority(issue_node: dict, priority_labels: list[str]) -> bool:
    if not priority_labels:
        return True
    issue_labels = {l["name"].lower() for l in issue_node.get("labels", {}).get("nodes", [])}
    target_labels = {l.lower() for l in priority_labels}
    return bool(issue_labels & target_labels)


def sort_issues(issues: list[dict], sort_by: str = "created") -> list[dict]:
    if sort_by == "reactions":
        return sorted(issues, key=lambda x: GitHubClient.reaction_count(x), reverse=True)
    elif sort_by == "comments":
        return sorted(issues, key=lambda x: GitHubClient.comment_count(x))
    elif sort_by == "oldest":
        return sorted(issues, key=lambda x: x.get("createdAt", ""))
    return issues


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
    elif not args.repo and not args.org:
        sys.exit(f"ERROR: config file '{args.config}' not found. Copy config.example.yaml to config.yaml or pass --repo/--org.")

    if args.repo:
        if "/" not in args.repo:
            sys.exit(f"ERROR: invalid --repo format '{args.repo}'. Expected 'owner/name'.")
        owner, name = args.repo.split("/", 1)
        repos = [{"owner": owner.strip(), "name": name.strip()}]
        orgs = []
    elif args.org:
        repos = []
        orgs = [args.org.strip()]
    else:
        repos = config.get("repos", [])
        orgs = config.get("orgs", [])
        if not repos and not orgs:
            sys.exit("ERROR: no repositories or organizations configured in config file.")

    filters = config.get("filters", {})
    if args.max_age_days is not None:
        filters["max_age_days"] = args.max_age_days
    if args.ignore_draft_prs:
        filters["ignore_draft_prs"] = True
    if args.uncommented_only:
        filters["uncommented_only"] = True
    if args.max_comments is not None:
        filters["max_comments"] = args.max_comments
    if args.priority_labels_only:
        filters["priority_labels_only"] = True

    priority_labels_only = filters.get("priority_labels_only", False)
    priority_labels = filters.get(
        "priority_labels",
        ["good-first-issue", "good first issue", "help-wanted", "help wanted"],
    )

    ignore_draft_prs = filters.get("ignore_draft_prs", False)
    max_age_days = filters.get("max_age_days", 0)
    page_size = config.get("page_size", 50)
    renotify_after_days = filters.get("renotify_after_days", 7)

    client = GitHubClient(token)
    state = load_state(args.state)

    sort_by = args.sort_by or config.get("sort_by", "created")

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

                is_reminder = is_known(state, key)
                issue["is_reminder"] = is_reminder

                if priority_labels_only and not matches_priority(issue, priority_labels):
                    print(f"  [LOG ONLY: non-priority] #{issue['number']} {issue['title']}", file=sys.stderr)
                    continue

                matches.append(issue)
                mark_notified(state, key)
        except Exception as e:
            print(f"  Failed to scan {full_name}: {e}", file=sys.stderr)
            continue

        total_matches += len(matches)
        if matches:
            matches = sort_issues(matches, sort_by=sort_by)
            print(f"  Found {len(matches)} matching issue(s).")
            if args.dry_run:
                for m in matches:
                    tag = "[REMINDER]" if m.get("is_reminder") else "[NEW]"
                    print(f"    {tag} #{m['number']} {m['title']}{format_issue_meta(m)} -> {m['url']}")
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

    for org in orgs:
        print(f"Scanning organization {org}...", file=sys.stderr)
        org_repo_matches = collections.defaultdict(list)
        try:
            for issue in client.fetch_org_issues(org, page_size):
                if max_age_days and max_age_days > 0 and (issue_age_hours(issue["createdAt"]) / 24) > max_age_days:
                    break

                if not GitHubClient.is_unassigned(issue):
                    continue
                if GitHubClient.has_open_linked_pr(issue, ignore_draft_prs=ignore_draft_prs):
                    continue
                if not passes_filters(issue, filters):
                    continue

                repo_info = issue.get("repository", {})
                repo_owner = repo_info.get("owner", {}).get("login", org)
                repo_name = repo_info.get("name", "unknown")
                full_name = f"{repo_owner}/{repo_name}"

                key = f"{full_name}#{issue['number']}"
                if not should_notify(state, key, renotify_after_days):
                    continue

                is_reminder = is_known(state, key)
                issue["is_reminder"] = is_reminder

                if priority_labels_only and not matches_priority(issue, priority_labels):
                    print(f"  [LOG ONLY: non-priority] #{issue['number']} {issue['title']}", file=sys.stderr)
                    continue

                org_repo_matches[full_name].append(issue)
                mark_notified(state, key)
        except Exception as e:
            print(f"  Failed to scan organization {org}: {e}", file=sys.stderr)
            continue

        for full_name, matches in org_repo_matches.items():
            total_matches += len(matches)
            matches = sort_issues(matches, sort_by=sort_by)
            print(f"  Found {len(matches)} matching issue(s) for {full_name}.")
            if args.dry_run:
                for m in matches:
                    tag = "[REMINDER]" if m.get("is_reminder") else "[NEW]"
                    print(f"    {tag} #{m['number']} {m['title']}{format_issue_meta(m)} -> {m['url']}")
            else:
                notify(
                    webhook_url=webhook_url,
                    repo_full_name=full_name,
                    issues=matches,
                    slack_bot_token=slack_bot_token,
                )

    if not args.dry_run:
        save_state(state, args.state)

    target_count = len(repos) + len(orgs)
    print(f"\nDone. {total_matches} total new match(es) across {target_count} target(s).")


if __name__ == "__main__":
    main()
