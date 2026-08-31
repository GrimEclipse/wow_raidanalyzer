"""Evidence-first analyzer for the Lost Explorers."""

from __future__ import annotations

from collections import Counter, defaultdict
import math

from boss_plugins.common import COMBAT_RES_SPELLS, write_json_result
from boss_plugins.venomous_abyss.runtime import build_aggregated_json as _build
from boss_plugins.venomous_abyss.shared import (
    IMMUNITY_SPELLS,
    ability_id,
    actor_name,
    avoidable_board as _avoidable_board,
    completed_casts as _completed_casts,
    event_amount,
    event_type,
    events_between as _events_between,
    fmt_ms,
    build_position_index,
    group_nearby,
    load_confirmed_source_names,
    load_confirmed_spell_names,
    player_ref,
    position_at_interpolated,
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
    "mechanicVersion": "lostexplorers-mythic-2026-08-31-frostfire-death-grace-mushroom-wave-v6",
    "features": {"survival": True, "fieldReplay": False},
    "fetchCastResources": True,
    "fetchPositionResources": True,
    "trackedActorGameIDs": {272110},
    "trackedActorEventFilters": ["source.id = 272110 OR target.id = 272110"],
}

THROW_JUNK_IMPACT = 1291935
MYTHIC_SPLINTERS = 1312853
RELIC_RUPTURE = 1310028
STOMP = 1306692
CRATE_WARNING_DELAY_MS = 15_000
MAX_ALLOWED_SPLINTER_STACK = 2
FROSTFIRE_EXPECTED_PER_COLOR = 5
FROSTFIRE_EARLY_DEATH_GRACE_MS = 2_000
FROSTFIRE_DEATH_REMOVE_WINDOW_MS = 500
RAID_COLLAPSE_DEATH_THRESHOLD = 8
SHELL_SPREAD_ANGLE_RADIANS = math.radians(20)
SHELL_MIDDLE_RADIUS = 800
SHELL_RAY_LENGTH = 10_000
SHELL_ARENA_CENTER = (-47_018.0, 69_725.0)

def _frostfire_remove(debuffs, player_id, debuff_id, applied_at, fight_end):
    return next((event for event in debuffs if event.get("targetID") == player_id
                 and int(ability_id(event) or 0) == debuff_id
                 and event_type(event) == "removedebuff"
                 and applied_at <= int(event.get("timestamp") or 0) <= fight_end), None)


def _first_player_death(deaths, player_id, start, end):
    return min(
        (
            event for event in deaths
            if event.get("targetID") == player_id
            and start <= int(event.get("timestamp") or 0) <= end
        ),
        key=lambda event: int(event.get("timestamp") or 0),
        default=None,
    )

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

def _crate_entity_at(timestamp, tracked_actor_events):
    stomps = [
        event for event in tracked_actor_events
        if event_type(event) == "instakill"
        and int(ability_id(event) or 0) == STOMP
        and event.get("targetID") is not None
        and event.get("targetInstance") is not None
        and abs(int(event.get("timestamp") or 0) - timestamp) <= 500
    ]
    stomp = min(
        stomps,
        key=lambda event: abs(int(event.get("timestamp") or 0) - timestamp),
        default=None,
    )
    deaths = [
        event for event in tracked_actor_events
        if event_type(event) == "death"
        and event.get("targetInstance") is not None
        and abs(int(event.get("timestamp") or 0) - timestamp) <= 500
    ]
    if stomp:
        matching_deaths = [
            event for event in deaths
            if event.get("targetID") == stomp.get("targetID")
            and event.get("targetInstance") == stomp.get("targetInstance")
        ]
        death = min(
            matching_deaths,
            key=lambda event: abs(int(event.get("timestamp") or 0) - int(stomp.get("timestamp") or 0)),
            default=None,
        )
    else:
        death = min(
            deaths,
            key=lambda event: abs(int(event.get("timestamp") or 0) - timestamp),
            default=None,
        )
    lifecycle_event = stomp or death
    actor_id = lifecycle_event.get("targetID") if lifecycle_event else None
    instance = lifecycle_event.get("targetInstance") if lifecycle_event else None
    coordinate_events = [
        event for event in tracked_actor_events
        if event.get("x") is not None and event.get("y") is not None
        and (
            (actor_id is not None and event.get("sourceID") == actor_id and event.get("sourceInstance") == instance)
            or (lifecycle_event is None and abs(int(event.get("timestamp") or 0) - timestamp) <= 1500)
        )
    ]
    coordinate = min(
        coordinate_events,
        key=lambda event: abs(int(event.get("timestamp") or 0) - timestamp),
        default=None,
    )
    if lifecycle_event is None and coordinate is not None:
        actor_id = coordinate.get("sourceID")
        instance = coordinate.get("sourceInstance")
    if lifecycle_event is None and coordinate is None:
        return None
    spawn = next(
        (
            event for event in tracked_actor_events
            if event_type(event) == "summon"
            and event.get("targetID") == actor_id
            and event.get("targetInstance") == instance
        ),
        None,
    )
    trigger_timestamp = int((stomp or death or {}).get("timestamp") or timestamp)
    spawn_timestamp = int(spawn.get("timestamp") or 0) if spawn else None
    age_ms = trigger_timestamp - spawn_timestamp if spawn_timestamp is not None else None
    return {
        "actorID": actor_id,
        "instance": instance,
        "spawnTimestamp": spawn_timestamp,
        "triggerTimestamp": trigger_timestamp,
        "stompTimestamp": int(stomp.get("timestamp") or 0) if stomp else None,
        "triggerEvidence": "explicit-stomp" if stomp else "death-alignment",
        "ageMs": age_ms,
        "ageSec": round(age_ms / 1000, 3) if age_ms is not None else None,
        "premature": age_ms is not None and 0 <= age_ms < CRATE_WARNING_DELAY_MS,
        "lifecyclePhase": (
            "落地等待期"
            if age_ms is not None and 0 <= age_ms < CRATE_WARNING_DELAY_MS
            else ("遗物爆裂警示期" if age_ms is not None else "箱龄未知")
        ),
        "deathTimestamp": int(death.get("timestamp") or 0) if death else None,
        "position": {"x": float(coordinate["x"]), "y": float(coordinate["y"])} if coordinate else None,
        "positionTimestamp": int(coordinate.get("timestamp") or 0) if coordinate else None,
        "positionSpellID": int(ability_id(coordinate) or 0) if coordinate else None,
    }

def _confirmed_crate_stepper(timestamp, crate, player_positions, actor_map, players):
    if not crate or not crate.get("position"):
        return None, []
    box = crate["position"]
    candidates = []
    for player_id in players:
        position = position_at_interpolated(
            player_positions,
            player_id,
            timestamp,
            reliable_window_ms=1500,
            fallback_window_ms=2500,
        )
        if not position:
            continue
        distance = (((position["x"] - box["x"]) ** 2 + (position["y"] - box["y"]) ** 2) ** 0.5) / 100
        candidates.append({
            **player_ref(players, actor_map, player_id),
            "distanceYards": round(distance, 2),
            "positionReliable": bool(position.get("reliable")),
            "sampleOffsetMs": position.get("sampleOffsetMs"),
        })
    candidates.sort(key=lambda row: row["distanceYards"])
    nearest = candidates[0] if candidates else None
    runner_up = candidates[1] if len(candidates) > 1 else None
    confirmed = (
        nearest
        if nearest
        and nearest["positionReliable"]
        and nearest["distanceYards"] <= 5
        and (runner_up is None or runner_up["distanceYards"] - nearest["distanceYards"] >= 1.5)
        else None
    )
    return confirmed, candidates[:3]

