import os
import unittest
from unittest.mock import patch, MagicMock

import main


class TestNotificationIsolation(unittest.TestCase):
    def setUp(self):
        self.test_state_file = "test_isolation_state.json"
        self.test_config_file = "test_isolation_cfg.yaml"
        with open(self.test_config_file, "w", encoding="utf-8") as f:
            f.write(
                "repos:\n"
                "  - owner: org\n"
                "    name: repo1\n"
                "  - owner: org\n"
                "    name: repo2\n"
            )
        if os.path.exists(self.test_state_file):
            os.remove(self.test_state_file)

    def tearDown(self):
        for path in (self.test_state_file, self.test_config_file):
            if os.path.exists(path):
                os.remove(path)

    @patch("main.save_state")
    @patch("main.notify")
    @patch("main.GitHubClient")
    def test_notification_failure_does_not_halt_subsequent_scans_or_mark_failed_state(
        self, mock_client_cls, mock_notify, mock_save_state
    ):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client_cls.is_unassigned.return_value = True
        mock_client_cls.has_open_linked_pr.return_value = False
        mock_client_cls.comment_count.return_value = 0
        mock_client_cls.reaction_count.return_value = 0

        # Repo 1 issue
        issue_r1 = {
            "number": 101,
            "title": "Repo 1 Bug",
            "url": "https://github.com/org/repo1/issues/101",
            "createdAt": "2026-09-17T00:00:00Z",
            "comments": {"totalCount": 0},
            "reactions": {"totalCount": 0},
            "assignees": {"totalCount": 0},
            "labels": {"nodes": []},
            "timelineItems": {"nodes": []},
        }
        # Repo 2 issue
        issue_r2 = {
            "number": 202,
            "title": "Repo 2 Bug",
            "url": "https://github.com/org/repo2/issues/202",
            "createdAt": "2026-09-17T00:00:00Z",
            "comments": {"totalCount": 0},
            "reactions": {"totalCount": 0},
            "assignees": {"totalCount": 0},
            "labels": {"nodes": []},
            "timelineItems": {"nodes": []},
        }

        def fetch_issues_side_effect(owner, name, page_size):
            if name == "repo1":
                yield issue_r1
            elif name == "repo2":
                yield issue_r2

        mock_client.fetch_open_issues.side_effect = fetch_issues_side_effect

        # Mock notify to fail on repo1, succeed on repo2
        def notify_side_effect(webhook_url, repo_full_name, issues, **kwargs):
            if repo_full_name == "org/repo1":
                raise RuntimeError("Slack webhook HTTP 500 error")
            return None

        mock_notify.side_effect = notify_side_effect

        # Mock args and env
        mock_args = MagicMock()
        mock_args.config = self.test_config_file
        mock_args.repo = None
        mock_args.org = None
        mock_args.state = self.test_state_file
        mock_args.dry_run = False
        mock_args.max_age_days = None
        mock_args.ignore_draft_prs = False
        mock_args.uncommented_only = False
        mock_args.max_comments = None
        mock_args.priority_labels_only = False
        mock_args.sort_by = None
        mock_args.metrics_json = False

        state_dict = {}

        with patch("main.parse_args", return_value=mock_args), \
             patch("os.environ.get", side_effect=lambda k, default=None: {
                 "GITHUB_TOKEN": "mock_pat",
                 "WEBHOOK_URL": "https://hooks.slack.com/mock",
             }.get(k, default)), \
             patch("main.load_state", return_value=state_dict):
            main.main()

        # Check notify was attempted for both repos
        self.assertEqual(mock_notify.call_count, 2)

        # Check that state ONLY contains org/repo2#202, NOT org/repo1#101
        self.assertNotIn("org/repo1#101", state_dict)
        self.assertIn("org/repo2#202", state_dict)

        # Ensure save_state was called at least once
        self.assertTrue(mock_save_state.called)


if __name__ == "__main__":
    unittest.main()
