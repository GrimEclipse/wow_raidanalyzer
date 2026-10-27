from unittest.mock import Mock
import pytest
from analyzer_core.config import resolve_analysis_options
from boss_plugins.venomous_abyss.shared import position_at, position_at_interpolated
import math

from analyzer_core.combat_replay import build_replay_tracks
from boss_plugins.venomous_abyss import coiledaltar as boss


def test_facing_belongs_to_resource_owner_and_zero_is_valid():
    events = [dict(timestamp=100, sourceID=1, targetID=2, resourceActor=2,
                   x=10, y=20, facing=0),
              dict(timestamp=200, sourceID=1, targetID=2, resourceActor=1,
                   x=30, y=40, facing=314)]
    args = ({'startTime': 0, 'endTime': 1000}, {1: {'name': 'A'}, 2: {'name': 'B'}}, {}, events)
    units = {u['actorID']: u for u in build_replay_tracks(*args, include_facing=True)['units']}
    assert units[2]['facingSamples'] == [[100, 0]]
    assert units[1]['facingSamples'] == [[200, 314]]
    assert all('facingSamples' not in u for u in build_replay_tracks(*args)['units'])


def test_dropped_globule_is_same_object_but_distinct_spawn_remains():
    venom = {'carriers': [dict(playerID=1, puddleID=1, venomKind='normal',
                 removeTimeMs=1000, dropPosition={'x': 100, 'y': 200})],
        'groundPuddles': [dict(puddleID=2, venomKind='normal', groundedFromMs=1050,
                              position={'x': 110, 'y': 200}),
                          dict(puddleID=3, venomKind='normal', groundedFromMs=1050,
                              position={'x': 400, 'y': 200})],
        'rounds': [{'spawns': [dict(spawnTimeMs=1050, venomKind='normal',
                                  position={'x': 110, 'y': 200}),
                              dict(spawnTimeMs=1050, venomKind='normal',
                                  position={'x': 400, 'y': 200})]}]}
    boss._merge_venom_drop_spawns(venom)
    assert [p['puddleID'] for p in venom['groundPuddles']] == [1, 3]
    assert venom['rounds'][0]['spawnCount'] == 1


def test_pickup_cannot_match_a_globule_cleared_by_p2_transition():
    fight = {'startTime': 0, 'endTime': 10000}
    casts = [dict(timestamp=100, type='cast', abilityGameID=boss.TOXIC_DELUGE, sourceID=8),
             dict(timestamp=200, type='cast', abilityGameID=boss.COALESCED_VENOM_CAST,
                  sourceID=9, sourceInstance=1, sourceResources={'x': 100, 'y': 100})]
    debuffs = [dict(timestamp=5000, type='applydebuff', abilityGameID=boss.VOLATILE_VENOM,
                    targetID=1), dict(timestamp=6000, type='removedebuff',
                                     abilityGameID=boss.VOLATILE_VENOM, targetID=1)]
    positions = boss.build_position_index([dict(timestamp=5000, type='cast', sourceID=1,
                                               sourceResources={'x': 100, 'y': 100})])
    markers = [{'key': 'p1', 'timeMs': 0}, {'key': 'p2', 'timeMs': 2000}, {'key': 'p3', 'timeMs': 4000}]
    venom = boss.analyze_toxic_deluge(fight, casts, debuffs, positions, {1: 'A'},
                                     {1: {'name': 'A'}}, markers)
    old = next(p for p in venom['groundPuddles'] if p['groundedFromMs'] == 200)
    assert venom['carriers'][0]['puddleID'] != old['puddleID']


