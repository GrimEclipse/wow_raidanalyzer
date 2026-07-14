import argparse
import json
import math
from pathlib import Path


DESIGNATED_HEALERS = {"旖旎云逸", "暗黑膏药"}
VOID_GRASP_ID = 1260027
DIMENSIONAL_SLASH_IDS = {1260838, 1260839}
REMOVED_AVOIDABLE_DAMAGE_KEYS = {
    "dimensionalSlashSteel", "dimensionalSlashMoonRing", "orbitingMatter",
    "devouringAbyss", "voidResidue", "dailyAvoidableDamage", "avoidableDamageDeaths",
}
AVOIDABLE_DAMAGE_LABELS = {
    "corruptionEssenceDamage": "腐化精华",
}
FINAL_VERDICT_EXCLUDED = {
    "collapsingVoidFriendlyFire", "interferenceShockInterrupts", "voidGraspDeaths", "missedEnergy", "dailyAvoidableDamage",
    "p1SilverArrowMissedFights",
} | set(AVOIDABLE_DAMAGE_LABELS)
PLAYER_CAST_NAMES = {
    116: "Frostbolt",
    596: "Prayer of Healing",
    686: "Shadow Bolt",
    1064: "Chain Heal",
    2061: "Flash Heal",
    6353: "Soul Fire",
    29722: "Incinerate",
    77472: "Healing Wave",
    82326: "Holy Light",
    105174: "Hand of Gul'dan",
    116858: "Chaos Bolt",
    199786: "Glacial Spike",
    361469: "Living Flame",
    373861: "Temporal Anomaly",
}
COSMIC_BARRIER_ID = 1261289
PHANTOM_GRACE_MS = 2200
PHANTOM_HIT_RADIUS_YARDS = 20 / 4.35
ARENA_CENTER = {"x": -36385, "y": 478822}
P1_EXPECTED_ARROW_TARGETS = {
    43_466: "殆米阿尔",
    99_350: "殁里乌姆",
    125_559: "龌勒卢斯",
}
P1_ARROW_TOLERANCE_MS = 8_000


def role_for(fight, name):
    for death in fight.get("deathTimeline") or []:
        if death.get("player") == name and death.get("role"):
            return death["role"]
    for rows in (fight.get("avoidableSummary") or {}).values():
        for row in rows or []:
            if row.get("name") == name and row.get("role"):
                return row["role"]
    return "unknown"


def time_to_ms(value):
    if not value:
        return 0
    parts = str(value).split(":")
    try:
        if len(parts) == 2:
            return int(round((int(parts[0]) * 60 + float(parts[1])) * 1000))
        if len(parts) == 3:
            return int(round((int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])) * 1000))
    except (TypeError, ValueError):
        return 0
    return 0


def ms_to_time(value):
    total_ms = max(0, int(value or 0))
    minutes, remainder = divmod(total_ms, 60000)
    seconds, millis = divmod(remainder, 1000)
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


def legacy_ray_payload(ray):
    return [{
        "label": item.get("label"),
        "start": {"x": item.get("startX"), "y": item.get("startY"), "yardX": round(float(item.get("startX") or 0) / 100, 2), "yardY": round(float(item.get("startY") or 0) / 100, 2)},
        "through": {"x": item.get("obeliskX"), "y": item.get("obeliskY"), "yardX": round(float(item.get("obeliskX") or 0) / 100, 2), "yardY": round(float(item.get("obeliskY") or 0) / 100, 2)},
        "end": {"x": item.get("endX"), "y": item.get("endY"), "yardX": round(float(item.get("endX") or 0) / 100, 2), "yardY": round(float(item.get("endY") or 0) / 100, 2)},
    } for item in ray.get("rays") or []]


def restore_bow_players(fight):
    crown = fight.get("crownOfTheCosmos") or {}
    audit = crown.get("fieldAudit") or {}
    groups = audit.get("bowGroups") or []
    legacy_rays = crown.get("voidGraspRays") or []
    death_details = audit.get("deathDetails") or []
    repaired_groups = 0
    restored_players = 0
    death_trigger_groups = 0
    for group in groups:
        start_ms = int(group.get("applyStartMs") or 0)
        fire_ms = int(group.get("fireTimeMs") or 0)
        for player in group.get("players") or []:
            apply_ms = int(player.get("applyTimeMs") or start_ms)
            fade_ms = int(player.get("fadeTimeMs") or fire_ms)
            death = min(
                (
                    item for item in death_details
                    if item.get("targetID") == player.get("targetID")
                    and apply_ms <= int(item.get("timeMs") or 0) <= fade_ms + 1_000
                ),
                key=lambda item: abs(int(item.get("timeMs") or 0) - fade_ms),
                default=None,
            )
            if death:
                player["diedAtFire"] = True
                player["deathTimeMs"] = int(death.get("timeMs") or 0)
                player["deathTime"] = death.get("time")
                player["triggerTimeMs"] = int(death.get("timeMs") or 0)
                player["triggerTime"] = death.get("time")
                player["deathTriggeredRay"] = True
                player["lastSecondState"] = None
                player["lastSecondMovementYards"] = None
                player["isSnapAiming"] = False
                if not player.get("rays"):
                    legacy = min((
                        ray for ray in legacy_rays
                        if ray.get("targetID") == player.get("targetID")
                        and abs(int(ray.get("positionMs") or 0) - int(death.get("timeMs") or 0)) <= 2_000
                    ), key=lambda ray: abs(int(ray.get("positionMs") or 0) - int(death.get("timeMs") or 0)), default=None)
                    if legacy:
                        player["rays"] = legacy_ray_payload(legacy)
                        player["fadeState"] = player.get("fadeState") or legacy.get("state")
                        if not player.get("obelisks"):
                            player["obelisks"] = [
                                {"label": item.get("label"), "point": item.get("through")}
                                for item in player["rays"]
                            ]
                player["missedPhantom"] = False
                player["missedPhantomExemptReason"] = "崩裂空无结算期间死亡，暂不统计未命中幻影"
                player.setdefault("healingWindow", {})["deathLimited"] = True
        candidates = [
            ray for ray in legacy_rays
            if ray.get("phase") == group.get("phase")
            and start_ms <= int(ray.get("positionMs") or 0) <= fire_ms + 1_000
            and start_ms - 1_000 <= time_to_ms(ray.get("applyTime")) <= start_ms + 4_000
        ]
        existing_ids = {player.get("targetID") for player in group.get("players") or []}
        restored = []
        for ray in candidates:
            target_id = ray.get("targetID")
            if target_id in existing_ids:
                continue
            ray_fire_ms = int(ray.get("positionMs") or 0)
            death = min(
                (
                    item for item in death_details
                    if item.get("targetID") == target_id
                    and start_ms <= int(item.get("timeMs") or 0) <= ray_fire_ms + 1_000
                ),
                key=lambda item: abs(int(item.get("timeMs") or 0) - ray_fire_ms),
                default=None,
            )
            died = bool(death)
            nested_rays = legacy_ray_payload(ray)
            state = ray.get("state") or {}
            obelisks = [{"label": item.get("label"), "point": item.get("through")} for item in legacy_ray_payload(ray)]
            hits = list(ray.get("hits") or [])
            restored.append({
                "targetID": target_id,
                "player": ray.get("player"),
                "applyTimeMs": time_to_ms(ray.get("applyTime")),
                "applyTime": ray.get("applyTime"),
                "fadeTimeMs": ray_fire_ms,
                "fadeTime": ray.get("fireTime"),
                "applyState": state,
                "applyFacingReliable": bool(state.get("facingRadians") is not None),
                "fadeState": state,
                "lastSecondState": None,
                "lastSecondMovementYards": None,
                "isSnapAiming": False,
                "obelisks": obelisks,
                "rays": nested_rays,
                "actualHits": hits,
                "actualPhantomHitCount": int(ray.get("phantomHits") or 0),
                "resolvedPhantomInstances": [],
                "resolutionEvidence": "legacyVoidGraspRay",
                "predictedPhantomHits": [],
                "missedPhantom": False,
                "snapAimingDeaths": [],
                "healing": {"healingByHealer": [], "totalHealing": 0},
                "allHealing": {"healingByHealer": [], "totalHealing": 0},
                "healingWindow": {"startTimeMs": time_to_ms(ray.get("applyTime")), "endTimeMs": ray_fire_ms, "deathLimited": died},
                "diedAtFire": died,
                "deathTriggeredRay": died,
                "triggerTimeMs": int(death.get("timeMs") or 0) if death else ray_fire_ms,
                "triggerTime": death.get("time") if death else ray.get("fireTime"),
                "deathTimeMs": int(death.get("timeMs") or 0) if death else None,
                "deathTime": death.get("time") if death else None,
                "restoredFromVoidGraspRays": True,
            })
            existing_ids.add(target_id)
        if restored:
            group.setdefault("players", []).extend(restored)
            group["players"].sort(key=lambda player: int(player.get("applyTimeMs") or 0))
        restored_all = [player for player in group.get("players") or [] if player.get("restoredFromVoidGraspRays")]
        if restored_all:
            repaired_groups += 1
            restored_players += len(restored_all)
        any_dead = any(player.get("diedAtFire") for player in group.get("players") or [])
        any_alive = any(not player.get("diedAtFire") for player in group.get("players") or [])
        if any_dead and any_alive:
            death_trigger_groups += 1
    return repaired_groups, restored_players, death_trigger_groups


