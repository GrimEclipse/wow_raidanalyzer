import unittest

from boss_plugins.void_spire.crown_of_the_cosmos import (
    apply_global_death_exemption,
    analyze_voreluth_vulnerability_fade,
    build_passage_cliff_board,
    build_transition_death_board,
    corruption_stack_at,
    melurium_alive_in_arrow_snapshot,
    CORRUPTION_ID,
    P1_SHADOW_BINDING_ID,
    MELURIUM_EXPECTED_MS,
)
from tools.crown_single_fight_audit import (
    DEATH_COMPENSATION_ID,
    GRAVITY_COLLAPSE_DAMAGE_ID,
    SPELL,
    TERMINAL_GUARD_ID,
    build_gravity_rounds,
    build_void_death_healing,
)


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


class TransitionDeathCourtTests(unittest.TestCase):
    @staticmethod
    def death(index, phase):
        return {
            "player": f"玩家{index}",
            "role": "dps",
            "absoluteTime": 100_000 + index * 1_000,
            "time": f"01:{index:02d}",
            "phase": phase,
            "ability": "转阶段击飞" if phase == "P2.5" else "银锋箭",
            "abilityID": None if phase == "P2.5" else 1233649,
        }

    def test_p15_and_small_p25_window_are_counted(self):
        fight = {"startTime": 100_000}
        rows = build_transition_death_board(
            fight,
            [self.death(1, "P1.5"), self.death(2, "P2.5"), self.death(3, "P2.5")],
            transition_abandoned=False,
        )
        events = [event for row in rows for event in row["events"]]

        self.assertEqual({event["phase"] for event in events}, {"P1.5", "P2.5"})
        self.assertTrue(all(event["counted"] for event in events))
        p25_events = [event for event in events if event["phase"] == "P2.5"]
        self.assertTrue(all(event["transitionTeamDeathCount"] == 2 for event in p25_events))
        self.assertTrue(all("<8" in event["countReason"] for event in p25_events))

    def test_p25_window_with_eight_deaths_is_display_only(self):
        fight = {"startTime": 100_000}
        rows = build_transition_death_board(
            fight,
            [self.death(index, "P2.5") for index in range(1, 9)],
            transition_abandoned=False,
        )
        events = [event for row in rows for event in row["events"]]

        self.assertEqual(len(events), 8)
        self.assertTrue(all(event["counted"] is False for event in events))
        self.assertTrue(all(event["transitionTeamDeathCount"] == 8 for event in events))
        self.assertTrue(all("达到8人" in event["countReason"] for event in events))


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


