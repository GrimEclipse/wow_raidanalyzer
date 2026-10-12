"""Declarative skill rulings for S2 mythic dungeon samples.

Loads a rulings JSON file (keyed by dungeon -> boss context -> spell id) and
merges it into an exported mythic-dungeon sample document.  All functions are
pure and dependency-free (constitution VI); failures degrade gracefully
(spec FR-4).  Contract: specs/001-s2-key-skills/contracts/document-delta.md.
"""

from __future__ import annotations

import json
from pathlib import Path

VALID_CATEGORIES = ("key", "trash", "unreviewed")


def _boss_context(row: dict) -> str:
    encounter = row.get("encounterId") or 0
    return f"encounter:{encounter}" if encounter else "trash"


def _parse_rulings(payload: object) -> tuple[dict, int]:
    """Validate a raw rulings payload.

    Returns ``(rulings, invalid_count)`` where ``invalid_count`` counts raw
    entries rejected by validation rules V1-V3 (bad category, ``key`` without
    evidence, bad spell id, malformed groups).  Well-formed groups for
    dungeons a given sample does not use are simply unused, never invalid.
    """
    if not isinstance(payload, dict):
        return {}, 0
    rulings: dict = {}
    invalid = 0
    for dungeon_key, contexts in payload.items():
        if not isinstance(dungeon_key, str) or not dungeon_key:
            invalid += 1
            continue
        if not isinstance(contexts, dict):
            invalid += 1
            continue
        dungeon: dict = {}
        for context_key, spells in contexts.items():
            if not isinstance(context_key, str) or not isinstance(spells, dict):
                invalid += 1
                continue
            context: dict = {}
            for spell_key, entry in spells.items():
                try:
                    spell_id = int(spell_key)
                except (TypeError, ValueError):
                    invalid += 1  # V3
                    continue
                if spell_id <= 0 or not isinstance(entry, dict):
                    invalid += 1  # V3
                    continue
                category = entry.get("category")
                if category not in VALID_CATEGORIES:
                    invalid += 1  # V1
                    continue
                evidence = entry.get("evidence") or []
                if category == "key" and not evidence:
                    invalid += 1  # V2
                    continue
                cleaned: dict = {"category": category}
                if evidence:
                    cleaned["evidence"] = evidence
                notes = entry.get("notes")
                if notes:
                    cleaned["notes"] = str(notes)
                context[str(spell_id)] = cleaned
            if context:
                dungeon[context_key] = context
        if dungeon:
            rulings[dungeon_key] = dungeon
    return rulings, invalid


def _read_rulings(path: str) -> tuple[dict, int, str | None]:
    """Read + validate a rulings file.  Never raises (V5 graceful degradation)."""
    file = Path(path)
    if not file.is_file():
        return {}, 0, "rulings file not found"
    try:
        payload = json.loads(file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {}, 0, f"rulings file invalid JSON: {exc}"
    if not isinstance(payload, dict):
        return {}, 0, "rulings file invalid schema: top level must be an object"
    rulings, invalid = _parse_rulings(payload)
    return rulings, invalid, None


def load_rulings(path: str) -> tuple[dict, str | None]:
    """Load and validate a rulings file.

    Returns ``(rulings, error)``.  On any load/validation failure the rulings
    dict is empty and ``error`` carries a human-readable reason (V5).
    """
    rulings, _invalid, error = _read_rulings(path)
    return rulings, error


def apply_rulings(document: dict, path: str) -> dict:
    """Merge rulings into a mythic-dungeon sample document (in place, returned).

    Candidates are matched by ``(dungeon key, boss context, spell id)``; the
    matched row gains ``ruling`` plus the pre-existing ``include``/``notes``
    fields (contract: contracts/document-delta.md).  When nothing can be
    applied the document keeps its existing ``skillSelection`` behaviour and
    gains a ``rulingsError`` reason (FR-4).  S1 documents without
    ``skillCandidates``/``skillSelection`` are untouched (FR-6).
    """
    candidates = document.get("skillCandidates")
    selection = document.get("skillSelection")
    if not isinstance(candidates, list) or not isinstance(selection, dict):
        return document  # S1 or non-sample document: zero impact

    rulings, invalid, error = _read_rulings(path)
    if error is not None:
        selection["rulingsError"] = error
        return document  # keep needs-review status: page falls back

    dungeon_key = (document.get("dungeon") or {}).get("key") or ""
    dungeon_rulings = rulings.get(dungeon_key) or {}

    applied = 0
    for row in candidates:
        if not isinstance(row, dict):
            continue
        spell_ruling = (dungeon_rulings.get(_boss_context(row)) or {}).get(
            str(row.get("spellId"))
        )
        if spell_ruling is None:
            continue
        category = spell_ruling["category"]
        row["ruling"] = spell_ruling
        row["include"] = True if category == "key" else False if category == "trash" else None
        row["notes"] = spell_ruling.get("notes") or row.get("notes") or ""
        applied += 1

    selection["rulings"] = {"file": str(path), "applied": applied, "skipped": invalid}
    if applied > 0:
        selection["status"] = "curated"
        selection.pop("rulingsError", None)
    else:
        selection["rulingsError"] = "no ruling matched any candidate for this dungeon"
    return document
