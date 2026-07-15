import unittest

from boss_plugins.void_spire.crown_of_the_cosmos import (
    apply_global_death_exemption,
    build_fight_combatants,
    classify_fight,
    finalize_p1_boss_attribution,
    first_bridge_cluster,
    is_enrage_tank_death,
    is_p15_abandon_jump,
    melurium_alive_in_arrow_snapshot,
    p1_silver_arrow_round_succeeded,
    terminal_abandon_bridge_cluster,
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


class CrownEnrageTankDeathTests(unittest.TestCase):
    def test_enrage_tank_death_is_not_tank_fault(self):
        death = {"timestamp": 120_000, "killingAbilityGameID": 1}
        self.assertTrue(is_enrage_tank_death(death, enrage_at=100_000))
        self.assertFalse(is_enrage_tank_death(death, enrage_at=130_000))

    def test_p1_tank_death_after_enrage_classifies_as_boss_enrage(self):
        fight = {"startTime": 0, "endTime": 200_000, "kill": False}
        markers = {"p15Start": 150_000, "p2Start": None}
        deaths = [
            {"timestamp": 110_000, "targetID": 1, "killingAbilityGameID": 1},
            {"timestamp": 111_000, "targetID": 2, "killingAbilityGameID": 1},
            {"timestamp": 112_000, "targetID": 3, "killingAbilityGameID": 1233826},
        ]
        buffs = [{"type": "applybuff", "timestamp": 100_000, "abilityGameID": 26662}]
        result = classify_fight(fight, deaths, markers, buffs)
        self.assertEqual(result["key"], "p1_boss_enrage")
        self.assertTrue(result.get("boardExclude"))
        self.assertNotEqual(result["key"], "tank_death")

    def test_p15_never_uses_tank_death_key(self):
        fight = {"startTime": 0, "endTime": 180_000, "kill": False}
        markers = {"p15Start": 100_000, "p2Start": None}
        deaths = [
            {"timestamp": 110_000, "targetID": 1, "killingAbilityGameID": 1},
            *[{"timestamp": 140_000 + index * 200, "targetID": 10 + index, "killingAbilityGameID": None} for index in range(12)],
        ]
        buffs = [{"type": "applybuff", "timestamp": 105_000, "abilityGameID": 26662}]
        result = classify_fight(fight, deaths, markers, buffs)
        self.assertEqual(result["phase"], "P1.5")
        self.assertNotEqual(result["key"], "tank_death")


class CrownAbandonJumpExemptionTests(unittest.TestCase):
    def test_early_p15_cliff_not_exempt_when_raid_jumps_in_p2(self):
        fight = {"startTime": 0, "endTime": 220_000}
        markers = {"p15Start": 100_000, "p2Start": 180_000}
        deaths = [
            {"timestamp": 120_000, "targetID": 1, "killingAbilityGameID": 1243981},
            {"timestamp": 130_000, "targetID": 2, "killingAbilityGameID": None},
            {"timestamp": 140_000, "targetID": 3, "killingAbilityGameID": 1243981},
            {"timestamp": 145_000, "targetID": 4, "killingAbilityGameID": 1243981},
            *[{"timestamp": 190_000 + index * 300, "targetID": 20 + index, "killingAbilityGameID": None} for index in range(12)],
        ]
        cluster = terminal_abandon_bridge_cluster(deaths)
        self.assertIsNotNone(cluster)
        self.assertGreaterEqual(cluster["start"], 180_000)
        death_row = {"abilityID": None, "absoluteTime": 130_000, "time": "02:10", "phase": "P1.5"}
        self.assertFalse(is_p15_abandon_jump(death_row, cluster, markers, fight))

    def test_terminal_p15_jump_cluster_is_exempt(self):
        fight = {"startTime": 0, "endTime": 160_000}
        markers = {"p15Start": 90_000, "p2Start": None}
        deaths = [
            {"timestamp": 100_000, "targetID": 1, "killingAbilityGameID": 1243981},
            *[{"timestamp": 120_000 + index * 250, "targetID": 10 + index, "killingAbilityGameID": None} for index in range(12)],
        ]
        cluster = terminal_abandon_bridge_cluster(deaths)
        death_row = {"abilityID": None, "absoluteTime": 121_000, "time": "02:01", "phase": "P1.5"}
        self.assertTrue(is_p15_abandon_jump(death_row, cluster, markers, fight))

    def test_bridge_cluster_prefers_largest_not_first_lone_fall(self):
        deaths = [
            {"timestamp": 50_000, "targetID": 1, "killingAbilityGameID": None},
            *[{"timestamp": 90_000 + index * 200, "targetID": 10 + index, "killingAbilityGameID": None} for index in range(8)],
        ]
        cluster = first_bridge_cluster(deaths)
        self.assertGreaterEqual(cluster["start"], 90_000)
        self.assertGreaterEqual(len(cluster["events"]), 8)


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


class FightCombatantRosterTests(unittest.TestCase):
    def test_roster_uses_friendly_players_not_whole_report_actors(self):
        fight = {"friendlyPlayers": [1, 2]}
        actor_map = {1: "冠冕A", 2: "冠冕B", 3: "其他Boss的人", 4: "路过的人"}
        actor_type = {1: "Player", 2: "Player", 3: "Player", 4: "Player"}
        player_roles = {1: "tank", 2: "range-dps"}
        combatants = build_fight_combatants(fight, actor_map, player_roles, actor_type)
        self.assertEqual([row["name"] for row in combatants], ["冠冕A", "冠冕B"])
        self.assertEqual(combatants[0]["roles"], ["tank"])
        self.assertEqual(combatants[1]["roles"], ["range-dps"])

    def test_roster_falls_back_to_combatant_info_when_friendly_missing(self):
        fight = {}
        actor_map = {10: "甲", 11: "乙", 12: "丙"}
        player_roles = {10: "melee-healer", 11: "melee-dps"}
        combatants = build_fight_combatants(fight, actor_map, player_roles)
        self.assertEqual([row["name"] for row in combatants], ["乙", "甲"])
        self.assertEqual({row["name"]: row["roles"] for row in combatants}, {
            "甲": ["melee-healer"],
            "乙": ["melee-dps"],
        })


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


class CrownP1SilverArrowAttributionTests(unittest.TestCase):
    def test_binding_remove_fallback_when_ray_misses(self):
        marked = [
            {"targetID": 2, "player": "渊重音"},
            {"targetID": 7, "player": "杀杀孩"},
        ]
        ray_miss = [
            {"targetID": 2, "player": "渊重音", "bosses": [], "hitBoss": False},
            {"targetID": 7, "player": "杀杀孩", "bosses": [], "hitBoss": False},
        ]
        hit_events = [{"targetID": 9, "boss": "龌勒卢斯", "timeMs": 125633}]

        attrs = finalize_p1_boss_attribution(marked, ray_miss, hit_events)

        self.assertTrue(all(row["hitBoss"] for row in attrs))
        self.assertEqual(attrs[0]["bosses"], ["龌勒卢斯"])
        self.assertEqual(attrs[0]["attributionSource"], "binding_remove_fallback")

    def test_round_succeeded_with_hit_events_even_if_attribution_misses(self):
        arrow = {
            "p1BossAttribution": [
                {"player": "渊重音", "hitBoss": False, "bosses": []},
                {"player": "杀杀孩", "hitBoss": False, "bosses": []},
            ],
            "p1BossHitEvents": [{"targetID": 9, "boss": "龌勒卢斯", "timeMs": 125633}],
        }
        self.assertTrue(p1_silver_arrow_round_succeeded(arrow))

    def test_round_failed_without_hit_events_or_attribution(self):
        arrow = {
            "p1BossAttribution": [
                {"player": "义子", "hitBoss": False, "bosses": []},
                {"player": "杀杀孩", "hitBoss": False, "bosses": []},
            ],
            "p1BossHitEvents": [],
        }
        self.assertFalse(p1_silver_arrow_round_succeeded(arrow))

    def test_ray_hit_is_preserved_without_overwriting(self):
        marked = [{"targetID": 2, "player": "渊重音"}]
        ray_hit = [{"targetID": 2, "player": "渊重音", "bosses": ["龌勒卢斯"], "hitBoss": True}]
        hit_events = [{"targetID": 9, "boss": "龌勒卢斯", "timeMs": 125633}]

        attrs = finalize_p1_boss_attribution(marked, ray_hit, hit_events)

        self.assertEqual(attrs, ray_hit)


if __name__ == "__main__":
    unittest.main()
