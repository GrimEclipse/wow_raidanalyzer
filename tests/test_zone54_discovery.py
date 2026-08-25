import unittest

from tools.wcl_zone54_discovery import (
    choose_representative_fights,
    merge_spell_catalog,
    render_markdown,
)
from tools.zone54_journal_import import extract_journal


class Zone54DiscoveryTests(unittest.TestCase):
    def test_representative_fight_prefers_kill_within_difficulty(self):
        documents = {
            "report": {
                "fights": [
                    {
                        "id": 1,
                        "encounterID": 3470,
                        "difficulty": 4,
                        "startTime": 0,
                        "endTime": 600_000,
                        "kill": False,
                    },
                    {
                        "id": 2,
                        "encounterID": 3470,
                        "difficulty": 4,
                        "startTime": 0,
                        "endTime": 400_000,
                        "kill": True,
                    },
                    {
                        "id": 3,
                        "encounterID": 3470,
                        "difficulty": 5,
                        "startTime": 0,
                        "endTime": 700_000,
                        "kill": False,
                    },
                ],
            },
        }
        selected = choose_representative_fights(documents, 4)
        self.assertEqual(selected[3470]["id"], 2)

    def test_journal_import_accepts_relative_and_absolute_spell_links(self):
        raw = (
            "[tabs name=\\\"Nek'zali the Soulcoiler-2888-details\\\"]\\r\\n"
            '<a href=\\"/cn/spell=1284032/soulcoil-well\\">'
            '[Soulcoil Well]</a>\\r\\n'
            '<a href=\\"https:\\/\\/www.wowhead.com\\/cn\\/spell=1290003\\">'
            'Uncoiling</a> On Mythic difficulty, the test changes. (Mythic)\\r\\n'
            '[tabs name=\\"Entombed Sentinels-1-details\\"]'
        )
        document = extract_journal(raw, "https://example.invalid")
        spells = document["bosses"]["nakzali"]["spells"]
        self.assertEqual(
            {row["spellID"] for row in spells},
            {1284032, 1290003},
        )
        self.assertTrue(document["bosses"]["nakzali"]["mythicDifferences"])

    def test_journal_import_restores_current_mythic_difficulty_badges(self):
        raw = (
            '[tabs name=\\"The Lost Explorers-1-details\\"]\\r\\n'
            '<a href=\\"/cn/spell=1291933/throw-junk\\">Throw Junk</a>\\r\\n'
            '[tabs name=\\"Sszorak-1-details\\"]\\r\\n'
            '<a href=\\"/cn/spell=1296898/unbound-ferocity\\">'
            'Unbound Ferocity</a>\\r\\n'
            '<a href=\\"/cn/spell=1297367/serpents-fury\\">'
            "Serpent's Fury</a>\\r\\n"
            '<a href=\\"/cn/spell=1297414/to-the-slaughter\\">'
            'To the Slaughter</a>\\r\\n'
            '<a href=\\"/cn/spell=1297707/virulence\\">Virulence</a>\\r\\n'
            '[tabs name=\\"The Twin Fangs-1-details\\"]\\r\\n'
            '<a href=\\"/cn/spell=1290516/ravenous-feast\\">'
            'Ravenous Feast</a>\\r\\n'
            '<a href=\\"/cn/spell=1303230/blood-torrent\\">'
            'Blood Torrent</a>\\r\\n'
            '<a href=\\"/cn/spell=1303378/protected-gestation\\">'
            'Protected Gestation</a>\\r\\n'
            '<a href=\\"/cn/spell=1308356/rouse-the-brood\\">'
            'Rouse the Brood</a>\\r\\n'
            '<a href=\\"/cn/spell=1308385/visceral-burst\\">'
            'Visceral Burst</a>\\r\\n'
            '[tabs name=\\"The Coiled Altar-1-details\\"]\\r\\n'
            '<a href=\\"/cn/spell=1285643/dreadmarch\\">'
            'Dreadmarch</a> (Mythic)\\r\\n'
            '<a href=\\"/cn/spell=1285911/unnerving-fixation\\">'
            'Unnerving Fixation</a> (Mythic)\\r\\n'
            '<a href=\\"/cn/spell=1304032/soulbinding\\">'
            'Soulbinding</a> (Mythic)\\r\\n'
            '[tabs name=\\"Ulatek-1-details\\"]'
        )
        document = extract_journal(raw, "https://example.invalid")
        lost = document["bosses"]["lostexplorers"]
        sszorak = document["bosses"]["sszorak"]
        twinfangs = document["bosses"]["twinfangs"]
        bargained = document["bosses"]["bargained"]
        self.assertIn("15 yards", lost["mythicDifferences"][0])
        self.assertIn("at least 14 players", sszorak["mythicDifferences"][0])
        mythic_rows = {
            row["spellID"]: row for row in sszorak["spells"]
            if row["spellID"] in {1296898, 1297367, 1297414, 1297707}
        }
        self.assertEqual(len(mythic_rows), 4)
        self.assertTrue(all(row["mythicOnly"] for row in mythic_rows.values()))
        twin_rows = {
            row["spellID"]: row for row in twinfangs["spells"]
        }
        self.assertFalse(twin_rows[1290516]["mythicOnly"])
        self.assertTrue(twin_rows[1303230]["mythicOnly"])
        self.assertTrue(twin_rows[1303378]["mythicOnly"])
        self.assertTrue(twin_rows[1308356]["mythicOnly"])
        self.assertTrue(twin_rows[1308385]["mythicOnly"])
        self.assertTrue(any(
            "Visceral Burst" in note
            for note in twinfangs["mythicDifferences"]
        ))
        bargained_rows = {
            row["spellID"]: row for row in bargained["spells"]
        }
        self.assertFalse(bargained_rows[1285643]["mythicOnly"])
        self.assertFalse(bargained_rows[1285911]["mythicOnly"])
        self.assertFalse(bargained_rows[1304032]["mythicOnly"])
        self.assertTrue(any(
            "99% damage-reduction" in note
            for note in bargained["mythicDifferences"]
        ))

    def test_markdown_outputs_actual_spell_ids_and_evidence_categories(self):
        journal = {
            "spells": [
                {
                    "spellID": 1284103,
                    "name": "Possession Barrage",
                    "mythicOnly": False,
                    "mythicMentioned": False,
                },
                {
                    "spellID": 1290361,
                    "name": "Soulcoiled",
                    "mythicOnly": True,
                    "mythicMentioned": True,
                },
            ],
        }
        evidence = {
            "heroic": {
                "fight": {
                    "reportID": "report",
                    "fightID": 1,
                    "durationMs": 100_000,
                    "kill": True,
                },
                "enemyCasts": [],
                "damageAbilities": [],
                "bossAuras": [],
                "playerDebuffs": [{
                    "spellID": 1284103,
                    "name": "Possession Barrage",
                    "eventCount": 4,
                    "uniqueTargetCount": 2,
                    "firstMs": 12_000,
                }],
            },
        }
        document = {
            "bosses": {
                "nakzali": {
                    "encounterID": 3470,
                    "name": "Nek'zali the Soulcoiler",
                    "evidence": evidence,
                    "journal": journal,
                    "spellCatalog": merge_spell_catalog(evidence, journal),
                },
            },
        }
        markdown = render_markdown(document)
        self.assertIn("`1284103`", markdown)
        self.assertIn("附身弹幕", markdown)
        self.assertIn("施加到玩家的 Debuff", markdown)
        self.assertIn("4 次 / 2 人 / 首次 12.0s", markdown)
        self.assertIn("`1290361`", markdown)


if __name__ == "__main__":
    unittest.main()
