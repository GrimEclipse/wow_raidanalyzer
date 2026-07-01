from importlib import import_module
from pathlib import Path
from typing import Optional, Union

from analyzer_core.catalog import find_boss


def load_plugin(entry):
    module = import_module(entry.plugin)
    if not hasattr(module, "analyze"):
        raise AttributeError(f"{entry.plugin} 缺少 analyze(report_ids, output_path) 接口")
    return module


def analyze_report(version: str, raid_key: str, boss_key: str, report_ids: str, output_path: Optional[Union[str, Path]] = None):
    entry = find_boss(version, raid_key, boss_key)
    print(f"[analyze] loading plugin: {entry.plugin}", flush=True)
    plugin = load_plugin(entry)
    print("[analyze] plugin loaded, starting WCL analysis", flush=True)
    return plugin.analyze(report_ids=report_ids, output_path=output_path, catalog_entry=entry)
