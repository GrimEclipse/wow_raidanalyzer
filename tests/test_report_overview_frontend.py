import unittest
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


if __name__ == "__main__":
    unittest.main()
