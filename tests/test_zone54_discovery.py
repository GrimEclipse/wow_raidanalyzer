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
                        "encounterID": 53470,
                        "difficulty": 4,
                        "startTime": 0,
                        "endTime": 600_000,
                        "kill": False,
                    },
                    {
                        "id": 2,
                        "encounterID": 53470,
                        "difficulty": 4,
                        "startTime": 0,
                        "endTime": 400_000,
                        "kill": True,
                    },
                    {
                        "id": 3,
                        "encounterID": 53470,
                        "difficulty": 5,
                        "startTime": 0,
                        "endTime": 700_000,
                        "kill": False,
                    },
                ],
            },
        }
        selected = choose_representative_fights(documents, 4)
        self.assertEqual(selected[53470]["id"], 2)

    def test_journal_import_accepts_relative_and_absolute_spell_links(self):
        raw = (
            "[tabs name=\\\"Nek'zali the Soulcoiler-2888-details\\\"]\\r\\n"
            '<a href=\\"/ptr/spell=1284032/soulcoil-well\\">'
            '[Soulcoil Well]</a>\\r\\n'
            '<a href=\\"https:\\/\\/www.wowhead.com\\/ptr\\/spell=1290003\\">'
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
                    "encounterID": 53470,
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
