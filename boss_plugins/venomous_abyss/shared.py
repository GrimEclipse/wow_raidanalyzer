"""Shared evidence helpers for Venomous Abyss boss analyzers."""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

from boss_plugins.common import (
    COMBAT_RES_SPELLS,
    PERSONAL_DEFENSIVES,
    build_player_mechanic_roles,
    combatant_spec_id,
    spec_class_color,
    spec_icon_slug,
    spec_localization,
)


DIFFICULTIES = {
    1: ("lfr", "随机团队"),
    2: ("flex", "弹性"),
    3: ("normal", "普通"),
    4: ("heroic", "英雄"),
    5: ("mythic", "史诗"),
}

TAUNT_SPELLS = {
    355: "嘲讽", 6795: "低吼", 56222: "黑暗命令", 62124: "清算之手",
    116189: "挑衅", 185245: "折磨", 51399: "黑暗命令",
}
HOLLOWING_STACK_IDS = {1284109, 1284110}
FALL_DEATH_LABEL = "跌落"
ENVIRONMENTAL_DAMAGE_NAMES = {
    1: "近战攻击",
    3: "跌落",
    4: "溺水",
    5: "疲劳",
    6: "环境火焰",
    7: "熔岩",
    8: "淤泥",
}
GUIDE_SOURCE = Path(__file__).resolve().parents[2] / "skills/venomous-abyss-raid-development/references/source-data/raid-guide-source.json"
EXTRA_SPELL_NAMES = {
    1: "近战攻击",
    1288554: "潜藏的教徒",
    1294605: "邪恶洪流",
    1295085: "灵魂转移",
    1305844: "爆炸惊喜冲击波",
    1307939: "残骸凋零",
    1291918: "旋壳",
    1305963: "腐蚀囊肿",
    1308853: "木刺爆裂",
    1310027: "遗物爆裂",
    1310028: "遗物爆裂",
    1311587: "遗物爆裂",
}
IMMUNITY_SPELLS = {
    int(spell_id): details.get("name", str(spell_id))
    for spell_id, details in PERSONAL_DEFENSIVES.items()
    if details.get("effectKind") in {"immunity", "magic_immunity"}
}


@lru_cache(maxsize=1)
def load_confirmed_spell_names():
    names = {int(key): value for key, value in EXTRA_SPELL_NAMES.items()}
    if not GUIDE_SOURCE.exists():
        return names
    payload = json.loads(GUIDE_SOURCE.read_text(encoding="utf-8"))
    for key, value in (payload.get("confirmedSpellNames") or {}).items():
        try:
            names[int(key)] = value
        except (TypeError, ValueError):
            continue
    return names


def spell_name(spell_id, local_names=None):
    if not spell_id:
        return FALL_DEATH_LABEL
    spell_id = int(spell_id)
    if spell_id in ENVIRONMENTAL_DAMAGE_NAMES:
        return ENVIRONMENTAL_DAMAGE_NAMES[spell_id]
    if local_names and local_names.get(spell_id):
        return local_names[spell_id]
    return load_confirmed_spell_names().get(spell_id, f"法术 {spell_id}")


def death_cause(spell_id):
    """Normalize WCL's pseudo ability IDs used by environmental deaths."""
    spell_id = int(spell_id or 0)
    if spell_id in {0, 3}:
        return "fall"
    if spell_id == 1:
        return "melee"
    if spell_id == 4:
        return "drowning"
    if spell_id == 5:
        return "fatigue"
    if spell_id in {6, 7, 8}:
        return "environment"
    return "ability"


