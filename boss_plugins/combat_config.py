"""Shared player-role and defensive ability configuration.

The tables in this module describe evidence, not verdicts.  In particular,
``effectKind=max_health`` or ``healing`` means the player used a defensive
action, but does not imply a fixed damage-reduction percentage.
"""

from typing import Iterable, Optional


PERSONAL_DEFENSIVES = {
    # Death Knight
    48792: {"name": "冰封之韧", "class": "DeathKnight", "effectKind": "damage_reduction", "durationMs": 8_000},
    48707: {"name": "反魔法护罩", "class": "DeathKnight", "effectKind": "magic_absorb", "durationMs": 5_000},
    49039: {"name": "巫妖之躯", "class": "DeathKnight", "effectKind": "damage_reduction", "durationMs": 10_000},
    # Demon Hunter
    198589: {"name": "疾影", "class": "DemonHunter", "effectKind": "damage_reduction", "durationMs": 10_000},
    196555: {"name": "虚空行走", "class": "DemonHunter", "effectKind": "immunity", "durationMs": 6_000},
    # Druid
    22812: {"name": "树皮术", "class": "Druid", "effectKind": "damage_reduction", "durationMs": 12_000},
    61336: {"name": "生存本能", "class": "Druid", "effectKind": "damage_reduction", "durationMs": 6_000},
    108238: {"name": "新生", "class": "Druid", "effectKind": "healing", "durationMs": 0},
    # Evoker
    363916: {"name": "黑曜鳞片", "class": "Evoker", "effectKind": "damage_reduction", "durationMs": 12_000},
    374348: {"name": "焕燃之焰", "class": "Evoker", "effectKind": "healing", "durationMs": 8_000},
    # Hunter
    186265: {"name": "灵龟守护", "class": "Hunter", "effectKind": "immunity", "durationMs": 8_000},
    264735: {"name": "适者生存", "class": "Hunter", "effectKind": "damage_reduction", "durationMs": 6_000},
    109304: {"name": "意气风发", "class": "Hunter", "effectKind": "healing", "durationMs": 0},
    # Mage
    45438: {"name": "寒冰屏障", "class": "Mage", "effectKind": "immunity", "durationMs": 10_000},
    110959: {"name": "强化隐形术", "class": "Mage", "effectKind": "damage_reduction", "durationMs": 3_000},
    342245: {"name": "操控时间", "class": "Mage", "effectKind": "health_rewind", "durationMs": 10_000},
    # Monk
    115203: {"name": "壮胆酒", "class": "Monk", "effectKind": "damage_reduction", "durationMs": 15_000},
    122783: {"name": "散魔功", "class": "Monk", "effectKind": "magic_reduction", "durationMs": 6_000},
    122278: {"name": "躯不坏", "class": "Monk", "effectKind": "damage_reduction", "durationMs": 10_000},
    122470: {"name": "业报之触", "class": "Monk", "effectKind": "absorb", "durationMs": 10_000},
    # Paladin
    642: {"name": "圣盾术", "class": "Paladin", "effectKind": "immunity", "durationMs": 8_000},
    498: {"name": "圣佑术", "class": "Paladin", "effectKind": "damage_reduction", "durationMs": 8_000},
    184662: {"name": "复仇之盾", "class": "Paladin", "effectKind": "absorb", "durationMs": 15_000},
    # Priest
    19236: {"name": "绝望祷言", "class": "Priest", "effectKind": "max_health", "durationMs": 10_000},
    47585: {"name": "消散", "class": "Priest", "effectKind": "damage_reduction", "durationMs": 6_000},
    586: {"name": "渐隐术", "class": "Priest", "effectKind": "conditional_reduction", "durationMs": 10_000},
    # Rogue
    31224: {"name": "暗影斗篷", "class": "Rogue", "effectKind": "magic_immunity", "durationMs": 5_000},
    1966: {"name": "佯攻", "class": "Rogue", "effectKind": "aoe_reduction", "durationMs": 6_000},
    5277: {"name": "闪避", "class": "Rogue", "effectKind": "avoidance", "durationMs": 10_000},
    185311: {"name": "猩红之瓶", "class": "Rogue", "effectKind": "healing", "durationMs": 6_000},
    # Shaman
    108271: {"name": "星界转移", "class": "Shaman", "effectKind": "damage_reduction", "durationMs": 12_000},
    198103: {"name": "土元素", "class": "Shaman", "effectKind": "max_health", "durationMs": 60_000},
    # Warlock
    104773: {"name": "不灭决心", "class": "Warlock", "effectKind": "damage_reduction", "durationMs": 8_000},
    108416: {"name": "黑暗契约", "class": "Warlock", "effectKind": "absorb", "durationMs": 20_000},
    6789: {"name": "死亡缠绕", "class": "Warlock", "effectKind": "healing", "durationMs": 0},
    # Warrior
    118038: {"name": "剑在人在", "class": "Warrior", "effectKind": "damage_reduction", "durationMs": 8_000},
    386208: {"name": "防御姿态", "class": "Warrior", "effectKind": "damage_reduction", "durationMs": 0},
    184364: {"name": "狂怒回复", "class": "Warrior", "effectKind": "damage_reduction", "durationMs": 8_000},
    23920: {"name": "法术反射", "class": "Warrior", "effectKind": "magic_reduction", "durationMs": 5_000},
}


