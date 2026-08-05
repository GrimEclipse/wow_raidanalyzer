from boss_plugins.venomous_abyss.nakzali import (
    DEFAULT_OPTIONS,
    analyze_avoidable,
    analyze_essence_rend,
    analyze_leaks,
    apply_barrage_verdicts,
    build_player_catalog,
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
    options = {**DEFAULT_OPTIONS, "essenceRendEdgeRatio": 0.7}
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
    assert placement["placementEstimate"] == "贴边"


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


def test_corpse_wither_is_not_classified_as_avoidable_damage():
    fight = {"startTime": 0, "endTime": 30_000}
    damage = [
        event(5_000, 1307939, "damage", targetID=7, amount=100_000),
        event(6_000, 1288554, "damage", targetID=7, amount=50_000),
    ]
    result = analyze_avoidable(fight, {7: "测试玩家"}, {7: "Player"}, damage, [])
    assert "1307939" not in result
    assert result["1288554"][0]["spellName"] == "移动黑圈"


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
