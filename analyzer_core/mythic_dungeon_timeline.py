"""Build stable Mythic+ route timelines from Warcraft Logs dungeon pulls.

The module deliberately keeps the evidence contract small:

* pull boundaries and enemy composition come from WCL ``dungeonPulls``;
* hostile abilities are emitted only from ``begincast`` events;
* player abilities are emitted only from successful ``cast`` events;
* Devourer Void Metamorphosis is reconstructed from removal of its charging
  counter aura because it does not produce a reliable player cast event.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone

from analyzer_core.mythic_dungeon_configs import dungeon_config as get_dungeon_config

_SKYREACH_CONFIG = get_dungeon_config("skyreach")
SKYREACH_ENEMY_ABILITIES = _SKYREACH_CONFIG["enemyAbilities"]
SKYREACH_ACTOR_ZH = _SKYREACH_CONFIG["actorTranslations"]

SKYREACH_PLAYER_ABILITIES = {
    102558: "化身：乌索克的守护者",
    20484: "复生",
    204066: "明月普照",
    1270292: "明月普照",
    22812: "树皮术",
    22842: "狂暴回复",
    61336: "生存本能",
    42650: "亡者大军",
    51052: "反魔法领域",
    48707: "反魔法护罩",
    48792: "冰封之韧",
    1233448: "黑暗突变",
    61999: "复活盟友",
    198589: "疾影",
    196718: "黑暗",
    1260459: "虚无之眼",
    1258283: "光盲圣怒的道标（连祷）",
    442204: "亘古吐息",
    374227: "微风",
    363916: "黑曜鳞片",
    443028: "天神御身",
    116849: "作茧缚命",
    115203: "壮胆酒",
    115310: "还魂术",
    116841: "迅如猛虎",
    115175: "抚慰之雾",
    124682: "氤氲之雾",
    325197: "朱鹤下凡",
    217832: "禁锢",
    49576: "死亡之握",
    58984: "影遁",
}

VOID_METAMORPHOSIS_ID = 1225789

TARGETED_PLAYER_ABILITIES = {
    20484,
    61999,
    204066,
    1270292,
    116849,
    116841,
    115175,
    124682,
    217832,
    49576,
}

PARTY_WIDE_PLAYER_ABILITIES = {
    51052,   # Anti-Magic Zone
    196718,  # Darkness
    374227,  # Zephyr
    442204,  # Breath of Eons
    115310,  # Revival
    1258283, # Litany trinket
}

SPEC_INFO = {
    104: ("守护", "德鲁伊", "坦克"),
    252: ("冰霜", "死亡骑士", "伤害"),
    270: ("织雾", "武僧", "治疗"),
    1473: ("增辉", "唤魔师", "伤害"),
    # The 12.0 Devourer specialization may not yet be present in older static
    # class libraries. WCL still supplies the localized spec name.
}

SPEC_NAME_ZH = {
    "Guardian": "守护",
    "Mistweaver": "织雾",
    "Devourer": "噬灭",
    "Augmentation": "增辉",
    "Unholy": "邪恶",
    "Frost": "冰霜",
}

CLASS_BY_TYPE = {
    "DemonHunter": "恶魔猎手",
    "DeathKnight": "死亡骑士",
    "Druid": "德鲁伊",
    "Evoker": "唤魔师",
    "Monk": "武僧",
}

ROLE_KEYS = {
    "tanks": "坦克",
    "healers": "治疗",
    "dps": "伤害",
}


def format_clock(milliseconds: int | float) -> str:
    milliseconds = max(0, int(round(milliseconds)))
    minutes, remainder = divmod(milliseconds, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{minutes:02d}:{seconds:02d}.{millis // 100}"


def _event_ability_id(event: dict) -> int:
    ability = event.get("ability") or {}
    return int(ability.get("gameID") or event.get("abilityGameID") or 0)


def _flatten_players(player_details: dict, friendly_ids: set[int]) -> list[dict]:
    players = []
    for role_key, role_name in ROLE_KEYS.items():
        for row in player_details.get(role_key, []) or []:
            actor_id = int(row.get("id") or 0)
            if actor_id not in friendly_ids:
                continue
            specs = row.get("specs") or []
            spec_row = max(specs, key=lambda item: item.get("count", 0), default={})
            raw_spec = spec_row.get("spec") or spec_row.get("id") or 0
            spec_id = int(raw_spec) if str(raw_spec).isdigit() else 0
            fallback = SPEC_INFO.get(spec_id, ("噬灭" if row.get("type") == "DemonHunter" else "未知", CLASS_BY_TYPE.get(row.get("type"), row.get("type") or "未知"), role_name))
            spec_english = spec_row.get("name") or (raw_spec if isinstance(raw_spec, str) else "") or ""
            spec_name = SPEC_NAME_ZH.get(spec_english, spec_english or fallback[0])
            class_name = CLASS_BY_TYPE.get(row.get("type"), fallback[1])
            players.append({
                "id": actor_id,
                "name": row.get("name") or f"Player {actor_id}",
                "class": row.get("type") or "Unknown",
                "className": class_name,
                "specId": spec_id,
                "spec": spec_name,
                "specEnglish": spec_english or None,
                "role": role_name,
            })
    return sorted(players, key=lambda row: (0 if row["role"] == "坦克" else 1 if row["role"] == "治疗" else 2, row["id"]))


def _actor_document(actor: dict | None, instance: int | None = None) -> dict | None:
    if not actor:
        return None
    result = {
        "id": int(actor.get("id") or 0),
        "name": actor.get("name") or "未知目标",
        "type": actor.get("type") or "Unknown",
    }
    if actor.get("gameID"):
        result["gameId"] = int(actor["gameID"])
    if actor.get("originalName") and actor.get("originalName") != actor.get("name"):
        result["originalName"] = actor["originalName"]
    if instance:
        result["instance"] = int(instance)
    return result


def _ability_document(ability_id: int, localized_name: str, ability_names: dict[int, str]) -> dict:
    return {
        "id": ability_id,
        "name": localized_name,
        "originalName": ability_names.get(ability_id) or localized_name,
    }


def _event_target(event: dict, actors: dict[int, dict], show_target: bool = True) -> dict | None:
    if not show_target:
        return None
    target_id = int(event.get("targetID") or 0)
    source_id = int(event.get("sourceID") or 0)
    actor = actors.get(target_id)
    if not target_id or target_id == source_id or not actor:
        return None
    if actor.get("type") == "Environment" or actor.get("name") == "Environment":
        return None
    return _actor_document(actor, event.get("targetInstance"))


def _timeline_event(
    event: dict,
    *,
    pull_start: int,
    dungeon_start: int,
    kind: str,
    actors: dict[int, dict],
    localized_name: str,
    ability_names: dict[int, str],
    synthetic: bool = False,
    linked_targets: list[dict] | None = None,
) -> dict:
    timestamp = int(event.get("timestamp") or pull_start)
    ability_id = _event_ability_id(event)
    source_id = int(event.get("sourceID") or 0)
    primary_target = _event_target(
        event,
        actors,
        show_target=(kind == "enemyBeginCast" or ability_id in TARGETED_PLAYER_ABILITIES),
    )
    targets = []
    for linked in linked_targets or []:
        target = _actor_document(actors.get(int(linked.get("targetID") or 0)), linked.get("targetInstance"))
        if target and target["id"] not in {row["id"] for row in targets}:
            targets.append(target)
    return {
        "timestamp": timestamp,
        "dungeonOffsetMs": timestamp - dungeon_start,
        "pullOffsetMs": timestamp - pull_start,
        "dungeonTime": format_clock(timestamp - dungeon_start),
        "pullTime": format_clock(timestamp - pull_start),
        "kind": kind,
        "eventType": event.get("type") or ("applybuff" if synthetic else "unknown"),
        "source": _actor_document(actors.get(source_id), event.get("sourceInstance")),
        "target": primary_target,
        "targets": targets,
        "ability": _ability_document(ability_id, localized_name, ability_names),
        "scope": "party" if ability_id in PARTY_WIDE_PLAYER_ABILITIES else "targeted" if ability_id in TARGETED_PLAYER_ABILITIES else "self",
        "synthetic": synthetic,
    }


def _pull_instances(pull: dict, actors: dict[int, dict]) -> list[dict]:
    instances = []
    for npc in pull.get("enemyNPCs") or []:
        actor_id = int(npc.get("id") or 0)
        minimum = int(npc.get("minimumInstanceID") or 1)
        maximum = int(npc.get("maximumInstanceID") or minimum)
        actor = actors.get(actor_id) or {"id": actor_id, "name": pull.get("name") or "Unknown", "type": "NPC", "gameID": npc.get("gameID")}
        for instance in range(minimum, maximum + 1):
            row = _actor_document(actor, instance) or {}
            row["label"] = f"{row.get('name', '未知怪物')} {instance}"
            instances.append(row)
    return instances


def _find_openers(
    pull: dict,
    enemies: list[dict],
    friendly_damage: list[dict],
    friendly_casts: list[dict],
    hostile_casts: list[dict],
    actors: dict[int, dict],
    player_ids: set[int],
) -> None:
    start = int(pull["startTime"])
    end = int(pull["endTime"])
    enemy_keys = {(row["id"], row.get("instance", 1)): row for row in enemies}
    candidates: dict[tuple[int, int], list[tuple[int, dict, str]]] = defaultdict(list)

    for event in friendly_casts:
        if event.get("type") != "cast":
            continue
        timestamp = int(event.get("timestamp") or 0)
        if timestamp < start or timestamp > end:
            continue
        target_id = int(event.get("targetID") or 0)
        target_instance = int(event.get("targetInstance") or 1)
        key = (target_id, target_instance)
        if key in enemy_keys and int(event.get("sourceID") or 0) in player_ids:
            candidates[key].append((timestamp, event, "cast"))

    for event in friendly_damage:
        timestamp = int(event.get("timestamp") or 0)
        if timestamp < start or timestamp > end:
            continue
        target_id = int(event.get("targetID") or 0)
        target_instance = int(event.get("targetInstance") or 1)
        key = (target_id, target_instance)
        if key in enemy_keys and int(event.get("sourceID") or 0) in player_ids:
            candidates[key].append((timestamp, event, "damage"))

    # Body pulls can begin before any friendly damage. In that case the first
    # hostile begin-cast target is the best evidence WCL provides.
    for event in hostile_casts:
        if event.get("type") != "begincast":
            continue
        timestamp = int(event.get("timestamp") or 0)
        if timestamp < start or timestamp > end:
            continue
        key = (int(event.get("sourceID") or 0), int(event.get("sourceInstance") or 1))
        target_id = int(event.get("targetID") or 0)
        if key in enemy_keys and target_id in player_ids:
            candidates[key].append((timestamp, {**event, "sourceID": target_id}, "enemyTarget"))

    for key, enemy in enemy_keys.items():
        options = sorted(candidates.get(key, []), key=lambda row: (row[0], 0 if row[2] == "cast" else 1))
        if not options:
            enemy["opener"] = None
            continue
        timestamp, event, evidence = options[0]
        source_id = int(event.get("sourceID") or 0)
        enemy["opener"] = {
            "player": _actor_document(actors.get(source_id)),
            "timestamp": timestamp,
            "dungeonTime": format_clock(timestamp - int(pull.get("dungeonStart", start))),
            "pullTime": format_clock(timestamp - start),
            "evidence": evidence,
            "abilityId": _event_ability_id(event) or None,
        }


def build_dungeon_document(
    *,
    report_code: str,
    report: dict,
    fight: dict,
    actors_original: list[dict],
    actors_localized: list[dict],
    abilities_original: list[dict],
    player_details: dict,
    hostile_casts: list[dict],
    friendly_casts: list[dict],
    friendly_damage: list[dict],
    void_meta_buffs: list[dict],
    scorching_ray_debuffs: list[dict] | None = None,
    linked_target_events: dict[int, list[dict]] | None = None,
    config: dict | None = None,
) -> dict:
    config = config or get_dungeon_config("skyreach")
    enemy_abilities = config.get("enemyAbilities") or {}
    actor_translations = config.get("actorTranslations") or {}
    linked_casts = config.get("linkedTargetCasts") or {}
    linked_event_map = dict(linked_target_events or {})
    if scorching_ray_debuffs is not None:
        linked_event_map.setdefault(1253541, scorching_ray_debuffs)
    fight_start = int(fight["startTime"])
    dungeon_end = int(fight["endTime"])
    keystone_time = int(fight.get("keystoneTime") or 0)
    key_start = dungeon_end - keystone_time if keystone_time else fight_start
    # The visible global timeline follows WCL's Fight clock so users can match
    # an event directly against the WCL UI. Key-clock offsets are retained as
    # separate fields for leaderboard/routing use.
    dungeon_start = fight_start
    original_by_id = {int(row["id"]): row for row in actors_original}
    localized_by_id = {int(row["id"]): row for row in actors_localized}
    actors = {}
    for actor_id, original in original_by_id.items():
        localized = localized_by_id.get(actor_id) or {}
        original_name = original.get("name") or f"Actor {actor_id}"
        localized_name = localized.get("name") or original_name
        if localized_name == original_name:
            localized_name = actor_translations.get(original_name, original_name)
        actors[actor_id] = {**original, "name": localized_name, "originalName": original_name}
    ability_names = {int(row["id"]): row.get("name") or str(row["id"]) for row in abilities_original}
    friendly_ids = {int(actor_id) for actor_id in fight.get("friendlyPlayers") or []}
    players = _flatten_players(player_details, friendly_ids)

    pulls = []
    source_pulls = sorted(fight.get("dungeonPulls") or [], key=lambda row: row["startTime"])
    source_pulls = [row for row in source_pulls if int(row["endTime"]) - int(row["startTime"]) >= 500]
    for ordinal, raw_pull in enumerate(source_pulls, start=1):
        pull = dict(raw_pull)
        pull["dungeonStart"] = dungeon_start
        start = int(pull["startTime"])
        end = int(pull["endTime"])
        is_boss = bool(int(pull.get("encounterID") or 0))
        enemies = _pull_instances(pull, actors)
        _find_openers(pull, enemies, friendly_damage, friendly_casts, hostile_casts, actors, friendly_ids)

        timeline = []
        for event in hostile_casts:
            ability_id = _event_ability_id(event)
            timestamp = int(event.get("timestamp") or 0)
            event_type = event.get("type")
            linked_rule = linked_casts.get(ability_id)
            display_event_type = (
                linked_rule.get("displayEventType", linked_rule.get("eventType", "cast"))
                if linked_rule else None
            )
            is_standard = not linked_rule and event_type == "begincast" and ability_id in enemy_abilities
            is_linked_target_cast = bool(linked_rule) and event_type == display_event_type
            if not (is_standard or is_linked_target_cast) or not (start <= timestamp <= end):
                continue
            linked_targets = []
            target_aura_id = int(linked_rule.get("targetAuraId") or 0) if linked_rule else 0
            if is_linked_target_cast and target_aura_id:
                anchor_timestamp = timestamp
                target_event_type = linked_rule.get("targetEventType", display_event_type)
                if target_event_type != display_event_type:
                    anchor_window = int(linked_rule.get("anchorWindowMs") or 15_000)
                    anchors = [
                        row for row in hostile_casts
                        if _event_ability_id(row) == ability_id
                        and row.get("type") == target_event_type
                        and int(row.get("sourceID") or 0) == int(event.get("sourceID") or 0)
                        and int(row.get("sourceInstance") or 0) == int(event.get("sourceInstance") or 0)
                        and timestamp <= int(row.get("timestamp") or 0) <= timestamp + anchor_window
                    ]
                    if anchors:
                        anchor_timestamp = min(int(row.get("timestamp") or 0) for row in anchors)
                tolerance = int(linked_rule.get("toleranceMs") or 50)
                linked_targets = [
                    row for row in linked_event_map.get(target_aura_id, [])
                    if row.get("type") == "applydebuff"
                    and int(row.get("targetID") or 0) in friendly_ids
                    and abs(int(row.get("timestamp") or 0) - anchor_timestamp) <= tolerance
                ]
            timeline.append(_timeline_event(
                event,
                pull_start=start,
                dungeon_start=dungeon_start,
                kind="enemyBeginCast",
                actors=actors,
                localized_name=enemy_abilities[ability_id],
                ability_names=ability_names,
                linked_targets=linked_targets,
            ))

        for event in friendly_casts:
            ability_id = _event_ability_id(event)
            timestamp = int(event.get("timestamp") or 0)
            if event.get("type") != "cast" or ability_id not in SKYREACH_PLAYER_ABILITIES or not (start <= timestamp <= end):
                continue
            timeline.append(_timeline_event(
                event,
                pull_start=start,
                dungeon_start=dungeon_start,
                kind="playerCast",
                actors=actors,
                localized_name=SKYREACH_PLAYER_ABILITIES[ability_id],
                ability_names=ability_names,
            ))

        for event in void_meta_buffs:
            timestamp = int(event.get("timestamp") or 0)
            # Devourer uses this aura as a 1-50 charging state. WCL's graph
            # enters the purple Metamorphosis coverage when the counter aura is
            # removed, then applies it again when that coverage ends.
            if event.get("type") != "removebuff" or not (start <= timestamp <= end):
                continue
            synthetic_event = {
                **event,
                "ability": {"gameID": VOID_METAMORPHOSIS_ID},
                "sourceID": event.get("targetID") or event.get("sourceID"),
                "sourceInstance": event.get("targetInstance"),
                "targetID": 0,
            }
            timeline.append(_timeline_event(
                synthetic_event,
                pull_start=start,
                dungeon_start=dungeon_start,
                kind="playerState",
                actors=actors,
                localized_name="进入虚空恶魔变形",
                ability_names=ability_names,
                synthetic=True,
            ))

        # WCL currently emits both the legacy and replacement spell IDs for
        # 明月普照 at the same timestamp. Collapse equivalent player rows and
        # keep the higher/current ID so the copied route has one action.
        deduplicated = {}
        for row in timeline:
            key = (
                row["kind"],
                row["timestamp"],
                (row.get("source") or {}).get("id"),
                (row.get("target") or {}).get("id"),
                row["ability"]["name"],
            )
            previous = deduplicated.get(key)
            if previous is None or row["ability"]["id"] > previous["ability"]["id"]:
                deduplicated[key] = row
        timeline = sorted(deduplicated.values(), key=lambda row: (row["timestamp"], 0 if row["kind"] == "enemyBeginCast" else 1))
        counts = Counter(row["name"] for row in enemies)
        pulls.append({
            "id": int(pull.get("id") or ordinal),
            "ordinal": ordinal,
            "type": "boss" if is_boss else "trash",
            "name": actor_translations.get(pull.get("name"), pull.get("name")) or ("Boss" if is_boss else f"Pull {ordinal}"),
            "originalName": pull.get("name") or None,
            "encounterId": int(pull.get("encounterID") or 0),
            "kill": bool(pull.get("kill")),
            "startTime": start,
            "endTime": end,
            "durationMs": end - start,
            "dungeonOffsetMs": start - dungeon_start,
            "dungeonTime": format_clock(start - dungeon_start),
            "duration": format_clock(end - start),
            "enemySummary": [{"name": name, "count": count} for name, count in sorted(counts.items())],
            "enemies": enemies,
            "timeline": timeline,
        })

    return {
        "schemaVersion": 1,
        "kind": "mythic-dungeon-route-timeline",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": {
            "provider": "Warcraft Logs",
            "reportCode": report_code,
            "reportUrl": f"https://www.warcraftlogs.com/reports/{report_code}?fight={fight['id']}",
            "fightId": int(fight["id"]),
            "reportTitle": report.get("title") or "",
        },
        "dungeon": {
            "key": config.get("key"),
            "name": fight.get("name") or (config.get("aliases") or [config.get("name")])[0],
            "nameZh": config.get("officialNameZh") or config.get("name") or fight.get("name"),
            "keystoneLevel": int(fight.get("keystoneLevel") or 0),
            "completed": bool(fight.get("kill")),
            "durationMs": dungeon_end - dungeon_start,
            "duration": format_clock(dungeon_end - dungeon_start),
            "keystoneTimeMs": int(fight.get("keystoneTime") or dungeon_end - dungeon_start),
            "keystoneTime": format_clock(fight.get("keystoneTime") or dungeon_end - dungeon_start),
            "wclFightWindowMs": dungeon_end - int(fight["startTime"]),
            "wclFightWindow": format_clock(dungeon_end - int(fight["startTime"])),
            "keyStartOffsetMs": key_start - fight_start,
        },
        "team": players,
        "contract": {
            "enemyEvents": "begincast, plus configured instant casts linked to their target debuffs",
            "playerEvents": "successful cast only",
            "voidMetamorphosis": "removebuff 1225789 reconstructed as state entry",
            "pullBoundaries": "WCL dungeonPulls",
        },
        "pulls": pulls,
    }


def build_skyreach_document(**kwargs) -> dict:
    kwargs.setdefault("config", get_dungeon_config("skyreach"))
    return build_dungeon_document(**kwargs)
