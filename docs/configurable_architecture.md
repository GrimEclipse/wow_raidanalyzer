# 配置化复盘架构

维护者：卫宇珩

## 目标

项目不再把“如何取证、如何判定、如何展示”全部写进单个 Boss Python 文件。12.0 的现有插件继续可用，新 Boss 按统一数据契约和规则包逐步接入。

最终应用同时支持：

- 服务端通过 WCL report ID 拉取日志并生成分析数据；
- 用户在页面上传分析 JSON，并按日志/Boss 唯一身份缓存在浏览器；
- 团长在规则编辑器中调整阈值、阶段、豁免和计数方式；
- 同一份基础数据可用不同规则包重新计算，不必重新请求 WCL；
- 页面直接读取已经生成的视图模型，实现快速渲染；
- 场地推演按 Boss 配置选择底图、坐标系和阶段状态。

## 四层数据

### 1. Encounter Bundle：不可变的基础数据

这是 JSON 的基底，不包含“某人应被判几次”这类结论。它保存：

- `analysisIdentity`：版本、副本、Boss、report ID、开荒日期和稳定 key；
- 战斗、玩家、NPC 与角色信息；
- 已标准化的死亡、施法、伤害、光环、驱散、打断、战复和坐标事件；
- 事件索引与可追溯的 WCL 时间戳；
- 为控制体积而裁剪过的证据窗口。

WCL 凭据只存在服务端。浏览器不直接持有 Client Secret。

### 2. Rule Pack：可编辑的判定规则

规则包只使用白名单运算符，不执行任意 JavaScript/Python。建议结构：

```json
{
  "schemaVersion": 1,
  "encounter": {
    "version": "12.1",
    "raidKey": "venomous_abyss",
    "bossKey": "nakzali"
  },
  "phases": [],
  "rules": [
    {
      "key": "transition_cliff_death",
      "label": "转阶段坠落",
      "scope": "death",
      "select": {
        "phase": ["P1.5", "P2.5"],
        "abilityId": [3]
      },
      "countWhen": {
        "lt": [{ "field": "fight.phaseDeaths" }, { "value": 8 }]
      },
      "exemptWhen": {
        "any": [
          { "eq": [{ "field": "fight.isAbandoned" }, { "value": true }] },
          { "gte": [{ "field": "fight.totalDeaths" }, { "value": 8 }] }
        ]
      },
      "verdict": {
        "points": 1,
        "reason": "{player} 在 {phase} 死于 {ability}"
      },
      "evidence": {
        "beforeMs": 8000,
        "afterMs": 2000,
        "include": ["death", "damage", "position"]
      }
    }
  ],
  "panels": ["wipe", "court", "replay"]
}
```

首批白名单运算符应限制为：`all`、`any`、`not`、`eq`、`ne`、`lt`、`lte`、`gt`、`gte`、`in`、`exists`、`count`、`sum` 和 `uniqueCount`。

### 3. Evaluation Result：规则执行结果

规则引擎读取 Encounter Bundle 与 Rule Pack，输出统一证据：

- 命中的规则；
- 计数/不计数；
- 豁免原因；
- 涉及玩家、阶段和时间；
- 原始事件引用；
- 场地坐标和 WCL 深链。

每条判定必须能回到证据，不允许只输出不可解释的最终分数。

### 4. View Model：页面快速渲染数据

View Model 是从执行结果生成的页面参数，包含灭团卡片、玩家榜、开庭分项、场地推演层和最终判决。它可以随时重建，不应成为唯一事实来源。

现有 `page1_wipeAnalysis`、`page2_avoidableBoard`、`page3_courtBoard` 等字段先由兼容适配器继续输出，等前端完成通用面板迁移后再逐步退场。

## 唯一身份与缓存

分析数据使用以下字段确定唯一性：

```text
version + raidKey + bossKey + sorted(report IDs) + progressDate
```

后端在输出 JSON 时写入 `meta.analysisIdentity` 与 `meta.analysisId`。旧 JSON 没有这些字段时，前端按同一规则推导。

页面上传的 JSON 缓存在 IndexedDB：

- 同一身份再次导入时覆盖；
- 刷新页面后仍可从下拉菜单读取；
- 用户可清除页面缓存；
- 服务端 `data/`、离线包内嵌数据和浏览器缓存使用同一个加载接口。

## API 边界

建议逐步形成以下接口：

```text
POST /api/sessions/import             上传 Encounter Bundle 或兼容旧 JSON
POST /api/sessions/from-wcl           根据 report ID 拉取并标准化
GET  /api/sessions                    按唯一身份列出缓存
GET  /api/sessions/{id}/bundle        获取基础数据
POST /api/sessions/{id}/evaluate      使用指定 Rule Pack 重新判定
GET  /api/rule-packs                  获取 Boss 规则包
PUT  /api/rule-packs/{id}             保存团长自定义规则
GET  /api/sessions/{id}/view          获取快速渲染 View Model
```

纯前端离线模式使用 Web Worker 执行同一套规则；本地服务器模式由服务端执行，但输入输出契约保持一致。

## 12.0 迁移顺序

1. 保留宇宙之冕、光盲先锋军和至暗之夜降临现有插件，作为结果对照组。
2. 先抽出阶段识别、死亡阈值、主动放弃和基础事件筛选四类通用算子。
3. 将 M6 跳楼规则迁移为第一份真实 Rule Pack，并对旧日志做逐场结果对比。
4. 抽出 WCL 鉴权、分页、actors/fights/events 请求，消除三个插件中的重复客户端代码。
5. 通用规则结果稳定后，再把专用 Python 逻辑缩减为少量 Boss hook。

## 12.1 接入约定

- `boss_catalog.json` 是版本、副本、Boss、外部唯一键和场地图的唯一目录源；
- 场地图存放在 `assets/raids/<raidKey>/`；
- 每个 Boss 使用稳定 key，与提供的外部 key 一一映射；
- 截图中另列的潮缚石窟首领尼姆瑞莎·唤波者单独归入 `tidebound_grotto`，不混入烈毒之渊序号；
- Boss 未拿到战斗日志和技能 ID 前保持 `supported: false`；
- 不用猜测技能、阶段或正式中文名，未知字段明确标记待定。
