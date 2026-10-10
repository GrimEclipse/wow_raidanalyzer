"""Build the explicitly approved public examples; never publish a data folder."""

from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# These reports were selected after the owner authorized Avalon examples.
DEMOS = [
    {"key": "sszorak", "boss": "sszorak", "label": "斯索拉克", "report": "ZFDWvrfqd6ygMKY2", "fight": 38, "raid": "venomous_abyss", "renderer": "progression", "tab": "replay"},
    {"key": "coiledaltar", "boss": "coiledaltar", "label": "盘卷祭坛", "report": "H1LdCx4hNG6jW2FT", "fight": 16, "raid": "venomous_abyss", "renderer": "coiledaltar", "tab": "replay"},
    {"key": "twinfangs", "boss": "twinfangs", "label": "双子毒牙", "report": "BZKtqb6wyTnAHGRV", "fight": 37, "raid": "venomous_abyss", "renderer": "progression", "tab": "brood"},
    {"key": "ulatek", "homepageVisible": False, "boss": "ulatek", "label": "乌拉特克（英雄）", "report": "ZFDWvrfqd6ygMKY2", "fight": 12, "raid": "venomous_abyss", "renderer": "ulatek", "tab": "replay"},
    {"key": "ulatek_mythic", "boss": "ulatek", "label": "乌拉特克", "report": "r19Gk7PJfVvmnFgM", "fight": 3, "raid": "venomous_abyss", "renderer": "ulatek", "tab": "replay"},
    {"key": "vashnik", "boss": "vashnik", "label": "瓦什尼克", "report": "ZFDWvrfqd6ygMKY2", "fight": 54, "raid": "venomous_abyss", "renderer": "vashnik", "tab": "replay"},
    {"key": "nymrissa_wavecaller", "homepageVisible": False, "boss": "nymrissa_wavecaller", "label": "尼姆瑞莎", "report": "ZFDWvrfqd6ygMKY2", "fight": 57, "raid": "tidebound_grotto", "renderer": "nymrissa_wavecaller", "tab": "explore"},
    {"key": "coiledaltar_progression", "homepageVisible": False, "boss": "coiledaltar", "label": "盘卷祭坛（史诗开荒）", "report": "H1LdCx4hNG6jW2FT", "fight": 16, "raid": "venomous_abyss", "renderer": "coiledaltar", "tab": "replay"},
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="Analyze the selected WCL fights using your own configured credentials")
    args = parser.parse_args()
    source = ROOT / "data" / "demo-working"
    output = ROOT / "assets" / "demos"
    output.mkdir(parents=True, exist_ok=True)
    manifest = []
    for demo in DEMOS:
        path = source / (demo["key"] + ".json")
        if args.refresh:
            from analyzer_core.single_fight import analyze_single_fight
            analyze_single_fight(report_code=demo["report"], fight_id=demo["fight"], output_path=path)
        if not path.is_file():
            raise SystemExit(f"Missing {path}; use --refresh to prepare this approved fight.")
        original = json.loads(path.read_text(encoding="utf-8-sig"))
        pulls = [pull for pull in original.get("data", {}).get("page1_wipeAnalysis", [])
                 if pull.get("reportID") == demo["report"] and pull.get("fightID") == demo["fight"]]
        if len(pulls) != 1 or original.get("meta", {}).get("bossKey") != demo["boss"]:
            raise SystemExit(f"Unexpected report identity in {path}")
        allowed_meta = ("version", "raidKey", "raidName", "bossKey", "bossName", "tabDefinitions", "arenaImage", "features", "mechanicVersion", "analysisConfig", "evidenceLimits")
        result = {"code": 200, "meta": {key: original["meta"][key] for key in allowed_meta if key in original["meta"]},
                  "data": {"page1_wipeAnalysis": pulls}}
        result["meta"]["demo"] = {"reportCode": demo["report"], "fightID": demo["fight"], "precomputed": True}
        (output / (demo["key"] + ".json")).write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        pull = pulls[0]
        manifest.append({"key": demo["key"], "homepageVisible": demo.get("homepageVisible", True), "label": demo["label"], "json": f"/assets/demos/{demo['key']}.json",
                         "page": f"/frontend/report/plugins/{demo['raid']}/{demo['renderer']}/report.html", "tab": demo["tab"],
                         "description": f"{pull.get('difficultyName')}，{'击杀' if pull.get('isKill') else '开荒'}，{pull.get('duration')}，WCL {demo['report']} / Fight {demo['fight']}"})
    (output / "manifest.json").write_text(json.dumps({"schemaVersion": 1, "demos": manifest}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Built {len(manifest)} approved demo variants in {output}")


if __name__ == "__main__":
    main()
