# Boss 8 · Ula'tek

Nightly egg-duty participation and carried-egg wave contacts are restricted to P1 and P2.5. Count distinct carry-aura intervals by application time; refreshes are not additional assignments. Use the confirmed second Bound Fury ending through the sixth soak on Normal/Heroic or eighth soak on Mythic, followed by about five seconds of falling, as P2.5, bounded by the next platform transition when incomplete. Show carry and contact counts together, including zero-duty roster players. Keep P2/P3 out of this comparison.

Ula'tek is the final Boss. Live Normal, Heroic, and Mythic evidence exists in WCL
Zone 53 (encounter 3492).

Use report `T9G1VpZHkmNgCfxL`, Fight 41 for the first checked-in Normal timeline.
Use the 591.94-second Heroic kill `njJBp2Nmrdgk1AaH`, Fight 2 for the complete
P1/P2/P2.5/P3 timeline. Mythic kill `fvqyDzgPW8xZQmwR`, Fight 61 supplies a
Zone 53 M8 sample. Its times are one team's observed casts, not universal timers.
P3 Serpent's Bite appears three times here, versus four in the Heroic sample.
Mythic Blightscale Wretch (`263942`) casts Fester Burst (`1310763`) six times
across P1/P3. The outside-of-10-yards danger comes from the spell description;
the sampled kill alone cannot prove every outside death.

WCL can order an egg-carrier's `1295360` removal a few milliseconds before the
same-frame `1292403` wave hit. Attribute this only inside a 250 ms removal grace
window and require a nearby `1301268` raid-aura mutation as hatch evidence.

Grasping Fangs is one six-player assignment per fight even when the two
Wardens apply their three targets about 1.2 seconds apart. Report each removal
and the corresponding `1311609` transition. Judge against the user-configured
`fangSafeStacks` cap (default three), not assignment side; keep side evidence
in the single-fight report. Missing stack evidence is not a violation.

On Mythic, a carrier can collide with another carrier or ground egg and hatch
it. A same-frame egg-aura removal plus hatch mutation without a wave or coil is
only a review clue; require position replay to confirm collision.

During each `1286860` Bound Fury window, damage to both Ula'tek (`257758`) and
the Venomous Heart (`267460`) is effective. Return the separate target totals
and their sum; attribute pet and guardian damage to the owning player.

Critical analysis has seven independent, default-on suboptions. Disabled sections must skip their event streams and spatial calculations where no other selected section needs them.

Nightly mechanics stop permanently at the first timestamp with eight simultaneously dead players. Include actual resurrect events when counting deaths before this threshold. Keep full single-fight evidence and show the cutoff notice; aggregate only the pre-cutoff review for every nightly metric, including egg duty counts.

Replay uses RaidPlan orthographic world centers, yaw, and vertical yard spans for the main floor and both corridors. First Circling Prey does not break the initial floor. Later completed Circling Prey removes the Boss's old quarter; snapshot the Boss before the cast, never the escaped raid. Bound Fury channels for its observed aura lifetime (about 20 seconds). Mother’s Wrath uses its observed damage ticks, preserving all nine impacts, with a user-confirmed three-yard circle. Raidwide Wrath or Rattler Slam (1299206) damage triggers a screen impact; normal tank ticks do not. Serpent's Bite has a seven-yard circle, Volatile Purge a three-yard circle. Remove unverified Boss main-wave geometry.

Public Mythic validation: `r19Gk7PJfVvmnFgM`, Fight 3, Copium kill on 2026-10-08. Mythic Noxious Shell is 1307612 (Heroic 1295360), Hardened shell is 1299650; P1 carryable spawn is 265644. Corridors also contain 268121, 268164 and 263535; P3 moving Slithering Clutch is 271194. Preserve observed instance tracks, shell damage and actual aura removal, and reject coordinate-less duplicate WCL aliases. Link a pickup only to a uniquely nearby, coordinate-confirmed egg. Aura removal cannot invent a permanent ground NPC.

