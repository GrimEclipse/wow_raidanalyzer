import json
from collections import defaultdict
from pathlib import Path


EXCLUDED_FROM_VERDICT = {"collapsingVoidFriendlyFire", "interferenceShockInterrupts"}


def _first_deaths(audit):
    rows = {}
    for death in audit.get("deathDetails") or []:
        target_id = death.get("targetID")
        time_ms = death.get("timeMs")
        if target_id is None or time_ms is None:
            continue
        rows[target_id] = min(rows.get(target_id, time_ms), time_ms)
    return rows


def _alive(rows, time_ms, deaths):
    return [row for row in rows or [] if deaths.get(row.get("id"), float("inf")) > time_ms]


def normalize_field_audit(audit):
    deaths = _first_deaths(audit)
    instances = audit.get("phantomInstances") or []
    for instance in instances:
        instance["spawnTimeMs"] = instance.get("castTimeMs") or instance.get("firstTimeMs")

    for collection in ("bowGroups", "waterEvents", "silverArrows", "p3Events"):
        for event in audit.get(collection) or []:
            time_ms = event.get("fireTimeMs") if event.get("fireTimeMs") is not None else event.get("timeMs", 0)
            if event.get("snapshot"):
                event["snapshot"]["players"] = _alive(event["snapshot"].get("players"), time_ms, deaths)

    water_events = audit.get("waterEvents") or []
    for event in water_events:
        time_ms = event.get("timeMs", 0)
        event["drops"] = [drop for drop in event.get("drops") or [] if deaths.get(drop.get("targetID"), float("inf")) > drop.get("timeMs", time_ms)]
        event["water"] = [drop for drop in event.get("water") or [] if deaths.get(drop.get("targetID"), float("inf")) > drop.get("timeMs", time_ms)]
        check = event.get("remoteStackCheck") or {}
        dead_names = {
            death.get("player") for death in audit.get("deathDetails") or []
            if death.get("timeMs", float("inf")) <= time_ms
        }
        check["outliers"] = [row for row in check.get("outliers") or [] if row.get("player") not in dead_names]
        if check.get("eligible"):
            check["stacked"] = not check["outliers"]

    for group in audit.get("bowGroups") or []:
        if group.get("phase") != "P2":
            continue
        fire_ms = group.get("fireTimeMs", 0)
        active = [
            instance for instance in instances
            if instance.get("firstTimeMs", float("inf")) <= fire_ms <= instance.get("lastTimeMs", -1) + 2_200
        ]
        active_ids = {instance.get("sourceInstance") for instance in active}
        group["phantoms"] = [{
            "sourceID": instance.get("sourceID"),
            "sourceInstance": instance.get("sourceInstance"),
            "name": "银色幻影",
            "firstTime": instance.get("firstTime"),
            "lastTime": instance.get("lastTime"),
            "position": instance.get("position"),
        } for instance in active]
        group["activePhantomCount"] = len(active)
        group["players"] = [
            player for player in group.get("players") or []
            if deaths.get(player.get("targetID"), float("inf")) > fire_ms
        ]
        for player in group.get("players") or []:
            player["shotAttribution"] = [
                row for row in player.get("shotAttribution") or []
                if row.get("phantom") is None or row.get("phantom") in active_ids
            ]
            if not active:
                player["missedPhantom"] = False

        next_event = min(
            (event for event in water_events if event.get("timeMs", 0) > fire_ms),
            key=lambda row: row.get("timeMs", 0),
            default=None,
        )
        if not next_event or not active_ids:
            group["survivingAtNextEvent"] = [] if not active_ids else group.get("survivingAtNextEvent", [])
            group["removedByNextEvent"] = []
            continue
        next_ms = next_event.get("timeMs", 0)
        surviving = {
            instance.get("sourceInstance") for instance in instances
            if instance.get("sourceInstance") in active_ids
            and instance.get("firstTimeMs", float("inf")) <= next_ms <= instance.get("lastTimeMs", -1) + 2_200
        }
        removed = active_ids - surviving
        group["nextEvidenceTimeMs"] = next_ms
        group["nextEvidenceTime"] = next_event.get("time")
        group["survivingAtNextEvent"] = sorted(surviving)
        group["removedByNextEvent"] = sorted(removed)
        if not removed and surviving == active_ids:
            for player in group.get("players") or []:
                player["shotAttribution"] = [{
                    "phantom": None,
                    "verdict": "未命中",
                    "confidence": "high",
                    "basis": "下个技能节点没有任何银色幻影实例消失",
                }]
                player["missedPhantom"] = True
                player["actualPhantomHitCount"] = 0
            group["shotOutcome"] = "本轮没有任何银色幻影消失，两名点名玩家均确认未命中"

    audit["waterDrops"] = [
        drop for drop in audit.get("waterDrops") or []
        if deaths.get(drop.get("targetID"), float("inf")) > drop.get("timeMs", 0)
    ]
    missed = defaultdict(int)
    for group in audit.get("bowGroups") or []:
        if group.get("phase") != "P2":
            continue
        for player in group.get("players") or []:
            if player.get("missedPhantom"):
                missed[player.get("player")] += 1
    audit.setdefault("summary", {})["p2MissedPhantomByPlayer"] = [
        {"player": player, "count": count}
        for player, count in sorted(missed.items(), key=lambda item: item[1], reverse=True)
    ]
    return audit


def _role_map(board, verdict):
    roles = {}
    for rows in board.values():
        for row in rows:
            roles.setdefault(row.get("name"), row.get("role") or ((row.get("roles") or ["unknown"])[0]))
    for row in verdict:
        roles.setdefault(row.get("name"), ((row.get("roles") or ["unknown"])[0]))
    return roles


