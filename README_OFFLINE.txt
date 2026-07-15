WoW Raid Analyzer 离线包（无需 Python）
====================================
编者：卫宇珩

本离线包是纯静态文件。构建时会把 data/ 下全部 wcl_*.json（以及根目录
兼容文件 wcl_hardcore_api.json、若存在的 verdict_data.json）完整映射烘焙进
assets/vendor/wcl_hardcore_api.js，收件人可在报告页下拉切换多天日志。

快速开始
--------
1. 双击 start_offline.bat（会提示是否已内嵌数据；有 Python 则顺带起本地服务）。
2. 或直接双击 index.html / report.html。
3. 主报告：report.html；终审历史：verdict.html；逐场场地：crown-fight-audit.html。

数据如何自动加载
----------------
- 打包脚本会把 JSON 写成：
    window.__WCL_DATA_BY_SOURCE__ = { "data/wcl_....json": {...}, ... }
    window.__WCL_HARDCORE_DATA__ = <默认/兼容主源>
    window.__VERDICT_DATA__ = {...}   （若构建时有 verdict_data.json）
- 页面通过 offline-data-loader.js 按 URL 的 ?json= 路径取对应内嵌对象，
  因此 file:// 也能切换多份日志。
- 若未烘焙成功，file:// 下仍会弹出「选择复盘 JSON」作为兜底。

更换 / 追加日志数据
------------------
1. 把新的导出放进工程 data/（命名：
   单日志 wcl_<reportId>_<boss>_<开荒日YYYYMMDD>.json；
   多日志 wcl_multi_<boss>_<导出日YYYYMMDD>.json）。兼容旧文件仍可放根目录
   wcl_hardcore_api.json。
2. 重新运行 build_offline_package.bat / .ps1，再分发新的 zip。
3. 也可把 JSON 直接覆盖离线包 data/ 中的同名文件；有本地 HTTP 时可 fetch，
   纯 file:// 仍建议重新烘焙以更新完整映射。

URL 书签
--------
报告页支持：
  report.html?json=data/wcl_mH8AFN1xXq94J2kW_crown_of_the_cosmos.json
便于多天日志快速辨识与分享。

终审导出
--------
- 在主报告「终审判决」填写开荒日期后点击确认，会下载：
  verdict-YYYY-MM-DD.json
- 建议存到文件夹：verdicts/
- 文件字段仅含：判定次数、判定原因、申诉无罪次数、申诉无罪原因、最终总智力损失。
- 日期可手动修改；不同开荒日的导入靠 progressDate 区分。

可选本地 HTTP
-------------
双击 start_offline.bat 时若本机有 Python，会启动 offline_server.py
（默认 http://127.0.0.1:8765/），并提供 /api/data-files 列举 data/。
没有 Python 时直接打开 HTML，内嵌完整映射下功能完整可用。
