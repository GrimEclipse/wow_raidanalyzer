"""Collect a first-pass spell/evidence catalog for WCL zone 54.

This is a developer discovery tool, not a player-facing analysis entry point.
It selects one representative (kill or longest) Mythic pull per encounter from
the supplied public reports and keeps provenance for every discovered spell.
"""

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from boss_plugins.void_spire.crown_of_the_cosmos import (
    fetch_events_all,
    get_token,
    graphql,
)


ZONE_ID = 54
ENCOUNTERS = {
    53470: {"key": "nakzali", "name": "Nek'zali the Soulcoiler"},
    53445: {"key": "sentinels", "name": "Entombed Sentinels"},
    53455: {"key": "vashnik", "name": "Vashnik the Malignant"},
    53497: {"key": "lostexplorers", "name": "The Lost Explorers"},
    53420: {"key": "sszorak", "name": "Sszorak"},
    53421: {"key": "twinfangs", "name": "The Twin Fangs"},
    53429: {"key": "bargained", "name": "The Coiled Altar"},
    53492: {
        "key": "ulatek",
        "name": "Ula'tek",
        "expectedUntested": True,
        "note": "团队副本尾王按惯例不开放公开测试，缺少 Mythic 日志属于预期状态。",
    },
}

MODE_DRAFTS = {
    "nakzali": {
        "confidence": "medium",
        "summary": "Boss 本体与多类灵魂/add 共同构成循环；Invoke/苏醒仪式召出或强化对象，灵魂转移与点燃构成处理链。",
        "phaseSignals": [1299673, 1295124, 1289683, 1289696, 1290003],
        "majorMechanics": [
            {"spellIDs": [1284103, 1292034], "note": "Possession Barrage 点名/射线伤害链"},
            {"spellIDs": [1287434], "note": "Essence Rend 约覆盖半团目标"},
            {"spellIDs": [1307939, 1293214, 1288772], "note": "多来源持续团队伤害/场地压力"},
        ],
    },
    "sentinels": {
        "confidence": "high",
        "summary": "Blood of Ula'tek 与 Breath of Ula'tek 双目标战；酸/血两类印记长期覆盖团队，约 103 秒一次 Vitriolic Stasis，Contaminate 约 52 秒循环。",
        "phaseSignals": [1284606, 1284588, 1290193, 1290189],
        "majorMechanics": [
            {"spellIDs": [1284500, 1284506], "note": "Mark of Acid/Blood 双阵营或双属性分配"},
            {"spellIDs": [1284257, 1284258], "note": "Contaminate 周期性团队伤害"},
            {"spellIDs": [1284487, 1284491, 1310126], "note": "Bloodvenom Injection 点名与后续伤害"},
        ],
    },
    "vashnik": {
        "confidence": "high",
        "summary": "Blood/Flame/Shadow 三种 Infusion 状态循环；Boss 通过 Imbibe 切换/吸收状态，Malignant Tumor 周期生成并以 Tumor Burst 结算。",
        "phaseSignals": [1298484, 1298489, 1298490, 1293968, 1293969, 1293971],
        "majorMechanics": [
            {"spellIDs": [1304437, 1304459], "note": "肿瘤生成、强化与爆炸链"},
            {"spellIDs": [1285979], "note": "Caustic Surge 高频团队压力"},
            {"spellIDs": [1294994, 1295173, 1295224], "note": "三类感染 Debuff/爆炸结果"},
        ],
    },
    "lostexplorers": {
        "confidence": "medium",
        "summary": "多首领/多物件战；Nama、Iku、Mor'zahi 与场地物件分别提供近战、卷轴、命令和环境技能，United Defense 暗示共享防御或联动阶段。",
        "phaseSignals": [1297646, 1292778, 1297075, 1297022, 1297024, 1296975],
        "majorMechanics": [
            {"spellIDs": [1297648, 1297649], "note": "冰/火 Patch 场地污染"},
            {"spellIDs": [1295858, 1310616], "note": "Shredding Shards 点名/分摊链"},
            {"spellIDs": [1292778, 1292780], "note": "Final Ascension 叠层与终局伤害"},
        ],
    },
    "sszorak": {
        "confidence": "medium",
        "summary": "以 Mutilate/Ravage 坦克连段为基础，穿插 Tempest 与多版本 Raging Crosswinds；后段出现 Venomous Surge 和 Unbound Ferocity 强化信号。",
        "phaseSignals": [1305959, 1286033, 1296898],
        "majorMechanics": [
            {"spellIDs": [1277027, 1277031, 1277002, 1277101], "note": "坦克 Mutilate/Ravage 连段"},
            {"spellIDs": [1285425, 1285453, 1297096, 1297111], "note": "Raging Crosswinds 风向/站位机制"},
            {"spellIDs": [1287205, 1297707, 1299899], "note": "Viscous Cyst 与 Virulence 点名/场地压力"},
        ],
    },
    "twinfangs": {
        "confidence": "high",
        "summary": "Ithraz/Vexhul 双首领并带 Barbed Bulwark/幼体对象；Protected Gestation 是显著护盾/孵化阶段，Stir the Depths 与 Ravenous Feast 是阶段切换信号。",
        "phaseSignals": [1303378, 1290956, 1290516, 1306872, 1294293],
        "majorMechanics": [
            {"spellIDs": [1290336, 1290480], "note": "Eternal Venom 高频全程压力"},
            {"spellIDs": [1289994, 1289237], "note": "Caustic Deluge 大范围伤害"},
            {"spellIDs": [1310102, 1310096, 1306925], "note": "Tainted Blood/Feasted/Congealed Gore 目标状态"},
        ],
    },
    "bargained": {
        "confidence": "medium",
        "summary": "Zul'jan 与 Hex Lord Malacrass 主导的多对象/祭坛战；Fangs of the Crucible 叠层推进，Manifestation of Dread 与灵魂系 add 构成恐惧阶段。",
        "phaseSignals": [1282520, 1282487, 1290316, 1309105, 1307959],
        "majorMechanics": [
            {"spellIDs": [1285017, 1283832], "note": "Axegrinder 目标追击/坦克压力"},
            {"spellIDs": [1283489, 1307425], "note": "Guillotine 点名处决链"},
            {"spellIDs": [1285911, 1286399], "note": "Unnerving Fixation/Wail of Terror 恐惧机制"},
        ],
    },
}


