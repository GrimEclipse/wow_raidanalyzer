# Phase 1 Data Model: S2 大秘境关键技能筛选

## Entity: SkillRuling（判定条目）

判定数据文件中的一条记录，按三层键定位：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| (定位键) dungeonKey | string | 是 | 副本标识，如 `altar_of_fangs`，与样本 manifest/dungeon key 一致 |
| (定位键) bossContext | string | 是 | Boss 上下文：`"encounter:<encounterId>"`（Boss 战）或 `"trash"`（小怪波） |
| (定位键) spellId | int | 是 | 敌方技能 ID（> 0） |
| category | string | 是 | `key`（关键技能）/ `trash`（小怪或其他）/ `unreviewed`（未判定） |
| evidence | Evidence[] | category=key 时必填 | 量化依据，≥1 条 |
| notes | string | 否 | 维护者备注（映射到候选行既有 `notes` 字段） |

## Entity: Evidence（判定依据）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| metric | string | 是 | 依据类型，如 `totalDamage` / `affectedPlayers` / `castCount` / `officialSource` |
| value | string | 是 | 人读值（如 "4/5 players hit"），不参与比较逻辑 |
| source | string | 否 | 出处说明（如 "WCL 9n2r3JATCDZGkaVN fight13"） |

## Entity: 样本文档增量（Document Delta）

生成后的 S2 样本 JSON 相对现状的变化：

| 路径 | 变化 | 说明 |
|---|---|---|
| `skillSelection.status` | `needs-review` → `curated` | 仅当该 dungeonKey 存在至少一条判定时 |
| `skillSelection.policy` | 不变 | `observed-hostile-casts` 保留为历史口径 |
| `skillSelection.rulings` | 新增 | `{file, applied, skipped}` 应用统计 |
| `skillSelection.rulingsError` | 条件新增 | 判定数据异常时的原因串 |
| `skillCandidates[i].ruling` | 条件新增 | `{category, evidence[], notes}`，未命中技能不加该字段 |
| `skillCandidates[i].include` | 填充 | `key→true, trash→false, unreviewed→null`（既有字段） |
| `skillCandidates[i].notes` | 填充 | 既有字段，ruling.notes 为空则保留空串 |
| 其余文档结构 | 不变 | S1 文档无 `skillCandidates`/`skillSelection`，零影响 |

## Validation Rules

- V1: `category` 必须是三值枚举之一，否则该条跳过并计入 `skipped`。
- V2: `category=key` 且 `evidence` 为空 → 该条跳过并计入 `skipped`（FR-3）。
- V3: `spellId` 必须为正整数。
- V4: rulings 中出现样本文档不存在的 `dungeonKey` → 整组跳过并计入 `skipped`（不报错）。
- V5: 文件缺失/坏 JSON/schema 顶层结构错误 → 空映射 + `rulingsError`（FR-4，优雅降级）。

## State Transitions

判定生命周期（数据文件视角）：`unreviewed（默认，无条目）→ key / trash（人工写入）
→ 修订（改 category 或 evidence）`。无运行时状态机——判定是静态数据，随样本重新生成生效。