class GravityDeathTriggerTests(unittest.TestCase):
    def test_dead_trigger_is_marked_and_not_attributed(self):
        fight = {"id": 5, "startTime": 100_000, "endTime": 200_000}
        actor_map = {1: "第一棒", 2: "死亡触发者"}
        debuffs = [
            {"type": "applydebuff", "abilityGameID": TERMINAL_GUARD_ID, "targetID": 1, "timestamp": 110_000},
            {"type": "applydebuff", "abilityGameID": TERMINAL_GUARD_ID, "targetID": 2, "timestamp": 110_050},
            {"type": "removedebuff", "abilityGameID": TERMINAL_GUARD_ID, "targetID": 1, "timestamp": 112_000},
            {"type": "removedebuff", "abilityGameID": TERMINAL_GUARD_ID, "targetID": 2, "timestamp": 113_000},
        ]
        deaths = [{
            "targetID": 2,
            "timestamp": 113_000,
            "killingAbilityGameID": GRAVITY_COLLAPSE_DAMAGE_ID,
        }]

        round_row = build_gravity_rounds(
            fight,
            actor_map,
            debuffs,
            deaths,
            {1: "melee-dps", 2: "range-dps"},
        )[0]

        self.assertTrue(round_row["breaks"][1]["deathTriggered"])
        self.assertTrue(round_row["deathTriggeredCollapse"])
        self.assertEqual(round_row["deathTriggeredPlayer"], "死亡触发者")
        self.assertEqual(round_row["violations"], [])
        self.assertIsNone(round_row["attributedPlayer"])
        self.assertFalse(round_row["counted"])
        self.assertIn("不作为归因人", round_row["exemptReason"])

    def test_gravity_compensation_under_eight_counts_as_effective_death(self):
        fight = {"id": 16, "startTime": 100_000, "endTime": 200_000}
        debuffs = [
            {"type": "applydebuff", "abilityGameID": TERMINAL_GUARD_ID, "targetID": 1, "timestamp": 110_000},
            {"type": "removedebuff", "abilityGameID": TERMINAL_GUARD_ID, "targetID": 1, "timestamp": 114_000},
            {"type": "applydebuff", "abilityGameID": DEATH_COMPENSATION_ID, "targetID": 9, "timestamp": 115_000},
        ]
        damage = [{
            "type": "damage",
            "abilityGameID": GRAVITY_COLLAPSE_DAMAGE_ID,
            "targetID": 9,
            "timestamp": 114_010,
            "amount": 150_000,
        }]

        round_row = build_gravity_rounds(
            fight,
            {1: "违规者", 9: "暗黑膏药"},
            debuffs,
            [],
            {1: "melee-dps", 9: "priest-healer"},
            damage,
        )[0]

        self.assertEqual(round_row["deathCount"], 0)
        self.assertEqual(round_row["compensationCount"], 1)
        self.assertEqual(round_row["effectiveDeathCount"], 1)
        self.assertEqual(round_row["compensationPlayers"], ["暗黑膏药"])
        self.assertEqual(round_row["attributedPlayer"], "违规者")
        self.assertTrue(round_row["counted"])

    def test_compensation_after_eighth_death_is_display_only(self):
        fight = {"id": 6, "startTime": 100_000, "endTime": 200_000}
        debuffs = [
            {"type": "applydebuff", "abilityGameID": TERMINAL_GUARD_ID, "targetID": 1, "timestamp": 110_000},
            {"type": "removedebuff", "abilityGameID": TERMINAL_GUARD_ID, "targetID": 1, "timestamp": 114_000},
            {"type": "applydebuff", "abilityGameID": DEATH_COMPENSATION_ID, "targetID": 9, "timestamp": 115_000},
        ]
        deaths = [
            {"targetID": 20 + index, "timestamp": 100_100 + index * 100, "killingAbilityGameID": 1}
            for index in range(8)
        ]
        damage = [{
            "type": "damage",
            "abilityGameID": GRAVITY_COLLAPSE_DAMAGE_ID,
            "targetID": 9,
            "timestamp": 114_010,
            "amount": 150_000,
        }]

        round_row = build_gravity_rounds(
            fight,
            {1: "违规者", 9: "暗黑膏药"},
            debuffs,
            deaths,
            {1: "melee-dps", 9: "priest-healer"},
            damage,
        )[0]

        self.assertEqual(round_row["compensationCount"], 0)
        self.assertEqual(round_row["effectiveDeathCount"], 0)
        self.assertFalse(round_row["compensations"][0]["underEightDeaths"])
        self.assertEqual(round_row["compensations"][0]["deathEventCountBeforeCompensation"], 8)
        self.assertFalse(round_row["counted"])


