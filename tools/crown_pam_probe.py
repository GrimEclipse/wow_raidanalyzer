import json
import math
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


REPORT_ID = "PAMtmJz8rNywYVQT"
SOURCE_CHECKS = [
    {"reportID": "PAMtmJz8rNywYVQT", "fightID": 30},
    {"reportID": "AGkdfNWKtR28xMTB", "fightID": 24},
]
OUT_PATH = Path("tmp") / "crown_pam_probe.json"

SPELL = {
    "silver_arrow_mark": 1233602,
    "silver_arrow_damage": 1233649,
    "silver_havoc": 1234546,
    "star_scatter": 1234570,
    "void_repulsion_mark": 1283236,
    "void_repulsion_damage": 1233826,
    "corruption": 1261531,
    "ranger_mark": 1259861,
    "silver_ricochet": 1259869,
    "silver_ricochet_energy_drain": 1259998,
    "cosmic_barrier": 1261289,
    "cosmic_radiation": 1260766,
    "portal": 1261339,
    "void_grasp": 1260027,
    "collapsing_void": 1255378,
}

NPC_IDS = {
    240430: "奥蕾莉亚",
    243805: "殁里乌姆",
    243810: "殆米阿尔",
    243811: "龌勒卢斯",
    254172: "龌勒卢斯",
    254173: "殆米阿尔",
    254174: "殁里乌姆",
}

PHANTOM_GAME_ID = 253742
P15_DURATION_MS = 38_000
P1_MIN_TRANSITION_START_MS = 123_559


def load_env_file():
    search_dirs = [Path.cwd(), Path(__file__).resolve().parents[1]]
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
        return


load_env_file()

