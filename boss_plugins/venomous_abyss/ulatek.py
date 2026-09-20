"""Evidence-first analyzer for Ula'tek."""

from __future__ import annotations

from copy import deepcopy
import math

from analyzer_core.config import resolve_analysis_options

CONFIG_SCHEMA = [{'key': 'wavesReviewEnabled', 'type': 'boolean', 'label': '腐蚀浪潮与带蛋', 'description': '', 'default': True}, {'key': 'rageReviewEnabled', 'type': 'boolean', 'label': '被缚之怒', 'description': '', 'default': True}, {'key': 'fangsReviewEnabled', 'type': 'boolean', 'label': '攫取毒牙', 'description': '', 'default': True}, {'key': 'criticalReviewEnabled', 'type': 'boolean', 'label': '关键流程与蛇母之怒', 'description': '', 'default': True}]

from collections import Counter, defaultdict

from analyzer_core.court_rules import validate_court_profile
from boss_plugins.combat_config import PERSONAL_DEFENSIVES, find_defensive_uses_before_death
from boss_plugins.common import write_json_result
from boss_plugins.venomous_abyss.runtime import build_aggregated_json as _build
from boss_plugins.venomous_abyss.shared import (
    ability_id,
    build_position_index,
    completed_casts,
    event_type,
    fmt_ms,
    load_confirmed_spell_names,
    load_confirmed_source_names,
    nightly_detail,
    nightly_player_totals,
    player_ref,
    position_at_interpolated,
    spell_name,
    source_name,
)


ULATEK_SPELL_NAMES = {
    1: "近战攻击",
    1286834: "死疽蒸汽",
    1286835: "死疽蒸汽",
    1286860: "被缚之怒",
    1286885: "落石",
    1287032: "剧毒撕咬",
    1287265: "幽魂盘卷",
    1287955: "虚空侵染外壳符文",
    1288879: "毒蛇之咬",
    1290409: "疫鳞卵簇",
    1290779: "恶意",
    1290991: "恶意",
    1292211: "腐蚀浪潮",
    1292403: "腐蚀浪潮",
    1295360: "恶性甲壳",
    1295905: "毒蛇之咬",
    1296301: "响尾猛击",
    1298570: "腐蚀浪潮",
    1298367: "蛇母之怒",
    1298369: "蛇母之怒",
    1298417: "岩石剧毒",
    1298418: "岩石剧毒",
    1299010: "幽魂盘卷",
    1299526: "烈毒之心",
    1300312: "厄鳞外壳",
    1300751: "毒蛇呼唤",
    1300685: "灵魂绞杀者",
    1301007: "无羁之怒",
    1301117: "攫取毒牙",
    1301122: "蛇母之怒",
    1301268: "腐臭薄膜",
    1301510: "盘绕猎物",
    1301512: "下潜",
    1302950: "蠕动孕育",
    1303410: "缺陷：虚弱",
    1303414: "石化钉刺",
    1304012: "毒蛇呼唤",
    1305650: "痛苦哀嚎",
    1305709: "绝望鞭笞",
    1305775: "恐怖咆哮",
    1305878: "易爆清除",
    1306119: "钙化尸骸",
    1306862: "孵化厄运",
    1307367: "被缚之怒",
    1311609: "凋萎静脉",
    1311611: "攫取毒牙",
    1311612: "攫取毒牙",
    1312967: "易爆清除",
    1313529: "摄入毒液",
    1313531: "酸液喷发",
    1315341: "盘绕猎物",
    1316356: "易爆清除",
    1316357: "易爆清除",
    1317955: "凋萎静脉",
    1318329: "钙化尸骸",
}

GUIDE_SPELLS = {**load_confirmed_spell_names(), **ULATEK_SPELL_NAMES}
SOURCE_NAMES = load_confirmed_source_names()
EGG_CARRY_ID = 1295360
WAVE_ID = 1292403
RAGE_ID = 1286860
HEART_ID = 1299526
ULATEK_GAME_ID = 257758
HEART_GAME_ID = 267460
DEVOURERS_SPAWN_GAME_ID = 266085
BLIGHTSCALE_SHRIEKER_GAME_ID = 273577
FANG_AURA_ID = 1311611
BLIGHT_VEIN_ID = 1311609
FANG_BATCH_WINDOW_MS = 3_000
DEVOURERS_SPAWN_SHELL_ID = 1290990
SERPENT_BITE_TARGET_ID = 1288879
INGESTED_VENOM_ID = 1313529
CALCIFIED_CORPSE_ID = 1306119
SERPENT_BITE_RADIUS_YARDS = 7
WAVE_DEATH_WINDOW_MS = 1_000
BASELINE_P3_SHRIEKERS = {1: 0, 2: 0, 3: 1, 4: 2}
HEALTHSTONE_IDS = {6262, 452930, 387636}
HEALING_POTION_IDS = {1234768, 1295247}
BURST_POTIONS = {1236616: "圣光潜力", 1236994: "鲁莽药水", 1295132: "液态光泽"}
P25_COIL_CAST_ID = 1299010
P25_COIL_DAMAGE_ID = 1287265
P25_COIL_COUNT = 6
P25_EGG_SETTLE_MS = 250

BOSS_CONFIG = {
    "key": "ulatek",
    "encounterIDs": {3492, 53492},
    "name": "乌拉特克",
    "arena": "assets/raids/venomous_abyss/08-ulatek-arena.jpg",
    "spellNames": GUIDE_SPELLS,
    "bossGameID": ULATEK_GAME_ID,
    "bossNameKeywords": {"Ula'tek", "乌拉特克"},
    "fetchPositionResources": True,
    "fetchCastResources": True,
    "trackedActorGameIDs": {BLIGHTSCALE_SHRIEKER_GAME_ID},
    "trackedDamageTargetGameIDs": {ULATEK_GAME_ID, HEART_GAME_ID, DEVOURERS_SPAWN_GAME_ID},
    "tabs": [
        ["survival", "全场存活情况"],
        ["waves", "腐蚀浪潮和带蛋情况"],
        ["heart", "被缚之怒"],
        ["fangs", "攫取毒牙处理"],
        ["critical", "关键流程问题"],
    ],
    "mechanicVersion": "ulatek-p25-egg-review-2026-09-20-v8",
    "features": {"survival": True, "fieldReplay": False},
}

COURT_PROFILE = {
    "bossKey": "ulatek",
    "phaseModel": "cast_and_aura_timeline",
    "phaseRule": "P1/P2/P3 以被缚之怒结束点切分；最终碎场轮次以盘绕猎物施法切分。",
    "rules": [
        {
            "key": "p25_egg_remaining", "label": "P2.5 连续分摊结束仍携蛋", "mode": "direct",
            "spellIDs": [1299010, 1287265, 1295360],
            "requiredEvidence": ["第二次被缚之怒结束", "六次幽魂盘卷完成", "结算后存活且携蛋光环仍生效"],
            "defaultCountEnabled": True, "severityUnits": 1,
        },
        {
            "key": "caustic_wave_hit",
            "label": "命中腐蚀浪潮",
            "mode": "direct",
            "spellIDs": [1292403],
            "requiredEvidence": ["腐蚀浪潮 Debuff apply/stack/refresh"],
            "defaultCountEnabled": True,
            "severityUnits": 1,
        },
        {
            "key": "egg_carrier_wave_hit",
            "label": "携带蛇卵命中腐蚀浪潮",
            "mode": "direct",
            "spellIDs": [1292403, 1295360],
            "requiredEvidence": ["恶性甲壳有效区间", "腐蚀浪潮施加", "恶性甲壳随后移除"],
            "defaultCountEnabled": True,
            "severityUnits": 2,
        },
        {
            "key": "fangs_excess_stack",
            "label": "违反攫取毒牙同场三秒、对场等消层的拉线逻辑",
            "mode": "direct",
            "spellIDs": [1311611, 1311609],
            "requiredEvidence": ["两名厄鳞守卫的施加时间与场侧", "攫取毒牙移除", "凋萎静脉全团消除"],
            "defaultCountEnabled": True,
            "severityUnits": 1,
        },
        {
            "key": "mother_wrath_raidwide",
            "label": "蛇母之怒无人承接并触发全团伤害",
            "mode": "direct",
            "spellIDs": [1298367, 1298369, 1301122],
            "requiredEvidence": ["蛇母之怒完成施法", "同轮至少 3 名玩家受到蛇母之怒伤害", "施法目标或施法前 Boss 最近一次近战目标"],
            "defaultCountEnabled": True,
            "severityUnits": 2,
        },
    ],
}
validate_court_profile(COURT_PROFILE)


def _amount(event):
    value = event.get("amount")
    if value is None:
        value = event.get("unmitigatedAmount")
    return int(value or 0)


def _aura_intervals(events, spell_id, fight_end):
    active = {}
    intervals = []
    for event in sorted(
        (row for row in events if int(ability_id(row) or 0) == spell_id),
        key=lambda row: int(row.get("timestamp") or 0),
    ):
        player_id = event.get("targetID")
        timestamp = int(event.get("timestamp") or 0)
        kind = event_type(event)
        if kind in {"applydebuff", "applydebuffstack", "refreshdebuff", "applybuff", "refreshbuff"}:
            active.setdefault(player_id, timestamp)
        elif kind in {"removedebuff", "removebuff"} and player_id in active:
            intervals.append({"playerID": player_id, "start": active.pop(player_id), "end": timestamp})
    for player_id, start in active.items():
        intervals.append({"playerID": player_id, "start": start, "end": int(fight_end), "openEnded": True})
    return sorted(intervals, key=lambda row: (row["start"], row["playerID"] or 0))


def _rage_windows(fight, raw):
    return _aura_intervals(raw["enemyBuffs"], RAGE_ID, fight["endTime"])


