"""Evidence-first analyzer for The Coiled Altar / 盘卷祭坛 (12.1 heroic)."""

from __future__ import annotations
from analyzer_core.combat_replay import fetch_replay_events, build_replay_tracks

from analyzer_core.config import resolve_analysis_options
from analyzer_core.analysis_profile import profile_schema, resolve_profile
from analyzer_core.player_abilities import load_player_ability_catalog

CONFIG_SCHEMA = profile_schema([
    {"key": "toxicDelugeReviewEnabled", "type": "boolean", "label": "剧毒洪流与毒液搬运", "default": True},
    {"key": "severReviewEnabled", "type": "boolean", "label": "撕裂清场", "default": True},
    {"key": "guillotineReviewEnabled", "type": "boolean", "label": "处斩分摊与跑离", "default": True},
    {"key": "dreadmarchReviewEnabled", "type": "boolean", "label": "恐惧行军与救人", "default": True},
    {"key": "manifestationsReviewEnabled", "type": "boolean", "label": "恐惧具象与凝视", "default": True},
    {"key": "soulSeverReviewEnabled", "type": "boolean", "label": "灵魂撕裂", "default": True},
    {"key": "gloombombReviewEnabled", "type": "boolean", "label": "幽暗炸弹分散", "default": True},
    {"key": "graveboundReviewEnabled", "type": "boolean", "label": "墓缚致死", "default": True},
    {"key": "eternalNightfallReviewEnabled", "type": "boolean", "label": "永恒夜幕破盾与打断", "default": True},
    {"key": "blightedSeverReviewEnabled", "type": "boolean", "label": "凋零撕裂", "default": True},
    {"key": "grimGuillotineReviewEnabled", "type": "boolean", "label": "冷酷处斩", "default": True},
    {"key": "fieldReplayEnabled", "type": "boolean", "label": "场地推演", "default": True, "expensive": True,
     "description": "为已选机制生成场地示意图。关闭后跳过制图；撕裂等位置判定仍会保留自身所需坐标与毒液、具象证据。"},
    {"key": "intermissionReviewEnabled", "type": "boolean", "label": "转阶段残片、治疗与输出复盘", "default": True,
     "description": "关闭后跳过转阶段治疗、Boss 承伤及药水光环取证。"},
    {"key": "guildTimelineEnabled", "type": "boolean", "label": "阿瓦隆停手与爆发轴检查", "default": True,
     "description": "仅对日志归属阿瓦隆的史诗场次执行；先检查提前转阶段，再检查爆发安排。"},
    {"key": "p1EarliestEndSeconds", "type": "number", "label": "P1 最早结束时间（秒）", "default": 170, "min": 170, "max": 600,
     "description": "P1 须完成约 2:42 的末轮撕裂，且至少打到 2:50；首次恐惧行军还须在 3:05 或之后开始读条。"},
    {"key": "firstDreadmarchEarliestSeconds", "type": "number", "label": "首次恐惧行军最早读条（秒）", "default": 185, "min": 185, "max": 600},
    {"key": "p1HoldUntilSeconds", "type": "number", "label": "P1 停手统计截止（秒）", "default": 165, "min": 0, "max": 600,
     "description": "统计 Boss 首次低于所选血量阈值后至 2:45 之前的玩家施法与含宠物伤害；2:45 起恢复输出不计入。此项不修改原 2:50 最早转阶段判定。"},
    {"key": "p2LastBladeOffsetSeconds", "type": "number", "label": "P2 最后一刀距 P2 开始（秒）", "default": 202.790, "min": 0, "max": 600,
     "description": "旧 M 击杀样本 6:26.052 − 3:03.262；随本场 P2 起点平移，并由首刀实测延迟校正，须有末轮刀完成事件才能确认已达要求。"},
    {"key": "burstWindowSeconds", "type": "number", "label": "爆发时间容差（秒）", "default": 10, "min": 0, "max": 30},
    {"key": "burstPlan", "type": "text", "multiline": True, "label": "爆发安排 JSON（留空使用截图预设）", "default": "",
     "description": "数组，每项含 player（角色名或 actor ID）、ability（公共技能目录 key）、times（开战后秒数，可用 [开始,结束] 指定区间）。饰品可单独用 spellIDs 数组与 label 填写确认的准确技能；可选 durationSeconds 仅作持续时间示意。未解析技能不会计错。"},
])

import math
from collections import Counter, defaultdict
from bisect import bisect_right
from pathlib import Path
from datetime import datetime, timedelta, timezone

from analyzer_core.analysis_scope import filter_fights
from analyzer_core.concurrency import run_parallel_indexed
from analyzer_core.progress import emit_progress
from analyzer_core.wcl_api import WclClient, encounter_phase_metadata, fight_phase_start_ms
from analyzer_core.wcl_report_ids import parse_wcl_report_ids
from boss_plugins.assets.icons import get_boss_icon_path
from boss_plugins.common import COMBAT_RES_SPELLS, role_to_basic, write_json_result
from boss_plugins.venomous_abyss.shared import (
    ability_id,
    actor_name,
    build_player_catalog,
    build_position_index,
    build_survival_timeline,
    difficulty_fields,
    event_amount,
    event_point,
    event_type,
    fmt_ms,
    group_nearby,
    load_confirmed_spell_names,
    nightly_detail,
    nightly_player_totals,
    player_ref,
    position_actor_id,
    position_at,
    position_at_interpolated,
    resolve_boss_actor_id,
    spell_name,
)


ENCOUNTER_ID = 3429
ENCOUNTER_IDS = {ENCOUNTER_ID, 53429}
CN_TZ = timezone(timedelta(hours=8))
ARENA_IMAGE = "assets/raids/venomous_abyss/07-coiledaltar.jpg"
# 07-coiledaltar.jpg 为 1997×1118；图中正方形石台边长约 1036px。
# WCL 与本团其他 Boss 一致：事件 x/y = 码 × 100。石台边长 110 码，中心 (0, 1158) 码。
# 旧标定把 110 单位当成 86 码，15 码圈会大 28%，距离判定也会偏松。
ARENA_IMAGE_WIDTH = 1997
ARENA_IMAGE_HEIGHT = 1118
ARENA_SQUARE_PX = 1036
ARENA_SIDE_YARDS = 110.0
ARENA_SIDE_UNITS = ARENA_SIDE_YARDS
ARENA_HALF_SIDE_UNITS = ARENA_SIDE_UNITS / 2.0
ARENA_HALF_SIDE_YARDS = ARENA_SIDE_YARDS / 2.0
ARENA_CENTER_X_UNITS = 0.0
ARENA_CENTER_Y_UNITS = 1158.0
ARENA_CENTER_X_YARDS = ARENA_CENTER_X_UNITS
ARENA_CENTER_Y_YARDS = ARENA_CENTER_Y_UNITS
WCL_COORD_SCALE = 100.0
WCL_UNITS_PER_YARD = WCL_COORD_SCALE
# plotScale 表示「中心到正方形直角边」占示意图宽/高的百分比，故 X/Y 不同以保持圆形半径为正圆。
ARENA_PLOT_SCALE_X = round((ARENA_SQUARE_PX / 2) / ARENA_IMAGE_WIDTH * 100, 4)
ARENA_PLOT_SCALE_Y = round((ARENA_SQUARE_PX / 2) / ARENA_IMAGE_HEIGHT * 100, 4)

SPELLS = load_confirmed_spell_names()
SPELLS.update({
    1243002: "死亡进军",
    1236616: "圣光潜力",
    1236994: "鲁莽药水",
    1282403: "凝结毒液",
    1282408: "凝结毒液",
    1282419: "不稳定毒液",
    1283485: "处斩",
    1283489: "处斩",
    1283594: "处斩",
    1283623: "寡妇之吻",
    1283631: "寡妇之触",
    1285643: "恐惧行军",
    1285847: "坚不可摧",
    1285911: "凝视",
    1286620: "灵魂撕裂",
    1286837: "墓缚",
    1286895: "幽暗炸弹",
    1286912: "永恒夜幕护盾",
    1286918: "永恒夜幕",
    1310752: "永恒夜幕",
    1287718: "收回精华",
    1287722: "灵魂抹除",
    1289798: "灵魂绑定",
    1295132: "液态光泽",
    1297445: "恐惧行军",
    1297906: "墓缚",
    1312424: "无能之辈",
    1285017: "碎斧",
    1283290: "剧毒之地",
    1288635: "恐惧威仪",
    1298795: "腐化毒素",
    1299266: "冷酷处斩",
    1299267: "冷酷处斩",
    1299396: "死亡之拥",
    1299401: "死亡低语",
    1299684: "撕裂",
    1299838: "毒液爆裂",
    1299960: "剧毒洪流",
    1301690: "撕裂",
    1304032: "灵魂绑定",
    1304033: "幽魂再生",
    1307184: "恐惧箭",
    1307279: "枯萎之刃",
    1307292: "凋零撕裂",
    1307403: "凋零撕裂",
    1307425: "处斩",
    1307652: "冷酷处斩",
    1307959: "灵魂撕裂",
    1310732: "恶毒共鸣",
    1310744: "恶毒共鸣",
    1310881: "幽暗炸弹",
    1310882: "幽暗炸弹",
    1310883: "幽暗炸弹",
    1312132: "恶毒共鸣",
    1310498: "诱变毒液",
    1310544: "烈毒变异体",
    1310691: "诱变毒液",
    1286399: "恐惧哀嚎",
    1286441: "精魂狂笑",
    1308011: "恐惧哀嚎",
    1309105: "灵魂之盾",
})

TOXIC_DELUGE = 1299960
COALESCED_VENOM_CAST = 1282403
COALESCED_VENOM_DAMAGE = 1282408
VOLATILE_VENOM = 1282419
# 史诗：烈毒变异体（召唤 NPC）与拾取后的诱变毒液。1310691 多为伤害，光环常见 1310498。
VIRULENT_MUTATION_CAST = 1310544
VIRULENT_MUTATION_NPC_GAME_ID = 271982
MUTAGENIC_VENOM_AURA_IDS = {1310498, 1310691}
MUTAGENIC_VENOM_DAMAGE = 1310691
VENOM_KIND_NORMAL = "normal"
VENOM_KIND_MUTATION = "virulent-mutation"
VIRULENT_BLAST_RADIUS_YARDS = 8.0
VENOM_CARRY_AURA_IDS = {VOLATILE_VENOM} | MUTAGENIC_VENOM_AURA_IDS
VENOM_SPAWN_CAST_IDS = {COALESCED_VENOM_CAST, VIRULENT_MUTATION_CAST}
# 掉落后短时间内再被捡起 → 视为接力搬运，中间落点不算「场上凝结毒液」。
VENOM_TRANSFER_WINDOW_MS = 1_500
# 游戏内毒液球拾取约 3 码；匹配阈值略放宽以吸收 WCL 坐标采样误差。
VENOM_PICKUP_MAX_YARDS = 4.0
SEVER_IDS = {1299684}
BLIGHTED_SEVER_IDS = {1307292}
CONE_SEVER_IDS = SEVER_IDS | BLIGHTED_SEVER_IDS
SOUL_SEVER_IDS = {1286620}
# 坦克易伤 / 结算 debuff：朝向按施加时刻（≈读条末秒）的坦克位置锁定。
SEVER_TANK_DEBUFF_IDS = {1301690}
BLIGHTED_SEVER_TANK_DEBUFF_IDS = {1307403}
SOUL_SEVER_TANK_DEBUFF_IDS = {1307959}
# 灵魂撕裂后判定凝视是否被清掉的观察窗口。
SOUL_SEVER_CLEAR_WINDOW_MS = 2_500
CAST_TO_TANK_DEBUFF_IDS = {
    1299684: SEVER_TANK_DEBUFF_IDS,
    1307292: BLIGHTED_SEVER_TANK_DEBUFF_IDS,
    1286620: SOUL_SEVER_TANK_DEBUFF_IDS,
}
CAST_LAST_SECOND_MS = 1_000
GUILLOTINE_CAST_IDS = {1283489}
GRIM_GUILLOTINE_CAST_IDS = {1299266, 1299267}
GUILLOTINE_DAMAGE_ID = 1283594
GRIM_GUILLOTINE_DAMAGE_IDS = {1283594, 1299266, 1299267}
GUILLOTINE_MARK = 1307425
GRIM_GUILLOTINE_MARK_IDS = {1307425, 1307652}
# P1 处斩后：全团寡妇之触；仍在分摊点 40 码内者额外吃寡妇之吻。
WIDOW_TOUCH_DAMAGE_ID = 1283631
WIDOW_KISS_DAMAGE_ID = 1283623
# P3 冷酷处斩后：全团死亡低语；范围内额外死亡之拥。
DEATH_WHISPER_DAMAGE_ID = 1299401
DEATH_EMBRACE_DAMAGE_ID = 1299396
# 分摊后查找脉冲/范围内伤害的最长等待；不再用固定秒数估位置。
GUILLOTINE_PULSE_SEARCH_MS = 25_000
GUILLOTINE_PULSE_MATCH_MS = 1_500
GUILLOTINE_RANGE_YARDS = 40
VENOM_RUPTURE = 1299838
FIXATION = 1285911
MANIFEST_NPC_GAME_ID = 261218
MANIFEST_CAST = 1290316
DREADMARCH_CAST_IDS = {1285643, 1243002}
DREADMARCH_DEBUFF_IDS = {1297445}
# 具象碰撞结果（仅史诗：恶毒共鸣 Malevolent Resonance）；英雄不做该证据。
MANIFEST_COLLISION_DEBUFF_IDS = {1310732, 1310744, 1312132}
# Boss 点名波次：施法后短窗口内的施加视为初始心控，而非撞具象。
DREADMARCH_INITIAL_APPLY_MS = 5_000
DREADMARCH_FIXATION_HINT_MS = 3_000
GLOOMBOMB_CAST_IDS = {1286895, 1310882}
GLOOMBOMB_DEBUFF_IDS = {1310881}
# 1310883 为实际爆炸伤害（盾碎 / shield cracked）；其它 ID 仅作回退。
GLOOMBOMB_EXPLODE_DAMAGE_IDS = {1310883}
GLOOMBOMB_DAMAGE_IDS = GLOOMBOMB_CAST_IDS | GLOOMBOMB_DEBUFF_IDS | GLOOMBOMB_EXPLODE_DAMAGE_IDS
GRAVEBOUND_IDS = {1286837, 1308330}
GRAVEBOUND_DEBUFF_IDS = {1286837}
# 墓缚伤害（拉取 DamageTaken）；致死只认 1297906 的 killing blow。
GRAVEBOUND_DAMAGE_IDS = {1308330, 1297906, 1286837}
GRAVEBOUND_KILL_ID = 1297906
# 炸弹爆炸后短窗口内的 1286837 施加，视为本次幽暗炸弹溅射。
GLOOMBOMB_GRAVEBOUND_WINDOW_MS = 2_000
# 点名圈只认该玩家吃到幽暗炸弹伤害前后 100ms 内的坐标。
GLOOMBOMB_APPLY_TYPES = {"applydebuff", "applybuff", "applydebuffstack", "applybuffstack"}
GLOOMBOMB_REMOVE_TYPES = {"removedebuff", "removebuff"}
GLOOMBOMB_STACK_REMOVE_TYPES = {"removedebuffstack", "removebuffstack"}
GLOOMBOMB_HIT_POS_WINDOW_MS = 100
# WCL 轨迹点常隔 200–400ms；±100ms 内往往没有第二点，图就不会变。爆炸时刻在两侧样本间插值。
GLOOMBOMB_INTERP_GAP_MS = 2_000
GLOOMBOMB_POSITION_MAX_OFFSET_MS = GLOOMBOMB_HIT_POS_WINDOW_MS
GLOOMBOMB_BEFORE_REMOVE_MAX_AGE_MS = 12_000
# 四人各一发施法（间隔约 0.5s）；波次按施法合并，再在窗口内收齐施加。
GLOOMBOMB_MARKS_PER_WAVE = 4
GLOOMBOMB_CAST_GAP_MS = 8_000
GLOOMBOMB_CAST_MERGE_MS = 20_000
GLOOMBOMB_WAVE_SPAN_MS = 15_000
GLOOMBOMB_APPLY_LOOKBACK_MS = 8_000
GLOOMBOMB_APPLY_WINDOW_MS = 12_000
GLOOMBOMB_LEFTOVER_ATTACH_MS = 15_000
ETERNAL_NIGHTFALL = 1286918
ETERNAL_NIGHTFALL_AURA = 1310752
VEIL_SHIELD = 1286912
# 被打断技能：读条 1286918，部分日志会把光环 1310752 记在 extraAbilityGameID。
NIGHTFALL_INTERRUPTED_SPELLS = {ETERNAL_NIGHTFALL, ETERNAL_NIGHTFALL_AURA}
# 轮次上界用下一发 begincast；没有下一发时再用这个上限，避免固定 12s 漏掉普通难度 ~14s 破盾。
NIGHTFALL_ROUND_MAX_MS = 45_000
NIGHTFALL_SHIELD_APPLY_LOOKBACK_MS = 2_000
UNASSAILABLE = 1285847
RECLAIM_ESSENCE = 1287718
SPIRIT_ERASURE = 1287722
# 踩片者易伤与伤害同 ID（1287722 applydebuff）；全团 AOE 按脉冲合并，不按承伤条数计次。
SPIRIT_ERASURE_DEBUFF_IDS = {1287722}
SPIRIT_ERASURE_WAVE_MS = 250
SPIRIT_ERASURE_STEPPER_WINDOW_MS = 500
INTERMISSION_BUFFS = {1304032, 1304033, 1304498}
P3_SOULBOUND = 1289798
POTION_LIGHTS_POTENTIAL = 1236616
POTION_RECKLESSNESS = 1236994
POTION_LIQUID_LUSTER = 1295132
INTERMISSION_POTIONS = {
    POTION_LIGHTS_POTENTIAL: "圣光潜力",
    POTION_RECKLESSNESS: "鲁莽药水",
    POTION_LIQUID_LUSTER: "液态光泽",
}
# 转阶段前预开药水也算本次爆发。
INTERMISSION_POTION_LOOKBACK_MS = 2_000

P2_SIGNAL_SPELL = 1307184
INTERMISSION_MS = 35_000
INTERMISSION_SOULBIND = 1304032
CONE_RADIUS_YARDS = 45  # Replay reach calibrated against observed clear positions and stack gains.
CONE_HALF_ANGLE_DEG = 30.0  # Preserve the 60-degree frontal angle.
MANIFEST_REPLAY_STEP_MS = 100
MANIFEST_REPLAY_SPEED_YARDS = 3.0  # Walking speed confirmed by the owner.
MANIFEST_WATCH_HALF_ANGLE_DEG = 30.0  # Owner: must look closely toward the ghost.
MANIFEST_FACING_MAX_AGE_MS = 1000
GLOOMBOMB_RADIUS_YARDS = 15
# 史诗怨毒盘魂者：灵魂之盾 2 层，需两枚幽暗炸弹；打断恐惧哀嚎会传送换位。
SPIRIT_SHIELD = 1309105
SOULCOILER_NPC_GAME_ID = 261521
SOULCOILER_BOMBS_REQUIRED = 2
SOULCOILER_EXPECTED_COUNT = 2
SOULCOILER_DEDUP_YARDS = 4.0
WAIL_OF_TERROR_IDS = {1286399, 1308011, 1286441}
SOULCOILER_INTERRUPT_LOOKBACK_MS = 5_000
SOULCOILER_RELOCATE_YARDS = 8.0
# 盘魂者取「点名施加 → 爆炸」这一段（约 5s）内、爆炸时刻或之前的最后一点，避免出生点/打断后传送。
SOULCOILER_BOMB_POS_PAD_MS = 250
CURSE_OF_TONGUES_ID = 1714
WAIL_CAST_MS = 10000
WAIL_CURSED_CAST_MS = 12000
ALTAR_FANGS_ID = 1282487
ALTAR_DEFILEMENT_ID = 1298381
ALTAR_CHANNEL_MS = 8000
ALTAR_GROUND_HOLD_MS = 15000
ALTAR_GROUND_RECEDE_MS = 24000  # Visual recession estimate; never a hit classifier.
ALTAR_GROUND_PEAK_RADII = (40, 50, 65, 80)  # Team screenshot estimate, per-phase ordinal.
ETERNAL_NIGHTFALL_CAST_MS = 15000
POSITION_RELIABLE_MS = 2_500

# Owner's cutoff is the encounter's local 2026-10-13 date, not analysis time.
TUNING_CUTOFF = datetime(2026, 10, 13, tzinfo=timezone(timedelta(hours=8)))
TUNING_SOURCE = 'https://us.forums.blizzard.com/en/wow/t/dungeon-and-raid-tuning-october-13/2380514'


def encounter_tuning(fight):
    report_start = fight.get('reportStartTime')
    absolute = int(report_start)+int(fight['startTime']) if report_start is not None else None
    updated = absolute is not None and absolute >= int(TUNING_CUTOFF.timestamp()*1000)
    if fight.get('observedTuning') is not None:
        updated = bool(fight['observedTuning'])
    mythic = int(fight.get('difficulty') or 0) == 5
    return {'key':'2026-10-13' if updated else 'before-2026-10-13',
            'evidence':fight.get('tuningEvidence') or ('fight-start-date-Asia-Shanghai' if absolute is not None else 'date-missing-legacy-fallback'),
            'observedMechanics':fight.get('observedMechanics',{}),
            'source':TUNING_SOURCE, 'mutationRadiusYards':6 if updated else 8,
            'p1InitialOrbCount':(8 if updated else 10) if mythic else None,
            'p1MutationCount':(4 if updated else 5) if mythic else None,
            'dreadmarchTargetCount':(3 if updated else 4) if mythic else None,
            'manifestWatchHalfAngleDegrees':MANIFEST_WATCH_HALF_ANGLE_DEG+(10 if updated else 0),
            'manifestAngleEvidence':'owner-calibrated-angle-plus-hotfix-increase',
            'manifestDespawnOnTargetDeath':updated, 'manifestImmediateRedGlow':updated,
            'nightfallCastMs':ETERNAL_NIGHTFALL_CAST_MS+(2000 if updated else 0)}


def _with_observed_tuning(fight, raw):
    """A same-day pre-maintenance fight must not inherit future tuning."""
    fight = dict(fight)
    if encounter_tuning(fight)['key'] != '2026-10-13' or int(fight.get('difficulty') or 0) != 5:
        return fight
    casts = sorted(raw.get('casts') or [], key=lambda r:int(r['timestamp']))
    deluges = [r for r in casts if ability_id(r)==TOXIC_DELUGE and is_cast_complete(r)]
    normals = []
    for i, cast in enumerate(deluges[:2]):
        end = deluges[i+1]['timestamp'] if i+1<len(deluges) else fight['endTime']
        rows = [r for r in casts if ability_id(r)==COALESCED_VENOM_CAST and is_cast_complete(r)
                and cast['timestamp']<=r['timestamp']<end]
        if rows:
            first = rows[0]['timestamp']
            initial = [r for r in rows if r['timestamp']<=first+1000]
            # Count observed actor instances, excluding recycled drop casts.
            if all(r.get('sourceID') is not None and r.get('sourceInstance') is not None for r in initial):
                normals.append(len({(r['sourceID'],r['sourceInstance']) for r in initial}))
    march = next((r for r in casts if ability_id(r) in DREADMARCH_CAST_IDS and is_cast_complete(r)),None)
    targets = None
    if march:
        hits = [r for r in raw.get('debuffs') or [] if ability_id(r) in DREADMARCH_DEBUFF_IDS
                and event_type(r)=='applydebuff' and march['timestamp']<=r['timestamp']<=march['timestamp']+2000]
        first = min((r['timestamp'] for r in hits),default=None)
        if first is not None:
            targets = len({r['targetID'] for r in hits if r['timestamp']<=first+250})
    observed = {'initialNormalOrbCounts':normals,'firstDreadmarchTargets':targets}
    if any(n>=5 for n in normals) or targets is not None and targets>=4:
        fight.update(observedTuning=False,tuningEvidence='observed-pre-hotfix-counts',observedMechanics=observed)
    elif normals and all(n==4 for n in normals) and targets==3:
        fight.update(observedTuning=True,tuningEvidence='observed-post-hotfix-counts',observedMechanics=observed)
    else:
        fight.update(tuningEvidence='date-candidate-not-event-confirmed',observedMechanics=observed)
    return fight

# 拉取时只向 WCL 要机制相关技能，避免整场友伤/治疗/带坐标的团员施法。
MECHANIC_CAST_IDS = (
    {TOXIC_DELUGE, COALESCED_VENOM_CAST, VIRULENT_MUTATION_CAST, ETERNAL_NIGHTFALL, ETERNAL_NIGHTFALL_AURA,
     P2_SIGNAL_SPELL, MANIFEST_CAST, FIXATION, RECLAIM_ESSENCE, INTERMISSION_SOULBIND,
     1288624, 1304028, 1286441, 1298381, 1299266}
    | SEVER_IDS | BLIGHTED_SEVER_IDS | SOUL_SEVER_IDS
    | GUILLOTINE_CAST_IDS | GRIM_GUILLOTINE_CAST_IDS
    | DREADMARCH_CAST_IDS | GLOOMBOMB_CAST_IDS | WAIL_OF_TERROR_IDS | {SPIRIT_SHIELD}
)
MECHANIC_DAMAGE_IDS = (
    {COALESCED_VENOM_DAMAGE, VOLATILE_VENOM, MUTAGENIC_VENOM_DAMAGE, VENOM_RUPTURE, GUILLOTINE_DAMAGE_ID,
     WIDOW_TOUCH_DAMAGE_ID, WIDOW_KISS_DAMAGE_ID, DEATH_WHISPER_DAMAGE_ID,
     DEATH_EMBRACE_DAMAGE_ID, SPIRIT_ERASURE, RECLAIM_ESSENCE}
    | GRIM_GUILLOTINE_DAMAGE_IDS | GRAVEBOUND_DAMAGE_IDS
    | GLOOMBOMB_CAST_IDS | GLOOMBOMB_DEBUFF_IDS | GLOOMBOMB_DAMAGE_IDS
)
MECHANIC_DEBUFF_IDS = (
    {VOLATILE_VENOM, FIXATION, GUILLOTINE_MARK, VENOM_RUPTURE}
    | MUTAGENIC_VENOM_AURA_IDS
    | GLOOMBOMB_DEBUFF_IDS | GRAVEBOUND_DEBUFF_IDS
    | DREADMARCH_DEBUFF_IDS | MANIFEST_COLLISION_DEBUFF_IDS
    | GRIM_GUILLOTINE_MARK_IDS
    | SEVER_TANK_DEBUFF_IDS | BLIGHTED_SEVER_TANK_DEBUFF_IDS | SOUL_SEVER_TANK_DEBUFF_IDS
    | SPIRIT_ERASURE_DEBUFF_IDS
)
MECHANIC_ENEMY_BUFF_IDS = set(INTERMISSION_BUFFS) | {VEIL_SHIELD, P3_SOULBOUND, SPIRIT_SHIELD, 1288624, 1304028}
FRIENDLY_CAST_IDS = set(COMBAT_RES_SPELLS) | set(INTERMISSION_POTIONS) | {SPIRIT_ERASURE}


def _boss_icon_src(key):
    path = get_boss_icon_path(key)
    return path.relative_to(path.parents[2]).as_posix()


FIELD_ICONS = {
    "zuljan": _boss_icon_src("zuljan"),
    "malacrass": _boss_icon_src("hex_lord_malacrass"),
    "poisonOrb": _boss_icon_src("poison_orb"),
    "manifestation": _boss_icon_src("manifestation_dread"),
}

TABS = [
    ("survival", "全场存活情况"),
    ("p1", "P1 毒蛇的交易"),
    ("p2", "P2 篡权者的报复"),
    ("intermission", "转阶段 被夺取的宿体"),
    ("p3", "P3 盘卷联合"),
    ("replay", "战斗回放"),
    ("field", "场地示意图"),
    ("explore", "机制工作台"),
]

PHASE_LABELS = {
    "p1": "P1 毒蛇交易",
    "p2": "P2 篡位者复仇",
    "intermission": "被夺取的容器",
    "p3": "P3 盘卷联合",
}


def progress(message, percent=None):
    print(f"[coiledaltar] {message}", flush=True)
    emit_progress(message, percent=percent, stage="analyze")


def is_apply(event):
    return event_type(event) in {"applydebuff", "applybuff", "applydebuffstack", "applybuffstack", "refreshdebuff"}


def is_remove(event):
    return event_type(event) in {"removedebuff", "removebuff", "removedebuffstack", "removebuffstack"}


def is_cast_complete(event):
    return event_type(event) == "cast"


def normalize_facing_radians(raw_facing):
    if raw_facing is None:
        return None
    radians = float(raw_facing) / 100.0
    while radians <= -math.pi:
        radians += math.tau
    while radians > math.pi:
        radians -= math.tau
    return radians


def yards_to_units(yards):
    return float(yards) * WCL_UNITS_PER_YARD


def units_to_yards(units):
    return float(units) / WCL_UNITS_PER_YARD


def distance_yards(left, right):
    return math.hypot(left[0] - right[0], left[1] - right[1]) / WCL_UNITS_PER_YARD


def arena_center_units():
    return (ARENA_CENTER_X_UNITS * WCL_COORD_SCALE, ARENA_CENTER_Y_UNITS * WCL_COORD_SCALE)


def point_dict(point, timestamp=None, reliable=None, offset_ms=None):
    if not point:
        return None
    row = {"x": round(point[0], 2), "y": round(point[1], 2)}
    if timestamp is not None:
        row["timestamp"] = int(timestamp)
    if reliable is not None:
        row["positionReliable"] = bool(reliable)
    if offset_ms is not None:
        row["sampleOffsetMs"] = int(offset_ms)
    return row


def actor_facing_at(index, actor_id, timestamp):
    row = position_at(index, actor_id, timestamp, max_offset_ms=POSITION_RELIABLE_MS)
    if not row:
        return None
    return {
        **row,
        "facingRadians": normalize_facing_radians(row.get("facing")),
    }


def in_frontal_cone(origin, facing_radians, point, radius_yards=CONE_RADIUS_YARDS, half_angle_deg=CONE_HALF_ANGLE_DEG):
    if origin is None or point is None or facing_radians is None:
        return False
    dx = point[0] - origin[0]
    dy = point[1] - origin[1]
    distance = math.hypot(dx, dy)
    if distance > yards_to_units(radius_yards):
        return False
    target_angle = math.atan2(-dy, dx)
    delta = (target_angle - facing_radians + math.pi) % (2 * math.pi) - math.pi
    return abs(delta) <= math.radians(half_angle_deg)


def cone_polygon(origin, facing_radians, radius_yards=CONE_RADIUS_YARDS, half_angle_deg=CONE_HALF_ANGLE_DEG, steps=18):
    if origin is None or facing_radians is None:
        return []
    radius = yards_to_units(radius_yards)
    points = [origin]
    start = facing_radians - math.radians(half_angle_deg)
    end = facing_radians + math.radians(half_angle_deg)
    for index in range(steps + 1):
        angle = start + (end - start) * index / steps
        points.append((origin[0] + math.cos(angle) * radius, origin[1] - math.sin(angle) * radius))
    points.append(origin)
    return [point_dict(point) for point in points]


def _position_xy(point):
    if not point:
        return None
    if isinstance(point, dict):
        if point.get("x") is None or point.get("y") is None:
            nested = point.get("position")
            if nested:
                return _position_xy(nested)
            return None
        return float(point["x"]), float(point["y"])
    if isinstance(point, (list, tuple)) and len(point) >= 2:
        return float(point[0]), float(point[1])
    return None


def facing_toward_point(origin, point):
    coords = _position_xy(point)
    if not coords or origin is None:
        return None
    dx = coords[0] - origin[0]
    dy = coords[1] - origin[1]
    return math.atan2(-dy, dx)


def point_last_seen_ms(point, fight_start):
    last = int(point.get("lastSeenMs") or 0)
    if last > fight_start:
        return last - fight_start
    return last


def active_points_near_cast(active_points, timestamp, fight_start, window_ms=30_000):
    cast_rel = timestamp - fight_start
    return [
        point for point in (active_points or [])
        if point.get("position") and point_last_seen_ms(point, fight_start) >= cast_rel - window_ms
    ]


def active_fixations_before_cast(points, cast_ts, fight_start):
    """撕裂/凋零撕裂释放前仍存活的恐惧具象（已 apply，且尚未 remove/despawn）。"""
    cast_rel = int(cast_ts) - int(fight_start)
    active = []
    for point in points or []:
        apply_rel = point.get("applyTimeMs")
        if apply_rel is None or int(apply_rel) > cast_rel:
            continue
        end_rel = point.get("removeTimeMs")
        if end_rel is None and point.get("despawnTimeMs") is not None:
            end_rel = point.get("despawnTimeMs")
        if end_rel is None:
            last = point_last_seen_ms(point, fight_start)
            end_rel = last if last else None
        # 释放前已消除（凝视消失或 NPC 消失）的不再计入
        if end_rel is not None and int(end_rel) <= cast_rel:
            continue
        active.append(point)
    return active


def classify_fixation_after_sever(point, cast_ts, fight_start, in_cone, clear_window_ms=SOUL_SEVER_CLEAR_WINDOW_MS):
    """
    综合判断本轮锥形撕裂是否清掉凝视（灵魂撕裂 / 凋零撕裂）：
    - 释放后短窗口内 remove → 已清掉
    - 否则视为未消掉；再结合是否在锥内区分漏清 / 锥外残留
    """
    cast_rel = int(cast_ts) - int(fight_start)
    remove_rel = point.get("removeTimeMs")
    cleared = (
        remove_rel is not None
        and cast_rel < int(remove_rel) <= cast_rel + int(clear_window_ms)
    )
    if cleared:
        outcome = "cleared"
    elif in_cone:
        outcome = "missed-in-cone"
    else:
        outcome = "outside-remain"
    return {
        "inCone": bool(in_cone),
        "debuffCleared": cleared,
        "uncleared": not cleared,
        "clearOutcome": outcome,
    }


# 兼容旧名
classify_fixation_after_soul_sever = classify_fixation_after_sever


def infer_facing_toward(origin, points):
    """Visualization-only facing estimate toward the centroid of nearby markers."""
    coords = [_position_xy(point) for point in (points or [])]
    coords = [row for row in coords if row]
    if not coords or origin is None:
        return None
    centroid_x = sum(row[0] for row in coords) / len(coords)
    centroid_y = sum(row[1] for row in coords) / len(coords)
    return facing_toward_point(origin, (centroid_x, centroid_y))


def plot_pct(point, arena):
    coords = _position_xy(point)
    if not coords or not arena:
        return None
    radius = float(arena.get("radius") or 1)
    dx = coords[0] - float(arena["centerX"])
    dy = coords[1] - float(arena["centerY"])
    return {
        "left": 50 + (dx / radius) * float(arena.get("plotScaleX") or ARENA_PLOT_SCALE_X),
        "top": 50 - (dy / radius) * float(arena.get("plotScaleY") or ARENA_PLOT_SCALE_Y),
    }


def plot_size_pct(yards, arena):
    if not arena:
        return {"width": 0.0, "height": 0.0}
    ratio = yards_to_units(yards) / float(arena.get("radius") or 1)
    return {
        "width": ratio * float(arena.get("plotScaleX") or ARENA_PLOT_SCALE_X),
        "height": ratio * float(arena.get("plotScaleY") or ARENA_PLOT_SCALE_Y),
    }


def _boss_start_point(position_index, boss_id):
    if boss_id is None:
        return None
    rows = position_index.get(boss_id) or []
    if not rows:
        return None
    first = rows[0]
    return point_dict((first["x"], first["y"]), timestamp=first.get("timestamp"), reliable=True)


def coiledaltar_arena(position_index=None, player_ids=None, boss_id=None):
    center = arena_center_units()
    boss_start = _boss_start_point(position_index or {}, boss_id)
    return {
        "centerX": center[0],
        "centerY": center[1],
        "centerXYards": ARENA_CENTER_X_UNITS,
        "centerYYards": ARENA_CENTER_Y_UNITS,
        "centerXUnits": ARENA_CENTER_X_UNITS,
        "centerYUnits": ARENA_CENTER_Y_UNITS,
        "radius": ARENA_HALF_SIDE_UNITS * WCL_COORD_SCALE,
        "radiusYards": ARENA_HALF_SIDE_YARDS,
        "radiusUnits": ARENA_HALF_SIDE_UNITS,
        "sideYards": ARENA_SIDE_YARDS,
        "sideUnits": ARENA_SIDE_UNITS,
        "halfSideYards": ARENA_HALF_SIDE_YARDS,
        "halfSideUnits": ARENA_HALF_SIDE_UNITS,
        "unitsPerYard": WCL_UNITS_PER_YARD,
        "wclCoordScale": WCL_COORD_SCALE,
        "method": "fixed-center-0-1158-square-110yd-wcl100",
        "bossCenter": True,
        "bossStart": boss_start,
        "plotScaleX": ARENA_PLOT_SCALE_X,
        "plotScaleY": ARENA_PLOT_SCALE_Y,
        "imageWidth": ARENA_IMAGE_WIDTH,
        "imageHeight": ARENA_IMAGE_HEIGHT,
        "squarePx": ARENA_SQUARE_PX,
        "gloombombRadiusYards": GLOOMBOMB_RADIUS_YARDS,
        "coneRadiusYards": CONE_RADIUS_YARDS,
        "guillotineRangeYards": GUILLOTINE_RANGE_YARDS,
        "virulentBlastRadiusYards": VIRULENT_BLAST_RADIUS_YARDS,
    }


def _xy_from_node(node):
    if not isinstance(node, dict) or node.get("x") is None or node.get("y") is None:
        return None
    try:
        return float(node["x"]), float(node["y"])
    except (TypeError, ValueError):
        return None


