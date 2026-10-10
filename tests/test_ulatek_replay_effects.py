import pytest
from boss_plugins.venomous_abyss import ulatek as u
from boss_plugins.venomous_abyss import sszorak as s


def event(t, kind, sid, **kw):
    return {'timestamp': t, 'type': kind, 'abilityGameID': sid, 'sourceID': 9, 'targetID': 9, **kw}


def test_wrath_fixed_circle_nine_observed_ticks_and_fury_channel():
    raw = {'bossID': 9, 'casts': [event(1000, 'begincast', 1298367),
        event(6000, 'cast', 1298367, targetID=1, resourceActor=1, x=0, y=2000)],
        'damage': [event(6300+i*333, 'damage', 1298369, targetID=1,
                         resourceActor=2, x=0, y=500+i*10, amount=10) for i in range(9)],
        'enemyBuffs': [event(10000, 'applybuff', u.RAGE_ID), event(30000, 'removebuff', u.RAGE_ID)],
        'resources': [], 'debuffs': []}
    changes = []
    scene = u._replay_effects({'startTime': 0, 'endTime': 40000}, {1: {}}, raw, changes)
    circle = scene['circles'][0]
    assert (circle['position']['x'], circle['position']['y']) == (0, 500)
    assert len(circle['tickTimesMs']) == 9
    assert circle['radiusYards'] == 3
    assert circle['endTimeMs'] == 6300+8*333+150
    fury = next(c for c in scene['channels'] if c['spellID'] == u.RAGE_ID)
    assert fury['endTimeMs']-fury['startTimeMs'] == 20000


@pytest.mark.parametrize('difficulty,count', [(4, 6), (5, 8)])
def test_first_floor_waits_for_all_soaks_and_five_second_fall(difficulty, count):
    raw = {'bossID': 9, 'casts': [event(50000+i*3000, 'cast', u.P25_COIL_CAST_ID) for i in range(count)],
        'enemyBuffs': [event(1000, 'applybuff', u.RAGE_ID), event(21000, 'removebuff', u.RAGE_ID),
                       event(25000, 'applybuff', u.RAGE_ID), event(45000, 'removebuff', u.RAGE_ID)],
        'debuffs': [], 'resources': [], 'damage': []}
    changes = []
    u._replay_effects({'startTime': 0, 'endTime': 90000, 'difficulty': difficulty}, {}, raw, changes)
    assert next(c['timeMs'] for c in changes if c['kind'] == 'shatter') == 50000+(count-1)*3000+5000
    raw['casts'].pop()
    changes = []
    u._replay_effects({'startTime': 0, 'endTime': 90000, 'difficulty': difficulty}, {}, raw, changes)
    assert not any(c['kind'] == 'shatter' for c in changes)


def test_sszorak_mark_refresh_does_not_duplicate_and_removal_ends_ring():
    raw = {'debuffs': [event(1000, 'applydebuff', s.SERPENTS_FURY_MARK_ID, targetID=1),
                      event(2000, 'refreshdebuff', s.SERPENTS_FURY_MARK_ID, targetID=1),
                      event(4000, 'removedebuff', s.SERPENTS_FURY_MARK_ID, targetID=1)]}
    assert s._replay_marks({'startTime': 0, 'endTime': 5000}, raw) == [
        {'playerID': 1, 'startTimeMs': 1000, 'endTimeMs': 4000, 'radiusYards': 8}]


def test_corridor_cast_ends_on_interrupt_for_the_matching_instance():
    raw = {'enemyBuffs': [], 'casts': [event(1000, 'begincast', 1290779, sourceInstance=1),
                     event(1100, 'begincast', 1290779, sourceInstance=2)],
           'interrupts': [{'timestamp': 1500, 'targetID': 9, 'targetInstance': 1,
                           'extraAbilityGameID': 1290779},
                          {'timestamp': 1700, 'targetID': 9, 'targetInstance': 2,
                           'extraAbilityGameID': 1290779}]}
    scene = u._replay_effects({'startTime': 0, 'endTime': 2000}, {}, raw, [])
    assert [(c['instance'], c['endTimeMs'], c['outcome']) for c in scene['npcCasts']] == [
        (1, 1500, 'interrupted'), (2, 1700, 'interrupted')]


