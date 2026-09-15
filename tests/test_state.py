import os
import unittest
from datetime import datetime, timezone, timedelta

from state import load_state, save_state, should_notify, mark_notified


class TestStateStore(unittest.TestCase):
    def setUp(self):
        self.test_path = "test_state.json"
        if os.path.exists(self.test_path):
            os.remove(self.test_path)

    def tearDown(self):
        if os.path.exists(self.test_path):
            os.remove(self.test_path)
        if os.path.exists(self.test_path + ".tmp"):
            os.remove(self.test_path + ".tmp")

    def test_save_and_load_state(self):
        state = {"pallets/flask#101": {"first_seen": "2026-01-01T00:00:00Z", "last_notified": "2026-01-01T00:00:00Z"}}
        save_state(state, self.test_path)
        loaded = load_state(self.test_path)
        self.assertEqual(loaded, state)

    def test_load_state_non_existent(self):
        loaded = load_state("non_existent_file.json")
        self.assertEqual(loaded, {})

    def test_should_notify_unseen(self):
        state = {}
        self.assertTrue(should_notify(state, "owner/repo#1", renotify_after_days=7))

    def test_should_notify_recently_notified(self):
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        state = {"owner/repo#1": {"first_seen": now_iso, "last_notified": now_iso}}
        self.assertFalse(should_notify(state, "owner/repo#1", renotify_after_days=7))

    def test_should_notify_after_expiration(self):
        past_dt = datetime.now(timezone.utc) - timedelta(days=10)
        past_iso = past_dt.isoformat().replace("+00:00", "Z")
        state = {"owner/repo#1": {"first_seen": past_iso, "last_notified": past_iso}}
        self.assertTrue(should_notify(state, "owner/repo#1", renotify_after_days=7))

    def test_should_notify_zero_days_never_renotifies(self):
        past_dt = datetime.now(timezone.utc) - timedelta(days=100)
        past_iso = past_dt.isoformat().replace("+00:00", "Z")
        state = {"owner/repo#1": {"first_seen": past_iso, "last_notified": past_iso}}
        self.assertFalse(should_notify(state, "owner/repo#1", renotify_after_days=0))

    def test_mark_notified(self):
        state = {}
        mark_notified(state, "owner/repo#1")
        self.assertIn("owner/repo#1", state)
        self.assertIn("first_seen", state["owner/repo#1"])
        self.assertIn("last_notified", state["owner/repo#1"])


if __name__ == "__main__":
    unittest.main()
