"""Evidence-first analyzer for Entombed Sentinels (12.1)."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from analyzer_core.concurrency import run_parallel_indexed
from analyzer_core.court_rules import validate_court_profile
from analyzer_core.progress import emit_progress
from analyzer_core.wcl_api import WclClient
from boss_plugins.combat_config import PERSONAL_DEFENSIVES
from boss_plugins.common import (
    build_player_mechanic_roles,
    combatant_spec_id,
    spec_class_color,
    spec_icon_slug,
    spec_localization,
    write_json_result,
)
from boss_plugins.venomous_abyss.shared import (
    build_survival_timeline,
    difficulty_fields,
    load_confirmed_spell_names,
    nightly_detail,
    nightly_player_totals,
)


ENCOUNTER_ID = 3445
ENCOUNTER_IDS = {ENCOUNTER_ID, 53445}
CN_TZ = timezone(timedelta(hours=8))

STASIS_IDS = {1284588, 1284606}
HELICAL_ID = 1284590
CULTIVATED_BURST_DAMAGE_ID = 1284941
CULTIVATED_BURST_DEBUFF_ID = 1284947
ACID_MARK_ID = 1284500
BLOOD_MARK_ID = 1284506
LIVING_VENOM_ID = 1284209
TOXIC_DROPLETS_CAST_ID = 1284434
TOXIC_DROPLETS_HIT_ID = 1284451
NOXIOUS_BLAST_ID = 1284452
UNSTABLE_MIASMA_ID = 1288260
SOAK_DAMAGE_ID = 1288282
CLINGING_MURK_ID = 1288297

DEFAULT_OPTIONS = {
    "helicalToxinReviewEnabled": True,
    "helicalLargeMovementYards": 5.0,
    "helicalPairingMaxDistanceYards": 8.0,
    "markReviewEnabled": True,
    "waterPlacementReviewEnabled": True,
    "waterOutlierDistanceYards": 8.0,
    "waterMaxSampleOffsetMs": 1500,
    "livingVenomReviewEnabled": True,
    "toxicDropletReviewEnabled": True,
}

COURT_PROFILE = {
    "bossKey": "sentinels",
    "phaseModel": "energy_cycle",
    "rules": [
        {
            "key": "toxic_droplet_missed", "label": "剧毒水滴漏踩", "mode": "direct",
            "spellIDs": [1284434, 1284451, 1284452],
            "requiredEvidence": ["droplet cast", "raid explosion 1284452"],
            "countOption": "toxicDropletCountEnabled", "defaultCountEnabled": True, "severityUnits": 1,
        },
        {
            "key": "helical_toxin_timeout", "label": "合星座（螺旋剧毒）未在 28 秒内完成", "mode": "direct",
            "spellIDs": [1284590, 1284941, 1311488],
            "requiredEvidence": ["stasis round", "Cultivated Burst"],
            "countOption": "helicalToxinCountEnabled", "defaultCountEnabled": True, "severityUnits": 1,
        },
        {
            "key": "protovenom_eruption", "label": "变换原毒错误碰撞", "mode": "direct",
            "spellIDs": [1296878, 1296882, 1296962],
            "requiredEvidence": ["round cast", "eruption center", "victim set"],
            "countOption": "protovenomCountEnabled", "defaultCountEnabled": True, "severityUnits": 1,
        },
        {
            "key": "red_water_placement", "label": "红水放置位置", "mode": "review",
            "spellIDs": [1284210, 1284471, 1284491, 1288260, 1288297],
            "requiredEvidence": ["water source", "source debuff remove timestamp", "nearest position", "water radius by source"],
            "calibration": "不同来源红水半径尚未确认",
            "countOption": "redWaterPlacementCountEnabled", "defaultCountEnabled": False, "severityUnits": 1,
        },
    ],
}
validate_court_profile(COURT_PROFILE)

IMMUNITY_ABILITIES = {
    spell_id: details
    for spell_id, details in PERSONAL_DEFENSIVES.items()
    if details.get("effectKind") in {"immunity", "magic_immunity"}
}


def progress(message, percent=None):
    print(f"[sentinels] {message}", flush=True)
    emit_progress(message, percent=percent, stage="analyze")


def ability_id(event):
    return event.get("abilityGameID") or event.get("killingAbilityGameID") or event.get("extraAbilityGameID")


def event_type(event):
    return str(event.get("type") or "").lower()


def event_amount(event):
    return int(event.get("amount") or event.get("unmitigatedAmount") or 0)


def fmt_ms(ms):
    seconds = max(0, int(ms or 0)) / 1000
    return f"{int(seconds // 60):02d}:{seconds % 60:04.1f}"


def actor_name(actor_map, actor_id):
    return str(actor_map.get(actor_id) or f"未知({actor_id})").split("-", 1)[0]


def cluster_events(events, tolerance_ms=2):
    """Group essentially simultaneous WCL rows, accepting the usual 1ms skew."""
    groups = []
    for event in sorted(events, key=lambda row: int(row.get("timestamp") or 0)):
        timestamp = int(event.get("timestamp") or 0)
        if not groups or timestamp - groups[-1][-1][0] > tolerance_ms:
            groups.append([])
        groups[-1].append((timestamp, event))
    return [[event for _, event in group] for group in groups]


def build_player_catalog(actor_map, actor_type, combatants):
    combatant_by_player = {event.get("sourceID") or event.get("targetID"): event for event in combatants}
    roles = build_player_mechanic_roles(combatants)
    rows = {}
    for actor_id, event in combatant_by_player.items():
        if actor_type.get(actor_id) != "Player":
            continue
        spec_id = combatant_spec_id(event)
        rows[actor_id] = {
            "id": actor_id,
            "name": actor_name(actor_map, actor_id),
            "specID": spec_id,
            "role": roles.get(actor_id, "unknown"),
            "icon": spec_icon_slug(spec_id),
            "classColor": spec_class_color(spec_id),
            "localization": spec_localization(spec_id),
        }
    return rows


def _unique_input_pair(result_stack):
    if result_stack == 2:
        return [1, 1]
    if result_stack == 6:
        return [3, 3]
    return None


def _coordinate_distance(position_index, left_id, right_id, timestamp):
    left = position_at(position_index, left_id, timestamp)
    right = position_at(position_index, right_id, timestamp)
    if not left or not right:
        return None
    return math.dist((left["x"], left["y"]), (right["x"], right["y"])) / 100


def same_frame_removal_pairs(player_ids):
    """Arbitrarily pair safe removals emitted in one WCL frame."""
    remaining = list(dict.fromkeys(player_id for player_id in player_ids if player_id is not None))
    pairs = []
    for offset in range(0, len(remaining) - 1, 2):
        pairs.append({
            "playerIDs": remaining[offset:offset + 2],
            "distanceYards": None,
            "pairingEvidence": "same-frame-removal",
        })
    return pairs


def nearest_active_partner(target_id, active_ids, timestamp, position_index, max_distance_yards):
    candidates = []
    for candidate_id in active_ids:
        if candidate_id == target_id:
            continue
        distance = _coordinate_distance(position_index, target_id, candidate_id, timestamp)
        if distance is not None and distance <= max_distance_yards:
            candidates.append((distance, candidate_id))
    if not candidates:
        return None
    distance, partner_id = min(candidates)
    return {
        "playerIDs": [target_id, partner_id],
        "distanceYards": round(distance, 1),
        "pairingEvidence": "coordinates",
        "positionConfidence": "high",
    }


def analyze_helical_toxins(
    fight,
    actor_map,
    stasis_events,
    aura_events,
    burst_damage,
    deaths=None,
    position_index=None,
    options=None,
):
    options = {**DEFAULT_OPTIONS, **(options or {})}
    position_index = position_index or {}
    starts = sorted(
        int(event.get("timestamp") or 0)
        for event in stasis_events
        if event_type(event) in {"cast", "applybuff"}
    )
    # Cast and applybuff commonly share a timestamp. Keep one round anchor.
    starts = [group[0] for group in cluster_events([{"timestamp": value} for value in starts], 50)]
    starts = [int(row.get("timestamp") or 0) for row in starts]
    deaths = deaths or []
    rounds = []
    for index, start in enumerate(starts, start=1):
        next_start = starts[index] if index < len(starts) else int(fight["endTime"]) + 1
        round_events = [
            event for event in aura_events
            if start <= int(event.get("timestamp") or 0) < next_start
        ]
        initial = [event for event in round_events if event_type(event) == "applydebuff"]
        if not initial and not round_events:
            continue
        deadline = start + 28_000
        round_bursts = [
            event for event in burst_damage
            if start <= int(event.get("timestamp") or 0) < next_start
        ]
        collision_rows = []
        known_values = {
            event.get("targetID"): int(event.get("stack"))
            for event in initial
            if event.get("targetID") is not None and event.get("stack") is not None
        }
        last_stack_collision = {}
        active_players = {
            event.get("targetID") for event in initial
            if event.get("targetID") is not None
        }
        non_initial = [event for event in round_events if event_type(event) != "applydebuff"]
        for group in cluster_events(non_initial):
            timestamp = min(int(event.get("timestamp") or 0) for event in group)
            kinds = {event_type(event) for event in group}
            targets = list(dict.fromkeys(
                event.get("targetID") for event in group
                if event.get("targetID") is not None
            ))
            if not targets:
                continue
            close_burst = any(abs(int(event.get("timestamp") or 0) - timestamp) <= 100 for event in round_bursts)
            close_death = any(
                event.get("targetID") in targets
                and abs(int(event.get("timestamp") or 0) - timestamp) <= 100
                for event in deaths
            )
            if kinds == {"applydebuffstack"} and len(targets) == 2:
                result_stack = int(group[0].get("stack") or 0)
                inferred = _unique_input_pair(result_stack)
                movement_evidence = collision_movement_evidence(
                    actor_map,
                    targets,
                    timestamp,
                    position_index,
                )
                row = {
                    "timeMs": timestamp - int(fight["startTime"]),
                    "time": fmt_ms(timestamp - int(fight["startTime"])),
                    "kind": "wrong-collision",
                    "players": [actor_name(actor_map, target_id) for target_id in targets],
                    "playerIDs": targets,
                    "resultStack": result_stack,
                    "inferredInput": inferred,
                    "collisionCombination": (
                        "1+2" if result_stack == 3 else
                        "1+1" if result_stack == 2 else
                        "3+3" if result_stack == 6 else
                        f"合计 {result_stack} 层"
                    ),
                    "recoverable": result_stack < 4,
                    "overflow": result_stack > 4,
                    "movementEvidence": movement_evidence,
                    "largeMovers": movement_before_collision(
                        actor_map,
                        targets,
                        timestamp,
                        position_index,
                        float(options["helicalLargeMovementYards"]),
                    ),
                }
                collision_rows.append(row)
                for target_id in targets:
                    active_players.add(target_id)
                    known_values[target_id] = result_stack
                    last_stack_collision[target_id] = row
                continue
            if kinds <= {"removedebuff", "removedebuffstack"} and not close_burst and not close_death:
                targets = [target_id for target_id in targets if target_id in active_players]
                if not targets:
                    continue
                max_pair_distance = float(options["helicalPairingMaxDistanceYards"])
                pair_rows = same_frame_removal_pairs(targets)
                paired_targets = {player_id for pair in pair_rows for player_id in pair["playerIDs"]}
                for target_id in targets:
                    if target_id in paired_targets or target_id not in active_players:
                        continue
                    inferred_pair = nearest_active_partner(
                        target_id,
                        active_players - paired_targets,
                        timestamp,
                        position_index,
                        max_pair_distance,
                    )
                    if inferred_pair:
                        pair_rows.append(inferred_pair)
                        paired_targets.update(inferred_pair["playerIDs"])
                for pair in pair_rows:
                    pair_targets = pair["playerIDs"]
                    prior = [known_values.get(target_id) for target_id in pair_targets]
                    known_input = None
                    if all(value is not None for value in prior) and sum(prior) == 4:
                        known_input = prior
                    elif sum(value is not None for value in prior) == 1:
                        known_index = 0 if prior[0] is not None else 1
                        known_value = prior[known_index]
                        inferred_partner = 4 - known_value
                        if 1 <= inferred_partner <= 3:
                            known_input = list(prior)
                            known_input[1 - known_index] = inferred_partner
                    recovery = known_input is not None and any(
                        last_stack_collision.get(target_id) is not None
                        for target_id in pair_targets
                    )
                    row = {
                        "timeMs": timestamp - int(fight["startTime"]),
                        "time": fmt_ms(timestamp - int(fight["startTime"])),
                        "kind": "recovery-clear" if recovery else "safe-clear",
                        "players": [actor_name(actor_map, target_id) for target_id in pair_targets],
                        "playerIDs": pair_targets,
                        "resultStack": 0,
                        "pairingEvidence": pair["pairingEvidence"],
                        "distanceYards": pair["distanceYards"],
                        "positionConfidence": pair.get("positionConfidence"),
                    }
                    if recovery:
                        row.update({
                            "knownInput": known_input,
                            "collisionCombination": "+".join(str(value) for value in known_input),
                        })
                    collision_rows.append(row)
                    for target_id in pair_targets:
                        active_players.discard(target_id)
                        known_values.pop(target_id, None)
                unresolved_targets = [
                    target_id for target_id in targets
                    if target_id not in paired_targets and target_id in active_players
                ]
                if not unresolved_targets:
                    continue
                targets = unresolved_targets
            # A single removal at the 28s endpoint is cleanup/timeout evidence,
            # not a fabricated partner attribution.
            for target_id in targets:
                collision_rows.append({
                    "timeMs": timestamp - int(fight["startTime"]),
                    "time": fmt_ms(timestamp - int(fight["startTime"])),
                    "kind": "timeout-remove" if close_burst or abs(timestamp - deadline) <= 250 else "unpaired-remove",
                    "players": [actor_name(actor_map, target_id)],
                    "playerIDs": [target_id],
                    "resultStack": 0,
                })
                if close_burst or abs(timestamp - deadline) <= 250:
                    active_players.discard(target_id)

        failures = []
        for event in round_bursts:
            target_id = event.get("targetID")
            source_collision = last_stack_collision.get(target_id)
            failures.append({
                "timeMs": int(event.get("timestamp") or 0) - int(fight["startTime"]),
                "time": fmt_ms(int(event.get("timestamp") or 0) - int(fight["startTime"])),
                "playerID": target_id,
                "player": actor_name(actor_map, target_id),
                "amount": event_amount(event),
                "spellID": CULTIVATED_BURST_DAMAGE_ID,
                "precedingResultStack": source_collision.get("resultStack") if source_collision else None,
                "precedingPlayers": source_collision.get("players") if source_collision else [],
            })
        wrong_collisions = [row for row in collision_rows if row["kind"] == "wrong-collision"]
        if wrong_collisions:
            wrong_collisions[0]["firstWrongCollision"] = True
        rounds.append({
            "index": index,
            "startTimeMs": start - int(fight["startTime"]),
            "startTime": fmt_ms(start - int(fight["startTime"])),
            "deadlineTimeMs": deadline - int(fight["startTime"]),
            "deadlineTime": fmt_ms(deadline - int(fight["startTime"])),
            "initialPlayerCount": len({event.get("targetID") for event in initial}),
            "initialStackCount": sum(event.get("stack") is not None for event in initial),
            "collisions": collision_rows,
            "wrongCollisionCount": len(wrong_collisions),
            "recoveryCount": sum(row["kind"] == "recovery-clear" for row in collision_rows),
            "failures": failures,
            "success": not failures and not wrong_collisions,
        })
    return {
        "rounds": rounds,
        "roundCount": len(rounds),
        "failedRoundCount": sum(not row["success"] for row in rounds),
        "wrongCollisionCount": sum(row["wrongCollisionCount"] for row in rounds),
        "explanation": "当前 WCL 的初次 applydebuff 事件不包含玩家层数；游戏内插件能显示的私有光环数字没有进入本场 combat log payload。正常同帧移除只记录安全相撞的两名玩家，撞错后的 applydebuffstack 才能用结果层数反推组合。每轮第一个错误碰撞会用不同色块提醒，具体是谁乱动仍需进一步确认。",
    }


def stasis_windows(fight, stasis_events):
    start_rows = [
        {"timestamp": int(event.get("timestamp") or 0)}
        for event in stasis_events
        if event_type(event) in {"cast", "applybuff"}
    ]
    end_rows = [
        {"timestamp": int(event.get("timestamp") or 0)}
        for event in stasis_events
        if event_type(event) == "removebuff"
    ]
    # Enemy cast and aura application/removal are commonly emitted a few
    # milliseconds apart. They are one transition, not separate phases.
    starts = [min(int(row["timestamp"]) for row in group) for group in cluster_events(start_rows, 100)]
    ends = [max(int(row["timestamp"]) for row in group) for group in cluster_events(end_rows, 100)]
    windows = []
    for start in starts:
        end = next((value for value in ends if value >= start), start + 12_000)
        windows.append((start, end))
    return windows


def _next_mark_stack(current, event):
    kind = event_type(event)
    if kind == "applydebuff":
        return int(event.get("stack") or 1)
    if kind in {"applydebuffstack", "refreshdebuff"}:
        return int(event.get("stack") or current or 1)
    if kind in {"removedebuff", "removedebuffstack"}:
        return 0
    return current


def _mark_state_at(events, timestamp):
    state = {ACID_MARK_ID: 0, BLOOD_MARK_ID: 0}
    for event in events:
        if int(event.get("timestamp") or 0) > timestamp:
            break
        spell_id = ability_id(event)
        state[spell_id] = _next_mark_stack(state[spell_id], event)
    return state


def _mark_summary(events, initial_state=None):
    state = dict(initial_state or {ACID_MARK_ID: 0, BLOOD_MARK_ID: 0})
    max_stacks = dict(state)
    simultaneous_count = 0
    highest_total = sum(state.values())
    overlapping = all(state.values())
    gain_counts = {ACID_MARK_ID: 0, BLOOD_MARK_ID: 0}
    for group in cluster_events(events):
        for event in group:
            spell_id = ability_id(event)
            if spell_id not in state:
                continue
            if event_type(event) in {"applydebuff", "applydebuffstack"}:
                gain_counts[spell_id] += 1
            state[spell_id] = _next_mark_stack(state[spell_id], event)
            max_stacks[spell_id] = max(max_stacks[spell_id], state[spell_id])
        now_overlapping = all(state.values())
        if now_overlapping and not overlapping:
            simultaneous_count += 1
        overlapping = now_overlapping
        highest_total = max(highest_total, sum(state.values()))
    return {
        "maxAcidStack": max_stacks[ACID_MARK_ID],
        "maxBloodStack": max_stacks[BLOOD_MARK_ID],
        "simultaneousBuffCount": simultaneous_count,
        "highestTotalStack": highest_total,
        "acidGainCount": gain_counts[ACID_MARK_ID],
        "bloodGainCount": gain_counts[BLOOD_MARK_ID],
    }


def analyze_marks(fight, actor_map, player_catalog, mark_events, stasis_events, deaths=None, watch_players=None):
    deaths = deaths or []
    windows = stasis_windows(fight, stasis_events)
    split_windows = []
    cursor = int(fight["startTime"])
    for start, end in windows:
        if cursor < start:
            split_windows.append((cursor, start))
        cursor = end
    if cursor < int(fight["endTime"]):
        split_windows.append((cursor, int(fight["endTime"])))

    by_player = defaultdict(list)
    for event in mark_events:
        target_id = event.get("targetID")
        spell_id = ability_id(event)
        if target_id in player_catalog and spell_id in {ACID_MARK_ID, BLOOD_MARK_ID}:
            by_player[target_id].append(event)
    for events in by_player.values():
        events.sort(key=lambda row: int(row.get("timestamp") or 0))

    players = []
    for player_id, player in player_catalog.items():
        player_events = by_player[player_id]
        overall = _mark_summary(player_events)
        cycle_rows = []
        for cycle_index, (start, end) in enumerate(split_windows, start=1):
            initial = _mark_state_at(player_events, start - 1)
            events = [event for event in player_events if start <= int(event.get("timestamp") or 0) < end]
            summary = _mark_summary(events, initial)
            cycle_rows.append({
                "index": cycle_index,
                "startTimeMs": start - int(fight["startTime"]),
                "endTimeMs": end - int(fight["startTime"]),
                "startTime": fmt_ms(start - int(fight["startTime"])),
                "endTime": fmt_ms(end - int(fight["startTime"])),
                "acid": {
                    "startStack": initial[ACID_MARK_ID],
                    "peak": summary["maxAcidStack"],
                    "gainCount": summary["acidGainCount"],
                },
                "blood": {
                    "startStack": initial[BLOOD_MARK_ID],
                    "peak": summary["maxBloodStack"],
                    "gainCount": summary["bloodGainCount"],
                },
                "simultaneousBuffCount": summary["simultaneousBuffCount"],
                "highestTotalStack": summary["highestTotalStack"],
            })
        players.append({
            **player,
            "maxAcidStack": overall["maxAcidStack"],
            "maxBloodStack": overall["maxBloodStack"],
            "simultaneousBuffCount": overall["simultaneousBuffCount"],
            "highestTotalStack": overall["highestTotalStack"],
            "cycles": cycle_rows,
        })
    players.sort(key=lambda row: (-row["highestTotalStack"], -row["simultaneousBuffCount"], row["name"]))
    death_over_thirty = []
    for death in deaths:
        player_id = death.get("targetID")
        if player_id not in player_catalog:
            continue
        timestamp = int(death.get("timestamp") or 0)
        stacks = _mark_state_at(by_player[player_id], timestamp - 1)
        total_stack = stacks[ACID_MARK_ID] + stacks[BLOOD_MARK_ID]
        if total_stack <= 30:
            continue
        death_over_thirty.append({
            **player_catalog[player_id],
            "playerID": player_id,
            "player": player_catalog[player_id]["name"],
            "timeMs": timestamp - int(fight["startTime"]),
            "time": fmt_ms(timestamp - int(fight["startTime"])),
            "acidStack": stacks[ACID_MARK_ID],
            "bloodStack": stacks[BLOOD_MARK_ID],
            "totalStack": total_stack,
        })
    return {
        "players": players,
        "cycleCount": len(split_windows),
        "deathOverThirty": death_over_thirty,
    }


def position_actor_id(event):
    if event.get("resourceActor") in {2, "2"}:
        return event.get("targetID")
    return event.get("sourceID") or event.get("targetID")


def build_position_index(events):
    index = defaultdict(list)
    for event in events:
        actor_id = position_actor_id(event)
        if actor_id is None or event.get("x") is None or event.get("y") is None:
            continue
        index[actor_id].append({
            "timestamp": int(event.get("timestamp") or 0),
            "x": float(event["x"]),
            "y": float(event["y"]),
            "facing": event.get("facing"),
            "hitPoints": event.get("hitPoints"),
            "maxHitPoints": event.get("maxHitPoints"),
            "absorb": event.get("absorb"),
        })
    for rows in index.values():
        rows.sort(key=lambda row: row["timestamp"])
    return index


def nearest_position(index, actor_id, timestamp, max_offset_ms):
    rows = index.get(actor_id) or []
    if not rows:
        return None
    row = min(rows, key=lambda item: abs(item["timestamp"] - timestamp))
    offset = row["timestamp"] - timestamp
    return {
        **row,
        "sampleOffsetMs": offset,
        "positionReliable": abs(offset) <= max_offset_ms,
    }


def position_at(index, actor_id, timestamp, max_gap_ms=1500):
    """Interpolate a WCL position sample at a specific timestamp."""
    rows = index.get(actor_id) or []
    if not rows:
        return None
    before = None
    after = None
    for row in rows:
        if row["timestamp"] <= timestamp:
            before = row
        if row["timestamp"] >= timestamp:
            after = row
            break
    if before and after and before["timestamp"] != after["timestamp"]:
        if timestamp - before["timestamp"] <= max_gap_ms and after["timestamp"] - timestamp <= max_gap_ms:
            ratio = (timestamp - before["timestamp"]) / (after["timestamp"] - before["timestamp"])
            return {
                "x": before["x"] + (after["x"] - before["x"]) * ratio,
                "y": before["y"] + (after["y"] - before["y"]) * ratio,
                "positionReliable": True,
            }
    nearest = nearest_position(index, actor_id, timestamp, max_gap_ms)
    if not nearest or not nearest["positionReliable"]:
        return None
    return nearest


def movement_before_collision(actor_map, player_ids, timestamp, position_index, threshold_yards):
    evidence = collision_movement_evidence(actor_map, player_ids, timestamp, position_index)
    if not evidence:
        return []
    return [
        {**row, "windowMs": evidence["windowMs"]}
        for row in evidence["players"]
        if row["movementYards"] > threshold_yards
    ]


def collision_movement_evidence(actor_map, player_ids, timestamp, position_index, window_ms=1000):
    """Return both players' movement and their closing distance before a wrong collision."""
    positions = {}
    players = []
    for player_id in player_ids:
        before = position_at(position_index, player_id, timestamp - window_ms)
        at_collision = position_at(position_index, player_id, timestamp)
        if not before or not at_collision:
            continue
        distance = math.dist(
            (before["x"], before["y"]),
            (at_collision["x"], at_collision["y"]),
        ) / 100
        positions[player_id] = (before, at_collision)
        players.append({
            "playerID": player_id,
            "player": actor_name(actor_map, player_id),
            "movementYards": round(distance, 1),
        })
    if not players:
        return None
    result = {"windowMs": window_ms, "players": players}
    if len(player_ids) == 2 and all(player_id in positions for player_id in player_ids):
        left_id, right_id = player_ids
        before_distance = math.dist(
            (positions[left_id][0]["x"], positions[left_id][0]["y"]),
            (positions[right_id][0]["x"], positions[right_id][0]["y"]),
        ) / 100
        collision_distance = math.dist(
            (positions[left_id][1]["x"], positions[left_id][1]["y"]),
            (positions[right_id][1]["x"], positions[right_id][1]["y"]),
        ) / 100
        result.update({
            "pairDistanceBeforeYards": round(before_distance, 1),
            "pairDistanceAtCollisionYards": round(collision_distance, 1),
            "closingDistanceYards": round(before_distance - collision_distance, 1),
        })
    return result


