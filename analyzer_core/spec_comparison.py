"""Shared orchestration for one-Fight, one-specialization comparisons."""

from __future__ import annotations

from datetime import datetime, timezone

from analyzer_core.wcl_api import WclClient
from spec_plugins import get_spec_analyzer


ABILITY_QUERY = """
query($code: String!) {
  reportData { report(code: $code) {
    masterData { abilities { gameID name type icon } }
  } }
}
"""


def collect_combatant_bundle(
    report_code: str,
    fight_id: int,
    source_id: int,
    *,
    label: str,
    role: str,
    client: WclClient | None = None,
) -> dict:
    client = client or WclClient()
    report = client.report_fights(report_code)
    fight = next((row for row in report.get("fights") or [] if int(row["id"]) == int(fight_id)), None)
    if not fight:
        raise ValueError(f"Report {report_code} 中不存在 Fight {fight_id}")
    actor = next((row for row in client.actors(report_code) if int(row["id"]) == int(source_id)), None)
    if not actor:
        raise ValueError(f"Report {report_code} 中不存在来源角色 {source_id}")
    abilities = (
        client.graphql_data(ABILITY_QUERY, {"code": report_code})
        .get("reportData", {}).get("report", {}).get("masterData", {}).get("abilities", [])
    )
    ability_names = {int(row["gameID"]): row["name"] for row in abilities}
    ability_icons = {
        int(row["gameID"]): str(row.get("icon") or "")
        for row in abilities
        if row.get("icon")
    }
    combatant_info = next(
        (
            row for row in client.events(report_code, "CombatantInfo", fight)
            if int(row.get("sourceID") or 0) == int(source_id)
        ),
        {},
    )
    return {
        "identity": {
            "role": role,
            "label": label,
            "playerName": actor.get("name"),
            "reportCode": report_code,
            "fightId": int(fight_id),
            "sourceId": int(source_id),
            "reportTitle": report.get("title"),
            "encounterName": fight.get("name"),
            "reportUrl": f"https://cn.warcraftlogs.com/reports/{report_code}?fight={fight_id}&type=casts&source={source_id}",
            "resourceUrl": f"https://cn.warcraftlogs.com/reports/{report_code}?fight={fight_id}&type=resources&source={source_id}&spell=109",
        },
        "spec": "Holy" if actor.get("subType") == "Paladin" else "Unknown",
        "actor": actor,
        "fight": fight,
        "abilityNames": ability_names,
        "abilityIcons": ability_icons,
        "combatantInfo": combatant_info,
        "casts": client.events(report_code, "Casts", fight, source_id=source_id, include_resources=True),
        # Source stream contains both self-buffs and managed buffs placed on
        # other players (for example Dawnlight).  Plugins filter locally.
        "buffs": client.events(report_code, "Buffs", fight, source_id=source_id),
        "resources": client.events(report_code, "Resources", fight, source_id=source_id),
    }


def build_spec_comparison(primary: dict, benchmark: dict, *, options: dict | None = None) -> dict:
    primary_class = str((primary.get("actor") or {}).get("subType") or "Unknown")
    primary_spec = str(primary.get("spec") or "Unknown")
    analyzer = get_spec_analyzer(primary_class, primary_spec)
    document = analyzer(primary, benchmark, options or {})
    document["generatedAt"] = datetime.now(timezone.utc).isoformat()
    document["encounter"] = {
        "name": (primary.get("fight") or {}).get("name"),
        "primaryFightId": (primary.get("fight") or {}).get("id"),
        "benchmarkFightId": (benchmark.get("fight") or {}).get("id"),
    }
    return document