CLIENT_ID = os.getenv("WCL_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("WCL_CLIENT_SECRET", "")
WCL_BASE_URL = os.getenv("WCL_BASE_URL", "https://www.warcraftlogs.com").rstrip("/")
PROXY_URL = os.getenv("WCL_PROXY", "http://127.0.0.1:7890").strip()
SSL_CONTEXT = ssl._create_unverified_context()


def opener():
    handlers = []
    if PROXY_URL:
        handlers.append(urllib.request.ProxyHandler({"http": PROXY_URL, "https": PROXY_URL}))
    handlers.append(urllib.request.HTTPSHandler(context=SSL_CONTEXT))
    return urllib.request.build_opener(*handlers)


HTTP = opener()


def http_json(url, data=None, headers=None, form=False):
    body = None
    if isinstance(data, dict) and form:
        body = urllib.parse.urlencode(data).encode("utf-8")
    elif data is not None:
        body = json.dumps(data).encode("utf-8")
        headers = {"Content-Type": "application/json", **(headers or {})}
    request = urllib.request.Request(url, data=body, headers=headers or {}, method="POST" if data is not None else "GET")
    last_error = None
    for attempt in range(1, 4):
        try:
            with HTTP.open(request, timeout=90) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {error.code}: {detail[:500]}") from error
        except Exception as error:
            last_error = error
            if attempt >= 3:
                raise
            time.sleep(2 * attempt)
    raise last_error


def get_token():
    if not CLIENT_ID or not CLIENT_SECRET:
        raise RuntimeError("missing WCL_CLIENT_ID / WCL_CLIENT_SECRET")
    raw = f"{CLIENT_ID}:{CLIENT_SECRET}".encode("ascii")
    auth = urllib.request.base64.b64encode(raw).decode("ascii") if hasattr(urllib.request, "base64") else None
    if auth is None:
        import base64
        auth = base64.b64encode(raw).decode("ascii")
    payload = http_json(
        f"{WCL_BASE_URL}/oauth/token",
        data={"grant_type": "client_credentials"},
        headers={"Authorization": f"Basic {auth}"},
        form=True,
    )
    return payload["access_token"]


def graphql(token, query, variables):
    payload = http_json(
        f"{WCL_BASE_URL}/api/v2/client",
        data={"query": query, "variables": variables},
        headers={"Authorization": f"Bearer {token}"},
    )
    if payload.get("errors"):
        raise RuntimeError(json.dumps(payload["errors"], ensure_ascii=False))
    return payload["data"]["reportData"]["report"]


def fetch_report_fights(token, report_id):
    fields = "id name startTime endTime kill friendlyPlayers"
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
    try:
        report = graphql(token, query, {"code": report_id})
    except RuntimeError:
        query = query.replace(" friendlyPlayers", "")
        report = graphql(token, query, {"code": report_id})
    valid = []
    for fight in report["fights"]:
        name = (fight.get("name") or "").lower()
        duration = fight["endTime"] - fight["startTime"]
        if duration < 20_000:
            continue
        if any(keyword in name for keyword in ["crown of the cosmos", "alleria", "奥蕾莉亚", "宇宙之冕"]):
            fight["reportStartTime"] = report["startTime"]
            valid.append(fight)
    return valid


def fetch_actor_maps(token, report_id):
    query = """
    query($code: String!) {
      reportData {
        report(code: $code) {
          masterData { actors { id name type petOwner gameID subType } }
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
    actor_game_id = {}
    for actor_item in actors:
        actor_id = actor_item["id"]
        owner_id = pet_to_owner.get(actor_id)
        name = id_to_name.get(owner_id, actor_item["name"]) if owner_id else actor_item["name"]
        actor_map[actor_id] = name
        actor_type[actor_id] = actor_item.get("type")
        actor_game_id[actor_id] = actor_item.get("gameID") or actor_item.get("subType")
    return actor_map, actor_type, actor_game_id


def fetch_event_page(token, report_id, data_type, fight, start_time=None, end_time=None, ability_id=None, hostility_type=None, include_resources=False):
    ability_arg = ", $abilityID: Float" if ability_id is not None else ""
    ability_filter = ", abilityID: $abilityID" if ability_id is not None else ""
    hostility_arg = ", $hostilityType: HostilityType" if hostility_type else ""
    hostility_filter = ", hostilityType: $hostilityType" if hostility_type else ""
    resources_arg = ", $includeResources: Boolean" if include_resources else ""
    resources_filter = ", includeResources: $includeResources" if include_resources else ""
    query = f"""
    query($code: String!, $dataType: EventDataType!, $startTime: Float!, $endTime: Float!, $fightIDs: [Int]{ability_arg}{hostility_arg}{resources_arg}) {{
      reportData {{
        report(code: $code) {{
          events(dataType: $dataType, startTime: $startTime, endTime: $endTime, fightIDs: $fightIDs, limit: 10000{ability_filter}{hostility_filter}{resources_filter}) {{
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
    return graphql(token, query, variables)["events"]


def fetch_events_all(token, report_id, data_type, fight, start_time=None, end_time=None, ability_id=None, hostility_type=None, include_resources=False):
    rows = []
    current_start = start_time if start_time is not None else fight["startTime"]
    final_end = end_time if end_time is not None else fight["endTime"]
    while current_start < final_end:
        page = fetch_event_page(token, report_id, data_type, fight, current_start, final_end, ability_id, hostility_type, include_resources)
        rows.extend(page.get("data") or [])
        next_page = page.get("nextPageTimestamp")
        if not next_page or next_page <= current_start:
            break
        current_start = next_page
    return rows


def fmt(ms):
    if ms is None:
        return None
    ms = int(ms)
    s = max(0, ms // 1000)
    return f"{s // 60:02d}:{s % 60:02d}.{ms % 1000:03d}"


def rel(fight, ts):
    if ts is None:
        return None
    return ts - fight["startTime"]


def event_type(event):
    return str(event.get("type") or "").lower()


def ability_id(event):
    return event.get("abilityGameID") or (event.get("ability") or {}).get("gameID")


def event_point(event, prefix=""):
    if not event:
        return None
    pairs = [
        (f"{prefix}x", f"{prefix}y"),
        (f"{prefix}X", f"{prefix}Y"),
        (f"{prefix}positionX", f"{prefix}positionY"),
        (f"{prefix}PositionX", f"{prefix}PositionY"),
    ]
    for xk, yk in pairs:
        if xk in event and yk in event:
            try:
                return float(event[xk]), float(event[yk])
            except (TypeError, ValueError):
                pass
    for key in (f"{prefix}position", f"{prefix}Position", f"{prefix}location", f"{prefix}Location"):
        value = event.get(key)
        if isinstance(value, dict):
            try:
                return float(value.get("x") or value.get("X")), float(value.get("y") or value.get("Y"))
            except (TypeError, ValueError):
                pass
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            try:
                return float(value[0]), float(value[1])
            except (TypeError, ValueError):
                pass
    return None


def actor_name(actor_map, actor_game_id, actor_id):
    if actor_id is None:
        return "?"
    game_id = actor_game_id.get(actor_id)
    if game_id in NPC_IDS:
        return NPC_IDS[game_id]
    return actor_map.get(actor_id) or f"#{actor_id}"


def group_by_window(events, window_ms):
    groups = []
    for event in sorted(events, key=lambda item: item.get("timestamp", 0)):
        ts = event.get("timestamp", 0)
        if not groups or ts - groups[-1]["end"] > window_ms:
            groups.append({"start": ts, "end": ts, "events": [event]})
        else:
            groups[-1]["end"] = ts
            groups[-1]["events"].append(event)
    return groups


def stacks_from_event(event):
    for key in ("stack", "stacks", "stackCount"):
        value = event.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    return None


def corruption_before(events, target_id, timestamp):
    stack = 0
    for event in sorted(events, key=lambda item: item.get("timestamp", 0)):
        if event.get("targetID") != target_id or event.get("timestamp", 0) >= timestamp:
            continue
        etype = event_type(event)
        seen = stacks_from_event(event)
        if "remove" in etype:
            stack = 0
        elif seen is not None:
            stack = seen
        elif "apply" in etype:
            stack = max(stack, 1)
    return stack


def build_positions(resource_events):
    positions = defaultdict(list)
    for event in resource_events:
        point = event_point(event)
        if not point:
            continue
        for actor_id in (event.get("targetID"), event.get("sourceID")):
            if actor_id is not None:
                positions[actor_id].append((event.get("timestamp", 0), point[0], point[1]))
                break
    for rows in positions.values():
        rows.sort(key=lambda item: item[0])
    return positions


def replay_position(positions, actor_id, timestamp, max_gap_ms=10_000):
    rows = positions.get(actor_id) or []
    before = None
    after = None
    for row in rows:
        if row[0] <= timestamp:
            before = row
        elif row[0] > timestamp:
            after = row
            break
    if before and before[0] == timestamp:
        return {"x": before[1], "y": before[2], "source": "resources_exact", "deltaMs": 0}
    if before and after and after[0] - before[0] <= max_gap_ms:
        span = after[0] - before[0]
        ratio = 0 if span <= 0 else (timestamp - before[0]) / span
        x = before[1] + (after[1] - before[1]) * ratio
        y = before[2] + (after[2] - before[2]) * ratio
        jump = math.dist((before[1], before[2]), (after[1], after[2]))
        return {
            "x": x,
            "y": y,
            "source": "resources_interpolated",
            "beforeDeltaMs": before[0] - timestamp,
            "afterDeltaMs": after[0] - timestamp,
            "jump": jump,
        }
    if before and timestamp - before[0] <= max_gap_ms:
        return {"x": before[1], "y": before[2], "source": "resources_before", "deltaMs": before[0] - timestamp}
    if after and after[0] - timestamp <= max_gap_ms:
        return {"x": after[1], "y": after[2], "source": "resources_after", "deltaMs": after[0] - timestamp}
    return None


def point_payload(pos):
    if not pos:
        return {"hasPosition": False}
    payload = {"hasPosition": True, "x": round(pos["x"], 2), "y": round(pos["y"], 2), "source": pos["source"]}
    for key in ("deltaMs", "beforeDeltaMs", "afterDeltaMs", "jump"):
        if key in pos:
            payload[key] = round(pos[key], 2) if isinstance(pos[key], float) else pos[key]
    return payload


def paired_marks(events, spell_id, start, end, window_ms):
    rows = [
        event for event in events
        if ability_id(event) == spell_id
        and "apply" in event_type(event)
        and start <= event.get("timestamp", 0) <= end
    ]
    return group_by_window(rows, window_ms)


def debuff_removes(events, spell_id, start, end):
    return [
        event for event in events
        if ability_id(event) == spell_id
        and "remove" in event_type(event)
        and start <= event.get("timestamp", 0) <= end
    ]


def first_event(events, spell_id, kind=None, start=None, end=None):
    rows = []
    for event in events:
        if ability_id(event) != spell_id:
            continue
        if kind and kind not in event_type(event):
            continue
        ts = event.get("timestamp", 0)
        if start is not None and ts < start:
            continue
        if end is not None and ts > end:
            continue
        rows.append(event)
    return min(rows, key=lambda item: item.get("timestamp", 0), default=None)


def fetch_event_page_ext(token, report_id, data_type, fight, start_time=None, end_time=None, ability_id=None, hostility_type=None, include_resources=False, source_id=None, target_id=None):
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


def fetch_events_all_ext(token, report_id, data_type, fight, start_time=None, end_time=None, **kwargs):
    rows = []
    current_start = start_time if start_time is not None else fight["startTime"]
    final_end = end_time if end_time is not None else fight["endTime"]
    while current_start < final_end:
        page = fetch_event_page_ext(token, report_id, data_type, fight, current_start, final_end, **kwargs)
        rows.extend(page.get("data") or [])
        next_page = page.get("nextPageTimestamp")
        if not next_page or next_page <= current_start:
            break
        current_start = next_page
    return rows


def dedupe_events(events):
    seen = set()
    rows = []
    for event in events:
        key = (
            event.get("timestamp"),
            event.get("type"),
            ability_id(event),
            event.get("sourceID"),
            event.get("targetID"),
            event.get("sourceInstance"),
            event.get("targetInstance"),
        )
        if key in seen:
            continue
        seen.add(key)
        rows.append(event)
    return rows


def energy_payload(event):
    if not event:
        return None
    payload = {}
    for key in ("resourceChange", "resourceChangeType", "resources", "sourceResources", "targetResources", "classResources"):
        if key in event:
            payload[key] = event.get(key)
    return payload or None


def phantom_segments(events):
    ticks = []
    for event in sorted(events, key=lambda item: item.get("timestamp", 0)):
        ts = event.get("timestamp", 0)
        if not ticks or ts - ticks[-1]["time"] > 550:
            ticks.append({"time": ts, "events": [event]})
        else:
            ticks[-1]["events"].append(event)
    segments = []
    for tick in ticks:
        if not segments or tick["time"] - segments[-1]["last"] > 3_500:
            segments.append({"first": tick["time"], "last": tick["time"], "ticks": [tick]})
        else:
            segments[-1]["last"] = tick["time"]
            segments[-1]["ticks"].append(tick)
    return segments


def summarize_void_repulsion(events, damage, positions, actor_map, actor_game_id, fight, start, end):
    removes = debuff_removes(events, SPELL["void_repulsion_mark"], start, end)
    rows = []
    for event in sorted(removes, key=lambda item: item.get("timestamp", 0)):
        target_id = event.get("targetID")
        exact = event_point(event, "target") or event_point(event)
        pos = {"x": exact[0], "y": exact[1], "source": "fade_event", "deltaMs": 0} if exact else replay_position(positions, target_id, event.get("timestamp", 0))
        impacts = [
            hit for hit in damage
            if ability_id(hit) == SPELL["void_repulsion_damage"]
            and hit.get("targetID") == target_id
            and abs(hit.get("timestamp", 0) - event.get("timestamp", 0)) <= 1000
        ]
        rows.append({
            "time": fmt(rel(fight, event.get("timestamp"))),
            "player": actor_name(actor_map, actor_game_id, target_id),
            "targetID": target_id,
            "position": point_payload(pos),
            "impactCountWithin1s": len(impacts),
        })
    return rows


def analyze_fight(token, report_id, fight, actor_map, actor_type, actor_game_id, phantom_actor_ids):
    print(f"analyzing fight={fight['id']} kill={fight.get('kill')} duration={fmt(fight['endTime'] - fight['startTime'])}")
    deaths = fetch_events_all(token, report_id, "Deaths", fight)
    casts = fetch_events_all(token, report_id, "Casts", fight)
    debuffs = []
    for spell_id in [
        SPELL["void_repulsion_mark"],
        SPELL["silver_arrow_mark"],
        SPELL["silver_havoc"],
        SPELL["star_scatter"],
        SPELL["ranger_mark"],
        SPELL["corruption"],
        SPELL["void_grasp"],
        1233470,
        1237844,
    ]:
        debuffs.extend(fetch_events_all(token, report_id, "Debuffs", fight, ability_id=spell_id))
    enemy_debuffs = []
    for spell_id in [SPELL["corruption"], 1233470, 1237844]:
        enemy_debuffs.extend(fetch_events_all(token, report_id, "Debuffs", fight, ability_id=spell_id, hostility_type="Enemies"))
    buffs = []
    for spell_id in [SPELL["silver_havoc"], SPELL["cosmic_barrier"], SPELL["cosmic_radiation"], 27680, 26662, 1239672]:
        buffs.extend(fetch_events_all(token, report_id, "Buffs", fight, ability_id=spell_id))
        buffs.extend(fetch_events_all(token, report_id, "Buffs", fight, ability_id=spell_id, hostility_type="Enemies"))
    buffs = dedupe_events(buffs)
    damage = []
    for spell_id in [SPELL["silver_arrow_damage"], SPELL["void_repulsion_damage"], SPELL["silver_ricochet"], SPELL["collapsing_void"]]:
        damage.extend(fetch_events_all(token, report_id, "DamageTaken", fight, ability_id=spell_id, include_resources=True))
    resources = fetch_events_all(token, report_id, "Resources", fight, include_resources=True)
    enemy_resources = fetch_events_all(token, report_id, "Resources", fight, hostility_type="Enemies", include_resources=True)
    positions = build_positions(resources)

    min_p15_start = fight["startTime"] + P1_MIN_TRANSITION_START_MS
    silver_havoc_events = [
        event for event in casts + debuffs + buffs
        if ability_id(event) == SPELL["silver_havoc"] and event.get("timestamp", 0) >= min_p15_start
    ]
    scatter_fades_all = debuff_removes(debuffs, SPELL["star_scatter"], min_p15_start, fight["endTime"])
    p2_start = max((event.get("timestamp", 0) for event in scatter_fades_all), default=None)
    p15_start_event = min(silver_havoc_events, key=lambda item: item.get("timestamp", 0), default=None)
    p15_start = p15_start_event.get("timestamp") if p15_start_event else (p2_start - P15_DURATION_MS if p2_start else None)
    if p15_start and not p2_start:
        p2_start = p15_start + P15_DURATION_MS

    barrier_apply = first_event(buffs, SPELL["cosmic_barrier"], "apply", p2_start, fight["endTime"])
    barrier_remove = first_event(buffs, SPELL["cosmic_barrier"], "remove", barrier_apply.get("timestamp") if barrier_apply else p2_start, fight["endTime"])
    radiation_apply = first_event(buffs, SPELL["cosmic_radiation"], "apply", p2_start, fight["endTime"])
    radiation_remove = first_event(buffs, SPELL["cosmic_radiation"], "remove", radiation_apply.get("timestamp") if radiation_apply else p2_start, fight["endTime"])
    p2_end = (barrier_apply or radiation_apply or {}).get("timestamp") or fight["endTime"]
    p3_start = (barrier_remove or radiation_remove or {}).get("timestamp")
    portal_casts = fetch_events_all(token, report_id, "Casts", fight, ability_id=SPELL["portal"], hostility_type="Enemies")
    portal_cast = first_event(portal_casts, SPELL["portal"], start=p3_start or p2_end, end=fight["endTime"])

    p1_void = summarize_void_repulsion(debuffs, damage, positions, actor_map, actor_game_id, fight, fight["startTime"], p15_start or fight["endTime"])
    p2_void = summarize_void_repulsion(debuffs, damage, positions, actor_map, actor_game_id, fight, p2_start or fight["startTime"], p2_end)

    shadow_removes = debuff_removes(enemy_debuffs, 1233470, fight["startTime"], p15_start or fight["endTime"])
    corruption_removes = debuff_removes(enemy_debuffs, SPELL["corruption"], fight["startTime"], p15_start or fight["endTime"])
    p1_arrow_rows = []
    for group in paired_marks(debuffs, SPELL["silver_arrow_mark"], fight["startTime"], p15_start or fight["endTime"], 2_000):
        expected_hit = group["start"] + 6_000
        enemy_hit = min(
            (
                event for event in shadow_removes
                if abs(event.get("timestamp", 0) - expected_hit) <= 2_500
            ),
            key=lambda item: abs(item.get("timestamp", 0) - expected_hit),
            default=None,
        )
        if not enemy_hit:
            enemy_hit = min(
                (
                    event for event in corruption_removes
                    if abs(event.get("timestamp", 0) - expected_hit) <= 2_500
                ),
                key=lambda item: abs(item.get("timestamp", 0) - expected_hit),
                default=None,
            )
        target_id = enemy_hit.get("targetID") if enemy_hit else None
        stack = corruption_before(enemy_debuffs, target_id, enemy_hit.get("timestamp", 0)) if enemy_hit and target_id else None
        player_hits = [
            event for event in damage
            if ability_id(event) == SPELL["silver_arrow_damage"]
            and abs(event.get("timestamp", 0) - expected_hit) <= 2_500
            and actor_type.get(event.get("targetID")) == "Player"
        ]
        p1_arrow_rows.append({
            "markTime": fmt(rel(fight, group["start"])),
            "expectedHitTime": fmt(rel(fight, expected_hit)),
            "markedPlayers": [actor_name(actor_map, actor_game_id, event.get("targetID")) for event in group["events"]],
            "bossHitTime": fmt(rel(fight, enemy_hit.get("timestamp"))) if enemy_hit else None,
            "bossHitTarget": actor_name(actor_map, actor_game_id, target_id) if target_id else None,
            "corruptionBeforeHit": stack,
            "playerDamageTargets": [actor_name(actor_map, actor_game_id, event.get("targetID")) for event in player_hits],
        })

    p15_deaths = [
        {
            "time": fmt(rel(fight, event.get("timestamp"))),
            "player": actor_name(actor_map, actor_game_id, event.get("targetID")),
            "abilityID": event.get("killingAbilityGameID"),
        }
        for event in deaths
        if p15_start and p2_start and p15_start <= event.get("timestamp", 0) <= p2_start
    ]

    ranger_rows = []
    ranger_groups = paired_marks(debuffs, SPELL["ranger_mark"], p2_start or fight["startTime"], p2_end, 3_000)
    for index, group in enumerate(ranger_groups, start=1):
        window_end = group["end"] + 8_000
        fades = [
            event for event in debuffs
            if ability_id(event) == SPELL["ranger_mark"]
            and "remove" in event_type(event)
            and group["start"] <= event.get("timestamp", 0) <= window_end
        ]
        hits = [
            event for event in damage
            if ability_id(event) == SPELL["silver_ricochet"]
            and group["start"] <= event.get("timestamp", 0) <= window_end
        ]
        boss_drains = [
            event for event in enemy_resources
            if ability_id(event) == SPELL["silver_ricochet_energy_drain"]
            and group["start"] <= event.get("timestamp", 0) <= window_end
            and actor_game_id.get(event.get("targetID")) == 240430
        ]
        ranger_rows.append({
            "index": index,
            "markStart": fmt(rel(fight, group["start"])),
            "markedPlayers": [actor_name(actor_map, actor_game_id, event.get("targetID")) for event in group["events"]],
            "fadeTimes": sorted({fmt(rel(fight, event.get("timestamp"))) for event in fades}),
            "ricochetHits": len(hits),
            "bossEnergyDrainCount": len(boss_drains),
            "bossEnergyDrains": [
                {
                    "time": fmt(rel(fight, event.get("timestamp"))),
                    "resourceChange": event.get("resourceChange"),
                    "resourceAfter": (event.get("classResources") or [{}])[0].get("amount"),
                }
                for event in boss_drains
            ],
            "success": len(boss_drains) > 0,
        })

    phantom_damage = []
    for phantom_id in phantom_actor_ids:
        try:
            phantom_damage.extend(fetch_events_all_ext(token, report_id, "DamageDone", fight, start_time=p2_start, end_time=p2_end, source_id=phantom_id, hostility_type="Enemies"))
        except RuntimeError as error:
            phantom_damage.append({"error": str(error), "sourceID": phantom_id})
    segments = phantom_segments([event for event in phantom_damage if "error" not in event])
    grasp_removes = [
        event for event in debuffs
        if ability_id(event) == SPELL["void_grasp"]
        and "remove" in event_type(event)
        and (p2_start or fight["startTime"]) <= event.get("timestamp", 0) <= p2_end
    ]
    phantom_rows = []
    for segment in segments:
        releaser = min(
            (
                event for event in grasp_removes
                if -1_000 <= segment["last"] - event.get("timestamp", 0) <= 3_500
            ),
            key=lambda item: abs(segment["last"] - item.get("timestamp", 0)),
            default=None,
        )
        phantom_rows.append({
            "firstDamage": fmt(rel(fight, segment["first"])),
            "lastDamage": fmt(rel(fight, segment["last"])),
            "tickCount": len(segment["ticks"]),
            "possibleEliminator": actor_name(actor_map, actor_game_id, releaser.get("targetID")) if releaser else None,
            "voidGraspFadeTime": fmt(rel(fight, releaser.get("timestamp"))) if releaser else None,
        })

    portal_positions = []
    if portal_cast:
        ts = portal_cast.get("timestamp", 0)
        player_ids = sorted(actor_id for actor_id, atype in actor_type.items() if atype == "Player")
        for actor_id in player_ids:
            pos = replay_position(positions, actor_id, ts)
            if pos:
                portal_positions.append({
                    "player": actor_name(actor_map, actor_game_id, actor_id),
                    "targetID": actor_id,
                    "position": point_payload(pos),
                })

    return {
        "fightID": fight["id"],
        "kill": fight.get("kill"),
        "duration": fmt(fight["endTime"] - fight["startTime"]),
        "counts": {
            "deaths": len(deaths),
            "casts": len(casts),
            "debuffs": len(debuffs),
            "enemyDebuffs": len(enemy_debuffs),
            "buffs": len(buffs),
            "damage": len(damage),
            "resources": len(resources),
            "enemyResources": len(enemy_resources),
            "phantomDamage": len([event for event in phantom_damage if "error" not in event]),
        },
        "phase": {
            "p15Start": fmt(rel(fight, p15_start)) if p15_start else None,
            "silverHavocEventTime": fmt(rel(fight, p15_start_event.get("timestamp"))) if p15_start_event else None,
            "p2Start": fmt(rel(fight, p2_start)) if p2_start else None,
            "scatterFadeFirst": fmt(rel(fight, min((event.get("timestamp", 0) for event in scatter_fades_all), default=0))) if scatter_fades_all else None,
            "scatterFadeLast": fmt(rel(fight, p2_start)) if p2_start else None,
            "barrierApply": fmt(rel(fight, barrier_apply.get("timestamp"))) if barrier_apply else None,
            "barrierRemove": fmt(rel(fight, barrier_remove.get("timestamp"))) if barrier_remove else None,
            "radiationApply": fmt(rel(fight, radiation_apply.get("timestamp"))) if radiation_apply else None,
            "radiationRemove": fmt(rel(fight, radiation_remove.get("timestamp"))) if radiation_remove else None,
            "p2DurationUntilBarrier": fmt((p2_end - p2_start) if p2_start and p2_end else None),
            "p2LastedFull140s": bool(p2_start and p2_end and p2_end - p2_start >= 140_000),
        },
        "p1": {
            "voidRepulsion": p1_void,
            "silverArrows": p1_arrow_rows,
        },
        "p15": {
            "deaths": p15_deaths,
        },
        "p2": {
            "rangerMarks": ranger_rows,
            "voidRepulsion": p2_void,
            "phantomActorIDs": phantom_actor_ids,
            "phantomSegments": phantom_rows,
        },
        "p3": {
            "portalCastTime": fmt(rel(fight, portal_cast.get("timestamp"))) if portal_cast else None,
            "portalCastTimes": [fmt(rel(fight, event.get("timestamp"))) for event in portal_casts],
            "portalPlayerPositions": portal_positions,
        },
    }


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    token = get_token()
    fights = fetch_report_fights(token, REPORT_ID)
    actor_map, actor_type, actor_game_id = fetch_actor_maps(token, REPORT_ID)
    phantom_actor_ids = sorted(actor_id for actor_id, game_id in actor_game_id.items() if game_id == PHANTOM_GAME_ID)
    source_checks = []
    for check in SOURCE_CHECKS:
        check_fights = fetch_report_fights(token, check["reportID"])
        check_fight = next((item for item in check_fights if item["id"] == check["fightID"]), None)
        check_actor_map, check_actor_type, check_actor_game_id = fetch_actor_maps(token, check["reportID"])
        check_phantoms = sorted(actor_id for actor_id, game_id in check_actor_game_id.items() if game_id == PHANTOM_GAME_ID)
        row = {
            "reportID": check["reportID"],
            "fightID": check["fightID"],
            "phantomActorIDs": check_phantoms,
            "phantomActorNames": {str(actor_id): check_actor_map.get(actor_id) for actor_id in check_phantoms},
        }
        if check_fight:
            row["damageDoneCountsBySource"] = {}
            for actor_id in check_phantoms:
                events = fetch_events_all_ext(token, check["reportID"], "DamageDone", check_fight, source_id=actor_id, hostility_type="Enemies")
                if events:
                    row["damageDoneCountsBySource"][str(actor_id)] = len(events)
            row["phaseSpellProbe"] = {}
            for data_type in ["Buffs", "Debuffs", "Casts", "DamageDone", "DamageTaken"]:
                row["phaseSpellProbe"][data_type] = {}
                for spell_id in [SPELL["cosmic_barrier"], SPELL["cosmic_radiation"]]:
                    events = fetch_events_all(token, check["reportID"], data_type, check_fight, ability_id=spell_id, hostility_type="Enemies")
                    row["phaseSpellProbe"][data_type][str(spell_id)] = len(events)
        source_checks.append(row)
    result = {
        "reportID": REPORT_ID,
        "fightIDs": [fight["id"] for fight in fights],
        "phantomActorIDsInReport": phantom_actor_ids,
        "sourceChecks": source_checks,
        "fights": [analyze_fight(token, REPORT_ID, fight, actor_map, actor_type, actor_game_id, phantom_actor_ids) for fight in fights],
    }
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT_PATH}")
    print(json.dumps(result, ensure_ascii=False, indent=2)[:8000])


if __name__ == "__main__":
    main()
