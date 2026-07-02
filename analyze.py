import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="WCL boss wipe analyzer")
    parser.add_argument("--report", required=True, help="WCL report id，多个用逗号分隔")
    parser.add_argument("--version", default="12.0", help="版本号")
    parser.add_argument("--raid", default="march_on_queldanas", help="副本 key")
    parser.add_argument("--boss", default="midnight_falls", help="boss key")
    parser.add_argument("--output", default=str(Path(__file__).resolve().with_name("wcl_hardcore_api.json")),
                        help="输出 JSON 路径")
    parser.add_argument("--include-dispels", action="store_true", help="读取额外驱散数据；当前主要用于光盲先锋军复仇者之盾减员分析")
    args = parser.parse_args()
    if args.include_dispels:
        os.environ["LIGHTBLINDED_VANGUARD_DISPELS"] = "1"

    print(
        f"[analyze] version={args.version} raid={args.raid} boss={args.boss} report={args.report} include_dispels={args.include_dispels}",
        flush=True,
    )
    from analyzer_core.runner import analyze_report

    analyze_report(
        version=args.version,
        raid_key=args.raid,
        boss_key=args.boss,
        report_ids=args.report,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
