import os
import unittest
from datetime import datetime, timezone, timedelta

from state import load_state, save_state, should_notify, mark_notified, is_known


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

    def test_is_known_dict(self):
        state = {}
        self.assertFalse(is_known(state, "owner/repo#1"))
        mark_notified(state, "owner/repo#1")
        self.assertTrue(is_known(state, "owner/repo#1"))


class TestSQLiteStateStore(unittest.TestCase):
    def setUp(self):
        self.db_path = "test_state.db"
        self.json_path = "test_migrate.json"
        self.stores = []
        self._cleanup()

    def _cleanup(self):
        for s in getattr(self, "stores", []):
            try:
                s.close()
            except Exception:
                pass
        self.stores = []
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass
        if os.path.exists(self.json_path):
            try:
                os.remove(self.json_path)
            except Exception:
                pass

    def tearDown(self):
        self._cleanup()

    def test_sqlite_mark_and_retrieve(self):
        store = load_state(self.db_path)
        self.stores.append(store)
        self.assertTrue(should_notify(store, "pallets/flask#1", 7))
        mark_notified(store, "pallets/flask#1")
        save_state(store, self.db_path)

        # Reopen
        store2 = load_state(self.db_path)
        self.stores.append(store2)
        self.assertFalse(should_notify(store2, "pallets/flask#1", 7))
        entry = store2.get("pallets/flask#1")
        self.assertIsNotNone(entry)
        self.assertIn("last_notified", entry)

    def test_sqlite_migration_from_json(self):
        json_data = {
            "org/repo#10": {"first_seen": "2026-01-01T00:00:00Z", "last_notified": "2026-01-01T00:00:00Z"},
            "org/repo#20": {"first_seen": "2026-01-02T00:00:00Z", "last_notified": "2026-01-02T00:00:00Z"},
        }
        with open(self.json_path, "w", encoding="utf-8") as f:
            import json
            json.dump(json_data, f)

        store = load_state(self.db_path)
        self.stores.append(store)
        migrated = store.migrate_from_json(self.json_path)
        self.assertEqual(migrated, 2)
        self.assertEqual(store.count(), 2)
        entry = store.get("org/repo#10")
        self.assertEqual(entry["first_seen"], "2026-01-01T00:00:00Z")

    def test_is_known_sqlite(self):
        store = load_state(self.db_path)
        self.stores.append(store)
        self.assertFalse(is_known(store, "test/repo#1"))
        store.mark_notified("test/repo#1")
        self.assertTrue(is_known(store, "test/repo#1"))


if __name__ == "__main__":
    unittest.main()