def report_index(token, report_id):
    query = """
    query($code: String!) {
      reportData {
        report(code: $code) {
          startTime
          fights {
            id encounterID name difficulty startTime endTime kill
          }
          masterData {
            actors { id name type subType gameID petOwner }
            abilities { gameID name type }
          }
        }
      }
    }
    """
    try:
        return graphql(token, query, {"code": report_id})
    except RuntimeError:
        fallback = """
        query($code: String!) {
          reportData {
            report(code: $code) {
              startTime
              fights {
                id encounterID name difficulty startTime endTime kill
              }
              masterData {
                actors { id name type subType gameID petOwner }
              }
            }
          }
        }
        """
        return graphql(token, fallback, {"code": report_id})


def ability_id(event):
    value = (
        event.get("abilityGameID")
        or event.get("abilityID")
        or (event.get("ability") or {}).get("gameID")
    )
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def event_amount(event):
    return int(event.get("amount") or event.get("unmitigatedAmount") or 0)


def event_is_apply(event):
    return str(event.get("type") or "").lower() in {
        "applydebuff",
        "applybuff",
        "applybuffstack",
        "applydebuffstack",
        "refreshdebuff",
        "refreshbuff",
    }


def event_is_remove(event):
    return str(event.get("type") or "").lower() in {
        "removedebuff",
        "removebuff",
        "removebuffstack",
        "removedebuffstack",
    }


def choose_representative_fights(report_documents):
    candidates = defaultdict(list)
    for report_id, document in report_documents.items():
        for fight in document.get("fights") or []:
            encounter_id = int(fight.get("encounterID") or 0)
            if encounter_id not in ENCOUNTERS or int(fight.get("difficulty") or 0) != 5:
                continue
            candidates[encounter_id].append({
                **fight,
                "reportID": report_id,
                "durationMs": int(fight["endTime"] - fight["startTime"]),
            })
    selected = {}
    for encounter_id, fights in candidates.items():
        selected[encounter_id] = max(
            fights,
            key=lambda fight: (
                bool(fight.get("kill")),
                int(fight.get("durationMs") or 0),
            ),
        )
    return selected


