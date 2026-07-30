"""WCL raid-cooldown discovery and MRT/NSRT timestamp exports.

The expensive boundary is deliberately small: one report summary request per
candidate fight and one complete friendly Casts timeline per returned match.
All ability filtering and export formatting happens locally.
"""

from __future__ import annotations

import json
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable

from analyzer_core.concurrency import request_post
from boss_plugins.combat_config import TEAM_COOLDOWNS
from boss_plugins.void_spire.crown_of_the_cosmos import (
    PROXIES,
    WCL_BASE_URL,
    fetch_events_all,
    get_token,
)


ROOT = Path(__file__).resolve().parents[1]
ZONE54_DISCOVERY = ROOT / "docs" / "zone54_spell_discovery.json"

RAIDS = {
    "venomous_abyss": {
        "zoneID": 54,
        "name": "烈毒之渊",
        "bosses": [
            {"key": "nakzali", "name": "缚魂者内克扎莉", "encounterID": 53470},
            {"key": "sentinels", "name": "陵寝哨兵", "encounterID": 53445},
            {"key": "vashnik", "name": "万毒邪祟者瓦什尼克", "encounterID": 53455},
            {"key": "lostexplorers", "name": "迷失的探险者", "encounterID": 53497},
            {"key": "sszorak", "name": "斯索拉克", "encounterID": 53420},
            {"key": "twinfangs", "name": "双子毒牙", "encounterID": 53421},
            {"key": "bargained", "name": "盘卷祭坛", "encounterID": 53429},
            {"key": "ulatek", "name": "乌拉特克", "encounterID": 53492},
        ],
    }
}

HEALER_SPECS = [
    {"key": "discipline-priest", "label": "戒律 牧师", "class": "Priest", "spec": "Discipline"},
    {"key": "holy-priest", "label": "神圣 牧师", "class": "Priest", "spec": "Holy"},
    {"key": "holy-paladin", "label": "神圣 圣骑士", "class": "Paladin", "spec": "Holy"},
    {"key": "restoration-shaman", "label": "恢复 萨满祭司", "class": "Shaman", "spec": "Restoration"},
    {"key": "restoration-druid", "label": "恢复 德鲁伊", "class": "Druid", "spec": "Restoration"},
    {"key": "mistweaver-monk", "label": "织雾 武僧", "class": "Monk", "spec": "Mistweaver"},
    {"key": "preservation-evoker", "label": "恩护 唤魔师", "class": "Evoker", "spec": "Preservation"},
]

SPEC_KEY_BY_PAIR = {
    (row["class"].lower(), row["spec"].lower()): row["key"]
    for row in HEALER_SPECS
}
SPEC_KEY_BY_PAIR.update({
    ("evoker", "augmentation"): "augmentation-evoker",
})
SPEC_LABEL_BY_KEY = {row["key"]: row["label"] for row in HEALER_SPECS}
CATEGORY_LABELS = {
    "healing": "治疗大技能",
    "raid_defensive": "团队减伤",
    "external": "单体外置",
    "movement": "团队位移",
    "augmentation": "增辉/唤魔师团队功能",
}

_CACHE_LOCK = threading.Lock()
_CACHE = {}
_CACHE_TTL_SECONDS = 15 * 60


def _cached(key):
    with _CACHE_LOCK:
        row = _CACHE.get(key)
        if row and time.time() - row["createdAt"] <= _CACHE_TTL_SECONDS:
            return row["value"]
    return None


def _store_cache(key, value):
    with _CACHE_LOCK:
        _CACHE[key] = {"createdAt": time.time(), "value": value}
    return value


