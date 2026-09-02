import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class HomeAndCalendarFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.calendar = (
            ROOT / "frontend/tools/raid-calendar/index.html"
        ).read_text(encoding="utf-8")
        cls.calendar_js = (
            ROOT / "frontend/tools/raid-calendar/app.js"
        ).read_text(encoding="utf-8")
        cls.calendar_css = (
            ROOT / "frontend/tools/raid-calendar/styles.css"
        ).read_text(encoding="utf-8")
        cls.online = (
            ROOT / "frontend/tools/analysis-runner/index.html"
        ).read_text(encoding="utf-8")

    def test_recent_pull_and_wcl_analysis_are_primary_features(self):
        primary, experimental = self.home.split('<section class="mt-10">', 1)
        self.assertIn("当日最近 Pull 分析", primary)
        self.assertIn("WCL 日志分析", primary)
        self.assertIn("单专精战斗复盘", experimental)
        self.assertIn("大秘境抄轴", experimental)

    def test_blackmark_history_is_descending_paginated_and_color_coded(self):
        self.assertIn('id="blackHistoryPagination"', self.calendar)
        self.assertIn("BLACK_HISTORY_PAGE_SIZE = 8", self.calendar_js)
        self.assertIn(".sort((left, right)", self.calendar_js)
        self.assertIn("blackHistoryPage = 1", self.calendar_js)
        self.assertIn(".history-card.black", self.calendar_css)
        self.assertIn(".history-card.red", self.calendar_css)
        self.assertIn(".history-card.neutral", self.calendar_css)

    def test_online_progress_has_staged_motion_and_download_action(self):
        self.assertIn('id="progressStage"', self.online)
        self.assertIn('id="progressElapsed"', self.online)
        self.assertIn('id="downloadLink"', self.online)
        self.assertIn("progress-scan", self.online)
        self.assertIn("data.downloadUrl || downloadUrl", self.online)


if __name__ == "__main__":
    unittest.main()