def arena_estimate(position_index):
    points = [(row["x"], row["y"]) for rows in position_index.values() for row in rows]
    if len(points) < 20:
        return None
    center_x = statistics.median(point[0] for point in points)
    center_y = statistics.median(point[1] for point in points)
    distances = sorted(math.dist(point, (center_x, center_y)) for point in points)
    radius = distances[min(len(distances) - 1, int(len(distances) * 0.96))]
    return {
        "centerX": round(center_x, 2),
        "centerY": round(center_y, 2),
        "radius": round(radius, 2),
        "radiusYards": round(radius / 100, 1),
        "method": "all-player-position-samples-p96",
    }


def snapshot_players(player_catalog, position_index, timestamp, max_offset_ms=2000):
    rows = []
    for player_id, player in player_catalog.items():
        position = nearest_position(position_index, player_id, timestamp, max_offset_ms)
        if not position:
            rows.append({**player, "position": None, "positionReliable": False, "sampleOffsetMs": None})
            continue
        rows.append({
            **player,
            "position": {"x": round(position["x"], 2), "y": round(position["y"], 2)},
            "facing": position.get("facing"),
            "sampleOffsetMs": position["sampleOffsetMs"],
            "positionReliable": position["positionReliable"],
        })
    return rows


def placement_metrics(positions, cluster_radius_yards):
    reliable = [row for row in positions if row.get("positionReliable")]
    if not reliable:
        return {
            "reliableCount": 0,
            "centroid": None,
            "maxRadiusYards": None,
            "diameterYards": None,
            "clustered": None,
        }
    centroid = {
        "x": statistics.mean(row["x"] for row in reliable),
        "y": statistics.mean(row["y"] for row in reliable),
    }
    radii = [math.dist((row["x"], row["y"]), (centroid["x"], centroid["y"])) for row in reliable]
    diameter = max(
        (math.dist((left["x"], left["y"]), (right["x"], right["y"])) for left in reliable for right in reliable),
        default=0,
    )
    max_radius_yards = max(radii, default=0) / 100
    return {
        "reliableCount": len(reliable),
        "centroid": {"x": round(centroid["x"], 2), "y": round(centroid["y"], 2)},
        "maxRadiusYards": round(max_radius_yards, 1),
        "averageRadiusYards": round(statistics.mean(radii) / 100, 1),
        "diameterYards": round(diameter / 100, 1),
        "clustered": max_radius_yards <= float(cluster_radius_yards),
    }


