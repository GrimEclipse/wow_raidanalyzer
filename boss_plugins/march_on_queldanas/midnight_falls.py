from analyzer_core.progress import emit_progress
from boss_plugins.common import write_json_result
from boss_plugins.march_on_queldanas import midnight_falls_core


def analyze(report_ids: str, output_path=None, catalog_entry=None, options=None):
    midnight_falls_core.REPORT_IDS_INPUT = report_ids
    midnight_falls_core.ONLINE_ANALYSIS_OPTIONS = options or {}
    if not hasattr(midnight_falls_core, "_BASE_PROGRESS"):
        midnight_falls_core._BASE_PROGRESS = midnight_falls_core.progress
    original_progress = midnight_falls_core._BASE_PROGRESS

    def wrapped_progress(message, indent=0):
        original_progress(message, indent)
        emit_progress(message, detail=indent > 0)

    midnight_falls_core.progress = wrapped_progress

    result = midnight_falls_core.build_aggregated_json()

    if catalog_entry:
        result.setdefault("meta", {}).update({
            "version": catalog_entry.version,
            "raidKey": catalog_entry.raid_key,
            "raidName": catalog_entry.raid_name,
            "bossKey": catalog_entry.boss_key,
            "bossName": catalog_entry.boss_name,
        })

    output = write_json_result(result, output_path, catalog_entry=catalog_entry)
    midnight_falls_core.progress(f"插件输出完成：{output}")
    return result
