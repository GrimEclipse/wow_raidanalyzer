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

    def test_replay_uses_aura_lifetimes_and_no_damage_wave_contact(self):
        raw = {'debuffs': [self.event(100, 'applydebuff', u.EGG_CARRY_ID, 1),
                           self.event(200, 'refreshdebuff', u.EGG_CARRY_ID, 1),
                           self.event(500, 'removedebuff', u.EGG_CARRY_ID, 1),
                           self.event(600, 'applydebuff', u.WAVE_ID, 1),
                           self.event(700, 'applydebuff', u.FANG_AURA_ID, 2, source=98)],
               'damage': [], 'enemyBuffs': [],
               'casts': [self.event(1000, 'begincast', 1315341), self.event(4000, 'cast', 1315341)]}
        out = u._replay_feedback(self.fight, self.players, raw)
        egg = next(a for a in out['auras'] if a['kind'] == 'egg')
        self.assertEqual((egg['startTimeMs'], egg['endTimeMs']), (100, 500))
        fang = next(a for a in out['auras'] if a['kind'] == 'fang')
        self.assertEqual(fang['sourceID'], 98)
        self.assertEqual(out['hits'], [{'timeMs': 600, 'playerID': 1}])
        self.assertEqual([e['timeMs'] for e in out['events'] if e['kind'] == 'shatter'], [4000])

    def test_fangs_use_configured_safe_stack_cap_and_keep_side_evidence(self):
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
        }, safe_stacks=3)
        wrong = {row["playerID"]: row["violationReasons"] for row in result["rounds"][0]["breaks"] if row["wrong"]}
        self.assertEqual(set(wrong), {3})
        self.assertIn("超过安全层数 3", wrong[3][0])
        self.assertEqual(result["safeStacks"], 3)
        self.assertEqual(result["rounds"][0]["bossInitialPosition"]["x"], 0)
        self.assertTrue(all(row["sideSource"] == "boss-initial-boundary" for row in result["rounds"][0]["sides"]))
        lower_cap = u._analyze_fangs(self.fight, self.actors, self.players, {
            "debuffs": debuffs, "casts": casts, "bossID": 99,
            "bossPositionEvents": [self.event(0, "damage", 1, -1, source=99, x=0, y=0)],
        }, safe_stacks=2)
        self.assertEqual({row["playerID"] for row in lower_cap["rounds"][0]["breaks"] if row["wrong"]}, {3, 4})

    def test_simultaneous_fangs_split_by_each_players_application_position(self):
        players = {i: {'name': f'P{i}'} for i in range(1, 7)}
        debuffs = [self.event(1010, 'applydebuff', u.FANG_AURA_ID, pid,
                              resourceActor=2, x=-7000 if pid <= 3 else 7000, y=155000)
                   for pid in players]
        debuffs += [self.event(5000 + pid, 'removedebuff', u.FANG_AURA_ID, pid)
                    for pid in players]
        raw = {'debuffs': debuffs,
               'casts': [self.event(1000, 'cast', 1301117, -1, source=141,
                                    sourceInstance=1, x=-6702),
                         self.event(1000, 'cast', 1301117, -1, source=142,
                                    sourceInstance=2, x=6702)],
               'bossID': 99,
               'bossPositionEvents': [self.event(0, 'damage', 1, -1, source=99, x=0, y=0)]}
        result = u._analyze_fangs(self.fight, {}, players, raw)
        round_row = result['rounds'][0]
        sides = {row['side']: row for row in round_row['sides']}
        self.assertEqual({row['playerID'] for row in sides['左场']['targets']}, {1, 2, 3})
        self.assertEqual({row['playerID'] for row in sides['右场']['targets']}, {4, 5, 6})
        self.assertEqual(sides['右场']['wardenInstance'], 2)
        self.assertTrue(all(row['sideSource'] == 'player-application-position'
                            for row in sides.values()))
        self.assertEqual({row['playerID']: row['side'] for row in round_row['breaks']},
                         {1: '左场', 2: '左场', 3: '左场',
                          4: '右场', 5: '右场', 6: '右场'})

    def test_egg_duty_counts_only_p1_and_includes_zero_duty_players(self):
        raw = {k: [] for k in ['casts','debuffs','damage','deaths','friendlyCasts','enemyBuffs']}
        for start,end in [(10000,20000),(50000,60000)]:
            raw['enemyBuffs'] += [self.event(start,'applybuff',u.RAGE_ID,99),self.event(end,'removebuff',u.RAGE_ID,99)]
        raw['casts'] = [self.event(t,'cast',u.P25_COIL_CAST_ID,-1) for t in [65000,68000,71000,74000,77000,80000]]
        for start,end,pid in [(1000,5000,1),(6000,9000,1),(30000,35000,2),(62000,72000,3),(90000,95000,4)]:
            raw['debuffs'] += [self.event(start,'applydebuff',u.EGG_CARRY_ID,pid),self.event(start+10,'refreshdebuff',u.EGG_CARRY_ID,pid),self.event(end,'removedebuff',u.EGG_CARRY_ID,pid)]
        raw['debuffs'] += [self.event(t,'applydebuff',u.WAVE_ID,pid) for t,pid in [(2000,1),(32000,2),(66000,3),(92000,4)]]
        waves=u._analyze_waves_and_eggs(self.fight,self.actors,self.players,raw,u._rage_windows(self.fight,raw))
        self.assertEqual([(r['playerID'],r['phase']) for r in waves['dutyCarries']],[(1,'P1'),(1,'P1')])
        self.assertEqual([r['playerID'] for r in waves['dutyWaveHits']],[1])
        self.assertIn((3, 'P2.5'), [(r['playerID'], r['phase']) for r in waves['carries']])
        metric=next(m for m in u._mechanic_overview([{'fightID':1,'ulatek':{'wavesAndEggs':waves}}])['metrics'] if m['key']=='eggCarrierWaveHits')
        self.assertEqual((metric['carryCount'],metric['value']),(2,1))
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

    def test_egg_steal_requires_full_group_and_links_early_hatch(self):
        players = {i: {"name": f"P{i}", "role": "range-dps"} for i in range(1, 10)}
        raw = {"casts": [], "damage": [], "deaths": [], "enemyBuffs": [],
               "debuffs": [], "analysisOptions": {"eggDutyPlayers": [f"P{i}" for i in range(1, 9)]}}
        for pid in (1, 2, 3, 4, 5, 6, 7, 9):
            raw["debuffs"].append(self.event(1000 + pid, "applydebuff", u.EGG_CARRY_ID, pid))
        raw["debuffs"] += [self.event(1500, "removedebuff", u.EGG_CARRY_ID, 9),
                           self.event(1500, "applydebuff", u.WAVE_ID, 9),
                           self.event(1500, "applydebuff", 1301268, 1)]
        result = u._analyze_waves_and_eggs(self.fight, {}, players, raw, [])
        self.assertEqual(result["applicationCount"], 1)
        self.assertEqual(result["eggAssignment"]["matchedCount"], 8)
        self.assertEqual([(r["player"], r["failureKinds"]) for r in result["stolenCarries"]],
                         [("P9", ["中波提前孵化"])])
        raw["analysisOptions"]["eggDutyPlayers"].pop()
        partial = u._analyze_waves_and_eggs(self.fight, {}, players, raw, [])
        self.assertFalse(partial["eggAssignment"]["ready"])
        self.assertEqual(partial["stolenCarries"], [])

    def test_p25_carry_never_counts_as_stolen_p1_duty(self):
        fight = {**self.fight, 'endTime': 100000, 'difficulty': 5}
        players = {i: {'name': f'P{i}', 'role': 'range-dps'} for i in range(1, 10)}
        raw = {'casts': [], 'damage': [], 'deaths': [], 'enemyBuffs': [],
               'debuffs': [], 'analysisOptions': {'eggDutyPlayers': [f'P{i}' for i in range(1, 9)]}}
        for start, end in ((10000, 20000), (50000, 60000)):
            raw['enemyBuffs'] += [self.event(start, 'applybuff', u.RAGE_ID, 99),
                                  self.event(end, 'removebuff', u.RAGE_ID, 99)]
        raw['casts'] = [self.event(t, 'cast', u.P25_COIL_CAST_ID, -1)
                        for t in (65000, 68000, 71000, 74000, 77000, 80000)]
        raw['debuffs'] = [self.event(62000, 'applydebuff', u.EGG_CARRY_ID, 9),
                          self.event(72000, 'removedebuff', u.EGG_CARRY_ID, 9)]
        waves = u._analyze_waves_and_eggs(fight, {}, players, raw, u._rage_windows(fight, raw))
        self.assertEqual(waves['dutyCarries'], [])
        self.assertEqual(waves['stolenCarries'], [])
        self.assertIn((9, 'P2.5'), [(r['playerID'], r['phase']) for r in waves['carries']])

    def test_mythic_wretch_casts_and_collision_clues_are_evidence_only(self):
        fight = {**self.fight, "difficulty": 5}
        raw = {
            "casts": [self.event(1000, "begincast", 1310763, source=88),
                      self.event(5000, "cast", 1310763, source=88)],
            "debuffs": [self.event(1000, "applydebuff", u.EGG_CARRY_ID, 1),
                        self.event(8000, "removedebuff", u.EGG_CARRY_ID, 1),
                        self.event(8050, "applydebuff", 1301268, 2)],
            "damage": [self.event(5020, "damage", 1310763, 2, source=88, amount=700000)],
            "deaths": [], "enemyBuffs": [],
        }

        wretch = u._analyze_mythic_wretch(fight, self.actors, self.players, raw)
        self.assertEqual(wretch["completedCount"], 1)
        self.assertEqual(wretch["rounds"][0]["hits"][0]["playerID"], 2)
        self.assertFalse(wretch["positionVerdictAvailable"])
        raw["casts"][1].update(x=0, y=0)
        raw["resources"] = [self.event(5000, "resourcechange", 0, source=1, x=0, y=0),
                            self.event(5000, "resourcechange", 0, source=2, x=1200, y=0)]
        raw["deaths"] = [self.event(9000, "death", 0, 2, killingAbilityGameID=1310763)]
        positioned = u._analyze_mythic_wretch(fight, self.actors, self.players, raw)
        self.assertTrue(positioned["positionVerdictAvailable"])
        self.assertEqual([row["playerID"] for row in positioned["rounds"][0]["outside"]], [2])
        self.assertEqual(positioned["rounds"][0]["outside"][0]["deathAbilityID"], 1310763)
        waves = u._analyze_waves_and_eggs(fight, self.actors, self.players, raw, [])
        self.assertEqual(len(waves["possibleCollisionHatches"]), 1)
        self.assertIn("不能单凭日志认定碰蛋", waves["possibleCollisionHatches"][0]["evidence"])

    def test_confirmed_egg_collision_requires_two_nearby_carriers_and_hatch(self):
        fight = {**self.fight, "difficulty": 5}
        raw = {"casts": [], "damage": [], "deaths": [], "enemyBuffs": [], "debuffs": [], "resources": []}
        for pid in (1, 2):
            raw["debuffs"] += [self.event(1000, "applydebuff", u.EGG_CARRY_ID, pid),
                               self.event(8000, "removedebuff", u.EGG_CARRY_ID, pid)]
            raw["resources"].append(self.event(8000, "resourcechange", 0, source=pid,
                                               resourceActor=1, x=pid * 100, y=2000))
        raw["debuffs"].append(self.event(8050, "applydebuff", 1301268, 3))
        waves = u._analyze_waves_and_eggs(fight, self.actors, self.players, raw, [])
        self.assertEqual(len(waves["eggCollisions"]), 1)
        self.assertEqual([p["player"] for p in waves["eggCollisions"][0]["players"]], ["P1", "P2"])
        metric = next(m for m in u._mechanic_overview([{"fightID": 7, "ulatek": {"wavesAndEggs": waves}}])["metrics"]
                      if m["key"] == "eggCollisions")
        self.assertEqual(metric["value"], 1)
        self.assertEqual(metric["events"][0]["fightID"], 7)
        self.assertEqual(metric["events"][0]["text"], "P1 阶段，P1 和 P2 撞蛋")
        self.assertNotIn("p25EggRemaining", [m["key"] for m in u._mechanic_overview([])["metrics"]])
        raw["resources"][1]["x"] = 2000
        raw.pop("_positionIndexes", None)
        self.assertEqual(u._analyze_waves_and_eggs(fight, self.actors, self.players, raw, [])["eggCollisions"], [])
        raw["resources"][1]["x"] = 200
        raw.pop("_positionIndexes", None)
        raw["debuffs"].append(self.event(8000, "applydebuff", u.WAVE_ID, 1))
        self.assertEqual(u._analyze_waves_and_eggs(fight, self.actors, self.players, raw, [])["eggCollisions"], [])

    def test_egg_collision_uses_p25_phase_after_second_rage(self):
        fight = {**self.fight, "difficulty": 5}
        raw = {"casts": [self.event(t, "cast", u.P25_COIL_CAST_ID) for t in range(65000, 89000, 3000)],
               "damage": [], "deaths": [], "resources": [], "debuffs": [],
               "enemyBuffs": [self.event(t, kind, u.RAGE_ID, 99)
                              for t, kind in ((10000, "applybuff"), (20000, "removebuff"),
                                              (50000, "applybuff"), (60000, "removebuff"))]}
        for pid in (1, 2):
            raw["debuffs"] += [self.event(61000, "applydebuff", u.EGG_CARRY_ID, pid),
                               self.event(64000, "removedebuff", u.EGG_CARRY_ID, pid)]
            raw["resources"].append(self.event(64000, "resourcechange", 0, source=pid,
                                               resourceActor=1, x=pid * 100, y=2000))
        raw["debuffs"].append(self.event(64010, "applydebuff", 1301268, 3))
        waves = u._analyze_waves_and_eggs(fight, self.actors, self.players, raw,
                                          u._rage_windows(fight, raw))
        self.assertEqual(waves["eggCollisions"][0]["phase"], "P2.5")

    def test_splash_confirms_collision_pair_without_position_samples(self):
        fight = {**self.fight, "difficulty": 5}
        raw = {"casts": [], "damage": [], "deaths": [], "enemyBuffs": [], "debuffs": [], "resources": []}
        for pid in (1, 2):
            raw["debuffs"] += [self.event(1000, "applydebuff", u.MYTHIC_EGG_CARRY_ID, pid),
                               self.event(8000 + pid * 10, "removedebuff", u.MYTHIC_EGG_CARRY_ID, pid)]
            raw["damage"] += [self.event(8050, "damage", u.EGG_COLLISION_SPLASH_ID, pid,
                                         amount=100 if pid == 1 else 0, absorbed=100 if pid == 2 else 0),
                              self.event(9050, "damage", u.EGG_COLLISION_SPLASH_ID, pid, amount=100)]
        raw["debuffs"].append(self.event(8030, "applydebuffstack", 1301268, 3, stack=2))
        waves = u._analyze_waves_and_eggs(fight, self.actors, self.players, raw, [])
        assert len(waves["eggCollisions"]) == 1
        assert [row["playerID"] for row in waves["eggCollisions"][0]["players"]] == [1, 2]
        assert waves["eggCollisions"][0]["splashSpellID"] == u.EGG_COLLISION_SPLASH_ID
        assert waves["eggCollisions"][0]["distanceYards"] is None
        raw["damage"] = [row for row in raw["damage"] if row["targetID"] == 1]
        assert u._analyze_waves_and_eggs(fight, self.actors, self.players, raw, [])["eggCollisions"] == []

    def test_splash_pairs_staggered_log_events_once(self):
        fight = {**self.fight, "difficulty": 5}
        raw = {"casts": [], "damage": [], "deaths": [], "enemyBuffs": [], "debuffs": [], "resources": []}
        for pid, offset in ((1, 0), (2, 86)):
            raw["debuffs"] += [self.event(1000, "applydebuff", u.MYTHIC_EGG_CARRY_ID, pid),
                               self.event(8000 + offset, "removedebuff", u.MYTHIC_EGG_CARRY_ID, pid),
                               self.event(8001 + offset, "applydebuffstack", 1301268, 3, stack=2)]
            raw["damage"].append(self.event(8002 + offset, "damage", u.EGG_COLLISION_SPLASH_ID,
                                            pid, amount=100))
        result = u._analyze_waves_and_eggs(fight, self.actors, self.players, raw, [])
        assert len(result["eggCollisions"]) == 1
        assert {p["playerID"] for p in result["eggCollisions"][0]["players"]} == {1, 2}

    def test_splash_collision_ignores_existing_hatched_viper(self):
        fight = {**self.fight, "difficulty": 5}
        raw = {"casts": [], "damage": [], "deaths": [], "enemyBuffs": [], "debuffs": [],
               "resources": [], "actorRows": [{"id": 77, "gameID": u.BLIGHTSCALE_VIPER_GAME_ID}]}
        for pid in (1, 2):
            raw["debuffs"] += [self.event(1000, "applydebuff", u.MYTHIC_EGG_CARRY_ID, pid),
                               self.event(8000, "removedebuff", u.MYTHIC_EGG_CARRY_ID, pid)]
            raw["damage"].append(self.event(8050, "damage", u.EGG_COLLISION_SPLASH_ID,
                                            pid, amount=100))
        raw["debuffs"].append(self.event(8030, "applydebuffstack", 1301268, 3, stack=2))
        raw["trackedActorEvents"] = [self.event(5000, "cast", 1, source=77, sourceInstance=1)]
        assert u._analyze_waves_and_eggs(fight, self.actors, self.players, raw, [])["eggCollisions"] == []
        raw["trackedActorEvents"].append(self.event(7000, "death", 0, 77, sourceInstance=1,
                                                       targetInstance=1))
        assert len(u._analyze_waves_and_eggs(fight, self.actors, self.players, raw, [])["eggCollisions"]) == 1

    def test_splash_collision_is_counted_in_p2(self):
        fight = {**self.fight, "difficulty": 5}
        raw = {"casts": [], "damage": [], "deaths": [], "resources": [], "debuffs": [],
               "enemyBuffs": [self.event(10000, "applybuff", u.RAGE_ID, 99),
                              self.event(20000, "removebuff", u.RAGE_ID, 99)]}
        for pid in (1, 2):
            raw["debuffs"] += [self.event(25000, "applydebuff", u.MYTHIC_EGG_CARRY_ID, pid),
                               self.event(30000, "removedebuff", u.MYTHIC_EGG_CARRY_ID, pid)]
            raw["damage"].append(self.event(30010, "damage", u.EGG_COLLISION_SPLASH_ID,
                                            pid, amount=100))
        raw["debuffs"].append(self.event(30005, "applydebuffstack", 1301268, 3, stack=2))
        result = u._analyze_waves_and_eggs(fight, self.actors, self.players, raw,
                                          u._rage_windows(fight, raw))
        assert result["eggCollisions"][0]["phase"] == "P2"

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
        mythic = u._analyze_p3_eggs({**self.fight, "difficulty": 5}, self.actors, self.players, raw, rage_windows)
        self.assertFalse(mythic["adjudicationAvailable"])
        self.assertTrue(all(row["baselineShriekerCount"] is None for row in mythic["rounds"]))

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




