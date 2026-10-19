"""Report-owned guild identity and optional team adjudication profiles."""
from copy import deepcopy

AVALON_GUILD_ID = 774422
PROFILE_SCHEMA = [{
    "key": "analysisProfile", "type": "select", "label": "分析规则",
    "default": "auto", "options": [
        {"value": "auto", "label": "按日志公会自动选择"},
        {"value": "base", "label": "基础分析"}],
    "description": "日志归属阿瓦隆时启用公会战术规则；其他公会或归属未知时使用基础分析。可手动选择仅基础分析。",
}]


def profile_schema(fields):
    return deepcopy(PROFILE_SCHEMA) + fields


def resolve_profile(guild=None, options=None):
    guild = guild or {}
    avalon = str(guild.get("id")) == str(AVALON_GUILD_ID)
    enabled = avalon and (options or {}).get("analysisProfile", "auto") != "base"
    return {"key": "avalon" if enabled else "base", "guild": guild,
            "label": "阿瓦隆专属分析" if enabled else "基础分析",
            "reason": "日志公会 ID 匹配" if enabled else
                      "已选择基础分析" if avalon else "日志未确认归属阿瓦隆"}
