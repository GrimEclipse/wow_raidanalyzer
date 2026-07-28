import unittest

from analyzer_core.config import resolve_analysis_options, validate_config_schema


SCHEMA = [
    {"key": "enabled", "type": "boolean", "default": True},
    {
        "key": "threshold",
        "type": "number",
        "integer": True,
        "min": 0,
        "max": 500,
        "default": 200,
        "visibleWhen": {"field": "enabled", "equals": True},
    },
    {"key": "players", "type": "playerList", "default": ["甲", "乙"]},
    {
        "key": "mode",
        "type": "select",
        "default": "evidence_only",
        "options": [
            {"value": "evidence_only", "label": "仅取证"},
            {"value": "adjudicate", "label": "归责"},
        ],
    },
]


class AnalysisConfigTests(unittest.TestCase):
    def test_defaults_are_resolved_and_copied(self):
        first = resolve_analysis_options(SCHEMA, {})
        second = resolve_analysis_options(SCHEMA, {})
        self.assertEqual(first["threshold"], 200)
        self.assertEqual(first["players"], ["甲", "乙"])
        first["players"].append("丙")
        self.assertEqual(second["players"], ["甲", "乙"])

    def test_ui_values_are_coerced(self):
        result = resolve_analysis_options(
            SCHEMA,
            {"enabled": "false", "threshold": "275", "players": "甲，乙 甲", "mode": "adjudicate"},
        )
        self.assertFalse(result["enabled"])
        self.assertEqual(result["threshold"], 275)
        self.assertEqual(result["players"], ["甲", "乙"])
        self.assertEqual(result["mode"], "adjudicate")

    def test_unknown_option_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "未知"):
            resolve_analysis_options(SCHEMA, {"python": "nope"})

    def test_number_bounds_are_enforced(self):
        with self.assertRaisesRegex(ValueError, "不能大于"):
            resolve_analysis_options(SCHEMA, {"threshold": 501})

    def test_invalid_select_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "允许范围"):
            resolve_analysis_options(SCHEMA, {"mode": "guess"})

    def test_duplicate_schema_keys_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "重复"):
            validate_config_schema([SCHEMA[0], SCHEMA[0]])

    def test_unknown_visibility_parent_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "未知字段"):
            validate_config_schema([
                {"key": "child", "type": "boolean", "visibleWhen": {"field": "missing", "equals": True}},
            ])

    def test_self_visibility_dependency_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "依赖自身"):
            validate_config_schema([
                {"key": "child", "type": "boolean", "visibleWhen": {"field": "child", "equals": True}},
            ])


if __name__ == "__main__":
    unittest.main()
