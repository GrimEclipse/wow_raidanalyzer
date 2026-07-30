import json
import unittest
from pathlib import Path

from tools.build_zone54_raid_guide import build_document, infer_tags


ROOT = Path(__file__).resolve().parents[1]


class Zone54RaidGuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        discovery = json.loads(
            (ROOT / "docs/zone54_spell_discovery.json").read_text(encoding="utf-8")
        )
        authored = json.loads(
            (ROOT / "docs/zone54_raid_guide_source.json").read_text(encoding="utf-8")
        )
        timelines = json.loads(
            (ROOT / "docs/zone54_boss_timelines.json").read_text(encoding="utf-8")
        )
        cls.document = build_document(discovery, authored, timelines)

    def test_guide_contains_all_bosses_and_keeps_ulatek_as_expected_untested(self):
        self.assertEqual(len(self.document["bosses"]), 8)
        ulatek = next(
            boss for boss in self.document["bosses"] if boss["key"] == "ulatek"
        )
        self.assertTrue(ulatek["expectedUntested"])
        self.assertFalse(ulatek["hasHeroicEvidence"])
        self.assertFalse(ulatek["hasMythicEvidence"])

    def test_reviewed_boss_keeps_authored_energy_and_mechanics(self):
        nakzali = next(
            boss for boss in self.document["bosses"] if boss["key"] == "nakzali"
        )
        self.assertEqual(nakzali["reviewStatus"], "reviewed")
        self.assertEqual(nakzali["energy"]["maximum"], 100)
        self.assertGreaterEqual(len(nakzali["mechanics"]), 6)
        self.assertTrue(all(row.get("leaderDetails") for row in nakzali["mechanics"]))
        self.assertTrue(all(row.get("wipePoints") for row in nakzali["mechanics"]))
        barrage = next(
            row for row in nakzali["mechanics"]
            if row["evidenceType"] == "tank-distance-aoe"
        )
        self.assertEqual(barrage["leaderSpellIDs"], [1284103])
        self.assertTrue(any("直线飞行" in row for row in barrage["leaderDetails"]))
        self.assertTrue(any("挡住实体灵魂" in row for row in barrage["leaderDetails"]))
        possession = next(
            spell for spell in nakzali["spells"] if spell["spellID"] == 1284103
        )
        self.assertEqual(possession["reviewStatus"], "reviewed")
        self.assertIn("playerDebuffs", possession["categories"])
        self.assertIn("enemyCasts", possession["categories"])

    def test_auto_tags_are_explicitly_uncertain_for_avoidable_candidates(self):
        tags = infer_tags("Raging Shadow Wave", ["damageAbilities"])
        self.assertIn("疑似可躲 / 需复核", tags)
        self.assertIn("伤害", tags)

    def test_static_page_uses_ptr_tooltips_and_generated_payload(self):
        page = (ROOT / "zone54-raid-guide.html").read_text(encoding="utf-8")
        self.assertIn("https://wow.zamimg.com/js/tooltips.js", page)
        self.assertIn("data-wowhead=\"domain=ptr&amp;dd=15\"", page)
        self.assertIn('class="spell-icon-link"', page)
        self.assertIn('class="spell-copy"', page)
        self.assertNotIn('class="spell-link"', page)
        self.assertIn(".spell-icon-link .iconsmall > ins", page)
        self.assertIn("background-size: cover !important", page)
        self.assertIn(".mechanic-card.mythic", page)
        self.assertIn('<span class="spell-id">ID: ${spellID}</span>', page)
        self.assertNotIn("function evidenceCell", page)
        self.assertIn("assets/vendor/zone54-raid-guide-data.js", page)
        self.assertIn("Boss 切换", page)

    def test_nakzali_contains_observed_heroic_and_mythic_timeline_markers(self):
        nakzali = next(
            boss for boss in self.document["bosses"] if boss["key"] == "nakzali"
        )
        heroic = nakzali["timelines"]["heroic"]
        mythic = nakzali["timelines"]["mythic"]
        heroic_p2 = next(
            marker for marker in heroic["phaseMarkers"] if marker["phase"] == "p2"
        )
        mythic_p2 = next(
            marker for marker in mythic["phaseMarkers"] if marker["phase"] == "p2"
        )
        self.assertEqual(heroic_p2["spellID"], 1290003)
        self.assertEqual(heroic_p2["timeMs"], 328208)
        self.assertEqual(mythic_p2["timeMs"], 206926)
        self.assertTrue(heroic["kill"])
        self.assertTrue(mythic["kill"])

    def test_confirmed_chinese_names_are_preserved_without_forcing_all_rows(self):
        nakzali = next(
            boss for boss in self.document["bosses"] if boss["key"] == "nakzali"
        )
        possession = next(
            spell for spell in nakzali["spells"] if spell["spellID"] == 1284103
        )
        unconfirmed = next(
            spell for spell in nakzali["spells"] if spell["spellID"] == 1285681
        )
        self.assertEqual(possession["nameZh"], "附身弹幕")
        self.assertIsNone(unconfirmed["nameZh"])

    def test_sentinels_keeps_wcl_instance_ids_and_mythic_private_aura(self):
        sentinels = next(
            boss for boss in self.document["bosses"] if boss["key"] == "sentinels"
        )
        self.assertEqual(sentinels["reviewStatus"], "reviewed")
        helical = next(
            mechanic for mechanic in sentinels["mechanics"]
            if mechanic["evidenceType"] == "exact-stack-pairing"
        )
        mythic = next(
            mechanic for mechanic in sentinels["mechanics"]
            if mechanic["priority"] == "mythic"
        )
        self.assertIn(1284590, helical["spellIDs"])
        self.assertIn(1284813, helical["spellIDs"])
        self.assertIn(1311488, helical["spellIDs"])
        self.assertEqual(
            mythic["spellIDs"], [1296878, 1296880, 1296882, 1296962]
        )
        override = next(
            spell for spell in sentinels["spells"] if spell["spellID"] == 1296880
        )
        self.assertEqual(override["nameEn"], "Shifting Protovenom")
        self.assertEqual(override["nameZh"], "变换原毒")
        eruption = next(
            spell for spell in sentinels["spells"] if spell["spellID"] == 1296962
        )
        self.assertEqual(eruption["nameZh"], "原毒喷发")
        self.assertEqual(sentinels["energy"]["title"], "循环与转阶段")
        self.assertTrue(all(row.get("leaderDetails") for row in sentinels["mechanics"]))
        self.assertTrue(all(row.get("wipePoints") for row in sentinels["mechanics"]))
        stasis = next(
            row for row in sentinels["mechanics"]
            if row["evidenceType"] == "exact-stack-pairing"
        )
        self.assertIn("合星座", stasis["title"])
        self.assertTrue(any("建立足够仇恨" in row for row in stasis["leaderDetails"]))
        miasma = next(
            row for row in sentinels["mechanics"]
            if row["evidenceType"] == "soak-then-placement"
        )
        self.assertTrue(any("分散到各自放水点" in row for row in miasma["leaderDetails"]))
        self.assertTrue(any("红水确实落地后" in row for row in miasma["leaderDetails"]))
        injection = next(
            row for row in sentinels["mechanics"]
            if row["evidenceType"] == "tank-stack-placement"
        )
        self.assertTrue(any("整轮分场期间不需要" in row for row in injection["leaderDetails"]))
        self.assertEqual(sentinels["energy"]["gaugeLabel"], "转阶段触发")
        self.assertNotIn("狂暴", sentinels["energy"]["gaugeLabel"])
        self.assertEqual(
            sentinels["timelines"]["heroic"]["phaseMarkers"][1]["timeMs"], 46225
        )
        self.assertEqual(
            sentinels["timelines"]["mythic"]["phaseMarkers"][1]["timeMs"], 46484
        )

    def test_vashnik_uses_fixed_timeline_and_directional_wave_evidence(self):
        vashnik = next(
            boss for boss in self.document["bosses"] if boss["key"] == "vashnik"
        )
        self.assertEqual(vashnik["reviewStatus"], "reviewed")
        self.assertIn("固定时间轴", vashnik["summary"])
        self.assertIn("三座能量之泉", vashnik["summary"])
        self.assertEqual(vashnik["energy"]["displayMode"], "rules")
        wave = next(
            mechanic for mechanic in vashnik["mechanics"]
            if mechanic["evidenceType"] == "assigned-directional-wave"
        )
        self.assertIn(1295798, wave["spellIDs"])
        self.assertIn("Assignment", wave["details"][3])
        self.assertEqual(wave["leaderSpellIDs"], [1280935])
        self.assertGreaterEqual(len(wave["wipePoints"]), 3)
        infection = next(
            mechanic for mechanic in vashnik["mechanics"]
            if mechanic["evidenceType"] == "infection-resolution"
        )
        self.assertIn("冥河喷发", infection["wipePoints"][0])
        self.assertIn("个人减伤", infection["wipePoints"][2])
        catalyst = next(
            mechanic for mechanic in vashnik["mechanics"]
            if mechanic["evidenceType"] == "unavoidable-raid-aoe"
        )
        self.assertNotIn("wipePoints", catalyst)
        heroic = vashnik["timelines"]["heroic"]
        mythic = vashnik["timelines"]["mythic"]
        self.assertTrue(heroic["kill"])
        self.assertFalse(mythic["kill"])
        self.assertEqual(heroic["phaseMarkers"][1]["timeMs"], 24107)
        self.assertEqual(mythic["phaseMarkers"][1]["timeMs"], 24083)


if __name__ == "__main__":
    unittest.main()