def point_segment_distance_yards(point, start, end):
    px, py = float(point.get("x") or 0), float(point.get("y") or 0)
    ax, ay = float(start.get("x") or 0), float(start.get("y") or 0)
    bx, by = float(end.get("x") or 0), float(end.get("y") or 0)
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay) / 100
    ratio = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + ratio * dx), py - (ay + ratio * dy)) / 100


def extended_ray_end(start, through, length=10_000):
    dx = float(through.get("x") or 0) - float(start.get("x") or 0)
    dy = float(through.get("y") or 0) - float(start.get("y") or 0)
    direction_length = math.hypot(dx, dy)
    if direction_length <= 0:
        return None
    return {
        "x": float(start.get("x") or 0) + dx / direction_length * length,
        "y": float(start.get("y") or 0) + dy / direction_length * length,
    }


def repair_p1_arrow_attribution(fight):
    crown = fight.get("crownOfTheCosmos") or {}
    audit = crown.get("fieldAudit") or {}
    arrows = [row for row in audit.get("silverArrows") or [] if row.get("phase") == "P1"]
    for arrow in arrows:
        bosses = (arrow.get("snapshot") or {}).get("bosses") or []
        boss_by_id = {row.get("id"): row for row in bosses}
        alleria = next((row for row in bosses if "奥蕾莉亚" in str(row.get("name") or "") and row.get("position")), None)
        start = (alleria or {}).get("position") or ARENA_CENTER
        hit_events = arrow.get("p1BossHitEvents") or []
        attribution = []
        for marked in arrow.get("markedPlayerPositions") or []:
            through = marked.get("position")
            ray_end = extended_ray_end(start, through) if through else None
            matched = []
            if ray_end:
                for hit in hit_events:
                    boss = boss_by_id.get(hit.get("targetID"))
                    if boss and boss.get("position") and point_segment_distance_yards(boss["position"], start, ray_end) <= 5:
                        matched.append(hit.get("boss") or boss.get("name"))
            attribution.append({
                "targetID": marked.get("targetID"),
                "player": marked.get("player"),
                "bosses": list(dict.fromkeys(name for name in matched if name)),
                "hitBoss": bool(matched),
            })
        arrow["p1BossAttribution"] = attribution
        arrow["p1AllMissedBoss"] = not any(row.get("hitBoss") for row in attribution)

    repaired_rows = []
    repaired_issues = []
    for issue in crown.get("p1ArrowIssues") or []:
        expected_target = issue.get("expectedTarget") or issue.get("target")
        expected_ms = next(
            (time_ms for time_ms, target in P1_EXPECTED_ARROW_TARGETS.items() if target == expected_target),
            int(issue.get("positionMs") or time_to_ms(issue.get("expectedTime") or issue.get("time"))),
        )
        arrow = min(arrows, key=lambda row: abs(int(row.get("timeMs") or 0) - expected_ms), default=None)
        confirmed = bool(
            arrow and abs(int(arrow.get("timeMs") or 0) - expected_ms) <= P1_ARROW_TOLERANCE_MS
            and any(expected_target and expected_target in str(hit.get("boss") or "") for hit in arrow.get("p1BossHitEvents") or [])
        )
        if not confirmed:
            repaired_issues.append(issue)
            continue
        repaired_rows.append({
            "time": arrow.get("time"),
            "kind": "field_audit_boss_hit",
            "target": expected_target,
            "expectedTime": ms_to_time(expected_ms),
            "markedPlayers": [
                {"id": row.get("targetID"), "name": row.get("player")}
                for row in arrow.get("markedPlayerPositions") or []
            ],
            "text": f"{expected_target} 银锋箭判定成功：场地审计确认Boss状态被移除，本轮点名为 {'、'.join(arrow.get('markedPlayers') or [])}。",
        })
    existing_rows = crown.get("p1ArrowRows") or []
    crown["p1ArrowRows"] = existing_rows + [row for row in repaired_rows if row.get("target") not in {item.get("target") for item in existing_rows}]
    for row in crown["p1ArrowRows"]:
        expected_ms = next((time_ms for time_ms, target in P1_EXPECTED_ARROW_TARGETS.items() if target == row.get("target")), None)
        if expected_ms is not None:
            row["expectedTime"] = ms_to_time(expected_ms)
    crown["p1ArrowIssues"] = repaired_issues


def normalize_p1_arrow_misses(fight):
    crown = fight.get("crownOfTheCosmos") or {}
    arrows = [row for row in ((crown.get("fieldAudit") or {}).get("silverArrows") or []) if row.get("phase") == "P1"]
    missed = {}
    used_ids = set()
    for expected_ms, expected_target in P1_EXPECTED_ARROW_TARGETS.items():
        arrow = min(
            (
                row for row in arrows
                if row.get("id") not in used_ids and abs(int(row.get("timeMs") or 0) - expected_ms) <= P1_ARROW_TOLERANCE_MS
            ),
            key=lambda row: abs(int(row.get("timeMs") or 0) - expected_ms),
            default=None,
        )
        if not arrow:
            continue
        used_ids.add(arrow.get("id"))
        for attribution in arrow.get("p1BossAttribution") or []:
            if attribution.get("hitBoss"):
                continue
            name = attribution.get("player")
            item = missed.setdefault(name, board_row(fight, name, "p1SilverArrowMissedFights", "P1 银锋箭未命中Boss场次"))
            item["markedCount"] = int(item.get("markedCount") or 0) + 1
            item.setdefault("missedRounds", []).append({
                "group": arrow.get("index"), "time": arrow.get("time"), "positionMs": arrow.get("timeMs"),
                "expectedTarget": expected_target,
            })
    rows = []
    for name, item in missed.items():
        rounds = item.pop("missedRounds", [])
        item["hitCount"] = 1
        item["events"] = [{
            "fightID": fight.get("fightID"), "phase": "P1", "group": rounds[0].get("group") if rounds else None,
            "time": rounds[0].get("time") if rounds else None, "positionMs": rounds[0].get("positionMs") if rounds else None,
            "missedRounds": rounds, "counted": True, "verdictCounted": False, "displayOnly": True,
            "countReason": "同一玩家同一场战斗无论漏射几轮，只统计1个未命中场次",
            "text": f"Fight{fight.get('fightID')} {name} 在 P1 有 {len(rounds)} 轮银锋箭未命中Boss：" + "、".join(f"#{row['group']} {row['expectedTarget']}" for row in rounds),
        }]
        rows.append(item)
    fight.setdefault("avoidableSummary", {})["p1SilverArrowMissedFights"] = rows


