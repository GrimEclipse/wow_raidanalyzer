import math

from boss_plugins.venomous_abyss.lostexplorers import analyze_lost, analyze_throw_junk
from boss_plugins.venomous_abyss.sszorak import (
    DIG_WIND_DIRECTIONS,
    _infer_dig_winds,
    _infer_wind_from_frames,
    _placement_slot_validation,
    analyze_sszorak,
)
from boss_plugins.venomous_abyss.twinfangs import analyze_twinfangs
from boss_plugins.venomous_abyss.vashnik import analyze_vashnik
from boss_plugins.venomous_abyss.shared import (
    build_position_index,
    build_survival_timeline,
    difficulty_fields,
    local_spell_tooltip,
    spell_name,
)


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


def test_local_tooltip_uses_confirmed_raid_guide_names_without_404_stub_text():
    assert local_spell_tooltip(1307939)["name"] == "残骸凋零"
    assert local_spell_tooltip(1295085)["name"] == "灵魂转移"
    assert local_spell_tooltip(1294605)["name"] == "邪恶洪流"


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


def test_lost_explorers_groups_defense_uses_opposite_patch_and_keeps_three_thuds():
    fight = {"startTime": 0, "endTime": 80_000}
    players = {1: player(1, "甲"), 2: player(2, "乙"), 3: player(3, "丙")}
    raw = {
        "casts": [event(1_000, 1295891, "cast"), event(50_000, 1296094, "cast")],
        "damage": [
            event(50_600, 1300237, "damage", targetID=1, amount=100),
            event(52_600, 1300237, "damage", targetID=2, amount=100),
            event(54_600, 1300237, "damage", targetID=3, amount=100),
        ],
        "debuffs": [
            event(1_200, 1295928, "applydebuff", targetID=1),
            event(1_300, 1295954, "applydebuff", targetID=2),
            event(1_500, 1297648, "applydebuff", targetID=1),
            event(2_000, 1295928, "removedebuff", targetID=1),
            event(2_010, 1297648, "removedebuff", targetID=1),
            event(30_000, 1295954, "removedebuff", targetID=2),
        ],
        "enemyBuffs": [
            event(10_000, 1297646, "applybuff", targetID=20),
            event(10_020, 1297646, "applybuff", targetID=21),
            event(10_040, 1297646, "applybuff", targetID=22),
            event(12_000, 1297646, "removebuff", targetID=20),
            event(12_010, 1297646, "removebuff", targetID=21),
            event(12_020, 1297646, "removebuff", targetID=22),
        ],
        "friendlyBuffs": [], "deaths": [],
    }
    result = analyze_lost(
        fight, {1: "甲", 2: "乙", 3: "丙", 20: "A", 21: "B", 22: "C"}, players, raw,
    )
    assert len(result["unitedDefense"]) == 1
    assert result["unitedDefense"][0]["durationSec"] == 2.0
    assert result["unitedDefenseTotalSec"] == 2.0
    assignments = result["frostfireVolley"][0]["assignments"]
    assert assignments[0]["resolution"] == "correct"
    assert assignments[1]["resolution"] == "timeout"
    assert len(result["mightyThud"][0]["waves"]) == 3


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

    # 每轮吃球：甲吃 1 个（正常份额），乙在场但 0 个（没吃）
    assert round_row["teamSize"] == 2
    assert round_row["aliveCount"] == 2
    assert round_row["ballCount"] == 1
    assert [(row["playerID"], row["count"]) for row in round_row["eaten"]] == [(1, 1)]
    assert [row["playerID"] for row in round_row["missed"]] == [2]
    assert round_row["abnormal"] == []
    # 该合成数据里两次叠层来源都是正常/未匹配，异常叠层记录应为空
    assert result["eternalVenom"]["abnormalGains"] == []


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
            event(9000, 1305963, "removedebuff", targetID=2),
            event(9500, 1305963, "removedebuff", targetID=3),
            event(10_000, 1285425, "applydebuff", targetID=1, x=0, y=1000),
            event(10_000, 1285453, "applydebuff", targetID=2, x=500, y=1000),
            event(17_000, 1285425, "removedebuff", targetID=1),
            event(17_000, 1285453, "removedebuff", targetID=2),
            event(17_010, 1285447, "applydebuff", targetID=1),
            event(17_010, 1285447, "applydebuff", targetID=2),
            event(17_400, 1285447, "removedebuff", targetID=1),
            event(17_420, 1285447, "removedebuff", targetID=2),
        ],
        "friendlyCasts": [event(17_200, 48265, "cast", sourceID=1)],
        "resources": [],
        "deaths": [],
        "bossID": 50,
        "bossPositionEvents": [{"timestamp": 1000, "sourceID": 50, "targetID": 50, "x": 0, "y": 0}],
    }
    result = analyze_sszorak(fight, {1: "甲", 2: "乙", 3: "丙", 50: "Boss"}, players, raw)
    placements = result["cysts"]["placements"]
    assert len(placements) == 3
    assert placements[0]["consumedAtMs"] == 8000
    assert placements[0]["activatedAtMs"] == 8000
    assert placements[0]["timeMs"] == 8000
    assert placements[0]["active"] is False
    assert result["fieldReplay"]["arena"]["method"] == "fixed-wcl-map-center"
    assert result["fieldReplay"]["arena"]["centerX"] == -40652.0
    assert result["fieldReplay"]["arena"]["centerY"] == 33843.0
    assert result["fieldReplay"]["arena"]["coordinateOffsetYards"] == -50
    assert result["fieldReplay"]["arena"]["rotationDegrees"] == 60
    assert result["fieldReplay"]["arenaImage"].endswith("05-sszorak-arena.png")
    assert result["fieldReplay"]["bossIcon"].endswith("05-sszorak-boss.png")
    assert len(result["crosswinds"]["waves"]) == 1
    wave = result["crosswinds"]["waves"][0]
    assert wave["targetCount"] == 2
    assert wave["resolvedCount"] == 2
    assert len(wave["pairings"]) == 1
    assert wave["targets"][0]["resolution"] == "与反方向玩家对撞消除"
    assert wave["targets"][0]["mobilityUses"][0]["spellName"] == "死亡脚步"
    assert wave["targets"][0]["mobilityUses"][0]["offsetFromLaunchMs"] == 190
    assert result["fieldReplay"]["frameStepMs"] == 200


