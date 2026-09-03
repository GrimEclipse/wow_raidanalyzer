from boss_plugins.venomous_abyss.nakzali import (
    DEFAULT_OPTIONS,
    SPELLS,
    analyze_corpse_cremation,
    analyze_inner_realm,
    analyze_avoidable,
    analyze_essence_rend,
    analyze_leaks,
    apply_barrage_verdicts,
    build_player_catalog,
    build_position_index,
    infer_barrage_interceptor,
    phase_markers,
    snapshot_at,
)


def event(timestamp, spell_id, kind="cast", **extra):
    return {"timestamp": timestamp, "abilityGameID": spell_id, "type": kind, **extra}


def test_phase_markers_do_not_use_wcl_last_phase():
    fight = {"startTime": 10_000, "endTime": 310_000, "kill": False, "bossPercentage": 3.5}
    casts = [
        event(110_000, 1295124, "begincast"),
        event(280_000, 1284034, "begincast"),
    ]
    buffs = [event(210_000, 1290003, "applybuff")]
    assert [row["key"] for row in phase_markers(fight, casts, buffs)] == [
        "p1", "intermission", "p2", "enrage", "wipe"
    ]


def test_essence_rend_uses_nearby_position_not_death_fallback():
    fight = {"startTime": 0, "endTime": 30_000}
    debuffs = [event(10_000, 1287434, "removedebuff", targetID=7)]
    damage = [event(9_700, 1287434, "damage", targetID=7, x=115, y=100)]
    options = {**DEFAULT_OPTIONS, "essenceRendPlacementCountEnabled": True}
    result = analyze_essence_rend(
        fight,
        {7: "测试玩家"},
        debuffs,
        damage,
        {"centerX": 100, "centerY": 100, "radius": 20},
        options,
    )
    placement = result["placements"][0]
    assert placement["sampleOffsetMs"] == -300
    assert placement["placementEstimate"] == "太靠近中场"
    assert placement["counted"] is True
    assert placement["distanceFromCenterYards"] == 0.1


def test_essence_rend_missing_position_stays_missing():
    fight = {"startTime": 0, "endTime": 30_000}
    result = analyze_essence_rend(
        fight,
        {7: "测试玩家"},
        [event(10_000, 1287434, "removedebuff", targetID=7)],
        [],
        None,
        DEFAULT_OPTIONS,
    )
    assert result["placements"][0]["placementEstimate"] == "没有任何可用坐标样本"


def test_extra_ritual_burn_requires_add_instance_for_confirmation():
    fight = {"startTime": 0, "endTime": 30_000}
    casts = [event(1_000, 1293664)]
    casts += [event(timestamp, 1297624) for timestamp in (1_500, 2_500, 3_500, 4_500, 5_500, 10_000)]
    casts += [event(9_200, 1287533, sourceID=50, sourceInstance=3)]
    markers = [{"key": "p1", "timeMs": 0}, {"key": "wipe", "timeMs": 30_000}]
    result = analyze_leaks(fight, casts, markers, {**DEFAULT_OPTIONS, "amaniLeakCountEnabled": True})
    assert result["confirmedCount"] == 1
    assert result["suspectedCount"] == 1
    assert result["events"][0]["counted"] is True


def test_enrage_barrage_never_becomes_intercept_verdict():
    rounds = [{"waves": [{"timeMs": 20_000, "delayFromCastMs": 100, "totalDamage": 9_000_000, "hitCount": 20}], "deaths": []}]
    apply_barrage_verdicts(
        rounds,
        {"delayMedianMs": 2_000, "damagePerPlayerMedian": 100_000},
        10_000,
        {**DEFAULT_OPTIONS, "possessionBarrageCountEnabled": True},
    )
    assert rounds[0]["waves"][0]["verdict"] == "狂暴后的附身弹幕"
    assert rounds[0]["waves"][0]["counted"] is False


