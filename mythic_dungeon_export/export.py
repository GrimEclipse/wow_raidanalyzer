import argparse
import base64
import json
import os
import ssl
import time
from collections import Counter, defaultdict
from pathlib import Path
from urllib import parse, request


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "wcl_casts_log.json"


MAGISTERS_TERRACE = {
    "key": "magisters_terrace",
    "name": "魔导师平台",
    "bosses": [
        {
            "key": "boss1",
            "name": "奥能金刚库斯托斯",
            "aliases": ["Custos", "奥能金刚库斯托斯"],
            "spells": [
                {"id": 474496, "name": "震退猛击", "note": "打坦技能"},
                {"id": 1214081, "name": "奥数驱除"},
                {"id": 474345, "name": "补给协议"},
            ],
        },
        {
            "key": "boss2",
            "name": "瑟拉奈尔·日鞭",
            "aliases": ["Selin", "瑟拉奈尔", "日鞭"],
            "spells": [
                {"id": 1225792, "name": "符文印记"},
                {"id": 1225193, "name": "静默浪潮"},
            ],
        },
        {
            "key": "boss3",
            "name": "吉梅尔鲁斯",
            "aliases": ["Gemellus", "吉梅尔鲁斯"],
            "spells": [
                {"id": 1224299, "name": "星界束缚"},
                {"id": 1223847, "name": "三重复制"},
                {"id": 1284954, "name": "寰宇刺击"},
            ],
        },
        {
            "key": "boss4",
            "name": "迪詹崔乌斯",
            "aliases": ["Dizarak", "迪詹崔乌斯"],
            "spells": [
                {"id": 1280113, "name": "庞大碎片", "note": "打坦技能"},
                {"id": 1215087, "name": "不稳定的虚空精华", "note": "接球"},
            ],
        },
    ],
    "trash": [
        {"id": 145629, "name": "反魔法领域（环境）", "owner": "环境"},
        {"id": 1254338, "name": "燃烧", "owner": "炎术士"},
        {"id": 1254336, "name": "燃烧", "owner": "炎术士"},
        {"id": 1244907, "name": "符文战刃", "owner": "小怪"},
        {"id": 473258, "name": "人群驱散", "owner": "小怪"},
    ],
    "potions": [
        {"id": 1236994, "name": "鲁莽药水"},
        {"id": 1236616, "name": "圣光潜力"},
    ],
    "player_spells": [
        {"id": 102558, "name": "化身：乌索克的守护者", "owner": "熊T"},
        {"id": 20484, "name": "复生", "owner": "熊T"},
        {"id": 204066, "name": "明月普照", "owner": "熊T"},
        {"id": 1270292, "name": "明月普照", "owner": "熊T"},
        {"id": 22812, "name": "树皮术", "owner": "熊T"},
        {"id": 22842, "name": "狂暴回复", "owner": "熊T"},
        {"id": 61336, "name": "生存本能", "owner": "熊T"},
        {"id": 42650, "name": "亡者大军", "owner": "DK"},
        {"id": 51052, "name": "反魔法领域", "owner": "DK"},
        {"id": 48707, "name": "反魔法护罩", "owner": "DK"},
        {"id": 48792, "name": "冰封之韧", "owner": "DK"},
        {"id": 1233448, "name": "黑暗突变", "owner": "DK"},
        {"id": 198589, "name": "疾影", "owner": "DH"},
        {"id": 196718, "name": "黑暗", "owner": "DH"},
        {"id": 1260459, "name": "虚无之眼", "owner": "DH"},
        {"id": 1258283, "name": "光盲圣怒的道标", "owner": "龙人"},
        {"id": 442204, "name": "亘古吐息", "owner": "龙人"},
        {"id": 374227, "name": "微风", "owner": "龙人"},
        {"id": 363916, "name": "黑曜鳞片", "owner": "龙人"},
        {"id": 443028, "name": "天神御身", "owner": "奶僧"},
        {"id": 116849, "name": "作茧缚命", "owner": "奶僧"},
        {"id": 115203, "name": "壮胆酒", "owner": "奶僧"},
        {"id": 115310, "name": "还魂术", "owner": "奶僧"},
        {"id": 116841, "name": "迅如猛虎", "owner": "奶僧"},
        {"id": 115175, "name": "抚慰之雾", "owner": "奶僧"},
        {"id": 124682, "name": "氤氲之雾", "owner": "奶僧"},
    ],
}