def event(ts, kind, spell, source=99, target=None, **extra):
    return dict(timestamp=ts, type=kind, abilityGameID=spell,
                sourceID=source, targetID=target, **extra)


def raw_fixture():
    return {key: [] for key in ('casts', 'friendlyCasts', 'debuffs', 'damage',
                                'deaths', 'enemyBuffs', 'friendlyBuffs',
                                'trackedActorEvents', 'resources')}


def test_rage_excludes_duplicated_augmentation_attribution_from_actual_damage():
    fight = {'startTime': 0, 'endTime': 3000}
    players = {1: {'name': 'Aug', 'specID': 1473, 'role': 'range-dps'},
               2: {'name': 'Mage', 'role': 'range-dps'}}
    raw = raw_fixture()
    raw['trackedDamageTargetGameIDByActorID'] = {50: u.ULATEK_GAME_ID,
                                                  60: u.HEART_GAME_ID}
    raw['trackedDamageTaken'] = [
        event(1500, 'damage', 101, source=1, target=60, amount=10),
        event(1500, 'damage', 102, source=2, target=60, amount=100),
        event(1500, 'damage', 103, source=2, target=50, amount=50),
        event(1500, 'damage', 104, source=1, target=60, amount=40,
              supportID=2, subtractsFromSupportedActor=True),
        event(1500, 'damage', 105, source=1, target=50, amount=20,
              supportID=2, subtractsFromSupportedActor=True),
        event(1500, 'damage', 106, source=1, target=60, amount=5,
              supportID=2, subtractsFromSupportedActor=False),
    ]
    result = u._analyze_rage(fight, {}, players, raw,
                             [{'start': 1000, 'end': 2000, 'playerID': 50}])
    round_row = result['rounds'][0]
    assert (round_row['totalDamage'], round_row['heartDamage'], round_row['bossDamage']) == (165, 115, 50)
    assert (round_row['simulatedSupportDamage'], round_row['simulatedHeartDamage'],
            round_row['simulatedBossDamage']) == (60, 40, 20)
    by_player = {row['playerID']: row for row in round_row['damageByPlayer']}
    assert (by_player[1]['totalDamage'], by_player[1]['simulatedSupportDamage']) == (15, 60)
    assert (by_player[2]['totalDamage'], by_player[2]['simulatedSupportDamage']) == (150, 0)
    assert result['totalDamage'] == 165


