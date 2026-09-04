import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from analyzer_core.analysis_scope import filter_fights, single_fight_scope
from analyzer_core.catalog import find_boss_by_encounter
from analyzer_core.player_abilities import abilities_for_roster, catalog_summary, load_player_ability_catalog
from analyzer_core.single_fight import latest_guild_fight, load_single_fight_config, raid_night_date, recent_guild_reports, report_overview


class AnalysisScopeTests(unittest.TestCase):
    def test_filter_is_opt_in_and_report_local(self):
        fights = [{"id": 1}, {"id": 2}]
        self.assertEqual(filter_fights("abc", fights), fights)
        with single_fight_scope("abc", 2):
            self.assertEqual(filter_fights("abc", fights), [{"id": 2}])
            self.assertEqual(filter_fights("other", fights), [])
        self.assertEqual(filter_fights("abc", fights), fights)


class PlayerAbilityCatalogTests(unittest.TestCase):
    def test_catalog_is_verified_and_covers_all_classes(self):
        summary = catalog_summary()
        self.assertEqual(summary["classCount"], 13)
        self.assertGreaterEqual(summary["abilityCount"], 163)
        self.assertGreaterEqual(summary["spellIdCount"], summary["abilityCount"])
        self.assertEqual(summary["verification"]["checkedAt"], "2026-08-13")
        self.assertEqual(len(summary["digest"]), 16)

    def test_roster_filter_selects_only_present_class_and_spec(self):
        resolved = abilities_for_roster([
            {"id": 7, "name": "Tank", "class": "DeathKnight", "spec": "Blood"},
        ])
        keys = {row["key"] for row in resolved["abilities"]}
        self.assertIn("death-knight.dancing-rune-weapon", keys)
        self.assertIn("death-knight.anti-magic-shell", keys)
        self.assertIn("potion.lights-potential", keys)
        self.assertNotIn("death-knight.pillar-of-frost", keys)
        self.assertFalse(any(row["class"] == "Mage" for row in resolved["abilities"]))

    def test_spec_english_wins_over_localized_display_spec(self):
        resolved = abilities_for_roster([{
            "id": 8, "name": "Bear", "class": "Druid",
            "spec": "守护", "specEnglish": "Guardian",
        }])
        keys = {row["key"] for row in resolved["abilities"]}
        self.assertIn("druid.incarnation-guardian", keys)

    def test_runtime_catalog_has_unique_keys_and_resolvable_ids(self):
        rows = load_player_ability_catalog()["abilities"]
        self.assertEqual(len(rows), len({row["key"] for row in rows}))
        self.assertTrue(all(row["ids"] for row in rows))


