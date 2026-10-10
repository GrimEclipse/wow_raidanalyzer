"""Evidence-first analyzer for Venomancer Vashnik."""

from __future__ import annotations

from copy import deepcopy
from math import hypot
from analyzer_core.config import resolve_analysis_options
from analyzer_core.event_evidence import actor_position, build_event_scene

CONFIG_SCHEMA = [{'key': 'avoidableReviewEnabled', 'type': 'boolean', 'label': '可规避伤害复盘', 'description': '', 'default': True}, {'key': 'infectionReviewEnabled', 'type': 'boolean', 'label': '适应性感染与接圈', 'description': '', 'default': True}]
CONFIG_SCHEMA.append({'key': 'infectionBatchWindowSeconds', 'type': 'number', 'label': '感染光环记录合并窗口', 'description': '日志没有感染施法时，将邻近光环首次应用汇成记录批次；不视为已确认机制轮次。', 'unit': '秒', 'min': 0.25, 'max': 5, 'step': 0.25, 'default': 1.5, 'visibleWhen': {'field': 'infectionReviewEnabled', 'equals': True}})
CONFIG_SCHEMA.append({'key': 'waveReviewEnabled', 'type': 'boolean', 'label': '泡沫与波浪方向参考', 'default': True})
CONFIG_SCHEMA.append({'key': 'fullReplayEnabled', 'type': 'boolean', 'label': '场地推演', 'description': '显示整场所有玩家与有位置记录的场地单位；关闭后不读取整场回放数据。', 'default': True})

# NSRT's removed WavesLine display used the minimap compass to draw an
# orthogonal world-axis reference, not a recorded player-facing or lock time.
WAVE_REFERENCE_SOURCE = 'https://github.com/Reloe/NorthernSkyRaidTools/blob/afac04613349580b162c3515bd9fe2d23f469cbd/NorthernSkyRaidTools/EncounterAlerts/MidnightS2/VashnikTheMalignant.lua'
FROTH_MARKER_ID = 1281913  # Actual timed aura in Avalon Fight 54; 1281910 is instantaneous.
IMBIBE_ID = 1284663
TOTEM_GAME_ID = 269430
MALIGNANCE_ID = 1304459
WAVE_WIDTH_YARDS = 5
# Simulation timing, not measured projectile speed. Evidence timestamps remain real.
WAVE_SIMULATION = {"widthYards": WAVE_WIDTH_YARDS, "speedYardsPerSecond": 20,
                   "rangeYards": 80, "resultWindowMs": 8000, "simulatedTiming": True}
PILLAR_RADIUS_YARDS = 3
MARKER_NAMES = {1: "星星", 2: "圆圈", 3: "菱形", 4: "三角", 5: "月亮", 6: "方块", 7: "十字", 8: "骷髅"}
# Six unobscured ground markers in the user's Fight 54 screenshot. Never reused
# for another report. Scale is provisional; this is review evidence, not blame.
REFERENCE_REPORT = "ZFDWvrfqd6ygMKY2"
REFERENCE_PIXELS = {2: (352, 331), 3: (423, 38), 4: (404, 378), 5: (510, 472), 6: (185, 439), 7: (303, 290)}
ARENA_PROFILE = {
    "source": "user-landmark-estimate", "verified": False,
    "image": "/assets/raids/venomous_abyss/03-vashnik.png",
    "imageWidth": 1997, "imageHeight": 1118,
    "imageTransform": "translate(141 1049) scale(.645 .6) rotate(-90)",
    "worldAnchor": {"x": 30760, "y": 47522},
    "imageAnchor": {"x": 501 + 7862/13431*(423-190) - 11042/13431*(38-174),
                    "y": 413 + 8411/13431*(423-190) + 5218/13431*(38-174)},
    # Closest equal-scale rotation/reflection to the landmark estimate. A general
    # affine transform sheared the two perpendicular world axes into oblique lines.
    "matrix": [(7862+5218)/26862*.0618, (11042+8411)/26862*.0618,
               (11042+8411)/26862*.0618, -(7862+5218)/26862*.0618],
    "fullBounds": {"x": 0, "y": 0, "w": 957, "h": 867},
    "combatBounds": {"x": 151, "y": 468, "w": 705, "h": 370},
}


def _load_marker_evidence(client, report_id, fight):
    try:
        return {"worldMarkerEvents": client.world_marker_events(report_id, int(fight["endTime"]))}
    except Exception:
        return {"worldMarkerEvents": [], "worldMarkerWarning": "光柱事件暂不可用；无法完成到位检查。"}