def test_carrier_contacts_collapse_but_raw_wave_mutations_remain():
    fight = {'startTime': 0, 'endTime': 10000}
    players = {1: {'name': 'P1', 'role': 'range-dps'}}
    raw = raw_fixture()
    raw['debuffs'] = [event(100, 'applydebuff', u.EGG_CARRY_ID, target=1),
                      event(1000, 'applydebuff', u.WAVE_ID, target=1),
                      event(1200, 'applydebuffstack', u.WAVE_ID, target=1),
                      event(2000, 'refreshdebuff', u.WAVE_ID, target=1)]
    result = u._analyze_waves_and_eggs(fight, {}, players, raw, [])
    assert result['applicationCount'] == 3
    assert [row['timeMs'] for row in result['dutyWaveHits']] == [1000, 2000]
    assert result['carries'][0]['waveHitCount'] == 2


def test_wave_exclusion_starts_at_omen_and_applies_globally_after_leak():
    fight = {'startTime': 0, 'endTime': 12000}
    players = {i: {'name': f'P{i}', 'role': 'tank' if i <= 2 else 'range-dps'} for i in range(1, 5)}
    raw = raw_fixture()
    raw['debuffs'] = [event(1000, 'applydebuff', u.PETRIFYING_SPINE_MARK_ID, target=3)]
    raw['debuffs'] += [event(ts, 'applydebuff', u.WAVE_ID, target=pid)
                       for ts, pid in ((900, 3), (1100, 3), (2100, 4), (3100, 4), (4100, 3))]
    raw['casts'] = [event(1500, 'cast', u.TOXIC_INCUBATION_CAST_ID,
                          source=50, sourceInstance=1, resourceActor=1, x=0, y=0)]
    raw['actorRows'] = [{'id': 60, 'gameID': u.BLIGHTSCALE_WRETCH_GAME_ID}]
    raw['resources'] = [event(1500, 'resourcechange', 0, source=1, resourceActor=1, x=100, y=0),
                        event(1500, 'resourcechange', 0, source=2, resourceActor=1, x=5000, y=0)]
    raw['replayEvents'] = [event(1500, 'damage', 0, source=60, sourceInstance=1,
                                 resourceActor=1, x=1000, y=0)]
    result = u.analyze_ulatek(fight, {}, players, raw)
    assert result['tankInterception']['failures'][0]['playerID'] == 1
    assert [(row['timeMs'], row['playerID']) for row in result['wavesAndEggs']['waveExclusions']] == [
        (1100, 3), (2100, 4), (3100, 4), (4100, 3)]