class SingleFightDiscoveryTests(unittest.TestCase):
    def test_default_guild_name_waits_for_wcl_lookup_and_env_override_clears_stale_name(self):
        self.assertEqual(load_single_fight_config()["guild"], {"id": 774422, "name": ""})
        previous = os.environ.get("WCL_GUILD_ID")
        os.environ["WCL_GUILD_ID"] = "824636"
        try:
            self.assertEqual(load_single_fight_config()["guild"], {"id": 824636, "name": ""})
        finally:
            if previous is None:
                os.environ.pop("WCL_GUILD_ID", None)
            else:
                os.environ["WCL_GUILD_ID"] = previous

    def test_raid_night_rollover_keeps_after_midnight_pull_on_prior_day(self):
        zone = ZoneInfo("Asia/Shanghai")
        before = datetime(2026, 8, 13, 0, 30, tzinfo=zone).timestamp() * 1000
        after = datetime(2026, 8, 13, 1, 30, tzinfo=zone).timestamp() * 1000
        self.assertEqual(raid_night_date(before, timezone_name="Asia/Shanghai", rollover_hour=1), "2026-08-12")
        self.assertEqual(raid_night_date(after, timezone_name="Asia/Shanghai", rollover_hour=1), "2026-08-13")

    def test_encounter_catalog_maps_supported_bosses(self):
        self.assertEqual(find_boss_by_encounter(3181).boss_key, "crown_of_the_cosmos")
        self.assertEqual(find_boss_by_encounter(3470).boss_key, "nakzali")
        self.assertEqual(find_boss_by_encounter(53470).boss_key, "nakzali")
        self.assertEqual(find_boss_by_encounter(3429).boss_key, "coiledaltar")
        self.assertEqual(find_boss_by_encounter(53429).boss_key, "coiledaltar")
        self.assertEqual(find_boss_by_encounter(3492).boss_key, "ulatek")
        self.assertEqual(find_boss_by_encounter(3379).boss_key, "nymrissa_wavecaller")
        self.assertIsNone(find_boss_by_encounter(999999))

    def test_recent_reports_filters_short_and_non_encounter_fights(self):
        class FakeClient:
            def graphql_data(self, query, variables):
                self.variables = variables
                return {
                    "guildData": {"guild": {"id": 123456, "name": "测试工会"}},
                    "reportData": {"reports": {"data": [{
                        "code": "ABC123", "title": "night", "startTime": 1786550400000,
                        "endTime": 1786550800000, "zone": {"id": 54, "name": "raid"},
                        "fights": [
                            {"id": 1, "name": "Trash", "encounterID": 0, "difficulty": 5, "kill": False, "startTime": 0, "endTime": 30000},
                            {"id": 2, "name": "Crown", "encounterID": 3181, "difficulty": 5, "kill": False, "startTime": 40000, "endTime": 50000},
                            {"id": 3, "name": "Crown", "encounterID": 3181, "difficulty": 5, "kill": True, "startTime": 60000, "endTime": 120000},
                        ],
                    }]}},
                    "rateLimitData": {"limitPerHour": 18000, "pointsSpentThisHour": 20},
                }

        client = FakeClient()
        result = recent_guild_reports(client, limit=1, guild_id=123456)
        self.assertEqual(len(result["reports"]), 1)
        self.assertEqual([row["id"] for row in result["reports"][0]["fights"]], [3])
        self.assertTrue(result["reports"][0]["lastFight"]["supported"])
        self.assertEqual(client.variables["guildID"], 123456)
        self.assertEqual(result["guild"], {"id": 123456, "name": "测试工会"})

    def test_report_overview_joins_friendly_players_and_specs(self):
        class FakeClient:
            def graphql_data(self, query, variables):
                return {"reportData": {"report": {
                    "title": "progress", "startTime": 1786550400000, "endTime": 1786550800000,
                    "guild": {"id": 123456, "name": "测试工会"},
                    "fights": [{
                        "id": 9, "name": "Crown", "encounterID": 3181, "difficulty": 5,
                        "kill": False, "startTime": 1000, "endTime": 61000,
                        "friendlyPlayers": [7], "friendlySpecs": ["Blood"],
                    }],
                    "masterData": {"actors": [{"id": 7, "name": "Tank", "type": "Player", "subType": "DeathKnight", "gameID": 1}]},
                }}}

        result = report_overview("ABC123", FakeClient())
        fight = result["fights"][0]
        self.assertEqual(fight["roster"][0]["spec"], "Blood")
        self.assertEqual(fight["roster"][0]["class"], "DeathKnight")
        self.assertTrue(fight["supported"])
        self.assertGreater(fight["abilitySelection"]["abilityCount"], 1)
        self.assertEqual(result["guild"], {"id": 123456, "name": "测试工会"})

    def test_recent_reports_rejects_non_positive_guild_id(self):
        with self.assertRaisesRegex(ValueError, "正整数"):
            recent_guild_reports(object(), guild_id=0)

    def test_latest_fight_is_selected_across_recent_reports(self):
        class FakeClient:
            def graphql_data(self, query, variables):
                return {
                    "guildData": {"guild": {"id": 123456, "name": "测试工会"}},
                    "reportData": {"reports": {"data": [
                        {"code": "OLD", "title": "old", "startTime": 100000, "endTime": 200000,
                         "fights": [{"id": 7, "name": "old", "encounterID": 3181, "difficulty": 5, "kill": False, "startTime": 1000, "endTime": 61000}]},
                        {"code": "NEW", "title": "new", "startTime": 300000, "endTime": 400000,
                         "fights": [{"id": 9, "name": "new", "encounterID": 3181, "difficulty": 5, "kill": False, "startTime": 2000, "endTime": 72000}]},
                    ]}},
                    "rateLimitData": {},
                }

        selected = latest_guild_fight(FakeClient(), guild_id=123456)
        self.assertEqual(selected["report"]["code"], "NEW")
        self.assertEqual(selected["fight"]["id"], 9)


class SingleFightFrontendTests(unittest.TestCase):
    def test_route_and_manual_fetch_are_wired(self):
        root = Path(__file__).resolve().parents[1]
        server = (root / "server.py").read_text(encoding="utf-8")
        page = (root / "frontend" / "tools" / "single-fight" / "index.html").read_text(encoding="utf-8")
        self.assertIn('"/single-fight": "/frontend/tools/single-fight/index.html"', server)
        self.assertIn('/api/single-fight/analyze', page)
        self.assertIn('id="guildSelect"', page)
        self.assertIn('&guildID=${encodeURIComponent(guildID)}', page)
        self.assertIn('const guildLabel=(id,name="")=>guildName(id,name)', page)
        self.assertIn('$("guildSelect").addEventListener("change"', page)
        self.assertIn('$("loadReports").addEventListener("click",loadReports)', page)
        self.assertNotIn("then(loadReports)", page)
        self.assertIn('id="waitScreen"', page)
        self.assertNotIn("singleFightPlayerTimeline", page)
        self.assertNotIn("爆发药", page)


class SingleFightProgressTests(unittest.TestCase):
    def test_single_fight_maps_wcl_subprogress_into_the_current_pull(self):
        from server import Job, translate_plugin_progress

        job = Job(id="test", owner_user_id=1)
        translate_plugin_progress(job, {"message": "读取 Fight 33（1/1）", "stage": "analyze"})
        self.assertEqual(job.percent, 16)
        translate_plugin_progress(job, {
            "message": "读取减益与叠层记录", "percent": 54, "stage": "fetch", "detail": True,
        })
        self.assertEqual(job.percent, 58)
        self.assertEqual(job.message, "分析战斗 1/1 · 读取减益与叠层记录")

    def test_multiple_reports_reserve_progress_for_later_reports(self):
        from server import Job, translate_plugin_progress

        job = Job(id="test", owner_user_id=1, report_total=2)
        translate_plugin_progress(job, {"message": "匹配到 10 场开荒记录"})
        translate_plugin_progress(job, {"message": "读取 Fight 5（5/10）"})
        translate_plugin_progress(job, {
            "message": "读取场地坐标样本", "percent": 88, "stage": "fetch", "detail": True,
        })
        self.assertLess(job.percent, 50)
        translate_plugin_progress(job, {"message": "匹配到 8 场开荒记录"})
        self.assertGreaterEqual(job.percent, 55)


if __name__ == "__main__":
    unittest.main()
