# WCL Zone 54 Mythic 初始取数

所有条目均保留 report/fight 来源；以下是日志事实，不等同于最终机制判定。

## Nek'zali the Soulcoiler (`nakzali`)

- 代表战斗：`HPrGLV84XRJjCykN` / Fight 9，时长 290986ms，kill=True
- 敌方 Cast：15 个 spell ID
- 敌方伤害：18 个 spell ID
- 玩家 Debuff：14 个 spell ID
- Boss/add Aura：9 个 spell ID
- 模式草稿置信度：medium
- 模式草稿：Boss 本体与多类灵魂/add 共同构成循环；Invoke/苏醒仪式召出或强化对象，灵魂转移与点燃构成处理链。

高频敌方 Cast：

- `1297624` Ritual Burn：260 次，中位间隔 989ms
- `1287533` Gravebound Advance：54 次，中位间隔 253ms
- `1300238` Soulcoiler's Curse：11 次，中位间隔 13135ms
- `1284103` Possession Barrage：8 次，中位间隔 6017ms
- `1293664` Soulcoil Ignition：4 次，中位间隔 2994ms
- `1292248` Soul Transfer：4 次，中位间隔 14971ms
- `1289855` Hungering Pyre：4 次，中位间隔 7523ms
- `1299673` Invoke：4 次，中位间隔 5024ms
- `1285681` Soulcoil Ignition：2 次，中位间隔 72643ms
- `1295124` Ritual of Awakening：2 次，中位间隔 1498ms
- `1293211` Soul Transfer：2 次，中位间隔 7992ms
- `1289902` Soul Transfer：2 次，中位间隔 1ms

主要伤害技能：

- `1307939` Corpse Blight：3454 次，总量 84954536，单次最高 33336
- `1293214` Grasping Depths：2163 次，总量 43568850，单次最高 66672
- `1292315` Uncoiling：1537 次，总量 13897972，单次最高 15433
- `1288772` Soulcoil Rite：1193 次，总量 66273302，单次最高 131590
- `1294729` Corpse Blight：736 次，总量 57274440，单次最高 94484
- `1308227` Immortal Coil：491 次，总量 22045829，单次最高 61605
- `1300239` Swirling Spirit：359 次，总量 16536168，单次最高 258939
- `1292034` Possession Barrage：291 次，总量 24475436，单次最高 353041
- `1` Melee：153 次，总量 11628189，单次最高 1354031
- `1284109` Hollowing Strikes：88 次，总量 4103492，单次最高 130910
- `1289875` Cremation：78 次，总量 2066958，单次最高 119010
- `1287434` Essence Rend：59 次，总量 5532703，单次最高 277690
- `1294933` Slithering Flame：45 次，总量 1797646，单次最高 120510
- `1288554` Latent Cultist：36 次，总量 5121616，单次最高 317360
- `1289855` Hungering Pyre：22 次，总量 2340164，单次最高 151528

玩家 Debuff：

- `1307939` Corpse Blight：775 事件，涉及 20 个目标
- `1293214` Grasping Depths：586 事件，涉及 20 个目标
- `1288772` Soulcoil Rite：443 事件，涉及 20 个目标
- `1297624` Ritual Burn：442 事件，涉及 20 个目标
- `1300239` Swirling Spirit：146 事件，涉及 13 个目标
- `1284109` Hollowing Strikes：137 事件，涉及 2 个目标
- `1288554` Latent Cultist：66 事件，涉及 15 个目标
- `1300235` Soul Exhaustion：46 事件，涉及 13 个目标
- `1287434` Essence Rend：32 事件，涉及 10 个目标
- `1289875` Cremation：22 事件，涉及 8 个目标
- `1299722` Invoke：14 事件，涉及 7 个目标
- `1294933` Slithering Flame：10 事件，涉及 5 个目标
- `1284103` Possession Barrage：8 事件，涉及 2 个目标
- `1306666` Hungering Pyre：2 事件，涉及 1 个目标

## Entombed Sentinels (`sentinels`)

- 代表战斗：`xdTc1fhtKWPrbCVv` / Fight 29，时长 421296ms，kill=True
- 敌方 Cast：10 个 spell ID
- 敌方伤害：19 个 spell ID
- 玩家 Debuff：9 个 spell ID
- Boss/add Aura：9 个 spell ID
- 模式草稿置信度：high
- 模式草稿：Blood of Ula'tek 与 Breath of Ula'tek 双目标战；酸/血两类印记长期覆盖团队，约 103 秒一次 Vitriolic Stasis，Contaminate 约 52 秒循环。

