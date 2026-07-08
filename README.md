# Mythic Analyzer

WCL 开荒日志复盘工具。项目以本地 Web 应用作为入口，按版本、副本和 Boss 调用对应插件，生成并展示复盘 JSON。

## 本机配置

复制 `.env.example` 到 `.env`，填入自己的 WCL API 凭据：

```env
WCL_CLIENT_ID=your_client_id
WCL_CLIENT_SECRET=your_client_secret
WCL_BASE_URL=https://www.warcraftlogs.com
WCL_PROXY=http://127.0.0.1:7890
WCL_REPORT_IDS=your_report_id
```

也可以直接用系统环境变量传入这些值。

## 命令行分析

```powershell
python analyze.py --version 12.0 --raid march_on_queldanas --boss midnight_falls --report your_report_id
```

默认会输出 `wcl_hardcore_api.json`，报告页 `/report` 会读取这个本地结果。该文件是本地生成数据，已加入 `.gitignore`，不要提交到仓库。

## 本地应用入口

推荐直接双击：

```text
start_app.bat
```

或手动启动：

```powershell
python server.py --open
```

服务启动后进入 `http://127.0.0.1:8765/`。

页面入口：

- `/`：应用首页，选择 JSON 查看、在线分析或大秘境抄轴工具。
- `/report`：报告查看页，读取默认 `wcl_hardcore_api.json` 或手动上传 JSON。
- `/online`：在线分析页，选择版本、副本和 Boss 后提交 report id。
- `/mythic-dungeon`：大秘境抄轴工具，固定读取 `mythic_dungeon_export/wcl_casts_log.json`。

当前在线入口开放：

- 光盲先锋军
- 宇宙之冕
- 至暗之夜降临

## 大秘境抄轴

`mythic_dungeon_export/` 保存大秘境施法导出工具和固定 JSON。当前模板标识为 `magisters_terrace`，页面会根据配置的 Boss 技能、小怪技能、药水和玩家监控技能生成：

- 总体大米时间轴
- 按玩家筛选的个人相关时间轴
- 每个 Boss 的关键技能窗口
- 药水 / 爆发波次

后续新增副本时，按同样结构补充技能配置即可。

## 目录

- `analyzer_core/`：版本、副本、Boss 目录、进度回调、并发工具和插件调度。
- `boss_plugins/`：按团队副本拆分的 Boss 分析插件。
- `mythic_dungeon_export/`：大秘境施法导出脚本和固定时间轴 JSON。
- `tools/`：项目辅助工具脚本。
- `server.py`：本地 Web 服务和在线分析任务队列。
- `index.html`：应用入口页。
- `online.html`：在线分析页。
- `report.html`：报告查看页。
- `mythic-dungeon.html`：大秘境抄轴页面。
- `boss_catalog.json`：前端可读取的 Boss 目录。
- `docs/`：插件配置化、产品结构和机制归因说明。
