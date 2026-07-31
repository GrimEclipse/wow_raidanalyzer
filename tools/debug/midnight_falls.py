import os

VERSION = "12.0"
RAID = "march_on_queldanas"
BOSS = "midnight_falls"
REPORT_ID = "rdtvn6ghqY4AkLj1"
INCLUDE_DISPELS = True


def main():
    print("[debug] Lightblinded Vanguard analyzer", flush=True)
    print(f"[debug] report={REPORT_ID}", flush=True)
    print("[debug] output=(auto: data/wcl_<report>_<boss>_<开荒日>.json)", flush=True)
    print(f"[debug] include_dispels={INCLUDE_DISPELS}", flush=True)
    if INCLUDE_DISPELS:
        os.environ["LIGHTBLINDED_VANGUARD_DISPELS"] = "1"

    from analyzer_core.runner import analyze_report

    analyze_report(
        version=VERSION,
        raid_key=RAID,
        boss_key=BOSS,
        report_ids=REPORT_ID,
        output_path=None,
    )


if __name__ == "__main__":
    main()
