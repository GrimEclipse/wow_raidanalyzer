"""Collect auditable Boss-spell evidence from selected PTR Mythic+ clears."""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analyzer_core.wcl_api import WclClient  # noqa: E402

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

ZONE_ID = 56
DIFFICULTY_ID = 10
CN_WCL_BASE_URL = "https://cn.warcraftlogs.com"

# Highest completed public samples found by scanning the first three pages of
# reportData.reports(zoneID: 56) on 2026-08-05. The report zone, difficulty and
# kill flag are revalidated every time the collector runs.
PTR_SAMPLES = {
    "altar_of_fangs": {
        "name": "Altar of Fangs", "nameZh": "毒牙祭坛",
        "encounterId": 62993, "reportCode": "t9F4ndwHpagv6Lyf", "fightId": 2,
    },
    "den_of_nalorakk": {
        "name": "Den of Nalorakk", "nameZh": "纳罗拉克的洞穴",
        "encounterId": 62825, "reportCode": "cRwKAHb3NFLVvrt6", "fightId": 3,
    },
    "kings_rest": {
        "name": "Kings' Rest", "nameZh": "诸王之眠",
        "encounterId": 111762, "reportCode": "KfrDbzGCHAcxT2pB", "fightId": 22,
    },
    "murder_row": {
        "name": "Murder Row", "nameZh": "密谋小径",
        "encounterId": 62813, "reportCode": "RPc7YhFvHQkbXqC6", "fightId": 3,
    },
    "ruby_life_pools": {
        "name": "Ruby Life Pools", "nameZh": "红玉新生法池",
        "encounterId": 162521, "reportCode": "2g8vZzCdqyhD6kc1", "fightId": 1,
    },
    "temple_of_sethraliss": {
        "name": "Temple of Sethraliss", "nameZh": "塞塔里斯神庙",
        "encounterId": 111877, "reportCode": "PJbqH3xvcFhjDymY", "fightId": 10,
    },
    "voidscar_arena": {
        "name": "Voidscar Arena", "nameZh": "虚空之痕竞技场",
        "encounterId": 62923, "reportCode": "t9F4ndwHpagv6Lyf", "fightId": 4,
    },
}

PLAYER_CONSUMABLE_NAMES = {
    "Light's Potential", "圣光潜力",
    "Potion of Recklessness", "鲁莽药水",
    "Unbridled Fury", "Potion of Unbridled Fury", "无拘之怒", "无拘之怒药水",
}

REPORT_QUERY = """
query($code: String!, $fightIDs: [Int]) {
  reportData { report(code: $code) {
    title startTime visibility zone { id name }
    masterData(translate: true) {
      actors { id name type subType gameID petOwner }
      abilities { gameID name }
    }
    fights(fightIDs: $fightIDs, translate: true) {
      id name encounterID difficulty kill startTime endTime keystoneLevel keystoneTime
      dungeonPulls {
        id name encounterID kill startTime endTime
        enemyNPCs { id gameID minimumInstanceID maximumInstanceID }
      }
    }
  } }
}
"""

LOCALIZED_QUERY = """
query($code: String!, $fightIDs: [Int]) {
  reportData { report(code: $code) {
    masterData(translate: true) {
      actors { id name type subType gameID petOwner }
      abilities { gameID name }
    }
    fights(fightIDs: $fightIDs, translate: true) {
      id name dungeonPulls { id name }
    }
  } }
}
"""


def _ability_id(event: dict) -> int:
    ability = event.get("ability") or {}
    return int(event.get("abilityGameID") or ability.get("gameID") or ability.get("guid") or 0)


