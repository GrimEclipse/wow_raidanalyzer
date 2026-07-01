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

from boss_plugins.common import write_json_result

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
P1_RAGE_LIMIT_MS = 165_000
P2_EARLY_RADIATION_MS = 140_000
P15_DURATION_MS = 38_000
MYTHIC_RAID_SIZE = 20

PULL_DEATH_IDS = {1255378, 1235631, 1235553, 1243981, 1233649, 1233826, 1260027, 1242553}
SHADOW_AOE_IDS = {1261289, 1260019}
TANK_DEATH_IDS = {1, 1233787, 1233789, 1246461, 1238709}
P1_TANK_IDS = {1, 1233787, 1233789, 1238709, 1243753, 1281707}
P2_TANK_IDS = {1, 1246461}
P3_TANK_IDS = {1, 1246461, 1233787, 1233789}
AOE_DEATH_IDS = {1243743, 1260000, 1260771, 1233826, 1255739, 1234570, 1261289, 1260019}
P3_LINE_DEATH_ID = 1239095
COSMIC_DEVOUR_ID = 1238882
P15_AVOIDABLE_IDS = {1235631, 1246001, 1243981, 1235553}
DIMENSIONAL_SLASH_IDS = {1260838, 1260839}
ENRAGE_IDS = {27680, 26662, 1239672}
RAGE_STACK_ID = 1233778
SHADOW_BINDING_IDS = {1233470, 1237844}
CORRUPTION_ID = 1261531
SILVER_ARROW_MARK_ID = 1233602
RANGER_MARK_ID = 1259861
VOID_GRASP_ID = 1260027
COLLAPSING_VOID_ID = 1255378
GRAVITY_COLLAPSE_DEBUFF_ID = 1255453
COSMIC_RADIATION_BUFF_ID = 1260766
COSMIC_RADIATION_DAMAGE_ID = 1260771
PORTAL_CAST_ID = 1261339
SILVER_HAVOC_CAST_ID = 1234546

P1_ARROW_TARGETS = {
    43_466: "殆米阿尔",
    99_350: "殁里乌姆",
    125_559: "龌勒卢斯",
}

ACTOR_NAME_OVERRIDES = {
    "Alleria Windrunner": "奥蕾莉亚·风行者",
    "The Crown of the Cosmos": "宇宙之冕",
    "Mawrius": "殁里乌姆",
    "Damiar": "殆米阿尔",
    "Voreluth": "龌勒卢斯",
}


def progress(message, indent=0):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {'  ' * indent}{message}", flush=True)