def _splinter_activations(fight, actor_map, players, debuffs, damage, resources=None, tracked_actor_events=None):
    """Track Mythic raid-wide Splinters pulses and align them to crate entities."""
    resources = resources or []
    tracked_actor_events = tracked_actor_events or []
    player_positions = build_position_index(resources + damage + debuffs)
    splinters = [
        event for event in debuffs
        if int(ability_id(event) or 0) == MYTHIC_SPLINTERS
        and event_type(event) in {"applydebuff", "applydebuffstack"}
        and event.get("targetID") in players
    ]
    rows = []
    for index, group in enumerate(group_nearby(splinters, window_ms=250), start=1):
        timestamp = min(int(event.get("timestamp") or 0) for event in group)
        peak_stack = max((int(event.get("stack") or 1) for event in group), default=1)
        affected_ids = sorted(
            {event.get("targetID") for event in group if event.get("targetID") in players},
            key=lambda value: actor_name(actor_map, value),
        )
        impact_events = [
            event for event in damage
            if abs(int(event.get("timestamp") or 0) - timestamp) <= 800
            and int(ability_id(event) or 0) == THROW_JUNK_IMPACT
            and event.get("targetID") in players
        ]
        impact_ids = sorted(
            {
                event.get("targetID") for event in impact_events
            },
            key=lambda value: actor_name(actor_map, value),
        )
        crate = _crate_entity_at(timestamp, tracked_actor_events)
        confirmed_stepper, nearest_players = (None, [])
        if crate and crate.get("premature"):
            confirmed_stepper, nearest_players = _confirmed_crate_stepper(
                timestamp, crate, player_positions, actor_map, players,
            )
        direct_impact_player = None
        if crate and crate.get("premature") and len(impact_ids) == 1:
            spawn_timestamp = crate.get("spawnTimestamp")
            direct_hit = min(
                (event for event in impact_events if event.get("targetID") == impact_ids[0]),
                key=lambda event: abs(int(event.get("timestamp") or 0) - timestamp),
                default=None,
            )
            if (
                direct_hit is not None
                and spawn_timestamp is not None
                and 0 <= int(direct_hit.get("timestamp") or 0) - spawn_timestamp <= 1000
                and 0 <= timestamp - spawn_timestamp <= 1500
            ):
                direct_impact_player = player_ref(players, actor_map, impact_ids[0])
        is_violation = peak_stack > MAX_ALLOWED_SPLINTER_STACK
        is_premature_stack_violation = bool(
            is_violation
            and crate
            and crate.get("premature")
            and not direct_impact_player
        )
        rows.append({
            "index": index,
            "timestamp": timestamp,
            "timeMs": timestamp - fight["startTime"],
            "time": fmt_ms(timestamp - fight["startTime"]),
            "stack": peak_stack,
            "isViolation": is_violation,
            "isPrematureStackViolation": is_premature_stack_violation,
            "premature": bool(crate and crate.get("premature")),
            "directImpactPlayer": direct_impact_player,
            "requiresStepperAttribution": is_premature_stack_violation,
            "affectedPlayers": [player_ref(players, actor_map, player_id) for player_id in affected_ids],
            "affectedCount": len(affected_ids),
            "boxEntity": crate,
            "confirmedStepper": confirmed_stepper,
            "nearestPlayers": nearest_players,
            "attributionStatus": (
                "direct-impact"
                if direct_impact_player
                else (
                    "confirmed-by-box-position"
                    if confirmed_stepper
                    else (
                        "box-instance-unmatched"
                        if not crate
                        else (
                            "timer-expired"
                            if crate.get("premature") is False
                            else (
                                "box-position-missing"
                                if not crate.get("position")
                                else "ambiguous-position"
                            )
                        )
                    )
                )
            ),
            "impactPlayers": [player_ref(players, actor_map, player_id) for player_id in impact_ids],
        })
    return rows

def _blast_wave_summary(fight, actor_map, players, damage):
    hits = [
        event for event in damage
        if int(ability_id(event) or 0) == 1305844 and event.get("targetID") in players
    ]
    by_player = defaultdict(list)
    for hit in hits:
        by_player[hit.get("targetID")].append(hit)
    rows = []
    for player_id in sorted(by_player, key=lambda value: (-len(by_player[value]), actor_name(actor_map, value))):
        events = by_player[player_id]
        rows.append({
            **player_ref(players, actor_map, player_id),
            "hitCount": len(events),
            "events": [
                {
                    "timestamp": int(event["timestamp"]),
                    "timeMs": int(event["timestamp"]) - fight["startTime"],
                    "time": fmt_ms(int(event["timestamp"]) - fight["startTime"]),
                }
                for event in events
            ],
        })
    return {"spellID": 1305844, "totalHitCount": len(hits), "players": rows}

