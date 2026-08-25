from boss_plugins.venomous_abyss.sentinels import (
    ACID_MARK_ID,
    BLOOD_MARK_ID,
    CLINGING_MURK_ID,
    CULTIVATED_BURST_DAMAGE_ID,
    DEFAULT_OPTIONS,
    HELICAL_ID,
    NOXIOUS_BLAST_ID,
    STASIS_IDS,
    TOXIC_DROPLETS_CAST_ID,
    TOXIC_DROPLETS_HIT_ID,
    UNSTABLE_MIASMA_ID,
    analyze_clinging_murk,
    analyze_helical_toxins,
    analyze_marks,
    analyze_toxic_droplets,
    build_position_index,
    phase_timeline,
)


def event(timestamp, spell_id, kind, target_id=None, **extra):
    row = {"timestamp": timestamp, "abilityGameID": spell_id, "type": kind, **extra}
    if target_id is not None:
        row["targetID"] = target_id
    return row


def test_helical_toxins_reconstructs_one_plus_one_then_two_plus_two_recovery():
    fight = {"startTime": 0, "endTime": 60_000}
    stasis = [event(10_000, next(iter(STASIS_IDS)), "cast")]
    auras = [
        event(10_010, HELICAL_ID, "applydebuff", 1),
        event(10_011, HELICAL_ID, "applydebuff", 2),
        event(12_000, HELICAL_ID, "applydebuffstack", 1, stack=2),
        event(12_000, HELICAL_ID, "applydebuffstack", 2, stack=2),
        event(15_595, HELICAL_ID, "removedebuff", 1),
        event(15_596, HELICAL_ID, "removedebuff", 2),
    ]
    result = analyze_helical_toxins(fight, {1: "甲", 2: "乙"}, stasis, auras, [])
    collisions = result["rounds"][0]["collisions"]
    assert collisions[0]["inferredInput"] == [1, 1]
    assert collisions[0]["resultStack"] == 2
    assert collisions[1]["kind"] == "recovery-clear"
    assert collisions[1]["knownInput"] == [2, 2]
    assert collisions[1]["time"] == "00:15.6"
    assert collisions[1]["playerIDs"] == [1, 2]


def test_helical_safe_clear_always_keeps_timestamp_and_player_ids():
    fight = {"startTime": 0, "endTime": 60_000}
    stasis = [event(10_000, next(iter(STASIS_IDS)), "cast")]
    auras = [
        event(10_010, HELICAL_ID, "applydebuff", 1),
        event(10_011, HELICAL_ID, "applydebuff", 2),
        event(12_000, HELICAL_ID, "removedebuff", 1),
        event(12_001, HELICAL_ID, "removedebuff", 2),
    ]

    result = analyze_helical_toxins(fight, {1: "甲", 2: "乙"}, stasis, auras, [])

    collision = result["rounds"][0]["collisions"][0]
    assert collision["kind"] == "safe-clear"
    assert collision["timeMs"] == 12_000
    assert collision["time"] == "00:12.0"
    assert collision["playerIDs"] == [1, 2]
    assert collision["pairingEvidence"] == "same-frame-removal"


def test_helical_arbitrarily_pairs_four_safe_removals_in_same_frame():
    fight = {"startTime": 0, "endTime": 60_000}
    stasis = [event(10_000, next(iter(STASIS_IDS)), "cast")]
    auras = [event(10_010 + player_id, HELICAL_ID, "applydebuff", player_id) for player_id in range(1, 5)]
    auras += [event(12_000, HELICAL_ID, "removedebuff", player_id) for player_id in range(1, 5)]
    result = analyze_helical_toxins(
        fight, {1: "甲", 2: "乙", 3: "丙", 4: "丁"}, stasis, auras, [],
    )

    collisions = result["rounds"][0]["collisions"]
    assert [row["playerIDs"] for row in collisions] == [[1, 2], [3, 4]]
    assert all(row["kind"] == "safe-clear" for row in collisions)
    assert all(row["pairingEvidence"] == "same-frame-removal" for row in collisions)
    assert [row["distanceYards"] for row in collisions] == [None, None]


def test_helical_consumes_initial_stack_if_wcl_ever_supplies_it():
    fight = {"startTime": 0, "endTime": 60_000}
    stasis = [event(10_000, next(iter(STASIS_IDS)), "cast")]
    auras = [
        event(10_010, HELICAL_ID, "applydebuff", 1, stack=1),
        event(10_011, HELICAL_ID, "applydebuff", 2, stack=3),
        event(12_000, HELICAL_ID, "removedebuff", 1),
        event(12_001, HELICAL_ID, "removedebuff", 2),
    ]

    result = analyze_helical_toxins(fight, {1: "甲", 2: "乙"}, stasis, auras, [])

    round_row = result["rounds"][0]
    assert round_row["initialStackCount"] == 2
    assert round_row["collisions"][0]["kind"] == "safe-clear"


