"""Evidence-first analyzer for the Lost Explorers."""

from __future__ import annotations

from collections import Counter, defaultdict

from boss_plugins.common import COMBAT_RES_SPELLS
from boss_plugins.venomous_abyss.runtime import analyze_boss, build_aggregated_json as _build
from boss_plugins.venomous_abyss.shared import (
    IMMUNITY_SPELLS,
    ability_id,
    active_immunities,
    actor_name,
    avoidable_board as _avoidable_board,
    completed_casts as _completed_casts,
    event_amount,
    event_type,
    events_between as _events_between,
    fmt_ms,
    group_nearby,
    load_confirmed_source_names,
    load_confirmed_spell_names,
    player_ref,
    source_name,
    spell_name,
)

GUIDE_SPELLS = load_confirmed_spell_names()
SOURCE_NAMES = load_confirmed_source_names()

BOSS_CONFIG = {
    "key": "lostexplorers",
    "encounterIDs": {3497},
    "name": "迷失的探险者",
    "arena": "assets/raids/venomous_abyss/04-lostexplorers.jpg",
    "spellNames": GUIDE_SPELLS,
    "tabs": [
        ["survival", "全场存活情况"],
        ["defense", "联合防御 / 投掷垃圾"],
        ["avoidable", "可规避机制"],
        ["special", "特殊技能处理"],
    ],
    "mechanicVersion": "lostexplorers-progression-2026-08-28",
    "features": {"survival": True, "fieldReplay": False},
}

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

def _immunity_intervals(buff_events, fight_end):
    """Build player immunity windows from WCL aura events."""
    active = {}
    intervals = defaultdict(list)
    for event in sorted(buff_events, key=lambda row: int(row.get("timestamp") or 0)):
        spell_id = int(ability_id(event) or 0)
        player_id = event.get("targetID")
        if spell_id not in IMMUNITY_SPELLS or player_id is None:
            continue
        timestamp = int(event.get("timestamp") or 0)
        key = (player_id, spell_id)
        kind = event_type(event)
        if kind in {"applybuff", "refreshbuff"}:
            active.setdefault(key, timestamp)
        elif kind == "removebuff":
            start = active.pop(key, timestamp)
            intervals[player_id].append((start, timestamp, spell_id))
    for (player_id, spell_id), start in active.items():
        intervals[player_id].append((start, int(fight_end), spell_id))
    return intervals

