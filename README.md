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
cp .env.example .env                  # add your GITHUB_TOKEN and WEBHOOK_URL
python run.py --dry-run               # auto-loads .env, auto-bootstraps config.yaml, and previews
python run.py                         # real run
```

### Manual Run

```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml   # edit the repo list
export GITHUB_TOKEN=ghp_xxxxxxxx      # classic PAT, no scopes needed for public repos; "repo" scope for private
export WEBHOOK_URL=https://hooks.slack.com/services/xxx/yyy/zzz
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
| `notifier.py` | Slack/Discord webhook formatting + chunking |
| `state.py` | JSON or SQLite dedupe store, atomic writes, auto-migration |
| `config.example.yaml` | Repo list + filters, copy to `config.yaml` |
| `.env.example` | Template for environment variables |
| `tests/` | Unit test suite (filter logic, GraphQL mocks, state) |

## 5. Suggested improvements (roughly in priority order)

**Reliability / correctness**
- Add a `--repo owner/name` flag to scan a single repo ad-hoc without editing config (implemented).
- Handle GitHub's secondary rate limits more gracefully (exponential backoff with Retry-After and x-ratelimit-reset inspection) (implemented).
- Add a unit test suite (mock GraphQL responses) covering the filter logic in `passes_filters` and `has_open_linked_pr` (implemented).
- Switch `state.json` to SQLite once repo count or issue volume grows (implemented: pass `--state state.db` with automatic migration from `state.json`).

**Automation**
- Once you're happy with manual runs, move to a scheduled **GitHub Actions workflow** (`schedule: cron`) - free, no server to maintain, and `GITHUB_TOKEN`/`WEBHOOK_URL` live as repo secrets. This is a ~15 line YAML addition, happy to write it when you're ready.
- Alternative: a simple `cron` entry on a personal server/Raspberry Pi if you want it fully self-hosted.

**Signal quality**
- Add a "staleness" tier: separately flag issues that are unassigned **and** have had zero comments in N days (higher-confidence "truly untouched").
- Cross-check against **draft PRs** too - currently a draft PR counts as "open" and will suppress the issue; you may want draft PRs to *not* count as claimed.
- Pull in issue **reactions** (thumbs-up count) so you can sort/prioritize by community interest in the notification.
- Support **org-wide scanning** (`org: anthropics` instead of an explicit repo list) using the `search` GraphQL root and a `is:issue is:open no:assignee` query, so you don't have to maintain the repo list by hand for large orgs.

**Notification quality**
- Group the daily/weekly digest into "new since last run" vs "still open reminder" sections instead of one flat list.
- Add a minimum-priority filter so only `good-first-issue` / `help-wanted` labeled issues get pushed, with everything else just logged.
- Include issue age and comment count inline in the Slack/Discord message for quick triage.

**Ops**
- Emit basic metrics (issues scanned, matched, notified) to stdout in a structured (JSON) line so you can pipe logs somewhere later if this grows beyond manual runs.
- Add a `.env.example` and `python-dotenv` support so you don't have to `export` vars by hand every session.

## 6. Known limitations to keep in mind

- Cross-reference detection can produce false negatives (see §2).
- GraphQL pagination fetches *all* open issues per repo before filtering - fine for repos with hundreds of issues, but very large repos (10k+ open issues) will be slow and costly on rate-limit points. Worth adding a `search` query with `is:issue is:open no:assignee` pre-filter server-side if that becomes an issue.
- No retry/backoff on the webhook POST itself yet - a transient Slack/Discord outage will just error out that repo's notification for the run.