def load_env_file():
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_env_file()

CLIENT_ID = os.getenv("WCL_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("WCL_CLIENT_SECRET", "")
WCL_BASE_URL = os.getenv("WCL_BASE_URL", "https://www.warcraftlogs.com").rstrip("/")
PROXY_URL = os.getenv("WCL_PROXY", "http://127.0.0.1:7890").strip()
VERIFY_SSL = os.getenv("WCL_VERIFY_SSL", "").strip().lower() in {"1", "true", "yes", "on"}


def opener():
    handlers = []
    if PROXY_URL:
        handlers.append(request.ProxyHandler({"http": PROXY_URL, "https": PROXY_URL}))
    if not VERIFY_SSL:
        handlers.append(request.HTTPSHandler(context=ssl._create_unverified_context()))
    return request.build_opener(*handlers)


HTTP = opener()


def post_json(url, payload=None, headers=None, form=None, timeout=90):
    headers = dict(headers or {})
    if form is not None:
        body = parse.urlencode(form).encode("utf-8")
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    else:
        body = json.dumps(payload or {}).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    req = request.Request(url, data=body, headers=headers, method="POST")
    with HTTP.open(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def get_access_token():
    if not CLIENT_ID or not CLIENT_SECRET:
        raise RuntimeError("请先在项目 .env 或系统环境变量中设置 WCL_CLIENT_ID 和 WCL_CLIENT_SECRET。")
    raw = f"{CLIENT_ID}:{CLIENT_SECRET}".encode("ascii")
    payload = post_json(
        f"{WCL_BASE_URL}/oauth/token",
        form={"grant_type": "client_credentials"},
        headers={"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")},
        timeout=30,
    )
    return payload["access_token"]


def graphql(token, query, variables):
    payload = post_json(
        f"{WCL_BASE_URL}/api/v2/client",
        payload={"query": query, "variables": variables},
        headers={"Authorization": f"Bearer {token}"},
    )
    if payload.get("errors"):
        raise RuntimeError(json.dumps(payload["errors"], ensure_ascii=False))
    return payload["data"]["reportData"]["report"]


def fetch_report_base(token, report_code):
    query = """
    query($code: String!) {
      reportData {
        report(code: $code) {
          startTime
          endTime
          title
          fights { id name encounterID startTime endTime kill }
          masterData {
            actors { id name type subType petOwner }
          }
        }
      }
    }
    """
    return graphql(token, query, {"code": report_code})


def fetch_events(
    token,
    report_code,
    data_type,
    hostility_type=None,
    start_time=0,
    end_time=999999999999,
    source_id=None,
    target_id=None,
):
    hostility_arg = ", $hostilityType: HostilityType" if hostility_type else ""
    hostility_filter = ", hostilityType: $hostilityType" if hostility_type else ""
    source_arg = ", $sourceID: Int" if source_id is not None else ""
    source_filter = ", sourceID: $sourceID" if source_id is not None else ""
    target_arg = ", $targetID: Int" if target_id is not None else ""
    target_filter = ", targetID: $targetID" if target_id is not None else ""
    query = f"""
    query($code: String!, $dataType: EventDataType!, $startTime: Float!, $endTime: Float!{hostility_arg}{source_arg}{target_arg}) {{
      reportData {{
        report(code: $code) {{
          events(dataType: $dataType, startTime: $startTime, endTime: $endTime, limit: 10000{hostility_filter}{source_filter}{target_filter}) {{
            data
            nextPageTimestamp
          }}
        }}
      }}
    }}
    """
    events = []
    current_start = start_time
    page = 1
    label = f"{data_type}/{hostility_type or 'All'}"
    while current_start < end_time:
        variables = {
            "code": report_code,
            "dataType": data_type,
            "startTime": float(current_start),
            "endTime": float(end_time),
        }
        if hostility_type:
            variables["hostilityType"] = hostility_type
        if source_id is not None:
            variables["sourceID"] = int(source_id)
        if target_id is not None:
            variables["targetID"] = int(target_id)
        report = graphql(token, query, variables)
        events_obj = report.get("events") or {}
        page_events = events_obj.get("data") or []
        events.extend(page_events)
        print(f"[export] {label} page {page}: {len(page_events)} events, total {len(events)}", flush=True)
        next_timestamp = events_obj.get("nextPageTimestamp")
        if not next_timestamp or next_timestamp <= current_start or not page_events:
            break
        current_start = next_timestamp
        page += 1
        time.sleep(0.35)
    return events


def dedupe_events(events):
    seen = set()
    unique = []
    for event in events:
        key = (
            event.get("timestamp"),
            event.get("type"),
            event.get("sourceID"),
            event.get("targetID"),
            event.get("abilityGameID"),
            event.get("amount"),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(event)
    return sorted(unique, key=lambda item: item.get("timestamp", 0))


def merge_windows(windows):
    if not windows:
        return []
    ordered = sorted(windows)
    merged = [list(ordered[0])]
    for start, end in ordered[1:]:
        last = merged[-1]
        if start <= last[1] + 1_000:
            last[1] = max(last[1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def actor_ids_for_boss(report, boss):
    aliases = {boss["name"].lower(), *(alias.lower() for alias in boss.get("aliases", []))}
    actor_ids = set()
    for actor in report.get("masterData", {}).get("actors", []):
        name = (actor.get("name") or "").lower()
        if actor.get("type") == "NPC" and any(alias and alias in name for alias in aliases):
            actor_ids.add(int(actor["id"]))
    return actor_ids


def fetch_boss_combat_events(token, report_code, report, enemy_casts, config, start_time, end_time):
    spell_to_boss = {}
    boss_lookup = {boss["key"]: boss for boss in config["bosses"]}
    for boss in config["bosses"]:
        for spell in boss["spells"]:
            spell_to_boss[spell["id"]] = boss["key"]

    source_windows = defaultdict(list)
    boss_cast_windows = defaultdict(list)
    for event in enemy_casts:
        boss_key = spell_to_boss.get(int(event.get("abilityGameID") or 0))
        if not boss_key:
            continue
        timestamp = int(event.get("timestamp", 0))
        window = (max(start_time, timestamp - 45_000), min(end_time, timestamp + 90_000))
        boss_cast_windows[boss_key].append(window)
        if event.get("sourceID") is not None:
            source_windows[int(event["sourceID"])].append(window)

    for boss_key, windows in boss_cast_windows.items():
        boss = boss_lookup[boss_key]
        for actor_id in actor_ids_for_boss(report, boss):
            source_windows[actor_id].extend(windows)

    combat_events = []
    for source_id in sorted(source_windows):
        for window_start, window_end in merge_windows(source_windows[source_id]):
            combat_events.extend(fetch_events(
                token,
                report_code,
                "DamageDone",
                "Enemies",
                window_start,
                window_end,
                source_id=source_id,
            ))
            combat_events.extend(fetch_events(
                token,
                report_code,
                "DamageTaken",
                "Enemies",
                window_start,
                window_end,
                target_id=source_id,
            ))
            combat_events.extend(fetch_events(
                token,
                report_code,
                "DamageDone",
                "Friendlies",
                window_start,
                window_end,
                target_id=source_id,
            ))
    return dedupe_events(combat_events)


def by_id(items):
    return {int(item["id"]): item for item in items if item.get("id") is not None}


def spell_maps(config):
    spells = {}
    boss_spell_to_boss = {}
    for spell in config["trash"]:
        spells[spell["id"]] = {**spell, "type": "trash"}
    for spell in config["potions"]:
        spells[spell["id"]] = {**spell, "type": "potion", "owner": "药水"}
    for spell in config["player_spells"]:
        spells[spell["id"]] = {**spell, "type": "player"}
    for boss in config["bosses"]:
        for spell in boss["spells"]:
            spells[spell["id"]] = {**spell, "type": "boss", "owner": boss["name"], "bossKey": boss["key"]}
            boss_spell_to_boss[spell["id"]] = boss["key"]
    return spells, boss_spell_to_boss


def actor_name(actor_lookup, actor_id):
    if actor_id in {None, -1, 0}:
        return ""
    actor = actor_lookup.get(int(actor_id))
    return actor.get("name") if actor else f"单位 {actor_id}"


def ability_name(ability_lookup, spell_lookup, ability_id):
    spell = spell_lookup.get(int(ability_id or 0))
    if spell:
        return spell["name"]
    ability = ability_lookup.get(int(ability_id or 0))
    return ability.get("name") if ability else f"未知技能 {ability_id}"


def round_seconds(timestamp, origin):
    return round((timestamp - origin) / 1000.0, 1)


def event_kind(event, spell_lookup):
    spell = spell_lookup.get(int(event.get("abilityGameID") or 0))
    return spell.get("type") if spell else "other"


def format_event(event, origin, actor_lookup, ability_lookup, spell_lookup, dungeon_start):
    ability_id = int(event.get("abilityGameID") or 0)
    spell = spell_lookup.get(ability_id) or {}
    source_id = event.get("sourceID")
    target_id = event.get("targetID")
    return {
        "time": round_seconds(event["timestamp"], origin),
        "dungeonTime": round_seconds(event["timestamp"], dungeon_start),
        "timestamp": event["timestamp"],
        "type": spell.get("type", "other"),
        "sourceID": source_id,
        "source": actor_name(actor_lookup, source_id) or spell.get("owner", ""),
        "targetID": target_id,
        "target": actor_name(actor_lookup, target_id),
        "abilityID": ability_id,
        "ability": ability_name(ability_lookup, spell_lookup, ability_id),
        "note": spell.get("note", ""),
    }


def infer_player_labels(events, actor_lookup, spell_lookup):
    class_score = defaultdict(Counter)
    for event in events:
        spell = spell_lookup.get(int(event.get("abilityGameID") or 0))
        if not spell or spell.get("type") not in {"player", "potion"}:
            continue
        source_id = event.get("sourceID")
        if source_id is None or source_id < 0 or source_id in actor_lookup:
            continue
        class_score[source_id][spell.get("owner") or "玩家"] += 1
    inferred = {}
    for source_id, score in class_score.items():
        label, _ = score.most_common(1)[0]
        inferred[int(source_id)] = label
    return inferred


def matching_fight_window(boss, fights):
    aliases = [boss["name"].lower(), *(alias.lower() for alias in boss.get("aliases", []))]
    candidates = []
    for fight in fights:
        name = (fight.get("name") or "").lower()
        if any(alias and alias in name for alias in aliases):
            candidates.append(fight)
    if not candidates:
        return None
    return max(candidates, key=lambda fight: fight.get("endTime", 0) - fight.get("startTime", 0))


def boss_source_ids(boss_events):
    counts = Counter(event.get("sourceID") for event in boss_events if event.get("sourceID") is not None)
    return [source_id for source_id, _ in counts.most_common()]


def death_for_sources(enemy_deaths, source_ids, after):
    source_set = set(source_ids)
    deaths = [
        event for event in enemy_deaths
        if event.get("targetID") in source_set and event.get("timestamp", 0) >= after
    ]
    return min(deaths, key=lambda event: event.get("timestamp", 0), default=None)


def combat_window_for_sources(combat_events, source_ids):
    source_set = set(source_ids)
    if not source_set:
        return None
    events = [
        event for event in combat_events
        if event.get("sourceID") in source_set or event.get("targetID") in source_set
    ]
    if not events:
        return None
    return (
        min(event.get("timestamp", 0) for event in events),
        max(event.get("timestamp", 0) for event in events),
    )


def build_potion_waves(events, actor_lookup, ability_lookup, spell_lookup, dungeon_start):
    potion_events = [
        event for event in events
        if event_kind(event, spell_lookup) == "potion"
    ]
    waves = []
    for event in sorted(potion_events, key=lambda item: item["timestamp"]):
        if not waves or event["timestamp"] - waves[-1]["startTimestamp"] > 25_000:
            waves.append({"startTimestamp": event["timestamp"], "events": []})
        waves[-1]["events"].append(format_event(event, dungeon_start, actor_lookup, ability_lookup, spell_lookup, dungeon_start))
    for index, wave in enumerate(waves, start=1):
        wave["index"] = index
        wave["time"] = round_seconds(wave["startTimestamp"], dungeon_start)
    return waves


def build_structured_payload(report_code, report, friendly_casts, enemy_casts, enemy_deaths, combat_events, config):
    actor_lookup = by_id(report.get("masterData", {}).get("actors", []))
    ability_lookup = by_id(report.get("masterData", {}).get("abilities", []))
    spell_lookup, boss_spell_to_boss = spell_maps(config)
    all_casts = sorted(friendly_casts + enemy_casts, key=lambda event: event.get("timestamp", 0))
    dungeon_start = min((event.get("timestamp", 0) for event in all_casts), default=report.get("startTime", 0))

    inferred = infer_player_labels(all_casts, actor_lookup, spell_lookup)
    players = [
        {"id": actor_id, "name": actor_name(actor_lookup, actor_id), "role": inferred.get(actor_id, "玩家")}
        for actor_id in sorted({
            int(event["sourceID"]) for event in friendly_casts
            if event.get("sourceID") is not None and event.get("sourceID") > 0
        })
    ]
    for player in players:
        if player["name"].startswith("单位 ") and player["id"] in inferred:
            player["name"] = inferred[player["id"]]

    relevant_events = [
        event for event in all_casts
        if int(event.get("abilityGameID") or 0) in spell_lookup
    ]
    boss_timelines = []
    for boss in config["bosses"]:
        spell_ids = {spell["id"] for spell in boss["spells"]}
        boss_events = [
            event for event in enemy_casts
            if int(event.get("abilityGameID") or 0) in spell_ids
        ]
        source_ids = boss_source_ids(boss_events)
        fight = matching_fight_window(boss, report.get("fights", []))
        combat_window = combat_window_for_sources(combat_events, source_ids)
        if combat_window:
            start, combat_end = combat_window
            death = death_for_sources(enemy_deaths, source_ids, start)
            end = death["timestamp"] if death else max(combat_end, max((event["timestamp"] for event in boss_events), default=combat_end))
            source = "combat"
        elif fight:
            start = fight["startTime"]
            end = fight["endTime"]
            source = "fight"
        elif boss_events:
            start = min(event["timestamp"] for event in boss_events)
            death = death_for_sources(enemy_deaths, source_ids, start)
            end = death["timestamp"] if death else max(event["timestamp"] for event in boss_events)
            source = "events"
        else:
            boss_timelines.append({
                "key": boss["key"],
                "name": boss["name"],
                "found": False,
                "events": [],
                "sourceIDs": [],
                "message": "没有命中该 Boss 的敌对施法；请重新导出 enemy casts。",
            })
            continue

        window_start = start
        window_end = end + 20_000
        window_events = [
            event for event in relevant_events
            if window_start <= event["timestamp"] <= window_end
        ]
        boss_timelines.append({
            "key": boss["key"],
            "name": boss["name"],
            "found": True,
            "windowSource": source,
            "startTime": start,
            "startDungeonTime": round_seconds(start, dungeon_start),
            "endTime": end,
            "duration": round_seconds(end, start),
            "firstBossCastTime": round_seconds(min((event["timestamp"] for event in boss_events), default=start), start),
            "sourceIDs": source_ids,
            "events": [
                format_event(event, start, actor_lookup, ability_lookup, spell_lookup, dungeon_start)
                for event in sorted(window_events, key=lambda item: item["timestamp"])
            ],
        })

    return {
        "meta": {
            "reportID": report_code,
            "title": report.get("title"),
            "startTime": report.get("startTime"),
            "endTime": report.get("endTime"),
            "exportType": "mythic-dungeon-timeline",
            "version": 2,
        },
        "dungeon": {"key": config["key"], "name": config["name"]},
        "players": players,
        "bossTimelines": boss_timelines,
        "potionWaves": build_potion_waves(relevant_events, actor_lookup, ability_lookup, spell_lookup, dungeon_start),
        "dungeonTimeline": [
            format_event(event, dungeon_start, actor_lookup, ability_lookup, spell_lookup, dungeon_start)
            for event in relevant_events
        ],
        "rawCounts": {
            "friendlyCasts": len(friendly_casts),
            "enemyCasts": len(enemy_casts),
            "enemyDeaths": len(enemy_deaths),
            "combatEvents": len(combat_events),
            "relevantEvents": len(relevant_events),
        },
    }


def load_local_events(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    return payload.get("events") or payload.get("casts") or payload.get("data") or []


def main():
    parser = argparse.ArgumentParser(description="Export WCL data for the Mythic+ timeline page.")
    parser.add_argument("--report", default=os.getenv("WCL_REPORT_IDS", "").split(",")[0].strip())
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--from-raw", help="Build structured JSON from an existing raw casts file.")
    parser.add_argument("--raw-array", action="store_true", help="Write only merged friendly/enemy cast events.")
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if args.from_raw:
        events = load_local_events(args.from_raw)
        report = {"masterData": {}, "fights": [], "title": Path(args.from_raw).name}
        payload = build_structured_payload("", report, events, [], [], [], MAGISTERS_TERRACE)
    else:
        if not args.report:
            raise SystemExit("请通过 --report 或 WCL_REPORT_IDS 指定 WCL report id。")
        token = get_access_token()
        report = fetch_report_base(token, args.report)
        start_time = 0
        end_time = max(1, int(report.get("endTime", 0) - report.get("startTime", 0))) if report.get("endTime") else 999999999999
        friendly_casts = fetch_events(token, args.report, "Casts", "Friendlies", start_time, end_time)
        enemy_casts = fetch_events(token, args.report, "Casts", "Enemies", start_time, end_time)
        enemy_deaths = fetch_events(token, args.report, "Deaths", "Enemies", start_time, end_time)
        combat_events = enemy_casts + fetch_boss_combat_events(
            token,
            args.report,
            report,
            enemy_casts,
            MAGISTERS_TERRACE,
            start_time,
            end_time,
        )
        payload = (
            sorted(friendly_casts + enemy_casts, key=lambda event: event.get("timestamp", 0))
            if args.raw_array
            else build_structured_payload(args.report, report, friendly_casts, enemy_casts, enemy_deaths, combat_events, MAGISTERS_TERRACE)
        )

    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if isinstance(payload, dict):
        counts = payload.get("rawCounts", {})
        print(f"[export] wrote {output_path} {counts}", flush=True)
    else:
        print(f"[export] wrote {output_path} ({len(payload)} cast events)", flush=True)


if __name__ == "__main__":
    main()
