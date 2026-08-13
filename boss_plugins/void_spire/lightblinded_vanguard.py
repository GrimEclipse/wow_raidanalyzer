import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import requests
except ModuleNotFoundError as exc:
    raise RuntimeError("缺少 requests 依赖，请先在当前 Python 环境执行：python -m pip install -r requirements.txt") from exc
import urllib3

from analyzer_core.concurrency import MAX_REQUEST_THREADS, request_post, run_parallel_indexed
from analyzer_core.progress import emit_progress
from analyzer_core.wcl_context import resolve_wcl_credentials
from boss_plugins.common import COMBAT_RES_SPELLS, HEALER_DISPEL_SPELLS, HEALER_SPEC_IDS, write_json_result

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


PLUGIN_CONFIG = {
    "boss": {
        "key": "lightblinded_vanguard",
        "name": "光盲先锋军",
        "keywords": ["lightblinded vanguard", "光盲先锋军"],
    },
}


def load_env_file():
    search_dirs = [Path.cwd(), Path(__file__).resolve().parents[2]]
    search_dirs.extend(Path(__file__).resolve().parents)
    seen = set()
    for directory in search_dirs:
        if directory in seen:
            continue
        seen.add(directory)
        env_path = directory / ".env"
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
        return env_path
    return None


load_env_file()

