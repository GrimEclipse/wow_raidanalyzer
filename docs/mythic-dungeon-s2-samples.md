# S2 正式服样本与技能清单

2026-09-08 通过 WCL API 核验：正式服为 Zone 55、Partition 1；Zone 56 为已冻结的 PTR。样本先从正式服副本排行榜筛选，再检查原始日志为公开、已完成、正确赛季，并重新核对该 Fight 的实际五人专精。

全部样本为鲜血死亡骑士、奥术法师、神圣圣骑士、武器战士、元素萨满祭司。没有用相近阵容替代，也没有把 PTR 或 S1 数据改名为 S2。

| 副本 | 层数 | 用时 | Boss / 小怪 Pull | WCL |
| --- | ---: | --- | --- | --- |
| 毒牙祭坛 | 20 | 28:43.5 | 3 / 6 | [Fight 13](https://www.warcraftlogs.com/reports/9n2r3JATCDZGkaVN?fight=13) |
| 纳罗拉克的洞穴 | 21 | 30:28.6 | 3 / 10 | [Fight 12](https://www.warcraftlogs.com/reports/LDYGZnMPTBxH3RQg?fight=12) |
| 诸王之眠 | 20 | 29:30.5 | 4 / 7 | [Fight 3](https://www.warcraftlogs.com/reports/CxnMkbgrFfLN9HhP?fight=3) |
| 密谋小径 | 21 | 33:49.2 | 4 / 7 | [Fight 37](https://www.warcraftlogs.com/reports/1WxFnZYQj9qRNGP4?fight=37) |

本地样本位于 `assets/samples/mythic_dungeon_s2_*.json`，清单为 `assets/samples/mythic_dungeon_manifest.json`。页面默认打开 S2，并保留 S1 分组。样本沿用现有路线时间轴结构：Pull 边界、怪物实例、首次交互、存活与敌方施法来自 WCL；玩家技能按本地职业目录筛选。

以上 S2 生成样本及引用它们的本地清单变更不随代码提交。GitHub 新克隆仍加载既有 S1 样本；重新生成 S2 JSON 后可直接在页面导入，或自行加入本地清单。

## 本地已有与待维护的内容

- `config/player_abilities.json`：12.1 玩家技能目录，WCL ID 核验日期 2026-08-13。该五人阵容可匹配 44 个目录项目（43 个施法项目与 1 个光环项目）；当前时间轴沿用成功施法逻辑，未接入鲜血 DK“炼狱”等通用被动光环还原。
- `analyzer_core/mythic_dungeon_configs.py`：S1 已筛选的敌方技能、目标关联与重建规则。
- `data/mythic_dungeon_ptr_zone56_boss_evidence.json`：2026-08-05 留存的七本 PTR Boss 原始取证，缺少独立小怪完整筛选；不能直接当正式服配置。
- `data/mythic_dungeon_s2_skill_review.json`：本次新增的正式服维护底稿，四本共 270 条“场景 / NPC / 技能”候选记录，包含 Boss、小怪、NPC 与技能 ID、中英文名、读条 / 成功施法次数及来源日志。
- `data/mythic_dungeon_s2_skill_review.md`：同一底稿的可读表格。

请在 JSON 的 `include` 填 `true`（保留）或 `false`（排除）；`null` 表示尚未确认。`notes` 可记录需要关联的点名目标、光环或缺失施法重建要求。底稿目前用于维护交接，修改后需要整理成对应 Boss / 副本配置再重新生成，并非页面实时读取的开关。

当前 S2 页面明确标记为“实际施法候选”：显示敌方读条，以及本场没有读条记录的成功施法；没有把这些全部判定为关键技能，没有从伤害或光环猜测缺失施法。候选清单仅覆盖这四份日志，未覆盖另外四本，也不保证囊括同一本所有机制。

## 重新生成

可发布的通用导出器位于 `analyzer_core/mythic_dungeon_export.py`，不依赖被忽略的本地 `tools/`。例：

```powershell
py -3.9 -m analyzer_core.mythic_dungeon_export --report 9n2r3JATCDZGkaVN --fight 13 --dungeon altar_of_fangs --observed-skills --name-zh 毒牙祭坛 --zone 55 --season 2 --party-spec DeathKnight:Blood --party-spec Mage:Arcane --party-spec Paladin:Holy --party-spec Warrior:Arms --party-spec Shaman:Elemental --output assets/samples/mythic_dungeon_s2_altar_of_fangs_9n2r3JATCDZGkaVN_fight13.json
```

使用已配置的 WCL 凭据。生成数据留在本地，遵循 AGENTS.md，不暂存 WCL 输出、数据库或凭据。新增 Boss 的最终规则应放在各自模块；通用导出器只处理传输、证据与文档结构。
