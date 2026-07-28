from importlib import import_module
from inspect import signature
from pathlib import Path
from typing import Optional, Union

from analyzer_core.catalog import find_boss
from analyzer_core.config import resolve_analysis_options
from analyzer_core.progress import emit_progress, progress_scope


def load_plugin(entry):
    module = import_module(entry.plugin)
    if not hasattr(module, "analyze"):
        raise AttributeError(f"{entry.plugin} 缺少 analyze(report_ids, output_path) 接口")
    return module


def call_plugin(plugin, *, report_ids, output_path, catalog_entry, options, progress_callback):
    params = signature(plugin.analyze).parameters
    kwargs = {"report_ids": report_ids}
    if "output_path" in params:
        kwargs["output_path"] = output_path
    if "catalog_entry" in params:
        kwargs["catalog_entry"] = catalog_entry
    if "options" in params:
        kwargs["options"] = options
    if "progress_callback" in params:
        kwargs["progress_callback"] = progress_callback
    return plugin.analyze(**kwargs)


def analyze_report(
    version: str,
    raid_key: str,
    boss_key: str,
    report_ids: str,
    output_path: Optional[Union[str, Path]] = None,
    options: Optional[dict] = None,
    progress_callback=None,
):
    with progress_scope(progress_callback):
        entry = find_boss(version, raid_key, boss_key)
        if not entry.supported:
            raise ValueError(f"{entry.boss_name} {entry.disabled_reason or '暂未接入在线分析'}")

        print(f"[analyze] loading plugin: {entry.plugin}", flush=True)
        emit_progress("加载 Boss 插件", percent=2, stage="prepare")
        plugin = load_plugin(entry)
        resolved_options = resolve_analysis_options(entry.config_schema, options or {})
        print("[analyze] plugin loaded, starting WCL analysis", flush=True)
        emit_progress("启动 WCL 分析任务", percent=5, stage="prepare")
        return call_plugin(
            plugin,
            report_ids=report_ids,
            output_path=output_path,
            catalog_entry=entry,
            options=resolved_options,
            progress_callback=progress_callback,
        )
