"""Evidence-first analyzer for Nymrissa Wavecaller.

The encounter is intentionally kept compact: the module records the few
repeatable mechanics that are useful after a pull without inventing blame when
WCL does not expose enough position or orb-lifecycle evidence.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from analyzer_core.analysis_scope import filter_fights
from analyzer_core.event_evidence import build_event_scene
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
    "evidenceRule": "光环应用与层数变化用于记录实际接触；持续伤害次数不等于踩球数量。",
}
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
    1284015: "诱惑水泡",
    1263301: "鱼人波次",
    1258673: "潮刺冲锋",
    1258668: "旋转漩涡",
    1258677: "旋转漩涡",
    1258150: "水泡破裂",
    1273091: "水雾护盾",
    1273150: "水雾护盾",
    1258894: "脉动潮汐",
    1271380: "脉动潮汐",
    1294867: "无尽潮汐",
    1295086: "无尽潮汐",
}

BOSS_CONFIG = {
    "key": "nymrissa_wavecaller",
    "name": "尼姆瑞莎·唤潮者",
    "encounterIDs": ENCOUNTER_IDS,
    "mechanicVersion": "nymrissa-fixed-orb-review-2026-10-08",
    "tabs": [
        ["survival", "死亡与战复"],
        ["rain", "深渊之雨"],
        ["frost", "冰霜与冰球"],
        ["transition", "鱼人转场"],
        ["pressure", "承伤复盘"],
        ["explore", "机制工作台"],
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
        hits = [event for event in damage if ability_id(event) == 1260843 and timestamp <= int(event.get("timestamp") or 0) < timestamp + int(options["rainWindowSeconds"] * 1000)]
        rain_rounds.append({
            "index": index,
            "timeMs": timestamp - start_time,
            "time": fmt_ms(timestamp - start_time),
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
    barrage_rounds = []
    for offset, cast in enumerate(barrage_casts):
        timestamp = int(cast.get("timestamp") or 0)
        next_timestamp = int(barrage_casts[offset + 1].get("timestamp") or end_time) if offset + 1 < len(barrage_casts) else end_time
        round_end = min(next_timestamp, timestamp + int(options["frostWindowSeconds"] * 1000))
        target_ids = {
            event.get("targetID")
            for event in debuffs
            if ability_id(event) in {1257608, 1257644, 1313393}
            and event_type(event) in {"applydebuff", "refreshdebuff"}
            and timestamp - 2_000 <= int(event.get("timestamp") or 0) <= timestamp + 8_000
            and event.get("targetID") in players
        }
        orb_hits = [
            event for event in damage
            if ability_id(event) in {1257651, 1281393, 1313448}
            and timestamp <= int(event.get("timestamp") or 0) < round_end
            and event.get("targetID") in players
        ]
        orb_stacks = {}
        for event in debuffs:
            if ability_id(event) != 1313448 or event.get("targetID") not in players or not timestamp <= int(event.get("timestamp") or 0) < round_end:
                continue
            if event_type(event) not in {"applydebuff", "applydebuffstack", "refreshdebuff"}:
                continue
            actor_id = event["targetID"]
            orb_stacks[actor_id] = max(orb_stacks.get(actor_id, 0), int(event.get("stack") or event.get("stacks") or 1))
        handler_ids = sorted({event["targetID"] for event in orb_hits} | set(orb_stacks))
        contacts = [{**player_ref(players, actor_map, actor_id),
                     "damageEventCount": sum(event["targetID"] == actor_id for event in orb_hits),
                     "maxStack": orb_stacks.get(actor_id),
                     "review": "坦克接触记录" if players[actor_id].get("role") == "tank" else "角色未知" if players[actor_id].get("role", "unknown") == "unknown" else "非坦克接触记录"}
                    for actor_id in handler_ids]
        bursts = [event for event in damage if ability_id(event) == 1313450 and timestamp <= int(event.get("timestamp") or 0) < round_end]
        barrage_rounds.append({
            "index": offset + 1,
            "timeMs": timestamp - start_time,
            "time": fmt_ms(timestamp - start_time),
            "spellID": ability_id(cast),
            "spellName": spell_name(ability_id(cast)),
            "targets": [player_ref(players, actor_map, player_id) for player_id in sorted(target_ids)],
            "orbHitCount": len(orb_hits),
            "handlers": [player_ref(players, actor_map, player_id) for player_id in handler_ids],
            "contacts": contacts,
            "tankContacts": [row for row in contacts if row["role"] == "tank"],
            "nonTankContacts": [row for row in contacts if row["role"] not in {"tank", "unknown"}],
            "orbStacks": [{**player_ref(players, actor_map, player_id), "maxStack": stack} for player_id, stack in sorted(orb_stacks.items())],
            "burstHitCount": len(bursts),
            "burstDamage": sum(int(event.get("amount") or 0) for event in bursts),
        })

    bubble_casts = completed_casts(casts, {1284015}) if options["transitionReviewEnabled"] else []
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
    hazard_hits = player_hit_board(fight, actor_map, players, damage, {1257654, 1258668, 1258677}) if options["pressureReviewEnabled"] else []
    tank_hits = player_hit_board(fight, actor_map, players, damage, {1282945, 1271458}) if options["pressureReviewEnabled"] else []
    scene = build_event_scene(fight, actor_map, players, raw, {
            "casts": {1257614: "冰霜弹幕", 1313393: "寒霜点名", 1260837: "深渊之雨", 1284015: "诱惑水泡", 1263301: "鱼人波次", 1294867: "无尽潮汐", 1295086: "无尽潮汐"},
            "debuffs": {1257608: "冰霜点名", 1257644: "冰霜点名", 1313393: "寒霜点名", 1313448: "冰球光环", 1282537: "冰球寒意", 1277386: "浸湿", 1307352: "浸湿", 1260843: "深渊之雨光环", 1260637: "水流喷射层数"},
            "damage": {1257651: "冰球命中", 1281393: "冰球命中", 1313448: "冰球命中", 1313450: "冰球爆发", 1313393: "寒霜伤害", 1257654: "残留冰霜", 1258668: "旋转漩涡", 1258677: "旋转漩涡", 1260843: "深渊之雨", 1282945: "冰刃乱舞", 1271458: "水流喷射", 1271380: "脉动潮汐"},
        }, key="nymrissa_wavecaller", arena_image="assets/raids/tidebound_grotto/01-nymrissa.jpg",
            note="冰霜点名、冰球、浸湿、深渊之雨与鱼人压力共用事件轴。冰球通常由坦克踩，无需分工；集中放与远程留中场均可，不按站位自动归责。场地坐标尚待校准。")
    for event in scene["events"]:
        if event["spellID"] == 1313448 and event["actorID"] in players:
            role = players[event["actorID"]].get("role") or "unknown"
            event["outcome"] = "冰球光环结束" if event["kind"] == "removedebuff" else "坦克接触记录" if role == "tank" else "角色未知" if role == "unknown" else "非坦克接触记录"
            event["detail"] = FROST_POLICY["evidenceRule"] + " " + FROST_POLICY["positionRule"]
    return {
        "eventScene": scene,
        "abyssalRain": {"rounds": rain_rounds, "drenched": sorted(drenched.values(), key=lambda row: (-row["maxStack"], row["player"]))},
        "frostBarrage": {"rounds": barrage_rounds, "policy": dict(FROST_POLICY)},
        "transitions": transitions,
        "hazardHits": hazard_hits,
        "tankPressure": tank_hits,
        "enrage": {"triggered": bool(enrage_casts), "timeMs": enrage_time - start_time if enrage_time else None, "time": fmt_ms(enrage_time - start_time) if enrage_time else None},
    }


analyze_mechanics = analyze_nymrissa


def fetch_payload(client, report_id, fight, options=None):
    options = resolve_analysis_options(CONFIG_SCHEMA, options or {})
    rain, frost, transition, pressure = (options[key] for key in ("rainReviewEnabled", "frostReviewEnabled", "transitionReviewEnabled", "pressureReviewEnabled"))
    cast_ids = {1294867, 1295086} | ({1260837} if rain else set()) | ({1257614, 1313393} if frost else set()) | ({1284015, 1263301} if transition else set())
    damage_ids = ({1260843} if rain else set()) | ({1257651, 1281393, 1313393, 1313448, 1313450} if frost else set()) | ({1271380} if transition else set()) | ({1257654, 1258668, 1258677, 1282945, 1271458} if pressure else set())
    debuff_ids = ({1277386, 1307352, 1260843} if rain else set()) | ({1257608, 1257644, 1282537, 1313393, 1313448} if frost else set()) | ({1260637} if pressure else set())
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
        mechanics["eventScene"]["combatReplay"] = build_replay_tracks(fight, players, actor_map, raw["replayEvents"], actor_rows=actors, spell_names=SPELL_NAMES, deaths=deaths, survival_timeline=survival["timeline"])
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
            "tabDefinitions": [{"key": key, "label": label} for key, label in BOSS_CONFIG["tabs"] if key in {"survival", "explore"} or options[{"rain": "rainReviewEnabled", "frost": "frostReviewEnabled", "transition": "transitionReviewEnabled", "pressure": "pressureReviewEnabled"}[key]]],
            "analysisConfig": options,
            "arenaImage": "assets/raids/tidebound_grotto/01-nymrissa.jpg",
            "features": {"survival": True, "fieldReplay": False},
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
