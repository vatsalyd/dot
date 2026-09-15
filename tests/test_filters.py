import unittest
from datetime import datetime, timezone, timedelta

from main import passes_filters, issue_age_hours


class TestFilterLogic(unittest.TestCase):
    def _create_issue(self, hours_ago=48, labels=None):
        created_dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        created_str = created_dt.isoformat().replace("+00:00", "Z")
        labels_nodes = [{"name": l} for l in (labels or [])]
        return {
            "number": 101,
            "title": "Test Issue",
            "url": "https://github.com/owner/repo/issues/101",
            "createdAt": created_str,
            "labels": {"nodes": labels_nodes},
        }

    def test_issue_age_hours(self):
        issue = self._create_issue(hours_ago=25)
        age = issue_age_hours(issue["createdAt"])
        self.assertAlmostEqual(age, 25.0, delta=0.2)

    def test_min_age_filter_skips_young_issue(self):
        issue = self._create_issue(hours_ago=5)
        filters = {"min_age_hours": 24}
        self.assertFalse(passes_filters(issue, filters))

    def test_min_age_filter_passes_old_issue(self):
        issue = self._create_issue(hours_ago=30)
        filters = {"min_age_hours": 24}
        self.assertTrue(passes_filters(issue, filters))

    def test_exclude_labels_case_insensitive(self):
        issue = self._create_issue(hours_ago=48, labels=["Needs-Triage", "Bug"])
        filters = {"exclude_labels": ["needs-triage", "wontfix"]}
        self.assertFalse(passes_filters(issue, filters))

    def test_exclude_labels_no_match_passes(self):
        issue = self._create_issue(hours_ago=48, labels=["enhancement", "good-first-issue"])
        filters = {"exclude_labels": ["blocked", "wontfix"]}
        self.assertTrue(passes_filters(issue, filters))

    def test_include_labels_matching_passes(self):
        issue = self._create_issue(hours_ago=48, labels=["Good-First-Issue", "Python"])
        filters = {"include_labels": ["good-first-issue"]}
        self.assertTrue(passes_filters(issue, filters))

    def test_include_labels_non_matching_fails(self):
        issue = self._create_issue(hours_ago=48, labels=["bug"])
        filters = {"include_labels": ["help-wanted", "good-first-issue"]}
        self.assertFalse(passes_filters(issue, filters))

    def test_include_labels_empty_allows_all(self):
        issue = self._create_issue(hours_ago=48, labels=["anything"])
        filters = {"include_labels": []}
        self.assertTrue(passes_filters(issue, filters))


if __name__ == "__main__":
    unittest.main()
