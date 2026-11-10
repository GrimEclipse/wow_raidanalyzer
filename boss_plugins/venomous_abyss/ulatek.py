"""Evidence-first analyzer for Ula'tek."""

from __future__ import annotations

from copy import deepcopy
import math
from bisect import bisect_left, bisect_right
from statistics import median
from analyzer_core.event_evidence import actor_position

from analyzer_core.config import resolve_analysis_options

CONFIG_SCHEMA = [{'key': 'wavesReviewEnabled', 'type': 'boolean', 'label': '腐蚀浪潮与带蛋', 'description': '', 'default': True}, {'key': 'rageReviewEnabled', 'type': 'boolean', 'label': '被缚之怒', 'description': '', 'default': True}, {'key': 'fangsReviewEnabled', 'type': 'boolean', 'label': '攫取毒牙', 'description': '', 'default': True}, {'key': 'criticalReviewEnabled', 'type': 'boolean', 'label': '关键流程与蛇母之怒', 'description': '', 'default': True}]
CONFIG_SCHEMA.append({'key': 'fangSafeStacks', 'type': 'number', 'label': '攫取毒牙拉断安全层数', 'description': '拉断后凋萎静脉达到此层数以内视为安全；按团队战术填写。', 'default': 3, 'integer': True, 'min': 0, 'max': 20, 'step': 1, 'visibleWhen': {'field': 'fangsReviewEnabled', 'equals': True}})
CONFIG_SCHEMA.append({'key': 'fullReplayEnabled', 'type': 'boolean', 'label': '场地推演', 'default': True,
                      'description': '显示整场玩家移动、首领施法、携蛋、毒牙连线与中波反馈。'})
CONFIG_SCHEMA.append({'key': 'eggDutyPlayers', 'type': 'playerList', 'label': '指定搬蛋成员', 'default': [],
                      'description': '阿瓦隆留空时使用固定 8 人名单；其他公会请填写本场搬蛋组。名单不足 8 人时不判定抢蛋。'})
CONFIG_SCHEMA.append({'key': 'cleanWaveReviewEnabled', 'type': 'boolean', 'label': '统计有效中波', 'default': False,
                      'description': '另列同阶段首次漏接前、且团队同时死亡未达到 2 人时的中波受击。原始中波次数始终保留。',
                      'visibleWhen': {'field': 'wavesReviewEnabled', 'equals': True}})
CRITICAL_FIELDS = {
    "maliceReviewEnabled": ("malice", "恶意打断"),
    "meleeReviewEnabled": ("nonTankMelee", "非坦克近战伤害"),
    "motherWrathReviewEnabled": ("motherWrath", "蛇母之怒承接与全团伤害"),
    "platformReviewEnabled": ("platformTransitions", "碎场流程与减伤"),
    "serpentBitesReviewEnabled": ("serpentBites", "毒蛇之咬分摊与位置"),
    "p25EggsReviewEnabled": ("p25Eggs", "P2.5 带蛋死亡与携蛋情况"),
    "coiledPreyReviewEnabled": ("coiledPreyDeaths", "盘绕猎物死亡"),
}
CONFIG_SCHEMA += [{"key": key, "type": "boolean", "label": label, "default": True,
                   "visibleWhen": {"field": "criticalReviewEnabled", "equals": True}}
                  for key, (_, label) in CRITICAL_FIELDS.items()]


def _critical_enabled(options, key):
    return options["criticalReviewEnabled"] and options[key]


from collections import Counter, defaultdict

from analyzer_core.court_rules import validate_court_profile
from boss_plugins.combat_config import PERSONAL_DEFENSIVES, find_defensive_uses_before_death
from boss_plugins.common import COMBAT_RES_SPELLS, write_json_result
from boss_plugins.venomous_abyss.runtime import build_aggregated_json as _build
from boss_plugins.venomous_abyss.shared import (
    ability_id,
    build_position_index,
    completed_casts,
    event_type,
    fmt_ms,
    load_confirmed_spell_names,
    load_confirmed_source_names,
    nightly_detail,
    nightly_player_totals,
    player_ref,
    position_at_interpolated,
    spell_name,
    source_name,
)


ULATEK_SPELL_NAMES = {
    1: "近战攻击",
    1286834: "死疽蒸汽",
    1286835: "死疽蒸汽",
    1286860: "被缚之怒",
    1286885: "落石",
    1287032: "剧毒撕咬",
    1287265: "幽魂盘卷",
    1287955: "虚空侵染外壳符文",
    1288879: "毒蛇之咬",
    1290409: "疫鳞卵簇",
    1290779: "恶意",
    1290991: "恶意",
    1292211: "腐蚀浪潮",
    1292403: "腐蚀浪潮",
    1295360: "恶性甲壳",
    1295905: "毒蛇之咬",
    1296301: "响尾猛击",
    1298570: "腐蚀浪潮",
    1298367: "蛇母之怒",
    1298369: "蛇母之怒",
    1298417: "岩石剧毒",
    1298418: "岩石剧毒",
    1299010: "幽魂盘卷",
    1299526: "烈毒之心",
    1299206: "响尾震击",
    1299650: "硬化外壳",
    1299759: "毒性孵化",
    1299919: "毒性孵化",
    1300312: "厄鳞外壳",
    1300751: "毒蛇呼唤",
    1300685: "灵魂绞杀者",
    1301007: "无羁之怒",
    1301117: "攫取毒牙",
    1301122: "蛇母之怒",
    1301268: "腐臭薄膜",
    1301510: "盘绕猎物",
    1301512: "下潜",
    1302950: "蠕动孕育",
    1303410: "缺陷：虚弱",
    1303414: "石化钉刺",
    1305163: "石化钉刺预兆",
    1304012: "毒蛇呼唤",
    1315541: "毒蛇呼唤",
    1305650: "痛苦哀嚎",
    1305709: "痛苦挣扎",
    1305775: "恐怖咆哮",
    1305878: "易爆清除",
    1306119: "钙化尸骸",
    1306862: "孵化厄运",
    1307367: "被缚之怒",
    1307617: "毒性甲壳",
    1307612: "毒性甲壳",
    1307635: "剧毒喷溅",
    1313754: "蠕动孕育",
    1313757: "沸腾毒液",
    1313758: "沸腾毒液",
    1319282: "腐蚀浪潮",
    1310763: "腐败爆发",
    1310764: "尖啸",
    1311609: "凋萎静脉",
    1312150: "腐臭蛋黄",
    1312262: "毒性灼烧",
    1311611: "攫取毒牙",
    1311612: "攫取毒牙",
    1312967: "易爆清除",
    1313529: "摄入毒液",
    1313531: "酸液喷发",
    1315341: "盘绕猎物",
    1316356: "易爆清除",
    1316357: "易爆清除",
    1317955: "凋萎静脉",
    1318329: "钙化尸骸",
}

GUIDE_SPELLS = {**load_confirmed_spell_names(), **ULATEK_SPELL_NAMES}
SOURCE_NAMES = load_confirmed_source_names()
EGG_CARRY_ID = 1295360
MYTHIC_EGG_CARRY_ID = 1307612
DOOMSCALE_EGG_CONTACT_ID = 1300312
DOOMSCALE_EGG_GAME_ID = 268164
DOOMSCALE_HATCH_CAST_ID = 1306862
EGG_CARRY_IDS = (EGG_CARRY_ID, MYTHIC_EGG_CARRY_ID)
EGG_COLLISION_SPLASH_ID = 1307635
HARDENED_SHELL_ID = 1299650
REPLAY_EGG_GAME_IDS = {265644, 266085, 268121, 263535, 268164, 271194}
CARRYABLE_EGG_GAME_IDS = {265644, 266085, 268121}
VOLATILE_PURGE_IDS = (1312967, 1316356)
MOTHER_WRATH_RADIUS_YARDS = 3
VOLATILE_PURGE_WARNING_MS = 6000
FESTER_BURST_ID = 1310763
TOXIC_INCUBATION_HIT_ID = 1299919
TOXIC_INCUBATION_CAST_ID = 1299759
BLIGHTSCALE_WRETCH_GAME_ID = 263942
BLIGHTSCALE_VIPER_GAME_ID = 261915
PETRIFYING_SPINE_ID = 1303414
PETRIFYING_SPINE_MARK_ID = 1305163
PETRIFYING_SPINE_RADIUS_YARDS = 8
AVALON_GUILD_ID = 774422
AVALON_EGG_DUTY_NAMES = ('贪睡熊熊', '茶喵不吃糖', '叮咚好烦', 'toccata',
                         'kamin*', '残夜将歇', '飞天小喷菇', '小心胡大海')
# One shared visual speed for every wave source; the 14-yard estimate matches
# the clearest cast-to-first-hit intervals in Fight 35 within position noise.
REPLAY_WAVE_SPEED_YARDS_PER_SECOND = 14
REPLAY_WAVE_TRAVEL_YARDS = 65
REPLAY_WAVE_WIDTH_YARDS = 3
BOSS_CAUSTIC_WAVE_CAST_ID = 1319282
BOSS_CAUSTIC_WAVE_EDGE_CAST_ID = 1311807
DESPERATE_THRASH_ID = 1305709
DESPERATE_THRASH_ANGLE_DEGREES = 60
DESPERATE_THRASH_LENGTH_YARDS = 30
RATTLER_SLAM_ID = 1299206
WAVE_ID = 1292403
RAGE_ID = 1286860
HEART_ID = 1299526
ULATEK_GAME_ID = 257758
HEART_GAME_ID = 267460
DEVOURERS_SPAWN_GAME_ID = 266085
BLIGHTSCALE_SHRIEKER_GAME_ID = 273577
FANG_AURA_ID = 1311611
FANG_BREAK_RADIUS_YARDS = 15
BLIGHT_VEIN_ID = 1311609
DEVOURERS_SPAWN_SHELL_ID = 1290990
SERPENT_BITE_TARGET_ID = 1288879
INGESTED_VENOM_ID = 1313529
CALCIFIED_CORPSE_ID = 1306119
SERPENT_BITE_RADIUS_YARDS = 7
WAVE_DEATH_WINDOW_MS = 1_000
WAVE_COUNT_DEATH_THRESHOLD = 2
BASELINE_P3_SHRIEKERS = {1: 0, 2: 0, 3: 1, 4: 2}
HEALTHSTONE_IDS = {6262, 452930, 387636}
HEALING_POTION_IDS = {1234768, 1295247}
BURST_POTIONS = {1236616: "圣光潜力", 1236994: "鲁莽药水", 1295132: "液态光泽"}
P25_COIL_CAST_ID = 1299010
P25_COIL_DAMAGE_ID = 1287265
P25_COIL_COUNT = 6
P25_MYTHIC_COIL_COUNT = 8
P25_FLOOR_BREAK_DELAY_MS = 5000
P25_EGG_SETTLE_MS = 250
SPECTRAL_COIL_GAME_ID = 267679
# Visual geometry follows the owner's annotated intermission diagram. These
# regions are not a hit classifier; keep real Coil coordinates as evidence.
FESTER_SAFE_RADIUS_YARDS = 10
COIL_SOAK_RADIUS_YARDS = FESTER_SAFE_RADIUS_YARDS
COIL_DIAGRAM_RADIUS_YARDS = 8
COIL_PLATFORM_IMAGE_BOUNDARY = (
    (.398, .05), (.602, .05), (.75, .315), (.75, .685),
    (.602, .95), (.398, .95), (.25, .685), (.25, .315),
)
COIL_REGION_IMAGE_CENTERS = (
    (.6915, .3568), (.5757, .1686), (.4220, .1686), (.3154, .3527),
    (.3142, .6309), (.4186, .8273), (.5757, .8273), (.6915, .6309),
)
REPLAY_INTERRUPT_IDS = {1766,47528,57994,147362,2139,183752,97547,6552}
REPLAY_CAST_EXPECTED_MS = {1290779: 1500, 1305650: 2500, 1305775: 2500,
                           1310764: 3000}

BOSS_CONFIG = {
    "key": "ulatek",
    "encounterIDs": {3492, 53492},
    "name": "乌拉特克",
    "arena": "assets/raids/venomous_abyss/08-ulatek-arena.jpg",
    "spellNames": GUIDE_SPELLS,
    "bossGameID": ULATEK_GAME_ID,
    "bossNameKeywords": {"Ula'tek", "乌拉特克"},
    "fetchPositionResources": True,
    "fetchCastResources": True,
    "trackedActorGameIDs": {BLIGHTSCALE_SHRIEKER_GAME_ID},
    "trackedDamageTargetGameIDs": {ULATEK_GAME_ID, HEART_GAME_ID, DEVOURERS_SPAWN_GAME_ID},
    "tabs": [
        ["survival", "全场存活情况"],
        ["replay", "场地回放"],
        ["waves", "腐蚀浪潮和带蛋情况"],
        ["heart", "被缚之怒"],
        ["fangs", "攫取毒牙处理"],
        ["critical", "关键流程问题"],
    ],
    "mechanicVersion": "ulatek-phase-exemptions-viper-splash-2026-11-10-v39",
    "features": {"survival": True, "fieldReplay": True},
}

COURT_PROFILE = {
    "bossKey": "ulatek",
    "phaseModel": "cast_and_aura_timeline",
    "phaseRule": "P1/P2/P3 以被缚之怒结束点切分；最终碎场轮次以盘绕猎物施法切分。",
    "rules": [
        {
            "key": "egg_collision", "label": "撞蛋", "mode": "direct",
            "spellIDs": [1295360, 1307612, 1301268, EGG_COLLISION_SPLASH_ID],
            "requiredEvidence": ["两名玩家同帧失去携蛋光环", "同帧孵化", "剧毒喷溅同时命中两人且场上没有已孵化的蝰蛇，或可靠位置相距不超过 4 码", "无中波或幽魂盘卷结算"],
            "defaultCountEnabled": True, "severityUnits": 1,
        },
        {
            "key": "caustic_wave_hit",
            "label": "命中腐蚀浪潮",
            "mode": "direct",
            "spellIDs": [1292403],
            "requiredEvidence": ["腐蚀浪潮 Debuff apply/stack/refresh"],
            "defaultCountEnabled": False,
            "severityUnits": 1,
        },
        {
            "key": "egg_carrier_wave_hit",
            "label": "携带蛇卵命中腐蚀浪潮",
            "mode": "direct",
            "spellIDs": [1292403, 1295360],
            "requiredEvidence": ["恶性甲壳有效区间", "腐蚀浪潮施加", "恶性甲壳随后移除"],
            "defaultCountEnabled": False,
            "severityUnits": 2,
        },
        {
            "key": "fangs_excess_stack",
            "label": "攫取毒牙拉断后超过配置的凋萎静脉安全层数",
            "mode": "direct",
            "spellIDs": [1311611, 1311609],
            "requiredEvidence": ["攫取毒牙移除", "随后凋萎静脉全团层数变化", "团队配置的安全层数"],
            "defaultCountEnabled": True,
            "severityUnits": 1,
        },
        {
            "key": "mother_wrath_raidwide",
            "label": "蛇母之怒无人承接并触发全团伤害",
            "mode": "direct",
            "spellIDs": [1298367, 1298369, 1301122],
            "requiredEvidence": ["蛇母之怒完成施法", "同轮至少 3 名玩家受到蛇母之怒伤害", "施法目标或施法前 Boss 最近一次近战目标"],
            "defaultCountEnabled": True,
            "severityUnits": 2,
        },
    ],
}
validate_court_profile(COURT_PROFILE)


def _amount(event):
    value = event.get("amount")
    if value is None:
        value = event.get("unmitigatedAmount")
    return int(value or 0)


def _aura_intervals(events, spell_id, fight_end):
    active = {}
    intervals = []
    for event in sorted(
        (row for row in events if int(ability_id(row) or 0) == spell_id),
        key=lambda row: int(row.get("timestamp") or 0),
    ):
        player_id = event.get("targetID")
        timestamp = int(event.get("timestamp") or 0)
        kind = event_type(event)
        if kind in {"applydebuff", "applydebuffstack", "refreshdebuff", "applybuff", "refreshbuff"}:
            active.setdefault(player_id, timestamp)
        elif kind in {"removedebuff", "removebuff"} and player_id in active:
            intervals.append({"playerID": player_id, "start": active.pop(player_id), "end": timestamp})
    for player_id, start in active.items():
        intervals.append({"playerID": player_id, "start": start, "end": int(fight_end), "openEnded": True})
    return sorted(intervals, key=lambda row: (row["start"], row["playerID"] or 0))


def _rage_windows(fight, raw):
    return _aura_intervals(raw["enemyBuffs"], RAGE_ID, fight["endTime"])


def _positions(raw, key='resources'):
    """Share one index per unchanged event list within this fight only."""
    rows = raw.get(key) or []
    cache = raw.setdefault('_positionIndexes', {})
    cached = cache.get(key)
    if cached is None or cached[0] is not rows:
        cached = (rows, build_position_index(rows))
        cache[key] = cached
    return cached[1]


def _carry_intervals(events, fight_end):
    return sorted([row for sid in EGG_CARRY_IDS
                   for row in _aura_intervals(events, sid, fight_end)],
                  key=lambda row: (row['start'], row['playerID'] or 0))


def _phase_at(timestamp, rage_windows):
    if not rage_windows or timestamp < rage_windows[0]["end"]:
        return "P1"
    if len(rage_windows) == 1 or timestamp < rage_windows[1]["end"]:
        return "P2"
    return "P3"


def _wave_exemption_phase_at(timestamp, fight, raw, rage_windows):
    phase = _phase_at(timestamp, rage_windows)
    if phase != "P3" or len(rage_windows) < 2:
        return phase
    after = rage_windows[1]["end"]
    casts = raw.get("casts") or []
    markers = [int(row["timestamp"]) for row in casts
               if ability_id(row) in {1295905, 1315341}
               and event_type(row) in {"begincast", "cast"}
               and int(row["timestamp"]) > after]
    coils = sorted(int(row["timestamp"]) for row in casts
                   if ability_id(row) == P25_COIL_CAST_ID and event_type(row) == "cast"
                   and int(row["timestamp"]) >= after)
    count = P25_MYTHIC_COIL_COUNT if int(fight.get("difficulty") or 0) == 5 else P25_COIL_COUNT
    if len(coils) >= count:
        markers.append(coils[count - 1] + P25_FLOOR_BREAK_DELAY_MS)
    return "P3" if markers and timestamp >= min(markers) else "P2.5"


def _progression_fields(phase):
    return {"fightPhase": phase, "wipePhase": phase,
            "phaseOrder": {"P1": 10, "P2": 20, "P2.5": 25, "P3": 30}.get(phase, 99)}


def _progression_phase(fight, raw):
    events = raw.get("enemyBuffs", []) + raw.get("casts", []) + raw.get("trackedActorEvents", [])
    events = list({_event_identity(e): e for e in events}.values())
    rage = _rage_windows(fight, {"enemyBuffs": events})
    finished = [r for r in rage if not r.get("openEnded") and r["end"] < fight["endTime"]]
    phase = "P1" if not finished else "P2"
    if len(finished) >= 2:
        phase = "P2.5"
        after = finished[1]["end"]
        coils = sorted(int(e["timestamp"]) for e in events if ability_id(e) == P25_COIL_CAST_ID
                       and event_type(e) == "cast" and after <= int(e["timestamp"]) <= fight["endTime"])
        p3_seen = any(ability_id(e) in {1295905, 1315341} and event_type(e) in {"begincast", "cast"}
                      and after < int(e["timestamp"]) <= fight["endTime"] for e in events)
        count = P25_MYTHIC_COIL_COUNT if int(fight.get('difficulty') or 0) == 5 else P25_COIL_COUNT
        if p3_seen or (len(coils) >= count and coils[count - 1] + P25_FLOOR_BREAK_DELAY_MS < fight["endTime"]):
            phase = "P3"
    return _progression_fields(phase)


def restore_progression(pull):
    """Fill overview fields from full-fight evidence, never the nightly cutoff."""
    mechanics = pull.get("ulatek") or {}
    summary = mechanics.get("progression")
    if summary is None:
        # Existing exported reports contain the same phase evidence in these reviews.
        rage_review = mechanics.get("rage") or {}
        rounds = rage_review.get("rounds")
        if rounds is None:
            summary = _progression_fields("阶段证据不足")
        else:
            finished = [r for r in rounds if r.get("endTime") != pull.get("duration")]
            phase = "P1" if not finished else "P2"
            if len(finished) >= 2:
                eggs = (mechanics.get("critical") or {}).get("p25Eggs") or {}
                phase = "P3" if eggs.get("completed") else "P2.5"
            summary = _progression_fields(phase)
        mechanics["progression"] = summary
    pull.update(summary)
    if pull.get("isKill"):
        pull["wipePhase"] = "击杀"


def _active_interval(intervals, player_id, timestamp, *, removal_grace_ms=0):
    return next(
        (
            row for row in intervals
            if row["playerID"] == player_id
            and row["start"] <= timestamp <= row["end"] + int(removal_grace_ms)
        ),
        None,
    )


def _raid_aura_changes(events, spell_id):
    """Collapse one raidwide aura mutation into one canonical stack change."""
    candidates = sorted(
        (
            event for event in events
            if int(ability_id(event) or 0) == spell_id
            and event_type(event) in {"applydebuff", "applydebuffstack", "refreshdebuff"}
        ),
        key=lambda row: int(row.get("timestamp") or 0),
    )
    changes = []
    for event in candidates:
        timestamp = int(event.get("timestamp") or 0)
        if not changes or timestamp - changes[-1]["timestamp"] > 80:
            changes.append({"timestamp": timestamp, "toStack": 0, "eventTypes": set()})
        change = changes[-1]
        change["toStack"] = max(change["toStack"], int(event.get("stack") or 1))
        change["eventTypes"].add(event_type(event))
    for change in changes:
        change["eventTypes"] = sorted(change["eventTypes"])
    return changes


def _event_identity(event):
    return (
        int(event.get("timestamp") or 0),
        event_type(event),
        event.get("sourceID"),
        event.get("sourceInstance"),
        event.get("targetID"),
        event.get("targetInstance"),
        int(ability_id(event) or 0),
        event.get("stack"),
    )


def _owner_player_id(event, players, pet_owners):
    source_id = event.get("sourceID")
    seen = set()
    while source_id not in players and source_id in pet_owners and source_id not in seen:
        seen.add(source_id)
        source_id = pet_owners[source_id]
    return source_id if source_id in players else None


def _living_player_ids(players, raw, timestamp):
    living = set(players)
    changes = [
        (int(event.get("timestamp") or 0), "death", event.get("targetID"))
        for event in raw.get("deaths") or []
    ]
    changes.extend(
        (int(event.get("timestamp") or 0), "resurrect", event.get("targetID"))
        for event in (raw.get("friendlyCasts") or []) + (raw.get("trackedActorEvents") or [])
        if event_type(event) == "resurrect"
    )
    changes.extend(
        (int(event.get("timestamp") or 0), "resurrect",
         event.get("sourceID") if ability_id(event) == 21169 else event.get("targetID"))
        for event in raw.get("friendlyCasts") or []
        if event_type(event) == "cast" and ability_id(event) in COMBAT_RES_SPELLS
    )
    for event_time, kind, player_id in sorted(changes):
        if event_time > timestamp:
            break
        if kind == "death":
            living.discard(player_id)
        else:
            living.add(player_id)
    return living


