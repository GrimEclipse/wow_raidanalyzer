"""Shared next-season specialization preference store."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "scoreboard" / "recruitment.db"
CATALOG_PATH = ROOT / "assets" / "specs" / "catalog.json"
_LOCK = threading.RLock()


def load_catalog() -> Dict[str, Any]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(DB_PATH))
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS recruitment_choices (
            user_id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            player_name TEXT NOT NULL,
            primary_spec_id INTEGER NOT NULL,
            secondary_spec_ids TEXT NOT NULL,
            notes TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.commit()
    return connection


def _spec_map() -> Dict[int, Dict[str, Any]]:
    return {int(row["id"]): row for row in load_catalog()["specs"]}


def _clean_text(value: Any, field_name: str, maximum: int, required: bool = False) -> str:
    text = " ".join(str(value or "").strip().split())
    if required and not text:
        raise ValueError(f"请填写{field_name}。")
    if len(text) > maximum:
        raise ValueError(f"{field_name}不能超过 {maximum} 个字符。")
    return text


def _serialize(row: sqlite3.Row, specs: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    primary_id = int(row["primary_spec_id"])
    alternatives = [int(value) for value in json.loads(row["secondary_spec_ids"])]
    primary = specs[primary_id]
    return {
        "userId": int(row["user_id"]),
        "username": row["username"],
        "playerName": row["player_name"],
        "primarySpecId": primary_id,
        "secondarySpecIds": alternatives,
        "notes": row["notes"],
        "updatedAt": row["updated_at"],
        "primaryRole": primary["role"],
        "primaryClassKey": primary["classKey"],
    }


def load_document(current_user: Dict[str, Any]) -> Dict[str, Any]:
    catalog = load_catalog()
    specs = {int(row["id"]): row for row in catalog["specs"]}
    role_order = {row["key"]: int(row["order"]) for row in catalog["roles"]}
    with _LOCK, closing(_connect()) as connection:
        rows = connection.execute("SELECT * FROM recruitment_choices").fetchall()
    entries = [_serialize(row, specs) for row in rows if int(row["primary_spec_id"]) in specs]
    entries.sort(key=lambda row: (
        role_order.get(row["primaryRole"], 99),
        row["primaryClassKey"],
        row["playerName"].casefold(),
    ))
    counts = {role["key"]: 0 for role in catalog["roles"]}
    composition_counts = {group["key"]: 0 for group in catalog["compositionGroups"]}
    composition_groups = {group["key"]: group for group in catalog["compositionGroups"]}
    melee_ids = set(composition_groups["melee"]["specIds"])
    ranged_ids = set(composition_groups["ranged"]["specIds"])
    present_classes = set()
    for entry in entries:
        counts[entry["primaryRole"]] += 1
        if entry["primaryRole"] == "tank":
            composition_counts["tank"] += 1
        elif entry["primarySpecId"] in melee_ids:
            composition_counts["melee"] += 1
        elif entry["primarySpecId"] in ranged_ids:
            composition_counts["ranged"] += 1
        present_classes.add(entry["primaryClassKey"])
    return {
        "schemaVersion": 1,
        "catalog": catalog,
        "entries": entries,
        "summary": {
            "total": len(entries),
            "roleCounts": counts,
            "compositionCounts": composition_counts,
            "missingClassKeys": [row["key"] for row in catalog["classes"] if row["key"] not in present_classes],
        },
        "currentUser": {
            "id": int(current_user["id"]),
            "username": current_user["username"],
            "isAdmin": bool(current_user.get("isAdmin")),
        },
    }


def save_choice(current_user: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    specs = _spec_map()
    try:
        primary_id = int(payload.get("primarySpecId"))
    except (TypeError, ValueError) as error:
        raise ValueError("请选择一个主选专精。") from error
    if primary_id not in specs:
        raise ValueError("主选专精不存在。")

    raw_alternatives = payload.get("secondarySpecIds") or []
    if not isinstance(raw_alternatives, list):
        raise ValueError("次选专精格式不正确。")
    if len(raw_alternatives) > 4:
        raise ValueError("次选专精最多添加 4 个。")
    alternatives = []
    for value in raw_alternatives:
        try:
            spec_id = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError("次选专精不存在。") from error
        if spec_id not in specs:
            raise ValueError("次选专精不存在。")
        if spec_id == primary_id or spec_id in alternatives:
            raise ValueError("主选与次选专精不能重复。")
        alternatives.append(spec_id)

    username = _clean_text(current_user.get("username"), "账号名", 80, required=True)
    player_name = _clean_text(payload.get("playerName") or username, "角色名", 32, required=True)
    notes = _clean_text(payload.get("notes"), "备注", 300)
    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _LOCK, closing(_connect()) as connection:
        connection.execute(
            """
            INSERT INTO recruitment_choices
                (user_id, username, player_name, primary_spec_id, secondary_spec_ids, notes, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                player_name = excluded.player_name,
                primary_spec_id = excluded.primary_spec_id,
                secondary_spec_ids = excluded.secondary_spec_ids,
                notes = excluded.notes,
                updated_at = excluded.updated_at
            """,
            (
                int(current_user["id"]), username, player_name, primary_id,
                json.dumps(alternatives, ensure_ascii=False), notes, updated_at,
            ),
        )
        connection.commit()
    return load_document(current_user)


def delete_choice(current_user: Dict[str, Any]) -> Dict[str, Any]:
    with _LOCK, closing(_connect()) as connection:
        connection.execute("DELETE FROM recruitment_choices WHERE user_id = ?", (int(current_user["id"]),))
        connection.commit()
    return load_document(current_user)
