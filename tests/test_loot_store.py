import tempfile
import unittest
from pathlib import Path

from analyzer_core import loot_store


class LootStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db = loot_store.DB_PATH
        loot_store.DB_PATH = Path(self.temp_dir.name) / "loot.db"
        loot_store.save_setup({
            "roster": [
                {"id": "tank", "name": "坦克", "classKey": "warrior", "className": "战士", "armorType": "plate", "active": True},
                {"id": "mage", "name": "法师", "classKey": "mage", "className": "法师", "armorType": "cloth", "active": True},
            ],
            "days": [],
        })

    def tearDown(self):
        loot_store.DB_PATH = self.original_db
        self.temp_dir.cleanup()

    def allocation(self, **overrides):
        payload = {
            "date": "2026-08-13",
            "raidKey": "venomous_abyss",
            "bossKey": "ulatek",
            "difficulty": "heroic",
            "sourceType": "boss",
            "itemId": "271878",
            "itemName": "Chausses of Unbound Rancor",
            "itemNameZh": "无拘怨恨腿铠",
            "itemTags": ["板甲", "腿部"],
            "recipientId": "tank",
            "awardType": "need",
            "requests": [{"playerId": "tank", "mode": "need", "note": "主专精"}],
        }
        payload.update(overrides)
        return payload

    def test_need_is_limited_once_per_difficulty_per_week(self):
        loot_store.add_allocation(self.allocation())
        with self.assertRaisesRegex(ValueError, "已使用需求权"):
            loot_store.add_allocation(self.allocation(itemId="268202", itemName="Jaw", itemNameZh="武器"))

        normal = loot_store.add_allocation(self.allocation(difficulty="normal", itemId="268202", itemName="Jaw", itemNameZh="武器"))
        self.assertTrue(normal["ok"])

    def test_two_previous_week_absences_disable_need_but_not_greed(self):
        loot_store.save_setup({
            "roster": loot_store.load_document("2026-08-13")["state"]["roster"],
            "days": [
                {"date": "2026-08-06", "raidKey": "venomous_abyss", "attendance": [{"playerId": "tank", "status": "leave"}]},
                {"date": "2026-08-07", "raidKey": "venomous_abyss", "attendance": [{"playerId": "tank", "status": "absent"}]},
            ],
        })
        eligibility = loot_store.load_document("2026-08-13", "heroic")["eligibility"]
        tank = next(row for row in eligibility if row["playerId"] == "tank")
        self.assertFalse(tank["needEligible"])
        self.assertEqual(tank["previousWeekAbsences"], 2)
        with self.assertRaisesRegex(ValueError, "仅可贪婪"):
            loot_store.add_allocation(self.allocation())
        self.assertTrue(loot_store.add_allocation(self.allocation(awardType="greed"))["ok"])

    def test_boe_does_not_require_a_boss(self):
        result = loot_store.add_allocation(self.allocation(
            sourceType="boe", bossKey="", itemId="", itemName="BOE", itemNameZh="装绑装备", awardType="greed"
        ))
        self.assertEqual(result["allocation"]["bossKey"], "boe")


if __name__ == "__main__":
    unittest.main()