def _analyze_waves_and_eggs(fight, actor_map, players, raw, rage_windows):
    egg_intervals = _carry_intervals(raw["debuffs"], fight["endTime"])
    p25 = _analyze_p25_eggs(fight, actor_map, players, {**raw, "enemyBuffs": raw.get("enemyBuffs", [])})
    def carry_phase(timestamp):
        if p25.get("started") and p25["dutyStartMs"] <= timestamp < p25["dutyEndMs"]:
            return "P2.5"
        return _phase_at(timestamp, rage_windows)
    def duty_phase(timestamp):
        # P2.5 requires carrying eggs for its own mechanic, but has no fixed
        # eight-player pickup assignment and cannot produce a "stolen egg".
        return "P1" if carry_phase(timestamp) == "P1" else None
    duty_carries = []
    for interval in egg_intervals:
        phase = duty_phase(interval["start"])
        if phase and interval["playerID"] in players:
            duty_carries.append({**player_ref(players, actor_map, interval["playerID"]), "phase": phase,
                                 "time": fmt_ms(interval["start"] - fight["startTime"]),
                                 "timeMs": interval["start"] - fight["startTime"],
                                 "endTimeMs": interval["end"] - fight["startTime"]})
    hatch_changes = _raid_aura_changes(raw["debuffs"], 1301268)
    wave_applies = [
        event for event in raw["debuffs"]
        if int(ability_id(event) or 0) == WAVE_ID
        and event.get("targetID") in players
        and event_type(event) in {"applydebuff", "applydebuffstack", "refreshdebuff"}
    ]
    # Keep raw aura mutations for review; the carrier statistic counts physical
    # contacts, so adjacent mutations from one wave must collapse per player.
    distinct_wave_applies = []
    seen = set()
    for event in sorted(wave_applies, key=lambda row: int(row.get("timestamp") or 0)):
        identity = _event_identity(event)
        if identity in seen:
            continue
        seen.add(identity)
        distinct_wave_applies.append(event)

    hits = []
    for event in distinct_wave_applies:
        timestamp = int(event.get("timestamp") or 0)
        player_id = event.get("targetID")
        # WCL can emit the egg-aura removal 1-20 ms before the same-frame wave
        # damage.  Keep a very small grace window and require the separate
        # Corrupting Film raid-aura mutation before calling the hatch confirmed.
        carry = _active_interval(egg_intervals, player_id, timestamp, removal_grace_ms=250)
        direct = min(
            (
                row for row in raw["damage"]
                if int(ability_id(row) or 0) == WAVE_ID
                and row.get("targetID") == player_id
                and abs(int(row.get("timestamp") or 0) - timestamp) <= 750
            ),
            key=lambda row: abs(int(row.get("timestamp") or 0) - timestamp),
            default=None,
        )
        hatch_change = min(
            (
                row for row in hatch_changes
                if abs(row["timestamp"] - timestamp) <= 500
            ),
            key=lambda row: abs(row["timestamp"] - timestamp),
            default=None,
        )
        removal_delta_ms = carry["end"] - timestamp if carry else None
        early_hatch = bool(
            carry
            and hatch_change
            and -250 <= removal_delta_ms <= 2500
        )
        hits.append({
            **player_ref(players, actor_map, player_id),
            "timeMs": timestamp - fight["startTime"],
            "time": fmt_ms(timestamp - fight["startTime"]),
            "phase": carry_phase(timestamp),
            "amount": _amount(direct or {}),
            "eggCarrier": bool(carry),
            "earlyHatchConfirmed": early_hatch,
            "eggRemovedAfterMs": removal_delta_ms,
            "hatchEvidence": ({
                "spellID": 1301268,
                "time": fmt_ms(hatch_change["timestamp"] - fight["startTime"]),
                "deltaMs": hatch_change["timestamp"] - timestamp,
                "toStack": hatch_change["toStack"],
            } if hatch_change else None),
            "eventType": event_type(event),
        })

    wave_deaths = []
    seen_wave_deaths = set()
    for row in hits:
        hit_timestamp = fight["startTime"] + row["timeMs"]
        death = min(
            (
                event for event in raw.get("deaths") or []
                if event.get("targetID") == row["playerID"]
                and hit_timestamp <= int(event.get("timestamp") or 0) <= hit_timestamp + WAVE_DEATH_WINDOW_MS
            ),
            key=lambda event: int(event.get("timestamp") or 0),
            default=None,
        )
        row["diedWithinWindow"] = bool(death)
        if death is not None:
            death_timestamp = int(death.get("timestamp") or 0)
            death_ability_id = int(death.get("killingAbilityGameID") or ability_id(death) or 0)
            row["deathDelayMs"] = death_timestamp - hit_timestamp
            row["deathAbilityID"] = death_ability_id
            identity = (row["playerID"], death_timestamp)
            if identity not in seen_wave_deaths:
                seen_wave_deaths.add(identity)
                wave_deaths.append({
                    **player_ref(players, actor_map, row["playerID"]),
                    "phase": row["phase"],
                    "waveTime": row["time"],
                    "deathTime": fmt_ms(death_timestamp - fight["startTime"]),
                    "delayMs": death_timestamp - hit_timestamp,
                    "abilityID": death_ability_id,
                    "ability": spell_name(death_ability_id, GUIDE_SPELLS),
                })
    carries = []
    for interval in egg_intervals:
        phase = carry_phase(interval["start"])
        if phase not in {"P1", "P2.5", "P3"}:
            continue
        player_id = interval["playerID"]
        related_hits = [
            row for row in hits
            if row["playerID"] == player_id
            and interval["start"] <= fight["startTime"] + row["timeMs"] <= interval["end"] + 250
        ]
        distinct_related_hits = []
        for hit in related_hits:
            if not distinct_related_hits or hit["timeMs"] - distinct_related_hits[-1]["timeMs"] > 750:
                distinct_related_hits.append(hit)
        carries.append({
            **player_ref(players, actor_map, player_id),
            "phase": phase,
            "startTime": fmt_ms(interval["start"] - fight["startTime"]),
            "endTime": fmt_ms(interval["end"] - fight["startTime"]),
            "durationSec": round((interval["end"] - interval["start"]) / 1000, 2),
            "waveHitCount": len(distinct_related_hits),
            "earlyHatchCount": sum(row["earlyHatchConfirmed"] for row in related_hits),
            "openEnded": bool(interval.get("openEnded")),
        })
    possible_collision_hatches = []
    if int(fight.get("difficulty") or 0) == 5:
        for interval in egg_intervals:
            if interval.get("openEnded") or interval["playerID"] not in players:
                continue
            timestamp = interval["end"]
            if any(hit["playerID"] == interval["playerID"] and
                   abs(fight["startTime"] + hit["timeMs"] - timestamp) <= 750
                   for hit in hits):
                continue
            if any(abs(int(event.get("timestamp") or 0) - timestamp) <= 750
                   for event in raw.get("damage") or []
                   if int(ability_id(event) or 0) == P25_COIL_DAMAGE_ID):
                continue
            hatch = min((change for change in hatch_changes
                         if abs(change["timestamp"] - timestamp) <= 750),
                        key=lambda change: abs(change["timestamp"] - timestamp), default=None)
            if hatch:
                possible_collision_hatches.append({
                    **player_ref(players, actor_map, interval["playerID"]),
                    "time": fmt_ms(timestamp - fight["startTime"]),
                    "timeMs": timestamp - fight["startTime"],
                    "phase": carry_phase(timestamp),
                    "hatchTime": fmt_ms(hatch["timestamp"] - fight["startTime"]),
                    "hatchTimestamp": hatch["timestamp"],
                    "evidence": "携蛋光环移除与孵化同帧，未见浪潮或幽魂盘卷；需复核位置，不能单凭日志认定碰蛋",
                })
    collisions = []
    if possible_collision_hatches:
        position_index = _positions(raw, 'replayEvents' if raw.get('replayEvents') else 'resources')
        viper_ids = {row['id'] for row in raw.get('actorRows') or []
                     if row.get('gameID') == BLIGHTSCALE_VIPER_GAME_ID}
        viper_events = defaultdict(list)
        for stream in ('replayEvents', 'trackedActorEvents', 'resources', 'casts', 'damage',
                       'debuffs', 'enemyBuffs', 'trackedDamageTaken'):
            for event in raw.get(stream) or []:
                for side in ('source', 'target'):
                    actor_id = event.get(side + 'ID')
                    if actor_id in viper_ids:
                        viper_events[(actor_id, event.get(side + 'Instance') or 0)].append(
                            (int(event.get('timestamp') or 0),
                             event_type(event) == 'death' and side == 'target'))
        def viper_already_hatched(timestamp):
            for events in viper_events.values():
                born = min((time for time, died in events if not died), default=None)
                if born is None or born >= timestamp:
                    continue
                death = min((time for time, died in events if died and time >= born), default=None)
                if death is None or death > timestamp:
                    return True
            return False
        splash_by_player = defaultdict(list)
        for event in raw.get("damage") or []:
            if (ability_id(event) == EGG_COLLISION_SPLASH_ID
                    and event.get("targetID") in players):
                splash_by_player[event["targetID"]].append(int(event["timestamp"]))
        candidates = []
        for left_index, left in enumerate(possible_collision_hatches):
            left_position = _position_sample(position_index, left['playerID'],
                                             fight['startTime'] + left['timeMs'])
            for right_index in range(left_index + 1, len(possible_collision_hatches)):
                right = possible_collision_hatches[right_index]
                if (left['playerID'] == right['playerID'] or left['phase'] != right['phase']
                        or abs(left['timeMs'] - right['timeMs']) > 250
                        or abs(left['hatchTimestamp'] - right['hatchTimestamp']) > 150):
                    continue
                right_position = _position_sample(position_index, right['playerID'],
                                                  fight['startTime'] + right['timeMs'])
                distance_yards = (math.hypot(left_position['x'] - right_position['x'],
                                             left_position['y'] - right_position['y']) / 100
                                  if left_position and right_position
                                  and left_position['reliable'] and right_position['reliable'] else None)
                splash_pair = next(((left_ts, right_ts)
                                    for left_ts in splash_by_player[left['playerID']]
                                    for right_ts in splash_by_player[right['playerID']]
                                    if abs(left_ts - left['hatchTimestamp']) <= 500
                                    and abs(right_ts - right['hatchTimestamp']) <= 500
                                    and abs(left_ts - right_ts) <= 100
                                    and not viper_already_hatched(min(left_ts, right_ts))), None)
                if splash_pair or distance_yards is not None and distance_yards <= 4:
                    candidates.append((0 if splash_pair else 1,
                                       distance_yards if distance_yards is not None else math.inf,
                                       left_index, right_index, splash_pair))
        used = set()
        for _, distance_yards, left_index, right_index, splash_pair in sorted(candidates):
            if left_index in used or right_index in used:
                continue
            used.update((left_index, right_index))
            left, right = possible_collision_hatches[left_index], possible_collision_hatches[right_index]
            left['confirmedCollision'] = right['confirmedCollision'] = True
            collisions.append({'timeMs': min(left['timeMs'], right['timeMs']),
                               'time': left['time'], 'phase': left['phase'],
                               'players': [{key: row.get(key) for key in ('player', 'playerID', 'classColor')}
                                           for row in (left, right)],
                               'distanceYards': round(distance_yards, 2) if math.isfinite(distance_yards) else None,
                               'splashSpellID': EGG_COLLISION_SPLASH_ID if splash_pair else None,
                               'splashTime': fmt_ms(min(splash_pair) - fight['startTime']) if splash_pair else None,
                               'evidence': ('同帧携蛋光环移除与孵化，剧毒喷溅同时命中两人'
                                            if splash_pair else '同帧携蛋光环移除与孵化，且两人可靠坐标相距不超过 4 码')})
    configured = (raw.get("analysisOptions") or {}).get("eggDutyPlayers") or []
    guild = raw.get("reportGuild") or {}
    if not configured and int(guild.get("id") or 0) == AVALON_GUILD_ID:
        configured = AVALON_EGG_DUTY_NAMES
    def assigned(player):
        name = player["player"].casefold()
        return any((name.startswith(str(entry)[:-1].casefold()) and
                    str(player.get("icon") or "").startswith("shaman-"))
                   if str(entry).endswith("*") else name == str(entry).casefold()
                   for entry in configured)
    assigned_ids = {pid for pid in players if assigned(player_ref(players, actor_map, pid))}
    assignment_ready = len(assigned_ids) >= 8
    duty_carries.sort(key=lambda row: row["timeMs"])
    carry_rounds = []
    for carry in duty_carries:
        if not carry_rounds or carry["phase"] != carry_rounds[-1]["phase"] or carry["timeMs"] - carry_rounds[-1]["lastMs"] > 30_000:
            carry_rounds.append({"phase": carry["phase"], "lastMs": carry["timeMs"], "carries": []})
        carry_rounds[-1]["lastMs"] = carry["timeMs"]
        carry_rounds[-1]["carries"].append(carry)
    stolen_carries = []
    for index, round_row in enumerate(carry_rounds, 1):
        for carry in round_row["carries"]:
            if not assignment_ready or carry["playerID"] in assigned_ids:
                continue
            failures = []
            if any(hit["playerID"] == carry["playerID"] and hit["earlyHatchConfirmed"]
                   and carry["timeMs"] <= hit["timeMs"] <= carry["endTimeMs"] + 250 for hit in hits):
                failures.append("中波提前孵化")
            if any(row["playerID"] == carry["playerID"] and
                   abs(carry["endTimeMs"] - row["timeMs"]) <= 750
                   for row in possible_collision_hatches):
                failures.append("确认撞蛋提前孵化" if any(
                    row["playerID"] == carry["playerID"] and row.get("confirmedCollision")
                    and abs(carry["endTimeMs"] - row["timeMs"]) <= 750
                    for row in possible_collision_hatches) else "疑似碰蛋提前孵化")
            stolen_carries.append({**carry, "round": index, "failureKinds": failures,
                                   "earlyHatch": bool(failures)})
    distinct_carrier_hits = []
    for row in (hit for hit in hits if hit["eggCarrier"]):
        previous = next((hit for hit in reversed(distinct_carrier_hits)
                         if hit["playerID"] == row["playerID"]), None)
        if previous and row["timeMs"] - previous["timeMs"] <= 750:
            continue
        distinct_carrier_hits.append(row)
    distinct_duty_hits = [row for row in distinct_carrier_hits
                          if duty_phase(fight["startTime"] + row["timeMs"])]
    return {
        "spellID": WAVE_ID,
        "eggAuraID": EGG_CARRY_ID, "eggAuraIDs": list(EGG_CARRY_IDS),
        "hitCount": len(hits),
        "applicationCount": len(hits),
        "eggCarrierHitCount": len(distinct_carrier_hits),
        "earlyHatchCount": sum(row["earlyHatchConfirmed"] for row in hits),
        "possibleCollisionHatches": possible_collision_hatches,
        "eggCollisions": sorted(collisions, key=lambda row: row['timeMs']),
        "hits": hits,
        "waveDeathWindowMs": WAVE_DEATH_WINDOW_MS,
        "waveDeaths": {
            "totalCount": len(wave_deaths),
            "p1Count": sum(row["phase"] == "P1" for row in wave_deaths),
            "p3Count": sum(row["phase"] == "P3" for row in wave_deaths),
            "events": wave_deaths,
        },
        "carries": carries,
        "dutyCarries": duty_carries,
        "eggAssignment": {"configured": list(configured), "matchedCount": len(assigned_ids),
                           "ready": assignment_ready, "source": "avalon-default" if not (raw.get("analysisOptions") or {}).get("eggDutyPlayers") and int(guild.get("id") or 0) == AVALON_GUILD_ID else "configured" if configured else "missing"},
        "stolenCarries": stolen_carries,
        "dutyWaveHits": distinct_duty_hits,
        "dutyPlayers": [player_ref(players, actor_map, pid) for pid in players],
    }


def _position_sample(position_index, actor_id, timestamp):
    sample = position_at_interpolated(
        position_index,
        actor_id,
        timestamp,
        reliable_window_ms=3_000,
        fallback_window_ms=15_000,
    )
    if not sample:
        return None
    return {
        "x": round(float(sample["x"]), 2),
        "y": round(float(sample["y"]), 2),
        "sampleOffsetMs": int(sample.get("sampleOffsetMs") or 0),
        "reliable": bool(sample.get("reliable")),
    }


