"""Honest fallback returned for specializations without an implementation."""

from __future__ import annotations


def analyze_comparison(primary: dict, benchmark: dict, options: dict | None = None) -> dict:
    actor = primary.get("actor") or {}
    return {
        "schemaVersion": 1,
        "kind": "single-fight-spec-comparison",
        "supportStatus": "stub",
        "identity": {
            "class": actor.get("subType") or "Unknown",
            "spec": primary.get("spec") or "Unknown",
        },
        "message": "该专精已经生成支持存根，但尚未配置 Buff、资源、爆发窗口和施法优先级。",
        "requiredEvidence": ["Casts", "Buffs", "Resources", "CombatantInfo"],
        "nextImplementation": {
            "plugin": "spec_plugins/<class>/<spec>.py",
            "sections": ["buffCoverage", "resourceLedger", "burstWindows", "castSequences"],
        },
        "players": {"primary": primary.get("identity"), "benchmark": benchmark.get("identity")},
    }
