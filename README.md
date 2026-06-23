# Mythic Analyzer

WCL 开荒日志复盘工具。当前项目已经拆出 boss plugin 架构，并保留鲁拉 / 至暗之夜降临的分析入口。

## 本机配置

复制 `.env.example` 到 `.env`，填入自己的 WCL API 凭据：

```env
WCL_CLIENT_ID=your_client_id
WCL_CLIENT_SECRET=your_client_secret
WCL_PROXY=http://127.0.0.1:7890
WCL_REPORT_IDS=your_report_id
```

也可以直接用系统环境变量传入这些值。

## 运行

```powershell
python analyze.py --version 12.0 --raid march_on_queldanas --boss midnight_falls --report your_report_id
```

默认会输出 `wcl_hardcore_api.json`，前端页面 `LuraJudgement.html` 会读取这个结果。

## 目录

- `analyzer_core/`：版本、副本、boss 目录和插件调度。
- `boss_plugins/`：按团队副本拆分的 boss 分析插件。
- `WCLMechanicMiner/`：用于在游戏内从地下城手册采集机制素材的轻量 WoW 插件。
- `docs/`：插件配置化和后续自动生成方案说明。

`legacy/` 是本地备份目录，默认不上传到仓库。
