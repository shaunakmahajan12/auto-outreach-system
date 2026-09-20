"""Offline diagnostic safety checks; these do not prove a live integration."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("inspection", Path(__file__).resolve().parents[1] / "scripts/inspect_tsenta.py")
inspection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inspection)


class InspectionTests(unittest.TestCase):
    def test_only_verified_read_tools_allowed(self):
        for name in ("apply-to-job", "approve-application", "submit-application-review", "reply-to-inbox-message", "invented-tool"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                inspection.validate_read(name, {})
        inspection.validate_read("list-applications", {"filter": "submitted", "page": 1, "limit": 100})
        inspection.validate_read("get-application-status", {"applicationId": "fictional-id", "include": ["resumePdfUrl"]})

    def test_rejects_unexpected_arguments_and_invalid_limits(self):
        for args in ({"limit": 101}, {"limit": True}, {"page": 0}, {"filter": "invented"}, {"submit": True}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                inspection.validate_read("list-applications", args)

    def test_endpoint_origin_rejected_before_network(self):
        for url in ("http://api.autojobs.me/v1", "https://api.autojobs.me.evil.example/", "https://api.autojobs.me@evil.example/", "https://evil.example/"):
            with self.subTest(url=url), self.assertRaises(RuntimeError):
                inspection.request(url)

    def test_redirects_cannot_forward_credentials(self):
        with self.assertRaises(RuntimeError):
            inspection.NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.example/")

    def test_personal_data_file_permissions_and_symlink_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "response.json"
            inspection.private_json(path, {"fictional": True})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            link = Path(directory) / "link.json"
            link.symlink_to(path)
            with self.assertRaises(OSError):
                inspection.private_json(link, {})


if __name__ == "__main__":
    unittest.main()
