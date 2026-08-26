"""Evidence-first shared engine for Venomous Abyss encounters 3-6."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from analyzer_core.analysis_scope import filter_fights
from analyzer_core.concurrency import run_parallel_indexed
from analyzer_core.progress import emit_progress
from analyzer_core.wcl_api import WclClient
from boss_plugins.common import write_json_result
from boss_plugins.venomous_abyss.shared import (
    IMMUNITY_SPELLS,
    ability_id,
    active_immunities,
    actor_name,
    arena_estimate_with_boss,
    build_player_catalog,
    build_position_index,
    build_survival_timeline,
    compact_actor_position_events,
    difficulty_fields,
    event_amount,
    event_type,
    fmt_ms,
    group_nearby,
    load_confirmed_source_names,
    load_confirmed_spell_names,
    movement,
    player_ref,
    position_at,
    position_at_interpolated,
    resolve_boss_actor_id,
    source_name,
    spell_name,
)


CN_TZ = timezone(timedelta(hours=8))
GUIDE_SPELLS = load_confirmed_spell_names()
SOURCE_NAMES = load_confirmed_source_names()

PREDATOR_CASTS = {1277002, 1277027, 1287072}
PREDATOR_DAMAGE = {
    1277002: {1277101},
    1277027: {1277031, 1285999},
    1287072: {1287083},
}
PREDATOR_LABELS = {1277002: "劫掠", 1277027: "毁伤", 1287072: "风暴"}
CYST_PLACEMENT_DEBUFF_ID = 1305963
CYST_TRIGGER_DEBUFF_ID = 1287205
CYST_VOLLEY_CAST_ID = 1305959
SSZORAK_GAME_ID = 257347
DIG_DURATION_MS = 25_000
REPLAY_STEP_MS = 200
POSITION_RELIABLE_MS = 2_000
KNOCKBACK_DISPLACEMENT = 350
CROSSWIND_CIRCLE_YARDS = 6
# WCL 世界标记：骷髅约 1 点、红叉约 6 点；风沿 skull↔cross 对角线（与左上→右下 45° 轴一致）
SKULL_MARKER_DEG = 60.0
CROSS_MARKER_DEG = -90.0
ASSET_MAP_ROTATION_DEG = -45.0


def _marker_vector(angle_deg):
    rad = math.radians(angle_deg)
    return math.cos(rad), math.sin(rad)


def _bearing_deg(dx, dy):
    return (math.degrees(math.atan2(-dy, dx)) + 360) % 360


def _skull_to_cross_bearing():
    sx, sy = _marker_vector(SKULL_MARKER_DEG)
    cx, cy = _marker_vector(CROSS_MARKER_DEG)
    return _bearing_deg(cx - sx, cy - sy)


_WIND_SKULL_TO_CROSS = _skull_to_cross_bearing()
_WIND_CROSS_TO_SKULL = (_WIND_SKULL_TO_CROSS + 180) % 360


def _asset_angle(wcl_angle):
    return (wcl_angle + ASSET_MAP_ROTATION_DEG) % 360


CROSSWIND_DIRECTIONS = {
    1285425: {
        "key": "A", "label": "骷髅 → 红叉",
        "angleDegrees": _asset_angle(_WIND_SKULL_TO_CROSS),
        "wclAngleDegrees": _WIND_SKULL_TO_CROSS,
    },
    1285453: {
        "key": "B", "label": "红叉 → 骷髅",
        "angleDegrees": _asset_angle(_WIND_CROSS_TO_SKULL),
        "wclAngleDegrees": _WIND_CROSS_TO_SKULL,
    },
}


def _wind_side_from_position(x, y, arena):
    if not arena:
        return None
    angle = _bearing_deg(x - arena["centerX"], y - arena["centerY"])
    delta_a = min((angle - _WIND_SKULL_TO_CROSS) % 360, (_WIND_SKULL_TO_CROSS - angle) % 360)
    delta_b = min((angle - _WIND_CROSS_TO_SKULL) % 360, (_WIND_CROSS_TO_SKULL - angle) % 360)
    return "A" if delta_a <= delta_b else "B"
VENOM_GAIN_DAMAGE = {
    1289201: "腐蚀液滴",
    1291404: "剧毒涌现",
    1308122: "剧毒涌现",
    1291478: "腐蚀唾液",
    1293295: "腐蚀唾液",
    1293979: "腐蚀唾液",
}
VENOM_ABNORMAL_DAMAGE = {
    1290338: "腐蚀液滴爆裂",
    1292806: "搅动深渊",
    1292807: "搅动深渊",
    1293749: "邪恶洪流",
    1294293: "邪恶洪流",
}
FEAST_IDS = {1290516, 1290654, 1290662, 1310211}

BOSSES = {
    "lostexplorers": {
        "encounterIDs": {3497},
        "name": "迷失的探险者",
        "arena": "assets/raids/venomous_abyss/04-lostexplorers.jpg",
        "spellNames": GUIDE_SPELLS,
        "tabs": [
            ["survival", "全场存活情况"], ["defense", "联合防御"],
            ["avoidable", "可规避机制"], ["special", "特殊技能处理"],
        ],
    },
    "vashnik": {
        "encounterIDs": {3455},
        "name": "万毒邪祟者瓦什尼克",
        "arena": "assets/raids/venomous_abyss/03-vashnik.png",
        "spellNames": GUIDE_SPELLS,
        "tabs": [
            ["survival", "全场存活情况"], ["avoidable", "可规避机制"],
            ["infection", "适应性感染"],
        ],
    },
    "sszorak": {
        "encounterIDs": {3420},
        "name": "斯索拉克",
        "arena": "assets/raids/venomous_abyss/05-sszorak.jpg",
        "spellNames": GUIDE_SPELLS,
        "tabs": [
            ["survival", "全场存活情况"], ["predator", "顶级掠食者"],
            ["replay", "场地推演"], ["cysts", "腐蚀囊肿"], ["crosswinds", "狂怒侧风"],
        ],
    },
    "twinfangs": {
        "encounterIDs": {3421},
        "name": "双子毒牙",
        "arena": "assets/raids/venomous_abyss/06-twinfangs.jpg",
        "spellNames": GUIDE_SPELLS,
        "tabs": [
            ["survival", "全场存活情况"], ["venom", "永恒毒液"],
            ["globules", "地板炸圈"], ["mythic", "史诗难度占位"],
        ],
    },
}


def progress(boss_key, message, percent=None):
    print(f"[{boss_key}] {message}", flush=True)
    emit_progress(message, percent=percent, stage="analyze")


def _events_between(events, start, end, spell_ids=None, types=None):
    spell_ids = set(spell_ids or [])
    types = set(types or [])
    return [event for event in events
            if start <= int(event.get("timestamp") or 0) < end
            and (not spell_ids or int(ability_id(event) or 0) in spell_ids)
            and (not types or event_type(event) in types)]


def _avoidable_board(fight, actor_map, players, damage, deaths, labels):
    deaths_by = {(event.get("targetID"), int(event.get("killingAbilityGameID") or 0)) for event in deaths}
    board = []
    for spell_id, spell_name in labels.items():
        grouped = defaultdict(list)
        for event in damage:
            if int(ability_id(event) or 0) == spell_id and event.get("targetID") in players:
                grouped[event.get("targetID")].append(event)
        for player_id, events in grouped.items():
            ref = player_ref(players, actor_map, player_id)
            board.append({
                **ref, "spellID": spell_id, "spellName": spell_name, "hitCount": len(events),
                "totalDamage": sum(event_amount(event) for event in events),
                "maxHit": max((event_amount(event) for event in events), default=0),
                "deathCount": int((player_id, spell_id) in deaths_by),
                "events": [{"timeMs": int(event["timestamp"] - fight["startTime"]), "time": fmt_ms(event["timestamp"] - fight["startTime"]), "amount": event_amount(event)} for event in events],
            })
    return sorted(board, key=lambda row: (row["deathCount"], row["totalDamage"], row["hitCount"]), reverse=True)


def _completed_casts(casts, spell_id):
    return [event for event in casts if int(ability_id(event) or 0) == spell_id and event_type(event) == "cast"]


def _frostfire_resolution(start, end, player_id, color, debuffs, friendly_buffs):
    debuff_id = 1295928 if color == "fire" else 1295954
    opposite_patch = 1297648 if color == "fire" else 1297649
    removed = next((event for event in debuffs if event.get("targetID") == player_id
                    and int(ability_id(event) or 0) == debuff_id
                    and event_type(event) == "removedebuff"
                    and start <= int(event.get("timestamp") or 0) < end), None)
    remove_ts = int(removed.get("timestamp") or 0) if removed else None
    if remove_ts is None:
        return "unresolved", "debuff-not-removed", True
    collided = next((event for event in debuffs if event.get("targetID") == player_id
                     and int(ability_id(event) or 0) == opposite_patch
                     and abs(int(event.get("timestamp") or 0) - remove_ts) <= 1500
                     and event_type(event) in {"applydebuff", "refreshdebuff"}), None)
    if collided:
        return "correct", "opposite-patch-collision", False
    immunities = active_immunities(friendly_buffs, player_id, remove_ts, 1800)
    if immunities:
        return "immunity", "immunity-removed-without-collision", True
    return "wrong", "removed-without-opposite-patch", True


def analyze_lost(fight, actor_map, players, raw):
    casts, damage, debuffs, enemy_buffs, friendly_buffs = (raw[key] for key in ("casts", "damage", "debuffs", "enemyBuffs", "friendlyBuffs"))
    defense_events = [event for event in enemy_buffs if int(ability_id(event) or 0) == 1297646]
    defense_rows = []
    active = {}
    for event in sorted(defense_events, key=lambda row: int(row.get("timestamp") or 0)):
        boss_id = event.get("targetID") or event.get("sourceID")
        if event_type(event) == "applybuff":
            active[boss_id] = int(event["timestamp"])
            continue
        if event_type(event) != "removebuff" or boss_id not in active:
            continue
        start_ts, end_ts = active.pop(boss_id), int(event["timestamp"])
        defense_rows.append({
            "index": len(defense_rows) + 1,
            "timeMs": start_ts - fight["startTime"],
            "time": fmt_ms(start_ts - fight["startTime"]),
            "endTimeMs": end_ts - fight["startTime"],
            "endTime": fmt_ms(end_ts - fight["startTime"]),
            "durationSec": round((end_ts - start_ts) / 1000, 1),
            "bossID": boss_id,
            "bossName": source_name(actor_map, boss_id, SOURCE_NAMES),
        })
    for boss_id, start_ts in active.items():
        defense_rows.append({
            "index": len(defense_rows) + 1,
            "timeMs": start_ts - fight["startTime"],
            "time": fmt_ms(start_ts - fight["startTime"]),
            "endTimeMs": None,
            "endTime": "战斗结束仍未结束",
            "durationSec": round((int(fight["endTime"]) - start_ts) / 1000, 1),
            "bossID": boss_id,
            "bossName": source_name(actor_map, boss_id, SOURCE_NAMES),
        })
    avoidable = _avoidable_board(fight, actor_map, players, damage, raw["deaths"], {1305844: spell_name(1305844)})
    shell_hits = [event for event in debuffs if int(ability_id(event) or 0) == 1291918 and event_type(event) in {"applydebuff", "refreshdebuff"}]
    shell_board = Counter(event.get("targetID") for event in shell_hits if event.get("targetID") in players)
    avoidable.extend([{**player_ref(players, actor_map, player_id), "spellID": 1291918, "spellName": spell_name(1291918), "hitCount": count,
                       "totalDamage": 0, "maxHit": 0, "deathCount": 0, "events": []} for player_id, count in shell_board.items()])
    missed = _completed_casts(casts, 1286922)

    volley_casts = _completed_casts(casts, 1295891)
    volley_rounds = []
    for index, cast in enumerate(volley_casts, start=1):
        start = int(cast["timestamp"])
        end = min(int(fight["endTime"]), start + 25_000)
        assignments = [event for event in _events_between(debuffs, start - 1000, start + 6000, {1295928, 1295954}) if event_type(event) == "applydebuff"]
        assignment_rows = []
        for assignment in assignments:
            player_id = assignment.get("targetID")
            color = "fire" if int(ability_id(assignment) or 0) == 1295928 else "frost"
            resolution, reason, left_patch_risk = _frostfire_resolution(start, end, player_id, color, debuffs, friendly_buffs)
            assignment_rows.append({
                **player_ref(players, actor_map, player_id),
                "color": color,
                "debuffID": int(ability_id(assignment)),
                "resolution": resolution,
                "resolutionReason": reason,
                "leftPatchRisk": left_patch_risk,
            })
        volley_target = cast.get("targetID") if cast.get("targetID") in players else None
        volley_rounds.append({"index": index, "timeMs": start - fight["startTime"], "time": fmt_ms(start - fight["startTime"]),
                              "targetID": volley_target, "target": actor_name(actor_map, volley_target) if volley_target else "全团冰火分配", "assignments": assignment_rows})

    thud_casts = _completed_casts(casts, 1296094)
    thud_rounds = []
    for index, cast in enumerate(thud_casts, start=1):
        timestamp = int(cast["timestamp"])
        hits = sorted(_events_between(damage, timestamp - 500, timestamp + 4500, {1300237}),
                      key=lambda event: int(event.get("timestamp") or 0))
        waves = group_nearby(hits, 450)
        wave_rows = []
        for wave_index, wave in enumerate(waves[:3], start=1):
            wave_ts = min(int(event["timestamp"]) for event in wave)
            participants = sorted({event.get("targetID") for event in wave if event.get("targetID") in players})
            target_id = max(participants, key=lambda player_id: sum(event_amount(event) for event in wave if event.get("targetID") == player_id), default=None)
            wave_rows.append({
                "wave": wave_index,
                "timeMs": wave_ts - fight["startTime"],
                "time": fmt_ms(wave_ts - fight["startTime"]),
                "targetID": target_id,
                "target": actor_name(actor_map, target_id),
                "participants": [player_ref(players, actor_map, player_id) for player_id in participants],
            })
        thud_rounds.append({
            "index": index, "timeMs": timestamp - fight["startTime"], "time": fmt_ms(timestamp - fight["startTime"]),
            "waves": wave_rows,
        })
    return {"unitedDefense": defense_rows, "avoidable": {"players": avoidable, "missedIceboundFlames": len(missed),
            "missedIceboundEvents": [{"time": fmt_ms(event["timestamp"] - fight["startTime"])} for event in missed]},
            "frostfireVolley": volley_rounds, "mightyThud": thud_rounds}


def analyze_vashnik(fight, actor_map, players, raw):
    avoidable = _avoidable_board(fight, actor_map, players, raw["damage"], raw["deaths"], {
        1295798: spell_name(1295798),
        1286737: spell_name(1286737),
    })
    avoidable_summary = [
        {"spellID": spell_id, "spellName": spell_name(spell_id),
         "hitCount": sum(row["hitCount"] for row in avoidable if row["spellID"] == spell_id),
         "playerCount": sum(1 for row in avoidable if row["spellID"] == spell_id)}
        for spell_id in (1295798, 1286737)
    ]
    infection_casts = sorted(_completed_casts(raw["casts"], 1282114), key=lambda event: event["timestamp"])
    rounds = []
    for index, cast in enumerate(infection_casts, start=1):
        start = int(cast["timestamp"])
        end = int(infection_casts[index]["timestamp"]) if index < len(infection_casts) else int(fight["endTime"])
        debuff_applies = [event for event in raw["debuffs"] if int(ability_id(event) or 0) in {1294994, 1295173, 1295224}
                          and event_type(event) == "applydebuff" and start <= int(event["timestamp"]) < end]
        soaker_hits = _events_between(raw["damage"], start, end, {1282117})
        soakers = sorted({event.get("targetID") for event in soaker_hits if event.get("targetID") in players})
        rounds.append({
            "index": index,
            "timeMs": start - fight["startTime"],
            "time": fmt_ms(start - fight["startTime"]),
            "endTime": fmt_ms(end - fight["startTime"]),
            "infectionTargets": [{
                **player_ref(players, actor_map, event.get("targetID")),
                "infectionID": int(ability_id(event)),
                "infection": spell_name(int(ability_id(event))),
            } for event in debuff_applies],
            "soakers": [player_ref(players, actor_map, player_id) for player_id in soakers],
            "soakerCount": len(soakers),
        })
    return {"avoidable": {"players": avoidable, "summary": avoidable_summary}, "adaptiveInfection": {"rounds": rounds}}


def _position_state(position_index, actor_id, timestamp):
    state = position_at_interpolated(position_index, actor_id, timestamp, reliable_window_ms=POSITION_RELIABLE_MS)
    if not state:
        return None, False
    return {"x": state["x"], "y": state["y"]}, bool(state.get("reliable"))


def _player_positions_over_window(position_index, player_ids, start, end, step_ms=REPLAY_STEP_MS):
    frames = []
    cursor = start
    while cursor <= end:
        frame_players = []
        for player_id in player_ids:
            position, reliable = _position_state(position_index, player_id, cursor)
            frame_players.append({
                "position": position,
                "positionReliable": reliable,
            })
        frames.append({"timeMs": cursor, "players": frame_players})
        cursor += step_ms
    return frames


def _infer_wind_from_frames(frames, arena):
    if not arena or len(frames) < 2:
        return None
    vectors = []
    for index in range(1, len(frames)):
        prev, curr = frames[index - 1], frames[index]
        for left, right in zip(prev["players"], curr["players"]):
            if not left.get("position") or not right.get("position"):
                continue
            dx = right["position"]["x"] - left["position"]["x"]
            dy = right["position"]["y"] - left["position"]["y"]
            if math.hypot(dx, dy) >= KNOCKBACK_DISPLACEMENT:
                vectors.append((dx, dy))
    if not vectors:
        return None
    dx = sum(item[0] for item in vectors) / len(vectors)
    dy = sum(item[1] for item in vectors) / len(vectors)
    angle = round((math.degrees(math.atan2(-dy, dx)) + 360) % 360, 1)
    delta_a = min((angle - _WIND_SKULL_TO_CROSS) % 360, (_WIND_SKULL_TO_CROSS - angle) % 360)
    delta_b = min((angle - _WIND_CROSS_TO_SKULL) % 360, (_WIND_CROSS_TO_SKULL - angle) % 360)
    direction = "A" if delta_a <= delta_b else "B"
    return {
        "dx": dx, "dy": dy,
        "angleDegrees": _asset_angle(angle),
        "wclAngleDegrees": angle,
        "directionKey": direction,
    }


def _infer_dig_winds(frames, arena, segment_count=3):
    if not frames:
        return []
    start_ms = frames[0]["timeMs"]
    end_ms = frames[-1]["timeMs"]
    span = max(end_ms - start_ms, 1)
    winds = []
    for index in range(segment_count):
        seg_start = start_ms + int(span * index / segment_count)
        seg_end = start_ms + int(span * (index + 1) / segment_count)
        segment = [frame for frame in frames if seg_start <= frame["timeMs"] <= seg_end]
        winds.append(_infer_wind_from_frames(segment, arena))
    return winds


def _placement_slot_validation(placements, wind_keys):
    opposite = {"A": "B", "B": "A"}
    for index, row in enumerate(placements[:4], start=1):
        row["slot"] = index
        if index <= 3 and len(wind_keys) >= index and wind_keys[index - 1]:
            expected_wind = wind_keys[index - 1]["directionKey"]
            expected_side = opposite.get(expected_wind)
            row["expectedWind"] = expected_wind
            row["expected"] = f"风口 {expected_wind} 对面（{expected_side} 侧）"
            row["placementOk"] = row.get("windSide") == expected_side
        elif index == 4:
            row["expected"] = "转阶段后坦克归位"
            row["placementOk"] = None
        else:
            row["expected"] = "风向待推断"
            row["placementOk"] = None
    return placements


def _sszorak_cysts(fight, actor_map, players, raw, position_index, arena):
    trigger_times = sorted({
        int(event["timestamp"])
        for event in raw["debuffs"]
        if int(ability_id(event) or 0) == CYST_TRIGGER_DEBUFF_ID and event_type(event) == "applydebuff"
    })
    rows = []
    active = {}
    for event in sorted(raw["debuffs"], key=lambda row: int(row.get("timestamp") or 0)):
        spell_id = int(ability_id(event) or 0)
        timestamp = int(event["timestamp"])
        target_id = event.get("targetID")
        if target_id not in players:
            continue
        if spell_id == CYST_PLACEMENT_DEBUFF_ID and event_type(event) == "applydebuff":
            position, reliable = _position_state(position_index, target_id, timestamp)
            wind_side = _wind_side_from_position(position["x"], position["y"], arena) if position and arena else None
            row = {
                "placementKey": f"{target_id}:{timestamp}",
                "applyTimestamp": timestamp,
                "timeMs": timestamp - fight["startTime"],
                "time": fmt_ms(timestamp - fight["startTime"]),
                **player_ref(players, actor_map, target_id),
                "position": position,
                "sampleOffsetMs": None,
                "positionReliable": reliable,
                "windSide": wind_side,
                "consumedAtMs": None,
                "consumedTime": None,
                "active": True,
            }
            active[target_id] = row
            rows.append(row)
        elif spell_id == CYST_PLACEMENT_DEBUFF_ID and event_type(event) == "removedebuff" and target_id in active:
            row = active.pop(target_id)
            row["consumedAtMs"] = timestamp - fight["startTime"]
            row["consumedTime"] = fmt_ms(timestamp - fight["startTime"])
            row["active"] = False
            row["consumeReason"] = "囊肿触发"
    for row in rows:
        if row.get("consumedAtMs") is not None:
            continue
        for trigger_ts in trigger_times:
            if trigger_ts >= row["applyTimestamp"]:
                row["consumedAtMs"] = trigger_ts - fight["startTime"]
                row["consumedTime"] = fmt_ms(trigger_ts - fight["startTime"])
                row["active"] = False
                row["consumeReason"] = "全团击飞"
                break
    return rows


def _sszorak_crosswind_waves(fight, actor_map, players, debuffs, position_index, arena):
    active = {}
    waves = defaultdict(list)
    for event in sorted(debuffs, key=lambda row: int(row.get("timestamp") or 0)):
        spell_id = int(ability_id(event) or 0)
        if spell_id not in CROSSWIND_DIRECTIONS:
            continue
        target_id = event.get("targetID")
        if target_id not in players:
            continue
        key = (target_id, spell_id)
        if event_type(event) == "applydebuff":
            active[key] = event
        elif event_type(event) == "removedebuff" and key in active:
            apply = active.pop(key)
            start, end = int(apply["timestamp"]), int(event["timestamp"])
            position, reliable = _position_state(position_index, target_id, start)
            waves[end].append({
                "applyTimestamp": start,
                "applyTimeMs": start - fight["startTime"],
                "applyTime": fmt_ms(start - fight["startTime"]),
                "timeMs": end - fight["startTime"],
                "time": fmt_ms(end - fight["startTime"]),
                "spellID": spell_id,
                **player_ref(players, actor_map, target_id),
                "position": position,
                "positionReliable": reliable,
                "circleRadiusYards": CROSSWIND_CIRCLE_YARDS,
                "directionGroup": CROSSWIND_DIRECTIONS[spell_id]["key"],
            })
    rows = []
    for end_ts in sorted(waves):
        targets = waves[end_ts]
        direction_spell = Counter(row["spellID"] for row in targets).most_common(1)[0][0]
        direction = CROSSWIND_DIRECTIONS[direction_spell]
        rows.append({
            "timeMs": targets[0]["timeMs"],
            "time": targets[0]["time"],
            "applyTimeMs": min(row["applyTimeMs"] for row in targets),
            "applyTime": fmt_ms(min(row["applyTimestamp"] for row in targets) - fight["startTime"]),
            "directionGroup": direction["key"],
            "inferredDirection": direction["label"],
            "arrowAngleDegrees": direction["angleDegrees"],
            "wclAngleDegrees": direction["wclAngleDegrees"],
            "targets": targets,
            "targetCount": len(targets),
        })
    return rows


def _predator_cycles(casts):
    casts = sorted([event for event in casts if int(ability_id(event) or 0) in PREDATOR_CASTS and event_type(event) == "cast"],
                   key=lambda event: event["timestamp"])
    cycles, current = [], []
    for event in casts:
        current.append(event)
        if len(current) == 5:
            cycles.append(current)
            current = []
    if current:
        cycles.append(current)
    return cycles


def analyze_sszorak(fight, actor_map, players, raw):
    casts, damage, debuffs = raw["casts"], raw["damage"], raw["debuffs"]
    boss_id = raw.get("bossID")
    position_index = build_position_index(raw.get("bossPositionEvents", []) + raw["resources"] + damage + debuffs)
    arena = arena_estimate_with_boss(position_index, players, boss_id=boss_id)
    deaths = raw["deaths"]
    tank_ids = {player_id for player_id, player in players.items() if player.get("role") == "tank"}

    sequence = []
    for cycle_index, cycle in enumerate(_predator_cycles(casts), start=1):
        for step_index, cast in enumerate(cycle, start=1):
            spell_id, timestamp = int(ability_id(cast)), int(cast["timestamp"])
            hits = _events_between(damage, timestamp - 300, timestamp + 2500, PREDATOR_DAMAGE[spell_id])
            hit_totals = Counter()
            for event in hits:
                if event.get("targetID") in players:
                    hit_totals[event.get("targetID")] += event_amount(event)
            if spell_id == 1287072:
                dot_hits = _events_between(damage, timestamp, timestamp + 3000, {1287083})
                affected = sorted({event.get("targetID") for event in dot_hits if event.get("targetID") in players})
                sequence.append({
                    "cycle": cycle_index, "step": step_index, "index": len(sequence) + 1,
                    "timeMs": timestamp - fight["startTime"], "time": fmt_ms(timestamp - fight["startTime"]),
                    "spellID": spell_id, "skill": PREDATOR_LABELS[spell_id], "targetID": None, "target": "—",
                    "affectedTargets": [player_ref(players, actor_map, player_id) for player_id in affected],
                    "participants": [], "deaths": [],
                })
                continue
            if spell_id == 1277002:
                target_id = next((player_id for player_id in tank_ids if hit_totals.get(player_id)), None)
                if target_id is None:
                    target_id = max(hit_totals, key=hit_totals.get, default=cast.get("targetID"))
            else:
                tank_hits = [player_id for player_id in hit_totals if player_id in tank_ids]
                target_id = tank_hits[0] if tank_hits else max(hit_totals, key=hit_totals.get, default=cast.get("targetID"))
            death_players = [event.get("targetID") for event in deaths
                             if timestamp - 300 <= int(event.get("timestamp") or 0) <= timestamp + 3000
                             and (not event.get("killingAbilityGameID") or int(event.get("killingAbilityGameID") or 0) in PREDATOR_DAMAGE[spell_id])]
            participants = [{**player_ref(players, actor_map, player_id), "damage": amount}
                            for player_id, amount in hit_totals.items()
                            if spell_id == 1277027 or player_id != target_id]
            sequence.append({
                "cycle": cycle_index, "step": step_index, "index": len(sequence) + 1,
                "timeMs": timestamp - fight["startTime"], "time": fmt_ms(timestamp - fight["startTime"]),
                "spellID": spell_id, "skill": PREDATOR_LABELS[spell_id],
                "targetID": target_id, "target": actor_name(actor_map, target_id) if target_id else "—",
                "participants": participants,
                "deaths": [player_ref(players, actor_map, player_id) for player_id in death_players],
            })

    tempest = _avoidable_board(fight, actor_map, players, damage, deaths, {1287083: spell_name(1287083)})
    all_cysts = _sszorak_cysts(fight, actor_map, players, raw, position_index, arena)
    digs = _completed_casts(casts, 1286033)
    cyst_rounds = []
    replay_rounds = []
    for index, dig in enumerate(digs, start=1):
        timestamp = int(dig["timestamp"])
        previous = int(digs[index - 2]["timestamp"]) if index > 1 else int(fight["startTime"])
        placements = [dict(row) for row in all_cysts if previous <= row["applyTimestamp"] <= timestamp][-4:]
        for slot, row in enumerate(placements, start=1):
            row["slot"] = slot
        cyst_rounds.append({"index": index, "time": fmt_ms(timestamp - fight["startTime"]), "placements": placements})

        end = timestamp + DIG_DURATION_MS
        frames = _player_positions_over_window(position_index, players, timestamp, end, step_ms=REPLAY_STEP_MS)
        winds = _infer_dig_winds(frames, arena, segment_count=3)
        validated = _placement_slot_validation(placements, winds)
        replay_rounds.append({
            "index": index,
            "timeMs": timestamp - fight["startTime"],
            "time": fmt_ms(timestamp - fight["startTime"]),
            "durationSec": DIG_DURATION_MS / 1000,
            "placements": validated,
            "winds": winds,
            "wind": winds[0] if winds else None,
            "frames": [{
                "timeMs": frame["timeMs"] - fight["startTime"],
                "time": fmt_ms(frame["timeMs"] - fight["startTime"]),
                "players": [{**player_ref(players, actor_map, player_id), **frame_player}
                             for player_id, frame_player in zip(players, frame["players"])],
            } for frame in frames],
        })

    crosswind_waves = _sszorak_crosswind_waves(fight, actor_map, players, debuffs, position_index, arena)
    crosswind_rows = [{
        "timeMs": wave["timeMs"], "time": wave["time"],
        "applyTimeMs": wave["applyTimeMs"], "applyTime": wave["applyTime"],
        "spellID": wave["targets"][0]["spellID"] if wave.get("targets") else None,
        "directionGroup": wave["directionGroup"],
        "inferredDirection": wave["inferredDirection"],
        "arrowAngleDegrees": wave["arrowAngleDegrees"],
        "targetCount": wave["targetCount"],
    } for wave in crosswind_waves]

    fall_deaths = [{
        **player_ref(players, actor_map, event.get("targetID")),
        "timeMs": int(event["timestamp"] - fight["startTime"]),
        "time": fmt_ms(int(event["timestamp"] - fight["startTime"])),
        "cause": spell_name(int(event.get("killingAbilityGameID") or 0)) if event.get("killingAbilityGameID") else "跌落",
        "note": "未记录致死技能，通常为掘地固守吹风或狂怒侧风导致跌落",
    } for event in deaths if event.get("targetID") in players and not event.get("killingAbilityGameID")]

    boss_center = None
    if boss_id is not None:
        boss_state = position_at_interpolated(position_index, boss_id, int(fight["startTime"] + fight["endTime"]) // 2)
        if boss_state:
            boss_center = {"x": boss_state["x"], "y": boss_state["y"]}

    return {
        "apexPredator": {"cycles": len(_predator_cycles(casts)), "sequence": sequence, "tempestDamage": tempest},
        "cysts": {"rounds": cyst_rounds, "placements": all_cysts},
        "crosswinds": {"waves": crosswind_waves, "players": crosswind_rows},
        "fieldReplay": {
            "arena": arena,
            "arenaImage": BOSSES["sszorak"]["arena"],
            "bossCenter": boss_center,
            "frameStepMs": REPLAY_STEP_MS,
            "rounds": replay_rounds,
            "crosswindWaves": crosswind_waves,
            "evidenceNote": "掘地固守 25 秒内按 200ms 插值采样；Boss 坐标锚定场地中心；囊肿在击飞后隐藏；狂怒侧风同步展示点名圈与固定风向。",
        },
        "fallDeaths": fall_deaths,
    }


def _venom_attribution(damage_events, casts, timestamp, player_id):
    nearby = [event for event in damage_events if event.get("targetID") == player_id
              and abs(int(event.get("timestamp") or 0) - timestamp) <= 1200]
    if nearby:
        spell_id = int(ability_id(nearby[0]) or 0)
        if spell_id in VENOM_ABNORMAL_DAMAGE:
            return VENOM_ABNORMAL_DAMAGE[spell_id], spell_id, "abnormal"
        if spell_id in VENOM_GAIN_DAMAGE:
            return VENOM_GAIN_DAMAGE[spell_id], spell_id, "normal"
        return spell_name(spell_id), spell_id, "damage"
    if any(abs(int(cast.get("timestamp") or 0) - timestamp) <= 3500 for cast in casts if int(ability_id(cast) or 0) in FEAST_IDS):
        return spell_name(1290516), 1290516, "feast"
    return "未知来源", None, "unknown"


def analyze_twinfangs(fight, actor_map, players, raw):
    debuffs, casts, damage, buffs = raw["debuffs"], raw["casts"], raw["damage"], raw["friendlyBuffs"]
    venom_events = [event for event in debuffs if int(ability_id(event) or 0) == 1290336]
    histories = []
    for player_id in players:
        current, peak, rows = 0, 0, []
        for event in sorted((item for item in venom_events if item.get("targetID") == player_id), key=lambda item: int(item.get("timestamp") or 0)):
            kind, before = event_type(event), current
            timestamp = int(event.get("timestamp") or 0)
            raw_stack = event.get("stack")
            if kind in {"applydebuff", "applydebuffstack", "refreshdebuff"}:
                current = int(raw_stack) if raw_stack is not None else max(1, current + (1 if "stack" in kind else 0))
                source_label, source_id, category = _venom_attribution(damage, casts, timestamp, player_id)
                action = "gain"
            elif kind == "removedebuffstack":
                current = int(raw_stack) if raw_stack is not None else max(0, current - 1)
                action = "remove"
                feast = any(abs(int(cast.get("timestamp") or 0) - timestamp) <= 3500 for cast in casts if int(ability_id(cast) or 0) in FEAST_IDS)
                source_label = spell_name(1290516) if feast else "层数移除"
                source_id = 1290516 if feast else None
                category = "feast" if feast else "remove"
            elif kind == "removedebuff":
                current, action = 0, "clear"
                source_label, source_id, category = spell_name(1290516), 1290516, "feast"
            else:
                continue
            peak = max(peak, current)
            rows.append({
                "timeMs": timestamp - fight["startTime"], "time": fmt_ms(timestamp - fight["startTime"]),
                "eventType": kind, "action": action, "fromStack": before, "toStack": current,
                "delta": current - before, "source": source_label, "sourceID": source_id, "category": category,
            })
        if rows:
            histories.append({**player_ref(players, actor_map, player_id), "peakStack": peak,
                              "gainCount": sum(row["delta"] for row in rows if row["delta"] > 0),
                              "removedCount": -sum(row["delta"] for row in rows if row["delta"] < 0), "events": rows})

    feast_casts = [event for event in casts if int(ability_id(event) or 0) in FEAST_IDS and event_type(event) == "cast"]
    feast_checks = []
    for index, cast in enumerate(feast_casts, start=1):
        timestamp = int(cast["timestamp"])
        present = sorted({event.get("targetID") for event in venom_events if event.get("targetID") in players
                          and abs(int(event.get("timestamp") or 0) - timestamp) <= 5000
                          and event_type(event) in {"applydebuff", "applydebuffstack", "refreshdebuff"}
                          and int(event.get("stack") or 1) >= 1})
        consumed = sorted({event.get("targetID") for event in venom_events if event.get("targetID") in players
                           and abs(int(event.get("timestamp") or 0) - timestamp) <= 5000
                           and event_type(event) in {"removedebuffstack", "removedebuff"}})
        missing = [player_ref(players, actor_map, player_id) for player_id in present if player_id not in consumed]
        feast_checks.append({
            "index": index, "time": fmt_ms(timestamp - fight["startTime"]),
            "present": [player_ref(players, actor_map, player_id) for player_id in present],
            "consumed": [player_ref(players, actor_map, player_id) for player_id in consumed],
            "missing": missing,
        })

    deluges = _completed_casts(casts, 1289192)
    emergences = sorted(int(event["timestamp"]) for event in casts if int(ability_id(event) or 0) == 1291404 and event_type(event) == "begincast")
    death_times = {player_id: min((int(event["timestamp"]) for event in raw["deaths"] if event.get("targetID") == player_id), default=10**18) for player_id in players}
    globule_rounds = []
    for index, cast in enumerate(deluges, start=1):
        start = int(cast["timestamp"])
        end = next((timestamp for timestamp in emergences if timestamp > start), int(fight["endTime"]))
        hits = _events_between(damage, start, end, {1289201})
        explosions = _events_between(damage, start, end, {1290338})
        participants = sorted({event.get("targetID") for event in hits if event.get("targetID") in players})
        explosion_ts = min((int(event["timestamp"]) for event in explosions), default=None)
        missing = []
        if explosion_ts:
            for player_id in players:
                if player_id in participants or death_times[player_id] <= explosion_ts:
                    continue
                immunities = active_immunities(buffs, player_id, explosion_ts, 1800)
                if not immunities:
                    missing.append(player_ref(players, actor_map, player_id))
        globule_rounds.append({"index": index, "timeMs": start - fight["startTime"], "time": fmt_ms(start - fight["startTime"]),
                               "endTime": fmt_ms(end - fight["startTime"]), "participantCount": len(participants),
                               "participants": [player_ref(players, actor_map, player_id) for player_id in participants],
                               "hitCount": len(hits), "exploded": bool(explosions), "explosionTime": fmt_ms(explosion_ts - fight["startTime"]) if explosion_ts else None,
                               "nonParticipants": missing})
    return {
        "eternalVenom": {"players": histories, "feastChecks": feast_checks},
        "globules": {"rounds": globule_rounds},
        "mythicPlaceholder": "该部分暂时没有可用的信息。",
    }


ANALYZERS = {"lostexplorers": analyze_lost, "vashnik": analyze_vashnik, "sszorak": analyze_sszorak, "twinfangs": analyze_twinfangs}


def fetch_payload(client, report_id, fight, boss_key, boss_id=None):
    payload = {
        "casts": client.events(report_id, "Casts", fight, hostility_type="Enemies"),
        "friendlyCasts": client.events(report_id, "Casts", fight, hostility_type="Friendlies"),
        "damage": client.events(report_id, "DamageTaken", fight, include_resources=True),
        "debuffs": client.events(report_id, "Debuffs", fight, include_resources=True),
        "enemyBuffs": client.events(report_id, "Buffs", fight, hostility_type="Enemies"),
        "friendlyBuffs": client.events(report_id, "Buffs", fight, hostility_type="Friendlies"),
        "deaths": client.events(report_id, "Deaths", fight),
        "combatants": client.events(report_id, "CombatantInfo", fight),
        "resources": [],
        "bossPositionEvents": [],
        "bossID": boss_id,
    }
    if boss_key == "sszorak":
        payload["resources"] = client.events(report_id, "Resources", fight, include_resources=True)
        if boss_id is not None:
            boss_damage = client.events(
                report_id,
                "DamageDone",
                fight,
                target_id=boss_id,
                include_resources=True,
            )
            payload["bossPositionEvents"] = compact_actor_position_events(boss_damage, boss_id)
    return payload


def render_fight(boss_key, report_id, report_start, actor_map, actor_type, fight, raw):
    config = BOSSES[boss_key]
    players = build_player_catalog(actor_map, actor_type, raw["combatants"])
    deaths = [event for event in raw["deaths"] if event.get("targetID") in players]
    raw["deaths"] = deaths
    duration_ms = int(fight["endTime"] - fight["startTime"])
    started = datetime.fromtimestamp((report_start + fight["startTime"]) / 1000, tz=CN_TZ)
    survival = build_survival_timeline(fight, actor_map, players, deaths, raw["friendlyCasts"], config["spellNames"])
    mechanics = ANALYZERS[boss_key](fight, actor_map, players, raw)
    return {
        "reportID": report_id, "fightID": int(fight["id"]), "fightName": fight.get("name"),
        "date": started.strftime("%Y-%m-%d"), "startClock": started.strftime("%H:%M:%S"), "startTimeIso": started.isoformat(),
        "isKill": bool(fight.get("kill")), "kill": bool(fight.get("kill")), "bossPercentage": float(fight.get("bossPercentage") or 0),
        "durationMs": duration_ms, "duration": fmt_ms(duration_ms), "fightPhase": "单阶段", "wipePhase": "击杀" if fight.get("kill") else "灭团",
        "wipeReason": "已击杀" if fight.get("kill") else "请按机制时间线复盘", "investigation": "死亡、战复与专属机制已按时间对齐。",
        "wclDeepLink": f"https://www.warcraftlogs.com/reports/{report_id}#fight={fight['id']}&type=summary",
        "players": list(players.values()), "survival": survival, "deathTimeline": survival["timeline"],
        boss_key: mechanics, **difficulty_fields(fight),
    }


def build_aggregated_json(boss_key, report_ids, options=None):
    config = BOSSES[boss_key]
    report_id_list = [value for value in (item.strip() for item in report_ids.replace(" ", "").split(",")) if value]
    if not report_id_list:
        raise RuntimeError("请传入至少一个 WCL report ID。")
    client = WclClient()
    rendered = []
    progress(boss_key, f"读取 {config['name']} Pull 列表", 8)
    for report_id in report_id_list:
        report = client.report_fights(report_id)
        fights = filter_fights(report_id, [fight for fight in report["fights"]
                         if int(fight.get("encounterID") or 0) in config["encounterIDs"] and fight["endTime"] - fight["startTime"] >= 20_000])
        actors = client.actors(report_id)
        actor_map = {actor["id"]: actor["name"] for actor in actors}
        actor_type = {actor["id"]: actor.get("type") for actor in actors}
        boss_id = None
        if boss_key == "sszorak":
            boss_id = resolve_boss_actor_id(actors, SSZORAK_GAME_ID, ("Sszorak", "斯索拉克"))
        progress(boss_key, f"{report_id}：匹配 {len(fights)} 场", 12)

        def fetch_one(item):
            index, fight = item
            progress(boss_key, f"读取 Fight {fight['id']}（{index}/{len(fights)}）")
            raw = fetch_payload(client, report_id, fight, boss_key, boss_id=boss_id)
            return index, render_fight(boss_key, report_id, report["startTime"], actor_map, actor_type, fight, raw)

        for _, row in run_parallel_indexed(list(enumerate(fights, start=1)), fetch_one):
            rendered.append(row)
    rendered.sort(key=lambda row: (row["startTimeIso"], row["reportID"], row["fightID"]))
    avoidable_rows = []
    for row in rendered:
        avoidable_rows.extend((row.get(boss_key) or {}).get("avoidable", {}).get("players", []))
    progress(boss_key, "生成难度分组、存活时间线与机制数据", 96)
    return {
        "code": 200,
        "meta": {"version": "12.1", "raidKey": "venomous_abyss", "raidName": "烈毒之渊", "bossKey": boss_key,
                 "bossName": config["name"], "analyzedReports": report_id_list, "mechanicVersion": f"{boss_key}-progression-2026-08-26",
                 "tabDefinitions": [{"key": key, "label": label} for key, label in config["tabs"]],
                 "arenaImage": config["arena"], "features": {"survival": True, "fieldReplay": boss_key == "sszorak"},
                 "evidenceLimits": {"positions": "仅使用 WCL 实际坐标样本；超过采样窗只展示，不归责。"}},
        "data": {"page1_wipeAnalysis": rendered, "page2_avoidableBoard": {"avoidable": avoidable_rows}},
    }


def analyze_boss(boss_key, report_ids, output_path=None, catalog_entry=None, options=None):
    return write_json_result(build_aggregated_json(boss_key, report_ids, options), output_path, catalog_entry=catalog_entry)
