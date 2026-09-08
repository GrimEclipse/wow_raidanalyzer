"""Export a real Mythic+ run, with curated rules or an explicit observed-skill preview."""

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
from analyzer_core.mythic_dungeon_configs import dungeon_config  # noqa: E402
from analyzer_core.wcl_api import WclClient  # noqa: E402

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

CN_WCL_BASE_URL = "https://cn.warcraftlogs.com"
NPC_LOCALIZATION_BATCH_SIZE = 50


METADATA_QUERY = """
query($code: String!, $fightIDs: [Int]) {
  reportData {
    report(code: $code) {
      title
      visibility
      zone { id name }
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


def _cn_client(client: WclClient) -> WclClient:
    cn_client = WclClient()
    cn_client.base_url = CN_WCL_BASE_URL
    cn_client._token = client.token()
    return cn_client


def _cn_localized_actors(cn_client: WclClient, original: list[dict], localized: list[dict]) -> list[dict]:
    """Resolve NPC names from Warcraft Logs' Simplified Chinese game data."""
    game_ids = sorted({
        int(row.get("gameID") or 0)
        for row in original
        if row.get("type") == "NPC" and row.get("gameID")
    })
    names_by_game_id = {}
    for offset in range(0, len(game_ids), NPC_LOCALIZATION_BATCH_SIZE):
        batch = game_ids[offset:offset + NPC_LOCALIZATION_BATCH_SIZE]
        declarations = ", ".join(f"$npc{index}: Int!" for index in range(len(batch)))
        selections = " ".join(
            f"npc{index}: npc(id: $npc{index}) {{ id name }}"
            for index in range(len(batch))
        )
        query = f"query({declarations}) {{ gameData {{ {selections} }} }}"
        variables = {f"npc{index}": game_id for index, game_id in enumerate(batch)}
        data = (cn_client.graphql_data(query, variables).get("gameData") or {})
        for index, game_id in enumerate(batch):
            node = data.get(f"npc{index}") or {}
            if node.get("name"):
                names_by_game_id[game_id] = node["name"]

    localized_by_id = {int(row.get("id") or 0): dict(row) for row in localized}
    for actor in original:
        actor_id = int(actor.get("id") or 0)
        game_id = int(actor.get("gameID") or 0)
        row = localized_by_id.setdefault(actor_id, {"id": actor_id, "name": actor.get("name")})
        if actor.get("type") == "NPC" and game_id in names_by_game_id:
            row["name"] = names_by_game_id[game_id]
    return list(localized_by_id.values())


def _cn_report_translations(
    cn_client: WclClient,
    report_code: str,
    fight_id: int,
    original_pulls: list[dict],
) -> tuple[dict[str, str], dict[int, str]]:
    query = """
    query($code: String!) {
      reportData { report(code: $code) {
        masterData(translate: true) { abilities { gameID name } }
        fights { id dungeonPulls { id name } }
      } }
    }
    """
    report = cn_client.graphql(query, {"code": report_code})
    fight = next((row for row in report.get("fights") or [] if int(row.get("id") or 0) == fight_id), {})
    localized_by_id = {
        int(row.get("id") or 0): row.get("name")
        for row in fight.get("dungeonPulls") or []
        if row.get("name")
    }
    pull_translations = {
        row["name"]: localized_by_id[int(row.get("id") or 0)]
        for row in original_pulls
        if row.get("name") and int(row.get("id") or 0) in localized_by_id
    }
    ability_translations = {
        int(row.get("gameID") or 0): row.get("name")
        for row in (report.get("masterData") or {}).get("abilities") or []
        if row.get("gameID") and row.get("name")
    }
    return pull_translations, ability_translations


