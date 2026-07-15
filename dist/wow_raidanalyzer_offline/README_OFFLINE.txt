离线包使用说明（无需安装 Python）
================================

1. 解压本目录到任意位置。
2. 分析 JSON 已放入 data\（也可之后自行覆盖/追加）。
   命名建议：data/wcl_<reportId>_<bossKey>_<开荒日YYYYMMDD>.json
3. 双击 start.bat（或 RaidAnalyzer.exe）。
4. 浏览器会打开本地页面：
   - 首页：选择「场面复盘」或「智商记事本」
   - report：场面分析 / 开庭（顶部可切换 data\ 多份日志）
   - scoreboard：日记式记事本（10 项扣分；「团队」行含 P1 龌勒易伤等）

计分板数据保存在 scoreboard\ 目录（本机 IndexedDB + 可选服务端库）。
关闭 RaidAnalyzer.exe 黑窗口即停止服务。

若 8765 端口被占用：
  RaidAnalyzer.exe --port 8877
