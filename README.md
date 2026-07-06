# Mythic Analyzer

WCL 开荒日志复盘工具。当前项目以本地 Web 应用作为入口，按版本、团队副本和 Boss 调用对应插件，生成并展示复盘 JSON。

## 本机配置

复制 `.env.example` 到 `.env`，填入自己的 WCL API 凭据：

```env
WCL_CLIENT_ID=your_client_id
WCL_CLIENT_SECRET=your_client_secret
WCL_PROXY=http://127.0.0.1:7890
WCL_REPORT_IDS=your_report_id
```

也可以直接用系统环境变量传入这些值。

## 命令行分析

```powershell
python analyze.py --version 12.0 --raid march_on_queldanas --boss midnight_falls --report your_report_id
```

默认会输出 `wcl_hardcore_api.json`，报告页 `report.html` 会读取这个结果。该 JSON 允许提交到仓库，用作默认展示和回归样例。

## 本地应用入口

推荐直接双击：

```text
start_app.bat
```

或手动启动：

```powershell
python server.py --open
```

服务启动后会进入 `http://127.0.0.1:8765/`。

页面入口：

- `/`：应用首页，选择 JSON 查看或在线分析。
- `/report`：报告查看页，读取默认 `wcl_hardcore_api.json` 或手动上传 JSON。
- `/online`：在线分析页，选择版本、团队副本和 Boss 后提交 report id。

当前在线入口只开放：

- 光盲先锋军
- 宇宙之冕
- 至暗之夜降临

未接入的 Boss 会在选择框里置灰。至暗之夜降临会额外显示终结矩阵打断分配预设输入。

## 目录

- `analyzer_core/`：版本、副本、boss 目录和插件调度。
- `boss_plugins/`：按团队副本拆分的 boss 分析插件。
- `server.py`：本地 Web 服务和在线分析任务队列。
- `index.html`：应用入口页。
- `online.html`：在线分析页。
- `report.html`：报告查看页。
- `boss_catalog.json`：前端可读取的 Boss 目录。
- `wcl_hardcore_api.json`：默认报告 JSON，可提交到仓库。
- `docs/`：插件配置化、产品结构和机制归因模式说明。
