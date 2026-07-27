import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    from tools.crown_pam_probe import (
        PHANTOM_GAME_ID,
        REPORT_ID,
        SPELL,
        actor_name,
        ability_id,
        event_point,
        event_type,
        fetch_actor_maps,
        fetch_events_all,
        fetch_events_all_ext,
        fetch_report_fights,
        fmt,
        get_token,
        group_by_window,
    )
except ModuleNotFoundError:
    from crown_pam_probe import (
    PHANTOM_GAME_ID,
    REPORT_ID,
    SPELL,
    actor_name,
    ability_id,
    event_point,
    event_type,
    fetch_actor_maps,
    fetch_events_all,
    fetch_events_all_ext,
    fetch_report_fights,
    fmt,
    get_token,
    group_by_window,
    )
from boss_plugins.common import build_player_mechanic_roles


FIGHT_ID = 30
OUT_PATH = Path("tmp") / "crown_fight30_audit.json"

ALLERIA_GAME_ID = 240430
ADD_GAME_IDS = {
    243805: "殁里乌姆",
    243810: "殆米阿尔",
    243811: "龌勒卢斯",
    254172: "龌勒卢斯",
    254173: "殆米阿尔",
    254174: "殁里乌姆",
}
P1_ADD_GAME_IDS = {243805, 243810, 243811}
P3_ADD_GAME_IDS = {254172, 254173, 254174}
RIFT_SIMULACRUM_GAME_ID = 254098

HEALER_SPEC_IDS = {65, 105, 256, 257, 264, 270, 1468}
WATER_OUTLIER_YARDS = 15.0
SNAP_MOVEMENT_YARDS = 5.0
FIELD_AUDIT_VERSION = "2026-07-24-compensation-gravity-v7"
COMBAT_RESURRECTION_IDS = {20484, 20608, 20707, 61999, 391054}
RAY_LENGTH_RAW = 10_000.0
RAY_WIDTH_RAW = 300.0
OBELISK_DISTANCE_RAW = 500.0
# Current log build uses 1238843 for the completed 噬灭宇宙 cast.
COSMIC_DEVOUR_ID = 1238843
TERMINAL_GUARD_ID = 1239111
GRAVITY_COLLAPSE_ID = 1255453
GRAVITY_COLLAPSE_DAMAGE_ID = 1239095
DEATH_COMPENSATION_ID = 211319
P1_BINDING_IDS = {1233470, 1237844, SPELL["corruption"]}


def rel(fight, timestamp):
    if timestamp is None:
        return None
    return int(timestamp - fight["startTime"])


def seconds(ms):
    return round((ms or 0) / 1000, 1)


def to_yards(value):
    return None if value is None else round(value / 100.0, 2)


def point_payload(point):
    if not point:
        return None
    return {
        "x": round(point[0], 2),
        "y": round(point[1], 2),
        "yardX": to_yards(point[0]),
        "yardY": to_yards(point[1]),
    }


def event_facing(event):
    value = event.get("facing") if event else None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_facing(raw):
    if raw is None:
        return None
    radians = float(raw) / 100.0
    while radians <= -math.pi:
        radians += math.tau
    while radians > math.pi:
        radians -= math.tau
    return radians


def actor_event_id(event):
    kind = event_type(event)
    if "buff" in kind or "debuff" in kind or kind == "death":
        return event.get("targetID")
    if event.get("sourceID") is not None:
        return event.get("sourceID")
    return event.get("targetID")


def build_position_index(events):
    rows = defaultdict(list)

    def add_row(event, actor_id, point, facing_raw):
        if actor_id is None or not point:
            return
        rows[actor_id].append({
            "timestamp": event.get("timestamp", 0),
            "x": point[0],
            "y": point[1],
            "facingRaw": facing_raw,
            "sourceType": event.get("type"),
            "abilityID": ability_id(event),
            "sourceInstance": event.get("sourceInstance"),
            "targetInstance": event.get("targetInstance"),
        })

    for event in events:
        add_row(event, actor_event_id(event), event_point(event), event_facing(event))
        add_row(event, event.get("sourceID"), event_point(event, "source"), event_facing(event))
        add_row(event, event.get("targetID"), event_point(event, "target"), event_facing(event))
    for actor_rows in rows.values():
        actor_rows.sort(key=lambda item: item["timestamp"])
    return rows


def state_at(index, actor_id, timestamp, max_gap_ms=3_000, allow_loose_position=False):
    rows = index.get(actor_id) or []
    if not rows:
        return None
    before = None
    after = None
    nearest_facing = None
    for row in rows:
        if row["timestamp"] <= timestamp:
            before = row
        elif row["timestamp"] > timestamp:
            after = row
            break
    candidates = [row for row in (before, after) if row]
    for row in sorted(rows, key=lambda item: abs(item["timestamp"] - timestamp)):
        if abs(row["timestamp"] - timestamp) <= max_gap_ms and row.get("facingRaw") is not None:
            nearest_facing = row
            break
    if before and after and after["timestamp"] - before["timestamp"] <= max_gap_ms:
        span = after["timestamp"] - before["timestamp"]
        ratio = 0.0 if span <= 0 else (timestamp - before["timestamp"]) / span
        x = before["x"] + (after["x"] - before["x"]) * ratio
        y = before["y"] + (after["y"] - before["y"]) * ratio
        source = "interpolated"
        delta = int(min(timestamp - before["timestamp"], after["timestamp"] - timestamp))
    else:
        close = sorted(candidates, key=lambda item: abs(item["timestamp"] - timestamp))
        if not close:
            return None
        best = close[0]
        if abs(best["timestamp"] - timestamp) > max_gap_ms and not allow_loose_position:
            return None
        x, y = best["x"], best["y"]
        source = "nearest"
        delta = int(best["timestamp"] - timestamp)
    facing_row = nearest_facing or before or after
    raw_facing = facing_row.get("facingRaw") if facing_row else None
    return {
        "x": x,
        "y": y,
        "point": point_payload((x, y)),
        "source": source,
        "deltaMs": delta,
        "facingRaw": raw_facing,
        "facingRadians": normalize_facing(raw_facing),
        "confidence": "high" if abs(delta) <= 500 else ("medium" if abs(delta) <= 1500 else "low"),
    }


def line_end_from_points(start, through, length=RAY_LENGTH_RAW):
    dx = through[0] - start[0]
    dy = through[1] - start[1]
    dist = math.hypot(dx, dy)
    if dist <= 0:
        return start
    scale = length / dist
    return (start[0] + dx * scale, start[1] + dy * scale)


def distance_point_to_segment(point, start, end):
    sx, sy = start
    ex, ey = end
    px, py = point
    dx = ex - sx
    dy = end[1] - start[1]
    span = dx * dx + dy * dy
    if span <= 0:
        return math.dist(point, start)
    t = max(0.0, min(1.0, ((px - sx) * dx + (py - sy) * dy) / span))
    closest = (sx + t * dx, sy + t * dy)
    return math.dist(point, closest)


def make_obelisks(apply_state):
    point = apply_state["point"]
    facing = apply_state.get("facingRadians")
    if not point or facing is None:
        return []
    origin = (point["x"], point["y"])
    directions = [
        ("behind", facing + math.pi),
        ("leftFront", facing + math.pi / 3),
        ("rightFront", facing - math.pi / 3),
    ]
    rows = []
    for label, angle in directions:
        rows.append({
            "label": label,
            "point": point_payload((
                origin[0] + math.cos(angle) * OBELISK_DISTANCE_RAW,
                origin[1] + math.sin(angle) * OBELISK_DISTANCE_RAW,
            )),
            "angleRadians": round(angle, 4),
        })
    return rows


def make_rays(fade_state, obelisks):
    if not fade_state or not fade_state.get("point"):
        return []
    start = (fade_state["point"]["x"], fade_state["point"]["y"])
    rows = []
    for obelisk in obelisks:
        target = obelisk.get("point")
        if not target:
            continue
        through = (target["x"], target["y"])
        end = line_end_from_points(start, through)
        rows.append({
            "label": obelisk["label"],
            "start": point_payload(start),
            "through": target,
            "end": point_payload(end),
            "widthYards": 3,
        })
    return rows


def event_actor_name(actor_map, actor_game_id, actor_id):
    if actor_game_id.get(actor_id) == ALLERIA_GAME_ID:
        return "奥蕾莉亚"
    if actor_game_id.get(actor_id) in ADD_GAME_IDS:
        return ADD_GAME_IDS[actor_game_id.get(actor_id)]
    if actor_game_id.get(actor_id) == PHANTOM_GAME_ID:
        return "银色幻影"
    return actor_name(actor_map, actor_game_id, actor_id)


def phase_window(fight, phase, phase_name):
    labels = phase.get("labels") or {}
    start, end = labels.get(phase_name, [fight["startTime"], fight["endTime"]])
    return start or fight["startTime"], end or fight["endTime"]


def phase_at(timestamp, phase):
    if phase.get("p3Start") and timestamp >= phase["p3Start"]:
        return "P3"
    if phase.get("p25Start") and timestamp >= phase["p25Start"]:
        return "P2.5"
    if phase.get("p2Start") and timestamp >= phase["p2Start"]:
        return "P2"
    if phase.get("p15Start") and timestamp >= phase["p15Start"]:
        return "P1.5"
    return "P1"


def dedupe(events):
    seen = set()
    rows = []
    for event in events:
        key = (
            event.get("timestamp"),
            event.get("type"),
            ability_id(event),
            event.get("sourceID"),
            event.get("targetID"),
            event.get("sourceInstance"),
            event.get("targetInstance"),
        )
        if key in seen:
            continue
        seen.add(key)
        rows.append(event)
    return rows


def first_event(events, spell_id, kind=None, start=None, end=None):
    rows = []
    for event in events:
        if ability_id(event) != spell_id:
            continue
        if kind and kind not in event_type(event):
            continue
        ts = event.get("timestamp", 0)
        if start is not None and ts < start:
            continue
        if end is not None and ts > end:
            continue
        rows.append(event)
    return min(rows, key=lambda item: item.get("timestamp", 0), default=None)


