"""Generic evidence -> assignment -> verdict evaluator for boss court rules."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable


VALID_MODES = {"direct", "assignment", "review"}


def validate_court_profile(profile: dict) -> dict:
    keys = set()
    for rule in profile.get("rules") or []:
        key = str(rule.get("key") or "").strip()
        if not key or key in keys:
            raise ValueError(f"开庭规则 key 缺失或重复：{key or '<empty>'}")
        keys.add(key)
        if rule.get("mode") not in VALID_MODES:
            raise ValueError(f"{key} 使用了未知开庭模式。")
        if rule.get("mode") == "assignment" and not rule.get("assignmentKey"):
            raise ValueError(f"{key} 是职责判定规则，但没有 assignmentKey。")
    return profile


def evaluate_court_evidence(
    profile: dict,
    evidence_rows: Iterable[dict],
    *,
    assignments: dict | None = None,
    options: dict | None = None,
) -> dict:
    """Evaluate normalized evidence without mutating the underlying facts.

    Evidence rows remain visible even when counting is disabled, a required
    assignment is absent, or the mechanism still needs manual review.
    """

    validate_court_profile(profile)
    assignments = assignments or {}
    options = options or {}
    definitions = {
        rule["key"]: rule
        for rule in profile.get("rules") or []
    }
    cases = []
    board = defaultdict(list)
    for raw in evidence_rows or []:
        rule_key = str(raw.get("ruleKey") or "")
        rule = definitions.get(rule_key)
        if not rule:
            continue
        option_key = rule.get("countOption")
        count_enabled = bool(
            options.get(option_key, rule.get("defaultCountEnabled", False))
            if option_key
            else rule.get("defaultCountEnabled", False)
        )
        counted = False
        status = "evidence_only"
        reason = ""
        if not raw.get("confirmed"):
            reason = "证据链尚未确认，只展示不计数。"
        elif not count_enabled:
            reason = "该项目当前配置为不统计。"
        elif rule["mode"] == "direct":
            counted = True
            status = "counted"
            reason = "直接失败事件已确认。"
        elif rule["mode"] == "assignment":
            assignment = assignments.get(rule["assignmentKey"])
            if not assignment:
                status = "missing_assignment"
                reason = "缺少本轮职责预设，不能仅凭位置或命中结果定罪。"
            elif raw.get("assignmentCompliant") is False:
                counted = True
                status = "counted"
                reason = "证据与本轮职责预设交叉后确认不合规。"
            else:
                status = "compliant"
                reason = "已有职责预设，但当前证据未确认违规。"
        elif raw.get("reviewDecision") == "count":
            counted = True
            status = "counted"
            reason = "人工复核已确认计入。"
        else:
            status = "needs_review"
            reason = "机制需要人工复核或校准，暂不自动计数。"

        case = {
            **raw,
            "ruleKey": rule_key,
            "label": rule.get("label") or rule_key,
            "mode": rule["mode"],
            "severityUnits": float(rule.get("severityUnits") or 1),
            "countEnabled": count_enabled,
            "counted": counted,
            "status": status,
            "verdictReason": reason,
        }
        cases.append(case)
        board[rule_key].append(case)
    return {
        "schemaVersion": 1,
        "bossKey": profile.get("bossKey"),
        "definitions": list(definitions.values()),
        "cases": cases,
        "board": dict(board),
    }
