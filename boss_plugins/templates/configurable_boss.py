from boss_plugins.common import placeholder_analyze


PLUGIN_CONFIG = {
    "boss": {
        "key": "example_boss",
        "name": "示例 Boss",
        "keywords": ["example boss", "示例 Boss"],
    },
    # The report shell renders panels from capabilities. New bosses must declare
    # these explicitly; legacy outputs are inferred by analyzer_core.contracts.
    "capabilities": {
        "wipe": {"enabled": True, "renderer": "generic-wipe"},
        "avoidable": {"enabled": True, "renderer": "generic-avoidable"},
        "interrupts": {"enabled": False, "renderer": "generic-interrupts"},
        "dispels": {"enabled": False, "renderer": "generic-dispels"},
        "mistakes": {"enabled": False, "renderer": "mistake-tracker"},
        "verdict": {"enabled": False, "renderer": "mistake-verdict"},
        "replay": {"enabled": False, "renderer": "field-audit"},
    },
    "snapshot_contract": {
        "player": [
            "id",
            "name",
            "spec",
            "position",
            "facing",
            "vitals.hitPoints",
            "vitals.maxHitPoints",
            "vitals.healthPercent",
            "vitals.absorb",
            "vitals.healAbsorb",
        ],
        "missing_value_policy": "Use null; never substitute zero or per-hit absorbed damage.",
        "healing_absorb": {
            "enabled": False,
            "spell_ids": [],
            "policy": "Do not add requests only for the player card.",
        },
    },
    "phases": [
        {"key": "P1", "before_ms": 180_000},
        {"key": "P2", "from_ms": 180_000},
    ],
    "wipe_rules": [
        {
            "key": "death_spell_reason",
            "reason": "示例机制死亡",
            "trigger": {"death_spell_ids": [123456]},
            "link": {"type": "damage-taken", "before_ms": 15_000, "after_ms": 2_000},
        },
        {
            "key": "replay_position_review",
            "reason": "示例站位复盘",
            "trigger": {"death_spell_ids": [654321]},
            "link": {"type": "replay", "position_ms": 330_000},
        },
    ],
    "interrupts": {
        "enabled": False,
        "mode": "rotation",
        "groups": [],
    },
    "debuff_attribution": [
        {
            "key": "example_fade_death",
            "title": "示例 debuff 致死归因",
            "phase": "P2",
            "debuff_ids": [111111],
            "death_spell_ids": [222222],
            "match_window_ms": 1500,
            "fatal_only": True,
        },
    ],
    "avoidable_boards": [
        {"key": "avoidableExample", "label": "示例可躲技能", "ids": [333333]},
    ],
    "panels": [
        {"type": "wipe_analysis"},
        {"type": "avoidable_board"},
    ],
}


def analyze(report_ids: str, output_path=None, catalog_entry=None):
    return placeholder_analyze(report_ids, output_path, catalog_entry)