高频敌方 Cast：

- `1284458` Empowering Slam：32 次，中位间隔 1532ms
- `1284487` Bloodvenom Injection：30 次，中位间隔 1512ms
- `1284434` Toxic Droplets：24 次，中位间隔 2023ms
- `1284251` Venom Coagulation：16 次，中位间隔 1516ms
- `1296878` Shifting Protovenom：16 次，中位间隔 4011ms
- `1288232` Unstable Miasma：15 次，中位间隔 20673ms
- `1284257` Contaminate：8 次，中位间隔 52280ms
- `1284483` Blighted Blood：8 次，中位间隔 2012ms
- `1284606` Vitriolic Stasis：4 次，中位间隔 103007ms
- `1284588` Vitriolic Stasis：4 次，中位间隔 102997ms

主要伤害技能：

- `1284506` Mark of Blood：2434 次，总量 102059050，单次最高 141678
- `1284500` Mark of Acid：2415 次，总量 108735809，单次最高 150745
- `1284258` Contaminate：1479 次，总量 93624148，单次最高 100009
- `1310126` Bloodvenom Injection：350 次，总量 19908202，单次最高 166681
- `1284813` Helical Toxins：331 次，总量 11572338，单次最高 75007
- `1303097` Clinging Murk：325 次，总量 3702400，单次最高 31735
- `1` Melee：312 次，总量 72072320，单次最高 1253746
- `1284210` Blood Venom：223 次，总量 20613776，单次最高 166681
- `1284451` Toxic Droplets：220 次，总量 39610776，单次最高 284691
- `1296882` Shifting Protovenom：130 次，总量 9833008，单次最高 100009
- `1284471` Blighted Blood：72 次，总量 5262575，单次最高 103142
- `1288282` Unstable Miasma：54 次，总量 13891809，单次最高 566715
- `1284209` Living Venom：46 次，总量 10269840，单次最高 357031
- `1296962` Protovenom Eruption：30 次，总量 9206848，单次最高 366696
- `1284452` Noxious Blast：20 次，总量 6211692，单次最高 386963

玩家 Debuff：

- `1284500` Mark of Acid：1061 事件，涉及 20 个目标
- `1284506` Mark of Blood：941 事件，涉及 20 个目标
- `1284210` Blood Venom：256 事件，涉及 20 个目标
- `1284590` Helical Toxins：144 事件，涉及 20 个目标
- `1288297` Clinging Murk：117 事件，涉及 20 个目标
- `1284491` Bloodvenom Injection：26 事件，涉及 2 个目标
- `1284471` Blighted Blood：16 事件，涉及 8 个目标
- `1288260` Unstable Miasma：14 事件，涉及 6 个目标
- `1297338` Deadly Venom：12 事件，涉及 5 个目标

## Vashnik the Malignant (`vashnik`)

- 代表战斗：`HPrGLV84XRJjCykN` / Fight 33，时长 497012ms，kill=False
- 敌方 Cast：9 个 spell ID
- 敌方伤害：23 个 spell ID
- 玩家 Debuff：10 个 spell ID
- Boss/add Aura：9 个 spell ID
- 模式草稿置信度：high
- 模式草稿：Blood/Flame/Shadow 三种 Infusion 状态循环；Boss 通过 Imbibe 切换/吸收状态，Malignant Tumor 周期生成并以 Tumor Burst 结算。

高频敌方 Cast：

- `1304437` Hardened Tumor：102 次，中位间隔 67ms
- `1304459` Tumor Burst：99 次，中位间隔 408ms
- `1280935` Dripping Fangs：36 次，中位间隔 2034ms
- `1282516` Malignant Catalyst：24 次，中位间隔 5033ms
- `1284663` Imbibe：19 次，中位间隔 5107ms
- `1282509` Malignant Catalyst：12 次，中位间隔 39004ms
- `1285979` Caustic Surge：11 次，中位间隔 11537ms
- `1280189` Malignant Burst：8 次，中位间隔 696ms
- `1291530` Sanguineous Fortitude：7 次，中位间隔 50810ms

主要伤害技能：

