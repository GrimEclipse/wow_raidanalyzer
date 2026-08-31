import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CALENDAR_FRONTEND = ROOT / "frontend" / "tools" / "raid-calendar"


class RaidCalendarFrontendTests(unittest.TestCase):
    def test_weekday_labels_are_centered(self):
        styles = (CALENDAR_FRONTEND / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".weekday-row { gap: 7px; padding: 0 0 7px; color: #687784; font-size: 11px; text-align: center; }", styles)

    def test_recipient_options_keep_each_players_class_color(self):
        app = (CALENDAR_FRONTEND / "app.js").read_text(encoding="utf-8")
        self.assertIn('const color = CLASS_COLORS[player.classKey] || "#edf2f7";', app)
        self.assertIn('style="color:${color}"', app)
        self.assertIn('$("#recipientSelect").style.color = playerColor', app)

    def test_allocation_item_links_enable_dynamic_wowhead_tooltips(self):
        page = (CALENDAR_FRONTEND / "index.html").read_text(encoding="utf-8")
        app = (CALENDAR_FRONTEND / "app.js").read_text(encoding="utf-8")
        self.assertIn('/assets/vendor/wow-tooltips.js?v=3', page)
        self.assertNotIn("https://wow.zamimg.com/js/tooltips.js", page)
        self.assertIn("iconizeLinks: false", page)
        self.assertIn('data-wowhead="domain=cn"', app)
        self.assertIn("function refreshWowheadTooltips()", app)
        self.assertIn("window.WH.Tooltips.refreshLinks()", app)

    def test_progression_day_can_be_toggled_without_touching_reset_settings(self):
        page = (CALENDAR_FRONTEND / "index.html").read_text(encoding="utf-8")
        app = (CALENDAR_FRONTEND / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="progressionToggle"', page)
        self.assertIn("async function toggleProgressionDay()", app)
        self.assertIn("progressionOverride = !wasProgression", app)
        self.assertNotIn("mythicCadenceWeeks", app[app.index("async function toggleProgressionDay()"):app.index("function renderRecipientOptions()")])

    def test_roster_class_options_keep_individual_class_colors(self):
        app = (CALENDAR_FRONTEND / "app.js").read_text(encoding="utf-8")
        self.assertIn('style="color:${CLASS_COLORS[key] || "#edf2f7"}"', app)
        self.assertIn('event.target.style.color = CLASS_COLORS[event.target.value]', app)


if __name__ == "__main__":
    unittest.main()
