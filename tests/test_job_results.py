import tempfile
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import server


class PersistedJobResultTests(unittest.TestCase):
    def test_result_survives_in_memory_job_table_reset_for_owner(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = root / "7" / "abcdef123456.json"
            result.parent.mkdir(parents=True)
            result.write_text('{"code":200}', encoding="utf-8")
            with patch.object(server, "JOB_DIR", root):
                self.assertEqual(
                    server.stored_job_result(
                        "abcdef123456", {"id": 7, "isAdmin": False}
                    ),
                    result,
                )
                self.assertIsNone(
                    server.stored_job_result(
                        "abcdef123456", {"id": 8, "isAdmin": False}
                    )
                )

    def test_download_url_is_explicit_and_job_id_is_validated(self):
        self.assertEqual(
            server.job_result_url("abcdef123456", download=True),
            "/api/jobs/abcdef123456/result?download=1",
        )
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            server, "JOB_DIR", Path(temp_dir)
        ):
            self.assertIsNone(
                server.stored_job_result("../escape", {"id": 1, "isAdmin": True})
            )

    def test_json_storage_prunes_expired_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old = root / "old.json"
            fresh = root / "fresh.json"
            old.write_text("{}", encoding="utf-8")
            fresh.write_text("{}", encoding="utf-8")
            os.utime(old, (100, 100))
            result = server.prune_json_storage(root, max_age_seconds=60, max_bytes=1000, now=200)
            self.assertFalse(old.exists())
            self.assertTrue(fresh.exists())
            self.assertEqual(result["removed"], 1)


if __name__ == "__main__":
    unittest.main()
