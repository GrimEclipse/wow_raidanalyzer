"""Evidence-first analyzer for Venomancer Vashnik."""

from __future__ import annotations

from analyzer_core.court_rules import validate_court_profile
from boss_plugins.venomous_abyss.runtime import analyze_boss, build_aggregated_json as _build
from boss_plugins.venomous_abyss.shared import (
    ability_id,
    avoidable_board as _avoidable_board,
    completed_casts as _completed_casts,
    event_type,
    events_between as _events_between,
    fmt_ms,
    load_confirmed_spell_names,
    player_ref,
    spell_name,
)

GUIDE_SPELLS = load_confirmed_spell_names()

BOSS_CONFIG = {
    "key": "vashnik",
    "encounterIDs": {3455},
    "name": "万毒邪祟者瓦什尼克",
    "arena": "assets/raids/venomous_abyss/03-vashnik.png",
    "spellNames": GUIDE_SPELLS,
    "tabs": [
        ["survival", "全场存活情况"],
        ["avoidable", "可规避机制"],
        ["infection", "适应性感染"],
    ],
    "mechanicVersion": "vashnik-progression-2026-08-28",
    "features": {"survival": True, "fieldReplay": False},
}

COURT_PROFILE = {
    "bossKey": "vashnik",
    "phaseModel": "fixed_timeline",
    "phaseRule": "只按起战后的固定事件轴和 Imbibe/Infusion Aura 切段；不得用血量提前结束阶段。",
    "rules": [
        {
            "key": "plague_wave_assignment", "label": "瘟疫泡沫波浪未命中指定目标", "mode": "assignment",
            "spellIDs": [1281908, 1281910, 1282078, 1295796, 1295798],
            "assignmentKey": "plagueWaveTargets",
            "requiredEvidence": ["Plague Froth remove timestamp", "player position near remove", "wave direction/facing", "assigned target position", "Plague Wave hit set"],
            "countOption": "plagueWaveAssignmentCountEnabled", "defaultCountEnabled": False, "severityUnits": 1,
        },
        {
            "key": "hardened_tumor_burst", "label": "硬化肿瘤未正确解除", "mode": "review",
            "spellIDs": [1304437, 1304459, 1295798],
            "requiredEvidence": ["tumor spawn", "Hardened Tumor aura", "wave intersection", "Tumor Burst"],
            "countOption": "hardenedTumorCountEnabled", "defaultCountEnabled": False, "severityUnits": 1,
        },
        {
            "key": "avoidable_plague_wave_hit", "label": "误吃瘟疫波浪", "mode": "review",
            "spellIDs": [1295798], "requiredEvidence": ["wave source", "wave direction", "damage target"],
            "countOption": "avoidablePlagueWaveCountEnabled", "defaultCountEnabled": False, "severityUnits": 1,
        },
    ],
}
validate_court_profile(COURT_PROFILE)

def analyze_vashnik(fight, actor_map, players, raw):
    avoidable = _avoidable_board(fight, actor_map, players, raw["damage"], raw["deaths"], {
        1295798: spell_name(1295798),
        1286737: spell_name(1286737),
    })
    avoidable_summary = [
        {"spellID": spell_id, "spellName": spell_name(spell_id),
         "hitCount": sum(row["hitCount"] for row in avoidable if row["spellID"] == spell_id),
         "playerCount": sum(1 for row in avoidable if row["spellID"] == spell_id)}
        for spell_id in (1295798, 1286737)
    ]
    infection_casts = sorted(_completed_casts(raw["casts"], 1282114), key=lambda event: event["timestamp"])
    rounds = []
    for index, cast in enumerate(infection_casts, start=1):
        start = int(cast["timestamp"])
        end = int(infection_casts[index]["timestamp"]) if index < len(infection_casts) else int(fight["endTime"])
        debuff_applies = [event for event in raw["debuffs"] if int(ability_id(event) or 0) in {1294994, 1295173, 1295224}
                          and event_type(event) == "applydebuff" and start <= int(event["timestamp"]) < end]
        soaker_hits = _events_between(raw["damage"], start, end, {1282117})
        soakers = sorted({event.get("targetID") for event in soaker_hits if event.get("targetID") in players})
        rounds.append({
            "index": index,
            "timeMs": start - fight["startTime"],
            "time": fmt_ms(start - fight["startTime"]),
            "endTime": fmt_ms(end - fight["startTime"]),
            "infectionTargets": [{
                **player_ref(players, actor_map, event.get("targetID")),
                "infectionID": int(ability_id(event)),
                "infection": spell_name(int(ability_id(event))),
            } for event in debuff_applies],
            "soakers": [player_ref(players, actor_map, player_id) for player_id in soakers],
            "soakerCount": len(soakers),
        })
    return {"avoidable": {"players": avoidable, "summary": avoidable_summary}, "adaptiveInfection": {"rounds": rounds}}

analyze_mechanics = analyze_vashnik


def build_aggregated_json(report_ids, options=None):
    return _build(BOSS_CONFIG, analyze_mechanics, report_ids, options)


def analyze(report_ids, output_path=None, catalog_entry=None, options=None, progress_callback=None):
    return analyze_boss(
        BOSS_CONFIG, analyze_mechanics, report_ids, output_path, catalog_entry, options
    )
