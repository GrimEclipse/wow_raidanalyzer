import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from analyzer_core import recruitment_store


class RecruitmentStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(recruitment_store, "DB_PATH", Path(self.temp_dir.name) / "recruitment.db")
        self.db_patch.start()
        self.user = {"id": 7, "username": "Kirin", "isAdmin": False}

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_save_sort_and_summary(self):
        document = recruitment_store.save_choice(self.user, {
            "playerName": "麒麟",
            "primarySpecId": 105,
            "secondarySpecIds": [102, 104],
            "notes": "必要时可以切坦",
        })
        self.assertEqual(document["summary"]["roleCounts"]["healer"], 1)
        self.assertEqual(document["summary"]["compositionCounts"]["ranged"], 1)
        self.assertEqual(document["entries"][0]["playerName"], "麒麟")
        self.assertNotIn("druid", document["summary"]["missingClassKeys"])

        tank_user = {"id": 8, "username": "Tank", "isAdmin": False}
        document = recruitment_store.save_choice(tank_user, {
            "primarySpecId": 73,
            "secondarySpecIds": [],
        })
        self.assertEqual([entry["primaryRole"] for entry in document["entries"]], ["tank", "healer"])
        self.assertEqual(document["summary"]["compositionCounts"], {"tank": 1, "melee": 0, "ranged": 1})

    def test_rejects_duplicate_and_unknown_specs(self):
        with self.assertRaisesRegex(ValueError, "不能重复"):
            recruitment_store.save_choice(self.user, {
                "primarySpecId": 62,
                "secondarySpecIds": [62],
            })
        with self.assertRaisesRegex(ValueError, "不存在"):
            recruitment_store.save_choice(self.user, {
                "primarySpecId": 999999,
                "secondarySpecIds": [],
            })

    def test_delete_only_removes_current_user(self):
        recruitment_store.save_choice(self.user, {"primarySpecId": 62})
        other = {"id": 8, "username": "Other", "isAdmin": False}
        recruitment_store.save_choice(other, {"primarySpecId": 73})
        document = recruitment_store.delete_choice(self.user)
        self.assertEqual([entry["userId"] for entry in document["entries"]], [8])


if __name__ == "__main__":
    unittest.main()
