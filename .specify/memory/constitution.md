<!--
Sync Impact Report
- Version change: (none) → 1.0.0 (initial ratification)
- Modified principles: n/a (initial)
- Added sections: Core Principles I–VI; Additional Constraints; Development Workflow; Governance
- Removed sections: n/a
- Deferred TODOs: none
- Source: distilled from repository AGENTS.md architecture guardrails (2026-09-10) and
  observed deployment policy (webhook auto-deploy on main).
-->

# Mythic Analyzer (wow_raidanalyzer) Constitution

## Core Principles

### I. 一 Boss 一插件（One Boss, One Plugin）

每个 Boss 的逻辑必须独立成 `boss_plugins/<raid>/` 下的一个 Python 模块；该模块独占
此 Boss 的技能 ID、机制判定规则、analyzer、配置与场地（court）档案。禁止创建多 Boss
共享逻辑容器（如 `progression.py`、`court_profiles.py`）。理由：Boss 机制彼此独立演化，
共享容器会让单 Boss 改动波及全体，回归风险不可控。

### II. 通用与专用隔离（Generic/Specialized Separation）

前端选择器与通用运行时（generic runtime）对 Boss 机制保持无知：它们只负责按插件
清单调度，绝不内嵌任何 Boss 专属判定。Boss 无关的可复用助手只允许放在
`boss_plugins/common.py`、副本级 `shared.py` 或通用运行时模块；共享模块内禁止出现
Boss 技能 ID 或 Boss 判定逻辑。

### III. 单一服务架构（NON-NEGOTIABLE）

应用只由 `server.py` 提供服务。禁止恢复任何离线服务器、离线 host 或离线打包器。
生产部署走 webhook 对 `main` 分支的自动部署；任何破坏 `server.py` 单一入口假设的
改动必须先修订本宪法。

### IV. 回归基线优先（Regression Baseline First）

影响分析结果、API 行为或页面路由的改动，必须以 pytest 全量通过作为完成标准；
现有测试视为行为基线，改基线（改测试断言）必须在提交说明中给出理由。
新功能先有失败测试再有实现（测试先行）；纯文档/配置改动豁免。

### V. 数据与凭据卫生（Data & Credential Hygiene）

禁止把生成的 WCL 数据、本地数据库（`cache/`、`data/` 下的运行时库）、凭据、缓存
或无关工作区改动加入提交。`.env`、WCL API 凭据只存在于本地文件；样本 JSON 与
本地清单变更不随代码提交（见 docs/mythic-dungeon-s2-samples.md）。

### VI. 简单依赖（Simplicity）

能不新增依赖就不新增：后端优先标准库与既有 requirements.txt 内的库；前端沿用
既有 vanilla JS 结构。任何新依赖必须在使用处注明不可替代的理由。

## Additional Constraints

- 团本日历、出勤与装备分配的线上真库是 `data/raid_calendar.db`；规范路由为
  `/raid-calendar` 与 `/api/raid-calendar`，`/loot`、`/api/loot` 仅为兼容别名。
- 旧名 `scoreboard` 与旧应用 `/verdicts` 已退役，禁止恢复；Boss 本地 verdict 字段
  是分析数据，不是独立应用。
- 大文件、模型与生成产物落数据盘软链约定（如 `/data/hotclip/*` 模式），系统盘只留
  程序本体。
- 面向玩家的页面文案默认中文；代码、提交信息与测试名用英文。

## Development Workflow

1. 分支：改动先开 feature 分支（生产 `main` 由 webhook 自动部署，未验证改动不得
   直推 main）。
2. 实现：遵循原则 I/II 的边界；提交前跑 `pytest` 全量（原则 IV）。
3. 提交：提交信息用英文 conventional 风格（feat/fix/docs/chore + 范围）；遵守
   原则 V 的卫生清单，`git status` 复核只含预期文件。
4. 部署：合并到 main 即触发 webhook 自动部署；部署后以 HTTPS 入口 + 关键 API
   回环验证。

## Governance

- 本宪法优先于仓库内其他约定文档；冲突时以本文件为准。
- 修订必须：说明理由、按语义化版本递增（MAJOR=原则废弃/重定义，MINOR=新增原则
  或实质扩展，PATCH=措辞澄清），并同步更新 AGENTS.md 中对应条目（AGENTS.md 是
  宪法在代码侧的执行摘要）。
- 代码评审与验收检查以本文件为合规基线；复杂度引入必须给出可验证的理由。

**Version**: 1.0.0 | **Ratified**: 2026-09-10 | **Last Amended**: 2026-09-10