def test_floor_removes_boss_old_corner_not_escaping_raid_or_later_boss_position():
    raw = {'enemyBuffs': [], 'casts': [event(2000, 'begincast', 1315341), event(10000, 'cast', 1315341)],
           'resources': [event(1900, 'resourcechange', 0, resourceActor=1, x=3500, y=158500),
                         event(2001, 'resourcechange', 0, resourceActor=1, x=-3500, y=152000),
                         event(1900, 'resourcechange', 0, sourceID=1, resourceActor=1, x=-3500, y=152000)]}
    scene = u._replay_effects({'startTime': 0, 'endTime': 11000}, {1: {}}, raw, [])
    assert scene['lostPlatforms'][0]['position'] == {'x': 3500, 'y': 158500}
    assert 'waves' not in scene


def test_shrieker_interrupt_records_player_spell_and_matching_instance():
    raw={'actorRows':[{'id':43,'gameID':u.BLIGHTSCALE_SHRIEKER_GAME_ID}],
         'casts':[event(1000,'begincast',1310764,sourceID=43,sourceInstance=1),
                  event(1000,'begincast',1310764,sourceID=43,sourceInstance=2)],
         'interrupts':[event(1800,'interrupt',6552,sourceID=1,targetID=43,
                              targetInstance=2,extraAbilityGameID=1310764)],
         'enemyBuffs':[]}
    scene=u._replay_effects({'startTime':0,'endTime':5000},{1:{}},raw,[])
    cast=scene['npcCasts'][0]
    assert cast['instance']==2 and cast['outcome']=='interrupted'
    assert (cast['interruptPlayerID'],cast['interruptSpellID'],cast['endTimeMs'])==(1,6552,1800)
    assert cast['interruptIcon']=='/assets/spells/6552.png'


def test_coil_corner_selects_fixed_region_and_preserves_observed_sequence():
    raw={'actorRows':[{'id':43,'gameID':u.SPECTRAL_COIL_GAME_ID}],
         'casts':[event(1000,'begincast',u.P25_COIL_CAST_ID,sourceID=43,sourceInstance=1),
                  event(5000,'cast',u.P25_COIL_CAST_ID,sourceID=43,sourceInstance=1,
                        resourceActor=1,x=4443,y=153603),
                  event(6000,'begincast',u.P25_COIL_CAST_ID,sourceID=43,sourceInstance=2),
                  event(10000,'cast',u.P25_COIL_CAST_ID,sourceID=43,sourceInstance=2,
                        resourceActor=1,x=4370,y=157293)]}
    circles=u._replay_coil_soaks({'startTime':0},raw)
    assert [c['regionIndex'] for c in circles]==[7,0]
    assert [c['startTimeMs'] for c in circles]==[1000,6000]
    assert all(c['radiusYards']==10 for c in circles)
    raw['casts'][1].update(x=4500,y=153700)
    raw['resources']=[event(5000,'damage',0,sourceID=1,resourceActor=1,x=-2000,y=154000)]
    assert u._replay_coil_soaks({'startTime':0},raw)[0]['position']==circles[0]['position']
    raw['casts'][1]['resourceActor']=2
    assert len(u._replay_coil_soaks({'startTime':0},raw))==1


def test_fullscreen_impact_requires_raid_damage_and_not_nine_tank_hits():
    raw = {'damage': [event(1000+i*333, 'damage', 1298369, targetID=1, amount=10) for i in range(9)]}
    fight = {'startTime': 0}
    players = {1: {}, 2: {}, 3: {}}
    assert u._replay_raid_impacts(fight, players, raw) == []
    raw['damage'] += [event(5000, 'damage', 1298369, targetID=i, amount=10) for i in players]
    raw['damage'] += [event(6000, 'damage', u.RATTLER_SLAM_ID, targetID=i, amount=10) for i in players]
    assert [(x['kind'], x['affectedCount']) for x in u._replay_raid_impacts(fight, players, raw)] == [('wrath', 3), ('slam', 3)]