def test_wave_exclusions_reset_when_raid_reaches_p3():
    fight = {'startTime': 0, 'endTime': 70000}
    players = {1: {'name': 'Tank', 'role': 'tank'}, 3: {'name': 'Carrier', 'role': 'range-dps'}}
    raw = raw_fixture()
    raw['analysisOptions'] = {'fullReplayEnabled': False, 'rageReviewEnabled': False,
                              'fangsReviewEnabled': False, 'criticalReviewEnabled': False}
    raw['enemyBuffs'] = [event(t, kind, u.RAGE_ID, target=99)
                         for t, kind in ((10000, 'applybuff'), (20000, 'removebuff'),
                                         (30000, 'applybuff'), (40000, 'removebuff'))]
    raw['casts'] = [event(t, 'cast', u.TOXIC_INCUBATION_CAST_ID,
                          source=50, sourceInstance=i, resourceActor=1, x=0, y=0)
                    for i, t in ((1, 2000), (2, 50000))]
    raw['casts'].append(event(41000, 'cast', 1295905, source=50))
    raw['resources'] = [event(t, 'resourcechange', 0, source=1, resourceActor=1, x=100, y=0)
                        for t in (2000, 50000)]
    raw['debuffs'] = [event(1000, 'applydebuff', u.PETRIFYING_SPINE_MARK_ID, target=3)]
    raw['debuffs'] += [event(t, 'applydebuff', u.WAVE_ID, target=3)
                       for t in (5000, 25000, 45000, 55000)]
    result = u.analyze_ulatek(fight, {}, players, raw)
    assert [row['timeMs'] for row in result['wavesAndEggs']['waveExclusions']] == [5000, 55000]


