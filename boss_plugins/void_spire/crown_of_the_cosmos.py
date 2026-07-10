import json
import math
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import requests
except ModuleNotFoundError as exc:
    raise RuntimeError("缺少 requests 依赖,请检查requirements！") from exc
import urllib3

from analyzer_core.concurrency import MAX_REQUEST_THREADS, request_post, run_parallel_indexed
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
    res.raise_for_status()
    return res.json()["access_token"]


def graphql(token, query, variables):
    headers = {"Authorization": f"Bearer {token}"}
    last_error = None
    for attempt in range(1, 4):
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
            if attempt >= 3:
                raise
            progress(f"WCL 请求失败，{attempt}/3，稍后重试：{error}", 2)
            time.sleep(2 * attempt)
    else:
        raise last_error
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
    return graphql(token, query, variables)["events"]


def fetch_events_all(token, report_id, data_type, fight, start_time=None, end_time=None, ability_id=None, hostility_type=None, include_resources=False, source_id=None, target_id=None):
    rows = []
    current_start = start_time if start_time is not None else fight["startTime"]
    final_end = end_time if end_time is not None else fight["endTime"]
    while current_start < final_end:
        page = fetch_event_page(token, report_id, data_type, fight, current_start, final_end, ability_id, hostility_type, include_resources, source_id, target_id)
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


def fetch_initial_combat_events(token, report_id, fight):
    try:
        return fetch_events_all(token, report_id, "DamageDone", fight, fight["startTime"], min(fight["endTime"], fight["startTime"] + 8_000))
    except Exception as error:
        progress(f"初始进战斗事件读取失败，无法判断非预期引怪来源：{error}", 2)
        return []


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
    for cluster in cluster_events(deaths, window_ms=5_000):
        if len(cluster["events"]) >= 2:
            return phase_at(cluster["start"], markers, fight)
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


def is_abandon_after_losses(deaths, bridge_cluster):
    if not bridge_cluster:
        return False
    return len(bridge_cluster.get("events", [])) >= 2 and prior_real_death_count(deaths, bridge_cluster["start"]) >= 5


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

    if fight.get("kill"):
        return {"key": "kill", "phase": "已击杀", "label": "已击杀"}
    if first_gravity_collapse_cluster(deaths):
        return {"key": "p3_line_aoe", "phase": "P3", "label": "P3 拉线 AoE 崩溃"}
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
            return {"key": "phase_abandon", "phase": bridge_cluster_phase, "label": f"{bridge_cluster_phase} 坠崖"}
        if len(cosmic_barrier_deaths) >= max(2, int(len(phase_deaths) * 0.6)):
            return {"key": "p2_phantom_barrier", "phase": phase, "label": f"{phase} 裂隙幻影未转火"}
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
        debuff_ids |= {VOID_GRASP_ID, RANGER_MARK_ID, VOID_REPULSION_DEBUFF_ID}
        damage_ids |= {COLLAPSING_VOID_ID, VOID_REPULSION_DAMAGE_ID, 1242553, SILVER_RICOCHET_ID}
        buff_ids |= {COSMIC_RADIATION_BUFF_ID, COSMIC_BARRIER_ID}

    if classification["phase"] == "P3" or key.startswith("p3"):
        debuff_ids |= {VOID_GRASP_ID, GRAVITY_COLLAPSE_DEBUFF_ID, TERMINAL_GUARD_DEBUFF_ID, RANGER_MARK_ID, VOID_REPULSION_DEBUFF_ID}
        damage_ids |= {COLLAPSING_VOID_ID, P3_LINE_DEATH_ID, COSMIC_RADIATION_DAMAGE_ID, COSMIC_DEVOUR_ID, VOID_REPULSION_DAMAGE_ID, 1242553}
        buff_ids |= ENRAGE_IDS | {COSMIC_RADIATION_BUFF_ID}
        cast_ids |= {PORTAL_CAST_ID}

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
        wrong_target_hit = (wrong_binding_hits or wrong_residue_hits or wrong_corruption_hits)
        if wrong_target_hit:
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
        row["spellName"] = "崩裂空无误伤"
        source_id = source.get("targetID") if source else None
        source_role = player_roles.get(source_id, "unknown")
        row["role"] = source_role
        row["roles"] = [] if source_role == "unknown" else [source_role]
        row["deathCount"] += 1
        row["hitCount"] += 1
        row["events"].append({
            "time": format_time(fight_elapsed(death, fight)),
            "target": target,
            "source": source_name,
            "ability": "崩裂空无",
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
        row["spellName"] = "崩裂空无误伤"
        source_id = source.get("targetID") if source else None
        source_role = player_roles.get(source_id, "unknown")
        row["role"] = source_role
        row["roles"] = [] if source_role == "unknown" else [source_role]
        row["hitCount"] += 1
        row["totalDamage"] += event_amount(event)

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
                "text": f"{format_time(cluster['start'] - fight['startTime'])} 第 {index} 组游侠队长印记消失人数不足：{player_names}",
            })
        elif not nearby_drains:
            rows.append({
                "time": format_time(cluster["start"] - fight["startTime"]),
                "group": index,
                "missingCount": 0,
                "players": [row["player"] for row in players],
                "text": f"{format_time(cluster['start'] - fight['startTime'])} 第 {index} 组游侠队长印记已消失 2 人（{player_names}），但未识别到奥蕾莉亚能量 -5（1259998）",
            })
    return rows


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
                "deathCount": 0,
                "totalDamage": 0,
                "damageText": row.get("damageText"),
                "events": [],
            })
            merged["roles"] = merge_roles(merged.get("roles"), row.get("roles") or ([] if row.get("role") in {None, "", "unknown"} else [row.get("role")]))
            merged["role"] = merged["roles"][0] if merged["roles"] else (row.get("role") or merged.get("role") or "unknown")
            merged["hitCount"] += row.get("hitCount", 0)
            merged["deathCount"] += row.get("deathCount", 0)
            merged["totalDamage"] += row.get("totalDamage", 0)
            if row.get("damageText"):
                merged["damageText"] = row.get("damageText")
            merged["events"].extend(row.get("events", [])[:10])


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


