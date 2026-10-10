from copy import deepcopy
from unittest.mock import patch

from analyzer_core.config import resolve_analysis_options
from boss_plugins.venomous_abyss import twinfangs as boss


def event(ts, sid, kind='cast', **kw):
    return dict(timestamp=ts, abilityGameID=sid, type=kind, **kw)


def fixture():
    fight = dict(id=1, startTime=0, endTime=120000, difficulty=5)
    players = {i:dict(id=i,name=f'P{i}',specID=64,role='ranged') for i in range(1,6)}
    raw = {key:[] for key in ['casts','damage','debuffs','friendlyBuffs','friendlyCasts','deaths','combatants','interrupts','trackedActorEvents']}
    return fight, {}, players, raw


def test_green_circle_and_wave_keep_distinct_damage_ids():
    fight, actor_map, players, raw = fixture()
    raw['analysisOptions'] = {key: False for key in boss.REVIEW_KEYS}
    raw['analysisOptions']['waveReviewEnabled'] = True
    raw['damage'] = [
        event(10000, 1289237, 'damage', targetID=1, amount=100),
        event(11000, 1289994, 'damage', targetID=2, amount=100),
        event(12000, 1292807, 'damage', targetID=3, amount=100),
        event(22000, 1292807, 'damage', targetID=3, amount=100),
        event(32000, 1292807, 'damage', targetID=3, amount=100),
        event(13000, 1292807, 'damage', targetID=4, amount=0),
    ]
    result = boss.analyze_twinfangs(fight, actor_map, players, raw)
    assert result['circleHits']['spellID'] == 1289994
    assert [row['playerID'] for row in result['circleHits']['players']] == [2]
    assert result['waveHits']['spellID'] == 1292807
    assert [row['playerID'] for row in result['waveHits']['players']] == [3]
    assert result['waveHits']['players'][0]['hitCount'] == 3


def options(**kwargs):
    return resolve_analysis_options(boss.CONFIG_SCHEMA,kwargs)


def feast_setup():
    f, am, players, raw = fixture()
    raw['casts'] = [event(10000,1290516,sourceID=90)]
    raw['damage'] = [event(ts,1290662,'damage',targetID=i,sourceID=90,hitType=10,amount=0)
                     for ts in [10000,12000,13500] for i in range(1,5)]
    opt = options(feastStrategy='immunity',feastGroups={'round1':['P1','P2','P3','P4']})
    return f,am,players,raw,opt


def test_generic_protection_pairs_preserve_repeated_provider_and_legacy_compatibility():
    _, _, players, _ = fixture()
    opt = options(protectionPairs={'round1': 'P5 P1 P5 P2'})
    assert boss._protection_pairs(opt, 1, players) == ([[5, 1], [5, 2]], [])
    assert boss._protection_pairs(options(protectionPairs={'round1': 'P5 P5'}), 1, players) == ([[5, 5]], [])
    opt = options(protectionPairs={'round2a': ['P5', 'P1'], 'round2b': ['P4', 'P2']})
    assert sorted(boss._protection_pairs(opt, 2, players)[0]) == [[4, 2], [5, 1]]
    assert options()['feastStrategy'] == 'immunity'


def test_wrong_protection_target_is_attributed_to_provider_for_any_recipient_class():
    f, am, players, raw, _ = feast_setup()
    opt = options(feastGroups={'round1': 'P1 P2 P3 P4'}, protectionPairs={'round1': 'P5 P1'})
    raw['friendlyBuffs'] = [event(9000, 1022, 'applybuff', sourceID=5, targetID=2)]
    for e in raw['damage']:
        if e['targetID'] == 1:
            e.update(hitType=1, amount=100)
    out = boss._feast_review(f, am, players, raw, opt)['rounds'][0]
    assert [r['playerID'] for r in out['failures']] == [5]
    assert '实际保护给了 P2' in out['failures'][0]['reasons'][0]


def test_round_display_only_shows_assigned_or_actual_immune_players():
    f, am, players, raw, opt = feast_setup()
    raw['damage'].append(event(10000, 1290662, 'damage', targetID=5, sourceID=90, hitType=1, amount=100))
    strike = boss._feast_review(f, am, players, raw, opt)['rounds'][0]['strikes'][0]
    assert strike['participantCount'] == 5
    assert {r['playerID'] for r in strike['displayParticipants']} == {1, 2, 3, 4}


