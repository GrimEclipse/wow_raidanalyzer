# Boss 6 · 双子毒牙

Status: leader flow authored; Heroic and Mythic WCL evidence connected.

## Encounter model

- Concentrated two-target fight with periodic target swaps.
- Vexhul applies permanent Eternal Venom; Ithraz removes it through Ravenous Feast.
- Each arena position contains two normal subcycles. Surge then moves both bosses to the next position.
- After all three positions are used, the bosses return to the center and enrage. The representative Heroic kill ended during the third position, so the final enrage time is not presented as observed.

## Normal cycle

1. Caustic Deluge creates Caustic Globules. Assigned low-stack players soak them before the 10-second raid failure.
2. Stone Breaker creates three ordered tank soaks.
3. Venomous Emergence summons three Spawn of Vexhul; Corrosive Spit is a targeted line that adds Eternal Venom.
4. Coiling Ichor targets several players with shrinking circles and drops puddles on expiration.
5. Stir the Depths creates avoidable waves that add Eternal Venom on hit.
6. Ravenous Feast strikes three times and removes one Eternal Venom stack from each valid player hit. Feasted prevents immediate reuse of the same group.
7. Consumed stacks create Bloodcurdled Mass targets. Kill them before Bloody Expulsion ramps by 15% per cast.
8. After the second subcycle, Surge begins the rotating-beam relocation.

## Mythic confirmation

- Blood Torrent and Caustic Deluge occur together. Barbed Bulwarks cast Protected Gestation around the globules; interrupting the cast removes the protection.
- Rouse the Brood and Venomous Emergence complete in the same millisecond in all four observed Mythic rounds. This is one combined mechanic window, not a conditional event that only starts if the ordinary spawn remains alive.
- Broodlings repeatedly begin Visceral Burst. The representative Mythic pull contains 56 begin-casts and matching real interrupt events, with no successful cast. Interrupting is the intended removal/retreat method.
- Mythic Ravenous Feast also creates Tainted Blood healing-absorb founts. Keep this separate from Bloodcurdled Mass: one is healed, the other is killed.
- A player death while affected by Eternal Venom creates additional Caustic Globules.

## Evidence anchors

- Heroic: `fgGFk1zvxV8QAwmW`, fight 37, 466.210 seconds, kill.
- Mythic: `8yDbgRFz9NnQktTx`, fight 35, 305.751 seconds, wipe.
- Heroic relocation starts: 154.466s and 324.000s (`1294293` / `1306872`).
- Mythic Rouse the Brood: 36.015s, 97.012s, 191.025s, 252.028s (`1308356`).
- Eternal Venom player aura: `1290336`; maximum visible stack in both samples is 9. Treat the next application as reaching 10 and killing the player.

## Adjudication boundaries

- Live Mythic analyzer details and calibration sources: `docs/twinfangs-mythic-analysis.md` at repository root. Each Feast has three strikes: raid first, assigned immune group for both remaining strikes. Early immunity removal and missing protection coverage are failures, deduplicated per player per round.
- Brood interrupt output identifies side, melee/ranged group and chronological spawn order. Far spawns after the third go to backup, never wrap to ranged player one. Near heads belong to the current tank with melee backup; do not infer private handoff communications or individual blame from missing interrupts.
- Return only the earliest completed Visceral Burst in each fight; later leaks are wipe aftermath and excluded from both the detail view and nightly count. Preserve the first head's chronological group order and never substitute a later head when first-leak coordinates are missing.
- Nightly first-leak statistics use the configured duty player when uniquely resolved, otherwise the side/group/order duty slot. Feast detail text must include the affected player, round and strike indices. Venom deaths remain single-fight evidence only. Stop Stone Breaker statistics at the first tank death in each fight and never attribute tank duty to a non-tank target.
- Three kill reports plus `vgdPJBnLNmzt13Qk` calibrate 30 fixed head positions across three arena wedges. Require NPC-owned coordinates; an interrupter's position is not a head position.

- WCL can identify every Eternal Venom stack source, Feast stack removal, globule timeout, Corrosive Spit hit, Stir the Depths hit, and Visceral Burst interrupt.
- WCL does not provide a trustworthy complete beam angle or puddle geometry. Use actual hit events for automatic blame; use nearby position samples only as supporting replay evidence.
- Do not infer a missed Protected Gestation interrupt merely because a globule lived longer. Require an unfinished cast or missing interrupt-table match.