def get_token():
    if not CLIENT_ID or not CLIENT_SECRET:
        raise RuntimeError("请先在项目 .env 或系统环境变量中设置 WCL_CLIENT_ID 和 WCL_CLIENT_SECRET。")
    progress(f"连接 WCL 鉴权端点：{WCL_BASE_URL}/oauth/token", 1)
    res = requests.post(
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
    res = requests.post(
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
        name = id_to_name.get(owner_id, actor_item["name"]) if owner_id else actor_item["name"]
        actor_map[actor_id] = ACTOR_NAME_OVERRIDES.get(name, name)
        actor_type[actor_id] = actor_item.get("type")
    return actor_map, actor_type


def fetch_event_page(token, report_id, data_type, fight, start_time=None, end_time=None, ability_id=None):
    ability_arg = ", $abilityID: Float" if ability_id is not None else ""
    ability_filter = ", abilityID: $abilityID" if ability_id is not None else ""
    query = f"""
    query($code: String!, $dataType: EventDataType!, $startTime: Float!, $endTime: Float!, $fightIDs: [Int]{ability_arg}) {{
      reportData {{
        report(code: $code) {{
          events(dataType: $dataType, startTime: $startTime, endTime: $endTime, fightIDs: $fightIDs, limit: 10000{ability_filter}) {{
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
    return graphql(token, query, variables)["events"]


def fetch_events_all(token, report_id, data_type, fight, start_time=None, end_time=None, ability_id=None):
    rows = []
    current_start = start_time if start_time is not None else fight["startTime"]
    final_end = end_time if end_time is not None else fight["endTime"]
    while current_start < final_end:
        page = fetch_event_page(token, report_id, data_type, fight, current_start, final_end, ability_id)
        rows.extend(page.get("data") or [])
        next_page = page.get("nextPageTimestamp")
        if not next_page or next_page <= current_start:
            break
        current_start = next_page
    return rows


def fetch_spell_events(token, report_id, fight, data_type, spell_ids, label):
    rows = []
    spell_ids = sorted(spell_ids)
    for index, spell_id in enumerate(spell_ids, start=1):
        progress(f"{label} {index}/{len(spell_ids)}：{SPELLS.get(spell_id, spell_id)} ({spell_id})", 2)
        spell_rows = fetch_events_all(token, report_id, data_type, fight, ability_id=spell_id)
        rows.extend(spell_rows)
        if spell_rows:
            progress(f"{SPELLS.get(spell_id, spell_id)}：{len(spell_rows)} 条", 2)
    return rows


def ability_id(event):
    return event.get("abilityGameID") or event.get("killingAbilityGameID") or event.get("extraAbilityGameID")


def ability_name(event):
    aid = ability_id(event)
    return event.get("abilityName") or event.get("name") or SPELLS.get(aid, str(aid or "未知"))


def actor(actor_map, actor_id):
    return actor_map.get(actor_id, f"未知({actor_id})")


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


def replay_link(report_id, fight_id, position_ms):
    return f"{WCL_BASE_URL}/reports/{report_id}?fight={fight_id}&view=replay&position={max(0, int(position_ms))}"


def event_is_apply(event):
    return str(event.get("type", "")).lower() in {"applybuff", "applydebuff", "refreshbuff", "refreshdebuff"}


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


def phase_markers(casts, buffs, debuffs, fight):
    silver_havoc_casts = [event for event in casts if ability_id(event) == SILVER_HAVOC_CAST_ID]
    p15_start = min((event.get("timestamp", 0) for event in silver_havoc_casts), default=None)

    scatter_removes = [event for event in debuffs if ability_id(event) == 1234570 and event_is_remove(event)]
    p2_start = min((event.get("timestamp", 0) for event in scatter_removes), default=None)
    if not p2_start and p15_start:
        p2_start = p15_start + P15_DURATION_MS

    radiation_applies = [event for event in buffs if ability_id(event) == COSMIC_RADIATION_BUFF_ID and event_is_apply(event)]
    radiation_removes = [event for event in buffs if ability_id(event) == COSMIC_RADIATION_BUFF_ID and event_is_remove(event)]
    p3_transition = min((event.get("timestamp", 0) for event in radiation_applies), default=None)
    p3_start = min((event.get("timestamp", 0) for event in radiation_removes), default=None)

    return {
        "p15Start": p15_start,
        "p2Start": p2_start,
        "p3Transition": p3_transition,
        "p3Start": p3_start,
        "silverHavocCasts": silver_havoc_casts,
        "radiationApplies": radiation_applies,
        "radiationRemoves": radiation_removes,
    }


def phase_at(timestamp, markers, fight):
    if markers.get("p3Start") and timestamp >= markers["p3Start"]:
        return "P3"
    if markers.get("p3Transition") and timestamp >= markers["p3Transition"]:
        return "P2转P3"
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


def death_ability_ids(deaths):
    return {death.get("killingAbilityGameID") for death in deaths if death.get("killingAbilityGameID")}


def is_bridge_death(death):
    return death.get("killingAbilityGameID") in {None, 3}


def bridge_deaths(deaths):
    return [death for death in deaths if is_bridge_death(death)]


def classify_fight(fight, deaths, markers, buffs):
    phase = primary_wipe_phase(deaths, markers, fight)
    death_ids = death_ability_ids(deaths)
    duration = fight["endTime"] - fight["startTime"]
    phase_deaths = [death for death in deaths if phase_at(death.get("timestamp", 0), markers, fight) == phase]
    pull_deaths = [death for death in phase_deaths if death.get("killingAbilityGameID") in PULL_DEATH_IDS]
    shadow_deaths = [death for death in phase_deaths if death.get("killingAbilityGameID") in SHADOW_AOE_IDS]
    tank_deaths = [death for death in phase_deaths[:3] if death.get("killingAbilityGameID") in TANK_DEATH_IDS]
    enrage_events = [event for event in buffs if ability_id(event) in ENRAGE_IDS and event_is_apply(event)]
    rage_events = [event for event in buffs if ability_id(event) == RAGE_STACK_ID and event_is_apply(event)]
    gravity_deaths = [death for death in deaths if death.get("killingAbilityGameID") == P3_LINE_DEATH_ID]

    if fight.get("kill"):
        return {"key": "kill", "phase": "已击杀", "label": "已击杀"}
    if len(bridge_deaths(deaths[:6])) >= 2:
        return {"key": "bridge_mistake", "phase": "过场", "label": "过桥 / 坠落失误"}

    if phase == "P1":
        if rage_events and duration < P1_RAGE_LIMIT_MS:
            return {"key": "p1_add_rage", "phase": "P1", "label": "P1 大怪狂暴"}
        if tank_deaths:
            return {"key": "tank_death", "phase": "P1", "label": "P1 倒坦"}
        return {"key": "p1_team_collapse", "phase": "P1", "label": "P1 团队减员过多"}

    if phase == "P1.5":
        if len(pull_deaths) >= 2:
            return {"key": "p15_pull_deaths", "phase": "P1.5", "label": "P1.5 过多玩家死于拉弓 / 跑位"}
        return {"key": "p15_team_collapse", "phase": "P1.5", "label": "P1.5 减员过多"}

    if phase in {"P2", "P2转P3"}:
        if len(pull_deaths) >= 2:
            return {"key": "p2_pull_deaths", "phase": "P2", "label": "P2 过多玩家死于拉弓"}
        if shadow_deaths:
            return {"key": "p2_shadow_aoe", "phase": "P2", "label": "银色幻影过多团血崩溃"}
        if tank_deaths:
            return {"key": "tank_death", "phase": "P2", "label": "P2 倒坦"}
        return {"key": "p2_aoe_collapse", "phase": "P2", "label": "P2 常规 AoE 团血崩溃"}

    if phase == "P3":
        if len(pull_deaths) >= 2:
            return {"key": "p3_pull_deaths", "phase": "P3", "label": "P3 过多玩家死于拉弓"}
        if enrage_events:
            return {"key": "p3_add_enrage", "phase": "P3", "label": "P3 大怪狂暴"}
        if len(gravity_deaths) > 2:
            first_gravity = min(gravity_deaths, key=lambda item: item.get("timestamp", 0))
            if len(deaths_before(deaths, first_gravity.get("timestamp", 0))) <= 2:
                return {"key": "p3_line_aoe", "phase": "P3", "label": "P3 拉线 AoE 崩溃"}
        if COSMIC_RADIATION_DAMAGE_ID in death_ids or COSMIC_DEVOUR_ID in death_ids:
            return {"key": "p3_boss_enrage", "phase": "P3", "label": "奥蕾莉亚狂暴"}
        return {"key": "p3_aoe_collapse", "phase": "P3", "label": "P3 常规 AoE 崩溃"}

    return {"key": "unknown", "phase": phase, "label": "未知归因"}


def detail_spell_plan(classification, deaths):
    key = classification["key"]
    damage_ids = set()
    debuff_ids = set()
    buff_ids = set()
    cast_ids = set()

    if key != "kill":
        debuff_ids |= {CORRUPTION_ID, SILVER_ARROW_MARK_ID}
        buff_ids |= SHADOW_BINDING_IDS
        damage_ids.add(1233649)

    if classification["phase"] == "P1" or key in {"p1_add_rage", "p1_team_collapse", "tank_death"}:
        debuff_ids |= {CORRUPTION_ID, SILVER_ARROW_MARK_ID}
        buff_ids |= SHADOW_BINDING_IDS | {RAGE_STACK_ID}
        damage_ids |= {1233649, 1255378, 1281707}

    if key in {"p15_pull_deaths", "p15_team_collapse"}:
        damage_ids |= P15_AVOIDABLE_IDS | {1234570, 1255378}

    if classification["phase"] == "P2" or key.startswith("p2"):
        debuff_ids |= {VOID_GRASP_ID, RANGER_MARK_ID}
        damage_ids |= {COLLAPSING_VOID_ID}
        buff_ids |= {COSMIC_RADIATION_BUFF_ID}

    if classification["phase"] == "P3" or key.startswith("p3"):
        debuff_ids |= {VOID_GRASP_ID, GRAVITY_COLLAPSE_DEBUFF_ID}
        damage_ids |= {COLLAPSING_VOID_ID, P3_LINE_DEATH_ID, COSMIC_RADIATION_DAMAGE_ID}
        buff_ids |= ENRAGE_IDS | {COSMIC_RADIATION_BUFF_ID}
        cast_ids |= {PORTAL_CAST_ID}

    if any(death.get("killingAbilityGameID") == 1233649 for death in deaths):
        debuff_ids.add(SILVER_ARROW_MARK_ID)
        damage_ids.add(1233649)

    if any(death.get("killingAbilityGameID") in TANK_DEATH_IDS for death in deaths[:3]):
        damage_ids |= P1_TANK_IDS | P2_TANK_IDS | P3_TANK_IDS
        buff_ids.add(RAGE_STACK_ID)

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


def analyze_p1_arrows(fight, actor_map, buffs, debuffs, damage_events):
    binding_removes = [
        event for event in buffs
        if ability_id(event) in SHADOW_BINDING_IDS and event_is_remove(event)
    ]
    corruption_removes = [
        event for event in debuffs
        if ability_id(event) == CORRUPTION_ID and event_is_remove(event)
    ]
    silver_arrow_hits = [
        event for event in damage_events
        if ability_id(event) == 1233649
    ]
    issues = []
    rows = []
    duration = fight["endTime"] - fight["startTime"]
    for expected in P1_EXPECTED_ARROW_MS:
        if duration < expected - P1_EXPECTED_TOLERANCE_MS:
            continue
        binding_hits = [
            event for event in binding_removes
            if abs(fight_elapsed(event, fight) - expected) <= P1_EXPECTED_TOLERANCE_MS
            and event_hits_expected_target(actor_map, event, expected)
        ]
        corruption_hits = [
            event for event in corruption_removes
            if abs(fight_elapsed(event, fight) - expected) <= P1_EXPECTED_TOLERANCE_MS
            and event_hits_expected_target(actor_map, event, expected)
        ]
        arrow_hits = [
            event for event in silver_arrow_hits
            if abs(fight_elapsed(event, fight) - expected) <= P1_EXPECTED_TOLERANCE_MS
            and event_hits_expected_target(actor_map, event, expected)
        ]
        if not binding_hits and not corruption_hits and not arrow_hits:
            issues.append({
                "time": format_time(expected),
                "positionMs": expected,
                "type": "missing_expected_arrow",
                "text": f"预期银锋箭未命中 {expected_arrow_target(expected)} / 未移除幽影束缚",
            })
            continue
        hit = binding_hits[0] if binding_hits else (corruption_hits[0] if corruption_hits else arrow_hits[0])
        target = event_target_name(actor_map, hit)
        nearby_corruption = [
            event for event in corruption_removes
            if abs(event.get("timestamp", 0) - hit.get("timestamp", 0)) <= 1_500
            and event_hits_expected_target(actor_map, event, expected)
        ]
        stack = max((int(event.get("stack") or event.get("stacks") or 0) for event in nearby_corruption), default=0)
        rows.append({
            "time": format_time(fight_elapsed(hit, fight)),
            "target": target,
            "stack": stack,
            "expectedTime": format_time(expected),
            "text": f"{target} 银锋箭判定成功，腐化精华约 {stack} 层",
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


def analyze_collapsing_void(fight, actor_map, actor_type, deaths, damage_events, debuffs):
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
        row["hitCount"] += 1
        row["totalDamage"] += event_amount(event)

    return sorted(rows_by_player.values(), key=lambda item: (item["deathCount"], item["hitCount"], item["totalDamage"]), reverse=True), death_rows


def analyze_p2_shadow_misses(fight, actor_map, damage_events, debuffs, markers):
    # WCL 当前日志中银色幻影命中/消失无法稳定通过 target 识别；先停用，避免误报。
    return []
    if not markers.get("p2Start"):
        return []
    fades = [
        event for event in debuffs
        if ability_id(event) == VOID_GRASP_ID and event_is_remove(event) and event.get("timestamp", 0) >= markers["p2Start"]
    ]
    misses = []
    for fade in fades:
        ts = fade.get("timestamp", 0)
        hits_shadow = False
        for event in damage_events:
            if ability_id(event) != COLLAPSING_VOID_ID:
                continue
            if abs(event.get("timestamp", 0) - ts) > 1_000:
                continue
            name = actor(actor_map, event.get("targetID")).lower()
            if "phantom" in name or "幻影" in name:
                hits_shadow = True
                break
        if not hits_shadow:
            misses.append({
                "time": format_time(fight_elapsed(fade, fight)),
                "player": actor(actor_map, fade.get("targetID")),
                "text": f"{format_time(fight_elapsed(fade, fight))} {actor(actor_map, fade.get('targetID'))} 的崩裂空无未识别到命中银色幻影",
            })
    return misses


def analyze_p2_energy(markers, fight, debuffs):
    p2_start = markers.get("p2Start")
    p3_transition = markers.get("p3Transition")
    if not p2_start or not p3_transition or p3_transition - p2_start >= P2_EARLY_RADIATION_MS:
        return []
    fades = [
        event for event in debuffs
        if ability_id(event) == RANGER_MARK_ID and event_is_remove(event) and p2_start <= event.get("timestamp", 0) <= p3_transition
    ]
    clusters = cluster_events(fades, window_ms=2_500)
    rows = []
    p2_duration = p3_transition - p2_start
    missing_energy = max(0, int(round((P2_EARLY_RADIATION_MS - p2_duration) / 1000)))
    if missing_energy:
        missing_marks = max(1, (missing_energy + 4) // 5)
        rows.append({
            "time": format_time(p3_transition - fight["startTime"]),
            "missingCount": missing_marks,
            "missingEnergy": missing_energy,
            "text": f"P2 约 {format_time(p2_duration)} 后提前进入宇宙辐射，估算少消 {missing_energy} 点能量，约 {missing_marks} 个游侠队长印记未命中 / 未生效",
        })
    for cluster in clusters:
        if len(cluster["events"]) < 2:
            rows.append({
                "time": format_time(cluster["start"] - fight["startTime"]),
                "missingCount": 2 - len(cluster["events"]),
                "text": f"{format_time(cluster['start'] - fight['startTime'])} 游侠队长印记消能人数不足",
            })
    return rows


def analyze_gravity_attribution(fight, actor_map, deaths, debuffs):
    gravity_deaths = [death for death in deaths if death.get("killingAbilityGameID") == P3_LINE_DEATH_ID]
    rows = []
    for cluster in cluster_events(gravity_deaths, window_ms=1_500):
        if len(cluster["events"]) <= 2:
            continue
        source = attribute_debuff_fade(cluster["events"][0], debuffs, fight, actor_map, GRAVITY_COLLAPSE_DEBUFF_ID, window_ms=2_000)
        rows.append({
            "time": format_time(cluster["start"] - fight["startTime"]),
            "source": source["player"] if source else "未知拉线",
            "deathCount": len(cluster["events"]),
            "players": [actor(actor_map, death.get("targetID")) for death in cluster["events"]],
            "text": f"{format_time(cluster['start'] - fight['startTime'])} 重力坍缩造成 {len(cluster['events'])} 人死亡，疑似由 {source['player'] if source else '未知拉线'} 触发",
        })
    return rows


def build_board_row(name, spell_key, spell_name, hit_count=0, death_count=0, total_damage=0, events=None):
    return {
        "name": name,
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
                "hitCount": 0,
                "deathCount": 0,
                "totalDamage": 0,
                "events": [],
            })
            merged["hitCount"] += row.get("hitCount", 0)
            merged["deathCount"] += row.get("deathCount", 0)
            merged["totalDamage"] += row.get("totalDamage", 0)
            merged["events"].extend(row.get("events", [])[:10])


def analyze_fight(report_id, fight, actor_map, actor_type, payload):
    deaths = payload["deaths"]
    markers = payload["markers"]
    classification = payload["classification"]
    detail_damage = payload["detailDamage"]
    detail_debuffs = payload["detailDebuffs"]
    detail_buffs = payload["detailBuffs"]
    detail_casts = payload["detailCasts"]

    duration_ms = fight["endTime"] - fight["startTime"]
    absolute_ms = fight["reportStartTime"] + fight["startTime"]
    local_start = get_local_datetime(absolute_ms)
    phase = classification["phase"]
    reason_key = classification["key"]

    death_timeline = []
    silver_marks = [event for event in detail_debuffs if ability_id(event) == SILVER_ARROW_MARK_ID and event_is_apply(event)]
    for death in deaths:
        ability = SPELLS.get(death.get("killingAbilityGameID"), str(death.get("killingAbilityGameID")))
        if death.get("killingAbilityGameID") is None:
            ability = "过桥 / 坠落失误"
        if death.get("killingAbilityGameID") == 1233649:
            marked = any(
                event.get("targetID") == death.get("targetID") and 0 <= death.get("timestamp", 0) - event.get("timestamp", 0) <= 10_000
                for event in silver_marks
            )
            if not marked:
                ability = "银锋箭（误伤）"
        death_timeline.append({
            "time": format_time(fight_elapsed(death, fight)),
            "absoluteTime": death.get("timestamp"),
            "player": actor(actor_map, death.get("targetID")),
            "abilityID": death.get("killingAbilityGameID"),
            "ability": ability,
        })

    is_kill = bool(fight.get("kill"))
    if is_kill:
        p1_arrow_rows, p1_arrow_issues = [], []
        collapsing_rows, collapsing_deaths = [], []
        shadow_misses = []
        energy_misses = []
        gravity_rows = []
    else:
        p1_arrow_rows, p1_arrow_issues = analyze_p1_arrows(fight, actor_map, detail_buffs, detail_debuffs, detail_damage)
        collapsing_rows, collapsing_deaths = analyze_collapsing_void(fight, actor_map, actor_type, deaths, detail_damage, detail_debuffs)
        shadow_misses = analyze_p2_shadow_misses(fight, actor_map, detail_damage, detail_debuffs, markers)
        energy_misses = analyze_p2_energy(markers, fight, detail_debuffs)
        gravity_rows = analyze_gravity_attribution(fight, actor_map, deaths, detail_debuffs)

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
                investigation = "最早 3 个死亡中出现坦克相关死亡，优先复盘坦克承伤与回响黑暗层数。"
                wcl_link = deep_link(report_id, fight["id"], "damage-taken", deaths[0]["timestamp"], 20_000, 5_000) if deaths else ""
            else:
                investigation = f"P1 直接灭团，本场死亡总人数 {len(deaths)}，归因为团队减员过多。"
        elif reason_key in {"p15_pull_deaths", "p2_pull_deaths", "p3_pull_deaths"}:
            investigation = f"本场有 {sum(1 for death in deaths if death.get('killingAbilityGameID') in PULL_DEATH_IDS)} 名玩家死于拉弓/射击/转阶段走位相关伤害。"
            wcl_link = deep_link(report_id, fight["id"], "deaths", deaths[0]["timestamp"], 15_000, 5_000) if deaths else ""
        elif reason_key == "p2_shadow_aoe":
            investigation = "死亡记录命中银色幻影相关 AoE，判定为银色幻影过多导致团血崩溃。"
            wcl_link = deep_link(report_id, fight["id"], "damage-taken", deaths[0]["timestamp"], 20_000, 5_000) if deaths else ""
        elif reason_key == "p3_add_enrage":
            portal_cast = min((event for event in detail_casts if ability_id(event) == PORTAL_CAST_ID), key=lambda item: item.get("timestamp", 0), default=None)
            investigation = "P3 发现大怪或裂隙幻影获得狂暴，判定为大怪狂暴。"
            wcl_link = replay_link(report_id, fight["id"], fight_elapsed(portal_cast, fight) - 3_000) if portal_cast else ""
        elif reason_key == "p3_line_aoe":
            investigation = gravity_rows[0]["text"] if gravity_rows else "P3 低减员状态下重力坍缩造成多人同秒死亡，判定为拉线 AoE 崩溃。"
            wcl_link = deep_link(report_id, fight["id"], "damage-taken", deaths[0]["timestamp"], 15_000, 5_000) if deaths else ""
        elif reason_key == "p3_boss_enrage":
            investigation = "玩家陆续死于宇宙辐射，判定为奥蕾莉亚狂暴；请同步检查 P2 是否提前结束。"
            wcl_link = deep_link(report_id, fight["id"], "damage-taken", deaths[0]["timestamp"], 20_000, 5_000) if deaths else ""
        elif reason_key == "bridge_mistake":
            bridge_rows = bridge_deaths(deaths[:8])
            names = "、".join(actor(actor_map, death.get("targetID")) for death in bridge_rows[:6])
            investigation = f"最早死亡中有 {len(bridge_rows)} 人属于坠落或无明确伤害记录，优先归因为过桥 / 过场失误。相关玩家：【{names}】。"
            wcl_link = replay_link(report_id, fight["id"], fight_elapsed(bridge_rows[0], fight) - 5_000) if bridge_rows else ""
        elif reason_key == "tank_death":
            investigation = "最早 3 个死亡中出现坦克相关死亡，判定为倒坦。"
            wcl_link = deep_link(report_id, fight["id"], "damage-taken", deaths[0]["timestamp"], 20_000, 5_000) if deaths else ""
        else:
            investigation = f"{phase} 阶段死亡总人数 {len(deaths)}，未命中更具体机制，归因为常规 AoE/团队减员崩溃。"
            wcl_link = deep_link(report_id, fight["id"], "damage-taken", deaths[0]["timestamp"], 20_000, 5_000) if deaths else ""

    trial_records = []
    if not is_kill and (p1_arrow_rows or p1_arrow_issues):
        trial_records.append({
            "type": "p1_arrows",
            "title": "P1 银锋箭 / 腐化精华",
            "summary": f"{len(p1_arrow_rows)} 次幽影束缚移除，{len(p1_arrow_issues)} 个异常",
            "rows": p1_arrow_rows + p1_arrow_issues,
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
            "title": "P2 拉弓未识别到命中银色幻影",
            "summary": f"{len(shadow_misses)} 次",
            "rows": shadow_misses[:20],
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

    local_board = {
        "p15AvoidableDeaths": [],
        "collapsingVoidFriendlyFire": collapsing_rows,
        "missedEnergy": [
            build_board_row("游侠队长印记", "missedEnergy", "未消到 Boss 能量", hit_count=len(energy_misses), events=energy_misses)
        ] if energy_misses else [],
    }

    p15_death_rows = defaultdict(lambda: {"name": "", "hitCount": 0, "deathCount": 0, "totalDamage": 0, "events": []})
    for death in deaths:
        if death.get("killingAbilityGameID") in P15_AVOIDABLE_IDS:
            name = actor(actor_map, death.get("targetID"))
            row = p15_death_rows[name]
            row["name"] = name
            row["spellKey"] = "p15AvoidableDeaths"
            row["spellName"] = "P1.5 跑位死亡"
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
                if key in {"p15Start", "p2Start", "p3Transition", "p3Start"}
            },
            "classificationKey": reason_key,
            "p1ArrowRows": p1_arrow_rows,
            "p1ArrowIssues": p1_arrow_issues,
            "collapsingVoidDeaths": collapsing_deaths,
            "missedShadows": shadow_misses,
            "missedEnergy": energy_misses,
            "gravityRows": gravity_rows,
        },
    }


def fetch_fight_payload(token, report_id, fight):
    progress("读取死亡事件", 2)
    deaths = fetch_events_all(token, report_id, "Deaths", fight)
    progress(f"死亡事件：{len(deaths)} 条", 2)

    casts = fetch_spell_events(token, report_id, fight, "Casts", {SILVER_HAVOC_CAST_ID, PORTAL_CAST_ID}, "读取阶段读条")
    buffs = fetch_spell_events(token, report_id, fight, "Buffs", {COSMIC_RADIATION_BUFF_ID, RAGE_STACK_ID} | ENRAGE_IDS, "读取阶段/狂暴 Buff")
    debuffs = fetch_spell_events(token, report_id, fight, "Debuffs", {1234570}, "读取阶段 Debuff")
    markers = phase_markers(casts, buffs, debuffs, fight)
    classification = classify_fight(fight, deaths, markers, buffs)
    progress(f"死亡归因初判：{classification['phase']} / {classification['label']}", 2)

    plan = detail_spell_plan(classification, deaths)
    detail_damage = fetch_spell_events(token, report_id, fight, "DamageTaken", plan["damage"], "读取明细伤害")
    detail_debuffs = debuffs + fetch_spell_events(token, report_id, fight, "Debuffs", plan["debuffs"], "读取明细 Debuff")
    detail_buffs = buffs + fetch_spell_events(token, report_id, fight, "Buffs", plan["buffs"], "读取明细 Buff")
    detail_casts = casts + fetch_spell_events(token, report_id, fight, "Casts", plan["casts"], "读取明细读条")
    return {
        "deaths": deaths,
        "markers": markers,
        "classification": classification,
        "detailDamage": detail_damage,
        "detailDebuffs": detail_debuffs,
        "detailBuffs": detail_buffs,
        "detailCasts": detail_casts,
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
            "mechanicVersion": "crown-of-the-cosmos-2026-07-01",
            "version": "12.0",
            "raidKey": "void_spire",
            "raidName": "虚影尖塔",
            "bossKey": "crown_of_the_cosmos",
            "bossName": "宇宙之冕",
            "features": {"interrupts": False},
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
        actor_map, actor_type = fetch_actor_maps(token, report_id)
        progress(f"匹配到 {len(fights)} 场宇宙之冕战斗", 1)
        for index, fight in enumerate(fights, start=1):
            progress(f"分析 Fight {fight['id']} ({index}/{len(fights)})", 1)
            payload = fetch_fight_payload(token, report_id, fight)
            fight_result = analyze_fight(report_id, fight, actor_map, actor_type, payload)
            merge_board(global_board, fight_result["avoidableSummary"])
            final_output["data"]["page1_wipeAnalysis"].append(fight_result)

    final_output["data"]["page2_avoidableBoard"] = {
        key: sorted(rows.values(), key=lambda item: (item["deathCount"], item["hitCount"], item["totalDamage"]), reverse=True)
        for key, rows in global_board.items()
    }
    return final_output


def analyze(report_ids: str, output_path=None, catalog_entry=None):
    result = build_aggregated_json(report_ids)
    return write_json_result(result, output_path)
