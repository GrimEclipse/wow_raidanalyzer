"""Normalization helpers for Warcraft Logs report identifiers."""

from __future__ import annotations

import re
from urllib.parse import unquote


REPORT_CODE_PATTERN = r"[A-Za-z0-9]{16}"
_REPORT_URL_RE = re.compile(
    rf"(?:https?://)?(?:[A-Za-z0-9-]+\.)*warcraftlogs\.com/reports/({REPORT_CODE_PATTERN})",
    re.IGNORECASE,
)
_REPORT_PATH_RE = re.compile(rf"/reports/({REPORT_CODE_PATTERN})", re.IGNORECASE)
_RAW_CODE_RE = re.compile(rf"(?<![A-Za-z0-9])({REPORT_CODE_PATTERN})(?![A-Za-z0-9])")


def parse_wcl_report_ids(value, *, max_count: int | None = None) -> list[str]:
    """Extract WCL report IDs from raw codes, report URLs, or mixed input."""
    values = value if isinstance(value, (list, tuple, set)) else [value]
    codes: list[str] = []
    for raw in values:
        text = unquote(str(raw or "")).replace(r"\&", "&")
        url_matches = list(_REPORT_URL_RE.finditer(text))
        if not url_matches:
            url_matches = list(_REPORT_PATH_RE.finditer(text))
        matches = [(match.start(1), match.group(1)) for match in url_matches]
        matches.extend((match.start(1), match.group(1)) for match in _RAW_CODE_RE.finditer(text))
        codes.extend(code for _, code in sorted(matches))

    unique = list(dict.fromkeys(codes))
    if max_count is not None:
        return unique[:max(0, int(max_count))]
    return unique


def normalize_wcl_report_ids(value, *, max_count: int | None = None) -> str:
    """Return a comma-separated report ID string accepted by boss analyzers."""
    return ",".join(parse_wcl_report_ids(value, max_count=max_count))