def test_barrage_interceptor_uses_first_player_crossing_boss_target_lane():
    players = {
        1: {"id": 1, "name": "点名者", "classColor": "#fff"},
        2: {"id": 2, "name": "近处挡线", "classColor": "#f00"},
        3: {"id": 3, "name": "远处挡线", "classColor": "#0f0"},
        4: {"id": 4, "name": "线外玩家", "classColor": "#00f"},
    }
    positions = build_position_index([
        {"timestamp": 1000, "sourceID": 50, "x": 0, "y": 0},
        {"timestamp": 1000, "sourceID": 1, "x": 2000, "y": 0},
        {"timestamp": 2000, "sourceID": 2, "x": 500, "y": 100},
        {"timestamp": 2000, "sourceID": 3, "x": 1000, "y": 0},
        {"timestamp": 2000, "sourceID": 4, "x": 500, "y": 500},
    ])

    result = infer_barrage_interceptor(2000, 1000, 1, players, positions, [50])

    assert result["player"] == "近处挡线"
    assert result["distanceToLaneYards"] == 1.0
    assert result["distanceFromBossYards"] == 5.0


def test_corpse_wither_is_not_classified_as_avoidable_damage():
    fight = {"startTime": 0, "endTime": 30_000}
    damage = [
        event(5_000, 1307939, "damage", targetID=7, amount=100_000),
        event(6_000, 1288554, "damage", targetID=7, amount=50_000),
    ]
    result = analyze_avoidable(fight, {7: "测试玩家"}, {7: "Player"}, damage, [])
    assert "1307939" not in result
    assert result["1288554"][0]["spellName"] == "潜藏的教徒"


def test_immortal_coil_is_not_classified_as_avoidable_damage():
    fight = {"startTime": 0, "endTime": 30_000}
    damage = [event(5_000, 1308227, "damage", targetID=7, amount=100_000)]
    assert analyze_avoidable(fight, {7: "测试玩家"}, {7: "Player"}, damage, []) == {}


def test_soulcoil_rite_uses_confirmed_chinese_alias():
    assert SPELLS[1288772] == "盘魂仪式"


def test_player_catalog_only_contains_current_fight_combatants():
    actors = {1: "本场玩家", 2: "报告中的其他玩家"}
    actor_types = {1: "Player", 2: "Player"}
    combatants = [{"sourceID": 1, "specID": 71}]
    assert list(build_player_catalog(actors, actor_types, combatants)) == [1]


def test_snapshot_does_not_fake_boss_centre_when_wcl_has_no_boss_position():
    snapshot = snapshot_at(
        10_000,
        {},
        [99],
        {99: "盘魂者内克扎利"},
        {},
        [],
        {"centerX": 100, "centerY": 200, "radius": 50},
    )
    boss = snapshot["bosses"][0]
    assert boss["position"] is None
    assert boss["positionRule"] == "missing"
    assert boss["positionReliable"] is False


def test_corpse_cremation_marks_no_attempt_only_when_awakened_host_is_observed():
    fight = {"startTime": 0, "endTime": 40_000, "difficulty": 5}
    players = {1: {"id": 1, "name": "远离尸体", "classColor": "#f00"}}
    rounds = [{"index": 1, "timeMs": 20_000, "time": "00:20.0"}]
    debuffs = [
        event(20_000, 1294933, "applydebuff", targetID=1),
        event(28_000, 1294933, "removedebuff", targetID=1),
    ]
    positions = build_position_index([
        event(20_000, 0, "resource", sourceID=1, x=2_000, y=0),
        event(28_000, 0, "resource", sourceID=1, x=2_000, y=0),
    ])
    amani_damage = [event(
        10_000, 1, "damage", targetID=50, targetInstance=3,
        hitPoints=0, x=0, y=0,
    )]
    amani_buffs = [event(
        30_000, 1297631, "applybuff", targetID=50, targetInstance=3,
    )]

    analyze_corpse_cremation(
        fight, {1: "远离尸体"}, players, rounds, debuffs, positions,
        amani_damage, amani_buffs, DEFAULT_OPTIONS,
    )

    result = rounds[0]["corpseCremation"]
    assert result["awakenedHostCount"] == 1
    assert result["noAttemptRefs"][0]["player"] == "远离尸体"
    assert result["players"][0]["nearestCorpseYards"] == 20.0
    assert result["players"][0]["nearestCorpseAtMark"] == {
        "corpseUID": "50:3:10000",
        "instance": 3,
        "x": 0.0,
        "y": 0.0,
        "distanceYards": 20.0,
    }


