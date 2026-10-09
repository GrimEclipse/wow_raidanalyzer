# Quickstart: S2 大秘境关键技能筛选 — 端到端验证

## 前置条件

- 仓库根目录：`/opt/wow_raidanalyzer`，分支 `speckit/s2-key-skills`
- Python 3.12 + `.venv`（仓库既有）
- rulings 示例文件：复制 `specs/001-s2-key-skills/contracts/` 内示例或手写一份到
  `assets/samples/mythic_dungeon_s2_skill_rulings.json`（本地文件，不提交）
- S2 样本：本机已有生成样本或按 `docs/mythic-dungeon-s2-samples.md` 重新生成
  （需要 WCL 凭据；无凭据时用单测夹具样本验证导出器接线）

## 1. 单元与回归测试

```bash
cd /opt/wow_raidanalyzer
.venv/bin/python -m pytest tests/test_mythic_dungeon_rulings.py -v   # 新功能测试
.venv/bin/python -m pytest                                            # 全量回归（宪法 IV 门槛）
```

预期：新文件测试全绿；全量 0 failed（基线数量只增不减）。

## 2. 导出器接线验证（无 WCL 凭据路径）

用测试夹具文档直接调合并函数：

```bash
.venv/bin/python - <<'EOF'
from analyzer_core.mythic_dungeon_rulings import apply_rulings
import json
doc = json.load(open("assets/samples/mythic_dungeon_<某个S2样本>.json"))
result = apply_rulings(doc, "assets/samples/mythic_dungeon_s2_skill_rulings.json")
print(result["skillSelection"])
EOF
```

预期：`status` 变 `curated`、`rulings.applied` 为正数；或 `rulingsError` 给出明确原因
（两者都算通过——降级路径合法）。

## 3. 页面人工验证

1. 起服务：`.venv/bin/python server.py`（或既有部署口）。
2. 打开 `/mythic-dungeon`，选择 S2 样本。
3. **分组展示**：候选事件按「关键技能 / 小怪或其他 / 未判定」三组展示，判定过的技能
   带 evidence 展开项。
4. **降级回退**：把 rulings 文件改坏（坏 JSON）→ 重新生成/加载 → 页面回到「实际施法候选」
   整体列表 + 可见提示，服务无 5xx。
5. **S1 不受影响**：选择任一 S1 样本，渲染与改动前一致。
6. **数据驱动**：把 rulings 中某技能 `trash → key`，重新生成样本后刷新页面，该技能移入
   关键技能组（全程未改代码）。

## 验收对照（spec Success Criteria）

- 5 秒内区分关键/小怪 → 步骤 3.3
- 修订一条判定 ≤1 分钟 → 步骤 3.6
- 全量 pytest 通过 + 三类场景覆盖 → 步骤 1
