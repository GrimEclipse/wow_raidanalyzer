"""Holy Paladin single-Fight comparison.

The plugin consumes normalized WCL bundles.  It never fetches data itself, so
the same facts can be rendered online, cached as JSON, or embedded in a fully
standalone HTML snapshot.
"""

from __future__ import annotations

from collections import Counter, defaultdict


SPELLS = {
    200025: ("美德道标", "美"),
    20473: ("神圣震击", "震"),
    19750: ("圣光闪现", "闪"),
    82326: ("圣光术", "光"),
    156322: ("永恒之火", "火"),
    85222: ("黎明圣光", "黎"),
    275773: ("审判", "审"),
    375576: ("圣洁鸣钟", "钟"),
    31884: ("复仇之怒", "翅"),
    1241413: ("愤怒之锤", "锤"),
    498: ("圣佑术", "佑"),
    31821: ("光环掌握", "环"),
    633: ("圣疗术", "疗"),
    6940: ("牺牲祝福", "牺"),
    4987: ("清洁术", "驱"),
    190784: ("神圣马驹", "马"),
    642: ("圣盾术", "盾"),
    1291894: ("饰品", "饰"),
    220637: ("审判（圣能）", "审"),
    88852: ("圣光道标（圣能）", "标"),
    138248: ("额外圣能", "能"),
}

BUFFS = [
    (54149, "圣光灌注", "personal"),
    (31884, "复仇之怒", "personal"),
    (223819, "神圣意志", "personal"),
    (431381, "曙光", "source"),
]


def _ability_icon(bundle: dict, ability_id: int) -> str:
    icons = bundle.get("abilityIcons") or {}
    return str(icons.get(ability_id) or icons.get(str(ability_id)) or "")


def _combatant_stats(bundle: dict) -> dict:
    info = bundle.get("combatantInfo") or {}
    equipped_levels = [
        int(row.get("itemLevel") or 0)
        for row in info.get("gear") or []
        if int(row.get("id") or 0) > 0 and int(row.get("itemLevel") or 0) > 1
    ]
    item_level = round(sum(equipped_levels) / len(equipped_levels), 1) if equipped_levels else None
    return {
        "itemLevel": item_level,
        "criticalStrike": int(info.get("critSpell") or info.get("critMelee") or 0),
        "haste": int(info.get("hasteSpell") or info.get("hasteMelee") or 0),
        "mastery": int(info.get("mastery") or 0),
        "versatility": int(info.get("versatilityHealingDone") or info.get("versatilityDamageDone") or 0),
    }


def _aura_intervals(events: list[dict], start: int, end: int) -> list[tuple[int, int]]:
    intervals = []
    active_at = None
    for row in events:
        event_type = row.get("type")
        if event_type == "applybuff" and active_at is None:
            active_at = max(start, int(row["timestamp"]))
        elif event_type == "removebuff" and active_at is not None:
            intervals.append((active_at, min(end, int(row["timestamp"]))))
            active_at = None
    if active_at is not None:
        intervals.append((active_at, end))
    return intervals


def _successful_casts(bundle: dict) -> list[dict]:
    return sorted(
        [row for row in bundle.get("casts") or [] if row.get("type") == "cast" and not row.get("fake")],
        key=lambda row: row["timestamp"],
    )


def _personal_buff_events(bundle: dict, ability_id: int) -> list[dict]:
    actor_id = int((bundle.get("actor") or {}).get("id") or 0)
    return sorted(
        [
            row for row in bundle.get("buffs") or []
            if int(row.get("abilityGameID") or 0) == ability_id
            and int(row.get("targetID") or actor_id) == actor_id
        ],
        key=lambda row: row["timestamp"],
    )


def _source_buff_events(bundle: dict, ability_id: int) -> list[dict]:
    actor_id = int((bundle.get("actor") or {}).get("id") or 0)
    return sorted(
        [
            row for row in bundle.get("buffs") or []
            if int(row.get("abilityGameID") or 0) == ability_id
            and int(row.get("sourceID") or actor_id) == actor_id
        ],
        key=lambda row: row["timestamp"],
    )


