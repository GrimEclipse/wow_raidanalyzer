"""Evidence-first analyzer for The Coiled Altar / 盘卷祭坛 (12.1 heroic)."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from analyzer_core.analysis_scope import filter_fights
from analyzer_core.concurrency import run_parallel_indexed
from analyzer_core.progress import emit_progress
from analyzer_core.wcl_api import WclClient
from boss_plugins.assets.icons import get_boss_icon_path
from boss_plugins.common import COMBAT_RES_SPELLS, role_to_basic, write_json_result
from boss_plugins.venomous_abyss.shared import (
    ability_id,
    actor_name,
    build_player_catalog,
    build_position_index,
    build_survival_timeline,
    difficulty_fields,
    event_amount,
    event_point,
    event_type,
    fmt_ms,
    group_nearby,
    load_confirmed_spell_names,
    nightly_detail,
    nightly_player_totals,
    player_ref,
    position_actor_id,
    position_at,
    position_at_interpolated,
    resolve_boss_actor_id,
    spell_name,
)


ENCOUNTER_ID = 3429
ENCOUNTER_IDS = {ENCOUNTER_ID}
CN_TZ = timezone(timedelta(hours=8))
ARENA_IMAGE = "assets/raids/venomous_abyss/07-coiledaltar.jpg"
# 07-coiledaltar.jpg 为 1997×1118；图中正方形石台边长约 1036px，对齐整场地正方形。
ARENA_IMAGE_WIDTH = 1997
ARENA_IMAGE_HEIGHT = 1118
ARENA_SQUARE_PX = 1036
# 整场地约边长 110 坐标单位 ≈ 86 码；Boss 出生点 (0, 1158) 为石台中心。
# WCL 事件坐标 = 坐标单位 × 100。
ARENA_SIDE_UNITS = 110.0
ARENA_SIDE_YARDS = 86.0
ARENA_HALF_SIDE_UNITS = ARENA_SIDE_UNITS / 2.0
ARENA_HALF_SIDE_YARDS = ARENA_SIDE_YARDS / 2.0
ARENA_CENTER_X_UNITS = 0.0
ARENA_CENTER_Y_UNITS = 1158.0
# 兼容旧字段名（值仍是坐标单位，不是码）。
ARENA_CENTER_X_YARDS = ARENA_CENTER_X_UNITS
ARENA_CENTER_Y_YARDS = ARENA_CENTER_Y_UNITS
WCL_COORD_SCALE = 100.0
WCL_UNITS_PER_YARD = WCL_COORD_SCALE * ARENA_SIDE_UNITS / ARENA_SIDE_YARDS
# plotScale 表示「中心到正方形直角边」占示意图宽/高的百分比，故 X/Y 不同以保持圆形半径为正圆。
ARENA_PLOT_SCALE_X = round((ARENA_SQUARE_PX / 2) / ARENA_IMAGE_WIDTH * 100, 4)
ARENA_PLOT_SCALE_Y = round((ARENA_SQUARE_PX / 2) / ARENA_IMAGE_HEIGHT * 100, 4)

SPELLS = load_confirmed_spell_names()
SPELLS.update({
    1243002: "死亡进军",
    1236616: "圣光潜力",
    1236994: "鲁莽药水",
    1282403: "凝结毒液",
    1282408: "凝结毒液",
    1282419: "不稳定毒液",
    1283485: "处斩",
    1283489: "处斩",
    1283594: "处斩",
    1283623: "寡妇之吻",
    1283631: "寡妇之触",
    1285643: "恐惧行军",
    1285847: "坚不可摧",
    1285911: "凝视",
    1286620: "灵魂撕裂",
    1286837: "墓缚",
    1286895: "幽暗炸弹",
    1286912: "永恒夜幕护盾",
    1286918: "永恒夜幕",
    1310752: "永恒夜幕",
    1287718: "收回精华",
    1287722: "灵魂抹除",
    1289798: "灵魂绑定",
    1295132: "液态光泽",
    1297445: "恐惧行军",
    1297906: "墓缚",
    1299266: "冷酷处斩",
    1299267: "冷酷处斩",
    1299396: "死亡之拥",
    1299401: "死亡低语",
    1299684: "撕裂",
    1299838: "毒液爆裂",
    1299960: "剧毒洪流",
    1301690: "撕裂",
    1304032: "灵魂绑定",
    1304033: "幽魂再生",
    1307184: "恐惧箭",
    1307279: "枯萎之刃",
    1307292: "凋零撕裂",
    1307403: "凋零撕裂",
    1307425: "处斩",
    1307652: "冷酷处斩",
    1307959: "灵魂撕裂",
    1310732: "恶毒共鸣",
    1310744: "恶毒共鸣",
    1310881: "幽暗炸弹",
    1310882: "幽暗炸弹",
    1312132: "恶毒共鸣",
})

TOXIC_DELUGE = 1299960
COALESCED_VENOM_CAST = 1282403
COALESCED_VENOM_DAMAGE = 1282408
VOLATILE_VENOM = 1282419
# 掉落后短时间内再被捡起 → 视为接力搬运，中间落点不算「场上凝结毒液」。
VENOM_TRANSFER_WINDOW_MS = 1_500
# 游戏内毒液球拾取约 3 码；匹配阈值略放宽以吸收 WCL 坐标采样误差。
VENOM_PICKUP_MAX_YARDS = 4.0
SEVER_IDS = {1299684}
BLIGHTED_SEVER_IDS = {1307292}
CONE_SEVER_IDS = SEVER_IDS | BLIGHTED_SEVER_IDS
SOUL_SEVER_IDS = {1286620}
# 坦克易伤 / 结算 debuff：朝向按施加时刻（≈读条末秒）的坦克位置锁定。
SEVER_TANK_DEBUFF_IDS = {1301690}
BLIGHTED_SEVER_TANK_DEBUFF_IDS = {1307403}
SOUL_SEVER_TANK_DEBUFF_IDS = {1307959}
# 灵魂撕裂后判定凝视是否被清掉的观察窗口。
SOUL_SEVER_CLEAR_WINDOW_MS = 2_500
CAST_TO_TANK_DEBUFF_IDS = {
    1299684: SEVER_TANK_DEBUFF_IDS,
    1307292: BLIGHTED_SEVER_TANK_DEBUFF_IDS,
    1286620: SOUL_SEVER_TANK_DEBUFF_IDS,
}
CAST_LAST_SECOND_MS = 1_000
GUILLOTINE_CAST_IDS = {1283489}
GRIM_GUILLOTINE_CAST_IDS = {1299266, 1299267}
GUILLOTINE_DAMAGE_ID = 1283594
GRIM_GUILLOTINE_DAMAGE_IDS = {1283594, 1299266, 1299267}
GUILLOTINE_MARK = 1307425
GRIM_GUILLOTINE_MARK_IDS = {1307425, 1307652}
# P1 处斩后：全团寡妇之触；仍在分摊点 40 码内者额外吃寡妇之吻。
WIDOW_TOUCH_DAMAGE_ID = 1283631
WIDOW_KISS_DAMAGE_ID = 1283623
# P3 冷酷处斩后：全团死亡低语；范围内额外死亡之拥。
DEATH_WHISPER_DAMAGE_ID = 1299401
DEATH_EMBRACE_DAMAGE_ID = 1299396
# 分摊后查找脉冲/范围内伤害的最长等待；不再用固定秒数估位置。
GUILLOTINE_PULSE_SEARCH_MS = 25_000
GUILLOTINE_PULSE_MATCH_MS = 1_500
GUILLOTINE_RANGE_YARDS = 40
VENOM_RUPTURE = 1299838
FIXATION = 1285911
MANIFEST_NPC_GAME_ID = 261218
MANIFEST_CAST = 1290316
DREADMARCH_CAST_IDS = {1285643, 1243002}
DREADMARCH_DEBUFF_IDS = {1297445}
# 具象碰撞结果（仅史诗：恶毒共鸣 Malevolent Resonance）；英雄不做该证据。
MANIFEST_COLLISION_DEBUFF_IDS = {1310732, 1310744, 1312132}
# Boss 点名波次：施法后短窗口内的施加视为初始心控，而非撞具象。
DREADMARCH_INITIAL_APPLY_MS = 5_000
DREADMARCH_FIXATION_HINT_MS = 3_000
GLOOMBOMB_CAST_IDS = {1286895, 1310882}
GLOOMBOMB_DEBUFF_IDS = {1310881}
GRAVEBOUND_IDS = {1286837, 1308330}
GRAVEBOUND_DEBUFF_IDS = {1286837}
# 墓缚伤害致死（WCL 死亡归因 / DamageTaken）。killingAbility 缺失时用 overkill 回退。
GRAVEBOUND_DAMAGE_IDS = {1308330, 1297906, 1286837}
GRAVEBOUND_KILL_OVERKILL_WINDOW_MS = 250
# 炸弹爆炸后短窗口内的 1286837 施加，视为本次幽暗炸弹溅射。
GLOOMBOMB_GRAVEBOUND_WINDOW_MS = 2_000
ETERNAL_NIGHTFALL = 1286918
ETERNAL_NIGHTFALL_AURA = 1310752
VEIL_SHIELD = 1286912
# 被打断技能：读条 1286918，部分日志会把光环 1310752 记在 extraAbilityGameID。
NIGHTFALL_INTERRUPTED_SPELLS = {ETERNAL_NIGHTFALL, ETERNAL_NIGHTFALL_AURA}
# 轮次上界用下一发 begincast；没有下一发时再用这个上限，避免固定 12s 漏掉普通难度 ~14s 破盾。
NIGHTFALL_ROUND_MAX_MS = 45_000
NIGHTFALL_SHIELD_APPLY_LOOKBACK_MS = 2_000
UNASSAILABLE = 1285847
RECLAIM_ESSENCE = 1287718
SPIRIT_ERASURE = 1287722
# 踩片者易伤与伤害同 ID（1287722 applydebuff）；全团 AOE 按脉冲合并，不按承伤条数计次。
SPIRIT_ERASURE_DEBUFF_IDS = {1287722}
SPIRIT_ERASURE_WAVE_MS = 250
SPIRIT_ERASURE_STEPPER_WINDOW_MS = 500
INTERMISSION_BUFFS = {1304032, 1304033, 1304498}
P3_SOULBOUND = 1289798
POTION_LIGHTS_POTENTIAL = 1236616
POTION_RECKLESSNESS = 1236994
POTION_LIQUID_LUSTER = 1295132
INTERMISSION_POTIONS = {
    POTION_LIGHTS_POTENTIAL: "圣光潜力",
    POTION_RECKLESSNESS: "鲁莽药水",
    POTION_LIQUID_LUSTER: "液态光泽",
}
# 转阶段前预开药水也算本次爆发。
INTERMISSION_POTION_LOOKBACK_MS = 2_000

P2_SIGNAL_SPELL = 1307184
INTERMISSION_MS = 35_000
CONE_RADIUS_YARDS = 35
CONE_HALF_ANGLE_DEG = 30.0  # 总宽约 60° 的正面锥形
GLOOMBOMB_RADIUS_YARDS = 15
POSITION_RELIABLE_MS = 2_500

# 拉取时只向 WCL 要机制相关技能，避免整场友伤/治疗/带坐标的团员施法。
MECHANIC_CAST_IDS = (
    {TOXIC_DELUGE, COALESCED_VENOM_CAST, ETERNAL_NIGHTFALL, ETERNAL_NIGHTFALL_AURA,
     P2_SIGNAL_SPELL, MANIFEST_CAST, FIXATION, RECLAIM_ESSENCE}
    | SEVER_IDS | BLIGHTED_SEVER_IDS | SOUL_SEVER_IDS
    | GUILLOTINE_CAST_IDS | GRIM_GUILLOTINE_CAST_IDS
    | DREADMARCH_CAST_IDS | GLOOMBOMB_CAST_IDS
)
MECHANIC_DAMAGE_IDS = (
    {COALESCED_VENOM_DAMAGE, VOLATILE_VENOM, VENOM_RUPTURE, GUILLOTINE_DAMAGE_ID,
     WIDOW_TOUCH_DAMAGE_ID, WIDOW_KISS_DAMAGE_ID, DEATH_WHISPER_DAMAGE_ID,
     DEATH_EMBRACE_DAMAGE_ID, SPIRIT_ERASURE, RECLAIM_ESSENCE}
    | GRIM_GUILLOTINE_DAMAGE_IDS | GRAVEBOUND_DAMAGE_IDS
    | GLOOMBOMB_CAST_IDS | GLOOMBOMB_DEBUFF_IDS
)
MECHANIC_DEBUFF_IDS = (
    {VOLATILE_VENOM, FIXATION, GUILLOTINE_MARK, VENOM_RUPTURE}
    | GLOOMBOMB_DEBUFF_IDS | GRAVEBOUND_DEBUFF_IDS
    | DREADMARCH_DEBUFF_IDS | MANIFEST_COLLISION_DEBUFF_IDS
    | GRIM_GUILLOTINE_MARK_IDS
    | SEVER_TANK_DEBUFF_IDS | BLIGHTED_SEVER_TANK_DEBUFF_IDS | SOUL_SEVER_TANK_DEBUFF_IDS
    | SPIRIT_ERASURE_DEBUFF_IDS
)
MECHANIC_ENEMY_BUFF_IDS = set(INTERMISSION_BUFFS) | {VEIL_SHIELD, P3_SOULBOUND}
FRIENDLY_CAST_IDS = set(COMBAT_RES_SPELLS) | set(INTERMISSION_POTIONS) | {SPIRIT_ERASURE}


def _boss_icon_src(key):
    path = get_boss_icon_path(key)
    return path.relative_to(path.parents[2]).as_posix()


FIELD_ICONS = {
    "zuljan": _boss_icon_src("zuljan"),
    "malacrass": _boss_icon_src("hex_lord_malacrass"),
    "poisonOrb": _boss_icon_src("poison_orb"),
    "manifestation": _boss_icon_src("manifestation_dread"),
}

TABS = [
    ("survival", "全场存活情况"),
    ("p1", "P1 毒蛇的交易"),
    ("p2", "P2 篡权者的报复"),
    ("intermission", "转阶段 被夺取的宿体"),
    ("p3", "P3 盘卷联合"),
    ("field", "场地示意图"),
]


def progress(message, percent=None):
    print(f"[coiledaltar] {message}", flush=True)
    emit_progress(message, percent=percent, stage="analyze")


def is_apply(event):
    return event_type(event) in {"applydebuff", "applybuff", "applydebuffstack", "applybuffstack", "refreshdebuff"}


def is_remove(event):
    return event_type(event) in {"removedebuff", "removebuff", "removedebuffstack", "removebuffstack"}


def is_cast_complete(event):
    return event_type(event) == "cast"


def normalize_facing_radians(raw_facing):
    if raw_facing is None:
        return None
    radians = float(raw_facing) / 100.0
    while radians <= -math.pi:
        radians += math.tau
    while radians > math.pi:
        radians -= math.tau
    return radians


def yards_to_units(yards):
    return float(yards) * WCL_UNITS_PER_YARD


def units_to_yards(units):
    return float(units) / WCL_UNITS_PER_YARD


def distance_yards(left, right):
    return math.hypot(left[0] - right[0], left[1] - right[1]) / WCL_UNITS_PER_YARD


def arena_center_units():
    return (ARENA_CENTER_X_UNITS * WCL_COORD_SCALE, ARENA_CENTER_Y_UNITS * WCL_COORD_SCALE)


def point_dict(point, timestamp=None, reliable=None, offset_ms=None):
    if not point:
        return None
    row = {"x": round(point[0], 2), "y": round(point[1], 2)}
    if timestamp is not None:
        row["timestamp"] = int(timestamp)
    if reliable is not None:
        row["positionReliable"] = bool(reliable)
    if offset_ms is not None:
        row["sampleOffsetMs"] = int(offset_ms)
    return row


def actor_facing_at(index, actor_id, timestamp):
    row = position_at(index, actor_id, timestamp, max_offset_ms=POSITION_RELIABLE_MS)
    if not row:
        return None
    return {
        **row,
        "facingRadians": normalize_facing_radians(row.get("facing")),
    }


def in_frontal_cone(origin, facing_radians, point, radius_yards=CONE_RADIUS_YARDS, half_angle_deg=CONE_HALF_ANGLE_DEG):
    if origin is None or point is None or facing_radians is None:
        return False
    dx = point[0] - origin[0]
    dy = point[1] - origin[1]
    distance = math.hypot(dx, dy)
    if distance > yards_to_units(radius_yards):
        return False
    target_angle = math.atan2(-dy, dx)
    delta = (target_angle - facing_radians + math.pi) % (2 * math.pi) - math.pi
    return abs(delta) <= math.radians(half_angle_deg)


def cone_polygon(origin, facing_radians, radius_yards=CONE_RADIUS_YARDS, half_angle_deg=CONE_HALF_ANGLE_DEG, steps=18):
    if origin is None or facing_radians is None:
        return []
    radius = yards_to_units(radius_yards)
    points = [origin]
    start = facing_radians - math.radians(half_angle_deg)
    end = facing_radians + math.radians(half_angle_deg)
    for index in range(steps + 1):
        angle = start + (end - start) * index / steps
        points.append((origin[0] + math.cos(angle) * radius, origin[1] - math.sin(angle) * radius))
    points.append(origin)
    return [point_dict(point) for point in points]


def _position_xy(point):
    if not point:
        return None
    if isinstance(point, dict):
        if point.get("x") is None or point.get("y") is None:
            nested = point.get("position")
            if nested:
                return _position_xy(nested)
            return None
        return float(point["x"]), float(point["y"])
    if isinstance(point, (list, tuple)) and len(point) >= 2:
        return float(point[0]), float(point[1])
    return None


def facing_toward_point(origin, point):
    coords = _position_xy(point)
    if not coords or origin is None:
        return None
    dx = coords[0] - origin[0]
    dy = coords[1] - origin[1]
    return math.atan2(-dy, dx)


def point_last_seen_ms(point, fight_start):
    last = int(point.get("lastSeenMs") or 0)
    if last > fight_start:
        return last - fight_start
    return last


def active_points_near_cast(active_points, timestamp, fight_start, window_ms=30_000):
    cast_rel = timestamp - fight_start
    return [
        point for point in (active_points or [])
        if point.get("position") and point_last_seen_ms(point, fight_start) >= cast_rel - window_ms
    ]


def active_fixations_before_cast(points, cast_ts, fight_start):
    """撕裂/凋零撕裂释放前仍存活的恐惧具象（已 apply，且尚未 remove/despawn）。"""
    cast_rel = int(cast_ts) - int(fight_start)
    active = []
    for point in points or []:
        apply_rel = point.get("applyTimeMs")
        if apply_rel is None or int(apply_rel) > cast_rel:
            continue
        end_rel = point.get("removeTimeMs")
        if end_rel is None and point.get("despawnTimeMs") is not None:
            end_rel = point.get("despawnTimeMs")
        if end_rel is None:
            last = point_last_seen_ms(point, fight_start)
            end_rel = last if last else None
        # 释放前已消除（凝视消失或 NPC 消失）的不再计入
        if end_rel is not None and int(end_rel) <= cast_rel:
            continue
        active.append(point)
    return active


def classify_fixation_after_sever(point, cast_ts, fight_start, in_cone, clear_window_ms=SOUL_SEVER_CLEAR_WINDOW_MS):
    """
    综合判断本轮锥形撕裂是否清掉凝视（灵魂撕裂 / 凋零撕裂）：
    - 释放后短窗口内 remove → 已清掉
    - 否则视为未消掉；再结合是否在锥内区分漏清 / 锥外残留
    """
    cast_rel = int(cast_ts) - int(fight_start)
    remove_rel = point.get("removeTimeMs")
    cleared = (
        remove_rel is not None
        and cast_rel < int(remove_rel) <= cast_rel + int(clear_window_ms)
    )
    if cleared:
        outcome = "cleared"
    elif in_cone:
        outcome = "missed-in-cone"
    else:
        outcome = "outside-remain"
    return {
        "inCone": bool(in_cone),
        "debuffCleared": cleared,
        "uncleared": not cleared,
        "clearOutcome": outcome,
    }


# 兼容旧名
classify_fixation_after_soul_sever = classify_fixation_after_sever


def infer_facing_toward(origin, points):
    """Visualization-only facing estimate toward the centroid of nearby markers."""
    coords = [_position_xy(point) for point in (points or [])]
    coords = [row for row in coords if row]
    if not coords or origin is None:
        return None
    centroid_x = sum(row[0] for row in coords) / len(coords)
    centroid_y = sum(row[1] for row in coords) / len(coords)
    return facing_toward_point(origin, (centroid_x, centroid_y))


def plot_pct(point, arena):
    coords = _position_xy(point)
    if not coords or not arena:
        return None
    radius = float(arena.get("radius") or 1)
    dx = coords[0] - float(arena["centerX"])
    dy = coords[1] - float(arena["centerY"])
    return {
        "left": 50 + (dx / radius) * float(arena.get("plotScaleX") or ARENA_PLOT_SCALE_X),
        "top": 50 - (dy / radius) * float(arena.get("plotScaleY") or ARENA_PLOT_SCALE_Y),
    }


def plot_size_pct(yards, arena):
    if not arena:
        return {"width": 0.0, "height": 0.0}
    ratio = yards_to_units(yards) / float(arena.get("radius") or 1)
    return {
        "width": ratio * float(arena.get("plotScaleX") or ARENA_PLOT_SCALE_X),
        "height": ratio * float(arena.get("plotScaleY") or ARENA_PLOT_SCALE_Y),
    }


def _boss_start_point(position_index, boss_id):
    if boss_id is None:
        return None
    rows = position_index.get(boss_id) or []
    if not rows:
        return None
    first = rows[0]
    return point_dict((first["x"], first["y"]), timestamp=first.get("timestamp"), reliable=True)


def coiledaltar_arena(position_index=None, player_ids=None, boss_id=None):
    center = arena_center_units()
    boss_start = _boss_start_point(position_index or {}, boss_id)
    return {
        "centerX": center[0],
        "centerY": center[1],
        "centerXYards": ARENA_CENTER_X_UNITS,
        "centerYYards": ARENA_CENTER_Y_UNITS,
        "centerXUnits": ARENA_CENTER_X_UNITS,
        "centerYUnits": ARENA_CENTER_Y_UNITS,
        "radius": ARENA_HALF_SIDE_UNITS * WCL_COORD_SCALE,
        "radiusYards": ARENA_HALF_SIDE_YARDS,
        "radiusUnits": ARENA_HALF_SIDE_UNITS,
        "sideYards": ARENA_SIDE_YARDS,
        "sideUnits": ARENA_SIDE_UNITS,
        "halfSideYards": ARENA_HALF_SIDE_YARDS,
        "halfSideUnits": ARENA_HALF_SIDE_UNITS,
        "unitsPerYard": WCL_UNITS_PER_YARD,
        "wclCoordScale": WCL_COORD_SCALE,
        "method": "fixed-center-0-1158-square-110u-86y",
        "bossCenter": True,
        "bossStart": boss_start,
        "plotScaleX": ARENA_PLOT_SCALE_X,
        "plotScaleY": ARENA_PLOT_SCALE_Y,
        "imageWidth": ARENA_IMAGE_WIDTH,
        "imageHeight": ARENA_IMAGE_HEIGHT,
        "squarePx": ARENA_SQUARE_PX,
        "gloombombRadiusYards": GLOOMBOMB_RADIUS_YARDS,
        "coneRadiusYards": CONE_RADIUS_YARDS,
        "guillotineRangeYards": GUILLOTINE_RANGE_YARDS,
    }


def _xy_from_node(node):
    if not isinstance(node, dict) or node.get("x") is None or node.get("y") is None:
        return None
    try:
        return float(node["x"]), float(node["y"])
    except (TypeError, ValueError):
        return None


def _source_self_point(event):
    """只取施法者自身坐标。WCL 施法事件顶层 x/y 经常是目标（坦克），不能当 Boss 位置。"""
    point = _xy_from_node(event.get("sourceResources"))
    if point:
        return point
    resource_actor = event.get("resourceActor")
    if resource_actor in {1, "1", "Source"}:
        return event_point(event)
    return None


def _target_self_point(event):
    """只取受击者自身坐标。resourceActor=Target 时顶层 x/y 才属于目标。"""
    point = _xy_from_node(event.get("targetResources"))
    if point:
        return point
    resource_actor = event.get("resourceActor")
    if resource_actor in {2, "2", "Target"}:
        return _xy_from_node(event) or _xy_from_node(event.get("resources"))
    return None


def _actor_self_point(event, actor_id):
    if actor_id is None:
        return None
    if event.get("sourceID") == actor_id:
        point = _source_self_point(event)
        if point:
            return point
    # 友伤打 Boss 时顶层 x/y / targetResources 才可能是 Boss；其它事件不要把目标坐标当 Boss。
    if event.get("targetID") == actor_id and event_type(event) == "damage":
        return _target_self_point(event)
    return None


def _actor_self_facing(event, actor_id):
    if event.get("sourceID") == actor_id:
        return (event.get("sourceResources") or {}).get("facing", event.get("facing"))
    if event.get("targetID") == actor_id:
        return (event.get("targetResources") or {}).get("facing", event.get("facing"))
    return event.get("facing")


def build_caster_self_position_index(events, actor_ids=None):
    """Boss 自身坐标：优先 sourceResources；Boss 受击时才用 targetResources。"""
    index = defaultdict(list)
    allowed = set(actor_ids) if actor_ids else None
    for event in events:
        candidates = []
        source_id = event.get("sourceID")
        target_id = event.get("targetID")
        if source_id is not None and (allowed is None or source_id in allowed):
            candidates.append(source_id)
        if target_id is not None and target_id != source_id and (allowed is None or target_id in allowed):
            candidates.append(target_id)
        timestamp = int(event.get("timestamp") or 0)
        for actor_id in candidates:
            point = _actor_self_point(event, actor_id)
            if not point:
                continue
            index[actor_id].append({
                "timestamp": timestamp,
                "x": point[0], "y": point[1],
                "facing": _actor_self_facing(event, actor_id),
            })
    for rows in index.values():
        rows.sort(key=lambda row: row["timestamp"])
    return index


def boss_cone_origin(origin_index, boss_actor_id, timestamp, cast_event=None):
    """撕裂锥形圆心：优先施法事件 sourceResources，否则取 Boss 自身轨迹。"""
    if cast_event is not None and boss_actor_id is not None and cast_event.get("sourceID") == boss_actor_id:
        cast_point = _source_self_point(cast_event)
        if cast_point:
            facing = (cast_event.get("sourceResources") or {}).get("facing", cast_event.get("facing"))
            return cast_point, {
                "x": cast_point[0],
                "y": cast_point[1],
                "facing": facing,
                "facingRadians": normalize_facing_radians(facing),
                "reliable": True,
                "positionRule": "cast-sourceResources",
                "sampleOffsetMs": 0,
            }
    live = actor_origin_at(origin_index, boss_actor_id, timestamp) if origin_index and boss_actor_id is not None else None
    if not live:
        return None, {
            "facingRadians": None,
            "reliable": False,
            "positionRule": "missing",
            "sampleOffsetMs": None,
        }
    return (live["x"], live["y"]), {
        "x": live["x"],
        "y": live["y"],
        "facing": live.get("facing"),
        "facingRadians": live.get("facingRadians"),
        "reliable": bool(live.get("reliable")),
        "positionRule": live.get("positionRule") or "boss-current",
        "sampleOffsetMs": live.get("sampleOffsetMs"),
    }


def boss_field_position(origin_index, boss_actor_id, timestamp, cast_event=None):
    """处斩/幽暗炸弹等非锥形图：Boss 标记用当时自身坐标，不用场地中心。"""
    origin, state = boss_cone_origin(origin_index, boss_actor_id, timestamp, cast_event=cast_event)
    if not origin:
        return None
    return point_dict(
        origin,
        timestamp=timestamp,
        reliable=bool(state and state.get("reliable")),
        offset_ms=(state or {}).get("sampleOffsetMs"),
    )


def actor_origin_at(index, actor_id, timestamp):
    row = position_at_interpolated(index, actor_id, timestamp, reliable_window_ms=POSITION_RELIABLE_MS)
    if not row:
        row = position_at(index, actor_id, timestamp, max_offset_ms=POSITION_RELIABLE_MS)
    if not row:
        return None
    return {
        **row,
        "facingRadians": normalize_facing_radians(row.get("facing")),
    }


def matching_begincast(casts, cast_event, max_duration_ms=15_000):
    """配对同一施法者、同一技能、完成 cast 之前最近的 begincast。"""
    if not cast_event:
        return None
    cast_ts = int(cast_event.get("timestamp") or 0)
    source_id = cast_event.get("sourceID")
    spell = int(ability_id(cast_event) or 0)
    best = None
    best_ts = None
    for event in casts or []:
        if event_type(event) != "begincast":
            continue
        if event.get("sourceID") != source_id:
            continue
        if int(ability_id(event) or 0) != spell:
            continue
        ts = int(event.get("timestamp") or 0)
        if ts > cast_ts or cast_ts - ts > max_duration_ms:
            continue
        if best is None or ts > best_ts:
            best = event
            best_ts = ts
    return best


def resolve_sever_facing_lock(casts, cast_event, debuffs=None, debuff_ids=None):
    """
    撕裂朝向锁定时刻：优先坦克易伤/结算 debuff 施加；否则读条最后一秒；再退回 cast 完成。
    返回 (lock_ms, tank_id, rule, debuff_event)。
    """
    cast_ts = int((cast_event or {}).get("timestamp") or 0)
    tank_id = (cast_event or {}).get("targetID")
    spell = int(ability_id(cast_event) or 0) if cast_event else 0
    ids = set(debuff_ids or CAST_TO_TANK_DEBUFF_IDS.get(spell) or ())
    if ids and debuffs is not None:
        window = _events_between(debuffs, cast_ts - 2_500, cast_ts + 2_500, ids)
        applies = [event for event in window if is_apply(event)]
        if tank_id is not None:
            matched = [event for event in applies if event.get("targetID") == tank_id]
            if matched:
                applies = matched
        if applies:
            applies.sort(key=lambda event: abs(int(event.get("timestamp") or 0) - cast_ts))
            chosen = applies[0]
            return int(chosen["timestamp"]), chosen.get("targetID") or tank_id, "tank-debuff", chosen
    begin = matching_begincast(casts, cast_event)
    if begin is not None:
        begin_ts = int(begin["timestamp"])
        lock_ms = max(begin_ts, cast_ts - CAST_LAST_SECOND_MS)
        return lock_ms, tank_id, "cast-last-second", None
    if cast_ts:
        return max(0, cast_ts - CAST_LAST_SECOND_MS), tank_id, "cast-last-second", None
    return cast_ts, tank_id, "cast-complete", None


def resolve_caster_origin_facing(
    position_index,
    source_id,
    boss_actor_id,
    timestamp,
    hint_points=None,
    target_id=None,
    origin_actor_id=None,
    origin_index=None,
    cast_event=None,
    facing_timestamp=None,
    allow_hint_override=True,
):
    """圆心=Boss（施法结算）；朝向中点=锁定时刻的坦克位置（debuff / 读条末秒）。"""
    origin_actor = origin_actor_id or boss_actor_id or source_id
    if cast_event is not None and origin_actor is None:
        origin_actor = cast_event.get("sourceID")
    origin, facing_state = boss_cone_origin(origin_index, origin_actor, timestamp, cast_event=cast_event)
    facing_radians = None
    facing_inferred = False
    tank_id = target_id if target_id is not None else (cast_event or {}).get("targetID")
    facing_at = int(facing_timestamp) if facing_timestamp is not None else int(timestamp)
    tank_facing = None
    tank_state = None
    if origin and tank_id is not None:
        tank_state = position_at(position_index, tank_id, facing_at, max_offset_ms=POSITION_RELIABLE_MS)
        if tank_state:
            tank_facing = facing_toward_point(origin, (tank_state["x"], tank_state["y"]))
            facing_radians = tank_facing
    if facing_radians is None and facing_state.get("facingRadians") is not None:
        facing_radians = facing_state["facingRadians"]
    if facing_radians is None and origin_index is not None:
        live = actor_origin_at(origin_index, origin_actor, timestamp)
        if live and live.get("facingRadians") is not None:
            facing_radians = live["facingRadians"]
            facing_state = {**facing_state, "facing": live.get("facing"), "facingRadians": facing_radians}
    hint_facing = None
    if origin and hint_points:
        hint_facing = infer_facing_toward(origin, hint_points)
    # 已按 debuff/读条末秒锁定坦克位置时，不再用毒液质心覆盖朝向。
    if origin and hint_facing is not None:
        if facing_radians is None:
            facing_radians = hint_facing
            facing_inferred = True
        elif allow_hint_override and tank_facing is not None:
            delta = (hint_facing - tank_facing + math.pi) % (2 * math.pi) - math.pi
            if abs(delta) > math.pi / 2:
                facing_radians = hint_facing
                facing_inferred = True
    if origin and facing_radians is None and hint_facing is not None:
        facing_radians = hint_facing
        facing_inferred = True
    return origin, facing_radians, facing_state, facing_inferred, tank_state


def build_actor_catalog(actor_rows):
    by_id = {}
    by_game_id = defaultdict(list)
    for row in actor_rows:
        actor_id = row["id"]
        game_id = row.get("gameID")
        entry = {
            "actorID": actor_id,
            "name": row.get("name"),
            "gameID": game_id,
            "type": row.get("type"),
        }
        by_id[actor_id] = entry
        if game_id is not None:
            by_game_id[int(game_id)].append(entry)
    return {"byID": by_id, "byGameID": dict(by_game_id)}


def resolve_manifest_instance(source_id, source_instance, actor_catalog):
    actor = actor_catalog["byID"].get(source_id) or {}
    game_id = actor.get("gameID")
    return {
        "sourceID": source_id,
        "sourceInstance": source_instance,
        "sourceName": actor.get("name"),
        "gameID": game_id,
        "isManifestNpc": game_id == MANIFEST_NPC_GAME_ID or any(
            token in str(actor.get("name") or "").lower()
            for token in ("manifestation of dread", "恐惧具象")
        ),
    }


def phase_at(time_ms, markers):
    current = markers[0]["key"] if markers else "p1"
    for marker in markers:
        if time_ms >= marker["timeMs"]:
            current = marker["key"]
    return current


def build_phase_markers(fight, casts, enemy_buffs, enemy_deaths=None, zuljan_id=None, malacrass_id=None):
    """P2 = 祖尔加死亡 / 玛拉卡斯出现；转阶段与 P3 仍看容器/灵魂绑定 Aura。"""
    start = int(fight["startTime"])
    p2_ms = None
    p2_signal = None
    intermission_ms = None
    p3_ms = None

    if zuljan_id is not None:
        for event in sorted(enemy_deaths or [], key=lambda row: int(row.get("timestamp") or 0)):
            if event.get("targetID") == zuljan_id and event_type(event) == "death":
                p2_ms = int(event["timestamp"]) - start
                p2_signal = "zuljan-death"
                break

    if p2_ms is None and malacrass_id is not None:
        for event in sorted(casts, key=lambda row: int(row.get("timestamp") or 0)):
            if event.get("sourceID") != malacrass_id:
                continue
            if event_type(event) in {"begincast", "cast"}:
                p2_ms = int(event["timestamp"]) - start
                p2_signal = "malacrass-appear"
                break

    if p2_ms is None:
        for event in sorted(casts, key=lambda row: int(row.get("timestamp") or 0)):
            if int(ability_id(event) or 0) == P2_SIGNAL_SPELL and event_type(event) == "begincast":
                p2_ms = int(event["timestamp"]) - start
                p2_signal = "fear-bolt-fallback"
                break

    for event in sorted(enemy_buffs, key=lambda row: int(row.get("timestamp") or 0)):
        spell = int(ability_id(event) or 0)
        if spell in INTERMISSION_BUFFS and is_apply(event) and intermission_ms is None:
            intermission_ms = int(event["timestamp"]) - start
        if spell == P3_SOULBOUND and is_apply(event):
            p3_ms = int(event["timestamp"]) - start

    markers = [{"key": "p1", "label": "P1 毒蛇交易", "timeMs": 0}]
    if p2_ms is not None:
        markers.append({
            "key": "p2",
            "label": "P2 篡位者复仇",
            "timeMs": p2_ms,
            "signal": p2_signal,
        })
    if intermission_ms is not None:
        markers.append({"key": "intermission", "label": "被夺取的容器", "timeMs": intermission_ms})
    if p3_ms is not None:
        markers.append({"key": "p3", "label": "P3 盘卷联合", "timeMs": p3_ms})
    markers.append({
        "key": "wipe",
        "label": "击杀" if fight.get("kill") else "灭团",
        "timeMs": int(fight["endTime"] - start),
    })
    return markers


def _ability_filter(spell_ids):
    ids = sorted({int(spell_id) for spell_id in spell_ids or [] if spell_id})
    if not ids:
        return None
    if len(ids) == 1:
        return f"ability.id = {ids[0]}"
    return "ability.id in (" + ", ".join(str(i) for i in ids) + ")"


def _actor_filter(actor_ids):
    ids = sorted({int(actor_id) for actor_id in actor_ids or [] if actor_id is not None})
    if not ids:
        return None
    if len(ids) == 1:
        return f"source.id = {ids[0]} OR target.id = {ids[0]}"
    joined = ", ".join(str(i) for i in ids)
    return f"source.id in ({joined}) OR target.id in ({joined})"


def _event_type_filter(types):
    return "type in (" + ", ".join(f'"{name}"' for name in types) + ")"


# 具象只点名上凝视，不打人。坐标来自其施法/debuff 的 sourceResources，以及被打到时的受击坐标。
NPC_POSITION_TYPES = (
    "cast", "begincast", "applybuff", "applydebuff", "removebuff", "removedebuff",
    "refreshbuff", "refreshdebuff", "death",
)


def _npc_position_filter_expression(npc_ids):
    actor_filter = _actor_filter(npc_ids)
    if not actor_filter:
        return None
    return f"({actor_filter}) and {_event_type_filter(NPC_POSITION_TYPES)}"


def _fetch_manifest_position_events(client, report_id, fight, manifest_ids):
    """具象坐标：点名施法/凝视 debuff、敌方资源采样，以及被打到时的受击位置。"""
    source_filter = _source_id_filter(manifest_ids)
    target_filter = _target_id_filter(manifest_ids)
    rows = []
    if source_filter:
        rows.extend(client.events(
            report_id, "Casts", fight,
            filter_expression=source_filter, hostility_type="Enemies", include_resources=True,
        ))
        rows.extend(client.events(
            report_id, "Resources", fight,
            filter_expression=source_filter, hostility_type="Enemies", include_resources=True,
        ))
    if target_filter:
        rows.extend(client.events(
            report_id, "DamageTaken", fight,
            filter_expression=target_filter, hostility_type="Enemies", include_resources=True,
        ))
    return rows


def _source_id_filter(actor_ids):
    ids = sorted({int(actor_id) for actor_id in actor_ids or [] if actor_id is not None})
    if not ids:
        return None
    if len(ids) == 1:
        return f"source.id = {ids[0]}"
    return "source.id in (" + ", ".join(str(i) for i in ids) + ")"


def _target_id_filter(actor_ids):
    ids = sorted({int(actor_id) for actor_id in actor_ids or [] if actor_id is not None})
    if not ids:
        return None
    if len(ids) == 1:
        return f"target.id = {ids[0]}"
    return "target.id in (" + ", ".join(str(i) for i in ids) + ")"


def _fetch_by_abilities(client, report_id, data_type, fight, spell_ids, **kwargs):
    expression = _ability_filter(spell_ids)
    if not expression:
        return []
    return client.events(report_id, data_type, fight, filter_expression=expression, **kwargs)


def _events_between(events, start, end, spell_ids=None):
    spell_ids = set(spell_ids or [])
    return [
        event for event in events
        if start <= int(event.get("timestamp") or 0) < end
        and (not spell_ids or int(ability_id(event) or 0) in spell_ids)
    ]


def _position_sample(index, actor_id, timestamp):
    row = position_at_interpolated(index, actor_id, timestamp, reliable_window_ms=POSITION_RELIABLE_MS)
    if not row:
        return None
    return point_dict((row["x"], row["y"]), timestamp=timestamp, reliable=row.get("reliable"), offset_ms=row.get("sampleOffsetMs"))


def manifest_actor_ids(actor_rows):
    ids = set()
    for row in actor_rows:
        game_id = row.get("gameID")
        name = str(row.get("name") or "").lower()
        if game_id == MANIFEST_NPC_GAME_ID or "manifestation of dread" in name or "恐惧具象" in name:
            ids.add(int(row["id"]))
    return ids


def _npc_position_events(raw, npc_actor_ids):
    if not npc_actor_ids:
        return []
    events = []
    for bucket in ("casts", "enemyDamage", "damage", "debuffs", "resources", "enemyDeaths", "npcPositionEvents"):
        for event in raw.get(bucket) or []:
            source_id = event.get("sourceID")
            target_id = event.get("targetID")
            actor_id = position_actor_id(event)
            if source_id in npc_actor_ids or target_id in npc_actor_ids or actor_id in npc_actor_ids:
                events.append(event)
    return events


def _npc_actor_point(event, actor_id):
    """恐惧具象等 NPC 自身坐标。施法顶层 x/y 常是被点名玩家，不能直接当 NPC 位置。"""
    if actor_id is None:
        return None
    kind = event_type(event)
    if event.get("sourceID") == actor_id:
        point = _xy_from_node(event.get("sourceResources"))
        if point:
            return point
        resource_actor = event.get("resourceActor")
        if resource_actor in {1, "1", "Source"}:
            return _xy_from_node(event) or _xy_from_node(event.get("resources"))
        target_id = event.get("targetID")
        # 无目标，或目标就是自己：顶层坐标才可能属于 NPC
        if target_id is None or target_id == actor_id:
            return _xy_from_node(event) or _xy_from_node(event.get("resources"))
        return None
    if event.get("targetID") == actor_id:
        point = _xy_from_node(event.get("targetResources"))
        if point:
            return point
        resource_actor = event.get("resourceActor")
        if resource_actor in {2, "2", "Target"}:
            return _xy_from_node(event) or _xy_from_node(event.get("resources"))
        # 友伤/死亡打在具象上时，顶层 x/y 通常是受击 NPC
        if kind in {"damage", "death"}:
            return _xy_from_node(event) or _xy_from_node(event.get("resources"))
        return None
    return None


def build_npc_position_index(events):
    """按 (actorID, instance) 索引 NPC 自身坐标；拒绝把被点名玩家坐标写入具象。"""
    index = defaultdict(list)

    def append(actor_id, instance, timestamp, point, facing):
        if actor_id is None or not point:
            return
        key = (int(actor_id), int(instance or 0))
        index[key].append({"timestamp": timestamp, "x": point[0], "y": point[1], "facing": facing})

    for event in events:
        timestamp = int(event.get("timestamp") or 0)
        source_id = event.get("sourceID")
        source_instance = event.get("sourceInstance") or event.get("sourceInstanceID")
        target_id = event.get("targetID")
        target_instance = event.get("targetInstance") or event.get("targetInstanceID")
        kind = event_type(event)
        if kind in {"cast", "begincast"}:
            point = _npc_actor_point(event, source_id)
            facing = (event.get("sourceResources") or {}).get("facing", event.get("facing"))
            append(source_id, source_instance, timestamp, point, facing)
        elif kind in {"damage", "death"}:
            point = _npc_actor_point(event, target_id)
            facing = (event.get("targetResources") or {}).get("facing", event.get("facing"))
            append(target_id, target_instance, timestamp, point, facing)
        else:
            for actor_id, instance in ((source_id, source_instance), (target_id, target_instance)):
                if actor_id is None:
                    continue
                point = _npc_actor_point(event, actor_id)
                facing = _actor_self_facing(event, actor_id)
                append(actor_id, instance, timestamp, point, facing)
    for rows in index.values():
        rows.sort(key=lambda row: row["timestamp"])
    return index


def _npc_instance_rows(index, actor_id, source_instance):
    if actor_id is None:
        return []
    actor_id = int(actor_id)
    if source_instance is not None:
        exact = index.get((actor_id, int(source_instance))) or []
        if exact:
            return exact
    return index.get((actor_id, 0)) or []


def _position_sample_npc(index, actor_id, source_instance, timestamp):
    rows = _npc_instance_rows(index, actor_id, source_instance)
    if not rows:
        return None
    nearest = min(rows, key=lambda row: abs(row["timestamp"] - timestamp))
    offset = int(nearest["timestamp"] - timestamp)
    if abs(offset) > 30_000:
        return None
    return point_dict(
        (nearest["x"], nearest["y"]),
        timestamp=timestamp,
        reliable=abs(offset) <= POSITION_RELIABLE_MS,
        offset_ms=offset,
    )


def _position_last_at_or_before(index, actor_id, source_instance, timestamp):
    """取该 NPC 实例在消失时刻（含）之前的最后一个坐标。"""
    if timestamp is None:
        return None
    rows = _npc_instance_rows(index, actor_id, source_instance)
    prior = [row for row in rows if int(row["timestamp"]) <= int(timestamp)]
    if not prior:
        return None
    last = prior[-1]
    offset = int(last["timestamp"] - timestamp)
    return point_dict(
        (last["x"], last["y"]),
        timestamp=timestamp,
        reliable=abs(offset) <= POSITION_RELIABLE_MS,
        offset_ms=offset,
    )


def _npc_instance_death_ts(deaths, actor_id, source_instance):
    if actor_id is None:
        return None
    wanted = int(source_instance or 0)
    times = []
    for event in deaths or []:
        if event.get("targetID") != actor_id:
            continue
        inst = event.get("targetInstance") or event.get("targetInstanceID") or 0
        if int(inst or 0) != wanted:
            continue
        times.append(int(event["timestamp"]))
    return min(times) if times else None


def _first_remove_after(events, target_id, apply_ts, spell_ids):
    spell_ids = set(spell_ids)
    return next(
        (
            event for event in events
            if event.get("targetID") == target_id
            and int(ability_id(event) or 0) in spell_ids
            and is_remove(event)
            and int(event.get("timestamp") or 0) >= int(apply_ts)
        ),
        None,
    )


def _gravebound_apply_in_window(events, target_id, start, end):
    return next(
        (
            event for event in events
            if event.get("targetID") == target_id
            and int(ability_id(event) or 0) in GRAVEBOUND_DEBUFF_IDS
            and is_apply(event)
            and start <= int(event.get("timestamp") or 0) <= end
        ),
        None,
    )


def _pet_owner_map(actor_rows):
    mapping = {}
    for row in actor_rows or []:
        owner = row.get("petOwner")
        if owner is None:
            continue
        mapping[int(row["id"])] = int(owner)
    return mapping


def _resolve_player_source(event, players, pet_owners):
    source_id = event.get("sourceID")
    if source_id in players:
        return source_id
    owner_id = pet_owners.get(source_id)
    if owner_id in players:
        return owner_id
    return None


def _player_is_healer(players, player_id):
    return role_to_basic((players.get(player_id) or {}).get("role")) == "healer"


def _alive_player_ids(players, deaths, friendly_casts, timestamp):
    alive = set(players)
    timeline = [
        (int(event.get("timestamp") or 0), "death", event.get("targetID"))
        for event in deaths or []
        if event.get("targetID") in players
    ]
    timeline.extend(
        (int(event.get("timestamp") or 0), "res", event.get("targetID"))
        for event in friendly_casts or []
        if event.get("targetID") in players
        and int(ability_id(event) or 0) in COMBAT_RES_SPELLS
        and event_type(event) in {"cast", "applybuff"}
    )
    for event_timestamp, kind, player_id in sorted(timeline):
        if event_timestamp >= timestamp:
            break
        if kind == "death":
            alive.discard(player_id)
        else:
            alive.add(player_id)
    return alive


def event_absorb_amount(event):
    return int(event.get("absorbed") or 0)


def _venom_spawn_point(event):
    """凝结毒液生成坐标：优先施法者自身，避免顶层目标污染。"""
    point = _source_self_point(event)
    if point:
        return point
    if event.get("targetID") in (None, event.get("sourceID")):
        return _xy_from_node(event) or _xy_from_node(event.get("resources"))
    return None


def _nearest_ground_puddle(ground, point, max_yards=VENOM_PICKUP_MAX_YARDS):
    """地上毒液中，落点/生成点距 point 最近且不超过 max_yards 的一团。"""
    if not ground or not point:
        return None
    best = None
    best_dist = None
    for puddle in ground:
        pos = _position_xy(puddle.get("position"))
        if not pos:
            continue
        dist = distance_yards(pos, point)
        if dist > max_yards:
            continue
        if best is None or dist < best_dist:
            best = puddle
            best_dist = dist
    return best


def _match_puddle_for_pickup(ground, player_xy, max_yards=VENOM_PICKUP_MAX_YARDS):
    """
    判断捡球是否对应已有地上毒液：用获得 debuff 时玩家位置与此前放球/生成位置是否过近。
    禁止「无近距时取最早落地」——会把远处另一球误绑并留下孤儿落点，造成去重失败。
    无可靠玩家坐标且场上仅一团时，只能归属该团。
    """
    if not ground:
        return None
    if player_xy:
        return _nearest_ground_puddle(ground, player_xy, max_yards=max_yards)
    if len(ground) == 1:
        return ground[0]
    return None


def analyze_toxic_deluge(fight, casts, debuffs, position_index, actor_map, players, markers, damage_events=None):
    """
    凝结毒液支持多次搬运：
    - 地上毒液 ↔ 玩家不稳定毒液(1282419) 来回切换
    - 掉落后短窗口内再被捡起视为接力，不把中间落点当成最终场上位置
    - 有 1282408 伤害源坐标时刷新地上毒液位置
    """
    fight_start = int(fight["startTime"])
    deluge_casts = [event for event in casts if int(ability_id(event) or 0) == TOXIC_DELUGE and is_cast_complete(event)]
    spawn_events = [event for event in casts if int(ability_id(event) or 0) == COALESCED_VENOM_CAST and is_cast_complete(event)]
    rounds = []
    for index, deluge in enumerate(deluge_casts, start=1):
        start = int(deluge["timestamp"])
        end = int(deluge_casts[index]["timestamp"]) if index < len(deluge_casts) else int(fight["endTime"])
        spawns = []
        for event in _events_between(spawn_events, start, start + 12_000):
            spawn_point = _venom_spawn_point(event)
            spawns.append({
                "spawnTimeMs": int(event["timestamp"]) - fight_start,
                "spawnTime": fmt_ms(int(event["timestamp"]) - fight_start),
                "sourceID": event.get("sourceID"),
                "sourceInstance": event.get("sourceInstance") or event.get("sourceInstanceID"),
                "position": point_dict(spawn_point, timestamp=int(event["timestamp"])) if spawn_point else None,
            })
        rounds.append({
            "index": index,
            "phase": phase_at(start - fight_start, markers),
            "timeMs": start - fight_start,
            "time": fmt_ms(start - fight_start),
            "spawnCount": len(spawns),
            "spawns": spawns,
            "carriers": [],
            "drops": [],
            "groundPuddles": [],
            "windowStart": start,
            "windowEnd": end,
        })

    ground = []  # 当前在地上的毒液
    carrying = {}  # playerID -> puddle being carried
    completed_puddles = []
    carrier_rows = []
    puddle_seq = 0

    def new_puddle(position, grounded_from_abs, spawn_meta=None):
        nonlocal puddle_seq
        puddle_seq += 1
        return {
            "puddleID": puddle_seq,
            "position": point_dict(position, timestamp=grounded_from_abs) if isinstance(position, tuple) else position,
            "groundedFromMs": grounded_from_abs - fight_start,
            "pickedUpAtMs": None,
            "transferCount": 0,
            "carriers": [],
            "spawn": spawn_meta,
            "sourceID": (spawn_meta or {}).get("sourceID"),
            "sourceInstance": (spawn_meta or {}).get("sourceInstance"),
        }

    # 生成时先放到地上（若有可靠坐标）
    for round_row in rounds:
        for spawn in round_row["spawns"]:
            if not spawn.get("position"):
                continue
            abs_ts = fight_start + int(spawn["spawnTimeMs"])
            ground.append(new_puddle(spawn["position"], abs_ts, spawn_meta=spawn))

    volatile_events = sorted(
        (
            event for event in debuffs
            if int(ability_id(event) or 0) == VOLATILE_VENOM and event.get("targetID") in players
        ),
        key=lambda row: int(row.get("timestamp") or 0),
    )

    for event in volatile_events:
        target_id = event.get("targetID")
        timestamp = int(event["timestamp"])
        rel_ms = timestamp - fight_start
        if is_apply(event):
            player_pos = _position_sample(position_index, target_id, timestamp)
            player_xy = _position_xy(player_pos)
            puddle = _match_puddle_for_pickup(ground, player_xy)
            if puddle is not None and puddle in ground:
                ground.remove(puddle)
                # 固化这一段「在地」区间，供撕裂时刻回放
                if puddle.get("groundedFromMs") is not None and puddle.get("position"):
                    completed_puddles.append({
                        "puddleID": puddle["puddleID"],
                        "position": dict(puddle["position"]),
                        "groundedFromMs": puddle["groundedFromMs"],
                        "pickedUpAtMs": rel_ms,
                        "transferCount": int(puddle.get("transferCount") or 0),
                        "carriers": list(puddle.get("carriers") or []),
                        "lastTickMs": puddle.get("lastTickMs"),
                        "sourceID": puddle.get("sourceID"),
                        "sourceInstance": puddle.get("sourceInstance"),
                    })
                # 若距上次落地很近，记为接力搬运
                if puddle.get("carriers") and (
                    rel_ms - int(puddle.get("groundedFromMs") or rel_ms) <= VENOM_TRANSFER_WINDOW_MS
                ):
                    puddle["transferCount"] = int(puddle.get("transferCount") or 0) + 1
                puddle["pickedUpAtMs"] = rel_ms
                puddle["groundedFromMs"] = None
            else:
                puddle = new_puddle(player_pos, timestamp)
                puddle["pickedUpAtMs"] = rel_ms
                puddle["groundedFromMs"] = None
            puddle.setdefault("carriers", []).append({
                **player_ref(players, actor_map, target_id),
                "applyTimeMs": rel_ms,
                "applyTime": fmt_ms(rel_ms),
                "pickupPosition": player_pos,
            })
            carrying[target_id] = puddle
            carrier_rows.append({
                **player_ref(players, actor_map, target_id),
                "phase": phase_at(rel_ms, markers),
                "applyTimeMs": rel_ms,
                "applyTime": fmt_ms(rel_ms),
                "removeTimeMs": None,
                "removeTime": None,
                "carryDurationMs": None,
                "dropPosition": None,
                "puddleID": puddle["puddleID"],
                "transferCount": puddle.get("transferCount") or 0,
                "kind": "pickup",
            })
            continue

        if not is_remove(event):
            continue
        puddle = carrying.pop(target_id, None)
        drop_position = _position_sample(position_index, target_id, timestamp)
        apply_rel = None
        if puddle and puddle.get("carriers"):
            apply_rel = puddle["carriers"][-1].get("applyTimeMs")
        row = {
            **player_ref(players, actor_map, target_id),
            "phase": phase_at(rel_ms, markers),
            "applyTimeMs": apply_rel,
            "applyTime": fmt_ms(apply_rel) if apply_rel is not None else None,
            "removeTimeMs": rel_ms,
            "removeTime": fmt_ms(rel_ms),
            "carryDurationMs": (rel_ms - apply_rel) if apply_rel is not None else None,
            "dropPosition": drop_position,
            "puddleID": (puddle or {}).get("puddleID"),
            "transferCount": (puddle or {}).get("transferCount") or 0,
            "kind": "drop",
        }
        carrier_rows.append(row)
        if puddle is None:
            puddle = new_puddle(drop_position, timestamp)
        else:
            if drop_position:
                puddle["position"] = drop_position
            puddle["groundedFromMs"] = rel_ms
            puddle["pickedUpAtMs"] = None
            if puddle.get("carriers"):
                puddle["carriers"][-1].update({
                    "removeTimeMs": rel_ms,
                    "removeTime": fmt_ms(rel_ms),
                    "carryDurationMs": row["carryDurationMs"],
                    "dropPosition": drop_position,
                })
        ground.append(puddle)
        round_match = next((item for item in reversed(rounds) if item["timeMs"] <= rel_ms), rounds[-1] if rounds else None)
        if round_match is not None:
            round_match["carriers"].append(row)
            round_match["drops"].append(row)

    # 用 1282408 地上毒液伤害源坐标刷新仍在地上的落点
    for event in sorted(damage_events or [], key=lambda row: int(row.get("timestamp") or 0)):
        if int(ability_id(event) or 0) != COALESCED_VENOM_DAMAGE:
            continue
        source_id = event.get("sourceID")
        source_instance = event.get("sourceInstance") or event.get("sourceInstanceID")
        point = _source_self_point(event)
        if not point:
            # 伤害打在玩家上时，顶层 x/y 常是玩家，不能用
            continue
        timestamp = int(event["timestamp"])
        rel_ms = timestamp - fight_start
        matched = None
        for puddle in ground:
            if source_id is not None and puddle.get("sourceID") == source_id:
                if source_instance is None or puddle.get("sourceInstance") in (None, source_instance):
                    matched = puddle
                    break
        if matched is None:
            matched = _nearest_ground_puddle(ground, point, max_yards=VENOM_PICKUP_MAX_YARDS)
        if matched is None:
            continue
        matched["position"] = point_dict(point, timestamp=timestamp)
        matched["lastTickMs"] = rel_ms
        if matched.get("sourceID") is None:
            matched["sourceID"] = source_id
            matched["sourceInstance"] = source_instance

    # 收尾：仍在地上的记为未再被捡起的区间
    for puddle in list(ground):
        if puddle.get("position") and puddle.get("groundedFromMs") is not None:
            completed_puddles.append({
                "puddleID": puddle["puddleID"],
                "position": dict(puddle["position"]) if isinstance(puddle.get("position"), dict) else puddle.get("position"),
                "groundedFromMs": puddle["groundedFromMs"],
                "pickedUpAtMs": None,
                "transferCount": int(puddle.get("transferCount") or 0),
                "carriers": list(puddle.get("carriers") or []),
                "lastTickMs": puddle.get("lastTickMs"),
                "sourceID": puddle.get("sourceID"),
                "sourceInstance": puddle.get("sourceInstance"),
            })

    for round_row in rounds:
        next_ms = rounds[round_row["index"]]["timeMs"] if round_row["index"] < len(rounds) else 10**12
        round_row["groundPuddles"] = [
            puddle for puddle in completed_puddles
            if puddle.get("position")
            and puddle.get("groundedFromMs") is not None
            and round_row["timeMs"] <= int(puddle["groundedFromMs"]) < next_ms
        ]

    drop_rows = [row for row in carrier_rows if row.get("kind") == "drop"]
    return {
        "rounds": rounds,
        "carriers": drop_rows,
        "pickups": [row for row in carrier_rows if row.get("kind") == "pickup"],
        "groundPuddles": completed_puddles,
        "evidenceNote": (
            "凝结毒液按落地/拾取状态机追踪，支持多次接力；"
            f"掉落后 {VENOM_TRANSFER_WINDOW_MS}ms 内再捡起记为搬运中转；"
            f"捡球时用玩家位置与放球点是否 ≤{VENOM_PICKUP_MAX_YARDS:g} 码判断同一球；"
            "撕裂几何只用「释放前仍在地上」的区间，优先 1282408 伤害源坐标。"
        ),
    }


def build_active_venom_points(toxic_deluge):
    """撕裂几何用「某时刻仍在地上」的凝结毒液，不是每一次 debuff 消失落点。"""
    points = []
    for puddle in toxic_deluge.get("groundPuddles") or []:
        position = puddle.get("position")
        grounded_from = puddle.get("groundedFromMs")
        if not position or grounded_from is None:
            continue
        points.append({
            "kind": "ground-venom",
            "puddleID": puddle.get("puddleID"),
            "position": position,
            "groundedFromMs": grounded_from,
            "pickedUpAtMs": puddle.get("pickedUpAtMs"),
            "transferCount": puddle.get("transferCount") or 0,
            "carriers": puddle.get("carriers") or [],
            "carrier": (puddle.get("carriers") or [{}])[-1].get("player") if puddle.get("carriers") else None,
            "player": (puddle.get("carriers") or [{}])[-1].get("player") if puddle.get("carriers") else None,
            "lastSeenMs": puddle.get("lastTickMs") if puddle.get("lastTickMs") is not None else grounded_from,
            "sourceID": puddle.get("sourceID"),
            "sourceInstance": puddle.get("sourceInstance"),
        })
    # 兼容旧结构：若尚无 groundPuddles，回退到最终 drops（仍去重接力）
    if points:
        return points
    for round_row in toxic_deluge.get("rounds") or []:
        for drop in round_row.get("drops") or []:
            if drop.get("dropPosition"):
                points.append({
                    "kind": "dropped-venom",
                    "carrier": drop.get("player"),
                    "player": drop.get("player"),
                    "playerID": drop.get("playerID"),
                    "position": drop["dropPosition"],
                    "groundedFromMs": drop.get("removeTimeMs"),
                    "pickedUpAtMs": None,
                    "lastSeenMs": drop.get("removeTimeMs"),
                    "transferCount": drop.get("transferCount") or 0,
                })
    return points


def active_venom_before_cast(points, cast_ts, fight_start, after_ms=None):
    """
    本轮撕裂应显示的凝结毒液：
    - 已在释放前落地，且释放前尚未再被捡起；
    - 上一轮撕裂后场上毒液已消除，故只保留落地时刻落在 (after_ms, cast] 的球
      （即本轮时间窗内生成/搬动落下的）。
    after_ms 为战斗相对毫秒；None 表示不设下界（首轮或未提供清场时刻）。
    """
    cast_rel = int(cast_ts) - int(fight_start)
    active = []
    for point in points or []:
        grounded = point.get("groundedFromMs")
        if grounded is None or int(grounded) > cast_rel:
            continue
        if after_ms is not None and int(grounded) <= int(after_ms):
            continue
        picked = point.get("pickedUpAtMs")
        if picked is not None and int(picked) <= cast_rel:
            continue
        active.append(point)
    return active


def previous_cone_sever_rel_ms(casts, cast_ts, fight_start):
    """上一轮锥形撕裂（撕裂/凋零撕裂）的战斗相对时刻；没有则 None。"""
    cast_abs = int(cast_ts)
    previous = [
        int(event["timestamp"])
        for event in (casts or [])
        if int(ability_id(event) or 0) in CONE_SEVER_IDS
        and is_cast_complete(event)
        and int(event.get("timestamp") or 0) < cast_abs
    ]
    if not previous:
        return None
    return max(previous) - int(fight_start)


def _rupture_stack_gain(debuffs, start, end):
    gains = []
    for event in _events_between(debuffs, start, end, {VENOM_RUPTURE}):
        if not is_apply(event):
            continue
        gains.append({
            "targetID": event.get("targetID"),
            "timestamp": int(event["timestamp"]),
            "stacks": int(event.get("stack") or 1),
        })
    return gains


def analyze_cone_sever(
    label,
    cast_ids,
    fight,
    casts,
    debuffs,
    position_index,
    actor_map,
    players,
    markers,
    active_points,
    actor_catalog,
    boss_actor_id=None,
    origin_index=None,
    npc_position_index=None,
):
    completed = [event for event in casts if int(ability_id(event) or 0) in cast_ids and is_cast_complete(event)]
    rounds = []
    for index, cast in enumerate(completed, start=1):
        timestamp = int(cast["timestamp"])
        source_id = cast.get("sourceID")
        fight_start = int(fight["startTime"])
        venom_pts = [point for point in active_points if point.get("kind") in {"ground-venom", "dropped-venom"}]
        manifest_pts = [point for point in active_points if point.get("kind") == "manifestation"]
        other_pts = [
            point for point in active_points
            if point.get("kind") not in {"ground-venom", "dropped-venom", "manifestation"}
        ]
        venom_after_ms = previous_cone_sever_rel_ms(casts, timestamp, fight_start)
        nearby_raw = (
            active_venom_before_cast(venom_pts, timestamp, fight_start, after_ms=venom_after_ms)
            + active_fixations_before_cast(manifest_pts, timestamp, fight_start)
            + active_points_near_cast(other_pts, timestamp, fight_start)
        )
        nearby_points = []
        for point in nearby_raw:
            if point.get("kind") == "manifestation":
                nearby_points.append(
                    enrich_manifest_point_at(point, npc_position_index or {}, position_index, timestamp)
                )
            else:
                nearby_points.append(point)
        spell = int(ability_id(cast) or 0)
        lock_ms, tank_id, facing_rule, _debuff = resolve_sever_facing_lock(
            casts, cast, debuffs=debuffs, debuff_ids=CAST_TO_TANK_DEBUFF_IDS.get(spell),
        )
        if tank_id is None:
            tank_id = cast.get("targetID")
        origin, facing_radians, facing_state, facing_inferred, tank_state = resolve_caster_origin_facing(
            position_index,
            source_id,
            boss_actor_id,
            timestamp,
            hint_points=nearby_points,
            target_id=tank_id,
            origin_actor_id=source_id or boss_actor_id,
            origin_index=origin_index,
            cast_event=cast,
            facing_timestamp=lock_ms,
            allow_hint_override=facing_rule not in {"tank-debuff", "cast-last-second"},
        )
        tank_position = None
        if tank_state:
            tank_position = point_dict(
                (tank_state["x"], tank_state["y"]),
                timestamp=lock_ms,
                reliable=tank_state.get("reliable"),
                offset_ms=tank_state.get("sampleOffsetMs"),
            )
        elif tank_id is not None:
            fallback = position_at(position_index, tank_id, lock_ms, max_offset_ms=POSITION_RELIABLE_MS)
            if fallback:
                tank_position = point_dict(
                    (fallback["x"], fallback["y"]),
                    timestamp=lock_ms,
                    reliable=fallback.get("reliable"),
                    offset_ms=fallback.get("sampleOffsetMs"),
                )
        in_cone = []
        uncleared = []
        cleared_manifests = []
        annotated_nearby = []
        classify_manifests = any(point.get("kind") == "manifestation" for point in nearby_points)
        for point in nearby_points:
            position = point.get("position") or point.get("manifestPosition")
            inside = False
            if position and origin is not None and facing_radians is not None:
                inside = in_frontal_cone(origin, facing_radians, (position["x"], position["y"]))
            if classify_manifests and point.get("kind") == "manifestation":
                verdict = classify_fixation_after_sever(point, timestamp, fight_start, inside)
                row = {**point, **verdict}
                annotated_nearby.append(row)
                if inside:
                    in_cone.append(row)
                if verdict["uncleared"]:
                    uncleared.append(row)
                else:
                    cleared_manifests.append(row)
            else:
                annotated_nearby.append(point)
                if inside:
                    in_cone.append(point)
        nearby_points = annotated_nearby
        rupture_gains = _rupture_stack_gain(debuffs, timestamp, timestamp + 2_500)
        inferred_cleared = max((row["stacks"] for row in rupture_gains), default=len(in_cone))
        facing_note = {
            "tank-debuff": "朝向按坦克获得易伤 debuff 时的位置锁定",
            "cast-last-second": "朝向按读条最后一秒的坦克位置锁定",
            "cast-complete": "朝向按读条完成时的坦克位置估算",
        }.get(facing_rule, "朝向按坦克位置估算")
        if classify_manifests:
            evidence_note = (
                f"具象消除以凝视 debuff 在释放后 {SOUL_SEVER_CLEAR_WINDOW_MS}ms 内是否消失为准；"
                f"锥内 {len([p for p in in_cone if p.get('kind') == 'manifestation'])}，"
                f"debuff 清掉 {len(cleared_manifests)}，未消掉 {len(uncleared)}；"
                "红线仅连未消掉凝视的玩家。"
            )
        else:
            evidence_note = (
                "示意图仅显示上一轮撕裂至本轮之间落地/搬动的毒液球；"
                "几何清场数来自锥形内的凝结毒液/恐惧具象坐标。"
            )
        rounds.append({
            "index": index,
            "label": label,
            "phase": phase_at(timestamp - int(fight["startTime"]), markers),
            "spellID": spell,
            "timeMs": timestamp - int(fight["startTime"]),
            "time": fmt_ms(timestamp - int(fight["startTime"])),
            "casterID": source_id,
            "caster": actor_name(actor_map, source_id),
            "origin": point_dict(origin, timestamp=timestamp, reliable=bool(facing_state and facing_state.get("reliable"))),
            "originRule": (facing_state or {}).get("positionRule"),
            "tankID": tank_id,
            "tankPosition": tank_position,
            "facingLockMs": lock_ms - fight_start,
            "facingRule": facing_rule,
            "facingRadians": facing_radians,
            "facingInferred": facing_inferred,
            "coneRadiusYards": CONE_RADIUS_YARDS,
            "coneHalfAngleDeg": CONE_HALF_ANGLE_DEG,
            "conePolygon": cone_polygon(origin, facing_radians),
            "clearedByGeometry": len(in_cone),
            "inferredClearedCount": inferred_cleared,
            "ruptureEvents": rupture_gains,
            "targetsInCone": in_cone,
            "nearbyPoints": nearby_points,
            "unclearedManifestations": uncleared if classify_manifests else [],
            "clearedManifestations": cleared_manifests if classify_manifests else [],
            "clearedByDebuff": len(cleared_manifests) if classify_manifests else None,
            "unclearedCount": len(uncleared) if classify_manifests else None,
            "evidenceNote": evidence_note,
        })
    return {"label": label, "castIDs": sorted(cast_ids), "rounds": rounds}


def analyze_guillotine(
    fight,
    casts,
    damage,
    debuffs,
    position_index,
    actor_map,
    players,
    markers,
    cast_ids,
    label,
    damage_ids=None,
    mark_ids=None,
    pulse_damage_id=None,
    in_range_damage_id=None,
    origin_index=None,
    boss_actor_id=None,
):
    """分摊后是否仍在 40 码内：用脉冲伤害后的范围内伤害证据，不用固定延迟估位置。

    P1：全团寡妇之触(1283631)时，圈内额外寡妇之吻(1283623)。
    P3：全团死亡低语(1299401)时，圈内额外死亡之拥(1299396)。
    """
    damage_ids = set(damage_ids or {GUILLOTINE_DAMAGE_ID})
    mark_ids = set(mark_ids or {GUILLOTINE_MARK})
    pulse_id = int(pulse_damage_id or WIDOW_TOUCH_DAMAGE_ID)
    in_range_id = int(in_range_damage_id or WIDOW_KISS_DAMAGE_ID)
    completed = [event for event in casts if int(ability_id(event) or 0) in cast_ids and is_cast_complete(event)]
    rounds = []
    for index, cast in enumerate(completed, start=1):
        timestamp = int(cast["timestamp"])
        share_hits = [
            event for event in _events_between(damage, timestamp - 500, timestamp + 3_000, damage_ids)
            if event.get("targetID") in players
        ]
        participants_by_id = {}
        for event in share_hits:
            target_id = event.get("targetID")
            hit_ts = int(event["timestamp"])
            position = (
                _position_sample(position_index, target_id, hit_ts)
                or _position_sample(position_index, target_id, timestamp)
            )
            prev = participants_by_id.get(target_id)
            amount = event_amount(event)
            if prev is None or float(amount or 0) >= float(prev.get("amount") or 0):
                participants_by_id[target_id] = {
                    **player_ref(players, actor_map, target_id),
                    "position": position or (prev or {}).get("position"),
                    "amount": amount,
                    "shareTimeMs": hit_ts - int(fight["startTime"]),
                }
        # 伤害事件缺失时，用处斩/冷酷处斩标记/治疗吸收施加补全分摊名单
        if not participants_by_id:
            for event in _events_between(debuffs, timestamp - 500, timestamp + 3_000, mark_ids):
                if not is_apply(event):
                    continue
                target_id = event.get("targetID")
                if target_id not in players or target_id in participants_by_id:
                    continue
                apply_ts = int(event["timestamp"])
                position = (
                    _position_sample(position_index, target_id, apply_ts)
                    or _position_sample(position_index, target_id, timestamp)
                )
                participants_by_id[target_id] = {
                    **player_ref(players, actor_map, target_id),
                    "position": position,
                    "amount": None,
                    "shareTimeMs": apply_ts - int(fight["startTime"]),
                }
        participants = list(participants_by_id.values())
        centroid = None
        if participants:
            xs = [row["position"]["x"] for row in participants if row.get("position")]
            ys = [row["position"]["y"] for row in participants if row.get("position")]
            if xs and ys:
                centroid = point_dict((sum(xs) / len(xs), sum(ys) / len(ys)))
        share_anchor = timestamp
        if share_hits:
            share_anchor = max(int(event["timestamp"]) for event in share_hits)
        elif participants:
            rels = [row.get("shareTimeMs") for row in participants if row.get("shareTimeMs") is not None]
            if rels:
                share_anchor = int(fight["startTime"]) + max(int(value) for value in rels)
        # 分摊后下一波全团脉冲；同波吃到范围内伤害 = 仍在 40 码内
        pulse_wave = _events_between(
            damage, share_anchor, share_anchor + GUILLOTINE_PULSE_SEARCH_MS, {pulse_id},
        )
        pulse_wave = [event for event in pulse_wave if event.get("targetID") in players]
        pulse_ts = None
        follow_up = []
        if pulse_wave:
            first_pulse = min(int(event["timestamp"]) for event in pulse_wave)
            pulse_ts = first_pulse
            pulse_cluster = [
                event for event in pulse_wave
                if abs(int(event["timestamp"]) - first_pulse) <= GUILLOTINE_PULSE_MATCH_MS
            ]
            if pulse_cluster:
                pulse_ts = max(int(event["timestamp"]) for event in pulse_cluster)
            in_range_hits = [
                event for event in _events_between(
                    damage,
                    first_pulse - GUILLOTINE_PULSE_MATCH_MS,
                    pulse_ts + GUILLOTINE_PULSE_MATCH_MS,
                    {in_range_id},
                )
                if event.get("targetID") in players
            ]
            by_id = {}
            for event in in_range_hits:
                target_id = event.get("targetID")
                hit_ts = int(event["timestamp"])
                position = (
                    _position_sample(position_index, target_id, hit_ts)
                    or _position_sample(position_index, target_id, pulse_ts)
                )
                distance = None
                if position and centroid:
                    distance = round(
                        distance_yards((position["x"], position["y"]), (centroid["x"], centroid["y"])),
                        1,
                    )
                prev = by_id.get(target_id)
                if prev is None or hit_ts <= int(prev.get("_hitTs") or hit_ts):
                    by_id[target_id] = {
                        **player_ref(players, actor_map, target_id),
                        "distanceFromShareYards": distance,
                        "position": position,
                        "stillInsideRange": True,
                        "checkTimeMs": hit_ts - int(fight["startTime"]),
                        "inRangeDamageID": in_range_id,
                        "_hitTs": hit_ts,
                    }
            follow_up = [{k: v for k, v in row.items() if k != "_hitTs"} for row in by_id.values()]
            follow_up.sort(key=lambda row: (row.get("player") or "", row.get("playerID") or 0))
        marked_players = sorted({
            event.get("targetID")
            for event in _events_between(debuffs, timestamp - 1_000, timestamp + 30_000, mark_ids)
            if is_apply(event) and event.get("targetID") in players
        })
        caster_id = cast.get("sourceID") if cast.get("sourceID") is not None else boss_actor_id
        boss_position = boss_field_position(origin_index, caster_id, timestamp, cast_event=cast)
        rounds.append({
            "index": index,
            "label": label,
            "phase": phase_at(timestamp - int(fight["startTime"]), markers),
            "spellID": int(ability_id(cast) or 0),
            "timeMs": timestamp - int(fight["startTime"]),
            "time": fmt_ms(timestamp - int(fight["startTime"])),
            "participantCount": len(participants),
            "participants": participants,
            "shareCentroid": centroid,
            "bossPosition": boss_position,
            "dangerRadiusYards": GUILLOTINE_RANGE_YARDS,
            "pulseDamageID": pulse_id,
            "inRangeDamageID": in_range_id,
            "pulseTimeMs": (pulse_ts - int(fight["startTime"])) if pulse_ts is not None else None,
            "stillInsideRange": follow_up,
            "guillotineMarks": [player_ref(players, actor_map, player_id) for player_id in marked_players],
        })
    return {"label": label, "rounds": rounds}


def _find_dreadmarch_remove(debuffs, target_id, apply_ts, fight_end):
    return next(
        (
            row for row in debuffs
            if row.get("targetID") == target_id
            and int(ability_id(row) or 0) in DREADMARCH_DEBUFF_IDS
            and is_remove(row)
            and int(row["timestamp"]) >= int(apply_ts)
        ),
        None,
    )


def _debuff_activity_near(debuffs, target_id, spell_ids, timestamp, window_ms):
    """目标在 timestamp 附近是否有指定 debuff 的施加/刷新/移除。"""
    hits = []
    low = int(timestamp) - int(window_ms)
    high = int(timestamp) + int(window_ms)
    for event in debuffs or []:
        if event.get("targetID") != target_id:
            continue
        if int(ability_id(event) or 0) not in spell_ids:
            continue
        ts = int(event.get("timestamp") or 0)
        if low <= ts <= high and (is_apply(event) or is_remove(event)):
            hits.append(event)
    return hits


def _annotate_dreadmarch_manifest_collisions(
    applications, cast_times, fight_start, fight_end, debuffs, use_malevolent_resonance=False,
):
    """
    每轮恐惧行军：第一次成功救人之后、下一轮 Boss 释放之前，
    新获得的 1297445 视为撞到恐惧具象（或由其引发的二次心控）。
    史诗可额外用恶毒共鸣印证；英雄仅结合凝视变化。
    """
    first_rescue_by_round = {}
    for row in applications:
        round_index = row.get("roundIndex")
        if not round_index or not row.get("rescued") or row.get("removedTimeMs") is None:
            continue
        remove_abs = int(fight_start) + int(row["removedTimeMs"])
        prev = first_rescue_by_round.get(round_index)
        if prev is None or remove_abs < prev:
            first_rescue_by_round[round_index] = remove_abs

    for row in applications:
        apply_abs = int(fight_start) + int(row["appliedTimeMs"])
        round_index = row.get("roundIndex")
        cast_abs = None
        if row.get("castTimeMs") is not None:
            cast_abs = int(fight_start) + int(row["castTimeMs"])
        elif round_index and 1 <= int(round_index) <= len(cast_times):
            cast_abs = cast_times[int(round_index) - 1]

        next_cast_abs = int(fight_end)
        if cast_abs is not None:
            later = [ts for ts in cast_times if ts > cast_abs]
            if later:
                next_cast_abs = min(later)
        elif round_index and int(round_index) < len(cast_times):
            next_cast_abs = cast_times[int(round_index)]

        first_rescue_abs = first_rescue_by_round.get(round_index)
        # 也可能跨轮：落在「上一轮首次救人 → 本轮施法」之间
        if first_rescue_abs is None and round_index and int(round_index) > 1:
            first_rescue_abs = first_rescue_by_round.get(int(round_index) - 1)
            if cast_abs is not None:
                next_cast_abs = cast_abs

        near_initial_wave = (
            cast_abs is not None
            and cast_abs - 1_500 <= apply_abs <= cast_abs + DREADMARCH_INITIAL_APPLY_MS
        )
        in_post_rescue_window = (
            first_rescue_abs is not None
            and first_rescue_abs < apply_abs < next_cast_abs
        )

        fixation_hits = _debuff_activity_near(
            debuffs, row.get("playerID"), {FIXATION}, apply_abs, DREADMARCH_FIXATION_HINT_MS,
        )
        resonance_hits = []
        if use_malevolent_resonance:
            resonance_hits = _debuff_activity_near(
                debuffs, row.get("playerID"), MANIFEST_COLLISION_DEBUFF_IDS, apply_abs, DREADMARCH_FIXATION_HINT_MS,
            )
        fixation_hint = bool(fixation_hits)
        resonance_hint = bool(resonance_hits)

        hit_manifest = False
        trigger_kind = "boss-cast" if near_initial_wave else "unknown"
        confidence = "low"
        if in_post_rescue_window and not near_initial_wave:
            hit_manifest = True
            trigger_kind = "manifest-collision"
            if resonance_hint:
                confidence = "high"
            elif fixation_hint:
                confidence = "medium"
            else:
                confidence = "medium"

        row["hitManifestation"] = hit_manifest
        row["triggerKind"] = trigger_kind
        row["collisionConfidence"] = confidence if hit_manifest else None
        row["fixationDebuffChanged"] = fixation_hint
        row["manifestCollisionDebuff"] = resonance_hint if use_malevolent_resonance else None
        if hit_manifest:
            if use_malevolent_resonance:
                hint = (
                    "同时段见恶毒共鸣/凝视变化。"
                    if (resonance_hint or fixation_hint)
                    else "可结合凝视(1285911)或恶毒共鸣变化进一步核对。"
                )
            else:
                hint = (
                    "同时段见凝视变化。"
                    if fixation_hint
                    else "可结合凝视(1285911)变化进一步核对；恶毒共鸣为史诗机制，英雄不做证据。"
                )
            row["evidenceNote"] = (
                "首次救人后、下一轮恐惧行军释放前再次获得 1297445，判定为撞到恐惧具象；" + hint
            )


def analyze_dreadmarch(fight, casts, debuffs, damage, friendly_damage, deaths, actor_map, players, markers):
    del damage, friendly_damage  # 救人只看 removedebuff，不再扫全场友伤
    cast_rows = sorted(
        [event for event in casts if int(ability_id(event) or 0) in DREADMARCH_CAST_IDS and is_cast_complete(event)],
        key=lambda row: int(row.get("timestamp") or 0),
    )
    cast_times = [int(event["timestamp"]) for event in cast_rows]
    fight_start = int(fight["startTime"])
    fight_end = int(fight["endTime"])
    # 恶毒共鸣仅史诗；英雄只靠救人后二次心控 + 凝视变化
    use_malevolent_resonance = int(fight.get("difficulty") or 0) == 5
    applications = []
    for event in sorted(debuffs, key=lambda row: int(row.get("timestamp") or 0)):
        if int(ability_id(event) or 0) not in DREADMARCH_DEBUFF_IDS or not is_apply(event):
            continue
        target_id = event.get("targetID")
        if target_id not in players:
            continue
        apply_ts = int(event["timestamp"])
        round_index = None
        round_cast_ts = None
        for index, cast_ts in enumerate(cast_times):
            next_cast = cast_times[index + 1] if index + 1 < len(cast_times) else fight_end
            if cast_ts - 1_500 <= apply_ts < next_cast:
                round_index = index + 1
                round_cast_ts = cast_ts
                break
        if round_index is None and cast_times:
            preceding = [cast_ts for cast_ts in cast_times if cast_ts <= apply_ts]
            if preceding and apply_ts - preceding[-1] <= 8_000:
                round_index = cast_times.index(preceding[-1]) + 1
                round_cast_ts = preceding[-1]
        remove_event = _find_dreadmarch_remove(debuffs, target_id, apply_ts, fight_end)
        remove_ts = int(remove_event["timestamp"]) if remove_event else None
        window_end = remove_ts or fight_end
        death_event = next(
            (
                row for row in deaths
                if row.get("targetID") == target_id and apply_ts <= int(row["timestamp"]) <= window_end + 2_000
            ),
            None,
        )
        death_ts = int(death_event["timestamp"]) if death_event else None
        died_before_remove = bool(death_ts and (remove_ts is None or death_ts < remove_ts))
        rescued = bool(remove_event) and not died_before_remove
        applications.append({
            **player_ref(players, actor_map, target_id),
            "roundIndex": round_index,
            "castTimeMs": (round_cast_ts - fight_start) if round_cast_ts else None,
            "castTime": fmt_ms(round_cast_ts - fight_start) if round_cast_ts else None,
            "phase": phase_at(apply_ts - fight_start, markers),
            "appliedTimeMs": apply_ts - fight_start,
            "appliedTime": fmt_ms(apply_ts - fight_start),
            "removedTimeMs": remove_ts - fight_start if remove_ts else None,
            "removedTime": fmt_ms(remove_ts - fight_start) if remove_ts else None,
            "rescued": rescued,
            "diedWhileControlled": died_before_remove,
            "failed": died_before_remove or not rescued,
            "hitManifestation": False,
            "triggerKind": "unknown",
            "evidenceNote": "救援成功以 1297445 removedebuff 为准，不再拉取对被控玩家的友伤命中。",
        })

    _annotate_dreadmarch_manifest_collisions(
        applications, cast_times, fight_start, fight_end, debuffs,
        use_malevolent_resonance=use_malevolent_resonance,
    )

    rounds = []
    grouped = defaultdict(list)
    for row in applications:
        key = row.get("roundIndex") or 0
        grouped[key].append(row)
    for index, cast in enumerate(cast_rows, start=1):
        targets = grouped.get(index, [])
        collisions = [row for row in targets if row.get("hitManifestation")]
        initial = [row for row in targets if not row.get("hitManifestation")]
        rounds.append({
            "index": index,
            "phase": phase_at(int(cast["timestamp"]) - fight_start, markers),
            "timeMs": int(cast["timestamp"]) - fight_start,
            "time": fmt_ms(int(cast["timestamp"]) - fight_start),
            "targetCount": len(initial),
            "rescuedCount": sum(1 for row in initial if row["rescued"]),
            "failedCount": sum(1 for row in initial if row["failed"]),
            "manifestCollisionCount": len(collisions),
            "targets": targets,
            "manifestCollisions": collisions,
        })
    unassigned = grouped.get(0, [])
    if unassigned:
        collisions = [row for row in unassigned if row.get("hitManifestation")]
        rounds.append({
            "index": len(rounds) + 1,
            "phase": unassigned[0].get("phase"),
            "timeMs": unassigned[0]["appliedTimeMs"],
            "time": unassigned[0]["appliedTime"],
            "targetCount": len(unassigned),
            "rescuedCount": sum(1 for row in unassigned if row["rescued"]),
            "failedCount": sum(1 for row in unassigned if row["failed"]),
            "manifestCollisionCount": len(collisions),
            "targets": unassigned,
            "manifestCollisions": collisions,
            "unassigned": True,
        })
    collision_rows = [row for row in applications if row.get("hitManifestation")]
    if use_malevolent_resonance:
        evidence_note = (
            "Boss 点名波次后第一次成功救人起、至下一轮恐惧行军释放前，"
            "新获得的 1297445 记为撞到恐惧具象；史诗可结合凝视(1285911)/恶毒共鸣核对。"
        )
    else:
        evidence_note = (
            "Boss 点名波次后第一次成功救人起、至下一轮恐惧行军释放前，"
            "新获得的 1297445 记为撞到恐惧具象；可结合凝视(1285911)变化核对。"
            "恶毒共鸣为史诗机制，英雄不做证据。"
        )
    return {
        "rounds": rounds,
        "applications": applications,
        "manifestCollisions": collision_rows,
        "manifestCollisionCount": len(collision_rows),
        "useMalevolentResonance": use_malevolent_resonance,
        "evidenceNote": evidence_note,
    }


def analyze_manifestations(
    fight,
    debuffs,
    npc_position_index,
    actor_map,
    players,
    actor_catalog,
    markers,
    enemy_deaths=None,
    position_index=None,
):
    fixations = []
    active = {}
    for event in sorted(debuffs, key=lambda row: int(row.get("timestamp") or 0)):
        if int(ability_id(event) or 0) != FIXATION:
            continue
        target_id = event.get("targetID")
        if target_id not in players:
            continue
        timestamp = int(event["timestamp"])
        source_id = event.get("sourceID")
        source_instance = event.get("sourceInstance") or event.get("sourceInstanceID")
        manifest = resolve_manifest_instance(source_id, source_instance, actor_catalog)
        if is_apply(event):
            if not manifest.get("isManifestNpc"):
                continue
            row = {
                **player_ref(players, actor_map, target_id),
                "phase": phase_at(timestamp - int(fight["startTime"]), markers),
                "applyTimeMs": timestamp - int(fight["startTime"]),
                "applyTime": fmt_ms(timestamp - int(fight["startTime"])),
                "removeTimeMs": None,
                "removeTime": None,
                "manifest": manifest,
                "manifestPosition": None,
                "playerPosition": None,
            }
            active[(target_id, source_id, source_instance)] = row
            fixations.append(row)
            continue
        if not is_remove(event):
            continue
        key = (target_id, source_id, source_instance)
        row = active.pop(key, None)
        if row:
            row["removeTimeMs"] = timestamp - int(fight["startTime"])
            row["removeTime"] = fmt_ms(timestamp - int(fight["startTime"]))
            row["removeTimestamp"] = timestamp

    fight_end = int(fight["endTime"])
    for row in fixations:
        manifest = row.get("manifest") or {}
        source_id = manifest.get("sourceID")
        source_instance = manifest.get("sourceInstance")
        apply_abs = int(fight["startTime"]) + int(row["applyTimeMs"])
        remove_abs = fight["startTime"] + row["removeTimeMs"] if row.get("removeTimeMs") is not None else None
        death_ts = _npc_instance_death_ts(enemy_deaths, source_id, source_instance)
        despawn_ts = min(ts for ts in (remove_abs, death_ts, fight_end) if ts is not None)
        # 具象坐标：消失前最后一次 NPC 自身采样（不是被点名玩家）
        position = _position_last_at_or_before(npc_position_index, source_id, source_instance, despawn_ts)
        if not position:
            position = _position_sample_npc(npc_position_index, source_id, source_instance, apply_abs)
        row["manifestPosition"] = position
        row["despawnTimeMs"] = int(despawn_ts) - int(fight["startTime"])
        row["despawnTime"] = fmt_ms(row["despawnTimeMs"])
        if position_index is not None and row.get("playerID") is not None:
            player_state = position_at(
                position_index, row["playerID"], apply_abs, max_offset_ms=POSITION_RELIABLE_MS,
            )
            if player_state:
                row["playerPosition"] = point_dict(
                    (player_state["x"], player_state["y"]),
                    timestamp=apply_abs,
                    reliable=player_state.get("reliable"),
                    offset_ms=player_state.get("sampleOffsetMs"),
                )

    manifestation_points = []
    for row in fixations:
        manifestation_points.append({
            "kind": "manifestation",
            "manifest": row["manifest"],
            "playerID": row.get("playerID"),
            "player": row["player"],
            "classColor": row.get("classColor"),
            "icon": row.get("icon"),
            "role": row.get("role"),
            "specID": row.get("specID"),
            "specName": row.get("specName"),
            "className": row.get("className"),
            "position": row.get("manifestPosition"),
            "manifestPosition": row.get("manifestPosition"),
            "playerPosition": row.get("playerPosition"),
            "lastSeenMs": int(fight["startTime"]) + int(row.get("despawnTimeMs") or row["applyTimeMs"]),
            "applyTimeMs": row["applyTimeMs"],
            "removeTimeMs": row.get("removeTimeMs"),
            "despawnTimeMs": row.get("despawnTimeMs"),
        })
    return {"fixations": fixations, "activePoints": manifestation_points}


def enrich_manifest_point_at(point, npc_position_index, position_index, timestamp):
    """在灵魂撕裂释放前一刻刷新具象 NPC 坐标与被点名玩家坐标。"""
    if not point:
        return point
    row = dict(point)
    # 释放前：取该时刻（含）之前最后一次 NPC 自身采样
    sample_ts = int(timestamp) - 1 if timestamp else timestamp
    manifest = row.get("manifest") or {}
    source_id = manifest.get("sourceID")
    source_instance = manifest.get("sourceInstance")
    npc_pos = _position_last_at_or_before(npc_position_index, source_id, source_instance, sample_ts)
    if not npc_pos:
        npc_pos = _position_sample_npc(npc_position_index, source_id, source_instance, sample_ts)
    if npc_pos:
        row["position"] = npc_pos
        row["manifestPosition"] = npc_pos
    player_id = row.get("playerID")
    if position_index is not None and player_id is not None:
        player_state = position_at(position_index, player_id, sample_ts, max_offset_ms=POSITION_RELIABLE_MS)
        if player_state:
            row["playerPosition"] = point_dict(
                (player_state["x"], player_state["y"]),
                timestamp=sample_ts,
                reliable=player_state.get("reliable"),
                offset_ms=player_state.get("sampleOffsetMs"),
            )
    return row


def analyze_soul_sever(
    fight,
    casts,
    deaths,
    position_index,
    actor_map,
    markers,
    manifestation_points,
    boss_actor_id=None,
    origin_index=None,
    debuffs=None,
    npc_position_index=None,
):
    completed = [event for event in casts if int(ability_id(event) or 0) in SOUL_SEVER_IDS and is_cast_complete(event)]
    rounds = []
    for index, cast in enumerate(completed, start=1):
        timestamp = int(cast["timestamp"])
        source_id = cast.get("sourceID")
        fight_start = int(fight["startTime"])
        active_before = active_fixations_before_cast(manifestation_points, timestamp, fight_start)
        nearby_points = [
            enrich_manifest_point_at(point, npc_position_index or {}, position_index, timestamp)
            for point in active_before
        ]
        lock_ms, tank_id, facing_rule, _debuff = resolve_sever_facing_lock(
            casts, cast, debuffs=debuffs, debuff_ids=SOUL_SEVER_TANK_DEBUFF_IDS,
        )
        if tank_id is None:
            tank_id = cast.get("targetID")
        origin, facing_radians, facing_state, facing_inferred, tank_state = resolve_caster_origin_facing(
            position_index,
            source_id,
            boss_actor_id,
            timestamp,
            hint_points=nearby_points,
            target_id=tank_id,
            origin_actor_id=source_id or boss_actor_id,
            origin_index=origin_index,
            cast_event=cast,
            facing_timestamp=lock_ms,
            allow_hint_override=facing_rule not in {"tank-debuff", "cast-last-second"},
        )
        in_cone = []
        uncleared = []
        cleared = []
        annotated = []
        for point in nearby_points:
            position = point.get("position") or point.get("manifestPosition")
            inside = False
            if position and origin is not None and facing_radians is not None:
                inside = in_frontal_cone(origin, facing_radians, (position["x"], position["y"]))
            verdict = classify_fixation_after_sever(point, timestamp, fight_start, inside)
            row = {**point, **verdict}
            annotated.append(row)
            if inside:
                in_cone.append(row)
            if verdict["uncleared"]:
                uncleared.append(row)
            else:
                cleared.append(row)
        cleared_deaths = [
            event for event in deaths
            if timestamp - 500 <= int(event.get("timestamp") or 0) <= timestamp + 2_000
            and event.get("targetID") not in (None,)
        ]
        tank_position = None
        if tank_state:
            tank_position = point_dict(
                (tank_state["x"], tank_state["y"]),
                timestamp=lock_ms,
                reliable=tank_state.get("reliable"),
                offset_ms=tank_state.get("sampleOffsetMs"),
            )
        elif tank_id is not None:
            fallback = position_at(position_index, tank_id, lock_ms, max_offset_ms=POSITION_RELIABLE_MS)
            if fallback:
                tank_position = point_dict(
                    (fallback["x"], fallback["y"]),
                    timestamp=lock_ms,
                    reliable=fallback.get("reliable"),
                    offset_ms=fallback.get("sampleOffsetMs"),
                )
        rounds.append({
            "index": index,
            "phase": phase_at(timestamp - int(fight["startTime"]), markers),
            "spellID": int(ability_id(cast) or 0),
            "timeMs": timestamp - int(fight["startTime"]),
            "time": fmt_ms(timestamp - int(fight["startTime"])),
            "origin": point_dict(origin, timestamp=timestamp),
            "facingRadians": facing_radians,
            "facingInferred": facing_inferred,
            "facingLockMs": lock_ms - fight_start,
            "facingRule": facing_rule,
            "tankID": tank_id,
            "tankPosition": tank_position,
            "coneRadiusYards": CONE_RADIUS_YARDS,
            "conePolygon": cone_polygon(origin, facing_radians),
            "manifestationsInCone": in_cone,
            "nearbyPoints": annotated,
            "unclearedManifestations": uncleared,
            "clearedManifestations": cleared,
            "clearedByGeometry": len(in_cone),
            "clearedByDebuff": len(cleared),
            "unclearedCount": len(uncleared),
            "addDeathSignals": len(cleared_deaths),
            "evidenceNote": (
                f"具象坐标取灵魂撕裂释放前；"
                f"锥内 {len(in_cone)}，debuff 清掉 {len(cleared)}，未消掉 {len(uncleared)}；"
                f"红线仅连未消掉凝视的玩家。"
            ),
        })
    return {"rounds": rounds}


def analyze_gloombomb(
    fight, casts, debuffs, position_index, actor_map, players, markers,
    origin_index=None, boss_actor_id=None,
):
    completed = [event for event in casts if int(ability_id(event) or 0) in GLOOMBOMB_CAST_IDS and is_cast_complete(event)]
    debuff_rows = sorted(debuffs, key=lambda row: int(row.get("timestamp") or 0))
    fight_start = int(fight["startTime"])
    rounds = []
    for index, cast in enumerate(completed, start=1):
        timestamp = int(cast["timestamp"])
        next_cast = int(completed[index]["timestamp"]) if index < len(completed) else timestamp + 20_000
        apply_window_end = min(next_cast, timestamp + 8_000)
        targets = []
        seen = set()
        for event in _events_between(debuff_rows, timestamp - 500, apply_window_end, GLOOMBOMB_DEBUFF_IDS):
            if not is_apply(event):
                continue
            target_id = event.get("targetID")
            if target_id not in players or target_id in seen:
                continue
            seen.add(target_id)
            apply_ts = int(event["timestamp"])
            remove_event = _first_remove_after(debuff_rows, target_id, apply_ts, GLOOMBOMB_DEBUFF_IDS)
            explode_ts = int(remove_event["timestamp"]) if remove_event else None
            position = _position_sample(position_index, target_id, explode_ts) if explode_ts else None
            targets.append({
                **player_ref(players, actor_map, target_id),
                "applyTimeMs": apply_ts - fight_start,
                "applyTime": fmt_ms(apply_ts - fight_start),
                "explodeTimeMs": (explode_ts - fight_start) if explode_ts else None,
                "explodeTime": fmt_ms(explode_ts - fight_start) if explode_ts else None,
                "position": position,
            })
        named_ids = {row["playerID"] for row in targets}
        spacing = []
        for left_index, left in enumerate(targets):
            for right in targets[left_index + 1:]:
                if not left.get("position") or not right.get("position"):
                    continue
                distance = distance_yards(
                    (left["position"]["x"], left["position"]["y"]),
                    (right["position"]["x"], right["position"]["y"]),
                )
                spacing.append({
                    "left": left["player"],
                    "right": right["player"],
                    "distanceYards": round(distance, 1),
                    "tooClose": distance < GLOOMBOMB_RADIUS_YARDS,
                })
        nearby_unnamed = []
        collateral_hits = []
        seen_nearby = set()
        seen_collateral = set()
        for target in targets:
            explode_rel = target.get("explodeTimeMs")
            origin = target.get("position")
            if explode_rel is None or not origin:
                target["nearbyUnnamed"] = []
                target["collateralGravebound"] = []
                continue
            explode_ts = fight_start + int(explode_rel)
            gb_start = explode_ts - 250
            gb_end = explode_ts + GLOOMBOMB_GRAVEBOUND_WINDOW_MS
            nearby_rows = []
            collateral_rows = []
            for player_id in players:
                if player_id in named_ids:
                    continue
                other_pos = _position_sample(position_index, player_id, explode_ts)
                if not other_pos:
                    continue
                distance = distance_yards(
                    (origin["x"], origin["y"]),
                    (other_pos["x"], other_pos["y"]),
                )
                if distance >= GLOOMBOMB_RADIUS_YARDS:
                    continue
                gravebound = _gravebound_apply_in_window(debuff_rows, player_id, gb_start, gb_end)
                row = {
                    **player_ref(players, actor_map, player_id),
                    "distanceYards": round(distance, 1),
                    "position": other_pos,
                    "fromPlayer": target["player"],
                    "fromPlayerID": target["playerID"],
                    "receivedGravebound": bool(gravebound),
                    "graveboundApplyTimeMs": (int(gravebound["timestamp"]) - fight_start) if gravebound else None,
                    "graveboundApplyTime": fmt_ms(int(gravebound["timestamp"]) - fight_start) if gravebound else None,
                }
                nearby_rows.append(row)
                if player_id not in seen_nearby:
                    nearby_unnamed.append(row)
                    seen_nearby.add(player_id)
                if gravebound:
                    collateral_rows.append(row)
                    if player_id not in seen_collateral:
                        collateral_hits.append(row)
                        seen_collateral.add(player_id)
            nearby_rows.sort(key=lambda row: (row["distanceYards"], row["player"]))
            target["nearbyUnnamed"] = nearby_rows
            target["collateralGravebound"] = collateral_rows
        too_close = [row for row in spacing if row["tooClose"]]
        caster_id = cast.get("sourceID") if cast.get("sourceID") is not None else boss_actor_id
        boss_position = boss_field_position(origin_index, caster_id, timestamp, cast_event=cast)
        rounds.append({
            "index": index,
            "phase": phase_at(timestamp - fight_start, markers),
            "timeMs": timestamp - fight_start,
            "time": fmt_ms(timestamp - fight_start),
            "targetCount": len(targets),
            "targets": targets,
            "bossPosition": boss_position,
            "spreadRadiusYards": GLOOMBOMB_RADIUS_YARDS,
            "pairSpacing": spacing,
            "tooClosePairs": too_close,
            "nearbyUnnamed": nearby_unnamed,
            "collateralHits": collateral_hits,
            "nearbyUnnamedCount": len(nearby_unnamed),
            "collateralCount": len(collateral_hits),
            "failed": bool(too_close or collateral_hits),
        })
    return {
        "rounds": rounds,
        "evidenceNote": (
            "点名以 1310881 施加/移除为准；只列出爆炸时 15 码内、且 2 秒内获得墓缚 1286837 的非点名玩家。"
        ),
    }


def _gravebound_damage_kill_id(death_event, damage_events=None):
    """只认墓缚伤害打死：killingAbility，或归因缺失时墓缚伤害 overkill。"""
    kill_id = int(death_event.get("killingAbilityGameID") or 0)
    if kill_id in GRAVEBOUND_DAMAGE_IDS:
        return kill_id
    if kill_id:
        return None
    death_ts = int(death_event.get("timestamp") or 0)
    target_id = death_event.get("targetID")
    for event in damage_events or []:
        if event.get("targetID") != target_id:
            continue
        spell = int(ability_id(event) or 0)
        if spell not in GRAVEBOUND_DAMAGE_IDS:
            continue
        if int(event.get("overkill") or 0) <= 0:
            continue
        ts = int(event.get("timestamp") or 0)
        if abs(ts - death_ts) <= GRAVEBOUND_KILL_OVERKILL_WINDOW_MS:
            return spell
    return None


def _is_gravebound_damage_death(row):
    if row.get("killedByGraveboundDamage") is False:
        return False
    spell = int(row.get("deathAbilityID") or 0)
    if spell and spell not in GRAVEBOUND_DAMAGE_IDS:
        return False
    return True


def analyze_gravebound_failures(fight, debuffs, deaths, actor_map, players, damage_events=None):
    """
    墓缚致死：只统计被墓缚伤害打死的玩家。
    带墓缚但死于其他技能不计入；死亡时是否仍带 1286837 仅作标注。
    """
    fight_start = int(fight["startTime"])
    fight_end = int(fight["endTime"])
    open_applies = defaultdict(list)
    intervals = defaultdict(list)  # playerID -> [(apply_abs, remove_abs)]
    for event in sorted(debuffs or [], key=lambda row: int(row.get("timestamp") or 0)):
        spell = int(ability_id(event) or 0)
        if spell not in GRAVEBOUND_DEBUFF_IDS and spell not in GRAVEBOUND_IDS:
            continue
        # 1308330 主要是伤害，也可能出现在 debuff 流；debuff 区间优先 1286837
        if spell not in GRAVEBOUND_DEBUFF_IDS and spell != 1286837:
            continue
        target_id = event.get("targetID")
        if target_id not in players:
            continue
        timestamp = int(event["timestamp"])
        if is_apply(event):
            open_applies[target_id].append(timestamp)
        elif is_remove(event) and open_applies[target_id]:
            apply_ts = open_applies[target_id].pop(0)
            intervals[target_id].append((apply_ts, timestamp))
    for target_id, applies in open_applies.items():
        for apply_ts in applies:
            intervals[target_id].append((apply_ts, fight_end))

    def had_gravebound_at(target_id, timestamp):
        return any(apply_ts <= timestamp <= remove_ts for apply_ts, remove_ts in intervals.get(target_id) or [])

    rows = []
    seen = set()
    for event in sorted(deaths or [], key=lambda row: int(row.get("timestamp") or 0)):
        target_id = event.get("targetID")
        if target_id not in players:
            continue
        death_ts = int(event.get("timestamp") or 0)
        kill_id = _gravebound_damage_kill_id(event, damage_events)
        if not kill_id:
            continue
        key = (target_id, death_ts // 500)
        if key in seen:
            continue
        seen.add(key)
        apply_rel = None
        for apply_ts, remove_ts in intervals.get(target_id) or []:
            if apply_ts <= death_ts <= remove_ts:
                apply_rel = apply_ts - fight_start
                break
        rows.append({
            **player_ref(players, actor_map, target_id),
            "timeMs": death_ts - fight_start,
            "time": fmt_ms(death_ts - fight_start),
            "graveboundActive": had_gravebound_at(target_id, death_ts),
            "graveboundApplyTimeMs": apply_rel,
            "graveboundApplyTime": fmt_ms(apply_rel) if apply_rel is not None else None,
            "deathAbilityID": kill_id,
            "deathAbility": spell_name(kill_id, SPELLS),
            "killedByGraveboundDamage": True,
        })
    return {
        "failures": rows,
        "evidenceNote": (
            "只统计墓缚伤害（1308330/1297906/1286837）打死的玩家；"
            "带墓缚但死于其他技能不计入。死亡时是否仍带 1286837 仅作标注。"
        ),
    }


def _nightfall_round_end(fight, casts_rows, index, start_ts):
    if index < len(casts_rows):
        return int(casts_rows[index]["timestamp"]) - 1
    return min(int(fight["endTime"]), start_ts + NIGHTFALL_ROUND_MAX_MS)


def _veil_shield_span(buff_rows, start_ts, end_ts):
    """配对本轮 1286912：只认完整 applybuff/removebuff，忽略层数跳动。"""
    apply_event = next(
        (
            event for event in buff_rows
            if int(ability_id(event) or 0) == VEIL_SHIELD
            and event_type(event) == "applybuff"
            and start_ts - NIGHTFALL_SHIELD_APPLY_LOOKBACK_MS <= int(event["timestamp"]) <= end_ts
        ),
        None,
    )
    remove_start = int(apply_event["timestamp"]) if apply_event else start_ts
    remove_event = next(
        (
            event for event in buff_rows
            if int(ability_id(event) or 0) == VEIL_SHIELD
            and event_type(event) == "removebuff"
            and remove_start <= int(event["timestamp"]) <= end_ts
        ),
        None,
    )
    return apply_event, remove_event


def _is_nightfall_interrupt(event):
    extra = int(event.get("extraAbilityGameID") or 0)
    if extra not in NIGHTFALL_INTERRUPTED_SPELLS:
        return False
    return event_type(event) in {"", "interrupt"}


def analyze_eternal_nightfall(
    fight,
    casts,
    enemy_buffs,
    interrupts,
    actor_map,
    players=None,
    friendly_damage=None,
    actor_rows=None,
    shield_target_id=None,
    markers=None,
    friendly_casts=None,
):
    del friendly_damage, shield_target_id  # 破盾只看 1286912 removebuff，不再统计打盾命中
    players = players or {}
    pet_owners = _pet_owner_map(actor_rows)
    casts_rows = [
        event for event in casts
        if int(ability_id(event) or 0) == ETERNAL_NIGHTFALL and event_type(event) == "begincast"
    ]
    interrupt_rows = [
        event for event in list(interrupts or []) + list(friendly_casts or [])
        if _is_nightfall_interrupt(event)
    ]
    buff_rows = sorted(enemy_buffs or [], key=lambda row: int(row.get("timestamp") or 0))
    fight_start = int(fight["startTime"])
    rounds = []
    for index, cast in enumerate(casts_rows, start=1):
        timestamp = int(cast["timestamp"])
        end = _nightfall_round_end(fight, casts_rows, index, timestamp)
        shield_apply, shield_remove = _veil_shield_span(buff_rows, timestamp, end)
        window_interrupts = [
            event for event in interrupt_rows
            if timestamp <= int(event.get("timestamp") or 0) <= end
        ]
        interrupt = window_interrupts[-1] if window_interrupts else None
        cast_success = any(
            event for event in casts
            if int(ability_id(event) or 0) == ETERNAL_NIGHTFALL
            and is_cast_complete(event)
            and timestamp <= int(event["timestamp"]) <= end
        )
        interrupt_player = None
        interrupt_spell_id = None
        if interrupt:
            interrupt_id = _resolve_player_source(interrupt, players, pet_owners) or interrupt.get("sourceID")
            interrupt_player = player_ref(players, actor_map, interrupt_id)
            interrupt_spell_id = int(interrupt.get("abilityGameID") or 0) or None
        rounds.append({
            "index": index,
            "phase": phase_at(timestamp - fight_start, markers or []),
            "timeMs": timestamp - fight_start,
            "time": fmt_ms(timestamp - fight_start),
            "shieldRemoved": bool(shield_remove),
            "shieldApplyTime": fmt_ms(int(shield_apply["timestamp"]) - fight_start) if shield_apply else None,
            "shieldRemoveTime": fmt_ms(int(shield_remove["timestamp"]) - fight_start) if shield_remove else None,
            "interrupted": bool(interrupt),
            "interruptTime": fmt_ms(int(interrupt["timestamp"]) - fight_start) if interrupt else None,
            "interruptSource": interrupt_player["player"] if interrupt_player else None,
            "interruptPlayer": interrupt_player,
            "interruptSpellID": interrupt_spell_id,
            "interruptSpell": spell_name(interrupt_spell_id, SPELLS) if interrupt_spell_id else None,
            "castCompleted": cast_success,
            "failed": cast_success or not shield_remove,
        })
    return {
        "rounds": rounds,
        "evidenceNote": (
            "护盾以本轮 1286912 的完整 removebuff 为准（不含层数跳动），窗口到下一发永恒夜幕为止。"
            "打断取友方 Interrupts 中 extraAbilityGameID 为 1286918/1310752 的最后一次，并标出打断玩家。"
            "不再统计破盾窗口内各玩家打盾伤害与命中次数。"
        ),
    }


def _cluster_events_by_time(events, merge_ms=250):
    waves = []
    for event in sorted(events or [], key=lambda row: int(row.get("timestamp") or 0)):
        ts = int(event.get("timestamp") or 0)
        if waves and ts - waves[-1]["timestamp"] <= merge_ms:
            waves[-1]["events"].append(event)
        else:
            waves.append({"timestamp": ts, "events": [event]})
    return waves


def _spirit_erasure_stepper_ids(wave, players, debuffs, friendly_damage, friendly_casts):
    """定位触发本次灵魂抹除的友方：伤害来源 / 易伤 debuff / 友方施法，不按承伤目标猜。"""
    wave_ts = int(wave["timestamp"])
    window_start = wave_ts - SPIRIT_ERASURE_STEPPER_WINDOW_MS
    window_end = wave_ts + SPIRIT_ERASURE_STEPPER_WINDOW_MS
    steppers = []
    seen = set()

    def add(player_id, evidence):
        if player_id not in players or player_id in seen:
            return
        seen.add(player_id)
        steppers.append((player_id, evidence))

    for event in wave.get("events") or []:
        add(event.get("sourceID"), "damage-source")
    for event in friendly_damage or []:
        if int(ability_id(event) or 0) != SPIRIT_ERASURE:
            continue
        ts = int(event.get("timestamp") or 0)
        if window_start <= ts <= window_end:
            add(event.get("sourceID"), "friendly-damage")
    for event in friendly_casts or []:
        if int(ability_id(event) or 0) != SPIRIT_ERASURE:
            continue
        if event_type(event) not in {"cast", "begincast"}:
            continue
        ts = int(event.get("timestamp") or 0)
        if window_start <= ts <= window_end:
            add(event.get("sourceID"), "friendly-cast")
    for event in debuffs or []:
        if int(ability_id(event) or 0) not in SPIRIT_ERASURE_DEBUFF_IDS:
            continue
        if not is_apply(event):
            continue
        ts = int(event.get("timestamp") or 0)
        if window_start <= ts <= window_end:
            add(event.get("targetID"), "desecrator-debuff")
    return steppers


def _dedupe_reclaim_events(events, merge_ms=250):
    """同一灵魂到达可能同时留下 cast/heal，按时间+来源去重。"""
    ordered = sorted(events or [], key=lambda row: (int(row.get("timestamp") or 0), int(row.get("sourceID") or 0)))
    kept = []
    for event in ordered:
        ts = int(event.get("timestamp") or 0)
        source_id = event.get("sourceID")
        duplicate = False
        for prev in kept:
            if prev.get("sourceID") != source_id:
                continue
            if abs(int(prev.get("timestamp") or 0) - ts) <= merge_ms:
                duplicate = True
                break
        if not duplicate:
            kept.append(event)
    return kept


def analyze_intermission(
    fight,
    enemy_buffs,
    damage,
    debuffs,
    actor_map,
    players,
    markers,
    heals=None,
    casts=None,
    friendly_damage=None,
    friendly_casts=None,
    deaths=None,
    zuljan_id=None,
    actor_rows=None,
    buffs=None,
):
    """
    转阶段漏片：残片未被踩到、抵达祖尔加时会施放收回精华（1287718）为其回血。
    以该技能的治疗/施法次数统计漏掉的灵魂数。
    踩片：1287722 是全团 AOE，按脉冲合并后找触发的友方，不把每个承伤目标当成一次踩片。
    """
    del markers  # 接口保留，当前转阶段窗口不依赖阶段标记
    start_event = next(
        (
            event for event in sorted(enemy_buffs, key=lambda row: int(row.get("timestamp") or 0))
            if int(ability_id(event) or 0) in INTERMISSION_BUFFS and is_apply(event)
        ),
        None,
    )
    if not start_event:
        return {"enabled": False, "reason": "本场未进入被夺取的容器转阶段。"}
    start = int(start_event["timestamp"])
    # 略加缓冲，避免窗口末尾到达的残片漏记
    end = start + INTERMISSION_MS + 2_000

    heal_hits = list(_events_between(heals or [], start, end, {RECLAIM_ESSENCE}))
    cast_hits = [
        event for event in _events_between(casts or [], start, end, {RECLAIM_ESSENCE})
        if is_cast_complete(event)
    ]
    damage_hits = list(_events_between(damage or [], start, end, {RECLAIM_ESSENCE}))

    # 优先治疗（漏片回血），再补施法；都没有时回退旧的 damage 桶
    if heal_hits or cast_hits:
        reclaim_events = _dedupe_reclaim_events(heal_hits + cast_hits)
        evidence_source = "heal+cast" if heal_hits and cast_hits else ("heal" if heal_hits else "cast")
    else:
        reclaim_events = _dedupe_reclaim_events(damage_hits)
        evidence_source = "damage-fallback"

    leaks = []
    total_heal = 0
    for event in reclaim_events:
        amount = event_amount(event)
        if amount:
            total_heal += int(amount)
        leaks.append({
            "timeMs": int(event["timestamp"]) - int(fight["startTime"]),
            "time": fmt_ms(int(event["timestamp"]) - int(fight["startTime"])),
            "sourceID": event.get("sourceID"),
            "source": actor_name(actor_map, event.get("sourceID")),
            "targetID": event.get("targetID"),
            "target": actor_name(actor_map, event.get("targetID")),
            "amount": amount or None,
            "eventType": event_type(event) or None,
        })

    erasure_hits = [
        event for event in _events_between(damage, start, end, {SPIRIT_ERASURE})
        if event.get("targetID") in players and event_type(event) in {"", "damage"}
    ]
    steps = []
    for index, wave in enumerate(_cluster_events_by_time(erasure_hits, SPIRIT_ERASURE_WAVE_MS), start=1):
        steppers = _spirit_erasure_stepper_ids(
            wave, players, debuffs, friendly_damage or [], friendly_casts or [],
        )
        hit_ids = []
        seen_hits = set()
        for event in wave["events"]:
            target_id = event.get("targetID")
            if target_id in seen_hits:
                continue
            seen_hits.add(target_id)
            hit_ids.append(target_id)
        primary = steppers[0][0] if steppers else None
        row = {
            "index": index,
            "timeMs": wave["timestamp"] - int(fight["startTime"]),
            "time": fmt_ms(wave["timestamp"] - int(fight["startTime"])),
            "hitCount": len(hit_ids),
            "evidence": steppers[0][1] if steppers else "unknown",
            "steppers": [
                {**player_ref(players, actor_map, player_id), "evidence": evidence}
                for player_id, evidence in steppers
            ],
        }
        if primary is not None:
            row.update(player_ref(players, actor_map, primary))
        else:
            row["player"] = None
            row["playerID"] = None
        steps.append(row)

    potion_start = start - INTERMISSION_POTION_LOOKBACK_MS
    potion_uses = {}
    for event in list(friendly_casts or []) + list(buffs or []):
        spell_id = int(ability_id(event) or 0)
        if spell_id not in INTERMISSION_POTIONS:
            continue
        kind = event_type(event)
        if kind == "cast":
            player_id = event.get("sourceID")
        elif kind in {"applybuff", "refreshbuff"}:
            player_id = event.get("targetID") or event.get("sourceID")
        else:
            continue
        ts = int(event.get("timestamp") or 0)
        if player_id not in players or not (potion_start <= ts < end):
            continue
        prev = potion_uses.get(player_id)
        if prev is not None and ts >= prev["timestamp"]:
            continue
        potion_uses[player_id] = {
            "timestamp": ts,
            "spellID": spell_id,
            "spellName": INTERMISSION_POTIONS[spell_id],
            "evidence": "cast" if kind == "cast" else "buff",
        }

    pet_owners = _pet_owner_map(actor_rows)
    damage_by = defaultdict(lambda: {"damage": 0})
    if zuljan_id is not None:
        for event in friendly_damage or []:
            if event_type(event) != "damage" or event.get("targetID") != zuljan_id:
                continue
            ts = int(event.get("timestamp") or 0)
            if not (start <= ts <= end):
                continue
            source_id = _resolve_player_source(event, players, pet_owners)
            if source_id is None or _player_is_healer(players, source_id):
                continue
            amount = int(event.get("amount") or 0) + int(event.get("absorbed") or 0)
            if amount <= 0:
                continue
            damage_by[source_id]["damage"] += amount

    alive = _alive_player_ids(players, deaths, friendly_casts, start)
    for event in friendly_casts or []:
        if event.get("targetID") not in players:
            continue
        if int(ability_id(event) or 0) not in COMBAT_RES_SPELLS:
            continue
        if event_type(event) not in {"cast", "applybuff"}:
            continue
        ts = int(event.get("timestamp") or 0)
        if start <= ts <= end:
            alive.add(event.get("targetID"))

    total_boss_damage = sum(row["damage"] for row in damage_by.values())
    survivors = []
    for player_id in alive:
        if _player_is_healer(players, player_id):
            continue
        potion = potion_uses.get(player_id)
        stats = damage_by.get(player_id) or {"damage": 0}
        damage_total = stats["damage"]
        pct = round(100.0 * damage_total / total_boss_damage, 1) if total_boss_damage else 0.0
        survivors.append({
            **player_ref(players, actor_map, player_id),
            "potionUsed": bool(potion),
            "potionSpellID": potion["spellID"] if potion else None,
            "potionName": potion["spellName"] if potion else None,
            "potionTimeMs": (potion["timestamp"] - int(fight["startTime"])) if potion else None,
            "potionTime": fmt_ms(potion["timestamp"] - int(fight["startTime"])) if potion else None,
            "potionEvidence": potion["evidence"] if potion else None,
            "zuljanDamage": damage_total,
            "zuljanPercent": pct,
        })
    survivors.sort(key=lambda row: (-row["zuljanDamage"], row["player"] or ""))
    potion_used_count = sum(1 for row in survivors if row["potionUsed"])
    return {
        "enabled": True,
        "startTimeMs": start - int(fight["startTime"]),
        "startTime": fmt_ms(start - int(fight["startTime"])),
        "durationMs": INTERMISSION_MS,
        "duration": fmt_ms(INTERMISSION_MS),
        "leakedFragments": leaks,
        "leakCount": len(leaks),
        "leakedSoulCount": len(leaks),
        "reclaimHealTotal": total_heal or None,
        "reclaimEvidenceSource": evidence_source,
        "spiritErasureSteps": steps,
        "spiritErasureStepCount": len(steps),
        "survivors": survivors,
        "survivorCount": len(survivors),
        "potionUsedCount": potion_used_count,
        "zuljanDamageTotal": total_boss_damage,
        "evidenceNote": (
            "漏掉的灵魂以收回精华（Reclaim Essence，1287718）为准："
            "残片抵达祖尔加回血即记 1 次漏片。"
            "灵魂抹除 1287722 是全团 AOE：同一脉冲合并为 1 次踩片，"
            "踩片者以友方伤害来源、1287722 易伤施加或友方施法为准，不用承伤目标计数。"
            "爆发药水与对祖尔加护盾伤害只统计非治疗玩家（转阶段开始时存活，含战复）："
            "是否使用圣光潜力 1236616、鲁莽药水 1236994 或液态光泽 1295132；"
            "对祖尔加伤害取该窗口对祖尔加的 DamageDone，不计命中次数，不含治疗。"
        ),
    }


def build_field_audit(
    arena, toxic_deluge, sever, soul_sever, gloombomb, blighted_sever,
    manifestations=None, guillotine=None, grim_guillotine=None,
):
    """场地示意图：撕裂锥形清场 + 处斩跑离 + 幽暗炸弹分散。"""
    del toxic_deluge, manifestations
    diagrams = []

    def append_cone_diagram(row, mechanic, primary_key):
        targets = []
        links = []
        source_points = row.get("nearbyPoints") or row.get(primary_key) or []
        for point in source_points:
            if (point.get("kind") == "manifestation") or point.get("manifestPosition") or (
                mechanic in {"灵魂撕裂", "凋零撕裂"} and point.get("manifest")
            ):
                manifest_pos = point.get("manifestPosition") or point.get("position")
                player_pos = point.get("playerPosition")
                uncleared = bool(point.get("uncleared")) if "uncleared" in point else True
                # 灵魂撕裂 / 凋零撕裂：红线只连本轮未消掉凝视的玩家
                draw_link = uncleared if mechanic in {"灵魂撕裂", "凋零撕裂"} else True
                if manifest_pos:
                    targets.append({
                        **{k: point.get(k) for k in ("player", "classColor", "manifest", "playerID", "clearOutcome", "icon", "role", "specID", "specName", "className") if point.get(k) is not None},
                        "kind": "manifestation",
                        "position": manifest_pos,
                        "manifestPosition": manifest_pos,
                        "playerPosition": player_pos,
                        "inCone": bool(point.get("inCone")),
                        "debuffCleared": bool(point.get("debuffCleared")),
                        "uncleared": uncleared,
                    })
                if player_pos and (mechanic not in {"灵魂撕裂", "凋零撕裂"} or draw_link):
                    targets.append({
                        **{k: point.get(k) for k in ("player", "classColor", "playerID", "icon", "role", "specID", "specName", "className") if point.get(k) is not None},
                        "kind": "manifest-target",
                        "position": player_pos,
                        "uncleared": uncleared,
                        "clearOutcome": point.get("clearOutcome"),
                    })
                if draw_link and manifest_pos and player_pos:
                    links.append({
                        "from": player_pos,
                        "to": manifest_pos,
                        "player": point.get("player"),
                        "clearOutcome": point.get("clearOutcome"),
                    })
            else:
                targets.append(point)
        if row.get("tankPosition"):
            targets = [{
                "kind": "tank",
                "player": "当前坦克",
                "position": row["tankPosition"],
            }] + targets
        annotation = row.get("evidenceNote") or ""
        if row.get("facingInferred"):
            annotation = (annotation + "；锥形朝向为根据附近标记点估算，仅供示意。").strip("；")
        if mechanic in {"灵魂撕裂", "凋零撕裂"} and row.get("clearedByDebuff") is not None:
            annotation = annotation or (
                f"释放前具象 {len([p for p in source_points if p.get('kind') == 'manifestation' or p.get('manifestPosition')])}；"
                f"锥内 {row.get('clearedByGeometry')}；"
                f"debuff 清掉 {row.get('clearedByDebuff')}；未消掉 {row.get('unclearedCount')}（红线）"
            )
        elif mechanic == "凋零撕裂":
            annotation = annotation or f"P3 组合清场推断 {row.get('inferredClearedCount')}"
        else:
            annotation = annotation or (
                f"推断清理 {row.get('inferredClearedCount')} 团，几何命中 {row.get('clearedByGeometry')}"
            )
        diagrams.append({
            "kind": "cone-clear",
            "mechanic": mechanic,
            "roundIndex": row["index"],
            "phase": row["phase"],
            "time": row["time"],
            "origin": row.get("origin"),
            "originRule": row.get("originRule"),
            "tankPosition": row.get("tankPosition"),
            "conePolygon": row.get("conePolygon") or [],
            "coneRadiusYards": row.get("coneRadiusYards", CONE_RADIUS_YARDS),
            "coneHalfAngleDeg": row.get("coneHalfAngleDeg", CONE_HALF_ANGLE_DEG),
            "facingRadians": row.get("facingRadians"),
            "facingRule": row.get("facingRule"),
            "facingLockMs": row.get("facingLockMs"),
            "facingInferred": bool(row.get("facingInferred")),
            "targets": targets,
            "links": links,
            "clearedCount": row.get("inferredClearedCount", row.get("clearedByGeometry")),
            "unclearedCount": row.get("unclearedCount"),
            "annotation": annotation,
        })

    def append_runout_diagram(row, mechanic, annotation):
        targets = []
        for participant in row.get("participants") or []:
            if not participant.get("position"):
                continue
            targets.append({
                **{k: participant.get(k) for k in ("player", "classColor", "playerID", "role", "icon") if participant.get(k) is not None},
                "kind": "guillotine-share",
                "position": participant["position"],
            })
        for inside in row.get("stillInsideRange") or []:
            if not inside.get("position"):
                continue
            targets.append({
                **{k: inside.get(k) for k in ("player", "classColor", "playerID", "role", "icon") if inside.get(k) is not None},
                "kind": "guillotine-inside",
                "position": inside["position"],
                "distanceFromShareYards": inside.get("distanceFromShareYards"),
            })
        if row.get("shareCentroid") or targets:
            diagrams.append({
                "kind": "runout",
                "mechanic": mechanic,
                "roundIndex": row["index"],
                "phase": row["phase"],
                "time": row["time"],
                "origin": row.get("shareCentroid"),
                "bossPosition": row.get("bossPosition"),
                "dangerRadiusYards": row.get("dangerRadiusYards", GUILLOTINE_RANGE_YARDS),
                "targets": targets,
                "annotation": annotation,
            })

    for row in (sever.get("rounds") or []):
        append_cone_diagram(row, row.get("label") or "撕裂", "targetsInCone")
    for row in ((guillotine or {}).get("rounds") or []):
        append_runout_diagram(
            row,
            row.get("label") or "处斩",
            (
                f"分摊 {row.get('participantCount', 0)} 人；"
                f"（{row.get('dangerRadiusYards', GUILLOTINE_RANGE_YARDS)} 码内）"
                f" {len(row.get('stillInsideRange') or [])} 人"
            ),
        )
    for row in (gloombomb.get("rounds") or []):
        targets = [target for target in (row.get("targets") or []) if target.get("position")]
        collateral = [
            player for player in (row.get("collateralHits") or [])
            if player.get("position")
        ]
        if not targets:
            continue
        too_close = row.get("tooClosePairs") or []
        diagrams.append({
            "kind": "spread",
            "mechanic": "幽暗炸弹",
            "roundIndex": row["index"],
            "phase": row["phase"],
            "time": row["time"],
            "bossPosition": row.get("bossPosition"),
            "targets": targets,
            "nearbyPlayers": collateral,
            "spreadRadiusYards": row.get("spreadRadiusYards", GLOOMBOMB_RADIUS_YARDS),
            "tooClosePairs": too_close,
            "annotation": (
                f"点名 {row.get('targetCount', 0)} 人；"
                f"过近组合 {len(too_close)}；"
                f"误伤墓缚 {row.get('collateralCount', len(collateral))}"
                f"（分散半径 {row.get('spreadRadiusYards', GLOOMBOMB_RADIUS_YARDS)} 码）"
            ),
        })
    for row in (soul_sever.get("rounds") or []):
        # 用释放前全部活跃具象；红线仅未消掉 debuff
        append_cone_diagram(row, "灵魂撕裂", "nearbyPoints")
    for row in ((grim_guillotine or {}).get("rounds") or []):
        append_runout_diagram(
            row,
            row.get("label") or "冷酷处斩",
            (
                f"分摊 {row.get('participantCount', 0)} 人；"
                f"死亡低语脉冲后仍吃死亡之拥（{row.get('dangerRadiusYards', GUILLOTINE_RANGE_YARDS)} 码内）"
                f" {len(row.get('stillInsideRange') or [])} 人"
            ),
        )
    for row in (blighted_sever.get("rounds") or []):
        append_cone_diagram(row, row.get("label") or "凋零撕裂", "targetsInCone")

    return {
        "arena": arena,
        "arenaImage": ARENA_IMAGE,
        "icons": dict(FIELD_ICONS),
        "diagrams": diagrams,
        "evidenceNote": (
            f"场地中心固定为坐标 ({ARENA_CENTER_X_UNITS:g}, {ARENA_CENTER_Y_UNITS:g})，"
        ),
    }


def analyze_fight(fight, actor_map, actor_type, actor_rows, raw):
    players = build_player_catalog(actor_map, actor_type, raw["combatants"])
    deaths = [event for event in raw["deaths"] if event.get("targetID") in players]
    enemy_deaths = [event for event in raw["enemyDeaths"] if event.get("targetID") not in players]
    raw["deaths"] = deaths
    actor_catalog = build_actor_catalog(actor_rows)
    manifest_ids = manifest_actor_ids(actor_rows)
    npc_position_events = _npc_position_events(raw, manifest_ids)
    npc_position_index = build_npc_position_index(npc_position_events)
    zuljan_id = resolve_boss_actor_id(actor_rows, None, ("Zul'jan", "祖尔加"))
    malacrass_id = resolve_boss_actor_id(actor_rows, None, ("Hex Lord Malacrass", "玛拉卡斯", "Malacrass"))
    boss_id = zuljan_id or malacrass_id
    boss_ids = {actor_id for actor_id in (zuljan_id, malacrass_id) if actor_id is not None}
    markers = build_phase_markers(
        fight, raw["casts"], raw["enemyBuffs"],
        enemy_deaths=enemy_deaths, zuljan_id=zuljan_id, malacrass_id=malacrass_id,
    )
    boss_position_events = _npc_position_events(raw, boss_ids)
    caster_index = build_caster_self_position_index(
        list(raw.get("casts") or [])
        + list(raw.get("damage") or [])
        + list(raw.get("resources") or [])
        + list(raw.get("npcPositionEvents") or []),
        boss_ids or None,
    )
    position_events = (
        list(raw.get("damage") or [])
        + list(raw.get("debuffs") or [])
        + list(raw.get("resources") or [])
        + list(raw.get("npcPositionEvents") or [])
        + boss_position_events
    )
    position_index = build_position_index(position_events)
    arena = coiledaltar_arena(position_index, list(players), boss_id=boss_id)

    toxic_deluge = analyze_toxic_deluge(
        fight, raw["casts"], raw["debuffs"], position_index, actor_map, players, markers,
        damage_events=list(raw.get("damage") or []),
    )
    venom_points = build_active_venom_points(toxic_deluge)
    manifestations = analyze_manifestations(
        fight, raw["debuffs"], npc_position_index, actor_map, players, actor_catalog, markers,
        enemy_deaths=enemy_deaths, position_index=position_index,
    )
    active_points = venom_points + (manifestations.get("activePoints") or [])

    sever = analyze_cone_sever(
        "撕裂", SEVER_IDS, fight, raw["casts"], raw["debuffs"], position_index, actor_map, players, markers,
        venom_points, actor_catalog, boss_actor_id=zuljan_id, origin_index=caster_index,
    )
    blighted_sever = analyze_cone_sever(
        "凋零撕裂", BLIGHTED_SEVER_IDS, fight, raw["casts"], raw["debuffs"], position_index, actor_map, players, markers,
        active_points, actor_catalog, boss_actor_id=zuljan_id, origin_index=caster_index,
        npc_position_index=npc_position_index,
    )
    guillotine = analyze_guillotine(
        fight, raw["casts"], raw["damage"], raw["debuffs"], position_index, actor_map, players, markers,
        GUILLOTINE_CAST_IDS, "处斩",
        pulse_damage_id=WIDOW_TOUCH_DAMAGE_ID,
        in_range_damage_id=WIDOW_KISS_DAMAGE_ID,
        origin_index=caster_index,
        boss_actor_id=zuljan_id,
    )
    grim_guillotine = analyze_guillotine(
        fight, raw["casts"], raw["damage"], raw["debuffs"], position_index, actor_map, players, markers,
        GRIM_GUILLOTINE_CAST_IDS, "冷酷处斩",
        damage_ids=GRIM_GUILLOTINE_DAMAGE_IDS,
        mark_ids=GRIM_GUILLOTINE_MARK_IDS,
        pulse_damage_id=DEATH_WHISPER_DAMAGE_ID,
        in_range_damage_id=DEATH_EMBRACE_DAMAGE_ID,
        origin_index=caster_index,
        boss_actor_id=zuljan_id,
    )
    dreadmarch = analyze_dreadmarch(
        fight, raw["casts"], raw["debuffs"], raw["damage"], [],
        deaths, actor_map, players, markers,
    )
    soul_sever = analyze_soul_sever(
        fight, raw["casts"], enemy_deaths, position_index, actor_map, markers, manifestations.get("activePoints") or [],
        boss_actor_id=malacrass_id, origin_index=caster_index, debuffs=raw["debuffs"],
        npc_position_index=npc_position_index,
    )
    gloombomb = analyze_gloombomb(
        fight, raw["casts"], raw["debuffs"], position_index, actor_map, players, markers,
        origin_index=caster_index, boss_actor_id=malacrass_id,
    )
    gravebound = analyze_gravebound_failures(
        fight, raw["debuffs"], deaths, actor_map, players,
        damage_events=list(raw.get("damage") or []),
    )
    eternal = analyze_eternal_nightfall(
        fight, raw["casts"], raw["enemyBuffs"], raw.get("interrupts") or [], actor_map,
        players=players,
        actor_rows=actor_rows,
        markers=markers,
        friendly_casts=raw.get("friendlyCasts") or [],
    )
    intermission = analyze_intermission(
        fight, raw["enemyBuffs"], raw["damage"], raw["debuffs"], actor_map, players, markers,
        heals=list(raw.get("heals") or []),
        casts=raw.get("casts") or [],
        friendly_damage=raw.get("bossDamage") or [],
        friendly_casts=raw.get("friendlyCasts") or [],
        deaths=deaths,
        zuljan_id=zuljan_id,
        actor_rows=actor_rows,
        buffs=raw.get("buffs") or [],
    )
    field_audit = build_field_audit(
        arena, toxic_deluge, sever, soul_sever, gloombomb, blighted_sever, manifestations,
        guillotine=guillotine, grim_guillotine=grim_guillotine,
    )

    return {
        "phaseTimeline": markers,
        "toxicDeluge": toxic_deluge,
        "sever": sever,
        "guillotine": guillotine,
        "dreadmarch": dreadmarch,
        "manifestations": manifestations,
        "soulSever": soul_sever,
        "gloombomb": gloombomb,
        "graveboundFailures": gravebound,
        "eternalNightfall": eternal,
        "intermission": intermission,
        "blightedSever": blighted_sever,
        "grimGuillotine": grim_guillotine,
        "fieldAudit": field_audit,
        "npcCatalog": {
            "manifestNpcGameID": MANIFEST_NPC_GAME_ID,
            "manifestActors": actor_catalog["byGameID"].get(MANIFEST_NPC_GAME_ID, []),
            "positionEventCount": len(npc_position_events),
            "positionSampleKeys": sorted(
                {f"{actor_id}:{instance}" for actor_id, instance in npc_position_index}
            ),
        },
    }


def fetch_payload(client, report_id, fight, actor_rows=None):
    actor_rows = actor_rows or []
    zuljan_id = resolve_boss_actor_id(actor_rows, None, ("Zul'jan", "祖尔加"))
    malacrass_id = resolve_boss_actor_id(actor_rows, None, ("Hex Lord Malacrass", "玛拉卡斯", "Malacrass"))
    manifest_ids = set(manifest_actor_ids(actor_rows))
    boss_ids = {actor_id for actor_id in (zuljan_id, malacrass_id) if actor_id is not None}
    npc_filter = _npc_position_filter_expression(manifest_ids | boss_ids)
    npc_position_events = []
    if npc_filter:
        npc_position_events.extend(client.events(
            report_id,
            "All",
            fight,
            filter_expression=npc_filter,
            include_resources=True,
        ))
    npc_position_events.extend(_fetch_manifest_position_events(client, report_id, fight, manifest_ids))
    boss_damage = []
    if zuljan_id is not None:
        boss_damage = client.events(report_id, "DamageDone", fight, target_id=zuljan_id)
    return {
        "casts": _fetch_by_abilities(
            client, report_id, "Casts", fight, MECHANIC_CAST_IDS,
            hostility_type="Enemies", include_resources=True,
        ),
        "friendlyCasts": _fetch_by_abilities(
            client, report_id, "Casts", fight, FRIENDLY_CAST_IDS, hostility_type="Friendlies",
        ),
        "damage": _fetch_by_abilities(
            client, report_id, "DamageTaken", fight, MECHANIC_DAMAGE_IDS, include_resources=True,
        ),
        "heals": _fetch_by_abilities(client, report_id, "Healing", fight, {RECLAIM_ESSENCE}),
        "debuffs": _fetch_by_abilities(
            client, report_id, "Debuffs", fight, MECHANIC_DEBUFF_IDS, include_resources=True,
        ),
        "buffs": _fetch_by_abilities(
            client, report_id, "Buffs", fight, set(INTERMISSION_POTIONS), hostility_type="Friendlies",
        ),
        "enemyBuffs": _fetch_by_abilities(
            client, report_id, "Buffs", fight, MECHANIC_ENEMY_BUFF_IDS, hostility_type="Enemies",
        ),
        "deaths": client.events(report_id, "Deaths", fight),
        "enemyDeaths": client.events(report_id, "Deaths", fight, hostility_type="Enemies"),
        "combatants": client.events(report_id, "CombatantInfo", fight),
        "resources": client.events(report_id, "Resources", fight, include_resources=True),
        "interrupts": client.events(report_id, "Interrupts", fight, hostility_type="Friendlies"),
        "npcPositionEvents": npc_position_events,
        "bossDamage": boss_damage,
    }


def render_fight(report_id, report_start, actor_map, actor_type, actor_rows, fight, raw):
    players = build_player_catalog(actor_map, actor_type, raw["combatants"])
    mechanics = analyze_fight(fight, actor_map, actor_type, actor_rows, raw)
    duration_ms = int(fight["endTime"] - fight["startTime"])
    started = datetime.fromtimestamp((report_start + fight["startTime"]) / 1000, tz=CN_TZ)
    survival = build_survival_timeline(fight, actor_map, players, raw["deaths"], raw["friendlyCasts"], SPELLS)
    end_phase = mechanics["phaseTimeline"][-2]["label"] if len(mechanics["phaseTimeline"]) > 1 else "P1"
    return {
        "reportID": report_id,
        "fightID": int(fight["id"]),
        "fightName": fight.get("name"),
        "date": started.strftime("%Y-%m-%d"),
        "startClock": started.strftime("%H:%M:%S"),
        "startTimeIso": started.isoformat(),
        "isKill": bool(fight.get("kill")),
        "kill": bool(fight.get("kill")),
        "bossPercentage": float(fight.get("bossPercentage") or 0),
        "durationMs": duration_ms,
        "duration": fmt_ms(duration_ms),
        "wipePhase": end_phase,
        "wipeReason": "已击杀" if fight.get("kill") else f"灭团于{end_phase}",
        "investigation": "凝结毒液、恐惧行军、锥形清场、幽暗炸弹分散与转阶段残片均已按阶段对齐。",
        "phaseTimeline": mechanics["phaseTimeline"],
        "wclDeepLink": f"https://www.warcraftlogs.com/reports/{report_id}#fight={fight['id']}&type=summary",
        "players": list(players.values()),
        "survival": survival,
        "deathTimeline": survival["timeline"],
        **difficulty_fields(fight),
        "coiledaltar": mechanics,
    }


REGULAR_PHASE_KEYS = {"p1", "p2", "p3"}


def _regular_phase(row):
    phase = str(row.get("phase") or "").lower()
    if not phase:
        return True
    if phase in REGULAR_PHASE_KEYS:
        return True
    return phase != "intermission" and "转" not in phase


def _mechanic_overview(rendered):
    """整夜机制统计：幽暗炸弹误伤、灵魂未劈中、常规阶段撞具象恐惧行军、墓缚致死。"""
    gloombomb_hits = []
    uncleared_souls = []
    dreadmarch_collisions = []
    gravebound_deaths = []
    for pull in rendered:
        mechanics = pull.get("coiledaltar") or {}
        for round_row in (mechanics.get("gloombomb") or {}).get("rounds") or []:
            named_targets = round_row.get("targets") or []
            has_named_breakdown = any("collateralGravebound" in (target or {}) for target in named_targets)
            if has_named_breakdown:
                for target in named_targets:
                    for hit in target.get("collateralGravebound") or []:
                        if hit.get("receivedGravebound") is False:
                            continue
                        gloombomb_hits.append(nightly_detail(
                            pull,
                            round_row.get("time") or hit.get("graveboundApplyTime"),
                            f"{target.get('player') or '未知玩家'} 的幽暗炸弹误伤 {hit.get('player') or '未知队友'}",
                            player=target.get("player"),
                            classColor=target.get("classColor"),
                            victim=hit.get("player"),
                        ))
            else:
                for hit in round_row.get("collateralHits") or []:
                    gloombomb_hits.append(nightly_detail(
                        pull,
                        round_row.get("time") or hit.get("graveboundApplyTime"),
                        f"{hit.get('fromPlayer') or '点名者'} 的幽暗炸弹误伤 {hit.get('player') or '未知队友'}",
                        player=hit.get("fromPlayer"),
                        classColor=hit.get("fromClassColor"),
                        victim=hit.get("player"),
                    ))
        for key, mechanic_name in (("soulSever", "灵魂撕裂"), ("blightedSever", "凋零撕裂")):
            for round_row in (mechanics.get(key) or {}).get("rounds") or []:
                for point in round_row.get("unclearedManifestations") or []:
                    if point.get("inCone") is True:
                        continue
                    uncleared_souls.append(nightly_detail(
                        pull,
                        round_row.get("time"),
                        f"{point.get('player') or '未知玩家'} 携带灵魂，未被{mechanic_name}劈中",
                        player=point.get("player"),
                        classColor=point.get("classColor"),
                        mechanic=mechanic_name,
                    ))
        dreadmarch = mechanics.get("dreadmarch") or {}
        applications = list(dreadmarch.get("applications") or [])
        if not applications:
            for round_row in dreadmarch.get("rounds") or []:
                applications.extend(round_row.get("targets") or [])
        for row in applications:
            if not _regular_phase(row):
                continue
            if not (row.get("hitManifestation") or row.get("triggerKind") == "manifest-collision"):
                continue
            dreadmarch_collisions.append(nightly_detail(
                pull,
                row.get("appliedTime") or row.get("time"),
                f"{row.get('player') or '未知玩家'} 常规阶段撞具象触发恐惧行军",
                player=row.get("player"),
                classColor=row.get("classColor"),
            ))
        for row in (mechanics.get("graveboundFailures") or {}).get("failures") or []:
            if not _is_gravebound_damage_death(row):
                continue
            ability = row.get("deathAbility") or row.get("deathAbilityID") or "墓缚"
            gravebound_deaths.append(nightly_detail(
                pull,
                row.get("time"),
                f"{row.get('player') or '未知玩家'} 死于墓缚（{ability}）",
                player=row.get("player"),
                classColor=row.get("classColor"),
                spellID=row.get("deathAbilityID"),
            ))
    return {
        "title": "整夜机制统计",
        "subtitle": "按所有 Pull 汇总可验证事件；单场阶段页明细保持原样。",
        "metrics": [
            {
                "key": "gloombombCollateralHits",
                "label": "幽暗炸弹误伤队友",
                "value": len(gloombomb_hits),
                "unit": "人次",
                "tone": "danger",
                "description": "按被点名炸弹的玩家计：爆炸 15 码内且 2 秒内给队友上墓缚 1286837 一次计一次。同一队友被两枚炸弹溅到会分别记到两名点名者。",
                "players": nightly_player_totals(gloombomb_hits),
                "events": gloombomb_hits,
            },
            {
                "key": "unclearedSouls",
                "label": "携带灵魂未被劈中",
                "value": len(uncleared_souls),
                "unit": "次",
                "tone": "danger",
                "description": "灵魂撕裂 / 凋零撕裂释放时场上仍有凝视，且该具象不在锥形内；锥内但没消掉的不算「未被劈中」。",
                "players": nightly_player_totals(uncleared_souls),
                "events": uncleared_souls,
            },
            {
                "key": "regularDreadmarch",
                "label": "常规阶段恐惧行军",
                "value": len(dreadmarch_collisions),
                "unit": "次",
                "tone": "warning",
                "description": "与单场撞具象同一套判定：常规阶段里首次救人后、下一轮 Boss 释放前再次获得 1297445 的玩家。Boss 正常点名不计入。",
                "players": nightly_player_totals(dreadmarch_collisions),
                "events": dreadmarch_collisions,
            },
            {
                "key": "graveboundDeaths",
                "label": "死于墓缚",
                "value": len(gravebound_deaths),
                "unit": "次",
                "tone": "danger",
                "description": "只统计被墓缚伤害（1308330 / 1297906 / 1286837）打死的玩家。带墓缚但死于其他技能不计入。",
                "players": nightly_player_totals(gravebound_deaths),
                "events": gravebound_deaths,
            },
        ],
    }


def build_aggregated_json(report_ids, options=None):
    report_id_list = [value for value in (item.strip() for item in report_ids.replace(" ", "").split(",")) if value]
    if not report_id_list:
        raise RuntimeError("请传入至少一个 WCL report ID。")
    client = WclClient()
    rendered = []
    progress("读取盘卷祭坛 Pull 列表", 8)
    for report_id in report_id_list:
        report = client.report_fights(report_id)
        fights = filter_fights(
            report_id,
            [
                fight for fight in report["fights"]
                if int(fight.get("encounterID") or 0) in ENCOUNTER_IDS
                and fight["endTime"] - fight["startTime"] >= 20_000
            ],
        )
        actor_rows = client.actors(report_id)
        actor_map = {row["id"]: row["name"] for row in actor_rows}
        actor_type = {row["id"]: row.get("type") for row in actor_rows}
        progress(f"{report_id}：匹配 {len(fights)} 场", 12)

        def fetch_one(item):
            index, fight = item
            progress(f"读取 Fight {fight['id']}（{index}/{len(fights)}）")
            raw = fetch_payload(client, report_id, fight, actor_rows)
            return index, render_fight(report_id, report["startTime"], actor_map, actor_type, actor_rows, fight, raw)

        for _, row in run_parallel_indexed(list(enumerate(fights, start=1)), fetch_one):
            rendered.append(row)
    rendered.sort(key=lambda row: (row["startTimeIso"], row["reportID"], row["fightID"]))
    progress("生成盘卷祭坛阶段复盘与场地示意图", 96)
    return {
        "code": 200,
        "meta": {
            "version": "12.1",
            "raidKey": "venomous_abyss",
            "raidName": "烈毒之渊",
            "bossKey": "coiledaltar",
            "bossName": "盘卷祭坛",
            "analyzedReports": report_id_list,
            "mechanicVersion": "coiledaltar-heroic-2026-08-29",
            "tabDefinitions": [{"key": key, "label": label} for key, label in TABS],
            "arenaImage": ARENA_IMAGE,
            "fieldIcons": dict(FIELD_ICONS),
            "features": {"survival": True, "fieldReplay": True},
            "evidenceLimits": {
                "positions": (
                    f"示意图把坐标 ({ARENA_CENTER_X_UNITS:g}, {ARENA_CENTER_Y_UNITS:g}) 映射为 "
                    f"边长约 {int(ARENA_SIDE_UNITS)} 单位（≈{int(ARENA_SIDE_YARDS)} 码）正方形场地中心；"
                    "示意图含撕裂锥形、处斩/冷酷处斩跑离、幽暗炸弹分散；"
                    "撕裂圆心优先取施法 sourceResources，朝向按坦克易伤 debuff / 读条末秒位置锁定；"
                    "剧毒洪流落点按落地/拾取状态机追踪（支持多次接力），场上毒液优先 1282408 源坐标；"
                    "P2 以祖尔加死亡或玛拉卡斯出现为准。"
                ),
                "manifestNpc": (
                    f"恐惧具象实例通过 debuff {FIXATION} 的 sourceID/sourceInstance 与 NPC gameID {MANIFEST_NPC_GAME_ID} 对齐；"
                    "坐标优先取 sourceResources / 受击 targetResources，不用被点名玩家的顶层 x/y；"
                    "示意图用红线连接被点名玩家与具象。"
                ),
            },
        },
        "data": {
            "page1_wipeAnalysis": rendered,
            "mechanicOverview": _mechanic_overview(rendered),
        },
    }


def analyze(report_ids, output_path=None, catalog_entry=None, options=None, progress_callback=None):
    del progress_callback  # reserved for runner compatibility
    payload = build_aggregated_json(report_ids, options)
    if output_path:
        write_json_result(payload, output_path)
    return payload