def make_ghost_scene(facing, missing=False):
    mechanics = {'combatReplay': {'units': [dict(actorID=1, kind='player',
        samples=[[t, 0, 0] for t in range(0, 2100, 100)],
        facingSamples=[] if missing else [[t, facing*100] for t in range(0, 2100, 100)])]},
        'manifestations': {'fixations': [dict(manifest={'sourceID': 9, 'sourceInstance': 1},
            playerID=1, applyTimeMs=0, removeTimeMs=2000, despawnTimeMs=2000)]}}
    raw = {'casts': [dict(type='cast', timestamp=0, sourceID=9, sourceInstance=1,
                         abilityGameID=boss.FIXATION, sourceResources={'x': 1000, 'y': 0})]}
    return boss._build_manifest_replay({'startTime': 0, 'endTime': 2000}, mechanics,
                                       raw, {1: {'name': 'A'}}, {1: 'A'})


def test_ghost_only_moves_when_target_faces_away_with_fresh_evidence():
    watched = make_ghost_scene(math.radians(29))['ghosts'][0]
    away = make_ghost_scene(math.radians(31))['ghosts'][0]
    missing = make_ghost_scene(0, missing=True)['ghosts'][0]
    assert watched['samples'][-1][1] == 1000
    assert away['samples'][-1][1] < 1000
    assert missing['samples'][-1][1] == 1000
    assert missing['samples'][-1][5] == 0


def test_player_resource_snapshot_cannot_be_used_as_npc_position():
    event = dict(type='damage', sourceID=1, targetID=9, resourceActor=1, x=10, y=20)
    assert boss._npc_actor_point(event, 9) is None


def test_resonance_only_attributes_nearby_unique_mover_and_not_both():
    def scene(second_facing=0, second_x=200):
        players = {1: {'name': 'Moving'}, 2: {'name': 'Watching'}}
        units = [dict(actorID=pid, kind='player',
                 samples=[[t, 0, 0] for t in range(0, 2100, 100)],
                 facingSamples=[[t, face*100] for t in range(0, 2100, 100)])
                 for pid, face in [(1, math.pi), (2, second_facing)]]
        fixations = [dict(manifest={'sourceID': 9, 'sourceInstance': pid}, playerID=pid,
                         applyTimeMs=0, removeTimeMs=2000, despawnTimeMs=2000)
                     for pid in players]
        raw = {'casts': [dict(type='cast', timestamp=0, sourceID=9, sourceInstance=pid,
                    abilityGameID=boss.FIXATION, sourceResources={'x': x, 'y': 0})
                    for pid, x in [(1, 400), (2, second_x)]],
               'debuffs': [dict(type='applydebuff', timestamp=600, targetID=pid,
                               abilityGameID=next(iter(boss.MANIFEST_COLLISION_DEBUFF_IDS)))
                          for pid in players]}
        mechanics = {'combatReplay': {'units': units}, 'manifestations': {'fixations': fixations}}
        return boss._build_manifest_replay({'startTime': 0, 'endTime': 2000}, mechanics,
            raw, players, {1: 'Moving', 2: 'Watching'})['resonanceCollisions'][0]
    assert scene()['responsiblePlayerID'] == 1
    assert scene(math.pi)['responsiblePlayerID'] is None
    assert scene(second_x=2000)['responsiblePlayerID'] is None


def test_sever_stack_delta_excludes_phase_cleanup_explosion():
    fight = {'startTime': 0, 'phaseTransitions': [{'startTime': 1300}]}
    raw = {'debuffs': [dict(timestamp=900, targetID=1, type='applydebuff',
                           abilityGameID=boss.VENOM_RUPTURE, stack=2),
                       dict(timestamp=1100, targetID=1, type='applydebuffstack',
                           abilityGameID=boss.VENOM_RUPTURE, stack=3),
                       dict(timestamp=1300, targetID=1, type='applydebuffstack',
                           abilityGameID=boss.VENOM_RUPTURE, stack=8)]}
    point = dict(puddleID=1, groundedFromMs=0, position={'x': 100, 'y': 0})
    row = dict(timeMs=1000, spellID=next(iter(boss.SEVER_IDS)), origin={'x': 0, 'y': 0}, facingRadians=0)
    boss._reconcile_venom_severs(fight, raw, [point], {'rounds': [row]})
    assert row['stackClearCheck']['observedCount'] == 1
    assert row['stackClearCheck']['status'] == 'matched'