def _analyze_tether_failures(fight, actor_map, players, raw):
    """Completed spectral casts need five observed tank interception ticks."""
    start, end = int(fight["startTime"]), int(fight["endTime"])
    wretch_ids = {row["id"] for row in raw.get("actorRows") or []
                  if row.get("gameID") == BLIGHTSCALE_WRETCH_GAME_ID}
    actor_games = {row.get("id"): row.get("gameID") for row in raw.get("actorRows") or []}
    replay_rows = (raw.get("replayEvents") or []) + (raw.get("resources") or []) + (raw.get("trackedActorEvents") or [])
    positions = _positions(raw)
    failures = []
    for cast in sorted((e for e in raw.get("casts") or []
                        if event_type(e) == "cast" and ability_id(e) == TOXIC_INCUBATION_CAST_ID),
                       key=lambda e: int(e["timestamp"])):
        ts = int(cast["timestamp"])
        instance = cast.get("sourceInstance") or 0
        ticks = [e for e in raw.get("damage") or []
                 if ability_id(e) == TOXIC_INCUBATION_HIT_ID
                 and (e.get("sourceID") == cast.get("sourceID")
                      or actor_games.get(e.get("sourceID")) == actor_games.get(cast.get("sourceID"))
                      and actor_games.get(cast.get("sourceID")) is not None)
                 and (e.get("sourceInstance") or 0) == instance
                 and ts - 100 <= int(e["timestamp"]) <= ts + 5_500
                 and players.get(e.get("targetID"), {}).get("role") == "tank"]
        tick_times = {int(e["timestamp"]) // 300 for e in ticks}
        wretch_samples, wretch_deaths = [], []
        for event in replay_rows:
            event_ts = int(event.get("timestamp") or 0)
            for side in ("source", "target"):
                if event.get(side + "ID") not in wretch_ids or (event.get(side + "Instance") or 0) != instance:
                    continue
                if side == "target" and event_type(event) == "death":
                    wretch_deaths.append(event_ts)
                point = actor_position(event, side)
                if point and abs(event_ts - ts) <= 5_500:
                    wretch_samples.append((abs(event_ts - ts), event.get(side + "ID"), point))
        if end < ts + 5_500 or any(death <= ts + 5_500 for death in wretch_deaths):
            continue
        if len(tick_times) >= 5:
            continue
        source = actor_position(cast, "source")
        target_id, target = (None, None)
        if wretch_samples:
            _, target_id, target = min(wretch_samples, key=lambda row: row[0])
        if target is None and cast.get("targetID") in wretch_ids:
            target_id = cast["targetID"]
            target = actor_position(cast, "target") or _position_sample(positions, target_id, ts)
        candidates = []
        if source and target:
            dx, dy = target["x"] - source["x"], target["y"] - source["y"]
            length = math.hypot(dx, dy)
            if length:
                for pid, player in players.items():
                    if player.get("role") != "tank":
                        continue
                    point = _position_sample(positions, pid, ts)
                    if not point or not point["reliable"]:
                        continue
                    along = ((point["x"] - source["x"]) * dx + (point["y"] - source["y"]) * dy) / length**2
                    lateral = abs((point["x"] - source["x"]) * dy - (point["y"] - source["y"]) * dx) / length / 100
                    if -0.2 <= along <= 1.2:
                        candidates.append((lateral, pid))
        candidates.sort()
        player_id = (candidates[0][1] if candidates and candidates[0][0] <= 12
                     and (len(candidates) == 1 or candidates[1][0] - candidates[0][0] >= 3) else None)
        attribution = "nearest-tank-to-line" if player_id else "unresolved"
        tick_owners = Counter(event.get("targetID") for event in ticks)
        if player_id is None and len(tick_owners) == 1:
            player_id = next(iter(tick_owners))
            attribution = "observed-interception-ticks"
        if player_id is None and source:
            distances = sorted((math.hypot(point["x"] - source["x"], point["y"] - source["y"]) / 100, pid)
                               for pid, player in players.items() if player.get("role") == "tank"
                               for point in [_position_sample(positions, pid, ts)] if point and point["reliable"])
            if distances and distances[0][0] <= 30 and (len(distances) == 1 or distances[1][0] - distances[0][0] >= 5):
                player_id = distances[0][1]
                attribution = "nearest-tank-to-caster"
        ref = player_ref(players, actor_map, player_id) if player_id else {}
        begins = [int(e["timestamp"]) for e in raw.get("casts") or []
                  if event_type(e) == "begincast" and ability_id(e) == TOXIC_INCUBATION_CAST_ID
                  and (e.get("sourceInstance") or 0) == instance and ts - 10_000 <= int(e["timestamp"]) < ts]
        failures.append({"timeMs": ts - start, "time": fmt_ms(ts - start),
                         "castStartTimeMs": (max(begins) if begins else ts) - start,
                         "sourceID": cast.get("sourceID"), "sourceInstance": instance,
                         "sourcePosition": source, "targetID": target_id, "targetInstance": instance,
                         "targetPosition": target, "tickCount": len(tick_times),
                         "playerID": player_id, "player": ref.get("player"),
                         "classColor": ref.get("classColor"),
                         "attribution": attribution})
    return {"castID": TOXIC_INCUBATION_CAST_ID, "hitID": TOXIC_INCUBATION_HIT_ID,
            "expectedTicks": 5, "failureCount": len(failures), "failures": failures}


def _clean_wave_hits(fight, players, raw, waves, tether_review):
    cutoff = _nightly_collapse(fight, players, raw, WAVE_COUNT_DEATH_THRESHOLD) or fight["endTime"]
    rage_windows = _rage_windows(fight, raw)
    first_failure = {}
    for row in tether_review.get("failures") or []:
        timestamp = fight["startTime"] + row["timeMs"]
        phase = _wave_exemption_phase_at(timestamp, fight, raw, rage_windows)
        first_failure[phase] = min(first_failure.get(phase, cutoff), timestamp)
    return [row for row in waves["hits"]
            if fight["startTime"] + row["timeMs"] < min(
                cutoff, first_failure.get(_wave_exemption_phase_at(
                    fight["startTime"] + row["timeMs"], fight, raw, rage_windows), cutoff))]


def _analyze_p25_eggs(fight, actor_map, players, raw):
    count = P25_MYTHIC_COIL_COUNT if int(fight.get('difficulty') or 0) == 5 else P25_COIL_COUNT
    result = {"enabled": True, "started": False, "completed": False, "expectedSoakCount": count,
              "completedSoakCount": 0, "deaths": [], "remaining": [], "deathCount": 0,
              "remainingCount": 0, "mistakeCount": 0,
              "evidenceNote": f"P2.5 按第二次被缚之怒结束后的{count}次幽魂盘卷界定。阶段内带蛋死亡单独统计；分摊结束仍携蛋仅供复盘，不判玩家失误。预留250毫秒处理同帧光环移除；日志不足或分摊未完成时不判残留。"}
    rage = _rage_windows(fight, raw)
    if len(rage) < 2 or rage[1].get("openEnded"):
        result["reason"] = "尚未确认第二次被缚之怒结束"
        return result
    after_rage = rage[1]["end"]
    unique = {_event_identity(e): e for e in raw.get("casts", [])}
    casts = sorted(unique.values(), key=lambda e: int(e["timestamp"]))
    phase_limit = min([int(fight["endTime"])] + [int(e["timestamp"]) for e in casts
                     if int(e["timestamp"]) > after_rage and ability_id(e) in {1295905, 1315341}
                     and event_type(e) in {"begincast", "cast"}])
    coils = [e for e in casts if ability_id(e) == P25_COIL_CAST_ID
             and after_rage <= int(e["timestamp"]) < phase_limit and event_type(e) in {"begincast", "cast"}]
    if not coils:
        result["reason"] = "尚未观测到 P2.5 连续幽魂盘卷"
        return result
    stage_start = min(int(e["timestamp"]) for e in coils)
    finishes = [e for e in coils if event_type(e) == "cast"]
    result.update(started=True, startTime=fmt_ms(stage_start - fight["startTime"]), completedSoakCount=len(finishes))
    completed = len(finishes) >= count
    checkpoint = None
    if completed:
        last = finishes[count - 1]
        last_ts = int(last["timestamp"])
        hits = [int(e["timestamp"]) for e in raw.get("damage", []) if ability_id(e) == P25_COIL_DAMAGE_ID
                and e.get("sourceID") == last.get("sourceID")
                and e.get("sourceInstance", 1) == last.get("sourceInstance", 1)
                and last_ts <= int(e["timestamp"]) <= last_ts + 1000]
        settlement = max([last_ts] + hits)
        checkpoint = settlement + P25_EGG_SETTLE_MS
        completed = checkpoint < int(fight["endTime"])
        result["lastSoakTime"] = fmt_ms(settlement - fight["startTime"])
    stage_end = checkpoint if completed else phase_limit
    result.update(dutyStartMs=after_rage, dutyEndMs=stage_end)
    result.update(completed=completed, endTime=fmt_ms(stage_end - fight["startTime"]))
    if not completed:
        result["reason"] = "连续分摊未完整结束或日志未覆盖结算后时刻，不判残留携蛋"
    deaths = sorted({_event_identity(e): e for e in raw.get("deaths", []) if event_type(e) == "death"
                     and e.get("targetID") in players}.values(), key=lambda e: int(e["timestamp"]))
    carries = _carry_intervals(raw.get("debuffs", []), fight["endTime"])
    for aura in carries:
        aura["end"] = min([aura["end"]] + [int(e["timestamp"]) for e in deaths
                          if e.get("targetID") == aura["playerID"] and aura["start"] <= int(e["timestamp"]) <= aura["end"]])
    for death in deaths:
        pid, ts = death["targetID"], int(death["timestamp"])
        carry = next((a for a in carries if a["playerID"] == pid and a["start"] < ts <= a["end"]), None)
        if stage_start <= ts <= stage_end and carry:
            sid = int(death.get("killingAbilityGameID") or ability_id(death) or 0)
            result["deaths"].append({**player_ref(players, actor_map, pid), "time": fmt_ms(ts - fight["startTime"]),
                                     "carryStartTime": fmt_ms(carry["start"] - fight["startTime"]),
                                     "abilityID": sid, "ability": spell_name(sid, GUIDE_SPELLS), "isPlayerMistake": False})
    if completed:
        living = _living_player_ids(players, raw, checkpoint)
        for pid in sorted(living):
            carry = next((a for a in carries if a["playerID"] == pid and a["start"] <= checkpoint and a["end"] > checkpoint), None)
            if carry:
                result["remaining"].append({**player_ref(players, actor_map, pid), "time": fmt_ms(checkpoint - fight["startTime"]),
                                            "carryStartTime": fmt_ms(carry["start"] - fight["startTime"]),
                                            "spellID": EGG_CARRY_ID, "isPlayerMistake": False,
                                            "reason": f"P2.5 {count}次幽魂盘卷结束后仍携带蛇卵，仅供复盘"})
    result["deathCount"], result["remainingCount"], result["mistakeCount"] = (
        len(result["deaths"]), len(result["remaining"]), 0)
    return result


def _analyze_serpent_bites(fight, actor_map, players, raw):
    casts = sorted(completed_casts(raw.get("casts") or [], 1295905), key=lambda row: int(row["timestamp"]))
    target_events = sorted(
        (
            event for event in raw.get("debuffs") or []
            if int(ability_id(event) or 0) == SERPENT_BITE_TARGET_ID
            and event.get("targetID") in players
        ),
        key=lambda row: int(row.get("timestamp") or 0),
    )
    position_index = _positions(raw, 'replayEvents' if raw.get('replayEvents') else 'resources')
    rounds = []
    for index, cast in enumerate(casts, start=1):
        cast_time = int(cast["timestamp"])
        next_cast = int(casts[index]["timestamp"]) if index < len(casts) else int(fight["endTime"])
        applies = [
            event for event in target_events
            if event_type(event) == "applydebuff"
            and cast_time - 250 <= int(event["timestamp"]) < min(cast_time + 2_500, next_cast)
        ]
        if not applies:
            continue
        target_ids = list(dict.fromkeys(event.get("targetID") for event in applies))
        removals = {
            player_id: min(
                (
                    event for event in target_events
                    if event.get("targetID") == player_id
                    and event_type(event) == "removedebuff"
                    and cast_time <= int(event["timestamp"]) < next_cast
                ),
                key=lambda row: int(row["timestamp"]),
                default=None,
            )
            for player_id in target_ids
        }
        completed_removals = [event for event in removals.values() if event is not None]
        snapshot_time = min(
            (int(event["timestamp"]) for event in completed_removals),
            default=min(next_cast - 1, cast_time + 9_500),
        )
        living = _living_player_ids(players, raw, snapshot_time)
        target_rows = []
        target_positions = []
        for player_id in target_ids:
            removal = removals[player_id]
            removal_time = int(removal["timestamp"]) if removal else snapshot_time
            position = _position_sample(position_index, player_id, removal_time)
            calcified = any(
                int(ability_id(event) or 0) == CALCIFIED_CORPSE_ID
                and event.get("targetID") == player_id
                and abs(int(event.get("timestamp") or 0) - removal_time) <= 500
                and event_type(event) in {"applydebuff", "applybuff"}
                for event in raw.get("debuffs") or []
            )
            volatile_purge = any(
                int(ability_id(event) or 0) in {1312967, 1316356}
                and event.get("targetID") == player_id
                and abs(int(event.get("timestamp") or 0) - removal_time) <= 500
                and event_type(event) == "applydebuff"
                for event in raw.get("debuffs") or []
            )
            row = {
                **player_ref(players, actor_map, player_id),
                "removeTime": fmt_ms(removal_time - fight["startTime"]) if removal else None,
                "removed": bool(removal),
                "resolution": "calcified_corpse" if calcified else ("volatile_purge" if volatile_purge else ("removed" if removal else "unresolved")),
                "volatilePurgeApplied": volatile_purge,
                "position": position,
            }
            target_rows.append(row)
            if position and position["reliable"]:
                target_positions.append((player_id, position))

        aura_participant_ids = sorted({
            event.get("targetID")
            for event in raw.get("debuffs") or []
            if int(ability_id(event) or 0) == INGESTED_VENOM_ID
            and event.get("targetID") in living
            and cast_time <= int(event.get("timestamp") or 0) <= snapshot_time
            and event_type(event) in {"applydebuff", "applydebuffstack", "refreshdebuff"}
        })
        aura_participant_set = set(aura_participant_ids) | set(target_ids)
        purge_events = [event for event in raw.get("debuffs") or []
                        if int(ability_id(event) or 0) in {1312967, 1316356}
                        and event_type(event) == "applydebuff"
                        and snapshot_time - 250 <= int(event.get("timestamp") or 0) <= snapshot_time + 750]
        purge_ids = {event.get("targetID") for event in purge_events}
        candidate_soaks = []
        for target in target_rows:
            target_id = target["playerID"]
            removal = removals[target_id]
            settle_time = int(removal["timestamp"]) if removal else snapshot_time
            # Each mark has its own seven-yard soak at resolution. The marked
            # player anchors the circle but cannot help soak their own mark.
            participant_ids = set()
            unplaced_ids = set()
            distances = {}
            target_position = _position_sample(position_index, target_id, settle_time)
            living_at_settle = _living_player_ids(players, raw, settle_time)
            if target_position and target_position["reliable"]:
                for player_id in living_at_settle - {target_id}:
                    position = _position_sample(position_index, player_id, settle_time)
                    if position and position["reliable"]:
                        distance = math.hypot(position["x"] - target_position["x"],
                                              position["y"] - target_position["y"])
                        distances[player_id] = distance
                        if distance <= SERPENT_BITE_RADIUS_YARDS * 100:
                            participant_ids.add(player_id)
            for event in raw.get("debuffs") or []:
                player_id = event.get("targetID")
                event_time = int(event.get("timestamp") or 0)
                if (ability_id(event) != INGESTED_VENOM_ID or player_id not in living_at_settle
                        or not cast_time <= event_time <= settle_time + 500
                        or event_type(event) not in {"applydebuff", "applydebuffstack", "refreshdebuff"}):
                    continue
                if player_id == target_id:
                    continue
                participant_position = _position_sample(position_index, player_id, event_time)
                target_position = _position_sample(position_index, target_id, event_time)
                if not participant_position or not target_position or not participant_position["reliable"] or not target_position["reliable"]:
                    unplaced_ids.add(player_id)
                    continue
                if math.hypot(participant_position["x"] - target_position["x"],
                              participant_position["y"] - target_position["y"]) <= SERPENT_BITE_RADIUS_YARDS * 100:
                    participant_ids.add(player_id)
            # The purge is applied just after the soak resolves. A participant
            # may already have moved out by the target aura removal timestamp.
            for player_id in (purge_ids | set(aura_participant_ids)) & living_at_settle - {target_id}:
                if player_id in participant_ids:
                    continue
                for offset in (0, 500, 1000, 1500):
                    sample_time = settle_time - offset
                    player_position = _position_sample(position_index, player_id, sample_time)
                    mark_position = _position_sample(position_index, target_id, sample_time)
                    if not player_position or not mark_position or not player_position["reliable"] or not mark_position["reliable"]:
                        unplaced_ids.add(player_id)
                        continue
                    distance = math.hypot(player_position["x"] - mark_position["x"],
                                          player_position["y"] - mark_position["y"])
                    distances[player_id] = min(distances.get(player_id, float("inf")), distance)
                    if distance <= SERPENT_BITE_RADIUS_YARDS * 100:
                        participant_ids.add(player_id)
                        break
            candidate_soaks.append((target, settle_time, participant_ids, unplaced_ids, distances))

        # When the two circles are apart, one player cannot fill both soaks.
        if len(candidate_soaks) == 2:
            first, second = candidate_soaks
            first_position = _position_sample(position_index, first[0]["playerID"], first[1])
            second_position = _position_sample(position_index, second[0]["playerID"], second[1])
            if (first_position and second_position and first_position["reliable"] and second_position["reliable"]
                    and math.hypot(first_position["x"] - second_position["x"],
                                   first_position["y"] - second_position["y"]) > 2 * SERPENT_BITE_RADIUS_YARDS * 100):
                for player_id in first[2] & second[2]:
                    farther = first if first[4].get(player_id, float("inf")) > second[4].get(player_id, float("inf")) else second
                    farther[2].discard(player_id)

        soak_rows = []
        for target, settle_time, participant_ids, unplaced_ids, _ in candidate_soaks:
            unknown_helpers = unplaced_ids - participant_ids
            soak_purge_ids = participant_ids & purge_ids
            resolution = ("calcified_corpse" if target["resolution"] == "calcified_corpse"
                          else "volatile_purge" if soak_purge_ids else target["resolution"])
            target["resolution"] = resolution
            soak_rows.append({"target": target, "time": fmt_ms(settle_time - fight["startTime"]),
                              "resolution": resolution,
                              "participants": [player_ref(players, actor_map, pid) for pid in sorted(participant_ids)],
                              "purgeRecipients": [player_ref(players, actor_map, pid) for pid in sorted(soak_purge_ids)],
                              "helperCount": len(participant_ids), "minimumHelpers": 5,
                              "enoughHelpers": len(participant_ids) >= 5,
                              "insufficientHelpers": len(participant_ids) + len(unknown_helpers) < 5,
                              "positionUnknown": [player_ref(players, actor_map, pid) for pid in sorted(unknown_helpers)]})
        participants = []
        non_participants = []
        position_unknown = []
        for player_id in sorted(living):
            position = _position_sample(position_index, player_id, snapshot_time)
            ref = player_ref(players, actor_map, player_id)
            nearest_id = None
            distance = None
            if position and position["reliable"] and target_positions:
                distances = [
                    (target_id, math.hypot(position["x"] - target_position["x"], position["y"] - target_position["y"]) / 100)
                    for target_id, target_position in target_positions
                ]
                nearest_id, distance = min(distances, key=lambda item: item[1])
            else:
                position_unknown.append({**ref, "position": position})
            row = {
                **ref,
                "distanceYards": round(distance, 2) if distance is not None else None,
                "nearestTargetID": nearest_id,
                "position": position,
            }
            (participants if player_id in aura_participant_set else non_participants).append(row)
        rounds.append({
            "index": index,
            "time": fmt_ms(cast_time - fight["startTime"]),
            "snapshotTime": fmt_ms(snapshot_time - fight["startTime"]),
            "radiusYards": SERPENT_BITE_RADIUS_YARDS,
            "targets": target_rows,
            "soaks": soak_rows,
            "participants": participants,
            "participantCount": len(participants),
            "nonParticipants": non_participants,
            "nonParticipantCount": len(non_participants),
            "unknownPlayers": position_unknown,
            "positionEvidenceComplete": not position_unknown and bool(target_positions),
            "allPlayersParticipated": not non_participants,
            "participationEvidence": "ingested-venom-aura",
            "auraParticipants": [player_ref(players, actor_map, player_id) for player_id in aura_participant_ids],
        })
    return {
        "spellID": 1295905,
        "targetAuraID": SERPENT_BITE_TARGET_ID,
        "participationAuraID": INGESTED_VENOM_ID,
        "roundCount": len(rounds),
        "rounds": rounds,
    }


def _clock_direction(position, center, boss_position):
    if not position or not center or not boss_position:
        return None
    forward_x = boss_position["x"] - center["x"]
    forward_y = boss_position["y"] - center["y"]
    egg_x = position["x"] - center["x"]
    egg_y = position["y"] - center["y"]
    if math.hypot(forward_x, forward_y) < 1 or math.hypot(egg_x, egg_y) < 1:
        return None
    dot = forward_x * egg_x + forward_y * egg_y
    cross = forward_x * egg_y - forward_y * egg_x
    clockwise = math.atan2(-cross, dot) % (2 * math.pi)
    quarter = int(math.floor(clockwise / (math.pi / 2) + 0.5)) % 4
    return ("12点", "3点", "6点", "9点")[quarter]


def _egg_assignment(clock_direction):
    return {"3点": "近战", "6点": "远程", "9点": "远程"}.get(clock_direction, "未指定")


def _analyze_p3_eggs(fight, actor_map, players, raw, rage_windows):
    mythic = int(fight.get("difficulty") or 0) == 5
    target_game_ids = raw.get("trackedDamageTargetGameIDByActorID") or {}
    spawn_actor_ids = {
        actor_id for actor_id, game_id in target_game_ids.items()
        if int(game_id or 0) == DEVOURERS_SPAWN_GAME_ID
    }
    spawn_events = []
    seen = set()
    for event in sorted(raw.get("casts") or [], key=lambda row: int(row.get("timestamp") or 0)):
        if int(ability_id(event) or 0) != DEVOURERS_SPAWN_SHELL_ID or event_type(event) != "cast":
            continue
        if spawn_actor_ids and event.get("sourceID") not in spawn_actor_ids:
            continue
        identity = (event.get("sourceID"), event.get("sourceInstance"), int(event.get("timestamp") or 0))
        if identity in seen or _phase_at(int(event.get("timestamp") or 0), rage_windows) != "P3":
            continue
        seen.add(identity)
        spawn_events.append(event)

    grouped = []
    for event in spawn_events:
        timestamp = int(event["timestamp"])
        if not grouped or timestamp - grouped[-1]["time"] > 1_500:
            grouped.append({"time": timestamp, "events": []})
        grouped[-1]["events"].append(event)

    egg_damage = [
        event for event in raw.get("trackedDamageTaken") or []
        if int(target_game_ids.get(event.get("targetID")) or 0) == DEVOURERS_SPAWN_GAME_ID
    ]
    pet_owners = raw.get("petOwners") or {}
    shell_removes = [
        event for event in raw.get("enemyBuffs") or []
        if int(ability_id(event) or 0) == DEVOURERS_SPAWN_SHELL_ID
        and event_type(event) == "removebuff"
    ]
    tracked_actor_game_ids = raw.get("trackedActorGameIDByActorID") or {}
    shrieker_actor_ids = {
        actor_id for actor_id, game_id in tracked_actor_game_ids.items()
        if int(game_id or 0) == BLIGHTSCALE_SHRIEKER_GAME_ID
    }
    shrieker_instances = defaultdict(list)
    for event in raw.get("trackedActorEvents") or []:
        if event.get("sourceID") in shrieker_actor_ids and event.get("sourceInstance") is not None:
            shrieker_instances[(event.get("sourceID"), event.get("sourceInstance"))].append(event)
    shriekers = []
    for (source_id, source_instance), events in shrieker_instances.items():
        events.sort(key=lambda row: int(row.get("timestamp") or 0))
        position_event = next(
            (
                event for event in events
                if event_type(event) in {"cast", "begincast"}
                and event.get("x") is not None and event.get("y") is not None
            ),
            None,
        )
        shriekers.append({
            "sourceID": source_id,
            "sourceInstance": source_instance,
            "time": int(events[0]["timestamp"]),
            "position": ({"x": float(position_event["x"]), "y": float(position_event["y"])} if position_event else None),
        })

    complete_group = next((group for group in grouped if len(group["events"]) >= 4), None)
    center = None
    if complete_group:
        points = [event for event in complete_group["events"] if event.get("x") is not None and event.get("y") is not None]
        if points:
            center = {"x": sum(float(row["x"]) for row in points) / len(points), "y": sum(float(row["y"]) for row in points) / len(points)}
    boss_index = _positions(raw, 'bossPositionEvents')
    boss_id = raw.get("bossID")
    rounds = []
    for index, group in enumerate(grouped, start=1):
        timestamp = group["time"]
        boss_state = _position_sample(boss_index, boss_id, timestamp) if boss_id is not None else None
        if center is None:
            points = [event for event in group["events"] if event.get("x") is not None and event.get("y") is not None]
            local_center = ({"x": sum(float(row["x"]) for row in points) / len(points), "y": sum(float(row["y"]) for row in points) / len(points)} if points else None)
        else:
            local_center = center
        round_shriekers = [
            row for row in shriekers
            if 4_000 <= row["time"] - timestamp <= 29_000
        ]
        baseline_shriekers = int(BASELINE_P3_SHRIEKERS.get(index, 0))
        # The four-slot Heroic baseline cannot establish a failed egg on Mythic,
        # where add composition differs. Keep observations without a verdict.
        extra_shrieker_count = 0 if mythic else max(0, len(round_shriekers) - baseline_shriekers)
        eggs = []
        for event in group["events"]:
            instance = event.get("sourceInstance")
            damage_events = [row for row in egg_damage if row.get("targetInstance") == instance]
            by_player = defaultdict(lambda: {"damage": 0, "hitCount": 0})
            for damage_event in damage_events:
                player_id = _owner_player_id(damage_event, players, pet_owners)
                if player_id is None:
                    continue
                by_player[player_id]["damage"] += _amount(damage_event)
                by_player[player_id]["hitCount"] += 1
            damage_by_player = sorted(
                ({**player_ref(players, actor_map, player_id), **values} for player_id, values in by_player.items()),
                key=lambda row: row["damage"],
                reverse=True,
            )
            killed = any(row.get("overkill") is not None for row in damage_events)
            position = ({"x": float(event["x"]), "y": float(event["y"])} if event.get("x") is not None and event.get("y") is not None else None)
            clock = _clock_direction(position, local_center, boss_state)
            removed = next(
                (
                    row for row in shell_removes
                    if row.get("targetID") == event.get("sourceID")
                    and row.get("targetInstance") == instance
                    and int(row.get("timestamp") or 0) >= timestamp
                ),
                None,
            )
            eggs.append({
                "instance": instance,
                "position": position,
                "clockDirection": clock,
                "expectedGroup": _egg_assignment(clock),
                "killed": killed,
                "removedTime": fmt_ms(int(removed["timestamp"]) - fight["startTime"]) if removed else None,
                "totalDamage": sum(row["damage"] for row in damage_by_player),
                "damageByPlayer": damage_by_player,
            })
        # An unfinished log can contain living eggs that never had time to hatch.
        # Only extra Shriekers above the fixed per-round baseline confirm a failed egg.
        unkilled_observed = [row for row in eggs if not row["killed"]]
        failed_observed = unkilled_observed[:extra_shrieker_count]
        for row in failed_observed:
            row["confirmedByExtraShrieker"] = True
        used_directions = {row["clockDirection"] for row in eggs if row.get("clockDirection")}
        missing_directions = [direction for direction in ("12点", "3点", "6点", "9点") if direction not in used_directions]
        synthetic_count = max(0, extra_shrieker_count - len(failed_observed))
        failed_eggs = list(failed_observed)
        for offset in range(synthetic_count):
            clock = missing_directions[offset] if offset < len(missing_directions) else None
            failed_eggs.append({
                "instance": None,
                "position": round_shriekers[baseline_shriekers + len(failed_observed) + offset].get("position"),
                "clockDirection": clock,
                "expectedGroup": _egg_assignment(clock),
                "killed": False,
                "confirmedByExtraShrieker": True,
                "totalDamage": 0,
                "damageByPlayer": [],
            })
        rounds.append({
            "index": index,
            "time": fmt_ms(timestamp - fight["startTime"]),
            "expectedEggCount": None if mythic else 4,
            "expectedKillableEggCount": None if mythic else max(0, 4 - baseline_shriekers),
            "observedEggCount": len(eggs),
            "baselineShriekerCount": None if mythic else baseline_shriekers,
            "adjudicationAvailable": not mythic,
            "shriekerCount": len(round_shriekers),
            "extraShriekerCount": extra_shrieker_count,
            "failedEggCount": len(failed_eggs),
            "eggs": eggs,
            "failedEggs": failed_eggs,
        })
    return {
        "eggGameID": DEVOURERS_SPAWN_GAME_ID,
        "shriekerGameID": BLIGHTSCALE_SHRIEKER_GAME_ID,
        "expectedEggsPerRound": None if mythic else 4,
        "adjudicationAvailable": not mythic,
        "roundCount": len(rounds),
        "failedEggCount": sum(row["failedEggCount"] for row in rounds),
        "rounds": rounds,
    }


def _burst_potion_intervals(fight, raw):
    """Use aura lifetimes, never cast timestamps or a fixed pre-window grace."""
    active, seen, intervals = {}, set(), []
    events = list(raw.get("friendlyBuffs") or []) + [e for e in raw.get("deaths", []) if event_type(e) == "death"]

    def close(key, end, open_ended=False):
        begin, unknown_start = active.pop(key)
        end = min([end] + [int(e["timestamp"]) for e in raw.get("deaths", [])
                           if event_type(e) == "death" and e.get("targetID") == key[0]
                           and begin <= int(e["timestamp"]) < end])
        if end > begin:
            intervals.append({"playerID": key[0], "spellID": key[1], "start": begin, "end": end,
                              "unknownStart": unknown_start, "openEnded": open_ended})

    for e in sorted(events, key=lambda e: int(e.get("timestamp") or 0)):
        ts, pid, kind = int(e.get("timestamp") or 0), e.get("targetID"), event_type(e)
        if ts > fight["endTime"]:
            continue
        if kind == "death":
            for key in list(active):
                if key[0] == pid:
                    close(key, ts)
            continue
        sid = int(ability_id(e) or 0)
        if sid not in BURST_POTIONS:
            continue
        key = (pid, sid)
        if kind in {"applybuff", "refreshbuff"}:
            active.setdefault(key, (ts, False))
            seen.add(key)
        elif kind == "removebuff":
            # An initial removal proves an aura carried into the recorded fight.
            if key not in seen:
                active[key] = (int(fight["startTime"]), True)
            if key in active:
                close(key, ts)
            seen.add(key)
    for key in list(active):
        close(key, int(fight["endTime"]), True)
    return intervals


def _rage_potions(fight, actor_map, players, raw, window, intervals):
    start, end = window["start"], window["end"]
    living = _living_player_ids(players, raw, start)
    rows = []
    for pid, p in players.items():
        role = str(p.get("role") or "")
        if not (role.endswith("tank") or role.endswith("dps")):
            continue
        effects, spans = [], []
        for aura in intervals:
            left, right = max(start, aura["start"]), min(end, aura["end"])
            if aura["playerID"] != pid or right <= left:
                continue
            spans.append((left, right))
            effects.append({"spellID": aura["spellID"], "spell": BURST_POTIONS[aura["spellID"]],
                            "startTime": None if aura["unknownStart"] else fmt_ms(aura["start"] - fight["startTime"]),
                            "endTime": fmt_ms(aura["end"] - fight["startTime"]),
                            "openEnded": aura["openEnded"], "unknownStart": aura["unknownStart"],
                            "overlapStart": fmt_ms(left - fight["startTime"]), "overlapEnd": fmt_ms(right - fight["startTime"]),
                            "overlapMs": right - left})
        merged = []
        for left, right in sorted(spans):
            if merged and left <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], right)
            else:
                merged.append([left, right])
        overlap_ms = sum(right - left for left, right in merged)
        available = raw.get("friendlyBuffs") is not None
        rows.append({**player_ref(players, actor_map, pid), "potionUsed": bool(effects) if available else None,
                     "aliveAtStart": pid in living, "coverageMs": overlap_ms,
                     "coveragePercent": round(100 * overlap_ms / (end - start), 1) if end > start else 0,
                     "effects": effects})
    rows.sort(key=lambda row: (row["potionUsed"] is True, row["playerID"]))
    return {"players": rows, "playerCount": len(rows), "usedCount": sum(r["potionUsed"] is True for r in rows),
            "missingCount": sum(r["potionUsed"] is False for r in rows),
            "unknownCount": sum(r["potionUsed"] is None for r in rows),
            "evidenceNote": "检查所有坦克和输出，包括零伤害及已死亡玩家；药水光环与易伤窗口有实际重叠即算已吃药，提前激活也计入。只统计爆发药水，不计治疗药水。覆盖时长按光环生效区间计算，死亡时截止。"}


