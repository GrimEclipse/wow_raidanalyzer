# tools 脚本说明

本目录存放**开发 / 调试 / 离线修复**用的辅助脚本。正式产出报告请优先使用项目根目录的 `analyze.py`；这里的工具用于规则迭代、单场深挖、JSON 修补与环境排查。

## 通用前提

- 在项目根目录执行（`mythic_analyzer/`）。
- Python 建议：`py -3`（Windows）或 `python3`。
- 需要访问 WCL 的脚本（`crown_pam_probe.py`、`crown_single_fight_audit.py`）依赖根目录 `.env` 中的 `WCL_CLIENT_ID` / `WCL_CLIENT_SECRET`。

```powershell
cd C:\path\to\mythic_analyzer
py -3 tools\<脚本名>.py ...
```

---

## 脚本一览

| 脚本 | 是否请求 WCL | 主要用途 |
|------|-------------|----------|
| `reprocess_crown_json.py` | 否 | 离线重算宇宙之冕 JSON 的开庭板与终审 |
| `refresh_crown_cached_output.py` | 否 | 轻量刷新 fieldAudit + 部分开庭分项 |
| `crown_single_fight_audit.py` | 是 | 拉取并生成单场完整场地审计 JSON |
| `crown_pam_probe.py` | 是 | 报告级 WCL 探针与多场摘要 |
| `export_crown_single_fight_form.py` | 否 | 将单场审计 JSON 导出为 Word 明细 |
| `diagnose_runtime.py` | 否 | 检查 Python / `.env` / 路径是否正常 |
| `export_verdict_excel.py` | 否 | 根据终审 payload 生成终审 Excel |

---

## reprocess_crown_json.py

**功能：** 在**不重新请求 WCL** 的前提下，读取已有分析 JSON，按当前开庭规则重算各场 `avoidableSummary`、合并生成 `page2_avoidableBoard` / `page3_courtBoard` / `page4_finalVerdict`。

**适用场景：**

- 开庭规则更新后（如龌勒卢斯易伤同场计 1 次、拉弓归因、P1 银锋箭等），已有 JSON 需要同步。
- 修复 bow 玩家恢复、幻影归因、第 8 死全局豁免等逻辑。

**用法：**

```powershell
py -3 tools/reprocess_crown_json.py data/wcl_<reportId>_crown_of_the_cosmos_<YYYYMMDD>.json
```

- 参数 `path`：输入 JSON 路径；默认 `data/wcl_hardcore_api.json`。
- **原地覆盖**写入（先写 `.tmp` 再替换）。
- 控制台会输出 `Bow repair` 统计（拉弓玩家恢复情况）。

**输入 / 输出：**

- 输入：`data/` 下完整 WCL 分析 JSON（含 `page1_wipeAnalysis`）。
- 输出：同路径文件，更新 board 与终审字段。

---

## refresh_crown_cached_output.py

**功能：** 对已缓存 JSON 做**较轻量**的二次处理：规范化各场 `fieldAudit`（死亡过滤、幻影实例、拉弓双漏射归因等），并据此重建 `missedShadows` / `missedEnergy` 分项及 `page4_finalVerdict`。

**与 reprocess 的区别：**

- `refresh`：主要动 `fieldAudit` + 少数分项，速度快，不负责全套 avoidable 规则重算。
- `reprocess`：逐场完整 normalize + merge board，规则覆盖更全（推荐用于开庭计数变更）。

**用法：**

```powershell
py -3 tools/refresh_crown_cached_output.py data/wcl_xxx.json
py -3 tools/refresh_crown_cached_output.py data/wcl_xxx.json data/wcl_xxx_refreshed.json
```

- `source`：源 JSON（必填）。
- `destination`：可选；省略则覆盖源文件。

---

## crown_single_fight_audit.py

**功能：** 从 WCL 拉取**指定报告的单场战斗**，生成完整「场地审计」JSON（拉弓、放水、银锋箭、幻影段、死亡时间线、P2 射影归因等）。是 `fieldAudit` 逻辑的开发参考实现。

**用法：**

```powershell
py -3 tools/crown_single_fight_audit.py
```

- 脚本内常量：`REPORT_ID`、`FIGHT_ID`（默认 `PAMtmJz8rNywYVQT` / Fight 30）。
- 修改这两个常量后重新运行即可审计其他场次。
- 默认输出：`tmp/crown_fight30_audit.json`。

**依赖：** `.env` 中 WCL 凭证；会大量分页请求事件日志。

---

## crown_pam_probe.py

**功能：** WCL **探针 / 冒烟测试**。对指定报告拉取战斗列表、actor 映射、幻影 actor、部分法术事件计数，并对 `SOURCE_CHECKS` 中配置的样本场做 `analyze_fight` 摘要。

**用法：**

```powershell
py -3 tools/crown_pam_probe.py
```

- 默认报告：`PAMtmJz8rNywYVQT`。
- 默认输出：`tmp/crown_pam_probe.json`。
- 也被 `crown_single_fight_audit.py` 复用（WCL 请求、actor 工具函数等）。

**适用场景：** 验证 WCL API 是否可用、幻影 sourceID 是否变化、新法术 ID 是否有事件。

---

## export_crown_single_fight_form.py

**功能：** 读取 `crown_single_fight_audit.py` 产出的 JSON，生成横向 Word 文档《宇宙之冕单场量化明细》。

**用法：**

```powershell
# 需先运行 crown_single_fight_audit.py 生成输入
py -3 tools/export_crown_single_fight_form.py
```

- 默认输入：`tmp/crown_fight30_audit.json`
- 默认输出：`output/宇宙之冕_Fight30_量化明细.docx`
- 依赖：`python-docx`

修改脚本顶部 `DATA` / `OUT` 常量可换输入输出路径。

---

## diagnose_runtime.py

**功能：** 打印当前终端能否正确执行项目 Python：解释器路径、工作目录、`analyze.py` 是否存在、环境变量与 `.env` 键是否就绪。

**用法：**

```powershell
py -3 tools/diagnose_runtime.py
```

无参数。排查「命令跑不起来 / 读不到 WCL 密钥」时先用它。

---

## export_verdict_excel.py

**功能：** 根据终审面板导出的 payload，使用 `openpyxl` 生成 `智力表_宇宙之冕_<YYYY-MM-DD>.xlsx`。

**用法：**

```powershell
py -3 tools/export_verdict_excel.py
```

（该脚本目前主要被 `offline_server.py` 的 `/api/export-verdict-excel` 调用。）

---

## 推荐工作流

### 规则更新后刷新已有 JSON

```powershell
py -3 tools/reprocess_crown_json.py data/wcl_pZg3NDa6JkY1yqz7_crown_of_the_cosmos_20260715.json
```

然后在浏览器打开 `/report?json=data/wcl_....json` 核对开庭板与智商同步。

### 深挖单场机制

1. 改 `crown_single_fight_audit.py` 的 `REPORT_ID` / `FIGHT_ID`
2. `py -3 tools/crown_single_fight_audit.py`
3. （可选）`py -3 tools/export_crown_single_fight_form.py`

### 环境异常

```powershell
py -3 tools/diagnose_runtime.py
```

---

## 注意事项

- 这些脚本**不会**自动更新 `data/manifest.json`；若离线包需要新文件列表，请手动维护 manifest 或重新 bake。
- `reprocess` / `refresh` 会修改 JSON，建议改前备份或使用 git。
- 正式全量分析仍用根目录 `analyze.py`；tools 仅作补丁与开发辅助。