def actor_maps(document):
    actors = (document.get("masterData") or {}).get("actors") or []
    by_id = {int(actor["id"]): actor for actor in actors}
    abilities = (document.get("masterData") or {}).get("abilities") or []
    ability_names = {
        int(ability["gameID"]): ability.get("name") or str(ability["gameID"])
        for ability in abilities
        if ability.get("gameID") is not None
    }
    return by_id, ability_names


def actor_is_friendly_player_or_pet(actor_id, actors):
    try:
        actor_id = int(actor_id)
    except (TypeError, ValueError):
        return False
    actor = actors.get(actor_id) or {}
    if actor.get("type") == "Player":
        return True
    owner_id = actor.get("petOwner")
    return bool(owner_id and (actors.get(int(owner_id)) or {}).get("type") == "Player")


def summarize_spell_events(events, *, fight, report_id, ability_names, actors, mode):
    grouped = defaultdict(list)
    for event in events:
        spell_id = ability_id(event)
        if not spell_id:
            continue
        source_id = event.get("sourceID")
        target_id = event.get("targetID")
        try:
            target_actor = actors.get(int(target_id)) or {}
        except (TypeError, ValueError):
            target_actor = {}
        if actor_is_friendly_player_or_pet(source_id, actors):
            continue
        # Anonymous/environment events can include player utility and self-damage
        # in WCL tables.  PTR boss spells in this zone use the new 1.2M+ range;
        # discard legacy low-ID environment rows while retaining NPC melee.
        if source_id in {None, -1, "-1"} and spell_id < 1_000_000:
            continue
        if mode == "debuffs" and target_actor.get("type") != "Player":
            continue
        if mode == "bossAuras" and target_actor.get("type") == "Player":
            continue
        grouped[spell_id].append(event)

    result = []
    for spell_id, rows in grouped.items():
        ordered = sorted(rows, key=lambda event: int(event.get("timestamp") or 0))
        timestamps = [int(event.get("timestamp") or 0) for event in ordered]
        targets = {
            int(event["targetID"])
            for event in ordered
            if event.get("targetID") is not None
        }
        sources = {
            int(event["sourceID"])
            for event in ordered
            if event.get("sourceID") is not None
        }
        intervals = [
            timestamps[index] - timestamps[index - 1]
            for index in range(1, len(timestamps))
            if timestamps[index] > timestamps[index - 1]
        ]
        amounts = [event_amount(event) for event in ordered if event_amount(event) > 0]
        result.append({
            "spellID": spell_id,
            "name": ability_names.get(spell_id, str(spell_id)),
            "eventCount": len(ordered),
            "sourceIDs": sorted(sources),
            "sourceNames": sorted({
                (actors.get(source_id) or {}).get("name") or str(source_id)
                for source_id in sources
            }),
            "uniqueTargetCount": len(targets),
            "firstMs": timestamps[0] - int(fight["startTime"]),
            "lastMs": timestamps[-1] - int(fight["startTime"]),
            "medianIntervalMs": int(statistics.median(intervals)) if intervals else None,
            "totalAmount": sum(amounts),
            "maxAmount": max(amounts) if amounts else 0,
            "eventTypes": dict(Counter(str(event.get("type") or "") for event in ordered)),
            "provenance": {
                "reportID": report_id,
                "fightID": int(fight["id"]),
            },
        })
    return sorted(
        result,
        key=lambda row: (row["eventCount"], row["maxAmount"]),
        reverse=True,
    )


def summarize_resource_events(events, actors, fight, report_id):
    rows = []
    for event in events:
        source_id = event.get("sourceID")
        if actor_is_friendly_player_or_pet(source_id, actors):
            continue
        change = event.get("resourceChange")
        resource_type = event.get("resourceChangeType")
        if change in {None, 0} and resource_type is None:
            continue
        rows.append({
            "timeMs": int(event.get("timestamp") or 0) - int(fight["startTime"]),
            "sourceID": source_id,
            "source": (actors.get(source_id) or {}).get("name") or str(source_id),
            "resourceChange": change,
            "resourceChangeType": resource_type,
            "resourceActor": event.get("resourceActor"),
            "provenance": {"reportID": report_id, "fightID": int(fight["id"])},
        })
    return rows


