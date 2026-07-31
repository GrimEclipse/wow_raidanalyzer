# Boss 5 — 斯索拉克 / Sszorak

Status: raid-leader flow authored; Heroic timeline and Mythic Serpent's Fury evidence mapped; analyzer remains inactive.

## Encounter model

- A regular single-target loop with three repeating responsibilities: Apex Predator combo, two Venomous Surge casts that create four cysts, then a 25-second Howling Maelstrom.
- Six vents preview the next three wind directions. The environment warning and 1—2—3 orbs are raid-leader information; WCL does not expose a stable vent-number event.
- Trigger one cyst for each gale to gain the five-second sticky effect. Keep the fourth cyst for the tank after the raid returns.
- Dig In (`1286033`) is the stable transition anchor and exposes the boss to increased damage.

## Core mechanics

- Apex Predator contains exactly two Ravage, two Mutilate, and one Tempest casts in a random order. Tempest is never first.
- Mutilate is a shared hit and applies a duration-refreshing DoT. PTR testing indicates Anti-Magic Shell can prevent the DoT application.
- Tempest waves remain in motion after moving away from the boss; avoid their continuing rotation.
- Raging Crosswinds marks players with directional knockbacks, then applies Turbulent Gusts. Two affected airborne players can collide to land.
- Heroic uses two Raging Crosswinds directions. Mythic WCL contains additional direction-instance IDs, but client-facing arrows are still required to map the exact directions.

## Mythic difference

- Serpent's Fury marks one player while the boss gains rage.
- At least 14 players must enter eight yards of the marked player to trigger To the Slaughter and consume rage.
- The charge applies Virulence; spread again before removal to stop its burst from propagating.
- Reaching 100 rage grants Unbound Ferocity (`1296898`) and is a direct failure result.

## Evidence boundaries

- WCL can verify the Serpent's Fury target, Virulence chain, Dig In windows, cyst trigger order, explicit hits, and Unbound Ferocity.
- Without a reliable same-millisecond position sample, WCL cannot prove the exact number of players inside eight yards. Record “rage not cleared” rather than convicting a specific player.
- The boss vulnerability during Dig In is confirmed as 30%.

## Source paths

- Authoritative guide copy: `../source-data/raid-guide-source.json`
- Heroic/Mythic representative timelines: `../source-data/boss-timelines.json`
- Spell inventory: project-root `zone54_spell_discovery.md`
