"""Local SQLite notebook for the scoreboard diary (no end-user JSON chore)."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parent
SCOREBOARD_DIR = ROOT / "scoreboard"
DB_PATH = SCOREBOARD_DIR / "notebook.db"
DATA_DIR = ROOT / "data"


def _connect() -> sqlite3.Connection:
    SCOREBOARD_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS days (
            date TEXT PRIMARY KEY,
            body TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def load_store() -> Dict[str, Any]:
    with _connect() as conn:
        rows = conn.execute("SELECT body FROM days ORDER BY date").fetchall()
    days = []
    for (body,) in rows:
        try:
            days.append(json.loads(body))
        except json.JSONDecodeError:
            continue
    return {"schemaVersion": 2, "days": days}


def save_store(store: Dict[str, Any]) -> Dict[str, Any]:
    days = store.get("days") or []
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    with _connect() as conn:
        conn.execute("DELETE FROM days")
        for day in days:
            date = str(day.get("date") or "").strip()
            if not date:
                continue
            day = dict(day)
            day["updatedAt"] = day.get("updatedAt") or now
            conn.execute(
                "INSERT OR REPLACE INTO days(date, body, updated_at) VALUES (?, ?, ?)",
                (date, json.dumps(day, ensure_ascii=False), day["updatedAt"]),
            )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('schemaVersion', ?)",
            (str(store.get("schemaVersion") or 2),),
        )
        conn.commit()
    return {"ok": True, "path": "scoreboard/notebook.db", "dayCount": len(days)}


def get_day(date: str) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute("SELECT body FROM days WHERE date = ?", (date,)).fetchone()
    if not row:
        return None
    return json.loads(row[0])


def put_day(date: str, day: Dict[str, Any]) -> Dict[str, Any]:
    day = dict(day)
    day["date"] = date
    day["updatedAt"] = day.get("updatedAt") or time.strftime("%Y-%m-%dT%H:%M:%S")
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO days(date, body, updated_at) VALUES (?, ?, ?)",
            (date, json.dumps(day, ensure_ascii=False), day["updatedAt"]),
        )
        conn.commit()
    return {"ok": True, "path": "scoreboard/notebook.db", "date": date}


def delete_day(date: str) -> Dict[str, Any]:
    with _connect() as conn:
        conn.execute("DELETE FROM days WHERE date = ?", (date,))
        conn.commit()
    return {"ok": True, "date": date}


def list_data_files() -> List[Dict[str, Any]]:
    try:
        from analyzer_core.wcl_paths import list_wcl_data_files, write_data_manifest

        files = list_wcl_data_files()
        write_data_manifest()
        return files
    except Exception:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        items = []
        for path in sorted(DATA_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            if path.name.lower() == "manifest.json":
                continue
            stat = path.stat()
            items.append({
                "path": f"data/{path.name}",
                "name": path.name,
                "label": path.name,
                "size": stat.st_size,
                "mtime": int(stat.st_mtime),
            })
        root_wcl = ROOT / "wcl_hardcore_api.json"
        if root_wcl.exists():
            stat = root_wcl.stat()
            items.append({
                "path": root_wcl.name,
                "name": root_wcl.name,
                "label": f"{root_wcl.name}（兼容默认）",
                "size": stat.st_size,
                "mtime": int(stat.st_mtime),
            })
        items.sort(key=lambda row: row["mtime"], reverse=True)
        return items


def latest_data_path() -> Optional[Path]:
    try:
        from analyzer_core.wcl_paths import iter_wcl_json_files

        files = list(iter_wcl_json_files())
        if files:
            return max(files, key=lambda p: p.stat().st_mtime)
    except Exception:
        pass
    candidates: List[Path] = [p for p in DATA_DIR.glob("*.json") if p.name.lower() != "manifest.json"]
    root_wcl = ROOT / "wcl_hardcore_api.json"
    if root_wcl.exists():
        candidates.append(root_wcl)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def read_latest_data() -> Optional[Dict[str, Any]]:
    path = latest_data_path()
    if not path:
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))
