"""Evidence-first analyzer and field replay for Sszorak."""

from __future__ import annotations

import math
from copy import deepcopy
from analyzer_core.config import resolve_analysis_options
from collections import Counter, defaultdict

from boss_plugins.common import write_json_result
from boss_plugins.venomous_abyss.runtime import build_aggregated_json as _build
from boss_plugins.venomous_abyss.shared import (
    IMMUNITY_SPELLS,
    ability_id,
    actor_name,
    avoidable_board as _avoidable_board,
    build_position_index,
    completed_casts as _completed_casts,
    event_amount,
    event_type,
    events_between as _events_between,
    fmt_ms,
    group_nearby,
    load_confirmed_spell_names,
    nightly_detail,
    nightly_player_totals,
    player_ref,
    position_at_interpolated,
    spell_name,
)

GUIDE_SPELLS = load_confirmed_spell_names()

CONFIG_SCHEMA = [
    {"key": "predatorReviewEnabled", "type": "boolean", "label": "顶级掠食者技能处理", "default": True},
    {"key": "tempestReviewEnabled", "type": "boolean", "label": "风暴施加与驱散", "default": True},
    {"key": "serpentsFuryReviewEnabled", "type": "boolean", "label": "史诗印记分摊", "default": True},
    {"key": "cystsReviewEnabled", "type": "boolean", "label": "囊肿放置与激活", "default": True,
     "description": "需要坐标与风向采样；关闭场地推演后仍可单独分析。"},
    {"key": "crosswindsReviewEnabled", "type": "boolean", "label": "狂怒侧风位置归因", "default": True},
    {"key": "fieldReplayEnabled", "type": "boolean", "label": "场地推演", "default": True, "expensive": True,
     "description": "生成逐帧回放。关闭后跳过回放帧；囊肿、侧风也关闭时，不再读取场地坐标。"},
]

BOSS_CONFIG = {
    "key": "sszorak",
    "encounterIDs": {3420, 53420},
    "name": "斯索拉克",
    "arena": "assets/raids/venomous_abyss/05-sszorak-arena.png",
    "bossIcon": "assets/raids/venomous_abyss/05-sszorak-boss.png",
    "spellNames": GUIDE_SPELLS,
    "tabs": [
        ["survival", "全场存活情况"],
        ["predator", "顶级掠食者"],
        ["replay", "场地推演"],
        ["cysts", "腐蚀囊肿"],
        ["crosswinds", "狂怒侧风"],
        ["fury", "毒蛇之怒"],
    ],
    "mechanicVersion": "sszorak-mythic-active-dispels-2026-09-12",
    "features": {"survival": True, "fieldReplay": True},
    "bossGameID": 257347,
    "bossNameKeywords": ["Sszorak", "斯索拉克"],
    "fetchPositionResources": True,
}

PREDATOR_CASTS = {1277002, 1277027, 1287072}

PREDATOR_DAMAGE = {
    1277002: {1277101},
    1277027: {1277031, 1285999},
    1287072: {1287083},
}

PREDATOR_LABELS = {1277002: "劫掠", 1277027: "毁伤", 1287072: "风暴"}

CYST_PLACEMENT_DEBUFF_ID = 1305963

TEMPEST_DEBUFF_ID = 1287083
SERPENTS_FURY_MARK_ID = 1305621
UNBOUND_FEROCITY_ID = 1296898
FURY_SOAK_RADIUS_YARDS = 8
FURY_REQUIRED_PLAYERS = 14
FURY_POSITION_WINDOW_MS = 500

CYST_TRIGGER_DEBUFF_ID = 1287205

CYST_VOLLEY_CAST_ID = 1305959

CYST_ASSIGNMENT_AFTER_VOLLEY_MS = 8_000


DIG_DURATION_MS = 25_000

REPLAY_STEP_MS = 200

POSITION_RELIABLE_MS = 2_000

KNOCKBACK_DISPLACEMENT = 350

WIND_STEP_DISPLACEMENT = 250

CROSSWIND_CIRCLE_YARDS = 6

CROSSWIND_LAUNCH_DEBUFF_ID = 1285447

CROSSWIND_ROUND_WINDOW_MS = 1_200

CROSSWIND_COLLISION_WINDOW_MS = 120

CROSSWIND_DAMAGE_IDS = {1285616, 1312219}

CYST_WIND_EXCLUDE_BEFORE_MS = 300

CYST_WIND_EXCLUDE_AFTER_MS = 2_500

REPLAY_TAIL_AFTER_CYST_MS = 2_000

SSZORAK_WCL_MAP_Y_OFFSET = -5_000

SSZORAK_ARENA_CENTER_X = -40_652.0

SSZORAK_ARENA_CENTER_Y = 33_843.0

SSZORAK_ARENA_RADIUS = 6_200.0

DIG_WIND_MARKERS = {
    "diamond": {"label": "紫菱", "angleDegrees": 15.0},
    "square": {"label": "方块", "angleDegrees": 60.0},
    "cross": {"label": "红叉", "angleDegrees": 105.0},
    "triangle": {"label": "三角", "angleDegrees": 195.0},
    "circle": {"label": "大饼", "angleDegrees": 240.0},
    "skull": {"label": "骷髅", "angleDegrees": 285.0},
}

DIG_WIND_OPPOSITES = {
    "triangle": "diamond", "diamond": "triangle",
    "circle": "square", "square": "circle",
    "skull": "cross", "cross": "skull",
}

DIG_WIND_LINES = {
    frozenset(("triangle", "diamond")): "三角↔紫菱",
    frozenset(("circle", "square")): "大饼↔方块",
    frozenset(("skull", "cross")): "骷髅↔红叉",
}

ASSET_MAP_ROTATION_DEG = 60.0

def _bearing_deg(dx, dy):
    return (math.degrees(math.atan2(-dy, dx)) + 360) % 360

def _asset_angle(wcl_angle):
    # pct() 对世界坐标执行正向数学旋转，映射到屏幕后角度会减少相同数值。
    return (wcl_angle - ASSET_MAP_ROTATION_DEG) % 360

def _angle_delta(left, right):
    return min((left - right) % 360, (right - left) % 360)

def _dig_direction(source_key):
    target_key = DIG_WIND_OPPOSITES[source_key]
    target = DIG_WIND_MARKERS[target_key]
    source = DIG_WIND_MARKERS[source_key]
    return {
        "key": f"{source_key}-to-{target_key}",
        "sourceKey": source_key,
        "sourceMarker": source["label"],
        "targetKey": target_key,
        "targetMarker": target["label"],
        "label": f'{source["label"]} → {target["label"]}',
        "lineKey": DIG_WIND_LINES[frozenset((source_key, target_key))],
        "angleDegrees": _asset_angle(target["angleDegrees"]),
        "wclAngleDegrees": target["angleDegrees"],
    }

DIG_WIND_DIRECTIONS = {
    source_key: _dig_direction(source_key)
    for source_key in ("triangle", "circle", "skull", "diamond", "square", "cross")
}

_WIND_SKULL_TO_CROSS = DIG_WIND_DIRECTIONS["skull"]["wclAngleDegrees"]
_WIND_CROSS_TO_SKULL = DIG_WIND_DIRECTIONS["cross"]["wclAngleDegrees"]

CROSSWIND_DIRECTIONS = {
    1285425: {
        "key": "A", "label": "红叉 → 骷髅",
        "angleDegrees": _asset_angle(_WIND_CROSS_TO_SKULL),
        "wclAngleDegrees": _WIND_CROSS_TO_SKULL,
    },
    1285453: {
        "key": "B", "label": "骷髅 → 红叉",
        "angleDegrees": _asset_angle(_WIND_SKULL_TO_CROSS),
        "wclAngleDegrees": _WIND_SKULL_TO_CROSS,
    },
    # 史诗增加一条与 A/B 垂直的对穿轴；不要用混有主动移动的短轨迹扭曲箭头。
    1297096: {"key": "C", "label": "三角 → 紫菱", "angleDegrees": _asset_angle(15), "wclAngleDegrees": 15},
    1297111: {"key": "D", "label": "紫菱 → 三角", "angleDegrees": _asset_angle(195), "wclAngleDegrees": 195},
}

