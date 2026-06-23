from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class BossEntry:
    version: str
    raid_key: str
    raid_name: str
    boss_key: str
    boss_name: str
    plugin: str


VERSION_12 = "12.0"

RAIDS = {
    "dream_rift": "梦境裂隙",
    "void_spire": "虚影尖塔",
    "march_on_queldanas": "进军奎尔丹纳斯",
    "sporefall": "暮孢陨坠",
}


CATALOG = [
    BossEntry(VERSION_12, "dream_rift", RAIDS["dream_rift"], "chimaerus", "奇美鲁斯，未梦之神",
              "boss_plugins.dream_rift.chimaerus"),

    BossEntry(VERSION_12, "void_spire", RAIDS["void_spire"], "imperator_averzian", "元首阿福扎恩",
              "boss_plugins.void_spire.imperator_averzian"),
    BossEntry(VERSION_12, "void_spire", RAIDS["void_spire"], "vorasius", "弗拉希乌斯",
              "boss_plugins.void_spire.vorasius"),
    BossEntry(VERSION_12, "void_spire", RAIDS["void_spire"], "fallen_king_salhadaar", "陨落之王萨哈达尔",
              "boss_plugins.void_spire.fallen_king_salhadaar"),
    BossEntry(VERSION_12, "void_spire", RAIDS["void_spire"], "vaelgor_ezzorak", "威厄高尔和艾佐拉克",
              "boss_plugins.void_spire.vaelgor_ezzorak"),
    BossEntry(VERSION_12, "void_spire", RAIDS["void_spire"], "lightblinded_vanguard", "光盲先锋军",
              "boss_plugins.void_spire.lightblinded_vanguard"),
    BossEntry(VERSION_12, "void_spire", RAIDS["void_spire"], "crown_of_the_cosmos", "宇宙之冕",
              "boss_plugins.void_spire.crown_of_the_cosmos"),

    BossEntry(VERSION_12, "march_on_queldanas", RAIDS["march_on_queldanas"], "beloren", "贝洛朗，奥的子嗣",
              "boss_plugins.march_on_queldanas.beloren"),
    BossEntry(VERSION_12, "march_on_queldanas", RAIDS["march_on_queldanas"], "midnight_falls", "至暗之夜降临",
              "boss_plugins.march_on_queldanas.midnight_falls"),

    BossEntry(VERSION_12, "sporefall", RAIDS["sporefall"], "rotmire", "腐沼",
              "boss_plugins.sporefall.rotmire"),
]


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
                    {"key": entry.boss_key, "name": entry.boss_name}
                    for entry in raid_entries
                ],
            })
        versions.append({"version": version, "raids": raids})
    return {"versions": versions}