def summarize_death_clusters(events, actors, fight, report_id, window_ms=1_500):
    ordered = sorted(events, key=lambda event: int(event.get("timestamp") or 0))
    clusters = []
    current = []
    for event in ordered:
        timestamp = int(event.get("timestamp") or 0)
        if current and timestamp - int(current[-1].get("timestamp") or 0) > window_ms:
            clusters.append(current)
            current = []
        current.append(event)
    if current:
        clusters.append(current)
    result = []
    for cluster in clusters:
        if len(cluster) < 2:
            continue
        timestamps = [int(event.get("timestamp") or 0) for event in cluster]
        result.append({
            "timeMs": timestamps[0] - int(fight["startTime"]),
            "count": len(cluster),
            "durationMs": timestamps[-1] - timestamps[0],
            "players": [
                (actors.get(event.get("targetID")) or {}).get("name")
                or str(event.get("targetID"))
                for event in cluster
            ],
            "abilityIDs": [event.get("killingAbilityGameID") for event in cluster],
            "provenance": {"reportID": report_id, "fightID": int(fight["id"])},
        })
    return result


def analyze_fight(token, fight, document):
    report_id = fight["reportID"]
    actors, ability_names = actor_maps(document)
    event_sets = {
        "casts": fetch_events_all(token, report_id, "Casts", fight, hostility_type="Enemies"),
        "damage": fetch_events_all(token, report_id, "DamageTaken", fight),
        "debuffs": fetch_events_all(token, report_id, "Debuffs", fight, hostility_type="Friendlies"),
        "bossAuras": fetch_events_all(token, report_id, "Buffs", fight, hostility_type="Enemies"),
        "resources": fetch_events_all(
            token,
            report_id,
            "Resources",
            fight,
            hostility_type="Enemies",
            include_resources=True,
        ),
        "deaths": fetch_events_all(token, report_id, "Deaths", fight),
    }
    return {
        "fight": {
            "reportID": report_id,
            "fightID": int(fight["id"]),
            "name": fight.get("name"),
            "kill": bool(fight.get("kill")),
            "durationMs": int(fight["endTime"] - fight["startTime"]),
        },
        "enemyCasts": summarize_spell_events(
            event_sets["casts"],
            fight=fight,
            report_id=report_id,
            ability_names=ability_names,
            actors=actors,
            mode="casts",
        ),
        "damageAbilities": summarize_spell_events(
            event_sets["damage"],
            fight=fight,
            report_id=report_id,
            ability_names=ability_names,
            actors=actors,
            mode="damage",
        ),
        "playerDebuffs": summarize_spell_events(
            event_sets["debuffs"],
            fight=fight,
            report_id=report_id,
            ability_names=ability_names,
            actors=actors,
            mode="debuffs",
        ),
        "bossAuras": summarize_spell_events(
            event_sets["bossAuras"],
            fight=fight,
            report_id=report_id,
            ability_names=ability_names,
            actors=actors,
            mode="bossAuras",
        ),
        "bossResources": summarize_resource_events(
            event_sets["resources"], actors, fight, report_id,
        ),
        "deathClusters": summarize_death_clusters(
            event_sets["deaths"], actors, fight, report_id,
        ),
    }


