import unittest
from datetime import datetime, timezone, timedelta

from main import passes_filters, issue_age_hours, sort_issues, matches_priority


class TestFilterLogic(unittest.TestCase):
    def _create_issue(self, hours_ago=48, labels=None, comments=0):
        created_dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        created_str = created_dt.isoformat().replace("+00:00", "Z")
        labels_nodes = [{"name": l} for l in (labels or [])]
        return {
            "number": 101,
            "title": "Test Issue",
            "url": "https://github.com/owner/repo/issues/101",
            "createdAt": created_str,
            "labels": {"nodes": labels_nodes},
            "comments": {"totalCount": comments},
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

    def test_max_age_filter_skips_very_old_issue(self):
        # 100 days old (2400 hours)
        issue = self._create_issue(hours_ago=2400)
        filters = {"max_age_days": 60}
        self.assertFalse(passes_filters(issue, filters))

    def test_max_age_filter_passes_recent_issue(self):
        # 10 days old (240 hours)
        issue = self._create_issue(hours_ago=240)
        filters = {"max_age_days": 60}
        self.assertTrue(passes_filters(issue, filters))

    def test_uncommented_only_filter(self):
        uncommented = self._create_issue(hours_ago=48, comments=0)
        commented = self._create_issue(hours_ago=48, comments=2)
        filters = {"uncommented_only": True}
        self.assertTrue(passes_filters(uncommented, filters))
        self.assertFalse(passes_filters(commented, filters))

    def test_max_comments_filter(self):
        low_comments = self._create_issue(hours_ago=48, comments=2)
        high_comments = self._create_issue(hours_ago=48, comments=5)
        filters = {"max_comments": 2}
        self.assertTrue(passes_filters(low_comments, filters))
        self.assertFalse(passes_filters(high_comments, filters))

    def test_sort_issues_by_reactions(self):
        i1 = {"number": 1, "createdAt": "2026-01-01T00:00:00Z", "reactions": {"totalCount": 2}}
        i2 = {"number": 2, "createdAt": "2026-01-02T00:00:00Z", "reactions": {"totalCount": 10}}
        sorted_list = sort_issues([i1, i2], sort_by="reactions")
        self.assertEqual([x["number"] for x in sorted_list], [2, 1])

    def test_sort_issues_by_comments(self):
        i1 = {"number": 1, "createdAt": "2026-01-01T00:00:00Z", "comments": {"totalCount": 8}}
        i2 = {"number": 2, "createdAt": "2026-01-02T00:00:00Z", "comments": {"totalCount": 1}}
        sorted_list = sort_issues([i1, i2], sort_by="comments")
        self.assertEqual([x["number"] for x in sorted_list], [2, 1])

    def test_matches_priority(self):
        issue_p = {"labels": {"nodes": [{"name": "Good First Issue"}]}}
        issue_np = {"labels": {"nodes": [{"name": "Documentation"}]}}
        priority_labels = ["good-first-issue", "good first issue", "help-wanted"]
        self.assertTrue(matches_priority(issue_p, priority_labels))
        self.assertFalse(matches_priority(issue_np, priority_labels))
        self.assertTrue(matches_priority(issue_np, []))


if __name__ == "__main__":
    unittest.main()
