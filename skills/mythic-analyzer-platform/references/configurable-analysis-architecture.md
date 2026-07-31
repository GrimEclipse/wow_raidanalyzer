# 可配置战斗分析架构

## 目标

分析器只负责生成可复核的事实；团队预设负责定义职责；规则配置负责决定是否计数。三层数据不得互相覆盖：

1. **Evidence（取证）**：WCL 原始事件、时间戳、坐标样本、施法、伤害、能量、打断。
2. **Assignment（职责预设）**：玩家/小组负责什么、谁被豁免、团队减伤轮次由谁执行。
3. **Verdict（判定）**：阈值、是否计数、豁免条件、扣分方式。

同一条 Evidence 可以在不同预设下得到不同 Verdict，但原始证据始终一致。

## 当前已经落地的配置契约

`boss_catalog.json` 的 `configSchema` 是界面与后端共同使用的唯一字段定义。在线分析页按 Schema 生成控件，后端 `analyzer_core.config.resolve_analysis_options()` 做类型、范围和未知字段校验，解析后的配置传入 Boss 插件，并写入结果 `meta.analysisOptions`。

支持的字段类型：

- `boolean`
- `number`
- `select`
- `text`
- `playerList` / `textList`
- `interruptGroups`

子配置可通过 `visibleWhen` 声明父开关，例如：

```json
{
  "key": "voidGraspHealingThreshold",
  "visibleWhen": {
    "field": "voidGraspReviewEnabled",
    "equals": true
  }
}
```

界面会随父配置即时折叠/展开子配置；后端仍按完整 Schema 解析默认值，保证配置回放和旧请求兼容。`visibleWhen.field` 必须引用同一首领中已存在的其他字段，不能自引用。

奥蕾莉亚当前首批配置：

- 是否拉取空虚之握治疗证据
- 空虚之握是否计入终审
- 指定治疗名单
- 死亡前 8 秒治疗阈值
- 银锋箭高伤致死是否计入终审
- 银锋箭高伤致死阈值
- 重力坍缩仅取证 / 实验性归责
- 重力坍缩大规模减员人数与死亡分组间隔

重力坍缩默认只输出死亡组、玩家、相邻死亡间隔和整组持续时间，不进入终审。

## 站位判定

没有职责预设时，不应把“离大团远”直接等价为站错。通用顺序应为：

1. 识别机制时间窗和玩家位置样本。
2. 读取该轮的 Assignment：固定点、允许区域、职责组、自由位或豁免位。
3. 只对拥有明确职责的玩家做合规判断。
4. 如果没有 Assignment，只输出离群值、聚类和置信度，不定罪。

术士在 P1 中场多线属于 Assignment 的“允许区域/自由位”，而不是在质心算法末端硬编码玩家名。若大量玩家站错，质心只能作为异常提示，不能作为正确位置的真值。

WCL 坐标是事件附近的采样证据，不保证与 debuff 毫秒级同步。位置记录必须同时保存：

- 机制时间戳
- 坐标样本时间戳
- 两者时间差
- 取样来源事件
- 置信度

超过预设时间差的坐标只能展示，不能判责。

## 个人减伤与团队技能

`boss_plugins.combat_config` 集中维护个人保命和团队技能。这里不保存或推导“固定减伤比例”，只保存：

- spell ID
- 名称、职业
- 效果类型（减伤、免疫、吸收、抬高生命、治疗等）
- 合理生效/取证时间窗
- 冷却时间
- 充能数

个人死亡审计只应对已经确认的高压轴/AOE 死亡运行。每场战斗一次性读取这些技能的完整 Casts 时间线，再通过
`audit_personal_defensive_readiness()` 对每个死亡产生三态结果：

- `defensive_active`：死亡发生在最近一次使用的合理作用窗内，不计未开减伤。
- `all_on_cooldown`：没有技能正在生效，但该玩家已配置的技能都在冷却，不计未开减伤。
- `available_unused`：至少一个已配置技能当时可用，玩家没有使用，才允许进入判责。

可用技能列表必须来自该角色实装天赋/战斗预设，不能把职业理论上可选但本场没点出的天赋算作“手里有技能”。

团队技能通过 `audit_raid_defensive_assignment()` 对预设轮次检查。治疗型团队技能（例如还魂）允许在伤害后的小窗口内落地；减伤型技能应在伤害前覆盖。未给该轮配置 Assignment 时只展示团队技能时间线，不判“漏按”。

## WCL 请求策略

- 基础事件按战斗读取一次。
- 个人/团队技能用所有已配置 spell ID 组成一次 Casts 过滤查询，按分页拉完整场次。
- 仅对已经确认的高压死亡运行本地时间线判断，不为每个玩家或每次死亡追加请求。
- 关闭某项 Evidence 开关时，不执行对应额外请求。

## 12.1 初始取数输出

当前发现结果位于 `docs/zone54_spell_discovery.json`（机器可读）与
项目根目录的 `zone54_spell_discovery.md`（人工复核）。乌拉特克是尾王且未开放测试，
因此被单列为 `expectedUntested`，不计入 `missingEncounterIDs`。

每个 Boss 的发现文件应保留以下三类 spell ID，且每条都保存来源 report/fight 和首末时间戳，不能只留一个没有出处的数字：

- `damageAbilities`：敌方来源的 DamageTaken / DamageDone 技能。
- `bossAuras`：Boss/add 获得的 Buff/Debuff，用于强化、阶段和能量机制。
- `playerDebuffs`：施加到玩家的 Debuff apply/refresh/remove/stack。

战斗模式草稿应由证据推导：

- Cast 周期与阶段分段
- Boss 能量变化
- 玩家 Debuff 的目标数、持续时间和结算伤害
- 大规模伤害/死亡簇
- add 出现与死亡
- Interrupts 的敌方读条和打断结果

任何尚未由至少一个 report/fight 支持的机制描述都应标记为“假设”，不能写成已确认规则。