def _client_graphql(token: str, query: str, variables: dict) -> dict:
    response = request_post(
        f"{WCL_BASE_URL}/api/v2/client",
        json={"query": query, "variables": variables},
        headers={"Authorization": f"Bearer {token}"},
        proxies=PROXIES,
        verify=False,
        timeout=90,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError(json.dumps(payload["errors"], ensure_ascii=False))
    return payload.get("data") or {}


def options_document() -> dict:
    return {
        "schemaVersion": 1,
        "raids": [
            {
                "key": key,
                "name": raid["name"],
                "zoneID": raid["zoneID"],
                "bosses": raid["bosses"],
            }
            for key, raid in RAIDS.items()
        ],
        "difficulties": [
            {"value": 4, "label": "英雄"},
            {"value": 5, "label": "史诗"},
        ],
        "healerSpecs": HEALER_SPECS,
        "categories": [
            {"key": key, "label": value}
            for key, value in CATEGORY_LABELS.items()
        ],
        "abilityCount": len(TEAM_COOLDOWNS),
    }


def _boss(raid_key: str, boss_key: str) -> dict:
    raid = RAIDS.get(raid_key)
    if not raid:
        raise ValueError("未知副本。")
    for boss in raid["bosses"]:
        if boss["key"] == boss_key:
            return boss
    raise ValueError("未知 Boss。")


def _ranked_report_codes(token: str, encounter_id: int, difficulty: int) -> list[str]:
    cache_key = ("rankings", encounter_id, difficulty)
    cached = _cached(cache_key)
    if cached is not None:
        return cached
    query = """
    query($encounterID: Int!, $difficulty: Int!) {
      worldData {
        encounter(id: $encounterID) {
          fightRankings(difficulty: $difficulty, page: 1)
        }
      }
    }
    """
    data = _client_graphql(
        token,
        query,
        {"encounterID": int(encounter_id), "difficulty": int(difficulty)},
    )
    rankings = (
        (((data.get("worldData") or {}).get("encounter") or {}).get("fightRankings") or {})
        .get("rankings")
        or []
    )
    codes = []
    for ranking in rankings:
        report = ranking.get("report") or {}
        code = report.get("code") or ranking.get("reportCode") or ranking.get("code")
        if code:
            codes.append(str(code))
    return _store_cache(cache_key, list(dict.fromkeys(codes)))


def _discovery_report_codes(difficulty: int) -> list[str]:
    if not ZONE54_DISCOVERY.is_file():
        return []
    data = json.loads(ZONE54_DISCOVERY.read_text(encoding="utf-8"))
    key = "mythic" if int(difficulty) == 5 else "heroic"
    return [str(value) for value in (data.get("reports") or {}).get(key) or []]


def _report_overview(token: str, report_code: str) -> dict:
    cache_key = ("overview", report_code)
    cached = _cached(cache_key)
    if cached is not None:
        return cached
    query = """
    query($code: String!) {
      reportData {
        report(code: $code) {
          code
          startTime
          fights {
            id
            encounterID
            name
            difficulty
            kill
            startTime
            endTime
          }
          masterData {
            actors {
              id
              name
              type
              subType
            }
          }
        }
      }
    }
    """
    report = (
        (_client_graphql(token, query, {"code": report_code}).get("reportData") or {})
        .get("report")
        or {}
    )
    return _store_cache(cache_key, report)


def _summary_roster(token: str, report_code: str, fight_id: int) -> dict:
    cache_key = ("summary", report_code, int(fight_id))
    cached = _cached(cache_key)
    if cached is not None:
        return cached
    query = """
    query($code: String!, $fightIDs: [Int]) {
      reportData {
        report(code: $code) {
          table(dataType: Summary, fightIDs: $fightIDs)
        }
      }
    }
    """
    table = (
        (_client_graphql(
            token,
            query,
            {"code": report_code, "fightIDs": [int(fight_id)]},
        ).get("reportData") or {})
        .get("report")
        or {}
    ).get("table") or {}
    payload = table.get("data") if isinstance(table.get("data"), dict) else table
    details = (payload or {}).get("playerDetails") or {}
    players = []
    for role_key, role in (("tanks", "tank"), ("healers", "healer"), ("dps", "dps")):
        for row in details.get(role_key) or []:
            specs = row.get("specs") or []
            first_spec = specs[0] if specs else row.get("spec")
            if isinstance(first_spec, dict):
                first_spec = first_spec.get("spec") or first_spec.get("name")
            spec = str(first_spec or "").strip()
            class_name = str(row.get("type") or row.get("class") or "").strip()
            spec_key = SPEC_KEY_BY_PAIR.get((class_name.lower(), spec.lower()), "")
            players.append({
                "id": row.get("id"),
                "name": str(row.get("name") or "").split("#", 1)[0],
                "class": class_name,
                "spec": spec,
                "specKey": spec_key,
                "specLabel": SPEC_LABEL_BY_KEY.get(spec_key, f"{spec} {class_name}".strip()),
                "role": role,
            })
    result = {
        "players": players,
        "healers": [row for row in players if row["role"] == "healer"],
    }
    return _store_cache(cache_key, result)


def composition_matches(
    healer_spec_keys: Iterable[str],
    *,
    healer_count: int,
    required_spec_keys: Iterable[str],
) -> bool:
    actual = [str(value) for value in healer_spec_keys if value]
    required = [str(value) for value in required_spec_keys if value]
    if len(actual) != int(healer_count):
        return False
    actual_counts = Counter(actual)
    required_counts = Counter(required)
    return all(actual_counts[key] >= count for key, count in required_counts.items())


def _candidate_fights(
    token: str,
    *,
    encounter_id: int,
    difficulty: int,
    healer_count: int,
    required_spec_keys: list[str],
) -> list[dict]:
    report_codes = list(dict.fromkeys([
        *_ranked_report_codes(token, encounter_id, difficulty),
        *_discovery_report_codes(difficulty),
    ]))
    overviews = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(_report_overview, token, code): code
            for code in report_codes[:60]
        }
        for future in as_completed(futures):
            try:
                overviews.append(future.result())
            except Exception:
                continue

    raw_candidates = []
    for report in overviews:
        for fight in report.get("fights") or []:
            if not fight.get("kill") or int(fight.get("difficulty") or 0) != int(difficulty):
                continue
            if int(fight.get("encounterID") or 0) != int(encounter_id):
                continue
            raw_candidates.append({
                "reportID": report.get("code"),
                "fightID": int(fight["id"]),
                "startTime": int(fight["startTime"]),
                "endTime": int(fight["endTime"]),
                "durationMs": int(fight["endTime"] - fight["startTime"]),
                "name": fight.get("name"),
                "actors": (report.get("masterData") or {}).get("actors") or [],
            })
    raw_candidates.sort(key=lambda row: row["durationMs"])

    matches = []
    for candidate in raw_candidates:
        roster = _summary_roster(token, candidate["reportID"], candidate["fightID"])
        healer_keys = [row["specKey"] for row in roster["healers"]]
        if not composition_matches(
            healer_keys,
            healer_count=healer_count,
            required_spec_keys=required_spec_keys,
        ):
            continue
        matches.append({**candidate, "roster": roster})
        if len(matches) >= 5:
            break
    return matches


