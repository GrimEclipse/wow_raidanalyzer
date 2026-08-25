"""WCL raid-cooldown discovery and MRT/NSRT timestamp exports.

Speed-ranking pages provide the first-pass fight duration and full composition.
Only the five returned matches need report details and complete friendly Casts;
all ability filtering and export formatting happens locally.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from analyzer_core.concurrency import request_post
from boss_plugins.combat_config import TEAM_COOLDOWNS
from boss_plugins.common import CLASS_NAMES, SPEC_ICON_SLUGS, SPEC_NAMES
from boss_plugins.void_spire.crown_of_the_cosmos import (
    PROXIES,
    WCL_BASE_URL,
    fetch_events_all,
    get_token,
)


ROOT = Path(__file__).resolve().parents[1]
ZONE54_DISCOVERY_PATHS = (
    ROOT / "skills" / "venomous-abyss-raid-development" / "references" / "source-data" / "spell-discovery.json",
    ROOT / "docs" / "zone54_spell_discovery.json",
)
ZONE54_TIMELINES_PATH = (
    ROOT / "skills" / "venomous-abyss-raid-development" / "references" / "source-data" / "boss-timelines.json"
)

RAIDS = {
    "dream_rift": {
        "version": "12.0",
        "zoneID": 46,
        "name": "梦境裂隙",
        "bosses": [
            {"key": "chimaerus", "name": "奇美鲁斯，未梦之神", "encounterID": 3306},
        ],
    },
    "void_spire": {
        "version": "12.0",
        "zoneID": 46,
        "name": "虚影尖塔",
        "bosses": [
            {"key": "imperator_averzian", "name": "元首阿福扎恩", "encounterID": 3176},
            {"key": "vorasius", "name": "弗拉希乌斯", "encounterID": 3177},
            {"key": "fallen_king_salhadaar", "name": "陨落之王萨哈达尔", "encounterID": 3179},
            {"key": "vaelgor_ezzorak", "name": "威厄高尔和艾佐拉克", "encounterID": 3178},
            {"key": "lightblinded_vanguard", "name": "光盲先锋军", "encounterID": 3180},
            {"key": "crown_of_the_cosmos", "name": "宇宙之冕", "encounterID": 3181},
        ],
    },
    "march_on_queldanas": {
        "version": "12.0",
        "zoneID": 46,
        "name": "进军奎尔丹纳斯",
        "bosses": [
            {"key": "beloren", "name": "贝洛朗，奥的子嗣", "encounterID": 3182},
            {"key": "midnight_falls", "name": "至暗之夜降临", "encounterID": 3183},
        ],
    },
    "sporefall": {
        "version": "12.0",
        "zoneID": 50,
        "name": "暮孢陨坠",
        "bosses": [
            {"key": "rotmire", "name": "腐沼", "encounterID": 3159},
        ],
    },
    "venomous_abyss": {
        "version": "12.1",
        "zoneID": 53,
        "name": "烈毒之渊",
        "bosses": [
            {"key": "nakzali", "name": "缚魂者内克扎莉", "encounterID": 3470},
            {"key": "sentinels", "name": "陵寝哨兵", "encounterID": 3445},
            {"key": "vashnik", "name": "万毒邪祟者瓦什尼克", "encounterID": 3455},
            {"key": "lostexplorers", "name": "迷失的探险者", "encounterID": 3497},
            {"key": "sszorak", "name": "斯索拉克", "encounterID": 3420},
            {"key": "twinfangs", "name": "双子毒牙", "encounterID": 3421},
            {"key": "bargained", "name": "盘卷祭坛", "encounterID": 3429},
            {"key": "ulatek", "name": "乌拉特克", "encounterID": 3492},
        ],
    },
    "tidebound_grotto": {
        "version": "12.1",
        # The live WCL zone groups the one-boss lair with the main raid.
        "zoneID": 53,
        "name": "潮缚石窟",
        "bosses": [
            {"key": "nymrissa_wavecaller", "name": "尼姆瑞莎·唤潮者", "encounterID": 3379},
        ],
    },
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

ALL_SPEC_ROWS = []
for _spec_id, _icon_slug in SPEC_ICON_SLUGS.items():
    _class_slug, _spec_slug = _icon_slug.split("-", 1)
    _class_names = CLASS_NAMES.get(_class_slug) or {}
    _spec_names = SPEC_NAMES.get(_spec_id) or {}
    _class_en = _class_names.get("enUS") or _class_slug
    _spec_en = _spec_names.get("enUS") or _spec_slug
    ALL_SPEC_ROWS.append({
        "key": f"{_spec_slug}-{_class_slug}",
        "label": f"{_spec_names.get('zhCN') or _spec_en} {_class_names.get('zhCN') or _class_en}",
        "class": _class_en,
        "spec": _spec_en,
    })

SPEC_KEY_BY_PAIR = {
    (row["class"].lower(), row["spec"].lower()): row["key"]
    for row in ALL_SPEC_ROWS
}
SPEC_LABEL_BY_KEY = {row["key"]: row["label"] for row in ALL_SPEC_ROWS}
HEALER_SPEC_KEYS = {row["key"] for row in HEALER_SPECS}
HEALER_SPEC_NAME_BY_KEY = {row["key"]: row["spec"] for row in HEALER_SPECS}
HEALER_SPEC_NAMES = {row["spec"].lower() for row in HEALER_SPECS}
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
RESULT_LIMIT = 5
ROSTER_BATCH_SIZE = 4
CAST_FETCH_WORKERS = 3
MAX_RANKING_PAGES = 20
ZONE_REPORT_PAGE_SIZE = 40
MAX_ZONE_REPORT_PAGES = 3
MAX_PROVIDED_REPORTS = 10


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
    versions = list(dict.fromkeys(raid["version"] for raid in RAIDS.values()))
    return {
        "schemaVersion": 2,
        "versions": [
            {"key": value, "label": value}
            for value in versions
        ],
        "raids": [
            {
                "key": key,
                "version": raid["version"],
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
            return {**boss, "raidKey": raid_key, "version": raid["version"]}
    raise ValueError("未知 Boss。")


def _ranked_fight_page(token: str, encounter_id: int, difficulty: int, page: int = 1) -> dict:
    cache_key = ("ranking-fights", encounter_id, difficulty, int(page))
    cached = _cached(cache_key)
    if cached is not None:
        return cached
    query = """
    query($encounterID: Int!, $difficulty: Int!, $page: Int!) {
      worldData {
        encounter(id: $encounterID) {
          fightRankings(difficulty: $difficulty, page: $page, includeOtherPlayers: true)
        }
      }
    }
    """
    data = _client_graphql(
        token,
        query,
        {"encounterID": int(encounter_id), "difficulty": int(difficulty), "page": int(page)},
    )
    document = (
        (((data.get("worldData") or {}).get("encounter") or {}).get("fightRankings") or {})
    )
    result = {
        "rankings": document.get("rankings") or [],
        "page": int(document.get("page") or page),
        "count": int(document.get("count") or len(document.get("rankings") or [])),
        "hasMorePages": bool(document.get("hasMorePages")),
    }
    return _store_cache(cache_key, result)


def _ranked_report_codes(token: str, encounter_id: int, difficulty: int) -> list[str]:
    codes = []
    for ranking in _ranked_fight_page(token, encounter_id, difficulty, 1)["rankings"]:
        report = ranking.get("report") or {}
        code = report.get("code") or ranking.get("reportCode") or ranking.get("code")
        if code:
            codes.append(str(code))
    return list(dict.fromkeys(codes))


def _zone_report_page(token: str, zone_id: int, page: int = 1) -> dict:
    """Return one public-report page with enough metadata to filter locally.

    Pulling only fight metadata and friendly specs keeps each bounded page
    below WCL's complexity limit. Exact actor/class data is requested only for
    the small set whose healer count and spec names already match.
    """
    cache_key = ("zone-report-page", int(zone_id), int(page))
    cached = _cached(cache_key)
    if cached is not None:
        return cached
    query = """
    query($zoneID: Int!, $page: Int!, $limit: Int!) {
      reportData {
        reports(zoneID: $zoneID, page: $page, limit: $limit) {
          total
          current_page
          last_page
          has_more_pages
          data {
            code
            fights {
              id
              encounterID
              name
              difficulty
              kill
              startTime
              endTime
              friendlyPlayers
              friendlySpecs
            }
          }
        }
      }
    }
    """
    pagination = (
        (_client_graphql(token, query, {
            "zoneID": int(zone_id),
            "page": int(page),
            "limit": ZONE_REPORT_PAGE_SIZE,
        }).get("reportData") or {})
        .get("reports")
        or {}
    )
    result = {
        "reports": pagination.get("data") or [],
        "total": int(pagination.get("total") or 0),
        "page": int(pagination.get("current_page") or page),
        "lastPage": int(pagination.get("last_page") or 1),
        "hasMorePages": bool(pagination.get("has_more_pages")),
    }
    return _store_cache(cache_key, result)


def _zone_report_codes(token: str, zone_id: int) -> dict:
    page = _zone_report_page(token, zone_id, 1)
    return {
        "codes": list(dict.fromkeys(
            str(row.get("code"))
            for row in page["reports"]
            if row.get("code")
        )),
        "total": page["total"],
        "page": page["page"],
        "lastPage": page["lastPage"],
        "hasMorePages": page["hasMorePages"],
    }


def parse_report_codes(value) -> list[str]:
    """Extract up to ten WCL report codes from codes, URLs or mixed text."""
    values = value if isinstance(value, list) else [value]
    codes = []
    for raw in values:
        text = str(raw or "")
        codes.extend(re.findall(r"(?:warcraftlogs\.com/)?reports/([A-Za-z0-9]{16})", text, re.IGNORECASE))
        for token in re.split(r"[\s,;]+", text):
            token = token.strip()
            if re.fullmatch(r"[A-Za-z0-9]{16}", token):
                codes.append(token)
    return list(dict.fromkeys(codes))[:MAX_PROVIDED_REPORTS]


def _discovery_report_codes(
    raid_key: str,
    difficulty: int,
    encounter_id: int | None = None,
) -> list[str]:
    key = "mythic" if int(difficulty) == 5 else "heroic"
    codes = []
    raid = RAIDS.get(raid_key) or {}
    # The checked-in discovery catalog intentionally preserves PTR evidence for
    # comparison. Live raid searches must use rankings and Zone 53 instead of
    # treating those historical report IDs as formal candidates.

    if encounter_id is not None:
        boss_key = next((
            boss["key"]
            for boss in (RAIDS.get(raid_key) or {}).get("bosses", [])
            if int(boss.get("encounterID") or 0) == int(encounter_id)
        ), None)
        reference = _reference_phase_data(boss_key, difficulty) if boss_key else {}
        if (
            reference.get("reportID")
            and int(reference.get("zoneID") or 0) == int(raid.get("zoneID") or 0)
        ):
            codes.append(str(reference["reportID"]))
    return list(dict.fromkeys(codes))


@lru_cache(maxsize=1)
def _reference_timelines() -> dict:
    if not ZONE54_TIMELINES_PATH.is_file():
        return {}
    return json.loads(ZONE54_TIMELINES_PATH.read_text(encoding="utf-8"))


def _reference_phase_data(
    boss_key: str,
    difficulty: int,
    *,
    raid_key: str | None = None,
) -> dict:
    difficulty_key = "mythic" if int(difficulty) == 5 else "heroic"
    reference = (
        ((_reference_timelines().get("bosses") or {}).get(boss_key) or {}).get(difficulty_key)
        or {}
    )
    if raid_key:
        live_zone_id = int((RAIDS.get(raid_key) or {}).get("zoneID") or 0)
        if int(reference.get("zoneID") or 0) != live_zone_id:
            return {}
    return reference


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
            friendlyPlayers
            friendlySpecs
            lastPhase
            lastPhaseAsAbsoluteIndex
            lastPhaseIsIntermission
            phaseTransitions {
              id
              startTime
            }
          }
          phases {
            encounterID
            separatesWipes
            phases {
              id
              name
              isIntermission
            }
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


def _embedded_roster(report: dict, fight: dict) -> dict | None:
    """Build a fight roster from report-list metadata without another request."""
    player_ids = fight.get("friendlyPlayers") or []
    specs = fight.get("friendlySpecs") or []
    if not player_ids or len(player_ids) != len(specs):
        return None
    actors = {
        int(row["id"]): row
        for row in ((report.get("masterData") or {}).get("actors") or [])
        if row.get("id") is not None
    }
    players = []
    for player_id, raw_spec in zip(player_ids, specs):
        try:
            actor = actors.get(int(player_id), {})
        except (TypeError, ValueError):
            actor = {}
        spec = str(raw_spec or "").strip()
        actor_type = str(actor.get("type") or "").strip()
        actor_subtype = str(actor.get("subType") or "").strip()
        class_name = actor_subtype if actor_type.lower() == "player" else (actor_subtype or actor_type)
        spec_key = SPEC_KEY_BY_PAIR.get((class_name.lower(), spec.lower()), "")
        role = "healer" if spec_key in HEALER_SPEC_KEYS else "dps"
        players.append({
            "id": player_id,
            "name": str(actor.get("name") or f"玩家 {player_id}").split("#", 1)[0],
            "class": class_name,
            "spec": spec,
            "specKey": spec_key,
            "specLabel": SPEC_LABEL_BY_KEY.get(spec_key, f"{spec} {class_name}".strip()),
            "role": role,
        })
    return {
        "players": players,
        "healers": [row for row in players if row["role"] == "healer"],
    }


def _report_candidates(
    report: dict,
    *,
    encounter_id: int,
    difficulty: int,
    source: str,
) -> list[dict]:
    phase_document = next((
        row
        for row in report.get("phases") or []
        if int(row.get("encounterID") or 0) == int(encounter_id)
    ), {})
    candidates = []
    for fight in report.get("fights") or []:
        if not fight.get("kill") or int(fight.get("difficulty") or 0) != int(difficulty):
            continue
        if int(fight.get("encounterID") or 0) != int(encounter_id):
            continue
        start_time = int(fight.get("startTime") or 0)
        end_time = int(fight.get("endTime") or 0)
        friendly_healer_specs = [
            str(value).strip()
            for value in fight.get("friendlySpecs") or []
            if str(value or "").strip().lower() in HEALER_SPEC_NAMES
        ]
        candidates.append({
            "reportID": str(report.get("code") or ""),
            "fightID": int(fight["id"]),
            "startTime": start_time,
            "endTime": end_time,
            "durationMs": max(0, end_time - start_time),
            "name": fight.get("name"),
            "actors": (report.get("masterData") or {}).get("actors") or [],
            "phaseTransitions": fight.get("phaseTransitions") or [],
            "phaseMetadata": phase_document.get("phases") or [],
            "roster": _embedded_roster(report, fight),
            "reportedHealerCount": len(friendly_healer_specs) if fight.get("friendlySpecs") is not None else None,
            "friendlyHealerSpecNames": friendly_healer_specs if fight.get("friendlySpecs") is not None else None,
            "source": source,
            "overviewComplete": source != "public_reports",
        })
    return candidates


def _ranking_candidates(rankings: Iterable[dict], *, boss_name: str) -> list[dict]:
    candidates = []
    for ranking in rankings:
        report = ranking.get("report") or {}
        report_code = report.get("code") or ranking.get("reportCode") or ranking.get("code")
        fight_id = report.get("fightID") or ranking.get("fightID")
        duration_ms = int(ranking.get("duration") or 0)
        absolute_start = int(ranking.get("startTime") or 0)
        report_start = int(report.get("startTime") or 0)
        if not report_code or fight_id is None or duration_ms <= 0 or absolute_start <= 0 or report_start <= 0:
            continue
        all_characters = ranking.get("allCharacters")
        healer_spec_keys = None if all_characters is None else []
        for player in all_characters or []:
            spec_key = SPEC_KEY_BY_PAIR.get((
                str(player.get("class") or "").lower(),
                str(player.get("spec") or "").lower(),
            ), "")
            if healer_spec_keys is not None and spec_key in HEALER_SPEC_KEYS:
                healer_spec_keys.append(spec_key)
        start_time = max(0, absolute_start - report_start)
        candidates.append({
            "reportID": str(report_code),
            "fightID": int(fight_id),
            "startTime": start_time,
            "endTime": start_time + duration_ms,
            "durationMs": duration_ms,
            "name": boss_name,
            "actors": [],
            "phaseTransitions": [],
            "phaseMetadata": [],
            "roster": None,
            "reportedHealerCount": ranking.get("healers"),
            "rankingHealerSpecKeys": healer_spec_keys,
            "source": "rankings",
            "overviewComplete": False,
        })
    return candidates


def _complete_candidate_overview(token: str, candidate: dict, *, encounter_id: int) -> dict:
    if candidate.get("overviewComplete"):
        return candidate
    report = _report_overview(token, candidate["reportID"])
    fight = next((
        row for row in report.get("fights") or []
        if int(row.get("id") or 0) == int(candidate["fightID"])
    ), None)
    if fight is None:
        return candidate
    complete = _report_candidates(
        report,
        encounter_id=encounter_id,
        difficulty=int(fight.get("difficulty") or 0),
        source=candidate.get("source") or "rankings",
    )
    row = next((item for item in complete if item["fightID"] == candidate["fightID"]), None)
    if row is None:
        return candidate
    row["roster"] = candidate.get("roster") or row.get("roster")
    if row["roster"] is None:
        row["roster"] = _summary_roster(token, candidate["reportID"], candidate["fightID"])
    row["overviewComplete"] = True
    return row


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


def fight_duration_matches(
    duration_ms: int,
    *,
    min_duration_seconds: float | None = None,
    max_duration_seconds: float | None = None,
) -> bool:
    duration_seconds = max(0, int(duration_ms)) / 1000
    if min_duration_seconds is not None and duration_seconds < float(min_duration_seconds):
        return False
    if max_duration_seconds is not None and duration_seconds > float(max_duration_seconds):
        return False
    return True


def _candidate_fights(
    token: str,
    *,
    raid_key: str,
    boss_name: str,
    encounter_id: int,
    difficulty: int,
    healer_count: int,
    required_spec_keys: list[str],
    min_duration_seconds: float | None,
    max_duration_seconds: float | None,
    provided_report_codes: list[str] | None = None,
) -> dict:
    discovery_codes = _discovery_report_codes(raid_key, difficulty, encounter_id)
    provided_codes = list(dict.fromkeys(provided_report_codes or []))[:MAX_PROVIDED_REPORTS]
    matches = []
    seen_fights = set()
    inspected_reports = set()
    zone_report_codes = set()
    ranked_report_codes = set()
    source_errors = []
    successful_source_requests = 0
    encounter_difficulty_kills = 0
    duration_filtered_fights = 0
    checked_count = 0
    roster_request_count = 0
    overview_request_count = 0
    ranking_pages_scanned = 0
    zone_pages_scanned = 0
    zone_report_total = 0

    def roster_matches(roster: dict) -> bool:
        nonlocal checked_count
        checked_count += 1
        healer_keys = [row["specKey"] for row in roster["healers"]]
        return composition_matches(
            healer_keys,
            healer_count=healer_count,
            required_spec_keys=required_spec_keys,
        )

    def consider(candidates: Iterable[dict]):
        nonlocal encounter_difficulty_kills, duration_filtered_fights, roster_request_count, checked_count
        pending = []
        for candidate in sorted(candidates, key=lambda row: row["durationMs"]):
            key = (candidate["reportID"], candidate["fightID"])
            if key in seen_fights:
                continue
            seen_fights.add(key)
            encounter_difficulty_kills += 1
            if not fight_duration_matches(
                candidate["durationMs"],
                min_duration_seconds=min_duration_seconds,
                max_duration_seconds=max_duration_seconds,
            ):
                continue
            duration_filtered_fights += 1
            roster = candidate.get("roster")
            if roster is not None:
                if roster_matches(roster):
                    matches.append(candidate)
                if len(matches) >= RESULT_LIMIT:
                    return
                continue
            reported_count = candidate.get("reportedHealerCount")
            if reported_count is not None and int(reported_count) != int(healer_count):
                continue
            ranking_healers = candidate.get("rankingHealerSpecKeys")
            if ranking_healers is not None:
                checked_count += 1
                if not composition_matches(
                    ranking_healers,
                    healer_count=healer_count,
                    required_spec_keys=required_spec_keys,
                ):
                    continue
                matches.append({**candidate, "compositionPrechecked": True})
                if len(matches) >= RESULT_LIMIT:
                    return
                continue
            friendly_healer_specs = candidate.get("friendlyHealerSpecNames")
            if friendly_healer_specs is not None:
                required_spec_names = [
                    HEALER_SPEC_NAME_BY_KEY[key]
                    for key in required_spec_keys
                ]
                if not composition_matches(
                    friendly_healer_specs,
                    healer_count=healer_count,
                    required_spec_keys=required_spec_names,
                ):
                    continue
            pending.append(candidate)

        for offset in range(0, len(pending), ROSTER_BATCH_SIZE):
            if len(matches) >= RESULT_LIMIT:
                return
            batch = pending[offset:offset + ROSTER_BATCH_SIZE]
            with ThreadPoolExecutor(max_workers=min(ROSTER_BATCH_SIZE, len(batch))) as executor:
                futures = [
                    executor.submit(_summary_roster, token, candidate["reportID"], candidate["fightID"])
                    for candidate in batch
                ]
                roster_request_count += len(futures)
                rosters = [future.result() for future in futures]
            for candidate, roster in zip(batch, rosters):
                if candidate.get("compositionPrechecked") or roster_matches(roster):
                    matches.append({**candidate, "roster": roster})
                if len(matches) >= RESULT_LIMIT:
                    return

    ranking_has_more = True
    for page_number in range(1, MAX_RANKING_PAGES + 1):
        if len(matches) >= RESULT_LIMIT or not ranking_has_more:
            break
        try:
            page = _ranked_fight_page(token, encounter_id, difficulty, page_number)
            successful_source_requests += 1
        except Exception as exc:
            source_errors.append(exc)
            break
        ranking_pages_scanned += 1
        rankings = page.get("rankings") or []
        codes = {
            str((row.get("report") or {}).get("code") or row.get("reportCode") or row.get("code"))
            for row in rankings
            if (row.get("report") or {}).get("code") or row.get("reportCode") or row.get("code")
        }
        ranked_report_codes.update(codes)
        inspected_reports.update(codes)
        consider(_ranking_candidates(rankings, boss_name=boss_name))
        ranking_has_more = bool(page.get("hasMorePages")) and bool(rankings)

    seed_codes = list(dict.fromkeys([*provided_codes, *discovery_codes]))
    if len(matches) < RESULT_LIMIT and seed_codes:
        inspected_reports.update(seed_codes)
        with ThreadPoolExecutor(max_workers=min(4, len(seed_codes))) as executor:
            futures = {
                executor.submit(_report_overview, token, code): code
                for code in seed_codes
            }
            overview_request_count += len(futures)
            for future in as_completed(futures):
                try:
                    report = future.result()
                    successful_source_requests += 1
                    consider(_report_candidates(
                        report,
                        encounter_id=encounter_id,
                        difficulty=difficulty,
                        source="provided" if futures[future] in provided_codes else "discovery",
                    ))
                except Exception as exc:
                    source_errors.append(exc)

    zone_id = RAIDS[raid_key].get("zoneID")
    zone_has_more = bool(zone_id)
    for page_number in range(1, MAX_ZONE_REPORT_PAGES + 1):
        if len(matches) >= RESULT_LIMIT or not zone_has_more:
            break
        try:
            page = _zone_report_page(token, zone_id, page_number)
            successful_source_requests += 1
        except Exception as exc:
            source_errors.append(exc)
            break
        zone_pages_scanned += 1
        zone_report_total = max(zone_report_total, int(page.get("total") or 0))
        reports = page.get("reports") or []
        codes = {str(row.get("code")) for row in reports if row.get("code")}
        zone_report_codes.update(codes)
        inspected_reports.update(codes)
        candidates = []
        for report in reports:
            candidates.extend(_report_candidates(
                report,
                encounter_id=encounter_id,
                difficulty=difficulty,
                source="public_reports",
            ))
        consider(candidates)
        zone_has_more = bool(page.get("hasMorePages")) and bool(reports)

    if successful_source_requests == 0 and source_errors:
        raise RuntimeError(
            "WCL 报告暂时无法读取；请检查 API 凭据、报告可见性或稍后再试。"
        ) from source_errors[0]

    incomplete_matches = [row for row in matches[:RESULT_LIMIT] if not row.get("overviewComplete")]
    if incomplete_matches:
        with ThreadPoolExecutor(max_workers=min(4, len(incomplete_matches))) as executor:
            completed = list(executor.map(
                lambda row: _complete_candidate_overview(token, row, encounter_id=encounter_id),
                incomplete_matches,
            ))
        overview_request_count += len(incomplete_matches)
        completed_by_key = {(row["reportID"], row["fightID"]): row for row in completed}
        matches = [
            completed_by_key.get((row["reportID"], row["fightID"]), row)
            for row in matches[:RESULT_LIMIT]
        ]
    matches.sort(key=lambda row: row["durationMs"])

    return {
        "matches": matches[:RESULT_LIMIT],
        "selection": {
            "searchStrategy": "paged_prefilter",
            "rankingPage": ranking_pages_scanned,
            "rankingPagesScanned": ranking_pages_scanned,
            "zoneReportPage": zone_pages_scanned,
            "zoneReportPagesScanned": zone_pages_scanned,
            "zoneReportTotal": zone_report_total,
            "zoneReportCodeCount": len(zone_report_codes),
            "rankedReportCodeCount": len(ranked_report_codes),
            "discoveryReportCodeCount": len(discovery_codes),
            "providedReportCodeCount": len(provided_codes),
            "sourceReportCount": len(inspected_reports),
            "reportLimit": MAX_ZONE_REPORT_PAGES * ZONE_REPORT_PAGE_SIZE + MAX_RANKING_PAGES * 50 + len(seed_codes),
            "inspectedReportCount": len(inspected_reports),
            "readableReportCount": len(inspected_reports),
            "encounterDifficultyKillCount": encounter_difficulty_kills,
            "durationFilteredFightCount": duration_filtered_fights,
            "candidateFightCount": duration_filtered_fights,
            "compositionCheckedCount": checked_count,
            "rosterRequestCount": roster_request_count,
            "overviewRequestCount": overview_request_count,
            "resultLimit": RESULT_LIMIT,
            "returnedCount": len(matches[:RESULT_LIMIT]),
            "stoppedEarly": len(matches) >= RESULT_LIMIT,
            "automaticSearchCapped": (
                len(matches) < RESULT_LIMIT
                and ((zone_pages_scanned >= MAX_ZONE_REPORT_PAGES and zone_has_more)
                     or (ranking_pages_scanned >= MAX_RANKING_PAGES and ranking_has_more))
            ),
            "order": "duration_ascending",
            "minDurationSeconds": min_duration_seconds,
            "maxDurationSeconds": max_duration_seconds,
        },
    }


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
            "class": player.get("class") or "",
            "specKey": player.get("specKey") or "",
            "specLabel": player.get("specLabel") or "",
            "spellID": spell_id,
            "spell": ability["name"],
            "category": ability["category"],
            "categoryLabel": CATEGORY_LABELS.get(ability["category"], ability["category"]),
        })
    return sorted(rows, key=lambda row: (row["timeMs"], row["player"], row["spellID"]))


def _phase_display_labels(phase_metadata: Iterable[dict]) -> dict[int, str]:
    labels = {}
    stage_number = 0
    for fallback_index, phase in enumerate(phase_metadata or [], start=1):
        phase_id = int(phase.get("id") or fallback_index)
        if phase.get("isIntermission"):
            labels[phase_id] = f"P{max(1, stage_number)}.5"
        else:
            stage_number += 1
            labels[phase_id] = f"P{stage_number}"
    return labels


def _reference_phase_id(phase_key: str, phase_metadata: list[dict]) -> int:
    """Map PTR discovery labels onto WCL's encounter phase ids.

    PTR reports currently expose phase metadata but no per-fight phaseTransitions.
    The checked-in discovery timeline therefore supplies the transition times.
    """
    metadata = list(phase_metadata or [])
    ids = [int(row.get("id") or index) for index, row in enumerate(metadata, start=1)]
    if not ids:
        return 1
    key = str(phase_key or "").strip().lower()
    if key in {"intermission", "stasis"}:
        intermission = next((
            int(row.get("id") or index)
            for index, row in enumerate(metadata, start=1)
            if row.get("isIntermission")
        ), None)
        return intermission or ids[min(1, len(ids) - 1)]
    if key.startswith("p") and key[1:].isdigit():
        stage_index = max(0, int(key[1:]) - 1)
        stage_ids = [
            int(row.get("id") or index)
            for index, row in enumerate(metadata, start=1)
            if not row.get("isIntermission")
        ]
        return stage_ids[min(stage_index, len(stage_ids) - 1)] if stage_ids else ids[0]
    if key.startswith("special-") and key.rsplit("-", 1)[-1].isdigit():
        special_index = int(key.rsplit("-", 1)[-1])
        return ids[min(special_index, len(ids) - 1)]
    return ids[0]


def build_phase_segments(
    *,
    fight_start: int,
    fight_end: int,
    phase_transitions: Iterable[dict] = (),
    phase_metadata: Iterable[dict] = (),
    reference: dict | None = None,
    report_id: str = "",
    fight_id: int = 0,
) -> dict:
    """Return normalized, ordered phase segments for one fight.

    Live 12.0 fights use WCL phaseTransitions. PTR fights fall back to the
    repository's observed phase markers because WCL currently returns null
    transitions for those reports.
    """
    metadata = list(phase_metadata or [])
    metadata_by_id = {
        int(row.get("id") or index): row
        for index, row in enumerate(metadata, start=1)
    }
    display_labels = _phase_display_labels(metadata)
    duration_ms = max(0, int(fight_end) - int(fight_start))
    segments = []
    source = "single_phase"
    confidence = "fallback"

    for transition in phase_transitions or []:
        phase_id = int(transition.get("id") or 1)
        raw_start = int(transition.get("startTime") or fight_start)
        relative_start = raw_start - int(fight_start) if raw_start >= int(fight_start) else raw_start
        phase = metadata_by_id.get(phase_id) or {}
        segments.append({
            "phaseIndex": phase_id,
            "phaseLabel": display_labels.get(phase_id, f"P{phase_id}"),
            "phaseName": str(phase.get("name") or f"Phase {phase_id}"),
            "startTimeMs": max(0, min(duration_ms, relative_start)),
        })
    if segments:
        source = "wcl"
        confidence = "exact"
    elif reference:
        reference_duration = max(1, int(reference.get("durationMs") or duration_ms or 1))
        exact_reference = (
            str(reference.get("reportID") or "") == str(report_id or "")
            and int(reference.get("fightID") or 0) == int(fight_id or 0)
        )
        scale = 1.0 if exact_reference else duration_ms / reference_duration
        for marker in reference.get("phaseMarkers") or []:
            phase_key = str(marker.get("phase") or "")
            if phase_key.lower() in {"kill", "wipe", "enrage"} or marker.get("source") == "fightEnd":
                continue
            phase_id = _reference_phase_id(phase_key, metadata)
            phase = metadata_by_id.get(phase_id) or {}
            segments.append({
                "phaseIndex": phase_id,
                "phaseLabel": display_labels.get(phase_id, phase_key.upper() or f"P{phase_id}"),
                "phaseName": str(marker.get("label") or phase.get("name") or phase_key or f"Phase {phase_id}"),
                "startTimeMs": max(0, min(duration_ms, round(int(marker.get("timeMs") or 0) * scale))),
            })
        if segments:
            source = "ptr_reference" if exact_reference else "ptr_reference_scaled"
            confidence = "observed" if exact_reference else "estimated"

    if not segments:
        first_phase = metadata_by_id.get(1) or (metadata[0] if metadata else {})
        first_id = int(first_phase.get("id") or 1)
        segments = [{
            "phaseIndex": first_id,
            "phaseLabel": display_labels.get(first_id, "P1"),
            "phaseName": str(first_phase.get("name") or "全程"),
            "startTimeMs": 0,
        }]
    segments.sort(key=lambda row: row["startTimeMs"])
    if segments[0]["startTimeMs"] > 0:
        first_phase = metadata_by_id.get(1) or {}
        segments.insert(0, {
            "phaseIndex": 1,
            "phaseLabel": display_labels.get(1, "P1"),
            "phaseName": str(first_phase.get("name") or "开场"),
            "startTimeMs": 0,
        })
    deduplicated = []
    for segment in segments:
        if deduplicated and segment == deduplicated[-1]:
            continue
        deduplicated.append(segment)
    for index, segment in enumerate(deduplicated):
        segment["endTimeMs"] = (
            deduplicated[index + 1]["startTimeMs"]
            if index + 1 < len(deduplicated)
            else duration_ms
        )
    return {
        "source": source,
        "confidence": confidence,
        "segments": deduplicated,
    }


def apply_phase_segments(timeline: Iterable[dict], phase_document: dict) -> list[dict]:
    segments = list((phase_document or {}).get("segments") or [])
    if not segments:
        return list(timeline or [])
    rows = []
    for row in timeline or []:
        time_ms = max(0, int(row.get("timeMs") or 0))
        segment = segments[0]
        for candidate in segments:
            if int(candidate.get("startTimeMs") or 0) <= time_ms:
                segment = candidate
            else:
                break
        rows.append({
            **row,
            "phaseIndex": int(segment.get("phaseIndex") or 1),
            "phaseLabel": segment.get("phaseLabel") or "P1",
            "phaseName": segment.get("phaseName") or "全程",
            "phaseTimeMs": max(0, time_ms - int(segment.get("startTimeMs") or 0)),
        })
    return rows


def _clock(time_ms: int) -> str:
    total_seconds = max(0, int(time_ms) // 1000)
    return f"{total_seconds // 60:02d}:{total_seconds % 60:02d}"


def export_mrt(timeline: Iterable[dict]) -> str:
    lines = []
    current_phase = None
    for row in timeline:
        phase = row.get("phaseLabel") or "P1"
        if phase != current_phase:
            if lines:
                lines.append("")
            lines.append(f"[{phase}] {row.get('phaseName') or '阶段'}")
            current_phase = phase
        lines.append(
            f"{{time:{_clock(row['timeMs'])}}} {{spell:{row['spellID']}}} {row['player']} - {row['spell']}"
        )
    return "\n".join(lines)


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
        seconds = round(max(0, int(row.get("phaseTimeMs", row["timeMs"]))) / 1000, 1)
        time_value = str(int(seconds)) if seconds.is_integer() else str(seconds)
        lines.append(
            f"time:{time_value};ph:{int(row.get('phaseIndex') or 1)};tag:{row['player']};spellid:{row['spellID']};"
        )
    return "\n".join(lines)


def export_timestamp_tsv(timeline: Iterable[dict]) -> str:
    """Return a stable human-readable table for spreadsheets and dashboards."""
    lines = ["全场时间\t阶段\t阶段内时间\t玩家\t技能\t法术ID\t类别"]
    lines.extend(
        f"{_clock(row['timeMs'])}\t{row.get('phaseLabel') or 'P1'}\t{_clock(row.get('phaseTimeMs', row['timeMs']))}\t{row['player']}\t{row['spell']}\t{row['spellID']}\t{row['categoryLabel']}"
        for row in timeline
    )
    return "\n".join(lines)


def search_raid_cooldowns(payload: dict) -> dict:
    started_at = time.perf_counter()
    raid_key = str(payload.get("raid") or "").strip()
    boss_key = str(payload.get("boss") or "").strip()
    difficulty = int(payload.get("difficulty") or 0)
    healer_count = int(payload.get("healerCount") or 0)
    required_specs = [
        str(value).strip()
        for value in payload.get("healerSpecs") or []
        if str(value).strip()
    ]
    provided_report_codes = parse_report_codes(payload.get("reportCodes") or payload.get("reportUrls"))
    min_duration_raw = payload.get("minFightDurationSeconds")
    max_duration_raw = payload.get("maxFightDurationSeconds")
    min_duration_seconds = None if min_duration_raw is None or min_duration_raw == "" else float(min_duration_raw)
    max_duration_seconds = None if max_duration_raw is None or max_duration_raw == "" else float(max_duration_raw)
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
    if min_duration_seconds is not None and min_duration_seconds < 0:
        raise ValueError("战斗时长下限不能小于 0 秒。")
    if max_duration_seconds is not None and max_duration_seconds < 0:
        raise ValueError("战斗时长上限不能小于 0 秒。")
    if (
        min_duration_seconds is not None
        and max_duration_seconds is not None
        and max_duration_seconds < min_duration_seconds
    ):
        raise ValueError("战斗时长上限不能小于下限。")

    token = get_token()
    candidate_result = _candidate_fights(
        token,
        raid_key=raid_key,
        boss_name=boss["name"],
        encounter_id=boss["encounterID"],
        difficulty=difficulty,
        healer_count=healer_count,
        required_spec_keys=required_specs,
        min_duration_seconds=min_duration_seconds,
        max_duration_seconds=max_duration_seconds,
        provided_report_codes=provided_report_codes,
    )
    matches = candidate_result["matches"]
    selection = candidate_result["selection"]
    if not matches:
        selection["elapsedMs"] = round((time.perf_counter() - started_at) * 1000)
        return {
            "schemaVersion": 2,
            "status": "no_match",
            "message": "现有公开过本记录中没有对应的治疗人数与治疗构成。",
            "query": {
                "raid": raid_key,
                "boss": boss_key,
                "difficulty": difficulty,
                "healerCount": healer_count,
                "healerSpecs": required_specs,
                "minFightDurationSeconds": min_duration_seconds,
                "maxFightDurationSeconds": max_duration_seconds,
                "reportCodes": provided_report_codes,
            },
            "selection": selection,
            "matches": [],
        }

    def build_result(candidate):
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
        phase_document = build_phase_segments(
            fight_start=candidate["startTime"],
            fight_end=candidate["endTime"],
            phase_transitions=candidate.get("phaseTransitions") or [],
            phase_metadata=candidate.get("phaseMetadata") or [],
            reference=_reference_phase_data(boss_key, difficulty, raid_key=raid_key),
            report_id=candidate["reportID"],
            fight_id=candidate["fightID"],
        )
        timeline = apply_phase_segments(timeline, phase_document)
        return {
            "reportID": candidate["reportID"],
            "fightID": candidate["fightID"],
            "fightName": candidate["name"],
            "durationMs": candidate["durationMs"],
            "wclUrl": f"{WCL_BASE_URL}/reports/{candidate['reportID']}#fight={candidate['fightID']}&type=casts",
            "healers": candidate["roster"]["healers"],
            "phases": phase_document,
            "timeline": timeline,
            "exportContext": {
                "encounterID": boss["encounterID"],
                "difficulty": difficulty,
                "encounterName": candidate["name"] or boss["name"],
            },
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
        }

    with ThreadPoolExecutor(max_workers=min(CAST_FETCH_WORKERS, len(matches))) as executor:
        result_matches = list(executor.map(build_result, matches))
    selection["elapsedMs"] = round((time.perf_counter() - started_at) * 1000)
    return {
        "schemaVersion": 2,
        "status": "ok",
        "message": f"找到 {len(result_matches)} 份同治疗构成的公开过本记录。",
        "query": {
            "raid": raid_key,
            "boss": boss_key,
            "difficulty": difficulty,
            "healerCount": healer_count,
            "healerSpecs": required_specs,
            "minFightDurationSeconds": min_duration_seconds,
            "maxFightDurationSeconds": max_duration_seconds,
            "reportCodes": provided_report_codes,
        },
        "selection": selection,
        "matches": result_matches,
    }
