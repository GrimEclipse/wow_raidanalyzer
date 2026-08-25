"""Extract the Patch 12.1 raid journal spell catalog from a datamined article.

The output is evidence for discovery, not a final mechanic verdict.  WCL
observations remain the source of truth for event types and timings.
"""

import argparse
import html
import json
import re
from pathlib import Path

SOURCE_URL = (
    "https://www.wowhead.com/news/"
    "preview-the-patch-12-1-dungeon-journal-raid-lair-and-dungeons-381960"
)

BOSSES = [
    ("nakzali", 3470, "Nek'zali the Soulcoiler"),
    ("sentinels", 3445, "Entombed Sentinels"),
    ("lostexplorers", 3497, "The Lost Explorers"),
    ("vashnik", 3455, "Vashnik the Malignant"),
    ("sszorak", 3420, "Sszorak"),
    ("twinfangs", 3421, "The Twin Fangs"),
    ("bargained", 3429, "The Coiled Altar"),
    ("ulatek", 3492, "Ula'tek"),
]

REFERENCE_VIDEOS = [
    {"boss": "nakzali", "bvid": "BV1vETC6vEw2", "title": "H1-盘魂者内克扎莉"},
    {"boss": "sentinels", "bvid": "BV1Z3TC6uEdU", "title": "H2-陵寝哨兵"},
    {"boss": "lostexplorers", "bvid": "BV1FuTC6rEcs", "title": "H3-迷失的探险者"},
    {"boss": "vashnik", "bvid": "BV1Z3TC6uE38", "title": "H4-万毒邪祟者瓦什尼克"},
    {"boss": "sszorak", "bvid": "BV12rMJ6sEWh", "title": "H5-斯索拉克"},
    {"boss": "twinfangs", "bvid": "BV12rMJ6sEg3", "title": "H6-双子毒牙"},
    {"boss": "bargained", "bvid": "BV11rMJ6sEoc", "title": "H7-盘卷祭坛"},
]

JOURNAL_DIFFICULTY_OVERRIDES = {
    # The original preview-news HTML flattens some difficulty badges. These
    # overrides come from the current Chinese encounter-journal NPC pages.
    "lostexplorers": {
        "source": "https://www.wowhead.com/cn/npc=267077/morzahi",
        "spellIDs": [],
        "notes": [
            "Relic Rupture: On Mythic difficulty, breaking a crate also inflicts Shadow damage to players within 15 yards."
        ],
    },
    "sszorak": {
        "source": "https://www.wowhead.com/cn/npc=257347/sszorak",
        "spellIDs": [1296898, 1297367, 1297414, 1297707],
        "notes": [
            "Serpent's Fury: On Mythic difficulty, Sszorak marks a player and gains rage over time. When at least 14 players are within 8 yards of the marked player, Sszorak casts To the Slaughter and consumes his rage. At 100 rage he gains Unbound Ferocity."
        ],
    },
    "twinfangs": {
        "source": "https://www.wowhead.com/cn/npc=257361/vexhul",
        "spellIDs": [1303230, 1303378, 1308356, 1308385],
        "nonMythicIDs": [1290516],
        "notes": [
            "Eternal Venom: On Mythic difficulty, a player who dies while afflicted creates additional Caustic Globules.",
            "Blood Torrent: On Mythic difficulty, each Caustic Globule is protected by a Barbed Bulwark. Interrupting Protected Gestation destroys the bulwark.",
            "Rouse the Brood: On Mythic difficulty, Ithraz summons Broodlings that repeatedly cast Visceral Burst. Interrupting the cast forces the Broodling to retreat.",
            "Ravenous Feast: On Mythic difficulty, consumed Eternal Venom creates Tainted Blood founts that must have their healing absorption removed before they expire.",
        ],
    },
    "bargained": {
        "source": (
            "https://www.wowhead.com/cn/guide/midnight/raids/"
            "venomous-abyss-coiled-altar-boss-strategy-abilities"
        ),
        "spellIDs": [],
        "nonMythicIDs": [
            1283623, 1283631, 1285643, 1285911, 1286399, 1286441,
            1287718, 1304032, 1304033,
        ],
        "notes": [
            "Toxic Deluge: On Mythic difficulty, venom mutations can detonate nearby Coalesced Venom and create additional chain-reaction pressure.",
            "Guillotine: On Mythic difficulty, Guillotined is permanent for the remainder of the encounter.",
            "Axegrinder: On Mythic difficulty, Axegrinders do not despawn and permanently reduce usable arena space.",
            "Manifestation of Dread: On Mythic difficulty, each manifestation is visible only to its fixated player and periodically refixates; contact triggers Malevolent Resonance.",
            "Spiritcackle: On Mythic difficulty, the summoned spirit has a 99% damage-reduction Spirit Shield that must be weakened with Gloombomb.",
            "Spirit Erasure: On Mythic difficulty, intercepting a fragment increases Spirit Erasure damage taken by 20% for 5 seconds.",
        ],
    },
    "ulatek": {
        "source": (
            "https://www.wowhead.com/guide/midnight/raids/"
            "venomous-abyss-ulatek-boss-strategy-abilities"
        ),
        "spellIDs": [1299650, 1307612, 1307635],
        "nonMythicIDs": [
            1287036, 1290779, 1295360, 1298367, 1301117,
            1301268, 1301800, 1303414, 1306086,
        ],
        "notes": [
            "Hardened, Noxious Shell, and Noxious Splash are Mythic-only parts of the Blightscale Spawn package.",
            "On Mythic difficulty, Volatile Purge also sends venomous waves across the arena.",
        ],
    },
}