def platform_for_point(point):
    if not point:
        return None
    if float(point.get("y") or 0) - ARENA_CENTER["y"] >= 0:
        return "top"
    return "lowerLeft" if float(point.get("x") or 0) < ARENA_CENTER["x"] else "lowerRight"


def repair_phantom_attribution(fight):
    audit = ((fight.get("crownOfTheCosmos") or {}).get("fieldAudit") or {})
    groups = audit.get("bowGroups") or []
    instances = [row for row in audit.get("phantomInstances") or [] if row.get("sourceInstance") is not None]
    water_events = audit.get("waterEvents") or []
    repaired = 0
    for group in groups:
        if group.get("phase") != "P2":
            continue
        instance_by_id = {row.get("sourceInstance"): row for row in instances}
        shown_ids = set()
        for player in group.get("players") or []:
            fade_ms = int(player.get("fadeTimeMs") or group.get("fireTimeMs") or 0)
            active_ids = sorted({
                row.get("sourceInstance") for row in instances
                if int(row.get("firstTimeMs") or 0) <= fade_ms <= int(row.get("lastTimeMs") or 0) + PHANTOM_GRACE_MS
            })
            shown_ids.update(active_ids)
            player["activePhantomInstances"] = active_ids
            player["phantomEligible"] = bool(active_ids)
            predicted = []
            for instance_id in active_ids:
                phantom = instance_by_id.get(instance_id) or {}
                point = phantom.get("position")
                if not point:
                    continue
                for ray in player.get("rays") or []:
                    distance = point_segment_distance_yards(point, ray.get("start") or {}, ray.get("end") or {})
                    if distance <= PHANTOM_HIT_RADIUS_YARDS:
                        predicted.append({"phantom": instance_id, "ray": ray.get("label"), "distanceYards": round(distance, 1)})
            player["predictedPhantomHits"] = predicted
            player["shotAttribution"] = []
            player["missedPhantom"] = False
            player["potentialMissedPhantom"] = bool(active_ids) and not predicted and not int(player.get("actualPhantomHitCount") or 0)
            if player.get("diedAtFire"):
                player["missedPhantomExemptReason"] = "崩裂空无结算期间死亡，暂不统计未命中幻影"

        phantom_rows = []
        for instance_id in sorted(shown_ids):
            instance = instance_by_id.get(instance_id) or {}
            phantom_rows.append({
                "sourceID": instance.get("sourceID"),
                "sourceInstance": instance_id,
                "name": "银色幻影",
                "firstTime": instance.get("firstTime") or ms_to_time(instance.get("firstTimeMs")),
                "lastTime": instance.get("lastTime") or ms_to_time(instance.get("lastTimeMs")),
                "position": instance.get("position"),
            })
        group["phantoms"] = phantom_rows
        group["activePhantomCount"] = len(shown_ids)
        group["phantomEligible"] = bool(shown_ids)
        if not shown_ids:
            continue

        fire_ms = int(group.get("fireTimeMs") or 0)
        evidence_candidates = [
            int(row.get("timeMs") or row.get("applyStartMs") or 0)
            for row in [*water_events, *groups]
            if int(row.get("timeMs") or row.get("applyStartMs") or 0) > fire_ms
        ]
        evidence_ms = min(evidence_candidates, default=fire_ms + 5000)
        surviving = {
            instance_id for instance_id in shown_ids
            if int((instance_by_id.get(instance_id) or {}).get("firstTimeMs") or 0) - 5000 <= evidence_ms
            <= int((instance_by_id.get(instance_id) or {}).get("lastTimeMs") or 0) + PHANTOM_GRACE_MS
        }
        removed = sorted(shown_ids - surviving)
        group["nextEvidenceTimeMs"] = evidence_ms
        group["survivingAtNextEvent"] = sorted(surviving)
        group["removedByNextEvent"] = removed

        if not removed:
            if surviving == shown_ids:
                for player in group.get("players") or []:
                    if player.get("diedAtFire") or not player.get("activePhantomInstances"):
                        continue
                    player["shotAttribution"].append({
                        "phantom": None,
                        "verdict": "未命中",
                        "confidence": "high",
                        "basis": "下个技能节点没有任何银色幻影实例消失",
                    })
                    player["missedPhantom"] = True
            repaired += 1
            continue

        player_counts = {}
        for row in (group.get("snapshot") or {}).get("players") or []:
            platform = platform_for_point(row.get("position"))
            if platform:
                player_counts[platform] = player_counts.get(platform, 0) + 1
        for instance_id in removed:
            direct = [
                player for player in group.get("players") or []
                if not player.get("diedAtFire")
                and any(hit.get("phantom") == instance_id for hit in player.get("predictedPhantomHits") or [])
            ]
            if len(direct) == 1:
                direct[0]["shotAttribution"].append({"phantom": instance_id, "verdict": "命中", "confidence": "high", "basis": "下个技能实例消失+射线相交"})
                continue
            platform = platform_for_point((instance_by_id.get(instance_id) or {}).get("position"))
            expected = "range" if player_counts.get(platform, 0) >= 4 else "melee"
            candidates = []
            for player in group.get("players") or []:
                if player.get("diedAtFire"):
                    continue
                if instance_id not in (player.get("activePhantomInstances") or []):
                    continue
                role = player.get("mechanicRole") or role_for(fight, player.get("player"))
                role_side = "range" if str(role).startswith("range-") else ("melee" if str(role).startswith("melee-") or role == "tank" else "unknown")
                if role_side == expected:
                    candidates.append(player)
            if len(candidates) == 1:
                candidates[0]["shotAttribution"].append({"phantom": instance_id, "verdict": "大概率命中", "confidence": "medium", "basis": f"下个技能实例消失；{platform}板块职责={expected}"})
            else:
                for player in group.get("players") or []:
                    if player.get("diedAtFire"):
                        continue
                    if instance_id in (player.get("activePhantomInstances") or []):
                        player["shotAttribution"].append({"phantom": instance_id, "verdict": "无法唯一归因", "confidence": "low", "basis": "实例消失已确认，但射线/职责不能唯一归因"})

        hit_players = [
            player for player in group.get("players") or []
            if any(row.get("verdict") in {"命中", "大概率命中"} for row in player.get("shotAttribution") or [])
        ]
        unassigned_players = [
            player for player in group.get("players") or []
            if not player.get("diedAtFire")
            and player.get("activePhantomInstances")
            and player not in hit_players
        ]
        if surviving and len(unassigned_players) == 1:
            unassigned_players[0]["shotAttribution"].append({
                "phantom": sorted(surviving)[0],
                "verdict": "未命中",
                "confidence": "high",
                "basis": "另一名点名已确认命中；该玩家对应幻影在下个技能节点仍存活",
            })
        for player in group.get("players") or []:
            if player.get("diedAtFire"):
                player["missedPhantom"] = False
                continue
            attributions = player.get("shotAttribution") or []
            if any(row.get("verdict") in {"命中", "大概率命中"} for row in attributions):
                player["missedPhantom"] = False
                player["actualPhantomHitCount"] = max(int(player.get("actualPhantomHitCount") or 0), 1)
            elif any("未命中" in str(row.get("verdict") or "") and row.get("confidence") in {"high", "medium"} for row in attributions):
                player["missedPhantom"] = True
        repaired += 1
    audit.setdefault("meta", {}).setdefault("schemaVersion", "2026-07-14-healer-state-v4")
    return repaired


