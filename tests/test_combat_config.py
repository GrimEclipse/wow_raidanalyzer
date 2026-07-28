import unittest

from boss_plugins.combat_config import (
    PERSONAL_DEFENSIVES,
    RAID_DEFENSIVES,
    audit_personal_defensive_readiness,
    audit_raid_defensive_assignment,
    defensive_spell_ids,
    find_defensive_uses_before_death,
)


class CombatConfigTests(unittest.TestCase):
    def test_expected_personal_and_raid_spells_are_configured(self):
        self.assertEqual(PERSONAL_DEFENSIVES[48792]["name"], "冰封之韧")
        self.assertEqual(PERSONAL_DEFENSIVES[19236]["effectKind"], "max_health")
        self.assertEqual(RAID_DEFENSIVES[97462]["name"], "命令怒吼")
        self.assertEqual(RAID_DEFENSIVES[115310]["effectKind"], "raid_healing")
        self.assertIn(48707, defensive_spell_ids())
        self.assertIn(51052, defensive_spell_ids())

    def test_death_audit_separates_personal_action_and_active_raid_cover(self):
        casts = [
            {"timestamp": 90_000, "sourceID": 7, "abilityGameID": 19236},
            {"timestamp": 95_000, "sourceID": 9, "abilityGameID": 62618},
            {"timestamp": 99_000, "sourceID": 8, "abilityGameID": 48792},
        ]
        result = find_defensive_uses_before_death(
            casts,
            death_timestamp=100_000,
            player_id=7,
            lookback_ms=15_000,
        )
        self.assertEqual(result["lastPersonalDefensive"]["spellID"], 19236)
        self.assertEqual(result["lastPersonalDefensive"]["effectKind"], "max_health")
        self.assertEqual([row["spellID"] for row in result["activeRaidDefensives"]], [62618])

    def test_expired_raid_cooldown_is_retained_as_evidence_but_not_coverage(self):
        result = find_defensive_uses_before_death(
            [{"timestamp": 80_000, "sourceID": 9, "abilityGameID": 97462}],
            death_timestamp=100_000,
            player_id=7,
            lookback_ms=30_000,
        )
        self.assertEqual(len(result["raidDefensives"]), 1)
        self.assertFalse(result["raidDefensives"][0]["activeAtDeath"])
        self.assertEqual(result["activeRaidDefensives"], [])

    def test_ready_but_unused_is_the_only_personal_failure_state(self):
        result = audit_personal_defensive_readiness(
            [],
            death_timestamp=100_000,
            player_id=7,
            available_spell_ids=[19236, 47585],
        )
        self.assertEqual(result["status"], "available_unused")
        self.assertTrue(result["counted"])
        self.assertEqual({row["spellID"] for row in result["readyUnusedAbilities"]}, {19236, 47585})

    def test_all_personal_defensives_on_cooldown_is_not_counted(self):
        casts = [
            {"timestamp": 20_000, "sourceID": 7, "abilityGameID": 19236},
            {"timestamp": 10_000, "sourceID": 7, "abilityGameID": 47585},
        ]
        result = audit_personal_defensive_readiness(
            casts,
            death_timestamp=100_000,
            player_id=7,
            available_spell_ids=[19236, 47585],
        )
        self.assertEqual(result["status"], "all_on_cooldown")
        self.assertFalse(result["counted"])

    def test_defensive_inside_effect_window_is_active(self):
        result = audit_personal_defensive_readiness(
            [{"timestamp": 95_000, "sourceID": 7, "abilityGameID": 19236}],
            death_timestamp=100_000,
            player_id=7,
            available_spell_ids=[19236],
        )
        self.assertEqual(result["status"], "defensive_active")
        self.assertFalse(result["counted"])
        self.assertEqual(result["abilities"][0]["lastUsage"], 95_000)

    def test_unused_second_charge_remains_available(self):
        result = audit_personal_defensive_readiness(
            [{"timestamp": 20_000, "sourceID": 7, "abilityGameID": 61336}],
            death_timestamp=100_000,
            player_id=7,
            available_spell_ids=[61336],
        )
        self.assertEqual(result["status"], "available_unused")
        self.assertEqual(result["abilities"][0]["charges"], 2)
        self.assertTrue(result["abilities"][0]["readyAtDeath"])

    def test_assigned_raid_heal_can_land_just_after_the_aoe(self):
        result = audit_raid_defensive_assignment(
            [{"timestamp": 100_800, "sourceID": 9, "abilityGameID": 115310}],
            mechanic_timestamp=100_000,
            assigned_spell_ids=[115310],
        )
        self.assertEqual(result["status"], "used")
        self.assertFalse(result["counted"])


if __name__ == "__main__":
    unittest.main()