RAID_DEFENSIVES = {
    97462: {"name": "命令怒吼", "class": "Warrior", "effectKind": "max_health", "durationMs": 10_000},
    51052: {"name": "反魔法领域", "class": "DeathKnight", "effectKind": "magic_reduction", "durationMs": 10_000},
    196718: {"name": "黑暗", "class": "DemonHunter", "effectKind": "avoidance", "durationMs": 8_000},
    31821: {"name": "光环掌握", "class": "Paladin", "effectKind": "aura_amplification", "durationMs": 8_000},
    62618: {"name": "真言术：障", "class": "Priest", "effectKind": "damage_reduction", "durationMs": 10_000},
    98008: {"name": "灵魂链接图腾", "class": "Shaman", "effectKind": "damage_reduction", "durationMs": 6_000},
    374227: {"name": "微风拂面", "class": "Evoker", "effectKind": "aoe_reduction", "durationMs": 8_000},
    414660: {"name": "群体屏障", "class": "Mage", "effectKind": "absorb", "durationMs": 60_000},
    740: {"name": "宁静", "class": "Druid", "effectKind": "raid_healing", "durationMs": 8_000},
    115310: {"name": "还魂术", "class": "Monk", "effectKind": "raid_healing", "durationMs": 0},
    388615: {"name": "祛病延年", "class": "Monk", "effectKind": "raid_healing", "durationMs": 0},
}

PERSONAL_DEFENSIVE_COOLDOWNS_MS = {
    48792: 120_000,
    48707: 60_000,
    49039: 120_000,
    198589: 60_000,
    196555: 180_000,
    22812: 60_000,
    61336: 180_000,
    108238: 90_000,
    363916: 90_000,
    374348: 60_000,
    186265: 180_000,
    264735: 120_000,
    109304: 120_000,
    45438: 240_000,
    110959: 120_000,
    342245: 60_000,
    115203: 360_000,
    122783: 90_000,
    122278: 120_000,
    122470: 90_000,
    642: 300_000,
    498: 60_000,
    184662: 120_000,
    19236: 90_000,
    47585: 120_000,
    586: 20_000,
    31224: 120_000,
    1966: 0,
    5277: 120_000,
    185311: 30_000,
    108271: 90_000,
    198103: 300_000,
    104773: 180_000,
    108416: 60_000,
    6789: 45_000,
    118038: 120_000,
    386208: 0,
    184364: 120_000,
    23920: 25_000,
}

# Instant heals, health rewinds and stance-like actions still count as a recent
# defensive action when used inside this evidence window.
PERSONAL_DEFENSIVE_EVIDENCE_WINDOWS_MS = {
    108238: 5_000,
    109304: 5_000,
    342245: 10_000,
    19236: 10_000,
    185311: 6_000,
    198103: 60_000,
    6789: 5_000,
    386208: 15_000,
}

# Recharge is evaluated from the full fight cast timeline.  Multi-charge spells
# stay available until every configured charge is currently recharging.
PERSONAL_DEFENSIVE_CHARGES = {
    61336: 2,
    363916: 2,
}

RAID_DEFENSIVE_COOLDOWNS_MS = {
    97462: 180_000,
    51052: 120_000,
    196718: 180_000,
    31821: 180_000,
    62618: 180_000,
    98008: 180_000,
    374227: 120_000,
    414660: 180_000,
    740: 180_000,
    115310: 180_000,
    388615: 180_000,
}

