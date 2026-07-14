import unittest

from boss_plugins.void_spire.crown_of_the_cosmos import (
    apply_global_death_exemption,
    melurium_alive_in_arrow_snapshot,
    MELURIUM_EXPECTED_MS,
)
from tools.crown_single_fight_audit import SPELL, build_void_death_healing


class CrownGlobalDeathExemptionTests(unittest.TestCase):
    def test_only_events_strictly_after_eighth_death_are_exempt(self):
        fight = {"startTime": 100_000}
        deaths = [{"timestamp": 101_000 + index * 1_000} for index in range(8)]
        board = {
            "p15AvoidableDeaths": [{
                "name": "测试玩家",
                "hitCount": 3,
                "deathCount": 3,
                "totalDamage": 0,
                "events": [
                    {"positionMs": 7_999, "counted": True},
                    {"positionMs": 8_000, "counted": True},
                    {"positionMs": 8_001, "counted": True},
                ],
            }],
        }

        result = apply_global_death_exemption(board, deaths, fight)
        events = board["p15AvoidableDeaths"][0]["events"]

        self.assertEqual(result["cutoffPositionMs"], 8_000)
        self.assertEqual([event["counted"] for event in events], [True, True, False])
        self.assertTrue(events[2]["globalExempt"])
        self.assertIn("第8次死亡", events[2]["globalExemptionReason"])
        self.assertEqual(board["p15AvoidableDeaths"][0]["hitCount"], 2)
        self.assertEqual(board["p15AvoidableDeaths"][0]["deathCount"], 2)

    def test_existing_mechanic_reason_is_retained_when_global_rule_wins(self):
        fight = {"startTime": 0}
        deaths = [{"timestamp": index * 1_000} for index in range(1, 9)]
        board = {
            "waterOutliers": [{
                "name": "测试玩家",
                "hitCount": 0,
                "deathCount": 0,
                "totalDamage": 0,
                "events": [{
                    "positionMs": 9_000,
                    "counted": False,
                    "countReason": "P1放水仅展示，不计数",
                }],
            }],
        }

        apply_global_death_exemption(board, deaths, fight)
        event = board["waterOutliers"][0]["events"][0]

        self.assertEqual(event["mechanicExemptionReason"], "P1放水仅展示，不计数")
        self.assertIn("全局最高优先级豁免", event["countReason"])


class MeluriumRound5SnapshotTests(unittest.TestCase):
    def test_melurium_alive_when_present_in_snapshot(self):
        arrow = {
            "timeMs": MELURIUM_EXPECTED_MS,
            "snapshot": {"bosses": [{"name": "殁里乌姆", "gameID": 254174}, {"name": "奥蕾莉亚·风行者"}]},
        }
        self.assertTrue(melurium_alive_in_arrow_snapshot(arrow))

    def test_melurium_dead_when_missing_from_snapshot(self):
        arrow = {
            "timeMs": MELURIUM_EXPECTED_MS,
            "snapshot": {"bosses": [{"name": "龌勒卢斯"}, {"name": "奥蕾莉亚·风行者"}]},
        }
        self.assertFalse(melurium_alive_in_arrow_snapshot(arrow))


class VoidDeathHealingRosterTests(unittest.TestCase):
    def test_accepts_player_ids_list_for_dead_roster_math(self):
        """player_ids() returns a sorted list; void-death roster math must coerce to sets."""
        fight = {"startTime": 0, "endTime": 100_000, "id": 26}
        events = {
            "deaths": [{
                "targetID": 1,
                "timestamp": 5_000,
                "killingAbilityGameID": SPELL["collapsing_void"],
            }],
            "healing": [],
            "debuffs": [],
            "casts": [],
        }
        rows = build_void_death_healing(
            fight,
            {1: "A", 2: "B", 3: "C", 10: "H"},
            {},
            events,
            [1, 2, 3],
            {10},
            [],
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["deadPlayerIDsAtDeath"], [1])
        self.assertEqual(rows[0]["playerRosterCount"], 3)
        self.assertEqual(rows[0]["aliveHealerIDsAtDeath"], [])


if __name__ == "__main__":
    unittest.main()
