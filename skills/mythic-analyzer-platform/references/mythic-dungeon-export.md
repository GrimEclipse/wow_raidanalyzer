# Mythic Dungeon Export

大秘境抄轴工具把一份可访问的 WCL 完成记录固化为可审查的路线时间轴。

## 稳定入口

- 页面：`/mythic-dungeon`
- 前端：`frontend/tools/mythic-dungeon/`
- 样板清单：`assets/samples/mythic_dungeon_manifest.json`
- 样板资源：`assets/samples/mythic_dungeon_<dungeon>_<report>_fight<id>.json`
- 12.1 技能跟踪表：`mythic-dungeon-12.1-spell-tracker.md`

## 生成流程

- `tools/find_mythic_dungeon_sample.py`：读取 WCL 地下城排行榜候选。
- `tools/export_mythic_dungeon_timeline.py`：导出一份指定报告。
- `tools/export_mythic_dungeon_samples.py`：按审定清单生成八个样板和 manifest。
- `analyzer_core/mythic_dungeon_configs.py`：副本名称、怪物技能与特殊目标关联规则。
- `analyzer_core/mythic_dungeon_timeline.py`：WCL `dungeonPulls` 到稳定 JSON 合同的转换。

选择规则为“公开且可读取的最高完成层优先，同层取最高记录”；通天峰固定使用用户指定的战临 +24。若排行榜条目对应的报告已转为私有，应在同层顺延到第一份可读取记录。

## 事件合同

- Pull 边界与怪物构成：WCL `dungeonPulls`。
- 怪物与 Boss：只取 `begincast`；无预读条但需要目标还原的技能走配置特例。
- 玩家技能：只取成功 `cast`。
- 噬灭恶魔猎手虚空恶魔变形：以 1225789 计数光环的 `removebuff` 还原进入时刻。
- 高阶贤者维里克斯灼烧射线：将 1253538 `cast` 与同毫秒 1253541 `applydebuff` 关联为三名目标。
- UI 的“与我相关”只过滤玩家事件；怪物与 Boss 时间轴始终保留。

## 无目标点名映射

- 艾杰斯亚学院：法力炸弹 386173 → 点名 386181；能量炸弹 374343 → 点名 374350。
- 迈萨拉洞窟：灵魂束缚 1252777 的 WCL `cast` 已直接携带目标。
- 萨隆矿坑：白霜冲击 1262745 → 点名 1262772。
- 节点希纳斯：蚀光步伐 1249014 → 点名 1249020，后续效果 1252875；辉熠消散 1253855 → 点名 1255503。
- 执政团之座：群体虚空灌输 1263542 → 同 ID 点名；不谐射线 1265463 → 点名 1265426，后续效果 1265464。
- 通天峰：灼烧射线 1253538 → 点名 1253541。
- 风行者之塔：炽焰腾流 466556 → 点名 466559；劲风射击 1253986 → 点名 1253979，约 6 秒后转为消水效果 1253978。