def test_p1_wretch_casts_use_explicit_target_actor():
    fight = {'startTime': 0, 'endTime': 10000}
    players = {1: {'name': 'P1'}}
    raw = raw_fixture()
    raw['actorRows'] = [{'id': 41, 'gameID': u.BLIGHTSCALE_WRETCH_GAME_ID, 'type': 'NPC'},
                        {'id': 42, 'gameID': u.ULATEK_GAME_ID, 'type': 'NPC'}]
    raw['enemyBuffs'] = [event(5000, 'applybuff', u.RAGE_ID)]
    raw['friendlyCasts'] = [event(1000, 'cast', 123, source=1, target=41),
                            event(2000, 'cast', 123, source=1, target=42),
                            event(6000, 'cast', 123, source=1, target=41)]
    row = u._p1_wretch_focus(fight, {}, players, raw, u._rage_windows(fight, raw))['players'][0]
    assert (row['wretchCastCount'], row['otherTargetCastCount']) == (1, 1)


def test_two_bites_do_not_share_helpers():
    fight = {'startTime': 0, 'endTime': 20000}
    players = {i: {'name': f'P{i}'} for i in range(1, 10)}
    raw = raw_fixture()
    raw['casts'] = [event(1000, 'cast', 1295905)]
    raw['debuffs'] = [event(1100, 'applydebuff', u.SERPENT_BITE_TARGET_ID, target=i)
                      for i in (1, 2)]
    raw['debuffs'] += [event(5000, 'removedebuff', u.SERPENT_BITE_TARGET_ID, target=i)
                       for i in (1, 2)]
    raw['debuffs'] += [event(3000, 'applydebuff', u.INGESTED_VENOM_ID, target=i)
                       for i in range(3, 10)]
    raw['resources'] = [event(3000, 'resourcechange', 0, source=i, resourceActor=1,
                              x=100 if i in (1, 3, 4, 5, 6) else 2100, y=0)
                        for i in players]
    soaks = u._analyze_serpent_bites(fight, {}, players, raw)['rounds'][0]['soaks']
    assert [row['helperCount'] for row in soaks] == [4, 3]
    assert not any(row['enoughHelpers'] for row in soaks)
    assert all(row['target']['playerID'] not in {p['playerID'] for p in row['participants']}
               for row in soaks)


