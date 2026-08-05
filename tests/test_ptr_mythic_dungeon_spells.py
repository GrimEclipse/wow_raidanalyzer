import json
from pathlib import Path

from tools.discover_ptr_mythic_dungeon_spells import (
    PTR_SAMPLES,
    _ability_id,
    _dedupe_events,
    _player_consumable_evidence,
)


ROOT = Path(__file__).resolve().parents[1]


def test_ptr_samples_cover_the_seven_non_blinding_vale_dungeons():
    assert len(PTR_SAMPLES) == 7
    assert {sample["encounterId"] for sample in PTR_SAMPLES.values()} == {
        62993, 62825, 111762, 62813, 162521, 111877, 62923,
    }
    assert 62859 not in {sample["encounterId"] for sample in PTR_SAMPLES.values()}


def test_ability_id_supports_current_and_legacy_wcl_event_shapes():
    assert _ability_id({"abilityGameID": 1236616}) == 1236616
    assert _ability_id({"ability": {"gameID": 1236994}}) == 1236994


def test_dedupe_only_removes_exact_page_boundary_duplicates():
    base = {
        "timestamp": 1000,
        "type": "applydebuff",
        "sourceID": 10,
        "targetID": 1,
        "abilityGameID": 123,
    }
    second_target = {**base, "targetID": 2}
    assert _dedupe_events([base, dict(base), second_target]) == [base, second_target]


def test_player_consumables_are_derived_from_observed_cast_and_buff_names():
    events = [
        {"type": "cast", "abilityGameID": 1236616, "sourceID": 1},
        {"type": "applybuff", "abilityGameID": 1236616, "sourceID": 1, "targetID": 1},
        {"type": "cast", "abilityGameID": 999, "sourceID": 1},
    ]
    evidence = _player_consumable_evidence(
        events[:1] + events[2:],
        events[1:2],
        {1: {"id": 1, "name": "Player"}},
        {},
        {
            1236616: {"name": "Light's Potential", "nameZh": "圣光潜力"},
            999: {"name": "Unrelated", "nameZh": "无关技能"},
        },
    )
    assert evidence == [{
        "id": 1236616,
        "name": "Light's Potential",
        "nameZh": "圣光潜力",
        "eventTypes": {"applybuff": 1, "cast": 1},
        "players": [{"id": 1, "name": "Player", "nameZh": "Player"}],
    }]


def test_generated_evidence_is_strictly_ptr_zone_56():
    path = ROOT / "data" / "mythic_dungeon_ptr_zone56_boss_evidence.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["source"] == {
        "provider": "Warcraft Logs",
        "zoneId": 56,
        "zoneName": "Mythic+ Season 2 (PTR)",
        "partitionId": 1,
        "partitionName": "PTR",
        "difficultyId": 10,
    }
    assert len(document["dungeons"]) == 7
    assert all(dungeon["bossPulls"] for dungeon in document["dungeons"])
    observed = {
        row["id"]
        for dungeon in document["dungeons"]
        for row in dungeon["playerConsumableEvidence"]
    }
    assert {1236616, 1236994} <= observed