def export(report_code: str, fight_id: int, output: Path, dungeon_key: str = "skyreach", *,
           config: dict | None = None, observed_skills: bool = False,
           expected_zone_id: int | None = None, expected_roster: set | None = None) -> dict:
    client = WclClient()
    config = dict(config) if config is not None else dungeon_config(dungeon_key)
    report = client.graphql(METADATA_QUERY, {"code": report_code, "fightIDs": [fight_id]})
    fight = next((row for row in report.get("fights") or [] if int(row.get("id") or 0) == fight_id), None)
    if not fight:
        raise RuntimeError(f"report {report_code} does not contain fight {fight_id}")
    if not fight.get("dungeonPulls"):
        raise RuntimeError(f"fight {fight_id} is not a WCL Mythic+ dungeon fight")
    aliases = {name.lower() for name in config.get("aliases") or []}
    if aliases and (fight.get("name") or "").lower() not in aliases:
        raise RuntimeError(f"fight {fight_id} is {fight.get('name')}, not {config.get('officialNameZh')}")
    if expected_zone_id is not None and (report.get("zone") or {}).get("id") != expected_zone_id:
        raise RuntimeError("report zone does not match the requested live season")
    if observed_skills and (not fight.get("kill") or report.get("visibility") != "public"):
        raise RuntimeError("preview samples must be completed public runs")
    if expected_roster is not None:
        from analyzer_core.mythic_dungeon_timeline import _flatten_players
        roster = _flatten_players(_player_details(report), set(fight.get("friendlyPlayers") or []))
        if len(roster) != 5 or {(row["class"], row["specEnglish"]) for row in roster} != expected_roster:
            raise RuntimeError("fight roster does not match the requested five specializations")
    cn_client = _cn_client(client)
    pull_translations, ability_translations = _cn_report_translations(
        cn_client,
        report_code,
        fight_id,
        fight.get("dungeonPulls") or [],
    )
    config = {
        **config,
        "pullTranslations": pull_translations,
        "abilityTranslations": ability_translations,
    }

    hostile_casts = client.events(report_code, "Casts", fight, hostility_type="Enemies")
    friendly_casts = client.events(report_code, "Casts", fight, hostility_type="Friendlies")
    friendly_damage = client.events(report_code, "DamageDone", fight, hostility_type="Friendlies")
    hostile_deaths = client.events(report_code, "Deaths", fight, hostility_type="Enemies")
    void_meta_buffs = client.events(
        report_code,
        "Buffs",
        fight,
        hostility_type="Friendlies",
        ability_id=VOID_METAMORPHOSIS_ID,
    )
    skill_candidates = []
    if observed_skills:
        from collections import Counter
        from analyzer_core.mythic_dungeon_timeline import _event_ability_id
        enemy_ids = {_event_ability_id(row) for row in hostile_casts if _event_ability_id(row) > 8}
        begin_ids = {_event_ability_id(row) for row in hostile_casts if row.get("type") == "begincast"}
        original_names = {int(row["gameID"]): row.get("name") for row in (report.get("original") or {}).get("abilities") or []}
        config["enemyAbilities"] = {key: ability_translations.get(key) or original_names.get(key) or str(key) for key in enemy_ids}
        config["linkedTargetCasts"] = {key: {"displayEventType": "cast"} for key in enemy_ids - begin_ids}
        actors_by_id = {row["id"]:row for row in (report.get("original") or {}).get("actors") or []}
        counts = Counter()
        for pull in fight.get("dungeonPulls") or []:
            for event in hostile_casts:
                if not pull["startTime"] <= int(event.get("timestamp") or 0) < pull["endTime"]:
                    continue
                actor = actors_by_id.get(event.get("sourceID")) or {}
                spell = _event_ability_id(event)
                if spell in enemy_ids:
                    counts[(pull.get("encounterID") or 0, actor.get("gameID") or 0, actor.get("name") or "Unknown", spell, event.get("type"))] += 1
        groups = {}
        for (encounter, npc_id, npc_name, spell, kind), count in counts.items():
            row = groups.setdefault((encounter,npc_id,spell), {"encounterId":encounter, "pullType":"boss" if encounter else "trash",
                "npcId":npc_id, "npcName":npc_name, "spellId":spell, "nameZh":config["enemyAbilities"][spell],
                "nameEn":original_names.get(spell), "include":None, "notes":"", "eventCounts":{}})
            row["eventCounts"][kind] = count
        skill_candidates = list(groups.values())
    linked_target_events = {}
    for rule in (config.get("linkedTargetCasts") or {}).values():
        aura_id = int(rule.get("targetAuraId") or 0)
        if not aura_id or aura_id in linked_target_events:
            continue
        data_type = rule.get("targetDataType") or "Debuffs"
        linked_target_events[aura_id] = client.events(
            report_code,
            data_type,
            fight,
            hostility_type=rule.get("targetHostilityType") or (
                "Enemies" if data_type == "DamageDone" else "Friendlies"
            ),
            ability_id=aura_id,
        )
    synthetic_events = {}
    for rule in config.get("syntheticEnemyCasts") or []:
        if rule.get("trigger") != "aura":
            continue
        aura_id = int(rule.get("triggerAbilityId") or 0)
        if not aura_id or aura_id in synthetic_events:
            continue
        synthetic_events[aura_id] = client.events(
            report_code,
            rule.get("eventDataType") or "Buffs",
            fight,
            hostility_type=rule.get("hostilityType") or "Enemies",
            ability_id=aura_id,
        )

    document = build_dungeon_document(
        report_code=report_code,
        report=report,
        fight=fight,
        actors_original=(report.get("original") or {}).get("actors") or [],
        actors_localized=_cn_localized_actors(
            cn_client,
            (report.get("original") or {}).get("actors") or [],
            (report.get("localized") or {}).get("actors") or [],
        ),
        abilities_original=[
            {"id": row.get("gameID"), **row}
            for row in (report.get("original") or {}).get("abilities") or []
        ],
        player_details=_player_details(report),
        hostile_casts=hostile_casts,
        friendly_casts=friendly_casts,
        friendly_damage=friendly_damage,
        void_meta_buffs=void_meta_buffs,
        hostile_deaths=hostile_deaths,
        linked_target_events=linked_target_events,
        synthetic_events=synthetic_events,
        config=config,
    )
    if observed_skills:
        document["source"]["zoneId"] = (report.get("zone") or {}).get("id")
        document["source"]["zoneName"] = (report.get("zone") or {}).get("name")
        document["skillSelection"] = {"status":"needs-review", "policy":"observed-hostile-casts",
            "note":"正式服实际施法预览；尚未筛选关键技能。包含读条与本场没有读条记录的成功施法，不重建缺失事件。"}
        document["skillCandidates"] = skill_candidates
        annotate_skill_candidates(document)
        document["contract"]["enemyEvents"] = "observed begincast plus cast-only abilities; not a curated key-skill list"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    return document