def test_mythic_egg_shell_pickup_and_consumption_use_instance_coordinates():
    fight = {'startTime': 0, 'endTime': 10000}
    rows = [event(1000, 'cast', u.HARDENED_SHELL_ID, sourceID=62, sourceInstance=1,
                  resourceActor=1, x=100, y=200, absorb=100),
            event(2000, 'damage', 1, sourceID=1, targetID=62, targetInstance=1,
                  resourceActor=2, x=100, y=200, absorb=0, amount=10, overkill=500, hitPoints=1),
            event(2000, 'removebuff', u.HARDENED_SHELL_ID, targetID=62, targetInstance=1),
            event(1000, 'applybuff', u.HARDENED_SHELL_ID, targetID=61, targetInstance=1)]
    carry = {'kind': 'egg', 'playerID': 1, 'startTimeMs': 2500, 'endTimeMs': 5000}
    raw = {'actorRows': [{'id': 61, 'gameID': 265644}, {'id': 62, 'gameID': 265644}],
           'replayEvents': rows, 'resources': [event(2500, 'resourcechange', 0, sourceID=1, resourceActor=1, x=101, y=201),
                                             event(5000, 'resourcechange', 0, sourceID=1, resourceActor=1, x=900, y=800)],
           'debuffs': [event(5000, 'applydebuff', 1312150, targetID=1)]}
    eggs = u._replay_eggs(fight, {1: {}}, raw, [carry], [9000])
    assert len(eggs) == 1
    assert eggs[0]['shieldBreakTimeMs'] == 2000
    assert eggs[0]['carries'][0]['outcome'] == 'consumed'
    assert eggs[0]['carries'][0]['releasePosition'] == {'x': 900, 'y': 800}
    assert eggs[0]['endTimeMs'] == 5000
    assert carry['eggKey'] == 'egg:62:1'
    assert eggs[0]['interactions'][0]['playerID'] == 1
    assert eggs[0]['deathTimeMs'] is None  # Shell overkill is not egg death.


def test_p3_mark_radii_and_purge_triads_do_not_depend_on_guide_timers():
    raw = {'debuffs': [event(1000, 'applydebuff', 1288879, targetID=1),
                      event(2000, 'applydebuff', 1312967, targetID=2)], 'casts': [], 'enemyBuffs': []}
    scene = u._replay_feedback({'startTime': 0, 'endTime': 3000, 'difficulty': 5}, {1: {}, 2: {}}, raw)
    assert [(a['kind'], a['radiusYards']) for a in scene['auras']] == [('bite', 7), ('purge', 3)]
    import math
    directions = scene['purgeDirections']
    assert len(directions) == 3
    for i, a in enumerate(directions):
        b = directions[(i+1)%3]
        assert math.hypot(a['x'], a['y']) == pytest.approx(1)
        assert a['x']*b['x']+a['y']*b['y'] == pytest.approx(-.5)


def test_pickup_can_use_real_post_teleport_sample_and_still_reject_ambiguity():
    fight = {'startTime': 0, 'endTime': 5000}
    raw = {'actorRows': [{'id': 62, 'gameID': 265644}],
           'replayEvents': [event(1000, 'cast', u.HARDENED_SHELL_ID, sourceID=62, sourceInstance=1,
                                 resourceActor=1, x=0, y=0, absorb=0)],
           'resources': [event(2000, 'resourcechange', 0, sourceID=1, resourceActor=1, x=2000, y=0),
                         event(2300, 'resourcechange', 0, sourceID=1, resourceActor=1, x=100, y=0)]}
    carry = {'kind': 'egg', 'playerID': 1, 'startTimeMs': 2010, 'endTimeMs': 4000}
    eggs = u._replay_eggs(fight, {1: {}}, raw, [carry], [5000])
    assert carry['eggKey'] == eggs[0]['key']
    raw['replayEvents'].append(event(1000, 'cast', u.HARDENED_SHELL_ID, sourceID=62, sourceInstance=2,
                                    resourceActor=1, x=0, y=0, absorb=0))
    carry.pop('eggKey')
    eggs = u._replay_eggs(fight, {1: {}}, raw, [carry], [5000])
    assert 'eggKey' not in carry
    assert not any(e['carries'] for e in eggs)