def _phase_at(timestamp, rage_windows):
    if not rage_windows or timestamp < rage_windows[0]["end"]:
        return "P1"
    if len(rage_windows) == 1 or timestamp < rage_windows[1]["end"]:
        return "P2"
    return "P3"


def _active_interval(intervals, player_id, timestamp, *, removal_grace_ms=0):
    return next(
        (
            row for row in intervals
            if row["playerID"] == player_id
            and row["start"] <= timestamp <= row["end"] + int(removal_grace_ms)
        ),
        None,
    )


def _raid_aura_changes(events, spell_id):
    """Collapse one raidwide aura mutation into one canonical stack change."""
    candidates = sorted(
        (
            event for event in events
            if int(ability_id(event) or 0) == spell_id
            and event_type(event) in {"applydebuff", "applydebuffstack", "refreshdebuff"}
        ),
        key=lambda row: int(row.get("timestamp") or 0),
    )
    changes = []
    for event in candidates:
        timestamp = int(event.get("timestamp") or 0)
        if not changes or timestamp - changes[-1]["timestamp"] > 80:
            changes.append({"timestamp": timestamp, "toStack": 0, "eventTypes": set()})
        change = changes[-1]
        change["toStack"] = max(change["toStack"], int(event.get("stack") or 1))
        change["eventTypes"].add(event_type(event))
    for change in changes:
        change["eventTypes"] = sorted(change["eventTypes"])
    return changes


def _event_identity(event):
    return (
        int(event.get("timestamp") or 0),
        event_type(event),
        event.get("sourceID"),
        event.get("sourceInstance"),
        event.get("targetID"),
        event.get("targetInstance"),
        int(ability_id(event) or 0),
        event.get("stack"),
    )


def _owner_player_id(event, players, pet_owners):
    source_id = event.get("sourceID")
    seen = set()
    while source_id not in players and source_id in pet_owners and source_id not in seen:
        seen.add(source_id)
        source_id = pet_owners[source_id]
    return source_id if source_id in players else None


def _living_player_ids(players, raw, timestamp):
    living = set(players)
    changes = [
        (int(event.get("timestamp") or 0), "death", event.get("targetID"))
        for event in raw.get("deaths") or []
    ]
    changes.extend(
        (int(event.get("timestamp") or 0), "resurrect", event.get("targetID"))
        for event in raw.get("friendlyCasts") or []
        if event_type(event) == "resurrect"
    )
    for event_time, kind, player_id in sorted(changes):
        if event_time > timestamp:
            break
        if kind == "death":
            living.discard(player_id)
        else:
            living.add(player_id)
    return living


def _analyze_waves_and_eggs(fight, actor_map, players, raw, rage_windows):
    egg_intervals = _aura_intervals(raw["debuffs"], EGG_CARRY_ID, fight["endTime"])
    hatch_changes = _raid_aura_changes(raw["debuffs"], 1301268)
    wave_applies = [
        event for event in raw["debuffs"]
        if int(ability_id(event) or 0) == WAVE_ID
        and event.get("targetID") in players
        and event_type(event) in {"applydebuff", "applydebuffstack", "refreshdebuff"}
    ]
    # Match the recently corrected Sszorak aura metric: count actual aura
    # applications, stack applications and refreshes.  Only exact duplicate rows
    # are transport duplicates; two mutations close together are two contacts.
    distinct_wave_applies = []
    seen = set()
    for event in sorted(wave_applies, key=lambda row: int(row.get("timestamp") or 0)):
        identity = _event_identity(event)
        if identity in seen:
            continue
        seen.add(identity)
        distinct_wave_applies.append(event)

    hits = []
    for event in distinct_wave_applies:
        timestamp = int(event.get("timestamp") or 0)
        player_id = event.get("targetID")
        # WCL can emit the egg-aura removal 1-20 ms before the same-frame wave
        # damage.  Keep a very small grace window and require the separate
        # Corrupting Film raid-aura mutation before calling the hatch confirmed.
        carry = _active_interval(egg_intervals, player_id, timestamp, removal_grace_ms=250)
        direct = min(
            (
                row for row in raw["damage"]
                if int(ability_id(row) or 0) == WAVE_ID
                and row.get("targetID") == player_id
                and abs(int(row.get("timestamp") or 0) - timestamp) <= 750
            ),
            key=lambda row: abs(int(row.get("timestamp") or 0) - timestamp),
            default=None,
        )
        hatch_change = min(
            (
                row for row in hatch_changes
                if abs(row["timestamp"] - timestamp) <= 500
            ),
            key=lambda row: abs(row["timestamp"] - timestamp),
            default=None,
        )
        removal_delta_ms = carry["end"] - timestamp if carry else None
        early_hatch = bool(
            carry
            and hatch_change
            and -250 <= removal_delta_ms <= 2500
        )
        hits.append({
            **player_ref(players, actor_map, player_id),
            "timeMs": timestamp - fight["startTime"],
            "time": fmt_ms(timestamp - fight["startTime"]),
            "phase": _phase_at(timestamp, rage_windows),
            "amount": _amount(direct or {}),
            "eggCarrier": bool(carry),
            "earlyHatchConfirmed": early_hatch,
            "eggRemovedAfterMs": removal_delta_ms,
            "hatchEvidence": ({
                "spellID": 1301268,
                "time": fmt_ms(hatch_change["timestamp"] - fight["startTime"]),
                "deltaMs": hatch_change["timestamp"] - timestamp,
                "toStack": hatch_change["toStack"],
            } if hatch_change else None),
            "eventType": event_type(event),
        })

    wave_deaths = []
    seen_wave_deaths = set()
    for row in hits:
        hit_timestamp = fight["startTime"] + row["timeMs"]
        death = min(
            (
                event for event in raw.get("deaths") or []
                if event.get("targetID") == row["playerID"]
                and hit_timestamp <= int(event.get("timestamp") or 0) <= hit_timestamp + WAVE_DEATH_WINDOW_MS
            ),
            key=lambda event: int(event.get("timestamp") or 0),
            default=None,
        )
        row["diedWithinWindow"] = bool(death)
        if death is not None:
            death_timestamp = int(death.get("timestamp") or 0)
            death_ability_id = int(death.get("killingAbilityGameID") or ability_id(death) or 0)
            row["deathDelayMs"] = death_timestamp - hit_timestamp
            row["deathAbilityID"] = death_ability_id
            identity = (row["playerID"], death_timestamp)
            if identity not in seen_wave_deaths:
                seen_wave_deaths.add(identity)
                wave_deaths.append({
                    **player_ref(players, actor_map, row["playerID"]),
                    "phase": row["phase"],
                    "waveTime": row["time"],
                    "deathTime": fmt_ms(death_timestamp - fight["startTime"]),
                    "delayMs": death_timestamp - hit_timestamp,
                    "abilityID": death_ability_id,
                    "ability": spell_name(death_ability_id, GUIDE_SPELLS),
                })
    carries = []
    for interval in egg_intervals:
        phase = _phase_at(interval["start"], rage_windows)
        if phase not in {"P1", "P3"}:
            continue
        player_id = interval["playerID"]
        related_hits = [
            row for row in hits
            if row["playerID"] == player_id
            and interval["start"] <= fight["startTime"] + row["timeMs"] <= interval["end"] + 250
        ]
        carries.append({
            **player_ref(players, actor_map, player_id),
            "phase": phase,
            "startTime": fmt_ms(interval["start"] - fight["startTime"]),
            "endTime": fmt_ms(interval["end"] - fight["startTime"]),
            "durationSec": round((interval["end"] - interval["start"]) / 1000, 2),
            "waveHitCount": len(related_hits),
            "earlyHatchCount": sum(row["earlyHatchConfirmed"] for row in related_hits),
            "openEnded": bool(interval.get("openEnded")),
        })
    return {
        "spellID": WAVE_ID,
        "eggAuraID": EGG_CARRY_ID,
        "hitCount": len(hits),
        "applicationCount": len(hits),
        "eggCarrierHitCount": sum(row["eggCarrier"] for row in hits),
        "earlyHatchCount": sum(row["earlyHatchConfirmed"] for row in hits),
        "hits": hits,
        "waveDeathWindowMs": WAVE_DEATH_WINDOW_MS,
        "waveDeaths": {
            "totalCount": len(wave_deaths),
            "p1Count": sum(row["phase"] == "P1" for row in wave_deaths),
            "p3Count": sum(row["phase"] == "P3" for row in wave_deaths),
            "events": wave_deaths,
        },
        "carries": carries,
    }


def _position_sample(position_index, actor_id, timestamp):
    sample = position_at_interpolated(
        position_index,
        actor_id,
        timestamp,
        reliable_window_ms=3_000,
        fallback_window_ms=15_000,
    )
    if not sample:
        return None
    return {
        "x": round(float(sample["x"]), 2),
        "y": round(float(sample["y"]), 2),
        "sampleOffsetMs": int(sample.get("sampleOffsetMs") or 0),
        "reliable": bool(sample.get("reliable")),
    }