def _analyze_rage(fight, actor_map, players, raw, rage_windows):
    rounds = []
    potion_intervals = _burst_potion_intervals(fight, raw)
    target_game_ids = raw.get("trackedDamageTargetGameIDByActorID") or {}
    for index, window in enumerate(rage_windows, start=1):
        start, end = window["start"], window["end"]
        window_damage = [
            event for event in raw.get("trackedDamageTaken") or []
            if start <= int(event.get("timestamp") or 0) <= end
            and (
                not target_game_ids
                or int(target_game_ids.get(event.get("targetID")) or 0) in {ULATEK_GAME_ID, HEART_GAME_ID}
            )
        ]
        boss_id = window.get("playerID")
        boss_damage = [
            event for event in window_damage
            if int(target_game_ids.get(event.get("targetID")) or 0) == ULATEK_GAME_ID
            or (not target_game_ids and event.get("targetID") == boss_id)
        ]
        heart_damage = [
            event for event in window_damage
            if int(target_game_ids.get(event.get("targetID")) or 0) == HEART_GAME_ID
            or (not target_game_ids and event.get("targetID") != boss_id)
        ]
        by_player = defaultdict(lambda: {
            "heartDamage": 0,
            "bossDamage": 0,
            "heartHits": 0,
            "bossHits": 0,
        })
        pet_owners = raw.get("petOwners") or {}

        for event in heart_damage:
            player_id = _owner_player_id(event, players, pet_owners)
            if player_id is None:
                continue
            by_player[player_id]["heartDamage"] += _amount(event)
            by_player[player_id]["heartHits"] += 1
        for event in boss_damage:
            player_id = _owner_player_id(event, players, pet_owners)
            if player_id is None:
                continue
            by_player[player_id]["bossDamage"] += _amount(event)
            by_player[player_id]["bossHits"] += 1
        damage_by_player = []
        for player_id, values in by_player.items():
            total_damage = values["heartDamage"] + values["bossDamage"]
            damage_by_player.append({
                **player_ref(players, actor_map, player_id),
                **values,
                "totalDamage": total_damage,
                "damage": total_damage,
                "hitCount": values["heartHits"] + values["bossHits"],
            })
        damage_by_player.sort(key=lambda row: row["totalDamage"], reverse=True)
        debris = [
            event for event in raw["damage"]
            if int(ability_id(event) or 0) == 1286885
            and event.get("targetID") in players
            and start <= int(event.get("timestamp") or 0) <= end
        ]
        deaths = [
            event for event in raw["deaths"]
            if start <= int(event.get("timestamp") or 0) <= end
        ]
        rounds.append({
            "index": index,
            "time": fmt_ms(start - fight["startTime"]),
            "endTime": fmt_ms(end - fight["startTime"]),
            "durationSec": round((end - start) / 1000, 2),
            "potions": _rage_potions(fight, actor_map, players, raw, window, potion_intervals),
            "heartDamage": sum(_amount(event) for event in heart_damage),
            "bossDamage": sum(_amount(event) for event in boss_damage),
            "totalDamage": sum(_amount(event) for event in window_damage),
            "damageByPlayer": damage_by_player,
            "heartDamageByPlayer": sorted(
                [
                    {
                        **row,
                        "damage": row["heartDamage"],
                        "hitCount": row["heartHits"],
                    }
                    for row in damage_by_player
                    if row["heartDamage"] > 0
                ],
                key=lambda row: row["damage"],
                reverse=True,
            ),
            "fallingDebrisHitCount": len(debris),
            "fallingDebrisDamage": sum(_amount(event) for event in debris),
            "fallingDebrisHits": [
                {
                    **player_ref(players, actor_map, event.get("targetID")),
                    "time": fmt_ms(int(event["timestamp"]) - fight["startTime"]),
                    "amount": _amount(event),
                }
                for event in debris
            ],
            "deathCount": len(deaths),
            "deaths": [
                {
                    **player_ref(players, actor_map, event.get("targetID")),
                    "time": fmt_ms(int(event["timestamp"]) - fight["startTime"]),
                    "abilityID": int(event.get("killingAbilityGameID") or ability_id(event) or 0),
                    "ability": spell_name(
                        int(event.get("killingAbilityGameID") or ability_id(event) or 0),
                        GUIDE_SPELLS,
                    ),
                }
                for event in deaths
            ],
        })
    return {
        "rounds": rounds,
        "totalDeathCount": sum(row["deathCount"] for row in rounds),
        "totalHeartDamage": sum(row["heartDamage"] for row in rounds),
        "totalBossDamage": sum(row["bossDamage"] for row in rounds),
        "totalDamage": sum(row["totalDamage"] for row in rounds),
    }


def _analyze_fangs(fight, actor_map, players, raw, safe_stacks=3):
    applies = [
        event for event in raw["debuffs"]
        if int(ability_id(event) or 0) == FANG_AURA_ID
        and event.get("targetID") in players
        and event_type(event) == "applydebuff"
    ]
    removes = [
        event for event in raw["debuffs"]
        if int(ability_id(event) or 0) == FANG_AURA_ID
        and event.get("targetID") in players
        and event_type(event) == "removedebuff"
    ]
    if not applies:
        return {"safeStacks": safe_stacks, "rounds": [], "wrongBreakCount": 0, "maxBlightStack": 0}

    start = min(int(event["timestamp"]) for event in applies)
    targets = {}
    for event in sorted(applies, key=lambda row: int(row["timestamp"])):
        targets.setdefault(event.get("targetID"), int(event["timestamp"]))

    apply_groups = []
    for event in sorted(applies, key=lambda row: int(row["timestamp"])):
        timestamp = int(event["timestamp"])
        if not apply_groups or timestamp - apply_groups[-1]["timestamp"] > 250:
            apply_groups.append({"timestamp": timestamp, "events": []})
        apply_groups[-1]["events"].append(event)
    warden_casts = sorted(completed_casts(raw.get("casts") or [], 1301117), key=lambda row: int(row["timestamp"]))
    boss_position_index = _positions(raw, 'bossPositionEvents')
    boss_id = raw.get("bossID")
    boss_position_rows = boss_position_index.get(boss_id) or []
    boss_spawn = boss_position_rows[0] if boss_position_rows else None
    boss_boundary_x = float(boss_spawn["x"]) if boss_spawn else None
    position_index = _positions(raw, 'replayEvents' if raw.get('replayEvents') else 'resources')
    cast_positions = [float(row["x"]) for row in warden_casts if row.get("x") is not None]
    def side_from_x(x):
        return "左场" if float(x) < (boss_boundary_x if boss_boundary_x is not None else 0) else "右场"
    side_groups = []
    for index, group in enumerate(apply_groups):
        nearby_casts = [row for row in warden_casts
                        if abs(int(row.get("timestamp") or 0) - group["timestamp"]) <= 500]
        cast = min(nearby_casts,
                   key=lambda row: abs(int(row["timestamp"]) - group["timestamp"]), default=None)
        if cast and cast.get("x") is not None and boss_boundary_x is not None:
            fallback_side, fallback_source = side_from_x(cast["x"]), "boss-initial-boundary"
        elif cast and cast.get("x") is not None and len(cast_positions) >= 2:
            fallback_side = "左场" if float(cast["x"]) == min(cast_positions) else "右场"
            fallback_source = "warden-relative-fallback"
        else:
            fallback_side = "先施加场" if index == 0 else ("后施加场" if index == 1 else f"第 {index + 1} 场")
            fallback_source = "application-order-fallback"
        buckets = {}
        for event in group["events"]:
            position = actor_position(event, "target")
            if position is None:
                sample = _position_sample(position_index, event.get("targetID"), group["timestamp"])
                # A late position sample still identifies the half when it is
                # well inside that platform; keep the cast fallback near mid.
                position = sample if sample and (sample["reliable"] or
                    abs(float(sample["x"]) - (boss_boundary_x or 0)) > 3_500) else None
            side = side_from_x(position["x"]) if position else fallback_side
            bucket = buckets.setdefault(side, {"timestamp": group["timestamp"], "events": [],
                                              "side": side, "positionSources": set()})
            bucket["events"].append(event)
            bucket["positionSources"].add("player-application-position" if position else fallback_source)
        for bucket in buckets.values():
            side_cast = min((row for row in nearby_casts if row.get("x") is not None
                             and side_from_x(row["x"]) == bucket["side"]),
                            key=lambda row: abs(int(row["timestamp"]) - group["timestamp"]), default=None)
            if side_cast is None and cast and bucket["side"] == fallback_side:
                side_cast = cast
            sources = bucket.pop("positionSources")
            bucket["sideSource"] = next(iter(sources)) if len(sources) == 1 else "mixed-position-evidence"
            bucket["wardenInstance"] = side_cast.get("sourceInstance") if side_cast else None
            bucket["positionX"] = float(side_cast["x"]) if side_cast and side_cast.get("x") is not None else None
            side_groups.append(bucket)
    apply_groups = sorted(side_groups, key=lambda group: (group["timestamp"], group["side"]))
    side_by_player = {
        event.get("targetID"): group["side"]
        for group in apply_groups
        for event in group["events"]
    }

    stack_changes = _raid_aura_changes(raw["debuffs"], BLIGHT_VEIN_ID)
    break_events = sorted(
        (row for row in removes if row.get("targetID") in targets),
        key=lambda row: int(row["timestamp"]),
    )
    assigned = defaultdict(list)
    unresolved_events = []
    for event in break_events:
        timestamp = int(event["timestamp"])
        change = min(
            (row for row in stack_changes if 0 <= row["timestamp"] - timestamp <= 500),
            key=lambda row: row["timestamp"] - timestamp,
            default=None,
        )
        if change:
            assigned[change["timestamp"]].append((event, change))
        else:
            unresolved_events.append(event)

    breaks = []
    for change_timestamp in sorted(assigned):
        group = assigned[change_timestamp]
        to_stack = int(group[0][1]["toStack"])
        from_stack = max(0, to_stack - len(group))
        for offset, (event, change) in enumerate(group):
            timestamp = int(event["timestamp"])
            row_from = from_stack + offset
            row_to = row_from + 1
            breaks.append({
                **player_ref(players, actor_map, event.get("targetID")),
                "time": fmt_ms(timestamp - fight["startTime"]),
                "heldSec": round((timestamp - targets[event.get("targetID")]) / 1000, 2),
                "fromStack": row_from,
                "toStack": row_to,
                "blightStack": row_to,
                "stackEvidenceTime": fmt_ms(change["timestamp"] - fight["startTime"]),
                "absoluteTime": timestamp,
                "side": side_by_player.get(event.get("targetID")),
            })
    for event in unresolved_events:
        timestamp = int(event["timestamp"])
        breaks.append({
            **player_ref(players, actor_map, event.get("targetID")),
            "time": fmt_ms(timestamp - fight["startTime"]),
            "heldSec": round((timestamp - targets[event.get("targetID")]) / 1000, 2),
            "fromStack": None,
            "toStack": None,
            "blightStack": 0,
            "stackEvidenceTime": None,
            "absoluteTime": timestamp,
            "side": side_by_player.get(event.get("targetID")),
            "evidenceMissing": True,
        })
    breaks.sort(key=lambda row: (row["absoluteTime"], row["player"]))

    active_blight = set()
    clear_times = []
    for event in sorted(
        (
            row for row in raw.get("debuffs") or []
            if int(ability_id(row) or 0) == BLIGHT_VEIN_ID
        ),
        key=lambda row: int(row.get("timestamp") or 0),
    ):
        kind = event_type(event)
        player_id = event.get("targetID")
        if kind == "applydebuff":
            active_blight.add(player_id)
        elif kind == "removedebuff" and player_id in active_blight:
            active_blight.discard(player_id)
            if not active_blight:
                clear_times.append(int(event.get("timestamp") or 0))

    # Keep the assignment-side evidence in the single-fight report, but use only
    # the observed raidwide stack transition to judge each tether removal.
    for row in breaks:
        stack = row["toStack"]
        row["safeStacks"] = safe_stacks
        row["wrong"] = stack is not None and stack > safe_stacks
        row["violationReasons"] = [f"拉断后凋萎静脉 {stack} 层，超过安全层数 {safe_stacks}"] if row["wrong"] else []
        row["adjudication"] = "over_safe_stacks" if row["wrong"] else ("missing_stack_evidence" if stack is None else "correct")

    unresolved = [
        player_ref(players, actor_map, player_id)
        for player_id in targets
        if not any(row["playerID"] == player_id for row in breaks)
    ]
    wrong_players = [row for row in breaks if row["wrong"]]
    rounds = [{
        "index": 1,
        "time": fmt_ms(start - fight["startTime"]),
        "targetCount": len(targets),
        "targets": [player_ref(players, actor_map, player_id) for player_id in targets],
        "sides": [
            {
                "side": group["side"],
                "applyTime": fmt_ms(group["timestamp"] - fight["startTime"]),
                "wardenInstance": group["wardenInstance"],
                "positionX": group["positionX"],
                "sideSource": group["sideSource"],
                "targets": [player_ref(players, actor_map, event.get("targetID")) for event in group["events"]],
            }
            for group in apply_groups
        ],
        "blightClearTimes": [fmt_ms(timestamp - fight["startTime"]) for timestamp in clear_times],
        "safeStacks": safe_stacks,
        "breaks": breaks,
        "unresolved": unresolved,
        "violationPlayers": wrong_players,
        "overLimitPlayers": wrong_players,
        "firstViolation": wrong_players[0] if wrong_players else None,
        "bossInitialPosition": ({
            "x": boss_boundary_x,
            "y": float(boss_spawn["y"]),
            "time": fmt_ms(int(boss_spawn["timestamp"]) - fight["startTime"]),
        } if boss_spawn else None),
        "maxBlightStack": max((row["toStack"] or 0 for row in breaks), default=0),
        "wrongBreakCount": len(wrong_players),
    }]
    return {
        "safeStacks": safe_stacks,
        "rounds": rounds,
        "wrongBreakCount": sum(row["wrongBreakCount"] for row in rounds),
        "maxBlightStack": max((row["maxBlightStack"] for row in rounds), default=0),
    }


def _analyze_mythic_wretch(fight, actor_map, players, raw):
    if int(fight.get("difficulty") or 0) != 5:
        return {}
    begins = sorted((event for event in raw.get("casts") or []
                     if int(ability_id(event) or 0) == 1310763
                     and event_type(event) == "begincast"),
                    key=lambda event: int(event.get("timestamp") or 0))
    completes = completed_casts(raw.get("casts") or [], 1310763)
    position_index = _positions(raw)
    rounds = []
    for begin in begins:
        start = int(begin["timestamp"])
        complete = next((event for event in completes
                         if event.get("sourceID") == begin.get("sourceID")
                         and start <= int(event["timestamp"]) <= start + 10_000), None)
        finish = int(complete["timestamp"]) if complete else None
        hits = [event for event in raw.get("damage") or []
                if finish is not None and int(ability_id(event) or 0) == 1310763
                and event.get("targetID") in players
                and finish - 250 <= int(event.get("timestamp") or 0) <= finish + 100
                and _amount(event) > 0]
        direct_hits = {}
        for event in hits:
            pid = event["targetID"]
            if pid not in direct_hits:
                direct_hits[pid] = {**player_ref(players, actor_map, pid), "amount": 0}
            direct_hits[pid]["amount"] += _amount(event)
        inside, outside, unknown = [], [], []
        if finish is not None:
            for player_id in sorted(_living_player_ids(players, raw, finish)):
                ref = player_ref(players, actor_map, player_id)
                position = _position_sample(position_index, player_id, finish)
                if not position or not position["reliable"] or complete.get("x") is None or complete.get("y") is None:
                    unknown.append(ref)
                    continue
                distance = math.hypot(position["x"] - float(complete["x"]),
                                      position["y"] - float(complete["y"])) / 100
                row = {**ref, "distanceYards": round(distance, 1)}
                death = next((event for event in raw.get("deaths") or []
                              if event.get("targetID") == player_id
                              and finish <= int(event.get("timestamp") or 0) <= finish + 12_000), None)
                if death:
                    row["deathTime"] = fmt_ms(int(death["timestamp"]) - fight["startTime"])
                    row["deathAbilityID"] = int(death.get("killingAbilityGameID") or ability_id(death) or 0)
                if player_id in direct_hits:
                    (outside if distance > 10 else inside).append(row)
        rounds.append({
            "time": fmt_ms(start - fight["startTime"]),
            "castCompleted": complete is not None,
            "completionTime": fmt_ms(finish - fight["startTime"]) if finish is not None else None,
            "hitCount": len(direct_hits),
            "hits": list(direct_hits.values()),
            "inside": inside,
            "outside": outside,
            "positionUnknown": unknown,
        })
    return {"spellID": 1310763, "rounds": rounds, "castCount": len(rounds),
            "completedCount": sum(row["castCompleted"] for row in rounds),
            "positionVerdictAvailable": any(row["inside"] or row["outside"] for row in rounds)}


def _analyze_malice(fight, actor_map, raw):
    begins = [
        event for event in raw["casts"]
        if int(ability_id(event) or 0) == 1290779 and event_type(event) == "begincast"
    ]
    completes = completed_casts(raw["casts"], 1290779)
    rows = []
    for event in begins:
        timestamp = int(event["timestamp"])
        completed = next(
            (
                row for row in completes
                if row.get("sourceID") == event.get("sourceID")
                and timestamp <= int(row.get("timestamp") or 0) <= timestamp + 8000
            ),
            None,
        )
        rows.append({
            "time": fmt_ms(timestamp - fight["startTime"]),
            "source": source_name(actor_map, event.get("sourceID"), SOURCE_NAMES) or "厄鳞守卫",
            "completed": bool(completed),
            "prevented": not completed,
        })
    return {
        "spellID": 1290779,
        "castCount": len(begins),
        "preventedCount": sum(row["prevented"] for row in rows),
        "completedCount": sum(row["completed"] for row in rows),
        "casts": rows,
    }


def _death_row(fight, actor_map, players, raw, event):
    timestamp = int(event.get("timestamp") or 0)
    player_id = event.get("targetID")
    defensive = find_defensive_uses_before_death(
        raw["friendlyCasts"],
        death_timestamp=timestamp,
        player_id=player_id,
        lookback_ms=15_000,
    )
    consumables = []
    for cast in raw["friendlyCasts"]:
        spell_id = int(ability_id(cast) or 0)
        cast_time = int(cast.get("timestamp") or 0)
        if cast.get("sourceID") != player_id or not timestamp - 20_000 <= cast_time <= timestamp:
            continue
        if spell_id in HEALTHSTONE_IDS:
            kind, name = "healthstone", "治疗石"
        elif spell_id in HEALING_POTION_IDS:
            kind, name = "healing_potion", spell_name(spell_id, GUIDE_SPELLS)
            if name == "未知技能":
                name = "生命治疗药水"
        else:
            continue
        consumables.append({
            "kind": kind,
            "spellID": spell_id,
            "spellName": name,
            "time": fmt_ms(cast_time - fight["startTime"]),
            "msBeforeDeath": timestamp - cast_time,
        })
    ability_id_value = int(event.get("killingAbilityGameID") or ability_id(event) or 0)
    personal = defensive.get("personalDefensives") or []
    return {
        **player_ref(players, actor_map, player_id),
        "time": fmt_ms(timestamp - fight["startTime"]),
        "abilityID": ability_id_value,
        "ability": spell_name(ability_id_value, GUIDE_SPELLS),
        "usedPersonalDefensive": bool(personal),
        "personalDefensiveWindowMs": 15_000,
        "personalDefensiveCriterion": "death-preceding-cast-record",
        "personalDefensives": personal,
        "usedHealthstone": any(row["kind"] == "healthstone" for row in consumables),
        "usedHealingPotion": any(row["kind"] == "healing_potion" for row in consumables),
        "consumables": consumables,
    }