SPELL_LINK = re.compile(
    r'href=\\"(?:https://www\.wowhead\.com)?/(?:cn|ptr)/spell=(?P<id>\d+)'
    r'(?:/[^\\"]*)?\\">(?P<name>[^<]+)<',
    re.IGNORECASE,
)


def normalized_source(raw):
    return (
        raw.replace("\\/", "/")
        .replace("\\r\\n", "\n")
        .replace("\\n", "\n")
        .replace("\\t", " ")
    )


def boss_segments(raw):
    positions = []
    for key, encounter_id, title in BOSSES:
        marker = f'[tabs name=\\"{title}-'
        index = raw.find(marker)
        if index >= 0:
            positions.append((index, key, encounter_id, title))
    positions.sort()
    result = {}
    for index, (_, key, encounter_id, title) in enumerate(positions):
        start = positions[index][0]
        next_tabs = raw.find('[tabs name=\\"', start + 20)
        end = next_tabs if next_tabs >= 0 else len(raw)
        result[key] = {
            "encounterID": encounter_id,
            "name": title,
            "raw": raw[start:end],
        }
    return result


def clean_text(value):
    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\[[^\]]+\]", " ", value)
    value = value.replace("\\", "")
    return re.sub(r"\s+", " ", value).strip(" :.-")


def extract_explicit_mythic_notes(segment):
    lines = segment.splitlines()
    notes = []
    for line in lines:
        if "On Mythic difficult" not in line and "On Mythic Difficult" not in line:
            continue
        note = clean_text(line)
        if note and note not in notes:
            notes.append(note)
    return notes


def extract_spells(segment):
    spells = {}
    for match in SPELL_LINK.finditer(segment):
        spell_id = int(match.group("id"))
        name = html.unescape(match.group("name")).strip().strip("[]")
        row = spells.setdefault(
            spell_id,
            {
                "spellID": spell_id,
                "name": name,
                "journalOccurrences": 0,
                "mythicOnly": False,
                "mythicMentioned": False,
            },
        )
        row["journalOccurrences"] += 1
        context = segment[max(0, match.start() - 500):match.end() + 900]
        if "(Mythic)" in context or "Mythic difficulty" in context or "Mythic Difficulty" in context:
            row["mythicMentioned"] = True
        if (
            "(Mythic)" in context
            and "(Heroic, Mythic)" not in context
            and "(Mythic, Heroic)" not in context
            and "(Normal, Mythic)" not in context
            and "(Raid Finder, Mythic)" not in context
        ):
            row["mythicOnly"] = True
    return sorted(spells.values(), key=lambda row: (row["spellID"], row["name"]))


def apply_difficulty_overrides(key, boss):
    override = JOURNAL_DIFFICULTY_OVERRIDES.get(key)
    if not override:
        return boss
    mythic_ids = set(override.get("spellIDs") or [])
    non_mythic_ids = set(override.get("nonMythicIDs") or [])
    for spell in boss.get("spells") or []:
        if int(spell["spellID"]) in mythic_ids:
            spell["mythicOnly"] = True
            spell["mythicMentioned"] = True
        if int(spell["spellID"]) in non_mythic_ids:
            spell["mythicOnly"] = False
    notes = boss.setdefault("mythicDifferences", [])
    for note in override.get("notes") or []:
        if note not in notes:
            notes.append(note)
    boss["difficultySource"] = override.get("source")
    return boss


def extract_journal(raw, source_url):
    normalized = normalized_source(raw)
    segments = boss_segments(normalized)
    bosses = {}
    for key, encounter_id, title in BOSSES:
        segment = segments.get(key)
        if not segment:
            bosses[key] = {
                "encounterID": encounter_id,
                "name": title,
                "available": False,
                "spells": [],
                "mythicDifferences": [],
            }
            continue
        bosses[key] = apply_difficulty_overrides(key, {
            "encounterID": encounter_id,
            "name": title,
            "available": True,
            "spells": extract_spells(segment["raw"]),
            "mythicDifferences": extract_explicit_mythic_notes(segment["raw"]),
        })
    return {
        "schemaVersion": 1,
        "zoneID": 53,
        "source": {
            "url": source_url,
            "kind": "datamined-dungeon-journal",
        },
        "referenceVideos": [
            {
                **row,
                "url": f"https://www.bilibili.com/video/{row['bvid']}",
                "subtitleTrackAvailable": False,
            }
            for row in REFERENCE_VIDEOS
        ],
        "bosses": bosses,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-url", default=SOURCE_URL)
    parser.add_argument("--input-html", help="使用已下载页面，避免再次联网")
    parser.add_argument(
        "--output",
        default="skills/venomous-abyss-raid-development/references/source-data/journal.json",
    )
    args = parser.parse_args()

    if args.input_html:
        raw = Path(args.input_html).read_text(encoding="utf-8")
    else:
        import requests

        response = requests.get(args.source_url, timeout=60)
        response.raise_for_status()
        raw = response.text

    document = extract_journal(raw, args.source_url)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"[journal] wrote {output}; "
        f"{sum(len(row['spells']) for row in document['bosses'].values())} spell rows",
        flush=True,
    )


if __name__ == "__main__":
    main()
