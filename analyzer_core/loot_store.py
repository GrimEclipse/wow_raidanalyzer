"""Local progression attendance and loot allocation store."""
from __future__ import annotations

import copy
import json
import sqlite3
import time
import uuid
from datetime import date as date_type, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "scoreboard" / "loot.db"
CATALOG_PATH = ROOT / "assets" / "loot" / "raid_loot_12_1.json"
DIFFICULTIES = {"lfr", "normal", "heroic", "mythic"}
DIFFICULTY_NAMES = {"lfr": "随机团队", "normal": "普通", "heroic": "英雄", "mythic": "史诗"}
ATTENDANCE_STATUSES = {"present", "late", "leave", "absent"}
AWARD_TYPES = {"need", "greed", "transmog", "alt"}
ARMOR_TYPES = {"cloth", "leather", "mail", "plate", "accessory", "weapon", "token", "other"}
SCHEDULED_WEEKDAYS = {3, 4, 5}  # Thursday, Friday, Saturday (Monday=0)


def _empty_state() -> Dict[str, Any]:
    return {"schemaVersion": 1, "roster": [], "days": [], "allocations": []}


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS loot_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            body TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def _load_state() -> Dict[str, Any]:
    with _connect() as conn:
        row = conn.execute("SELECT body FROM loot_state WHERE id = 1").fetchone()
    if not row:
        return _empty_state()
    try:
        return _normalise_state(json.loads(row[0]))
    except (json.JSONDecodeError, TypeError, ValueError):
        return _empty_state()


def _save_state(state: Dict[str, Any]) -> None:
    state = _normalise_state(state)
    body = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO loot_state(id, body, updated_at) VALUES (1, ?, ?)",
            (body, now),
        )
        conn.commit()


def _text(value: Any, limit: int = 200) -> str:
    return str(value or "").strip()[:limit]


def _parse_date(value: Any) -> date_type:
    try:
        return date_type.fromisoformat(_text(value, 10))
    except ValueError as error:
        raise ValueError("日期必须使用 YYYY-MM-DD 格式。") from error


