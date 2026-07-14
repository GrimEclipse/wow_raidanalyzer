# 奥蕾莉亚开庭面板显示过滤

## 当前规则

`report.html` 只在前端展示层过滤以下五名玩家：

- `Jokermeow`
- `黑心喵`
- `Leviac`
- `Leviackerman`
- `茶喵不吃糖`

底层 `wcl_hardcore_api.json`、逐场分析和插件统计均保留完整数据。

## 以后移除过滤

在 `report.html` 中搜索常量 `COURT_DISPLAY_EXCLUDED_PLAYERS`。

删除该常量、`isCourtDisplayExcluded` 函数，以及 `bindData` 中下列三处 `.filter(...)` 即可：

1. `page4_finalVerdict` 映射前的过滤。
2. `page2_avoidableBoard` 各栏目行数据的过滤。
3. `page2_avoidableFirstDeathBoard` 前置死亡排行的过滤。

## 对外静态包

场地分析页的离线 JSON 选择功能由以下文件提供：

`assets/vendor/offline-data-loader.js`

对外提供静态文件时，需保留 `crown-fight-audit.html`、`wcl_hardcore_api.json`、`assets/` 的相对目录结构。通过 `file://` 双击页面时会弹出 JSON 文件选择框；通过本地 HTTP 服务访问时会继续自动读取 URL 中的 `source` 参数。