def _analyze_p25_eggs(fight, actor_map, players, raw):
    result = {"enabled": True, "started": False, "completed": False, "expectedSoakCount": P25_COIL_COUNT,
              "completedSoakCount": 0, "deaths": [], "remaining": [], "deathCount": 0, "mistakeCount": 0,
              "evidenceNote": "P2.5 按第二次被缚之怒结束后的六次幽魂盘卷界定。阶段内带蛋死亡单独统计；第六次结算后仍存活且携蛋记一次玩家失误。预留250毫秒处理同帧光环移除；日志不足或分摊未完成时不判残留。"}
    rage = _rage_windows(fight, raw)
    if len(rage) < 2 or rage[1].get("openEnded"):
        result["reason"] = "尚未确认第二次被缚之怒结束"
        return result
    after_rage = rage[1]["end"]
    unique = {_event_identity(e): e for e in raw.get("casts", [])}
    casts = sorted(unique.values(), key=lambda e: int(e["timestamp"]))
    phase_limit = min([int(fight["endTime"])] + [int(e["timestamp"]) for e in casts
                     if int(e["timestamp"]) > after_rage and ability_id(e) in {1295905, 1315341}
                     and event_type(e) in {"begincast", "cast"}])
    coils = [e for e in casts if ability_id(e) == P25_COIL_CAST_ID
             and after_rage <= int(e["timestamp"]) < phase_limit and event_type(e) in {"begincast", "cast"}]
    if not coils:
        result["reason"] = "尚未观测到 P2.5 连续幽魂盘卷"
        return result
    stage_start = min(int(e["timestamp"]) for e in coils)
    finishes = [e for e in coils if event_type(e) == "cast"]
    result.update(started=True, startTime=fmt_ms(stage_start - fight["startTime"]), completedSoakCount=len(finishes))
    completed = len(finishes) >= P25_COIL_COUNT
    checkpoint = None
    if completed:
        last = finishes[P25_COIL_COUNT - 1]
        last_ts = int(last["timestamp"])
        hits = [int(e["timestamp"]) for e in raw.get("damage", []) if ability_id(e) == P25_COIL_DAMAGE_ID
                and e.get("sourceID") == last.get("sourceID")
                and e.get("sourceInstance", 1) == last.get("sourceInstance", 1)
                and last_ts <= int(e["timestamp"]) <= last_ts + 1000]
        settlement = max([last_ts] + hits)
        checkpoint = settlement + P25_EGG_SETTLE_MS
        completed = checkpoint < int(fight["endTime"])
        result["lastSoakTime"] = fmt_ms(settlement - fight["startTime"])
    stage_end = checkpoint if completed else phase_limit
    result.update(completed=completed, endTime=fmt_ms(stage_end - fight["startTime"]))
    if not completed:
        result["reason"] = "连续分摊未完整结束或日志未覆盖结算后时刻，不判残留携蛋"
    deaths = sorted({_event_identity(e): e for e in raw.get("deaths", []) if event_type(e) == "death"
                     and e.get("targetID") in players}.values(), key=lambda e: int(e["timestamp"]))
    carries = _aura_intervals(raw.get("debuffs", []), EGG_CARRY_ID, fight["endTime"])
    for aura in carries:
        aura["end"] = min([aura["end"]] + [int(e["timestamp"]) for e in deaths
                          if e.get("targetID") == aura["playerID"] and aura["start"] <= int(e["timestamp"]) <= aura["end"]])
    for death in deaths:
        pid, ts = death["targetID"], int(death["timestamp"])
        carry = next((a for a in carries if a["playerID"] == pid and a["start"] < ts <= a["end"]), None)
        if stage_start <= ts <= stage_end and carry:
            sid = int(death.get("killingAbilityGameID") or ability_id(death) or 0)
            result["deaths"].append({**player_ref(players, actor_map, pid), "time": fmt_ms(ts - fight["startTime"]),
                                     "carryStartTime": fmt_ms(carry["start"] - fight["startTime"]),
                                     "abilityID": sid, "ability": spell_name(sid, GUIDE_SPELLS), "isPlayerMistake": False})
    if completed:
        living = _living_player_ids(players, raw, checkpoint)
        for pid in sorted(living):
            carry = next((a for a in carries if a["playerID"] == pid and a["start"] <= checkpoint and a["end"] > checkpoint), None)
            if carry:
                result["remaining"].append({**player_ref(players, actor_map, pid), "time": fmt_ms(checkpoint - fight["startTime"]),
                                            "carryStartTime": fmt_ms(carry["start"] - fight["startTime"]),
                                            "spellID": EGG_CARRY_ID, "isPlayerMistake": True,
                                            "reason": "P2.5 六次幽魂盘卷结束后仍携带蛇卵"})
    result["deathCount"], result["mistakeCount"] = len(result["deaths"]), len(result["remaining"])
    return result


def _analyze_serpent_bites(fight, actor_map, players, raw):
    casts = sorted(completed_casts(raw.get("casts") or [], 1295905), key=lambda row: int(row["timestamp"]))
    target_events = sorted(
        (
            event for event in raw.get("debuffs") or []
            if int(ability_id(event) or 0) == SERPENT_BITE_TARGET_ID
            and event.get("targetID") in players
        ),
        key=lambda row: int(row.get("timestamp") or 0),
    )
    position_index = build_position_index(raw.get("resources") or [])
    rounds = []
    for index, cast in enumerate(casts, start=1):
        cast_time = int(cast["timestamp"])
        next_cast = int(casts[index]["timestamp"]) if index < len(casts) else int(fight["endTime"])
        applies = [
            event for event in target_events
            if event_type(event) == "applydebuff"
            and cast_time - 250 <= int(event["timestamp"]) < min(cast_time + 2_500, next_cast)
        ]
        if not applies:
            continue
        target_ids = list(dict.fromkeys(event.get("targetID") for event in applies))
        removals = {
            player_id: min(
                (
                    event for event in target_events
                    if event.get("targetID") == player_id
                    and event_type(event) == "removedebuff"
                    and cast_time <= int(event["timestamp"]) < next_cast
                ),
                key=lambda row: int(row["timestamp"]),
                default=None,
            )
            for player_id in target_ids
        }
        completed_removals = [event for event in removals.values() if event is not None]
        snapshot_time = min(
            (int(event["timestamp"]) for event in completed_removals),
            default=min(next_cast - 1, cast_time + 9_500),
        )
        living = _living_player_ids(players, raw, snapshot_time)
        target_rows = []
        target_positions = []
        for player_id in target_ids:
            removal = removals[player_id]
            removal_time = int(removal["timestamp"]) if removal else snapshot_time
            position = _position_sample(position_index, player_id, removal_time)
            calcified = any(
                int(ability_id(event) or 0) == CALCIFIED_CORPSE_ID
                and event.get("targetID") == player_id
                and abs(int(event.get("timestamp") or 0) - removal_time) <= 500
                and event_type(event) in {"applydebuff", "applybuff"}
                for event in raw.get("debuffs") or []
            )
            volatile_purge = any(
                int(ability_id(event) or 0) in {1312967, 1316356}
                and event.get("targetID") == player_id
                and abs(int(event.get("timestamp") or 0) - removal_time) <= 500
                and event_type(event) == "applydebuff"
                for event in raw.get("debuffs") or []
            )
            row = {
                **player_ref(players, actor_map, player_id),
                "removeTime": fmt_ms(removal_time - fight["startTime"]) if removal else None,
                "removed": bool(removal),
                "resolution": "calcified_corpse" if calcified else ("volatile_purge" if volatile_purge else ("removed" if removal else "unresolved")),
                "volatilePurgeApplied": volatile_purge,
                "position": position,
            }
            target_rows.append(row)
            if position and position["reliable"]:
                target_positions.append((player_id, position))

        aura_participant_ids = sorted({
            event.get("targetID")
            for event in raw.get("debuffs") or []
            if int(ability_id(event) or 0) == INGESTED_VENOM_ID
            and event.get("targetID") in living
            and cast_time <= int(event.get("timestamp") or 0) <= snapshot_time
            and event_type(event) in {"applydebuff", "applydebuffstack", "refreshdebuff"}
        })
        aura_participant_set = set(aura_participant_ids) | set(target_ids)
        participants = []
        non_participants = []
        position_unknown = []
        for player_id in sorted(living):
            position = _position_sample(position_index, player_id, snapshot_time)
            ref = player_ref(players, actor_map, player_id)
            nearest_id = None
            distance = None
            if position and position["reliable"] and target_positions:
                distances = [
                    (target_id, math.hypot(position["x"] - target_position["x"], position["y"] - target_position["y"]) / 100)
                    for target_id, target_position in target_positions
                ]
                nearest_id, distance = min(distances, key=lambda item: item[1])
            else:
                position_unknown.append({**ref, "position": position})
            row = {
                **ref,
                "distanceYards": round(distance, 2) if distance is not None else None,
                "nearestTargetID": nearest_id,
                "position": position,
            }
            (participants if player_id in aura_participant_set else non_participants).append(row)
        rounds.append({
            "index": index,
            "time": fmt_ms(cast_time - fight["startTime"]),
            "snapshotTime": fmt_ms(snapshot_time - fight["startTime"]),
            "radiusYards": SERPENT_BITE_RADIUS_YARDS,
            "targets": target_rows,
            "participants": participants,
            "participantCount": len(participants),
            "nonParticipants": non_participants,
            "nonParticipantCount": len(non_participants),
            "unknownPlayers": position_unknown,
            "positionEvidenceComplete": not position_unknown and bool(target_positions),
            "allPlayersParticipated": not non_participants,
            "participationEvidence": "ingested-venom-aura",
            "auraParticipants": [player_ref(players, actor_map, player_id) for player_id in aura_participant_ids],
        })
    return {
        "spellID": 1295905,
        "targetAuraID": SERPENT_BITE_TARGET_ID,
        "participationAuraID": INGESTED_VENOM_ID,
        "roundCount": len(rounds),
        "rounds": rounds,
    }


def _clock_direction(position, center, boss_position):
    if not position or not center or not boss_position:
        return None
    forward_x = boss_position["x"] - center["x"]
    forward_y = boss_position["y"] - center["y"]
    egg_x = position["x"] - center["x"]
    egg_y = position["y"] - center["y"]
    if math.hypot(forward_x, forward_y) < 1 or math.hypot(egg_x, egg_y) < 1:
        return None
    dot = forward_x * egg_x + forward_y * egg_y
    cross = forward_x * egg_y - forward_y * egg_x
    clockwise = math.atan2(-cross, dot) % (2 * math.pi)
    quarter = int(math.floor(clockwise / (math.pi / 2) + 0.5)) % 4
    return ("12点", "3点", "6点", "9点")[quarter]


