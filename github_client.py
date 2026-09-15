"""
GitHub GraphQL client for fetching open issues and determining whether
they have a linked/open pull request.

Why GraphQL instead of REST:
- One request can fetch issues + assignees + labels + cross-referenced PRs
  together, instead of N+1 REST calls per issue.
- GitHub's "linked PR" relationship isn't exposed as a simple REST field.
  The closest signal is the CrossReferencedEvent timeline item, which fires
  when a PR body/commit mentions "#<issue_number>" (including "closes #123"
  style keywords). We inspect those events to see if any *open* PR
  references the issue.

Caveat (documented, not hidden): this catches PRs that reference the issue
number in their body/commits. It will NOT catch a PR that solves the issue
without ever mentioning it. That's a known limitation of GitHub's own
"Development" sidebar too -- there is no fully reliable API for "is anyone
already working on this."
"""

import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import requests

GRAPHQL_URL = "https://api.github.com/graphql"

ISSUES_QUERY = """
query($owner: String!, $name: String!, $pageSize: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    issues(
      first: $pageSize
      after: $after
      states: OPEN
      orderBy: {field: CREATED_AT, direction: DESC}
    ) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        number
        title
        url
        createdAt
        comments {
          totalCount
        }
        assignees(first: 1) {
          totalCount
        }
        labels(first: 10) {
          nodes {
            name
          }
        }
        timelineItems(itemTypes: [CROSS_REFERENCED_EVENT], first: 20) {
          nodes {
            ... on CrossReferencedEvent {
              source {
                ... on PullRequest {
                  number
                  state
                  isDraft
                  url
                }
              }
            }
          }
        }
      }
    }
  }
}
"""


class GitHubClient:
    def __init__(self, token: str, session: requests.Session | None = None):
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "unassigned-issue-bot",
            }
        )

    @staticmethod
    def _get_retry_wait(resp: requests.Response, default_wait: float) -> float:
        """Inspects Retry-After and x-ratelimit-reset headers to determine backoff."""
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return max(float(retry_after), 1.0)
            except ValueError:
                try:
                    target = parsedate_to_datetime(retry_after)
                    diff = (target - datetime.now(timezone.utc)).total_seconds()
                    return max(diff, 1.0)
                except Exception:
                    pass

        if resp.headers.get("x-ratelimit-remaining") == "0":
            reset_header = resp.headers.get("x-ratelimit-reset")
            if reset_header:
                try:
                    reset_time = float(reset_header)
                    diff = reset_time - time.time()
                    return max(diff, 1.0)
                except ValueError:
                    pass

        return default_wait

    def _post(self, query: str, variables: dict, max_attempts: int = 4) -> dict:
        for attempt in range(max_attempts):
            resp = self.session.post(
                GRAPHQL_URL, json={"query": query, "variables": variables}
            )
            if resp.status_code == 200:
                data = resp.json()
                if "errors" in data:
                    raise RuntimeError(f"GraphQL error: {data['errors']}")
                return data["data"]

            if resp.status_code in (403, 429, 500, 502, 503, 504):
                if attempt == max_attempts - 1:
                    resp.raise_for_status()
                default_backoff = 2 ** attempt * 5
                wait = self._get_retry_wait(resp, default_backoff)
                time.sleep(min(wait, 60.0))
                continue

            resp.raise_for_status()
        resp.raise_for_status()

    def fetch_open_issues(self, owner: str, name: str, page_size: int = 50):
        """Yields raw issue nodes (dicts) for every open issue in the repo."""
        after = None
        while True:
            data = self._post(
                ISSUES_QUERY,
                {"owner": owner, "name": name, "pageSize": page_size, "after": after},
            )
            repo = data.get("repository")
            if repo is None:
                raise RuntimeError(f"Repo not found or inaccessible: {owner}/{name}")

            issues = repo["issues"]
            for node in issues["nodes"]:
                yield node

            if issues["pageInfo"]["hasNextPage"]:
                after = issues["pageInfo"]["endCursor"]
            else:
                break

    @staticmethod
    def has_open_linked_pr(issue_node: dict, ignore_draft_prs: bool = False) -> bool:
        for item in issue_node["timelineItems"]["nodes"]:
            source = item.get("source")
            if source and source.get("state") == "OPEN":
                if ignore_draft_prs and source.get("isDraft"):
                    continue
                return True
        return False

    @staticmethod
    def comment_count(issue_node: dict) -> int:
        return issue_node.get("comments", {}).get("totalCount", 0)

    @staticmethod
    def is_unassigned(issue_node: dict) -> bool:
        return issue_node["assignees"]["totalCount"] == 0