def _alive_at(player_id, timestamp, deaths, position_index):
    prior_deaths = [
        int(event.get("timestamp") or 0)
        for event in deaths
        if event.get("targetID") == player_id and int(event.get("timestamp") or 0) <= timestamp
    ]
    if not prior_deaths:
        return True
    last_death = max(prior_deaths)
    return any(last_death < row["timestamp"] <= timestamp for row in position_index.get(player_id, []))


def analyze_clinging_murk(
    fight,
    actor_map,
    player_catalog,
    debuffs,
    position_index,
    options,
    mark_events=None,
    deaths=None,
):
    mark_events = mark_events or []
    deaths = deaths or []
    marks_by_player = defaultdict(list)
    for event in mark_events:
        if event.get("targetID") in player_catalog:
            marks_by_player[event.get("targetID")].append(event)
    for events in marks_by_player.values():
        events.sort(key=lambda row: int(row.get("timestamp") or 0))
    miasma_removes = [
        event for event in debuffs
        if ability_id(event) == UNSTABLE_MIASMA_ID and event_type(event) == "removedebuff"
    ]
    murk_events = [event for event in debuffs if ability_id(event) == CLINGING_MURK_ID]
    rounds = []
    for index, miasma in enumerate(sorted(miasma_removes, key=lambda row: row["timestamp"]), start=1):
        soak_time = int(miasma["timestamp"])
        applies = [
            event for event in murk_events
            if event_type(event) in {"applydebuff", "applydebuffstack"}
            and abs(int(event.get("timestamp") or 0) - soak_time) <= 100
        ]
        carrier_ids = sorted({event.get("targetID") for event in applies if event.get("targetID") is not None})
        removes = [
            event for event in murk_events
            if event_type(event) == "removedebuff"
            and event.get("targetID") in carrier_ids
            and soak_time < int(event.get("timestamp") or 0) <= soak_time + 10_000
        ]
        if not removes:
            continue
        drop_time = int(statistics.median(int(event["timestamp"]) for event in removes))
        placements = []
        for target_id in carrier_ids:
            target_remove = next((event for event in removes if event.get("targetID") == target_id), None)
            timestamp = int(target_remove["timestamp"]) if target_remove else drop_time
            position = nearest_position(
                position_index,
                target_id,
                timestamp,
                int(options["waterMaxSampleOffsetMs"]),
            )
            row = {
                "playerID": target_id,
                "player": actor_name(actor_map, target_id),
                "timeMs": timestamp - int(fight["startTime"]),
                "time": fmt_ms(timestamp - int(fight["startTime"])),
            }
            if position:
                row.update({
                    "_x": position["x"],
                    "_y": position["y"],
                    "sampleOffsetMs": position["sampleOffsetMs"],
                    "positionReliable": position["positionReliable"],
                })
            else:
                row.update({"_x": None, "_y": None, "sampleOffsetMs": None, "positionReliable": False})
            placements.append(row)
        reliable = [row for row in placements if row["positionReliable"]]
        if reliable:
            center = (
                statistics.median(row["_x"] for row in reliable),
                statistics.median(row["_y"] for row in reliable),
            )
            for row in reliable:
                row["distanceFromGroupYards"] = round(math.dist((row["_x"], row["_y"]), center) / 100, 1)
        outlier_threshold = float(options["waterOutlierDistanceYards"])
        dispersed = [
            {
                "playerID": row["playerID"],
                "player": row["player"],
                "time": row["time"],
                "distanceFromGroupYards": row["distanceFromGroupYards"],
                "sampleOffsetMs": row["sampleOffsetMs"],
            }
            for row in reliable
            if row.get("distanceFromGroupYards", 0) > outlier_threshold
        ]
        blood_side = []
        for player_id, player in player_catalog.items():
            if not _alive_at(player_id, soak_time, deaths, position_index):
                continue
            stacks = _mark_state_at(marks_by_player[player_id], soak_time)
            if stacks[BLOOD_MARK_ID] > stacks[ACID_MARK_ID]:
                blood_side.append({
                    "playerID": player_id,
                    "player": player["name"],
                    "acidStack": stacks[ACID_MARK_ID],
                    "bloodStack": stacks[BLOOD_MARK_ID],
                })
        missing_blood_side = [row for row in blood_side if row["playerID"] not in carrier_ids]
        public_placements = [
            {key: value for key, value in row.items() if not key.startswith("_")}
            for row in placements
        ]
        rounds.append({
            "index": index,
            "soakTimeMs": soak_time - int(fight["startTime"]),
            "soakTime": fmt_ms(soak_time - int(fight["startTime"])),
            "dropTimeMs": drop_time - int(fight["startTime"]),
            "dropTime": fmt_ms(drop_time - int(fight["startTime"])),
            "initialTargetID": miasma.get("targetID"),
            "initialTarget": actor_name(actor_map, miasma.get("targetID")),
            "carrierCount": len(carrier_ids),
            "bloodSideCandidateCount": len(blood_side),
            "missingBloodSidePlayers": missing_blood_side,
            "dispersedPlayers": dispersed,
            "reliableRemovalPositionCount": len(reliable),
            "placements": public_placements,
        })
    return {
        "rounds": rounds,
        "roundCount": len(rounds),
        "outlierDistanceYards": float(options["waterOutlierDistanceYards"]),
    }


