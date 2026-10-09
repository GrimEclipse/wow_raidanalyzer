# Phase 0 Research: S2 大秘境关键技能筛选

## R1: 判定数据的接入层选型

**Decision**: 导出器（`mythic_dungeon_export.py`）在生成样本时合并判定；服务端 `server.py`
零改动。

**Rationale**: 样本文档是导出器产出的静态 JSON（文档 `docs/mythic-dungeon-s2-samples.md` 的
重新生成流程是唯一权威来源）；服务端只做静态伺服（`/assets/` 路径已在 `handle_static` 白名单）。
在导出层合并 = 单一数据流、无第二事实源，且天然满足宪法 III（不动 server.py）。

**Alternatives considered**:
- 服务端按需读取 rulings 文件并注入响应：需要改 server.py 处理逻辑，且静态 JSON 口径被打破
  （同一 URL 内容随另一个文件漂移），否决。
- 前端并行 fetch rulings 文件自行合并：前端承载业务逻辑，违反宪法 II 通用/专用隔离精神，
  且浏览器端两次 fetch 增加状态同步复杂度，否决。

## R2: `skillCandidates` 现有结构与复用性

**Decision**: 直接复用既有 `skillCandidates[]` 行（含 `encounterId/pullType/npcId/npcName/
spellId/nameZh/nameEn/include/notes/eventCounts`），追加 `ruling` 子对象；
`include/notes` 两个既有空字段由 ruling 填充语义（`include=true/false/null` ↔
`category=key/trash/unreviewed`），不另起炉灶。

**Rationale**: 导出器已生成该结构（`mythic_dungeon_export.py:191-216`），行内已有
`include/notes` 预留字段——官方结构本来就为人工筛选预留了位置，补齐语义成本最低。

**Alternatives considered**:
- 新建独立 `keySkills[]` 数组：与 `skillCandidates` 重复承载同一批技能，前端要处理两套
  数据源，否决。

## R3: 判定数据文件的格式与存放

**Decision**: `assets/samples/mythic_dungeon_s2_skill_rulings.json`，按
`{ dungeonKey: { bossContext: { spellId: {category, evidence[], notes} } } }` 三层嵌套；
仓库内提交 `specs/001-s2-key-skills/contracts/skill-rulings.schema.json` + 一份
`examples/`（2-3 条假数据示例），实际文件 gitignore 口径同 S2 样本。

**Rationale**: 「副本+Boss 上下文+技能」三元组定位一条判定，满足 spec FR-1 的上下文隔离
（同一技能在 Boss 战与小怪波出现的分类可不同）；声明式 JSON 满足 FR-1 可版本化与
US3「改数据不改代码」；schema+示例入库满足 FR-5，实际数据不入库满足宪法 V。

**Alternatives considered**:
- SQLite（如 raid_calendar.db）：样本/判定都是静态生成物，数据库引入写路径与迁移负担，
  过度设计，否决。
- Python dict 常量入库：判定会频繁修订，代码文件每次改都污染 git 历史，且违反
  「数据驱动」要求，否决。

## R4: 降级行为（FR-4）

**Decision**: 合并函数对「文件不存在 / JSON 解析失败 / schema 不符」三类异常统一返回
空判定映射 + 原因字符串；导出器在 `skillSelection` 上保留 `status:"needs-review"`
并附加 `rulingsError` 字段；S2 页面由此自动回退现有「候选事件」展示并提示判定数据不可用。

**Rationale**: 三类异常都在导出（生成时）发生而非页面加载时，浏览器端零新失败模式；
`rulingsError` 让维护者从导出产物直接看出哪类问题，可调试性最强。

**Alternatives considered**:
- 解析失败直接抛异常中断导出：一次数据文件笔误会阻断整条样本生成链，可用性差，否决。

## R5: 前端展示的通用性边界

**Decision**: 前端新增逻辑仅限于：读取 `skillSelection.status` 与
`skillCandidates[].ruling.category` 做通用分组（key/trash/unreviewed 三桶）、渲染
`ruling.evidence[]` 数组、状态文案切换。不出现任何 spellId 字面量、不出现 Boss 判定规则。

**Rationale**: 宪法原则 II；分组三桶是通用分类学（数据里来），不是机制知识。

## R6: 测试策略

**Decision**: `tests/test_mythic_dungeon_rulings.py` 覆盖：加载成功/文件缺失/坏 JSON/
schema 不符四类输入；合并对 `include/notes/ruling` 三字段的填充；按上下文隔离（同 spellId
不同 bossContext 判定不同）；S1 文档（无 skillCandidates）零影响。导出器接线用最小
monkeypatch 单测验证参数传递。全量 pytest 为回归门槛。

**Rationale**: 合并逻辑是纯函数，最适合单测；导出器端到端需要 WCL 凭据，只测接线不测
真实抓取（与既有测试口径一致）。
