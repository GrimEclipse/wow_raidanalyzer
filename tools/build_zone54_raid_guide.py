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

HERO_ASSETS = {
    "nakzali": "assets/raids/venomous_abyss/01-nakzali-hero.jpg",
    "sentinels": "assets/raids/venomous_abyss/02-sentinels-hero.jpg",
    "vashnik": "assets/raids/venomous_abyss/03-vashnik-hero.jpg",
    "lostexplorers": "assets/raids/venomous_abyss/04-lostexplorers-hero.jpg",
    "sszorak": "assets/raids/venomous_abyss/05-sszorak-hero.jpg",
    "twinfangs": "assets/raids/venomous_abyss/06-twinfangs-hero.jpg",
    "bargained": "assets/raids/venomous_abyss/07-bargained-hero.jpg",
    "ulatek": "assets/raids/venomous_abyss/08-ulatek-hero.jpg",
    "nymrissa_wavecaller": "assets/raids/tidebound_grotto/01-nymrissa.jpg",
}

MECHANIC_ALERT_RULES = (
    (
        "坦克预警",
        ("坦克", "换坦", "对坦", "坦克正面", "头前", "嘲讽", "接圈"),
    ),
    (
        "伤害输出预警",
        (
            "DPS", "转火", "优先小怪", "优先大怪", "破盾", "打破护盾",
            "击杀时限", "双目标", "同步压血", "救人",
        ),
    ),
    (
        "治疗预警",
        (
            "全团 AOE", "全团AOE", "固定团伤", "全团伤害", "团队伤害",
            "治疗轴", "治疗排轴", "全屏", "不可避免的全团",
        ),
    ),
    (
        "控制/打断预警",
        (
            "控制组", "打断组", "可打断", "减速/控制", "持续打断",
            "控制小怪", "打断转火",
        ),
    ),
)

TIMELINE_TERM_RENAMES = {
    "灵魂点燃": "盘魂点燃",
    "苏醒仪式": "觉醒仪式",
    "苏醒纽带": "觉醒之缚",
    "解缚之怒": "溃散之怒",
    "变换原毒": "变幻的原型毒液",
    "瘟疫泡沫": "滴毒之牙",
    "呼啸漩涡": "呼啸旋涡",
    "毒液激流": "剧毒涌动",
    "缠绕脓液": "盘卷脓液",
    "熔炉之牙": "盘卷祭坛之牙",
    "死亡进军": "恐惧行军",
    "精魂狂啸": "精魂狂笑",
    "幽魂炸弹": "幽暗炸弹",
    "熔炉亵渎": "盘卷祭坛亵渎",
    "诱惑水泡": "诱人水泡",
    "Water Flurry": "冰刃乱舞",
    "Frost Barrage": "冰霜弹幕",
    "Tidepiercer's Rush": "激荡漩涡",
    "Pop!": "嘭！",
    "Turbulent Gusts": "湍流侧风",
    "To the Slaughter": "大开杀戒",
    "Serpent's Fury": "毒蛇之怒",
    "Virulence": "剧毒",
    "Unbound Ferocity": "怒不可遏",
    "无拘狂暴": "怒不可遏",
}


def normalize_timeline_terms(value):
    if isinstance(value, str):
        for old_name, official_name in TIMELINE_TERM_RENAMES.items():
            value = value.replace(old_name, official_name)
        return value
    if isinstance(value, list):
        return [normalize_timeline_terms(item) for item in value]
    if isinstance(value, dict):
        return {
            key: normalize_timeline_terms(item)
            for key, item in value.items()
        }
    return value

