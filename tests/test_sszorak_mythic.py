import unittest
from unittest.mock import patch

from boss_plugins.venomous_abyss import sszorak as s


class SszorakMythicTests(unittest.TestCase):
    def setUp(self):
        self.fight = {"startTime": 0, "endTime": 20000, "difficulty": 5, "kill": False}
        self.players = {i: {"name": f"P{i}", "role": "range-dps"} for i in range(1, 21)}
        self.players[19]["role"] = "range-healer"
        self.players[20]["role"] = "melee-healer"
        self.actors = {i: f"P{i}" for i in self.players}
        self.raw = {"bossID": 99, "enemyBuffs": [self.event(10000, "applybuff", s.UNBOUND_FEROCITY_ID, 99)],
                    "debuffs": [self.event(1, "applydebuff", s.SERPENTS_FURY_MARK_ID, 1)],
                    "deaths": [], "trackedActorEvents": []}
        self.positions = {i: [{"timestamp": 9999, "x": 0 if i == 1 else 1000, "y": 0}] for i in self.players}

    def event(self, timestamp, kind, spell, target, **kw):
        return {"timestamp": timestamp, "type": kind, "abilityGameID": spell, "targetID": target, "sourceID": 99, **kw}

    def analyze(self):
        return s._serpents_fury(self.fight, self.actors, self.players, self.raw, self.positions)

    def test_three_dead_counts_four_dead_exempts(self):
        self.raw["deaths"] = [self.event(8000, "death", 0, i) for i in (2, 3, 4)]
        result = self.analyze()
        self.assertFalse(result["events"][0]["exempt"])
        self.assertEqual(len(result["players"]), 14)  # 20 - 3 dead - 2 healers - marked player
        self.raw["deaths"].append(self.event(8000, "death", 0, 5))
        result = self.analyze()
        self.assertTrue(result["events"][0]["exempt"])
        self.assertEqual(result["players"], [])

    def test_both_healer_roles_excluded_and_radius_is_inclusive(self):
        self.positions[2][0]["x"] = 800
        self.positions[3][0]["x"] = 801
        row = self.analyze()["events"][0]
        self.assertEqual({p["playerID"] for p in row["insidePlayers"]}, {1, 2})
        self.assertIn(3, {p["playerID"] for p in row["outsidePlayers"]})
        self.assertEqual({p["playerID"] for p in row["excludedHealers"]}, {19, 20})
        self.assertFalse({19, 20} & {p["playerID"] for p in row["outsidePlayers"]})

    def test_resurrect_and_same_timestamp_deaths(self):
        self.raw["deaths"] = [self.event(8000, "death", 0, i) for i in (2, 3, 4, 19)]
        self.raw["trackedActorEvents"] = [self.event(9000, "resurrect", 0, 19)]
        self.raw["deaths"].append(self.event(10000, "death", 0, 5))
        row = self.analyze()["events"][0]
        self.assertEqual(row["deadCount"], 3)
        self.assertFalse(row["exempt"])

    def test_missing_and_stale_coordinates_never_count(self):
        self.positions.pop(2)
        self.positions[3][0]["timestamp"] = 7000
        row = self.analyze()["events"][0]
        self.assertEqual({p["playerID"] for p in row["unknownPlayers"]}, {2, 3})
        self.positions.pop(1)
        self.assertEqual(self.analyze()["players"], [])

    def test_no_mark_no_fury_heroic_and_kill(self):
        self.raw["debuffs"] = []
        self.assertEqual(self.analyze()["players"], [])
        self.fight["difficulty"] = 4
        self.assertEqual(self.analyze()["events"], [])
        self.fight.update(difficulty=5, kill=True)
        self.assertEqual(self.analyze()["events"], [])

    def test_deduplicates_enrage_and_ignores_refresh(self):
        self.raw["enemyBuffs"] *= 2
        self.raw["enemyBuffs"].append(self.event(11000, "refreshbuff", s.UNBOUND_FEROCITY_ID, 99))
        self.assertEqual(self.analyze()["enrageCount"], 1)

    def test_tempest_aura_and_actual_dispel_not_ticks_or_removals(self):
        raw = {"debuffs": [self.event(i, kind, s.TEMPEST_DEBUFF_ID, 1) for i, kind in enumerate(
            ["applydebuff", "applydebuffstack", "refreshdebuff", "removedebuff", "damage"], 1)],
            "trackedActorEvents": [self.event(8, "dispel", 123, 1, extraAbilityGameID=s.TEMPEST_DEBUFF_ID),
                                   self.event(9, "dispel", 123, 1, extraAbilityGameID=456)]}
        result = s._tempest_aura_counts(self.fight, self.actors, self.players, raw)
        self.assertEqual(result["applicationCount"], 3)
        self.assertEqual(result["dispelCount"], 1)

    def test_perpendicular_mythic_axis(self):
        angles = [s.CROSSWIND_DIRECTIONS[i]["wclAngleDegrees"] for i in (1285425, 1285453, 1297096, 1297111)]
        self.assertEqual(s._angle_delta(angles[0], angles[1]), 180)
        self.assertEqual(s._angle_delta(angles[2], angles[3]), 180)
        self.assertEqual(s._angle_delta(angles[0], angles[2]), 90)

    def test_dispels_credit_caster_and_pet_owner_not_recipient(self):
        direct = self.event(100, 'dispel', 123, 1, extraAbilityGameID=s.TEMPEST_DEBUFF_ID)
        direct['sourceID'] = 19
        pet = {**direct, 'timestamp': 200, 'sourceID': 70, 'targetID': 2}
        raw = {'debuffs': [self.event(50, 'applydebuff', s.TEMPEST_DEBUFF_ID, 1)],
               'trackedActorEvents': [direct, pet], 'petOwners': {70: 20}}
        data = s._tempest_aura_counts(self.fight, self.actors, self.players, raw)
        rows = {r['playerID']: r for r in data['players']}
        self.assertEqual(rows[1]['applicationCount'], 1)
        self.assertEqual(rows[1]['dispelCount'], 0)
        self.assertEqual(rows[19]['dispelCount'], 1)
        self.assertEqual(rows[20]['dispelCount'], 1)
        self.assertNotIn(2, rows)
        overview = s._mechanic_overview([{'reportID': 'test', 'fightID': 1, 'sszorak': {'tempest': data}}])
        metric = next(r for r in overview['metrics'] if r['key'] == 'stormDispels')
        self.assertEqual({r['player']: r['count'] for r in metric['players']}, {'P19': 1, 'P20': 1})
        self.assertEqual([r['targetPlayerID'] for r in metric['events']], [1, 2])

    def test_mythic_pairings_do_not_mix_perpendicular_axes(self):
        debuffs = []
        for pid, spell in ((1, 1285425), (2, 1285453), (3, 1297096), (4, 1297111)):
            debuffs += [self.event(1000, 'applydebuff', spell, pid), self.event(2000, 'removedebuff', spell, pid),
                        self.event(2000, 'applydebuff', s.CROSSWIND_LAUNCH_DEBUFF_ID, pid),
                        self.event(3000, 'removedebuff', s.CROSSWIND_LAUNCH_DEBUFF_ID, pid)]
        waves = s._sszorak_crosswind_waves(self.fight, self.actors, self.players, debuffs, [], [], [], {}, None)
        self.assertEqual(len(waves), 1)
        self.assertEqual(waves[0]['resolvedCount'], 4)
        self.assertEqual({(r['left']['playerID'], r['right']['playerID']) for r in waves[0]['pairings']}, {(1, 2), (3, 4)})
        self.assertEqual(len(waves[0]['axes']), 2)

    def test_fetch_dependencies_when_replay_off(self):
        options = {field["key"]: False for field in s.CONFIG_SCHEMA}
        options["tempestReviewEnabled"] = True
        with patch.object(s, "_build", return_value={"data": {"page1_wipeAnalysis": []}}) as build:
            s.build_aggregated_json('test', options)
            config = build.call_args.args[0]
            self.assertIn('debuffs', config['fetchKeys'])
            self.assertFalse(config['fetchPositionResources'])
            self.assertIn("type = 'dispel'", config['trackedActorEventFilters'][0])
        options["serpentsFuryReviewEnabled"] = True
        with patch.object(s, "_build", return_value={"data": {"page1_wipeAnalysis": []}}) as build:
            s.build_aggregated_json('test', options)
            config = build.call_args.args[0]
            self.assertIn('enemyBuffs', config['fetchKeys'])
            self.assertTrue(config['fetchPositionResources'])
            self.assertIn("type = 'resurrect'", config['trackedActorEventFilters'][0])


if __name__ == '__main__':
    unittest.main()