def fetch_spell_bundle(token, report_id, fight):
    print("fetching events for single-fight audit...")
    casts = fetch_events_all(token, report_id, "Casts", fight, include_resources=True)
    debuffs = []
    buffs = []
    damage = []
    for spell_id in [
        SPELL["void_grasp"],
        SPELL["void_repulsion_mark"],
        SPELL["silver_arrow_mark"],
        SPELL["ranger_mark"],
        SPELL["star_scatter"],
        SPELL["silver_havoc"],
        SPELL["cosmic_barrier"],
        SPELL["cosmic_radiation"],
        TERMINAL_GUARD_ID,
        GRAVITY_COLLAPSE_ID,
        DEATH_COMPENSATION_ID,
    ]:
        debuffs.extend(fetch_events_all(token, report_id, "Debuffs", fight, ability_id=spell_id, include_resources=True))
    for spell_id in [SPELL["cosmic_barrier"], SPELL["cosmic_radiation"], SPELL["silver_havoc"], 26662, 27680, 1239672]:
        buffs.extend(fetch_events_all(token, report_id, "Buffs", fight, ability_id=spell_id, include_resources=True))
        buffs.extend(fetch_events_all(token, report_id, "Buffs", fight, ability_id=spell_id, hostility_type="Enemies", include_resources=True))
    for spell_id in [
        SPELL["silver_arrow_damage"],
        SPELL["collapsing_void"],
        SPELL["void_repulsion_damage"],
        SPELL["silver_ricochet"],
        SPELL["silver_ricochet_energy_drain"],
        GRAVITY_COLLAPSE_DAMAGE_ID,
    ]:
        damage.extend(fetch_events_all(token, report_id, "DamageTaken", fight, ability_id=spell_id, include_resources=True))
        damage.extend(fetch_events_all(token, report_id, "DamageDone", fight, ability_id=spell_id, hostility_type="Enemies", include_resources=True))
    deaths = fetch_events_all(token, report_id, "Deaths", fight)
    # includeResources 会在部分治疗事件上返回目标当前/最大生命值，供空虚之握
    # “点名时血量 > 50%”判定使用。没有可靠采样时必须明确豁免。
    healing = fetch_events_all(token, report_id, "Healing", fight, include_resources=True)
    combatants = fetch_events_all(token, report_id, "CombatantInfo", fight)
    resources = fetch_events_all(token, report_id, "Resources", fight, include_resources=True)
    enemy_resources = fetch_events_all(token, report_id, "Resources", fight, hostility_type="Enemies", include_resources=True)
    enemy_debuffs = []
    for spell_id in P1_BINDING_IDS:
        enemy_debuffs.extend(fetch_events_all(token, report_id, "Debuffs", fight, ability_id=spell_id, hostility_type="Enemies", include_resources=True))
    return {
        "casts": dedupe(casts),
        "debuffs": dedupe(debuffs),
        "buffs": dedupe(buffs),
        "damage": dedupe(damage),
        "deaths": dedupe(deaths),
        "healing": dedupe(healing),
        "combatants": dedupe(combatants),
        "resources": dedupe(resources),
        "enemyResources": dedupe(enemy_resources),
        "enemyDebuffs": dedupe(enemy_debuffs),
    }


def fetch_actor_position_events(token, report_id, fight, actor_ids):
    rows = []
    for actor_id in sorted(actor_ids):
        for data_type in ("Resources", "Casts", "DamageDone"):
            rows.extend(fetch_events_all_ext(
                token,
                report_id,
                data_type,
                fight,
                source_id=actor_id,
                hostility_type="Enemies",
                include_resources=True,
            ))
        rows.extend(fetch_events_all_ext(
            token,
            report_id,
            "DamageTaken",
            fight,
            target_id=actor_id,
            hostility_type="Enemies",
            include_resources=True,
        ))
    return dedupe(rows)


def combatant_spec_id(event):
    for key in ("specID", "specId", "spec", "specializationID", "specializationId"):
        value = event.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def healer_ids(combatants):
    return {
        event.get("sourceID") or event.get("targetID")
        for event in combatants
        if combatant_spec_id(event) in HEALER_SPEC_IDS and (event.get("sourceID") or event.get("targetID"))
    }


def build_phase(fight, events):
    start = fight["startTime"]
    silver_havoc = first_event(events["casts"] + events["buffs"] + events["debuffs"], SPELL["silver_havoc"], start=start + 123_000)
    star_fades = [
        event for event in events["debuffs"]
        if ability_id(event) == SPELL["star_scatter"] and "remove" in event_type(event)
    ]
    p2_start = max((event.get("timestamp", 0) for event in star_fades), default=None)
    p15_start = silver_havoc.get("timestamp") if silver_havoc else (p2_start - 38_000 if p2_start else None)
    barrier_apply = first_event(events["buffs"], SPELL["cosmic_barrier"], "apply", p2_start, fight["endTime"])
    barrier_remove = first_event(events["buffs"], SPELL["cosmic_barrier"], "remove", barrier_apply.get("timestamp") if barrier_apply else p2_start, fight["endTime"])
    radiation_apply = first_event(events["buffs"], SPELL["cosmic_radiation"], "apply", p2_start, fight["endTime"])
    radiation_remove = first_event(events["buffs"], SPELL["cosmic_radiation"], "remove", radiation_apply.get("timestamp") if radiation_apply else p2_start, fight["endTime"])
    p25_start = (barrier_apply or radiation_apply or {}).get("timestamp")
    p3_start = (barrier_remove or radiation_remove or {}).get("timestamp")
    return {
        "p15Start": p15_start,
        "p2Start": p2_start,
        "p25Start": p25_start,
        "p3Start": p3_start,
        "labels": {
            "P1": [start, p15_start],
            "P1.5": [p15_start, p2_start],
            "P2": [p2_start, p25_start],
            "P2.5": [p25_start, p3_start],
            "P3": [p3_start, fight["endTime"]],
        },
    }


def pair_void_grasp(debuffs):
    active = {}
    rows = []
    for event in sorted(debuffs, key=lambda item: item.get("timestamp", 0)):
        if ability_id(event) != SPELL["void_grasp"]:
            continue
        target_id = event.get("targetID")
        if "apply" in event_type(event):
            active[target_id] = event
        elif "remove" in event_type(event) and target_id in active:
            rows.append({"targetID": target_id, "apply": active.pop(target_id), "remove": event})
    return rows


def group_void_grasp_pairs(pairs):
    clusters = []
    for pair in sorted(pairs, key=lambda item: item["apply"].get("timestamp", 0)):
        ts = pair["apply"].get("timestamp", 0)
        if not clusters or ts - clusters[-1]["end"] > 2_500:
            clusters.append({"start": ts, "end": ts, "pairs": [pair]})
        else:
            clusters[-1]["end"] = ts
            clusters[-1]["pairs"].append(pair)
    return clusters


def active_phantoms_at(phantom_segments, timestamp):
    return [
        segment for segment in phantom_segments
        if segment["first"] <= timestamp <= segment["last"] + 2_200
    ]


def phantom_segments_from_damage(damage_events, actor_game_id, cast_events=None):
    by_instance = defaultdict(list)
    for event in damage_events:
        if actor_game_id.get(event.get("sourceID")) != PHANTOM_GAME_ID:
            continue
        key = (event.get("sourceID"), event.get("sourceInstance"))
        by_instance[key].append(event)
    segments = []
    for (source_id, source_instance), events in by_instance.items():
        ticks = []
        for event in sorted(events, key=lambda item: item.get("timestamp", 0)):
            ts = event.get("timestamp", 0)
            if not ticks or ts - ticks[-1]["time"] > 550:
                ticks.append({"time": ts, "events": [event]})
            else:
                ticks[-1]["events"].append(event)
        for tick in ticks:
            if not segments or segments[-1].get("key") != (source_id, source_instance) or tick["time"] - segments[-1]["last"] > 3_500:
                segments.append({
                    "key": (source_id, source_instance),
                    "sourceID": source_id,
                    "sourceInstance": source_instance,
                    "first": tick["time"],
                    "last": tick["time"],
                    "events": tick["events"][:],
                })
            else:
                segments[-1]["last"] = tick["time"]
                segments[-1]["events"].extend(tick["events"])
    by_key = {(segment["sourceID"], segment["sourceInstance"]): segment for segment in segments}
    for event in cast_events or []:
        if actor_game_id.get(event.get("sourceID")) != PHANTOM_GAME_ID or event.get("sourceInstance") is None:
            continue
        point = event_point(event, "source") or (event_point(event) if event.get("resourceActor") == 1 else None)
        if not point:
            continue
        key = (event.get("sourceID"), event.get("sourceInstance"))
        segment = by_key.get(key)
        if not segment:
            segment = {"key": key, "sourceID": key[0], "sourceInstance": key[1], "first": event.get("timestamp", 0), "last": event.get("timestamp", 0), "events": []}
            segments.append(segment)
            by_key[key] = segment
        segment["first"] = min(segment["first"], event.get("timestamp", 0))
        segment["castPosition"] = point_payload(point)
        segment["castTime"] = event.get("timestamp", 0)
    return sorted(segments, key=lambda item: item["first"])


def phantom_position(segment, timestamp, position_index):
    if segment.get("castPosition"):
        return segment["castPosition"]
    nearest = min(segment["events"], key=lambda item: abs(item.get("timestamp", 0) - timestamp), default=None)
    # Multiple simultaneous phantoms may share one actor ID.  Their damage
    # events still carry distinct source positions, so never collapse them via
    # the actor-level position index when an event coordinate is available.
    point = (event_point(nearest, "source") or event_point(nearest)) if nearest else None
    if point:
        return point_payload(point)
    state = state_at(position_index, segment["sourceID"], timestamp, max_gap_ms=4_000, allow_loose_position=True)
    return state["point"] if state else None


def actors_at(timestamp, actor_ids, position_index, actor_map, actor_game_id, max_gap_ms=60_000):
    rows = []
    for actor_id in actor_ids:
        state = state_at(position_index, actor_id, timestamp, max_gap_ms=max_gap_ms, allow_loose_position=True)
        rows.append({
            "id": actor_id,
            "name": event_actor_name(actor_map, actor_game_id, actor_id),
            "gameID": actor_game_id.get(actor_id),
            "position": state["point"] if state else None,
            "confidence": state.get("confidence") if state else "unknown",
            "deltaMs": state.get("deltaMs") if state else None,
            "positionSource": state.get("source") if state else None,
        })
    return rows


def player_ids(combatants, actor_type):
    ids = {
        event.get("sourceID") or event.get("targetID")
        for event in combatants
        if event.get("sourceID") is not None or event.get("targetID") is not None
    }
    return sorted(actor_id for actor_id in ids if actor_id is not None)


def living_player_ids_at(player_actor_ids, deaths, timestamp):
    dead_ids = {
        event.get("targetID") for event in deaths or []
        if event.get("targetID") is not None and event.get("timestamp", 0) <= timestamp
    }
    return [actor_id for actor_id in player_actor_ids if actor_id not in dead_ids]


def snapshot_at(timestamp, player_actor_ids, boss_actor_ids, position_index, actor_map, actor_game_id, deaths=None):
    return {
        "timeMsAbsolute": timestamp,
        "players": actors_at(timestamp, living_player_ids_at(player_actor_ids, deaths, timestamp), position_index, actor_map, actor_game_id, max_gap_ms=6_000),
        "bosses": actors_at(timestamp, boss_actor_ids, position_index, actor_map, actor_game_id),
    }


