"""Extract the Patch 12.1 raid journal spell catalog from a datamined article.

The output is evidence for discovery, not a final mechanic verdict.  WCL
observations remain the source of truth for event types and timings.
"""

import argparse
import html
import json
import re
from pathlib import Path

import requests


SOURCE_URL = (
    "https://www.wowhead.com/news/"
    "preview-the-patch-12-1-dungeon-journal-raid-lair-and-dungeons-381960"
)

BOSSES = [
    ("nakzali", 53470, "Nek'zali the Soulcoiler"),
    ("sentinels", 53445, "Entombed Sentinels"),
    ("lostexplorers", 53497, "The Lost Explorers"),
    ("vashnik", 53455, "Vashnik the Malignant"),
    ("sszorak", 53420, "Sszorak"),
    ("twinfangs", 53421, "The Twin Fangs"),
    ("bargained", 53429, "The Coiled Altar"),
    ("ulatek", 53492, "Ula'tek"),
]

REFERENCE_VIDEOS = [
    {"boss": "nakzali", "bvid": "BV1vETC6vEw2", "title": "H1-盘魂者内克扎莉"},
    {"boss": "sentinels", "bvid": "BV1Z3TC6uEdU", "title": "H2-陵寝哨兵"},
    {"boss": "vashnik", "bvid": "BV1Z3TC6uE38", "title": "H3-万毒邪祟者瓦什尼克"},
    {"boss": "lostexplorers", "bvid": "BV1FuTC6rEcs", "title": "H4-迷失的探险者"},
    {"boss": "sszorak", "bvid": "BV12rMJ6sEWh", "title": "H5-斯索拉克"},
    {"boss": "twinfangs", "bvid": "BV12rMJ6sEg3", "title": "H6-双子毒牙"},
    {"boss": "bargained", "bvid": "BV11rMJ6sEoc", "title": "H7-盘卷祭坛"},
]

SPELL_LINK = re.compile(
    r'href=\\"(?:https://www\.wowhead\.com)?/ptr/spell=(?P<id>\d+)'
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
        bosses[key] = {
            "encounterID": encounter_id,
            "name": title,
            "available": True,
            "spells": extract_spells(segment["raw"]),
            "mythicDifferences": extract_explicit_mythic_notes(segment["raw"]),
        }
    return {
        "schemaVersion": 1,
        "zoneID": 54,
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
    parser.add_argument("--output", default="docs/zone54_journal.json")
    args = parser.parse_args()

    if args.input_html:
        raw = Path(args.input_html).read_text(encoding="utf-8")
    else:
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