def _normalise_roster(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result = []
    seen = set()
    for raw in rows or []:
        player_id = _text(raw.get("id"), 80) or uuid.uuid4().hex[:12]
        name = _text(raw.get("name"), 80)
        if not name or player_id in seen:
            continue
        seen.add(player_id)
        armor = _text(raw.get("armorType"), 20).lower()
        result.append({
            "id": player_id,
            "name": name,
            "classKey": _text(raw.get("classKey"), 30).lower(),
            "className": _text(raw.get("className"), 40),
            "armorType": armor if armor in ARMOR_TYPES else "other",
            "active": bool(raw.get("active", True)),
            "notes": _text(raw.get("notes"), 300),
        })
    return result


def _normalise_days(rows: Iterable[Dict[str, Any]], player_ids: set[str]) -> List[Dict[str, Any]]:
    result = []
    seen_dates = set()
    for raw in rows or []:
        try:
            day_date = _parse_date(raw.get("date")).isoformat()
        except ValueError:
            continue
        if day_date in seen_dates:
            continue
        seen_dates.add(day_date)
        attendance = []
        seen_players = set()
        for entry in raw.get("attendance") or []:
            player_id = _text(entry.get("playerId"), 80)
            status = _text(entry.get("status"), 20).lower()
            if player_id not in player_ids or player_id in seen_players or status not in ATTENDANCE_STATUSES:
                continue
            seen_players.add(player_id)
            attendance.append({
                "playerId": player_id,
                "status": status,
                "note": _text(entry.get("note"), 300),
            })
        result.append({
            "date": day_date,
            "raidKey": _text(raw.get("raidKey"), 80) or "venomous_abyss",
            "notes": _text(raw.get("notes"), 1000),
            "attendance": attendance,
        })
    return sorted(result, key=lambda row: row["date"])


def _normalise_request(raw: Dict[str, Any], player_ids: set[str]) -> Dict[str, Any] | None:
    player_id = _text(raw.get("playerId"), 80)
    mode = _text(raw.get("mode"), 20).lower()
    if player_id not in player_ids or mode not in AWARD_TYPES:
        return None
    return {"playerId": player_id, "mode": mode, "note": _text(raw.get("note"), 300)}


def _normalise_allocations(rows: Iterable[Dict[str, Any]], player_ids: set[str]) -> List[Dict[str, Any]]:
    result = []
    for raw in rows or []:
        try:
            allocation_date = _parse_date(raw.get("date")).isoformat()
        except ValueError:
            continue
        recipient_id = _text(raw.get("recipientId"), 80)
        award_type = _text(raw.get("awardType"), 20).lower()
        difficulty = _text(raw.get("difficulty"), 20).lower()
        source_type = _text(raw.get("sourceType"), 20).lower()
        if recipient_id not in player_ids or award_type not in AWARD_TYPES or difficulty not in DIFFICULTIES:
            continue
        if source_type not in {"boss", "boe"}:
            source_type = "boss"
        requests = []
        seen_requests = set()
        for request in raw.get("requests") or []:
            normal = _normalise_request(request, player_ids)
            if normal and normal["playerId"] not in seen_requests:
                seen_requests.add(normal["playerId"])
                requests.append(normal)
        result.append({
            "id": _text(raw.get("id"), 80) or uuid.uuid4().hex[:16],
            "date": allocation_date,
            "raidKey": _text(raw.get("raidKey"), 80) or "venomous_abyss",
            "bossKey": _text(raw.get("bossKey"), 80) if source_type == "boss" else "boe",
            "difficulty": difficulty,
            "sourceType": source_type,
            "itemId": _text(raw.get("itemId"), 40),
            "itemName": _text(raw.get("itemName"), 160),
            "itemNameZh": _text(raw.get("itemNameZh"), 160),
            "itemTags": [_text(tag, 40) for tag in (raw.get("itemTags") or []) if _text(tag, 40)][:20],
            "recipientId": recipient_id,
            "awardType": award_type,
            "requests": requests,
            "notes": _text(raw.get("notes"), 1000),
            "createdAt": _text(raw.get("createdAt"), 40) or datetime.now().astimezone().isoformat(timespec="seconds"),
        })
    return sorted(result, key=lambda row: (row["date"], row["createdAt"]), reverse=True)


def _normalise_state(raw: Dict[str, Any]) -> Dict[str, Any]:
    roster = _normalise_roster((raw or {}).get("roster") or [])
    player_ids = {row["id"] for row in roster}
    return {
        "schemaVersion": 1,
        "roster": roster,
        "days": _normalise_days((raw or {}).get("days") or [], player_ids),
        "allocations": _normalise_allocations((raw or {}).get("allocations") or [], player_ids),
    }


def load_catalog() -> Dict[str, Any]:
    if not CATALOG_PATH.is_file():
        return {"schemaVersion": 1, "raids": []}
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8-sig"))


def _week_start(value: date_type) -> date_type:
    return value - timedelta(days=value.weekday())


def _previous_week_absences(state: Dict[str, Any], player_id: str, selected: date_type) -> int:
    start = _week_start(selected) - timedelta(days=7)
    end = start + timedelta(days=6)
    count = 0
    for day in state["days"]:
        current = date_type.fromisoformat(day["date"])
        if not (start <= current <= end) or current.weekday() not in SCHEDULED_WEEKDAYS:
            continue
        entry = next((row for row in day["attendance"] if row["playerId"] == player_id), None)
        if entry and entry["status"] in {"leave", "absent"}:
            count += 1
    return count


def _need_uses(state: Dict[str, Any], player_id: str, selected: date_type, difficulty: str) -> int:
    start = _week_start(selected)
    end = start + timedelta(days=6)
    return sum(
        1 for row in state["allocations"]
        if row["recipientId"] == player_id
        and row["awardType"] == "need"
        and row["difficulty"] == difficulty
        and start <= date_type.fromisoformat(row["date"]) <= end
    )


def eligibility_for(state: Dict[str, Any], selected_date: str, difficulty: str) -> List[Dict[str, Any]]:
    selected = _parse_date(selected_date)
    difficulty = _text(difficulty, 20).lower()
    if difficulty not in DIFFICULTIES:
        raise ValueError("无效的副本难度。")
    result = []
    for player in state["roster"]:
        absences = _previous_week_absences(state, player["id"], selected)
        uses = _need_uses(state, player["id"], selected, difficulty)
        eligible = player["active"] and absences < 2 and uses < 1
        reason = "可需求"
        if not player["active"]:
            reason = "非活动成员"
        elif absences >= 2:
            reason = f"上周请假/缺勤 {absences} 次，本周仅可贪婪"
        elif uses >= 1:
            reason = f"本周{DIFFICULTY_NAMES[difficulty]}难度已使用需求权"
        result.append({
            "playerId": player["id"],
            "needEligible": eligible,
            "reason": reason,
            "previousWeekAbsences": absences,
            "needUsesThisWeek": uses,
        })
    return result


def load_document(selected_date: str | None = None, difficulty: str = "heroic") -> Dict[str, Any]:
    selected_date = selected_date or date_type.today().isoformat()
    state = _load_state()
    return {
        "schemaVersion": 1,
        "rules": {
            "scheduledWeekdays": [4, 5, 6],
            "absenceThreshold": 2,
            "needLimitPerDifficultyPerWeek": 1,
            "awardTypes": ["need", "greed", "transmog", "alt"],
        },
        "catalog": load_catalog(),
        "state": state,
        "eligibility": eligibility_for(state, selected_date, difficulty),
        "selectedDate": selected_date,
        "difficulty": difficulty,
    }


def save_setup(payload: Dict[str, Any]) -> Dict[str, Any]:
    existing = _load_state()
    candidate = {
        "schemaVersion": 1,
        "roster": payload.get("roster") or [],
        "days": payload.get("days") or [],
        "allocations": existing["allocations"],
    }
    state = _normalise_state(candidate)
    _save_state(state)
    return {"ok": True, "rosterCount": len(state["roster"]), "dayCount": len(state["days"])}


def add_allocation(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = _load_state()
    player_ids = {row["id"] for row in state["roster"]}
    normalised = _normalise_allocations([payload], player_ids)
    if not normalised:
        raise ValueError("分配记录缺少有效的日期、难度、获奖玩家或分配类型。")
    allocation = normalised[0]
    if not allocation["itemName"] and not allocation["itemNameZh"]:
        raise ValueError("请选择装备，或填写 BOE 装备名称。")
    if allocation["sourceType"] == "boss" and not allocation["bossKey"]:
        raise ValueError("Boss 掉落必须选择对应 Boss。")
    if allocation["awardType"] == "need":
        eligibility = next(
            row for row in eligibility_for(state, allocation["date"], allocation["difficulty"])
            if row["playerId"] == allocation["recipientId"]
        )
        if not eligibility["needEligible"]:
            raise ValueError(eligibility["reason"])
    state["allocations"].append(allocation)
    _save_state(state)
    return {"ok": True, "allocation": copy.deepcopy(allocation)}


def delete_allocation(allocation_id: str) -> Dict[str, Any]:
    state = _load_state()
    before = len(state["allocations"])
    state["allocations"] = [row for row in state["allocations"] if row["id"] != allocation_id]
    if len(state["allocations"]) == before:
        raise ValueError("分配记录不存在。")
    _save_state(state)
    return {"ok": True, "id": allocation_id}