def boss_energy_at(timestamp, boss_actor_ids, events):
    candidates = []
    for event in events["casts"] + events["enemyResources"] + events["damage"]:
        if event.get("sourceID") not in boss_actor_ids:
            continue
        for resource in event.get("classResources") or []:
            if str(resource.get("type")) == "3" and resource.get("amount") is not None:
                candidates.append((abs(event.get("timestamp", 0) - timestamp), resource.get("amount"), resource.get("max"), event.get("timestamp", 0)))
    if not candidates:
        return None
    _, amount, maximum, sample_ts = min(candidates, key=lambda item: item[0])
    return {"amount": amount, "max": maximum, "sampleDeltaMs": int(sample_ts - timestamp)}


def platform_for_point(point, center):
    if not point:
        return None
    dx = point["x"] - center["x"]
    dy = point["y"] - center["y"]
    if dy >= 0:
        return "top"
    return "lowerLeft" if dx < 0 else "lowerRight"


def build_p3_events(fight, actor_map, actor_game_id, events, phase, position_index, player_actor_ids):
    boss_ids = actor_ids_for_phase(actor_game_id, "P3")
    center = {"x": -36385, "y": 478822}
    rows = []
    contaminations = []
    relevant = [event for event in events["casts"] if ability_id(event) in {COSMIC_DEVOUR_ID, SPELL["portal"]} and event_type(event) == "cast"]
    for event in sorted(relevant, key=lambda item: item.get("timestamp", 0)):
        ts = event.get("timestamp", 0)
        if phase_at(ts, phase) != "P3":
            continue
        kind = "cosmicDevour" if ability_id(event) == COSMIC_DEVOUR_ID else "portal"
        boss_state = state_at(position_index, event.get("sourceID"), ts, max_gap_ms=15_000, allow_loose_position=True)
        row = {
            "id": f"{kind}-{len(rows) + 1}", "index": len(rows) + 1, "eventType": kind, "phase": "P3",
            "timeMs": rel(fight, ts), "time": fmt(rel(fight, ts)),
            "snapshot": snapshot_at(ts, player_actor_ids, boss_ids, position_index, actor_map, actor_game_id, events["deaths"]),
            "bossEnergy": boss_energy_at(ts, boss_ids, events),
        }
        rows.append(row)
        if kind == "cosmicDevour":
            contaminations.append({
                "castTimeMs": rel(fight, ts), "activeTimeMs": rel(fight, ts + 10_000),
                "platform": platform_for_point(boss_state.get("point") if boss_state else None, center),
                "bossPosition": boss_state.get("point") if boss_state else None,
            })
    return rows, contaminations


def phantom_spawn_time_ms(segment, bow_groups, fight):
    cast_ms = rel(fight, segment.get("castTime")) if segment.get("castTime") else None
    if cast_ms is None:
        return rel(fight, segment.get("first"))
    return cast_ms


def prune_dead_npcs(rows, absolute_ts, enemy_deaths):
    dead_ids = {
        event.get("targetID") for event in enemy_deaths
        if event.get("targetID") is not None and event.get("timestamp", 0) <= absolute_ts
    }
    return [row for row in rows if row.get("id") not in dead_ids]


def apply_npc_lifetimes(fight, enemy_deaths, event_groups):
    for row in event_groups:
        time_ms = row.get("fireTimeMs") if row.get("fireTimeMs") is not None else row.get("timeMs")
        if time_ms is None:
            continue
        absolute_ts = fight["startTime"] + time_ms
        if "actors" in row:
            row["actors"] = prune_dead_npcs(row.get("actors") or [], absolute_ts, enemy_deaths)
        if row.get("snapshot"):
            row["snapshot"]["bosses"] = prune_dead_npcs(row["snapshot"].get("bosses") or [], absolute_ts, enemy_deaths)


def refine_p2_shot_attribution(fight, bow_groups, water_events, phantom_segments, player_roles):
    for group in bow_groups:
        if group.get("phase") != "P2":
            continue
        evidence_nodes = [
            {"timeMs": row.get("timeMs"), "time": row.get("time")}
            for row in water_events
            if row.get("timeMs", 0) > group.get("fireTimeMs", 0)
        ]
        evidence_nodes.extend({
            "timeMs": row.get("applyStartMs"),
            "time": row.get("applyStart"),
        } for row in bow_groups if row is not group and row.get("applyStartMs", 0) > group.get("fireTimeMs", 0))
        next_event = min(evidence_nodes, key=lambda row: row["timeMs"], default=None)
        if not next_event:
            continue
        next_abs = fight["startTime"] + next_event["timeMs"]
        shown_instances = {row.get("sourceInstance") for row in group.get("phantoms") or [] if row.get("sourceInstance") is not None}
        group["phantomEligible"] = bool(shown_instances)
        for player in group.get("players") or []:
            if player.get("diedAtFire"):
                player["missedPhantom"] = False
                player["missedPhantomExemptReason"] = "崩裂空无结算期间死亡，暂不统计未命中幻影"
        if not shown_instances:
            for player in group.get("players") or []:
                player["missedPhantom"] = False
            continue
        surviving_instances = {
            segment.get("sourceInstance") for segment in phantom_segments
            if segment.get("sourceInstance") in shown_instances
            and segment.get("first", 0) - 5_000 <= next_abs <= segment.get("last", 0) + 2_200
        }
        removed_instances = sorted(shown_instances - surviving_instances)
        group["nextEvidenceTimeMs"] = next_event["timeMs"]
        group["nextEvidenceTime"] = next_event["time"]
        group["survivingAtNextEvent"] = sorted(surviving_instances)
        group["removedByNextEvent"] = removed_instances
        if not removed_instances:
            if shown_instances and surviving_instances == shown_instances:
                for player in group.get("players") or []:
                    if player.get("diedAtFire") or not player.get("activePhantomInstances"):
                        continue
                    player.setdefault("shotAttribution", []).append({
                        "phantom": None,
                        "verdict": "未命中",
                        "confidence": "high",
                        "basis": "下个技能节点没有任何银色幻影实例消失",
                    })
                    player["missedPhantom"] = True
                group["shotOutcome"] = "本轮没有任何银色幻影消失，两名点名玩家均确认未命中"
            continue
        player_counts = defaultdict(int)
        for row in (group.get("snapshot") or {}).get("players") or []:
            platform = platform_for_point(row.get("position"), {"x": -36385, "y": 478822})
            if platform:
                player_counts[platform] += 1
        phantom_by_instance = {row.get("sourceInstance"): row for row in group.get("phantoms") or []}
        for removed_instance in removed_instances:
            direct = [
                player for player in group.get("players") or []
                if not player.get("diedAtFire")
                and any(hit.get("phantom") == removed_instance for hit in player.get("predictedPhantomHits") or [])
            ]
            if len(direct) == 1:
                direct[0].setdefault("shotAttribution", []).append({"phantom": removed_instance, "verdict": "命中", "confidence": "high", "basis": "下个技能实例消失+射线相交"})
                continue
            phantom = phantom_by_instance.get(removed_instance) or {}
            platform = platform_for_point(phantom.get("position"), {"x": -36385, "y": 478822})
            expected = "range" if player_counts.get(platform, 0) >= 4 else "melee"
            candidates = []
            for player in group.get("players") or []:
                if player.get("diedAtFire"):
                    continue
                if removed_instance not in (player.get("activePhantomInstances") or []):
                    continue
                role = player_roles.get(player.get("targetID"), "unknown")
                role_side = "range" if role.startswith("range-") else ("melee" if role.startswith("melee-") or role == "tank" else "unknown")
                player["mechanicRole"] = role
                if role_side == expected:
                    candidates.append(player)
            if len(candidates) == 1:
                candidates[0].setdefault("shotAttribution", []).append({"phantom": removed_instance, "verdict": "大概率命中", "confidence": "medium", "basis": f"下个技能实例消失；{platform}板块职责={expected}"})
            else:
                for player in group.get("players") or []:
                    if player.get("diedAtFire"):
                        continue
                    if removed_instance not in (player.get("activePhantomInstances") or []):
                        continue
                    player.setdefault("shotAttribution", []).append({"phantom": removed_instance, "verdict": "无法唯一归因", "confidence": "low", "basis": "实例消失已确认，但射线/职责不能唯一归因"})
        hit_players = [
            player for player in group.get("players") or []
            if any(item.get("verdict") in {"命中", "大概率命中"} for item in player.get("shotAttribution") or [])
        ]
        unassigned_players = [
            player for player in group.get("players") or []
            if not player.get("diedAtFire")
            and player.get("activePhantomInstances")
            and player not in hit_players
        ]
        if surviving_instances and len(unassigned_players) == 1:
            unassigned_players[0].setdefault("shotAttribution", []).append({
                "phantom": sorted(surviving_instances)[0],
                "verdict": "未命中",
                "confidence": "high",
                "basis": "另一名点名已确认命中；该玩家对应幻影在下个技能节点仍存活",
            })
        for player in group.get("players") or []:
            if player.get("diedAtFire"):
                player["missedPhantom"] = False
                player["missedPhantomExemptReason"] = "崩裂空无结算期间死亡，暂不统计未命中幻影"
                continue
            attributions = player.get("shotAttribution") or []
            if any(item["verdict"] in {"命中", "大概率命中"} for item in attributions):
                player["missedPhantom"] = False
                player["actualPhantomHitCount"] = max(player.get("actualPhantomHitCount", 0), 1)
            elif any(
                "未命中" in str(item.get("verdict") or "")
                and item.get("confidence") in {"high", "medium"}
                for item in attributions
            ):
                player["missedPhantom"] = True


def build_rift_instances(fight, casts, enemy_deaths, actor_game_id):
    rows = []
    seen = set()
    for event in sorted(casts, key=lambda item: item.get("timestamp", 0)):
        if actor_game_id.get(event.get("sourceID")) != RIFT_SIMULACRUM_GAME_ID or event.get("resourceActor") != 1:
            continue
        instance = event.get("sourceInstance")
        key = (event.get("sourceID"), instance)
        if key in seen:
            continue
        point = event_point(event)
        if not point:
            continue
        seen.add(key)
        death = min((row for row in enemy_deaths if row.get("targetID") == key[0] and row.get("targetInstance") == instance and row.get("timestamp", 0) >= event.get("timestamp", 0)), key=lambda row: row.get("timestamp", 0), default=None)
        rows.append({
            "sourceID": key[0], "sourceInstance": instance,
            "spawnTimeMs": rel(fight, event.get("timestamp")),
            "deathTimeMs": rel(fight, death.get("timestamp")) if death else None,
            "position": point_payload(point),
        })
    return rows


