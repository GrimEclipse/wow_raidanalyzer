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

    def test_need_conflict_warns_but_can_be_overridden(self):
        loot_store.add_allocation(self.allocation())
        with self.assertRaises(loot_store.LootConflictWarning) as caught:
            loot_store.add_allocation(self.allocation(itemId="268202", itemName="Jaw", itemNameZh="武器"))
        self.assertIn("于 2026-08-13 获得了", caught.exception.warnings[0])

        overridden = loot_store.add_allocation(self.allocation(
            itemId="268202", itemName="Jaw", itemNameZh="武器", confirmOverride=True
        ))
        self.assertTrue(overridden["overridden"])

        normal = loot_store.add_allocation(self.allocation(difficulty="normal", itemId="268202", itemName="Jaw", itemNameZh="武器"))
        self.assertTrue(normal["ok"])

    def test_two_previous_week_absences_disable_need_but_not_greed(self):
        loot_store.save_setup({
            "roster": loot_store.load_document("2026-08-13")["state"]["roster"],
            "days": [
                {"date": "2026-08-24", "raidKey": "venomous_abyss", "attendance": [{"playerId": "tank", "status": "leave"}]},
                {"date": "2026-08-25", "raidKey": "venomous_abyss", "attendance": [{"playerId": "tank", "status": "absent"}]},
            ],
        })
        eligibility = loot_store.load_document("2026-08-27", "heroic")["eligibility"]
        tank = next(row for row in eligibility if row["playerId"] == "tank")
        self.assertFalse(tank["needEligible"])
        self.assertEqual(tank["previousWeekAbsences"], 2)
        self.assertEqual(tank["previousWeekAbsenceDates"], ["2026-08-24", "2026-08-25"])
        with self.assertRaises(loot_store.LootConflictWarning) as caught:
            loot_store.add_allocation(self.allocation(date="2026-08-27"))
        self.assertIn("2026-08-24、2026-08-25", caught.exception.warnings[0])
        self.assertIn("暂无需求权", caught.exception.warnings[0])
        self.assertTrue(loot_store.add_allocation(self.allocation(date="2026-08-27", confirmOverride=True))["ok"])
        self.assertTrue(loot_store.add_allocation(self.allocation(date="2026-08-27", awardType="greed"))["ok"])

    def test_boe_does_not_require_a_boss(self):
        result = loot_store.add_allocation(self.allocation(
            sourceType="boe", bossKey="", itemId="", itemName="BOE", itemNameZh="装绑装备", awardType="greed"
        ))
        self.assertEqual(result["allocation"]["bossKey"], "boe")

    def test_progression_calendar_and_mythic_resets(self):
        document = loot_store.load_document("2026-09-01")
        self.assertIn("2026-08-20", document["calendar"]["progressionDates"])
        self.assertIn("2026-08-24", document["calendar"]["progressionDates"])
        self.assertIn("2026-08-25", document["calendar"]["progressionDates"])
        self.assertIn("2026-08-27", document["calendar"]["progressionDates"])
        resets = document["calendar"]["mythicResetDates"]
        self.assertIn("2026-08-20", resets)
        self.assertIn("2026-09-03", resets)
        self.assertNotIn("2026-08-27", resets)

        loot_store.save_settings({"mythicCadenceWeeks": 1})
        resets = loot_store.load_document("2026-09-01")["calendar"]["mythicResetDates"]
        self.assertIn("2026-08-20", resets)
        self.assertIn("2026-08-27", resets)
        self.assertIn("2026-09-03", resets)
        self.assertIn("2026-09-10", resets)

    def test_progression_days_can_be_manually_added_or_cancelled_without_changing_resets(self):
        before = loot_store.load_document("2026-09-01")["calendar"]["mythicResetDates"]
        loot_store.save_setup({
            "days": [
                {
                    "date": "2026-08-26",
                    "raidKey": "venomous_abyss",
                    "progressionOverride": True,
                    "attendance": [],
                },
                {
                    "date": "2026-08-27",
                    "raidKey": "venomous_abyss",
                    "progressionOverride": False,
                    "attendance": [],
                },
            ],
        })
        document = loot_store.load_document("2026-09-01")
        self.assertIn("2026-08-26", document["calendar"]["progressionDates"])
        self.assertNotIn("2026-08-27", document["calendar"]["progressionDates"])
        self.assertEqual(document["calendar"]["mythicResetDates"], before)

    def test_cancelled_progression_day_does_not_count_as_an_absence(self):
        loot_store.save_setup({
            "days": [
                {
                    "date": "2026-08-24",
                    "raidKey": "venomous_abyss",
                    "progressionOverride": False,
                    "attendance": [{"playerId": "tank", "status": "leave"}],
                },
                {
                    "date": "2026-08-25",
                    "raidKey": "venomous_abyss",
                    "progressionOverride": True,
                    "attendance": [{"playerId": "tank", "status": "leave"}],
                },
            ],
        })
        eligibility = loot_store.load_document("2026-08-27", "heroic")["eligibility"]
        tank = next(row for row in eligibility if row["playerId"] == "tank")
        self.assertEqual(tank["previousWeekAbsenceDates"], ["2026-08-25"])
        self.assertTrue(tank["needEligible"])

    def test_mythic_need_uses_two_week_period_by_default(self):
        loot_store.add_allocation(self.allocation(date="2026-08-24", difficulty="mythic", itemNameZh="毒灼护腕"))
        with self.assertRaises(loot_store.LootConflictWarning) as caught:
            loot_store.add_allocation(self.allocation(date="2026-08-27", difficulty="mythic", itemNameZh="咒魇裂魂匕首"))
        self.assertIn("于 2026-08-24 获得了「毒灼护腕」", caught.exception.warnings[0])

        loot_store.save_settings({"mythicCadenceWeeks": 1})
        self.assertTrue(loot_store.add_allocation(self.allocation(
            date="2026-08-27", difficulty="mythic", itemNameZh="咒魇裂魂匕首"
        ))["ok"])

    def test_need_lockout_starts_on_thursday(self):
        loot_store.add_allocation(self.allocation(date="2026-08-27"))
        with self.assertRaises(loot_store.LootConflictWarning):
            loot_store.add_allocation(self.allocation(date="2026-09-02", itemId="other", itemNameZh="另一件"))
        self.assertTrue(loot_store.add_allocation(self.allocation(date="2026-09-03", itemId="new", itemNameZh="新周装备"))["ok"])

    def test_catalog_contains_complete_official_zhcn_raid_loot(self):
        catalog = loot_store.load_catalog()
        self.assertEqual(catalog["source"]["build"], "12.1.0.69189")
        self.assertEqual(catalog["source"]["locale"], "zhCN")
        self.assertEqual(catalog["summary"], {"raidCount": 2, "bossCount": 9, "itemCount": 130})
        items = [item for raid in catalog["raids"] for boss in raid["bosses"] for item in boss["items"]]
        self.assertTrue(all(item["nameZh"] and item["lootType"] and item["slot"] for item in items))
        self.assertEqual(sum(item["lootType"] == "家具" for item in items), 12)
        self.assertIn("“受枷者的狂怒”壁画", {item["nameZh"] for item in items})


if __name__ == "__main__":
    unittest.main()