def _egg_assignment(clock_direction):
    return {"3点": "近战", "6点": "远程", "9点": "远程"}.get(clock_direction, "未指定")


def _analyze_p3_eggs(fight, actor_map, players, raw, rage_windows):
    target_game_ids = raw.get("trackedDamageTargetGameIDByActorID") or {}
    spawn_actor_ids = {
        actor_id for actor_id, game_id in target_game_ids.items()
        if int(game_id or 0) == DEVOURERS_SPAWN_GAME_ID
    }
    spawn_events = []
    seen = set()
    for event in sorted(raw.get("casts") or [], key=lambda row: int(row.get("timestamp") or 0)):
        if int(ability_id(event) or 0) != DEVOURERS_SPAWN_SHELL_ID or event_type(event) != "cast":
            continue
        if spawn_actor_ids and event.get("sourceID") not in spawn_actor_ids:
            continue
        identity = (event.get("sourceID"), event.get("sourceInstance"), int(event.get("timestamp") or 0))
        if identity in seen or _phase_at(int(event.get("timestamp") or 0), rage_windows) != "P3":
            continue
        seen.add(identity)
        spawn_events.append(event)

    grouped = []
    for event in spawn_events:
        timestamp = int(event["timestamp"])
        if not grouped or timestamp - grouped[-1]["time"] > 1_500:
            grouped.append({"time": timestamp, "events": []})
        grouped[-1]["events"].append(event)

    egg_damage = [
        event for event in raw.get("trackedDamageTaken") or []
        if int(target_game_ids.get(event.get("targetID")) or 0) == DEVOURERS_SPAWN_GAME_ID
    ]
    pet_owners = raw.get("petOwners") or {}
    shell_removes = [
        event for event in raw.get("enemyBuffs") or []
        if int(ability_id(event) or 0) == DEVOURERS_SPAWN_SHELL_ID
        and event_type(event) == "removebuff"
    ]
    tracked_actor_game_ids = raw.get("trackedActorGameIDByActorID") or {}
    shrieker_actor_ids = {
        actor_id for actor_id, game_id in tracked_actor_game_ids.items()
        if int(game_id or 0) == BLIGHTSCALE_SHRIEKER_GAME_ID
    }
    shrieker_instances = defaultdict(list)
    for event in raw.get("trackedActorEvents") or []:
        if event.get("sourceID") in shrieker_actor_ids and event.get("sourceInstance") is not None:
            shrieker_instances[(event.get("sourceID"), event.get("sourceInstance"))].append(event)
    shriekers = []
    for (source_id, source_instance), events in shrieker_instances.items():
        events.sort(key=lambda row: int(row.get("timestamp") or 0))
        position_event = next(
            (
                event for event in events
                if event_type(event) in {"cast", "begincast"}
                and event.get("x") is not None and event.get("y") is not None
            ),
            None,
        )
        shriekers.append({
            "sourceID": source_id,
            "sourceInstance": source_instance,
            "time": int(events[0]["timestamp"]),
            "position": ({"x": float(position_event["x"]), "y": float(position_event["y"])} if position_event else None),
        })

    complete_group = next((group for group in grouped if len(group["events"]) >= 4), None)
    center = None
    if complete_group:
        points = [event for event in complete_group["events"] if event.get("x") is not None and event.get("y") is not None]
        if points:
            center = {"x": sum(float(row["x"]) for row in points) / len(points), "y": sum(float(row["y"]) for row in points) / len(points)}
    boss_index = build_position_index(raw.get("bossPositionEvents") or [])
    boss_id = raw.get("bossID")
    rounds = []
    for index, group in enumerate(grouped, start=1):
        timestamp = group["time"]
        boss_state = _position_sample(boss_index, boss_id, timestamp) if boss_id is not None else None
        if center is None:
            points = [event for event in group["events"] if event.get("x") is not None and event.get("y") is not None]
            local_center = ({"x": sum(float(row["x"]) for row in points) / len(points), "y": sum(float(row["y"]) for row in points) / len(points)} if points else None)
        else:
            local_center = center
        round_shriekers = [
            row for row in shriekers
            if 4_000 <= row["time"] - timestamp <= 29_000
        ]
        baseline_shriekers = int(BASELINE_P3_SHRIEKERS.get(index, 0))
        extra_shrieker_count = max(0, len(round_shriekers) - baseline_shriekers)
        eggs = []
        for event in group["events"]:
            instance = event.get("sourceInstance")
            damage_events = [row for row in egg_damage if row.get("targetInstance") == instance]
            by_player = defaultdict(lambda: {"damage": 0, "hitCount": 0})
            for damage_event in damage_events:
                player_id = _owner_player_id(damage_event, players, pet_owners)
                if player_id is None:
                    continue
                by_player[player_id]["damage"] += _amount(damage_event)
                by_player[player_id]["hitCount"] += 1
            damage_by_player = sorted(
                ({**player_ref(players, actor_map, player_id), **values} for player_id, values in by_player.items()),
                key=lambda row: row["damage"],
                reverse=True,
            )
            killed = any(row.get("overkill") is not None for row in damage_events)
            position = ({"x": float(event["x"]), "y": float(event["y"])} if event.get("x") is not None and event.get("y") is not None else None)
            clock = _clock_direction(position, local_center, boss_state)
            removed = next(
                (
                    row for row in shell_removes
                    if row.get("targetID") == event.get("sourceID")
                    and row.get("targetInstance") == instance
                    and int(row.get("timestamp") or 0) >= timestamp
                ),
                None,
            )
            eggs.append({
                "instance": instance,
                "position": position,
                "clockDirection": clock,
                "expectedGroup": _egg_assignment(clock),
                "killed": killed,
                "removedTime": fmt_ms(int(removed["timestamp"]) - fight["startTime"]) if removed else None,
                "totalDamage": sum(row["damage"] for row in damage_by_player),
                "damageByPlayer": damage_by_player,
            })
        # An unfinished log can contain living eggs that never had time to hatch.
        # Only extra Shriekers above the fixed per-round baseline confirm a failed egg.
        unkilled_observed = [row for row in eggs if not row["killed"]]
        failed_observed = unkilled_observed[:extra_shrieker_count]
        for row in failed_observed:
            row["confirmedByExtraShrieker"] = True
        used_directions = {row["clockDirection"] for row in eggs if row.get("clockDirection")}
        missing_directions = [direction for direction in ("12点", "3点", "6点", "9点") if direction not in used_directions]
        synthetic_count = max(0, extra_shrieker_count - len(failed_observed))
        failed_eggs = list(failed_observed)
        for offset in range(synthetic_count):
            clock = missing_directions[offset] if offset < len(missing_directions) else None
            failed_eggs.append({
                "instance": None,
                "position": round_shriekers[baseline_shriekers + len(failed_observed) + offset].get("position"),
                "clockDirection": clock,
                "expectedGroup": _egg_assignment(clock),
                "killed": False,
                "confirmedByExtraShrieker": True,
                "totalDamage": 0,
                "damageByPlayer": [],
            })
        rounds.append({
            "index": index,
            "time": fmt_ms(timestamp - fight["startTime"]),
            "expectedEggCount": 4,
            "expectedKillableEggCount": max(0, 4 - baseline_shriekers),
            "observedEggCount": len(eggs),
            "baselineShriekerCount": baseline_shriekers,
            "shriekerCount": len(round_shriekers),
            "extraShriekerCount": extra_shrieker_count,
            "failedEggCount": len(failed_eggs),
            "eggs": eggs,
            "failedEggs": failed_eggs,
        })
    return {
        "eggGameID": DEVOURERS_SPAWN_GAME_ID,
        "shriekerGameID": BLIGHTSCALE_SHRIEKER_GAME_ID,
        "expectedEggsPerRound": 4,
        "roundCount": len(rounds),
        "failedEggCount": sum(row["failedEggCount"] for row in rounds),
        "rounds": rounds,
    }


def _burst_potion_intervals(fight, raw):
    """Use aura lifetimes, never cast timestamps or a fixed pre-window grace."""
    active, seen, intervals = {}, set(), []
    events = list(raw.get("friendlyBuffs") or []) + [e for e in raw.get("deaths", []) if event_type(e) == "death"]

    def close(key, end, open_ended=False):
        begin, unknown_start = active.pop(key)
        end = min([end] + [int(e["timestamp"]) for e in raw.get("deaths", [])
                           if event_type(e) == "death" and e.get("targetID") == key[0]
                           and begin <= int(e["timestamp"]) < end])
        if end > begin:
            intervals.append({"playerID": key[0], "spellID": key[1], "start": begin, "end": end,
                              "unknownStart": unknown_start, "openEnded": open_ended})

    for e in sorted(events, key=lambda e: int(e.get("timestamp") or 0)):
        ts, pid, kind = int(e.get("timestamp") or 0), e.get("targetID"), event_type(e)
        if ts > fight["endTime"]:
            continue
        if kind == "death":
            for key in list(active):
                if key[0] == pid:
                    close(key, ts)
            continue
        sid = int(ability_id(e) or 0)
        if sid not in BURST_POTIONS:
            continue
        key = (pid, sid)
        if kind in {"applybuff", "refreshbuff"}:
            active.setdefault(key, (ts, False))
            seen.add(key)
        elif kind == "removebuff":
            # An initial removal proves an aura carried into the recorded fight.
            if key not in seen:
                active[key] = (int(fight["startTime"]), True)
            if key in active:
                close(key, ts)
            seen.add(key)
    for key in list(active):
        close(key, int(fight["endTime"]), True)
    return intervals