class VoreluthVulnerabilityFadeTests(unittest.TestCase):
    def test_multiple_fades_aggregated_per_fight_with_stacks(self):
        fight = {"id": 7, "startTime": 1_000_000, "endTime": 1_200_000}
        actor_map = {9: "龌勒卢斯"}
        actor_game_id = {9: 243811}
        debuffs = [
            {"type": "applydebuff", "abilityGameID": CORRUPTION_ID, "targetID": 9, "timestamp": 1_010_000, "stack": 1},
            {"type": "applydebuffstack", "abilityGameID": CORRUPTION_ID, "targetID": 9, "timestamp": 1_020_000, "stack": 2},
            {"type": "removedebuff", "abilityGameID": CORRUPTION_ID, "targetID": 9, "timestamp": 1_030_000},
            {"type": "applydebuff", "abilityGameID": CORRUPTION_ID, "targetID": 9, "timestamp": 1_040_000, "stack": 1},
            {"type": "applydebuffstack", "abilityGameID": CORRUPTION_ID, "targetID": 9, "timestamp": 1_045_000, "stack": 2},
            {"type": "applydebuffstack", "abilityGameID": CORRUPTION_ID, "targetID": 9, "timestamp": 1_050_000, "stack": 3},
            {"type": "removedebuff", "abilityGameID": CORRUPTION_ID, "targetID": 9, "timestamp": 1_060_000},
            {"type": "removedebuff", "abilityGameID": P1_SHADOW_BINDING_ID, "targetID": 9, "timestamp": 1_125_000},
        ]
        summary = analyze_voreluth_vulnerability_fade(fight, actor_map, actor_game_id, debuffs)
        self.assertIsNotNone(summary)
        self.assertEqual(summary["fadeCount"], 2)
        self.assertEqual(summary["stacks"], [2, 3])
        self.assertTrue(summary["counted"])
        self.assertTrue(summary["verdictCounted"])
        self.assertFalse(summary["displayOnly"])
        self.assertIn("2层", summary["text"])
        self.assertIn("3层", summary["text"])
        self.assertEqual(corruption_stack_at(debuffs, 9, 1_030_000), 2)
        self.assertEqual(corruption_stack_at(debuffs, 9, 1_060_000), 3)

        from boss_plugins.void_spire.crown_of_the_cosmos import build_voreluth_vulnerability_board
        rows, _ = build_voreluth_vulnerability_board(
            fight, actor_map, actor_game_id, debuffs, player_roles={1: "tank", 2: "tank", 3: "healer"},
        )
        # actor map needs tank names
        actor_map[1] = "坦克甲"
        actor_map[2] = "坦克乙"
        rows, summary2 = build_voreluth_vulnerability_board(
            fight, actor_map, actor_game_id, debuffs, player_roles={1: "tank", 2: "tank", 3: "healer"},
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["name"] for row in rows}, {"坦克甲", "坦克乙"})
        self.assertTrue(all(row.get("role") == "tank" for row in rows))
        self.assertTrue(all(not row.get("isSystem") for row in rows))
        self.assertEqual(rows[0]["hitCount"], 1)
        self.assertEqual(len(rows[0]["events"]), 1)
        self.assertEqual(len(rows[0]["events"][0]["fades"]), 2)
        self.assertIn("坦克甲", summary2["text"])

    def test_fade_after_binding_remove_is_ignored(self):
        fight = {"id": 1, "startTime": 0, "endTime": 200_000}
        actor_map = {9: "龌勒卢斯"}
        actor_game_id = {9: 254172}
        debuffs = [
            {"type": "applydebuff", "abilityGameID": CORRUPTION_ID, "targetID": 9, "timestamp": 10_000, "stack": 1},
            {"type": "removedebuff", "abilityGameID": P1_SHADOW_BINDING_ID, "targetID": 9, "timestamp": 50_000},
            {"type": "removedebuff", "abilityGameID": CORRUPTION_ID, "targetID": 9, "timestamp": 60_000},
        ]
        summary = analyze_voreluth_vulnerability_fade(fight, actor_map, actor_game_id, debuffs)
        self.assertIsNone(summary)

    def test_stack_tick_remove_is_not_full_fade(self):
        fight = {"id": 2, "startTime": 0, "endTime": 200_000}
        actor_map = {9: "龌勒卢斯"}
        actor_game_id = {9: 243811}
        debuffs = [
            {"type": "applydebuff", "abilityGameID": CORRUPTION_ID, "targetID": 9, "timestamp": 10_000, "stack": 1},
            {"type": "removedebuffstack", "abilityGameID": CORRUPTION_ID, "targetID": 9, "timestamp": 20_000, "stack": 0},
            {"type": "removedebuff", "abilityGameID": P1_SHADOW_BINDING_ID, "targetID": 9, "timestamp": 80_000},
        ]
        summary = analyze_voreluth_vulnerability_fade(fight, actor_map, actor_game_id, debuffs)
        self.assertIsNone(summary)

    def test_fade_after_first_silver_arrow_mark_is_ignored(self):
        fight = {"id": 23, "startTime": 0, "endTime": 220_000}
        actor_map = {9: "龌勒卢斯"}
        actor_game_id = {9: 243811}
        debuffs = [
            {"type": "applydebuff", "abilityGameID": CORRUPTION_ID, "targetID": 9, "timestamp": 90_000, "stack": 3},
            {"type": "applydebuff", "abilityGameID": 1233602, "targetID": 101, "timestamp": 26_000},
            {"type": "applydebuff", "abilityGameID": 1233602, "targetID": 102, "timestamp": 43_000},
            {"type": "applydebuff", "abilityGameID": 1233602, "targetID": 103, "timestamp": 62_000},
            {"type": "applydebuff", "abilityGameID": 1233602, "targetID": 104, "timestamp": 81_000},
            {"type": "applydebuff", "abilityGameID": 1233602, "targetID": 105, "timestamp": 99_000},
            {"type": "applydebuff", "abilityGameID": 1233602, "targetID": 106, "timestamp": 130_000},
            {"type": "applydebuff", "abilityGameID": CORRUPTION_ID, "targetID": 9, "timestamp": 105_000, "stack": 1},
            {"type": "removedebuff", "abilityGameID": CORRUPTION_ID, "targetID": 9, "timestamp": 124_000, "stack": 1},  # should count
            {"type": "applydebuff", "abilityGameID": CORRUPTION_ID, "targetID": 9, "timestamp": 130_100, "stack": 2},
            {"type": "removedebuff", "abilityGameID": CORRUPTION_ID, "targetID": 9, "timestamp": 130_500, "stack": 2},  # should be ignored (near 6th silver arrow)
            {"type": "removedebuff", "abilityGameID": P1_SHADOW_BINDING_ID, "targetID": 9, "timestamp": 150_000},
        ]
        summary = analyze_voreluth_vulnerability_fade(fight, actor_map, actor_game_id, debuffs)
        self.assertIsNotNone(summary)
        self.assertEqual(summary["fadeCount"], 1)
        self.assertEqual(summary["firstFadeTime"], "02:04")
        self.assertEqual(summary["firstFadeStack"], 1)