def _critical_melee(fight, actor_map, players, raw):
    melee_by_player = defaultdict(list)
    for event in raw["damage"]:
        player_id = event.get("targetID")
        if int(ability_id(event) or 0) != 1 or player_id not in players:
            continue
        if players[player_id].get("role") == "tank":
            continue
        # Misses, dodges and immunes can still arrive as damage-table rows. The
        # requested metric is players actually hit by melee, so require damage.
        if _amount(event) <= 0:
            continue
        melee_by_player[player_id].append(event)
    melee_players = []
    for player_id, events in melee_by_player.items():
        sources = Counter(source_name(actor_map, event.get("sourceID"), SOURCE_NAMES) for event in events)
        melee_players.append({
            **player_ref(players, actor_map, player_id),
            "hitCount": len(events),
            "totalDamage": sum(_amount(event) for event in events),
            "sources": [{"source": name, "count": count} for name, count in sources.most_common()],
            "events": [
                {
                    "time": fmt_ms(int(event["timestamp"]) - fight["startTime"]),
                    "amount": _amount(event),
                    "source": source_name(actor_map, event.get("sourceID"), SOURCE_NAMES),
                }
                for event in events
            ],
        })
    melee_players.sort(key=lambda row: (row["totalDamage"], row["hitCount"]), reverse=True)

    return {"hitCount": sum(r["hitCount"] for r in melee_players), "totalDamage": sum(r["totalDamage"] for r in melee_players), "players": melee_players}


def _critical_wrath(fight, actor_map, players, raw):
    wrath_casts = sorted(completed_casts(raw["casts"], 1298367), key=lambda row: int(row["timestamp"]))
    wrath_damage = [
        event for event in raw["damage"]
        if int(ability_id(event) or 0) in {1298369, 1301122}
        and event.get("targetID") in players
        and _amount(event) > 0
    ]
    mother_wrath_failures = []
    for index, event in enumerate(wrath_casts, start=1):
        timestamp = int(event["timestamp"])
        next_timestamp = int(wrath_casts[index]["timestamp"]) if index < len(wrath_casts) else fight["endTime"]
        window_end = min(timestamp + 12_000, next_timestamp)
        damage_events = [
            row for row in wrath_damage
            if timestamp - 250 <= int(row.get("timestamp") or 0) < window_end
        ]
        affected_ids = sorted({row.get("targetID") for row in damage_events if row.get("targetID") in players})

        # 正常处理是同一名坦克连续承受多跳；圈内无人时才会扩散至全团。
        # 使用“至少 3 名不同玩家”作为扩散证据，避免把坦克的 9 连击误判为 A 团。
        if len(affected_ids) < 3:
            continue

        receiver_id = event.get("targetID") if event.get("targetID") in players else None
        receiver_evidence = "蛇母之怒施法目标" if receiver_id is not None else None
        evidence_delta_ms = 0 if receiver_id is not None else None
        if receiver_id is None:
            source_id = event.get("sourceID")
            recent_melee = max(
                (
                    row for row in raw["damage"]
                    if int(ability_id(row) or 0) == 1
                    and row.get("targetID") in players
                    and row.get("sourceID") == source_id
                    and timestamp - 8_000 <= int(row.get("timestamp") or 0) <= timestamp
                ),
                key=lambda row: int(row.get("timestamp") or 0),
                default=None,
            )
            if recent_melee is not None:
                receiver_id = recent_melee.get("targetID")
                receiver_evidence = "施法前 Boss 最近一次近战目标"
                evidence_delta_ms = timestamp - int(recent_melee.get("timestamp") or 0)

        first_damage_time = min(int(row.get("timestamp") or timestamp) for row in damage_events)
        mother_wrath_failures.append({
            "index": index,
            "time": fmt_ms(timestamp - fight["startTime"]),
            "damageTime": fmt_ms(first_damage_time - fight["startTime"]),
            "spellID": 1298367,
            "receiver": player_ref(players, actor_map, receiver_id) if receiver_id is not None else None,
            "receiverEvidence": receiver_evidence or "未取得施法目标或近期近战目标",
            "evidenceDeltaMs": evidence_delta_ms,
            "affectedCount": len(affected_ids),
            "affectedPlayers": [player_ref(players, actor_map, player_id) for player_id in affected_ids],
            "hitCount": len(damage_events),
            "totalDamage": sum(_amount(row) for row in damage_events),
            "damageSpellIDs": sorted({int(ability_id(row) or 0) for row in damage_events}),
        })

    return {"castCount": len(wrath_casts), "raidWideFailureCount": len(mother_wrath_failures), "raidWideTargetThreshold": 3, "failures": mother_wrath_failures}


def _critical_platform(fight, actor_map, players, raw):
    shatters = completed_casts(raw["casts"], 1315341)
    bites = completed_casts(raw["casts"], 1295905)
    transitions = []
    previous_end = 0
    for index, shatter in enumerate(sorted(shatters, key=lambda row: int(row["timestamp"])), start=1):
        shatter_time = int(shatter["timestamp"])
        bite = max(
            (
                row for row in bites
                if previous_end < int(row.get("timestamp") or 0) <= shatter_time
            ),
            key=lambda row: int(row.get("timestamp") or 0),
            default=None,
        )
        start = int(bite["timestamp"]) if bite else shatter_time - 30_000
        end = shatter_time + 3000
        deaths = [
            _death_row(fight, actor_map, players, raw, event)
            for event in raw["deaths"]
            if start <= int(event.get("timestamp") or 0) <= end
        ]
        transitions.append({
            "index": index,
            "label": f"第 {index} 次碎场流程",
            "startTime": fmt_ms(start - fight["startTime"]),
            "endTime": fmt_ms(end - fight["startTime"]),
            "shatterTime": fmt_ms(shatter_time - fight["startTime"]),
            "deathCount": len(deaths),
            "deaths": deaths,
        })
        previous_end = shatter_time
    focus = transitions[1] if len(transitions) >= 2 else None
    return {"platformTransitions": transitions, "platform2To3": focus}


def _critical_prey(fight, actor_map, players, raw):
    coiled_prey_deaths = [
        _death_row(fight, actor_map, players, raw, event)
        for event in raw.get("deaths") or []
        if int(event.get("killingAbilityGameID") or ability_id(event) or 0) == 1301510
    ]
    return {"spellID": 1301510, "deathCount": len(coiled_prey_deaths), "deaths": coiled_prey_deaths}


def _analyze_critical(fight, actor_map, players, raw):
    options = resolve_analysis_options(CONFIG_SCHEMA, raw.get("analysisOptions") or {})
    functions = {"maliceReviewEnabled": lambda: _analyze_malice(fight, actor_map, raw),
                 "meleeReviewEnabled": lambda: _critical_melee(fight, actor_map, players, raw),
                 "motherWrathReviewEnabled": lambda: _critical_wrath(fight, actor_map, players, raw),
                 "serpentBitesReviewEnabled": lambda: _analyze_serpent_bites(fight, actor_map, players, raw),
                 "p25EggsReviewEnabled": lambda: _analyze_p25_eggs(fight, actor_map, players, raw),
                 "coiledPreyReviewEnabled": lambda: _critical_prey(fight, actor_map, players, raw)}
    result = {"enabledItems": {name: _critical_enabled(options, key) for key, (name, _) in CRITICAL_FIELDS.items()}}
    for key, fn in functions.items():
        if _critical_enabled(options, key):
            result[CRITICAL_FIELDS[key][0]] = fn()
    if _critical_enabled(options, "platformReviewEnabled"):
        result.update(_critical_platform(fight, actor_map, players, raw))
    return result


def _nightly_collapse(fight, players, raw, threshold=8):
    changes = [e for e in raw.get("deaths", []) if event_type(e) == "death"]
    changes += [e for e in raw.get("friendlyCasts", []) + raw.get("trackedActorEvents", []) if event_type(e) == "resurrect"]
    dead = set()
    for e in sorted(changes, key=lambda e: int(e["timestamp"])):
        pid = e.get("targetID")
        if pid not in players:
            continue
        if event_type(e) == "death":
            dead.add(pid)
        else:
            dead.discard(pid)
        if len(dead) >= threshold:
            return int(e["timestamp"])
    return None


# RaidPlan's orthographic map metadata supplies the world center, yaw and
# vertical span. WCL replay axes are (-worldY, worldX), in hundredths of yards.
REPLAY_MAPS = {
    'platform': {'image': '/assets/raids/venomous_abyss/08-ulatek-platform.jpg',
                 'width': 2123, 'height': 1188, 'centerX': 0, 'centerY': 155367,
                 'yaw': -0.215, 'yards': 85},
    'broken': {'image': '/assets/raids/venomous_abyss/08-ulatek-platform-broken.jpg',
               'width': 2123, 'height': 1188, 'centerX': 0, 'centerY': 155367,
               'yaw': -0.215, 'yards': 85},
    'left': {'image': '/assets/raids/venomous_abyss/08-ulatek-left.jpg',
             'width': 2448, 'height': 1371, 'centerX': -9233, 'centerY': 155367.1,
             'yaw': 90, 'yards': 140},
    'right': {'image': '/assets/raids/venomous_abyss/08-ulatek-right.jpg',
              'width': 2448, 'height': 1371, 'centerX': 9233, 'centerY': 155367,
              'yaw': -90, 'yards': 140},
}


def _coil_region_position(slot, arena):
    """Enlarge the diagram's circle by moving its center inward, retaining clearance."""
    image_x, image_y = COIL_REGION_IMAGE_CENTERS[slot]
    scale = arena['height'] / arena['yards']
    px, py = (image_x-.5)*arena['width']/scale, (image_y-.5)*arena['height']/scale
    distance = math.hypot(px, py)
    inward = (-px/distance, -py/distance)
    boundary = [((x-.5)*arena['width']/scale, (y-.5)*arena['height']/scale)
                for x, y in COIL_PLATFORM_IMAGE_BOUNDARY]
    edges = []
    for i, a in enumerate(boundary):
        b = boundary[(i+1) % len(boundary)]
        dx, dy = b[0]-a[0], b[1]-a[1]
        length = math.hypot(dx, dy)
        normal = (-dy/length, dx/length)
        clearance = (px-a[0])*normal[0]+(py-a[1])*normal[1]
        approach = inward[0]*normal[0]+inward[1]*normal[1]
        edges.append((clearance, approach))
    target = min(d for d, _ in edges)+COIL_SOAK_RADIUS_YARDS-COIL_DIAGRAM_RADIUS_YARDS
    shift = max([0]+[(target-d)/approach for d, approach in edges if approach > 0])
    px, py = px+inward[0]*shift, py+inward[1]*shift
    yaw = math.radians(arena['yaw'])
    return {'x':arena['centerX']+(px*math.cos(yaw)+py*math.sin(yaw))*100,
            'y':arena['centerY']-(-px*math.sin(yaw)+py*math.cos(yaw))*100}


def _replay_coil_soaks(fight, raw):
    """Identify one of eight fixed regions from the Spectral Coil's corner."""
    start = int(fight['startTime'])
    casts = sorted(raw.get('casts') or [], key=lambda e:int(e['timestamp']))
    source_ids = {a['id'] for a in raw.get('actorRows') or [] if a.get('gameID') == SPECTRAL_COIL_GAME_ID}
    center = REPLAY_MAPS['platform']
    result = []
    for e in casts:
        if event_type(e) != 'cast' or ability_id(e) != P25_COIL_CAST_ID:
            continue
        # The actor position is the tail base at a corner, not the impact center.
        origin = actor_position(e,'source')
        if not origin or source_ids and e.get('sourceID') not in source_ids:
            continue
        dx,dy = origin['x']-center['centerX'],origin['y']-center['centerY']
        if math.hypot(dx,dy) < 1000:
            continue
        angle = math.atan2(dy,dx)
        slot = round((angle-math.pi/8)/(math.pi/4)) % 8
        position = _coil_region_position(slot, center)
        ts = int(e['timestamp'])
        begins = [int(b['timestamp']) for b in casts if event_type(b) == 'begincast'
            and ability_id(b) == P25_COIL_CAST_ID and b.get('sourceID') == e.get('sourceID')
            and b.get('sourceInstance',0) == e.get('sourceInstance',0)
            and ts-10000 <= int(b['timestamp']) < ts]
        result.append({'kind':'coil-soak','sourceID':e.get('sourceID'),
            'sourceInstance':e.get('sourceInstance',0),'regionIndex':slot,'sourcePosition':origin,
            'position':position,'positionEvidence':'spectral-coil-corner',
            'regionGeometryEvidence':'user-diagram-floor-landmarks',
            'startTimeMs':(begins[-1] if begins else ts-4000)-start,
            'impactTimeMs':ts-start,'endTimeMs':ts-start+450,'radiusYards':COIL_SOAK_RADIUS_YARDS})
    return result


ULATEK_MUSIC_TRACKS = {
    'p1': {'src':'/frontend/assets/audio/ulatek/p1.mp3','sourceStartSeconds':0,'durationMs':505000},
    'p2': {'src':'/frontend/assets/audio/ulatek/p2.mp3','sourceStartSeconds':509,'durationMs':242000},
    'p25': {'src':'/frontend/assets/audio/ulatek/p25.mp3','sourceStartSeconds':1471,'durationMs':34000},
    'p3': {'src':'/frontend/assets/audio/ulatek/p3.mp3','sourceStartSeconds':1087,'durationMs':381000},
}
# Silence-only intervals verified against the owner's source recording. Keep
# the opening fades and musical quiet passages; join only these internal gaps.
ULATEK_MUSIC_SILENCE_CUTS = {
    'p1': [(136.781202,140.402993),(298.767551,301.568027),(417.400227,420.916712)],
    'p3': [(145.569705,148.582381),(252.234286,255.126621)],
}
for _key, _cuts in ULATEK_MUSIC_SILENCE_CUTS.items():
    _track = ULATEK_MUSIC_TRACKS[_key]
    _track.update(sourceDurationMs=_track['durationMs'],silenceCutsSeconds=_cuts,
                  joinCrossfadeMs=120,assetVersion='20261013-continuous')
    _track['durationMs'] = round(_track['sourceDurationMs']-sum((b-a)*1000 for a,b in _cuts)-120*len(_cuts))
P25_EGG_SUMMON_IDS = {1300751,1304012,1315541}
P3_MUSIC_LEAD_MS = 5000


def _replay_music_profile(fight, events, boss_positions):
    start, duration = int(fight['startTime']), int(fight['endTime'])-int(fight['startTime'])
    rages = sorted([e for e in events if e.get('kind')=='rage'],key=lambda e:e['timeMs'])
    phases = []
    def add(key, begin, end):
        finish = min(duration,end,begin+ULATEK_MUSIC_TRACKS[key]['durationMs'])
        if begin < finish:
            phases.append({'key':key,'startTimeMs':begin,'endTimeMs':finish})
    egg_start, returned = None, None
    if len(rages)>1:
        second_end = rages[1]['endTimeMs']
        # Music follows the completed Call, never its cast start or an alias
        # that started before the second Fury actually finished.
        egg_start = min([e.get('endTimeMs',e['timeMs']) for e in events if e.get('kind')=='egg-summon'
                         and e.get('castStartTimeMs',e['timeMs'])>=second_end
                         and e.get('outcome','completed')=='completed'],default=None)
        shattered = min([e['timeMs'] for e in events if e.get('kind')=='shatter'
                         and e['timeMs']>=second_end],default=None)
        returned = min([int(p['timestamp'])-start for p in boss_positions
                        if shattered is not None and int(p['timestamp'])-start>=shattered],default=None)
    first_end = rages[0]['endTimeMs'] if rages else duration
    add('p1',0,first_end)
    p3_start = max(0,returned-P3_MUSIC_LEAD_MS) if returned is not None else None
    if rages:
        add('p2',first_end,egg_start if egg_start is not None else p3_start if p3_start is not None else duration)
    if egg_start is not None:
        add('p25',egg_start,p3_start if p3_start is not None else duration)
    if p3_start is not None:
        add('p3',p3_start,duration)
    return {'tracks':deepcopy(ULATEK_MUSIC_TRACKS),'phases':phases,'crossfadeMs':1500,
            'defaultVolume':.3,'p3Evidence':'first-boss-position-after-intermission-floor-break',
            'p3LeadMs':P3_MUSIC_LEAD_MS,'p25Evidence':'completed-serpent-call-after-second-bound-fury'}


