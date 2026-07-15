import json
import os
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import requests
import urllib3

from analyzer_core.concurrency import MAX_REQUEST_THREADS, request_post, run_parallel_indexed

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def load_env_file():
    search_dirs = [Path.cwd(), Path(__file__).resolve().parent]
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

# ================= 1. 全局配置 =================
CLIENT_ID = os.getenv("WCL_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("WCL_CLIENT_SECRET", "")

REPORT_IDS_INPUT = os.getenv("WCL_REPORT_IDS", "")
TARGET_BOSS_KEYWORDS = ["midnight falls", "l'ura", "至暗之夜降临", "鲁拉"]
PROXY_URL = os.getenv("WCL_PROXY", "http://127.0.0.1:7890").strip()
PROXIES = {"http": PROXY_URL, "https": PROXY_URL} if PROXY_URL else None
WCL_BASE_URL = os.getenv("WCL_BASE_URL", "https://www.warcraftlogs.com").rstrip("/")

TERMINAL_MATRIX_ID = 1286276
SKY_GLAIVE_ID = 1254076
HOLY_END_ID = 1284699
DISSONANCE_ID = 1249585
DARK_WELL_ID = 1282028
TIDAL_TERROR_ID = 1282017
STELLAR_SHARD_IDS = {1279581, 1281473}
STELLAR_SHARD_DEBUFF_IDS = {1285510, 1279512}
HEAVEN_AND_HELL_ID = 1276526
P4_UNIQUE_DEATH_IDS = STELLAR_SHARD_IDS | {HEAVEN_AND_HELL_ID}

SPELLS = {
    1254076: "天穹战刃", 1253873: "近战（鲁拉）", 1253878: "天穹之枪（坦克尖刺）",
    1286276: "终结矩阵/终结棱柱", 1284699: "圣光终末（水晶爆炸）", 1249585: "不谐",
    1249582: "共振", 1282458: "光辉", 1249797: "破碎天空",
    1279581: "星辰裂片", 1281473: "星辰裂片", 1285510: "星辰裂片（debuff）", 1279512: "星辰裂片（debuff）", 1254398: "闪烁（水晶组dot）",
    1282028: "黑暗之井", 1282017: "黑暗熔毁", 1252974: "渐黯（黄昏水晶未奶满）",
    1251789: "宇宙裂隙（没转掉）", 1282469: "黑暗类星体", 1282470: "黑暗类星体",
    1266388: "黑暗星座", 1266584: "黑暗星座", 1266586: "黑暗星座",
    1263255: "黑色浪潮", 1281184: "临界状态", 1281178: "临界状态",
    1254262: "鲁拉之泪", 1254256: "纳鲁的挽歌（漏圈）", 1287702: "割裂激涌（对场死完）",
    1266810: "圣光虹吸", 1263514: "至暗之夜", 1253879: "被刺穿（dot）", 1276526: "天堂与地狱",
    1254257: "鲁拉之泪", 1251080: "黑暗天使长", 1285719: "黑色浪潮（p4）", 1273033: "虚空蜂拥", 1276529: "次元突破（对撞）"
}

AVOIDABLE_SPELLS = {
    "skyGlaive": {"label": "天穹战刃", "ids": {SKY_GLAIVE_ID}, "keywords": ["天穹战刃", "sky glaive"]},
    "darkQuasar": {"label": "黑暗类星体", "ids": {1282469}, "keywords": ["黑暗类星体", "dark quasar"]},
    "darkConstellation": {"label": "黑暗星座", "ids": {1266584, 1266586},
                          "keywords": ["黑暗星座", "dark constellation"]},
}

INTERRUPT_GROUPS = [
    ["染小九", "Breezeluck", "摆烂威"],
    ["Oogi", "Superhunter", "飞天小喷菇"],
    ["岩深丶启动", "叮咚好烦", "三坑不二"],
    ["爱音", "polonaise", "茶喵不吃糖"],
]

PLAYER_ALIASES = {
    "染小九": {"染小九"}, "Breezeluck": {"Breezeluck"}, "摆烂威": {"摆烂威"},
    "Oogi": {"Oogi"}, "Superhunter": {"Superhunter"}, "飞天小喷菇": {"飞天小喷菇"},
    "岩深丶启动": {"岩深丶启动"}, "叮咚好烦": {"叮咚好烦", "Loveating", "利文泽拉"},
    "三坑不二": {"三坑不二"}, "不可以蛇蛇": {"不可以蛇蛇"},
    "polonaise": {"polonaise", "Polonaise"}, "茶喵不吃糖": {"茶喵不吃糖", "阿莱西-加斯"},
}

P1_END_MS = 231_000
P2_END_MS = 330_000
P2_TO_P3_END_MS = 342_000
P2_TO_P3_SPREAD_REPLAY_MS = 330_000
P3_FALLBACK_START_MS = 360_000
P4_SIGNAL_AFTER_MS = 330_000
P4_NO_DEATH_MS = 510_000
MATRIX_ACCIDENT_WINDOW_MS = 25_000
CN_TZ = timezone(timedelta(hours=8))


def progress(message, indent=0):
    prefix = "  " * indent
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {prefix}{message}", flush=True)


def progress_bar(current, total, width=18):
    if total <= 0:
        return "[" + "-" * width + "]"
    filled = int(width * current / total)
    return "[" + "#" * filled + "-" * (width - filled) + f"] {current}/{total}"


# ================= 2. WCL API =================
def get_token():
    if not CLIENT_ID or not CLIENT_SECRET:
        raise RuntimeError("请先在项目 .env 或系统环境变量中设置 WCL_CLIENT_ID 和 WCL_CLIENT_SECRET。")
    url = f"{WCL_BASE_URL}/oauth/token"
    res = request_post(url, data={"grant_type": "client_credentials"}, auth=(CLIENT_ID, CLIENT_SECRET),
                        proxies=PROXIES, verify=False, timeout=30)
    if res.status_code == 401:
        raise RuntimeError(
            f"WCL 鉴权失败：当前 WCL_CLIENT_ID / WCL_CLIENT_SECRET 无效，或不是 {WCL_BASE_URL} 对应的客户端凭据。"
            "注意 WCL_CLIENT_ID 需要填写 API Clients 页面里的 Client ID，不是 WCL 用户名或主页名。"
        )
    res.raise_for_status()
    return res.json()["access_token"]


def graphql(token, query, variables):
    url = f"{WCL_BASE_URL}/api/v2/client"
    headers = {"Authorization": f"Bearer {token}"}
    res = request_post(url, json={"query": query, "variables": variables}, headers=headers, proxies=PROXIES,
                        verify=False, timeout=90)
    res.raise_for_status()
    payload = res.json()
    if payload.get("errors"): raise RuntimeError(json.dumps(payload["errors"], ensure_ascii=False))
    return payload["data"]["reportData"]["report"]


def fetch_report_fights(token, report_id):
    query = """
    query($code: String!) {
      reportData {
        report(code: $code) {
          startTime
          fights { id name startTime endTime kill }
        }
      }
    }
    """
    report = graphql(token, query, {"code": report_id})
    report_start_ms = report["startTime"]
    valid = []
    for fight in report["fights"]:
        name = (fight.get("name") or "").lower()
        duration = fight["endTime"] - fight["startTime"]
        if duration < 20_000:  # 过滤20秒内起手秒团的 Trash
            continue
        if any(keyword in name for keyword in TARGET_BOSS_KEYWORDS):
            fight["reportStartTime"] = report_start_ms
            valid.append(fight)
    return valid


def fetch_master_actor_map(token, report_id):
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

    id_to_name = {}
    pet_to_owner = {}

    # 构建基础映射和宠物血统
    for actor in actors:
        id_to_name[actor["id"]] = actor["name"]
        if actor.get("petOwner"):
            pet_to_owner[actor["id"]] = actor["petOwner"]

    actor_map = {}
    for actor in actors:
        if actor["id"] in pet_to_owner:
            owner_id = pet_to_owner[actor["id"]]
            # 如果是宠物，直接将其名字映射为主人的名字
            actor_map[actor["id"]] = id_to_name.get(owner_id, actor["name"])
        else:
            actor_map[actor["id"]] = actor["name"]

    return actor_map


def fetch_event_page(token, report_id, data_type, fight, start_time=None, end_time=None, ability_id=None):
    ability_arg = f", $abilityID: Float" if ability_id is not None else ""
    ability_filter = ", abilityID: $abilityID" if ability_id is not None else ""
    query = f"""
    query($code: String!, $dataType: EventDataType!, $startTime: Float!, $endTime: Float!, $fightIDs: [Int]{ability_arg}) {{
      reportData {{ report(code: $code) {{ events(dataType: $dataType, startTime: $startTime, endTime: $endTime, fightIDs: $fightIDs, limit: 10000{ability_filter}) {{ data nextPageTimestamp }} }} }}
    }}
    """
    report_vars = {
        "code": report_id, "dataType": data_type,
        "startTime": float(start_time if start_time is not None else fight["startTime"]),
        "endTime": float(end_time if end_time is not None else fight["endTime"]),
        "fightIDs": [fight["id"]],
    }
    if ability_id is not None: report_vars["abilityID"] = float(ability_id)
    return graphql(token, query, report_vars)["events"]


def fetch_events(token, report_id, data_type, fight, start_time=None, end_time=None, ability_id=None):
    page = fetch_event_page(token, report_id, data_type, fight, start_time, end_time, ability_id)
    return page.get("data") or []


def fetch_avoidable_damage(token, report_id, fight, emit_progress=None):
    rows, seen = [], set()
    ability_jobs = []
    for config in AVOIDABLE_SPELLS.values():
        if emit_progress:
            emit_progress(f"读取可躲避伤害：{config['label']}")
        ability_jobs.extend(sorted(config["ids"]))

    def fetch_one(index_and_ability):
        index, aid = index_and_ability
        return index, fetch_events(token, report_id, "DamageTaken", fight, ability_id=aid)

    for _, events in run_parallel_indexed(
        list(enumerate(ability_jobs, start=1)),
        fetch_one,
        max_workers=MAX_REQUEST_THREADS,
    ):
        for event in events:
            key = (event.get("timestamp"), event.get("sourceID"), event.get("targetID"), event.get("abilityGameID"),
                   event.get("amount"))
            if key not in seen:
                seen.add(key)
                rows.append(event)
    return rows


def fetch_fight_data(token, report_id, fight, actor_map, emit_progress=None):
    if emit_progress:
        emit_progress("读取死亡事件")
    deaths = fetch_events(token, report_id, "Deaths", fight)
    death_ids = {event.get("killingAbilityGameID") for event in deaths}
    interrupts, naruu_tear_damage, p4_stellar_debuffs = [], [], []
    if emit_progress:
        emit_progress(f"死亡事件：{len(deaths)} 条")

    if TERMINAL_MATRIX_ID in death_ids:
        if emit_progress:
            emit_progress("检测到终结矩阵死亡，读取打断记录")
        interrupts = fetch_events(token, report_id, "Interrupts", fight)
        if emit_progress:
            emit_progress(f"打断记录：{len(interrupts)} 条")

    for death in deaths:
        if death.get("killingAbilityGameID") == 1254256:
            event_time = death.get("timestamp", fight["startTime"])
            if emit_progress:
                emit_progress(f"读取纳鲁的挽歌前后鲁拉之泪窗口：{format_time(event_time - fight['startTime'])}")
            naruu_tear_damage.extend(
                fetch_events(token, report_id, "DamageTaken", fight, start_time=event_time - 20_000,
                             end_time=event_time + 2_000, ability_id=1254262))

    wipe_elapsed_ms = fight["endTime"] - fight["startTime"]
    if find_p4_signal_death(deaths, fight) or (not deaths and wipe_elapsed_ms > P4_NO_DEATH_MS):
        if emit_progress:
            emit_progress("判定存在 P4 信号，读取星辰裂片 debuff faded")
        def fetch_one_debuff(index_and_ability):
            index, ability = index_and_ability
            return index, fetch_events(
                token, report_id, "Debuffs", fight,
                start_time=fight["startTime"] + P4_SIGNAL_AFTER_MS,
                end_time=fight["endTime"], ability_id=ability)

        for _, events in run_parallel_indexed(
            list(enumerate(sorted(STELLAR_SHARD_DEBUFF_IDS), start=1)),
            fetch_one_debuff,
            max_workers=MAX_REQUEST_THREADS,
        ):
            p4_stellar_debuffs.extend(events)
        if emit_progress:
            emit_progress(f"P4 星辰裂片 debuff：{len(p4_stellar_debuffs)} 条")

    avoidable_damage = fetch_avoidable_damage(token, report_id, fight, emit_progress=emit_progress)
    if emit_progress:
        emit_progress(f"可躲避伤害合计：{len(avoidable_damage)} 条")

    return {
        "actorMap": actor_map,
        "deaths": deaths,
        "interrupts": interrupts,
        "naruuTearDamage": naruu_tear_damage,
        "p4StellarDebuffs": p4_stellar_debuffs,
        "avoidableDamage": avoidable_damage,
    }


# ================= 3. 工具函数与核心算法 =================
def ability_id(e): return e.get("abilityGameID") or e.get("killingAbilityGameID") or e.get("extraAbilityGameID")


def ability_name(e): aid = ability_id(e); return e.get("abilityName") or e.get("name") or SPELLS.get(aid,
                                                                                                     str(aid or "未知"))


def event_amount(e): return int(e.get("amount") or 0) + int(e.get("absorbed") or 0)


def actor(actor_map, actor_id): return actor_map.get(actor_id, f"未知({actor_id})")


def fight_elapsed(e, fight): return int(e.get("timestamp", 0) - fight["startTime"])


def format_time(ms): return str(timedelta(seconds=max(0, int(ms)) // 1000))[2:7]


def deep_link(r_id, f_id, v_type, ev_time, pb=15_000,
              pa=2_000): return f"{WCL_BASE_URL}/reports/{r_id}#fight={f_id}&type={v_type}&start={ev_time - pb}&end={ev_time + pa}"


def replay_link(r_id, f_id, position_ms):
    return f"{WCL_BASE_URL}/reports/{r_id}?fight={f_id}&view=replay&position={max(0, int(position_ms))}"


def base_phase_from_elapsed_ms(ms):
    if ms < P1_END_MS: return "P1"
    if ms < P2_END_MS: return "P2"
    if ms <= P2_TO_P3_END_MS: return "P2转P3"
    return "P3"


def find_p4_signal_death(deaths, fight):
    return next((e for e in deaths if e.get("killingAbilityGameID") in P4_UNIQUE_DEATH_IDS
                 and fight_elapsed(e, fight) > P4_SIGNAL_AFTER_MS), None)


def infer_wipe_phase(wipe_elapsed_ms, deaths, fight):
    if find_p4_signal_death(deaths, fight):
        return "P4"
    if not deaths and wipe_elapsed_ms > P4_NO_DEATH_MS:
        return "P4"
    return base_phase_from_elapsed_ms(wipe_elapsed_ms)


def is_avoidable(e, config): return ability_id(e) in config["ids"] or any(
    k.lower() in ability_name(e).lower() for k in config["keywords"])


def get_local_datetime(absolute_ms):
    return datetime.fromtimestamp(absolute_ms / 1000.0, CN_TZ)


def raid_night_date_str(local_dt):
    from analyzer_core.wcl_paths import to_raid_night_date
    return to_raid_night_date(local_dt).isoformat()


def canonical_player_name(name):
    normalized = (name or "").lower()
    for canonical, aliases in PLAYER_ALIASES.items():
        if normalized in {alias.lower() for alias in aliases}: return canonical
    return name


def analyze_terminal_matrix(wipe_time, interrupts, actor_map, fight_start):
    """
    终极重构版：抛弃基于时间的聚类防抖，直接基于矩阵组的出场顺序进行顺位检查！
    """
    accident_start = wipe_time - MATRIX_ACCIDENT_WINDOW_MS
    accident_end = wipe_time + 2_000

    # 圈出所有在事故窗口内的有效打断记录 (宠物已经映射为主人名字)
    window_rows = [row for row in interrupts if accident_start <= row.get("timestamp", 0) <= accident_end]

    actual_canon = set()
    window_interrupts = []

    for row in sorted(window_rows, key=lambda item: item.get("timestamp", 0)):
        raw_name = actor(actor_map, row.get("sourceID"))
        canon = canonical_player_name(raw_name)
        actual_canon.add(canon)

        window_interrupts.append({
            "time": format_time(row.get("timestamp", 0) - fight_start),
            "offsetMs": row.get("timestamp", 0) - wipe_time,
            "absoluteTime": row.get("timestamp"),
            "player": canonical_player_name(raw_name) or raw_name,
            "rawPlayer": raw_name,
            "ability": ability_name(row),
        })

    # 核心审判逻辑：严格按组别顺位检查。第一组没漏才看第二组。哪组没齐就判哪组。
    failed_group_idx = None
    failed_missing = []

    for idx, group in enumerate(INTERRUPT_GROUPS):
        missing = [n for n in group if canonical_player_name(n) not in actual_canon]
        if missing:
            failed_group_idx = idx
            failed_missing = missing
            break  # 抓到第一顺位的战犯组，立刻退出循环

    if failed_group_idx is not None:
        expected_group = INTERRUPT_GROUPS[failed_group_idx]
        investigation = f"第 {failed_group_idx + 1} 组漏断。分配组: {', '.join(expected_group)}。漏断：【{'、'.join(failed_missing)}】。"
    else:
        investigation = "事故窗口内 4 组名单内成员均已施放打断，可能目标分配重叠或打错！"

    return {
        "investigation": investigation,
        "windowInterrupts": window_interrupts
    }


def is_debuff_fade(event):
    event_type = (event.get("type") or "").lower()
    return "remove" in event_type or "fade" in event_type


def nearest_stellar_fade(event_time, debuff_fades):
    candidates = [row for row in debuff_fades if 0 <= event_time - row.get("timestamp", 0) <= 1_500]
    if not candidates:
        candidates = [row for row in debuff_fades if abs(event_time - row.get("timestamp", 0)) <= 500]
    return min(candidates, key=lambda row: abs(event_time - row.get("timestamp", 0))) if candidates else None


def analyze_p4_stellar_shards(debuff_events, deaths, actor_map, fight_start):
    p4_start = fight_start + P4_SIGNAL_AFTER_MS
    rows, seen = [], set()
    debuff_fades = sorted(
        [event for event in debuff_events
         if event.get("timestamp", 0) > p4_start
         and ability_id(event) in STELLAR_SHARD_DEBUFF_IDS
         and is_debuff_fade(event)],
        key=lambda item: item.get("timestamp", 0)
    )
    shard_deaths = sorted(
        [death for death in deaths
         if death.get("timestamp", 0) > p4_start
         and death.get("killingAbilityGameID") in STELLAR_SHARD_IDS],
        key=lambda item: item.get("timestamp", 0)
    )

    for death in shard_deaths:
        fade = nearest_stellar_fade(death.get("timestamp", 0), debuff_fades)
        shard_player = actor(actor_map, fade.get("targetID")) if fade else actor(actor_map, death.get("sourceID"))
        target = actor(actor_map, death.get("targetID"))
        key = (death.get("timestamp"), shard_player, target)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "time": format_time(death.get("timestamp", 0) - fight_start),
            "source": shard_player,
            "target": target,
            "ability": ability_name(death),
            "amount": 0,
            "isDeath": True,
            "debuffTime": format_time(fade.get("timestamp", 0) - fight_start) if fade else "",
            "summary": f"{target} 死于 {shard_player} 的星辰裂片",
        })
    return rows


# ================= 4. 单场分析 =================
def analyze_fight(report_id, fight, raw, global_avoidable):
    actor_map = raw["actorMap"]
    deaths = sorted(raw["deaths"], key=lambda item: item.get("timestamp", 0))
    avoidable_damage = raw["avoidableDamage"]
    interrupts = sorted(raw["interrupts"], key=lambda item: item.get("timestamp", 0))
    p4_stellar_debuffs = raw.get("p4StellarDebuffs", [])

    # 开打时钟用真实本地时间；开荒日（date）按 01:00 前归属前一天。
    absolute_ms = fight["reportStartTime"] + fight["startTime"]
    local_start = get_local_datetime(absolute_ms)
    date_str = raid_night_date_str(local_start)
    start_clock = local_start.strftime("%H:%M")
    start_datetime = local_start.strftime("%Y-%m-%d %H:%M")

    local_avoidable = {key: {} for key in AVOIDABLE_SPELLS}
    for event in avoidable_damage:
        for board in (local_avoidable, global_avoidable):
            target = actor(actor_map, event.get("targetID"))
            for key, config in AVOIDABLE_SPELLS.items():
                if is_avoidable(event, config):
                    row = board[key].setdefault(target, {"name": target, "spellKey": key, "spellName": config["label"],
                                                         "totalDamage": 0, "hitCount": 0, "deathCount": 0})
                    row["totalDamage"] += event_amount(event)
                    row["hitCount"] += 1

    for death in deaths:
        death_id = death.get("killingAbilityGameID")
        target = actor(actor_map, death.get("targetID"))
        for key, config in AVOIDABLE_SPELLS.items():
            if death_id in config["ids"] or any(
                    k.lower() in SPELLS.get(death_id, "").lower() for k in config["keywords"]):
                for board in (local_avoidable, global_avoidable):
                    board[key].setdefault(target, {"name": target, "spellKey": key, "spellName": config["label"],
                                                   "totalDamage": 0, "hitCount": 0, "deathCount": 0})["deathCount"] += 1

    first_mechanic_death = next((e for e in deaths if
                                 e.get("killingAbilityGameID") in {TERMINAL_MATRIX_ID, 1254256, 1251789, 1252974,
                                                                   HOLY_END_ID, DISSONANCE_ID}), None)
    p4_signal_death = find_p4_signal_death(deaths, fight)
    wipe_elapsed_ms = fight["endTime"] - fight["startTime"]
    wipe_phase = infer_wipe_phase(wipe_elapsed_ms, deaths, fight)
    actual_phase = wipe_phase
    is_kill = bool(fight.get("kill"))
    if is_kill:
        wipe_phase = "已击杀"
    first_mechanic_id = first_mechanic_death.get("killingAbilityGameID") if first_mechanic_death else None
    wipe_reason, investigation, wcl_link = "大面积 AoE 减员崩盘", "", ""
    p4_stellar_shards = analyze_p4_stellar_shards(
        p4_stellar_debuffs, deaths, actor_map, fight["startTime"]
    ) if actual_phase == "P4" else []

    if is_kill:
        wipe_reason = "已击杀"
        investigation = f"Boss 已击杀，本场不归类为灭团。战斗结束于 {format_time(wipe_elapsed_ms)}，下方保留本场死亡记录供复盘。"
        wcl_link = replay_link(report_id, fight["id"], max(0, wipe_elapsed_ms - 3_000))
    elif p4_signal_death:
        signal_time = fight_elapsed(p4_signal_death, fight)
        wipe_reason = "P4阶段减员"
        investigation = f"P4阶段发生减员，已定位到首次 P4 独有死亡前 3 秒回放。死亡发生在本场 {format_time(signal_time)}。"
        wcl_link = replay_link(report_id, fight["id"], signal_time - 3_000)
    elif first_mechanic_id == TERMINAL_MATRIX_ID:
        matrix = analyze_terminal_matrix(first_mechanic_death["timestamp"], interrupts, actor_map, fight["startTime"])
        wipe_reason, investigation = "终结矩阵漏断", matrix["investigation"]
        wcl_link = deep_link(report_id, fight["id"], "interrupts", first_mechanic_death["timestamp"],
                             MATRIX_ACCIDENT_WINDOW_MS, 2_000)
    elif first_mechanic_id == 1254256:
        wipe_reason, investigation = "纳鲁的挽歌（漏接鲁拉之泪）", "触发前后请通过链接检查人员分散位置。"
        wcl_link = replay_link(report_id, fight["id"], P2_TO_P3_SPREAD_REPLAY_MS)
    elif first_mechanic_id == 1251789:
        wipe_reason, investigation = "宇宙裂隙（没转掉）", "午夜水晶读条未被及时处理，优先复盘转火和目标分配。"
        wcl_link = deep_link(report_id, fight["id"], "damage-done", first_mechanic_death["timestamp"])
    elif first_mechanic_id == 1252974:
        wipe_reason, investigation = "渐黯（黄昏水晶未奶满）", "黄昏水晶未成功转化为黎明水晶，优先复盘治疗分配。"
        wcl_link = deep_link(report_id, fight["id"], "healing", first_mechanic_death["timestamp"])
    elif first_mechanic_id == HOLY_END_ID:
        wipe_reason, investigation = "圣光终末（地上黎明水晶碎裂）", "地上水晶吃到宇宙伤害后碎裂；重点检查临界状态、星辰裂片、类星体前后的水晶放置。"
        wcl_link = deep_link(report_id, fight["id"], "damage-taken", first_mechanic_death["timestamp"])
    elif first_mechanic_id == DISSONANCE_ID:
        phase = "P1 不谐" if fight_elapsed(first_mechanic_death, fight) < P1_END_MS else "P3 点名碰牌不谐"
        wipe_reason, investigation = f"不谐（{phase}）", f"死亡发生在本场 {format_time(fight_elapsed(first_mechanic_death, fight))}，判定为{phase}。"

    if not is_kill and wipe_phase == "P4" and not p4_signal_death:
        wipe_reason = "P4阶段减员" if deaths else "P4阶段记录"
        investigation = "P4阶段发生减员。请结合死亡时间线查看具体死亡原因。" if deaths else "战斗超过 8:30 且无死亡记录，判定进入 P4。"
        wcl_link = replay_link(report_id, fight["id"], P4_NO_DEATH_MS - 3_000)

    timeline = [
        {"time": format_time(fight_elapsed(e, fight)), "absoluteTime": e.get("timestamp"),
         "player": actor(actor_map, e.get("targetID")),
         "abilityID": e.get("killingAbilityGameID"),
         "ability": SPELLS.get(e.get("killingAbilityGameID"), str(e.get("killingAbilityGameID")))}
        for e in deaths if e.get("killingAbilityGameID") not in [DARK_WELL_ID, TIDAL_TERROR_ID]
    ]

    return {
        "reportID": report_id, "fightID": fight["id"], "date": date_str,
        "fightName": fight.get("name"), "fightStart": fight["startTime"], "fightEnd": fight["endTime"],
        "startClock": start_clock, "startDateTime": start_datetime,
        "duration": format_time(fight["endTime"] - fight["startTime"]),
        "fightStatus": "kill" if is_kill else "wipe", "isKill": is_kill, "kill": is_kill,
        "fightPhase": actual_phase, "wipePhase": wipe_phase, "wipeElapsedMs": wipe_elapsed_ms,
        "wipeReason": wipe_reason, "investigation": investigation, "wclDeepLink": wcl_link,
        "deathTimeline": timeline,
        "p4StellarShardHits": p4_stellar_shards,
        "matrixWindowInterrupts": matrix["windowInterrupts"] if "matrix" in locals() else [],
        "avoidableSummary": {key: sorted(rows.values(), key=lambda item: item["totalDamage"], reverse=True) for
                             key, rows in local_avoidable.items()},
    }


def merge_avoidable_summary(global_avoidable, summary):
    for key, rows in summary.items():
        bucket = global_avoidable.setdefault(key, {})
        for row in rows:
            target = row["name"]
            merged = bucket.setdefault(
                target,
                {
                    "name": target,
                    "spellKey": row.get("spellKey", key),
                    "spellName": row.get("spellName", ""),
                    "totalDamage": 0,
                    "hitCount": 0,
                    "deathCount": 0,
                },
            )
            merged["totalDamage"] += row.get("totalDamage", 0)
            merged["hitCount"] += row.get("hitCount", 0)
            merged["deathCount"] += row.get("deathCount", 0)


# ================= 5. 聚合输出 =================
def build_aggregated_json():
    progress("启动鲁拉开荒复盘分析")
    progress("连接 WCL，获取访问令牌", 1)
    token = get_token()
    report_ids = [rid.strip() for rid in REPORT_IDS_INPUT.replace(" ", "").split(",") if rid.strip()]
    if not report_ids:
        raise RuntimeError("请通过 WCL_REPORT_IDS 环境变量或插件入口传入至少一个 WCL 日志 ID。")
    progress(f"准备分析 {len(report_ids)} 份日志：{', '.join(report_ids)}", 1)
    global_avoidable = {key: {} for key in AVOIDABLE_SPELLS}

    final_output = {
        "code": 200,
        "meta": {"analyzedReports": report_ids, "mechanicVersion": "lura-2026-06-16",
                 "version": "12.0",
                 "raidKey": "void_spire_dream_rift_queldanas",
                 "raidName": "虚影尖塔 / 梦境裂隙 / 进军奎尔丹纳斯",
                 "bossKey": "lura",
                 "bossName": "鲁拉（至暗之夜降临）",
                 "avoidableSpells": {key: value["label"] for key, value in AVOIDABLE_SPELLS.items()},
                 "spellLabels": {str(key): value for key, value in SPELLS.items()},
                 "phaseConfig": {
                     "p1EndMs": P1_END_MS,
                    "p2EndMs": P2_END_MS,
                    "p2ToP3EndMs": P2_TO_P3_END_MS,
                    "p2ToP3SpreadReplayMs": P2_TO_P3_SPREAD_REPLAY_MS,
                    "p4SignalAfterMs": P4_SIGNAL_AFTER_MS,
                     "p4NoDeathMs": P4_NO_DEATH_MS,
                     "p4UniqueDeathIds": sorted(P4_UNIQUE_DEATH_IDS),
                     "stellarShardDamageIds": sorted(STELLAR_SHARD_IDS),
                     "stellarShardDebuffIds": sorted(STELLAR_SHARD_DEBUFF_IDS),
                 }},
        "data": {"page1_wipeAnalysis": [], "page2_glaiveBoard": [], "page2_avoidableBoard": {}},
    }

    for report_idx, report_id in enumerate(report_ids, start=1):
        progress(f"分析日志 {report_idx}/{len(report_ids)}：{report_id}")
        progress("读取角色与宠物归属", 1)
        actor_map = fetch_master_actor_map(token, report_id)
        progress(f"角色映射完成：{len(actor_map)} 个单位", 1)
        progress("匹配鲁拉战斗列表", 1)
        fights = fetch_report_fights(token, report_id)
        progress(f"匹配鲁拉战斗：{len(fights)} 场", 1)

        def analyze_one_fight(index_and_fight):
            fight_idx, fight = index_and_fight
            bar = progress_bar(fight_idx, len(fights))
            duration = format_time(fight["endTime"] - fight["startTime"])
            progress(f"{bar} Fight {fight['id']}，时长 {duration}", 1)

            def fight_progress(message):
                progress(message, 2)

            raw = fetch_fight_data(token, report_id, fight, actor_map, emit_progress=fight_progress)
            progress("分析灭团原因与个人榜单", 2)
            local_avoidable = {key: {} for key in AVOIDABLE_SPELLS}
            result = analyze_fight(report_id, fight, raw, local_avoidable)
            return fight_idx, result

        def report_fight_done(completed, total, result):
            _, fight_result = result
            progress(
                f"已完成 {completed}/{total} 场鲁拉战斗：Fight {fight_result['fightID']}",
                1,
            )

        for _, result in run_parallel_indexed(
            list(enumerate(fights, start=1)),
            analyze_one_fight,
            on_complete=report_fight_done,
        ):
            merge_avoidable_summary(global_avoidable, result["avoidableSummary"])
            if result["deathTimeline"] or result["wipePhase"] == "P4":
                final_output["data"]["page1_wipeAnalysis"].append(result)
                progress(f"判定结果：{result['wipePhase']} / {result['wipeReason']} / 死亡时间线 {len(result['deathTimeline'])} 条", 2)
            else:
                progress("本场无有效死亡记录，跳过灭团面板输出", 2)

    progress("汇总可躲避伤害排行榜", 1)
    for key, rows in global_avoidable.items():
        sorted_rows = sorted(rows.values(), key=lambda item: item["totalDamage"], reverse=True)
        for idx, row in enumerate(sorted_rows, start=1): row["rank"] = idx
        final_output["data"]["page2_avoidableBoard"][key] = sorted_rows

    final_output["data"]["page2_glaiveBoard"] = final_output["data"]["page2_avoidableBoard"].get("skyGlaive", [])
    progress("分析完成，准备写入 JSON", 1)
    return final_output


if __name__ == "__main__":
    from boss_plugins.common import write_json_result

    final_json = build_aggregated_json()
    out_file = write_json_result(final_json, report_ids=globals().get("REPORT_IDS_INPUT") or "", boss_key="midnight_falls")
    progress(f"聚合分析完成：{out_file}")
