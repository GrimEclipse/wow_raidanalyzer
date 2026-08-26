import json
import unittest
from pathlib import Path

from spec_plugins.paladin.holy import analyze_comparison
from spec_plugins.registry import get_spec_analyzer
from spec_plugins.stub import analyze_comparison as stub_analyzer
from tools.export_spec_comparison import render_standalone


ROOT = Path(__file__).resolve().parents[1]


def bundle(name, casts=None, buffs=None, resources=None, duration=60000, combatant_info=None):
    return {
        "identity": {"playerName": name, "role": "primary", "fightId": 1},
        "actor": {"id": 7, "subType": "Paladin"},
        "spec": "Holy",
        "fight": {"id": 1, "name": "Boss", "startTime": 1000, "endTime": 1000 + duration},
        "casts": casts or [],
        "buffs": buffs or [],
        "resources": resources or [],
        "abilityNames": {},
        "combatantInfo": combatant_info or {},
    }


class SpecComparisonTests(unittest.TestCase):
    def test_registry_returns_holy_and_honest_stub(self):
        self.assertIs(get_spec_analyzer("Paladin", "Holy"), analyze_comparison)
        self.assertIs(get_spec_analyzer("Mage", "Arcane"), stub_analyzer)

    def test_begincast_is_not_counted_as_successful_flash(self):
        casts = [
            {"timestamp": 2000, "type": "cast", "abilityGameID": 200025},
            {"timestamp": 3000, "type": "begincast", "abilityGameID": 19750},
            {"timestamp": 3000, "type": "cast", "abilityGameID": 19750},
        ]
        result = analyze_comparison(bundle("A", casts), bundle("B", casts))
        primary = result["players"]["primary"]
        flash = next(row for row in primary["casts"] if row["abilityId"] == 19750)
        self.assertEqual(flash["count"], 1)
        self.assertEqual(flash["windowCount"], 1)
        self.assertEqual(primary["castContinuity"]["unfinishedCount"], 0)

    def test_unmatched_begincast_is_reported(self):
        casts = [{"timestamp": 3000, "type": "begincast", "abilityGameID": 19750}]
        result = analyze_comparison(bundle("A", casts), bundle("B"))
        continuity = result["players"]["primary"]["castContinuity"]
        self.assertEqual(continuity["unfinishedCount"], 1)
        self.assertEqual(continuity["unfinished"][0]["abilityId"], 19750)

    def test_resource_ledger_keeps_total_waste(self):
        resources = [{
            "timestamp": 2000, "resourceChangeType": 9, "resourceChange": 1,
            "waste": 1, "maxResourceAmount": 5, "abilityGameID": 20473,
        }]
        result = analyze_comparison(bundle("A", resources=resources), bundle("B"))
        self.assertEqual(result["players"]["primary"]["resourceLedger"]["waste"], 1)

    def test_combatant_stats_include_item_level_and_secondary_ratings(self):
        info = {
            "gear": [{"id": 1, "itemLevel": 300}, {"id": 2, "itemLevel": 310}, {"id": 3, "itemLevel": 1}],
            "critSpell": 585,
            "hasteSpell": 752,
            "mastery": 1141,
            "versatilityHealingDone": 297,
        }
        result = analyze_comparison(bundle("A", combatant_info=info), bundle("B"))
        stats = result["players"]["primary"]["combatantStats"]
        self.assertEqual(stats["itemLevel"], 305.0)
        self.assertEqual(stats["criticalStrike"], 585)
        self.assertEqual(stats["versatility"], 297)

    def test_frontend_and_snapshot_marker_are_copyable(self):
        page = (ROOT / "frontend" / "tools" / "spec-comparison" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="downloadHtml"', page)
        self.assertIn("增益覆盖对比", page)
        self.assertIn("未完成读条与施法空档", page)
        self.assertIn("开战属性对比", page)
        self.assertIn('data-wowhead="domain=cn&amp;dd=15"', page)
        self.assertIn("https://www.wowhead.com/cn/spell=", page)
        self.assertNotIn("spell-fallback", page)
        self.assertNotIn("美德分析窗口", page)
        self.assertIn("new Set([431381,431522])", page)
        self.assertNotIn("MYTHIC ANALYZER", page)
        self.assertNotIn("读完就能用的结论", page)
        html = render_standalone({"kind": "single-fight-spec-comparison", "schemaVersion": 1})
        self.assertIn('"single-fight-spec-comparison"', html)
        self.assertNotIn('<script id="embedded-data" type="application/json">{}</script>', html)

    def test_routes_and_catalog_are_registered(self):
        server = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertIn('"/spec-compare": "/frontend/tools/spec-comparison/index.html"', server)
        self.assertIn('"/spec_catalog.json"', server)
        catalog = json.loads((ROOT / "spec_catalog.json").read_text(encoding="utf-8"))
        self.assertEqual(catalog["specializations"][0]["key"], "paladin-holy")


if __name__ == "__main__":
    unittest.main()