def test_corpse_cremation_checks_the_full_slithering_flame_window():
    fight = {"startTime": 0, "endTime": 40_000, "difficulty": 5}
    players = {1: {"id": 1, "name": "后程接近", "classColor": "#f00"}}
    rounds = [{"index": 1, "timeMs": 20_000, "time": "00:20.0"}]
    debuffs = [
        event(20_000, 1294933, "applydebuff", targetID=1),
        event(28_000, 1294933, "removedebuff", targetID=1),
    ]
    positions = build_position_index([
        event(20_000, 0, "resource", sourceID=1, x=2_000, y=0),
        event(23_000, 0, "resource", sourceID=1, x=1_500, y=0),
        event(26_000, 0, "resource", sourceID=1, x=800, y=0),
        event(28_000, 0, "resource", sourceID=1, x=800, y=0),
    ])
    amani_damage = [event(
        10_000, 1, "damage", targetID=50, targetInstance=3,
        hitPoints=0, x=0, y=0,
    )]
    amani_buffs = [event(
        29_000, 1297631, "applybuff", targetID=50, targetInstance=3,
    )]

    analyze_corpse_cremation(
        fight, {1: "后程接近"}, players, rounds, debuffs, positions,
        amani_damage, amani_buffs, DEFAULT_OPTIONS,
    )

    player = rounds[0]["corpseCremation"]["players"][0]
    assert player["nearestCorpseAtMark"]["distanceYards"] == 20.0
    assert player["nearestCorpseYards"] == 8.0
    assert player["attempted"] is True
    assert rounds[0]["corpseCremation"]["noAttemptRefs"] == []


def test_inner_realm_splits_recovery_entry_in_same_well():
    fight = {"startTime": 0, "endTime": 60_000, "difficulty": 5}
    players = {
        1: {"id": 1, "name": "三队甲", "classColor": "#f00"},
        2: {"id": 2, "name": "补位乙", "classColor": "#0f0"},
    }
    payload = {
        "innerBuffs": [
            event(1_000, 1300514, "applybuff", targetID=60),
            event(50_000, 1300514, "removebuff", targetID=60),
        ],
        "debuffs": [
            event(5_000, 1299988, "applydebuff", targetID=1),
            event(25_000, 1299988, "removedebuff", targetID=1),
            event(21_000, 1290361, "applydebuff", targetID=1),
            event(35_000, 1299988, "applydebuff", targetID=2),
            event(48_000, 1299988, "removedebuff", targetID=2),
        ],
        "casts": [event(20_000, 1300238, "cast", sourceID=61)],
        "interrupts": [],
        "damage": [],
        "deaths": [],
    }
    options = {
        **DEFAULT_OPTIONS,
        "innerRealmTeams": {"3": ["三队甲"], "4": ["补位乙"]},
        "innerRealmRotation": ["3", "4"],
    }

    result = analyze_inner_realm(fight, {1: "三队甲", 2: "补位乙"}, players, payload, options)

    assert len(result["rounds"]) == 2
    assert result["rounds"][0]["wellIndex"] == result["rounds"][1]["wellIndex"] == 1
    assert result["rounds"][0]["curseSuccessCount"] == 1
    assert result["rounds"][0]["mindControlledRefs"][0]["player"] == "三队甲"
    assert result["rounds"][1]["entrantRefs"][0]["player"] == "补位乙"