def board_row(fight, name, key, label):
    role = role_for(fight, name)
    return {
        "name": name,
        "role": role,
        "roles": [] if role == "unknown" else [role],
        "spellKey": key,
        "spellName": label,
        "hitCount": 0,
        "deathCount": 0,
        "totalDamage": 0,
        "events": [],
    }


def normalize_snap_aiming(fight):
    audit = ((fight.get("crownOfTheCosmos") or {}).get("fieldAudit") or {})
    per_player = {}
    for group in audit.get("bowGroups") or []:
        for player in group.get("players") or []:
            name = player.get("player")
            if not name:
                continue
            item = per_player.setdefault(name, board_row(fight, name, "collapsingVoidSnapAiming", "崩裂空无甩狙"))
            item["markedCount"] = int(item.get("markedCount") or 0) + 1
            if not player.get("isSnapAiming"):
                continue
            deaths = player.get("snapAimingDeaths") or []
            item["hitCount"] += 1
            item["deathCount"] += len(deaths)
            movement = float(player.get("lastSecondMovementYards") or 0)
            item["events"].append({
                "fightID": fight.get("fightID"),
                "phase": group.get("phase"),
                "group": group.get("index"),
                "time": player.get("fadeTime") or group.get("fireTime"),
                "positionMs": player.get("fadeTimeMs") or group.get("fireTimeMs"),
                "movementYards": movement,
                "players": [death.get("player") for death in deaths if death.get("player")],
                "deathCount": len(deaths),
                "counted": bool(deaths),
                "countReason": (
                    f"最后1秒移动{movement:.2f}码，甩狙导致{len(deaths)}名队友死亡"
                    if deaths else f"最后1秒移动{movement:.2f}码，判定甩狙；未导致队友死亡，不进入终审"
                ),
            })
    fight["avoidableSummary"].pop("collapsingVoidFriendlyFire", None)
    fight["avoidableSummary"]["collapsingVoidSnapAiming"] = list(per_player.values())
    audit.setdefault("summary", {})["snapAimingByPlayer"] = [
        {
            "player": row["name"],
            "markedCount": row.get("markedCount", 0),
            "snapCount": row.get("hitCount", 0),
            "deathCount": row.get("deathCount", 0),
        }
        for row in sorted(per_player.values(), key=lambda item: (item.get("deathCount", 0), item.get("hitCount", 0), item.get("markedCount", 0)), reverse=True)
    ]


def normalize_shadow_misses(fight):
    crown = fight.get("crownOfTheCosmos") or {}
    groups = ((crown.get("fieldAudit") or {}).get("bowGroups") or [])
    marked_counts = {}
    for group in groups:
        if group.get("phase") != "P2":
            continue
        for player in group.get("players") or []:
            if player.get("phantomEligible"):
                name = player.get("player")
                marked_counts[name] = marked_counts.get(name, 0) + 1

    per_player = {}
    details = []
    for group in groups:
        if group.get("phase") != "P2" or not group.get("phantomEligible"):
            continue
        marked_names = [player.get("player") for player in group.get("players") or []]
        for player in group.get("players") or []:
            if player.get("diedAtFire"):
                continue
            confirmed = [
                row for row in player.get("shotAttribution") or []
                if row.get("confidence") in {"high", "medium"} and "未命中" in str(row.get("verdict") or "")
            ]
            if not player.get("missedPhantom") or not confirmed:
                continue
            name = player.get("player")
            item = per_player.setdefault(name, board_row(fight, name, "missedShadows", "P2 拉弓未命中幻影"))
            item["markedCount"] = marked_counts.get(name, 0)
            item["hitCount"] += 1
            event = {
                "fightID": fight.get("fightID"),
                "phase": "P2",
                "group": group.get("index"),
                "time": group.get("fireTime"),
                "positionMs": group.get("fireTimeMs"),
                "players": marked_names,
                "tag": f"bow:{group.get('id')}",
                "attribution": confirmed,
                "counted": True,
                "countReason": "该玩家在有银色幻影的P2拉弓中存在明确未命中证据",
            }
            item["events"].append(event)
            details.append({**event, "player": name, "text": f"{group.get('fireTime')} {name} 未命中银色幻影"})
    fight["avoidableSummary"]["missedShadows"] = list(per_player.values())
    crown["missedShadows"] = details
    summary = ((crown.get("fieldAudit") or {}).setdefault("summary", {}))
    summary["p2MissedPhantomByPlayer"] = [
        {"player": row["name"], "markedCount": row.get("markedCount", 0), "count": row.get("hitCount", 0)}
        for row in sorted(per_player.values(), key=lambda item: item.get("hitCount", 0), reverse=True)
    ]
    summary["p2MarkedByPlayer"] = [
        {"player": player, "count": count}
        for player, count in sorted(marked_counts.items(), key=lambda item: item[1], reverse=True)
    ]


def event_clusters(events, window_ms=5_000):
    clusters = []
    for event in sorted(events, key=lambda row: int(row.get("absoluteTime") or 0)):
        timestamp = int(event.get("absoluteTime") or 0)
        if not clusters or timestamp - clusters[-1]["end"] > window_ms:
            clusters.append({"start": timestamp, "end": timestamp, "events": [event]})
        else:
            clusters[-1]["end"] = timestamp
            clusters[-1]["events"].append(event)
    return clusters


