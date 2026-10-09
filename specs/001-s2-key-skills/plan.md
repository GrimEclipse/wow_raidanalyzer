# Implementation Plan: S2 大秘境关键技能筛选

**Branch**: `speckit/s2-key-skills` | **Date**: 2026-09-10 | **Spec**: specs/001-s2-key-skills/spec.md

**Input**: Feature specification from `/specs/001-s2-key-skills/spec.md`

## Summary

把 `/mythic-dungeon` S2 页面从「实际施法候选」预览升级为经筛选的关键技能判定。采用
**数据驱动 + 导出器注入**方案：新增声明式判定数据文件（rulings，本地维护不随代码提交），
`mythic_dungeon_export.py` 新增 `--rulings` 参数在生成样本时把判定合并进样本 JSON
（`skillCandidates[].ruling` + `skillSelection.status` 升级为 `curated`）；前端仅做通用
分组渲染（关键/小怪/未判定），不内嵌任何技能 ID；合并逻辑集中在
`analyzer_core/mythic_dungeon_rulings.py` 纯函数模块，pytest 全覆盖。

## Technical Context

**Language/Version**: Python 3.12（后端/导出器）；vanilla JS（前端，无构建链）

**Primary Dependencies**: 既有 requirements.txt 内依赖；零新增依赖（宪法原则 VI）

**Storage**: 判定数据 = 本地 JSON 文件（`assets/samples/mythic_dungeon_s2_skill_rulings.json`，
与 S2 样本同口径不随代码提交；仓库内提交 JSON Schema + 示例）；样本文档 = 静态 JSON（现状）

**Testing**: pytest（既有套件，基线全绿为准）；前端无自动化测试（人工 quickstart 验证）

**Target Platform**: Linux 服务器（HK，webhook 自动部署 main）；浏览器（现代 Chrome/Edge）

**Project Type**: web-service（server.py 单一入口，静态样本 JSON + 通用前端）

**Performance Goals**: 判定合并 O(n)（n=候选条目，几十条量级）；页面加载不因判定引入可感知延迟

**Constraints**: 不碰 `main`（分支开发）；S1 样本与既有测试零回归；判定数据缺失时优雅降级

**Scale/Scope**: 4 份 S2 样本、每样本几十~几百条候选施法；单人维护口径

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 检查 | 结论 |
|---|---|---|
| I. 一 Boss 一插件 | 判定按「副本+Boss 上下文」存数据文件，不改任何 Boss 插件 | PASS |
| II. 通用/专用隔离 | 前端只渲染 `ruling.category` 通用字段；技能 ID 只存在于数据文件与导出器参数 | PASS |
| III. 单一服务架构 | 不新增服务/离线模式；判定文件走既有 `/assets/` 静态伺服 | PASS |
| IV. 回归基线优先 | 合并逻辑先行测试（TDD）；全量 pytest 为完成标准 | PASS |
| V. 数据卫生 | rulings 与 S2 样本同口径不提交；仅 schema/示例入库 | PASS |
| VI. 简单依赖 | 零新依赖，纯标准库 | PASS |

## Project Structure

### Documentation (this feature)

```text
specs/001-s2-key-skills/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   ├── skill-rulings.schema.json   # rulings 文件 JSON Schema
│   └── document-delta.md           # 样本文档字段增量契约
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
analyzer_core/
├── mythic_dungeon_rulings.py    # NEW: 判定加载/校验/合并（纯函数，可测）
└── mythic_dungeon_export.py     # MODIFIED: --rulings 参数接线路径
frontend/tools/mythic-dungeon/
├── app.js                       # MODIFIED: 通用分组渲染 + 状态文案
└── index.html / app.css         # MODIFIED: 分组容器与样式
tests/
└── test_mythic_dungeon_rulings.py  # NEW: TDD
assets/samples/                  # rulings 实际文件（本地，gitignore 口径同 S2 样本）
```

**Structure Decision**: 不新建顶层目录；全部落在既有 `analyzer_core/`、
`frontend/tools/mythic-dungeon/`、`tests/` 与 `assets/samples/` 内，符合既有布局。
导出器注入而非服务端合并的理由：样本是静态 JSON 且由导出器生成（既有数据流），
服务端零改动即满足宪法 III；前端保持纯通用渲染满足宪法 II。
