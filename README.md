# Mythic Analyzer

面向 WCL 的团队副本复盘工具。Boss 逻辑、Boss 专用前端和全局产品工具彼此隔离。

## 启动

运行服务后在网页注册账号，并在“我的账号与 WCL”中保存当前用户的 WCL Client 凭据。命令行分析仍可使用 `.env.example` 中的环境变量配置。

```text
start_app.bat
```

或执行 `python server.py --open`，访问 `http://127.0.0.1:8765/`。服务默认监听
`0.0.0.0:8765`，服务器部署可通过 `APP_HOST`、`APP_PORT`（或平台提供的
`PORT`）覆盖监听地址与端口。

稳定入口：

- `/`：公开首页；`/raid-guide`：无需登录的团长手册
- `/account`：当前用户的 WCL 凭据、工会与密码；`/admin/accounts`：仅 admin 的账号管理
- `/report`：按 JSON 中的 Boss 身份选择通用报告或专用报告
- `/online`：通过界面运行 WCL 分析
- `/single-fight`：手动读取已配置工会的 report，按开荒日选择单场 Pull 并复用 Boss 逐场规则；相同 Fight 使用缓存
- `/spec-compare`：单场单专精与 WCL 对标日志的 Buff、资源溢出、爆发窗口和施法序列报告；支持下载独立 HTML 留档
- `/cooldowns`：团队技能时间轴查询与 MRT/NSRT 导出
- `/raid-calendar`：管理员专用的开荒出勤、需求权与装备分配日历（旧 `/loot` 地址继续兼容）
- `/audit`：奥蕾莉亚场地明细

账号等级为普通账户、管理员、admin。普通账户可以运行 WCL 分析并修改自己的凭据；管理员还可以使用 Avalon 工会运营；admin 另可管理账号。所有 WCL 查询都使用发起查询的登录用户保存的凭据。

首页提供独立的 **Mythic TOOLS / 大秘境工具** 分区，入口为 `/mythic-dungeon`。可输入 Report 和 Fight 直接分析大秘境，也能查看第一赛季八本历史日志、第二赛季四份正式服样本或导入本地 JSON。已配置副本采用规则表；其余副本暂展示公开完成日志的实际施法候选，仍待筛选 Boss / 小怪关键技能。来源、维护清单与生成方式见 [S2 样本说明](docs/mythic-dungeon-s2-samples.md)。

`/online` 整场分析根据当前 Boss 插件显示逐项配置，选择应用于日志中的全部 Pull；分析项目默认全选，场地推演可单独关闭。高级单场选择也复用相同配置，首页一键分析保持完整分析。关闭项目会跳过对应计算及独占的 WCL 取证，其他已选项目仍保留必要的共享证据，报告明确标记未分析项目。

服务器默认允许 4 个任务同时分析，同一账号同时运行 1 个任务；单任务内最多 4 个 Pull 并行，全进程 WCL 请求并发上限为 6。可在环境变量或 `.env` 配置 `WCL_MAX_JOB_THREADS`、`WCL_MAX_USER_JOB_THREADS`、`WCL_MAX_FIGHT_THREADS`、`WCL_MAX_REQUEST_THREADS`，修改后重启 `server.py`。4 不是硬上限，服务器允许时可将 `WCL_MAX_JOB_THREADS` 设为 8、16 或更高；如果旧部署显式设置为 1，需修改该配置才能跨账号并发。排队时状态区域显示运行数/容量、等待数、入队顺序位置及等待原因，并随队列变化更新。详细行为与验证见 [分析配置和任务并发](docs/analysis-options-and-concurrency.md)。

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
