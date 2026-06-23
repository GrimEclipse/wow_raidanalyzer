import importlib.util
from pathlib import Path

from boss_plugins.common import write_json_result


ANALYZER_SCRIPT = Path(__file__).resolve().parents[2] / "40-WCL开荒日志分析.py"


def load_analyzer_module():
    spec = importlib.util.spec_from_file_location("midnight_falls_analyzer", ANALYZER_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载鲁拉分析脚本：{ANALYZER_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def analyze(report_ids: str, output_path=None, catalog_entry=None):
    module = load_analyzer_module()
    module.REPORT_IDS_INPUT = report_ids
    result = module.build_aggregated_json()

    if catalog_entry:
        result.setdefault("meta", {}).update({
            "version": catalog_entry.version,
            "raidKey": catalog_entry.raid_key,
            "raidName": catalog_entry.raid_name,
            "bossKey": catalog_entry.boss_key,
            "bossName": catalog_entry.boss_name,
        })

    output = write_json_result(result, output_path)
    module.progress(f"插件输出完成：{output}")
    return result
