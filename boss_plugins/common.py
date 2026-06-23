import json
from pathlib import Path


class BossPluginNotImplemented(NotImplementedError):
    pass


def write_json_result(result, output_path=None):
    output = Path(output_path) if output_path else Path(__file__).resolve().parents[1] / "wcl_hardcore_api.json"
    with open(output, "w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
    return output


def placeholder_analyze(report_ids: str, output_path=None, catalog_entry=None):
    boss_name = catalog_entry.boss_name if catalog_entry else "未配置 Boss"
    raise BossPluginNotImplemented(
        f"{boss_name} 的插件文件已创建，但分析逻辑尚未配置。"
        "请基于 boss_plugins/templates/configurable_boss.py 填写机制规则。"
    )