def _ability_id(event: dict):
    value = event.get("abilityGameID") or event.get("abilityID")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_cooldown_timeline(
    cast_events: Iterable[dict],
    *,
    fight_start: int,
    players: Iterable[dict],
) -> list[dict]:
    player_by_id = {
        int(row["id"]): row
        for row in players
        if row.get("id") is not None
    }
    rows = []
    seen = set()
    for event in cast_events or []:
        if str(event.get("type") or "").lower() not in {"cast", "begincast"}:
            continue
        spell_id = _ability_id(event)
        ability = TEAM_COOLDOWNS.get(spell_id)
        source_id = event.get("sourceID")
        if not ability or source_id is None:
            continue
        timestamp = int(event.get("timestamp") or 0)
        key = (int(source_id), spell_id, timestamp)
        if key in seen:
            continue
        seen.add(key)
        player = player_by_id.get(int(source_id)) or {}
        spec_keys = ability.get("specKeys") or []
        if spec_keys and player.get("specKey") not in spec_keys:
            continue
        rows.append({
            "timeMs": max(0, timestamp - int(fight_start)),
            "timestamp": timestamp,
            "sourceID": int(source_id),
            "player": player.get("name") or f"Actor {source_id}",
            "role": player.get("role") or "unknown",
            "specKey": player.get("specKey") or "",
            "specLabel": player.get("specLabel") or "",
            "spellID": spell_id,
            "spell": ability["name"],
            "category": ability["category"],
            "categoryLabel": CATEGORY_LABELS.get(ability["category"], ability["category"]),
        })
    return sorted(rows, key=lambda row: (row["timeMs"], row["player"], row["spellID"]))