def test_sszorak_stops_replay_positions_at_first_death():
    fight = {"startTime": 0, "endTime": 50_000}
    players = {1: player(1, "甲"), 2: player(2, "乙")}
    raw = {
        "casts": [event(20_000, 1286033, "cast")],
        "damage": [
            {"timestamp": 19_000, "sourceID": 1, "targetID": 50, "x": -40652, "y": 38843},
            {"timestamp": 19_000, "sourceID": 2, "targetID": 50, "x": -40552, "y": 38843},
            {"timestamp": 25_000, "sourceID": 2, "targetID": 50, "x": -39000, "y": 40000},
        ],
        "debuffs": [],
        "resources": [],
        "deaths": [event(21_000, 0, "death", targetID=2)],
        "bossID": 50,
        "bossPositionEvents": [
            {"timestamp": 1000, "sourceID": 50, "targetID": 50, "x": -40682, "y": 38835},
        ],
    }
    result = analyze_sszorak(fight, {1: "甲", 2: "乙", 50: "Boss"}, players, raw)
    frames = result["fieldReplay"]["rounds"][0]["frames"]
    before = next(frame for frame in frames if frame["timeMs"] == 20_800)
    after = next(frame for frame in frames if frame["timeMs"] == 21_000)
    assert before["players"][1]["dead"] is False
    assert after["players"][1]["dead"] is True
    assert after["players"][1]["position"] is None
    assert result["fieldReplay"]["arena"]["bossStart"] == {"x": -40682.0, "y": 33835.0}


def test_sszorak_dig_wind_uses_six_sources_across_three_lines():
    arena = {"centerX": 0, "centerY": 0, "radius": 6200}
    for source_key, expected in DIG_WIND_DIRECTIONS.items():
        angle = math.radians(expected["wclAngleDegrees"])
        # 风证据要求同一帧至少两名玩家同向移动（单人移动多为闪现贴囊/走位）。
        frames = [
            {"timeMs": 0, "players": [
                {"position": {"x": 0, "y": 0}},
                {"position": {"x": 500, "y": 0}},
            ]},
            {"timeMs": 200, "players": [
                {"position": {
                    "x": math.cos(angle) * 1000,
                    "y": -math.sin(angle) * 1000,
                }},
                {"position": {
                    "x": 500 + math.cos(angle) * 1000,
                    "y": -math.sin(angle) * 1000,
                }},
            ]},
        ]
        result = _infer_wind_from_frames(frames, arena)
        assert result["sourceKey"] == source_key
        assert result["targetKey"] == expected["targetKey"]
        assert result["directionLabel"] == expected["label"]

    assert len({row["lineKey"] for row in DIG_WIND_DIRECTIONS.values()}) == 3
    assert DIG_WIND_DIRECTIONS["skull"]["angleDegrees"] == 45
    assert DIG_WIND_DIRECTIONS["cross"]["angleDegrees"] == 225


