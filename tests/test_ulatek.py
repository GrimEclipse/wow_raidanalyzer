import unittest

from boss_plugins.venomous_abyss import ulatek as u


class UlatekTests(unittest.TestCase):
    def setUp(self):
        self.fight = {"startTime": 0, "endTime": 120000, "difficulty": 4, "kill": False}
        self.players = {i: {"name": f"P{i}", "role": "range-dps"} for i in range(1, 7)}
        self.actors = {i: f"P{i}" for i in self.players}

    @staticmethod
    def event(timestamp, kind, spell, target=None, source=99, **extra):
        return {
            "timestamp": timestamp,
            "type": kind,
            "abilityGameID": spell,
            "sourceID": source,
            "targetID": target,
            **extra,
        }

    def test_fangs_use_side_batches_not_stack_cap(self):
        debuffs = []
        for player_id in (1, 2, 3):
            debuffs.append(self.event(1010, "applydebuff", u.FANG_AURA_ID, player_id))
        for player_id in (4, 5, 6):
            debuffs.append(self.event(2210, "applydebuff", u.FANG_AURA_ID, player_id))
        for timestamp, player_id in ((5000, 1), (6000, 2), (7000, 4), (9001, 3), (13000, 5), (15000, 6)):
            debuffs.append(self.event(timestamp, "removedebuff", u.FANG_AURA_ID, player_id))
        debuffs.extend(self.event(5001, "applydebuff", u.BLIGHT_VEIN_ID, player_id) for player_id in self.players)
        debuffs.extend(self.event(6001, "applydebuffstack", u.BLIGHT_VEIN_ID, player_id, stack=2) for player_id in self.players)
        debuffs.extend(self.event(7001, "applydebuffstack", u.BLIGHT_VEIN_ID, player_id, stack=3) for player_id in self.players)
        debuffs.extend(self.event(9002, "applydebuffstack", u.BLIGHT_VEIN_ID, player_id, stack=4) for player_id in self.players)
        debuffs.extend(self.event(11000, "removedebuff", u.BLIGHT_VEIN_ID, player_id) for player_id in self.players)
        debuffs.extend(self.event(13001, "applydebuff", u.BLIGHT_VEIN_ID, player_id) for player_id in self.players)
        debuffs.extend(self.event(15001, "applydebuffstack", u.BLIGHT_VEIN_ID, player_id, stack=2) for player_id in self.players)
        casts = [
            self.event(1000, "cast", 1301117, -1, source=141, sourceInstance=1, x=-100),
            self.event(2200, "cast", 1301117, -1, source=141, sourceInstance=2, x=100),
        ]
        result = u._analyze_fangs(self.fight, self.actors, self.players, {
            "debuffs": debuffs,
            "casts": casts,
            "bossID": 99,
            "bossPositionEvents": [self.event(0, "damage", 1, -1, source=99, x=0, y=0)],
        })
        wrong = {row["playerID"]: row["violationReasons"] for row in result["rounds"][0]["breaks"] if row["wrong"]}
        self.assertEqual(set(wrong), {4})
        self.assertIn("对场未等待凋萎静脉消除", wrong[4])
        self.assertEqual(result["rounds"][0]["firstBreakSide"], "左场")
        self.assertEqual(result["rounds"][0]["bossInitialPosition"]["x"], 0)
        self.assertTrue(all(row["sideSource"] == "boss-initial-boundary" for row in result["rounds"][0]["sides"]))
        suppressed = next(row for row in result["rounds"][0]["breaks"] if row["playerID"] == 3)
        self.assertEqual(suppressed["adjudication"], "not_attributed_after_first_violation")

    def test_egg_duty_counts_only_p1_and_p25_and_includes_zero_duty_players(self):
        raw = {k: [] for k in ['casts','debuffs','damage','deaths','friendlyCasts','enemyBuffs']}
        for start,end in [(10000,20000),(50000,60000)]:
            raw['enemyBuffs'] += [self.event(start,'applybuff',u.RAGE_ID,99),self.event(end,'removebuff',u.RAGE_ID,99)]
        raw['casts'] = [self.event(t,'cast',u.P25_COIL_CAST_ID,-1) for t in [65000,68000,71000,74000,77000,80000]]
        for start,end,pid in [(1000,5000,1),(6000,9000,1),(30000,35000,2),(62000,72000,3),(90000,95000,4)]:
            raw['debuffs'] += [self.event(start,'applydebuff',u.EGG_CARRY_ID,pid),self.event(start+10,'refreshdebuff',u.EGG_CARRY_ID,pid),self.event(end,'removedebuff',u.EGG_CARRY_ID,pid)]
        raw['debuffs'] += [self.event(t,'applydebuff',u.WAVE_ID,pid) for t,pid in [(2000,1),(32000,2),(66000,3),(92000,4)]]
        waves=u._analyze_waves_and_eggs(self.fight,self.actors,self.players,raw,u._rage_windows(self.fight,raw))
        self.assertEqual([(r['playerID'],r['phase']) for r in waves['dutyCarries']],[(1,'P1'),(1,'P1'),(3,'P2.5')])
        self.assertEqual([r['playerID'] for r in waves['dutyWaveHits']],[1,3])
        metric=next(m for m in u._mechanic_overview([{'fightID':1,'ulatek':{'wavesAndEggs':waves}}])['metrics'] if m['key']=='eggCarrierWaveHits')
        self.assertEqual((metric['carryCount'],metric['value']),(3,2))
        rows={r['player']:r for r in metric['players']}
        self.assertEqual((rows['P1']['carryCount'],rows['P1']['waveHitCount']),(2,1))
        self.assertEqual(rows['P6']['carryCount'],0)
        self.assertEqual(rows['P4']['waveHitCount'],0)

    def test_wave_counts_aura_mutations_and_one_second_death_once(self):
        apply = self.event(1000, "applydebuff", u.WAVE_ID, 1)
        raw = {
            "debuffs": [apply, dict(apply), self.event(1200, "applydebuffstack", u.WAVE_ID, 1, stack=2), self.event(1500, "refreshdebuff", u.WAVE_ID, 1)],
            "damage": [],
            "deaths": [self.event(2199, "death", 0, 1, killingAbilityGameID=123)],
        }
        result = u._analyze_waves_and_eggs(self.fight, self.actors, self.players, raw, [])
        self.assertEqual(result["applicationCount"], 3)
        self.assertEqual(result["waveDeaths"]["totalCount"], 1)
        self.assertEqual(result["waveDeaths"]["p1Count"], 1)

    def test_serpent_bite_participation_uses_ingested_venom_aura(self):
        debuffs = []
        for player_id in (1, 2, 3):
            debuffs.extend([
                self.event(1500, "applydebuff", u.SERPENT_BITE_TARGET_ID, player_id),
                self.event(10500, "removedebuff", u.SERPENT_BITE_TARGET_ID, player_id),
                self.event(1600, "applydebuff", u.INGESTED_VENOM_ID, player_id),
                self.event(10500, "applydebuff", 1312967, player_id),
            ])
        raw = {
            "casts": [self.event(1000, "cast", 1295905, -1)],
            "debuffs": debuffs,
            "resources": [],
            "deaths": [],
            "friendlyCasts": [],
        }
        result = u._analyze_serpent_bites(self.fight, self.actors, {key: value for key, value in self.players.items() if key <= 4}, raw)
        round_row = result["rounds"][0]
        self.assertEqual({row["playerID"] for row in round_row["participants"]}, {1, 2, 3})
        self.assertEqual({row["playerID"] for row in round_row["nonParticipants"]}, {4})
        self.assertEqual(round_row["participationEvidence"], "ingested-venom-aura")
        self.assertTrue(all(row["resolution"] == "volatile_purge" for row in round_row["targets"]))

    def test_fixed_late_round_shriekers_are_not_failed_eggs(self):
        casts = []
        damage = []
        instance = 1
        for round_time, egg_count in ((1000, 4), (30000, 4), (60000, 3), (90000, 2)):
            for slot in range(egg_count):
                casts.append(self.event(round_time, "cast", u.DEVOURERS_SPAWN_SHELL_ID, -1, source=142, sourceInstance=instance, x=slot * 1000, y=round_time))
                damage.append(self.event(round_time + 5000, "damage", 1, 142, source=1, targetInstance=instance, amount=100, overkill=0))
                instance += 1
        shriekers = [
            self.event(66000, "cast", 1, 1, source=149, sourceInstance=1),
            self.event(96000, "cast", 1, 1, source=149, sourceInstance=2),
            self.event(97000, "cast", 1, 1, source=149, sourceInstance=3),
        ]
        raw = {
            "casts": casts,
            "trackedDamageTaken": damage,
            "trackedDamageTargetGameIDByActorID": {142: u.DEVOURERS_SPAWN_GAME_ID},
            "trackedActorEvents": shriekers,
            "trackedActorGameIDByActorID": {149: u.BLIGHTSCALE_SHRIEKER_GAME_ID},
            "enemyBuffs": [],
            "petOwners": {},
            "bossPositionEvents": [],
            "bossID": 99,
        }
        rage_windows = [{"end": 100}, {"end": 200}]
        result = u._analyze_p3_eggs(self.fight, self.actors, self.players, raw, rage_windows)
        self.assertEqual([row["baselineShriekerCount"] for row in result["rounds"]], [0, 0, 1, 2])
        self.assertEqual(result["failedEggCount"], 0)

    def test_extra_shrieker_confirms_failed_egg_and_returns_player_damage(self):
        casts = [
            self.event(1000, "cast", u.DEVOURERS_SPAWN_SHELL_ID, -1, source=142, sourceInstance=instance)
            for instance in range(1, 5)
        ]
        damage = [
            self.event(2000, "damage", 1, 142, source=1, targetInstance=instance, amount=100, overkill=0)
            for instance in range(1, 4)
        ]
        damage.extend([
            self.event(2000, "damage", 1, 142, source=1, targetInstance=4, amount=55),
            self.event(2100, "damage", 1, 142, source=50, targetInstance=4, amount=45),
        ])
        raw = {
            "casts": casts,
            "trackedDamageTaken": damage,
            "trackedDamageTargetGameIDByActorID": {142: u.DEVOURERS_SPAWN_GAME_ID},
            "trackedActorEvents": [self.event(7000, "cast", 1, 1, source=149, sourceInstance=1)],
            "trackedActorGameIDByActorID": {149: u.BLIGHTSCALE_SHRIEKER_GAME_ID},
            "enemyBuffs": [],
            "petOwners": {50: 2},
            "bossPositionEvents": [],
            "bossID": 99,
        }
        result = u._analyze_p3_eggs(self.fight, self.actors, self.players, raw, [{"end": 100}, {"end": 200}])
        failed = result["rounds"][0]["failedEggs"][0]
        self.assertEqual(result["failedEggCount"], 1)
        self.assertTrue(failed["confirmedByExtraShrieker"])
        self.assertEqual([(row["playerID"], row["damage"]) for row in failed["damageByPlayer"]], [(1, 55), (2, 45)])


if __name__ == "__main__":
    unittest.main()