# Raid-planning abilities are intentionally broader than ``RAID_DEFENSIVES``.
# They drive the raid-leader timeline/export tool and must not automatically be
# interpreted as mitigation covering a death.
TEAM_COOLDOWNS = {
    # Restoration Druid
    740: {"name": "宁静", "class": "Druid", "category": "healing", "specKeys": ["restoration-druid"]},
    197721: {"name": "繁盛", "class": "Druid", "category": "healing", "specKeys": ["restoration-druid"]},
    33891: {"name": "化身：生命之树", "class": "Druid", "category": "healing", "specKeys": ["restoration-druid"]},
    # Discipline / Holy Priest
    62618: {"name": "真言术：障", "class": "Priest", "category": "raid_defensive", "specKeys": ["discipline-priest"]},
    47536: {"name": "全神贯注", "class": "Priest", "category": "healing", "specKeys": ["discipline-priest"]},
    246287: {"name": "福音", "class": "Priest", "category": "healing", "specKeys": ["discipline-priest"]},
    33206: {"name": "痛苦压制", "class": "Priest", "category": "external", "specKeys": ["discipline-priest"]},
    64843: {"name": "神圣赞美诗", "class": "Priest", "category": "healing", "specKeys": ["holy-priest"]},
    265202: {"name": "圣言术：赎", "class": "Priest", "category": "healing", "specKeys": ["holy-priest"]},
    200183: {"name": "神圣化身", "class": "Priest", "category": "healing", "specKeys": ["holy-priest"]},
    47788: {"name": "守护之魂", "class": "Priest", "category": "external", "specKeys": ["holy-priest"]},
    # Holy Paladin
    31821: {"name": "光环掌握", "class": "Paladin", "category": "raid_defensive", "specKeys": ["holy-paladin"]},
    31884: {"name": "复仇之怒", "class": "Paladin", "category": "healing", "specKeys": ["holy-paladin"]},
    200652: {"name": "提尔的拯救", "class": "Paladin", "category": "healing", "specKeys": ["holy-paladin"]},
    414170: {"name": "破晓", "class": "Paladin", "category": "healing", "specKeys": ["holy-paladin"]},
    375576: {"name": "圣洁鸣钟", "class": "Paladin", "category": "healing", "specKeys": ["holy-paladin"]},
    # Restoration Shaman
    98008: {"name": "灵魂链接图腾", "class": "Shaman", "category": "raid_defensive", "specKeys": ["restoration-shaman"]},
    108280: {"name": "治疗之潮图腾", "class": "Shaman", "category": "healing", "specKeys": ["restoration-shaman"]},
    114052: {"name": "升腾", "class": "Shaman", "category": "healing", "specKeys": ["restoration-shaman"]},
    207399: {"name": "先祖护佑图腾", "class": "Shaman", "category": "raid_defensive", "specKeys": ["restoration-shaman"]},
    # Mistweaver Monk
    115310: {"name": "还魂术", "class": "Monk", "category": "healing", "specKeys": ["mistweaver-monk"]},
    388615: {"name": "祛病延年", "class": "Monk", "category": "healing", "specKeys": ["mistweaver-monk"]},
    322118: {"name": "召唤青龙玉珑", "class": "Monk", "category": "healing", "specKeys": ["mistweaver-monk"]},
    325197: {"name": "召唤朱鹤赤精", "class": "Monk", "category": "healing", "specKeys": ["mistweaver-monk"]},
    116849: {"name": "作茧缚命", "class": "Monk", "category": "external", "specKeys": ["mistweaver-monk"]},
    # Preservation Evoker
    363534: {"name": "回溯", "class": "Evoker", "category": "healing", "specKeys": ["preservation-evoker"]},
    359816: {"name": "梦境飞行", "class": "Evoker", "category": "healing", "specKeys": ["preservation-evoker"]},
    370537: {"name": "静滞", "class": "Evoker", "category": "healing", "specKeys": ["preservation-evoker"]},
    357170: {"name": "时间膨胀", "class": "Evoker", "category": "external", "specKeys": ["preservation-evoker"]},
    374227: {"name": "微风拂面", "class": "Evoker", "category": "raid_defensive", "specKeys": ["preservation-evoker", "augmentation-evoker"]},
    # Cross-role raid defensives
    97462: {"name": "命令怒吼", "class": "Warrior", "category": "raid_defensive", "specKeys": []},
    51052: {"name": "反魔法领域", "class": "DeathKnight", "category": "raid_defensive", "specKeys": []},
    196718: {"name": "黑暗", "class": "DemonHunter", "category": "raid_defensive", "specKeys": []},
    414660: {"name": "群体屏障", "class": "Mage", "category": "raid_defensive", "specKeys": []},
    # Raid movement / positional utility
    106898: {"name": "狂奔怒吼", "class": "Druid", "category": "movement", "specKeys": []},
    192077: {"name": "狂风图腾", "class": "Shaman", "category": "movement", "specKeys": []},
    111771: {"name": "恶魔传送门", "class": "Warlock", "category": "movement", "specKeys": []},
    # Augmentation / Evoker raid utility
    374968: {"name": "时间螺旋", "class": "Evoker", "category": "augmentation", "specKeys": ["augmentation-evoker"]},
    406732: {"name": "空间悖论", "class": "Evoker", "category": "augmentation", "specKeys": ["augmentation-evoker"]},
}