def _source_self_point(event):
    """只取施法者自身坐标。WCL 施法事件顶层 x/y 经常是目标（坦克），不能当 Boss 位置。"""
    point = _xy_from_node(event.get("sourceResources"))
    if point:
        return point
    resource_actor = event.get("resourceActor")
    if resource_actor in {1, "1", "Source"}:
        return event_point(event)
    return None


def _target_self_point(event):
    """只取受击者自身坐标。resourceActor=Target 时顶层 x/y 才属于目标。"""
    point = _xy_from_node(event.get("targetResources"))
    if point:
        return point
    resource_actor = event.get("resourceActor")
    if resource_actor in {2, "2", "Target"}:
        return _xy_from_node(event) or _xy_from_node(event.get("resources"))
    return None


def _aura_target_point(event):
    """光环在目标身上：优先 targetResources；否则顶层 x/y 视为目标（玩家）坐标。"""
    point = _target_self_point(event)
    if point:
        return point
    kind = event_type(event)
    if "buff" in kind or "debuff" in kind:
        return _xy_from_node(event) or _xy_from_node(event.get("resources"))
    return None


def _is_gloombomb_full_remove(event):
    kind = event_type(event)
    if kind in GLOOMBOMB_REMOVE_TYPES:
        return True
    if kind in GLOOMBOMB_STACK_REMOVE_TYPES:
        return int(event.get("stack") or 0) == 0
    return False


def _first_full_aura_remove_after(events, target_id, apply_ts, spell_ids):
    spell_ids = set(spell_ids)
    wanted = int(target_id) if target_id is not None else None
    return next(
        (
            event for event in events
            if int(event.get("targetID") or -1) == wanted
            and int(ability_id(event) or 0) in spell_ids
            and _is_gloombomb_full_remove(event)
            and int(event.get("timestamp") or 0) >= int(apply_ts)
        ),
        None,
    )


def _point_at_aura_remove(remove_event, position_index, target_id):
    explode_ts = int(remove_event["timestamp"])
    point = _aura_target_point(remove_event)
    if point:
        return point_dict(point, timestamp=explode_ts, reliable=True, offset_ms=0)
    sampled = _position_sample(position_index, target_id, explode_ts)
    if sampled and abs(int(sampled.get("sampleOffsetMs") or 0)) <= GLOOMBOMB_POSITION_MAX_OFFSET_MS:
        return sampled
    return None


def _actor_self_point(event, actor_id):
    if actor_id is None:
        return None
    if event.get("sourceID") == actor_id:
        point = _source_self_point(event)
        if point:
            return point
    # 友伤打 Boss 时顶层 x/y / targetResources 才可能是 Boss；其它事件不要把目标坐标当 Boss。
    if event.get("targetID") == actor_id and event_type(event) == "damage":
        return _target_self_point(event)
    return None


def _actor_self_facing(event, actor_id):
    if event.get("sourceID") == actor_id:
        return (event.get("sourceResources") or {}).get("facing", event.get("facing"))
    if event.get("targetID") == actor_id:
        return (event.get("targetResources") or {}).get("facing", event.get("facing"))
    return event.get("facing")


def build_caster_self_position_index(events, actor_ids=None):
    """Boss 自身坐标：优先 sourceResources；Boss 受击时才用 targetResources。"""
    index = defaultdict(list)
    allowed = set(actor_ids) if actor_ids else None
    for event in events:
        candidates = []
        source_id = event.get("sourceID")
        target_id = event.get("targetID")
        if source_id is not None and (allowed is None or source_id in allowed):
            candidates.append(source_id)
        if target_id is not None and target_id != source_id and (allowed is None or target_id in allowed):
            candidates.append(target_id)
        timestamp = int(event.get("timestamp") or 0)
        for actor_id in candidates:
            point = _actor_self_point(event, actor_id)
            if not point:
                continue
            index[actor_id].append({
                "timestamp": timestamp,
                "x": point[0], "y": point[1],
                "facing": _actor_self_facing(event, actor_id),
            })
    for rows in index.values():
        rows.sort(key=lambda row: row["timestamp"])
    return index


def boss_cone_origin(origin_index, boss_actor_id, timestamp, cast_event=None):
    """撕裂锥形圆心：优先施法事件 sourceResources，否则取 Boss 自身轨迹。"""
    if cast_event is not None and boss_actor_id is not None and cast_event.get("sourceID") == boss_actor_id:
        cast_point = _source_self_point(cast_event)
        if cast_point:
            facing = (cast_event.get("sourceResources") or {}).get("facing", cast_event.get("facing"))
            return cast_point, {
                "x": cast_point[0],
                "y": cast_point[1],
                "facing": facing,
                "facingRadians": normalize_facing_radians(facing),
                "reliable": True,
                "positionRule": "cast-sourceResources",
                "sampleOffsetMs": 0,
            }
    live = actor_origin_at(origin_index, boss_actor_id, timestamp) if origin_index and boss_actor_id is not None else None
    if not live:
        return None, {
            "facingRadians": None,
            "reliable": False,
            "positionRule": "missing",
            "sampleOffsetMs": None,
        }
    return (live["x"], live["y"]), {
        "x": live["x"],
        "y": live["y"],
        "facing": live.get("facing"),
        "facingRadians": live.get("facingRadians"),
        "reliable": bool(live.get("reliable")),
        "positionRule": live.get("positionRule") or "boss-current",
        "sampleOffsetMs": live.get("sampleOffsetMs"),
    }


def boss_field_position(origin_index, boss_actor_id, timestamp, cast_event=None):
    """处斩/幽暗炸弹等非锥形图：Boss 标记用当时自身坐标，不用场地中心。"""
    origin, state = boss_cone_origin(origin_index, boss_actor_id, timestamp, cast_event=cast_event)
    if not origin:
        return None
    return point_dict(
        origin,
        timestamp=timestamp,
        reliable=bool(state and state.get("reliable")),
        offset_ms=(state or {}).get("sampleOffsetMs"),
    )


def actor_origin_at(index, actor_id, timestamp):
    row = position_at_interpolated(index, actor_id, timestamp, reliable_window_ms=POSITION_RELIABLE_MS)
    if not row:
        row = position_at(index, actor_id, timestamp, max_offset_ms=POSITION_RELIABLE_MS)
    if not row:
        return None
    return {
        **row,
        "facingRadians": normalize_facing_radians(row.get("facing")),
    }


def matching_begincast(casts, cast_event, max_duration_ms=15_000):
    """配对同一施法者、同一技能、完成 cast 之前最近的 begincast。"""
    if not cast_event:
        return None
    cast_ts = int(cast_event.get("timestamp") or 0)
    source_id = cast_event.get("sourceID")
    spell = int(ability_id(cast_event) or 0)
    best = None
    best_ts = None
    for event in casts or []:
        if event_type(event) != "begincast":
            continue
        if event.get("sourceID") != source_id:
            continue
        if int(ability_id(event) or 0) != spell:
            continue
        ts = int(event.get("timestamp") or 0)
        if ts > cast_ts or cast_ts - ts > max_duration_ms:
            continue
        if best is None or ts > best_ts:
            best = event
            best_ts = ts
    return best


def resolve_sever_facing_lock(casts, cast_event, debuffs=None, debuff_ids=None):
    """
    撕裂朝向锁定时刻：优先坦克易伤/结算 debuff 施加；否则读条最后一秒；再退回 cast 完成。
    返回 (lock_ms, tank_id, rule, debuff_event)。
    """
    cast_ts = int((cast_event or {}).get("timestamp") or 0)
    tank_id = (cast_event or {}).get("targetID")
    spell = int(ability_id(cast_event) or 0) if cast_event else 0
    ids = set(debuff_ids or CAST_TO_TANK_DEBUFF_IDS.get(spell) or ())
    if ids and debuffs is not None:
        window = _events_between(debuffs, cast_ts - 2_500, cast_ts + 2_500, ids)
        applies = [event for event in window if is_apply(event)]
        if tank_id is not None:
            matched = [event for event in applies if event.get("targetID") == tank_id]
            if matched:
                applies = matched
        if applies:
            applies.sort(key=lambda event: abs(int(event.get("timestamp") or 0) - cast_ts))
            chosen = applies[0]
            return int(chosen["timestamp"]), chosen.get("targetID") or tank_id, "tank-debuff", chosen
    begin = matching_begincast(casts, cast_event)
    if begin is not None:
        begin_ts = int(begin["timestamp"])
        lock_ms = max(begin_ts, cast_ts - CAST_LAST_SECOND_MS)
        return lock_ms, tank_id, "cast-last-second", None
    if cast_ts:
        return max(0, cast_ts - CAST_LAST_SECOND_MS), tank_id, "cast-last-second", None
    return cast_ts, tank_id, "cast-complete", None


def resolve_caster_origin_facing(
    position_index,
    source_id,
    boss_actor_id,
    timestamp,
    hint_points=None,
    target_id=None,
    origin_actor_id=None,
    origin_index=None,
    cast_event=None,
    facing_timestamp=None,
    allow_hint_override=True,
):
    """圆心=Boss（施法结算）；朝向中点=锁定时刻的坦克位置（debuff / 读条末秒）。"""
    origin_actor = origin_actor_id or boss_actor_id or source_id
    if cast_event is not None and origin_actor is None:
        origin_actor = cast_event.get("sourceID")
    origin, facing_state = boss_cone_origin(origin_index, origin_actor, timestamp, cast_event=cast_event)
    facing_radians = None
    facing_inferred = False
    tank_id = target_id if target_id is not None else (cast_event or {}).get("targetID")
    facing_at = int(facing_timestamp) if facing_timestamp is not None else int(timestamp)
    tank_facing = None
    tank_state = None
    if origin and tank_id is not None:
        tank_state = position_at(position_index, tank_id, facing_at, max_offset_ms=POSITION_RELIABLE_MS)
        if tank_state:
            tank_facing = facing_toward_point(origin, (tank_state["x"], tank_state["y"]))
            facing_radians = tank_facing
    if facing_radians is None and facing_state.get("facingRadians") is not None:
        facing_radians = facing_state["facingRadians"]
    if facing_radians is None and origin_index is not None:
        live = actor_origin_at(origin_index, origin_actor, timestamp)
        if live and live.get("facingRadians") is not None:
            facing_radians = live["facingRadians"]
            facing_state = {**facing_state, "facing": live.get("facing"), "facingRadians": facing_radians}
    hint_facing = None
    if origin and hint_points:
        hint_facing = infer_facing_toward(origin, hint_points)
    # 已按 debuff/读条末秒锁定坦克位置时，不再用毒液质心覆盖朝向。
    if origin and hint_facing is not None:
        if facing_radians is None:
            facing_radians = hint_facing
            facing_inferred = True
        elif allow_hint_override and tank_facing is not None:
            delta = (hint_facing - tank_facing + math.pi) % (2 * math.pi) - math.pi
            if abs(delta) > math.pi / 2:
                facing_radians = hint_facing
                facing_inferred = True
    if origin and facing_radians is None and hint_facing is not None:
        facing_radians = hint_facing
        facing_inferred = True
    return origin, facing_radians, facing_state, facing_inferred, tank_state


def build_actor_catalog(actor_rows):
    by_id = {}
    by_game_id = defaultdict(list)
    for row in actor_rows:
        actor_id = row["id"]
        game_id = row.get("gameID")
        entry = {
            "actorID": actor_id,
            "name": row.get("name"),
            "gameID": game_id,
            "type": row.get("type"),
        }
        by_id[actor_id] = entry
        if game_id is not None:
            by_game_id[int(game_id)].append(entry)
    return {"byID": by_id, "byGameID": dict(by_game_id)}


def resolve_manifest_instance(source_id, source_instance, actor_catalog):
    actor = actor_catalog["byID"].get(source_id) or {}
    game_id = actor.get("gameID")
    return {
        "sourceID": source_id,
        "sourceInstance": source_instance,
        "sourceName": actor.get("name"),
        "gameID": game_id,
        "isManifestNpc": game_id == MANIFEST_NPC_GAME_ID or any(
            token in str(actor.get("name") or "").lower()
            for token in ("manifestation of dread", "恐惧具象")
        ),
    }


def phase_at(time_ms, markers):
    current = markers[0]["key"] if markers else "p1"
    for marker in markers:
        if marker.get("key") == "wipe":
            continue
        if time_ms >= marker["timeMs"]:
            current = marker["key"]
    return current


def _wcl_phase_key(phase_id, meta, metadata):
    name = str((meta or {}).get("name") or "")
    text = name.lower()
    if (meta or {}).get("isIntermission") or any(
        token in text for token in ("intermission", "container", "vessel", "host", "容器", "宿体", "stolen", "captured")
    ):
        return "intermission"
    if any(token in text for token in ("usurper", "revenge", "malacrass", "篡", "报复", "复仇")):
        return "p2"
    if any(token in text for token in ("coiled", "union", "joint", "combined", "盘卷", "联合")):
        return "p3"
    if any(token in text for token in ("serpent", "bargain", "trade", "deal", "毒蛇", "交易")):
        return "p1"
    if not metadata:
        return {1: "p1", 2: "p2", 3: "intermission", 4: "p3"}.get(int(phase_id or 1), "p1")
    stage = 0
    for index, row in enumerate(metadata, start=1):
        pid = int(row.get("id") or index)
        if row.get("isIntermission"):
            if pid == int(phase_id):
                return "intermission"
            continue
        stage += 1
        if pid == int(phase_id):
            return f"p{stage}" if stage <= 3 else f"p{stage}"
    return "p1"


def _markers_from_wcl(fight, metadata):
    transitions = list(fight.get("phaseTransitions") or [])
    if not transitions:
        return None
    metadata = list(metadata or fight.get("wclPhaseMetadata") or [])
    by_id = {int(row.get("id") or index): row for index, row in enumerate(metadata, start=1)}
    markers = []
    for transition in sorted(transitions, key=lambda row: int(row.get("startTime") or 0)):
        phase_id = int(transition.get("id") or 1)
        meta = by_id.get(phase_id) or {}
        key = _wcl_phase_key(phase_id, meta, metadata)
        markers.append({
            "key": key,
            "label": PHASE_LABELS.get(key) or meta.get("name") or key,
            "timeMs": max(0, fight_phase_start_ms(fight, transition)),
            "signal": "wcl-phase",
            "wclPhaseId": phase_id,
            "wclPhaseName": meta.get("name"),
        })
    if not markers:
        return None
    if markers[0]["timeMs"] > 0 and markers[0]["key"] != "p1":
        markers.insert(0, {
            "key": "p1",
            "label": PHASE_LABELS["p1"],
            "timeMs": 0,
            "signal": "wcl-phase-start",
        })
    return markers


def build_phase_markers(fight, casts, enemy_buffs, enemy_deaths=None, zuljan_id=None, malacrass_id=None):
    """优先用 WCL phaseTransitions；没有阶段数据时再按死亡/出现/技能推断。"""
    start = int(fight["startTime"])
    wcl_markers = _markers_from_wcl(fight, fight.get("wclPhaseMetadata"))
    intermission_ms = None
    p3_ms = None
    for event in sorted(enemy_buffs or [], key=lambda row: int(row.get("timestamp") or 0)):
        spell = int(ability_id(event) or 0)
        if spell in INTERMISSION_BUFFS and is_apply(event) and intermission_ms is None:
            intermission_ms = int(event["timestamp"]) - start
        if spell == P3_SOULBOUND and is_apply(event):
            p3_ms = int(event["timestamp"]) - start

    wipe = {
        "key": "wipe",
        "label": "击杀" if fight.get("kill") else "灭团",
        "timeMs": int(fight["endTime"] - start),
    }
    if wcl_markers:
        keys = {row["key"] for row in wcl_markers}
        if "intermission" not in keys and intermission_ms is not None:
            wcl_markers.append({
                "key": "intermission",
                "label": PHASE_LABELS["intermission"],
                "timeMs": intermission_ms,
                "signal": "container-aura",
            })
        if "p3" not in keys and p3_ms is not None:
            wcl_markers.append({
                "key": "p3",
                "label": PHASE_LABELS["p3"],
                "timeMs": p3_ms,
                "signal": "soulbound-aura",
            })
        wcl_markers.sort(key=lambda row: int(row.get("timeMs") or 0))
        return wcl_markers + [wipe]

    candidates = []

    if zuljan_id is not None:
        for event in sorted(enemy_deaths or [], key=lambda row: int(row.get("timestamp") or 0)):
            if event.get("targetID") == zuljan_id and event_type(event) == "death":
                candidates.append((int(event["timestamp"]) - start, "zuljan-death"))
                break

    if malacrass_id is not None:
        for event in sorted(casts, key=lambda row: int(row.get("timestamp") or 0)):
            if event.get("sourceID") != malacrass_id:
                continue
            if event_type(event) in {"begincast", "cast"}:
                candidates.append((int(event["timestamp"]) - start, "malacrass-appear"))
                break

    for event in sorted(casts, key=lambda row: int(row.get("timestamp") or 0)):
        if int(ability_id(event) or 0) == P2_SIGNAL_SPELL and event_type(event) == "begincast":
            candidates.append((int(event["timestamp"]) - start, "fear-bolt-fallback"))
            break

    for event in sorted(casts, key=lambda row: int(row.get("timestamp") or 0)):
        if int(ability_id(event) or 0) in GLOOMBOMB_CAST_IDS and event_type(event) in {"begincast", "cast"}:
            candidates.append((int(event["timestamp"]) - start, "gloombomb"))
            break

    p2_ms = None
    p2_signal = None
    if candidates:
        p2_ms, p2_signal = min(candidates, key=lambda row: row[0])

    markers = [{"key": "p1", "label": PHASE_LABELS["p1"], "timeMs": 0}]
    if p2_ms is not None:
        markers.append({
            "key": "p2",
            "label": PHASE_LABELS["p2"],
            "timeMs": p2_ms,
            "signal": p2_signal,
        })
    if intermission_ms is not None:
        markers.append({"key": "intermission", "label": PHASE_LABELS["intermission"], "timeMs": intermission_ms})
    if p3_ms is not None:
        markers.append({"key": "p3", "label": PHASE_LABELS["p3"], "timeMs": p3_ms})
    markers.append(wipe)
    return markers


def _ability_filter(spell_ids):
    ids = sorted({int(spell_id) for spell_id in spell_ids or [] if spell_id})
    if not ids:
        return None
    if len(ids) == 1:
        return f"ability.id = {ids[0]}"
    return "ability.id in (" + ", ".join(str(i) for i in ids) + ")"


def _actor_filter(actor_ids):
    ids = sorted({int(actor_id) for actor_id in actor_ids or [] if actor_id is not None})
    if not ids:
        return None
    if len(ids) == 1:
        return f"source.id = {ids[0]} OR target.id = {ids[0]}"
    joined = ", ".join(str(i) for i in ids)
    return f"source.id in ({joined}) OR target.id in ({joined})"


def _event_type_filter(types):
    return "type in (" + ", ".join(f'"{name}"' for name in types) + ")"


# 具象只点名上凝视，不打人。坐标来自其施法/debuff 的 sourceResources，以及被打到时的受击坐标。
NPC_POSITION_TYPES = (
    "cast", "begincast", "damage", "applybuff", "applydebuff", "removebuff", "removedebuff",
    "refreshbuff", "refreshdebuff", "death",
)


def _npc_position_filter_expression(npc_ids):
    actor_filter = _actor_filter(npc_ids)
    if not actor_filter:
        return None
    return f"({actor_filter}) and {_event_type_filter(NPC_POSITION_TYPES)}"


def _fetch_manifest_position_events(client, report_id, fight, manifest_ids):
    """NPC 坐标：自身施法/资源，以及友方对该敌方目标造成伤害时的目标位置。"""
    source_filter = _source_id_filter(manifest_ids)
    target_filter = _target_id_filter(manifest_ids)
    rows = []
    if source_filter:
        rows.extend(client.events(
            report_id, "Casts", fight,
            filter_expression=source_filter, hostility_type="Enemies", include_resources=True,
        ))
        rows.extend(client.events(
            report_id, "Resources", fight,
            filter_expression=source_filter, hostility_type="Enemies", include_resources=True,
        ))
    if target_filter:
        # 敌方 NPC 是 DamageDone 的 target。此前只查 DamageTaken，导致盘魂者
        # 受击位置没有进入索引；DamageDone 也是 runtime 获取 Boss 位置的路径。
        for actor_id in sorted({int(actor_id) for actor_id in manifest_ids}):
            rows.extend(client.events(
                report_id, "DamageDone", fight,
                target_id=actor_id, include_resources=True,
            ))
        # 保留 DamageTaken 作为不同 WCL 数据视图的兼容路径。
        rows.extend(client.events(
            report_id, "DamageTaken", fight,
            filter_expression=target_filter, hostility_type="Enemies", include_resources=True,
        ))
    return rows


def _source_id_filter(actor_ids):
    ids = sorted({int(actor_id) for actor_id in actor_ids or [] if actor_id is not None})
    if not ids:
        return None
    if len(ids) == 1:
        return f"source.id = {ids[0]}"
    return "source.id in (" + ", ".join(str(i) for i in ids) + ")"


def _target_id_filter(actor_ids):
    ids = sorted({int(actor_id) for actor_id in actor_ids or [] if actor_id is not None})
    if not ids:
        return None
    if len(ids) == 1:
        return f"target.id = {ids[0]}"
    return "target.id in (" + ", ".join(str(i) for i in ids) + ")"


def _fetch_by_abilities(client, report_id, data_type, fight, spell_ids, **kwargs):
    expression = _ability_filter(spell_ids)
    if not expression:
        return []
    return client.events(report_id, data_type, fight, filter_expression=expression, **kwargs)


def _events_between(events, start, end, spell_ids=None):
    spell_ids = set(spell_ids or [])
    return [
        event for event in events
        if start <= int(event.get("timestamp") or 0) < end
        and (not spell_ids or int(ability_id(event) or 0) in spell_ids)
    ]


def _position_sample(index, actor_id, timestamp):
    row = position_at_interpolated(index, actor_id, timestamp, reliable_window_ms=POSITION_RELIABLE_MS)
    if not row:
        return None
    return point_dict((row["x"], row["y"]), timestamp=timestamp, reliable=row.get("reliable"), offset_ms=row.get("sampleOffsetMs"))


def manifest_actor_ids(actor_rows):
    ids = set()
    for row in actor_rows:
        game_id = row.get("gameID")
        name = str(row.get("name") or "").lower()
        if game_id == MANIFEST_NPC_GAME_ID or "manifestation of dread" in name or "恐惧具象" in name:
            ids.add(int(row["id"]))
    return ids


def virulent_mutation_actor_ids(actor_rows):
    ids = set()
    for row in actor_rows or []:
        game_id = row.get("gameID")
        name = str(row.get("name") or "").lower()
        if game_id == VIRULENT_MUTATION_NPC_GAME_ID or "virulent mutation" in name or "烈毒变异体" in name:
            ids.add(int(row["id"]))
    return ids


def soulcoiler_actor_ids(actor_rows):
    ids = set()
    for row in actor_rows or []:
        game_id = int(row.get("gameID") or 0)
        name = str(row.get("name") or "").lower()
        if (
            game_id == SOULCOILER_NPC_GAME_ID
            or "spiteful soulcoiler" in name
            or "怨毒盘魂者" in name
            or "soulcoiler" in name
        ):
            ids.add(int(row["id"]))
    return ids


def _npc_position_events(raw, npc_actor_ids):
    if not npc_actor_ids:
        return []
    events = []
    for bucket in (
        "casts", "enemyDamage", "damage", "debuffs", "enemyBuffs", "buffs",
        "resources", "enemyDeaths", "npcPositionEvents",
    ):
        for event in raw.get(bucket) or []:
            source_id = event.get("sourceID")
            target_id = event.get("targetID")
            actor_id = position_actor_id(event)
            if source_id in npc_actor_ids or target_id in npc_actor_ids or actor_id in npc_actor_ids:
                events.append(event)
    return events


def _npc_actor_point(event, actor_id):
    """NPC 自身坐标。敌方施法 includeResources 时顶层 x/y 是施法者，不能因为有目标就丢掉。"""
    if actor_id is None:
        return None
    kind = event_type(event)
    if event.get("sourceID") == actor_id:
        point = _xy_from_node(event.get("sourceResources"))
        if point:
            return point
        resource_actor = event.get("resourceActor")
        if resource_actor in {1, "1", "Source"}:
            return _xy_from_node(event) or _xy_from_node(event.get("resources"))
        if kind in {"resourcechange", ""}:
            return _xy_from_node(event) or _xy_from_node(event.get("resources"))
        target_id = event.get("targetID")
        if target_id is None or target_id == actor_id:
            return _xy_from_node(event) or _xy_from_node(event.get("resources"))
        return None
    if event.get("targetID") == actor_id:
        point = _xy_from_node(event.get("targetResources"))
        if point:
            return point
        resource_actor = event.get("resourceActor")
        if resource_actor in {2, "2", "Target"}:
            return _xy_from_node(event) or _xy_from_node(event.get("resources"))
        if resource_actor in {1, "1", "Source"}:
            return None
        # WCL includeResources 对 damage/healing 只记录目标资源；坐标通常就在
        # 事件顶层，即使没有 targetResources/resourceActor 也属于受击 NPC。
        if kind in {"damage", "death"}:
            return _xy_from_node(event) or _xy_from_node(event.get("resources"))
        return None
    return None


def build_npc_position_index(events):
    """按 (actorID, instance) 索引 NPC 自身坐标；拒绝把被点名玩家坐标写入具象。"""
    index = defaultdict(list)

    def append(actor_id, instance, timestamp, point, facing):
        if actor_id is None or not point:
            return
        key = (int(actor_id), int(instance or 0))
        index[key].append({"timestamp": timestamp, "x": point[0], "y": point[1], "facing": facing})

    for event in events:
        timestamp = int(event.get("timestamp") or 0)
        source_id = event.get("sourceID")
        source_instance = event.get("sourceInstance") or event.get("sourceInstanceID")
        target_id = event.get("targetID")
        target_instance = event.get("targetInstance") or event.get("targetInstanceID")
        kind = event_type(event)
        if kind == "interrupt":
            continue
        if kind in {"cast", "begincast"}:
            point = _npc_actor_point(event, source_id)
            facing = (event.get("sourceResources") or {}).get("facing", event.get("facing"))
            append(source_id, source_instance, timestamp, point, facing)
        elif kind in {"damage", "death"}:
            point = _npc_actor_point(event, target_id)
            facing = (event.get("targetResources") or {}).get("facing", event.get("facing"))
            append(target_id, target_instance, timestamp, point, facing)
        else:
            for actor_id, instance in ((source_id, source_instance), (target_id, target_instance)):
                if actor_id is None:
                    continue
                point = _npc_actor_point(event, actor_id)
                facing = _actor_self_facing(event, actor_id)
                append(actor_id, instance, timestamp, point, facing)
    for rows in index.values():
        rows.sort(key=lambda row: row["timestamp"])
    return index


def _npc_instance_rows(index, actor_id, source_instance):
    if actor_id is None:
        return []
    actor_id = int(actor_id)
    if source_instance is not None:
        exact = index.get((actor_id, int(source_instance))) or []
        if exact:
            return exact
    matches = [rows for (aid, inst), rows in index.items() if aid == actor_id]
    if len(matches) == 1:
        return matches[0]
    return index.get((actor_id, 0)) or []


def _position_from_npc_rows(rows, timestamp, allow_future=False):
    if not rows or timestamp is None:
        return None
    ts = int(timestamp)
    prior = [row for row in rows if int(row["timestamp"]) <= ts]
    if prior:
        chosen = prior[-1]
    elif allow_future:
        chosen = min(rows, key=lambda row: abs(int(row["timestamp"]) - ts))
    else:
        return None
    offset = int(chosen["timestamp"] - ts)
    return point_dict(
        (chosen["x"], chosen["y"]),
        timestamp=ts,
        reliable=abs(offset) <= POSITION_RELIABLE_MS,
        offset_ms=offset,
    )


def _position_sample_npc(index, actor_id, source_instance, timestamp):
    rows = _npc_instance_rows(index, actor_id, source_instance)
    if not rows:
        return None
    nearest = min(rows, key=lambda row: abs(row["timestamp"] - timestamp))
    offset = int(nearest["timestamp"] - timestamp)
    if abs(offset) > 30_000:
        return None
    return point_dict(
        (nearest["x"], nearest["y"]),
        timestamp=timestamp,
        reliable=abs(offset) <= POSITION_RELIABLE_MS,
        offset_ms=offset,
    )


def _soulcoiler_instance_rows(index, actor_id, source_instance, extra_rows=None):
    """只合并当前 instance 与未标 instance(0) 的样本，不能混入另一只盘魂者。"""
    rows = []
    seen = set()
    actor_id = int(actor_id) if actor_id is not None else None
    if actor_id is None:
        return []
    wanted_instance = int(source_instance or 0)
    for (aid, instance), inst_rows in (index or {}).items():
        if (
            int(aid) != actor_id
            or int(instance or 0) not in {0, wanted_instance}
            or not inst_rows
        ):
            continue
        for row in inst_rows:
            ident = (row.get("timestamp"), row.get("x"), row.get("y"))
            if ident in seen:
                continue
            seen.add(ident)
            rows.append(row)
    for row in extra_rows or []:
        row_instance = int(row.get("instance") or 0)
        if row_instance not in {0, wanted_instance}:
            continue
        ident = (row.get("timestamp"), row.get("x"), row.get("y"))
        if ident in seen:
            continue
        seen.add(ident)
        rows.append(row)
    return rows


def _soulcoiler_event_coord_rows(events, actor_id, start_ts, end_ts):
    if actor_id is None or not events:
        return []
    wanted = int(actor_id)
    start = int(start_ts)
    end = int(end_ts)
    rows = []
    for event in events:
        ts = int(event.get("timestamp") or 0)
        if ts < start or ts > end:
            continue
        if event.get("sourceID") != wanted and event.get("targetID") != wanted:
            continue
        point = _npc_actor_point(event, wanted)
        if not point:
            continue
        if event.get("targetID") == wanted:
            instance = event.get("targetInstance") or event.get("targetInstanceID") or 0
        else:
            instance = event.get("sourceInstance") or event.get("sourceInstanceID") or 0
        rows.append({
            "timestamp": ts,
            "x": point[0],
            "y": point[1],
            "instance": int(instance or 0),
        })
    return rows


def _soulcoiler_rows(index, actor_id, source_instance):
    if not index or actor_id is None:
        return []
    rows = list(_npc_instance_rows(index, actor_id, source_instance) or [])
    if rows:
        return rows
    actor_id = int(actor_id)
    pooled = []
    for (aid, _inst), inst_rows in index.items():
        if int(aid) != actor_id or not inst_rows:
            continue
        pooled.extend(inst_rows)
    return pooled


def _soulcoiler_position_at(index, actor_id, source_instance, timestamp):
    """盘魂者坐标只取该时刻及之前的最后一点，不用爆炸后打断传送的未来样本。"""
    if not index or actor_id is None or timestamp is None:
        return None
    pos = _position_from_npc_rows(
        _soulcoiler_rows(index, actor_id, source_instance), timestamp, allow_future=False,
    )
    if pos:
        return pos
    best = None
    best_off = None
    actor_id = int(actor_id)
    for (aid, _inst), rows in index.items():
        if int(aid) != actor_id or not rows:
            continue
        candidate = _position_from_npc_rows(rows, timestamp, allow_future=False)
        if not candidate:
            continue
        off = abs(int(candidate.get("sampleOffsetMs") or 0))
        if best is None or off < best_off:
            best, best_off = candidate, off
    return best


def _soulcoiler_position_near(index, actor_id, source_instance, timestamp, window_ms=SOULCOILER_BOMB_POS_PAD_MS, extra_rows=None):
    """只取 timestamp ± window_ms 内最近的盘魂者坐标，不跨秒插值、不用窗口外的点。"""
    if timestamp is None:
        return None
    ts = int(timestamp)
    pad = int(window_ms)
    return _soulcoiler_position_in_window(
        index, actor_id, source_instance, ts - pad, ts + pad, ts, extra_rows=extra_rows,
    )


def _soulcoiler_position_in_window(index, actor_id, source_instance, start_ts, end_ts, prefer_ts=None, extra_rows=None):
    rows = _soulcoiler_instance_rows(
        index, actor_id, source_instance, extra_rows=extra_rows,
    )
    if not rows or start_ts is None or end_ts is None:
        return None
    start = int(start_ts)
    end = int(end_ts)
    if end < start:
        start, end = end, start
    in_window = [row for row in rows if start <= int(row["timestamp"]) <= end]
    if not in_window:
        return None
    prefer = int(prefer_ts) if prefer_ts is not None else end
    before_prefer = [row for row in in_window if int(row["timestamp"]) <= prefer]
    pool = before_prefer or in_window
    nearest = min(pool, key=lambda row: abs(int(row["timestamp"]) - prefer))
    offset = int(nearest["timestamp"] - prefer)
    return point_dict(
        (nearest["x"], nearest["y"]),
        timestamp=prefer,
        reliable=abs(offset) <= SOULCOILER_BOMB_POS_PAD_MS,
        offset_ms=offset,
    )


def _position_last_at_or_before(index, actor_id, source_instance, timestamp):
    """取该 NPC 实例在消失时刻（含）之前的最后一个坐标。"""
    if timestamp is None:
        return None
    rows = _npc_instance_rows(index, actor_id, source_instance)
    prior = [row for row in rows if int(row["timestamp"]) <= int(timestamp)]
    if not prior:
        return None
    last = prior[-1]
    offset = int(last["timestamp"] - timestamp)
    return point_dict(
        (last["x"], last["y"]),
        timestamp=timestamp,
        reliable=abs(offset) <= POSITION_RELIABLE_MS,
        offset_ms=offset,
    )


def _npc_instance_death_ts(deaths, actor_id, source_instance):
    if actor_id is None:
        return None
    wanted = int(source_instance or 0)
    times = []
    for event in deaths or []:
        if event.get("targetID") != actor_id:
            continue
        inst = event.get("targetInstance") or event.get("targetInstanceID") or 0
        if int(inst or 0) != wanted:
            continue
        times.append(int(event["timestamp"]))
    return min(times) if times else None


def _first_remove_after(events, target_id, apply_ts, spell_ids):
    spell_ids = set(spell_ids)
    return next(
        (
            event for event in events
            if event.get("targetID") == target_id
            and int(ability_id(event) or 0) in spell_ids
            and is_remove(event)
            and int(event.get("timestamp") or 0) >= int(apply_ts)
        ),
        None,
    )


def _gravebound_apply_in_window(events, target_id, start, end):
    return next(
        (
            event for event in events
            if event.get("targetID") == target_id
            and int(ability_id(event) or 0) in GRAVEBOUND_DEBUFF_IDS
            and is_apply(event)
            and start <= int(event.get("timestamp") or 0) <= end
        ),
        None,
    )


def _pet_owner_map(actor_rows):
    mapping = {}
    for row in actor_rows or []:
        owner = row.get("petOwner")
        if owner is None:
            continue
        mapping[int(row["id"])] = int(owner)
    return mapping


def _resolve_player_source(event, players, pet_owners):
    source_id = event.get("sourceID")
    if source_id in players:
        return source_id
    owner_id = pet_owners.get(source_id)
    if owner_id in players:
        return owner_id
    return None


def _player_is_healer(players, player_id):
    return role_to_basic((players.get(player_id) or {}).get("role")) == "healer"


def _alive_player_ids(players, deaths, friendly_casts, timestamp):
    alive = set(players)
    timeline = [
        (int(event.get("timestamp") or 0), "death", event.get("targetID"))
        for event in deaths or []
        if event.get("targetID") in players
    ]
    timeline.extend(
        (int(event.get("timestamp") or 0), "res", event.get("targetID"))
        for event in friendly_casts or []
        if event.get("targetID") in players
        and int(ability_id(event) or 0) in COMBAT_RES_SPELLS
        and event_type(event) in {"cast", "applybuff"}
    )
    for event_timestamp, kind, player_id in sorted(timeline):
        if event_timestamp >= timestamp:
            break
        if kind == "death":
            alive.discard(player_id)
        else:
            alive.add(player_id)
    return alive


def event_absorb_amount(event):
    return int(event.get("absorbed") or 0)


def _venom_spawn_point(event):
    """凝结毒液生成坐标：优先施法者自身，避免顶层目标污染。"""
    point = _source_self_point(event)
    if point:
        return point
    if event.get("targetID") in (None, event.get("sourceID")):
        return _xy_from_node(event) or _xy_from_node(event.get("resources"))
    return None


def _nearest_ground_puddle(ground, point, max_yards=VENOM_PICKUP_MAX_YARDS, kinds=None):
    """地上毒液中，落点/生成点距 point 最近且不超过 max_yards 的一团。"""
    if not ground or not point:
        return None
    allowed = set(kinds) if kinds else None
    best = None
    best_dist = None
    for puddle in ground:
        if allowed is not None and puddle.get("venomKind", VENOM_KIND_NORMAL) not in allowed:
            continue
        pos = _position_xy(puddle.get("position"))
        if not pos:
            continue
        dist = distance_yards(pos, point)
        if dist > max_yards:
            continue
        if best is None or dist < best_dist:
            best = puddle
            best_dist = dist
    return best


def _match_puddle_for_pickup(ground, player_xy, max_yards=VENOM_PICKUP_MAX_YARDS, kinds=None):
    """
    判断捡球是否对应已有地上毒液：用获得 debuff 时玩家位置与此前放球/生成位置是否过近。
    禁止「无近距时取最早落地」——会把远处另一球误绑并留下孤儿落点，造成去重失败。
    无可靠玩家坐标且场上仅一团时，只能归属该团。
    """
    allowed = set(kinds) if kinds else None
    candidates = [
        puddle for puddle in (ground or [])
        if allowed is None or puddle.get("venomKind", VENOM_KIND_NORMAL) in allowed
    ]
    if not candidates:
        return None
    if player_xy:
        return _nearest_ground_puddle(candidates, player_xy, max_yards=max_yards, kinds=allowed)
    if len(candidates) == 1:
        return candidates[0]
    return None