def _pillars_at(raw, fight, time_ms):
    reference = raw.get("reportID") == REFERENCE_REPORT and int(fight.get("id") or 0) == 54
    active = {}
    if reference:
        for icon, (px, py) in REFERENCE_PIXELS.items():
            active[icon] = {"icon": icon, "name": MARKER_NAMES[icon],
                            "x": 30760 + (px - 423) / .0618,
                            "y": 47522 - (py - 38) / .0618,
                            "source": "screenshot-estimate", "estimated": True}
    timestamp = int(fight["startTime"]) + time_ms
    for event in sorted(raw.get("worldMarkerEvents") or [], key=lambda row: row.get("timestamp", 0)):
        if event.get("timestamp", 0) > timestamp:
            break
        icon = event.get("icon")
        if icon not in MARKER_NAMES:
            continue
        if event.get("type") == "worldmarkerremoved":
            # Screenshot is a snapshot of this fight, not an earlier room.
            if not reference or event.get("timestamp", 0) >= fight["startTime"] or active.get(icon, {}).get("source") == "wcl-event":
                active.pop(icon, None)
        elif event.get("type") == "worldmarkerplaced":
            x, y = event.get("x"), event.get("y")
            # This room's coordinate envelope is independent of Boss tanking.
            if x is not None and y is not None and 16000 <= x <= 45000 and 32000 <= y <= 57000:
                active[icon] = {"icon": icon, "name": MARKER_NAMES[icon], "x": x, "y": y,
                                "source": "wcl-event", "estimated": False,
                                "placedTimeMs": event["timestamp"] - fight["startTime"]}
            elif not reference or event.get("timestamp", 0) >= fight["startTime"]:
                active.pop(icon, None)
    return list(active.values())


def _distinct_pillar_matches(rows, pillars):
    """Keep all maximum-cardinality assignments so collisions blame nobody arbitrarily."""
    candidates = [[p["icon"] for p in pillars if hypot(row["position"]["x"] - p["x"], row["position"]["y"] - p["y"]) <= PILLAR_RADIUS_YARDS * 100] if row.get("position") else [] for row in rows]
    states = [{0}]
    for icons in candidates:
        next_states = set(states[-1])
        for mask in states[-1]:
            next_states.update(mask | (1 << icon) for icon in icons if not mask & (1 << icon))
        states.append(next_states)
    best = max(bin(mask).count("1") for mask in states[-1])
    optimal = {mask for mask in states[-1] if bin(mask).count("1") == best}
    possibilities = [set() for _ in rows]
    for index in range(len(rows)-1, -1, -1):
        previous = set()
        for mask in optimal:
            if mask in states[index]:
                possibilities[index].add(None)
                previous.add(mask)
            for icon in candidates[index]:
                bit = 1 << icon
                if mask & bit and mask ^ bit in states[index]:
                    possibilities[index].add(icon)
                    previous.add(mask ^ bit)
        optimal = previous
    return candidates, possibilities, best


