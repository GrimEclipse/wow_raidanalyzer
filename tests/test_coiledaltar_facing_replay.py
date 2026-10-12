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
        dict(id=99,name="Zul'jan",gameID=270093),dict(id=9,name="Zul'jan",gameID=257911)])
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
             for t,spell in [(0,1282487),(100000,1298381),(200000,1298381),
                             (300000,1298381),(400000,1298381)]]
    mechanics = {'combatReplay':{'bosses':[dict(actorID=9,casts=[])]}}
    scene = boss._build_altar_ground_replay({'startTime':0,'endTime':500000},mechanics,{'casts':casts})
    assert scene['rounds'][0]['kind'] == 'green'
    assert scene['rounds'][0]['channelEndTimeMs'] == 8000
    assert scene['rounds'][-1]['fullCoverage']
    assert [r['peakRadiusYards'] for r in scene['rounds'][1:]] == [50,60,70,80]
    assert scene['rounds'][0]['recedeStartTimeMs'] == 23000
    assert scene['rounds'][0]['endTimeMs'] == 47000
    assert scene['rounds'][1]['endTimeMs'] == 147000
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
