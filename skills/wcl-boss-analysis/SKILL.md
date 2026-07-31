---
name: wcl-boss-analysis
description: Develop and review one Boss-specific WCL analysis plugin, including evidence collection, configurable adjudication, wipe attribution, spatial replay, mistake output, and its dedicated frontend renderer. Use when a request names a Boss, spell, mechanic, death cause, or replay judgment.
---

# WCL Boss Analysis

Build evidence first, then apply configurable responsibility rules.

## Workflow

1. Identify the Boss and read only its reference directory.
2. Read `references/common/debuff-fade-attribution.md` when coordinates or aura endpoints are involved.
3. Confirm the WCL event source, timestamp semantics, actor IDs, and missing fields before writing judgment logic.
4. Separate:
   - raw evidence;
   - derived facts;
   - configurable adjudication;
   - scoring/export.
5. Register backend capabilities in `boss_catalog.json`.
6. Add or update `frontend/report/plugins/<raidKey>/<bossKey>/plugin.js`. Use a dedicated report page only when the generic renderer cannot represent the mechanic.
7. Test the Boss plugin without changing unrelated Boss output.

## Existing references

- 奥蕾莉亚 / 宇宙之冕: `references/crown_of_the_cosmos/`
- 光盲先锋军: `references/lightblinded_vanguard/`
- 通用光环消失与位置归因: `references/common/`

Never convert absent WCL coordinates into a confident player fault. Preserve sampling offsets and expose evidence gaps internally even if the end-user UI hides confidence jargon.