def test_bite_counts_nearby_helper_at_resolution_without_aura_event():
    fight = {'startTime': 0, 'endTime': 20000}
    players = {i: {'name': f'P{i}'} for i in (1, 2, 3)}
    raw = raw_fixture()
    raw['casts'] = [event(1000, 'cast', 1295905)]
    raw['debuffs'] = [event(1100, 'applydebuff', u.SERPENT_BITE_TARGET_ID, target=1),
                      event(5000, 'removedebuff', u.SERPENT_BITE_TARGET_ID, target=1)]
    raw['resources'] = [event(5000, 'resourcechange', 0, source=i,
                              resourceActor=1, x=x, y=0)
                        for i, x in ((1, 0), (2, 600), (3, 900))]
    soak = u._analyze_serpent_bites(fight, {}, players, raw)['rounds'][0]['soaks'][0]
    assert soak['helperCount'] == 1
    assert [row['playerID'] for row in soak['participants']] == [2]


def test_bite_counts_resurrected_helper_and_other_marked_target_per_circle():
    fight = {'startTime': 0, 'endTime': 10000}
    players = {i: {'name': f'P{i}'} for i in range(1, 7)}
    raw = raw_fixture()
    raw['deaths'] = [event(1000, 'death', 0, target=6)]
    raw['friendlyCasts'] = [event(2000, 'cast', 21169, source=6)]
    raw['casts'] = [event(3000, 'cast', 1295905)]
    raw['debuffs'] = [event(3100, 'applydebuff', u.SERPENT_BITE_TARGET_ID, target=i)
                      for i in (1, 2)]
    raw['debuffs'] += [event(7000, 'removedebuff', u.SERPENT_BITE_TARGET_ID, target=i)
                       for i in (1, 2)]
    raw['debuffs'] += [event(7010, 'applydebuff', 1312967, target=i)
                       for i in (3, 4, 5, 6)]
    raw['replayEvents'] = [event(7000, 'resourcechange', 0, source=i,
                                 resourceActor=1, x=100 * i, y=0)
                           for i in players]
    soaks = u._analyze_serpent_bites(fight, {}, players, raw)['rounds'][0]['soaks']
    assert [row['helperCount'] for row in soaks] == [5, 5]
    assert all(row['resolution'] == 'volatile_purge' for row in soaks)
    assert all({p['playerID'] for p in row['purgeRecipients']} == {3, 4, 5, 6}
               for row in soaks)