def test_replay_reach_covers_observed_far_clear_without_clearing_next_ball():
    # M kill 8:26.6: the near 44-yard ball participates in the six-stack
    # increase, while the farther dropped ball remains for the next cycle.
    origin, facing = (378, 114133), -1.834650299
    assert boss.in_frontal_cone(origin, facing, (327, 118533))
    assert not boss.in_frontal_cone(origin, facing, (-298, 118718))


def test_zuljan_revives_in_vulnerability_phase_without_inventing_health():
    body = {'phaseTimeline': [{'key':'intermission','timeMs':3000}],
            'combatReplay': {'bosses':[dict(actorID=9,states=[[1000,'dead']],health=[[4000,50,100]])],
                             'units':[dict(actorID=9,states=[[1000,'dead']])]}}
    boss._apply_altar_boss_lifetimes(body,[dict(id=99,name="Zul'jan",gameID=270093),
                                         dict(id=9,name="Zul'jan",gameID=257911)])
    assert body['combatReplay']['bosses'][0]['states'] == [[1000,'dead'],[3000,'alive']]
    assert body['combatReplay']['bosses'][0]['health'] == [[4000,50,100]]
    assert body['combatReplay']['units'][0]['states'][-1] == [3000,'alive']


def test_vulnerability_damage_fetch_targets_real_boss_only_within_phase():
    calls = []
    class Client:
        def events(self, report, kind, fight, **kwargs):
            calls.append((kind,kwargs))
            return [{'evidence':'actual-boss'}] if kind == 'DamageDone' else []
    fight = {'startTime':0,'endTime':20000,'phaseTransitions':[
        {'id':3,'startTime':1000},{'id':4,'startTime':5000}]}
    payload = boss.fetch_payload(Client(),'example',fight,[
        dict(id=99,name="Zul'jan",gameID=270093),dict(id=9,name="Zul'jan",gameID=257911)], options={"intermissionReviewEnabled":True})
    query = next(opts for kind,opts in calls if kind == 'DamageDone')
    assert query['target_id'] == 9
    assert (query['start_time'],query['end_time']) == (1000,5000)
    assert payload['bossDamage'] == [{'evidence':'actual-boss'}]


def test_soulcoiler_instances_have_separate_cast_interrupt_health_and_death():
    units = [dict(key=f'9:{i}',actorID=9,instance=i,gameID=boss.SOULCOILER_NPC_GAME_ID,
             samples=[[100,10,20]],states=[[1500,'dead']] if i==1 else []) for i in (1,2)]
    rows = [dict(type='begincast',timestamp=100,sourceID=9,sourceInstance=i,abilityGameID=1286399) for i in (1,2)]
    rows += [dict(type='interrupt',timestamp=500,sourceID=1,targetID=9,targetInstance=1,abilityGameID=96231),
             dict(type='damage',timestamp=600,sourceID=1,targetID=9,targetInstance=2,resourceActor=1,hitPoints=5,maxHitPoints=100),
             dict(type='damage',timestamp=700,sourceID=1,targetID=9,targetInstance=2,resourceActor=2,hitPoints=80,maxHitPoints=100)]
    result = boss._build_soulcoiler_replay({'startTime':0,'endTime':20000},
        {'combatReplay':{'units':units}},{'replayEvents':rows},{1:{'name':'A'}},{1:'A'})['actors']
    assert result[0]['casts'][0]['outcome'] == 'interrupted'
    assert result[0]['casts'][0]['endTimeMs'] == 500
    assert result[1]['casts'][0]['endTimeMs'] == 10100
    assert result[1]['health'] == [[700,80,100]]
    assert result[0]['endTimeMs'] == 1500


