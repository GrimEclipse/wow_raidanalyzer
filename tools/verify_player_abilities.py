"""Verify the shared player ability catalog against current WCL GameData.

The command is read-only by design.  It never silently rewrites the runtime
catalog; maintainers review differences and update the catalog explicitly.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analyzer_core.player_abilities import load_player_ability_catalog
from analyzer_core.wcl_api import WclClient


def verify() -> list[str]:
    rows = load_player_ability_catalog()["abilities"]
    spell_ids = sorted({int(value) for row in rows for value in row["ids"]})
    resolved = {}
    client = WclClient()
    for offset in range(0, len(spell_ids), 50):
        chunk = spell_ids[offset:offset + 50]
        aliases = " ".join(f"a{spell_id}: ability(id:{spell_id}){{id name}}" for spell_id in chunk)
        data = client.graphql_data(f"query {{ gameData {{ {aliases} }} }}", {})["gameData"]
        resolved.update({spell_id: data.get(f"a{spell_id}") for spell_id in chunk})

    errors = []
    for row in rows:
        for spell_id in row["ids"]:
            value = resolved.get(int(spell_id))
            if not value:
                errors.append(f"{row['key']}: ID {spell_id} 无法解析")
                continue
            expected_names = {part.strip().lower() for part in str(row["nameEn"]).split("/") if part.strip()}
            if str(value.get("name") or "").strip().lower() not in expected_names:
                names = [resolved[int(value)]["name"] for value in row["ids"] if resolved.get(int(value))]
                if {name.strip().lower() for name in names} != expected_names:
                    errors.append(f"{row['key']}: 配置 {row['nameEn']} / WCL {names}")
    print(f"checked abilities={len(rows)} spellIds={len(spell_ids)} errors={len(errors)}")
    for error in errors:
        print(error)
    return errors


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    raise SystemExit(1 if verify() else 0)
