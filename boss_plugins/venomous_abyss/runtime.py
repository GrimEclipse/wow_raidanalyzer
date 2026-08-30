"""Shared WCL orchestration for Venomous Abyss Boss modules.

This module owns transport and output contracts only. Spell IDs, mechanic
windows, and Boss-specific verdicts belong in the individual Boss module.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from analyzer_core.analysis_scope import filter_fights
from analyzer_core.concurrency import run_parallel_indexed
from analyzer_core.progress import emit_progress
from analyzer_core.wcl_api import WclClient
from boss_plugins.common import write_json_result
from boss_plugins.venomous_abyss.shared import (
    build_player_catalog,
    build_survival_timeline,
    compact_actor_position_events,
    difficulty_fields,
    fmt_ms,
    resolve_boss_actor_id,
)


CN_TZ = timezone(timedelta(hours=8))


def progress(config, message, percent=None):
    boss_key = config["key"]
    print(f"[{boss_key}] {message}", flush=True)
    emit_progress(message, percent=percent, stage="analyze")


def fetch_payload(client, report_id, fight, config, boss_id=None):
    payload = {
        "casts": client.events(report_id, "Casts", fight, hostility_type="Enemies"),
        "friendlyCasts": client.events(report_id, "Casts", fight, hostility_type="Friendlies"),
        "damage": client.events(report_id, "DamageTaken", fight, include_resources=True),
        "debuffs": client.events(report_id, "Debuffs", fight, include_resources=True),
        "enemyBuffs": client.events(report_id, "Buffs", fight, hostility_type="Enemies"),
        "friendlyBuffs": client.events(report_id, "Buffs", fight, hostility_type="Friendlies"),
        "deaths": client.events(report_id, "Deaths", fight),
        "combatants": client.events(report_id, "CombatantInfo", fight),
        "resources": [],
        "bossPositionEvents": [],
        "bossID": boss_id,
    }
    if config.get("fetchPositionResources"):
        payload["resources"] = client.events(report_id, "Resources", fight, include_resources=True)
        if boss_id is not None:
            boss_damage = client.events(
                report_id,
                "DamageDone",
                fight,
                target_id=boss_id,
                include_resources=True,
            )
            payload["bossPositionEvents"] = compact_actor_position_events(boss_damage, boss_id)
    return payload


def render_fight(config, analyzer, report_id, report_start, actor_map, actor_type, fight, raw):
    boss_key = config["key"]
    players = build_player_catalog(actor_map, actor_type, raw["combatants"])
    deaths = [event for event in raw["deaths"] if event.get("targetID") in players]
    raw["deaths"] = deaths
    duration_ms = int(fight["endTime"] - fight["startTime"])
    started = datetime.fromtimestamp((report_start + fight["startTime"]) / 1000, tz=CN_TZ)
    survival = build_survival_timeline(
        fight,
        actor_map,
        players,
        deaths,
        raw["friendlyCasts"],
        config["spellNames"],
    )
    mechanics = analyzer(fight, actor_map, players, raw)
    return {
        "reportID": report_id,
        "fightID": int(fight["id"]),
        "fightName": fight.get("name"),
        "date": started.strftime("%Y-%m-%d"),
        "startClock": started.strftime("%H:%M:%S"),
        "startTimeIso": started.isoformat(),
        "isKill": bool(fight.get("kill")),
        "kill": bool(fight.get("kill")),
        "bossPercentage": float(fight.get("bossPercentage") or 0),
        "durationMs": duration_ms,
        "duration": fmt_ms(duration_ms),
        "fightPhase": "单阶段",
        "wipePhase": "击杀" if fight.get("kill") else "灭团",
        "wipeReason": "已击杀" if fight.get("kill") else "请按机制时间线复盘",
        "investigation": "死亡、战复与专属机制已按时间对齐。",
        "wclDeepLink": f"https://www.warcraftlogs.com/reports/{report_id}#fight={fight['id']}&type=summary",
        "players": list(players.values()),
        "survival": survival,
        "deathTimeline": survival["timeline"],
        boss_key: mechanics,
        **difficulty_fields(fight),
    }


def build_aggregated_json(config, analyzer, report_ids, options=None):
    boss_key = config["key"]
    report_id_list = [
        value
        for value in (item.strip() for item in report_ids.replace(" ", "").split(","))
        if value
    ]
    if not report_id_list:
        raise RuntimeError("请传入至少一个 WCL report ID。")
    client = WclClient()
    rendered = []
    progress(config, f"读取 {config['name']} Pull 列表", 8)
    for report_id in report_id_list:
        report = client.report_fights(report_id)
        fights = filter_fights(
            report_id,
            [
                fight
                for fight in report["fights"]
                if int(fight.get("encounterID") or 0) in config["encounterIDs"]
                and fight["endTime"] - fight["startTime"] >= 20_000
            ],
        )
        actors = client.actors(report_id)
        actor_map = {actor["id"]: actor["name"] for actor in actors}
        actor_type = {actor["id"]: actor.get("type") for actor in actors}
        boss_id = None
        if config.get("bossGameID"):
            boss_id = resolve_boss_actor_id(
                actors,
                config["bossGameID"],
                config.get("bossNameKeywords") or (),
            )
        progress(config, f"{report_id}：匹配 {len(fights)} 场", 12)

        def fetch_one(item):
            index, fight = item
            progress(config, f"读取 Fight {fight['id']}（{index}/{len(fights)}）")
            raw = fetch_payload(client, report_id, fight, config, boss_id=boss_id)
            return index, render_fight(
                config,
                analyzer,
                report_id,
                report["startTime"],
                actor_map,
                actor_type,
                fight,
                raw,
            )

        for _, row in run_parallel_indexed(list(enumerate(fights, start=1)), fetch_one):
            rendered.append(row)
    rendered.sort(key=lambda row: (row["startTimeIso"], row["reportID"], row["fightID"]), reverse=True)
    avoidable_rows = []
    for row in rendered:
        avoidable_rows.extend((row.get(boss_key) or {}).get("avoidable", {}).get("players", []))
    progress(config, "生成难度分组、存活时间线与机制数据", 96)
    return {
        "code": 200,
        "meta": {
            "version": "12.1",
            "raidKey": "venomous_abyss",
            "raidName": "烈毒之渊",
            "bossKey": boss_key,
            "bossName": config["name"],
            "analyzedReports": report_id_list,
            "mechanicVersion": config["mechanicVersion"],
            "tabDefinitions": [
                {"key": key, "label": label} for key, label in config["tabs"]
            ],
            "arenaImage": config["arena"],
            "features": config.get("features") or {"survival": True},
            "evidenceLimits": {
                "positions": "仅使用 WCL 实际坐标样本；超过采样窗只展示，不归责。"
            },
        },
        "data": {
            "page1_wipeAnalysis": rendered,
            "page2_avoidableBoard": {"avoidable": avoidable_rows},
        },
    }


def analyze_boss(config, analyzer, report_ids, output_path=None, catalog_entry=None, options=None):
    result = build_aggregated_json(config, analyzer, report_ids, options)
    return write_json_result(result, output_path, catalog_entry=catalog_entry)
