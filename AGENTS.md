# Repository architecture guardrails

Read this file before editing analysis code.

- One Boss equals one backend Python module under `boss_plugins/<raid>/`. The module owns that Boss's spell IDs, mechanic rules, analyzer, configuration, and court profile.
- Never create a multi-Boss logic container such as `progression.py` or `court_profiles.py`.
- Put only reusable, Boss-agnostic helpers in `boss_plugins/common.py`, a raid-level `shared.py`, or a generic runtime module. Shared modules must not contain Boss spell IDs or Boss adjudication logic.
- Keep the frontend selector and generic runtime ignorant of Boss mechanics.
- The application is served by `server.py` only. Do not restore offline servers, offline hosts, or offline package builders.
- The live raid calendar, attendance, and loot-allocation store is `data/raid_calendar.db`. Canonical routes are `/raid-calendar` and `/api/raid-calendar`; `/loot` and `/api/loot` are compatibility aliases.
- The old `scoreboard` name and the `/verdicts` application are retired. Do not restore them. Boss-local verdict fields are analysis data, not a standalone application.
- Do not stage generated WCL data, local databases, credentials, caches, or unrelated working-tree changes.