def test_extra_unprotected_player_is_visible_as_direct_soak_not_raid_splash():
    f, am, players, raw, opt = feast_setup()
    raw['damage'].append(event(12039, 1290662, 'damage', targetID=5,
                               sourceID=90, hitType=1, amount=697302))
    strike = boss._feast_review(f, am, players, raw, opt)['rounds'][0]['strikes'][1]
    assert {p['playerID'] for p in strike['displayParticipants']} == {1, 2, 3, 4, 5}
    assert [(p['playerID'], p['damage']) for p in strike['directUnprotected']] == [(5, 697302)]
    assert strike['secondaryRaidDamage'] == []


def test_immune_and_turtle_deflection_count_as_participants_not_damage():
    f,am,players,raw,opt = feast_setup()
    for e in raw['damage']:
        if e['targetID']==4:
            e.update(hitType=0,buffs='186265.')
    raw['damage'] += [event(12000,1310211,'damage',targetID=1,hitType=10,amount=0)]
    out=boss._feast_review(f,am,players,raw,opt)['rounds'][0]
    assert [s['participantCount'] for s in out['strikes']]==[4,4,4]
    assert not out['failures']


def test_early_cancel_and_absent_player_count_once_per_round():
    f,am,players,raw,opt = feast_setup()
    raw['friendlyBuffs']=[event(9000,45438,'applybuff',targetID=1,sourceID=1),event(11500,45438,'removebuff',targetID=1,sourceID=1)]
    for e in raw['damage']:
        if e['targetID']==1 and e['timestamp']>10000: e.update(hitType=1,amount=100)
    raw['damage']=[e for e in raw['damage'] if e['targetID']!=2 or e['timestamp']==10000]
    out=boss._feast_review(f,am,players,raw,opt)['rounds'][0]
    assert {p['playerID'] for p in out['failures']}=={1,2}
    assert all(p['strikeIndices']==[2,3] for p in out['failures'])
    assert '提前结束' in out['failures'][0]['reasons'][0]
    assert out['strikes'][1]['participantCount']==3


def test_missing_protection_is_assigned_to_configured_provider():
    f,am,players,raw,opt = feast_setup()
    # Use round 4 so a single Holy Paladin's protection is the explicit duty.
    raw['casts']=[event(t,1290516,sourceID=90) for t in [1000,2000,3000,10000]]
    players[1]['specID']=71
    for e in raw['damage']:
        if e['targetID']==1:e.update(hitType=1,amount=100)
    opt=options(feastStrategy='immunity',feastGroups={'round4':['P1','P2','P3','P4']},protectionPairs={'round4':['P5','P1']})
    out=boss._feast_review(f,am,players,raw,opt)['rounds'][-1]
    assert [r['playerID'] for r in out['failures']]==[5]


def test_missing_first_strike_does_not_hide_second_strike_failure():
    f,am,players,raw,opt = feast_setup()
    raw['damage']=[e for e in raw['damage'] if e['timestamp']>10000 and e['targetID']!=1]
    out=boss._feast_review(f,am,players,raw,opt)['rounds'][0]
    assert [s['index'] for s in out['strikes']]==[2,3]
    assert out['incomplete'] and out['failures'][0]['playerID']==1


def test_underfilled_raid_splash_does_not_turn_victims_into_soakers():
    f,am,players,raw,opt=feast_setup()
    raw['damage']=[e for e in raw['damage'] if not(e['targetID']==1 and e['timestamp']==12000)]
    raw['damage'] += [event(12325,1290662,'damage',targetID=i,sourceID=90,hitType=1,amount=1000) for i in range(1,6)]
    out=boss._feast_review(f,am,players,raw,opt)['rounds'][0]
    assert len(out['strikes'])==3
    assert out['strikes'][1]['participantCount']==3 and out['strikes'][1]['underfilled']
    assert len(out['strikes'][1]['secondaryRaidDamage'])==5
    assert [p['playerID'] for p in out['failures']]==[1]


def test_fast_raid_splash_156ms_after_immune_soak_is_not_a_participant():
    f, am, players, raw, opt = feast_setup()
    raw['damage'] += [event(12156, 1290662, 'damage', targetID=5,
                            sourceID=90, hitType=1, amount=1000)]
    strike = boss._feast_review(f, am, players, raw, opt)['rounds'][0]['strikes'][1]
    assert strike['participantCount'] == 4
    assert {p['playerID'] for p in strike['participants']} == {1, 2, 3, 4}
    assert [(p['playerID'], p['delayMs']) for p in strike['secondaryRaidDamage']] == [(5, 156)]


