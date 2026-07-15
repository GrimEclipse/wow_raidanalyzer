离线包使用说明（无需安装 Python）
================================

1. 运行仓库内 build_offline_package.bat（或 .ps1）生成：
   - dist\wow_raidanalyzer_offline\
   - dist\wow_raidanalyzer_offline.zip
2. 打包脚本会复制：前端 HTML、assets、Boss 图标、data\wcl_*.json，并编译 RaidAnalyzer.exe
3. 解压/进入 dist\wow_raidanalyzer_offline\ 后双击 start.bat
4. 浏览器打开后：
   - report.html：场面分析 / 开庭（顶部可切换 data\ 多份日志）
     · P1 龌勒卢斯易伤异常在「扣分项目」；按场计数，不进个人终审
   - scoreboard.html：智商记事本
     · 10 项扣分始终展示；「团队」行收录龌勒易伤等机制计数
     · 上一天/下一天按日历移动，空日也可进入
     · 选中某份分析 JSON「导入到该开荒日」会跳到日志日期
     · 时间显示为中国时间（UTC+8）
     · 改动自动存本机；有宿主时顺带写本地库

关闭 exe 黑窗口即停止本地服务。
