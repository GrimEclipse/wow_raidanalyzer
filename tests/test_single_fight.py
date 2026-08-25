import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from analyzer_core.analysis_scope import filter_fights, single_fight_scope
from analyzer_core.catalog import find_boss_by_encounter
from analyzer_core.player_abilities import abilities_for_roster, catalog_summary, load_player_ability_catalog
from analyzer_core.single_fight import raid_night_date, recent_guild_reports, report_overview


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
        self.assertIsNone(find_boss_by_encounter(999999))

    def test_recent_reports_filters_short_and_non_encounter_fights(self):
        class FakeClient:
            def graphql_data(self, query, variables):
                return {
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

        result = recent_guild_reports(FakeClient(), limit=1)
        self.assertEqual(len(result["reports"]), 1)
        self.assertEqual([row["id"] for row in result["reports"][0]["fights"]], [3])
        self.assertTrue(result["reports"][0]["lastFight"]["supported"])

    def test_report_overview_joins_friendly_players_and_specs(self):
        class FakeClient:
            def graphql_data(self, query, variables):
                return {"reportData": {"report": {
                    "title": "progress", "startTime": 1786550400000, "endTime": 1786550800000,
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


class SingleFightFrontendTests(unittest.TestCase):
    def test_route_and_manual_fetch_are_wired(self):
        root = Path(__file__).resolve().parents[1]
        server = (root / "server.py").read_text(encoding="utf-8")
        page = (root / "frontend" / "tools" / "single-fight" / "index.html").read_text(encoding="utf-8")
        self.assertIn('"/single-fight": "/frontend/tools/single-fight/index.html"', server)
        self.assertIn('/api/single-fight/analyze', page)
        self.assertIn('$("loadReports").addEventListener("click",loadReports)', page)
        self.assertNotIn("then(loadReports)", page)


if __name__ == "__main__":
    unittest.main()
