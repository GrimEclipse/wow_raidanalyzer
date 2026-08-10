import json
from pathlib import Path

from analyzer_core.mythic_dungeon_timeline import (
    _fill_unique_enemy_instances,
    build_skyreach_document,
    format_clock,
)
from analyzer_core.mythic_dungeon_configs import dungeon_config


ROOT = Path(__file__).resolve().parents[1]


def event(timestamp, event_type, ability_id, source_id, target_id=0, **extra):
    return {
        "timestamp": timestamp,
        "type": event_type,
        "abilityGameID": ability_id,
        "sourceID": source_id,
        "targetID": target_id,
        **extra,
    }


def build(**overrides):
    report = {"title": "test"}
    fight = {
        "id": 2,
        "name": "Skyreach",
        "startTime": 900,
        "endTime": 11_000,
        "keystoneTime": 10_000,
        "keystoneLevel": 24,
        "kill": True,
        "friendlyPlayers": [1, 2, 3],
        "dungeonPulls": [
            {
                "id": 1,
                "name": "Trash",
                "encounterID": 0,
                "kill": False,
                "startTime": 1_100,
                "endTime": 5_000,
                "enemyNPCs": [{"id": 10, "gameID": 100, "minimumInstanceID": 1, "maximumInstanceID": 2}],
            },
            {
                "id": 2,
                "name": "Artifact",
                "encounterID": 0,
                "kill": False,
                "startTime": 5_001,
                "endTime": 5_010,
                "enemyNPCs": [],
            },
            {
                "id": 3,
                "name": "Ranjit",
                "encounterID": 1698,
                "kill": True,
                "startTime": 6_000,
                "endTime": 10_500,
                "enemyNPCs": [{"id": 11, "gameID": 101, "minimumInstanceID": 1, "maximumInstanceID": 1}],
            },
        ],
    }
    inputs = {
        "report_code": "abc",
        "report": report,
        "fight": fight,
        "actors_original": [
            {"id": 1, "name": "Tank", "type": "Druid"},
            {"id": 2, "name": "Healer", "type": "Monk"},
            {"id": 3, "name": "DPS", "type": "DemonHunter"},
            {"id": 10, "name": "Mob", "type": "NPC", "gameID": 100},
            {"id": 11, "name": "Ranjit", "type": "NPC", "gameID": 101},
        ],
        "actors_localized": [],
        "abilities_original": [
            {"id": 1254380, "name": "Shear"},
            {"id": 22812, "name": "Barkskin"},
            {"id": 116849, "name": "Life Cocoon"},
            {"id": 1225789, "name": "Void Metamorphosis"},
            {"id": 1253538, "name": "Scorching Ray"},
        ],
        "player_details": {
            "tanks": [{"id": 1, "name": "Tank", "type": "Druid", "specs": [{"spec": "Guardian", "count": 1}]}],
            "healers": [{"id": 2, "name": "Healer", "type": "Monk", "specs": [{"spec": "Mistweaver", "count": 1}]}],
            "dps": [{"id": 3, "name": "DPS", "type": "DemonHunter", "specs": [{"spec": "Devourer", "count": 1}]}],
        },
        "hostile_casts": [
            event(1_400, "begincast", 1254380, 10, 1, sourceInstance=1),
            event(1_700, "cast", 1254380, 10, 1, sourceInstance=1),
            event(7_000, "cast", 1253538, 11),
        ],
        "friendly_casts": [
            event(1_200, "cast", 22812, 1, 1),
            event(1_300, "cast", 116849, 2, 1),
            event(1_350, "begincast", 116849, 2, 1),
        ],
        "friendly_damage": [event(1_150, "damage", 1, 1, 10, targetInstance=1)],
        "hostile_deaths": [event(4_600, "death", 0, -1, 10, targetInstance=1)],
        "void_meta_buffs": [
            event(1_450, "applybuff", 1225789, 3, 3),
            event(1_500, "removebuff", 1225789, 3, 3),
        ],
        "scorching_ray_debuffs": [
            event(7_000, "applydebuff", 1253541, 11, 1),
            event(7_000, "applydebuff", 1253541, 11, 2),
            event(7_000, "applydebuff", 1253541, 11, 3),
        ],
    }
    inputs.update(overrides)
    return build_skyreach_document(**inputs)


def test_uses_wcl_clock_and_discards_tiny_artifact_pull():
    document = build()
    assert document["dungeon"]["durationMs"] == 10_100
    assert document["dungeon"]["keystoneTimeMs"] == 10_000
    assert len(document["pulls"]) == 2
    assert document["pulls"][0]["dungeonTime"] == "00:00.2"


