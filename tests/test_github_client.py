import unittest
from unittest.mock import MagicMock
import requests

from github_client import GitHubClient


class TestGitHubClient(unittest.TestCase):
    def test_is_unassigned_true_when_zero(self):
        node = {"assignees": {"totalCount": 0}}
        self.assertTrue(GitHubClient.is_unassigned(node))

    def test_is_unassigned_false_when_assigned(self):
        node = {"assignees": {"totalCount": 2}}
        self.assertFalse(GitHubClient.is_unassigned(node))

    def test_has_open_linked_pr_true_when_open(self):
        node = {
            "timelineItems": {
                "nodes": [
                    {
                        "source": {
                            "number": 42,
                            "state": "OPEN",
                            "url": "https://github.com/owner/repo/pull/42",
                        }
                    }
                ]
            }
        }
        self.assertTrue(GitHubClient.has_open_linked_pr(node))

    def test_has_open_linked_pr_false_when_merged_or_closed(self):
        node = {
            "timelineItems": {
                "nodes": [
                    {
                        "source": {
                            "number": 42,
                            "state": "MERGED",
                            "url": "https://github.com/owner/repo/pull/42",
                        }
                    },
                    {
                        "source": {
                            "number": 43,
                            "state": "CLOSED",
                            "url": "https://github.com/owner/repo/pull/43",
                        }
                    },
                ]
            }
        }
        self.assertFalse(GitHubClient.has_open_linked_pr(node))

    def test_has_open_linked_pr_false_when_empty_timeline(self):
        node = {"timelineItems": {"nodes": []}}
        self.assertFalse(GitHubClient.has_open_linked_pr(node))

    def test_has_open_linked_pr_ignores_draft_pr_when_flag_is_set(self):
        node = {
            "timelineItems": {
                "nodes": [
                    {
                        "source": {
                            "number": 42,
                            "state": "OPEN",
                            "isDraft": True,
                            "url": "https://github.com/owner/repo/pull/42",
                        }
                    }
                ]
            }
        }
        # Default behavior: draft PR is treated as open linked PR
        self.assertTrue(GitHubClient.has_open_linked_pr(node, ignore_draft_prs=False))
        # With ignore_draft_prs=True: draft PR is ignored
        self.assertFalse(GitHubClient.has_open_linked_pr(node, ignore_draft_prs=True))

    def test_comment_count(self):
        node = {"comments": {"totalCount": 5}}
        self.assertEqual(GitHubClient.comment_count(node), 5)
        empty_node = {}
        self.assertEqual(GitHubClient.comment_count(empty_node), 0)

    def test_reaction_count(self):
        node = {"reactions": {"totalCount": 12}}
        self.assertEqual(GitHubClient.reaction_count(node), 12)
        empty_node = {}
        self.assertEqual(GitHubClient.reaction_count(empty_node), 0)

    def test_get_retry_wait_parses_seconds(self):
        resp = requests.Response()
        resp.headers["Retry-After"] = "25"
        self.assertEqual(GitHubClient._get_retry_wait(resp, 5.0), 25.0)

    def test_get_retry_wait_falls_back_to_default(self):
        resp = requests.Response()
        self.assertEqual(GitHubClient._get_retry_wait(resp, 10.0), 10.0)

    def test_post_retries_on_rate_limit_and_succeeds(self):
        session = MagicMock()
        resp_429 = requests.Response()
        resp_429.status_code = 429
        resp_429.headers["Retry-After"] = "0.01"

        resp_200 = requests.Response()
        resp_200.status_code = 200
        resp_200._content = b'{"data": {"repository": {"issues": {"nodes": []}}}}'

        session.post.side_effect = [resp_429, resp_200]

        client = GitHubClient(token="mock-token", session=session)
        result = client._post("query", {})
        self.assertIn("repository", result)
        self.assertEqual(session.post.call_count, 2)

    def test_fetch_org_issues_yields_issues(self):
        session = MagicMock()
        resp = requests.Response()
        resp.status_code = 200
        resp._content = b'''{
            "data": {
                "search": {
                    "issueCount": 1,
                    "pageInfo": {"hasNextPage": false, "endCursor": null},
                    "nodes": [
                        {
                            "number": 55,
                            "title": "Org wide issue",
                            "url": "https://github.com/org/repo/issues/55",
                            "createdAt": "2026-01-01T00:00:00Z",
                            "repository": {"name": "repo", "owner": {"login": "org"}}
                        }
                    ]
                }
            }
        }'''
        session.post.return_value = resp

        client = GitHubClient(token="mock-token", session=session)
        issues = list(client.fetch_org_issues("org", page_size=20))
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["number"], 55)
        self.assertEqual(issues[0]["repository"]["name"], "repo")


if __name__ == "__main__":
    unittest.main()