def _alive_players_at(players, deaths, friendly_casts, timestamp):
    alive = set(players)
    timeline = [
        (int(event.get("timestamp") or 0), "death", event.get("targetID"))
        for event in deaths
        if event.get("targetID") in players
    ]
    timeline.extend(
        (int(event.get("timestamp") or 0), "res", event.get("targetID"))
        for event in friendly_casts
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

def analyze_throw_junk(fight, actor_map, players, casts, damage, debuffs, friendly_buffs, deaths, friendly_casts=None):
    """Group Throw Junk casts and report crate-step evidence until the next group."""
    throw_events = [
        event for event in casts
        if int(ability_id(event) or 0) in {1291933, 1306145}
        and event_type(event) == "begincast"
    ]
    throw_groups = group_nearby(throw_events, window_ms=6000)
    immunity_intervals = _immunity_intervals(friendly_buffs, fight["endTime"])
    friendly_casts = friendly_casts or []

    rounds = []
    for group_index, group in enumerate(throw_groups):
        start = min(int(event.get("timestamp") or 0) for event in group)
        end = (
            min(int(event.get("timestamp") or 0) for event in throw_groups[group_index + 1])
            if group_index + 1 < len(throw_groups)
            else int(fight["endTime"])
        )
        step_events = [
            event for event in debuffs
            if start <= int(event.get("timestamp") or 0) < end
            and int(ability_id(event) or 0) == 1308853
            and event_type(event) in {"applydebuff", "applydebuffstack"}
            and event.get("targetID") in players
        ]
        steps_by_player = defaultdict(list)
        for event in step_events:
            steps_by_player[event.get("targetID")].append(event)
        stepped_ids = set(steps_by_player)
        stepped = []
        for player_id in sorted(stepped_ids, key=lambda value: actor_name(actor_map, value)):
            events = steps_by_player[player_id]
            timestamps = [int(event.get("timestamp") or 0) for event in events]
            stepped.append({
                **player_ref(players, actor_map, player_id),
                "stepCount": len(events),
                "firstStepTime": fmt_ms(min(timestamps) - fight["startTime"]),
                "lastStepTime": fmt_ms(max(timestamps) - fight["startTime"]),
                "peakStack": max((int(event.get("stack") or 1) for event in events), default=1),
            })

        immunity_rows = []
        immunity_ids = set()
        for player_id in players:
            overlapping = [
                (left, right, spell_id)
                for left, right, spell_id in immunity_intervals.get(player_id, [])
                if left < end and right >= start
            ]
            if not overlapping or player_id in stepped_ids:
                continue
            immunity_ids.add(player_id)
            immunity_rows.append({
                **player_ref(players, actor_map, player_id),
                "immunities": [
                    {
                        "spellID": spell_id,
                        "spellName": IMMUNITY_SPELLS[spell_id],
                        "time": fmt_ms(max(left, start) - fight["startTime"]),
                    }
                    for left, _right, spell_id in overlapping
                ],
            })

        alive_ids = _alive_players_at(players, deaths, friendly_casts, end)
        missing_ids = alive_ids - stepped_ids - immunity_ids
        missing = [
            player_ref(players, actor_map, player_id)
            for player_id in sorted(missing_ids, key=lambda value: actor_name(actor_map, value))
        ]
        direct_hits = [
            event for event in damage
            if start <= int(event.get("timestamp") or 0) < end
            and int(ability_id(event) or 0) == 1291935
            and event.get("targetID") in players
        ]
        direct_hit_ids = sorted(
            {event.get("targetID") for event in direct_hits},
            key=lambda value: actor_name(actor_map, value),
        )
        rupture_hits = [
            event for event in damage
            if start <= int(event.get("timestamp") or 0) < end
            and int(ability_id(event) or 0) in {1310027, 1311587}
            and event.get("targetID") in players
        ]
        rounds.append({
            "index": group_index + 1,
            "timeMs": start - fight["startTime"],
            "time": fmt_ms(start - fight["startTime"]),
            "endTimeMs": end - fight["startTime"],
            "endTime": fmt_ms(end - fight["startTime"]),
            "throwCount": len(group),
            "throwSpellID": 1291933,
            "stepSpellID": 1308853,
            "stepped": stepped,
            "stepCount": len(stepped),
            "immunityPlayers": immunity_rows,
            "immunityCount": len(immunity_rows),
            "missing": missing,
            "missingCount": len(missing),
            "directHitPlayers": [player_ref(players, actor_map, player_id) for player_id in direct_hit_ids],
            "relicRuptureSpellID": 1310028,
            "relicRuptureTriggered": bool(rupture_hits),
            "relicRuptureHitCount": len(rupture_hits),
        })
    return {
        "rounds": rounds,
        "roundCount": len(rounds),
        "relicRuptureRoundCount": sum(row["relicRuptureTriggered"] for row in rounds),
    }

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
    throw_junk = analyze_throw_junk(
        fight, actor_map, players, casts, damage, debuffs, friendly_buffs, raw["deaths"], raw.get("friendlyCasts"),
    )
    return {"unitedDefense": defense_rows, "unitedDefenseTotalSec": total_defense_duration_sec,
            "throwJunk": throw_junk,
            "avoidable": {"players": avoidable, "missedIceboundFlames": len(missed),
            "missedIceboundEvents": [{"time": fmt_ms(event["timestamp"] - fight["startTime"])} for event in missed]},
            "frostfireVolley": volley_rounds, "mightyThud": thud_rounds}

analyze_mechanics = analyze_lost


def build_aggregated_json(report_ids, options=None):
    return _build(BOSS_CONFIG, analyze_mechanics, report_ids, options)


def analyze(report_ids, output_path=None, catalog_entry=None, options=None, progress_callback=None):
    return analyze_boss(
        BOSS_CONFIG, analyze_mechanics, report_ids, output_path, catalog_entry, options
    )
