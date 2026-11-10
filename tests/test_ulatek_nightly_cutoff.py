from boss_plugins.venomous_abyss import ulatek as boss


def fixture():
    players = {i: {'name': f'P{i}', 'role': 'range-dps'} for i in range(1, 11)}
    raw = {k: [] for k in ['casts', 'damage', 'debuffs', 'enemyBuffs', 'friendlyBuffs', 'friendlyCasts', 'deaths', 'combatants', 'trackedActorEvents']}
    return {'id': 1, 'startTime': 0, 'endTime': 120000}, players, raw


def event(ts, kind, pid, spell=0, **kwargs):
    return dict(timestamp=ts, type=kind, targetID=pid, sourceID=99, abilityGameID=spell, **kwargs)


def test_cutoff_counts_current_dead_players_and_never_resumes_after_eighth_death():
    fight, players, raw = fixture()
    raw['deaths'] = [event(i * 1000, 'death', i) for i in range(1, 9)]
    raw['trackedActorEvents'] = [event(7500, 'resurrect', 1)]
    assert boss._nightly_collapse(fight, players, raw) is None
    raw['deaths'] += [event(8500, 'death', 777), event(9000, 'death', 1)]
    raw['trackedActorEvents'] += [event(9500, 'resurrect', 2)]
    assert boss._nightly_collapse(fight, players, raw) == 9000


def test_single_fight_keeps_post_collapse_details_but_nightly_excludes_them():
    fight, players, raw = fixture()
    raw['deaths'] = [event(i * 1000, 'death', i) for i in range(1, 9)]
    raw['damage'] = [event(t, 'damage', 9, 1, amount=100) for t in [500, 8000, 9000]]
    raw['debuffs'] = [event(t, 'applydebuff', 9, boss.WAVE_ID) for t in [600, 8000, 9500]]
    raw['debuffs'] += [event(100, 'applydebuff', 9, boss.EGG_CARRY_ID), event(1000, 'removedebuff', 9, boss.EGG_CARRY_ID), event(8500, 'applydebuff', 9, boss.EGG_CARRY_ID)]
    result = boss.analyze_ulatek(fight, {}, players, raw)
    assert result['nightlyExemption']['timeMs'] == 8000
    assert result['critical']['nonTankMelee']['hitCount'] == 3
    assert result['nightlyReview']['critical']['nonTankMelee']['hitCount'] == 1
    assert len(result['wavesAndEggs']['dutyCarries']) == 2
    metrics = {r['key']: r for r in boss._mechanic_overview([{'fightID': 1, 'ulatek': result}])['metrics']}
    assert metrics['nonTankMelee']['value'] == 1
    assert metrics['waveHits']['value'] == 1
    assert metrics['eggCarrierWaveHits']['carryCount'] == 1


def test_seven_deaths_does_not_exempt_later_statistics():
    fight, players, raw = fixture()
    raw['deaths'] = [event(i * 1000, 'death', i) for i in range(1, 8)]
    raw['damage'] = [event(9000, 'damage', 9, 1, amount=100)]
    result = boss.analyze_ulatek(fight, {}, players, raw)
    assert not result['nightlyExemption']['active']
    assert 'nightlyReview' not in result
    assert result['critical']['nonTankMelee']['hitCount'] == 1


def test_nightly_melee_breakdown_groups_creature_names_and_egg_columns_are_structured():
    fight, players, raw = fixture()
    raw['damage'] = [event(t, 'damage', 9, 1, amount=100) for t in [1000, 2000, 3000]]
    raw['damage'][-1]['sourceID'] = 98
    result = boss.analyze_ulatek(fight, {99: '乌拉特克', 98: '尖啸者'}, players, raw)
    metrics = {r['key']: r for r in boss._mechanic_overview([{'fightID': 1, 'ulatek': result}])['metrics']}
    player = metrics['nonTankMelee']['players'][0]
    assert player['count'] == 3
    assert player['countBreakdown'] == [{'label': '乌拉特克', 'count': 2}, {'label': '尖啸者', 'count': 1}]
    assert [c['label'] for c in metrics['eggCarrierWaveHits']['summaryColumns']] == ['搬蛋次数', '总中波次数', '期间中波次数', '可排除次数']
    assert all('countLabel' not in p for p in metrics['eggCarrierWaveHits']['players'])


def test_low_egg_duty_filter_only_includes_damage_roles():
    fight, players, raw = fixture()
    players[1]['role'] = 'tank'
    players[2]['role'] = 'range-healer'
    players[3]['role'] = 'melee-healer'
    players[4]['role'] = 'unknown'
    result = boss.analyze_ulatek(fight, {}, players, raw)
    metric = next(m for m in boss._mechanic_overview([{'fightID': 1, 'ulatek': result}])['metrics'] if m['key'] == 'eggCarrierWaveHits')
    eligible = {p['playerID'] for p in metric['players'] if p['dutyFilterEligible']}
    assert eligible == set(range(5, 11))


def test_optional_clean_waves_stop_at_first_tether_failure_or_second_death():
    fight, players, raw = fixture()
    raw['deaths'] = [event(i * 1000, 'death', i) for i in range(1, 9)]
    waves = {'hits': [{'timeMs': t, 'player': 'P9', 'time': str(t)} for t in [500, 7000, 8000, 9000]]}
    clean = boss._clean_wave_hits(fight, players, raw, waves,
                                  {'failures': [{'timeMs': 7500}]})
    assert [r['timeMs'] for r in clean] == [500]
    clean = boss._clean_wave_hits(fight, players, raw, waves,
                                  {'failures': [{'timeMs': 6500}]})
    assert [r['timeMs'] for r in clean] == [500]


def test_clean_waves_reset_tether_exclusion_in_later_phase():
    fight, players, raw = fixture()
    raw['casts'] = [event(41000, 'cast', 99, 1295905)]
    raw['enemyBuffs'] = [event(t, kind, 99, boss.RAGE_ID)
                         for t, kind in ((10000, 'applybuff'), (20000, 'removebuff'),
                                         (30000, 'applybuff'), (40000, 'removebuff'))]
    waves = {'hits': [{'timeMs': t} for t in (1000, 5000, 25000, 45000, 55000)]}
    clean = boss._clean_wave_hits(fight, players, raw, waves,
                                  {'failures': [{'timeMs': 3000}, {'timeMs': 50000}]})
    assert [row['timeMs'] for row in clean] == [1000, 25000, 45000]