def render_markdown(document):
    lines = [
        "# WCL Zone 54 Mythic 初始取数",
        "",
        "所有条目均保留 report/fight 来源；以下是日志事实，不等同于最终机制判定。",
        "",
    ]
    for key, boss in document["bosses"].items():
        lines.extend([
            f"## {boss['name']} (`{key}`)",
            "",
            f"- 代表战斗：`{boss['fight']['reportID']}` / Fight {boss['fight']['fightID']}"
            f"，时长 {boss['fight']['durationMs']}ms，kill={boss['fight']['kill']}",
            f"- 敌方 Cast：{len(boss['enemyCasts'])} 个 spell ID",
            f"- 敌方伤害：{len(boss['damageAbilities'])} 个 spell ID",
            f"- 玩家 Debuff：{len(boss['playerDebuffs'])} 个 spell ID",
            f"- Boss/add Aura：{len(boss['bossAuras'])} 个 spell ID",
            f"- 模式草稿置信度：{(boss.get('modeDraft') or {}).get('confidence', 'unknown')}",
            f"- 模式草稿：{(boss.get('modeDraft') or {}).get('summary', '尚未形成')}",
            "",
            "高频敌方 Cast：",
            "",
        ])
        for row in boss["enemyCasts"][:12]:
            lines.append(
                f"- `{row['spellID']}` {row['name']}：{row['eventCount']} 次"
                f"，中位间隔 {row['medianIntervalMs']}ms"
            )
        lines.extend(["", "主要伤害技能：", ""])
        for row in boss["damageAbilities"][:15]:
            lines.append(
                f"- `{row['spellID']}` {row['name']}：{row['eventCount']} 次"
                f"，总量 {row['totalAmount']}，单次最高 {row['maxAmount']}"
            )
        lines.extend(["", "玩家 Debuff：", ""])
        for row in boss["playerDebuffs"][:15]:
            lines.append(
                f"- `{row['spellID']}` {row['name']}：{row['eventCount']} 事件"
                f"，涉及 {row['uniqueTargetCount']} 个目标"
            )
        lines.append("")
    expected_untested = document.get("expectedUntested") or []
    if expected_untested:
        lines.extend(["## 预期不开放测试", ""])
        for row in expected_untested:
            lines.append(f"- {row['name']} (`{row['key']}`)：{row['note']}")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports", required=True, help="逗号分隔的 WCL report ID")
    parser.add_argument("--output", default="docs/zone54_spell_discovery.json")
    parser.add_argument("--markdown", default="docs/zone54_spell_discovery.md")
    parser.add_argument("--resume", action="store_true", help="保留已有 Boss 结果，只补缺失 encounter")
    args = parser.parse_args()

    report_ids = [value.strip() for value in args.reports.split(",") if value.strip()]
    output = Path(args.output)
    markdown = Path(args.markdown)
    token = get_token()
    documents = {report_id: report_index(token, report_id) for report_id in report_ids}
    selected = choose_representative_fights(documents)

    if args.resume and output.exists():
        result = json.loads(output.read_text(encoding="utf-8"))
        result["reports"] = list(dict.fromkeys([*(result.get("reports") or []), *report_ids]))
    else:
        result = {
            "schemaVersion": 1,
            "zoneID": ZONE_ID,
            "reports": report_ids,
            "bosses": {},
            "missingEncounterIDs": [],
        }
    for encounter_id, fight in sorted(selected.items(), key=lambda item: list(ENCOUNTERS).index(item[0])):
        metadata = ENCOUNTERS[encounter_id]
        if metadata["key"] in result["bosses"]:
            continue
        print(
            f"[zone54] {metadata['name']}: {fight['reportID']} Fight {fight['id']}",
            flush=True,
        )
        result["bosses"][metadata["key"]] = {
            "encounterID": encounter_id,
            "name": metadata["name"],
            **analyze_fight(token, fight, documents[fight["reportID"]]),
        }

    for boss_key, boss in result["bosses"].items():
        boss["modeDraft"] = MODE_DRAFTS.get(boss_key, {
            "confidence": "unknown",
            "summary": "尚无足够日志形成模式草稿。",
            "phaseSignals": [],
            "majorMechanics": [],
        })
    captured_encounters = {
        int(boss.get("encounterID") or 0)
        for boss in result["bosses"].values()
    }
    expected_untested_ids = {
        encounter_id
        for encounter_id, metadata in ENCOUNTERS.items()
        if metadata.get("expectedUntested")
    }
    result["expectedUntested"] = [
        {
            "encounterID": encounter_id,
            "key": ENCOUNTERS[encounter_id]["key"],
            "name": ENCOUNTERS[encounter_id]["name"],
            "note": ENCOUNTERS[encounter_id]["note"],
        }
        for encounter_id in sorted(expected_untested_ids)
        if encounter_id not in captured_encounters
    ]
    result["missingEncounterIDs"] = sorted(
        set(ENCOUNTERS) - captured_encounters - expected_untested_ids
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown.write_text(render_markdown(result), encoding="utf-8")
    print(f"[zone54] wrote {output} and {markdown}", flush=True)
    if result["missingEncounterIDs"]:
        print(f"[zone54] missing encounter IDs: {result['missingEncounterIDs']}", flush=True)


if __name__ == "__main__":
    main()
