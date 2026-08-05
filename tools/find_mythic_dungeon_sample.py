"""Inspect WCL Mythic+ encounter rankings for public sample reports."""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analyzer_core.wcl_api import WclClient  # noqa: E402

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


ZONE_QUERY = """
query($zoneID: Int!) {
  worldData { zone(id: $zoneID) { id name encounters { id name } } }
}
"""

RANKING_QUERY = """
query($encounterID: Int!, $page: Int, $bracket: Int) {
  worldData {
    encounter(id: $encounterID) {
      id name
      fightRankings(page: $page, bracket: $bracket, leaderboard: LogsOnly)
    }
  }
}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zone", type=int, default=47)
    parser.add_argument("--encounter", type=int)
    parser.add_argument("--bracket", type=int)
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    client = WclClient()
    if not args.encounter:
        data = client.graphql_data(ZONE_QUERY, {"zoneID": args.zone})
        print(json.dumps(data["worldData"]["zone"], ensure_ascii=False, indent=2))
        return
    data = client.graphql_data(RANKING_QUERY, {
        "encounterID": args.encounter,
        "bracket": args.bracket,
        "page": args.page,
    })
    encounter = data["worldData"]["encounter"]
    if args.full:
        print(json.dumps(encounter, ensure_ascii=False, indent=2))
        return
    payload = encounter.get("fightRankings") or {}
    rankings = payload.get("rankings") if isinstance(payload, dict) else payload
    compact = []
    for row in (rankings or [])[: max(args.limit, 0)]:
        report = row.get("report") or {}
        compact.append({
            "keyLevel": row.get("bracketData"),
            "rank": row.get("rank"),
            "score": row.get("score"),
            "duration": row.get("duration"),
            "reportCode": report.get("code"),
            "fightId": report.get("fightID"),
            "team": [member.get("name") for member in (row.get("roles") or {}).get("tanks", [])]
                + [member.get("name") for member in (row.get("roles") or {}).get("healers", [])]
                + [member.get("name") for member in (row.get("roles") or {}).get("dps", [])],
        })
    print(json.dumps({
        "encounterId": encounter.get("id"),
        "encounterName": encounter.get("name"),
        "page": payload.get("page") if isinstance(payload, dict) else args.page,
        "hasMorePages": payload.get("hasMorePages") if isinstance(payload, dict) else None,
        "rankings": compact,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