def attach_rift_instances(fight, rift_instances, event_groups):
    for row in event_groups:
        if row.get("phase") != "P3":
            continue
        time_ms = row.get("fireTimeMs") if row.get("fireTimeMs") is not None else row.get("timeMs")
        if time_ms is None:
            continue
        living = [item for item in rift_instances if item["spawnTimeMs"] <= time_ms and (item.get("deathTimeMs") is None or time_ms < item["deathTimeMs"])]
        rendered = [{
            "id": f"rift-{item['sourceID']}-{item['sourceInstance']}", "name": f"裂隙幻影#{item['sourceInstance']}",
            "gameID": RIFT_SIMULACRUM_GAME_ID, "position": item["position"], "confidence": "high",
        } for item in living]
        if "actors" in row:
            row["actors"] = [actor for actor in row.get("actors") or [] if actor.get("gameID") != RIFT_SIMULACRUM_GAME_ID] + rendered
        if row.get("snapshot"):
            row["snapshot"]["bosses"] = [actor for actor in row["snapshot"].get("bosses") or [] if actor.get("gameID") != RIFT_SIMULACRUM_GAME_ID] + rendered


def healing_breakdown(events, healer_set, target_id, start_ts, end_ts, actor_map, actor_game_id):
    totals = defaultdict(int)
    for event in events["healing"]:
        if event.get("targetID") != target_id or event.get("sourceID") not in healer_set:
            continue
        if start_ts <= event.get("timestamp", 0) <= end_ts:
            totals[event.get("sourceID")] += int(event.get("amount") or 0) + int(event.get("absorbed") or 0)
    rows = [{
        "healerID": healer_id,
        "healer": event_actor_name(actor_map, actor_game_id, healer_id),
        "amount": amount,
    } for healer_id, amount in sorted(totals.items(), key=lambda item: item[1], reverse=True)]
    return {"healingByHealer": rows, "totalHealing": sum(totals.values())}


def actor_ids_for_phase(actor_game_id, phase_name):
    game_ids = {ALLERIA_GAME_ID}
    if phase_name == "P1":
        game_ids.update(P1_ADD_GAME_IDS)
    if phase_name == "P3":
        game_ids.update(P3_ADD_GAME_IDS)
        game_ids.add(RIFT_SIMULACRUM_GAME_ID)
    return sorted(
        actor_id for actor_id, game_id in actor_game_id.items()
        if game_id in game_ids
    )


def build_water(debuffs, damage, position_index, actor_map, actor_game_id, fight, phase, deaths=None):
    active = {}
    drops = []
    for event in sorted(debuffs, key=lambda item: item.get("timestamp", 0)):
        if ability_id(event) != SPELL["void_repulsion_mark"]:
            continue
        target_id = event.get("targetID")
        if "apply" in event_type(event):
            active[target_id] = event
        elif "remove" in event_type(event):
            apply_event = active.get(target_id)
            if any(
                death.get("targetID") == target_id
                and death.get("timestamp", 0) <= event.get("timestamp", 0)
                for death in deaths or []
            ):
                active.pop(target_id, None)
                continue
            exact = event_point(event, "target") or event_point(event)
            state = {"point": point_payload(exact), "confidence": "high", "source": "fadeEvent"} if exact else state_at(position_index, target_id, event.get("timestamp", 0), max_gap_ms=5_000)
            drops.append({
                "id": f"water-{len(drops) + 1}",
                "timeMs": rel(fight, event.get("timestamp")),
                "time": fmt(rel(fight, event.get("timestamp"))),
                "phase": phase_at(event.get("timestamp", 0), phase),
                "player": event_actor_name(actor_map, actor_game_id, target_id),
                "targetID": target_id,
                "position": state.get("point") if state else None,
                "confidence": state.get("confidence") if state else "unknown",
                "applyTimeMs": rel(fight, apply_event.get("timestamp")) if apply_event else None,
            })
    grouped = group_by_window([{"timestamp": fight["startTime"] + drop["timeMs"], **drop} for drop in drops], 9_000)
    for group in grouped:
        members = group["events"]
        points = [drop["position"] for drop in members if drop.get("position")]
        if len(points) < 2:
            continue
        cx = sum(point["x"] for point in points) / len(points)
        cy = sum(point["y"] for point in points) / len(points)
        for drop in members:
            if not drop.get("position"):
                continue
            distance_yards = math.dist((drop["position"]["x"], drop["position"]["y"]), (cx, cy)) / 100.0
            match = next(item for item in drops if item["id"] == drop["id"])
            match["distanceFromGroupYards"] = round(distance_yards, 1)
            match["isOutlier"] = distance_yards > WATER_OUTLIER_YARDS
    for group_index, group in enumerate(grouped):
        phase_name = phase_at(group["start"], phase)
        next_group = next((candidate for candidate in grouped[group_index + 1:] if phase_at(candidate["start"], phase) == phase_name), None)
        for grouped_drop in group["events"]:
            match = next(item for item in drops if item["id"] == grouped_drop["id"])
            match["waterRoundIndex"] = group_index + 1
            match["roundTimeMs"] = rel(fight, group["end"])
            match["maturesAtMs"] = rel(fight, next_group["end"]) if next_group else None
    return drops


def build_water_events(fight, actor_map, actor_game_id, water_drops, phase, position_index, player_actor_ids, player_roles, deaths=None):
    rows = []
    events = [
        {"timestamp": fight["startTime"] + drop["timeMs"], **drop}
        for drop in water_drops
    ]
    for index, group in enumerate(group_by_window(events, 9_000), start=1):
        phase_name = phase_at(group["start"], phase)
        phase_start, _ = phase_window(fight, phase, phase_name)
        time_ms = rel(fight, group["end"])
        apply_times = [drop.get("applyTimeMs") for drop in group["events"] if drop.get("applyTimeMs") is not None]
        apply_abs = fight["startTime"] + min(apply_times) if apply_times else group["start"]
        remote_ids = [
            player_id for player_id in living_player_ids_at(player_actor_ids, deaths, apply_abs)
            if str(player_roles.get(player_id, "")).startswith("range-")
        ]
        remote_rows = actors_at(apply_abs, remote_ids, position_index, actor_map, actor_game_id, max_gap_ms=6_000)
        remote_points = [row["position"] for row in remote_rows if row.get("position")]
        remote_outliers = []
        max_remote_distance = None
        if remote_points:
            cx = sum(point["x"] for point in remote_points) / len(remote_points)
            cy = sum(point["y"] for point in remote_points) / len(remote_points)
            distances = []
            for remote in remote_rows:
                if not remote.get("position"):
                    continue
                distance = math.dist((remote["position"]["x"], remote["position"]["y"]), (cx, cy)) / 100.0
                distances.append(distance)
                if distance > 15:
                    remote_outliers.append({"player": remote["name"], "distanceYards": round(distance, 1)})
            max_remote_distance = round(max(distances), 1) if distances else None
        rows.append({
            "id": f"water-event-{index}",
            "index": index,
            "eventType": "water",
            "phase": phase_name,
            "timeMs": time_ms,
            "time": fmt(time_ms),
            "drops": group["events"],
            "water": [
                drop for drop in water_drops
                if drop["phase"] == phase_name
                and drop.get("maturesAtMs") is not None and drop["maturesAtMs"] <= time_ms
            ],
            "actors": actors_at(group["end"], actor_ids_for_phase(actor_game_id, phase_name), position_index, actor_map, actor_game_id),
            "snapshot": snapshot_at(group["end"], player_actor_ids, actor_ids_for_phase(actor_game_id, phase_name), position_index, actor_map, actor_game_id, deaths),
            "growth": {"startsAtFade": True, "fullAtNextWater": True, "maxRadiusYards": 25},
            "remoteStackCheck": {
                "eligible": phase_name == "P2" and index >= 6,
                "exempt": phase_name == "P2" and index == 5,
                "thresholdYards": 15,
                "remoteCount": len(remote_points),
                "maxDistanceFromCentroidYards": max_remote_distance,
                "outliers": remote_outliers,
                "stacked": not remote_outliers if remote_points else None,
            },
        })
    return rows


