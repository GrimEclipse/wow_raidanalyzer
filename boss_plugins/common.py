import json
from pathlib import Path

from boss_plugins.combat_config import (
    PERSONAL_DEFENSIVES,
    RAID_DEFENSIVES,
    audit_personal_defensive_readiness,
    audit_raid_defensive_assignment,
    defensive_spell_ids,
    find_defensive_uses_before_death,
)


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

SPEC_ICON_SLUGS = {
    62: "mage-arcane",
    63: "mage-fire",
    64: "mage-frost",
    65: "paladin-holy",
    66: "paladin-protection",
    70: "paladin-retribution",
    71: "warrior-arms",
    72: "warrior-fury",
    73: "warrior-protection",
    102: "druid-balance",
    103: "druid-feral",
    104: "druid-guardian",
    105: "druid-restoration",
    250: "deathknight-blood",
    251: "deathknight-frost",
    252: "deathknight-unholy",
    253: "hunter-beastmastery",
    254: "hunter-marksmanship",
    255: "hunter-survival",
    256: "priest-discipline",
    257: "priest-holy",
    258: "priest-shadow",
    259: "rogue-assassination",
    260: "rogue-outlaw",
    261: "rogue-subtlety",
    262: "shaman-elemental",
    263: "shaman-enhancement",
    264: "shaman-restoration",
    265: "warlock-affliction",
    266: "warlock-demonology",
    267: "warlock-destruction",
    268: "monk-brewmaster",
    269: "monk-windwalker",
    270: "monk-mistweaver",
    577: "demonhunter-havoc",
    581: "demonhunter-vengeance",
    1467: "evoker-devastation",
    1468: "evoker-preservation",
    1473: "evoker-augmentation",
    1480: "demonhunter-devourer",
}

CLASS_NAMES = {
    "deathknight": {"enUS": "Death Knight", "zhCN": "死亡骑士"},
    "demonhunter": {"enUS": "Demon Hunter", "zhCN": "恶魔猎手"},
    "druid": {"enUS": "Druid", "zhCN": "德鲁伊"},
    "evoker": {"enUS": "Evoker", "zhCN": "唤魔师"},
    "hunter": {"enUS": "Hunter", "zhCN": "猎人"},
    "mage": {"enUS": "Mage", "zhCN": "法师"},
    "monk": {"enUS": "Monk", "zhCN": "武僧"},
    "paladin": {"enUS": "Paladin", "zhCN": "圣骑士"},
    "priest": {"enUS": "Priest", "zhCN": "牧师"},
    "rogue": {"enUS": "Rogue", "zhCN": "潜行者"},
    "shaman": {"enUS": "Shaman", "zhCN": "萨满祭司"},
    "warlock": {"enUS": "Warlock", "zhCN": "术士"},
    "warrior": {"enUS": "Warrior", "zhCN": "战士"},
}