def test_failed_bite_keeps_each_calcified_circles_helpers_separate():
    fight = {'startTime': 0, 'endTime': 10000}
    players = {i: {'name': f'P{i}'} for i in range(1, 7)}
    raw = raw_fixture()
    raw['casts'] = [event(1000, 'cast', 1295905)]
    raw['debuffs'] = [event(1100, 'applydebuff', u.SERPENT_BITE_TARGET_ID, target=i)
                      for i in (1, 2)]
    raw['debuffs'] += [event(5000, 'removedebuff', u.SERPENT_BITE_TARGET_ID, target=i)
                       for i in (1, 2)]
    raw['debuffs'] += [event(5010, 'applydebuff', u.CALCIFIED_CORPSE_ID, target=i)
                       for i in (1, 2)]
    raw['replayEvents'] = [event(5000, 'resourcechange', 0, source=i,
                                 resourceActor=1, x=x, y=0)
                           for i, x in ((1, 0), (2, 2000), (3, 100), (4, 2100), (5, 2200), (6, 2300))]
    soaks = u._analyze_serpent_bites(fight, {}, players, raw)['rounds'][0]['soaks']
    assert [row['resolution'] for row in soaks] == ['calcified_corpse'] * 2
    assert [{p['playerID'] for p in row['participants']} for row in soaks] == [{3}, {4, 5, 6}]