def build_pillar_review(review, scene, fight, raw):
    imbibes = sorted({int(row["timestamp"]) - int(fight["startTime"]) for row in _completed_casts(raw.get("casts") or [], IMBIBE_ID)})
    groups = []
    for record in sorted(review["records"], key=lambda row: row.get("applicationTimeMs") if row.get("applicationTimeMs") is not None else row["timeMs"]):
        applied = record.get("applicationTimeMs")
        if applied is None:
            continue
        if not groups or applied - groups[-1]["applicationTimeMs"] > 1500:
            groups.append({"index": len(groups) + 1, "applicationTimeMs": applied, "players": []})
        groups[-1]["players"].append(record)
    cycles, round_rows, scene_by_id = {}, [], {row["id"]: row for row in scene["events"]}
    for group in groups:
        preceding = [t for t in imbibes if t <= group["applicationTimeMs"]]
        imbibe = preceding[-1] if preceding else None
        cycles[imbibe] = cycles.get(imbibe, 0) + 1
        checked = imbibe is not None and cycles[imbibe] == 1
        release = max(row["timeMs"] for row in group["players"] if row["ending"] != "death") if any(row["ending"] != "death" for row in group["players"]) else group["applicationTimeMs"]
        pillars = _pillars_at(raw, fight, release)
        eligible = [{**row, "position": row.get("position") if row["referenceAvailable"] and abs((row.get("position") or {}).get("sampleOffsetMs", 0)) <= 250 else None} for row in group["players"]]
        candidates, matches, occupied = _distinct_pillar_matches(eligible, pillars)
        # Five recorded placements do not prove that an unrecorded sixth pillar
        # was absent. A full snapshot or all eight icons is needed for absence.
        complete = bool(raw.get("worldMarkersComplete") or len(pillars) == 8) and all(not row["estimated"] for row in pillars)
        for i, row in enumerate(group["players"]):
            position = row.get("position")
            nearest = min(pillars, key=lambda p: hypot(position["x"]-p["x"], position["y"]-p["y"])) if position and pillars else None
            distance = round(hypot(position["x"]-nearest["x"], position["y"]-nearest["y"])/100, 2) if nearest else None
            valid = row["referenceAvailable"] and abs((position or {}).get("sampleOffsetMs", 0)) <= 250
            outcome = "首波方向参考" if imbibe is None else "第二批补救清场"
            if checked:
                if not valid:
                    outcome = "死亡提前移除" if row["ending"] == "death" else "缺少及时坐标"
                elif occupied == 5 and candidates[i] and all(not p["estimated"] for p in pillars if p["icon"] in candidates[i]):
                    outcome = "已到不同光柱"
                elif not complete:
                    outcome = "光柱证据不足" if not pillars else ("接近参考光柱" if nearest["estimated"] else "接近已记录光柱") if candidates[i] else "偏离已知光柱 · 待复核"
                elif not candidates[i]:
                    outcome = "未到光柱"
                elif None in matches[i]:
                    outcome = "重复占位 · 待复核"
                else:
                    outcome = "已到不同光柱"
            row.update(roundIndex=group["index"], cycleIndex=imbibes.index(imbibe)+1 if imbibe is not None else 0,
                       waveInCycle=cycles[imbibe], checked=checked, pillarOutcome=outcome,
                       nearestPillar=nearest, distanceYards=distance, candidatePillars=candidates[i],
                       problem=checked and complete and valid and outcome in {"未到光柱", "重复占位 · 待复核"})
            event = scene_by_id.get(row.get("eventID"))
            if event:
                event.update(waveRoundIndex=group["index"], group=f"点名 #{group['index']} · {'首波' if imbibe is None else '痛饮 '+str(row['cycleIndex'])+' / 点名 '+str(cycles[imbibe])}",
                             outcome=outcome, problem=row["problem"], layer="光柱到位" if checked else "波浪方向参考",
                             detail=f"任选 5 个不同光柱；参考半径 {PILLAR_RADIUS_YARDS} 码。" + (f" 最近{nearest['name']}：{distance} 码。" if nearest else "") + ("截图估算仅供复核，未计为确定失误。" if not complete else ""))
        round_rows.append({**group, "timeMs": release, "time": fmt_ms(release), "imbibeTimeMs": imbibe,
                           "cycleIndex": imbibes.index(imbibe)+1 if imbibe is not None else 0,
                           "waveInCycle": cycles[imbibe], "checked": checked,
                           "pillars": pillars, "markerEvidenceComplete": complete,
                           "distinctOccupied": occupied, "problemPlayers": [r["player"] for r in group["players"] if r["problem"]],
                           "reviewPlayers": [r["player"] for r in group["players"] if checked and r["pillarOutcome"] not in {"已到不同光柱", "接近参考光柱", "接近已记录光柱"}]})
    review.update(rounds=round_rows, imbibes=[{"index": i+1, "timeMs": t, "time": fmt_ms(t)} for i, t in enumerate(imbibes)],
                  pillarRadiusYards=PILLAR_RADIUS_YARDS,
                  pillarRule="痛饮后第一批点名：任选五个不同光柱；第二批检查补救清场，首波仅查看方向。",
                  markerNote=raw.get("worldMarkerWarning") or "光柱优先读取本报告开战前与战斗内的放置/移除记录。API 未返回的初始光柱不代表场上没有光柱。参考场 Fight 54 的六个可见光柱另附截图估算；遮挡光柱未补猜。")
    scene["pillarRounds"] = round_rows
    scene["arenaProjection"] = deepcopy(ARENA_PROFILE)
    return review