def analyze_toxic_droplets(
    fight,
    actor_map,
    casts,
    damage,
    player_catalog=None,
    friendly_casts=None,
    deaths=None,
    position_index=None,
):
    player_catalog = player_catalog or {}
    friendly_casts = friendly_casts or []
    deaths = deaths or []
    position_index = position_index or {}
    anchors = sorted(
        int(event["timestamp"])
        for event in casts
        if ability_id(event) == TOXIC_DROPLETS_CAST_ID and event_type(event) == "cast"
    )
    hits = [event for event in damage if ability_id(event) == TOXIC_DROPLETS_HIT_ID]
    blasts = [event for event in damage if ability_id(event) == NOXIOUS_BLAST_ID]
    rounds = []
    for index, start in enumerate(anchors, start=1):
        next_start = anchors[index] if index < len(anchors) else int(fight["endTime"]) + 1
        end = min(next_start, start + 25_000)
        round_hits = [event for event in hits if start <= int(event["timestamp"]) < end]
        round_blasts = [event for event in blasts if start <= int(event["timestamp"]) < end]
        counts = Counter(event.get("targetID") for event in round_hits)
        no_hit_players = []
        for player_id, player in player_catalog.items():
            if player_id in counts or not _alive_at(player_id, start, deaths, position_index):
                continue
            immunities = []
            for cast in friendly_casts:
                if (cast.get("sourceID") or cast.get("targetID")) != player_id:
                    continue
                details = IMMUNITY_ABILITIES.get(ability_id(cast))
                if not details:
                    continue
                cast_time = int(cast.get("timestamp") or 0)
                duration = int(details.get("durationMs") or 0)
                if cast_time <= end and cast_time + duration >= start:
                    immunities.append({
                        "spellID": ability_id(cast),
                        "spell": details["name"],
                        "timeMs": cast_time - int(fight["startTime"]),
                        "time": fmt_ms(cast_time - int(fight["startTime"])),
                    })
            no_hit_players.append({
                "playerID": player_id,
                "player": player["name"],
                "immunityCandidate": bool(immunities),
                "immunityEvidence": immunities,
            })
        rounds.append({
            "index": index,
            "castTimeMs": start - int(fight["startTime"]),
            "castTime": fmt_ms(start - int(fight["startTime"])),
            "soakHitCount": len(round_hits),
            "uniqueSoakerCount": len(counts),
            "repeatSoakers": [
                {"playerID": target_id, "player": actor_name(actor_map, target_id), "count": count}
                for target_id, count in counts.items() if count > 1
            ],
            "noHitPlayers": no_hit_players,
            "missed": bool(round_blasts),
            "blastTimeMs": int(round_blasts[0]["timestamp"]) - int(fight["startTime"]) if round_blasts else None,
            "blastVictimCount": len({event.get("targetID") for event in round_blasts}),
        })
    return {"rounds": rounds, "missedRoundCount": sum(row["missed"] for row in rounds)}


