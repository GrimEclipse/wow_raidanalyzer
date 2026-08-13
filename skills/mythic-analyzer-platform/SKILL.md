---
name: mythic-analyzer-platform
description: Maintain the Mythic Analyzer platform architecture, shared contracts, frontend report routing, standalone raid tools, local server routes, data storage, and offline packaging. Use when changing global behavior shared by multiple Boss plugins or reorganizing project structure; do not use it for the mechanics of one Boss.
---

# Mythic Analyzer Platform

Keep the product shell independent from Boss adjudication.

## Start here

1. Read `references/platform-map.md`.
2. For manual guild-report discovery, isolated single-fight analysis, cache behavior, or the shared player ability catalog, read `references/single-fight-analysis.md`.
3. For capability or configuration changes, also read `references/analysis-capabilities.md` and `references/configurable-analysis-architecture.md`.
4. For adding a plugin, read `references/plugin-generation.md`.
5. Touch only the shared layer required by the request. Put Boss-specific rules in the Boss backend and frontend plugin directories.

## Architecture rules

- Treat `boss_catalog.json` as the public registration contract.
- Keep analysis orchestration in `analyzer_core/`; never import one Boss plugin from another.
- Keep the report selector generic. It may inspect `meta.raidKey` and `meta.bossKey`, but must not know spell IDs or mechanic field names.
- Put a specialized report under `frontend/report/plugins/<raidKey>/<bossKey>/`.
- Use `frontend/report/generic.html` only for capability-shaped data shared across Bosses.
- Keep raid guide, cooldown timeline, analysis runner, and IQ notebook as separate tools under `frontend/tools/`.
- Keep `/single-fight` isolated from `/online`: the former selects exactly one Fight and may reuse a cache; the latter keeps the original full-report behavior.
- Treat `config/player_abilities.json` as the runtime source of truth for player burst, defensive, utility, interrupt, and control evidence. Do not copy new spell-ID lists into individual tools.
- Resolve the roster and spec first, then select catalog entries. Query WCL Casts/Buffs as bulk event streams; never issue one WCL request per configured player spell.
- Preserve friendly routes in `server.py`, `offline_server.py`, and `host/OfflineHost.cs`.
- Update `build_offline_package.ps1` whenever a runtime directory moves.

## Verification

Run Python unit tests, JavaScript syntax checks, route smoke tests, and a root-directory audit. Verify at least one specialized report and one generic report with real JSON.