def _replay_effects(fight, players, raw, changes):
    start, end = int(fight['startTime']), int(fight['endTime'])
    casts = sorted(raw.get('casts') or [], key=lambda e: int(e['timestamp']))
    rage = _rage_windows(fight, raw)
    first_shatter = None
    if len(rage) >= 2 and not rage[1].get('openEnded'):
        count = P25_MYTHIC_COIL_COUNT if int(fight.get('difficulty') or 0) == 5 else P25_COIL_COUNT
        coils = [e for e in casts if ability_id(e) == P25_COIL_CAST_ID and event_type(e) == 'cast'
                 and int(e['timestamp']) >= rage[1]['end']]
        if len(coils) >= count:
            last = int(coils[count-1]['timestamp'])
            settlement = max([last] + [int(e['timestamp']) for e in raw.get('damage') or []
                if ability_id(e) == P25_COIL_DAMAGE_ID and last <= int(e['timestamp']) <= last+1000])
            first_shatter = settlement+P25_FLOOR_BREAK_DELAY_MS
    position_index = _positions(raw)
    times = {actor: [r['timestamp'] for r in rows] for actor, rows in position_index.items()}
    def point(actor, ts, before_only=False):
        rows = position_index.get(actor) or []
        if not rows:
            return None
        i = bisect_right(times[actor], ts) if before_only else bisect_left(times[actor], ts)
        q = (rows[i-1] if i else None) if before_only else min(rows[max(0, i-1):i+1], key=lambda r: abs(r['timestamp']-ts), default=None)
        return {'x': q['x'], 'y': q['y']} if q and abs(q['timestamp']-ts) <= 3000 else None
    def cast_start(e, fallback):
        candidates = [r for r in casts if event_type(r) == 'begincast'
                      and ability_id(r) == ability_id(e) and r.get('sourceID') == e.get('sourceID')
                      and r.get('sourceInstance') == e.get('sourceInstance')
                      and int(e['timestamp'])-10000 <= int(r['timestamp']) <= int(e['timestamp'])]
        return int(candidates[-1]['timestamp']) if candidates else int(e['timestamp'])-fallback
    def wrath_platform(boss_position):
        if not boss_position:
            return None
        center = REPLAY_MAPS['platform']
        dx, dy = boss_position['x']-center['centerX'], boss_position['y']-center['centerY']
        if abs(dx) > 2_000 and abs(dy) > 2_000:
            return ('corner', 1 if dx > 0 else -1, 1 if dy > 0 else -1)
        return ('side', 'x' if abs(dx) >= abs(dy) else 'y',
                1 if (dx if abs(dx) >= abs(dy) else dy) > 0 else -1)
    def wrath_floor_fallback(platform):
        if not platform:
            return None
        center = REPLAY_MAPS['platform']
        # A fallback only: the tank's observed successful interception is the
        # actual reference, not the decorative corner of the inner floor.
        offset = 2_800
        if platform[0] == 'corner':
            return {'x': center['centerX'] + platform[1]*offset,
                    'y': center['centerY'] + platform[2]*offset}
        return ({'x': center['centerX'] + platform[2]*offset, 'y': center['centerY']}
                if platform[1] == 'x' else
                {'x': center['centerX'], 'y': center['centerY'] + platform[2]*offset})
    def boss_front(event, ts):
        origin = actor_position(event, 'source') or point(event.get('sourceID'), ts)
        if not origin:
            return None
        rows = position_index.get(event.get('sourceID')) or []
        nearest = min(rows, key=lambda row: abs(row['timestamp'] - ts), default=None)
        facing = (nearest.get('facing') if nearest and abs(nearest['timestamp'] - ts) <= 3000
                  else None)
        if facing is None and (str(event.get('resourceActor')) == '1'
                               or event.get('sourceResources')):
            facing = event.get('facing')
        if facing is None:
            return None
        radians = float(facing) / 100
        return {'x': origin['x'] + 300 * math.cos(radians),
                'y': origin['y'] - 300 * math.sin(radians)}
    circles, channels, npc_casts, cones, lost_platforms = [], [], [], [], []
    damage = raw.get('damage') or []
    wrath_casts = [e for e in casts if event_type(e) == 'cast' and ability_id(e) == 1298367]
    wrath_anchors = {}
    for index, wrath in enumerate(wrath_casts):
        ts = int(wrath['timestamp'])
        next_cast = int(wrath_casts[index+1]['timestamp']) if index+1 < len(wrath_casts) else end
        hits = sorted((hit for hit in damage
                       if ability_id(hit) in {1298369, 1301122}
                       and hit.get('sourceID') == wrath.get('sourceID')
                       and hit.get('targetID') in players and _amount(hit) > 0
                       and ts <= int(hit['timestamp']) < min(ts+5_000, next_cast)),
                      key=lambda hit: int(hit['timestamp']))
        hit_players = {hit['targetID'] for hit in hits}
        # Three distinct damaged players is the raid-wide failure threshold.
        # A stray second recipient does not invalidate the main tank's soak.
        if not hit_players or len(hit_players) >= 3:
            continue
        tank_id = max(hit_players, key=lambda pid: (sum(hit['targetID'] == pid for hit in hits),
                                                   pid == wrath.get('targetID')))
        tank_hits = [hit for hit in hits if hit['targetID'] == tank_id]
        if len(tank_hits) < 3:
            continue
        # Use the later strikes so the opening knockback cannot move the
        # fixed circle away from the tank's successful interception point.
        tank_points = [actor_position(hit, 'target') or point(tank_id, int(hit['timestamp']))
                       for hit in tank_hits[-5:]]
        tank_points = [p for p in tank_points if p]
        boss_position = point(wrath.get('sourceID'), cast_start(wrath, 5_000), before_only=True) or actor_position(wrath, 'source')
        platform = wrath_platform(boss_position)
        if platform and len(tank_points) >= 3:
            wrath_anchors.setdefault(platform, []).append({'x': median(p['x'] for p in tank_points),
                                                            'y': median(p['y'] for p in tank_points)})
    wrath_anchors = {platform: {'x': median(p['x'] for p in points),
                                'y': median(p['y'] for p in points)}
                     for platform, points in wrath_anchors.items()}
    for e in casts:
        if event_type(e) != 'cast':
            continue
        sid, ts = ability_id(e), int(e['timestamp'])
        origin = actor_position(e, 'source') or point(e.get('sourceID'), ts)
        if sid == 1296301 and origin:
            circles.append({'kind': 'rattle', 'sourceID': e.get('sourceID'), 'sourceInstance': e.get('sourceInstance', 0),
                'startTimeMs': cast_start(e, 4000)-start, 'impactTimeMs': ts-start,
                'endTimeMs': ts-start+750, 'position': origin, 'radiusYards': 35})
            changes.append({'kind': 'rattle', 'label': '响尾猛击', 'timeMs': cast_start(e, 4000)-start})
        if sid == 1298367:
            ticks = sorted({int(r['timestamp']) for r in damage if ability_id(r) in {1298369, 1301122}
                            and r.get('sourceID') == e.get('sourceID') and ts <= int(r['timestamp']) < ts+5000})
            wrath_start = cast_start(e, 5000)
            platform = wrath_platform(point(e.get('sourceID'), wrath_start, before_only=True) or origin)
            receiver = wrath_anchors.get(platform) or wrath_floor_fallback(platform)
            # One successful tank interception calibrates every cast on this
            # platform, including a later cast that spread to the whole raid.
            if receiver:
                circles.append({'kind': 'wrath', 'sourceID': e.get('sourceID'), 'playerID': e.get('targetID'),
                    'startTimeMs': wrath_start-start, 'impactTimeMs': ts-start,
                    'endTimeMs': (ticks[-1]+150 if ticks else ts+1000)-start,
                    'position': receiver, 'positionEvidence': ('successful-tank-interception'
                        if platform in wrath_anchors else 'floor-landmark-fallback'),
                    'radiusYards': MOTHER_WRATH_RADIUS_YARDS,
                    'tickTimesMs': [t-start for t in ticks]})
            channels.append({'actorID': e.get('sourceID'), 'spellID': sid, 'spellName': '蛇母之怒',
                'startTimeMs': ts-start, 'endTimeMs': (ticks[-1]+150 if ticks else ts+1000)-start,
                'phase': 'channel', 'outcome': 'completed'})
            changes.append({'kind': 'wrath', 'label': '蛇母之怒', 'timeMs': wrath_start-start})
        if sid == 1315341:
            before = cast_start(e, 10000)
            # Snapshot the Boss before Circling Prey, never the escaping raid.
            boss_position = point(e.get('sourceID'), before, before_only=True)
            if boss_position:
                lost_platforms.append({'timeMs': ts-start, 'position': boss_position,
                                       'positionEvidence': 'boss-before-cast'})
    last_unbridled = {}
    for hit in sorted(damage, key=lambda row: int(row['timestamp'])):
        if (ability_id(hit) != 1301007 or _amount(hit) <= 0
                or hit.get('targetID') not in players):
            continue
        ts = int(hit['timestamp'])
        source_id = hit.get('sourceID')
        if ts - last_unbridled.get(source_id, -10_000) <= 120:
            continue
        position = boss_front(hit, ts)
        if position:
            last_unbridled[source_id] = ts
            circles.append({'kind': 'unbridled', 'sourceID': hit.get('sourceID'),
                            'startTimeMs': ts-start, 'impactTimeMs': ts-start,
                            'endTimeMs': ts-start+650, 'position': position,
                            'radiusYards': 1.5})
    shrieker_ids = {a['id'] for a in raw.get('actorRows') or []
                    if a.get('gameID') == BLIGHTSCALE_SHRIEKER_GAME_ID}
    observed_cast_lengths = defaultdict(list)
    for completed_cast in casts:
        if event_type(completed_cast) != 'cast':
            continue
        completed_ts = int(completed_cast['timestamp'])
        began = [int(row['timestamp']) for row in casts
                 if event_type(row) == 'begincast' and ability_id(row) == ability_id(completed_cast)
                 and row.get('sourceID') == completed_cast.get('sourceID')
                 and (row.get('sourceInstance') or 0) == (completed_cast.get('sourceInstance') or 0)
                 and 0 < completed_ts - int(row['timestamp']) <= 15_000]
        if began:
            observed_cast_lengths[ability_id(completed_cast)].append(completed_ts - max(began))
    for e in casts:
        sid, ts = ability_id(e), int(e['timestamp'])
        if event_type(e) != 'begincast' or (sid not in {1290779, 1305650, 1305709, 1305775,
                                                       1306862, FESTER_BURST_ID, PETRIFYING_SPINE_ID}
                and e.get('sourceID') not in shrieker_ids):
            continue
        completed = [int(r['timestamp']) for r in casts if event_type(r) == 'cast'
                     and ability_id(r) == sid and r.get('sourceID') == e.get('sourceID')
                     and r.get('sourceInstance', 0) == e.get('sourceInstance', 0)
                     and ts < int(r['timestamp']) <= ts+15000]
        interrupts = [r for r in raw.get('interrupts') or []
                   if r.get('targetID') == e.get('sourceID')
                   and r.get('targetInstance', 0) == e.get('sourceInstance', 0)
                   and r.get('extraAbilityGameID') == sid and ts < int(r['timestamp']) <= ts+15000]
        stopped = [int(r['timestamp']) for r in interrupts]
        finishes = [(t, 'completed') for t in completed] + [(t, 'interrupted') for t in stopped]
        if finishes:
            finish, outcome = min(finishes)
            expected_duration = (median(observed_cast_lengths[sid]) if observed_cast_lengths[sid]
                                 else REPLAY_CAST_EXPECTED_MS.get(sid, finish-ts))
            expected_finish = max(finish + 250, ts + int(expected_duration)) if outcome == 'interrupted' else finish
            npc_casts.append({'actorID': e.get('sourceID'), 'instance': e.get('sourceInstance', 0),
                'startTimeMs': ts-start, 'endTimeMs': finish-start,
                'expectedEndTimeMs': expected_finish-start,
                'spellID': sid, 'spellName': GUIDE_SPELLS.get(sid), 'outcome': outcome})
            if outcome == 'interrupted':
                kick = next(r for r in interrupts if int(r['timestamp']) == finish)
                kick_sid = ability_id(kick)
                npc_casts[-1].update(interruptPlayerID=kick.get('sourceID'), interruptSpellID=kick_sid,
                    interruptIcon=f'/assets/spells/{kick_sid}.png' if kick_sid in REPLAY_INTERRUPT_IDS else None)
            if sid in {1290779,1305650,1310764}:
                changes.append({'kind':'npc-cast','label':(GUIDE_SPELLS.get(sid) or '尖啸者')+'施法',
                                'timeMs':ts-start})
                if outcome == 'interrupted':
                    changes.append({'kind':'interrupt','label':(GUIDE_SPELLS.get(sid) or '尖啸者')+'打断',
                                    'timeMs':finish-start})
            if sid == FESTER_BURST_ID:
                completion = next((r for r in casts if event_type(r) == 'cast'
                    and ability_id(r) == sid and int(r['timestamp']) == finish
                    and r.get('sourceID') == e.get('sourceID')
                    and r.get('sourceInstance', 0) == e.get('sourceInstance', 0)), None)
                origin = actor_position(e, 'source') or (actor_position(completion, 'source') if completion else None)
                if origin:
                    circles.append({'kind': 'fester-safe', 'sourceID': e.get('sourceID'),
                        'sourceInstance': e.get('sourceInstance', 0), 'startTimeMs': ts-start,
                        'impactTimeMs': finish-start, 'endTimeMs': finish-start,
                        'position': origin, 'radiusYards': FESTER_SAFE_RADIUS_YARDS})
                    changes.append({'kind': 'fester', 'label': '腐败爆发', 'timeMs': ts-start})
            if sid == DESPERATE_THRASH_ID:
                # Reconstruct aim from this exact instance's tank hit; the
                # replay is retrospective, so a completed hit can prove aim.
                impact = next((r for r in damage if ability_id(r) == sid
                    and r.get('sourceID') == e.get('sourceID')
                    and r.get('sourceInstance', 0) == e.get('sourceInstance', 0)
                    and finish-250 <= int(r['timestamp']) <= finish+500
                    and players.get(r.get('targetID'), {}).get('role') == 'tank'), None)
                completion = next((r for r in casts if event_type(r) == 'cast'
                    and ability_id(r) == sid and int(r['timestamp']) == finish
                    and r.get('sourceID') == e.get('sourceID')
                    and r.get('sourceInstance', 0) == e.get('sourceInstance', 0)), None)
                origin = actor_position(e, 'source') or (actor_position(completion, 'source') if completion else None)
                target = ((actor_position(impact, 'target') or point(impact.get('targetID'), finish)) if impact else None)
                if not target and origin:
                    tanks = [point(pid, ts) for pid, p in players.items() if p.get('role') == 'tank']
                    target = min((p for p in tanks if p), key=lambda p: (p['x']-origin['x'])**2+(p['y']-origin['y'])**2, default=None)
                if origin and target:
                    cones.append({'actorID': e.get('sourceID'), 'instance': e.get('sourceInstance', 0),
                        'startTimeMs': ts-start, 'endTimeMs': finish-start,
                        'position': origin, 'targetPosition': target, 'spellID': sid,
                        'angleDegrees': DESPERATE_THRASH_ANGLE_DEGREES,
                        'lengthYards': DESPERATE_THRASH_LENGTH_YARDS,
                        'directionEvidence': 'tank-hit' if impact else 'nearest-tank'})
    for mark in _aura_intervals(raw.get('debuffs') or [], PETRIFYING_SPINE_MARK_ID, end):
        pid = mark['playerID']
        if pid not in players:
            continue
        apply = next((e for e in raw.get('debuffs') or [] if ability_id(e) == PETRIFYING_SPINE_MARK_ID
                      and e.get('targetID') == pid and int(e['timestamp']) == mark['start']), None)
        caster, instance = (apply.get('sourceID'), apply.get('sourceInstance') or 0) if apply else (None, 0)
        cast = next((e for e in casts if event_type(e) == 'cast' and ability_id(e) == PETRIFYING_SPINE_ID
                     and e.get('sourceID') == caster and (e.get('sourceInstance') or 0) == instance
                     and abs(int(e['timestamp']) - mark['end']) <= 1_000), None)
        impact = int(cast['timestamp']) if cast else mark['end']
        position = point(pid, impact)
        if position:
            circles.append({'kind': 'petrifying-spine', 'sourceID': caster,
                            'sourceInstance': instance, 'playerID': pid,
                            'startTimeMs': mark['start']-start, 'impactTimeMs': impact-start,
                            'endTimeMs': impact-start+(500 if cast else 0),
                            'position': position, 'radiusYards': PETRIFYING_SPINE_RADIUS_YARDS})
        if cast:
            changes.append({'kind': 'spine', 'label': '石化钉刺', 'timeMs': impact-start})
    boss_id = raw.get('bossID')
    changes.extend({'kind':'egg-summon','label':'毒蛇呼唤','timeMs':int(e['timestamp'])-start,
                    'endTimeMs':int(e['timestamp'])-start,'castStartTimeMs':cast_start(e,0)-start,
                    'spellID':ability_id(e),'outcome':'completed'}
                   for e in casts if event_type(e)=='cast' and ability_id(e) in P25_EGG_SUMMON_IDS
                   and e.get('sourceID')==boss_id)
    for row in rage:
        channels.append({'actorID': boss_id, 'spellID': RAGE_ID, 'spellName': '被缚之怒',
                         'startTimeMs': row['start']-start, 'endTimeMs': row['end']-start,
                         'phase': 'channel', 'outcome': 'completed'})
    phase_windows = []
    if first_shatter is not None:
        changes.append({'kind': 'shatter', 'label': '初次碎场', 'timeMs': first_shatter-start})
    if rage:
        returns = [int(e['timestamp']) for e in casts if len(rage)>1 and ability_id(e) == RAGE_ID
                   and event_type(e) == 'begincast' and rage[1]['start']-10000 <= int(e['timestamp']) <= rage[1]['start']]
        phase_end = max(returns) if returns else rage[1]['start'] if len(rage)>1 else end
        # Camera follows the observed raid return, before the second Fury cast.
        # Require a populated corridor first and a sustained majority back on
        # the central floor. One tank or a teleport cannot switch the camera.
        corridor_seen, return_candidate, return_time = False, None, None
        for time in range(rage[0]['end'], phase_end, 500):
            positioned = [point(pid, time, before_only=True) for pid in players]
            positioned = [p for p in positioned if p]
            if len(positioned) < max(3, len(players)*.6):
                return_candidate = None
                continue
            outside = sum(abs(p['x']) > 5500 for p in positioned)
            corridor_seen |= outside >= len(positioned)*.6
            inside = sum(abs(p['x']) <= 4500 and abs(p['y']-155367) <= 5500 for p in positioned)
            if corridor_seen and inside >= len(positioned)*.75:
                return_candidate = time if return_candidate is None else return_candidate
                if time-return_candidate >= 1000:
                    return_time = return_candidate
                    break
            else:
                return_candidate = None
        if return_time is not None:
            phase_end = return_time
            changes.append({'kind': 'return', 'label': '返回中场', 'timeMs': phase_end-start})
        phase_windows.append({'key': 'p2', 'startTimeMs': rage[0]['end']-start, 'endTimeMs': phase_end-start,
                              'endEvidence': 'raid-position-return' if return_time is not None else 'fury-cast'})
        changes.append({'kind': 'p2', 'label': '双长廊', 'timeMs': rage[0]['end']-start})
    circles.extend(_replay_coil_soaks(fight, raw))
    for c in circles:
        if c['kind'] == 'coil-soak':
            changes.append({'kind':'coil-soak','label':'幽魂盘卷分摊','timeMs':c['startTimeMs']})
    return {'circles': circles, 'channels': channels, 'npcCasts': npc_casts, 'cones': cones,
            'musicReplay':_replay_music_profile(fight,changes,position_index.get(boss_id,[])),
            'phaseWindows': phase_windows, 'lostPlatforms': lost_platforms, 'maps': deepcopy(REPLAY_MAPS),
            'arena': {'centerX': 0, 'centerY': 155367, 'pixelsPerYard': 1188/85,
                      'imageCenterX': 2123/2, 'imageCenterY': 1188/2, 'estimated': False}}


def _replay_raid_impacts(fight, players, raw):
    groups = []
    for e in sorted(raw.get('damage') or [], key=lambda r: int(r['timestamp'])):
        sid, ts = ability_id(e), int(e['timestamp'])
        if sid not in {1298369, 1301122, RATTLER_SLAM_ID} or e.get('targetID') not in players or _amount(e) <= 0:
            continue
        kind = 'slam' if sid == RATTLER_SLAM_ID else 'wrath'
        group = next((g for g in reversed(groups[-4:]) if g['kind'] == kind
                      and g['sourceID'] == e.get('sourceID') and ts-g['timestamp'] <= 120), None)
        if group is None:
            group = {'timestamp': ts, 'kind': kind, 'sourceID': e.get('sourceID'), 'players': set(), 'explicit': False}
            groups.append(group)
        group['players'].add(e['targetID'])
        group['explicit'] |= sid in {1301122, RATTLER_SLAM_ID}
    return [{'kind': g['kind'], 'timeMs': g['timestamp']-fight['startTime'],
             'affectedCount': len(g['players']), 'sourceID': g['sourceID']}
            for g in groups if g['explicit'] or len(g['players']) >= 3]