def analyze_living_venom(fight, actor_map, damage, deaths, player_catalog=None):
    player_catalog = player_catalog or {}
    rows = defaultdict(list)
    for event in damage:
        if ability_id(event) == LIVING_VENOM_ID:
            rows[event.get("targetID")].append(event)
    death_rows = [event for event in deaths if ability_id(event) == LIVING_VENOM_ID]
    players = []
    for target_id, events in rows.items():
        players.append({
            **(player_catalog.get(target_id) or {}),
            "playerID": target_id,
            "player": actor_name(actor_map, target_id),
            "hitCount": len(events),
            "totalDamage": sum(event_amount(event) for event in events),
            "maxHit": max(event_amount(event) for event in events),
            "deathCount": sum(event.get("targetID") == target_id for event in death_rows),
            "events": [
                {
                    "timeMs": int(event["timestamp"]) - int(fight["startTime"]),
                    "time": fmt_ms(int(event["timestamp"]) - int(fight["startTime"])),
                    "amount": event_amount(event),
                }
                for event in events
            ],
        })
    players.sort(key=lambda row: (row["deathCount"], row["hitCount"], row["totalDamage"]), reverse=True)
    return {
        "spellID": LIVING_VENOM_ID,
        "players": players,
        "totalHits": sum(row["hitCount"] for row in players),
        "totalDamage": sum(row["totalDamage"] for row in players),
    }


