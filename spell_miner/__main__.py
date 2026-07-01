from __future__ import annotations

import argparse
import json
from pathlib import Path

from .db2 import DB2Store
from .graph import SpellGraphMiner, load_seed_file, parse_known_edges


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mine WoW DB2 spell exports into raid analyzer mechanism candidates."
    )
    parser.add_argument("--db2-dir", required=True, help="Directory containing exported DB2 CSV/TSV files.")
    parser.add_argument("--keyword", action="append", default=[], help="Spell or journal keyword to search.")
    parser.add_argument("--seed-id", action="append", type=int, default=[], help="Known spell id entry point.")
    parser.add_argument("--encounter-id", action="append", type=int, default=[], help="Journal encounter id entry.")
    parser.add_argument("--seed-file", help="JSON file containing keywords, seed_ids, encounter_ids, known_edges.")
    parser.add_argument("--out", help="Output JSON path. Defaults to stdout.")
    parser.add_argument("--max-depth", type=int, default=3, help="SpellEffect trigger expansion depth.")
    parser.add_argument(
        "--no-name-siblings",
        action="store_true",
        help="Disable same-name spell id expansion.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db2_dir = Path(args.db2_dir).resolve()
    seed_data = load_seed_file(Path(args.seed_file).resolve() if args.seed_file else None)

    keywords = list(seed_data.get("keywords", [])) + args.keyword
    seed_ids = {int(value) for value in seed_data.get("seed_ids", [])} | set(args.seed_id)
    encounter_ids = {int(value) for value in seed_data.get("encounter_ids", [])} | set(args.encounter_id)
    known_edges = parse_known_edges(seed_data)

    store = DB2Store(db2_dir)
    miner = SpellGraphMiner(store)
    payload = miner.mine(
        seed_ids=seed_ids,
        keywords=keywords,
        encounter_ids=encounter_ids,
        known_edges=known_edges,
        max_depth=args.max_depth,
        include_name_siblings=not args.no_name_siblings,
    )
    text = json.dumps(payload, ensure_ascii=False, indent=2)

    if args.out:
        out_path = Path(args.out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
        print(f"Wrote {out_path}")
    else:
        print(text)


if __name__ == "__main__":
    main()