def test_enemy_only_begincast_player_only_cast_and_target_rules():
    timeline = build()["pulls"][0]["timeline"]
    assert [row["kind"] for row in timeline].count("enemyBeginCast") == 1
    assert [row["kind"] for row in timeline].count("playerCast") == 2
    barkskin = next(row for row in timeline if row["ability"]["id"] == 22812)
    cocoon = next(row for row in timeline if row["ability"]["id"] == 116849)
    assert barkskin["target"] is None
    assert cocoon["target"]["name"] == "Tank"
    enemy_cast = next(row for row in timeline if row["kind"] == "enemyBeginCast")
    assert enemy_cast["source"]["instance"] == 1


def test_void_metamorphosis_is_reconstructed_from_counter_remove():
    state = next(row for row in build()["pulls"][0]["timeline"] if row["kind"] == "playerState")
    assert state["ability"]["id"] == 1225789
    assert state["synthetic"] is True
    assert state["target"] is None
    assert state["eventType"] == "removebuff"


def test_instant_enemy_cast_uses_linked_debuff_targets():
    event_row = next(row for row in build()["pulls"][1]["timeline"] if row["ability"]["id"] == 1253538)
    assert event_row["eventType"] == "cast"
    assert [target["name"] for target in event_row["targets"]] == ["Tank", "Healer", "DPS"]
    assert "instance" not in event_row["source"]


def test_targetless_begincast_links_targets_from_its_completed_cast_and_ignores_pets():
    document = build(
        config={
            "key": "test",
            "officialNameZh": "测试副本",
            "enemyAbilities": {1254380: "无目标点名"},
            "linkedTargetCasts": {
                1254380: {
                    "displayEventType": "begincast",
                    "targetEventType": "cast",
                    "targetAuraId": 999001,
                    "toleranceMs": 100,
                },
            },
        },
        hostile_casts=[
            event(1_400, "begincast", 1254380, 10, sourceInstance=1),
            event(1_700, "cast", 1254380, 10, sourceInstance=1),
        ],
        linked_target_events={
            999001: [
                event(1_750, "applydebuff", 999001, 10, 1),
                event(1_750, "applydebuff", 999001, 10, 99),
            ],
        },
        scorching_ray_debuffs=None,
    )
    rows = [row for row in document["pulls"][0]["timeline"] if row["ability"]["id"] == 1254380]
    assert len(rows) == 1
    assert rows[0]["eventType"] == "begincast"
    assert [target["name"] for target in rows[0]["targets"]] == ["Tank"]


def test_linked_cast_can_require_a_completed_anchor_and_keep_primary_plus_bounce_targets():
    document = build(
        config={
            "key": "test",
            "officialNameZh": "测试副本",
            "enemyAbilities": {900001: "双目标技能"},
            "linkedTargetCasts": {
                900001: {
                    "displayEventType": "begincast",
                    "targetEventType": "cast",
                    "targetAuraId": 900002,
                    "toleranceMs": 100,
                    "requireAnchor": True,
                    "includeAnchorTarget": True,
                },
            },
        },
        hostile_casts=[
            event(7_000, "begincast", 900001, 11),
            event(7_500, "cast", 900001, 11, 1),
            event(8_000, "begincast", 900001, 11),
        ],
        linked_target_events={
            900002: [
                event(7_550, "applydebuff", 900002, 11, 1),
                event(7_550, "applydebuff", 900002, 11, 2),
            ],
        },
        scorching_ray_debuffs=None,
    )
    rows = [row for row in document["pulls"][1]["timeline"] if row["ability"]["id"] == 900001]
    assert len(rows) == 1
    assert [target["name"] for target in rows[0]["targets"]] == ["Tank", "Healer"]


def test_aura_driven_synthetic_channel_keeps_its_fade_duration():
    document = build(
        config={
            "key": "test",
            "officialNameZh": "测试副本",
            "enemyAbilities": {900010: "引导"},
            "syntheticEnemyCasts": [{
                "trigger": "aura",
                "triggerAbilityId": 900011,
                "triggerEventType": "applybuff",
                "endEventType": "removebuff",
                "abilityId": 900010,
                "name": "引导",
                "evidence": "光环获得→消失",
            }],
        },
        hostile_casts=[],
        synthetic_events={
            900011: [
                event(7_000, "applybuff", 900011, 11, 11),
                event(9_400, "removebuff", 900011, 11, 11),
            ],
        },
        scorching_ray_debuffs=None,
    )
    row = next(row for row in document["pulls"][1]["timeline"] if row["ability"]["id"] == 900010)
    assert row["synthetic"] is True
    assert row["durationMs"] == 2_400
    assert row["duration"] == "00:02.4"
    assert row["syntheticEvidence"] == "光环获得→消失"


