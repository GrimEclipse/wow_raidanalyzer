import json
from pathlib import Path

from analyzer_core.mythic_dungeon_timeline import build_skyreach_document, format_clock


ROOT = Path(__file__).resolve().parents[1]


def event(timestamp, event_type, ability_id, source_id, target_id=0, **extra):
    return {
        "timestamp": timestamp,
        "type": event_type,
        "abilityGameID": ability_id,
        "sourceID": source_id,
        "targetID": target_id,
        **extra,
    }


def build(**overrides):
    report = {"title": "test"}
    fight = {
        "id": 2,
        "name": "Skyreach",
        "startTime": 900,
        "endTime": 11_000,
        "keystoneTime": 10_000,
        "keystoneLevel": 24,
        "kill": True,
        "friendlyPlayers": [1, 2, 3],
        "dungeonPulls": [
            {
                "id": 1,
                "name": "Trash",
                "encounterID": 0,
                "kill": False,
                "startTime": 1_100,
                "endTime": 5_000,
                "enemyNPCs": [{"id": 10, "gameID": 100, "minimumInstanceID": 1, "maximumInstanceID": 2}],
            },
            {
                "id": 2,
                "name": "Artifact",
                "encounterID": 0,
                "kill": False,
                "startTime": 5_001,
                "endTime": 5_010,
                "enemyNPCs": [],
            },
            {
                "id": 3,
                "name": "Ranjit",
                "encounterID": 1698,
                "kill": True,
                "startTime": 6_000,
                "endTime": 10_500,
                "enemyNPCs": [{"id": 11, "gameID": 101, "minimumInstanceID": 1, "maximumInstanceID": 1}],
            },
        ],
    }
    inputs = {
        "report_code": "abc",
        "report": report,
        "fight": fight,
        "actors_original": [
            {"id": 1, "name": "Tank", "type": "Druid"},
            {"id": 2, "name": "Healer", "type": "Monk"},
            {"id": 3, "name": "DPS", "type": "DemonHunter"},
            {"id": 10, "name": "Mob", "type": "NPC", "gameID": 100},
            {"id": 11, "name": "Ranjit", "type": "NPC", "gameID": 101},
        ],
        "actors_localized": [],
        "abilities_original": [
            {"id": 1254380, "name": "Shear"},
            {"id": 22812, "name": "Barkskin"},
            {"id": 116849, "name": "Life Cocoon"},
            {"id": 1225789, "name": "Void Metamorphosis"},
            {"id": 1253538, "name": "Scorching Ray"},
        ],
        "player_details": {
            "tanks": [{"id": 1, "name": "Tank", "type": "Druid", "specs": [{"spec": "Guardian", "count": 1}]}],
            "healers": [{"id": 2, "name": "Healer", "type": "Monk", "specs": [{"spec": "Mistweaver", "count": 1}]}],
            "dps": [{"id": 3, "name": "DPS", "type": "DemonHunter", "specs": [{"spec": "Devourer", "count": 1}]}],
        },
        "hostile_casts": [
            event(1_400, "begincast", 1254380, 10, 1, sourceInstance=1),
            event(1_700, "cast", 1254380, 10, 1, sourceInstance=1),
            event(7_000, "cast", 1253538, 11),
        ],
        "friendly_casts": [
            event(1_200, "cast", 22812, 1, 1),
            event(1_300, "cast", 116849, 2, 1),
            event(1_350, "begincast", 116849, 2, 1),
        ],
        "friendly_damage": [event(1_150, "damage", 1, 1, 10, targetInstance=1)],
        "void_meta_buffs": [
            event(1_450, "applybuff", 1225789, 3, 3),
            event(1_500, "removebuff", 1225789, 3, 3),
        ],
        "scorching_ray_debuffs": [
            event(7_000, "applydebuff", 1253541, 11, 1),
            event(7_000, "applydebuff", 1253541, 11, 2),
            event(7_000, "applydebuff", 1253541, 11, 3),
        ],
    }
    inputs.update(overrides)
    return build_skyreach_document(**inputs)


def test_uses_wcl_clock_and_discards_tiny_artifact_pull():
    document = build()
    assert document["dungeon"]["durationMs"] == 10_100
    assert document["dungeon"]["keystoneTimeMs"] == 10_000
    assert len(document["pulls"]) == 2
    assert document["pulls"][0]["dungeonTime"] == "00:00.2"


