"""Evidence-first analyzer for the Twin Fangs."""

from __future__ import annotations

from collections import Counter, defaultdict

from boss_plugins.venomous_abyss.runtime import analyze_boss, build_aggregated_json as _build
from boss_plugins.venomous_abyss.shared import (
    ability_id,
    active_immunities,
    completed_casts as _completed_casts,
    death_near as _death_near,
    event_type,
    events_between as _events_between,
    fmt_ms,
    group_nearby,
    load_confirmed_spell_names,
    player_ref,
    spell_name,
)

GUIDE_SPELLS = load_confirmed_spell_names()

BOSS_CONFIG = {
    "key": "twinfangs",
    "encounterIDs": {3421},
    "name": "双子毒牙",
    "arena": "assets/raids/venomous_abyss/06-twinfangs.jpg",
    "spellNames": GUIDE_SPELLS,
    "tabs": [
        ["survival", "全场存活情况"],
        ["venom", "永恒毒液"],
        ["globules", "地板炸圈"],
        ["mythic", "史诗难度占位"],
    ],
    "mechanicVersion": "twinfangs-progression-2026-08-28",
    "features": {"survival": True, "fieldReplay": False},
}

VENOM_GAIN_DAMAGE = {
    1289201: "腐蚀液滴",
    1291404: "剧毒涌现",
    1308122: "剧毒涌现",
    1291478: "腐蚀唾液",
    1293295: "腐蚀唾液",
    1293979: "腐蚀唾液",
}

VENOM_ABNORMAL_DAMAGE = {
    1289994: "腐蚀洪流",
    1290338: "腐蚀液滴爆裂",
    1292806: "搅动深渊",
    1292807: "搅动深渊",
    1293749: "邪恶洪流",
    1294293: "邪恶洪流",
    1294605: "邪恶洪流",
}

FEAST_IDS = {1290516, 1290654, 1290662, 1310211}

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
    direct_cast = min(
        (cast for cast in casts if int(ability_id(cast) or 0) == 1290336
         and abs(int(cast.get("timestamp") or 0) - timestamp) <= 5000),
        key=lambda cast: abs(int(cast.get("timestamp") or 0) - timestamp),
        default=None,
    )
    if direct_cast:
        return "Boss 直接叠层", 1290336, "normal"
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
        eaten_counts = Counter(event.get("targetID") for event in hits if event.get("targetID") in players)
        alive = [player_id for player_id in players if death_times[player_id] >= start]
        eaten_rows = []
        for player_id in sorted(eaten_counts, key=lambda item: (-eaten_counts[item], item)):
            count = eaten_counts[player_id]
            eaten_rows.append({**player_ref(players, actor_map, player_id), "count": count, "abnormal": count > 1})
        missed_rows = [player_ref(players, actor_map, player_id) for player_id in alive if player_id not in eaten_counts]
        globule_rounds.append({"index": index, "timeMs": start - fight["startTime"], "time": fmt_ms(start - fight["startTime"]),
                               "endTime": fmt_ms(end - fight["startTime"]), "participantCount": len(participants),
                               "participants": [player_ref(players, actor_map, player_id) for player_id in participants],
                               "hitCount": len(hits), "exploded": bool(explosions), "explosionTime": fmt_ms(explosion_ts - fight["startTime"]) if explosion_ts else None,
                               "nonParticipants": missing,
                               "teamSize": len(players), "aliveCount": len(alive), "ballCount": len(hits),
                               "eaten": eaten_rows, "missed": missed_rows,
                               "abnormal": [row for row in eaten_rows if row["abnormal"]]})
    abnormal_gains = []
    for history in histories:
        for row in history["events"]:
            if row.get("category") == "abnormal" and row.get("delta", 0) > 0:
                abnormal_gains.append({
                    "playerID": history["playerID"], "player": history["player"],
                    "classColor": history.get("classColor"), "icon": history.get("icon"), "role": history.get("role"),
                    "timeMs": row["timeMs"], "time": row["time"], "delta": row["delta"], "toStack": row["toStack"],
                    "source": row["source"], "sourceID": row["sourceID"],
                })
    return {
        "eternalVenom": {"players": histories, "feastChecks": feast_checks, "abnormalGains": abnormal_gains},
        "globules": {"rounds": globule_rounds},
        "mythicPlaceholder": "该部分暂时没有可用的信息。",
    }

analyze_mechanics = analyze_twinfangs


def build_aggregated_json(report_ids, options=None):
    return _build(BOSS_CONFIG, analyze_mechanics, report_ids, options)


def analyze(report_ids, output_path=None, catalog_entry=None, options=None, progress_callback=None):
    return analyze_boss(
        BOSS_CONFIG, analyze_mechanics, report_ids, output_path, catalog_entry, options
    )
