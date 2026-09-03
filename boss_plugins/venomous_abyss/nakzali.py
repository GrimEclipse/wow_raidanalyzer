"""Initial evidence-first analyzer for Nek'zali the Soulcoiler (12.1)."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from analyzer_core.concurrency import run_parallel_indexed
from analyzer_core.court_rules import validate_court_profile
from analyzer_core.progress import emit_progress
from analyzer_core.wcl_api import WclClient
from boss_plugins.common import (
    build_player_mechanic_roles,
    combatant_spec_id,
    spec_class_color,
    spec_icon_slug,
    spec_localization,
    write_json_result,
)
from boss_plugins.venomous_abyss.shared import (
    HOLLOWING_STACK_IDS,
    TAUNT_SPELLS,
    build_survival_timeline,
    difficulty_fields,
    load_confirmed_spell_names,
    load_confirmed_source_names,
    nightly_detail,
    nightly_player_totals,
    player_ref,
    source_name,
    spell_name,
)


ENCOUNTER_ID = 3470
LEGACY_ENCOUNTER_IDS = {53470}
ENCOUNTER_IDS = {ENCOUNTER_ID, *LEGACY_ENCOUNTER_IDS}
CN_TZ = timezone(timedelta(hours=8))

SPELLS = load_confirmed_spell_names()
SOURCE_NAMES = load_confirmed_source_names()
SPELLS.update({
    1288772: "盘魂仪式",
    1284034: "解缚之怒",
    1284103: "附身弹幕",
    1292034: "附身弹幕",
    1285681: "缠魂点燃",
    1293664: "缠魂点燃",
    1287426: "精华撕裂",
    1287434: "精华撕裂",
    1287533: "墓缚推进",
    1289683: "苏醒仪式",
    1290003: "解缚",
    1289855: "噬灭烈焰",
    1289875: "焚烧",
    1290361: "盘魂",
    1292248: "灵魂转移",
    1293214: "攫取深渊",
    1294729: "尸体枯萎",
    1294933: "蛇形烈焰",
    1295085: "灵魂转移",
    1295124: "苏醒仪式",
    1297624: "仪式灼烧",
    1299673: "祈求",
    1299722: "祈求打断",
    1297631: "觉醒宿主",
    1299988: "不朽盘卷",
    1300235: "灵魂疲惫",
    1300238: "盘魂者诅咒",
    1300239: "盘旋精魂",
    1306666: "噬灭烈焰点名",
    1307939: "残骸凋零",
    1308227: "不朽盘卷",
})

PHASE_CASTS = {1293664, 1295124, 1292248, 1289855, 1299673, 1284034}
MECHANIC_CASTS = PHASE_CASTS | {1284103, 1287533, 1297624, 1300238}
AVOIDABLE_DAMAGE = {
    1288554: spell_name(1288554),
    1295085: spell_name(1295085),
    1300239: "盘旋精魂",
}
POSITION_DAMAGE_IDS = set(AVOIDABLE_DAMAGE) | {1287434, 1292034, 1293214}

DEFAULT_OPTIONS = {
    "essenceRendReviewEnabled": True,
    "essenceRendPlacementCountEnabled": False,
    "essenceRendMinDistanceYards": 20,
    "essenceRendMaxSampleOffsetMs": 1250,
    "essenceRendEdgeRatio": 0.72,
    "amaniLeakReviewEnabled": True,
    "amaniLeakCountEnabled": False,
    "possessionBarrageReviewEnabled": True,
    "possessionBarrageCountEnabled": False,
    "hungeringPyreReviewEnabled": True,
    "hungeringPyreSoakRadiusYards": 10,
    "corpseBurnRadiusYards": 5,
    "corpseAttemptRadiusYards": 10,
    "innerRealmReviewEnabled": True,
    "innerRealmTeams": {},
    "innerRealmRotation": ["3", "4"],
    "raidCollapseDeathThreshold": 8,
    "invokeInterruptReviewEnabled": True,
    "avoidableDamageReviewEnabled": True,
}

COURT_PROFILE = {
    "bossKey": "nakzali",
    "phaseModel": "event_driven",
    "rules": [
        {
            "key": "amani_reached_well", "label": "无眠的阿曼尼漏进灵魂之井", "mode": "direct",
            "spellIDs": [1287533, 1297624],
            "requiredEvidence": ["add identity", "well entry", "adjacent Ritual Burn"],
            "countOption": "amaniLeakCountEnabled", "defaultCountEnabled": True, "severityUnits": 1,
        },
        {
            "key": "possession_barrage_intercept", "label": "附身弹幕路径拦截", "mode": "assignment",
            "spellIDs": [1284103, 1292034], "assignmentKey": "possessionBarrageTankLane",
            "requiredEvidence": ["cast target", "boss facing", "hit players", "position samples"],
            "countOption": "possessionBarrageCountEnabled", "defaultCountEnabled": False, "severityUnits": 1,
        },
        {
            "key": "essence_rend_placement", "label": "精华撕裂解除位置", "mode": "assignment",
            "spellIDs": [1287426, 1287434, 1287198], "assignmentKey": "essenceRendAllowedRegions",
            "requiredEvidence": ["remove timestamp", "nearest position sample", "sample offset"],
            "countOption": "essenceRendPlacementCountEnabled", "defaultCountEnabled": False, "severityUnits": 1,
        },
    ],
}
validate_court_profile(COURT_PROFILE)


def progress(message, percent=None):
    print(f"[nakzali] {message}", flush=True)
    emit_progress(message, percent=percent, stage="analyze")


def ability_id(event):
    return event.get("abilityGameID") or event.get("killingAbilityGameID") or event.get("extraAbilityGameID")


def event_amount(event):
    return int(event.get("amount") or event.get("unmitigatedAmount") or 0)


def event_type(event):
    return str(event.get("type") or "").lower()


def is_apply(event):
    return event_type(event) in {"applydebuff", "applybuff", "applydebuffstack", "applybuffstack", "refreshdebuff"}


def is_remove(event):
    return event_type(event) in {"removedebuff", "removebuff", "removedebuffstack", "removebuffstack"}


def fmt_ms(ms):
    seconds = max(0, int(ms or 0)) / 1000
    return f"{int(seconds // 60):02d}:{seconds % 60:04.1f}"


def actor_name(actor_map, actor_id):
    return actor_map.get(actor_id, f"未知({actor_id})")


def event_point(event):
    nodes = [event, event.get("resources") or {}, event.get("sourceResources") or {}]
    for node in nodes:
        if not isinstance(node, dict):
            continue
        for x_key, y_key in (("x", "y"), ("positionX", "positionY"), ("X", "Y")):
            if x_key in node and y_key in node:
                try:
                    return float(node[x_key]), float(node[y_key])
                except (TypeError, ValueError):
                    pass
        position = node.get("position") or node.get("location")
        if isinstance(position, dict) and position.get("x") is not None and position.get("y") is not None:
            return float(position["x"]), float(position["y"])
    return None


def position_actor_id(event):
    resource_actor = event.get("resourceActor")
    if resource_actor in {2, "2"}:
        return event.get("targetID")
    if resource_actor in {1, "1"}:
        return event.get("sourceID")
    kind = event_type(event)
    if "buff" in kind or "debuff" in kind or kind == "death":
        return event.get("targetID")
    return event.get("sourceID") or event.get("targetID")


def build_position_index(events):
    rows = defaultdict(list)
    for event in events:
        point = event_point(event)
        actor_id = position_actor_id(event)
        if actor_id is None or not point:
            continue
        rows[actor_id].append({
            "timestamp": int(event.get("timestamp") or 0),
            "x": point[0],
            "y": point[1],
            "facing": event.get("facing"),
            "hitPoints": event.get("hitPoints"),
            "maxHitPoints": event.get("maxHitPoints"),
            "absorb": event.get("absorb"),
            "abilityID": ability_id(event),
            "sourceType": event_type(event),
        })
    for actor_rows in rows.values():
        actor_rows.sort(key=lambda row: row["timestamp"])
    return rows


def actor_state_at(index, actor_id, timestamp, reliable_window_ms=3_000, fallback_window_ms=30_000):
    rows = index.get(actor_id) or []
    if not rows:
        return None
    before = None
    after = None
    for row in rows:
        if row["timestamp"] <= timestamp:
            before = row
        else:
            after = row
            break
    if before and after:
        before_delta = timestamp - before["timestamp"]
        after_delta = after["timestamp"] - timestamp
        if before_delta <= reliable_window_ms and after_delta <= reliable_window_ms:
            span = after["timestamp"] - before["timestamp"]
            ratio = 0 if span <= 0 else before_delta / span
            reference = before if before_delta <= after_delta else after
            reference_delta = int(reference["timestamp"] - timestamp)
            return {
                "timestamp": timestamp,
                "x": before["x"] + (after["x"] - before["x"]) * ratio,
                "y": before["y"] + (after["y"] - before["y"]) * ratio,
                "facing": reference.get("facing"),
                "hitPoints": reference.get("hitPoints"),
                "maxHitPoints": reference.get("maxHitPoints"),
                "absorb": reference.get("absorb"),
                "sampleTimestamp": reference["timestamp"],
                "sampleOffsetMs": reference_delta,
                "beforeOffsetMs": -before_delta,
                "afterOffsetMs": after_delta,
                "positionRule": "interpolated",
                "reliable": True,
            }
    nearest = min((row for row in (before, after) if row), key=lambda row: abs(row["timestamp"] - timestamp), default=None)
    if not nearest:
        return None
    delta = int(nearest["timestamp"] - timestamp)
    return {
        **nearest,
        "sampleTimestamp": nearest["timestamp"],
        "sampleOffsetMs": delta,
        "positionRule": "nearest" if abs(delta) <= reliable_window_ms else "nearest-reference",
        "reliable": abs(delta) <= reliable_window_ms,
        "outsideFallbackWindow": abs(delta) > fallback_window_ms,
    }


def compact_actor_position_events(events, actor_id, minimum_interval_ms=120):
    """Keep a small but movement-safe position stream for a target actor."""
    compact = []
    last_timestamp = None
    last_state = None
    for event in events:
        if position_actor_id(event) != actor_id or not event_point(event):
            continue
        timestamp = int(event.get("timestamp") or 0)
        point = event_point(event)
        state = (round(point[0], 2), round(point[1], 2), event.get("facing"))
        if last_timestamp is not None and timestamp - last_timestamp < minimum_interval_ms and state == last_state:
            continue
        compact.append(event)
        last_timestamp = timestamp
        last_state = state
    return compact


def vitals_from_state(state):
    if not state:
        return None
    hit_points = state.get("hitPoints")
    max_hit_points = state.get("maxHitPoints")
    health_percent = None
    if hit_points is not None and max_hit_points:
        health_percent = round(max(0, min(100, float(hit_points) / float(max_hit_points) * 100)), 1)
    if health_percent is None and state.get("absorb") is None:
        return None
    return {
        "hitPoints": hit_points,
        "maxHitPoints": max_hit_points,
        "healthPercent": health_percent,
        "absorb": state.get("absorb"),
        "sampleDeltaMs": state.get("sampleOffsetMs"),
        "confidence": "nearby" if state.get("reliable") else "reference-only",
    }


def snapshot_at(timestamp, player_catalog, boss_ids, actor_map, position_index, deaths, arena=None):
    dead_ids = {
        event.get("targetID") for event in deaths
        if event.get("targetID") is not None and int(event.get("timestamp") or 0) <= timestamp
    }
    players = []
    for actor_id, player in player_catalog.items():
        if actor_id in dead_ids:
            continue
        state = actor_state_at(position_index, actor_id, timestamp, reliable_window_ms=3_000)
        players.append({
            **player,
            "position": ({"x": round(state["x"], 2), "y": round(state["y"], 2)} if state else None),
            "facing": state.get("facing") if state else None,
            "sampleOffsetMs": state.get("sampleOffsetMs") if state else None,
            "positionRule": state.get("positionRule") if state else "missing",
            "positionReliable": bool(state and state.get("reliable")),
            "vitals": vitals_from_state(state),
        })
    bosses = []
    for actor_id in boss_ids:
        state = actor_state_at(position_index, actor_id, timestamp, reliable_window_ms=8_000)
        position = {"x": round(state["x"], 2), "y": round(state["y"], 2)} if state else None
        position_rule = state.get("positionRule") if state else "missing"
        bosses.append({
            "id": actor_id,
            "name": actor_name(actor_map, actor_id),
            "position": position,
            "facing": state.get("facing") if state else None,
            "sampleOffsetMs": state.get("sampleOffsetMs") if state else None,
            "positionReliable": bool(state and state.get("reliable")),
            "positionRule": position_rule,
            "vitals": vitals_from_state(state),
        })
    return {"timeMsAbsolute": timestamp, "players": players, "bosses": bosses}


def cluster_timestamps(events, window_ms=180):
    timestamps = sorted(int(event.get("timestamp") or 0) for event in events)
    groups = []
    for timestamp in timestamps:
        if not groups or timestamp - groups[-1][-1] > window_ms:
            groups.append([timestamp])
        else:
            groups[-1].append(timestamp)
    return [int(statistics.median(group)) for group in groups]


def phase_markers(fight, casts, buffs):
    intermission = next((event for event in casts if ability_id(event) == 1295124 and event_type(event) == "begincast"), None)
    if not intermission:
        intermission = next((event for event in casts if ability_id(event) in {1289683, 1295124}), None)
    p2 = next((event for event in buffs if ability_id(event) == 1290003 and is_apply(event)), None)
    if not p2:
        p2 = next((event for event in casts if ability_id(event) == 1299673), None)
    enrage = next((event for event in casts if ability_id(event) == 1284034), None)
    rows = [{"key": "p1", "label": "P1 缠魂者启蒙", "timeMs": 0}]
    if intermission:
        rows.append({"key": "intermission", "label": "转阶段：苏醒仪式", "timeMs": int(intermission["timestamp"] - fight["startTime"]), "spellID": ability_id(intermission)})
    if p2:
        rows.append({"key": "p2", "label": "P2 解缚", "timeMs": int(p2["timestamp"] - fight["startTime"]), "spellID": ability_id(p2)})
    if enrage:
        rows.append({"key": "enrage", "label": "解缚之怒", "timeMs": int(enrage["timestamp"] - fight["startTime"]), "spellID": 1284034})
    rows.append({
        "key": "kill" if fight.get("kill") else "wipe",
        "label": "击杀" if fight.get("kill") else f"{float(fight.get('bossPercentage') or 100):.2f}% 灭团",
        "timeMs": int(fight["endTime"] - fight["startTime"]),
    })
    return sorted(rows, key=lambda row: row["timeMs"])


def phase_at(elapsed_ms, markers):
    phase = "p1"
    for marker in markers:
        if marker["timeMs"] > elapsed_ms:
            break
        if marker["key"] in {"p1", "intermission", "p2", "enrage"}:
            phase = marker["key"]
    return phase


def fetch_payload(client, report_id, fight, options, boss_id=None, amani_ids=None):
    casts = [
        event for event in client.events(report_id, "Casts", fight, hostility_type="Enemies")
        if ability_id(event) in MECHANIC_CASTS
    ]
    buffs = client.events(report_id, "Buffs", fight, ability_id=1290003, hostility_type="Enemies")
    inner_buffs = []
    amani_buffs = []
    if options.get("innerRealmReviewEnabled"):
        inner_buffs = client.events(report_id, "Buffs", fight, ability_id=1300514, hostility_type="Enemies")
    if options.get("hungeringPyreReviewEnabled"):
        amani_buffs = client.events(report_id, "Buffs", fight, ability_id=1297631, hostility_type="Enemies")
    deaths = client.events(report_id, "Deaths", fight)
    combatants = client.events(report_id, "CombatantInfo", fight)
    debuffs = []
    if options["essenceRendReviewEnabled"]:
        debuffs.extend(client.events(report_id, "Debuffs", fight, ability_id=1287434))
    if options["invokeInterruptReviewEnabled"]:
        debuffs.extend(client.events(report_id, "Debuffs", fight, ability_id=1299722))
    if options["hungeringPyreReviewEnabled"]:
        debuffs.extend(client.events(report_id, "Debuffs", fight, ability_id=1306666))
        debuffs.extend(client.events(report_id, "Debuffs", fight, ability_id=1294933))
    if options.get("innerRealmReviewEnabled"):
        for spell_id in (1290361, 1299988, 1300235):
            debuffs.extend(client.events(report_id, "Debuffs", fight, ability_id=spell_id))
    debuffs.extend(client.events(report_id, "Debuffs", fight, ability_id=1284109))
    damage = []
    wanted_damage = set()
    if options["essenceRendReviewEnabled"]:
        wanted_damage.add(1287434)
    if options["possessionBarrageReviewEnabled"]:
        wanted_damage.add(1292034)
    if options["hungeringPyreReviewEnabled"]:
        wanted_damage.add(1289855)
        wanted_damage.add(1289875)
        wanted_damage.add(1294933)
    if options.get("innerRealmReviewEnabled"):
        wanted_damage.add(1300239)
    wanted_damage.update({1284109, 1295085})
    if options["avoidableDamageReviewEnabled"]:
        wanted_damage.update(AVOIDABLE_DAMAGE)
        wanted_damage.add(1293214)
    for spell_id in sorted(wanted_damage):
        damage.extend(client.events(report_id, "DamageTaken", fight, ability_id=spell_id, include_resources=True))
    position_events = []
    if options["essenceRendReviewEnabled"] or options["possessionBarrageReviewEnabled"] or options["hungeringPyreReviewEnabled"]:
        position_events = client.events(report_id, "Resources", fight, include_resources=True)
    boss_position_events = []
    if boss_id is not None:
        boss_damage = client.events(
            report_id,
            "DamageDone",
            fight,
            target_id=boss_id,
            include_resources=True,
        )
        boss_position_events = compact_actor_position_events(boss_damage, boss_id)
    amani_damage = []
    if options.get("hungeringPyreReviewEnabled"):
        pyre_completions = [
            int(event.get("timestamp") or 0) for event in casts
            if ability_id(event) == 1289855 and event_type(event) == "cast"
        ]
        amani_end = min(
            int(fight["endTime"]),
            (max(pyre_completions) + 30_000) if pyre_completions else int(fight["endTime"]),
        )
        for amani_id in sorted(set(amani_ids or [])):
            amani_damage.extend(client.events(
                report_id,
                "DamageDone",
                fight,
                start_time=fight["startTime"],
                end_time=amani_end,
                target_id=amani_id,
                include_resources=True,
            ))
    return {
        "casts": casts,
        "buffs": buffs,
        "innerBuffs": inner_buffs,
        "amaniBuffs": amani_buffs,
        "deaths": deaths,
        "combatants": combatants,
        "debuffs": debuffs,
        "damage": damage,
        "positionEvents": position_events,
        "bossPositionEvents": boss_position_events,
        "amaniDamage": amani_damage,
        "friendlyCasts": client.events(report_id, "Casts", fight, hostility_type="Friendlies"),
        "interrupts": client.events(report_id, "Interrupts", fight),
    }


def build_player_catalog(actor_map, actor_type, combatants):
    combatant_by_player = {event.get("sourceID") or event.get("targetID"): event for event in combatants}
    roles = build_player_mechanic_roles(combatants)
    rows = {}
    for actor_id, name in actor_map.items():
        # actor_map contains every player who appeared anywhere in the report.
        # CombatantInfo is fight-scoped, so it is the authoritative roster here.
        if actor_type.get(actor_id) != "Player" or actor_id not in combatant_by_player:
            continue
        spec_id = combatant_spec_id(combatant_by_player.get(actor_id, {}))
        rows[actor_id] = {
            "id": actor_id,
            "name": name.split("-", 1)[0],
            "specID": spec_id,
            "role": roles.get(actor_id, "unknown"),
            "icon": spec_icon_slug(spec_id),
            "classColor": spec_class_color(spec_id),
            "localization": spec_localization(spec_id),
        }
    return rows


def arena_estimate(events, actor_type=None):
    points = [
        event_point(event) for event in events
        if not actor_type or actor_type.get(position_actor_id(event)) == "Player"
    ]
    points = [point for point in points if point]
    if len(points) < 6:
        return None
    center = (statistics.median(point[0] for point in points), statistics.median(point[1] for point in points))
    distances = sorted(math.dist(point, center) for point in points)
    radius = distances[min(len(distances) - 1, int(len(distances) * 0.95))]
    if radius <= 0:
        return None
    return {"centerX": center[0], "centerY": center[1], "radius": radius, "method": "all-player-position-samples-p95"}


def nearest_position(target_id, timestamp, damage, max_offset_ms):
    all_candidates = [
        event for event in damage
        if position_actor_id(event) == target_id
        and event_point(event)
    ]
    if not all_candidates:
        return None
    all_candidates.sort(key=lambda event: (abs(int(event.get("timestamp") or 0) - timestamp), 0 if int(event.get("timestamp") or 0) <= timestamp else 1))
    event = all_candidates[0]
    point = event_point(event)
    offset = int(event["timestamp"] - timestamp)
    return {
        "x": point[0],
        "y": point[1],
        "sampleTimestamp": int(event["timestamp"]),
        "sampleOffsetMs": offset,
        "sampleAbilityID": ability_id(event),
        "positionReliable": abs(offset) <= max_offset_ms,
    }


def analyze_essence_rend(fight, actor_map, debuffs, damage, arena, options, players=None):
    if not options["essenceRendReviewEnabled"]:
        return {"enabled": False, "placements": []}
    placements = []
    edge_ratio = float(options["essenceRendEdgeRatio"])
    minimum_distance_yards = float(options.get("essenceRendMinDistanceYards") or 20)
    if arena:
        arena["radiusYards"] = round(float(arena["radius"]) / 100, 1)
        arena["edgeThresholdYards"] = round(float(arena["radius"]) * edge_ratio / 100, 1)
    active = {}
    for event in sorted(debuffs, key=lambda row: int(row.get("timestamp") or 0)):
        if ability_id(event) != 1287434:
            continue
        target_id = event.get("targetID")
        if is_apply(event):
            active[target_id] = event
            continue
        if not is_remove(event):
            continue
        apply_event = active.pop(target_id, None)
        timestamp = int(event.get("timestamp") or 0)
        position = nearest_position(target_id, timestamp, damage, int(options["essenceRendMaxSampleOffsetMs"]))
        row = {
            **(player_ref(players or {}, actor_map, target_id) if players else {
                "targetID": target_id,
                "player": actor_name(actor_map, target_id).split("-", 1)[0],
            }),
            "timeMs": timestamp - fight["startTime"],
            "time": fmt_ms(timestamp - fight["startTime"]),
            "applyTimeMs": int(apply_event["timestamp"] - fight["startTime"]) if apply_event else None,
            "applyTime": fmt_ms(apply_event["timestamp"] - fight["startTime"]) if apply_event else None,
            "removeType": event_type(event),
            "counted": False,
            "countReason": "默认仅取证；未配置允许落点区域",
        }
        if position:
            row.update(position)
            if arena and position["positionReliable"]:
                distance_from_center = math.dist((position["x"], position["y"]), (arena["centerX"], arena["centerY"]))
                relative_radius = distance_from_center / arena["radius"]
                row["relativeRadius"] = round(relative_radius, 3)
                row["distanceFromCenterYards"] = round(distance_from_center / 100, 1)
                row["placementEstimate"] = "距离中场安全" if distance_from_center / 100 >= minimum_distance_yards else "太靠近中场"
                if options["essenceRendPlacementCountEnabled"] and distance_from_center / 100 < minimum_distance_yards:
                    row["counted"] = True
                    row["countReason"] = f"距中场 {distance_from_center / 100:.1f} 码，小于 20 码"
            elif position["positionReliable"]:
                row["placementEstimate"] = "场地中心未标定"
            else:
                row["placementEstimate"] = "坐标偏移过大"
        else:
            row["placementEstimate"] = "没有任何可用坐标样本"
        placements.append(row)
    return {
        "enabled": True,
        "spellID": 1287434,
        "minimumDistanceYards": minimum_distance_yards,
        "placementRule": "窗口内坐标用于落点；窗口外仍返回最近样本时间但不参与判责；不使用死亡事件代替落点",
        "arenaEstimate": arena,
        "placements": placements,
    }


def analyze_hungering_pyre(fight, actor_map, debuffs, damage, options, casts=None):
    if not options["hungeringPyreReviewEnabled"]:
        return {"enabled": False, "rounds": []}
    active = {}
    rounds = []
    for event in sorted(debuffs, key=lambda row: int(row.get("timestamp") or 0)):
        if ability_id(event) != 1306666:
            continue
        target_id = event.get("targetID")
        if is_apply(event):
            active[target_id] = event
            continue
        if not is_remove(event):
            continue
        applied = active.pop(target_id, None)
        timestamp = int(event.get("timestamp") or 0)
        damage_targets = sorted({
            row.get("targetID") for row in damage
            if ability_id(row) == 1289855
            and row.get("targetID") is not None
            and 0 <= int(row.get("timestamp") or 0) - timestamp <= 500
        })
        rounds.append({
            "index": len(rounds) + 1,
            "spellID": 1289855,
            "debuffID": 1306666,
            "targetID": target_id,
            "target": actor_name(actor_map, target_id).split("-", 1)[0],
            "applyTimeMs": int(applied["timestamp"] - fight["startTime"]) if applied else None,
            "applyTime": fmt_ms(applied["timestamp"] - fight["startTime"]) if applied else None,
            "timeMs": timestamp - fight["startTime"],
            "time": fmt_ms(timestamp - fight["startTime"]),
            "damageTargetIDs": damage_targets,
            "soakRadiusYards": float(options["hungeringPyreSoakRadiusYards"]),
            "evidenceTime": "1306666 removedebuff",
        })
    if not rounds:
        completed = [event for event in (casts or []) if ability_id(event) == 1289855 and event_type(event) == "cast"]
        for event in sorted(completed, key=lambda row: int(row.get("timestamp") or 0)):
            timestamp = int(event.get("timestamp") or 0)
            damage_targets = sorted({row.get("targetID") for row in damage if ability_id(row) == 1289855
                                     and row.get("targetID") is not None and -300 <= int(row.get("timestamp") or 0) - timestamp <= 1500})
            target_id = event.get("targetID")
            rounds.append({
                "index": len(rounds) + 1, "spellID": 1289855, "debuffID": None,
                "targetID": target_id, "target": actor_name(actor_map, target_id).split("-", 1)[0],
                "applyTimeMs": None, "applyTime": None, "timeMs": timestamp - fight["startTime"],
                "time": fmt_ms(timestamp - fight["startTime"]), "damageTargetIDs": damage_targets,
                "soakRadiusYards": float(options["hungeringPyreSoakRadiusYards"]), "evidenceTime": "1289855 cast completion",
            })
    return {
        "enabled": True,
        "spellID": 1289855,
        "debuffID": 1306666,
        "rounds": rounds,
        "rule": "以葬火点名 Debuff 消失时刻回放全团位置；10 码分摊圈先作为场景参照，不自动判责。",
    }


def analyze_leaks(fight, casts, markers, options):
    ignition_events = [event for event in casts if ability_id(event) == 1293664 and event_type(event) == "cast"]
    ritual_events = [event for event in casts if ability_id(event) == 1297624]
    advance_events = [event for event in casts if ability_id(event) == 1287533]
    burn_pulses = cluster_timestamps(ritual_events)
    baseline = set()
    for ignition in ignition_events:
        start = int(ignition["timestamp"])
        candidates = [pulse for pulse in burn_pulses if start - 300 <= pulse <= start + 6500]
        baseline.update(candidates[:5])
    extra_pulses = [pulse for pulse in burn_pulses if pulse not in baseline and phase_at(pulse - fight["startTime"], markers) in {"p1", "intermission"}]
    advances_by_instance = defaultdict(list)
    for event in advance_events:
        identity = (event.get("sourceID"), event.get("sourceInstance") or event.get("sourceInstanceID"))
        advances_by_instance[identity].append(int(event.get("timestamp") or 0))
    rows = []
    used_pulses = set()
    for identity, timestamps in advances_by_instance.items():
        last_advance = max(timestamps)
        adjacent = [pulse for pulse in extra_pulses if pulse not in used_pulses and 0 <= pulse - last_advance <= 2500]
        if not adjacent:
            continue
        pulse = min(adjacent)
        used_pulses.add(pulse)
        has_instance = identity[1] is not None
        rows.append({
            "sourceID": identity[0],
            "sourceInstance": identity[1],
            "timeMs": pulse - fight["startTime"],
            "time": fmt_ms(pulse - fight["startTime"]),
            "advanceToBurnMs": pulse - last_advance,
            "evidence": "add-instance + extra Ritual Burn" if has_instance else "extra Ritual Burn near final Gravebound Advance",
            "counted": bool(options["amaniLeakCountEnabled"] and has_instance),
            "countReason": "存在小怪实例与额外仪式灼烧相邻证据" if has_instance else "缺少小怪实例键，作为疑似漏怪展示",
        })
    unmatched = [pulse for pulse in extra_pulses if pulse not in used_pulses]
    return {
        "enabled": bool(options["amaniLeakReviewEnabled"]),
        "confirmedCount": sum(1 for row in rows if row["sourceInstance"] is not None),
        "suspectedCount": len(rows) + len(unmatched),
        "baselineBurnPulseCount": len(baseline),
        "extraBurnPulseCount": len(extra_pulses),
        "events": rows + [{
            "timeMs": pulse - fight["startTime"],
            "time": fmt_ms(pulse - fight["startTime"]),
            "evidence": "unmatched extra Ritual Burn",
            "counted": False,
            "countReason": "未能和单个阿曼尼实例闭环，暂不归责",
        } for pulse in unmatched],
    }


def infer_barrage_interceptor(
    timestamp, cast_timestamp, target_id, players, position_index, boss_ids,
    *, maximum_line_distance_yards=3.0,
):
    """Find the first player physically crossing the Boss-to-target projectile lane."""
    boss_state = next((
        state for state in (
            actor_state_at(position_index, boss_id, cast_timestamp, reliable_window_ms=3_000)
            for boss_id in boss_ids
        ) if state and state.get("reliable")
    ), None)
    target_state = actor_state_at(position_index, target_id, cast_timestamp, reliable_window_ms=3_000)
    if not boss_state or not target_state or not target_state.get("reliable"):
        return None
    bx, by = boss_state["x"], boss_state["y"]
    tx, ty = target_state["x"], target_state["y"]
    dx, dy = tx - bx, ty - by
    length_squared = dx * dx + dy * dy
    if length_squared <= 0:
        return None
    lane_length = math.sqrt(length_squared)
    candidates = []
    for player_id in players:
        if player_id == target_id:
            continue
        state = actor_state_at(position_index, player_id, timestamp, reliable_window_ms=3_000)
        if not state or not state.get("reliable"):
            continue
        projection = ((state["x"] - bx) * dx + (state["y"] - by) * dy) / length_squared
        # Ignore players behind the Boss, standing almost on the Boss, or already at
        # the intended target endpoint. They cannot explain an early collision.
        if not 0.08 <= projection <= 0.92:
            continue
        nearest_x = bx + projection * dx
        nearest_y = by + projection * dy
        line_distance = math.dist((state["x"], state["y"]), (nearest_x, nearest_y))
        if line_distance / 100 > maximum_line_distance_yards:
            continue
        candidates.append((projection, line_distance, player_id, state))
    if not candidates:
        return None
    projection, line_distance, player_id, state = min(candidates, key=lambda row: (row[0], row[1]))
    return {
        **player_ref(players, {}, player_id),
        "distanceToLaneYards": round(line_distance / 100, 1),
        "distanceFromBossYards": round(projection * lane_length / 100, 1),
        "targetDistanceYards": round(lane_length / 100, 1),
        "sampleOffsetMs": state.get("sampleOffsetMs"),
        "evidence": "first-player-on-boss-target-segment",
    }


def analyze_barrage(
    fight, actor_map, casts, damage, deaths, players=None, position_index=None, boss_ids=None,
):
    players = players or {}
    position_index = position_index or {}
    boss_ids = boss_ids or []
    cast_rows = sorted((event for event in casts if ability_id(event) == 1284103 and event_type(event) == "cast"), key=lambda event: event["timestamp"])
    damage_rows = [event for event in damage if ability_id(event) == 1292034]
    death_rows = [event for event in deaths if ability_id(event) == 1292034 or event.get("killingAbilityGameID") == 1292034]
    rounds = []
    for index, cast in enumerate(cast_rows, start=1):
        start = int(cast["timestamp"])
        end = int(cast_rows[index]["timestamp"]) if index < len(cast_rows) else min(fight["endTime"], start + 12_000)
        hits = [event for event in damage_rows if start <= int(event.get("timestamp") or 0) < end]
        waves = cluster_timestamps(hits, window_ms=220)
        wave_rows = []
        for wave_ts in waves:
            wave_hits = [event for event in hits if abs(int(event.get("timestamp") or 0) - wave_ts) <= 220]
            total = sum(event_amount(event) for event in wave_hits)
            low_health = []
            for hit in wave_hits:
                maximum = hit.get("maxHitPoints") or (hit.get("resources") or {}).get("maxHitPoints")
                current = hit.get("hitPoints") or (hit.get("resources") or {}).get("hitPoints")
                if maximum and current is not None:
                    before = min(float(maximum), float(current) + event_amount(hit))
                    if before / float(maximum) < 0.45:
                        low_health.append(actor_name(actor_map, hit.get("targetID")).split("-", 1)[0])
            wave_rows.append({
                "timestamp": wave_ts,
                "timeMs": wave_ts - fight["startTime"],
                "delayFromCastMs": wave_ts - start,
                "hitCount": len({event.get("targetID") for event in wave_hits}),
                "totalDamage": total,
                "lowHealthPlayers": sorted(set(low_health)),
                "interceptorCandidate": infer_barrage_interceptor(
                    wave_ts, start, cast.get("targetID"), players, position_index, boss_ids,
                ),
            })
        round_deaths = [event for event in death_rows if start <= int(event.get("timestamp") or 0) < end]
        rounds.append({
            "index": index,
            "timeMs": start - fight["startTime"],
            "time": fmt_ms(start - fight["startTime"]),
            "targetID": cast.get("targetID"),
            "target": actor_name(actor_map, cast.get("targetID")).split("-", 1)[0],
            "waves": wave_rows,
            "deaths": [actor_name(actor_map, event.get("targetID")).split("-", 1)[0] for event in round_deaths],
        })
    return rounds


def barrage_baseline(raw_fights):
    kill_waves = [wave for fight in raw_fights if fight["fight"].get("kill") for row in fight["barrage"] for wave in row["waves"]]
    all_waves = kill_waves or [wave for fight in raw_fights for row in fight["barrage"] for wave in row["waves"]]
    if not all_waves:
        return None
    return {
        "delayMedianMs": int(statistics.median(wave["delayFromCastMs"] for wave in all_waves)),
        "damagePerPlayerMedian": int(statistics.median(wave["totalDamage"] / max(1, wave["hitCount"]) for wave in all_waves)),
        "source": "kill" if kill_waves else "all-pulls",
    }


def apply_barrage_verdicts(rounds, baseline, enrage_time_ms, options):
    if not baseline:
        return
    for row in rounds:
        for wave in row["waves"]:
            per_player = wave["totalDamage"] / max(1, wave["hitCount"])
            early = wave["delayFromCastMs"] < baseline["delayMedianMs"] - 700
            high = per_player > baseline["damagePerPlayerMedian"] * 1.35
            during_enrage = enrage_time_ms is not None and wave["timeMs"] >= enrage_time_ms
            if during_enrage:
                verdict = "狂暴后的附身弹幕"
            elif early and high:
                verdict = "疑似被提前拦截，飞行距离不足"
            elif row["deaths"] and wave["lowHealthPlayers"]:
                verdict = "弹幕数值接近基线，死者入射前血量不足"
            else:
                verdict = "未见明显异常"
            wave["verdict"] = verdict
            wave["counted"] = bool(options["possessionBarrageCountEnabled"] and early and high and not during_enrage)


def analyze_invoke(fight, actor_map, debuffs, markers):
    rows = []
    for event in debuffs:
        if ability_id(event) != 1299722 or not is_apply(event):
            continue
        elapsed = int(event["timestamp"] - fight["startTime"])
        rows.append({
            "timeMs": elapsed,
            "time": fmt_ms(elapsed),
            "phase": phase_at(elapsed, markers),
            "playerID": event.get("targetID"),
            "player": actor_name(actor_map, event.get("targetID")).split("-", 1)[0],
            "spellID": 1299722,
            "interruptedAbilityID": event.get("extraAbilityGameID"),
            "interruptedAbility": SPELLS.get(event.get("extraAbilityGameID"), str(event.get("extraAbilityGameID"))) if event.get("extraAbilityGameID") else "未记录施法技能",
        })
    return rows


def analyze_transition_assignments(fight, actor_map, player_catalog, pyre_rounds, debuffs, damage):
    slithering = [event for event in debuffs if ability_id(event) == 1294933 and is_apply(event)]
    for row in pyre_rounds:
        if row.get("targetID") not in player_catalog:
            row["targetID"] = None
            row["target"] = "当前坦克（WCL 未返回主目标）"
        timestamp = int(fight["startTime"] + row["timeMs"])
        snake_events = [event for event in slithering if -1500 <= int(event.get("timestamp") or 0) - timestamp <= 3500]
        snake_ids = sorted({event.get("targetID") for event in snake_events if event.get("targetID") is not None})
        row["soakPlayerRefs"] = [player_ref(player_catalog, actor_map, player_id) for player_id in row.get("damageTargetIDs", []) if player_id in player_catalog]
        row["soakPlayersByDamage"] = [ref["player"] for ref in row["soakPlayerRefs"]]
        row["slitheringFlameRefs"] = [player_ref(player_catalog, actor_map, player_id) for player_id in snake_ids if player_id in player_catalog]
        row["slitheringFlamePlayers"] = [ref["player"] for ref in row["slitheringFlameRefs"]]
        row["nonSoakers"] = row["slitheringFlamePlayers"]
        row["rule"] = "噬灭烈焰伤害目标为分摊者；同轮获得蛇形烈焰的玩家为未分摊组。"
    return pyre_rounds


def aura_intervals(events, spell_id, fight_end):
    active = {}
    intervals = []
    for event in sorted(events, key=lambda row: int(row.get("timestamp") or 0)):
        if int(ability_id(event) or 0) != int(spell_id):
            continue
        target_id = event.get("targetID")
        if is_apply(event):
            active.setdefault(target_id, event)
        elif is_remove(event) and target_id in active:
            applied = active.pop(target_id)
            intervals.append({
                "targetID": target_id,
                "start": int(applied.get("timestamp") or 0),
                "end": int(event.get("timestamp") or 0),
                "removeType": event_type(event),
            })
    for target_id, applied in active.items():
        intervals.append({
            "targetID": target_id,
            "start": int(applied.get("timestamp") or 0),
            "end": int(fight_end),
            "removeType": "fight-end",
        })
    return sorted(intervals, key=lambda row: (row["start"], row["targetID"] or 0))


def _trajectory_points(position_index, actor_id, start, end):
    points = []
    for timestamp in (start, end):
        state = actor_state_at(position_index, actor_id, timestamp, reliable_window_ms=2_000)
        if state and state.get("reliable"):
            points.append((timestamp, float(state["x"]), float(state["y"])))
    points.extend(
        (int(row["timestamp"]), float(row["x"]), float(row["y"]))
        for row in position_index.get(actor_id) or []
        if start <= int(row["timestamp"]) <= end
    )
    return sorted(set(points))


def _nearest_path_distance(points, point):
    if not points:
        return None
    px, py = point
    best = (math.inf, points[0][0])
    for timestamp, x, y in points:
        best = min(best, (math.dist((x, y), (px, py)), timestamp))
    for left, right in zip(points, points[1:]):
        lt, lx, ly = left
        rt, rx, ry = right
        if rt - lt > 3_000:
            continue
        dx, dy = rx - lx, ry - ly
        length_sq = dx * dx + dy * dy
        ratio = 0 if length_sq <= 0 else max(0.0, min(1.0, ((px - lx) * dx + (py - ly) * dy) / length_sq))
        x, y = lx + ratio * dx, ly + ratio * dy
        best = min(best, (math.dist((x, y), (px, py)), int(lt + ratio * (rt - lt))))
    return {"distanceYards": round(best[0] / 100, 1), "timestamp": best[1]}


def reconstruct_amani_corpses(fight, amani_damage, amani_buffs):
    corpses = []
    last_death = {}
    for event in sorted(amani_damage, key=lambda row: int(row.get("timestamp") or 0)):
        if event.get("hitPoints") != 0 or event.get("x") is None or event.get("y") is None:
            continue
        identity = (event.get("targetID"), event.get("targetInstance"))
        timestamp = int(event.get("timestamp") or 0)
        if timestamp - last_death.get(identity, -10_000) < 1_000:
            continue
        last_death[identity] = timestamp
        corpses.append({
            "uid": f"{identity[0]}:{identity[1]}:{timestamp}",
            "actorID": identity[0],
            "instance": identity[1],
            "deathTimestamp": timestamp,
            "deathTimeMs": timestamp - fight["startTime"],
            "deathTime": fmt_ms(timestamp - fight["startTime"]),
            "x": float(event["x"]),
            "y": float(event["y"]),
            "awakenedTimestamp": None,
        })
    wake_events = []
    seen_wakes = set()
    for event in sorted(amani_buffs, key=lambda row: int(row.get("timestamp") or 0)):
        if int(ability_id(event) or 0) != 1297631 or not is_apply(event):
            continue
        identity = (event.get("targetID"), event.get("targetInstance"))
        timestamp = int(event.get("timestamp") or 0)
        key = (*identity, timestamp)
        if key in seen_wakes:
            continue
        seen_wakes.add(key)
        candidates = [
            corpse for corpse in corpses
            if (corpse["actorID"], corpse["instance"]) == identity
            and corpse["deathTimestamp"] < timestamp
            and corpse["awakenedTimestamp"] is None
        ]
        corpse = max(candidates, key=lambda row: row["deathTimestamp"]) if candidates else None
        if corpse:
            corpse["awakenedTimestamp"] = timestamp
        wake_events.append({
            "timestamp": timestamp,
            "timeMs": timestamp - fight["startTime"],
            "time": fmt_ms(timestamp - fight["startTime"]),
            "actorID": identity[0],
            "instance": identity[1],
            "corpseUID": corpse["uid"] if corpse else None,
        })
    return corpses, wake_events


def analyze_corpse_cremation(
    fight, actor_map, players, pyre_rounds, debuffs, position_index,
    amani_damage, amani_buffs, options,
):
    corpses, wake_events = reconstruct_amani_corpses(fight, amani_damage, amani_buffs)
    snake_intervals = aura_intervals(debuffs, 1294933, fight["endTime"])
    consumed = set()
    burn_radius = float(options.get("corpseBurnRadiusYards") or 5)
    attempt_radius = float(options.get("corpseAttemptRadiusYards") or 10)
    for index, round_row in enumerate(pyre_rounds):
        timestamp = int(fight["startTime"] + round_row["timeMs"])
        next_timestamp = (
            int(fight["startTime"] + pyre_rounds[index + 1]["timeMs"])
            if index + 1 < len(pyre_rounds) else min(int(fight["endTime"]), timestamp + 30_000)
        )
        intervals = [row for row in snake_intervals if -1_500 <= row["start"] - timestamp <= 3_500]
        round_wakes = [row for row in wake_events if timestamp <= row["timestamp"] < next_timestamp]
        wake_uids = {row["corpseUID"] for row in round_wakes if row.get("corpseUID")}
        available_at_round_start = [
            corpse for corpse in corpses
            if corpse["deathTimestamp"] < timestamp
            and corpse["uid"] not in consumed
            and not (corpse.get("awakenedTimestamp") and corpse["awakenedTimestamp"] < timestamp)
        ]
        player_rows = []
        crossing_candidates = []
        for interval in intervals:
            player_id = interval["targetID"]
            interaction_start = interval["start"]
            interaction_end = interval["end"]
            marked_state = actor_state_at(position_index, player_id, interval["start"], reliable_window_ms=2_000)
            corpses_at_mark = [
                corpse for corpse in corpses
                if corpse["deathTimestamp"] <= interval["start"]
                and corpse["uid"] not in consumed
                and not (
                    corpse.get("awakenedTimestamp")
                    and corpse["awakenedTimestamp"] <= interval["start"]
                )
            ]
            nearest_at_mark = None
            if marked_state and marked_state.get("reliable") and corpses_at_mark:
                nearest_corpse = min(
                    corpses_at_mark,
                    key=lambda corpse: math.dist(
                        (float(marked_state["x"]), float(marked_state["y"])),
                        (corpse["x"], corpse["y"]),
                    ),
                )
                nearest_at_mark = {
                    "corpseUID": nearest_corpse["uid"],
                    "instance": nearest_corpse["instance"],
                    "x": round(nearest_corpse["x"], 1),
                    "y": round(nearest_corpse["y"], 1),
                    "distanceYards": round(
                        math.dist(
                            (float(marked_state["x"]), float(marked_state["y"])),
                            (nearest_corpse["x"], nearest_corpse["y"]),
                        ) / 100,
                        1,
                    ),
                }
            distances = []
            relevant_corpses = [
                corpse for corpse in corpses
                if corpse["deathTimestamp"] <= interaction_end
                and corpse["uid"] not in consumed
                and not (
                    corpse.get("awakenedTimestamp")
                    and corpse["awakenedTimestamp"] <= interaction_start
                )
            ]
            position_available = bool(
                _trajectory_points(position_index, player_id, interaction_start, interaction_end)
            )
            for corpse in relevant_corpses:
                corpse_window_start = max(interaction_start, corpse["deathTimestamp"])
                corpse_window_end = interaction_end
                if corpse.get("awakenedTimestamp"):
                    corpse_window_end = min(corpse_window_end, corpse["awakenedTimestamp"])
                if corpse_window_end < corpse_window_start:
                    continue
                points = _trajectory_points(
                    position_index, player_id, corpse_window_start, corpse_window_end,
                )
                position_available = position_available or bool(points)
                nearest = _nearest_path_distance(points, (corpse["x"], corpse["y"]))
                if nearest:
                    distances.append((nearest["distanceYards"], nearest["timestamp"], corpse))
            distances.sort(key=lambda row: (row[0], row[1]))
            nearest = distances[0] if distances else None
            ref = player_ref(players, actor_map, player_id)
            player_row = {
                **ref,
                "markedAtMs": interval["start"] - fight["startTime"],
                "markedAt": fmt_ms(interval["start"] - fight["startTime"]),
                "auraStartMs": interaction_start - fight["startTime"],
                "auraEndMs": interaction_end - fight["startTime"],
                "auraStart": fmt_ms(interaction_start - fight["startTime"]),
                "auraEnd": fmt_ms(interaction_end - fight["startTime"]),
                "positionAvailable": position_available,
                "markedPositionAvailable": bool(marked_state and marked_state.get("reliable")),
                "nearestCorpseAtMark": nearest_at_mark,
                "nearestCorpseYards": nearest[0] if nearest else None,
                "attempted": bool(nearest and nearest[0] <= attempt_radius),
                "burnedCorpses": [],
                "status": "未取得可靠移动坐标" if not position_available else "持续期间未接近任何尸体",
            }
            if player_row["attempted"]:
                player_row["status"] = "已尝试接近尸体"
            for distance, crossing_time, corpse in distances:
                if distance <= burn_radius and corpse["uid"] not in wake_uids:
                    crossing_candidates.append((crossing_time, distance, corpse, player_row))
            player_rows.append(player_row)
        for crossing_time, distance, corpse, player_row in sorted(crossing_candidates, key=lambda row: (row[0], row[1])):
            if corpse["uid"] in consumed:
                continue
            consumed.add(corpse["uid"])
            player_row["burnedCorpses"].append({
                "corpseUID": corpse["uid"],
                "instance": corpse["instance"],
                "timeMs": crossing_time - fight["startTime"],
                "time": fmt_ms(crossing_time - fight["startTime"]),
                "distanceYards": distance,
            })
            player_row["status"] = "已焚烧尸体"
        consumed.update(wake_uids)
        no_attempt = [
            row for row in player_rows
            if round_wakes and row["positionAvailable"] and not row["attempted"]
        ]
        round_row["corpseCremation"] = {
            "burnRadiusYards": burn_radius,
            "attemptRadiusYards": attempt_radius,
            "availableCorpseCount": len(available_at_round_start),
            "inferredBurnedCount": sum(len(row["burnedCorpses"]) for row in player_rows),
            "awakenedHostCount": len(round_wakes),
            "awakenedHosts": round_wakes,
            "players": player_rows,
            "noAttemptRefs": no_attempt,
            "rule": "蛇形烈焰（1294933）的约 8 秒持续时间是尸体交互窗口；轨迹进入尸体 5 码视为焚烧、进入 10 码视为尝试。随后约 20 秒的焚化（1289875）仅为 DOT，不用于判断尸体交互。觉醒宿主是失败的直接证据。",
        }
    return {"corpses": corpses, "awakenedHosts": wake_events}


def _configured_inner_teams(options, players):
    by_name = {row.get("name", "").split("-", 1)[0]: player_id for player_id, row in players.items()}
    configured = {}
    for team, members in (options.get("innerRealmTeams") or {}).items():
        resolved = set()
        for member in members or []:
            if isinstance(member, int) or str(member).isdigit():
                player_id = int(member)
            else:
                player_id = by_name.get(str(member).split("-", 1)[0])
            if player_id in players:
                resolved.add(player_id)
        configured[str(team)] = resolved
    return configured


def analyze_inner_realm(fight, actor_map, players, payload, options):
    if not options.get("innerRealmReviewEnabled") or int(fight.get("difficulty") or 0) != 5:
        return {"enabled": False, "rounds": [], "groupEvidenceAvailable": False}
    well_intervals = aura_intervals(payload.get("innerBuffs") or [], 1300514, fight["endTime"])
    inside = aura_intervals(payload.get("debuffs") or [], 1299988, fight["endTime"])
    fatigue = aura_intervals(payload.get("debuffs") or [], 1300235, fight["endTime"])
    mind_controls = [
        event for event in payload.get("debuffs") or []
        if int(ability_id(event) or 0) == 1290361 and is_apply(event)
    ]
    curse_casts = [
        event for event in payload.get("casts") or []
        if int(ability_id(event) or 0) == 1300238
    ]
    curse_interrupts = [
        event for event in payload.get("interrupts") or []
        if int(event.get("extraAbilityGameID") or 0) == 1300238
    ]
    swirl_damage = [
        event for event in payload.get("damage") or []
        if int(ability_id(event) or 0) == 1300239 and event_amount(event) > 0
    ]
    configured_teams = _configured_inner_teams(options, players)
    owner_map = payload.get("actorOwnerMap") or {}
    rotation = [str(value) for value in (options.get("innerRealmRotation") or [])]
    death_time = {}
    for event in payload.get("deaths") or []:
        target_id = event.get("targetID")
        death_time[target_id] = min(death_time.get(target_id, int(event["timestamp"])), int(event["timestamp"]))
    rounds = []
    row_index = 0
    for well_index, well in enumerate(well_intervals, start=1):
        well_start, well_end = well["start"], well["end"]
        well_entries = sorted(
            [row for row in inside if well_start - 1_500 <= row["start"] <= well_end + 1_500],
            key=lambda row: row["start"],
        )
        clusters = []
        for entrant in well_entries:
            if not clusters or entrant["start"] - clusters[-1][-1]["start"] > 10_000:
                clusters.append([])
            clusters[-1].append(entrant)
        if not clusters:
            clusters = [[]]
        for attempt_index, entrants in enumerate(clusters, start=1):
            row_index += 1
            cluster_start = min((row["start"] for row in entrants), default=well_start)
            next_start = (
                min(row["start"] for row in clusters[attempt_index])
                if attempt_index < len(clusters) else well_end
            )
            start = well_start if attempt_index == 1 else cluster_start
            end = max(start, min(well_end, next_start))
            entrant_ids = {row["targetID"] for row in entrants if row["targetID"] in players}
            expected_team = rotation[(well_index - 1) % len(rotation)] if rotation else None
            expected_ids = set(configured_teams.get(expected_team) or []) if expected_team else set()
            expected_alive = {player_id for player_id in expected_ids if death_time.get(player_id, math.inf) > start}
            missing = expected_alive - entrant_ids
            unexpected = entrant_ids - expected_alive if expected_ids else set()
            fatigued = {
                entrant["targetID"] for entrant in entrants
                if any(row["targetID"] == entrant["targetID"] and row["start"] <= entrant["start"] < row["end"] for row in fatigue)
            }
            attempts = [row for row in curse_casts if start <= int(row.get("timestamp") or 0) < end]
            successes = [row for row in attempts if event_type(row) == "cast"]
            interrupts = [row for row in curse_interrupts if start <= int(row.get("timestamp") or 0) < end]
            controlled_ids = {
                row.get("targetID") for row in mind_controls
                if start <= int(row.get("timestamp") or 0) < end and row.get("targetID") in players
            }
            hit_by_player = defaultdict(list)
            for event in swirl_damage:
                if start <= int(event.get("timestamp") or 0) < end:
                    hit_by_player[event.get("targetID")].append(event)
            hit_rows = []
            for player_id, events in hit_by_player.items():
                hit_rows.append({
                    **player_ref(players, actor_map, player_id),
                    "hitCount": len(events),
                    "totalDamage": sum(event_amount(event) for event in events),
                })
            assignment_configured = bool(expected_ids)
            assignment_ok = assignment_configured and not missing and not unexpected and not fatigued
            rounds.append({
                "index": row_index,
                "wellIndex": well_index,
                "attemptIndex": attempt_index,
                "timeMs": start - fight["startTime"],
                "time": fmt_ms(start - fight["startTime"]),
                "endTimeMs": end - fight["startTime"],
                "endTime": fmt_ms(end - fight["startTime"]),
                "expectedTeam": expected_team,
                "assignmentConfigured": assignment_configured,
                "assignmentStatus": "正常" if assignment_ok else ("异常" if assignment_configured else "未配置小队名单"),
                "entrantRefs": [player_ref(players, actor_map, player_id) for player_id in sorted(entrant_ids)],
                "missingRefs": [player_ref(players, actor_map, player_id) for player_id in sorted(missing)],
                "unexpectedRefs": [player_ref(players, actor_map, player_id) for player_id in sorted(unexpected)],
                "fatiguedRefs": [player_ref(players, actor_map, player_id) for player_id in sorted(fatigued)],
                "curseCastCount": len(interrupts) + len(successes),
                "curseInterruptCount": len(interrupts),
                "curseSuccessCount": len(successes),
                "interrupts": [{
                    "timeMs": int(row["timestamp"]) - fight["startTime"],
                    "time": fmt_ms(int(row["timestamp"]) - fight["startTime"]),
                    **player_ref(players, actor_map, owner_map.get(row.get("sourceID")) or row.get("sourceID")),
                    "spellID": row.get("abilityGameID"),
                    "spell": SPELLS.get(row.get("abilityGameID"), spell_name(row.get("abilityGameID"))),
                } for row in interrupts],
                "mindControlledRefs": [player_ref(players, actor_map, player_id) for player_id in sorted(controlled_ids)],
                "swirlingSpirit": sorted(hit_rows, key=lambda row: (row["hitCount"], row["totalDamage"]), reverse=True),
            })
    return {
        "enabled": True,
        "spellIDs": [1299988, 1300235, 1300238, 1300239, 1290361],
        "groupEvidenceAvailable": False,
        "groupEvidenceNote": "WCL 不提供游戏内小队编号；名单配置后才进行 3/4 队轮换判定。",
        "configuredTeams": sorted(configured_teams),
        "rotation": rotation,
        "rounds": rounds,
        "totals": {
            "roundCount": len(rounds),
            "curseInterruptCount": sum(row["curseInterruptCount"] for row in rounds),
            "curseSuccessCount": sum(row["curseSuccessCount"] for row in rounds),
            "mindControlledCount": sum(len(row["mindControlledRefs"]) for row in rounds),
            "swirlingSpiritHitCount": sum(sum(player["hitCount"] for player in row["swirlingSpirit"]) for row in rounds),
        },
    }


def analyze_tank_swap(fight, actor_map, players, debuffs, friendly_casts, barrage, survival):
    tank_ids = {player_id for player_id, player in players.items() if player.get("role") == "tank"}
    stack_rows = []
    stacks_by_player = defaultdict(list)
    stack_events = [
        event for event in debuffs
        if int(ability_id(event) or 0) in HOLLOWING_STACK_IDS
        and event.get("targetID") in tank_ids
    ]
    explicit_stack_keys = {
        (event.get("targetID"), int(event.get("timestamp") or 0))
        for event in stack_events
        if event_type(event) in {"applydebuffstack", "removedebuffstack"}
    }
    for event in sorted(stack_events, key=lambda row: int(row.get("timestamp") or 0)):
        spell_id = int(ability_id(event) or 0)
        if spell_id not in HOLLOWING_STACK_IDS or event.get("targetID") not in tank_ids:
            continue
        timestamp = int(event.get("timestamp") or 0)
        kind = event_type(event)
        if kind in {"refreshdebuff", "refreshdebuffstack"} and (
            event.get("targetID"), timestamp
        ) in explicit_stack_keys:
            # WCL 会在同一毫秒同时给出 stack=N 和 refresh(stack=1)；后者只是刷新持续时间，
            # 不能覆盖真实层数。
            continue
        if kind in {"applydebuff", "applydebuffstack", "refreshdebuff", "refreshdebuffstack"}:
            stack = int(event.get("stack") or 1)
        elif kind in {"removedebuff", "removedebuffstack"}:
            stack = int(event.get("stack") or 0)
        else:
            continue
        row = {
            **player_ref(players, actor_map, event.get("targetID")),
            "timeMs": timestamp - fight["startTime"],
            "time": fmt_ms(timestamp - fight["startTime"]),
            "eventType": kind,
            "stack": stack,
            "absoluteTime": timestamp,
            "spellID": spell_id,
        }
        stack_rows.append(row)
        stacks_by_player[event.get("targetID")].append(row)

    def stack_before(player_id, timestamp):
        prior = [row for row in stacks_by_player.get(player_id, []) if row["absoluteTime"] <= timestamp]
        return prior[-1]["stack"] if prior else None

    taunts = []
    for event in friendly_casts:
        spell_id = int(ability_id(event) or 0)
        if spell_id not in TAUNT_SPELLS or event.get("sourceID") not in tank_ids or event_type(event) != "cast":
            continue
        timestamp = int(event.get("timestamp") or 0)
        target_id = event.get("targetID")
        taunts.append({
            **player_ref(players, actor_map, event.get("sourceID")),
            "timeMs": timestamp - fight["startTime"],
            "time": fmt_ms(timestamp - fight["startTime"]),
            "spellID": spell_id,
            "spell": TAUNT_SPELLS[spell_id],
            "targetID": target_id,
            "target": source_name(actor_map, target_id, SOURCE_NAMES) if target_id else "—",
        })
    tank_deaths = []
    for row in survival.get("timeline", []):
        if row.get("kind") != "death" or row.get("playerID") not in tank_ids:
            continue
        tank_deaths.append({
            **row,
            "ability": row.get("ability") or spell_name(row.get("abilityID"), SPELLS),
            "deathCause": row.get("deathCause") or ("fall" if not row.get("abilityID") else "ability"),
        })
    barrage_stacks = []
    for barrage_row in barrage:
        timestamp = int(fight["startTime"] + barrage_row["timeMs"])
        stacks = []
        for player_id in tank_ids:
            stack_value = stack_before(player_id, timestamp)
            stacks.append({
                **player_ref(players, actor_map, player_id),
                "stack": stack_value if stack_value is not None else "—",
            })
        barrage_stacks.append({
            "index": barrage_row["index"], "time": barrage_row["time"], "timeMs": barrage_row["timeMs"],
            "targetID": barrage_row.get("targetID"), "target": barrage_row.get("target"), "tanks": stacks,
        })
    return {
        "tanks": [players[player_id] for player_id in tank_ids],
        "hollowingStacks": stack_rows,
        "peakStacks": [{
            **player_ref(players, actor_map, player_id),
            "peakStack": max((row["stack"] for row in stack_rows if row["playerID"] == player_id), default=0),
        } for player_id in tank_ids],
        "barrageStacks": barrage_stacks,
        "taunts": sorted(taunts, key=lambda row: row["timeMs"]),
        "barrageTargets": [{"index": row["index"], "time": row["time"], "targetID": row.get("targetID"), "target": row.get("target")} for row in barrage],
        "tankDeaths": tank_deaths,
    }


def build_field_replay_events(fight, markers, player_catalog, boss_ids, actor_map, position_index, deaths, placements, barrage_rounds, pyre_rounds, arena):
    rows = []
    for index, placement in enumerate(placements, start=1):
        timestamp = int(fight["startTime"] + placement["timeMs"])
        rows.append({
            "id": f"essence-{index}",
            "eventType": "essenceRend",
            "index": index,
            "timeMs": placement["timeMs"],
            "time": placement["time"],
            "phase": phase_at(placement["timeMs"], markers),
            "title": f"精华撕裂解除 · {placement['player']}",
            "targetID": placement.get("targetID"),
            "target": placement.get("player"),
            "placement": placement,
            "snapshot": snapshot_at(timestamp, player_catalog, boss_ids, actor_map, position_index, deaths, arena),
        })
    for barrage in barrage_rounds:
        timestamp = int(fight["startTime"] + barrage["timeMs"])
        rows.append({
            "id": f"barrage-{barrage['index']}",
            "eventType": "possessionBarrage",
            "index": barrage["index"],
            "timeMs": barrage["timeMs"],
            "time": barrage["time"],
            "phase": phase_at(barrage["timeMs"], markers),
            "title": f"附身弹幕 #{barrage['index']}",
            "targetID": barrage.get("targetID"),
            "target": barrage.get("target"),
            "barrage": barrage,
            "snapshot": snapshot_at(timestamp, player_catalog, boss_ids, actor_map, position_index, deaths, arena),
        })
    for pyre in pyre_rounds:
        timestamp = int(fight["startTime"] + pyre["timeMs"])
        snapshot = snapshot_at(timestamp, player_catalog, boss_ids, actor_map, position_index, deaths, arena)
        target = next((player for player in snapshot["players"] if player["id"] == pyre.get("targetID")), None)
        target_position = target.get("position") if target else None
        soak_players = []
        spread_players = []
        missing_players = []
        for player in snapshot["players"]:
            position = player.get("position")
            if not position or not target_position:
                player["mechanicState"] = "unknown"
                missing_players.append(player["name"])
                continue
            distance_yards = math.dist(
                (position["x"], position["y"]),
                (target_position["x"], target_position["y"]),
            ) / 100
            player["distanceFromPyreTargetYards"] = round(distance_yards, 1)
            if distance_yards <= pyre["soakRadiusYards"]:
                player["mechanicState"] = "soak"
                soak_players.append(player["name"])
            else:
                player["mechanicState"] = "spread"
                spread_players.append(player["name"])
        pyre["soakPlayers"] = soak_players
        pyre["spreadPlayers"] = spread_players
        pyre["missingPositionPlayers"] = missing_players
        rows.append({
            "id": f"pyre-{pyre['index']}",
            "eventType": "hungeringPyre",
            "index": pyre["index"],
            "timeMs": pyre["timeMs"],
            "time": pyre["time"],
            "phase": phase_at(pyre["timeMs"], markers),
            "title": f"噬灭烈焰分散 #{pyre['index']} · {pyre['target']}",
            "targetID": pyre.get("targetID"),
            "target": pyre.get("target"),
            "pyre": pyre,
            "snapshot": snapshot,
        })
    return sorted(rows, key=lambda row: (row["timeMs"], row["eventType"], row["index"]))


def analyze_avoidable(fight, actor_map, actor_type, damage, deaths, players=None):
    players = players or {}
    death_keys = {(event.get("targetID"), event.get("killingAbilityGameID") or ability_id(event)) for event in deaths}
    board = defaultdict(lambda: defaultdict(lambda: {"hitCount": 0, "totalDamage": 0, "deathCount": 0, "events": []}))
    for event in damage:
        spell_id = ability_id(event)
        if spell_id not in AVOIDABLE_DAMAGE:
            continue
        target_id = event.get("targetID")
        if actor_type.get(target_id) != "Player":
            continue
        if event_amount(event) <= 0 and (target_id, spell_id) not in death_keys:
            # Immune / reflect / dodge / deflect rows can still be emitted by WCL;
            # they are evidence of avoiding the mechanic, not a landed hit.
            continue
        row = board[spell_id][target_id]
        row["hitCount"] += 1
        row["totalDamage"] += event_amount(event)
        elapsed = int(event["timestamp"] - fight["startTime"])
        row["events"].append({"timeMs": elapsed, "time": fmt_ms(elapsed), "amount": event_amount(event)})
    output = {}
    for spell_id, targets in board.items():
        output[str(spell_id)] = []
        for target_id, row in targets.items():
            ref = player_ref(players, actor_map, target_id)
            row.update({
                **ref,
                "name": ref["player"],
                "spellID": spell_id,
                "spellName": AVOIDABLE_DAMAGE[spell_id],
                "deathCount": int((target_id, spell_id) in death_keys),
            })
            output[str(spell_id)].append(row)
        output[str(spell_id)].sort(key=lambda row: (row["deathCount"], row["totalDamage"], row["hitCount"]), reverse=True)
    return output


def top_death_ability(deaths):
    counts = defaultdict(int)
    for event in deaths:
        spell_id = event.get("killingAbilityGameID") or ability_id(event)
        if spell_id:
            counts[int(spell_id)] += 1
    return max(counts, key=counts.get) if counts else None


def classify_fight(raw):
    fight = raw["fight"]
    markers = raw["markers"]
    deaths = raw["payload"]["deaths"]
    end_phase = phase_at(fight["endTime"] - fight["startTime"] - 1, markers)
    enrage_marker = next((row for row in markers if row["key"] == "enrage"), None)
    barrage_deaths = sum(len(row["deaths"]) for row in raw["barrage"])
    avoidable_deaths = sum(row["deathCount"] for rows in raw["avoidable"].values() for row in rows)
    if fight.get("kill"):
        code, label = "kill", "击杀"
        reason = "击杀场仍保留漏怪、站位、弹幕和可躲伤害问题，不因过本自动清零。"
    elif enrage_marker:
        code, label = "enrage", "解缚之怒狂暴"
        reason = "Boss 达到 100 能量后进入解缚之怒；狂暴后的附身弹幕不再归为单个玩家挡错。"
    elif barrage_deaths:
        abnormal = any("提前拦截" in wave.get("verdict", "") for row in raw["barrage"] for wave in row["waves"])
        code, label = ("barrage_intercept", "附身弹幕路径异常") if abnormal else ("barrage_health", "附身弹幕期间团血崩溃")
        reason = "附身弹幕造成直接减员；结合飞行延迟、单人均伤与命中前血量区分挡线和治疗压力。"
    elif end_phase == "intermission":
        code, label = "intermission", "苏醒仪式转场失败"
        reason = "战斗结束于回响转场；优先检查分摊、焚烧尸体和转场残余小怪。"
    elif raw["leaks"]["suspectedCount"]:
        code, label = "amani_leak", "阿曼尼漏怪推动时间轴"
        reason = "观察到额外仪式灼烧与阿曼尼推进相邻；该结论按证据完整度区分确认与疑似。"
    elif avoidable_deaths:
        code, label = "avoidable", "可躲避机制减员"
        reason = "移动黑圈、尸体枯萎或井口伤害造成直接减员。"
    else:
        spell_id = top_death_ability(deaths)
        code, label = "unresolved", f"死亡链待复核（{SPELLS.get(spell_id, spell_id or '无致死技能')}）"
        reason = "当前事件不足以把灭团归给单一机制，保留死亡链供人工复核。"
    return {
        "code": code,
        "label": label,
        "reason": reason,
        "endPhase": end_phase,
        "endPhaseLabel": {"p1": "P1", "intermission": "苏醒仪式", "p2": "P2", "enrage": "狂暴"}.get(end_phase, end_phase),
    }


def merge_avoidable(global_board, local_board):
    for spell_id, rows in local_board.items():
        for row in rows:
            key = row["playerID"]
            target = global_board[spell_id].get(key)
            if target is None:
                target = {**row, "events": []}
                global_board[spell_id][key] = target
            else:
                target["hitCount"] += row["hitCount"]
                target["totalDamage"] += row["totalDamage"]
                target["deathCount"] += row["deathCount"]
            target["events"].extend(row["events"])


def _death_count_before(pull, time_ms):
    return len({
        row.get("playerID") for row in (pull.get("deathTimeline") or [])
        if row.get("kind") == "death" and int(row.get("timeMs") or 0) <= int(time_ms or 0)
    })


def _mechanic_overview(rendered, options=None):
    threshold = int((options or {}).get("raidCollapseDeathThreshold") or 8)
    corpse_failures = []
    close_essence = []
    barrage_rounds = []
    inner_failures = []
    avoidable_deaths = []
    for pull in rendered:
        mechanics = pull.get("nakzali") or {}
        for round_row in (mechanics.get("hungeringPyre") or {}).get("rounds") or []:
            cremation = round_row.get("corpseCremation") or {}
            if not cremation.get("awakenedHostCount"):
                continue
            evidence_time = (cremation.get("awakenedHosts") or [{}])[0].get("timeMs", round_row.get("timeMs"))
            death_count = _death_count_before(pull, evidence_time)
            if death_count > threshold:
                continue
            for ref in cremation.get("noAttemptRefs") or []:
                corpse_failures.append(nightly_detail(
                    pull,
                    round_row.get("time"),
                    f"噬灭烈焰 #{round_row.get('index')} 后触发觉醒宿主；{ref.get('player')} 的蛇形烈焰轨迹未进入任意尸体 10 码范围",
                    player=ref.get("player"),
                    classColor=ref.get("classColor"),
                    raidDeathCountBefore=death_count,
                ))
        for round_row in (mechanics.get("possessionBarrage") or {}).get("rounds") or []:
            abnormal = [
                wave for wave in round_row.get("waves") or []
                if "提前拦截" in str(wave.get("verdict") or "")
            ]
            if not abnormal:
                continue
            candidate = next((
                wave.get("interceptorCandidate") for wave in abnormal
                if wave.get("interceptorCandidate")
            ), None)
            if not candidate:
                continue
            evidence_time = abnormal[0].get("timeMs", round_row.get("timeMs"))
            death_count = _death_count_before(pull, evidence_time)
            if death_count > threshold:
                continue
            barrage_rounds.append(nightly_detail(
                pull, round_row.get("time"),
                f"附身弹幕 #{round_row.get('index')} 被提前拦截；{candidate.get('player')} 位于 Boss 与坦克目标之间，距弹道 {candidate.get('distanceToLaneYards')} 码",
                player=candidate.get("player"),
                classColor=candidate.get("classColor"),
                raidDeathCountBefore=death_count,
            ))
        for placement in (mechanics.get("essenceRend") or {}).get("placements") or []:
            if placement.get("placementEstimate") != "太靠近中场":
                continue
            death_count = _death_count_before(pull, placement.get("timeMs"))
            if death_count > threshold:
                continue
            close_essence.append(nightly_detail(
                pull, placement.get("time"),
                f"{placement.get('player') or '未知玩家'} 的精华撕裂距中场 {placement.get('distanceFromCenterYards')} 码（要求至少 20 码）",
                player=placement.get("player"), classColor=placement.get("classColor"), raidDeathCountBefore=death_count,
            ))
        for round_row in (mechanics.get("innerRealm") or {}).get("rounds") or []:
            if not round_row.get("assignmentConfigured") or round_row.get("assignmentStatus") == "正常":
                continue
            death_count = _death_count_before(pull, round_row.get("timeMs"))
            if death_count > threshold:
                continue
            missing_names = "、".join(ref.get("player") for ref in round_row.get("missingRefs") or []) or "无"
            unexpected_names = "、".join(ref.get("player") for ref in round_row.get("unexpectedRefs") or []) or "无"
            fatigued_names = "、".join(ref.get("player") for ref in round_row.get("fatiguedRefs") or []) or "无"
            inner_failures.append(nightly_detail(
                pull,
                round_row.get("time"),
                f"内场 #{round_row.get('index')}（预期 {round_row.get('expectedTeam')} 队）异常：缺席 {missing_names}；替入 {unexpected_names}；带灵魂疲惫进入 {fatigued_names}",
                raidDeathCountBefore=death_count,
            ))
        for death in pull.get("deathTimeline") or []:
            if death.get("kind") != "death" or int(death.get("abilityID") or 0) not in {1288554, 1295085, 1300239}:
                continue
            death_count = _death_count_before(pull, death.get("timeMs"))
            if death_count > threshold:
                continue
            avoidable_deaths.append(nightly_detail(
                pull,
                death.get("time"),
                f"{death.get('player')} 死于 {death.get('ability')}",
                player=death.get("player"),
                classColor=death.get("classColor"),
                spellID=death.get("abilityID"),
                raidDeathCountBefore=death_count,
            ))
    return {
        "title": "整夜机制统计",
        "subtitle": f"所有项目只统计机制发生时累计减员不超过 {threshold} 人的记录；超过阈值后的崩盘阶段不继续归责。",
        "metrics": [
            {
                "key": "awakenedHostNoAttempt", "label": "觉醒宿主时未尝试焚尸", "value": len(corpse_failures), "unit": "人次",
                "tone": "danger", "description": "仅在该轮确实触发觉醒宿主时，蛇形烈焰全程未进入任意可用尸体 10 码范围的玩家才计数。",
                "players": nightly_player_totals(corpse_failures), "events": corpse_failures,
            },
            {
                "key": "closeEssenceRends", "label": "精华撕裂未远离中场", "value": len(close_essence), "unit": "次",
                "tone": "warning", "description": "可靠解除位置距估算场地中心小于 20 码时计数。",
                "players": nightly_player_totals(close_essence), "events": close_essence,
            },
            {
                "key": "barrageIntercepts", "label": "错误挡住附身弹幕", "value": len(barrage_rounds), "unit": "次",
                "tone": "danger", "description": "同一轮最多计一次；必须同时存在异常团伤与可靠坐标，证明该玩家位于 Boss 和坦克目标之间。",
                "players": nightly_player_totals(barrage_rounds), "events": barrage_rounds,
            },
            {
                "key": "incorrectInnerRealm", "label": "未按分组进入内场", "value": len(inner_failures), "unit": "轮",
                "tone": "danger", "description": "WCL 不记录小队编号；只有配置 3/4 队名单后才比较实际不朽盘卷进入记录，未配置时不计数。",
                "players": nightly_player_totals(inner_failures), "events": inner_failures,
            },
            {
                "key": "avoidableDeaths", "label": "死于可躲避技能", "value": len(avoidable_deaths), "unit": "次",
                "tone": "danger", "description": "仅统计灵魂转移、潜藏的教徒与盘旋精魂的直接致死记录。",
                "players": nightly_player_totals(avoidable_deaths), "events": avoidable_deaths,
            },
        ],
    }


def analyze_report_fight(report_id, report_start, actor_map, actor_type, actor_rows, fight, payload, options):
    payload["deaths"] = [
        event for event in payload["deaths"]
        if actor_type.get(event.get("targetID")) == "Player"
    ]
    markers = phase_markers(fight, payload["casts"], payload["buffs"])
    player_catalog = build_player_catalog(actor_map, actor_type, payload["combatants"])
    actor_game_id = {row["id"]: row.get("gameID") for row in actor_rows}
    payload["actorOwnerMap"] = {row["id"]: row.get("petOwner") for row in actor_rows if row.get("petOwner")}
    boss_ids = [actor_id for actor_id, game_id in actor_game_id.items() if game_id == 259927]
    position_events = payload.get("positionEvents") or []
    boss_position_events = payload.get("bossPositionEvents") or []
    position_index = build_position_index(position_events + boss_position_events + payload["damage"])
    arena = arena_estimate(position_events, actor_type) or arena_estimate(payload["damage"], actor_type)
    essence_rend = analyze_essence_rend(
        fight,
        actor_map,
        payload["debuffs"],
        payload["damage"] + position_events,
        arena,
        options,
        player_catalog,
    )
    barrage = analyze_barrage(
        fight, actor_map, payload["casts"], payload["damage"], payload["deaths"],
        player_catalog, position_index, boss_ids,
    )
    hungering_pyre = analyze_hungering_pyre(fight, actor_map, payload["debuffs"], payload["damage"], options, payload["casts"])
    analyze_transition_assignments(fight, actor_map, player_catalog, hungering_pyre["rounds"], payload["debuffs"], payload["damage"])
    corpse_lifecycle = analyze_corpse_cremation(
        fight,
        actor_map,
        player_catalog,
        hungering_pyre["rounds"],
        payload["debuffs"],
        position_index,
        payload.get("amaniDamage") or [],
        payload.get("amaniBuffs") or [],
        options,
    )
    inner_realm = analyze_inner_realm(fight, actor_map, player_catalog, payload, options)
    raw = {
        "reportID": report_id,
        "reportStart": report_start,
        "fight": fight,
        "payload": payload,
        "markers": markers,
        "players": player_catalog,
        "actorMap": actor_map,
        "essenceRend": essence_rend,
        "leaks": analyze_leaks(fight, payload["casts"], markers, options),
        "barrage": barrage,
        "hungeringPyre": hungering_pyre,
        "corpseLifecycle": corpse_lifecycle,
        "innerRealm": inner_realm,
        "invoke": analyze_invoke(fight, actor_map, payload["debuffs"], markers),
        "avoidable": analyze_avoidable(fight, actor_map, actor_type, payload["damage"], payload["deaths"], player_catalog),
    }
    return raw


def render_fight(raw, baseline, options):
    fight = raw["fight"]
    enrage = next((row for row in raw["markers"] if row["key"] == "enrage"), None)
    apply_barrage_verdicts(raw["barrage"], baseline, enrage["timeMs"] if enrage else None, options)
    classification = classify_fight(raw)
    duration_ms = int(fight["endTime"] - fight["startTime"])
    started_at = datetime.fromtimestamp((raw["reportStart"] + fight["startTime"]) / 1000, tz=CN_TZ)
    ended_at = datetime.fromtimestamp((raw["reportStart"] + fight["endTime"]) / 1000, tz=CN_TZ)
    report_date = started_at.strftime("%Y-%m-%d")
    summary = (
        f"本场{'击杀' if fight.get('kill') else '灭团'}于{classification['endPhaseLabel']}，"
        f"Boss 剩余 {float(fight.get('bossPercentage') or 0):.2f}%；"
        f"确认/疑似漏怪 {raw['leaks']['confirmedCount']}/{raw['leaks']['suspectedCount']} 次。"
        f"初判：{classification['label']}。"
    )
    survival = build_survival_timeline(
        fight,
        {player_id: player["name"] for player_id, player in raw["players"].items()},
        raw["players"],
        raw["payload"]["deaths"],
        raw["payload"].get("friendlyCasts") or [],
        SPELLS,
    )
    tank_swap = analyze_tank_swap(
        fight,
        raw.get("actorMap") or {player_id: player["name"] for player_id, player in raw["players"].items()},
        raw["players"],
        raw["payload"]["debuffs"],
        raw["payload"].get("friendlyCasts") or [],
        raw["barrage"],
        survival,
    )
    interrupted_counts = defaultdict(int)
    for event in raw["invoke"]:
        interrupted_counts[event.get("interruptedAbility") or "未记录施法技能"] += 1
    most_interrupted = max(interrupted_counts, key=interrupted_counts.get) if interrupted_counts else None
    return {
        "reportID": raw["reportID"],
        "fightID": fight["id"],
        "date": report_date,
        "startClock": started_at.strftime("%H:%M:%S"),
        "startTimeIso": started_at.isoformat(),
        "endTimeIso": ended_at.isoformat(),
        "isKill": bool(fight.get("kill")),
        "kill": bool(fight.get("kill")),
        "bossPercentage": float(fight.get("bossPercentage") or 0),
        "durationMs": duration_ms,
        "duration": fmt_ms(duration_ms),
        "wipePhase": classification["endPhaseLabel"],
        "wipeReason": classification["label"],
        "classification": classification,
        "summary": summary,
        "investigation": classification["reason"],
        "phaseTimeline": raw["markers"],
        "wclDeepLink": f"https://www.warcraftlogs.com/reports/{raw['reportID']}#fight={fight['id']}&type=summary",
        "players": list(raw["players"].values()),
        "survival": survival,
        "deathTimeline": survival["timeline"],
        **difficulty_fields(fight),
        "nakzali": {
            "amaniLeaks": raw["leaks"],
            "essenceRend": raw["essenceRend"],
            "possessionBarrage": {"baseline": baseline, "rounds": raw["barrage"]},
            "hungeringPyre": raw["hungeringPyre"],
            "innerRealm": raw["innerRealm"],
            "invokeInterrupts": {"count": len(raw["invoke"]), "events": raw["invoke"],
                                 "mostInterruptedAbility": most_interrupted,
                                 "abilityCounts": [{"ability": name, "count": count} for name, count in sorted(interrupted_counts.items(), key=lambda item: item[1], reverse=True)]},
            "tankSwap": tank_swap,
            "avoidableBoard": raw["avoidable"],
        },
        "avoidableSummary": raw["avoidable"],
    }


def build_aggregated_json(report_ids, options=None):
    from analyzer_core.analysis_scope import filter_fights
    options = {**DEFAULT_OPTIONS, **(options or {})}
    report_id_list = [value for value in (item.strip() for item in report_ids.replace(" ", "").split(",")) if value]
    if not report_id_list:
        raise RuntimeError("请传入至少一个 WCL report ID。")
    client = WclClient()
    raw_fights = []
    progress("读取 1 号 Boss Pull 列表", 8)
    for report_id in report_id_list:
        report = client.report_fights(report_id)
        fights = filter_fights(report_id, [
            row for row in report["fights"]
            if int(row.get("encounterID") or 0) in ENCOUNTER_IDS
            and row["endTime"] - row["startTime"] >= 20_000
        ])
        actor_rows = client.actors(report_id)
        actor_map = {row["id"]: row["name"] for row in actor_rows}
        actor_type = {row["id"]: row.get("type") for row in actor_rows}
        primary_boss_id = next((row["id"] for row in actor_rows if row.get("gameID") == 259927), None)
        amani_ids = [row["id"] for row in actor_rows if row.get("gameID") == 261509]
        progress(f"{report_id}：匹配 {len(fights)} 场", 12)

        def fetch_one(index_and_fight):
            index, fight = index_and_fight
            progress(f"读取 Fight {fight['id']}（{index}/{len(fights)}）")
            payload = fetch_payload(
                client,
                report_id,
                fight,
                options,
                boss_id=primary_boss_id,
                amani_ids=amani_ids,
            )
            raw = analyze_report_fight(report_id, report["startTime"], actor_map, actor_type, actor_rows, fight, payload, options)
            return index, raw

        for _, raw in run_parallel_indexed(list(enumerate(fights, start=1)), fetch_one):
            raw_fights.append(raw)
    baseline = barrage_baseline(raw_fights)
    rendered = [render_fight(raw, baseline, options) for raw in raw_fights]
    rendered.sort(key=lambda row: (row["date"], row["reportID"], row["fightID"]))
    global_board = defaultdict(dict)
    for row in rendered:
        merge_avoidable(global_board, row["nakzali"]["avoidableBoard"])
    global_rows = {
        spell_id: sorted(players.values(), key=lambda row: (row["deathCount"], row["totalDamage"], row["hitCount"]), reverse=True)
        for spell_id, players in global_board.items()
    }
    progress("生成按阶段 Pull 与单场断案数据", 96)
    return {
        "code": 200,
        "meta": {
            "version": "12.1",
            "raidKey": "venomous_abyss",
            "raidName": "烈毒之渊",
            "bossKey": "nakzali",
            "bossName": "盘魂者内克扎利",
            "analyzedReports": report_id_list,
            "mechanicVersion": "nakzali-initial-court-2026-08-03",
            "features": {"interrupts": False, "dispels": False, "fieldReplay": False, "mistakes": False},
            "capabilities": {
                "wipe": {"enabled": True, "renderer": "nakzali-pulls"},
                "avoidable": {"enabled": True, "renderer": "nakzali-avoidable"},
                "replay": {"enabled": True, "renderer": "nakzali-field"},
                "mistakes": {"enabled": False, "renderer": "mistake-tracker"},
                "verdict": {"enabled": False, "renderer": "mistake-verdict"},
            },
            "analysisConfig": options,
            "evidenceLimits": {
                "essenceRend": "移除事件没有坐标；只取附近伤害/资源采样，不使用死亡位置回填。",
                "blackCircle": "回放精华撕裂移除时玩家的附近坐标；1288554 的伤害来源是 Boss，没有黑圈 actor 坐标，因此不伪造连续移动轨迹。",
                "amaniLeak": "仅在额外仪式灼烧与独立小怪实例相邻时记为确认；其余为疑似。",
            },
        },
        "data": {
            "page1_wipeAnalysis": rendered,
            "page2_avoidableBoard": global_rows,
            "barrageBaseline": baseline,
            "mechanicOverview": _mechanic_overview(rendered, options),
        },
    }


def analyze(report_ids: str, output_path=None, catalog_entry=None, options=None, progress_callback=None):
    result = build_aggregated_json(report_ids, options=options)
    return write_json_result(result, output_path, catalog_entry=catalog_entry)