def test_enemy_only_begincast_player_only_cast_and_target_rules():
    timeline = build()["pulls"][0]["timeline"]
    assert [row["kind"] for row in timeline].count("enemyBeginCast") == 1
    assert [row["kind"] for row in timeline].count("playerCast") == 2
    barkskin = next(row for row in timeline if row["ability"]["id"] == 22812)
    cocoon = next(row for row in timeline if row["ability"]["id"] == 116849)
    assert barkskin["target"] is None
    assert cocoon["target"]["name"] == "Tank"


def test_void_metamorphosis_is_reconstructed_from_counter_remove():
    state = next(row for row in build()["pulls"][0]["timeline"] if row["kind"] == "playerState")
    assert state["ability"]["id"] == 1225789
    assert state["synthetic"] is True
    assert state["target"] is None
    assert state["eventType"] == "removebuff"


def test_instant_enemy_cast_uses_linked_debuff_targets():
    event_row = next(row for row in build()["pulls"][1]["timeline"] if row["ability"]["id"] == 1253538)
    assert event_row["eventType"] == "cast"
    assert [target["name"] for target in event_row["targets"]] == ["Tank", "Healer", "DPS"]


def test_targetless_begincast_links_targets_from_its_completed_cast_and_ignores_pets():
    document = build(
        config={
            "key": "test",
            "officialNameZh": "测试副本",
            "enemyAbilities": {1254380: "无目标点名"},
            "linkedTargetCasts": {
                1254380: {
                    "displayEventType": "begincast",
                    "targetEventType": "cast",
                    "targetAuraId": 999001,
                    "toleranceMs": 100,
                },
            },
        },
        hostile_casts=[
            event(1_400, "begincast", 1254380, 10, sourceInstance=1),
            event(1_700, "cast", 1254380, 10, sourceInstance=1),
        ],
        linked_target_events={
            999001: [
                event(1_750, "applydebuff", 999001, 10, 1),
                event(1_750, "applydebuff", 999001, 10, 99),
            ],
        },
        scorching_ray_debuffs=None,
    )
    rows = [row for row in document["pulls"][0]["timeline"] if row["ability"]["id"] == 1254380]
    assert len(rows) == 1
    assert rows[0]["eventType"] == "begincast"
    assert [target["name"] for target in rows[0]["targets"]] == ["Tank"]


def test_enemy_instances_and_openers_are_preserved():
    enemies = build()["pulls"][0]["enemies"]
    assert [row["instance"] for row in enemies] == [1, 2]
    assert enemies[0]["opener"]["player"]["name"] == "Tank"
    assert enemies[1]["opener"] is None


def test_clock_format_is_tenths():
    assert format_clock(197_849) == "03:17.8"


def test_stable_sample_manifest_covers_the_season_pool():
    manifest = json.loads((ROOT / "assets" / "samples" / "mythic_dungeon_manifest.json").read_text(encoding="utf-8"))
    samples = {row["key"]: row for row in manifest["samples"]}
    assert len(samples) == 8
    assert samples["skyreach"]["reportCode"] == "xpYfcXrBnkP8W1Ka"
    assert samples["skyreach"]["keystoneLevel"] == 24
    assert samples["algethar_academy"]["keystoneLevel"] == 24
    assert samples["seat_of_the_triumvirate"]["keystoneLevel"] == 24
    assert all(row["keystoneLevel"] == 25 for key, row in samples.items() if key not in {
        "skyreach", "algethar_academy", "seat_of_the_triumvirate",
    })


def test_stable_sample_files_match_manifest_contract():
    manifest = json.loads((ROOT / "assets" / "samples" / "mythic_dungeon_manifest.json").read_text(encoding="utf-8"))
    for sample in manifest["samples"]:
        document = json.loads((ROOT / sample["file"].lstrip("/")).read_text(encoding="utf-8"))
        assert document["kind"] == "mythic-dungeon-route-timeline"
        assert document["dungeon"]["completed"] is True
        assert document["dungeon"]["keystoneLevel"] == sample["keystoneLevel"]
        assert document["source"]["reportCode"] == sample["reportCode"]
        assert document["pulls"]
