# Mythic Analyzer

面向 WCL 的团队副本复盘工具。Boss 逻辑、Boss 专用前端和全局产品工具彼此隔离。

## 启动

复制 `.env.example` 为 `.env` 并填写 WCL API 凭据，然后运行：

```text
start_app.bat
```

或执行 `python server.py --open`，访问 `http://127.0.0.1:8765/`。服务默认监听
`0.0.0.0:8765`，服务器部署可通过 `APP_HOST`、`APP_PORT`（或平台提供的
`PORT`）覆盖监听地址与端口。

稳定入口：

- `/report`：按 JSON 中的 Boss 身份选择通用报告或专用报告
- `/online`：通过界面运行 WCL 分析
- `/single-fight`：手动读取已配置工会的 report，按开荒日选择单场 Pull 并复用 Boss 逐场规则；相同 Fight 使用缓存
- `/spec-compare`：单场单专精与 WCL 对标日志的 Buff、资源溢出、爆发窗口和施法序列报告；支持下载独立 HTML 留档
- `/raid-guide`：团本手册
- `/cooldowns`：团队技能时间轴查询与 MRT/NSRT 导出
- `/raid-calendar`：开荒出勤、需求权与装备分配日历（旧 `/loot` 地址继续兼容）
- `/audit`：奥蕾莉亚场地明细

命令行仍可用于开发和自动化：

```powershell
py analyze.py --version 12.0 --raid void_spire --boss crown_of_the_cosmos --report your_report_id
```

生成数据统一写入 `data/`。

## 目录

- `analyzer_core/`：共享契约、调度、数据路径、单场分析和团队技能
- `boss_plugins/`：后端 Boss 插件
- `frontend/report/`：报告入口、通用报告和 Boss 前端插件
- `frontend/tools/`：团本手册、团队时间轴、在线执行器与团队运营工具
- `config/player_abilities.json`：按职业/专精维护的 WCL 已验证爆发、减伤、功能、打断与控制技能公共目录
- `data/raid_calendar.db`：团本日历、出勤和拾取分配的本地持久化数据（不纳入 Git）

新增 Boss 时注册后端插件，并创建
`frontend/report/plugins/<raidKey>/<bossKey>/plugin.js`。只有通用报告无法表达时，才增加该 Boss 的专用 `report.html`。

产品仅由 `server.py` 提供在线服务，不再维护离线宿主或离线打包链路。
