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
    1251812: "最终审判",
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
    20484: "复生",
    61999: "盟友复生",
    20707: "灵魂石",
    391054: "代祷",
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

AVOIDABLE_SPELLS = {
    "holyHammer": {"label": "神圣之锤", "ids": {1249047}},
    "holyBell": {"label": "圣洁鸣钟", "ids": {1248652}},
    "graceStorm": {"label": "神恩风暴", "ids": {1272324}},
}

AVOIDABLE_DAMAGE_IDS = {spell_id for config in AVOIDABLE_SPELLS.values() for spell_id in config["ids"]}
TANK_DEATH_IDS = {1251857, 1251859, 1246726, 1251812}
TANK_SIGNAL_DEATH_IDS = TANK_DEATH_IDS
TANK_DETAIL_DAMAGE_IDS = {1251857, 1251859, 1246726, 1251812}
TANK_DETAIL_DEBUFF_IDS = TANK_VULN_IDS
SPLIT_DEATH_IDS = {EXECUTION_SENTENCE_DAMAGE_ID, EXECUTED_DAMAGE_ID}
SPLIT_RELATED_DEATH_IDS = SPLIT_DEATH_IDS | {1249047}
SPLIT_DETAIL_DAMAGE_IDS = {EXECUTION_SENTENCE_DAMAGE_ID, EXECUTED_DAMAGE_ID}
SPLIT_DETAIL_DEBUFF_IDS = {1248994, EXECUTION_SENTENCE_DAMAGE_ID}
SHIELD_DETAIL_DAMAGE_IDS = {BLINDING_LIGHT_ID}
SHIELD_DETAIL_DEBUFF_IDS = {1255739}
COMBAT_RES_IDS = {20484, 61999, 20707, 391054}

ACTOR_NAME_OVERRIDES = {
    "General Amias Bellamy": "阿米尔斯·贝莱梅将军",
    "Commander Venel Lightblood": "指挥官维纳尔·光血",
    "Lightblinded Vanguard": "光盲先锋军",
}


def progress(message, indent=0):
    prefix = "  " * indent
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {prefix}{message}", flush=True)


def get_token():
    progress(f"连接 WCL 鉴权端点：{WCL_BASE_URL}/oauth/token", 1)
    if not CLIENT_ID or not CLIENT_SECRET:
        raise RuntimeError("请先在项目 .env 或系统环境变量中设置 WCL_CLIENT_ID 和 WCL_CLIENT_SECRET。")
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
        actor_map[actor_id] = id_to_name.get(owner_id, actor_item["name"]) if owner_id else actor_item["name"]
        actor_type[actor_id] = actor_item.get("type")
    return actor_map, actor_type


def fetch_event_page(token, report_id, data_type, fight, start_time=None, end_time=None, ability_id=None):
    ability_arg = f", $abilityID: Float" if ability_id is not None else ""
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


def ability_id(event):
    return event.get("abilityGameID") or event.get("killingAbilityGameID") or event.get("extraAbilityGameID")


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


def actor(actor_map, actor_id):
    name = actor_map.get(actor_id, f"未知({actor_id})")
    return ACTOR_NAME_OVERRIDES.get(name, name)


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


def build_avoidable_rows(actor_map, damage_events, deaths):
    local = {key: {} for key in AVOIDABLE_SPELLS}
    for event in damage_events:
        aid = ability_id(event)
        target = actor(actor_map, event.get("targetID"))
        for key, config in AVOIDABLE_SPELLS.items():
            if aid not in config["ids"]:
                continue
            row = local[key].setdefault(
                target,
                {
                    "name": target,
                    "spellKey": key,
                    "spellName": config["label"],
                    "totalDamage": 0,
                    "hitCount": 0,
                    "deathCount": 0,
                },
            )
            row["totalDamage"] += event_amount(event)
            row["hitCount"] += 1
    for death in deaths:
        death_id = death.get("killingAbilityGameID")
        target = actor(actor_map, death.get("targetID"))
        for key, config in AVOIDABLE_SPELLS.items():
            if death_id not in config["ids"]:
                continue
            row = local[key].setdefault(
                target,
                {
                    "name": target,
                    "spellKey": key,
                    "spellName": config["label"],
                    "totalDamage": 0,
                    "hitCount": 0,
                    "deathCount": 0,
                },
            )
            row["deathCount"] += 1
    return {key: sorted(rows.values(), key=lambda item: item["totalDamage"], reverse=True) for key, rows in local.items()}


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
                    "totalDamage": 0,
                    "hitCount": 0,
                    "deathCount": 0,
                },
            )
            merged["totalDamage"] += row.get("totalDamage", 0)
            merged["hitCount"] += row.get("hitCount", 0)
            merged["deathCount"] += row.get("deathCount", 0)