def local_spell_tooltip(spell_id):
    """Return a small Wowhead-compatible payload when PTR tooltip data is absent.

    The live tooltip service often has no page for newly datamined raid spells.
    Keeping the response shape compatible avoids noisy local 404s while the
    visible name remains sourced from the checked-in Chinese raid guide.
    """
    spell_id = int(spell_id)
    name = spell_name(spell_id)
    return {
        "name": name,
        "icon": "inv_misc_questionmark",
        "tooltip": (
            '<table><tr><td><b class="q">'
            + name
            + '</b><br><span class="q0">团长手册本地法术存根</span>'
            + f'<br><span class="q0">法术 ID：{spell_id}</span></td></tr></table>'
        ),
    }


def load_confirmed_source_names():
    if not GUIDE_SOURCE.exists():
        return {}
    payload = json.loads(GUIDE_SOURCE.read_text(encoding="utf-8"))
    return payload.get("confirmedSourceNames") or {}


def source_name(actor_map, actor_id, local_names=None):
    raw = actor_name(actor_map, actor_id)
    short = raw.split("-", 1)[0]
    catalog = local_names or load_confirmed_source_names()
    return catalog.get(raw, catalog.get(short, short))


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


def difficulty_fields(fight):
    value = int(fight.get("difficulty") or 0)
    key, name = DIFFICULTIES.get(value, ("unknown", f"未知难度 {value}"))
    return {"difficulty": value, "difficultyKey": key, "difficultyName": name}


def build_player_catalog(actor_map, actor_type, combatants):
    info = {event.get("sourceID") or event.get("targetID"): event for event in combatants}
    roles = build_player_mechanic_roles(combatants)
    players = {}
    for actor_id, event in info.items():
        if actor_type.get(actor_id) != "Player":
            continue
        spec_id = combatant_spec_id(event)
        players[actor_id] = {
            "id": actor_id,
            "name": actor_name(actor_map, actor_id),
            "specID": spec_id,
            "role": roles.get(actor_id, "unknown"),
            "icon": spec_icon_slug(spec_id),
            "classColor": spec_class_color(spec_id),
            "localization": spec_localization(spec_id),
        }
    return players


def player_ref(players, actor_map, actor_id):
    player = players.get(actor_id) or {}
    return {
        "playerID": actor_id,
        "player": player.get("name") or actor_name(actor_map, actor_id),
        "classColor": player.get("classColor") or "#e5e7eb",
        "icon": player.get("icon"),
        "role": player.get("role", "unknown"),
    }