def phase_timeline(fight, stasis_events):
    windows = stasis_windows(fight, stasis_events)
    rows = [{"key": "split-1", "label": "分场 1", "timeMs": 0}]
    for index, (start, end) in enumerate(windows, start=1):
        rows.append({"key": f"stasis-{index}", "label": f"强酸静滞 {index}", "timeMs": start - int(fight["startTime"])})
        if end < int(fight["endTime"]):
            rows.append({"key": f"split-{index + 1}", "label": f"分场 {index + 1}", "timeMs": end - int(fight["startTime"])})
    rows.append({
        "key": "kill" if fight.get("kill") else "wipe",
        "label": "击杀" if fight.get("kill") else "灭团",
        "timeMs": int(fight["endTime"] - fight["startTime"]),
    })
    return rows


def fetch_payload(client, report_id, fight, options):
    casts = client.events(report_id, "Casts", fight, hostility_type="Enemies")
    friendly_casts = client.events(report_id, "Casts", fight, hostility_type="Friendlies")
    damage = client.events(report_id, "DamageTaken", fight, include_resources=True)
    debuffs = client.events(report_id, "Debuffs", fight, hostility_type="Friendlies")
    buffs = client.events(report_id, "Buffs", fight, hostility_type="Enemies")
    deaths = client.events(report_id, "Deaths", fight)
    combatants = client.events(report_id, "CombatantInfo", fight)
    resources = []
    if options["waterPlacementReviewEnabled"] or options["helicalToxinReviewEnabled"]:
        resources = client.events(report_id, "Resources", fight, include_resources=True)
    return {
        "casts": casts,
        "friendlyCasts": friendly_casts,
        "damage": damage,
        "debuffs": debuffs,
        "buffs": buffs,
        "deaths": deaths,
        "combatants": combatants,
        "resources": resources,
    }