class SilverArrowHitEvidenceTests(unittest.TestCase):
    def test_boss_hit_events_count_as_round_success(self):
        attributions = [{"hitBoss": False}, {"hitBoss": False}]
        hit_events = [{"targetID": 9, "boss": "龌勒卢斯"}]
        round_success = any(row.get("hitBoss") for row in attributions) or bool(hit_events)
        self.assertTrue(round_success)

    def test_p1_arrow_rows_confirm_hit_covers_apply_remove_gap(self):
        from boss_plugins.void_spire.crown_of_the_cosmos import p1_arrow_rows_confirm_hit

        rows = [{
            "kind": "binding_removed",
            "target": "殆米阿尔",
            "time": "00:40",
            "expectedTime": "00:43",
            "markedPlayers": [{"id": 15, "name": "神奇大叔"}, {"id": 16, "name": "陈瀚"}],
        }]
        arrow = {
            "timeMs": 43_516,
            "markedPlayers": ["神奇大叔", "陈瀚"],
            "p1BossHitEvents": [],
            "p1BossAttribution": [{"hitBoss": False}, {"hitBoss": False}],
        }
        self.assertTrue(p1_arrow_rows_confirm_hit(rows, "殆米阿尔", arrow))
        self.assertFalse(p1_arrow_rows_confirm_hit(rows, "殁里乌姆", arrow))
        self.assertFalse(p1_arrow_rows_confirm_hit(rows, "殆米阿尔", {
            **arrow,
            "markedPlayers": ["其他人", "另一个人"],
        }))



