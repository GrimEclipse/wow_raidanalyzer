import hashlib
import json
from typing import Any, Dict, Iterable


ANALYSIS_DOCUMENT_TYPE = "wow-raid-analysis"
ANALYSIS_SCHEMA_VERSION = 1
CAPABILITY_SCHEMA_VERSION = 1


_CAPABILITY_RENDERERS = {
    "wipe": "generic-wipe",
    "avoidable": "generic-avoidable",
    "interrupts": "generic-interrupts",
    "dispels": "generic-dispels",
    "mistakes": "mistake-tracker",
    "verdict": "mistake-verdict",
    "replay": "field-audit",
}


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


def _has_rows(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_has_rows(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return bool(value)
    return value is not None and value is not False


def _has_field_audit(data: dict) -> bool:
    for fight in data.get("page1_wipeAnalysis") or []:
        crown = (fight or {}).get("crownOfTheCosmos") or {}
        if crown.get("fieldAudit"):
            return True
    return False


def _capability(enabled: bool, renderer: str) -> dict:
    return {"enabled": bool(enabled), "renderer": renderer}


def infer_analysis_capabilities(result: Dict[str, Any]) -> dict:
    """Build the canonical UI capability map while accepting legacy boss output."""
    meta = result.get("meta") or {}
    data = result.get("data") or {}
    features = meta.get("features") or {}
    boss_key = str(meta.get("bossKey") or "")

    has_mistakes = (
        _has_rows(data.get("page3_courtBoard"))
        or _has_rows(data.get("page4_finalVerdict"))
        or features.get("finalVerdict") is True
    )
    has_avoidable = _has_rows(data.get("page2_avoidableBoard")) or _has_rows(data.get("page2_glaiveBoard"))
    dispel_analysis = data.get("page3_dispelAnalysis")
    has_dispels = features.get("dispels") is True or (
        isinstance(dispel_analysis, dict)
        and dispel_analysis.get("enabled") is not False
        and _has_rows(dispel_analysis.get("fights") or dispel_analysis.get("summary"))
    )
    if "interrupts" in features:
        has_interrupts = features.get("interrupts") is not False
    else:
        has_interrupts = (
            boss_key == "midnight_falls"
            or _has_rows(data.get("page3_interruptAnalysis"))
            or _has_rows(data.get("page2_interruptBoard"))
        )

    capabilities = {
        "wipe": _capability(
            "page1_wipeAnalysis" in data,
            _CAPABILITY_RENDERERS["wipe"],
        ),
        "avoidable": _capability(
            has_avoidable or has_mistakes,
            "mistake-tracker" if has_mistakes else _CAPABILITY_RENDERERS["avoidable"],
        ),
        "interrupts": _capability(has_interrupts, _CAPABILITY_RENDERERS["interrupts"]),
        "dispels": _capability(has_dispels, _CAPABILITY_RENDERERS["dispels"]),
        "mistakes": _capability(has_mistakes, _CAPABILITY_RENDERERS["mistakes"]),
        "verdict": _capability(
            has_mistakes and (
                "page4_finalVerdict" in data
                or features.get("finalVerdict") is True
            ),
            _CAPABILITY_RENDERERS["verdict"],
        ),
        "replay": _capability(_has_field_audit(data), _CAPABILITY_RENDERERS["replay"]),
    }

    explicit = meta.get("capabilities") or {}
    for key, value in explicit.items():
        if isinstance(value, bool):
            capabilities[key] = _capability(value, _CAPABILITY_RENDERERS.get(key, key))
        elif isinstance(value, dict):
            base = capabilities.get(key, _capability(False, _CAPABILITY_RENDERERS.get(key, key)))
            capabilities[key] = {**base, **value}
            capabilities[key]["enabled"] = bool(capabilities[key].get("enabled"))
    return capabilities


def build_mistake_tracker_contract(result: Dict[str, Any], capabilities: dict) -> dict:
    meta = result.get("meta") or {}
    court_config = meta.get("courtConfig") or {}
    explicit = meta.get("mistakeTracker") or {}
    tank_multiplier = court_config.get("verdictTankMultiplier", 1.0)
    contract = {
        "schemaVersion": 1,
        "enabled": bool((capabilities.get("mistakes") or {}).get("enabled")),
        "pointsPerUnit": court_config.get("verdictPointsPerCount", 10),
        "roleMultipliers": {"tank": tank_multiplier},
        "definitions": [],
    }
    contract.update(explicit)
    contract["enabled"] = bool(contract.get("enabled"))
    contract["definitions"] = list(contract.get("definitions") or [])
    return contract


def apply_analysis_contract(result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(result, dict):
        raise TypeError("分析结果必须是 JSON 对象。")
    result.setdefault("documentType", ANALYSIS_DOCUMENT_TYPE)
    result.setdefault("schemaVersion", ANALYSIS_SCHEMA_VERSION)
    meta = result.setdefault("meta", {})
    identity = build_analysis_identity(result)
    meta["analysisIdentity"] = identity
    meta["analysisId"] = identity["key"]
    capabilities = infer_analysis_capabilities(result)
    meta["capabilitySchemaVersion"] = CAPABILITY_SCHEMA_VERSION
    meta["capabilities"] = capabilities
    meta["mistakeTracker"] = build_mistake_tracker_contract(result, capabilities)
    return result
