import unittest
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SharedReportOverviewFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = (ROOT / "frontend/core/report-plugin-runtime.js").read_text(encoding="utf-8")
        cls.overview = (ROOT / "frontend/report/overview.html").read_text(encoding="utf-8")
        cls.overview_js = (ROOT / "frontend/report/overview.js").read_text(encoding="utf-8")
        cls.sentinels = (
            ROOT / "frontend/report/plugins/venomous_abyss/sentinels/report.html"
        ).read_text(encoding="utf-8")
        cls.sentinels_js = (
            ROOT / "frontend/report/plugins/venomous_abyss/sentinels/report.js"
        ).read_text(encoding="utf-8")
        cls.sentinels_css = (
            ROOT / "frontend/report/plugins/venomous_abyss/sentinels/revision.css"
        ).read_text(encoding="utf-8")
        cls.report_index = (ROOT / "frontend/report/index.html").read_text(encoding="utf-8")

    def test_all_reports_route_through_shared_pull_overview(self):
        self.assertIn('function overviewUrl(sourcePath)', self.runtime)
        self.assertIn('frontend/report/overview.html', self.runtime)
        self.assertIn('function detailUrl(descriptor, sourcePath, fightID)', self.runtime)
        self.assertIn('function storePayload(payload)', self.runtime)
        self.assertIn('function loadPayload(sourcePath)', self.runtime)
        self.assertIn('sessionStorage.setItem', self.runtime)
        self.assertIn('id="pullBoard"', self.overview)
        self.assertIn('按阶段分组', self.overview)
        self.assertIn('MythicReportRuntime.detailUrl', self.overview_js)
        self.assertNotRegex(self.overview_js, r"\breturn\d")

    def test_sentinels_page_is_detail_only_and_has_safe_navigation(self):
        self.assertNotIn('data-tab="overview"', self.sentinels)
        self.assertIn('id="overviewLink"', self.sentinels)
        self.assertIn('href="/"', self.sentinels)
        self.assertIn('new URLSearchParams(location.search).get("fight")', self.sentinels_js)
        self.assertIn('/frontend/report/overview.html?json=', self.sentinels_js)

    def test_safe_collision_renders_time_and_pairing_evidence(self):
        self.assertIn('collision.time || "—"', self.sentinels_js)
        self.assertIn('坐标参考配对', self.sentinels_js)
        self.assertIn('安全消除', self.sentinels_js)

    def test_collision_cards_wrap_as_cards_not_player_names(self):
        self.assertIn("minmax(390px,1fr)", self.sentinels_css)
        self.assertIn("flex-wrap:nowrap", self.sentinels_css)
        self.assertIn("word-break:keep-all", self.sentinels_css)
        self.assertIn(".timeout-burst .effect-line{grid-column:2 / -1}", self.sentinels_css)

    def test_project_report_samples_are_merged_with_local_analysis_files(self):
        self.assertIn('assets/samples/report_manifest.json', self.report_index)
        self.assertIn('appendFiles((await response.json()).files)', self.report_index)

    def test_published_guild_kill_report_has_complete_safe_collision_evidence(self):
        manifest = json.loads((ROOT / "assets/samples/report_manifest.json").read_text(encoding="utf-8"))
        row = next(item for item in manifest["files"] if "GJx48AgjRMt3KrpZ" in item["path"])
        payload = json.loads((ROOT / row["path"]).read_text(encoding="utf-8-sig"))
        pulls = payload["data"]["page1_wipeAnalysis"]
        self.assertTrue(any(pull["fightID"] == 21 and pull["isKill"] for pull in pulls))
        safe_collisions = [
            collision
            for pull in pulls
            for round_row in pull["sentinels"]["helicalToxins"]["rounds"]
            for collision in round_row["collisions"]
            if collision["kind"] == "safe-clear"
        ]
        self.assertTrue(safe_collisions)
        self.assertTrue(all(row.get("time") and row.get("timeMs") is not None for row in safe_collisions))
        self.assertTrue(all(len(row.get("playerIDs") or []) == 2 for row in safe_collisions))


if __name__ == "__main__":
    unittest.main()