def _rage_potions(fight, actor_map, players, raw, window, intervals):
    start, end = window["start"], window["end"]
    living = _living_player_ids(players, raw, start)
    rows = []
    for pid, p in players.items():
        role = str(p.get("role") or "")
        if not (role.endswith("tank") or role.endswith("dps")):
            continue
        effects, spans = [], []
        for aura in intervals:
            left, right = max(start, aura["start"]), min(end, aura["end"])
            if aura["playerID"] != pid or right <= left:
                continue
            spans.append((left, right))
            effects.append({"spellID": aura["spellID"], "spell": BURST_POTIONS[aura["spellID"]],
                            "startTime": None if aura["unknownStart"] else fmt_ms(aura["start"] - fight["startTime"]),
                            "endTime": fmt_ms(aura["end"] - fight["startTime"]),
                            "openEnded": aura["openEnded"], "unknownStart": aura["unknownStart"],
                            "overlapStart": fmt_ms(left - fight["startTime"]), "overlapEnd": fmt_ms(right - fight["startTime"]),
                            "overlapMs": right - left})
        merged = []
        for left, right in sorted(spans):
            if merged and left <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], right)
            else:
                merged.append([left, right])
        overlap_ms = sum(right - left for left, right in merged)
        available = raw.get("friendlyBuffs") is not None
        rows.append({**player_ref(players, actor_map, pid), "potionUsed": bool(effects) if available else None,
                     "aliveAtStart": pid in living, "coverageMs": overlap_ms,
                     "coveragePercent": round(100 * overlap_ms / (end - start), 1) if end > start else 0,
                     "effects": effects})
    rows.sort(key=lambda row: (row["potionUsed"] is True, row["playerID"]))
    return {"players": rows, "playerCount": len(rows), "usedCount": sum(r["potionUsed"] is True for r in rows),
            "missingCount": sum(r["potionUsed"] is False for r in rows),
            "unknownCount": sum(r["potionUsed"] is None for r in rows),
            "evidenceNote": "检查所有坦克和输出，包括零伤害及已死亡玩家；药水光环与易伤窗口有实际重叠即算已吃药，提前激活也计入。只统计爆发药水，不计治疗药水。覆盖时长按光环生效区间计算，死亡时截止。"}


def _analyze_rage(fight, actor_map, players, raw, rage_windows):
    rounds = []
    potion_intervals = _burst_potion_intervals(fight, raw)
    target_game_ids = raw.get("trackedDamageTargetGameIDByActorID") or {}
    for index, window in enumerate(rage_windows, start=1):
        start, end = window["start"], window["end"]
        window_damage = [
            event for event in raw.get("trackedDamageTaken") or []
            if start <= int(event.get("timestamp") or 0) <= end
            and (
                not target_game_ids
                or int(target_game_ids.get(event.get("targetID")) or 0) in {ULATEK_GAME_ID, HEART_GAME_ID}
            )
        ]
        boss_id = window.get("playerID")
        boss_damage = [
            event for event in window_damage
            if int(target_game_ids.get(event.get("targetID")) or 0) == ULATEK_GAME_ID
            or (not target_game_ids and event.get("targetID") == boss_id)
        ]
        heart_damage = [
            event for event in window_damage
            if int(target_game_ids.get(event.get("targetID")) or 0) == HEART_GAME_ID
            or (not target_game_ids and event.get("targetID") != boss_id)
        ]
        by_player = defaultdict(lambda: {
            "heartDamage": 0,
            "bossDamage": 0,
            "heartHits": 0,
            "bossHits": 0,
        })
        pet_owners = raw.get("petOwners") or {}

        for event in heart_damage:
            player_id = _owner_player_id(event, players, pet_owners)
            if player_id is None:
                continue
            by_player[player_id]["heartDamage"] += _amount(event)
            by_player[player_id]["heartHits"] += 1
        for event in boss_damage:
            player_id = _owner_player_id(event, players, pet_owners)
            if player_id is None:
                continue
            by_player[player_id]["bossDamage"] += _amount(event)
            by_player[player_id]["bossHits"] += 1
        damage_by_player = []
        for player_id, values in by_player.items():
            total_damage = values["heartDamage"] + values["bossDamage"]
            damage_by_player.append({
                **player_ref(players, actor_map, player_id),
                **values,
                "totalDamage": total_damage,
                "damage": total_damage,
                "hitCount": values["heartHits"] + values["bossHits"],
            })
        damage_by_player.sort(key=lambda row: row["totalDamage"], reverse=True)
        debris = [
            event for event in raw["damage"]
            if int(ability_id(event) or 0) == 1286885
            and event.get("targetID") in players
            and start <= int(event.get("timestamp") or 0) <= end
        ]
        deaths = [
            event for event in raw["deaths"]
            if start <= int(event.get("timestamp") or 0) <= end
        ]
        rounds.append({
            "index": index,
            "time": fmt_ms(start - fight["startTime"]),
            "endTime": fmt_ms(end - fight["startTime"]),
            "durationSec": round((end - start) / 1000, 2),
            "potions": _rage_potions(fight, actor_map, players, raw, window, potion_intervals),
            "heartDamage": sum(_amount(event) for event in heart_damage),
            "bossDamage": sum(_amount(event) for event in boss_damage),
            "totalDamage": sum(_amount(event) for event in window_damage),
            "damageByPlayer": damage_by_player,
            "heartDamageByPlayer": sorted(
                [
                    {
                        **row,
                        "damage": row["heartDamage"],
                        "hitCount": row["heartHits"],
                    }
                    for row in damage_by_player
                    if row["heartDamage"] > 0
                ],
                key=lambda row: row["damage"],
                reverse=True,
            ),
            "fallingDebrisHitCount": len(debris),
            "fallingDebrisDamage": sum(_amount(event) for event in debris),
            "fallingDebrisHits": [
                {
                    **player_ref(players, actor_map, event.get("targetID")),
                    "time": fmt_ms(int(event["timestamp"]) - fight["startTime"]),
                    "amount": _amount(event),
                }
                for event in debris
            ],
            "deathCount": len(deaths),
            "deaths": [
                {
                    **player_ref(players, actor_map, event.get("targetID")),
                    "time": fmt_ms(int(event["timestamp"]) - fight["startTime"]),
                    "abilityID": int(event.get("killingAbilityGameID") or ability_id(event) or 0),
                    "ability": spell_name(
                        int(event.get("killingAbilityGameID") or ability_id(event) or 0),
                        GUIDE_SPELLS,
                    ),
                }
                for event in deaths
            ],
        })
    return {
        "rounds": rounds,
        "totalDeathCount": sum(row["deathCount"] for row in rounds),
        "totalHeartDamage": sum(row["heartDamage"] for row in rounds),
        "totalBossDamage": sum(row["bossDamage"] for row in rounds),
        "totalDamage": sum(row["totalDamage"] for row in rounds),
    }