def build_void_repulsion_records(fight, actor_map, debuffs, markers, resource_events=None, casts=None, actor_game_id=None, damage_events=None):
    resource_events = resource_events or []
    casts = casts or []
    damage_events = damage_events or []
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


def analyze_void_repulsion_placement(fight, actor_map, debuffs, markers, resource_events=None, casts=None, actor_game_id=None, damage_events=None):
    records = build_void_repulsion_records(fight, actor_map, debuffs, markers, resource_events, casts, actor_game_id, damage_events)
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


def first_combat_initiator(initial_events, actor_map, actor_type):
    candidates = []
    for event in initial_events:
        source_id = event.get("sourceID")
        target_id = event.get("targetID")
        if not source_id or actor_type.get(source_id) != "Player":
            continue
        if actor_type.get(target_id) == "Player":
            continue
        amount = event_amount(event)
        candidates.append((event.get("timestamp", 0), amount, source_id))
    if not candidates:
        return None
    _, _, source_id = min(candidates, key=lambda item: item[0])
    return {
        "id": source_id,
        "name": actor(actor_map, source_id),
    }


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
        void_repulsion_rows, void_repulsion_records = analyze_void_repulsion_placement(fight, actor_map, detail_debuffs, markers, position_events, detail_casts, actor_game_id, detail_damage)
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
        void_repulsion_rows, void_repulsion_records = analyze_void_repulsion_placement(fight, actor_map, detail_debuffs, markers, position_events, detail_casts, actor_game_id, detail_damage)

    void_grasp_rays = analyze_void_grasp_rays(fight, actor_map, actor_type, actor_game_id, detail_debuffs, detail_damage, position_events, markers)
    p1_arrow_audit = analyze_p1_arrow_audit(fight, actor_map, detail_debuffs, detail_damage, markers, p1_arrow_rows)

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
            investigation = f"本场有 {sum(1 for death in deaths if death.get('killingAbilityGameID') in PULL_DEATH_IDS)} 名玩家死于拉弓/射击/转阶段走位相关伤害。"
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
            investigation = f"团队选择放弃或非预期引怪后快速重开。在选择重开前已有{deaths_before_repull}人死亡。"
            initiator = first_combat_initiator(initial_events, actor_map, actor_type)
            if initiator:
                investigation += f" 初始进战斗来源疑似为 {initiator['name']}。"
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
            "title": "崩裂空无误伤致死",
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
            for phase in ["P1", "P1.5", "P2", "P2.5", "P3"]:
                phase_records = [record for record in void_repulsion_records if record.get("phase") == phase]
                if not phase_records:
                    continue
                phase_rows.append({
                    "time": phase_records[0].get("time"),
                    "phase": phase,
                    "details": phase_records,
                    "text": f"{phase} 已记录 {len(phase_records)} 个虚空斥力放水点。",
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
        for player in event.get("players") or []:
            row = missed_energy_board.setdefault(player, build_board_row(player, "missedEnergy", "未消到 Boss 能量", role="unknown"))
            row["hitCount"] += 1
            row["events"].append(event)

    local_board = {
        "p15AvoidableDeaths": [],
        "collapsingVoidFriendlyFire": collapsing_rows,
        "missedEnergy": list(missed_energy_board.values()),
    }

    p15_death_rows = defaultdict(lambda: {"name": "", "hitCount": 0, "deathCount": 0, "totalDamage": 0, "events": []})
    for death in deaths:
        if death.get("killingAbilityGameID") in P15_AVOIDABLE_IDS:
            name = actor(actor_map, death.get("targetID"))
            role = player_roles.get(death.get("targetID"), "unknown")
            row = p15_death_rows[name]
            row["name"] = name
            row["role"] = role
            row["roles"] = [] if role == "unknown" else [role]
            row["spellKey"] = "p15AvoidableDeaths"
            row["spellName"] = "P1.5 跑位死亡"
            row["damageText"] = "-"
            row["hitCount"] += 1
            row["deathCount"] += 1
            row["events"].append({
                "time": format_time(fight_elapsed(death, fight)),
                "ability": SPELLS.get(death.get("killingAbilityGameID"), str(death.get("killingAbilityGameID"))),
            })
    local_board["p15AvoidableDeaths"] = sorted(p15_death_rows.values(), key=lambda item: item["deathCount"], reverse=True)

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
        "trialRecords": trial_records,
        "avoidableSummary": local_board,
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
        },
    }