def test_boss_repeats_are_numbered_and_crawth_screeches_reset_per_phase():
    document = build(
        config={
            "key": "algethar_academy",
            "officialNameZh": "艾杰斯亚学院",
            "enemyAbilities": {1276752: "毁灭之风", 377004: "震耳尖啸"},
        },
        hostile_casts=[
            event(6_500, "begincast", 1276752, 11),
            event(7_000, "begincast", 377004, 11),
            event(7_500, "begincast", 377004, 11),
            event(8_000, "begincast", 1276752, 11),
            event(8_500, "begincast", 377004, 11),
        ],
        scorching_ray_debuffs=None,
    )
    names = [row["ability"]["name"] for row in document["pulls"][1]["timeline"]]
    assert names == [
        "毁灭之风1",
        "风阶段 震耳尖啸1",
        "风阶段 震耳尖啸2",
        "毁灭之风2",
        "火阶段 震耳尖啸1",
    ]


def test_enemy_instances_and_openers_are_preserved():
    enemies = build()["pulls"][0]["enemies"]
    assert [row["instance"] for row in enemies] == [1, 2]
    assert enemies[0]["opener"]["player"]["name"] == "Tank"
    assert enemies[1]["opener"] is None


def test_opener_evidence_uses_localized_ability_name_instead_of_spell_id():
    document = build(
        config={
            "key": "test",
            "officialNameZh": "测试副本",
            "enemyAbilities": {},
            "abilityTranslations": {6795: "低吼"},
        },
        friendly_damage=[event(1_150, "damage", 6795, 1, 10, targetInstance=1)],
    )
    opener = document["pulls"][0]["enemies"][0]["opener"]
    assert opener["abilityId"] == 6795
    assert opener["abilityName"] == "低吼"


def test_current_breath_of_eons_id_is_kept_in_boss_timeline():
    document = build(
        friendly_casts=[event(7_000, "cast", 403631, 3)],
        scorching_ray_debuffs=None,
    )
    row = next(row for row in document["pulls"][1]["timeline"] if row["ability"]["id"] == 403631)
    assert row["ability"]["name"] == "亘古吐息"


def test_consumable_bursts_and_evoker_bloodlust_are_kept():
    document = build(
        friendly_casts=[
            event(7_000, "cast", 1236616, 1),
            event(7_100, "cast", 1236994, 2),
            event(7_200, "cast", 390386, 3),
        ],
        scorching_ray_debuffs=None,
    )
    rows = [
        row for row in document["pulls"][1]["timeline"]
        if row["ability"]["id"] in {1236616, 1236994, 390386}
    ]
    assert [row["ability"]["name"] for row in rows] == ["圣光潜力", "鲁莽药水", "守护巨龙之怒"]
    assert rows[-1]["scope"] == "party"


def test_successful_enemy_cast_can_link_its_tank_target_from_damage():
    document = build(
        config={
            "key": "seat_of_the_triumvirate",
            "officialNameZh": "执政团之座",
            "enemyAbilities": {1263440: "虚空挥砍"},
            "linkedTargetCasts": {
                1263440: {
                    "displayEventType": "cast",
                    "targetAuraId": 1263494,
                    "targetAuraEventType": "damage",
                    "toleranceMs": 1800,
                },
            },
        },
        hostile_casts=[event(7_000, "cast", 1263440, 11, -1)],
        linked_target_events={
            1263494: [event(8_500, "damage", 1263494, 11, 1)],
        },
        scorching_ray_debuffs=None,
    )
    row = document["pulls"][1]["timeline"][0]
    assert row["ability"]["name"] == "虚空挥砍"
    assert [target["name"] for target in row["targets"]] == ["Tank"]


def test_completed_boss_pull_restores_missing_death_at_pull_end():
    boss = build()["pulls"][1]
    enemy = next(row for row in boss["enemies"] if row.get("isBoss"))
    assert enemy["death"]["timestamp"] == boss["endTime"]
    assert enemy["death"]["synthetic"] is True
    assert enemy["death"]["evidence"] == "bossPullEnd"
    assert enemy["survivalMs"] == boss["durationMs"]
    assert enemy["label"] == enemy["name"]


