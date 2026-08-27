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
    player_ref,
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
WIND_STEP_DISPLACEMENT = 250
CROSSWIND_CIRCLE_YARDS = 6
CROSSWIND_LAUNCH_DEBUFF_ID = 1285447
CROSSWIND_ROUND_WINDOW_MS = 1_200
CROSSWIND_COLLISION_WINDOW_MS = 120
CROSSWIND_DAMAGE_IDS = {1285616, 1312219}
CYST_WIND_EXCLUSION_MS = 1_100
# WCL 战斗事件的 Y 坐标比回放地图显示坐标高 50 码。Boss 出生点在两套坐标中分别为
# 约 (-406.52, 388.43) 与 (-406.52, 338.43)。后端统一转成 WCL 地图坐标再输出。
SSZORAK_WCL_MAP_Y_OFFSET = -5_000
SSZORAK_ARENA_CENTER_X = -40_652.0
SSZORAK_ARENA_CENTER_Y = 33_843.0
SSZORAK_ARENA_RADIUS = 6_200.0
# WCL 坐标采用屏幕角度：0° 向右、90° 向下。六个风口之间留出 12 点与 6 点两个入口。
# 用户提供的 RaidPlan 底图相对 WCL 轨迹顺时针旋转 60° 后即可对齐。
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
    # 史诗难度新增的两种点名实例。方向最终以起飞后的坐标矢量为准，
    # 不把尚未由日志证明的图标方向硬编码进结论。
    1297096: {"key": "C", "label": "史诗额外方向 1297096", "angleDegrees": None, "wclAngleDegrees": None},
    1297111: {"key": "D", "label": "史诗额外方向 1297111", "angleDegrees": None, "wclAngleDegrees": None},
}


