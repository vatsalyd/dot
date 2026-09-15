# dot

Scans a configurable list of GitHub repos for **open issues that have no
assignee and no linked open pull request**, and posts new matches to
Slack or Discord. Runs manually via `python main.py`.

## 1. How it works

1. **Config** (`config.yaml`) lists repos and filters. Editable without
   touching code.
2. For each repo, the bot queries GitHub's **GraphQL API** for all open
   issues, pulling `assignees`, `labels`, and `timelineItems` (cross-
   referenced PRs) in a single paginated query per repo - much cheaper
   than the REST equivalent (which would need one call per issue to
   check for linked PRs).
3. **Filtering**, in order:
   - Skip if it has any assignee.
   - Skip if any timeline cross-reference points to a PR that is still `OPEN`.
   - Skip if younger than `min_age_hours`.
   - Skip/keep based on `exclude_labels` / `include_labels`.
   - Skip if already notified recently (`state.json`, governed by `renotify_after_days`).
4. Remaining issues are batched per repo and POSTed to your Slack or
   Discord webhook (auto-detected from the URL).
5. `state.json` is updated so the same issue isn't re-announced every run.

## 2. Detecting "no PR" - the important caveat

GitHub does **not** expose a clean "linked PR" field via the API. The
signal used here is `CrossReferencedEvent`: it fires whenever a PR's
title/body/commit message mentions `#<issue-number>` (this is also what
powers the "Development" sidebar and `Closes #123` auto-linking on
github.com). So:

- Catches: PRs that reference the issue via `fixes #123`, `closes #123`,
  or a plain `#123` mention.
- Misses: a PR that solves the issue but never mentions its number.

This is the same limitation every "find unclaimed issues" tool has,
including GitHub's own UI. It's a good proxy, not a guarantee.

## 3. Setup

### Quick Start (Recommended)

```bash
pip install -r requirements.txt
cp .env.example .env                  # set GITHUB_TOKEN and either SLACK_BOT_TOKEN (for per-repo channels) or WEBHOOK_URL
python run.py --dry-run               # auto-loads .env, auto-bootstraps config.yaml, and previews
python run.py                         # real run
```

### Manual Run

```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml   # edit the repo list
export GITHUB_TOKEN=ghp_xxxxxxxx      # classic PAT, no scopes needed for public repos; "repo" scope for private
export SLACK_BOT_TOKEN=xoxb-xxxxxxxx  # optional: automatically creates & posts to #<repo-name> per repo
# OR: export WEBHOOK_URL=https://hooks.slack.com/services/... (single channel)
python main.py --repo pallets/flask --dry-run # ad-hoc single repo test
python main.py --dry-run              # preview without posting or saving state
python main.py                        # real run
python -m unittest discover tests     # run unit test suite
```

**Token scopes:** for public repos, a token with **no scopes** (or fine-
grained token with just "Metadata: read" + "Issues: read" + "Pull
requests: read") is enough. Rate limit for GraphQL is 5,000 points/hour
per token, which is generous for issue-only queries.

## 4. Project layout

| File | Purpose |
|---|---|
| `run.py` | Streamlined launcher with automatic .env loading and config bootstrap |
| `main.py` | Orchestrates scan -> filter -> notify -> save state |
| `github_client.py` | GraphQL queries, pagination, PR cross-reference detection |
| `notifier.py` | Slack/Discord notifications, automatic per-repo channel creation |
| `state.py` | JSON or SQLite dedupe store, atomic writes, auto-migration |
| `config.example.yaml` | Repo list + filters, copy to `config.yaml` |
| `.env.example` | Template for environment variables |
| `tests/` | Unit test suite (filter logic, GraphQL mocks, state, notifier) |

## 5. Suggested improvements (all implemented)

**Reliability / correctness**
- Add a `--repo owner/name` flag to scan a single repo ad-hoc without editing config (implemented).
- Handle GitHub's secondary rate limits more gracefully (exponential backoff with Retry-After and x-ratelimit-reset inspection) (implemented).
- Add a unit test suite (mock GraphQL responses) covering the filter logic in `passes_filters` and `has_open_linked_pr` (implemented).
- Switch `state.json` to SQLite once repo count or issue volume grows (implemented: pass `--state state.db` with automatic migration from `state.json`).
- Retry and exponential backoff on webhook POST requests with Retry-After handling (implemented).

**Automation**
- Scheduled **GitHub Actions workflow** (`.github/workflows/scan.yml`) with cron trigger and state caching (implemented).
- Alternative: a simple `cron` entry on a personal server/Raspberry Pi if you want it fully self-hosted.

**Signal quality**
- Add a "staleness" tier: separately flag issues that are unassigned and have had zero comments (`--uncommented-only`, `--max-comments`) (implemented).
- Cross-check against **draft PRs** too - `--ignore-draft-prs` ensures draft PRs do not count as claimed (implemented).
- Pull in issue **reactions** (thumbs-up count) and sort by `--sort-by [reactions|comments|created|oldest]` (implemented).
- Support **org-wide scanning** (`--org <name>` or `orgs:` list in config) using the `search` GraphQL root and a `is:issue is:open no:assignee` query (implemented).

**Notification quality**
- Group the daily/weekly digest into "New Unassigned Issues" vs "Still Open Reminders" sections instead of one flat list (implemented).
- Add a minimum-priority filter (`--priority-labels-only`) so only priority-labeled issues get pushed, with everything else logged (implemented).
- Include issue age, comment count, and upvotes inline in the Slack/Discord message for quick triage (implemented).

**Ops**
- Emit basic metrics (issues scanned, matched, notified, duration) to stdout in a structured JSON line via `--metrics-json` (implemented).
- Add a `.env.example` and zero-dependency launcher `run.py` that auto-loads `.env` and auto-bootstraps `config.yaml` (implemented).

## 6. Known limitations to keep in mind

- Cross-reference detection can produce false negatives (see §2).
- GraphQL repository pagination fetches issues per repo before filtering; for very large organizations, org-wide search (`--org`) pre-filters on the server side (`is:issue is:open no:assignee`).