def _aura_uptime(events: list[dict], start: int, end: int) -> int:
    active_at = None
    total = 0
    for row in events:
        event_type = row.get("type")
        if event_type == "applybuff" and active_at is None:
            active_at = max(start, int(row["timestamp"]))
        elif event_type == "removebuff" and active_at is not None:
            total += max(0, min(end, int(row["timestamp"])) - active_at)
            active_at = None
    if active_at is not None:
        total += max(0, end - active_at)
    return total


def _source_aura_uptime(events: list[dict], start: int, end: int) -> int:
    by_target = defaultdict(list)
    for row in events:
        by_target[int(row.get("targetID") or 0)].append(row)
    intervals = []
    for rows in by_target.values():
        active_at = None
        for row in rows:
            if row.get("type") == "applybuff" and active_at is None:
                active_at = max(start, int(row["timestamp"]))
            elif row.get("type") == "removebuff" and active_at is not None:
                intervals.append((active_at, min(end, int(row["timestamp"]))))
                active_at = None
        if active_at is not None:
            intervals.append((active_at, end))
    return _union_duration(intervals)


def _infusion_state(events: list[dict], timestamp: int) -> int:
    stacks = 0
    for row in events:
        if int(row["timestamp"]) >= timestamp:
            break
        event_type = row.get("type")
        if event_type == "applybuff":
            stacks = 2
        elif event_type == "applybuffstack":
            stacks = int(row.get("stack") or 2)
        elif event_type == "removebuffstack":
            stacks = int(row.get("stack") or 1)
        elif event_type == "removebuff":
            stacks = 0
    return stacks


def _holy_power_tracker(bundle: dict, casts: list[dict]):
    resources = sorted(
        [row for row in bundle.get("resources") or [] if row.get("resourceChangeType") == 9],
        key=lambda row: row["timestamp"],
    )
    timeline = []
    sequence = 0
    for row in resources:
        timeline.append((int(row["timestamp"]), 0, sequence, "gain", row))
        sequence += 1
    for row in casts:
        cost_row = next(
            (value for value in row.get("classResources") or [] if value.get("type") == 9 and value.get("cost", 0) > 0),
            None,
        )
        if cost_row:
            timeline.append((int(row["timestamp"]), 1, sequence, "spend", row))
            sequence += 1
    timeline.sort(key=lambda item: item[:3])

    def at(timestamp: int) -> int:
        state = 0
        for event_time, _, _, event_type, row in timeline:
            if event_time >= timestamp:
                break
            if event_type == "gain":
                state = min(
                    int(row.get("maxResourceAmount") or 5),
                    state + int(row.get("resourceChange") or 0) - int(row.get("waste") or 0),
                )
            else:
                cost = next(value for value in row["classResources"] if value.get("type") == 9 and value.get("cost", 0) > 0)
                state = max(0, int(cost.get("amount", state)) - int(cost.get("cost") or 0))
        return state

    return at, resources


def _union_duration(intervals: list[tuple[int, int]]) -> int:
    total = 0
    current = None
    for start, end in sorted(intervals):
        if current is None:
            current = [start, end]
        elif start <= current[1]:
            current[1] = max(current[1], end)
        else:
            total += current[1] - current[0]
            current = [start, end]
    if current:
        total += current[1] - current[0]
    return total


def _spell_payload(bundle: dict, row: dict, window_start: int, infusion_events: list[dict], holy_power_at) -> dict:
    ability_id = int(row.get("abilityGameID") or 0)
    name, glyph = SPELLS.get(ability_id, (str(row.get("abilityName") or ability_id), "·"))
    payload = {
        "abilityId": ability_id,
        "name": name,
        "glyph": glyph,
        "icon": _ability_icon(bundle, ability_id),
        "offsetMs": int(row["timestamp"]) - window_start,
    }
    if ability_id in {19750, 82326, 275773, 375576}:
        payload["infusionStacks"] = _infusion_state(infusion_events, int(row["timestamp"]))
    if ability_id == 375576:
        payload["holyPower"] = holy_power_at(int(row["timestamp"]))
    return payload