def _clock(time_ms: int) -> str:
    total_seconds = max(0, int(time_ms) // 1000)
    return f"{total_seconds // 60:02d}:{total_seconds % 60:02d}"


def export_mrt(timeline: Iterable[dict]) -> str:
    return "\n".join(
        f"{{time:{_clock(row['timeMs'])}}} {{spell:{row['spellID']}}} {row['player']} - {row['spell']}"
        for row in timeline
    )


def export_nsrt(
    timeline: Iterable[dict],
    *,
    encounter_id: int,
    difficulty: int,
    encounter_name: str,
) -> str:
    difficulty_name = "Mythic" if int(difficulty) == 5 else "Heroic"
    lines = [
        f"EncounterID:{int(encounter_id)};Difficulty:{difficulty_name};Name:{encounter_name};"
    ]
    for row in timeline:
        seconds = round(max(0, int(row["timeMs"])) / 1000, 1)
        time_value = str(int(seconds)) if seconds.is_integer() else str(seconds)
        lines.append(
            f"time:{time_value};ph:1;tag:{row['player']};spellid:{row['spellID']};"
        )
    return "\n".join(lines)


def export_timestamp_tsv(timeline: Iterable[dict]) -> str:
    """Return a stable human-readable table for spreadsheets and dashboards."""
    lines = ["时间\t玩家\t技能\t法术ID\t类别"]
    lines.extend(
        f"{_clock(row['timeMs'])}\t{row['player']}\t{row['spell']}\t{row['spellID']}\t{row['categoryLabel']}"
        for row in timeline
    )
    return "\n".join(lines)


def search_raid_cooldowns(payload: dict) -> dict:
    raid_key = str(payload.get("raid") or "").strip()
    boss_key = str(payload.get("boss") or "").strip()
    difficulty = int(payload.get("difficulty") or 0)
    healer_count = int(payload.get("healerCount") or 0)
    required_specs = [
        str(value).strip()
        for value in payload.get("healerSpecs") or []
        if str(value).strip()
    ]
    boss = _boss(raid_key, boss_key)
    if difficulty not in {4, 5}:
        raise ValueError("难度必须是英雄或史诗。")
    if not 1 <= healer_count <= 10:
        raise ValueError("治疗人数必须在 1 到 10 之间。")
    unknown_specs = sorted(set(required_specs) - set(SPEC_LABEL_BY_KEY))
    if unknown_specs:
        raise ValueError(f"未知治疗专精：{', '.join(unknown_specs)}")
    if len(required_specs) > healer_count:
        raise ValueError("指定治疗构成数量不能超过治疗人数。")

    token = get_token()
    matches = _candidate_fights(
        token,
        encounter_id=boss["encounterID"],
        difficulty=difficulty,
        healer_count=healer_count,
        required_spec_keys=required_specs,
    )
    if not matches:
        return {
            "schemaVersion": 1,
            "status": "no_match",
            "message": "现有公开过本记录中没有对应的治疗人数与治疗构成。",
            "query": {
                "raid": raid_key,
                "boss": boss_key,
                "difficulty": difficulty,
                "healerCount": healer_count,
                "healerSpecs": required_specs,
            },
            "matches": [],
        }

    result_matches = []
    for candidate in matches:
        fight = {
            "id": candidate["fightID"],
            "startTime": candidate["startTime"],
            "endTime": candidate["endTime"],
        }
        casts = fetch_events_all(
            token,
            candidate["reportID"],
            "Casts",
            fight,
            hostility_type="Friendlies",
        )
        timeline = build_cooldown_timeline(
            casts,
            fight_start=candidate["startTime"],
            players=candidate["roster"]["players"],
        )
        result_matches.append({
            "reportID": candidate["reportID"],
            "fightID": candidate["fightID"],
            "fightName": candidate["name"],
            "durationMs": candidate["durationMs"],
            "wclUrl": f"{WCL_BASE_URL}/reports/{candidate['reportID']}#fight={candidate['fightID']}&type=casts",
            "healers": candidate["roster"]["healers"],
            "timeline": timeline,
            "exports": {
                "mrt": export_mrt(timeline),
                "nsrt": export_nsrt(
                    timeline,
                    encounter_id=boss["encounterID"],
                    difficulty=difficulty,
                    encounter_name=candidate["name"] or boss["name"],
                ),
                "timestampTsv": export_timestamp_tsv(timeline),
            },
        })
    return {
        "schemaVersion": 1,
        "status": "ok",
        "message": f"找到 {len(result_matches)} 份同治疗构成的公开过本记录。",
        "query": {
            "raid": raid_key,
            "boss": boss_key,
            "difficulty": difficulty,
            "healerCount": healer_count,
            "healerSpecs": required_specs,
        },
        "matches": result_matches,
    }
