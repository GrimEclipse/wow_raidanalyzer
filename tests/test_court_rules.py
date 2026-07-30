import unittest

from analyzer_core.court_rules import evaluate_court_evidence
from boss_plugins.venomous_abyss.court_profiles import COURT_PROFILES


class CourtRuleTests(unittest.TestCase):
    def test_direct_failure_can_count_when_enabled(self):
        result = evaluate_court_evidence(
            COURT_PROFILES["sentinels"],
            [{"ruleKey": "toxic_droplet_missed", "player": "A", "confirmed": True}],
        )
        self.assertTrue(result["cases"][0]["counted"])

    def test_assignment_rule_never_convicts_without_preset(self):
        result = evaluate_court_evidence(
            COURT_PROFILES["vashnik"],
            [{
                "ruleKey": "plague_wave_assignment",
                "player": "A",
                "confirmed": True,
                "assignmentCompliant": False,
            }],
            options={"plagueWaveAssignmentCountEnabled": True},
        )
        self.assertFalse(result["cases"][0]["counted"])
        self.assertEqual(result["cases"][0]["status"], "missing_assignment")

    def test_review_rule_defaults_to_evidence_only(self):
        result = evaluate_court_evidence(
            COURT_PROFILES["sentinels"],
            [{"ruleKey": "red_water_placement", "player": "A", "confirmed": True}],
        )
        self.assertFalse(result["cases"][0]["counted"])
        self.assertEqual(result["cases"][0]["status"], "evidence_only")


if __name__ == "__main__":
    unittest.main()