def test_helical_single_remove_uses_nearest_active_coordinate_partner():
    fight = {"startTime": 0, "endTime": 60_000}
    stasis = [event(10_000, next(iter(STASIS_IDS)), "cast")]
    auras = [
        event(10_010, HELICAL_ID, "applydebuff", 1),
        event(10_011, HELICAL_ID, "applydebuff", 2),
        event(10_012, HELICAL_ID, "applydebuff", 3),
        event(12_000, HELICAL_ID, "removedebuff", 1),
    ]
    positions = build_position_index([
        {"timestamp": 12_000, "sourceID": 1, "x": 0, "y": 0},
        {"timestamp": 12_000, "sourceID": 2, "x": 180, "y": 0},
        {"timestamp": 12_000, "sourceID": 3, "x": 1600, "y": 0},
    ])

    result = analyze_helical_toxins(
        fight, {1: "甲", 2: "乙", 3: "丙"}, stasis, auras, [],
        position_index=positions,
    )

    collision = result["rounds"][0]["collisions"][0]
    assert collision["kind"] == "safe-clear"
    assert collision["playerIDs"] == [1, 2]
    assert collision["pairingEvidence"] == "coordinates"
    assert collision["distanceYards"] == 1.8


def test_phase_timeline_deduplicates_cast_and_buff_rows_for_one_stasis():
    fight = {"startTime": 0, "endTime": 90_000}
    spell_id = next(iter(STASIS_IDS))
    stasis = [
        event(40_000, spell_id, "cast"),
        event(40_025, spell_id, "applybuff"),
        event(52_000, spell_id, "removebuff"),
        event(52_030, spell_id, "removebuff"),
    ]

    timeline = phase_timeline(fight, stasis)

    assert [row["label"] for row in timeline] == ["分场 1", "强酸静滞 1", "分场 2", "灭团"]


def test_helical_toxins_links_three_plus_three_overflow_to_burst():
    fight = {"startTime": 0, "endTime": 60_000}
    stasis = [event(10_000, next(iter(STASIS_IDS)), "cast")]
    auras = [
        event(10_010, HELICAL_ID, "applydebuff", 1),
        event(10_011, HELICAL_ID, "applydebuff", 2),
        event(20_000, HELICAL_ID, "applydebuffstack", 1, stack=6),
        event(20_000, HELICAL_ID, "applydebuffstack", 2, stack=6),
        event(38_000, HELICAL_ID, "removedebuff", 1),
    ]
    damage = [event(38_000, CULTIVATED_BURST_DAMAGE_ID, "damage", 1, amount=999)]
    result = analyze_helical_toxins(fight, {1: "甲", 2: "乙"}, stasis, auras, damage)
    round_row = result["rounds"][0]
    assert round_row["collisions"][0]["inferredInput"] == [3, 3]
    assert round_row["collisions"][0]["overflow"] is True
    assert round_row["collisions"][0]["firstWrongCollision"] is True
    assert round_row["failures"][0]["precedingResultStack"] == 6
    assert round_row["success"] is False


def test_helical_wrong_collision_reports_last_second_movement_over_five_yards():
    fight = {"startTime": 0, "endTime": 60_000}
    stasis = [event(10_000, next(iter(STASIS_IDS)), "cast")]
    auras = [
        event(10_010, HELICAL_ID, "applydebuff", 1),
        event(10_011, HELICAL_ID, "applydebuff", 2),
        event(12_000, HELICAL_ID, "applydebuffstack", 1, stack=3),
        event(12_000, HELICAL_ID, "applydebuffstack", 2, stack=3),
    ]
    positions = build_position_index([
        {"timestamp": 11_000, "sourceID": 1, "x": 0, "y": 0},
        {"timestamp": 12_000, "sourceID": 1, "x": 600, "y": 0},
        {"timestamp": 11_000, "sourceID": 2, "x": 0, "y": 0},
        {"timestamp": 12_000, "sourceID": 2, "x": 200, "y": 0},
    ])
    result = analyze_helical_toxins(
        fight, {1: "甲", 2: "乙"}, stasis, auras, [], position_index=positions
    )
    collision = result["rounds"][0]["collisions"][0]
    assert collision["largeMovers"] == [
        {"playerID": 1, "player": "甲", "movementYards": 6.0, "windowMs": 1000}
    ]
    assert collision["movementEvidence"] == {
        "windowMs": 1000,
        "players": [
            {"playerID": 1, "player": "甲", "movementYards": 6.0},
            {"playerID": 2, "player": "乙", "movementYards": 2.0},
        ],
        "pairDistanceBeforeYards": 0.0,
        "pairDistanceAtCollisionYards": 4.0,
        "closingDistanceYards": -4.0,
    }


