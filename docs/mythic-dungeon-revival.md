# 大秘境抄轴恢复清单

核对日期：2026-09-08。已追加四份正式服 S2 指定阵容样本，入口移到首页 Mythic TOOLS；当前为待筛选的实际施法预览。最新来源和维护底稿见 [S2 样本说明](mythic-dungeon-s2-samples.md)。以下保留 S1 与历史取证清点。

## 已恢复的预览

首页提供 `/mythic-dungeon` 样例入口，由 `server.py` 服务。页面可切换八个第一赛季副本、导入本地分析 JSON、查看 Boss / 小怪 Pull、开怪归属、怪物实例与存活时间、关键施法和玩家状态，并按玩家、事件类型、全局 / Pull 时间筛选。

- 页面：`frontend/tools/mythic-dungeon/`。
- 样例清单：`assets/samples/mythic_dungeon_manifest.json`，八份 JSON 均在同目录。
- 样例副本：艾杰斯亚学院、魔导师平台、迈萨拉洞窟、节点希纳斯、萨隆矿坑、执政团之座、通天峰、风行者之塔。
- 现有分析器：`analyzer_core/mythic_dungeon_timeline.py`。
- 第一赛季配置：`analyzer_core/mythic_dungeon_configs.py`。
- 公共玩家技能目录：`config/player_abilities.json`。

## 找到的第二赛季资料

`data/mythic_dungeon_ptr_zone56_boss_evidence.json` 生成于 **2026-08-05**，来源明确为 WCL Zone 56、PTR 分区 1、难度 10。它是原始证据，不是可直接导入页面的 `mythic-dungeon-route-timeline` 文档。

| 副本 | Boss Pull 数 | 各 Pull 技能记录数合计 |
| --- | ---: | ---: |
| 毒牙祭坛 | 3 | 41 |
| 纳罗拉克的洞穴 | 3 | 41 |
| 诸王之眠 | 4 | 55 |
| 密谋小径 | 4 | 63 |
| 红玉新生法池 | 3 | 48 |
| 塞塔里斯神庙 | 4 | 50 |
| 虚空之痕竞技场 | 3 | 29 |
| 合计 | 24 | 327 |

这些数量是已记录技能条目，不能直接当成关键技能数量。每条带技能 ID、中英文名、施法与附近 Debuff 证据。采集器只将有 encounter ID 的 Boss Pull 写入结果；Boss 战中的召唤物可能在内，但没有独立小怪 Pull 的完整取证。`Blinding Vale` 被原采集清单明确排除，不能宣称新赛季八本齐备。

本地工具还在，但被当前 `.gitignore` 排除，GitHub 新克隆不会获得它们：

- `tools/discover_ptr_mythic_dungeon_spells.py`：PTR Boss 技能取证。
- `tools/find_mythic_dungeon_sample.py`：公开样例查找。
- `tools/export_mythic_dungeon_timeline.py`：单份 WCL 转换。
- `tools/export_mythic_dungeon_samples.py`：第一赛季样例生成。
- `tmp/ptr_altar_probe.json`：另有毒牙祭坛本地探针文件，暂未作为配置来源。

原始资料继续保留在本地，不将生成 WCL 数据、配置凭据或缓存纳入提交。

## 新赛季接入顺序与验收

1. 确认目标正式服赛季、WCL Zone / 分区与有效 encounter ID，重取代表性过本日志，对比 PTR 证据。首个候选为已有三场 Boss 证据的毒牙祭坛。
2. 按 `boss_plugins/<raid>/` 中“一 Boss 一模块”的约束维护各 Boss 的技能、关联目标和重建规则；副本小怪数据也按副本隔离。通用时间轴引擎只处理事件与配置。现有第一赛季集中配置是历史实现，新赛季不继续往其中堆入多 Boss 逻辑。
3. 补采独立小怪 Pull 的敌对施法、伤害、光环、NPC ID 与实例，区分读条、成功施法、中断和重建证据；不能把所有伤害技能直接列成关键技能。
4. 将采集、转换能力整理为可发布的后端模块，再通过 `server.py` 的账号凭据上下文、任务进度和临时结果机制接入。当前仅有静态页面路由，没有大秘境在线查询 API。
5. 首本验收：Boss 与小怪 Pull 边界正确；目标、实例、时间基准正确；重建事件有明确标签；职业技能来自公共目录；输出可导入现有页面。随后逐本扩展，并单独补齐缺失副本。

## 本次验证

既有大秘境时间轴和样例契约测试、PTR 取证测试均通过；八份 S1 与四份 S2 样例文件和清单匹配。S2 已有实际日志预览，但完整关键技能筛选、缺失事件重建和在线查询入口仍待后续接入。
