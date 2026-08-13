# Platform map

## Shared runtime

- `analyze.py`: CLI compatibility entry.
- `server.py`: development HTTP API and static route host.
- `offline_server.py`: Python offline host.
- `host/OfflineHost.cs`: zero-dependency packaged host.
- `analyzer_core/`: catalog, contracts, runner, WCL path policy, notebook store, and shared spell/spec configuration.
- `boss_catalog.json`: backend plugin registration, configuration schema, and frontend capability declarations.

## Frontend

- `frontend/report/index.html`: reads analysis identity and resolves a Boss frontend plugin.
- `frontend/core/report-plugin-runtime.js`: validates plugin keys and loads the descriptor by convention.
- `frontend/report/generic.html`: shared wipe and avoidable-damage renderer.
- `frontend/report/plugins/<raid>/<boss>/plugin.js`: one Boss descriptor.
- `frontend/report/plugins/<raid>/<boss>/report.html`: optional specialized report.
- `frontend/tools/raid-guide/`: raid leader handbook.
- `frontend/tools/raid-cooldowns/`: raid cooldown timeline search/export.
- `frontend/tools/analysis-runner/`: UI-driven WCL analysis.
- `frontend/tools/single-fight/`: manual guild report/day/Fight selection, single-fight jobs, cache status, and roster-filtered player timeline.
- `frontend/tools/mythic-dungeon/`: stable Mythic+ route samples and per-Pull timelines.
- `frontend/offline/`: offline package landing page.

## Stable public routes

Use `/report`, `/online`, `/cooldowns`, `/mythic-dungeon`, `/raid-guide`, `/loot`, and `/audit` on every host. `/single-fight` is intentionally online-server-only because it requires authenticated WCL credentials and background jobs; do not advertise it in the offline package. Physical paths may change; update the applicable hosts and packaging together.

## Shared player ability evidence

- `config/player_abilities.json`: current WCL-verified spell IDs and categories.
- `analyzer_core/player_abilities.py`: validates and resolves the catalog from a concrete roster/spec list.
- `tools/verify_player_abilities.py`: read-only verification against WCL GameData.
- `analyzer_core/analysis_scope.py`: thread-local one-Fight filter; lets single-fight jobs reuse Boss rules without changing full-report analysis.
- `analyzer_core/single_fight.py`: guild report discovery, China raid-night grouping, cache, and bulk player Casts/Buffs extraction.

## Data

Generated WCL JSON belongs in `data/`. `data/wcl_hardcore_api.json` is the compatibility sample, not a root-level runtime file.

Audited, frontend-shipped Mythic+ reference samples belong in `assets/samples/` and are indexed by `mythic_dungeon_manifest.json`; they are deliberately versioned rather than fetched on every page load.