def _mushroom_activations(
    fight, actor_map, players, casts, debuffs, damage=None, deaths=None,
    friendly_casts=None, resources=None,
):
    """Attribute mushroom activation and its Explosive Surprise shockwave cycle."""
    damage = damage or []
    deaths = deaths or []
    friendly_casts = friendly_casts or []
    resources = resources or []
    player_positions = build_position_index(resources + damage + debuffs)
    mushroom_casts = sorted(
        (
            event for event in casts
            if int(ability_id(event) or 0) == 1299855
            and event_type(event) == "cast"
        ),
        key=lambda event: int(event.get("timestamp") or 0),
    )
    bounce_events = sorted(
        (
            event for event in debuffs
            if int(ability_id(event) or 0) == 1299854
            and event_type(event) == "applydebuff"
            and event.get("targetID") in players
        ),
        key=lambda event: int(event.get("timestamp") or 0),
    )
    surprise_applies = sorted(
        (
            event for event in debuffs
            if int(ability_id(event) or 0) == 1297625
            and event_type(event) == "applydebuff"
            and event.get("targetID") in players
        ),
        key=lambda event: int(event.get("timestamp") or 0),
    )
    grouped = defaultdict(list)
    anonymous_groups = []
    for event in bounce_events:
        instance = event.get("sourceInstance")
        if instance is not None:
            grouped[instance].append(event)
            continue
        timestamp = int(event.get("timestamp") or 0)
        if not anonymous_groups or timestamp - int(anonymous_groups[-1][-1].get("timestamp") or 0) > 5000:
            anonymous_groups.append([])
        anonymous_groups[-1].append(event)
    event_groups = list(grouped.values()) + anonymous_groups
    event_groups.sort(key=lambda rows: min(int(event.get("timestamp") or 0) for event in rows))
    rows = []
    used_casts = set()
    for index, events in enumerate(event_groups, start=1):
        timestamp = min(int(event.get("timestamp") or 0) for event in events)
        source_instance = events[0].get("sourceInstance")
        cast_candidates = [
            cast for cast in mushroom_casts
            if id(cast) not in used_casts
            and (
                cast.get("sourceInstance") == source_instance
                if source_instance is not None
                else cast.get("sourceInstance") is None
            )
            and int(cast.get("timestamp") or 0) <= timestamp + 250
        ]
        mushroom_cast = max(
            cast_candidates,
            key=lambda event: int(event.get("timestamp") or 0),
            default=None,
        )
        if mushroom_cast is not None:
            used_casts.add(id(mushroom_cast))
        position = (
            {
                "x": float(mushroom_cast["x"]),
                "y": float(mushroom_cast["y"]),
            }
            if mushroom_cast is not None
            and mushroom_cast.get("x") is not None
            and mushroom_cast.get("y") is not None
            else None
        )
        first_ids = []
        for event in events:
            player_id = event.get("targetID")
            if int(event.get("timestamp") or 0) == timestamp and player_id not in first_ids:
                first_ids.append(player_id)
        all_ids = sorted({event.get("targetID") for event in events}, key=lambda value: actor_name(actor_map, value))
        distance_rows = []
        if position:
            for player_id in players:
                player_position = position_at_interpolated(
                    player_positions,
                    player_id,
                    timestamp,
                    reliable_window_ms=1500,
                    fallback_window_ms=2500,
                )
                if not player_position:
                    continue
                distance = (
                    (
                        (player_position["x"] - position["x"]) ** 2
                        + (player_position["y"] - position["y"]) ** 2
                    ) ** 0.5
                ) / 100
                distance_rows.append({
                    **player_ref(players, actor_map, player_id),
                    "distanceYards": round(distance, 2),
                    "positionReliable": bool(player_position.get("reliable")),
                    "sampleOffsetMs": player_position.get("sampleOffsetMs"),
                })
        distance_rows.sort(key=lambda row: row["distanceYards"])
        distance_by_player = {row["playerID"]: row for row in distance_rows}
        trigger_candidates = []
        for player_id in first_ids:
            trigger = player_ref(players, actor_map, player_id)
            if player_id in distance_by_player:
                trigger.update({
                    key: distance_by_player[player_id][key]
                    for key in ("distanceYards", "positionReliable", "sampleOffsetMs")
                })
                trigger["positionConfirmed"] = bool(
                    trigger["positionReliable"] and trigger["distanceYards"] <= 5
                )
            else:
                trigger["positionConfirmed"] = False
            trigger_candidates.append(trigger)
        confirmed_candidates = [row for row in trigger_candidates if row.get("positionConfirmed")]
        if confirmed_candidates:
            selected_trigger = min(confirmed_candidates, key=lambda row: row.get("distanceYards", float("inf")))
        elif trigger_candidates:
            selected_trigger = min(trigger_candidates, key=lambda row: row.get("distanceYards", float("inf")))
        else:
            selected_trigger = None
        trigger_players = [selected_trigger] if selected_trigger else []
        position_confirmed = bool(selected_trigger and selected_trigger.get("positionConfirmed"))
        runner_up_distance = min(
            (
                row.get("distanceYards") for row in trigger_candidates
                if row is not selected_trigger and row.get("distanceYards") is not None
            ),
            default=None,
        )
        spawn_timestamp = int(mushroom_cast.get("timestamp") or 0) if mushroom_cast else None
        activation_delay_ms = max(0, timestamp - spawn_timestamp) if spawn_timestamp is not None else None
        prior_deaths = sorted(
            (
                death for death in deaths
                if death.get("targetID") in players
                and int(death.get("timestamp") or 0) < timestamp
            ),
            key=lambda death: int(death.get("timestamp") or 0),
        )
        prior_death_ids = sorted(
            {death.get("targetID") for death in prior_deaths},
            key=lambda player_id: actor_name(actor_map, player_id),
        )
        raid_already_collapsed = len(prior_deaths) >= RAID_COLLAPSE_DEATH_THRESHOLD

        cycle_anchor = spawn_timestamp if spawn_timestamp is not None else timestamp
        surprise_candidates = [
            event for event in surprise_applies
            if abs(int(event.get("timestamp") or 0) - cycle_anchor) <= 2_000
        ]
        surprise_apply = min(
            surprise_candidates,
            key=lambda event: abs(int(event.get("timestamp") or 0) - cycle_anchor),
            default=None,
        )
        surprise_apply_timestamp = int(surprise_apply.get("timestamp") or 0) if surprise_apply else None
        surprise_target_id = surprise_apply.get("targetID") if surprise_apply else None
        next_surprise_apply_timestamp = next(
            (
                int(event.get("timestamp") or 0) for event in surprise_applies
                if surprise_apply_timestamp is not None
                and int(event.get("timestamp") or 0) > surprise_apply_timestamp
            ),
            None,
        )
        surprise_remove = next(
            (
                event for event in debuffs
                if surprise_target_id is not None
                and event.get("targetID") == surprise_target_id
                and int(ability_id(event) or 0) == 1297625
                and event_type(event) == "removedebuff"
                and int(event.get("timestamp") or 0) >= surprise_apply_timestamp
                and (
                    next_surprise_apply_timestamp is None
                    or int(event.get("timestamp") or 0) < next_surprise_apply_timestamp
                )
            ),
            None,
        )
        surprise_remove_timestamp = int(surprise_remove.get("timestamp") or 0) if surprise_remove else None
        if surprise_remove_timestamp is not None:
            # Explosive Surprise fading is the observable start of the shockwave
            # mechanic.  There is no fixed ten-second delay: activating the
            # mushroom before this boundary consumes it before the wave arrives.
            mechanic_arrival_timestamp = surprise_remove_timestamp
            expected_wave_timestamp = surprise_remove_timestamp
            wave_window_start = surprise_remove_timestamp - 1_000
            wave_window_end = next_surprise_apply_timestamp or int(fight["endTime"])
            trigger_offset_from_remove_ms = timestamp - surprise_remove_timestamp
            premature_activation = timestamp < surprise_remove_timestamp
            timing_basis = "explosive-surprise-remove"
        else:
            # Old/partial payloads can omit the aura removal.  Keep the spawn-age
            # fallback only for those payloads; actual blast damage still anchors
            # the replay below.
            mechanic_arrival_timestamp = None
            expected_wave_timestamp = spawn_timestamp + 22_200 if spawn_timestamp is not None else timestamp
            wave_window_start = expected_wave_timestamp - 5_200
            wave_window_end = min(expected_wave_timestamp + 4_800, int(fight["endTime"]))
            trigger_offset_from_remove_ms = None
            premature_activation = activation_delay_ms is not None and activation_delay_ms <= 5_000
            timing_basis = "mushroom-spawn-fallback"
        blast_candidates = [
            event for event in damage
            if int(ability_id(event) or 0) == 1305844
            and event.get("targetID") in players
            and wave_window_start <= int(event.get("timestamp") or 0) < wave_window_end
        ]
        actual_wave_timestamp = min(
            (int(event.get("timestamp") or 0) for event in blast_candidates),
            default=None,
        )
        bounce_wave_timestamp = min(
            (
                int(event.get("timestamp") or 0) for event in events
                if wave_window_start <= int(event.get("timestamp") or 0) < wave_window_end
            ),
            default=None,
        )
        wave_timestamp = (
            actual_wave_timestamp
            or mechanic_arrival_timestamp
            or bounce_wave_timestamp
            or expected_wave_timestamp
        )
        wave_hit_ids = sorted(
            {event.get("targetID") for event in blast_candidates},
            key=lambda value: actor_name(actor_map, value),
        )
        wave_deaths = []
        seen_wave_death_ids = set()
        death_window_end = min(wave_timestamp + 8_000, wave_window_end)
        for death in sorted(deaths, key=lambda row: int(row.get("timestamp") or 0)):
            death_timestamp = int(death.get("timestamp") or 0)
            death_player_id = death.get("targetID")
            killing_spell_id = int(death.get("killingAbilityGameID") or ability_id(death) or 0)
            if death_player_id not in players:
                continue
            if death_player_id in seen_wave_death_ids:
                continue
            if not wave_timestamp - 2_500 <= death_timestamp <= death_window_end:
                continue
            if killing_spell_id not in {0, 3, 1305844}:
                continue
            seen_wave_death_ids.add(death_player_id)
            wave_deaths.append({
                **player_ref(players, actor_map, death_player_id),
                "timestamp": death_timestamp,
                "timeMs": death_timestamp - fight["startTime"],
                "time": fmt_ms(death_timestamp - fight["startTime"]),
                "killingSpellID": killing_spell_id or None,
                "cause": "blast-wave" if killing_spell_id == 1305844 else "fall-or-unattributed",
            })
        alive_before_wave = _alive_players_at(
            players, deaths, friendly_casts, wave_timestamp - 2_500,
        )
        majority_threshold = max(1, len(alive_before_wave) // 2 + 1)
        majority_wave_deaths = len(wave_deaths) >= majority_threshold
        mass_wave_deaths = len(wave_deaths) >= 5
        fight_end_delta_ms = int(fight["endTime"]) - wave_timestamp
        fight_ends_near_wave = bool(wave_deaths) and -2_000 <= fight_end_delta_ms <= 10_000
        wave_caused_wipe = mass_wave_deaths or fight_ends_near_wave
        premature_caused_wipe = (
            premature_activation
            and wave_caused_wipe
            and not raid_already_collapsed
        )
        rows.append({
            "index": index,
            "timeMs": timestamp - fight["startTime"],
            "time": fmt_ms(timestamp - fight["startTime"]),
            "sourceInstance": source_instance,
            "mushroomEntity": {
                "actorID": mushroom_cast.get("sourceID") if mushroom_cast else events[0].get("sourceID"),
                "instance": mushroom_cast.get("sourceInstance") if mushroom_cast else source_instance,
                "spawnCastTimestamp": spawn_timestamp,
                "spawnTime": (
                    fmt_ms(int(mushroom_cast.get("timestamp") or 0) - fight["startTime"])
                    if mushroom_cast else None
                ),
                "position": position,
                "positionSpellID": 1299855 if position else None,
            },
            "triggerPlayers": trigger_players,
            "firstBounceTargets": trigger_candidates,
            "simultaneousFirstTargetCount": len(trigger_candidates),
            "positionSelectionMarginYards": (
                round(runner_up_distance - selected_trigger["distanceYards"], 2)
                if selected_trigger
                and selected_trigger.get("distanceYards") is not None
                and runner_up_distance is not None
                else None
            ),
            "triggerConfidence": (
                "simultaneous-first-bounce-nearest-position"
                if position_confirmed and len(trigger_candidates) > 1
                else ("first-bounce-target-and-position" if position_confirmed else "first-bounce-target")
            ),
            "positionConfirmed": position_confirmed,
            "nearestPlayers": distance_rows[:3],
            "affectedPlayers": [player_ref(players, actor_map, player_id) for player_id in all_ids],
            "activationDelayMs": activation_delay_ms,
            "prematureActivation": premature_activation,
            "priorDeathCount": len(prior_deaths),
            "priorUniqueDeathCount": len(prior_death_ids),
            "priorDeathPlayers": [
                player_ref(players, actor_map, player_id) for player_id in prior_death_ids
            ],
            "raidCollapseDeathThreshold": RAID_COLLAPSE_DEATH_THRESHOLD,
            "raidAlreadyCollapsed": raid_already_collapsed,
            "attributionSuppressedReason": (
                f"触发前已有 {len(prior_deaths)} 次玩家死亡，达到大团崩溃阈值 {RAID_COLLAPSE_DEATH_THRESHOLD}"
                if raid_already_collapsed else None
            ),
            "timingBasis": timing_basis,
            "triggerOffsetFromSurpriseRemoveMs": trigger_offset_from_remove_ms,
            "explosiveSurprise": {
                "spellID": 1297625,
                "target": player_ref(players, actor_map, surprise_target_id) if surprise_target_id else None,
                "applyTimestamp": surprise_apply_timestamp,
                "applyTime": fmt_ms(surprise_apply_timestamp - fight["startTime"]) if surprise_apply_timestamp else None,
                "removeTimestamp": surprise_remove_timestamp,
                "removeTime": fmt_ms(surprise_remove_timestamp - fight["startTime"]) if surprise_remove_timestamp else None,
                "nextApplyTimestamp": next_surprise_apply_timestamp,
            },
            "expectedWaveTimestamp": expected_wave_timestamp,
            "mechanicArrivalTimestamp": mechanic_arrival_timestamp,
            "waveTimestamp": wave_timestamp,
            "waveTimeMs": wave_timestamp - fight["startTime"],
            "waveTime": fmt_ms(wave_timestamp - fight["startTime"]),
            "waveTimestampSource": (
                "blast-damage" if actual_wave_timestamp is not None
                else (
                    "explosive-surprise-remove" if mechanic_arrival_timestamp is not None
                    else ("bounce-window" if bounce_wave_timestamp is not None else "spawn-fallback")
                )
            ),
            "waveHitPlayers": [player_ref(players, actor_map, player_id) for player_id in wave_hit_ids],
            "waveDeaths": wave_deaths,
            "aliveBeforeWaveCount": len(alive_before_wave),
            "majorityDeathThreshold": majority_threshold,
            "majorityWaveDeaths": majority_wave_deaths,
            "massWaveDeaths": mass_wave_deaths,
            "fightEndsNearWave": fight_ends_near_wave,
            "fightEndDeltaMs": fight_end_delta_ms,
            "waveCausedWipe": wave_caused_wipe,
            "prematureCausedWipe": premature_caused_wipe,
            "individualWaveFailures": [] if mass_wave_deaths or wave_caused_wipe else wave_deaths,
        })
    return rows

def _distance_to_ray_segment(point, origin, angle, length=SHELL_RAY_LENGTH):
    direction = (math.cos(angle), math.sin(angle))
    delta = (point[0] - origin[0], point[1] - origin[1])
    projected = max(0.0, min(length, delta[0] * direction[0] + delta[1] * direction[1]))
    closest = (
        origin[0] + direction[0] * projected,
        origin[1] + direction[1] * projected,
    )
    return math.dist(point, closest)


def _shell_spin_rounds(fight, actor_map, players, casts, debuffs, resources=None, damage=None):
    shell_hits = [
        event for event in debuffs
        if int(ability_id(event) or 0) == 1291918
        and event_type(event) in {"applydebuff", "refreshdebuff"}
        and event.get("targetID") in players
    ]
    position_index = build_position_index(
        list(resources or []) + list(damage or []) + list(casts or []) + list(debuffs or [])
    )
    middle = {
        "x": SHELL_ARENA_CENTER[0],
        "y": SHELL_ARENA_CENTER[1],
        "radiusYards": SHELL_MIDDLE_RADIUS / 100,
        "method": "scribe-spawn-fixed-center",
    }
    rows = []
    for index, cast in enumerate(_completed_casts(casts, 1296062), start=1):
        timestamp = int(cast.get("timestamp") or 0)
        hit_ids = sorted(
            {
                event.get("targetID") for event in shell_hits
                if timestamp - 1000 <= int(event.get("timestamp") or 0) <= timestamp + 6500
            },
            key=lambda value: actor_name(actor_map, value),
        )
        target_id = cast.get("targetID") if cast.get("targetID") in players else None
        target_role = (players.get(target_id) or {}).get("role") if target_id is not None else None
        ranged_ids = [player_id for player_id in hit_ids if str((players.get(player_id) or {}).get("role") or "").startswith("range-")]
        origin = (
            (float(cast["x"]), float(cast["y"]))
            if cast.get("x") is not None and cast.get("y") is not None
            else None
        )
        target_position = position_at_interpolated(
            position_index, target_id, timestamp,
            reliable_window_ms=2_000, fallback_window_ms=3_000,
        ) if target_id is not None else None
        rays = []
        if origin and target_position and target_position.get("reliable"):
            base_angle = math.atan2(
                target_position["y"] - origin[1],
                target_position["x"] - origin[0],
            )
            for label, offset in (
                ("中线", 0.0),
                ("左侧龟壳", SHELL_SPREAD_ANGLE_RADIANS),
                ("右侧龟壳", -SHELL_SPREAD_ANGLE_RADIANS),
            ):
                angle = base_angle + offset
                direction = (math.cos(angle), math.sin(angle))
                middle_delta = (middle["x"] - origin[0], middle["y"] - origin[1])
                forward_distance = (
                    middle_delta[0] * direction[0] + middle_delta[1] * direction[1]
                )
                distance = (
                    _distance_to_ray_segment((middle["x"], middle["y"]), origin, angle)
                    if middle else None
                )
                rays.append({
                    "label": label,
                    "angleDegrees": round((math.degrees(angle) + 360) % 360, 1),
                    "middleDistanceYards": round(distance / 100, 2) if distance is not None else None,
                    "forwardDistanceYards": round(forward_distance / 100, 2),
                    "crossesMiddle": (
                        distance is not None
                        and forward_distance > 100
                        and distance <= SHELL_MIDDLE_RADIUS
                    ),
                })
        crossed = bool(rays) and any(ray["crossesMiddle"] for ray in rays)
        closest_middle_distance = min(
            (ray["middleDistanceYards"] for ray in rays if ray["middleDistanceYards"] is not None),
            default=None,
        )
        is_named_melee = str(target_role or "").startswith("melee-") or target_role == "tank"
        rows.append({
            "index": index,
            "timeMs": timestamp - fight["startTime"],
            "time": fmt_ms(timestamp - fight["startTime"]),
            "namedPlayer": player_ref(players, actor_map, target_id) if target_id is not None else None,
            "namedRole": target_role,
            "namedMeleePlayer": player_ref(players, actor_map, target_id) if crossed and is_named_melee else None,
            "hitPlayers": [player_ref(players, actor_map, player_id) for player_id in hit_ids],
            "rangedHitPlayers": [player_ref(players, actor_map, player_id) for player_id in ranged_ids],
            "crossedRangedStack": crossed,
            "crossedMiddle": crossed,
            "geometryConfirmed": bool(origin and target_position and target_position.get("reliable") and middle),
            "bossPosition": {"x": origin[0], "y": origin[1]} if origin else None,
            "namedPlayerPosition": (
                {"x": target_position["x"], "y": target_position["y"], "sampleOffsetMs": target_position.get("sampleOffsetMs")}
                if target_position else None
            ),
            "middle": middle,
            "rays": rays,
            "closestMiddleDistanceYards": closest_middle_distance,
            "directionVerdict": (
                "crossed-middle" if crossed
                else ("guided-outward" if rays and middle else "insufficient-position-data")
            ),
        })
    return rows

def _elemental_explosions(fight, actor_map, players, damage, volley_rounds):
    assignments = [assignment for round_row in volley_rounds for assignment in round_row.get("assignments", [])]
    explosion_events = [event for event in damage if int(ability_id(event) or 0) == 1295952]
    rows = []
    for index, group in enumerate(group_nearby(explosion_events, window_ms=250), start=1):
        timestamp = min(int(event.get("timestamp") or 0) for event in group)
        direct_ids = {
            event.get("sourceID") for event in group if event.get("sourceID") in players
        }
        candidates = [
            assignment for assignment in assignments
            if assignment.get("removeTimestamp") is not None
            and abs(int(assignment["removeTimestamp"]) - timestamp) <= 1500
        ]
        pairs = []
        seen = set()
        for fire in (row for row in candidates if row.get("color") == "fire"):
            for frost in (row for row in candidates if row.get("color") == "frost"):
                key = tuple(sorted((fire["playerID"], frost["playerID"])))
                if key in seen:
                    continue
                seen.add(key)
                direct_matches = sum(player_id in direct_ids for player_id in key)
                timing_delta = abs(int(fire["removeTimestamp"]) - int(frost["removeTimestamp"]))
                pairs.append({
                    "firePlayer": player_ref(players, actor_map, fire["playerID"]),
                    "frostPlayer": player_ref(players, actor_map, frost["playerID"]),
                    "timingDeltaMs": timing_delta,
                    "directEvidenceCount": direct_matches,
                    "confidence": "event-source-and-timing" if direct_matches else "synchronized-remove",
                })
        pairs.sort(key=lambda row: (-row["directEvidenceCount"], row["timingDeltaMs"]))
        likely_pair = pairs[0] if pairs and (pairs[0]["directEvidenceCount"] > 0 or len(pairs) == 1) else None
        affected_ids = sorted(
            {event.get("targetID") for event in group if event.get("targetID") in players},
            key=lambda value: actor_name(actor_map, value),
        )
        rows.append({
            "index": index,
            "timeMs": timestamp - fight["startTime"],
            "time": fmt_ms(timestamp - fight["startTime"]),
            "hitCount": len(group),
            "affectedPlayers": [player_ref(players, actor_map, player_id) for player_id in affected_ids],
            "likelyPair": likely_pair,
            "candidatePairs": pairs[:3],
            "candidatePairCount": len(pairs),
            "attributionStatus": "likely" if likely_pair else ("ambiguous-timing" if pairs else "unresolved"),
        })
    return rows

def analyze_throw_junk(
    fight, actor_map, players, casts, damage, debuffs, friendly_buffs, deaths,
    friendly_casts=None, resources=None, tracked_actor_events=None,
):
    """Group Throw Junk casts and report crate-step evidence until the next group."""
    throw_events = [
        event for event in casts
        if int(ability_id(event) or 0) in {1291933, 1306145}
        and event_type(event) == "begincast"
    ]
    throw_groups = group_nearby(throw_events, window_ms=6000)
    immunity_intervals = _immunity_intervals(friendly_buffs, fight["endTime"])
    friendly_casts = friendly_casts or []
    mythic_activations = _splinter_activations(
        fight,
        actor_map,
        players,
        debuffs,
        damage,
        resources=resources,
        tracked_actor_events=tracked_actor_events,
    )
    has_mythic_splinters = bool(mythic_activations)

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
        missing_ids = set() if has_mythic_splinters else alive_ids - stepped_ids - immunity_ids
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
        direct_hit_events = [
            {
                **player_ref(players, actor_map, event.get("targetID")),
                "timestamp": int(event.get("timestamp") or 0),
                "timeMs": int(event.get("timestamp") or 0) - fight["startTime"],
                "time": fmt_ms(int(event.get("timestamp") or 0) - fight["startTime"]),
            }
            for event in sorted(direct_hits, key=lambda row: int(row.get("timestamp") or 0))
        ]
        rupture_hits = [
            event for event in damage
            if start <= int(event.get("timestamp") or 0) < end
            and int(ability_id(event) or 0) in {1310027, 1311587}
            and event.get("targetID") in players
        ]
        round_activations = [row for row in mythic_activations if start <= row["timestamp"] < end]
        rounds.append({
            "index": group_index + 1,
            "timeMs": start - fight["startTime"],
            "time": fmt_ms(start - fight["startTime"]),
            "endTimeMs": end - fight["startTime"],
            "endTime": fmt_ms(end - fight["startTime"]),
            "throwCount": len(group),
            "throwSpellID": 1291933,
            "stepSpellID": 1312853 if has_mythic_splinters else 1308853,
            "evidenceMode": "mythic-raidwide-stacks" if has_mythic_splinters else "legacy-individual-debuff",
            "stepped": stepped,
            "stepCount": len(stepped),
            "immunityPlayers": immunity_rows,
            "immunityCount": len(immunity_rows),
            "missing": missing,
            "missingCount": len(missing),
            "directHitPlayers": [player_ref(players, actor_map, player_id) for player_id in direct_hit_ids],
            "directHitCount": len(direct_hit_events),
            "directHitEvents": direct_hit_events,
            "splinterActivations": round_activations,
            "stackViolations": [row for row in round_activations if row["isViolation"]],
            "relicRuptureSpellID": 1310028,
            "relicRuptureTriggered": bool(rupture_hits),
            "relicRuptureHitCount": len(rupture_hits),
        })
    return {
        "rounds": rounds,
        "roundCount": len(rounds),
        "relicRuptureRoundCount": sum(row["relicRuptureTriggered"] for row in rounds),
        "evidenceMode": "mythic-raidwide-stacks" if has_mythic_splinters else "legacy-individual-debuff",
        "splinterActivations": mythic_activations,
        "stackViolations": [row for row in mythic_activations if row["isViolation"]],
        "stackViolationCount": sum(row["isViolation"] for row in mythic_activations),
        "prematureActivations": [row for row in mythic_activations if row.get("premature")],
        "prematureActivationCount": sum(bool(row.get("premature")) for row in mythic_activations),
        "dangerousStackViolations": [
            row for row in mythic_activations if row["isPrematureStackViolation"]
        ],
        "dangerousStackViolationCount": sum(
            row["isPrematureStackViolation"] for row in mythic_activations
        ),
        "timerExpiredStackViolations": [
            row for row in mythic_activations
            if row["isViolation"] and row["attributionStatus"] == "timer-expired"
        ],
        "directImpactStackViolations": [
            row for row in mythic_activations
            if row["isViolation"] and row["attributionStatus"] == "direct-impact"
        ],
        "unmatchedStackViolations": [
            row for row in mythic_activations
            if row["isViolation"] and row["attributionStatus"] == "box-instance-unmatched"
        ],
        "overThreeStackViolations": [row for row in mythic_activations if row["stack"] > 3],
        "overThreeStackViolationCount": sum(row["stack"] > 3 for row in mythic_activations),
        "directHitCount": sum(row["directHitCount"] for row in rounds),
        "directHitEvents": [event for row in rounds for event in row["directHitEvents"]],
        "attributionNote": (
            "史诗木刺按无用的垃圾实例的生成、Stomp 与销毁时间对齐；只统计箱龄不足 15 秒且不是投掷直接命中的全团叠层。当前 WCL 不提供这些提前消失箱子的坐标，因此不输出交互玩家归责。"
            if has_mythic_splinters else None
        ),
    }


def _annotate_splinter_contexts(fight, throw_junk, mushrooms, volley_rounds):
    """Tag overlap windows without treating timing overlap as player attribution."""
    context_counts = Counter()
    fight_start = int(fight["startTime"])
    for activation in throw_junk.get("splinterActivations") or []:
        timestamp = int(activation.get("timestamp") or 0)
        contexts = []
        for mushroom in mushrooms:
            activation_timestamp = fight_start + int(mushroom.get("timeMs") or 0)
            wave_timestamp = int(mushroom.get("waveTimestamp") or activation_timestamp)
            if activation_timestamp - 1_000 <= timestamp <= wave_timestamp + 5_000:
                contexts.append({
                    "key": "mushroom-wave",
                    "label": "蘑菇躲冲击波 / 击飞落地窗口",
                })
                break
        for volley in volley_rounds:
            start = fight_start + int(volley.get("timeMs") or 0) - 1_000
            remove_timestamps = [
                int(row["removeTimestamp"])
                for row in volley.get("assignments") or []
                if row.get("removeTimestamp") is not None
            ]
            end = max(remove_timestamps, default=start + 20_000) + 1_500
            if start <= timestamp <= end:
                contexts.append({
                    "key": "frostfire-spread",
                    "label": "霜火连射分散找圈窗口",
                })
                break
        activation["mechanicContexts"] = contexts
        if activation.get("isPrematureStackViolation"):
            for context in contexts:
                context_counts[context["key"]] += 1
    throw_junk["dangerousStackContextSummary"] = [
        {
            "key": key,
            "label": {
                "mushroom-wave": "蘑菇躲冲击波 / 击飞落地窗口",
                "frostfire-spread": "霜火连射分散找圈窗口",
            }[key],
            "count": count,
        }
        for key, count in context_counts.most_common()
    ]

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
        warning_start = max(
            (
                int(event.get("timestamp") or 0) for event in casts
                if int(ability_id(event) or 0) == 1295891
                and event_type(event) == "begincast"
                and start - 8_000 <= int(event.get("timestamp") or 0) <= start
            ),
            default=start - 6_000,
        )
        assignments = [event for event in _events_between(debuffs, start - 1000, start + 6000, {1295928, 1295954}) if event_type(event) == "applydebuff"]
        assignment_rows = []
        for assignment in assignments:
            player_id = assignment.get("targetID")
            color = "fire" if int(ability_id(assignment) or 0) == 1295928 else "frost"
            debuff_id = int(ability_id(assignment))
            apply_ts = int(assignment["timestamp"])
            removed = _frostfire_remove(debuffs, player_id, debuff_id, apply_ts, int(fight["endTime"]))
            remove_ts = int(removed["timestamp"]) if removed else None
            # The aura can survive into the next volley.  Search until the fight
            # ends so a later death-removal is not mistaken for a normal clear.
            death = _first_player_death(raw["deaths"], player_id, apply_ts, int(fight["endTime"]))
            death_ts = int(death.get("timestamp") or 0) if death else None
            early_death = bool(
                death_ts is not None
                and death_ts - apply_ts <= FROSTFIRE_EARLY_DEATH_GRACE_MS
            )
            death_removed = bool(
                death_ts is not None
                and (
                    remove_ts is None
                    or abs(remove_ts - death_ts) <= FROSTFIRE_DEATH_REMOVE_WINDOW_MS
                )
            )
            assignment_rows.append({
                **player_ref(players, actor_map, player_id),
                "color": color,
                "debuffID": debuff_id,
                "applyTimestamp": apply_ts,
                "applyTimeMs": apply_ts - fight["startTime"],
                "applyTime": fmt_ms(apply_ts - fight["startTime"]),
                "removeTimestamp": remove_ts,
                "removeTime": fmt_ms(remove_ts - fight["startTime"]) if remove_ts else None,
                "durationMs": remove_ts - apply_ts if remove_ts else None,
                "deathTimestamp": death_ts,
                "deathTime": fmt_ms(death_ts - fight["startTime"]) if death_ts else None,
                "deathWithinGrace": early_death,
                "deathRemovedDebuff": death_removed,
                "resolution": "unresolved",
                "resolutionReason": "debuff-not-removed",
                "leftPatchRisk": True,
                "collisionPartner": None,
                "strandedExempt": False,
            })
        for row in assignment_rows:
            remove_ts = row["removeTimestamp"]
            if row["deathWithinGrace"]:
                row["resolution"] = "early-death-exempt"
                row["resolutionReason"] = "death-within-two-second-grace"
                row["leftPatchRisk"] = False
            elif row["deathRemovedDebuff"]:
                row["resolution"] = "death"
                row["resolutionReason"] = "carried-debuff-until-death"
            elif remove_ts is not None:
                # WCL can omit the private collision/patch aura.  A live player
                # receiving a normal removedebuff is sufficient completion
                # evidence, regardless of collision, cloak, or another immunity.
                row["resolution"] = "correct"
                row["resolutionReason"] = "debuff-removed-while-alive"
                row["leftPatchRisk"] = False

        first_apply_timestamp = min(
            (row["applyTimestamp"] for row in assignment_rows),
            default=start + 6_000,
        )
        assigned_player_ids = {row["playerID"] for row in assignment_rows}
        pre_apply_deaths = []
        for death in sorted(raw["deaths"], key=lambda event: int(event.get("timestamp") or 0)):
            death_ts = int(death.get("timestamp") or 0)
            player_id = death.get("targetID")
            if player_id not in players or player_id in assigned_player_ids:
                continue
            if not warning_start <= death_ts <= first_apply_timestamp:
                continue
            pre_apply_deaths.append({
                **player_ref(players, actor_map, player_id),
                "timestamp": death_ts,
                "timeMs": death_ts - fight["startTime"],
                "time": fmt_ms(death_ts - fight["startTime"]),
                "killingSpellID": int(death.get("killingAbilityGameID") or ability_id(death) or 0) or None,
            })

        color_counts = Counter(row["color"] for row in assignment_rows)
        pre_apply_slots = len(pre_apply_deaths)
        missing_fire = min(
            max(0, FROSTFIRE_EXPECTED_PER_COLOR - color_counts["fire"]),
            pre_apply_slots,
        )
        pre_apply_slots -= missing_fire
        missing_frost = min(
            max(0, FROSTFIRE_EXPECTED_PER_COLOR - color_counts["frost"]),
            pre_apply_slots,
        )
        missing_fire += sum(
            row["color"] == "fire" and row["deathWithinGrace"]
            for row in assignment_rows
        )
        missing_frost += sum(
            row["color"] == "frost" and row["deathWithinGrace"]
            for row in assignment_rows
        )
        early_deaths = [
            {
                **player_ref(players, actor_map, row["playerID"]),
                "color": row["color"],
                "timestamp": row["deathTimestamp"],
                "timeMs": row["deathTimestamp"] - fight["startTime"],
                "time": row["deathTime"],
            }
            for row in assignment_rows
            if row["deathWithinGrace"]
        ]
        linked_deaths = pre_apply_deaths + early_deaths

        for row in assignment_rows:
            review_window_ms = int(fight["endTime"]) - row["applyTimestamp"]
            row["reviewWindowMs"] = review_window_ms
            row["failureCounted"] = row["resolution"] == "death" or (
                row["resolution"] == "unresolved" and review_window_ms > 5_000
            )
            row["failureGraceMs"] = 5_000

        exemptions = []
        for stranded_color, capacity, missing_color in (
            ("frost", missing_fire, "fire"),
            ("fire", missing_frost, "frost"),
        ):
            candidates = sorted(
                (
                    row for row in assignment_rows
                    if row["color"] == stranded_color and row["failureCounted"]
                ),
                key=lambda row: (
                    row["resolution"] != "unresolved",
                    -(row["durationMs"] or row["reviewWindowMs"]),
                    actor_name(actor_map, row["playerID"]),
                ),
            )
            for row in candidates[:capacity]:
                row["strandedExempt"] = True
                row["failureCounted"] = False
                row["resolution"] = "stranded-exempt"
                row["resolutionReason"] = f"missing-{missing_color}-counterpart"
                row["linkedDeaths"] = linked_deaths
                row["leftPatchRisk"] = False
                exemptions.append({
                    **player_ref(players, actor_map, row["playerID"]),
                    "color": row["color"],
                    "missingCounterpartColor": missing_color,
                    "reason": row["resolutionReason"],
                })
        volley_target = cast.get("targetID") if cast.get("targetID") in players else None
        volley_rounds.append({
            "index": index,
            "timeMs": start - fight["startTime"],
            "time": fmt_ms(start - fight["startTime"]),
            "warningTimeMs": warning_start - fight["startTime"],
            "warningTime": fmt_ms(warning_start - fight["startTime"]),
            "targetID": volley_target,
            "target": actor_name(actor_map, volley_target) if volley_target else "全团冰火分配",
            "expectedPerColor": FROSTFIRE_EXPECTED_PER_COLOR,
            "fireCount": color_counts["fire"],
            "frostCount": color_counts["frost"],
            "missingFireSlots": missing_fire,
            "missingFrostSlots": missing_frost,
            "preApplyDeaths": pre_apply_deaths,
            "earlyDeaths": early_deaths,
            "exemptions": exemptions,
            "assignments": assignment_rows,
        })

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
        fight,
        actor_map,
        players,
        casts,
        damage,
        debuffs,
        friendly_buffs,
        raw["deaths"],
        raw.get("friendlyCasts"),
        raw.get("resources"),
        raw.get("trackedActorEvents"),
    )
    blast_wave = _blast_wave_summary(fight, actor_map, players, damage)
    mushrooms = _mushroom_activations(
        fight,
        actor_map,
        players,
        casts,
        debuffs,
        damage=damage,
        deaths=raw["deaths"],
        friendly_casts=raw.get("friendlyCasts"),
        resources=raw.get("resources"),
    )
    _annotate_splinter_contexts(fight, throw_junk, mushrooms, volley_rounds)
    elemental_explosions = _elemental_explosions(fight, actor_map, players, damage, volley_rounds)
    shell_spins = _shell_spin_rounds(
        fight, actor_map, players, casts, debuffs,
        resources=raw.get("resources"), damage=damage,
    )
    return {"unitedDefense": defense_rows, "unitedDefenseTotalSec": total_defense_duration_sec,
            "throwJunk": throw_junk,
            "avoidable": {"players": avoidable, "missedIceboundFlames": len(missed),
            "missedIceboundEvents": [{"time": fmt_ms(event["timestamp"] - fight["startTime"])} for event in missed]},
            "blastWave": blast_wave,
            "mushroomActivations": mushrooms,
            "elementalExplosions": elemental_explosions,
            "shellSpins": shell_spins,
            "frostfireVolley": volley_rounds, "mightyThud": thud_rounds}

