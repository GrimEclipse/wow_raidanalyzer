from dataclasses import dataclass, field
from typing import Iterable, List


@dataclass(frozen=True)
class BossEntry:
    version: str
    raid_key: str
    raid_name: str
    boss_key: str
    boss_name: str
    plugin: str
    supported: bool = False
    disabled_reason: str = "暂未接入在线分析"
    config_schema: List[dict] = field(default_factory=list)


VERSIONS = ("12.0", "12.1")

RAIDS = {
    "dream_rift": "梦境裂隙",
    "void_spire": "虚影尖塔",
    "march_on_queldanas": "进军奎尔丹纳斯",
    "sporefall": "暮孢陨坠",
}


MIDNIGHT_FALLS_CONFIG = [
    {
        "key": "terminalMatrixInterruptGroups",
        "type": "interruptGroups",
        "label": "终结矩阵打断分配预设（请保证 id 完全一致）",
        "groups": [
            {"key": "group1", "label": "第一组", "slots": 3},
            {"key": "group2", "label": "第二组", "slots": 3},
            {"key": "group3", "label": "第三组", "slots": 3},
            {"key": "group4", "label": "第四组", "slots": 3},
        ],
    }
]


BOSS_DEFINITIONS = [
    ("dream_rift", "chimaerus", "奇美鲁斯，未梦之神", "boss_plugins.dream_rift.chimaerus", False, []),

    ("void_spire", "imperator_averzian", "元首阿福扎恩", "boss_plugins.void_spire.imperator_averzian", False, []),
    ("void_spire", "vorasius", "弗拉希乌斯", "boss_plugins.void_spire.vorasius", False, []),
    ("void_spire", "fallen_king_salhadaar", "陨落之王萨哈达尔", "boss_plugins.void_spire.fallen_king_salhadaar", False, []),
    ("void_spire", "vaelgor_ezzorak", "威厄高尔和艾佐拉克", "boss_plugins.void_spire.vaelgor_ezzorak", False, []),
    ("void_spire", "lightblinded_vanguard", "光盲先锋军", "boss_plugins.void_spire.lightblinded_vanguard", True, []),
    ("void_spire", "crown_of_the_cosmos", "宇宙之冕", "boss_plugins.void_spire.crown_of_the_cosmos", True, []),

    ("march_on_queldanas", "beloren", "贝洛朗，奥的子嗣", "boss_plugins.march_on_queldanas.beloren", False, []),
    ("march_on_queldanas", "midnight_falls", "至暗之夜降临", "boss_plugins.march_on_queldanas.midnight_falls", True, MIDNIGHT_FALLS_CONFIG),

    ("sporefall", "rotmire", "腐沼", "boss_plugins.sporefall.rotmire", False, []),
]


def build_catalog() -> List[BossEntry]:
    entries = []
    for version in VERSIONS:
        for raid_key, boss_key, boss_name, plugin, supported, config_schema in BOSS_DEFINITIONS:
            entries.append(
                BossEntry(
                    version=version,
                    raid_key=raid_key,
                    raid_name=RAIDS[raid_key],
                    boss_key=boss_key,
                    boss_name=boss_name,
                    plugin=plugin,
                    supported=supported,
                    disabled_reason="" if supported else "暂未接入在线分析",
                    config_schema=config_schema,
                )
            )
    return entries


CATALOG = build_catalog()


def iter_versions() -> Iterable[str]:
    seen = set()
    for entry in CATALOG:
        if entry.version not in seen:
            seen.add(entry.version)
            yield entry.version


def find_boss(version: str, raid_key: str, boss_key: str) -> BossEntry:
    for entry in CATALOG:
        if entry.version == version and entry.raid_key == raid_key and entry.boss_key == boss_key:
            return entry
    available = ", ".join(f"{item.version}/{item.raid_key}/{item.boss_key}" for item in CATALOG)
    raise ValueError(f"未找到 boss 插件：{version}/{raid_key}/{boss_key}。可用项：{available}")


def to_frontend_catalog() -> dict:
    versions = []
    for version in iter_versions():
        raids = []
        version_entries = [entry for entry in CATALOG if entry.version == version]
        for raid_key in dict.fromkeys(entry.raid_key for entry in version_entries):
            raid_entries = [entry for entry in version_entries if entry.raid_key == raid_key]
            raids.append({
                "key": raid_key,
                "name": raid_entries[0].raid_name,
                "bosses": [
                    {
                        "key": entry.boss_key,
                        "name": entry.boss_name,
                        "supported": entry.supported,
                        "disabledReason": entry.disabled_reason,
                        "configSchema": entry.config_schema,
                    }
                    for entry in raid_entries
                ],
            })
        versions.append({"version": version, "raids": raids})
    return {"versions": versions}
