"""Print compact raw WCL events for selected spell IDs in one fight.

This is a developer evidence tool for connecting encounter-journal spell IDs
to their concrete cast, aura and damage event variants.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from boss_plugins.void_spire.crown_of_the_cosmos import fetch_events_all, get_token
from tools.wcl_zone54_discovery import ability_id, actor_maps, report_index


TABLES = {
    "casts": ("Casts", "Enemies"),
    "damage": ("DamageTaken", None),
    "debuffs": ("Debuffs", "Friendlies"),
    "buffs": ("Buffs", "Enemies"),
}


def compact_event(event, fight_start, actors, ability_names):
    source = actors.get(int(event["sourceID"])) if event.get("sourceID") is not None else {}
    target = actors.get(int(event["targetID"])) if event.get("targetID") is not None else {}
    spell_id = ability_id(event)
    return {
        "timeMs": int(event.get("timestamp") or 0) - int(fight_start),
        "type": event.get("type"),
        "spellID": spell_id,
        "spell": ability_names.get(spell_id, str(spell_id)),
        "sourceID": event.get("sourceID"),
        "source": (source or {}).get("name"),
        "targetID": event.get("targetID"),
        "target": (target or {}).get("name"),
        "stack": event.get("stack"),
        "extraAbilityGameID": event.get("extraAbilityGameID"),
        "amount": event.get("amount"),
        "unmitigatedAmount": event.get("unmitigatedAmount"),
        "hitType": event.get("hitType"),
    }


def summarize_events(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["spellID"], row["spell"])].append(row)
    result = []
    for (spell_id, spell), events in grouped.items():
        times_by_type = defaultdict(list)
        for event in events:
            times_by_type[event["type"]].append(event["timeMs"])
        result.append({
            "spellID": spell_id,
            "spell": spell,
            "eventTypes": dict(Counter(event["type"] for event in events)),
            "timesByType": {
                event_type: times[:40]
                for event_type, times in times_by_type.items()
            },
            "sources": sorted({
                event["source"] for event in events if event.get("source")
            }),
            "targets": sorted({
                event["target"] for event in events if event.get("target")
            })[:40],
        })
    return sorted(result, key=lambda row: row["spellID"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--fight", required=True, type=int)
    parser.add_argument("--ids", required=True, help="Comma-separated spell IDs")
    parser.add_argument(
        "--tables",
        default="casts,damage,debuffs,buffs",
        help=f"Comma-separated subset of: {','.join(TABLES)}",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Group by spell and print event-type timestamp lists.",
    )
    args = parser.parse_args()

    selected_ids = {int(value) for value in args.ids.split(",") if value.strip()}
    selected_tables = [value.strip() for value in args.tables.split(",") if value.strip()]
    unknown = [value for value in selected_tables if value not in TABLES]
    if unknown:
        parser.error(f"Unknown tables: {', '.join(unknown)}")

    token = get_token()
    document = report_index(token, args.report)
    fight = next(
        row for row in document.get("fights") or []
        if int(row.get("id") or 0) == args.fight
    )
    fight = {**fight, "reportID": args.report}
    actors, ability_names = actor_maps(document)
    result = {
        "reportID": args.report,
        "fightID": args.fight,
        "fight": {
            "name": fight.get("name"),
            "difficulty": fight.get("difficulty"),
            "kill": fight.get("kill"),
            "durationMs": int(fight["endTime"] - fight["startTime"]),
        },
        "events": {},
    }
    for table in selected_tables:
        data_type, hostility = TABLES[table]
        rows = fetch_events_all(
            token,
            args.report,
            data_type,
            fight,
            hostility_type=hostility,
        )
        compact_rows = [
            compact_event(event, fight["startTime"], actors, ability_names)
            for event in rows
            if ability_id(event) in selected_ids
        ]
        result["events"][table] = (
            summarize_events(compact_rows) if args.summary else compact_rows
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
