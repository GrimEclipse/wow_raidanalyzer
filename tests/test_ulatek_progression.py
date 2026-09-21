import pytest
from boss_plugins.venomous_abyss import ulatek as u


def event(t, kind, spell):
    return {'timestamp': t, 'type': kind, 'abilityGameID': spell, 'targetID': 99, 'sourceID': 99}


@pytest.mark.parametrize('end,expected', [(15, 'P1'), (20, 'P1'), (25, 'P2'), (35, 'P2'), (42, 'P2.5'), (60, 'P2.5'), (400, 'P3')])
def test_wipe_phase_tracks_completed_rage_and_p25_including_open_windows(end, expected):
    events = [event(10,'applybuff',u.RAGE_ID), event(20,'removebuff',u.RAGE_ID),
              event(30,'applybuff',u.RAGE_ID), event(40,'removebuff',u.RAGE_ID)]
    events += [event(t, 'cast', u.P25_COIL_CAST_ID) for t in range(50,56)]
    raw = {'trackedActorEvents': [e for e in events if e['timestamp'] <= end]}
    assert u._progression_phase({'endTime':end}, raw)['wipePhase'] == expected


def test_p3_spell_proves_transition_when_a_coil_cast_is_missing():
    raw = {'enemyBuffs': [event(10,'applybuff',u.RAGE_ID), event(20,'removebuff',u.RAGE_ID),
                          event(30,'applybuff',u.RAGE_ID), event(40,'removebuff',u.RAGE_ID)],
           'casts':[event(100, 'begincast', 1315341)]}
    assert u._progression_phase({'endTime':110}, raw)['wipePhase'] == 'P3'


def test_overview_uses_full_fight_phase_instead_of_nightly_exemption_snapshot():
    pull = {'ulatek': {'progression': u._progression_fields('P3'),
                       'nightlyReview': {'progression': u._progression_fields('P1')}}}
    u.restore_progression(pull)
    assert pull['wipePhase'] == 'P3'
    pull['isKill'] = True
    u.restore_progression(pull)
    assert pull['fightPhase'] == 'P3'
    assert pull['wipePhase'] == '击杀'
