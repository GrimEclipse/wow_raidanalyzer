import hashlib
import json
from typing import Any, Dict, Iterable


ANALYSIS_DOCUMENT_TYPE = "wow-raid-analysis"
ANALYSIS_SCHEMA_VERSION = 1


def _first_fight_date(data: dict) -> str:
    fights = data.get("page1_wipeAnalysis") or []
    for fight in fights:
        date = str((fight or {}).get("date") or "").strip()
        if date:
            return date
    return ""


def _normalized_reports(values: Iterable[Any]) -> list:
    return sorted({str(value).strip() for value in (values or []) if str(value).strip()})


def build_analysis_identity(result: Dict[str, Any]) -> dict:
    meta = result.get("meta") or {}
    data = result.get("data") or {}
    identity = {
        "version": str(meta.get("version") or "unknown-version").strip(),
        "raidKey": str(meta.get("raidKey") or "unknown-raid").strip(),
        "bossKey": str(meta.get("bossKey") or "unknown-boss").strip(),
        "reports": _normalized_reports(meta.get("analyzedReports") or []),
        "date": str(meta.get("progressDate") or _first_fight_date(data) or "unknown-date").strip(),
    }
    canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    identity["key"] = "/".join([
        identity["version"],
        identity["raidKey"],
        identity["bossKey"],
        digest,
    ])
    return identity


def apply_analysis_contract(result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(result, dict):
        raise TypeError("分析结果必须是 JSON 对象。")
    result.setdefault("documentType", ANALYSIS_DOCUMENT_TYPE)
    result.setdefault("schemaVersion", ANALYSIS_SCHEMA_VERSION)
    meta = result.setdefault("meta", {})
    identity = build_analysis_identity(result)
    meta["analysisIdentity"] = identity
    meta["analysisId"] = identity["key"]
    return result
