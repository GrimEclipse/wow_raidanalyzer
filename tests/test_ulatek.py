import unittest

from boss_plugins.venomous_abyss.ulatek import analyze_ulatek


class UlatekAnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.fight = {"startTime": 0, "endTime": 120_000}
        self.actor_map = {1: "坦克", 2: "法师", 3: "牧师", 90: "乌拉特克", 91: "厄鳞守卫"}
        self.players = {
            1: {"name": "坦克", "role": "tank", "classColor": "#c79c6e"},
            2: {"name": "法师", "role": "range-dps", "classColor": "#69ccf0"},
            3: {"name": "牧师", "role": "range-healer", "classColor": "#ffffff"},
        }

    @staticmethod
    def raw(**overrides):
        result = {
            "casts": [],
            "friendlyCasts": [],
            "damage": [],
            "debuffs": [],
            "enemyBuffs": [],
            "friendlyBuffs": [],
            "deaths": [],
            "trackedDamageTaken": [],
        }
        result.update(overrides)
        return result

    def test_wave_frame_mutations_count_as_one_carrier_hit(self):
        raw = self.raw(
            debuffs=[
                {"timestamp": 1_000, "type": "applydebuff", "abilityGameID": 1295360, "targetID": 2},
                {"timestamp": 2_000, "type": "applydebuff", "abilityGameID": 1292403, "targetID": 2},
                {"timestamp": 2_030, "type": "applydebuffstack", "abilityGameID": 1292403, "targetID": 2, "stack": 2},
                {"timestamp": 2_080, "type": "refreshdebuff", "abilityGameID": 1292403, "targetID": 2},
                {"timestamp": 2_100, "type": "applydebuff", "abilityGameID": 1301268, "targetID": 1},
                {"timestamp": 2_100, "type": "applydebuff", "abilityGameID": 1301268, "targetID": 2},
                {"timestamp": 3_000, "type": "removedebuff", "abilityGameID": 1295360, "targetID": 2},
            ],
            damage=[{"timestamp": 2_020, "type": "damage", "abilityGameID": 1292403, "targetID": 2, "amount": 1234}],
        )

        result = analyze_ulatek(self.fight, self.actor_map, self.players, raw)["wavesAndEggs"]

        self.assertEqual(result["hitCount"], 1)
        self.assertEqual(result["eggCarrierHitCount"], 1)
        self.assertEqual(result["earlyHatchCount"], 1)
        self.assertEqual(result["hits"][0]["amount"], 1234)

    def test_same_frame_egg_removal_before_wave_is_still_attributed(self):
        raw = self.raw(
            debuffs=[
                {"timestamp": 1_000, "type": "applydebuff", "abilityGameID": 1295360, "targetID": 2},
                {"timestamp": 10_000, "type": "removedebuff", "abilityGameID": 1295360, "targetID": 2},
                {"timestamp": 10_013, "type": "applydebuff", "abilityGameID": 1292403, "targetID": 2},
                {"timestamp": 10_014, "type": "applydebuffstack", "abilityGameID": 1301268, "targetID": 1, "stack": 2},
            ],
            damage=[
                {"timestamp": 10_013, "type": "damage", "abilityGameID": 1292403, "targetID": 2, "amount": 4321},
            ],
        )

        result = analyze_ulatek(self.fight, self.actor_map, self.players, raw)["wavesAndEggs"]

        self.assertEqual(result["eggCarrierHitCount"], 1)
        self.assertEqual(result["earlyHatchCount"], 1)
        self.assertEqual(result["hits"][0]["eggRemovedAfterMs"], -13)
        self.assertEqual(result["hits"][0]["hatchEvidence"]["toStack"], 2)

    def test_fang_break_only_flags_stack_above_safe_limit(self):
        raw = self.raw(debuffs=[
            {"timestamp": 10_000, "type": "applydebuff", "abilityGameID": 1311611, "targetID": 2},
            {"timestamp": 11_220, "type": "applydebuff", "abilityGameID": 1311611, "targetID": 3},
            {"timestamp": 15_000, "type": "removedebuff", "abilityGameID": 1311611, "targetID": 2},
            {"timestamp": 15_010, "type": "applydebuff", "abilityGameID": 1311609, "targetID": 1},
            {"timestamp": 18_000, "type": "removedebuff", "abilityGameID": 1311611, "targetID": 3},
            {"timestamp": 18_010, "type": "applydebuffstack", "abilityGameID": 1311609, "targetID": 1, "stack": 3},
        ])

        result = analyze_ulatek(self.fight, self.actor_map, self.players, raw)["fangs"]

        self.assertEqual(result["wrongBreakCount"], 1)
        self.assertEqual(len(result["rounds"]), 1)
        self.assertEqual(result["rounds"][0]["targetCount"], 2)
        self.assertEqual((result["rounds"][0]["breaks"][0]["fromStack"], result["rounds"][0]["breaks"][0]["toStack"]), (0, 1))
        self.assertFalse(result["rounds"][0]["breaks"][0]["wrong"])
        self.assertTrue(result["rounds"][0]["breaks"][1]["wrong"])

    def test_critical_counts_actual_non_tank_melee_and_wrath_once(self):
        raw = self.raw(
            casts=[
                {"timestamp": 20_000, "type": "cast", "abilityGameID": 1298367, "sourceID": 90, "targetID": 2},
                {"timestamp": 30_000, "type": "begincast", "abilityGameID": 1290779, "sourceID": 91},
                {"timestamp": 36_000, "type": "cast", "abilityGameID": 1290779, "sourceID": 91},
            ],
            damage=[
                {"timestamp": 20_100, "type": "damage", "abilityGameID": 1298369, "sourceID": 90, "targetID": 2, "amount": 100},
                {"timestamp": 20_200, "type": "damage", "abilityGameID": 1298369, "sourceID": 90, "targetID": 2, "amount": 100},
                {"timestamp": 40_000, "type": "damage", "abilityGameID": 1, "sourceID": 91, "targetID": 2, "amount": 500},
                {"timestamp": 40_100, "type": "damage", "abilityGameID": 1, "sourceID": 91, "targetID": 2, "amount": 0, "hitType": 7},
                {"timestamp": 40_200, "type": "damage", "abilityGameID": 1, "sourceID": 91, "targetID": 1, "amount": 900},
            ],
        )

        result = analyze_ulatek(self.fight, self.actor_map, self.players, raw)["critical"]

        self.assertEqual(result["nonTankMotherWrath"]["castCount"], 1)
        self.assertEqual(result["nonTankMelee"]["hitCount"], 1)
        self.assertEqual(result["nonTankMelee"]["totalDamage"], 500)
        self.assertEqual(result["malice"]["completedCount"], 1)

    def test_rage_window_sums_heart_damage_rocks_and_deaths(self):
        raw = self.raw(
            enemyBuffs=[
                {"timestamp": 10_000, "type": "applybuff", "abilityGameID": 1286860, "targetID": 90},
                {"timestamp": 30_000, "type": "removebuff", "abilityGameID": 1286860, "targetID": 90},
            ],
            trackedDamageTaken=[
                {"timestamp": 12_000, "type": "damage", "abilityGameID": 123, "sourceID": 2, "amount": 10_000},
                {"timestamp": 15_000, "type": "damage", "abilityGameID": 123, "sourceID": 3, "amount": 20_000},
            ],
            damage=[{"timestamp": 18_000, "type": "damage", "abilityGameID": 1286885, "targetID": 2, "amount": 3_000}],
            deaths=[{"timestamp": 19_000, "type": "death", "targetID": 2, "killingAbilityGameID": 1286885}],
        )

        result = analyze_ulatek(self.fight, self.actor_map, self.players, raw)["rage"]

        self.assertEqual(result["rounds"][0]["heartDamage"], 30_000)
        self.assertEqual(result["rounds"][0]["fallingDebrisHitCount"], 1)
        self.assertEqual(result["rounds"][0]["deathCount"], 1)


if __name__ == "__main__":
    unittest.main()
