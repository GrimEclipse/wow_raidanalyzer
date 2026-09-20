"""Evidence-first analyzer for the Twin Fangs."""

from __future__ import annotations

from copy import deepcopy
from math import hypot
from statistics import median
from analyzer_core.config import resolve_analysis_options

CONFIG_SCHEMA = [
    {"key": "venomReviewEnabled", "type": "boolean", "label": "永恒毒液叠层与来源", "default": True},
    {"key": "feastReviewEnabled", "type": "boolean", "label": "贪婪盛宴消层检查", "default": True},
    {"key": "globulesReviewEnabled", "type": "boolean", "label": "每轮吃球与漏吃", "default": True},
    {"key": "waveReviewEnabled", "type": "boolean", "label": "腐蚀洪流波浪命中", "default": True},
    {"key": "broodReviewEnabled", "type": "boolean", "label": "史诗蛇头打断与点位", "default": True},
    {"key": "venomDeathReviewEnabled", "type": "boolean", "label": "史诗带毒死亡与后续爆球", "default": True},
    {"key": "stoneReviewEnabled", "type": "boolean", "label": "裂石击接圈与全团伤害", "default": True},
    {"key": "earlyDeathReviewEnabled", "type": "boolean", "label": "提前死亡与死亡伤害明细", "default": True},
    {"key": "feastStrategy", "type": "select", "label": "史诗贪婪盛宴打法", "default": "normal",
     "options": [{"value": "normal", "label": "非免疫分摊"}, {"value": "immunity", "label": "首段全团、后两段免疫组"}],
     "visibleWhen": {"field": "feastReviewEnabled", "equals": True}},
    {"key": "feastGroups", "type": "interruptGroups", "label": "免疫分摊名单（每轮四人）", "default": {},
     "description": "填写玩家名或本报告 Actor ID。每轮对应一次盛宴的后两段；第五轮以后须补充安排，不自动循环。未配置或名单无法唯一匹配时只显示证据，不计个人失误。",
     "groups": [{"key": "round1", "label": "第一轮：三法师＋猎人"}, {"key": "round2", "label": "第二轮：两战士保护＋两防骑无敌"},
                {"key": "round3", "label": "第三轮：三法师＋猎人"}, {"key": "round4", "label": "第四轮：两冰法＋奶骑无敌＋战士保护"}],
     "visibleWhen": {"field": "feastStrategy", "equals": "immunity"}},
    {"key": "protectionPairs", "type": "interruptGroups", "label": "保护责任人（依次填写施法者、受保护战士）", "default": {},
     "groups": [{"key": "round2a", "label": "第二轮第一组保护"}, {"key": "round2b", "label": "第二轮第二组保护"}, {"key": "round4", "label": "第四轮奶骑保护"}],
     "visibleWhen": {"field": "feastStrategy", "equals": "immunity"}},
    {"key": "broodGroups", "type": "interruptGroups", "label": "蛇头打断名单", "default": {},
     "description": "每侧远程按每次召唤中远点蛇头首次出现顺序分配，非固定点位号。近点 1、2 号由当前接该侧 Boss 的坦克主断，近战为补断。每个远程槽位填写一人。",
     "groups": [{"key": side + str(i), "label": label + "远程第" + str(i) + "个"} for side, label in [("left", "左侧"), ("right", "右侧")] for i in range(1, 4)]
               + [{"key": "leftBackup", "label": "左侧近战补断"}, {"key": "rightBackup", "label": "右侧近战补断"},
                  {"key": "leftRangedBackup", "label": "左侧远程第四个及以后补断（可选）"}, {"key": "rightRangedBackup", "label": "右侧远程第四个及以后补断（可选）"}],
     "visibleWhen": {"field": "broodReviewEnabled", "equals": True}},
    {"key": "earlyDeathGapSeconds", "type": "number", "label": "提前死亡与后续死亡间隔（秒）", "default": 8, "min": 3, "max": 60,
     "visibleWhen": {"field": "earlyDeathReviewEnabled", "equals": True}},
]


from collections import Counter, defaultdict

from boss_plugins.common import write_json_result
from boss_plugins.venomous_abyss.runtime import build_aggregated_json as _build
from boss_plugins.venomous_abyss.shared import (
    ability_id,
    active_immunities,
    avoidable_board as _avoidable_board,
    completed_casts as _completed_casts,
    death_near as _death_near,
    event_type,
    events_between as _events_between,
    fmt_ms,
    group_nearby,
    load_confirmed_spell_names,
    nightly_detail,
    nightly_player_totals,
    player_ref,
    spell_name,
)

GUIDE_SPELLS = load_confirmed_spell_names()
GUIDE_SPELLS.update({1306876: "血色风暴", 1294976: "剧毒烟气", 1295107: "浓缩唾液",
                     1292348: "永恒毒液", 1310105: "污秽爆发"})
DEATH_MECHANIC_NOTES = {1306876: "可躲避伤害：地板红色AOE", 1294976: "环境AOE",
                        1295107: "浓缩唾液", 1292348: "永恒毒液",
                        1310105: "吸圈未处理产生的全团爆发"}