def fetch_fight_payload(token, report_id, fight, actor_game_id=None):
    progress("读取死亡事件", 2)
    deaths = fetch_events_all(token, report_id, "Deaths", fight)
    progress(f"死亡事件：{len(deaths)} 条", 2)

    casts = fetch_spell_events(token, report_id, fight, "Casts", {SILVER_HAVOC_CAST_ID, PORTAL_CAST_ID}, "读取阶段读条")
    casts += fetch_spell_events(token, report_id, fight, "Casts", {PORTAL_CAST_ID}, "读取敌方阶段读条", hostility_type="Enemies")
    buffs = fetch_spell_events(token, report_id, fight, "Buffs", {COSMIC_RADIATION_BUFF_ID, COSMIC_BARRIER_ID, RAGE_STACK_ID} | ENRAGE_IDS, "读取阶段/狂暴 Buff")
    buffs += fetch_spell_events(token, report_id, fight, "Buffs", {COSMIC_RADIATION_BUFF_ID, COSMIC_BARRIER_ID, RAGE_STACK_ID} | ENRAGE_IDS, "读取敌方阶段/狂暴 Buff", hostility_type="Enemies")
    debuffs = fetch_spell_events(token, report_id, fight, "Debuffs", {1234570, TERMINAL_GUARD_DEBUFF_ID}, "读取阶段 Debuff")
    progress("读取敌方能量事件", 2)
    energy_events = fetch_events_all(token, report_id, "Resources", fight, hostility_type="Enemies", include_resources=True)
    progress(f"敌方能量事件：{len(energy_events)} 条", 2)
    markers = phase_markers(casts, buffs, debuffs, fight, energy_events)
    markers = infer_phase_markers_from_deaths(markers, deaths, fight)
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
    }


def build_aggregated_json(report_ids):
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
            "mechanicVersion": "crown-of-the-cosmos-2026-07-06",
            "version": "12.0",
            "raidKey": "void_spire",
            "raidName": "虚影尖塔",
            "bossKey": "crown_of_the_cosmos",
            "bossName": "宇宙之冕",
            "features": {"interrupts": False, "avoidableTotal": False, "avoidableLabel": "开庭分析"},
            "avoidableSpells": {
                "p15AvoidableDeaths": "P1.5 跑位死亡",
                "collapsingVoidFriendlyFire": "崩裂空无误伤",
                "missedEnergy": "未消到 Boss 能量",
            },
            "spellLabels": {str(key): value for key, value in SPELLS.items()},
        },
        "data": {"page1_wipeAnalysis": [], "page2_avoidableBoard": {}},
    }

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
    return final_output


def analyze(report_ids: str, output_path=None, catalog_entry=None, options=None):
    result = build_aggregated_json(report_ids)
    return write_json_result(result, output_path)
