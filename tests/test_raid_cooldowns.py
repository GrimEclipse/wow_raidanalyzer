import unittest

from analyzer_core.raid_cooldowns import (
    build_cooldown_timeline,
    composition_matches,
    export_mrt,
    export_nsrt,
    export_timestamp_tsv,
)


class RaidCooldownTests(unittest.TestCase):
    def test_composition_preserves_duplicate_specs(self):
        actual = [
            "discipline-priest",
            "discipline-priest",
            "holy-paladin",
            "restoration-shaman",
        ]
        self.assertTrue(composition_matches(
            actual,
            healer_count=4,
            required_spec_keys=[
                "discipline-priest",
                "discipline-priest",
                "holy-paladin",
            ],
        ))
        self.assertFalse(composition_matches(
            actual,
            healer_count=4,
            required_spec_keys=[
                "discipline-priest",
                "discipline-priest",
                "discipline-priest",
            ],
        ))
        self.assertFalse(composition_matches(
            actual,
            healer_count=5,
            required_spec_keys=[],
        ))

    def test_timeline_filters_unconfigured_casts_and_exports(self):
        timeline = build_cooldown_timeline(
            [
                {"type": "cast", "timestamp": 130_000, "sourceID": 7, "abilityGameID": 98008},
                {"type": "cast", "timestamp": 131_000, "sourceID": 7, "abilityGameID": 123},
                {"type": "cast", "timestamp": 132_000, "sourceID": 8, "abilityGameID": 31884},
            ],
            fight_start=100_000,
            players=[{
                "id": 7,
                "name": "奶萨",
                "role": "healer",
                "specKey": "restoration-shaman",
                "specLabel": "恢复 萨满祭司",
            }, {
                "id": 8,
                "name": "惩戒骑",
                "role": "dps",
                "specKey": "",
                "specLabel": "惩戒 圣骑士",
            }],
        )
        self.assertEqual(len(timeline), 1)
        self.assertEqual(timeline[0]["timeMs"], 30_000)
        self.assertIn("{time:00:30}", export_mrt(timeline))
        self.assertIn("{spell:98008}", export_mrt(timeline))
        nsrt = export_nsrt(
            timeline,
            encounter_id=53455,
            difficulty=5,
            encounter_name="Vashnik the Malignant",
        )
        self.assertIn("EncounterID:53455;Difficulty:Mythic", nsrt)
        self.assertIn("time:30;ph:1;tag:奶萨;spellid:98008;", nsrt)
        self.assertIn("00:30\t奶萨\t灵魂链接图腾\t98008", export_timestamp_tsv(timeline))


if __name__ == "__main__":
    unittest.main()