class PassageCliffMistakeTests(unittest.TestCase):
    def test_mid_phase_cliff_counts_and_p1_transition_skipped(self):
        fight = {"id": 9, "startTime": 100_000, "endTime": 200_000}
        markers = {"p15Start": 150_000, "p2Start": 160_000, "p25Start": 180_000, "p3Start": 190_000}
        # before p15 = P1 (skip), between p15-p2 = P1.5 (skip), after p2 = P2 (count)
        deaths = [
            {"targetID": 1, "timestamp": 110_000, "killingAbilityGameID": None},  # P1 skip
            {"targetID": 2, "timestamp": 155_000, "killingAbilityGameID": None},  # P1.5 skip
            {"targetID": 4, "timestamp": 165_000, "killingAbilityGameID": None},  # P2 count
            {"targetID": 3, "timestamp": 170_000, "killingAbilityGameID": 123},   # non-cliff skip
        ]
        timeline = [
            {"player": "甲", "role": "melee-dps", "absoluteTime": 110_000, "time": "00:10", "phase": "P1", "ability": "坠崖", "abilityID": None},
            {"player": "乙", "role": "range-dps", "absoluteTime": 155_000, "time": "00:55", "phase": "P1.5", "ability": "坠崖", "abilityID": None},
            {"player": "丁", "role": "melee-dps", "absoluteTime": 165_000, "time": "01:05", "phase": "P2", "ability": "坠崖", "abilityID": None},
            {"player": "丙", "role": "tank", "absoluteTime": 170_000, "time": "01:10", "phase": "P2", "ability": "银锋箭", "abilityID": 123},
        ]
        rows = build_passage_cliff_board(fight, deaths, markers, timeline, {4: "melee-dps"}, "p2_team_collapse")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "丁")
        self.assertEqual(rows[0]["hitCount"], 1)
        self.assertTrue(rows[0]["events"][0]["counted"])

    def test_abandon_wave_cliffs_not_counted(self):
        fight = {"id": 10, "startTime": 0, "endTime": 60_000}
        markers = {}
        # 6 cliff deaths clustered = abandon wave under phase_abandon
        deaths = [{"targetID": i, "timestamp": 50_000 + i * 200, "killingAbilityGameID": None} for i in range(6)]
        timeline = [
            {"player": f"P{i}", "role": "dps", "absoluteTime": 50_000 + i * 200, "time": "00:50", "phase": "P1", "ability": "坠崖", "abilityID": None}
            for i in range(6)
        ]
        rows = build_passage_cliff_board(fight, deaths, markers, timeline, {}, "phase_abandon")
        self.assertEqual(rows, [])

    def test_dense_p2_cliff_cluster_exempts_even_within_first_eight(self):
        """Fight18 型：P1.5 先有机制减员，进 P2 后短时大团跳崖；前几名坠崖虽在第8死内也要豁免。"""
        fight = {"id": 18, "startTime": 0, "endTime": 200_000}
        markers = {"p15Start": 100_000, "p2Start": 150_000}
        deaths = [
            {"targetID": 1, "timestamp": 140_000, "killingAbilityGameID": 1243981},
            {"targetID": 2, "timestamp": 140_500, "killingAbilityGameID": 1243981},
            {"targetID": 3, "timestamp": 141_000, "killingAbilityGameID": 1243981},
            {"targetID": 4, "timestamp": 142_000, "killingAbilityGameID": 1246001},
            {"targetID": 5, "timestamp": 143_000, "killingAbilityGameID": 1246001},
        ]
        # P2 dense cliffs starting at death #6
        for i in range(8):
            deaths.append({"targetID": 10 + i, "timestamp": 158_000 + i * 300, "killingAbilityGameID": None})
        timeline = []
        for death in deaths:
            is_cliff = death.get("killingAbilityGameID") in {None, 3}
            timeline.append({
                "player": f"P{death['targetID']}",
                "role": "dps",
                "absoluteTime": death["timestamp"],
                "time": "02:58",
                "phase": "P1.5" if death["timestamp"] < 150_000 else "P2",
                "ability": "坠崖" if is_cliff else "银锋弹幕射击",
                "abilityID": death.get("killingAbilityGameID"),
            })
        rows = build_passage_cliff_board(fight, deaths, markers, timeline, {}, "phase_abandon")
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
