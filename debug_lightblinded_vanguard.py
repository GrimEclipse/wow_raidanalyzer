from pathlib import Path
import os


VERSION = "12.0"
RAID = "void_spire"
BOSS = "lightblinded_vanguard"
REPORT_ID = "KaYJRC3PX2ntDq8y"
OUTPUT = Path(__file__).resolve().with_name("wcl_hardcore_api.json")
INCLUDE_DISPELS = True


def main():
    print("[debug] Lightblinded Vanguard analyzer", flush=True)
    print(f"[debug] report={REPORT_ID}", flush=True)
    print(f"[debug] output={OUTPUT}", flush=True)
    print(f"[debug] include_dispels={INCLUDE_DISPELS}", flush=True)
    if INCLUDE_DISPELS:
        os.environ["LIGHTBLINDED_VANGUARD_DISPELS"] = "1"

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