def normalize_classification(fight):
    crown = fight.get("crownOfTheCosmos") or {}
    if fight.get("isKill") or fight.get("kill") or fight.get("fightStatus") == "已击杀":
        return
    deaths = fight.get("deathTimeline") or []
    decisive = max(event_clusters(deaths), key=lambda cluster: len(cluster["events"]), default=None)
    if decisive:
        prior_players = {
            death.get("player") for death in deaths
            if death.get("player") and int(death.get("absoluteTime") or 0) < decisive["start"]
        }
        decisive_phase = (decisive.get("events") or [{}])[0].get("phase")
        if decisive_phase == "P3" and len(prior_players) >= 4:
            phase_counts = {}
            for death in deaths:
                if int(death.get("absoluteTime") or 0) >= decisive["start"]:
                    continue
                phase_name = death.get("phase") or "未知阶段"
                phase_counts[phase_name] = phase_counts.get(phase_name, 0) + 1
            distribution = "、".join(f"{phase} {count}人次" for phase, count in phase_counts.items())
            fight["fightPhase"] = "P3"
            fight["wipePhase"] = "P3"
            fight["wipeReason"] = "P3 前置减员过多后团队崩溃"
            fight["investigation"] = f"最终死亡簇前已有 {len(prior_players)} 名不同玩家发生过死亡，判定为前置阶段减员过多导致团队失去续战能力。"
            if distribution:
                fight["investigation"] += f"前置死亡分布：{distribution}。"
            crown["classificationKey"] = "prior_attrition_collapse"
            return

    bridge_deaths = [death for death in deaths if death.get("abilityID") in {None, 3} or death.get("ability") in {"坠崖", "转阶段击飞"}]
    bridge_cluster = max(event_clusters(bridge_deaths), key=lambda cluster: len(cluster["events"]), default=None)
    if bridge_cluster and len(bridge_cluster["events"]) >= 2:
        prior_real = [
            death for death in deaths
            if int(death.get("absoluteTime") or 0) < bridge_cluster["start"] and death not in bridge_deaths
        ]
        prior_players = {death.get("player") for death in prior_real if death.get("player")}
        bridge_phase = bridge_cluster["events"][0].get("phase")
        if len(prior_players) >= 4 and bridge_phase in {"P2", "P2.5", "P3"}:
            prior_p2 = [death for death in prior_real if death.get("phase") == "P2"]
            prior_p15 = [death for death in prior_real if death.get("phase") == "P1.5"]
            prior_p15_all = [
                death for death in deaths
                if death.get("phase") == "P1.5" and int(death.get("absoluteTime") or 0) < bridge_cluster["start"]
            ]
            cause_phase = "P1.5" if bridge_phase == "P2" and not prior_p2 and len(prior_p15) >= 2 else bridge_phase
            if cause_phase == "P1.5":
                label = "P1.5 减员过多，进入 P2 后放弃"
                investigation = f"P1.5 已出现 {len(prior_p15_all)} 人次减员；进入 P2 后团队集中跳崖重开。"
            else:
                phase_losses = [death for death in deaths if death.get("phase") == cause_phase]
                label = f"{cause_phase} 团队减员后放弃"
                investigation = f"{cause_phase} 阶段累计出现 {len(phase_losses)} 人次减员，团队随后选择放弃。"
            fight["fightPhase"] = cause_phase
            fight["wipePhase"] = cause_phase
            fight["wipeReason"] = label
            fight["investigation"] = investigation
            crown["classificationKey"] = "phase_abandon"
            return

    if crown.get("classificationKey") not in {"p15_pull_deaths", "p15_team_collapse"}:
        if crown.get("classificationKey") == "phase_abandon":
            if fight.get("wipePhase") == "P1" and crown.get("p1ArrowIssues"):
                fight["wipeReason"] = "P1 银锋箭处理异常"
                fight["investigation"] = crown["p1ArrowIssues"][0].get("text") or fight.get("investigation")
            elif fight.get("wipePhase") != "P1":
                phase_name = fight.get("wipePhase") or fight.get("fightPhase") or "该阶段"
                phase_losses = [death for death in deaths if death.get("phase") == phase_name]
                fight["investigation"] = f"{phase_name} 阶段累计出现 {len(phase_losses)} 人次减员，团队随后选择放弃。"
        return
    decisive = max(event_clusters(deaths), key=lambda cluster: len(cluster["events"]), default=None)
    if not decisive or not decisive["events"] or decisive["events"][0].get("phase") != "P2":
        return
    p2_deaths = [death for death in deaths if death.get("phase") == "P2"]
    barrier_deaths = [death for death in p2_deaths if death.get("abilityID") == COSMIC_BARRIER_ID]
    bridge_deaths = [death for death in p2_deaths if death.get("abilityID") in {None, 3}]
    bridge_cluster = max(event_clusters(bridge_deaths), key=lambda cluster: len(cluster["events"]), default=None)

    if len(barrier_deaths) >= max(2, int(len(p2_deaths) * 0.6)):
        key = "p2_phantom_barrier"
        label = "P2 宇宙屏障狂暴（裂隙幻影未及时击杀）"
        investigation = f"P2 有 {len(barrier_deaths)} 人死于宇宙屏障；P1.5 已前置死亡 {sum(1 for death in deaths if death.get('phase') == 'P1.5')} 人。"
    elif bridge_cluster and len(bridge_cluster["events"]) >= 2:
        prior_real = [
            death for death in deaths
            if int(death.get("absoluteTime") or 0) < bridge_cluster["start"]
            and death.get("abilityID") not in {None, 3}
        ]
        prior_p2_real = [death for death in prior_real if death.get("phase") == "P2"]
        if len(prior_real) >= 5:
            key = "phase_abandon"
            if prior_p2_real:
                label = "P2 团队减员后放弃"
                investigation = f"P2 已发生 {len(prior_p2_real)} 次非坠崖死亡，随后团队集中跳崖重开。"
            else:
                label = "P2 入场时因 P1.5 前置减员过多放弃"
                investigation = f"P1.5 已前置死亡 {sum(1 for death in deaths if death.get('phase') == 'P1.5')} 人；进入 P2 后团队选择跳崖重开。"
        else:
            key = "phase_bridge_mistake"
            label = "P2 过桥 / 坠崖"
            investigation = "P2 发生集中坠崖，但此前没有形成大规模机制减员。"
    else:
        key = "p2_aoe_collapse"
        label = "P2 团队减员过多"
        investigation = "主死亡簇发生在 P2，按 P2 团队减员归类。"

    fight["fightPhase"] = "P2"
    fight["wipePhase"] = "P2"
    fight["wipeReason"] = label
    fight["investigation"] = investigation
    crown["classificationKey"] = key


def normalize_shocks(fight):
    crown = fight.get("crownOfTheCosmos") or {}
    per_player = {}
    for shock in crown.get("interferenceShockRows") or []:
        details = []
        actual = [
            cast for cast in shock.get("interrupted") or []
            if cast.get("evidence") == "wcl_interrupt_table"
        ]
        shock["interrupted"] = actual
        shock["interruptedCount"] = len(actual)
        shock["confidence"] = "wcl_interrupt_table" if actual else "no_explicit_interrupt_table_match"
        for cast in actual:
            spell_id = int(cast.get("spellID") or 0)
            cast["spell"] = PLAYER_CAST_NAMES.get(spell_id, f"Spell {spell_id}")
            details.append(f"{cast.get('player')}：{cast['spell']}（{spell_id}）")
            name = cast.get("player")
            row = per_player.setdefault(name, board_row(fight, name, "interferenceShockInterrupts", "干扰震荡打断"))
            row["hitCount"] += 1
            row["events"].append({
                **cast, "fightID": fight.get("fightID"), "time": shock.get("time"),
                "counted": True, "countReason": "WCL Interrupts 明确记录",
            })
        shock["text"] = f"{shock.get('time')} 干扰震荡实际打断 {len(details)} 人：{'；'.join(details)}" if details else f"{shock.get('time')} 干扰震荡没有明确 Interrupts 记录"
    fight.setdefault("avoidableSummary", {})["interferenceShockInterrupts"] = list(per_player.values())


def normalize_energy(fight):
    crown = fight.get("crownOfTheCosmos") or {}
    audit = crown.get("fieldAudit") or {}
    existing = crown.get("missedEnergy") or []
    rows = [row for row in existing if not row.get("counted")]
    for arrow in audit.get("silverArrows") or []:
        if arrow.get("phase") != "P2":
            continue
        for assignment in arrow.get("sourceAssignments") or []:
            if assignment.get("bossEnergyDrained"):
                continue
            players = list(assignment.get("players") or [])
            if not players:
                continue
            instance = assignment.get("sourceInstance")
            rows.append({
                "time": arrow.get("time"),
                "group": arrow.get("index"),
                "sourceInstance": instance,
                "missingCount": 0,
                "players": players,
                "counted": True,
                "verdictCounted": False,
                "displayOnly": True,
                "countReason": "该银色幻影对应的两名点名未使奥蕾莉亚能量 -5",
                "text": f"{arrow.get('time')} 点名玩家：{'、'.join(players)}；对应银色幻影 {instance or '-'} 未成功消除 Boss 能量",
            })
    for event in rows:
        event["verdictCounted"] = False
        event["displayOnly"] = True
    crown["missedEnergy"] = rows
    per_player = {}
    for event in rows:
        if not event.get("counted"):
            continue
        for player in event.get("players") or []:
            item = per_player.setdefault(player, board_row(fight, player, "missedEnergy", "P2消Boss能量失误"))
            item["hitCount"] += 1
            item["events"].append({**event, "fightID": fight.get("fightID")})
    fight["avoidableSummary"]["missedEnergy"] = list(per_player.values())