def _venom_kind_from_spell(spell_id):
    if int(spell_id or 0) in MUTAGENIC_VENOM_AURA_IDS or int(spell_id or 0) == VIRULENT_MUTATION_CAST:
        return VENOM_KIND_MUTATION
    return VENOM_KIND_NORMAL


def _venom_blast_yards(kind, radius=VIRULENT_BLAST_RADIUS_YARDS):
    return radius if kind == VENOM_KIND_MUTATION else None


def _venom_map_kind(kind, *, grounded=True):
    if kind == VENOM_KIND_MUTATION:
        return "virulent-mutation" if grounded else "virulent-mutation-spawn"
    return "ground-venom" if grounded else "venom-spawn"


def _puddle_snapshot(puddle, picked_up_at_ms=None):
    kind = puddle.get("venomKind") or VENOM_KIND_NORMAL
    return {
        "puddleID": puddle["puddleID"],
        "venomKind": kind,
        "blastRadiusYards": _venom_blast_yards(kind),
        "position": dict(puddle["position"]) if isinstance(puddle.get("position"), dict) else puddle.get("position"),
        "groundedFromMs": puddle["groundedFromMs"],
        "pickedUpAtMs": picked_up_at_ms,
        "transferCount": int(puddle.get("transferCount") or 0),
        "carriers": list(puddle.get("carriers") or []),
        "lastTickMs": puddle.get("lastTickMs"),
        "sourceID": puddle.get("sourceID"),
        "sourceInstance": puddle.get("sourceInstance"),
    }


def analyze_toxic_deluge(fight, casts, debuffs, position_index, actor_map, players, markers, damage_events=None):
    """
    凝结毒液支持多次搬运：
    - 地上毒液 ↔ 玩家不稳定毒液(1282419) 来回切换
    - 史诗烈毒变异体（1310544 / 诱变毒液 1310498·1310691）单独成团，不与普通毒液球混绑
    - 掉落后短窗口内再被捡起视为接力，不把中间落点当成最终场上位置
    - 有 1282408 伤害源坐标时刷新地上毒液位置
    """
    blast_radius = encounter_tuning(fight)["mutationRadiusYards"]
    fight_start = int(fight["startTime"])
    deluge_casts = [event for event in casts if int(ability_id(event) or 0) == TOXIC_DELUGE and is_cast_complete(event)]
    spawn_events = [
        event for event in casts
        if int(ability_id(event) or 0) in VENOM_SPAWN_CAST_IDS and is_cast_complete(event)
    ]
    rounds = []
    for index, deluge in enumerate(deluge_casts, start=1):
        start = int(deluge["timestamp"])
        end = int(deluge_casts[index]["timestamp"]) if index < len(deluge_casts) else int(fight["endTime"])
        spawns = []
        for event in _events_between(spawn_events, start, start + 12_000):
            spawn_point = _venom_spawn_point(event)
            venom_kind = _venom_kind_from_spell(ability_id(event))
            spawns.append({
                "spawnTimeMs": int(event["timestamp"]) - fight_start,
                "spawnTime": fmt_ms(int(event["timestamp"]) - fight_start),
                "sourceID": event.get("sourceID"),
                "sourceInstance": event.get("sourceInstance") or event.get("sourceInstanceID"),
                "spellID": int(ability_id(event) or 0),
                "venomKind": venom_kind,
                "blastRadiusYards": _venom_blast_yards(venom_kind, blast_radius),
                "position": point_dict(spawn_point, timestamp=int(event["timestamp"])) if spawn_point else None,
            })
        rounds.append({
            "index": index,
            "phase": phase_at(start - fight_start, markers),
            "timeMs": start - fight_start,
            "time": fmt_ms(start - fight_start),
            "spawnCount": len(spawns),
            "mutationSpawnCount": sum(1 for spawn in spawns if spawn.get("venomKind") == VENOM_KIND_MUTATION),
            "spawns": spawns,
            "carriers": [],
            "drops": [],
            "groundPuddles": [],
            "windowStart": start,
            "windowEnd": end,
        })

    ground = []  # 当前在地上的毒液
    carrying = {}  # playerID -> puddle being carried
    completed_puddles = []
    carrier_rows = []
    puddle_seq = 0

    def new_puddle(position, grounded_from_abs, spawn_meta=None, venom_kind=VENOM_KIND_NORMAL):
        nonlocal puddle_seq
        puddle_seq += 1
        kind = (spawn_meta or {}).get("venomKind") or venom_kind or VENOM_KIND_NORMAL
        return {
            "puddleID": puddle_seq,
            "venomKind": kind,
            "blastRadiusYards": _venom_blast_yards(kind, blast_radius),
            "position": point_dict(position, timestamp=grounded_from_abs) if isinstance(position, tuple) else position,
            "groundedFromMs": grounded_from_abs - fight_start,
            "pickedUpAtMs": None,
            "transferCount": 0,
            "carriers": [],
            "spawn": spawn_meta,
            "sourceID": (spawn_meta or {}).get("sourceID"),
            "sourceInstance": (spawn_meta or {}).get("sourceInstance"),
        }

    # 生成时先放到地上（若有可靠坐标）
    for round_row in rounds:
        for spawn in round_row["spawns"]:
            if not spawn.get("position"):
                continue
            abs_ts = fight_start + int(spawn["spawnTimeMs"])
            ground.append(new_puddle(
                spawn["position"], abs_ts, spawn_meta=spawn,
                venom_kind=spawn.get("venomKind") or VENOM_KIND_NORMAL,
            ))

    carry_events = sorted(
        (
            event for event in debuffs
            if int(ability_id(event) or 0) in VENOM_CARRY_AURA_IDS and event.get("targetID") in players
        ),
        key=lambda row: int(row.get("timestamp") or 0),
    )

    for event in carry_events:
        target_id = event.get("targetID")
        timestamp = int(event["timestamp"])
        rel_ms = timestamp - fight_start
        carry_kind = _venom_kind_from_spell(ability_id(event))
        if is_apply(event):
            if target_id in carrying:
                continue
            player_pos = _position_sample(position_index, target_id, timestamp)
            player_xy = _position_xy(player_pos)
            phase_floor = max([m['timeMs'] for m in markers if m.get('key') == 'p2' and m['timeMs'] <= rel_ms]+[-1])
            available = [p for p in ground if p.get("groundedFromMs") is not None
                         and phase_floor <= p["groundedFromMs"] <= rel_ms]
            puddle = _match_puddle_for_pickup(available, player_xy, kinds={carry_kind})
            if puddle is not None and puddle in ground:
                ground.remove(puddle)
                # 固化这一段「在地」区间，供撕裂时刻回放
                if puddle.get("groundedFromMs") is not None and puddle.get("position"):
                    completed_puddles.append(_puddle_snapshot(puddle, picked_up_at_ms=rel_ms))
                # 若距上次落地很近，记为接力搬运
                if puddle.get("carriers") and (
                    rel_ms - int(puddle.get("groundedFromMs") or rel_ms) <= VENOM_TRANSFER_WINDOW_MS
                ):
                    puddle["transferCount"] = int(puddle.get("transferCount") or 0) + 1
                puddle["pickedUpAtMs"] = rel_ms
                puddle["groundedFromMs"] = None
            else:
                puddle = new_puddle(player_pos, timestamp, venom_kind=carry_kind)
                puddle["pickedUpAtMs"] = rel_ms
                puddle["groundedFromMs"] = None
            puddle["venomKind"] = carry_kind
            puddle["blastRadiusYards"] = _venom_blast_yards(carry_kind, blast_radius)
            puddle.setdefault("carriers", []).append({
                **player_ref(players, actor_map, target_id),
                "applyTimeMs": rel_ms,
                "applyTime": fmt_ms(rel_ms),
                "pickupPosition": player_pos,
                "venomKind": carry_kind,
                "spellID": int(ability_id(event) or 0),
            })
            carrying[target_id] = puddle
            carrier_rows.append({
                **player_ref(players, actor_map, target_id),
                "phase": phase_at(rel_ms, markers),
                "applyTimeMs": rel_ms,
                "applyTime": fmt_ms(rel_ms),
                "removeTimeMs": None,
                "pickupPosition": player_pos,
                "removeTime": None,
                "carryDurationMs": None,
                "dropPosition": None,
                "puddleID": puddle["puddleID"],
                "transferCount": puddle.get("transferCount") or 0,
                "venomKind": carry_kind,
                "blastRadiusYards": _venom_blast_yards(carry_kind, blast_radius),
                "spellID": int(ability_id(event) or 0),
                "kind": "pickup",
            })
            continue

        if not is_remove(event):
            continue
        if target_id not in carrying:
            continue
        puddle = carrying.pop(target_id, None)
        drop_position = _position_sample(position_index, target_id, timestamp)
        apply_rel = None
        if puddle and puddle.get("carriers"):
            apply_rel = puddle["carriers"][-1].get("applyTimeMs")
        drop_kind = (puddle or {}).get("venomKind") or carry_kind
        row = {
            **player_ref(players, actor_map, target_id),
            "phase": phase_at(rel_ms, markers),
            "applyTimeMs": apply_rel,
            "applyTime": fmt_ms(apply_rel) if apply_rel is not None else None,
            "removeTimeMs": rel_ms,
            "removeTime": fmt_ms(rel_ms),
            "carryDurationMs": (rel_ms - apply_rel) if apply_rel is not None else None,
            "dropPosition": drop_position,
            "pickupPosition": (puddle.get("carriers") or [{}])[-1].get("pickupPosition") if puddle else None,
            "puddleID": (puddle or {}).get("puddleID"),
            "transferCount": (puddle or {}).get("transferCount") or 0,
            "venomKind": drop_kind,
            "blastRadiusYards": _venom_blast_yards(drop_kind, blast_radius),
            "spellID": int(ability_id(event) or 0),
            "kind": "drop",
            "finalDrop": True,
        }
        carrier_rows.append(row)
        if puddle is None:
            puddle = new_puddle(drop_position, timestamp, venom_kind=drop_kind)
        else:
            if drop_position:
                puddle["position"] = drop_position
            puddle["groundedFromMs"] = rel_ms
            puddle["pickedUpAtMs"] = None
            puddle["venomKind"] = drop_kind
            puddle["blastRadiusYards"] = _venom_blast_yards(drop_kind, blast_radius)
            if puddle.get("carriers"):
                puddle["carriers"][-1].update({
                    "removeTimeMs": rel_ms,
                    "removeTime": fmt_ms(rel_ms),
                    "carryDurationMs": row["carryDurationMs"],
                    "dropPosition": drop_position,
                    "venomKind": drop_kind,
                })
        ground.append(puddle)
        round_match = next((item for item in reversed(rounds) if item["timeMs"] <= rel_ms), rounds[-1] if rounds else None)
        if round_match is not None:
            round_match["carriers"].append(row)
            round_match["drops"].append(row)

    # 用 1282408 地上毒液伤害源坐标刷新仍在地上的落点
    for event in sorted(damage_events or [], key=lambda row: int(row.get("timestamp") or 0)):
        if int(ability_id(event) or 0) != COALESCED_VENOM_DAMAGE:
            continue
        source_id = event.get("sourceID")
        source_instance = event.get("sourceInstance") or event.get("sourceInstanceID")
        point = _source_self_point(event)
        if not point:
            # 伤害打在玩家上时，顶层 x/y 常是玩家，不能用
            continue
        timestamp = int(event["timestamp"])
        rel_ms = timestamp - fight_start
        matched = None
        for puddle in ground:
            if source_id is not None and puddle.get("sourceID") == source_id:
                if source_instance is None or puddle.get("sourceInstance") in (None, source_instance):
                    matched = puddle
                    break
        if matched is None:
            matched = _nearest_ground_puddle(
                ground, point, max_yards=VENOM_PICKUP_MAX_YARDS, kinds={VENOM_KIND_NORMAL},
            )
        if matched is None:
            continue
        matched["position"] = point_dict(point, timestamp=timestamp)
        matched["lastTickMs"] = rel_ms
        if matched.get("sourceID") is None:
            matched["sourceID"] = source_id
            matched["sourceInstance"] = source_instance

    # 收尾：仍在地上的记为未再被捡起的区间
    for puddle in list(ground):
        if puddle.get("position") and puddle.get("groundedFromMs") is not None:
            completed_puddles.append(_puddle_snapshot(puddle, picked_up_at_ms=None))

    for round_row in rounds:
        next_ms = rounds[round_row["index"]]["timeMs"] if round_row["index"] < len(rounds) else 10**12
        round_row["groundPuddles"] = [
            puddle for puddle in completed_puddles
            if puddle.get("position")
            and puddle.get("groundedFromMs") is not None
            and round_row["timeMs"] <= int(puddle["groundedFromMs"]) < next_ms
        ]
        last_drop_by_puddle = {}
        for drop in round_row["drops"]:
            if drop.get("puddleID") is None:
                continue
            last_drop_by_puddle[drop["puddleID"]] = drop
        for drop in round_row["drops"]:
            drop["finalDrop"] = last_drop_by_puddle.get(drop.get("puddleID")) is drop

    drop_rows = [row for row in carrier_rows if row.get("kind") == "drop"]
    mutation_drops = [row for row in drop_rows if row.get("venomKind") == VENOM_KIND_MUTATION]
    return {
        "rounds": rounds,
        "carriers": drop_rows,
        "pickups": [row for row in carrier_rows if row.get("kind") == "pickup"],
        "groundPuddles": completed_puddles,
        "hasVirulentMutation": bool(mutation_drops) or any(
            spawn.get("venomKind") == VENOM_KIND_MUTATION
            for round_row in rounds
            for spawn in round_row.get("spawns") or []
        ),
        "virulentBlastRadiusYards": blast_radius,
        "evidenceNote": (
            "凝结毒液按落地/拾取状态机追踪，支持多次接力；"
            f"掉落后 {VENOM_TRANSFER_WINDOW_MS}ms 内再捡起记为搬运中转；"
            f"捡球时用玩家位置与放球点是否 ≤{VENOM_PICKUP_MAX_YARDS:g} 码判断同一球；"
            "史诗烈毒变异体（1310544）与诱变毒液（1310498/1310691）单独成团，"
            f"最终落点绘制 {blast_radius:g} 码引爆圈；"
            "撕裂几何只用「释放前仍在地上」的区间，优先 1282408 伤害源坐标。"
        ),
    }


def build_active_venom_points(toxic_deluge):
    """撕裂几何用「某时刻仍在地上」的凝结毒液，不是每一次 debuff 消失落点。"""
    blast_radius = toxic_deluge.get("virulentBlastRadiusYards", VIRULENT_BLAST_RADIUS_YARDS)
    points = []
    for puddle in toxic_deluge.get("groundPuddles") or []:
        position = puddle.get("position")
        grounded_from = puddle.get("groundedFromMs")
        if not position or grounded_from is None:
            continue
        kind = puddle.get("venomKind") or VENOM_KIND_NORMAL
        points.append({
            "kind": _venom_map_kind(kind, grounded=True),
            "venomKind": kind,
            "blastRadiusYards": _venom_blast_yards(kind, blast_radius),
            "puddleID": puddle.get("puddleID"),
            "position": position,
            "groundedFromMs": grounded_from,
            "pickedUpAtMs": puddle.get("pickedUpAtMs"),
            "transferCount": puddle.get("transferCount") or 0,
            "carriers": puddle.get("carriers") or [],
            "carrier": (puddle.get("carriers") or [{}])[-1].get("player") if puddle.get("carriers") else None,
            "player": (puddle.get("carriers") or [{}])[-1].get("player") if puddle.get("carriers") else None,
            "lastSeenMs": puddle.get("lastTickMs") if puddle.get("lastTickMs") is not None else grounded_from,
            "sourceID": puddle.get("sourceID"),
            "sourceInstance": puddle.get("sourceInstance"),
        })
    # 兼容旧结构：若尚无 groundPuddles，回退到最终 drops（仍去重接力）
    if points:
        return points
    for round_row in toxic_deluge.get("rounds") or []:
        for drop in round_row.get("drops") or []:
            if drop.get("dropPosition"):
                drop_kind = drop.get("venomKind") or VENOM_KIND_NORMAL
                points.append({
                    "kind": _venom_map_kind(drop_kind, grounded=True),
                    "venomKind": drop_kind,
                    "blastRadiusYards": _venom_blast_yards(drop_kind, blast_radius) if drop.get("finalDrop") else None,
                    "carrier": drop.get("player"),
                    "player": drop.get("player"),
                    "playerID": drop.get("playerID"),
                    "position": drop["dropPosition"],
                    "groundedFromMs": drop.get("removeTimeMs"),
                    "pickedUpAtMs": None,
                    "lastSeenMs": drop.get("removeTimeMs"),
                    "transferCount": drop.get("transferCount") or 0,
                })
    return points


def active_venom_before_cast(points, cast_ts, fight_start, after_ms=None):
    """
    本轮撕裂应显示的凝结毒液：
    - 已在释放前落地，且释放前尚未再被捡起；
    - 上一轮撕裂后场上毒液已消除，故只保留落地时刻落在 (after_ms, cast] 的球
      （即本轮时间窗内生成/搬动落下的）。
    after_ms 为战斗相对毫秒；None 表示不设下界（首轮或未提供清场时刻）。
    """
    cast_rel = int(cast_ts) - int(fight_start)
    active = []
    for point in points or []:
        grounded = point.get("groundedFromMs")
        if grounded is None or int(grounded) > cast_rel:
            continue
        if after_ms is not None and int(grounded) <= int(after_ms):
            continue
        picked = point.get("pickedUpAtMs")
        if picked is not None and int(picked) <= cast_rel:
            continue
        active.append(point)
    return active


def previous_cone_sever_rel_ms(casts, cast_ts, fight_start):
    """上一轮锥形撕裂（撕裂/凋零撕裂）的战斗相对时刻；没有则 None。"""
    cast_abs = int(cast_ts)
    previous = [
        int(event["timestamp"])
        for event in (casts or [])
        if int(ability_id(event) or 0) in CONE_SEVER_IDS
        and is_cast_complete(event)
        and int(event.get("timestamp") or 0) < cast_abs
    ]
    if not previous:
        return None
    return max(previous) - int(fight_start)


def _rupture_stack_gain(debuffs, start, end):
    gains = []
    for event in _events_between(debuffs, start, end, {VENOM_RUPTURE}):
        if not is_apply(event):
            continue
        gains.append({
            "targetID": event.get("targetID"),
            "timestamp": int(event["timestamp"]),
            "stacks": int(event.get("stack") or 1),
        })
    return gains


def analyze_cone_sever(
    label,
    cast_ids,
    fight,
    casts,
    debuffs,
    position_index,
    actor_map,
    players,
    markers,
    active_points,
    actor_catalog,
    boss_actor_id=None,
    origin_index=None,
    npc_position_index=None,
):
    completed = [event for event in casts if int(ability_id(event) or 0) in cast_ids and is_cast_complete(event)]
    rounds = []
    for index, cast in enumerate(completed, start=1):
        timestamp = int(cast["timestamp"])
        source_id = cast.get("sourceID")
        fight_start = int(fight["startTime"])
        venom_pts = [
            point for point in active_points
            if point.get("kind") in {"ground-venom", "dropped-venom", "virulent-mutation"}
            or point.get("venomKind") in {VENOM_KIND_NORMAL, VENOM_KIND_MUTATION}
        ]
        manifest_pts = [point for point in active_points if point.get("kind") == "manifestation"]
        other_pts = [
            point for point in active_points
            if point.get("kind") not in {"ground-venom", "dropped-venom", "virulent-mutation", "manifestation"}
            and point.get("venomKind") not in {VENOM_KIND_NORMAL, VENOM_KIND_MUTATION}
        ]
        venom_after_ms = previous_cone_sever_rel_ms(casts, timestamp, fight_start)
        nearby_raw = (
            active_venom_before_cast(venom_pts, timestamp, fight_start, after_ms=venom_after_ms)
            + active_fixations_before_cast(manifest_pts, timestamp, fight_start)
            + active_points_near_cast(other_pts, timestamp, fight_start)
        )
        nearby_points = []
        for point in nearby_raw:
            if point.get("kind") == "manifestation":
                nearby_points.append(
                    enrich_manifest_point_at(point, npc_position_index or {}, position_index, timestamp)
                )
            else:
                nearby_points.append(point)
        spell = int(ability_id(cast) or 0)
        lock_ms, tank_id, facing_rule, _debuff = resolve_sever_facing_lock(
            casts, cast, debuffs=debuffs, debuff_ids=CAST_TO_TANK_DEBUFF_IDS.get(spell),
        )
        if tank_id is None:
            tank_id = cast.get("targetID")
        origin, facing_radians, facing_state, facing_inferred, tank_state = resolve_caster_origin_facing(
            position_index,
            source_id,
            boss_actor_id,
            timestamp,
            hint_points=nearby_points,
            target_id=tank_id,
            origin_actor_id=source_id or boss_actor_id,
            origin_index=origin_index,
            cast_event=cast,
            facing_timestamp=lock_ms,
            allow_hint_override=facing_rule not in {"tank-debuff", "cast-last-second"},
        )
        tank_position = None
        if tank_state:
            tank_position = point_dict(
                (tank_state["x"], tank_state["y"]),
                timestamp=lock_ms,
                reliable=tank_state.get("reliable"),
                offset_ms=tank_state.get("sampleOffsetMs"),
            )
        elif tank_id is not None:
            fallback = position_at(position_index, tank_id, lock_ms, max_offset_ms=POSITION_RELIABLE_MS)
            if fallback:
                tank_position = point_dict(
                    (fallback["x"], fallback["y"]),
                    timestamp=lock_ms,
                    reliable=fallback.get("reliable"),
                    offset_ms=fallback.get("sampleOffsetMs"),
                )
        in_cone = []
        uncleared = []
        cleared_manifests = []
        annotated_nearby = []
        classify_manifests = any(point.get("kind") == "manifestation" for point in nearby_points)
        for point in nearby_points:
            position = point.get("position") or point.get("manifestPosition")
            inside = False
            if position and origin is not None and facing_radians is not None:
                inside = in_frontal_cone(origin, facing_radians, (position["x"], position["y"]))
            if classify_manifests and point.get("kind") == "manifestation":
                verdict = classify_fixation_after_sever(point, timestamp, fight_start, inside)
                row = {**point, **verdict}
                annotated_nearby.append(row)
                if inside:
                    in_cone.append(row)
                if verdict["uncleared"]:
                    uncleared.append(row)
                else:
                    cleared_manifests.append(row)
            else:
                annotated_nearby.append(point)
                if inside:
                    in_cone.append(point)
        nearby_points = annotated_nearby
        rupture_gains = _rupture_stack_gain(debuffs, timestamp, timestamp + 2_500)
        inferred_cleared = max((row["stacks"] for row in rupture_gains), default=len(in_cone))
        facing_note = {
            "tank-debuff": "朝向按坦克获得易伤 debuff 时的位置锁定",
            "cast-last-second": "朝向按读条最后一秒的坦克位置锁定",
            "cast-complete": "朝向按读条完成时的坦克位置估算",
        }.get(facing_rule, "朝向按坦克位置估算")
        if classify_manifests:
            evidence_note = (
                f"具象消除以凝视 debuff 在释放后 {SOUL_SEVER_CLEAR_WINDOW_MS}ms 内是否消失为准；"
                f"锥内 {len([p for p in in_cone if p.get('kind') == 'manifestation'])}，"
                f"debuff 清掉 {len(cleared_manifests)}，未消掉 {len(uncleared)}；"
                "红线仅连未消掉凝视的玩家。"
            )
        else:
            evidence_note = (
                "示意图仅显示上一轮撕裂至本轮之间落地/搬动的毒液球；"
                "几何清场数来自锥形内的凝结毒液/恐惧具象坐标。"
            )
        rounds.append({
            "index": index,
            "label": label,
            "phase": phase_at(timestamp - int(fight["startTime"]), markers),
            "spellID": spell,
            "timeMs": timestamp - int(fight["startTime"]),
            "time": fmt_ms(timestamp - int(fight["startTime"])),
            "casterID": source_id,
            "caster": actor_name(actor_map, source_id),
            "origin": point_dict(origin, timestamp=timestamp, reliable=bool(facing_state and facing_state.get("reliable"))),
            "originRule": (facing_state or {}).get("positionRule"),
            "tankID": tank_id,
            "tankPosition": tank_position,
            "facingLockMs": lock_ms - fight_start,
            "facingRule": facing_rule,
            "facingRadians": facing_radians,
            "facingInferred": facing_inferred,
            "coneRadiusYards": CONE_RADIUS_YARDS,
            "coneHalfAngleDeg": CONE_HALF_ANGLE_DEG,
            "conePolygon": cone_polygon(origin, facing_radians),
            "clearedByGeometry": len(in_cone),
            "inferredClearedCount": inferred_cleared,
            "ruptureEvents": rupture_gains,
            "targetsInCone": in_cone,
            "nearbyPoints": nearby_points,
            "unclearedManifestations": uncleared if classify_manifests else [],
            "clearedManifestations": cleared_manifests if classify_manifests else [],
            "clearedByDebuff": len(cleared_manifests) if classify_manifests else None,
            "unclearedCount": len(uncleared) if classify_manifests else None,
            "evidenceNote": evidence_note,
        })
    return {"label": label, "castIDs": sorted(cast_ids), "rounds": rounds}


MYTHIC_DIFFICULTY = 5
MYTHIC_SEVER_PAIR_RULE = (
    "史诗 P1/P3：每两轮撕裂处理一轮剧毒洪流的凝结毒液和烈毒变异体。"
    "默认第一下劈场地南侧，第二下劈场地北侧。"
)


def _is_ground_venom_point(point):
    kind = point.get("kind")
    if kind in {"manifestation", "manifest-target", "venom-spawn", "virulent-mutation-spawn"}:
        return False
    return kind in {"ground-venom", "dropped-venom", "virulent-mutation"} or point.get("venomKind") in {
        VENOM_KIND_NORMAL, VENOM_KIND_MUTATION,
    }


def venom_arena_side(point):
    """场地中心以南（WCL Y 更小、示意图更靠下）为南侧，其余为北侧。"""
    coords = _position_xy((point or {}).get("position") or point)
    if not coords:
        return None
    return "south" if coords[1] < arena_center_units()[1] else "north"


def _next_deluge_time_ms(deluge_rounds, deluge):
    start = int(deluge.get("timeMs") or 0)
    later = [int(row.get("timeMs") or 0) for row in deluge_rounds or [] if int(row.get("timeMs") or 0) > start]
    return min(later) if later else 10**15


def _orbs_for_deluge_side(venom_points, sever_time_ms, side, window_start, window_end):
    """本轮撕裂应清的球：该次剧毒洪流落地、释放时仍在地上、且位于指定一侧。"""
    chosen = {}
    loose = []
    for point in venom_points or []:
        if not _is_ground_venom_point(point) or venom_arena_side(point) != side:
            continue
        grounded = point.get("groundedFromMs")
        if grounded is None:
            continue
        grounded = int(grounded)
        if grounded < int(window_start) or grounded >= int(window_end) or grounded > int(sever_time_ms):
            continue
        picked = point.get("pickedUpAtMs")
        if picked is not None and int(picked) <= int(sever_time_ms):
            continue
        key = point.get("puddleID")
        if key is None:
            loose.append(point)
            continue
        previous = chosen.get(key)
        if previous is None or grounded >= int(previous.get("groundedFromMs") or 0):
            chosen[key] = point
    return list(chosen.values()) + loose


def _apply_mythic_side_assignment(row, assigned, side, side_label, slot, pair_index, deluge):
    origin_xy = _position_xy(row.get("origin"))
    facing = row.get("facingRadians")
    marked = []
    for point in assigned:
        coords = _position_xy(point.get("position"))
        inside = bool(coords and in_frontal_cone(origin_xy, facing, coords))
        marked.append({
            **point,
            "assignedSide": side,
            "assignedSideLabel": side_label,
            "inCone": inside,
        })
    non_venom = [point for point in (row.get("nearbyPoints") or []) if not _is_ground_venom_point(point)]
    row["nearbyPoints"] = non_venom + marked
    kept_hits = [point for point in (row.get("targetsInCone") or []) if not _is_ground_venom_point(point)]
    venom_hits = [point for point in marked if point.get("inCone")]
    row["targetsInCone"] = kept_hits + venom_hits
    row["clearedByGeometry"] = len(row["targetsInCone"])
    normal = sum(1 for point in marked if point.get("venomKind") != VENOM_KIND_MUTATION)
    mutation = len(marked) - normal
    missed = len(marked) - len(venom_hits)
    deluge_index = deluge.get("index") if deluge else None
    row["mythicDelugePair"] = {
        "enabled": True,
        "pairIndex": pair_index,
        "slot": slot,
        "side": side,
        "sideLabel": side_label,
        "delugeIndex": deluge_index,
        "delugeTime": deluge.get("time") if deluge else None,
        "assignedCount": len(marked),
        "assignedInCone": len(venom_hits),
        "assignedMissed": missed,
        "normalCount": normal,
        "mutationCount": mutation,
    }
    sentence = (
        f"史诗默认第 {slot} 下劈{side_label}：剧毒洪流 #{deluge_index or '—'}，"
        f"应清 {len(marked)}（凝结毒液 {normal}，烈毒变异体 {mutation}），"
        f"锥内 {len(venom_hits)}，未覆盖 {missed}。"
        "南侧为场地中心以南，北侧为中心以北。"
    )
    if row.get("label") == "凋零撕裂":
        prior = (row.get("evidenceNote") or "").rstrip("。")
        row["evidenceNote"] = f"{prior}。{sentence}" if prior else sentence
    else:
        row["evidenceNote"] = sentence
    if not deluge:
        return
    clear = deluge.setdefault("mythicSeverClear", {
        "southSeverIndex": None,
        "northSeverIndex": None,
        "southLabel": None,
        "northLabel": None,
        "southAssigned": 0,
        "northInCone": 0,
        "southMissed": 0,
        "northAssigned": 0,
        "southInCone": 0,
        "northMissed": 0,
    })
    prefix = "south" if side == "south" else "north"
    clear[f"{prefix}SeverIndex"] = row.get("index")
    clear[f"{prefix}Label"] = f"{row.get('label')} #{row.get('index')}"
    clear[f"{prefix}Assigned"] = len(marked)
    clear[f"{prefix}InCone"] = len(venom_hits)
    clear[f"{prefix}Missed"] = missed


def annotate_mythic_sever_deluge_pairs(fight, toxic_deluge, sever, blighted_sever, venom_points):
    """史诗 P1 撕裂、P3 凋零撕裂：两轮一组，分别对应同一轮剧毒洪流的南侧和北侧。"""
    if int((fight or {}).get("difficulty") or 0) != MYTHIC_DIFFICULTY or not toxic_deluge:
        return
    points = venom_points or build_active_venom_points(toxic_deluge)
    all_deluges = list(toxic_deluge.get("rounds") or [])
    for phase, result in (("p1", sever), ("p3", blighted_sever)):
        if not result:
            continue
        phase_severs = sorted(
            [row for row in (result.get("rounds") or []) if row.get("phase") == phase],
            key=lambda row: int(row.get("timeMs") or 0),
        )
        if not phase_severs:
            continue
        phase_deluges = sorted(
            [row for row in all_deluges if row.get("phase") == phase],
            key=lambda row: int(row.get("timeMs") or 0),
        )
        deluge_cursor = 0
        for pair_index, start in enumerate(range(0, len(phase_severs), 2), start=1):
            chunk = phase_severs[start:start + 2]
            first_time = int(chunk[0].get("timeMs") or 0)
            deluge = None
            if deluge_cursor < len(phase_deluges) and int(phase_deluges[deluge_cursor].get("timeMs") or 0) <= first_time:
                deluge = phase_deluges[deluge_cursor]
                deluge_cursor += 1
            window_start = int(deluge["timeMs"]) if deluge else None
            window_end = _next_deluge_time_ms(all_deluges, deluge) if deluge else None
            for slot_index, row in enumerate(chunk):
                side, side_label = ("south", "南侧") if slot_index == 0 else ("north", "北侧")
                assigned = []
                if deluge is not None:
                    assigned = _orbs_for_deluge_side(
                        points, int(row.get("timeMs") or 0), side, window_start, window_end,
                    )
                _apply_mythic_side_assignment(
                    row, assigned, side, side_label, slot_index + 1, pair_index, deluge,
                )
        result["mythicPairing"] = {"enabled": True, "phase": phase, "rule": MYTHIC_SEVER_PAIR_RULE}
    if any((result or {}).get("mythicPairing") for result in (sever, blighted_sever)):
        note = toxic_deluge.get("evidenceNote") or ""
        if MYTHIC_SEVER_PAIR_RULE not in note:
            toxic_deluge["evidenceNote"] = f"{note}{MYTHIC_SEVER_PAIR_RULE}"


def analyze_guillotine(
    fight,
    casts,
    damage,
    debuffs,
    position_index,
    actor_map,
    players,
    markers,
    cast_ids,
    label,
    damage_ids=None,
    mark_ids=None,
    pulse_damage_id=None,
    in_range_damage_id=None,
    origin_index=None,
    boss_actor_id=None,
):
    """分摊后是否仍在 40 码内：用脉冲伤害后的范围内伤害证据，不用固定延迟估位置。

    P1：全团寡妇之触(1283631)时，圈内额外寡妇之吻(1283623)。
    P3：全团死亡低语(1299401)时，圈内额外死亡之拥(1299396)。
    """
    damage_ids = set(damage_ids or {GUILLOTINE_DAMAGE_ID})
    mark_ids = set(mark_ids or {GUILLOTINE_MARK})
    pulse_id = int(pulse_damage_id or WIDOW_TOUCH_DAMAGE_ID)
    in_range_id = int(in_range_damage_id or WIDOW_KISS_DAMAGE_ID)
    completed = [event for event in casts if int(ability_id(event) or 0) in cast_ids and is_cast_complete(event)]
    rounds = []
    for index, cast in enumerate(completed, start=1):
        timestamp = int(cast["timestamp"])
        share_hits = [
            event for event in _events_between(damage, timestamp - 500, timestamp + 3_000, damage_ids)
            if event.get("targetID") in players
        ]
        participants_by_id = {}
        for event in share_hits:
            target_id = event.get("targetID")
            hit_ts = int(event["timestamp"])
            position = (
                _position_sample(position_index, target_id, hit_ts)
                or _position_sample(position_index, target_id, timestamp)
            )
            prev = participants_by_id.get(target_id)
            amount = event_amount(event)
            if prev is None or float(amount or 0) >= float(prev.get("amount") or 0):
                participants_by_id[target_id] = {
                    **player_ref(players, actor_map, target_id),
                    "position": position or (prev or {}).get("position"),
                    "amount": amount,
                    "shareTimeMs": hit_ts - int(fight["startTime"]),
                }
        # 伤害事件缺失时，用处斩/冷酷处斩标记/治疗吸收施加补全分摊名单
        if not participants_by_id:
            for event in _events_between(debuffs, timestamp - 500, timestamp + 3_000, mark_ids):
                if not is_apply(event):
                    continue
                target_id = event.get("targetID")
                if target_id not in players or target_id in participants_by_id:
                    continue
                apply_ts = int(event["timestamp"])
                position = (
                    _position_sample(position_index, target_id, apply_ts)
                    or _position_sample(position_index, target_id, timestamp)
                )
                participants_by_id[target_id] = {
                    **player_ref(players, actor_map, target_id),
                    "position": position,
                    "amount": None,
                    "shareTimeMs": apply_ts - int(fight["startTime"]),
                }
        participants = list(participants_by_id.values())
        centroid = None
        if participants:
            xs = [row["position"]["x"] for row in participants if row.get("position")]
            ys = [row["position"]["y"] for row in participants if row.get("position")]
            if xs and ys:
                centroid = point_dict((sum(xs) / len(xs), sum(ys) / len(ys)))
        share_anchor = timestamp
        if share_hits:
            share_anchor = max(int(event["timestamp"]) for event in share_hits)
        elif participants:
            rels = [row.get("shareTimeMs") for row in participants if row.get("shareTimeMs") is not None]
            if rels:
                share_anchor = int(fight["startTime"]) + max(int(value) for value in rels)
        # 分摊后下一波全团脉冲；同波吃到范围内伤害 = 仍在 40 码内
        pulse_wave = _events_between(
            damage, share_anchor, share_anchor + GUILLOTINE_PULSE_SEARCH_MS, {pulse_id},
        )
        pulse_wave = [event for event in pulse_wave if event.get("targetID") in players]
        pulse_ts = None
        follow_up = []
        if pulse_wave:
            first_pulse = min(int(event["timestamp"]) for event in pulse_wave)
            pulse_ts = first_pulse
            pulse_cluster = [
                event for event in pulse_wave
                if abs(int(event["timestamp"]) - first_pulse) <= GUILLOTINE_PULSE_MATCH_MS
            ]
            if pulse_cluster:
                pulse_ts = max(int(event["timestamp"]) for event in pulse_cluster)
            in_range_hits = [
                event for event in _events_between(
                    damage,
                    first_pulse - GUILLOTINE_PULSE_MATCH_MS,
                    pulse_ts + GUILLOTINE_PULSE_MATCH_MS,
                    {in_range_id},
                )
                if event.get("targetID") in players
            ]
            by_id = {}
            for event in in_range_hits:
                target_id = event.get("targetID")
                hit_ts = int(event["timestamp"])
                position = (
                    _position_sample(position_index, target_id, hit_ts)
                    or _position_sample(position_index, target_id, pulse_ts)
                )
                distance = None
                if position and centroid:
                    distance = round(
                        distance_yards((position["x"], position["y"]), (centroid["x"], centroid["y"])),
                        1,
                    )
                prev = by_id.get(target_id)
                if prev is None or hit_ts <= int(prev.get("_hitTs") or hit_ts):
                    by_id[target_id] = {
                        **player_ref(players, actor_map, target_id),
                        "distanceFromShareYards": distance,
                        "position": position,
                        "stillInsideRange": True,
                        "checkTimeMs": hit_ts - int(fight["startTime"]),
                        "inRangeDamageID": in_range_id,
                        "_hitTs": hit_ts,
                    }
            follow_up = [{k: v for k, v in row.items() if k != "_hitTs"} for row in by_id.values()]
            follow_up.sort(key=lambda row: (row.get("player") or "", row.get("playerID") or 0))
        marked_players = sorted({
            event.get("targetID")
            for event in _events_between(debuffs, timestamp - 1_000, timestamp + 30_000, mark_ids)
            if is_apply(event) and event.get("targetID") in players
        })
        caster_id = cast.get("sourceID") if cast.get("sourceID") is not None else boss_actor_id
        boss_position = boss_field_position(origin_index, caster_id, timestamp, cast_event=cast)
        rounds.append({
            "index": index,
            "label": label,
            "phase": phase_at(timestamp - int(fight["startTime"]), markers),
            "spellID": int(ability_id(cast) or 0),
            "timeMs": timestamp - int(fight["startTime"]),
            "time": fmt_ms(timestamp - int(fight["startTime"])),
            "participantCount": len(participants),
            "participants": participants,
            "shareCentroid": centroid,
            "bossPosition": boss_position,
            "dangerRadiusYards": GUILLOTINE_RANGE_YARDS,
            "pulseDamageID": pulse_id,
            "inRangeDamageID": in_range_id,
            "pulseTimeMs": (pulse_ts - int(fight["startTime"])) if pulse_ts is not None else None,
            "stillInsideRange": follow_up,
            "guillotineMarks": [player_ref(players, actor_map, player_id) for player_id in marked_players],
        })
    return {"label": label, "rounds": rounds}


