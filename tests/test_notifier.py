import unittest
from unittest.mock import MagicMock
import requests

from notifier import sanitize_channel_name, SlackClient, notify, _format_slack, _format_discord


class TestNotifier(unittest.TestCase):
    def test_sanitize_channel_name(self):
        self.assertEqual(sanitize_channel_name("mlflow"), "mlflow")
        self.assertEqual(sanitize_channel_name("kubeflow/pipelines"), "kubeflow-pipelines")
        self.assertEqual(sanitize_channel_name("My Project_123!"), "my-project_123")
        self.assertEqual(sanitize_channel_name(""), "unclaimed-issues")
        self.assertEqual(sanitize_channel_name("a" * 100), "a" * 80)

    def test_format_slack(self):
        issues = [{"title": "Bug in API", "url": "https://github.com/org/repo/issues/1", "number": 1}]
        payload = _format_slack("org/repo", issues)
        self.assertIn("*<https://github.com/org/repo/issues/1|#1> Bug in API*", payload["text"])

    def test_slack_client_finds_existing_channel(self):
        session = MagicMock()
        resp_list = requests.Response()
        resp_list.status_code = 200
        resp_list._content = b'{"ok": true, "channels": [{"name": "mlflow", "id": "C12345"}]}'
        session.get.return_value = resp_list

        client = SlackClient("xoxb-mock-token", session=session)
        ch_id = client.get_or_create_channel("mlflow")
        self.assertEqual(ch_id, "C12345")
        # Should not call conversations.create
        self.assertFalse(any("/conversations.create" in str(c) for c in session.post.call_args_list))

    def test_slack_client_creates_new_channel(self):
        session = MagicMock()
        resp_list = requests.Response()
        resp_list.status_code = 200
        resp_list._content = b'{"ok": true, "channels": []}'
        session.get.return_value = resp_list

        resp_create = requests.Response()
        resp_create.status_code = 200
        resp_create._content = b'{"ok": true, "channel": {"id": "C99999"}}'
        session.post.return_value = resp_create

        client = SlackClient("xoxb-mock-token", session=session)
        ch_id = client.get_or_create_channel("deepchem")
        self.assertEqual(ch_id, "C99999")

    def test_notify_dispatches_to_slack_bot_token(self):
        session = MagicMock()
        resp_list = requests.Response()
        resp_list.status_code = 200
        resp_list._content = b'{"ok": true, "channels": [{"name": "deepchem", "id": "C_DEEP"}]}'
        session.get.return_value = resp_list

        resp_post = requests.Response()
        resp_post.status_code = 200
        resp_post._content = b'{"ok": true}'
        session.post.return_value = resp_post

        # Mock SlackClient inside notify
        with unittest.mock.patch("notifier.requests.Session", return_value=session):
            issues = [{"title": "Fix", "url": "https://github.com/deepchem/deepchem/issues/10", "number": 10}]
            notify(
                webhook_url=None,
                repo_full_name="deepchem/deepchem",
                issues=issues,
                slack_bot_token="xoxb-mock",
            )


if __name__ == "__main__":
    unittest.main()
