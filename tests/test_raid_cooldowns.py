from pathlib import Path
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
    fight_duration_matches,
    options_document,
    parse_report_codes,
)


class RaidCooldownTests(unittest.TestCase):
    def test_frontend_keeps_cooldowns_and_phase_transition_rows_separate(self):
        page = (
            Path(__file__).resolve().parents[1]
            / "frontend" / "tools" / "raid-cooldowns" / "index.html"
        ).read_text(encoding="utf-8")
        self.assertIn("const displayTimeline", page)
        self.assertIn("phase-transition-row", page)
        self.assertIn("阶段转换", page)
        self.assertIn("（+${clock(row.phaseTimeMs ?? row.timeMs)}）", page)

    def test_options_include_live_12_0_and_12_1_boss_lists(self):
        options = options_document()
        self.assertEqual([row["key"] for row in options["versions"]], ["12.1", "12.0"])
        raids = {row["key"]: row for row in options["raids"]}
        self.assertEqual(raids["void_spire"]["version"], "12.0")
        self.assertEqual(
            [row["encounterID"] for row in raids["void_spire"]["bosses"]],
            [3176, 3177, 3179, 3178, 3180, 3181],
        )
        self.assertEqual(len(raids["venomous_abyss"]["bosses"]), 8)
        self.assertEqual(raids["venomous_abyss"]["zoneID"], 53)
        self.assertEqual(
            [row["encounterID"] for row in raids["venomous_abyss"]["bosses"]],
            [3470, 3445, 3455, 3497, 3420, 3421, 3429, 3492],
        )
        self.assertEqual(
            raids["tidebound_grotto"]["bosses"][0]["key"],
            "nymrissa_wavecaller",
        )
        self.assertEqual(raids["tidebound_grotto"]["zoneID"], 53)
        self.assertEqual(raids["tidebound_grotto"]["bosses"][0]["encounterID"], 3379)

    def test_non_healer_specs_use_common_chinese_labels(self):
        self.assertEqual(
            raid_cooldowns.SPEC_LABEL_BY_KEY["elemental-shaman"],
            "元素 萨满祭司",
        )
        self.assertEqual(
            raid_cooldowns.SPEC_LABEL_BY_KEY["augmentation-evoker"],
            "增辉 唤魔师",
        )
        self.assertNotIn("elemental-shaman", raid_cooldowns.HEALER_SPEC_KEYS)

    def test_non_healer_team_utility_keeps_localized_spec_labels(self):
        timeline = build_cooldown_timeline(
            [
                {"type": "cast", "timestamp": 110_000, "sourceID": 1, "abilityGameID": 192077},
                {"type": "cast", "timestamp": 120_000, "sourceID": 2, "abilityGameID": 374968},
            ],
            fight_start=100_000,
            players=[
                {"id": 1, "name": "元素萨", "role": "dps", "class": "Shaman", "specKey": "elemental-shaman", "specLabel": "元素 萨满祭司"},
                {"id": 2, "name": "增辉", "role": "dps", "class": "Evoker", "specKey": "augmentation-evoker", "specLabel": "增辉 唤魔师"},
            ],
        )
        self.assertEqual([row["specLabel"] for row in timeline], ["元素 萨满祭司", "增辉 唤魔师"])

    def test_live_search_does_not_seed_ptr_discovery_reports(self):
        self.assertEqual(_discovery_report_codes("venomous_abyss", 4), [])
        self.assertEqual(_discovery_report_codes("venomous_abyss", 5), [])
        self.assertEqual(_discovery_report_codes("void_spire", 5), [])
        self.assertEqual(_discovery_report_codes("tidebound_grotto", 4, 3379), [])
        self.assertEqual(_discovery_report_codes("tidebound_grotto", 5, 3379), [])

    def test_zone_report_listing_adds_public_live_candidates(self):
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
            result = raid_cooldowns._zone_report_codes("token", 53)
        self.assertEqual(result["codes"], ["PTR-PUBLIC-1", "PTR-PUBLIC-2"])
        self.assertEqual(result["total"], 27)

    def test_report_codes_accept_wcl_urls_and_plain_codes(self):
        self.assertEqual(parse_report_codes(
            "https://www.warcraftlogs.com/reports/pJvx3ArdFNXmk4j1?fight=9\n"
            "g2Cm9dXRjxAT61Dw"
        ), ["pJvx3ArdFNXmk4j1", "g2Cm9dXRjxAT61Dw"])

    def test_embedded_report_roster_distinguishes_ambiguous_healer_specs(self):
        report = {
            "masterData": {"actors": [
                {"id": 1, "name": "牧师", "type": "Player", "subType": "Priest"},
                {"id": 2, "name": "萨满", "type": "Player", "subType": "Shaman"},
                {"id": 3, "name": "德鲁伊", "type": "Player", "subType": "Druid"},
            ]},
        }
        fight = {
            "friendlyPlayers": [1, 2, 3],
            "friendlySpecs": ["Holy", "Restoration", "Restoration"],
        }
        roster = raid_cooldowns._embedded_roster(report, fight)
        self.assertEqual(
            [row["specKey"] for row in roster["healers"]],
            ["holy-priest", "restoration-shaman", "restoration-druid"],
        )

    def test_candidate_search_keeps_speed_rankings_ahead_of_public_fallback(self):
        healer_characters = [
            {"class": "Priest", "spec": "Discipline"},
            {"class": "Priest", "spec": "Discipline"},
            {"class": "Monk", "spec": "Mistweaver"},
            {"class": "Druid", "spec": "Restoration"},
        ]
        rankings = []
        for index in range(5):
            rankings.append({
                "duration": 500_000 + index,
                "startTime": 2_000_000 + index * 600_000,
                "healers": 4,
                "allCharacters": healer_characters,
                "report": {
                    "code": f"RANKEDREPORT{index:04d}",
                    "fightID": 9,
                    "startTime": 1_000_000 + index * 600_000,
                },
            })
        roster = {
            "players": [],
            "healers": [
                {"specKey": "discipline-priest"},
                {"specKey": "discipline-priest"},
                {"specKey": "mistweaver-monk"},
                {"specKey": "restoration-druid"},
            ],
        }
        with (
            patch.object(raid_cooldowns, "_discovery_report_codes", return_value=[]),
            patch.object(raid_cooldowns, "_ranked_fight_page", return_value={
                "rankings": rankings,
                "page": 1,
                "count": 5,
                "hasMorePages": True,
            }),
            patch.object(raid_cooldowns, "_summary_roster", return_value=roster),
            patch.object(raid_cooldowns, "_complete_candidate_overview", side_effect=lambda token, row, encounter_id: row),
            patch.object(raid_cooldowns, "_zone_report_page") as zone_page,
        ):
            result = raid_cooldowns._candidate_fights(
                "token",
                raid_key="march_on_queldanas",
                boss_name="至暗之夜降临",
                encounter_id=3183,
                difficulty=5,
                healer_count=4,
                required_spec_keys=[
                    "discipline-priest",
                    "discipline-priest",
                    "mistweaver-monk",
                    "restoration-druid",
                ],
                min_duration_seconds=None,
                max_duration_seconds=None,
            )
        self.assertEqual(len(result["matches"]), 5)
        self.assertEqual(result["selection"]["rankingPagesScanned"], 1)
        self.assertEqual(result["selection"]["zoneReportPagesScanned"], 0)
        self.assertEqual(result["selection"]["rosterRequestCount"], 0)
        zone_page.assert_not_called()

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

    def test_fight_duration_filter_uses_complete_kill_length(self):
        self.assertTrue(fight_duration_matches(
            360_000,
            min_duration_seconds=300,
            max_duration_seconds=420,
        ))
        self.assertFalse(fight_duration_matches(
            240_000,
            min_duration_seconds=300,
            max_duration_seconds=420,
        ))
        self.assertFalse(fight_duration_matches(
            480_000,
            min_duration_seconds=300,
            max_duration_seconds=420,
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
            encounter_id=3455,
            difficulty=5,
            encounter_name="Vashnik the Malignant",
        )
        self.assertIn("EncounterID:3455;Difficulty:Mythic", nsrt)
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
