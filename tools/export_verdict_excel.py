from __future__ import annotations

from copy import copy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


MECHANIC_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("waterOutliers", "放水未集中"),
    ("p15AvoidableDeaths", "转阶段死亡"),
    ("passageCliffMistakes", "过场失误"),
    ("p1SilverArrowMissedFights", "P1银锋射怪失误"),
    ("p1SilverArrowDeaths", "P1银锋高伤致死"),
    ("missedShadows", "P2拉弓未中幻影"),
    ("collapsingVoidSnapAiming", "崩裂甩狙"),
    ("gravityLineViolation", "重力坍缩致死违规"),
    ("voidGraspHealingLow", "空虚之握治疗不足"),
    ("tankRiftSlashFailure", "裂隙换坦失误"),
    ("voreluthVulnerabilityFade", "P1龌勒易伤"),
)

HEADERS: List[str] = (
    ["ID", "职责", "判定次数"]
    + [label for _, label in MECHANIC_COLUMNS]
    + ["申诉次数", "原因", "追加次数", "追加原因", "总计"]
)

COL_RECOGNITION = 3
COL_APPEAL = 3 + len(MECHANIC_COLUMNS) + 1
COL_ADDITIONAL = COL_APPEAL + 2
COL_TOTAL = COL_ADDITIONAL + 2

HEADER_FONT = Font(name="Microsoft YaHei", size=11, bold=True, color="FFF9FAFB")
HEADER_FILL = PatternFill("solid", fgColor="FF1F2937")
DATA_FONT = Font(name="Microsoft YaHei", size=10)
THIN_SIDE = Side(style="thin")
CELL_BORDER = Border(left=THIN_SIDE, right=THIN_SIDE, top=THIN_SIDE, bottom=THIN_SIDE)
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)

COLUMN_WIDTHS = {
    "A": 16.0,
    "B": 14.0,
    "C": 10.0,
    **{get_column_letter(4 + i): 13.0 for i in range(len(MECHANIC_COLUMNS))},
    get_column_letter(COL_APPEAL): 10.0,
    get_column_letter(COL_APPEAL + 1): 36.0,
    get_column_letter(COL_ADDITIONAL): 10.0,
    get_column_letter(COL_ADDITIONAL + 1): 36.0,
    get_column_letter(COL_TOTAL): 10.0,
}


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        if x is None:
            return default
        return int(x)
    except Exception:
        return default


def _next_available_path(path: Path) -> Path:
    """若文件存在，按 (2)/(3)... 递增追加到文件名后。"""
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    i = 2
    while True:
        candidate = parent / f"{stem}({i}){suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def _apply_header_style(cell) -> None:
    cell.font = copy(HEADER_FONT)
    cell.fill = copy(HEADER_FILL)
    cell.alignment = copy(CENTER)
    cell.border = copy(CELL_BORDER)


def _apply_data_style(cell, *, center: bool = False) -> None:
    cell.font = copy(DATA_FONT)
    cell.alignment = copy(CENTER if center else LEFT)
    cell.border = copy(CELL_BORDER)


def _mechanic_value(breakdown: Dict[str, Any], key: str) -> int | None:
    count = _safe_int((breakdown or {}).get(key), 0)
    return count if count else None


def export_verdict_excel(payload: Dict[str, Any], target_dir: str | Path, boss_name: str = "宇宙之冕") -> Path:
    """
    生成终审 Excel（.xlsx）并写入磁盘。

    payload:
    - date: YYYY-MM-DD
    - players: [{
        name, rolesText, recognitionCount, breakdown,
        appealAcquittalCount, appealAcquittalReasons,
        additionalCount, additionalReasons
      }, ...]
    """
    date = str(payload.get("date") or datetime.now().date())
    players_raw: Sequence[Dict[str, Any]] = payload.get("players") or []

    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = _next_available_path(target_dir / f"智力表_{boss_name}_{date}.xlsx")

    wb = Workbook()
    ws = wb.active
    ws.title = f"{boss_name}_{date.replace('-', '')}"

    ws.row_dimensions[1].height = 30.0
    for col_idx, title in enumerate(HEADERS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=title)
        _apply_header_style(cell)

    for col_letter, width in COLUMN_WIDTHS.items():
        ws.column_dimensions[col_letter].width = width

    for row_idx, player in enumerate(players_raw, start=2):
        breakdown = player.get("breakdown") or {}
        recognition = _safe_int(player.get("recognitionCount"), 0)
        appeal_count = _safe_int(player.get("appealAcquittalCount"), 0)
        additional_count = _safe_int(player.get("additionalCount"), 0)

        values: List[Any] = [
            str(player.get("name") or ""),
            str(player.get("rolesText") or ""),
            recognition,
            *[_mechanic_value(breakdown, key) for key, _ in MECHANIC_COLUMNS],
            appeal_count or None,
            str(player.get("appealAcquittalReasons") or "") or None,
            additional_count or None,
            str(player.get("additionalReasons") or "") or None,
        ]

        for col_idx, value in enumerate(values, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            _apply_data_style(cell, center=col_idx not in (COL_APPEAL + 1, COL_ADDITIONAL + 1))

        total_cell = ws.cell(
            row=row_idx,
            column=COL_TOTAL,
            value=(
                f"=({get_column_letter(COL_RECOGNITION)}{row_idx}"
                f"-{get_column_letter(COL_APPEAL)}{row_idx}"
                f"+{get_column_letter(COL_ADDITIONAL)}{row_idx})*10"
            ),
        )
        _apply_data_style(total_cell, center=True)

    wb.save(out_path)
    return out_path