def build_totem_replay(scene, fight, raw):
    """Instance-local lifetimes; never infer death or location from a missing cast."""
    start, end = int(fight["startTime"]), int(fight["endTime"])
    actor_ids = {int(actor) for actor, game in (raw.get("trackedActorGameIDByActorID") or {}).items()
                 if int(game) == TOTEM_GAME_ID}
    units, seen = {}, set()
    for event in sorted(raw.get("trackedActorEvents") or [], key=lambda e: e.get("timestamp", 0)):
        timestamp = int(event.get("timestamp") or 0)
        if not start <= timestamp <= end:
            continue
        kind = event_type(event)
        side = "target" if kind in {"summon", "death", "destroy"} else "source"
        actor = event.get(side + "ID")
        if actor not in actor_ids:
            continue
        instance = int(event.get(side + "Instance") or 0)
        key = f"{actor}:{instance}"
        unit = units.setdefault(key, {"key": key, "actorID": actor, "instance": instance,
                    "name": f"恶念图腾 {key}", "spawnTimeMs": None, "firstSeenTimeMs": timestamp-start,
                    "deathTimeMs": None, "despawnTimeMs": None, "castStarts": [], "castCompletions": [], "positions": []})
        t, point = timestamp-start, actor_position(event, side)
        if point and not any(p["timeMs"] == t and p["x"] == point["x"] and p["y"] == point["y"] for p in unit["positions"]):
            unit["positions"].append({**point, "timeMs": t})
        signature = (key, kind, t, ability_id(event))
        if signature in seen:
            continue
        seen.add(signature)
        if kind == "summon":
            unit["spawnTimeMs"] = t if unit["spawnTimeMs"] is None else min(t, unit["spawnTimeMs"])
        elif kind == "death":
            unit["deathTimeMs"] = t
        elif kind == "destroy":
            unit["despawnTimeMs"] = t
        elif ability_id(event) == MALIGNANCE_ID and kind in {"begincast", "cast"}:
            unit["castStarts" if kind == "begincast" else "castCompletions"].append(t)
        else:
            continue
        label = {"summon": "图腾召唤", "death": "图腾死亡", "destroy": "图腾消失",
                 "begincast": "恶念开始读条", "cast": "恶念完成施法"}[kind]
        scene["events"].append({"id": f"vashnik-totem:{key}:{kind}:{t}", "timeMs": t,
             "layer": "恶念图腾", "label": label, "actor": unit["name"], "actorID": actor,
             "totemKey": key, "role": "enemy", "kind": kind, "group": "恶念图腾",
             "spellID": ability_id(event), "sourceID": event.get("sourceID"), "targetID": event.get("targetID"),
             "amount": 0, "outcome": label, "problem": False,
             "points": [{"position": point, "label": unit["name"], "color": "#b8f36b"}] if point else [],
             "evidence": f"WCL {kind} · 实例 {key}" + ("；事件坐标" if point else "；该事件未附坐标")})
    # Position owners can differ from cast sources; inspect both sides of the
    # complete position stream without borrowing another instance's location.
    for event in raw.get("replayEvents") or []:
        for side in ("source", "target"):
            actor = event.get(side + "ID")
            key = f"{actor}:{int(event.get(side + 'Instance') or 0)}"
            unit = units.get(key)
            point = actor_position(event, side) if unit else None
            if point:
                unit["positions"].append({**point, "timeMs": int(event["timestamp"])-start})
    rows = list(units.values())
    for unit in rows:
        unique = {(p["timeMs"], p["x"], p["y"]): p for p in unit["positions"]}
        unit["positions"] = sorted(unique.values(), key=lambda p: p["timeMs"])
    def alive(u, t):
        born = u["spawnTimeMs"] if u["spawnTimeMs"] is not None else u["firstSeenTimeMs"]
        gone = u["deathTimeMs"] if u["deathTimeMs"] is not None else u["despawnTimeMs"]
        return born <= t and (gone is None or gone > t)
    rounds = scene.get("pillarRounds") or []
    for i, round_row in enumerate(rounds):
        release = min((p.get("timeMs", round_row["timeMs"]) for p in round_row.get("players", []) if p.get("ending") != "death"), default=round_row["timeMs"])
        next_wave = rounds[i+1]["applicationTimeMs"] if i+1 < len(rounds) else end-start
        result_time = min(round_row["timeMs"] + WAVE_SIMULATION["resultWindowMs"], next_wave, end-start)
        imbibe = round_row.get("imbibeTimeMs")
        # Count the entire named batch, including clearance before normal expiry
        # when some marked players die early. Legacy snapshots have no roster.
        observation_start = round_row["applicationTimeMs"] if round_row.get("players") else release
        before = [u for u in rows if alive(u, observation_start-1) and
                  (imbibe is None or (u["spawnTimeMs"] if u["spawnTimeMs"] is not None else u["firstSeenTimeMs"]) >= imbibe)]
        cleared = [u for u in before if u["deathTimeMs"] is not None and observation_start <= u["deathTimeMs"] <= result_time]
        remaining = [u for u in before if alive(u, result_time)]
        round_row["totemResult"] = {"beforeKeys": [u["key"] for u in before],
                   "clearedKeys": [u["key"] for u in cleared], "remainingKeys": [u["key"] for u in remaining],
                   "resultTimeMs": result_time, "observationStartTimeMs": observation_start,
                   "note": "死亡时间来自日志；放波后死亡不单独证明由哪名玩家的波浪命中。"}
        round_row["purpose"] = "光柱到位与清场" if round_row.get("checked") else "补救清场" if round_row.get("cycleIndex") else "首波方向参考"
        round_row["explosionReview"] = []
    explosions = []
    projection = scene.get("arenaProjection") or ARENA_PROFILE
    bounds = projection["combatBounds"]
    for unit in rows:
        for timestamp in unit["castCompletions"]:
            born = unit["spawnTimeMs"] if unit["spawnTimeMs"] is not None else unit["firstSeenTimeMs"]
            cycles = [r for r in rounds if r.get("imbibeTimeMs") is not None and r["imbibeTimeMs"] <= born]
            cycle = max(cycles, key=lambda r: r["imbibeTimeMs"]).get("cycleIndex") if cycles else None
            preceding = [r for r in rounds if r["applicationTimeMs"] <= timestamp and (cycle is None or r.get("cycleIndex") == cycle)]
            latest = preceding[-1] if preceding else None
            related = [r for r in rounds if latest and r.get("cycleIndex", 0) == latest.get("cycleIndex", 0) and r["applicationTimeMs"] <= timestamp]
            point = next((p for p in reversed(unit["positions"]) if p["timeMs"] <= timestamp), None) or next(iter(unit["positions"]), None)
            region = "坐标不足，区域待核对"
            if point:
                dx, dy = point["x"]-projection["worldAnchor"]["x"], point["y"]-projection["worldAnchor"]["y"]
                a,b,c,d = projection["matrix"]
                x = (projection["imageAnchor"]["x"]+a*dx+b*dy-bounds["x"])/bounds["w"]
                y = (projection["imageAnchor"]["y"]+c*dx+d*dy-bounds["y"])/bounds["h"]
                region = ("上" if y < 1/3 else "下" if y > 2/3 else "中") + ("左" if x < 1/3 else "右" if x > 2/3 else "部") + "区域（场地对齐估算）"
            review = {"timeMs": timestamp, "time": fmt_ms(timestamp), "totemKey": unit["key"],
                      "cycleIndex": latest.get("cycleIndex", 0) if latest else None,
                      "waveRoundIndices": [r.get("index", i+1) for i,r in enumerate(related)],
                      "players": list(dict.fromkeys(p["player"] for r in related for p in r.get("players", []))),
                      "unclearedRegion": region, "position": point,
                      "note": "恶念完成施法确认本周期存在未清图腾；点名玩家供共同复核，不自动归责个人。"}
            explosions.append(review)
            for round_row in related:
                round_row["explosionReview"].append(review)
                for player in round_row.get("players", []):
                    player["clearanceReview"] = True
            for event in scene["events"]:
                if event.get("totemKey") == unit["key"] and event["timeMs"] == timestamp and event["kind"] == "cast":
                    event.update(problem=True, outcome="恶念爆炸 · 清场复核", detail=region)
    scene["totemReplay"] = {"units": rows, "explosions": explosions, "simulation": dict(WAVE_SIMULATION),
          "summary": {"spawned": sum(u["spawnTimeMs"] is not None for u in rows),
                      "deaths": sum(u["deathTimeMs"] is not None for u in rows),
                      "positioned": sum(bool(u["positions"]) for u in rows),
                      "completedCasts": sum(len(u["castCompletions"]) for u in rows)},
          "positionNote": "图腾按 actor ID + instance 区分。坐标只使用本实例记录；定点图腾的后续坐标可用于回看先前位置，并标注采样时间。没有坐标的实例仅展示状态。"}
    scene["events"].sort(key=lambda row: row["timeMs"])

