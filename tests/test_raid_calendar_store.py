import tempfile
import unittest
import shutil
from pathlib import Path

from analyzer_core import raid_calendar_store as calendar_store


class RaidCalendarStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db = calendar_store.DB_PATH
        self.original_legacy_db = calendar_store.LEGACY_DB_PATH
        calendar_store.DB_PATH = Path(self.temp_dir.name) / "raid_calendar.db"
        calendar_store.LEGACY_DB_PATH = Path(self.temp_dir.name) / "missing_legacy.db"
        calendar_store.save_setup({
            "roster": [
                {"id": "tank", "name": "坦克", "classKey": "warrior", "className": "战士", "armorType": "plate", "active": True},
                {"id": "mage", "name": "法师", "classKey": "mage", "className": "法师", "armorType": "cloth", "active": True},
            ],
            "days": [],
        })

    def tearDown(self):
        calendar_store.DB_PATH = self.original_db
        calendar_store.LEGACY_DB_PATH = self.original_legacy_db
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
        calendar_store.add_allocation(self.allocation())
        with self.assertRaises(calendar_store.LootConflictWarning) as caught:
            calendar_store.add_allocation(self.allocation(itemId="268202", itemName="Jaw", itemNameZh="武器"))
        self.assertIn("于 2026-08-13 获得了", caught.exception.warnings[0])

        overridden = calendar_store.add_allocation(self.allocation(
            itemId="268202", itemName="Jaw", itemNameZh="武器", confirmOverride=True
        ))
        self.assertTrue(overridden["overridden"])

        normal = calendar_store.add_allocation(self.allocation(difficulty="normal", itemId="268202", itemName="Jaw", itemNameZh="武器"))
        self.assertTrue(normal["ok"])

    def test_two_previous_week_absences_disable_need_but_not_greed(self):
        calendar_store.save_setup({
            "roster": calendar_store.load_document("2026-08-13")["state"]["roster"],
            "days": [
                {"date": "2026-08-24", "raidKey": "venomous_abyss", "attendance": [{"playerId": "tank", "status": "leave"}]},
                {"date": "2026-08-25", "raidKey": "venomous_abyss", "attendance": [{"playerId": "tank", "status": "absent"}]},
            ],
        })
        eligibility = calendar_store.load_document("2026-08-27", "heroic")["eligibility"]
        tank = next(row for row in eligibility if row["playerId"] == "tank")
        self.assertFalse(tank["needEligible"])
        self.assertEqual(tank["previousWeekAbsences"], 2)
        self.assertEqual(tank["previousWeekAbsenceDates"], ["2026-08-24", "2026-08-25"])
        with self.assertRaises(calendar_store.LootConflictWarning) as caught:
            calendar_store.add_allocation(self.allocation(date="2026-08-27"))
        self.assertIn("2026-08-24、2026-08-25", caught.exception.warnings[0])
        self.assertIn("暂无需求权", caught.exception.warnings[0])
        self.assertTrue(calendar_store.add_allocation(self.allocation(date="2026-08-27", confirmOverride=True))["ok"])
        self.assertTrue(calendar_store.add_allocation(self.allocation(date="2026-08-27", awardType="greed"))["ok"])

    def test_boe_does_not_require_a_boss(self):
        result = calendar_store.add_allocation(self.allocation(
            sourceType="boe", bossKey="", itemId="", itemName="BOE", itemNameZh="装绑装备", awardType="greed"
        ))
        self.assertEqual(result["allocation"]["bossKey"], "boe")

    def test_progression_calendar_and_mythic_resets(self):
        document = calendar_store.load_document("2026-09-01")
        self.assertIn("2026-08-20", document["calendar"]["progressionDates"])
        self.assertIn("2026-08-24", document["calendar"]["progressionDates"])
        self.assertIn("2026-08-25", document["calendar"]["progressionDates"])
        self.assertIn("2026-08-27", document["calendar"]["progressionDates"])
        resets = document["calendar"]["mythicResetDates"]
        self.assertIn("2026-08-27", resets)
        self.assertIn("2026-09-10", resets)
        self.assertNotIn("2026-09-03", resets)

        calendar_store.save_settings({"mythicCadenceWeeks": 1})
        resets = calendar_store.load_document("2026-09-01")["calendar"]["mythicResetDates"]
        self.assertIn("2026-08-27", resets)
        self.assertIn("2026-09-03", resets)
        self.assertIn("2026-09-10", resets)

    def test_progression_days_can_be_manually_added_or_cancelled_without_changing_resets(self):
        before = calendar_store.load_document("2026-09-01")["calendar"]["mythicResetDates"]
        calendar_store.save_setup({
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
        document = calendar_store.load_document("2026-09-01")
        self.assertIn("2026-08-26", document["calendar"]["progressionDates"])
        self.assertNotIn("2026-08-27", document["calendar"]["progressionDates"])
        self.assertEqual(document["calendar"]["mythicResetDates"], before)

    def test_cancelled_progression_day_does_not_count_as_an_absence(self):
        calendar_store.save_setup({
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
        eligibility = calendar_store.load_document("2026-08-27", "heroic")["eligibility"]
        tank = next(row for row in eligibility if row["playerId"] == "tank")
        self.assertEqual(tank["previousWeekAbsenceDates"], ["2026-08-25"])
        self.assertTrue(tank["needEligible"])

    def test_mythic_need_uses_two_week_period_by_default(self):
        calendar_store.add_allocation(self.allocation(date="2026-08-27", difficulty="mythic", itemNameZh="毒灼护腕"))
        with self.assertRaises(calendar_store.LootConflictWarning) as caught:
            calendar_store.add_allocation(self.allocation(date="2026-09-03", difficulty="mythic", itemNameZh="咒魇裂魂匕首"))
        self.assertIn("于 2026-08-27 获得了「毒灼护腕」", caught.exception.warnings[0])

        calendar_store.save_settings({"mythicCadenceWeeks": 1})
        self.assertTrue(calendar_store.add_allocation(self.allocation(
            date="2026-09-03", difficulty="mythic", itemNameZh="咒魇裂魂匕首"
        ))["ok"])

    def test_need_lockout_starts_on_thursday(self):
        calendar_store.add_allocation(self.allocation(date="2026-08-27"))
        with self.assertRaises(calendar_store.LootConflictWarning):
            calendar_store.add_allocation(self.allocation(date="2026-09-02", itemId="other", itemNameZh="另一件"))
        self.assertTrue(calendar_store.add_allocation(self.allocation(date="2026-09-03", itemId="new", itemNameZh="新周装备"))["ok"])

    def test_catalog_contains_complete_official_zhcn_raid_loot(self):
        catalog = calendar_store.load_catalog()
        self.assertEqual(catalog["source"]["build"], "12.1.0.69189")
        self.assertEqual(catalog["source"]["locale"], "zhCN")
        self.assertEqual(catalog["summary"], {"raidCount": 2, "bossCount": 9, "itemCount": 130})
        items = [item for raid in catalog["raids"] for boss in raid["bosses"] for item in boss["items"]]
        self.assertTrue(all(item["nameZh"] and item["lootType"] and item["slot"] for item in items))
        self.assertEqual(sum(item["lootType"] == "家具" for item in items), 12)
        self.assertIn("“受枷者的狂怒”壁画", {item["nameZh"] for item in items})

    def test_roster_nickname_is_preserved_and_displayed_first(self):
        calendar_store.save_setup({
            "roster": [
                {"id": "papa", "name": "贪睡熊熊", "nickname": "爬爬", "classKey": "druid", "className": "德鲁伊", "armorType": "leather", "active": True},
            ],
            "days": [],
        })
        player = calendar_store.load_document("2026-08-13")["state"]["roster"][0]
        self.assertEqual(player["nickname"], "爬爬")
        self.assertEqual(player["name"], "贪睡熊熊")
        # 职业决定护甲：德鲁伊 = 皮甲
        self.assertEqual(player["armorType"], "leather")

    def test_blackmark_upsert_per_date_raid_and_difficulty(self):
        first = calendar_store.add_blackmark({"date": "2026-08-13", "difficulty": "heroic", "raidKey": "venomous_abyss", "playerId": "tank", "verdict": "black", "notes": "板甲护腕全需"})
        self.assertTrue(first["ok"])
        self.assertFalse(first["replaced"])
        # 同日同副本同难度重复登记 = 覆盖更新（换人/改判定/改备注）
        second = calendar_store.add_blackmark({"date": "2026-08-13", "difficulty": "heroic", "raidKey": "venomous_abyss", "playerId": "mage", "verdict": "red", "notes": "改成法师黑，且当天掉落爆炸"})
        self.assertTrue(second["replaced"])
        self.assertEqual(second["mark"]["playerId"], "mage")
        self.assertEqual(second["mark"]["verdict"], "red")
        # 同日不同副本同难度 = 两条独立记录（同一天可以黑多个副本）
        other_raid = calendar_store.add_blackmark({"date": "2026-08-13", "difficulty": "heroic", "raidKey": "tidebound_grotto", "playerId": "tank", "verdict": "neutral"})
        self.assertFalse(other_raid["replaced"])
        state = calendar_store.load_document("2026-08-13")["state"]
        marks = {(row["date"], row["raidKey"], row["difficulty"]): row for row in state["blackMarks"]}
        self.assertEqual(marks[("2026-08-13", "venomous_abyss", "heroic")]["playerId"], "mage")
        self.assertEqual(marks[("2026-08-13", "venomous_abyss", "heroic")]["verdict"], "red")
        self.assertEqual(marks[("2026-08-13", "tidebound_grotto", "heroic")]["playerId"], "tank")
        self.assertEqual(marks[("2026-08-13", "tidebound_grotto", "heroic")]["verdict"], "neutral")
        self.assertEqual(len(state["blackMarks"]), 2)
        # 非法副本 key 回退到目录第一个副本（当前 CD 团本）
        fallback = calendar_store.add_blackmark({"date": "2026-08-13", "difficulty": "normal", "raidKey": "not_a_raid", "playerId": "tank"})["mark"]
        self.assertEqual(fallback["raidKey"], "tidebound_grotto")

    def test_blackmark_requires_valid_player_difficulty_and_deletable(self):
        with self.assertRaises(ValueError):
            calendar_store.add_blackmark({"date": "2026-08-13", "difficulty": "heroic", "playerId": "ghost"})
        with self.assertRaises(ValueError):
            calendar_store.add_blackmark({"date": "2026-08-13", "difficulty": "torghast", "playerId": "tank"})
        mark = calendar_store.add_blackmark({"date": "2026-08-13", "difficulty": "mythic", "raidKey": "venomous_abyss", "playerId": "tank", "notes": "史诗黑"})["mark"]
        result = calendar_store.delete_blackmark(mark["id"])
        self.assertTrue(result["ok"])
        state = calendar_store.load_document("2026-08-13")["state"]
        self.assertFalse(any(row["playerId"] == "tank" and row["difficulty"] == "mythic" for row in state["blackMarks"]))
        with self.assertRaises(ValueError):
            calendar_store.delete_blackmark(mark["id"])

    def test_blackmark_verdict_defaults_and_invalid_fallback(self):
        # 不传判定 = 默认 black；非法值回退 black
        default_mark = calendar_store.add_blackmark({"date": "2026-08-15", "difficulty": "heroic", "playerId": "tank"})["mark"]
        self.assertEqual(default_mark["verdict"], "black")
        invalid = calendar_store.add_blackmark({"date": "2026-08-16", "difficulty": "heroic", "playerId": "tank", "verdict": "purple"})["mark"]
        self.assertEqual(invalid["verdict"], "black")
        red = calendar_store.add_blackmark({"date": "2026-08-17", "difficulty": "heroic", "playerId": "tank", "verdict": "RED"})["mark"]
        self.assertEqual(red["verdict"], "red")
        # 第三种判定：一般般（不掉不炸）
        neutral = calendar_store.add_blackmark({"date": "2026-08-18", "difficulty": "heroic", "playerId": "tank", "verdict": "neutral"})["mark"]
        self.assertEqual(neutral["verdict"], "neutral")

    def test_blackmark_history_survives_and_feeds_prompt_text(self):
        calendar_store.add_blackmark({"date": "2026-08-13", "difficulty": "heroic", "raidKey": "venomous_abyss", "playerId": "tank", "notes": "三次需求全歪"})
        document = calendar_store.load_document("2026-09-03")
        marks = [row for row in document["state"]["blackMarks"] if row["playerId"] == "tank"]
        self.assertEqual(len(marks), 1)
        mark = marks[0]
        names = {row["id"]: row for row in document["state"]["roster"]}
        prompt = (
            f"该玩家于 {mark['date']} 黑本【{calendar_store.DIFFICULTY_NAMES[mark['difficulty']]}】"
            f"【烈毒之渊】，【{mark['notes']}】"
        )
        self.assertIn("2026-08-13", prompt)
        self.assertIn("英雄", prompt)
        self.assertEqual(names["tank"]["name"], "坦克")
        self.assertIn("【烈毒之渊】", prompt)

    def test_legacy_scoreboard_database_is_copied_to_calendar_location(self):
        legacy_path = Path(self.temp_dir.name) / "scoreboard" / "loot.db"
        legacy_path.parent.mkdir(parents=True)
        shutil.copy2(calendar_store.DB_PATH, legacy_path)
        calendar_store.DB_PATH.unlink()
        calendar_store.LEGACY_DB_PATH = legacy_path

        document = calendar_store.load_document("2026-08-13")

        self.assertTrue(calendar_store.DB_PATH.is_file())
        self.assertTrue(legacy_path.is_file())
        self.assertEqual(document["state"]["roster"][0]["id"], "tank")


if __name__ == "__main__":
    unittest.main()