def test_nonimmune_mode_and_unresolved_names_never_invent_individual_failures():
    f,am,players,raw,opt=feast_setup()
    raw['damage']=[e for e in raw['damage'] if e['targetID']==1]
    for opt in [options(),options(feastStrategy='immunity'),options(feastStrategy='immunity',feastGroups={'round1':['Missing','P2','P3','P4']})]:
        assert not boss._feast_review(f,am,players,raw,opt)['rounds'][0]['failures']


def test_successful_immunity_substitution_does_not_penalize_absent_assignment():
    f,am,players,raw,opt=feast_setup()
    for e in raw['damage']:
        if e['targetID']==1 and e['timestamp']>10000:e['targetID']=5
    out=boss._feast_review(f,am,players,raw,opt)['rounds'][0]
    assert not out['failures']


def test_absent_warrior_without_preprotection_blames_provider_but_protected_warrior_is_absent():
    f,am,players,raw,opt=feast_setup();players[1]['specID']=71
    raw['casts']=[event(t,1290516,sourceID=90) for t in [1000,2000,3000,10000]]
    raw['damage']=[e for e in raw['damage'] if e['targetID']!=1 or e['timestamp']==10000]
    opt=options(feastStrategy='immunity',feastGroups={'round4':['P1','P2','P3','P4']},protectionPairs={'round4':['P5','P1']})
    out=boss._feast_review(f,am,players,raw,opt)['rounds'][-1]
    assert [p['playerID'] for p in out['failures']]==[5]
    raw.pop('_twinImmunityIntervals')
    raw['friendlyBuffs']=[event(9000,1022,'applybuff',sourceID=5,targetID=1)]
    out=boss._feast_review(f,am,players,raw,opt)['rounds'][-1]
    assert [p['playerID'] for p in out['failures']]==[1]


def test_brood_three_current_deaths_exempt_but_resurrection_restores_review():
    f,am,players,raw=fixture()
    raw['casts']=[event(1000,1308356,sourceID=90),event(10000,1308385,sourceID=99,x=-3733,y=65496)]
    raw['deaths']=[event(5000,0,'death',targetID=i) for i in [1,2,3]]
    out=boss._brood_review(f,am,players,raw,options())
    assert not out['events'] and out['collapseExemption']['deadCount']==3
    raw.pop('_twinLifeEvents')
    raw['trackedActorEvents']=[event(8000,0,'resurrect',targetID=1)]
    out=boss._brood_review(f,am,players,raw,options())
    assert len(out['events'])==1 and out['collapseExemption'] is None


def test_dead_assignment_is_not_penalized_and_resurrection_restores_duty():
    f,am,players,raw,opt=feast_setup()
    raw['damage']=[e for e in raw['damage'] if e['targetID']!=1]
    raw['deaths']=[event(8000,0,'death',targetID=1)]
    assert not boss._feast_review(f,am,players,raw,opt)['rounds'][0]['failures']
    raw.pop('_twinLifeEvents')
    raw['trackedActorEvents']=[event(11000,20484,'resurrect',targetID=1)]
    assert boss._feast_review(f,am,players,raw,opt)['rounds'][0]['failures'][0]['playerID']==1


def test_head_instances_use_target_resource_position_and_live_tank():
    f,am,players,raw=fixture();players[1]['role']='tank';players[2]['role']='tank'
    raw['trackedActorGameIDByActorID']={90:257361,91:257368,99:270898}
    raw['casts']=[event(20000,1289192,sourceID=90,x=-1616,y=69157),event(30000,1308356,sourceID=91),
                  event(31000,1308385,'begincast',sourceID=99,sourceInstance=1),event(35000,1308385,sourceID=99,sourceInstance=1,x=-608,y=69221,resourceActor=1),
                  event(32000,1308385,'begincast',sourceID=99,sourceInstance=2)]
    raw['damage']=[event(25000,1,'damage',sourceID=90,targetID=1),event(30500,1,'damage',sourceID=90,targetID=2)]
    raw['trackedActorEvents']=[event(32200,123,'damage',sourceID=3,targetID=99,targetInstance=2,resourceActor=2,x=-3733,y=65496)]
    raw['interrupts']=[event(33000,2139,'interrupt',sourceID=3,targetID=99,targetInstance=2,extraAbilityGameID=1308385)]
    out=boss._brood_review(f,am,players,raw,options(broodGroups={'left1':['P3']}))
    assert [r['position']['label'] for r in out['events']]==['左1']
    assert out['events'][0]['assigned'][0]['playerID']==2
    assert out['events'][0]['leakLabel']=='左侧近战组第1个蛇头漏断脏腑爆裂'
    assert out['events'][0]['timeMs']==35000
    assert not out['events'][0]['failures']
    assert out['successfulCastCount']==1