def build_bow_groups(fight, actor_map, actor_type, actor_game_id, events, phase, position_index, phantom_segments, water_drops, player_actor_ids, healer_set):
    pairs = pair_void_grasp(events["debuffs"])
    clusters = group_void_grasp_pairs(pairs)
    groups = []
    for index, cluster in enumerate(clusters, start=1):
        fire_ts = max(pair["remove"].get("timestamp", 0) for pair in cluster["pairs"])
        phase_name = phase_at(cluster["start"], phase)
        phase_start, _ = phase_window(fight, phase, phase_name)
        active_by_player = {}
        death_by_player = {}
        active_phantom_map = {}
        for pair in cluster["pairs"]:
            target_id = pair["targetID"]
            apply_ts = pair["apply"].get("timestamp", 0)
            fade_ts = pair["remove"].get("timestamp", 0)
            death = next((
                item for item in events["deaths"]
                if item.get("targetID") == target_id
                and apply_ts <= item.get("timestamp", 0) <= fade_ts + 1_000
            ), None)
            trigger_ts = death.get("timestamp", 0) if death else fade_ts
            pair_key = (target_id, fade_ts)
            death_by_player[pair_key] = death
            pair_active = active_phantoms_at(phantom_segments, trigger_ts)
            active_by_player[pair_key] = pair_active
            for segment in pair_active:
                active_phantom_map[(segment.get("sourceID"), segment.get("sourceInstance"))] = segment
        active_phantoms = list(active_phantom_map.values())
        phantom_rows = []
        for segment in active_phantoms:
            phantom_rows.append({
                "sourceID": segment["sourceID"],
                "sourceInstance": segment["sourceInstance"],
                "name": "银色幻影",
                "firstTime": fmt(rel(fight, segment["first"])),
                "lastTime": fmt(rel(fight, segment["last"])),
                "position": phantom_position(segment, fire_ts, position_index),
            })
        players = []
        group_hits = [
            event for event in events["damage"]
            if ability_id(event) == SPELL["collapsing_void"]
            and cluster["start"] <= event.get("timestamp", 0) <= fire_ts + 2_000
        ]
        for pair in cluster["pairs"]:
            target_id = pair["targetID"]
            apply_ts = pair["apply"].get("timestamp", 0)
            fade_ts = pair["remove"].get("timestamp", 0)
            death = death_by_player.get((target_id, fade_ts))
            trigger_ts = death.get("timestamp", 0) if death else fade_ts
            player_active_phantoms = active_by_player.get((target_id, fade_ts), [])
            player_active_instances = sorted({
                segment.get("sourceInstance") for segment in player_active_phantoms
                if segment.get("sourceInstance") is not None
            })
            resolved_instance_ids = {
                segment.get("sourceInstance") for segment in player_active_phantoms
                if segment.get("sourceInstance") is not None
                and segment["first"] <= trigger_ts
                and 0 <= trigger_ts - segment["last"] <= 2_200
            }
            apply_exact = event_point(pair["apply"], "target") or event_point(pair["apply"])
            apply_state = state_at(position_index, target_id, apply_ts, max_gap_ms=12_000)
            if apply_exact:
                apply_state = apply_state or {}
                apply_state.update({
                    "x": apply_exact[0], "y": apply_exact[1], "point": point_payload(apply_exact),
                    "source": "applyEvent", "deltaMs": 0, "confidence": "high",
                    "facingRaw": event_facing(pair["apply"]),
                    "facingRadians": normalize_facing(event_facing(pair["apply"])),
                })
            trigger_exact = (event_point(death, "target") or event_point(death)) if death else None
            fade_state = state_at(position_index, target_id, trigger_ts, max_gap_ms=3_000)
            if trigger_exact:
                fade_state = fade_state or {}
                fade_state.update({
                    "x": trigger_exact[0], "y": trigger_exact[1], "point": point_payload(trigger_exact),
                    "source": "deathEvent", "deltaMs": 0, "confidence": "high",
                })
            last_second_state = None if death else state_at(position_index, target_id, fade_ts - 1_000, max_gap_ms=3_000)
            last_second_yards = None
            if last_second_state and fade_state:
                last_second_yards = math.dist(
                    (last_second_state["x"], last_second_state["y"]),
                    (fade_state["x"], fade_state["y"]),
                ) / 100.0
            facing_reliable = bool(apply_state and apply_state.get("facingRadians") is not None and abs(apply_state.get("deltaMs") or 0) <= 1_500)
            facing_available = bool(apply_state and apply_state.get("facingRadians") is not None and abs(apply_state.get("deltaMs") or 0) <= 6_000)
            obelisks = make_obelisks(apply_state) if facing_available else []
            rays = make_rays(fade_state, obelisks) if fade_state else []
            actual_hits = [
                event for event in group_hits
                if abs(event.get("timestamp", 0) - trigger_ts) <= 1_500
            ]
            actual_phantom_hits = [
                event for event in actual_hits
                if actor_game_id.get(event.get("targetID")) == PHANTOM_GAME_ID
            ]
            deaths_from_shot = [
                death for death in events["deaths"]
                if death.get("targetID") in {hit.get("targetID") for hit in actual_hits}
                and death.get("killingAbilityGameID") == SPELL["collapsing_void"]
                and trigger_ts <= death.get("timestamp", 0) <= trigger_ts + 2_000
            ]
            healing_end = death.get("timestamp", 0) if death else fade_ts
            healing_start = max(apply_ts, healing_end - 6_000) if death else apply_ts
            all_healing = healing_breakdown(events, healer_set, target_id, apply_ts, healing_end, actor_map, actor_game_id)
            predicted_phantom_hits = []
            for phantom in phantom_rows:
                if phantom.get("sourceInstance") not in player_active_instances:
                    continue
                point = phantom.get("position")
                if not point:
                    continue
                p = (point["x"], point["y"])
                for ray in rays:
                    start = (ray["start"]["x"], ray["start"]["y"])
                    end = (ray["end"]["x"], ray["end"]["y"])
                    distance = distance_point_to_segment(p, start, end)
                    px_per_yard = 4.35 if phase_name in {"P2", "P2.5", "P3"} else 4.93
                    hit_radius_raw = ((8 / 2 + 32 / 2) / px_per_yard) * 100.0
                    if distance <= hit_radius_raw:
                        predicted_phantom_hits.append({
                            "phantom": phantom.get("sourceInstance") or phantom.get("sourceID"),
                            "ray": ray["label"],
                            "distanceYards": round(distance / 100.0, 1),
                        })
            resolved_by_geometry = sorted({
                item["phantom"] for item in predicted_phantom_hits
                if item["phantom"] in resolved_instance_ids
            })
            apply_health = player_health_snapshot(events, target_id, apply_ts)
            players.append({
                "targetID": target_id,
                "player": event_actor_name(actor_map, actor_game_id, target_id),
                "applyTimeMs": rel(fight, apply_ts),
                "applyTime": fmt(rel(fight, apply_ts)),
                "targetHealthAtApply": (apply_health or {}).get("hitPoints"),
                "targetMaxHealthAtApply": (apply_health or {}).get("maxHitPoints"),
                "targetHealthPercentAtApply": (apply_health or {}).get("percent"),
                "targetHealthSampleDeltaMs": (apply_health or {}).get("sampleDeltaMs"),
                "fadeTimeMs": rel(fight, fade_ts),
                "fadeTime": fmt(rel(fight, fade_ts)),
                "triggerTimeMs": rel(fight, trigger_ts),
                "triggerTime": fmt(rel(fight, trigger_ts)),
                "deathTriggeredRay": bool(death),
                "diedAtFire": bool(death),
                "deathTimeMs": rel(fight, death.get("timestamp")) if death else None,
                "deathTime": fmt(rel(fight, death.get("timestamp"))) if death else None,
                "applyState": apply_state,
                "applyFacingReliable": facing_reliable,
                "applyFacingEstimated": facing_available and not facing_reliable,
                "fadeState": fade_state,
                "lastSecondState": last_second_state,
                "lastSecondMovementYards": round(last_second_yards, 2) if last_second_yards is not None else None,
                "isSnapAiming": last_second_yards is not None and last_second_yards > SNAP_MOVEMENT_YARDS,
                "obelisks": obelisks,
                "rays": rays,
                "actualHits": [
                    {
                        "time": fmt(rel(fight, event.get("timestamp"))),
                        "target": event_actor_name(actor_map, actor_game_id, event.get("targetID")),
                        "targetID": event.get("targetID"),
                        "targetType": "phantom" if actor_game_id.get(event.get("targetID")) == PHANTOM_GAME_ID else actor_type.get(event.get("targetID")),
                        "amount": int(event.get("amount") or 0) + int(event.get("absorbed") or 0),
                    }
                    for event in actual_hits
                ],
                "actualPhantomHitCount": len(actual_phantom_hits) if actual_phantom_hits else len(resolved_by_geometry),
                "resolvedPhantomInstances": resolved_by_geometry,
                "resolutionEvidence": "damageEvent" if actual_phantom_hits else ("instance2sCycle+geometry" if resolved_by_geometry else "none"),
                "predictedPhantomHits": predicted_phantom_hits,
                "activePhantomInstances": player_active_instances,
                "phantomEligible": phase_name == "P2" and bool(player_active_instances),
                "potentialMissedPhantom": phase_name == "P2" and bool(player_active_instances) and len(actual_phantom_hits) == 0 and len(predicted_phantom_hits) == 0,
                "missedPhantom": False,
                "snapAimingDeaths": [{
                    "targetID": item.get("targetID"),
                    "player": event_actor_name(actor_map, actor_game_id, item.get("targetID")),
                    "timeMs": rel(fight, item.get("timestamp")),
                    "time": fmt(rel(fight, item.get("timestamp"))),
                } for item in deaths_from_shot] if last_second_yards is not None and last_second_yards > SNAP_MOVEMENT_YARDS else [],
                "healing": healing_breakdown(events, healer_set, target_id, healing_start, healing_end, actor_map, actor_game_id),
                "allHealing": all_healing,
                "healingWindow": {"startTimeMs": rel(fight, healing_start), "endTimeMs": rel(fight, healing_end), "deathLimited": bool(death)},
            })
        groups.append({
            "id": f"bow-{index}",
            "index": index,
            "phase": phase_name,
            "applyStartMs": rel(fight, cluster["start"]),
            "applyStart": fmt(rel(fight, cluster["start"])),
            "fireTimeMs": rel(fight, fire_ts),
            "fireTime": fmt(rel(fight, fire_ts)),
            "players": players,
            "actors": actors_at(fire_ts, actor_ids_for_phase(actor_game_id, phase_name), position_index, actor_map, actor_game_id),
            "snapshot": snapshot_at(fire_ts, player_actor_ids, actor_ids_for_phase(actor_game_id, phase_name), position_index, actor_map, actor_game_id, events["deaths"]),
            "phantoms": phantom_rows,
            "water": [
                drop for drop in water_drops
                if drop["phase"] == phase_name
                and drop.get("maturesAtMs") is not None and drop["maturesAtMs"] <= rel(fight, fire_ts)
            ],
            "activePhantomCount": len(active_phantoms),
            "phantomEligible": phase_name == "P2" and bool(active_phantoms),
            "eventType": "bow",
        })
    return groups


