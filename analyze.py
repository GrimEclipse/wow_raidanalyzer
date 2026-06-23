import argparse
from pathlib import Path

from analyzer_core.runner import analyze_report


def main():
    parser = argparse.ArgumentParser(description="WCL boss wipe analyzer")
    parser.add_argument("--report", required=True, help="WCL report id，多个用逗号分隔")
    parser.add_argument("--version", default="12.0", help="版本号")
    parser.add_argument("--raid", default="march_on_queldanas", help="副本 key")
    parser.add_argument("--boss", default="midnight_falls", help="boss key")
    parser.add_argument("--output", default=str(Path(__file__).resolve().with_name("wcl_hardcore_api.json")),
                        help="输出 JSON 路径")
    args = parser.parse_args()

    analyze_report(
        version=args.version,
        raid_key=args.raid,
        boss_key=args.boss,
        report_ids=args.report,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
