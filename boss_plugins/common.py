import json
from pathlib import Path


COMBAT_RES_SPELLS = {
    20484: "复生",
    61999: "复活盟友",
    20707: "灵魂石",
    391054: "代祷",
}

HEALER_DISPEL_SPELLS = {
    4987: "清洁术",
    115450: "清创生血",
    88423: "自然之愈",
    360823: "自然平衡",
    527: "纯净术",
    77130: "净化灵魂",
    32375: "群体驱散",
    115310: "还魂术",
    89808: "烧灼魔法",
}

HEALER_SPEC_IDS = {
    65: "神圣圣骑士",
    105: "恢复德鲁伊",
    256: "戒律牧师",
    257: "神圣牧师",
    264: "恢复萨满",
    270: "织雾武僧",
    1468: "恩护唤魔师",
}


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
