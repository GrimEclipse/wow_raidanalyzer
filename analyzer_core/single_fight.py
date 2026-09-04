"""Manual guild-report discovery and isolated single-fight analysis service."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from analyzer_core.analysis_scope import single_fight_scope
from analyzer_core.catalog import CATALOG, BossEntry, find_boss_by_encounter
from analyzer_core.player_abilities import abilities_for_roster, catalog_summary
from analyzer_core.progress import emit_progress
from analyzer_core.raid_cooldowns import RAIDS
from analyzer_core.runner import analyze_report
from analyzer_core.wcl_api import WclClient


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "single_fight.json"
CACHE_DIR = ROOT / ".single_fight_cache"
ANALYSIS_SCHEMA = "single-fight-v2"

DIFFICULTIES = {1: "普通", 3: "普通", 4: "英雄", 5: "史诗", 10: "史诗钥石"}


def load_single_fight_config() -> dict:
    document = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    guild = dict(document.get("guild") or {})
    configured_id = int(guild.get("id") or 774422)
    guild["id"] = int(os.getenv("WCL_GUILD_ID") or configured_id)
    if guild["id"] != configured_id:
        guild["name"] = ""
    document["guild"] = guild
    return document


def raid_night_date(timestamp_ms: int | float, *, timezone_name: str, rollover_hour: int) -> str:
    local = datetime.fromtimestamp(float(timestamp_ms) / 1000, tz=ZoneInfo(timezone_name))
    return (local - timedelta(hours=int(rollover_hour))).date().isoformat()


def _local_iso(timestamp_ms: int | float, timezone_name: str) -> str:
    return datetime.fromtimestamp(float(timestamp_ms) / 1000, tz=ZoneInfo(timezone_name)).isoformat()


def _known_encounters() -> dict[int, dict]:
    rows = {}
    for raid_key, raid in RAIDS.items():
        version = str(raid.get("version") or "").replace(" PTR", "")
        for boss in raid.get("bosses") or []:
            rows[int(boss["encounterID"])] = {
                "version": version,
                "raidKey": raid_key,
                "raidName": raid["name"],
                "bossKey": boss["key"],
                "bossName": boss["name"],
            }
    return rows


KNOWN_ENCOUNTERS = _known_encounters()


def _entry_for_fight(fight: dict) -> BossEntry | None:
    encounter_id = int(fight.get("encounterID") or 0)
    entry = find_boss_by_encounter(encounter_id)
    if entry:
        return entry
    known = KNOWN_ENCOUNTERS.get(encounter_id)
    if not known:
        return None
    return next((
        row for row in CATALOG
        if row.version == known["version"]
        and row.raid_key == known["raidKey"]
        and row.boss_key == known["bossKey"]
    ), None)


def _fight_document(report: dict, fight: dict, config: dict) -> dict:
    report_start = int(report.get("startTime") or 0)
    absolute_start = report_start + int(fight.get("startTime") or 0)
    absolute_end = report_start + int(fight.get("endTime") or 0)
    raid_config = config["raidNight"]
    entry = _entry_for_fight(fight)
    known = KNOWN_ENCOUNTERS.get(int(fight.get("encounterID") or 0), {})
    result = {
        "id": int(fight.get("id") or 0),
        "name": fight.get("name") or known.get("bossName") or "未知战斗",
        "encounterID": int(fight.get("encounterID") or 0),
        "difficulty": int(fight.get("difficulty") or 0),
        "difficultyName": DIFFICULTIES.get(int(fight.get("difficulty") or 0), "未知"),
        "kill": bool(fight.get("kill")),
        "durationMs": max(0, int(fight.get("endTime") or 0) - int(fight.get("startTime") or 0)),
        "relativeStartTime": int(fight.get("startTime") or 0),
        "relativeEndTime": int(fight.get("endTime") or 0),
        "absoluteStartTime": absolute_start,
        "absoluteEndTime": absolute_end,
        "startTimeIso": _local_iso(absolute_start, raid_config["timezone"]),
        "raidNightDate": raid_night_date(
            absolute_start,
            timezone_name=raid_config["timezone"],
            rollover_hour=raid_config["rolloverHour"],
        ),
        "wclUrl": f"https://www.warcraftlogs.com/reports/{report.get('code', '')}#fight={int(fight.get('id') or 0)}",
        "supported": bool(entry and entry.supported),
        "disabledReason": entry.disabled_reason if entry and not entry.supported else "",
    }
    identity = entry and {
        "version": entry.version,
        "raidKey": entry.raid_key,
        "raidName": entry.raid_name,
        "bossKey": entry.boss_key,
        "bossName": entry.boss_name,
    } or known
    if identity:
        result["analysisIdentity"] = identity
    return result


def _candidate_fights(report: dict, config: dict) -> list[dict]:
    rows = [
        _fight_document(report, fight, config)
        for fight in report.get("fights") or []
        if int(fight.get("encounterID") or 0) > 0
        and int(fight.get("endTime") or 0) - int(fight.get("startTime") or 0) >= 20_000
    ]
    return sorted(rows, key=lambda row: (row["absoluteStartTime"], row["id"]))


def recent_guild_reports(
    client: WclClient | None = None,
    *,
    selected_date: str = "",
    limit: int | None = None,
    guild_id: int | None = None,
) -> dict:
    config = load_single_fight_config()
    client = client or WclClient()
    configured_guild_id = int(config["guild"]["id"])
    selected_guild_id = configured_guild_id if guild_id is None else int(guild_id)
    if selected_guild_id <= 0:
        raise ValueError("WCL 工会 ID 必须是正整数。")
    selected_guild = dict(config["guild"])
    selected_guild["id"] = selected_guild_id
    if selected_guild_id != configured_guild_id:
        selected_guild["name"] = "自定义工会"
    report_limit = max(1, min(50, int(limit or config.get("recentReportLimit") or 20)))
    query = """
    query($guildID: Int!, $limit: Int!) {
      guildData { guild(id: $guildID) { id name } }
      reportData { reports(guildID: $guildID, limit: $limit) { data {
        code title startTime endTime zone { id name }
        fights { id name encounterID difficulty kill startTime endTime bossPercentage fightPercentage }
      } } }
      rateLimitData { limitPerHour pointsSpentThisHour pointsResetIn }
    }
    """
    data = client.graphql_data(query, {"guildID": selected_guild_id, "limit": report_limit})
    wcl_guild = (data.get("guildData") or {}).get("guild") or {}
    if wcl_guild:
        selected_guild = {
            "id": int(wcl_guild.get("id") or selected_guild_id),
            "name": str(wcl_guild.get("name") or selected_guild.get("name") or "工会"),
        }
    reports = []
    for raw in ((data.get("reportData") or {}).get("reports") or {}).get("data") or []:
        report = {**raw, "code": str(raw.get("code") or "")}
        fights = _candidate_fights(report, config)
        if selected_date:
            fights = [row for row in fights if row["raidNightDate"] == selected_date]
        if selected_date and not fights:
            continue
        dates = sorted({row["raidNightDate"] for row in fights})
        reports.append({
            "code": report["code"],
            "title": report.get("title") or report["code"],
            "zone": report.get("zone") or {},
            "startTime": report.get("startTime"),
            "endTime": report.get("endTime"),
            "raidNightDates": dates,
            "fightCount": len(fights),
            "supportedFightCount": sum(1 for row in fights if row["supported"]),
            "lastFight": fights[-1] if fights else None,
            "fights": fights,
        })
    return {
        "schemaVersion": 1,
        "guild": selected_guild,
        "raidNight": config["raidNight"],
        "selectedDate": selected_date,
        "reports": reports,
        "rateLimit": data.get("rateLimitData") or {},
        "abilityCatalog": catalog_summary(),
    }


def latest_guild_fight(
    client: WclClient | None = None,
    *,
    guild_id: int | None = None,
    report_limit: int = 5,
) -> dict:
    """Resolve the chronologically latest completed Boss pull for a guild.

    Selection is intentionally strict: an unsupported latest Boss is returned so
    the caller can explain that limitation instead of silently analyzing an older
    encounter.
    """
    discovery = recent_guild_reports(
        client,
        guild_id=guild_id,
        limit=max(1, min(10, int(report_limit or 5))),
    )
    candidates = [
        {"report": report, "fight": fight}
        for report in discovery["reports"]
        for fight in report.get("fights") or []
    ]
    if not candidates:
        raise ValueError("最近的 WCL 报告中没有已结束且时长达到 20 秒的 Boss 战。")
    selected = max(
        candidates,
        key=lambda row: (
            int(row["fight"].get("absoluteStartTime") or 0),
            int(row["fight"].get("id") or 0),
        ),
    )
    return {
        "schemaVersion": 1,
        "guild": discovery["guild"],
        "report": {
            "code": selected["report"]["code"],
            "title": selected["report"]["title"],
        },
        "fight": selected["fight"],
        "rateLimit": discovery["rateLimit"],
    }


def report_overview(report_code: str, client: WclClient | None = None) -> dict:
    config = load_single_fight_config()
    code = str(report_code or "").strip()
    if not code:
        raise ValueError("缺少 WCL report code。")
    client = client or WclClient()
    query = """
    query($code: String!) { reportData { report(code: $code) {
      title startTime endTime guild { id name }
      fights { id name encounterID difficulty kill startTime endTime bossPercentage fightPercentage friendlyPlayers friendlySpecs }
      masterData { actors { id name type subType petOwner gameID } }
    } } }
    """
    report = client.graphql_data(query, {"code": code})["reportData"]["report"]
    if not report:
        raise ValueError(f"无法读取 report：{code}")
    report = {**report, "code": code}
    actors = {int(row["id"]): row for row in (report.get("masterData") or {}).get("actors") or []}
    fights = _candidate_fights(report, config)
    raw_fights = {int(row.get("id") or 0): row for row in report.get("fights") or []}
    for fight in fights:
        raw = raw_fights[fight["id"]]
        ids = list(raw.get("friendlyPlayers") or [])
        specs = list(raw.get("friendlySpecs") or [])
        roster = []
        for index, actor_id in enumerate(ids):
            actor = actors.get(int(actor_id)) or {}
            if actor.get("type") != "Player":
                continue
            roster.append({
                "id": int(actor_id),
                "name": actor.get("name") or f"Player {actor_id}",
                "class": actor.get("subType") or "Unknown",
                "spec": str(specs[index] if index < len(specs) else ""),
            })
        fight["roster"] = roster
        resolved = abilities_for_roster(roster)
        fight["abilitySelection"] = {
            "abilityCount": len(resolved["abilities"]),
            "spellIdCount": len(resolved["spellIds"]),
            "classes": sorted({row["class"] for row in roster}),
            "specs": sorted({row["spec"] for row in roster if row["spec"]}),
        }
    return {
        "schemaVersion": 1,
        "code": code,
        "title": report.get("title") or code,
        "guild": report.get("guild") or config["guild"],
        "raidNightDates": sorted({row["raidNightDate"] for row in fights}),
        "fights": fights,
    }


def _ability_id(event: dict) -> int:
    ability = event.get("ability") or {}
    return int(event.get("abilityGameID") or event.get("abilityID") or ability.get("gameID") or 0)


def _event_pages(client: WclClient, report_code: str, data_type: str, fight: dict) -> tuple[list[dict], int]:
    rows = []
    page_count = 0
    current = float(fight["startTime"])
    end_time = float(fight["endTime"])
    while current < end_time:
        page = client.event_page(
            report_code, data_type, fight,
            start_time=current, end_time=end_time, hostility_type="Friendlies",
        )
        page_count += 1
        rows.extend(page.get("data") or [])
        next_page = page.get("nextPageTimestamp")
        if not next_page or float(next_page) <= current:
            break
        current = float(next_page)
    return rows, page_count


def player_ability_timeline(client: WclClient, report_code: str, fight: dict, roster: list[dict]) -> dict:
    resolved = abilities_for_roster(roster)
    players = {int(row["id"]): row for row in roster}
    actor_catalog = {actor_id: abilities_for_roster([player])["byEvent"] for actor_id, player in players.items()}
    cast_rows, cast_pages = _event_pages(client, report_code, "Casts", fight)
    aura_rows, aura_pages = _event_pages(client, report_code, "Buffs", fight)
    timeline = []

    for event_kind, events in (("cast", cast_rows), ("aura", aura_rows)):
        for event in events:
            if event_kind == "aura" and event.get("type") not in {"applybuff", "refreshbuff"}:
                continue
            actor_id = int(event.get("sourceID") if event_kind == "cast" else event.get("targetID") or 0)
            player = players.get(actor_id)
            ability_id = _ability_id(event)
            ability = (actor_catalog.get(actor_id) or {}).get(event_kind, {}).get(ability_id)
            if not player or not ability:
                continue
            timeline.append({
                "timestamp": int(event.get("timestamp") or 0),
                "timeMs": int(event.get("timestamp") or 0) - int(fight["startTime"]),
                "event": event_kind,
                "type": event.get("type") or event_kind,
                "abilityId": ability_id,
                "abilityKey": ability["key"],
                "abilityName": ability["nameZh"],
                "category": ability["category"],
                "playerId": actor_id,
                "playerName": player["name"],
                "class": player["class"],
                "spec": player["spec"],
                "targetId": int(event.get("targetID") or 0) or None,
            })

    unique = {}
    for row in timeline:
        identity = (row["timestamp"], row["event"], row["abilityId"], row["playerId"], row["targetId"])
        unique[identity] = row
    timeline = sorted(unique.values(), key=lambda row: (row["timestamp"], row["playerId"], row["abilityId"]))
    return {
        "selection": {
            "strategy": "composition -> class/spec -> verified ability IDs -> two bulk event streams",
            "rosterCount": len(roster),
            "abilityCount": len(resolved["abilities"]),
            "spellIdCount": len(resolved["spellIds"]),
        },
        "requestMetrics": {
            "castPages": cast_pages,
            "buffPages": aura_pages,
            "logicalGraphQLRequests": cast_pages + aura_pages,
            "perSpellQueries": 0,
        },
        "events": timeline,
    }


def _cache_key(report_code: str, fight_id: int, entry: BossEntry, options: dict) -> str:
    plugin = importlib.import_module(entry.plugin)
    implementation_paths = [
        Path(plugin.__file__).resolve(),
        ROOT / "boss_catalog.json",
        ROOT / "analyzer_core" / "single_fight.py",
    ]
    if entry.raid_key == "venomous_abyss":
        implementation_paths.extend([
            ROOT / "boss_plugins" / "venomous_abyss" / "shared.py",
            ROOT / "skills" / "venomous-abyss-raid-development" / "references" / "source-data" / "raid-guide-source.json",
        ])
    if entry.boss_key == "crown_of_the_cosmos":
        implementation_paths.append(ROOT / "tools" / "crown_single_fight_audit.py")
    implementation_hash = hashlib.sha256()
    for path in implementation_paths:
        implementation_hash.update(path.read_bytes())
    source = {
        "schema": ANALYSIS_SCHEMA,
        "report": report_code,
        "fight": int(fight_id),
        "identity": [entry.version, entry.raid_key, entry.boss_key],
        "options": options,
        "abilityCatalog": catalog_summary()["digest"],
        "implementation": implementation_hash.hexdigest()[:16],
    }
    return hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:24]


def analyze_single_fight(
    *, report_code: str, fight_id: int, output_path: Path, options: dict | None = None,
    force: bool = False, progress_callback=None,
) -> dict:
    from analyzer_core.contracts import apply_analysis_contract

    started = time.perf_counter()
    code = str(report_code or "").strip()
    options = dict(options or {})
    client = WclClient()
    emit_progress("读取 report 场次与阵容", percent=5, stage="discovery")
    overview = report_overview(code, client)
    fight = next((row for row in overview["fights"] if row["id"] == int(fight_id)), None)
    if not fight:
        raise ValueError(f"report {code} 中不存在可分析的 Fight {fight_id}。")
    entry = _entry_for_fight(fight)
    if not entry or not entry.supported:
        reason = entry.disabled_reason if entry else "未在 Boss 目录中登记"
        raise ValueError(f"{fight['name']} 暂不能生成单场结论：{reason}。")

    cache_key = _cache_key(code, int(fight_id), entry, options)
    cache_path = CACHE_DIR / entry.version / entry.raid_key / entry.boss_key / f"{cache_key}.json"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.is_file() and not force:
        shutil.copyfile(cache_path, output_path)
        result = json.loads(output_path.read_text(encoding="utf-8"))
        single_meta = result.setdefault("meta", {}).setdefault("singleFight", {})
        single_meta["cacheHit"] = True
        single_meta["sourceElapsedSeconds"] = single_meta.get("elapsedSeconds")
        single_meta["elapsedSeconds"] = round(time.perf_counter() - started, 3)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        emit_progress("命中同场分析缓存", percent=99, stage="cache")
        return {"path": output_path, "cacheHit": True, "cacheKey": cache_key}

    emit_progress("按当前 Boss 逐场规则开始分析", percent=12, stage="analyze")
    with single_fight_scope(code, int(fight_id)):
        analyze_report(
            version=entry.version,
            raid_key=entry.raid_key,
            boss_key=entry.boss_key,
            report_ids=code,
            output_path=output_path,
            options=options,
            progress_callback=progress_callback,
        )

    result = json.loads(output_path.read_text(encoding="utf-8-sig"))
    elapsed = round(time.perf_counter() - started, 3)
    result.setdefault("meta", {})["singleFight"] = {
        "schemaVersion": ANALYSIS_SCHEMA,
        "guild": overview["guild"],
        "reportCode": code,
        "fightID": fight["id"],
        "raidNightDate": fight["raidNightDate"],
        "startTimeIso": fight["startTimeIso"],
        "encounterID": fight["encounterID"],
        "cacheKey": cache_key,
        "cacheHit": False,
        "elapsedSeconds": elapsed,
        "abilitySelection": fight["abilitySelection"],
    }
    result = apply_analysis_contract(result)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(output_path, cache_path)
    emit_progress("单场结论已写入缓存", percent=99, stage="write")
    return {"path": output_path, "cacheHit": False, "cacheKey": cache_key}
