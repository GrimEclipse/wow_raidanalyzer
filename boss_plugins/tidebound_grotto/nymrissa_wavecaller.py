"""Evidence-first analyzer for Nymrissa Wavecaller.

The encounter is intentionally kept compact: the module records the few
repeatable mechanics that are useful after a pull without inventing blame when
WCL does not expose enough position or orb-lifecycle evidence.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from analyzer_core.analysis_scope import filter_fights
from analyzer_core.config import resolve_analysis_options
from analyzer_core.progress import emit_progress
from analyzer_core.wcl_api import WclClient
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


ENCOUNTER_IDS = {3379}
CN_TZ = timezone(timedelta(hours=8))
FROST_POLICY = {
    "handlerRule": "通常由坦克踩球；无需配置玩家分工。",
    "positionRule": "集中放冰球与部分远程留中场输出鱼人均为有效打法；不按站位分散程度自动归责。",
    "evidenceRule": "以 Frost Orb 光环首次应用为踩球接触；以 Frost Burst 全团伤害簇为球结算。持续伤害次数不等于踩球次数。",
    "rainTouchRule": "深渊之雨正读条结束后引导约 4 秒；仅在这 4 秒引导窗内踩球单独标出（高概率减员）。",
}
BURST_CLUSTER_MS = 250
TOUCH_BEFORE_BURST_MS = 2_500
ORB_AURA_ID = 1313448
ORB_BURST_ID = 1313450
RAIN_AURA_ID = 1260843
RAIN_CAST_ID = 1260837
RAIN_CHANNEL_MS = 4_000
BUBBLE_CAST_ID = 1284015
POP_CAST_ID = 1258150
SURGE_CAST_ID = 1258673
SURGE_DAMAGE_IDS = {1258668, 1258677}
SURGE_FORESHADOW_MS = 5_000  # after cast complete, warning sits on the rim
SURGE_TRAVEL_MS = 3_500  # then slowly rushes to mid
ALLURING_BUBBLE_RADIUS_YARDS = 10
ORB_PUDDLE_RADIUS_YARDS = 5
ORB_PUDDLE_DURATION_MS = 30_000
FROST_DROP_SPELL_ID = 1313393  # each tick drops one ground orb; 3 per mark
WATER_JET_CAST_ID = 1281951
WATER_JET_DAMAGE_ID = 1271458
LINGERING_FROST_ID = 1257654
UNITS_PER_YARD = 100
BOSS_GAME_ID = 252959
BIG_MURLOC_GAME_ID = 257892  # Bubblefin Frostscale — Waterfog Shield / 附近减伤
SMALL_MURLOC_GAME_ID = 253032  # Bubblefin Shorerunner — 无特殊技能
MURLOC_GAME_IDS = {BIG_MURLOC_GAME_ID, SMALL_MURLOC_GAME_ID}
BOSS_PORTRAIT = "/assets/raids/tidebound_grotto/icons/nymrissa.png"
BIG_MURLOC_PORTRAIT = "/assets/raids/tidebound_grotto/icons/frostscale.png"
# Eight wedges from north, clockwise. atan2(dx, dy) with +y north / +x east.
SURGE_DIRECTIONS = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]
from analyzer_core.combat_replay import fetch_replay_events, build_replay_tracks

CONFIG_SCHEMA = [
    {"key":"fullReplayEnabled", "type":"boolean", "default":True, "label":"完整场地回放", "description":"读取整场所有玩家的位置记录。"},
    {"key": "rainReviewEnabled", "type": "boolean", "label": "深渊之雨与浸湿", "default": True},
    {"key": "frostReviewEnabled", "type": "boolean", "label": "冰霜点名与冰球", "default": True},
    {"key": "transitionReviewEnabled", "type": "boolean", "label": "水泡与鱼人压力", "default": True},
    {"key": "pressureReviewEnabled", "type": "boolean", "label": "场地伤害与对坦压力", "default": True},
    {"key": "rainWindowSeconds", "type": "number", "label": "深渊之雨统计窗口", "unit": "秒", "min": 1, "max": 30, "default": 12},
    {"key": "frostWindowSeconds", "type": "number", "label": "冰球轮次最大窗口", "unit": "秒", "min": 5, "max": 90, "default": 45},
    {"key": "transitionWindowSeconds", "type": "number", "label": "转场最大统计窗口", "unit": "秒", "min": 5, "max": 120, "default": 75},
]

SPELL_NAMES = {
    1: "近战攻击",
    3: "跌落",
    1257614: "冰霜弹幕",
    1257608: "冰霜弹幕点名",
    1257644: "冰霜弹幕",
    1257651: "漂流冰球",
    1281393: "漂流冰球",
    1282537: "漂流冰球寒意",
    # Verified in Avalon ZFDWvrfqd6ygMKY2 / Fight 57 masterData and events.
    1313393: "Chilling Frost",
    1313448: "Frost Orb",
    1313450: "Frost Burst",
    1257654: "残留冰霜",
    1260837: "深渊之雨",
    1260843: "深渊之雨",
    1277386: "浸湿",
    1307352: "浸湿",
    1282937: "冰刃乱舞",
    1282945: "冰刃乱舞",
    1281951: "水流喷射",
    1271458: "水流喷射",
    1284015: "诱人水泡",
    1263301: "鱼人波次",
    1258673: "激荡漩涡",
    1258668: "激荡漩涡",
    1258677: "激荡漩涡",
    1258150: "嘭！",
    1258154: "嘭！",
    1273091: "水雾护盾",
    1273150: "水雾护盾",
    1260012: "鱼人攻击",
    1258894: "脉动潮汐",
    1271380: "脉动潮汐",
    1294867: "无尽潮汐",
    1295086: "无尽潮汐",
}

BOSS_CONFIG = {
    "key": "nymrissa_wavecaller",
    "name": "尼姆瑞莎·唤潮者",
    "encounterIDs": ENCOUNTER_IDS,
    "mechanicVersion": "nymrissa-rain4s-murloc-surge8-2026-10-25",
    "tabs": [
        ["survival", "死亡与战复"],
        ["replay", "场地推演"],
        ["rain", "深渊之雨"],
        ["frost", "冰霜与冰球"],
        ["transition", "鱼人转场"],
        ["pressure", "承伤复盘"],
    ],
}


def ability_id(event):
    return int(
        event.get("abilityGameID")
        or event.get("killingAbilityGameID")
        or (event.get("ability") or {}).get("gameID")
        or 0
    )


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


def player_ref(players, actor_map, actor_id):
    player = players.get(actor_id) or {}
    return {
        "playerID": actor_id,
        "player": player.get("name") or actor_name(actor_map, actor_id),
        "classColor": player.get("classColor") or "#e5e7eb",
        "icon": player.get("icon"),
        "role": player.get("role") or "unknown",
    }


def build_players(actors, combatants):
    actor_map = {int(actor["id"]): actor.get("name") or f"Actor {actor['id']}" for actor in actors}
    actor_type = {int(actor["id"]): actor.get("type") for actor in actors}
    info = {event.get("sourceID") or event.get("targetID"): event for event in combatants}
    roles = build_player_mechanic_roles(combatants)
    players = {}
    for actor_id, actor_kind in actor_type.items():
        # masterData includes the whole report, potentially several raid rosters.
        # CombatantInfo identifies the participants in this particular Fight.
        if actor_kind != "Player" or actor_id not in info:
            continue
        event = info.get(actor_id) or {}
        spec_id = combatant_spec_id(event)
        localization = spec_localization(spec_id)
        players[actor_id] = {
            "id": actor_id,
            "name": actor_name(actor_map, actor_id),
            "specID": spec_id,
            "role": roles.get(actor_id, "unknown"),
            "icon": spec_icon_slug(spec_id),
            "classColor": spec_class_color(spec_id) or CLASS_COLORS.get(str(actor_kind).lower()) or "#e5e7eb",
            "localization": localization,
        }
    return actor_map, players


def completed_casts(events, spell_ids):
    spell_ids = set(spell_ids)
    return sorted(
        [event for event in events if ability_id(event) in spell_ids and event_type(event) == "cast"],
        key=lambda event: int(event.get("timestamp") or 0),
    )


def aura_active_windows(fight, events, spell_id, players):
    """Build inclusive apply→remove windows for a player debuff."""
    pending = {}
    windows = []
    start = int(fight["startTime"])
    for event in sorted(events or [], key=lambda item: int(item.get("timestamp") or 0)):
        if ability_id(event) != spell_id:
            continue
        target = event.get("targetID")
        if target not in players:
            continue
        kind = event_type(event)
        stamp = int(event.get("timestamp") or 0)
        if kind in {"applydebuff", "applydebuffstack", "refreshdebuff"}:
            pending.setdefault(target, stamp)
        elif kind == "removedebuff":
            apply = pending.pop(target, stamp)
            windows.append({"playerID": target, "applyTimeMs": apply - start, "removeTimeMs": stamp - start})
    end_ms = int(fight["endTime"]) - start
    for target, apply in pending.items():
        windows.append({"playerID": target, "applyTimeMs": apply - start, "removeTimeMs": end_ms})
    return windows


def under_aura(windows, player_id, time_ms):
    return any(
        row["playerID"] == player_id and int(row["applyTimeMs"]) <= int(time_ms) <= int(row["removeTimeMs"])
        for row in windows or []
    )


def cluster_burst_events(fight, damage, players):
    """Collapse Frost Burst AoE into one cluster per explosion."""
    start = int(fight["startTime"])
    hits = sorted(
        [
            event for event in damage or []
            if ability_id(event) == ORB_BURST_ID and event.get("targetID") in players
        ],
        key=lambda event: int(event.get("timestamp") or 0),
    )
    clusters = []
    for event in hits:
        stamp = int(event.get("timestamp") or 0)
        amount = int(event.get("amount") or event.get("unmitigatedAmount") or 0)
        target = event.get("targetID")
        if clusters and stamp - clusters[-1]["absoluteTime"] <= BURST_CLUSTER_MS:
            cluster = clusters[-1]
            cluster["hitCount"] += 1
            cluster["totalDamage"] += amount
            cluster["targetIDs"].add(target)
            continue
        clusters.append({
            "absoluteTime": stamp,
            "timeMs": stamp - start,
            "time": fmt_ms(stamp - start),
            "hitCount": 1,
            "totalDamage": amount,
            "targetIDs": {target},
        })
    for cluster in clusters:
        cluster["targetIDs"] = sorted(cluster["targetIDs"])
    return clusters


def orb_touch_events(fight, debuffs, players):
    """Frost Orb applydebuff is the touch evidence; stack ticks are not new soaks."""
    start = int(fight["startTime"])
    touches = []
    last_touch = {}
    for event in sorted(debuffs or [], key=lambda item: int(item.get("timestamp") or 0)):
        if ability_id(event) != ORB_AURA_ID or event_type(event) != "applydebuff":
            continue
        target = event.get("targetID")
        if target not in players:
            continue
        stamp = int(event.get("timestamp") or 0)
        previous = last_touch.get(target)
        # Guard against rare double-apply noise on the same soak.
        if previous is not None and stamp - previous <= 800:
            continue
        last_touch[target] = stamp
        touches.append({
            "absoluteTime": stamp,
            "timeMs": stamp - start,
            "time": fmt_ms(stamp - start),
            "playerID": target,
            "stack": int(event.get("stack") or event.get("stacks") or 1),
            "kind": event_type(event),
        })
    return touches


def rain_channel_windows(fight, casts):
    """Abyssal Rain: finished cast then ~4s channel. Touches only count inside this window."""
    start = int(fight["startTime"])
    windows = []
    for cast in completed_casts(casts, {RAIN_CAST_ID}):
        begin = int(cast.get("timestamp") or 0) - start
        windows.append({"startTimeMs": begin, "endTimeMs": begin + RAIN_CHANNEL_MS, "time": fmt_ms(begin)})
    return windows


def under_rain_channel(windows, time_ms):
    return any(int(row["startTimeMs"]) <= int(time_ms) <= int(row["endTimeMs"]) for row in windows or [])


def classify_orb_outcomes(fight, actor_map, players, raw):
    """Split ground-orb resolution into player touches vs auto/timeout bursts."""
    start = int(fight["startTime"])
    rain_channels = rain_channel_windows(fight, raw.get("casts") or [])
    touches_raw = orb_touch_events(fight, raw.get("debuffs") or [], players)
    bursts = cluster_burst_events(fight, raw.get("damage") or [], players)
    touches = []
    for touch in touches_raw:
        ref = player_ref(players, actor_map, touch["playerID"])
        rain_active = under_rain_channel(rain_channels, touch["timeMs"])
        role = ref.get("role") or "unknown"
        touches.append({
            **ref,
            **touch,
            "underAbyssalRain": rain_active,
            "review": (
                "深渊之雨引导期间踩球"
                if rain_active else
                "坦克踩球"
                if role == "tank" else
                "非坦克踩球"
                if role != "unknown" else
                "踩球（角色未知）"
            ),
            "problem": rain_active or role not in {"tank", "unknown"},
        })

    used_touches = set()
    burst_rows = []
    for index, burst in enumerate(bursts, start=1):
        nearby = [
            touch for touch_index, touch in enumerate(touches)
            if touch_index not in used_touches
            and 0 <= burst["absoluteTime"] - touch["absoluteTime"] <= TOUCH_BEFORE_BURST_MS
        ]
        nearby.sort(key=lambda row: burst["absoluteTime"] - row["absoluteTime"])
        trigger = nearby[0] if nearby else None
        if trigger is not None:
            used_touches.add(next(
                touch_index for touch_index, touch in enumerate(touches)
                if touch is trigger or (
                    touch["playerID"] == trigger["playerID"] and touch["absoluteTime"] == trigger["absoluteTime"]
                )
            ))
        timed_out = trigger is None
        burst_rows.append({
            "index": index,
            "timeMs": burst["timeMs"],
            "time": burst["time"],
            "hitCount": burst["hitCount"],
            "totalDamage": burst["totalDamage"],
            "timedOut": timed_out,
            "triggered": not timed_out,
            "triggerPlayerID": None if trigger is None else trigger["playerID"],
            "triggerPlayer": None if trigger is None else trigger.get("player"),
            "triggerClassColor": None if trigger is None else trigger.get("classColor"),
            "triggerUnderAbyssalRain": False if trigger is None else bool(trigger.get("underAbyssalRain")),
            "outcome": "超时自爆" if timed_out else "踩球触发爆发",
            "problem": timed_out or bool(trigger and trigger.get("underAbyssalRain")),
        })

    rain_touches = [row for row in touches if row.get("underAbyssalRain")]
    return {
        "touches": touches,
        "bursts": burst_rows,
        "rainTouches": rain_touches,
        "rainChannels": rain_channels,
        "checks": {
            "touchCount": len(touches),
            "timeoutBursts": sum(1 for row in burst_rows if row["timedOut"]),
            "touchBursts": sum(1 for row in burst_rows if row["triggered"]),
            "rainTouchCount": len(rain_touches),
        },
        "policy": dict(FROST_POLICY),
        "note": (
            "踩球以 Frost Orb 光环首次应用为准；超时自爆以 Frost Burst 全团伤害簇为准。"
            "若爆发前 2.5 秒内有踩球，记为踩球触发；否则记为场地球自动爆炸。"
            "深渊之雨仅统计正读条结束后 4 秒引导窗内的踩球。"
        ),
    }


def sample_at(samples, time_ms):
    """Last [t,x,y] at or before time_ms."""
    if not samples:
        return None
    lo, hi = 0, len(samples)
    while lo < hi:
        mid = (lo + hi) // 2
        if samples[mid][0] <= time_ms:
            lo = mid + 1
        else:
            hi = mid
    if lo <= 0:
        return None
    row = samples[lo - 1]
    return {"x": row[1], "y": row[2], "timeMs": row[0]}


def boss_unit_from_replay(replay):
    for unit in (replay or {}).get("units") or []:
        if unit.get("gameID") == BOSS_GAME_ID or "Nymrissa" in str(unit.get("name") or ""):
            return unit
    bosses = (replay or {}).get("bosses") or []
    if not bosses:
        return None
    boss_id = bosses[0].get("actorID")
    return next((unit for unit in (replay or {}).get("units") or [] if unit.get("actorID") == boss_id), None)


def arena_bounds_from_replay(replay, center=None):
    xs, ys = [], []
    for unit in (replay or {}).get("units") or []:
        if unit.get("kind") not in {"player", "enemy"}:
            continue
        for row in unit.get("samples") or []:
            xs.append(row[1])
            ys.append(row[2])
    if not xs:
        return None
    pad = UNITS_PER_YARD * 8
    min_x, max_x, min_y, max_y = min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad
    # Bubble must sit on the projected map center (= bounding-box midpoint).
    center = center or {"x": (min_x + max_x) / 2, "y": (min_y + max_y) / 2}
    return {
        "minX": min_x,
        "maxX": max_x,
        "minY": min_y,
        "maxY": max_y,
        "centerX": center["x"],
        "centerY": center["y"],
        "unitsPerYard": UNITS_PER_YARD,
    }


def arena_center_from_replay(replay):
    """诱人水泡固定在场地几何中心（投影后正中央），不跟 Boss 瞬时坐标。"""
    bounds = arena_bounds_from_replay(replay)
    if not bounds:
        return None
    return {"x": bounds["centerX"], "y": bounds["centerY"]}


def direction_index(dx, dy):
    """0=北 … 7=西北，顺时针。+y 北、+x 东。"""
    angle = math.atan2(dx, dy)  # 0 = north, positive toward east
    sector = (angle + math.pi) / (math.pi / 4)
    return int(sector) % 8


def direction_label(index):
    return SURGE_DIRECTIONS[int(index) % 8]


def player_position_at(replay, player_id, time_ms):
    unit = next((row for row in (replay or {}).get("units") or [] if row.get("actorID") == player_id and row.get("kind") == "player"), None)
    point = sample_at((unit or {}).get("samples") or [], time_ms)
    return point


def build_alluring_bubbles(fight, casts, replay, center):
    """诱人水泡 cast → 嘭！；圈固定在场地中心约 10 码。"""
    start = int(fight["startTime"])
    end_ms = int(fight["endTime"]) - start
    bubble_casts = completed_casts(casts, {BUBBLE_CAST_ID})
    pop_casts = completed_casts(casts, {POP_CAST_ID})
    pops = [int(event.get("timestamp") or 0) - start for event in pop_casts]
    rows = []
    for index, cast in enumerate(bubble_casts, start=1):
        begin = int(cast.get("timestamp") or 0) - start
        pop = next((time for time in pops if time >= begin), None)
        next_bubble = (
            int(bubble_casts[index].get("timestamp") or 0) - start
            if index < len(bubble_casts) else end_ms
        )
        end = pop if pop is not None else next_bubble
        rows.append({
            "index": index,
            "startTimeMs": begin,
            "endTimeMs": end,
            "popTimeMs": pop,
            "time": fmt_ms(begin),
            "endTime": fmt_ms(end),
            "popTime": fmt_ms(pop) if pop is not None else None,
            "radiusYards": ALLURING_BUBBLE_RADIUS_YARDS,
            "center": {"x": center["x"], "y": center["y"]} if center else None,
            "spellID": BUBBLE_CAST_ID,
            "popSpellID": POP_CAST_ID,
            "note": "诱人水泡固定在场地中心约 10 码，持续到嘭！。",
        })
    return rows


def build_surging_vortex(fight, actor_map, players, casts, damage, replay, center):
    """8 向涌向中心：读条完预兆约 5 秒，再缓慢涌入；安全区用抵达时刻站位。"""
    start = int(fight["startTime"])
    end_ms = int(fight["endTime"]) - start
    begins = sorted(
        [event for event in casts if ability_id(event) == SURGE_CAST_ID and event_type(event) == "begincast"],
        key=lambda event: int(event.get("timestamp") or 0),
    )
    finishes = completed_casts(casts, {SURGE_CAST_ID})
    if not finishes and begins:
        finishes = begins
    pop_times = [
        int(event.get("timestamp") or 0) - start
        for event in casts
        if ability_id(event) == POP_CAST_ID and event_type(event) == "cast"
    ]
    hits = [
        event for event in damage or []
        if ability_id(event) in SURGE_DAMAGE_IDS and event.get("targetID") in players
    ]
    rounds = []
    for index, cast in enumerate(finishes, start=1):
        finish = int(cast.get("timestamp") or 0) - start
        begin_event = next((event for event in reversed(begins) if int(event.get("timestamp") or 0) - start <= finish), None)
        begin = int(begin_event.get("timestamp") or 0) - start if begin_event else finish
        next_finish = (
            int(finishes[index].get("timestamp") or 0) - start
            if index < len(finishes) else end_ms
        )
        pop = next((time for time in pop_times if time >= finish), None)
        foreshadow_end = finish + SURGE_FORESHADOW_MS
        arrival = foreshadow_end + SURGE_TRAVEL_MS
        if pop is not None:
            arrival = min(arrival, pop)
        window_end = min(next_finish, pop if pop is not None else arrival + 5_000)
        window_hits = [
            event for event in hits
            if foreshadow_end - 500 <= int(event.get("timestamp") or 0) - start < window_end
        ]
        hit_ids = {event["targetID"] for event in window_hits}
        by_player = defaultdict(list)
        for event in window_hits:
            by_player[event["targetID"]].append(event)
        players_hit = []
        for player_id, events in by_player.items():
            # Hit direction uses position near first damage; safe zone uses arrival only.
            hit_time = int(events[0].get("timestamp") or 0) - start
            point = player_position_at(replay, player_id, hit_time) if center else None
            sector = None
            if point and center:
                sector = direction_index(point["x"] - center["x"], point["y"] - center["y"])
            players_hit.append({
                **player_ref(players, actor_map, player_id),
                "hitCount": len(events),
                "totalDamage": sum(int(event.get("amount") or event.get("unmitigatedAmount") or 0) for event in events),
                "times": [fmt_ms(int(event.get("timestamp") or 0) - start) for event in events],
                "firstTimeMs": hit_time,
                "firstTime": fmt_ms(hit_time),
                "directionIndex": sector,
                "direction": direction_label(sector) if sector is not None else None,
                "position": point,
            })
        players_hit.sort(key=lambda row: (-row["hitCount"], -row["totalDamage"], row["player"]))

        # Safe wedge: densest sector among living, unhit players at wave ARRIVAL (not cast start).
        sector_votes = Counter()
        for player_id in players:
            if player_id in hit_ids or not center:
                continue
            point = player_position_at(replay, player_id, arrival)
            if not point:
                continue
            sector_votes[direction_index(point["x"] - center["x"], point["y"] - center["y"])] += 1
        safe_index = sector_votes.most_common(1)[0][0] if sector_votes else None
        rounds.append({
            "index": index,
            "timeMs": begin,
            "time": fmt_ms(begin),
            "castEndTimeMs": finish,
            "castEndTime": fmt_ms(finish),
            "foreshadowEndTimeMs": foreshadow_end,
            "foreshadowEndTime": fmt_ms(foreshadow_end),
            "arrivalTimeMs": arrival,
            "arrivalTime": fmt_ms(arrival),
            "popTimeMs": pop,
            "popTime": fmt_ms(pop) if pop is not None else None,
            "endTimeMs": window_end,
            "endTime": fmt_ms(window_end),
            "spellID": SURGE_CAST_ID,
            "spellName": spell_name(SURGE_CAST_ID),
            "hitCount": len(window_hits),
            "playerCount": len(players_hit),
            "players": players_hit,
            "safeDirectionIndex": safe_index,
            "safeDirection": direction_label(safe_index) if safe_index is not None else None,
            "sectorCounts": {direction_label(i): sector_votes.get(i, 0) for i in range(8)},
            "problem": bool(players_hit),
            "note": "读条完预兆约 5 秒后缓慢涌入中心；安全方向按抵达时刻未中招站位众数推断。",
        })
    return {
        "rounds": rounds,
        "directions": list(SURGE_DIRECTIONS),
        "players": sorted(
            [
                {
                    **player_ref(players, actor_map, player_id),
                    "hitCount": sum(1 for event in hits if event.get("targetID") == player_id),
                    "totalDamage": sum(
                        int(event.get("amount") or event.get("unmitigatedAmount") or 0)
                        for event in hits if event.get("targetID") == player_id
                    ),
                    "times": [
                        fmt_ms(int(event.get("timestamp") or 0) - start)
                        for event in hits if event.get("targetID") == player_id
                    ],
                }
                for player_id in {event.get("targetID") for event in hits}
            ],
            key=lambda row: (-row["hitCount"], -row["totalDamage"], row["player"]),
        ),
        "note": (
            "激荡漩涡从八个方向涌向中心，仅一处安全。"
            "读条完成后预兆约 5 秒，再缓慢移向场地中间；"
            "安全方向按涌入抵达时刻未中招玩家站位众数推断（不是读条开始时的站位）。"
        ),
    }


def _dist2(a, b):
    return (a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2


def build_ground_orbs_and_puddles(fight, actor_map, players, damage, debuffs, replay, orb_review):
    """Each Chilling Frost tick drops one ice orb at feet (≈3 per mark); soak → 5yd water."""
    start = int(fight["startTime"])
    end_ms = int(fight["endTime"]) - start
    drops = sorted(
        [
            event for event in damage or []
            if ability_id(event) == FROST_DROP_SPELL_ID and event.get("targetID") in players
        ],
        key=lambda event: int(event.get("timestamp") or 0),
    )
    touches = list(orb_review.get("touches") or [])
    bursts = list(orb_review.get("bursts") or [])
    orbs = []
    for index, event in enumerate(drops, start=1):
        time_ms = int(event.get("timestamp") or 0) - start
        player_id = event.get("targetID")
        point = player_position_at(replay, player_id, time_ms)
        if not point:
            continue
        orbs.append({
            "index": index,
            "key": f"orb:{index}:{player_id}:{time_ms}",
            "startTimeMs": time_ms,
            "endTimeMs": min(end_ms, time_ms + ORB_PUDDLE_DURATION_MS),
            "x": point["x"],
            "y": point["y"],
            "dropperID": player_id,
            "dropper": player_ref(players, actor_map, player_id).get("player"),
            "consumed": False,
            "consumeTimeMs": None,
            "consumeBy": None,
            "puddle": False,
        })

    soak_radius2 = (UNITS_PER_YARD * 12) ** 2
    for touch in touches:
        touch_pos = player_position_at(replay, touch["playerID"], touch["timeMs"])
        if not touch_pos:
            continue
        candidates = [
            orb for orb in orbs
            if not orb["consumed"]
            and orb["startTimeMs"] <= touch["timeMs"] <= orb["endTimeMs"]
            and _dist2(orb, touch_pos) <= soak_radius2
        ]
        if not candidates:
            # Fallback: nearest orb dropped in the last 35s regardless of distance noise.
            candidates = [
                orb for orb in orbs
                if not orb["consumed"] and 0 <= touch["timeMs"] - orb["startTimeMs"] <= 35_000
            ]
        if not candidates:
            continue
        candidates.sort(key=lambda orb: (_dist2(orb, touch_pos), touch["timeMs"] - orb["startTimeMs"]))
        orb = candidates[0]
        orb["consumed"] = True
        orb["consumeTimeMs"] = touch["timeMs"]
        orb["consumeBy"] = touch.get("player")
        orb["endTimeMs"] = touch["timeMs"]
        orb["puddle"] = True
        orb["puddleStartMs"] = touch["timeMs"]
        orb["puddleEndMs"] = min(end_ms, touch["timeMs"] + ORB_PUDDLE_DURATION_MS)
        orb["underAbyssalRain"] = bool(touch.get("underAbyssalRain"))

    for burst in bursts:
        if burst.get("triggered") and burst.get("triggerPlayerID") is not None:
            # Already handled via matching touch when possible.
            continue
        burst_time = burst["timeMs"]
        for orb in orbs:
            if orb["consumed"]:
                continue
            if 0 <= burst_time - orb["startTimeMs"] <= 35_000 and burst_time <= orb["endTimeMs"]:
                orb["consumed"] = True
                orb["consumeTimeMs"] = burst_time
                orb["endTimeMs"] = burst_time
                orb["puddle"] = False  # timeout burst: no lingering soak water

    puddles = [
        {
            "key": f"puddle:{orb['index']}",
            "startTimeMs": orb["puddleStartMs"],
            "endTimeMs": orb["puddleEndMs"],
            "x": orb["x"],
            "y": orb["y"],
            "radiusYards": ORB_PUDDLE_RADIUS_YARDS,
            "source": orb.get("consumeBy") or orb.get("dropper"),
        }
        for orb in orbs
        if orb.get("puddle") and orb.get("puddleStartMs") is not None
    ]
    return {
        "orbs": [
            {
                "key": orb["key"],
                "index": orb["index"],
                "startTimeMs": orb["startTimeMs"],
                "endTimeMs": orb["endTimeMs"],
                "x": orb["x"],
                "y": orb["y"],
                "dropper": orb.get("dropper"),
                "dropperID": orb.get("dropperID"),
                "consumed": orb["consumed"],
                "consumeTimeMs": orb.get("consumeTimeMs"),
            }
            for orb in orbs
        ],
        "puddles": puddles,
        "note": "点名后每次 Chilling Frost 伤害在脚下落一颗冰球（通常每人 3 颗）；踩球后留下约 5 码水面。",
    }


def build_water_jets(fight, actor_map, players, casts, damage, replay):
    """Boss Water Jet beam toward the primary tank while the jet is active."""
    start = int(fight["startTime"])
    begins = sorted(
        [event for event in casts or [] if ability_id(event) == WATER_JET_CAST_ID and event_type(event) == "begincast"],
        key=lambda event: int(event.get("timestamp") or 0),
    )
    finishes = completed_casts(casts or [], {WATER_JET_CAST_ID})
    dmg = sorted(
        [
            event for event in damage or []
            if ability_id(event) == WATER_JET_DAMAGE_ID and event.get("targetID") in players
        ],
        key=lambda event: int(event.get("timestamp") or 0),
    )
    rows = []
    for index, begin_event in enumerate(begins or finishes, start=1):
        begin = int(begin_event.get("timestamp") or 0) - start
        finish_event = next(
            (event for event in finishes if int(event.get("timestamp") or 0) - start >= begin),
            None,
        )
        cast_end = int(finish_event.get("timestamp") or 0) - start if finish_event else begin + 3_000
        next_begin = (
            int((begins or finishes)[index].get("timestamp") or 0) - start
            if index < len(begins or finishes) else begin + 20_000
        )
        window = [event for event in dmg if cast_end - 500 <= int(event.get("timestamp") or 0) - start < next_begin]
        if not window:
            # Windup with no logged damage yet — still show beam to current tank target of cast.
            target_id = begin_event.get("targetID")
            if target_id not in players:
                continue
            end = cast_end + 4_000
            rows.append({
                "index": index,
                "startTimeMs": begin,
                "endTimeMs": end,
                "castEndTimeMs": cast_end,
                "targetID": target_id,
                "target": player_ref(players, actor_map, target_id).get("player"),
                "hitCount": 0,
            })
            continue
        by_target = Counter(event.get("targetID") for event in window)
        target_id = by_target.most_common(1)[0][0]
        last_hit = int(window[-1].get("timestamp") or 0) - start
        rows.append({
            "index": index,
            "startTimeMs": begin,
            "endTimeMs": last_hit + 200,
            "castEndTimeMs": cast_end,
            "targetID": target_id,
            "target": player_ref(players, actor_map, target_id).get("player"),
            "hitCount": by_target[target_id],
            "spellID": WATER_JET_CAST_ID,
            "spellName": spell_name(WATER_JET_CAST_ID),
        })
    return rows


def build_murloc_review(fight, replay, casts):
    """大鱼人 Bubblefin Frostscale（附近减伤） / 小鱼人 Bubblefin Shorerunner（无技能）。"""
    start = int(fight["startTime"])
    end_ms = int(fight["endTime"]) - start
    bubble_casts = completed_casts(casts, {BUBBLE_CAST_ID})
    units = [
        unit for unit in (replay or {}).get("units") or []
        if unit.get("gameID") in MURLOC_GAME_IDS
    ]
    rounds = []
    for index, cast in enumerate(bubble_casts, start=1):
        begin = int(cast.get("timestamp") or 0) - start
        next_begin = (
            int(bubble_casts[index].get("timestamp") or 0) - start
            if index < len(bubble_casts) else end_ms
        )
        big, small = [], []
        for unit in units:
            samples = unit.get("samples") or []
            if not samples:
                continue
            first, last = samples[0][0], samples[-1][0]
            if last < begin - 2_000 or first >= next_begin:
                continue
            death = next((state[0] for state in unit.get("states") or [] if state[1] == "dead" and begin - 2_000 <= state[0] < next_begin), None)
            row = {
                "actorID": unit.get("actorID"),
                "instance": unit.get("instance"),
                "gameID": unit.get("gameID"),
                "name": unit.get("name"),
                "kind": "big" if unit.get("gameID") == BIG_MURLOC_GAME_ID else "small",
                "spawnTimeMs": max(begin, first),
                "deathTimeMs": death,
                "deathTime": fmt_ms(death) if death is not None else None,
                "portrait": BIG_MURLOC_PORTRAIT if unit.get("gameID") == BIG_MURLOC_GAME_ID else None,
            }
            (big if row["kind"] == "big" else small).append(row)
        rounds.append({
            "index": index,
            "timeMs": begin,
            "time": fmt_ms(begin),
            "endTimeMs": next_begin,
            "bigCount": len(big),
            "smallCount": len(small),
            "big": big,
            "small": small,
            "killedBig": sum(1 for row in big if row.get("deathTimeMs") is not None),
            "killedSmall": sum(1 for row in small if row.get("deathTimeMs") is not None),
        })
    return {
        "rounds": rounds,
        "bigGameID": BIG_MURLOC_GAME_ID,
        "smallGameID": SMALL_MURLOC_GAME_ID,
        "bigName": "泡鳍霜鳞（大鱼人，附近减伤）",
        "smallName": "泡鳍短跑者（小鱼人，无特殊技能）",
        "bigPortrait": BIG_MURLOC_PORTRAIT,
        "note": "史诗大鱼人带水雾护盾给附近鱼人减伤，应优先处理；小鱼人无特殊技能。",
    }


def stamp_add_despawns(replay, fight):
    """Mark big murlocs dead when their position samples end so the field clears."""
    end_ms = int(fight["endTime"]) - int(fight["startTime"])
    for unit in (replay or {}).get("units") or []:
        if unit.get("gameID") != BIG_MURLOC_GAME_ID:
            continue
        samples = unit.get("samples") or []
        if not samples:
            continue
        states = list(unit.get("states") or [])
        if any(row[1] == "dead" for row in states):
            continue
        last = samples[-1][0]
        # Still alive at pull end — leave as-is.
        if last >= end_ms - 1_500:
            continue
        states.append([last, "dead"])
        unit["states"] = sorted(states, key=lambda row: row[0])
    return replay


def attach_boss_cast_bars(fight, replay, casts):
    start = int(fight["startTime"])
    bosses = list((replay or {}).get("bosses") or [])
    if not bosses:
        # Promote the Nymrissa unit into bosses so cast bars / status work.
        unit = boss_unit_from_replay(replay)
        if unit:
            bosses = [{"actorID": unit["actorID"], "gameID": unit.get("gameID"), "name": unit.get("name"), "health": [], "energy": [], "casts": [], "states": unit.get("states") or []}]
            replay = {**(replay or {}), "bosses": bosses}
        else:
            return replay
    boss = bosses[0]
    pending = None
    built = []
    relevant = {
        BUBBLE_CAST_ID, SURGE_CAST_ID, POP_CAST_ID, RAIN_CAST_ID, WATER_JET_CAST_ID,
        1257614, 1313393, 1294867, 1295086, 1263301,
    }
    for event in sorted(casts or [], key=lambda item: int(item.get("timestamp") or 0)):
        spell = ability_id(event)
        if spell not in relevant or event_type(event) not in {"begincast", "cast"}:
            continue
        source = event.get("sourceID")
        if source not in {None, -1, boss.get("actorID")}:
            continue
        time_ms = int(event.get("timestamp") or 0) - start
        kind = event_type(event)
        if kind == "begincast":
            if pending:
                pending["endTimeMs"] = time_ms
                pending["outcome"] = "unconfirmed"
            pending = {
                "startTimeMs": time_ms,
                "endTimeMs": time_ms + 1_000,
                "expectedEndTimeMs": time_ms + 1_000,
                "spellID": spell,
                "spellName": spell_name(spell),
                "outcome": "unconfirmed",
                "phase": "cast",
            }
            built.append(pending)
        elif pending and pending["spellID"] == spell:
            pending["endTimeMs"] = time_ms
            pending["expectedEndTimeMs"] = time_ms
            pending["outcome"] = "completed"
            pending = None
        elif kind == "cast" and not pending:
            # Instant / no-begincast (e.g. 嘭！). Do not duplicate bars that already have begincast.
            built.append({
                "startTimeMs": max(0, time_ms - 400),
                "endTimeMs": time_ms,
                "expectedEndTimeMs": time_ms,
                "spellID": spell,
                "spellName": spell_name(spell),
                "outcome": "completed",
                "phase": "cast",
            })
    boss["casts"] = sorted(built, key=lambda row: row["startTimeMs"])
    replay["bosses"] = [boss] + bosses[1:]
    return replay


def player_hit_board(fight, actor_map, players, damage, spell_ids):
    spell_ids = set(spell_ids)
    grouped = defaultdict(list)
    for event in damage:
        spell_id = ability_id(event)
        target_id = event.get("targetID")
        if spell_id in spell_ids and target_id in players:
            grouped[(target_id, spell_id)].append(event)
    rows = []
    for (target_id, spell_id), events in grouped.items():
        rows.append({
            **player_ref(players, actor_map, target_id),
            "spellID": spell_id,
            "spellName": spell_name(spell_id),
            "hitCount": len(events),
            "totalDamage": sum(int(event.get("amount") or event.get("unmitigatedAmount") or 0) for event in events),
            "events": [
                {
                    "timeMs": int(event.get("timestamp") or 0) - int(fight["startTime"]),
                    "time": fmt_ms(int(event.get("timestamp") or 0) - int(fight["startTime"])),
                    "amount": int(event.get("amount") or event.get("unmitigatedAmount") or 0),
                }
                for event in events
            ],
        })
    return sorted(rows, key=lambda row: (-row["hitCount"], -row["totalDamage"], row["player"]))


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
            "deathCause": "fall" if spell_id in {0, 3} else "ability",
        })
    seen_resurrections = set()
    for event in friendly_casts:
        spell_id = ability_id(event)
        target_id = event.get("targetID")
        if spell_id not in COMBAT_RES_SPELLS or target_id not in players or event_type(event) not in {"cast", "applybuff"}:
            continue
        timestamp = int(event.get("timestamp") or 0)
        identity = (timestamp // 1500, event.get("sourceID"), target_id, spell_id)
        if identity in seen_resurrections:
            continue
        seen_resurrections.add(identity)
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


def analyze_nymrissa(fight, actor_map, players, raw):
    options = resolve_analysis_options(CONFIG_SCHEMA, raw.get("analysisOptions") or {})
    start_time = int(fight["startTime"])
    end_time = int(fight["endTime"])
    damage = raw.get("damage") or []
    debuffs = raw.get("debuffs") or []
    casts = raw.get("casts") or []

    rain_casts = completed_casts(casts, {1260837}) if options["rainReviewEnabled"] else []
    rain_rounds = []
    for index, cast in enumerate(rain_casts, start=1):
        timestamp = int(cast.get("timestamp") or 0)
        channel_end = timestamp + RAIN_CHANNEL_MS
        hits = [event for event in damage if ability_id(event) == 1260843 and timestamp <= int(event.get("timestamp") or 0) < channel_end]
        rain_rounds.append({
            "index": index,
            "timeMs": timestamp - start_time,
            "time": fmt_ms(timestamp - start_time),
            "channelEndTimeMs": channel_end - start_time,
            "channelEndTime": fmt_ms(channel_end - start_time),
            "channelMs": RAIN_CHANNEL_MS,
            "hitCount": len(hits),
            "totalDamage": sum(int(event.get("amount") or 0) for event in hits),
        })

    drenched = {}
    for event in debuffs if options["rainReviewEnabled"] else []:
        if ability_id(event) not in {1277386, 1307352} or event.get("targetID") not in players:
            continue
        target_id = event["targetID"]
        stack = int(event.get("stack") or event.get("stacks") or (1 if event_type(event) == "applydebuff" else 0))
        current = drenched.setdefault(target_id, {**player_ref(players, actor_map, target_id), "maxStack": 0, "lastTime": ""})
        if stack >= current["maxStack"]:
            current["maxStack"] = stack
            current["lastTime"] = fmt_ms(int(event.get("timestamp") or 0) - start_time)

    barrage_casts = completed_casts(casts, {1257614, 1313393}) if options["frostReviewEnabled"] else []
    orb_review = classify_orb_outcomes(fight, actor_map, players, raw) if options["frostReviewEnabled"] else {
        "touches": [], "bursts": [], "rainTouches": [], "checks": {}, "policy": dict(FROST_POLICY), "note": "",
    }
    barrage_rounds = []
    for offset, cast in enumerate(barrage_casts):
        timestamp = int(cast.get("timestamp") or 0)
        next_timestamp = int(barrage_casts[offset + 1].get("timestamp") or end_time) if offset + 1 < len(barrage_casts) else end_time
        round_end = min(next_timestamp, timestamp + int(options["frostWindowSeconds"] * 1000))
        round_start_ms = timestamp - start_time
        round_end_ms = round_end - start_time
        target_ids = {
            event.get("targetID")
            for event in debuffs
            if ability_id(event) in {1257608, 1257644, 1313393}
            and event_type(event) in {"applydebuff", "refreshdebuff"}
            and timestamp - 2_000 <= int(event.get("timestamp") or 0) <= timestamp + 8_000
            and event.get("targetID") in players
        }
        round_touches = [row for row in orb_review["touches"] if round_start_ms <= row["timeMs"] < round_end_ms]
        round_bursts = [row for row in orb_review["bursts"] if round_start_ms <= row["timeMs"] < round_end_ms]
        rain_touches = [row for row in round_touches if row.get("underAbyssalRain")]
        barrage_rounds.append({
            "index": offset + 1,
            "timeMs": round_start_ms,
            "time": fmt_ms(round_start_ms),
            "spellID": ability_id(cast),
            "spellName": spell_name(ability_id(cast)),
            "targets": [player_ref(players, actor_map, player_id) for player_id in sorted(target_ids)],
            "touches": round_touches,
            "bursts": round_bursts,
            "rainTouches": rain_touches,
            "handlers": [
                {**player_ref(players, actor_map, player_id), "underAbyssalRain": any(row["playerID"] == player_id and row.get("underAbyssalRain") for row in round_touches)}
                for player_id in sorted({row["playerID"] for row in round_touches})
            ],
            "contacts": round_touches,
            "tankContacts": [row for row in round_touches if row.get("role") == "tank"],
            "nonTankContacts": [row for row in round_touches if row.get("role") not in {"tank", "unknown"}],
            "timeoutBurstCount": sum(1 for row in round_bursts if row.get("timedOut")),
            "touchBurstCount": sum(1 for row in round_bursts if row.get("triggered")),
            "rainTouchCount": len(rain_touches),
            "burstHitCount": sum(row.get("hitCount") or 0 for row in round_bursts),
            "burstDamage": sum(row.get("totalDamage") or 0 for row in round_bursts),
            # Kept for older UI readers; damage ticks are no longer the touch source of truth.
            "orbHitCount": len(round_touches),
        })

    bubble_casts = completed_casts(casts, {BUBBLE_CAST_ID}) if options["transitionReviewEnabled"] else []
    transitions = []
    for offset, cast in enumerate(bubble_casts):
        timestamp = int(cast.get("timestamp") or 0)
        next_timestamp = int(bubble_casts[offset + 1].get("timestamp") or end_time) if offset + 1 < len(bubble_casts) else end_time
        window_end = min(next_timestamp, timestamp + int(options["transitionWindowSeconds"] * 1000))
        add_waves = [event for event in casts if ability_id(event) == 1263301 and timestamp <= int(event.get("timestamp") or 0) < window_end and event_type(event) == "cast"]
        pulses = [event for event in damage if ability_id(event) == 1271380 and timestamp <= int(event.get("timestamp") or 0) < window_end]
        transitions.append({
            "index": offset + 1,
            "timeMs": timestamp - start_time,
            "time": fmt_ms(timestamp - start_time),
            "addWaveCount": len(add_waves),
            "pulsingHitCount": len(pulses),
            "pulsingDamage": sum(int(event.get("amount") or 0) for event in pulses),
        })

    enrage_casts = completed_casts(casts, {1294867, 1295086})
    enrage_time = int(enrage_casts[0].get("timestamp") or 0) if enrage_casts else 0
    hazard_hits = player_hit_board(fight, actor_map, players, damage, {1257654} | SURGE_DAMAGE_IDS) if options["pressureReviewEnabled"] else []
    tank_hits = player_hit_board(fight, actor_map, players, damage, {1282945, 1271458}) if options["pressureReviewEnabled"] else []
    # Surging vortex / murlocs / bubbles need combatReplay — filled in render_fight.
    rain_touches = orb_review.get("rainTouches") or []
    return {
        "abyssalRain": {
            "rounds": rain_rounds,
            "drenched": sorted(drenched.values(), key=lambda row: (-row["maxStack"], row["player"])),
            "channelMs": RAIN_CHANNEL_MS,
            "note": "正读条结束后引导约 4 秒；下列承伤与雨中踩球均按该引导窗统计。",
        },
        "frostBarrage": {"rounds": barrage_rounds, "policy": dict(FROST_POLICY), "orbReview": orb_review},
        "orbReview": orb_review,
        "rainOrbTouches": {
            "players": rain_touches,
            "count": len(rain_touches),
            "note": FROST_POLICY["rainTouchRule"],
        },
        "surgingVortex": {"rounds": [], "players": [], "note": ""},
        "murlocs": {"rounds": [], "note": ""},
        "transitions": transitions,
        "alluringBubbles": [],
        "hazardHits": hazard_hits,
        "tankPressure": tank_hits,
        "enrage": {"triggered": bool(enrage_casts), "timeMs": enrage_time - start_time if enrage_time else None, "time": fmt_ms(enrage_time - start_time) if enrage_time else None},
        "portraits": {"boss": BOSS_PORTRAIT, "bigMurloc": BIG_MURLOC_PORTRAIT},
        "checks": {
            **(orb_review.get("checks") or {}),
            "surgeHitPlayers": 0,
            "surgeRounds": 0,
        },
    }


analyze_mechanics = analyze_nymrissa


def fetch_payload(client, report_id, fight, options=None):
    options = resolve_analysis_options(CONFIG_SCHEMA, options or {})
    rain, frost, transition, pressure = (options[key] for key in ("rainReviewEnabled", "frostReviewEnabled", "transitionReviewEnabled", "pressureReviewEnabled"))
    cast_ids = (
        {1294867, 1295086, BUBBLE_CAST_ID, POP_CAST_ID, SURGE_CAST_ID, WATER_JET_CAST_ID}
        | ({1260837} if rain or frost else set())  # frost rain-touch needs rain cast→4s channel
        | ({1257614, 1313393} if frost else set())
        | ({1263301} if transition else set())
    )
    damage_ids = (
        ({1260843} if rain else set())
        | ({1257651, 1281393, 1313393, 1313448, 1313450} if frost else set())
        | ({1271380} | SURGE_DAMAGE_IDS | {1258154} if transition else set())
        | ({LINGERING_FROST_ID, 1282945, WATER_JET_DAMAGE_ID} | SURGE_DAMAGE_IDS if pressure else set())
        | {WATER_JET_DAMAGE_ID}  # field replay always needs jet beam targets
    )
    # Frost review needs Abyssal Rain aura windows to flag rain-period orb touches.
    debuff_ids = (
        ({1277386, 1307352, 1260843} if rain else set())
        | ({1257608, 1257644, 1282537, 1313393, 1313448, 1260843} if frost else set())
        | ({1260637} if pressure else set())
    )
    def fetch(stream, ids, **kwargs):
        if not ids:
            return []
        expression = "ability.id in (" + ", ".join(str(value) for value in sorted(ids)) + ")"
        return client.events(report_id, stream, fight, filter_expression=expression, **kwargs)
    return {
        "casts": fetch("Casts", cast_ids, hostility_type="Enemies"),
        "friendlyCasts": client.events(report_id, "Casts", fight, hostility_type="Friendlies"),
        "damage": fetch("DamageTaken", damage_ids, include_resources=True),
        "debuffs": fetch("Debuffs", debuff_ids, include_resources=True),
        "deaths": client.events(report_id, "Deaths", fight),
        "combatants": client.events(report_id, "CombatantInfo", fight),
        "replayEvents": fetch_replay_events(client, report_id, fight) if options["fullReplayEnabled"] else [],
        "analysisOptions": options,
    }


def render_fight(report_id, report_start, actors, fight, raw):
    actor_map, players = build_players(actors, raw.get("combatants") or [])
    deaths = [event for event in raw.get("deaths") or [] if event.get("targetID") in players]
    survival = survival_timeline(fight, actor_map, players, deaths, raw.get("friendlyCasts") or [])
    mechanics = analyze_nymrissa(fight, actor_map, players, raw)
    if raw.get("replayEvents"):
        replay = build_replay_tracks(
            fight, players, actor_map, raw["replayEvents"],
            actor_rows=actors, spell_names=SPELL_NAMES, deaths=deaths, survival_timeline=survival["timeline"],
        )
        replay = attach_boss_cast_bars(fight, replay, raw.get("casts") or [])
        replay = stamp_add_despawns(replay, fight)
        center = arena_center_from_replay(replay)
        arena = arena_bounds_from_replay(replay, center)
        bubbles = build_alluring_bubbles(fight, raw.get("casts") or [], replay, center)
        surging = build_surging_vortex(
            fight, actor_map, players, raw.get("casts") or [], raw.get("damage") or [], replay, center,
        ) if (raw.get("analysisOptions") or {}).get("transitionReviewEnabled", True) else {"rounds": [], "players": [], "note": ""}
        murlocs = build_murloc_review(fight, replay, raw.get("casts") or [])
        orb_fx = build_ground_orbs_and_puddles(
            fight, actor_map, players, raw.get("damage") or [], raw.get("debuffs") or [],
            replay, mechanics.get("orbReview") or {},
        )
        water_jets = build_water_jets(
            fight, actor_map, players, raw.get("casts") or [], raw.get("damage") or [], replay,
        )
        mechanics["combatReplay"] = replay
        mechanics["alluringBubbles"] = bubbles
        mechanics["surgingVortex"] = surging
        mechanics["murlocs"] = murlocs
        mechanics["groundOrbs"] = orb_fx.get("orbs") or []
        mechanics["orbPuddles"] = orb_fx.get("puddles") or []
        mechanics["waterJets"] = water_jets
        mechanics["checks"] = {
            **(mechanics.get("checks") or {}),
            "surgeHitPlayers": sum(row.get("playerCount") or 0 for row in surging.get("rounds") or []),
            "surgeRounds": len(surging.get("rounds") or []),
            "bigMurlocs": sum(row.get("bigCount") or 0 for row in murlocs.get("rounds") or []),
            "smallMurlocs": sum(row.get("smallCount") or 0 for row in murlocs.get("rounds") or []),
            "groundOrbCount": len(orb_fx.get("orbs") or []),
            "orbPuddleCount": len(orb_fx.get("puddles") or []),
            "waterJetCount": len(water_jets),
        }
        mechanics["fieldReplay"] = {
            "enabled": True,
            "arenaImage": "/assets/raids/tidebound_grotto/01-nymrissa.jpg",
            "arena": arena,
            "center": center,
            "bubbles": bubbles,
            "radiusYards": ALLURING_BUBBLE_RADIUS_YARDS,
            "puddleRadiusYards": ORB_PUDDLE_RADIUS_YARDS,
            "groundOrbs": orb_fx.get("orbs") or [],
            "orbPuddles": orb_fx.get("puddles") or [],
            "waterJets": water_jets,
            "bossPortrait": BOSS_PORTRAIT,
            "bigMurlocPortrait": BIG_MURLOC_PORTRAIT,
            "note": (
                "诱人水泡固定在场地正中央约 10 码直到嘭！；"
                "激荡漩涡读条完预兆约 5 秒后缓慢涌入，安全区按抵达时站位；"
                "点名每次伤害落一冰球，踩球后留下约 5 码水面；水流喷射对坦射线。"
            ),
        }
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
        "difficultyName": difficulty_names.get(difficulty, f"未知难度 {difficulty}"),
        "wipeReason": "已击杀" if fight.get("kill") else "结合死亡时间线与机制轮次复盘",
        "investigation": "基础复盘只陈列可验证事件，不根据缺失的坐标或冰球生命周期强行归责。",
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
    emit_progress("读取尼姆瑞莎·唤潮者 Pull 列表", percent=8, stage="analyze")
    for report_id in report_id_list:
        report = client.report_fights(report_id)
        fights = filter_fights(
            report_id,
            [
                fight for fight in report.get("fights") or []
                if int(fight.get("encounterID") or 0) in ENCOUNTER_IDS
                and int(fight.get("endTime") or 0) - int(fight.get("startTime") or 0) >= 20_000
            ],
        )
        actors = client.actors(report_id)
        emit_progress(f"{report_id}：匹配 {len(fights)} 场", percent=12, stage="analyze")
        for index, fight in enumerate(fights, start=1):
            emit_progress(f"读取 Fight {fight['id']}（{index}/{len(fights)}）", stage="analyze")
            rendered.append(render_fight(report_id, report["startTime"], actors, fight, fetch_payload(client, report_id, fight, options)))
    rendered.sort(key=lambda row: (row["startTimeIso"], row["reportID"], row["fightID"]), reverse=True)
    hazard_rows = [row for pull in rendered for row in (pull[BOSS_CONFIG["key"]].get("hazardHits") or [])]
    emit_progress("生成尼姆瑞莎基础复盘", percent=96, stage="analyze")
    tab_gate = {
        "rain": "rainReviewEnabled",
        "frost": "frostReviewEnabled",
        "transition": "transitionReviewEnabled",
        "pressure": "pressureReviewEnabled",
    }
    return {
        "code": 200,
        "meta": {
            "version": "12.1",
            "raidKey": "tidebound_grotto",
            "raidName": "潮缚石窟",
            "bossKey": BOSS_CONFIG["key"],
            "bossName": BOSS_CONFIG["name"],
            "analyzedReports": report_id_list,
            "mechanicVersion": BOSS_CONFIG["mechanicVersion"],
            "tabDefinitions": [
                {"key": key, "label": label}
                for key, label in BOSS_CONFIG["tabs"]
                if key in {"survival", "replay"} or options[tab_gate[key]]
            ],
            "analysisConfig": options,
            "arenaImage": "assets/raids/tidebound_grotto/01-nymrissa.jpg",
            "features": {"survival": True, "fieldReplay": True},
            "evidenceLimits": {"attribution": "当前版本不使用缺失的冰球生命周期或位置数据判定个人责任。"},
        },
        "data": {
            "page1_wipeAnalysis": rendered,
            "page2_avoidableBoard": {"avoidable": hazard_rows},
        },
    }


def analyze(report_ids, output_path=None, catalog_entry=None, options=None, progress_callback=None):
    del progress_callback
    return write_json_result(
        build_aggregated_json(report_ids, options),
        output_path,
        catalog_entry=catalog_entry,
    )