from analyzer_core.court_rules import validate_court_profile
from boss_plugins.common import write_json_result
from boss_plugins.venomous_abyss.runtime import build_aggregated_json as _build
from boss_plugins.venomous_abyss.shared import (
    ability_id,
    avoidable_board as _avoidable_board,
    completed_casts as _completed_casts,
    event_type,
    events_between as _events_between,
    fmt_ms,
    load_confirmed_spell_names,
    nightly_detail,
    nightly_player_totals,
    player_ref,
    spell_name,
)

GUIDE_SPELLS = load_confirmed_spell_names()

BOSS_CONFIG = {
    "key": "vashnik",
    "encounterIDs": {3455, 53455},
    "name": "万毒邪祟者瓦什尼克",
    "arena": "assets/raids/venomous_abyss/03-vashnik.png",
    "spellNames": GUIDE_SPELLS,
    "tabs": [
        ["survival", "全场存活情况"],
        ["replay", "场地回放"],
        ["avoidable", "可规避机制"],
        ["infection", "适应性感染"],
        ["waves", "光柱与波浪"],
        ["explore", "机制工作台"],
    ],
    "mechanicVersion": "vashnik-wave-totem-replay-2026-10-08",
    "features": {"survival": True, "fieldReplay": False},
    "fetchCastResources": True,
    "fetchFriendlyCastResources": True,
    "fetchConcurrency": 4,
    "fetchKeys": {"casts", "friendlyCasts", "damage", "debuffs", "deaths", "combatants"},
    "extraPayloadLoader": _load_marker_evidence,
    "trackedActorGameIDs": {TOTEM_GAME_ID},
    "trackedActorEventFilters": [f"source.id = {TOTEM_GAME_ID} or target.id = {TOTEM_GAME_ID}"],
}