def build_silver_arrows(fight, actor_map, actor_type, actor_game_id, events, phase, position_index, player_actor_ids, phantom_segments):
    mark_ids = {SPELL["silver_arrow_mark"], SPELL["ranger_mark"]}
    marks = [event for event in events["debuffs"] if ability_id(event) in mark_ids and "apply" in event_type(event)]
    rows = []
    for index, group in enumerate(group_by_window(marks, 3_000), start=1):
        spell_id = ability_id(group["events"][0])
        removes = [event for event in events["debuffs"] if ability_id(event) == spell_id and "remove" in event_type(event) and group["start"] <= event.get("timestamp", 0) <= group["end"] + 10_000]
        effect_ts = max((event.get("timestamp", 0) for event in removes), default=group["start"])
        drains = [event for event in events["enemyResources"] if ability_id(event) == SPELL["silver_ricochet_energy_drain"] and group["start"] <= event.get("timestamp", 0) <= group["end"] + 8_000]
        damage_id = SPELL["silver_arrow_damage"] if spell_id == SPELL["silver_arrow_mark"] else SPELL["silver_ricochet"]
        hits = [event for event in events["damage"] if ability_id(event) == damage_id and effect_ts - 2_500 <= event.get("timestamp", 0) <= effect_ts + 2_500]
        phase_name = phase_at(group["start"], phase)
        bosses = actor_ids_for_phase(actor_game_id, phase_name)
        phase_mark_events = [event for event in group["events"] if phase_at(event.get("timestamp", 0), phase) == phase_name]
        marked_positions = []
        if phase_name == "P1":
            for mark_event in phase_mark_events:
                target_id = mark_event.get("targetID")
                state = state_at(position_index, target_id, effect_ts, max_gap_ms=6_000)
                marked_positions.append({
                    "targetID": target_id,
                    "player": event_actor_name(actor_map, actor_game_id, target_id),
                    "position": state.get("point") if state else None,
                    "facingRadians": state.get("facingRadians") if state else None,
                    "confidence": state.get("confidence") if state else "unknown",
                })
        source_phantoms = [{
            "sourceInstance": segment.get("sourceInstance"), "position": segment.get("castPosition"),
            "castTimeMs": rel(fight, segment.get("castTime")), "castTimeAbsolute": segment.get("castTime"),
        } for segment in phantom_segments if phase_name == "P2" and group["start"] - 1_000 <= (segment.get("castTime") or 0) <= group["end"] + 3_000]
        source_assignments = []
        if phase_name == "P2":
            for phantom in source_phantoms:
                assigned = sorted(
                    phase_mark_events,
                    key=lambda event: abs(event.get("timestamp", 0) - phantom.get("castTimeAbsolute", 0)),
                )[:2]
                source_assignments.append({
                    "sourceInstance": phantom.get("sourceInstance"),
                    "players": [event_actor_name(actor_map, actor_game_id, event.get("targetID")) for event in assigned],
                    "bossEnergyDrained": bool(drains),
                })
        # P1 银锋箭：Boss 束缚/腐化常在「点名 apply」附近被清掉，而 effect_ts 取的是点名
        # remove（箭实际射出感）。实战中两者可相差 >2.5s（如 Fight21 #2：apply/束缚≈00:40，
        # remove≈00:43.5）。窗口需覆盖 apply→remove，与 analyze_p1_arrows 一致。
        p1_enemy_removes = [
            event for event in events.get("enemyDebuffs", [])
            if ability_id(event) in P1_BINDING_IDS and "remove" in event_type(event)
            and group["start"] - 1_000 <= event.get("timestamp", 0) <= effect_ts + 2_500
        ] if phase_name == "P1" else []
        # 几何归因：优先用束缚移除时刻的 Boss 快照（目标死后 effect_ts 快照里会缺席）
        geometry_ts = min((event.get("timestamp", 0) for event in p1_enemy_removes), default=effect_ts)
        boss_by_id = {row.get("id"): row for row in snapshot_at(geometry_ts, [], bosses, position_index, actor_map, actor_game_id)["bosses"]}
        alleria = next((row for row in boss_by_id.values() if row.get("gameID") == ALLERIA_GAME_ID and row.get("position")), None)
        if not alleria:
            alleria = next(
                (
                    row for row in snapshot_at(effect_ts, [], bosses, position_index, actor_map, actor_game_id)["bosses"]
                    if row.get("gameID") == ALLERIA_GAME_ID and row.get("position")
                ),
                None,
            )
        p1_boss_attribution = []
        if alleria and alleria.get("position"):
            start = (alleria["position"]["x"], alleria["position"]["y"])
            removed_ids = {event.get("targetID") for event in p1_enemy_removes}
            for marked in marked_positions:
                if not marked.get("position"):
                    continue
                through = (marked["position"]["x"], marked["position"]["y"])
                direction_x = through[0] - start[0]
                direction_y = through[1] - start[1]
                direction_length = math.hypot(direction_x, direction_y)
                if direction_length <= 0:
                    continue
                end = (
                    start[0] + direction_x / direction_length * RAY_LENGTH_RAW,
                    start[1] + direction_y / direction_length * RAY_LENGTH_RAW,
                )
                matched = []
                for boss_id in removed_ids:
                    boss = boss_by_id.get(boss_id)
                    if boss and boss.get("position") and distance_point_to_segment((boss["position"]["x"], boss["position"]["y"]), start, end) <= 500:
                        matched.append(boss.get("name"))
                p1_boss_attribution.append({"targetID": marked.get("targetID"), "player": marked["player"], "bosses": matched, "hitBoss": bool(matched)})
        p1_hit_events = [
            {
                "targetID": event.get("targetID"),
                "boss": event_actor_name(actor_map, actor_game_id, event.get("targetID")),
                "timeMs": rel(fight, event.get("timestamp")),
            }
            for event in p1_enemy_removes
        ]
        rows.append({
            "id": f"silver-arrow-{index}", "index": index, "eventType": "silverArrow", "phase": phase_name,
            "spellID": spell_id,
            "timeMs": rel(fight, effect_ts), "time": fmt(rel(fight, effect_ts)),
            "markedPlayers": [event_actor_name(actor_map, actor_game_id, event.get("targetID")) for event in group["events"]],
            "markedPlayerPositions": marked_positions,
            "actualHits": [{"targetID": e.get("targetID"), "target": event_actor_name(actor_map, actor_game_id, e.get("targetID")), "amount": int(e.get("amount") or 0) + int(e.get("absorbed") or 0), "isMarked": e.get("targetID") in {mark.get("targetID") for mark in phase_mark_events}} for e in hits],
            "bossEnergyDrained": bool(drains), "drainCount": len(drains),
            "failedPlayers": [event_actor_name(actor_map, actor_game_id, event.get("targetID")) for event in phase_mark_events] if phase_name == "P2" and not drains else [],
            "snapshot": snapshot_at(effect_ts, player_actor_ids, bosses, position_index, actor_map, actor_game_id, events["deaths"]),
            "sourcePhantoms": [{key: value for key, value in item.items() if key != "castTimeAbsolute"} for item in source_phantoms],
            "sourceAssignments": source_assignments,
            "p1BossHitEvents": p1_hit_events,
            "p1BossAttribution": p1_boss_attribution,
            "p1AllMissedBoss": phase_name == "P1" and not any(item.get("hitBoss") for item in p1_boss_attribution) and not p1_hit_events,
        })
    return rows


def build_gravity_rounds(fight, actor_map, debuffs, deaths, player_roles, damage=None):
    guard_applies = [event for event in debuffs if ability_id(event) == TERMINAL_GUARD_ID and event_type(event) == "applydebuff"]
    rounds = []
    for index, cluster in enumerate(group_by_window(guard_applies, 1_000), start=1):
        start = cluster["start"]
        targets = unique = []
        seen = set()
        for event in cluster["events"]:
            if event.get("targetID") not in seen:
                seen.add(event.get("targetID")); unique.append(event)
        target_ids = set(seen)
        breaks = [event for event in debuffs if ability_id(event) == TERMINAL_GUARD_ID and "remove" in event_type(event) and event.get("targetID") in target_ids and start <= event.get("timestamp", 0) <= start + 20_000]
        breaks = sorted(breaks, key=lambda event: event.get("timestamp", 0))
        break_rows = []
        previous = None
        for order, event in enumerate(breaks, start=1):
            delay = event.get("timestamp", 0) - start if order == 1 else event.get("timestamp", 0) - previous
            compliant = delay <= 3_000 if order == 1 else delay >= 2_000
            trigger_death = min(
                (
                    death for death in deaths
                    if death.get("targetID") == event.get("targetID")
                    and abs(death.get("timestamp", 0) - event.get("timestamp", 0)) <= 750
                ),
                key=lambda death: abs(death.get("timestamp", 0) - event.get("timestamp", 0)),
                default=None,
            )
            break_rows.append({
                "order": order, "player": event_actor_name(actor_map, {}, event.get("targetID")), "targetID": event.get("targetID"),
                "timeMs": rel(fight, event.get("timestamp")), "time": fmt(rel(fight, event.get("timestamp"))),
                "delayMs": delay, "compliant": compliant,
                "rule": "首棒≤3秒" if order == 1 else "与前一棒间隔≥2秒",
                "deathTriggered": trigger_death is not None,
                "deathTrigger": {
                    "timeMs": rel(fight, trigger_death.get("timestamp")),
                    "time": fmt(rel(fight, trigger_death.get("timestamp"))),
                    "abilityID": trigger_death.get("killingAbilityGameID"),
                } if trigger_death else None,
            })
            previous = event.get("timestamp", 0)
        gravity_deaths = [death for death in deaths if death.get("killingAbilityGameID") == GRAVITY_COLLAPSE_DAMAGE_ID and start <= death.get("timestamp", 0) <= start + 25_000]
        gravity_hits = [
            event for event in damage or []
            if ability_id(event) == GRAVITY_COLLAPSE_DAMAGE_ID
            and start <= event.get("timestamp", 0) <= start + 25_000
        ]
        compensation_rows = []
        for compensation in (
            event for event in debuffs
            if ability_id(event) == DEATH_COMPENSATION_ID
            and event_type(event) == "applydebuff"
            and start <= event.get("timestamp", 0) <= start + 25_000
        ):
            target_id = compensation.get("targetID")
            matching_hit = min(
                (
                    event for event in gravity_hits
                    if event.get("targetID") == target_id
                    and 0 <= compensation.get("timestamp", 0) - event.get("timestamp", 0) <= 15_000
                ),
                key=lambda event: compensation.get("timestamp", 0) - event.get("timestamp", 0),
                default=None,
            )
            if not matching_hit:
                continue
            death_events_before = [
                death for death in deaths
                if death.get("timestamp", 0) <= compensation.get("timestamp", 0)
            ]
            dead_before = {
                death.get("targetID")
                for death in death_events_before
                if death.get("targetID") is not None
            }
            under_eight = len(death_events_before) < 8
            compensation_rows.append({
                "player": event_actor_name(actor_map, {}, target_id),
                "targetID": target_id,
                "timeMs": rel(fight, compensation.get("timestamp")),
                "time": fmt(rel(fight, compensation.get("timestamp"))),
                "gravityDamageTimeMs": rel(fight, matching_hit.get("timestamp")),
                "gravityDamageTime": fmt(rel(fight, matching_hit.get("timestamp"))),
                "gravityDamageAmount": int(matching_hit.get("amount") or 0) + int(matching_hit.get("absorbed") or 0),
                "deathEventCountBeforeCompensation": len(death_events_before),
                "uniqueDeadPlayerCountBeforeCompensation": len(dead_before),
                "underEightDeaths": under_eight,
                "countedAsEffectiveDeath": under_eight,
            })
        actual_death_ids = {death.get("targetID") for death in gravity_deaths}
        effective_compensations = [
            row for row in compensation_rows
            if row["countedAsEffectiveDeath"] and row.get("targetID") not in actual_death_ids
        ]
        effective_death_count = len(gravity_deaths) + len(effective_compensations)
        effective_death_players = [
            event_actor_name(actor_map, {}, death.get("targetID")) for death in gravity_deaths
        ] + [row["player"] for row in effective_compensations]
        prior_deaths = [death for death in deaths if death.get("timestamp", 0) < start]
        prior_dead_ids = {death.get("targetID") for death in prior_deaths if death.get("targetID") is not None}
        prior_healer_deaths = [
            death for death in prior_deaths
            if str(player_roles.get(death.get("targetID"), "")).endswith("-healer")
        ]
        round_healer_deaths = [
            death for death in gravity_deaths
            if str(player_roles.get(death.get("targetID"), "")).endswith("-healer")
        ]
        healer_death_count = len(prior_healer_deaths) + len(round_healer_deaths)
        violations = [
            row for row in break_rows
            if not row["compliant"] and not row.get("deathTriggered")
        ]
        first_violation = next(iter(violations), None)
        attrition_exempt = len(prior_dead_ids) > 4 or healer_death_count > 2
        compensation_countable = bool(effective_compensations)
        counted = bool(
            first_violation
            and effective_death_count
            and (compensation_countable or not attrition_exempt)
        )
        casualty_timestamps = [death.get("timestamp", 0) for death in gravity_deaths]
        casualty_timestamps += [
            fight["startTime"] + row["gravityDamageTimeMs"]
            for row in effective_compensations
        ]
        first_casualty = min(casualty_timestamps, default=None)
        trigger = max(
            (
                row for row in break_rows
                if first_casualty is None
                or fight["startTime"] + row["timeMs"] <= first_casualty
            ),
            key=lambda row: row["timeMs"],
            default=None,
        )
        death_triggered_collapse = bool(trigger and trigger.get("deathTriggered"))
        rounds.append({
            "index": index, "applyTimeMs": rel(fight, start), "applyTime": fmt(rel(fight, start)),
            "targets": [event_actor_name(actor_map, {}, event.get("targetID")) for event in unique],
            "breaks": break_rows, "violations": violations,
            "deathCount": len(gravity_deaths),
            "deathPlayers": [event_actor_name(actor_map, {}, death.get("targetID")) for death in gravity_deaths],
            "compensationCount": len(effective_compensations),
            "compensationPlayers": [row["player"] for row in effective_compensations],
            "compensations": compensation_rows,
            "effectiveDeathCount": effective_death_count,
            "effectiveDeathPlayers": effective_death_players,
            "collapseTrigger": trigger,
            "deathTriggeredCollapse": death_triggered_collapse,
            "deathTriggeredPlayer": trigger.get("player") if death_triggered_collapse else None,
            "priorDeathCount": len(prior_dead_ids),
            "priorHealerDeathCount": len(prior_healer_deaths),
            "healerDeathCountThroughRound": healer_death_count,
            "firstViolation": first_violation,
            "attributedPlayer": first_violation.get("player") if first_violation else None,
            "attributedPlayerID": first_violation.get("targetID") if first_violation else None,
            "causedDeaths": bool(effective_death_count),
            "counted": counted,
            "exemptReason": (
                f"大团已减员过多（本轮前已有{len(prior_dead_ids)}名不同玩家死亡，本轮结算后治疗死亡{healer_death_count}人）"
                if attrition_exempt and not compensation_countable else (
                    "本轮没有造成减员"
                    if not effective_death_count else (
                        f"本轮重力坍缩由{trigger.get('player')}死亡直接触发，死亡玩家不作为归因人"
                        if death_triggered_collapse and not first_violation else None
                    )
                )
            ),
        })
    return rounds