def test_mythic_purge_countdown_starts_on_post_bite_mark_and_crosses_aura_transition():
    raw = {'debuffs': [event(1000, 'applydebuff', 1312967, targetID=1),
                      event(6000, 'removedebuff', 1312967, targetID=1),
                      event(6010, 'applydebuff', 1316356, targetID=1),
                      event(24010, 'removedebuff', 1316356, targetID=1)],
           'casts': [], 'enemyBuffs': []}
    scene = u._replay_feedback({'startTime': 0, 'endTime': 30000, 'difficulty': 5}, {1: {}}, raw)
    first, second = scene['auras']
    assert first['radiusYards'] == 3
    assert first['warningStartTimeMs'] == 1000
    assert first['warningEndTimeMs'] == 7000
    assert second['endTimeMs'] == 24010  # Keep actual aura lifetime for attribution.
    assert second['warningStartTimeMs'] == 6010
    assert second['warningEndTimeMs'] == 6010
    assert second['radiusYards'] is None


def test_fester_bubble_and_head_cast_are_instance_local_and_end_at_completion():
    raw = {'casts': [event(1000,'begincast',u.FESTER_BURST_ID,sourceInstance=3),
                     event(5000,'cast',u.FESTER_BURST_ID,sourceInstance=3,
                           resourceActor=1,x=2000,y=157000)], 'enemyBuffs': []}
    scene = u._replay_effects({'startTime':0,'endTime':6000},{},raw,[])
    bubble = scene['circles'][0]
    assert (bubble['kind'],bubble['radiusYards'],bubble['sourceInstance']) == ('fester-safe',10,3)
    assert (bubble['startTimeMs'],bubble['endTimeMs']) == (1000,5000)
    assert scene['npcCasts'][0]['spellID'] == u.FESTER_BURST_ID


def test_purge_launches_once_at_six_seconds_not_on_second_aura_apply():
    raw = {'debuffs':[event(1000,'applydebuff',1312967,targetID=1),
                     event(6000,'removedebuff',1312967,targetID=1),
                     event(6010,'applydebuff',1316356,targetID=1),
                     event(24010,'removedebuff',1316356,targetID=1)],
           'resources':[event(7000,'resourcechange',0,sourceID=1,resourceActor=1,x=100,y=200)],
           'casts':[],'enemyBuffs':[]}
    scene = u._replay_feedback({'startTime':0,'endTime':30000,'difficulty':5},{1:{}},raw)
    assert len(scene['waves']) == 1
    wave = scene['waves'][0]
    assert (wave['timeMs'],wave['position']['x'],wave['widthYards']) == (7000,100,3)
    assert len(wave['directions']) == 3
    raw['debuffs'] = raw['debuffs'][:2]
    scene = u._replay_feedback({'startTime':0,'endTime':30000,'difficulty':5},{1:{}},raw)
    assert not scene['waves']


def incubation_raw():
    return {'actorRows':[{'id':43,'gameID':263942}],
            'casts':[event(1000,'cast',1299759,resourceActor=1,x=0,y=0)],
            'damage':[event(t,'damage',1299919,targetID=1,
                            resourceActor=2,x=x,y=y,**extra)
                      for t,x,y,extra in [(1001,500,500,{'facing':0}),
                                          (2001,600,400,{'facing':157}),
                                          (3001,500,500,{})]],
            'replayEvents':[event(1000,'damage',0,sourceID=43,sourceInstance=2,
                                  resourceActor=1,x=1000,y=1000)]}


def test_incubation_axis_connects_wretch_and_does_not_depend_on_tank_facing():
    scene = u._replay_projectiles({'startTime':0},{1:{'role':'tank'}},incubation_raw(),[])
    tether = scene['tankTethers'][0]
    assert (tether['targetID'],tether['targetInstance']) == (43,2)
    assert tether['tickTimesMs'] == [1001,2001,3001]
    assert len(scene['waves']) == 3
    assert (scene['waves'][1]['position']['x'],scene['waves'][1]['position']['y']) == (600,400)
    for wave in scene['waves']:
        a,b = wave['directions']
        assert a['x']+a['y'] == pytest.approx(0)  # Perpendicular to (1000,1000).
        assert a['x']**2+a['y']**2 == pytest.approx(1)
        assert b == {'x':-a['x'],'y':-a['y']}


