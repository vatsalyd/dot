import unittest
from main import normalize_repo_entry, passes_filters


class TestConfigResilience(unittest.TestCase):
    def test_normalize_repo_entry_dict(self):
        entry = {"owner": "pallets", "name": "flask", "channel": "#flask-issues"}
        result = normalize_repo_entry(entry)
        self.assertEqual(result, ("pallets", "flask", "#flask-issues"))

    def test_normalize_repo_entry_string(self):
        entry = "pallets/flask"
        result = normalize_repo_entry(entry)
        self.assertEqual(result, ("pallets", "flask", None))

    def test_normalize_repo_entry_invalid_string(self):
        self.assertIsNone(normalize_repo_entry("invalid-format"))
        self.assertIsNone(normalize_repo_entry("/onlyname"))
        self.assertIsNone(normalize_repo_entry("onlyowner/"))

    def test_normalize_repo_entry_invalid_dict(self):
        self.assertIsNone(normalize_repo_entry({"owner": "missing_name"}))
        self.assertIsNone(normalize_repo_entry({"name": "missing_owner"}))
        self.assertIsNone(normalize_repo_entry({}))

    def test_normalize_repo_entry_non_dict_or_string(self):
        self.assertIsNone(normalize_repo_entry(None))
        self.assertIsNone(normalize_repo_entry(123))
        self.assertIsNone(normalize_repo_entry([]))

    def test_passes_filters_with_none_or_empty_filters(self):
        issue_node = {
            "createdAt": "2026-09-17T00:00:00Z",
            "comments": {"totalCount": 0},
            "labels": {"nodes": [{"name": "bug"}]},
        }
        # None exclude_labels and include_labels should not raise TypeError
        filters = {
            "exclude_labels": None,
            "include_labels": None,
            "min_age_hours": None,
            "max_age_days": None,
        }
        self.assertTrue(passes_filters(issue_node, filters))

    def test_passes_filters_empty_dict(self):
        issue_node = {
            "createdAt": "2026-09-17T00:00:00Z",
            "comments": {"totalCount": 0},
            "labels": {"nodes": []},
        }
        self.assertTrue(passes_filters(issue_node, {}))


if __name__ == "__main__":
    unittest.main()