- `1284561` Toxic Vapor：4609 次，总量 207693624，单次最高 158679
- `1305901` Burning Presence：2216 次，总量 64827959，单次最高 41670
- `1281925` Plague Froth：1316 次，总量 44944959，单次最高 47604
- `1285979` Caustic Surge：794 次，总量 43047975，单次最高 100009
- `1295229` Siphon Blood：557 次，总量 37384783，单次最高 125011
- `1291467` Virulent Fumes：360 次，总量 30674189，单次最高 119010
- `1280934` Dripping Fangs：271 次，总量 27388106，单次最高 349096
- `1295209` Explode：253 次，总量 5856968，单次最高 198350
- `1282525` Malignant Catalyst：213 次，总量 43094967，单次最高 277691
- `1295224` Siphoning Infection：201 次，总量 4997576，单次最高 33719
- `1295173` Exploding Infection：139 次，总量 7057636，单次最高 67438
- `1294994` Stygian Infection：135 次，总量 3239499，单次最高 33719
- `1298582` Hemo Expulsion：117 次，总量 20819833，单次最高 500429
- `1298587` Conflagrating Expulsion：116 次，总量 15987704，单次最高 379850
- `1` Melee：112 次，总量 26811458，单次最高 903519

玩家 Debuff：

- `1291461` Virulent Fumes：540 事件，涉及 20 个目标
- `1285979` Caustic Surge：436 事件，涉及 20 个目标
- `1281913` Plague Froth：144 事件，涉及 17 个目标
- `1282078` Plague Froth：144 事件，涉及 17 个目标
- `1281910` Plague Froth：144 事件，涉及 17 个目标
- `1280934` Dripping Fangs：35 事件，涉及 2 个目标
- `1294994` Stygian Infection：32 事件，涉及 12 个目标
- `1295173` Exploding Infection：28 事件，涉及 10 个目标
- `1295224` Siphoning Infection：28 事件，涉及 11 个目标
- `1280189` Malignant Burst：9 事件，涉及 2 个目标

## The Lost Explorers (`lostexplorers`)

- 代表战斗：`HPrGLV84XRJjCykN` / Fight 26，时长 451182ms，kill=False
- 敌方 Cast：28 个 spell ID
- 敌方伤害：23 个 spell ID
- 玩家 Debuff：11 个 spell ID
- Boss/add Aura：12 个 spell ID
- 模式草稿置信度：medium
- 模式草稿：多首领/多物件战；Nama、Iku、Mor'zahi 与场地物件分别提供近战、卷轴、命令和环境技能，United Defense 暗示共享防御或联动阶段。

高频敌方 Cast：

- `1292758` Evil Eyes：210 次，中位间隔 1ms
- `1291934` Throw Junk：121 次，中位间隔 3983ms
- `1291933` Throw Junk：56 次，中位间隔 3005ms
- `1310616` Shredding Shards：49 次，中位间隔 505ms
- `1296062` Shell Spin：32 次，中位间隔 4038ms
- `1286922` Icebound Flames：21 次，中位间隔 22997ms
- `1296021` Blink Nova：17 次，中位间隔 14511ms
- `1306145` Throw Junk：8 次，中位间隔 3052ms
- `1292796` Creepy Flames：7 次，中位间隔 1ms
- `1295854` Shredding Shards：7 次，中位间隔 62354ms
- `1296135` Mighty Thud：6 次，中位间隔 2013ms
- `1296095` Mighty Thud：6 次，中位间隔 2013ms

主要伤害技能：

- `1295450` Malevolent Presence：4195 次，总量 242026246，单次最高 225020
- `1308853` Splinters：1526 次，总量 57096725，单次最高 147876
- `1311587` Relic Rupture：879 次，总量 107738085，单次最高 166681
- `1` Melee：275 次，总量 43293670，单次最高 1381241
- `1294334` Blink Nova：153 次，总量 50170567，单次最高 601159
- `1292780` Final Ascension：96 次，总量 25055767，单次最高 1083427
- `1310616` Shredding Shards：49 次，总量 10182533，单次最高 535659
- `1300237` Mighty Thud：39 次，总量 19075305，单次最高 902856
- `1295928` Burning Flames：33 次，总量 1903692，单次最高 83341
- `1295954` Piercing Frost：27 次，总量 1273350，单次最高 58338
- `1310027` Relic Rupture：19 次，总量 5065716，单次最高 345916
- `1297648` Frost Patch：18 次，总量 588985，单次最高 41675
- `1297649` Fire Patch：15 次，总量 366347，单次最高 41675
- `1295985` Frostfire Volley：10 次，总量 646595，单次最高 83345
- `1295893` Frostfire Volley：10 次，总量 485397，单次最高 83341