def test_sszorak_cyst_validation_uses_first_two_winds_and_one_of_last_two():
    winds = [
        DIG_WIND_DIRECTIONS["triangle"],
        DIG_WIND_DIRECTIONS["circle"],
        DIG_WIND_DIRECTIONS["skull"],
    ]
    placements = [
        {"windSide": "diamond"},
        {"windSide": "triangle"},
        {"windSide": "cross"},
        {"windSide": "square"},
    ]
    result = _placement_slot_validation(placements, winds)
    assert result[0]["placementOk"] is True
    assert result[1]["placementOk"] is False
    assert result[2]["placementOk"] is True
    assert result[3]["placementOk"] is True


def test_sszorak_cyst_validation_marks_incomplete_winds_as_unverified():
    winds = [DIG_WIND_DIRECTIONS["triangle"], DIG_WIND_DIRECTIONS["circle"], None]
    placements = [
        {"windSide": "cross"},
        {"windSide": "diamond"},
        {"windSide": "square"},
        {"windSide": "skull"},
    ]
    result = _placement_slot_validation(placements, winds)
    assert result[0]["placementStatus"] == "unverified"
    assert result[0]["placementOk"] is None
    assert result[1]["placementOk"] is True


def test_lost_tracks_united_defense_total_duration():
    fight = {"startTime": 0, "endTime": 60_000}
    players = {1: player(1), 2: player(2), 3: player(3)}
    raw = {
        "casts": [], "damage": [], "debuffs": [],
        "enemyBuffs": [
            event(10_000, 1297646, "applybuff", targetID=20),
            event(10_020, 1297646, "applybuff", targetID=21),
            event(12_000, 1297646, "removebuff", targetID=20),
            event(12_010, 1297646, "removebuff", targetID=21),
            event(20_000, 1297646, "applybuff", targetID=20),
            event(20_020, 1297646, "applybuff", targetID=22),
            event(23_000, 1297646, "removebuff", targetID=20),
            event(23_010, 1297646, "removebuff", targetID=22),
        ],
        "friendlyBuffs": [], "deaths": [],
    }
    result = analyze_lost(
        fight, {1: "甲", 2: "乙", 3: "丙", 20: "A", 21: "B", 22: "C"}, players, raw,
    )
    assert len(result["unitedDefense"]) == 2
    assert result["unitedDefenseTotalSec"] == 5.0


def test_lost_throw_junk_tracks_steps_immunity_missing_and_relic_rupture():
    fight = {"startTime": 0, "endTime": 50_000}
    players = {
        1: player(1, "踩箱者"),
        2: player(2, "免疫者"),
        3: player(3, "未踩者"),
        4: player(4, "阵亡者"),
    }
    casts = [
        event(1_000, 1291933, "begincast"),
        event(5_000, 1291933, "begincast"),
        event(9_000, 1306145, "begincast"),
        event(30_000, 1291933, "begincast"),
    ]
    debuffs = [
        event(7_000, 1308853, "applydebuff", targetID=1, stack=1),
        event(8_000, 1308853, "applydebuffstack", targetID=1, stack=2),
    ]
    friendly_buffs = [
        event(6_500, 642, "applybuff", targetID=2),
        event(8_500, 642, "removebuff", targetID=2),
    ]
    damage = [event(7_500, 1310027, "damage", targetID=3, amount=1234)]
    deaths = [event(9_500, 1, "death", targetID=4, killingAbilityGameID=1)]

    result = analyze_throw_junk(
        fight, {1: "踩箱者", 2: "免疫者", 3: "未踩者", 4: "阵亡者"},
        players, casts, damage, debuffs, friendly_buffs, deaths, [],
    )

    assert result["roundCount"] == 2
    first = result["rounds"][0]
    assert first["throwCount"] == 3
    assert first["stepped"][0]["playerID"] == 1
    assert first["stepped"][0]["stepCount"] == 2
    assert first["stepped"][0]["peakStack"] == 2
    assert first["immunityPlayers"][0]["playerID"] == 2
    assert first["immunityPlayers"][0]["immunities"][0]["spellName"] == "圣盾术"
    assert [row["playerID"] for row in first["missing"]] == [3]
    assert first["relicRuptureTriggered"] is True
    assert first["relicRuptureHitCount"] == 1
    assert "relicRuptureTime" not in first
    assert "relicRuptureVictims" not in first
    assert "relicRuptureDamage" not in first
    assert result["rounds"][1]["relicRuptureTriggered"] is False


