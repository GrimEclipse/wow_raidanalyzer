"""Build the stable, static Zone 54 raid-leader guide payload.

The authored source is the player-facing truth. WCL discovery data is merged as
an evidence appendix and must never overwrite reviewed mechanic prose.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.wcl_zone54_discovery import BOSS_ZH, ENCOUNTERS, PHASE_DRAFTS


CATEGORY_LABELS = {
    "damageAbilities": "伤害",
    "playerDebuffs": "玩家 Debuff",
    "bossAuras": "Boss / add Aura",
    "enemyCasts": "敌方 Cast",
    "journalOnly": "仅手册",
}

ARENA_ASSETS = {
    "nakzali": "assets/raids/venomous_abyss/01-nakzali.png",
    "sentinels": "assets/raids/venomous_abyss/02-sentinels.png",
    "vashnik": "assets/raids/venomous_abyss/03-vashnik.png",
    "lostexplorers": "assets/raids/venomous_abyss/04-lostexplorers.jpg",
    "sszorak": "assets/raids/venomous_abyss/05-sszorak.jpg",
    "twinfangs": "assets/raids/venomous_abyss/06-twinfangs.jpg",
    "bargained": "assets/raids/venomous_abyss/07-bargained.jpg",
    "ulatek": "assets/raids/venomous_abyss/08-ulatek-arena.jpg",
}


def infer_tags(name, categories):
    text = name.lower()
    tags = []

    def add(value):
        if value not in tags:
            tags.append(value)

    if "damageAbilities" in categories:
        add("伤害")
    if "playerDebuffs" in categories:
        add("Debuff")
    if "bossAuras" in categories:
        add("Aura / 阶段")
    if "enemyCasts" in categories:
        add("Cast")
    if "journalOnly" in categories:
        add("仅手册")

    if any(word in text for word in (
        "ground", "patch", "slick", "residue", "globule", "wave", "shards",
        "eruption", "barrage", "bolt", "missile", "debris",
    )):
        add("疑似可躲 / 需复核")
    if any(word in text for word in (
        "rite", "surge", "deluge", "rain", "presence", "wail", "burst",
        "explosion", "nova", "maelstrom", "fury",
    )):
        add("AOE / 团队伤害")
    if any(word in text for word in (
        "sever", "injection", "claw", "strike", "bite", "thrash", "mutilate",
        "ravage", "slap", "smash",
    )):
        add("坦克 / 近战")
    if any(word in text for word in (
        "mark", "infection", "venom", "toxin", "hollow", "blight", "burn",
        "corrupted", "fractured",
    )):
        add("状态 / 层数")
    if any(word in text for word in (
        "awakening", "uncoiling", "stasis", "imbibe", "ascension",
        "gestation", "invoke", "ritual", "transition", "union",
    )):
        add("阶段信号")
    if any(word in text for word in ("fixation", "hunt", "pursuit")):
        add("点名 / 追踪")
    return tags or ["待分类"]


def compact_observation(item):
    if not item:
        return None
    return {
        "events": int(item.get("eventCount") or 0),
        "targets": int(item.get("uniqueTargetCount") or 0),
        "firstMs": int(item.get("firstMs") or 0),
        "lastMs": int(item.get("lastMs") or 0),
        "eventTypes": item.get("eventTypes") or {},
        "sources": item.get("sourceNames") or [],
        "provenance": item.get("provenance") or {},
    }


def build_spell_rows(boss, confirmed_spell_names=None, spell_overrides=None):
    confirmed_spell_names = confirmed_spell_names or {}
    spell_overrides = spell_overrides or {}
    aggregate = {}
    catalog = boss.get("spellCatalog") or {}
    for category in CATEGORY_LABELS:
        for row in catalog.get(category) or []:
            spell_id = int(row["spellID"])
            if spell_id < 1_000_000:
                continue
            target = aggregate.setdefault(spell_id, {
                "spellID": spell_id,
                "nameEn": row.get("name") or str(spell_id),
                "nameZh": confirmed_spell_names.get(str(spell_id)),
                "categories": [],
                "observedIn": {},
                "journal": {},
            })
            if category not in target["categories"]:
                target["categories"].append(category)
            journal = row.get("journal") or {}
            if journal:
                target["journal"].update(journal)
                target["nameEn"] = journal.get("name") or target["nameEn"]
            for difficulty, item in (row.get("observedIn") or {}).items():
                target["observedIn"][difficulty] = compact_observation(item)
            if category == "journalOnly":
                target["journal"].update({
                    "mythicOnly": bool(row.get("mythicOnly")),
                    "mythicMentioned": bool(row.get("mythicMentioned")),
                })
    for raw_spell_id, override in spell_overrides.items():
        spell_id = int(raw_spell_id)
        target = aggregate.setdefault(spell_id, {
            "spellID": spell_id,
            "nameEn": override.get("nameEn") or str(spell_id),
            "nameZh": confirmed_spell_names.get(str(spell_id)),
            "categories": [],
            "observedIn": {},
            "journal": {},
        })
        if override.get("nameEn"):
            target["nameEn"] = override["nameEn"]
        for category in override.get("categories") or ["journalOnly"]:
            if category in CATEGORY_LABELS and category not in target["categories"]:
                target["categories"].append(category)
        target["authoredTags"] = override.get("tags") or []
    rows = []
    for spell_id, row in aggregate.items():
        row["categoryLabels"] = [CATEGORY_LABELS[key] for key in row["categories"]]
        row["tags"] = row.pop("authoredTags", None) or infer_tags(
            row["nameEn"], row["categories"],
        )
        row["wowheadUrl"] = f"https://www.wowhead.com/ptr/spell={spell_id}"
        row["reviewStatus"] = "auto"
        rows.append(row)
    return sorted(rows, key=lambda row: (
        "heroic" not in row["observedIn"],
        "mythic" not in row["observedIn"],
        row["spellID"],
    ))


def phase_rows(key):
    return [
        {
            "key": f"phase-{index + 1}",
            "label": name.split(" ", 1)[0],
            "title": name,
            "trigger": trigger,
            "goal": note,
            "spellIDs": spell_ids,
        }
        for index, (name, trigger, spell_ids, note) in enumerate(PHASE_DRAFTS.get(key, []))
    ]


def build_document(discovery, authored, timelines=None):
    authored_bosses = authored.get("bosses") or {}
    confirmed_spell_names = authored.get("confirmedSpellNames") or {}
    timeline_bosses = (timelines or {}).get("bosses") or {}
    bosses = []
    order_by_key = {
        metadata["key"]: index + 1
        for index, metadata in enumerate(ENCOUNTERS.values())
    }
    metadata_by_key = {
        metadata["key"]: metadata
        for metadata in ENCOUNTERS.values()
    }
    for key in order_by_key:
        evidence_boss = (discovery.get("bosses") or {}).get(key) or {}
        source = authored_bosses.get(key) or {}
        metadata = metadata_by_key[key]
        boss = {
            "key": key,
            "order": order_by_key[key],
            "nameZh": BOSS_ZH.get(key, metadata["name"]),
            "nameEn": metadata["name"],
            "image": ARENA_ASSETS.get(key),
            "reviewStatus": source.get("reviewStatus") or "draft",
            "difficulty": source.get("difficulty") or "英雄日志基线 / 史诗差异待复核",
            "summary": source.get("summary") or (
                "该 Boss 已完成法术 ID 与 WCL 事件取数，详细带团流程尚待人工复核。"
            ),
            "energy": source.get("energy"),
            "phases": source.get("phases") or phase_rows(key),
            "mechanics": source.get("mechanics") or [],
            "timelines": timeline_bosses.get(key) or {},
            "spells": build_spell_rows(
                evidence_boss,
                confirmed_spell_names=confirmed_spell_names,
                spell_overrides=source.get("spellOverrides") or {},
            ),
            "journalSpellCount": len((evidence_boss.get("journal") or {}).get("spells") or []),
            "hasHeroicEvidence": bool((evidence_boss.get("evidence") or {}).get("heroic")),
            "hasMythicEvidence": bool((evidence_boss.get("evidence") or {}).get("mythic")),
            "expectedUntested": bool(metadata.get("expectedUntested")),
        }
        reviewed_ids = {
            int(spell_id)
            for mechanic in boss["mechanics"]
            for spell_id in mechanic.get("spellIDs") or []
        }
        for spell in boss["spells"]:
            if spell["spellID"] in reviewed_ids:
                spell["reviewStatus"] = "reviewed"
        bosses.append(boss)

    return {
        "schemaVersion": 1,
        "zoneID": int(authored.get("zoneID") or 54),
        "raidNameZh": authored.get("raidNameZh") or "烈毒之渊",
        "raidNameEn": authored.get("raidNameEn") or "The Venomous Abyss",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sources": discovery.get("sources") or {},
        "bosses": bosses,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--discovery", default="docs/zone54_spell_discovery.json")
    parser.add_argument("--source", default="docs/zone54_raid_guide_source.json")
    parser.add_argument("--timelines", default="docs/zone54_boss_timelines.json")
    parser.add_argument("--output", default="assets/vendor/zone54-raid-guide-data.js")
    args = parser.parse_args()

    discovery = json.loads(Path(args.discovery).read_text(encoding="utf-8"))
    authored = json.loads(Path(args.source).read_text(encoding="utf-8"))
    timeline_path = Path(args.timelines)
    timelines = (
        json.loads(timeline_path.read_text(encoding="utf-8"))
        if timeline_path.exists()
        else {}
    )
    document = build_document(discovery, authored, timelines)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    output.write_text(
        "window.ZONE54_RAID_GUIDE=" + payload + ";\n",
        encoding="utf-8",
    )
    print(
        f"[zone54-guide] wrote {output}: {len(document['bosses'])} bosses, "
        f"{sum(len(boss['spells']) for boss in document['bosses'])} spell rows",
        flush=True,
    )


if __name__ == "__main__":
    main()
