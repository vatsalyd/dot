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

    def _post(self, query: str, variables: dict) -> dict:
        for attempt in range(3):
            resp = self.session.post(
                GRAPHQL_URL, json={"query": query, "variables": variables}
            )
            if resp.status_code == 200:
                data = resp.json()
                if "errors" in data:
                    raise RuntimeError(f"GraphQL error: {data['errors']}")
                return data["data"]
            if resp.status_code in (502, 503) or resp.status_code == 403:
                # 403 can mean secondary rate limit -- back off and retry.
                wait = 2 ** attempt * 5
                time.sleep(wait)
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
    def has_open_linked_pr(issue_node: dict) -> bool:
        for item in issue_node["timelineItems"]["nodes"]:
            source = item.get("source")
            if source and source.get("state") == "OPEN":
                return True
        return False

    @staticmethod
    def is_unassigned(issue_node: dict) -> bool:
        return issue_node["assignees"]["totalCount"] == 0