def test_wail_duration_is_independent_of_early_interrupt_and_curse_adjusts_rate():
    units = [dict(key='9:1',actorID=9,instance=1,gameID=boss.SOULCOILER_NPC_GAME_ID,
                  samples=[[0,10,20]],states=[])]
    rows = [dict(type='begincast',timestamp=0,sourceID=9,sourceInstance=1,abilityGameID=1286399),
            dict(type='interrupt',timestamp=1000,sourceID=1,targetID=9,targetInstance=1,abilityGameID=96231),
            dict(type='applydebuff',timestamp=1500,targetID=9,targetInstance=1,abilityGameID=1714),
            dict(type='begincast',timestamp=2000,sourceID=9,sourceInstance=1,abilityGameID=1286399),
            dict(type='removedebuff',timestamp=5000,targetID=9,targetInstance=1,abilityGameID=1714)]
    casts = boss._build_soulcoiler_replay({'startTime':0,'endTime':20000},
        {'combatReplay':{'units':units}},{'replayEvents':rows},{1:{'name':'A'}},{1:'A'})['actors'][0]['casts']
    assert casts[0]['durationMs'] == 10000
    assert casts[0]['expectedEndTimeMs'] == 10000
    assert casts[0]['endTimeMs'] == 1000
    assert casts[1]['progressSegments'] == [[2000,0,12000],[5000,.25,10000]]
    assert casts[1]['expectedEndTimeMs'] == 12500


def test_altar_channels_anchor_ground_and_fourth_purple_covers_floor():
    casts = [dict(type='cast',timestamp=t,abilityGameID=spell,sourceID=9)
             for t,spell in [(0,1282487),(50000,1282487),(100000,1298381),(200000,1298381),
                             (300000,1298381),(400000,1298381)]]
    mechanics = {'combatReplay':{'bosses':[dict(actorID=9,casts=[])]}}
    scene = boss._build_altar_ground_replay({'startTime':0,'endTime':500000},mechanics,{'casts':casts})
    assert scene['rounds'][0]['kind'] == 'green'
    assert scene['rounds'][0]['channelEndTimeMs'] == 8000
    assert scene['rounds'][-1]['fullCoverage']
    assert [r['peakRadiusYards'] for r in scene['rounds'] if r['kind']=='green'] == [40,50]
    assert [r['peakRadiusYards'] for r in scene['rounds'] if r['kind']=='purple'] == [40,50,65,80]
    assert scene['rounds'][0]['recedeStartTimeMs'] == 23000
    assert scene['rounds'][0]['endTimeMs'] == 47000
    assert scene['rounds'][2]['endTimeMs'] == 147000
    assert all(c['phase'] == 'channel' for c in mechanics['combatReplay']['bosses'][0]['casts'])


def test_nightfall_replay_uses_fixed_duration_and_real_interrupt_not_next_cast():
    mechanics = {'combatReplay':{'bosses':[dict(actorID=9,casts=[
        dict(spellID=boss.ETERNAL_NIGHTFALL,startTimeMs=0,endTimeMs=20000,outcome='unconfirmed')])]}}
    rows = [dict(type='begincast',timestamp=0,sourceID=9,abilityGameID=boss.ETERNAL_NIGHTFALL),
            dict(type='interrupt',timestamp=5000,sourceID=1,targetID=8,
                 abilityGameID=6552,extraAbilityGameID=boss.ETERNAL_NIGHTFALL),
            dict(type='interrupt',timestamp=6000,sourceID=1,targetID=9,
                 abilityGameID=6552,extraAbilityGameID=999),
            dict(type='interrupt',timestamp=11000,sourceID=1,targetID=9,
                 abilityGameID=6552,extraAbilityGameID=boss.ETERNAL_NIGHTFALL),
            dict(type='begincast',timestamp=20000,sourceID=9,abilityGameID=boss.ETERNAL_NIGHTFALL),
            dict(type='cast',timestamp=35000,sourceID=9,abilityGameID=boss.ETERNAL_NIGHTFALL),
            dict(type='begincast',timestamp=40000,sourceID=9,abilityGameID=boss.ETERNAL_NIGHTFALL)]
    # The same transport row may occur in more than one fetched page.
    rows.append(dict(rows[0]))
    boss._apply_altar_nightfall_replay({'startTime':0,'endTime':60000},mechanics,
        {'replayEvents':rows},{1:{'name':'A'}},{1:'A'})
    casts = mechanics['combatReplay']['bosses'][0]['casts']
    assert len(casts) == 3
    assert casts[0]['durationMs'] == 15000
    assert casts[0]['expectedEndTimeMs'] == 15000
    assert casts[0]['endTimeMs'] == 11000
    assert casts[0]['outcome'] == 'interrupted'
    assert casts[0]['interruptedBy']['playerID'] == 1
    assert casts[0]['interruptIcon'] == '/assets/spells/6552.png'
    assert casts[1]['endTimeMs'] == 35000
    assert casts[1]['outcome'] == 'completed'
    assert casts[2]['endTimeMs'] == 55000
    assert casts[2]['outcome'] == 'unconfirmed'