def test_lost_throw_junk_reincludes_player_after_combat_res():
    fight = {"startTime": 0, "endTime": 30_000}
    players = {1: player(1, "战复玩家"), 2: player(2, "施法者")}
    result = analyze_throw_junk(
        fight, {1: "战复玩家", 2: "施法者"}, players,
        [event(20_000, 1291933, "begincast")], [], [], [],
        [event(5_000, 1, "death", targetID=1, killingAbilityGameID=1)],
        [event(10_000, 20484, "cast", sourceID=2, targetID=1)],
    )
    assert {row["playerID"] for row in result["rounds"][0]["missing"]} == {1, 2}


def test_twinfangs_inserts_death_when_feast_clears_multiple_stacks():
    fight = {"startTime": 0, "endTime": 50_000}
    players = {1: player(1, "甲")}
    raw = {
        "debuffs": [
            event(1000, 1290336, "applydebuff", targetID=1, sourceID=50, stack=1),
            event(2000, 1290336, "applydebuffstack", targetID=1, sourceID=50, stack=3),
            event(3000, 1290336, "removedebuff", targetID=1, sourceID=50),
        ],
        "casts": [event(2800, 1290516, "cast", targetID=0)],
        "damage": [],
        "friendlyBuffs": [],
        "deaths": [event(3000, 1287083, "death", targetID=1, killingAbilityGameID=1287083)],
    }
    history = analyze_twinfangs(fight, {1: "甲", 50: "Boss"}, players, raw)["eternalVenom"]["players"][0]
    clear = history["events"][-1]
    assert clear["category"] == "death"
    assert clear["sourceID"] == 1287083
    assert clear["fromStack"] == 3


def test_spell_name_maps_melee_attack():
    assert spell_name(1) == "近战攻击"
    assert spell_name(999999999) == "未知技能"


def test_infer_dig_winds_prefers_movement_and_never_uses_cyst_activation_as_direction():
    arena = {"centerX": 0, "centerY": 0, "radius": 6200}
    cross_angle = math.radians(DIG_WIND_DIRECTIONS["cross"]["wclAngleDegrees"])
    frames = [
        {"timeMs": 16000, "players": [{"position": {"x": 0, "y": 0}}, {"position": {"x": 0, "y": 0}}]},
        {"timeMs": 16200, "players": [
            {"position": {"x": math.cos(cross_angle) * 1000, "y": -math.sin(cross_angle) * 1000}},
            {"position": {"x": math.cos(cross_angle) * 1000, "y": -math.sin(cross_angle) * 1000}},
        ]},
        {"timeMs": 16400, "players": [
            {"position": {"x": math.cos(cross_angle) * 2000, "y": -math.sin(cross_angle) * 2000}},
            {"position": {"x": math.cos(cross_angle) * 2000, "y": -math.sin(cross_angle) * 2000}},
        ]},
    ]
    expected = _infer_wind_from_frames(frames, arena)
    assert expected["sourceKey"] == "cross"
    winds = _infer_dig_winds(frames, arena, segment_count=1, activation_rows=[])
    assert winds[0]["directionLabel"] == expected["directionLabel"]
    blocked = _infer_dig_winds(frames, arena, segment_count=1, activation_rows=[{
        "activatedTimestamp": 16350,
        "windSide": "circle",
        "placementKey": "circle",
        "player": "错误放置",
    }])
    assert blocked[0] is None


