"""Correlate targetless enemy casts with nearby player Debuff applications."""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analyzer_core.wcl_api import WclClient  # noqa: E402
from tools.export_mythic_dungeon_timeline import METADATA_QUERY  # noqa: E402

warnings.filterwarnings("ignore", message="Unverified HTTPS request")


def ability_id(event: dict) -> int:
    return int((event.get("ability") or {}).get("gameID") or event.get("abilityGameID") or 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True)
    parser.add_argument("--fight", type=int, required=True)
    parser.add_argument("--casts", required=True, help="comma-separated cast spell IDs")
    parser.add_argument("--tolerance", type=int, default=1000)
    args = parser.parse_args()

    selected = {int(value) for value in args.casts.split(",") if value.strip()}
    client = WclClient()
    report = client.graphql(METADATA_QUERY, {"code": args.report, "fightIDs": [args.fight]})
    fight = next(row for row in report["fights"] if int(row["id"]) == args.fight)
    casts = [
        row for row in client.events(args.report, "Casts", fight, hostility_type="Enemies")
        if ability_id(row) in selected and row.get("type") in {"begincast", "cast"}
    ]
    debuffs = [
        row for row in client.events(args.report, "Debuffs", fight, hostility_type="Friendlies")
        if row.get("type") == "applydebuff"
    ]
    grouped = defaultdict(lambda: {"castTimes": set(), "deltas": [], "targets": set()})
    for cast in casts:
        timestamp = int(cast.get("timestamp") or 0)
        for debuff in debuffs:
            delta = int(debuff.get("timestamp") or 0) - timestamp
            if abs(delta) > args.tolerance:
                continue
            key = (ability_id(cast), cast["type"], ability_id(debuff))
            grouped[key]["castTimes"].add(timestamp)
            grouped[key]["deltas"].append(delta)
            grouped[key]["targets"].add(int(debuff.get("targetID") or 0))
    result = []
    for (cast_id, event_type, aura_id), row in grouped.items():
        result.append({
            "castId": cast_id,
            "castEventType": event_type,
            "auraId": aura_id,
            "matchedCasts": len(row["castTimes"]),
            "applications": len(row["deltas"]),
            "targetCount": len(row["targets"]),
            "deltaRangeMs": [min(row["deltas"]), max(row["deltas"])],
        })
    result.sort(key=lambda row: (-row["matchedCasts"], abs(row["deltaRangeMs"][0]), row["auraId"]))
    print(json.dumps({
        "report": args.report,
        "fight": args.fight,
        "castCounts": {
            f"{cast_id}:{event_type}": sum(1 for row in casts if ability_id(row) == cast_id and row["type"] == event_type)
            for cast_id in sorted(selected)
            for event_type in ("begincast", "cast")
        },
        "candidates": result[:100],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