def test_unknown_coordinates_do_not_fall_back_to_interrupter_location():
    f,am,players,raw=fixture()
    raw['casts']=[event(10000,1308356,sourceID=90),event(11000,1308385,sourceID=99,sourceInstance=1)]
    raw['trackedActorEvents']=[event(10500,123,'damage',sourceID=1,targetID=99,targetInstance=1,resourceActor=1,x=-608,y=69221)]
    out=boss._brood_review(f,am,players,raw,options())
    assert out['unresolvedCount']==1 and not out['events'][0]['failures']


def test_fourth_far_head_goes_to_backup_without_restarting_rotation():
    f,am,players,raw=fixture()
    raw['casts']=[event(10000,1308356,sourceID=90)]
    raw['casts'] += [event(11000+i*1000,1308385,'begincast',sourceID=99,sourceInstance=i+1,
                          resourceActor=1,x=-3733,y=65496) for i in range(4)]
    raw['casts'] += [event(15000,1308385,sourceID=99,sourceInstance=4,resourceActor=1,x=-3733,y=65496)]
    opt=options(broodGroups={'left1':['P1'],'left2':['P2'],'left3':['P3'],'leftRangedBackup':['P4']})
    out=boss._brood_review(f,am,players,raw,opt)
    assert [r['groupOrder'] for r in out['events']]==[4]
    fourth=out['events'][0]
    assert not fourth['assigned'] and fourth['backup'][0]['playerID']==4
    assert fourth['leakLabel']=='左侧远程组第4个蛇头漏断脏腑爆裂'
    assert all(not r['failures'] for r in out['events'])


def test_only_first_completed_burst_is_returned_even_if_another_head_began_earlier():
    f,am,players,raw=fixture()
    raw['casts']=[event(1000,1308356,sourceID=90),
                  event(2000,1308385,'begincast',sourceID=99,sourceInstance=1),
                  event(3000,1308385,'begincast',sourceID=99,sourceInstance=2),
                  event(7000,1308385,sourceID=99,sourceInstance=1,x=-3733,y=65496),
                  event(5000,1308385,sourceID=99,sourceInstance=2,x=-3733,y=65496),
                  event(8000,1308385,sourceID=99,sourceInstance=2,x=-3733,y=65496)]
    out=boss._brood_review(f,am,players,raw,options())
    assert len(out['events'])==1 and out['successfulCastCount']==1
    row=out['events'][0]
    assert row['instance']==2 and row['groupOrder']==2
    assert row['successTimesMs']==[5000] and row['timeMs']==5000


def test_stone_raid_explosion_count_is_not_victim_count():
    f,am,players,raw=fixture()
    players[2]['role']='tank'
    raw['casts']=[event(10000,1289092,sourceID=90,targetID=2)]
    raw['damage']=[event(10010,1289153,'damage',sourceID=90,targetID=i,amount=100) for i in range(1,6)]
    out=boss._stone_review(f,am,players,raw)
    assert out['raidDamageCount']==1 and out['events'][0]['tank']['playerID']==2
    assert len(out['events'][0]['victims'])==5


def test_stone_counts_only_first_raid_damage_in_a_fight():
    f,am,players,raw=fixture();players[2]['role']='tank'
    raw['casts']=[event(ts,1289092,sourceID=90,targetID=2) for ts in (10000,13000)]
    raw['damage']=[event(ts,1289153,'damage',sourceID=90,targetID=1,amount=100) for ts in (10010,13010)]
    out=boss._stone_review(f,am,players,raw)
    assert out['raidDamageCount']==1 and out['observedRaidDamageCount']==2
    assert [row['raidDamageCount'] for row in out['events']]==[1,0]
    assert out['events'][1]['raidDamage'] and out['events'][1]['exemptionReasons']