CROSSWIND_MOBILITY_SPELLS = {
    100: "冲锋",
    781: "后跳",
    1850: "急奔",
    1953: "闪现术",
    2645: "幽魂之狼",
    2983: "疾跑",
    3411: "援护",
    6544: "英勇飞跃",
    36554: "暗影步",
    48020: "恶魔法阵：传送",
    48265: "死亡脚步",
    49376: "野性冲锋",
    52174: "英勇飞跃",
    102383: "野性冲锋",
    102401: "野性冲锋",
    109132: "滚地翻",
    111400: "燃烧突袭",
    115008: "真气突",
    119996: "魂体双分：转移",
    121536: "天堂之羽",
    186257: "猎豹守护",
    189110: "地狱火撞击",
    190784: "神圣马驹",
    190925: "鱼叉猛刺",
    192063: "阵风",
    195072: "邪能冲撞",
    195457: "抓钩",
    198793: "复仇回避",
    212653: "闪光术",
    358267: "悬空",
    360995: "青翠之拥",
    370665: "营救",
}

def _wind_side_from_position(x, y, arena):
    if not arena:
        return None
    angle = _bearing_deg(x - arena["centerX"], y - arena["centerY"])
    return min(
        DIG_WIND_MARKERS,
        key=lambda marker_key: _angle_delta(angle, DIG_WIND_MARKERS[marker_key]["angleDegrees"]),
    )

def _position_state(position_index, actor_id, timestamp):
    state = position_at_interpolated(position_index, actor_id, timestamp, reliable_window_ms=POSITION_RELIABLE_MS)
    if not state:
        return None, False
    return {"x": state["x"], "y": state["y"]}, bool(state.get("reliable"))

def _sszorak_map_position_index(position_index):
    """Convert combat-event coordinates to the coordinates displayed by WCL's replay map."""
    return {
        actor_id: [{**row, "y": row["y"] + SSZORAK_WCL_MAP_Y_OFFSET} for row in rows]
        for actor_id, rows in position_index.items()
    }

def _sszorak_arena(position_index, boss_id=None):
    boss_start = None
    if boss_id is not None and position_index.get(boss_id):
        first = position_index[boss_id][0]
        boss_start = {"x": first["x"], "y": first["y"]}
    return {
        "centerX": SSZORAK_ARENA_CENTER_X,
        "centerY": SSZORAK_ARENA_CENTER_Y,
        "radius": SSZORAK_ARENA_RADIUS,
        "radiusYards": SSZORAK_ARENA_RADIUS / 100,
        "method": "fixed-wcl-map-center",
        "bossCenter": True,
        "bossStart": boss_start,
        "coordinateOffsetYards": SSZORAK_WCL_MAP_Y_OFFSET / 100,
        # RaidPlan 原图为 986 x 554；场地半径在图中约为 270px。
        "plotScaleX": 27.4,
        "plotScaleY": 48.7,
        "rotationDegrees": ASSET_MAP_ROTATION_DEG,
    }

def _first_death_times(deaths, player_ids):
    return {
        player_id: min(
            (int(event["timestamp"]) for event in deaths if event.get("targetID") == player_id),
            default=None,
        )
        for player_id in player_ids
    }

def _player_positions_over_window(
    position_index, player_ids, start, end, step_ms=REPLAY_STEP_MS, death_times=None,
):
    death_times = death_times or {}
    frames = []
    cursor = start
    while cursor <= end:
        frame_players = []
        for player_id in player_ids:
            death_time = death_times.get(player_id)
            if death_time is not None and cursor >= death_time:
                frame_players.append({
                    "position": None,
                    "positionReliable": False,
                    "dead": True,
                    "deathTimestamp": death_time,
                })
                continue
            position, reliable = _position_state(position_index, player_id, cursor)
            frame_players.append({
                "position": position,
                "positionReliable": reliable,
                "dead": False,
            })
        frames.append({"timeMs": cursor, "players": frame_players})
        cursor += step_ms
    return frames

