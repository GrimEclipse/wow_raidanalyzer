import unittest

from analyzer_core.contracts import (
    apply_analysis_contract,
    build_analysis_identity,
    infer_analysis_capabilities,
)


class AnalysisContractTests(unittest.TestCase):
    def sample_result(self):
        return {
            "meta": {
                "version": "12.1",
                "raidKey": "venomous_abyss",
                "bossKey": "nakzali",
                "analyzedReports": ["report-b", "report-a", "report-a"],
            },
            "data": {"page1_wipeAnalysis": [{"date": "2026-09-01"}]},
        }

    def test_identity_is_stable_and_normalizes_reports(self):
        first = build_analysis_identity(self.sample_result())
        second_result = self.sample_result()
        second_result["meta"]["analyzedReports"] = ["report-a", "report-b"]
        second = build_analysis_identity(second_result)
        self.assertEqual(first, second)
        self.assertEqual(first["reports"], ["report-a", "report-b"])
        self.assertTrue(first["key"].startswith("12.1/venomous_abyss/nakzali/"))

    def test_contract_is_backward_compatible_metadata(self):
        result = self.sample_result()
        returned = apply_analysis_contract(result)
        self.assertIs(returned, result)
        self.assertEqual(result["documentType"], "wow-raid-analysis")
        self.assertEqual(result["schemaVersion"], 1)
        self.assertEqual(result["meta"]["analysisId"], result["meta"]["analysisIdentity"]["key"])
        self.assertEqual(result["meta"]["capabilitySchemaVersion"], 1)

    def test_legacy_crown_output_infers_mistake_and_replay_capabilities(self):
        result = self.sample_result()
        result["meta"]["features"] = {"interrupts": False, "finalVerdict": True}
        result["meta"]["courtConfig"] = {
            "verdictPointsPerCount": 12,
            "verdictTankMultiplier": 0.5,
        }
        result["data"].update({
            "page1_wipeAnalysis": [{
                "date": "2026-09-01",
                "crownOfTheCosmos": {"fieldAudit": {"summary": {}}},
            }],
            "page2_avoidableBoard": {"waterOutliers": [{"name": "A"}]},
            "page3_courtBoard": {"waterOutliers": [{"name": "A"}]},
            "page4_finalVerdict": [],
        })
        apply_analysis_contract(result)
        capabilities = result["meta"]["capabilities"]
        self.assertTrue(capabilities["mistakes"]["enabled"])
        self.assertEqual(capabilities["avoidable"]["renderer"], "mistake-tracker")
        self.assertTrue(capabilities["verdict"]["enabled"])
        self.assertTrue(capabilities["replay"]["enabled"])
        self.assertFalse(capabilities["interrupts"]["enabled"])
        self.assertEqual(result["meta"]["mistakeTracker"]["pointsPerUnit"], 12)
        self.assertEqual(result["meta"]["mistakeTracker"]["roleMultipliers"]["tank"], 0.5)

    def test_legacy_lura_output_uses_generic_avoidable_and_interrupt_panels(self):
        result = self.sample_result()
        result["meta"]["bossKey"] = "midnight_falls"
        result["data"]["page2_avoidableBoard"] = {"skyGlaive": [{"name": "A"}]}
        capabilities = infer_analysis_capabilities(result)
        self.assertTrue(capabilities["avoidable"]["enabled"])
        self.assertEqual(capabilities["avoidable"]["renderer"], "generic-avoidable")
        self.assertFalse(capabilities["mistakes"]["enabled"])
        self.assertTrue(capabilities["interrupts"]["enabled"])

    def test_legacy_lightblind_output_preserves_dispel_and_explicit_interrupt_flag(self):
        result = self.sample_result()
        result["meta"]["bossKey"] = "lightblinded_vanguard"
        result["meta"]["features"] = {"interrupts": False, "dispels": True}
        result["data"]["page2_avoidableBoard"] = {"holyFire": [{"name": "A"}]}
        result["data"]["page3_dispelAnalysis"] = {"enabled": True, "fights": [{}]}
        capabilities = infer_analysis_capabilities(result)
        self.assertTrue(capabilities["avoidable"]["enabled"])
        self.assertTrue(capabilities["dispels"]["enabled"])
        self.assertFalse(capabilities["interrupts"]["enabled"])

    def test_explicit_capability_overrides_legacy_inference(self):
        result = self.sample_result()
        result["meta"]["bossKey"] = "midnight_falls"
        result["meta"]["capabilities"] = {
            "interrupts": {"enabled": False, "renderer": "custom-interrupts"},
            "replay": True,
        }
        capabilities = infer_analysis_capabilities(result)
        self.assertFalse(capabilities["interrupts"]["enabled"])
        self.assertEqual(capabilities["interrupts"]["renderer"], "custom-interrupts")
        self.assertTrue(capabilities["replay"]["enabled"])


if __name__ == "__main__":
    unittest.main()