def _dedupe_events(events: list[dict]) -> list[dict]:
    """Remove exact API page-boundary duplicates without merging real targets."""
    result = []
    seen = set()
    for event in events:
        key = (
            event.get("timestamp"), event.get("type"),
            event.get("sourceID"), event.get("sourceInstance"),
            event.get("targetID"), event.get("targetInstance"),
            _ability_id(event), event.get("extraAbilityGameID"),
            event.get("amount"), event.get("hitType"),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(event)
    return result


def _actor_name(actor_id: int, actors: dict[int, dict], localized: dict[int, dict]) -> tuple[str, str]:
    original = actors.get(actor_id) or {}
    translated = localized.get(actor_id) or {}
    name = original.get("name") or f"Actor {actor_id}"
    return name, translated.get("name") or name


def _event_summary(events: list[dict], pull_start: int, actors: dict[int, dict], localized: dict[int, dict]) -> dict:
    event_types = Counter(row.get("type") or "unknown" for row in events)
    source_ids = sorted({int(row.get("sourceID") or 0) for row in events if row.get("sourceID")})
    target_ids = sorted({int(row.get("targetID") or 0) for row in events if row.get("targetID")})
    timestamps = [int(row.get("timestamp") or 0) for row in events]
    return {
        "eventCount": len(events),
        "eventTypes": dict(sorted(event_types.items())),
        "sourceActors": [
            {"id": actor_id, "name": _actor_name(actor_id, actors, localized)[0], "nameZh": _actor_name(actor_id, actors, localized)[1]}
            for actor_id in source_ids
        ],
        "targetActors": [
            {"id": actor_id, "name": _actor_name(actor_id, actors, localized)[0], "nameZh": _actor_name(actor_id, actors, localized)[1]}
            for actor_id in target_ids
        ],
        "firstMs": min(timestamps) - pull_start if timestamps else None,
        "lastMs": max(timestamps) - pull_start if timestamps else None,
    }


def _linked_debuffs(casts: list[dict], debuffs: list[dict], ability_names: dict[int, dict]) -> list[dict]:
    anchors = [row for row in casts if row.get("type") == "cast"]
    if not anchors:
        anchors = [row for row in casts if row.get("type") == "begincast"]
    grouped: dict[int, dict] = {}
    for anchor in anchors:
        timestamp = int(anchor.get("timestamp") or 0)
        nearby = [
            row for row in debuffs
            if row.get("type") in {"applydebuff", "applydebuffstack"}
            and -100 <= int(row.get("timestamp") or 0) - timestamp <= 3500
        ]
        by_ability: dict[int, list[dict]] = defaultdict(list)
        for event in nearby:
            by_ability[_ability_id(event)].append(event)
        for ability_id, rows in by_ability.items():
            entry = grouped.setdefault(ability_id, {
                "abilityId": ability_id,
                "name": (ability_names.get(ability_id) or {}).get("name") or f"Spell {ability_id}",
                "nameZh": (ability_names.get(ability_id) or {}).get("nameZh") or (ability_names.get(ability_id) or {}).get("name") or f"Spell {ability_id}",
                "matchedCastCount": 0,
                "targetCounts": [],
                "delaysMs": [],
            })
            entry["matchedCastCount"] += 1
            entry["targetCounts"].append(len({int(row.get("targetID") or 0) for row in rows if row.get("targetID")}))
            entry["delaysMs"].append(min(int(row.get("timestamp") or 0) - timestamp for row in rows))
    return sorted(grouped.values(), key=lambda row: (-row["matchedCastCount"], row["abilityId"]))[:8]


def _player_consumable_evidence(
    casts: list[dict],
    buffs: list[dict],
    actors: dict[int, dict],
    localized_actors: dict[int, dict],
    ability_names: dict[int, dict],
) -> list[dict]:
    """Summarize observed offensive-potion Cast/Buff chains in the selected clear."""
    by_ability: dict[int, list[dict]] = defaultdict(list)
    for event in casts + buffs:
        ability_id = _ability_id(event)
        names = ability_names.get(ability_id) or {}
        if names.get("name") in PLAYER_CONSUMABLE_NAMES or names.get("nameZh") in PLAYER_CONSUMABLE_NAMES:
            by_ability[ability_id].append(event)

    result = []
    for ability_id, events in sorted(by_ability.items()):
        names = ability_names.get(ability_id) or {}
        actor_ids = sorted({
            int(event.get("sourceID") or event.get("targetID") or 0)
            for event in events
            if event.get("sourceID") or event.get("targetID")
        })
        result.append({
            "id": ability_id,
            "name": names.get("name") or f"Spell {ability_id}",
            "nameZh": names.get("nameZh") or names.get("name") or f"Spell {ability_id}",
            "eventTypes": dict(sorted(Counter(event.get("type") or "unknown" for event in events).items())),
            "players": [
                {
                    "id": actor_id,
                    "name": _actor_name(actor_id, actors, localized_actors)[0],
                    "nameZh": _actor_name(actor_id, actors, localized_actors)[1],
                }
                for actor_id in actor_ids
            ],
        })
    return result


def _build_pull(
    pull: dict,
    pull_name_zh: str,
    casts: list[dict],
    debuffs: list[dict],
    buffs: list[dict],
    damage: list[dict],
    actors: dict[int, dict],
    localized_actors: dict[int, dict],
    ability_names: dict[int, dict],
) -> dict:
    start = int(pull["startTime"])
    end = int(pull["endTime"])
    actor_ids = {int(row.get("id") or 0) for row in pull.get("enemyNPCs") or []}
    pull_casts = [row for row in casts if start <= int(row.get("timestamp") or 0) <= end and int(row.get("sourceID") or 0) in actor_ids]
    pull_debuffs = [row for row in debuffs if start <= int(row.get("timestamp") or 0) <= end and int(row.get("sourceID") or 0) in actor_ids]
    pull_buffs = [row for row in buffs if start <= int(row.get("timestamp") or 0) <= end and int(row.get("targetID") or 0) in actor_ids]
    pull_damage = [row for row in damage if int(row.get("sourceID") or 0) in actor_ids]

    by_ability: dict[int, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for category, rows in (("casts", pull_casts), ("debuffs", pull_debuffs), ("buffs", pull_buffs), ("damage", pull_damage)):
        for event in rows:
            ability_id = _ability_id(event)
            if ability_id:
                by_ability[ability_id][category].append(event)

    abilities = []
    for ability_id, categories in by_ability.items():
        names = ability_names.get(ability_id) or {}
        row = {
            "id": ability_id,
            "name": names.get("name") or f"Spell {ability_id}",
            "nameZh": names.get("nameZh") or names.get("name") or f"Spell {ability_id}",
        }
        for category in ("casts", "debuffs", "buffs", "damage"):
            events = categories.get(category) or []
            if events:
                row[category] = _event_summary(events, start, actors, localized_actors)
                if category == "damage":
                    row[category]["totalAmount"] = sum(int(event.get("amount") or 0) for event in events)
        if categories.get("casts"):
            row["nearbyDebuffs"] = _linked_debuffs(categories["casts"], pull_debuffs, ability_names)
        abilities.append(row)

    abilities.sort(key=lambda row: (
        0 if row.get("casts") else 1 if row.get("debuffs") else 2 if row.get("buffs") else 3,
        row["id"],
    ))
    return {
        "id": int(pull.get("id") or 0),
        "name": pull.get("name") or "",
        "nameZh": pull_name_zh or pull.get("name") or "",
        "encounterId": int(pull.get("encounterID") or 0),
        "kill": bool(pull.get("kill")),
        "startTime": start,
        "endTime": end,
        "durationMs": end - start,
        "actors": [
            {
                "id": actor_id,
                "gameId": int((actors.get(actor_id) or {}).get("gameID") or 0),
                "name": _actor_name(actor_id, actors, localized_actors)[0],
                "nameZh": _actor_name(actor_id, actors, localized_actors)[1],
                "instances": [int(npc.get("minimumInstanceID") or 1), int(npc.get("maximumInstanceID") or npc.get("minimumInstanceID") or 1)],
            }
            for npc in pull.get("enemyNPCs") or []
            for actor_id in [int(npc.get("id") or 0)]
        ],
        "abilities": abilities,
    }


def collect_sample(key: str, sample: dict) -> dict:
    client = WclClient()
    report = client.graphql(REPORT_QUERY, {"code": sample["reportCode"], "fightIDs": [sample["fightId"]]})
    fight = next((row for row in report.get("fights") or [] if int(row.get("id") or 0) == sample["fightId"]), None)
    if not fight:
        raise RuntimeError(f"{key}: missing fight {sample['fightId']}")
    if int((report.get("zone") or {}).get("id") or 0) != ZONE_ID:
        raise RuntimeError(f"{key}: report is not PTR zone {ZONE_ID}")
    if int(fight.get("difficulty") or 0) != DIFFICULTY_ID or not fight.get("kill"):
        raise RuntimeError(f"{key}: selected fight is not a completed PTR dungeon")
    if int(fight.get("encounterID") or 0) != sample["encounterId"]:
        raise RuntimeError(f"{key}: unexpected encounter ID")

    cn_client = WclClient()
    cn_client.base_url = CN_WCL_BASE_URL
    cn_client._token = client.token()
    localized = cn_client.graphql(LOCALIZED_QUERY, {"code": sample["reportCode"], "fightIDs": [sample["fightId"]]})

    master = report.get("masterData") or {}
    localized_master = localized.get("masterData") or {}
    actors = {int(row.get("id") or 0): row for row in master.get("actors") or []}
    localized_actors = {int(row.get("id") or 0): row for row in localized_master.get("actors") or []}
    localized_abilities = {int(row.get("gameID") or 0): row.get("name") for row in localized_master.get("abilities") or []}
    ability_names = {
        int(row.get("gameID") or 0): {
            "name": row.get("name"),
            "nameZh": localized_abilities.get(int(row.get("gameID") or 0)) or row.get("name"),
        }
        for row in master.get("abilities") or []
        if row.get("gameID")
    }
    localized_fight = next((row for row in localized.get("fights") or [] if int(row.get("id") or 0) == sample["fightId"]), {})
    pull_names_zh = {
        int(row.get("id") or 0): row.get("name")
        for row in localized_fight.get("dungeonPulls") or []
    }

    casts = _dedupe_events(client.events(sample["reportCode"], "Casts", fight, hostility_type="Enemies"))
    debuffs = _dedupe_events(client.events(sample["reportCode"], "Debuffs", fight, hostility_type="Friendlies"))
    buffs = _dedupe_events(client.events(sample["reportCode"], "Buffs", fight, hostility_type="Enemies"))
    friendly_casts = _dedupe_events(client.events(sample["reportCode"], "Casts", fight, hostility_type="Friendlies"))
    friendly_buffs = _dedupe_events(client.events(sample["reportCode"], "Buffs", fight, hostility_type="Friendlies"))
    boss_pulls = [row for row in fight.get("dungeonPulls") or [] if int(row.get("encounterID") or 0)]
    pulls = []
    for pull in boss_pulls:
        damage = _dedupe_events(client.events(
            sample["reportCode"], "DamageDone", fight,
            start_time=int(pull["startTime"]), end_time=int(pull["endTime"]),
            hostility_type="Enemies",
        ))
        pulls.append(_build_pull(
            pull,
            pull_names_zh.get(int(pull.get("id") or 0), pull.get("name") or ""),
            casts, debuffs, buffs, damage, actors, localized_actors, ability_names,
        ))

    return {
        "key": key,
        "name": sample["name"],
        "nameZh": sample["nameZh"],
        "reportCode": sample["reportCode"],
        "reportUrl": f"https://www.warcraftlogs.com/reports/{sample['reportCode']}?fight={sample['fightId']}",
        "fightId": sample["fightId"],
        "encounterId": sample["encounterId"],
        "keystoneLevel": int(fight.get("keystoneLevel") or 0),
        "durationMs": int(fight["endTime"]) - int(fight["startTime"]),
        "playerConsumableEvidence": _player_consumable_evidence(
            friendly_casts, friendly_buffs, actors, localized_actors, ability_names,
        ),
        "bossPulls": pulls,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "data" / "mythic_dungeon_ptr_zone56_boss_evidence.json",
    )
    parser.add_argument("--dungeon", choices=sorted(PTR_SAMPLES))
    args = parser.parse_args()
    selected = {args.dungeon: PTR_SAMPLES[args.dungeon]} if args.dungeon else PTR_SAMPLES
    documents = []
    for key, sample in selected.items():
        print(f"collecting {key} {sample['reportCode']} fight {sample['fightId']}...", flush=True)
        documents.append(collect_sample(key, sample))
    output = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": {
            "provider": "Warcraft Logs",
            "zoneId": ZONE_ID,
            "zoneName": "Mythic+ Season 2 (PTR)",
            "partitionId": 1,
            "partitionName": "PTR",
            "difficultyId": DIFFICULTY_ID,
        },
        "dungeons": documents,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {args.output} ({len(documents)} dungeons)", flush=True)


if __name__ == "__main__":
    main()