def _find_dreadmarch_remove(debuffs, target_id, apply_ts, fight_end):
    return next(
        (
            row for row in debuffs
            if row.get("targetID") == target_id
            and int(ability_id(row) or 0) in DREADMARCH_DEBUFF_IDS
            and is_remove(row)
            and int(row["timestamp"]) >= int(apply_ts)
        ),
        None,
    )


def _debuff_activity_near(debuffs, target_id, spell_ids, timestamp, window_ms):
    """目标在 timestamp 附近是否有指定 debuff 的施加/刷新/移除。"""
    hits = []
    low = int(timestamp) - int(window_ms)
    high = int(timestamp) + int(window_ms)
    for event in debuffs or []:
        if event.get("targetID") != target_id:
            continue
        if int(ability_id(event) or 0) not in spell_ids:
            continue
        ts = int(event.get("timestamp") or 0)
        if low <= ts <= high and (is_apply(event) or is_remove(event)):
            hits.append(event)
    return hits


def _annotate_dreadmarch_manifest_collisions(
    applications, cast_times, fight_start, fight_end, debuffs, use_malevolent_resonance=False,
):
    """
    每轮恐惧行军：第一次成功救人之后、下一轮 Boss 释放之前，
    新获得的 1297445 视为撞到恐惧具象（或由其引发的二次心控）。
    史诗可额外用恶毒共鸣印证；英雄仅结合凝视变化。
    """
    first_rescue_by_round = {}
    for row in applications:
        round_index = row.get("roundIndex")
        if not round_index or not row.get("rescued") or row.get("removedTimeMs") is None:
            continue
        remove_abs = int(fight_start) + int(row["removedTimeMs"])
        prev = first_rescue_by_round.get(round_index)
        if prev is None or remove_abs < prev:
            first_rescue_by_round[round_index] = remove_abs

    for row in applications:
        apply_abs = int(fight_start) + int(row["appliedTimeMs"])
        round_index = row.get("roundIndex")
        cast_abs = None
        if row.get("castTimeMs") is not None:
            cast_abs = int(fight_start) + int(row["castTimeMs"])
        elif round_index and 1 <= int(round_index) <= len(cast_times):
            cast_abs = cast_times[int(round_index) - 1]

        next_cast_abs = int(fight_end)
        if cast_abs is not None:
            later = [ts for ts in cast_times if ts > cast_abs]
            if later:
                next_cast_abs = min(later)
        elif round_index and int(round_index) < len(cast_times):
            next_cast_abs = cast_times[int(round_index)]

        first_rescue_abs = first_rescue_by_round.get(round_index)
        # 也可能跨轮：落在「上一轮首次救人 → 本轮施法」之间
        if first_rescue_abs is None and round_index and int(round_index) > 1:
            first_rescue_abs = first_rescue_by_round.get(int(round_index) - 1)
            if cast_abs is not None:
                next_cast_abs = cast_abs

        near_initial_wave = (
            cast_abs is not None
            and cast_abs - 1_500 <= apply_abs <= cast_abs + DREADMARCH_INITIAL_APPLY_MS
        )
        in_post_rescue_window = (
            first_rescue_abs is not None
            and first_rescue_abs < apply_abs < next_cast_abs
        )

        fixation_hits = _debuff_activity_near(
            debuffs, row.get("playerID"), {FIXATION}, apply_abs, DREADMARCH_FIXATION_HINT_MS,
        )
        resonance_hits = []
        if use_malevolent_resonance:
            resonance_hits = _debuff_activity_near(
                debuffs, row.get("playerID"), MANIFEST_COLLISION_DEBUFF_IDS, apply_abs, DREADMARCH_FIXATION_HINT_MS,
            )
        fixation_hint = bool(fixation_hits)
        resonance_hint = bool(resonance_hits)

        hit_manifest = False
        trigger_kind = "boss-cast" if near_initial_wave else "unknown"
        confidence = "low"
        if in_post_rescue_window and not near_initial_wave:
            hit_manifest = True
            trigger_kind = "manifest-collision"
            if resonance_hint:
                confidence = "high"
            elif fixation_hint:
                confidence = "medium"
            else:
                confidence = "medium"

        row["hitManifestation"] = hit_manifest
        row["triggerKind"] = trigger_kind
        row["collisionConfidence"] = confidence if hit_manifest else None
        row["fixationDebuffChanged"] = fixation_hint
        row["manifestCollisionDebuff"] = resonance_hint if use_malevolent_resonance else None
        if hit_manifest:
            if use_malevolent_resonance:
                hint = (
                    "同时段见恶毒共鸣/凝视变化。"
                    if (resonance_hint or fixation_hint)
                    else "可结合凝视(1285911)或恶毒共鸣变化进一步核对。"
                )
            else:
                hint = (
                    "同时段见凝视变化。"
                    if fixation_hint
                    else "可结合凝视(1285911)变化进一步核对；恶毒共鸣为史诗机制，英雄不做证据。"
                )
            row["evidenceNote"] = (
                "首次救人后、下一轮恐惧行军释放前再次获得 1297445，判定为撞到恐惧具象；" + hint
            )


def analyze_dreadmarch(fight, casts, debuffs, damage, friendly_damage, deaths, actor_map, players, markers):
    del damage, friendly_damage  # 救人只看 removedebuff，不再扫全场友伤
    cast_rows = sorted(
        [event for event in casts if int(ability_id(event) or 0) in DREADMARCH_CAST_IDS and is_cast_complete(event)],
        key=lambda row: int(row.get("timestamp") or 0),
    )
    cast_times = [int(event["timestamp"]) for event in cast_rows]
    fight_start = int(fight["startTime"])
    fight_end = int(fight["endTime"])
    # 恶毒共鸣仅史诗；英雄只靠救人后二次心控 + 凝视变化
    use_malevolent_resonance = int(fight.get("difficulty") or 0) == 5
    applications = []
    for event in sorted(debuffs, key=lambda row: int(row.get("timestamp") or 0)):
        if int(ability_id(event) or 0) not in DREADMARCH_DEBUFF_IDS or not is_apply(event):
            continue
        target_id = event.get("targetID")
        if target_id not in players:
            continue
        apply_ts = int(event["timestamp"])
        round_index = None
        round_cast_ts = None
        for index, cast_ts in enumerate(cast_times):
            next_cast = cast_times[index + 1] if index + 1 < len(cast_times) else fight_end
            if cast_ts - 1_500 <= apply_ts < next_cast:
                round_index = index + 1
                round_cast_ts = cast_ts
                break
        if round_index is None and cast_times:
            preceding = [cast_ts for cast_ts in cast_times if cast_ts <= apply_ts]
            if preceding and apply_ts - preceding[-1] <= 8_000:
                round_index = cast_times.index(preceding[-1]) + 1
                round_cast_ts = preceding[-1]
        remove_event = _find_dreadmarch_remove(debuffs, target_id, apply_ts, fight_end)
        remove_ts = int(remove_event["timestamp"]) if remove_event else None
        window_end = remove_ts or fight_end
        death_event = next(
            (
                row for row in deaths
                if row.get("targetID") == target_id and apply_ts <= int(row["timestamp"]) <= window_end + 2_000
            ),
            None,
        )
        death_ts = int(death_event["timestamp"]) if death_event else None
        died_before_remove = bool(death_ts and (remove_ts is None or death_ts < remove_ts))
        rescued = bool(remove_event) and not died_before_remove
        applications.append({
            **player_ref(players, actor_map, target_id),
            "roundIndex": round_index,
            "castTimeMs": (round_cast_ts - fight_start) if round_cast_ts else None,
            "castTime": fmt_ms(round_cast_ts - fight_start) if round_cast_ts else None,
            "phase": phase_at(apply_ts - fight_start, markers),
            "appliedTimeMs": apply_ts - fight_start,
            "appliedTime": fmt_ms(apply_ts - fight_start),
            "removedTimeMs": remove_ts - fight_start if remove_ts else None,
            "removedTime": fmt_ms(remove_ts - fight_start) if remove_ts else None,
            "rescued": rescued,
            "diedWhileControlled": died_before_remove,
            "failed": died_before_remove or not rescued,
            "hitManifestation": False,
            "triggerKind": "unknown",
            "evidenceNote": "救援成功以 1297445 removedebuff 为准，不再拉取对被控玩家的友伤命中。",
        })

    _annotate_dreadmarch_manifest_collisions(
        applications, cast_times, fight_start, fight_end, debuffs,
        use_malevolent_resonance=use_malevolent_resonance,
    )

    rounds = []
    grouped = defaultdict(list)
    for row in applications:
        key = row.get("roundIndex") or 0
        grouped[key].append(row)
    for index, cast in enumerate(cast_rows, start=1):
        targets = grouped.get(index, [])
        collisions = [row for row in targets if row.get("hitManifestation")]
        initial = [row for row in targets if not row.get("hitManifestation")]
        rounds.append({
            "index": index,
            "phase": phase_at(int(cast["timestamp"]) - fight_start, markers),
            "timeMs": int(cast["timestamp"]) - fight_start,
            "time": fmt_ms(int(cast["timestamp"]) - fight_start),
            "targetCount": len(initial),
            "rescuedCount": sum(1 for row in initial if row["rescued"]),
            "failedCount": sum(1 for row in initial if row["failed"]),
            "manifestCollisionCount": len(collisions),
            "targets": targets,
            "manifestCollisions": collisions,
        })
    unassigned = grouped.get(0, [])
    if unassigned:
        collisions = [row for row in unassigned if row.get("hitManifestation")]
        rounds.append({
            "index": len(rounds) + 1,
            "phase": unassigned[0].get("phase"),
            "timeMs": unassigned[0]["appliedTimeMs"],
            "time": unassigned[0]["appliedTime"],
            "targetCount": len(unassigned),
            "rescuedCount": sum(1 for row in unassigned if row["rescued"]),
            "failedCount": sum(1 for row in unassigned if row["failed"]),
            "manifestCollisionCount": len(collisions),
            "targets": unassigned,
            "manifestCollisions": collisions,
            "unassigned": True,
        })
    collision_rows = [row for row in applications if row.get("hitManifestation")]
    if use_malevolent_resonance:
        evidence_note = (
            "Boss 点名波次后第一次成功救人起、至下一轮恐惧行军释放前，"
            "新获得的 1297445 记为撞到恐惧具象；史诗可结合凝视(1285911)/恶毒共鸣核对。"
        )
    else:
        evidence_note = (
            "Boss 点名波次后第一次成功救人起、至下一轮恐惧行军释放前，"
            "新获得的 1297445 记为撞到恐惧具象；可结合凝视(1285911)变化核对。"
            "恶毒共鸣为史诗机制，英雄不做证据。"
        )
    return {
        "rounds": rounds,
        "applications": applications,
        "manifestCollisions": collision_rows,
        "manifestCollisionCount": len(collision_rows),
        "useMalevolentResonance": use_malevolent_resonance,
        "evidenceNote": evidence_note,
    }


def analyze_manifestations(
    fight,
    debuffs,
    npc_position_index,
    actor_map,
    players,
    actor_catalog,
    markers,
    enemy_deaths=None,
    position_index=None,
    player_deaths=None,
):
    fixations = []
    active = {}
    for event in sorted(debuffs, key=lambda row: int(row.get("timestamp") or 0)):
        if int(ability_id(event) or 0) != FIXATION:
            continue
        target_id = event.get("targetID")
        if target_id not in players:
            continue
        timestamp = int(event["timestamp"])
        source_id = event.get("sourceID")
        source_instance = event.get("sourceInstance") or event.get("sourceInstanceID")
        manifest = resolve_manifest_instance(source_id, source_instance, actor_catalog)
        if is_apply(event):
            if not manifest.get("isManifestNpc"):
                continue
            row = {
                **player_ref(players, actor_map, target_id),
                "phase": phase_at(timestamp - int(fight["startTime"]), markers),
                "applyTimeMs": timestamp - int(fight["startTime"]),
                "applyTime": fmt_ms(timestamp - int(fight["startTime"])),
                "removeTimeMs": None,
                "removeTime": None,
                "manifest": manifest,
                "manifestPosition": None,
                "playerPosition": None,
            }
            active[(target_id, source_id, source_instance)] = row
            fixations.append(row)
            continue
        if not is_remove(event):
            continue
        key = (target_id, source_id, source_instance)
        row = active.pop(key, None)
        if row:
            row["removeTimeMs"] = timestamp - int(fight["startTime"])
            row["removeTime"] = fmt_ms(timestamp - int(fight["startTime"]))
            row["removeTimestamp"] = timestamp

    fight_end = int(fight["endTime"])
    tuning = encounter_tuning(fight)
    retired, surviving_rows = {}, []
    for row in fixations:
        manifest = row.get("manifest") or {}
        source_id = manifest.get("sourceID")
        source_instance = manifest.get("sourceInstance")
        apply_abs = int(fight["startTime"]) + int(row["applyTimeMs"])
        key = (source_id, source_instance)
        if source_id is not None and key in retired and apply_abs >= retired[key]:
            continue
        remove_abs = fight["startTime"] + row["removeTimeMs"] if row.get("removeTimeMs") is not None else None
        death_ts = _npc_instance_death_ts(enemy_deaths, source_id, source_instance)
        target_death = min((int(e['timestamp']) for e in player_deaths or []
            if e.get('targetID') == row['playerID'] and apply_abs <= int(e['timestamp']) <= (remove_abs or fight_end)),
            default=None) if tuning['manifestDespawnOnTargetDeath'] else None
        despawn_ts = min(ts for ts in (remove_abs, death_ts, target_death, fight_end) if ts is not None)
        if target_death is not None and target_death == despawn_ts:
            retired[key] = target_death
            row.update(removeTimeMs=target_death-int(fight['startTime']),
                       removeTime=fmt_ms(target_death-int(fight['startTime'])),
                       despawnReason='fixated-target-death')
        # 具象坐标：消失前最后一次 NPC 自身采样（不是被点名玩家）
        position = _position_last_at_or_before(npc_position_index, source_id, source_instance, despawn_ts)
        if not position:
            position = _position_sample_npc(npc_position_index, source_id, source_instance, apply_abs)
        row["manifestPosition"] = position
        row["despawnTimeMs"] = int(despawn_ts) - int(fight["startTime"])
        row["despawnTime"] = fmt_ms(row["despawnTimeMs"])
        if position_index is not None and row.get("playerID") is not None:
            player_state = position_at(
                position_index, row["playerID"], apply_abs, max_offset_ms=POSITION_RELIABLE_MS,
            )
            if player_state:
                row["playerPosition"] = point_dict(
                    (player_state["x"], player_state["y"]),
                    timestamp=apply_abs,
                    reliable=player_state.get("reliable"),
                    offset_ms=player_state.get("sampleOffsetMs"),
                )

        surviving_rows.append(row)
    fixations = surviving_rows
    manifestation_points = []
    for row in fixations:
        manifestation_points.append({
            "kind": "manifestation",
            "manifest": row["manifest"],
            "playerID": row.get("playerID"),
            "player": row["player"],
            "classColor": row.get("classColor"),
            "icon": row.get("icon"),
            "role": row.get("role"),
            "specID": row.get("specID"),
            "specName": row.get("specName"),
            "className": row.get("className"),
            "position": row.get("manifestPosition"),
            "manifestPosition": row.get("manifestPosition"),
            "playerPosition": row.get("playerPosition"),
            "lastSeenMs": int(fight["startTime"]) + int(row.get("despawnTimeMs") or row["applyTimeMs"]),
            "applyTimeMs": row["applyTimeMs"],
            "removeTimeMs": row.get("removeTimeMs"),
            "despawnTimeMs": row.get("despawnTimeMs"),
        })
    return {"fixations": fixations, "activePoints": manifestation_points}


def enrich_manifest_point_at(point, npc_position_index, position_index, timestamp):
    """在灵魂撕裂释放前一刻刷新具象 NPC 坐标与被点名玩家坐标。"""
    if not point:
        return point
    row = dict(point)
    # 释放前：取该时刻（含）之前最后一次 NPC 自身采样
    sample_ts = int(timestamp) - 1 if timestamp else timestamp
    manifest = row.get("manifest") or {}
    source_id = manifest.get("sourceID")
    source_instance = manifest.get("sourceInstance")
    npc_pos = _position_last_at_or_before(npc_position_index, source_id, source_instance, sample_ts)
    if not npc_pos:
        npc_pos = _position_sample_npc(npc_position_index, source_id, source_instance, sample_ts)
    if npc_pos:
        row["position"] = npc_pos
        row["manifestPosition"] = npc_pos
    player_id = row.get("playerID")
    if position_index is not None and player_id is not None:
        player_state = position_at(position_index, player_id, sample_ts, max_offset_ms=POSITION_RELIABLE_MS)
        if player_state:
            row["playerPosition"] = point_dict(
                (player_state["x"], player_state["y"]),
                timestamp=sample_ts,
                reliable=player_state.get("reliable"),
                offset_ms=player_state.get("sampleOffsetMs"),
            )
    return row


def analyze_soul_sever(
    fight,
    casts,
    deaths,
    position_index,
    actor_map,
    markers,
    manifestation_points,
    boss_actor_id=None,
    origin_index=None,
    debuffs=None,
    npc_position_index=None,
):
    completed = [event for event in casts if int(ability_id(event) or 0) in SOUL_SEVER_IDS and is_cast_complete(event)]
    rounds = []
    for index, cast in enumerate(completed, start=1):
        timestamp = int(cast["timestamp"])
        source_id = cast.get("sourceID")
        fight_start = int(fight["startTime"])
        active_before = active_fixations_before_cast(manifestation_points, timestamp, fight_start)
        nearby_points = [
            enrich_manifest_point_at(point, npc_position_index or {}, position_index, timestamp)
            for point in active_before
        ]
        lock_ms, tank_id, facing_rule, _debuff = resolve_sever_facing_lock(
            casts, cast, debuffs=debuffs, debuff_ids=SOUL_SEVER_TANK_DEBUFF_IDS,
        )
        if tank_id is None:
            tank_id = cast.get("targetID")
        origin, facing_radians, facing_state, facing_inferred, tank_state = resolve_caster_origin_facing(
            position_index,
            source_id,
            boss_actor_id,
            timestamp,
            hint_points=nearby_points,
            target_id=tank_id,
            origin_actor_id=source_id or boss_actor_id,
            origin_index=origin_index,
            cast_event=cast,
            facing_timestamp=lock_ms,
            allow_hint_override=facing_rule not in {"tank-debuff", "cast-last-second"},
        )
        in_cone = []
        uncleared = []
        cleared = []
        annotated = []
        for point in nearby_points:
            position = point.get("position") or point.get("manifestPosition")
            inside = False
            if position and origin is not None and facing_radians is not None:
                inside = in_frontal_cone(origin, facing_radians, (position["x"], position["y"]))
            verdict = classify_fixation_after_sever(point, timestamp, fight_start, inside)
            row = {**point, **verdict}
            annotated.append(row)
            if inside:
                in_cone.append(row)
            if verdict["uncleared"]:
                uncleared.append(row)
            else:
                cleared.append(row)
        cleared_deaths = [
            event for event in deaths
            if timestamp - 500 <= int(event.get("timestamp") or 0) <= timestamp + 2_000
            and event.get("targetID") not in (None,)
        ]
        tank_position = None
        if tank_state:
            tank_position = point_dict(
                (tank_state["x"], tank_state["y"]),
                timestamp=lock_ms,
                reliable=tank_state.get("reliable"),
                offset_ms=tank_state.get("sampleOffsetMs"),
            )
        elif tank_id is not None:
            fallback = position_at(position_index, tank_id, lock_ms, max_offset_ms=POSITION_RELIABLE_MS)
            if fallback:
                tank_position = point_dict(
                    (fallback["x"], fallback["y"]),
                    timestamp=lock_ms,
                    reliable=fallback.get("reliable"),
                    offset_ms=fallback.get("sampleOffsetMs"),
                )
        rounds.append({
            "index": index,
            "phase": phase_at(timestamp - int(fight["startTime"]), markers),
            "spellID": int(ability_id(cast) or 0),
            "timeMs": timestamp - int(fight["startTime"]),
            "time": fmt_ms(timestamp - int(fight["startTime"])),
            "origin": point_dict(origin, timestamp=timestamp),
            "facingRadians": facing_radians,
            "facingInferred": facing_inferred,
            "facingLockMs": lock_ms - fight_start,
            "facingRule": facing_rule,
            "tankID": tank_id,
            "tankPosition": tank_position,
            "coneRadiusYards": CONE_RADIUS_YARDS,
            "conePolygon": cone_polygon(origin, facing_radians),
            "manifestationsInCone": in_cone,
            "nearbyPoints": annotated,
            "unclearedManifestations": uncleared,
            "clearedManifestations": cleared,
            "clearedByGeometry": len(in_cone),
            "clearedByDebuff": len(cleared),
            "unclearedCount": len(uncleared),
            "addDeathSignals": len(cleared_deaths),
            "evidenceNote": (
                f"具象坐标取灵魂撕裂释放前；"
                f"锥内 {len(in_cone)}，debuff 清掉 {len(cleared)}，未消掉 {len(uncleared)}；"
                f"红线仅连未消掉凝视的玩家。"
            ),
        })
    return {"rounds": rounds}


def _soulcoiler_event_key(event, coiler_ids):
    target_id = event.get("targetID")
    source_id = event.get("sourceID")
    actor_id = target_id if target_id in coiler_ids else source_id if source_id in coiler_ids else None
    if actor_id is None:
        return None
    instance = (
        event.get("targetInstance") or event.get("targetInstanceID")
        or event.get("sourceInstance") or event.get("sourceInstanceID")
        or 0
    )
    return (int(actor_id), int(instance or 0))


def _spirit_shield_crack_event(buffs, coiler_ids, key, start_ts, end_ts):
    """返回该 instance 在本轮掉盾的原始事件；事件本身可能携带目标坐标。"""
    start = int(start_ts)
    end = int(end_ts)
    matches = []
    for event in buffs or []:
        if int(ability_id(event) or 0) != SPIRIT_SHIELD:
            continue
        if _soulcoiler_event_key(event, coiler_ids) != key:
            continue
        kind = event_type(event)
        if kind not in {"removebuffstack", "removebuff"}:
            continue
        ts = int(event.get("timestamp") or 0)
        if start <= ts <= end:
            matches.append(event)
    return min(matches, key=lambda event: int(event.get("timestamp") or 0), default=None)


def _round_soulcoiler_cracks(buffs, coiler_ids, start_ts, end_ts):
    """本轮炸弹实际打掉的盾事件；用它限定活跃盘魂者，不能从整场 instance 中猜。"""
    start = int(start_ts)
    end = int(end_ts)
    rows = []
    for event in buffs or []:
        if int(ability_id(event) or 0) != SPIRIT_SHIELD:
            continue
        if event_type(event) not in {"removebuffstack", "removebuff"}:
            continue
        ts = int(event.get("timestamp") or 0)
        key = _soulcoiler_event_key(event, coiler_ids)
        if key and start <= ts <= end:
            rows.append((key, event))
    return rows


def _round_soulcoiler_specs(round_cracks, fallback_keys):
    """保留有 instance 的每只怪；instance 缺失时按掉盾坐标聚成最多两只怪。"""
    if not round_cracks:
        return [(actor_id, instance, None) for actor_id, instance in fallback_keys]
    specs = []
    seen_keys = set()
    uninstanced = []
    for key, event in round_cracks:
        actor_id, instance = key
        if instance:
            if key not in seen_keys:
                specs.append((actor_id, instance, event))
                seen_keys.add(key)
            continue
        point = _target_self_point(event)
        if not point:
            if key not in seen_keys:
                specs.append((actor_id, 0, event))
                seen_keys.add(key)
            continue
        matched = False
        for cluster in uninstanced:
            if distance_yards(point, cluster["point"]) <= SOULCOILER_DEDUP_YARDS:
                matched = True
                break
        if not matched:
            uninstanced.append({"actorID": actor_id, "event": event, "point": point})
    specs.extend((row["actorID"], 0, row["event"]) for row in uninstanced)
    return specs


def _spirit_shield_stacks_at(buffs, coiler_ids, key, timestamp):
    stacks = 0
    for event in buffs or []:
        if int(ability_id(event) or 0) != SPIRIT_SHIELD:
            continue
        event_key = _soulcoiler_event_key(event, coiler_ids)
        if event_key != key:
            continue
        ts = int(event.get("timestamp") or 0)
        if ts > timestamp:
            break
        kind = event_type(event)
        if kind in {"applybuff", "applybuffstack", "refreshbuff"}:
            stacks = int(event.get("stack") or stacks or SOULCOILER_BOMBS_REQUIRED)
        elif kind == "removebuffstack":
            stacks = int(event.get("stack") or max(0, stacks - 1))
        elif kind == "removebuff":
            stacks = 0
    return stacks


def _soulcoiler_keys(coiler_ids, casts, buffs, npc_position_index=None):
    keys = set()
    for event in list(casts or []) + list(buffs or []):
        if int(ability_id(event) or 0) not in WAIL_OF_TERROR_IDS | {SPIRIT_SHIELD}:
            continue
        key = _soulcoiler_event_key(event, coiler_ids)
        if key:
            keys.add(key)
    for (actor_id, instance) in (npc_position_index or {}):
        if actor_id in coiler_ids:
            keys.add((int(actor_id), int(instance or 0)))
    for actor_id in coiler_ids:
        insts = [inst for aid, inst in keys if aid == actor_id]
        real = [inst for inst in insts if inst != 0]
        if real and 0 in insts:
            keys.discard((int(actor_id), 0))
        elif not insts:
            keys.add((int(actor_id), 0))
    return sorted(keys)


def _pick_round_soulcoilers(candidates, bomb_positions):
    """每轮只保留当场两只怨毒盘魂者；同点重复 instance / 已死 / 无坐标的丢掉。"""
    ranked = []
    for row in candidates:
        pos = row.get("position")
        if not pos:
            continue
        nearest_bomb = None
        for bomb in bomb_positions or []:
            dist = _xy_distance_yards(pos, bomb)
            if dist is None:
                continue
            if nearest_bomb is None or dist < nearest_bomb:
                nearest_bomb = dist
        ranked.append({
            **row,
            "nearestBombYards": nearest_bomb,
        })
    ranked.sort(
        key=lambda row: (
            0 if int(row.get("shieldStacks") or 0) > 0 else 1,
            row["nearestBombYards"] if row["nearestBombYards"] is not None else 10**9,
            -int(row.get("sourceInstance") or 0),
        )
    )
    picked = []
    for row in ranked:
        xy = _position_xy(row.get("position"))
        if not xy:
            continue
        duplicate = False
        for kept in picked:
            kept_xy = _position_xy(kept.get("position"))
            if kept_xy and distance_yards(xy, kept_xy) <= SOULCOILER_DEDUP_YARDS:
                duplicate = True
                break
        if duplicate:
            continue
        picked.append(row)
        if len(picked) >= SOULCOILER_EXPECTED_COUNT:
            break
    return picked


def _is_wail_interrupt(event, coiler_ids):
    extra = int(event.get("extraAbilityGameID") or 0)
    if extra not in WAIL_OF_TERROR_IDS:
        return False
    kind = event_type(event)
    if kind and kind not in {"interrupt"}:
        return False
    return event.get("targetID") in coiler_ids or event.get("sourceID") in coiler_ids


def _xy_distance_yards(left, right):
    left_xy = _position_xy(left)
    right_xy = _position_xy(right)
    if not left_xy or not right_xy:
        return None
    return round(distance_yards(left_xy, right_xy), 1)


def annotate_gloombomb_soulcoilers(
    fight, rounds, casts, enemy_buffs, interrupts, npc_position_index, actor_map, players,
    actor_rows, markers, enemy_deaths=None, damage_events=None,
):
    """史诗：把每轮幽暗炸弹对齐到怨毒盘魂者灵魂之盾，并检查打断换位导致炸空。"""
    coiler_ids = soulcoiler_actor_ids(actor_rows)
    has_shield = any(int(ability_id(event) or 0) == SPIRIT_SHIELD for event in (enemy_buffs or []))
    if not coiler_ids or not has_shield:
        return False
    fight_start = int(fight["startTime"])
    buffs = sorted(enemy_buffs or [], key=lambda row: int(row.get("timestamp") or 0))
    interrupt_rows = [
        event for event in interrupts or []
        if _is_wail_interrupt(event, coiler_ids)
    ]
    keys = _soulcoiler_keys(coiler_ids, casts, buffs, npc_position_index)
    pet_owners = _pet_owner_map(actor_rows)
    for round_row in rounds:
        explode_times = [
            fight_start + int(target["explodeTimeMs"])
            for target in round_row.get("targets") or []
            if target.get("explodeTimeMs") is not None
        ]
        round_abs = fight_start + int(round_row.get("timeMs") or 0)
        apply_times = [
            fight_start + int(target["applyTimeMs"])
            for target in round_row.get("targets") or []
            if target.get("applyTimeMs") is not None
        ]
        if explode_times:
            snapshot_ts = min(explode_times)
            bomb_pos_end = max(explode_times) + SOULCOILER_BOMB_POS_PAD_MS
            bomb_pos_start = (min(apply_times) if apply_times else min(explode_times) - 5_500)
        else:
            snapshot_ts = round_abs
            bomb_pos_start = snapshot_ts - 5_500
            bomb_pos_end = snapshot_ts + SOULCOILER_BOMB_POS_PAD_MS
        bomb_positions = [
            target.get("position")
            for target in round_row.get("targets") or []
            if target.get("position")
        ]
        round_cracks = _round_soulcoiler_cracks(
            buffs, coiler_ids, bomb_pos_start, bomb_pos_end,
        )
        round_specs = _round_soulcoiler_specs(round_cracks, keys)
        candidates = []
        for actor_id, instance, round_crack_event in round_specs:
            death_ts = _npc_instance_death_ts(enemy_deaths, actor_id, instance)
            if death_ts is not None and death_ts < snapshot_ts:
                continue
            crack_event = round_crack_event
            if crack_event is None:
                crack_event = _spirit_shield_crack_event(
                    buffs, coiler_ids, (actor_id, instance),
                    bomb_pos_start, bomb_pos_end,
                )
            crack_ts = int(crack_event["timestamp"]) if crack_event else None
            coiler_ts = crack_ts or snapshot_ts
            stacks = _spirit_shield_stacks_at(buffs, coiler_ids, (actor_id, instance), coiler_ts)
            extra_rows = (
                _soulcoiler_event_coord_rows(damage_events, actor_id, bomb_pos_start, bomb_pos_end)
                + _soulcoiler_event_coord_rows(buffs, actor_id, bomb_pos_start, bomb_pos_end)
                + _soulcoiler_event_coord_rows(casts, actor_id, bomb_pos_start, bomb_pos_end)
            )
            # 盾事件只使用明确属于 Target 的坐标；不能把顶层来源坐标误画成盘魂者。
            crack_point = _target_self_point(crack_event) if crack_event else None
            sample_start = coiler_ts - SOULCOILER_BOMB_POS_PAD_MS
            sample_end = coiler_ts + SOULCOILER_BOMB_POS_PAD_MS
            position = (
                point_dict(crack_point, timestamp=coiler_ts, reliable=True, offset_ms=0)
                if crack_point else
                _soulcoiler_position_in_window(
                    npc_position_index, actor_id, instance,
                    sample_start, sample_end, coiler_ts,
                    extra_rows=extra_rows,
                )
            )
            if not position:
                continue
            position_source = "shield-crack-event" if crack_point else "bomb-window-sample"
            window_start = snapshot_ts - SOULCOILER_INTERRUPT_LOOKBACK_MS
            window_end = max(explode_times) if explode_times else snapshot_ts
            interrupts_here = [
                event for event in interrupt_rows
                if _soulcoiler_event_key(event, coiler_ids) == (actor_id, instance)
                and window_start <= int(event.get("timestamp") or 0) <= window_end
            ]
            last_interrupt = interrupts_here[-1] if interrupts_here else None
            prev_position = None
            relocate_yards = None
            if last_interrupt:
                interrupt_ts = int(last_interrupt["timestamp"])
                prev_position = _soulcoiler_position_at(
                    npc_position_index, actor_id, instance, interrupt_ts - 50,
                )
                relocate_yards = _xy_distance_yards(prev_position, position)
            interrupt_player = None
            if last_interrupt:
                interrupt_id = _resolve_player_source(last_interrupt, players, pet_owners) or last_interrupt.get("sourceID")
                interrupt_player = player_ref(players, actor_map, interrupt_id)
            hits = []
            displaced_here = []
            for target in round_row.get("targets") or []:
                explode_rel = target.get("explodeTimeMs")
                bomb_pos = target.get("position")
                if explode_rel is None or not bomb_pos:
                    continue
                explode_ts = fight_start + int(explode_rel)
                coiler_at_explode = position
                if instance:
                    coiler_at_explode = _soulcoiler_position_near(
                        npc_position_index, actor_id, instance, explode_ts,
                        extra_rows=extra_rows,
                    ) or position
                distance = _xy_distance_yards(bomb_pos, coiler_at_explode)
                hit = distance is not None and distance < GLOOMBOMB_RADIUS_YARDS
                would_hit_prev = False
                if prev_position:
                    prev_dist = _xy_distance_yards(bomb_pos, prev_position)
                    would_hit_prev = prev_dist is not None and prev_dist < GLOOMBOMB_RADIUS_YARDS
                relocated = relocate_yards is not None and relocate_yards >= SOULCOILER_RELOCATE_YARDS
                displaced_miss = bool(last_interrupt and relocated and would_hit_prev and not hit)
                hit_row = {
                    "player": target.get("player"),
                    "playerID": target.get("playerID"),
                    "classColor": target.get("classColor"),
                    "distanceYards": distance,
                    "hit": hit,
                    "wouldHitBeforeInterrupt": would_hit_prev,
                    "displacedMiss": displaced_miss,
                }
                hits.append(hit_row)
                if displaced_miss:
                    displaced_here.append({
                        **hit_row,
                        "soulcoilerInstance": instance,
                        "interruptTime": fmt_ms(int(last_interrupt["timestamp"]) - fight_start),
                        "interruptPlayer": interrupt_player,
                        "relocateYards": relocate_yards,
                    })
            candidates.append({
                "kind": "soulcoiler",
                "sourceID": actor_id,
                "sourceInstance": instance,
                "name": actor_name(actor_map, actor_id) or "怨毒盘魂者",
                "position": position,
                "positionSource": position_source,
                "previousPosition": prev_position if relocate_yards and relocate_yards >= SOULCOILER_RELOCATE_YARDS else None,
                "shieldStacks": stacks,
                "bombsRequired": SOULCOILER_BOMBS_REQUIRED,
                "bombHits": sum(1 for row in hits if row["hit"]),
                "hits": hits,
                "interrupted": bool(last_interrupt),
                "interruptTime": fmt_ms(int(last_interrupt["timestamp"]) - fight_start) if last_interrupt else None,
                "interruptPlayer": interrupt_player,
                "relocateYards": relocate_yards,
                "displacedMiss": any(row["displacedMiss"] for row in hits),
                "_displacedRows": displaced_here,
            })
        coilers = _pick_round_soulcoilers(candidates, bomb_positions)
        displaced_misses = []
        for coiler in coilers:
            displaced_misses.extend(coiler.pop("_displacedRows", []))
        round_row["soulcoilers"] = coilers
        round_row["soulcoilerCount"] = len(coilers)
        round_row["shieldHits"] = sum(row.get("bombHits") or 0 for row in coilers)
        round_row["displacedMisses"] = displaced_misses
        round_row["displacedMissCount"] = len(displaced_misses)
    return True


def _cluster_timestamped_events(events, gap_ms, span_ms):
    waves = []
    current = []
    for event in events:
        ts = int(event["timestamp"])
        if not current:
            current = [event]
            continue
        first = int(current[0]["timestamp"])
        last = int(current[-1]["timestamp"])
        if ts - last <= gap_ms and ts - first <= span_ms:
            current.append(event)
        else:
            waves.append(current)
            current = [event]
    if current:
        waves.append(current)
    return waves