def normalize_rift_slash(fight):
    crown = fight.get("crownOfTheCosmos") or {}
    per_player = {}
    for slash in crown.get("riftSlashTankSwaps") or []:
        offender = slash.get("offender")
        identified = bool(offender and not str(offender).startswith("未能唯一识别"))
        fatal = bool(slash.get("causedTankDeath"))
        other_alive = slash.get("otherTankAlive") is True
        over_limit = int(slash.get("stack") or 0) > 3
        slash["counted"] = identified and fatal and other_alive and over_limit
        slash["scoreMultiplier"] = 1.0 if slash["counted"] else 0.0
        slash["countReason"] = (
            "死亡时裂隙挥砍层数>3，另一坦仍存活，存活坦克计数+1"
            if slash["counted"]
            else "未同时满足坦克死亡、层数>3及另一坦存活，仅展示不计数"
        )
        if not slash["counted"]:
            continue
        item = per_player.setdefault(offender, board_row(fight, offender, "tankRiftSlashFailure", "P2 裂隙挥砍换坦失误"))
        item["hitCount"] += 1
        item["deathCount"] += 1
        item["events"].append({**slash, "fightID": fight.get("fightID")})
    fight["avoidableSummary"]["tankRiftSlashFailure"] = list(per_player.values())


def normalize_gravity(fight):
    crown = fight.get("crownOfTheCosmos") or {}
    rounds = ((crown.get("fieldAudit") or {}).get("gravityRounds") or [])
    deaths = fight.get("deathTimeline") or []
    per_player = {}
    rendered = []
    for round_row in rounds:
        apply_ms = int(round_row.get("applyTimeMs") or 0)
        prior = [death for death in deaths if int(death.get("absoluteTime") or 0) < int(fight.get("fightStart") or 0) + apply_ms]
        prior_names = {death.get("player") for death in prior if death.get("player")}
        prior_healers = [death for death in prior if str(death.get("role") or "").endswith("-healer")]
        first = min(
            (row for row in round_row.get("violations") or []),
            key=lambda row: int(row.get("order") or 999),
            default=None,
        )
        death_count = int(round_row.get("deathCount") or 0)
        round_healer_deaths = sum(
            1 for name in round_row.get("deathPlayers") or []
            if str(role_for(fight, name)).endswith("-healer")
        )
        healer_death_count = len(prior_healers) + round_healer_deaths
        exempt_reason = None
        if len(prior_names) > 4 or healer_death_count > 2:
            exempt_reason = f"大团已减员过多（本轮前已有{len(prior_names)}名不同玩家死亡，本轮结算后治疗死亡{healer_death_count}人）"
        elif not death_count:
            exempt_reason = "本轮没有造成减员"
        counted = bool(first and death_count and not exempt_reason)
        round_row.update({
            "priorDeathCount": len(prior_names),
            "priorHealerDeathCount": len(prior_healers),
            "healerDeathCountThroughRound": healer_death_count,
            "firstViolation": first,
            "attributedPlayer": first.get("player") if first else None,
            "attributedPlayerID": first.get("targetID") if first else None,
            "causedDeaths": bool(death_count),
            "counted": counted,
            "exemptReason": exempt_reason,
        })
        death_text = f"是（{first.get('player')}·{death_count}人）" if death_count and first else "否"
        reason = (
            f"归因：{first.get('player')}为本轮第一个违规者（{first.get('rule')}，{int(first.get('delayMs') or 0) / 1000:.3f}秒）"
            if first else "归因：未发现违反时序的拉线玩家"
        )
        if exempt_reason:
            reason += f"；豁免：{exempt_reason}"
        round_row["text"] = f"{round_row.get('applyTime')} 本轮是否减员：{death_text}；{reason}"
        rendered.append(round_row)
        if not counted:
            continue
        name = first["player"]
        item = per_player.setdefault(name, board_row(fight, name, "gravityLineViolation", "P3 重力坍缩违规致死"))
        item["hitCount"] += 1
        item["deathCount"] += death_count
        item["events"].append({
            **first,
            "fightID": fight.get("fightID"),
            "phase": "P3",
            "group": round_row.get("index"),
            "players": round_row.get("targets") or [],
            "deathCount": death_count,
            "deathPlayers": round_row.get("deathPlayers") or [],
            "counted": True,
            "countReason": f"首个违规者导致本轮减员{death_count}人",
            "text": round_row["text"],
        })
    crown["gravityRows"] = rendered
    fight["avoidableSummary"]["gravityLineViolation"] = list(per_player.values())


def matching_void_grasp_bow_from_json(fight, target_id, death_ms):
    groups = sorted(
        (((fight.get("crownOfTheCosmos") or {}).get("fieldAudit") or {}).get("bowGroups") or []),
        key=lambda row: int(row.get("applyStartMs") or 0),
    )
    candidates = []
    for group in groups:
        for player in group.get("players") or []:
            if player.get("targetID") != target_id:
                continue
            start_ms = int(player.get("applyTimeMs") or group.get("applyStartMs") or 0)
            end_ms = int(player.get("fadeTimeMs") or group.get("fireTimeMs") or start_ms)
            if start_ms <= death_ms <= end_ms + 1_000:
                candidates.append((abs(end_ms - death_ms), group))
    if not candidates:
        return None
    group = min(candidates, key=lambda item: item[0])[1]
    same_phase = [row for row in groups if row.get("phase") == group.get("phase")]
    return {
        "id": group.get("id"),
        "index": group.get("index"),
        "phase": group.get("phase"),
        "phaseIndex": same_phase.index(group) + 1 if group in same_phase else None,
    }