CLIENT_ID = os.getenv("WCL_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("WCL_CLIENT_SECRET", "")
WCL_BASE_URL = os.getenv("WCL_BASE_URL", "https://www.warcraftlogs.com").rstrip("/")
PROXY_URL = os.getenv("WCL_PROXY", "http://127.0.0.1:7890").strip()
PROXIES = {"http": PROXY_URL, "https": PROXY_URL} if PROXY_URL else None
CN_TZ = timezone(timedelta(hours=8))
ENABLE_DISPEL_ANALYSIS = os.getenv("LIGHTBLINDED_VANGUARD_DISPELS", "").strip().lower() in {"1", "true", "yes", "on"}
ENABLE_AOE_AVOIDABLE_FIRST_DEATHS = os.getenv("LIGHTBLINDED_VANGUARD_AOE_AVOIDABLE_FIRST_DEATHS", "1").strip().lower() not in {"0", "false", "no", "off"}
DISPEL_LOGIC_TEXT = "统计逻辑：死亡前 last3hits 疑似包含复仇者之盾；死亡前未被可躲避技能命中；阵亡人数 < 5 且治疗阵亡人数 < 2；排除战斗结束前 15 秒、软狂暴阶段和坦克已无法战复后的拉脱段；回看死亡前 8 秒内是否存在复仇者之盾实际驱散事件，并统计治疗是否完成驱散。"


SPELLS = {
    1: "近战攻击",
    1246497: "复仇者之盾",
    1246502: "复仇者之盾",
    1258514: "盲目之光",
    1258661: "光明灌注",
    1248652: "圣洁鸣钟",
    1249022: "被处决",
    1249024: "处决宣判",
    1251857: "审判",
    1251859: "正义盾击",
    1246726: "审判",
    1251812: "惩戒裁决",
    1249047: "神圣之锤",
    1276982: "神圣奉献",
    1246765: "神圣风暴",
    1272310: "神圣风暴（强化）",
    1272324: "神恩风暴",
    1246749: "神圣鸣罪",
    1249135: "践踏",
    1246745: "驱邪术",
    1248994: "处决宣判预兆",
    1246736: "惩戒审判易伤",
    1246487: "复仇者之盾预兆",
    1255739: "灼热光辉",
    1256133: "狂热层数",
    1272423: "Zealous Spirit",
    20484: "复生",
    61999: "盟友复生",
    20707: "灵魂石",
    391054: "代祷",
    4987: "清洁术",
    115450: "清创生血",
    88423: "自然之愈",
    360823: "自然平衡",
    527: "纯净术",
    77130: "净化灵魂",
    32375: "群体驱散",
    115310: "还魂术",
    89808: "烧灼魔法",
    211319: "代偿",
}

EXECUTION_SENTENCE_DAMAGE_ID = 1249024
EXECUTED_DAMAGE_ID = 1249022
MELEE_ATTACK_ID = 1
BLINDING_LIGHT_ID = 1258514
PROT_JUDGMENT_VULN_ID = 1251857
RET_JUDGMENT_VULN_ID = 1246736
TANK_STRIKE_IDS = {1251859, 1251812}
TANK_VULN_IDS = {PROT_JUDGMENT_VULN_ID, RET_JUDGMENT_VULN_ID}
MYTHIC_RAID_SIZE = 20
SOFT_ENRAGE_MS = 395_000
TANK_SPEC_IDS = {250, 581, 104, 268, 66, 73}
HOLY_PRIEST_SPEC_ID = 257
AVOIDABLE_CHEAT_DEATH_IDS = {211319}

AVOIDABLE_SPELLS = {
    "holyHammer": {"label": "神圣之锤", "ids": {1249047}},
    "holyBell": {"label": "圣洁鸣钟", "ids": {1248652}},
    "graceStorm": {"label": "神恩风暴", "ids": {1272324}},
}

AVOIDABLE_DAMAGE_IDS = {spell_id for config in AVOIDABLE_SPELLS.values() for spell_id in config["ids"]}
TANK_DEATH_IDS = {1251857, 1251859, 1246726, 1251812}
TANK_SIGNAL_DEATH_IDS = TANK_DEATH_IDS
TANK_DETAIL_DAMAGE_IDS = {1251857, 1251859, 1246726, 1251812}
TANK_DETAIL_CAST_IDS = {1251857, 1251859, 1246736, 1251812}
TANK_CAST_DAMAGE_MATCH_IDS = {1246736: 1246726}
TANK_DETAIL_DEBUFF_IDS = TANK_VULN_IDS
SPLIT_DEATH_IDS = {EXECUTION_SENTENCE_DAMAGE_ID, EXECUTED_DAMAGE_ID}
SPLIT_RELATED_DEATH_IDS = SPLIT_DEATH_IDS | {1249047}
SPLIT_DETAIL_DAMAGE_IDS = {EXECUTION_SENTENCE_DAMAGE_ID, EXECUTED_DAMAGE_ID}
SPLIT_DETAIL_DEBUFF_IDS = {1248994, EXECUTION_SENTENCE_DAMAGE_ID}
SHIELD_DETAIL_DAMAGE_IDS = {BLINDING_LIGHT_ID}
SHIELD_DETAIL_DEBUFF_IDS = {1255739}
COMBAT_RES_IDS = {20484, 61999, 20707, 391054}
AVENGER_SHIELD_CAST_ID = 1246497
AVENGER_SHIELD_DAMAGE_ID = 1246502
AVENGER_SHIELD_DEBUFF_ID = 1246502
AVENGER_SHIELD_IDS = {AVENGER_SHIELD_CAST_ID, AVENGER_SHIELD_DAMAGE_ID, AVENGER_SHIELD_DEBUFF_ID}
DISPEL_CHECK_CAST_IDS = set(HEALER_DISPEL_SPELLS) | set(COMBAT_RES_SPELLS)
SOFT_ENRAGE_BUFF_ID = 1256133
ZEALOUS_SPIRIT_ID = 1272423

ACTOR_NAME_OVERRIDES = {
    "General Amias Bellamy": "阿米尔斯·贝莱梅将军",
    "Commander Venel Lightblood": "指挥官维纳尔·光血",
    "Lightblinded Vanguard": "光盲先锋军",
}


def progress(message, indent=0):
    prefix = "  " * indent
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {prefix}{message}", flush=True)
    emit_progress(message, detail=indent > 0)


def get_token():
    credentials = resolve_wcl_credentials(CLIENT_ID, CLIENT_SECRET)
    progress(f"连接 WCL 鉴权端点：{WCL_BASE_URL}/oauth/token", 1)
    if not credentials.client_id or not credentials.client_secret:
        raise RuntimeError("请先在项目 .env 或系统环境变量中设置 WCL_CLIENT_ID 和 WCL_CLIENT_SECRET。")
    res = request_post(
        f"{WCL_BASE_URL}/oauth/token",
        data={"grant_type": "client_credentials"},
        auth=(credentials.client_id, credentials.client_secret),
        proxies=PROXIES,
        verify=False,
        timeout=30,
    )
    if res.status_code == 401:
        raise RuntimeError("WCL 鉴权失败：请确认 .env 中填写的是 API Client ID / Secret。")
    res.raise_for_status()
    return res.json()["access_token"]


def graphql(token, query, variables):
    headers = {"Authorization": f"Bearer {token}"}
    res = request_post(
        f"{WCL_BASE_URL}/api/v2/client",
        json={"query": query, "variables": variables},
        headers=headers,
        proxies=PROXIES,
        verify=False,
        timeout=90,
    )
    res.raise_for_status()
    payload = res.json()
    if payload.get("errors"):
        raise RuntimeError(json.dumps(payload["errors"], ensure_ascii=False))
    return payload["data"]["reportData"]["report"]


def fetch_report_fights(token, report_id):
    from analyzer_core.analysis_scope import filter_fights
    def query_fights(include_friendly_players=True):
        fight_fields = "id name startTime endTime kill friendlyPlayers" if include_friendly_players else "id name startTime endTime kill"
        query = """
    query($code: String!) {
      reportData {
        report(code: $code) {
          startTime
          fights { __FIGHT_FIELDS__ }
        }
      }
    }
    """.replace("__FIGHT_FIELDS__", fight_fields)
        return graphql(token, query, {"code": report_id})

    try:
        report = query_fights(include_friendly_players=True)
    except RuntimeError as error:
        if "friendlyPlayers" not in str(error):
            raise
        progress("当前 WCL fights 不支持 friendlyPlayers，分摊逃兵将使用回退成员判断", 2)
        report = query_fights(include_friendly_players=False)
    valid = []
    for fight in report["fights"]:
        name = (fight.get("name") or "").lower()
        duration = fight["endTime"] - fight["startTime"]
        if duration < 20_000:
            continue
        if any(keyword in name for keyword in PLUGIN_CONFIG["boss"]["keywords"]):
            fight["reportStartTime"] = report["startTime"]
            valid.append(fight)
    return filter_fights(report_id, valid)


def fetch_actor_maps(token, report_id):
    query = """
    query($code: String!) {
      reportData {
        report(code: $code) {
          masterData { actors { id name type petOwner } }
        }
      }
    }
    """
    report = graphql(token, query, {"code": report_id})
    actors = report["masterData"]["actors"]
    id_to_name = {actor["id"]: actor["name"] for actor in actors}
    pet_to_owner = {
        actor["id"]: actor["petOwner"]
        for actor in actors
        if actor.get("petOwner") and actor.get("petOwner") in id_to_name
    }
    actor_map = {}
    actor_type = {}
    for actor_item in actors:
        actor_id = actor_item["id"]
        owner_id = pet_to_owner.get(actor_id)
        actor_map[actor_id] = id_to_name.get(owner_id, actor_item["name"]) if owner_id else actor_item["name"]
        actor_type[actor_id] = actor_item.get("type")
    return actor_map, actor_type


def fetch_combatant_info(token, report_id, fight):
    try:
        return fetch_events_all(token, report_id, "CombatantInfo", fight)
    except Exception as error:
        progress(f"CombatantInfo 读取失败，治疗识别将使用回退逻辑：{error}", 2)
        return []


def fetch_event_page(token, report_id, data_type, fight, start_time=None, end_time=None, ability_id=None, hostility_type=None):
    ability_arg = f", $abilityID: Float" if ability_id is not None else ""
    ability_filter = ", abilityID: $abilityID" if ability_id is not None else ""
    hostility_arg = ", $hostilityType: HostilityType" if hostility_type else ""
    hostility_filter = ", hostilityType: $hostilityType" if hostility_type else ""
    query = f"""
    query($code: String!, $dataType: EventDataType!, $startTime: Float!, $endTime: Float!, $fightIDs: [Int]{ability_arg}{hostility_arg}) {{
      reportData {{
        report(code: $code) {{
          events(dataType: $dataType, startTime: $startTime, endTime: $endTime, fightIDs: $fightIDs, limit: 10000{ability_filter}{hostility_filter}) {{
            data
            nextPageTimestamp
          }}
        }}
      }}
    }}
    """
    variables = {
        "code": report_id,
        "dataType": data_type,
        "startTime": float(start_time if start_time is not None else fight["startTime"]),
        "endTime": float(end_time if end_time is not None else fight["endTime"]),
        "fightIDs": [fight["id"]],
    }
    if ability_id is not None:
        variables["abilityID"] = float(ability_id)
    if hostility_type:
        variables["hostilityType"] = hostility_type
    return graphql(token, query, variables).get("events")


def fetch_events_all(token, report_id, data_type, fight, start_time=None, end_time=None, ability_id=None, hostility_type=None):
    rows = []
    current_start = start_time if start_time is not None else fight["startTime"]
    final_end = end_time if end_time is not None else fight["endTime"]
    while current_start < final_end:
        page = fetch_event_page(token, report_id, data_type, fight, current_start, final_end, ability_id, hostility_type)
        if not page:
            progress(f"{data_type} 查询返回空页，按 0 条处理：fight={fight['id']} ability={ability_id or 'ALL'}", 3)
            break
        rows.extend(page.get("data") or [])
        next_page = page.get("nextPageTimestamp")
        if not next_page or next_page <= current_start:
            break
        current_start = next_page
    return rows


def ability_id(event):
    return event.get("abilityGameID") or event.get("killingAbilityGameID") or event.get("extraAbilityGameID")


def extra_ability_id(event):
    return event.get("extraAbilityGameID")


def ability_name(event):
    aid = ability_id(event)
    return event.get("abilityName") or event.get("name") or SPELLS.get(aid, str(aid or "未知"))


def tank_ability_name(event):
    aid = ability_id(event)
    if aid in TANK_VULN_IDS:
        return "审判"
    return ability_name(event)


def event_amount(event):
    return int(event.get("amount") or 0) + int(event.get("absorbed") or 0)


def is_environment_actor_name(name):
    return name in {"Environment", "环境", "未知(None)", "未知(0)"}


def is_environment_actor(actor_map, actor_id):
    return actor_id in {None, 0} or is_environment_actor_name(actor(actor_map, actor_id))


def event_key(event):
    return (
        event.get("timestamp", 0),
        event.get("sourceID"),
        event.get("targetID"),
        ability_id(event),
        event_amount(event),
    )


def actor(actor_map, actor_id):
    name = actor_map.get(actor_id, f"未知({actor_id})")
    return ACTOR_NAME_OVERRIDES.get(name, name)


def fight_elapsed(event, fight):
    return int(event.get("timestamp", 0) - fight["startTime"])


def format_time(ms):
    return str(timedelta(seconds=max(0, int(ms)) // 1000))[2:7]


def event_source_id(event):
    return event.get("sourceID") or event.get("targetID")


def event_target_id(event):
    return event.get("targetID")


def combatant_spec_id(event):
    for key in ("specID", "specId", "spec", "specializationID", "specializationId"):
        value = event.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def infer_healer_player_ids(combatant_info, casts):
    healer_ids = set()
    for event in combatant_info:
        spec_id = combatant_spec_id(event)
        source_id = event_source_id(event)
        if source_id and spec_id in HEALER_SPEC_IDS:
            healer_ids.add(source_id)
    if healer_ids:
        return healer_ids
    for event in casts:
        if ability_id(event) in DISPEL_CHECK_CAST_IDS and event.get("sourceID"):
            healer_ids.add(event.get("sourceID"))
    return healer_ids


def build_player_roles(combatant_info, tank_player_ids=None):
    roles = {}
    for event in combatant_info:
        source_id = event_source_id(event)
        spec_id = combatant_spec_id(event)
        if not source_id:
            continue
        if spec_id in TANK_SPEC_IDS:
            roles[source_id] = "tank"
        elif spec_id in HEALER_SPEC_IDS:
            roles[source_id] = "healer"
        else:
            roles.setdefault(source_id, "dps")
    for player_id in tank_player_ids or set():
        if player_id and player_id not in roles:
            roles[player_id] = "tank"
    return roles


def build_player_specs(combatant_info):
    specs = {}
    for event in combatant_info:
        source_id = event_source_id(event)
        spec_id = combatant_spec_id(event)
        if source_id and spec_id:
            specs[source_id] = spec_id
    return specs


def get_local_datetime(absolute_ms):
    return datetime.fromtimestamp(absolute_ms / 1000.0, CN_TZ)


def raid_night_date_str(local_dt):
    from analyzer_core.wcl_paths import to_raid_night_date
    return to_raid_night_date(local_dt).isoformat()


def deep_link(report_id, fight_id, view_type, event_time, before_ms=15_000, after_ms=2_000):
    return (
        f"{WCL_BASE_URL}/reports/{report_id}#fight={fight_id}&type={view_type}"
        f"&start={event_time - before_ms}&end={event_time + after_ms}"
    )


def fight_type_link(report_id, fight_id, view_type):
    return f"{WCL_BASE_URL}/reports/{report_id}?fight={fight_id}&type={view_type}"


def deaths_link(report_id, fight_id):
    return fight_type_link(report_id, fight_id, "deaths")


def dispels_link(report_id, fight_id):
    return fight_type_link(report_id, fight_id, "dispels")


def replay_link(report_id, fight_id, position_ms):
    return f"{WCL_BASE_URL}/reports/{report_id}?fight={fight_id}&view=replay&position={max(0, int(position_ms))}"


def cluster_events(events, window_ms=3_000):
    clusters = []
    for event in sorted(events, key=lambda item: item.get("timestamp", 0)):
        if not clusters or event.get("timestamp", 0) - clusters[-1]["end"] > window_ms:
            clusters.append({"start": event.get("timestamp", 0), "end": event.get("timestamp", 0), "events": [event]})
        else:
            clusters[-1]["end"] = event.get("timestamp", 0)
            clusters[-1]["events"].append(event)
    return clusters


def deaths_before(deaths, timestamp):
    return [death for death in deaths if death.get("timestamp", 0) <= timestamp]


def compensation_for_damage_event(damage_event, compensation_events):
    target_id = damage_event.get("targetID")
    timestamp = damage_event.get("timestamp", 0)
    candidates = [
        event for event in compensation_events
        if event.get("targetID") == target_id
        and event_is_apply(event)
        and -250 <= event.get("timestamp", 0) - timestamp <= 2_500
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda event: abs(event.get("timestamp", 0) - timestamp))


def empty_avoidable_row(name, spell_key, spell_name, role="unknown"):
    roles = [] if role in {None, "", "unknown"} else [role]
    return {
        "name": name,
        "role": role,
        "roles": roles,
        "spellKey": spell_key,
        "spellName": spell_name,
        "totalDamage": 0,
        "hitCount": 0,
        "deathCount": 0,
        "deathCompensationCount": 0,
    }


def sort_avoidable_rows(rows):
    return sorted(rows, key=lambda item: item.get("totalDamage", 0), reverse=True)


def merge_roles(existing_roles, new_roles):
    order = {"tank": 0, "healer": 1, "dps": 2, "unknown": 3}
    roles = {role for role in (existing_roles or []) + (new_roles or []) if role and role != "unknown"}
    return sorted(roles, key=lambda role: order.get(role, 99))


def build_avoidable_rows(actor_map, damage_events, deaths, player_roles=None, player_specs=None, compensation_events=None):
    player_roles = player_roles or {}
    player_specs = player_specs or {}
    compensation_events = compensation_events or []
    local = {key: {} for key in AVOIDABLE_SPELLS}
    seen_compensations = set()
    for event in damage_events:
        aid = ability_id(event)
        target_id = event.get("targetID")
        target = actor(actor_map, target_id)
        for key, config in AVOIDABLE_SPELLS.items():
            if aid not in config["ids"]:
                continue
            row = local[key].setdefault(target, empty_avoidable_row(target, key, config["label"], player_roles.get(target_id, "unknown")))
            row["totalDamage"] += event_amount(event)
            row["hitCount"] += 1
            compensation = compensation_for_damage_event(event, compensation_events) if player_specs.get(target_id) == HOLY_PRIEST_SPEC_ID else None
            if compensation:
                compensation_key = (key, target_id, ability_id(compensation), compensation.get("timestamp", 0))
                if compensation_key not in seen_compensations:
                    seen_compensations.add(compensation_key)
                    row["deathCompensationCount"] += 1
    for death in deaths:
        death_id = death.get("killingAbilityGameID")
        target_id = death.get("targetID")
        target = actor(actor_map, target_id)
        for key, config in AVOIDABLE_SPELLS.items():
            if death_id not in config["ids"]:
                continue
            row = local[key].setdefault(target, empty_avoidable_row(target, key, config["label"], player_roles.get(target_id, "unknown")))
            row["deathCount"] += 1
    return {key: sort_avoidable_rows(rows.values()) for key, rows in local.items()}


def merge_avoidable(global_board, local_board):
    for key, rows in local_board.items():
        bucket = global_board.setdefault(key, {})
        for row in rows:
            target = row["name"]
            merged = bucket.setdefault(
                target,
                {
                    "name": target,
                    "spellKey": key,
                    "spellName": row["spellName"],
                    "role": row.get("role", "unknown"),
                    "roles": row.get("roles") or ([] if row.get("role") in {None, "", "unknown"} else [row.get("role")]),
                    "totalDamage": 0,
                    "hitCount": 0,
                    "deathCount": 0,
                    "deathCompensationCount": 0,
                },
            )
            merged["roles"] = merge_roles(merged.get("roles"), row.get("roles") or ([] if row.get("role") in {None, "", "unknown"} else [row.get("role")]))
            merged["role"] = merged["roles"][0] if merged["roles"] else (row.get("role") or merged.get("role") or "unknown")
            merged["totalDamage"] += row.get("totalDamage", 0)
            merged["hitCount"] += row.get("hitCount", 0)
            merged["deathCount"] += row.get("deathCount", 0)
            merged["deathCompensationCount"] += row.get("deathCompensationCount", 0)


def recent_events_for_player(events, player_id, timestamp, before_ms=12_000):
    return [
        event for event in events
        if event.get("targetID") == player_id and timestamp - before_ms <= event.get("timestamp", 0) <= timestamp + 500
    ]


def event_is_apply(event):
    return str(event.get("type", "")).lower() in {"applybuff", "applydebuff", "refreshbuff", "refreshdebuff"}


def healer_is_alive(healer_id, timestamp, deaths, res_events):
    last_death = max(
        (death.get("timestamp", 0) for death in deaths if death.get("targetID") == healer_id and death.get("timestamp", 0) <= timestamp),
        default=None,
    )
    if last_death is None:
        return True
    return any(
        event.get("targetID") == healer_id and last_death < event.get("timestamp", 0) <= timestamp
        for event in res_events
    )


def healer_deaths_before(deaths, healer_ids, timestamp):
    return {
        death.get("targetID")
        for death in deaths
        if death.get("targetID") in healer_ids and death.get("timestamp", 0) <= timestamp
    }


def recent_shield_damage_for_death(death, shield_damage_events):
    timestamp = death.get("timestamp", 0)
    target_id = death.get("targetID")
    candidates = [
        event for event in shield_damage_events
        if event.get("targetID") == target_id and 0 <= timestamp - event.get("timestamp", 0) <= 8_500
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda event: event.get("timestamp", 0))


def shield_debuff_start_for_death(death, shield_debuffs, fallback_event):
    target_id = death.get("targetID")
    death_ts = death.get("timestamp", 0)
    candidates = [
        event for event in shield_debuffs
        if event.get("targetID") == target_id
        and event_is_apply(event)
        and 0 <= death_ts - event.get("timestamp", 0) <= 12_000
    ]
    if candidates:
        return max(candidates, key=lambda event: event.get("timestamp", 0))
    return fallback_event


def casts_in_window(casts, source_id, start_ts, end_ts):
    return [
        event for event in casts
        if event.get("sourceID") == source_id
        and start_ts <= event.get("timestamp", 0) <= end_ts
    ]


def avenger_shield_dispels_in_window(dispels, start_ts, end_ts, target_id=None, source_id=None):
    return [
        event for event in dispels
        if start_ts <= event.get("timestamp", 0) <= end_ts
        and extra_ability_id(event) == AVENGER_SHIELD_DEBUFF_ID
        and (target_id is None or event.get("targetID") == target_id)
        and (source_id is None or event.get("sourceID") == source_id)
    ]


def soft_enrage_start_timestamp(fight, soft_enrage_buffs):
    if fight["endTime"] - fight["startTime"] > SOFT_ENRAGE_MS:
        return fight["startTime"] + SOFT_ENRAGE_MS
    return None


def max_soft_enrage_stack(soft_enrage_buffs):
    stack_events = [event for event in soft_enrage_buffs if ability_id(event) == SOFT_ENRAGE_BUFF_ID]
    if not stack_events:
        return 0, None
    def event_stack(event):
        return int(event.get("stack") or event.get("stacks") or 0)
    best = max(stack_events, key=lambda event: (event_stack(event), event.get("timestamp", 0)))
    return event_stack(best), best


def soft_enrage_stack_at_timestamp(soft_enrage_buffs, timestamp):
    stack_events = [
        event for event in soft_enrage_buffs
        if ability_id(event) == SOFT_ENRAGE_BUFF_ID and event.get("timestamp", 0) <= timestamp
    ]
    if not stack_events:
        stack_events = [
            event for event in soft_enrage_buffs
            if ability_id(event) == SOFT_ENRAGE_BUFF_ID and 0 <= event.get("timestamp", 0) - timestamp <= 3_000
        ]
    if not stack_events:
        return 0, None
    def event_stack(event):
        return int(event.get("stack") or event.get("stacks") or 0)
    best = max(stack_events, key=lambda event: event.get("timestamp", 0))
    return event_stack(best), best


def soft_enrage_evidence(fight, actor_map, soft_enrage_buffs):
    start_ts = soft_enrage_start_timestamp(fight, soft_enrage_buffs)
    stack, stack_event = max_soft_enrage_stack(soft_enrage_buffs)
    stack_at_start, stack_at_start_event = soft_enrage_stack_at_timestamp(soft_enrage_buffs, start_ts) if start_ts else (0, None)
    zealous_events = [
        event for event in soft_enrage_buffs
        if ability_id(event) == ZEALOUS_SPIRIT_ID and event_is_apply(event)
    ]
    first_zealous = min(zealous_events, key=lambda event: event.get("timestamp", 0), default=None)
    return {
        "triggered": bool(start_ts),
        "startTime": format_time(start_ts - fight["startTime"]) if start_ts else None,
        "startTimestamp": start_ts,
        "stack": stack,
        "stackTime": format_time(fight_elapsed(stack_event, fight)) if stack_event else None,
        "stackTarget": actor(actor_map, stack_event.get("targetID")) if stack_event else None,
        "stackAtStart": stack_at_start,
        "stackAtStartTime": format_time(fight_elapsed(stack_at_start_event, fight)) if stack_at_start_event else None,
        "zealousTime": format_time(fight_elapsed(first_zealous, fight)) if first_zealous else None,
    }


def analyze_dispel_failures(deaths, avoidable_damage_events, shield_damage_events, shield_debuffs, dispel_casts, dispel_events, res_events, combatant_info, actor_map, fight, soft_enrage_start=None, suppress_after_timestamp=None):
    healer_ids = infer_healer_player_ids(combatant_info, dispel_casts)
    if not healer_ids:
        return []
    avoidable_death_ids = {death.get("targetID") for death in deaths if death.get("killingAbilityGameID") in AVOIDABLE_DAMAGE_IDS}
    rows = []
    for death in deaths:
        death_ts = death.get("timestamp", 0)
        if soft_enrage_start and death_ts >= soft_enrage_start:
            continue
        if suppress_after_timestamp and death_ts >= suppress_after_timestamp:
            continue
        if fight["endTime"] - death_ts < 15_000:
            continue
        if death.get("killingAbilityGameID") in SPLIT_RELATED_DEATH_IDS | TANK_SIGNAL_DEATH_IDS | {BLINDING_LIGHT_ID}:
            continue
        if len(deaths_before(deaths, death_ts)) >= 5:
            continue
        if len(healer_deaths_before(deaths, healer_ids, death_ts)) >= 2:
            continue
        if death.get("targetID") in avoidable_death_ids or death.get("killingAbilityGameID") in AVOIDABLE_DAMAGE_IDS:
            continue
        if any(
            event.get("targetID") == death.get("targetID") and 0 <= death_ts - event.get("timestamp", 0) <= 8_000
            for event in avoidable_damage_events
        ):
            continue
        shield_hit = recent_shield_damage_for_death(death, shield_damage_events)
        if not shield_hit:
            continue
        debuff_start = shield_debuff_start_for_death(death, shield_debuffs, shield_hit)
        start_ts = max(fight["startTime"], death_ts - 8_000)
        end_ts = death_ts
        successful_target_dispels = avenger_shield_dispels_in_window(dispel_events, start_ts, end_ts, target_id=death.get("targetID"))
        if successful_target_dispels:
            continue
        healer_rows = []
        used_any = False
        for healer_id in sorted(healer_ids, key=lambda item: actor(actor_map, item)):
            healer_name = actor(actor_map, healer_id)
            used = avenger_shield_dispels_in_window(dispel_events, start_ts, end_ts, source_id=healer_id)
            if not used:
                used = [
                    event for event in casts_in_window(dispel_casts, healer_id, start_ts, end_ts)
                    if ability_id(event) in HEALER_DISPEL_SPELLS
                ]
            if used:
                used_any = True
                spells = "、".join(dict.fromkeys(ability_name(event) for event in used))
                healer_rows.append({
                    "name": healer_name,
                    "status": "used",
                    "spellName": spells,
                    "text": f"{healer_name}（已使用 {spells}）",
                })
            elif not healer_is_alive(healer_id, end_ts, deaths, res_events):
                healer_rows.append({
                    "name": healer_name,
                    "status": "dead",
                    "text": f"{healer_name}（已阵亡）",
                })
            else:
                healer_rows.append({
                    "name": healer_name,
                    "status": "missing",
                    "text": f"{healer_name}（未使用）",
                })
        if not any(row["status"] == "missing" for row in healer_rows):
            continue
        rows.append({
            "time": format_time(fight_elapsed(death, fight)),
            "player": actor(actor_map, death.get("targetID")),
            "ability": SPELLS.get(death.get("killingAbilityGameID"), str(death.get("killingAbilityGameID"))),
            "shieldTime": format_time(fight_elapsed(shield_hit, fight)),
            "windowStart": format_time(start_ts - fight["startTime"]),
            "windowEnd": format_time(end_ts - fight["startTime"]),
            "usedAny": used_any,
            "healers": healer_rows,
            "text": f"{actor(actor_map, death.get('targetID'))} 死亡前 last3hits 疑似包含复仇者之盾，检查 {format_time(start_ts - fight['startTime'])}-{format_time(end_ts - fight['startTime'])} 治疗驱散窗口",
        })
    return rows


def infer_tank_player_ids(damage_events):
    scores = defaultdict(lambda: {"hitCount": 0, "totalDamage": 0, "firstHit": 10**18})
    for event in damage_events:
        if ability_id(event) not in TANK_DETAIL_DAMAGE_IDS:
            continue
        target_id = event.get("targetID")
        if not target_id:
            continue
        row = scores[target_id]
        row["hitCount"] += 1
        row["totalDamage"] += event_amount(event)
        row["firstHit"] = min(row["firstHit"], event.get("timestamp", 0))
    ranked = sorted(
        scores.items(),
        key=lambda item: (-item[1]["hitCount"], item[1]["firstHit"], -item[1]["totalDamage"]),
    )
    stable = [player_id for player_id, row in ranked if row["hitCount"] >= 2]
    if len(stable) >= 2:
        return set(stable[:2])
    return {player_id for player_id, _ in ranked[:2]}


def tank_death_evidence(deaths, damage_events, cast_events, actor_map, fight, tank_player_ids):
    candidate_deaths = [
        death for death in deaths
        if death.get("killingAbilityGameID") in TANK_SIGNAL_DEATH_IDS
        and death.get("targetID") in tank_player_ids
    ]
    if not candidate_deaths:
        return []
    tank_related_damage = [event for event in damage_events if ability_id(event) in TANK_DEATH_IDS]
    tank_related_casts = [event for event in cast_events if ability_id(event) in TANK_DETAIL_CAST_IDS]
    first_death_ts = min(death.get("timestamp", 0) for death in candidate_deaths)
    last_death_ts = max(death.get("timestamp", 0) for death in candidate_deaths)
    related_casts = [
        event for event in tank_related_casts
        if first_death_ts - 25_000 <= event.get("timestamp", 0) <= last_death_ts + 500
    ]
    related_damage = [
        event for event in tank_related_damage
        if first_death_ts - 25_000 <= event.get("timestamp", 0) <= last_death_ts + 500
    ]
    related_casts = sorted(related_casts, key=lambda item: item.get("timestamp", 0))
    related_damage = sorted(related_damage, key=lambda item: item.get("timestamp", 0))
    events = []
    seen = set()
    matched_damage_keys = set()

    def nearest_damage_for_cast(cast_event):
        aid = ability_id(cast_event)
        damage_aid = TANK_CAST_DAMAGE_MATCH_IDS.get(aid, aid)
        source_id = cast_event.get("sourceID")
        target_id = cast_event.get("targetID")
        target_is_environment = is_environment_actor(actor_map, target_id)
        candidates = []
        for damage in related_damage:
            if ability_id(damage) != damage_aid:
                continue
            if source_id is not None and damage.get("sourceID") != source_id:
                continue
            if target_id is not None and not target_is_environment and damage.get("targetID") != target_id:
                continue
            if abs(damage.get("timestamp", 0) - cast_event.get("timestamp", 0)) <= 2_000:
                candidates.append(damage)
        if not candidates:
            return None
        return min(candidates, key=lambda damage: abs(damage.get("timestamp", 0) - cast_event.get("timestamp", 0)))

    def append_tank_event(event, matched_damage=None):
        aid = ability_id(event)
        source_id = event.get("sourceID") if event.get("sourceID") is not None else (matched_damage or {}).get("sourceID")
        target_id = event.get("targetID")
        if is_environment_actor(actor_map, target_id):
            target_id = (matched_damage or {}).get("targetID")
        if is_environment_actor(actor_map, target_id):
            return
        timestamp = event.get("timestamp", 0)
        if matched_damage and (not target_id or abs(matched_damage.get("timestamp", 0) - timestamp) <= 500):
            timestamp = matched_damage.get("timestamp", timestamp)
        key = (timestamp // 1000, source_id, target_id, aid)
        if key in seen:
            return
        seen.add(key)
        source = actor(actor_map, source_id)
        target = actor(actor_map, target_id)
        ability = tank_ability_name(event)
        amount = event_amount(matched_damage) if matched_damage else 0
        amount_text = f"（{amount:,}）" if aid in TANK_STRIKE_IDS and amount else ""
        if matched_damage:
            matched_damage_keys.add(event_key(matched_damage))
        events.append({
            "time": format_time(timestamp - fight["startTime"]),
            "absoluteTime": timestamp,
            "source": source,
            "target": target,
            "sourceID": source_id,
            "targetID": target_id,
            "ability": ability,
            "abilityID": aid,
            "amount": amount,
            "kind": "tank_evidence",
            "text": f"{source} 对 {target} 使用了{ability}{amount_text}",
        })

    for event in related_casts:
        append_tank_event(event, nearest_damage_for_cast(event))
    for damage in related_damage:
        if event_key(damage) in matched_damage_keys:
            continue
        append_tank_event(damage, damage)

    events = sorted(events, key=lambda item: item.get("absoluteTime", 0))[-12:]
    death_lines = []
    for death in sorted(candidate_deaths, key=lambda item: item.get("timestamp", 0)):
        death_ability = SPELLS.get(death.get("killingAbilityGameID"), str(death.get("killingAbilityGameID")))
        death_lines.append({
            "time": format_time(fight_elapsed(death, fight)),
            "absoluteTime": death.get("timestamp", 0),
            "player": actor(actor_map, death.get("targetID")),
            "ability": death_ability,
            "text": f"{actor(actor_map, death.get('targetID'))} 死于 {death_ability}",
        })
    return [{
        "time": format_time(first_death_ts - fight["startTime"]),
        "player": "、".join(unique_names(line["player"] for line in death_lines)),
        "deathAbility": "、".join(line["ability"] for line in death_lines),
        "deathLine": "；".join(line["text"] for line in death_lines),
        "deathLines": death_lines,
        "deathCount": len(death_lines),
        "events": events,
    }]


def infer_tank_players(damage_events, actor_map):
    tank_ids = infer_tank_player_ids(damage_events)
    return [actor(actor_map, player_id) for player_id in sorted(tank_ids, key=lambda item: actor(actor_map, item))]


def format_combat_res_events(res_events, actor_map, fight):
    rows = []
    seen = set()
    for event in sorted(res_events, key=lambda item: item.get("timestamp", 0)):
        source = actor(actor_map, event.get("sourceID"))
        target = actor(actor_map, event.get("targetID"))
        if target in {"Environment", "环境", "未知(None)"}:
            continue
        ability = ability_name(event)
        dedupe_key = (event.get("timestamp", 0) // 2_000, source, target, ability)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        rows.append({
            "time": format_time(fight_elapsed(event, fight)),
            "source": source,
            "target": target,
            "ability": ability,
            "abilityID": ability_id(event),
            "text": f"{source} 对 {target} 使用了{ability}",
            "timestamp": event.get("timestamp", 0),
            "targetID": event.get("targetID"),
        })
    return rows


def combat_res_after_death(tank_death, res_rows):
    death_time = tank_death.get("timestamp", 0)
    target_id = tank_death.get("targetID")
    return [
        row for row in res_rows
        if row.get("timestamp", 0) >= death_time and (not row.get("targetID") or row.get("targetID") == target_id)
    ]


def combat_res_before_timestamp(timestamp, res_rows):
    return [row for row in res_rows if row.get("timestamp", 0) < timestamp]


def combat_res_for_tank_deaths(tank_deaths, res_rows):
    tank_ids = {death.get("targetID") for death in tank_deaths}
    first_death = min((death.get("timestamp", 0) for death in tank_deaths), default=0)
    last_death = max((death.get("timestamp", 0) for death in tank_deaths), default=0)
    return [
        row for row in res_rows
        if row.get("targetID") in tank_ids and first_death <= row.get("timestamp", 0) <= last_death
    ]


def tank_unrecoverable_timestamp(tank_deaths, res_rows):
    if not tank_deaths:
        return None
    ordered = sorted(tank_deaths, key=lambda item: item.get("timestamp", 0))
    first_tank_death = ordered[0]
    tank_rescues = combat_res_for_tank_deaths(ordered, res_rows)
    unique_tank_death_ids = {death.get("targetID") for death in ordered}
    if len(unique_tank_death_ids) >= 2 and len(tank_rescues) < len(ordered):
        return first_tank_death.get("timestamp", 0)
    if combat_res_before_timestamp(first_tank_death.get("timestamp", 0), res_rows) and not combat_res_after_death(first_tank_death, res_rows):
        return first_tank_death.get("timestamp", 0)
    return None


def unique_names(names):
    seen = set()
    result = []
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        result.append(name)
    return result


def role_text(role):
    return {"tank": "坦克", "healer": "治疗", "dps": "伤害输出"}.get(role or "unknown", "未知")


def early_death_offender_rows(deaths, actor_map, player_roles, fight, limit=4):
    rows = []
    for death in sorted(deaths, key=lambda item: item.get("timestamp", 0))[:limit]:
        role = player_roles.get(death.get("targetID"), "unknown")
        ability = SPELLS.get(death.get("killingAbilityGameID"), str(death.get("killingAbilityGameID")))
        player = actor(actor_map, death.get("targetID"))
        rows.append({
            "time": format_time(fight_elapsed(death, fight)),
            "player": player,
            "role": role,
            "roleText": role_text(role),
            "ability": ability,
            "abilityID": death.get("killingAbilityGameID"),
            "text": f"{player} 死于 {ability}",
        })
    return rows


def avoidable_first_death_rows(deaths, actor_map, player_roles, fight, limit=4):
    rows = []
    for death in sorted(deaths, key=lambda item: item.get("timestamp", 0)):
        ability_id_value = death.get("killingAbilityGameID")
        if ability_id_value not in AVOIDABLE_DAMAGE_IDS:
            continue
        role = player_roles.get(death.get("targetID"), "unknown")
        ability = SPELLS.get(ability_id_value, str(ability_id_value))
        player = actor(actor_map, death.get("targetID"))
        rows.append({
            "time": format_time(fight_elapsed(death, fight)),
            "timestamp": death.get("timestamp", 0),
            "player": player,
            "role": role,
            "roles": [] if role in {None, "", "unknown"} else [role],
            "roleText": role_text(role),
            "ability": ability,
            "abilityID": ability_id_value,
            "text": f"{player} 死于 {ability}",
        })
        if len(rows) >= limit:
            break
    return rows


def split_death_clusters_from_deaths(deaths):
    execution_deaths = [death for death in deaths if death.get("killingAbilityGameID") in SPLIT_RELATED_DEATH_IDS]
    return [
        cluster
        for cluster in cluster_events(execution_deaths, window_ms=10_000)
        if len(cluster["events"]) >= 2 and any(event.get("killingAbilityGameID") in SPLIT_DEATH_IDS for event in cluster["events"])
    ]


def split_clusters(deaths, execution_damage):
    return split_death_clusters_from_deaths(deaths), cluster_events(execution_damage, window_ms=2_000)


def death_ability_ids(deaths):
    return {death.get("killingAbilityGameID") for death in deaths if death.get("killingAbilityGameID")}


def split_issue_summary(cluster, fight):
    if not cluster:
        return ""
    count = len(cluster["events"])
    time = format_time(cluster["start"] - fight["startTime"])
    return f"{time} 附近处决宣判 / 被处决 / 神圣之锤造成 {count} 人死亡"


def split_replay_link(report_id, fight, cluster):
    if not cluster:
        return ""
    return replay_link(report_id, fight["id"], fight_elapsed(cluster["events"][0], fight) - 5_000)


def is_likely_reset(deaths):
    return 0 < len(deaths) < MYTHIC_RAID_SIZE


def first_event_timestamp(events):
    if not events:
        return None
    return min(event.get("timestamp", 0) for event in events)


def has_avoidable_before_tank(deaths):
    tank_deaths = [death for death in deaths if death.get("killingAbilityGameID") in TANK_SIGNAL_DEATH_IDS]
    if not tank_deaths:
        return False
    first_tank_ts = first_event_timestamp(tank_deaths)
    return any(
        death.get("killingAbilityGameID") in AVOIDABLE_DAMAGE_IDS and death.get("timestamp", 0) < first_tank_ts
        for death in deaths
    )


def classify_fight_from_deaths(fight, deaths):
    if fight.get("kill"):
        return {"key": "kill", "label": "已击杀"}
    if not deaths:
        return {"key": "reset_no_deaths", "label": "无死亡记录 / 团队拉脱"}

    death_ids = death_ability_ids(deaths)
    split_death_clusters = split_death_clusters_from_deaths(deaths)
    split_ts = first_event_timestamp(split_death_clusters[0]["events"]) if split_death_clusters else None
    tank_deaths = [death for death in deaths if death.get("killingAbilityGameID") in TANK_SIGNAL_DEATH_IDS]
    tank_after_split = bool(split_ts and any(death.get("timestamp", 0) > split_ts for death in tank_deaths))
    if split_death_clusters and tank_after_split:
        return {"key": "tank_swap_with_split", "label": "分摊出问题后倒T"}
    if has_avoidable_before_tank(deaths) and is_likely_reset(deaths):
        return {"key": "avoidable_into_tank", "label": "前置可躲避减员后倒T / 拉脱"}
    if tank_deaths and (len(deaths) < 5 or death_ids & TANK_DEATH_IDS):
        return {"key": "tank_swap", "label": "死亡技能指向换嘲 / 倒T"}
    if split_death_clusters:
        return {"key": "split_reset" if is_likely_reset(deaths) else "split_collapse", "label": "处决宣判 / 被处决集中阵亡"}
    if len(deaths) <= 4 and any(death.get("killingAbilityGameID") == BLINDING_LIGHT_ID for death in deaths):
        return {"key": "shield_failed", "label": "盲目之光减员"}
    if is_likely_reset(deaths):
        return {"key": "reset_after_deaths", "label": "减员后团队拉脱"}
    if len(deaths) >= 4:
        return {"key": "aoe_collapse", "label": "团队减员过多 / AoE 崩溃"}
    return {"key": "unknown", "label": "死亡技能未命中明确规则"}


def fight_player_ids(fight, actor_type):
    ids = fight.get("friendlyPlayers") or []
    if ids:
        return {int(actor_id) for actor_id in ids}
    return {actor_id for actor_id, kind in actor_type.items() if kind == "Player"}


def split_deserters(deaths, damage_clusters, actor_map, actor_type, fight):
    player_ids = fight_player_ids(fight, actor_type)
    rows_by_player = defaultdict(lambda: {"name": "", "missCount": 0, "events": []})
    for cluster in damage_clusters:
        timestamp = cluster["start"]
        if len(deaths_before(deaths, timestamp)) > 5:
            continue
        if fight["endTime"] - timestamp < 20_000:
            continue
        hit_ids = {event.get("targetID") for event in cluster["events"]}
        dead_ids = {death.get("targetID") for death in deaths_before(deaths, timestamp)}
        alive_ids = player_ids - dead_ids
        missing_ids = sorted(alive_ids - hit_ids, key=lambda item: actor(actor_map, item))
        if not missing_ids:
            continue
        for player_id in missing_ids:
            name = actor(actor_map, player_id)
            row = rows_by_player[player_id]
            row["name"] = name
            row["missCount"] += 1
            row["events"].append({
                "time": format_time(timestamp - fight["startTime"]),
                "hitCount": len(hit_ids),
                "missingCount": len(missing_ids),
            })
    return sorted(rows_by_player.values(), key=lambda item: item["missCount"], reverse=True)


def analyze_fight(
    report_id,
    fight,
    actor_map,
    actor_type,
    deaths,
    avoidable_damage_events,
    detail_damage_events,
    detail_cast_events,
    debuffs,
    res_events,
    preliminary,
    shield_damage_events,
    shield_debuffs,
    dispel_casts,
    dispel_events,
    combatant_info,
    compensation_events,
    soft_enrage_buffs,
):
    absolute_ms = fight["reportStartTime"] + fight["startTime"]
    local_start = get_local_datetime(absolute_ms)
    duration_ms = fight["endTime"] - fight["startTime"]

    execution_damage = [event for event in detail_damage_events if ability_id(event) in SPLIT_DEATH_IDS]
    split_death_clusters, split_damage_clusters = split_clusters(deaths, execution_damage)
    split_keys = {"split_collapse", "split_reset", "tank_swap_with_split"}
    tank_keys = {"tank_swap", "tank_swap_with_split", "avoidable_into_tank", "tank_no_bres", "aoe_after_tank_res", "aoe_before_tank"}
    player_specs = build_player_specs(combatant_info)
    tank_player_ids = infer_tank_player_ids(detail_damage_events)
    tank_player_ids |= {
        death.get("targetID") for death in deaths
        if death.get("killingAbilityGameID") in TANK_SIGNAL_DEATH_IDS
        and death.get("targetID")
        and (not player_specs.get(death.get("targetID")) or player_specs.get(death.get("targetID")) in TANK_SPEC_IDS)
    }
    player_roles = build_player_roles(combatant_info, tank_player_ids)
    local_avoidable = build_avoidable_rows(actor_map, avoidable_damage_events, deaths, player_roles, player_specs, compensation_events)
    tank_players = [actor(actor_map, player_id) for player_id in sorted(tank_player_ids, key=lambda item: actor(actor_map, item))]
    res_rows = format_combat_res_events(res_events, actor_map, fight)
    soft_enrage = soft_enrage_evidence(fight, actor_map, soft_enrage_buffs)
    dispel_rows = []
    tank_deaths = [
        death for death in deaths
        if death.get("killingAbilityGameID") in TANK_SIGNAL_DEATH_IDS and death.get("targetID") in tank_player_ids
    ]
    tank_unrecoverable_at = tank_unrecoverable_timestamp(tank_deaths, res_rows)
    blind_light_deaths = [death for death in deaths if death.get("killingAbilityGameID") == BLINDING_LIGHT_ID]
    reason_key = preliminary["key"]
    if reason_key in {"tank_swap", "tank_swap_with_split", "avoidable_into_tank"} and not tank_deaths:
        reason_key = "split_reset" if split_death_clusters else ("reset_after_deaths" if is_likely_reset(deaths) else "aoe_collapse")
    if tank_deaths:
        first_tank_death = min(tank_deaths, key=lambda item: item.get("timestamp", 0))
        deaths_before_tank = deaths_before(deaths, first_tank_death.get("timestamp", 0))
        tank_res_after = combat_res_after_death(first_tank_death, res_rows)
        tank_rescues = combat_res_for_tank_deaths(tank_deaths, res_rows)
        unique_tank_death_ids = {death.get("targetID") for death in tank_deaths}
        if len(deaths_before_tank) > 4:
            reason_key = "aoe_before_tank"
        elif len(unique_tank_death_ids) >= 2 and len(tank_rescues) < len(tank_deaths):
            reason_key = "tank_no_bres"
        elif len(deaths) > 4 and tank_res_after:
            reason_key = "aoe_after_tank_res"
        elif len(deaths) > 4 and not tank_res_after and combat_res_before_timestamp(first_tank_death.get("timestamp", 0), res_rows):
            reason_key = "tank_no_bres"
    if not fight.get("kill") and soft_enrage.get("triggered"):
        soft_start = soft_enrage.get("startTimestamp") or fight["startTime"] + SOFT_ENRAGE_MS
        deaths_before_soft = deaths_before(deaths, soft_start)
        hard_reasons = {"tank_swap", "tank_swap_with_split", "avoidable_into_tank", "tank_no_bres", "aoe_after_tank_res", "aoe_before_tank"}
        if len(deaths_before_soft) > 4 and reason_key not in hard_reasons:
            reason_key = "aoe_collapse"
        elif reason_key not in hard_reasons:
            reason_key = "soft_enrage"

    deserters = split_deserters(deaths, split_damage_clusters, actor_map, actor_type, fight) if reason_key in split_keys else []
    tank_evidence = tank_death_evidence(deaths, detail_damage_events, detail_cast_events, actor_map, fight, tank_player_ids) if reason_key in tank_keys else []

    is_kill = bool(fight.get("kill"))
    wipe_reason = "团队减员过多 / AoE 崩溃"
    investigation = "本场没有命中更明确的归因规则，请查看死亡时间线。"
    wcl_link = ""

    if is_kill:
        wipe_phase = "已击杀"
        wipe_reason = "已击杀"
        investigation = f"Boss 已击杀，本场不归类为灭团。战斗结束于 {format_time(duration_ms)}，下方保留死亡和明细数据。"
        wcl_link = deaths_link(report_id, fight["id"])
    else:
        wipe_phase = "单阶段"
        if reason_key == "reset_no_deaths":
            wipe_reason = "团队拉脱 / 无死亡记录"
            investigation = "本场没有死亡事件，通常是团队主动拉脱或重开。"
            wcl_link = deaths_link(report_id, fight["id"])
        elif reason_key == "tank_swap":
            wipe_reason = "换嘲失误 / 倒T"
            names = "、".join(row["player"] for row in tank_evidence) if tank_evidence else "、".join(actor(actor_map, death.get("targetID")) for death in deaths[:2])
            investigation = f"【{names}】死亡前存在审判、正义盾击或惩戒裁决记录，优先复盘换嘲与坦克承伤。"
            wcl_link = deaths_link(report_id, fight["id"]) if deaths else ""
        elif reason_key == "tank_swap_with_split":
            split_cluster = split_death_clusters[0] if split_death_clusters else None
            split_text = split_issue_summary(split_cluster, fight)
            names = "、".join(row["player"] for row in tank_evidence) if tank_evidence else "、".join(actor(actor_map, death.get("targetID")) for death in deaths if death.get("killingAbilityGameID") in TANK_SIGNAL_DEATH_IDS)
            wipe_reason = "换嘲失误 / 倒T"
            investigation = f"最终归因指向坦克承伤或换嘲问题，【{names}】死亡前存在审判、正义盾击或惩戒裁决记录；同时 {split_text}，分摊也存在问题。"
            wcl_link = split_replay_link(report_id, fight, split_cluster) or (deaths_link(report_id, fight["id"]) if deaths else "")
        elif reason_key == "avoidable_into_tank":
            avoidable_deaths = [death for death in deaths if death.get("killingAbilityGameID") in AVOIDABLE_DAMAGE_IDS]
            names = "、".join(actor(actor_map, death.get("targetID")) for death in avoidable_deaths[:3])
            tank_names = "、".join(row["player"] for row in tank_evidence) if tank_evidence else "、".join(actor(actor_map, death.get("targetID")) for death in deaths if death.get("killingAbilityGameID") in TANK_SIGNAL_DEATH_IDS)
            wipe_reason = "前置可躲避减员后倒T / 团队拉脱"
            investigation = f"前置有玩家【{names}】死于可躲避技能，随后【{tank_names}】出现坦克相关死亡；本场未死满，倾向减员后团队拉脱。"
            wcl_link = deaths_link(report_id, fight["id"]) if deaths else ""
        elif reason_key == "tank_no_bres":
            first_tank_death = min(tank_deaths, key=lambda item: item.get("timestamp", 0)) if tank_deaths else None
            used_before = combat_res_before_timestamp(first_tank_death.get("timestamp", 0), res_rows) if first_tank_death else []
            tank_names = "、".join(actor(actor_map, death.get("targetID")) for death in tank_deaths)
            wipe_reason = "倒T / 战复资源已用"
            investigation = f"【{tank_names}】发生坦克相关死亡，且倒T前已使用 {len(used_before)} 次战复，后续未看到对坦克的战复记录，倾向战复资源不足导致倒T无法补救。"
            wcl_link = deaths_link(report_id, fight["id"]) if first_tank_death else ""
        elif reason_key in {"split_collapse", "split_reset"} and split_death_clusters:
            cluster = split_death_clusters[0]
            wipe_reason = "分摊出现问题 / 团队拉脱" if reason_key == "split_reset" else "分摊出现问题阵亡"
            suffix = "；本场未死满，倾向团队决策拉脱。" if reason_key == "split_reset" else "，判定为分摊崩盘。"
            investigation = f"{split_issue_summary(cluster, fight)}{suffix}"
            wcl_link = split_replay_link(report_id, fight, cluster)
        elif reason_key == "shield_failed" and blind_light_deaths:
            wipe_reason = "圣洁护盾没转掉"
            investigation = "当前 pull 减员少于 4 人时出现盲目之光死亡，判定圣洁护盾未及时处理。"
            wcl_link = deaths_link(report_id, fight["id"])
        elif reason_key == "reset_after_deaths":
            wipe_reason = "减员后团队拉脱"
            investigation = f"本场死亡总人数 {len(deaths)}，未达到全团阵亡规模，倾向团队在减员后主动拉脱或重开。"
            wcl_link = deaths_link(report_id, fight["id"]) if deaths else ""
        elif reason_key == "aoe_after_tank_res":
            tank_names = "、".join(actor(actor_map, death.get("targetID")) for death in tank_deaths)
            investigation = f"本场发生过坦克死亡（{tank_names}），但之后有战复记录，最终死亡总人数 {len(deaths)}，归因为团队减员过多 / AoE 崩溃。"
            wipe_reason = "团队减员过多 / AoE 崩溃"
            wcl_link = deaths_link(report_id, fight["id"]) if deaths else ""
        elif reason_key == "aoe_before_tank":
            tank_names = "、".join(actor(actor_map, death.get("targetID")) for death in tank_deaths)
            wipe_reason = "团队减员过多 / AoE 崩溃"
            investigation = f"倒T前团队已死亡超过 4 人，后续 {tank_names} 的坦克相关死亡更像崩溃结果；最终归因为团队减员过多 / AoE 崩溃。"
            wcl_link = deaths_link(report_id, fight["id"]) if deaths else ""
        elif reason_key == "aoe_collapse":
            wipe_reason = "团队减员过多 / AoE 崩溃"
            investigation = f"本场死亡总人数 {len(deaths)}，因团队减员过多 / AoE 崩溃灭团。"
            wcl_link = deaths_link(report_id, fight["id"]) if deaths else ""
        elif reason_key == "soft_enrage":
            wipe_reason = "防骑层数过高 / 软狂暴灭团"
            stack_text = f"，贝莱梅最高记录到 {soft_enrage['stack']} 层" if soft_enrage.get("stack") else ""
            zealous_text = ""
            investigation = f"战斗超过 6:35 后进入贝莱梅软狂暴检查窗口{zealous_text}{stack_text}。此阶段飞盾伤害已进入高压/软狂暴逻辑，不再归因为治疗驱散，倾向防骑层数过高、惩戒过早死亡导致软狂暴灭团。"
            wcl_link = deaths_link(report_id, fight["id"]) if deaths else ""

    if not is_kill and reason_key == "tank_no_bres":
        tank_names = "、".join(unique_names(actor(actor_map, death.get("targetID")) for death in tank_deaths))
        tank_rescues = combat_res_for_tank_deaths(tank_deaths, res_rows)
        wipe_reason = "倒T / 倒T重置"
        if tank_rescues:
            investigation = f"【{tank_names}】连续发生坦克死亡，本场只记录到 {len(tank_rescues)} 次坦克战复，无法补足双坦数量，归因为倒T / 倒T重置。"
        else:
            investigation = f"【{tank_names}】发生坦克死亡，后续没有能抢救坦克的战复记录，归因为倒T / 倒T重置。"
        wcl_link = deaths_link(report_id, fight["id"]) if deaths else ""
    elif not is_kill and reason_key == "aoe_before_tank":
        tank_names = "、".join(unique_names(actor(actor_map, death.get("targetID")) for death in tank_deaths))
        wipe_reason = "团队减员过多 / AoE 崩溃"
        investigation = f"战斗发生了倒T（{tank_names}），但倒T前已经阵亡超过 4 人，归因为团队减员过多。"
        wcl_link = deaths_link(report_id, fight["id"]) if deaths else ""
    elif not is_kill and reason_key == "soft_enrage":
        start_ts = soft_enrage.get("startTimestamp") or fight["startTime"] + SOFT_ENRAGE_MS
        prior_deaths = len(deaths_before(deaths, start_ts))
        stack_at_start = soft_enrage.get("stackAtStart") or soft_enrage.get("stack") or 0
        stack_text = f"防骑此时已叠加 {stack_at_start} 层报应" if stack_at_start else "防骑层数未能从日志中稳定读取"
        zealous_text = ""
        max_stack_text = f"本场最高记录到 {soft_enrage['stack']} 层。" if soft_enrage.get("stack") and soft_enrage.get("stack") != stack_at_start else ""
        wipe_reason = "防骑层数过高 / 软狂暴灭团"
        investigation = f"战斗超过 6:35 后进入贝莱梅软狂暴检查窗口。群体飞盾前，{stack_text}。在此前已经减员 {prior_deaths} 名玩家。{zealous_text}{max_stack_text}此阶段飞盾不再归因为治疗驱散，倾向防骑层数过高、惩戒过早死亡导致软狂暴灭团。"
        wcl_link = deaths_link(report_id, fight["id"]) if deaths else ""

    dispel_suppressed_reasons = {"tank_swap", "tank_swap_with_split", "avoidable_into_tank", "tank_no_bres"}
    if not is_kill and reason_key not in dispel_suppressed_reasons:
        dispel_rows = analyze_dispel_failures(
            deaths,
            avoidable_damage_events,
            shield_damage_events,
            shield_debuffs,
            dispel_casts,
            dispel_events,
            res_events,
            combatant_info,
            actor_map,
            fight,
            soft_enrage.get("startTimestamp"),
            tank_unrecoverable_at,
        )
        for row in dispel_rows:
            row["reportID"] = report_id
            row["fightID"] = fight["id"]
            row["fightName"] = fight.get("name")
            row["wclDispelsLink"] = dispels_link(report_id, fight["id"])

    death_timeline = [
        {
            "time": format_time(fight_elapsed(death, fight)),
            "absoluteTime": death.get("timestamp"),
            "player": actor(actor_map, death.get("targetID")),
            "role": player_roles.get(death.get("targetID"), "unknown"),
            "roleText": role_text(player_roles.get(death.get("targetID"), "unknown")),
            "abilityID": death.get("killingAbilityGameID"),
            "ability": SPELLS.get(death.get("killingAbilityGameID"), str(death.get("killingAbilityGameID"))),
            "kind": "death",
        }
        for death in deaths
    ]
    for row in tank_evidence:
        for event in row.get("events", []):
            death_timeline.append({
                "time": event.get("time"),
                "absoluteTime": event.get("absoluteTime"),
                "player": event.get("target"),
                "role": player_roles.get(event.get("targetID"), "tank"),
                "roleText": "坦克",
                "abilityID": event.get("abilityID"),
                "ability": event.get("ability"),
                "kind": "tank_evidence",
                "source": event.get("source"),
                "target": event.get("target"),
                "amount": event.get("amount"),
                "text": event.get("text"),
            })
    death_timeline = sorted(
        death_timeline,
        key=lambda item: (item.get("absoluteTime") or 0, 0 if item.get("kind") == "tank_evidence" else 1),
    )

    trial_records = []
    if split_death_clusters and reason_key in split_keys:
        trial_records.append({
            "type": "split_issue",
            "title": "处决宣判分摊问题",
            "summary": f"{len(split_death_clusters[0]['events'])} 人在同一轮分摊相关机制中死亡",
            "rows": [
                {
                    "time": format_time(death.get("timestamp", 0) - fight["startTime"]),
                    "player": actor(actor_map, death.get("targetID")),
                    "ability": SPELLS.get(death.get("killingAbilityGameID"), str(death.get("killingAbilityGameID"))),
                }
                for death in split_death_clusters[0]["events"]
            ],
        })
    if deserters:
        trial_records.append({
            "type": "split_deserters",
            "title": "处决宣判分摊逃兵",
            "summary": f"共 {sum(row['missCount'] for row in deserters)} 次未吃到分摊伤害记录",
            "rows": deserters[:20],
        })
    if tank_evidence:
        trial_records.append({
            "type": "tank_swap",
            "title": "倒T / 换嘲证据",
            "summary": f"{sum(row.get('deathCount', 1) for row in tank_evidence)} 名死亡玩家存在审判、正义盾击或惩戒裁决记录",
            "rows": tank_evidence,
        })
    if res_rows:
        trial_records.append({
            "type": "combat_res",
            "title": "战复记录",
            "summary": f"本场记录到 {len(res_rows)} 次战复施放",
            "rows": res_rows,
        })
    avoidable_first_deaths = []
    if ENABLE_AOE_AVOIDABLE_FIRST_DEATHS and reason_key in {"aoe_collapse", "aoe_after_tank_res", "aoe_before_tank"}:
        avoidable_first_deaths = avoidable_first_death_rows(deaths, actor_map, player_roles, fight)
    return {
        "reportID": report_id,
        "fightID": fight["id"],
        "fightName": fight.get("name"),
        "date": raid_night_date_str(local_start),
        "startClock": local_start.strftime("%H:%M"),
        "startDateTime": local_start.strftime("%Y-%m-%d %H:%M"),
        "duration": format_time(duration_ms),
        "fightStart": fight["startTime"],
        "fightEnd": fight["endTime"],
        "fightStatus": "kill" if is_kill else "wipe",
        "isKill": is_kill,
        "kill": is_kill,
        "fightPhase": "单阶段",
        "wipePhase": wipe_phase,
        "wipeElapsedMs": duration_ms,
        "wipeReason": wipe_reason,
        "investigation": investigation,
        "wclDeepLink": wcl_link,
        "deathTimeline": death_timeline,
        "trialRecords": trial_records,
        "avoidableSummary": local_avoidable,
        "lightblindedVanguard": {
            "splitDeathClusters": [
                {
                    "time": format_time(cluster["start"] - fight["startTime"]),
                    "deathCount": len(cluster["events"]),
                    "players": [actor(actor_map, event.get("targetID")) for event in cluster["events"]],
                }
                for cluster in split_death_clusters
            ],
            "splitDeserters": deserters,
            "tankEvidence": tank_evidence,
            "tankPlayers": tank_players,
            "combatResurrections": res_rows,
            "dispelIssues": dispel_rows,
            "avoidableFirstDeaths": avoidable_first_deaths,
            "softEnrage": soft_enrage,
        },
    }


def fetch_spell_events(token, report_id, fight, data_type, spell_ids, label, hostility_type=None):
    rows = []
    spell_ids = sorted(spell_ids)
    if not spell_ids:
        return rows

    def fetch_one(index_and_spell):
        index, spell_id = index_and_spell
        progress(f"{label} {index}/{len(spell_ids)}：{SPELLS.get(spell_id, spell_id)} ({spell_id})", 2)
        spell_rows = fetch_events_all(token, report_id, data_type, fight, ability_id=spell_id, hostility_type=hostility_type)
        return index, spell_id, spell_rows

    for _, spell_id, spell_rows in run_parallel_indexed(
        list(enumerate(spell_ids, start=1)),
        fetch_one,
        max_workers=MAX_REQUEST_THREADS,
    ):
        rows.extend(spell_rows)
        if spell_rows:
            progress(f"{SPELLS.get(spell_id, spell_id)}：{len(spell_rows)} 条", 2)
    return rows


def detail_spell_ids_for_reason(reason_key, deaths):
    damage_ids = set()
    debuff_ids = set()
    cast_ids = set()
    has_tank_death_signal = bool(death_ability_ids(deaths) & TANK_SIGNAL_DEATH_IDS)
    if reason_key in {"tank_swap", "avoidable_into_tank"}:
        damage_ids |= TANK_DETAIL_DAMAGE_IDS
        cast_ids |= TANK_DETAIL_CAST_IDS
    elif reason_key == "tank_swap_with_split":
        damage_ids |= TANK_DETAIL_DAMAGE_IDS | SPLIT_DETAIL_DAMAGE_IDS
        debuff_ids |= SPLIT_DETAIL_DEBUFF_IDS
        cast_ids |= TANK_DETAIL_CAST_IDS
    elif reason_key in {"split_collapse", "split_reset"}:
        damage_ids |= SPLIT_DETAIL_DAMAGE_IDS
        debuff_ids |= SPLIT_DETAIL_DEBUFF_IDS
    elif reason_key == "shield_failed":
        damage_ids |= SHIELD_DETAIL_DAMAGE_IDS
        debuff_ids |= SHIELD_DETAIL_DEBUFF_IDS
    elif reason_key in {"aoe_collapse", "reset_after_deaths"} and has_tank_death_signal:
        damage_ids |= TANK_DETAIL_DAMAGE_IDS
        cast_ids |= TANK_DETAIL_CAST_IDS
    return damage_ids, debuff_ids, cast_ids


def needs_dispel_check(fight, deaths):
    soft_start = fight["startTime"] + SOFT_ENRAGE_MS
    for death in deaths:
        if death.get("timestamp", 0) >= soft_start:
            continue
        if fight["endTime"] - death.get("timestamp", 0) < 15_000:
            continue
        if death.get("killingAbilityGameID") in AVOIDABLE_DAMAGE_IDS:
            continue
        if death.get("killingAbilityGameID") in SPLIT_RELATED_DEATH_IDS | TANK_SIGNAL_DEATH_IDS | {BLINDING_LIGHT_ID}:
            continue
        if len(deaths_before(deaths, death.get("timestamp", 0))) < 5:
            return True
    return False


def fetch_fight_payload(token, report_id, fight):
    progress("读取死亡事件", 2)
    deaths = fetch_events_all(token, report_id, "Deaths", fight)
    progress(f"死亡事件：{len(deaths)} 条", 2)

    preliminary = classify_fight_from_deaths(fight, deaths)
    progress(f"死亡归因初判：{preliminary['label']}", 2)

    avoidable_damage_events = fetch_spell_events(
        token,
        report_id,
        fight,
        "DamageTaken",
        AVOIDABLE_DAMAGE_IDS,
        "读取可躲避伤害",
    )

    detail_damage_ids, detail_debuff_ids, detail_cast_ids = detail_spell_ids_for_reason(preliminary["key"], deaths)
    if detail_damage_ids or detail_debuff_ids or detail_cast_ids:
        progress("按归因补充读取线索事件", 2)
    detail_damage_events = fetch_spell_events(
        token,
        report_id,
        fight,
        "DamageTaken",
        detail_damage_ids,
        "读取归因伤害线索",
    )
    debuffs = fetch_spell_events(
        token,
        report_id,
        fight,
        "Debuffs",
        detail_debuff_ids,
        "读取归因光环线索",
    )
    detail_cast_events = fetch_spell_events(
        token,
        report_id,
        fight,
        "Casts",
        detail_cast_ids,
        "读取归因施放线索",
        hostility_type="Enemies",
    )
    res_events = []
    if death_ability_ids(deaths) & TANK_SIGNAL_DEATH_IDS:
        res_events = fetch_spell_events(
            token,
            report_id,
            fight,
            "Casts",
            COMBAT_RES_IDS,
            "读取战复记录",
        )
    shield_damage_events = []
    shield_debuffs = []
    dispel_casts = []
    dispel_events = []
    combatant_info = []
    compensation_events = []
    soft_enrage_buffs = []
    if avoidable_damage_events:
        compensation_events = fetch_spell_events(
            token,
            report_id,
            fight,
            "Debuffs",
            AVOIDABLE_CHEAT_DEATH_IDS,
            "读取代偿 / 免死触发线索",
        )
    if not fight.get("kill") and fight["endTime"] - fight["startTime"] > SOFT_ENRAGE_MS:
        progress("读取 6:35 后软狂暴层数线索", 2)
        soft_enrage_buffs = fetch_spell_events(
            token,
            report_id,
            fight,
            "Buffs",
            {SOFT_ENRAGE_BUFF_ID, ZEALOUS_SPIRIT_ID},
            "读取贝莱梅软狂暴 Buff",
            hostility_type="Enemies",
        )
    if ENABLE_DISPEL_ANALYSIS and needs_dispel_check(fight, deaths):
        progress("按死亡 last3hits 补充读取飞盾 / 驱散线索", 2)
        shield_damage_events = fetch_spell_events(
            token,
            report_id,
            fight,
            "DamageTaken",
            {AVENGER_SHIELD_DAMAGE_ID},
            "读取复仇者之盾伤害线索",
        )
        shield_debuffs = fetch_spell_events(
            token,
            report_id,
            fight,
            "Debuffs",
            {AVENGER_SHIELD_DEBUFF_ID},
            "读取复仇者之盾 Debuff 线索",
        )
        dispel_casts = fetch_spell_events(
            token,
            report_id,
            fight,
            "Casts",
            DISPEL_CHECK_CAST_IDS,
            "读取治疗驱散 / 战复线索",
        )
        progress("读取实际驱散事件", 2)
        dispel_events = [
            event for event in fetch_events_all(token, report_id, "Dispels", fight)
            if extra_ability_id(event) == AVENGER_SHIELD_DEBUFF_ID
        ]
        progress(f"复仇者之盾实际驱散：{len(dispel_events)} 条", 3)
        if not res_events:
            res_events = [event for event in dispel_casts if ability_id(event) in COMBAT_RES_IDS]
    combatant_info = fetch_combatant_info(token, report_id, fight)
    return deaths, avoidable_damage_events, detail_damage_events, detail_cast_events, debuffs, res_events, preliminary, shield_damage_events, shield_debuffs, dispel_casts, dispel_events, combatant_info, compensation_events, soft_enrage_buffs


def summarize_dispel_analysis(fights):
    summary = {}
    fight_rows = []
    for fight in fights:
        rows = fight.get("lightblindedVanguard", {}).get("dispelIssues", [])
        if not rows:
            continue
        fight_rows.append({
            "reportID": fight.get("reportID"),
            "fightID": fight.get("fightID"),
            "startDateTime": fight.get("startDateTime"),
            "duration": fight.get("duration"),
            "wclDispelsLink": dispels_link(fight.get("reportID"), fight.get("fightID")),
            "issueCount": len(rows),
            "rows": rows,
        })
        for row in rows:
            for healer in row.get("healers", []):
                name = healer.get("name")
                if not name:
                    continue
                bucket = summary.setdefault(name, {"name": name, "missing": 0, "dead": 0, "used": 0, "total": 0})
                status = healer.get("status")
                if status == "missing":
                    bucket["missing"] += 1
                elif status == "dead":
                    bucket["dead"] += 1
                elif status == "used":
                    bucket["used"] += 1
                bucket["total"] += 1
    return {
        "enabled": ENABLE_DISPEL_ANALYSIS,
        "logic": DISPEL_LOGIC_TEXT,
        "summary": sorted(summary.values(), key=lambda item: (item["missing"], item["dead"], item["total"]), reverse=True),
        "fights": sorted(fight_rows, key=lambda item: (item.get("reportID") or "", item.get("fightID") or 0)),
    }


def summarize_avoidable_first_deaths(fights):
    summary = {}
    for fight in fights:
        for row in fight.get("lightblindedVanguard", {}).get("avoidableFirstDeaths", []):
            name = row.get("player")
            if not name:
                continue
            bucket = summary.setdefault(name, {
                "name": name,
                "roles": [],
                "count": 0,
                "spells": {},
                "events": [],
            })
            bucket["roles"] = merge_roles(bucket.get("roles"), row.get("roles") or ([] if row.get("role") in {None, "", "unknown"} else [row.get("role")]))
            bucket["role"] = bucket["roles"][0] if bucket["roles"] else (row.get("role") or "unknown")
            bucket["count"] += 1
            spell_name = row.get("ability") or str(row.get("abilityID") or "")
            if spell_name:
                bucket["spells"][spell_name] = bucket["spells"].get(spell_name, 0) + 1
            bucket["events"].append({
                "reportID": fight.get("reportID"),
                "fightID": fight.get("fightID"),
                "time": row.get("time"),
                "ability": row.get("ability"),
                "wclLink": fight.get("wclDeepLink"),
            })
    rows = []
    for bucket in summary.values():
        spells = sorted(bucket["spells"].items(), key=lambda item: item[1], reverse=True)
        bucket["spellSummary"] = " / ".join(f"{name}×{count}" for name, count in spells[:3])
        rows.append(bucket)
    return sorted(rows, key=lambda item: (item.get("count", 0), len(item.get("events", []))), reverse=True)


def build_aggregated_json(report_ids):
    progress(f"WCL 基础地址：{WCL_BASE_URL}", 1)
    progress(f"WCL 代理：{PROXY_URL or '未启用'}", 1)
    progress("启动光盲先锋军复盘分析")
    token = get_token()
    report_id_list = [report_id.strip() for report_id in report_ids.replace(" ", "").split(",") if report_id.strip()]
    if not report_id_list:
        raise RuntimeError("请传入至少一个 WCL 日志 ID。")

    final_output = {
        "code": 200,
        "meta": {
            "analyzedReports": report_id_list,
            "mechanicVersion": "lightblinded-vanguard-2026-07-01",
            "version": "12.0",
            "raidKey": "void_spire",
            "raidName": "虚影尖塔",
            "bossKey": "lightblinded_vanguard",
            "bossName": "光盲先锋军",
            "features": {
                "interrupts": False,
                "dispels": ENABLE_DISPEL_ANALYSIS,
                "aoeOffenders": False,
                "aoeAvoidableFirstDeaths": ENABLE_AOE_AVOIDABLE_FIRST_DEATHS,
            },
            "dispelAnalysisEnabled": ENABLE_DISPEL_ANALYSIS,
            "avoidableSpells": {key: value["label"] for key, value in AVOIDABLE_SPELLS.items()},
            "spellLabels": {str(key): value for key, value in SPELLS.items()},
            "trialRecordTypes": {
                "split_deserters": "处决宣判分摊逃兵",
                "tank_swap": "倒T / 换嘲证据",
            },
        },
        "data": {"page1_wipeAnalysis": [], "page2_avoidableBoard": {}, "page2_avoidableFirstDeathBoard": [], "page3_dispelAnalysis": {"enabled": ENABLE_DISPEL_ANALYSIS, "logic": DISPEL_LOGIC_TEXT, "summary": [], "fights": []}},
    }

    global_avoidable = {key: {} for key in AVOIDABLE_SPELLS}
    for report_id in report_id_list:
        progress(f"读取日志 {report_id}", 1)
        fights = fetch_report_fights(token, report_id)
        actor_map, actor_type = fetch_actor_maps(token, report_id)
        progress(f"匹配到 {len(fights)} 场光盲先锋军战斗", 1)

        def analyze_one_fight(index_and_fight):
            index, fight = index_and_fight
            progress(f"分析 Fight {fight['id']} ({index}/{len(fights)})", 1)
            (
                deaths,
                avoidable_damage_events,
                detail_damage_events,
                detail_cast_events,
                debuffs,
                res_events,
                preliminary,
                shield_damage_events,
                shield_debuffs,
                dispel_casts,
                dispel_events,
                combatant_info,
                compensation_events,
                soft_enrage_buffs,
            ) = fetch_fight_payload(token, report_id, fight)
            fight_result = analyze_fight(
                report_id,
                fight,
                actor_map,
                actor_type,
                deaths,
                avoidable_damage_events,
                detail_damage_events,
                detail_cast_events,
                debuffs,
                res_events,
                preliminary,
                shield_damage_events,
                shield_debuffs,
                dispel_casts,
                dispel_events,
                combatant_info,
                compensation_events,
                soft_enrage_buffs,
            )
            return index, fight_result

        def report_fight_done(completed, total, result):
            _, fight_result = result
            progress(
                f"已完成 {completed}/{total} 场光盲先锋军战斗：Fight {fight_result['fightID']}",
                1,
            )

        for _, fight_result in run_parallel_indexed(
            list(enumerate(fights, start=1)),
            analyze_one_fight,
            on_complete=report_fight_done,
        ):
            merge_avoidable(global_avoidable, fight_result["avoidableSummary"])
            final_output["data"]["page1_wipeAnalysis"].append(fight_result)

    final_output["data"]["page3_dispelAnalysis"] = summarize_dispel_analysis(final_output["data"]["page1_wipeAnalysis"])
    final_output["data"]["page2_avoidableBoard"] = {
        key: sort_avoidable_rows(rows.values())
        for key, rows in global_avoidable.items()
    }
    final_output["data"]["page2_avoidableFirstDeathBoard"] = summarize_avoidable_first_deaths(final_output["data"]["page1_wipeAnalysis"])
    return final_output


def analyze(report_ids: str, output_path=None, catalog_entry=None, options=None):
    result = build_aggregated_json(report_ids)
    return write_json_result(result, output_path, catalog_entry=catalog_entry)