def _ability_id(event: dict) -> Optional[int]:
    value = (
        event.get("abilityGameID")
        or event.get("abilityID")
        or event.get("gameID")
        or (event.get("ability") or {}).get("gameID")
    )
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def defensive_spell_ids(*, include_personal=True, include_raid=True) -> set:
    spell_ids = set()
    if include_personal:
        spell_ids.update(PERSONAL_DEFENSIVES)
    if include_raid:
        spell_ids.update(RAID_DEFENSIVES)
    return spell_ids


def _player_casts_for_spell(cast_events, player_id, spell_id, *, before_timestamp=None) -> list:
    rows = []
    for event in cast_events or []:
        if event.get("sourceID") != player_id or _ability_id(event) != spell_id:
            continue
        timestamp = int(event.get("timestamp") or 0)
        if before_timestamp is not None and timestamp > before_timestamp:
            continue
        rows.append(event)
    return sorted(rows, key=lambda event: int(event.get("timestamp") or 0))


def audit_personal_defensive_readiness(
    cast_events: Iterable[dict],
    *,
    death_timestamp: int,
    player_id,
    available_spell_ids: Iterable[int],
) -> dict:
    """Classify a death using full-fight defensive cast history.

    ``available_spell_ids`` must be the abilities actually available to this
    character (from combatant/talent data or an explicit roster preset).  This
    prevents optional talents from being treated as unused merely because the
    class could theoretically learn them.
    """

    abilities = []
    for raw_spell_id in available_spell_ids or []:
        spell_id = int(raw_spell_id)
        if spell_id not in PERSONAL_DEFENSIVES:
            continue
        casts = _player_casts_for_spell(
            cast_events,
            player_id,
            spell_id,
            before_timestamp=death_timestamp,
        )
        last = casts[-1] if casts else None
        last_timestamp = int(last.get("timestamp") or 0) if last else None
        cooldown_ms = int(PERSONAL_DEFENSIVE_COOLDOWNS_MS.get(spell_id) or 0)
        charges = int(PERSONAL_DEFENSIVE_CHARGES.get(spell_id) or 1)
        duration_ms = int(PERSONAL_DEFENSIVES[spell_id].get("durationMs") or 0)
        evidence_window_ms = int(
            PERSONAL_DEFENSIVE_EVIDENCE_WINDOWS_MS.get(spell_id, duration_ms)
        )
        ms_since_usage = death_timestamp - last_timestamp if last_timestamp is not None else None
        active_at_death = (
            last_timestamp is not None
            and evidence_window_ms > 0
            and ms_since_usage <= evidence_window_ms
        )
        recharging_uses = (
            []
            if cooldown_ms == 0
            else [
                int(event.get("timestamp") or 0)
                for event in casts
                if int(event.get("timestamp") or 0) + cooldown_ms > death_timestamp
            ]
        )
        ready_at_death = cooldown_ms == 0 or len(recharging_uses) < charges
        cooldown_remaining_ms = (
            0
            if ready_at_death
            else min(timestamp + cooldown_ms - death_timestamp for timestamp in recharging_uses)
        )
        abilities.append({
            "spellID": spell_id,
            **PERSONAL_DEFENSIVES[spell_id],
            "cooldownMs": cooldown_ms,
            "charges": charges,
            "chargesRecharging": len(recharging_uses),
            "evidenceWindowMs": evidence_window_ms,
            "lastUsage": last_timestamp,
            "msSinceLastUsage": ms_since_usage,
            "activeAtDeath": active_at_death,
            "readyAtDeath": ready_at_death,
            "cooldownRemainingMs": cooldown_remaining_ms,
        })

    active = [row for row in abilities if row["activeAtDeath"]]
    ready = [row for row in abilities if row["readyAtDeath"]]
    if active:
        status = "defensive_active"
    elif ready:
        status = "available_unused"
    elif abilities:
        status = "all_on_cooldown"
    else:
        status = "no_configured_defensive"
    return {
        "status": status,
        "counted": status == "available_unused",
        "deathTimestamp": int(death_timestamp),
        "playerID": player_id,
        "abilities": abilities,
        "activeAbilities": active,
        "readyUnusedAbilities": ready if not active else [],
    }


