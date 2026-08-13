"""Central, roster-aware catalog for player timeline evidence."""

from __future__ import annotations

import json
import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Iterable


CATALOG_PATH = Path(__file__).resolve().parents[1] / "config" / "player_abilities.json"


@lru_cache(maxsize=1)
def load_player_ability_catalog() -> dict:
    document = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    abilities = document.get("abilities")
    if not isinstance(abilities, list):
        raise RuntimeError("player_abilities.json 缺少 abilities 数组。")
    keys: set[str] = set()
    ids: dict[tuple[int, str], str] = {}
    for row in abilities:
        key = str(row.get("key") or "").strip()
        spell_ids = [int(value) for value in row.get("ids") or []]
        if not key or not spell_ids:
            raise RuntimeError("职业技能目录存在缺少 key/ids 的项目。")
        if key in keys:
            raise RuntimeError(f"职业技能目录 key 重复：{key}")
        keys.add(key)
        for spell_id in spell_ids:
            identity = (spell_id, str(row.get("event") or "cast"))
            owner = ids.get(identity)
            if owner and owner != key:
                raise RuntimeError(f"职业技能目录 ID 重复：{spell_id}（{owner} / {key}）")
            ids[identity] = key
    return document


def normalize_roster(roster: Iterable[dict]) -> list[dict]:
    rows = []
    for row in roster or []:
        actor_id = int(row.get("id") or 0)
        class_name = str(row.get("class") or row.get("subType") or "").strip()
        spec_name = str(row.get("specEnglish") or row.get("spec") or "").strip()
        if actor_id and class_name:
            rows.append({**row, "id": actor_id, "class": class_name, "spec": spec_name})
    return rows


def abilities_for_roster(roster: Iterable[dict]) -> dict:
    """Resolve once from composition; consumers then query Casts/Buffs in bulk."""
    players = normalize_roster(roster)
    classes = {row["class"] for row in players}
    specs_by_class: dict[str, set[str]] = {}
    for row in players:
        specs_by_class.setdefault(row["class"], set()).add(row["spec"])

    selected = []
    for ability in load_player_ability_catalog()["abilities"]:
        class_name = ability["class"]
        if class_name != "Any" and class_name not in classes:
            continue
        required_specs = set(ability.get("specs") or [])
        if required_specs and not (required_specs & specs_by_class.get(class_name, set())):
            continue
        selected.append(ability)

    by_event: dict[str, dict[int, dict]] = {"cast": {}, "aura": {}}
    for ability in selected:
        event_kind = str(ability.get("event") or "cast")
        for spell_id in ability["ids"]:
            by_event.setdefault(event_kind, {})[int(spell_id)] = ability
    return {
        "players": players,
        "abilities": selected,
        "byEvent": by_event,
        "spellIds": sorted({spell_id for rows in by_event.values() for spell_id in rows}),
    }


def catalog_summary() -> dict:
    document = load_player_ability_catalog()
    abilities = document["abilities"]
    return {
        "schemaVersion": document["schemaVersion"],
        "gameVersion": document["gameVersion"],
        "abilityCount": len(abilities),
        "spellIdCount": sum(len(row["ids"]) for row in abilities),
        "classCount": len({row["class"] for row in abilities if row["class"] != "Any"}),
        "verification": document["verification"],
        "digest": hashlib.sha256(CATALOG_PATH.read_bytes()).hexdigest()[:16],
        "categories": document["categories"],
    }
