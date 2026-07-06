# Debuff Fade Attribution

有些机制的伤害或死亡不是由最终受害者自己触发，而是由另一个玩家身上的 debuff 消失、爆炸或传递造成。此类机制不要只看死亡事件的 source/target，需要把死亡或伤害事件回溯到附近的 debuff faded/remove 事件。

## 基本流程

1. 读取机制相关 debuff 事件，至少包含 apply 和 remove/fade。
2. 读取死亡或伤害事件。
3. 对每条死亡/伤害，在时间窗口内寻找最近的 debuff remove/fade。
4. 将 remove/fade 事件的 target 作为影响来源。
5. 将最终受害者、影响来源、debuff 时间、死亡/伤害时间一起写入结果。

## 当前实现参考

- 至暗之夜降临：`boss_plugins/march_on_queldanas/midnight_falls_core.py`
  - `is_debuff_fade`
  - `nearest_stellar_fade`
  - `analyze_p4_stellar_shards`
- 宇宙之冕：`boss_plugins/void_spire/crown_of_the_cosmos.py`
  - `attribute_debuff_fade`
  - `analyze_collapsing_void`

至暗之夜降临里的星辰裂片逻辑是最早验证过的实现：通过 debuff faded 判断是谁的技能影响到其他人。宇宙之冕后续如果继续扩展类似机制，优先复用 `attribute_debuff_fade` 这种通用形态，而不是再写只适配单个技能的临时代码。

## 注意点

- 时间窗口不要过大。一般先从 `500ms-2000ms` 开始，根据 WCL 事件顺序微调。
- 如果同一时间有多个 remove/fade，优先匹配同 ability id，再按时间距离排序。
- 输出时要区分“死亡者”和“影响来源”，避免把责任归到被影响的人身上。
- 如果没有匹配到 faded 事件，结果应保留为空或回退到死亡/伤害原始 source，不要伪造归因。