def test_helical_stack_three_can_recover_with_two_separate_one_players():
    fight = {"startTime": 0, "endTime": 60_000}
    stasis = [event(10_000, next(iter(STASIS_IDS)), "cast")]
    auras = [event(10_010 + player_id, HELICAL_ID, "applydebuff", player_id) for player_id in range(1, 5)]
    auras += [
        event(12_000, HELICAL_ID, "applydebuffstack", 1, stack=3),
        event(12_000, HELICAL_ID, "applydebuffstack", 2, stack=3),
        event(15_000, HELICAL_ID, "removedebuff", 1),
        event(15_001, HELICAL_ID, "removedebuff", 3),
        event(16_000, HELICAL_ID, "removedebuff", 2),
        event(16_001, HELICAL_ID, "removedebuff", 4),
    ]
    names = {player_id: str(player_id) for player_id in range(1, 5)}
    result = analyze_helical_toxins(fight, names, stasis, auras, [])
    recoveries = [row for row in result["rounds"][0]["collisions"] if row["kind"] == "recovery-clear"]
    assert [row["knownInput"] for row in recoveries] == [[3, 1], [3, 1]]


def test_marks_returns_compact_overlap_and_total_stack_summary():
    fight = {"startTime": 0, "endTime": 100_000}
    players = {1: {"id": 1, "name": "鸟德", "specID": 102}}
    stasis = [
        event(40_000, next(iter(STASIS_IDS)), "applybuff"),
        event(50_000, next(iter(STASIS_IDS)), "removebuff"),
    ]
    marks = [
        event(5_000, ACID_MARK_ID, "applydebuff", 1),
        event(11_000, ACID_MARK_ID, "applydebuffstack", 1, stack=2),
        event(17_000, BLOOD_MARK_ID, "applydebuff", 1),
        event(56_000, BLOOD_MARK_ID, "applydebuffstack", 1, stack=7),
    ]
    result = analyze_marks(fight, {1: "鸟德"}, players, marks, stasis)
    player = result["players"][0]
    assert player["maxAcidStack"] == 2
    assert player["maxBloodStack"] == 7
    assert player["simultaneousBuffCount"] == 1
    assert player["highestTotalStack"] == 9
    assert "timeline" not in player["cycles"][0]["acid"]


def test_clinging_murk_reports_missing_blood_side_and_dispersed_players():
    fight = {"startTime": 0, "endTime": 30_000}
    players = {
        1: {"id": 1, "name": "甲"},
        2: {"id": 2, "name": "乙"},
        3: {"id": 3, "name": "丙"},
        4: {"id": 4, "name": "丁"},
    }
    debuffs = [event(10_000, UNSTABLE_MIASMA_ID, "removedebuff", 1)]
    for player_id in (1, 2, 3):
        debuffs.append(event(10_010, CLINGING_MURK_ID, "applydebuff", player_id))
        debuffs.append(event(16_000, CLINGING_MURK_ID, "removedebuff", player_id))
    positions = build_position_index([
        {"timestamp": 15_950, "sourceID": 1, "x": 1000, "y": 1000},
        {"timestamp": 15_950, "sourceID": 2, "x": 1100, "y": 1000},
        {"timestamp": 15_950, "sourceID": 3, "x": 3000, "y": 1000},
        {"timestamp": 9_950, "sourceID": 4, "x": 1000, "y": 1000},
    ])
    marks = [
        event(2_000, BLOOD_MARK_ID, "applydebuffstack", 4, stack=3),
        event(2_000, ACID_MARK_ID, "applydebuff", 4),
    ]
    result = analyze_clinging_murk(
        fight,
        {1: "甲", 2: "乙", 3: "丙", 4: "丁"},
        players,
        debuffs,
        positions,
        {**DEFAULT_OPTIONS, "waterMaxSampleOffsetMs": 500, "waterOutlierDistanceYards": 5},
        marks,
        [],
    )
    round_row = result["rounds"][0]
    assert [row["player"] for row in round_row["missingBloodSidePlayers"]] == ["丁"]
    assert [row["player"] for row in round_row["dispersedPlayers"]] == ["丙"]
    assert round_row["reliableRemovalPositionCount"] == 3


def test_toxic_droplet_round_marks_noxious_blast_as_missed_orb():
    fight = {"startTime": 0, "endTime": 40_000}
    casts = [event(5_000, TOXIC_DROPLETS_CAST_ID, "cast")]
    damage = [
        event(8_000, TOXIC_DROPLETS_HIT_ID, "damage", 1),
        event(20_000, NOXIOUS_BLAST_ID, "damage", 1),
        event(20_000, NOXIOUS_BLAST_ID, "damage", 2),
    ]
    players = {1: {"id": 1, "name": "甲"}, 2: {"id": 2, "name": "乙"}}
    friendly_casts = [{"timestamp": 7_000, "abilityGameID": 642, "type": "cast", "sourceID": 2}]
    result = analyze_toxic_droplets(
        fight, {1: "甲", 2: "乙"}, casts, damage, players, friendly_casts
    )
    assert result["missedRoundCount"] == 1
    assert result["rounds"][0]["blastVictimCount"] == 2
    assert result["rounds"][0]["noHitPlayers"][0]["player"] == "乙"
    assert result["rounds"][0]["noHitPlayers"][0]["immunityCandidate"] is True
