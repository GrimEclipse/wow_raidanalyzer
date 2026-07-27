import unittest

from analyzer_core.contracts import apply_analysis_contract, build_analysis_identity


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


if __name__ == "__main__":
    unittest.main()
