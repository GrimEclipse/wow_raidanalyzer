# Mythic Analyzer

WCL 开荒日志复盘工具。分析场面战斗与「智商计分板」分离：前者产出 JSON 与开庭明细，后者按开荒日期做日记式计分、申诉留痕与追加扣分。

## 本机配置（分析用）

复制 `.env.example` 到 `.env`，填入 WCL API 凭据后可用命令行或 `/online` 拉日志。

## 给最终用户的离线包（无需 Python）

```powershell
.\build_offline_package.bat
```

产物在 `dist/wow_raidanalyzer_offline/`：

- `RaidAnalyzer.exe`：本地宿主（提供静态页 + `data/` / `scoreboard/` API）
- `start.bat`：双击启动
- `data/`：把分析得到的 `*.json` 丢进这里即可被自动加载
- `scoreboard/`：计分板按日持久化
- `report.html` / `scoreboard.html` / `assets/` …

对方用法：解压 → 把 JSON 放进 `data/` → 双击 `start.bat`。

## 开发者本机入口

```text
start_app.bat
```

或 `python server.py --open` → `http://127.0.0.1:8765/`

- `/` 首页
- `/report` 场面分析 / 开庭
- `/scoreboard` 智商计分板日记
- `/online` 在线拉 WCL（需本机 Python）

## 命令行分析

```powershell
py analyze.py --version 12.0 --raid void_spire --boss crown_of_the_cosmos --report your_report_id
```

输出默认 `wcl_hardcore_api.json`（已 gitignore）。

## 目录

- `analyzer_core/`：目录、进度、并发、调度
- `boss_plugins/`：Boss 插件
- `host/OfflineHost.cs`：离线 exe 源码（打包时用 csc 编译）
- `tools/`：辅助脚本
- `scoreboard.html`：计分板
- `report.html`：分析报告
- `docs/`：说明文档
