# Boss 插件自动配置草案

目标不是让后台直接生成大量手写逻辑，而是让后台生成一份 `PLUGIN_CONFIG`，再由通用分析器读取配置。

## 目录约定

```text
boss_plugins/
  dream_rift/
    chimaerus.py
  void_spire/
    imperator_averzian.py
    vorasius.py
  march_on_queldanas/
    midnight_falls.py
  templates/
    configurable_boss.py
```

每个团队副本是一个大文件夹，每个 boss 是一个单文件。

## 后台表单应收集的信息

- 基础信息：版本、副本、boss key、boss 中英文名、WCL boss 名关键词
- 阶段规则：按时间、按 cast、按死亡技能、按 debuff/cast 信号进入阶段
- 灭团规则：死亡技能、阶段限定、优先级、WCL 链接类型
- 回放定位点：固定机制时间点、相对事件偏移、WCL replay position，用于检查站位和分散
- 打断规则：是否启用、固定轮次/左右场/目标分配、名单
- debuff 归因：debuff id、faded/apply 事件、匹配死亡/伤害 id、匹配窗口
- 可躲避榜：技能 id、展示名、是否统计死亡
- 前端模块：是否展示打断证据、debuff 归因表、可躲避榜、特殊时间线

## 自动生成的插件形态

```python
from boss_plugins.configurable import analyze_from_config


PLUGIN_CONFIG = {
    "boss": {
        "key": "midnight_falls",
        "name": "至暗之夜降临",
        "keywords": ["midnight falls", "l'ura", "至暗之夜降临", "鲁拉"],
    },
    "phases": [
        {"key": "P1", "before_ms": 231000},
        {"key": "P2", "from_ms": 231000, "before_ms": 330000},
        {"key": "P2转P3", "from_ms": 330000, "before_ms": 342000},
        {
            "key": "P4",
            "signals": {
                "death_spell_ids": [1279581, 1281473, 1276526],
                "after_ms": 330000,
                "no_death_after_ms": 510000
            }
        }
    ],
    "wipe_rules": [
        {
            "key": "terminal_matrix_interrupt",
            "reason": "终结矩阵漏断",
            "trigger": {"death_spell_ids": [1286276]},
            "analyzer": "interrupt_rotation",
            "link": {"type": "interrupts", "before_ms": 25000, "after_ms": 2000}
        },
        {
            "key": "p2_to_p3_spread",
            "reason": "纳鲁的挽歌（漏接鲁拉之泪）",
            "trigger": {"death_spell_ids": [1254256]},
            "link": {
                "type": "replay",
                "position_ms": 330000,
                "description": "定位到黑暗熔毁分散收尾点，检查人员分散位置"
            }
        }
    ],
    "debuff_attribution": [
        {
            "key": "p4_stellar_shard_death",
            "title": "P4 星辰裂片致死归因",
            "phase": "P4",
            "debuff_ids": [1285510, 1279512],
            "death_spell_ids": [1279581, 1281473],
            "match_window_ms": 1500,
            "fatal_only": True
        }
    ],
    "avoidable_boards": [
        {"key": "skyGlaive", "label": "天穹战刃", "ids": [1254076]}
    ]
}


def analyze(report_ids: str, output_path=None, catalog_entry=None):
    return analyze_from_config(PLUGIN_CONFIG, report_ids, output_path, catalog_entry)
```

## 建议的演进路线

1. 先保留至暗之夜降临的现有插件入口，作为已验证基准。
2. 写一个 `boss_plugins/configurable.py`，支持 `death_spell_reason`、`interrupt_rotation`、`debuff_fade_death`、`avoidable_board` 四种通用分析器。
3. 用奇美鲁斯做第一个纯配置 boss，验证不写特殊 Python 也能跑。
4. 当某个 boss 有特殊机制时，只在单 boss 文件里补一个小 hook，不改 core。