def _analyze_fangs(fight, actor_map, players, raw):
    applies = [
        event for event in raw["debuffs"]
        if int(ability_id(event) or 0) == FANG_AURA_ID
        and event.get("targetID") in players
        and event_type(event) == "applydebuff"
    ]
    removes = [
        event for event in raw["debuffs"]
        if int(ability_id(event) or 0) == FANG_AURA_ID
        and event.get("targetID") in players
        and event_type(event) == "removedebuff"
    ]
    if not applies:
        return {"batchWindowSec": 3, "rounds": [], "wrongBreakCount": 0, "maxBlightStack": 0}

    start = min(int(event["timestamp"]) for event in applies)
    targets = {}
    for event in sorted(applies, key=lambda row: int(row["timestamp"])):
        targets.setdefault(event.get("targetID"), int(event["timestamp"]))

    apply_groups = []
    for event in sorted(applies, key=lambda row: int(row["timestamp"])):
        timestamp = int(event["timestamp"])
        if not apply_groups or timestamp - apply_groups[-1]["timestamp"] > 250:
            apply_groups.append({"timestamp": timestamp, "events": []})
        apply_groups[-1]["events"].append(event)
    warden_casts = sorted(completed_casts(raw.get("casts") or [], 1301117), key=lambda row: int(row["timestamp"]))
    matched_casts = []
    for group in apply_groups:
        cast = min(
            (
                row for row in warden_casts
                if abs(int(row.get("timestamp") or 0) - group["timestamp"]) <= 500
            ),
            key=lambda row: abs(int(row.get("timestamp") or 0) - group["timestamp"]),
            default=None,
        )
        matched_casts.append(cast)
    boss_position_index = build_position_index(raw.get("bossPositionEvents") or [])
    boss_id = raw.get("bossID")
    boss_position_rows = boss_position_index.get(boss_id) or []
    boss_spawn = boss_position_rows[0] if boss_position_rows else None
    boss_boundary_x = float(boss_spawn["x"]) if boss_spawn else None
    cast_positions = [float(row["x"]) for row in matched_casts if row and row.get("x") is not None]
    for index, group in enumerate(apply_groups):
        cast = matched_casts[index]
        if cast and cast.get("x") is not None and boss_boundary_x is not None:
            side = "左场" if float(cast["x"]) < boss_boundary_x else "右场"
            side_source = "boss-initial-boundary"
        elif cast and cast.get("x") is not None and len(cast_positions) >= 2:
            side = "左场" if float(cast["x"]) == min(cast_positions) else "右场"
            side_source = "warden-relative-fallback"
        else:
            side = "先施加场" if index == 0 else ("后施加场" if index == 1 else f"第 {index + 1} 场")
            side_source = "application-order-fallback"
        group["side"] = side
        group["sideSource"] = side_source
        group["wardenInstance"] = cast.get("sourceInstance") if cast else None
        group["positionX"] = float(cast["x"]) if cast and cast.get("x") is not None else None
    side_by_player = {
        event.get("targetID"): group["side"]
        for group in apply_groups
        for event in group["events"]
    }

    stack_changes = _raid_aura_changes(raw["debuffs"], BLIGHT_VEIN_ID)
    break_events = sorted(
        (row for row in removes if row.get("targetID") in targets),
        key=lambda row: int(row["timestamp"]),
    )
    assigned = defaultdict(list)
    unresolved_events = []
    for event in break_events:
        timestamp = int(event["timestamp"])
        change = min(
            (row for row in stack_changes if 0 <= row["timestamp"] - timestamp <= 500),
            key=lambda row: row["timestamp"] - timestamp,
            default=None,
        )
        if change:
            assigned[change["timestamp"]].append((event, change))
        else:
            unresolved_events.append(event)

    breaks = []
    for change_timestamp in sorted(assigned):
        group = assigned[change_timestamp]
        to_stack = int(group[0][1]["toStack"])
        from_stack = max(0, to_stack - len(group))
        for offset, (event, change) in enumerate(group):
            timestamp = int(event["timestamp"])
            row_from = from_stack + offset
            row_to = row_from + 1
            breaks.append({
                **player_ref(players, actor_map, event.get("targetID")),
                "time": fmt_ms(timestamp - fight["startTime"]),
                "heldSec": round((timestamp - targets[event.get("targetID")]) / 1000, 2),
                "fromStack": row_from,
                "toStack": row_to,
                "blightStack": row_to,
                "stackEvidenceTime": fmt_ms(change["timestamp"] - fight["startTime"]),
                "absoluteTime": timestamp,
                "side": side_by_player.get(event.get("targetID")),
            })
    for event in unresolved_events:
        timestamp = int(event["timestamp"])
        breaks.append({
            **player_ref(players, actor_map, event.get("targetID")),
            "time": fmt_ms(timestamp - fight["startTime"]),
            "heldSec": round((timestamp - targets[event.get("targetID")]) / 1000, 2),
            "fromStack": None,
            "toStack": None,
            "blightStack": 0,
            "stackEvidenceTime": None,
            "absoluteTime": timestamp,
            "side": side_by_player.get(event.get("targetID")),
            "evidenceMissing": True,
        })
    breaks.sort(key=lambda row: (row["absoluteTime"], row["player"]))

    active_blight = set()
    clear_times = []
    for event in sorted(
        (
            row for row in raw.get("debuffs") or []
            if int(ability_id(row) or 0) == BLIGHT_VEIN_ID
        ),
        key=lambda row: int(row.get("timestamp") or 0),
    ):
        kind = event_type(event)
        player_id = event.get("targetID")
        if kind == "applydebuff":
            active_blight.add(player_id)
        elif kind == "removedebuff" and player_id in active_blight:
            active_blight.discard(player_id)
            if not active_blight:
                clear_times.append(int(event.get("timestamp") or 0))

    first_break = breaks[0] if breaks else None
    first_side = first_break.get("side") if first_break else None
    first_time = first_break.get("absoluteTime") if first_break else None
    first_clear = next((timestamp for timestamp in clear_times if first_time is not None and timestamp > first_time), None)
    opposite_sides = [group["side"] for group in apply_groups if group["side"] != first_side]
    opposite_side = opposite_sides[0] if opposite_sides else None
    opposite_after_clear = [
        row for row in breaks
        if row.get("side") == opposite_side
        and first_clear is not None
        and row["absoluteTime"] >= first_clear
    ]
    second_time = opposite_after_clear[0]["absoluteTime"] if opposite_after_clear else None

    candidate_reasons = []
    for row in breaks:
        reasons = []
        timestamp = row["absoluteTime"]
        if row.get("side") == first_side and first_time is not None:
            row["batch"] = 1
            row["deltaFromBatchStartMs"] = timestamp - first_time
            if timestamp - first_time > FANG_BATCH_WINDOW_MS:
                reasons.append("同场未在首断后 3 秒内拉断")
        elif row.get("side") == opposite_side:
            row["batch"] = 2
            if first_clear is None or timestamp < first_clear:
                reasons.append("对场未等待凋萎静脉消除")
                row["deltaFromBatchStartMs"] = None
            elif second_time is not None:
                row["deltaFromBatchStartMs"] = timestamp - second_time
                if timestamp - second_time > FANG_BATCH_WINDOW_MS:
                    reasons.append("同场未在首断后 3 秒内拉断")
        else:
            row["batch"] = None
            row["deltaFromBatchStartMs"] = None
            reasons.append("无法确认所属场侧")
        row["blightClearedBeforeBreak"] = bool(first_clear is not None and timestamp >= first_clear)
        candidate_reasons.append(reasons)

    first_violation_index = next(
        (index for index, reasons in enumerate(candidate_reasons) if reasons),
        None,
    )
    for index, row in enumerate(breaks):
        is_first_violation = index == first_violation_index
        row["violationReasons"] = candidate_reasons[index] if is_first_violation else []
        row["wrong"] = is_first_violation
        row["adjudication"] = (
            "first_violation"
            if is_first_violation
            else ("not_attributed_after_first_violation" if candidate_reasons[index] else "correct")
        )

    unresolved = [
        player_ref(players, actor_map, player_id)
        for player_id in targets
        if not any(row["playerID"] == player_id for row in breaks)
    ]
    wrong_players = [breaks[first_violation_index]] if first_violation_index is not None else []
    rounds = [{
        "index": 1,
        "time": fmt_ms(start - fight["startTime"]),
        "targetCount": len(targets),
        "targets": [player_ref(players, actor_map, player_id) for player_id in targets],
        "sides": [
            {
                "side": group["side"],
                "applyTime": fmt_ms(group["timestamp"] - fight["startTime"]),
                "wardenInstance": group["wardenInstance"],
                "positionX": group["positionX"],
                "sideSource": group["sideSource"],
                "targets": [player_ref(players, actor_map, event.get("targetID")) for event in group["events"]],
            }
            for group in apply_groups
        ],
        "firstBreakSide": first_side,
        "firstBreakTime": fmt_ms(first_time - fight["startTime"]) if first_time is not None else None,
        "blightClearTime": fmt_ms(first_clear - fight["startTime"]) if first_clear is not None else None,
        "secondBreakSide": opposite_side,
        "secondBreakTime": fmt_ms(second_time - fight["startTime"]) if second_time is not None else None,
        "breaks": breaks,
        "unresolved": unresolved,
        "violationPlayers": wrong_players,
        "overLimitPlayers": wrong_players,
        "firstViolation": wrong_players[0] if wrong_players else None,
        "bossInitialPosition": ({
            "x": boss_boundary_x,
            "y": float(boss_spawn["y"]),
            "time": fmt_ms(int(boss_spawn["timestamp"]) - fight["startTime"]),
        } if boss_spawn else None),
        "maxBlightStack": max((row["toStack"] or 0 for row in breaks), default=0),
        "wrongBreakCount": len(wrong_players),
    }]
    return {
        "batchWindowSec": FANG_BATCH_WINDOW_MS // 1000,
        "rounds": rounds,
        "wrongBreakCount": sum(row["wrongBreakCount"] for row in rounds),
        "maxBlightStack": max((row["maxBlightStack"] for row in rounds), default=0),
    }


def _analyze_malice(fight, actor_map, raw):
    begins = [
        event for event in raw["casts"]
        if int(ability_id(event) or 0) == 1290779 and event_type(event) == "begincast"
    ]
    completes = completed_casts(raw["casts"], 1290779)
    rows = []
    for event in begins:
        timestamp = int(event["timestamp"])
        completed = next(
            (
                row for row in completes
                if row.get("sourceID") == event.get("sourceID")
                and timestamp <= int(row.get("timestamp") or 0) <= timestamp + 8000
            ),
            None,
        )
        rows.append({
            "time": fmt_ms(timestamp - fight["startTime"]),
            "source": source_name(actor_map, event.get("sourceID"), SOURCE_NAMES) or "厄鳞守卫",
            "completed": bool(completed),
            "prevented": not completed,
        })
    return {
        "spellID": 1290779,
        "castCount": len(begins),
        "preventedCount": sum(row["prevented"] for row in rows),
        "completedCount": sum(row["completed"] for row in rows),
        "casts": rows,
    }


def _death_row(fight, actor_map, players, raw, event):
    timestamp = int(event.get("timestamp") or 0)
    player_id = event.get("targetID")
    defensive = find_defensive_uses_before_death(
        raw["friendlyCasts"],
        death_timestamp=timestamp,
        player_id=player_id,
        lookback_ms=15_000,
    )
    consumables = []
    for cast in raw["friendlyCasts"]:
        spell_id = int(ability_id(cast) or 0)
        cast_time = int(cast.get("timestamp") or 0)
        if cast.get("sourceID") != player_id or not timestamp - 20_000 <= cast_time <= timestamp:
            continue
        if spell_id in HEALTHSTONE_IDS:
            kind, name = "healthstone", "治疗石"
        elif spell_id in HEALING_POTION_IDS:
            kind, name = "healing_potion", spell_name(spell_id, GUIDE_SPELLS)
            if name == "未知技能":
                name = "生命治疗药水"
        else:
            continue
        consumables.append({
            "kind": kind,
            "spellID": spell_id,
            "spellName": name,
            "time": fmt_ms(cast_time - fight["startTime"]),
            "msBeforeDeath": timestamp - cast_time,
        })
    ability_id_value = int(event.get("killingAbilityGameID") or ability_id(event) or 0)
    personal = defensive.get("personalDefensives") or []
    return {
        **player_ref(players, actor_map, player_id),
        "time": fmt_ms(timestamp - fight["startTime"]),
        "abilityID": ability_id_value,
        "ability": spell_name(ability_id_value, GUIDE_SPELLS),
        "usedPersonalDefensive": bool(personal),
        "personalDefensiveWindowMs": 15_000,
        "personalDefensiveCriterion": "death-preceding-cast-record",
        "personalDefensives": personal,
        "usedHealthstone": any(row["kind"] == "healthstone" for row in consumables),
        "usedHealingPotion": any(row["kind"] == "healing_potion" for row in consumables),
        "consumables": consumables,
    }