def _merge_small_waves(waves, gap_ms, max_size):
    merged = []
    for wave in waves:
        if merged:
            prev = merged[-1]
            gap = int(wave[0]["timestamp"]) - int(prev[-1]["timestamp"])
            if gap <= gap_ms and len(prev) + len(wave) <= max_size:
                prev.extend(wave)
                continue
        merged.append(list(wave))
    return merged


def _cluster_gloombomb_apply_waves(debuff_rows, players):
    applies = [
        event for event in (debuff_rows or [])
        if int(ability_id(event) or 0) in GLOOMBOMB_DEBUFF_IDS
        and event_type(event) in GLOOMBOMB_APPLY_TYPES
        and event.get("targetID") in players
    ]
    clustered = _cluster_timestamped_events(applies, GLOOMBOMB_CAST_GAP_MS, GLOOMBOMB_WAVE_SPAN_MS)
    return _merge_small_waves(clustered, GLOOMBOMB_CAST_MERGE_MS, GLOOMBOMB_MARKS_PER_WAVE)


def _unique_wave_applies(wave):
    seen = set()
    unique = []
    for event in wave:
        target_id = event.get("targetID")
        if target_id in seen:
            continue
        seen.add(target_id)
        unique.append(event)
    return unique


def _is_roster_player(target_id, players):
    if target_id in (players or {}):
        return True
    try:
        return int(target_id) in players
    except (TypeError, ValueError):
        return False


def _gloombomb_apply_events(debuff_rows, players):
    return [
        event for event in (debuff_rows or [])
        if int(ability_id(event) or 0) in GLOOMBOMB_DEBUFF_IDS
        and event_type(event) in GLOOMBOMB_APPLY_TYPES
        and _is_roster_player(event.get("targetID"), players)
    ]


def _gloombomb_wave_specs(completed, debuff_rows, players):
    """每轮以施法波次为准，把窗口内点名收进同一张图；没有施法时才退回施加聚类。"""
    applies = _gloombomb_apply_events(debuff_rows, players)
    if completed:
        cast_waves = _merge_small_waves(
            _cluster_timestamped_events(completed, GLOOMBOMB_CAST_GAP_MS, GLOOMBOMB_WAVE_SPAN_MS),
            GLOOMBOMB_CAST_MERGE_MS,
            GLOOMBOMB_MARKS_PER_WAVE,
        )
        specs = []
        claimed = set()
        for index, wave in enumerate(cast_waves):
            first_cast = int(wave[0]["timestamp"])
            last_cast = int(wave[-1]["timestamp"])
            next_start = (
                int(cast_waves[index + 1][0]["timestamp"])
                if index + 1 < len(cast_waves)
                else last_cast + 30_000
            )
            window_start = first_cast - GLOOMBOMB_APPLY_LOOKBACK_MS
            window_end = min(next_start, last_cast + GLOOMBOMB_APPLY_WINDOW_MS)
            window_applies = [
                event for event in applies
                if window_start <= int(event["timestamp"]) < window_end
            ]
            unique = _unique_wave_applies(window_applies)
            for event in unique:
                claimed.add(id(event))
            specs.append((wave[0], unique, first_cast))
        leftovers = [event for event in applies if id(event) not in claimed]
        for event in leftovers:
            ts = int(event["timestamp"])
            best_index = None
            best_dist = None
            for index, (_cast, _unique, first_cast) in enumerate(specs):
                dist = abs(ts - first_cast)
                if best_index is None or dist < best_dist:
                    best_index, best_dist = index, dist
            if best_index is None or best_dist > GLOOMBOMB_LEFTOVER_ATTACH_MS:
                continue
            target_id = event.get("targetID")
            unique = specs[best_index][1]
            if any(row.get("targetID") == target_id for row in unique):
                continue
            unique.append(event)
        return [(cast, _unique_wave_applies(unique), first_cast) for cast, unique, first_cast in specs if unique]

    waves = _cluster_gloombomb_apply_waves(debuff_rows, players)
    specs = []
    for wave in waves:
        unique = _unique_wave_applies(wave)
        if not unique:
            continue
        specs.append((None, unique, int(unique[0]["timestamp"])))
    return specs


def _gloombomb_cast_for_wave(completed, first_ts, last_ts):
    if not completed:
        return None
    window_start = first_ts - 3_000
    window_end = last_ts + 2_000
    in_window = [
        event for event in completed
        if window_start <= int(event["timestamp"]) <= window_end
    ]
    if in_window:
        return in_window[0]
    mid = (first_ts + last_ts) // 2
    return min(completed, key=lambda event: abs(int(event["timestamp"]) - mid))


def _index_rows_for_actor(index, actor_id):
    if actor_id is None or not index:
        return []
    keys = {actor_id}
    try:
        keys.add(int(actor_id))
    except (TypeError, ValueError):
        pass
    rows = []
    seen = set()
    for key in keys:
        for row in index.get(key) or []:
            ident = (row.get("timestamp"), row.get("x"), row.get("y"))
            if ident in seen:
                continue
            seen.add(ident)
            rows.append(row)
    return rows


def _event_coord_row(event):
    if not event:
        return None
    point = _target_self_point(event) or _aura_target_point(event) or event_point(event)
    if not point:
        return None
    return {"timestamp": int(event["timestamp"]), "x": point[0], "y": point[1]}


def _timeline_point_near(rows, timestamp, window_ms=GLOOMBOMB_HIT_POS_WINDOW_MS):
    """按 timestamp 在轨迹上取值：两侧样本间隔不超过 2s 则插值（与回放同一时刻），否则取 2s 内最近点。"""
    if not rows or timestamp is None:
        return None
    ts = int(timestamp)
    window = int(window_ms)
    max_gap = int(GLOOMBOMB_INTERP_GAP_MS)
    before = [row for row in rows if int(row["timestamp"]) <= ts]
    after = [row for row in rows if int(row["timestamp"]) >= ts]
    left = max(before, key=lambda row: int(row["timestamp"])) if before else None
    right = min(after, key=lambda row: int(row["timestamp"])) if after else None
    if left and right:
        left_ts = int(left["timestamp"])
        right_ts = int(right["timestamp"])
        gap = right_ts - left_ts
        if gap == 0:
            return point_dict((left["x"], left["y"]), timestamp=ts, reliable=True, offset_ms=left_ts - ts)
        if gap <= max_gap:
            t = (ts - left_ts) / gap
            x = float(left["x"]) + (float(right["x"]) - float(left["x"])) * t
            y = float(left["y"]) + (float(right["y"]) - float(left["y"])) * t
            reliable = min(ts - left_ts, right_ts - ts) <= window
            return point_dict((x, y), timestamp=ts, reliable=reliable, offset_ms=0)
    nearby = [row for row in rows if abs(int(row["timestamp"]) - ts) <= max_gap]
    if not nearby:
        return None
    nearest = min(nearby, key=lambda row: abs(int(row["timestamp"]) - ts))
    offset = int(nearest["timestamp"] - ts)
    return point_dict(
        (nearest["x"], nearest["y"]),
        timestamp=ts,
        reliable=abs(offset) <= window,
        offset_ms=offset,
    )


def _timeline_point_at(rows, timestamp, max_age_ms=GLOOMBOMB_POSITION_MAX_OFFSET_MS):
    """取 timestamp 当时（含）的坐标；晚于该时刻的样本不用，过早的上点名坐标也不用。"""
    if not rows or timestamp is None:
        return None
    ts = int(timestamp)
    at_or_before = [row for row in rows if int(row["timestamp"]) <= ts]
    if not at_or_before:
        return None
    last = max(at_or_before, key=lambda row: int(row["timestamp"]))
    offset = int(last["timestamp"] - ts)
    if max_age_ms is not None and abs(offset) > max_age_ms:
        return None
    return point_dict(
        (last["x"], last["y"]),
        timestamp=ts,
        reliable=abs(offset) <= POSITION_RELIABLE_MS,
        offset_ms=offset,
    )


def _index_point_at(index, actor_id, timestamp, max_age_ms=GLOOMBOMB_POSITION_MAX_OFFSET_MS):
    if actor_id is None:
        return None
    return _timeline_point_at(_index_rows_for_actor(index, actor_id), timestamp, max_age_ms=max_age_ms)


def _index_point_near(index, actor_id, timestamp, window_ms=GLOOMBOMB_HIT_POS_WINDOW_MS):
    if actor_id is None:
        return None
    return _timeline_point_near(_index_rows_for_actor(index, actor_id), timestamp, window_ms=window_ms)


def _npc_point_at(npc_index, actor_id, timestamp, max_age_ms=GLOOMBOMB_POSITION_MAX_OFFSET_MS):
    if not npc_index or actor_id is None:
        return None
    rows = []
    for (aid, _inst), inst_rows in npc_index.items():
        if int(aid) != int(actor_id):
            continue
        rows.extend(inst_rows or [])
    return _timeline_point_at(rows, timestamp, max_age_ms=max_age_ms)


def _aura_row(event):
    if not event:
        return None
    point = _aura_target_point(event)
    if not point:
        return None
    return {"timestamp": int(event["timestamp"]), "x": point[0], "y": point[1]}


def _index_point_last_before(index, actor_id, timestamp, max_age_ms=GLOOMBOMB_BEFORE_REMOVE_MAX_AGE_MS):
    """取 timestamp 之前（不含）的最后坐标，避免用上爆炸/位移后的样本。"""
    if not index or actor_id is None or timestamp is None:
        return None
    rows = index.get(actor_id) or []
    prior = [row for row in rows if int(row["timestamp"]) < int(timestamp)]
    if not prior:
        return None
    last = prior[-1]
    offset = int(last["timestamp"] - timestamp)
    if max_age_ms is not None and abs(offset) > max_age_ms:
        return None
    return point_dict(
        (last["x"], last["y"]),
        timestamp=int(timestamp),
        reliable=abs(offset) <= POSITION_RELIABLE_MS,
        offset_ms=offset,
    )


def _npc_point_last_before(npc_index, actor_id, timestamp, max_age_ms=GLOOMBOMB_BEFORE_REMOVE_MAX_AGE_MS):
    if not npc_index or actor_id is None or timestamp is None:
        return None
    rows = []
    for (aid, _inst), inst_rows in npc_index.items():
        if int(aid) != int(actor_id):
            continue
        rows.extend(inst_rows or [])
    if not rows:
        return None
    rows.sort(key=lambda row: int(row["timestamp"]))
    prior = [row for row in rows if int(row["timestamp"]) < int(timestamp)]
    if not prior:
        return None
    last = prior[-1]
    offset = int(last["timestamp"] - timestamp)
    if max_age_ms is not None and abs(offset) > max_age_ms:
        return None
    return point_dict(
        (last["x"], last["y"]),
        timestamp=int(timestamp),
        reliable=abs(offset) <= POSITION_RELIABLE_MS,
        offset_ms=offset,
    )


def _player_event_point(event):
    """DamageTaken 顶层 x/y 属于受击玩家。"""
    if not event:
        return None
    point = _target_self_point(event)
    if point:
        return point
    if event_type(event) == "damage":
        return (
            _xy_from_node(event.get("targetResources"))
            or _xy_from_node(event)
            or _xy_from_node(event.get("resources"))
        )
    return None


def _gloombomb_damage_hit(damage_events, target_id, apply_ts, remove_ts=None):
    if target_id is None:
        return None
    wanted = int(target_id)
    start = int(apply_ts)
    end = int(remove_ts) + 1_000 if remove_ts is not None else start + 20_000
    hits = []
    for event in damage_events or []:
        if event_type(event) != "damage":
            continue
        if int(ability_id(event) or 0) not in GLOOMBOMB_DAMAGE_IDS:
            continue
        if int(event.get("targetID") or -1) != wanted:
            continue
        ts = int(event.get("timestamp") or 0)
        if ts < start or ts > end:
            continue
        hits.append(event)
    if not hits:
        return None
    explode_hits = [
        event for event in hits
        if int(ability_id(event) or 0) in GLOOMBOMB_EXPLODE_DAMAGE_IDS
    ]
    pool = explode_hits or hits
    if remove_ts is not None:
        return min(pool, key=lambda event: abs(int(event["timestamp"]) - int(remove_ts)))
    return max(pool, key=lambda event: int(event["timestamp"]))


def _gloombomb_target_position(hit_event, position_index, target_id):
    """只使用吃到幽暗炸弹伤害时刻 ±100ms 的受击者坐标。"""
    if not hit_event:
        return None, None
    snapshot_ts = int(hit_event["timestamp"])
    rows = _index_rows_for_actor(position_index, target_id)
    point = _player_event_point(hit_event)
    if point:
        rows.append({"timestamp": snapshot_ts, "x": point[0], "y": point[1]})
    position = _timeline_point_near(rows, snapshot_ts, GLOOMBOMB_HIT_POS_WINDOW_MS)
    if position:
        return position, "damage-hit"
    return None, None


def analyze_gloombomb(
    fight, casts, debuffs, position_index, actor_map, players, markers,
    origin_index=None, boss_actor_id=None, npc_position_index=None, actor_rows=None,
    enemy_buffs=None, interrupts=None, enemy_deaths=None, damage_events=None,
):
    completed = [event for event in casts if int(ability_id(event) or 0) in GLOOMBOMB_CAST_IDS and is_cast_complete(event)]
    completed.sort(key=lambda row: int(row.get("timestamp") or 0))
    debuff_rows = sorted(debuffs, key=lambda row: int(row.get("timestamp") or 0))
    fight_start = int(fight["startTime"])
    rounds = []
    for index, (cast, apply_events, round_ts) in enumerate(_gloombomb_wave_specs(completed, debuff_rows, players), start=1):
        if not apply_events:
            continue
        first_ts = int(apply_events[0]["timestamp"])
        last_ts = int(apply_events[-1]["timestamp"])
        if cast is None:
            cast = _gloombomb_cast_for_wave(completed, first_ts, last_ts)
        timestamp = int(cast["timestamp"]) if cast else round_ts
        targets = []
        for event in apply_events:
            target_id = event.get("targetID")
            apply_ts = int(event["timestamp"])
            remove_event = _first_full_aura_remove_after(debuff_rows, target_id, apply_ts, GLOOMBOMB_DEBUFF_IDS)
            hit_event = _gloombomb_damage_hit(
                damage_events, target_id, apply_ts,
                remove_ts=int(remove_event["timestamp"]) if remove_event else None,
            )
            explode_ts = int(hit_event["timestamp"]) if hit_event else None
            position, position_rule = _gloombomb_target_position(hit_event, position_index, target_id)
            # Older callers omitted the damage stream. Keep their aura-removal
            # snapshot available, explicitly labelled as a proxy. Live analysis
            # passes a damage list and requires an observed explosion instead.
            if damage_events is None and remove_event is not None:
                explode_ts = int(remove_event["timestamp"])
                position = _index_point_near(position_index, target_id, explode_ts)
                position_rule = "aura-remove-proxy"
            targets.append({
                **player_ref(players, actor_map, target_id),
                "applyTimeMs": apply_ts - fight_start,
                "applyTime": fmt_ms(apply_ts - fight_start),
                "removeTimeMs": int(remove_event['timestamp'])-fight_start if remove_event else None,
                "explodeTimeMs": (explode_ts - fight_start) if explode_ts else None,
                "explodeTime": fmt_ms(explode_ts - fight_start) if explode_ts else None,
                "position": position,
                "positionRule": position_rule,
            })
        named_ids = {row["playerID"] for row in targets}
        spacing = []
        for left_index, left in enumerate(targets):
            for right in targets[left_index + 1:]:
                if not left.get("position") or not right.get("position"):
                    continue
                distance = distance_yards(
                    (left["position"]["x"], left["position"]["y"]),
                    (right["position"]["x"], right["position"]["y"]),
                )
                spacing.append({
                    "left": left["player"],
                    "right": right["player"],
                    "distanceYards": round(distance, 1),
                    "tooClose": distance < GLOOMBOMB_RADIUS_YARDS,
                })
        nearby_unnamed = []
        collateral_hits = []
        seen_nearby = set()
        seen_collateral = set()
        for target in targets:
            explode_rel = target.get("explodeTimeMs")
            origin = target.get("position")
            if explode_rel is None or not origin:
                target["nearbyUnnamed"] = []
                target["collateralGravebound"] = []
                continue
            explode_ts = fight_start + int(explode_rel)
            gb_start = explode_ts - 250
            gb_end = explode_ts + GLOOMBOMB_GRAVEBOUND_WINDOW_MS
            nearby_rows = []
            collateral_rows = []
            for player_id in players:
                if player_id in named_ids:
                    continue
                other_pos = _index_point_near(position_index, player_id, explode_ts)
                if not other_pos:
                    continue
                distance = distance_yards(
                    (origin["x"], origin["y"]),
                    (other_pos["x"], other_pos["y"]),
                )
                if distance >= GLOOMBOMB_RADIUS_YARDS:
                    continue
                gravebound = _gravebound_apply_in_window(debuff_rows, player_id, gb_start, gb_end)
                row = {
                    **player_ref(players, actor_map, player_id),
                    "distanceYards": round(distance, 1),
                    "position": other_pos,
                    "fromPlayer": target["player"],
                    "fromPlayerID": target["playerID"],
                    "receivedGravebound": bool(gravebound),
                    "graveboundApplyTimeMs": (int(gravebound["timestamp"]) - fight_start) if gravebound else None,
                    "graveboundApplyTime": fmt_ms(int(gravebound["timestamp"]) - fight_start) if gravebound else None,
                }
                nearby_rows.append(row)
                if player_id not in seen_nearby:
                    nearby_unnamed.append(row)
                    seen_nearby.add(player_id)
                if gravebound:
                    collateral_rows.append(row)
                    if player_id not in seen_collateral:
                        collateral_hits.append(row)
                        seen_collateral.add(player_id)
            nearby_rows.sort(key=lambda row: (row["distanceYards"], row["player"]))
            target["nearbyUnnamed"] = nearby_rows
            target["collateralGravebound"] = collateral_rows
        too_close = [row for row in spacing if row["tooClose"]]
        explode_abs = [
            fight_start + int(target["explodeTimeMs"])
            for target in targets
            if target.get("explodeTimeMs") is not None
        ]
        boss_ts = min(explode_abs) if explode_abs and damage_events is not None else (timestamp if cast else first_ts)
        caster_id = (cast.get("sourceID") if cast and cast.get("sourceID") is not None else boss_actor_id)
        boss_position = (
            _index_point_at(origin_index or {}, caster_id, boss_ts, max_age_ms=POSITION_RELIABLE_MS)
            or _index_point_at(origin_index or {}, boss_actor_id, boss_ts, max_age_ms=POSITION_RELIABLE_MS)
            or _npc_point_at(npc_position_index or {}, caster_id, boss_ts, max_age_ms=POSITION_RELIABLE_MS)
            or _npc_point_at(npc_position_index or {}, boss_actor_id, boss_ts, max_age_ms=POSITION_RELIABLE_MS)
        )
        round_time_ms = timestamp - fight_start if cast else (round_ts - fight_start)
        rounds.append({
            "index": index,
            "phase": phase_at(round_time_ms, markers),
            "timeMs": round_time_ms,
            "time": fmt_ms(round_time_ms),
            "targetCount": len(targets),
            "targets": targets,
            "bossPosition": boss_position,
            "bossPositionTimeMs": boss_ts - fight_start,
            "spreadRadiusYards": GLOOMBOMB_RADIUS_YARDS,
            "pairSpacing": spacing,
            "tooClosePairs": too_close,
            "nearbyUnnamed": nearby_unnamed,
            "collateralHits": collateral_hits,
            "nearbyUnnamedCount": len(nearby_unnamed),
            "collateralCount": len(collateral_hits),
            "failed": bool(too_close or collateral_hits),
        })
    mythic_shield = annotate_gloombomb_soulcoilers(
        fight, rounds, casts, enemy_buffs, interrupts, npc_position_index or {},
        actor_map, players, actor_rows or [], markers, enemy_deaths=enemy_deaths,
        damage_events=damage_events,
    )
    note = (
        "点名玩家按爆炸伤害时刻取值；怨毒盘魂者优先直接取灵魂之盾掉层事件携带的目标坐标，"
        "否则只在本轮幽暗炸弹从点名到爆炸（约 5s）的同一 NPC instance 内取坐标。"
        "只列出爆炸时 15 码内、且 2 秒内获得墓缚 1286837 的非点名玩家。"
    )
    if mythic_shield:
        note += (
            "史诗怨毒盘魂者灵魂之盾（1309105）需两枚 15 码内幽暗炸弹移除；"
            "打断恐惧哀嚎后若盘魂者位移超过 8 码，且炸弹本可命中原位、爆炸时已出圈，记为打断炸空。"
        )
    return {
        "rounds": rounds,
        "hasSoulcoilerShield": bool(mythic_shield),
        "soulcoilerBombsRequired": SOULCOILER_BOMBS_REQUIRED,
        "evidenceNote": note,
    }


def _gravebound_damage_kill_id(death_event, damage_events=None):
    """只认 1297906 直接致死（WCL killingAbility）。"""
    kill_id = int(death_event.get("killingAbilityGameID") or 0)
    if kill_id == GRAVEBOUND_KILL_ID:
        return kill_id
    return None


def _is_gravebound_damage_death(row):
    if row.get("killedByGraveboundDamage") is False:
        return False
    return int(row.get("deathAbilityID") or 0) == GRAVEBOUND_KILL_ID