def recent_events_for_player(events, player_id, timestamp, before_ms=12_000):
    return [
        event for event in events
        if event.get("targetID") == player_id and timestamp - before_ms <= event.get("timestamp", 0) <= timestamp + 500
    ]


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


def tank_death_evidence(deaths, damage_events, debuffs, actor_map, fight, tank_player_ids):
    candidate_deaths = [
        death for death in deaths
        if death.get("killingAbilityGameID") in TANK_SIGNAL_DEATH_IDS
        and death.get("targetID") in tank_player_ids
    ]
    if not candidate_deaths:
        return []
    tank_related_damage = [event for event in damage_events if ability_id(event) in TANK_DEATH_IDS | TANK_VULN_IDS]
    tank_related_debuffs = [event for event in debuffs if ability_id(event) in TANK_VULN_IDS]
    first_death_ts = min(death.get("timestamp", 0) for death in candidate_deaths)
    last_death_ts = max(death.get("timestamp", 0) for death in candidate_deaths)
    related = [
        event for event in tank_related_damage
        if first_death_ts - 25_000 <= event.get("timestamp", 0) <= last_death_ts + 500
    ]
    for death in candidate_deaths:
        related += recent_events_for_player(tank_related_debuffs, death.get("targetID"), death.get("timestamp", 0), before_ms=25_000)
    related = sorted(related, key=lambda item: item.get("timestamp", 0))
    events = []
    seen = set()
    for event in related:
        aid = ability_id(event)
        key = (event.get("timestamp", 0) // 1000, event.get("sourceID"), event.get("targetID"), aid, event_amount(event))
        if key in seen:
            continue
        seen.add(key)
        source = actor(actor_map, event.get("sourceID"))
        target = actor(actor_map, event.get("targetID"))
        ability = tank_ability_name(event)
        amount = event_amount(event)
        amount_text = f"（{amount:,}）" if amount else ""
        events.append({
            "time": format_time(fight_elapsed(event, fight)),
            "source": source,
            "target": target,
            "ability": ability,
            "abilityID": aid,
            "amount": amount,
            "text": f"{source} 对 {target} 释放了{ability}{amount_text}",
        })
    death_lines = []
    for death in sorted(candidate_deaths, key=lambda item: item.get("timestamp", 0)):
        death_ability = SPELLS.get(death.get("killingAbilityGameID"), str(death.get("killingAbilityGameID")))
        death_lines.append({
            "time": format_time(fight_elapsed(death, fight)),
            "player": actor(actor_map, death.get("targetID")),
            "ability": death_ability,
            "text": f"{actor(actor_map, death.get('targetID'))} 死于 {death_ability}",
        })
    return [{
        "time": format_time(first_death_ts - fight["startTime"]),
        "player": "、".join(line["player"] for line in death_lines),
        "deathAbility": "、".join(line["ability"] for line in death_lines),
        "deathLine": "；".join(line["text"] for line in death_lines),
        "deathLines": death_lines,
        "deathCount": len(death_lines),
        "events": events[-12:],
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


def analyze_fight(report_id, fight, actor_map, actor_type, deaths, avoidable_damage_events, detail_damage_events, debuffs, res_events, preliminary):
    absolute_ms = fight["reportStartTime"] + fight["startTime"]
    local_start = get_local_datetime(absolute_ms)
    duration_ms = fight["endTime"] - fight["startTime"]

    local_avoidable = build_avoidable_rows(actor_map, avoidable_damage_events, deaths)
    execution_damage = [event for event in detail_damage_events if ability_id(event) in SPLIT_DEATH_IDS]
    split_death_clusters, split_damage_clusters = split_clusters(deaths, execution_damage)
    split_keys = {"split_collapse", "split_reset", "tank_swap_with_split"}
    tank_keys = {"tank_swap", "tank_swap_with_split", "avoidable_into_tank", "tank_no_bres", "aoe_after_tank_res", "aoe_before_tank"}
    tank_player_ids = infer_tank_player_ids(detail_damage_events)
    tank_players = [actor(actor_map, player_id) for player_id in sorted(tank_player_ids, key=lambda item: actor(actor_map, item))]
    res_rows = format_combat_res_events(res_events, actor_map, fight)
    tank_deaths = [
        death for death in deaths
        if death.get("killingAbilityGameID") in TANK_SIGNAL_DEATH_IDS and death.get("targetID") in tank_player_ids
    ]
    blind_light_deaths = [death for death in deaths if death.get("killingAbilityGameID") == BLINDING_LIGHT_ID]
    reason_key = preliminary["key"]
    if reason_key in {"tank_swap", "tank_swap_with_split", "avoidable_into_tank"} and not tank_deaths:
        reason_key = "split_reset" if split_death_clusters else ("reset_after_deaths" if is_likely_reset(deaths) else "aoe_collapse")
    if tank_deaths:
        first_tank_death = min(tank_deaths, key=lambda item: item.get("timestamp", 0))
        deaths_before_tank = deaths_before(deaths, first_tank_death.get("timestamp", 0))
        tank_res_after = combat_res_after_death(first_tank_death, res_rows)
        if len(deaths_before_tank) > 4:
            reason_key = "aoe_before_tank"
        elif len(deaths) > 4 and tank_res_after:
            reason_key = "aoe_after_tank_res"
        elif len(deaths) > 4 and not tank_res_after and combat_res_before_timestamp(first_tank_death.get("timestamp", 0), res_rows):
            reason_key = "tank_no_bres"

    deserters = split_deserters(deaths, split_damage_clusters, actor_map, actor_type, fight) if reason_key in split_keys else []
    tank_evidence = tank_death_evidence(deaths, detail_damage_events, debuffs, actor_map, fight, tank_player_ids) if reason_key in tank_keys else []

    is_kill = bool(fight.get("kill"))
    wipe_reason = "团队减员过多 / AoE 崩溃"
    investigation = "本场没有命中更明确的归因规则，请查看死亡时间线。"
    wcl_link = ""

    if is_kill:
        wipe_phase = "已击杀"
        wipe_reason = "已击杀"
        investigation = f"Boss 已击杀，本场不归类为灭团。战斗结束于 {format_time(duration_ms)}，下方保留死亡和明细数据。"
        wcl_link = replay_link(report_id, fight["id"], max(0, duration_ms - 3_000))
    else:
        wipe_phase = "单阶段"
        if reason_key == "reset_no_deaths":
            wipe_reason = "团队拉脱 / 无死亡记录"
            investigation = "本场没有死亡事件，通常是团队主动拉脱或重开。"
            wcl_link = replay_link(report_id, fight["id"], max(0, duration_ms - 3_000))
        elif reason_key == "tank_swap":
            wipe_reason = "换嘲失误 / 倒T"
            names = "、".join(row["player"] for row in tank_evidence) if tank_evidence else "、".join(actor(actor_map, death.get("targetID")) for death in deaths[:2])
            investigation = f"【{names}】死亡前存在审判、正义盾击或最终审判记录，优先复盘换嘲与坦克承伤。"
            wcl_link = deep_link(report_id, fight["id"], "damage-taken", deaths[0]["timestamp"], 20_000, 3_000) if deaths else ""
        elif reason_key == "tank_swap_with_split":
            split_cluster = split_death_clusters[0] if split_death_clusters else None
            split_text = split_issue_summary(split_cluster, fight)
            names = "、".join(row["player"] for row in tank_evidence) if tank_evidence else "、".join(actor(actor_map, death.get("targetID")) for death in deaths if death.get("killingAbilityGameID") in TANK_SIGNAL_DEATH_IDS)
            wipe_reason = "换嘲失误 / 倒T"
            investigation = f"最终归因指向坦克承伤或换嘲问题，【{names}】死亡前存在审判、正义盾击或最终审判记录；同时 {split_text}，分摊也存在问题。"
            wcl_link = split_replay_link(report_id, fight, split_cluster) or (deep_link(report_id, fight["id"], "damage-taken", deaths[0]["timestamp"], 20_000, 3_000) if deaths else "")
        elif reason_key == "avoidable_into_tank":
            avoidable_deaths = [death for death in deaths if death.get("killingAbilityGameID") in AVOIDABLE_DAMAGE_IDS]
            names = "、".join(actor(actor_map, death.get("targetID")) for death in avoidable_deaths[:3])
            tank_names = "、".join(row["player"] for row in tank_evidence) if tank_evidence else "、".join(actor(actor_map, death.get("targetID")) for death in deaths if death.get("killingAbilityGameID") in TANK_SIGNAL_DEATH_IDS)
            wipe_reason = "前置可躲避减员后倒T / 团队拉脱"
            investigation = f"前置有玩家【{names}】死于可躲避技能，随后【{tank_names}】出现坦克相关死亡；本场未死满，倾向减员后团队拉脱。"
            wcl_link = deep_link(report_id, fight["id"], "damage-taken", avoidable_deaths[0]["timestamp"] if avoidable_deaths else deaths[0]["timestamp"], 12_000, 5_000) if deaths else ""
        elif reason_key == "tank_no_bres":
            first_tank_death = min(tank_deaths, key=lambda item: item.get("timestamp", 0)) if tank_deaths else None
            used_before = combat_res_before_timestamp(first_tank_death.get("timestamp", 0), res_rows) if first_tank_death else []
            tank_names = "、".join(actor(actor_map, death.get("targetID")) for death in tank_deaths)
            wipe_reason = "倒T / 战复资源已用"
            investigation = f"【{tank_names}】发生坦克相关死亡，且倒T前已使用 {len(used_before)} 次战复，后续未看到对坦克的战复记录，倾向战复资源不足导致倒T无法补救。"
            wcl_link = deep_link(report_id, fight["id"], "damage-taken", first_tank_death["timestamp"], 20_000, 5_000) if first_tank_death else ""
        elif reason_key in {"split_collapse", "split_reset"} and split_death_clusters:
            cluster = split_death_clusters[0]
            wipe_reason = "分摊出现问题 / 团队拉脱" if reason_key == "split_reset" else "分摊出现问题阵亡"
            suffix = "；本场未死满，倾向团队决策拉脱。" if reason_key == "split_reset" else "，判定为分摊崩盘。"
            investigation = f"{split_issue_summary(cluster, fight)}{suffix}"
            wcl_link = split_replay_link(report_id, fight, cluster)
        elif reason_key == "shield_failed" and blind_light_deaths:
            wipe_reason = "圣洁护盾没转掉"
            investigation = "当前 pull 减员少于 4 人时出现盲目之光死亡，判定圣洁护盾未及时处理。"
            wcl_link = deep_link(report_id, fight["id"], "damage-done", blind_light_deaths[0]["timestamp"], 15_000, 2_000)
        elif reason_key == "reset_after_deaths":
            wipe_reason = "减员后团队拉脱"
            investigation = f"本场死亡总人数 {len(deaths)}，未达到全团阵亡规模，倾向团队在减员后主动拉脱或重开。"
            wcl_link = deep_link(report_id, fight["id"], "damage-taken", deaths[0]["timestamp"], 12_000, 5_000) if deaths else ""
        elif reason_key == "aoe_after_tank_res":
            tank_names = "、".join(actor(actor_map, death.get("targetID")) for death in tank_deaths)
            investigation = f"本场发生过坦克死亡（{tank_names}），但之后有战复记录，最终死亡总人数 {len(deaths)}，归因为团队减员过多 / AoE 崩溃。"
            wipe_reason = "团队减员过多 / AoE 崩溃"
            wcl_link = deep_link(report_id, fight["id"], "damage-taken", deaths[0]["timestamp"], 20_000, 5_000) if deaths else ""
        elif reason_key == "aoe_before_tank":
            tank_names = "、".join(actor(actor_map, death.get("targetID")) for death in tank_deaths)
            wipe_reason = "团队减员过多 / AoE 崩溃"
            investigation = f"倒T前团队已死亡超过 4 人，后续 {tank_names} 的坦克相关死亡更像崩溃结果；最终归因为团队减员过多 / AoE 崩溃。"
            wcl_link = deep_link(report_id, fight["id"], "damage-taken", deaths[0]["timestamp"], 20_000, 5_000) if deaths else ""
        elif reason_key == "aoe_collapse":
            wipe_reason = "团队减员过多 / AoE 崩溃"
            investigation = f"本场死亡总人数 {len(deaths)}，因团队减员过多 / AoE 崩溃灭团。"
            wcl_link = deep_link(report_id, fight["id"], "damage-taken", deaths[0]["timestamp"], 20_000, 5_000) if deaths else ""

    death_timeline = [
        {
            "time": format_time(fight_elapsed(death, fight)),
            "absoluteTime": death.get("timestamp"),
            "player": actor(actor_map, death.get("targetID")),
            "abilityID": death.get("killingAbilityGameID"),
            "ability": SPELLS.get(death.get("killingAbilityGameID"), str(death.get("killingAbilityGameID"))),
        }
        for death in deaths
    ]

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
            "summary": f"{sum(row.get('deathCount', 1) for row in tank_evidence)} 名死亡玩家存在审判、正义盾击或最终审判记录",
            "rows": tank_evidence,
        })
    if res_rows:
        trial_records.append({
            "type": "combat_res",
            "title": "战复记录",
            "summary": f"本场记录到 {len(res_rows)} 次战复施放",
            "rows": res_rows,
        })

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
        },
    }