BOSS_CONFIG = {
    "key": "twinfangs",
    "encounterIDs": {3421, 53421},
    "name": "双子毒牙",
    "arena": "assets/raids/venomous_abyss/06-twinfangs.jpg",
    "spellNames": GUIDE_SPELLS,
    "tabs": [
        ["survival", "全场存活情况"],
        ["venom", "永恒毒液"],
        ["globules", "地板炸圈"],
        ["feast", "盛宴分摊"], ["brood", "蛇头打断"],
        ["venomDeaths", "带毒死亡"], ["stone", "裂石击"], ["earlyDeaths", "提前死亡"],
    ],
    "mechanicVersion": "twinfangs-venom-rounds-immunity-timing-2026-09-20",
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

# WCL coordinates are hundredths of a yard. Centers calibrated from three live
# Mythic kills and vgdPJBnLNmzt13Qk; keep all encounter geometry in this module.
BROOD_ARENAS = (
    {"key": "north", "label": "上方场地", "bosses": {"left": (-1616, 69157), "right": (1586, 69132)},
     "left": [(-608, 69221), (-2621, 68385), (-3066, 67684), (-3259, 66245), (-3733, 65496)],
     "right": [(549, 69187), (2537, 68338), (2999, 67581), (3307, 66207), (3831, 65404)]},
    {"key": "southeast", "label": "右下场地", "bosses": {"left": (7684, 58466), "right": (6103, 55739)},
     "left": [(7347, 57244), (7186, 59504), (6642, 60475), (6112, 61455), (5641, 62417)],
     "right": [(6934, 56535), (5071, 55638), (3891, 55570), (2887, 55607), (1958, 55528)]},
    {"key": "southwest", "label": "左下场地", "bosses": {"left": (-6055, 55691), "right": (-7797, 58496)},
     "left": [(-6868, 56570), (-4893, 55657), (-4096, 55697), (-3289, 55662), (-2372, 55653)],
     "right": [(-7258, 57339), (-7189, 59537), (-6754, 60323), (-6363, 60931), (-5915, 61687)]},
)
BROOD_NPC_ID = 270898
BOSS_NPC_IDS = {257361, 257368}
BROOD_CAST_ID = 1308385
BROOD_SUMMON_ID = 1308356
FEAST_HIT_ID = 1290662
STONE_RAID_DAMAGE_ID = 1289153
IMMUNITY_NAMES = {45438: "寒冰屏障", 642: "圣盾术", 1022: "保护祝福", 186265: "灵龟守护"}
REVIEW_KEYS = [field["key"] for field in CONFIG_SCHEMA if field["type"] == "boolean"]


def _unique_events(events):
    result, seen = [], set()
    for e in sorted(events, key=lambda e: int(e.get("timestamp") or 0)):
        key = (e.get("timestamp"), event_type(e), ability_id(e), e.get("sourceID"), e.get("sourceInstance", 1),
               e.get("targetID"), e.get("targetInstance", 1), e.get("extraAbilityGameID"))
        if key not in seen:
            result.append(e)
            seen.add(key)
    return result


def _match_names(names, players):
    resolved, unresolved = [], []
    for name in names or []:
        matches = [pid for pid, p in players.items() if str(pid) == str(name) or p.get("name") == name]
        if len(matches) == 1 and matches[0] not in resolved:
            resolved.append(matches[0])
        else:
            unresolved.append(str(name))
    return resolved, unresolved


def _life_at(raw, pid, timestamp):
    alive = True
    if "_twinLifeEvents" not in raw:
        raw["_twinLifeEvents"] = _unique_events([e for e in raw.get("deaths", []) + raw.get("trackedActorEvents", []) + raw.get("friendlyCasts", [])
                                                if event_type(e) in {"death", "resurrect"}])
    for e in raw["_twinLifeEvents"]:
        if int(e.get("timestamp") or 0) > timestamp:
            break
        if e.get("targetID") != pid:
            continue
        if event_type(e) == "death":
            alive = False
        elif event_type(e) == "resurrect":
            alive = True
    return alive


def _locate_head(x, y):
    candidates = [(hypot(x - point[0], y - point[1]), arena, side, i, point)
                  for arena in BROOD_ARENAS for side in ("left", "right") for i, point in enumerate(arena[side], 1)]
    distance, arena, side, slot, point = min(candidates, key=lambda item: item[0])
    if distance > 400:
        return None
    return {"arena": arena["key"], "arenaLabel": arena["label"], "side": side, "slot": slot,
            "label": ("左" if side == "left" else "右") + str(slot), "x": x, "y": y,
            "centerX": point[0], "centerY": point[1], "offsetYards": round(distance / 100, 2)}


def _tank_for_boss(raw, players, boss_id, timestamp):
    # Current target evidence, not a fixed tank name or the Feast/Stone target.
    candidates = [e for e in raw.get("damage", []) if e.get("sourceID") == boss_id and int(ability_id(e) or 0) == 1
                  and e.get("targetID") in players and players[e["targetID"]].get("role", "").endswith("tank")
                  and 0 <= timestamp - int(e.get("timestamp") or 0) <= 15000]
    taunts = [e for e in raw.get("friendlyCasts", []) if e.get("targetID") == boss_id
              and e.get("sourceID") in players and players[e["sourceID"]].get("role", "").endswith("tank")
              and int(ability_id(e) or 0) in {62124, 355, 6795, 56222, 116189, 185245}
              and 0 <= timestamp - int(e.get("timestamp") or 0) <= 15000 and event_type(e) == "cast"]
    evidence = [(int(e["timestamp"]), e["targetID"], "Boss 普攻目标") for e in candidates]
    evidence += [(int(e["timestamp"]), e["sourceID"], "最近嘲讽") for e in taunts]
    evidence += [(int(e["timestamp"]), e["targetID"], "Boss 最近坦克技能目标")
                 for e in raw.get("casts", []) if e.get("sourceID") == boss_id
                 and ability_id(e) in {1289092, 1289192} and event_type(e) == "cast"
                 and e.get("targetID") in players and players[e["targetID"]].get("role", "").endswith("tank")
                 and 0 <= timestamp - int(e["timestamp"]) <= 15000]
    if not evidence:
        return None, None
    ts, pid, reason = max(evidence)
    if not _life_at(raw, pid, timestamp):
        return None, {"reason": "最近仇恨目标已死亡", "timestamp": ts}
    return pid, {"reason": reason, "timestamp": ts, "ageMs": timestamp - ts}


def _boss_for_side(raw, position, timestamp):
    arena = next(a for a in BROOD_ARENAS if a["key"] == position["arena"])
    point = arena["bosses"][position["side"]]
    game_ids = raw.get("trackedActorGameIDByActorID", {})
    ids = {int(aid) for aid, gid in game_ids.items() if gid in BOSS_NPC_IDS}
    # Casts expose the stationary boss position even while its melee is paused.
    samples = [e for e in raw.get("casts", []) if e.get("sourceID") in ids and e.get("x") is not None
               and e.get("y") is not None and 0 <= timestamp - int(e["timestamp"]) <= 60000
               and hypot(e["x"] - point[0], e["y"] - point[1]) <= 500]
    return max(samples, key=lambda e: e["timestamp"])["sourceID"] if samples else None


def _brood_review(fight, actor_map, players, raw, options):
    if int(fight.get("difficulty") or 0) != 5:
        return {"enabled": False, "reason": "仅适用于史诗难度", "events": []}
    start = int(fight["startTime"])
    casts = _unique_events(raw.get("casts", []) + raw.get("trackedActorEvents", []))
    summons = [e for e in casts if ability_id(e) == BROOD_SUMMON_ID and event_type(e) == "cast"]
    heads = defaultdict(list)
    for e in casts:
        if ability_id(e) == BROOD_CAST_ID and event_type(e) in {"begincast", "cast"}:
            heads[(e.get("sourceID"), e.get("sourceInstance", 1))].append(e)
    interrupts = [e for e in _unique_events(raw.get("interrupts", []) + raw.get("trackedActorEvents", []))
                  if event_type(e) == "interrupt" and e.get("extraAbilityGameID") == BROOD_CAST_ID]
    output = []
    for (actor, instance), events in heads.items():
        begun = min(int(e["timestamp"]) for e in events)
        completed = [e for e in events if event_type(e) == "cast"]
        kicks = [e for e in interrupts if e.get("targetID") == actor and e.get("targetInstance", 1) == instance]
        coordinates = []
        for e in raw.get("trackedActorEvents", []) + events:
            if e.get("x") is None or e.get("y") is None:
                continue
            source = e.get("resourceActor") in {1, "1"} or (e.get("resourceActor") is None and event_type(e) == "cast")
            side = "source" if source else "target" if e.get("resourceActor") in {2, "2"} else None
            if side and e.get(side + "ID") == actor and e.get(side + "Instance", 1) == instance:
                coordinates.append((e["x"], e["y"]))
        point = _locate_head(median(p[0] for p in coordinates), median(p[1] for p in coordinates)) if coordinates else None
        round_no = sum(int(e["timestamp"]) <= begun for e in summons)
        output.append({"round": round_no, "timeMs": begun - start, "time": fmt_ms(begun - start), "actorID": actor,
                       "instance": instance, "position": point, "successfulCasts": len(completed),
                       "successTimesMs": [int(e["timestamp"]) - start for e in completed],
                       "interrupts": [{"time": fmt_ms(int(e["timestamp"]) - start), "spellID": ability_id(e),
                                       "player": player_ref(players, actor_map, raw.get("petOwners", {}).get(e.get("sourceID"), e.get("sourceID")))} for e in kicks],
                       "status": "漏断成功施法" if completed else "已打断" if kicks else "未见成功施法，结局未确认",
                       "assigned": [], "backup": [], "failures": [], "assignmentNote": "", "rangedOrder": None})
    output.sort(key=lambda row: row["timeMs"])
    group_counts = Counter()
    for row in output:
        position = row["position"]
        if not position or not row["round"]:
            row["assignmentNote"] = "点位或召唤轮次证据不足，不作个人归责"
            continue
        side = position["side"]
        group = "melee" if position["slot"] <= 2 else "ranged"
        group_key = (row["round"], position["arena"], side, group)
        group_counts[group_key] += 1
        row["groupOrder"] = group_counts[group_key]
        row["groupLabel"] = ("左侧" if side == "left" else "右侧") + ("近战组" if group == "melee" else "远程组")
        row["leakLabel"] = f"{row['groupLabel']}第{row['groupOrder']}个蛇头漏断脏腑爆裂" if row["successfulCasts"] else None
        timestamp = start + (min(row["successTimesMs"]) if row["successTimesMs"] else row["timeMs"])
        backup, _ = _match_names(options["broodGroups"].get(side + "Backup"), players)
        assigned = []
        if position["slot"] <= 2:
            boss_id = _boss_for_side(raw, position, timestamp)
            tank, evidence = _tank_for_boss(raw, players, boss_id, timestamp) if boss_id is not None else (None, None)
            assigned = [tank] if tank is not None else []
            row.update({"bossActorID": boss_id, "tankEvidence": evidence, "backup": [player_ref(players, actor_map, pid) for pid in backup]})
            row["assignmentNote"] = "近点由当前坦克主断，近战补断；日志无法确认是否口头交接补断" if assigned else "缺少可靠的当时仇恨目标，无法分配坦克责任"
        else:
            order = row["groupOrder"]
            row["rangedOrder"] = order
            names = options["broodGroups"].get(side + str(order), [])
            assigned, unresolved = _match_names(names, players)
            if order > 3:
                assigned = []
                backup, _ = _match_names(options["broodGroups"].get(side + "RangedBackup", []), players)
                row["backup"] = [player_ref(players, actor_map, pid) for pid in backup]
                row["assignmentNote"] = "远程第四个及以后交补断，不重新轮转到第一人"
            elif len(assigned) != 1 or unresolved:
                assigned = []
                row["assignmentNote"] = "远程槽位未配置、重名或出现顺序超出三人安排，不计个人失误"
            else:
                row["assignmentNote"] = "按本轮该侧远点蛇头出现顺序分配"
        row["assigned"] = [player_ref(players, actor_map, pid) for pid in assigned]
        row["responsibilitySlot"] = ("左" if side == "left" else "右") + ("前" if group == "melee" else "后") + str(row["groupOrder"]) + "断"
        row["responsiblePlayers"] = row["assigned"]
    leaks = [row for row in output if row["successTimesMs"]]
    first = min(leaks, key=lambda row: min(row["successTimesMs"])) if leaks else None
    dead_count = sum(not _life_at(raw, pid, start + min(first["successTimesMs"]) - 1) for pid in players) if first else 0
    excluded = None
    if first and dead_count >= 3:
        excluded = {"time": fmt_ms(min(first["successTimesMs"])), "deadCount": dead_count,
                    "reason": "首次漏断前已有至少3人死亡且未战复，崩溃阶段不归责"}
        first = None
    if first:
        first["spawnTime"] = first["time"]
        first["spawnTimeMs"] = first["timeMs"]
        first["timeMs"] = min(first["successTimesMs"])
        first["time"] = fmt_ms(first["timeMs"])
        first["successTimesMs"] = [first["timeMs"]]
        first["successfulCasts"] = 1
    output = [first] if first else []
    return {"enabled": True, "events": output, "successfulCastCount": int(first is not None), "firstLeakOnly": True, "collapseExemption": excluded,
            "unresolvedCount": sum(r["position"] is None for r in output),
            "positionNote": "每场仅返回首次脏腑爆裂成功施法，后续漏断忽略。序号按此前该组蛇头出现顺序计算。面向场地尖端按左5→左1、右1→右5编号；坐标误差超过4码不匹配。", "arenas": BROOD_ARENAS}


def _immunity_state(raw, pid, timestamp, hits=()):
    if "_twinImmunityIntervals" not in raw:
        indexed, active = defaultdict(list), {}
        for e in sorted(raw.get("friendlyBuffs", []), key=lambda e: int(e.get("timestamp") or 0)):
            sid = int(ability_id(e) or 0)
            if sid not in IMMUNITY_NAMES:
                continue
            target, ts, kind = e.get("targetID"), int(e["timestamp"]), event_type(e)
            key = (target, sid)
            if kind in {"applybuff", "refreshbuff"}:
                active.setdefault(key, (ts, e.get("sourceID")))
            elif kind == "removebuff" and key in active:
                begin, source = active.pop(key)
                indexed[target].append((sid, begin, ts, source))
        for (target, sid), (begin, source) in active.items():
            indexed[target].append((sid, begin, 10**18, source))
        raw["_twinImmunityIntervals"] = indexed
    intervals = raw["_twinImmunityIntervals"].get(pid, [])
    covered = [{"spellID": sid, "spell": IMMUNITY_NAMES[sid], "sourceID": source, "start": begin, "end": end if end < 10**18 else None}
               for sid, begin, end, source in intervals if begin <= timestamp < end]
    # Buff snapshots on the exact hit are stronger evidence than an imprecise
    # apply timestamp. They also cover aura application before the pull starts.
    for hit in hits:
        snapshot = {int(v) for v in str(hit.get("buffs") or "").split('.') if v.isdigit()}
        for sid in snapshot.intersection(IMMUNITY_NAMES):
            if not any(r["spellID"] == sid for r in covered):
                covered.append({"spellID": sid, "spell": IMMUNITY_NAMES[sid], "sourceID": None, "start": None, "end": None})
    ended = [{"spellID": sid, "spell": IMMUNITY_NAMES[sid], "end": end, "sourceID": source, "secondsBefore": round((timestamp - end) / 1000, 3)}
             for sid, begin, end, source in intervals if 0 < timestamp - end <= 10000]
    immune_hit = any(h.get("hitType") == 10 for h in hits)
    protected_hit = bool(hits) and all(float(h.get("amount") or 0) == 0 for h in hits) and (immune_hit or bool(covered))
    return {"auras": covered, "recentlyEnded": ended, "immuneHit": immune_hit, "protectedHit": protected_hit,
            "hitTypes": sorted({h.get("hitType") for h in hits if h.get("hitType") is not None})}


def _immunity_usage_review(fight, actor_map, players, raw, rounds):
    """Review observed usage separately from missed-soak responsibility."""
    start, end = int(fight["startTime"]), int(fight["endTime"])
    casts = [e for e in _unique_events(raw.get("friendlyCasts", []))
             if ability_id(e) in IMMUNITY_NAMES and event_type(e) == "cast"
             and e.get("sourceID") in players and start <= int(e["timestamp"]) <= end]
    applications = [e for e in _unique_events(raw.get("friendlyBuffs", []))
                    if ability_id(e) in IMMUNITY_NAMES and event_type(e) == "applybuff"
                    and e.get("targetID") in players and start <= int(e["timestamp"]) <= end]
    # One activation may have both a cast and an aura application. Prefer the
    # aura's actual recipient (especially external Blessing of Protection).
    used_applications, activations = set(), []
    for cast in casts:
        sid, ts = ability_id(cast), int(cast["timestamp"])
        matches = [(i, e) for i, e in enumerate(applications) if i not in used_applications
                   and ability_id(e) == sid and e.get("sourceID") == cast.get("sourceID")
                   and (sid != 1022 or cast.get("targetID") not in players or e.get("targetID") == cast.get("targetID"))
                   and abs(int(e["timestamp"]) - ts) <= 1000]
        match = min(matches, key=lambda item: abs(int(item[1]["timestamp"]) - ts), default=None)
        if match:
            used_applications.add(match[0])
        aura = match[1] if match else None
        target = aura["targetID"] if aura else cast.get("targetID") if sid == 1022 else cast["sourceID"]
        activations.append((ts, sid, cast["sourceID"], target, aura))
    activations.extend((int(e["timestamp"]), ability_id(e), e.get("sourceID"), e["targetID"], e)
                       for i, e in enumerate(applications) if i not in used_applications)
    rows = []
    for ts, sid, source, target, aura in sorted(activations, key=lambda item: item[0]):
        _immunity_state(raw, target, ts)
        intervals = raw.get("_twinImmunityIntervals", {}).get(target, [])
        interval = next((item for item in intervals if item[0] == sid and aura is not None
                         and item[1] == int(aura["timestamp"])), None)
        aura_end = interval[2] if interval and interval[2] < 10**18 else None
        coverage = []
        for round_row in rounds:
            strikes = [s for s in round_row["strikes"] if s["index"] in ({1, 2, 3} if sid == 1022 else {2, 3})]
            covered = [s["index"] for s in strikes if interval
                       and interval[1] <= start + s["timeMs"] < interval[2]]
            if covered:
                coverage.append({"round": round_row["index"], "strikeIndices": covered})
        next_round = next((r for r in rounds if start + r["timeMs"] + 4250 >= ts
                           and any(p["playerID"] == target for p in r["assigned"])), None)
        upcoming = next_round or next((r for r in rounds if start + r["timeMs"] + 4250 >= ts), None)
        near_round = next((r for r in rounds if start + r["timeMs"] - 10000 <= ts <= start + r["timeMs"] + 4250), None)
        status, abnormal = "覆盖盛宴", False
        if not coverage:
            if not rounds:
                status = "未见盛宴记录，无法核对使用时机"
            elif near_round and interval is None:
                status = "盛宴附近施法，缺少光环覆盖证据"
            elif near_round and near_round["incomplete"]:
                status = "盛宴伤害段记录不完整，覆盖待核对"
            else:
                status, abnormal = "非盛宴时段使用，需复核用途", True
        # A successful immunity for an earlier round (including a substitute)
        # is not an off-timing use merely because a later assignment exists.
        if next_round and aura_end is not None and (not coverage or any(c["round"] == next_round["index"] for c in coverage)):
            required = [s for s in next_round["strikes"] if s["index"] in ({1, 2, 3} if sid == 1022 else {2, 3})]
            missing = [s for s in required if aura_end <= start + s["timeMs"]]
            if missing:
                status = "免疫已结束，未覆盖已安排的第 " + str(next_round["index"]) + " 轮第 " + "、".join(str(s["index"]) for s in missing) + " 段"
                abnormal = True
        replacements = []
        if next_round:
            for strike in next_round["strikes"]:
                if strike["index"] not in {2, 3} or any(p["playerID"] == target for p in strike["participants"]):
                    continue
                extras = [p for p in strike["participants"] if p["immunity"]["protectedHit"]
                          and p["playerID"] not in {a["playerID"] for a in next_round["assigned"]}]
                if extras:
                    replacements.append({"strikeIndex": strike["index"], "players": extras})
        rows.append({"timeMs": ts - start, "time": fmt_ms(ts - start), "spellID": sid, "spell": IMMUNITY_NAMES[sid],
                     "caster": player_ref(players, actor_map, source), "target": player_ref(players, actor_map, target),
                     "endTime": fmt_ms(aura_end - start) if aura_end is not None else None,
                     "coverage": coverage, "abnormal": abnormal, "status": status,
                     "nextRound": upcoming["index"] if upcoming else None,
                     "secondsBefore": round((start + upcoming["timeMs"] - ts) / 1000, 2) if upcoming else None,
                     "assigned": next_round is not None, "replacements": replacements})
    return {"events": rows, "abnormalCount": sum(row["abnormal"] for row in rows),
            "evidenceNote": "列出保护、无敌、冰箱、龟壳的实际使用；非盛宴时段或已结束未覆盖安排标为待复核，补位成功也保留。盛宴前10秒至第三段附近视为准备窗口；窗口外仍实际覆盖盛宴的使用不标异常。日志不能证明乱按、剩余冷却或补位的因果关系，本表不追加个人分摊失误。"}


def _feast_review(fight, actor_map, players, raw, options):
    if int(fight.get("difficulty") or 0) != 5:
        return {"enabled": False, "reason": "英雄消层检查见永恒毒液页", "rounds": []}
    start = int(fight["startTime"])
    casts = [e for e in _unique_events(raw.get("casts", [])) if ability_id(e) == 1290516 and event_type(e) == "cast"]
    hits = [e for e in raw.get("damage", []) if ability_id(e) == FEAST_HIT_ID and e.get("targetID") in players]
    rounds = []
    for index, cast in enumerate(casts, 1):
        ts = int(cast["timestamp"])
        buckets = defaultdict(list)
        for e in hits:
            offset = int(e["timestamp"]) - ts
            if not -200 <= offset <= 6000:
                continue
            closest = min(enumerate((0, 2000, 3500), 1), key=lambda item: abs(offset - item[1]))
            if abs(offset - closest[1]) <= 750:
                buckets[closest[0]].append(e)
        groups = sorted(buckets.items())
        ids, unresolved = _match_names(options["feastGroups"].get("round" + str(index), []), players)
        configured = len(ids) == 4 and not unresolved
        round_row = {"index": index, "time": fmt_ms(ts - start), "timeMs": ts - start, "strikes": [], "failures": [],
                     "assigned": [player_ref(players, actor_map, pid) for pid in ids], "unresolvedNames": unresolved,
                     "assignmentValid": configured, "configurationNote": "" if configured else "本轮需配置四名可唯一识别的免疫玩家，当前只展示实测证据"}
        failures = {}
        for strike_index, group in groups:
            hit_time = min(int(e["timestamp"]) for e in group)
            # Underfilled soaks produce a later raid-wide burst using the SAME
            # damage ID (~325ms later in live logs). Those victims did not soak.
            primary = [e for e in group if int(e["timestamp"]) - hit_time <= 200]
            spill = [e for e in group if int(e["timestamp"]) - hit_time > 200]
            by_player = defaultdict(list)
            for e in primary:
                by_player[e["targetID"]].append(e)
            participants = []
            for pid, events in by_player.items():
                immunity = _immunity_state(raw, pid, hit_time, events)
                participants.append({**player_ref(players, actor_map, pid), "damage": sum(int(e.get("amount") or 0) for e in events),
                                     "immunity": immunity, "result": "免疫" if immunity["immuneHit"] else "偏转/免疫覆盖的零伤害" if immunity["protectedHit"] else "实际命中"})
            strike = {"index": strike_index, "time": fmt_ms(hit_time - start), "timeMs": hit_time - start,
                      "participants": participants, "participantCount": len(by_player), "minimum": 4,
                      "underfilled": len(by_player) < 4, "assignmentChecks": [],
                      "secondaryRaidDamage": [{**player_ref(players, actor_map, e["targetID"]), "damage": int(e.get("amount") or 0),
                                               "delayMs": int(e["timestamp"]) - hit_time} for e in spill]}
            if options["feastStrategy"] == "immunity" and strike_index in {2, 3} and configured:
                for pid in ids:
                    events = by_player.get(pid, [])
                    immunity = _immunity_state(raw, pid, hit_time, events)
                    alive = _life_at(raw, pid, hit_time - 1)
                    reason = None
                    if not alive:
                        status = "此前已死亡，不追加分摊失误"
                    elif not events:
                        status = reason = "未见参与本段分摊的命中/免疫记录"
                        if len(participants) >= 4 and all(p["immunity"]["protectedHit"] for p in participants) and not spill:
                            status, reason = "其他玩家成功补位完成免疫分摊，不计名单缺席", None
                    elif not immunity["protectedHit"]:
                        status = reason = "免疫提前结束，未覆盖本段" if immunity["recentlyEnded"] else "参与分摊但未获得有效免疫"
                    else:
                        status = "正确免疫分摊"
                    uses = [e for e in raw.get("friendlyCasts", []) if e.get("sourceID") == pid and ability_id(e) in IMMUNITY_NAMES
                            and event_type(e) == "cast" and int(e["timestamp"]) <= hit_time]
                    check = {**player_ref(players, actor_map, pid), "status": status, "immunity": immunity,
                             "recentCasts": [{"spellID": ability_id(e), "time": fmt_ms(int(e["timestamp"]) - start),
                                              "secondsBefore": round((hit_time - int(e["timestamp"])) / 1000, 2)} for e in uses[-4:]],
                             "cooldownNote": "施法历史供核对；日志不直接提供技能剩余冷却，不能断言没CD或误触取消。"}
                    strike["assignmentChecks"].append(check)
                    if reason:
                        # Explicit external-protection assignment attributes a missing
                        # protection to its provider, while an absent warrior remains
                        # the warrior's missed-soak record.
                        responsible = pid
                        if players[pid].get("specID") in {71, 72, 73}:
                            for key, pair in options["protectionPairs"].items():
                                pair_ids, errors = _match_names(pair, players)
                                if key.startswith("round" + str(index)) and len(pair_ids) == 2 and not errors and pair_ids[1] == pid:
                                    first_hits = buckets.get(1, [])
                                    first_time = min((int(e["timestamp"]) for e in first_hits), default=ts)
                                    pre = _immunity_state(raw, pid, first_time, [e for e in first_hits if e.get("targetID") == pid])
                                    pre_protection = any(a["spellID"] == 1022 for a in pre["auras"])
                                    current_protection = any(a["spellID"] == 1022 for a in immunity["auras"])
                                    if not pre_protection or not current_protection:
                                        responsible = pair_ids[0]
                                        reason = ("未在首段击飞前施加保护，影响 " if not pre_protection else "保护未覆盖 ") + str(players[pid].get("name")) + " 的分摊"
                                    check["status"] = reason
                                    check["responsiblePlayer"] = player_ref(players, actor_map, responsible)
                                    break
                        failure = failures.setdefault(responsible, {**player_ref(players, actor_map, responsible), "strikeIndices": [], "reasons": []})
                        failure["strikeIndices"].append(strike_index)
                        if reason not in failure["reasons"]:
                            failure["reasons"].append(reason)
            round_row["strikes"].append(strike)
        round_row["observedStrikeCount"] = len(groups)
        round_row["incomplete"] = {s["index"] for s in round_row["strikes"]} != {1, 2, 3}
        round_row["failures"] = list(failures.values())
        rounds.append(round_row)
    return {"enabled": True, "strategy": options["feastStrategy"], "rounds": rounds,
            "immunityUsage": _immunity_usage_review(fight, actor_map, players, raw, rounds) if options["feastStrategy"] == "immunity" else None,
            "evidenceNote": "每次盛宴分三段；首段全团，免疫打法只核对后两段。命中包含 immune、偏转及零伤害，按玩家去重；延迟超过200ms的同ID全团溅射单列，不算分摊参与者。每人每轮最多计一次失误；缺失整段记录不凭空归责。"}


def _stone_review(fight, actor_map, players, raw):
    start = int(fight["startTime"])
    tank_ids = {pid for pid, p in players.items() if p.get("role", "").endswith("tank")}
    tank_deaths = [int(e["timestamp"]) for e in raw.get("deaths", [])
                   if event_type(e) == "death" and e.get("targetID") in tank_ids]
    cutoff = min(tank_deaths) if tank_deaths else int(fight["endTime"]) + 1
    targeted = [e for e in _unique_events(raw.get("casts", [])) if ability_id(e) == 1289092 and event_type(e) == "cast"]
    casts = [e for e in _unique_events(raw.get("casts", [])) if ability_id(e) == 1288538 and event_type(e) == "cast"] or targeted
    bursts = group_nearby([e for e in raw.get("damage", []) if ability_id(e) == STONE_RAID_DAMAGE_ID and e.get("targetID") in players and int(e["timestamp"]) < cutoff], window_ms=250)
    rows = []
    used = set()
    for index, cast in enumerate(casts, 1):
        ts = int(cast["timestamp"])
        if ts >= cutoff:
            continue
        matched = [(i, group) for i, group in enumerate(bursts) if i not in used and abs(int(group[0]["timestamp"]) - ts) <= 1500]
        for i, _ in matched:
            used.add(i)
        damage = [e for _, group in matched for e in group]
        direct = [e for e in targeted if e.get("sourceID") == cast.get("sourceID") and abs(int(e["timestamp"]) - ts) <= 500 and e.get("targetID") in players]
        earlier = [e for e in targeted if e.get("sourceID") == cast.get("sourceID") and 0 <= ts - int(e["timestamp"]) <= 7500 and e.get("targetID") in players]
        target_evidence = "实际裂石击命中目标" if direct else "同组三连击最近接圈目标"
        prior = max(direct or earlier, key=lambda e: e["timestamp"]) if direct or earlier else None
        pid = prior.get("targetID") if prior else None
        if pid not in tank_ids:
            pid, tank_evidence = _tank_for_boss(raw, players, cast.get("sourceID"), ts - 1500)
            target_evidence = "读条时当前仇恨目标（接圈目标未直接确认）" if pid is not None else "接圈目标证据不足"
        rows.append({"index": index, "time": fmt_ms(ts - start), "timeMs": ts - start,
                     "tank": player_ref(players, actor_map, pid) if pid in tank_ids else None,
                     "targetIsTank": players.get(pid, {}).get("role", "").endswith("tank"),
                     "raidDamageCount": len(matched), "raidDamage": bool(matched),
                     "victims": [player_ref(players, actor_map, pid) for pid in sorted({e["targetID"] for e in damage})],
                     "totalDamage": sum(int(e.get("amount") or 0) for e in damage),
                     "evidence": target_evidence + ("；全团伤害由独立爆发伤害确认" if matched else "；未见全团爆发伤害")})
    for i, group in enumerate(bursts):
        if i not in used:
            ts = int(group[0]["timestamp"])
            if ts >= cutoff:
                continue
            rows.append({"index": None, "time": fmt_ms(ts - start), "timeMs": ts - start, "tank": None,
                         "targetIsTank": False, "raidDamageCount": 1, "raidDamage": True,
                         "victims": [player_ref(players, actor_map, pid) for pid in sorted({e["targetID"] for e in group})],
                         "totalDamage": sum(int(e.get("amount") or 0) for e in group), "evidence": "全团伤害已确认，缺少对应点名目标"})
    return {"enabled": True, "events": sorted(rows, key=lambda r: r["timeMs"]),
            "raidDamageCount": sum(r["raidDamageCount"] for r in rows),
            "tankDeathCutoffMs": cutoff - start if tank_deaths else None}


def _venom_death_stack(events, pid, timestamp):
    # Death removes the aura in the same log batch, sometimes a few ms first.
    trimmed = [e for e in events if not (e.get("targetID") == pid and event_type(e) == "removedebuff"
                                       and 0 <= timestamp - int(e["timestamp"]) <= 100)]
    return _venom_stack_at(trimmed, pid, timestamp)


def _death_reviews(fight, actor_map, players, raw, options):
    start = int(fight["startTime"])
    deaths = [e for e in _unique_events(raw.get("deaths", [])) if e.get("targetID") in players]
    venom = [e for e in raw.get("debuffs", []) if ability_id(e) == 1290336]
    all_rows = []
    for death in deaths:
        ts, pid = int(death["timestamp"]), death["targetID"]
        incoming = [e for e in raw.get("damage", []) if e.get("targetID") == pid and ts - 8000 <= int(e["timestamp"]) <= ts]
        killer = int(death.get("killingAbilityGameID") or 0)
        row = {**player_ref(players, actor_map, pid), "time": fmt_ms(ts - start), "timeMs": ts - start,
               "killingSpellID": killer, "killingSpell": spell_name(killer, GUIDE_SPELLS),
               "mechanicNote": DEATH_MECHANIC_NOTES.get(killer, ""), "avoidable": killer == 1306876,
               "venomStacks": _venom_death_stack(venom, pid, ts), "early": False,
               "precedingDamage": [{"time": fmt_ms(int(e["timestamp"]) - start), "spellID": ability_id(e),
                                    "spell": spell_name(ability_id(e), GUIDE_SPELLS), "source": actor_map.get(e.get("sourceID"), "未知"),
                                    "amount": int(e.get("amount") or 0), "absorbed": int(e.get("absorbed") or 0),
                                    "overkill": int(e.get("overkill") or 0), "hitType": e.get("hitType")} for e in incoming]}
        all_rows.append(row)
    gap_ms = int(options["earlyDeathGapSeconds"] * 1000)
    cutoff = None
    for i, row in enumerate(all_rows[:-1]):
        gap = all_rows[i + 1]["timeMs"] - row["timeMs"]
        if gap >= gap_ms:
            cutoff = i
            break
    if cutoff is None and len(all_rows) == 1 and int(fight["endTime"]) - start - all_rows[0]["timeMs"] >= gap_ms:
        cutoff = 0
    if cutoff is not None:
        boundary = all_rows[cutoff + 1]["timeMs"] if cutoff + 1 < len(all_rows) else int(fight["endTime"]) - start
        for row in all_rows[:cutoff + 1]:
            row["early"] = True
            row["gapToFollowingDeathsSeconds"] = round((boundary - row["timeMs"]) / 1000, 2)
    explosions = group_nearby([e for e in raw.get("damage", []) if ability_id(e) == 1290338 and e.get("targetID") in players], window_ms=250)
    burst_rows = []
    venom_rows = [r for r in all_rows if r["venomStacks"] > 0]
    for group in explosions:
        ts = int(group[0]["timestamp"]) - start
        candidates = [r for r in venom_rows if 0 < ts - r["timeMs"] <= 15000]
        burst_rows.append({"time": fmt_ms(ts), "timeMs": ts, "totalDamage": sum(int(e.get("amount") or 0) for e in group),
                           "victims": [player_ref(players, actor_map, pid) for pid in sorted({e["targetID"] for e in group})],
                           "nearbyVenomDeaths": [{"player": r["player"], "playerID": r["playerID"], "time": r["time"], "stacks": r["venomStacks"]} for r in candidates],
                           "causality": "时间上相邻；无法唯一确认每颗球来源，不作一对一因果归责"})
    return ({"enabled": True, "gapSeconds": options["earlyDeathGapSeconds"], "deaths": all_rows,
             "earlyDeaths": [r for r in all_rows if r["early"]], "evidenceNote": "将首次明显死亡间隔之前的死亡单列，提供全部死亡前8秒伤害；提前死亡是复盘线索，不等同于自动判责。"},
            {"enabled": int(fight.get("difficulty") or 0) == 5, "deaths": venom_rows,
             "expectedGlobuleCount": sum(r["venomStacks"] for r in venom_rows), "explosions": burst_rows,
             "evidenceNote": "带毒死亡层数对应机制预期额外球数，并非日志观测到的实体生成数量；球爆炸单独按实测全团伤害展示。"})

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

def _venom_rounds(fight, actor_map, players, raw, histories, globule_rounds):
    """Use the existing Corrosive Deluge pickup windows, including zero pickups."""
    history_by_id = {p["playerID"]: p["events"] for p in histories}
    damage = _unique_events(raw.get("damage", []))
    output = []
    for round_row in globule_rounds:
        begin, end = round_row["timeMs"], round_row["endTimeMs"]
        eaten = {p["playerID"]: p["count"] for p in round_row["eaten"]}
        abnormal_hits = Counter(e["targetID"] for e in damage
                                if e.get("targetID") in players and ability_id(e) in VENOM_ABNORMAL_DAMAGE
                                and begin <= int(e["timestamp"]) - fight["startTime"] < end
                                and event_type(e) == "damage" and e.get("hitType") != 10
                                and float(e.get("amount") or 0) + float(e.get("absorbed") or 0) > 0)
        rows = []
        for pid in players:
            gains = [e for e in history_by_id.get(pid, []) if begin <= e["timeMs"] < end and e["delta"] > 0]
            orb = sum(e["delta"] for e in gains if e["sourceID"] == 1289201)
            abnormal = sum(e["delta"] for e in gains if e["category"] == "abnormal")
            other = sum(e["delta"] for e in gains if e["sourceID"] != 1289201 and e["category"] != "abnormal")
            rows.append({**player_ref(players, actor_map, pid), "orbStacks": orb, "orbCount": eaten.get(pid, 0),
                         "abnormalHitCount": abnormal_hits[pid], "abnormalStacks": abnormal,
                         "otherStacks": other, "unknownStacks": sum(e["delta"] for e in gains if e["category"] == "unknown"),
                         "totalGains": orb + abnormal + other,
                         "aliveAtStart": _life_at(raw, pid, fight["startTime"] + begin),
                         "aliveAtEnd": _life_at(raw, pid, fight["startTime"] + end)})
        rows.sort(key=lambda p: (p["orbCount"], p["orbStacks"], p["playerID"]))
        output.append({"index": round_row["index"], "time": round_row["time"], "endTime": round_row["endTime"],
                       "players": rows, "zeroPickupCount": sum(p["orbCount"] == 0 for p in rows),
                       "hitCount": round_row["hitCount"]})
    return output


def analyze_twinfangs(fight, actor_map, players, raw):
    options = resolve_analysis_options(CONFIG_SCHEMA, raw.get("analysisOptions") or {})
    if not any(options[key] for key in REVIEW_KEYS):
        return {"enabled": False}
    debuffs, casts, damage, buffs, deaths = (
        raw["debuffs"], raw["casts"], raw["damage"], raw["friendlyBuffs"], raw["deaths"],
    )
    venom_events = [event for event in debuffs if int(ability_id(event) or 0) == 1290336]
    histories = []
    for player_id in (players if options["venomReviewEnabled"] or options["globulesReviewEnabled"] else []):
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
    for index, cast in enumerate(feast_casts if options["feastReviewEnabled"] else [], start=1):
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
    for index, cast in enumerate(deluges if options["globulesReviewEnabled"] or options["venomReviewEnabled"] else [], start=1):
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
                               "endTime": fmt_ms(end - fight["startTime"]), "endTimeMs": end - fight["startTime"], "participantCount": len(participants),
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
    wave_hits = _avoidable_board(
        fight, actor_map, players, damage, deaths, {1289994: "腐蚀洪流波浪"}
    ) if options["waveReviewEnabled"] else []
    mythic = int(fight.get("difficulty") or 0) == 5
    if mythic:
        # Heroic's one-ball-per-player allocation is not a Mythic assignment.
        feast_checks = []
        for row in globule_rounds:
            row["missed"] = []
            row["nonParticipants"] = []
            row["abnormal"] = []
            for person in row["eaten"]:
                person["abnormal"] = False
            row["evidenceNote"] = "史诗包含坦克洪流与带毒死亡额外球，只统计实测吃球，不套用每人一球归责。"
    early, venom_deaths = ({"enabled": False}, {"enabled": False})
    if options["earlyDeathReviewEnabled"] or (mythic and options["venomDeathReviewEnabled"]):
        early, venom_deaths = _death_reviews(fight, actor_map, players, raw, options)
    tank_globules = []
    if mythic and options["globulesReviewEnabled"]:
        for index, cast in enumerate(deluges, 1):
            ts = int(cast["timestamp"])
            cover = [e for e in casts if int(ability_id(e) or 0) == 1303378 and event_type(e) == "cast"
                     and ts <= int(e["timestamp"]) <= ts + 10000]
            tank_globules.append({"index": index, "time": fmt_ms(ts - fight["startTime"]),
                                  "target": player_ref(players, actor_map, cast.get("targetID")),
                                  "bulwarks": [{"actorID": e.get("sourceID"), "instance": e.get("sourceInstance", 1),
                                                "x": e.get("x"), "y": e.get("y"), "time": fmt_ms(int(e["timestamp"]) - fight["startTime"])} for e in cover]})
    venom_rounds = _venom_rounds(fight, actor_map, players, raw, histories, globule_rounds)
    return {
        "eternalVenom": {"players": histories if options["venomReviewEnabled"] else [], "feastChecks": feast_checks,
                         "abnormalGains": abnormal_gains if options["venomReviewEnabled"] else [],
                         "rounds": venom_rounds if options["venomReviewEnabled"] else []},
        "globules": {"rounds": globule_rounds if options["globulesReviewEnabled"] else [],
                     "venomRounds": venom_rounds if options["globulesReviewEnabled"] else []},
        "waveHits": {"spellID": 1289994, "players": wave_hits},
        "isMythic": mythic,
        "tankGlobules": {"enabled": mythic and options["globulesReviewEnabled"], "rounds": tank_globules},
        "feast": _feast_review(fight, actor_map, players, raw, options) if options["feastReviewEnabled"] else {"enabled": False},
        "brood": _brood_review(fight, actor_map, players, raw, options) if options["broodReviewEnabled"] else {"enabled": False},
        "stone": _stone_review(fight, actor_map, players, raw) if options["stoneReviewEnabled"] else {"enabled": False},
        "earlyDeaths": early if options["earlyDeathReviewEnabled"] else {"enabled": False},
        "venomDeaths": venom_deaths if options["venomDeathReviewEnabled"] else {"enabled": False},
    }

analyze_mechanics = analyze_twinfangs


def _mechanic_overview(rendered, options=None):
    options = resolve_analysis_options(CONFIG_SCHEMA, options or {})
    wave_hits = []
    for pull in rendered:
        if pull.get("shortPull"):
            continue
        mechanics = pull.get(BOSS_CONFIG["key"]) or {}
        for player_row in (mechanics.get("waveHits") or {}).get("players") or []:
            for event in player_row.get("events") or []:
                wave_hits.append(nightly_detail(
                    pull, event.get("time"),
                    f"{player_row.get('player') or '未知玩家'} 命中腐蚀洪流波浪",
                    player=player_row.get("player"), classColor=player_row.get("classColor"),
                    spellID=1289994,
                ))
    result = {
        "title": "整夜机制统计",
        "subtitle": "按所有 Pull 汇总实际命中事件；单场毒液与吃球明细保持原样。",
        "metrics": [{
            "key": "waveHits", "label": "命中波浪", "value": len(wave_hits), "unit": "次",
            "tone": "warning", "description": "腐蚀洪流波浪 1289994 对玩家造成伤害的总人次。",
            "players": nightly_player_totals(wave_hits), "events": wave_hits,
        }],
    }
    if not options["waveReviewEnabled"]:
        result["metrics"] = []
    specs = [
        ("broodReviewEnabled", "broodLeaks", "脏腑爆裂首漏断", "每场仅统计首次成功施法；按责任槽位和已配置玩家汇总，未配置时保留左右侧及组内序号。"),
        ("feastReviewEnabled", "feastFailures", "免疫分摊失误", "仅免疫打法且四人名单有效时计数，每人每轮最多一次；保护责任按配置施法者归属。"),
        ("stoneReviewEnabled", "stoneRaidDamage", "裂石击全团伤害", "按爆发次数统计，附接圈坦克；从本场首次倒坦起停止统计，不把非坦克接怪当作接圈责任。"),
        ("earlyDeathReviewEnabled", "earlyDeaths", "提前死亡", "首批明显早于后续死亡的玩家，按配置间隔筛选；完整死亡伤害仍保留。"),
    ]
    for option, key, label, description in specs:
        if not options[option] or (key == "feastFailures" and options["feastStrategy"] != "immunity"):
            continue
        details, value = [], 0
        for pull in rendered:
            if pull.get("shortPull"):
                continue
            data = pull.get(BOSS_CONFIG["key"]) or {}
            if key == "broodLeaks":
                for row in (data.get("brood") or {}).get("events", []):
                    value += row["successfulCasts"]
                    if not row["successfulCasts"]:
                        continue
                    responsible = row.get("responsiblePlayers") or []
                    slot = row.get("responsibilitySlot") or "点位未确认"
                    display = responsible[0]["player"] if len(responsible) == 1 else slot
                    owner = responsible[0] if len(responsible) == 1 else {}
                    details.append(nightly_detail(pull, row["time"], (row.get("leakLabel") or "点位未确认的蛇头漏断脏腑爆裂") + "；责任：" + display,
                                                  player=display, classColor=owner.get("classColor"), playerID=owner.get("playerID"), responsibilitySlot=slot, responsiblePlayers=responsible,
                                                  spellID=BROOD_CAST_ID, position=row.get("position"), groupOrder=row.get("groupOrder"),
                                                  groupLabel=row.get("groupLabel"), assignmentNote=row.get("assignmentNote"),
                                                  count=row["successfulCasts"]))
            elif key == "feastFailures":
                for row in (data.get("feast") or {}).get("rounds", []):
                    for p in row["failures"]:
                        value += 1
                        details.append(nightly_detail(pull, row["time"], p["player"] + "：第" + str(row["index"]) + "轮，第" + "、".join(map(str, sorted(set(p["strikeIndices"])))) + "段，" + "；".join(p["reasons"]), **p, round=row["index"], spellID=1290516))
            elif key == "stoneRaidDamage":
                for row in (data.get("stone") or {}).get("events", []):
                    if row["raidDamage"]:
                        value += row["raidDamageCount"]
                        tank = row.get("tank") or {}
                        details.append(nightly_detail(pull, row["time"], "裂石击产生全团伤害；当前处理坦克：" + str(tank.get("player") or "未确认") + "；坦克ID：" + str(tank.get("playerID") or "未确认"), **tank, tankID=tank.get("playerID"), spellID=STONE_RAID_DAMAGE_ID))
            else:
                section = data.get(key) or {}
                if not section.get("enabled"):
                    continue
                for row in section.get("deaths" if key == "venomDeaths" else "earlyDeaths", []):
                    value += 1
                    details.append(nightly_detail(pull, row["time"], f"{row['player']}：{row['killingSpell']} 致死，携带 {row['venomStacks']} 层永恒毒液" + ("；" + row["mechanicNote"] if row.get("mechanicNote") else ""),
                                                  player=row["player"], playerID=row["playerID"], classColor=row.get("classColor"), spellID=row["killingSpellID"], venomStacks=row["venomStacks"]))
        result["metrics"].append({"key": key, "label": label, "value": value, "unit": "次", "tone": "warning",
                                   "description": description, "players": nightly_player_totals([r for r in details if r.get("player")]), "events": details})
        if key == "broodLeaks":
            result["metrics"][-1]["summaryViews"] = [
                {"key": "slots", "label": "责任位置", "rows": nightly_player_totals([{**r, "player": r["responsibilitySlot"], "classColor": None} for r in details])},
                {"key": "players", "label": "归责玩家", "rows": nightly_player_totals(details)}]
    result["subtitle"] = "按已选项目汇总；漏断、分摊、全团伤害与提前死亡均可展开查看证据。"
    return result


def build_aggregated_json(report_ids, options=None):
    options = resolve_analysis_options(CONFIG_SCHEMA, options or {})
    config = deepcopy(BOSS_CONFIG)
    config["fetchEventResources"] = False
    config["fetchKeys"] = {"friendlyCasts", "deaths", "combatants"}
    if options["venomReviewEnabled"] or options["feastReviewEnabled"]:
        config["fetchKeys"].update({"debuffs", "casts"})
    if options["venomReviewEnabled"] or options["globulesReviewEnabled"] or options["waveReviewEnabled"]:
        config["fetchKeys"].add("damage")
    if options["globulesReviewEnabled"]:
        config["fetchKeys"].update({"casts", "friendlyBuffs"})
    if options["feastReviewEnabled"]:
        config["fetchKeys"].update({"damage", "friendlyBuffs"})
    if options["broodReviewEnabled"] or options["stoneReviewEnabled"]:
        config["fetchKeys"].update({"casts", "damage"})
    if options["earlyDeathReviewEnabled"] or options["venomDeathReviewEnabled"]:
        config["fetchKeys"].update({"damage", "debuffs"})
    config["fetchCastResources"] = options["broodReviewEnabled"] or options["globulesReviewEnabled"]
    config["trackedActorGameIDs"] = BOSS_NPC_IDS | {BROOD_NPC_ID}
    config["trackedActorEventFilters"] = []
    if options["broodReviewEnabled"]:
        config["trackedActorEventFilters"].append("source.id = 270898 or target.id = 270898")
        config["fetchInterrupts"] = True
        config["fetchKeys"].add("interrupts")
    if any(options[k] for k in ("broodReviewEnabled", "feastReviewEnabled", "earlyDeathReviewEnabled", "venomDeathReviewEnabled")):
        config["trackedActorEventFilters"].append('type = "resurrect"')
    # With no custom filter the generic runtime would fetch every tracked NPC.
    if not config["trackedActorEventFilters"]:
        config["trackedActorGameIDs"] = set()
    tab_enabled = {"survival": True, "venom": options["venomReviewEnabled"] or options["feastReviewEnabled"],
                   "globules": options["globulesReviewEnabled"], "feast": options["feastReviewEnabled"], "brood": options["broodReviewEnabled"],
                   "venomDeaths": options["venomDeathReviewEnabled"], "stone": options["stoneReviewEnabled"], "earlyDeaths": options["earlyDeathReviewEnabled"]}
    config["tabs"] = [row for row in config["tabs"] if tab_enabled[row[0]]]
    config["skippedAnalyses"] = [field["label"] for field in CONFIG_SCHEMA if field["type"] == "boolean" and not options[field["key"]]]
    result = _build(config, analyze_mechanics, report_ids, options)
    for pull in result.get("data", {}).get("page1_wipeAnalysis", []):
        if not pull.get("isKill") and pull.get("durationMs", 30000) < 30000:
            pull.update(shortPull=True, fightPhase="误开怪 / ADD处理", wipePhase="误开怪 / ADD处理",
                        wipeReason="战斗不足30秒，按误开怪/ADD处理保留明细，不计整夜机制统计")
    result["data"]["mechanicOverview"] = _mechanic_overview(
        result.get("data", {}).get("page1_wipeAnalysis") or [], options
    )
    return result


def analyze(report_ids, output_path=None, catalog_entry=None, options=None, progress_callback=None):
    return write_json_result(
        build_aggregated_json(report_ids, options), output_path, catalog_entry=catalog_entry
    )
