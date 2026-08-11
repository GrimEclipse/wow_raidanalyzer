import json
import unittest
from pathlib import Path

from tools.build_zone54_raid_guide import build_document, infer_tags


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DATA = (
    ROOT
    / "skills"
    / "venomous-abyss-raid-development"
    / "references"
    / "source-data"
)


class Zone54RaidGuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        discovery = json.loads(
            (SOURCE_DATA / "spell-discovery.json").read_text(encoding="utf-8")
        )
        authored = json.loads(
            (SOURCE_DATA / "raid-guide-source.json").read_text(encoding="utf-8")
        )
        timelines = json.loads(
            (SOURCE_DATA / "boss-timelines.json").read_text(encoding="utf-8")
        )
        cls.document = build_document(discovery, authored, timelines)

    def test_guide_contains_all_bosses_and_keeps_ulatek_as_expected_untested(self):
        self.assertEqual(len(self.document["bosses"]), 9)
        ulatek = next(
            boss for boss in self.document["bosses"] if boss["key"] == "ulatek"
        )
        self.assertTrue(ulatek["expectedUntested"])
        self.assertFalse(ulatek["hasHeroicEvidence"])
        self.assertFalse(ulatek["hasMythicEvidence"])
        nymrissa = next(
            boss for boss in self.document["bosses"]
            if boss["key"] == "nymrissa_wavecaller"
        )
        self.assertEqual(nymrissa["raidKey"], "tidebound_grotto")
        self.assertEqual(nymrissa["nameZh"], "尼姆瑞莎·唤潮者")
        self.assertTrue(nymrissa["image"].endswith("01-nymrissa.jpg"))
        self.assertTrue(nymrissa["hasHeroicEvidence"])
        self.assertTrue(nymrissa["hasMythicEvidence"])

    def test_nymrissa_uses_zone57_wcl_ids_and_fixed_transition_timeline(self):
        nymrissa = next(
            boss for boss in self.document["bosses"]
            if boss["key"] == "nymrissa_wavecaller"
        )
        spells = {spell["spellID"]: spell for spell in nymrissa["spells"]}
        self.assertIn(1257614, spells)
        self.assertIn(1257651, spells)
        self.assertIn(1284015, spells)
        self.assertIn(1281951, spells)
        self.assertIn("heroic", spells[1257614]["observedIn"])
        self.assertIn("mythic", spells[1257614]["observedIn"])
        self.assertEqual(
            spells[1257614]["observedIn"]["mythic"]["provenance"]["fightID"],
            10,
        )

        heroic = nymrissa["timelines"]["heroic"]
        mythic = nymrissa["timelines"]["mythic"]
        self.assertTrue(heroic["kill"])
        self.assertEqual(heroic["reportID"], "zpRDdcafg7hCrT9Y")
        self.assertEqual(mythic["bossPercentage"], 17.79)
        self.assertEqual(mythic["reportID"], "ZmYa6M2QV4hbLCry")
        self.assertEqual(
            [
                marker["timeMs"]
                for marker in mythic["phaseMarkers"]
                if marker["phase"].startswith("bubble-")
            ],
            [26979, 144006, 261042],
        )
        transition = next(
            mechanic for mechanic in nymrissa["mechanics"]
            if mechanic["evidenceType"] == "fixed-add-intermission"
        )
        self.assertEqual(transition["leaderSpellIDs"], [1284015])
        self.assertIn(1263301, transition["spellIDs"])

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
        ignition = next(
            spell for spell in nakzali["spells"] if spell["spellID"] == 1285681
        )
        self.assertEqual(ignition["nameZh"], "盘魂点燃")
        well = next(
            mechanic for mechanic in nakzali["mechanics"]
            if mechanic["title"] == "盘魂之井与能量"
        )
        self.assertTrue(well["important"])
        self.assertIn("治疗预警", well["alerts"])
        self.assertNotIn("roles", well)
        self.assertNotIn("tags", well)
        corpse_blight = next(
            mechanic for mechanic in nakzali["mechanics"]
            if mechanic["evidenceType"] == "priority-add"
        )
        self.assertIn("全团", corpse_blight["summary"])
        self.assertTrue(any("30 秒" in row for row in corpse_blight["details"]))
        self.assertTrue(any("可以叠加" in row for row in corpse_blight["details"]))

    def test_auto_tags_are_explicitly_uncertain_for_avoidable_candidates(self):
        tags = infer_tags("Raging Shadow Wave", ["damageAbilities"])
        self.assertIn("疑似可躲 / 需复核", tags)
        self.assertIn("伤害", tags)

    def test_static_page_uses_chinese_tooltips_and_generated_payload(self):
        page = (ROOT / "frontend" / "tools" / "raid-guide" / "index.html").read_text(encoding="utf-8")
        self.assertIn("https://wow.zamimg.com/js/tooltips.js", page)
        self.assertIn("data-wowhead=\"domain=cn&amp;dd=15\"", page)
        self.assertIn('data-wh-rename-link="true"', page)
        self.assertIn("https://www.wowhead.com/cn/spell=${spellID}", page)
        self.assertTrue(all(
            spell["wowheadUrl"].startswith("https://www.wowhead.com/cn/spell=")
            for boss in self.document["bosses"]
            for spell in boss["spells"]
        ))
        self.assertIn('class="spell-icon-link"', page)
        self.assertIn('class="spell-copy"', page)
        self.assertNotIn('class="spell-link"', page)
        self.assertIn(".spell-icon-link .iconsmall > ins", page)
        self.assertIn("background-size: cover !important", page)
        self.assertIn(".mechanic-card.mythic", page)
        self.assertIn('<span class="spell-id">ID: ${spellID}</span>', page)
        self.assertIn("function mechanicSpellCluster", page)
        self.assertIn("mechanic-spell-icons", page)
        self.assertIn("mechanic-primary-spell", page)
        self.assertIn("附属效果", page)
        self.assertNotIn("related-spell-ids", page)
        self.assertIn('includes("enemyCasts")', page)
        self.assertIn('includes("playerDebuffs")', page)
        self.assertIn("font-variant-numeric: tabular-nums", page)
        self.assertIn("mythic-note", page)
        self.assertIn("常见减员点", page)
        self.assertNotIn("常见灭团点", page)
        self.assertIn("坦克预警", page)
        self.assertIn("伤害输出预警", page)
        self.assertIn("控制/打断预警", page)
        self.assertIn("timeline-combo", page)
        self.assertIn("sourceColor", page)
        self.assertNotIn("function evidenceCell", page)
        self.assertNotIn("人工明细已复核", page)
        self.assertNotIn("流程与分类待复核", page)
        self.assertNotIn("个流程阶段", page)
        self.assertIn("未经过测试 · 阶段未知", page)
        self.assertIn("boss-test-note", page)
        self.assertIn("assets/vendor/zone54-raid-guide-data.js", page)
        self.assertIn("Boss 切换", page)
        self.assertIn("战斗大概时间分析（粗略时间轴）", page)
        self.assertIn("开发 ID 明细", page)
        self.assertNotIn('href="#overview"', page)
        self.assertNotIn('id="overviewText"', page)
        self.assertIn('id="energy"', page)
        self.assertNotIn("用阶段目标说明这一场战斗怎么打，而不是复述单份 WCL。", page)
        self.assertLess(
            page.index('<section id="mechanics"'),
            page.index('<section id="timeline"'),
        )

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

    def test_confirmed_chinese_names_are_preserved(self):
        nakzali = next(
            boss for boss in self.document["bosses"] if boss["key"] == "nakzali"
        )
        possession = next(
            spell for spell in nakzali["spells"] if spell["spellID"] == 1284103
        )
        soulcoil_ignition = next(
            spell for spell in nakzali["spells"] if spell["spellID"] == 1285681
        )
        self.assertEqual(possession["nameZh"], "附身弹幕")
        self.assertEqual(soulcoil_ignition["nameZh"], "盘魂点燃")

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
        self.assertEqual(override["nameZh"], "变幻的原型毒液")
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
        self.assertTrue(any("个人减伤" in row for row in infection["wipePoints"]))
        self.assertIn("伤害随距离衰减", infection["leaderDetails"][1])
        self.assertIn("离开人群放置", infection["leaderDetails"][1])
        self.assertNotIn("全团分散", infection["leaderDetails"][1])
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
        self.assertEqual(
            len([row for row in heroic["events"] if row["spellID"] == 1280935]),
            23,
        )
        self.assertEqual(
            len([row for row in heroic["events"] if row["spellID"] == 1282114]),
            22,
        )
        self.assertEqual(
            len([row for row in mythic["events"] if row["spellID"] == 1282114]),
            11,
        )
        self.assertTrue(all(
            row["sourceName"] == "万毒邪祟者瓦什尼克"
            for row in heroic["events"]
        ))

    def test_lost_explorers_keeps_authored_flow_and_evidence_boundaries(self):
        boss = next(
            row for row in self.document["bosses"]
            if row["key"] == "lostexplorers"
        )
        self.assertEqual(boss["reviewStatus"], "reviewed")
        self.assertEqual(boss["energy"]["maximum"], 4)
        self.assertEqual(len(boss["phases"]), 3)
        self.assertEqual(len(boss["mechanics"]), 10)

        fish = next(
            mechanic for mechanic in boss["mechanics"]
            if mechanic["evidenceType"] == "result-only-interaction-cycle"
        )
        self.assertTrue(any("WCL" in row for row in fish["details"]))
        self.assertTrue(any("1296975" in row for row in fish["details"]))
        self.assertIn(1306145, fish["spellIDs"])
        self.assertIn(1306137, fish["spellIDs"])
        self.assertIn("1296975/1297022/1297024", fish["verification"])

        heroic = boss["timelines"]["heroic"]
        mythic = boss["timelines"]["mythic"]
        self.assertTrue(heroic["kill"])
        self.assertFalse(mythic["kill"])
        fourth = next(
            marker for marker in mythic["phaseMarkers"]
            if marker["phase"] == "cycle-4"
        )
        enrage = next(
            marker for marker in mythic["phaseMarkers"]
            if marker["phase"] == "enrage"
        )
        self.assertEqual(fourth["timeMs"], 374994)
        self.assertEqual(enrage["timeMs"], 439232)
        self.assertFalse(any(event["timeMs"] == 332337 for event in mythic["events"]))
        self.assertFalse(any(
            row["spellID"] in {1286922, 1291933}
            for row in heroic["events"] + mythic["events"]
        ))
        expected_counts = {
            1292104: 2,
            1292779: 1,
            1295891: 1,
            1296021: 6,
            1296062: 13,
            1296094: 3,
            1296249: 2,
            1306145: 3,
        }
        for spell_id, count in expected_counts.items():
            self.assertEqual(
                len([row for row in heroic["events"] if row["spellID"] == spell_id]),
                count,
            )
        source_by_spell = {
            row["spellID"]: row["sourceName"]
            for row in heroic["events"]
        }
        self.assertEqual(source_by_spell[1296062], "大副纳玛")
        self.assertEqual(source_by_spell[1306145], "商人盖博")
        self.assertEqual(
            [row["timeMs"] for row in heroic["events"] if row["spellID"] == 1306145],
            [31029, 155808, 280622],
        )
        self.assertTrue(all(row["eventType"] == "cast" for row in heroic["events"]))
        mythic_counts = {
            1292104: 2,
            1292779: 2,
            1295891: 2,
            1296021: 8,
            1296062: 16,
            1296094: 2,
            1296249: 2,
            1306145: 4,
        }
        for spell_id, count in mythic_counts.items():
            self.assertEqual(
                len([row for row in mythic["events"] if row["spellID"] == spell_id]),
                count,
            )
        self.assertTrue(all(row["eventType"] == "cast" for row in mythic["events"]))
        crate = next(
            mechanic for mechanic in boss["mechanics"]
            if mechanic["evidenceType"] == "mythic-crate-proximity-burst"
        )
        self.assertEqual(crate["priority"], "mythic")
        self.assertIn(1311587, crate["spellIDs"])

    def test_lost_explorers_preserves_only_confirmed_chinese_spell_names(self):
        boss = next(
            row for row in self.document["bosses"]
            if row["key"] == "lostexplorers"
        )
        icebound = next(
            spell for spell in boss["spells"] if spell["spellID"] == 1286922
        )
        blink = next(
            spell for spell in boss["spells"] if spell["spellID"] == 1296021
        )
        blast_wave = next(
            spell for spell in boss["spells"] if spell["spellID"] == 1305844
        )
        self.assertEqual(icebound["nameZh"], "\u51b0\u5c01\u70c8\u7130")
        self.assertEqual(blink["nameZh"], "\u95ea\u73b0\u65b0\u661f")
        self.assertIsNone(blast_wave["nameZh"])

    def test_sszorak_keeps_fixed_wind_cycle_and_mythic_rage_failure(self):
        boss = next(
            row for row in self.document["bosses"] if row["key"] == "sszorak"
        )
        self.assertEqual(boss["reviewStatus"], "reviewed")
        self.assertEqual(boss["energy"]["maximum"], 3)
        self.assertEqual(len(boss["mechanics"]), 7)

        cysts = next(
            mechanic for mechanic in boss["mechanics"]
            if mechanic["evidenceType"] == "two-target-cyst-resource"
        )
        self.assertIn(1305959, cysts["spellIDs"])
        self.assertIn(1287205, cysts["spellIDs"])

        fury = next(
            mechanic for mechanic in boss["mechanics"]
            if mechanic["evidenceType"] == "mythic-minimum-stack-rage-check"
        )
        self.assertEqual(fury["priority"], "mythic")
        self.assertIn(1296898, fury["spellIDs"])
        self.assertIn("1296898", fury["verification"])

        heroic = boss["timelines"]["heroic"]
        mythic = boss["timelines"]["mythic"]
        self.assertTrue(heroic["kill"])
        self.assertFalse(mythic["kill"])
        first_maelstrom = next(
            marker for marker in heroic["phaseMarkers"]
            if marker["phase"] == "maelstrom-1"
        )
        enrage = next(
            marker for marker in mythic["phaseMarkers"]
            if marker["phase"] == "enrage"
        )
        self.assertEqual(first_maelstrom["timeMs"], 111095)
        self.assertEqual(enrage["spellID"], 1296898)
        self.assertEqual(enrage["timeMs"], 157996)
        self.assertIn("30% 易伤", boss["energy"]["rules"][3])
        self.assertEqual(
            [row["timeMs"] for row in heroic["events"] if row["spellID"] == 1285419],
            [43360, 95554, 181450, 233679, 319656, 371826],
        )
        self.assertEqual(
            [row["timeMs"] for row in mythic["events"] if row["spellID"] == 1285419],
            [39007, 86010, 166044],
        )
        heroic_combos = [
            event for event in heroic["events"]
            if event["spellID"] == 1277025
        ]
        mythic_combos = [
            event for event in mythic["events"]
            if event["spellID"] == 1277025
        ]
        self.assertEqual(len(heroic_combos), 6)
        self.assertEqual(len(mythic_combos), 3)
        self.assertEqual(heroic_combos[0]["timeMs"], 5566)
        self.assertEqual(
            [child["spellID"] for child in heroic_combos[0]["children"]],
            [1277002, 1277027, 1287072, 1277002, 1277027],
        )
        self.assertEqual(mythic_combos[0]["timeMs"], 5038)

    def test_sszorak_confirmed_names_keep_unconfirmed_damage_names_english(self):
        boss = next(
            row for row in self.document["bosses"] if row["key"] == "sszorak"
        )
        ravage = next(
            spell for spell in boss["spells"] if spell["spellID"] == 1277002
        )
        sidewind = next(
            spell for spell in boss["spells"] if spell["spellID"] == 1297096
        )
        gash = next(
            spell for spell in boss["spells"] if spell["spellID"] == 1285998
        )
        self.assertEqual(ravage["nameZh"], "\u52ab\u63a0")
        self.assertEqual(sidewind["nameZh"], "\u72c2\u6012\u4fa7\u98ce")
        self.assertIsNone(gash["nameZh"])
        mutilate = next(
            mechanic for mechanic in boss["mechanics"]
            if mechanic["evidenceType"] == "shared-hit-refreshing-dot"
        )
        self.assertIn("少于 5 人", mutilate["summary"])
        self.assertNotIn("PTR", " ".join(mutilate["details"]))
        self.assertTrue(next(
            mechanic for mechanic in boss["mechanics"]
            if mechanic["title"] == "狂怒侧风"
        )["important"])

    def test_twin_fangs_keeps_stack_cycle_and_verified_mythic_interrupts(self):
        boss = next(
            row for row in self.document["bosses"] if row["key"] == "twinfangs"
        )
        self.assertEqual(boss["reviewStatus"], "reviewed")
        self.assertEqual(boss["energy"]["maximum"], 9)
        self.assertEqual(boss["energy"]["gaugeLabel"], "9 层死亡")
        self.assertEqual(len(boss["phases"]), 4)
        self.assertEqual(len(boss["mechanics"]), 11)

        venom = next(
            mechanic for mechanic in boss["mechanics"]
            if mechanic["evidenceType"] == "permanent-stack-death-threshold"
        )
        self.assertIn(1290336, venom["spellIDs"])
        self.assertTrue(any("9 层" in row for row in venom["details"]))

        brood = next(
            mechanic for mechanic in boss["mechanics"]
            if mechanic["evidenceType"] == "mythic-repeating-interrupt-retreat"
        )
        self.assertEqual(brood["priority"], "mythic")
        self.assertIn(1308356, brood["spellIDs"])
        self.assertIn(1308385, brood["spellIDs"])
        self.assertTrue(any("56 次" in row for row in brood["details"]))

        heroic = boss["timelines"]["heroic"]
        mythic = boss["timelines"]["mythic"]
        self.assertTrue(heroic["kill"])
        self.assertFalse(mythic["kill"])
        self.assertEqual(heroic["phaseMarkers"][1]["timeMs"], 154466)
        self.assertEqual(heroic["phaseMarkers"][3]["timeMs"], 324000)
        self.assertEqual(mythic["phaseMarkers"][1]["timeMs"], 140001)
        self.assertEqual(
            mythic["events"][1]["spellID"], 1308356
        )

    def test_twin_fangs_preserves_user_confirmed_chinese_names(self):
        boss = next(
            row for row in self.document["bosses"] if row["key"] == "twinfangs"
        )
        eternal = next(
            spell for spell in boss["spells"] if spell["spellID"] == 1290336
        )
        feast = next(
            spell for spell in boss["spells"] if spell["spellID"] == 1290516
        )
        emergence = next(
            spell for spell in boss["spells"] if spell["spellID"] == 1291404
        )
        self.assertEqual(eternal["nameZh"], "永恒毒液")
        self.assertEqual(feast["nameZh"], "贪婪盛宴")
        self.assertEqual(emergence["nameZh"], "剧毒涌现")

    def test_coiled_altar_keeps_four_stage_flow_and_evidence_boundaries(self):
        boss = next(
            row for row in self.document["bosses"] if row["key"] == "bargained"
        )
        self.assertEqual(boss["reviewStatus"], "reviewed")
        self.assertEqual(len(boss["phases"]), 5)
        self.assertEqual(len(boss["mechanics"]), 12)

        transition = next(
            mechanic for mechanic in boss["mechanics"]
            if mechanic["evidenceType"] == "fixed-regeneration-fragment-intermission"
        )
        self.assertIn(1304032, transition["spellIDs"])
        self.assertTrue(any("35 秒" in row for row in transition["details"]))
        self.assertTrue(any("3%" in row for row in transition["summary"].splitlines()))
        self.assertTrue(any("20%" in row for row in transition["mythicNotes"]))

        manifestation = next(
            mechanic for mechanic in boss["mechanics"]
            if mechanic["evidenceType"] == "facing-controlled-fixate"
        )
        self.assertIn(1310744, manifestation["spellIDs"])
        self.assertIn("不自动判定", manifestation["verification"])

        heroic = boss["timelines"]["heroic"]
        mythic = boss["timelines"]["mythic"]
        self.assertFalse(heroic["kill"])
        self.assertFalse(mythic["kill"])
        self.assertEqual(heroic["phaseMarkers"][1]["timeMs"], 192693)
        self.assertEqual(heroic["phaseMarkers"][3]["timeMs"], 526182)
        self.assertEqual(mythic["phaseMarkers"][1]["timeMs"], 184405)
        self.assertEqual(
            len([row for row in heroic["events"] if row["spellID"] == 1299684]),
            8,
        )
        for spell_id in (1285643, 1286441, 1286895, 1286620):
            self.assertEqual(
                len([row for row in heroic["events"] if row["spellID"] == spell_id]),
                7,
            )
        self.assertEqual(
            len([row for row in mythic["events"] if row["spellID"] == 1299684]),
            8,
        )
        sever = next(row for row in heroic["events"] if row["spellID"] == 1299684)
        deathmarch = next(row for row in heroic["events"] if row["spellID"] == 1285643)
        self.assertEqual(sever["sourceName"], "祖尔加")
        self.assertEqual(deathmarch["sourceName"], "妖术领主玛拉卡斯")
        dreadmarch_mechanic = next(
            mechanic for mechanic in boss["mechanics"]
            if mechanic["evidenceType"] == "mind-control-shield-rescue"
        )
        self.assertEqual(dreadmarch_mechanic["title"], "恐惧行军：打破护盾救人")
        self.assertTrue(dreadmarch_mechanic["important"])
        self.assertTrue(any("两只幽灵" in row for row in dreadmarch_mechanic["leaderDetails"]))
        self.assertTrue(any("滚雪球" in row for row in dreadmarch_mechanic["leaderDetails"]))
        self.assertTrue(any(
            row.get("value") == "仅开场约 14.5 秒"
            for row in heroic["stats"]
        ))

    def test_coiled_altar_preserves_user_confirmed_chinese_names(self):
        boss = next(
            row for row in self.document["bosses"] if row["key"] == "bargained"
        )
        guillotine = next(
            spell for spell in boss["spells"] if spell["spellID"] == 1283489
        )
        dreadmarch = next(
            spell for spell in boss["spells"] if spell["spellID"] == 1285643
        )
        nightfall = next(
            spell for spell in boss["spells"] if spell["spellID"] == 1286918
        )
        self.assertEqual(guillotine["nameZh"], "处斩")
        self.assertEqual(dreadmarch["nameZh"], "恐惧行军")
        self.assertEqual(nightfall["nameZh"], "永恒夜幕")
        spiritcackle = next(
            spell for spell in boss["spells"] if spell["spellID"] == 1286441
        )
        self.assertEqual(spiritcackle["nameZh"], "精魂狂笑")


if __name__ == "__main__":
    unittest.main()