def analyze_gravebound_failures(fight, debuffs, deaths, actor_map, players, damage_events=None):
    """
    墓缚致死：只统计 1297906 作为 killing blow 直接打死的玩家。
    1286837 / 1308330 致死、带墓缚但死于其他技能均不计入。
    """
    fight_start = int(fight["startTime"])
    fight_end = int(fight["endTime"])
    open_applies = defaultdict(list)
    intervals = defaultdict(list)  # playerID -> [(apply_abs, remove_abs)]
    for event in sorted(debuffs or [], key=lambda row: int(row.get("timestamp") or 0)):
        spell = int(ability_id(event) or 0)
        if spell not in GRAVEBOUND_DEBUFF_IDS and spell not in GRAVEBOUND_IDS:
            continue
        # 1308330 主要是伤害，也可能出现在 debuff 流；debuff 区间优先 1286837
        if spell not in GRAVEBOUND_DEBUFF_IDS and spell != 1286837:
            continue
        target_id = event.get("targetID")
        if target_id not in players:
            continue
        timestamp = int(event["timestamp"])
        if is_apply(event):
            open_applies[target_id].append(timestamp)
        elif is_remove(event) and open_applies[target_id]:
            apply_ts = open_applies[target_id].pop(0)
            intervals[target_id].append((apply_ts, timestamp))
    for target_id, applies in open_applies.items():
        for apply_ts in applies:
            intervals[target_id].append((apply_ts, fight_end))

    def had_gravebound_at(target_id, timestamp):
        return any(apply_ts <= timestamp <= remove_ts for apply_ts, remove_ts in intervals.get(target_id) or [])

    rows = []
    seen = set()
    for event in sorted(deaths or [], key=lambda row: int(row.get("timestamp") or 0)):
        target_id = event.get("targetID")
        if target_id not in players:
            continue
        death_ts = int(event.get("timestamp") or 0)
        kill_id = _gravebound_damage_kill_id(event, damage_events)
        if not kill_id:
            continue
        key = (target_id, death_ts // 500)
        if key in seen:
            continue
        seen.add(key)
        apply_rel = None
        for apply_ts, remove_ts in intervals.get(target_id) or []:
            if apply_ts <= death_ts <= remove_ts:
                apply_rel = apply_ts - fight_start
                break
        rows.append({
            **player_ref(players, actor_map, target_id),
            "timeMs": death_ts - fight_start,
            "time": fmt_ms(death_ts - fight_start),
            "graveboundActive": had_gravebound_at(target_id, death_ts),
            "graveboundApplyTimeMs": apply_rel,
            "graveboundApplyTime": fmt_ms(apply_rel) if apply_rel is not None else None,
            "deathAbilityID": kill_id,
            "deathAbility": spell_name(kill_id, SPELLS),
            "killedByGraveboundDamage": True,
        })
    return {
        "failures": rows,
        "evidenceNote": (
            "只统计 1297906 直接致死；1286837 / 1308330 以及其他技能致死不计入。"
            "死亡时是否仍带墓缚 1286837 仅作标注。"
        ),
    }


def _nightfall_round_end(fight, casts_rows, index, start_ts):
    if index < len(casts_rows):
        return int(casts_rows[index]["timestamp"]) - 1
    return min(int(fight["endTime"]), start_ts + NIGHTFALL_ROUND_MAX_MS)


def _veil_shield_span(buff_rows, start_ts, end_ts):
    """配对本轮 1286912：只认完整 applybuff/removebuff，忽略层数跳动。"""
    apply_event = next(
        (
            event for event in buff_rows
            if int(ability_id(event) or 0) == VEIL_SHIELD
            and event_type(event) == "applybuff"
            and start_ts - NIGHTFALL_SHIELD_APPLY_LOOKBACK_MS <= int(event["timestamp"]) <= end_ts
        ),
        None,
    )
    remove_start = int(apply_event["timestamp"]) if apply_event else start_ts
    remove_event = next(
        (
            event for event in buff_rows
            if int(ability_id(event) or 0) == VEIL_SHIELD
            and event_type(event) == "removebuff"
            and remove_start <= int(event["timestamp"]) <= end_ts
        ),
        None,
    )
    return apply_event, remove_event


def _is_nightfall_interrupt(event):
    extra = int(event.get("extraAbilityGameID") or 0)
    if extra not in NIGHTFALL_INTERRUPTED_SPELLS:
        return False
    return event_type(event) in {"", "interrupt"}


def analyze_eternal_nightfall(
    fight,
    casts,
    enemy_buffs,
    interrupts,
    actor_map,
    players=None,
    friendly_damage=None,
    actor_rows=None,
    shield_target_id=None,
    markers=None,
    friendly_casts=None,
):
    del friendly_damage, shield_target_id  # 破盾只看 1286912 removebuff，不再统计打盾命中
    players = players or {}
    pet_owners = _pet_owner_map(actor_rows)
    casts_rows = [
        event for event in casts
        if int(ability_id(event) or 0) == ETERNAL_NIGHTFALL and event_type(event) == "begincast"
    ]
    interrupt_rows = [
        event for event in list(interrupts or []) + list(friendly_casts or [])
        if _is_nightfall_interrupt(event)
    ]
    buff_rows = sorted(enemy_buffs or [], key=lambda row: int(row.get("timestamp") or 0))
    fight_start = int(fight["startTime"])
    rounds = []
    for index, cast in enumerate(casts_rows, start=1):
        timestamp = int(cast["timestamp"])
        end = _nightfall_round_end(fight, casts_rows, index, timestamp)
        shield_apply, shield_remove = _veil_shield_span(buff_rows, timestamp, end)
        window_interrupts = [
            event for event in interrupt_rows
            if timestamp <= int(event.get("timestamp") or 0) <= end
        ]
        interrupt = window_interrupts[-1] if window_interrupts else None
        cast_success = any(
            event for event in casts
            if int(ability_id(event) or 0) == ETERNAL_NIGHTFALL
            and is_cast_complete(event)
            and timestamp <= int(event["timestamp"]) <= end
        )
        interrupt_player = None
        interrupt_spell_id = None
        if interrupt:
            interrupt_id = _resolve_player_source(interrupt, players, pet_owners) or interrupt.get("sourceID")
            interrupt_player = player_ref(players, actor_map, interrupt_id)
            interrupt_spell_id = int(interrupt.get("abilityGameID") or 0) or None
        rounds.append({
            "index": index,
            "phase": phase_at(timestamp - fight_start, markers or []),
            "timeMs": timestamp - fight_start,
            "time": fmt_ms(timestamp - fight_start),
            "shieldRemoved": bool(shield_remove),
            "shieldApplyTime": fmt_ms(int(shield_apply["timestamp"]) - fight_start) if shield_apply else None,
            "shieldRemoveTime": fmt_ms(int(shield_remove["timestamp"]) - fight_start) if shield_remove else None,
            "interrupted": bool(interrupt),
            "interruptTime": fmt_ms(int(interrupt["timestamp"]) - fight_start) if interrupt else None,
            "interruptSource": interrupt_player["player"] if interrupt_player else None,
            "interruptPlayer": interrupt_player,
            "interruptSpellID": interrupt_spell_id,
            "interruptSpell": spell_name(interrupt_spell_id, SPELLS) if interrupt_spell_id else None,
            "castCompleted": cast_success,
            "failed": cast_success or not shield_remove,
        })
    return {
        "rounds": rounds,
        "evidenceNote": (
            "护盾以本轮 1286912 的完整 removebuff 为准（不含层数跳动），窗口到下一发永恒夜幕为止。"
            "打断取友方 Interrupts 中 extraAbilityGameID 为 1286918/1310752 的最后一次，并标出打断玩家。"
            "不再统计破盾窗口内各玩家打盾伤害与命中次数。"
        ),
    }


def _cluster_events_by_time(events, merge_ms=250):
    waves = []
    for event in sorted(events or [], key=lambda row: int(row.get("timestamp") or 0)):
        ts = int(event.get("timestamp") or 0)
        if waves and ts - waves[-1]["timestamp"] <= merge_ms:
            waves[-1]["events"].append(event)
        else:
            waves.append({"timestamp": ts, "events": [event]})
    return waves


def _spirit_erasure_stepper_ids(wave, players, debuffs, friendly_damage, friendly_casts):
    """定位触发本次灵魂抹除的友方：伤害来源 / 易伤 debuff / 友方施法，不按承伤目标猜。"""
    wave_ts = int(wave["timestamp"])
    window_start = wave_ts - SPIRIT_ERASURE_STEPPER_WINDOW_MS
    window_end = wave_ts + SPIRIT_ERASURE_STEPPER_WINDOW_MS
    steppers = []
    seen = set()

    def add(player_id, evidence):
        if player_id not in players or player_id in seen:
            return
        seen.add(player_id)
        steppers.append((player_id, evidence))

    for event in wave.get("events") or []:
        add(event.get("sourceID"), "damage-source")
    for event in friendly_damage or []:
        if int(ability_id(event) or 0) != SPIRIT_ERASURE:
            continue
        ts = int(event.get("timestamp") or 0)
        if window_start <= ts <= window_end:
            add(event.get("sourceID"), "friendly-damage")
    for event in friendly_casts or []:
        if int(ability_id(event) or 0) != SPIRIT_ERASURE:
            continue
        if event_type(event) not in {"cast", "begincast"}:
            continue
        ts = int(event.get("timestamp") or 0)
        if window_start <= ts <= window_end:
            add(event.get("sourceID"), "friendly-cast")
    for event in debuffs or []:
        if int(ability_id(event) or 0) not in SPIRIT_ERASURE_DEBUFF_IDS:
            continue
        if not is_apply(event):
            continue
        ts = int(event.get("timestamp") or 0)
        if window_start <= ts <= window_end:
            add(event.get("targetID"), "desecrator-debuff")
    return steppers


def _dedupe_reclaim_events(events, merge_ms=250):
    """同一灵魂到达可能同时留下 cast/heal，按时间+来源去重。"""
    ordered = sorted(events or [], key=lambda row: (int(row.get("timestamp") or 0), int(row.get("sourceID") or 0)))
    kept = []
    for event in ordered:
        ts = int(event.get("timestamp") or 0)
        source_id = event.get("sourceID")
        duplicate = False
        for prev in kept:
            if prev.get("sourceID") != source_id:
                continue
            if abs(int(prev.get("timestamp") or 0) - ts) <= merge_ms:
                duplicate = True
                break
        if not duplicate:
            kept.append(event)
    return kept


def analyze_intermission(
    fight,
    enemy_buffs,
    damage,
    debuffs,
    actor_map,
    players,
    markers,
    heals=None,
    casts=None,
    friendly_damage=None,
    friendly_casts=None,
    deaths=None,
    zuljan_id=None,
    actor_rows=None,
    buffs=None,
):
    """
    转阶段漏片：残片未被踩到、抵达祖尔加时会施放收回精华（1287718）为其回血。
    以该技能的治疗/施法次数统计漏掉的灵魂数。
    踩片：1287722 是全团 AOE，按脉冲合并后找触发的友方，不把每个承伤目标当成一次踩片。
    """
    del markers  # 接口保留，当前转阶段窗口不依赖阶段标记
    start_event = next(
        (
            event for event in sorted(enemy_buffs, key=lambda row: int(row.get("timestamp") or 0))
            if int(ability_id(event) or 0) in INTERMISSION_BUFFS and is_apply(event)
        ),
        None,
    )
    if not start_event:
        return {"enabled": False, "reason": "本场未进入被夺取的容器转阶段。"}
    start = int(start_event["timestamp"])
    # 略加缓冲，避免窗口末尾到达的残片漏记
    end = start + INTERMISSION_MS + 2_000

    heal_hits = list(_events_between(heals or [], start, end, {RECLAIM_ESSENCE}))
    cast_hits = [
        event for event in _events_between(casts or [], start, end, {RECLAIM_ESSENCE})
        if is_cast_complete(event)
    ]
    damage_hits = list(_events_between(damage or [], start, end, {RECLAIM_ESSENCE}))

    # 优先治疗（漏片回血），再补施法；都没有时回退旧的 damage 桶
    if heal_hits or cast_hits:
        reclaim_events = _dedupe_reclaim_events(heal_hits + cast_hits)
        evidence_source = "heal+cast" if heal_hits and cast_hits else ("heal" if heal_hits else "cast")
    else:
        reclaim_events = _dedupe_reclaim_events(damage_hits)
        evidence_source = "damage-fallback"

    leaks = []
    total_heal = 0
    for event in reclaim_events:
        amount = event_amount(event)
        if amount:
            total_heal += int(amount)
        leaks.append({
            "timeMs": int(event["timestamp"]) - int(fight["startTime"]),
            "time": fmt_ms(int(event["timestamp"]) - int(fight["startTime"])),
            "sourceID": event.get("sourceID"),
            "source": actor_name(actor_map, event.get("sourceID")),
            "targetID": event.get("targetID"),
            "target": actor_name(actor_map, event.get("targetID")),
            "amount": amount or None,
            "eventType": event_type(event) or None,
        })

    erasure_hits = [
        event for event in _events_between(damage, start, end, {SPIRIT_ERASURE})
        if event.get("targetID") in players and event_type(event) in {"", "damage"}
    ]
    steps = []
    for index, wave in enumerate(_cluster_events_by_time(erasure_hits, SPIRIT_ERASURE_WAVE_MS), start=1):
        steppers = _spirit_erasure_stepper_ids(
            wave, players, debuffs, friendly_damage or [], friendly_casts or [],
        )
        hit_ids = []
        seen_hits = set()
        for event in wave["events"]:
            target_id = event.get("targetID")
            if target_id in seen_hits:
                continue
            seen_hits.add(target_id)
            hit_ids.append(target_id)
        primary = steppers[0][0] if steppers else None
        row = {
            "index": index,
            "timeMs": wave["timestamp"] - int(fight["startTime"]),
            "time": fmt_ms(wave["timestamp"] - int(fight["startTime"])),
            "hitCount": len(hit_ids),
            "evidence": steppers[0][1] if steppers else "unknown",
            "steppers": [
                {**player_ref(players, actor_map, player_id), "evidence": evidence}
                for player_id, evidence in steppers
            ],
        }
        if primary is not None:
            row.update(player_ref(players, actor_map, primary))
        else:
            row["player"] = None
            row["playerID"] = None
        steps.append(row)

    potion_start = start - INTERMISSION_POTION_LOOKBACK_MS
    potion_ends = [int(e["timestamp"]) for e in enemy_buffs
                   if int(e.get("timestamp") or 0) > start and (
                       ability_id(e) in INTERMISSION_BUFFS and is_remove(e)
                       or ability_id(e) == P3_SOULBOUND and is_apply(e))]
    potion_end = min(min(potion_ends, default=start+INTERMISSION_MS), int(fight["endTime"]))
    potion_uses = {}
    for event in list(friendly_casts or []) + list(buffs or []):
        spell_id = int(ability_id(event) or 0)
        if spell_id not in INTERMISSION_POTIONS:
            continue
        kind = event_type(event)
        if kind == "cast":
            player_id = event.get("sourceID")
        elif kind in {"applybuff", "refreshbuff"}:
            player_id = event.get("targetID") or event.get("sourceID")
        else:
            continue
        ts = int(event.get("timestamp") or 0)
        if player_id not in players or not (potion_start <= ts < potion_end):
            continue
        prev = potion_uses.get(player_id)
        if prev is not None and ts >= prev["timestamp"]:
            continue
        potion_uses[player_id] = {
            "timestamp": ts,
            "spellID": spell_id,
            "spellName": INTERMISSION_POTIONS[spell_id],
            "evidence": "cast" if kind == "cast" else "buff",
        }

    pet_owners = _pet_owner_map(actor_rows)
    damage_by = defaultdict(lambda: {"damage": 0})
    if zuljan_id is not None:
        for event in friendly_damage or []:
            if event_type(event) != "damage" or event.get("targetID") != zuljan_id:
                continue
            ts = int(event.get("timestamp") or 0)
            if not (start <= ts <= end):
                continue
            source_id = _resolve_player_source(event, players, pet_owners)
            if source_id is None or _player_is_healer(players, source_id):
                continue
            amount = int(event.get("amount") or 0) + int(event.get("absorbed") or 0)
            if amount <= 0:
                continue
            damage_by[source_id]["damage"] += amount

    alive = _alive_player_ids(players, deaths, friendly_casts, start)
    for event in friendly_casts or []:
        if event.get("targetID") not in players:
            continue
        if int(ability_id(event) or 0) not in COMBAT_RES_SPELLS:
            continue
        if event_type(event) not in {"cast", "applybuff"}:
            continue
        ts = int(event.get("timestamp") or 0)
        if start <= ts <= end:
            alive.add(event.get("targetID"))

    total_boss_damage = sum(row["damage"] for row in damage_by.values())
    survivors = []
    for player_id in alive:
        if _player_is_healer(players, player_id):
            continue
        potion = potion_uses.get(player_id)
        stats = damage_by.get(player_id) or {"damage": 0}
        damage_total = stats["damage"]
        pct = round(100.0 * damage_total / total_boss_damage, 1) if total_boss_damage else 0.0
        survivors.append({
            **player_ref(players, actor_map, player_id),
            "potionUsed": bool(potion),
            "potionDuringVulnerability": bool(potion and start <= potion["timestamp"] < potion_end),
            "potionPrecast": bool(potion and potion["timestamp"] < start),
            "potionSpellID": potion["spellID"] if potion else None,
            "potionName": potion["spellName"] if potion else None,
            "potionTimeMs": (potion["timestamp"] - int(fight["startTime"])) if potion else None,
            "potionTime": fmt_ms(potion["timestamp"] - int(fight["startTime"])) if potion else None,
            "potionEvidence": potion["evidence"] if potion else None,
            "zuljanDamage": damage_total,
            "zuljanPercent": pct,
        })
    survivors.sort(key=lambda row: (-row["zuljanDamage"], row["player"] or ""))
    potion_used_count = sum(1 for row in survivors if row["potionUsed"])
    return {
        "enabled": True,
        "startTimeMs": start - int(fight["startTime"]),
        "startTime": fmt_ms(start - int(fight["startTime"])),
        "durationMs": INTERMISSION_MS,
        "duration": fmt_ms(INTERMISSION_MS),
        "leakedFragments": leaks,
        "leakCount": len(leaks),
        "leakedSoulCount": len(leaks),
        "reclaimHealTotal": total_heal or None,
        "reclaimEvidenceSource": evidence_source,
        "spiritErasureSteps": steps,
        "spiritErasureStepCount": len(steps),
        "survivors": survivors,
        "survivorCount": len(survivors),
        "potionUsedCount": potion_used_count,
        "zuljanDamageTotal": total_boss_damage,
        "evidenceNote": (
            "漏掉的灵魂以收回精华（Reclaim Essence，1287718）为准："
            "残片抵达祖尔加回血即记 1 次漏片。"
            "灵魂抹除 1287722 是全团 AOE：同一脉冲合并为 1 次踩片，"
            "踩片者以友方伤害来源、1287722 易伤施加或友方施法为准，不用承伤目标计数。"
            "爆发药水与对祖尔加护盾伤害只统计非治疗玩家（转阶段开始时存活，含战复）："
            "是否使用圣光潜力 1236616、鲁莽药水 1236994 或液态光泽 1295132；"
            "对祖尔加伤害取该窗口对祖尔加的 DamageDone，不计命中次数，不含治疗。"
        ),
    }


def build_field_audit(
    arena, toxic_deluge, sever, soul_sever, gloombomb, blighted_sever,
    manifestations=None, guillotine=None, grim_guillotine=None,
):
    """场地示意图：撕裂锥形清场 + 处斩跑离 + 幽暗炸弹分散 + 史诗毒液/烈毒变异体落点。"""
    blast_radius = toxic_deluge.get("virulentBlastRadiusYards", VIRULENT_BLAST_RADIUS_YARDS)
    diagrams = []

    def append_cone_diagram(row, mechanic, primary_key):
        targets = []
        links = []
        source_points = row.get("nearbyPoints") or row.get(primary_key) or []
        for point in source_points:
            if (point.get("kind") == "manifestation") or point.get("manifestPosition") or (
                mechanic in {"灵魂撕裂", "凋零撕裂"} and point.get("manifest")
            ):
                manifest_pos = point.get("manifestPosition") or point.get("position")
                player_pos = point.get("playerPosition")
                uncleared = bool(point.get("uncleared")) if "uncleared" in point else True
                # 灵魂撕裂 / 凋零撕裂：红线只连本轮未消掉凝视的玩家
                draw_link = uncleared if mechanic in {"灵魂撕裂", "凋零撕裂"} else True
                if manifest_pos:
                    targets.append({
                        **{k: point.get(k) for k in ("player", "classColor", "manifest", "playerID", "clearOutcome", "icon", "role", "specID", "specName", "className") if point.get(k) is not None},
                        "kind": "manifestation",
                        "position": manifest_pos,
                        "manifestPosition": manifest_pos,
                        "playerPosition": player_pos,
                        "inCone": bool(point.get("inCone")),
                        "debuffCleared": bool(point.get("debuffCleared")),
                        "uncleared": uncleared,
                    })
                if player_pos and (mechanic not in {"灵魂撕裂", "凋零撕裂"} or draw_link):
                    targets.append({
                        **{k: point.get(k) for k in ("player", "classColor", "playerID", "icon", "role", "specID", "specName", "className") if point.get(k) is not None},
                        "kind": "manifest-target",
                        "position": player_pos,
                        "uncleared": uncleared,
                        "clearOutcome": point.get("clearOutcome"),
                    })
                if draw_link and manifest_pos and player_pos:
                    links.append({
                        "from": player_pos,
                        "to": manifest_pos,
                        "player": point.get("player"),
                        "clearOutcome": point.get("clearOutcome"),
                    })
            else:
                targets.append(point)
        if row.get("tankPosition"):
            targets = [{
                "kind": "tank",
                "player": "当前坦克",
                "position": row["tankPosition"],
            }] + targets
        annotation = row.get("evidenceNote") or ""
        if row.get("facingInferred"):
            annotation = (annotation + "；锥形朝向为根据附近标记点估算，仅供示意。").strip("；")
        if mechanic in {"灵魂撕裂", "凋零撕裂"} and row.get("clearedByDebuff") is not None:
            annotation = annotation or (
                f"释放前具象 {len([p for p in source_points if p.get('kind') == 'manifestation' or p.get('manifestPosition')])}；"
                f"锥内 {row.get('clearedByGeometry')}；"
                f"debuff 清掉 {row.get('clearedByDebuff')}；未消掉 {row.get('unclearedCount')}（红线）"
            )
        elif mechanic == "凋零撕裂":
            annotation = annotation or f"P3 组合清场推断 {row.get('inferredClearedCount')}"
        else:
            mutation_n = sum(1 for point in targets if point.get("venomKind") == VENOM_KIND_MUTATION)
            annotation = annotation or (
                f"推断清理 {row.get('inferredClearedCount')} 团，几何命中 {row.get('clearedByGeometry')}"
                + (f"；烈毒变异体 {mutation_n} 团（紫圈 {blast_radius:g} 码）" if mutation_n else "")
            )
        diagrams.append({
            "kind": "cone-clear",
            "mechanic": mechanic,
            "roundIndex": row["index"],
            "phase": row["phase"],
            "time": row["time"],
            "timeMs": row.get("timeMs"),
            "origin": row.get("origin"),
            "originRule": row.get("originRule"),
            "tankPosition": row.get("tankPosition"),
            "conePolygon": row.get("conePolygon") or [],
            "coneRadiusYards": row.get("coneRadiusYards", CONE_RADIUS_YARDS),
            "coneHalfAngleDeg": row.get("coneHalfAngleDeg", CONE_HALF_ANGLE_DEG),
            "facingRadians": row.get("facingRadians"),
            "facingRule": row.get("facingRule"),
            "facingLockMs": row.get("facingLockMs"),
            "facingInferred": bool(row.get("facingInferred")),
            "targets": targets,
            "links": links,
            "clearedCount": row.get("inferredClearedCount", row.get("clearedByGeometry")),
            "unclearedCount": row.get("unclearedCount"),
            "assignedSideLabel": (row.get("mythicDelugePair") or {}).get("sideLabel"),
            "annotation": annotation,
        })

    def append_runout_diagram(row, mechanic, annotation):
        targets = []
        for participant in row.get("participants") or []:
            if not participant.get("position"):
                continue
            targets.append({
                **{k: participant.get(k) for k in ("player", "classColor", "playerID", "role", "icon") if participant.get(k) is not None},
                "kind": "guillotine-share",
                "position": participant["position"],
            })
        for inside in row.get("stillInsideRange") or []:
            if not inside.get("position"):
                continue
            targets.append({
                **{k: inside.get(k) for k in ("player", "classColor", "playerID", "role", "icon") if inside.get(k) is not None},
                "kind": "guillotine-inside",
                "position": inside["position"],
                "distanceFromShareYards": inside.get("distanceFromShareYards"),
            })
        if row.get("shareCentroid") or targets:
            diagrams.append({
                "kind": "runout",
                "mechanic": mechanic,
                "roundIndex": row["index"],
                "phase": row["phase"],
                "time": row["time"],
            "timeMs": row.get("timeMs"),
                "origin": row.get("shareCentroid"),
                "bossPosition": row.get("bossPosition"),
                "dangerRadiusYards": row.get("dangerRadiusYards", GUILLOTINE_RANGE_YARDS),
                "targets": targets,
            "annotation": annotation,
        })

    def append_venom_diagram(row):
        targets = []
        for spawn in row.get("spawns") or []:
            if not spawn.get("position"):
                continue
            kind = spawn.get("venomKind") or VENOM_KIND_NORMAL
            targets.append({
                "kind": _venom_map_kind(kind, grounded=False),
                "venomKind": kind,
                "position": spawn["position"],
                "timeMs": spawn.get("timeMs"),
                "player": "烈毒变异体生成" if kind == VENOM_KIND_MUTATION else "凝结毒液生成",
            })
        last_drops = {}
        for drop in row.get("drops") or []:
            if drop.get("puddleID") is None or not drop.get("dropPosition"):
                continue
            last_drops[drop["puddleID"]] = drop
        for drop in last_drops.values():
            kind = drop.get("venomKind") or VENOM_KIND_NORMAL
            mutation = kind == VENOM_KIND_MUTATION
            targets.append({
                **{k: drop.get(k) for k in ("player", "classColor", "playerID", "icon", "role") if drop.get(k) is not None},
                "kind": _venom_map_kind(kind, grounded=True),
                "venomKind": kind,
                "position": drop["dropPosition"],
                "timeMs": drop.get("removeTimeMs"),
                "blastRadiusYards": _venom_blast_yards(kind, blast_radius) if mutation else None,
                "finalDrop": True,
            })
        if not targets:
            return
        mutation_n = sum(1 for target in targets if target.get("venomKind") == VENOM_KIND_MUTATION and target.get("finalDrop"))
        diagrams.append({
            "kind": "venom-field",
            "mechanic": "剧毒洪流",
            "roundIndex": row["index"],
            "phase": row["phase"],
            "time": row["time"],
            "timeMs": row.get("timeMs"),
            "targets": targets,
            "virulentBlastRadiusYards": blast_radius,
            "annotation": (
                f"生成 {row.get('spawnCount', 0)} 团"
                + (f"，其中烈毒变异体 {row.get('mutationSpawnCount', 0)} 团" if row.get("mutationSpawnCount") else "")
                + f"；最终落点 {len(last_drops)} 团"
                + (f"；紫圈为烈毒变异体 {blast_radius:g} 码引爆范围（{mutation_n} 团）" if mutation_n else "")
            ),
        })

    for row in (toxic_deluge.get("rounds") or []):
        append_venom_diagram(row)
    for row in (sever.get("rounds") or []):
        append_cone_diagram(row, row.get("label") or "撕裂", "targetsInCone")
    for row in ((guillotine or {}).get("rounds") or []):
        append_runout_diagram(
            row,
            row.get("label") or "处斩",
            (
                f"分摊 {row.get('participantCount', 0)} 人；"
                f"（{row.get('dangerRadiusYards', GUILLOTINE_RANGE_YARDS)} 码内）"
                f" {len(row.get('stillInsideRange') or [])} 人"
            ),
        )
    for row in (gloombomb.get("rounds") or []):
        targets = [target for target in (row.get("targets") or []) if target.get("position")]
        collateral = [
            player for player in (row.get("collateralHits") or [])
            if player.get("position")
        ]
        if not targets and not (row.get("soulcoilers") or []):
            continue
        too_close = row.get("tooClosePairs") or []
        bomb_targets = []
        for target in targets:
            bomb_targets.append({**target, "kind": target.get("kind") or "bomb"})
        for coiler in row.get("soulcoilers") or []:
            current_pos = coiler.get("position")
            if not current_pos:
                continue
            bomb_targets.append({
                "kind": "soulcoiler",
                "player": coiler.get("name") or "怨毒盘魂者",
                "position": current_pos,
                "sourceInstance": coiler.get("sourceInstance"),
                "shieldStacks": coiler.get("shieldStacks"),
                "bombHits": coiler.get("bombHits"),
                "displacedMiss": coiler.get("displacedMiss"),
            })
        if not bomb_targets:
            continue
        miss_n = row.get("displacedMissCount") or 0
        shield_note = ""
        if row.get("soulcoilers"):
            shield_note = (
                f"；怨毒盘魂者 {row.get('soulcoilerCount', 0)}；"
                f"盾层命中 {row.get('shieldHits', 0)}"
                + (f"；打断炸空 {miss_n}" if miss_n else "")
            )
        diagrams.append({
            "kind": "spread",
            "mechanic": "幽暗炸弹",
            "roundIndex": row["index"],
            "phase": row["phase"],
            "time": row["time"],
            "timeMs": row.get("timeMs"),
            "bossPosition": row.get("bossPosition"),
            "targets": bomb_targets,
            "nearbyPlayers": collateral,
            "spreadRadiusYards": row.get("spreadRadiusYards", GLOOMBOMB_RADIUS_YARDS),
            "tooClosePairs": too_close,
            "annotation": (
                f"点名 {row.get('targetCount', 0)} 人；"
                f"过近组合 {len(too_close)}；"
                f"误伤墓缚 {row.get('collateralCount', len(collateral))}"
                f"（分散半径 {row.get('spreadRadiusYards', GLOOMBOMB_RADIUS_YARDS)} 码）"
                f"{shield_note}"
            ),
        })
    for row in (soul_sever.get("rounds") or []):
        # 用释放前全部活跃具象；红线仅未消掉 debuff
        append_cone_diagram(row, "灵魂撕裂", "nearbyPoints")
    for row in ((grim_guillotine or {}).get("rounds") or []):
        append_runout_diagram(
            row,
            row.get("label") or "冷酷处斩",
            (
                f"分摊 {row.get('participantCount', 0)} 人；"
                f"死亡低语脉冲后仍吃死亡之拥（{row.get('dangerRadiusYards', GUILLOTINE_RANGE_YARDS)} 码内）"
                f" {len(row.get('stillInsideRange') or [])} 人"
            ),
        )
    for row in (blighted_sever.get("rounds") or []):
        append_cone_diagram(row, row.get("label") or "凋零撕裂", "targetsInCone")

    return {
        "arena": arena,
        "arenaImage": ARENA_IMAGE,
        "icons": dict(FIELD_ICONS),
        "diagrams": diagrams,
        "evidenceNote": (
            f"场地中心 ({ARENA_CENTER_X_UNITS:g}, {ARENA_CENTER_Y_UNITS:g}) 码，石台边长 {int(ARENA_SIDE_YARDS)} 码（WCL 坐标=码×100）。"
            f"史诗烈毒变异体最终落点按 {blast_radius:g} 码紫圈绘制引爆范围。"
        ),
    }


def _analysis_needs(options):
    # Clearing mechanics require the objects being cleared even when their own
    # report section is deselected. Map generation never enables other reviews.
    needs = dict(options)
    needs["toxicDelugeReviewEnabled"] |= options["severReviewEnabled"] or options["blightedSeverReviewEnabled"]
    needs["manifestationsReviewEnabled"] |= options["soulSeverReviewEnabled"] or options["blightedSeverReviewEnabled"]
    needs["positions"] = any(needs[key] for key in (
        "toxicDelugeReviewEnabled", "manifestationsReviewEnabled", "severReviewEnabled",
        "blightedSeverReviewEnabled", "soulSeverReviewEnabled", "guillotineReviewEnabled",
        "grimGuillotineReviewEnabled", "gloombombReviewEnabled"))
    return needs


def analyze_fight(fight, actor_map, actor_type, actor_rows, raw):
    fight = _with_observed_tuning(fight, raw)
    options = resolve_analysis_options(CONFIG_SCHEMA, raw.get("analysisOptions") or {})
    needs = _analysis_needs(options)
    field_enabled = needs["positions"]
    players = build_player_catalog(actor_map, actor_type, raw["combatants"])
    deaths = [event for event in raw["deaths"] if event.get("targetID") in players]
    enemy_deaths = [event for event in raw["enemyDeaths"] if event.get("targetID") not in players]
    raw["deaths"] = deaths
    actor_catalog = build_actor_catalog(actor_rows)
    manifest_ids = manifest_actor_ids(actor_rows)
    mutation_ids = virulent_mutation_actor_ids(actor_rows)
    soulcoiler_ids = soulcoiler_actor_ids(actor_rows)
    npc_position_events = _npc_position_events(raw, set(manifest_ids) | set(mutation_ids) | set(soulcoiler_ids)) if field_enabled else []
    npc_position_index = build_npc_position_index(npc_position_events) if field_enabled else {}
    zuljan_id = resolve_boss_actor_id(actor_rows, 257911, ("Zul'jan", "祖尔加"))
    malacrass_id = resolve_boss_actor_id(actor_rows, 259854, ("Hex Lord Malacrass", "玛拉卡斯", "Malacrass"))
    boss_id = zuljan_id or malacrass_id
    boss_ids = {actor_id for actor_id in (zuljan_id, malacrass_id) if actor_id is not None}
    markers = build_phase_markers(
        fight, raw["casts"], raw["enemyBuffs"],
        enemy_deaths=enemy_deaths, zuljan_id=zuljan_id, malacrass_id=malacrass_id,
    )
    boss_position_events = _npc_position_events(raw, boss_ids) if field_enabled else []
    caster_index = build_caster_self_position_index(
        list(raw.get("casts") or [])
        + list(raw.get("damage") or [])
        + list(raw.get("resources") or [])
        + list(raw.get("npcPositionEvents") or []),
        boss_ids or None,
    ) if field_enabled else {}
    position_events = (
        list(raw.get("damage") or [])
        + list(raw.get("debuffs") or [])
        + list(raw.get("resources") or [])
        + list(raw.get("npcPositionEvents") or [])
        + boss_position_events
    )
    position_index = build_position_index(position_events) if field_enabled else {}
    arena = coiledaltar_arena(position_index, list(players), boss_id=boss_id) if field_enabled else {}
    if arena:
        arena["virulentBlastRadiusYards"] = encounter_tuning(fight)["mutationRadiusYards"]

    toxic_deluge = analyze_toxic_deluge(
        fight, raw["casts"], raw["debuffs"], position_index, actor_map, players, markers,
        damage_events=list(raw.get("damage") or []),
    ) if needs["toxicDelugeReviewEnabled"] else {}
    if toxic_deluge:
        toxic_deluge["expectedP1InitialOrbCount"] = encounter_tuning(fight)["p1InitialOrbCount"]
        toxic_deluge["expectedP1MutationCount"] = encounter_tuning(fight)["p1MutationCount"]
        _merge_venom_drop_spawns(toxic_deluge)
    venom_points = build_active_venom_points(toxic_deluge) if field_enabled else []
    manifestations = analyze_manifestations(
        fight, raw["debuffs"], npc_position_index, actor_map, players, actor_catalog, markers,
        enemy_deaths=enemy_deaths, position_index=position_index, player_deaths=deaths,
    ) if needs["manifestationsReviewEnabled"] else {}
    active_points = venom_points + (manifestations.get("activePoints") or [])

    sever = analyze_cone_sever(
        "撕裂", SEVER_IDS, fight, raw["casts"], raw["debuffs"], position_index, actor_map, players, markers,
        venom_points, actor_catalog, boss_actor_id=zuljan_id, origin_index=caster_index,
    ) if options["severReviewEnabled"] else {}
    blighted_sever = analyze_cone_sever(
        "凋零撕裂", BLIGHTED_SEVER_IDS, fight, raw["casts"], raw["debuffs"], position_index, actor_map, players, markers,
        active_points, actor_catalog, boss_actor_id=zuljan_id, origin_index=caster_index,
        npc_position_index=npc_position_index,
    ) if options["blightedSeverReviewEnabled"] else {}
    if int(fight.get("difficulty") or 0) == MYTHIC_DIFFICULTY:
        annotate_mythic_sever_deluge_pairs(fight, toxic_deluge, sever, blighted_sever, venom_points)
    _reconcile_venom_severs(fight, raw, venom_points, sever, blighted_sever)
    guillotine = analyze_guillotine(
        fight, raw["casts"], raw["damage"], raw["debuffs"], position_index, actor_map, players, markers,
        GUILLOTINE_CAST_IDS, "处斩",
        pulse_damage_id=WIDOW_TOUCH_DAMAGE_ID,
        in_range_damage_id=WIDOW_KISS_DAMAGE_ID,
        origin_index=caster_index,
        boss_actor_id=zuljan_id,
    ) if options["guillotineReviewEnabled"] else {}
    grim_guillotine = analyze_guillotine(
        fight, raw["casts"], raw["damage"], raw["debuffs"], position_index, actor_map, players, markers,
        GRIM_GUILLOTINE_CAST_IDS, "冷酷处斩",
        damage_ids=GRIM_GUILLOTINE_DAMAGE_IDS,
        mark_ids=GRIM_GUILLOTINE_MARK_IDS,
        pulse_damage_id=DEATH_WHISPER_DAMAGE_ID,
        in_range_damage_id=DEATH_EMBRACE_DAMAGE_ID,
        origin_index=caster_index,
        boss_actor_id=zuljan_id,
    ) if options["grimGuillotineReviewEnabled"] else {}
    dreadmarch = analyze_dreadmarch(
        fight, raw["casts"], raw["debuffs"], raw["damage"], [],
        deaths, actor_map, players, markers,
    ) if options["dreadmarchReviewEnabled"] else {}
    if dreadmarch:
        dreadmarch["expectedInitialTargetCount"] = encounter_tuning(fight)["dreadmarchTargetCount"]
    soul_sever = analyze_soul_sever(
        fight, raw["casts"], enemy_deaths, position_index, actor_map, markers, manifestations.get("activePoints") or [],
        boss_actor_id=malacrass_id, origin_index=caster_index, debuffs=raw["debuffs"],
        npc_position_index=npc_position_index,
    ) if options["soulSeverReviewEnabled"] else {}
    gloombomb = analyze_gloombomb(
        fight, raw["casts"], raw["debuffs"], position_index, actor_map, players, markers,
        origin_index=caster_index, boss_actor_id=malacrass_id,
        npc_position_index=npc_position_index, actor_rows=actor_rows,
        enemy_buffs=raw.get("enemyBuffs") or [], interrupts=raw.get("interrupts") or [],
        enemy_deaths=enemy_deaths, damage_events=list(raw.get("damage") or []),
    ) if options["gloombombReviewEnabled"] else {}
    gravebound = analyze_gravebound_failures(
        fight, raw["debuffs"], deaths, actor_map, players,
        damage_events=list(raw.get("damage") or []),
    ) if options["graveboundReviewEnabled"] else {}
    eternal = analyze_eternal_nightfall(
        fight, raw["casts"], raw["enemyBuffs"], raw.get("interrupts") or [], actor_map,
        players=players,
        actor_rows=actor_rows,
        markers=markers,
        friendly_casts=raw.get("friendlyCasts") or [],
    ) if options["eternalNightfallReviewEnabled"] else {}
    intermission = analyze_intermission(
        fight, raw["enemyBuffs"], raw["damage"], raw["debuffs"], actor_map, players, markers,
        heals=list(raw.get("heals") or []),
        casts=raw.get("casts") or [],
        friendly_damage=raw.get("bossDamage") or [],
        friendly_casts=raw.get("friendlyCasts") or [],
        deaths=deaths,
        zuljan_id=zuljan_id,
        actor_rows=actor_rows,
        buffs=raw.get("buffs") or [],
    ) if options["intermissionReviewEnabled"] else {}
    field_audit = build_field_audit(
        arena, toxic_deluge if options["toxicDelugeReviewEnabled"] else {}, sever, soul_sever, gloombomb, blighted_sever,
        manifestations if options["manifestationsReviewEnabled"] else {},
        guillotine=guillotine, grim_guillotine=grim_guillotine,
    ) if options["fieldReplayEnabled"] and field_enabled else {}

    return {
        "phaseTimeline": markers,
        "toxicDeluge": toxic_deluge if options["toxicDelugeReviewEnabled"] else {},
        "sever": sever,
        "guillotine": guillotine,
        "dreadmarch": dreadmarch,
        "manifestations": manifestations if options["manifestationsReviewEnabled"] else {},
        "soulSever": soul_sever,
        "gloombomb": gloombomb,
        "graveboundFailures": gravebound,
        "eternalNightfall": eternal,
        "intermission": intermission,
        "blightedSever": blighted_sever,
        "grimGuillotine": grim_guillotine,
        "fieldAudit": field_audit,
        "npcCatalog": {
            "manifestNpcGameID": MANIFEST_NPC_GAME_ID,
            "manifestActors": actor_catalog["byGameID"].get(MANIFEST_NPC_GAME_ID, []),
            "soulcoilerNpcGameID": SOULCOILER_NPC_GAME_ID,
            "soulcoilerActors": actor_catalog["byGameID"].get(SOULCOILER_NPC_GAME_ID, []),
            "soulcoilerActorIDs": sorted(soulcoiler_ids),
            "soulcoilerPositionSampleKeys": sorted(
                f"{actor_id}:{instance}"
                for actor_id, instance in npc_position_index
                if actor_id in soulcoiler_ids
            ),
            "positionEventCount": len(npc_position_events),
            "positionSampleKeys": sorted(
                {f"{actor_id}:{instance}" for actor_id, instance in npc_position_index}
            ),
        },
    }


def _merge_venom_drop_spawns(venom):
    """A carried globule's observed respawn is its drop, not another globule."""
    drops = [c for c in venom.get('carriers', []) if c.get('removeTimeMs') is not None and c.get('dropPosition')]
    aliases = {}
    for p in venom.get('groundPuddles', []):
        t, pos = p.get('groundedFromMs'), p.get('position')
        if t is None or not pos:
            continue
        matches = [c for c in drops if c.get('puddleID') != p.get('puddleID')
                   and c.get('venomKind') == p.get('venomKind')
                   and abs(c['removeTimeMs']-t) <= 300
                   and math.hypot(pos['x']-c['dropPosition']['x'], pos['y']-c['dropPosition']['y']) <= 100]
        if len(matches) == 1:
            aliases[p['puddleID']] = matches[0]['puddleID']
    def resolve(key):
        seen = set()
        while key in aliases and key not in seen:
            seen.add(key)
            key = aliases[key]
        return key
    def remap(value):
        if isinstance(value, dict):
            if 'puddleID' in value:
                value['puddleID'] = resolve(value['puddleID'])
            for child in value.values():
                remap(child)
        elif isinstance(value, list):
            for child in value:
                remap(child)
    remap(venom)
    for round_row in venom.get('rounds', []):
        for spawn in round_row.get('spawns', []):
            pos = spawn.get('position')
            if not pos:
                continue
            matches = [c for c in drops if c.get('venomKind') == spawn.get('venomKind')
                       and abs(c['removeTimeMs']-spawn['spawnTimeMs']) <= 300
                       and math.hypot(pos['x']-c['dropPosition']['x'], pos['y']-c['dropPosition']['y']) <= 100]
            if len(matches) == 1:
                spawn.update(dropRespawn=True, puddleID=matches[0]['puddleID'])
        round_row['spawnCount'] = sum(not s.get('dropRespawn') for s in round_row.get('spawns', []))
    venom['mergedDropSpawnCount'] = len(aliases)


def _reconcile_venom_severs(fight, raw, venom_points, *sections):
    """Cross-check real stack changes and unique ground-object geometry."""
    start = int(fight['startTime'])
    if not any(section.get('rounds') for section in sections):
        return
    stacks = defaultdict(list)
    for e in sorted(raw.get('debuffs', []), key=lambda e:int(e['timestamp'])):
        if ability_id(e) != VENOM_RUPTURE:
            continue
        kind = event_type(e)
        value = 0 if kind in {'removedebuff', 'removebuff'} else int(e.get('stack') or 1)
        stacks[e.get('targetID')].append((int(e['timestamp']), value))
    rows = sorted([r for section in sections for r in section.get('rounds', [])], key=lambda r:r['timeMs'])
    cleared = {}
    phase_cleanups = [int(p['startTime'])-start for p in fight.get('phaseTransitions', [])
                      if p.get('id') == 2]
    for row in rows:
        ts = start+row['timeMs']
        next_phase = min([int(p['startTime']) for p in fight.get('phaseTransitions', []) if int(p['startTime']) > ts]+[ts+750])
        deltas = []
        for pid, changes in stacks.items():
            before = next((v for t, v in reversed(changes) if t < ts), 0)
            values = [v for t, v in changes if ts <= t < min(ts+751, next_phase)]
            if values and max(values) > before:
                deltas.append((pid, max(values)-before))
        observed = Counter(v for _, v in deltas).most_common(1)
        actual = observed[0][0] if observed else None
        candidates = {}
        for p in venom_points:
            grounded = p.get('groundedFromMs', p.get('timeMs'))
            picked = p.get('pickedUpAtMs')
            key = p.get('puddleID')
            if key is None or grounded is None or grounded > row['timeMs'] or picked is not None and picked <= row['timeMs']:
                continue
            if any(grounded < boundary <= row['timeMs'] for boundary in phase_cleanups):
                continue
            if grounded <= cleared.get(key, -1):
                continue
            if key not in candidates or grounded > candidates[key].get('groundedFromMs', -1):
                candidates[key] = p
        origin = _position_xy(row.get('origin'))
        if not origin or row.get('facingRadians') is None:
            continue
        angles = [row['facingRadians']]
        cast = next((e for e in raw.get('casts', []) if is_cast_complete(e) and ability_id(e) == row['spellID'] and int(e['timestamp']) == ts), None)
        own_facing = normalize_facing_radians((cast.get('sourceResources') or {}).get('facing', cast.get('facing'))) if cast else None
        if own_facing is not None:
            angles.append(own_facing)
        alternatives = []
        for angle in angles:
            hits = [p for p in candidates.values() if p.get('position') and in_frontal_cone(origin, angle, _position_xy(p['position']))]
            alternatives.append((angle, hits))
        matching = [(a, h) for a, h in alternatives if actual is not None and len(h) == actual]
        sets = {tuple(sorted(p['puddleID'] for p in h)) for _, h in matching}
        verified = len(sets) == 1
        angle, hits = matching[0] if verified else alternatives[0]
        row['stackClearCheck'] = {'observedCount':actual, 'geometryCount':len(hits),
            'samplePlayers':len(deltas), 'status':'matched' if verified else 'unresolved',
            'matchingSubsetUnique':verified}
        if angle != row['facingRadians']:
            row.update(facingRadians=angle, facingRule='caster-facing-stack-verified',
                       conePolygon=cone_polygon(origin, angle))
        non_venom = [p for p in row.get('targetsInCone', []) if not _is_ground_venom_point(p)]
        row['targetsInCone'] = non_venom+hits
        row['clearedByGeometry'] = len(row['targetsInCone'])
        row['inferredClearedCount'] = actual if actual is not None else len(hits)
        for p in hits:
            cleared[p['puddleID']] = row['timeMs']


def _replay_pose(unit, t):
    rows = unit.get('samples', [])
    if not rows:
        return None
    times = unit['_positionTimes']
    i = bisect_right(times, t)-1
    if i < 0 or t-times[i] > 1500:
        return None
    row = rows[i]
    x, y = row[1], row[2]
    if i+1 < len(rows) and times[i+1]-times[i] <= 1500:
        f = (t-times[i])/(times[i+1]-times[i] or 1)
        x, y = x+(rows[i+1][1]-x)*f, y+(rows[i+1][2]-y)*f
    fi = bisect_right(unit['_facingTimes'], t)-1
    face = unit.get('facingSamples', [])[fi] if fi >= 0 else None
    return {'x':x, 'y':y, 'facing':normalize_facing_radians(face[1]) if face and t-face[0] <= MANIFEST_FACING_MAX_AGE_MS else None}


def _build_manifest_replay(fight, mechanics, raw, players, actor_map):
    """Face-aware estimates, with observed spawns and aura/death lifetimes."""
    tuning = encounter_tuning(fight)
    watch_angle = tuning['manifestWatchHalfAngleDegrees']
    start, duration = int(fight['startTime']), int(fight['endTime'])-int(fight['startTime'])
    units = {u['actorID']:{**u, '_positionTimes':[r[0] for r in u['samples']],
                          '_facingTimes':[r[0] for r in u.get('facingSamples', [])]}
             for u in mechanics.get('combatReplay', {}).get('units', []) if u['kind'] == 'player'}
    grouped = defaultdict(list)
    for row in mechanics.get('manifestations', {}).get('fixations', []):
        m = row['manifest']
        grouped[(m['sourceID'], int(m.get('sourceInstance') or 0))].append(row)
    anchors = defaultdict(list)
    for e in raw.get('casts', []):
        key = (e.get('sourceID'), int(e.get('sourceInstance') or 0))
        if key in grouped and ability_id(e) == FIXATION and is_cast_complete(e):
            p = _npc_actor_point(e, e.get('sourceID'))
            if p:
                anchors[key].append((int(e['timestamp'])-start, p))
    ghosts = []
    for key, assignments in grouped.items():
        assignments.sort(key=lambda r:r['applyTimeMs'])
        begins = assignments[0]['applyTimeMs']
        ends = max(r.get('despawnTimeMs', r.get('removeTimeMs')) or duration for r in assignments)
        samples = sorted(anchors[key])
        known = [r for r in samples if r[0] <= begins]
        if not known:
            continue  # Never initialize a ghost with its future or player's position.
        x, y = known[-1][1]
        previous_anchor, last_move = known[-1][0], None
        trajectory = []
        for t in range(begins, min(ends, duration)+1, MANIFEST_REPLAY_STEP_MS):
            fresh = [a for a in samples if previous_anchor < a[0] <= t]
            if fresh:
                previous_anchor, (x, y) = fresh[-1]
            assignment = next((r for r in reversed(assignments) if r['applyTimeMs'] <= t and t < (r.get('removeTimeMs') or duration)), None)
            pid = assignment['playerID'] if assignment else None
            pose = _replay_pose(units.get(pid, {}), t)
            moving, known_facing = False, bool(pose and pose['facing'] is not None)
            if known_facing:
                dx, dy = x-pose['x'], y-pose['y']
                bearing = math.atan2(-dy, dx)
                watched = math.cos(bearing-pose['facing']) >= math.cos(math.radians(watch_angle))
                distance = math.hypot(dx, dy)
                moving = not watched and distance > 100 and t > max(begins,previous_anchor)
                if moving:
                    amount = min(distance-100, MANIFEST_REPLAY_SPEED_YARDS*100*MANIFEST_REPLAY_STEP_MS/1000)
                    x, y = x-dx/distance*amount, y-dy/distance*amount
                    last_move = t
            trajectory.append([t, round(x, 2), round(y, 2), pid, int(moving), int(known_facing), last_move])
        ghosts.append({'key':f'{key[0]}:{key[1]}', 'actorID':key[0], 'instance':key[1],
            'startTimeMs':begins, 'endTimeMs':ends, 'samples':trajectory,
            'endReason':next((r.get('despawnReason') for r in assignments if r.get('despawnTimeMs')==ends),None),
            'assignments':[{'playerID':r['playerID'], 'startTimeMs':r['applyTimeMs'],
                            'endTimeMs':r.get('removeTimeMs') or duration} for r in assignments],
            'positionEvidence':'observed-spawn-facing-estimate'})
    triggers = []
    for e in sorted(raw.get('debuffs', []), key=lambda e:int(e['timestamp'])):
        if ability_id(e) in MANIFEST_COLLISION_DEBUFF_IDS and event_type(e) == 'applydebuff':
            t = int(e['timestamp'])-start
            if not triggers or t-triggers[-1]['timeMs'] > 300:
                triggers.append({'timeMs':t, 'playerIDs':[]})
            if e.get('targetID') in players and e['targetID'] not in triggers[-1]['playerIDs']:
                triggers[-1]['playerIDs'].append(e['targetID'])
    for hit in triggers:
        t, movements = hit['timeMs'], []
        for ghost in ghosts:
            s = next((r for r in reversed(ghost['samples']) if r[0] <= t), None)
            if s and ghost['startTimeMs'] <= t < ghost['endTimeMs'] and s[3] in hit['playerIDs']:
                movements.append({'ghostKey':ghost['key'], 'playerID':s[3], 'moving':bool(s[4]),
                    'facingKnown':bool(s[5]), 'lastMovementTimeMs':s[6],
                    'estimatedPosition':{'x':s[1], 'y':s[2]}})
        movers = [m for m in movements if m['facingKnown'] and m['lastMovementTimeMs'] is not None and t-m['lastMovementTimeMs'] <= 1000]
        stationary = [m for m in movements if m['facingKnown'] and not m['moving']]
        separation = None
        if len(movements) == 2:
            a, b = (m['estimatedPosition'] for m in movements)
            separation = math.hypot(a['x']-b['x'], a['y']-b['y'])/100
        unique = (len(movers) == 1 and separation is not None and separation <= 5
                  and any(m['playerID'] != movers[0]['playerID'] for m in stationary)
                  and all(m['facingKnown'] for m in movements))
        hit.update(phase=phase_at(t, mechanics.get('phaseTimeline', [])),
                   movements=movements, estimatedSeparationYards=separation,
                   responsiblePlayerID=movers[0]['playerID'] if unique else None,
                   confidence='facing-inferred' if unique else 'insufficient-or-both-moving',
                   players=[player_ref(players, actor_map, pid) for pid in hit['playerIDs']],
                   responsiblePlayer=player_ref(players, actor_map, movers[0]['playerID']) if unique else None,
                   deaths=[player_ref(players, actor_map, e['targetID']) for e in raw.get('deaths', [])
                           if e.get('targetID') in hit['playerIDs'] and t <= int(e['timestamp'])-start <= t+6000
                           and e.get('killingAbilityGameID') in MANIFEST_COLLISION_DEBUFF_IDS])
        if unique:
            mover = next(g for g in ghosts if g['key'] == movers[0]['ghostKey'])
            other = next(m for m in stationary if m['playerID'] != movers[0]['playerID'])
            endpoint = other['estimatedPosition']
            if _constrain_manifest_endpoint(mover, t, (endpoint['x'], endpoint['y'])):
                hit['contactPosition'] = endpoint
                hit['contactEvidence'] = 'observed-resonance-constrained-estimate'
    clear_rows = sorted([*mechanics.get('soulSever', {}).get('rounds', []),
                         *mechanics.get('blightedSever', {}).get('rounds', [])], key=lambda r:r['timeMs'])
    for ghost in ghosts:
        if ghost.get('endReason') == 'fixated-target-death':
            continue  # A target's death is not evidence that a frontal cleared its ghost.
        clear = next((r for r in clear_rows if abs(r['timeMs']-ghost['endTimeMs']) <= 200), None)
        if not clear or not ghost['samples'] or not clear.get('origin') or clear.get('facingRadians') is None:
            continue
        s = ghost['samples'][-1]
        point = _closest_clear_point(clear, (s[1],s[2]))
        distance = math.hypot(point[0]-s[1],point[1]-s[2])/100
        adjusted = distance <= 8 and _constrain_manifest_endpoint(ghost, ghost['endTimeMs']-1, point)
        ghost['terminalConstraint'] = {'timeMs':clear['timeMs'], 'spellID':clear['spellID'],
             'correctionYards':round(distance,2), 'status':'constrained-estimate' if adjusted else 'unresolved',
             'hasObservedDespawnPosition':False}
    _exclude_unrecorded_manifest_contacts(ghosts,triggers)
    return {'ghosts':ghosts, 'resonanceCollisions':triggers,
            'stepMs':MANIFEST_REPLAY_STEP_MS, 'speedYardsPerSecond':MANIFEST_REPLAY_SPEED_YARDS,
            'watchHalfAngleDegrees':watch_angle, 'immediateRedGlow':tuning['manifestImmediateRedGlow'],
            'evidenceNote':'出生位置和凝视关系来自日志；后续轨迹按玩家面向估算。只有一只近期移动且另一只面对玩家停住时，标注推测移动方；缺少面向或双方移动不确定单人责任。'}


def _closest_clear_point(row, point):
    """Nearest point strictly inside the observed clearing cast's sector."""
    ox, oy = row['origin']['x'], row['origin']['y']
    dx, dy = point[0]-ox, point[1]-oy
    distance, angle = math.hypot(dx,dy), math.atan2(-dy,dx)
    face = row['facingRadians']
    delta = math.atan2(math.sin(angle-face),math.cos(angle-face))
    half = math.radians(row.get('coneHalfAngleDeg',CONE_HALF_ANGLE_DEG))
    radius = row.get('coneRadiusYards',CONE_RADIUS_YARDS)*100-25
    if abs(delta) < half and distance < radius:
        return point
    bearing = face+max(-half+.02,min(half-.02,delta))
    length = max(0,min(radius,distance*math.cos(angle-bearing)))
    return ox+math.cos(bearing)*length, oy-math.sin(bearing)*length


def _constrain_manifest_endpoint(ghost, time_ms, point):
    """Fit a confirmed contact/clear within prior moving segments only.

    Keep the observed spawn and watched (stationary) intervals intact. The
    result is explicitly constrained inference, never an observed coordinate.
    """
    rows = ghost['samples']
    end = bisect_right([s[0] for s in rows],time_ms)-1
    if end < 0:
        return False
    dx, dy = point[0]-rows[end][1], point[1]-rows[end][2]
    if math.hypot(dx,dy) < 1:
        return True
    moving = [i for i in range(1,end+1) if rows[i][4]][-30:]
    if not moving:
        return False
    count, eligible = 0, set(moving)
    for i in range(moving[0],len(rows)):
        if i in eligible:
            count += 1
        weight = min(1,count/len(moving))
        rows[i][1] = round(rows[i][1]+dx*weight,2)
        rows[i][2] = round(rows[i][2]+dy*weight,2)
    ghost['positionEvidence'] = 'observed-spawn-facing-and-clear-constrained-estimate'
    return True


def _exclude_unrecorded_manifest_contacts(ghosts, collisions):
    """Fit sparse facing paths to the observed absence of resonance.

    This is an offline positional constraint, not NPC avoidance behavior.
    Never alter observed spawns or attribute movement from this correction.
    """
    if not ghosts:
        return
    ticks = range(min(g['startTimeMs'] for g in ghosts),max(g['endTimeMs'] for g in ghosts),100)
    times = {g['key']:[s[0] for s in g['samples']] for g in ghosts}
    for t in ticks:
        active = [(g,bisect_right(times[g['key']],t)-1) for g in ghosts
                  if g['startTimeMs']+2000 <= t < g['endTimeMs']-100]
        for i,(a,ai) in enumerate(active):
            sa = a['samples'][ai]
            for b,bi in active[i+1:]:
                sb = b['samples'][bi]
                if not sa[5] or not sb[5] or sa[3] == sb[3]:
                    continue
                if any(e['timeMs']-150 <= t <= e['timeMs']+5000
                       and {sa[3],sb[3]} == set(e['playerIDs']) for e in collisions):
                    continue
                dx,dy = sa[1]-sb[1],sa[2]-sb[2]
                distance = math.hypot(dx,dy)
                if distance >= 150:
                    continue
                recent_a, recent_b = sa[6] or -1,sb[6] or -1
                mover,at,other = (a,ai,sb) if recent_a >= recent_b else (b,bi,sa)
                own = mover['samples'][at]
                vx,vy = own[1]-other[1],own[2]-other[2]
                length = math.hypot(vx,vy)
                if not length:
                    vx,vy,length = 1,0,1
                desired = (other[1]+vx/length*151,other[2]+vy/length*151)
                if _constrain_manifest_endpoint(mover,t,desired):
                    mover['contactExclusionCorrections'] = mover.get('contactExclusionCorrections',0)+1
                    mover['positionEvidence'] = 'observed-spawn-facing-clear-and-resonance-constrained-estimate'


def _apply_altar_boss_lifetimes(mechanics, actor_rows):
    replay = mechanics['combatReplay']
    zuljan = resolve_boss_actor_id(actor_rows, 257911, ("Zul'jan", "祖尔加"))
    revive = next((p['timeMs'] for p in mechanics.get('phaseTimeline', []) if p['key'] == 'intermission'), None)
    for row in replay['bosses']:
        row['portrait'] = "/boss_plugins/assets/Zul'jan.png" if row['actorID'] == zuljan else '/boss_plugins/assets/HexLord_Malacrass.png'
    if revive is not None and zuljan is not None:
        for row in [*replay['bosses'], *replay['units']]:
            if row['actorID'] == zuljan:
                row['states'] = sorted([*row['states'], [revive, 'alive']])


def _build_soulcoiler_replay(fight, mechanics, raw, players, actor_map):
    """Instance-local positions, health, shields and interrupted cast windows."""
    start, duration = int(fight['startTime']), int(fight['endTime'])-int(fight['startTime'])
    actors = {u['key']:{**u, 'casts':[], 'health':[], 'shield':[], 'teleports':[],
              'startTimeMs':u['samples'][0][0], 'icon':'/boss_plugins/assets/Spiteful_Soulcoiler.png'}
              for u in mechanics['combatReplay']['units']
              if u.get('gameID') == SOULCOILER_NPC_GAME_ID and u['samples']}
    by_key = {(a['actorID'], a['instance']):a for a in actors.values()}
    pending = {}
    cursed = set()
    rows = sorted(raw.get('replayEvents', []), key=lambda e:int(e['timestamp']))
    for e in rows:
        t, kind = int(e['timestamp'])-start, event_type(e)
        source = (e.get('sourceID'), int(e.get('sourceInstance') or 0))
        target = (e.get('targetID'), int(e.get('targetInstance') or 0))
        if source not in by_key and target not in by_key:
            continue
        if target in by_key and ability_id(e) == CURSE_OF_TONGUES_ID and 'debuff' in kind:
            applied = kind != 'removedebuff'
            changed = applied != (target in cursed)
            if applied:
                cursed.add(target)
            else:
                cursed.discard(target)
            cast = pending.get(target)
            if changed and cast and t < cast['endTimeMs']:
                previous = cast['progressSegments'][-1]
                progress = min(1,previous[1]+(t-previous[0])/previous[2])
                duration_ms = WAIL_CURSED_CAST_MS if applied else WAIL_CAST_MS
                cast['progressSegments'].append([t,progress,duration_ms])
                cast.update(durationMs=duration_ms,expectedEndTimeMs=t+(1-progress)*duration_ms,
                            endTimeMs=min(duration,t+(1-progress)*duration_ms))
        if kind == 'begincast' and source in by_key and ability_id(e) in WAIL_OF_TERROR_IDS:
            old = pending.get(source)
            if old:
                old.update(endTimeMs=t, outcome='unconfirmed')
            duration_ms = WAIL_CURSED_CAST_MS if source in cursed else WAIL_CAST_MS
            cast = {'startTimeMs':t, 'endTimeMs':min(duration,t+duration_ms),
                    'expectedEndTimeMs':t+duration_ms,'durationMs':duration_ms,
                    'progressSegments':[[t,0,duration_ms]],'spellID':ability_id(e),
                    'spellName':'恐惧哀嚎', 'outcome':'unconfirmed'}
            by_key[source]['casts'].append(cast)
            pending[source] = cast
        elif kind == 'interrupt' and target in by_key:
            cast = pending.pop(target, None)
            if cast and t <= cast['endTimeMs']:
                spell = int(ability_id(e) or 0)
                icon = next((f'/assets/spells/{spell}.{ext}' for ext in ('png','jpg')
                             if Path(__file__).resolve().parents[2].joinpath('assets','spells',f'{spell}.{ext}').is_file()), None)
                cast.update(endTimeMs=t, outcome='interrupted', interruptSpellID=spell,
                            interruptIcon=icon, interruptedBy=player_ref(players, actor_map, e.get('sourceID')))
        elif kind == 'cast' and source in by_key:
            if ability_id(e) == 1308011:
                by_key[source]['teleports'].append(t)
            cast = pending.get(source)
            if cast and ability_id(e) == cast['spellID']:
                cast.update(endTimeMs=t, outcome='completed')
                pending.pop(source, None)
        if target in by_key and ability_id(e) == SPIRIT_SHIELD and 'buff' in kind:
            amount = 0 if kind == 'removebuff' else int(e.get('stack') or (2 if kind == 'applybuff' else 1))
            by_key[target]['shield'].append([t,amount])
        for side, key in [('source',source),('target',target)]:
            if key not in by_key:
                continue
            resource = e.get(side+'Resources') or {}
            if str(e.get('resourceActor')) == ('1' if side == 'source' else '2'):
                resource = e
            if resource.get('hitPoints') is not None and resource.get('maxHitPoints'):
                by_key[key]['health'].append([t,resource['hitPoints'],resource['maxHitPoints']])
    for actor in actors.values():
        actor['endTimeMs'] = next((t for t,s in actor['states'] if s == 'dead'), duration)
    return {'actors':list(actors.values())}


def _build_altar_ground_replay(fight, mechanics, raw):
    start = int(fight['startTime'])
    duration = int(fight['endTime'])-start
    rounds, seen, purple_count, green_count = [],set(),0,0
    for e in sorted(raw.get('casts', []),key=lambda e:int(e['timestamp'])):
        spell = ability_id(e)
        if spell not in {ALTAR_FANGS_ID,ALTAR_DEFILEMENT_ID} or not is_cast_complete(e):
            continue
        t = int(e['timestamp'])-start
        if (spell,t,e.get('sourceID')) in seen:
            continue
        seen.add((spell,t,e.get('sourceID')))
        purple = spell == ALTAR_DEFILEMENT_ID
        if purple:
            purple_count += 1
        else:
            green_count += 1
        ordinal = purple_count if purple else green_count
        rounds.append({'startTimeMs':t,'channelEndTimeMs':min(duration,t+ALTAR_CHANNEL_MS),
            'recedeStartTimeMs':t+ALTAR_CHANNEL_MS+ALTAR_GROUND_HOLD_MS,
            'endTimeMs':min(duration,t+ALTAR_CHANNEL_MS+ALTAR_GROUND_HOLD_MS+ALTAR_GROUND_RECEDE_MS),
            'spellID':spell,'casterID':e.get('sourceID'),'kind':'purple' if purple else 'green',
            'ordinal':ordinal,
            'peakRadiusYards':ALTAR_GROUND_PEAK_RADII[min(ordinal,len(ALTAR_GROUND_PEAK_RADII))-1],
            'fullCoverage':purple and purple_count>=4})
    replay = mechanics['combatReplay']
    for row in rounds:
        boss = next((b for b in replay['bosses'] if b['actorID']==row['casterID']),None)
        if boss is not None:
            boss['casts'].append({'startTimeMs':row['startTimeMs'],'endTimeMs':row['channelEndTimeMs'],
                'spellID':row['spellID'],'spellName':'盘卷祭坛亵渎' if row['kind']=='purple' else '盘卷祭坛之牙',
                'phase':'channel','outcome':'completed'})
            boss['casts'].sort(key=lambda c:c['startTimeMs'])
    return {'rounds':rounds,'sideCenters':[{'x':-5500,'y':115800},{'x':5500,'y':115800}],
            'floorBounds':{'minX':-5500,'maxX':5500,'minY':110300,'maxY':121300},
            'positionEvidence':'fixed-mouths-and-estimated-radius',
            'holdDurationMs':ALTAR_GROUND_HOLD_MS,'recedeDurationMs':ALTAR_GROUND_RECEDE_MS}


def _apply_altar_nightfall_replay(fight, mechanics, raw, players, actor_map):
    """Boss-owned fixed cast length with actual completion/interrupt boundaries."""
    nightfall_ms = encounter_tuning(fight)['nightfallCastMs']
    start, duration = int(fight['startTime']), int(fight['endTime'])-int(fight['startTime'])
    bosses = {b['actorID']:b for b in mechanics['combatReplay']['bosses']}
    for b in bosses.values():
        b['casts'] = [c for c in b['casts'] if c['spellID'] not in NIGHTFALL_INTERRUPTED_SPELLS]
    pending, seen = {}, set()
    rows = [e for e in raw.get('replayEvents', [])
            if (e.get('sourceID') in bosses and
                (event_type(e) == 'begincast' or
                 event_type(e) == 'cast' and ability_id(e) in NIGHTFALL_INTERRUPTED_SPELLS))
            or (e.get('targetID') in bosses and event_type(e) == 'interrupt' and _is_nightfall_interrupt(e))]
    for e in sorted(rows,key=lambda e:int(e['timestamp'])):
        t, kind, source, spell = int(e['timestamp'])-start, event_type(e), e.get('sourceID'), ability_id(e)
        signature = (t,kind,source,e.get('targetID'),spell,e.get('extraAbilityGameID'))
        if signature in seen:
            continue
        seen.add(signature)
        if kind == 'begincast' and source in bosses:
            old = pending.pop(source,None)
            if old and t < old['endTimeMs']:
                old['endTimeMs'] = t
            if spell in NIGHTFALL_INTERRUPTED_SPELLS:
                cast = {'startTimeMs':t,'endTimeMs':min(duration,t+nightfall_ms),
                        'expectedEndTimeMs':t+nightfall_ms,
                        'durationMs':nightfall_ms,'spellID':spell,
                        'spellName':'永恒夜幕','outcome':'unconfirmed','interruptFeedbackMs':650}
                bosses[source]['casts'].append(cast)
                pending[source] = cast
        elif kind == 'interrupt' and _is_nightfall_interrupt(e):
            cast = pending.get(e.get('targetID'))
            if cast and cast['startTimeMs'] <= t <= cast['endTimeMs']:
                sid = ability_id(e)
                icon = next((f'/assets/spells/{sid}.{ext}' for ext in ('png','jpg')
                             if Path(__file__).resolve().parents[2].joinpath('assets','spells',f'{sid}.{ext}').is_file()), None)
                cast.update(endTimeMs=t,outcome='interrupted',interruptSpellID=sid,
                            interruptIcon=icon,interruptedBy=player_ref(players,actor_map,source))
                pending.pop(e.get('targetID'),None)
        elif kind == 'cast' and spell in NIGHTFALL_INTERRUPTED_SPELLS:
            cast = pending.get(source)
            if cast and cast['startTimeMs'] <= t <= cast['endTimeMs']:
                cast.update(endTimeMs=t,outcome='completed')
                pending.pop(source,None)
    for b in bosses.values():
        b['casts'].sort(key=lambda c:c['startTimeMs'])


def _apply_altar_soulbind_replay(fight, mechanics, raw):
    """35-second Malacrass channel, anchored to his self aura/cast."""
    start, duration = int(fight['startTime']), int(fight['endTime'])-int(fight['startTime'])
    bosses = {b['actorID']:b for b in mechanics['combatReplay']['bosses'] if b.get('gameID')==259854}
    rows = sorted([*(raw.get('replayEvents') or []),*(raw.get('casts') or []),*(raw.get('enemyBuffs') or [])],
                  key=lambda e:int(e['timestamp']))
    channels, seen = [], {}
    for event in rows:
        source, target, kind, spell = event.get('sourceID'), event.get('targetID'), event_type(event), ability_id(event)
        if source not in bosses or spell!=INTERMISSION_SOULBIND:
            continue
        if not (kind=='cast' or kind=='applybuff' and target==source):
            continue
        ts = int(event['timestamp'])
        if source in seen and ts-seen[source]<500:
            continue
        seen[source] = ts
        stops = [int(e['timestamp']) for e in rows if int(e['timestamp'])>ts and
                 ((event_type(e)=='removebuff' and ability_id(e)==INTERMISSION_SOULBIND and e.get('targetID')==source)
                  or (event_type(e)=='applybuff' and ability_id(e)==P3_SOULBOUND and e.get('targetID')==source))]
        actual = min(stops,default=None)
        death = min((int(e['timestamp']) for e in raw.get('enemyDeaths') or []
                     if e.get('targetID')==source and int(e['timestamp'])>=ts),default=None)
        end = min(actual if actual is not None else ts+INTERMISSION_MS,
                  death if death is not None else start+duration,start+duration)
        if end<=ts:
            continue
        outcome = 'completed' if actual is not None and end>=ts+INTERMISSION_MS-250 else 'cancelled' if end<ts+INTERMISSION_MS else 'unconfirmed'
        cast = {'startTimeMs':ts-start,'endTimeMs':end-start,'expectedEndTimeMs':ts-start+INTERMISSION_MS,
                'durationMs':INTERMISSION_MS,'spellID':INTERMISSION_SOULBIND,'spellName':'灵魂绑定',
                'phase':'channel','outcome':outcome,'evidence':'self-aura' if kind=='applybuff' else 'observed-cast'}
        channels.append({'casterID':source,**cast})
    for actor, boss in bosses.items():
        boss['casts'] = [c for c in boss['casts'] if c['spellID']!=INTERMISSION_SOULBIND]
        boss['casts'].extend({k:v for k,v in c.items() if k!='casterID'} for c in channels if c['casterID']==actor)
        boss['casts'].sort(key=lambda c:c['startTimeMs'])
    return {'channels':channels,'durationMs':INTERMISSION_MS}


# Comparison rows use the same event signals for historical and current logs.
# These are encounter activity/aura boundaries, not the 1-HP thresholds used
# independently by the guild hold/adjudication checks.
GUILD_COMPARISON_PHASE_SIGNALS = (("p2", 1288624), ("intermission", 1304028), ("p3", 1289798))
GUILD_COMPARISON_SPELLS = (
    ("sever", "撕裂", {1299684}, {"p1"}),
    ("guillotine", "处斩", {1283489}, {"p1"}),
    ("cackle", "精魂狂笑", {1286441}, {"p2", "p3"}),
    ("soul", "灵魂裂劈", {1286620}, {"p2"}),
    ("gloom", "幽暗炸弹", set(GLOOMBOMB_CAST_IDS), {"p2"}),
    ("night", "永恒夜幕", {ETERNAL_NIGHTFALL}, {"p2", "p3"}),
    ("bind", "灵魂绑定", {INTERMISSION_SOULBIND}, {"intermission"}),
    ("defile", "盘卷祭坛亵渎", {1298381}, {"p3"}),
    ("grim", "冷酷处斩", {1299266, 1299267}, {"p3"}),
)


def build_timeline_comparison_evidence(fight, casts, enemy_buffs):
    """One extraction path for both comparison rows; never infer missing casts.

    Icons mark cast starts (begincast when available, otherwise instant cast).
    1299266 is the start signal for 1299267, rather than a second Guillotine.
    Nightfall needs only its observed begincast; an interrupt is not required
    to show that the boss started it. Soulbinding spans the whole intermission.
    """
    start, end = int(fight["startTime"]), int(fight["endTime"])
    duration = end-start
    casts = sorted((e for e in casts if start <= int(e.get("timestamp", -1)) <= end), key=lambda e: e["timestamp"])
    buffs = [e for e in enemy_buffs if start <= int(e.get("timestamp", -1)) <= end]
    markers = [{"key": "p1", "timeMs": 0, "signal": "fight-start"}]
    for key, sid in GUILD_COMPARISON_PHASE_SIGNALS:
        candidates = [e for e in buffs if ability_id(e) == sid and event_type(e) == "applybuff"]
        if not candidates:
            candidates = [e for e in casts if ability_id(e) == sid and event_type(e) == "cast"]
        if candidates:
            first = min(candidates, key=lambda e: e["timestamp"])
            markers.append({"key": key, "timeMs": int(first["timestamp"])-start,
                            "spellID": sid, "signal": event_type(first)})
    markers.sort(key=lambda m: m["timeMs"])
    by_phase = {m["key"]: m["timeMs"] for m in markers}
    events = []
    for key, label, ids, allowed in GUILD_COMPARISON_SPELLS:
        if key == "bind":
            if "intermission" in by_phase:
                events.append({"key": key, "label": label, "spellID": INTERMISSION_SOULBIND,
                    "timeMs": by_phase["intermission"], "endTimeMs": by_phase.get("p3", duration),
                    "phase": "intermission", "sourceType": "phase"})
            continue
        rows = [e for e in casts if ability_id(e) in ids]
        begins = [e for e in rows if event_type(e) == "begincast"]
        onsets = list(begins)
        if key == "grim":
            onsets += [e for e in rows if ability_id(e) == 1299266 and event_type(e) == "cast"]
        unique, last = [], {}
        for e in sorted(onsets, key=lambda e: e["timestamp"]):
            source = e.get("sourceID")
            if source not in last or int(e["timestamp"])-last[source] > 300:
                unique.append(e)
                last[source] = int(e["timestamp"])
        selected, consumed = list(unique), set()
        for e in rows:
            if event_type(e) != "cast" or (key == "grim" and ability_id(e) == 1299266):
                continue
            candidates = [(i, b) for i, b in enumerate(unique) if i not in consumed and b.get("sourceID") == e.get("sourceID")
                          and 0 <= int(e["timestamp"])-int(b["timestamp"]) <= 30000]
            if candidates:
                consumed.add(max(candidates, key=lambda pair: pair[1]["timestamp"])[0])
                continue
            selected.append(e)
        seen = {}
        for e in sorted(selected, key=lambda e: e["timestamp"]):
            t = int(e["timestamp"])-start
            source = e.get("sourceID")
            if source in seen and t-seen[source] <= 300:
                continue
            seen[source] = t
            phase = next(m["key"] for m in reversed(markers) if m["timeMs"] <= t)
            if phase in allowed:
                events.append({"key": key, "label": label, "spellID": ability_id(e), "timeMs": t,
                    "endTimeMs": t, "phase": phase, "sourceType": event_type(e)})
    events.sort(key=lambda e: e["timeMs"])
    return {"ruleVersion": "boss-starts-phase-auras-v1", "phaseTimeline": markers, "events": events,
            "counts": {key: sum(e["key"] == key for e in events) for key, _, _, _ in GUILD_COMPARISON_SPELLS}}


# Guild assignments remain Boss-owned; ability identities come from the shared catalog.
AVALON_BURST_ROWS = [
    ("Breezeluck", "death-knight.army-of-the-dead", [0,180,395,607]),
    ("Breezeluck", "death-knight.apocalypse", [0,180,246,331,395,469,565,607]),
    ("飞天小喷菇", "demon-hunter.void-metamorphosis", [246,395,469,565]),
    ("小楚唯", "druid.incarnation-balance", [0,[180,200],331,395,469,565]),
    ("贪睡熊熊", "druid.incarnation-balance", [0,[180,200],331,395,469,565]),
    ("若叶睦", "evoker.breath-of-eons", [0,180,270,395,469,565]),
    ("若叶睦", "evoker.time-skip", [9,188,549]),
    ("Superhunter", "hunter.trueshot", [0,120,246,395,565]),
    ("Superhunter", "hunter.volley", [469]),
    ("三坑不二", "mage.ray-of-frost", [0,120,180,246,395,469,517]),
    ("小心胡大海", "mage.arcane-surge", [0,90,180,270,395]),
    ("劉浩然", "monk.invoke-xuen", [0,90,180,270,395,517,607]),
    ("劉浩然", "monk.zenith", [0,90,180,270,395,469,517,607]),
    ("残夜将歇", "rogue.shadow-blades", [0,90,180,270,395,565]),
    ("残夜将歇", "rogue.goremaws-bite", [0,90,180,270,395,565]),
    ("叮咚好烦", "warlock.summon-darkglare", [0,120,246,395,517]),
    ("茶喵不吃糖", "warlock.summon-darkglare", [0,120,246,395,517]),
    ("染小战", "warrior.avatar", [0,180,246,331,395,565]),
    ("雷横", "warrior.avatar", [0,180,246,331,395,565]),
    ("染小战", "warrior.warbreaker", [469]),
    ("雷横", "warrior.warbreaker", [469]),
    ("小楚唯", "item.offensive-trinket", [0,[180,200],395,565]),
    ("贪睡熊熊", "item.offensive-trinket", [0,[180,200],395,565]),
]
AVALON_PLAN_NOTES = [
    "截图的巨神按确认映射天神下凡；战士按实际施法核对，不推断愤怒掌控冷却。",
    "饰品按已确认的主动技能核对，可通过自定义安排逐人指定。",
    "增辉时间跳跃安排为 0:09、3:08、9:09；亘古吐息与跳跃分别核对。",
    "默认法师安排按本场专精选择奥术涌动或冰霜射线，保留该玩家原定时间点；自定义明确指定的技能不自动替换。",
    "两名德鲁伊按本场专精核对，治疗场次不计 DPS 爆发安排。持续条取自身增益或施法者在敌方目标上的减益，不用飞行光环代替。",
]


def burst_plan(options):
    import json
    custom = options.get("burstPlan", "")
    try:
        rows = json.loads(custom) if custom else [
            {"player": p, "ability": a, "times": times} for p, a, times in AVALON_BURST_ROWS]
        if not isinstance(rows, list) or len(rows) > 200:
            raise ValueError("安排必须为不超过 200 项的数组")
        for row in rows:
            if not isinstance(row, dict) or not row.get("player") or not (row.get("ability") or row.get("spellIDs")):
                raise ValueError("每项需要 player 和 ability（或自定义 spellIDs）")
            if "spellIDs" in row and (not isinstance(row["spellIDs"], list) or not 1 <= len(row["spellIDs"]) <= 20
                    or any(isinstance(v, bool) or not isinstance(v, int) or not 0 < v < 100000000 for v in row["spellIDs"])):
                raise ValueError("spellIDs 必须为 1–20 个有效整数技能 ID")
            if not isinstance(row.get("times"), list) or len(row["times"]) > 100:
                raise ValueError("times 必须为不超过 100 项的数组")
            for time in row["times"]:
                values = time if isinstance(time, list) else [time]
                if len(values) not in (1, 2) or any(isinstance(v, bool) or not isinstance(v, (int, float))
                        or not math.isfinite(v) or not 0 <= v <= 3600 for v in values):
                    raise ValueError("时间必须为 0–3600 秒或 [开始,结束]")
                if len(values) == 2 and values[0] > values[1]:
                    raise ValueError("时间区间开始不得晚于结束")
            duration = row.get("durationSeconds")
            if duration is not None and (not isinstance(duration, (int, float)) or not math.isfinite(duration) or not 0 < duration <= 600):
                raise ValueError("durationSeconds 必须为 0–600 秒")
            tolerance = row.get("toleranceSeconds")
            if tolerance is not None and (isinstance(tolerance, bool) or not isinstance(tolerance, (int, float))
                    or not math.isfinite(tolerance) or not 0 <= tolerance <= 30):
                raise ValueError("toleranceSeconds 必须为 0–30 秒")
        return rows
    except (ValueError, TypeError) as error:
        raise ValueError(f"M7 爆发安排格式错误：{error}") from error


def _guild_timeline_enabled(raw, options):
    return options["guildTimelineEnabled"] and resolve_profile(raw.get("reportGuild"), options)["key"] == "avalon"


def _resource_for_actor(event, actor_id):
    for side, number in (("source", "1"), ("target", "2")):
        if event.get(side + "ID") != actor_id:
            continue
        resource = event.get(side + "Resources") or {}
        if str(event.get("resourceActor")) == number:
            resource = event
        if resource.get("hitPoints") is not None and resource.get("maxHitPoints", 0) > 0:
            return resource
    return None


def _guild_phase_control(fight, markers, raw, actor_rows, options):
    start = int(fight["startTime"])
    times = {r["key"]: int(r["timeMs"]) for r in markers}
    streams = raw.get("guildBossDamage", []) + raw.get("replayEvents", []) + raw.get("enemyDeaths", [])
    phases = []
    for phase, next_phase, game_id, planned in (
        ("p1", "p2", 257911, options["p1EarliestEndSeconds"]*1000),
        ("p2", "intermission", 259854, times.get("p2", 0)+options["p2LastBladeOffsetSeconds"]*1000),
    ):
        boss_id = resolve_boss_actor_id(actor_rows, game_id, ())
        begin, end = times.get(phase), times.get(next_phase)
        row = {"phase": phase, "bossID": boss_id, "startTimeMs": begin, "phaseEndTimeMs": end,
               "earliestEndTimeMs": round(planned), "status": "unreached", "thresholds": {}}
        if begin is None or boss_id is None:
            phases.append(row)
            continue
        limit = end if end is not None else int(fight["endTime"])-start
        health = {}
        one_hp, deaths = [], []
        for event in streams:
            t = int(event.get("timestamp") or 0)-start
            if not begin <= t <= limit:
                continue
            resource = _resource_for_actor(event, boss_id)
            if resource:
                health[t] = float(resource["hitPoints"])/float(resource["maxHitPoints"])*100
                if resource["hitPoints"] <= 1:
                    one_hp.append(t)
            if event_type(event) == "death" and event.get("targetID") == boss_id:
                deaths.append(t)
        # 1-HP samples and enemy deaths locate the actual transition trigger.
        trigger = min(one_hp+deaths, default=None)
        observed_end = trigger if trigger is not None else end
        row.update(triggerTimeMs=trigger, endTimeMs=observed_end,
                   endEvidence="boss-1hp-or-death" if trigger is not None else "phase-transition" if end is not None else "fight-truncated")
        blade_ids = SEVER_IDS if phase == "p1" else SOUL_SEVER_IDS
        blades = sorted({int(e["timestamp"])-start for e in raw.get("casts", [])
                         if ability_id(e) in blade_ids and is_cast_complete(e)
                         and begin <= int(e["timestamp"])-start <= limit})
        row["bladeTimesMs"] = blades
        if phase == "p2" and blades:
            # P2's first frontal can be delayed by the preceding transition.
            # Preserve the reference fifth-minus-first spacing rather than
            # allowing a delayed fifth frontal to be skipped by wall-clock time.
            row["bladeDriftMs"] = blades[0]-(begin+32772)
            planned += row["bladeDriftMs"]
        blade_target = 162043 if phase == "p1" else planned
        required_blade = next((t for t in blades if t >= blade_target-1000), None)
        deadline = max(planned, required_blade or planned)
        row["earliestEndTimeMs"] = round(deadline)
        row["requiredBladeTimeMs"] = required_blade
        row["status"] = "early" if observed_end is not None and observed_end < deadline else "on-time" if observed_end is not None else "in-progress"
        if row["status"] == "on-time" and required_blade is None:
            row["status"] = "unknown"
            row["reason"] = "到达约定时间，但缺少最后一刀完成事件，不判漏爆发"
        if phase == "p1":
            march = min((int(e["timestamp"])-start for e in raw.get("casts", [])
                         if ability_id(e) in DREADMARCH_CAST_IDS and event_type(e) == "begincast"
                         and end is not None and end <= int(e["timestamp"])-start <= int(fight["endTime"])-start), default=None)
            earliest_march = round(options["firstDreadmarchEarliestSeconds"]*1000)
            row.update(firstDreadmarchTimeMs=march, firstDreadmarchEarliestTimeMs=earliest_march)
            reasons = []
            if observed_end is not None and observed_end < deadline:
                reasons.append("P1 在最早结束时间 " + fmt_ms(deadline) + " 前结束")
            if march is not None and march < earliest_march:
                row["status"] = "early"
                reasons.append("首次恐惧行军 " + fmt_ms(march) + " 开始读条，早于 " + fmt_ms(earliest_march))
            elif march is None and row["status"] == "on-time":
                row["status"] = "unknown"
                reasons.append("尚无首次恐惧行军读条记录，暂不判漏爆发")
            if reasons:
                row["reason"] = "；".join(reasons)
        samples = sorted(health.items())
        row["thresholdWindows"] = {}
        for threshold in range(1, 11):
            hold_begin = next((t for t, hp in samples if hp < threshold), None)
            hold_until = round(options["p1HoldUntilSeconds"]*1000) if phase == "p1" else None
            if phase == "p1":
                row["thresholdWindows"][str(threshold)] = {
                    "startTimeMs": hold_begin if hold_begin is not None and hold_begin < hold_until else None,
                    "endTimeMs": hold_until,
                    "evidenceEndTimeMs": min(hold_until, observed_end if observed_end is not None else limit),
                    "endExclusive": True,
                }
            # Use only the causal last HP sample, with a bounded sampling age.
            cast_rows, damage_rows = [], []
            for key, target, kinds in (("guildPlayerCasts", cast_rows, {"cast"}), ("guildBossDamage", damage_rows, {"damage"})):
                for event in raw.get(key, []):
                    t = int(event.get("timestamp") or 0)-start
                    if event.get("targetID") != boss_id or event_type(event) not in kinds or not begin <= t <= limit:
                        continue
                    if phase == "p1":
                        if hold_begin is not None and hold_begin <= t < hold_until and (observed_end is None or t <= observed_end):
                            target.append(event)
                        continue
                    resource = _resource_for_actor(event, boss_id)
                    index = bisect_right(samples, (t, float("inf")))-1
                    hp = float(resource["hitPoints"])/float(resource["maxHitPoints"])*100 if resource else (
                        samples[index][1] if index >= 0 and t-samples[index][0] <= 3000 else None)
                    if hp is not None and hp < threshold and (observed_end is None or t <= observed_end):
                        target.append(event)
            row["thresholds"][str(threshold)] = {"casts": cast_rows, "damage": damage_rows}
        row["healthSampleCount"] = len(samples)
        phases.append(row)
    return phases


def _burst_aura_intervals(events, actor, ids, start, end, *, target="self"):
    active, intervals = {}, []
    def append(key, begin, finish, truncated=False):
        if finish <= begin:
            return
        row = {"startTimeMs": begin, "endTimeMs": finish,
               "evidence": ("enemy-debuff" if target == "enemy" else "aura")+("-truncated" if truncated else "")}
        if target == "enemy":
            row.update(targetID=key[0], targetInstance=key[1], sourceID=actor, auraSpellIDs=[key[2]])
        intervals.append(row)
    for event in sorted(events, key=lambda e: int(e.get("timestamp") or 0)):
        if ability_id(event) not in ids:
            continue
        if target == "enemy":
            if event.get("sourceID") != actor or event.get("targetID") in {None, -1, actor}:
                continue
            applies, removes = {"applydebuff", "refreshdebuff", "applydebuffstack"}, {"removedebuff"}
        else:
            if event.get("targetID") != actor:
                continue
            applies, removes = {"applybuff", "refreshbuff", "applybuffstack"}, {"removebuff"}
        t = max(0, min(end, int(event["timestamp"])-start))
        key = (event.get("targetID"), event.get("targetInstance") or 0, ability_id(event))
        kind = event_type(event)
        if kind in applies:
            active.setdefault(key, t)
        elif kind in removes and key in active:
            append(key, active.pop(key), t)
    for key, begin in active.items():
        append(key, begin, end, True)
    # Some effects log multiple aura IDs on the same target. Union overlapping
    # aliases, keeping separate enemies and spawn instances independent.
    merged = []
    for row in sorted(intervals, key=lambda r: (r.get("targetID", actor), r.get("targetInstance", 0), r["startTimeMs"])):
        previous = merged[-1] if merged else None
        if (previous and previous.get("targetID") == row.get("targetID")
                and previous.get("targetInstance", 0) == row.get("targetInstance", 0)
                and row["startTimeMs"] <= previous["endTimeMs"]):
            previous["endTimeMs"] = max(previous["endTimeMs"], row["endTimeMs"])
            if target == "enemy":
                previous["auraSpellIDs"] = sorted(set(previous["auraSpellIDs"]+row["auraSpellIDs"]))
            if row["evidence"].endswith("-truncated"):
                previous["evidence"] = row["evidence"]
        else:
            merged.append(row)
    return sorted(merged, key=lambda r: r["startTimeMs"])


def build_guild_icon_timelines(timelines, raw, players, actor_map, fight):
    """Presentation evidence follows configured assignments, never all catalog spells."""
    catalog = {a["key"]: a for a in load_player_ability_catalog()["abilities"]}
    start, duration = int(fight["startTime"]), int(fight["endTime"])-int(fight["startTime"])
    result = []
    for row in timelines:
        key = row["ability"]
        if key.startswith("item."):
            continue
        ability = catalog.get(key, {})
        ids = ability.get("ids") or row.get("spellIDs", [])
        category = "major-burst" if key == "mage.ray-of-frost" else ability.get("category", "major-burst")
        windows = []
        if category == "major-burst":
            for check in row.get("windows", []):
                lo, hi = check["plannedStartTimeMs"], check["plannedEndTimeMs"]
                tolerance = max(0, check["endTimeMs"]-hi-check.get("phaseShiftMs", 0))
                windows.append({"timeMs": lo, "endTimeMs": hi,
                                "windowStartMs": max(0, lo-tolerance), "windowEndMs": hi+tolerance})
        result.append({**row, "category": category, "spellIDs": ids, "plannedWindows": windows,
                       "windows": []})
    item_ids = catalog.get("item.offensive-trinket", {}).get("ids", [])
    item_labels = {1297761: "乌拉特克的烈毒之心", 1250533: "货运者水壶",
                   1293316: "强化毒液", 1295885: "妖术领主的厄运神像"}
    for pid in players:
        for sid in item_ids:
            casts = sorted({int(e["timestamp"])-start for e in raw.get("guildPlayerCasts", [])
                            if event_type(e) == "cast" and e.get("sourceID") == pid and ability_id(e) == sid})
            if not casts:
                continue
            result.append({**player_ref(players, actor_map, pid), "ability": "item."+str(sid),
                "label": item_labels.get(sid, "主动饰品"), "spellIDs": [sid], "category": "trinket",
                "casts": casts, "intervals": _burst_aura_intervals(raw.get("guildPlayerBuffs", []), pid, {sid}, start, duration),
                "plannedWindows": [], "windows": [], "effectKind": "self-buff"})
    return result


GUILD_PLANNED_PHASE_STARTS = {"p1": 0, "p2": 180000, "intermission": 395000, "p3": 430000}


def guild_phase_timings(markers, controls):
    by_phase = {row["phase"]: row for row in controls}
    result = []
    for marker in markers:
        key = marker["key"]
        if key not in GUILD_PLANNED_PHASE_STARTS:
            continue
        control = by_phase.get(key, {})
        finish = control.get("endTimeMs")
        march = control.get("firstDreadmarchTimeMs")
        result.append({"phase": key, "startTimeMs": marker["timeMs"],
                       "plannedStartTimeMs": GUILD_PLANNED_PHASE_STARTS[key],
                       "startAdvanceMs": max(0, GUILD_PLANNED_PHASE_STARTS[key]-marker["timeMs"]),
                       "endAdvanceMs": max(0, control["earliestEndTimeMs"]-finish) if finish is not None else 0,
                       "firstDreadmarchAdvanceMs": max(0, control["firstDreadmarchEarliestTimeMs"]-march) if march is not None else 0})
    return result


def analyze_guild_timeline(fight, markers, raw, actor_rows, actor_map, players, options):
    profile = resolve_profile(raw.get("reportGuild"), options)
    result = {"enabled": False, "analysisProfile": profile}
    if not _guild_timeline_enabled(raw, options) or int(fight.get("difficulty") or 0) != 5:
        return {**result, "reason": "仅对已启用专属检查的阿瓦隆史诗日志执行"}
    start, duration = int(fight["startTime"]), int(fight["endTime"])-int(fight["startTime"])
    phases = _guild_phase_control(fight, markers, raw, actor_rows, options)
    owners = {a["id"]: a.get("petOwner") for a in actor_rows if a.get("petOwner") is not None}
    def owner(actor):
        visited = set()
        while actor in owners and actor not in visited:
            visited.add(actor)
            actor = owners[actor]
        return actor
    for phase in phases:
        for threshold, evidence in phase["thresholds"].items():
            totals = {pid: {**player_ref(players, actor_map, pid), "castCount": 0, "damage": 0,
                           "petDamage": 0, "casts": []} for pid in players}
            for event in evidence["casts"]:
                pid = event.get("sourceID")
                if pid not in players:  # Pets cannot increment a player's cast count.
                    continue
                row = totals[pid]
                row["castCount"] += 1
                row["casts"].append({"timeMs": int(event["timestamp"])-start, "spellID": ability_id(event)})
            for event in evidence["damage"]:
                source = event.get("sourceID")
                pid = owner(source)
                if pid not in players:
                    continue
                amount = max(0, float(event.get("amount") or 0)-float(event.get("overkill") or 0))
                totals[pid]["damage"] += amount
                if source != pid:
                    totals[pid]["petDamage"] += amount
            phase["thresholds"][threshold] = sorted(
                [r for r in totals.values() if r["castCount"] or r["damage"]],
                key=lambda r: (-r["castCount"], -r["damage"]))
    early = any(p["status"] == "early" for p in phases)
    uncertain = phases[0]["status"] not in {"on-time", "early"} or any(p["status"] == "unknown" for p in phases)
    skip_reason = "前序阶段时间轴提前，跳过爆发缺失计数" if early else "前序阶段结束、末轮刀或首次恐惧行军读条尚未确认，不判漏爆发" if uncertain else None
    catalog = {a["key"]: a for a in load_player_ability_catalog()["abilities"]}
    cast_index = defaultdict(list)
    for event in raw.get("guildPlayerCasts", []):
        if event_type(event) == "cast" and event.get("sourceID") in players:
            cast_index[(event["sourceID"], ability_id(event))].append(int(event["timestamp"])-start)
    checks, unresolved, timelines = [], [], []
    effective_plan = [dict(row) for row in burst_plan(options)]
    tolerance = options["burstWindowSeconds"]*1000
    phase_times = {p["key"]: p["timeMs"] for p in markers}
    # The screenshot is an absolute plan with P2 starting at 3:00. Later P2
    # windows shift with the actual P2 start; early transitions skip all counts.
    for assignment in effective_plan:
        name = str(assignment["player"])
        key = assignment.get("ability") or "custom:"+"/".join(map(str, assignment["spellIDs"]))
        matches = [pid for pid, p in players.items() if str(pid) == name or p.get("name") == name
                   or p.get("name", "").lstrip("、丶` ") == name]
        ability = ({"ids": assignment["spellIDs"], "nameZh": assignment.get("label") or key}
                   if assignment.get("spellIDs") else catalog.get(key))
        if len(matches) != 1 or not ability:
            unresolved.append({"player": name, "ability": key, "reason": "角色未唯一匹配本场阵容" if len(matches) != 1 else "技能尚未验证"})
            continue
        pid, ids = matches[0], set(ability["ids"])
        localization = players[pid].get("localization") or {}
        class_name = (localization.get("class") or {}).get("enUS")
        spec_name = (localization.get("spec") or {}).get("enUS")
        if not options.get("burstPlan") and class_name == "Druid" and spec_name == "Restoration":
            unresolved.append({"player": name, "ability": key, "reason": "本场为治疗专精，不计 DPS 爆发安排"})
            continue
        if (not options.get("burstPlan") and class_name == "Mage"
                and key in {"mage.arcane-surge", "mage.ray-of-frost"}
                and spec_name in {"Arcane", "Frost"}):
            selected = {"Arcane": "mage.arcane-surge", "Frost": "mage.ray-of-frost"}[spec_name]
            assignment["configuredAbility"] = key
            key, ability = selected, catalog[selected]
            assignment.update(ability=key, label=ability["nameZh"], spec=spec_name)
            ids = set(ability["ids"])
        normalize = lambda v: "".join(c for c in str(v).lower() if c.isalnum())
        if (class_name and ability.get("class", "Any") != "Any" and normalize(class_name) != normalize(ability["class"])) or (
                spec_name and ability.get("specs") and spec_name not in ability["specs"]):
            unresolved.append({"player": name, "ability": key, "reason": "本场职业/专精与安排不匹配，未计数"})
            continue
        actual = sorted({t for sid in ids for t in cast_index[(pid, sid)]})
        row_tolerance = assignment.get("toleranceSeconds", 3 if key == "evoker.time-skip" else tolerance/1000)*1000
        used = set()
        effect_kind = ability.get("effectKind", "self-buff")
        aura_target = ability.get("auraTarget", "self")
        aura_ids = set(ability.get("auraIds", ability["ids"]))
        aura = [] if effect_kind == "cast-only" else _burst_aura_intervals(
            raw.get("guildEnemyDebuffs" if aura_target == "enemy" else "guildPlayerBuffs", []),
            pid, aura_ids, start, duration, target=aura_target)
        for interval in aura:
            if interval.get("targetID") is not None:
                interval["target"] = actor_map.get(interval["targetID"]) or str(interval["targetID"])
        timeline = {**player_ref(players, actor_map, pid), "ability": key, "label": ability["nameZh"],
                    "casts": actual, "intervals": aura, "windows": [], "effectKind": effect_kind, "spellIDs": sorted(ids)}
        for planned in assignment["times"]:
            lo, hi = planned if isinstance(planned, list) else (planned, planned)
            lo, hi = lo*1000, hi*1000
            phase, nominal = ("p3", 430000) if lo >= 469000 else ("intermission", 395000) if lo >= 395000 else ("p2", 180000) if lo >= 180000 else ("p1", 0)
            phase_reached = phase in phase_times
            shift = phase_times.get(phase, nominal)-nominal
            begin, end = max(0, lo+shift-row_tolerance), hi+shift+row_tolerance
            reached = phase_reached and duration >= end
            hit = next((t for t in actual if begin <= t <= end and t not in used), None)
            if hit is not None:
                used.add(hit)
            previous = max((t for t in actual if t < begin), default=None)
            following = min((t for t in actual if t > end), default=None)
            premature = previous is not None and previous not in used and begin-previous <= 60000
            status = "used" if hit is not None and phase_reached else "not-reached" if not reached else "early" if premature and (following is None or begin-previous <= following-end) else "late" if following is not None else "missing"
            row = {**player_ref(players, actor_map, pid), "ability": key, "label": ability["nameZh"],
                   "plannedStartTimeMs": lo, "plannedEndTimeMs": hi, "phaseShiftMs": shift,
                   "phase": phase,
                   "startTimeMs": begin, "endTimeMs": end, "castTimeMs": hit,
                   "previousCastTimeMs": previous, "nextCastTimeMs": following, "status": status,
                   "counted": reached and hit is None and skip_reason is None,
                   "reason": skip_reason or ("本场尚未走完整个检查窗口" if not reached and hit is None else
                       "在要求窗口使用" if hit is not None else f"{fmt_ms(begin)}–{fmt_ms(end)} 未使用；"+
                       (f"上一次 {fmt_ms(previous)}；" if previous is not None else "此前无使用记录；")+
                       (f"下一次 {fmt_ms(following)}，延后" if following is not None else "后续无使用记录"))}
            checks.append(row)
            timeline["windows"].append(row)
        if not aura and assignment.get("durationSeconds") and effect_kind != "cast-only":
            timeline["intervals"] = [{"startTimeMs": t, "endTimeMs": min(duration, t+assignment["durationSeconds"]*1000),
                                      "evidence": "configured-estimate"} for t in actual]
        timelines.append(timeline)
    return {"enabled": True, "analysisProfile": profile, "phaseControl": phases, "defaultThreshold": 5,
            "evidenceVersion": "guild-effects-v2",
            "holdWindowVersion": 2,
            "burstSkipped": skip_reason is not None, "burstSkipReason": skip_reason,
            "checks": checks, "timelines": timelines, "unresolved": unresolved,
            "timelineViewVersion": "icons-v1",
            "displayTimelines": build_guild_icon_timelines(timelines, raw, players, actor_map, fight),
            "bossComparison": build_timeline_comparison_evidence(fight, raw.get("casts", []), raw.get("enemyBuffs", [])),
            "count": sum(r["counted"] for r in checks),
            "players": [{**player_ref(players, actor_map, pid), "count": sum(r["counted"] for r in checks if r["playerID"] == pid)} for pid in players],
            "plan": effective_plan, "planNotes": [] if options.get("burstPlan") else AVALON_PLAN_NOTES,
            "phaseTimings": guild_phase_timings(markers, phases),
            "phaseTimeline": markers, "durationMs": duration,
            "reference": {"reportID": "Qh8XMfKGTmLJtk2r", "fightID": 1, "killTimeMs": 636333,
                          "p2TimeMs": 177991, "intermissionTimeMs": 389099, "p3TimeMs": 427666,
                          "phaseMethod": "boss-starts-phase-auras-v1"},
            "evidenceNote": "cast 仅统计玩家以该阶段 Boss 为目标的成功施法；伤害包含宠物。血量取目标自身资源或此前 3 秒内的样本；缺失不补零。未到达的爆发窗口不计数，技能充能与冷却刷新不替代实际施法。"}


def _fetch_guild_timeline(client, report_id, fight, actor_rows, payload, options):
    if not _guild_timeline_enabled(payload, options) or int(fight.get("difficulty") or 0) != 5:
        return payload
    burst_plan(options)  # Reject malformed configuration before expensive evidence requests.
    bosses = [a["id"] for a in actor_rows if a.get("gameID") in {257911, 259854}]
    if not bosses:
        return payload
    # WCL expression target.id is the NPC game ID, unlike GraphQL targetID
    # which is report-local. A report actor ID here silently returns no damage.
    expression = "target.id IN (257911, 259854)"
    payload["guildBossDamage"] = client.events(report_id, "DamageDone", fight,
        filter_expression=expression, include_resources=True)
    payload["guildPlayerCasts"] = client.events(report_id, "Casts", fight, hostility_type="Friendlies", include_resources=True)
    payload["guildPlayerBuffs"] = client.events(report_id, "Buffs", fight, hostility_type="Friendlies")
    catalog = {a["key"]: a for a in load_player_ability_catalog()["abilities"]}
    enemy_ids = sorted({sid for row in burst_plan(options) for ability in [catalog.get(row.get("ability"), {})]
                        if ability.get("auraTarget") == "enemy" for sid in ability.get("auraIds", [])})
    payload["guildEnemyDebuffs"] = client.events(report_id, "All", fight,
        filter_expression='type IN ("applydebuff", "refreshdebuff", "applydebuffstack", "removedebuff") AND ability.id IN ('+
        ', '.join(map(str, enemy_ids))+')') if enemy_ids else []
    return payload


def guild_timeline_overview(rendered):
    enabled = [p for p in rendered if (p.get("coiledaltar", {}).get("guildTimeline") or {}).get("enabled")]
    if not enabled:
        return []
    burst, hold = [], []
    for pull in enabled:
        data = pull["coiledaltar"]["guildTimeline"]
        for row in data["checks"]:
            if row["counted"]:
                burst.append(nightly_detail(pull, fmt_ms(row["startTimeMs"]), row["label"]+"："+row["reason"],
                    player=row["player"], playerID=row["playerID"], classColor=row.get("classColor"), count=1))
        for phase in data["phaseControl"]:
            if phase["status"] != "early":
                continue
            for row in phase["thresholds"].get("5", []):
                if row["castCount"]:
                    hold_until = phase.get("thresholdWindows", {}).get("5", {}).get("endTimeMs", 165000)
                    hold.append(nightly_detail(pull, fmt_ms(phase["endTimeMs"]),
                        phase["phase"].upper()+(" 首次低于 5% 至 "+fmt_ms(hold_until)+" 前目标施法 " if phase["phase"] == "p1" else " 提前结束，Boss 5% 以下目标施法 ")+str(row["castCount"])+" 次",
                        player=row["player"],playerID=row["playerID"],classColor=row.get("classColor"),
                        count=row["castCount"],damage=row["damage"],petDamage=row["petDamage"]))
    return [
        {"key":"guildBurstMisses","label":"公会爆发窗口未使用","value":len(burst),"unit":"次","tone":"warning",
         "description":"仅统计没有提前转阶段、已走完窗口且角色技能匹配的安排。",
         "players":nightly_player_totals(burst),"events":burst,"detailTab":"guildTimeline"},
        {"key":"guildHoldCasts","label":"提前转阶段低血量施法","value":sum(r["count"] for r in hold),"unit":"次","tone":"warning",
         "description":"P1 从首次低于 5% 至配置的停手截止（默认 2:45）前；P2 统计低于 5% 的目标施法。宠物只计伤害，单场支持 1%–10% 调整。",
         "players":nightly_player_totals(hold),"events":hold,"detailTab":"guildTimeline"}]


def fetch_payload(client, report_id, fight, actor_rows=None, options=None):
    options = resolve_analysis_options(CONFIG_SCHEMA, options or {})
    burst_plan(options)
    needs = _analysis_needs(options)
    field_enabled = needs["positions"]
    phase_enabled = options["eternalNightfallReviewEnabled"]
    intermission_enabled = options["intermissionReviewEnabled"]
    actor_rows = actor_rows or []
    if options['fieldReplayEnabled']:
        # One complete replay transport also supplies mechanic streams. Avoid
        # fetching the same coordinates again for each individual mechanic.
        from boss_plugins.venomous_abyss.runtime import _unified_payload
        zuljan = resolve_boss_actor_id(actor_rows, 257911, ("Zul'jan", "祖尔加"))
        ids = set(MECHANIC_CAST_IDS) | set(MECHANIC_DAMAGE_IDS) | set(MECHANIC_DEBUFF_IDS)
        ids |= set(MECHANIC_ENEMY_BUFF_IDS) | set(INTERMISSION_POTIONS) | {RECLAIM_ESSENCE}
        ids |= {CURSE_OF_TONGUES_ID,ALTAR_FANGS_ID,ALTAR_DEFILEMENT_ID}
        cfg = {'fetchCombatReplay':True, 'fetchPositionResources':True,
               'unifiedEventFilter':('resources.actor.id > 0 OR type IN '
                   '("cast", "begincast", "combatantinfo", "death", "resurrect", "interrupt") '
                   'OR ability.id IN ('+', '.join(map(str, sorted(ids)))+')'
                   +(f' OR (type = "heal" AND target.id = {zuljan})' if zuljan else ''))}
        transition = next((p for p in fight.get('phaseTransitions', []) if p.get('id') == 3), None)
        damage_window = None
        if transition and zuljan and options['intermissionReviewEnabled']:
            begin = int(transition['startTime'])
            end = min([int(p['startTime']) for p in fight['phaseTransitions'] if int(p['startTime']) > begin]+[int(fight['endTime'])])
            damage_window = begin,end
        def fetch_stream(index):
            if index == 2:
                return index,client.events(report_id, 'DamageDone', fight, target_id=zuljan,
                    start_time=damage_window[0],end_time=damage_window[1])
            value = (_unified_payload(client, report_id, fight, cfg, None, actor_rows, (), {}, (), {}, {})
                     if index == 0 else client.events(report_id, 'Deaths', fight))
            return index,value
        streams = run_parallel_indexed([0,1]+([2] if damage_window else []),fetch_stream,max_workers=3)
        payload, deaths = streams[0][1], streams[1][1]
        rows = payload['replayEvents']
        npc_ids = {a['id'] for a in actor_rows if a.get('type') not in {'Player', 'Pet'} and a.get('petOwner') is None}
        # All-events death rows omit killingAbilityGameID. Keep the compact
        # dedicated stream so cause-of-death adjudication remains lossless.
        payload.update({'heals':[e for e in rows if event_type(e) == 'heal' and ability_id(e) == RECLAIM_ESSENCE],
                        'buffs':payload['friendlyBuffs'],
                        'npcPositionEvents':[e for e in rows if e.get('sourceID') in npc_ids or e.get('targetID') in npc_ids],
                        'enemyDeaths':payload['deaths'][:],
                        'deaths':deaths,
                        'bossDamage':streams[2][1] if damage_window else [e for e in rows if event_type(e) == 'damage' and e.get('targetID') == zuljan],
                        'analysisOptions':options})
        payload["reportGuild"] = fight.get("reportGuild") or {}
        return _fetch_guild_timeline(client, report_id, fight, actor_rows, payload, options)
    zuljan_id = resolve_boss_actor_id(actor_rows, 257911, ("Zul'jan", "祖尔加"))
    malacrass_id = resolve_boss_actor_id(actor_rows, 259854, ("Hex Lord Malacrass", "玛拉卡斯", "Malacrass"))
    manifest_ids = set(manifest_actor_ids(actor_rows))
    mutation_ids = set(virulent_mutation_actor_ids(actor_rows))
    soulcoiler_ids = set(soulcoiler_actor_ids(actor_rows))
    boss_ids = {actor_id for actor_id in (zuljan_id, malacrass_id) if actor_id is not None}
    npc_filter = _npc_position_filter_expression(manifest_ids | boss_ids | mutation_ids | soulcoiler_ids)
    npc_position_events = []
    if field_enabled and npc_filter:
        npc_position_events.extend(client.events(
            report_id,
            "All",
            fight,
            filter_expression=npc_filter,
            include_resources=field_enabled,
        ))
    if needs["manifestationsReviewEnabled"]:
        npc_position_events.extend(_fetch_manifest_position_events(client, report_id, fight, manifest_ids))
    if field_enabled and soulcoiler_ids:
        npc_position_events.extend(_fetch_manifest_position_events(client, report_id, fight, soulcoiler_ids))
    boss_damage = []
    if intermission_enabled and zuljan_id is not None:
        boss_damage = client.events(report_id, "DamageDone", fight, target_id=zuljan_id)
    payload = {
        "reportGuild": fight.get("reportGuild") or {},
        "casts": _fetch_by_abilities(
            client, report_id, "Casts", fight, MECHANIC_CAST_IDS,
            hostility_type="Enemies", include_resources=field_enabled,
        ),
        "friendlyCasts": _fetch_by_abilities(
            client, report_id, "Casts", fight, FRIENDLY_CAST_IDS, hostility_type="Friendlies",
        ),
        "damage": _fetch_by_abilities(
            client, report_id, "DamageTaken", fight, MECHANIC_DAMAGE_IDS, include_resources=field_enabled,
        ) if field_enabled or any(options[key] for key in (
            "toxicDelugeReviewEnabled", "dreadmarchReviewEnabled", "guillotineReviewEnabled",
            "grimGuillotineReviewEnabled", "graveboundReviewEnabled", "intermissionReviewEnabled",
            "gloombombReviewEnabled",
        )) else [],
        "heals": _fetch_by_abilities(client, report_id, "Healing", fight, {RECLAIM_ESSENCE}) if intermission_enabled else [],
        "debuffs": _fetch_by_abilities(
            client, report_id, "Debuffs", fight, MECHANIC_DEBUFF_IDS, include_resources=field_enabled,
        ) if field_enabled or any(options[key] for key in ("dreadmarchReviewEnabled", "graveboundReviewEnabled", "intermissionReviewEnabled")) else [],
        "buffs": _fetch_by_abilities(
            client, report_id, "Buffs", fight, set(INTERMISSION_POTIONS), hostility_type="Friendlies",
        ) if intermission_enabled else [],
        "enemyBuffs": _fetch_by_abilities(
            client, report_id, "Buffs", fight, MECHANIC_ENEMY_BUFF_IDS, hostility_type="Enemies",
            include_resources=field_enabled,
        ),
        "deaths": client.events(report_id, "Deaths", fight),
        "enemyDeaths": client.events(report_id, "Deaths", fight, hostility_type="Enemies"),
        "combatants": client.events(report_id, "CombatantInfo", fight),
        "resources": client.events(report_id, "Resources", fight, include_resources=True) if field_enabled else [],
        "interrupts": client.events(report_id, "Interrupts", fight, hostility_type="Friendlies") if phase_enabled or options["gloombombReviewEnabled"] else [],
        "replayEvents": fetch_replay_events(client, report_id, fight) if options["fieldReplayEnabled"] else [],
        "npcPositionEvents": npc_position_events,
        "bossDamage": boss_damage,
        "analysisOptions": options,
    }
    return _fetch_guild_timeline(client, report_id, fight, actor_rows, payload, options)


def render_fight(report_id, report_start, actor_map, actor_type, actor_rows, fight, raw):
    fight = {**fight, "reportStartTime":report_start}
    fight = _with_observed_tuning(fight, raw)
    players = build_player_catalog(actor_map, actor_type, raw["combatants"])
    mechanics = analyze_fight(fight, actor_map, actor_type, actor_rows, raw)
    mechanics["tuning"] = encounter_tuning(fight)
    options = resolve_analysis_options(CONFIG_SCHEMA, raw.get("analysisOptions") or {})
    mechanics["analysisProfile"] = resolve_profile(raw.get("reportGuild"), options)
    mechanics["guildTimeline"] = analyze_guild_timeline(
        fight, mechanics["phaseTimeline"], raw, actor_rows, actor_map, players, options)

    duration_ms = int(fight["endTime"] - fight["startTime"])
    started = datetime.fromtimestamp((report_start + fight["startTime"]) / 1000, tz=CN_TZ)
    survival = build_survival_timeline(fight, actor_map, players, raw["deaths"], raw["friendlyCasts"], SPELLS)
    if raw.get("replayEvents"):
        mechanics["combatReplay"] = build_replay_tracks(fight, players, actor_map, raw["replayEvents"], actor_rows=actor_rows, spell_names=SPELLS, deaths=raw["deaths"], survival_timeline=survival["timeline"], include_facing=True)
        _apply_altar_boss_lifetimes(mechanics, actor_rows)
        mechanics['soulcoilerReplay'] = _build_soulcoiler_replay(fight, mechanics, raw, players, actor_map)
        mechanics['altarGroundReplay'] = _build_altar_ground_replay(fight, mechanics, raw)
        _apply_altar_nightfall_replay(fight, mechanics, raw, players, actor_map)
        mechanics['soulbindReplay'] = _apply_altar_soulbind_replay(fight, mechanics, raw)
        mechanics['manifestReplay'] = _build_manifest_replay(fight, mechanics, raw, players, actor_map)
        mechanics.setdefault('manifestations', {})['resonanceCollisions'] = mechanics['manifestReplay']['resonanceCollisions']
    end_phase = mechanics["phaseTimeline"][-2]["label"] if len(mechanics["phaseTimeline"]) > 1 else "P1"
    return {
        "reportID": report_id,
        "fightID": int(fight["id"]),
        "fightName": fight.get("name"),
        "date": started.strftime("%Y-%m-%d"),
        "startClock": started.strftime("%H:%M:%S"),
        "startTimeIso": started.isoformat(),
        "isKill": bool(fight.get("kill")),
        "kill": bool(fight.get("kill")),
        "bossPercentage": float(fight.get("bossPercentage") or 0),
        "fightPercentage": fight.get("fightPercentage"),
        "phaseCode": {"p1":"P1", "p2":"P2", "intermission":"P2.5", "p3":"P3"}.get(
            next((p["key"] for p in reversed(mechanics["phaseTimeline"]) if p["key"] not in {"wipe", "kill"}), ""), ""),
        "durationMs": duration_ms,
        "duration": fmt_ms(duration_ms),
        "wipePhase": end_phase,
        "wipeReason": "已击杀" if fight.get("kill") else f"灭团于{end_phase}",
        "investigation": "阶段以 WCL 报告 phaseTransitions 为准；凝结毒液、恐惧行军、锥形清场、幽暗炸弹分散与转阶段残片均已按阶段对齐。",
        "phaseTimeline": mechanics["phaseTimeline"],
        "wclDeepLink": f"https://www.warcraftlogs.com/reports/{report_id}#fight={fight['id']}&type=summary",
        "players": list(players.values()),
        "survival": survival,
        "deathTimeline": survival["timeline"],
        **difficulty_fields(fight),
        "coiledaltar": mechanics,
    }


REGULAR_PHASE_KEYS = {"p1", "p2", "p3"}


def _regular_phase(row):
    phase = str(row.get("phase") or "").lower()
    if not phase:
        return True
    if phase in REGULAR_PHASE_KEYS:
        return True
    return phase != "intermission" and "转" not in phase


def _mechanic_overview(rendered):
    """整夜机制统计：幽暗炸弹误伤、灵魂未劈中、常规阶段撞具象恐惧行军、墓缚致死。"""
    gloombomb_hits = []
    uncleared_souls = []
    dreadmarch_collisions = []
    gravebound_deaths = []
    for pull in rendered:
        mechanics = pull.get("coiledaltar") or {}
        for round_row in (mechanics.get("gloombomb") or {}).get("rounds") or []:
            named_targets = round_row.get("targets") or []
            has_named_breakdown = any("collateralGravebound" in (target or {}) for target in named_targets)
            if has_named_breakdown:
                for target in named_targets:
                    for hit in target.get("collateralGravebound") or []:
                        if hit.get("receivedGravebound") is False:
                            continue
                        gloombomb_hits.append(nightly_detail(
                            pull,
                            round_row.get("time") or hit.get("graveboundApplyTime"),
                            f"{target.get('player') or '未知玩家'} 的幽暗炸弹误伤 {hit.get('player') or '未知队友'}",
                            player=target.get("player"),
                            classColor=target.get("classColor"),
                            victim=hit.get("player"),
                        ))
            else:
                for hit in round_row.get("collateralHits") or []:
                    gloombomb_hits.append(nightly_detail(
                        pull,
                        round_row.get("time") or hit.get("graveboundApplyTime"),
                        f"{hit.get('fromPlayer') or '点名者'} 的幽暗炸弹误伤 {hit.get('player') or '未知队友'}",
                        player=hit.get("fromPlayer"),
                        classColor=hit.get("fromClassColor"),
                        victim=hit.get("player"),
                    ))
        for key, mechanic_name in (("soulSever", "灵魂撕裂"), ("blightedSever", "凋零撕裂")):
            for round_row in (mechanics.get(key) or {}).get("rounds") or []:
                for point in round_row.get("unclearedManifestations") or []:
                    if point.get("inCone") is True:
                        continue
                    uncleared_souls.append(nightly_detail(
                        pull,
                        round_row.get("time"),
                        f"{point.get('player') or '未知玩家'} 携带灵魂，未被{mechanic_name}劈中",
                        player=point.get("player"),
                        classColor=point.get("classColor"),
                        mechanic=mechanic_name,
                    ))
        dreadmarch = mechanics.get("dreadmarch") or {}
        applications = list(dreadmarch.get("applications") or [])
        if not applications:
            for round_row in dreadmarch.get("rounds") or []:
                applications.extend(round_row.get("targets") or [])
        for row in applications:
            if not _regular_phase(row):
                continue
            if not (row.get("hitManifestation") or row.get("triggerKind") == "manifest-collision"):
                continue
            dreadmarch_collisions.append(nightly_detail(
                pull,
                row.get("appliedTime") or row.get("time"),
                f"{row.get('player') or '未知玩家'} 常规阶段撞具象触发恐惧行军",
                player=row.get("player"),
                classColor=row.get("classColor"),
            ))
        for row in (mechanics.get("graveboundFailures") or {}).get("failures") or []:
            if not _is_gravebound_damage_death(row):
                continue
            ability = row.get("deathAbility") or row.get("deathAbilityID") or "墓缚"
            gravebound_deaths.append(nightly_detail(
                pull,
                row.get("time"),
                f"{row.get('player') or '未知玩家'} 死于墓缚（{ability}）",
                player=row.get("player"),
                classColor=row.get("classColor"),
                spellID=row.get("deathAbilityID"),
            ))
    return {
        "title": "整夜机制统计",
        "subtitle": "按所有 Pull 汇总可验证事件；单场阶段页明细保持原样。",
        "metrics": [
            {
                "key": "gloombombCollateralHits",
                "label": "幽暗炸弹误伤队友",
                "value": len(gloombomb_hits),
                "unit": "人次",
                "tone": "danger",
                "description": "按被点名炸弹的玩家计：爆炸 15 码内且 2 秒内给队友上墓缚 1286837 一次计一次。同一队友被两枚炸弹溅到会分别记到两名点名者。",
                "players": nightly_player_totals(gloombomb_hits),
                "events": gloombomb_hits,
            },
            {
                "key": "unclearedSouls",
                "label": "携带灵魂未被劈中",
                "value": len(uncleared_souls),
                "unit": "次",
                "tone": "danger",
                "description": "灵魂撕裂 / 凋零撕裂释放时场上仍有凝视，且该具象不在锥形内；锥内但没消掉的不算「未被劈中」。",
                "players": nightly_player_totals(uncleared_souls),
                "events": uncleared_souls,
            },
            {
                "key": "regularDreadmarch",
                "label": "常规阶段恐惧行军",
                "value": len(dreadmarch_collisions),
                "unit": "次",
                "tone": "warning",
                "description": "与单场撞具象同一套判定：常规阶段里首次救人后、下一轮 Boss 释放前再次获得 1297445 的玩家。Boss 正常点名不计入。",
                "players": nightly_player_totals(dreadmarch_collisions),
                "events": dreadmarch_collisions,
            },
            {
                "key": "graveboundDeaths",
                "label": "死于墓缚",
                "value": len(gravebound_deaths),
                "unit": "次",
                "tone": "danger",
                "description": "只统计 1297906 直接致死。1286837 / 1308330 以及其他技能致死不计入。",
                "players": nightly_player_totals(gravebound_deaths),
                "events": gravebound_deaths,
            },
        ],
    }


def build_aggregated_json(report_ids, options=None):
    options = resolve_analysis_options(CONFIG_SCHEMA, options or {})
    report_id_list = parse_wcl_report_ids(report_ids)
    if not report_id_list:
        raise RuntimeError("请传入至少一个 WCL report ID。")
    client = WclClient()
    rendered = []
    progress("读取盘卷祭坛 Pull 列表", 8)
    for report_id in report_id_list:
        report = client.report_fights(report_id)
        phase_metadata = encounter_phase_metadata(report, ENCOUNTER_IDS)
        fights = filter_fights(
            report_id,
            [
                {
                    **fight,
                    "wclPhaseMetadata": phase_metadata,
                    "reportStartTime": report["startTime"],
                    "reportGuild": report.get("guild") or {},
                }
                for fight in report["fights"]
                if int(fight.get("encounterID") or 0) in ENCOUNTER_IDS
                and fight["endTime"] - fight["startTime"] >= 20_000
            ],
        )
        actor_rows = client.actors(report_id)
        actor_map = {row["id"]: row["name"] for row in actor_rows}
        actor_type = {row["id"]: row.get("type") for row in actor_rows}
        progress(f"{report_id}：匹配 {len(fights)} 场", 12)

        def fetch_one(item):
            index, fight = item
            progress(f"读取 Fight {fight['id']}（{index}/{len(fights)}）")
            raw = fetch_payload(client, report_id, fight, actor_rows, options)
            return index, render_fight(report_id, report["startTime"], actor_map, actor_type, actor_rows, fight, raw)

        for _, row in run_parallel_indexed(list(enumerate(fights, start=1)), fetch_one):
            rendered.append(row)
    rendered.sort(key=lambda row: (row["startTimeIso"], row["reportID"], row["fightID"]))
    progress("生成盘卷祭坛阶段复盘与场地示意图", 96)
    overview = _mechanic_overview(rendered)
    metric_enabled = {"gloombombCollateralHits": options["gloombombReviewEnabled"],
                      "unclearedSouls": options["soulSeverReviewEnabled"] or options["blightedSeverReviewEnabled"],
                      "regularDreadmarch": options["dreadmarchReviewEnabled"], "graveboundDeaths": options["graveboundReviewEnabled"]}
    overview["metrics"] = [row for row in overview["metrics"] if metric_enabled[row["key"]]]
    overview["metrics"].extend(guild_timeline_overview(rendered))
    return {
        "code": 200,
        "meta": {
            "version": "12.1",
            "raidKey": "venomous_abyss",
            "raidName": "烈毒之渊",
            "bossKey": "coiledaltar",
            "bossName": "盘卷祭坛",
            "analyzedReports": report_id_list,
            "mechanicVersion": "coiledaltar-guild-timeline-2026-10-19-v150",
            "tabDefinitions": [{"key": key, "label": label} for key, label in TABS
                               if (key not in {"field", "replay"} or options["fieldReplayEnabled"])
                               and (key != "intermission" or options["intermissionReviewEnabled"])],
            "analysisConfig": options,
            "skippedAnalyses": [field["label"] for field in CONFIG_SCHEMA if field["type"] == "boolean" and not options[field["key"]]],
            "arenaImage": ARENA_IMAGE,
            "fieldIcons": dict(FIELD_ICONS),
            "features": {"survival": True, "fieldReplay": options["fieldReplayEnabled"]},
            "evidenceLimits": {
                "positions": (
                    f"示意图把坐标 ({ARENA_CENTER_X_UNITS:g}, {ARENA_CENTER_Y_UNITS:g}) 映射为 "
                    f"边长 {int(ARENA_SIDE_YARDS)} 码正方形（WCL 坐标=码×100），"
                    "示意图含撕裂锥形、处斩/冷酷处斩跑离、幽暗炸弹分散；"
                    "撕裂圆心优先取施法 sourceResources，朝向按坦克易伤 debuff / 读条末秒位置锁定；"
                    "剧毒洪流落点按落地/拾取状态机追踪（支持多次接力），场上毒液优先 1282408 源坐标；"
                    "阶段优先使用 WCL phaseTransitions；没有阶段数据时再按祖尔加死亡或玛拉卡斯出现推断 P2。"
                ),
                "manifestNpc": (
                    f"恐惧具象实例通过 debuff {FIXATION} 的 sourceID/sourceInstance 与 NPC gameID {MANIFEST_NPC_GAME_ID} 对齐；"
                    "坐标优先取 sourceResources / 受击 targetResources，不用被点名玩家的顶层 x/y；"
                    "示意图用红线连接被点名玩家与具象。"
                ),
            },
        },
        "data": {
            "page1_wipeAnalysis": rendered,
            "mechanicOverview": overview,
        },
    }


def analyze(report_ids, output_path=None, catalog_entry=None, options=None, progress_callback=None):
    del progress_callback  # reserved for runner compatibility
    payload = build_aggregated_json(report_ids, options)
    if output_path:
        write_json_result(payload, output_path)
    return payload
