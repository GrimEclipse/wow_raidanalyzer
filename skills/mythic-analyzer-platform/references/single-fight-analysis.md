# Manual single-fight analysis

## Product flow

1. The user presses “获取数据”; there is no polling daemon or automatic report listener.
2. Read recent reports for the configured guild ID in `config/single_fight.json` (`774422` by default; `WCL_GUILD_ID` may override it).
3. Convert `report.startTime + fight.startTime` to `Asia/Shanghai`. Subtract the configured rollover hour before deriving `raidNightDate`, so after-midnight pulls stay on the correct progression day.
4. Keep Encounter fights lasting at least 20 seconds. When a report is opened, read `friendlyPlayers`, `friendlySpecs`, and master actors and show every candidate Pull.
5. Default to the last Pull on the selected progression day. Do not silently analyze unsupported encounters.
6. POST the explicit `reportCode` and `fightID` to `/api/single-fight/analyze`.

## Isolation and reuse

- `/api/analyze` and `/online` retain full-report behavior.
- A single-fight worker enters `analyzer_core.analysis_scope.single_fight_scope`; participating Boss plugins filter their normal fight list inside the current context only.
- The selected Boss plugin therefore produces the same per-fight judgement as the full-report analyzer. Never build a second simplified judgement engine in the shared module.
- Cache keys include schema, report, Fight, Boss identity, analysis options, the current ability-catalog digest, and a Boss implementation digest. Rule/code changes therefore invalidate old cache entries. `force=true` is the only supported cache bypass.
- Cache data belongs in `.single_fight_cache/` and is not versioned.

## Player ability catalog

- Runtime source: `config/player_abilities.json`.
- Current verified baseline (2026-08-13): 163 abilities / 170 IDs across all 13 classes, covering major/mid burst, personal and party defensives, external/utility, passive survival procs, Bloodlust, potions, interrupts, and control skills.
- Every ID must resolve from current WCL `gameData.ability`; run `py -3.9 tools/verify_player_abilities.py` after any edit.
- Verification proves the current ID/name pair. Event semantics still require a real report sample, especially passive aura triggers and replaced/hero-talent spells.
- Resolve composition first. Class-wide entries apply to that class; spec entries apply only when that exact WCL `friendlySpecs` value is present.
- Fetch `Casts` and `Buffs` in bulk. Filtering 100 selected IDs locally is still two logical requests when each stream fits one page; 100 separate ability queries is forbidden.
- Mythic+ timeline export consumes the same resolver and keeps only its legacy special-item fallback locally.

## Measured baseline

Real smoke test: guild report `fyCKZcJka7PqVh43`, Crown of the Cosmos Fight 23, 2026-07-23.

- Uncached end-to-end: about 59 seconds.
- Existing Crown Boss analysis: 55 logical GraphQL requests (field audit is the expensive portion).
- Added roster/player timeline: 2 logical requests, 0 per-spell queries, 52 matched events.
- Same Fight cache hit: about 1.1 seconds including report overview validation.

Treat these as an observed heavy sample, not an SLA. Different plugins and pagination produce different totals.

## Required checks

1. Unit-test raid-night dates around rollover.
2. Test the ContextVar filter leaves ordinary full-report calls unchanged.
3. Test roster resolution does not include absent classes/specs.
4. Run the WCL catalog verifier.
5. Smoke-test recent report discovery and one real supported Fight when credentials/network are available.
6. Confirm a second identical run reports `cacheHit: true`.
