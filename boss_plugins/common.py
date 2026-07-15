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


TANK_SPEC_IDS = {
    66: "Protection Paladin",
    73: "Protection Warrior",
    104: "Guardian Druid",
    250: "Blood Death Knight",
    268: "Brewmaster Monk",
    581: "Vengeance Demon Hunter",
}

MELEE_DPS_SPEC_IDS = {
    70: "Retribution Paladin",
    71: "Arms Warrior",
    72: "Fury Warrior",
    103: "Feral Druid",
    251: "Frost Death Knight",
    252: "Unholy Death Knight",
    255: "Survival Hunter",
    259: "Assassination Rogue",
    260: "Outlaw Rogue",
    261: "Subtlety Rogue",
    263: "Enhancement Shaman",
    269: "Windwalker Monk",
    577: "Havoc Demon Hunter",
}

MELEE_HEALER_SPEC_IDS = {
    65: "Holy Paladin",
    270: "Mistweaver Monk",
}

RANGE_DPS_SPEC_IDS = {
    62: "Arcane Mage",
    63: "Fire Mage",
    64: "Frost Mage",
    102: "Balance Druid",
    253: "Beast Mastery Hunter",
    254: "Marksmanship Hunter",
    258: "Shadow Priest",
    262: "Elemental Shaman",
    265: "Affliction Warlock",
    266: "Demonology Warlock",
    267: "Destruction Warlock",
    1467: "Devastation Evoker",
    1473: "Augmentation Evoker",
    1480: "Devourer Demon Hunter",
}

RANGE_HEALER_SPEC_IDS = {
    105: "Restoration Druid",
    256: "Discipline Priest",
    257: "Holy Priest",
    264: "Restoration Shaman",
    1468: "Preservation Evoker",
}

SPEC_ROLE_GROUPS = {
    **{spec_id: "tank" for spec_id in TANK_SPEC_IDS},
    **{spec_id: "melee-dps" for spec_id in MELEE_DPS_SPEC_IDS},
    **{spec_id: "melee-healer" for spec_id in MELEE_HEALER_SPEC_IDS},
    **{spec_id: "range-dps" for spec_id in RANGE_DPS_SPEC_IDS},
    **{spec_id: "range-healer" for spec_id in RANGE_HEALER_SPEC_IDS},
}

ROLE_TEXT = {
    "tank": "坦克",
    "melee-dps": "近战输出",
    "melee-healer": "近战治疗",
    "range-dps": "远程输出",
    "range-healer": "远程治疗",
    "healer": "治疗",
    "dps": "输出",
    "unknown": "未知",
}


def combatant_spec_id(event):
    for key in ("specID", "specId", "spec", "specializationID", "specializationId"):
        value = event.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def event_source_id(event):
    return event.get("sourceID") or event.get("targetID")


def spec_role_group(spec_id):
    try:
        spec_id = int(spec_id)
    except (TypeError, ValueError):
        return "unknown"
    return SPEC_ROLE_GROUPS.get(spec_id, "unknown")


def role_to_basic(role):
    if role == "tank":
        return "tank"
    if role in {"melee-healer", "range-healer", "healer"}:
        return "healer"
    if role in {"melee-dps", "range-dps", "dps"}:
        return "dps"
    return "unknown"


def build_player_mechanic_roles(combatant_info, tank_player_ids=None):
    roles = {}
    for event in combatant_info:
        source_id = event_source_id(event)
        if not source_id:
            continue
        role = spec_role_group(combatant_spec_id(event))
        if role != "unknown":
            roles[source_id] = role
    for player_id in tank_player_ids or set():
        if player_id:
            roles[player_id] = "tank"
    return roles


def build_player_basic_roles(combatant_info, tank_player_ids=None):
    return {
        player_id: role_to_basic(role)
        for player_id, role in build_player_mechanic_roles(combatant_info, tank_player_ids).items()
    }


def role_text(role):
    return ROLE_TEXT.get(role or "unknown", "未知")


class BossPluginNotImplemented(NotImplementedError):
    pass


def write_json_result(result, output_path=None):
    from analyzer_core.wcl_paths import resolve_wcl_output_path, write_data_manifest

    output = resolve_wcl_output_path(result=result, output_path=output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
    write_data_manifest(extra_path=output)
    return output


def placeholder_analyze(report_ids: str, output_path=None, catalog_entry=None):
    boss_name = catalog_entry.boss_name if catalog_entry else "未配置 Boss"
    raise BossPluginNotImplemented(
        f"{boss_name} 的插件文件已创建，但分析逻辑尚未配置。"
        "请基于 boss_plugins/templates/configurable_boss.py 填写机制规则。"
    )