def test_partial_tether_ticks_resolve_tank_when_target_position_missing():
    fight = {'startTime': 0, 'endTime': 20000}
    players = {1: {'name': 'P1', 'role': 'tank'}, 2: {'name': 'P2', 'role': 'tank'}}
    raw = raw_fixture()
    raw['actorRows'] = [{'id': 60, 'gameID': 268029}, {'id': 73, 'gameID': 268029}]
    raw['casts'] = [event(5000, 'cast', u.TOXIC_INCUBATION_CAST_ID,
                          source=73, sourceInstance=1)]
    raw['damage'] = [event(ts, 'damage', u.TOXIC_INCUBATION_HIT_ID,
                           source=60 if ts == 5000 else 73, target=1, sourceInstance=1)
                     for ts in (5000, 6000, 7000)]
    failure = u._analyze_tether_failures(fight, {}, players, raw)['failures'][0]
    assert (failure['tickCount'], failure['playerID'], failure['attribution']) == (
        3, 1, 'observed-interception-ticks')


def test_first_p1_tether_with_zero_ticks_keeps_failure_without_wretch_sample():
    fight = {'startTime': 0, 'endTime': 20000}
    players = {1: {'name': 'P1', 'role': 'tank'}, 2: {'name': 'P2', 'role': 'tank'}}
    raw = raw_fixture()
    raw['casts'] = [event(5000, 'cast', u.TOXIC_INCUBATION_CAST_ID,
                          source=73, sourceInstance=1, resourceActor=1, x=0, y=0)]
    raw['resources'] = [event(5000, 'resourcechange', 0, source=1,
                              resourceActor=1, x=200, y=0),
                        event(5000, 'resourcechange', 0, source=2,
                              resourceActor=1, x=5000, y=0)]
    failure = u._analyze_tether_failures(fight, {}, players, raw)['failures'][0]
    assert (failure['tickCount'], failure['playerID'], failure['attribution']) == (
        0, 1, 'nearest-tank-to-caster')


def test_p3_wrath_uses_boss_side_at_cast_start():
    fight = {'startTime': 0, 'endTime': 20000}
    raw = raw_fixture()
    raw['casts'] = [event(1000, 'begincast', 1298367, source=21),
                    event(6000, 'cast', 1298367, source=21,
                          resourceActor=1, x=3000, y=155367)]
    raw['resources'] = [event(1000, 'resourcechange', 0, source=21,
                              resourceActor=1, x=0, y=158367)]
    circle = u._replay_effects(fight, {}, raw, [])['circles'][0]
    assert circle['position'] == {'x': 0, 'y': 158367}


def test_p3_corner_wrath_uses_its_platform_landmark():
    fight = {'startTime': 0, 'endTime': 20000}
    for x, y, expected_x, expected_y in ((3300, 152112, 2300, 153367),
                                         (3300, 158446, 2300, 157367),
                                         (-3300, 152112, -2300, 153367),
                                         (-3300, 158446, -2300, 157367)):
        raw = raw_fixture()
        raw['casts'] = [event(6000, 'cast', 1298367, source=21,
                              resourceActor=1, x=x, y=y)]
        circle = u._replay_effects(fight, {}, raw, [])['circles'][0]
        assert circle['position'] == {'x': expected_x, 'y': expected_y}
