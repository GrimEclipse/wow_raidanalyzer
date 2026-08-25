# Boss 2 · Entombed Sentinels

Structured source key: `sentinels`.

The encounter is a long split-field two-target cycle. Preserve the red/green mechanics, delayed red-water placement after the soak mark expires, tank swap during 腐毒停滞, threat rebuilding through 99% reduction, and the “合星座” handling of 螺旋剧毒. Mythic 变换病原体 must remain visually distinguished.

Frontend descriptor: `frontend/report/plugins/venomous_abyss/sentinels/plugin.js`.

Analyzer implementation: `boss_plugins/venomous_abyss/sentinels.py`.

The analyzer treats player Mark of Acid/Blood as `1284500` / `1284506`; the
similarly named `1284494` / `1284503` rows are Boss self-buffs. Helical Toxins
uses `1284590`: paired `removedebuff` rows identify a safe collision, paired
`applydebuffstack` rows identify a wrong collision and expose the resulting
number. Initial private-aura values remain absent, so only uniquely constrained
inputs such as `1+1 -> 2` and `3+3 -> 6` may be inferred.

Verified against report `GJx48AgjRMt3KrpZ`, Fight 21 on 2026-08-25: all
98 initial `applydebuff` rows omit `stack`; all 94 `removedebuff` rows also omit
it. Only the six wrong-collision `applydebuffstack` rows contain `stack`
(`2`, `3`, or `6`). A client addon displaying private-aura numbers is not proof
that those numbers were serialized into the WCL combat-log payload. Consume an
initial `stack` if WCL adds it in the future, but never synthesize it today.

When more than two Helical removals land in the same WCL frame, arbitrary
two-player grouping is sufficient because the event is already a safe clear and
does not assign responsibility. If only one removal is logged, a still-active
partner may be filled only when the collision-time position is within the
configured 8-yard reliability bound. Every safe pair must keep `time`, `timeMs`,
`playerIDs`, and pairing evidence.

Current analysis contract:

- A clean Helical round is collapsed by default and exposes only the two-player
  pairs. Any round containing a wrong collision or timeout opens by default.
- A full-report JSON opens on the shared `frontend/report/overview.html` Pull
  board used by every Boss. Selecting a Pull enters this Boss's dedicated skill
  analysis with `fightID`; the dedicated page must not duplicate the overview.
  Its header always retains Home and shared-overview navigation.
- Each Helical round is one full-width panel stacked below the previous round.
  Event cells inside an expanded panel use a wrapping responsive grid and must
  never require a horizontal scrollbar. A timeout removal and Cultivated Burst
  damage for the same player in the same event window are rendered together in
  one compact cell.
- The first wrong collision in each round is highlighted. If either participant
  moved more than 8 yards during the preceding second, report that movement as
  evidence but do not assign responsibility without further review.
- Mark overview contains only maximum Acid stack, maximum Blood stack, overlap
  episode count, and maximum combined stack. Keep the per-player cycle query;
  do not emit every stack tick or special-case Balance/Destruction players.
- Do not draw a field replay for the soak/drop mechanic. Report only players
  whose current Blood stack exceeds Acid but who did not receive Clinging Murk,
  plus Clinging Murk carriers whose removal position is over the configured
  relative-distance threshold.
- Toxic Droplets reports repeat soakers and alive players with no droplet hit in
  the round. Friendly immunity casts are evidence annotations, not proof that a
  player fulfilled a soak assignment.
