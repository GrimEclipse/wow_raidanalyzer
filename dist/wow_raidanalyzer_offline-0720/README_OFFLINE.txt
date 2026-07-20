离线包使用说明（无需安装 Python / openpyxl）
==========================================

1. 解压后应得到外层文件夹 wow_raidanalyzer_offline\，再进入该目录使用。
2. 分析 JSON 已放入 data\（也可之后自行覆盖/追加）。
   命名建议：data/wcl_<reportId>_<bossKey>_<开荒日YYYYMMDD>.json
3. 双击 start.bat（或 RaidAnalyzer.exe）。
4. 浏览器会打开本地页面：
   - 首页：选择「场面复盘」或「智商记事本」
   - report：场面分析 / 开庭 / 终审（顶部可切换 data\ 多份日志）
   - scoreboard：日记式记事本（判定明细默认可收起）
5. 终审「导出 Excel」：优先走本机 API；若无 Python+openpyxl，
   浏览器会用 assets\vendor\verdict-xlsx.js 直接生成 .xlsx（无需额外依赖）。

计分板数据保存在 scoreboard\ 目录。
关闭 RaidAnalyzer.exe 黑窗口即停止服务。

若 8765 端口被占用：
  RaidAnalyzer.exe --port 8877
