# Boss 4 — 迷失的探险者 / The Lost Explorers

Status: raid-leader flow authored; WCL evidence mapped; analysis plugin remains intentionally inactive.

## Encounter model

- Council encounter with three active bosses: 大副纳玛、书卷贤者伊库、商人盖博. 莫尔扎希 is the encounter timer/enrage actor.
- Nama and Iku are tanked targets; Gebbo ignores tank threat and patrols the inner ring.
- The normal loop is two stacked targets plus one moving target. Multi-dotting is valuable, but bringing both other bosses into Nama's 团结光环 causes 99% damage reduction.
- Each `强化` window must be interrupted through the fish interaction. The three successful deliveries each trigger one boss's special sequence through `束缚苦痛`; the same boss cannot receive the fish twice.
- Kill the encounter before the fourth `强化`. In the observed Mythic wipe, the fourth window proceeds into Final Ascension and raid-wide lethal damage.

## Boss responsibilities

### 大副纳玛

- `旋壳`: targets a random melee and throws three shells forward. Plan melee positions so the line does not cross the group.
- `巨力猛击`: three soak circles. Two players are sufficient per circle, but the 30-second vulnerability prevents the same players from soaking again while marked.

### 书卷贤者伊库

- `冰封烈焰`: interrupt assignment required. A successful cast deals direct Frostfire damage and leaves a dispellable 12-second DoT.
- `闪现新星`: teleports to a marked player and deals distance-falloff raid damage. The marked player must move away from the group.
- `霜火连射`: three consecutive applications to ten players per cast, split between frost and fire. Enter an opposite-color patch to remove the DoT and clear the patch; each clear triggers `元素爆炸`, so removals must be staggered.

### 商人盖博

- `投掷垃圾`: avoid the impact. The remaining box can be opened by stepping on it, applying a stacking bleed.
- During the fish window, an extra junk throw produces the fish used to interrupt `强化`.
- `投掷蘑菇`: places mushrooms under ranged players. Touching one begins its detonation and launches a player; use the launch to pass the expanding `爆炸惊喜` wave. Teleports and Demon Hunter double jump can also cross the wave.

## Evidence boundaries

- WCL distinguishes the fish-producing throw from ordinary junk: `1306145` is its cast and `1306137` is the same throw's completion/result. The observed Heroic kill completes it at 00:31.029 / 02:35.808 / 04:40.622; the Mythic sample completes it at 00:30.989 / 02:37.383 / 04:42.121 / 06:47.322.
- WCL exposes the successful delivery through `莫尔扎希的命令` / `束缚苦痛` anchors, but does not expose a stable event identifying the player who picked up or threw the fish. Analysis may prove fish generation, success, target, and timing only.
- Mythic crate breaking adds a 15-yard Relic Rupture burst. WCL records the result through `1310028` and damage instances `1310027` / `1311587`; without crate coordinates it should not infer who stood too close.
- Frostfire Volley is known to cast three times. The timeline records the observed first/last cast window and must not invent an exact timestamp for the middle cast.
- Confirmed Chinese names come from the user's PTR observations. Unconfirmed damage-only spell names remain English until a reliable localized source exists.

## Source paths

- Authoritative encounter copy and spell overrides: `../source-data/raid-guide-source.json`
- Representative Heroic/Mythic timelines: `../source-data/boss-timelines.json`
- Full WCL spell inventory: project-root `zone54_spell_discovery.md`
