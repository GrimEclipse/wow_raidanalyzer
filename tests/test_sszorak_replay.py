from boss_plugins.venomous_abyss import sszorak as s


def aura(t, kind, sid, pid=1):
    return {'timestamp':t, 'type':kind, 'abilityGameID':sid, 'targetID':pid}


def test_cross_refresh_survives_original_expiry_and_new_player_propagation():
    raw = {'debuffs':[
        aura(1000, 'applydebuff', 1297707),
        aura(2000, 'applydebuff', 1299899),
        aura(5500, 'refreshdebuff', 1297707),
        aura(6000, 'applydebuff', 1297707, 2),
        aura(7000, 'removedebuff', 1299899),
        aura(10500, 'removedebuff', 1297707),
        aura(11000, 'removedebuff', 1297707, 2)]}
    rows = s._replay_virulence({'startTime':0, 'endTime':12000}, raw)
    assert len(rows) == 3
    assert rows[0]['endTimeMs'] == 10500
    assert rows[0]['refreshTimesMs'] == [5500]
    assert rows[1]['endTimeMs'] == 7000
    assert rows[2]['playerID'] == 2 and rows[2]['startTimeMs'] == 6000


def test_cross_death_clears_both_aura_types_and_allows_reapplication():
    raw = {'debuffs':[
        aura(1000, 'applydebuff', 1297707), aura(1500, 'applydebuff', 1299899),
        aura(2200, 'removedebuff', 1297707), aura(4000, 'applydebuff', 1297707)],
        'deaths':[aura(2000, 'death', 0)]}
    rows = s._replay_virulence({'startTime':0, 'endTime':6000}, raw)
    assert [r['endTimeMs'] for r in rows] == [2000, 2000, 6000]
    assert [r['endEvidence'] for r in rows] == ['death', 'death', 'fight-end']


def test_predator_cone_aims_at_tank_even_when_dps_takes_more_damage():
    raw = {'bossID':9, 'casts':[
        {'timestamp':1000, 'type':'begincast', 'abilityGameID':1277027, 'sourceID':9},
        {'timestamp':4000, 'type':'cast', 'abilityGameID':1277027, 'sourceID':9}],
        'damage':[
        {'timestamp':4010, 'type':'damage', 'abilityGameID':1285999, 'sourceID':9, 'targetID':2, 'amount':1000},
        {'timestamp':4020, 'type':'damage', 'abilityGameID':1285999, 'sourceID':9, 'targetID':1, 'amount':1}]}
    positions = {9:[{'timestamp':4000, 'x':0, 'y':0}],
                 1:[{'timestamp':4000, 'x':100, 'y':0}],
                 2:[{'timestamp':4000, 'x':-100, 'y':0}]}
    rows = s._replay_predator_cones({'startTime':0, 'endTime':6000},
                                  {1:{'role':'tank'}, 2:{'role':'melee-dps'}}, raw, positions)
    assert len(rows) == 1 and rows[0]['targetID'] == 1
    assert rows[0]['startTimeMs'] == 1000 and rows[0]['impactTimeMs'] == 4000
    assert rows[0]['targetPosition']['x'] == 100
    positions[9][0]['timestamp'] = 0
    assert not s._replay_predator_cones({'startTime':0, 'endTime':6000},
                                      {1:{'role':'tank'}}, raw, positions)