def _replay_eggs(fight, players, raw, auras, clear_times):
    """Instance lifecycles; pickup association needs a unique nearby egg.

    A removed carry aura alone never creates a permanent ground egg. Preserve
    the observed release point briefly, or the confirmed consumption/death.
    """
    start, end = int(fight['startTime']), int(fight['endTime'])
    metadata = {a['id']: a for a in raw.get('actorRows') or []}
    records = {}
    rows = raw.get('replayEvents') or (raw.get('casts', []) + raw.get('trackedDamageTaken', []) + raw.get('enemyBuffs', []))
    for e in rows:
        ts, sid, kind = int(e['timestamp'])-start, ability_id(e), event_type(e)
        for side in ('source', 'target'):
            aid, instance = e.get(side+'ID'), e.get(side+'Instance') or 0
            gid = metadata.get(aid, {}).get('gameID')
            if gid not in REPLAY_EGG_GAME_IDS:
                continue
            r = records.setdefault((aid, instance), {'actorID': aid, 'instance': instance, 'gameID': gid,
                'samples': {}, 'shell': {}, 'shellEvents': [], 'interactions': {}, 'carries': [], 'deathTimeMs': None})
            p = actor_position(e, side)
            if p:
                r['samples'][ts] = [ts, p['x'], p['y']]
                resource = e.get(side+'Resources') or e
                if resource.get('absorb') is not None:
                    r['shell'][ts] = int(resource['absorb'])
            if side == 'target':
                if sid == HARDENED_SHELL_ID and kind in {'applybuff', 'refreshbuff', 'removebuff'}:
                    r['shellEvents'].append([ts, kind != 'removebuff'])
                # Shielded carryable eggs stay at 1 HP after shell overkill.
                # Require actual zero HP, or an explicit death event.
                resource = e.get('targetResources') or (e if actor_position(e, 'target') else {})
                if kind == 'death' or kind == 'damage' and e.get('overkill') is not None and e['overkill'] >= 0 and resource.get('hitPoints') == 0:
                    r['deathTimeMs'] = min(ts, r['deathTimeMs'] if r['deathTimeMs'] is not None else ts)
                if kind == 'damage' and (_amount(e) > 0 or int(e.get('absorbed') or 0) > 0):
                    r['interactions'][(ts//100, e.get('sourceID'))] = {'timeMs': ts, 'playerID': e.get('sourceID'), 'spellID': sid}
    eggs = []
    for r in records.values():
        if not r['samples']:
            continue  # WCL's duplicate NPC alias has no observed coordinates.
        r['samples'] = sorted(r['samples'].values())
        r['position'] = {'x': r['samples'][0][1], 'y': r['samples'][0][2]}
        r['startTimeMs'] = r['samples'][0][0]
        r['endTimeMs'] = r['deathTimeMs'] if r['deathTimeMs'] is not None else end-start
        if r['gameID'] in CARRYABLE_EGG_GAME_IDS:
            r['endTimeMs'] = min([r['endTimeMs']] + [t for t in clear_times if t > r['startTimeMs']])
        else:
            # Without a terminal event, stop extrapolating a moving/clutch NPC.
            r['endTimeMs'] = min(r['endTimeMs'], r['samples'][-1][0]+1000)
        maximum = max(r['shell'].values(), default=0)
        r['shield'] = [[ts, amount, maximum] for ts, amount in sorted(r.pop('shell').items())]
        r['shieldBreakTimeMs'] = next((ts for ts, active in sorted(r['shellEvents']) if not active), None)
        if r['shieldBreakTimeMs'] is None and maximum:
            r['shieldBreakTimeMs'] = next((t for t, amount, _ in r['shield'] if amount == 0), None)
        r['interactions'] = sorted(r['interactions'].values(), key=lambda h: h['timeMs'])
        r['key'] = f"egg:{r['actorID']}:{r['instance']}"
        eggs.append(r)
    positions = _positions(raw)
    deaths = raw.get('deaths') or []
    for a in sorted((a for a in auras if a['kind'] == 'egg'), key=lambda a: a['startTimeMs']):
        p = position_at_interpolated(positions, a['playerID'], start+a['startTimeMs'])
        if not p or not p.get('reliable'):
            continue
        # Teleports (e.g. Shadowstep) can publish their new coordinates a few
        # hundred milliseconds after the pickup aura. Use nearby real samples
        # for association; never extrapolate an invented egg position.
        pickup_time = start+a['startTimeMs']
        nearby = [p] + [q for q in positions.get(a['playerID'], [])
                         if pickup_time-250 <= q['timestamp'] <= pickup_time+750]
        candidates = []
        for r in eggs:
            if r['gameID'] not in CARRYABLE_EGG_GAME_IDS or r['carries'] or not r['startTimeMs'] <= a['startTimeMs'] < r['endTimeMs']:
                continue
            if r['shieldBreakTimeMs'] is not None and r['shieldBreakTimeMs'] > a['startTimeMs']+250:
                continue
            distance = min(math.hypot(q['x']-r['position']['x'], q['y']-r['position']['y'])/100 for q in nearby)
            if distance <= 3:
                candidates.append((distance, r))
        candidates.sort(key=lambda item: item[0])
        if not candidates or len(candidates)>1 and candidates[1][0]-candidates[0][0] < .25:
            continue
        distance, r = candidates[0]
        release = position_at_interpolated(positions, a['playerID'], start+a['endTimeMs'])
        consumed = any(ability_id(e) == 1312150 and e.get('targetID') == a['playerID']
                       and abs(int(e['timestamp'])-start-a['endTimeMs']) <= 250 for e in raw.get('debuffs') or [])
        r['carries'].append({**a, 'releasePosition': {'x': release['x'], 'y': release['y']} if release else None,
            'outcome': 'consumed' if consumed else 'dead' if any(e.get('targetID') == a['playerID'] and abs(int(e['timestamp'])-start-a['endTimeMs'])<500 for e in deaths) else 'released',
            'associationEstimated': True, 'pickupDistanceYards': round(distance, 2)})
        r['endTimeMs'] = min(r['endTimeMs'], a['endTimeMs'])
        a['eggKey'] = r['key']
    for egg in eggs:
        if egg['gameID'] in CARRYABLE_EGG_GAME_IDS and not egg['carries'] and egg['deathTimeMs'] is None:
            # An unpicked corridor egg with no later observations must not
            # remain on screen through the next phase boundary.
            egg['endTimeMs'] = min(egg['endTimeMs'], egg['samples'][-1][0] + 1_000)
    return sorted(eggs, key=lambda r: (r['startTimeMs'], r['key']))


def _replay_projectiles(fight, players, raw, auras):
    """Observed emitters and tank ticks; travel is a visual model."""
    start = int(fight['startTime'])
    positions, wretch_positions = defaultdict(dict), defaultdict(dict)
    wretch_ids = {a['id'] for a in raw.get('actorRows') or [] if a.get('gameID') == 263942}
    deaths = {}
    for e in raw.get('replayEvents') or raw.get('resources') or []:
        ts = int(e['timestamp'])
        if e.get('type') == 'death' and e.get('targetID') in wretch_ids:
            deaths[(e['targetID'], e.get('targetInstance', 0))] = ts
        for side in ('source', 'target'):
            pid = e.get(side+'ID')
            if pid not in players and pid not in wretch_ids:
                continue
            p = actor_position(e, side)
            if not p:
                continue
            if pid in players:
                positions[pid][ts] = p
            else:
                wretch_positions[(pid, e.get(side+'Instance', 0))][ts] = p
    positions = {pid: sorted(v.items()) for pid,v in positions.items()}
    wretch_positions = {key: sorted(v.items()) for key,v in wretch_positions.items()}
    times = {pid:[v[0] for v in rows] for pid,rows in positions.items()}
    wretch_times = {key:[v[0] for v in rows] for key,rows in wretch_positions.items()}
    def nearby(index, stamps, pid, ts, gap):
        rows = index.get(pid) or []
        i = bisect_right(stamps.get(pid) or [], ts)
        row = rows[i-1] if i else None
        return row[1] if row and ts-row[0] <= gap else None
    waves, tethers = [], []
    def wave(ts, pid, p, directions, kind):
        if p:
            waves.append({'timeMs': ts-start, 'playerID': pid, 'position': p, 'kind': kind,
                'directions': directions, 'widthYards': REPLAY_WAVE_WIDTH_YARDS,
                'speedYardsPerSecond': REPLAY_WAVE_SPEED_YARDS_PER_SECOND,
                'travelYards': REPLAY_WAVE_TRAVEL_YARDS, 'travelEvidence': 'visual-model'})
    # A Boss arm wave is one diagonal front between two synchronized casts:
    # Ula'tek (1319282) and the paired Gore Rattle (1311807). The front moves
    # in Ula'tek's observed facing direction. Later 1298570 casts do not prove
    # independent fronts and must not be replayed from their edge positions.
    casts = raw.get('casts') or []
    for cast in casts:
        if event_type(cast) != 'cast' or ability_id(cast) != BOSS_CAUSTIC_WAVE_CAST_ID:
            continue
        origin = actor_position(cast, 'source')
        facing = cast.get('facing')
        if not origin or facing is None:
            continue
        ts = int(cast['timestamp'])
        partners = [row for row in casts if event_type(row) == 'cast'
                    and ability_id(row) == BOSS_CAUSTIC_WAVE_EDGE_CAST_ID
                    and abs(int(row['timestamp']) - ts) <= 150
                    and actor_position(row, 'source')]
        if len(partners) != 1:
            continue
        edge = actor_position(partners[0], 'source')
        if not 2000 <= math.hypot(edge['x']-origin['x'], edge['y']-origin['y']) <= 8000:
            continue
        starts = [int(row['timestamp']) for row in casts if event_type(row) == 'begincast'
                  and ability_id(row) == BOSS_CAUSTIC_WAVE_CAST_ID
                  and row.get('sourceID') == cast.get('sourceID')
                  and 0 < ts-int(row['timestamp']) <= 9000]
        radians = float(facing) / 100
        waves.append({'timeMs': ts-start, 'warningStartTimeMs': max(starts)-start if starts else ts-start,
                      'position': origin, 'frontEndPosition': edge, 'kind': 'boss-caustic',
                      'directions': [{'x': math.cos(radians), 'y': -math.sin(radians)}],
                      'widthYards': REPLAY_WAVE_WIDTH_YARDS,
                      'speedYardsPerSecond': REPLAY_WAVE_SPEED_YARDS_PER_SECOND,
                      'travelYards': 110, 'travelEvidence': 'visual-model',
                      'sourceSpellID': BOSS_CAUSTIC_WAVE_CAST_ID,
                      'pairedSpellID': BOSS_CAUSTIC_WAVE_EDGE_CAST_ID,
                      'sourceActorID': cast.get('sourceID'),
                      'pairedActorID': partners[0].get('sourceID'),
                      'directionEvidence': 'synchronized-casts-and-boss-facing'})
    if int(fight.get('difficulty') or 0) == 5:
        for a in auras:
            if a['kind'] != 'purge' or a['spellID'] != 1312967:
                continue
            launch = a['warningEndTimeMs']+start
            if launch-(a['startTimeMs']+start) < VOLATILE_PURGE_WARNING_MS:
                continue
            wave(launch, a['playerID'], nearby(positions,times,a['playerID'],launch,3000),
                 [{'x':0,'y':1},{'x':math.sqrt(3)/2,'y':-.5},{'x':-math.sqrt(3)/2,'y':-.5}], 'purge')
    groups = {}
    def tether_target(source, tank, ts, cast):
        if not source:
            return None
        candidates = []
        explicit = (cast.get('targetID'), cast.get('targetInstance', 0)) if cast else None
        for target in wretch_positions:
            if deaths.get(target, math.inf) <= ts:
                continue
            p = nearby(wretch_positions, wretch_times, target, ts, 3000)
            if not p:
                continue
            if target == explicit:
                return target, p
            dx, dy = p['x']-source['x'], p['y']-source['y']
            length = math.hypot(dx, dy)
            if not length:
                continue
            score = 0
            if tank:
                tx, ty = tank['x']-source['x'], tank['y']-source['y']
                along = (tx*dx+ty*dy)/(length*length)
                if not 0 <= along <= 1.25:
                    continue
                score = abs(tx*dy-ty*dx)/length
            candidates.append((score, target, p))
        candidates.sort(key=lambda row: row[0])
        # Multiple equally aligned living instances do not prove which one was linked.
        if not candidates or len(candidates) > 1 and candidates[1][0]-candidates[0][0] < 100:
            return None
        return candidates[0][1:]
    ticks = sorted((e for e in raw.get('damage') or [] if ability_id(e) == TOXIC_INCUBATION_HIT_ID
                    and players.get(e.get('targetID'),{}).get('role') == 'tank'), key=lambda e:e['timestamp'])
    for e in ticks:
        ts, pid = int(e['timestamp']), e['targetID']
        p = actor_position(e,'target') or nearby(positions,times,pid,ts,750)
        key = (e.get('sourceID'), e.get('sourceInstance',0), pid)
        group = groups.get(key)
        if group is None or ts-start-group['endTimeMs'] > 2000:
            cast = next((c for c in raw.get('casts') or []
                if c.get('sourceID') == key[0] and c.get('sourceInstance',0) == key[1]
                and ability_id(c) == 1299759 and abs(int(c['timestamp'])-ts)<1000),None)
            source = actor_position(e,'source')
            if not source:
                source = actor_position(cast,'source') if cast else None
            group = {'sourceID':key[0],'instance':key[1],'playerID':pid,'position':source,
                     'startTimeMs':ts-start,'endTimeMs':ts-start+300,'tickTimesMs':[]}
            target = tether_target(source, p, ts, cast)
            if target:
                (target_id, target_instance), target_position = target
                group.update(targetID=target_id, targetInstance=target_instance,
                             targetPosition=target_position)
            groups[key] = group
            tethers.append(group)
        group['endTimeMs'] = ts-start+300
        group['tickTimesMs'].append(ts-start)
        target_key = (group.get('targetID'), group.get('targetInstance', 0))
        target = nearby(wretch_positions, wretch_times, target_key, ts, 3000)
        source = group['position']
        if p and source and target and deaths.get(target_key, math.inf) > ts:
            dx, dy = target['x']-source['x'], target['y']-source['y']
            length = math.hypot(dx, dy)
            if length:
                wave(ts,pid,p,[{'x':-dy/length,'y':dx/length},
                              {'x':dy/length,'y':-dx/length}],'tank-incubation')
    return {'waves':waves,'tankTethers':tethers}


def _replay_warden_health(fight, raw):
    """Keep each corridor Warden's owned health separate from other instances."""
    start = int(fight['startTime'])
    ids = {a['id'] for a in raw.get('actorRows') or [] if a.get('gameID') == 264045}
    rows = {}
    for e in sorted(raw.get('replayEvents') or [], key=lambda row: row['timestamp']):
        t = int(e['timestamp'])-start
        for side in ('source', 'target'):
            actor = e.get(side+'ID')
            if actor not in ids:
                continue
            instance = e.get(side+'Instance', 0)
            row = rows.setdefault((actor, instance), {'actorID':actor, 'instance':instance,
                'gameID':264045, 'name':'厄鳞守卫', 'startTimeMs':t, 'health':{}, 'states':[]})
            if e.get('type') == 'death' and side == 'target':
                row['states'].append([t,'dead'])
            if not row.get('position'):
                row['position'] = actor_position(e, side)
            resource = e.get(side+'Resources') or {}
            if str(e.get('resourceActor')) == ('1' if side == 'source' else '2'):
                resource = e
            hp, maximum = resource.get('hitPoints'), resource.get('maxHitPoints')
            if hp is not None and maximum and maximum > 0:
                row['health'][t//100] = [t, int(hp), int(maximum)]
    return [{**row, 'health':sorted(row['health'].values())} for row in rows.values()]


def _replay_feedback(fight, players, raw, tether_review=None):
    """Boss-local effects driven by observed aura lifetimes, never guide timers."""
    start, end = int(fight['startTime']), int(fight['endTime'])
    debuffs = raw.get('debuffs') or []
    auras = []
    fang_positions = None
    for sid, kind in ([(sid, 'egg') for sid in EGG_CARRY_IDS] + [(FANG_AURA_ID, 'fang'), (SERPENT_BITE_TARGET_ID, 'bite')] + [(sid, 'purge') for sid in VOLATILE_PURGE_IDS]):
        for row in _aura_intervals(debuffs, sid, end):
            if row['playerID'] in players:
                source = next((e.get('sourceID') for e in debuffs if ability_id(e) == sid
                               and e.get('targetID') == row['playerID'] and int(e['timestamp']) == row['start']), None)
                auras.append({**row, 'sourceID': source, 'kind': kind, 'startTimeMs': row['start']-start,
                              'endTimeMs': row['end']-start, 'spellID': sid,
                              'radiusYards': SERPENT_BITE_RADIUS_YARDS if kind == 'bite' else
                                  FANG_BREAK_RADIUS_YARDS if kind == 'fang' else 3 if sid == 1316356 else None})
                if kind == 'fang':
                    if fang_positions is None:
                        fang_positions = _positions(raw, 'replayEvents' if raw.get('replayEvents') else 'resources')
                    origin = position_at_interpolated(fang_positions, row['playerID'], row['start'])
                    if origin and origin.get('reliable'):
                        auras[-1]['position'] = {'x': origin['x'], 'y': origin['y']}
                        auras[-1]['positionEvidence'] = origin.get('positionRule', 'observed')
                if kind == 'purge':
                    # The first mark is not a countdown. The second aura's
                    # first six seconds own both the circle and Mythic triad.
                    auras[-1]['warningStartTimeMs'] = row['start']-start
                    auras[-1]['warningEndTimeMs'] = (min(row['end'], row['start']+VOLATILE_PURGE_WARNING_MS)
                                                   if sid == 1316356 else row['start'])-start
    # This shell is unique to the four Doomscale eggs. Ordinary carry auras
    # must not create the red 20-second timer.
    shell_events = [event for stream in ('friendlyBuffs', 'debuffs', 'replayEvents')
                    for event in raw.get(stream) or []
                    if ability_id(event) == DOOMSCALE_EGG_CONTACT_ID
                    and event.get('targetID') in players]
    seen_shell_auras = set()
    for row in _aura_intervals(shell_events, DOOMSCALE_EGG_CONTACT_ID, end):
        if row['playerID'] not in players:
            continue
        key = (row['playerID'], row['start'])
        if key in seen_shell_auras:
            continue
        seen_shell_auras.add(key)
        auras.append({'playerID': row['playerID'], 'kind': 'doom-egg',
                      'spellID': DOOMSCALE_EGG_CONTACT_ID,
                      'startTimeMs': row['start']-start,
                      'endTimeMs': min(row['end'], row['start']+20_000)-start})
    if int(fight.get('difficulty') or 0) == 5:
        # Countdown begins on the post-Bite first Purge mark. Changing aura
        # ID after five seconds does not restart or cancel its six seconds.
        for a in auras:
            if a['kind'] != 'purge':
                continue
            a.update(warningStartTimeMs=a['startTimeMs'],warningEndTimeMs=a['startTimeMs'],radiusYards=None)
            if a['spellID'] == 1312967:
                second = next((b for b in auras if b['spellID'] == 1316356
                    and b['playerID'] == a['playerID']
                    and 0 <= b['startTimeMs']-a['endTimeMs'] <= 250),None)
                finish = min(a['startTimeMs']+VOLATILE_PURGE_WARNING_MS,
                             second['endTimeMs'] if second else a['endTimeMs'])
                a.update(radiusYards=3,warningEndTimeMs=finish)
    projectiles = _replay_projectiles(fight, players, raw, auras)
    hits = {(int(e['timestamp'])-start, e.get('targetID')) for e in debuffs
            if ability_id(e) == WAVE_ID and event_type(e) in {'applydebuff', 'applydebuffstack', 'refreshdebuff'}
            and e.get('targetID') in players}
    hits.update((int(e['timestamp'])-start, e.get('targetID')) for e in raw.get('damage') or []
                if ability_id(e) in {WAVE_ID, 1286885, 1298369, 1301122, RATTLER_SLAM_ID,
                                     PETRIFYING_SPINE_ID} and e.get('targetID') in players and _amount(e) > 0)
    changes = [{'timeMs': 0, 'label': '战斗开始', 'kind': 'start'}]
    changes += [{'timeMs': int(e['timestamp'])-start, 'label': '场地破裂', 'kind': 'shatter'}
                for e in completed_casts(raw.get('casts') or [], 1315341)]
    changes += [{'timeMs': row['start']-start, 'label': '被缚之怒', 'kind': 'rage', 'endTimeMs': row['end']-start}
                for row in _rage_windows(fight, raw)]
    scene = _replay_effects(fight, players, raw, changes)
    clear_times = [c['timeMs'] for c in changes if c['kind'] in {'rage', 'shatter'}]
    eggs = _replay_eggs(fight, players, raw, auras, clear_times)
    egg_hatch_casts = []
    egg_by_instance = {(egg['actorID'], egg['instance']): egg for egg in eggs
                       if egg['gameID'] == DOOMSCALE_EGG_GAME_ID}
    doomscale_actors = {row['id'] for row in raw.get('actorRows') or []
                        if row.get('gameID') == DOOMSCALE_EGG_GAME_ID}
    unique_contacts = {}
    for stream in ('friendlyBuffs', 'enemyBuffs', 'debuffs', 'replayEvents'):
        for event in raw.get(stream) or []:
            if ability_id(event) == DOOMSCALE_EGG_CONTACT_ID and event_type(event) in {
                    'applybuff', 'applydebuff', 'refreshbuff', 'refreshdebuff'}:
                key = (int(event['timestamp']), event_type(event), event.get('sourceID'),
                       event.get('sourceInstance') or 0, event.get('targetID'),
                       event.get('targetInstance') or 0)
                unique_contacts.setdefault(key, event)
    contacts = sorted(unique_contacts.values(), key=lambda event: int(event['timestamp']))
    contact_positions = _positions(raw) if any(event.get('targetID') in players for event in contacts) else {}
    claimed_contacts = set()
    hatch_events = (raw.get('replayEvents') or []) + (raw.get('casts') or [])
    hatch_starts = {}
    for cast in hatch_events:
        if ability_id(cast) == DOOMSCALE_HATCH_CAST_ID and event_type(cast) == 'begincast':
            actor, instance = cast.get('sourceID'), cast.get('sourceInstance') or 0
            if actor in doomscale_actors or (actor, instance) in egg_by_instance:
                hatch_starts.setdefault((actor, instance, int(cast['timestamp'])), cast)
    ordered_starts = sorted(hatch_starts.values(), key=lambda event: (int(event['timestamp']),
                                                                       event.get('sourceInstance') or 0))
    hatch_positions = {id(cast): (egg_by_instance.get((cast.get('sourceID'),
                                                       cast.get('sourceInstance') or 0)) or {}).get('position')
                       or actor_position(cast, 'source') for cast in ordered_starts}
    sides_by_event = {}
    cast_batches = []
    for cast in ordered_starts:
        if not cast_batches or int(cast['timestamp'])-int(cast_batches[-1][0]['timestamp']) > 1000:
            cast_batches.append([])
        cast_batches[-1].append(cast)
    for batch in cast_batches:
        # WCL often omits egg coordinates. Rank any observed x positions and
        # distribute the remaining simultaneous casts evenly between sides.
        ranked = sorted(batch, key=lambda cast: (
            hatch_positions[id(cast)]['x'] if hatch_positions[id(cast)] else 0,
            int(cast['timestamp']), cast.get('sourceInstance') or 0))
        for index, cast in enumerate(ranked):
            sides_by_event[id(cast)] = 'left' if index < (len(ranked)+1)//2 else 'right'
    for cast in ordered_starts:
        actor, instance, cast_start_ms = cast.get('sourceID'), cast.get('sourceInstance') or 0, int(cast['timestamp'])-start
        egg = egg_by_instance.get((actor, instance))
        position = hatch_positions[id(cast)]
        side = sides_by_event[id(cast)]
        finish = cast_start_ms + 90_000
        def touches_egg(event):
            if ((event.get('sourceID') == actor and (event.get('sourceInstance') or 0) == instance)
                    or (event.get('targetID') == actor and (event.get('targetInstance') or 0) == instance)):
                return True
            player_id = event.get('targetID') if event.get('targetID') in players else event.get('sourceID')
            if player_id not in players:
                return False
            player_position = position_at_interpolated(contact_positions, player_id, int(event['timestamp']))
            if not player_position or not player_position.get('reliable'):
                return False
            if position:
                return math.hypot(player_position['x']-position['x'],
                                  player_position['y']-position['y']) <= 300
            return ('left' if player_position['x'] < 0 else 'right') == side
        contact = next((event for event in contacts
                        if cast_start_ms <= int(event['timestamp'])-start < finish
                        and id(event) not in claimed_contacts
                        and touches_egg(event)), None)
        if contact:
            claimed_contacts.add(id(contact))
        pickup_ms = int(contact['timestamp'])-start if contact else None
        egg_hatch_casts.append({
            'eggKey': (egg or {}).get('key'), 'actorID': actor, 'instance': instance,
            'position': position, 'side': side, 'spellID': DOOMSCALE_HATCH_CAST_ID, 'spellName': '孵化厄运',
            'startTimeMs': cast_start_ms, 'endTimeMs': pickup_ms if contact else finish,
            'expectedEndTimeMs': finish, 'durationMs': 90_000,
            'outcome': 'interrupted' if contact else 'completed' if end-start >= finish else 'unconfirmed',
            'interruptFeedbackMs': 1_200 if contact else 0,
            'interruptPlayerID': (contact.get('targetID') if contact.get('targetID') in players
                                  else contact.get('sourceID') if contact.get('sourceID') in players else None) if contact else None,
            'evidence': '厄鳞之卵 1306862 起读；1300312 接触使其停止，90 秒为读条时长',
        })
    leak_waves, leak_tethers = [], []
    for failure in (tether_review or {}).get('failures') or []:
        source, target = failure.get('sourcePosition'), failure.get('targetPosition')
        if not source or not target:
            continue
        leak_tethers.append({'startTimeMs': failure['castStartTimeMs'],
                             'endTimeMs': failure['timeMs'] + 1_000,
                             'sourceID': failure['sourceID'], 'instance': failure['sourceInstance'],
                             'position': source, 'targetID': failure['targetID'],
                             'targetInstance': failure['targetInstance'], 'targetPosition': target})
        axis = math.atan2(target['y'] - source['y'], target['x'] - source['x'])
        leak_waves.append({'timeMs': failure['timeMs'] + 1_000, 'position': target,
                           'kind': 'tether-leak', 'sourceID': failure['sourceID'],
                           'directions': [{'x': math.cos(axis + i * 2 * math.pi / 5),
                                           'y': math.sin(axis + i * 2 * math.pi / 5)} for i in range(5)],
                           'widthYards': REPLAY_WAVE_WIDTH_YARDS,
                           'speedYardsPerSecond': REPLAY_WAVE_SPEED_YARDS_PER_SECOND,
                           'travelYards': REPLAY_WAVE_TRAVEL_YARDS,
                           'travelEvidence': 'visual-model-from-missed-interception'})
    return {'auras': auras, 'hits': [{'timeMs': ts, 'playerID': pid} for ts, pid in sorted(hits)],
            'events': sorted(changes, key=lambda row: row['timeMs']), 'eggs': eggs,
            'eggHatchCasts': egg_hatch_casts,
            'raidImpacts': _replay_raid_impacts(fight, players, raw),
            'wardens': _replay_warden_health(fight, raw),
            # NSRT's north-up UlatekWaveLines texture is a fixed 120-degree
            # triad, rotated only by the minimap compass. This is a direction
            # warning, not a guessed projectile speed or a Boss wave path.
            'purgeDirections': ([{'x': 0, 'y': 1}, {'x': math.sqrt(3)/2, 'y': -.5},
                                 {'x': -math.sqrt(3)/2, 'y': -.5}]
                                if int(fight.get('difficulty') or 0) == 5 else []),
            **scene, **projectiles, 'waves': projectiles['waves'] + leak_waves,
            'leakTethers': leak_tethers}


def _p1_wretch_focus(fight, actor_map, players, raw, rage_windows):
    p1_end = rage_windows[0]["start"] if rage_windows else fight["endTime"]
    actors = {row.get("id"): row for row in raw.get("actorRows") or []}
    counts = defaultdict(lambda: Counter())
    for event in raw.get("friendlyCasts") or []:
        if event_type(event) != "cast" or event.get("fake") or event.get("sourceID") not in players:
            continue
        if not fight["startTime"] <= int(event.get("timestamp") or 0) < p1_end:
            continue
        target = actors.get(event.get("targetID")) or {}
        target_game = target.get("gameID")
        if target.get("type") != "NPC" or not target_game:
            continue
        counts[event["sourceID"]][int(target_game)] += 1
    rows = []
    for player_id in players:
        targets = counts[player_id]
        rows.append({**player_ref(players, actor_map, player_id),
                     "wretchCastCount": targets[BLIGHTSCALE_WRETCH_GAME_ID],
                     "otherTargetCastCount": sum(count for game_id, count in targets.items()
                                                 if game_id != BLIGHTSCALE_WRETCH_GAME_ID),
                     "otherTargets": [{"gameID": game_id,
                                       "name": next((actor.get("name") for actor in actors.values()
                                                     if actor.get("gameID") == game_id), str(game_id)),
                                       "castCount": count}
                                      for game_id, count in sorted(targets.items())
                                      if game_id != BLIGHTSCALE_WRETCH_GAME_ID]})
    return {"targetGameID": BLIGHTSCALE_WRETCH_GAME_ID,
            "p1EndTime": fmt_ms(p1_end - fight["startTime"]), "players": rows,
            "targetedCastCount": sum(row["wretchCastCount"] for row in rows)}


def analyze_ulatek(fight, actor_map, players, raw):
    options = resolve_analysis_options(CONFIG_SCHEMA, raw.get("analysisOptions") or {})
    rage_windows = _rage_windows(fight, raw)
    tether_review = _analyze_tether_failures(fight, actor_map, players, raw) if options["wavesReviewEnabled"] or options["fullReplayEnabled"] else {}
    waves = _analyze_waves_and_eggs(fight, actor_map, players, raw, rage_windows) if options["wavesReviewEnabled"] else {}
    if waves:
        waves["p3Eggs"] = _analyze_p3_eggs(fight, actor_map, players, raw, rage_windows)
        wave_cutoff = _nightly_collapse(fight, players, raw, WAVE_COUNT_DEATH_THRESHOLD)
        waves["countingDeathThreshold"] = WAVE_COUNT_DEATH_THRESHOLD
        waves["countingCutoffMs"] = wave_cutoff - fight["startTime"] if wave_cutoff is not None else None
        waves["countingHits"] = [row for row in waves["hits"]
                                 if wave_cutoff is None or fight["startTime"] + row["timeMs"] < wave_cutoff]
        waves["countingDutyWaveHits"] = [row for row in waves["dutyWaveHits"]
                                         if wave_cutoff is None or fight["startTime"] + row["timeMs"] < wave_cutoff]
        spine_first = {}
        for event in raw.get("debuffs") or []:
            if (ability_id(event) == PETRIFYING_SPINE_MARK_ID
                    and event_type(event) in {"applydebuff", "refreshdebuff"}
                    and event.get("targetID") in players):
                player_id = event["targetID"]
                timestamp = int(event["timestamp"])
                key = (_wave_exemption_phase_at(timestamp, fight, raw, rage_windows), player_id)
                spine_first[key] = min(spine_first.get(key, fight["endTime"]), timestamp)
        leak_first = {}
        for row in tether_review.get("failures") or []:
            timestamp = fight["startTime"] + row["timeMs"]
            phase = _wave_exemption_phase_at(timestamp, fight, raw, rage_windows)
            leak_first[phase] = min(leak_first.get(phase, fight["endTime"]), timestamp)
        waves["waveExclusions"] = []
        for hit in waves["countingHits"]:
            timestamp = fight["startTime"] + hit["timeMs"]
            phase = _wave_exemption_phase_at(timestamp, fight, raw, rage_windows)
            reasons = []
            if spine_first.get((phase, hit["playerID"]), fight["endTime"]) < timestamp:
                reasons.append("此前获得石化钉刺预兆")
            if leak_first.get(phase, fight["endTime"]) < timestamp:
                reasons.append("此前坦克漏线")
            if reasons:
                waves["waveExclusions"].append({**hit, "reason": "、".join(reasons)})
        if options["cleanWaveReviewEnabled"]:
            waves["cleanWaveHits"] = _clean_wave_hits(fight, players, raw, waves, tether_review)
    result = {
        "progression": _progression_phase(fight, raw),
        "wavesAndEggs": waves,
        "tankInterception": tether_review,
        "mythicWretch": _analyze_mythic_wretch(fight, actor_map, players, raw) if options["wavesReviewEnabled"] else {},
        "rage": _analyze_rage(fight, actor_map, players, raw, rage_windows) if options["rageReviewEnabled"] else {},
        "fangs": _analyze_fangs(fight, actor_map, players, raw, options["fangSafeStacks"]) if options["fangsReviewEnabled"] else {},
        "p1WretchFocus": _p1_wretch_focus(fight, actor_map, players, raw, rage_windows),
        "critical": _analyze_critical(fight, actor_map, players, raw) if options["criticalReviewEnabled"] else {},
    }
    if options['fullReplayEnabled'] and not raw.get('_nightlyPass'):
        result['replayFeedback'] = _replay_feedback(fight, players, raw, tether_review)

    if not raw.get("_nightlyPass"):
        cutoff = _nightly_collapse(fight, players, raw)
        result["nightlyExemption"] = {"threshold": 8, "active": cutoff is not None,
                                     "timeMs": cutoff - fight["startTime"] if cutoff is not None else None,
                                     "time": fmt_ms(cutoff - fight["startTime"]) if cutoff is not None else None,
                                     "reason": "本场死亡人数首次达到8人，此时及之后的记录不计整晚统计；单场保留供复盘，战复后不恢复本场计数。"}
        if cutoff is not None:
            limited = {key: [e for e in value if not isinstance(e, dict) or "timestamp" not in e or int(e["timestamp"]) < cutoff]
                       if isinstance(value, list) else value for key, value in raw.items()}
            limited["_nightlyPass"] = True
            result["nightlyReview"] = analyze_ulatek({**fight, "endTime": cutoff, "kill": False}, actor_map, players, limited)
    return result


analyze_mechanics = analyze_ulatek


def _mechanic_overview(rendered):
    wave_hits = []
    clean_wave_hits = []
    clean_wave_enabled = False
    egg_hits = []
    wave_exclusions = []
    egg_duties, egg_roster = [], {}
    egg_steals, tank_failures = [], []
    p1_wave_deaths = []
    p3_wave_deaths = []
    wrong_breaks = []
    coiled_prey_deaths = []
    focus_deaths = []
    melee_events = []
    melee_damage = 0
    mother_wrath_failures = []
    p25_egg_deaths, egg_collisions = [], []
    for pull in rendered:
        full_mechanics = pull.get(BOSS_CONFIG["key"]) or {}
        mechanics = full_mechanics.get("nightlyReview") or full_mechanics
        waves = mechanics.get("wavesAndEggs") or {}
        if "cleanWaveHits" in waves:
            clean_wave_enabled = True
        for row in waves.get("cleanWaveHits") or []:
            clean_wave_hits.append(nightly_detail(pull, row["time"],
                f"{row['player']}：有效中波受击", player=row["player"],
                classColor=row.get("classColor"), spellID=WAVE_ID))
        for row in waves.get("stolenCarries") or []:
            detail = "、".join(row.get("failureKinds") or [])
            egg_steals.append(nightly_detail(pull, row["time"],
                f"{row['player']}：第 {row['round']} 轮抢蛋" + (f"，{detail}" if detail else ""),
                player=row["player"], playerID=row["playerID"], classColor=row.get("classColor"),
                spellID=MYTHIC_EGG_CARRY_ID, earlyHatch=bool(row.get("earlyHatch")),
                failureKinds=row.get("failureKinds") or []))
        for row in waves.get("eggCollisions") or []:
            left, right = row["players"]
            egg_collisions.append(nightly_detail(
                pull, row["time"],
                f"{row['phase']} 阶段，{left['player']} 和 {right['player']} 撞蛋",
                phase=row["phase"], players=row["players"],
                distanceYards=row["distanceYards"], splashTime=row.get("splashTime"),
                evidence=row["evidence"], spellID=EGG_COLLISION_SPLASH_ID if row.get("splashSpellID") else EGG_CARRY_ID))
        for row in (mechanics.get("tankInterception") or {}).get("failures") or []:
            tank_failures.append(nightly_detail(pull, row["time"],
                f"{row.get('player') or '责任坦克未确定'}：毒性孵化接线不足 {row['tickCount']}/5 跳",
                player=row.get("player"), classColor=row.get("classColor"),
                spellID=TOXIC_INCUBATION_CAST_ID, tickCount=row["tickCount"],
                attribution=row.get("attribution")))
        for player in waves.get("dutyPlayers", []):
            egg_roster[player["player"]] = player
        for row in waves.get("dutyCarries", []):
            egg_duties.append(nightly_detail(pull, row["time"], f"{row['player']}：{row['phase']} 领取蛇卵", player=row["player"],
                                             playerID=row["playerID"], classColor=row.get("classColor"), phase=row["phase"], spellID=EGG_CARRY_ID))
        for row in waves.get("countingDutyWaveHits", waves.get("dutyWaveHits", [])):
            egg_hits.append(nightly_detail(pull, row["time"], f"{row['player']}：P1 搬蛋期间命中腐蚀浪潮",
                                           player=row["player"], classColor=row.get("classColor"), spellID=WAVE_ID))
        for row in waves.get("waveExclusions") or []:
            wave_exclusions.append(nightly_detail(pull, row["time"],
                f"{row['player']}：中波可排除（{row['reason']}）",
                player=row["player"], classColor=row.get("classColor"), reason=row["reason"]))
        egg_review = (mechanics.get("critical") or {}).get("p25Eggs") or {}
        for row in egg_review.get("deaths", []):
            p25_egg_deaths.append(nightly_detail(
                pull, row["time"], f"{row['player']}：P2.5 连续分摊期间带蛋死亡",
                player=row["player"], playerID=row["playerID"], classColor=row.get("classColor"),
                spellID=EGG_CARRY_ID, isPlayerMistake=False))
        for row in (mechanics.get("wavesAndEggs") or {}).get("countingHits", waves.get("hits", [])):
            event = nightly_detail(
                pull,
                row.get("time"),
                f"{row.get('player') or '未知玩家'} 命中腐蚀浪潮",
                player=row.get("player"),
                classColor=row.get("classColor"),
                spellID=WAVE_ID,
            )
            wave_hits.append(event)
        for row in (((mechanics.get("wavesAndEggs") or {}).get("waveDeaths") or {}).get("events") or []):
            event = nightly_detail(
                pull,
                row.get("deathTime"),
                f"{row.get('player')} 在 {row.get('phase')} 中波后 1 秒内死亡（{row.get('ability')}）",
                player=row.get("player"),
                classColor=row.get("classColor"),
                spellID=row.get("abilityID"),
                waveTime=row.get("waveTime"),
                delayMs=row.get("delayMs"),
            )
            if row.get("phase") == "P1":
                p1_wave_deaths.append(event)
            elif row.get("phase") == "P3":
                p3_wave_deaths.append(event)
        for fang_round in (mechanics.get("fangs") or {}).get("rounds") or []:
            for row in fang_round.get("breaks") or []:
                if not row.get("wrong"):
                    continue
                wrong_breaks.append(nightly_detail(
                    pull,
                    row.get("time"),
                    f"{row.get('player')} 拉断超出安全层数：{'、'.join(row.get('violationReasons') or ['未知原因'])}",
                    player=row.get("player"),
                    classColor=row.get("classColor"),
                    spellID=BLIGHT_VEIN_ID,
                ))
        for row in (((mechanics.get("critical") or {}).get("coiledPreyDeaths") or {}).get("deaths") or []):
            coiled_prey_deaths.append(nightly_detail(
                pull,
                row.get("time"),
                f"{row.get('player')} 死于盘绕猎物",
                player=row.get("player"),
                classColor=row.get("classColor"),
                spellID=1301510,
            ))
        focus = (mechanics.get("critical") or {}).get("platform2To3") or {}
        for row in focus.get("deaths") or []:
            status = "已开个人减伤" if row.get("usedPersonalDefensive") else "未记录个人减伤"
            focus_deaths.append(nightly_detail(
                pull,
                row.get("time"),
                f"{row.get('player')} 在第2→第3平台流程死亡（{status}）",
                player=row.get("player"),
                classColor=row.get("classColor"),
                spellID=row.get("abilityID"),
                usedPersonalDefensive=bool(row.get("usedPersonalDefensive")),
                usedHealthstone=bool(row.get("usedHealthstone")),
                usedHealingPotion=bool(row.get("usedHealingPotion")),
            ))
        melee = (mechanics.get("critical") or {}).get("nonTankMelee") or {}
        melee_damage += int(melee.get("totalDamage") or 0)
        for player_row in melee.get("players") or []:
            for event in player_row.get("events") or []:
                melee_events.append(nightly_detail(
                    pull,
                    event.get("time"),
                    f"{player_row.get('player')} 被 {event.get('source')} 近战攻击",
                    player=player_row.get("player"),
                    classColor=player_row.get("classColor"),
                    spellID=1,
                    amount=event.get("amount"),
                    source=event.get("source") or "未知生物",
                ))
        wrath = (mechanics.get("critical") or {}).get("motherWrath") or {}
        for row in wrath.get("failures") or []:
            receiver = row.get("receiver") or {}
            receiver_name = receiver.get("player") or "未解析目标"
            mother_wrath_failures.append(nightly_detail(
                pull,
                row.get("time"),
                f"蛇母之怒触发全团伤害；当轮承接目标：{receiver_name}",
                player=receiver.get("player"),
                classColor=receiver.get("classColor"),
                spellID=1298367,
                affectedCount=row.get("affectedCount"),
                totalDamage=row.get("totalDamage"),
                receiverEvidence=row.get("receiverEvidence"),
            ))
    carry_totals = {row["player"]: row["count"] for row in nightly_player_totals(egg_duties)}
    hit_totals = {row["player"]: row["count"] for row in nightly_player_totals(egg_hits)}
    all_wave_totals = {row["player"]: row["count"] for row in nightly_player_totals(wave_hits)}
    exclusion_totals = {row["player"]: row["count"] for row in nightly_player_totals(wave_exclusions)}
    egg_players = []
    for name, player in egg_roster.items():
        carries, hits = carry_totals.get(name, 0), hit_totals.get(name, 0)
        egg_players.append({**player, "count": hits, "carryCount": carries, "waveHitCount": hits,
                            "totalWaveHitCount": all_wave_totals.get(name, 0),
                            "excludableCount": exclusion_totals.get(name, 0),
                            "dutyFilterEligible": player.get("role") in {"melee-dps", "range-dps", "ranged-dps", "dps"}})
    egg_players.sort(key=lambda row: (-row["carryCount"], -row["waveHitCount"], row["player"]))
    stolen_players = nightly_player_totals(egg_steals)
    for player in stolen_players:
        player["failedCount"] = sum(bool(event.get("earlyHatch")) for event in egg_steals
                                    if event.get("player") == player["player"])
    melee_players = nightly_player_totals(melee_events)
    for player in melee_players:
        sources = Counter(e["source"] for e in melee_events if e.get("player") == player["player"])
        player["countBreakdown"] = [{"label": source, "count": count} for source, count in sources.most_common()]
    return {
        "title": "整夜机制统计",
        "subtitle": "按全部乌拉特克 Pull 汇总中波、搬蛋与抢蛋、接线、P1/P3 死亡及关键流程；原始中波受击不直接判定玩家失误。",
        "metrics": [
            {"key": "eggSteals", "label": "抢蛋与提前孵化", "value": len(egg_steals), "unit": "次",
             "tone": "danger", "description": "指定搬蛋组满 8 人时，其他玩家领取蛇卵才计抢蛋；同一栏标出中波或疑似碰蛋提前孵化。",
             "summaryColumns": [{"key": "count", "label": "抢蛋次数"},
                                {"key": "failedCount", "label": "同时提前孵化"}],
             "players": stolen_players, "events": egg_steals, "detailTab": "waves"},
            {"key": "tankTetherFailures", "label": "毒性孵化漏接", "value": len(tank_failures), "unit": "次",
             "tone": "danger", "description": "虚影完成施法且有足够观察时间，但未记录满 5 跳坦克接线；优先按实际承接跳数归责，零跳时仅在坦克位置明显可区分时推定。",
             "players": nightly_player_totals(tank_failures), "events": tank_failures,
             "detailTab": "waves"},
            *([{"key": "cleanWaveHits", "label": "有效中波受击", "value": len(clean_wave_hits), "unit": "次",
                "tone": "warning", "description": "仅统计同阶段首次可确认漏接之前、且团队同时死亡人数未达到 2 人时的受击；跨阶段重新计算漏接豁免。",
                "players": nightly_player_totals(clean_wave_hits), "events": clean_wave_hits,
                "detailTab": "waves"}] if clean_wave_enabled else []),
            {"key": "p25EggDeaths", "label": "P2.5 带蛋死亡", "value": len(p25_egg_deaths), "unit": "人次",
             "tone": "warning", "players": nightly_player_totals(p25_egg_deaths), "events": p25_egg_deaths},
            {"key": "eggCollisions", "label": "撞蛋", "value": len(egg_collisions), "unit": "次",
             "tone": "danger", "description": "两名玩家同帧失去携蛋并出现孵化；没有已孵化蝰蛇时，剧毒喷溅同帧命中双方可确认撞蛋，可靠坐标相距不超过 4 码也可确认。P2 同样适用，事件列出双方姓名。",
             "events": egg_collisions, "detailTab": "waves"},
            {
                "key": "waveHits",
                "label": "中波施加/刷新次数",
                "value": len(wave_hits),
                "unit": "次",
                "tone": "warning",
                "players": nightly_player_totals(wave_hits),
                "events": wave_hits,
            },
            {
                "key": "p1WaveDeaths",
                "label": "P1 吃波死亡",
                "value": len(p1_wave_deaths),
                "unit": "人次",
                "tone": "danger",
                "players": nightly_player_totals(p1_wave_deaths),
                "events": p1_wave_deaths,
            },
            {
                "key": "p3WaveDeaths",
                "label": "P3 吃波死亡",
                "value": len(p3_wave_deaths),
                "unit": "人次",
                "tone": "danger",
                "players": nightly_player_totals(p3_wave_deaths),
                "events": p3_wave_deaths,
            },
            {
                "key": "eggCarrierWaveHits",
                "label": "P1 搬蛋任务与中波",
                "value": len(egg_hits),
                "unit": "次",
                "tone": "danger",
                "description": f"今晚共带蛋 {len(egg_duties)} 次。中波在团队同时死亡达到 {WAVE_COUNT_DEATH_THRESHOLD} 人时停止计数；同一玩家 750 毫秒内的带蛋中波合并一次。石化钉刺预兆或团队漏线只影响同阶段后续中波的可排除次数。",
                "carryCount": len(egg_duties),
                "summaryColumns": [{"key": "carryCount", "label": "搬蛋次数"}, {"key": "totalWaveHitCount", "label": "总中波次数"}, {"key": "waveHitCount", "label": "期间中波次数"}, {"key": "excludableCount", "label": "可排除次数"}],
                "summaryFilter": {"key": "carryCount", "label": "仅显示搬蛋次数少于", "defaultThreshold": 10,
                                  "totalKey": "totalWaveHitCount", "totalLabel": "总中波次数",
                                  "eligibilityKey": "dutyFilterEligible", "description": "仅统计输出玩家，排除治疗和坦克。"},
                "players": egg_players,
                "events": egg_hits + egg_duties + wave_exclusions,
            },
            {
                "key": "wrongFangBreaks",
                "label": "拉断超出安全层数",
                "value": len(wrong_breaks),
                "unit": "次",
                "tone": "danger",
                "players": nightly_player_totals(wrong_breaks),
                "events": wrong_breaks,
            },
            {
                "key": "coiledPreyDeaths",
                "label": "死于盘绕猎物",
                "value": len(coiled_prey_deaths),
                "unit": "人次",
                "tone": "danger",
                "players": nightly_player_totals(coiled_prey_deaths),
                "events": coiled_prey_deaths,
            },
            {
                "key": "platform2To3Defensives",
                "label": "第2→第3平台死亡减伤检查",
                "value": len(focus_deaths),
                "unit": "人次",
                "tone": "warning",
                "players": nightly_player_totals(focus_deaths),
                "events": focus_deaths,
            },
            {
                "key": "nonTankMelee",
                "label": "非坦克被近战攻击",
                "value": len(melee_events),
                "unit": "次",
                "tone": "danger",
                "totalDamage": melee_damage,
                "players": melee_players,
                "countBreakdownLabel": "攻击生物与次数",
                "events": melee_events,
            },
            {
                "key": "motherWrathRaidwide",
                "label": "蛇母之怒 A 团",
                "value": len(mother_wrath_failures),
                "unit": "次",
                "tone": "danger",
                "players": nightly_player_totals(mother_wrath_failures),
                "events": mother_wrath_failures,
            },
        ],
    }


def build_aggregated_json(report_ids, options=None):
    options = resolve_analysis_options(CONFIG_SCHEMA, options or {})
    config = deepcopy(BOSS_CONFIG)
    config['fetchCombatReplay'] = options['fullReplayEnabled']
    config['fetchUnifiedEvents'] = options['fullReplayEnabled']
    if options['fullReplayEnabled']:
        aura_ids = sorted(set(ULATEK_SPELL_NAMES) | {DEVOURERS_SPAWN_SHELL_ID} | set(BURST_POTIONS))
        config['unifiedEventFilter'] = ('resources.actor.id > 0 OR '
            'type IN ("damage", "cast", "begincast", "combatantinfo", "death", "resurrect", "interrupt") '
            'OR ability.id IN (' + ', '.join(map(str, aura_ids)) + ')')
        config['replayActorGameIDs'] = {ULATEK_GAME_ID, HEART_GAME_ID, 259555, 267418,
            264045, 269200, DEVOURERS_SPAWN_GAME_ID, BLIGHTSCALE_SHRIEKER_GAME_ID, 261915, 267679,
            263942, 263535} | REPLAY_EGG_GAME_IDS
        config['replayActorNames'] = {'Ravenous Doomscale'}
    config['features']['fieldReplay'] = options['fullReplayEnabled']
    config["trackedDamageTargetGameIDs"] = set()
    if options["rageReviewEnabled"]:
        config["trackedDamageTargetGameIDs"].update({ULATEK_GAME_ID, HEART_GAME_ID})
    if options["wavesReviewEnabled"]:
        config["trackedDamageTargetGameIDs"].add(DEVOURERS_SPAWN_GAME_ID)
    config["trackedActorGameIDs"] = {BLIGHTSCALE_SHRIEKER_GAME_ID, BLIGHTSCALE_VIPER_GAME_ID} if options["wavesReviewEnabled"] else set()
    critical = lambda key: _critical_enabled(options, key)
    spatial = options["wavesReviewEnabled"] or options["fangsReviewEnabled"] or critical("serpentBitesReviewEnabled")
    config["fetchPositionResources"] = spatial
    config["fetchEventResources"] = spatial
    config["fetchCastResources"] = spatial
    config["fetchTrackedActorResources"] = spatial
    config["fetchKeys"] = {"friendlyCasts", "deaths", "combatants"}
    if options['fullReplayEnabled']:
        config['fetchKeys'].update({'casts', 'damage', 'debuffs', 'enemyBuffs'})
    if options["wavesReviewEnabled"] or options["rageReviewEnabled"]:
        config["fetchKeys"].update({"casts", "damage", "debuffs", "enemyBuffs"})
    if options["rageReviewEnabled"]:
        config["fetchKeys"].add("friendlyBuffs")
    if options["fangsReviewEnabled"]:
        config["fetchKeys"].update({"casts", "debuffs"})
    for key, streams in {
        "maliceReviewEnabled": {"casts"}, "meleeReviewEnabled": {"damage"},
        "motherWrathReviewEnabled": {"casts", "damage"}, "platformReviewEnabled": {"casts"},
        "serpentBitesReviewEnabled": {"casts", "debuffs"},
        "p25EggsReviewEnabled": {"casts", "debuffs", "enemyBuffs", "damage"},
    }.items():
        if critical(key):
            config["fetchKeys"].update(streams)
    has_analysis = any(options[k] for k in ("wavesReviewEnabled", "rageReviewEnabled", "fangsReviewEnabled")) or any(critical(k) for k in CRITICAL_FIELDS)
    config["trackedActorEventFilters"] = ['type = "resurrect"'] if has_analysis else []
    if options["wavesReviewEnabled"]:
        config["trackedActorEventFilters"].append(f"source.id = {BLIGHTSCALE_SHRIEKER_GAME_ID}")
        config["trackedActorEventFilters"].append(
            f"(source.id = {BLIGHTSCALE_VIPER_GAME_ID} OR target.id = {BLIGHTSCALE_VIPER_GAME_ID})")
    if not {"casts", "enemyBuffs"}.issubset(config["fetchKeys"]):
        config["trackedActorEventFilters"].append(
            '(ability.id = 1286860 OR ability.id = 1299010 OR ability.id = 1295905 OR ability.id = 1315341) '
            'AND (type = "applybuff" OR type = "removebuff" OR type = "cast" OR type = "begincast")')
    config["skippedAnalyses"] = [field["label"] for field in CONFIG_SCHEMA
                                 if field["type"] == "boolean" and field["key"] != "cleanWaveReviewEnabled"
                                 and not options[field["key"]]]
    config["tabs"] = [row for row in config["tabs"] if row[0] == "survival" or options[{"replay":"fullReplayEnabled", "waves":"wavesReviewEnabled", "heart":"rageReviewEnabled", "fangs":"fangsReviewEnabled", "critical":"criticalReviewEnabled"}[row[0]]]]
    result = _build(config, analyze_mechanics, report_ids, options)
    for pull in result.get("data", {}).get("page1_wipeAnalysis") or []:
        restore_progression(pull)
    result["meta"]["courtProfile"] = COURT_PROFILE
    result["data"]["mechanicOverview"] = _mechanic_overview(
        result.get("data", {}).get("page1_wipeAnalysis") or []
    )
    metric_options = {
        "eggSteals": "wavesReviewEnabled", "tankTetherFailures": "wavesReviewEnabled",
        "cleanWaveHits": "cleanWaveReviewEnabled",
        "p25EggDeaths": "p25EggsReviewEnabled", "eggCollisions": "wavesReviewEnabled",
        "waveHits": "wavesReviewEnabled", "p1WaveDeaths": "wavesReviewEnabled", "p3WaveDeaths": "wavesReviewEnabled", "eggCarrierWaveHits": "wavesReviewEnabled",
        "wrongFangBreaks": "fangsReviewEnabled", "platform2To3Defensives": "platformReviewEnabled",
        "coiledPreyDeaths": "coiledPreyReviewEnabled", "nonTankMelee": "meleeReviewEnabled", "motherWrathRaidwide": "motherWrathReviewEnabled",
    }
    result["data"]["mechanicOverview"]["metrics"] = [
        row for row in result["data"]["mechanicOverview"]["metrics"] if (_critical_enabled(options, metric_options[row["key"]]) if metric_options[row["key"]] in CRITICAL_FIELDS else options[metric_options[row["key"]]])
    ]
    return result


def analyze(report_ids, output_path=None, catalog_entry=None, options=None, progress_callback=None):
    return write_json_result(
        build_aggregated_json(report_ids, options), output_path, catalog_entry=catalog_entry
    )