玩家 Debuff：

- `1291929` Steady Strikes：329 事件，涉及 2 个目标
- `1308853` Splinters：222 事件，涉及 18 个目标
- `1295858` Shredding Shards：91 事件，涉及 2 个目标
- `1310500` Aftershock：88 事件，涉及 19 个目标
- `1299854` Bounce：62 事件，涉及 17 个目标
- `1291918` Shell Spin：51 事件，涉及 13 个目标
- `1297648` Frost Patch：42 事件，涉及 15 个目标
- `1297649` Fire Patch：34 事件，涉及 14 个目标
- `1295928` Burning Flames：30 事件，涉及 9 个目标
- `1295954` Piercing Frost：30 事件，涉及 6 个目标
- `1297625` Explosive Surprise：4 事件，涉及 2 个目标

## Sszorak (`sszorak`)

- 代表战斗：`8yDbgRFz9NnQktTx` / Fight 9，时长 169290ms，kill=False
- 敌方 Cast：12 个 spell ID
- 敌方伤害：18 个 spell ID
- 玩家 Debuff：16 个 spell ID
- Boss/add Aura：3 个 spell ID
- 模式草稿置信度：medium
- 模式草稿：以 Mutilate/Ravage 坦克连段为基础，穿插 Tempest 与多版本 Raging Crosswinds；后段出现 Venomous Surge 和 Unbound Ferocity 强化信号。

高频敌方 Cast：

- `1277027` Mutilate：12 次，中位间隔 3008ms
- `1277002` Ravage：12 次，中位间隔 3015ms
- `1277031` Mutilate：6 次，中位间隔 12506ms
- `1287072` Tempest：6 次，中位间隔 3508ms
- `1277101` Ravage：6 次，中位间隔 12479ms
- `1285453` Raging Crosswinds：6 次，中位间隔 199ms
- `1285425` Raging Crosswinds：6 次，中位间隔 199ms
- `1297111` Raging Crosswinds：4 次，中位间隔 206ms
- `1297096` Raging Crosswinds：4 次，中位间隔 206ms
- `1305959` Venomous Surge：3 次，中位间隔 63514ms
- `1285419` Raging Crosswinds：3 次，中位间隔 63518ms
- `1286033` Dig In：1 次，中位间隔 Nonems

主要伤害技能：

- `1285965` Ula'tek's Presence：1375 次，总量 95254728，单次最高 600054
- `1285998` Mutilated Gash：895 次，总量 82397154，单次最高 684347
- `1287205` Viscous Cyst：336 次，总量 31549674，单次最高 476040
- `1312189` Virulence：195 次，总量 16197173，单次最高 119010
- `1312219` Raging Crosswinds：158 次，总量 2084685，单次最高 20880
- `1306120` Venomous Surge：78 次，总量 11018731，单次最高 414073
- `1285999` Caustic Venom：45 次，总量 17841715，单次最高 723971
- `1312156` Venomous Surge：40 次，总量 2503570，单次最高 95208
- `1` Melee：38 次，总量 10009617，单次最高 1747442
- `1285616` Raging Crosswinds：21 次，总量 5688636，单次最高 405866
- `1287083` Tempest：19 次，总量 4178083，单次最高 829660
- `1297338` Deadly Venom：7 次，总量 531239，单次最高 87400
- `1277101` Ravage：6 次，总量 7460438，单次最高 3332289
- `1296667` Caustic Residue：5 次，总量 244075，单次最高 244075
- `1300089` Virulence：3 次，总量 1627496，单次最高 653985

玩家 Debuff：

