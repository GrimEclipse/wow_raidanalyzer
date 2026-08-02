import unittest
from unittest.mock import patch

from analyzer_core import raid_cooldowns
from analyzer_core.raid_cooldowns import (
    _discovery_report_codes,
    _reference_phase_data,
    apply_phase_segments,
    build_phase_segments,
    build_cooldown_timeline,
    composition_matches,
    export_mrt,
    export_nsrt,
    export_timestamp_tsv,
    options_document,
)


class RaidCooldownTests(unittest.TestCase):
    def test_options_include_live_12_0_and_ptr_boss_lists(self):
        options = options_document()
        self.assertEqual([row["key"] for row in options["versions"]], ["12.0", "12.1 PTR"])
        raids = {row["key"]: row for row in options["raids"]}
        self.assertEqual(raids["void_spire"]["version"], "12.0")
        self.assertEqual(
            [row["encounterID"] for row in raids["void_spire"]["bosses"]],
            [3176, 3177, 3179, 3178, 3180, 3181],
        )
        self.assertEqual(len(raids["venomous_abyss"]["bosses"]), 8)

    def test_ptr_discovery_fallback_uses_checked_in_reports(self):
        self.assertIn("xBt6r2LqHzdfkZN7", _discovery_report_codes("venomous_abyss", 4))
        self.assertIn("g2Cm9dXRjxAT61Dw", _discovery_report_codes("venomous_abyss", 4))
        self.assertIn("HPrGLV84XRJjCykN", _discovery_report_codes("venomous_abyss", 5))
        self.assertEqual(_discovery_report_codes("void_spire", 5), [])

    def test_zone_report_listing_adds_public_ptr_candidates(self):
        raid_cooldowns._CACHE.clear()
        with patch.object(raid_cooldowns, "_client_graphql", return_value={
            "reportData": {"reports": {
                "total": 27,
                "current_page": 1,
                "last_page": 1,
                "has_more_pages": False,
                "data": [{"code": "PTR-PUBLIC-1"}, {"code": "PTR-PUBLIC-2"}],
            }}
        }):
            result = raid_cooldowns._zone_report_codes("token", 54)
        self.assertEqual(result["codes"], ["PTR-PUBLIC-1", "PTR-PUBLIC-2"])
        self.assertEqual(result["total"], 27)

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
        self.assertIn("00:30\tP1\t00:30\t奶萨\t灵魂链接图腾\t98008", export_timestamp_tsv(timeline))

    def test_timeline_keeps_player_class_and_uses_short_breeze_name(self):
        timeline = build_cooldown_timeline(
            [{"type": "cast", "timestamp": 15_000, "sourceID": 9, "abilityGameID": 374227}],
            fight_start=0,
            players=[{
                "id": 9,
                "name": "龙希尔",
                "class": "Evoker",
                "role": "healer",
                "specKey": "preservation-evoker",
                "specLabel": "恩护 唤魔师",
            }],
        )
        self.assertEqual(timeline[0]["class"], "Evoker")
        self.assertEqual(timeline[0]["spell"], "微风")

    def test_phase_exports_use_wcl_transition_and_phase_relative_nsrt_time(self):
        timeline = [
            {"timeMs": 30_000, "player": "牧师", "spellID": 62618, "spell": "真言术：障", "categoryLabel": "团队减伤"},
            {"timeMs": 150_000, "player": "萨满", "spellID": 98008, "spell": "灵魂链接图腾", "categoryLabel": "团队减伤"},
        ]
        phases = build_phase_segments(
            fight_start=1_000_000,
            fight_end=1_240_000,
            phase_transitions=[
                {"id": 1, "startTime": 1_000_000},
                {"id": 2, "startTime": 1_120_000},
            ],
            phase_metadata=[
                {"id": 1, "name": "Stage One", "isIntermission": False},
                {"id": 2, "name": "Intermission", "isIntermission": True},
            ],
        )
        timeline = apply_phase_segments(timeline, phases)
        self.assertEqual(phases["source"], "wcl")
        self.assertEqual(timeline[0]["phaseLabel"], "P1")
        self.assertEqual(timeline[1]["phaseLabel"], "P1.5")
        self.assertEqual(timeline[1]["phaseTimeMs"], 30_000)
        nsrt = export_nsrt(timeline, encounter_id=3181, difficulty=5, encounter_name="Crown")
        self.assertIn("time:30;ph:2;tag:萨满;spellid:98008;", nsrt)
        mrt = export_mrt(timeline)
        self.assertIn("[P1.5] Intermission", mrt)
        self.assertIn("{time:02:30}", mrt)

    def test_ptr_reference_phases_are_available_without_wcl_transitions(self):
        reference = _reference_phase_data("nakzali", 4)
        phases = build_phase_segments(
            fight_start=2_000_000,
            fight_end=2_481_612,
            phase_transitions=[],
            phase_metadata=[
                {"id": 1, "name": "Stage One", "isIntermission": False},
                {"id": 2, "name": "Intermission", "isIntermission": True},
                {"id": 3, "name": "Stage Two", "isIntermission": False},
            ],
            reference=reference,
            report_id=reference["reportID"],
            fight_id=reference["fightID"],
        )
        self.assertEqual(phases["source"], "ptr_reference")
        self.assertEqual(
            [row["phaseLabel"] for row in phases["segments"][:3]],
            ["P1", "P1.5", "P2"],
        )


if __name__ == "__main__":
    unittest.main()
