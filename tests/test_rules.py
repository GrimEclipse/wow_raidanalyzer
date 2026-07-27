import unittest

from analyzer_core.rules import RuleEvaluationError, evaluate_expression, evaluate_rule


TRANSITION_RULE = {
    "key": "transition_cliff_death",
    "label": "转阶段坠落",
    "select": {
        "death.phase": ["P1.5", "P2.5"],
        "death.abilityId": [3],
    },
    "countWhen": {
        "lt": [{"field": "fight.phaseDeaths"}, {"value": 8}],
    },
    "exemptWhen": {
        "any": [
            {"eq": [{"field": "fight.isAbandoned"}, {"value": True}]},
            {"gte": [{"field": "fight.totalDeathsBefore"}, {"value": 8}]},
        ],
    },
    "verdict": {
        "points": 1,
        "reason": "{death.player} 在 {death.phase} 死于 {death.ability}",
    },
}


def context(phase_deaths, *, abandoned=False, total_before=0):
    return {
        "death": {
            "phase": "P2.5",
            "abilityId": 3,
            "ability": "坠崖",
            "player": "测试玩家",
        },
        "fight": {
            "phaseDeaths": phase_deaths,
            "isAbandoned": abandoned,
            "totalDeathsBefore": total_before,
        },
    }


class RuleEngineTests(unittest.TestCase):
    def test_transition_deaths_below_eight_are_counted(self):
        result = evaluate_rule(TRANSITION_RULE, context(7))
        self.assertTrue(result["matched"])
        self.assertTrue(result["counted"])
        self.assertEqual(result["points"], 1)
        self.assertEqual(result["reason"], "测试玩家 在 P2.5 死于 坠崖")

    def test_transition_deaths_at_eight_are_not_counted(self):
        result = evaluate_rule(TRANSITION_RULE, context(8))
        self.assertTrue(result["matched"])
        self.assertFalse(result["counted"])

    def test_abandoned_fight_is_exempted(self):
        result = evaluate_rule(TRANSITION_RULE, context(2, abandoned=True))
        self.assertTrue(result["exempted"])
        self.assertFalse(result["counted"])

    def test_unsupported_operator_is_rejected(self):
        with self.assertRaisesRegex(RuleEvaluationError, "不支持"):
            evaluate_expression({"python": "__import__('os')"}, {})


if __name__ == "__main__":
    unittest.main()