def fetch_spell_events(token, report_id, fight, data_type, spell_ids, label):
    rows = []
    spell_ids = sorted(spell_ids)
    if not spell_ids:
        return rows
    for index, spell_id in enumerate(spell_ids, start=1):
        progress(f"{label} {index}/{len(spell_ids)}：{SPELLS.get(spell_id, spell_id)} ({spell_id})", 2)
        spell_rows = fetch_events_all(token, report_id, data_type, fight, ability_id=spell_id)
        rows.extend(spell_rows)
        if spell_rows:
            progress(f"{SPELLS.get(spell_id, spell_id)}：{len(spell_rows)} 条", 2)
    return rows


def detail_spell_ids_for_reason(reason_key, deaths):
    damage_ids = set()
    debuff_ids = set()
    has_tank_death_signal = bool(death_ability_ids(deaths) & TANK_SIGNAL_DEATH_IDS)
    if reason_key in {"tank_swap", "avoidable_into_tank"}:
        damage_ids |= TANK_DETAIL_DAMAGE_IDS
        debuff_ids |= TANK_DETAIL_DEBUFF_IDS
    elif reason_key == "tank_swap_with_split":
        damage_ids |= TANK_DETAIL_DAMAGE_IDS | SPLIT_DETAIL_DAMAGE_IDS
        debuff_ids |= TANK_DETAIL_DEBUFF_IDS | SPLIT_DETAIL_DEBUFF_IDS
    elif reason_key in {"split_collapse", "split_reset"}:
        damage_ids |= SPLIT_DETAIL_DAMAGE_IDS
        debuff_ids |= SPLIT_DETAIL_DEBUFF_IDS
    elif reason_key == "shield_failed":
        damage_ids |= SHIELD_DETAIL_DAMAGE_IDS
        debuff_ids |= SHIELD_DETAIL_DEBUFF_IDS
    elif reason_key in {"aoe_collapse", "reset_after_deaths"} and has_tank_death_signal:
        damage_ids |= TANK_DETAIL_DAMAGE_IDS
        debuff_ids |= TANK_DETAIL_DEBUFF_IDS
    return damage_ids, debuff_ids


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

    detail_damage_ids, detail_debuff_ids = detail_spell_ids_for_reason(preliminary["key"], deaths)
    if detail_damage_ids or detail_debuff_ids:
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
    return deaths, avoidable_damage_events, detail_damage_events, debuffs, res_events, preliminary


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
            },
            "avoidableSpells": {key: value["label"] for key, value in AVOIDABLE_SPELLS.items()},
            "spellLabels": {str(key): value for key, value in SPELLS.items()},
            "trialRecordTypes": {
                "split_deserters": "处决宣判分摊逃兵",
                "tank_swap": "倒T / 换嘲证据",
            },
        },
        "data": {"page1_wipeAnalysis": [], "page2_avoidableBoard": {}},
    }

    global_avoidable = {key: {} for key in AVOIDABLE_SPELLS}
    for report_id in report_id_list:
        progress(f"读取日志 {report_id}", 1)
        fights = fetch_report_fights(token, report_id)
        actor_map, actor_type = fetch_actor_maps(token, report_id)
        progress(f"匹配到 {len(fights)} 场光盲先锋军战斗", 1)
        for index, fight in enumerate(fights, start=1):
            progress(f"分析 Fight {fight['id']} ({index}/{len(fights)})", 1)
            deaths, avoidable_damage_events, detail_damage_events, debuffs, res_events, preliminary = fetch_fight_payload(token, report_id, fight)
            fight_result = analyze_fight(
                report_id,
                fight,
                actor_map,
                actor_type,
                deaths,
                avoidable_damage_events,
                detail_damage_events,
                debuffs,
                res_events,
                preliminary,
            )
            merge_avoidable(global_avoidable, fight_result["avoidableSummary"])
            final_output["data"]["page1_wipeAnalysis"].append(fight_result)

    final_output["data"]["page2_avoidableBoard"] = {
        key: sorted(rows.values(), key=lambda item: item["totalDamage"], reverse=True)
        for key, rows in global_avoidable.items()
    }
    return final_output


def analyze(report_ids: str, output_path=None, catalog_entry=None):
    result = build_aggregated_json(report_ids)
    return write_json_result(result, output_path)
