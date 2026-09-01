"""Evidence-first analyzer for Ula'tek."""

from __future__ import annotations

from collections import Counter, defaultdict

from analyzer_core.court_rules import validate_court_profile
from boss_plugins.combat_config import PERSONAL_DEFENSIVES, find_defensive_uses_before_death
from boss_plugins.common import write_json_result
from boss_plugins.venomous_abyss.runtime import build_aggregated_json as _build
from boss_plugins.venomous_abyss.shared import (
    ability_id,
    completed_casts,
    event_type,
    fmt_ms,
    load_confirmed_spell_names,
    load_confirmed_source_names,
    nightly_detail,
    nightly_player_totals,
    player_ref,
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
FANG_AURA_ID = 1311611
BLIGHT_VEIN_ID = 1311609
SAFE_BLIGHT_STACK = 2
HEALTHSTONE_IDS = {6262, 452930, 387636}
HEALING_POTION_IDS = {1234768, 1295247}

BOSS_CONFIG = {
    "key": "ulatek",
    "encounterIDs": {3492, 53492},
    "name": "乌拉特克",
    "arena": "assets/raids/venomous_abyss/08-ulatek-arena.jpg",
    "spellNames": GUIDE_SPELLS,
    "trackedDamageTargetGameIDs": {267460},
    "tabs": [
        ["survival", "全场存活情况"],
        ["waves", "腐蚀浪潮和带蛋情况"],
        ["heart", "被缚之怒"],
        ["fangs", "攫取毒牙处理"],
        ["critical", "关键流程问题"],
    ],
    "mechanicVersion": "ulatek-progression-2026-09-01-v2",
    "features": {"survival": True, "fieldReplay": False},
}

COURT_PROFILE = {
    "bossKey": "ulatek",
    "phaseModel": "cast_and_aura_timeline",
    "phaseRule": "P1/P2/P3 以被缚之怒结束点切分；最终碎场轮次以盘绕猎物施法切分。",
    "rules": [
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
            "label": "攫取毒牙拉断使凋萎静脉超过安全层数",
            "mode": "direct",
            "spellIDs": [1311611, 1311609],
            "requiredEvidence": ["攫取毒牙移除", "同毫秒凋萎静脉层数"],
            "defaultCountEnabled": True,
            "severityUnits": 1,
        },
        {
            "key": "non_tank_mother_wrath",
            "label": "蛇母之怒命中非坦克目标",
            "mode": "direct",
            "spellIDs": [1298367, 1298369, 1301122],
            "requiredEvidence": ["蛇母之怒完成施法目标", "本场职责"],
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


def _analyze_waves_and_eggs(fight, actor_map, players, raw, rage_windows):
    egg_intervals = _aura_intervals(raw["debuffs"], EGG_CARRY_ID, fight["endTime"])
    hatch_changes = _raid_aura_changes(raw["debuffs"], 1301268)
    wave_applies = [
        event for event in raw["debuffs"]
        if int(ability_id(event) or 0) == WAVE_ID
        and event.get("targetID") in players
        and event_type(event) in {"applydebuff", "applydebuffstack", "refreshdebuff"}
    ]
    # A single contact can be emitted as applydebuff + applydebuffstack/refresh in
    # the same combat-log frame. Count the contact once, rather than counting the
    # transport-level aura mutations as separate wave hits.
    distinct_wave_applies = []
    last_contact_by_player = {}
    for event in sorted(wave_applies, key=lambda row: int(row.get("timestamp") or 0)):
        player_id = event.get("targetID")
        timestamp = int(event.get("timestamp") or 0)
        if timestamp - last_contact_by_player.get(player_id, -10_000) <= 500:
            continue
        last_contact_by_player[player_id] = timestamp
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
        "eggCarrierHitCount": sum(row["eggCarrier"] for row in hits),
        "earlyHatchCount": sum(row["earlyHatchConfirmed"] for row in hits),
        "hits": hits,
        "carries": carries,
    }


def _analyze_rage(fight, actor_map, players, raw, rage_windows):
    rounds = []
    for index, window in enumerate(rage_windows, start=1):
        start, end = window["start"], window["end"]
        heart_damage = [
            event for event in raw.get("trackedDamageTaken") or []
            if start <= int(event.get("timestamp") or 0) <= end
        ]
        by_player = defaultdict(lambda: {"damage": 0, "hits": 0})
        for event in heart_damage:
            player_id = event.get("sourceID")
            if player_id not in players:
                continue
            by_player[player_id]["damage"] += _amount(event)
            by_player[player_id]["hits"] += 1
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
            "heartDamage": sum(_amount(event) for event in heart_damage),
            "heartDamageByPlayer": sorted(
                [
                    {
                        **player_ref(players, actor_map, player_id),
                        "damage": values["damage"],
                        "hitCount": values["hits"],
                    }
                    for player_id, values in by_player.items()
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
    return {"rounds": rounds, "totalDeathCount": sum(row["deathCount"] for row in rounds)}


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
        return {"safeStack": SAFE_BLIGHT_STACK, "rounds": [], "wrongBreakCount": 0, "maxBlightStack": 0}

    # This mechanic is one assignment per fight.  The two Wardens can apply the
    # six debuffs about 1.2 s apart, so grouping by transport timestamp would
    # incorrectly split one assignment into two rounds.
    start = min(int(event["timestamp"]) for event in applies)
    targets = {}
    for event in sorted(applies, key=lambda row: int(row["timestamp"])):
        targets.setdefault(event.get("targetID"), int(event["timestamp"]))
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
                "wrong": row_to > SAFE_BLIGHT_STACK,
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
            "wrong": False,
            "evidenceMissing": True,
        })
    breaks.sort(key=lambda row: (row["time"], row["player"]))
    unresolved = [
        player_ref(players, actor_map, player_id)
        for player_id in targets
        if not any(row["playerID"] == player_id for row in breaks)
    ]
    wrong_players = [row for row in breaks if row["wrong"]]
    rounds = [{
        "index": 1,
        "time": fmt_ms(start - fight["startTime"]),
        "targetCount": len(targets),
        "targets": [player_ref(players, actor_map, player_id) for player_id in targets],
        "breaks": breaks,
        "unresolved": unresolved,
        "overLimitPlayers": wrong_players,
        "maxBlightStack": max((row["toStack"] or 0 for row in breaks), default=0),
        "wrongBreakCount": len(wrong_players),
    }]
    return {
        "safeStack": SAFE_BLIGHT_STACK,
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

    mother_wrath = []
    for event in completed_casts(raw["casts"], 1298367):
        target_id = event.get("targetID")
        if target_id not in players or players[target_id].get("role") == "tank":
            continue
        timestamp = int(event["timestamp"])
        mother_wrath.append({
            **player_ref(players, actor_map, target_id),
            "time": fmt_ms(timestamp - fight["startTime"]),
            "spellID": 1298367,
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
    return {
        "malice": _analyze_malice(fight, actor_map, raw),
        "nonTankMelee": {
            "hitCount": sum(row["hitCount"] for row in melee_players),
            "totalDamage": sum(row["totalDamage"] for row in melee_players),
            "players": melee_players,
        },
        "nonTankMotherWrath": {
            "castCount": len(mother_wrath),
            "casts": mother_wrath,
        },
        "platformTransitions": transitions,
        "platform2To3": focus,
    }


def analyze_ulatek(fight, actor_map, players, raw):
    rage_windows = _rage_windows(fight, raw)
    return {
        "wavesAndEggs": _analyze_waves_and_eggs(fight, actor_map, players, raw, rage_windows),
        "rage": _analyze_rage(fight, actor_map, players, raw, rage_windows),
        "fangs": _analyze_fangs(fight, actor_map, players, raw),
        "critical": _analyze_critical(fight, actor_map, players, raw),
    }


analyze_mechanics = analyze_ulatek


def _mechanic_overview(rendered):
    wave_hits = []
    egg_hits = []
    wrong_breaks = []
    focus_deaths = []
    melee_events = []
    melee_damage = 0
    for pull in rendered:
        mechanics = pull.get(BOSS_CONFIG["key"]) or {}
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
        for fang_round in (mechanics.get("fangs") or {}).get("rounds") or []:
            for row in fang_round.get("breaks") or []:
                if not row.get("wrong"):
                    continue
                wrong_breaks.append(nightly_detail(
                    pull,
                    row.get("time"),
                    f"{row.get('player')} 拉断后凋萎静脉达到 {row.get('blightStack')} 层",
                    player=row.get("player"),
                    classColor=row.get("classColor"),
                    spellID=BLIGHT_VEIN_ID,
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
    return {
        "title": "整夜机制统计",
        "subtitle": "按全部乌拉特克 Pull 汇总腐蚀浪潮、带蛋、拉断、平台减伤与非坦克近战证据。",
        "metrics": [
            {
                "key": "waveHits",
                "label": "中波次数",
                "value": len(wave_hits),
                "unit": "次",
                "tone": "warning",
                "players": nightly_player_totals(wave_hits),
                "events": wave_hits,
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
                "label": "攫取毒牙错误拉断",
                "value": len(wrong_breaks),
                "unit": "次",
                "tone": "danger",
                "players": nightly_player_totals(wrong_breaks),
                "events": wrong_breaks,
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
        ],
    }


def build_aggregated_json(report_ids, options=None):
    result = _build(BOSS_CONFIG, analyze_mechanics, report_ids, options)
    result["meta"]["courtProfile"] = COURT_PROFILE
    result["data"]["mechanicOverview"] = _mechanic_overview(
        result.get("data", {}).get("page1_wipeAnalysis") or []
    )
    return result


def analyze(report_ids, output_path=None, catalog_entry=None, options=None, progress_callback=None):
    return write_json_result(
        build_aggregated_json(report_ids, options), output_path, catalog_entry=catalog_entry
    )