def alive_players_at(events, player_set, timestamp):
    alive = set(player_set)
    timeline = []
    for death in events["deaths"]:
        target_id = death.get("targetID")
        if target_id in player_set and death.get("timestamp", 0) <= timestamp:
            timeline.append((death.get("timestamp", 0), 0, "death", target_id))
    for cast in events["casts"]:
        cast_type = event_type(cast)
        if "resurrect" not in cast_type and ability_id(cast) not in COMBAT_RESURRECTION_IDS:
            continue
        target_id = cast.get("targetID") or cast.get("sourceID")
        if target_id in player_set and cast.get("timestamp", 0) <= timestamp:
            timeline.append((cast.get("timestamp", 0), 1, "resurrect", target_id))
    for _, _, kind, target_id in sorted(timeline):
        if kind == "death":
            alive.discard(target_id)
        elif target_id not in alive:
            alive.add(target_id)
    return alive


def player_health_snapshot(events, target_id, timestamp, before_ms=3_000, after_ms=1_000):
    """Return the nearest reliable target-health sample around a mechanic apply."""
    candidates = []
    for event in events.get("healing") or []:
        event_ts = int(event.get("timestamp") or 0)
        if event.get("targetID") != target_id or not (timestamp - before_ms <= event_ts <= timestamp + after_ms):
            continue
        hit_points = event.get("hitPoints")
        max_hit_points = event.get("maxHitPoints")
        if hit_points is None or not max_hit_points:
            continue
        resource_actor = event.get("resourceActor")
        if resource_actor not in {2, "2"} and not (
            event.get("sourceID") == target_id and resource_actor in {1, "1"}
        ):
            continue
        candidates.append(event)
    if not candidates:
        return None
    before = [event for event in candidates if int(event.get("timestamp") or 0) <= timestamp]
    event = max(before, key=lambda row: int(row.get("timestamp") or 0)) if before else min(
        candidates, key=lambda row: int(row.get("timestamp") or 0)
    )
    hit_points = int(event.get("hitPoints") or 0)
    max_hit_points = int(event.get("maxHitPoints") or 0)
    return {
        "hitPoints": hit_points,
        "maxHitPoints": max_hit_points,
        "percent": round(hit_points * 100 / max_hit_points, 2) if max_hit_points else None,
        "sampleTimeMs": int(event.get("timestamp") or 0),
        "sampleDeltaMs": int(event.get("timestamp") or 0) - int(timestamp),
    }


def build_void_death_healing(fight, actor_map, actor_game_id, events, player_set, healer_set, phantom_segments):
    # player_ids() returns a sorted list for snapshot ordering; coerce to sets for roster math.
    player_id_set = set(player_set)
    healer_id_set = set(healer_set)
    rows = []
    for death in events["deaths"]:
        if death.get("killingAbilityGameID") not in {SPELL["collapsing_void"], SPELL["void_grasp"]}:
            continue
        target_id = death.get("targetID")
        ts = death.get("timestamp", 0)
        totals6s = defaultdict(int)
        totals8s = defaultdict(int)
        for event in events["healing"]:
            if event.get("targetID") != target_id:
                continue
            if event.get("sourceID") not in healer_id_set:
                continue
            event_ts = event.get("timestamp", 0)
            if not (ts - 8_000 <= event_ts <= ts):
                continue
            amount = int(event.get("amount") or 0) + int(event.get("absorbed") or 0)
            totals8s[event.get("sourceID")] += amount
            if ts - 6_000 <= event_ts:
                totals6s[event.get("sourceID")] += amount
        active_count = len(active_phantoms_at(phantom_segments, ts))
        alive_players = alive_players_at(events, player_id_set, ts)
        alive_healers = healer_id_set & alive_players
        dead_players = player_id_set - alive_players
        apply_event = max((
            event for event in events["debuffs"]
            if ability_id(event) == SPELL["void_grasp"]
            and event.get("targetID") == target_id
            and "apply" in event_type(event)
            and ts - 15_000 <= event.get("timestamp", 0) <= ts
        ), key=lambda event: event.get("timestamp", 0), default=None)
        health = player_health_snapshot(events, target_id, apply_event.get("timestamp", 0)) if apply_event else None
        rows.append({
            "timeMs": rel(fight, ts),
            "time": fmt(rel(fight, ts)),
            "player": event_actor_name(actor_map, actor_game_id, target_id),
            "targetID": target_id,
            "abilityID": death.get("killingAbilityGameID"),
            "applyTimeMs": rel(fight, apply_event.get("timestamp")) if apply_event else None,
            "targetHealthAtApply": (health or {}).get("hitPoints"),
            "targetMaxHealthAtApply": (health or {}).get("maxHitPoints"),
            "targetHealthPercentAtApply": (health or {}).get("percent"),
            "targetHealthSampleDeltaMs": (health or {}).get("sampleDeltaMs"),
            "activePhantomCount": active_count,
            "exemptByPhantoms": active_count >= 4,
            "playerRosterCount": len(player_id_set),
            "deadPlayerCountAtDeath": len(dead_players),
            "deadPlayerIDsAtDeath": sorted(dead_players),
            "healerRosterCount": len(healer_id_set),
            "healerRosterIDs": sorted(healer_id_set),
            "healerRoster": [
                {
                    "healerID": healer_id,
                    "healer": event_actor_name(actor_map, actor_game_id, healer_id),
                }
                for healer_id in sorted(healer_id_set)
            ],
            "aliveHealerCountAtDeath": len(alive_healers),
            "aliveHealerIDsAtDeath": sorted(alive_healers),
            "healingByHealer": [
                {
                    "healerID": healer_id,
                    "healer": event_actor_name(actor_map, actor_game_id, healer_id),
                    "amount": totals6s.get(healer_id, 0),
                    "healing6s": totals6s.get(healer_id, 0),
                    "healing8s": amount,
                }
                for healer_id, amount in sorted(totals8s.items(), key=lambda item: item[1], reverse=True)
            ],
            "totalHealing": sum(totals6s.values()),
            "totalHealing6s": sum(totals6s.values()),
            "totalHealing8s": sum(totals8s.values()),
        })
    return rows


def build_ranger_energy(fight, actor_map, actor_game_id, events, phase):
    rows = []
    p2_start = phase.get("p2Start") or fight["startTime"]
    p2_end = phase.get("p25Start") or fight["endTime"]
    marks = [
        event for event in events["debuffs"]
        if ability_id(event) == SPELL["ranger_mark"]
        and "apply" in event_type(event)
        and p2_start <= event.get("timestamp", 0) <= p2_end
    ]
    for index, group in enumerate(group_by_window(marks, 3_000), start=1):
        window_end = group["end"] + 8_000
        drains = [
            event for event in events["enemyResources"]
            if ability_id(event) == SPELL["silver_ricochet_energy_drain"]
            and group["start"] <= event.get("timestamp", 0) <= window_end
        ]
        rows.append({
            "index": index,
            "timeMs": rel(fight, group["start"]),
            "time": fmt(rel(fight, group["start"])),
            "players": [event_actor_name(actor_map, actor_game_id, event.get("targetID")) for event in group["events"]],
            "success": bool(drains),
            "drainCount": len(drains),
        })
    return rows


