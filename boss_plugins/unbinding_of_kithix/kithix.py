"""Combat replay for Kith'ix / 基希克斯.

Spell IDs and add game IDs stay in this module. The replay draws the P1 and P2
mechanics described by the encounter journal onto the shared position tracks.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from analyzer_core.analysis_scope import filter_fights
from analyzer_core.combat_replay import build_replay_tracks, fetch_replay_events
from analyzer_core.config import resolve_analysis_options
from analyzer_core.event_evidence import actor_position
from analyzer_core.progress import emit_progress
from analyzer_core.wcl_api import WclClient, encounter_phase_metadata, fight_phase_start_ms
from analyzer_core.wcl_report_ids import parse_wcl_report_ids
from boss_plugins.common import (
    CLASS_COLORS,
    COMBAT_RES_SPELLS,
    build_player_mechanic_roles,
    combatant_spec_id,
    spec_class_color,
    spec_icon_slug,
    spec_localization,
    write_json_result,
)


ENCOUNTER_IDS = {3513, 53513}
CN_TZ = timezone(timedelta(hours=8))
KITHIX_NPC_GAME_ID = 267861
BOMBER_BEETLE_NPC_GAME_ID = 268194
VENOMOUS_HULK_NPC_GAME_ID = 268190
MINDSTINGER_EGG_NPC_GAME_ID = 268201

DARK_DEVASTATION = 1304930
VOIDSCAR = 1304950
VOIDSWARM = 1301511
GUT_REACTION = 1302117
DIGESTIVE_JUICES = 1302319
VOIDWEAVE = 1302333
MIND_STING = 1304040
VENOM_ROAR = 1302884
EXTINGUISH = 1304424
LIGHTS_EMBRACE = 1304526
SUFFOCATING_DARKNESS = 1302951
DARK_FRENZY = 1303260
RADIANT_BARRIER = 1302952
DIVINE_RADIANCE = 1303169
UNSPEAKABLE_HORRORS = 1304045
OVERWHELMING_FEAR = 1304046
ABYSSAL_GRASP = 1303406
NULL_GATE = 1308873
NEGATION = 1318467
EXPLOSIVE_RESTABILIZATION = 1318472
LAST_LIGHT = 1305427
RADIANT_GRACE = 1305428
ECLIPSE_FRAGMENT = 1308674
RADIANT_FADE = 1308675

EGG_HATCH_MS = 10_000
GRASP_CLEAR_MS = 8_000
DEVASTATION_RADIUS_YARDS = 15.0
ROAR_RADIUS_YARDS = 60.0
ROAR_HALF_ANGLE_DEG = 30.0
GATE_RADIUS_YARDS = 5.0
RESTABILIZE_RADIUS_YARDS = 10.0
UNITS_PER_YARD = 100.0
MAP_WIDTH = 1093
MAP_HEIGHT = 614
PLATFORM_RADIUS_YARDS = 45.0
PLATFORM_RADIUS_PX = 220.0
ICON_ROOT = "/assets/raids/venomous_abyss/icons"
MAP_IMAGE = "/assets/raids/venomous_abyss/the-unbinding-of-kith-ix.png"

APPLY_TYPES = {"applydebuff", "applybuff", "applydebuffstack", "applybuffstack"}
REMOVE_TYPES = {"removedebuff", "removebuff", "removedebuffstack", "removebuffstack"}

ADD_KINDS = {
    BOMBER_BEETLE_NPC_GAME_ID: "bomber",
    VENOMOUS_HULK_NPC_GAME_ID: "hulk",
    MINDSTINGER_EGG_NPC_GAME_ID: "egg",
}
ADD_ICONS = {
    "kithix": "kithix",
    "bomber": "bomber-beetle",
    "hulk": "venomous-hulk",
    "weaver": "voidweaver",
    "egg": "mindstinger-egg",
    "mindstinger": "mindstinger",
}

CONFIG_SCHEMA = [
    {"key": "fullReplayEnabled", "type": "boolean", "default": True, "label": "完整战斗回放", "description": "读取整场玩家与小怪的位置，用于场地回放。"},
    {"key": "phaseOneReviewEnabled", "type": "boolean", "default": True, "label": "第一阶段机制", "description": "黑暗毁灭、虫群、熄灭、窒息黑暗、蚀日碎片、恐惧与深渊攫取。"},
    {"key": "phaseTwoReviewEnabled", "type": "boolean", "default": True, "label": "第二阶段机制", "description": "虚无之门、湮消、爆炸复稳，以及玩家是否获得光耀恩典 debuff。"},
]

SPELL_NAMES = {
    DARK_DEVASTATION: "黑暗毁灭",
    VOIDSCAR: "虚空之痕",
    VOIDSWARM: "虚空虫群",
    GUT_REACTION: "肠胃反应",
    DIGESTIVE_JUICES: "腐蚀胃液",
    VOIDWEAVE: "虚空编织",
    MIND_STING: "缚脑蛰刺",
    VENOM_ROAR: "烈毒咆哮",
    EXTINGUISH: "熄灭",
    LIGHTS_EMBRACE: "圣光之拥",
    SUFFOCATING_DARKNESS: "窒息黑暗",
    DARK_FRENZY: "黑暗狂乱",
    RADIANT_BARRIER: "辉光壁垒",
    DIVINE_RADIANCE: "神圣光辉",
    UNSPEAKABLE_HORRORS: "不可名状之怖",
    OVERWHELMING_FEAR: "极度恐惧",
    ABYSSAL_GRASP: "深渊攫取",
    NULL_GATE: "虚无之门",
    NEGATION: "湮消",
    EXPLOSIVE_RESTABILIZATION: "爆炸复稳",
    LAST_LIGHT: "最后的圣光",
    RADIANT_GRACE: "光耀恩典",
    ECLIPSE_FRAGMENT: "蚀日碎片",
    RADIANT_FADE: "辉光消逝",
    3: "跌落",
}

BOSS_CONFIG = {
    "key": "kithix",
    "name": "基希克斯",
    "encounterIDs": ENCOUNTER_IDS,
    "mechanicVersion": "kithix-replay-p1-p2-2026-10-25",
    "tabs": [
        ["survival", "死亡与战复"],
        ["replay", "战斗回放"],
        ["p1", "第一阶段"],
        ["p2", "第二阶段"],
    ],
}


def ability_id(event):
    return int(event.get("abilityGameID") or event.get("killingAbilityGameID") or (event.get("ability") or {}).get("gameID") or 0)


def event_type(event):
    return str(event.get("type") or "").lower()


def fmt_ms(milliseconds):
    seconds = max(0, int(milliseconds or 0)) / 1000
    return f"{int(seconds // 60):02d}:{seconds % 60:04.1f}"


def spell_name(spell_id):
    spell_id = int(spell_id or 0)
    return SPELL_NAMES.get(spell_id, f"法术 {spell_id}" if spell_id else "未知伤害")


def actor_name(actor_map, actor_id):
    return str(actor_map.get(actor_id) or f"未知({actor_id})").split("-", 1)[0]


def rel_ms(fight, timestamp):
    return int(timestamp or 0) - int(fight["startTime"])


def player_ref(players, actor_map, actor_id):
    player = players.get(actor_id) or {}
    return {
        "playerID": actor_id,
        "player": player.get("name") or actor_name(actor_map, actor_id),
        "classColor": player.get("classColor") or "#e5e7eb",
        "icon": player.get("icon"),
        "role": player.get("role") or "unknown",
    }


def icon_for(kind):
    slug = ADD_ICONS.get(kind)
    return f"{ICON_ROOT}/{slug}.png" if slug else None


def event_point(event, side="target"):
    point = actor_position(event, side)
    if point:
        return {"x": float(point["x"]), "y": float(point["y"])}
    kind = event_type(event)
    if side == "target" and kind in {"damage", "death"} and event.get("x") is not None and event.get("y") is not None:
        return {"x": float(event["x"]), "y": float(event["y"])}
    if event.get("x") is not None and event.get("y") is not None and str(event.get("resourceActor")) in {"1", "2", "Source", "Target"}:
        return {"x": float(event["x"]), "y": float(event["y"])}
    return None


def distance_yards(left, right):
    if not left or not right:
        return None
    return math.hypot(float(left["x"]) - float(right["x"]), float(left["y"]) - float(right["y"])) / UNITS_PER_YARD


def in_frontal_cone(origin, facing_radians, point, radius_yards=ROAR_RADIUS_YARDS, half_angle_deg=ROAR_HALF_ANGLE_DEG):
    if origin is None or point is None or facing_radians is None:
        return False
    dx = float(point["x"]) - float(origin["x"])
    dy = float(point["y"]) - float(origin["y"])
    if math.hypot(dx, dy) > radius_yards * UNITS_PER_YARD:
        return False
    target_angle = math.atan2(-dy, dx)
    delta = (target_angle - facing_radians + math.pi) % (2 * math.pi) - math.pi
    return abs(delta) <= math.radians(half_angle_deg)


def _median(values):
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def build_arena(center):
    radius_units = PLATFORM_RADIUS_YARDS * UNITS_PER_YARD
    return {
        "image": MAP_IMAGE,
        "width": MAP_WIDTH,
        "height": MAP_HEIGHT,
        "centerX": None if center is None else round(center[0], 2),
        "centerY": None if center is None else round(center[1], 2),
        "radius": radius_units,
        "unitsPerYard": UNITS_PER_YARD,
        "platformRadiusYards": PLATFORM_RADIUS_YARDS,
        "plotScaleX": round(PLATFORM_RADIUS_PX / MAP_WIDTH * 100, 4),
        "plotScaleY": round(PLATFORM_RADIUS_PX / MAP_HEIGHT * 100, 4),
        "bossPortrait": f"{ICON_ROOT}/kithix.png",
        "method": "liadrin-or-kithix-median-center-45yd-platform",
    }


def classify_actor(actor):
    game_id = int(actor.get("gameID") or 0)
    name = str(actor.get("name") or "").lower()
    if game_id == KITHIX_NPC_GAME_ID or "kith'ix" in name or "kithix" in name or "基希克斯" in name:
        return "kithix"
    if game_id in ADD_KINDS:
        return ADD_KINDS[game_id]
    if "liadrin" in name or "莉亚德琳" in name:
        return "liadrin"
    if "voidweaver" in name or "虚空编织" in name:
        return "weaver"
    if "mindstinger egg" in name or "缚脑者之卵" in name or "mindstinger egg" in name:
        return "egg"
    if name.strip() in {"mindstinger", "缚脑者"} or "mindstinger" in name and "egg" not in name:
        return "mindstinger"
    if "bomber" in name or "自爆甲虫" in name:
        return "bomber"
    if "venomous hulk" in name or "烈毒巨虫" in name:
        return "hulk"
    return None


def phase_timeline(fight, casts):
    del casts
    labels = {"p1": "第一阶段", "p2": "第二阶段"}
    markers = [{"key": "p1", "label": labels["p1"], "timeMs": 0, "phaseID": 1}]
    metadata = {int(row.get("id") or 0): row for row in fight.get("wclPhaseMetadata") or []}
    seen = {0}
    for transition in fight.get("phaseTransitions") or []:
        phase_id = int(transition.get("id") or 0)
        time_ms = fight_phase_start_ms(fight, transition)
        if time_ms in seen and phase_id <= 1:
            continue
        seen.add(time_ms)
        meta = metadata.get(phase_id) or {}
        name = str(meta.get("name") or "")
        lowered = name.lower()
        key = "p1" if phase_id <= 1 or "黑暗" in name else "p2" if phase_id >= 2 or "圣光" in name or "eclipse" in lowered or "light" in lowered or "howl" in lowered else f"p{phase_id or 1}"
        markers.append({
            "key": key,
            "label": labels.get(key, f"阶段 {phase_id}"),
            "timeMs": time_ms,
            "phaseID": phase_id,
        })
    markers.sort(key=lambda row: (row["timeMs"], row["phaseID"]))
    return markers


def phase_at(markers, time_ms):
    current = "p1"
    for row in markers or []:
        if int(row.get("timeMs") or 0) <= int(time_ms):
            current = row["key"]
    return current


def completed_casts(fight, casts, spell_ids):
    spell_ids = set(spell_ids)
    pending = {}
    rows = []
    for event in sorted(casts or [], key=lambda item: int(item.get("timestamp") or 0)):
        spell_id = ability_id(event)
        if spell_id not in spell_ids:
            continue
        source = event.get("sourceID")
        kind = event_type(event)
        if kind == "begincast":
            pending[(source, int(event.get("sourceInstance") or 0), spell_id)] = event
        elif kind == "cast":
            begin = pending.pop((source, int(event.get("sourceInstance") or 0), spell_id), None)
            rows.append({
                "spellID": spell_id,
                "spellName": spell_name(spell_id),
                "sourceID": source,
                "sourceInstance": int(event.get("sourceInstance") or 0),
                "targetID": event.get("targetID"),
                "startTimeMs": rel_ms(fight, (begin or event).get("timestamp")),
                "timeMs": rel_ms(fight, event.get("timestamp")),
                "time": fmt_ms(rel_ms(fight, event.get("timestamp"))),
                "position": event_point(event, "source") or event_point(event, "target"),
                "targetPosition": event_point(event, "target"),
            })
    return rows


def aura_windows(fight, events, spell_ids):
    spell_ids = set(spell_ids)
    pending = {}
    rows = []
    ordered = sorted(events or [], key=lambda item: int(item.get("timestamp") or 0))
    for event in ordered:
        spell_id = ability_id(event)
        if spell_id not in spell_ids:
            continue
        kind = event_type(event)
        target = event.get("targetID")
        if target is None or kind not in APPLY_TYPES | REMOVE_TYPES:
            continue
        key = (target, spell_id, int(event.get("targetInstance") or 0))
        if kind in APPLY_TYPES:
            pending.setdefault(key, event)
        else:
            start = pending.pop(key, None)
            apply_ms = rel_ms(fight, (start or event).get("timestamp"))
            remove_ms = rel_ms(fight, event.get("timestamp"))
            rows.append(_aura_row(fight, start or event, event, spell_id, apply_ms, remove_ms, closed=start is not None))
    end_ms = int(fight["endTime"]) - int(fight["startTime"])
    for key, start in pending.items():
        target, spell_id, _instance = key
        apply_ms = rel_ms(fight, start.get("timestamp"))
        rows.append(_aura_row(fight, start, None, spell_id, apply_ms, end_ms, closed=False))
    rows.sort(key=lambda row: (row["applyTimeMs"], row["spellID"], row.get("playerID") or 0))
    return rows


def _aura_row(fight, start, end, spell_id, apply_ms, remove_ms, closed):
    event = start or end or {}
    return {
        "spellID": spell_id,
        "spellName": spell_name(spell_id),
        "playerID": event.get("targetID"),
        "sourceID": event.get("sourceID"),
        "instance": int(event.get("targetInstance") or 0),
        "applyTimeMs": apply_ms,
        "applyTime": fmt_ms(apply_ms),
        "removeTimeMs": remove_ms if closed else None,
        "removeTime": fmt_ms(remove_ms) if closed else None,
        "durationMs": max(0, remove_ms - apply_ms) if closed else None,
        "closed": closed,
        "position": (event_point(end, "target") if end else None) or event_point(event, "target") or event_point(event, "source"),
        "stacks": int(event.get("stack") or event.get("stacks") or 1),
        "debuff": "debuff" in event_type(event),
    }


def grasp_reviews(windows, fight_duration_ms):
    reviews = []
    for row in windows:
        if row["spellID"] != ABYSSAL_GRASP:
            continue
        duration = row["durationMs"]
        if row["closed"]:
            cleared = duration is not None and duration <= GRASP_CLEAR_MS
            missed = not cleared
        else:
            cleared = False
            missed = int(fight_duration_ms) - int(row["applyTimeMs"]) > GRASP_CLEAR_MS
        reviews.append({
            **row,
            "deadlineMs": GRASP_CLEAR_MS,
            "cleared": cleared,
            "missed": missed,
        })
    return reviews


def egg_reviews(eggs, fight_duration_ms):
    reviews = []
    for egg in eggs:
        spawn = int(egg["spawnTimeMs"])
        death = egg.get("deathTimeMs")
        elapsed = (int(death) - spawn) if death is not None else int(fight_duration_ms) - spawn
        missed = elapsed > EGG_HATCH_MS and (death is not None or int(fight_duration_ms) - spawn > EGG_HATCH_MS)
        reviews.append({
            **egg,
            "deadlineMs": spawn + EGG_HATCH_MS,
            "elapsedMs": max(0, elapsed),
            "cleared": death is not None and int(death) - spawn <= EGG_HATCH_MS,
            "missed": missed,
        })
    return reviews


def final_light_reviews(players, auras, moment_ms, dead_before):
    present = {
        row["playerID"]
        for row in auras
        if row["spellID"] == RADIANT_GRACE and row.get("debuff") and row["applyTimeMs"] >= int(moment_ms) - 2000
    }
    rows = []
    for actor_id, player in players.items():
        if actor_id in dead_before:
            continue
        grace = actor_id in present
        rows.append({
            "playerID": actor_id,
            "player": player.get("name"),
            "classColor": player.get("classColor"),
            "radiantGrace": grace,
            "complete": grace,
        })
    return rows


def cluster_points(points, radius_yards=4.0):
    clusters = []
    for point in points:
        match = next((row for row in clusters if distance_yards(row, point) is not None and distance_yards(row, point) <= radius_yards), None)
        if match is None:
            clusters.append({**point, "count": 1})
            continue
        count = match["count"] + 1
        match["x"] = (match["x"] * match["count"] + point["x"]) / count
        match["y"] = (match["y"] * match["count"] + point["y"]) / count
        match["count"] = count
        match["startTimeMs"] = min(match["startTimeMs"], point["startTimeMs"])
        match["endTimeMs"] = max(match["endTimeMs"], point["endTimeMs"])
    for row in clusters:
        row["x"] = round(row["x"], 2)
        row["y"] = round(row["y"], 2)
    return clusters


def eclipse_volleys(scars, darkness_casts, radiance_casts, fade_auras, fragment_auras, duration_ms):
    """Keep every void scar position, and fire the ones already down when darkness starts.

    Each suffocating darkness shoots from scars that appeared before it began.
    Radiant Fade inside that window means a fragment reached Liadrin. Applies
    within 1.5 seconds are one impact.
    """
    windows = []
    for cast in darkness_casts or []:
        start_ms = int(cast.get("startTimeMs") if cast.get("startTimeMs") is not None else cast.get("timeMs") or 0)
        end_ms = next((int(row["timeMs"]) for row in radiance_casts or [] if int(row.get("timeMs") or 0) >= start_ms), None)
        windows.append({**cast, "startTimeMs": start_ms, "endTimeMs": int(duration_ms) if end_ms is None else end_ms})
    assigned = []
    for index, scar in enumerate(scars or []):
        volleys = [row["startTimeMs"] for row in windows if int(scar["startTimeMs"]) < row["startTimeMs"]]
        assigned.append({
            **scar,
            "key": scar.get("key") or f"scar:{index}:{scar['startTimeMs']}",
            "volleyTimesMs": volleys,
            "endTimeMs": int(duration_ms),
        })
    reviews = []
    for window in windows:
        fired = [scar for scar in assigned if window["startTimeMs"] in scar["volleyTimesMs"]]
        fades = [
            row for row in fade_auras or []
            if window["startTimeMs"] <= int(row["applyTimeMs"]) <= window["endTimeMs"] + 500
        ]
        impacts = []
        for row in sorted(fades, key=lambda item: int(item["applyTimeMs"])):
            if impacts and int(row["applyTimeMs"]) - impacts[-1] <= 1500:
                continue
            impacts.append(int(row["applyTimeMs"]))
        soaks = [
            row for row in fragment_auras or []
            if window["startTimeMs"] <= int(row["applyTimeMs"]) <= window["endTimeMs"]
        ]
        reviews.append({
            **window,
            "scarCount": len(fired),
            "soakedCount": len({row.get("playerID") for row in soaks}),
            "fadeCount": len(impacts),
            "fadeTimesMs": impacts,
            "leaked": bool(impacts),
        })
    return assigned, reviews


FRAGMENT_CORRIDOR_YARDS = 8.0


def _position_samples(fight, events):
    samples = {}
    for event in events or []:
        stamp = rel_ms(fight, event.get("timestamp"))
        for side in ("source", "target"):
            actor_id = event.get(side + "ID")
            point = event_point(event, side)
            if actor_id is None or not point:
                continue
            samples.setdefault(actor_id, []).append((stamp, point["x"], point["y"]))
    for rows in samples.values():
        rows.sort()
    return samples


def _nearest_sample(samples, actor_id, time_ms, max_gap_ms=2000):
    rows = (samples or {}).get(actor_id)
    if not rows or time_ms is None:
        return None
    time_ms = int(time_ms)
    lo, hi = 0, len(rows)
    while lo < hi:
        mid = (lo + hi) // 2
        if rows[mid][0] < time_ms:
            lo = mid + 1
        else:
            hi = mid
    best = None
    for index in (lo - 1, lo):
        if 0 <= index < len(rows):
            gap = abs(rows[index][0] - time_ms)
            if best is None or gap < best[0]:
                best = (gap, rows[index])
    if best is None or best[0] > max_gap_ms:
        return None
    return {"x": best[1][1], "y": best[1][2]}


def collect_void_points(fight, devastations, damage, samples):
    """Each Dark Devastation leaves a void scar where that tank is standing."""
    del fight, damage
    points = []
    for cast in devastations or []:
        moment = int(cast.get("timeMs") or cast.get("startTimeMs") or 0)
        point = _nearest_sample(samples, cast.get("tankID"), moment) or cast.get("targetPosition")
        if point:
            points.append({**point, "startTimeMs": moment, "endTimeMs": moment, "tankID": cast.get("tankID"), "tank": cast.get("tank")})
    return points


def _along_scar_line(scar, liadrin, player):
    dx = float(liadrin["x"]) - float(scar["x"])
    dy = float(liadrin["y"]) - float(scar["y"])
    length = math.hypot(dx, dy)
    if length < 1:
        return None
    px = float(player["x"]) - float(scar["x"])
    py = float(player["y"]) - float(scar["y"])
    progress = (px * dx + py * dy) / (length * length)
    if progress < -0.05 or progress > 1.15:
        return None
    clamped = min(1.0, max(0.0, progress))
    offset = math.hypot(px - dx * clamped, py - dy * clamped) / UNITS_PER_YARD
    return progress, offset


def fragment_hits(fight, damage, auras, samples=None):
    """The first Eclipse Fragment hit on a player is the soak; later ticks are the DoT."""
    rows = []
    for event in damage or []:
        if ability_id(event) != ECLIPSE_FRAGMENT:
            continue
        player_id = event.get("targetID")
        if player_id is None:
            continue
        moment = rel_ms(fight, event.get("timestamp"))
        point = event_point(event, "target") or _nearest_sample(samples, player_id, moment)
        if not point:
            continue
        rows.append({"playerID": player_id, "timeMs": moment, **point, "source": "damage"})
    for aura in auras or []:
        if aura.get("spellID") != ECLIPSE_FRAGMENT or aura.get("playerID") is None:
            continue
        point = aura.get("position") or _nearest_sample(samples, aura.get("playerID"), aura.get("applyTimeMs"))
        if not point:
            continue
        rows.append({"playerID": aura["playerID"], "timeMs": int(aura["applyTimeMs"]), "x": point["x"], "y": point["y"], "source": "aura"})
    rows.sort(key=lambda row: (row["timeMs"], 0 if row["source"] == "damage" else 1))
    return rows


def fragment_paths(scars, windows, hits, liadrin, names=None):
    """Fit each soaked fragment from the scar whose line to Liadrin passes the hit."""
    if not liadrin:
        return []
    names = names or {}
    paths = []
    for window in windows or []:
        pool = {}
        for hit in hits or []:
            if not (window["startTimeMs"] <= int(hit["timeMs"]) <= window["endTimeMs"] + 500):
                continue
            previous = pool.get(hit["playerID"])
            if previous is None:
                pool[hit["playerID"]] = hit
                continue
            if previous["source"] == "damage" and hit["source"] != "damage":
                continue
            if hit["source"] == "damage" and previous["source"] != "damage":
                pool[hit["playerID"]] = hit
                continue
            if int(hit["timeMs"]) < int(previous["timeMs"]):
                pool[hit["playerID"]] = hit
        firing = [scar for scar in scars or [] if window["startTimeMs"] in (scar.get("volleyTimesMs") or [])]
        candidates = []
        for hit in pool.values():
            for scar in firing:
                scored = _along_scar_line(scar, liadrin, hit)
                if scored is None or scored[1] > FRAGMENT_CORRIDOR_YARDS:
                    continue
                candidates.append((scored[1], scored[0], int(hit["timeMs"]), hit, scar))
        candidates.sort(key=lambda row: (row[0], row[2], row[1]))
        used_scars, used_players = set(), set()
        for offset, progress, _time_ms, hit, scar in candidates:
            if scar["key"] in used_scars or hit["playerID"] in used_players:
                continue
            used_scars.add(scar["key"])
            used_players.add(hit["playerID"])
            paths.append({
                "key": f"{scar['key']}:{hit['playerID']}:{hit['timeMs']}",
                "playerID": hit["playerID"],
                "player": names.get(hit["playerID"]),
                "timeMs": int(hit["timeMs"]),
                "launchTimeMs": int(window.get("timeMs") or window["startTimeMs"]),
                "darknessTimeMs": window["startTimeMs"],
                "scarKey": scar["key"],
                "scar": {"x": scar["x"], "y": scar["y"]},
                "soak": {"x": round(float(hit["x"]), 2), "y": round(float(hit["y"]), 2)},
                "liadrin": {"x": round(float(liadrin["x"]), 2), "y": round(float(liadrin["y"]), 2)},
                "offsetYards": round(offset, 2),
                "progress": round(progress, 3),
            })
    paths.sort(key=lambda row: (row["timeMs"], row["playerID"]))
    return paths


def _collect_samples(events, wanted_ids):
    samples = {actor_id: [] for actor_id in wanted_ids}
    for event in events or []:
        for side in ("source", "target"):
            actor_id = event.get(side + "ID")
            if actor_id not in samples:
                continue
            point = event_point(event, side)
            if point:
                samples[actor_id].append((int(event.get("timestamp") or 0), point["x"], point["y"]))
    return samples


def arena_center(actor_rows, events):
    classified = {int(row["id"]): classify_actor(row) for row in actor_rows or [] if row.get("id") is not None}
    liadrin = {actor_id for actor_id, kind in classified.items() if kind == "liadrin"}
    bosses = {actor_id for actor_id, kind in classified.items() if kind == "kithix"}
    samples = _collect_samples(events, liadrin or bosses)
    chosen = next((rows for rows in samples.values() if rows), None)
    if not chosen:
        return None
    return (_median([row[1] for row in chosen]), _median([row[2] for row in chosen]))


def _actors_with_cast_kinds(actor_rows, casts):
    """Name a caster from the spell when the NPC id is not in the actor table."""
    rows = list(actor_rows or [])
    known = {int(row["id"]) for row in rows if row.get("id") is not None and classify_actor(row)}
    inferred = {}
    labels = {VENOM_ROAR: ("hulk", "Venomous Hulk", VENOMOUS_HULK_NPC_GAME_ID), VOIDWEAVE: ("weaver", "Voidweaver", 0), GUT_REACTION: ("bomber", "Bomber Beetle", BOMBER_BEETLE_NPC_GAME_ID), MIND_STING: ("mindstinger", "Mindstinger", 0)}
    for event in casts or []:
        source = event.get("sourceID")
        if source is None or source in known or source in inferred:
            continue
        label = labels.get(ability_id(event))
        if label:
            inferred[source] = label
    for actor_id, (_kind, name, game_id) in inferred.items():
        rows.append({"id": actor_id, "name": name, "gameID": game_id})
    return rows


def _event_instance(event, side):
    return int(event.get(side + "Instance") or event.get(side + "InstanceID") or 0)


def _is_killing_event(event):
    if event_type(event) == "death":
        return True
    overkill = event.get("overkill")
    hit_points = event.get("hitPoints")
    return overkill is not None and int(overkill) >= 0 and hit_points == 0


def _assign_death_times(position_instances, kills, first_seen, actor_id):
    """Match a death to the position track even when WCL instances disagree."""
    assigned = {}
    used = set()
    for index, (instance, timestamp) in enumerate(kills):
        if instance not in position_instances:
            continue
        if instance not in assigned or timestamp < assigned[instance]:
            assigned[instance] = timestamp
            used.add(index)
    unused = [kills[index] for index in range(len(kills)) if index not in used]
    open_positions = [instance for instance in position_instances if instance not in assigned]
    zero_deaths = [timestamp for instance, timestamp in unused if instance == 0]
    if len(open_positions) == 1 and len(zero_deaths) == 1:
        assigned[open_positions[0]] = zero_deaths[0]
        unused = [row for row in unused if row[0] != 0]
        open_positions = []
    if open_positions and len(open_positions) == len(unused):
        ordered_positions = sorted(open_positions, key=lambda instance: first_seen.get((actor_id, instance), 0))
        ordered_kills = sorted(unused, key=lambda row: row[1])
        for instance, (_kill_instance, timestamp) in zip(ordered_positions, ordered_kills):
            spawn = first_seen.get((actor_id, instance), timestamp)
            if timestamp + 500 >= spawn:
                assigned[instance] = timestamp
    return assigned


def _actor_lifetimes(fight, actor_rows, events, deaths):
    classified = []
    by_id = {}
    for row in actor_rows or []:
        kind = classify_actor(row)
        if not kind:
            continue
        actor_id = int(row["id"])
        by_id[actor_id] = kind
        classified.append(row)
    first = {}
    for event in events or []:
        for side in ("source", "target"):
            actor_id = event.get(side + "ID")
            if actor_id not in by_id:
                continue
            if event_point(event, side) is None and side == "target" and _is_killing_event(event):
                continue
            instance = _event_instance(event, side)
            key = (actor_id, instance)
            timestamp = int(event.get("timestamp") or 0)
            first[key] = min(first.get(key, timestamp), timestamp)
    kills_by_actor = {}
    seen_kills = set()
    for event in list(deaths or []) + list(events or []):
        if not _is_killing_event(event):
            continue
        actor_id = event.get("targetID")
        if actor_id not in by_id:
            continue
        timestamp = int(event.get("timestamp") or 0)
        instance = _event_instance(event, "target")
        signature = (actor_id, instance, timestamp)
        if signature in seen_kills:
            continue
        seen_kills.add(signature)
        kills_by_actor.setdefault(actor_id, []).append((instance, timestamp))
    death_at = {}
    for actor_id, kills in kills_by_actor.items():
        position_instances = {instance for (row_actor, instance) in first if row_actor == actor_id}
        if not position_instances:
            position_instances = {instance for instance, _timestamp in kills} or {0}
        for instance, timestamp in _assign_death_times(position_instances, kills, first, actor_id).items():
            death_at[(actor_id, instance)] = timestamp
    rows = []
    seen = set(first) | set(death_at)
    for actor_id, instance in seen:
        kind = by_id.get(actor_id)
        if not kind or kind == "kithix":
            continue
        spawn = first.get((actor_id, instance))
        death = death_at.get((actor_id, instance))
        if spawn is None and death is None:
            continue
        spawn = spawn if spawn is not None else death
        rows.append({
            "actorID": actor_id,
            "instance": instance,
            "key": f"{actor_id}:{instance}",
            "kind": kind,
            "name": next((row.get("name") for row in classified if int(row["id"]) == actor_id), None) or actor_name({}, actor_id),
            "gameID": next((int(row.get("gameID") or 0) for row in classified if int(row["id"]) == actor_id), 0),
            "icon": icon_for(kind),
            "spawnTimeMs": rel_ms(fight, spawn),
            "deathTimeMs": None if death is None else rel_ms(fight, death),
        })
    rows.sort(key=lambda row: (row["spawnTimeMs"], row["kind"], row["actorID"], row["instance"]))
    return rows


def _clear_gates(gates, blasts):
    for blast in blasts:
        for gate in gates:
            if gate.get("clearedTimeMs") is not None or gate["dropTimeMs"] > blast["timeMs"]:
                continue
            gap = distance_yards(gate.get("position"), blast.get("position"))
            if gap is not None and gap <= RESTABILIZE_RADIUS_YARDS:
                gate["clearedTimeMs"] = blast["timeMs"]
                gate["clearedBy"] = blast.get("sourceID")


def analyze_kithix(fight, actor_map, players, raw, actor_rows):
    options = resolve_analysis_options(CONFIG_SCHEMA, raw.get("analysisOptions") or {})
    start = int(fight["startTime"])
    duration_ms = int(fight["endTime"]) - start
    casts = list(raw.get("casts") or [])
    auras = aura_windows(fight, list(raw.get("debuffs") or []) + list(raw.get("buffs") or []) + list(raw.get("enemyBuffs") or []), {
        LIGHTS_EMBRACE, DARK_FRENZY, RADIANT_BARRIER, UNSPEAKABLE_HORRORS, OVERWHELMING_FEAR,
        ABYSSAL_GRASP, NULL_GATE, NEGATION, RADIANT_GRACE, ECLIPSE_FRAGMENT, RADIANT_FADE,
    })
    markers = phase_timeline(fight, casts)
    center = arena_center(actor_rows, list(raw.get("replayEvents") or []) + casts + list(raw.get("damage") or []))
    adds = _actor_lifetimes(fight, _actors_with_cast_kinds(actor_rows, casts), list(raw.get("replayEvents") or []) + casts + list(raw.get("damage") or []) + list(raw.get("debuffs") or []), raw.get("deaths") or [])
    for row in auras:
        row["player"] = actor_name(actor_map, row["playerID"])
        if row["playerID"] in players:
            row.update(player_ref(players, actor_map, row["playerID"]))
        row["phase"] = phase_at(markers, row["applyTimeMs"])
    devastations = []
    if options["phaseOneReviewEnabled"]:
        for cast in completed_casts(fight, casts, {DARK_DEVASTATION}):
            devastations.append({
                **cast,
                "phase": phase_at(markers, cast["timeMs"]),
                "radiusYards": DEVASTATION_RADIUS_YARDS,
                "tankID": cast.get("targetID"),
                "tank": actor_name(actor_map, cast.get("targetID")),
            })
    samples = _position_samples(fight, list(raw.get("replayEvents") or []) + casts + list(raw.get("damage") or []) + list(raw.get("debuffs") or []))
    void_points = collect_void_points(fight, devastations, raw.get("damage"), samples)
    voidscars = []
    for row in cluster_points(void_points):
        row["phase"] = phase_at(markers, row["startTimeMs"])
        voidscars.append(row)
    darkness_casts = completed_casts(fight, casts, {SUFFOCATING_DARKNESS}) if options["phaseOneReviewEnabled"] else []
    radiance_casts = completed_casts(fight, casts, {DIVINE_RADIANCE}) if options["phaseOneReviewEnabled"] else []
    voidscars, darkness = eclipse_volleys(
        voidscars,
        darkness_casts,
        radiance_casts,
        [row for row in auras if row["spellID"] == RADIANT_FADE],
        [row for row in auras if row["spellID"] == ECLIPSE_FRAGMENT],
        duration_ms,
    )
    liadrin = None if center is None else {"x": center[0], "y": center[1]}
    paths = fragment_paths(voidscars, darkness, fragment_hits(fight, raw.get("damage"), auras, samples), liadrin, actor_map)
    eggs = egg_reviews([row for row in adds if row["kind"] == "egg"], duration_ms) if options["phaseOneReviewEnabled"] else []
    roars = []
    weaves = []
    if options["phaseOneReviewEnabled"]:
        roars = [{**cast, "radiusYards": ROAR_RADIUS_YARDS, "halfAngleDeg": ROAR_HALF_ANGLE_DEG, "phase": phase_at(markers, cast["timeMs"])} for cast in completed_casts(fight, casts, {VENOM_ROAR})]
        weaves = [{**cast, "phase": phase_at(markers, cast["timeMs"]), "target": actor_name(actor_map, cast.get("targetID"))} for cast in completed_casts(fight, casts, {VOIDWEAVE})]
    explosions = completed_casts(fight, casts, {GUT_REACTION}) if options["phaseOneReviewEnabled"] else []
    beetles = [row for row in adds if row["kind"] == "bomber"]
    for beetle in beetles:
        blast = next((cast for cast in explosions if cast["sourceID"] == beetle["actorID"] and beetle["spawnTimeMs"] <= cast["timeMs"] <= (beetle["deathTimeMs"] or duration_ms) + 500), None)
        beetle["explodeTimeMs"] = blast["timeMs"] if blast else beetle.get("deathTimeMs")
        beetle["chaseTargetID"] = blast.get("targetID") if blast else None
    grasps = grasp_reviews(auras, duration_ms) if options["phaseOneReviewEnabled"] else []
    gates = []
    negations = []
    blasts = []
    if options["phaseTwoReviewEnabled"]:
        for row in auras:
            if row["spellID"] != NULL_GATE:
                continue
            drop = row["removeTimeMs"] if row["removeTimeMs"] is not None else row["applyTimeMs"] + 5000
            gates.append({**row, "dropTimeMs": drop, "radiusYards": GATE_RADIUS_YARDS, "clearedTimeMs": None})
        blasts = [{**cast, "radiusYards": RESTABILIZE_RADIUS_YARDS, "position": cast.get("targetPosition") or cast.get("position")} for cast in completed_casts(fight, casts, {EXPLOSIVE_RESTABILIZATION})]
        _clear_gates(gates, blasts)
        for row in auras:
            if row["spellID"] != NEGATION:
                continue
            resolved = any(row["playerID"] == blast.get("sourceID") and row["applyTimeMs"] <= blast["timeMs"] <= (row["removeTimeMs"] or duration_ms) + 800 for blast in blasts)
            negations.append({**row, "restabilized": resolved, "missed": not resolved and row["closed"]})
    dead_before = set()
    light_moment = next((row["timeMs"] for row in completed_casts(fight, casts, {LAST_LIGHT})), next((row["timeMs"] for row in markers if row["key"] == "p2"), None))
    if light_moment is not None:
        for event in raw.get("deaths") or []:
            if event.get("targetID") in players and rel_ms(fight, event.get("timestamp")) <= light_moment:
                dead_before.add(event.get("targetID"))
    lights = final_light_reviews(players, auras, light_moment, dead_before) if options["phaseTwoReviewEnabled"] and light_moment is not None else []
    frenzy = [row for row in auras if row["spellID"] == DARK_FRENZY]
    return {
        "phaseTimeline": markers,
        "arena": build_arena(center),
        "adds": adds,
        "eggs": eggs,
        "devastations": devastations,
        "voidscars": voidscars,
        "roars": roars,
        "weaves": weaves,
        "beetles": beetles,
        "explosions": explosions,
        "extinguishes": completed_casts(fight, casts, {EXTINGUISH}) if options["phaseOneReviewEnabled"] else [],
        "embraces": [row for row in auras if row["spellID"] == LIGHTS_EMBRACE],
        "darkness": darkness,
        "fragments": [row for row in auras if row["spellID"] == ECLIPSE_FRAGMENT],
        "fragmentPaths": paths,
        "frenzies": frenzy,
        "barriers": [row for row in auras if row["spellID"] == RADIANT_BARRIER] or completed_casts(fight, casts, {RADIANT_BARRIER}),
        "radiances": radiance_casts,
        "horrors": [row for row in auras if row["spellID"] in {UNSPEAKABLE_HORRORS, OVERWHELMING_FEAR}],
        "grasps": grasps,
        "swarms": completed_casts(fight, casts, {VOIDSWARM}),
        "gates": gates,
        "negations": negations,
        "restabilizations": blasts,
        "finalLights": lights,
        "checks": {
            "eggsMissed": sum(1 for row in eggs if row["missed"]),
            "graspsMissed": sum(1 for row in grasps if row["missed"]),
            "fragmentLeaks": sum(row["fadeCount"] for row in darkness),
            "frenziedAdds": len({(row.get("playerID"), row.get("instance")) for row in frenzy}),
            "negationsUnresolved": sum(1 for row in negations if row["missed"]),
            "finalLightMissing": sum(1 for row in lights if not row["complete"]),
        },
        "evidenceNote": (
            "阶段来自 WCL 的阶段切换，回放左上角固定显示第一阶段、第二阶段。"
            "缚脑者之卵需在出现后 10 秒内死亡。深渊攫取需在 8 秒内移除。"
            "黑暗毁灭按坦克周围 15 码绘制，烈毒咆哮按施法者朝向前方 60 度、60 码绘制。"
            "窒息黑暗开始前已经留下的虚空之痕会朝莉亚德琳射出蚀日碎片。玩家第一次受到蚀日碎片伤害的位置若落在某条痕迹射向莉亚德琳的 8 码走廊内，就把这一发的飞行路径按该伤害时间拟合。"
            "辉光消逝表示有碎片碰到了她。"
            "爆炸复稳以 10 码清除仍在场上的虚无之门。光耀恩典只核对仍存活玩家身上的 debuff。"
            "场地中心优先取莉亚德琳，否则取基希克斯的坐标中位数；可见石台按半径 45 码贴合地图。"
        ),
    }


def build_players(actors, combatants):
    actor_map = {int(actor["id"]): actor.get("name") or f"Actor {actor['id']}" for actor in actors}
    actor_type = {int(actor["id"]): actor.get("type") for actor in actors}
    info = {event.get("sourceID") or event.get("targetID"): event for event in combatants}
    roles = build_player_mechanic_roles(combatants)
    players = {}
    for actor_id, actor_kind in actor_type.items():
        if actor_kind != "Player" or actor_id not in info:
            continue
        spec_id = combatant_spec_id(info.get(actor_id) or {})
        players[actor_id] = {
            "id": actor_id,
            "name": actor_name(actor_map, actor_id),
            "specID": spec_id,
            "role": roles.get(actor_id, "unknown"),
            "icon": spec_icon_slug(spec_id),
            "classColor": spec_class_color(spec_id) or CLASS_COLORS.get(str(actor_kind).lower()) or "#e5e7eb",
            "localization": spec_localization(spec_id),
        }
    return actor_map, players


def survival_timeline(fight, actor_map, players, deaths, friendly_casts):
    timeline = []
    alive = set(players)
    for event in deaths:
        target_id = event.get("targetID")
        if target_id not in players:
            continue
        timestamp = int(event.get("timestamp") or 0)
        spell_id = ability_id(event)
        timeline.append({
            **player_ref(players, actor_map, target_id),
            "kind": "death",
            "absoluteTime": timestamp,
            "timeMs": timestamp - int(fight["startTime"]),
            "time": fmt_ms(timestamp - int(fight["startTime"])),
            "abilityID": spell_id,
            "ability": spell_name(spell_id),
        })
    seen = set()
    for event in friendly_casts:
        spell_id = ability_id(event)
        target_id = event.get("targetID")
        if spell_id not in COMBAT_RES_SPELLS or target_id not in players or event_type(event) not in {"cast", "applybuff"}:
            continue
        timestamp = int(event.get("timestamp") or 0)
        identity = (timestamp // 1500, event.get("sourceID"), target_id, spell_id)
        if identity in seen:
            continue
        seen.add(identity)
        timeline.append({
            **player_ref(players, actor_map, target_id),
            "kind": "combat_res",
            "absoluteTime": timestamp,
            "timeMs": timestamp - int(fight["startTime"]),
            "time": fmt_ms(timestamp - int(fight["startTime"])),
            "source": actor_name(actor_map, event.get("sourceID")),
            "abilityID": spell_id,
            "ability": COMBAT_RES_SPELLS[spell_id],
        })
    timeline.sort(key=lambda row: (row["absoluteTime"], 0 if row["kind"] == "death" else 1))
    for row in timeline:
        if row["kind"] == "death":
            alive.discard(row["playerID"])
        else:
            alive.add(row["playerID"])
    return {
        "rosterCount": len(players),
        "survivorCount": len(alive),
        "deathCount": sum(row["kind"] == "death" for row in timeline),
        "combatResCount": sum(row["kind"] == "combat_res" for row in timeline),
        "survivors": [players[player_id] for player_id in players if player_id in alive],
        "timeline": timeline,
    }


def _id_filter(spell_ids):
    return "ability.id in (" + ", ".join(str(value) for value in sorted(spell_ids)) + ")"


def fetch_payload(client, report_id, fight, options=None):
    options = resolve_analysis_options(CONFIG_SCHEMA, options or {})
    cast_ids = {
        DARK_DEVASTATION, VOIDSWARM, GUT_REACTION, VOIDWEAVE, MIND_STING, VENOM_ROAR, EXTINGUISH,
        SUFFOCATING_DARKNESS, RADIANT_BARRIER, DIVINE_RADIANCE, NULL_GATE, NEGATION,
        EXPLOSIVE_RESTABILIZATION, LAST_LIGHT, RADIANT_GRACE,
    }
    aura_ids = {
        LIGHTS_EMBRACE, DARK_FRENZY, RADIANT_BARRIER, UNSPEAKABLE_HORRORS, OVERWHELMING_FEAR,
        ABYSSAL_GRASP, NULL_GATE, NEGATION, RADIANT_GRACE, ECLIPSE_FRAGMENT, RADIANT_FADE,
    }
    damage_ids = {DARK_DEVASTATION, VOIDSCAR, GUT_REACTION, DIGESTIVE_JUICES, VOIDWEAVE, MIND_STING, VENOM_ROAR, EXTINGUISH, EXPLOSIVE_RESTABILIZATION, ECLIPSE_FRAGMENT}

    def fetch(stream, spell_ids, **kwargs):
        if not spell_ids:
            return []
        return client.events(report_id, stream, fight, filter_expression=_id_filter(spell_ids), **kwargs)

    return {
        "casts": fetch("Casts", cast_ids, hostility_type="Enemies", include_resources=True),
        "friendlyCasts": client.events(report_id, "Casts", fight, hostility_type="Friendlies"),
        "damage": fetch("DamageTaken", damage_ids, include_resources=True),
        "debuffs": fetch("Debuffs", aura_ids, include_resources=True),
        "buffs": fetch("Buffs", aura_ids, hostility_type="Friendlies", include_resources=True),
        "enemyBuffs": fetch("Buffs", {DARK_FRENZY, RADIANT_BARRIER}, hostility_type="Enemies", include_resources=True),
        "deaths": client.events(report_id, "Deaths", fight),
        "combatants": client.events(report_id, "CombatantInfo", fight),
        "replayEvents": fetch_replay_events(client, report_id, fight, include_metadata=True) if options["fullReplayEnabled"] else [],
        "analysisOptions": options,
    }


def _stamp_add_deaths(replay, adds):
    """Copy a matched add death onto the position track the map actually draws."""
    units = (replay or {}).get("units") or []
    by_actor = {}
    for unit in units:
        by_actor.setdefault(unit.get("actorID"), []).append(unit)
    for add in adds or []:
        death = add.get("deathTimeMs")
        if death is None:
            continue
        matches = [unit for unit in by_actor.get(add.get("actorID"), []) if unit.get("instance") == add.get("instance")]
        if not matches and len(by_actor.get(add.get("actorID"), [])) == 1:
            matches = by_actor[add["actorID"]]
        for unit in matches:
            states = unit.setdefault("states", [])
            if not any(len(row) >= 2 and row[0] == death and row[1] == "dead" for row in states):
                states.append([death, "dead"])
            states.sort(key=lambda row: (row[0], row[1]))


def render_fight(report_id, report_start, actors, fight, raw):
    actor_map, players = build_players(actors, raw.get("combatants") or [])
    player_deaths = [event for event in raw.get("deaths") or [] if event.get("targetID") in players]
    survival = survival_timeline(fight, actor_map, players, player_deaths, raw.get("friendlyCasts") or [])
    mechanics = analyze_kithix(fight, actor_map, players, raw, actors)
    if raw.get("replayEvents"):
        mechanics["combatReplay"] = build_replay_tracks(
            fight, players, actor_map, raw["replayEvents"], actor_rows=actors,
            spell_names=SPELL_NAMES, deaths=player_deaths, survival_timeline=survival["timeline"], include_facing=True,
        )
        _stamp_add_deaths(mechanics["combatReplay"], mechanics.get("adds"))
    duration_ms = int(fight["endTime"]) - int(fight["startTime"])
    started = datetime.fromtimestamp((int(report_start) + int(fight["startTime"])) / 1000, tz=CN_TZ)
    difficulty = int(fight.get("difficulty") or 0)
    difficulty_names = {1: "随机团队", 2: "弹性", 3: "普通", 4: "英雄", 5: "史诗"}
    return {
        "reportID": report_id,
        "fightID": int(fight["id"]),
        "fightName": fight.get("name") or BOSS_CONFIG["name"],
        "date": started.strftime("%Y-%m-%d"),
        "startClock": started.strftime("%H:%M:%S"),
        "startTimeIso": started.isoformat(),
        "isKill": bool(fight.get("kill")),
        "kill": bool(fight.get("kill")),
        "bossPercentage": float(fight.get("bossPercentage") or 0),
        "fightPercentage": fight.get("fightPercentage"),
        "durationMs": duration_ms,
        "duration": fmt_ms(duration_ms),
        "difficulty": difficulty,
        "difficultyKey": {5: "mythic", 4: "heroic", 3: "normal"}.get(difficulty, "unknown"),
        "difficultyName": difficulty_names.get(difficulty, f"未知难度 {difficulty}"),
        "wipeReason": "已击杀" if fight.get("kill") else "结合死亡时间线与两阶段机制复盘",
        "wclDeepLink": f"https://www.warcraftlogs.com/reports/{report_id}#fight={fight['id']}&type=summary",
        "players": list(players.values()),
        "survival": survival,
        "deathTimeline": survival["timeline"],
        BOSS_CONFIG["key"]: mechanics,
    }


def build_aggregated_json(report_ids, options=None, client=None):
    options = resolve_analysis_options(CONFIG_SCHEMA, options or {})
    report_id_list = parse_wcl_report_ids(report_ids)
    if not report_id_list:
        raise RuntimeError("请传入至少一个 WCL report ID。")
    client = client or WclClient()
    rendered = []
    emit_progress("读取基希克斯 Pull 列表", percent=8, stage="analyze")
    for report_id in report_id_list:
        report = client.report_fights(report_id)
        phase_metadata = encounter_phase_metadata(report, ENCOUNTER_IDS)
        fights = filter_fights(report_id, [
            {**fight, "wclPhaseMetadata": phase_metadata}
            for fight in report.get("fights") or []
            if int(fight.get("encounterID") or 0) in ENCOUNTER_IDS
            and int(fight.get("endTime") or 0) - int(fight.get("startTime") or 0) >= 20_000
        ])
        actors = client.actors(report_id)
        emit_progress(f"{report_id}：匹配 {len(fights)} 场", percent=12, stage="analyze")
        for index, fight in enumerate(fights, start=1):
            emit_progress(f"读取 Fight {fight['id']}（{index}/{len(fights)}）", stage="analyze")
            rendered.append(render_fight(report_id, report["startTime"], actors, fight, fetch_payload(client, report_id, fight, options)))
    rendered.sort(key=lambda row: (row["startTimeIso"], row["reportID"], row["fightID"]), reverse=True)
    return {
        "code": 200,
        "meta": {
            "version": "12.1",
            "raidKey": "unbinding_of_kithix",
            "raidName": "基希克斯破封",
            "bossKey": BOSS_CONFIG["key"],
            "bossName": BOSS_CONFIG["name"],
            "analyzedReports": report_id_list,
            "mechanicVersion": BOSS_CONFIG["mechanicVersion"],
            "tabDefinitions": [{"key": key, "label": label} for key, label in BOSS_CONFIG["tabs"]],
            "analysisConfig": options,
            "arenaImage": "assets/raids/venomous_abyss/the-unbinding-of-kith-ix.png",
            "features": {"survival": True, "fieldReplay": True},
        },
        "data": {"page1_wipeAnalysis": rendered, "page2_avoidableBoard": {"avoidable": []}},
    }


def analyze(report_ids, output_path=None, catalog_entry=None, options=None, progress_callback=None):
    del progress_callback
    return write_json_result(build_aggregated_json(report_ids, options), output_path, catalog_entry=catalog_entry)