def test_clear_constraint_preserves_spawn_and_stationary_intervals():
    ghost = {'samples':[[0,100,0,1,0,1,None], [100,130,0,1,1,1,100],
                         [200,130,0,1,0,1,100], [300,160,0,1,1,1,300]]}
    assert boss._constrain_manifest_endpoint(ghost,300,(200,0))
    assert ghost['samples'][0][1:3] == [100,0]
    assert ghost['samples'][1][1:3] == ghost['samples'][2][1:3]
    assert ghost['samples'][-1][1:3] == [200,0]
    assert 'estimate' in ghost['positionEvidence']


def test_sparse_paths_respect_recorded_and_unrecorded_contacts():
    import copy
    ghosts = [dict(key='a',startTimeMs=0,endTimeMs=4000,
                   samples=[[0,0,0,1,0,1,None],[1000,30,0,1,1,1,1000],[2100,50,0,1,1,1,2100]]),
              dict(key='b',startTimeMs=0,endTimeMs=4000,
                   samples=[[0,300,0,2,0,1,None],[1000,300,0,2,0,1,None],[2100,60,0,2,1,1,2100]])]
    observed = copy.deepcopy(ghosts)
    boss._exclude_unrecorded_manifest_contacts(observed,[{'timeMs':2100,'playerIDs':[1,2]}])
    assert observed == ghosts
    boss._exclude_unrecorded_manifest_contacts(ghosts,[])
    assert abs(ghosts[0]['samples'][-1][1]-ghosts[1]['samples'][-1][1]) >= 150
    assert ghosts[0]['samples'][0][1] == 0
    assert 'estimate' in ghosts[0]['positionEvidence']


def test_defaults_focus_on_p2_and_have_no_plan_import():
    opts = resolve_analysis_options(boss.CONFIG_SCHEMA, {})
    for key in ('toxicDelugeReviewEnabled', 'severReviewEnabled', 'guillotineReviewEnabled',
                'dreadmarchReviewEnabled', 'blightedSeverReviewEnabled', 'grimGuillotineReviewEnabled',
                'intermissionReviewEnabled'):
        assert not opts[key]
    assert opts['fieldReplayEnabled'] and opts['playerTimelineEnabled'] and opts['guillotineTelegraphEnabled']
    assert 'burstPlan' not in opts


def test_replay_stream_reused_without_duplicate_timeline_requests():
    opts = resolve_analysis_options(boss.CONFIG_SCHEMA, {})
    client = Mock()
    casts = [dict(timestamp=100, type='cast', sourceID=1, abilityGameID=107574)]
    damage = dict(timestamp=200, type='damage', sourceID=1, targetID=90, amount=20)
    raw = dict(reportGuild={'id':774422}, replayEvents=[*casts, damage], friendlyCasts=casts,
               friendlyBuffs=[], debuffs=[])
    result = boss._fetch_guild_timeline(client, 'r', {'difficulty':5},
        [dict(id=90, gameID=257911)], raw, opts)
    assert result['guildPlayerCasts'] is casts
    assert result['guildBossDamage'] == [damage]
    client.events.assert_not_called()
    opts['playerTimelineEnabled'] = False
    assert boss._fetch_guild_timeline(client, 'r', {}, [], raw, opts) is raw
    client.events.assert_not_called()


