import re
from typing import Any, Dict, Iterable


class RuleEvaluationError(ValueError):
    pass


def get_field(context: dict, path: str) -> Any:
    value: Any = context
    for part in str(path or "").split("."):
        if not part:
            continue
        if isinstance(value, dict) and part in value:
            value = value[part]
            continue
        if isinstance(value, (list, tuple)) and part.isdigit():
            index = int(part)
            value = value[index] if 0 <= index < len(value) else None
            continue
        return None
    return value


def _pair(operands: Any, operator: str) -> tuple:
    if not isinstance(operands, list) or len(operands) != 2:
        raise RuleEvaluationError(f"{operator} 需要两个参数。")
    return operands[0], operands[1]


def _collection(value: Any) -> Iterable:
    if value is None:
        return []
    if isinstance(value, dict):
        return value.values()
    if isinstance(value, (list, tuple, set, str)):
        return value
    return [value]


def resolve_value(node: Any, context: dict) -> Any:
    if not isinstance(node, dict):
        return node
    if set(node) == {"value"}:
        return node["value"]
    if set(node) == {"field"}:
        return get_field(context, node["field"])
    if len(node) != 1:
        raise RuleEvaluationError("表达式对象必须只包含一个运算符。")

    operator, operands = next(iter(node.items()))
    if operator == "count":
        return len(list(_collection(resolve_value(operands, context))))
    if operator == "sum":
        return sum(float(value or 0) for value in _collection(resolve_value(operands, context)))
    if operator == "uniqueCount":
        return len({str(value) for value in _collection(resolve_value(operands, context))})
    return evaluate_expression(node, context)


def evaluate_expression(expression: Any, context: dict) -> bool:
    if isinstance(expression, bool):
        return expression
    if not isinstance(expression, dict) or len(expression) != 1:
        raise RuleEvaluationError("逻辑表达式必须是只包含一个运算符的对象。")

    operator, operands = next(iter(expression.items()))
    if operator == "all":
        if not isinstance(operands, list):
            raise RuleEvaluationError("all 需要数组参数。")
        return all(evaluate_expression(item, context) for item in operands)
    if operator == "any":
        if not isinstance(operands, list):
            raise RuleEvaluationError("any 需要数组参数。")
        return any(evaluate_expression(item, context) for item in operands)
    if operator == "not":
        return not evaluate_expression(operands, context)
    if operator == "exists":
        return resolve_value(operands, context) is not None

    binary_operators = {"eq", "ne", "lt", "lte", "gt", "gte", "in", "contains"}
    if operator not in binary_operators:
        raise RuleEvaluationError(f"不支持的规则运算符：{operator}")
    left_node, right_node = _pair(operands, operator)
    left = resolve_value(left_node, context)
    right = resolve_value(right_node, context)
    if operator == "eq":
        return left == right
    if operator == "ne":
        return left != right
    if operator == "lt":
        return left is not None and right is not None and left < right
    if operator == "lte":
        return left is not None and right is not None and left <= right
    if operator == "gt":
        return left is not None and right is not None and left > right
    if operator == "gte":
        return left is not None and right is not None and left >= right
    if operator == "in":
        return left in _collection(right)
    if operator == "contains":
        return right in _collection(left)
    raise RuleEvaluationError(f"不支持的规则运算符：{operator}")


def matches_selector(selector: Dict[str, Any], context: dict) -> bool:
    for field, expected in (selector or {}).items():
        actual = get_field(context, field)
        if isinstance(expected, list):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


_TEMPLATE_FIELD = re.compile(r"\{([a-zA-Z0-9_.-]+)\}")


def render_template(template: str, context: dict) -> str:
    def replace(match):
        value = get_field(context, match.group(1))
        return "" if value is None else str(value)

    return _TEMPLATE_FIELD.sub(replace, str(template or ""))


def evaluate_rule(rule: Dict[str, Any], context: dict) -> dict:
    matched = matches_selector(rule.get("select") or {}, context)
    count_when = evaluate_expression(rule["countWhen"], context) if rule.get("countWhen") is not None else True
    exempted = evaluate_expression(rule["exemptWhen"], context) if rule.get("exemptWhen") is not None else False
    counted = bool(matched and count_when and not exempted)
    verdict = rule.get("verdict") or {}
    return {
        "ruleKey": str(rule.get("key") or ""),
        "label": str(rule.get("label") or rule.get("key") or ""),
        "matched": matched,
        "counted": counted,
        "exempted": bool(matched and exempted),
        "points": float(verdict.get("points") or 0) if counted else 0,
        "reason": render_template(verdict.get("reason") or "", context) if matched else "",
    }