def test_sszorak_cyst_activation_window_is_asymmetric_and_solo_move_is_not_wind():
    """2026-08-24 斯索拉克 kill 战 #1 掘地第三棒风回归：团风在撞囊瞬间结束、
    囊肿爆炸在激活后反向击飞。对称 ±1.1s 排除窗会把真实风尾吞掉、把反向击飞
    尾巴漏在窗外，整段风被判反。
    验证：① 激活前 300ms / 激活后 2500ms 的非对称排除——风（激活前）仍算证据、
    爆炸（激活后）全部排除；② 单人移动帧不再单独构成风证据（闪现贴囊不带偏）。"""
    from boss_plugins.venomous_abyss import sszorak as P

    arena = {"centerX": 0, "centerY": 0, "radius": 6200}
    wind_angle = math.radians(P.DIG_WIND_DIRECTIONS["circle"]["wclAngleDegrees"])
    # 团风：3 名玩家同向持续移动 0-1800ms（末帧距激活 100ms，须仍算风证据）。
    frames = []
    for i in range(10):
        t = 200 * i
        frames.append({"timeMs": t, "players": [
            {"position": {"x": math.cos(wind_angle) * (1000 * j + 2000 * i),
                          "y": -math.sin(wind_angle) * (1000 * j + 2000 * i)}}
            for j in range(3)
        ]})
    # 囊肿激活 1900ms；爆炸反向击飞 2000-3000ms（全部落在激活后 2500ms 排除窗内）。
    activation = 1900
    back_angle = math.radians(P.DIG_WIND_DIRECTIONS["square"]["wclAngleDegrees"])
    base = [(math.cos(wind_angle) * (1000 * j + 18000),
             -math.sin(wind_angle) * (1000 * j + 18000)) for j in range(3)]
    for k in range(6):
        t = 2000 + 200 * k
        frames.append({"timeMs": t, "players": [
            {"position": {"x": base[j][0] + math.cos(back_angle) * 1000 * (k + 1),
                          "y": base[j][1] - math.sin(back_angle) * 1000 * (k + 1)}}
            for j in range(3)
        ]})

    wind = P._infer_wind_from_frames(frames, arena, excluded_timestamps=[activation])
    assert wind is not None
    assert wind["sourceKey"] == "circle"
    assert wind["targetKey"] == "square"
    assert wind["sustainedFrameCount"] == 7

    # 单人移动帧：只有一名玩家大幅移动时不得单独构成风证据。
    solo = [
        {"timeMs": 0, "players": [
            {"position": {"x": 0, "y": 0}},
            {"position": {"x": 100, "y": 0}},
        ]},
        {"timeMs": 200, "players": [
            {"position": {"x": math.cos(wind_angle) * 2000,
                          "y": -math.sin(wind_angle) * 2000}},
            {"position": {"x": 120, "y": 0}},
        ]},
    ]
    assert P._infer_wind_from_frames(solo, arena) is None


def test_twinfangs_globule_rounds_track_eaten_counts_missed_and_abnormal_gains():
    fight = {"startTime": 0, "endTime": 30_000}
    players = {1: player(1, "甲"), 2: player(2, "乙"), 3: player(3, "丙")}
    raw = {
        "debuffs": [
            event(6100, 1290336, "applydebuff", targetID=1, sourceID=50, stack=1),
            event(8000, 1290336, "applydebuffstack", targetID=3, sourceID=50, stack=2),
        ],
        "casts": [
            event(5000, 1289192, "cast", targetID=0),
            event(25_000, 1291404, "begincast", targetID=0),
        ],
        "damage": [
            # 腐蚀液滴（球）命中：甲×1、乙×2、丙×1
            event(6000, 1289201, "damage", targetID=1, amount=10),
            event(6500, 1289201, "damage", targetID=2, amount=10),
            event(7000, 1289201, "damage", targetID=2, amount=10),
            event(7500, 1289201, "damage", targetID=3, amount=10),
            # 腐蚀液滴爆裂直接给丙叠 2 层（异常叠层）
            event(8100, 1290338, "damage", targetID=3, amount=100),
        ],
        "friendlyBuffs": [], "deaths": [],
    }
    result = analyze_twinfangs(fight, {1: "甲", 2: "乙", 3: "丙", 50: "Boss"}, players, raw)
    round_row = result["globules"]["rounds"][0]
    assert round_row["teamSize"] == 3
    assert round_row["aliveCount"] == 3
    assert round_row["ballCount"] == 4
    assert [(row["playerID"], row["count"]) for row in round_row["eaten"]] == [(2, 2), (1, 1), (3, 1)]
    assert round_row["missed"] == []
    assert [(row["playerID"], row["count"]) for row in round_row["abnormal"]] == [(2, 2)]
    gains = result["eternalVenom"]["abnormalGains"]
    # 丙的爆裂叠层是异常叠层；甲吃球的正常叠层不在此列
    assert [(row["playerID"], row["sourceID"]) for row in gains] == [(3, 1290338)]
    assert gains[0]["delta"] == 2
    assert gains[0]["toStack"] == 2


def test_twinfangs_deluge_green_circle_hit_is_abnormal_gain():
    fight = {"startTime": 0, "endTime": 30_000}
    players = {1: player(1, "甲")}
    raw = {
        "debuffs": [
            event(10_000, 1290336, "applydebuff", targetID=1, sourceID=50, stack=1),
        ],
        "casts": [event(5_000, 1289192, "cast", targetID=0)],
        "damage": [event(9_990, 1289994, "damage", targetID=1, amount=50)],
        "friendlyBuffs": [], "deaths": [],
    }
    result = analyze_twinfangs(fight, {1: "甲", 50: "Boss"}, players, raw)
    row = result["eternalVenom"]["players"][0]["events"][0]
    assert row["category"] == "abnormal"
    assert row["sourceID"] == 1289994
    assert result["eternalVenom"]["abnormalGains"][0]["sourceID"] == 1289994
