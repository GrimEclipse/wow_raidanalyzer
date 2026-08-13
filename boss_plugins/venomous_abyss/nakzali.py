"""Initial evidence-first analyzer for Nek'zali the Soulcoiler (12.1)."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from analyzer_core.concurrency import run_parallel_indexed
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


ENCOUNTER_ID = 53470
CN_TZ = timezone(timedelta(hours=8))

SPELLS = {
    1284034: "解缚之怒",
    1284103: "附身弹幕",
    1292034: "附身弹幕",
    1285681: "缠魂点燃",
    1293664: "缠魂点燃",
    1287426: "精华撕裂",
    1287434: "精华撕裂",
    1287533: "墓缚推进",
    1288554: "潜伏教徒",
    1289683: "苏醒仪式",
    1290003: "解缚",
    1289855: "葬火",
    1292034: "附身弹幕",
    1292248: "灵魂转移",
    1293214: "攫取深渊",
    1294729: "尸体枯萎",
    1294933: "追踪火焰",
    1295124: "苏醒仪式",
    1297624: "仪式灼烧",
    1299673: "祈求",
    1299722: "祈求打断",
    1300239: "盘旋灵魂",
    1306666: "葬火点名",
    1307939: "尸体枯萎",
    1308227: "不朽盘卷",
}

PHASE_CASTS = {1293664, 1295124, 1292248, 1289855, 1299673, 1284034}
MECHANIC_CASTS = PHASE_CASTS | {1284103, 1287533, 1297624}
AVOIDABLE_DAMAGE = {
    1288554: "移动黑圈",
    1300239: "盘旋灵魂",
    1308227: "不朽盘卷",
}
POSITION_DAMAGE_IDS = set(AVOIDABLE_DAMAGE) | {1287434, 1292034, 1293214}

DEFAULT_OPTIONS = {
    "essenceRendReviewEnabled": True,
    "essenceRendPlacementCountEnabled": False,
    "essenceRendMaxSampleOffsetMs": 1250,
    "essenceRendEdgeRatio": 0.72,
    "amaniLeakReviewEnabled": True,
    "amaniLeakCountEnabled": False,
    "possessionBarrageReviewEnabled": True,
    "possessionBarrageCountEnabled": False,
    "hungeringPyreReviewEnabled": True,
    "hungeringPyreSoakRadiusYards": 10,
    "invokeInterruptReviewEnabled": True,
    "avoidableDamageReviewEnabled": True,
}


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


def fetch_payload(client, report_id, fight, options, boss_id=None):
    casts = [
        event for event in client.events(report_id, "Casts", fight, hostility_type="Enemies")
        if ability_id(event) in MECHANIC_CASTS
    ]
    buffs = client.events(report_id, "Buffs", fight, ability_id=1290003, hostility_type="Enemies")
    deaths = client.events(report_id, "Deaths", fight)
    combatants = client.events(report_id, "CombatantInfo", fight)
    debuffs = []
    if options["essenceRendReviewEnabled"]:
        debuffs.extend(client.events(report_id, "Debuffs", fight, ability_id=1287434))
    if options["invokeInterruptReviewEnabled"]:
        debuffs.extend(client.events(report_id, "Debuffs", fight, ability_id=1299722))
    if options["hungeringPyreReviewEnabled"]:
        debuffs.extend(client.events(report_id, "Debuffs", fight, ability_id=1306666))
    damage = []
    wanted_damage = set()
    if options["essenceRendReviewEnabled"]:
        wanted_damage.add(1287434)
    if options["possessionBarrageReviewEnabled"]:
        wanted_damage.add(1292034)
    if options["hungeringPyreReviewEnabled"]:
        wanted_damage.add(1289855)
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
    return {
        "casts": casts,
        "buffs": buffs,
        "deaths": deaths,
        "combatants": combatants,
        "debuffs": debuffs,
        "damage": damage,
        "positionEvents": position_events,
        "bossPositionEvents": boss_position_events,
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


def analyze_essence_rend(fight, actor_map, debuffs, damage, arena, options):
    if not options["essenceRendReviewEnabled"]:
        return {"enabled": False, "placements": []}
    placements = []
    edge_ratio = float(options["essenceRendEdgeRatio"])
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
            "targetID": target_id,
            "player": actor_name(actor_map, target_id).split("-", 1)[0],
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
                row["placementEstimate"] = "贴边" if relative_radius >= edge_ratio else "未贴边"
                if options["essenceRendPlacementCountEnabled"] and relative_radius < edge_ratio:
                    row["counted"] = True
                    row["countReason"] = f"估算半径 {relative_radius:.2f} 低于配置阈值 {edge_ratio:.2f}"
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
        "placementRule": "窗口内坐标用于落点；窗口外仍返回最近样本时间但不参与判责；不使用死亡事件代替落点",
        "arenaEstimate": arena,
        "placements": placements,
    }


def analyze_hungering_pyre(fight, actor_map, debuffs, damage, options):
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


def analyze_barrage(fight, actor_map, casts, damage, deaths):
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
                "timeMs": wave_ts - fight["startTime"],
                "delayFromCastMs": wave_ts - start,
                "hitCount": len({event.get("targetID") for event in wave_hits}),
                "totalDamage": total,
                "lowHealthPlayers": sorted(set(low_health)),
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
        })
    return rows


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
            "title": f"葬火分散 #{pyre['index']} · {pyre['target']}",
            "targetID": pyre.get("targetID"),
            "target": pyre.get("target"),
            "pyre": pyre,
            "snapshot": snapshot,
        })
    return sorted(rows, key=lambda row: (row["timeMs"], row["eventType"], row["index"]))


def analyze_avoidable(fight, actor_map, actor_type, damage, deaths):
    death_keys = {(event.get("targetID"), event.get("killingAbilityGameID") or ability_id(event)) for event in deaths}
    board = defaultdict(lambda: defaultdict(lambda: {"hitCount": 0, "totalDamage": 0, "deathCount": 0, "events": []}))
    for event in damage:
        spell_id = ability_id(event)
        if spell_id not in AVOIDABLE_DAMAGE:
            continue
        target_id = event.get("targetID")
        if actor_type.get(target_id) != "Player":
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
            row.update({
                "name": actor_name(actor_map, target_id).split("-", 1)[0],
                "playerID": target_id,
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


def analyze_report_fight(report_id, report_start, actor_map, actor_type, actor_rows, fight, payload, options):
    payload["deaths"] = [
        event for event in payload["deaths"]
        if actor_type.get(event.get("targetID")) == "Player"
    ]
    markers = phase_markers(fight, payload["casts"], payload["buffs"])
    player_catalog = build_player_catalog(actor_map, actor_type, payload["combatants"])
    actor_game_id = {row["id"]: row.get("gameID") for row in actor_rows}
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
    )
    barrage = analyze_barrage(fight, actor_map, payload["casts"], payload["damage"], payload["deaths"])
    hungering_pyre = analyze_hungering_pyre(fight, actor_map, payload["debuffs"], payload["damage"], options)
    field_events = build_field_replay_events(
        fight,
        markers,
        player_catalog,
        boss_ids,
        actor_map,
        position_index,
        payload["deaths"],
        essence_rend["placements"],
        barrage,
        hungering_pyre["rounds"],
        arena,
    )
    raw = {
        "reportID": report_id,
        "reportStart": report_start,
        "fight": fight,
        "payload": payload,
        "markers": markers,
        "players": player_catalog,
        "essenceRend": essence_rend,
        "leaks": analyze_leaks(fight, payload["casts"], markers, options),
        "barrage": barrage,
        "hungeringPyre": hungering_pyre,
        "invoke": analyze_invoke(fight, actor_map, payload["debuffs"], markers),
        "avoidable": analyze_avoidable(fight, actor_map, actor_type, payload["damage"], payload["deaths"]),
        "fieldEvents": field_events,
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
        "nakzali": {
            "amaniLeaks": raw["leaks"],
            "essenceRend": raw["essenceRend"],
            "possessionBarrage": {"baseline": baseline, "rounds": raw["barrage"]},
            "hungeringPyre": raw["hungeringPyre"],
            "invokeInterrupts": {"count": len(raw["invoke"]), "events": raw["invoke"]},
            "avoidableBoard": raw["avoidable"],
            "fieldReplay": {
                "arenaImage": "assets/raids/venomous_abyss/01-nakzali.png",
                "placements": raw["essenceRend"]["placements"],
                "movingBlackCircleRemovals": raw["essenceRend"]["placements"],
                "events": raw["fieldEvents"],
                "blackCircleTracking": "remove-player-position-only",
                "trackingMode": "essence-rend-remove-nearby-player-position",
                "limitation": "1287434 的移除事件没有坐标；使用移除时间附近的玩家坐标。1288554 由 Boss 作为伤害来源，没有可追踪的黑圈 actor 坐标。",
            },
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
            if row.get("encounterID") == ENCOUNTER_ID and row["endTime"] - row["startTime"] >= 20_000
        ])
        actor_rows = client.actors(report_id)
        actor_map = {row["id"]: row["name"] for row in actor_rows}
        actor_type = {row["id"]: row.get("type") for row in actor_rows}
        primary_boss_id = next((row["id"] for row in actor_rows if row.get("gameID") == 259927), None)
        progress(f"{report_id}：匹配 {len(fights)} 场", 12)

        def fetch_one(index_and_fight):
            index, fight = index_and_fight
            progress(f"读取 Fight {fight['id']}（{index}/{len(fights)}）")
            payload = fetch_payload(client, report_id, fight, options, boss_id=primary_boss_id)
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
            "features": {"interrupts": False, "dispels": False, "fieldReplay": True, "mistakes": False},
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
        },
    }


def analyze(report_ids: str, output_path=None, catalog_entry=None, options=None, progress_callback=None):
    result = build_aggregated_json(report_ids, options=options)
    return write_json_result(result, output_path, catalog_entry=catalog_entry)
