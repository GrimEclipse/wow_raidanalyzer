"""Boss-independent, lossless event snapshots for client-side exploration."""

from __future__ import annotations
from bisect import bisect_left
from collections import defaultdict


def actor_position(event, side):
    """Return coordinates only when their owning actor is known."""
    resources = event.get(side + "Resources") or {}
    if resources.get("x") is not None and resources.get("y") is not None:
        return {"x": resources["x"], "y": resources["y"], "evidence": side + "Resources"}
    owner = 1 if side == "source" else 2
    if str(event.get("resourceActor")) == str(owner) and event.get("x") is not None and event.get("y") is not None:
        return {"x": event["x"], "y": event["y"], "evidence": "resourceActor"}
    return None


def build_event_scene(fight, actor_map, players, raw, streams, *, key, arena_image, note):
    """streams maps stream names to Boss-owned ability ID -> layer labels."""
    result, seen = [], set()
    start = int(fight["startTime"])
    positions = defaultdict(list)
    for rows in raw.values():
        if not isinstance(rows, list):
            continue
        for event in rows:
            if not isinstance(event, dict):
                continue
            for side in ("source", "target"):
                point = actor_position(event, side)
                actor_id = event.get(side + "ID")
                if point and actor_id is not None:
                    actor_key = (actor_id, event.get(side + "Instance") or 0)
                    positions[actor_key].append((int(event.get("timestamp") or 0), point))
    for rows in positions.values():
        rows.sort(key=lambda row: row[0])
    position_times = {actor: [row[0] for row in rows] for actor, rows in positions.items()}
    for stream, labels in streams.items():
        for event in raw.get(stream) or []:
            ability = int(event.get("abilityGameID") or event.get("killingAbilityGameID") or 0)
            kind = str(event.get("type") or "").lower()
            if ability not in labels or kind not in {"cast", "begincast", "damage", "applydebuff", "removedebuff", "applydebuffstack", "refreshdebuff", "death", "interrupt"}:
                continue
            time = int(event.get("timestamp") or 0) - start
            if time < 0 or time > int(fight["endTime"]) - start:
                continue
            side = "target" if event.get("targetID") in players else "source"
            actor_id = event.get(side + "ID")
            actor_key = (actor_id, event.get(side + "Instance") or 0)
            actor = players.get(actor_id) or {}
            name = actor.get("name") or str(actor_map.get(actor_id) or f"单位 {actor_id}")
            signature = (time, kind, ability, event.get("sourceID"), event.get("sourceInstance"), event.get("targetID"), event.get("targetInstance"), event.get("amount"), event.get("stack"))
            if signature in seen:
                continue
            seen.add(signature)
            point = actor_position(event, side)
            position_note = point["evidence"] if point else "缺少该单位坐标"
            if not point and positions.get(actor_key):
                rows = positions[actor_key]
                timestamp = int(event.get("timestamp") or 0)
                index = bisect_left(position_times[actor_key], timestamp)
                candidate = min(rows[max(0, index - 1):index + 1], key=lambda row: abs(row[0] - timestamp))
                if abs(candidate[0] - timestamp) <= 750:
                    point = {**candidate[1], "sampleOffsetMs": candidate[0] - timestamp}
                    position_note = f"同单位相邻坐标快照，偏移 {candidate[0] - timestamp}ms；仅供显示"
            result.append({
                "id": str(len(result)), "timeMs": time, "layer": labels[ability],
                "label": labels[ability], "actor": name, "actorID": actor_id,
                "role": actor.get("role") or "unknown",
                "kind": kind, "group": labels[ability], "spellID": ability,
                "amount": int(event.get("amount") or 0), "stack": event.get("stack") or event.get("stacks"),
                "sourceID": event.get("sourceID"), "targetID": event.get("targetID"),
                "outcome": "已记录", "problem": False,
                "points": [{"position": point, "label": name, "color": actor.get("classColor") or "#7dd3fc"}] if point else [],
                "evidence": f"WCL {kind}；" + position_note,
            })
    result.sort(key=lambda row: row["timeMs"])
    deaths = [{"timeMs": int(event.get("timestamp") or 0) - start, "kind": "death", "actorID": event.get("targetID")}
              for event in raw.get("deaths") or [] if event.get("targetID") in players and 0 <= int(event.get("timestamp") or 0) - start <= int(fight["endTime"]) - start]
    deaths.sort(key=lambda row: row["timeMs"])
    return {"key": key, "deaths": deaths, "durationMs": int(fight["endTime"]) - start, "arenaImage": "/" + arena_image.lstrip("/"),
            "events": result, "note": note, "projection": "uncalibrated"}
