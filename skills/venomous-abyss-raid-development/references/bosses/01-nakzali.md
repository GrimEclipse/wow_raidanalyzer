# Boss 1 · Nakzali

Structured source key: `nakzali`.

Use `../source-data/raid-guide-source.json` for the current raid-leader flow and confirmed spell list. Preserve user-confirmed names such as 精华撕裂、祈求、贾瓦埃的回响、附身弹幕、灵魂残缺 and 午夜舞步. The line-of-fire and interception behavior of 附身弹幕 is raid-critical and must not be omitted.

Frontend descriptor: `frontend/report/plugins/venomous_abyss/nakzali/plugin.js`.

## Initial adjudication model

- Build the Pull list from WCL fight metadata. Always show kill/wipe, remaining Boss percentage, duration, and locally derived phase; WCL `lastPhase` is not reliable for current PTR reports.
- Phase anchors are `1295124` (Ritual of Awakening) for intermission, `1290003` (Uncoiling) for P2, and `1284034` (Uncoiled Rage) for enrage.
- Compare progression wipes against the kill Pull. A kill does not suppress observed mechanic issues.
- Count an Amani leak as confirmed only when an extra `1297624` Ritual Burn pulse closes against an individual add instance after `1287533` Gravebound Advance. Keep unmatched extra pulses as suspected evidence.
- `1287434` Essence Rend remove events have timestamps but no coordinates. Use the nearest position-bearing damage/resource event within the configured window; never substitute a death position. The current product labels the result as `贴边` / `未贴边` from the configured distance-to-centre threshold, while window-exceeded samples remain reference-only.
- Player Resources events directly provide current/max health, absorb, x/y and facing. Keep these values in event snapshots and tooltips; do not derive healing-absorb totals.
- Retrieve Nek'zali position and facing from `DamageDone` events targeting actor gameID `259927` with target resources included. Never replace missing Boss coordinates with the arena centre.
- `1289855` is the Hungering Pyre damage/cast family. Pair `1306666` apply/remove on its target and use the `removedebuff` timestamp for the intermission soak/spread replay; the 10-yard ring is visual evidence until PTR range behaviour is confirmed.
- Derive the Possession Barrage baseline from `1284103` casts and `1292034` wave damage in the kill Pull. Enrage takes precedence over interception; early/high-damage waves are interception candidates, while normal waves killing already-low players are raid-health candidates.
- `1299722` applied by Invoke is the direct player-level signal for casts interrupted by `1299673`.
- Mythic Soulcoil Well applies persistent inward pressure through Grasping Depths `1293212/1293214`; Immortal Coil `1299988/1308227` is the well-entry consequence. Preserve this in both leader guidance and field analysis.