SPEC_NAMES = {
    62: {"enUS": "Arcane", "zhCN": "奥术"},
    63: {"enUS": "Fire", "zhCN": "火焰"},
    64: {"enUS": "Frost", "zhCN": "冰霜"},
    65: {"enUS": "Holy", "zhCN": "神圣"},
    66: {"enUS": "Protection", "zhCN": "防护"},
    70: {"enUS": "Retribution", "zhCN": "惩戒"},
    71: {"enUS": "Arms", "zhCN": "武器"},
    72: {"enUS": "Fury", "zhCN": "狂怒"},
    73: {"enUS": "Protection", "zhCN": "防护"},
    102: {"enUS": "Balance", "zhCN": "平衡"},
    103: {"enUS": "Feral", "zhCN": "野性"},
    104: {"enUS": "Guardian", "zhCN": "守护"},
    105: {"enUS": "Restoration", "zhCN": "恢复"},
    250: {"enUS": "Blood", "zhCN": "鲜血"},
    251: {"enUS": "Frost", "zhCN": "冰霜"},
    252: {"enUS": "Unholy", "zhCN": "邪恶"},
    253: {"enUS": "Beast Mastery", "zhCN": "野兽控制"},
    254: {"enUS": "Marksmanship", "zhCN": "射击"},
    255: {"enUS": "Survival", "zhCN": "生存"},
    256: {"enUS": "Discipline", "zhCN": "戒律"},
    257: {"enUS": "Holy", "zhCN": "神圣"},
    258: {"enUS": "Shadow", "zhCN": "暗影"},
    259: {"enUS": "Assassination", "zhCN": "奇袭"},
    260: {"enUS": "Outlaw", "zhCN": "狂徒"},
    261: {"enUS": "Subtlety", "zhCN": "敏锐"},
    262: {"enUS": "Elemental", "zhCN": "元素"},
    263: {"enUS": "Enhancement", "zhCN": "增强"},
    264: {"enUS": "Restoration", "zhCN": "恢复"},
    265: {"enUS": "Affliction", "zhCN": "痛苦"},
    266: {"enUS": "Demonology", "zhCN": "恶魔学识"},
    267: {"enUS": "Destruction", "zhCN": "毁灭"},
    268: {"enUS": "Brewmaster", "zhCN": "酒仙"},
    269: {"enUS": "Windwalker", "zhCN": "踏风"},
    270: {"enUS": "Mistweaver", "zhCN": "织雾"},
    577: {"enUS": "Havoc", "zhCN": "浩劫"},
    581: {"enUS": "Vengeance", "zhCN": "复仇"},
    1467: {"enUS": "Devastation", "zhCN": "湮灭"},
    1468: {"enUS": "Preservation", "zhCN": "恩护"},
    1473: {"enUS": "Augmentation", "zhCN": "增辉"},
    1480: {"enUS": "Devourer", "zhCN": "吞噬"},
}

CLASS_COLORS = {
    "deathknight": "#C41E3A",
    "demonhunter": "#A330C9",
    "druid": "#FF7C0A",
    "evoker": "#33937F",
    "hunter": "#AAD372",
    "mage": "#3FC7EB",
    "monk": "#00FF98",
    "paladin": "#F48CBA",
    "priest": "#FFFFFF",
    "rogue": "#FFF468",
    "shaman": "#0070DD",
    "warlock": "#8788EE",
    "warrior": "#C69B6D",
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

ROLE_NAMES = {
    "tank": {"enUS": "Tank", "zhCN": "坦克"},
    "healer": {"enUS": "Healer", "zhCN": "治疗"},
    "dps": {"enUS": "Damage", "zhCN": "输出"},
    "unknown": {"enUS": "Unknown", "zhCN": "未知"},
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


def spec_icon_slug(spec_id):
    try:
        spec_id = int(spec_id)
    except (TypeError, ValueError):
        return None
    return SPEC_ICON_SLUGS.get(spec_id)


def spec_class_slug(spec_id):
    icon_slug = spec_icon_slug(spec_id)
    return icon_slug.split("-", 1)[0] if icon_slug else None


def spec_class_color(spec_id):
    return CLASS_COLORS.get(spec_class_slug(spec_id))


def spec_localization(spec_id):
    """Return locale-neutral keys plus translated display labels for a spec."""
    try:
        spec_id = int(spec_id)
    except (TypeError, ValueError):
        return {
            "spec": {},
            "class": {},
            "role": dict(ROLE_NAMES["unknown"]),
        }
    class_slug = spec_class_slug(spec_id)
    basic_role = role_to_basic(spec_role_group(spec_id))
    return {
        "spec": dict(SPEC_NAMES.get(spec_id) or {}),
        "class": dict(CLASS_NAMES.get(class_slug) or {}),
        "role": dict(ROLE_NAMES.get(basic_role) or ROLE_NAMES["unknown"]),
    }


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


def write_json_result(result, output_path=None, catalog_entry=None):
    from analyzer_core.contracts import apply_analysis_contract
    from analyzer_core.wcl_paths import resolve_wcl_output_path, write_data_manifest

    if catalog_entry:
        meta = result.setdefault("meta", {})
        meta.update({
            "version": catalog_entry.version,
            "raidKey": catalog_entry.raid_key,
            "raidName": catalog_entry.raid_name,
            "bossKey": catalog_entry.boss_key,
            "bossName": catalog_entry.boss_name,
        })
        if catalog_entry.capabilities:
            meta["capabilities"] = dict(catalog_entry.capabilities)
    result = apply_analysis_contract(result)
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