def normalize_void_healing(fight, threshold):
    crown = fight.get("crownOfTheCosmos") or {}
    audit_rows = ((crown.get("fieldAudit") or {}).get("voidDeaths") or [])
    deaths = fight.get("deathTimeline") or []
    normalized = []
    low_board = {}
    for row in crown.get("voidGraspHealing") or []:
        event_ms = int(row.get("positionMs") or 0)
        verified_death = min(
            (
                death for death in deaths
                if death.get("player") == row.get("player")
                and int(death.get("abilityID") or 0) == VOID_GRASP_ID
                and abs(time_to_ms(death.get("time")) - event_ms) <= 1_000
            ),
            key=lambda death: abs(time_to_ms(death.get("time")) - event_ms),
            default=None,
        )
        if verified_death is None:
            continue
        bow = matching_void_grasp_bow_from_json(fight, row.get("playerID"), event_ms)
        prior_dead_names = {
            death.get("player") for death in deaths
            if int(death.get("absoluteTime") or 0) < int(fight.get("fightStart") or 0) + event_ms
        }
        audit = min(
            (
                item for item in audit_rows
                if item.get("targetID") == row.get("playerID")
                and abs(int(item.get("timeMs") or 0) - event_ms) <= 1_000
            ),
            key=lambda item: abs(int(item.get("timeMs") or 0) - event_ms),
            default=None,
        )
        phantom_count = int((audit or {}).get("activePhantomCount") or 0)
        dead_player_count = int((audit or {}).get("deadPlayerCountAtDeath") or len(prior_dead_names))
        healer_roster_count = int((audit or {}).get("healerRosterCount") or 0)
        alive_healer_ids = set((audit or {}).get("aliveHealerIDsAtDeath") or [])
        alive_healer_count = int(
            (audit or {}).get("aliveHealerCountAtDeath")
            if (audit or {}).get("aliveHealerCountAtDeath") is not None
            else max(0, healer_roster_count - sum(1 for name in prior_dead_names if name in DESIGNATED_HEALERS))
        )
        reasons = []
        if crown.get("classificationKey") == "phase_abandon":
            reasons.append("放弃/add引怪战斗")
        if dead_player_count > 3:
            reasons.append(f"死亡时场上已有{dead_player_count}名玩家减员")
        if phantom_count >= 4:
            reasons.append(f"场上存活银色幻影{phantom_count}个")
        if alive_healer_count < 4:
            reasons.append(f"死亡时治疗组未满员（存活{alive_healer_count}/4）")
        exempt = bool(reasons)
        healer_by_name = {}
        for source in row.get("healers") or []:
            name = source.get("healer")
            if not name:
                continue
            merged = healer_by_name.setdefault(name, {
                "healer": name,
                "healerID": source.get("healerID"),
                "healerIDs": [],
                "healing6s": 0,
                "healing8s": 0,
            })
            source_ids = source.get("healerIDs") or ([source.get("healerID")] if source.get("healerID") is not None else [])
            merged["healerIDs"] = list(dict.fromkeys(merged["healerIDs"] + source_ids))
            merged["healing6s"] += int(source.get("healing6s") or 0)
            merged["healing8s"] += int(source.get("healing8s") or 0)
        audit_healers = {}
        for source in (audit or {}).get("healingByHealer") or []:
            name = source.get("healer")
            if name:
                audit_healers[name] = source
        for source in (audit or {}).get("healerRoster") or []:
            name = source.get("healer")
            if name and name not in audit_healers:
                audit_healers[name] = source
        for name, source in audit_healers.items():
            if name not in DESIGNATED_HEALERS:
                continue
            source_id = source.get("healerID")
            merged = healer_by_name.setdefault(name, {
                "healer": name,
                "healerID": source_id,
                "healerIDs": [],
                "healing6s": int(source.get("healing6s", source.get("amount") or 0)),
                "healing8s": int(source.get("healing8s", source.get("amount") or 0)),
            })
            if source_id is not None and source_id not in merged["healerIDs"]:
                merged["healerIDs"].append(source_id)
        healers = []
        for name in sorted(DESIGNATED_HEALERS):
            source = healer_by_name.get(name) or {"healer": name, "healing6s": 0, "healing8s": 0}
            source_ids = set(source.get("healerIDs") or ([source.get("healerID")] if source.get("healerID") is not None else []))
            if alive_healer_ids:
                if not (source_ids & alive_healer_ids):
                    continue
            elif name in prior_dead_names:
                continue
            healer = {**source, "insufficient": not exempt and int(source.get("healing8s") or 0) < threshold}
            healers.append(healer)
        fixed = {
            **row,
            "verifiedDeath": True,
            "deathAbilityID": VOID_GRASP_ID,
            "bowID": (bow or {}).get("id"),
            "bowGroup": (bow or {}).get("index"),
            "bowPhase": (bow or {}).get("phase"),
            "phaseBowGroup": (bow or {}).get("phaseIndex"),
            "window8s": f"{ms_to_time(max(0, event_ms - 8_000))}-{ms_to_time(event_ms)}",
            "healers": healers,
            "totalHealing6s": sum(int(healer.get("healing6s") or 0) for healer in healers),
            "activePhantomCount": phantom_count,
            "deadPlayerCountAtDeath": dead_player_count,
            "healerRosterCount": healer_roster_count,
            "aliveHealerCountAtDeath": alive_healer_count,
            "aliveHealerIDsAtDeath": sorted(alive_healer_ids),
            "exempt": exempt,
            "exemptionReasons": reasons,
            "counted": not exempt,
        }
        normalized.append(fixed)
        victim = row.get("player")
        if exempt:
            continue
        for healer in healers:
            if not healer.get("insufficient"):
                continue
            name = healer["healer"]
            item = low_board.setdefault(name, board_row(fight, name, "voidGraspHealingLow", "空虚之握死亡治疗不足"))
            item["hitCount"] += 1
            bow_text = (
                f"{fixed.get('bowPhase')}拉弓#{fixed.get('phaseBowGroup')}（全场#{fixed.get('bowGroup')}）"
                if fixed.get("bowGroup") else "未匹配到拉弓轮次"
            )
            healing_amount = int(healer.get("healing8s") or 0)
            item["events"].append({
                **healer,
                "death": victim,
                "deathTime": row.get("time"),
                "time": row.get("time"),
                "positionMs": event_ms,
                "fightID": fight.get("fightID"),
                "phase": fixed.get("bowPhase"),
                "group": fixed.get("bowGroup"),
                "phaseGroup": fixed.get("phaseBowGroup"),
                "tag": f"bow:{fixed.get('bowID')}" if fixed.get("bowID") else None,
                "victimVerifiedDead": True,
                "counted": True,
                "countReason": "已核对死亡事件；死亡时减员≤3、幻影<4且4名治疗均存活，统计死亡前8秒指定治疗量低于阈值",
                "text": f"{victim} 于 Fight{fight.get('fightID')} {bow_text}中阵亡（{row.get('time')}）；死亡前8秒内 {name} 对其治疗量为 {healing_amount:,}",
            })
    crown["voidGraspHealing"] = normalized
    fight["avoidableSummary"]["voidGraspHealingLow"] = list(low_board.values())
    fight["avoidableSummary"].pop("voidGraspDeaths", None)


def normalize_water_outliers(fight):
    audit = ((fight.get("crownOfTheCosmos") or {}).get("fieldAudit") or {})
    water_events = audit.get("waterEvents") or []
    first_p2_water_id = next((event.get("id") for event in water_events if event.get("phase") == "P2"), None)
    per_player = {}
    for water_event in water_events:
        if water_event.get("phase") == "P1" or water_event.get("id") == first_p2_water_id:
            continue
        for drop in water_event.get("drops") or []:
            if not drop.get("isOutlier") or drop.get("applyTimeMs") is None:
                continue
            name = drop.get("player")
            item = per_player.setdefault(name, board_row(fight, name, "waterOutliers", "放水未集中"))
            item["hitCount"] += 1
            item["events"].append({
                "time": drop.get("time"),
                "positionMs": drop.get("timeMs"),
                "phase": water_event.get("phase"),
                "group": water_event.get("index"),
                "player": name,
                "targetID": drop.get("targetID"),
                "markTime": ms_to_time(drop.get("applyTimeMs")),
                "markPositionMs": drop.get("applyTimeMs"),
                "distanceFromCenter": drop.get("distanceFromGroupYards"),
                "distanceFromGroupYards": drop.get("distanceFromGroupYards"),
                "position": drop.get("position"),
                "fightID": fight.get("fightID"),
                "tag": f"water:{water_event.get('id')}",
                "counted": True,
                "countReason": "坐标离组超过15码",
                "text": f"{name}（actor ID {drop.get('targetID')}）坐标离组 {drop.get('distanceFromGroupYards')} 码",
            })
    fight["avoidableSummary"]["waterOutliers"] = list(per_player.values())


def build_transition_analysis(fights):
    fight_rows = []
    summary = {}
    for fight in fights:
        rows = []
        for source in fight.get("transitionDetails") or []:
            ability_id = int(source.get("abilityID") or 0)
            source_phase = source.get("phase")
            if ability_id in DIMENSIONAL_SLASH_IDS or source_phase == "P2.5" or source.get("category") in {"次元斩", "P2.5击飞", "P2.5死亡"}:
                category = "P2.5死亡"
                phase = "P2.5"
            elif source_phase == "P1.5" or source.get("category") == "P1.5死亡":
                category = "P1.5死亡"
                phase = "P1.5"
            else:
                continue
            row = {**source, "category": category, "phase": phase}
            rows.append(row)
            item = summary.setdefault(category, {
                "category": category,
                "deathCount": 0,
                "compensationCount": 0,
                "displayDeathCount": 0,
                "players": {},
            })
            item["deathCount"] += int(row.get("deathCount") or 0)
            item["compensationCount"] += int(row.get("compensationCount") or 0)
            item["displayDeathCount"] += int(row.get("displayDeathCount") or 0)
            player = row.get("player")
            if player:
                item["players"][player] = item["players"].get(player, 0) + 1
        fight["transitionDetails"] = rows
        if rows:
            fight_rows.append({
                "reportID": fight.get("reportID"),
                "fightID": fight.get("fightID"),
                "startDateTime": fight.get("startDateTime"),
                "duration": fight.get("duration"),
                "rows": rows,
            })
    return {
        "summary": [
            {
                **row,
                "players": [
                    {"name": name, "count": count}
                    for name, count in sorted(row["players"].items(), key=lambda item: item[1], reverse=True)
                ],
            }
            for row in summary.values()
        ],
        "fights": fight_rows,
    }


