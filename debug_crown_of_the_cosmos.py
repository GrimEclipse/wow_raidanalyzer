from pathlib import Path


VERSION = "12.0"
RAID = "void_spire"
BOSS = "crown_of_the_cosmos"
REPORT_ID = "VMxJ7p1NCYXAahb4"
OUTPUT = Path(__file__).resolve().with_name("wcl_hardcore_api.json")


def main():
    print("[debug] Crown of the Cosmos analyzer", flush=True)
    print(f"[debug] report={REPORT_ID}", flush=True)
    print(f"[debug] output={OUTPUT}", flush=True)

    from analyzer_core.runner import analyze_report

    analyze_report(
        version=VERSION,
        raid_key=RAID,
        boss_key=BOSS,
        report_ids=REPORT_ID,
        output_path=OUTPUT,
    )


if __name__ == "__main__":
    main()