User confirms Mythic Volatile Purge fires three green directions like the Mercedes emblem. NSRT's early UlatekWaveLines texture has fixed north/SE/SW spokes separated by 120 degrees; minimap-compass rotation only changes their screen orientation. Latest user correction: the three-yard circle and six-second countdown start on the post-Bite first Purge application (1312967), and cross its transition to 1316356 without restarting. The sample removes Bite at 413404 ms, applies the first Purge at 413428 ms, changes aura at 418461 ms, and begins Purge damage at 419454 ms. Preserve both actual aura lifetimes separately. Render one three-spoke wave launch at the countdown end. Its three-yard width is user-confirmed; travel speed/range are a visual model, never hit adjudication. Source for triad orientation: Reloe/NorthernSkyRaidTools commit b2df480ea5b05eea11c45a3aa6a8e91dece2a413, EncounterAlerts/MidnightS2/Ulatek.lua and Media/Textures/UlatekWaveLines.png.

P2 displays left corridor above right corridor with slightly smaller maps and player portraits. End the split camera on a sustained raid return to the central floor, using observed player coordinates, rather than the second Bound Fury cast. The Heroic sample returns around 4:22 and the current Mythic sample around 4:40; do not hardcode either timestamp. Weakened/Ravenous Doomscale share portrait 145464, distinct from Doomscale Warden 143901; Blightscale Viper (261915) uses portrait 142993. Desperate Thrash (1305709), named 痛苦挣扎 by the user, previews a 30-degree, 30-yard cone during its cast and clears on completion or interrupt. Prefer matching-instance tank hits for aim, with the nearest recorded tank as a visual fallback.

Fester Burst (1310763) previews the instance-local ten-yard safe bubble while casting, with an overhead cast bar in every phase. The Mythic sample contains Wretch (263942) instance 3 in P3 and casts at 458786/492852 ms; do not invent another spawn. Toxic Incubation interception is proven by tank hits of 1299919, five ticks about one second apart per tether. The actual line connects the spectral caster to the living Blightscale Wretch (263942), not to the intercepting tank. Match actor instances and deaths using owned WCL coordinates. Each tick emits two opposite waves at the tank's observed position, perpendicular to the caster-to-Wretch axis; neither player facing nor movement determines direction. Missing or ambiguous Wretch coordinates omit the invented line and waves while retaining interception ticks. User does not want general player-facing indicators. Limit floor removal to polygons inside the broken platform quarters, retaining the side staircases.

P2 uses vertically stacked corridor crops, left above right, with the same outer replay dimensions as the central platform. Crop the unused upper map area without dropping the raid's movement route. Show an independent Doomscale Warden (264045) health and cast card in each corridor; health must belong to the matching actor instance and resource owner, never to a player attacking the Warden. Reserve the cast slot so cast starts do not change layout height.

Mythic P3 Blightscale Shriekers (273577) must appear on the main map as independent instance tracks, including their movement away from shattered quarters. Use local portrait 147462 (doomscale-wretch.png). The public sample spawns two at 507899/507900 ms; their 1310764 casts begin at 526507 ms and are interrupted separately. Include both Shriekers' actual casts (1313531 and 1310764 in this sample). For Malice, Anguished Cry and Shrieker casts, retain interrupt player, ability and matching target instance; stop the cast immediately, show a brief player portrait/ability icon, then clear the feedback. Keep interrupt icons local under assets/spells.

User confirms Spectral Coil (267679) corner identifies one of exactly eight fixed soak regions; once the first region is chosen the sequence is fixed. Decode the actual sequence from 1299010 source-instance coordinates; never move a circle to a player cluster or assume all 1287265 damage recipients are soakers. The sample has four P1 casts and eight after the second Fury, all with distinct source instances and coordinates. Circle region centers currently use a 32-yard ring snapped to eight 22.5-degree-offset spokes, estimated from the user's 2026-10-10 diagram; precise center calibration remains pending. Preserve the real source coordinate and regionGeometryEvidence separately. Ten-yard radius comes from [Spectral Coils](https://www.wowhead.com/spell=1287265/spectral-coils); [Vicious Echoes](https://www.wowhead.com/spell=1310764/vicious-echoes) verifies the Shrieker's interruptible cast.