- `1287205` Viscous Cyst：112 事件，涉及 14 个目标
- `1277051` Mutilated Gash：90 事件，涉及 19 个目标
- `1297707` Virulence：42 事件，涉及 15 个目标
- `1285447` Turbulent Gusts：40 事件，涉及 18 个目标
- `1282873` Corroding Venom：36 事件，涉及 2 个目标
- `1299899` Virulence：36 事件，涉及 14 个目标
- `1287083` Tempest：14 事件，涉及 7 个目标
- `1277105` Ravage：12 事件，涉及 2 个目标
- `1285453` Raging Crosswinds：12 事件，涉及 5 个目标
- `1285425` Raging Crosswinds：12 事件，涉及 6 个目标
- `1305963` Venomous Surge：11 事件，涉及 6 个目标
- `1296667` Caustic Residue：10 事件，涉及 3 个目标
- `1297338` Deadly Venom：10 事件，涉及 1 个目标
- `1297111` Raging Crosswinds：8 事件，涉及 4 个目标
- `1297096` Raging Crosswinds：8 事件，涉及 4 个目标

## The Twin Fangs (`twinfangs`)

- 代表战斗：`8yDbgRFz9NnQktTx` / Fight 35，时长 305751ms，kill=False
- 敌方 Cast：20 个 spell ID
- 敌方伤害：27 个 spell ID
- 玩家 Debuff：16 个 spell ID
- Boss/add Aura：5 个 spell ID
- 模式草稿置信度：high
- 模式草稿：Ithraz/Vexhul 双首领并带 Barbed Bulwark/幼体对象；Protected Gestation 是显著护盾/孵化阶段，Stir the Depths 与 Ravenous Feast 是阶段切换信号。

高频敌方 Cast：

- `1290336` Eternal Venom：232 次，中位间隔 200ms
- `1289994` Caustic Deluge：122 次，中位间隔 332ms
- `1289201` Caustic Globule：98 次，中位间隔 375ms
- `1303378` Protected Gestation：58 次，中位间隔 334ms
- `1308385` Visceral Burst：56 次，中位间隔 1001ms
- `1310360` Envenomed：44 次，中位间隔 502ms
- `1291478` Corrosive Spit：26 次，中位间隔 1005ms
- `1288538` Stone Breaker：24 次，中位间隔 1500ms
- `1289092` Fractured：13 次，中位间隔 3005ms
- `1289192` Caustic Deluge：8 次，中位间隔 1011ms
- `1303230` Blood Torrent：8 次，中位间隔 1012ms
- `1291404` Venomous Emergence：8 次，中位间隔 3008ms

主要伤害技能：

- `1290480` Eternal Venom：5185 次，总量 118194398，单次最高 82511
- `1294976` Toxic Fumes：2928 次，总量 184636148，单次最高 100009
- `1292806` Stir the Depths：320 次，总量 34376696，单次最高 158680
- `1290878` Coiling Ichor：280 次，总量 19107351，单次最高 133946
- `1` Melee：105 次，总量 23681794，单次最高 1843126
- `1289201` Caustic Globule：98 次，总量 11891610，单次最高 238020
- `1308482` Rouse the Brood：80 次，总量 10727856，单次最高 198350
- `1308122` Venomous Emergence：80 次，总量 5846209，单次最高 118970
- `1290662` Ravenous Feast：75 次，总量 20190112，单次最高 508769
- `1290338` Caustic Globule：51 次，总量 2714280，单次最高 106479
- `1289237` Caustic Deluge：44 次，总量 481768，单次最高 138041
- `1292348` Eternal Venom：36 次，总量 0，单次最高 0
- `1303235` Blood Torrent：20 次，总量 0，单次最高 0
- `1306876` Sanguine Storm：18 次，总量 6349778，单次最高 426958
- `1292552` Congealed Gore：17 次，总量 903649，单次最高 79340

玩家 Debuff：

- `1310102` Tainted Blood：636 事件，涉及 20 个目标
- `1290336` Eternal Venom：338 事件，涉及 20 个目标
- `1310096` Feasted：146 事件，涉及 20 个目标
- `1306925` Congealed Gore：120 事件，涉及 18 个目标
- `1310360` Envenomed：84 事件，涉及 2 个目标
- `1292552` Congealed Gore：58 事件，涉及 15 个目标
- `1292807` Stir the Depths：48 事件，涉及 15 个目标
- `1293979` Corrosive Spit：36 事件，涉及 11 个目标
- `1290814` Coiling Ichor：24 事件，涉及 11 个目标
- `1289092` Fractured：22 事件，涉及 3 个目标
- `1309471` Noxious Slick：22 事件，涉及 5 个目标
- `1297338` Deadly Venom：10 事件，涉及 3 个目标
- `1289192` Caustic Deluge：8 事件，涉及 2 个目标
- `1303230` Blood Torrent：8 事件，涉及 2 个目标
- `1303235` Blood Torrent：8 事件，涉及 2 个目标

