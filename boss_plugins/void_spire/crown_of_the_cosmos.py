import json
import math
import os
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import requests
except ModuleNotFoundError as exc:
    raise RuntimeError("缺少 requests 依赖,请检查requirements！") from exc
import urllib3

from analyzer_core.concurrency import MAX_REQUEST_RETRIES, MAX_REQUEST_THREADS, REQUEST_RETRY_BASE_SECONDS, request_post, run_parallel_indexed
from analyzer_core.progress import emit_progress
from boss_plugins.common import build_player_mechanic_roles, role_text as common_role_text, write_json_result

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


PLUGIN_CONFIG = {
    "boss": {
        "key": "crown_of_the_cosmos",
        "name": "宇宙之冕",
        "keywords": ["crown of the cosmos", "alleria", "奥蕾莉亚", "宇宙之冕"],
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
_API_METRICS_LOCK = threading.Lock()
_API_LOGICAL_REQUESTS = 0


SPELLS = {
    1: "近战攻击",
    3: "坠落",
    27680: "狂暴",
    26662: "狂暴",
    1233470: "幽影束缚",
    1233602: "银锋箭标记",
    1233649: "银锋箭",
    1233778: "回响黑暗",
    1233819: "虚空斥力",
    1233787: "黑暗之手",
    1233789: "黑暗之手",
    1233826: "虚空斥力",
    1234546: "裂银浩劫",
    1234570: "星辰散射",
    1235553: "银锋弹幕射击",
    1235631: "奇点喷发",
    1237040: "虚空追猎者钉刺",
    1237844: "幽影束缚",
    1237875: "虚空召唤",
    1238709: "黑暗冲锋",
    1239095: "重力坍缩",
    1238882: "噬灭宇宙",
    1239672: "凝结形态",
    1239111: "终末守护",
    1243743: "干扰震荡",
    1243753: "暴食深渊",
    1243981: "银锋弹幕射击",
    1246001: "环绕物质",
    1246461: "裂隙挥砍",
    1246462: "裂隙挥砍",
    1242553: "虚空残渣",
    1255378: "崩裂空无",
    1255453: "重力坍缩",
    1259861: "游侠队长印记",
    1259869: "银锋弹射",
    1260000: "虚空弹幕",
    1260019: "幻影反冲",
    1260027: "空虚之握",
    1260766: "宇宙辐射",
    1260771: "宇宙辐射",
    1260838: "次元斩",
    1260839: "次元斩",
    1261289: "宇宙屏障",
    1261339: "宇宙传送门",
    1261531: "腐化精华",
    1281707: "回响黑暗",
    1283236: "虚空斥力",
}

P1_EXPECTED_ARROW_MS = [43_466, 99_350, 125_559]
P1_EXPECTED_TOLERANCE_MS = 2_000
GLOBAL_DEATH_EXEMPT_THRESHOLD = 8
P1_MIN_TRANSITION_START_MS = P1_EXPECTED_ARROW_MS[-1] - P1_EXPECTED_TOLERANCE_MS
P1_RAGE_LIMIT_MS = 165_000
P2_EXPECTED_DURATION_MS = 150_000
P15_DURATION_MS = 38_000
P15_SCATTER_MIN_AFTER_START_MS = 30_000
P15_SCATTER_MAX_AFTER_START_MS = 50_000
P25_FALLBACK_DURATION_MS = 18_000
P3_PORTAL_LEAD_MS = 16_000
P3_LINE_FALLBACK_LEAD_MS = 55_000
MYTHIC_RAID_SIZE = 20
SILVER_ARROW_DAMAGE_ID = 1233649
SILVER_RICOCHET_ID = 1259869
SILVER_RICOCHET_ENERGY_DRAIN_ID = 1259998
SILVER_ARROW_DAMAGE_WARN = 300_000
VOID_REPULSION_DISTANCE_WARN = 2_500.0
VOID_REPULSION_SPREAD_MULTIPLIER = 1.8
VOID_REPULSION_WATER_RADIUS_YARDS = 15
VOID_REPULSION_GROUP_WINDOW_MS = 9_000

PULL_DEATH_IDS = {1255378, 1235631, 1235553, 1243981, SILVER_ARROW_DAMAGE_ID, 1233826, 1260027, 1242553}
SHADOW_AOE_IDS = {1261289, 1260019}
TANK_DEATH_IDS = {1, 1233787, 1233789, 1246461, 1238709}
P1_TANK_IDS = {1, 1233787, 1233789, 1238709, 1243753, 1281707}
P2_TANK_IDS = {1, 1246461}
P3_TANK_IDS = {1, 1246461, 1233787, 1233789}
AOE_DEATH_IDS = {1243743, 1260000, 1260771, 1233826, 1255739, 1234570, 1261289, 1260019}
P3_LINE_DEATH_ID = 1239095
COSMIC_DEVOUR_ID = 1238882
TERMINAL_GUARD_DEBUFF_ID = 1239111
P15_AVOIDABLE_IDS = {1235631, 1246001, 1243981, 1235553}
DIMENSIONAL_SLASH_IDS = {1260838, 1260839}
ENRAGE_IDS = {27680, 26662, 1239672}
RAGE_STACK_ID = 1233778
P1_SHADOW_BINDING_ID = 1233470
P2_SHADOW_BINDING_ID = 1237844
SHADOW_BINDING_IDS = {P1_SHADOW_BINDING_ID, P2_SHADOW_BINDING_ID}
CORRUPTION_ID = 1261531
AVOIDABLE_DAMAGE_SPELLS = {
    "corruptionEssenceDamage": {"id": CORRUPTION_ID, "name": "腐化精华"},
}
AVOIDABLE_DAMAGE_IDS = {row["id"] for row in AVOIDABLE_DAMAGE_SPELLS.values()}
SILVER_ARROW_MARK_ID = 1233602
SILVER_RESIDUE_ID = 1233689
RANGER_MARK_ID = 1259861
VOID_REPULSION_DEBUFF_ID = 1283236
VOID_REPULSION_DAMAGE_ID = 1233826
VOID_REPULSION_CAST_ID = 1233819
VOID_GRASP_ID = 1260027
COLLAPSING_VOID_ID = 1255378
GRAVITY_COLLAPSE_DEBUFF_ID = 1255453
COSMIC_RADIATION_BUFF_ID = 1260766
COSMIC_RADIATION_DAMAGE_ID = 1260771
COSMIC_BARRIER_ID = 1261289
PORTAL_CAST_ID = 1261339
SILVER_HAVOC_CAST_ID = 1234546
ALLERIA_GAME_ID = 240430
MAWRIUS_GAME_ID = 243805
PHANTOM_GAME_ID = 253742
INTERFERENCE_SHOCK_ID = 1243743
DEATH_COMPENSATION_ID = 211319
RIFT_SLASH_ID = 1246462
RIFT_SLASH_DAMAGE_ID = 1246461
P3_ADD_GAME_IDS = {
    1: 254172,  # 龌勒卢斯
    2: 254173,  # 殆米阿尔
    3: 254174,  # 殁里乌姆
}
P3_ADD_NAMES = {
    254172: "龌勒卢斯",
    254173: "殆米阿尔",
    254174: "殁里乌姆",
}
VORELUTH_GAME_IDS = {254172, 243811}  # 实战日志中可见 243811
VORELUTH_VULN_SKILL_KEY = "voreluthVulnerabilityFade"
VORELUTH_VULN_SKILL_NAME = "P1 龌勒卢斯易伤异常"
PASSAGE_CLIFF_SKILL_KEY = "passageCliffMistakes"
PASSAGE_CLIFF_SKILL_NAME = "过场失误"
DESIGNATED_HEALER_IDS = {
    int(value) for value in os.getenv("CROWN_DESIGNATED_HEALER_IDS", "").split(",")
    if value.strip().isdigit()
}

PLAYER_CAST_NAMES = {
    116: "Frostbolt",
    596: "Prayer of Healing",
    686: "Shadow Bolt",
    1064: "Chain Heal",
    2061: "Flash Heal",
    6353: "Soul Fire",
    29722: "Incinerate",
    77472: "Healing Wave",
    82326: "Holy Light",
    105174: "Hand of Gul'dan",
    116858: "Chaos Bolt",
    199786: "Glacial Spike",
    205021: "Ray of Frost",
    361469: "Living Flame",
    373861: "Temporal Anomaly",
}
DESIGNATED_HEALER_NAMES = {
    name.strip()
    for name in os.getenv("CROWN_DESIGNATED_HEALER_NAMES", "旖旎云逸,暗黑膏药").split(",")
    if name.strip()
}
VOID_GRASP_HEALING_MIN = int(os.getenv("CROWN_VOID_GRASP_HEALING_MIN", "200000"))
VERDICT_POINTS_PER_COUNT = int(os.getenv("CROWN_VERDICT_POINTS_PER_COUNT", "10"))
VERDICT_TANK_MULTIPLIER = float(os.getenv("CROWN_VERDICT_TANK_MULTIPLIER", "1"))


def configured_acquittals():
    result = {}
    for item in os.getenv("CROWN_APPEAL_ACQUITTALS", "").split(","):
        if ":" not in item:
            continue
        name, value = item.rsplit(":", 1)
        if name.strip() and value.strip().isdigit():
            result[name.strip()] = int(value.strip())
    return result

TANK_SPEC_IDS = {
    66, 104, 250, 268, 581, 1446,
}
HEALER_SPEC_IDS = {
    65, 105, 256, 257, 264, 270, 1468,
}

P1_ARROW_TARGETS = {
    43_466: "殆米阿尔",
    99_350: "殁里乌姆",
    125_559: "龌勒卢斯",
}
MELURIUM_EXPECTED_MS = 99_350
MELURIUM_GAME_IDS = {254174, MAWRIUS_GAME_ID}

ACTOR_NAME_OVERRIDES = {
    "Alleria Windrunner": "奥蕾莉亚·风行者",
    "The Crown of the Cosmos": "宇宙之冕",
    "Mawrius": "殁里乌姆",
    "Morium": "殁里乌姆",
    "Damiar": "殆米阿尔",
    "Demiar": "殆米阿尔",
    "Voreluth": "龌勒卢斯",
    "Vorelus": "龌勒卢斯",
}


def progress(message, indent=0):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {'  ' * indent}{message}", flush=True)
    emit_progress(message, detail=indent > 0)


def get_token():
    if not CLIENT_ID or not CLIENT_SECRET:
        raise RuntimeError("请先在项目 .env 或系统环境变量中设置 WCL_CLIENT_ID 和 WCL_CLIENT_SECRET。")
    progress(f"连接 WCL 鉴权端点：{WCL_BASE_URL}/oauth/token", 1)
    res = request_post(
        f"{WCL_BASE_URL}/oauth/token",
        data={"grant_type": "client_credentials"},
        auth=(CLIENT_ID, CLIENT_SECRET),
        proxies=PROXIES,
        verify=False,
        timeout=30,
    )
    if res.status_code == 401:
        raise RuntimeError("WCL 鉴权失败：请确认 .env 中填写的是 API Client ID / Secret。")
    if res.status_code == 403:
        raise RuntimeError(
            f"WCL 鉴权端点连续返回 403（已自动重试 {MAX_REQUEST_RETRIES} 次）。"
            f"当前代理：{PROXY_URL or '未启用'}。请检查代理出口或稍后重试；这不是额度不足。"
        )
    res.raise_for_status()
    return res.json()["access_token"]


def graphql(token, query, variables):
    global _API_LOGICAL_REQUESTS
    with _API_METRICS_LOCK:
        _API_LOGICAL_REQUESTS += 1
    headers = {"Authorization": f"Bearer {token}"}
    last_error = None
    for attempt in range(1, MAX_REQUEST_RETRIES + 1):
        try:
            res = request_post(
                f"{WCL_BASE_URL}/api/v2/client",
                json={"query": query, "variables": variables},
                headers=headers,
                proxies=PROXIES,
                verify=False,
                timeout=90,
            )
            break
        except requests.RequestException as error:
            last_error = error
            if attempt >= MAX_REQUEST_RETRIES:
                raise
            progress(f"WCL 请求失败，{attempt}/{MAX_REQUEST_RETRIES}，稍后重试：{error}", 2)
            time.sleep(REQUEST_RETRY_BASE_SECONDS * (2 ** (attempt - 1)))
    else:
        raise last_error
    if res.status_code == 403:
        body = (res.text or "")[:300].replace("\n", " ")
        raise RuntimeError(
            f"WCL v2 连续返回 403（已自动重试 {MAX_REQUEST_RETRIES} 次，代理：{PROXY_URL or '未启用'}）。"
            f"响应摘要：{body or '无'}"
        )
    res.raise_for_status()
    payload = res.json()
    if payload.get("errors"):
        raise RuntimeError(json.dumps(payload["errors"], ensure_ascii=False))
    return payload["data"]["reportData"]["report"]


def fetch_report_fights(token, report_id):
    def query_fights(include_friendly_players=True):
        fields = "id name startTime endTime kill friendlyPlayers" if include_friendly_players else "id name startTime endTime kill"
        query = """
        query($code: String!) {
          reportData {
            report(code: $code) {
              startTime
              fights { __FIELDS__ }
            }
          }
        }
        """.replace("__FIELDS__", fields)
        return graphql(token, query, {"code": report_id})

    try:
        report = query_fights(True)
    except RuntimeError as error:
        if "friendlyPlayers" not in str(error):
            raise
        progress("当前 WCL fights 不支持 friendlyPlayers，使用回退查询", 2)
        report = query_fights(False)

    valid = []
    for fight in report["fights"]:
        name = (fight.get("name") or "").lower()
        duration = fight["endTime"] - fight["startTime"]
        if duration < 20_000:
            continue
        if any(keyword in name for keyword in PLUGIN_CONFIG["boss"]["keywords"]):
            fight["reportStartTime"] = report["startTime"]
            valid.append(fight)
    return valid


def fetch_actor_maps(token, report_id):
    def query_actors(include_game_id=True):
        fields = "id name type petOwner gameID subType" if include_game_id else "id name type petOwner"
        query = """
        query($code: String!) {
          reportData {
            report(code: $code) {
              masterData { actors { __FIELDS__ } }
            }
          }
        }
        """.replace("__FIELDS__", fields)
        return graphql(token, query, {"code": report_id})

    try:
        report = query_actors(True)
    except RuntimeError as error:
        if "gameID" not in str(error) and "subType" not in str(error):
            raise
        progress("当前 WCL actors 不支持 gameID/subType，使用名字回退识别 NPC", 2)
        report = query_actors(False)
    actors = report["masterData"]["actors"]
    id_to_name = {actor["id"]: actor["name"] for actor in actors}
    pet_to_owner = {
        actor["id"]: actor["petOwner"]
        for actor in actors
        if actor.get("petOwner") and actor.get("petOwner") in id_to_name
    }
    actor_map = {}
    actor_type = {}
    actor_game_id = {}
    for actor_item in actors:
        actor_id = actor_item["id"]
        owner_id = pet_to_owner.get(actor_id)
        name = id_to_name.get(owner_id, actor_item["name"]) if owner_id else actor_item["name"]
        actor_map[actor_id] = ACTOR_NAME_OVERRIDES.get(name, name)
        actor_type[actor_id] = actor_item.get("type")
        actor_game_id[actor_id] = actor_item.get("gameID") or actor_item.get("subType")
    return actor_map, actor_type, actor_game_id


def fetch_event_page(token, report_id, data_type, fight, start_time=None, end_time=None, ability_id=None, hostility_type=None, include_resources=False, source_id=None, target_id=None):
    ability_arg = ", $abilityID: Float" if ability_id is not None else ""
    ability_filter = ", abilityID: $abilityID" if ability_id is not None else ""
    hostility_arg = ", $hostilityType: HostilityType" if hostility_type else ""
    hostility_filter = ", hostilityType: $hostilityType" if hostility_type else ""
    resources_arg = ", $includeResources: Boolean" if include_resources else ""
    resources_filter = ", includeResources: $includeResources" if include_resources else ""
    source_arg = ", $sourceID: Int" if source_id is not None else ""
    source_filter = ", sourceID: $sourceID" if source_id is not None else ""
    target_arg = ", $targetID: Int" if target_id is not None else ""
    target_filter = ", targetID: $targetID" if target_id is not None else ""
    query = f"""
    query($code: String!, $dataType: EventDataType!, $startTime: Float!, $endTime: Float!, $fightIDs: [Int]{ability_arg}{hostility_arg}{resources_arg}{source_arg}{target_arg}) {{
      reportData {{
        report(code: $code) {{
          events(dataType: $dataType, startTime: $startTime, endTime: $endTime, fightIDs: $fightIDs, limit: 10000{ability_filter}{hostility_filter}{resources_filter}{source_filter}{target_filter}) {{
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
    if include_resources:
        variables["includeResources"] = True
    if source_id is not None:
        variables["sourceID"] = int(source_id)
    if target_id is not None:
        variables["targetID"] = int(target_id)
    for attempt in range(1, MAX_REQUEST_RETRIES + 1):
        report = graphql(token, query, variables)
        events = report.get("events")
        if events is not None:
            return events
        progress(f"WCL events 为空，{attempt}/{MAX_REQUEST_RETRIES} 稍后重试", 2)
        time.sleep(REQUEST_RETRY_BASE_SECONDS * (2 ** (attempt - 1)))
    return {"data": [], "nextPageTimestamp": None}


def fetch_events_all(token, report_id, data_type, fight, start_time=None, end_time=None, ability_id=None, hostility_type=None, include_resources=False, source_id=None, target_id=None):
    rows = []
    current_start = start_time if start_time is not None else fight["startTime"]
    final_end = end_time if end_time is not None else fight["endTime"]
    while current_start < final_end:
        page = fetch_event_page(token, report_id, data_type, fight, current_start, final_end, ability_id, hostility_type, include_resources, source_id, target_id)
        if not page:
            page = {"data": [], "nextPageTimestamp": None}
        rows.extend(page.get("data") or [])
        next_page = page.get("nextPageTimestamp")
        if not next_page or next_page <= current_start:
            break
        current_start = next_page
    return rows


def fetch_spell_events(token, report_id, fight, data_type, spell_ids, label, hostility_type=None, include_resources=False):
    rows = []
    spell_ids = sorted(spell_ids)
    if not spell_ids:
        return rows

    def fetch_one(index_and_spell):
        index, spell_id = index_and_spell
        progress(f"{label} {index}/{len(spell_ids)}：{SPELLS.get(spell_id, spell_id)} ({spell_id})", 2)
        spell_rows = fetch_events_all(token, report_id, data_type, fight, ability_id=spell_id, hostility_type=hostility_type, include_resources=include_resources)
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


def fetch_combatant_info(token, report_id, fight):
    try:
        return fetch_events_all(token, report_id, "CombatantInfo", fight)
    except Exception as error:
        progress(f"CombatantInfo 读取失败，职责展示将使用未知：{error}", 2)
        return []


def fetch_interference_interrupt_table(token, report_id, fight):
    query = """
    query($code: String!, $fightIDs: [Int]) {
      reportData {
        report(code: $code) {
          table(dataType: Interrupts, fightIDs: $fightIDs, hostilityType: Enemies)
        }
      }
    }
    """
    report = graphql(token, query, {"code": report_id, "fightIDs": [fight["id"]]})
    return report.get("table") or {}


def fetch_initial_combat_events(token, report_id, fight):
    end_time = min(fight["endTime"], fight["startTime"] + 15_000)
    events = []
    for data_type in ("DamageDone", "DamageTaken"):
        try:
            events.extend(fetch_events_all(token, report_id, data_type, fight, fight["startTime"], end_time))
        except Exception as error:
            progress(f"初始进战斗 {data_type} 读取失败，引怪推测可能不完整：{error}", 2)
    return events


def ability_id(event):
    return event.get("abilityGameID") or event.get("killingAbilityGameID") or event.get("extraAbilityGameID")


def ability_name(event):
    aid = ability_id(event)
    return event.get("abilityName") or event.get("name") or SPELLS.get(aid, str(aid or "未知"))


def actor(actor_map, actor_id):
    return actor_map.get(actor_id, f"未知({actor_id})")


def build_player_roles(combatant_info):
    return build_player_mechanic_roles(combatant_info)


def role_text(role):
    return common_role_text(role)


def merge_roles(existing_roles, new_roles):
    order = {
        "tank": 0,
        "melee-healer": 1,
        "range-healer": 2,
        "melee-dps": 3,
        "range-dps": 4,
        "healer": 5,
        "dps": 6,
        "unknown": 7,
    }
    roles = {role for role in (existing_roles or []) + (new_roles or []) if role and role != "unknown"}
    return sorted(roles, key=lambda role: order.get(role, 99))


def event_amount(event):
    return int(event.get("amount") or 0) + int(event.get("absorbed") or 0)


def fight_elapsed(event, fight):
    return int(event.get("timestamp", 0) - fight["startTime"])


def format_time(ms):
    return str(timedelta(seconds=max(0, int(ms)) // 1000))[2:7]


def get_local_datetime(absolute_ms):
    return datetime.fromtimestamp(absolute_ms / 1000.0, CN_TZ)


def deep_link(report_id, fight_id, view_type, event_time, before_ms=15_000, after_ms=2_000):
    return (
        f"{WCL_BASE_URL}/reports/{report_id}#fight={fight_id}&type={view_type}"
        f"&start={event_time - before_ms}&end={event_time + after_ms}"
    )


def fight_type_link(report_id, fight_id, view_type):
    return f"{WCL_BASE_URL}/reports/{report_id}?fight={fight_id}&type={view_type}"


def deaths_link(report_id, fight_id):
    return fight_type_link(report_id, fight_id, "deaths")


def replay_link(report_id, fight_id, position_ms):
    return f"{WCL_BASE_URL}/reports/{report_id}?fight={fight_id}&view=replay&position={max(0, int(position_ms))}"


def event_is_apply(event):
    return str(event.get("type", "")).lower() in {"applybuff", "applydebuff", "applybuffstack", "applydebuffstack", "refreshbuff", "refreshdebuff"}


def event_is_remove(event):
    return str(event.get("type", "")).lower() in {"removebuff", "removedebuff"}


def event_is_full_debuff_fade(event):
    """Debuff 因层数/持续时间正常完整消失（非 removedebuffstack 的单层衰减事件）。"""
    return str(event.get("type", "")).lower() == "removedebuff"


def corruption_stack_at(debuffs, target_id, at_ts):
    """还原目标在 at_ts 时刻腐化精华层数；完整 removedebuff 取断前层数。"""
    stack = 0
    for event in sorted((debuffs or []), key=lambda row: (row.get("timestamp", 0), str(row.get("type") or ""))):
        if ability_id(event) != CORRUPTION_ID or event.get("targetID") != target_id:
            continue
        ts = int(event.get("timestamp") or 0)
        if ts > at_ts:
            break
        etype = str(event.get("type") or "").lower()
        if etype in {"applydebuff", "applydebuffstack", "refreshdebuff"}:
            stack = int(event.get("stack") or stack or 1)
        elif etype == "removedebuffstack":
            if event.get("stack") is not None:
                stack = int(event.get("stack") or 0)
            else:
                stack = max(0, stack - 1)
        elif etype == "removedebuff":
            if ts == at_ts:
                if event.get("stack") is not None:
                    return max(1, int(event.get("stack") or 1))
                return max(1, stack) if stack else 1
            stack = 0
    return stack


def is_voreluth_actor(actor_map, actor_game_id, actor_id):
    if actor_id is None:
        return False
    game_id = (actor_game_id or {}).get(actor_id)
    try:
        if game_id is not None and int(game_id) in VORELUTH_GAME_IDS:
            return True
    except (TypeError, ValueError):
        pass
    name = str(actor(actor_map, actor_id) or "")
    return "龌勒卢斯" in name or "Voreluth" in name or "Vorelus" in name



def cliff_abandon_clusters(deaths, window_ms=8_000, min_size=4):
    """短窗口内连续多起坠崖 → 视为跳崖放弃波（含灭团末尾大团放弃）。

    注意：不能只取 first_bridge_cluster——前面若有零星坠崖，会把真正的放弃波漏掉（如 Fight18）。
    """
    return [
        cluster
        for cluster in cluster_events(bridge_deaths(deaths), window_ms=window_ms)
        if len(cluster.get("events") or []) >= min_size
    ]


def timestamp_in_cliff_abandon_cluster(timestamp, clusters, pad_before_ms=1_000, pad_after_ms=2_000):
    ts = int(timestamp or 0)
    for cluster in clusters or []:
        if int(cluster["start"]) - pad_before_ms <= ts <= int(cluster["end"]) + pad_after_ms:
            return True
    return False


def build_passage_cliff_board(fight, deaths, markers, death_timeline, player_roles, reason_key):
    """P2/P3 非转阶段窗口、非放弃跳崖波、且死亡序号仍 <8 的莫名坠崖 → 过场失误（必扣）。

    P1 无场地缝隙：掉下去即视为放弃跳崖，一律不记本项；P1.5/P2.5 仍归属转阶段项。
    密集坠崖簇（≥4 人 / 约 8s）整簇豁免，覆盖「进本阶段后大团放弃」误判。
    """
    ordered = sorted(deaths or [], key=lambda death: death.get("timestamp", 0))
    # 约 8s 内 ≥4 人坠崖 = 跳崖放弃波；不依赖 classification，避免 first_bridge_cluster 被零星坠崖占坑
    abandon_clusters = cliff_abandon_clusters(ordered)
    timeline = list(death_timeline or [])
    board = {}
    for index, death in enumerate(ordered):
        if index >= GLOBAL_DEATH_EXEMPT_THRESHOLD:
            continue
        if not is_bridge_death(death):
            continue
        phase = phase_at(death.get("timestamp", 0), markers, fight)
        # P1 无缝隙；P1.5/P2.5 为转阶段窗口
        if phase in {"P1", "P1.5", "P2.5"}:
            continue
        ts = int(death.get("timestamp") or 0)
        if timestamp_in_cliff_abandon_cluster(ts, abandon_clusters):
            continue
        match = min(
            (row for row in timeline if abs(int(row.get("absoluteTime") or 0) - ts) <= 20),
            key=lambda row: abs(int(row.get("absoluteTime") or 0) - ts),
            default=None,
        )
        if match and match.get("ability") == "转阶段击飞":
            continue
        name = (match or {}).get("player")
        if not name:
            continue
        role = (match or {}).get("role") or (player_roles or {}).get(death.get("targetID"), "unknown")
        position_ms = ts - int(fight["startTime"])
        time_text = (match or {}).get("time") or format_time(position_ms)
        item = board.setdefault(name, build_board_row(name, PASSAGE_CLIFF_SKILL_KEY, PASSAGE_CLIFF_SKILL_NAME, role=role))
        item["hitCount"] += 1
        item["deathCount"] += 1
        item["events"].append({
            "fightID": fight.get("id"),
            "player": name,
            "role": role,
            "phase": phase,
            "time": time_text,
            "positionMs": position_ms,
            "ability": "坠崖",
            "abilityID": death.get("killingAbilityGameID"),
            "counted": True,
            "verdictCounted": True,
            "displayOnly": False,
            "countReason": (
                f"{phase} 非转阶段窗口莫名坠崖，且不在密集跳崖放弃波内、死亡仍在第"
                f"{GLOBAL_DEATH_EXEMPT_THRESHOLD}次内，按过场失误计数"
            ),
            "text": f"Fight{fight.get('id')} {name} 于 {time_text}（{phase}）死于坠崖 · 过场失误",
        })
    return sorted(board.values(), key=lambda row: row.get("deathCount", 0), reverse=True)


def fight_tank_players(actor_map, player_roles):
    """Return [(actor_id, name), ...] for players with tank role."""
    tanks = []
    for actor_id, role in (player_roles or {}).items():
        if role != "tank":
            continue
        tanks.append((actor_id, actor(actor_map, actor_id)))
    tanks.sort(key=lambda item: (item[1] or "", item[0] or 0))
    return tanks


def analyze_voreluth_vulnerability_fade(fight, actor_map, actor_game_id, debuffs):
    """P1 龌勒卢斯易伤异常（按场计数，归因坦克）。

    窗口：龌勒卢斯第一次被施加腐化精华 → 其幽影束缚消失之前。
    同场多次完整 faded：每名坦克各计 fade 次数（不展示名单中的坦克仍写入 JSON，前端过滤）。
    """
    voreluth_ids = {
        actor_id for actor_id in set(actor_map) | set(actor_game_id or {})
        if is_voreluth_actor(actor_map, actor_game_id, actor_id)
    }
    if not voreluth_ids:
        return None

    fades = []
    first_apply_ms = None
    binding_gone_ms = None
    silver_arrow_apply_times_ms = sorted(
        (
            int(event.get("timestamp") or 0) - int(fight.get("startTime") or 0)
            for event in debuffs or []
            if ability_id(event) == SILVER_ARROW_MARK_ID and event_is_apply(event)
        )
    )
    # 只以第6轮银锋箭（P1关键击杀轮）作为截断点；没有第6轮时再回退到最后一轮
    final_p1_arrow_ms = None
    if len(silver_arrow_apply_times_ms) >= 6:
        final_p1_arrow_ms = int(silver_arrow_apply_times_ms[5])
    elif silver_arrow_apply_times_ms:
        final_p1_arrow_ms = int(silver_arrow_apply_times_ms[-1])
    for target_id in sorted(voreluth_ids):
        corruption_applies = sorted(
            (
                event for event in debuffs or []
                if ability_id(event) == CORRUPTION_ID
                and event_is_apply(event)
                and event.get("targetID") == target_id
            ),
            key=lambda event: event.get("timestamp", 0),
        )
        if not corruption_applies:
            continue
        first_apply = corruption_applies[0]
        apply_ts = int(first_apply.get("timestamp") or 0)
        apply_ms = apply_ts - int(fight["startTime"])
        first_apply_ms = apply_ms if first_apply_ms is None else min(first_apply_ms, apply_ms)
        binding_end = next(
            (
                event for event in sorted(
                    (
                        event for event in debuffs or []
                        if ability_id(event) == P1_SHADOW_BINDING_ID
                        and event_is_remove(event)
                        and event.get("targetID") == target_id
                    ),
                    key=lambda event: event.get("timestamp", 0),
                )
                if int(event.get("timestamp") or 0) >= apply_ts
            ),
            None,
        )
        window_end = int(binding_end.get("timestamp") or 0) if binding_end else int(fight.get("endTime") or apply_ts)
        if binding_end:
            gone_ms = window_end - int(fight["startTime"])
            binding_gone_ms = gone_ms if binding_gone_ms is None else max(binding_gone_ms, gone_ms)
        for fade in sorted(
            (
                event for event in debuffs or []
                if ability_id(event) == CORRUPTION_ID
                and event_is_full_debuff_fade(event)
                and event.get("targetID") == target_id
            ),
            key=lambda event: event.get("timestamp", 0),
        ):
            fade_ts = int(fade.get("timestamp") or 0)
            if not (apply_ts < fade_ts < window_end):
                continue
            position_ms = fade_ts - int(fight["startTime"])
            # 仅统计第6银锋箭（P1 最后一轮）前的断层；其后不再计入
            if final_p1_arrow_ms is not None and position_ms >= int(final_p1_arrow_ms):
                continue
            stack = corruption_stack_at(debuffs, target_id, fade_ts)
            # Boss 会被银锋箭射击；如果腐化精华消失发生在银锋箭作用时刻附近，
            # 视为“预期内消失”，不作为断层计入。
            if final_p1_arrow_ms is not None and abs(position_ms - int(final_p1_arrow_ms)) <= 3_000:
                continue
            fades.append({
                "time": format_time(position_ms),
                "positionMs": position_ms,
                "stack": stack,
                "targetID": target_id,
                "target": actor(actor_map, target_id),
                "text": f"{format_time(position_ms)} 完整 faded，断时约 {stack} 层",
            })

    if not fades:
        return None

    fades.sort(key=lambda row: int(row.get("positionMs") or 0))
    stack_parts = [f"{int(row.get('stack') or 0)}层@{row.get('time')}" for row in fades]
    first_fade_ms = int(fades[0].get("positionMs") or 0)
    first_fade_stack = int(fades[0].get("stack") or 0)
    stack_label = "、".join(f"{int(row.get('stack') or 0)}层" for row in fades)
    return {
        "fightID": fight.get("id"),
        "fadeCount": len(fades),
        "fades": fades,
        "stacks": [int(row.get("stack") or 0) for row in fades],
        "stackSummary": "、".join(stack_parts),
        "applyTime": format_time(first_apply_ms) if first_apply_ms is not None else None,
        "bindingGoneTime": format_time(binding_gone_ms) if binding_gone_ms is not None else None,
        "bindingRemoved": binding_gone_ms is not None,
        "time": format_time(first_fade_ms),
        "positionMs": first_fade_ms,
        "firstFadeTime": format_time(first_fade_ms),
        "firstFadeStack": first_fade_stack,
        "counted": True,
        "verdictCounted": True,
        "displayOnly": False,
        "excludeFromCourtPlayers": False,
        "isSystem": False,
        "countReason": "腐化精华在幽影束缚仍存在期间因层数完整消失发生 complete faded；若消失时间落在银锋箭作用附近则视为预期内不计断层（同场仅计1次；受第8死豁免）",
        "text": (
            f"Fight{fight.get('id')} 龌勒卢斯第一次被施加腐化精华时间为 {format_time(first_apply_ms) if first_apply_ms is not None else '-'}，"
            f"第一次消失时间为 {format_time(first_fade_ms)}，断时约 {first_fade_stack}层。"
            f"（同场fade {stack_label}）仅计1次"
        ),
    }


def build_voreluth_vulnerability_board(fight, actor_map, actor_game_id, debuffs, player_roles=None):
    summary = analyze_voreluth_vulnerability_fade(fight, actor_map, actor_game_id, debuffs)
    if not summary:
        return [], None
    tanks = fight_tank_players(actor_map, player_roles)
    if not tanks:
        row = build_board_row(f"Fight{fight.get('id')}", VORELUTH_VULN_SKILL_KEY, VORELUTH_VULN_SKILL_NAME, role="unknown")
        row["hitCount"] = 1 if int(summary.get("fadeCount") or 0) else 0
        row["isSystem"] = True
        row["excludeFromCourtPlayers"] = True
        row["events"] = [summary]
        return [row], summary

    rows = []
    for actor_id, name in tanks:
        if not name:
            continue
        row = build_board_row(name, VORELUTH_VULN_SKILL_KEY, VORELUTH_VULN_SKILL_NAME, role="tank")
        fades = summary.get("fades") or []
        stacks = [int(fade.get("stack") or 0) for fade in fades if fade.get("stack") is not None]
        stack_text = "、".join(f"{stack}层" for stack in stacks if stack)
        times = [fade.get("time") for fade in fades if fade.get("time")]
        tank_events = [{
            "fightID": fight.get("id"),
            "player": name,
            "targetID": actor_id,
            "role": "tank",
            "time": times[-1] if times else None,
            "positionMs": fades[-1].get("positionMs") if fades else None,
            "stack": stacks[-1] if stacks else None,
            "fadeCount": len(fades),
            "fades": fades,
            "counted": True,
            "verdictCounted": True,
            "displayOnly": False,
            "excludeFromCourtPlayers": False,
            "isSystem": False,
            "countReason": "P1 龌勒卢斯易伤异常：银锋箭作用附近造成的腐化精华消失不计断层，同场仅计 1 次",
            "applyTime": summary.get("applyTime"),
            "firstFadeTime": summary.get("firstFadeTime"),
            "firstFadeStack": summary.get("firstFadeStack"),
            "text": (
                f"Fight{fight.get('id')} {name}（坦克）· 龌勒卢斯第一次被施加腐化精华时间为 {summary.get('applyTime') or '-'}，"
                f"第一次消失时间为 {summary.get('firstFadeTime') or '-'}，断时约 {summary.get('firstFadeStack') or 0}层。"
                + (f"（同场fade {stack_text}）仅计1次" if stack_text else "仅计1次")
            ),
        }]
        row["hitCount"] = 1 if tank_events else 0
        row["events"] = tank_events
        rows.append(row)
    tank_names = "、".join(name for _, name in tanks if name)
    summary = {
        **summary,
        "attributedTanks": [name for _, name in tanks if name],
        "text": f"{summary.get('text')}；归因坦克：{tank_names or '无'}",
    }
    return rows, summary




def cluster_events(events, window_ms=3_000):
    clusters = []
    for event in sorted(events, key=lambda item: item.get("timestamp", 0)):
        ts = event.get("timestamp", 0)
        if not clusters or ts - clusters[-1]["end"] > window_ms:
            clusters.append({"start": ts, "end": ts, "events": [event]})
        else:
            clusters[-1]["end"] = ts
            clusters[-1]["events"].append(event)
    return clusters


def deaths_before(deaths, timestamp):
    return [death for death in deaths if death.get("timestamp", 0) <= timestamp]


def boss_energy_events(energy_events):
    return [
        event for event in (energy_events or [])
        if str(event.get("resourceChangeType")) == "3"
        and (event.get("resourceChange") is not None or event.get("classResources"))
    ]


def boss_energy_after(event):
    resources = event.get("classResources") or []
    for resource in resources:
        if str(resource.get("type")) == "3":
            return resource.get("amount")
    return None


def phase_markers(casts, buffs, debuffs, fight, energy_events=None):
    min_p15_start = fight["startTime"] + P1_MIN_TRANSITION_START_MS
    silver_havoc_casts = [event for event in casts if ability_id(event) == SILVER_HAVOC_CAST_ID]
    silver_havoc_times = sorted(
        event.get("timestamp", 0)
        for event in silver_havoc_casts
    )
    p15_start = min((timestamp for timestamp in silver_havoc_times if timestamp >= min_p15_start), default=None)

    scatter_remove_times = sorted(
        event.get("timestamp", 0)
        for event in debuffs
        if ability_id(event) == 1234570 and event_is_remove(event)
    )
    p2_start = None
    if p15_start:
        p2_start = max((
            timestamp for timestamp in scatter_remove_times
            if p15_start + P15_SCATTER_MIN_AFTER_START_MS <= timestamp <= p15_start + P15_SCATTER_MAX_AFTER_START_MS
        ), default=None)
    elif scatter_remove_times:
        inferred_p15_start = max(scatter_remove_times) - P15_DURATION_MS
        if inferred_p15_start >= min_p15_start:
            p15_start = inferred_p15_start
            p2_start = max(scatter_remove_times)
        elif min(scatter_remove_times) >= min_p15_start:
            p15_start = min_p15_start

    if p15_start and not p2_start:
        p2_start = p15_start + P15_DURATION_MS
    if p2_start and not p15_start:
        p15_start = max(fight["startTime"], p2_start - P15_DURATION_MS)

    energy_rows = boss_energy_events(energy_events)
    energy_resets = sorted(
        event.get("timestamp", 0)
        for event in energy_rows
        if event.get("resourceChange", 0) <= -90
        and event.get("timestamp", 0) >= (p15_start or min_p15_start)
    )
    if energy_resets and p2_start:
        pre_p3_reset = min(energy_resets, default=None)
        if pre_p3_reset and abs(pre_p3_reset - p2_start) <= 10_000:
            p2_start = pre_p3_reset

    radiation_applies = [event for event in buffs if ability_id(event) == COSMIC_RADIATION_BUFF_ID and event_is_apply(event)]
    radiation_removes = [event for event in buffs if ability_id(event) == COSMIC_RADIATION_BUFF_ID and event_is_remove(event)]
    p3_transition = min((event.get("timestamp", 0) for event in radiation_applies), default=None)
    p3_start = min((event.get("timestamp", 0) for event in radiation_removes), default=None)

    barrier_applies = [event for event in buffs if ability_id(event) == COSMIC_BARRIER_ID and event_is_apply(event)]
    barrier_removes = [event for event in buffs if ability_id(event) == COSMIC_BARRIER_ID and event_is_remove(event)]
    p25_start = min((event.get("timestamp", 0) for event in barrier_applies), default=None) or p3_transition
    p25_end = min((event.get("timestamp", 0) for event in barrier_removes), default=None) or p3_start
    if p25_start and not p3_transition:
        p3_transition = p25_start
    if p25_end and not p3_start:
        p3_start = p25_end

    portal_casts = [event for event in casts if ability_id(event) == PORTAL_CAST_ID]
    first_portal = min((event.get("timestamp", 0) for event in portal_casts), default=None)
    if not p3_start and first_portal:
        p3_start = max(fight["startTime"], first_portal - P3_PORTAL_LEAD_MS)
    if p3_start and not p25_end:
        p25_end = p3_start
    if p3_start and not p25_start and p2_start:
        p25_start = max(p2_start, p3_start - P25_FALLBACK_DURATION_MS)
    if p25_start and not p3_transition:
        p3_transition = p25_start

    terminal_guard_applies = [
        event for event in debuffs
        if ability_id(event) == TERMINAL_GUARD_DEBUFF_ID
        and str(event.get("type", "")).lower() == "applydebuff"
    ]
    first_terminal_guard = min((event.get("timestamp", 0) for event in terminal_guard_applies), default=None)
    if not p3_start and first_terminal_guard:
        p3_start = first_terminal_guard
    if p3_start and not p25_end:
        p25_end = p3_start
    if p3_start and not p25_start and p2_start:
        p25_start = max(p2_start, p3_start - P25_FALLBACK_DURATION_MS)
    if p25_start and not p3_transition:
        p3_transition = p25_start

    return {
        "p15Start": p15_start,
        "p2Start": p2_start,
        "p3Transition": p3_transition,
        "p25Start": p25_start,
        "p25End": p25_end,
        "p3Start": p3_start,
        "silverHavocCasts": silver_havoc_casts,
        "radiationApplies": radiation_applies,
        "radiationRemoves": radiation_removes,
        "barrierApplies": barrier_applies,
        "barrierRemoves": barrier_removes,
        "portalCasts": portal_casts,
        "terminalGuardApplies": terminal_guard_applies,
    }


def infer_phase_markers_from_deaths(markers, deaths, fight):
    if markers.get("p3Start"):
        return markers

    slash_deaths = sorted(
        (death for death in deaths if death.get("killingAbilityGameID") in DIMENSIONAL_SLASH_IDS),
        key=lambda item: item.get("timestamp", 0),
    )
    gravity_cluster = first_gravity_collapse_cluster(deaths)
    p3_signal_deaths = sorted(
        (
            death for death in deaths
            if death.get("killingAbilityGameID") in {P3_LINE_DEATH_ID, COSMIC_DEVOUR_ID, COSMIC_RADIATION_DAMAGE_ID}
        ),
        key=lambda item: item.get("timestamp", 0),
    )

    p3_start = None
    if slash_deaths:
        p25_start = max(fight["startTime"], slash_deaths[0].get("timestamp", 0) - 1_000)
        p3_start = slash_deaths[-1].get("timestamp", 0) + 7_000
        markers["p25Start"] = markers.get("p25Start") or p25_start
        markers["p3Transition"] = markers.get("p3Transition") or markers["p25Start"]
    elif gravity_cluster:
        p3_start = gravity_cluster["start"] - P3_LINE_FALLBACK_LEAD_MS
        if markers.get("p2Start"):
            p3_start = max(markers["p2Start"], p3_start)
    elif p3_signal_deaths:
        p3_start = p3_signal_deaths[0].get("timestamp", 0) - P3_LINE_FALLBACK_LEAD_MS
        if markers.get("p2Start"):
            p3_start = max(markers["p2Start"], p3_start)

    if p3_start:
        markers["p3Start"] = min(max(fight["startTime"], p3_start), fight["endTime"])
        markers["p25End"] = markers.get("p25End") or markers["p3Start"]
        if not markers.get("p25Start") and markers.get("p2Start"):
            markers["p25Start"] = max(markers["p2Start"], markers["p3Start"] - P25_FALLBACK_DURATION_MS)
        if markers.get("p25Start") and not markers.get("p3Transition"):
            markers["p3Transition"] = markers["p25Start"]
    return markers


def sanitize_phase_markers(markers, fight):
    """Reject mechanically impossible early phase markers from abandon/death noise."""
    start = fight["startTime"]
    clean = dict(markers)
    if clean.get("p2Start") and clean["p2Start"] < start + 120_000:
        clean["p2Start"] = None
    p3_values = [clean.get(key) for key in ("p3Transition", "p25Start", "p25End", "p3Start") if clean.get(key)]
    if p3_values and min(p3_values) < start + 240_000:
        for key in ("p3Transition", "p25Start", "p25End", "p3Start"):
            clean[key] = None
    return clean


def phase_at(timestamp, markers, fight):
    if markers.get("p3Start") and timestamp >= markers["p3Start"]:
        return "P3"
    if markers.get("p25Start") and timestamp >= markers["p25Start"]:
        return "P2.5"
    if markers.get("p3Transition") and timestamp >= markers["p3Transition"]:
        return "P2.5"
    if markers.get("p2Start") and timestamp >= markers["p2Start"]:
        return "P2"
    if markers.get("p15Start") and timestamp >= markers["p15Start"]:
        return "P1.5"
    return "P1"


def fight_phase(markers, fight):
    return phase_at(fight["endTime"], markers, fight)


def primary_wipe_phase(deaths, markers, fight):
    if not deaths:
        return fight_phase(markers, fight)
    clusters = cluster_events(deaths, window_ms=5_000)
    decisive = max(clusters, key=lambda cluster: len(cluster["events"]), default=None)
    if decisive and len(decisive["events"]) >= 2:
        return phase_at(decisive["start"], markers, fight)
    return phase_at(deaths[0].get("timestamp", fight["endTime"]), markers, fight)


def phase_window(markers, fight, phase):
    windows = {
        "P1": (fight["startTime"], markers.get("p15Start") or fight["endTime"]),
        "P1.5": (markers.get("p15Start"), markers.get("p2Start")),
        "P2": (markers.get("p2Start"), markers.get("p25Start") or markers.get("p3Transition")),
        "P2.5": (markers.get("p25Start") or markers.get("p3Transition"), markers.get("p25End") or markers.get("p3Start")),
        "P3": (markers.get("p3Start"), fight["endTime"]),
    }
    return windows.get(phase, (None, None))


def phase_timeline(markers, fight):
    rows = []
    for phase in ["P1", "P1.5", "P2", "P2.5", "P3"]:
        start, end = phase_window(markers, fight, phase)
        if start is None:
            continue
        if end is None:
            end = fight["endTime"]
        if end < start:
            end = start
        rows.append({
            "phase": phase,
            "start": format_time(start - fight["startTime"]),
            "end": format_time(end - fight["startTime"]),
            "startMs": int(start - fight["startTime"]),
            "endMs": int(end - fight["startTime"]),
            "durationMs": int(max(0, end - start)),
        })
    return rows


def death_ability_ids(deaths):
    return {death.get("killingAbilityGameID") for death in deaths if death.get("killingAbilityGameID")}


def is_bridge_death(death):
    return death.get("killingAbilityGameID") in {None, 3}


def bridge_deaths(deaths):
    return [death for death in deaths if is_bridge_death(death)]


def bridge_death_count(deaths):
    return len(bridge_deaths(deaths))


def is_mass_abandon(deaths, bridge_rows):
    if not deaths or not bridge_rows:
        return False
    return len(bridge_rows) >= min(12, max(6, int(len(deaths) * 0.6)))


def is_bridge_cluster_significant(cluster):
    return bool(cluster and len(cluster.get("events", [])) >= 3)


def first_bridge_cluster(deaths):
    bridge_rows = bridge_deaths(deaths)
    clusters = cluster_events(bridge_rows, window_ms=5_000)
    return clusters[0] if clusters else None


def has_prior_real_death(deaths, timestamp):
    return any(
        not is_bridge_death(death) and death.get("timestamp", 0) < timestamp
        for death in deaths
    )


def prior_real_death_count(deaths, timestamp):
    return sum(
        1 for death in deaths
        if not is_bridge_death(death) and death.get("timestamp", 0) < timestamp
    )


def unique_player_death_count_before(deaths, timestamp):
    return len({
        death.get("targetID") for death in deaths
        if death.get("targetID") is not None and death.get("timestamp", 0) < timestamp
    })


def decisive_death_cluster(deaths):
    return max(cluster_events(deaths, window_ms=5_000), key=lambda row: len(row.get("events", [])), default=None)


def is_abandon_after_losses(deaths, bridge_cluster):
    if not bridge_cluster:
        return False
    return len(bridge_cluster.get("events", [])) >= 2 and prior_real_death_count(deaths, bridge_cluster["start"]) >= 4


def first_gravity_collapse_cluster(deaths):
    gravity_deaths = [death for death in deaths if death.get("killingAbilityGameID") == P3_LINE_DEATH_ID]
    for cluster in cluster_events(gravity_deaths, window_ms=1_500):
        if len(cluster["events"]) > 2:
            return cluster
    return None


def classify_fight(fight, deaths, markers, buffs):
    phase = primary_wipe_phase(deaths, markers, fight)
    death_ids = death_ability_ids(deaths)
    duration = fight["endTime"] - fight["startTime"]
    phase_deaths = [death for death in deaths if phase_at(death.get("timestamp", 0), markers, fight) == phase]
    if phase == "P1.5":
        pull_deaths = [death for death in phase_deaths if death.get("killingAbilityGameID") in P15_AVOIDABLE_IDS]
    else:
        pull_deaths = [death for death in phase_deaths if death.get("killingAbilityGameID") in PULL_DEATH_IDS]
    shadow_deaths = [death for death in phase_deaths if death.get("killingAbilityGameID") in SHADOW_AOE_IDS]
    tank_deaths = [death for death in phase_deaths[:3] if death.get("killingAbilityGameID") in TANK_DEATH_IDS]
    phase_bridge_deaths = bridge_deaths(phase_deaths)
    bridge_cluster = first_bridge_cluster(deaths)
    bridge_cluster_phase = phase_at(bridge_cluster["start"], markers, fight) if bridge_cluster else phase
    enrage_events = [event for event in buffs if ability_id(event) in ENRAGE_IDS and event_is_apply(event)]
    rage_events = [event for event in buffs if ability_id(event) == RAGE_STACK_ID and event_is_apply(event)]
    gravity_deaths = [death for death in deaths if death.get("killingAbilityGameID") == P3_LINE_DEATH_ID]
    cosmic_barrier_deaths = [death for death in phase_deaths if death.get("killingAbilityGameID") == COSMIC_BARRIER_ID]
    decisive_cluster = decisive_death_cluster(deaths)
    prior_unique_deaths = unique_player_death_count_before(deaths, decisive_cluster["start"]) if decisive_cluster else 0
    gravity_cluster = first_gravity_collapse_cluster(deaths)

    if fight.get("kill"):
        return {"key": "kill", "phase": "已击杀", "label": "已击杀"}
    if gravity_cluster:
        gravity_prior_deaths = unique_player_death_count_before(deaths, gravity_cluster["start"])
        if gravity_prior_deaths <= 3:
            return {"key": "p3_line_aoe", "phase": "P3", "label": "P3 拉线 AoE 崩溃"}
        return {"key": "prior_attrition_collapse", "phase": "P3", "label": "P3 前置减员过多后团队崩溃"}
    if COSMIC_DEVOUR_ID in death_ids:
        return {"key": "p3_boss_enrage", "phase": "P3", "label": "奥蕾莉亚狂暴"}

    if phase == "P1":
        if is_mass_abandon(deaths, bridge_deaths(deaths)):
            return {"key": "phase_abandon", "phase": "P1", "label": "P1 放弃/add"}
        if rage_events and duration < P1_RAGE_LIMIT_MS:
            return {"key": "p1_add_rage", "phase": "P1", "label": "P1 大怪狂暴"}
        if tank_deaths:
            return {"key": "tank_death", "phase": "P1", "label": "P1 倒坦"}
        return {"key": "p1_team_collapse", "phase": "P1", "label": "P1 团队减员过多"}

    if phase == "P1.5":
        if is_mass_abandon(deaths, phase_bridge_deaths):
            return {"key": "phase_abandon", "phase": "P1.5", "label": "P1.5 坠崖"}
        if len(pull_deaths) >= 2:
            return {"key": "p15_pull_deaths", "phase": "P1.5", "label": "P1.5 过多玩家死于拉弓 / 跑位"}
        return {"key": "p15_team_collapse", "phase": "P1.5", "label": "P1.5 减员过多"}

    if phase in {"P2", "P2.5"}:
        if bridge_cluster_phase in {"P2", "P2.5", "P3"} and is_abandon_after_losses(deaths, bridge_cluster):
            prior_p2_real = [
                death for death in deaths
                if death.get("timestamp", 0) < bridge_cluster["start"]
                and phase_at(death.get("timestamp", 0), markers, fight) == "P2"
                and not is_bridge_death(death)
            ]
            label = (
                "P1.5 减员过多，进入 P2 后放弃"
                if bridge_cluster_phase == "P2" and not prior_p2_real
                else f"{bridge_cluster_phase} 团队减员后放弃"
            )
            cause_phase = "P1.5" if bridge_cluster_phase == "P2" and not prior_p2_real else bridge_cluster_phase
            return {"key": "phase_abandon", "phase": cause_phase, "label": label}
        if len(cosmic_barrier_deaths) >= max(2, int(len(phase_deaths) * 0.6)):
            return {"key": "p2_phantom_barrier", "phase": phase, "label": f"{phase} 宇宙屏障狂暴（裂隙幻影未及时击杀）"}
        if phase == "P2.5" and phase_bridge_deaths:
            if is_mass_abandon(deaths, phase_bridge_deaths):
                return {"key": "phase_abandon", "phase": "P2.5", "label": "P2.5 坠崖"}
            return {"key": "p25_knockback", "phase": "P2.5", "label": "P2.5 转阶段击飞"}
        if is_bridge_cluster_significant(bridge_cluster) and phase == "P2" and phase_at(bridge_cluster["start"], markers, fight) == "P2":
            if is_mass_abandon(deaths, bridge_cluster["events"]) or has_prior_real_death(deaths, bridge_cluster["start"]):
                return {"key": "phase_abandon", "phase": "P2", "label": "P2 坠崖"}
            return {"key": "phase_bridge_mistake", "phase": "P2", "label": "P2 过桥 / 坠崖"}
        if len(pull_deaths) >= 2:
            return {"key": "p2_pull_deaths", "phase": phase, "label": f"{phase} 过多玩家死于拉弓"}
        if shadow_deaths:
            return {"key": "p2_shadow_aoe", "phase": phase, "label": "银色幻影过多团血崩溃"}
        if tank_deaths:
            return {"key": "tank_death", "phase": phase, "label": f"{phase} 倒坦"}
        return {"key": "p2_aoe_collapse", "phase": phase, "label": f"{phase} 常规 AoE 团血崩溃"}

    if phase == "P3":
        if prior_unique_deaths >= 4:
            return {"key": "prior_attrition_collapse", "phase": "P3", "label": "P3 前置减员过多后团队崩溃"}
        if bridge_cluster_phase == "P3" and is_abandon_after_losses(deaths, bridge_cluster):
            return {"key": "phase_abandon", "phase": "P3", "label": "P3 坠崖"}
        if is_bridge_cluster_significant(bridge_cluster) and phase_at(bridge_cluster["start"], markers, fight) == "P3":
            if is_mass_abandon(deaths, bridge_cluster["events"]) or has_prior_real_death(deaths, bridge_cluster["start"]):
                return {"key": "phase_abandon", "phase": "P3", "label": "P3 坠崖"}
            return {"key": "phase_bridge_mistake", "phase": "P3", "label": "P3 过桥 / 坠崖"}
        if len(pull_deaths) >= 2:
            return {"key": "p3_pull_deaths", "phase": "P3", "label": "P3 过多玩家死于拉弓"}
        if enrage_events:
            return {"key": "p3_add_enrage", "phase": "P3", "label": "P3 大怪狂暴"}
        return {"key": "p3_aoe_collapse", "phase": "P3", "label": "P3 常规 AoE 崩溃"}

    return {"key": "unknown", "phase": phase, "label": "未知归因"}


def detail_spell_plan(classification, deaths):
    key = classification["key"]
    damage_ids = set()
    debuff_ids = set()
    buff_ids = set()
    cast_ids = set()
    damage_ids |= AVOIDABLE_DAMAGE_IDS

    if key == "kill":
        debuff_ids |= {
            P1_SHADOW_BINDING_ID,
            CORRUPTION_ID,
            SILVER_ARROW_MARK_ID,
            VOID_GRASP_ID,
            RANGER_MARK_ID,
            VOID_REPULSION_DEBUFF_ID,
            GRAVITY_COLLAPSE_DEBUFF_ID,
            TERMINAL_GUARD_DEBUFF_ID,
        }
        buff_ids |= {P1_SHADOW_BINDING_ID, RAGE_STACK_ID, COSMIC_RADIATION_BUFF_ID, COSMIC_BARRIER_ID} | ENRAGE_IDS
        damage_ids |= {
            SILVER_ARROW_DAMAGE_ID,
            COLLAPSING_VOID_ID,
            VOID_REPULSION_DAMAGE_ID,
            SILVER_RICOCHET_ID,
            COSMIC_RADIATION_DAMAGE_ID,
            COSMIC_DEVOUR_ID,
            P3_LINE_DEATH_ID,
            1242553,
        }
        cast_ids |= {PORTAL_CAST_ID}

    if classification["phase"] == "P1" or key in {"p1_add_rage", "p1_team_collapse"}:
        debuff_ids |= {P1_SHADOW_BINDING_ID, CORRUPTION_ID, SILVER_ARROW_MARK_ID, VOID_GRASP_ID, SILVER_RESIDUE_ID, VOID_REPULSION_DEBUFF_ID}
        buff_ids |= {P1_SHADOW_BINDING_ID, RAGE_STACK_ID, SILVER_RESIDUE_ID}
        damage_ids |= {1233649, 1255378, 1281707, VOID_REPULSION_DAMAGE_ID, 1242553}

    if key in {"p15_pull_deaths", "p15_team_collapse"}:
        damage_ids |= P15_AVOIDABLE_IDS | {1234570, 1255378}

    if classification["phase"] in {"P2", "P2.5"} or key.startswith("p2"):
        debuff_ids |= {VOID_GRASP_ID, RANGER_MARK_ID, VOID_REPULSION_DEBUFF_ID, RIFT_SLASH_ID}
        damage_ids |= {COLLAPSING_VOID_ID, VOID_REPULSION_DAMAGE_ID, 1242553, SILVER_RICOCHET_ID}
        buff_ids |= {COSMIC_RADIATION_BUFF_ID, COSMIC_BARRIER_ID}

    if classification["phase"] == "P3" or key.startswith("p3"):
        debuff_ids |= {VOID_GRASP_ID, GRAVITY_COLLAPSE_DEBUFF_ID, TERMINAL_GUARD_DEBUFF_ID, RANGER_MARK_ID, VOID_REPULSION_DEBUFF_ID}
        damage_ids |= {COLLAPSING_VOID_ID, P3_LINE_DEATH_ID, COSMIC_RADIATION_DAMAGE_ID, COSMIC_DEVOUR_ID, VOID_REPULSION_DAMAGE_ID, 1242553}
        buff_ids |= ENRAGE_IDS | {COSMIC_RADIATION_BUFF_ID}
        cast_ids |= {PORTAL_CAST_ID}

    # 裂隙挥砍换坦审计属于全场固定明细，即使灭团主因不在P2也要读取。
    debuff_ids.add(RIFT_SLASH_ID)

    if any(death.get("killingAbilityGameID") == 1233649 for death in deaths):
        debuff_ids.add(SILVER_ARROW_MARK_ID)
        damage_ids.add(1233649)

    if any(death.get("killingAbilityGameID") == COLLAPSING_VOID_ID for death in deaths):
        debuff_ids.add(VOID_GRASP_ID)
        damage_ids.add(COLLAPSING_VOID_ID)

    if any(death.get("killingAbilityGameID") == P3_LINE_DEATH_ID for death in deaths):
        debuff_ids.add(GRAVITY_COLLAPSE_DEBUFF_ID)
        debuff_ids.add(TERMINAL_GUARD_DEBUFF_ID)
        damage_ids.add(P3_LINE_DEATH_ID)

    if any(death.get("killingAbilityGameID") in TANK_DEATH_IDS for death in deaths[:3]):
        damage_ids |= P1_TANK_IDS | P2_TANK_IDS | P3_TANK_IDS
        buff_ids.add(RAGE_STACK_ID)

    if VOID_REPULSION_DEBUFF_ID in debuff_ids:
        cast_ids.add(VOID_REPULSION_CAST_ID)

    return {
        "damage": damage_ids,
        "debuffs": debuff_ids,
        "buffs": buff_ids,
        "casts": cast_ids,
    }


def nearest_expected_arrow(elapsed_ms):
    return min(P1_EXPECTED_ARROW_MS, key=lambda item: abs(item - elapsed_ms))


def expected_arrow_target(expected):
    return P1_ARROW_TARGETS.get(expected, "目标大怪")


def is_melurium_actor(row):
    if not row:
        return False
    if row.get("gameID") in MELURIUM_GAME_IDS:
        return True
    name = str(row.get("name") or "")
    return "殁里乌姆" in name or "Mawrius" in name or "Morium" in name


def melurium_alive_in_arrow_snapshot(arrow):
    """Whether 殁里乌姆 is still present in the silver-arrow snapshot (alive)."""
    rows = list((arrow.get("snapshot") or {}).get("bosses") or [])
    rows.extend(arrow.get("actors") or [])
    return any(is_melurium_actor(row) for row in rows)


def is_melurium_arrow_slot(expected_ms, arrow=None):
    if expected_ms == MELURIUM_EXPECTED_MS or expected_arrow_target(expected_ms) == "殁里乌姆":
        return True
    if arrow and abs(int(arrow.get("timeMs") or 0) - MELURIUM_EXPECTED_MS) <= P1_EXPECTED_TOLERANCE_MS:
        return True
    return False


def p1_arrow_rows_confirm_hit(p1_arrow_rows, expected_target, arrow=None):
    """True when analyze_p1_arrows already recorded a successful clear for this expected slot.

    Used as a court fallback when fieldAudit geometric / ±2.5s-around-mark-remove evidence
    is empty (binding often drops near mark apply, seconds before mark remove).
    """
    if not expected_target:
        return False
    marked = {name for name in (arrow or {}).get("markedPlayers") or [] if name}
    for row in p1_arrow_rows or []:
        if row.get("kind") not in {"binding_removed", "silver_residue", "field_audit_boss_hit"}:
            continue
        target = str(row.get("target") or "")
        if expected_target not in target and target not in expected_target:
            continue
        row_players = {player.get("name") for player in (row.get("markedPlayers") or []) if player.get("name")}
        if marked and row_players and marked.isdisjoint(row_players):
            continue
        return True
    return False


def event_target_name(actor_map, event):
    return actor(actor_map, event.get("targetID"))


def event_hits_expected_target(actor_map, event, expected):
    target_name = event_target_name(actor_map, event)
    expected_name = expected_arrow_target(expected)
    return expected_name in target_name or target_name in expected_name


def is_boss_binding_target(actor_map, event):
    target_name = event_target_name(actor_map, event)
    return any(name in target_name or target_name in name for name in P1_ARROW_TARGETS.values())


def silver_arrow_mark_clusters(fight, actor_map, debuffs, markers):
    marks = [
        event for event in debuffs
        if ability_id(event) == SILVER_ARROW_MARK_ID
        and event_is_apply(event)
        and phase_at(event.get("timestamp", 0), markers, fight) == "P1"
    ]
    clusters = []
    for cluster in cluster_events(marks, window_ms=2_500):
        players = []
        seen = set()
        for event in sorted(cluster["events"], key=lambda item: item.get("timestamp", 0)):
            target_id = event.get("targetID")
            if target_id in seen:
                continue
            seen.add(target_id)
            players.append({
                "id": target_id,
                "name": actor(actor_map, target_id),
                "timestamp": event.get("timestamp", 0),
            })
        if players:
            clusters.append({
                "start": cluster["start"],
                "end": cluster["end"],
                "players": players[:2],
            })
    return clusters


def nearest_arrow_mark_cluster(mark_clusters, timestamp):
    if not mark_clusters:
        return None
    candidates = [
        cluster for cluster in mark_clusters
        if abs(cluster["start"] - timestamp) <= 8_000 or 0 <= timestamp - cluster["start"] <= 12_000
    ]
    if not candidates:
        candidates = mark_clusters
    return min(candidates, key=lambda cluster: abs(cluster["start"] - timestamp))


def arrow_mark_names(mark_cluster):
    if not mark_cluster:
        return "未识别"
    return ",".join(player["name"] for player in mark_cluster.get("players", []) if player.get("name")) or "未识别"


def arrow_mark_names_with_ids(mark_cluster):
    if not mark_cluster:
        return "未识别"
    rows = [
        f"{player['name']}({player['id']})"
        for player in mark_cluster.get("players", [])
        if player.get("id") is not None
    ]
    return ",".join(rows) if rows else arrow_mark_names(mark_cluster)


def is_marked_by_arrow(target_id, mark_cluster):
    return bool(mark_cluster and target_id in {player.get("id") for player in mark_cluster.get("players", [])})


def debuff_stack_before(events, target_id, timestamp, window_ms=30_000):
    candidates = [
        event for event in events
        if event.get("targetID") == target_id
        and event.get("timestamp", 0) <= timestamp
        and timestamp - event.get("timestamp", 0) <= window_ms
    ]
    stacks = []
    for event in candidates:
        try:
            stacks.append(int(event.get("stack") or event.get("stacks") or 0))
        except (TypeError, ValueError):
            continue
    return max(stacks, default=0)


def analyze_p1_arrows(fight, actor_map, buffs, debuffs, damage_events, markers):
    mark_clusters = silver_arrow_mark_clusters(fight, actor_map, debuffs, markers)
    binding_removes = [
        event for event in buffs + debuffs
        if ability_id(event) == P1_SHADOW_BINDING_ID
        and event_is_remove(event)
        and phase_at(event.get("timestamp", 0), markers, fight) == "P1"
    ]
    residue_applies = [
        event for event in buffs + debuffs
        if ability_id(event) == SILVER_RESIDUE_ID and event_is_apply(event)
    ]
    corruption_removes = [
        event for event in debuffs
        if ability_id(event) == CORRUPTION_ID and event_is_remove(event)
    ]
    corruption_events = [
        event for event in debuffs
        if ability_id(event) == CORRUPTION_ID
    ]
    issues = []
    rows = []
    claimed_binding_removes = set()
    duration = fight["endTime"] - fight["startTime"]
    for expected in P1_EXPECTED_ARROW_MS:
        if duration < expected - P1_EXPECTED_TOLERANCE_MS:
            continue
        expected_timestamp = fight["startTime"] + expected
        mark_cluster = nearest_arrow_mark_cluster(mark_clusters, expected_timestamp)
        if not mark_cluster or abs(mark_cluster["start"] - expected_timestamp) > 8_000:
            issues.append({
                "time": format_time(expected),
                "positionMs": expected,
                "type": "missing_arrow_mark",
                "expectedTarget": expected_arrow_target(expected),
                "text": f"{format_time(expected)} 预期银锋箭应处理 {expected_arrow_target(expected)}，但未识别到本轮银锋箭点名。",
            })
            continue
        window_start = mark_cluster["start"] - 1_000
        window_end = mark_cluster["start"] + 12_000
        binding_hits = [
            event for event in binding_removes
            if window_start <= event.get("timestamp", 0) <= window_end
            and event_hits_expected_target(actor_map, event, expected)
        ]
        wrong_binding_hits = [
            event for event in binding_removes
            if window_start <= event.get("timestamp", 0) <= window_end
            and is_boss_binding_target(actor_map, event)
            and not event_hits_expected_target(actor_map, event, expected)
        ]
        corruption_hits = [
            event for event in corruption_removes
            if window_start <= event.get("timestamp", 0) <= window_end
            and event_hits_expected_target(actor_map, event, expected)
        ]
        wrong_corruption_hits = [
            event for event in corruption_removes
            if window_start <= event.get("timestamp", 0) <= window_end
            and is_boss_binding_target(actor_map, event)
            and not event_hits_expected_target(actor_map, event, expected)
        ]
        residue_hits = [
            event for event in residue_applies
            if window_start <= event.get("timestamp", 0) <= window_end
            and event_hits_expected_target(actor_map, event, expected)
        ]
        wrong_residue_hits = [
            event for event in residue_applies
            if window_start <= event.get("timestamp", 0) <= window_end
            and is_boss_binding_target(actor_map, event)
            and not event_hits_expected_target(actor_map, event, expected)
        ]
        arrow_hits = [
            event for event in damage_events
            if ability_id(event) == SILVER_ARROW_DAMAGE_ID
            and window_start <= event.get("timestamp", 0) <= window_end
            and event_hits_expected_target(actor_map, event, expected)
        ]
        correct_target_hit = binding_hits or residue_hits or corruption_hits or arrow_hits
        wrong_target_hit = (wrong_binding_hits or wrong_residue_hits or wrong_corruption_hits)
        if wrong_target_hit and not correct_target_hit:
            wrong = wrong_target_hit[0]
            issues.append({
                "time": format_time(fight_elapsed(wrong, fight)),
                "positionMs": fight_elapsed(wrong, fight),
                "type": "wrong_expected_arrow_target",
                "expectedTarget": expected_arrow_target(expected),
                "actualTarget": event_target_name(actor_map, wrong),
                "markedPlayers": mark_cluster.get("players", []) if mark_cluster else [],
                "text": f"预期银锋箭应命中 {expected_arrow_target(expected)}，但本轮清除了 {event_target_name(actor_map, wrong)} 的幽影束缚，本轮银锋箭点名为 {arrow_mark_names(mark_cluster)}。",
            })
            continue
        if not binding_hits and not residue_hits:
            if corruption_hits or arrow_hits:
                issues.append({
                    "time": format_time(expected),
                    "kind": "arrow_damage_only",
                    "type": "missing_binding_remove",
                    "target": expected_arrow_target(expected),
                    "expectedTime": format_time(expected),
                    "markedPlayers": mark_cluster.get("players", []) if mark_cluster else [],
                    "text": f"{format_time(expected)} 只识别到银锋箭/腐化精华相关记录，未识别到 {expected_arrow_target(expected)} 的幽影束缚移除；本轮点名为 {arrow_mark_names(mark_cluster)}。",
                })
            else:
                issues.append({
                    "time": format_time(expected),
                    "positionMs": expected,
                    "type": "missing_binding_remove",
                    "target": expected_arrow_target(expected),
                    "expectedTime": format_time(expected),
                    "markedPlayers": mark_cluster.get("players", []) if mark_cluster else [],
                    "text": f"{format_time(expected)} 预期银锋箭应处理 {expected_arrow_target(expected)}，但未识别到幽影束缚移除或腐化精华移除；本轮点名为 {arrow_mark_names(mark_cluster)}。",
                })
            continue
        hit = binding_hits[0] if binding_hits else residue_hits[0]
        evidence_label = "幽影束缚移除" if binding_hits else "银色残渣获得"
        if not binding_hits:
            rows.append({
                "time": format_time(fight_elapsed(hit, fight)),
                "kind": "silver_residue",
                "target": event_target_name(actor_map, hit),
                "expectedTime": format_time(expected),
                "markedPlayers": mark_cluster.get("players", []) if mark_cluster else [],
                "text": f"{event_target_name(actor_map, hit)} 通过银色残渣获得记录判定本轮已处理，本轮点名为 {arrow_mark_names(mark_cluster)}。",
            })
            continue
        hit = binding_hits[0]
        target = event_target_name(actor_map, hit)
        nearby_corruption = [
            event for event in corruption_removes
            if abs(event.get("timestamp", 0) - hit.get("timestamp", 0)) <= 1_500
            and event_hits_expected_target(actor_map, event, expected)
        ]
        stack = max((int(event.get("stack") or event.get("stacks") or 0) for event in nearby_corruption), default=0)
        if stack == 0 and nearby_corruption:
            stack = max(
                (
                    debuff_stack_before(corruption_events, event.get("targetID"), event.get("timestamp", 0))
                    for event in nearby_corruption
                ),
                default=0,
            )
        claimed_binding_removes.add(id(hit))
        rows.append({
            "time": format_time(fight_elapsed(hit, fight)),
            "kind": "binding_removed",
            "target": target,
            "stack": stack,
            "expectedTime": format_time(expected),
            "markedPlayers": mark_cluster.get("players", []) if mark_cluster else [],
            "text": f"{target} 银锋箭判定成功：{evidence_label}，本轮点名为 {arrow_mark_names(mark_cluster)}，腐化精华约 {stack} 层",
        })
    for hit in binding_removes:
        if id(hit) in claimed_binding_removes:
            continue
        elapsed = fight_elapsed(hit, fight)
        expected = nearest_expected_arrow(elapsed)
        if abs(elapsed - expected) > P1_EXPECTED_TOLERANCE_MS:
            issues.append({
                "time": format_time(elapsed),
                "positionMs": elapsed,
                "type": "unexpected_arrow",
                "text": f"{format_time(elapsed)} 非预期时间移除 {actor(actor_map, hit.get('targetID'))} 的幽影束缚",
            })
    return rows, issues


def attribute_debuff_fade(damage_or_death, debuffs, fight, actor_map, ability_id_filter, window_ms=1_500):
    timestamp = damage_or_death.get("timestamp", 0)
    exact_fades = [
        event for event in debuffs
        if ability_id(event) == ability_id_filter
        and event_is_remove(event)
        and abs(event.get("timestamp", 0) - timestamp) <= window_ms
    ]
    if exact_fades:
        event = min(exact_fades, key=lambda item: abs(item.get("timestamp", 0) - timestamp))
        return {
            "time": format_time(fight_elapsed(event, fight)),
            "player": actor(actor_map, event.get("targetID")),
            "targetID": event.get("targetID"),
            "timestamp": event.get("timestamp", 0),
        }

    previous_fades = [
        event for event in debuffs
        if ability_id(event) == ability_id_filter
        and event_is_remove(event)
        and 0 <= timestamp - event.get("timestamp", 0) <= 12_000
    ]
    if previous_fades:
        event = max(previous_fades, key=lambda item: item.get("timestamp", 0))
        return {
            "time": format_time(fight_elapsed(event, fight)),
            "player": actor(actor_map, event.get("targetID")),
            "targetID": event.get("targetID"),
            "timestamp": event.get("timestamp", 0),
        }

    previous_applies = [
        event for event in debuffs
        if ability_id(event) == ability_id_filter
        and event_is_apply(event)
        and 0 <= timestamp - event.get("timestamp", 0) <= 12_000
    ]
    if not previous_applies:
        return None
    event = max(previous_applies, key=lambda item: item.get("timestamp", 0))
    return {
        "time": format_time(fight_elapsed(event, fight)),
        "player": actor(actor_map, event.get("targetID")),
        "targetID": event.get("targetID"),
        "timestamp": event.get("timestamp", 0),
    }


def analyze_collapsing_void(fight, actor_map, actor_type, deaths, damage_events, debuffs, player_roles=None):
    player_roles = player_roles or {}
    friendly_ids = set(fight.get("friendlyPlayers") or [])
    rows_by_player = defaultdict(lambda: {"name": "", "hitCount": 0, "deathCount": 0, "totalDamage": 0, "events": []})
    death_rows = []
    for death in deaths:
        if death.get("killingAbilityGameID") != COLLAPSING_VOID_ID:
            continue
        source = attribute_debuff_fade(death, debuffs, fight, actor_map, VOID_GRASP_ID, window_ms=2_000)
        source_name = source["player"] if source else "未知点名"
        target = actor(actor_map, death.get("targetID"))
        row = rows_by_player[source_name]
        row["name"] = source_name
        row["spellKey"] = "collapsingVoidFriendlyFire"
        row["spellName"] = "崩裂空无误伤他人"
        source_id = source.get("targetID") if source else None
        source_role = player_roles.get(source_id, "unknown")
        row["role"] = source_role
        row["roles"] = [] if source_role == "unknown" else [source_role]
        row["deathCount"] += 1
        row["hitCount"] += 1
        row["events"].append({
            "time": format_time(fight_elapsed(death, fight)),
            "positionMs": int(fight_elapsed(death, fight)),
            "target": target,
            "source": source_name,
            "ability": "崩裂空无",
            "counted": source is not None,
            "countReason": "伤害来源可对应到空虚之握移除玩家" if source else "无法确定射线来源，不计数",
        })
        death_rows.append(f"{format_time(fight_elapsed(death, fight))} {target} 死于 {source_name} 的崩裂空无")

    for event in damage_events:
        if ability_id(event) != COLLAPSING_VOID_ID:
            continue
        target_id = event.get("targetID")
        if friendly_ids and target_id not in friendly_ids:
            continue
        if actor_type.get(target_id) != "Player":
            continue
        source = attribute_debuff_fade(event, debuffs, fight, actor_map, VOID_GRASP_ID, window_ms=2_000)
        source_name = source["player"] if source else "未知点名"
        row = rows_by_player[source_name]
        row["name"] = source_name
        row["spellKey"] = "collapsingVoidFriendlyFire"
        row["spellName"] = "崩裂空无误伤他人"
        source_id = source.get("targetID") if source else None
        source_role = player_roles.get(source_id, "unknown")
        row["role"] = source_role
        row["roles"] = [] if source_role == "unknown" else [source_role]
        row["hitCount"] += 1
        row["totalDamage"] += event_amount(event)
        row["events"].append({
            "time": format_time(fight_elapsed(event, fight)),
            "positionMs": int(fight_elapsed(event, fight)),
            "target": actor(actor_map, target_id),
            "source": source_name,
            "ability": "崩裂空无",
            "amount": event_amount(event),
            "counted": source is not None,
            "countReason": "伤害来源可对应到空虚之握移除玩家" if source else "无法确定射线来源，不计数",
        })

    return sorted(rows_by_player.values(), key=lambda item: (item["deathCount"], item["hitCount"], item["totalDamage"]), reverse=True), death_rows


def is_phantom_actor(actor_map, actor_game_id, actor_id):
    if str((actor_game_id or {}).get(actor_id)) == str(PHANTOM_GAME_ID):
        return True
    name = actor(actor_map, actor_id).lower()
    return "phantom" in name or "幻影" in name


def phantom_instance_key(event):
    instance = event.get("sourceInstance")
    if instance is None:
        instance = event.get("sourceInstanceID")
    return (event.get("sourceID"), instance)


def phantom_instance_label(event_or_segment):
    instance = event_or_segment.get("sourceInstance")
    if instance is None:
        instance = event_or_segment.get("sourceInstanceID")
    if instance is None:
        return "银色幻影"
    try:
        number = int(instance)
    except (TypeError, ValueError):
        number = instance
    return f"银色幻影{number}"


def phantom_damage_segments(phantom_damage, p2_start=None, p3_transition=None):
    by_instance = defaultdict(list)
    for event in phantom_damage or []:
        ts = event.get("timestamp", 0)
        if p2_start and ts < p2_start:
            continue
        if p3_transition and ts >= p3_transition:
            continue
        by_instance[phantom_instance_key(event)].append(event)

    segments = []
    for (source_id, source_instance), events in by_instance.items():
        ticks = []
        for event in sorted(events, key=lambda item: item.get("timestamp", 0)):
            ts = event.get("timestamp", 0)
            if not ticks or ts - ticks[-1]["time"] > 550:
                ticks.append({"time": ts, "events": [event]})
            else:
                ticks[-1]["events"].append(event)
        for tick in ticks:
            if not segments or segments[-1].get("sourceKey") != (source_id, source_instance) or tick["time"] - segments[-1]["last"] > 3_500:
                segments.append({
                    "sourceID": source_id,
                    "sourceInstance": source_instance,
                    "sourceKey": (source_id, source_instance),
                    "label": phantom_instance_label({"sourceInstance": source_instance}),
                    "first": tick["time"],
                    "last": tick["time"],
                    "ticks": [tick],
                })
            else:
                segments[-1]["last"] = tick["time"]
                segments[-1]["ticks"].append(tick)
    return sorted(segments, key=lambda item: (item["first"], item.get("sourceInstance") or 0))


def analyze_p2_shadow_misses(fight, actor_map, actor_game_id, damage_events, debuffs, markers, phantom_damage=None):
    p2_start = markers.get("p2Start")
    p3_transition = markers.get("p3Transition")
    if not p2_start:
        return []
    segments = phantom_damage_segments(phantom_damage, p2_start, p3_transition)
    fades = [
        event for event in debuffs
        if ability_id(event) == VOID_GRASP_ID
        and event_is_remove(event)
        and event.get("timestamp", 0) >= p2_start
        and (not p3_transition or event.get("timestamp", 0) < p3_transition)
    ]
    fade_clusters = cluster_events(fades, window_ms=2_500)
    misses = []
    if segments:
        reported = set()
        reference_end = min(fight["endTime"], p3_transition or fight["endTime"])
        active_count = sum(1 for segment in segments if segment["first"] <= reference_end and segment["last"] >= reference_end - 3_500)
        if active_count:
            misses.append({
                "time": format_time(reference_end - fight["startTime"]),
                "type": "active_phantom_count",
                "activeCount": active_count,
                "text": f"{format_time(reference_end - fight['startTime'])} 当前场上仍存在 {active_count} 个银色幻影仍在产生伤害记录。",
            })
        for index, cluster in enumerate(fade_clusters, start=1):
            players = unique_event_targets(cluster["events"], actor_map)
            player_names = "、".join(row["player"] for row in players) if players else "未识别"
            window_start = cluster["start"] - 1_000
            window_end = cluster["end"] + 3_500
            candidates = [
                segment for segment in segments
                if segment["sourceKey"] not in reported
                and segment["first"] <= cluster["end"] + 1_000
                and segment["last"] >= window_start
            ]
            for segment in candidates:
                if segment["last"] <= window_end:
                    reported.add(segment["sourceKey"])
                    continue
                reported.add(segment["sourceKey"])
                misses.append({
                    "time": format_time(cluster["start"] - fight["startTime"]),
                    "group": index,
                    "players": [row["player"] for row in players],
                    "phantom": segment["label"],
                    "text": f"{format_time(cluster['start'] - fight['startTime'])} 本轮点名为 {player_names}，{segment['label']} 本轮没有被清理掉。",
                })
        return misses

    if not any(is_phantom_actor(actor_map, actor_game_id, event.get("targetID")) for event in damage_events):
        return []
    for fade in fades:
        ts = fade.get("timestamp", 0)
        hits_shadow = False
        for event in damage_events:
            if ability_id(event) != COLLAPSING_VOID_ID:
                continue
            if abs(event.get("timestamp", 0) - ts) > 1_000:
                continue
            if is_phantom_actor(actor_map, actor_game_id, event.get("targetID")):
                hits_shadow = True
                break
        if not hits_shadow:
            misses.append({
                "time": format_time(fight_elapsed(fade, fight)),
                "player": actor(actor_map, fade.get("targetID")),
                "text": f"{format_time(fight_elapsed(fade, fight))} {actor(actor_map, fade.get('targetID'))} 的崩裂空无未识别到命中银色幻影",
            })
    return misses


def analyze_p2_energy(markers, fight, debuffs, damage_events, energy_events, actor_map, actor_game_id):
    p2_start = markers.get("p2Start")
    p3_transition = markers.get("p3Transition")
    if not p2_start or not p3_transition or p3_transition - p2_start >= P2_EXPECTED_DURATION_MS:
        return []
    fades = [
        event for event in debuffs
        if ability_id(event) == RANGER_MARK_ID and event_is_remove(event) and p2_start <= event.get("timestamp", 0) <= p3_transition
    ]
    clusters = cluster_events(fades, window_ms=900)
    rows = []
    p2_duration = p3_transition - p2_start
    missing_energy = max(0, int(round((P2_EXPECTED_DURATION_MS - p2_duration) / 1000)))
    if missing_energy:
        missing_drains = max(1, (missing_energy + 4) // 5)
        rows.append({
            "time": format_time(p3_transition - fight["startTime"]),
            "missingCount": missing_drains,
            "missingEnergy": missing_energy,
            "counted": False,
            "countReason": "只能确认存在消能缺口，无法归责到具体玩家",
            "text": f"P2 约 {format_time(p2_duration)} 后提前进入宇宙辐射，完整时长应约 02:30；估算少延长 {missing_energy} 秒，约 {missing_drains} 次 -5 能量消除未生效。",
        })
    energy_drains = [
        event for event in (energy_events or [])
        if ability_id(event) == SILVER_RICOCHET_ENERGY_DRAIN_ID
        and event.get("resourceChange", 0) < 0
        and str((actor_game_id or {}).get(event.get("targetID"))) == str(ALLERIA_GAME_ID)
        and p2_start <= event.get("timestamp", 0) <= p3_transition
    ]
    for index, cluster in enumerate(clusters, start=1):
        players = unique_event_targets(cluster["events"], actor_map)
        nearby_drains = [
            event for event in energy_drains
            if cluster["start"] - 500 <= event.get("timestamp", 0) <= cluster["end"] + 2_500
        ]
        player_names = "、".join(row["player"] for row in players) if players else "未识别"
        if len(players) < 2:
            rows.append({
                "time": format_time(cluster["start"] - fight["startTime"]),
                "group": index,
                "missingCount": 2 - len(players),
                "players": [row["player"] for row in players],
                "counted": False,
                "verdictCounted": False,
                "displayOnly": True,
                "countReason": "点名人数不足但无法确定责任玩家",
                "text": f"{format_time(cluster['start'] - fight['startTime'])} 第 {index} 组游侠队长印记消失人数不足：{player_names}",
            })
        elif not nearby_drains:
            rows.append({
                "time": format_time(cluster["start"] - fight["startTime"]),
                "group": index,
                "missingCount": 0,
                "players": [row["player"] for row in players],
                "playerIDs": [row["targetID"] for row in players],
                "counted": False,
                "verdictCounted": False,
                "displayOnly": True,
                "countReason": "消能失误仅展示分析，永远不计数、不进入终审",
                "text": f"{format_time(cluster['start'] - fight['startTime'])} 第 {index} 组游侠队长印记已消失 2 人（{player_names}），但未识别到奥蕾莉亚能量 -5（1259998）",
            })
    return rows


def refine_p2_energy_with_field_audit(rows, field_audit, actor_map):
    if not field_audit:
        return rows
    reverse_actor = {name: actor_id for actor_id, name in actor_map.items()}
    refined = [row for row in rows if not row.get("counted")]
    for arrow in field_audit.get("silverArrows") or []:
        if arrow.get("phase") != "P2":
            continue
        for assignment in arrow.get("sourceAssignments") or []:
            if assignment.get("bossEnergyDrained"):
                continue
            players = list(assignment.get("players") or [])
            if not players:
                continue
            player_text = "、".join(players)
            source_instance = assignment.get("sourceInstance")
            refined.append({
                "time": arrow.get("time"),
                "group": arrow.get("index"),
                "sourceInstance": source_instance,
                "missingCount": 0,
                "players": players,
                "playerIDs": [reverse_actor.get(player) for player in players],
                "counted": False,
                "verdictCounted": False,
                "displayOnly": True,
                "countReason": "消能失误仅展示分析，永远不计数、不进入终审",
                "text": f"{arrow.get('time')} 点名玩家：{player_text}；对应银色幻影 {source_instance or '-'} 未成功消除 Boss 能量",
            })
    return refined if len(refined) > sum(1 for row in rows if not row.get("counted")) else rows


def analyze_ranger_mark_groups(markers, fight, debuffs, phase_name):
    phase_start, phase_end = phase_window(markers, fight, phase_name)
    if phase_start is None:
        return []
    if phase_end is None:
        phase_end = fight["endTime"]
    fades = [
        event for event in debuffs
        if ability_id(event) == RANGER_MARK_ID
        and event_is_remove(event)
        and phase_start <= event.get("timestamp", 0) <= phase_end
    ]
    rows = []
    for index, cluster in enumerate(cluster_events(fades, window_ms=900), start=1):
        players = []
        seen = set()
        for event in cluster["events"]:
            target_id = event.get("targetID")
            if target_id in seen:
                continue
            seen.add(target_id)
            players.append(target_id)
        rows.append({
            "time": format_time(cluster["start"] - fight["startTime"]),
            "group": index,
            "count": len(players),
            "targetIDs": players,
            "text": f"{phase_name} 第 {index} 组游侠队长印记消失 {len(players)} 人",
        })
    return rows


def render_ranger_mark_groups(rows, actor_map, phase_name):
    rendered = []
    for row in rows:
        names = [actor(actor_map, target_id) for target_id in row.get("targetIDs", [])]
        rendered.append({
            **row,
            "players": names,
            "text": f"{row['time']} {phase_name} 第 {row['group']} 组游侠队长印记消失 {row['count']} 人：{('、'.join(names) if names else '未识别')}",
        })
    return rendered


def unique_event_targets(events, actor_map):
    seen = set()
    rows = []
    for event in events:
        target_id = event.get("targetID")
        if target_id in seen:
            continue
        seen.add(target_id)
        rows.append({
            "targetID": target_id,
            "player": actor(actor_map, target_id),
            "timestamp": event.get("timestamp", 0),
        })
    return rows


def gravity_round_at(timestamp, debuffs, fight, actor_map):
    guard_applies = [
        event for event in debuffs
        if ability_id(event) == TERMINAL_GUARD_DEBUFF_ID
        and str(event.get("type", "")).lower() == "applydebuff"
        and -45_000 <= event.get("timestamp", 0) - timestamp <= 2_000
    ]
    guard_clusters = cluster_events(guard_applies, window_ms=4_000)
    guard_cluster = max(
        (
            cluster for cluster in guard_clusters
            if 0 <= timestamp - cluster["start"] <= 15_000
        ),
        key=lambda item: item["start"],
        default=None,
    )
    if guard_cluster:
        round_targets = unique_event_targets(guard_cluster["events"], actor_map)
    else:
        round_targets = []

    collapse_applies = [
        event for event in debuffs
        if ability_id(event) == GRAVITY_COLLAPSE_DEBUFF_ID
        and event_is_apply(event)
        and -20_000 <= event.get("timestamp", 0) - timestamp <= 8_000
    ]
    if not round_targets:
        apply_clusters = cluster_events(collapse_applies, window_ms=4_000)
        containing_clusters = [
            cluster for cluster in apply_clusters
            if cluster["start"] - 1_000 <= timestamp <= cluster["end"] + 1_000
        ]
        round_cluster = max(containing_clusters, key=lambda item: item["end"], default=None)
        if not round_cluster:
            prior_clusters = [cluster for cluster in apply_clusters if cluster["start"] <= timestamp]
            round_cluster = max(prior_clusters, key=lambda item: item["end"], default=None)
        if round_cluster:
            round_targets = unique_event_targets(round_cluster["events"], actor_map)

    target_ids = {row["targetID"] for row in round_targets}
    collapse_apply_triggers = [
        event for event in collapse_applies
        if abs(event.get("timestamp", 0) - timestamp) <= 1_000
    ]
    if target_ids:
        matching_apply_triggers = [event for event in collapse_apply_triggers if event.get("targetID") in target_ids]
        if matching_apply_triggers:
            collapse_apply_triggers = matching_apply_triggers

    guard_removes = [
        event for event in debuffs
        if ability_id(event) == TERMINAL_GUARD_DEBUFF_ID
        and event_is_remove(event)
        and abs(event.get("timestamp", 0) - timestamp) <= 1_500
    ]
    if target_ids:
        matching_guard_removes = [event for event in guard_removes if event.get("targetID") in target_ids]
        if matching_guard_removes:
            guard_removes = matching_guard_removes

    trigger = None
    if collapse_apply_triggers:
        trigger_candidates = sorted(collapse_apply_triggers, key=lambda item: item.get("timestamp", 0))
        trigger = trigger_candidates[-1]
        if len(trigger_candidates) >= 2:
            latest_gap = timestamp - trigger.get("timestamp", 0)
            previous_gap = timestamp - trigger_candidates[-2].get("timestamp", 0)
            if 0 <= latest_gap <= 120 and previous_gap <= 800:
                trigger = trigger_candidates[-2]

    removes = [
        event for event in debuffs
        if ability_id(event) == GRAVITY_COLLAPSE_DEBUFF_ID
        and event_is_remove(event)
        and abs(event.get("timestamp", 0) - timestamp) <= 2_500
    ]
    if target_ids:
        matching_removes = [event for event in removes if event.get("targetID") in target_ids]
        if matching_removes:
            removes = matching_removes
    if not trigger:
        trigger = min(removes, key=lambda item: abs(item.get("timestamp", 0) - timestamp), default=None)
    if not trigger and guard_removes:
        trigger = min(guard_removes, key=lambda item: abs(item.get("timestamp", 0) - timestamp), default=None)
    if not trigger:
        trigger = max(
            (
                event for event in debuffs
                if ability_id(event) == GRAVITY_COLLAPSE_DEBUFF_ID
                and event_is_remove(event)
                and 0 <= timestamp - event.get("timestamp", 0) <= 8_000
            ),
            key=lambda item: item.get("timestamp", 0),
            default=None,
        )
    return {
        "targets": round_targets,
        "trigger": {
            "targetID": trigger.get("targetID"),
            "player": actor(actor_map, trigger.get("targetID")),
            "timestamp": trigger.get("timestamp", 0),
            "time": format_time(fight_elapsed(trigger, fight)),
        } if trigger else None,
    }


def analyze_gravity_attribution(fight, actor_map, deaths, debuffs):
    gravity_deaths = [death for death in deaths if death.get("killingAbilityGameID") == P3_LINE_DEATH_ID]
    rows = []
    for cluster in cluster_events(gravity_deaths, window_ms=1_500):
        if len(cluster["events"]) <= 2:
            continue
        round_info = gravity_round_at(cluster["start"], debuffs, fight, actor_map)
        trigger = round_info["trigger"]
        target_names = [row["player"] for row in round_info["targets"]]
        trigger_name = trigger["player"] if trigger else "未知拉线"
        target_text = "、".join(target_names) if target_names else "未识别"
        rows.append({
            "time": format_time(cluster["start"] - fight["startTime"]),
            "source": trigger_name,
            "deathCount": len(cluster["events"]),
            "markPlayers": target_names,
            "trigger": trigger,
            "players": [actor(actor_map, death.get("targetID")) for death in cluster["events"]],
            "text": f"{format_time(cluster['start'] - fight['startTime'])} 重力坍缩造成 {len(cluster['events'])} 人死亡，本轮点名为 {target_text}，团血崩于{trigger_name}的那次拉线。",
        })
    return rows


def build_board_row(name, spell_key, spell_name, hit_count=0, death_count=0, total_damage=0, events=None, role="unknown"):
    roles = [] if role in {None, "", "unknown"} else [role]
    return {
        "name": name,
        "role": role,
        "roles": roles,
        "spellKey": spell_key,
        "spellName": spell_name,
        "hitCount": hit_count,
        "deathCount": death_count,
        "totalDamage": total_damage,
        "events": events or [],
    }


def display_time_to_ms(value):
    try:
        minutes, seconds = str(value or "0:0").split(":", 1)
        return int(round((int(minutes) * 60 + float(seconds)) * 1_000))
    except (TypeError, ValueError):
        return 0


def event_position_ms(event):
    for key in ("positionMs", "timeMs", "markPositionMs", "fireTimeMs", "applyTimeMs"):
        if event.get(key) is not None:
            try:
                return int(event.get(key))
            except (TypeError, ValueError):
                pass
    return display_time_to_ms(event.get("time") or event.get("deathTime"))


def apply_global_death_exemption(local_board, deaths, fight):
    """Suppress every mistake strictly after the fight's eighth death.

    Suppressed events stay in JSON with an explicit reason so the report can
    show them under “不计数”.  The eighth-death event itself remains eligible;
    only later events are globally exempt.
    """
    ordered_deaths = sorted(deaths or [], key=lambda row: int(row.get("timestamp") or 0))
    cutoff_ms = None
    if len(ordered_deaths) >= GLOBAL_DEATH_EXEMPT_THRESHOLD:
        cutoff_ms = int(ordered_deaths[GLOBAL_DEATH_EXEMPT_THRESHOLD - 1].get("timestamp") or 0) - int(fight["startTime"])
    for skill_key, board_rows in local_board.items():
        for row in board_rows or []:
            events = row.get("events") or []
            row["observedHitCount"] = int(row.get("hitCount") or 0)
            row["observedDeathCount"] = int(row.get("deathCount") or 0)
            for event in events:
                position_ms = event_position_ms(event)
                event.setdefault("positionMs", position_ms)
                if cutoff_ms is None or position_ms <= cutoff_ms:
                    continue
                if event.get("counted") is False and event.get("countReason"):
                    event["mechanicExemptionReason"] = event.get("countReason")
                event["counted"] = False
                event["globalExempt"] = True
                event["globalExemptionReason"] = (
                    f"全局最高优先级豁免：本场第{GLOBAL_DEATH_EXEMPT_THRESHOLD}次死亡发生于"
                    f"{format_time(cutoff_ms)}，该失误发生在其后"
                )
                event["countReason"] = event["globalExemptionReason"]
            if events:
                counted_events = [event for event in events if event.get("counted") is not False]
                display_only_keys = set(AVOIDABLE_DAMAGE_SPELLS) | {"missedEnergy", "interferenceShockInterrupts"}
                if skill_key in display_only_keys:
                    # 仅展示项：保留观察到的次数与伤害；计数字段永远为 0
                    row["hitCount"] = int(row.get("observedHitCount") or len(events))
                    row["countedCount"] = 0
                    row["uncountedCount"] = len(events)
                    if skill_key in set(AVOIDABLE_DAMAGE_SPELLS):
                        row["deathCount"] = 0
                        if any(event.get("amount") is not None for event in events):
                            row["totalDamage"] = sum(int(event.get("amount") or 0) for event in events)
                    continue
                row["hitCount"] = len(counted_events)
                row["countedCount"] = len(counted_events)
                row["uncountedCount"] = len(events) - len(counted_events)
                if skill_key == VORELUTH_VULN_SKILL_KEY:
                    # 每条 event 可能是「一次 fade」或旧版「同场汇总」
                    def _fade_n(event):
                        n = int(event.get("fadeCount") or 0)
                        if n:
                            return n
                        fades = event.get("fades")
                        return len(fades) if isinstance(fades, list) and fades else 1

                    row["hitCount"] = sum(_fade_n(event) for event in counted_events)
                    row["countedCount"] = row["hitCount"]
                    row["uncountedCount"] = sum(
                        _fade_n(event) for event in events if event.get("counted") is False
                    )
                elif skill_key == "collapsingVoidSnapAiming":
                    row["deathCount"] = sum(int(event.get("deathCount") or 0) for event in counted_events)
                elif skill_key == "gravityLineViolation":
                    row["deathCount"] = sum(int(event.get("deathCount") or 0) for event in counted_events)
                elif skill_key in {"p1SilverArrowDeaths", "p15AvoidableDeaths", PASSAGE_CLIFF_SKILL_KEY}:
                    row["deathCount"] = len(counted_events)
                elif skill_key == "tankRiftSlashFailure":
                    row["deathCount"] = sum(1 for event in counted_events if event.get("causedTankDeath"))
                if row.get("totalDamage") and all(event.get("amount") is not None for event in events):
                    row["totalDamage"] = sum(int(event.get("amount") or 0) for event in counted_events)
    return {
        "deathThreshold": GLOBAL_DEATH_EXEMPT_THRESHOLD,
        "deathCount": len(ordered_deaths),
        "cutoffPositionMs": cutoff_ms,
        "cutoffTime": format_time(cutoff_ms) if cutoff_ms is not None else None,
        "reason": (
            f"本场第{GLOBAL_DEATH_EXEMPT_THRESHOLD}次死亡后所有失误均不计数"
            if cutoff_ms is not None else
            f"本场死亡不足{GLOBAL_DEATH_EXEMPT_THRESHOLD}次，不触发全局豁免"
        ),
    }


def analyze_avoidable_damage(fight, actor_map, actor_type, player_roles, damage_events, deaths, markers):
    """Build the display-only Corruption Essence hit counter.

    Per-hit evidence is retained for counted/uncounted court cards, while
    damage and death attribution remain excluded from the final verdict.
    """
    spell_by_id = {row["id"]: (key, row["name"]) for key, row in AVOIDABLE_DAMAGE_SPELLS.items()}
    boards = {key: {} for key in AVOIDABLE_DAMAGE_SPELLS}
    for event in sorted(damage_events or [], key=lambda row: row.get("timestamp", 0)):
        spell_id = ability_id(event)
        spell = spell_by_id.get(spell_id)
        target_id = event.get("targetID")
        if not spell or actor_type.get(target_id) != "Player":
            continue
        key, spell_name = spell
        player = actor(actor_map, target_id)
        role = player_roles.get(target_id, "unknown")
        row = boards[key].setdefault(player, build_board_row(player, key, spell_name, role=role))
        row["hitCount"] += 1
        row["damageText"] = "-"
        position_ms = int(event.get("timestamp", 0) - fight["startTime"])
        row["events"].append({
            "time": format_time(position_ms),
            "positionMs": position_ms,
            "abilityID": spell_id,
            "ability": spell_name,
            "amount": event_amount(event),
            "counted": False,
            "verdictCounted": False,
            "displayOnly": True,
            "hitStatOnly": True,
            "countReason": "腐化精华仅作命中统计，永远不计数、不进入终审",
        })
    return {
        key: sorted(rows.values(), key=lambda row: row["hitCount"], reverse=True)
        for key, rows in boards.items()
    }


def build_snap_aiming_board(field_audit, player_roles, fight_id):
    rows = {}
    for group in (field_audit or {}).get("bowGroups") or []:
        for player in group.get("players") or []:
            name = player.get("player")
            if not name:
                continue
            item = rows.setdefault(
                name,
                build_board_row(
                    name,
                    "collapsingVoidSnapAiming",
                    "崩裂空无甩狙",
                    role=player_roles.get(player.get("targetID"), player.get("mechanicRole", "unknown")),
                ),
            )
            item["markedCount"] = int(item.get("markedCount") or 0) + 1
            if player.get("diedAtFire") or player.get("deathTriggeredRay"):
                item["events"].append({
                    "fightID": fight_id,
                    "phase": group.get("phase"),
                    "group": group.get("index"),
                    "time": player.get("deathTime") or player.get("fadeTime") or group.get("fireTime"),
                    "positionMs": player.get("deathTimeMs") or player.get("fadeTimeMs") or group.get("fireTimeMs"),
                    "players": [],
                    "deathCount": 0,
                    "counted": False,
                    "displayOnly": True,
                    "countReason": player.get("missedPhantomExemptReason")
                    or "崩裂空无结算期间点名玩家死亡（提前结算），仅展示不计数",
                })
                continue
            if not player.get("isSnapAiming"):
                continue
            deaths = player.get("snapAimingDeaths") or []
            item["hitCount"] += 1
            item["deathCount"] += len(deaths)
            item["events"].append({
                "fightID": fight_id,
                "phase": group.get("phase"),
                "group": group.get("index"),
                "time": player.get("fadeTime") or group.get("fireTime"),
                "positionMs": player.get("fadeTimeMs") or group.get("fireTimeMs"),
                "movementYards": player.get("lastSecondMovementYards"),
                "players": [death.get("player") for death in deaths if death.get("player")],
                "deathCount": len(deaths),
                "counted": bool(deaths),
                "countReason": (
                    f"最后1秒移动{float(player.get('lastSecondMovementYards') or 0):.2f}码，甩狙导致{len(deaths)}名队友死亡"
                    if deaths else
                    f"最后1秒移动{float(player.get('lastSecondMovementYards') or 0):.2f}码，判定甩狙；未导致队友死亡，不进入终审"
                ),
            })
    return list(rows.values())


def merge_board(global_board, local_board):
    for key, rows in local_board.items():
        bucket = global_board.setdefault(key, {})
        for row in rows:
            name = row.get("name")
            if not name:
                continue
            spell_name = row.get("spellName") or row.get("spell_name") or key
            merged = bucket.setdefault(name, {
                "name": name,
                "spellKey": row.get("spellKey") or key,
                "spellName": spell_name,
                "role": row.get("role", "unknown"),
                "roles": row.get("roles") or ([] if row.get("role") in {None, "", "unknown"} else [row.get("role")]),
                "hitCount": 0,
                "countedCount": 0,
                "uncountedCount": 0,
                "markedCount": 0,
                "deathCount": 0,
                "totalDamage": 0,
                "damageText": row.get("damageText"),
                "events": [],
                "isNpc": bool(row.get("isNpc")),
                "excludeFromCourtPlayers": bool(row.get("excludeFromCourtPlayers") or row.get("isNpc")),
            })
            merged["isNpc"] = bool(merged.get("isNpc") or row.get("isNpc"))
            merged["excludeFromCourtPlayers"] = bool(
                merged.get("excludeFromCourtPlayers") or row.get("excludeFromCourtPlayers") or row.get("isNpc")
            )
            merged["roles"] = merge_roles(merged.get("roles"), row.get("roles") or ([] if row.get("role") in {None, "", "unknown"} else [row.get("role")]))
            merged["role"] = merged["roles"][0] if merged["roles"] else (row.get("role") or merged.get("role") or "unknown")
            merged["hitCount"] += row.get("hitCount", 0)
            merged["countedCount"] += int(row.get("countedCount", row.get("hitCount") or 0))
            merged["uncountedCount"] += int(row.get("uncountedCount") or 0)
            merged["markedCount"] += row.get("markedCount", 0)
            merged["deathCount"] += row.get("deathCount", 0)
            merged["totalDamage"] += row.get("totalDamage", 0)
            if row.get("damageText"):
                merged["damageText"] = row.get("damageText")
            merged["events"].extend(row.get("events", []))


def silver_arrow_damage_for_death(death, damage_events):
    target_id = death.get("targetID")
    timestamp = death.get("timestamp", 0)
    candidates = [
        event for event in damage_events
        if ability_id(event) == SILVER_ARROW_DAMAGE_ID
        and event.get("targetID") == target_id
        and 0 <= timestamp - event.get("timestamp", 0) <= 1_500
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda event: event_amount(event))


def max_buff_stack_before(events, spell_id, timestamp):
    stacks = []
    for event in events:
        if ability_id(event) != spell_id or event.get("timestamp", 0) > timestamp:
            continue
        try:
            stacks.append(int(event.get("stack") or event.get("stacks") or 0))
        except (TypeError, ValueError):
            continue
    return max(stacks, default=0)


def event_point(event, prefix=""):
    for key in (f"{prefix}position", f"{prefix}Position", f"{prefix}location", f"{prefix}Location"):
        value = event.get(key)
        if isinstance(value, dict):
            try:
                return float(value.get("x") or value.get("X")), float(value.get("y") or value.get("Y"))
            except (TypeError, ValueError):
                continue
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            try:
                return float(value[0]), float(value[1])
            except (TypeError, ValueError):
                continue
    pairs = [
        (f"{prefix}x", f"{prefix}y"),
        (f"{prefix}X", f"{prefix}Y"),
        (f"{prefix}positionX", f"{prefix}positionY"),
        (f"{prefix}PositionX", f"{prefix}PositionY"),
    ]
    for x_key, y_key in pairs:
        if x_key not in event or y_key not in event:
            continue
        try:
            return float(event[x_key]), float(event[y_key])
        except (TypeError, ValueError):
            continue
    return None


def point_distance(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def coordinate_distance_yards(distance):
    return distance / 100


def nearest_actor_position(timestamp, target_id, resource_events, window_ms=8_000, allow_future=True):
    candidates = [
        event for event in resource_events
        if (event.get("targetID") == target_id or event.get("sourceID") == target_id)
        and event_point(event)
        and abs(event.get("timestamp", 0) - timestamp) <= window_ms
        and (allow_future or event.get("timestamp", 0) <= timestamp)
    ]
    if not candidates:
        return None
    if allow_future:
        return min(candidates, key=lambda event: abs(event.get("timestamp", 0) - timestamp))
    return max(candidates, key=lambda event: event.get("timestamp", 0))


def actor_position_at(timestamp, target_id, resource_events, window_ms=10_000):
    rows = sorted(
        (
            event for event in resource_events
            if (event.get("targetID") == target_id or event.get("sourceID") == target_id)
            and event_point(event)
            and abs(event.get("timestamp", 0) - timestamp) <= window_ms
        ),
        key=lambda event: event.get("timestamp", 0),
    )
    if not rows:
        return None
    before = None
    after = None
    for event in rows:
        event_ts = event.get("timestamp", 0)
        if event_ts <= timestamp:
            before = event
        elif event_ts > timestamp:
            after = event
            break
    exact = next((event for event in rows if event.get("timestamp", 0) == timestamp), None)
    if exact:
        x, y = event_point(exact)
        return {
            "timestamp": timestamp,
            "x": x,
            "y": y,
            "sourceRule": "resourceExact",
            "deltaMs": 0,
        }
    if before and after:
        before_point = event_point(before)
        after_point = event_point(after)
        span = after.get("timestamp", 0) - before.get("timestamp", 0)
        ratio = 0 if span <= 0 else (timestamp - before.get("timestamp", 0)) / span
        return {
            "timestamp": timestamp,
            "x": before_point[0] + (after_point[0] - before_point[0]) * ratio,
            "y": before_point[1] + (after_point[1] - before_point[1]) * ratio,
            "sourceRule": "resourceInterpolated",
            "beforeDeltaMs": before.get("timestamp", 0) - timestamp,
            "afterDeltaMs": after.get("timestamp", 0) - timestamp,
        }
    candidate = before or after
    x, y = event_point(candidate)
    return {
        "timestamp": candidate.get("timestamp", 0),
        "x": x,
        "y": y,
        "sourceRule": "resourceBefore" if before else "resourceAfter",
        "deltaMs": candidate.get("timestamp", 0) - timestamp,
    }


def event_facing(event):
    value = event.get("facing")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_facing_radians(raw_facing):
    if raw_facing is None:
        return None
    # WCL position resources in this report encode facing as radians * 100.
    radians = float(raw_facing) / 100.0
    while radians <= -math.pi:
        radians += math.tau
    while radians > math.pi:
        radians -= math.tau
    return radians


def nearest_actor_state(timestamp, actor_id, resource_events, window_ms=2_500):
    candidates = [
        event for event in resource_events
        if (event.get("targetID") == actor_id or event.get("sourceID") == actor_id)
        and event_point(event)
        and abs(event.get("timestamp", 0) - timestamp) <= window_ms
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda event: (
        0 if event_facing(event) is not None else 1,
        abs(event.get("timestamp", 0) - timestamp),
    ))
    event = candidates[0]
    x, y = event_point(event)
    delta = int(event.get("timestamp", 0) - timestamp)
    abs_delta = abs(delta)
    confidence = "high" if abs_delta <= 500 else ("medium" if abs_delta <= 1_500 else "low")
    return {
        "timestamp": event.get("timestamp", 0),
        "deltaMs": delta,
        "confidence": confidence,
        "sourceRule": "nearestEventWithFacing" if event_facing(event) is not None else "nearestEvent",
        "x": x,
        "y": y,
        "rawFacing": event_facing(event),
        "facingRadians": normalize_facing_radians(event_facing(event)),
    }


def confidence_from_delta(delta_ms):
    if delta_ms is None:
        return "unknown"
    delta = abs(int(delta_ms))
    if delta <= 500:
        return "high"
    if delta <= 1_500:
        return "medium"
    return "low"


def project_point(point, angle, distance):
    return (
        point[0] + math.cos(angle) * distance,
        point[1] + math.sin(angle) * distance,
    )


def distance_point_to_segment(point, start, end):
    sx, sy = start
    ex, ey = end
    px, py = point
    dx = ex - sx
    dy = ey - sy
    span = dx * dx + dy * dy
    if span <= 0:
        return point_distance(point, start)
    t = max(0.0, min(1.0, ((px - sx) * dx + (py - sy) * dy) / span))
    closest = (sx + t * dx, sy + t * dy)
    return point_distance(point, closest)


def ray_record(label, origin, angle, length=10_000):
    end = project_point(origin, angle, length)
    obelisk = project_point(origin, angle, 500)
    return {
        "label": label,
        "angleRadians": round(angle, 4),
        "startX": round(origin[0], 2),
        "startY": round(origin[1], 2),
        "endX": round(end[0], 2),
        "endY": round(end[1], 2),
        "obeliskX": round(obelisk[0], 2),
        "obeliskY": round(obelisk[1], 2),
    }


def void_grasp_ray_set(origin, facing_radians):
    if origin is None or facing_radians is None:
        return []
    directions = [
        ("back", facing_radians + math.pi),
        ("leftFront", facing_radians + math.pi / 3),
        ("leftBack", facing_radians - math.pi / 3),
    ]
    return [ray_record(label, origin, angle) for label, angle in directions]


def clean_point(point):
    if not point:
        return None
    return {"x": round(point[0], 2), "y": round(point[1], 2), "yardX": round(point[0] / 100, 2), "yardY": round(point[1] / 100, 2)}


def pair_void_grasp_events(debuffs, start_time=None, end_time=None):
    active = {}
    pairs = []
    for event in sorted(debuffs, key=lambda item: item.get("timestamp", 0)):
        if ability_id(event) != VOID_GRASP_ID:
            continue
        ts = event.get("timestamp", 0)
        if start_time and ts < start_time:
            continue
        if end_time and ts > end_time:
            continue
        target_id = event.get("targetID")
        if event_is_apply(event):
            active[target_id] = event
        elif event_is_remove(event):
            apply_event = active.pop(target_id, None)
            if apply_event:
                pairs.append((apply_event, event))
    return pairs


def analyze_void_grasp_rays(fight, actor_map, actor_type, actor_game_id, debuffs, damage_events, resource_events, markers):
    pairs = pair_void_grasp_events(debuffs, fight["startTime"], fight["endTime"])
    records = []
    for index, (apply_event, remove_event) in enumerate(pairs, start=1):
        target_id = apply_event.get("targetID")
        apply_ts = apply_event.get("timestamp", 0)
        remove_ts = remove_event.get("timestamp", 0)
        state = nearest_actor_state(apply_ts, target_id, resource_events, window_ms=3_000)
        origin = (state["x"], state["y"]) if state else None
        rays = void_grasp_ray_set(origin, state.get("facingRadians") if state else None)
        hit_window_start = remove_ts - 500
        hit_window_end = remove_ts + 2_000
        hits = [
            event for event in damage_events
            if ability_id(event) == COLLAPSING_VOID_ID
            and hit_window_start <= event.get("timestamp", 0) <= hit_window_end
        ]
        hit_rows = []
        phantom_hits = 0
        player_hits = 0
        for event in hits:
            target = event.get("targetID")
            is_phantom = is_phantom_actor(actor_map, actor_game_id, target)
            is_player = actor_type.get(target) == "Player"
            if is_phantom:
                phantom_hits += 1
            if is_player:
                player_hits += 1
            point = event_point(event, "target") or event_point(event)
            nearest_ray = None
            if point and rays:
                distances = [
                    (ray["label"], distance_point_to_segment(point, (ray["startX"], ray["startY"]), (ray["endX"], ray["endY"])))
                    for ray in rays
                ]
                label, distance = min(distances, key=lambda item: item[1])
                nearest_ray = {"label": label, "distanceYards": round(coordinate_distance_yards(distance), 1)}
            hit_rows.append({
                "time": format_time(event.get("timestamp", 0) - fight["startTime"]),
                "positionMs": int(event.get("timestamp", 0) - fight["startTime"]),
                "target": actor(actor_map, target),
                "targetID": target,
                "targetType": "phantom" if is_phantom else ("player" if is_player else actor_type.get(target, "unknown")),
                "amount": event_amount(event),
                "point": clean_point(point),
                "nearestRay": nearest_ray,
            })
        records.append({
            "index": index,
            "phase": phase_at(apply_ts, markers, fight),
            "player": actor(actor_map, target_id),
            "targetID": target_id,
            "applyTime": format_time(apply_ts - fight["startTime"]),
            "fireTime": format_time(remove_ts - fight["startTime"]),
            "positionMs": int(remove_ts - fight["startTime"]),
            "durationMs": int(remove_ts - apply_ts),
            "state": {
                "time": format_time(state["timestamp"] - fight["startTime"]) if state else None,
                "deltaMs": state.get("deltaMs") if state else None,
                "confidence": state.get("confidence") if state else "unknown",
                "sourceRule": state.get("sourceRule") if state else "missing",
                "point": clean_point(origin),
                "facingRaw": round(state["rawFacing"], 2) if state and state.get("rawFacing") is not None else None,
                "facingRadians": round(state["facingRadians"], 4) if state and state.get("facingRadians") is not None else None,
            },
            "rays": rays,
            "hits": hit_rows,
            "phantomHits": phantom_hits,
            "playerHits": player_hits,
            "status": "friendly_fire" if player_hits else ("hit_phantom" if phantom_hits else "no_hit"),
            "text": f"{format_time(remove_ts - fight['startTime'])} {actor(actor_map, target_id)} 崩裂空无：命中幻影 {phantom_hits} 次，误伤玩家 {player_hits} 次，坐标置信度 {state.get('confidence') if state else 'unknown'}。",
        })
    return records


def marked_player_id_set(row):
    return {player.get("id") for player in row.get("markedPlayers", []) if player.get("id") is not None}


def analyze_p1_arrow_audit(fight, actor_map, debuffs, damage_events, markers, resolved_rows=None):
    clusters = silver_arrow_mark_clusters(fight, actor_map, debuffs, markers)
    rows = []
    for index, cluster in enumerate(clusters, start=1):
        start = cluster["start"]
        window_end = start + 12_000
        hits = [
            event for event in damage_events
            if ability_id(event) == SILVER_ARROW_DAMAGE_ID
            and start - 1_000 <= event.get("timestamp", 0) <= window_end
        ]
        boss_hits = [event for event in hits if is_boss_binding_target(actor_map, event)]
        player_hits = [event for event in hits if event.get("targetID") in {player.get("id") for player in cluster.get("players", [])}]
        source_ids = sorted({
            event.get("sourceID")
            for event in hits
            if event.get("sourceID") in {player.get("id") for player in cluster.get("players", [])}
        })
        expected = nearest_expected_arrow(start - fight["startTime"])
        rows.append({
            "index": index,
            "phase": "P1",
            "time": format_time(start - fight["startTime"]),
            "positionMs": int(start - fight["startTime"]),
            "expectedTime": format_time(expected),
            "expectedTarget": expected_arrow_target(expected),
            "markedPlayers": cluster.get("players", []),
            "shotPlayers": [{"id": player_id, "name": actor(actor_map, player_id)} for player_id in source_ids],
            "bossHits": [
                {
                    "time": format_time(event.get("timestamp", 0) - fight["startTime"]),
                    "target": event_target_name(actor_map, event),
                    "source": actor(actor_map, event.get("sourceID")),
                    "amount": event_amount(event),
                }
                for event in boss_hits
            ],
            "friendlyHits": [
                {
                    "time": format_time(event.get("timestamp", 0) - fight["startTime"]),
                    "target": event_target_name(actor_map, event),
                    "source": actor(actor_map, event.get("sourceID")),
                    "amount": event_amount(event),
                }
                for event in player_hits
            ],
            "status": "hit_boss" if boss_hits else ("hit_player_only" if player_hits else "no_damage_hit"),
            "text": f"P1 第 {index} 轮银锋箭：点名 {arrow_mark_names(cluster)}，命中 Boss/add {len(boss_hits)} 次，误伤点名玩家 {len(player_hits)} 次。",
        })
    for resolved in resolved_rows or []:
        if resolved.get("kind") not in {"binding_removed", "silver_residue"}:
            continue
        resolved_ids = marked_player_id_set(resolved)
        match = next((row for row in rows if resolved_ids and marked_player_id_set(row) == resolved_ids), None)
        if not match:
            match = {
                "index": len(rows) + 1,
                "phase": "P1",
                "time": resolved.get("time"),
                "positionMs": 0,
                "expectedTime": resolved.get("expectedTime"),
                "expectedTarget": resolved.get("target"),
                "markedPlayers": resolved.get("markedPlayers") or [],
                "shotPlayers": resolved.get("markedPlayers") or [],
                "bossHits": [],
                "friendlyHits": [],
            }
            rows.append(match)
        match["status"] = "removed_boss_buff"
        match["resolvedTarget"] = resolved.get("target")
        match["resolvedKind"] = resolved.get("kind")
        match["resolvedStack"] = resolved.get("stack")
        match["shotPlayers"] = resolved.get("markedPlayers") or match.get("shotPlayers") or []
        match["bossHits"] = [{
            "time": resolved.get("time"),
            "target": resolved.get("target"),
            "source": arrow_mark_names({"players": resolved.get("markedPlayers") or []}),
            "amount": 0,
            "evidence": resolved.get("kind"),
        }]
        match["text"] = resolved.get("text") or match.get("text")
    return rows


def first_actor_position(actor_ids, resource_events, fight, window_ms=30_000):
    actor_ids = {actor_id for actor_id in actor_ids if actor_id is not None}
    if not actor_ids:
        return None
    candidates = [
        event for event in resource_events
        if (event.get("targetID") in actor_ids or event.get("sourceID") in actor_ids)
        and event_point(event)
    ]
    if not candidates:
        return None
    early = [
        event for event in candidates
        if fight["startTime"] <= event.get("timestamp", 0) <= fight["startTime"] + window_ms
    ]
    return min(early or candidates, key=lambda event: abs(event.get("timestamp", 0) - fight["startTime"]))


def find_alleria_actor_ids(actor_map, actor_game_id=None):
    actor_game_id = actor_game_id or {}
    ids = {
        actor_id for actor_id, game_id in actor_game_id.items()
        if str(game_id) == str(ALLERIA_GAME_ID)
    }
    if ids:
        return ids
    return {
        actor_id for actor_id, name in actor_map.items()
        if "奥蕾莉亚" in name or "Alleria" in name
    }


def nearest_void_repulsion_cast(timestamp, casts):
    casts = [
        event for event in casts
        if ability_id(event) == VOID_REPULSION_CAST_ID
    ]
    if not casts:
        return None
    candidates = [
        event for event in casts
        if -2_000 <= timestamp - event.get("timestamp", 0) <= 12_000
    ]
    return min(candidates or casts, key=lambda event: abs(timestamp - event.get("timestamp", 0)))


def void_repulsion_cast_index(cast_event, casts):
    if not cast_event:
        return None
    cast_timestamps = sorted({
        event.get("timestamp", 0)
        for event in casts
        if ability_id(event) == VOID_REPULSION_CAST_ID
    })
    try:
        return cast_timestamps.index(cast_event.get("timestamp", 0)) + 1
    except ValueError:
        return None


def nearest_void_repulsion_impact(timestamp, target_id, damage_events, window_ms=1_000):
    candidates = [
        event for event in damage_events
        if ability_id(event) == VOID_REPULSION_DAMAGE_ID
        and event.get("targetID") == target_id
        and abs(event.get("timestamp", 0) - timestamp) <= window_ms
        and (event_point(event, "target") or event_point(event))
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda event: abs(event.get("timestamp", 0) - timestamp))


def build_void_repulsion_records(fight, actor_map, debuffs, markers, resource_events=None, casts=None, actor_game_id=None, damage_events=None, deaths=None):
    resource_events = resource_events or []
    casts = casts or []
    damage_events = damage_events or []
    deaths = deaths or []
    alleria_position_event = first_actor_position(find_alleria_actor_ids(actor_map, actor_game_id), resource_events, fight)
    arena_center = event_point(alleria_position_event or {})
    events = [
        event for event in debuffs
        if ability_id(event) == VOID_REPULSION_DEBUFF_ID
    ]
    active = {}
    records = []
    for event in sorted(events, key=lambda item: item.get("timestamp", 0)):
        target_id = event.get("targetID")
        if event_is_apply(event):
            active[target_id] = event
            continue
        if not event_is_remove(event):
            continue
        apply_event = active.pop(target_id, None)
        if any(
            death.get("targetID") == target_id
            and death.get("timestamp", 0) <= event.get("timestamp", 0)
            for death in deaths
        ):
            continue
        faded_point = event_point(event, "target") or event_point(event)
        impact_event = nearest_void_repulsion_impact(event.get("timestamp", 0), target_id, damage_events)
        target_position_event = actor_position_at(event.get("timestamp", 0), target_id, resource_events)
        source_position_event = nearest_actor_position(event.get("timestamp", 0), event.get("sourceID"), resource_events, 5_000, allow_future=False)
        cast_event = nearest_void_repulsion_cast((apply_event or event).get("timestamp", 0), casts)
        point = (
            faded_point
            or event_point(impact_event or {}, "target") or event_point(impact_event or {})
            or event_point(target_position_event or {})
        )
        source_point = (
            event_point(event, "source") or event_point(apply_event or {}, "source")
            or event_point(source_position_event or {})
        )
        drop_timestamp = event.get("timestamp", 0)
        relative_point = (point[0] - arena_center[0], point[1] - arena_center[1]) if point and arena_center else point
        record = {
            "time": format_time(drop_timestamp - fight["startTime"]),
            "positionMs": int(drop_timestamp - fight["startTime"]),
            "phase": phase_at(drop_timestamp, markers, fight),
            "player": actor(actor_map, event.get("targetID")),
            "targetID": target_id,
            "hasPosition": bool(point),
            "x": round(relative_point[0], 2) if relative_point else None,
            "y": round(relative_point[1], 2) if relative_point else None,
            "rawX": round(point[0], 2) if point else None,
            "rawY": round(point[1], 2) if point else None,
            "originX": round(arena_center[0], 2) if arena_center else None,
            "originY": round(arena_center[1], 2) if arena_center else None,
            "originPlayer": "奥蕾莉亚",
            "waterRadiusYards": VOID_REPULSION_WATER_RADIUS_YARDS,
            "_point": relative_point,
            "_sourcePoint": source_point,
        }
        if faded_point:
            record["positionSourceTime"] = record["time"]
            record["positionSourceDeltaMs"] = 0
            record["positionSourceRule"] = "fadeEvent"
        elif impact_event:
            record["positionSourceTime"] = format_time(impact_event.get("timestamp", 0) - fight["startTime"])
            record["positionSourceDeltaMs"] = int(impact_event.get("timestamp", 0) - drop_timestamp)
            record["positionSourceRule"] = "impactDamage"
        elif target_position_event:
            record["positionSourceTime"] = format_time(target_position_event.get("timestamp", 0) - fight["startTime"])
            record["positionSourceDeltaMs"] = int(target_position_event.get("timestamp", 0) - drop_timestamp)
            record["positionSourceRule"] = target_position_event.get("sourceRule")
            for key in ("beforeDeltaMs", "afterDeltaMs"):
                if key in target_position_event:
                    record[key] = int(target_position_event[key])
        if source_position_event:
            record["sourcePositionTime"] = format_time(source_position_event.get("timestamp", 0) - fight["startTime"])
        if cast_event:
            record["castTime"] = format_time(cast_event.get("timestamp", 0) - fight["startTime"])
            record["castPositionMs"] = int(cast_event.get("timestamp", 0) - fight["startTime"])
            record["castIndex"] = void_repulsion_cast_index(cast_event, casts)
        if apply_event:
            record["markTime"] = format_time(apply_event.get("timestamp", 0) - fight["startTime"])
            record["markPositionMs"] = int(apply_event.get("timestamp", 0) - fight["startTime"])
        records.append(record)

    return records


def clean_void_repulsion_record(record):
    return {
        key: value for key, value in record.items()
        if not key.startswith("_")
    }


def void_repulsion_round_groups(records):
    groups = []
    for record in sorted(records, key=lambda item: item.get("castPositionMs") or item.get("markPositionMs") or item.get("positionMs") or 0):
        anchor = record.get("castPositionMs") or record.get("markPositionMs") or record.get("positionMs") or 0
        cast_index = record.get("castIndex")
        group = None
        if cast_index:
            group = next((item for item in groups if item.get("phase") == record.get("phase") and item.get("castIndex") == cast_index), None)
        else:
            previous = groups[-1] if groups else None
            if previous and previous.get("phase") == record.get("phase") and abs(anchor - previous.get("anchorMs", 0)) <= VOID_REPULSION_GROUP_WINDOW_MS:
                group = previous
        if not group:
            group = {
                "phase": record.get("phase"),
                "castIndex": cast_index,
                "anchorMs": anchor,
                "time": record.get("castTime") or record.get("markTime") or record.get("time"),
                "records": [],
            }
            groups.append(group)
        group["records"].append(record)
        group["anchorMs"] = min(group.get("anchorMs", anchor), anchor)
    return groups


def analyze_void_repulsion_placement(fight, actor_map, debuffs, markers, resource_events=None, casts=None, actor_game_id=None, damage_events=None, deaths=None):
    records = build_void_repulsion_records(fight, actor_map, debuffs, markers, resource_events, casts, actor_game_id, damage_events, deaths)
    if not records:
        return [], []

    clean_records = [clean_void_repulsion_record(record) for record in records]
    drops_with_position = [record for record in records if record.get("_point")]
    if not drops_with_position:
        return [], clean_records

    rows = []
    for group in void_repulsion_round_groups(drops_with_position):
        phase_records = group["records"]
        if len(phase_records) < 3:
            continue
        center_candidates = [record["_point"] for record in phase_records]
        center = (
            sum(point[0] for point in center_candidates) / len(center_candidates),
            sum(point[1] for point in center_candidates) / len(center_candidates),
        )
        distances = [point_distance(record["_point"], center) for record in phase_records]
        average_distance = sum(distances) / len(distances)
        max_distance = max(distances)
        warn_distance = max(
            VOID_REPULSION_WATER_RADIUS_YARDS * 100,
            average_distance * VOID_REPULSION_SPREAD_MULTIPLIER,
        )
        outliers = [
            record for record, distance in zip(phase_records, distances)
            if distance > warn_distance
        ]
        for record, distance in zip(phase_records, distances):
            record["distanceFromCenter"] = round(coordinate_distance_yards(distance), 1)
            record["distanceFromCenterRaw"] = round(distance, 1)
            record["status"] = "偏散" if record in outliers else "正常"
        if not outliers:
            continue
        names = "、".join(record["player"] for record in outliers[:5])
        rows.append({
            "time": phase_records[0]["time"],
            "phase": group.get("phase"),
            "type": "void_repulsion_scattered",
            "severity": "warning",
            "details": [clean_void_repulsion_record(record) for record in phase_records],
            "text": f"{group.get('phase')} 第 {group.get('castIndex') or '?'} 次虚空斥力放水位置疑似偏散：本轮识别 {len(phase_records)} 人，最大偏离约 {coordinate_distance_yards(max_distance):.1f} 码，异常玩家：{names}。",
        })
    return rows, [clean_void_repulsion_record(record) for record in records]


def first_combat_initiator(initial_events, actor_map, actor_type, detail_debuffs=None, fight=None):
    aggro_candidates = []
    pulled_candidates = []
    for event in initial_events:
        source_id = event.get("sourceID")
        target_id = event.get("targetID")
        timestamp = event.get("timestamp", 0)
        if actor_type.get(source_id) == "Player" and actor_type.get(target_id) != "Player":
            aggro_candidates.append((timestamp, source_id))
        if actor_type.get(target_id) == "Player" and actor_type.get(source_id) != "Player":
            pulled_candidates.append((timestamp, target_id))
    if aggro_candidates:
        _, source_id = min(aggro_candidates, key=lambda item: item[0])
        return {"id": source_id, "name": actor(actor_map, source_id), "reason": "最先对敌方造成伤害"}
    if pulled_candidates:
        _, target_id = min(pulled_candidates, key=lambda item: item[0])
        return {"id": target_id, "name": actor(actor_map, target_id), "reason": "最先受到敌方伤害"}
    if detail_debuffs and fight:
        early_end = fight["startTime"] + 30_000
        void_applies = sorted(
            (
                event for event in detail_debuffs
                if ability_id(event) == VOID_GRASP_ID
                and event_is_apply(event)
                and fight["startTime"] <= event.get("timestamp", 0) <= early_end
            ),
            key=lambda item: item.get("timestamp", 0),
        )
        if void_applies:
            target_id = void_applies[0].get("targetID")
            return {"id": target_id, "name": actor(actor_map, target_id), "reason": "战斗初期最早空虚之握点名"}
    return None


def count_phase_pull_deaths(deaths, markers, fight, phase):
    return [
        death for death in deaths
        if phase_at(death.get("timestamp", 0), markers, fight) == phase
        and death.get("killingAbilityGameID") in (P15_AVOIDABLE_IDS if phase == "P1.5" else PULL_DEATH_IDS)
    ]


def interference_pairs_from_table(table_data, actor_map, actor_type):
    if isinstance(table_data, str):
        try:
            table_data = json.loads(table_data)
        except json.JSONDecodeError:
            return []
    name_to_ids = defaultdict(list)
    for actor_id, name in actor_map.items():
        if actor_type.get(actor_id) == "Player":
            name_to_ids[name].append(actor_id)
    pairs = {}

    def spell_rows(node):
        if isinstance(node, list):
            for item in node:
                yield from spell_rows(item)
            return
        if not isinstance(node, dict):
            return
        if node.get("guid") and isinstance(node.get("details"), list) and (
            int(node.get("spellsInterrupted") or 0) > 0
            or int(node.get("spellChannelsInterrupted") or 0) > 0
        ):
            yield node
            return
        for value in node.values():
            if isinstance(value, (dict, list)):
                yield from spell_rows(value)

    for spell_row in spell_rows(table_data):
        try:
            spell_id = int(spell_row.get("guid"))
        except (TypeError, ValueError):
            continue
        spell_name = spell_row.get("name") or PLAYER_CAST_NAMES.get(spell_id, f"Spell {spell_id}")
        try:
            table_timestamp = int(spell_row.get("timestamp")) if spell_row.get("timestamp") is not None else None
        except (TypeError, ValueError):
            table_timestamp = None
        for detail in spell_row.get("details") or []:
            ability_names = {str(item.get("name") or "") for item in detail.get("abilities") or []}
            if "Interrupting Tremor" not in ability_names and "干扰震荡" not in ability_names:
                continue
            for interrupted_actor in detail.get("actors") or []:
                player_name = interrupted_actor.get("name")
                player_ids = name_to_ids.get(player_name) or []
                if len(player_ids) != 1:
                    continue
                player_id = player_ids[0]
                try:
                    count = max(1, int(interrupted_actor.get("total") or 1))
                except (TypeError, ValueError):
                    count = 1
                key = (player_id, spell_id)
                previous = pairs.get(key)
                if previous is None or count > previous["count"]:
                    pairs[key] = {
                        "playerID": player_id,
                        "player": actor(actor_map, player_id),
                        "spellID": spell_id,
                        "spell": spell_name,
                        "count": count,
                        "tableTimestamp": table_timestamp,
                    }
    return list(pairs.values())


def analyze_interference_shock(fight, actor_map, actor_type, shock_casts, player_casts, interrupt_table, markers):
    """Filter cast timing through WCL's Interrupts table evidence."""
    shocks = sorted(
        (event for event in shock_casts if ability_id(event) == INTERFERENCE_SHOCK_ID and str(event.get("type", "")).lower() == "cast"),
        key=lambda event: event.get("timestamp", 0),
    )
    cast_rows = sorted((event for event in (player_casts or []) if actor_type.get(event.get("sourceID")) == "Player"), key=lambda event: event.get("timestamp", 0))
    rows = [{
        "index": index,
        "phase": phase_at(shock.get("timestamp", 0), markers, fight),
        "time": format_time(shock.get("timestamp", 0) - fight["startTime"]),
        "positionMs": int(shock.get("timestamp", 0) - fight["startTime"]),
        "source": actor(actor_map, shock.get("sourceID")),
        "interrupted": [],
        "interruptedCount": 0,
        "confidence": "wcl_interrupt_table",
    } for index, shock in enumerate(shocks, start=1)]
    used_player_shocks = set()
    table_pairs = interference_pairs_from_table(interrupt_table, actor_map, actor_type)
    for pair in table_pairs:
        for occurrence in range(int(pair.get("count") or 1)):
            candidates = []
            for row, shock in zip(rows, shocks):
                player_id = pair["playerID"]
                spell_id = pair["spellID"]
                if (row["index"], player_id) in used_player_shocks:
                    continue
                shock_ts = shock.get("timestamp", 0)
                matching_casts = [
                    event for event in cast_rows
                    if event.get("sourceID") == player_id
                    and ability_id(event) == spell_id
                    and shock_ts - 8_000 <= event.get("timestamp", 0) <= shock_ts + 300
                ]
                if matching_casts:
                    nearest = min(matching_casts, key=lambda event: abs(shock_ts - event.get("timestamp", 0)))
                    event_type = str(nearest.get("type", "")).lower()
                    score = abs(shock_ts - nearest.get("timestamp", 0)) - (20_000 if event_type == "begincast" else 0)
                    candidates.append((score, row, nearest))
            table_timestamp = pair.get("tableTimestamp")
            if table_timestamp is not None and occurrence == 0:
                table_candidates = [
                    (abs(shock.get("timestamp", 0) - table_timestamp), row)
                    for row, shock in zip(rows, shocks)
                    if (row["index"], pair["playerID"]) not in used_player_shocks
                ]
                target_row = min(table_candidates, key=lambda item: item[0])[1] if table_candidates else None
                target_shock = shocks[target_row["index"] - 1] if target_row else None
                matching_casts = [
                    event for event in cast_rows
                    if target_shock
                    and event.get("sourceID") == pair["playerID"]
                    and ability_id(event) == pair["spellID"]
                    and target_shock.get("timestamp", 0) - 8_000 <= event.get("timestamp", 0) <= target_shock.get("timestamp", 0) + 300
                ]
                cast_event = min(matching_casts, key=lambda event: abs(target_shock.get("timestamp", 0) - event.get("timestamp", 0))) if matching_casts else None
            elif candidates:
                _, target_row, cast_event = min(candidates, key=lambda item: item[0])
            else:
                target_row = next((row for row in rows if (row["index"], pair["playerID"]) not in used_player_shocks), None)
                cast_event = None
            if target_row is None:
                break
            used_player_shocks.add((target_row["index"], pair["playerID"]))
            target_row["interrupted"].append({
                **pair,
                "role": "unknown",
                "castStart": format_time(cast_event.get("timestamp", 0) - fight["startTime"]) if cast_event else None,
                "evidence": "wcl_interrupt_table",
            })

    for index, shock in enumerate(shocks, start=1):
        row = rows[index - 1]
        row["interruptedCount"] = len(row["interrupted"])
        details = "；".join(f"{item['player']}：{item['spell']}" for item in row["interrupted"])
        row["text"] = f"{row['time']} 干扰震荡实际打断 {row['interruptedCount']} 名玩家" + (f"：{details}" if details else "。")
    return rows


def matching_void_grasp_bow(field_audit, target_id, death_elapsed_ms):
    groups = sorted((field_audit or {}).get("bowGroups") or [], key=lambda row: int(row.get("applyStartMs") or 0))
    candidates = []
    for group in groups:
        for player in group.get("players") or []:
            if player.get("targetID") != target_id:
                continue
            start_ms = int(player.get("applyTimeMs") or group.get("applyStartMs") or 0)
            end_ms = int(player.get("fadeTimeMs") or group.get("fireTimeMs") or start_ms)
            if start_ms <= death_elapsed_ms <= end_ms + 1_000:
                candidates.append((abs(end_ms - death_elapsed_ms), group))
    if not candidates:
        return None
    group = min(candidates, key=lambda item: item[0])[1]
    same_phase = [row for row in groups if row.get("phase") == group.get("phase")]
    return {
        "id": group.get("id"),
        "index": group.get("index"),
        "phase": group.get("phase"),
        "phaseIndex": same_phase.index(group) + 1 if group in same_phase else None,
    }


def analyze_void_grasp_healing(fight, actor_map, actor_type, deaths, healing_by_target, player_roles=None, field_audit=None, classification_key=None):
    rows = []
    player_roles = player_roles or {}
    audit_deaths = (field_audit or {}).get("voidDeaths") or []
    designated_name_ids = defaultdict(set)
    if DESIGNATED_HEALER_IDS:
        for actor_id in DESIGNATED_HEALER_IDS:
            designated_name_ids[actor(actor_map, actor_id)].add(actor_id)
    else:
        for actor_id, name in actor_map.items():
            if name in DESIGNATED_HEALER_NAMES:
                designated_name_ids[name].add(actor_id)
    for death in deaths:
        if death.get("killingAbilityGameID") != VOID_GRASP_ID:
            continue
        death_ts = death.get("timestamp", 0)
        death_elapsed_ms = int(death_ts - fight["startTime"])
        target_id = death.get("targetID")
        bow = matching_void_grasp_bow(field_audit, target_id, death_elapsed_ms)
        healing = healing_by_target.get(target_id, [])
        six = defaultdict(int)
        eight = defaultdict(int)
        for event in healing:
            ts = event.get("timestamp", 0)
            source_id = event.get("sourceID")
            amount = event_amount(event)
            if death_ts - 8_000 <= ts <= death_ts:
                eight[source_id] += amount
            if death_ts - 6_000 <= ts <= death_ts:
                six[source_id] += amount
        prior_dead_names = {
            actor(actor_map, row.get("targetID")) for row in deaths
            if row.get("timestamp", 0) < death_ts
        }
        audit_death = min(
            (
                row for row in audit_deaths
                if row.get("targetID") == target_id
                and abs(int(row.get("timeMs") or 0) - int(death_ts - fight["startTime"])) <= 1_000
            ),
            key=lambda row: abs(int(row.get("timeMs") or 0) - int(death_ts - fight["startTime"])),
            default=None,
        )
        death_designated_name_ids = defaultdict(set)
        for healer_name, source_ids in designated_name_ids.items():
            death_designated_name_ids[healer_name].update(source_ids)
        for source in (audit_death or {}).get("healerRoster") or []:
            healer_name = source.get("healer")
            healer_id = source.get("healerID")
            if healer_name in DESIGNATED_HEALER_NAMES and healer_id is not None:
                death_designated_name_ids[healer_name].add(healer_id)
        for source in (audit_death or {}).get("healingByHealer") or []:
            healer_name = source.get("healer")
            healer_id = source.get("healerID")
            if healer_name in DESIGNATED_HEALER_NAMES and healer_id is not None:
                death_designated_name_ids[healer_name].add(healer_id)
        active_phantoms = int((audit_death or {}).get("activePhantomCount") or 0)
        dead_player_count = int((audit_death or {}).get("deadPlayerCountAtDeath") or len(prior_dead_names))
        death_event_count = sum(1 for row in deaths if row.get("timestamp", 0) <= death_ts)
        target_health_percent = (audit_death or {}).get("targetHealthPercentAtApply")
        healer_roster_count = int((audit_death or {}).get("healerRosterCount") or sum(
            1 for role in player_roles.values() if str(role).endswith("-healer") or role == "healer"
        ))
        alive_healer_ids = set((audit_death or {}).get("aliveHealerIDsAtDeath") or [])
        alive_healer_count = int(
            (audit_death or {}).get("aliveHealerCountAtDeath")
            if (audit_death or {}).get("aliveHealerCountAtDeath") is not None
            else max(0, healer_roster_count - sum(1 for name in prior_dead_names if name in death_designated_name_ids))
        )
        exemption_reasons = []
        if classification_key == "phase_abandon":
            exemption_reasons.append("放弃/add引怪战斗")
        if death_event_count >= GLOBAL_DEATH_EXEMPT_THRESHOLD:
            exemption_reasons.append(
                f"全局最高优先级豁免：该死亡为本场第{death_event_count}次死亡，团队死亡次数已达到{GLOBAL_DEATH_EXEMPT_THRESHOLD}"
            )
        if active_phantoms >= 4:
            exemption_reasons.append(f"场上存活银色幻影{active_phantoms}个")
        if alive_healer_count < 4:
            exemption_reasons.append(f"死亡时治疗组未满员（存活{alive_healer_count}/4）")
        if target_health_percent is None:
            exemption_reasons.append("点名时血量数据缺失，无法确认血量>50%")
        elif float(target_health_percent) <= 50:
            exemption_reasons.append(f"点名时血量仅{float(target_health_percent):.2f}%（要求>50%）")
        exempt = bool(exemption_reasons)
        breakdown = []
        for healer_name in sorted(death_designated_name_ids):
            source_ids = death_designated_name_ids[healer_name]
            if alive_healer_ids:
                if not (source_ids & alive_healer_ids):
                    continue
            elif healer_name in prior_dead_names:
                continue
            healing6s = sum(six.get(source_id, 0) for source_id in source_ids)
            healing8s = sum(eight.get(source_id, 0) for source_id in source_ids)
            breakdown.append({
                "healerID": min(source_ids) if source_ids else None,
                "healerIDs": sorted(source_ids),
                "healer": healer_name,
                "healing6s": healing6s,
                "healing8s": healing8s,
                "insufficient": healing8s < VOID_GRASP_HEALING_MIN,
            })
        rows.append({
            "time": format_time(death_elapsed_ms),
            "positionMs": death_elapsed_ms,
            "playerID": target_id,
            "player": actor(actor_map, target_id),
            "verifiedDeath": True,
            "deathAbilityID": VOID_GRASP_ID,
            "bowID": (bow or {}).get("id"),
            "bowGroup": (bow or {}).get("index"),
            "bowPhase": (bow or {}).get("phase"),
            "phaseBowGroup": (bow or {}).get("phaseIndex"),
            "healers": breakdown,
            "totalHealing6s": sum(item["healing6s"] for item in breakdown),
            "window6s": f"{format_time(max(0, death_ts - fight['startTime'] - 6_000))}-{format_time(death_ts - fight['startTime'])}",
            "window8s": f"{format_time(max(0, death_elapsed_ms - 8_000))}-{format_time(death_elapsed_ms)}",
            "threshold8s": VOID_GRASP_HEALING_MIN,
            "activePhantomCount": active_phantoms,
            "deadPlayerCountAtDeath": dead_player_count,
            "deathEventCountAtDeath": death_event_count,
            "targetHealthAtApply": (audit_death or {}).get("targetHealthAtApply"),
            "targetMaxHealthAtApply": (audit_death or {}).get("targetMaxHealthAtApply"),
            "targetHealthPercentAtApply": target_health_percent,
            "targetHealthSampleDeltaMs": (audit_death or {}).get("targetHealthSampleDeltaMs"),
            "healerRosterCount": healer_roster_count,
            "aliveHealerCountAtDeath": alive_healer_count,
            "aliveHealerIDsAtDeath": sorted(alive_healer_ids),
            "exempt": exempt,
            "exemptionReasons": exemption_reasons,
            "counted": not exempt,
        })
    return rows


def build_transition_details(fight, actor_map, player_roles, deaths, markers, buffs):
    rows = []
    for death in deaths:
        phase = phase_at(death.get("timestamp", 0), markers, fight)
        ability = death.get("killingAbilityGameID")
        if phase not in {"P1.5", "P2.5"} and ability not in DIMENSIONAL_SLASH_IDS:
            continue
        transition_phase = "P2.5" if ability in DIMENSIONAL_SLASH_IDS else phase
        category = "P1.5死亡" if transition_phase == "P1.5" else "P2.5死亡"
        target_id = death.get("targetID")
        rows.append({
            "category": category,
            "phase": transition_phase,
            "time": format_time(death.get("timestamp", 0) - fight["startTime"]),
            "positionMs": int(death.get("timestamp", 0) - fight["startTime"]),
            "player": actor(actor_map, target_id),
            "role": player_roles.get(target_id, "unknown"),
            "abilityID": ability,
            "ability": SPELLS.get(ability, "坠崖" if ability in {None, 3} else str(ability)),
            "deathCount": 1,
            "compensationCount": 0,
            "displayDeathCount": 1,
        })
    for event in buffs or []:
        if ability_id(event) != DEATH_COMPENSATION_ID or not event_is_apply(event):
            continue
        phase = phase_at(event.get("timestamp", 0), markers, fight)
        if phase not in {"P1.5", "P2.5"}:
            continue
        target_id = event.get("targetID")
        rows.append({
            "category": "P1.5死亡" if phase == "P1.5" else "P2.5死亡",
            "phase": phase,
            "time": format_time(event.get("timestamp", 0) - fight["startTime"]),
            "positionMs": int(event.get("timestamp", 0) - fight["startTime"]),
            "player": actor(actor_map, target_id),
            "role": player_roles.get(target_id, "unknown"),
            "abilityID": DEATH_COMPENSATION_ID,
            "ability": "代偿触发",
            "deathCount": 0,
            "compensationCount": 1,
            "displayDeathCount": 1,
        })
    return rows


def build_p3_portal_summons(fight, actor_map, actor_game_id, casts):
    portal_map = {}
    for event in casts:
        if ability_id(event) == PORTAL_CAST_ID and str(event.get("type", "")).lower() == "cast":
            portal_map.setdefault((event.get("sourceID"), event.get("timestamp", 0)), event)
    portals = sorted(portal_map.values(), key=lambda event: event.get("timestamp", 0))
    devours = sorted({event.get("timestamp", 0) for event in casts if ability_id(event) == COSMIC_DEVOUR_ID and str(event.get("type", "")).lower() == "cast"})
    rows = []
    for index, portal in enumerate(portals, start=1):
        cycle_index = ((index - 1) % 3) + 1
        game_id = P3_ADD_GAME_IDS[cycle_index]
        actor_ids = [actor_id for actor_id, value in actor_game_id.items() if str(value) == str(game_id)]
        start = portal.get("timestamp", 0)
        end = min((ts for ts in devours if ts > start), default=fight["endTime"])
        rows.append({
            "portalIndex": index,
            "cycleIndex": cycle_index,
            "time": format_time(start - fight["startTime"]),
            "positionMs": int(start - fight["startTime"]),
            "despawnTime": format_time(end - fight["startTime"]),
            "gameID": game_id,
            "actorIDs": actor_ids,
            "name": P3_ADD_NAMES[game_id],
        })
    return rows


def analyze_rift_slash_tank_swaps(fight, actor_map, actor_type, player_roles, debuffs, deaths, markers):
    tank_ids = sorted(player_id for player_id, role in player_roles.items() if role == "tank")
    rows = []
    slash_events = sorted(
        (row for row in debuffs if ability_id(row) == RIFT_SLASH_ID and row.get("targetID") in tank_ids),
        key=lambda row: row.get("timestamp", 0),
    )
    tank_deaths = sorted((
        death for death in deaths
        if death.get("targetID") in tank_ids
        and death.get("killingAbilityGameID") in (TANK_DEATH_IDS | {RIFT_SLASH_DAMAGE_ID})
        and phase_at(death.get("timestamp", 0), markers, fight) == "P2"
    ), key=lambda row: row.get("timestamp", 0))
    for death in tank_deaths:
        target_id = death.get("targetID")
        death_ts = death.get("timestamp", 0)
        stack = 0
        for event in slash_events:
            if event.get("timestamp", 0) > death_ts:
                break
            if event.get("targetID") != target_id:
                continue
            event_kind = str(event.get("type", "")).lower()
            stack = 0 if "remove" in event_kind else int(event.get("stack") or event.get("stacks") or 1)
        if stack <= 3:
            continue
        surviving_tanks = [
            player_id for player_id in tank_ids
            if player_id != target_id
            and not any(
                row.get("targetID") == player_id and row.get("timestamp", 0) <= death_ts
                for row in deaths
            )
        ]
        offender_id = surviving_tanks[0] if len(surviving_tanks) == 1 else None
        counted = offender_id is not None
        rows.append({
            "time": format_time(death_ts - fight["startTime"]),
            "positionMs": int(death_ts - fight["startTime"]),
            "phase": "P2",
            "victim": actor(actor_map, target_id),
            "victimID": target_id,
            "stack": stack,
            "offender": actor(actor_map, offender_id) if offender_id else "未能唯一识别存活的另一坦",
            "offenderID": offender_id,
            "causedTankDeath": True,
            "otherTankAlive": bool(offender_id),
            "deathAbilityID": death.get("killingAbilityGameID"),
            "counted": counted,
            "scoreMultiplier": 1.0 if counted else 0.0,
            "countReason": "死亡时裂隙挥砍层数>3，另一坦仍存活，存活坦克计数+1" if counted else "死亡时没有可归责的存活坦克，仅展示不计数",
            "text": f"{format_time(death_ts - fight['startTime'])} {actor(actor_map, target_id)} 在裂隙挥砍 {stack} 层时死亡；存活坦克：{actor(actor_map, offender_id) if offender_id else '无'}。",
        })
    return rows


def analyze_fight(report_id, fight, actor_map, actor_type, payload):
    deaths = payload["deaths"]
    markers = payload["markers"]
    classification = payload["classification"]
    detail_damage = payload["detailDamage"]
    detail_debuffs = payload["detailDebuffs"]
    detail_buffs = payload["detailBuffs"]
    detail_casts = payload["detailCasts"]
    energy_events = payload.get("energyEvents") or []
    phantom_damage = payload.get("phantomDamage") or []
    position_events = (payload.get("positionEvents") or []) + [event for event in detail_damage if event_point(event)]
    player_roles = payload.get("playerRoles") or {}
    initial_events = payload.get("initialEvents") or []
    actor_game_id = payload.get("actorGameID") or {}
    shock_casts = payload.get("shockCasts") or []
    player_casts = payload.get("playerCasts") or []
    shock_interrupt_table = payload.get("shockInterruptTable") or {}
    healing_by_target = payload.get("healingByTarget") or {}
    field_audit = payload.get("fieldAudit")

    duration_ms = fight["endTime"] - fight["startTime"]
    absolute_ms = fight["reportStartTime"] + fight["startTime"]
    local_start = get_local_datetime(absolute_ms)
    phase = classification["phase"]
    reason_key = classification["key"]

    death_timeline = []
    silver_marks = [event for event in detail_debuffs if ability_id(event) == SILVER_ARROW_MARK_ID and event_is_apply(event)]
    arrow_mark_clusters = silver_arrow_mark_clusters(fight, actor_map, detail_debuffs, markers)
    for death in deaths:
        death_phase = phase_at(death.get("timestamp", 0), markers, fight)
        ability = SPELLS.get(death.get("killingAbilityGameID"), str(death.get("killingAbilityGameID")))
        amount = None
        if death.get("killingAbilityGameID") in {None, 3}:
            if death_phase == "P2.5":
                ability = "转阶段击飞"
            elif reason_key == "phase_abandon" or death_phase in {"P1", "P1.5"}:
                ability = "坠崖"
            else:
                ability = "坠崖"
        if death.get("killingAbilityGameID") == SILVER_ARROW_DAMAGE_ID:
            mark_cluster = nearest_arrow_mark_cluster(arrow_mark_clusters, death.get("timestamp", 0))
            arrow_damage = silver_arrow_damage_for_death(death, detail_damage)
            amount = event_amount(arrow_damage) if arrow_damage else None
            if is_marked_by_arrow(death.get("targetID"), mark_cluster):
                ability = "银锋箭"
            else:
                ability = "银锋箭（误伤）"
        row = {
            "time": format_time(fight_elapsed(death, fight)),
            "absoluteTime": death.get("timestamp"),
            "player": actor(actor_map, death.get("targetID")),
            "role": player_roles.get(death.get("targetID"), "unknown"),
            "roleText": role_text(player_roles.get(death.get("targetID"), "unknown")),
            "abilityID": death.get("killingAbilityGameID"),
            "ability": ability,
            "phase": death_phase,
        }
        if amount:
            row["amount"] = amount
        death_timeline.append(row)

    is_kill = bool(fight.get("kill"))
    if is_kill:
        p1_arrow_rows, p1_arrow_issues = analyze_p1_arrows(fight, actor_map, detail_buffs, detail_debuffs, detail_damage, markers)
        collapsing_rows, collapsing_deaths = analyze_collapsing_void(fight, actor_map, actor_type, deaths, detail_damage, detail_debuffs, player_roles)
        shadow_misses = analyze_p2_shadow_misses(fight, actor_map, actor_game_id, detail_damage, detail_debuffs, markers, phantom_damage)
        energy_misses = analyze_p2_energy(markers, fight, detail_debuffs, detail_damage, energy_events, actor_map, actor_game_id)
        gravity_rows = analyze_gravity_attribution(fight, actor_map, deaths, detail_debuffs)
        p2_ranger_mark_rows = render_ranger_mark_groups(analyze_ranger_mark_groups(markers, fight, detail_debuffs, "P2"), actor_map, "P2")
        void_repulsion_rows, void_repulsion_records = analyze_void_repulsion_placement(fight, actor_map, detail_debuffs, markers, position_events, detail_casts, actor_game_id, detail_damage, deaths)
    else:
        if phase == "P1":
            p1_arrow_rows, p1_arrow_issues = analyze_p1_arrows(fight, actor_map, detail_buffs, detail_debuffs, detail_damage, markers)
        else:
            p1_arrow_rows, p1_arrow_issues = [], []
        collapsing_rows, collapsing_deaths = analyze_collapsing_void(fight, actor_map, actor_type, deaths, detail_damage, detail_debuffs, player_roles)
        shadow_misses = analyze_p2_shadow_misses(fight, actor_map, actor_game_id, detail_damage, detail_debuffs, markers, phantom_damage)
        energy_misses = analyze_p2_energy(markers, fight, detail_debuffs, detail_damage, energy_events, actor_map, actor_game_id)
        gravity_rows = analyze_gravity_attribution(fight, actor_map, deaths, detail_debuffs)
        p2_ranger_mark_rows = render_ranger_mark_groups(analyze_ranger_mark_groups(markers, fight, detail_debuffs, "P2"), actor_map, "P2")
        void_repulsion_rows, void_repulsion_records = analyze_void_repulsion_placement(fight, actor_map, detail_debuffs, markers, position_events, detail_casts, actor_game_id, detail_damage, deaths)

    void_grasp_rays = analyze_void_grasp_rays(fight, actor_map, actor_type, actor_game_id, detail_debuffs, detail_damage, position_events, markers)
    p1_arrow_audit = analyze_p1_arrow_audit(fight, actor_map, detail_debuffs, detail_damage, markers, p1_arrow_rows)
    interference_rows = analyze_interference_shock(
        fight, actor_map, actor_type, shock_casts, player_casts, shock_interrupt_table, markers,
    )
    energy_misses = refine_p2_energy_with_field_audit(energy_misses, field_audit, actor_map)
    void_grasp_healing = analyze_void_grasp_healing(
        fight, actor_map, actor_type, deaths, healing_by_target,
        player_roles=player_roles, field_audit=field_audit, classification_key=reason_key,
    )
    transition_details = build_transition_details(fight, actor_map, player_roles, deaths, markers, detail_buffs)
    p3_portal_summons = build_p3_portal_summons(fight, actor_map, actor_game_id, detail_casts)
    rift_slash_rows = analyze_rift_slash_tank_swaps(fight, actor_map, actor_type, player_roles, detail_debuffs, deaths, markers)

    wipe_reason = classification["label"]
    wcl_link = ""
    investigation = ""

    if is_kill:
        wipe_phase = "已击杀"
        wipe_reason = "已击杀"
        investigation = f"Boss 已击杀，本场不归类为灭团。战斗结束于 {format_time(duration_ms)}。"
        wcl_link = replay_link(report_id, fight["id"], max(0, duration_ms - 3_000))
    else:
        wipe_phase = phase
        if reason_key == "p1_add_rage":
            rage_rows = [event for event in detail_buffs if ability_id(event) == RAGE_STACK_ID]
            max_stack = max((int(event.get("stack") or event.get("stacks") or 0) for event in rage_rows), default=0)
            investigation = f"P1 龌勒卢斯出现回响黑暗叠层，最高约 {max_stack} 层，且灭团时间早于 2:45，判定为 P1 大怪狂暴。"
            wcl_link = deep_link(report_id, fight["id"], "buffs", rage_rows[-1]["timestamp"], 20_000, 5_000) if rage_rows else ""
        elif reason_key in {"p1_team_collapse", "tank_death"}:
            if p1_arrow_issues:
                wipe_reason = "P1 银锋箭处理异常"
                investigation = p1_arrow_issues[0]["text"]
                wcl_link = replay_link(report_id, fight["id"], max(0, p1_arrow_issues[0].get("positionMs", 0) - 3_000))
            elif reason_key == "tank_death":
                first_death_ts = deaths[0]["timestamp"] if deaths else fight["endTime"]
                echo_stack = max_buff_stack_before(detail_buffs, RAGE_STACK_ID, first_death_ts)
                stack_text = f"死亡前回响黑暗最高约 {echo_stack} 层。" if echo_stack else "未识别到死亡前回响黑暗层数。"
                investigation = f"最早 3 个死亡中出现坦克相关死亡，优先复盘坦克承伤与回响黑暗层数。{stack_text}"
                wcl_link = deep_link(report_id, fight["id"], "damage-taken", deaths[0]["timestamp"], 20_000, 5_000) if deaths else ""
            else:
                investigation = f"P1 直接灭团，本场死亡总人数 {len(deaths)}，归因为团队减员过多。"
        elif reason_key in {"p15_pull_deaths", "p2_pull_deaths", "p3_pull_deaths"}:
            if reason_key == "p15_pull_deaths":
                pull_rows = count_phase_pull_deaths(deaths, markers, fight, "P1.5")
            else:
                pull_rows = [death for death in deaths if death.get("killingAbilityGameID") in PULL_DEATH_IDS]
            pull_names = "、".join(actor(actor_map, death.get("targetID")) for death in pull_rows)
            investigation = f"本场有 {len(pull_rows)} 名玩家死于拉弓/射击/转阶段走位相关伤害。"
            if pull_names:
                investigation += f"相关玩家：【{pull_names}】。"
            wcl_link = deep_link(report_id, fight["id"], "deaths", deaths[0]["timestamp"], 15_000, 5_000) if deaths else ""
        elif reason_key == "p2_shadow_aoe":
            investigation = "死亡记录命中银色幻影相关 AoE，判定为银色幻影过多导致团血崩溃。"
            wcl_link = deep_link(report_id, fight["id"], "damage-taken", deaths[0]["timestamp"], 20_000, 5_000) if deaths else ""
        elif reason_key == "p2_phantom_barrier":
            barrier_deaths = sum(1 for death in deaths if death.get("killingAbilityGameID") == COSMIC_BARRIER_ID)
            investigation = f"{phase} 有 {barrier_deaths} 人死于宇宙屏障，判定为裂隙幻影没有被正常转火处理。"
            wcl_link = deaths_link(report_id, fight["id"]) if deaths else ""
        elif reason_key == "phase_abandon" and phase == "P1" and p1_arrow_issues:
            wipe_reason = "P1 银锋箭处理异常"
            investigation = p1_arrow_issues[0]["text"]
            wcl_link = replay_link(report_id, fight["id"], max(0, p1_arrow_issues[0].get("positionMs", 0) - 3_000))
        elif reason_key == "phase_abandon":
            bridge_rows = bridge_deaths(deaths)
            first_bridge_ts = min((death.get("timestamp", 0) for death in bridge_rows), default=None)
            deaths_before_repull = prior_real_death_count(deaths, first_bridge_ts) if first_bridge_ts else 0
            phase_loss_rows = [death for death in death_timeline if death.get("phase") == phase]
            if phase == "P1":
                investigation = f"P1 起手后团队快速放弃。在选择重开前已有{deaths_before_repull}人死亡。"
                initiator = first_combat_initiator(initial_events, actor_map, actor_type, detail_debuffs, fight)
                if initiator:
                    reason = initiator.get("reason") or "初始进战斗来源"
                    investigation += f" 疑似引怪玩家：【{initiator['name']}】（{reason}）。"
            else:
                loss_names = "、".join(row.get("player") for row in phase_loss_rows[:10])
                investigation = f"{phase} 阶段累计出现 {len(phase_loss_rows)} 人次减员，团队随后选择放弃。"
                if loss_names:
                    investigation += f"该阶段减员玩家：【{loss_names}】。"
            wcl_link = replay_link(report_id, fight["id"], fight_elapsed(bridge_rows[0], fight) - 5_000) if bridge_rows else ""
        elif reason_key == "phase_bridge_mistake":
            bridge_rows = bridge_deaths([death for death in deaths if phase_at(death.get("timestamp", 0), markers, fight) == phase])
            names = "、".join(actor(actor_map, death.get("targetID")) for death in bridge_rows[:8])
            investigation = f"{phase} 阶段发生过台子/坠崖，相关玩家：【{names}】。"
            wcl_link = replay_link(report_id, fight["id"], fight_elapsed(bridge_rows[0], fight) - 5_000) if bridge_rows else ""
        elif reason_key == "p25_knockback":
            bridge_rows = bridge_deaths([death for death in deaths if phase_at(death.get("timestamp", 0), markers, fight) == "P2.5"])
            names = "、".join(actor(actor_map, death.get("targetID")) for death in bridge_rows[:8])
            investigation = f"P2.5 宇宙屏障持续期间发生坠崖，归因为转阶段击飞。相关玩家：【{names}】。"
            wcl_link = replay_link(report_id, fight["id"], fight_elapsed(bridge_rows[0], fight) - 5_000) if bridge_rows else ""
        elif reason_key == "p3_add_enrage":
            portal_cast = min((event for event in detail_casts if ability_id(event) == PORTAL_CAST_ID), key=lambda item: item.get("timestamp", 0), default=None)
            investigation = "P3 发现大怪或裂隙幻影获得狂暴，判定为大怪狂暴。"
            wcl_link = replay_link(report_id, fight["id"], fight_elapsed(portal_cast, fight) - 3_000) if portal_cast else (deaths_link(report_id, fight["id"]) if deaths else "")
        elif reason_key == "p3_line_aoe":
            investigation = gravity_rows[0]["text"] if gravity_rows else "P3 低减员状态下重力坍缩造成多人同秒死亡，判定为拉线 AoE 崩溃。"
            wcl_link = deaths_link(report_id, fight["id"]) if deaths else ""
        elif reason_key == "prior_attrition_collapse":
            decisive = decisive_death_cluster(deaths)
            prior_count = unique_player_death_count_before(deaths, decisive["start"]) if decisive else 0
            phase_counts = defaultdict(int)
            if decisive:
                for death in deaths:
                    if death.get("timestamp", 0) >= decisive["start"]:
                        continue
                    phase_counts[phase_at(death.get("timestamp", 0), markers, fight)] += 1
            phase_text = "、".join(f"{name} {count}人次" for name, count in phase_counts.items())
            investigation = f"最终崩溃前已有 {prior_count} 名不同玩家发生过死亡，判定为前置阶段减员过多导致团队失去续战能力。"
            if phase_text:
                investigation += f"前置死亡分布：{phase_text}。"
            wcl_link = deaths_link(report_id, fight["id"]) if deaths else ""
        elif reason_key == "p3_boss_enrage":
            ranger_text = f" P2 消能异常：{'; '.join(row['text'] for row in energy_misses[:4])}。" if energy_misses else " 请同步检查 P2 游侠队长印记连线是否按时消到 Boss 能量。"
            investigation = f"玩家陆续死于噬灭宇宙，判定为奥蕾莉亚狂暴；请同步检查 P2 是否提前结束。{ranger_text}"
            wcl_link = deaths_link(report_id, fight["id"]) if deaths else ""
        elif reason_key == "tank_death":
            first_death_ts = deaths[0]["timestamp"] if deaths else fight["endTime"]
            echo_stack = max_buff_stack_before(detail_buffs, RAGE_STACK_ID, first_death_ts)
            stack_text = f"死亡前回响黑暗最高约 {echo_stack} 层。" if echo_stack else ""
            investigation = f"最早 3 个死亡中出现坦克相关死亡，判定为倒坦。{stack_text}"
            wcl_link = deep_link(report_id, fight["id"], "damage-taken", deaths[0]["timestamp"], 20_000, 5_000) if deaths else ""
        else:
            investigation = f"{phase} 阶段死亡总人数 {len(deaths)}，未命中更具体机制，归因为常规 AoE/团队减员崩溃。"
            wcl_link = deep_link(report_id, fight["id"], "damage-taken", deaths[0]["timestamp"], 20_000, 5_000) if deaths else ""

    if not is_kill and deaths and reason_key != "p3_add_enrage":
        wcl_link = deaths_link(report_id, fight["id"])

    trial_records = []
    if not is_kill and phase == "P1" and p1_arrow_issues:
        binding_remove_count = sum(1 for row in p1_arrow_rows if row.get("kind") == "binding_removed")
        trial_records.append({
            "type": "p1_arrows",
            "title": "P1 银锋箭 / 腐化精华",
            "summary": f"{binding_remove_count} 次幽影束缚移除，{len(p1_arrow_issues)} 个异常",
            "rows": p1_arrow_issues,
        })
    if collapsing_deaths:
        trial_records.append({
            "type": "collapsing_void_deaths",
            "title": "崩裂空无误伤他人致死",
            "summary": f"{len(collapsing_deaths)} 条致死记录",
            "rows": [{"text": text} for text in collapsing_deaths],
        })
    if shadow_misses:
        trial_records.append({
            "type": "missed_shadows",
            "title": "P2 银色幻影处理",
            "summary": f"{len(shadow_misses)} 次",
            "rows": shadow_misses[:20],
        })
    if p1_arrow_audit:
        trial_records.append({
            "type": "p1_arrow_audit",
            "title": "P1 Silver Arrow boss-hit audit",
            "summary": f"{len(p1_arrow_audit)} arrow rounds",
            "rows": p1_arrow_audit,
        })
    if void_grasp_rays:
        trial_records.append({
            "type": "void_grasp_rays",
            "title": "Collapsing Void ray simulation",
            "summary": f"{len(void_grasp_rays)} void grasp casts",
            "rows": void_grasp_rays,
        })
    if energy_misses:
        trial_records.append({
            "type": "missed_energy",
            "title": "游侠队长印记消能异常",
            "summary": f"{len(energy_misses)} 组",
            "rows": energy_misses,
        })
    if gravity_rows:
        trial_records.append({
            "type": "gravity_collapse",
            "title": "P3 重力坍缩归因",
            "summary": f"{len(gravity_rows)} 次多人死亡",
            "rows": gravity_rows,
        })
    if void_repulsion_records:
        if not void_repulsion_rows:
            phase_rows = []
            for phase_name in ["P1", "P1.5", "P2", "P2.5", "P3"]:
                phase_records = [record for record in void_repulsion_records if record.get("phase") == phase_name]
                if not phase_records:
                    continue
                phase_rows.append({
                    "time": phase_records[0].get("time"),
                    "phase": phase_name,
                    "details": phase_records,
                    "text": f"{phase_name} 已记录 {len(phase_records)} 个虚空斥力放水点。",
                })
            void_repulsion_rows = phase_rows
        trial_records.append({
            "type": "void_repulsion_placement",
            "title": "虚空斥力放水位置",
            "summary": f"{len(void_repulsion_records)} 个放水点",
            "rows": void_repulsion_rows,
        })

    missed_energy_board = {}
    for event in energy_misses:
        player_ids = event.get("playerIDs") or []
        players = event.get("players") or []
        if not players:
            continue
        for player_index, player in enumerate(players):
            player_id = player_ids[player_index] if player_index < len(player_ids) else None
            row = missed_energy_board.setdefault(player, build_board_row(player, "missedEnergy", "P2消Boss能量失误", role=player_roles.get(player_id, "unknown")))
            row["hitCount"] += 1
            row["events"].append({
                **event,
                "counted": False,
                "verdictCounted": False,
                "displayOnly": True,
                "countReason": event.get("countReason") or "消能失误仅展示分析，永远不计数、不进入终审",
            })

    snap_aiming_rows = build_snap_aiming_board(field_audit, player_roles, fight["id"])

    local_board = {
        "p15AvoidableDeaths": [],
        PASSAGE_CLIFF_SKILL_KEY: [],
        "collapsingVoidSnapAiming": snap_aiming_rows,
        "missedEnergy": list(missed_energy_board.values()),
        "interferenceShockInterrupts": [],
        "waterOutliers": [],
        "voidGraspHealingLow": [],
        "p1SilverArrowDeaths": [],
        "p1SilverArrowMissedFights": [],
        "missedShadows": [],
        "gravityLineViolation": [],
        "tankRiftSlashFailure": [],
        VORELUTH_VULN_SKILL_KEY: [],
    }
    local_board.update(analyze_avoidable_damage(
        fight, actor_map, actor_type, player_roles, detail_damage, deaths, markers,
    ))
    voreluth_rows, voreluth_summary = build_voreluth_vulnerability_board(
        fight, actor_map, actor_game_id, detail_debuffs, player_roles=player_roles,
    )
    local_board[VORELUTH_VULN_SKILL_KEY] = voreluth_rows

    shock_board = {}
    for shock in interference_rows:
        for interrupted in shock.get("interrupted") or []:
            name = interrupted["player"]
            row = shock_board.setdefault(name, build_board_row(name, "interferenceShockInterrupts", "干扰震荡打断", role=player_roles.get(interrupted.get("playerID"), "unknown")))
            row["hitCount"] += 1
            row["events"].append({
                **interrupted,
                "time": shock["time"],
                "fightID": fight["id"],
                "positionMs": shock.get("positionMs"),
                "counted": False,
                "verdictCounted": False,
                "displayOnly": True,
                "countReason": "干扰震荡仅展示分析，永远不计数、不进入终审",
            })
    local_board["interferenceShockInterrupts"] = list(shock_board.values())

    water_board = {}
    audit_water_events = (field_audit or {}).get("waterEvents") or []
    first_p2_water_id = next((event.get("id") for event in audit_water_events if event.get("phase") == "P2"), None)
    for water_event in audit_water_events:
        counted_event = water_event.get("phase") != "P1" and water_event.get("id") != first_p2_water_id
        for drop in water_event.get("drops") or []:
            if not drop.get("isOutlier") or drop.get("applyTimeMs") is None:
                continue
            name = drop.get("player")
            item = water_board.setdefault(name, build_board_row(name, "waterOutliers", "放水未集中", role=player_roles.get(drop.get("targetID"), "unknown")))
            item["hitCount"] += 1 if counted_event else 0
            item["events"].append({
                "time": drop.get("time"),
                "positionMs": drop.get("timeMs"),
                "phase": water_event.get("phase"),
                "group": water_event.get("index"),
                "player": name,
                "targetID": drop.get("targetID"),
                "markTime": format_time(drop.get("applyTimeMs")),
                "markPositionMs": drop.get("applyTimeMs"),
                "distanceFromCenter": drop.get("distanceFromGroupYards"),
                "distanceFromGroupYards": drop.get("distanceFromGroupYards"),
                "position": drop.get("position"),
                "fightID": fight["id"],
                "tag": f"water:{water_event.get('id')}",
                "counted": counted_event,
                "countReason": (
                    "坐标离组超过15码"
                    if counted_event else ("P1放水仅展示，不计数" if water_event.get("phase") == "P1" else "P2首轮放水豁免，仅展示不计数")
                ),
                "text": f"{name}（actor ID {drop.get('targetID')}）坐标离组 {drop.get('distanceFromGroupYards')} 码",
            })
    local_board["waterOutliers"] = list(water_board.values())

    healing_board = {}
    for death_row in void_grasp_healing:
        for healer in death_row.get("healers") or []:
            if not healer.get("insufficient"):
                continue
            name = healer["healer"]
            item = healing_board.setdefault(name, build_board_row(name, "voidGraspHealingLow", "空虚之握死亡治疗不足", role=player_roles.get(healer.get("healerID"), "unknown")))
            counted = not death_row.get("exempt")
            item["hitCount"] += 1 if counted else 0
            bow_text = (
                f"{death_row.get('bowPhase')}拉弓#{death_row.get('phaseBowGroup')}（全场#{death_row.get('bowGroup')}）"
                if death_row.get("bowGroup") else "未匹配到拉弓轮次"
            )
            healing_amount = int(healer.get("healing8s") or 0)
            item["events"].append({
                **healer,
                "death": death_row["player"],
                "deathTime": death_row["time"],
                "time": death_row["time"],
                "positionMs": death_row.get("positionMs"),
                "fightID": fight["id"],
                "phase": death_row.get("bowPhase"),
                "group": death_row.get("bowGroup"),
                "phaseGroup": death_row.get("phaseBowGroup"),
                "tag": f"bow:{death_row.get('bowID')}" if death_row.get("bowID") else None,
                "victimVerifiedDead": death_row.get("verifiedDeath") is True,
                "counted": counted,
                "countReason": (
                    "已核对死亡事件；本场死亡<8、点名时血量>50%、幻影<4且4名治疗均存活，统计死亡前8秒指定治疗量低于200000"
                    if counted else "；".join(death_row.get("exemptionReasons") or ["命中空虚之握豁免条件"])
                ),
                "text": f"{death_row['player']} 于 Fight{fight['id']} {bow_text}中阵亡（{death_row['time']}）；死亡前8秒内 {name} 对其治疗量为 {healing_amount:,}",
            })
    local_board["voidGraspHealingLow"] = list(healing_board.values())

    silver_death_board = {}
    for death_row in death_timeline:
        if death_row.get("phase") != "P1" or death_row.get("abilityID") != SILVER_ARROW_DAMAGE_ID or int(death_row.get("amount") or 0) <= 275_000:
            continue
        name = death_row["player"]
        item = silver_death_board.setdefault(name, build_board_row(name, "p1SilverArrowDeaths", "P1 银锋箭高伤致死", role=death_row.get("role", "unknown")))
        item["hitCount"] += 1
        item["deathCount"] += 1
        item["totalDamage"] += int(death_row.get("amount") or 0)
        amount = int(death_row.get("amount") or 0)
        item["events"].append({
            **death_row,
            "fightID": fight["id"],
            "counted": True,
            "verdictCounted": True,
            "countReason": "点名玩家受到超过275000的致死银锋箭",
            "text": f"{name} 死于 P1 银锋箭高伤（{amount:,}），按高伤致死计数",
        })
    local_board["p1SilverArrowDeaths"] = list(silver_death_board.values())

    p1_arrow_miss_board = {}
    p1_audit_arrows = [row for row in (field_audit or {}).get("silverArrows", []) if row.get("phase") == "P1"]
    used_arrow_ids = set()
    for expected_ms in P1_EXPECTED_ARROW_MS:
        arrow = min(
            (
                row for row in p1_audit_arrows
                if row.get("id") not in used_arrow_ids
                and abs(int(row.get("timeMs") or 0) - expected_ms) <= P1_EXPECTED_TOLERANCE_MS
            ),
            key=lambda row: abs(int(row.get("timeMs") or 0) - expected_ms),
            default=None,
        )
        if not arrow:
            continue
        used_arrow_ids.add(arrow.get("id"))
        attributions = arrow.get("p1BossAttribution") or []
        expected_target = expected_arrow_target(expected_ms)
        # 一轮银锋箭由两名玩家共同完成：任一人正确命中目标 Boss/add，
        # 或场地审计已确认 Boss/add 幽影束缚被移除，均视为本轮机制成功完成。
        # （几何归因偶发丢射线时，以 p1BossHitEvents 为准；若场地窗口漏掉束缚移除，
        #  则以 analyze_p1_arrows 成功行兜底，避免「已射死目标仍记双人空射」。）
        round_success = (
            any(row.get("hitBoss") for row in attributions)
            or bool(arrow.get("p1BossHitEvents"))
            or p1_arrow_rows_confirm_hit(p1_arrow_rows, expected_target, arrow)
        )
        if round_success:
            continue
        # 第5轮（~99.35s 殁里乌姆档）：双人空射且殁里乌姆已死 → 预期空射，不入板；
        # 双人空射且殁里乌姆仍存活 → 定罪计数。
        if is_melurium_arrow_slot(expected_ms, arrow) and not melurium_alive_in_arrow_snapshot(arrow):
            continue
        round_counted = bool(attributions)
        marked_rows = arrow.get("markedPlayerPositions") or [
            {"player": name, "targetID": None} for name in arrow.get("markedPlayers") or []
        ]
        for marked in marked_rows:
            name = marked.get("player")
            if not name:
                continue
            item = p1_arrow_miss_board.setdefault(
                name,
                build_board_row(name, "p1SilverArrowMissedFights", "P1 银锋箭射怪失误", role=player_roles.get(marked.get("targetID"), "unknown")),
            )
            item["markedCount"] = int(item.get("markedCount") or 0) + 1
            item["hitCount"] += 1 if round_counted else 0
            pair_names = [row.get("player") for row in marked_rows if row.get("player")]
            melurium_alive = melurium_alive_in_arrow_snapshot(arrow) if is_melurium_arrow_slot(expected_ms, arrow) else None
            count_reason = (
                "本轮两名银锋箭点名玩家均未命中指定Boss/add，两人各计数1次"
                if round_counted else "缺少本轮Boss命中归因证据，仅展示不计数"
            )
            if round_counted and melurium_alive is True:
                count_reason = "第5轮双人空射且殁里乌姆仍存活，判定未命中，两人各计数1次"
            item["events"].append({
                "fightID": fight["id"],
                "phase": "P1",
                "group": arrow.get("index"),
                "time": arrow.get("time"),
                "positionMs": arrow.get("timeMs"),
                "expectedTarget": expected_arrow_target(expected_ms),
                "meluriumAlive": melurium_alive,
                "players": pair_names,
                "counted": round_counted,
                "verdictCounted": round_counted,
                "displayOnly": not round_counted,
                "countReason": count_reason,
                "text": (
                    f"Fight{fight['id']} P1 第{arrow.get('index')}轮银锋箭点名{'、'.join(pair_names)}，"
                    + (
                        f"两人均未命中{expected_arrow_target(expected_ms)}"
                        + ("（殁里乌姆仍存活）" if melurium_alive is True else "")
                        if round_counted else "证据不足，暂不定罪"
                    )
                ),
            })
    local_board["p1SilverArrowMissedFights"] = list(p1_arrow_miss_board.values())

    shadow_board = {}
    p2_marked_counts = defaultdict(int)
    for bow in (field_audit or {}).get("bowGroups", []):
        if bow.get("phase") != "P2":
            continue
        for player in bow.get("players") or []:
            if player.get("phantomEligible"):
                p2_marked_counts[player.get("player")] += 1
    for bow in (field_audit or {}).get("bowGroups", []):
        if bow.get("phase") != "P2":
            continue
        marked_names = [player.get("player") for player in bow.get("players") or []]
        for player in bow.get("players") or []:
            name = player.get("player")
            if not name:
                continue
            if player.get("diedAtFire") or player.get("deathTriggeredRay"):
                item = shadow_board.setdefault(
                    name,
                    build_board_row(name, "missedShadows", "P2 拉弓未命中幻影", role=player_roles.get(player.get("targetID"), "unknown")),
                )
                item["markedCount"] = p2_marked_counts.get(name, 0)
                item["events"].append({
                    "fightID": fight["id"], "phase": "P2", "group": bow.get("index"),
                    "time": player.get("deathTime") or bow.get("fireTime"),
                    "positionMs": player.get("deathTimeMs") or bow.get("fireTimeMs"),
                    "players": marked_names, "tag": f"bow:{bow.get('id')}",
                    "counted": False, "displayOnly": True,
                    "countReason": player.get("missedPhantomExemptReason")
                    or "崩裂空无结算期间点名玩家死亡（提前结算），仅展示不计数",
                })
                continue
            confirmed_misses = [
                attr for attr in player.get("shotAttribution") or []
                if attr.get("confidence") in {"high", "medium"} and "未命中" in str(attr.get("verdict", ""))
            ]
            if not player.get("missedPhantom"):
                continue
            item = shadow_board.setdefault(name, build_board_row(name, "missedShadows", "P2 拉弓未命中幻影", role=player_roles.get(player.get("targetID"), "unknown")))
            item["markedCount"] = p2_marked_counts.get(name, 0)
            counted = bool(confirmed_misses)
            item["hitCount"] += 1 if counted else 0
            item["events"].append({
                "fightID": fight["id"], "phase": "P2", "group": bow.get("index"),
                "time": bow.get("fireTime"), "positionMs": bow.get("fireTimeMs"),
                "players": marked_names, "tag": f"bow:{bow.get('id')}",
                "attribution": confirmed_misses, "counted": counted,
                "countReason": (
                    "该玩家存在明确的职责归因未命中记录，且责任幻影在后续节点仍存活"
                    if counted else "检测到疑似未命中，但职责归因证据不足，仅展示不计数"
                ),
            })
    local_board["missedShadows"] = list(shadow_board.values())

    gravity_board = {}
    for gravity in (field_audit or {}).get("gravityRounds", []):
        first_violation = gravity.get("firstViolation") or min(
            (row for row in gravity.get("violations") or []),
            key=lambda row: int(row.get("order") or 999),
            default=None,
        )
        if not first_violation:
            continue
        name = first_violation.get("player")
        item = gravity_board.setdefault(name, build_board_row(name, "gravityLineViolation", "P3 重力坍缩违规致死", role=player_roles.get(first_violation.get("targetID"), "unknown")))
        counted = gravity.get("counted") is True
        item["hitCount"] += 1 if counted else 0
        item["deathCount"] += int(gravity.get("deathCount") or 0) if counted else 0
        item["events"].append({
            **first_violation, "fightID": fight["id"], "phase": "P3", "group": gravity.get("index"),
            "players": gravity.get("targets") or [], "deathCount": gravity.get("deathCount"),
            "deathPlayers": gravity.get("deathPlayers") or [], "counted": counted,
            "countReason": (
                f"首个违规者导致本轮减员{int(gravity.get('deathCount') or 0)}人"
                if counted else (gravity.get("exemptReason") or "本轮未满足归责计数条件，仅展示不计数")
            ),
        })
    local_board["gravityLineViolation"] = list(gravity_board.values())

    transition_abandoned = reason_key == "phase_abandon" or is_mass_abandon(deaths, bridge_deaths(deaths))

    rift_board = {}
    for slash in rift_slash_rows:
        if not slash.get("offender"):
            continue
        name = slash.get("offender")
        item = rift_board.setdefault(name, build_board_row(name, "tankRiftSlashFailure", "P2 裂隙挥砍换坦失误", role="tank"))
        counted = bool(slash.get("counted") and slash.get("causedTankDeath"))
        item["hitCount"] += 1 if counted else 0
        item["deathCount"] += 1 if counted else 0
        slash.setdefault("countReason", "满足换坦失误归责条件" if counted else "未满足完整归责条件，仅展示不计数")
        slash["counted"] = counted
        item["events"].append({**slash, "fightID": fight["id"]})
    local_board["tankRiftSlashFailure"] = list(rift_board.values())

    p15_death_rows = defaultdict(lambda: {"name": "", "hitCount": 0, "deathCount": 0, "totalDamage": 0, "events": []})
    for death_row in death_timeline:
        if death_row.get("phase") == "P1.5":
            name = death_row.get("player")
            role = death_row.get("role", "unknown")
            row = p15_death_rows[name]
            row["name"] = name
            row["role"] = role
            row["roles"] = [] if role == "unknown" else [role]
            row["spellKey"] = "p15AvoidableDeaths"
            row["spellName"] = "转阶段死亡"
            row["damageText"] = "-"
            row["hitCount"] += 1
            row["deathCount"] += 1
            is_abandon_jump = bool(
                transition_abandoned
                and death_row.get("abilityID") in {None, 3}
            )
            ability_name = death_row.get("ability") or "未知技能"
            row["events"].append({
                **death_row,
                "positionMs": int(death_row.get("absoluteTime") or 0) - int(fight["startTime"]),
                "deathCount": 1,
                "ability": ability_name,
                "counted": not is_abandon_jump,
                "countReason": (
                    "识别为团队主动跳崖重开，仅展示不计数"
                    if is_abandon_jump else "确认发生于P1.5转阶段，按转阶段死亡计数"
                ),
                "text": (
                    f"{name} 于 {death_row.get('time')} 死于【{ability_name}】"
                    + ("（主动跳崖重开）" if is_abandon_jump else "（转阶段死亡计数）")
                ),
            })
    local_board["p15AvoidableDeaths"] = sorted(p15_death_rows.values(), key=lambda item: item["deathCount"], reverse=True)
    local_board[PASSAGE_CLIFF_SKILL_KEY] = build_passage_cliff_board(
        fight, deaths, markers, death_timeline, player_roles, reason_key,
    )

    for board_rows in local_board.values():
        for board_row in board_rows:
            for board_event in board_row.get("events") or []:
                board_event.setdefault("fightID", fight["id"])
    global_exemption = apply_global_death_exemption(local_board, deaths, fight)

    return {
        "reportID": report_id,
        "fightID": fight["id"],
        "fightName": fight.get("name"),
        "date": local_start.strftime("%Y-%m-%d"),
        "startClock": local_start.strftime("%H:%M"),
        "startDateTime": local_start.strftime("%Y-%m-%d %H:%M"),
        "duration": format_time(duration_ms),
        "fightStart": fight["startTime"],
        "fightEnd": fight["endTime"],
        "fightStatus": "kill" if is_kill else "wipe",
        "isKill": is_kill,
        "kill": is_kill,
        "fightPhase": phase,
        "wipePhase": wipe_phase,
        "wipeElapsedMs": duration_ms,
        "wipeReason": wipe_reason,
        "investigation": investigation,
        "wclDeepLink": wcl_link,
        "deathTimeline": death_timeline,
        "transitionDetails": transition_details,
        "trialRecords": trial_records,
        "avoidableSummary": local_board,
        "globalExemption": global_exemption,
        "crownOfTheCosmos": {
            "phaseMarkers": {
                key: (format_time(value - fight["startTime"]) if isinstance(value, int) else None)
                for key, value in markers.items()
                if key in {"p15Start", "p2Start", "p3Transition", "p25Start", "p25End", "p3Start"}
            },
            "phaseTimeline": phase_timeline(markers, fight),
            "classificationKey": reason_key,
            "p1ArrowRows": p1_arrow_rows,
            "p1ArrowIssues": p1_arrow_issues,
            "p1ArrowAudit": p1_arrow_audit,
            "voidGraspRays": void_grasp_rays,
            "collapsingVoidDeaths": collapsing_deaths,
            "missedShadows": shadow_misses,
            "missedEnergy": energy_misses,
            "gravityRows": gravity_rows,
            "p2RangerMarkRows": p2_ranger_mark_rows,
            "voidRepulsionPlacement": void_repulsion_rows,
            "voidRepulsionRecords": void_repulsion_records,
            "voidGraspHealing": void_grasp_healing,
            "interferenceShockRows": interference_rows,
            "voreluthVulnerabilityFade": voreluth_summary,
            "p3PortalSummons": p3_portal_summons,
            "riftSlashTankSwaps": rift_slash_rows,
            "transitionAbandoned": transition_abandoned,
            "globalExemption": global_exemption,
            "fieldAuditUrl": f"crown-fight-audit.html?source=wcl_hardcore_api.json&report={report_id}&fight={fight['id']}",
            "fieldAudit": field_audit,
        },
    }


def fetch_fight_payload(token, report_id, fight, actor_game_id=None):
    progress("读取死亡事件", 2)
    deaths = fetch_events_all(token, report_id, "Deaths", fight)
    progress(f"死亡事件：{len(deaths)} 条", 2)

    casts = fetch_spell_events(token, report_id, fight, "Casts", {SILVER_HAVOC_CAST_ID, PORTAL_CAST_ID, COSMIC_DEVOUR_ID}, "读取阶段读条")
    casts += fetch_spell_events(token, report_id, fight, "Casts", {PORTAL_CAST_ID, COSMIC_DEVOUR_ID}, "读取敌方阶段读条", hostility_type="Enemies")
    shock_casts = fetch_spell_events(token, report_id, fight, "Casts", {INTERFERENCE_SHOCK_ID}, "读取干扰震荡", hostility_type="Enemies")
    player_casts = []
    shock_interrupt_table = {}
    completed_shocks = [event for event in shock_casts if str(event.get("type", "")).lower() == "cast"]
    if completed_shocks:
        shock_start = min(event.get("timestamp", 0) for event in completed_shocks)
        shock_end = max(event.get("timestamp", 0) for event in completed_shocks)
        player_casts = fetch_events_all(
            token, report_id, "Casts", fight,
            start_time=max(fight["startTime"], shock_start - 8_000),
            end_time=min(fight["endTime"], shock_end + 500),
            hostility_type="Friendlies",
        )
        progress("读取干扰震荡 Interrupts 汇总表", 2)
        shock_interrupt_table = fetch_interference_interrupt_table(token, report_id, fight)
    buffs = fetch_spell_events(token, report_id, fight, "Buffs", {COSMIC_RADIATION_BUFF_ID, COSMIC_BARRIER_ID, RAGE_STACK_ID, DEATH_COMPENSATION_ID} | ENRAGE_IDS, "读取阶段/狂暴 Buff")
    buffs += fetch_spell_events(token, report_id, fight, "Buffs", {COSMIC_RADIATION_BUFF_ID, COSMIC_BARRIER_ID, RAGE_STACK_ID} | ENRAGE_IDS, "读取敌方阶段/狂暴 Buff", hostility_type="Enemies")
    debuffs = fetch_spell_events(token, report_id, fight, "Debuffs", {1234570, TERMINAL_GUARD_DEBUFF_ID}, "读取阶段 Debuff")
    progress("读取敌方能量事件", 2)
    energy_events = fetch_events_all(token, report_id, "Resources", fight, hostility_type="Enemies", include_resources=True)
    progress(f"敌方能量事件：{len(energy_events)} 条", 2)
    markers = phase_markers(casts, buffs, debuffs, fight, energy_events)
    markers = infer_phase_markers_from_deaths(markers, deaths, fight)
    markers = sanitize_phase_markers(markers, fight)
    classification = classify_fight(fight, deaths, markers, buffs)
    progress(f"死亡归因初判：{classification['phase']} / {classification['label']}", 2)

    plan = detail_spell_plan(classification, deaths)
    needs_positions = bool(
        {VOID_REPULSION_DEBUFF_ID, VOID_GRASP_ID, SILVER_ARROW_MARK_ID} & set(plan["debuffs"])
    )
    detail_damage = fetch_spell_events(
        token,
        report_id,
        fight,
        "DamageTaken",
        plan["damage"],
        "读取明细伤害",
        include_resources=needs_positions,
    )
    detail_debuffs = debuffs + fetch_spell_events(token, report_id, fight, "Debuffs", plan["debuffs"], "读取明细 Debuff")
    detail_buffs = buffs + fetch_spell_events(token, report_id, fight, "Buffs", plan["buffs"], "读取明细 Buff")
    if P1_SHADOW_BINDING_ID in plan["debuffs"] or SILVER_RESIDUE_ID in plan["debuffs"] or CORRUPTION_ID in plan["debuffs"]:
        detail_debuffs += fetch_spell_events(
            token,
            report_id,
            fight,
            "Debuffs",
            {P1_SHADOW_BINDING_ID, SILVER_RESIDUE_ID, CORRUPTION_ID},
            "读取敌方明细 Debuff",
            hostility_type="Enemies",
        )
    if P1_SHADOW_BINDING_ID in plan["buffs"] or SILVER_RESIDUE_ID in plan["buffs"]:
        detail_buffs += fetch_spell_events(
            token,
            report_id,
            fight,
            "Buffs",
            {P1_SHADOW_BINDING_ID, SILVER_RESIDUE_ID},
            "读取敌方明细 Buff",
            hostility_type="Enemies",
        )
    detail_casts = casts + fetch_spell_events(token, report_id, fight, "Casts", plan["casts"], "读取明细读条")
    position_events = []
    if needs_positions:
        progress("读取坐标资源事件", 2)
        position_events = fetch_events_all(token, report_id, "Resources", fight, include_resources=True)
        progress(f"坐标资源事件：{len(position_events)} 条", 2)
    phantom_damage = []
    if markers.get("p2Start") and COLLAPSING_VOID_ID in plan["damage"]:
        phantom_ids = sorted(actor_id for actor_id, game_id in (actor_game_id or {}).items() if str(game_id) == str(PHANTOM_GAME_ID))
        for phantom_id in phantom_ids:
            progress(f"读取银色幻影伤害 source={phantom_id}", 2)
            phantom_damage.extend(fetch_events_all(token, report_id, "DamageDone", fight, source_id=phantom_id, hostility_type="Enemies"))
        if phantom_ids:
            progress(f"银色幻影伤害事件：{len(phantom_damage)} 条", 2)
    combatant_info = fetch_combatant_info(token, report_id, fight)
    initial_events = fetch_initial_combat_events(token, report_id, fight) if classification["key"] == "phase_abandon" else []
    healing_by_target = {}
    void_grasp_death_targets = sorted({
        death.get("targetID") for death in deaths
        if death.get("killingAbilityGameID") == VOID_GRASP_ID and death.get("targetID") is not None
    })
    for target_id in void_grasp_death_targets:
        target_deaths = [death.get("timestamp", 0) for death in deaths if death.get("targetID") == target_id and death.get("killingAbilityGameID") == VOID_GRASP_ID]
        healing_by_target[target_id] = fetch_events_all(
            token, report_id, "Healing", fight,
            start_time=max(fight["startTime"], min(target_deaths) - 8_000),
            end_time=min(fight["endTime"], max(target_deaths) + 1),
            target_id=target_id,
            hostility_type="Friendlies",
        )
    return {
        "deaths": deaths,
        "markers": markers,
        "classification": classification,
        "detailDamage": detail_damage,
        "detailDebuffs": detail_debuffs,
        "detailBuffs": detail_buffs,
        "detailCasts": detail_casts,
        "energyEvents": energy_events,
        "phantomDamage": phantom_damage,
        "positionEvents": position_events,
        "playerRoles": build_player_roles(combatant_info),
        "initialEvents": initial_events,
        "shockCasts": shock_casts,
        "playerCasts": player_casts,
        "shockInterruptTable": shock_interrupt_table,
        "healingByTarget": healing_by_target,
    }


def build_aggregated_json(report_ids):
    global _API_LOGICAL_REQUESTS
    started_at = time.perf_counter()
    with _API_METRICS_LOCK:
        _API_LOGICAL_REQUESTS = 0
    progress(f"WCL 基础地址：{WCL_BASE_URL}", 1)
    progress(f"WCL 代理：{PROXY_URL or '未启用'}", 1)
    progress("启动宇宙之冕复盘分析")
    token = get_token()
    report_id_list = [report_id.strip() for report_id in report_ids.replace(" ", "").split(",") if report_id.strip()]
    if not report_id_list:
        raise RuntimeError("请传入至少一个 WCL 日志 ID。")

    final_output = {
        "code": 200,
        "meta": {
            "analyzedReports": report_id_list,
            "mechanicVersion": "crown-of-the-cosmos-2026-07-15-court-verdict-v2",
            "version": "12.0",
            "raidKey": "void_spire",
            "raidName": "虚影尖塔",
            "bossKey": "crown_of_the_cosmos",
            "bossName": "宇宙之冕",
            "features": {"interrupts": False, "avoidableTotal": False, "avoidableLabel": "开庭面板", "transitionDetails": True, "finalVerdict": True},
            "avoidableSpells": {
                "p15AvoidableDeaths": "转阶段死亡",
                "collapsingVoidSnapAiming": "崩裂空无甩狙",
                "missedEnergy": "P2消Boss能量失误",
                "missedShadows": "P2 拉弓未命中幻影",
                "waterOutliers": "放水未集中",
                "voidGraspHealingLow": "空虚之握死亡治疗不足",
                "p1SilverArrowDeaths": "P1 银锋箭高伤致死",
                "p1SilverArrowMissedFights": "P1 银锋箭射怪失误",
                **{key: row["name"] for key, row in AVOIDABLE_DAMAGE_SPELLS.items()},
                "interferenceShockInterrupts": "干扰震荡打断",
                VORELUTH_VULN_SKILL_KEY: VORELUTH_VULN_SKILL_NAME,
                PASSAGE_CLIFF_SKILL_KEY: PASSAGE_CLIFF_SKILL_NAME,
                "gravityLineViolation": "P3 重力坍缩违规致死",
                "tankRiftSlashFailure": "P2 裂隙挥砍换坦失误",
            },
            "courtConfig": {
                "waterOutlierYards": 15,
                "voidGraspHealingThreshold8s": VOID_GRASP_HEALING_MIN,
                "globalDeathExemptionThreshold": GLOBAL_DEATH_EXEMPT_THRESHOLD,
                "designatedHealerIDs": sorted(DESIGNATED_HEALER_IDS),
                "designatedHealerNames": sorted(DESIGNATED_HEALER_NAMES),
                "verdictPointsPerCount": VERDICT_POINTS_PER_COUNT,
                "verdictTankMultiplier": VERDICT_TANK_MULTIPLIER,
            },
            "spellLabels": {str(key): value for key, value in SPELLS.items()},
        },
        "data": {"page1_wipeAnalysis": [], "page2_transitionAnalysis": {"summary": [], "fights": []}, "page3_courtBoard": {}, "page4_finalVerdict": [], "page2_avoidableBoard": {}},
    }

    field_audit_cache = {}
    cache_path = os.getenv("CROWN_FIELD_AUDIT_CACHE", "").strip()
    if cache_path and Path(cache_path).exists():
        try:
            cached_root = json.loads(Path(cache_path).read_text(encoding="utf-8"))
            for cached_fight in cached_root.get("data", {}).get("page1_wipeAnalysis", []):
                audit = (cached_fight.get("crownOfTheCosmos") or {}).get("fieldAudit")
                if audit and (audit.get("meta") or {}).get("schemaVersion") == "2026-07-14-global-exemption-v6":
                    field_audit_cache[(str(cached_fight.get("reportID")), int(cached_fight.get("fightID")))] = audit
            progress(f"复用逐技能场地缓存：{len(field_audit_cache)} 场", 1)
        except Exception as error:
            progress(f"逐技能场地缓存读取失败，将重新生成：{error}", 1)

    global_board = {}
    for report_id in report_id_list:
        progress(f"读取日志 {report_id}", 1)
        fights = fetch_report_fights(token, report_id)
        actor_map, actor_type, actor_game_id = fetch_actor_maps(token, report_id)
        progress(f"匹配到 {len(fights)} 场宇宙之冕战斗", 1)

        def analyze_one_fight(index_and_fight):
            index, fight = index_and_fight
            progress(f"分析 Fight {fight['id']} ({index}/{len(fights)})", 1)
            payload = fetch_fight_payload(token, report_id, fight, actor_game_id)
            payload["actorGameID"] = actor_game_id
            cached_audit = field_audit_cache.get((str(report_id), int(fight["id"])))
            if cached_audit:
                payload["fieldAudit"] = cached_audit
            else:
                try:
                    from tools.crown_single_fight_audit import build_single_fight_audit
                    progress(f"生成 Fight {fight['id']} 逐技能场地推演", 2)
                    payload["fieldAudit"] = build_single_fight_audit(
                        token, report_id, fight, actor_map, actor_type, actor_game_id,
                    )
                except Exception as error:
                    progress(f"Fight {fight['id']} 场地推演失败，保留开庭汇总：{error}", 2)
                    payload["fieldAudit"] = None
            fight_result = analyze_fight(report_id, fight, actor_map, actor_type, payload)
            return index, fight_result

        def report_fight_done(completed, total, result):
            _, fight_result = result
            progress(
                f"已完成 {completed}/{total} 场宇宙之冕战斗：Fight {fight_result['fightID']}",
                1,
            )

        for _, fight_result in run_parallel_indexed(
            list(enumerate(fights, start=1)),
            analyze_one_fight,
            on_complete=report_fight_done,
        ):
            merge_board(global_board, fight_result["avoidableSummary"])
            final_output["data"]["page1_wipeAnalysis"].append(fight_result)

    final_output["data"]["page2_avoidableBoard"] = {
        key: sorted(rows.values(), key=lambda item: (item["deathCount"], item["hitCount"], item["totalDamage"]), reverse=True)
        for key, rows in global_board.items()
    }
    final_output["data"]["page3_courtBoard"] = dict(final_output["data"]["page2_avoidableBoard"])

    transition_fights = []
    transition_summary = defaultdict(lambda: {"category": "", "deathCount": 0, "compensationCount": 0, "displayDeathCount": 0, "players": {}})
    for fight_result in final_output["data"]["page1_wipeAnalysis"]:
        rows = fight_result.get("transitionDetails") or []
        if not rows:
            continue
        transition_fights.append({
            "reportID": fight_result["reportID"], "fightID": fight_result["fightID"],
            "startDateTime": fight_result.get("startDateTime"), "duration": fight_result.get("duration"),
            "rows": rows,
        })
        for row in rows:
            summary = transition_summary[row["category"]]
            summary["category"] = row["category"]
            summary["deathCount"] += row.get("deathCount", 0)
            summary["compensationCount"] += row.get("compensationCount", 0)
            summary["displayDeathCount"] += row.get("displayDeathCount", 0)
            summary["players"][row["player"]] = summary["players"].get(row["player"], 0) + 1
    final_output["data"]["page2_transitionAnalysis"] = {
        "summary": [{**row, "players": [{"name": name, "count": count} for name, count in sorted(row["players"].items(), key=lambda item: item[1], reverse=True)]} for row in transition_summary.values()],
        "fights": transition_fights,
    }

    acquittals = configured_acquittals()
    verdict_players = {}
    for skill_key, rows in final_output["data"]["page3_courtBoard"].items():
        # 腐化精华 / 消能失误 / 干扰震荡等仅展示项永不进终审。
        if skill_key in {
            "collapsingVoidFriendlyFire",
            "voidGraspDeaths",
            "missedEnergy",
            "interferenceShockInterrupts",
        } | set(AVOIDABLE_DAMAGE_SPELLS):
            continue
        for row in rows:
            name = row.get("name")
            if not name or row.get("isSystem") or row.get("excludeFromCourtPlayers"):
                continue
            item = verdict_players.setdefault(name, {"name": name, "roles": [], "recognitionCount": 0, "appealAcquittalCount": acquittals.get(name, 0), "breakdown": {}, "penaltyUnits": 0.0})
            item["roles"] = merge_roles(item["roles"], row.get("roles") or [row.get("role", "unknown")])
            if skill_key == "collapsingVoidSnapAiming":
                count = int(row.get("deathCount") or 0)
            elif skill_key in {"corruptionEssenceHits", "corruptionEssenceTop3"}:
                count = sum(1 for event in row.get("events") or [] if event.get("counted"))
            else:
                count = int(row.get("hitCount") or row.get("deathCount") or 0)
            item["recognitionCount"] += count
            item["breakdown"][skill_key] = item["breakdown"].get(skill_key, 0) + count
            base_multiplier = VERDICT_TANK_MULTIPLIER if "tank" in (row.get("roles") or [row.get("role")]) else 1.0
            penalty_units = count * base_multiplier
            for event in row.get("events") or []:
                if event.get("counted") is False or event.get("scoreMultiplier") is None:
                    continue
                penalty_units += float(event.get("scoreMultiplier")) - base_multiplier
            item["penaltyUnits"] += penalty_units
    for item in verdict_players.values():
        multiplier = VERDICT_TANK_MULTIPLIER if "tank" in item.get("roles", []) else 1.0
        item["scoreMultiplier"] = multiplier
        item["appealUnitMultiplier"] = multiplier
        item["penaltyUnits"] = round(item["penaltyUnits"], 3)
        item["iqLoss"] = round(max(0, item["penaltyUnits"] - item["appealAcquittalCount"] * multiplier) * VERDICT_POINTS_PER_COUNT)
    final_output["data"]["page4_finalVerdict"] = sorted(verdict_players.values(), key=lambda item: (item["iqLoss"], item["recognitionCount"]), reverse=True)
    elapsed_seconds = round(time.perf_counter() - started_at, 3)
    with _API_METRICS_LOCK:
        logical_requests = _API_LOGICAL_REQUESTS
    final_output["meta"]["performance"] = {
        "fightCount": len(final_output["data"]["page1_wipeAnalysis"]),
        "elapsedSeconds": elapsed_seconds,
        "logicalGraphQLRequests": logical_requests,
        "maxFightThreads": int(os.getenv("WCL_MAX_FIGHT_THREADS", "4") or 4),
        "maxRequestThreads": MAX_REQUEST_THREADS,
        "note": "并发只缩短墙钟时间，不减少 WCL GraphQL 请求数或配额消耗。",
    }
    return final_output


def analyze(report_ids: str, output_path=None, catalog_entry=None, options=None):
    result = build_aggregated_json(report_ids)
    return write_json_result(result, output_path)