def _infer_wind_from_frames(frames, arena, excluded_timestamps=None):
    if not arena or len(frames) < 2:
        return None
    excluded_timestamps = excluded_timestamps or []
    direction_steps = defaultdict(list)
    for index in range(1, len(frames)):
        prev, curr = frames[index - 1], frames[index]
        if any(
            timestamp - CYST_WIND_EXCLUDE_BEFORE_MS
            <= curr["timeMs"] <= timestamp + CYST_WIND_EXCLUDE_AFTER_MS
            for timestamp in excluded_timestamps
        ):
            continue
        step_vectors = []
        for left, right in zip(prev["players"], curr["players"]):
            if not left.get("position") or not right.get("position"):
                continue
            dx = right["position"]["x"] - left["position"]["x"]
            dy = right["position"]["y"] - left["position"]["y"]
            if math.hypot(dx, dy) >= WIND_STEP_DISPLACEMENT:
                step_vectors.append((dx, dy))
        if not step_vectors:
            continue
        step_votes = defaultdict(list)
        for dx, dy in step_vectors:
            vector_angle = (math.degrees(math.atan2(-dy, dx)) + 360) % 360
            source_key, direction = min(
                DIG_WIND_DIRECTIONS.items(),
                key=lambda item: _angle_delta(vector_angle, item[1]["wclAngleDegrees"]),
            )
            step_votes[source_key].append((dx, dy, vector_angle, direction))
        source_key, selected = max(
            step_votes.items(),
            key=lambda item: (len(item[1]), sum(math.hypot(row[0], row[1]) for row in item[1])),
        )
        # 只有同一帧至少两名玩家同向移动，或该方向占本帧多数（且本帧不止一人移动）时，
        # 才作为持续风证据——单人移动多为闪现贴囊或走位，不足以判定团风。
        if len(selected) >= 2 or (len(step_vectors) >= 2 and len(selected) / len(step_vectors) >= .6):
            direction_steps[source_key].append({
                "timeMs": curr["timeMs"], "selected": selected,
                "allCount": len(step_vectors),
            })
    if not direction_steps:
        return None
    source_key, selected_steps = max(
        direction_steps.items(),
        key=lambda item: (
            len(item[1]),
            sum(len(step["selected"]) for step in item[1]),
            sum(math.hypot(row[0], row[1]) for step in item[1] for row in step["selected"]),
        ),
    )
    selected = [row for step in selected_steps for row in step["selected"]]
    direction = selected[0][3]
    dx = sum(item[0] for item in selected) / len(selected)
    dy = sum(item[1] for item in selected) / len(selected)
    angle = round((math.degrees(math.atan2(-dy, dx)) + 360) % 360, 1)
    all_vote_count = sum(step["allCount"] for step in selected_steps)
    vote_ratio = len(selected) / max(all_vote_count, 1)
    angle_delta = round(_angle_delta(angle, direction["wclAngleDegrees"]), 1)
    return {
        "dx": dx, "dy": dy,
        # 场地箭头吸附到六个固定风口方向；实际位移角另行保留用于复核。
        "angleDegrees": direction["angleDegrees"],
        "wclAngleDegrees": direction["wclAngleDegrees"],
        "observedAngleDegrees": angle,
        "angleDeltaDegrees": angle_delta,
        "sampleTimeMs": selected_steps[len(selected_steps) // 2]["timeMs"],
        "samplePlayerCount": max(len(step["selected"]) for step in selected_steps),
        "sustainedFrameCount": len(selected_steps),
        "directionVoteCount": len(selected),
        "directionVoteRatio": round(vote_ratio, 3),
        "directionConfidence": "high" if vote_ratio >= .6 and angle_delta <= 20 else "medium" if vote_ratio >= .4 else "low",
        "directionKey": direction["key"],
        "directionLabel": direction["label"],
        "sourceKey": source_key,
        "sourceMarker": direction["sourceMarker"],
        "targetKey": direction["targetKey"],
        "targetMarker": direction["targetMarker"],
        "lineKey": direction["lineKey"],
    }

def _infer_dig_winds(frames, arena, segment_count=3, activation_rows=None):
    if not frames:
        return []
    activation_rows = activation_rows or []
    excluded_timestamps = [row["activatedTimestamp"] for row in activation_rows]
    start_ms = frames[0]["timeMs"]
    end_ms = frames[-1]["timeMs"]
    span = max(end_ms - start_ms, 1)
    winds = []
    for index in range(segment_count):
        seg_start = start_ms + int(span * index / segment_count)
        seg_end = start_ms + int(span * (index + 1) / segment_count)
        segment = [frame for frame in frames if seg_start <= frame["timeMs"] <= seg_end]
        wind = _infer_wind_from_frames(segment, arena, excluded_timestamps=excluded_timestamps)
        activations = [
            row for row in activation_rows
            if seg_start <= row["activatedTimestamp"] <= seg_end and row.get("windSide")
        ]
        if activations and wind is not None:
            activation = min(activations, key=lambda row: row["activatedTimestamp"])
            placement_side = activation["windSide"]
            wind = dict(wind)
            wind["nearbyActivation"] = {
                "placementKey": activation.get("placementKey"),
                "player": activation.get("player"),
                "windSide": placement_side,
                "windSideLabel": DIG_WIND_MARKERS.get(placement_side, {}).get("label"),
            }
        winds.append(wind)
    return winds

def _placement_slot_validation(placements, winds, expected_wind_count=3):
    rows = placements[:4]
    for index, row in enumerate(rows, start=1):
        row["slot"] = index
        row["windSideLabel"] = DIG_WIND_MARKERS.get(row.get("windSide"), {}).get("label")
        row["placementOk"] = None
        row["expected"] = "风向待推断"

    valid_winds = [wind for wind in winds if wind]
    winds_complete = len(valid_winds) >= expected_wind_count
    verified_sides = list(dict.fromkeys(wind["targetKey"] for wind in valid_winds))
    required_labels = "、".join(DIG_WIND_MARKERS[side]["label"] for side in verified_sides)
    for row in rows[:2]:
        row["expectedSides"] = verified_sides
        row["expected"] = f"本轮三次风的对面位置：{required_labels or '待推断'}"
        side = row.get("windSide")
        if side in verified_sides:
            row["placementOk"] = True
        elif not winds_complete:
            row["placementOk"] = None
            row["placementStatus"] = "unverified"
        elif side:
            row["placementOk"] = False
        else:
            row["placementOk"] = None

    covered = {row.get("windSide") for row in rows[:2] if row.get("windSide") in verified_sides}
    missing = [side for side in verified_sides if side not in covered]
    tail = rows[2:4]
    for row in tail:
        row["expectedSides"] = missing
        row["expected"] = (
            "后两人至少一人补足：" + "、".join(DIG_WIND_MARKERS[side]["label"] for side in missing)
            if missing else "三个风向已覆盖；该位置不归责"
        )
        if row.get("windSide") in missing:
            row["placementOk"] = True
            missing.remove(row["windSide"])
        else:
            row["placementOk"] = None
    if missing:
        for row in tail:
            if row.get("placementOk") is not True:
                if winds_complete:
                    row["placementOk"] = False
                    row["expected"] = "未补足：" + "、".join(DIG_WIND_MARKERS[side]["label"] for side in missing)
                else:
                    row["placementOk"] = None
                    row["placementStatus"] = "unverified"
    return placements

def _sszorak_cysts(fight, actor_map, players, raw, position_index, arena):
    """Build cyst placement evidence.

    Venomous Surge is assigned on apply, but the cyst is created at the holder's
    position when the aura is removed. Activation is attributed separately from
    Viscous Cyst aura/damage and forced-movement evidence.
    """
    rows = []
    pending = {}
    for event in sorted(raw["debuffs"], key=lambda row: int(row.get("timestamp") or 0)):
        spell_id = int(ability_id(event) or 0)
        timestamp = int(event["timestamp"])
        target_id = event.get("targetID")
        if target_id not in players:
            continue
        if spell_id == CYST_PLACEMENT_DEBUFF_ID and event_type(event) == "applydebuff":
            pending[target_id] = event
        elif spell_id == CYST_PLACEMENT_DEBUFF_ID and event_type(event) == "removedebuff" and target_id in pending:
            applied = pending.pop(target_id)
            position, reliable = _position_state(position_index, target_id, timestamp)
            wind_side = _wind_side_from_position(position["x"], position["y"], arena) if position and arena else None
            placement_hits = _events_between(raw["damage"], timestamp - 250, timestamp + 350, {1306120})
            row = {
                "placementKey": f"{target_id}:{timestamp}",
                "assignmentTimestamp": int(applied["timestamp"]),
                "assignmentTimeMs": int(applied["timestamp"]) - fight["startTime"],
                "assignmentTime": fmt_ms(int(applied["timestamp"]) - fight["startTime"]),
                "applyTimestamp": timestamp,
                "placementTimestamp": timestamp,
                "timeMs": timestamp - fight["startTime"],
                "time": fmt_ms(timestamp - fight["startTime"]),
                **player_ref(players, actor_map, target_id),
                "position": position,
                "sampleOffsetMs": None,
                "positionReliable": reliable,
                "windSide": wind_side,
                "placementDamageCount": len(placement_hits),
                "activatedAtMs": None,
                "activatedTime": None,
                "activationConfidence": None,
                "activationEvidence": None,
                "consumedAtMs": None,
                "consumedTime": None,
                "active": True,
            }
            rows.append(row)
    volley_casts = _completed_casts(raw["casts"], CYST_VOLLEY_CAST_ID)
    for row in rows:
        assignment_ts = row["assignmentTimestamp"]
        volley = next((
            cast for cast in reversed(volley_casts)
            if 0 <= assignment_ts - int(cast["timestamp"]) <= CYST_ASSIGNMENT_AFTER_VOLLEY_MS
        ), None)
        if volley is None:
            continue
        volley_ts = int(volley["timestamp"])
        row["volleyTimestamp"] = volley_ts
        row["volleyTimeMs"] = volley_ts - fight["startTime"]
        row["volleyTime"] = fmt_ms(volley_ts - fight["startTime"])
    return rows


def _cyst_placements_for_dig(all_cysts, previous_dig_ts, dig_ts):
    """Select two Cyst Volley batches for one Burrow phase.

    A 1305959 cast assigns two players a few seconds apart. Those two players
    are one placement batch even though their aura removals are staggered.
    """
    volley_timestamps = sorted({
        row["volleyTimestamp"]
        for row in all_cysts
        if row.get("volleyTimestamp") is not None
        and previous_dig_ts <= row["volleyTimestamp"] <= dig_ts
    })[-2:]
    if volley_timestamps:
        selected = [
            dict(row) for row in all_cysts
            if row.get("volleyTimestamp") in volley_timestamps
        ]
        selected.sort(key=lambda row: (row["volleyTimestamp"], row["assignmentTimestamp"]))
        for wave, volley_ts in enumerate(volley_timestamps, start=1):
            wave_rows = [row for row in selected if row["volleyTimestamp"] == volley_ts]
            for target_order, row in enumerate(wave_rows, start=1):
                row["placementWave"] = wave
                row["volleyTargetOrder"] = target_order
        return selected

    # Compatibility for older/synthetic payloads that predate volley evidence.
    selected = [
        dict(row) for row in all_cysts
        if previous_dig_ts <= row["applyTimestamp"] <= dig_ts
    ][-4:]
    for index, row in enumerate(selected):
        row["placementWave"] = min(index // 2 + 1, 2)
        row["volleyTargetOrder"] = index % 2 + 1
    return selected

def _forced_movement_evidence(position_index, actor_map, players, timestamp, death_times):
    rows = []
    for player_id in players:
        death_time = death_times.get(player_id)
        if death_time is not None and timestamp >= death_time:
            continue
        before = position_at_interpolated(
            position_index, player_id, timestamp - 400, reliable_window_ms=POSITION_RELIABLE_MS,
        )
        after = position_at_interpolated(
            position_index, player_id, timestamp + 400, reliable_window_ms=POSITION_RELIABLE_MS,
        )
        if not before or not after or not before.get("reliable") or not after.get("reliable"):
            continue
        dx, dy = after["x"] - before["x"], after["y"] - before["y"]
        distance = math.hypot(dx, dy)
        if distance < KNOCKBACK_DISPLACEMENT:
            continue
        rows.append({
            **player_ref(players, actor_map, player_id),
            "distanceYards": round(distance / 100, 1),
            "dx": round(dx, 1),
            "dy": round(dy, 1),
        })
    return sorted(rows, key=lambda row: row["distanceYards"], reverse=True)

def _attribute_cyst_activations(
    fight, actor_map, players, raw, position_index, placements, death_times,
):
    aura_applies = [
        event for event in raw["debuffs"]
        if int(ability_id(event) or 0) == CYST_TRIGGER_DEBUFF_ID
        and event_type(event) == "applydebuff"
    ]
    activation_groups = group_nearby(aura_applies, window_ms=250)
    active = []
    placement_cursor = 0
    activations = []
    unmatched = []

    for activation_index, group in enumerate(activation_groups, start=1):
        timestamp = min(int(event["timestamp"]) for event in group)
        while placement_cursor < len(placements) and placements[placement_cursor]["placementTimestamp"] <= timestamp:
            active.append(placements[placement_cursor])
            placement_cursor += 1
        if not active:
            unmatched.append({
                "timeMs": timestamp - fight["startTime"],
                "time": fmt_ms(timestamp - fight["startTime"]),
                "auraApplyCount": len(group),
                "reason": "当时没有已放置且未激活的囊肿",
            })
            continue

        living_positions = []
        for player_id in players:
            death_time = death_times.get(player_id)
            if death_time is not None and timestamp >= death_time:
                continue
            state = position_at_interpolated(
                position_index, player_id, timestamp, reliable_window_ms=POSITION_RELIABLE_MS,
            )
            if not state or not state.get("reliable"):
                continue
            living_positions.append((player_id, state))

        distances = []
        for row in active:
            if not row.get("position") or not living_positions:
                continue
            nearest_player_id, nearest_state = min(
                living_positions,
                key=lambda item: math.hypot(
                    item[1]["x"] - row["position"]["x"],
                    item[1]["y"] - row["position"]["y"],
                ),
            )
            distance = math.hypot(
                nearest_state["x"] - row["position"]["x"],
                nearest_state["y"] - row["position"]["y"],
            ) / 100
            distances.append((distance, row, nearest_player_id))

        if distances:
            nearest_distance, cyst, nearest_player_id = min(distances, key=lambda item: item[0])
            confidence = "high" if nearest_distance <= 12 else "medium" if nearest_distance <= 25 else "low"
        else:
            # 没有可靠坐标时只保留激活证据，不猜测具体囊肿。
            unmatched.append({
                "timeMs": timestamp - fight["startTime"],
                "time": fmt_ms(timestamp - fight["startTime"]),
                "auraApplyCount": len(group),
                "reason": "缺少存活玩家的可靠坐标",
            })
            continue

        damage_hits = _events_between(
            raw["damage"], timestamp - 250, timestamp + 350, {CYST_TRIGGER_DEBUFF_ID},
        )
        forced_movements = _forced_movement_evidence(
            position_index, actor_map, players, timestamp, death_times,
        )
        relative_ms = timestamp - fight["startTime"]
        evidence = {
            "auraApplyCount": len(group),
            "damageHitCount": len(damage_hits),
            "forcedMovementCount": len(forced_movements),
            "forcedMovements": forced_movements,
            "nearestPlayer": player_ref(players, actor_map, nearest_player_id),
            "nearestDistanceYards": round(nearest_distance, 1),
        }
        cyst.update({
            "activatedAtMs": relative_ms,
            "activatedTime": fmt_ms(relative_ms),
            "activationConfidence": confidence,
            "activationEvidence": evidence,
            # 保留旧字段以兼容已有前端与离线 JSON。
            "consumedAtMs": relative_ms,
            "consumedTime": fmt_ms(relative_ms),
            "active": False,
            "consumeReason": "囊肿激活",
        })
        active.remove(cyst)
        activations.append({
            "index": activation_index,
            "timeMs": relative_ms,
            "time": fmt_ms(relative_ms),
            "placementKey": cyst["placementKey"],
            "playerID": cyst["playerID"],
            "player": cyst["player"],
            "confidence": confidence,
            **evidence,
        })
    return activations, unmatched

def _first_matching_event(events, *, target_id, spell_id, event_kind, start, end):
    return next((
        event for event in events
        if event.get("targetID") == target_id
        and int(ability_id(event) or 0) == spell_id
        and event_type(event) == event_kind
        and start <= int(event.get("timestamp") or 0) <= end
    ), None)

def _crosswind_mobility_uses(
    fight, actor_map, players, friendly_casts, player_id, launch_timestamp, resolution_timestamp,
):
    if launch_timestamp is None:
        return []
    end = resolution_timestamp if resolution_timestamp is not None else launch_timestamp + 10_000
    rows = []
    for event in friendly_casts:
        if event.get("sourceID") != player_id or event_type(event) != "cast":
            continue
        timestamp = int(event.get("timestamp") or 0)
        # 保留起飞前半秒的预按技能，并覆盖整个空中阶段。
        if not launch_timestamp - 500 <= timestamp <= end + 150:
            continue
        spell_id = int(ability_id(event) or 0)
        if spell_id not in CROSSWIND_MOBILITY_SPELLS:
            continue
        offset_ms = timestamp - launch_timestamp
        rows.append({
            "spellID": spell_id,
            "spellName": CROSSWIND_MOBILITY_SPELLS[spell_id],
            "source": player_ref(players, actor_map, player_id),
            "timeMs": timestamp - fight["startTime"],
            "time": fmt_ms(timestamp - fight["startTime"]),
            "offsetFromLaunchMs": offset_ms,
            "timingLabel": (
                f"起飞前 {abs(offset_ms) / 1000:.2f}s"
                if offset_ms < 0 else f"起飞后 {offset_ms / 1000:.2f}s"
            ),
            "target": player_ref(players, actor_map, event.get("targetID"))
            if event.get("targetID") in players else None,
        })
    return sorted(rows, key=lambda row: row["timeMs"])

def _crosswind_immunity_uses(
    fight, actor_map, players, friendly_casts, player_id, apply_timestamp, end_timestamp,
):
    rows = []
    for event in friendly_casts:
        if event.get("sourceID") != player_id or event_type(event) != "cast":
            continue
        timestamp = int(event.get("timestamp") or 0)
        spell_id = int(ability_id(event) or 0)
        if spell_id not in IMMUNITY_SPELLS or not apply_timestamp <= timestamp <= end_timestamp:
            continue
        offset_ms = timestamp - apply_timestamp
        rows.append({
            "spellID": spell_id,
            "spellName": IMMUNITY_SPELLS[spell_id],
            "source": player_ref(players, actor_map, player_id),
            "timeMs": timestamp - fight["startTime"],
            "time": fmt_ms(timestamp - fight["startTime"]),
            "offsetFromAssignmentMs": offset_ms,
            "timingLabel": f"点名后 {offset_ms / 1000:.2f}s",
        })
    return sorted(rows, key=lambda row: row["timeMs"])

def _sszorak_crosswind_waves(
    fight, actor_map, players, debuffs, friendly_casts, damage, deaths, position_index, arena,
):
    """Group one full Crosswinds assignment and prove its airborne collisions.

    1285425/1285453 are the two assignment directions. Their expiry applies
    1285447 (the airborne aura); opposite-direction players removing 1285447 in
    the same 120ms window is the direct collision evidence.
    """
    ordered_debuffs = sorted(debuffs, key=lambda row: int(row.get("timestamp") or 0))
    assignments = [
        event for event in ordered_debuffs
        if int(ability_id(event) or 0) in CROSSWIND_DIRECTIONS
        and event_type(event) == "applydebuff"
        and event.get("targetID") in players
    ]
    rows = []
    for round_index, group in enumerate(
        group_nearby(assignments, window_ms=CROSSWIND_ROUND_WINDOW_MS), start=1,
    ):
        targets = []
        for assignment in group:
            spell_id = int(ability_id(assignment) or 0)
            direction = CROSSWIND_DIRECTIONS[spell_id]
            target_id = assignment.get("targetID")
            apply_ts = int(assignment["timestamp"])
            assignment_remove = _first_matching_event(
                ordered_debuffs,
                target_id=target_id,
                spell_id=spell_id,
                event_kind="removedebuff",
                start=apply_ts,
                end=min(int(fight["endTime"]), apply_ts + 15_000),
            )
            assignment_remove_ts = int(assignment_remove["timestamp"]) if assignment_remove else None
            launch_apply = None
            if assignment_remove_ts is not None:
                launch_apply = _first_matching_event(
                    ordered_debuffs,
                    target_id=target_id,
                    spell_id=CROSSWIND_LAUNCH_DEBUFF_ID,
                    event_kind="applydebuff",
                    start=assignment_remove_ts - 100,
                    end=assignment_remove_ts + 500,
                )
            launch_ts = int(launch_apply["timestamp"]) if launch_apply else None
            launch_remove = None
            if launch_ts is not None:
                launch_remove = _first_matching_event(
                    ordered_debuffs,
                    target_id=target_id,
                    spell_id=CROSSWIND_LAUNCH_DEBUFF_ID,
                    event_kind="removedebuff",
                    start=launch_ts,
                    end=min(int(fight["endTime"]), launch_ts + 10_000),
                )
            resolution_ts = int(launch_remove["timestamp"]) if launch_remove else None
            position, reliable = _position_state(position_index, target_id, apply_ts)
            launch_position, launch_reliable = (
                _position_state(position_index, target_id, launch_ts) if launch_ts is not None else (None, False)
            )
            resolution_position, resolution_reliable = (
                _position_state(position_index, target_id, resolution_ts)
                if resolution_ts is not None else (None, False)
            )
            flight_probe_position, _ = (
                _position_state(
                    position_index,
                    target_id,
                    min(launch_ts + 800, resolution_ts or launch_ts + 800),
                ) if launch_ts is not None else (None, False)
            )
            arrow_angle = direction.get("angleDegrees")
            observed_flight_angle = None
            if launch_position and flight_probe_position:
                observed_flight_angle = _bearing_deg(
                    flight_probe_position["x"] - launch_position["x"],
                    flight_probe_position["y"] - launch_position["y"],
                )
                if arrow_angle is None:
                    arrow_angle = _asset_angle(observed_flight_angle)
            travel_yards = None
            if launch_position and resolution_position:
                travel_yards = round(math.hypot(
                    resolution_position["x"] - launch_position["x"],
                    resolution_position["y"] - launch_position["y"],
                ) / 100, 1)
            mobility_uses = _crosswind_mobility_uses(
                fight, actor_map, players, friendly_casts, target_id, launch_ts, resolution_ts,
            )
            immunity_uses = _crosswind_immunity_uses(
                fight,
                actor_map,
                players,
                friendly_casts,
                target_id,
                apply_ts,
                min(
                    int(fight["endTime"]),
                    (resolution_ts or launch_ts or assignment_remove_ts or apply_ts) + 2_000,
                ),
            )
            death_ts = min((
                int(event["timestamp"]) for event in deaths
                if event.get("targetID") == target_id
                and apply_ts <= int(event.get("timestamp") or 0) <= apply_ts + 15_000
            ), default=None)
            targets.append({
                "applyTimestamp": apply_ts,
                "applyTimeMs": apply_ts - fight["startTime"],
                "applyTime": fmt_ms(apply_ts - fight["startTime"]),
                "launchTimestamp": launch_ts,
                "launchTimeMs": launch_ts - fight["startTime"] if launch_ts is not None else None,
                "launchTime": fmt_ms(launch_ts - fight["startTime"]) if launch_ts is not None else None,
                "resolutionTimestamp": resolution_ts,
                "resolutionTimeMs": resolution_ts - fight["startTime"] if resolution_ts is not None else None,
                "resolutionTime": fmt_ms(resolution_ts - fight["startTime"]) if resolution_ts is not None else None,
                "airborneMs": resolution_ts - launch_ts
                if resolution_ts is not None and launch_ts is not None else None,
                "spellID": spell_id,
                **player_ref(players, actor_map, target_id),
                "position": position,
                "positionReliable": reliable,
                "launchPosition": launch_position,
                "launchPositionReliable": launch_reliable,
                "resolutionPosition": resolution_position,
                "resolutionPositionReliable": resolution_reliable,
                "travelDistanceYards": travel_yards,
                "circleRadiusYards": CROSSWIND_CIRCLE_YARDS,
                "directionGroup": direction["key"],
                "directionLabel": direction["label"],
                "arrowAngleDegrees": arrow_angle,
                "observedFlightAngleDegrees": round(observed_flight_angle, 1) if observed_flight_angle is not None else None,
                "mobilityUses": mobility_uses,
                "immunityUses": immunity_uses,
                "deathDuringAirborne": bool(
                    death_ts is not None and launch_ts is not None
                    and launch_ts <= death_ts <= (resolution_ts or launch_ts + 10_000)
                ),
                "deathAfterAssignment": bool(
                    death_ts is not None and apply_ts <= death_ts <= apply_ts + 15_000
                ),
                "collisionPartner": None,
                "resolution": "未找到起飞光环" if launch_ts is None else "未找到移除证据",
            })

        # 不以相近坐标猜测：只将相反方向且 1285447 在同一时间窗移除的玩家配为一次对撞。
        pairings = []
        paired_ids = set()
        group_a = [row for row in targets if row["directionGroup"] in {"A", "C"} and row["resolutionTimestamp"]]
        group_b = [row for row in targets if row["directionGroup"] in {"B", "D"} and row["resolutionTimestamp"]]
        for left in sorted(group_a, key=lambda row: row["resolutionTimestamp"]):
            candidates = [
                right for right in group_b
                if right["playerID"] not in paired_ids
                and right["directionGroup"] == {"A": "B", "C": "D"}[left["directionGroup"]]
                and abs(right["resolutionTimestamp"] - left["resolutionTimestamp"])
                <= CROSSWIND_COLLISION_WINDOW_MS
            ]
            if not candidates:
                continue
            right = min(candidates, key=lambda row: abs(row["resolutionTimestamp"] - left["resolutionTimestamp"]))
            paired_ids.update((left["playerID"], right["playerID"]))
            left["collisionPartner"] = player_ref(players, actor_map, right["playerID"])
            right["collisionPartner"] = player_ref(players, actor_map, left["playerID"])
            left["resolution"] = right["resolution"] = "与反方向玩家对撞消除"
            collision_ts = max(left["resolutionTimestamp"], right["resolutionTimestamp"])
            pairings.append({
                "timeMs": collision_ts - fight["startTime"],
                "time": fmt_ms(collision_ts - fight["startTime"]),
                "left": player_ref(players, actor_map, left["playerID"]),
                "right": player_ref(players, actor_map, right["playerID"]),
                "leftDirection": left["directionLabel"],
                "rightDirection": right["directionLabel"],
                "leftAirborneMs": left["airborneMs"],
                "rightAirborneMs": right["airborneMs"],
                "mobilityUses": left["mobilityUses"] + right["mobilityUses"],
            })
        for target in targets:
            if target["playerID"] in paired_ids:
                continue
            if target["deathDuringAirborne"]:
                target["resolution"] = "空中阶段死亡"
            elif target["launchTimestamp"] is None and target["immunityUses"]:
                target["resolution"] = "免疫解除（{}）".format(
                    "、".join(row["spellName"] for row in target["immunityUses"])
                )
            elif target["launchTimestamp"] is None and target["deathAfterAssignment"]:
                target["resolution"] = "点名后、起飞前死亡"
            elif target["airborneMs"] is not None and target["airborneMs"] >= 5_500:
                target["resolution"] = f'超时移除（{target["airborneMs"] / 1000:.2f}s）'
            elif target["resolutionTimestamp"] is not None:
                target["resolution"] = "单独移除，未找到反方向同窗玩家"

        assigned_ids = {row["playerID"] for row in targets}
        launch_floor = min((row["launchTimestamp"] for row in targets if row["launchTimestamp"]), default=None)
        launch_ceiling = max((row["launchTimestamp"] for row in targets if row["launchTimestamp"]), default=None)
        collateral = []
        if launch_floor is not None and launch_ceiling is not None:
            for hit in _events_between(
                damage, launch_floor - 500, launch_ceiling + 2_000, CROSSWIND_DAMAGE_IDS,
            ):
                victim_id = hit.get("targetID")
                if victim_id not in players or victim_id in assigned_ids:
                    continue
                hit_timestamp = int(hit.get("timestamp") or 0)
                source_row = next((row for row in targets if row["playerID"] == hit.get("sourceID")), None)
                victim_position, _ = _position_state(position_index, victim_id, hit_timestamp)
                if source_row is None and victim_position:
                    candidates = [row for row in targets if row.get("launchPosition")]
                    if candidates:
                        source_row = min(candidates, key=lambda row: math.hypot(
                            victim_position["x"] - row["launchPosition"]["x"],
                            victim_position["y"] - row["launchPosition"]["y"],
                        ))
                nearest_distance = None
                if source_row and victim_position and source_row.get("launchPosition"):
                    nearest_distance = round(math.hypot(
                        victim_position["x"] - source_row["launchPosition"]["x"],
                        victim_position["y"] - source_row["launchPosition"]["y"],
                    ) / 100, 1)
                collateral.append({
                    **player_ref(players, actor_map, victim_id),
                    "timeMs": hit_timestamp - fight["startTime"],
                    "time": fmt_ms(hit_timestamp - fight["startTime"]),
                    "spellID": int(ability_id(hit) or 0),
                    "amount": event_amount(hit),
                    "sourceTarget": player_ref(players, actor_map, source_row["playerID"]) if source_row else None,
                    "distanceYards": nearest_distance,
                })

        targets.sort(key=lambda row: (row["directionGroup"], row["applyTimestamp"], row["playerID"]))
        apply_ts = min(row["applyTimestamp"] for row in targets)
        launch_times = [row["launchTimestamp"] for row in targets if row["launchTimestamp"] is not None]
        resolution_times = [row["resolutionTimestamp"] for row in targets if row["resolutionTimestamp"] is not None]
        end_ts = max(resolution_times or launch_times or [apply_ts])
        direction_groups = []
        for spell_id, direction in CROSSWIND_DIRECTIONS.items():
            direction_targets = [row for row in targets if row["spellID"] == spell_id]
            if direction_targets:
                direction_groups.append({
                    "key": direction["key"],
                    "spellID": spell_id,
                    "label": direction["label"],
                    "targets": direction_targets,
                    "targetCount": len(direction_targets),
                })
        rows.append({
            "index": round_index,
            "timeMs": end_ts - fight["startTime"],
            "time": fmt_ms(end_ts - fight["startTime"]),
            "applyTimeMs": apply_ts - fight["startTime"],
            "applyTime": fmt_ms(apply_ts - fight["startTime"]),
            "launchTimeMs": min(launch_times) - fight["startTime"] if launch_times else None,
            "launchTime": fmt_ms(min(launch_times) - fight["startTime"]) if launch_times else None,
            "directionGroup": "+".join(group["key"] for group in direction_groups),
            "inferredDirection": "骷髅 ↔ 红叉；三角 ↔ 紫菱" if any(group["key"] in {"C", "D"} for group in direction_groups) else "骷髅 ↔ 红叉",
            "axes": [{"label": "骷髅 ↔ 红叉", "angleDegrees": CROSSWIND_DIRECTIONS[1285425]["angleDegrees"]}]
                    + ([{"label": "三角 ↔ 紫菱", "angleDegrees": CROSSWIND_DIRECTIONS[1297096]["angleDegrees"]}]
                       if any(group["key"] in {"C", "D"} for group in direction_groups) else []),
            "arrowAngleDegrees": CROSSWIND_DIRECTIONS[1285425]["angleDegrees"],
            "wclAngleDegrees": CROSSWIND_DIRECTIONS[1285425]["wclAngleDegrees"],
            "targets": targets,
            "directionGroups": direction_groups,
            "pairings": sorted(pairings, key=lambda row: row["timeMs"]),
            "targetCount": len(targets),
            "resolvedCount": len(paired_ids),
            "unresolvedCount": len(targets) - len(paired_ids),
            "mobilityUseCount": sum(len(row["mobilityUses"]) for row in targets),
            "immunityUseCount": sum(len(row["immunityUses"]) for row in targets),
            "collateralHits": collateral,
            "collateralHitCount": len(collateral),
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

def _tempest_aura_counts(fight, actor_map, players, raw):
    applications, dispels = [], []
    seen = set()
    for event in sorted(raw.get("debuffs", []) + raw.get("trackedActorEvents", []), key=lambda e: e["timestamp"]):
        kind, target = event_type(event), event.get("targetID")
        if target not in players:
            continue
        is_apply = ability_id(event) == TEMPEST_DEBUFF_ID and kind in {"applydebuff", "applydebuffstack", "refreshdebuff"}
        is_dispel = kind == "dispel" and event.get("extraAbilityGameID") == TEMPEST_DEBUFF_ID
        if not (is_apply or is_dispel):
            continue
        key = (event["timestamp"], kind, event.get("sourceID"), target, ability_id(event), event.get("stack"))
        if key in seen:
            continue
        seen.add(key)
        row = {**player_ref(players, actor_map, target), "timeMs": event["timestamp"] - fight["startTime"],
               "time": fmt_ms(event["timestamp"] - fight["startTime"]), "eventType": kind,
               "spellID": TEMPEST_DEBUFF_ID}
        if is_dispel:
            source = event.get("sourceID")
            # 图腾等宠物的驱散保留实体，同时归到主人名下。
            owner = raw.get("petOwners", {}).get(source, source)
            row.update({"dispelSourceID": source, "dispelSpellID": ability_id(event),
                        "dispeller": player_ref(players, actor_map, owner)})
        (applications if is_apply else dispels).append(row)
    ids = {row["playerID"] for row in applications} | {
        row["dispeller"]["playerID"] for row in dispels if row["dispeller"]["playerID"] in players
    }
    return {"applications": applications, "dispels": dispels,
            "applicationCount": len(applications), "dispelCount": len(dispels),
            "players": [{**player_ref(players, actor_map, pid),
                         "applicationCount": sum(row["playerID"] == pid for row in applications),
                         "dispelCount": sum(row["dispeller"]["playerID"] == pid for row in dispels)} for pid in sorted(ids)]}


def _serpents_fury(fight, actor_map, players, raw, position_index):
    result = {"enabled": True, "requiredPlayers": FURY_REQUIRED_PLAYERS, "radiusYards": FURY_SOAK_RADIUS_YARDS,
              "events": [], "players": [], "enrageCount": 0, "exemptCount": 0,
              "evidenceNote": "仅统计史诗未击杀 Pull 的怒不可遏施加；结算前全团死亡超过 3 人豁免。排除所有治疗者，其他存活玩家以印记目标 8 码范围判定，双方坐标须在 500ms 内，缺失坐标不计圈外。"}
    if int(fight.get("difficulty") or 0) != 5 or fight.get("kill"):
        return result
    boss_id = raw.get("bossID")
    enrages = sorted({int(e["timestamp"]) for e in raw.get("enemyBuffs", [])
                      if ability_id(e) == UNBOUND_FEROCITY_ID and event_type(e) == "applybuff"
                      and (boss_id is None or e.get("targetID") == boss_id)})
    marks = sorted([e for e in raw.get("debuffs", []) if ability_id(e) == SERPENTS_FURY_MARK_ID], key=lambda e: e["timestamp"])
    life_events = sorted(raw.get("deaths", []) + [e for e in raw.get("trackedActorEvents", []) if event_type(e) == "resurrect"],
                         key=lambda e: e["timestamp"])
    misses = Counter()
    for timestamp in enrages:
        dead = set()
        for event in life_events:
            if int(event["timestamp"]) >= timestamp:
                break
            pid = event.get("targetID")
            if pid not in players:
                continue
            if event_type(event) == "death":
                dead.add(pid)
            elif event_type(event) == "resurrect":
                dead.discard(pid)
        active = {}
        for event in marks:
            if int(event["timestamp"]) >= timestamp:
                break
            pid = event.get("targetID")
            if event_type(event) in {"applydebuff", "refreshdebuff"}:
                active[pid] = event["timestamp"]
            elif event_type(event) == "removedebuff":
                active.pop(pid, None)
        target = next(iter(active)) if len(active) == 1 else None
        row = {"timeMs": timestamp - fight["startTime"], "time": fmt_ms(timestamp - fight["startTime"]),
               "spellID": UNBOUND_FEROCITY_ID, "deadCount": len(dead), "exempt": len(dead) > 3,
               "markTarget": player_ref(players, actor_map, target) if target is not None else None,
               "outsidePlayers": [], "insidePlayers": [], "unknownPlayers": [],
               "excludedHealers": [player_ref(players, actor_map, pid) for pid, p in players.items() if str(p.get("role") or "").endswith("healer")]}
        if row["exempt"]:
            row["status"] = "死亡超过 3 人，豁免"
        else:
            mark_position = position_at_interpolated(position_index, target, timestamp - 1, reliable_window_ms=FURY_POSITION_WINDOW_MS) if target not in dead else None
            for pid in players:
                if pid in dead or str(players[pid].get("role") or "").endswith("healer"):
                    continue
                ref = player_ref(players, actor_map, pid)
                point = position_at_interpolated(position_index, pid, timestamp - 1, reliable_window_ms=FURY_POSITION_WINDOW_MS)
                if not mark_position or not mark_position.get("reliable") or not point or not point.get("reliable"):
                    row["unknownPlayers"].append(ref)
                    continue
                distance = math.hypot(point["x"] - mark_position["x"], point["y"] - mark_position["y"])/100
                ref.update({"distanceYards": round(distance, 2), "sampleOffsetMs": point["sampleOffsetMs"],
                            "markSampleOffsetMs": mark_position["sampleOffsetMs"]})
                row["insidePlayers" if distance <= FURY_SOAK_RADIUS_YARDS else "outsidePlayers"].append(ref)
                if distance > FURY_SOAK_RADIUS_YARDS:
                    misses[pid] += 1
            row["status"] = "坐标证据不足，部分或全部未确认" if row["unknownPlayers"] else "已按狂暴前位置结算"
        row["insideCount"] = len(row["insidePlayers"])
        row["outsideCount"] = len(row["outsidePlayers"])
        row["unknownCount"] = len(row["unknownPlayers"])
        result["events"].append(row)
    result["enrageCount"] = len(enrages)
    result["exemptCount"] = sum(row["exempt"] for row in result["events"])
    result["players"] = [{**player_ref(players, actor_map, pid), "count": count} for pid, count in misses.most_common()]
    return result


def analyze_sszorak(fight, actor_map, players, raw):
    casts, damage, debuffs = raw["casts"], raw["damage"], raw["debuffs"]
    options = resolve_analysis_options(CONFIG_SCHEMA, raw.get("analysisOptions") or {})
    deaths = raw["deaths"]
    death_times = _first_death_times(deaths, players)
    tank_ids = {player_id for player_id, player in players.items() if player.get("role") == "tank"}

    sequence = []
    for cycle_index, cycle in enumerate(_predator_cycles(casts) if options["predatorReviewEnabled"] else [], start=1):
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

    tempest = _avoidable_board(fight, actor_map, players, damage, deaths, {1287083: spell_name(1287083)}) if options["tempestReviewEnabled"] else []
    tempest_auras = _tempest_aura_counts(fight, actor_map, players, raw) if options["tempestReviewEnabled"] else {"enabled": False}
    fury_enabled = options["serpentsFuryReviewEnabled"] and int(fight.get("difficulty") or 0) == 5
    if not fury_enabled and not any(options[key] for key in ("fieldReplayEnabled", "cystsReviewEnabled", "crosswindsReviewEnabled")):
        return {"apexPredator": {"cycles": len(_predator_cycles(casts)), "sequence": sequence, "tempestDamage": tempest},
                "tempest": tempest_auras, "serpentsFury": {"enabled": False},
                "cysts": {"enabled": False}, "crosswinds": {"enabled": False},
                "fieldReplay": {"enabled": False}, "fallDeaths": []}
    boss_id = raw.get("bossID")
    combat_position_index = build_position_index(raw.get("bossPositionEvents", []) + raw["resources"] + damage + debuffs)
    position_index = _sszorak_map_position_index(combat_position_index)
    fury = _serpents_fury(fight, actor_map, players, raw, position_index) if fury_enabled else {"enabled": False}
    arena = _sszorak_arena(position_index, boss_id=boss_id)

    all_cysts = _sszorak_cysts(fight, actor_map, players, raw, position_index, arena) if options["cystsReviewEnabled"] or options["fieldReplayEnabled"] else []
    cyst_activations, unmatched_activations = _attribute_cyst_activations(
        fight, actor_map, players, raw, position_index, all_cysts, death_times,
    ) if all_cysts else ([], [])
    digs = _completed_casts(casts, 1286033) if options["cystsReviewEnabled"] or options["fieldReplayEnabled"] else []
    cyst_rounds = []
    replay_rounds = []
    for index, dig in enumerate(digs, start=1):
        timestamp = int(dig["timestamp"])
        previous = int(digs[index - 2]["timestamp"]) if index > 1 else int(fight["startTime"])
        placements = _cyst_placements_for_dig(all_cysts, previous, timestamp)
        for slot, row in enumerate(placements, start=1):
            row["slot"] = slot

        wind_end = timestamp + DIG_DURATION_MS
        # 回放窗口延到本轮最后一个囊肿被撞后 2 秒（第四个囊肿常在掘地结束后才被撞），
        # 但不越过下一轮掘地或战斗结束；风向推断仍只用 25s 掘地固守窗口内的帧。
        round_placement_keys = {row["placementKey"] for row in placements}
        round_activation_abs = [
            fight["startTime"] + row["activatedAtMs"]
            for row in all_cysts
            if row.get("activatedAtMs") is not None
            and row["placementKey"] in round_placement_keys
        ]
        replay_end = max(wind_end, max(round_activation_abs, default=wind_end) + REPLAY_TAIL_AFTER_CYST_MS)
        if index + 1 < len(digs):
            replay_end = min(replay_end, int(digs[index + 1]["timestamp"]))
        replay_end = min(replay_end, int(fight["endTime"]))
        wind_frames = _player_positions_over_window(
            position_index,
            players,
            timestamp,
            wind_end,
            step_ms=REPLAY_STEP_MS,
            death_times=death_times,
        )
        frames = _player_positions_over_window(
            position_index,
            players,
            timestamp,
            replay_end,
            step_ms=REPLAY_STEP_MS,
            death_times=death_times,
        ) if options["fieldReplayEnabled"] else []
        activation_rows = [
            {
                **row,
                "activatedTimestamp": fight["startTime"] + row["activatedAtMs"],
            }
            for row in all_cysts
            if row.get("activatedAtMs") is not None
            and timestamp <= fight["startTime"] + row["activatedAtMs"] <= wind_end
        ]
        winds = _infer_dig_winds(
            wind_frames, arena, segment_count=3, activation_rows=activation_rows,
        )
        validated = _placement_slot_validation(placements, winds)
        cyst_rounds.append({
            "index": index,
            "time": fmt_ms(timestamp - fight["startTime"]),
            "placements": validated,
            "windsComplete": len([wind for wind in winds if wind]) >= 3,
        })
        if options["fieldReplayEnabled"]:
            replay_rounds.append({
                "index": index,
                "timeMs": timestamp - fight["startTime"],
                "time": fmt_ms(timestamp - fight["startTime"]),
                "durationSec": DIG_DURATION_MS / 1000,
                "windowSec": round((replay_end - timestamp) / 1000, 1),
                "placements": validated,
                "winds": winds,
                "windsComplete": len([wind for wind in winds if wind]) >= 3,
                "wind": winds[0] if winds else None,
                "frames": [{
                    "timeMs": frame["timeMs"] - fight["startTime"],
                    "time": fmt_ms(frame["timeMs"] - fight["startTime"]),
                    "players": [{**player_ref(players, actor_map, player_id), **frame_player}
                                 for player_id, frame_player in zip(players, frame["players"])],
                } for frame in frames],
            })

    crosswind_waves = _sszorak_crosswind_waves(
        fight,
        actor_map,
        players,
        debuffs,
        raw.get("friendlyCasts", []),
        damage,
        deaths,
        position_index,
        arena,
    ) if options["crosswindsReviewEnabled"] or options["fieldReplayEnabled"] else []
    crosswind_rows = [{
        "timeMs": wave["timeMs"], "time": wave["time"],
        "applyTimeMs": wave["applyTimeMs"], "applyTime": wave["applyTime"],
        "spellIDs": sorted({row["spellID"] for row in wave.get("targets", [])}),
        "directionGroup": wave["directionGroup"],
        "inferredDirection": wave["inferredDirection"],
        "arrowAngleDegrees": wave["arrowAngleDegrees"],
        "targetCount": wave["targetCount"],
        "resolvedCount": wave["resolvedCount"],
        "unresolvedCount": wave["unresolvedCount"],
    } for wave in crosswind_waves]

    fall_deaths = [{
        **player_ref(players, actor_map, event.get("targetID")),
        "timeMs": int(event["timestamp"] - fight["startTime"]),
        "time": fmt_ms(int(event["timestamp"] - fight["startTime"])),
        "cause": spell_name(int(event.get("killingAbilityGameID") or 0)) if event.get("killingAbilityGameID") else "跌落",
        "note": "未记录致死技能，通常为掘地固守吹风或狂怒侧风导致跌落",
    } for event in deaths if event.get("targetID") in players and not event.get("killingAbilityGameID")]

    # 场地中心使用已确认的 Boss 出生点，不再使用会随 Boss 移动漂移的全程中位数。
    boss_center = {"x": arena["centerX"], "y": arena["centerY"]}

    return {
        "apexPredator": {"cycles": len(_predator_cycles(casts)), "sequence": sequence, "tempestDamage": tempest},
        "tempest": tempest_auras,
        "serpentsFury": fury,
        "cysts": {
            "rounds": cyst_rounds,
            "placements": all_cysts,
            "activations": cyst_activations,
            "unmatchedActivations": unmatched_activations,
        } if options["cystsReviewEnabled"] else {"enabled": False},
        "crosswinds": {"waves": crosswind_waves, "players": crosswind_rows} if options["crosswindsReviewEnabled"] else {"enabled": False},
        "fieldReplay": {
            "enabled": options["fieldReplayEnabled"],
            "arena": arena,
            "arenaImage": BOSS_CONFIG["arena"],
            "bossIcon": BOSS_CONFIG["bossIcon"],
            "bossCenter": boss_center,
            "frameStepMs": REPLAY_STEP_MS,
            "rounds": replay_rounds,
            "crosswindWaves": crosswind_waves,
            "evidenceNote": "使用校正后的 RaidPlan 原图；WCL 轨迹旋转 60° 后映射到六个风口、三条对穿轴（12 点与 6 点是入口）；掘地固守 25 秒内按 200ms 插值采样，回放窗口延至本轮最后一个囊肿被撞后 2 秒；玩家死亡后停止位置预估；囊肿按光环、伤害、受迫位移和最近存活玩家证据激活后隐藏。",
        },
        "fallDeaths": fall_deaths,
    }

analyze_mechanics = analyze_sszorak


def _mechanic_overview(rendered):
    bad_cysts = []
    storm_applications, storm_dispels, fury_misses = [], [], []
    fury_enrages = fury_exempt = 0
    for pull in rendered:
        mechanics = pull.get(BOSS_CONFIG["key"]) or {}
        for round_row in (mechanics.get("cysts") or {}).get("rounds") or []:
            for placement in round_row.get("placements") or []:
                if placement.get("placementOk") is not False:
                    continue
                bad_cysts.append(nightly_detail(
                    pull, placement.get("time"),
                    f"{placement.get('player') or '未知玩家'} 囊肿放置错误：{placement.get('expected') or '未落在本轮要求位置'}",
                    player=placement.get("player"), classColor=placement.get("classColor"),
                ))
        for field, output, label in (("applications", storm_applications, "被施加风暴"), ("dispels", storm_dispels, "主动驱散风暴")):
            for event in (mechanics.get("tempest") or {}).get(field, []):
                credited = event["dispeller"] if field == "dispels" else event
                detail = f"{credited['player']} {label}"
                if field == "dispels":
                    detail += f"（目标：{event['player']}）"
                output.append(nightly_detail(pull, event.get("time"), detail,
                                            player=credited["player"], classColor=credited.get("classColor"),
                                            playerID=credited["playerID"], spellID=TEMPEST_DEBUFF_ID,
                                            targetPlayer=event["player"], targetPlayerID=event["playerID"],
                                            dispeller=event.get("dispeller"), eventType=event.get("eventType")))
        for event in (mechanics.get("serpentsFury") or {}).get("events", []):
            fury_enrages += 1
            fury_exempt += int(event["exempt"])
            for player_row in event["outsidePlayers"]:
                fury_misses.append(nightly_detail(pull, event["time"],
                    f"{player_row['player']} 怒满狂暴时未在印记 8 码内（{player_row['distanceYards']} 码）",
                    player=player_row["player"], playerID=player_row["playerID"], classColor=player_row.get("classColor"),
                    spellID=UNBOUND_FEROCITY_ID, distanceYards=player_row["distanceYards"]))
    return {
        "title": "整夜机制统计",
        "subtitle": "按所有 Pull 汇总囊肿、风暴施加与驱散、史诗印记未进圈次数。",
        "metrics": [
            {
                "key": "badCystPlacements", "label": "囊肿放置错误", "value": len(bad_cysts), "unit": "次",
                "tone": "danger", "description": "只统计已有坐标和风向证据、明确判定 placementOk=false 的放置。",
                "players": nightly_player_totals(bad_cysts), "events": bad_cysts,
            },
            {
                "key": "stormApplications", "label": "风暴施加", "value": len(storm_applications), "unit": "次",
                "tone": "warning", "description": "统计风暴光环的首次施加、叠层与刷新，不统计持续伤害跳数。",
                "players": nightly_player_totals(storm_applications), "events": storm_applications,
            },
            {
                "key": "stormDispels", "label": "主动驱散风暴", "value": len(storm_dispels), "unit": "次",
                "tone": "info", "description": "按实际驱散者统计成功驱散风暴的事件次数；图腾等宠物归属主人，自然消失与死亡移除不计。",
                "players": nightly_player_totals(storm_dispels), "events": storm_dispels,
            },
            {
                "key": "furyOutside", "label": "怒满时未进印记", "value": len(fury_misses), "unit": "次",
                "tone": "danger", "description": "仅计存活非治疗玩家，印记半径 8 码；全团死亡超过 3 人豁免，坐标不足不计。",
                "enrageCount": fury_enrages, "exemptCount": fury_exempt,
                "players": nightly_player_totals(fury_misses), "events": fury_misses,
            },
        ],
    }


def build_aggregated_json(report_ids, options=None):
    options = resolve_analysis_options(CONFIG_SCHEMA, options or {})
    config = deepcopy(BOSS_CONFIG)
    spatial = any(options[key] for key in ("fieldReplayEnabled", "cystsReviewEnabled", "crosswindsReviewEnabled", "serpentsFuryReviewEnabled"))
    config["fetchPositionResources"] = spatial
    config["fetchEventResources"] = spatial
    config["features"]["fieldReplay"] = options["fieldReplayEnabled"]
    tab_enabled = {"survival": True, "predator": options["predatorReviewEnabled"] or options["tempestReviewEnabled"],
                   "replay": options["fieldReplayEnabled"], "cysts": options["cystsReviewEnabled"],
                   "crosswinds": options["crosswindsReviewEnabled"], "fury": options["serpentsFuryReviewEnabled"]}
    config["tabs"] = [row for row in config["tabs"] if tab_enabled.get(row[0], False)]
    config["fetchKeys"] = {"friendlyCasts", "deaths", "combatants"}
    if any(options.values()):
        config["fetchKeys"].update({"casts", "damage"})
    if spatial or options["tempestReviewEnabled"]:
        config["fetchKeys"].add("debuffs")
    filters = []
    if options["tempestReviewEnabled"]:
        filters.append("type = 'dispel'")
    if options["serpentsFuryReviewEnabled"]:
        config["fetchKeys"].add("enemyBuffs")
        filters.append("type = 'resurrect'")
    config["trackedActorEventFilters"] = [" OR ".join(filters)] if filters else []
    config["skippedAnalyses"] = [field["label"] for field in CONFIG_SCHEMA if not options[field["key"]]]
    result = _build(config, analyze_mechanics, report_ids, options)
    result["data"]["mechanicOverview"] = _mechanic_overview(
        result.get("data", {}).get("page1_wipeAnalysis") or []
    )
    if not options["cystsReviewEnabled"]:
        result["data"]["mechanicOverview"]["metrics"] = [row for row in result["data"]["mechanicOverview"]["metrics"] if row["key"] != "badCystPlacements"]
    if not options["tempestReviewEnabled"]:
        result["data"]["mechanicOverview"]["metrics"] = [row for row in result["data"]["mechanicOverview"]["metrics"] if row["key"] not in {"stormApplications", "stormDispels"}]
    if not options["serpentsFuryReviewEnabled"]:
        result["data"]["mechanicOverview"]["metrics"] = [row for row in result["data"]["mechanicOverview"]["metrics"] if row["key"] != "furyOutside"]
    return result


def analyze(report_ids, output_path=None, catalog_entry=None, options=None, progress_callback=None):
    return write_json_result(
        build_aggregated_json(report_ids, options), output_path, catalog_entry=catalog_entry
    )