def test_stone_prior_ball_explosion_exempts_first_damage_but_later_ball_does_not():
    f,am,players,raw=fixture();players[2]['role']='tank'
    raw['casts']=[event(10000,1289092,sourceID=90,targetID=2)]
    raw['damage']=[event(9000,1290338,'damage',targetID=1,amount=100),
                   event(10010,1289153,'damage',sourceID=90,targetID=1,amount=100)]
    out=boss._stone_review(f,am,players,raw)
    assert out['raidDamageCount']==0
    assert out['events'][0]['priorBallExplosionTimeMs']==9000
    assert '炸球' in out['events'][0]['exemptionReasons'][0]
    raw['casts'].append(event(13000,1289092,sourceID=90,targetID=2))
    raw['damage'].append(event(13010,1289153,'damage',sourceID=90,targetID=1,amount=100))
    out=boss._stone_review(f,am,players,raw)
    assert out['raidDamageCount']==0 and '之后' in out['events'][1]['exemptionReasons'][0]
    raw['damage'][0]['timestamp']=11000
    assert boss._stone_review(f,am,players,raw)['raidDamageCount']==1


def test_stone_exempts_only_when_more_than_three_players_died_before_damage():
    f,am,players,raw=fixture();players[2]['role']='tank'
    raw['casts']=[event(10000,1289092,sourceID=90,targetID=2)]
    raw['damage']=[event(10010,1289153,'damage',sourceID=90,targetID=1,amount=100)]
    raw['deaths']=[event(9000,0,'death',targetID=i) for i in (1,3,4)]
    assert boss._stone_review(f,am,players,raw)['raidDamageCount']==1
    raw['deaths'].append(event(9500,0,'death',targetID=5))
    out=boss._stone_review(f,am,players,raw)
    assert out['raidDamageCount']==0 and out['events'][0]['priorDeathCount']==4
    assert '超过 3 人' in out['events'][0]['exemptionReasons'][0]


def test_stone_stops_at_first_tank_death_and_never_blames_non_tank():
    f,am,players,raw=fixture();players[2]['role']='tank'
    raw['deaths']=[event(11000,0,'death',targetID=2)]
    raw['casts']=[event(10000,1289092,sourceID=90,targetID=2),event(12000,1289092,sourceID=90,targetID=3)]
    raw['damage']=[event(ts,1289153,'damage',targetID=1,amount=100) for ts in [10000,12000,16000]]
    out=boss._stone_review(f,am,players,raw)
    assert out['raidDamageCount']==1 and len(out['events'])==1
    assert out['tankDeathCutoffMs']==11000
    raw['deaths']=[]
    out=boss._stone_review(f,am,players,raw)
    assert out['events'][1]['tank']['playerID']==2


def test_failed_stone_has_no_target_cast_and_uses_same_combo_target():
    f,am,players,raw=fixture();players[2]['role']='tank'
    raw['casts']=[event(10000,1289092,sourceID=90,targetID=2),event(10000,1288538,sourceID=90),event(13000,1288538,sourceID=90)]
    raw['damage']=[event(13010,1289153,'damage',sourceID=90,targetID=i,amount=100) for i in range(1,6)]
    out=boss._stone_review(f,am,players,raw)
    assert out['events'][1]['tank']['playerID']==2 and out['events'][1]['raidDamage']


def test_death_aura_removal_batch_preserves_stack_and_all_death_details():
    f,am,players,raw=fixture()
    raw['debuffs']=[event(5000,1290336,'applydebuffstack',targetID=1,stack=5),event(19999,1290336,'removedebuff',targetID=1)]
    raw['deaths']=[event(20000,0,'death',targetID=1,killingAbilityGameID=1289994),event(40000,0,'death',targetID=2,killingAbilityGameID=1290480)]
    raw['damage']=[event(20000,1289994,'damage',targetID=1,amount=100),event(30000,1290338,'damage',targetID=2,amount=100)]
    early,venom=boss._death_reviews(f,am,players,raw,options())
    assert len(early['deaths'])==2 and early['earlyDeaths'][0]['playerID']==1
    assert venom['expectedGlobuleCount']==5
    assert venom['explosions'][0]['nearbyVenomDeaths'][0]['playerID']==1
    assert early['deaths'][0]['precedingDamage'][0]['spellID']==1289994


def test_all_disabled_skips_new_streams_and_has_only_survival_tab():
    captured={}
    def build(config,analyzer,reports,opts):
        captured.update(config)
        return {'data':{'page1_wipeAnalysis':[]}}
    with patch.object(boss,'_build',side_effect=build):
        out=boss.build_aggregated_json('a'*16,{key:False for key in boss.REVIEW_KEYS})
    assert captured['fetchKeys']=={'friendlyCasts','deaths','combatants'}
    assert not captured['trackedActorGameIDs'] and not captured['trackedActorEventFilters']
    assert captured['tabs']==[['survival','全场存活情况']]
    assert out['data']['mechanicOverview']['metrics']==[]