def _analyze_critical(fight, actor_map, players, raw):
    melee_by_player = defaultdict(list)
    for event in raw["damage"]:
        player_id = event.get("targetID")
        if int(ability_id(event) or 0) != 1 or player_id not in players:
            continue
        if players[player_id].get("role") == "tank":
            continue
        # Misses, dodges and immunes can still arrive as damage-table rows. The
        # requested metric is players actually hit by melee, so require damage.
        if _amount(event) <= 0:
            continue
        melee_by_player[player_id].append(event)
    melee_players = []
    for player_id, events in melee_by_player.items():
        sources = Counter(source_name(actor_map, event.get("sourceID"), SOURCE_NAMES) for event in events)
        melee_players.append({
            **player_ref(players, actor_map, player_id),
            "hitCount": len(events),
            "totalDamage": sum(_amount(event) for event in events),
            "sources": [{"source": name, "count": count} for name, count in sources.most_common()],
            "events": [
                {
                    "time": fmt_ms(int(event["timestamp"]) - fight["startTime"]),
                    "amount": _amount(event),
                    "source": source_name(actor_map, event.get("sourceID"), SOURCE_NAMES),
                }
                for event in events
            ],
        })
    melee_players.sort(key=lambda row: (row["totalDamage"], row["hitCount"]), reverse=True)

    wrath_casts = sorted(completed_casts(raw["casts"], 1298367), key=lambda row: int(row["timestamp"]))
    wrath_damage = [
        event for event in raw["damage"]
        if int(ability_id(event) or 0) in {1298369, 1301122}
        and event.get("targetID") in players
        and _amount(event) > 0
    ]
    mother_wrath_failures = []
    for index, event in enumerate(wrath_casts, start=1):
        timestamp = int(event["timestamp"])
        next_timestamp = int(wrath_casts[index]["timestamp"]) if index < len(wrath_casts) else fight["endTime"]
        window_end = min(timestamp + 12_000, next_timestamp)
        damage_events = [
            row for row in wrath_damage
            if timestamp - 250 <= int(row.get("timestamp") or 0) < window_end
        ]
        affected_ids = sorted({row.get("targetID") for row in damage_events if row.get("targetID") in players})

        # 正常处理是同一名坦克连续承受多跳；圈内无人时才会扩散至全团。
        # 使用“至少 3 名不同玩家”作为扩散证据，避免把坦克的 9 连击误判为 A 团。
        if len(affected_ids) < 3:
            continue

        receiver_id = event.get("targetID") if event.get("targetID") in players else None
        receiver_evidence = "蛇母之怒施法目标" if receiver_id is not None else None
        evidence_delta_ms = 0 if receiver_id is not None else None
        if receiver_id is None:
            source_id = event.get("sourceID")
            recent_melee = max(
                (
                    row for row in raw["damage"]
                    if int(ability_id(row) or 0) == 1
                    and row.get("targetID") in players
                    and row.get("sourceID") == source_id
                    and timestamp - 8_000 <= int(row.get("timestamp") or 0) <= timestamp
                ),
                key=lambda row: int(row.get("timestamp") or 0),
                default=None,
            )
            if recent_melee is not None:
                receiver_id = recent_melee.get("targetID")
                receiver_evidence = "施法前 Boss 最近一次近战目标"
                evidence_delta_ms = timestamp - int(recent_melee.get("timestamp") or 0)

        first_damage_time = min(int(row.get("timestamp") or timestamp) for row in damage_events)
        mother_wrath_failures.append({
            "index": index,
            "time": fmt_ms(timestamp - fight["startTime"]),
            "damageTime": fmt_ms(first_damage_time - fight["startTime"]),
            "spellID": 1298367,
            "receiver": player_ref(players, actor_map, receiver_id) if receiver_id is not None else None,
            "receiverEvidence": receiver_evidence or "未取得施法目标或近期近战目标",
            "evidenceDeltaMs": evidence_delta_ms,
            "affectedCount": len(affected_ids),
            "affectedPlayers": [player_ref(players, actor_map, player_id) for player_id in affected_ids],
            "hitCount": len(damage_events),
            "totalDamage": sum(_amount(row) for row in damage_events),
            "damageSpellIDs": sorted({int(ability_id(row) or 0) for row in damage_events}),
        })

    shatters = completed_casts(raw["casts"], 1315341)
    bites = completed_casts(raw["casts"], 1295905)
    transitions = []
    previous_end = 0
    for index, shatter in enumerate(sorted(shatters, key=lambda row: int(row["timestamp"])), start=1):
        shatter_time = int(shatter["timestamp"])
        bite = max(
            (
                row for row in bites
                if previous_end < int(row.get("timestamp") or 0) <= shatter_time
            ),
            key=lambda row: int(row.get("timestamp") or 0),
            default=None,
        )
        start = int(bite["timestamp"]) if bite else shatter_time - 30_000
        end = shatter_time + 3000
        deaths = [
            _death_row(fight, actor_map, players, raw, event)
            for event in raw["deaths"]
            if start <= int(event.get("timestamp") or 0) <= end
        ]
        transitions.append({
            "index": index,
            "label": f"第 {index} 次碎场流程",
            "startTime": fmt_ms(start - fight["startTime"]),
            "endTime": fmt_ms(end - fight["startTime"]),
            "shatterTime": fmt_ms(shatter_time - fight["startTime"]),
            "deathCount": len(deaths),
            "deaths": deaths,
        })
        previous_end = shatter_time
    focus = transitions[1] if len(transitions) >= 2 else None
    coiled_prey_deaths = [
        _death_row(fight, actor_map, players, raw, event)
        for event in raw.get("deaths") or []
        if int(event.get("killingAbilityGameID") or ability_id(event) or 0) == 1301510
    ]
    return {
        "malice": _analyze_malice(fight, actor_map, raw),
        "nonTankMelee": {
            "hitCount": sum(row["hitCount"] for row in melee_players),
            "totalDamage": sum(row["totalDamage"] for row in melee_players),
            "players": melee_players,
        },
        "motherWrath": {
            "castCount": len(wrath_casts),
            "raidWideFailureCount": len(mother_wrath_failures),
            "raidWideTargetThreshold": 3,
            "failures": mother_wrath_failures,
        },
        "platformTransitions": transitions,
        "platform2To3": focus,
        "serpentBites": _analyze_serpent_bites(fight, actor_map, players, raw),
        "p25Eggs": _analyze_p25_eggs(fight, actor_map, players, raw),
        "coiledPreyDeaths": {
            "spellID": 1301510,
            "deathCount": len(coiled_prey_deaths),
            "deaths": coiled_prey_deaths,
        },
    }


def analyze_ulatek(fight, actor_map, players, raw):
    options = resolve_analysis_options(CONFIG_SCHEMA, raw.get("analysisOptions") or {})
    rage_windows = _rage_windows(fight, raw)
    waves = _analyze_waves_and_eggs(fight, actor_map, players, raw, rage_windows) if options["wavesReviewEnabled"] else {}
    if waves:
        waves["p3Eggs"] = _analyze_p3_eggs(fight, actor_map, players, raw, rage_windows)
    return {
        "wavesAndEggs": waves,
        "rage": _analyze_rage(fight, actor_map, players, raw, rage_windows) if options["rageReviewEnabled"] else {},
        "fangs": _analyze_fangs(fight, actor_map, players, raw) if options["fangsReviewEnabled"] else {},
        "critical": _analyze_critical(fight, actor_map, players, raw) if options["criticalReviewEnabled"] else {},
    }


analyze_mechanics = analyze_ulatek