## The Coiled Altar (`bargained`)

- 代表战斗：`HPrGLV84XRJjCykN` / Fight 54，时长 234189ms，kill=False
- 敌方 Cast：20 个 spell ID
- 敌方伤害：25 个 spell ID
- 玩家 Debuff：16 个 spell ID
- Boss/add Aura：10 个 spell ID
- 模式草稿置信度：medium
- 模式草稿：Zul'jan 与 Hex Lord Malacrass 主导的多对象/祭坛战；Fangs of the Crucible 叠层推进，Manifestation of Dread 与灵魂系 add 构成恐惧阶段。

高频敌方 Cast：

- `1283290` Noxious Ground：41 次，中位间隔 493ms
- `1299684` Sever：16 次，中位间隔 3034ms
- `1285847` Unassailable：14 次，中位间隔 480ms
- `1290316` Manifestation of Dread：14 次，中位间隔 487ms
- `1285911` Unnerving Fixation：11 次，中位间隔 799ms
- `1286399` Wail of Terror：11 次，中位间隔 1765ms
- `1307184` Dread Bolt：10 次，中位间隔 3647ms
- `1282287` Venomfang：8 次，中位间隔 2001ms
- `1283832` Axegrinder：4 次，中位间隔 2016ms
- `1283489` Guillotine：4 次，中位间隔 3513ms
- `1285643` Dreadmarch：4 次，中位间隔 2007ms
- `1308311` Retaliatory Malice：4 次，中位间隔 1ms

主要伤害技能：

- `1282408` Coalesced Venom：7347 次，总量 92837359，单次最高 17085
- `1299838` Venom Rupture：1008 次，总量 84247788，单次最高 198349
- `1282512` Fangs of the Crucible：388 次，总量 22644903，单次最高 81240
- `1288635` Dreadful Presence：322 次，总量 27214834，单次最高 127364
- `1285017` Axegrinder：260 次，总量 20168150，单次最高 106405
- `1282288` Volatile Venom：189 次，总量 11156047，单次最高 80639
- `1310691` Mutagenic Venom：79 次，总量 12068830，单次最高 241272
- `1283290` Noxious Ground：62 次，总量 6686388，单次最高 159101
- `1308323` Retaliatory Malice：45 次，总量 7629465，单次最高 253463
- `1` Melee：43 次，总量 8238017，单次最高 1152789
- `1300322` Twinfang Toxin：43 次，总量 6784595，单次最高 312453
- `1283631` Widow's Touch：37 次，总量 4708763，单次最高 175806
- `1306906` Venomfang：27 次，总量 2592708，单次最高 107622
- `1283594` Guillotine：20 次，总量 5589617，单次最高 440933
- `1307184` Dread Bolt：10 次，总量 1232138，单次最高 173659

玩家 Debuff：

- `1299838` Venom Rupture：1019 事件，涉及 20 个目标
- `1285017` Axegrinder：186 事件，涉及 19 个目标
- `1283290` Noxious Ground：74 事件，涉及 20 个目标
- `1282419` Volatile Venom：44 事件，涉及 11 个目标
- `1307425` Guillotined：40 事件，涉及 20 个目标
- `1285911` Unnerving Fixation：33 事件，涉及 14 个目标
- `1310498` Mutagenic Venom：26 事件，涉及 5 个目标
- `1286399` Wail of Terror：20 事件，涉及 9 个目标
- `1301690` Sever：16 事件，涉及 2 个目标
- `1306906` Venomfang：16 事件，涉及 8 个目标
- `1286837` Gravebound：15 事件，涉及 6 个目标
- `1297445` Dreadmarch：12 事件，涉及 7 个目标
- `1286901` Gloombomb：8 事件，涉及 4 个目标
- `1283485` Guillotine：4 事件，涉及 2 个目标
- `1310744` Malevolent Resonance：4 事件，涉及 2 个目标

## 预期不开放测试

- Ula'tek (`ulatek`)：团队副本尾王按惯例不开放公开测试，缺少 Mythic 日志属于预期状态。