def analyze_report_fight(report_id, report_start, actor_map, actor_type, fight, payload, options):
    player_catalog = build_player_catalog(actor_map, actor_type, payload["combatants"])
    player_deaths = [event for event in payload["deaths"] if event.get("targetID") in player_catalog]
    stasis_events = [
        event for event in payload["casts"] + payload["buffs"]
        if ability_id(event) in STASIS_IDS
    ]
    helical_events = [event for event in payload["debuffs"] if ability_id(event) == HELICAL_ID]
    burst_damage = [event for event in payload["damage"] if ability_id(event) == CULTIVATED_BURST_DAMAGE_ID]
    mark_events = [event for event in payload["debuffs"] if ability_id(event) in {ACID_MARK_ID, BLOOD_MARK_ID}]
    # DamageTaken resource snapshots are substantially denser than the Resources
    # table for some players. Combining both avoids silently losing the final
    # approach immediately before a collision.
    position_index = build_position_index(payload["resources"] + payload["damage"])
    helical = analyze_helical_toxins(
        fight,
        actor_map,
        stasis_events,
        helical_events,
        burst_damage,
        player_deaths,
        position_index,
        options,
    ) if options["helicalToxinReviewEnabled"] else {
        "rounds": [], "roundCount": 0, "failedRoundCount": 0, "wrongCollisionCount": 0,
        "explanation": "螺旋毒素分析已在配置中关闭。",
    }
    marks = analyze_marks(
        fight,
        actor_map,
        player_catalog,
        mark_events,
        stasis_events,
        player_deaths,
    ) if options["markReviewEnabled"] else {"players": [], "cycleCount": 0}
    water = analyze_clinging_murk(
        fight,
        actor_map,
        player_catalog,
        payload["debuffs"],
        position_index,
        options,
        mark_events,
        player_deaths,
    ) if options["waterPlacementReviewEnabled"] else {"rounds": [], "roundCount": 0}
    droplets = analyze_toxic_droplets(
        fight,
        actor_map,
        payload["casts"],
        payload["damage"],
        player_catalog,
        payload.get("friendlyCasts") or [],
        player_deaths,
        position_index,
    ) if options["toxicDropletReviewEnabled"] else {"rounds": [], "missedRoundCount": 0}
    living = analyze_living_venom(
        fight, actor_map, payload["damage"], player_deaths, player_catalog
    ) if options["livingVenomReviewEnabled"] else {
        "spellID": LIVING_VENOM_ID, "players": [], "totalHits": 0, "totalDamage": 0,
    }
    duration_ms = int(fight["endTime"] - fight["startTime"])
    started_at = datetime.fromtimestamp((report_start + fight["startTime"]) / 1000, tz=CN_TZ)
    difficulty = int(fight.get("difficulty") or 0)
    difficulty_names = {1: "LFR", 2: "普通", 3: "普通", 4: "英雄", 5: "史诗"}
    difficulty_name = difficulty_names.get(difficulty, f"难度{difficulty}" if difficulty else "未知")
    failure_names = [failure["player"] for row in helical["rounds"] for failure in row["failures"]]
    if failure_names:
        wipe_reason = f"螺旋毒素超时：{'、'.join(failure_names)}"
    elif droplets["missedRoundCount"]:
        wipe_reason = f"剧毒水滴漏踩 {droplets['missedRoundCount']} 轮"
    else:
        wipe_reason = "击杀复盘" if fight.get("kill") else "死亡链待复核"
    survival_spell_names = load_confirmed_spell_names()
    survival_spell_names.update({
        LIVING_VENOM_ID: "活体毒液",
        TOXIC_DROPLETS_HIT_ID: "剧毒水滴",
        NOXIOUS_BLAST_ID: "剧毒冲击",
        CULTIVATED_BURST_DAMAGE_ID: "培育爆裂",
    })
    survival = build_survival_timeline(
        fight, actor_map, player_catalog, player_deaths, payload.get("friendlyCasts") or [],
        survival_spell_names,
    )
    return {
        "reportID": report_id,
        "fightID": fight["id"],
        "difficulty": difficulty,
        "difficultyName": difficulty_name,
        "date": started_at.strftime("%Y-%m-%d"),
        "startClock": started_at.strftime("%H:%M:%S"),
        "startTimeIso": started_at.isoformat(),
        "isKill": bool(fight.get("kill")),
        "kill": bool(fight.get("kill")),
        "bossPercentage": float(fight.get("bossPercentage") or 0),
        "durationMs": duration_ms,
        "duration": fmt_ms(duration_ms),
        "wipePhase": "击杀" if fight.get("kill") else "分场/静滞循环",
        "wipeReason": wipe_reason,
        "summary": f"{helical['roundCount']} 次强酸静滞，{helical['wrongCollisionCount']} 次错误碰撞，{helical['failedRoundCount']} 轮超时；活体毒液 {living['totalHits']} 次命中。",
        "phaseTimeline": phase_timeline(fight, stasis_events),
        "wclDeepLink": f"https://www.warcraftlogs.com/reports/{report_id}#fight={fight['id']}&type=summary",
        "players": list(player_catalog.values()),
        "survival": survival,
        "deathTimeline": survival["timeline"],
        **difficulty_fields(fight),
        "sentinels": {
            "helicalToxins": helical,
            "marks": marks,
            "clingingMurk": water,
            "toxicDroplets": droplets,
            "livingVenom": living,
        },
        "avoidableSummary": {"1284209": living["players"]},
    }


def merge_living_venom(global_rows, fight):
    for row in fight["sentinels"]["livingVenom"]["players"]:
        target = global_rows.get(row["playerID"])
        if target is None:
            target = {**row, "events": []}
            global_rows[row["playerID"]] = target
        else:
            target["hitCount"] += row["hitCount"]
            target["totalDamage"] += row["totalDamage"]
            target["maxHit"] = max(target["maxHit"], row["maxHit"])
            target["deathCount"] += row["deathCount"]
        target["events"].extend({**event, "fightID": fight["fightID"]} for event in row["events"])


