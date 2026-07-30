# Analysis capabilities and 12.1 boss integration

The report shell loads modules from `meta.capabilities`; it must not branch on a
boss key. Bosses declare the same capability map in `boss_catalog.json`.

Supported capabilities:

- `wipe`: whole-pull wipe cards (`generic-wipe`)
- `avoidable`: generic avoidable-damage board (`generic-avoidable`) or the
  mistake workflow (`mistake-tracker`)
- `interrupts`: interrupt rotation and missed-interrupt evidence
- `dispels`: dispel evidence
- `mistakes`: counted/uncounted mistake facts and appeal input
- `verdict`: IQ-loss calculation and Excel export
- `replay`: phase/event field replay

Legacy JSON is inferred by `analyzer_core.contracts` on the backend and
`assets/vendor/analysis-capabilities.js` in the browser. Crown of the Cosmos,
Midnight Falls, and Lightblinded Vanguard are frozen regression baselines.

## Player field snapshot

Every future boss that enables `replay` should emit player snapshots with:

- `id`, `name`, spec, class color
- position, facing, sample time offset and confidence
- `vitals.hitPoints`, `vitals.maxHitPoints`, `vitals.healthPercent`
- `vitals.absorb`, `vitals.healAbsorb`

Missing values are `null`, never zero. A damage event's `absorbed` value is the
amount absorbed for that hit and must not be presented as the player's current
shield. With `includeResources`, WCL emits `hitPoints`, `maxHitPoints`, and the
player's current positive `absorb` value. WCL resource samples do not expose the
sum of current healing-absorb effects. Healing absorption is therefore optional:
only a rule pack that already requests configured absorb-valued debuffs and
healing events may derive it. The UI labels that value as derived and otherwise
shows that evidence collection is not configured.
