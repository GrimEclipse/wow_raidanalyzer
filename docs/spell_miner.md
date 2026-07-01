# DB2 法术挖掘工具草案

这个工具的目标不是替代 WCL 实战验证，而是提前把 PTR/live 客户端里的法术资料整理成 boss plugin 可以审阅的候选配置。

## 第一版边界

第一版先读取已经导出的 DB2 CSV/TSV 文件，不直接解析本地 CASC。这样做的好处是很稳：无论数据来自 wow.tools.local、Wago.tools 导出，还是之后我们写的本地 CASC helper，只要最终落成 CSV/TSV，就能复用同一个归纳逻辑。

## 需要准备的前置文件

如果正在运行 `wow.tools.local`，可以直接用项目里的脚本导出，不需要手动点网页按钮：

```powershell
.\tools\export_wtl_db2.ps1
```

默认会从 `http://localhost:5000` 导出 `12.0.7.68275` / `zhCN` / hotfix 后的若干表，写到：

```text
db2_exports/live_12_0_7_68275/
```

最少需要：

- `SpellName.csv`：法术 id 和名称。
- `SpellEffect.csv`：法术效果、光环、触发法术关系，尤其是 `EffectTriggerSpell`。
- `JournalEncounterSection.csv`：地下城手册 section 到 spell id 的入口。

强烈建议补充：

- `JournalEncounter.csv`：用于确认 encounter/boss 元信息。
- `Spell.csv`、`SpellMisc.csv`、`SpellDuration.csv`、`SpellRadius.csv`、`SpellRange.csv`
- `SpellTargetRestrictions.csv`、`SpellAuraOptions.csv`、`SpellAuraRestrictions.csv`
- `SpellDescriptionVariables.csv`、`SpellXDescriptionVariables.csv`、`SpellTooltip.csv`
- `SpellScript.csv`、`SpellLabel.csv`、`SpellXSpellVisual.csv`

当前 WTL / 12.0.7 的 DB2 里未必存在 `SpellDescription`、`SpellAuraDescription` 这种直观表名。描述文本主要来自地下城手册 `JournalEncounterSection`；法术 tooltip 的数值变量则拆在 `SpellDescriptionVariables` / `SpellXDescriptionVariables` 等表里。因此第一版挖掘重点不是“还原完整 tooltip 文案”，而是建立：

```text
Journal section spell id -> SpellName -> SpellEffect trigger graph -> aura / damage / child spell 候选
```

可选人工映射：

- 某些隐藏阶段、服务端脚本触发、同名但 DB2 没有显式边的技能，仍然需要人工种子文件补一条 `known_edges`。

## 命令示例

按关键词搜索并展开：

```powershell
python -m spell_miner --db2-dir .\db2_exports\ptr_12_0 --keyword 星辰裂片 --out .\generated\stellar_shard_candidates.json
```

按地下城手册 encounter 入口展开：

```powershell
python -m spell_miner --db2-dir .\db2_exports\ptr_12_0 --encounter-id 2740 --out .\generated\lura_journal_candidates.json
```

结合人工种子：

```powershell
python -m spell_miner --db2-dir .\db2_exports\ptr_12_0 --seed-file .\examples\spell_miner_lura_seeds.json --out .\generated\lura_candidates.json
```

## 种子文件格式

```json
{
  "keywords": ["星辰裂片", "天堂与地狱"],
  "seed_ids": [1282441],
  "encounter_ids": [2740],
  "known_edges": [
    {
      "from": 1282441,
      "to": 1285510,
      "type": "manual_apply_aura",
      "note": "WCL 实战确认：P4 星辰裂片点名 debuff"
    },
    {
      "from": 1285510,
      "to": 1281473,
      "type": "manual_trigger_damage",
      "note": "debuff faded 附近造成实际命中伤害"
    }
  ]
}
```

## 输出如何接入 boss plugin

输出 JSON 里最重要的是 `mechanism_candidates`：

- `root_spell_ids`：手册入口、施法入口或人工指定入口。
- `aura_ids`：疑似 buff/debuff id。
- `damage_ids`：疑似实际伤害/死亡 id。
- `trigger_spell_ids`：会继续触发其他 spell 的 id。
- `evidence`：为什么它们被连在一起，比如 `EffectTriggerSpell`、同名 spell、人工映射。

后续 boss plugin 不应盲信它，而是把它当“候选草稿”。确认后再拆到：

- `wipe_rules.death_spell_ids`
- `debuff_attribution.debuff_ids`
- `debuff_attribution.death_spell_ids`
- `avoidable_boards.ids`

## 后续接 PTR 的两种路线

1. 在线路线：从 Wago.tools / wow.tools.local 导出指定 build 的 DB2 表，再喂给 `spell_miner`。这适合快。
2. 本地路线：读取 `D:\World of Warcraft\_ptr_\Data` 的 CASC 数据，用 DBCD/WoWDBDefs 解析 DB2，再导出同样的 CSV。这个适合稳定和版本前准备。

我建议先用在线/导出路线把机制归纳跑通，再补本地 CASC provider。因为真正关键的不是下载表，而是把“手册入口 id、隐藏 aura、实际伤害 id、死亡 id”整理成可审阅的关系图。

## 如何从本地 WoW 客户端打开 DB2

WoW 目录里通常看不到单独的 `.db2` 文件。以当前国服正式服安装为例，真实数据在：

```text
D:\World of Warcraft\Data
```

这个目录是 CASC 存储，里面是 `data.xxx`、`.idx`、`indices`、`config` 等文件。`DBFilesClient/SpellName.db2` 这类文件被打包在 CASC 里，所以不能直接用 Excel 或普通编辑器打开。

实际需要两步：

1. CASC 层：从 `Data` 目录里定位并取出 `DBFilesClient/*.db2`。
2. DB2 层：用对应 build 的表结构定义把二进制 DB2 解码成行列数据。

推荐先用 `wow.tools.local` 完成这两步。它本身就集成了读取 CASC 的 `TACTSharp`、读取 DB2 的 `DBCD`，并依赖 `WoWDBDefs` 提供表结构。启动时传入：

```powershell
.\wow.tools.local.exe -wowFolder "D:\World of Warcraft" -wowProduct wow -region cn -locale zhCN
```

然后打开它提示的本地网页，一般是：

```text
http://localhost:5000
```

在网页里进入 DB2/DBC 浏览页面，导出这些表：

```text
SpellName
SpellDescription
SpellAuraDescription
SpellEffect
JournalEncounter
JournalEncounterSection
```

导出的 CSV/TSV 放进一个目录，比如：

```text
db2_exports/live_12_0_7_68275/
```

再运行：

```powershell
python -m spell_miner --db2-dir .\db2_exports\live_12_0_7_68275 --seed-file .\examples\spell_miner_lura_seeds.json --out .\generated\lura_candidates.json
```

如果是 PTR，只要把 `-wowFolder` 换成 PTR 客户端根目录即可，例如：

```powershell
.\wow.tools.local.exe -wowFolder "D:\World of Warcraft\_ptr_" -wowProduct wowt -region us -locale zhCN
```

实际 product 名称要以 Battle.net 安装的 `.build.info` 为准。