def test_synchronized_clone_casts_collapse_to_one_numbered_round():
    document = build(
        config={
            "key": "test",
            "officialNameZh": "测试副本",
            "enemyAbilities": {900020: "复制技能"},
            "bossCastRoundRules": [{
                "pullOriginalName": "Ranjit",
                "sourceOriginalName": "Ranjit",
                "abilityIds": [900020],
                "windowMs": 100,
            }],
        },
        hostile_casts=[
            event(7_000, "begincast", 900020, 11),
            event(7_040, "begincast", 900020, 11, sourceInstance=1),
            event(7_080, "begincast", 900020, 11, sourceInstance=2),
            event(8_000, "begincast", 900020, 11),
            event(8_040, "begincast", 900020, 11, sourceInstance=1),
            event(8_080, "begincast", 900020, 11, sourceInstance=2),
        ],
        scorching_ray_debuffs=None,
    )
    rows = [row for row in document["pulls"][1]["timeline"] if row["ability"]["id"] == 900020]
    assert [row["ability"]["name"] for row in rows] == ["复制技能1", "复制技能2"]
    assert [row["roundCastCount"] for row in rows] == [3, 3]
    assert all(row["roundLabel"] == "本体+2复制体" for row in rows)


def test_boss_is_not_numbered_as_instance_but_its_summon_is():
    timeline = [{
        "source": {"id": 11, "name": "Boss", "type": "NPC"},
        "target": {"id": 12, "name": "Summon", "type": "NPC"},
        "targets": [],
    }]
    enemies = [{"id": 11, "name": "Boss", "instance": 1}]
    _fill_unique_enemy_instances(
        timeline,
        enemies,
        excluded_actor_ids={11},
        number_unknown_npcs=True,
    )
    assert "instance" not in timeline[0]["source"]
    assert timeline[0]["target"]["instance"] == 1


def test_enemy_instances_are_time_sorted_and_include_death_survival():
    document = build(
        friendly_damage=[
            event(1_800, "damage", 1, 1, 10, targetInstance=1),
            event(1_200, "damage", 1, 2, 10, targetInstance=2),
        ],
        hostile_deaths=[
            event(4_600, "death", 0, -1, 10, targetInstance=1),
            event(3_200, "death", 0, -1, 10, targetInstance=2),
        ],
    )
    enemies = document["pulls"][0]["enemies"]
    assert [row["instance"] for row in enemies] == [2, 1]
    assert enemies[0]["death"]["pullTime"] == "00:02.1"
    assert enemies[0]["survival"] == "00:02.0"
    assert enemies[1]["death"]["pullTime"] == "00:03.5"
    assert enemies[1]["survival"] == "00:03.2"


def test_clock_format_is_tenths():
    assert format_clock(197_849) == "03:17.8"


def test_pit_of_saron_tracks_tyrannus_bone_infusion():
    assert dungeon_config("pit_of_saron")["enemyAbilities"][1276648] == "骸骨灌注"


def test_requested_boss_spell_ids_are_configured_with_observed_corrections():
    assert dungeon_config("nexus_point_xenas")["enemyAbilities"][1253950] == "灼热撕裂"
    assert dungeon_config("windrunner_spire")["enemyAbilities"][467040] == "燃烧烈风"
    maisara = dungeon_config("maisara_caverns")
    assert maisara["enemyAbilities"][1249478] == "腐肉飞扑"
    assert maisara["enemyAbilities"][1252676] == "粉碎灵魂"
    assert maisara["enemyAbilities"][1251023] == "碎魂者"
    assert maisara["enemyAbilities"][1253788] == "裂魂咆哮"
    magisters = dungeon_config("magisters_terrace")
    assert magisters["enemyAbilities"][1264687] == "吞噬打击"
    assert magisters["enemyAbilities"][1248138] == "虚空炸弹"
    assert magisters["enemyAbilities"][1265977] == "吞噬暗影"


def test_stable_sample_manifest_covers_the_season_pool():
    manifest = json.loads((ROOT / "assets" / "samples" / "mythic_dungeon_manifest.json").read_text(encoding="utf-8"))
    samples = {row["key"]: row for row in manifest["samples"]}
    assert len(samples) == 8
    assert samples["skyreach"]["reportCode"] == "xpYfcXrBnkP8W1Ka"
    assert samples["skyreach"]["keystoneLevel"] == 24
    assert samples["algethar_academy"]["keystoneLevel"] == 24
    assert samples["seat_of_the_triumvirate"]["keystoneLevel"] == 24
    assert all(row["keystoneLevel"] == 25 for key, row in samples.items() if key not in {
        "skyreach", "algethar_academy", "seat_of_the_triumvirate",
    })


def test_stable_sample_files_match_manifest_contract():
    manifest = json.loads((ROOT / "assets" / "samples" / "mythic_dungeon_manifest.json").read_text(encoding="utf-8"))
    for sample in manifest["samples"]:
        document = json.loads((ROOT / sample["file"].lstrip("/")).read_text(encoding="utf-8"))
        assert document["kind"] == "mythic-dungeon-route-timeline"
        assert document["dungeon"]["completed"] is True
        assert document["dungeon"]["keystoneLevel"] == sample["keystoneLevel"]
        assert document["source"]["reportCode"] == sample["reportCode"]
        assert document["pulls"]