def merge_boards(fights):
    merged = {}
    for fight in fights:
        for key, rows in (fight.get("avoidableSummary") or {}).items():
            bucket = merged.setdefault(key, {})
            for row in rows or []:
                name = row.get("name")
                if not name:
                    continue
                item = bucket.setdefault(name, {
                    "name": name,
                    "spellKey": row.get("spellKey") or key,
                    "spellName": row.get("spellName") or key,
                    "role": row.get("role", "unknown"),
                    "roles": list(row.get("roles") or []),
                    "hitCount": 0,
                    "markedCount": 0,
                    "deathCount": 0,
                    "totalDamage": 0,
                    "damageText": row.get("damageText"),
                    "events": [],
                })
                item["roles"] = list(dict.fromkeys(item["roles"] + list(row.get("roles") or [])))
                item["hitCount"] += int(row.get("hitCount") or 0)
                item["markedCount"] += int(row.get("markedCount") or 0)
                item["deathCount"] += int(row.get("deathCount") or 0)
                item["totalDamage"] += int(row.get("totalDamage") or 0)
                item["events"].extend(row.get("events") or [])
    return {
        key: sorted(rows.values(), key=lambda row: (row["deathCount"], row["hitCount"], row["totalDamage"]), reverse=True)
        for key, rows in merged.items()
    }


def rebuild_verdict(board, config):
    players = {}
    tank_multiplier = float(config.get("verdictTankMultiplier") or 1)
    points = int(config.get("verdictPointsPerCount") or 10)
    for key, rows in board.items():
        if key in FINAL_VERDICT_EXCLUDED:
            continue
        for row in rows:
            name = row.get("name")
            if not name:
                continue
            item = players.setdefault(name, {"name": name, "roles": [], "recognitionCount": 0, "appealAcquittalCount": 0, "breakdown": {}, "penaltyUnits": 0.0})
            roles = list(row.get("roles") or ([row.get("role")] if row.get("role") else []))
            item["roles"] = list(dict.fromkeys(item["roles"] + roles))
            if key == "collapsingVoidSnapAiming":
                count = int(row.get("deathCount") or 0)
            elif key in {"corruptionEssenceHits", "corruptionEssenceTop3"}:
                count = sum(1 for event in row.get("events") or [] if event.get("counted"))
            else:
                count = int(row.get("hitCount") or row.get("deathCount") or 0)
            item["recognitionCount"] += count
            item["breakdown"][key] = item["breakdown"].get(key, 0) + count
            base = tank_multiplier if "tank" in roles else 1.0
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
        item["iqLoss"] = round(max(0, item["penaltyUnits"]) * points)
    return sorted(players.values(), key=lambda row: (row["iqLoss"], row["recognitionCount"]), reverse=True)


def reprocess(root):
    data = root.get("data") or {}
    fights = data.get("page1_wipeAnalysis") or []
    config = (root.setdefault("meta", {}).setdefault("courtConfig", {}))
    root["meta"]["mechanicVersion"] = "crown-of-the-cosmos-2026-07-14"
    config["designatedHealerNames"] = sorted(DESIGNATED_HEALERS)
    spell_labels = root["meta"].setdefault("avoidableSpells", {})
    spell_labels.pop("collapsingVoidFriendlyFire", None)
    spell_labels.pop("p3TransitionMistake", None)
    spell_labels.pop("corruptionEssenceHits", None)
    spell_labels.pop("corruptionEssenceTop3", None)
    spell_labels.pop("voidGraspDeaths", None)
    for key in REMOVED_AVOIDABLE_DAMAGE_KEYS:
        spell_labels.pop(key, None)
    spell_labels.update(AVOIDABLE_DAMAGE_LABELS)
    spell_labels["collapsingVoidSnapAiming"] = "崩裂空无甩狙"
    spell_labels["p1SilverArrowMissedFights"] = "P1 银锋箭未命中Boss场次"
    threshold = int(config.get("voidGraspHealingThreshold8s") or 200000)
    repair_stats = {"fights": 0, "groups": 0, "players": 0, "deathTriggerFights": 0, "deathTriggerGroups": 0}
    for fight in fights:
        fight.setdefault("avoidableSummary", {})
        fight["avoidableSummary"].pop("voidGraspDeaths", None)
        for key in REMOVED_AVOIDABLE_DAMAGE_KEYS:
            fight["avoidableSummary"].pop(key, None)
        repair_p1_arrow_attribution(fight)
        normalize_classification(fight)
        normalize_shocks(fight)
        fight["avoidableSummary"].pop("p3TransitionMistake", None)
        fight["avoidableSummary"].pop("corruptionEssenceHits", None)
        fight["avoidableSummary"].pop("corruptionEssenceTop3", None)
        for row in fight["avoidableSummary"].get("corruptionEssenceDamage") or []:
            row["totalDamage"] = 0
            row["deathCount"] = 0
            row["damageText"] = "-"
            row["events"] = []
        repaired_groups, restored_players, death_trigger_groups = restore_bow_players(fight)
        if repaired_groups:
            repair_stats["fights"] += 1
            repair_stats["groups"] += repaired_groups
            repair_stats["players"] += restored_players
            repair_stats["deathTriggerGroups"] += death_trigger_groups
            if death_trigger_groups:
                repair_stats["deathTriggerFights"] += 1
        repair_phantom_attribution(fight)
        normalize_p1_arrow_misses(fight)
        normalize_snap_aiming(fight)
        normalize_shadow_misses(fight)
        normalize_energy(fight)
        normalize_rift_slash(fight)
        normalize_gravity(fight)
        normalize_void_healing(fight, threshold)
        normalize_water_outliers(fight)
    board = merge_boards(fights)
    data["page2_avoidableBoard"] = board
    data["page2_transitionAnalysis"] = build_transition_analysis(fights)
    court_board = dict(board)
    data["page3_courtBoard"] = court_board
    data["page4_finalVerdict"] = rebuild_verdict(court_board, (root.get("meta") or {}).get("courtConfig") or {})
    root["meta"]["localReprocess"] = {"bowRepair": repair_stats}
    return root


def main():
    parser = argparse.ArgumentParser(description="Reprocess an existing Crown JSON without making WCL requests.")
    parser.add_argument("path", nargs="?", default="wcl_hardcore_api.json")
    args = parser.parse_args()
    path = Path(args.path).resolve()
    root = json.loads(path.read_text(encoding="utf-8"))
    reprocess(root)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(root, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
    print(f"Reprocessed locally: {path}")
    stats = root["meta"]["localReprocess"]["bowRepair"]
    print(
        f"Bow repair: fights={stats['fights']} groups={stats['groups']} "
        f"players={stats['players']} death_trigger_fights={stats['deathTriggerFights']} "
        f"death_trigger_groups={stats['deathTriggerGroups']}"
    )


if __name__ == "__main__":
    main()