def audit_raid_defensive_assignment(
    cast_events: Iterable[dict],
    *,
    mechanic_timestamp: int,
    assigned_spell_ids: Iterable[int],
    lead_ms=5_000,
    followup_ms=1_500,
) -> dict:
    """Check whether an assigned raid cooldown was pressed for one AOE."""

    assigned = {int(value) for value in assigned_spell_ids or [] if int(value) in RAID_DEFENSIVES}
    window_start = int(mechanic_timestamp) - int(lead_ms)
    window_end = int(mechanic_timestamp) + int(followup_ms)
    uses = []
    for event in cast_events or []:
        spell_id = _ability_id(event)
        timestamp = int(event.get("timestamp") or 0)
        if spell_id not in assigned or not window_start <= timestamp <= window_end:
            continue
        uses.append({
            "spellID": spell_id,
            **RAID_DEFENSIVES[spell_id],
            "sourceID": event.get("sourceID"),
            "timestamp": timestamp,
            "offsetMs": timestamp - mechanic_timestamp,
        })
    uses.sort(key=lambda row: row["timestamp"])
    return {
        "status": "used" if uses else "missing",
        "counted": not uses,
        "mechanicTimestamp": int(mechanic_timestamp),
        "assignedSpellIDs": sorted(assigned),
        "uses": uses,
        "window": {"beforeMs": int(lead_ms), "afterMs": int(followup_ms)},
    }


def find_defensive_uses_before_death(
    cast_events: Iterable[dict],
    *,
    death_timestamp: int,
    player_id=None,
    lookback_ms=15_000,
) -> dict:
    """Return personal actions and raid cooldown coverage near one death.

    Personal actions are limited to the dead player's casts.  Raid cooldowns
    may be cast by any friendly player and count as active only when their
    configured duration covers the death timestamp.
    """

    personal = []
    raid = []
    window_start = int(death_timestamp) - int(lookback_ms)
    for event in cast_events or []:
        spell_id = _ability_id(event)
        timestamp = int(event.get("timestamp") or 0)
        if not spell_id or timestamp < window_start or timestamp > death_timestamp:
            continue
        if spell_id in PERSONAL_DEFENSIVES and event.get("sourceID") == player_id:
            personal.append({
                "spellID": spell_id,
                **PERSONAL_DEFENSIVES[spell_id],
                "timestamp": timestamp,
                "msBeforeDeath": death_timestamp - timestamp,
            })
        if spell_id in RAID_DEFENSIVES:
            ability = RAID_DEFENSIVES[spell_id]
            duration = int(ability.get("durationMs") or 0)
            raid.append({
                "spellID": spell_id,
                **ability,
                "sourceID": event.get("sourceID"),
                "timestamp": timestamp,
                "msBeforeDeath": death_timestamp - timestamp,
                "activeAtDeath": duration > 0 and timestamp + duration >= death_timestamp,
            })
    personal.sort(key=lambda row: row["timestamp"], reverse=True)
    raid.sort(key=lambda row: row["timestamp"], reverse=True)
    return {
        "lastPersonalDefensive": personal[0] if personal else None,
        "personalDefensives": personal,
        "raidDefensives": raid,
        "activeRaidDefensives": [row for row in raid if row["activeAtDeath"]],
        "lookbackMs": int(lookback_ms),
    }
