#!/usr/bin/env python3
"""Export the 12.1 raid loot catalog from a running wow.tools.local instance."""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "assets" / "loot" / "raid_loot_12_1.json"
TARGET_INSTANCES = {
    "1317": ("tidebound_grotto", "潮缚石窟"),
    "1320": ("venomous_abyss", "烈毒之渊"),
}
ENCOUNTER_KEYS = {
    "2849": "nymrissa_wavecaller",
    "2888": "nakzali",
    "2874": "sentinels",
    "2894": "lost_explorers",
    "2882": "vashnik",
    "2871": "sszorak",
    "2887": "twin_fangs",
    "2883": "coiled_altar",
    "2895": "ulatek",
}

CLASS_BITS = {
    1: "warrior", 2: "paladin", 3: "hunter", 4: "rogue", 5: "priest",
    6: "death-knight", 7: "shaman", 8: "mage", 9: "warlock", 10: "monk",
    11: "druid", 12: "demon-hunter", 13: "evoker",
}
ARMOR_CLASSES = {
    "cloth": ["mage", "priest", "warlock"],
    "leather": ["demon-hunter", "druid", "monk", "rogue"],
    "mail": ["evoker", "hunter", "shaman"],
    "plate": ["death-knight", "paladin", "warrior"],
}
WEAPON_CLASSES = {
    0: ["death-knight", "hunter", "monk", "paladin", "rogue", "shaman", "warrior"],
    1: ["death-knight", "hunter", "paladin", "shaman", "warrior"],
    2: ["hunter"],
    3: ["hunter"],
    4: ["druid", "monk", "paladin", "priest", "rogue", "shaman", "warrior"],
    5: ["death-knight", "druid", "monk", "paladin", "shaman", "warrior"],
    6: ["death-knight", "druid", "hunter", "monk", "paladin", "warrior"],
    7: ["death-knight", "demon-hunter", "hunter", "mage", "monk", "paladin", "rogue", "warlock", "warrior"],
    8: ["death-knight", "hunter", "paladin", "warrior"],
    9: ["demon-hunter"],
    10: ["druid", "hunter", "mage", "monk", "priest", "shaman", "warlock"],
    13: ["demon-hunter", "druid", "hunter", "monk", "rogue", "shaman", "warrior"],
    15: ["demon-hunter", "druid", "hunter", "mage", "priest", "rogue", "shaman", "warlock"],
    18: ["hunter"],
    19: ["mage", "priest", "warlock"],
}
WEAPON_NAMES = {
    0: "单手斧", 1: "双手斧", 2: "弓", 3: "枪械", 4: "单手锤", 5: "双手锤",
    6: "长柄武器", 7: "单手剑", 8: "双手剑", 9: "战刃", 10: "法杖",
    13: "拳套", 15: "匕首", 18: "弩", 19: "魔杖",
}
SLOT_NAMES = {
    1: "头部", 2: "颈部", 3: "肩部", 4: "衬衣", 5: "胸部", 6: "腰部",
    7: "腿部", 8: "脚部", 9: "腕部", 10: "手部", 11: "手指", 12: "饰品",
    13: "单手", 14: "副手", 15: "远程", 16: "背部", 17: "双手", 20: "胸部",
    21: "主手", 22: "副手", 23: "副手物品", 26: "远程",
}
ARMOR_NAMES = {
    "cloth": "布甲", "leather": "皮甲", "mail": "锁甲", "plate": "板甲",
    "accessory": "首饰", "weapon": "武器", "token": "套装兑换物",
    "cosmetic": "幻化收藏", "mount": "坐骑", "pet": "宠物", "toy": "玩具",
    "furniture": "家具", "other": "其他",
}


def fetch_rows(base_url: str, name: str, build: str, locale: str) -> list[dict[str, str]]:
    query = urllib.parse.urlencode({
        "name": name,
        "build": build,
        "locale": locale,
        "useHotfixes": "true",
    })
    with urllib.request.urlopen(f"{base_url.rstrip('/')}/dbc/export/?{query}", timeout=300) as response:
        data = response.read().decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(data)))


def as_int(value: str | None, default: int = 0) -> int:
    try:
        return int(value or default)
    except ValueError:
        return default


def classes_from_mask(mask: int) -> list[str]:
    if mask <= 0:
        return []
    return [key for class_id, key in CLASS_BITS.items() if mask & (1 << (class_id - 1))]


def slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "unknown"