def test_incubation_ignores_dead_instance_and_preserves_missing_target_ticks():
    raw = incubation_raw()
    raw['replayEvents'] += [event(900,'damage',0,sourceID=43,sourceInstance=1,
                                    resourceActor=1,x=1000,y=1000),
                            event(950,'death',0,targetID=43,targetInstance=1)]
    scene = u._replay_projectiles({'startTime':0},{1:{'role':'tank'}},raw,[])
    assert scene['tankTethers'][0]['targetInstance'] == 2
    raw['replayEvents'] = []
    scene = u._replay_projectiles({'startTime':0},{1:{'role':'tank'}},raw,[])
    assert scene['tankTethers'][0]['tickTimesMs'] == [1001,2001,3001]
    assert not scene['waves']


def test_incubation_degenerate_axis_never_invents_a_direction():
    raw = incubation_raw()
    raw['replayEvents'][0].update(x=0,y=0)
    scene = u._replay_projectiles({'startTime':0},{1:{'role':'tank'}},raw,[])
    assert not scene['waves']


def test_corridor_warden_health_uses_owned_resources_and_separates_instances():
    raw={'actorRows':[{'id':43,'gameID':264045}], 'replayEvents':[
        event(1000,'damage',0,sourceID=43,sourceInstance=1,resourceActor=1,
              x=-10000,y=155000,hitPoints=800,maxHitPoints=1000),
        event(1100,'damage',0,targetID=43,targetInstance=2,sourceID=1,
              resourceActor=1,hitPoints=123,maxHitPoints=500),
        event(1200,'damage',0,targetID=43,targetInstance=2,
              targetResources={'x':10000,'y':155000,'hitPoints':600,'maxHitPoints':1000}),
        event(1500,'death',0,targetID=43,targetInstance=1)]}
    rows=u._replay_warden_health({'startTime':100},raw)
    a,b=rows
    assert a['health']==[[900,800,1000]]
    assert b['health']==[[1100,600,1000]]  # Player health never becomes Warden health.
    assert a['position']['x']==-10000 and b['position']['x']==10000
    assert a['states']==[[1400,'dead']] and not b['states']


def test_camera_returns_when_raid_reaches_center_not_on_second_fury_cast():
    players = {pid: {} for pid in range(1, 5)}
    resources = [event(t, 'resourcechange', 0, sourceID=pid, resourceActor=1,
                       x=1000 if t >= 65000 or pid == 1 else 10000, y=155367)
                 for t in range(22000, 100000, 500) for pid in players]
    raw = {'casts': [event(95000, 'begincast', u.RAGE_ID)], 'resources': resources,
           'enemyBuffs': [event(1000, 'applybuff', u.RAGE_ID), event(21000, 'removebuff', u.RAGE_ID),
                          event(100000, 'applybuff', u.RAGE_ID), event(120000, 'removebuff', u.RAGE_ID)]}
    changes = []
    scene = u._replay_effects({'startTime': 0, 'endTime': 130000}, players, raw, changes)
    assert scene['phaseWindows'][0]['endTimeMs'] == 65000
    assert scene['phaseWindows'][0]['endEvidence'] == 'raid-position-return'
    assert next(e for e in changes if e['kind'] == 'return')['timeMs'] == 65000


def test_thrashing_cone_uses_matching_instance_tank_hit_and_ends_on_completion():
    raw = {'enemyBuffs': [], 'casts': [
        event(1000, 'begincast', u.DESPERATE_THRASH_ID, sourceInstance=2),
        event(4000, 'cast', u.DESPERATE_THRASH_ID, sourceInstance=2,
              resourceActor=1, x=0, y=155367)],
        'damage': [event(3980, 'damage', u.DESPERATE_THRASH_ID, sourceInstance=1,
                         targetID=1, resourceActor=2, x=-1000, y=155367),
                   event(3990, 'damage', u.DESPERATE_THRASH_ID, sourceInstance=2,
                         targetID=1, resourceActor=2, x=1000, y=155367)]}
    scene = u._replay_effects({'startTime': 0, 'endTime': 5000}, {1: {'role': 'tank'}}, raw, [])
    cone = scene['cones'][0]
    assert (cone['instance'], cone['angleDegrees'], cone['lengthYards']) == (2, 30, 30)
    assert cone['targetPosition']['x'] == 1000
    assert cone['directionEvidence'] == 'tank-hit'
    assert (cone['startTimeMs'], cone['endTimeMs']) == (1000, 4000)
