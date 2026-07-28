import copy
import re
from typing import Any, Iterable


SUPPORTED_CONFIG_TYPES = {
    "boolean",
    "interruptGroups",
    "number",
    "playerList",
    "select",
    "text",
    "textList",
}


def validate_config_schema(schema: Iterable[dict]) -> None:
    schema = list(schema or [])
    seen = set()
    for field in schema:
        if not isinstance(field, dict):
            raise RuntimeError("Boss configSchema 中的字段必须是对象。")
        key = str(field.get("key") or "").strip()
        field_type = str(field.get("type") or "").strip()
        if not key:
            raise RuntimeError("Boss configSchema 字段缺少 key。")
        if key in seen:
            raise RuntimeError(f"Boss configSchema 存在重复字段：{key}")
        if field_type not in SUPPORTED_CONFIG_TYPES:
            raise RuntimeError(f"Boss configSchema 字段 {key} 使用了不支持的类型：{field_type}")
        if field_type == "select" and not field.get("options"):
            raise RuntimeError(f"Boss configSchema 下拉字段 {key} 缺少 options。")
        seen.add(key)
    for field in schema:
        condition = field.get("visibleWhen")
        if condition is None:
            continue
        if not isinstance(condition, dict):
            raise RuntimeError(f"Boss configSchema 字段 {field['key']} 的 visibleWhen 必须是对象。")
        parent_key = str(condition.get("field") or "").strip()
        if not parent_key:
            raise RuntimeError(f"Boss configSchema 字段 {field['key']} 的 visibleWhen 缺少 field。")
        if parent_key == field["key"]:
            raise RuntimeError(f"Boss configSchema 字段 {field['key']} 不能依赖自身。")
        if parent_key not in seen:
            raise RuntimeError(
                f"Boss configSchema 字段 {field['key']} 依赖了未知字段：{parent_key}"
            )
        if "equals" not in condition and "notEquals" not in condition:
            raise RuntimeError(
                f"Boss configSchema 字段 {field['key']} 的 visibleWhen 需要 equals 或 notEquals。"
            )


def _as_boolean(value: Any, key: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    raise ValueError(f"配置 {key} 必须是布尔值。")


def _as_number(value: Any, field: dict) -> Any:
    key = field["key"]
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"配置 {key} 必须是数值。") from error
    if field.get("integer"):
        if not number.is_integer():
            raise ValueError(f"配置 {key} 必须是整数。")
        number = int(number)
    minimum = field.get("min")
    maximum = field.get("max")
    if minimum is not None and number < float(minimum):
        raise ValueError(f"配置 {key} 不能小于 {minimum}。")
    if maximum is not None and number > float(maximum):
        raise ValueError(f"配置 {key} 不能大于 {maximum}。")
    return number


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, str):
        values = re.split(r"[\s,，、;；]+", value)
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        raise ValueError("名单配置必须是字符串或数组。")
    result = []
    seen = set()
    for item in values:
        normalized = str(item).strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _select_values(field: dict) -> set:
    values = set()
    for item in field.get("options") or []:
        value = item.get("value") if isinstance(item, dict) else item
        values.add(str(value))
    return values


def _coerce_field(field: dict, value: Any) -> Any:
    key = field["key"]
    field_type = field["type"]
    if field_type == "boolean":
        return _as_boolean(value, key)
    if field_type == "number":
        return _as_number(value, field)
    if field_type in {"playerList", "textList"}:
        try:
            return _as_list(value)
        except ValueError as error:
            raise ValueError(f"配置 {key}：{error}") from error
    if field_type == "text":
        return str(value or "").strip()
    if field_type == "select":
        normalized = str(value)
        if normalized not in _select_values(field):
            raise ValueError(f"配置 {key} 的值不在允许范围内。")
        return normalized
    if field_type == "interruptGroups":
        if not isinstance(value, dict):
            raise ValueError(f"配置 {key} 必须是分组对象。")
        group_keys = {str(group.get("key")) for group in field.get("groups") or []}
        unknown = set(value) - group_keys
        if unknown:
            raise ValueError(f"配置 {key} 包含未知分组：{', '.join(sorted(unknown))}")
        return {
            group_key: _as_list(value.get(group_key))
            for group_key in group_keys
        }
    raise ValueError(f"配置 {key} 使用了不支持的类型：{field_type}")


def resolve_analysis_options(schema: Iterable[dict], options: Any) -> dict:
    schema = list(schema or [])
    validate_config_schema(schema)
    if options is None:
        options = {}
    if not isinstance(options, dict):
        raise ValueError("分析配置 options 必须是对象。")

    fields = {field["key"]: field for field in schema}
    unknown = set(options) - set(fields)
    if unknown:
        raise ValueError(f"存在未知分析配置：{', '.join(sorted(unknown))}")

    resolved = {}
    for key, field in fields.items():
        if key in options:
            raw_value = options[key]
        elif "default" in field:
            raw_value = copy.deepcopy(field["default"])
        elif field["type"] == "boolean":
            raw_value = False
        elif field["type"] in {"playerList", "textList"}:
            raw_value = []
        elif field["type"] == "interruptGroups":
            raw_value = {}
        else:
            continue
        resolved[key] = _coerce_field(field, raw_value)
    return resolved
