import unittest

from boss_plugins.venomous_abyss import coiledaltar


class CoiledAltarMechanicsTest(unittest.TestCase):
    def test_frontal_cone_filters_points_within_radius_and_angle(self):
        origin = (0.0, 0.0)
        facing = 0.0
        inside = (3000.0, 0.0)
        outside_angle = (-3000.0, 0.0)
        outside_range = (5000.0, 0.0)
        self.assertTrue(coiledaltar.in_frontal_cone(origin, facing, inside))
        self.assertFalse(coiledaltar.in_frontal_cone(origin, facing, outside_angle))
        self.assertFalse(coiledaltar.in_frontal_cone(origin, facing, outside_range))

    def test_phase_markers_follow_p2_intermission_and_p3_signals(self):
        fight = {"startTime": 1_000_000, "endTime": 1_540_000, "kill": False}
        casts = [
            {"timestamp": 1_192_693, "type": "begincast", "abilityGameID": coiledaltar.P2_SIGNAL_SPELL},
        ]
        enemy_buffs = [
            {"timestamp": 1_491_175, "type": "applybuff", "abilityGameID": 1304032},
            {"timestamp": 1_526_182, "type": "applybuff", "abilityGameID": coiledaltar.P3_SOULBOUND},
        ]
        markers = coiledaltar.build_phase_markers(fight, casts, enemy_buffs)
        keys = [row["key"] for row in markers]
        self.assertEqual(keys[:4], ["p1", "p2", "intermission", "p3"])
        self.assertEqual(markers[1]["signal"], "fear-bolt-fallback")

    def test_intermission_counts_leaked_souls_by_reclaim_essence(self):
        fight = {"startTime": 0, "endTime": 200_000, "kill": False}
        players = {10: {"id": 10, "name": "A", "classColor": "#fff", "role": "dps"}}
        markers = [{"key": "intermission", "label": "被夺取的容器", "timeMs": 100_000}]
        enemy_buffs = [{"timestamp": 100_000, "type": "applybuff", "abilityGameID": 1304032, "targetID": 1}]
        # 同一灵魂的 heal+cast 应去重为 1；另一灵魂再计 1
        heals = [
            {"timestamp": 110_000, "type": "heal", "abilityGameID": 1287718, "sourceID": 50, "targetID": 1, "amount": 300_000},
            {"timestamp": 125_000, "type": "heal", "abilityGameID": 1287718, "sourceID": 51, "targetID": 1, "amount": 300_000},
        ]
        casts = [
            {"timestamp": 110_050, "type": "cast", "abilityGameID": 1287718, "sourceID": 50, "targetID": 1},
        ]
        damage = [
            {"timestamp": 112_000, "type": "damage", "abilityGameID": 1287722, "targetID": 10, "amount": 50_000},
        ]
        result = coiledaltar.analyze_intermission(
            fight, enemy_buffs, damage, [], {1: "祖尔加", 50: "残片A", 51: "残片B", 10: "A"}, players, markers,
            heals=heals, casts=casts,
        )
        self.assertTrue(result["enabled"])
        self.assertEqual(result["leakedSoulCount"], 2)
        self.assertEqual(result["leakCount"], 2)
        self.assertEqual(result["reclaimHealTotal"], 600_000)
        self.assertEqual(len(result["spiritErasureSteps"]), 1)
        self.assertIn("收回精华", result["evidenceNote"])

        cast_only = coiledaltar.analyze_intermission(
            fight, enemy_buffs, [], [], {52: "残片C"}, {}, markers,
            heals=[], casts=[{"timestamp": 118_000, "type": "cast", "abilityGameID": 1287718, "sourceID": 52}],
        )
        self.assertEqual(cast_only["leakedSoulCount"], 1)
        self.assertEqual(cast_only["reclaimEvidenceSource"], "cast")

    def test_spirit_erasure_groups_raid_aoe_and_finds_friendly_stepper(self):
        fight = {"startTime": 0, "endTime": 200_000, "kill": False}
        players = {
            10: {"id": 10, "name": "A", "classColor": "#fff", "role": "dps"},
            11: {"id": 11, "name": "B", "classColor": "#fff", "role": "healer"},
            12: {"id": 12, "name": "C", "classColor": "#fff", "role": "dps"},
        }
        markers = [{"key": "intermission", "label": "被夺取的容器", "timeMs": 100_000}]
        enemy_buffs = [{"timestamp": 100_000, "type": "applybuff", "abilityGameID": 1304032, "targetID": 1}]
        # 同一脉冲打到 3 人，不能算 3 次踩片；踩片者是施加 1287722 的 B
        damage = [
            {"timestamp": 112_000, "type": "damage", "abilityGameID": 1287722, "sourceID": 25, "targetID": 10, "amount": 50_000},
            {"timestamp": 112_020, "type": "damage", "abilityGameID": 1287722, "sourceID": 25, "targetID": 11, "amount": 50_000},
            {"timestamp": 112_040, "type": "damage", "abilityGameID": 1287722, "sourceID": 25, "targetID": 12, "amount": 50_000},
            {"timestamp": 118_000, "type": "damage", "abilityGameID": 1287722, "sourceID": 25, "targetID": 10, "amount": 50_000},
            {"timestamp": 118_010, "type": "damage", "abilityGameID": 1287722, "sourceID": 25, "targetID": 11, "amount": 50_000},
        ]
        debuffs = [
            {"timestamp": 112_010, "type": "applydebuff", "abilityGameID": 1287722, "targetID": 11},
            {"timestamp": 118_000, "type": "applydebuffstack", "abilityGameID": 1287722, "targetID": 10},
        ]
        result = coiledaltar.analyze_intermission(
            fight, enemy_buffs, damage, debuffs,
            {1: "祖尔加", 25: "玛拉卡斯", 10: "A", 11: "B", 12: "C"},
            players, markers,
        )
        self.assertEqual(result["spiritErasureStepCount"], 2)
        self.assertEqual(len(result["spiritErasureSteps"]), 2)
        first, second = result["spiritErasureSteps"]
        self.assertEqual(first["hitCount"], 3)
        self.assertEqual(first["player"], "B")
        self.assertEqual(first["evidence"], "desecrator-debuff")
        self.assertEqual(second["hitCount"], 2)
        self.assertEqual(second["player"], "A")

        sourced = coiledaltar.analyze_intermission(
            fight, enemy_buffs,
            [{"timestamp": 112_000, "type": "damage", "abilityGameID": 1287722, "sourceID": 10, "targetID": 11, "amount": 1}],
            [],
            {1: "祖尔加", 10: "A", 11: "B"}, players, markers,
        )
        self.assertEqual(sourced["spiritErasureSteps"][0]["player"], "A")
        self.assertEqual(sourced["spiritErasureSteps"][0]["evidence"], "damage-source")

    def test_intermission_reports_survivor_potions_and_zuljan_damage(self):
        fight = {"startTime": 0, "endTime": 200_000, "kill": False}
        players = {
            10: {"id": 10, "name": "A", "classColor": "#fff", "role": "dps"},
            11: {"id": 11, "name": "B", "classColor": "#fff", "role": "dps"},
            12: {"id": 12, "name": "C", "classColor": "#fff", "role": "healer"},
            13: {"id": 13, "name": "Dead", "classColor": "#fff", "role": "dps"},
            14: {"id": 14, "name": "Rezzed", "classColor": "#fff", "role": "dps"},
            15: {"id": 15, "name": "Priest", "classColor": "#fff", "role": "range-healer"},
        }
        markers = [{"key": "intermission", "label": "被夺取的容器", "timeMs": 100_000}]
        enemy_buffs = [{"timestamp": 100_000, "type": "applybuff", "abilityGameID": 1304032, "targetID": 1}]
        result = coiledaltar.analyze_intermission(
            fight, enemy_buffs, [], [],
            {1: "祖尔加", 10: "A", 11: "B", 12: "C", 13: "Dead", 14: "Rezzed", 15: "Priest", 99: "水元素"},
            players, markers,
            friendly_casts=[
                {"timestamp": 101_000, "type": "cast", "abilityGameID": 1236616, "sourceID": 10},
                {"timestamp": 99_000, "type": "cast", "abilityGameID": 1236994, "sourceID": 12},
                {"timestamp": 99_500, "type": "cast", "abilityGameID": 1236994, "sourceID": 13},
                {"timestamp": 105_000, "type": "cast", "abilityGameID": 61999, "sourceID": 12, "targetID": 14},
            ],
            buffs=[
                {"timestamp": 102_000, "type": "applybuff", "abilityGameID": 1295132, "sourceID": 11, "targetID": 11},
            ],
            friendly_damage=[
                {"timestamp": 110_000, "type": "damage", "sourceID": 10, "targetID": 1, "amount": 80_000},
                {"timestamp": 111_000, "type": "damage", "sourceID": 11, "targetID": 1, "amount": 30_000},
                {"timestamp": 112_000, "type": "damage", "sourceID": 99, "targetID": 1, "amount": 20_000},
                {"timestamp": 113_000, "type": "damage", "sourceID": 12, "targetID": 1, "amount": 10_000},
                {"timestamp": 113_500, "type": "damage", "sourceID": 15, "targetID": 1, "amount": 8_000},
                {"timestamp": 114_000, "type": "damage", "sourceID": 10, "targetID": 25, "amount": 500_000},
                {"timestamp": 90_000, "type": "damage", "sourceID": 10, "targetID": 1, "amount": 9_000_000},
            ],
            deaths=[
                {"timestamp": 90_000, "type": "death", "targetID": 13},
                {"timestamp": 80_000, "type": "death", "targetID": 14},
            ],
            zuljan_id=1,
            actor_rows=[{"id": 99, "name": "水元素", "petOwner": 11}],
        )
        by_name = {row["player"]: row for row in result["survivors"]}
        self.assertEqual(set(by_name), {"A", "B", "Rezzed"})
        self.assertEqual(result["potionUsedCount"], 2)
        self.assertEqual(result["zuljanDamageTotal"], 130_000)
        self.assertEqual(by_name["A"]["potionName"], "圣光潜力")
        self.assertEqual(by_name["A"]["zuljanDamage"], 80_000)
        self.assertEqual(by_name["B"]["potionName"], "液态光泽")
        self.assertEqual(by_name["B"]["zuljanDamage"], 50_000)
        self.assertNotIn("C", by_name)
        self.assertNotIn("Priest", by_name)
        self.assertFalse(by_name["Rezzed"]["potionUsed"])
        self.assertEqual(by_name["Rezzed"]["zuljanDamage"], 0)
        self.assertEqual(result["survivors"][0]["player"], "A")

    def test_phase_p2_uses_zuljan_death_before_malacrass(self):
        fight = {"startTime": 0, "endTime": 400_000, "kill": False}
        enemy_deaths = [{"timestamp": 180_000, "type": "death", "targetID": 24}]
        casts = [
            {"timestamp": 181_000, "type": "begincast", "sourceID": 25, "abilityGameID": 1307184},
            {"timestamp": 190_000, "type": "begincast", "sourceID": 25, "abilityGameID": coiledaltar.P2_SIGNAL_SPELL},
        ]
        markers = coiledaltar.build_phase_markers(
            fight, casts, [], enemy_deaths=enemy_deaths, zuljan_id=24, malacrass_id=25,
        )
        self.assertEqual(markers[1]["key"], "p2")
        self.assertEqual(markers[1]["timeMs"], 180_000)
        self.assertEqual(markers[1]["signal"], "zuljan-death")

    def test_phase_p2_falls_back_to_malacrass_appear(self):
        fight = {"startTime": 0, "endTime": 400_000, "kill": False}
        casts = [
            {"timestamp": 200_000, "type": "cast", "sourceID": 25, "abilityGameID": 1285643},
        ]
        markers = coiledaltar.build_phase_markers(
            fight, casts, [], enemy_deaths=[], zuljan_id=24, malacrass_id=25,
        )
        self.assertEqual(markers[1]["key"], "p2")
        self.assertEqual(markers[1]["timeMs"], 200_000)
        self.assertEqual(markers[1]["signal"], "malacrass-appear")

    def test_gravebound_failures_require_gravebound_damage_kill(self):
        fight = {"startTime": 0, "endTime": 200_000, "kill": False}
        players = {
            10: {"id": 10, "name": "Tank", "classColor": "#fff", "role": "tank"},
            11: {"id": 11, "name": "Dps", "classColor": "#fff", "role": "dps"},
        }
        actor_map = {10: "Tank", 11: "Dps"}
        debuffs = [
            {"timestamp": 50_000, "type": "applydebuff", "abilityGameID": 1286837, "targetID": 10},
            {"timestamp": 80_000, "type": "removedebuff", "abilityGameID": 1286837, "targetID": 10},
            {"timestamp": 90_000, "type": "applydebuff", "abilityGameID": 1286837, "targetID": 11},
        ]
        deaths = [
            {"timestamp": 70_000, "type": "death", "targetID": 10, "killingAbilityGameID": 1308330},
            {"timestamp": 95_000, "type": "death", "targetID": 11, "killingAbilityGameID": 1297906},
        ]
        result = coiledaltar.analyze_gravebound_failures(
            fight, debuffs, deaths, actor_map, players, damage_events=[],
        )
        self.assertEqual([row["player"] for row in result["failures"]], ["Dps"])
        self.assertEqual(result["failures"][0]["deathAbilityID"], 1297906)
        self.assertTrue(result["failures"][0]["killedByGraveboundDamage"])

        overkill_only = coiledaltar.analyze_gravebound_failures(
            fight, debuffs,
            [{"timestamp": 95_000, "type": "death", "targetID": 11}],
            actor_map, players,
            damage_events=[{
                "timestamp": 95_000, "type": "damage", "abilityGameID": 1297906,
                "targetID": 11, "amount": 1, "overkill": 800,
            }],
        )
        self.assertEqual(overkill_only["failures"], [])

        empty = coiledaltar.analyze_gravebound_failures(
            fight, debuffs,
            [
                {"timestamp": 70_000, "type": "death", "targetID": 10, "killingAbilityGameID": 1286837},
                {"timestamp": 95_000, "type": "death", "targetID": 11, "killingAbilityGameID": 1, "extraAbilityGameID": 1286837},
            ],
            actor_map, players, damage_events=[],
        )
        self.assertEqual(empty["failures"], [])
        fight = {"startTime": 0, "endTime": 300_000, "kill": False}
        players = {
            10: {"id": 10, "name": "Healer", "classColor": "#fff", "role": "healer"},
            11: {"id": 11, "name": "Mage", "classColor": "#fff", "role": "dps"},
        }
        actor_map = {10: "Healer", 11: "Mage"}
        markers = [{"key": "p2", "label": "P2", "timeMs": 0}]
        casts = [{"timestamp": 100_000, "type": "cast", "abilityGameID": 1285643}]
        debuffs = [
            {"timestamp": 100_500, "type": "applydebuff", "abilityGameID": 1297445, "targetID": 10},
            {"timestamp": 104_000, "type": "removedebuff", "abilityGameID": 1297445, "targetID": 10},
        ]
        friendly_damage = [
            {"timestamp": 102_000, "type": "damage", "abilityGameID": 1, "sourceID": 11, "targetID": 10, "amount": 5000},
        ]
        result = coiledaltar.analyze_dreadmarch(
            fight, casts, debuffs, [], friendly_damage, [], actor_map, players, markers,
        )
        self.assertEqual(result["applications"][0]["rescued"], True)
        self.assertEqual(result["applications"][0]["failed"], False)
        self.assertNotIn("friendlyHitCount", result["applications"][0])
        self.assertFalse(result["applications"][0]["hitManifestation"])
        self.assertEqual(result["applications"][0]["triggerKind"], "boss-cast")

    def test_dreadmarch_post_rescue_apply_counts_as_manifest_collision(self):
        fight = {"startTime": 0, "endTime": 400_000, "kill": False}
        players = {
            10: {"id": 10, "name": "A", "classColor": "#fff", "role": "dps"},
            11: {"id": 11, "name": "B", "classColor": "#fff", "role": "dps"},
            12: {"id": 12, "name": "C", "classColor": "#fff", "role": "dps"},
        }
        actor_map = {10: "A", 11: "B", 12: "C"}
        markers = [{"key": "p2", "label": "P2", "timeMs": 0}]
        casts = [
            {"timestamp": 100_000, "type": "cast", "abilityGameID": 1285643},
            {"timestamp": 160_000, "type": "cast", "abilityGameID": 1285643},
        ]
        debuffs = [
            # 初始点名
            {"timestamp": 100_500, "type": "applydebuff", "abilityGameID": 1297445, "targetID": 10},
            {"timestamp": 100_600, "type": "applydebuff", "abilityGameID": 1297445, "targetID": 11},
            {"timestamp": 108_000, "type": "removedebuff", "abilityGameID": 1297445, "targetID": 10},  # 首次救人
            # 救人后、下一轮释放前：C 被心控 + 凝视变化
            {"timestamp": 120_000, "type": "applydebuff", "abilityGameID": 1285911, "targetID": 12, "sourceID": 88},
            {"timestamp": 121_000, "type": "applydebuff", "abilityGameID": 1297445, "targetID": 12},
            {"timestamp": 130_000, "type": "removedebuff", "abilityGameID": 1297445, "targetID": 12},
            {"timestamp": 140_000, "type": "removedebuff", "abilityGameID": 1297445, "targetID": 11},
            # 第二轮 Boss 点名
            {"timestamp": 160_500, "type": "applydebuff", "abilityGameID": 1297445, "targetID": 10},
            {"timestamp": 170_000, "type": "removedebuff", "abilityGameID": 1297445, "targetID": 10},
        ]
        result = coiledaltar.analyze_dreadmarch(
            fight, casts, debuffs, [], [], [], actor_map, players, markers,
        )
        by_player_time = {(row["player"], row["appliedTimeMs"]): row for row in result["applications"]}
        self.assertFalse(by_player_time[("A", 100_500)]["hitManifestation"])
        self.assertFalse(by_player_time[("B", 100_600)]["hitManifestation"])
        collision = by_player_time[("C", 121_000)]
        self.assertTrue(collision["hitManifestation"])
        self.assertEqual(collision["triggerKind"], "manifest-collision")
        self.assertTrue(collision["fixationDebuffChanged"])
        self.assertEqual(result["manifestCollisionCount"], 1)
        self.assertEqual(result["rounds"][0]["manifestCollisionCount"], 1)
        self.assertEqual(result["rounds"][0]["targetCount"], 2)  # 初始点名不含撞具象
        self.assertFalse(result["useMalevolentResonance"])  # 默认非史诗
        self.assertIsNone(collision["manifestCollisionDebuff"])

        mythic_fight = {**fight, "difficulty": 5}
        mythic = coiledaltar.analyze_dreadmarch(
            mythic_fight, casts, debuffs + [
                {"timestamp": 121_100, "type": "applydebuff", "abilityGameID": 1310744, "targetID": 12},
            ], [], [], [], actor_map, players, markers,
        )
        self.assertTrue(mythic["useMalevolentResonance"])
        mythic_hit = next(row for row in mythic["applications"] if row["player"] == "C" and row["hitManifestation"])
        self.assertTrue(mythic_hit["manifestCollisionDebuff"])

    def test_manifest_instance_resolution_uses_actor_game_id(self):
        catalog = coiledaltar.build_actor_catalog([
            {"id": 42, "name": "Manifestation of Dread", "gameID": coiledaltar.MANIFEST_NPC_GAME_ID, "type": "NPC"},
        ])
        row = coiledaltar.resolve_manifest_instance(42, 7, catalog)
        self.assertTrue(row["isManifestNpc"])
        self.assertEqual(row["sourceInstance"], 7)

    def test_manifest_position_uses_npc_cast_coordinates(self):
        index = coiledaltar.build_npc_position_index([
            {
                "timestamp": 200_000,
                "type": "cast",
                "abilityGameID": coiledaltar.MANIFEST_CAST,
                "sourceID": 88,
                "sourceInstance": 2,
                "x": 1200.0,
                "y": 3400.0,
            },
        ])
        position = coiledaltar._position_sample_npc(index, 88, 2, 200_100)
        self.assertIsNotNone(position)
        self.assertEqual(position["x"], 1200.0)
        self.assertEqual(position["y"], 3400.0)
        self.assertTrue(position["positionReliable"])

    def test_npc_index_uses_fixation_cast_and_debuff_source_resources(self):
        index = coiledaltar.build_npc_position_index([
            {
                "timestamp": 200_000,
                "type": "cast",
                "abilityGameID": coiledaltar.FIXATION,
                "sourceID": 88,
                "sourceInstance": 2,
                "targetID": 10,
                "x": 9000.0,
                "y": 9000.0,
                "sourceResources": {"x": 1200.0, "y": 3400.0, "facing": 0},
            },
            {
                "timestamp": 200_050,
                "type": "applydebuff",
                "abilityGameID": coiledaltar.FIXATION,
                "sourceID": 88,
                "sourceInstance": 2,
                "targetID": 10,
                "x": 9100.0,
                "y": 9100.0,
                "sourceResources": {"x": 1250.0, "y": 3450.0, "facing": 0},
            },
        ])
        rows = index[(88, 2)]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["x"], 1200.0)
        self.assertEqual(rows[1]["x"], 1250.0)
        self.assertNotEqual(rows[0]["x"], 9000.0)

    def test_npc_index_does_not_use_manifest_as_damage_source(self):
        index = coiledaltar.build_npc_position_index([
            {
                "timestamp": 200_000,
                "type": "damage",
                "sourceID": 88,
                "sourceInstance": 2,
                "targetID": 10,
                "x": 9000.0,
                "y": 9000.0,
                "sourceResources": {"x": 1200.0, "y": 3400.0, "facing": 0},
            },
        ])
        self.assertIsNone(coiledaltar._position_last_at_or_before(index, 88, 2, 200_000))

    def test_npc_index_falls_back_when_incoming_damage_has_no_instance(self):
        index = coiledaltar.build_npc_position_index([
            {
                "timestamp": 205_000,
                "type": "damage",
                "sourceID": 10,
                "targetID": 88,
                "x": 1500.0,
                "y": 2500.0,
            },
        ])
        position = coiledaltar._position_last_at_or_before(index, 88, 2, 210_000)
        self.assertIsNotNone(position)
        self.assertEqual(position["x"], 1500.0)
        self.assertEqual(position["y"], 2500.0)

    def test_npc_index_ignores_polluted_cast_xy_toward_player(self):
        index = coiledaltar.build_npc_position_index([
            {
                "timestamp": 200_000,
                "type": "cast",
                "sourceID": 88,
                "sourceInstance": 2,
                "targetID": 10,
                "x": 9000.0,
                "y": 9000.0,
                "sourceResources": {"x": 1200.0, "y": 3400.0, "facing": 0},
            },
            {
                "timestamp": 201_000,
                "type": "cast",
                "sourceID": 88,
                "sourceInstance": 2,
                "targetID": 10,
                "x": 9100.0,
                "y": 9100.0,
            },
        ])
        rows = index[(88, 2)]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["x"], 1200.0)
        self.assertEqual(rows[0]["y"], 3400.0)

    def test_active_fixations_before_cast_and_clear_classification(self):
        points = [
            {"applyTimeMs": 100_000, "removeTimeMs": 150_500, "position": {"x": 1, "y": 1}},
            {"applyTimeMs": 100_000, "removeTimeMs": 200_000, "position": {"x": 2, "y": 2}},
            {"applyTimeMs": 160_000, "removeTimeMs": None, "position": {"x": 3, "y": 3}},
            {"applyTimeMs": 90_000, "removeTimeMs": 140_000, "position": {"x": 4, "y": 4}},
        ]
        active = coiledaltar.active_fixations_before_cast(points, 150_000, 0)
        self.assertEqual(len(active), 2)
        self.assertEqual(active[0]["position"]["x"], 1)
        self.assertEqual(active[1]["position"]["x"], 2)

        # P2 已消除的具象不应进入 P3 凋零撕裂窗口
        p2_cleared = [
            {
                "kind": "manifestation",
                "applyTimeMs": 120_000,
                "removeTimeMs": 180_000,
                "despawnTimeMs": 180_000,
                "lastSeenMs": 180_000,
                "position": {"x": 9, "y": 9},
            },
            {
                "kind": "manifestation",
                "applyTimeMs": 220_000,
                "removeTimeMs": None,
                "despawnTimeMs": 400_000,
                "lastSeenMs": 400_000,
                "position": {"x": 8, "y": 8},
            },
        ]
        p3_active = coiledaltar.active_fixations_before_cast(p2_cleared, 300_000, 0)
        self.assertEqual(len(p3_active), 1)
        self.assertEqual(p3_active[0]["position"]["x"], 8)

        # 仅有 despawn、无 remove 时也要排除已消失实例
        despawn_only = [{
            "applyTimeMs": 100_000,
            "removeTimeMs": None,
            "despawnTimeMs": 160_000,
            "position": {"x": 7, "y": 7},
        }]
        self.assertEqual(coiledaltar.active_fixations_before_cast(despawn_only, 200_000, 0), [])

        cleared = coiledaltar.classify_fixation_after_sever(
            {"removeTimeMs": 150_800}, 150_000, 0, in_cone=True,
        )
        self.assertTrue(cleared["debuffCleared"])
        self.assertFalse(cleared["uncleared"])
        self.assertEqual(cleared["clearOutcome"], "cleared")

        missed = coiledaltar.classify_fixation_after_sever(
            {"removeTimeMs": 200_000}, 150_000, 0, in_cone=True,
        )
        self.assertTrue(missed["uncleared"])
        self.assertEqual(missed["clearOutcome"], "missed-in-cone")

        outside = coiledaltar.classify_fixation_after_sever(
            {"removeTimeMs": None}, 150_000, 0, in_cone=False,
        )
        self.assertTrue(outside["uncleared"])
        self.assertEqual(outside["clearOutcome"], "outside-remain")
        # 旧名仍可用
        self.assertTrue(
            coiledaltar.classify_fixation_after_soul_sever(
                {"removeTimeMs": 150_800}, 150_000, 0, in_cone=True,
            )["debuffCleared"]
        )

    def test_manifestation_includes_player_and_npc_positions(self):
        fight = {"startTime": 0, "endTime": 400_000, "kill": False}
        players = {10: {"id": 10, "name": "Hunter", "classColor": "#fff", "role": "dps"}}
        catalog = coiledaltar.build_actor_catalog([
            {"id": 88, "name": "恐惧具象", "gameID": coiledaltar.MANIFEST_NPC_GAME_ID, "type": "NPC"},
        ])
        npc_index = coiledaltar.build_npc_position_index([
            {
                "timestamp": 200_000,
                "type": "cast",
                "sourceID": 88,
                "sourceInstance": 2,
                "targetID": 10,
                "x": 9000.0,
                "y": 9000.0,
                "sourceResources": {"x": 3000.0, "y": 4000.0},
            },
        ])
        player_index = coiledaltar.build_position_index([
            {"timestamp": 200_000, "type": "cast", "sourceID": 10, "x": 1500.0, "y": 1600.0},
        ])
        result = coiledaltar.analyze_manifestations(
            fight,
            [
                {
                    "timestamp": 200_000,
                    "type": "applydebuff",
                    "abilityGameID": 1285911,
                    "targetID": 10,
                    "sourceID": 88,
                    "sourceInstance": 2,
                },
                {
                    "timestamp": 220_000,
                    "type": "removedebuff",
                    "abilityGameID": 1285911,
                    "targetID": 10,
                    "sourceID": 88,
                    "sourceInstance": 2,
                },
            ],
            npc_index,
            {10: "Hunter"},
            players,
            catalog,
            [{"key": "p2", "label": "P2", "timeMs": 0}],
            position_index=player_index,
        )
        row = result["fixations"][0]
        self.assertEqual(row["manifestPosition"]["x"], 3000.0)
        self.assertEqual(row["manifestPosition"]["y"], 4000.0)
        self.assertEqual(row["playerPosition"]["x"], 1500.0)
        self.assertEqual(row["playerPosition"]["y"], 1600.0)
        self.assertEqual(result["activePoints"][0]["position"]["x"], 3000.0)
        self.assertNotEqual(result["activePoints"][0]["position"]["x"], 9000.0)

    def test_manifestation_position_uses_incoming_damage_coordinates(self):
        fight = {"startTime": 0, "endTime": 400_000, "kill": False}
        players = {10: {"id": 10, "name": "Hunter", "classColor": "#fff", "role": "dps"}}
        catalog = coiledaltar.build_actor_catalog([
            {"id": 88, "name": "恐惧具象", "gameID": coiledaltar.MANIFEST_NPC_GAME_ID, "type": "NPC"},
        ])
        npc_index = coiledaltar.build_npc_position_index([
            {
                "timestamp": 205_000,
                "type": "damage",
                "sourceID": 10,
                "targetID": 88,
                "targetInstance": 2,
                "x": 9100.0,
                "y": 9100.0,
                "targetResources": {"x": 3300.0, "y": 4400.0},
            },
        ])
        result = coiledaltar.analyze_manifestations(
            fight,
            [{
                "timestamp": 200_000,
                "type": "applydebuff",
                "abilityGameID": 1285911,
                "targetID": 10,
                "sourceID": 88,
                "sourceInstance": 2,
            }],
            npc_index,
            {10: "Hunter"},
            players,
            catalog,
            [{"key": "p2", "label": "P2", "timeMs": 0}],
        )
        self.assertEqual(result["fixations"][0]["manifestPosition"]["x"], 3300.0)
        self.assertEqual(result["fixations"][0]["manifestPosition"]["y"], 4400.0)
        self.assertEqual(result["activePoints"][0]["player"], "Hunter")

    def test_manifestation_without_coords_still_tracks_uncleared_players(self):
        fight = {"startTime": 0, "endTime": 400_000, "kill": False}
        players = {10: {"id": 10, "name": "Hunter", "classColor": "#fff", "role": "dps"}}
        catalog = coiledaltar.build_actor_catalog([
            {"id": 88, "name": "恐惧具象", "gameID": coiledaltar.MANIFEST_NPC_GAME_ID, "type": "NPC"},
        ])
        result = coiledaltar.analyze_manifestations(
            fight,
            [
                {
                    "timestamp": 100_000,
                    "type": "applydebuff",
                    "abilityGameID": 1285911,
                    "targetID": 10,
                    "sourceID": 88,
                    "sourceInstance": 1,
                },
                {
                    "timestamp": 250_000,
                    "type": "removedebuff",
                    "abilityGameID": 1285911,
                    "targetID": 10,
                    "sourceID": 88,
                    "sourceInstance": 1,
                },
            ],
            {},
            {10: "Hunter"},
            players,
            catalog,
            [{"key": "p2", "label": "P2", "timeMs": 0}],
        )
        self.assertEqual(len(result["activePoints"]), 1)
        self.assertIsNone(result["activePoints"][0]["manifestPosition"])
        soul = coiledaltar.analyze_soul_sever(
            fight,
            [{"timestamp": 150_000, "type": "cast", "abilityGameID": 1286620, "sourceID": 25}],
            [],
            {},
            {10: "Hunter", 25: "玛拉卡斯"},
            [{"key": "p2", "label": "P2", "timeMs": 0}],
            result["activePoints"],
        )
        round_row = soul["rounds"][0]
        self.assertEqual(round_row["unclearedCount"], 1)
        self.assertEqual(round_row["unclearedManifestations"][0]["player"], "Hunter")
        self.assertEqual(round_row["nearbyPoints"][0]["clearOutcome"], "outside-remain")

    def test_gloombomb_uses_debuff_remove_position(self):
        fight = {"startTime": 0, "endTime": 300_000, "kill": False}
        players = {10: {"id": 10, "name": "Mage", "classColor": "#fff", "role": "dps"}}
        index = coiledaltar.build_position_index([
            {"timestamp": 100_000, "type": "cast", "sourceID": 10, "x": 1000.0, "y": 1000.0},
            {"timestamp": 106_000, "type": "cast", "sourceID": 10, "x": 5000.0, "y": 5000.0},
        ])
        result = coiledaltar.analyze_gloombomb(
            fight,
            [{"timestamp": 100_000, "type": "cast", "abilityGameID": 1286895}],
            [
                {"timestamp": 100_200, "type": "applydebuff", "abilityGameID": 1310881, "targetID": 10},
                {"timestamp": 106_000, "type": "removedebuff", "abilityGameID": 1310881, "targetID": 10},
            ],
            index,
            {10: "Mage"},
            players,
            [{"key": "p2", "label": "P2", "timeMs": 0}],
        )
        target = result["rounds"][0]["targets"][0]
        self.assertEqual(target["position"]["x"], 5000.0)
        self.assertEqual(target["position"]["y"], 5000.0)
        self.assertEqual(target["explodeTimeMs"], 106_000)

    def test_gloombomb_flags_unnamed_players_inside_radius_with_gravebound(self):
        fight = {"startTime": 0, "endTime": 300_000, "kill": False}
        players = {
            10: {"id": 10, "name": "Mage", "classColor": "#fff", "role": "dps"},
            11: {"id": 11, "name": "Priest", "classColor": "#fff", "role": "healer"},
            12: {"id": 12, "name": "Hunter", "classColor": "#fff", "role": "dps"},
            13: {"id": 13, "name": "Rogue", "classColor": "#fff", "role": "dps"},
            14: {"id": 14, "name": "Warlock", "classColor": "#fff", "role": "dps"},
        }
        index = coiledaltar.build_position_index([
            {"timestamp": 106_000, "type": "cast", "sourceID": 10, "x": 0.0, "y": 0.0},
            {"timestamp": 106_000, "type": "cast", "sourceID": 11, "x": 800.0, "y": 0.0},
            {"timestamp": 106_000, "type": "cast", "sourceID": 12, "x": 1_600.0, "y": 0.0},
            {"timestamp": 106_000, "type": "cast", "sourceID": 13, "x": 4_000.0, "y": 0.0},
            {"timestamp": 106_000, "type": "cast", "sourceID": 14, "x": 900.0, "y": 0.0},
        ])
        result = coiledaltar.analyze_gloombomb(
            fight,
            [{"timestamp": 100_000, "type": "cast", "abilityGameID": 1286895}],
            [
                {"timestamp": 100_200, "type": "applydebuff", "abilityGameID": 1310881, "targetID": 10},
                {"timestamp": 100_300, "type": "applydebuff", "abilityGameID": 1310881, "targetID": 14},
                {"timestamp": 106_000, "type": "removedebuff", "abilityGameID": 1310881, "targetID": 10},
                {"timestamp": 106_000, "type": "removedebuff", "abilityGameID": 1310881, "targetID": 14},
                {"timestamp": 106_080, "type": "applydebuff", "abilityGameID": 1286837, "targetID": 10},
                {"timestamp": 106_100, "type": "applydebuff", "abilityGameID": 1286837, "targetID": 11},
                {"timestamp": 106_100, "type": "applydebuff", "abilityGameID": 1286837, "targetID": 14},
            ],
            index,
            {10: "Mage", 11: "Priest", 12: "Hunter", 13: "Rogue", 14: "Warlock"},
            players,
            [{"key": "p2", "label": "P2", "timeMs": 0}],
        )
        round_row = result["rounds"][0]
        nearby_names = {row["player"] for row in round_row["nearbyUnnamed"]}
        collateral_names = {row["player"] for row in round_row["collateralHits"]}
        self.assertIn("Priest", nearby_names)
        self.assertIn("Hunter", nearby_names)
        self.assertNotIn("Rogue", nearby_names)
        self.assertNotIn("Warlock", nearby_names)
        self.assertNotIn("Mage", nearby_names)
        self.assertEqual(collateral_names, {"Priest"})
        self.assertEqual(round_row["collateralCount"], 1)
        self.assertTrue(round_row["failed"])
        priest = next(row for row in round_row["nearbyUnnamed"] if row["player"] == "Priest")
        hunter = next(row for row in round_row["nearbyUnnamed"] if row["player"] == "Hunter")
        self.assertTrue(priest["receivedGravebound"])
        self.assertFalse(hunter["receivedGravebound"])
        self.assertLess(priest["distanceYards"], coiledaltar.GLOOMBOMB_RADIUS_YARDS)
        self.assertTrue(any(pair["tooClose"] for pair in round_row["tooClosePairs"]))

    def test_eternal_nightfall_reports_interrupt_without_shield_hit_counts(self):
        fight = {"startTime": 0, "endTime": 400_000, "kill": False}
        players = {
            10: {"id": 10, "name": "Mage", "classColor": "#fff", "role": "dps"},
            11: {"id": 11, "name": "Warrior", "classColor": "#fff", "role": "dps"},
        }
        result = coiledaltar.analyze_eternal_nightfall(
            fight,
            [{"timestamp": 100_000, "type": "begincast", "sourceID": 25, "abilityGameID": 1286918}],
            [
                {"timestamp": 100_000, "type": "applybuff", "abilityGameID": 1286912, "targetID": 25},
                {"timestamp": 105_400, "type": "removebuff", "abilityGameID": 1286912, "targetID": 25},
            ],
            [{"timestamp": 106_000, "type": "interrupt", "sourceID": 11, "abilityGameID": 6552, "extraAbilityGameID": 1286918}],
            {10: "Mage", 11: "Warrior", 25: "玛拉卡斯", 99: "水元素"},
            players=players,
            actor_rows=[{"id": 99, "name": "水元素", "petOwner": 10}],
        )
        round_row = result["rounds"][0]
        self.assertTrue(round_row["shieldRemoved"])
        self.assertNotIn("shieldDamageByPlayer", round_row)
        self.assertNotIn("shieldDamageTotal", round_row)
        self.assertEqual(round_row["phase"], "p1")
        self.assertTrue(round_row["interrupted"])
        self.assertEqual(round_row["interruptSource"], "Warrior")
        self.assertEqual(round_row["interruptPlayer"]["player"], "Warrior")
        self.assertEqual(round_row["interruptSpellID"], 6552)

    def test_eternal_nightfall_phase_follows_markers(self):
        fight = {"startTime": 0, "endTime": 700_000, "kill": False}
        result = coiledaltar.analyze_eternal_nightfall(
            fight,
            [
                {"timestamp": 100_000, "type": "begincast", "sourceID": 25, "abilityGameID": 1286918},
                {"timestamp": 600_000, "type": "begincast", "sourceID": 25, "abilityGameID": 1286918},
            ],
            [
                {"timestamp": 100_000, "type": "applybuff", "abilityGameID": 1286912, "targetID": 25},
                {"timestamp": 105_000, "type": "removebuff", "abilityGameID": 1286912, "targetID": 25},
                {"timestamp": 600_000, "type": "applybuff", "abilityGameID": 1286912, "targetID": 25},
                {"timestamp": 605_000, "type": "removebuff", "abilityGameID": 1286912, "targetID": 25},
            ],
            [],
            {25: "玛拉卡斯"},
            markers=[
                {"key": "p1", "label": "P1", "timeMs": 0},
                {"key": "p2", "label": "P2", "timeMs": 80_000},
                {"key": "intermission", "label": "转阶段", "timeMs": 500_000},
                {"key": "p3", "label": "P3", "timeMs": 540_000},
            ],
        )
        self.assertEqual([row["phase"] for row in result["rounds"]], ["p2", "p3"])

    def test_eternal_nightfall_does_not_count_shield_hit_ticks(self):
        fight = {"startTime": 0, "endTime": 400_000, "kill": False}
        players = {10: {"id": 10, "name": "Mage", "classColor": "#fff", "role": "dps"}}
        result = coiledaltar.analyze_eternal_nightfall(
            fight,
            [{"timestamp": 200_000, "type": "begincast", "sourceID": 25, "abilityGameID": 1286918}],
            [
                {"timestamp": 200_000, "type": "applybuff", "abilityGameID": 1286912, "targetID": 25},
                {"timestamp": 205_000, "type": "removebuff", "abilityGameID": 1286912, "targetID": 25},
            ],
            [],
            {10: "Mage", 25: "玛拉卡斯"},
            players=players,
            friendly_damage=[
                {"timestamp": 202_000, "type": "damage", "sourceID": 10, "targetID": 25, "amount": 12_000},
                {"timestamp": 203_000, "type": "damage", "sourceID": 10, "targetID": 25, "amount": 8_000},
            ],
            shield_target_id=25,
        )
        round_row = result["rounds"][0]
        self.assertTrue(round_row["shieldRemoved"])
        self.assertNotIn("shieldDamageByPlayer", round_row)
        self.assertNotIn("hitCount", round_row)

    def test_eternal_nightfall_counts_shield_remove_after_12s(self):
        fight = {"startTime": 0, "endTime": 400_000, "kill": False}
        players = {11: {"id": 11, "name": "Warrior", "classColor": "#fff", "role": "dps"}}
        result = coiledaltar.analyze_eternal_nightfall(
            fight,
            [{"timestamp": 200_000, "type": "begincast", "sourceID": 25, "abilityGameID": 1286918}],
            [
                {"timestamp": 200_000, "type": "applybuff", "abilityGameID": 1286912, "targetID": 25},
                {"timestamp": 201_000, "type": "removebuffstack", "abilityGameID": 1286912, "targetID": 25},
                {"timestamp": 214_272, "type": "removebuff", "abilityGameID": 1286912, "targetID": 25},
            ],
            [
                {"timestamp": 205_000, "type": "interrupt", "sourceID": 10, "abilityGameID": 1766, "extraAbilityGameID": 1286918},
                {"timestamp": 215_000, "type": "interrupt", "sourceID": 11, "abilityGameID": 6552, "extraAbilityGameID": 1286918},
            ],
            {10: "Rogue", 11: "Warrior", 25: "玛拉卡斯"},
            players=players,
            shield_target_id=25,
        )
        round_row = result["rounds"][0]
        self.assertTrue(round_row["shieldRemoved"])
        self.assertEqual(round_row["shieldRemoveTime"], coiledaltar.fmt_ms(214_272))
        self.assertTrue(round_row["interrupted"])
        self.assertEqual(round_row["interruptSource"], "Warrior")
        self.assertEqual(round_row["interruptSpellID"], 6552)

    def test_eternal_nightfall_interrupt_from_friendly_casts(self):
        fight = {"startTime": 0, "endTime": 400_000, "kill": False}
        players = {10: {"id": 10, "name": "Rogue", "classColor": "#fff", "role": "dps"}}
        result = coiledaltar.analyze_eternal_nightfall(
            fight,
            [{"timestamp": 100_000, "type": "begincast", "sourceID": 25, "abilityGameID": 1286918}],
            [
                {"timestamp": 100_000, "type": "applybuff", "abilityGameID": 1286912, "targetID": 25},
                {"timestamp": 106_000, "type": "removebuff", "abilityGameID": 1286912, "targetID": 25},
            ],
            [],
            {10: "Rogue", 25: "玛拉卡斯"},
            players=players,
            shield_target_id=25,
            friendly_casts=[
                {"timestamp": 106_400, "type": "interrupt", "sourceID": 10, "abilityGameID": 1766, "extraAbilityGameID": 1286918},
            ],
        )
        round_row = result["rounds"][0]
        self.assertTrue(round_row["interrupted"])
        self.assertEqual(round_row["interruptPlayer"]["player"], "Rogue")
        self.assertEqual(round_row["interruptSpellID"], 1766)

    def test_sever_cone_origin_uses_boss_current_position(self):
        index = coiledaltar.build_position_index([
            {
                "timestamp": 100_000,
                "type": "damage",
                "abilityGameID": 1,
                "sourceID": 24,
                "targetID": 10,
                "x": 9000.0,
                "y": 9000.0,
                "facing": 0,
            },
        ])
        cast = {
            "timestamp": 100_000,
            "type": "cast",
            "abilityGameID": 1299684,
            "sourceID": 24,
            "targetID": 10,
            "x": 1000.0,
            "y": 2000.0,
            "sourceResources": {"x": 1500.0, "y": 2500.0, "facing": 0},
        }
        origin_index = coiledaltar.build_caster_self_position_index([cast], {24})
        origin, facing, state, inferred, *_ = coiledaltar.resolve_caster_origin_facing(
            index, 24, 24, 100_000,
            origin_actor_id=24,
            origin_index=origin_index,
            cast_event=cast,
            target_id=10,
        )
        self.assertEqual(origin, (1500.0, 2500.0))
        self.assertEqual(state["positionRule"], "cast-sourceResources")
        self.assertNotEqual(origin, coiledaltar.arena_center_units())
        polluted, *_ = coiledaltar.resolve_caster_origin_facing(index, 24, 24, 100_000, origin_actor_id=24)
        self.assertIsNone(polluted)

    def test_caster_index_uses_target_resources_when_boss_is_hit(self):
        origin_index = coiledaltar.build_caster_self_position_index([
            {
                "timestamp": 100_000,
                "type": "damage",
                "sourceID": 10,
                "targetID": 24,
                "x": 9000.0,
                "y": 9000.0,
                "targetResources": {"x": 3200.0, "y": 116_100.0, "facing": 1.2},
            },
        ], {24})
        origin, facing, state, inferred, *_ = coiledaltar.resolve_caster_origin_facing(
            {}, 24, 24, 100_000,
            origin_actor_id=24,
            origin_index=origin_index,
        )
        self.assertEqual(origin, (3200.0, 116_100.0))
        self.assertEqual(state["x"], 3200.0)

    def test_manifestation_uses_last_position_before_despawn_for_instance(self):
        fight = {"startTime": 0, "endTime": 400_000, "kill": False}
        players = {10: {"id": 10, "name": "Hunter", "classColor": "#fff", "role": "dps"}}
        catalog = coiledaltar.build_actor_catalog([
            {"id": 88, "name": "Manifestation of Dread", "gameID": coiledaltar.MANIFEST_NPC_GAME_ID, "type": "NPC"},
        ])
        index = coiledaltar.build_npc_position_index([
            {"timestamp": 200_000, "type": "cast", "sourceID": 88, "sourceInstance": 2, "x": 1000.0, "y": 1000.0},
            {"timestamp": 210_000, "type": "cast", "sourceID": 88, "sourceInstance": 2, "x": 3000.0, "y": 4000.0},
            {"timestamp": 250_000, "type": "cast", "sourceID": 88, "sourceInstance": 3, "x": 8000.0, "y": 8000.0},
        ])
        result = coiledaltar.analyze_manifestations(
            fight,
            [
                {"timestamp": 200_000, "type": "applydebuff", "abilityGameID": 1285911, "targetID": 10, "sourceID": 88, "sourceInstance": 2},
                {"timestamp": 220_000, "type": "removedebuff", "abilityGameID": 1285911, "targetID": 10, "sourceID": 88, "sourceInstance": 2},
            ],
            index,
            {10: "Hunter"},
            players,
            catalog,
            [{"key": "p1", "label": "P1", "timeMs": 0}, {"key": "p2", "label": "P2", "timeMs": 180_000}],
            enemy_deaths=[{"timestamp": 218_000, "type": "death", "targetID": 88, "targetInstance": 2}],
        )
        position = result["fixations"][0]["manifestPosition"]
        self.assertEqual(position["x"], 3000.0)
        self.assertEqual(position["y"], 4000.0)
        self.assertEqual(result["fixations"][0]["phase"], "p2")
        self.assertEqual(result["activePoints"][0]["position"]["x"], 3000.0)

    def test_manifestation_ignores_non_manifest_sources(self):
        fight = {"startTime": 0, "endTime": 400_000, "kill": False}
        players = {10: {"id": 10, "name": "Hunter", "classColor": "#fff", "role": "dps"}}
        catalog = coiledaltar.build_actor_catalog([
            {"id": 99, "name": "Some Other Add", "gameID": 1, "type": "NPC"},
        ])
        result = coiledaltar.analyze_manifestations(
            fight,
            [
                {"timestamp": 50_000, "type": "applydebuff", "abilityGameID": 1285911, "targetID": 10, "sourceID": 99, "sourceInstance": 1},
            ],
            {},
            {10: "Hunter"},
            players,
            catalog,
            [{"key": "p1", "label": "P1", "timeMs": 0}, {"key": "p2", "label": "P2", "timeMs": 180_000}],
        )
        self.assertEqual(result["fixations"], [])

    def test_guillotine_danger_radius_is_40_yards(self):
        self.assertEqual(coiledaltar.GUILLOTINE_RANGE_YARDS, 40)
        self.assertEqual(coiledaltar.WIDOW_TOUCH_DAMAGE_ID, 1283631)
        self.assertEqual(coiledaltar.WIDOW_KISS_DAMAGE_ID, 1283623)
        self.assertEqual(coiledaltar.DEATH_WHISPER_DAMAGE_ID, 1299401)
        self.assertEqual(coiledaltar.DEATH_EMBRACE_DAMAGE_ID, 1299396)

    def test_guillotine_still_inside_uses_widow_kiss_after_touch_pulse(self):
        fight = {"startTime": 0, "endTime": 100_000, "kill": False}
        players = {
            10: {"id": 10, "name": "A", "classColor": "#fff", "role": "dps"},
            11: {"id": 11, "name": "B", "classColor": "#fff", "role": "dps"},
        }
        markers = [{"key": "p1", "label": "P1", "timeMs": 0}]
        index = coiledaltar.build_position_index([
            {"timestamp": 10_000, "type": "cast", "sourceID": 10, "x": 0.0, "y": 115_800.0},
            {"timestamp": 10_000, "type": "cast", "sourceID": 11, "x": 100.0, "y": 115_800.0},
            {"timestamp": 18_000, "type": "cast", "sourceID": 10, "x": 200.0, "y": 115_800.0},
            {"timestamp": 18_000, "type": "cast", "sourceID": 11, "x": 20_000.0, "y": 115_800.0},
        ])
        result = coiledaltar.analyze_guillotine(
            fight,
            [{"timestamp": 10_000, "type": "cast", "abilityGameID": 1283489, "sourceID": 1}],
            [
                {"timestamp": 10_050, "type": "damage", "abilityGameID": 1283594, "targetID": 10, "amount": 100},
                {"timestamp": 10_050, "type": "damage", "abilityGameID": 1283594, "targetID": 11, "amount": 100},
                # 全团寡妇之触；仅 A 仍在圈内吃寡妇之吻（位置已不重要）
                {"timestamp": 18_000, "type": "damage", "abilityGameID": 1283631, "targetID": 10, "amount": 50},
                {"timestamp": 18_000, "type": "damage", "abilityGameID": 1283631, "targetID": 11, "amount": 50},
                {"timestamp": 18_020, "type": "damage", "abilityGameID": 1283623, "targetID": 10, "amount": 80},
            ],
            [],
            index,
            {10: "A", 11: "B"},
            players,
            markers,
            coiledaltar.GUILLOTINE_CAST_IDS,
            "处斩",
            pulse_damage_id=coiledaltar.WIDOW_TOUCH_DAMAGE_ID,
            in_range_damage_id=coiledaltar.WIDOW_KISS_DAMAGE_ID,
        )
        row = result["rounds"][0]
        self.assertEqual(row["participantCount"], 2)
        self.assertEqual(row["pulseDamageID"], 1283631)
        self.assertEqual(row["inRangeDamageID"], 1283623)
        self.assertEqual(row["pulseTimeMs"], 18_000)
        inside_names = {p["player"] for p in row["stillInsideRange"]}
        self.assertEqual(inside_names, {"A"})

    def test_grim_guillotine_still_inside_uses_death_embrace(self):
        fight = {"startTime": 0, "endTime": 200_000, "kill": False}
        players = {
            10: {"id": 10, "name": "A", "classColor": "#fff", "role": "dps"},
            11: {"id": 11, "name": "B", "classColor": "#fff", "role": "dps"},
        }
        markers = [{"key": "p3", "label": "P3", "timeMs": 0}]
        index = coiledaltar.build_position_index([
            {"timestamp": 100_000, "type": "cast", "sourceID": 10, "x": 1_000.0, "y": 115_800.0},
            {"timestamp": 100_000, "type": "cast", "sourceID": 11, "x": 1_200.0, "y": 115_800.0},
        ])
        result = coiledaltar.analyze_guillotine(
            fight,
            [{"timestamp": 100_000, "type": "cast", "abilityGameID": 1299267, "sourceID": 1}],
            [
                {"timestamp": 100_100, "type": "damage", "abilityGameID": 1299267, "targetID": 10, "amount": 100},
                {"timestamp": 100_100, "type": "damage", "abilityGameID": 1299267, "targetID": 11, "amount": 100},
                {"timestamp": 112_000, "type": "damage", "abilityGameID": 1299401, "targetID": 10, "amount": 50},
                {"timestamp": 112_000, "type": "damage", "abilityGameID": 1299401, "targetID": 11, "amount": 50},
                {"timestamp": 112_050, "type": "damage", "abilityGameID": 1299396, "targetID": 11, "amount": 90},
            ],
            [],
            index,
            {10: "A", 11: "B"},
            players,
            markers,
            coiledaltar.GRIM_GUILLOTINE_CAST_IDS,
            "冷酷处斩",
            damage_ids=coiledaltar.GRIM_GUILLOTINE_DAMAGE_IDS,
            mark_ids=coiledaltar.GRIM_GUILLOTINE_MARK_IDS,
            pulse_damage_id=coiledaltar.DEATH_WHISPER_DAMAGE_ID,
            in_range_damage_id=coiledaltar.DEATH_EMBRACE_DAMAGE_ID,
        )
        row = result["rounds"][0]
        self.assertEqual(row["pulseDamageID"], 1299401)
        inside_names = {p["player"] for p in row["stillInsideRange"]}
        self.assertEqual(inside_names, {"B"})

    def test_grim_guillotine_falls_back_to_absorb_mark_and_appears_in_field(self):
        fight = {"startTime": 0, "endTime": 200_000, "kill": False}
        players = {
            10: {"id": 10, "name": "A", "classColor": "#fff", "role": "dps"},
            11: {"id": 11, "name": "B", "classColor": "#fff", "role": "dps"},
        }
        markers = [{"key": "p3", "label": "P3", "timeMs": 0}]
        index = coiledaltar.build_position_index([
            {"timestamp": 100_000, "type": "cast", "sourceID": 10, "x": 1_000.0, "y": 115_800.0},
            {"timestamp": 100_000, "type": "cast", "sourceID": 11, "x": 1_200.0, "y": 115_800.0},
            {"timestamp": 105_000, "type": "cast", "sourceID": 10, "x": 1_100.0, "y": 115_800.0},
            {"timestamp": 105_000, "type": "cast", "sourceID": 11, "x": 1_300.0, "y": 115_800.0},
        ])
        # 无分摊伤害，仅有 1307652 治疗吸收施加
        result = coiledaltar.analyze_guillotine(
            fight,
            [{"timestamp": 100_000, "type": "cast", "abilityGameID": 1299267, "sourceID": 1}],
            [],
            [
                {"timestamp": 100_200, "type": "applydebuff", "abilityGameID": 1307652, "targetID": 10},
                {"timestamp": 100_200, "type": "applydebuff", "abilityGameID": 1307652, "targetID": 11},
            ],
            index,
            {10: "A", 11: "B"},
            players,
            markers,
            coiledaltar.GRIM_GUILLOTINE_CAST_IDS,
            "冷酷处斩",
            damage_ids=coiledaltar.GRIM_GUILLOTINE_DAMAGE_IDS,
            mark_ids=coiledaltar.GRIM_GUILLOTINE_MARK_IDS,
        )
        self.assertEqual(result["label"], "冷酷处斩")
        self.assertEqual(result["rounds"][0]["participantCount"], 2)
        self.assertIsNotNone(result["rounds"][0]["shareCentroid"])

        audit = coiledaltar.build_field_audit(
            None, {"rounds": []}, {"rounds": []}, {"rounds": []}, {"rounds": []}, {"rounds": []},
            grim_guillotine=result,
        )
        mechanics = [row["mechanic"] for row in audit["diagrams"]]
        self.assertIn("冷酷处斩", mechanics)
        grim = next(row for row in audit["diagrams"] if row["mechanic"] == "冷酷处斩")
        self.assertEqual(grim["kind"], "runout")
        self.assertTrue(grim["origin"])
        self.assertGreaterEqual(len(grim["targets"]), 2)

    def test_field_icons_come_from_assets_loader(self):
        from boss_plugins.assets.icons import get_boss_icon_path

        for key in ("zuljan", "hex_lord_malacrass", "poison_orb", "manifestation_dread"):
            self.assertTrue(get_boss_icon_path(key).is_file(), key)
        audit = coiledaltar.build_field_audit(
            None, {"rounds": []}, {"rounds": []}, {"rounds": []}, {"rounds": []}, {"rounds": []},
        )
        self.assertEqual(audit["icons"]["zuljan"], coiledaltar._boss_icon_src("zuljan"))
        self.assertEqual(audit["icons"]["malacrass"], coiledaltar._boss_icon_src("hex_lord_malacrass"))
        self.assertEqual(audit["icons"]["poisonOrb"], coiledaltar._boss_icon_src("poison_orb"))
        self.assertEqual(audit["icons"]["manifestation"], coiledaltar._boss_icon_src("manifestation_dread"))
        self.assertEqual(audit["icons"]["zuljan"], "boss_plugins/assets/Zul'jan.png")

    def test_arena_uses_fixed_yard_center_0_1158(self):
        index = coiledaltar.build_position_index([
            {"timestamp": 10_000, "type": "cast", "abilityGameID": 1, "sourceID": 24, "x": 12_000.0, "y": -8_000.0},
            {"timestamp": 40_000, "type": "cast", "abilityGameID": 1, "sourceID": 24, "x": 18_000.0, "y": -3_000.0},
            {"timestamp": 20_000, "type": "damage", "abilityGameID": 1, "targetID": 7, "x": 12_500.0, "y": -7_500.0},
        ])
        arena = coiledaltar.coiledaltar_arena(index, [7], boss_id=24)
        self.assertEqual(arena["centerXYards"], 0)
        self.assertEqual(arena["centerYYards"], 1158)
        self.assertEqual(arena["centerX"], 0.0)
        self.assertEqual(arena["centerY"], 115_800.0)
        self.assertEqual(arena["sideUnits"], 110)
        self.assertEqual(arena["sideYards"], 86)
        self.assertEqual(arena["radiusUnits"], 55)
        self.assertEqual(arena["radiusYards"], 43)
        self.assertEqual(arena["radius"], 5_500.0)
        self.assertAlmostEqual(arena["unitsPerYard"], 100 * 110 / 86)
        self.assertEqual(arena["wclCoordScale"], 100)
        self.assertEqual(arena["method"], "fixed-center-0-1158-square-110u-86y")
        self.assertEqual(arena["bossStart"]["x"], 12_000.0)
        self.assertAlmostEqual(arena["plotScaleX"], coiledaltar.ARENA_PLOT_SCALE_X)
        self.assertAlmostEqual(arena["plotScaleY"], coiledaltar.ARENA_PLOT_SCALE_Y)

    def test_square_edges_and_skill_radii_map_from_fixed_center(self):
        arena = coiledaltar.coiledaltar_arena()
        cx, cy = coiledaltar.arena_center_units()
        half = coiledaltar.ARENA_HALF_SIDE_UNITS * coiledaltar.WCL_COORD_SCALE
        east = coiledaltar.plot_pct((cx + half, cy), arena)
        north = coiledaltar.plot_pct((cx, cy + half), arena)
        self.assertAlmostEqual(east["left"], 50 + coiledaltar.ARENA_PLOT_SCALE_X, places=4)
        self.assertAlmostEqual(east["top"], 50.0, places=4)
        self.assertAlmostEqual(north["left"], 50.0, places=4)
        self.assertAlmostEqual(north["top"], 50 - coiledaltar.ARENA_PLOT_SCALE_Y, places=4)
        half_square_px = coiledaltar.ARENA_SQUARE_PX / 2
        for yards in (15, 35, 40, 43):
            size = coiledaltar.plot_size_pct(yards, arena)
            px_x = size["width"] / 100 * coiledaltar.ARENA_IMAGE_WIDTH
            px_y = size["height"] / 100 * coiledaltar.ARENA_IMAGE_HEIGHT
            expected = yards / coiledaltar.ARENA_SIDE_YARDS * coiledaltar.ARENA_SQUARE_PX
            self.assertAlmostEqual(px_x, px_y, places=2)
            self.assertAlmostEqual(px_x, expected, places=2)
        edge = coiledaltar.plot_size_pct(coiledaltar.ARENA_HALF_SIDE_YARDS, arena)
        self.assertAlmostEqual(edge["width"] / 100 * coiledaltar.ARENA_IMAGE_WIDTH, half_square_px, places=2)

    def test_field_audit_includes_sever_guillotine_and_gloombomb(self):
        audit = coiledaltar.build_field_audit(
            None,
            {"rounds": [{"index": 1, "phase": "p1", "time": "00:10.0", "spawnCount": 1, "spawns": [], "carriers": [], "drops": []}]},
            {"rounds": [{
                "index": 1,
                "label": "撕裂",
                "phase": "p1",
                "time": "00:30.0",
                "origin": {"x": 0.0, "y": 115_800.0},
                "conePolygon": [{"x": 0.0, "y": 115_800.0}, {"x": 1000.0, "y": 115_800.0}, {"x": 0.0, "y": 115_800.0}],
                "nearbyPoints": [{"kind": "dropped-venom", "position": {"x": 500.0, "y": 115_800.0}}],
                "targetsInCone": [],
                "inferredClearedCount": 0,
                "clearedByGeometry": 0,
                "tankPosition": {"x": 2000.0, "y": 115_800.0},
            }]},
            {"rounds": []},
            {"rounds": [{
                "index": 1,
                "phase": "p2",
                "time": "03:00.0",
                "targetCount": 1,
                "targets": [{"player": "Mage", "position": {"x": 100.0, "y": 200.0}}],
                "collateralHits": [{"player": "Priest", "position": {"x": 150.0, "y": 200.0}, "receivedGravebound": True, "distanceYards": 4.0}],
                "collateralCount": 1,
                "spreadRadiusYards": 15,
                "tooClosePairs": [],
                "bossPosition": {"x": 3200.0, "y": 116_100.0},
            }]},
            {"rounds": []},
            manifestations={"fixations": [{"phase": "p1", "applyTime": "00:05.0", "manifestPosition": {"x": 1, "y": 2}}]},
            guillotine={"rounds": [{
                "index": 1,
                "label": "处斩",
                "phase": "p1",
                "time": "00:20.0",
                "participantCount": 1,
                "shareCentroid": {"x": 100.0, "y": 200.0},
                "bossPosition": {"x": 1500.0, "y": 2500.0},
                "dangerRadiusYards": 40,
                "participants": [{"player": "Tank", "position": {"x": 110.0, "y": 210.0}}],
                "stillInsideRange": [],
            }]},
        )
        kinds = [row["kind"] for row in audit["diagrams"]]
        mechanics = [row["mechanic"] for row in audit["diagrams"]]
        self.assertEqual(kinds, ["cone-clear", "runout", "spread"])
        self.assertEqual(mechanics, ["撕裂", "处斩", "幽暗炸弹"])
        self.assertEqual(audit["diagrams"][0]["targets"][0]["kind"], "tank")
        self.assertEqual(audit["diagrams"][0]["targets"][1]["kind"], "dropped-venom")
        self.assertEqual(audit["diagrams"][1]["origin"]["x"], 100.0)
        self.assertEqual(audit["diagrams"][1]["bossPosition"]["x"], 1500.0)
        self.assertEqual(audit["diagrams"][1]["bossPosition"]["y"], 2500.0)
        self.assertNotEqual(
            (audit["diagrams"][1]["bossPosition"]["x"], audit["diagrams"][1]["bossPosition"]["y"]),
            coiledaltar.arena_center_units(),
        )
        self.assertEqual(audit["diagrams"][2]["targets"][0]["player"], "Mage")
        self.assertEqual(audit["diagrams"][2]["nearbyPlayers"][0]["player"], "Priest")
        self.assertEqual(audit["diagrams"][2]["bossPosition"]["x"], 3200.0)
        self.assertIn("误伤墓缚 1", audit["diagrams"][2]["annotation"])

    def test_guillotine_and_gloombomb_use_boss_current_position(self):
        fight = {"startTime": 0, "endTime": 200_000, "kill": False}
        players = {10: {"id": 10, "name": "A", "classColor": "#fff", "role": "dps"}}
        guillotine_cast = {
            "timestamp": 10_000,
            "type": "cast",
            "abilityGameID": 1283489,
            "sourceID": 24,
            "sourceResources": {"x": 1500.0, "y": 2500.0},
        }
        gloombomb_cast = {
            "timestamp": 100_000,
            "type": "cast",
            "abilityGameID": 1286895,
            "sourceID": 25,
            "sourceResources": {"x": 3200.0, "y": 116_100.0},
        }
        origin_index = coiledaltar.build_caster_self_position_index(
            [guillotine_cast, gloombomb_cast], {24, 25},
        )
        player_index = coiledaltar.build_position_index([
            {"timestamp": 10_000, "type": "cast", "sourceID": 10, "x": 110.0, "y": 210.0},
            {"timestamp": 106_000, "type": "cast", "sourceID": 10, "x": 5000.0, "y": 5000.0},
        ])
        guillotine = coiledaltar.analyze_guillotine(
            fight, [guillotine_cast],
            [{"timestamp": 10_050, "type": "damage", "abilityGameID": 1283594, "targetID": 10, "amount": 100}],
            [], player_index, {10: "A", 24: "祖尔加"}, players,
            [{"key": "p1", "label": "P1", "timeMs": 0}],
            coiledaltar.GUILLOTINE_CAST_IDS, "处斩",
            origin_index=origin_index, boss_actor_id=24,
        )
        gloombomb = coiledaltar.analyze_gloombomb(
            fight, [gloombomb_cast],
            [
                {"timestamp": 100_200, "type": "applydebuff", "abilityGameID": 1310881, "targetID": 10},
                {"timestamp": 106_000, "type": "removedebuff", "abilityGameID": 1310881, "targetID": 10},
            ],
            player_index, {10: "A", 25: "玛拉卡斯"}, players,
            [{"key": "p2", "label": "P2", "timeMs": 0}],
            origin_index=origin_index, boss_actor_id=25,
        )
        center = coiledaltar.arena_center_units()
        self.assertEqual(guillotine["rounds"][0]["bossPosition"]["x"], 1500.0)
        self.assertEqual(guillotine["rounds"][0]["bossPosition"]["y"], 2500.0)
        self.assertNotEqual(
            (guillotine["rounds"][0]["bossPosition"]["x"], guillotine["rounds"][0]["bossPosition"]["y"]),
            center,
        )
        self.assertEqual(gloombomb["rounds"][0]["bossPosition"]["x"], 3200.0)
        self.assertEqual(gloombomb["rounds"][0]["bossPosition"]["y"], 116_100.0)
        audit = coiledaltar.build_field_audit(
            None, {"rounds": []}, {"rounds": []}, {"rounds": []}, gloombomb, {"rounds": []},
            guillotine=guillotine,
        )
        runout = next(row for row in audit["diagrams"] if row["kind"] == "runout")
        spread = next(row for row in audit["diagrams"] if row["kind"] == "spread")
        self.assertEqual(runout["bossPosition"]["x"], 1500.0)
        self.assertNotEqual(runout["bossPosition"]["x"], runout["origin"]["x"])
        self.assertEqual(spread["bossPosition"]["x"], 3200.0)

    def test_active_venom_points_use_ground_intervals_not_every_drop(self):
        toxic = {
            "groundPuddles": [
                {
                    "puddleID": 1,
                    "position": {"x": 100.0, "y": 200.0},
                    "groundedFromMs": 10_000,
                    "pickedUpAtMs": 12_000,
                    "transferCount": 0,
                    "carriers": [{"player": "A"}],
                },
                {
                    "puddleID": 1,
                    "position": {"x": 900.0, "y": 800.0},
                    "groundedFromMs": 15_000,
                    "pickedUpAtMs": None,
                    "transferCount": 1,
                    "carriers": [{"player": "A"}, {"player": "B"}],
                },
            ],
            "rounds": [],
        }
        points = coiledaltar.build_active_venom_points(toxic)
        self.assertEqual(len(points), 2)
        self.assertEqual(points[0]["kind"], "ground-venom")
        at_mid = coiledaltar.active_venom_before_cast(points, 11_000, 0)
        self.assertEqual(len(at_mid), 1)
        self.assertEqual(at_mid[0]["position"]["x"], 100.0)
        at_final = coiledaltar.active_venom_before_cast(points, 20_000, 0)
        self.assertEqual(len(at_final), 1)
        self.assertEqual(at_final[0]["position"]["x"], 900.0)

        # 上一轮撕裂后毒液已清：只显示本轮窗口内落地的球
        between = coiledaltar.active_venom_before_cast(points, 20_000, 0, after_ms=12_000)
        self.assertEqual(len(between), 1)
        self.assertEqual(between[0]["position"]["x"], 900.0)
        stale = coiledaltar.active_venom_before_cast(
            [
                {"kind": "ground-venom", "position": {"x": 1.0, "y": 1.0}, "groundedFromMs": 5_000, "pickedUpAtMs": None},
                {"kind": "ground-venom", "position": {"x": 2.0, "y": 2.0}, "groundedFromMs": 16_000, "pickedUpAtMs": None},
            ],
            20_000,
            0,
            after_ms=12_000,
        )
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0]["position"]["x"], 2.0)

    def test_previous_cone_sever_rel_ms_finds_last_clear(self):
        casts = [
            {"timestamp": 10_000, "type": "cast", "abilityGameID": 1299684},
            {"timestamp": 40_000, "type": "cast", "abilityGameID": 1299684},
            {"timestamp": 90_000, "type": "cast", "abilityGameID": 1307292},
        ]
        self.assertIsNone(coiledaltar.previous_cone_sever_rel_ms(casts, 10_000, 0))
        self.assertEqual(coiledaltar.previous_cone_sever_rel_ms(casts, 40_000, 0), 10_000)
        self.assertEqual(coiledaltar.previous_cone_sever_rel_ms(casts, 90_000, 0), 40_000)

    def test_blighted_sever_classifies_manifest_clear_by_debuff(self):
        fight = {"startTime": 0, "endTime": 200_000, "kill": False}
        markers = [{"key": "p3", "label": "P3", "timeMs": 0}]
        index = coiledaltar.build_position_index([
            {
                "timestamp": 100_000,
                "type": "cast",
                "sourceID": 1,
                "x": 0.0,
                "y": 115_800.0,
                "facing": 0,
                "sourceResources": {"x": 0.0, "y": 115_800.0, "facing": 0},
            },
        ])
        points = [
            {
                "kind": "manifestation",
                "applyTimeMs": 50_000,
                "removeTimeMs": 100_800,
                "position": {"x": 1_000.0, "y": 115_800.0},
                "manifestPosition": {"x": 1_000.0, "y": 115_800.0},
                "playerPosition": {"x": 2_000.0, "y": 115_800.0},
                "player": "A",
                "playerID": 10,
            },
            {
                "kind": "manifestation",
                "applyTimeMs": 50_000,
                "removeTimeMs": 180_000,
                "position": {"x": 1_200.0, "y": 115_800.0},
                "manifestPosition": {"x": 1_200.0, "y": 115_800.0},
                "playerPosition": {"x": 2_200.0, "y": 115_800.0},
                "player": "B",
                "playerID": 11,
                "icon": "mage-fire",
                "specID": 63,
                "specName": "火焰",
                "className": "法师",
                "classColor": "#3fc7eb",
                "role": "range-dps",
            },
        ]
        result = coiledaltar.analyze_cone_sever(
            "凋零撕裂",
            coiledaltar.BLIGHTED_SEVER_IDS,
            fight,
            [{
                "timestamp": 100_000,
                "type": "cast",
                "abilityGameID": 1307292,
                "sourceID": 1,
                "sourceResources": {"x": 0.0, "y": 115_800.0, "facing": 0},
            }],
            [],
            index,
            {1: "Boss", 10: "A", 11: "B"},
            {
                10: {"id": 10, "name": "A", "classColor": "#fff", "role": "dps"},
                11: {"id": 11, "name": "B", "classColor": "#fff", "role": "dps"},
            },
            markers,
            points,
            {},
            boss_actor_id=1,
            origin_index=index,
        )
        row = result["rounds"][0]
        self.assertEqual(row["clearedByDebuff"], 1)
        self.assertEqual(row["unclearedCount"], 1)
        outcomes = {p["player"]: p["clearOutcome"] for p in row["nearbyPoints"]}
        self.assertEqual(outcomes["A"], "cleared")
        self.assertEqual(outcomes["B"], "missed-in-cone")

        audit = coiledaltar.build_field_audit(
            None, {"rounds": []}, {"rounds": []}, {"rounds": []}, {"rounds": []}, result,
        )
        blighted = next(d for d in audit["diagrams"] if d["mechanic"] == "凋零撕裂")
        self.assertEqual(len(blighted["links"]), 1)
        self.assertEqual(blighted["links"][0]["player"], "B")
        self.assertEqual(blighted["unclearedCount"], 1)
        named = next(row for row in blighted["targets"] if row.get("kind") == "manifest-target")
        self.assertEqual(named["icon"], "mage-fire")
        self.assertEqual(named["specID"], 63)
        self.assertEqual(named["specName"], "火焰")

    def test_toxic_deluge_tracks_multi_carry_ground_position(self):
        fight = {"startTime": 0, "endTime": 100_000, "kill": False}
        players = {
            10: {"id": 10, "name": "A", "classColor": "#fff", "role": "dps"},
            11: {"id": 11, "name": "B", "classColor": "#fff", "role": "dps"},
        }
        markers = [{"key": "p1", "label": "P1", "timeMs": 0}]
        index = coiledaltar.build_position_index([
            {"timestamp": 10_000, "type": "cast", "sourceID": 10, "x": 1000.0, "y": 1000.0},
            {"timestamp": 12_000, "type": "cast", "sourceID": 10, "x": 2000.0, "y": 2000.0},
            {"timestamp": 12_500, "type": "cast", "sourceID": 11, "x": 2100.0, "y": 2100.0},
            {"timestamp": 18_000, "type": "cast", "sourceID": 11, "x": 5000.0, "y": 6000.0},
        ])
        result = coiledaltar.analyze_toxic_deluge(
            fight,
            [
                {"timestamp": 5_000, "type": "cast", "abilityGameID": coiledaltar.TOXIC_DELUGE, "sourceID": 1},
                {
                    "timestamp": 6_000,
                    "type": "cast",
                    "abilityGameID": coiledaltar.COALESCED_VENOM_CAST,
                    "sourceID": 50,
                    "sourceInstance": 1,
                    "sourceResources": {"x": 1000.0, "y": 1000.0},
                },
            ],
            [
                {"timestamp": 10_000, "type": "applydebuff", "abilityGameID": coiledaltar.VOLATILE_VENOM, "targetID": 10},
                {"timestamp": 12_000, "type": "removedebuff", "abilityGameID": coiledaltar.VOLATILE_VENOM, "targetID": 10},
                {"timestamp": 12_400, "type": "applydebuff", "abilityGameID": coiledaltar.VOLATILE_VENOM, "targetID": 11},
                {"timestamp": 18_000, "type": "removedebuff", "abilityGameID": coiledaltar.VOLATILE_VENOM, "targetID": 11},
            ],
            index,
            {10: "A", 11: "B"},
            players,
            markers,
        )
        points = coiledaltar.build_active_venom_points(result)
        # 中间落点 2000,2000 已被接力捡起；撕裂前只应看到最终落点
        final = coiledaltar.active_venom_before_cast(points, 20_000, 0)
        self.assertEqual(len(final), 1)
        self.assertEqual(final[0]["position"]["x"], 5000.0)
        self.assertEqual(final[0]["position"]["y"], 6000.0)
        self.assertGreaterEqual(final[0]["transferCount"], 1)
        mid = coiledaltar.active_venom_before_cast(points, 12_200, 0)
        self.assertEqual(len(mid), 1)
        self.assertEqual(mid[0]["position"]["x"], 2000.0)

    def test_venom_pickup_matches_by_drop_proximity_not_earliest(self):
        """场上多团时，应用捡球玩家与放球点距离判定同球，禁止误绑最早落地团。"""
        far = {
            "puddleID": 1,
            "position": {"x": 0.0, "y": 0.0},
            "groundedFromMs": 1_000,
        }
        near = {
            "puddleID": 2,
            "position": {"x": 5000.0, "y": 5000.0},
            "groundedFromMs": 10_000,
        }
        ground = [far, near]
        matched = coiledaltar._match_puddle_for_pickup(ground, (5100.0, 5050.0))
        self.assertIs(matched, near)
        # 离两团都远：不得回退到 earliest
        self.assertIsNone(coiledaltar._match_puddle_for_pickup(ground, (20_000.0, 20_000.0)))
        self.assertIsNone(coiledaltar._match_puddle_for_pickup(ground, None))
        self.assertIs(coiledaltar._match_puddle_for_pickup([near], None), near)

        fight = {"startTime": 0, "endTime": 100_000, "kill": False}
        players = {
            10: {"id": 10, "name": "A", "classColor": "#fff", "role": "dps"},
            11: {"id": 11, "name": "B", "classColor": "#fff", "role": "dps"},
        }
        markers = [{"key": "p1", "label": "P1", "timeMs": 0}]
        # A 捡近处球并放下；若 B 的坐标离放球点很远，旧逻辑会误绑远处最早生成团
        index = coiledaltar.build_position_index([
            {"timestamp": 8_000, "type": "cast", "sourceID": 10, "x": 8000.0, "y": 8000.0},
            {"timestamp": 12_000, "type": "cast", "sourceID": 10, "x": 8200.0, "y": 8200.0},
            {"timestamp": 12_400, "type": "cast", "sourceID": 11, "x": 20_000.0, "y": 20_000.0},
            {"timestamp": 18_000, "type": "cast", "sourceID": 11, "x": 20_100.0, "y": 20_100.0},
        ])
        result = coiledaltar.analyze_toxic_deluge(
            fight,
            [
                {"timestamp": 1_000, "type": "cast", "abilityGameID": coiledaltar.TOXIC_DELUGE, "sourceID": 1},
                {
                    "timestamp": 2_000,
                    "type": "cast",
                    "abilityGameID": coiledaltar.COALESCED_VENOM_CAST,
                    "sourceID": 50,
                    "sourceInstance": 1,
                    "sourceResources": {"x": 0.0, "y": 0.0},
                },
                {
                    "timestamp": 2_100,
                    "type": "cast",
                    "abilityGameID": coiledaltar.COALESCED_VENOM_CAST,
                    "sourceID": 51,
                    "sourceInstance": 2,
                    "sourceResources": {"x": 8000.0, "y": 8000.0},
                },
            ],
            [
                {"timestamp": 8_000, "type": "applydebuff", "abilityGameID": coiledaltar.VOLATILE_VENOM, "targetID": 10},
                {"timestamp": 12_000, "type": "removedebuff", "abilityGameID": coiledaltar.VOLATILE_VENOM, "targetID": 10},
                {"timestamp": 12_400, "type": "applydebuff", "abilityGameID": coiledaltar.VOLATILE_VENOM, "targetID": 11},
                {"timestamp": 18_000, "type": "removedebuff", "abilityGameID": coiledaltar.VOLATILE_VENOM, "targetID": 11},
            ],
            index,
            {10: "A", 11: "B"},
            players,
            markers,
        )
        final = coiledaltar.active_venom_before_cast(coiledaltar.build_active_venom_points(result), 20_000, 0)
        xs = sorted(p["position"]["x"] for p in final)
        # 旧 earliest 回退会把远处生成团误绑到 B，导致 0 消失、只剩孤儿放球点+B 落点
        self.assertEqual(xs, [0.0, 8200.0, 20_100.0])

    def test_normalize_facing_wraps_to_pi_range(self):
        self.assertAlmostEqual(coiledaltar.normalize_facing_radians(-779), -1.5068, places=3)

    def test_active_points_near_cast_handles_fight_relative_timestamps(self):
        fight_start = 1_000_000
        timestamp = fight_start + 25_000
        points = [
            {"position": {"x": 1.0, "y": 2.0}, "lastSeenMs": 20_000},
            {"position": {"x": 3.0, "y": 4.0}, "lastSeenMs": fight_start + 24_000},
            {"position": {"x": 5.0, "y": 6.0}, "lastSeenMs": 1_000},
        ]
        nearby = coiledaltar.active_points_near_cast(points, timestamp, fight_start)
        self.assertEqual(len(nearby), 3)
        old_point = [{"position": {"x": 9.0, "y": 9.0}, "lastSeenMs": 1_000}]
        self.assertEqual(len(coiledaltar.active_points_near_cast(old_point, fight_start + 120_000, fight_start)), 0)

    def test_cone_half_angle_matches_60_degree_frontal(self):
        self.assertEqual(coiledaltar.CONE_HALF_ANGLE_DEG, 30.0)

    def test_resolve_caster_origin_without_self_index_is_missing(self):
        index = coiledaltar.build_position_index([
            {
                "timestamp": 100_000,
                "type": "cast",
                "abilityGameID": 1,
                "sourceID": 99,
                "x": 0.0,
                "y": 0.0,
                "facing": 0,
            },
            {
                "timestamp": 100_000,
                "type": "cast",
                "abilityGameID": 1,
                "sourceID": 24,
                "x": 1000.0,
                "y": 2000.0,
                "facing": 0,
            },
        ])
        origin, facing, state, inferred, *_ = coiledaltar.resolve_caster_origin_facing(
            index, 99, 24, 100_050,
            hint_points=[{"position": {"x": 4000.0, "y": 2000.0}}],
            origin_actor_id=24,
        )
        self.assertIsNone(origin)
        self.assertEqual(state["positionRule"], "missing")

    def test_source_self_point_prefers_source_resources_over_target_xy(self):
        event = {
            "timestamp": 100_000,
            "type": "cast",
            "sourceID": 24,
            "targetID": 10,
            "x": 9000.0,
            "y": 9000.0,
            "sourceResources": {"x": 0.0, "y": 115_800.0, "facing": 0},
        }
        self.assertEqual(coiledaltar._source_self_point(event), (0.0, 115_800.0))
        self.assertIsNone(coiledaltar._source_self_point({
            "timestamp": 100_000, "type": "cast", "sourceID": 24, "x": 9000.0, "y": 9000.0,
        }))

    def test_infer_facing_toward_centroid(self):
        facing = coiledaltar.infer_facing_toward((0.0, 0.0), [{"x": 3000.0, "y": 0.0}])
        self.assertIsNotNone(facing)
        self.assertTrue(coiledaltar.in_frontal_cone((0.0, 0.0), facing, (3000.0, 0.0)))

    def test_resolve_caster_origin_ignores_polluted_cast_xy(self):
        index = coiledaltar.build_position_index([
            {
                "timestamp": 100_000,
                "type": "cast",
                "abilityGameID": 1,
                "sourceID": 24,
                "x": 1000.0,
                "y": 2000.0,
                "facing": 0,
            },
        ])
        origin, facing, state, inferred, *_ = coiledaltar.resolve_caster_origin_facing(
            index, 24, 24, 100_050, hint_points=[{"position": {"x": 4000.0, "y": 2000.0}}],
        )
        self.assertIsNone(origin)
        self.assertNotEqual(origin, (1000.0, 2000.0))
        self.assertEqual(state["positionRule"], "missing")

    def test_sever_facing_lock_prefers_tank_debuff(self):
        cast = {
            "timestamp": 100_000,
            "type": "cast",
            "abilityGameID": 1299684,
            "sourceID": 24,
            "targetID": 10,
        }
        casts = [
            {"timestamp": 97_000, "type": "begincast", "abilityGameID": 1299684, "sourceID": 24, "targetID": 10},
            cast,
        ]
        debuffs = [
            {
                "timestamp": 99_850,
                "type": "applydebuff",
                "abilityGameID": 1301690,
                "sourceID": 24,
                "targetID": 10,
            },
        ]
        lock_ms, tank_id, rule, event = coiledaltar.resolve_sever_facing_lock(casts, cast, debuffs=debuffs)
        self.assertEqual(lock_ms, 99_850)
        self.assertEqual(tank_id, 10)
        self.assertEqual(rule, "tank-debuff")
        self.assertEqual(event["abilityGameID"], 1301690)

    def test_sever_facing_lock_falls_back_to_cast_last_second(self):
        cast = {
            "timestamp": 100_000,
            "type": "cast",
            "abilityGameID": 1299684,
            "sourceID": 24,
            "targetID": 10,
        }
        casts = [
            {"timestamp": 97_000, "type": "begincast", "abilityGameID": 1299684, "sourceID": 24, "targetID": 10},
            cast,
        ]
        lock_ms, tank_id, rule, event = coiledaltar.resolve_sever_facing_lock(casts, cast, debuffs=[])
        self.assertEqual(lock_ms, 99_000)
        self.assertEqual(tank_id, 10)
        self.assertEqual(rule, "cast-last-second")
        self.assertIsNone(event)

    def test_sever_facing_uses_tank_position_at_lock_time(self):
        cast = {
            "timestamp": 100_000,
            "type": "cast",
            "abilityGameID": 1299684,
            "sourceID": 24,
            "targetID": 10,
            "sourceResources": {"x": 0.0, "y": 115_800.0, "facing": 0},
        }
        position_index = coiledaltar.build_position_index([
            {
                "timestamp": 99_000,
                "type": "cast",
                "sourceID": 10,
                "x": 0.0,
                "y": 120_000.0,
                "facing": 0,
            },
            {
                "timestamp": 100_000,
                "type": "cast",
                "sourceID": 10,
                "x": 8_000.0,
                "y": 115_800.0,
                "facing": 0,
            },
        ])
        origin_index = coiledaltar.build_caster_self_position_index([cast], {24})
        origin, facing, state, inferred, tank_state = coiledaltar.resolve_caster_origin_facing(
            position_index, 24, 24, 100_000,
            target_id=10,
            origin_actor_id=24,
            origin_index=origin_index,
            cast_event=cast,
            facing_timestamp=99_000,
            allow_hint_override=False,
        )
        self.assertEqual(origin, (0.0, 115_800.0))
        self.assertEqual((tank_state["x"], tank_state["y"]), (0.0, 120_000.0))
        expected = coiledaltar.facing_toward_point(origin, (0.0, 120_000.0))
        self.assertAlmostEqual(facing, expected)
        self.assertFalse(inferred)

    def test_fetch_payload_filters_mechanic_events_instead_of_full_raid_damage(self):
        calls = []

        class Client:
            def events(self, report_id, data_type, fight, **kwargs):
                calls.append({"dataType": data_type, **kwargs})
                return []

        fight = {"id": 1, "startTime": 0, "endTime": 1000}
        actor_rows = [
            {"id": 24, "name": "Zul'jan", "type": "NPC"},
            {"id": 88, "name": "Manifestation of Dread", "gameID": coiledaltar.MANIFEST_NPC_GAME_ID},
        ]
        coiledaltar.fetch_payload(Client(), "abc", fight, actor_rows)
        damage_done = [row for row in calls if row["dataType"] == "DamageDone"]
        self.assertEqual(len(damage_done), 1)
        self.assertEqual(damage_done[0].get("target_id"), 24)
        self.assertFalse(damage_done[0].get("include_resources"))
        taken_calls = [row for row in calls if row["dataType"] == "DamageTaken"]
        mechanic_taken = next(row for row in taken_calls if "ability.id in" in str(row.get("filter_expression") or ""))
        self.assertIn(str(coiledaltar.SPIRIT_ERASURE), mechanic_taken["filter_expression"])
        self.assertTrue(mechanic_taken.get("include_resources"))
        manifest_taken = next(row for row in taken_calls if row.get("filter_expression") == "target.id = 88")
        self.assertTrue(manifest_taken.get("include_resources"))
        self.assertEqual(manifest_taken.get("hostility_type"), "Enemies")
        friendly_casts = next(
            row for row in calls
            if row["dataType"] == "Casts" and row.get("hostility_type") == "Friendlies"
        )
        self.assertFalse(friendly_casts.get("include_resources"))
        self.assertIn("ability.id in", friendly_casts["filter_expression"])
        enemy_casts = next(
            row for row in calls
            if row["dataType"] == "Casts" and row.get("hostility_type") == "Enemies"
            and "ability.id" in str(row.get("filter_expression") or "")
        )
        self.assertIn(str(coiledaltar.FIXATION), enemy_casts["filter_expression"])
        heals = next(row for row in calls if row["dataType"] == "Healing")
        self.assertEqual(heals["filter_expression"], "ability.id = 1287718")
        npc_all = next(row for row in calls if row["dataType"] == "All")
        expression = npc_all["filter_expression"]
        self.assertIn("source.id in (24, 88)", expression)
        self.assertIn("applydebuff", expression)
        self.assertNotIn('"damage"', expression)
        self.assertFalse(any(
            row["dataType"] == "DamageDone" and row.get("filter_expression") == "source.id = 88"
            for row in calls
        ))
        manifest_casts = next(
            row for row in calls
            if row["dataType"] == "Casts" and row.get("filter_expression") == "source.id = 88"
        )
        self.assertTrue(manifest_casts.get("include_resources"))
        manifest_resources = next(
            row for row in calls
            if row["dataType"] == "Resources" and row.get("filter_expression") == "source.id = 88"
        )
        self.assertEqual(manifest_resources.get("hostility_type"), "Enemies")


if __name__ == "__main__":
    unittest.main()