def build_survival_timeline(fight, actor_map, players, deaths, friendly_casts, spell_names=None):
    spell_names = spell_names or {}
    rows = []
    death_ids = set()
    for event in sorted(deaths, key=lambda item: int(item.get("timestamp") or 0)):
        target_id = event.get("targetID")
        if target_id not in players:
            continue
        death_ids.add(target_id)
        spell_id = int(event.get("killingAbilityGameID") or ability_id(event) or 0)
        ref = player_ref(players, actor_map, target_id)
        rows.append({
            **ref,
            "kind": "death",
            "timeMs": int(event.get("timestamp") or 0) - int(fight["startTime"]),
            "time": fmt_ms(int(event.get("timestamp") or 0) - int(fight["startTime"])),
            "absoluteTime": int(event.get("timestamp") or 0),
            "abilityID": spell_id,
            "ability": spell_name(spell_id, spell_names),
            "abilityLabel": spell_name(spell_id, spell_names),
            "deathCause": death_cause(spell_id),
        })
    seen = set()
    for event in sorted(friendly_casts, key=lambda item: int(item.get("timestamp") or 0)):
        spell_id = int(ability_id(event) or 0)
        if spell_id not in COMBAT_RES_SPELLS or event_type(event) not in {"cast", "applybuff"}:
            continue
        target_id = event.get("targetID")
        if target_id not in players:
            continue
        key = (int(event.get("timestamp") or 0) // 1500, event.get("sourceID"), target_id, spell_id)
        if key in seen:
            continue
        seen.add(key)
        target = player_ref(players, actor_map, target_id)
        rows.append({
            **target,
            "kind": "combat_res",
            "timeMs": int(event.get("timestamp") or 0) - int(fight["startTime"]),
            "time": fmt_ms(int(event.get("timestamp") or 0) - int(fight["startTime"])),
            "absoluteTime": int(event.get("timestamp") or 0),
            "sourceID": event.get("sourceID"),
            "source": actor_name(actor_map, event.get("sourceID")),
            "abilityID": spell_id,
            "ability": COMBAT_RES_SPELLS[spell_id],
        })
    rows.sort(key=lambda row: (row["absoluteTime"], 0 if row["kind"] == "death" else 1))
    alive_ids = set(players)
    for row in rows:
        if row["kind"] == "death":
            alive_ids.discard(row.get("playerID"))
        elif row["kind"] == "combat_res":
            alive_ids.add(row.get("playerID"))
    alive = [player for actor_id, player in players.items() if actor_id in alive_ids]
    return {
        "rosterCount": len(players),
        "survivorCount": len(alive),
        "deathCount": sum(row["kind"] == "death" for row in rows),
        "combatResCount": sum(row["kind"] == "combat_res" for row in rows),
        "survivors": alive,
        "timeline": rows,
    }


def group_nearby(events, window_ms=1000):
    groups = []
    for event in sorted(events, key=lambda row: int(row.get("timestamp") or 0)):
        timestamp = int(event.get("timestamp") or 0)
        if not groups or timestamp - int(groups[-1][-1].get("timestamp") or 0) > window_ms:
            groups.append([])
        groups[-1].append(event)
    return groups


def events_between(events, start, end, spell_ids=None, types=None):
    """Return events in one half-open mechanic window."""
    spell_ids = set(spell_ids or [])
    types = set(types or [])
    return [
        event for event in events
        if start <= int(event.get("timestamp") or 0) < end
        and (not spell_ids or int(ability_id(event) or 0) in spell_ids)
        and (not types or event_type(event) in types)
    ]


def completed_casts(casts, spell_id):
    """Return completed enemy casts for a single spell."""
    return [
        event for event in casts
        if int(ability_id(event) or 0) == spell_id and event_type(event) == "cast"
    ]


def avoidable_board(fight, actor_map, players, damage, deaths, labels):
    """Build the common per-player avoidable-damage board shape."""
    deaths_by = {
        (event.get("targetID"), int(event.get("killingAbilityGameID") or 0))
        for event in deaths
    }
    board = []
    for spell_id, spell_label in labels.items():
        grouped = defaultdict(list)
        for event in damage:
            if int(ability_id(event) or 0) == spell_id and event.get("targetID") in players:
                grouped[event.get("targetID")].append(event)
        for player_id, player_events in grouped.items():
            board.append({
                **player_ref(players, actor_map, player_id),
                "spellID": spell_id,
                "spellName": spell_label,
                "hitCount": len(player_events),
                "totalDamage": sum(event_amount(event) for event in player_events),
                "maxHit": max((event_amount(event) for event in player_events), default=0),
                "deathCount": int((player_id, spell_id) in deaths_by),
                "events": [
                    {
                        "timeMs": int(event["timestamp"] - fight["startTime"]),
                        "time": fmt_ms(event["timestamp"] - fight["startTime"]),
                        "amount": event_amount(event),
                    }
                    for event in player_events
                ],
            })
    return sorted(
        board,
        key=lambda row: (row["deathCount"], row["totalDamage"], row["hitCount"]),
        reverse=True,
    )


def nightly_detail(pull, time_value, text, **extra):
    """Create one generic clickable nightly-overview record."""
    return {
        "reportID": pull.get("reportID"),
        "fightID": pull.get("fightID"),
        "date": pull.get("date"),
        "startClock": pull.get("startClock"),
        "time": time_value,
        "text": text,
        **extra,
    }


def nightly_player_totals(events):
    """Aggregate mechanic event attribution without owning Boss rules."""
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
        row["count"] += int(event.get("count") or 1)
    return sorted(totals.values(), key=lambda row: (-row["count"], row["player"]))


def death_near(deaths, player_id, timestamp, window_ms=500):
    """Return a player's nearest death event around a mechanic timestamp."""
    candidates = [
        event for event in deaths
        if event.get("targetID") == player_id
        and abs(int(event.get("timestamp") or 0) - timestamp) <= window_ms
    ]
    return min(candidates, key=lambda event: abs(int(event.get("timestamp") or 0) - timestamp), default=None)


def event_point(event):
    for node in (event, event.get("resources") or {}, event.get("sourceResources") or {}):
        if not isinstance(node, dict):
            continue
        for x_key, y_key in (("x", "y"), ("positionX", "positionY"), ("X", "Y")):
            if node.get(x_key) is not None and node.get(y_key) is not None:
                try:
                    return float(node[x_key]), float(node[y_key])
                except (TypeError, ValueError):
                    pass
    return None


def position_actor_id(event):
    resource_actor = event.get("resourceActor")
    if resource_actor in {2, "2"}:
        return event.get("targetID")
    if resource_actor in {1, "1"}:
        return event.get("sourceID")
    if "buff" in event_type(event) or "debuff" in event_type(event) or event_type(event) == "death":
        return event.get("targetID")
    return event.get("sourceID") or event.get("targetID")


def build_position_index(events):
    index = defaultdict(list)
    for event in events:
        point = event_point(event)
        actor_id = position_actor_id(event)
        if actor_id is None or not point:
            continue
        index[actor_id].append({
            "timestamp": int(event.get("timestamp") or 0),
            "x": point[0], "y": point[1], "facing": event.get("facing"),
        })
    for rows in index.values():
        rows.sort(key=lambda row: row["timestamp"])
    return index


def position_at(index, actor_id, timestamp, max_offset_ms=2500):
    rows = index.get(actor_id) or []
    if not rows:
        return None
    nearest = min(rows, key=lambda row: abs(row["timestamp"] - timestamp))
    offset = nearest["timestamp"] - timestamp
    return {**nearest, "sampleOffsetMs": offset, "reliable": abs(offset) <= max_offset_ms}


def position_at_interpolated(index, actor_id, timestamp, reliable_window_ms=3_000, fallback_window_ms=30_000):
    """Linearly interpolate actor coordinates between WCL samples for smooth replay."""
    rows = index.get(actor_id) or []
    if not rows:
        return None
    before = None
    after = None
    for row in rows:
        if row["timestamp"] <= timestamp:
            before = row
        else:
            after = row
            break
    if before and after:
        before_delta = timestamp - before["timestamp"]
        after_delta = after["timestamp"] - timestamp
        if before_delta <= reliable_window_ms and after_delta <= reliable_window_ms:
            span = after["timestamp"] - before["timestamp"]
            ratio = 0 if span <= 0 else before_delta / span
            reference = before if before_delta <= after_delta else after
            reference_delta = int(reference["timestamp"] - timestamp)
            return {
                "timestamp": timestamp,
                "x": before["x"] + (after["x"] - before["x"]) * ratio,
                "y": before["y"] + (after["y"] - before["y"]) * ratio,
                "facing": reference.get("facing"),
                "sampleOffsetMs": reference_delta,
                "positionRule": "interpolated",
                "reliable": True,
            }
    nearest = min((row for row in (before, after) if row), key=lambda row: abs(row["timestamp"] - timestamp), default=None)
    if not nearest:
        return None
    delta = int(nearest["timestamp"] - timestamp)
    return {
        **nearest,
        "sampleOffsetMs": delta,
        "positionRule": "nearest" if abs(delta) <= reliable_window_ms else "nearest-reference",
        "reliable": abs(delta) <= reliable_window_ms,
        "outsideFallbackWindow": abs(delta) > fallback_window_ms,
    }


def compact_actor_position_events(events, actor_id, minimum_interval_ms=120):
    compact = []
    last_timestamp = None
    last_state = None
    for event in events:
        if position_actor_id(event) != actor_id or not event_point(event):
            continue
        timestamp = int(event.get("timestamp") or 0)
        point = event_point(event)
        state = (round(point[0], 2), round(point[1], 2), event.get("facing"))
        if last_timestamp is not None and timestamp - last_timestamp < minimum_interval_ms and state == last_state:
            continue
        compact.append(event)
        last_timestamp = timestamp
        last_state = state
    return compact


def resolve_boss_actor_id(actor_rows, game_id, name_keywords=()):
    for row in actor_rows:
        if row.get("gameID") == game_id:
            return row["id"]
    lowered = tuple(keyword.lower() for keyword in name_keywords)
    for row in actor_rows:
        name = str(row.get("name") or "").lower()
        if any(keyword in name for keyword in lowered):
            return row["id"]
    return None


def arena_estimate_with_boss(index, player_ids, boss_id=None):
    center_x = center_y = None
    method = "player-samples-p96"
    if boss_id is not None:
        boss_rows = index.get(boss_id) or []
        if boss_rows:
            center_x = statistics.median(row["x"] for row in boss_rows)
            center_y = statistics.median(row["y"] for row in boss_rows)
            method = "boss-center-p96"
    points = [(row["x"], row["y"]) for actor_id in player_ids for row in (index.get(actor_id) or [])]
    if center_x is None or center_y is None:
        if len(points) < 8:
            return None
        center_x = statistics.median(point[0] for point in points)
        center_y = statistics.median(point[1] for point in points)
    if not points:
        return None
    distances = sorted(math.dist(point, (center_x, center_y)) for point in points)
    radius = distances[min(len(distances) - 1, int(len(distances) * .96))]
    return {
        "centerX": center_x, "centerY": center_y, "radius": radius,
        "radiusYards": round(radius / 100, 1), "method": method, "bossCenter": method == "boss-center-p96",
    }


def movement(index, actor_id, start, end):
    left = position_at(index, actor_id, start, max_offset_ms=1500)
    right = position_at(index, actor_id, end, max_offset_ms=1500)
    if not left or not right:
        return None
    dx, dy = right["x"] - left["x"], right["y"] - left["y"]
    return {
        "from": {"x": left["x"], "y": left["y"], "sampleOffsetMs": left["sampleOffsetMs"]},
        "to": {"x": right["x"], "y": right["y"], "sampleOffsetMs": right["sampleOffsetMs"]},
        "dx": dx, "dy": dy,
        "distanceYards": round(math.hypot(dx, dy) / 100, 1),
        "angleDegrees": round((math.degrees(math.atan2(-dy, dx)) + 360) % 360, 1),
        "reliable": bool(left["reliable"] and right["reliable"]),
    }


def arena_estimate(index, player_ids):
    points = [(row["x"], row["y"]) for actor_id in player_ids for row in (index.get(actor_id) or [])]
    if len(points) < 8:
        return None
    center_x = statistics.median(point[0] for point in points)
    center_y = statistics.median(point[1] for point in points)
    distances = sorted(math.dist(point, (center_x, center_y)) for point in points)
    radius = distances[min(len(distances) - 1, int(len(distances) * .96))]
    return {"centerX": center_x, "centerY": center_y, "radius": radius, "radiusYards": round(radius / 100, 1), "method": "player-samples-p96"}


def active_immunities(buff_events, player_id, timestamp, window_ms=1500):
    return [
        {"spellID": int(ability_id(event) or 0), "spellName": IMMUNITY_SPELLS.get(int(ability_id(event) or 0), str(ability_id(event)))}
        for event in buff_events
        if event.get("targetID") == player_id
        and int(ability_id(event) or 0) in IMMUNITY_SPELLS
        and abs(int(event.get("timestamp") or 0) - timestamp) <= window_ms
    ]