COURT_PROFILE = {
    "bossKey": "vashnik",
    "phaseModel": "fixed_timeline",
    "phaseRule": "只按起战后的固定事件轴和 Imbibe/Infusion Aura 切段；不得用血量提前结束阶段。",
    "rules": [
        {
            "key": "plague_wave_assignment", "label": "瘟疫泡沫波浪未命中指定目标", "mode": "assignment",
            "spellIDs": [1281908, 1281910, 1282078, 1295796, 1295798],
            "assignmentKey": "plagueWaveTargets",
            "requiredEvidence": ["Plague Froth remove timestamp", "player position near remove", "wave direction/facing", "assigned target position", "Plague Wave hit set"],
            "countOption": "plagueWaveAssignmentCountEnabled", "defaultCountEnabled": False, "severityUnits": 1,
        },
        {
            "key": "malignant_totem_malignance", "label": "恶念图腾处理复核", "mode": "review",
            "spellIDs": [1304459, 1309774, 1295798],
            "requiredEvidence": ["totem spawn", "wave intersection", "Malignance cast"],
            "countOption": "malignantTotemCountEnabled", "defaultCountEnabled": False, "severityUnits": 1,
        },
        {
            "key": "avoidable_plague_wave_hit", "label": "误吃瘟疫波浪", "mode": "review",
            "spellIDs": [1295798], "requiredEvidence": ["wave source", "wave direction", "damage target"],
            "countOption": "avoidablePlagueWaveCountEnabled", "defaultCountEnabled": False, "severityUnits": 1,
        },
    ],
}
validate_court_profile(COURT_PROFILE)


def build_wave_review(scene, players):
    """Pair actual timed auras, retaining missing/death endings as evidence."""
    active, records = {}, []
    deaths = scene.get("deaths") or []
    for event in scene["events"]:
        if event["spellID"] != FROTH_MARKER_ID or event["actorID"] not in players:
            continue
        actor_id = event["actorID"]
        if event["kind"] == "applydebuff":
            active[actor_id] = event
            continue
        if event["kind"] != "removedebuff":
            continue
        applied = active.pop(actor_id, None)
        duration = event["timeMs"] - applied["timeMs"] if applied else None
        died = any(row.get("actorID") == actor_id and abs(row["timeMs"] - event["timeMs"]) <= 250 for row in deaths)
        point = next((row["position"] for row in event["points"] if row.get("position")), None)
        reference_available = point is not None and duration is not None and duration > 0 and not died
        record = {"index": len(records) + 1, "playerID": actor_id, "player": event["actor"],
                  "timeMs": event["timeMs"], "time": fmt_ms(event["timeMs"]), "durationMs": duration,
                  "icon": players[actor_id].get("icon"), "classColor": players[actor_id].get("classColor"),
                  "position": point, "referenceAvailable": reference_available,
                  "ending": "death" if died else "removed", "lockTimeMs": None,
                  "applicationTimeMs": applied["timeMs"] if applied else None, "eventID": event["id"]}
        records.append(record)
        event.update(layer="波浪方向参考", label="泡沫移除位置", group=f"泡沫记录 #{record['index']}",
                     outcome="死亡时移除" if died else "光环移除",
                     detail="世界坐标双轴参考；不代表实测波浪轨迹或已确认的锁定时刻。")
        if reference_available:
            event["guides"] = [{"origin": point, "axis": axis, "label": "世界坐标方向参考"}
                               for axis in ({"x": 1, "y": 0}, {"x": 0, "y": 1})]
    return {"records": records, "referenceSource": WAVE_REFERENCE_SOURCE,
            "referenceRule": "按已确认机制展示固定垂直 X；世界轴方向参照 NSRT 罗盘双轴代码。",
            "lockRule": "源码没有实际锁定时刻；泡沫移除时间仅作为位置复核锚点。"}