def summarize_counts(bow_groups, ranger_energy, water_drops):
    missed_phantom = defaultdict(int)
    p2_marked = defaultdict(int)
    snap_aiming = defaultdict(lambda: {"markedCount": 0, "snapCount": 0, "deathCount": 0})
    for group in bow_groups:
        for player in group["players"]:
            snap_row = snap_aiming[player["player"]]
            snap_row["markedCount"] += 1
            if player.get("isSnapAiming"):
                snap_row["snapCount"] += 1
                snap_row["deathCount"] += len(player.get("snapAimingDeaths") or [])
            if group["phase"] != "P2" or not player.get("phantomEligible"):
                continue
            p2_marked[player["player"]] += 1
            if player.get("missedPhantom") and not player.get("diedAtFire"):
                missed_phantom[player["player"]] += 1
    missed_energy = defaultdict(int)
    for row in ranger_energy:
        if row["success"]:
            continue
        for player in row["players"]:
            missed_energy[player] += 1
    water_outliers = defaultdict(lambda: defaultdict(int))
    for drop in water_drops:
        if drop.get("isOutlier"):
            water_outliers[drop["phase"]][drop["player"]] += 1
    return {
        "bowGroupsByPhase": dict(sorted((phase, sum(1 for group in bow_groups if group["phase"] == phase)) for phase in ["P1", "P1.5", "P2", "P2.5", "P3"])),
        "p2MissedPhantomByPlayer": [
            {"player": player, "markedCount": p2_marked[player], "count": count}
            for player, count in sorted(missed_phantom.items(), key=lambda item: item[1], reverse=True)
        ],
        "p2MarkedByPlayer": [{"player": player, "count": count} for player, count in sorted(p2_marked.items(), key=lambda item: item[1], reverse=True)],
        "snapAimingByPlayer": [
            {"player": player, **counts}
            for player, counts in sorted(snap_aiming.items(), key=lambda item: (item[1]["deathCount"], item[1]["snapCount"], item[1]["markedCount"]), reverse=True)
        ],
        "p2MissedEnergyByPlayer": [{"player": player, "count": count} for player, count in sorted(missed_energy.items(), key=lambda item: item[1], reverse=True)],
        "waterOutliersByPhase": {
            phase: [{"player": player, "count": count} for player, count in sorted(players.items(), key=lambda item: item[1], reverse=True)]
            for phase, players in water_outliers.items()
        },
    }


def build_single_fight_audit(token, report_id, fight, actor_map=None, actor_type=None, actor_game_id=None):
    if actor_map is None or actor_type is None or actor_game_id is None:
        actor_map, actor_type, actor_game_id = fetch_actor_maps(token, report_id)
    events = fetch_spell_bundle(token, report_id, fight)
    try:
        events["enemyDeaths"] = dedupe(fetch_events_all_ext(token, report_id, "Deaths", fight, hostility_type="Enemies"))
    except Exception:
        events["enemyDeaths"] = []
    hostile_p3_casts = []
    for spell_id in (COSMIC_DEVOUR_ID, SPELL["portal"]):
        hostile_p3_casts.extend(fetch_events_all_ext(
            token, report_id, "Casts", fight,
            ability_id=spell_id, hostility_type="Enemies", include_resources=True,
        ))
    events["casts"].extend(dedupe(hostile_p3_casts))
    phase = build_phase(fight, events)
    relevant_actor_ids = sorted(
        actor_id for actor_id, game_id in actor_game_id.items()
        if game_id == ALLERIA_GAME_ID or game_id in ADD_GAME_IDS or game_id == RIFT_SIMULACRUM_GAME_ID
    )
    extra_position_events = fetch_actor_position_events(token, report_id, fight, relevant_actor_ids)

    phantom_actor_ids = sorted(actor_id for actor_id, game_id in actor_game_id.items() if game_id == PHANTOM_GAME_ID)
    phantom_damage = []
    phantom_casts = []
    for actor_id in phantom_actor_ids:
        phantom_damage.extend(fetch_events_all_ext(token, report_id, "DamageDone", fight, source_id=actor_id, hostility_type="Enemies", include_resources=True))
        phantom_casts.extend(fetch_events_all_ext(token, report_id, "Casts", fight, source_id=actor_id, hostility_type="Enemies", include_resources=True))
    events["damage"].extend(dedupe(phantom_damage))
    events["casts"].extend(dedupe(phantom_casts))

    position_events = (
        events["resources"]
        + events["enemyResources"]
        + events["casts"]
        + events["debuffs"]
        + events["buffs"]
        + events["damage"]
        + extra_position_events
    )
    position_index = build_position_index(position_events)
    # Boss damage/debuff rows can carry the victim's bare x/y.  Never let those
    # ambiguous coordinates overwrite an NPC trajectory.  For NPCs, keep only
    # self-owned cast/resource rows or an explicitly named source position.
    safe_boss_events = [
        event for event in extra_position_events
        if event.get("sourceID") in relevant_actor_ids
        and (event_point(event, "source") is not None or (
            "damage" not in event_type(event)
            and "buff" not in event_type(event)
            and "debuff" not in event_type(event)
        ))
    ]
    safe_boss_index = build_position_index(safe_boss_events)
    for actor_id in relevant_actor_ids:
        if safe_boss_index.get(actor_id):
            position_index[actor_id] = safe_boss_index[actor_id]
    players = player_ids(events["combatants"], actor_type)
    healers = healer_ids(events["combatants"])
    player_roles = build_player_mechanic_roles(events["combatants"])
    phantom_segments = phantom_segments_from_damage(events["damage"], actor_game_id, events["casts"])
    water_drops = build_water(events["debuffs"], events["damage"], position_index, actor_map, actor_game_id, fight, phase, events["deaths"])
    bow_groups = build_bow_groups(fight, actor_map, actor_type, actor_game_id, events, phase, position_index, phantom_segments, water_drops, players, healers)
    water_events = build_water_events(fight, actor_map, actor_game_id, water_drops, phase, position_index, players, player_roles, events["deaths"])
    silver_arrows = build_silver_arrows(fight, actor_map, actor_type, actor_game_id, events, phase, position_index, players, phantom_segments)
    ranger_energy = build_ranger_energy(fight, actor_map, actor_game_id, events, phase)
    void_deaths = build_void_death_healing(fight, actor_map, actor_game_id, events, players, healers, phantom_segments)
    p3_events, p3_contaminations = build_p3_events(fight, actor_map, actor_game_id, events, phase, position_index, players)
    gravity_rounds = build_gravity_rounds(
        fight,
        actor_map,
        events["debuffs"],
        events["deaths"],
        player_roles,
        events["damage"],
    )
    refine_p2_shot_attribution(fight, bow_groups, water_events, phantom_segments, player_roles)
    rift_instances = build_rift_instances(fight, events["casts"] + extra_position_events, events["enemyDeaths"], actor_game_id)
    apply_npc_lifetimes(fight, events["enemyDeaths"], bow_groups + water_events + silver_arrows + p3_events)
    attach_rift_instances(fight, rift_instances, bow_groups + water_events + silver_arrows + p3_events)

    result = {
        "meta": {
            "reportID": report_id,
            "fightID": fight["id"],
            "schemaVersion": FIELD_AUDIT_VERSION,
            "sourceURL": f"https://www.warcraftlogs.com/reports/{report_id}?fight={fight['id']}",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "mechanicNote": "Void Grasp apply fixes three obelisks behind/left-front/right-front; on debuff remove, rays fire from the player's current position toward those fixed obelisks.",
        },
        "fight": {
            "id": fight["id"],
            "name": fight.get("name"),
            "kill": fight.get("kill"),
            "durationMs": fight["endTime"] - fight["startTime"],
            "duration": fmt(fight["endTime"] - fight["startTime"]),
        },
        "phase": {
            key: (fmt(rel(fight, value)) if isinstance(value, int) else value)
            for key, value in phase.items()
            if key != "labels"
        },
        "arena": {
            "image": "assets/crown_of_cosmos_arena.png",
            "imageByPhase": {"P1": "assets/crown_of_cosmos_arena.png", "P1.5": "assets/crown_of_cosmos_arena.png", "P2": "assets/crown_of_cosmos_arena_p2.png", "P2.5": "assets/crown_of_cosmos_arena_p2.png", "P3": "assets/crown_of_cosmos_arena_p2.png"},
            "center": {"x": -36385, "y": 478822},
            "pixelsPerYard": 4.6,
            "pixelsPerYardByPhase": {"P1": 4.93, "P1.5": 4.93, "P2": 4.35, "P2.5": 4.35, "P3": 4.35},
            "radiusYardsByPhase": {"P1": 75, "P1.5": 75, "P2": 85, "P2.5": 85, "P3": 85},
            "waterGrowthModel": "linearUntilNextWater",
            "waterRadiusYards": 25,
            "rayLengthYards": 100,
            "rayWidthPixels": 3,
        },
        "icons": {
            "alleria": "boss_plugins/assets/alleria_windrunner.png",
            "silverPhantom": "boss_plugins/assets/silver_phantom.png",
        },
        "bowGroups": bow_groups,
        "waterEvents": water_events,
        "silverArrows": silver_arrows,
        "phantomInstances": [{
            "sourceID": segment.get("sourceID"), "sourceInstance": segment.get("sourceInstance"),
            "firstTimeMs": rel(fight, segment.get("first")), "lastTimeMs": rel(fight, segment.get("last")),
            "castTimeMs": rel(fight, segment.get("castTime")) if segment.get("castTime") else None,
            "spawnTimeMs": phantom_spawn_time_ms(segment, bow_groups, fight),
            "position": segment.get("castPosition"),
        } for segment in phantom_segments],
        "p3Events": p3_events,
        "p3Contaminations": p3_contaminations,
        "gravityRounds": gravity_rounds,
        "riftInstances": rift_instances,
        "waterDrops": water_drops,
        "voidDeaths": void_deaths,
        "deathDetails": [{
            "timeMs": rel(fight, event.get("timestamp")),
            "time": fmt(rel(fight, event.get("timestamp"))),
            "phase": phase_at(event.get("timestamp", 0), phase),
            "player": event_actor_name(actor_map, actor_game_id, event.get("targetID")),
            "targetID": event.get("targetID"),
            "abilityID": event.get("killingAbilityGameID"),
        } for event in sorted(events["deaths"], key=lambda item: item.get("timestamp", 0))],
        "rangerEnergy": ranger_energy,
        "summary": summarize_counts(bow_groups, ranger_energy, water_drops),
        "debugCounts": {
            **{key: len(value) for key, value in events.items() if isinstance(value, list)},
            "extraPositionEvents": len(extra_position_events),
        },
    }
    return result


def main():
    token = get_token()
    fights = fetch_report_fights(token, REPORT_ID)
    fight = next((item for item in fights if item["id"] == FIGHT_ID), None)
    if not fight:
        raise RuntimeError(f"fight {FIGHT_ID} not found")
    result = build_single_fight_audit(token, REPORT_ID, fight)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT_PATH}")
    print(json.dumps({
        "bowGroupsByPhase": result["summary"]["bowGroupsByPhase"],
        "voidDeaths": len(result["voidDeaths"]),
        "p2MissedPhantom": result["summary"]["p2MissedPhantomByPlayer"],
        "p2MissedEnergy": result["summary"]["p2MissedEnergyByPlayer"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