def test_boss_configuration_is_not_mutated():
    before=deepcopy(boss.BOSS_CONFIG)
    with patch.object(boss,'_build',return_value={'data':{'page1_wipeAnalysis':[]}}):
        boss.build_aggregated_json('a'*16)
    assert boss.BOSS_CONFIG==before


def test_confirmed_death_names_and_player_in_nightly_detail():
    f,am,players,raw=fixture()
    ids=[1306876,1294976,1295107,1292348,1310105]
    raw['deaths']=[event(10000+i*10000,0,'death',targetID=i+1,killingAbilityGameID=sid) for i,sid in enumerate(ids)]
    early,venom=boss._death_reviews(f,am,players,raw,options())
    assert [r['killingSpell'] for r in early['deaths']]==['血色风暴','剧毒烟气','浓缩唾液','永恒毒液','污秽爆发']
    assert early['deaths'][0]['avoidable']
    pull={'fightID':1,'twinfangs':{'earlyDeaths':early}}
    metric=next(m for m in boss._mechanic_overview([pull])['metrics'] if m['key']=='earlyDeaths')
    assert metric['events'][0]['text'].startswith('P1：血色风暴')


def test_short_pull_retains_deaths_but_is_excluded_from_nightly_metrics():
    pull={'fightID':44,'durationMs':22300,'isKill':False,'twinfangs':{'earlyDeaths':{'enabled':True,'earlyDeaths':[]}}}
    with patch.object(boss,'_build',return_value={'data':{'page1_wipeAnalysis':[pull]}}):
        result=boss.build_aggregated_json('a'*16)
    assert pull['shortPull'] and pull['wipePhase']=='误开怪 / ADD处理'
    assert all(m['value']==0 for m in result['data']['mechanicOverview']['metrics'])


def test_five_ranged_slots_and_no_wrap_after_fifth():
    for order in (4, 5, 6):
        f,am,players,raw=fixture()
        raw['casts']=[event(10000,1308356,sourceID=90)]
        raw['casts'] += [event(11000+i*1000,1308385,'begincast',sourceID=99,sourceInstance=i+1,
                              resourceActor=1,x=-3733,y=65496) for i in range(order)]
        raw['casts'] += [event(20000,1308385,sourceID=99,sourceInstance=order,resourceActor=1,x=-3733,y=65496)]
        opt=options(broodGroups={**{f'left{i}':[f'P{i}'] for i in range(1,6)},'leftRangedBackup':['P1']})
        row=boss._brood_review(f,am,players,raw,opt)['events'][0]
        assert row['groupOrder']==order
        if order <= 5:
            assert row['assigned'][0]['playerID']==order
        else:
            assert not row['assigned'] and row['backup'][0]['playerID']==1
def test_replay_shield_break_uses_absorb_removal_and_last_attacker():
    players={1:{"name":"First"},2:{"name":"Breaker"}}
    raw={"actorRows":[{"id":9,"gameID":boss.BULWARK_NPC_ID}],"replayEvents":[
        {"timestamp":100,"type":"cast","sourceID":9,"sourceInstance":2,"abilityGameID":1303378,"resourceActor":1,"x":20,"y":30},
        {"timestamp":200,"type":"absorbed","sourceID":1,"targetID":9,"targetInstance":2,"abilityGameID":123},
        {"timestamp":450,"type":"damage","sourceID":2,"targetID":9,"targetInstance":2,"abilityGameID":123},
        {"timestamp":500,"type":"removebuff","sourceID":9,"sourceInstance":2,"targetID":9,"targetInstance":2,"abilityGameID":1303378},
    ],"friendlyCasts":[{"timestamp":350,"type":"cast","sourceID":1,"abilityGameID":119381}],"friendlyBuffs":[
        {"timestamp":200,"type":"applybuff","sourceID":1,"targetID":2,"abilityGameID":1022},
        {"timestamp":600,"type":"removebuff","sourceID":1,"targetID":2,"abilityGameID":1022},
    ]}
    result=boss._replay_feedback({"startTime":0,"endTime":1000},{1:"First",2:"Breaker"},players,raw)
    wall=result["bulwarks"][0]
    assert wall["endTimeMs"]==500
    assert wall["breaker"]["playerID"]==2
    assert len(wall["attacks"])==2
    assert result["controls"][0]["spellID"]==119381
    assert result["immunities"][0]["playerID"]==2
    assert result["immunities"][0]["endTimeMs"]==600


