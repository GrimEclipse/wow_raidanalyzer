"""WCL 复盘 JSON 路径约定。

单日志：data/wcl_<reportId>_<bossKey>_<开荒日YYYYMMDD>.json
  开荒日：本地 01:00 前归属前一天（例 7/12 19:00～7/13 00:59 → 20260712）
多日志：data/wcl_multi_<bossKey>_<导出日YYYYMMDD>.json
  导出日按中国时区当天，同天多次运行覆盖
兼容：根目录 wcl_hardcore_api.json 仍可作为默认/调试产物。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Union

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
LEGACY_WCL_JSON = DATA_DIR / "wcl_hardcore_api.json"
MANIFEST_PATH = DATA_DIR / "manifest.json"

CN_TZ = timezone(timedelta(hours=8))
WCL_NAME_RE = re.compile(r"^wcl_.+\.json$", re.IGNORECASE)
DATE_SUFFIX_RE = re.compile(r"_(\d{8})$")


def parse_report_ids(report_ids: Union[str, List[str], None]) -> List[str]:
    if isinstance(report_ids, list):
        return [str(part).strip() for part in report_ids if str(part).strip()]
    return [part.strip() for part in str(report_ids or "").replace(" ", "").split(",") if part.strip()]


def to_raid_night_date(dt: datetime):
    """开荒日：01:00 前归属前一天。"""
    local = dt.astimezone(CN_TZ) if dt.tzinfo else dt.replace(tzinfo=CN_TZ)
    if local.hour < 1:
        return (local - timedelta(days=1)).date()
    return local.date()


def export_date_tag(now: Optional[datetime] = None) -> str:
    """导出当天标签（中国时区 YYYYMMDD），供 multi 同天覆盖。"""
    current = now or datetime.now(CN_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=CN_TZ)
    else:
        current = current.astimezone(CN_TZ)
    return current.strftime("%Y%m%d")


def raid_night_date_tag(dt: datetime) -> str:
    return to_raid_night_date(dt).strftime("%Y%m%d")


def parse_fight_datetime(fight: dict) -> Optional[datetime]:
    raw = fight.get("startDateTime") or fight.get("startTimeIso")
    if raw:
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            return parsed.astimezone(CN_TZ) if parsed.tzinfo else parsed.replace(tzinfo=CN_TZ)
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(str(raw), fmt).replace(tzinfo=CN_TZ)
            except ValueError:
                continue
    date = fight.get("date")
    clock = fight.get("startClock") or "00:00"
    if date:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(f"{date} {clock}", fmt).replace(tzinfo=CN_TZ)
            except ValueError:
                continue
        try:
            return datetime.strptime(str(date), "%Y-%m-%d").replace(tzinfo=CN_TZ)
        except ValueError:
            return None
    return None


def infer_log_date_tag(result: Optional[dict]) -> str:
    """从分析结果推断单日志开荒日；无法推断时退回导出日。"""
    wipes = ((result or {}).get("data") or {}).get("page1_wipeAnalysis") or []
    tags = []
    for fight in wipes:
        dt = parse_fight_datetime(fight)
        if dt is not None:
            tags.append(raid_night_date_tag(dt))
            continue
        date = str(fight.get("date") or "").replace("-", "")
        if re.fullmatch(r"\d{8}", date):
            tags.append(date)
    if tags:
        return min(tags)
    return export_date_tag()


def default_wcl_output_path(
    report_ids: Union[str, List[str], None],
    boss_key: str,
    *,
    date_tag: Optional[str] = None,
    result: Optional[dict] = None,
) -> Path:
    """按日志数量 + 日期标签生成默认输出路径。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ids = parse_report_ids(report_ids)
    boss = (boss_key or "unknown_boss").strip() or "unknown_boss"
    if len(ids) >= 2:
        tag = date_tag or export_date_tag()
        return DATA_DIR / f"wcl_multi_{boss}_{tag}.json"
    if len(ids) == 1:
        tag = date_tag or (infer_log_date_tag(result) if result is not None else export_date_tag())
        return DATA_DIR / f"wcl_{ids[0]}_{boss}_{tag}.json"
    return LEGACY_WCL_JSON


def resolve_wcl_output_path(
    result: Optional[dict] = None,
    output_path: Optional[Union[str, Path]] = None,
    report_ids: Union[str, List[str], None] = None,
    boss_key: Optional[str] = None,
) -> Path:
    """写出时解析最终路径；显式 output_path 优先。"""
    if output_path:
        return Path(output_path)
    meta = (result or {}).get("meta") or {}
    ids = parse_report_ids(report_ids if report_ids is not None else meta.get("analyzedReports"))
    boss = (boss_key or meta.get("bossKey") or "unknown_boss").strip() or "unknown_boss"
    return default_wcl_output_path(ids, boss, result=result)


def to_web_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


def _file_label(path: Path) -> str:
    name = path.name
    if name == "wcl_hardcore_api.json":
        return "wcl_hardcore_api.json（兼容默认）"
    stem = path.stem
    date = None
    match = DATE_SUFFIX_RE.search(stem)
    if match:
        date = match.group(1)
        stem = stem[: match.start()]
    if stem.startswith("wcl_multi_"):
        boss = stem[len("wcl_multi_"):]
        label = f"多日志 · {boss}"
    elif stem.startswith("wcl_"):
        body = stem[4:]
        report_id, sep, boss = body.partition("_")
        label = f"{report_id} · {boss}" if sep else body
    else:
        label = stem
    if date:
        label = f"{label} · {date[:4]}-{date[4:6]}-{date[6:]}"
    return label


def iter_wcl_json_files() -> Iterable[Path]:
    if LEGACY_WCL_JSON.is_file():
        yield LEGACY_WCL_JSON
    if DATA_DIR.is_dir():
        for path in sorted(DATA_DIR.glob("wcl_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            if path.name.lower() == "manifest.json":
                continue
            if WCL_NAME_RE.match(path.name):
                yield path


def list_wcl_data_files() -> List[dict]:
    files = []
    seen = set()
    for path in iter_wcl_json_files():
        web = to_web_path(path)
        if web in seen:
            continue
        seen.add(web)
        stat = path.stat()
        files.append({
            "path": web,
            "name": path.name,
            "label": _file_label(path),
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
        })
    files.sort(key=lambda row: row["mtime"], reverse=True)
    return files


def write_data_manifest(extra_path: Optional[Path] = None) -> Path:
    """写出 data/manifest.json，供静态/离线包列举可用 JSON。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    files = list_wcl_data_files()
    if extra_path and extra_path.is_file():
        web = to_web_path(extra_path)
        if not any(row["path"] == web for row in files):
            stat = extra_path.stat()
            files.insert(0, {
                "path": web,
                "name": extra_path.name,
                "label": _file_label(extra_path),
                "size": stat.st_size,
                "mtime": int(stat.st_mtime),
            })
            files.sort(key=lambda row: row["mtime"], reverse=True)
    payload = {
        "schemaVersion": 1,
        "files": files,
    }
    MANIFEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return MANIFEST_PATH
