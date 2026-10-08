import pytest

from boss_plugins.venomous_abyss.vashnik import ARENA_PROFILE, build_totem_replay


def test_field_projection_preserves_perpendicular_axes_and_equal_scale():
    a, b, c, d = ARENA_PROFILE['matrix']
    assert a*b+c*d == pytest.approx(0, abs=1e-12)
    assert a*a+c*c == pytest.approx(b*b+d*d)


def test_totem_instances_have_independent_lifetimes_and_coordinate_evidence():
    scene = {'events': [], 'pillarRounds': [{'timeMs': 5000, 'applicationTimeMs': 1000}]}
    raw = {'trackedActorGameIDByActorID': {405: 269430, 407: 269430},
           'trackedActorEvents': [
               {'timestamp': 1100, 'type': 'summon', 'targetID': 405, 'targetInstance': 1},
               {'timestamp': 1200, 'type': 'summon', 'targetID': 405, 'targetInstance': 2},
               {'timestamp': 1300, 'type': 'summon', 'targetID': 407, 'targetInstance': 1},
               {'timestamp': 2000, 'type': 'begincast', 'sourceID': 405, 'sourceInstance': 1, 'abilityGameID': 1304459},
               {'timestamp': 2000, 'type': 'begincast', 'sourceID': 405, 'sourceInstance': 2, 'abilityGameID': 1304459},
               {'timestamp': 6000, 'type': 'death', 'targetID': 405, 'targetInstance': 1},
               {'timestamp': 10000, 'type': 'cast', 'sourceID': 405, 'sourceInstance': 2, 'abilityGameID': 1304459,
                'resourceActor': 1, 'x': 30000, 'y': 42000},
           ]}
    build_totem_replay(scene, {'startTime': 0, 'endTime': 20000}, raw)
    units = {u['key']: u for u in scene['totemReplay']['units']}
    assert units['405:1']['deathTimeMs'] == 6000
    assert units['405:2']['deathTimeMs'] is None
    assert units['407:1']['deathTimeMs'] is None
    assert units['405:1']['positions'] == []
    assert units['405:2']['positions'][0]['x'] == 30000
    assert units['407:1']['positions'] == []
    assert units['405:2']['castCompletions'] == [10000]
    assert scene['pillarRounds'][0]['totemResult']['clearedKeys'] == ['405:1']
    assert scene['pillarRounds'][0]['totemResult']['remainingKeys'] == ['405:2', '407:1']


def test_missing_death_does_not_imply_cleared_and_later_spawns_are_not_wave_survivors():
    scene = {'events': [], 'pillarRounds': [{'timeMs': 5000, 'applicationTimeMs': 1000}]}
    raw = {'trackedActorGameIDByActorID': {'405': 269430}, 'trackedActorEvents': [
        {'timestamp': 1000, 'type': 'begincast', 'sourceID': 405, 'sourceInstance': 1, 'abilityGameID': 1304459},
        {'timestamp': 6000, 'type': 'summon', 'targetID': 405, 'targetInstance': 2},
    ]}
    build_totem_replay(scene, {'startTime': 0, 'endTime': 10000}, raw)
    assert scene['pillarRounds'][0]['totemResult']['remainingKeys'] == ['405:1']
    assert not scene['pillarRounds'][0]['totemResult']['clearedKeys']
    assert scene['totemReplay']['units'][0]['spawnTimeMs'] is None


def test_explosion_reviews_both_clearance_rounds_of_spawn_cycle_with_late_coordinate():
    scene = {'events': [], 'pillarRounds': [
        {'index': 1, 'timeMs': 4000, 'applicationTimeMs': 3000, 'imbibeTimeMs': 1000,
         'cycleIndex': 1, 'checked': True, 'players': [{'player': 'A'}]},
        {'index': 2, 'timeMs': 7000, 'applicationTimeMs': 6000, 'imbibeTimeMs': 1000,
         'cycleIndex': 1, 'checked': False, 'players': [{'player': 'B'}]},
        {'index': 3, 'timeMs': 11000, 'applicationTimeMs': 10000, 'imbibeTimeMs': 9000,
         'cycleIndex': 2, 'checked': True, 'players': [{'player': 'C'}]},
    ]}
    raw = {'trackedActorGameIDByActorID': {405: 269430}, 'trackedActorEvents': [
        {'timestamp': 2000, 'type': 'summon', 'targetID': 405, 'targetInstance': 1},
        {'timestamp': 12000, 'type': 'cast', 'sourceID': 405, 'sourceInstance': 1, 'abilityGameID': 1304459},
    ], 'replayEvents': [
        {'timestamp': 11500, 'sourceID': 1, 'targetID': 405, 'targetInstance': 1,
         'resourceActor': 2, 'x': 26181, 'y': 42429},
    ]}
    build_totem_replay(scene, {'startTime': 0, 'endTime': 20000}, raw)
    review = scene['totemReplay']['explosions'][0]
    assert review['waveRoundIndices'] == [1, 2]
    assert review['players'] == ['A', 'B']
    assert review['position']['x'] == 26181
    assert scene['pillarRounds'][1]['purpose'] == '补救清场'
    assert scene['pillarRounds'][1]['explosionReview']
    assert not scene['pillarRounds'][2]['explosionReview']


def test_batch_clearance_includes_early_waves_and_excludes_previous_cycle_units():
    scene = {'events': [], 'pillarRounds': [
        {'index': 1, 'timeMs': 7000, 'applicationTimeMs': 3000, 'imbibeTimeMs': 1000,
         'cycleIndex': 1, 'checked': True, 'players': [{'player': 'A', 'timeMs': 4000}, {'player': 'B', 'timeMs': 7000}]},
    ]}
    raw = {'trackedActorGameIDByActorID': {405: 269430}, 'trackedActorEvents': [
        {'timestamp': 500, 'type': 'summon', 'targetID': 405, 'targetInstance': 1},
        {'timestamp': 2000, 'type': 'summon', 'targetID': 405, 'targetInstance': 2},
        {'timestamp': 2100, 'type': 'summon', 'targetID': 405, 'targetInstance': 3},
        {'timestamp': 4500, 'type': 'death', 'targetID': 405, 'targetInstance': 2},
    ]}
    build_totem_replay(scene, {'startTime': 0, 'endTime': 20000}, raw)
    result = scene['pillarRounds'][0]['totemResult']
    assert result['beforeKeys'] == ['405:2', '405:3']
    assert result['clearedKeys'] == ['405:2']
    assert result['remainingKeys'] == ['405:3']