def test_foreign_guild_sees_actual_casts_without_avalon_checks():
    opts = resolve_analysis_options(boss.CONFIG_SCHEMA, {})
    players = {1:dict(id=1, name='A', role='melee-dps')}
    raw = dict(reportGuild={'id':1}, casts=[], enemyBuffs=[], guildPlayerCasts=[
        dict(timestamp=1200,type='begincast',sourceID=1,abilityGameID=107574),
        dict(timestamp=1500,type='cast',sourceID=1,abilityGameID=107574)])
    result = boss.analyze_guild_timeline(dict(startTime=1000,endTime=3000,difficulty=5),
        [dict(key='p1',timeMs=0)], raw, [], {1:'A'}, players, opts)
    assert result['enabled'] and not result['checksEnabled'] and result['actualOnly']
    assert not result['checks'] and not result['plan'] and not result['phaseControl']
    assert result['displayTimelines'][0]['casts'] == [500]
    assert result['displayTimelines'][0]['plannedWindows'] == []
    opts['playerTimelineEnabled'] = False
    assert not boss.analyze_guild_timeline({}, [], raw, [], {}, players, opts)['enabled']


def test_warning_uses_real_cast_target_not_all_soakers_and_ends_after_final_hit():
    raw = {'casts':[
        dict(timestamp=1000,type='begincast',abilityGameID=1283489,sourceID=90,targetID=-1),
        dict(timestamp=4500,type='cast',abilityGameID=1283489,sourceID=90,targetID=1)],
        'debuffs':[dict(timestamp=6000,type='applydebuff',abilityGameID=1307425,targetID=2)],
        'damage':[dict(timestamp=t,type='damage',abilityGameID=1283594,targetID=pid)
                  for t,pid in ((6000,1),(6004,2))]}
    rows = boss._guillotine_telegraphs({'startTime':0,'endTime':10000},raw,{1:{},2:{}})
    assert len(rows) == 1 and rows[0]['playerID'] == 1
    assert rows[0]['radiusYards'] == 6
    assert (rows[0]['startTimeMs'], rows[0]['endTimeMs']) == (1000,6004)
    assert rows[0]['completed']


def test_binary_position_queries_preserve_nearest_ties_and_interpolation():
    rows = [dict(timestamp=t,x=x,y=0) for t,x in ((0,0),(100,10),(100,11),(200,20))]
    index = {1:rows}
    assert position_at(index,1,150)['x'] == 10
    assert position_at(index,1,100)['x'] == 10
    assert position_at_interpolated(index,1,150)['x'] == 15.5
    assert position_at_interpolated(index,1,-10)['reliable']
    assert not position_at(index,1,10000)['reliable']


def test_indexed_bomb_positions_preserve_unsorted_duplicates_gaps_and_ties():
    import random
    rng = random.Random(77)
    for _ in range(20):
        rows = [dict(timestamp=rng.randrange(0, 100)*100, x=i, y=-i) for i in range(40)]
        indexed = boss._IndexedPositionRows(rows)
        for ts in range(-500, 11000, 137):
            for window in (0, 100, 750):
                assert boss._timeline_point_near(indexed, ts, window) == boss._timeline_point_near(rows, ts, window)
            for age in (None, 0, 500):
                assert boss._timeline_point_at(indexed, ts, age) == boss._timeline_point_at(rows, ts, age)


def test_bomb_hit_snapshot_does_not_mutate_cached_actor_positions():
    import copy
    index = boss._MechanicPositionIndex({1:[dict(timestamp=1000,x=0,y=0)]})
    before = copy.deepcopy(index)
    rows = boss._index_rows_for_actor(index, 1)
    point, rule = boss._gloombomb_target_position(dict(timestamp=1500,type='damage',
        targetID=1,resourceActor=2,x=50,y=60),index,1)
    assert rule == 'damage-hit' and (point['x'],point['y']) == (50,60)
    assert index == before and len(rows) == 1
    assert boss._index_rows_for_actor(index,1) is rows


