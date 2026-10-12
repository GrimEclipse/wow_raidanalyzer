# Tasks: S2 大秘境关键技能筛选

**Feature**: specs/001-s2-key-skills | **Branch**: `speckit/s2-key-skills`
**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## Phase 1: Setup

- [x] T001 创建 rulings 示例文件 `specs/001-s2-key-skills/contracts/rulings.example.json`（含 encounter 与 trash 各一条判定、一条 `key` 带 evidence、校验合法）

## Phase 2: Foundational

- [x] T002 [P] 新建 `analyzer_core/mythic_dungeon_rulings.py`：实现 `load_rulings(path) -> tuple[dict, str|None]`（加载+校验+降级，规则 V1-V5）与 `apply_rulings(document, path) -> document`（按 `(dungeonKey, bossContext, spellId)` 合并进 `skillCandidates[].include/notes/ruling`，更新 `skillSelection`，见 contracts/document-delta.md）
- [x] T003 [P] 新建 `tests/test_mythic_dungeon_rulings.py`：覆盖加载成功/文件缺失/坏 JSON/schema 顶层错误、合并填充三字段、上下文隔离（同 spellId 不同 bossContext）、`key` 无 evidence 被跳过、未知 dungeonKey 整组跳过、S1 文档零影响、`applied>0` 才升 `curated`（TDD：先 T003 红再 T002 绿）
- [x] T004 接线 `analyzer_core/mythic_dungeon_export.py`：CLI 增 `--rulings PATH`（默认指向 `assets/samples/mythic_dungeon_s2_skill_rulings.json`，`--no-rulings` 关闭），在样本写盘前调用 `apply_rulings`；补一条接线单测

## Phase 3: User Story 1 — 查看已判定的关键技能清单 (P1)

**Story Goal**: 团长在 S2 页面看到关键/小怪/未判定三组泾渭分明的技能分组。
**Independent Test**: 带判定字段的样本 JSON 在页面渲染出三组，组内条目与数据一致。

- [x] T005 [P] [US1] `frontend/tools/mythic-dungeon/app.js`：候选区按 `ruling.category` 通用三分组渲染（key/trash/unreviewed 桶 + 计数），`status=="curated"` 才启用分组，否则维持现有整体列表；无任何 spellId 字面量
- [x] T006 [P] [US1] `frontend/tools/mythic-dungeon/index.html` + `app.css`：三组分节容器、组标题、`season-notice` 文案随 `status` 切换（curated：已配置关键技能筛选）

## Phase 4: User Story 2 — 判定有据可查 (P2)

- [x] T007 [US2] `frontend/tools/mythic-dungeon/app.js`：关键技能条目展开渲染 `ruling.evidence[]`（metric/value/source）与 notes；数据无 evidence 的 key 条目不渲染依据区（数据层已由 V2 保证，前端只做通用展示）

## Phase 5: User Story 3 — 维护者增量修订 (P3)

- [x] T008 [US3] 数据驱动验证：基于 contracts 示例复制本机 rulings 文件，改一条 `trash→key` 后重跑 `apply_rulings`，确认输出随数据变化（脚本化验证，不改代码）
- [x] T009 [US3] 降级 UX 验证：坏 JSON rulings 重跑，确认 `skillSelection.status` 保持 `needs-review` 且 `rulingsError` 有值、页面回退候选预览（脚本 + 人工页面各验一次）

## Phase 6: Polish & Cross-Cutting

- [x] T010 回归门槛：`.venv/bin/python -m pytest` 全量 0 failed（基线只增不减）
- [x] T011 更新 `docs/mythic-dungeon-s2-samples.md`「本地已有与待维护的内容」节：登记 rulings 文件口径、schema/示例位置与修订流程
- [x] T012 `git status` 卫生检查（宪法 V：rulings 实际文件与 S2 样本不入库），提交至 `speckit/s2-key-skills` 分支（不推 main，生产零风险）

## Dependencies

- T002/T003 互相配合（TDD），T004 依赖 T002；US1（T005/T006）依赖 T002 数据契约；T007 依赖 T005；T008/T009 依赖 T002；T010-T012 收尾。
- 用户故事顺序：US1 → US2 → US3（P1→P3），US1 完成即 MVP 可演示。

## Parallel Execution Example

- T002 + T003 同批（同分支不同文件，TDD 红绿迭代）
- T005 + T006 同批（前端 js 与 html/css 分离）
- T001/T008 与后端任务无文件冲突，可穿插

## Implementation Strategy

- MVP = Phase 1-3（数据契约 + 合并逻辑 + US1 分组展示）：生成的新样本已可区分关键技能。
- US2/US3 是体验与维护性增量，随后补齐。
- 每阶段结束跑一次 pytest 快检，最终 T010 全量把关。
