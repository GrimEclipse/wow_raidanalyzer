from analyzer_core.combat_replay import build_replay_tracks


def test_complete_positions_keep_non_mechanic_players_and_resource_ownership():
    players = {1: {"name": "A", "icon": "mage-arcane", "classColor": "#3FC7EB"},
               2: {"name": "B"}, 3: {"name": "No position"}}
    rows = [
        {"timestamp": 1100, "sourceID": 1, "targetID": 2, "resourceActor": 2, "x": 10, "y": 20},
        {"timestamp": 1200, "sourceID": 1, "resourceActor": 1, "x": 30, "y": 40},
        {"timestamp": 1200, "sourceID": 1, "resourceActor": 1, "x": 30, "y": 40},
        {"timestamp": 1300, "sourceID": 9, "sourceInstance": 1, "resourceActor": 1, "x": 50, "y": 60},
        {"timestamp": 1400, "sourceID": 9, "sourceInstance": 2, "resourceActor": 1, "x": 70, "y": 80},
        {"timestamp": 1800, "type": "death", "targetID": 9, "targetInstance": 1},
    ]
    result = build_replay_tracks({"startTime": 1000, "endTime": 2000}, players, {}, rows)
    units = {u["key"]: u for u in result["units"]}
    assert units["1:0"]["samples"] == [[200, 30, 40]]
    assert units["2:0"]["samples"] == [[100, 10, 20]]
    assert units["9:1"]["samples"] == [[300, 50, 60]]
    assert units["9:2"]["samples"] == [[400, 70, 80]]
    assert units["9:1"]["states"] == [[800, "dead"]]
    assert units["9:2"]["states"] == []
    assert units["1:0"]["icon"] == "/assets/specs/mage-arcane.jpg"
    assert result["positionedPlayers"] == 2
    assert result["missingPlayers"] == ["No position"]


def test_replay_death_and_resurrection_do_not_hide_other_players():
    events = [{"timestamp": 100, "sourceID": 1, "resourceActor": 1, "x": 0, "y": 0}]
    result = build_replay_tracks({"startTime": 0, "endTime": 3000}, {1: {"name": "A"}}, {}, events,
                                deaths=[{"timestamp": 1000, "targetID": 1}],
                                resurrections=[{"timestamp": 2000, "targetID": 1}])
    assert result["units"][0]["states"] == [[1000, "dead"], [2000, "alive"]]


def test_boss_health_uses_resource_owner_and_casts_ignore_other_npcs():
    rows = [
        {"timestamp": 100, "type": "damage", "sourceID": 1, "targetID": 9, "resourceActor": 2, "hitPoints": 800, "maxHitPoints": 1000},
        {"timestamp": 150, "type": "damage", "sourceID": 9, "targetID": 1, "resourceActor": 2, "hitPoints": 50, "maxHitPoints": 100},
        {"timestamp": 200, "type": "begincast", "sourceID": 9, "abilityGameID": 100},
        {"timestamp": 200, "type": "begincast", "sourceID": 9, "abilityGameID": 100},
        {"timestamp": 700, "type": "cast", "sourceID": 9, "abilityGameID": 100},
        {"timestamp": 300, "type": "begincast", "sourceID": 10, "abilityGameID": 100},
    ]
    result = build_replay_tracks({"startTime": 0, "endTime": 1000}, {1: {"name": "Player"}}, {9: "Boss"}, rows,
                                actor_rows=[{"id": 9, "subType": "Boss", "gameID": 123}, {"id": 10, "subType": "NPC"}], spell_names={100: "Cast"})
    assert len(result["bosses"]) == 1
    boss = result["bosses"][0]
    assert boss["health"] == [[100, 800, 1000]]
    assert boss["casts"] == [{"startTimeMs": 200, "endTimeMs": 700, "spellID": 100, "spellName": "Cast", "outcome": "completed"}]


def test_boss_energy_does_not_use_the_players_resource_snapshot():
    rows = [{'type': 'damage', 'timestamp': 100, 'sourceID': 1, 'targetID': 9,
             'resourceActor': 2, 'hitPoints': 800, 'maxHitPoints': 1000,
             'classResources': [{'type': 3, 'amount': 25, 'max': 100}]},
            {'type': 'damage', 'timestamp': 200, 'sourceID': 9, 'targetID': 1,
             'resourceActor': 2, 'classResources': [{'type': 3, 'amount': 90, 'max': 100}]}]
    replay = build_replay_tracks({'startTime': 0, 'endTime': 1000}, {1: {'name': 'P'}}, {9: 'B'}, rows,
                                actor_rows=[{'id': 9, 'subType': 'Boss'}])
    assert replay['bosses'][0]['energy'] == [[100, 25, 100]]