def test_replay_raid_damage_is_not_avoidable_feedback_and_channels_follow_cast():
    raw={"actorRows":[],"replayEvents":[
        {"timestamp":100,"type":"damage","sourceID":9,"targetID":1,"abilityGameID":1292806,"amount":10},
        {"timestamp":200,"type":"damage","sourceID":9,"targetID":1,"abilityGameID":1306876,"amount":10},
        {"timestamp":300,"type":"cast","sourceID":9,"targetID":1,"abilityGameID":1289192},
    ],"friendlyBuffs":[]}
    result=boss._replay_feedback({"startTime":0,"endTime":10000},{1:"Tank"},{1:{"name":"Tank"}},raw)
    assert [h["spellID"] for h in result["hits"]]==[1306876]
    channel=result["channels"][0]
    assert (channel["startTimeMs"],channel["endTimeMs"],channel["targetID"])==(300,4300,1)
    assert channel["phase"]=="channel"


def test_replay_striker_windup_and_death_are_instance_local():
    rows=[{"timestamp":100,"type":"begincast","sourceID":9,"sourceInstance":2,"abilityGameID":1291478,"resourceActor":1,"x":-624,"y":63384},
          {"timestamp":5100,"type":"cast","sourceID":9,"sourceInstance":2,"targetID":1,"abilityGameID":1291478},
          {"timestamp":5500,"type":"death","targetID":9,"targetInstance":2,"abilityGameID":0},
          {"timestamp":6000,"type":"begincast","sourceID":9,"sourceInstance":3,"abilityGameID":1291478,"resourceActor":1,"x":22,"y":63613}]
    heads,_=boss._replay_animation_units({"startTime":0,"endTime":10000},rows,{"actorRows":[{"id":9,"gameID":boss.STRIKER_NPC_ID}]},{})
    assert heads[0]["endTimeMs"]==5500 and heads[1]["endTimeMs"] is None
    assert heads[0]["arena"]=="north" and heads[0]["slot"]=="left"
    assert heads[0]["casts"][0]["targetID"]==1


def test_feast_channel_stops_on_boss_death_instead_of_running_past_it():
    rows = [
        {"timestamp": 2000, "type": "cast", "sourceID": 9, "abilityGameID": 1290516},
        {"timestamp": 5000, "type": "death", "targetID": 9},
    ]
    _, channels = boss._replay_animation_units(
        {"startTime": 0, "endTime": 10000}, rows, {"actorRows": []}, {}
    )
    assert len(channels) == 1
    assert channels[0]["phase"] == "channel"
    assert (channels[0]["startTimeMs"], channels[0]["endTimeMs"]) == (2000, 5000)


def test_rotation_uses_paladin_path_and_separated_hits():
    from math import sin,cos,radians,degrees
    rows=[{"timestamp":1000,"type":"cast","sourceID":9,"abilityGameID":1,"resourceActor":1,"x":-1616,"y":69157},
          {"timestamp":10000,"type":"cast","sourceID":9,"abilityGameID":1294293,"resourceActor":1,"x":0,"y":61155}]
    for time,angle in [(10500,80),(18000,-70)]:
        rows.append({"timestamp":time,"type":"damage","sourceID":9,"targetID":2,"abilityGameID":1294605,"resourceActor":2,"x":round(3000*cos(radians(angle))),"y":61155+round(3000*sin(radians(angle)))})
    for i in range(20):
        a=radians(90-i*4)
        rows.append({"timestamp":10000+i*500,"type":"damage","sourceID":1,"targetID":9,"abilityGameID":1,"resourceActor":1,"x":round(3000*cos(a)),"y":61155+round(3000*sin(a))})
    torrents=[{"actorID":9,"startTimeMs":10000,"endTimeMs":24000}]
    boss._torrent_rotation(torrents,rows,0,{1:{"specID":66},2:{"specID":62}})
    assert torrents[0]["rotationDirection"]==-1
    assert abs(torrents[0]["fittedAngularSpeedDegrees"]-20)<.1
    assert abs(torrents[0]["angularSpeedDegrees"]*14-270)<.001
    assert abs(degrees(torrents[0]["initialAngleRadians"])-90)<.2
    assert torrents[0]["previousArena"]=="north"


