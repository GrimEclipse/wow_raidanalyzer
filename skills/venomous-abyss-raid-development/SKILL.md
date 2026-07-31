---
name: venomous-abyss-raid-development
description: Maintain the 12.1 Venomous Abyss raid leader guide and seed future Boss analyzers from encounter flow, journal text, WCL timelines, damage IDs, cast IDs, aura IDs, and Mythic-only differences. Use for bosses 1–8, guide content, spell discovery, timeline transitions, or initial adjudication design.
---

# Venomous Abyss Raid Development

Keep raid-leader guidance and developer evidence distinct but linked.

## Select the Boss

Read the matching file in `references/bosses/`. Do not load all source dumps unless the task spans multiple Bosses.

## Update workflow

1. Treat user-authored encounter flow and confirmed Chinese names as authoritative.
2. Use `references/source-data/raid-guide-source.json` as the page source for Bosses already structured.
3. Use the project-root `zone54_spell_discovery.md` for the readable spell inventory; inspect the large JSON in `references/source-data/spell-discovery.json` only for exact rows.
4. Use journal and timeline JSON to corroborate phases, casts, energy transitions, debuffs, damage, summons, and Mythic differences.
5. In raid-leader copy, explain what the raid does and what wipes the pull. Keep spell-ID/evidence details in the developer section.
6. Do not invent a Mythic Ula'tek timeline: the final Boss conventionally has no test logs.
7. Rebuild `assets/vendor/zone54-raid-guide-data.js` with `tools/build_zone54_raid_guide.py` after source changes.
8. Verify `frontend/tools/raid-guide/index.html` and its icon tooltip behavior.

## Boss status

- Bosses 1–7 have structured guide material and are candidates for analyzer design.
- Boss 7 has a complete authored P1/P2/intermission/P3 flow; its current Heroic evidence only covers the opening of P3, and its Mythic evidence ends in early P2.
- Boss 8 Ula'tek is a journal/manual-design target without test-log expectations.