def _mechanic_overview(rendered):
    high_stack_deaths = []
    spear_hits = []
    spear_death_count = 0
    first_wrong_collisions = []
    for pull in rendered:
        mechanics = pull.get("sentinels") or {}
        for row in (mechanics.get("marks") or {}).get("deathOverThirty") or []:
            high_stack_deaths.append(nightly_detail(
                pull, row.get("time"),
                f"{row.get('player') or '未知玩家'} 死亡时红 {row.get('bloodStack')} + 绿 {row.get('acidStack')} = {row.get('totalStack')} 层",
                player=row.get("player"), classColor=row.get("classColor"),
            ))
        for row in (mechanics.get("livingVenom") or {}).get("players") or []:
            spear_death_count += int(row.get("deathCount") or 0)
            for event in row.get("events") or []:
                spear_hits.append(nightly_detail(
                    pull, event.get("time"),
                    f"{row.get('player') or '未知玩家'} 命中绿色长矛",
                    player=row.get("player"), classColor=row.get("classColor"), spellID=LIVING_VENOM_ID,
                ))
        for round_row in (mechanics.get("helicalToxins") or {}).get("rounds") or []:
            first = next((row for row in round_row.get("collisions") or [] if row.get("firstWrongCollision")), None)
            if not first:
                continue
            names = "、".join(row.get("player") or "未知玩家" for row in first.get("players") or [])
            first_wrong_collisions.append(nightly_detail(
                pull, first.get("time"),
                f"本轮第一次错误碰撞：{names or first.get('collisionCombination') or '未识别组合'}",
            ))
    return {
        "title": "整夜机制统计",
        "subtitle": "按所有 Pull 汇总死亡层数、绿色长矛与每轮第一次错误碰撞。",
        "metrics": [
            {
                "key": "deathOverThirty", "label": "死亡时红绿总层数超过 30", "value": len(high_stack_deaths), "unit": "次",
                "tone": "danger", "description": "读取死亡前一毫秒的红色与绿色印记层数，总和严格大于 30 才计数。",
                "players": nightly_player_totals(high_stack_deaths), "events": high_stack_deaths,
            },
            {
                "key": "greenSpearHits", "label": "绿色长矛命中 / 死亡", "value": f"{len(spear_hits)} / {spear_death_count}", "unit": "次",
                "tone": "warning", "description": "前一个数字为绿色长矛伤害命中总人次，后一个数字为该技能致死次数。",
                "players": nightly_player_totals(spear_hits), "events": spear_hits,
            },
            {
                "key": "firstWrongCollisions", "label": "团队内第一个撞错", "value": len(first_wrong_collisions), "unit": "次",
                "tone": "danger", "description": "每一轮螺旋毒素最多计一次，只取该轮第一次明确的错误碰撞。",
                "players": [], "events": first_wrong_collisions,
            },
        ],
    }


def build_aggregated_json(report_ids, options=None):
    from analyzer_core.analysis_scope import filter_fights

    options = {**DEFAULT_OPTIONS, **(options or {})}
    report_id_list = [value for value in (item.strip() for item in report_ids.replace(" ", "").split(",")) if value]
    if not report_id_list:
        raise RuntimeError("请传入至少一个 WCL report ID。")
    client = WclClient()
    rendered = []
    progress("读取 2 号 Boss Pull 列表", 8)
    for report_id in report_id_list:
        report = client.report_fights(report_id)
        fights = filter_fights(report_id, [
            fight for fight in report["fights"]
            if int(fight.get("encounterID") or 0) in ENCOUNTER_IDS
            and int(fight["endTime"] - fight["startTime"]) >= 20_000
        ])
        actor_rows = client.actors(report_id)
        actor_map = {row["id"]: row["name"] for row in actor_rows}
        actor_type = {row["id"]: row.get("type") for row in actor_rows}
        progress(f"{report_id}：匹配 {len(fights)} 场", 12)

        def fetch_one(index_and_fight):
            index, fight = index_and_fight
            progress(f"读取 Fight {fight['id']}（{index}/{len(fights)}）")
            payload = fetch_payload(client, report_id, fight, options)
            return index, analyze_report_fight(
                report_id,
                report["startTime"],
                actor_map,
                actor_type,
                fight,
                payload,
                options,
            )

        for _, row in run_parallel_indexed(list(enumerate(fights, start=1)), fetch_one):
            rendered.append(row)
    rendered.sort(key=lambda row: (row["date"], row["reportID"], row["fightID"]))
    global_living = {}
    for fight in rendered:
        merge_living_venom(global_living, fight)
    progress("生成陵寝哨兵转阶段与场地分析", 96)
    return {
        "code": 200,
        "meta": {
            "version": "12.1",
            "raidKey": "venomous_abyss",
            "raidName": "烈毒之渊",
            "bossKey": "sentinels",
            "bossName": "陵寝哨兵",
            "analyzedReports": report_id_list,
            "mechanicVersion": "sentinels-helical-collision-movement-v4-2026-08-25",
            "features": {"interrupts": False, "dispels": False, "fieldReplay": False, "mistakes": False},
            "capabilities": {
                "wipe": {"enabled": True, "renderer": "sentinels-pulls"},
                "avoidable": {"enabled": True, "renderer": "sentinels-avoidable"},
                "replay": {"enabled": False, "renderer": "sentinels-field"},
                "mistakes": {"enabled": False, "renderer": "mistake-tracker"},
                "verdict": {"enabled": False, "renderer": "mistake-verdict"},
            },
            "analysisConfig": options,
        },
        "data": {
            "page1_wipeAnalysis": rendered,
            "page2_avoidableBoard": {"1284209": sorted(global_living.values(), key=lambda row: (row["deathCount"], row["hitCount"], row["totalDamage"]), reverse=True)},
            "mechanicOverview": _mechanic_overview(rendered),
        },
    }


def analyze(report_ids: str, output_path=None, catalog_entry=None, options=None, progress_callback=None):
    result = build_aggregated_json(report_ids, options=options)
    return write_json_result(result, output_path, catalog_entry=catalog_entry)


def debug_analyze(report_id, fight_id=None, output_path=None, options=None):
    """Quick command-line entry point for full-report or isolated-fight checks."""
    from analyzer_core.analysis_scope import single_fight_scope

    output = Path(output_path) if output_path else Path("data") / (
        f"wcl_{report_id}_sentinels_fight{fight_id}.json" if fight_id else
        f"wcl_{report_id}_sentinels_all.json"
    )
    if fight_id is None:
        result = build_aggregated_json(report_id, options=options)
    else:
        with single_fight_scope(report_id, int(fight_id)):
            result = build_aggregated_json(report_id, options=options)
    path = write_json_result(result, output)
    fights = result.get("data", {}).get("page1_wipeAnalysis", [])
    summary = {
        "output": str(path.resolve()),
        "fightCount": len(fights),
        "fightIDs": [row.get("fightID") for row in fights],
        "wrongCollisions": sum(
            row.get("sentinels", {}).get("helicalToxins", {}).get("wrongCollisionCount", 0)
            for row in fights
        ),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return path


def debug_main(argv=None):
    parser = argparse.ArgumentParser(description="陵寝哨兵 WCL 分析调试入口")
    parser.add_argument("--debug", action="store_true", help="启用调试入口")
    parser.add_argument("--report", required=True, help="WCL report ID")
    parser.add_argument("--fight", type=int, help="只分析指定 Fight；省略则分析整份 report")
    parser.add_argument("--output", help="输出 JSON 路径")
    args = parser.parse_args(argv)
    if not args.debug:
        parser.error("请添加 --debug，避免误触发联网分析。")
    debug_analyze(args.report, args.fight, args.output)


if __name__ == "__main__":
    debug_main()