ARENA_ASSETS = {
    "nakzali": "assets/raids/venomous_abyss/01-nakzali.png",
    "sentinels": "assets/raids/venomous_abyss/02-sentinels.png",
    "vashnik": "assets/raids/venomous_abyss/03-vashnik.png",
    "lostexplorers": "assets/raids/venomous_abyss/04-lostexplorers.jpg",
    "sszorak": "assets/raids/venomous_abyss/05-sszorak.jpg",
    "twinfangs": "assets/raids/venomous_abyss/06-twinfangs.jpg",
    "bargained": "assets/raids/venomous_abyss/07-bargained.jpg",
    "ulatek": "assets/raids/venomous_abyss/08-ulatek-arena.jpg",
    "nymrissa_wavecaller": "assets/raids/tidebound_grotto/01-nymrissa.jpg",
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


def present_mechanics(mechanics):
    """Keep only actionable warning badges in the shipped guide payload."""
    result = []
    for mechanic in mechanics:
        row = json.loads(json.dumps(mechanic))
        searchable = " ".join(
            str(value)
            for value in (
                row.get("title") or "",
                row.get("summary") or "",
                *(row.get("roles") or []),
                *(row.get("tags") or []),
                *(row.get("leaderDetails") or []),
            )
        )
        explicit_alerts = row.get("alerts")
        row["alerts"] = list(explicit_alerts) if explicit_alerts is not None else [
            label
            for label, keywords in MECHANIC_ALERT_RULES
            if any(keyword in searchable for keyword in keywords)
        ]
        row.pop("roles", None)
        row.pop("tags", None)
        result.append(row)
    return result


def build_spell_rows(
    boss,
    confirmed_spell_names=None,
    spell_overrides=None,
    required_spell_ids=None,
):
    confirmed_spell_names = confirmed_spell_names or {}
    spell_overrides = spell_overrides or {}
    required_spell_ids = required_spell_ids or set()
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
        for difficulty, item in (override.get("observedIn") or {}).items():
            target["observedIn"][difficulty] = compact_observation(item)
        target["authoredTags"] = override.get("tags") or []
    for raw_spell_id in required_spell_ids:
        spell_id = int(raw_spell_id)
        confirmed_name = confirmed_spell_names.get(str(spell_id))
        aggregate.setdefault(spell_id, {
            "spellID": spell_id,
            "nameEn": confirmed_name or str(spell_id),
            "nameZh": confirmed_name,
            "categories": ["journalOnly"],
            "observedIn": {},
            "journal": {},
        })
    rows = []
    for spell_id, row in aggregate.items():
        row["categoryLabels"] = [CATEGORY_LABELS[key] for key in row["categories"]]
        row["tags"] = row.pop("authoredTags", None) or infer_tags(
            row["nameEn"], row["categories"],
        )
        row["wowheadUrl"] = f"https://www.wowhead.com/cn/spell={spell_id}"
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


def enrich_timelines(timelines, evidence_boss, confirmed_source_names=None):
    if not timelines:
        return {}
    confirmed_source_names = confirmed_source_names or {}
    result = normalize_timeline_terms(json.loads(json.dumps(timelines)))
    source_index = {"heroic": {}, "mythic": {}}
    catalog = evidence_boss.get("spellCatalog") or {}
    for category in CATEGORY_LABELS:
        for row in catalog.get(category) or []:
            spell_id = int(row.get("spellID") or 0)
            for difficulty, observation in (row.get("observedIn") or {}).items():
                if difficulty not in source_index:
                    continue
                names = [
                    str(name) for name in (observation.get("sourceNames") or [])
                    if name
                ]
                if names:
                    source_index[difficulty].setdefault(spell_id, set()).update(names)

    for difficulty, timeline in result.items():
        if difficulty not in source_index:
            continue
        expanded_events = list(timeline.get("events") or [])
        for series in timeline.pop("eventSeries", []) or []:
            template = {
                key: value
                for key, value in series.items()
                if key != "timesMs"
            }
            expanded_events.extend(
                {**template, "timeMs": int(time_ms)}
                for time_ms in series.get("timesMs") or []
            )
        deduplicated = {}
        for event in expanded_events:
            key = (int(event.get("timeMs") or 0), int(event.get("spellID") or 0))
            deduplicated[key] = event
        timeline["events"] = sorted(
            deduplicated.values(),
            key=lambda event: int(event.get("timeMs") or 0),
        )
        for event in timeline.get("events") or []:
            spell_id = int(event.get("spellID") or 0)
            names = sorted(source_index[difficulty].get(spell_id) or [])
            if not event.get("sourceName") and len(names) == 1:
                event["sourceName"] = names[0]
            for child in event.get("children") or []:
                child_spell_id = int(child.get("spellID") or 0)
                child_names = sorted(
                    source_index[difficulty].get(child_spell_id) or []
                )
                if not child.get("sourceName") and len(child_names) == 1:
                    child["sourceName"] = child_names[0]
            if not event.get("sourceName"):
                child_sources = {
                    child.get("sourceName")
                    for child in event.get("children") or []
                    if child.get("sourceName")
                }
                if len(child_sources) == 1:
                    event["sourceName"] = child_sources.pop()
            if event.get("sourceName") in confirmed_source_names:
                event["sourceName"] = confirmed_source_names[event["sourceName"]]
            for child in event.get("children") or []:
                if child.get("sourceName") in confirmed_source_names:
                    child["sourceName"] = confirmed_source_names[child["sourceName"]]
    return result


def build_document(discovery, authored, timelines=None):
    authored_bosses = authored.get("bosses") or {}
    confirmed_spell_names = authored.get("confirmedSpellNames") or {}
    confirmed_source_names = authored.get("confirmedSourceNames") or {}
    timeline_bosses = (timelines or {}).get("bosses") or {}
    bosses = []
    metadata_rows = [
        {**metadata, "encounterID": encounter_id, "order": index + 1, "raidKey": "venomous_abyss"}
        for index, (encounter_id, metadata) in enumerate(ENCOUNTERS.items())
    ]
    metadata_rows.extend(authored.get("extraBosses") or [])
    for metadata in metadata_rows:
        key = metadata["key"]
        evidence_boss = (discovery.get("bosses") or {}).get(key) or {}
        source = authored_bosses.get(key) or {}
        raid = next(
            (row for row in (authored.get("raids") or []) if row["key"] == metadata.get("raidKey")),
            {},
        )
        boss = {
            "key": key,
            "order": int(metadata.get("order") or 1),
            "raidKey": metadata.get("raidKey") or "venomous_abyss",
            "raidNameZh": raid.get("nameZh") or authored.get("raidNameZh") or "烈毒之渊",
            "raidNameEn": raid.get("nameEn") or authored.get("raidNameEn") or "The Venomous Abyss",
            "encounterID": int(metadata.get("encounterID") or 0),
            "nameZh": BOSS_ZH.get(key, metadata.get("nameZh") or metadata.get("name")),
            "nameEn": metadata.get("nameEn") or metadata.get("name"),
            "image": HERO_ASSETS.get(key),
            "arenaImage": ARENA_ASSETS.get(key),
            "reviewStatus": source.get("reviewStatus") or "draft",
            "difficulty": source.get("difficulty") or "英雄日志基线 / 史诗差异待复核",
            "summary": source.get("summary") or (
                "该 Boss 已完成法术 ID 与 WCL 事件取数，详细带团流程尚待人工复核。"
            ),
            "energy": source.get("energy"),
            "phases": source.get("phases") or phase_rows(key),
            "mechanics": present_mechanics(source.get("mechanics") or []),
            "timelines": enrich_timelines(
                timeline_bosses.get(key) or {},
                evidence_boss,
                confirmed_source_names=confirmed_source_names,
            ),
            "spells": build_spell_rows(
                evidence_boss,
                confirmed_spell_names=confirmed_spell_names,
                spell_overrides=source.get("spellOverrides") or {},
                required_spell_ids={
                    int(spell_id)
                    for section in (
                        *(source.get("phases") or []),
                        *(source.get("mechanics") or []),
                    )
                    for spell_id in (
                        *(section.get("spellIDs") or []),
                        *(section.get("leaderSpellIDs") or []),
                    )
                },
            ),
            "journalSpellCount": len((evidence_boss.get("journal") or {}).get("spells") or []),
            "hasHeroicEvidence": bool(
                (evidence_boss.get("evidence") or {}).get("heroic")
                or (timeline_bosses.get(key) or {}).get("heroic")
            ),
            "hasMythicEvidence": bool(
                (evidence_boss.get("evidence") or {}).get("mythic")
                or (timeline_bosses.get(key) or {}).get("mythic")
            ),
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
        "schemaVersion": 2,
        "zoneID": int(authored.get("zoneID") or 54),
        "guideNameZh": authored.get("guideNameZh") or "12.1 团长战斗手册",
        "raids": authored.get("raids") or [],
        "raidNameZh": authored.get("raidNameZh") or "烈毒之渊",
        "raidNameEn": authored.get("raidNameEn") or "The Venomous Abyss",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sources": discovery.get("sources") or {},
        "bosses": bosses,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--discovery",
        default="skills/venomous-abyss-raid-development/references/source-data/spell-discovery.json",
    )
    parser.add_argument(
        "--source",
        default="skills/venomous-abyss-raid-development/references/source-data/raid-guide-source.json",
    )
    parser.add_argument(
        "--timelines",
        default="skills/venomous-abyss-raid-development/references/source-data/boss-timelines.json",
    )
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