analyze_mechanics = analyze_lost


def _mechanic_overview(rendered):
    """Build Boss-owned nightly metrics for the generic overview renderer."""
    direct_hits = []
    premature_wipes = []
    individual_wave_deaths = []
    frostfire_failures = []
    over_three_stacks = []
    excluded_direct_impact_stacks = 0
    excluded_timer_expired_stacks = 0
    unmatched_threshold_stacks = 0

    def detail(pull, time_value, text, **extra):
        return {
            "reportID": pull.get("reportID"),
            "fightID": pull.get("fightID"),
            "date": pull.get("date"),
            "startClock": pull.get("startClock"),
            "time": time_value,
            "text": text,
            **extra,
        }

    def player_totals(events):
        totals = {}
        for event in events:
            player_name = event.get("player")
            if not player_name:
                continue
            row = totals.setdefault(player_name, {
                "player": player_name,
                "count": 0,
                "classColor": event.get("classColor") or "#e5e7eb",
            })
            row["count"] += 1
        return sorted(totals.values(), key=lambda row: (-row["count"], row["player"]))

    for pull in sorted(rendered, key=lambda row: row.get("startTimeIso") or ""):
        mechanics = pull.get(BOSS_CONFIG["key"]) or {}
        throw_junk = mechanics.get("throwJunk") or {}
        excluded_direct_impact_stacks += len(
            throw_junk.get("directImpactStackViolations") or []
        )
        excluded_timer_expired_stacks += len(
            throw_junk.get("timerExpiredStackViolations") or []
        )
        unmatched_threshold_stacks += len(
            throw_junk.get("unmatchedStackViolations") or []
        )
        for event in throw_junk.get("directHitEvents") or []:
            direct_hits.append(detail(
                pull,
                event.get("time"),
                f"{event.get('player') or '未知玩家'} 被垃圾箱直接命中",
                player=event.get("player"),
                classColor=event.get("classColor"),
            ))
        for mushroom in mechanics.get("mushroomActivations") or []:
            trigger = next(iter(mushroom.get("triggerPlayers") or []), {})
            trigger_name = trigger.get("player") or "触发者未知"
            death_names = "、".join(
                row.get("player") or "未知玩家" for row in mushroom.get("waveDeaths") or []
            ) or "未记录到可归因死亡"
            if mushroom.get("prematureCausedWipe"):
                offset_ms = mushroom.get("triggerOffsetFromSurpriseRemoveMs")
                if offset_ms is None:
                    timing_text = "在安全窗口前提前触发"
                elif offset_ms < 0:
                    timing_text = f"在爆炸惊喜结束前 {abs(offset_ms) / 1000:.1f} 秒提前触发"
                else:
                    timing_text = f"在爆炸惊喜结束后 {offset_ms / 1000:.1f} 秒过早触发"
                wipe_basis = []
                if mushroom.get("massWaveDeaths"):
                    wipe_basis.append("冲击波/坠落死亡至少 5 人")
                if mushroom.get("fightEndsNearWave"):
                    end_delta_ms = mushroom.get("fightEndDeltaMs")
                    wipe_basis.append(
                        f"战斗在冲击波后 {max(0, int(end_delta_ms or 0)) / 1000:.1f} 秒结束"
                    )
                premature_wipes.append(detail(
                    pull,
                    mushroom.get("time"),
                    f"{trigger_name} {timing_text}；冲击波/坠落死亡 {len(mushroom.get('waveDeaths') or [])} 人；判定依据：{'、'.join(wipe_basis)}；死亡：{death_names}",
                    player=trigger.get("player"),
                    classColor=trigger.get("classColor"),
                    positionConfirmed=bool(mushroom.get("positionConfirmed")),
                ))
            for death in mushroom.get("individualWaveFailures") or []:
                individual_wave_deaths.append(detail(
                    pull,
                    death.get("time") or mushroom.get("waveTime"),
                    f"{death.get('player') or '未知玩家'} 未躲过冲击波",
                    player=death.get("player"),
                    classColor=death.get("classColor"),
                    cause=death.get("cause"),
                ))
        for volley in mechanics.get("frostfireVolley") or []:
            for assignment in volley.get("assignments") or []:
                if not assignment.get("failureCounted"):
                    continue
                color = "火" if assignment.get("color") == "fire" else "冰"
                reason = {
                    "death": "一直携带至死亡",
                    "unresolved": "战斗结束前仍未移除",
                }.get(assignment.get("resolution"), "未正常移除")
                frostfire_failures.append(detail(
                    pull,
                    assignment.get("applyTime") or volley.get("time"),
                    f"{assignment.get('player') or '未知玩家'} 的{color}圈：{reason}",
                    player=assignment.get("player"),
                    classColor=assignment.get("classColor"),
                    color=assignment.get("color"),
                ))
        dangerous_stack_violations = throw_junk.get("dangerousStackViolations")
        if dangerous_stack_violations is None:
            dangerous_stack_violations = throw_junk.get("stackViolations") or []
        for activation in dangerous_stack_violations:
            crate = activation.get("boxEntity") or {}
            age_text = (
                f"箱龄 {crate.get('ageSec'):.1f} 秒，{crate.get('lifecyclePhase')}"
                if crate.get("ageSec") is not None
                else "箱龄未知"
            )
            context_text = "、".join(
                row.get("label") or "" for row in activation.get("mechanicContexts") or []
            ) or "未落入已标记机制窗口"
            over_three_stacks.append(detail(
                pull,
                activation.get("time"),
                f"全团木刺升至 {activation.get('stack')} 层；{age_text}；场景：{context_text}；交互玩家无法从 WCL 确认",
                attributionStatus=activation.get("attributionStatus"),
                mechanicContexts=activation.get("mechanicContexts") or [],
            ))

    unresolved_over_three = len(over_three_stacks)
    return {
        "title": "史诗机制整夜一览",
        "subtitle": "按每次 Pull 的可验证事件汇总；点击指标可查看时间、玩家与归因依据。",
        "metrics": [
            {
                "key": "crateDirectHits",
                "label": "被箱子直接砸中",
                "value": len(direct_hits),
                "unit": "次",
                "tone": "danger",
                "description": "垃圾箱直接命中伤害事件。",
                "players": player_totals(direct_hits),
                "events": direct_hits,
            },
            {
                "key": "prematureMushroomWipes",
                "label": "误踩蘑菇导致灭团",
                "value": len(premature_wipes),
                "unit": "次",
                "tone": "danger",
                "description": f"蘑菇在爆炸惊喜结束、冲击波机制到场前已被触发；随后至少 5 人死于冲击波/坠落，或战斗在该波冲击后 10 秒内结束。触发前已有 {RAID_COLLAPSE_DEATH_THRESHOLD} 次及以上玩家死亡时，仅保留事件，不再归因为蘑菇导致灭团。",
                "players": player_totals(premature_wipes),
                "events": premature_wipes,
            },
            {
                "key": "individualBlastWaveDeaths",
                "label": "冲击波单人躲避失败",
                "value": len(individual_wave_deaths),
                "unit": "人次",
                "tone": "warning",
                "description": "排除冲击波引发灭团或至少 5 人坠落的波次后，单独死于冲击波/坠落的人次。",
                "players": player_totals(individual_wave_deaths),
                "events": individual_wave_deaths,
            },
            {
                "key": "frostfireRemovalFailures",
                "label": "冰火未正常移除",
                "value": len(frostfire_failures),
                "unit": "次",
                "tone": "warning",
                "description": "只统计一直携带冰火直到死亡，或战斗结束前仍未移除；正常移除不再猜测解除手段。点名后 2 秒内死亡，以及因此失去对侧搭档的玩家均豁免。",
                "players": player_totals(frostfire_failures),
                "events": frostfire_failures,
            },
            {
                "key": "crateStacksOverThree",
                "label": "全团木刺达到 3 层",
                "value": len(over_three_stacks),
                "unit": "次",
                "tone": "danger",
                "description": f"只统计箱龄不足 15 秒、且排除投掷垃圾直接命中后，全团木刺达到 3 层及以上的事件；{unresolved_over_three} 次均只确认箱子实例与叠层，不归责到玩家。另排除 {excluded_direct_impact_stacks} 次直接命中、{excluded_timer_expired_stacks} 次 15 秒后自然到期；{unmatched_threshold_stacks} 次未能可靠对齐箱子实例。",
                "players": player_totals(over_three_stacks),
                "events": over_three_stacks,
                "confirmedCount": 0,
                "unresolvedCount": unresolved_over_three,
                "excludedDirectImpactCount": excluded_direct_impact_stacks,
                "excludedTimerExpiredCount": excluded_timer_expired_stacks,
                "unmatchedThresholdCount": unmatched_threshold_stacks,
            },
        ],
    }


def build_aggregated_json(report_ids, options=None):
    result = _build(BOSS_CONFIG, analyze_mechanics, report_ids, options)
    rendered = result.get("data", {}).get("page1_wipeAnalysis") or []
    result["data"]["mechanicOverview"] = _mechanic_overview(rendered)
    return result


def analyze(report_ids, output_path=None, catalog_entry=None, options=None, progress_callback=None):
    result = build_aggregated_json(report_ids, options)
    return write_json_result(result, output_path, catalog_entry=catalog_entry)
