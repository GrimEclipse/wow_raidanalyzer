"""Export one real WCL Mythic+ run into the route-timeline JSON contract."""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analyzer_core.mythic_dungeon_timeline import (  # noqa: E402
    VOID_METAMORPHOSIS_ID,
    build_dungeon_document,
)
from analyzer_core.mythic_dungeon_configs import DUNGEON_CONFIGS, dungeon_config  # noqa: E402
from analyzer_core.wcl_api import WclClient  # noqa: E402

warnings.filterwarnings("ignore", message="Unverified HTTPS request")


METADATA_QUERY = """
query($code: String!, $fightIDs: [Int]) {
  reportData {
    report(code: $code) {
      title
      startTime
      original: masterData {
        actors { id name type subType gameID petOwner }
        abilities { gameID name icon }
      }
      localized: masterData(translate: true) {
        actors { id name type subType gameID petOwner }
      }
      playerDetails(fightIDs: $fightIDs, includeCombatantInfo: true, translate: true)
      fights {
        id name encounterID difficulty kill startTime endTime
        keystoneLevel keystoneTime friendlyPlayers
        dungeonPulls {
          id name encounterID kill startTime endTime x y
          enemyNPCs {
            id gameID minimumInstanceID maximumInstanceID
            minimumInstanceGroupID maximumInstanceGroupID
          }
        }
      }
    }
  }
}
"""


def _player_details(report: dict) -> dict:
    value = report.get("playerDetails") or {}
    if isinstance(value, dict) and "data" in value:
        value = value.get("data") or {}
    if isinstance(value, dict) and "playerDetails" in value:
        value = value.get("playerDetails") or {}
    return value if isinstance(value, dict) else {}


def export(report_code: str, fight_id: int, output: Path, dungeon_key: str = "skyreach") -> dict:
    client = WclClient()
    config = dungeon_config(dungeon_key)
    report = client.graphql(METADATA_QUERY, {"code": report_code, "fightIDs": [fight_id]})
    fight = next((row for row in report.get("fights") or [] if int(row.get("id") or 0) == fight_id), None)
    if not fight:
        raise RuntimeError(f"report {report_code} does not contain fight {fight_id}")
    if not fight.get("dungeonPulls"):
        raise RuntimeError(f"fight {fight_id} is not a WCL Mythic+ dungeon fight")
    aliases = {name.lower() for name in config.get("aliases") or []}
    if aliases and (fight.get("name") or "").lower() not in aliases:
        raise RuntimeError(f"fight {fight_id} is {fight.get('name')}, not {config.get('officialNameZh')}")

    hostile_casts = client.events(report_code, "Casts", fight, hostility_type="Enemies")
    friendly_casts = client.events(report_code, "Casts", fight, hostility_type="Friendlies")
    friendly_damage = client.events(report_code, "DamageDone", fight, hostility_type="Friendlies")
    void_meta_buffs = client.events(
        report_code,
        "Buffs",
        fight,
        hostility_type="Friendlies",
        ability_id=VOID_METAMORPHOSIS_ID,
    )
    linked_target_events = {}
    for rule in (config.get("linkedTargetCasts") or {}).values():
        aura_id = int(rule.get("targetAuraId") or 0)
        if not aura_id or aura_id in linked_target_events:
            continue
        linked_target_events[aura_id] = client.events(
            report_code,
            "Debuffs",
            fight,
            hostility_type="Friendlies",
            ability_id=aura_id,
        )

    document = build_dungeon_document(
        report_code=report_code,
        report=report,
        fight=fight,
        actors_original=(report.get("original") or {}).get("actors") or [],
        actors_localized=(report.get("localized") or {}).get("actors") or [],
        abilities_original=[
            {"id": row.get("gameID"), **row}
            for row in (report.get("original") or {}).get("abilities") or []
        ],
        player_details=_player_details(report),
        hostile_casts=hostile_casts,
        friendly_casts=friendly_casts,
        friendly_damage=friendly_damage,
        void_meta_buffs=void_meta_buffs,
        linked_target_events=linked_target_events,
        config=config,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default="xpYfcXrBnkP8W1Ka")
    parser.add_argument("--fight", type=int, default=2)
    parser.add_argument("--dungeon", choices=sorted(DUNGEON_CONFIGS), default="skyreach")
    parser.add_argument("--list-fights", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
    )
    args = parser.parse_args()
    if args.list_fights:
        client = WclClient()
        report = client.graphql(METADATA_QUERY, {"code": args.report, "fightIDs": [args.fight]})
        print(json.dumps([
            {
                "id": row.get("id"),
                "name": row.get("name"),
                "kill": row.get("kill"),
                "keystoneLevel": row.get("keystoneLevel"),
                "keystoneTime": row.get("keystoneTime"),
                "pulls": len(row.get("dungeonPulls") or []),
            }
            for row in report.get("fights") or []
            if row.get("dungeonPulls")
        ], ensure_ascii=False, indent=2))
        return
    output = args.output or ROOT / "assets" / "samples" / f"mythic_dungeon_{args.dungeon}_{args.report}_fight{args.fight}.json"
    document = export(args.report, args.fight, output, args.dungeon)
    print(json.dumps({
        "output": str(output),
        "dungeon": document["dungeon"],
        "team": document["team"],
        "pulls": len(document["pulls"]),
        "timelineEvents": sum(len(row["timeline"]) for row in document["pulls"]),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