def _base_row(name, key, label, role):
    return {"name": name, "spellKey": key, "spellName": label, "role": role, "roles": [role], "hitCount": 0, "deathCount": 0, "totalDamage": 0, "damageText": None, "events": []}


def rebuild_boards(data, meta):
    board = data["page3_courtBoard"]
    roles = _role_map(board, data.get("page4_finalVerdict") or [])
    labels = meta.get("avoidableSpells") or {}

    shadows = {}
    energy = {}
    for fight in data.get("page1_wipeAnalysis") or []:
        crown = fight.get("crownOfTheCosmos") or {}
        audit = crown.get("fieldAudit") or {}
        for bow in audit.get("bowGroups") or []:
            if bow.get("phase") != "P2":
                continue
            marked_names = [player.get("player") for player in bow.get("players") or []]
            for player in bow.get("players") or []:
                confirmed = [
                    row for row in player.get("shotAttribution") or []
                    if row.get("confidence") in {"high", "medium"} and "未命中" in str(row.get("verdict", ""))
                ]
                if not confirmed or not player.get("missedPhantom"):
                    continue
                name = player.get("player")
                item = shadows.setdefault(name, _base_row(name, "missedShadows", labels.get("missedShadows", "P2 拉弓未命中幻影"), roles.get(name, "unknown")))
                item["hitCount"] += 1
                item["events"].append({
                    "fightID": fight.get("fightID"), "phase": "P2", "group": bow.get("index"),
                    "time": bow.get("fireTime"), "positionMs": bow.get("fireTimeMs"),
                    "players": marked_names, "tag": f"bow:{bow.get('id')}",
                    "attribution": confirmed, "counted": True,
                    "countReason": "下个技能节点没有任何银色幻影消失，确认两名点名均未命中" if not bow.get("removedByNextEvent") else "射线与实例存亡已确认未命中",
                })

        for event in crown.get("missedEnergy") or []:
            if len(event.get("players") or []) == 2 and "1259998" in str(event.get("text", "")):
                event["counted"] = True
                event["countReason"] = "两名点名均已确认，但本轮未产生奥蕾莉亚能量 -5；两人共同计入并保留申诉入口"
            if not event.get("counted"):
                continue
            for name in event.get("players") or []:
                item = energy.setdefault(name, _base_row(name, "missedEnergy", labels.get("missedEnergy", "P2消Boss能量失误"), roles.get(name, "unknown")))
                item["hitCount"] += 1
                item["events"].append({**event, "fightID": fight.get("fightID"), "counted": True})

    board["missedShadows"] = sorted(shadows.values(), key=lambda row: row["hitCount"], reverse=True)
    board["missedEnergy"] = sorted(energy.values(), key=lambda row: row["hitCount"], reverse=True)
    data["page2_avoidableBoard"] = board


def rebuild_verdict(data, meta):
    old = {row.get("name"): row for row in data.get("page4_finalVerdict") or []}
    players = {}
    tank_multiplier = float((meta.get("courtConfig") or {}).get("verdictTankMultiplier", 0.5))
    points = float((meta.get("courtConfig") or {}).get("verdictPointsPerCount", 10))
    for skill_key, rows in data.get("page3_courtBoard", {}).items():
        if skill_key in EXCLUDED_FROM_VERDICT:
            continue
        for row in rows:
            name = row.get("name")
            if not name:
                continue
            item = players.setdefault(name, {"name": name, "roles": [], "recognitionCount": 0, "appealAcquittalCount": (old.get(name) or {}).get("appealAcquittalCount", 0), "breakdown": {}, "penaltyUnits": 0.0})
            for role in row.get("roles") or [row.get("role", "unknown")]:
                if role and role not in item["roles"]:
                    item["roles"].append(role)
            count = int(row.get("hitCount") or row.get("deathCount") or 0)
            item["recognitionCount"] += count
            item["breakdown"][skill_key] = item["breakdown"].get(skill_key, 0) + count
            base = tank_multiplier if "tank" in (row.get("roles") or [row.get("role")]) else 1.0
            units = count * base
            for event in row.get("events") or []:
                if event.get("counted") is False or event.get("scoreMultiplier") is None:
                    continue
                units += float(event["scoreMultiplier"]) - base
            item["penaltyUnits"] += units
    for item in players.values():
        multiplier = tank_multiplier if "tank" in item["roles"] else 1.0
        item["scoreMultiplier"] = multiplier
        item["appealUnitMultiplier"] = multiplier
        item["penaltyUnits"] = round(item["penaltyUnits"], 3)
        item["iqLoss"] = round(max(0, item["penaltyUnits"] - item["appealAcquittalCount"] * multiplier) * points)
    data["page4_finalVerdict"] = sorted(players.values(), key=lambda row: (row["iqLoss"], row["recognitionCount"]), reverse=True)


def refresh(source, destination=None):
    source = Path(source)
    destination = Path(destination or source)
    payload = json.loads(source.read_text(encoding="utf-8"))
    for fight in payload.get("data", {}).get("page1_wipeAnalysis") or []:
        audit = (fight.get("crownOfTheCosmos") or {}).get("fieldAudit")
        if audit:
            normalize_field_audit(audit)
    rebuild_boards(payload["data"], payload.get("meta") or {})
    rebuild_verdict(payload["data"], payload.get("meta") or {})
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return destination


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("destination", nargs="?")
    args = parser.parse_args()
    print(refresh(args.source, args.destination))
