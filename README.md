# Mythic Analyzer

面向 WCL 的团队副本复盘工具。Boss 逻辑、Boss 专用前端和全局产品工具彼此隔离。

## 启动

复制 `.env.example` 为 `.env` 并填写 WCL API 凭据，然后运行：

```text
start_app.bat
```

或执行 `python server.py --open`，访问 `http://127.0.0.1:8765/`。

稳定入口：

- `/report`：按 JSON 中的 Boss 身份选择通用报告或专用报告
- `/online`：通过界面运行 WCL 分析
- `/raid-guide`：12.1 团长手册
- `/cooldowns`：团队技能时间轴查询与 MRT/NSRT 导出
- `/loot`：开荒出勤、需求权与装备分配日历
- `/audit`：奥蕾莉亚场地明细

命令行仍可用于开发和自动化：

```powershell
py analyze.py --version 12.0 --raid void_spire --boss crown_of_the_cosmos --report your_report_id
```

生成数据统一写入 `data/`。

## 目录

- `analyzer_core/`：共享契约、调度、数据路径和团队技能
- `boss_plugins/`：后端 Boss 插件
- `frontend/report/`：报告入口、通用报告和 Boss 前端插件
- `frontend/tools/`：团长手册、团队时间轴、在线执行器与团队运营工具
- `skills/`：项目维护规范与 Boss 研究资料
- `tools/debug/`：手工调试入口
- `host/OfflineHost.cs`：无需 Python 的离线宿主

新增 Boss 时注册后端插件，并创建
`frontend/report/plugins/<raidKey>/<bossKey>/plugin.js`。只有通用报告无法表达时，才增加该 Boss 的专用 `report.html`。

## 离线包

```powershell
.\build_offline_package.bat
```

产物位于 `dist/wow_raidanalyzer_offline/`。最终用户将 JSON 放入 `data/` 后运行 `start.bat`。
