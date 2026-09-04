import unittest

from boss_plugins.tidebound_grotto.nymrissa_wavecaller import analyze_nymrissa


class NymrissaAnalyzerTests(unittest.TestCase):
    def test_baseline_mechanics_are_grouped_without_position_blame(self):
        fight = {"id": 10, "startTime": 1_000, "endTime": 101_000}
        actor_map = {1: "Tank", 2: "Mage"}
        players = {
            1: {"id": 1, "name": "Tank", "role": "tank", "classColor": "#fff"},
            2: {"id": 2, "name": "Mage", "role": "range-dps", "classColor": "#3fc7eb"},
        }
        raw = {
            "casts": [
                {"type": "cast", "timestamp": 2_000, "abilityGameID": 1260837},
                {"type": "cast", "timestamp": 10_000, "abilityGameID": 1257614},
                {"type": "cast", "timestamp": 30_000, "abilityGameID": 1284015},
                {"type": "cast", "timestamp": 35_000, "abilityGameID": 1263301},
                {"type": "cast", "timestamp": 90_000, "abilityGameID": 1295086},
            ],
            "damage": [
                {"timestamp": 3_000, "abilityGameID": 1260843, "targetID": 1, "amount": 100},
                {"timestamp": 15_000, "abilityGameID": 1257651, "targetID": 2, "amount": 200},
                {"timestamp": 20_000, "abilityGameID": 1257654, "targetID": 2, "amount": 300},
                {"timestamp": 25_000, "abilityGameID": 1282945, "targetID": 1, "amount": 400},
                {"timestamp": 40_000, "abilityGameID": 1271380, "targetID": 1, "amount": 500},
            ],
            "debuffs": [
                {"type": "applydebuff", "timestamp": 10_500, "abilityGameID": 1257608, "targetID": 2},
                {"type": "applydebuffstack", "timestamp": 50_000, "abilityGameID": 1277386, "targetID": 1, "stack": 3},
            ],
        }

        result = analyze_nymrissa(fight, actor_map, players, raw)

        self.assertEqual(result["abyssalRain"]["rounds"][0]["hitCount"], 1)
        self.assertEqual(result["abyssalRain"]["drenched"][0]["maxStack"], 3)
        self.assertEqual(result["frostBarrage"]["rounds"][0]["targets"][0]["player"], "Mage")
        self.assertEqual(result["frostBarrage"]["rounds"][0]["orbHitCount"], 1)
        self.assertEqual(result["transitions"][0]["addWaveCount"], 1)
        self.assertEqual(result["transitions"][0]["pulsingHitCount"], 1)
        self.assertEqual(result["hazardHits"][0]["spellID"], 1257654)
        self.assertEqual(result["tankPressure"][0]["player"], "Tank")
        self.assertTrue(result["enrage"]["triggered"])


if __name__ == "__main__":
    unittest.main()
