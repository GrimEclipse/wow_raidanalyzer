import argparse
import json
from pathlib import Path


DESIGNATED_HEALERS = {"旖旎云逸", "暗黑膏药"}
FINAL_VERDICT_EXCLUDED = {"collapsingVoidFriendlyFire", "interferenceShockInterrupts", "voidGraspDeaths"}
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
            nested_rays = [] if died else legacy_ray_payload(ray)
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
                "fadeState": None if died else state,
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
            restored_dead = any(player.get("diedAtFire") for player in restored_all)
            any_alive = any(not player.get("diedAtFire") for player in group.get("players") or [])
            if restored_dead and any_alive:
                death_trigger_groups += 1
    return repaired_groups, restored_players, death_trigger_groups


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
    if crown.get("classificationKey") not in {"p15_pull_deaths", "p15_team_collapse"}:
        return
    deaths = fight.get("deathTimeline") or []
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
    for shock in crown.get("interferenceShockRows") or []:
        details = []
        for cast in shock.get("interrupted") or []:
            spell_id = int(cast.get("spellID") or 0)
            cast["spell"] = PLAYER_CAST_NAMES.get(spell_id, f"Spell {spell_id}")
            details.append(f"{cast.get('player')}：{cast['spell']}（{spell_id}）")
        shock["text"] = f"{shock.get('time')} 干扰震荡打断 {len(details)} 人：{'；'.join(details)}" if details else f"{shock.get('time')} 干扰震荡未识别到未完成读条"
    for row in (fight.get("avoidableSummary") or {}).get("interferenceShockInterrupts") or []:
        for event in row.get("events") or []:
            spell_id = int(event.get("spellID") or 0)
            event["spell"] = PLAYER_CAST_NAMES.get(spell_id, f"Spell {spell_id}")


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
                "countReason": "该银色幻影对应的两名点名未使奥蕾莉亚能量 -5",
                "text": f"{arrow.get('time')} 点名玩家：{'、'.join(players)}；对应银色幻影 {instance or '-'} 未成功消除 Boss 能量",
            })
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


def normalize_void_healing(fight, threshold):
    crown = fight.get("crownOfTheCosmos") or {}
    audit_rows = ((crown.get("fieldAudit") or {}).get("voidDeaths") or [])
    deaths = fight.get("deathTimeline") or []
    normalized = []
    low_board = {}
    death_board = {}
    for row in crown.get("voidGraspHealing") or []:
        event_ms = int(row.get("positionMs") or 0)
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
        reasons = []
        if crown.get("classificationKey") == "phase_abandon":
            reasons.append("放弃/add引怪战斗")
        if phantom_count >= 4:
            reasons.append(f"场上存活银色幻影{phantom_count}个")
        exempt = bool(reasons)
        healer_by_name = {healer.get("healer"): healer for healer in row.get("healers") or []}
        healers = []
        for name in sorted(DESIGNATED_HEALERS):
            if name in prior_dead_names:
                continue
            source = healer_by_name.get(name) or {"healer": name, "healing6s": 0, "healing8s": 0}
            healer = {**source, "insufficient": not exempt and int(source.get("healing8s") or 0) < threshold}
            healers.append(healer)
        fixed = {
            **row,
            "healers": healers,
            "totalHealing6s": sum(int(healer.get("healing6s") or 0) for healer in healers),
            "activePhantomCount": phantom_count,
            "exempt": exempt,
            "exemptionReasons": reasons,
            "counted": not exempt,
        }
        normalized.append(fixed)
        victim = row.get("player")
        victim_item = death_board.setdefault(victim, board_row(fight, victim, "voidGraspDeaths", "空虚之握死亡"))
        victim_item["hitCount"] += 1
        victim_item["deathCount"] += 1
        victim_item["events"].append({
            **fixed,
            "fightID": fight.get("fightID"),
            "counted": False,
            "countReason": f"豁免：{'、'.join(reasons)}" if reasons else "空虚之握死亡记录，暂不计入终审",
            "lowHealers": [healer for healer in healers if healer.get("insufficient")],
        })
        if exempt:
            continue
        for healer in healers:
            if not healer.get("insufficient"):
                continue
            name = healer["healer"]
            item = low_board.setdefault(name, board_row(fight, name, "voidGraspHealingLow", "空虚之握死亡治疗不足"))
            item["events"].append({
                **healer,
                "death": victim,
                "time": row.get("time"),
                "fightID": fight.get("fightID"),
                "counted": True,
                "countReason": "指定治疗存活且8秒窗口治疗量低于阈值",
            })
    for item in low_board.values():
        item["hitCount"] = 1
    crown["voidGraspHealing"] = normalized
    fight["avoidableSummary"]["voidGraspHealingLow"] = list(low_board.values())
    fight["avoidableSummary"]["voidGraspDeaths"] = list(death_board.values())


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
                    "deathCount": 0,
                    "totalDamage": 0,
                    "damageText": row.get("damageText"),
                    "events": [],
                })
                item["roles"] = list(dict.fromkeys(item["roles"] + list(row.get("roles") or [])))
                item["hitCount"] += int(row.get("hitCount") or 0)
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
            if key in {"corruptionEssenceHits", "corruptionEssenceTop3"}:
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
    config["designatedHealerNames"] = sorted(DESIGNATED_HEALERS)
    root["meta"].setdefault("avoidableSpells", {})["collapsingVoidFriendlyFire"] = "崩裂空无误伤他人"
    threshold = int(config.get("voidGraspHealingThreshold8s") or 200000)
    repair_stats = {"fights": 0, "groups": 0, "players": 0, "deathTriggerFights": 0, "deathTriggerGroups": 0}
    for fight in fights:
        fight.setdefault("avoidableSummary", {})
        normalize_classification(fight)
        normalize_shocks(fight)
        for row in fight["avoidableSummary"].get("collapsingVoidFriendlyFire") or []:
            row["spellName"] = "崩裂空无误伤他人"
        repaired_groups, restored_players, death_trigger_groups = restore_bow_players(fight)
        if repaired_groups:
            repair_stats["fights"] += 1
            repair_stats["groups"] += repaired_groups
            repair_stats["players"] += restored_players
            repair_stats["deathTriggerGroups"] += death_trigger_groups
            if death_trigger_groups:
                repair_stats["deathTriggerFights"] += 1
        normalize_energy(fight)
        normalize_gravity(fight)
        normalize_void_healing(fight, threshold)
    board = merge_boards(fights)
    data["page2_avoidableBoard"] = board
    data["page3_courtBoard"] = board
    data["page4_finalVerdict"] = rebuild_verdict(board, (root.get("meta") or {}).get("courtConfig") or {})
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