# 狂怒侧风起飞至对撞期间值得回看的主动位移技能。名称沿用简体中文客户端。
# 同一技能可能因形态、天赋或日志归一化产生多个法术 ID。
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
VENOM_GAIN_DAMAGE = {
    1289994: "腐蚀洪流",
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
    1294605: "邪恶洪流",
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
        "arena": "assets/raids/venomous_abyss/05-sszorak-arena.png",
        "bossIcon": "assets/raids/venomous_abyss/05-sszorak-boss.png",
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


def _frostfire_remove(debuffs, player_id, debuff_id, applied_at, fight_end):
    return next((event for event in debuffs if event.get("targetID") == player_id
                 and int(ability_id(event) or 0) == debuff_id
                 and event_type(event) == "removedebuff"
                 and applied_at <= int(event.get("timestamp") or 0) <= fight_end), None)


def _opposite_patch_at_remove(debuffs, player_id, patch_id, remove_ts):
    patch_events = sorted(
        (event for event in debuffs if event.get("targetID") == player_id
         and int(ability_id(event) or 0) == patch_id
         and event_type(event) in {"applydebuff", "refreshdebuff", "removedebuff"}
         and remove_ts - 15_000 <= int(event.get("timestamp") or 0) <= remove_ts + 150),
        key=lambda event: int(event.get("timestamp") or 0),
    )
    active_since = None
    for event in patch_events:
        timestamp = int(event.get("timestamp") or 0)
        if event_type(event) in {"applydebuff", "refreshdebuff"}:
            active_since = timestamp
        elif timestamp < remove_ts - 150:
            active_since = None
    return active_since


def analyze_lost(fight, actor_map, players, raw):
    casts, damage, debuffs, enemy_buffs, friendly_buffs = (raw[key] for key in ("casts", "damage", "debuffs", "enemyBuffs", "friendlyBuffs"))
    defense_events = [event for event in enemy_buffs if int(ability_id(event) or 0) == 1297646]
    per_boss_defense_rows = []
    active = {}
    for event in sorted(defense_events, key=lambda row: int(row.get("timestamp") or 0)):
        boss_id = event.get("targetID") or event.get("sourceID")
        if event_type(event) == "applybuff":
            active[boss_id] = int(event["timestamp"])
            continue
        if event_type(event) != "removebuff" or boss_id not in active:
            continue
        start_ts, end_ts = active.pop(boss_id), int(event["timestamp"])
        per_boss_defense_rows.append({
            "index": len(per_boss_defense_rows) + 1,
            "timestamp": start_ts,
            "timeMs": start_ts - fight["startTime"],
            "time": fmt_ms(start_ts - fight["startTime"]),
            "endTimeMs": end_ts - fight["startTime"],
            "endTime": fmt_ms(end_ts - fight["startTime"]),
            "durationSec": round((end_ts - start_ts) / 1000, 1),
            "bossID": boss_id,
            "bossName": source_name(actor_map, boss_id, SOURCE_NAMES),
        })
    for boss_id, start_ts in active.items():
        per_boss_defense_rows.append({
            "index": len(per_boss_defense_rows) + 1,
            "timestamp": start_ts,
            "timeMs": start_ts - fight["startTime"],
            "time": fmt_ms(start_ts - fight["startTime"]),
            "endTimeMs": None,
            "endTime": "战斗结束仍未结束",
            "durationSec": round((int(fight["endTime"]) - start_ts) / 1000, 1),
            "bossID": boss_id,
            "bossName": source_name(actor_map, boss_id, SOURCE_NAMES),
        })
    defense_rows = []
    for group in group_nearby(
        sorted(per_boss_defense_rows, key=lambda row: row["timeMs"]), window_ms=300,
    ):
        start_ms = min(row["timeMs"] for row in group)
        ended = [row["endTimeMs"] for row in group if row["endTimeMs"] is not None]
        end_ms = max(ended) if len(ended) == len(group) else None
        boss_names = sorted({row["bossName"] for row in group})
        if len(boss_names) < 2:
            continue
        defense_rows.append({
            "index": len(defense_rows) + 1,
            "timeMs": start_ms,
            "time": fmt_ms(start_ms),
            "endTimeMs": end_ms,
            "endTime": fmt_ms(end_ms) if end_ms is not None else "战斗结束仍未结束",
            "durationSec": round(((end_ms if end_ms is not None else fight["endTime"] - fight["startTime"]) - start_ms) / 1000, 1),
            "bossNames": boss_names,
            "bossName": "、".join(boss_names),
            "bossCount": len(boss_names),
        })
    total_defense_duration_sec = round(sum(row["durationSec"] for row in defense_rows), 1)
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
        end = int(volley_casts[index]["timestamp"]) if index < len(volley_casts) else int(fight["endTime"])
        assignments = [event for event in _events_between(debuffs, start - 1000, start + 6000, {1295928, 1295954}) if event_type(event) == "applydebuff"]
        assignment_rows = []
        for assignment in assignments:
            player_id = assignment.get("targetID")
            color = "fire" if int(ability_id(assignment) or 0) == 1295928 else "frost"
            debuff_id = int(ability_id(assignment))
            removed = _frostfire_remove(debuffs, player_id, debuff_id, int(assignment["timestamp"]), int(fight["endTime"]))
            remove_ts = int(removed["timestamp"]) if removed else None
            assignment_rows.append({
                **player_ref(players, actor_map, player_id),
                "color": color,
                "debuffID": debuff_id,
                "applyTimestamp": int(assignment["timestamp"]),
                "removeTimestamp": remove_ts,
                "removeTime": fmt_ms(remove_ts - fight["startTime"]) if remove_ts else None,
                "durationMs": remove_ts - int(assignment["timestamp"]) if remove_ts else None,
                "resolution": "unresolved",
                "resolutionReason": "debuff-not-removed",
                "leftPatchRisk": True,
                "collisionPartner": None,
            })
        for row in assignment_rows:
            remove_ts = row["removeTimestamp"]
            opposite_patch_id = 1297648 if row["color"] == "fire" else 1297649
            patch_since = (
                _opposite_patch_at_remove(debuffs, row["playerID"], opposite_patch_id, remove_ts)
                if remove_ts is not None else None
            )
            if patch_since is not None:
                row["resolution"] = "correct"
                row["resolutionReason"] = "opposite-patch-cleansing"
                row["oppositePatchID"] = opposite_patch_id
                row["oppositePatchSince"] = fmt_ms(patch_since - fight["startTime"])
                row["leftPatchRisk"] = False
            elif remove_ts and active_immunities(friendly_buffs, row["playerID"], remove_ts, 1800):
                row["resolution"], row["resolutionReason"] = "immunity", "immunity-remove"
            elif row["durationMs"] is not None and row["durationMs"] >= 20_000:
                row["resolution"], row["resolutionReason"] = "timeout", "timeout-remove-left-patch"
            elif remove_ts is not None:
                row["resolution"], row["resolutionReason"] = "wrong", "remove-without-opposite-color-window"
        for row in assignment_rows:
            if row["resolution"] not in {"wrong", "unresolved"} or row["removeTimestamp"] is None:
                continue
            opposite = "frost" if row["color"] == "fire" else "fire"
            candidates = [
                candidate for candidate in assignment_rows
                if candidate["color"] == opposite and candidate["removeTimestamp"] is not None
                and abs(candidate["removeTimestamp"] - row["removeTimestamp"]) <= 650
            ]
            if not candidates:
                continue
            partner = min(candidates, key=lambda candidate: abs(candidate["removeTimestamp"] - row["removeTimestamp"]))
            row["resolution"] = "correct"
            row["resolutionReason"] = "opposite-color-synchronized-remove"
            row["collisionPartner"] = player_ref(players, actor_map, partner["playerID"])
            row["leftPatchRisk"] = False
        volley_target = cast.get("targetID") if cast.get("targetID") in players else None
        volley_rounds.append({"index": index, "timeMs": start - fight["startTime"], "time": fmt_ms(start - fight["startTime"]),
                              "targetID": volley_target, "target": actor_name(actor_map, volley_target) if volley_target else "全团冰火分配", "assignments": assignment_rows})

    thud_casts = _completed_casts(casts, 1296094)
    thud_rounds = []
    for index, cast in enumerate(thud_casts, start=1):
        timestamp = int(cast["timestamp"])
        hits = sorted(_events_between(damage, timestamp - 500, timestamp + 6500, {1300237}),
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
    return {"unitedDefense": defense_rows, "unitedDefenseTotalSec": total_defense_duration_sec,
            "avoidable": {"players": avoidable, "missedIceboundFlames": len(missed),
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
        # 用户提供的 RaidPlan 原图为 986 x 554；场地半径在图中约为 270px。
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
        if any(abs(curr["timeMs"] - timestamp) <= CYST_WIND_EXCLUSION_MS for timestamp in excluded_timestamps):
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
        # 只有同一帧至少两名玩家同向移动，或该方向占本帧多数时，才作为持续风证据。
        if len(selected) >= 2 or len(selected) / len(step_vectors) >= .6:
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


def _death_near(deaths, player_id, timestamp, window_ms=500):
    return min(
        (event for event in deaths
         if event.get("targetID") == player_id
         and abs(int(event.get("timestamp") or 0) - timestamp) <= window_ms),
        key=lambda event: abs(int(event.get("timestamp") or 0) - timestamp),
        default=None,
    )


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
    return rows


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
        group_a = [row for row in targets if row["directionGroup"] == "A" and row["resolutionTimestamp"]]
        group_b = [row for row in targets if row["directionGroup"] == "B" and row["resolutionTimestamp"]]
        for left in sorted(group_a, key=lambda row: row["resolutionTimestamp"]):
            candidates = [
                right for right in group_b
                if right["playerID"] not in paired_ids
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
            "directionGroup": "A+B",
            "inferredDirection": "骷髅 ↔ 红叉",
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


def analyze_sszorak(fight, actor_map, players, raw):
    casts, damage, debuffs = raw["casts"], raw["damage"], raw["debuffs"]
    boss_id = raw.get("bossID")
    combat_position_index = build_position_index(raw.get("bossPositionEvents", []) + raw["resources"] + damage + debuffs)
    position_index = _sszorak_map_position_index(combat_position_index)
    arena = _sszorak_arena(position_index, boss_id=boss_id)
    deaths = raw["deaths"]
    death_times = _first_death_times(deaths, players)
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
    cyst_activations, unmatched_activations = _attribute_cyst_activations(
        fight, actor_map, players, raw, position_index, all_cysts, death_times,
    )
    digs = _completed_casts(casts, 1286033)
    cyst_rounds = []
    replay_rounds = []
    for index, dig in enumerate(digs, start=1):
        timestamp = int(dig["timestamp"])
        previous = int(digs[index - 2]["timestamp"]) if index > 1 else int(fight["startTime"])
        placements = [dict(row) for row in all_cysts if previous <= row["applyTimestamp"] <= timestamp][-4:]
        for slot, row in enumerate(placements, start=1):
            row["slot"] = slot

        end = timestamp + DIG_DURATION_MS
        frames = _player_positions_over_window(
            position_index,
            players,
            timestamp,
            end,
            step_ms=REPLAY_STEP_MS,
            death_times=death_times,
        )
        activation_rows = [
            {
                **row,
                "activatedTimestamp": fight["startTime"] + row["activatedAtMs"],
            }
            for row in all_cysts
            if row.get("activatedAtMs") is not None
            and timestamp <= fight["startTime"] + row["activatedAtMs"] <= end
        ]
        winds = _infer_dig_winds(
            frames, arena, segment_count=3, activation_rows=activation_rows,
        )
        validated = _placement_slot_validation(placements, winds)
        cyst_rounds.append({
            "index": index,
            "time": fmt_ms(timestamp - fight["startTime"]),
            "placements": validated,
            "windsComplete": len([wind for wind in winds if wind]) >= 3,
        })
        replay_rounds.append({
            "index": index,
            "timeMs": timestamp - fight["startTime"],
            "time": fmt_ms(timestamp - fight["startTime"]),
            "durationSec": DIG_DURATION_MS / 1000,
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
    )
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
        "cysts": {
            "rounds": cyst_rounds,
            "placements": all_cysts,
            "activations": cyst_activations,
            "unmatchedActivations": unmatched_activations,
        },
        "crosswinds": {"waves": crosswind_waves, "players": crosswind_rows},
        "fieldReplay": {
            "arena": arena,
            "arenaImage": BOSSES["sszorak"]["arena"],
            "bossIcon": BOSSES["sszorak"]["bossIcon"],
            "bossCenter": boss_center,
            "frameStepMs": REPLAY_STEP_MS,
            "rounds": replay_rounds,
            "crosswindWaves": crosswind_waves,
            "evidenceNote": "使用校正后的 RaidPlan 原图；WCL 轨迹旋转 60° 后映射到六个风口、三条对穿轴（12 点与 6 点是入口）；25 秒内按 200ms 插值采样；玩家死亡后停止位置预估；囊肿按光环、伤害、受迫位移和最近存活玩家证据激活后隐藏。",
        },
        "fallDeaths": fall_deaths,
    }


def _venom_attribution(damage_events, casts, timestamp, player_id):
    nearby = sorted(
        (event for event in damage_events if event.get("targetID") == player_id
         and abs(int(event.get("timestamp") or 0) - timestamp) <= 4500
         and int(ability_id(event) or 0) in {*VENOM_GAIN_DAMAGE, *VENOM_ABNORMAL_DAMAGE}),
        key=lambda event: abs(int(event.get("timestamp") or 0) - timestamp),
    )
    if nearby:
        spell_id = int(ability_id(nearby[0]) or 0)
        if spell_id in VENOM_ABNORMAL_DAMAGE:
            return VENOM_ABNORMAL_DAMAGE[spell_id], spell_id, "abnormal"
        return VENOM_GAIN_DAMAGE[spell_id], spell_id, "normal"
    emergence = min(
        (cast for cast in casts if int(ability_id(cast) or 0) in {1291404, 1308122}
         and abs(int(cast.get("timestamp") or 0) - timestamp) <= 4500),
        key=lambda cast: abs(int(cast.get("timestamp") or 0) - timestamp),
        default=None,
    )
    if emergence:
        spell_id = int(ability_id(emergence) or 0)
        return "剧毒涌现", spell_id, "normal"
    targeted_cast = min(
        (cast for cast in casts if cast.get("targetID") == player_id
         and int(ability_id(cast) or 0) in {1289201, 1291478}
         and abs(int(cast.get("timestamp") or 0) - timestamp) <= 4500),
        key=lambda cast: abs(int(cast.get("timestamp") or 0) - timestamp),
        default=None,
    )
    if targeted_cast:
        spell_id = int(ability_id(targeted_cast) or 0)
        return VENOM_GAIN_DAMAGE.get(spell_id, spell_name(spell_id)), spell_id, "normal"
    if any(abs(int(cast.get("timestamp") or 0) - timestamp) <= 3500 for cast in casts if int(ability_id(cast) or 0) in FEAST_IDS):
        return spell_name(1290516), 1290516, "feast"
    return "未匹配到已知叠层伤害", None, "unknown"


def _venom_stack_at(events, player_id, timestamp):
    current = 0
    for event in sorted(
        (row for row in events if row.get("targetID") == player_id
         and int(row.get("timestamp") or 0) <= timestamp),
        key=lambda row: int(row.get("timestamp") or 0),
    ):
        kind = event_type(event)
        raw_stack = event.get("stack")
        if kind in {"applydebuff", "applydebuffstack", "refreshdebuff"}:
            current = int(raw_stack) if raw_stack is not None else max(1, current + (1 if kind == "applydebuffstack" else 0))
        elif kind == "removedebuffstack":
            current = int(raw_stack) if raw_stack is not None else max(0, current - 1)
        elif kind == "removedebuff":
            current = 0
    return current


def analyze_twinfangs(fight, actor_map, players, raw):
    debuffs, casts, damage, buffs, deaths = (
        raw["debuffs"], raw["casts"], raw["damage"], raw["friendlyBuffs"], raw["deaths"],
    )
    venom_events = [event for event in debuffs if int(ability_id(event) or 0) == 1290336]
    histories = []
    for player_id in players:
        current, peak, rows = 0, 0, []
        for event in sorted((item for item in venom_events if item.get("targetID") == player_id), key=lambda item: int(item.get("timestamp") or 0)):
            kind, before = event_type(event), current
            timestamp = int(event.get("timestamp") or 0)
            raw_stack = event.get("stack")
            death_event = None
            if kind in {"applydebuff", "applydebuffstack", "refreshdebuff"}:
                current = int(raw_stack) if raw_stack is not None else max(1, current + (1 if "stack" in kind else 0))
                source_label, source_id, category = _venom_attribution(damage, casts, timestamp, player_id)
                action = "gain"
            elif kind == "removedebuffstack":
                current = int(raw_stack) if raw_stack is not None else max(0, current - 1)
                action = "remove"
                feast = any(abs(int(cast.get("timestamp") or 0) - timestamp) <= 3500 for cast in casts if int(ability_id(cast) or 0) in FEAST_IDS)
                if before > 1 and current == 0:
                    death_event = _death_near(deaths, player_id, timestamp)
                    if death_event:
                        source_id = int(death_event.get("killingAbilityGameID") or ability_id(death_event) or 0)
                        source_label = spell_name(source_id)
                        category = "death"
                        action = "death_clear"
                    elif feast:
                        source_label = spell_name(1290516)
                        source_id = 1290516
                        category = "feast"
                    else:
                        source_label = "层数异常归零"
                        source_id = None
                        category = "clear"
                elif feast:
                    source_label = spell_name(1290516)
                    source_id = 1290516
                    category = "feast"
                else:
                    source_label = "层数移除"
                    source_id = None
                    category = "remove"
            elif kind == "removedebuff":
                current, action = 0, "clear"
                feast = any(abs(int(cast.get("timestamp") or 0) - timestamp) <= 3500 for cast in casts if int(ability_id(cast) or 0) in FEAST_IDS)
                if before > 0:
                    death_event = _death_near(deaths, player_id, timestamp)
                    if death_event:
                        source_id = int(death_event.get("killingAbilityGameID") or ability_id(death_event) or 0)
                        source_label = spell_name(source_id)
                        category = "death"
                        action = "death_clear"
                    elif feast and before > 1:
                        source_label = spell_name(1290516)
                        source_id = 1290516
                        category = "feast"
                    elif feast:
                        source_label = spell_name(1290516)
                        source_id = 1290516
                        category = "feast"
                    else:
                        source_label = "光环完全移除"
                        source_id = None
                        category = "clear"
                elif feast:
                    source_label = spell_name(1290516)
                    source_id = 1290516
                    category = "feast"
                else:
                    source_label = "光环完全移除"
                    source_id = None
                    category = "clear"
            else:
                continue
            peak = max(peak, current)
            row = {
                "timeMs": timestamp - fight["startTime"], "time": fmt_ms(timestamp - fight["startTime"]),
                "eventType": kind, "action": action, "fromStack": before, "toStack": current,
                "delta": current - before, "source": source_label, "sourceID": source_id, "category": category,
            }
            if death_event:
                row["deathAtMs"] = int(death_event.get("timestamp") or 0) - fight["startTime"]
                row["deathAbilityID"] = int(death_event.get("killingAbilityGameID") or ability_id(death_event) or 0)
            rows.append(row)
        if rows:
            histories.append({**player_ref(players, actor_map, player_id), "peakStack": peak,
                              "gainCount": sum(row["delta"] for row in rows if row["delta"] > 0),
                              "removedCount": -sum(row["delta"] for row in rows if row["delta"] < 0), "events": rows})

    feast_casts = [
        min(group, key=lambda event: int(event.get("timestamp") or 0))
        for group in group_nearby(
            [event for event in casts if int(ability_id(event) or 0) in FEAST_IDS and event_type(event) == "cast"],
            window_ms=1000,
        )
    ]
    feast_checks = []
    for index, cast in enumerate(feast_casts, start=1):
        timestamp = int(cast["timestamp"])
        present = sorted(
            player_id for player_id in players
            if _venom_stack_at(venom_events, player_id, timestamp - 1) > 0
        )
        consumed = sorted({
            event.get("targetID") for event in venom_events
            if event.get("targetID") in present
            and timestamp - 500 <= int(event.get("timestamp") or 0) <= timestamp + 5000
            and event_type(event) in {"removedebuffstack", "removedebuff"}
        })
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
                 "bossName": config["name"], "analyzedReports": report_id_list, "mechanicVersion": f"{boss_key}-progression-2026-08-27",
                 "tabDefinitions": [{"key": key, "label": label} for key, label in config["tabs"]],
                 "arenaImage": config["arena"], "features": {"survival": True, "fieldReplay": boss_key == "sszorak"},
                 "evidenceLimits": {"positions": "仅使用 WCL 实际坐标样本；超过采样窗只展示，不归责。"}},
        "data": {"page1_wipeAnalysis": rendered, "page2_avoidableBoard": {"avoidable": avoidable_rows}},
    }


def analyze_boss(boss_key, report_ids, output_path=None, catalog_entry=None, options=None):
    return write_json_result(build_aggregated_json(boss_key, report_ids, options), output_path, catalog_entry=catalog_entry)