def _player_summary(bundle: dict, window_ms: int) -> dict:
    fight = bundle["fight"]
    start, end = int(fight["startTime"]), int(fight["endTime"])
    duration_ms = end - start
    casts = _successful_casts(bundle)
    infusion_events = _personal_buff_events(bundle, 54149)
    holy_power_at, resources = _holy_power_tracker(bundle, casts)
    cast_counts = Counter(int(row.get("abilityGameID") or 0) for row in casts)

    virtues = [row for row in casts if int(row.get("abilityGameID") or 0) == 200025]
    windows = []
    window_counts = Counter()
    for index, virtue in enumerate(virtues, 1):
        window_start = int(virtue["timestamp"])
        window_end = min(end, window_start + window_ms)
        rows = [
            row for row in casts
            if window_start < int(row["timestamp"]) <= window_end
            and int(row.get("abilityGameID") or 0) in SPELLS
            and int(row.get("abilityGameID") or 0) != 200025
        ]
        window_counts.update(int(row["abilityGameID"]) for row in rows)
        windows.append({
            "index": index,
            "startMs": window_start - start,
            "durationMs": window_end - window_start,
            "sequence": [_spell_payload(bundle, row, window_start, infusion_events, holy_power_at) for row in rows],
        })

    buff_coverage = []
    for ability_id, label, mode in BUFFS:
        events = _personal_buff_events(bundle, ability_id) if mode == "personal" else _source_buff_events(bundle, ability_id)
        uptime = _aura_uptime(events, start, end) if mode == "personal" else _source_aura_uptime(events, start, end)
        event_counts = Counter(row.get("type") for row in events)
        buff_coverage.append({
            "abilityId": ability_id,
            "name": label,
            "icon": _ability_icon(bundle, ability_id),
            "uptimeMs": uptime,
            "uptimePercent": round(uptime / duration_ms * 100, 2) if duration_ms else 0,
            "applications": event_counts["applybuff"] + event_counts["applybuffstack"],
        })
    virtue_uptime = _union_duration([(int(row["timestamp"]), min(end, int(row["timestamp"]) + window_ms)) for row in virtues])
    buff_coverage.insert(1, {
        "abilityId": 200025,
        "name": "美德道标",
        "icon": _ability_icon(bundle, 200025),
        "uptimeMs": virtue_uptime,
        "uptimePercent": round(virtue_uptime / duration_ms * 100, 2) if duration_ms else 0,
        "applications": len(virtues),
    })

    infusion_types = Counter(row.get("type") for row in infusion_events)
    infusion_charges = infusion_types["applybuff"] * 2 + infusion_types["applybuffstack"]
    consumption = Counter()
    unmatched = 0
    for aura in infusion_events:
        if aura.get("type") not in {"removebuff", "removebuffstack"}:
            continue
        candidates = [row for row in casts if abs(int(row["timestamp"]) - int(aura["timestamp"])) <= 150]
        if not candidates:
            unmatched += 1
            continue
        nearest = min(candidates, key=lambda row: abs(int(row["timestamp"]) - int(aura["timestamp"])))
        consumption[int(nearest.get("abilityGameID") or 0)] += 1

    nominal = sum(int(row.get("resourceChange") or 0) for row in resources)
    waste = sum(int(row.get("waste") or 0) for row in resources)
    spend_by_ability = defaultdict(lambda: {"casts": 0, "amount": 0})
    for row in casts:
        power = next((value for value in row.get("classResources") or [] if value.get("type") == 9 and value.get("cost", 0) > 0), None)
        if power:
            item = spend_by_ability[int(row.get("abilityGameID") or 0)]
            item["casts"] += 1
            item["amount"] += int(power.get("cost") or 0)
    spent = sum(item["amount"] for item in spend_by_ability.values())

    gain_sources = defaultdict(lambda: {"events": 0, "actual": 0, "waste": 0})
    ability_names = bundle.get("abilityNames") or {}
    for row in resources:
        ability_id = int(row.get("abilityGameID") or 0)
        item = gain_sources[ability_id]
        item["events"] += 1
        item["actual"] += int(row.get("resourceChange") or 0) - int(row.get("waste") or 0)
        item["waste"] += int(row.get("waste") or 0)

    tolls = []
    for row in casts:
        if int(row.get("abilityGameID") or 0) != 375576:
            continue
        timestamp = int(row["timestamp"])
        triggered = [
            event for event in resources
            if int(event.get("abilityGameID") or 0) == 20473 and 0 < int(event["timestamp"]) - timestamp <= 600
        ]
        tolls.append({
            "timeMs": timestamp - start,
            "holyPower": holy_power_at(timestamp),
            "infusionStacks": _infusion_state(infusion_events, timestamp),
            "generated": sum(int(event.get("resourceChange") or 0) - int(event.get("waste") or 0) for event in triggered),
            "waste": sum(int(event.get("waste") or 0) for event in triggered),
        })

    def spell_stat(ability_id: int) -> dict:
        count = cast_counts[ability_id]
        name, glyph = SPELLS[ability_id]
        return {
            "abilityId": ability_id,
            "name": name,
            "glyph": glyph,
            "icon": _ability_icon(bundle, ability_id),
            "count": count,
            "perMinute": round(count / duration_ms * 60000, 2) if duration_ms else 0,
            "windowCount": window_counts[ability_id],
            "perWindow": round(window_counts[ability_id] / len(windows), 2) if windows else 0,
        }

    virtue_intervals = [(int(row["timestamp"]), min(end, int(row["timestamp"]) + window_ms)) for row in virtues]

    def in_virtue(timestamp: int) -> bool:
        return any(left <= timestamp <= right for left, right in virtue_intervals)

    def key_skill(ability_id: int, buff_id: int | None = None) -> dict:
        name, glyph = SPELLS[ability_id]
        uses = [row for row in casts if int(row.get("abilityGameID") or 0) == ability_id]
        intervals = _aura_intervals(_personal_buff_events(bundle, buff_id), start, end) if buff_id else []
        uptime = _union_duration(intervals)
        return {
            "abilityId": ability_id,
            "name": name,
            "glyph": glyph,
            "icon": _ability_icon(bundle, ability_id),
            "count": len(uses),
            "windowCount": sum(1 for row in uses if in_virtue(int(row["timestamp"]))),
            "timesMs": [int(row["timestamp"]) - start for row in uses],
            "uptimeMs": uptime,
            "uptimePercent": round(uptime / duration_ms * 100, 2) if duration_ms else 0,
        }

    begin_casts = sorted(
        [row for row in bundle.get("casts") or [] if row.get("type") == "begincast" and not row.get("fake")],
        key=lambda row: row["timestamp"],
    )
    successful_by_ability = defaultdict(list)
    for row in casts:
        successful_by_ability[int(row.get("abilityGameID") or 0)].append(row)
    matched = defaultdict(set)
    unfinished = []
    for begin in begin_casts:
        ability_id = int(begin.get("abilityGameID") or 0)
        begin_time = int(begin["timestamp"])
        match_index = next(
            (
                index for index, row in enumerate(successful_by_ability[ability_id])
                if index not in matched[ability_id]
                and begin_time <= int(row["timestamp"]) <= begin_time + 5000
            ),
            None,
        )
        if match_index is not None:
            matched[ability_id].add(match_index)
            continue
        name, glyph = SPELLS.get(ability_id, (str(begin.get("abilityName") or ability_id), "·"))
        unfinished.append({
            "timeMs": begin_time - start,
            "abilityId": ability_id,
            "name": name,
            "glyph": glyph,
            "icon": _ability_icon(bundle, ability_id),
        })

    idle_gaps = []
    for previous, current in zip(casts, casts[1:]):
        gap = int(current["timestamp"]) - int(previous["timestamp"])
        if 2500 < gap <= 15000:
            idle = max(0, gap - 1500)
            idle_gaps.append({
                "startMs": int(previous["timestamp"]) - start,
                "endMs": int(current["timestamp"]) - start,
                "gapMs": gap,
                "idleMs": idle,
            })

    toll_skill = key_skill(375576)
    toll_skill["uses"] = tolls
    toll_skill["generated"] = sum(row["generated"] for row in tolls)
    toll_skill["waste"] = sum(row["waste"] for row in tolls)
    key_skills = {
        "divineToll": toll_skill,
        "avengingWrath": key_skill(31884, 31884),
        "auraMastery": key_skill(31821, 31821),
    }

    identity = bundle.get("identity") or {}
    return {
        "identity": identity,
        "durationMs": duration_ms,
        "combatantStats": _combatant_stats(bundle),
        "casts": [spell_stat(ability_id) for ability_id in (200025, 20473, 19750, 82326, 156322, 85222, 275773, 375576)],
        "buffCoverage": buff_coverage,
        "resourceLedger": {
            "nominalGained": nominal,
            "actualGained": nominal - waste,
            "spent": spent,
            "waste": waste,
            "wastePerMinute": round(waste / duration_ms * 60000, 2) if duration_ms else 0,
            "gainSources": [
                {
                    "abilityId": ability_id,
                    "name": SPELLS.get(ability_id, (ability_names.get(str(ability_id)) or ability_names.get(ability_id) or str(ability_id), "·"))[0],
                    "icon": _ability_icon(bundle, ability_id),
                    **values,
                }
                for ability_id, values in sorted(gain_sources.items(), key=lambda item: -item[1]["events"])
            ],
        },
        "infusion": {
            "procEvents": infusion_types["applybuff"] + infusion_types["applybuffstack"],
            "charges": infusion_charges,
            "consumed": sum(consumption.values()),
            "expiredOrUnmatched": unmatched,
            "destinations": [
                {"abilityId": ability_id, "name": SPELLS.get(ability_id, (ability_names.get(str(ability_id)) or str(ability_id), "·"))[0], "icon": _ability_icon(bundle, ability_id), "count": count}
                for ability_id, count in consumption.most_common()
            ],
        },
        "windows": windows,
        "windowAggregate": [spell_stat(ability_id) for ability_id, _ in window_counts.most_common() if ability_id in SPELLS],
        "divineTolls": tolls,
        "keySkills": key_skills,
        "castContinuity": {
            "unfinishedCount": len(unfinished),
            "unfinished": unfinished,
            "idleGapCount": len(idle_gaps),
            "idleMs": sum(row["idleMs"] for row in idle_gaps),
            "lostGcdEstimate": sum(row["idleMs"] for row in idle_gaps) // 1500,
            "largestGaps": sorted(idle_gaps, key=lambda row: -row["idleMs"])[:8],
        },
    }


