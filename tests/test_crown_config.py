import unittest

from boss_plugins.void_spire.crown_of_the_cosmos import (
    P3_LINE_DEATH_ID,
    analyze_gravity_attribution,
    resolve_crown_analysis_config,
)


class CrownConfigTests(unittest.TestCase):
    def test_gravity_defaults_to_evidence_only(self):
        config = resolve_crown_analysis_config()
        self.assertEqual(config["gravityResponsibilityMode"], "evidence_only")
        self.assertEqual(config["gravityMassDeathMinimum"], 3)
        self.assertEqual(config["gravityClusterWindowMs"], 1500)

    def test_gravity_evidence_keeps_group_intervals(self):
        deaths = [
            {"timestamp": 10_000, "targetID": 1, "killingAbilityGameID": P3_LINE_DEATH_ID},
            {"timestamp": 10_400, "targetID": 2, "killingAbilityGameID": P3_LINE_DEATH_ID},
            {"timestamp": 11_100, "targetID": 3, "killingAbilityGameID": P3_LINE_DEATH_ID},
        ]
        rows = analyze_gravity_attribution(
            {"startTime": 0, "endTime": 20_000},
            {1: "甲", 2: "乙", 3: "丙"},
            deaths,
            [],
            cluster_window_ms=1_000,
            minimum_deaths=3,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["players"], ["甲", "乙", "丙"])
        self.assertEqual(rows[0]["deathIntervalsMs"], [400, 700])
        self.assertEqual(rows[0]["clusterDurationMs"], 1100)

    def test_gravity_minimum_is_configurable(self):
        deaths = [
            {"timestamp": 10_000, "targetID": 1, "killingAbilityGameID": P3_LINE_DEATH_ID},
            {"timestamp": 10_400, "targetID": 2, "killingAbilityGameID": P3_LINE_DEATH_ID},
        ]
        rows = analyze_gravity_attribution(
            {"startTime": 0, "endTime": 20_000},
            {1: "甲", 2: "乙"},
            deaths,
            [],
            minimum_deaths=3,
        )
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