def classify(item_id: str, item: dict[str, str], sparse: dict[str, str], decor: dict[str, str] | None,
             is_toy: bool) -> tuple[str, str, str, list[str]]:
    class_id = as_int(item.get("ClassID"))
    subclass_id = as_int(item.get("SubclassID"))
    inventory_type = as_int(item.get("InventoryType") or sparse.get("InventoryType"))
    allowable_mask = as_int(sparse.get("AllowableClass"), -1)
    explicit_classes = classes_from_mask(allowable_mask)

    if decor or class_id == 20:
        return "家具", "furniture", "家具", []
    if is_toy:
        return "玩具", "toy", "玩具", []
    if item_id == "270909" or (class_id == 15 and explicit_classes):
        return "套装兑换物", "token", "套装兑换物", explicit_classes
    if class_id == 15 and subclass_id == 5:
        return "坐骑", "mount", "坐骑", []
    if class_id == 15 and subclass_id == 2:
        return "宠物", "pet", "宠物", []
    if class_id == 2:
        return "装备", "weapon", WEAPON_NAMES.get(subclass_id, "武器"), explicit_classes or WEAPON_CLASSES.get(subclass_id, [])
    if class_id == 4:
        if subclass_id == 5:
            return "装备", "cosmetic", SLOT_NAMES.get(inventory_type, "幻化收藏"), explicit_classes
        if subclass_id == 1:
            armor = "cloth"
        elif subclass_id == 2:
            armor = "leather"
        elif subclass_id == 3:
            armor = "mail"
        elif subclass_id == 4:
            armor = "plate"
        elif subclass_id == 6:
            return "装备", "weapon", "盾牌", explicit_classes or ["paladin", "shaman", "warrior"]
        else:
            armor = "accessory"
        return "装备", armor, SLOT_NAMES.get(inventory_type, "其他部位"), explicit_classes or ARMOR_CLASSES.get(armor, [])
    return "其他收藏", "other", "其他", explicit_classes


def build_catalog(base_url: str, build: str, locale: str) -> dict:
    tables = {name: fetch_rows(base_url, name, build, locale) for name in (
        "JournalInstance", "JournalEncounter", "JournalEncounterItem", "Item", "ItemSparse", "Toy", "HouseDecor",
    )}
    instances = {row["ID"]: row for row in tables["JournalInstance"] if row["ID"] in TARGET_INSTANCES}
    if set(instances) != set(TARGET_INSTANCES):
        raise RuntimeError(f"目标团本不完整：期望 {sorted(TARGET_INSTANCES)}，实际 {sorted(instances)}")

    encounters = {
        row["ID"]: row for row in tables["JournalEncounter"]
        if row["JournalInstanceID"] in TARGET_INSTANCES
    }
    encounter_items: dict[str, list[str]] = defaultdict(list)
    for row in tables["JournalEncounterItem"]:
        if row["JournalEncounterID"] in encounters and row["ItemID"] not in encounter_items[row["JournalEncounterID"]]:
            encounter_items[row["JournalEncounterID"]].append(row["ItemID"])

    item_ids = {item_id for values in encounter_items.values() for item_id in values}
    item_rows = {row["ID"]: row for row in tables["Item"] if row["ID"] in item_ids}
    sparse_rows = {row["ID"]: row for row in tables["ItemSparse"] if row["ID"] in item_ids}
    toy_ids = {row["ItemID"] for row in tables["Toy"] if row["ItemID"] in item_ids}
    decor_rows = {row["ItemID"]: row for row in tables["HouseDecor"] if row["ItemID"] in item_ids}

    raids = []
    for instance_id, (raid_key, expected_name) in TARGET_INSTANCES.items():
        instance = instances[instance_id]
        raid_name = instance["Name_lang"] or expected_name
        bosses = []
        selected = [row for row in encounters.values() if row["JournalInstanceID"] == instance_id]
        for encounter in sorted(selected, key=lambda row: as_int(row["OrderIndex"])):
            encounter_id = encounter["ID"]
            items = []
            for item_id in encounter_items.get(encounter_id, []):
                item = item_rows.get(item_id, {})
                sparse = sparse_rows.get(item_id, {})
                decor = decor_rows.get(item_id)
                name = sparse.get("Display_lang") or (decor or {}).get("Name_lang") or f"物品 {item_id}"
                loot_type, armor_type, slot, classes = classify(item_id, item, sparse, decor, item_id in toy_ids)
                tags = list(dict.fromkeys([loot_type, ARMOR_NAMES.get(armor_type, armor_type), slot]))
                items.append({
                    "id": as_int(item_id),
                    "nameZh": name,
                    "nameEn": "",
                    "wowheadUrl": f"https://www.wowhead.com/cn/item={item_id}",
                    "translationStatus": "official-zhCN-db2",
                    "lootType": loot_type,
                    "slot": slot,
                    "armorType": armor_type,
                    "classes": classes,
                    "tags": tags,
                })
            bosses.append({
                "key": ENCOUNTER_KEYS.get(encounter_id, f"encounter-{encounter_id}"),
                "id": as_int(encounter_id),
                "name": encounter["Name_lang"],
                "order": max(1, as_int(encounter["OrderIndex"])),
                "lootStatus": "official-zhCN-db2",
                "items": items,
            })
        raids.append({
            "key": raid_key,
            "id": as_int(instance_id),
            "name": raid_name,
            "bosses": bosses,
        })

    item_count = sum(len(boss["items"]) for raid in raids for boss in raid["bosses"])
    return {
        "schemaVersion": 2,
        "season": "12.1",
        "source": {
            "kind": "wow.tools.local-db2",
            "build": build,
            "locale": locale,
            "tables": ["JournalInstance", "JournalEncounter", "JournalEncounterItem", "Item", "ItemSparse", "Toy", "HouseDecor"],
        },
        "summary": {"raidCount": len(raids), "bossCount": sum(len(raid["bosses"]) for raid in raids), "itemCount": item_count},
        "raids": raids,
        "boe": {"key": "boe", "name": "装绑物品", "items": [], "allowFreeText": True},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:5055")
    parser.add_argument("--build", default="12.1.0.69189")
    parser.add_argument("--locale", default="zhCN")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    catalog = build_catalog(args.base_url, args.build, args.locale)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(catalog["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
