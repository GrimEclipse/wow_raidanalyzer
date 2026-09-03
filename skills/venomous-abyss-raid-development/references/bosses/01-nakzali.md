# Boss 1 · Nakzali

Structured source key: `nakzali`.

Use `../source-data/raid-guide-source.json` for the current raid-leader flow and confirmed spell list. Preserve user-confirmed names such as 精华撕裂、祈求、贾瓦埃的回响、附身弹幕、灵魂残缺 and 午夜舞步. The line-of-fire and interception behavior of 附身弹幕 is raid-critical and must not be omitted.

Frontend descriptor: `frontend/report/plugins/venomous_abyss/nakzali/plugin.js`.

## Initial adjudication model

- Build the Pull list from WCL fight metadata. Always show kill/wipe, remaining Boss percentage, duration, and locally derived phase; WCL `lastPhase` is not reliable for current PTR reports.
- Phase anchors are `1295124` (Ritual of Awakening) for intermission, `1290003` (Uncoiling) for P2, and `1284034` (Uncoiled Rage) for enrage.
- Compare progression wipes against the kill Pull. A kill does not suppress observed mechanic issues.
- Count an Amani leak as confirmed only when an extra `1297624` Ritual Burn pulse closes against an individual add instance after `1287533` Gravebound Advance. Keep unmatched extra pulses as suspected evidence.
- Corpse Blight is a raid-wide, stacking 30-second damage-over-time effect when a Restless Amani dies. Do not model it as a local 15-yard death explosion; simultaneous add deaths are a raid-healing failure window.
- `1287434` Essence Rend is a plain dispellable debuff, not a healing absorb. Remove events have timestamps but no coordinates. Use the nearest position-bearing damage/resource event within the configured window; never substitute a death position. The current product labels the result from the configured distance-to-centre threshold, while window-exceeded samples remain reference-only.
- Player Resources events directly provide current/max health, absorb, x/y and facing. Keep these values in event snapshots and tooltips; do not derive healing-absorb totals.
- Retrieve Nek'zali position and facing from `DamageDone` events targeting actor gameID `259927` with target resources included. Never replace missing Boss coordinates with the arena centre.
- `1289855` is the Hungering Pyre damage/cast family. Preserve the existing soak-player damage evidence. Slithering Flame `1294933` identifies the corpse-burning assignment, mark time, and approximately eight-second corpse-interaction window. The following approximately twenty-second `1289875` aura is only the Immolation DOT and is not a corpse-interaction window.
- Restless Amani has no reliable NPC Death row. Reconstruct each corpse from `DamageDone` targeting gameID `261509` where target resources reach `hitPoints=0`; identity is `(targetID, targetInstance)` and every later zero-health lifecycle creates a new corpse. `1297631` Vessel of Awakening is the direct Awakened Host failure signal. Return the nearest active corpse coordinate and distance at the Slithering Flame mark, then inspect every reliable movement segment across that `1294933` aura window. A path within 5 yards consumes a corpse; only mark a player as making no attempt when Awakened Host really occurred and reliable movement stayed outside 10 yards of every relevant corpse.
- Derive the Possession Barrage baseline from `1284103` casts and `1292034` wave damage in the kill Pull. Enrage takes precedence over interception; early/high-damage waves are interception candidates, while normal waves killing already-low players are raid-health candidates.
- `1299722` applied by Invoke is the direct player-level signal for casts interrupted by `1299673`.
- WCL CombatantInfo and composition payloads do not expose game raid subgroup numbers. Never infer group 1/2/3/4 from position. Accept configured inner-team rosters, while always showing the actual entrants from Immortal Coil `1299988`.
- In Mythic, group well windows from enemy Immortal Coil `1300514`; split multiple entry attempts in one well when the first team fails and a recovery team enters. Soul Exhaustion `1300235` proves the post-exit lockout. Soulcoiler's Curse `1300238` uses interrupt events versus successful casts, `1290361` confirms players actually mind-controlled, and damaging `1300239` rows count avoidable Swirling Spirit hits. Immortal Coil `1308227` is regular inner-realm AOE and must not be counted as avoidable damage.
- Nightly responsibility rows stop after the ninth distinct player death: events with at most eight prior distinct deaths remain countable, later collapse events do not.
