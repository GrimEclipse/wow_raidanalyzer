"""Export a specialization comparison as JSON and a standalone HTML archive."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analyzer_core.spec_comparison import build_spec_comparison, collect_combatant_bundle
from analyzer_core.wcl_api import WclClient


TEMPLATE = ROOT / "frontend" / "tools" / "spec-comparison" / "index.html"


def render_standalone(document: dict) -> str:
    html = TEMPLATE.read_text(encoding="utf-8")
    payload = json.dumps(document, ensure_ascii=False).replace("</", "<\\/")
    marker = '<script id="embedded-data" type="application/json">{}</script>'
    if marker not in html:
        raise RuntimeError("专精对比页面缺少 embedded-data 存根")
    return html.replace(marker, f'<script id="embedded-data" type="application/json">{payload}</script>')


def export_document(document: dict, json_path: Path, html_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_standalone(document), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="生成单场单专精 WCL 对标页")
    parser.add_argument("--primary-report", default="ZTcf3gMPmnBFVtvx")
    parser.add_argument("--primary-fight", type=int, default=18)
    parser.add_argument("--primary-source", type=int, default=7)
    parser.add_argument("--primary-label", default="你的日志")
    parser.add_argument("--benchmark-report", default="WgHChtKn2Paw9bfz")
    parser.add_argument("--benchmark-fight", type=int, default=83)
    parser.add_argument("--benchmark-source", type=int, default=843)
    parser.add_argument("--benchmark-label", default="WCL 前列对标")
    parser.add_argument("--json", type=Path, default=ROOT / "assets" / "samples" / "spec-comparisons" / "holy-paladin-sszorak.json")
    parser.add_argument("--html", type=Path, default=ROOT / "assets" / "samples" / "spec-comparisons" / "holy-paladin-sszorak.html")
    args = parser.parse_args()

    client = WclClient()
    primary = collect_combatant_bundle(
        args.primary_report, args.primary_fight, args.primary_source,
        label=args.primary_label, role="primary", client=client,
    )
    benchmark = collect_combatant_bundle(
        args.benchmark_report, args.benchmark_fight, args.benchmark_source,
        label=args.benchmark_label, role="benchmark", client=client,
    )
    document = build_spec_comparison(primary, benchmark, options={"virtueWindowMs": 9000})
    export_document(document, args.json, args.html)
    print(f"JSON: {args.json}")
    print(f"HTML: {args.html}")


if __name__ == "__main__":
    main()
