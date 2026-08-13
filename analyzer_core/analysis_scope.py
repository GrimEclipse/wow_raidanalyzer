"""Opt-in analysis scope used by the isolated single-fight workflow.

The legacy report analyzers keep their existing public interface.  A context
variable narrows only the current worker thread, so a single-fight request can
reuse the exact boss rules without changing a full-report job running nearby.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class AnalysisScope:
    report_id: str
    fight_id: int


_CURRENT_SCOPE: ContextVar[AnalysisScope | None] = ContextVar(
    "mythic_analyzer_analysis_scope", default=None
)


@contextmanager
def single_fight_scope(report_id: str, fight_id: int):
    scope = AnalysisScope(str(report_id).strip(), int(fight_id))
    token = _CURRENT_SCOPE.set(scope)
    try:
        yield scope
    finally:
        _CURRENT_SCOPE.reset(token)


def filter_fights(report_id: str, fights: Iterable[dict]) -> list[dict]:
    rows = list(fights)
    scope = _CURRENT_SCOPE.get()
    if scope is None:
        return rows
    if str(report_id).strip() != scope.report_id:
        return []
    return [row for row in rows if int(row.get("id") or 0) == scope.fight_id]
