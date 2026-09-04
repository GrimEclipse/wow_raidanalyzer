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
        cls.account = (
            ROOT / "frontend/auth/account.html"
        ).read_text(encoding="utf-8")

    def test_recent_pull_and_wcl_analysis_are_primary_features(self):
        primary, experimental = self.home.split('<footer id="adminLab" class="lab" hidden>', 1)
        self.assertIn("分析最新一场 Boss", primary)
        self.assertIn("高级选择 · 指定 Report / Fight", primary)
        self.assertIn("整晚日志分析", primary)
        self.assertIn("打开本地分析 JSON", primary)
        self.assertIn("Avalon 工会运营", primary)
        self.assertIn("单专精战斗复盘", experimental)
        self.assertIn("大秘境抄轴", experimental)

    def test_home_uses_one_random_chinese_line_and_admin_only_labs(self):
        self.assertNotIn("Raid intelligence, without the detour", self.home)
        self.assertNotIn("刚灭的这一把", self.home)
        self.assertIn("刚刚是谁把蛋踩出来的？", self.home)
        self.assertIn("让我贪完这个棱彩飞弹……", self.home)
        self.assertIn("让我们看看是谁干了……", self.home)
        self.assertIn("$('heroLine').textContent=lines[randomIndex()]", self.home)
        self.assertIn("$('adminLab').hidden=!me.isAdmin", self.home)

    def test_home_can_reopen_release_notes_and_submit_feedback(self):
        self.assertIn('id="releaseNotesButton"', self.home)
        self.assertIn('id="releaseNotes"', self.home)
        self.assertIn("$('releaseNotesButton').onclick=openReleaseNotes", self.home)
        self.assertIn("$('dismissReleaseNotes').onclick=closeReleaseNotes", self.home)
        self.assertIn("https://github.com/GrimEclipse/wow_raidanalyzer/issues/new", self.home)

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

    def test_account_embeds_the_complete_wcl_client_guide(self):
        self.assertIn("WCL V2 Client 完整图文指引（5 步）", self.account)
        self.assertIn("不要勾选 Public Client", self.account)
        self.assertIn("Client Secret 只显示这一次", self.account)
        for index in range(1, 7):
            self.assertIn(f"/frontend/assets/guides/wcl-v2/0{index}-", self.account)
        self.assertIn("https://github.com/GrimEclipse/wow_raidanalyzer/issues/new", self.account)


if __name__ == "__main__":
    unittest.main()
