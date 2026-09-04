import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOGIN_PAGE = ROOT / "frontend" / "auth" / "login.html"


class LoginFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = LOGIN_PAGE.read_text(encoding="utf-8")

    def test_login_page_shows_version_and_removes_old_slogan(self):
        self.assertIn("v1.3.0", self.page)
        self.assertIn('id="versionButton"', self.page)
        self.assertNotIn("旨在快速帮团长完成团本开荒中问题的定位", self.page)

    def test_release_notice_is_scoped_by_version_and_user(self):
        self.assertIn('id="releaseNotice"', self.page)
        self.assertIn("更新日志以及相关碎碎念", self.page)
        self.assertIn("mythicAnalyzer.releaseNotice.${RELEASE_VERSION}.${userId", self.page)
        self.assertIn("localStorage.setItem(pendingNoticeKey, 'seen')", self.page)
        self.assertIn("versionButton.addEventListener('click'", self.page)
        self.assertIn("noticeModal.scrollTop = 0", self.page)
        self.assertIn("https://github.com/GrimEclipse/wow_raidanalyzer", self.page)
        self.assertIn("所有 Boss 共用的整场 Pull 概览", self.page)
        self.assertIn("同帧多条安全移除的两两归组", self.page)
        self.assertIn("一键分析最新一场 Boss", self.page)

    def test_canvas_has_drifting_constellations_and_comets(self):
        self.assertIn("const linked = stars.filter", self.page)
        self.assertIn("createLinearGradient", self.page)
        self.assertIn("comets.push", self.page)
        self.assertIn("const cometPalettes", self.page)
        self.assertIn("const burst=Math.random()<.28", self.page)
        self.assertIn("nextCometAt=time+1250+Math.random()*3400", self.page)
        self.assertIn("prefers-reduced-motion: reduce", self.page)


if __name__ == "__main__":
    unittest.main()