def test_venom_sources_use_head_instance_order_and_do_not_count_raid_tick_as_wave():
    fight, actor_map, players, raw = fixture()
    raw['casts'] = [event(10000,1291478,sourceID=70,sourceInstance=1,targetID=1),
                    event(11000,1291478,sourceID=70,sourceInstance=2,targetID=2),
                    event(20000,1291478,sourceID=70,sourceInstance=1,targetID=2)]
    raw['damage'] = [event(10005,1293295,'damage',sourceID=70,sourceInstance=1,targetID=1,amount=1),
                     event(11005,1293295,'damage',sourceID=70,sourceInstance=2,targetID=2,amount=1),
                     event(20005,1292806,'damage',targetID=2,amount=1),
                     event(20005,1293295,'damage',sourceID=70,sourceInstance=1,targetID=2,amount=1)]
    raw['debuffs'] = [event(10006,1290336,'applydebuff',targetID=1),
                      event(11006,1290336,'applydebuff',targetID=2),
                      event(20006,1290336,'applydebuffstack',targetID=2,stack=2)]
    histories = boss.analyze_twinfangs(fight,actor_map,players,raw)['eternalVenom']['players']
    second = next(p for p in histories if p['playerID']==2)
    assert [e['originKey'] for e in second['events']] == ['spitFirst','spitRepeat']
    assert second['events'][1]['category'] == 'abnormal'


def test_death_reduction_to_nonzero_stack_has_own_source_and_is_not_double_subtracted():
    fight, actor_map, players, raw = fixture()
    raw['damage'] = [event(1000,1289201,'damage',targetID=1,amount=1)]
    raw['debuffs'] = [event(1000,1290336,'applydebuffstack',targetID=1,stack=7),
                      event(19999,1290336,'removedebuffstack',targetID=1,stack=4)]
    raw['deaths'] = [event(20000,0,'death',targetID=1)]
    raw['trackedActorEvents'] = [event(30000,1294293,'applybuff',sourceID=90,targetID=90),
                                event(44000,1294293,'removebuff',sourceID=90,targetID=90)]
    out = boss.analyze_twinfangs(fight,actor_map,players,raw)
    checkpoint = next(p for p in out['eternalVenom']['checkpoints'][0]['players'] if p['playerID']==1)
    assert checkpoint['sourceStacks'] == {'orb':7}
    assert checkpoint['deathReduction'] == checkpoint['observedDeathReduction'] == 3
    assert checkpoint['stacks'] == 4 and checkpoint['reconciliationDelta'] == 0
    assert checkpoint['otherReduction'] == 0


def test_immune_wave_that_adds_venom_is_visible_but_raid_pulse_is_not():
    fight, actor_map, players, raw = fixture()
    raw['damage'] = [event(1000,1292807,'damage',targetID=1,amount=0,hitType=10),
                     event(2000,1292806,'damage',targetID=1,amount=1)]
    raw['debuffs'] = [event(1001,1290336,'applydebuff',targetID=1)]
    out = boss.analyze_twinfangs(fight,actor_map,players,raw)
    assert out['eternalVenom']['players'][0]['events'][0]['originKey'] == 'wave'
    assert [h['spellID'] for h in out['replayFeedback']['hits']] == [1292807]


def test_wave_aura_without_damage_proves_source_and_contact_is_counted_once():
    fight, actor_map, players, raw = fixture()
    raw['debuffs'] = [event(10000,1292807,'applydebuff',targetID=1),
                      event(10009,1290336,'applydebuff',targetID=1),
                      event(10200,1292807,'removedebuff',targetID=1)]
    raw['casts'] = [event(10008,1290336,targetID=1),event(13000,1291404)]
    out = boss.analyze_twinfangs(fight,actor_map,players,raw)
    assert out['eternalVenom']['players'][0]['events'][0]['originKey'] == 'wave'
    assert out['waveHits']['players'][0]['hitCount'] == 1
    assert out['waveHits']['players'][0]['totalDamage'] == 0
    raw['damage'] = [event(10100,1292807,'damage',targetID=1,amount=10),
                     event(10150,1292807,'damage',targetID=1,amount=20)]
    assert len(boss._wave_contact_events(raw)) == 1
    assert boss._wave_contact_events(raw)[0]['amount'] == 30


def test_future_emergence_is_not_misattributed_to_an_earlier_stack():
    idx = boss._venom_source_index([event(13000,1308122,'damage',targetID=1,amount=1)], [], [])
    _,sid,category = boss._venom_attribution([], [event(13000,1291404)],10000,1,idx)
    assert sid is None and category == 'unknown'