def annotate_skill_candidates(document: dict) -> None:
    """Attach display names without adding any encounter-specific rules."""
    pulls = document.get("pulls") or []
    boss_names = {row["encounterId"]: row["name"] for row in pulls if row.get("encounterId")}
    npc_names = {row["gameId"]: row["name"] for pull in pulls for row in pull.get("enemies") or []}
    for row in document.get("skillCandidates") or []:
        row["bossName"] = boss_names.get(row["encounterId"])
        row["npcNameZh"] = npc_names.get(row["npcId"], row["npcName"])


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default="xpYfcXrBnkP8W1Ka")
    parser.add_argument("--fight", type=int, default=2)
    parser.add_argument("--dungeon", default="skyreach")
    parser.add_argument("--observed-skills", action="store_true", help="Preview observed casts before key-skill curation")
    parser.add_argument("--name-zh", help="Dungeon label for an observed preview")
    parser.add_argument("--zone", type=int, help="Reject a report outside this WCL zone")
    parser.add_argument("--season", type=int)
    parser.add_argument("--party-spec", action="append", default=[], help="Required Class:Spec; supply all five")
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
    expected_roster = {tuple(item.split(":", 1)) for item in args.party_spec} if args.party_spec else None
    if expected_roster is not None and (len(expected_roster) != 5 or any(len(item) != 2 for item in expected_roster)):
        parser.error("--party-spec requires five distinct Class:Spec pairs")
    config = {"key":args.dungeon, "officialNameZh":args.name_zh} if args.observed_skills else None
    document = export(args.report, args.fight, output, args.dungeon, config=config,
                      observed_skills=args.observed_skills, expected_zone_id=args.zone, expected_roster=expected_roster)
    if args.season:
        document["dungeon"]["season"] = args.season
        output.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "dungeon": document["dungeon"],
        "team": document["team"],
        "pulls": len(document["pulls"]),
        "timelineEvents": sum(len(row["timeline"]) for row in document["pulls"]),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
