# Document Delta Contract: S2 样本 JSON 判定字段

本文档是 `analyzer_core/mythic_dungeon_rulings.py` 与消费方（导出器、前端）之间的契约。
字段全部为**可选增量**：不存在时消费方必须保持既有行为（向后兼容）。

## skillSelection 增量

```json
{
  "skillSelection": {
    "status": "needs-review | curated",
    "policy": "observed-hostile-casts",
    "note": "...（既有字段，不变）",
    "rulings": {
      "file": "<rulings 文件路径或 'embedded'>",
      "applied": 12,
      "skipped": 1
    },
    "rulingsError": "rulings file not found | invalid JSON | invalid schema (仅异常时存在)"
  }
}
```

规则：
- `status` 升级为 `curated` 当且仅当 `rulings.applied > 0` 且无 `rulingsError`。
- `applied` = 成功合并到候选行的判定条数；`skipped` = 因校验规则 V1-V4 被跳过的条数。

## skillCandidates[] 增量

```json
{
  "encounterId": 421,
  "pullType": "boss | trash",
  "npcId": 12345,
  "npcName": "…",
  "spellId": 442504,
  "nameZh": "…",
  "nameEn": "…",
  "include": true | false | null,
  "notes": "…",
  "eventCounts": {"cast": 3, "begincast": 1},
  "ruling": {
    "category": "key | trash | unreviewed",
    "evidence": [{"metric": "totalDamage", "value": "…", "source": "…"}],
    "notes": "…"
  }
}
```

匹配键：`(dungeonKey, bossContext, spellId)`，其中
`bossContext = encounterId ? "encounter:<encounterId>" : "trash"`（取候选行自身
`encounterId`）。未命中的候选行**不添加** `ruling` 字段（前端归入「未判定」组）。

## 兼容性

- S1 文档：无 `skillSelection`/`skillCandidates`，完全不受影响。
- 旧 S2 文档（本特性之前生成）：无增量字段，前端按现状渲染候选预览。
- 新 S2 文档（rulings 异常）：`rulingsError` 存在、`status` 保持 `needs-review`，
  前端回退候选预览并提示。

## 前端展示映射（通用，无技能知识）

| 数据 | 展示 |
|---|---|
| `status == "curated"` 且候选含 `ruling.category` | 候选按 key/trash/unreviewed 三组分节渲染 |
| `status != "curated"` | 维持现有「候选事件」整体列表 |
| `ruling.evidence[]` | 判定详情内逐条渲染 metric/value/source |
