from boss_plugins.venomous_abyss.vashnik import analyze_vashnik, _distinct_pillar_matches


def evidence():
    players = {i: {"id": i, "name": f"P{i}", "role": "range-dps"} for i in range(1, 6)}
    markers = [{"type": "worldmarkerplaced", "timestamp": 0, "icon": i,
                "x": 30000 + i * 1000, "y": 42000, "mapID": 3004} for i in players]
    raw = {"casts": [{"type": "cast", "timestamp": 20000, "abilityGameID": 1284663}],
           "damage": [], "deaths": [], "debuffs": [], "worldMarkerEvents": markers,
           "worldMarkersComplete": True}
    for apply in (1000, 30000, 60000):
        for i in players:
            raw["debuffs"].extend([
                {"type": "applydebuff", "timestamp": apply, "abilityGameID": 1281913, "targetID": i},
                {"type": "removedebuff", "timestamp": apply + 6000 + i, "abilityGameID": 1281913, "targetID": i,
                 "targetResources": {"x": 30000 + i * 1000, "y": 42000}},
            ])
    return players, raw


def analyze(players, raw):
    return analyze_vashnik({"id": 1, "startTime": 0, "endTime": 100000}, {}, players, raw)


def test_first_wave_after_imbibe_accepts_any_five_distinct_pillars():
    players, raw = evidence()
    # Reverse personal destinations; no player-to-marker assignment exists.
    for row in raw["debuffs"]:
        if row["type"] == "removedebuff":
            row["targetResources"]["x"] = 36000 - row["targetID"] * 1000
    result = analyze(players, raw)["plagueWaves"]
    assert [r["checked"] for r in result["rounds"]] == [False, True, False]
    assert all(r["pillarOutcome"] == "已到不同光柱" for r in result["records"] if r["checked"])


def test_duplicate_occupants_both_require_review_and_far_player_is_returned():
    players, raw = evidence()
    for row in raw["debuffs"]:
        if row["type"] == "removedebuff" and 36000 <= row["timestamp"] < 37000:
            if row["targetID"] == 2:
                row["targetResources"]["x"] = 31000
            if row["targetID"] == 5:
                row["targetResources"]["y"] = 45000
    result = analyze(players, raw)["plagueWaves"]["rounds"][1]
    assert result["problemPlayers"] == ["P1", "P2", "P5"]
    assert [r["pillarOutcome"] for r in result["players"]][:2] == ["重复占位 · 待复核"] * 2
    assert result["players"][4]["pillarOutcome"] == "未到光柱"


def test_partial_marker_history_never_claims_missing_markers_are_absent():
    players, raw = evidence()
    raw.pop("worldMarkersComplete")
    raw["worldMarkerEvents"] = raw["worldMarkerEvents"][:1]
    result = analyze(players, raw)["plagueWaves"]["rounds"][1]
    assert not result["markerEvidenceComplete"]
    assert not result["problemPlayers"]
    assert result["reviewPlayers"] == ["P2", "P3", "P4", "P5"]


def test_marker_move_removal_and_guild_identity_are_respected():
    players, raw = evidence()
    raw["reportID"] = "anotherGuild"
    raw["worldMarkerEvents"].extend([
        {"type": "worldmarkerremoved", "timestamp": 25000, "icon": 1},
        {"type": "worldmarkerplaced", "timestamp": 26000, "icon": 1, "x": 31000, "y": 45000},
        {"type": "worldmarkerremoved", "timestamp": 35000, "icon": 2},
    ])
    round_row = analyze(players, raw)["plagueWaves"]["rounds"][1]
    assert len(round_row["pillars"]) == 4
    assert next(p for p in round_row["pillars"] if p["icon"] == 1)["y"] == 45000
    assert not any(p["estimated"] for p in round_row["pillars"])


def test_matching_search_is_bounded_by_eight_markers_for_large_odd_batches():
    rows = [{"position": {"x": 0, "y": 0}} for _ in range(30)]
    pillars = [{"icon": i, "x": 0, "y": 0} for i in range(1, 9)]
    candidates, possibilities, count = _distinct_pillar_matches(rows, pillars)
    assert count == 8
    assert all(None in choices and len(choices) == 9 for choices in possibilities)


def test_dead_or_stale_samples_do_not_consume_a_pillar_or_create_faults():
    players, raw = evidence()
    raw["analysisOptions"] = {"infectionReviewEnabled": False}
    raw["deaths"] = [{"type": "death", "timestamp": 36002, "targetID": 2}]
    for row in raw["debuffs"]:
        if row["type"] == "removedebuff" and 36000 < row["timestamp"] < 37000:
            if row["targetID"] == 2:
                row["targetResources"]["x"] = 31000
            if row["targetID"] == 5:
                row.pop("targetResources")
    raw["damage"] = [{"type": "damage", "timestamp": 36505, "abilityGameID": 1,
                      "targetID": 5, "targetResources": {"x": 35000, "y": 42000}}]
    row = analyze(players, raw)["plagueWaves"]["rounds"][1]
    assert row["checked"]
    assert row["players"][0]["pillarOutcome"] == "已到不同光柱"
    assert row["players"][1]["pillarOutcome"] == "死亡提前移除"
    assert row["players"][4]["pillarOutcome"] == "缺少及时坐标"
    assert not row["problemPlayers"]
