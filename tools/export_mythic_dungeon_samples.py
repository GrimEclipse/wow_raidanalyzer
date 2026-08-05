"""Build the audited Season 1 Mythic+ sample bundle and its frontend manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.export_mythic_dungeon_timeline import export  # noqa: E402


SAMPLES = (
    {"key": "algethar_academy", "report": "TaqLH6KvWAG3XVP8", "fight": 3, "level": 24, "policy": "highest-public"},
    {"key": "magisters_terrace", "report": "QTKp4CaWZydRjrwA", "fight": 3, "level": 25, "policy": "highest-public"},
    {"key": "maisara_caverns", "report": "G2rmFDHLQRz1Y4Jw", "fight": 2, "level": 25, "policy": "highest-readable-public"},
    {"key": "nexus_point_xenas", "report": "frjtBDLW2AdnHQk4", "fight": 9, "level": 25, "policy": "highest-public"},
    {"key": "pit_of_saron", "report": "jm2JZ7RFqGB3VtPT", "fight": 14, "level": 25, "policy": "highest-public"},
    {"key": "seat_of_the_triumvirate", "report": "n1Y4X9wbHNqaQDgp", "fight": 1, "level": 24, "policy": "highest-public"},
    {"key": "skyreach", "report": "xpYfcXrBnkP8W1Ka", "fight": 2, "level": 24, "policy": "user-selected"},
    {"key": "windrunner_spire", "report": "1B2NxWQCkXMVqTnt", "fight": 1, "level": 25, "policy": "highest-public"},
)


def sample_path(sample: dict) -> Path:
    return ROOT / "assets" / "samples" / (
        f"mythic_dungeon_{sample['key']}_{sample['report']}_fight{sample['fight']}.json"
    )


def manifest_row(sample: dict, document: dict, path: Path) -> dict:
    dungeon = document["dungeon"]
    source = document["source"]
    return {
        "key": sample["key"],
        "name": dungeon["name"],
        "nameZh": dungeon["nameZh"],
        "keystoneLevel": dungeon["keystoneLevel"],
        "completed": dungeon["completed"],
        "duration": dungeon["keystoneTime"],
        "reportCode": source["reportCode"],
        "fightId": source["fightId"],
        "selectionPolicy": sample["policy"],
        "file": "/assets/samples/" + path.name,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", action="append", choices=[row["key"] for row in SAMPLES])
    parser.add_argument("--skip-existing", action="store_true")
    args = parser.parse_args()
    selected = set(args.only or [])
    manifest = []
    for sample in SAMPLES:
        path = sample_path(sample)
        should_export = not selected or sample["key"] in selected
        if should_export and not (args.skip_existing and path.exists()):
            print(f"Exporting {sample['key']} +{sample['level']} ...", flush=True)
            document = export(sample["report"], sample["fight"], path, sample["key"])
        elif path.exists():
            document = json.loads(path.read_text(encoding="utf-8"))
        else:
            continue
        dungeon = document.get("dungeon") or {}
        if not dungeon.get("completed") or int(dungeon.get("keystoneLevel") or 0) != sample["level"]:
            raise RuntimeError(
                f"sample validation failed for {sample['key']}: "
                f"completed={dungeon.get('completed')} level={dungeon.get('keystoneLevel')}"
            )
        manifest.append(manifest_row(sample, document, path))

    manifest_path = ROOT / "assets" / "samples" / "mythic_dungeon_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({
        "schemaVersion": 1,
        "selectionRule": "highest completed public key first; Skyreach uses the user-selected report",
        "samples": manifest,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"manifest": str(manifest_path), "samples": len(manifest)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