def analyze_comparison(primary: dict, benchmark: dict, options: dict | None = None) -> dict:
    options = options or {}
    window_ms = int(options.get("virtueWindowMs") or 9000)
    primary_summary = _player_summary(primary, window_ms)
    benchmark_summary = _player_summary(benchmark, window_ms)
    p = primary_summary
    b = benchmark_summary

    def cast(summary: dict, ability_id: int) -> dict:
        return next(row for row in summary["casts"] if row["abilityId"] == ability_id)

    judgment_gap = cast(p, 275773)["count"] - cast(b, 275773)["count"]
    flash_gap = cast(b, 19750)["windowCount"] - cast(p, 19750)["windowCount"]
    insights = [
        f"对标玩家在美德窗口内多完成 {max(0, flash_gap)} 次圣光闪现；主玩家则多按了 {max(0, cast(p, 275773)['windowCount'] - cast(b, 275773)['windowCount'])} 次审判。",
        f"主玩家总圣能溢出 {p['resourceLedger']['waste']}，对标玩家 {b['resourceLedger']['waste']}；每分钟分别为 {p['resourceLedger']['wastePerMinute']} 与 {b['resourceLedger']['wastePerMinute']}。",
        f"两边灌注可用层数为 {p['infusion']['charges']} 比 {b['infusion']['charges']}，审判总次数差为 {judgment_gap:+d}；差距主要来自灌注去向和填充优先级，而不是简单的触发次数。",
    ]
    return {
        "schemaVersion": 1,
        "kind": "single-fight-spec-comparison",
        "supportStatus": "implemented",
        "identity": {"class": "Paladin", "spec": "Holy", "specName": "神圣圣骑士"},
        "methodology": {
            "windowName": "美德道标",
            "windowMs": window_ms,
            "successfulCastsOnly": True,
            "resourceType": 9,
            "notes": ["读条开始 begincast 不计入成功施法。", "Buff 层数按 apply/remove/stack 事件重放。", "圣能按收益、浪费和实际消耗形成总账。"],
        },
        "players": {"primary": primary_summary, "benchmark": benchmark_summary},
        "insights": insights,
    }
