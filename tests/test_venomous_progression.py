from boss_plugins.venomous_abyss.progression import analyze_sszorak, analyze_twinfangs, analyze_vashnik
from boss_plugins.venomous_abyss.shared import build_survival_timeline, difficulty_fields, build_position_index


def player(player_id, name="测试玩家"):
    return {"id": player_id, "name": name, "classColor": "#fff", "role": "dps", "icon": None}


def event(timestamp, spell_id, kind, **extra):
    return {"timestamp": timestamp, "abilityGameID": spell_id, "type": kind, **extra}


def test_difficulty_fields_keep_numeric_and_localized_values():
    assert difficulty_fields({"difficulty": 3}) == {
        "difficulty": 3, "difficultyKey": "normal", "difficultyName": "普通"
    }
    assert difficulty_fields({"difficulty": 4})["difficultyKey"] == "heroic"
    assert difficulty_fields({"difficulty": 5})["difficultyName"] == "史诗"


def test_survival_timeline_merges_death_and_combat_res_in_time_order():
    fight = {"startTime": 1000, "endTime": 20_000}
    players = {1: player(1, "甲"), 2: player(2, "乙")}
    deaths = [{"timestamp": 5000, "targetID": 1, "killingAbilityGameID": 99}]
    casts = [event(7000, 20484, "cast", sourceID=2, targetID=1)]
    result = build_survival_timeline(fight, {1: "甲", 2: "乙"}, players, deaths, casts, {99: "测试伤害"})
    assert [row["kind"] for row in result["timeline"]] == ["death", "combat_res"]
    assert result["timeline"][0]["ability"] == "测试伤害"
    assert result["combatResCount"] == 1
    assert result["survivorCount"] == 2


def test_vashnik_infection_groups_by_cast_windows():
    fight = {"startTime": 0, "endTime": 60_000}
    players = {1: player(1, "甲"), 2: player(2, "乙")}
    raw = {
        "damage": [], "deaths": [],
        "casts": [
            event(10_000, 1282114, "cast"),
            event(30_000, 1282114, "cast"),
        ],
        "debuffs": [
            event(10_500, 1295173, "applydebuff", targetID=1),
            event(30_500, 1294994, "applydebuff", targetID=2),
        ],
    }
    result = analyze_vashnik(fight, {1: "甲", 2: "乙"}, players, raw)
    assert len(result["adaptiveInfection"]["rounds"]) == 2
    assert result["adaptiveInfection"]["rounds"][0]["soakerCount"] == 0


def test_twinfangs_tracks_stack_changes_and_explosion_nonparticipants():
    fight = {"startTime": 0, "endTime": 50_000}
    players = {1: player(1, "甲"), 2: player(2, "乙")}
    raw = {
        "debuffs": [
            event(1000, 1290336, "applydebuff", targetID=1, sourceID=50, stack=1),
            event(2000, 1290336, "applydebuffstack", targetID=1, sourceID=50, stack=2),
            event(3000, 1290336, "removedebuffstack", targetID=1, sourceID=50, stack=1),
        ],
        "casts": [
            event(5000, 1289192, "cast", targetID=0),
            event(20_000, 1291404, "begincast", targetID=0),
        ],
        "damage": [
            event(6000, 1289201, "damage", targetID=1, amount=10),
            event(10_000, 1290338, "damage", targetID=1, amount=100),
        ],
        "friendlyBuffs": [], "deaths": [],
    }
    result = analyze_twinfangs(fight, {1: "甲", 2: "乙", 50: "Boss"}, players, raw)
    history = result["eternalVenom"]["players"][0]
    assert history["peakStack"] == 2
    assert history["removedCount"] == 1
    round_row = result["globules"]["rounds"][0]
    assert round_row["exploded"] is True
    assert [row["playerID"] for row in round_row["nonParticipants"]] == [2]


def test_sszorak_tracks_cyst_placement_consumption_and_crosswind_wave():
    fight = {"startTime": 0, "endTime": 200_000}
    players = {1: player(1, "甲"), 2: player(2, "乙"), 3: player(3, "丙")}
    raw = {
        "casts": [
            event(20_000, 1286033, "cast"),
        ],
        "damage": [
            {"timestamp": 5000, "sourceID": 1, "targetID": 50, "x": 0, "y": 0},
            {"timestamp": 6000, "sourceID": 2, "targetID": 50, "x": 5000, "y": 0},
            {"timestamp": 7000, "sourceID": 3, "targetID": 50, "x": -5000, "y": 0},
        ],
        "debuffs": [
            event(5000, 1305963, "applydebuff", targetID=1, x=0, y=5000),
            event(6000, 1305963, "applydebuff", targetID=2, x=5000, y=5000),
            event(7000, 1305963, "applydebuff", targetID=3, x=-5000, y=5000),
            event(8000, 1305963, "removedebuff", targetID=1),
            event(8000, 1287205, "applydebuff", targetID=1),
            event(10_000, 1285425, "applydebuff", targetID=1, x=0, y=1000),
            event(10_000, 1285425, "applydebuff", targetID=2, x=500, y=1000),
            event(17_000, 1285425, "removedebuff", targetID=1),
            event(17_000, 1285425, "removedebuff", targetID=2),
        ],
        "resources": [],
        "deaths": [],
        "bossID": 50,
        "bossPositionEvents": [{"timestamp": 1000, "sourceID": 50, "targetID": 50, "x": 0, "y": 0}],
    }
    result = analyze_sszorak(fight, {1: "甲", 2: "乙", 3: "丙", 50: "Boss"}, players, raw)
    placements = result["cysts"]["placements"]
    assert len(placements) == 3
    assert placements[0]["consumedAtMs"] == 8000
    assert placements[0]["active"] is False
    assert result["fieldReplay"]["arena"]["method"] == "boss-center-p96"
    assert len(result["crosswinds"]["waves"]) == 1
    assert result["crosswinds"]["waves"][0]["targetCount"] == 2
    assert result["fieldReplay"]["frameStepMs"] == 200