def analyze_vashnik(fight, actor_map, players, raw):
    options = resolve_analysis_options(CONFIG_SCHEMA, raw.get("analysisOptions") or {})
    avoidable = _avoidable_board(fight, actor_map, players, raw["damage"], raw["deaths"], {
        1295798: spell_name(1295798),
        1286737: spell_name(1286737),
    }) if options["avoidableReviewEnabled"] else []
    avoidable_summary = [
        {"spellID": spell_id, "spellName": spell_name(spell_id),
         "hitCount": sum(row["hitCount"] for row in avoidable if row["spellID"] == spell_id),
         "playerCount": sum(1 for row in avoidable if row["spellID"] == spell_id)}
        for spell_id in (1295798, 1286737)
    ]
    infection_casts = sorted(_completed_casts(raw["casts"], 1282114), key=lambda event: event["timestamp"])
    group_basis = "cast"
    if not infection_casts and options["infectionReviewEnabled"]:
        group_basis = "observed-aura-batch"
        applies = sorted((event for event in raw["debuffs"] if int(ability_id(event) or 0) in {1294994, 1295173, 1295224}
                          and event_type(event) == "applydebuff" and event.get("targetID") in players), key=lambda event: int(event["timestamp"]))
        for event in applies:
            timestamp = int(event["timestamp"])
            if not infection_casts or timestamp - int(infection_casts[-1]["timestamp"]) > options["infectionBatchWindowSeconds"] * 1000:
                infection_casts.append({"timestamp": timestamp})
    rounds = []
    for index, cast in enumerate(infection_casts if options["infectionReviewEnabled"] else [], start=1):
        start = int(cast["timestamp"])
        end = int(infection_casts[index]["timestamp"]) if index < len(infection_casts) else int(fight["endTime"])
        debuff_applies = [event for event in raw["debuffs"] if int(ability_id(event) or 0) in {1294994, 1295173, 1295224}
                          and event_type(event) == "applydebuff" and start <= int(event["timestamp"]) < end]
        soaker_hits = _events_between(raw["damage"], start, end, {1282117})
        soakers = sorted({event.get("targetID") for event in soaker_hits if event.get("targetID") in players})
        rounds.append({
            "index": index,
            "groupBasis": group_basis,
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
    streams = {}
    if options["avoidableReviewEnabled"]:
        streams["damage"] = {1295798: "瘟疫波浪命中", 1286737: "场地伤害"}
    if options["infectionReviewEnabled"]:
        streams.setdefault("damage", {})[1282117] = "感染接圈"
        streams["debuffs"] = {1294994: "适应性感染", 1295173: "适应性感染", 1295224: "适应性感染"}
        streams["casts"] = {1282114: "感染施法", 1304459: "恶念施法", 1309774: "恶念图腾", 1282509: "恶性催化", 1282516: "恶性催化", 1284663: "汲取阶段"}
    if options["waveReviewEnabled"]:
        streams.setdefault("casts", {})[IMBIBE_ID] = "痛饮"
        streams.setdefault("debuffs", {}).update({1281908: "泡沫触发记录", 1281910: "泡沫触发记录", FROTH_MARKER_ID: "瘟疫泡沫标记", 1282078: "泡沫触发记录"})
        streams.setdefault("damage", {})[1295798] = "瘟疫波浪命中"
    scene = build_event_scene(fight, actor_map, players, raw, streams, key="vashnik",
                             arena_image=BOSS_CONFIG["arena"],
                             note="感染、接圈、痛饮、推波与图腾共用事件轴。选择点名批次，可播放垂直 X 推波或直接查看本批结果；波速和射程为模拟参数。图腾状态按实例读取，缺少坐标时只列状态。场地与截图光柱近似对齐，到位检查使用世界坐标。")
    wave_review = build_pillar_review(build_wave_review(scene, players), scene, fight, raw) if options["waveReviewEnabled"] else {"records": [], "rounds": []}
    if options["waveReviewEnabled"]:
        build_totem_replay(scene, fight, raw)
    return {"avoidable": {"players": avoidable, "summary": avoidable_summary}, "adaptiveInfection": {"rounds": rounds, "groupBasis": group_basis}, "plagueWaves": wave_review, "eventScene": scene}

analyze_mechanics = analyze_vashnik


def _mechanic_overview(rendered):
    wave_hits = []
    floor_hits = []
    explosions = []
    for pull in rendered:
        mechanics = pull.get(BOSS_CONFIG["key"]) or {}
        for event in (mechanics.get("eventScene") or {}).get("totemReplay", {}).get("explosions", []):
            explosions.append(nightly_detail(pull, event["time"], "恶念爆炸 · " + event["unclearedRegion"],
                                             spellID=MALIGNANCE_ID, waveRoundIndices=event["waveRoundIndices"],
                                             reviewPlayers=event["players"], totemKey=event["totemKey"]))
        for player_row in (mechanics.get("avoidable") or {}).get("players") or []:
            spell_id = int(player_row.get("spellID") or 0)
            if spell_id == 1295798:
                target = wave_hits
            elif spell_id == 1286737:
                target = floor_hits
            else:
                continue
            for event in player_row.get("events") or []:
                target.append(nightly_detail(
                    pull, event.get("time"),
                    f"{player_row.get('player') or '未知玩家'} 命中{player_row.get('spellName') or spell_name(player_row.get('spellID'))}",
                    player=player_row.get("player"), classColor=player_row.get("classColor"),
                    spellID=player_row.get("spellID"),
                ))
    return {
        "title": "整夜机制统计",
        "subtitle": "单场判定保持不变；这里按所有 Pull 汇总可验证命中。",
        "metrics": [
            {"key": "malignanceExplosions", "label": "恶念图腾漏清", "value": len(explosions), "unit": "次",
             "tone": "danger", "description": "按恶念完成施法统计，关联本周期点名玩家供共同复核。",
             "players": [], "events": explosions},
            {
                "key": "plagueWaveHits", "label": "命中瘟疫泡沫波浪", "value": len(wave_hits), "unit": "次",
                "tone": "danger", "description": "瘟疫波浪 1295798 对玩家造成伤害的总人次。",
                "players": nightly_player_totals(wave_hits), "events": wave_hits,
            },
            {
                "key": "floorCircleHits", "label": "命中地板黑圈", "value": len(floor_hits), "unit": "次",
                "tone": "warning", "description": "地板黑圈 1286737 对玩家造成伤害的总人次。",
                "players": nightly_player_totals(floor_hits), "events": floor_hits,
            },
        ],
    }


def build_aggregated_json(report_ids, options=None):
    options = resolve_analysis_options(CONFIG_SCHEMA, options or {})
    config = deepcopy(BOSS_CONFIG)
    config["fetchCombatReplay"] = options["fullReplayEnabled"]
    if not options["waveReviewEnabled"]:
        config.pop("extraPayloadLoader", None)
        config["fetchFriendlyCastResources"] = False
        config["trackedActorGameIDs"] = set()
        config["trackedActorEventFilters"] = []
    if not any(options[key] for key in ("avoidableReviewEnabled", "infectionReviewEnabled", "waveReviewEnabled")):
        config["fetchKeys"] = {"friendlyCasts", "deaths", "combatants"}
        config["fetchPositionResources"] = False
        config["trackedActorGameIDs"] = set()
        config["trackedActorEventFilters"] = []
        config["trackedDamageTargetGameIDs"] = set()
        config["tabs"] = [row for row in config["tabs"] if row[0] == "survival"]
    config["skippedAnalyses"] = [field["label"] for field in CONFIG_SCHEMA if field["type"] == "boolean" and not options[field["key"]]]
    config["tabs"] = [row for row in config["tabs"] if row[0] in {"survival", "replay", "explore"} or options[{"avoidable":"avoidableReviewEnabled", "infection":"infectionReviewEnabled", "waves":"waveReviewEnabled"}[row[0]]]]
    result = _build(config, analyze_mechanics, report_ids, options)
    result["data"]["mechanicOverview"] = _mechanic_overview(
        result.get("data", {}).get("page1_wipeAnalysis") or []
    )
    if not options["avoidableReviewEnabled"]:
        result["data"]["mechanicOverview"] = {"title": "部分机制未分析", "subtitle": "、".join(config["skippedAnalyses"]), "metrics": []}
    return result


def analyze(report_ids, output_path=None, catalog_entry=None, options=None, progress_callback=None):
    return write_json_result(
        build_aggregated_json(report_ids, options), output_path, catalog_entry=catalog_entry
    )