def _mechanic_overview(rendered):
    wave_hits = []
    egg_hits = []
    p1_wave_deaths = []
    p3_wave_deaths = []
    wrong_breaks = []
    coiled_prey_deaths = []
    focus_deaths = []
    melee_events = []
    melee_damage = 0
    mother_wrath_failures = []
    p25_egg_deaths, p25_egg_remaining = [], []
    for pull in rendered:
        mechanics = pull.get(BOSS_CONFIG["key"]) or {}
        egg_review = (mechanics.get("critical") or {}).get("p25Eggs") or {}
        for key, target, label in (("deaths", p25_egg_deaths, "P2.5 连续分摊期间带蛋死亡"),
                                   ("remaining", p25_egg_remaining, "P2.5 分摊结束仍携蛋（玩家失误）")):
            for row in egg_review.get(key, []):
                target.append(nightly_detail(pull, row["time"], f"{row['player']}：{label}",
                                             player=row["player"], playerID=row["playerID"], classColor=row.get("classColor"),
                                             spellID=EGG_CARRY_ID, isPlayerMistake=key == "remaining"))
        for row in (mechanics.get("wavesAndEggs") or {}).get("hits") or []:
            event = nightly_detail(
                pull,
                row.get("time"),
                f"{row.get('player') or '未知玩家'} 命中腐蚀浪潮",
                player=row.get("player"),
                classColor=row.get("classColor"),
                spellID=WAVE_ID,
            )
            wave_hits.append(event)
            if row.get("eggCarrier"):
                egg_hits.append({**event, "text": f"{row.get('player')} 携带蛇卵命中腐蚀浪潮"})
        for row in (((mechanics.get("wavesAndEggs") or {}).get("waveDeaths") or {}).get("events") or []):
            event = nightly_detail(
                pull,
                row.get("deathTime"),
                f"{row.get('player')} 在 {row.get('phase')} 中波后 1 秒内死亡（{row.get('ability')}）",
                player=row.get("player"),
                classColor=row.get("classColor"),
                spellID=row.get("abilityID"),
                waveTime=row.get("waveTime"),
                delayMs=row.get("delayMs"),
            )
            if row.get("phase") == "P1":
                p1_wave_deaths.append(event)
            elif row.get("phase") == "P3":
                p3_wave_deaths.append(event)
        for fang_round in (mechanics.get("fangs") or {}).get("rounds") or []:
            for row in fang_round.get("breaks") or []:
                if not row.get("wrong"):
                    continue
                wrong_breaks.append(nightly_detail(
                    pull,
                    row.get("time"),
                    f"{row.get('player')} 违反拉线逻辑：{'、'.join(row.get('violationReasons') or ['未知原因'])}",
                    player=row.get("player"),
                    classColor=row.get("classColor"),
                    spellID=BLIGHT_VEIN_ID,
                ))
        for row in (((mechanics.get("critical") or {}).get("coiledPreyDeaths") or {}).get("deaths") or []):
            coiled_prey_deaths.append(nightly_detail(
                pull,
                row.get("time"),
                f"{row.get('player')} 死于盘绕猎物",
                player=row.get("player"),
                classColor=row.get("classColor"),
                spellID=1301510,
            ))
        focus = (mechanics.get("critical") or {}).get("platform2To3") or {}
        for row in focus.get("deaths") or []:
            status = "已开个人减伤" if row.get("usedPersonalDefensive") else "未记录个人减伤"
            focus_deaths.append(nightly_detail(
                pull,
                row.get("time"),
                f"{row.get('player')} 在第2→第3平台流程死亡（{status}）",
                player=row.get("player"),
                classColor=row.get("classColor"),
                spellID=row.get("abilityID"),
                usedPersonalDefensive=bool(row.get("usedPersonalDefensive")),
                usedHealthstone=bool(row.get("usedHealthstone")),
                usedHealingPotion=bool(row.get("usedHealingPotion")),
            ))
        melee = (mechanics.get("critical") or {}).get("nonTankMelee") or {}
        melee_damage += int(melee.get("totalDamage") or 0)
        for player_row in melee.get("players") or []:
            for event in player_row.get("events") or []:
                melee_events.append(nightly_detail(
                    pull,
                    event.get("time"),
                    f"{player_row.get('player')} 被 {event.get('source')} 近战攻击",
                    player=player_row.get("player"),
                    classColor=player_row.get("classColor"),
                    spellID=1,
                    amount=event.get("amount"),
                ))
        wrath = (mechanics.get("critical") or {}).get("motherWrath") or {}
        for row in wrath.get("failures") or []:
            receiver = row.get("receiver") or {}
            receiver_name = receiver.get("player") or "未解析目标"
            mother_wrath_failures.append(nightly_detail(
                pull,
                row.get("time"),
                f"蛇母之怒触发全团伤害；当轮承接目标：{receiver_name}",
                player=receiver.get("player"),
                classColor=receiver.get("classColor"),
                spellID=1298367,
                affectedCount=row.get("affectedCount"),
                totalDamage=row.get("totalDamage"),
                receiverEvidence=row.get("receiverEvidence"),
            ))
    return {
        "title": "整夜机制统计",
        "subtitle": "按全部乌拉特克 Pull 汇总腐蚀浪潮、P1/P3 中波死亡、带蛋、拉线、盘绕猎物、蛇母之怒 A 团、平台减伤与非坦克近战证据。",
        "metrics": [
            {"key": "p25EggDeaths", "label": "P2.5 带蛋死亡", "value": len(p25_egg_deaths), "unit": "人次",
             "tone": "warning", "players": nightly_player_totals(p25_egg_deaths), "events": p25_egg_deaths},
            {"key": "p25EggRemaining", "label": "P2.5 分摊结束仍携蛋", "value": len(p25_egg_remaining), "unit": "次",
             "tone": "danger", "description": "六次连续分摊结束后仍存活且携蛋，每名玩家每场计一次失误。",
             "players": nightly_player_totals(p25_egg_remaining), "events": p25_egg_remaining},
            {
                "key": "waveHits",
                "label": "中波施加/刷新次数",
                "value": len(wave_hits),
                "unit": "次",
                "tone": "warning",
                "players": nightly_player_totals(wave_hits),
                "events": wave_hits,
            },
            {
                "key": "p1WaveDeaths",
                "label": "P1 吃波死亡",
                "value": len(p1_wave_deaths),
                "unit": "人次",
                "tone": "danger",
                "players": nightly_player_totals(p1_wave_deaths),
                "events": p1_wave_deaths,
            },
            {
                "key": "p3WaveDeaths",
                "label": "P3 吃波死亡",
                "value": len(p3_wave_deaths),
                "unit": "人次",
                "tone": "danger",
                "players": nightly_player_totals(p3_wave_deaths),
                "events": p3_wave_deaths,
            },
            {
                "key": "eggCarrierWaveHits",
                "label": "带蛋中波次数",
                "value": len(egg_hits),
                "unit": "次",
                "tone": "danger",
                "players": nightly_player_totals(egg_hits),
                "events": egg_hits,
            },
            {
                "key": "wrongFangBreaks",
                "label": "违反拉线逻辑",
                "value": len(wrong_breaks),
                "unit": "次",
                "tone": "danger",
                "players": nightly_player_totals(wrong_breaks),
                "events": wrong_breaks,
            },
            {
                "key": "coiledPreyDeaths",
                "label": "死于盘绕猎物",
                "value": len(coiled_prey_deaths),
                "unit": "人次",
                "tone": "danger",
                "players": nightly_player_totals(coiled_prey_deaths),
                "events": coiled_prey_deaths,
            },
            {
                "key": "platform2To3Defensives",
                "label": "第2→第3平台死亡减伤检查",
                "value": len(focus_deaths),
                "unit": "人次",
                "tone": "warning",
                "players": nightly_player_totals(focus_deaths),
                "events": focus_deaths,
            },
            {
                "key": "nonTankMelee",
                "label": "非坦克被近战攻击",
                "value": len(melee_events),
                "unit": "次",
                "tone": "danger",
                "totalDamage": melee_damage,
                "players": nightly_player_totals(melee_events),
                "events": melee_events,
            },
            {
                "key": "motherWrathRaidwide",
                "label": "蛇母之怒 A 团",
                "value": len(mother_wrath_failures),
                "unit": "次",
                "tone": "danger",
                "players": nightly_player_totals(mother_wrath_failures),
                "events": mother_wrath_failures,
            },
        ],
    }


def build_aggregated_json(report_ids, options=None):
    options = resolve_analysis_options(CONFIG_SCHEMA, options or {})
    config = deepcopy(BOSS_CONFIG)
    config["trackedDamageTargetGameIDs"] = set()
    if options["rageReviewEnabled"]:
        config["trackedDamageTargetGameIDs"].update({ULATEK_GAME_ID, HEART_GAME_ID})
    if options["wavesReviewEnabled"]:
        config["trackedDamageTargetGameIDs"].add(DEVOURERS_SPAWN_GAME_ID)
    config["trackedActorGameIDs"] = {BLIGHTSCALE_SHRIEKER_GAME_ID} if options["wavesReviewEnabled"] else set()
    config["fetchPositionResources"] = bool(
        options["wavesReviewEnabled"]
        or options["criticalReviewEnabled"]
        or options["fangsReviewEnabled"]
    )
    if not any(options.values()):
        config["fetchKeys"] = {"friendlyCasts", "deaths", "combatants"}
        config["fetchPositionResources"] = False
        config["trackedActorGameIDs"] = set()
        config["trackedActorEventFilters"] = []
        config["trackedDamageTargetGameIDs"] = set()
        config["tabs"] = [row for row in config["tabs"] if row[0] == "survival"]
    config["skippedAnalyses"] = [field["label"] for field in CONFIG_SCHEMA if not options[field["key"]]]
    config["tabs"] = [row for row in config["tabs"] if row[0] == "survival" or options[{"waves":"wavesReviewEnabled", "heart":"rageReviewEnabled", "fangs":"fangsReviewEnabled", "critical":"criticalReviewEnabled"}[row[0]]]]
    result = _build(config, analyze_mechanics, report_ids, options)
    result["meta"]["courtProfile"] = COURT_PROFILE
    result["data"]["mechanicOverview"] = _mechanic_overview(
        result.get("data", {}).get("page1_wipeAnalysis") or []
    )
    metric_options = {
        "p25EggDeaths": "criticalReviewEnabled", "p25EggRemaining": "criticalReviewEnabled",
        "waveHits": "wavesReviewEnabled", "p1WaveDeaths": "wavesReviewEnabled", "p3WaveDeaths": "wavesReviewEnabled", "eggCarrierWaveHits": "wavesReviewEnabled",
        "wrongFangBreaks": "fangsReviewEnabled", "platform2To3Defensives": "criticalReviewEnabled",
        "coiledPreyDeaths": "criticalReviewEnabled", "nonTankMelee": "criticalReviewEnabled", "motherWrathRaidwide": "criticalReviewEnabled",
    }
    result["data"]["mechanicOverview"]["metrics"] = [
        row for row in result["data"]["mechanicOverview"]["metrics"] if options[metric_options[row["key"]]]
    ]
    return result


def analyze(report_ids, output_path=None, catalog_entry=None, options=None, progress_callback=None):
    return write_json_result(
        build_aggregated_json(report_ids, options), output_path, catalog_entry=catalog_entry
    )
