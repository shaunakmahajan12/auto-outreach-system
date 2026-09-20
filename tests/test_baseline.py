"""Fictional fixtures only. Live evidence is kept separately in ignored .local/."""
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("baseline", Path(__file__).resolve().parents[1] / "scripts/tsenta_baseline.py")
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)


def fixture(status="COMPLETED"):
    return {"tool": "list-applications", "arguments": {"filter": "all", "page": 1, "limit": 100},
            "response": {"result": {"structuredContent": {"tool": "list-applications", "result": {
                "applications": [{"applicationId": "FICTIONAL-application-1", "status": status,
                                  "companyName": "Fictional Example Company", "jobTitle": "Fictional Role"}],
                "pagination": {"page": 1, "limit": 100, "total": 1, "totalPages": 1}
            }}}}}


class BaselineTests(unittest.TestCase):
    def test_only_completed_is_confirmed(self):
        self.assertEqual(baseline.normalize_status("COMPLETED"), "confirmed_submitted")
        for status in ("READY", "RUNNING", "FAILED", "SKIPPED", "PENDING_SUBMIT_REVIEW", "submitted", "APPLIED", "new_unknown_status"):
            self.assertNotEqual(baseline.normalize_status(status), "confirmed_submitted")

    def test_incomplete_history_rejected(self):
        page = fixture()
        page["response"]["result"]["structuredContent"]["result"]["pagination"].update(total=101, totalPages=2)
        with self.assertRaises(ValueError):
            baseline.validate_snapshot([page])

    def test_duplicate_source_ids_rejected(self):
        page = fixture()
        result = page["response"]["result"]["structuredContent"]["result"]
        result["applications"] *= 2
        result["pagination"]["total"] = 2
        with self.assertRaises(ValueError):
            baseline.validate_snapshot([page])

    def test_filtered_and_error_responses_rejected(self):
        page = fixture()
        page["arguments"]["filter"] = "submitted"
        with self.assertRaises(ValueError):
            baseline.validate_snapshot([page])
        page = fixture()
        page["response"]["result"]["isError"] = True
        with self.assertRaises(ValueError):
            baseline.validate_snapshot([page])

    def test_baseline_idempotent_and_never_starts_research(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "test.sqlite"
            for _ in range(2):
                self.assertEqual(baseline.save_baseline([fixture()], database), 1)
            with sqlite3.connect(str(database)) as conn:
                self.assertEqual(conn.execute("SELECT count(*) FROM applications").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT historical,confirmed_at_baseline,research_state,submitted_at FROM applications").fetchone(), (1, 1, "historical_no_outreach", None))
            with self.assertRaises(ValueError):
                baseline.save_baseline([fixture("FAILED")], database)
            with sqlite3.connect(str(database)) as conn:
                self.assertEqual(conn.execute("SELECT source_status FROM applications").fetchone()[0], "COMPLETED")


if __name__ == "__main__":
    unittest.main()