def test_replay_keeps_orbs_and_frontals_when_all_detailed_reviews_are_off():
    options = resolve_analysis_options(boss.CONFIG_SCHEMA, {})
    options.update({row['key']: False for row in boss.CONFIG_SCHEMA if row['type'] == 'boolean'})
    options['fieldReplayEnabled'] = True
    options['guillotineTelegraphEnabled'] = True
    sid = next(iter(boss.SEVER_IDS))
    casts = [dict(timestamp=100,type='cast',abilityGameID=boss.TOXIC_DELUGE,sourceID=9),
             dict(timestamp=200,type='cast',abilityGameID=boss.COALESCED_VENOM_CAST,sourceID=10,
                  sourceInstance=1,sourceResources={'x':1000,'y':0}),
             dict(timestamp=2000,type='begincast',abilityGameID=sid,sourceID=9,targetID=1),
             dict(timestamp=3000,type='cast',abilityGameID=sid,sourceID=9,targetID=1,
                  sourceResources={'x':0,'y':0,'facing':0}),
             dict(timestamp=4000,type='begincast',abilityGameID=1283489,sourceID=9,targetID=1),
             dict(timestamp=7500,type='cast',abilityGameID=1283489,sourceID=9,targetID=1),
             dict(timestamp=11000,type='begincast',abilityGameID=1299267,sourceID=9,targetID=1),
             dict(timestamp=11000,type='cast',abilityGameID=1299266,sourceID=9,targetID=-1),
             dict(timestamp=14500,type='cast',abilityGameID=1299267,sourceID=9,targetID=1)]
    raw = {key:[] for key in ('damage','enemyDeaths','deaths','enemyBuffs','debuffs','friendlyCasts')}
    raw.update(casts=casts,combatants=[dict(sourceID=1,specID=62)],analysisOptions=options,
               resources=[dict(timestamp=2000,type='resourcechange',sourceID=1,resourceActor=1,x=2000,y=0)])
    raw['damage'] = [dict(timestamp=t,type='damage',abilityGameID=spell,sourceID=9,targetID=1,
                         resourceActor=2,x=2000,y=0) for t,spell in
                     ((8500,boss.GUILLOTINE_DAMAGE_ID),(15500,1299296))]
    actors = [dict(id=1,name='A',type='Player'),dict(id=9,name="Zul'jan",gameID=257911,type='NPC')]
    fight = dict(startTime=0,endTime=20000,difficulty=4)
    result = boss.analyze_fight(fight,{1:'A',9:"Zul'jan"},{1:'Player',9:'NPC'},actors,raw)
    for key in ('toxicDeluge','sever','blightedSever','soulSever','manifestations','gloombomb','guillotine','grimGuillotine'):
        assert result[key] == {}
    visual = result['replayMechanics']
    assert visual['toxicDeluge']['groundPuddles'][0]['position']['x'] == 1000
    assert len(visual['cones']) == 1
    assert visual['cones'][0]['origin'] is not None
    assert visual['cones'][0]['facingRadians'] is not None
    assert 'unclearedCount' not in visual['cones'][0]
    assert len(visual['runouts']) == 2
    assert all(r['dangerRadiusYards'] == 40 and r['shareCentroid'] for r in visual['runouts'])
    assert len(result['guillotineTelegraphs']) == 2
    assert result['guillotineTelegraphs'][0]['endTimeMs'] == 8500
    assert result['guillotineTelegraphs'][1]['endTimeMs'] == 15500
    assert result['fieldAudit']['diagrams'] == []
    options['fieldReplayEnabled'] = False
    result = boss.analyze_fight(fight,{1:'A',9:"Zul'jan"},{1:'Player',9:'NPC'},actors,raw)
    assert result['replayMechanics'] == {} and result['fieldAudit'] == {}
