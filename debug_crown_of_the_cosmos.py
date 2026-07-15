import os

VERSION = "12.0"
RAID = "void_spire"
BOSS = "crown_of_the_cosmos"
FALLBACK_REPORT_ID = "mH8AFN1xXq94J2kW"


def main():
    from boss_plugins.void_spire.crown_of_the_cosmos import load_env_file

    load_env_file()
    report_id = os.getenv("WCL_REPORT_IDS", "").strip() or FALLBACK_REPORT_ID

    print("[debug] Crown of the Cosmos analyzer", flush=True)
    print(f"[debug] report={report_id}", flush=True)
    print("[debug] output=(auto: data/wcl_<report>_<boss>_<开荒日>.json)", flush=True)

    from analyzer_core.runner import analyze_report

    analyze_report(
        version=VERSION,
        raid_key=RAID,
        boss_key=BOSS,
        report_ids=report_id,
        output_path=None,
    )


if __name__ == "__main__":
    main()
