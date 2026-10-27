import json
from copy import deepcopy
from unittest.mock import Mock

import pytest

from analyzer_core.analysis_profile import resolve_profile
from analyzer_core.config import resolve_analysis_options
from boss_plugins.venomous_abyss import coiledaltar as m7, twinfangs as m6, sszorak as m5


def setup(p1_end=170000, duration=240000):
    fight = dict(startTime=1000000, endTime=1000000+duration, difficulty=5)
    actors = [dict(id=90, gameID=257911), dict(id=91, gameID=259854), dict(id=20, petOwner=1)]
    players = {1: dict(id=1, name="Warrior", role="melee-dps")}
    markers = [dict(key="p1", timeMs=0), dict(key="p2", timeMs=p1_end), dict(key="wipe", timeMs=duration)]
    options = resolve_analysis_options(m7.CONFIG_SCHEMA, {})
    options["burstPlan"] = json.dumps([dict(player="Warrior", ability="warrior.avatar", times=[0, 180])])
    raw = {"reportGuild": {"id": 774422}, "casts": [], "guildPlayerCasts": [],
           "guildPlayerBuffs": [], "guildBossDamage": [], "enemyDeaths": []}
    def event(t, kind="damage", **kwargs):
        return dict(timestamp=1000000+t, type=kind, **kwargs)
    raw["casts"] = [event(162043, "cast", abilityGameID=next(iter(m7.SEVER_IDS)), sourceID=90)]
    if duration >= 185000:
        raw["casts"].append(event(185000, "begincast", abilityGameID=next(iter(m7.DREADMARCH_CAST_IDS)), sourceID=91))
    return fight, markers, raw, actors, players, options, event


def analyze(fixture):
    fight, markers, raw, actors, players, options, _ = fixture
    return m7.analyze_guild_timeline(fight, markers, raw, actors, {}, players, options)


def test_profile_uses_report_id_not_spoofable_name_and_base_can_be_selected():
    assert resolve_profile({"id":774422})["key"] == "avalon"
    assert resolve_profile({"id":1, "name":"阿瓦隆"})["key"] == "base"
    assert resolve_profile()["key"] == "base"
    assert resolve_profile({"id":774422}, {"analysisProfile":"base"})["key"] == "base"


def test_early_phase_skips_all_burst_counts_and_pet_casts_but_keeps_pet_damage():
    fixture = setup(150000)
    _, _, raw, _, _, _, event = fixture
    raw["guildBossDamage"] = [
        event(145000, sourceID=1, targetID=90, amount=100, resourceActor=2, hitPoints=400, maxHitPoints=10000),
        event(145010, sourceID=20, targetID=90, amount=50),
        event(145020, sourceID=1, targetID=91, amount=9999),
    ]
    raw["guildPlayerCasts"] = [event(145000, "cast", sourceID=1, targetID=90, abilityGameID=1),
                               event(145005, "cast", sourceID=20, targetID=90, abilityGameID=2)]
    result = analyze(fixture)
    assert result["burstSkipped"] and result["count"] == 0
    phase = result["phaseControl"][0]
    assert phase["status"] == "early"
    row = phase["thresholds"]["5"][0]
    assert (row["castCount"], row["damage"], row["petDamage"]) == (1, 150, 50)
    assert not phase["thresholds"]["4"]  # Strictly below, not <= threshold.
    assert phase["thresholds"]["10"][0]["castCount"] == 1


def test_early_trigger_beats_later_phase_marker():
    fixture = setup()
    *_, event = fixture
    fixture[2]["guildBossDamage"] = [event(150000, targetID=90, sourceID=1, amount=10,
        targetResources={"hitPoints":1,"maxHitPoints":10000})]
    phase = analyze(fixture)["phaseControl"][0]
    assert phase["status"] == "early" and phase["endTimeMs"] == 150000


def test_p1_window_starts_at_observed_crossing_without_using_player_or_future_hp():
    fixture = setup(150000)
    raw, event = fixture[2], fixture[-1]
    raw["guildBossDamage"] = [event(140000, sourceID=1, targetID=90, amount=30,
        sourceResources={"hitPoints":1,"maxHitPoints":100}, targetResources={"hitPoints":400,"maxHitPoints":10000})]
    raw["guildPlayerCasts"] = [event(t, "cast", sourceID=1, targetID=90, abilityGameID=1)
                               for t in [139999, 140000, 143001]]
    row = analyze(fixture)["phaseControl"][0]["thresholds"]["5"][0]
    assert row["castCount"] == 2
    assert [c["timeMs"] for c in row["casts"]] == [140000,143001]


def test_on_time_counts_missing_window_shifts_p2_and_matches_cast_once():
    fixture = setup()
    raw, event = fixture[2], fixture[-1]
    raw["guildPlayerCasts"] = [event(0, "cast", sourceID=1, abilityGameID=107574)]
    result = analyze(fixture)
    assert not result["burstSkipped"] and result["count"] == 1
    row = result["checks"][1]
    assert row["startTimeMs"] == 160000 and row["endTimeMs"] == 180000
    assert row["previousCastTimeMs"] == 0 and row["status"] == "missing"


def test_never_count_unfinished_window_missing_blade_or_unreached_p3():
    fixture = setup(duration=175000)
    assert analyze(fixture)["count"] == 0  # First Dreadmarch has not confirmed alignment.
    assert analyze(fixture)["checks"][1]["status"] == "not-reached"
    fixture[2]["casts"] = []
    assert analyze(fixture)["burstSkipped"] and analyze(fixture)["count"] == 0
    fixture = setup(duration=600000)
    fixture[5]["burstPlan"] = json.dumps([dict(player="Warrior", ability="warrior.avatar", times=[469])])
    assert analyze(fixture)["checks"][0]["status"] == "not-reached"
    assert analyze(fixture)["count"] == 0


def test_p1_blade_at_242_does_not_allow_death_before_250_and_first_march_must_wait_until_305():
    fixture = setup(p1_end=165000)
    result = analyze(fixture)
    assert result["phaseControl"][0]["earliestEndTimeMs"] == 170000
    assert result["phaseControl"][0]["requiredBladeTimeMs"] == 162043
    assert result["phaseControl"][0]["status"] == "early" and result["burstSkipped"]
    fixture = setup(p1_end=171000)
    fixture[2]["casts"][-1]["timestamp"] = 1184999
    result = analyze(fixture)
    assert result["phaseControl"][0]["status"] == "early" and result["burstSkipped"]
    assert "3:05" in result["phaseControl"][0]["reason"]
    fixture[2]["casts"][-1]["timestamp"] = 1185000
    assert analyze(fixture)["phaseControl"][0]["status"] == "on-time"
    fixture[2]["casts"][-1]["type"] = "cast"
    assert analyze(fixture)["phaseControl"][0]["status"] == "unknown"


def test_p2_deadline_tracks_actual_p2_start_and_early_p2_skips_bursts():
    fixture = setup(p1_end=180000, duration=500000)
    fixture[1].insert(2, dict(key="intermission", timeMs=380000))
    result = analyze(fixture)
    assert result["phaseControl"][1]["earliestEndTimeMs"] == 382790
    assert result["phaseControl"][1]["status"] == "early"
    assert result["count"] == 0 and result["burstSkipped"]


def test_actual_delayed_last_blade_and_buff_refresh_duration():
    fixture = setup(p1_end=175000)
    raw, event = fixture[2], fixture[-1]
    raw["casts"][0]["timestamp"] = 1170000
    raw["guildPlayerBuffs"] = [event(t, kind, targetID=1, abilityGameID=107574)
        for t, kind in [(1000,"applybuff"),(5000,"refreshbuff"),(21000,"removebuff")]]
    result = analyze(fixture)
    assert result["phaseControl"][0]["earliestEndTimeMs"] == 170000
    assert result["timelines"][0]["intervals"] == [dict(startTimeMs=1000,endTimeMs=21000,evidence="aura")]


def test_base_profile_has_no_extra_requests_or_guild_counts():
    fixture = setup()
    fixture[2]["reportGuild"] = {"id":1}
    client = Mock()
    assert analyze(fixture)["enabled"] and not analyze(fixture)["checksEnabled"]
    assert m7._fetch_guild_timeline(client,"R",fixture[0],fixture[3],fixture[2],fixture[5]) is fixture[2]
    assert client.events.call_count == 1
    assert client.events.call_args.args[1] == "Casts"


def test_damage_transport_uses_npc_game_ids_and_does_not_filter_enemy_targets_as_friendlies():
    fixture = setup()
    client = Mock()
    client.events.return_value = []
    m7._fetch_guild_timeline(client,"R",fixture[0],fixture[3],fixture[2],fixture[5])
    damage = client.events.call_args_list[0]
    assert damage.args[1] == "DamageDone"
    assert damage.kwargs["filter_expression"] == "target.id IN (257911, 259854)"
    assert "hostility_type" not in damage.kwargs
    assert client.events.call_count == 3


def test_p2_first_blade_delay_moves_required_final_blade():
    fixture = setup(p1_end=180000,duration=450000)
    fixture[1].insert(2,dict(key="intermission",timeMs=390000))
    fixture[2]["casts"].append(fixture[-1](226895,"cast",abilityGameID=next(iter(m7.SOUL_SEVER_IDS))))
    result = analyze(fixture)
    phase = result["phaseControl"][1]
    assert phase["bladeDriftMs"] == 14123
    assert phase["earliestEndTimeMs"] == 396913
    assert phase["status"] == "early"


def test_custom_trinket_missing_player_and_bad_configuration():
    fixture = setup()
    fixture[5]["burstPlan"] = json.dumps([dict(player="Warrior",spellIDs=[12345],label="指定饰品",times=[0])])
    assert analyze(fixture)["checks"][0]["counted"]
    fixture[5]["burstPlan"] = json.dumps([dict(player="Absent",ability="warrior.avatar",times=[0])])
    assert analyze(fixture)["count"] == 0 and analyze(fixture)["unresolved"]
    for value in ('{}','[{}]','[{"player":"A","ability":"x","times":[[20,10]]}]'):
        with pytest.raises(ValueError):
            m7.burst_plan({"burstPlan":value})


def test_potion_after_actual_vulnerability_ends_is_not_counted():
    fight, markers, raw, actors, players, options, event = setup()
    buffs = [event(100000,"applybuff",abilityGameID=m7.INTERMISSION_SOULBIND,targetID=91),
             event(135000,"removebuff",abilityGameID=m7.INTERMISSION_SOULBIND,targetID=91)]
    result = m7.analyze_intermission(fight,buffs,[],[],{},players,markers,
        friendly_casts=[event(136000,"cast",abilityGameID=m7.POTION_RECKLESSNESS,sourceID=1)])
    assert result["potionUsedCount"] == 0
    result = m7.analyze_intermission(fight,buffs,[],[],{},players,markers,
        friendly_casts=[event(99000,"cast",abilityGameID=m7.POTION_RECKLESSNESS,sourceID=1)])
    assert result["potionUsedCount"] == 1
    assert result["survivors"][0]["potionPrecast"]
    assert not result["survivors"][0]["potionDuringVulnerability"]


def test_m6_no_assignment_does_not_infer_tank_duty_and_foreign_guild_ignores_preset():
    from tests.test_twinfangs_mythic import fixture as twin_fixture, options, event
    fight, actors, players, raw = twin_fixture()
    raw["casts"] = [event(1000,1308356,sourceID=90),event(2000,1308385,sourceID=99,x=-608,y=69221,resourceActor=1)]
    for guild in ({"id":1},{"id":774422}):
        raw["reportGuild"] = guild
        result = m6._brood_review(fight, actors, players, raw, options())
        assert not result["assignmentEnabled"]
        assert not result["replayEvents"][0].get("responsiblePlayers")
    raw["reportGuild"] = {"id":1}
    _, actors, players, raw2, opt = __import__('tests.test_twinfangs_mythic',fromlist=['feast_setup']).feast_setup()
    raw2["reportGuild"] = {"id":1}
    assert m6._feast_review(fight,actors,players,raw2,opt)["strategy"] == "normal"


def test_arcane_surge_uses_separate_self_buff_and_only_successful_cast():
    fixture=setup()
    raw,event=fixture[2],fixture[-1]
    fixture[5]['burstPlan']=json.dumps([dict(player='Warrior',ability='mage.arcane-surge',times=[10])])
    raw['guildPlayerCasts']=[event(7000,'begincast',sourceID=1,abilityGameID=365350),event(10000,'cast',sourceID=1,abilityGameID=365350)]
    raw['guildPlayerBuffs']=[event(10000,'applybuff',sourceID=1,targetID=1,abilityGameID=365362),event(27400,'removebuff',sourceID=1,targetID=1,abilityGameID=365362)]
    result=analyze(fixture)
    assert result['timelines'][0]['casts']==[10000]
    assert result['timelines'][0]['intervals']==[dict(startTimeMs=10000,endTimeMs=27400,evidence='aura')]
    assert result['checks'][0]['status']=='used'


def test_breath_tracks_enemy_debuffs_by_caster_target_and_instance_not_flight_buff():
    fixture=setup()
    raw,event=fixture[2],fixture[-1]
    fixture[5]['burstPlan']=json.dumps([dict(player='Warrior',ability='evoker.breath-of-eons',times=[0])])
    raw['guildPlayerBuffs']=[event(0,'applybuff',targetID=1,abilityGameID=403631),event(2000,'removebuff',targetID=1,abilityGameID=403631)]
    raw['guildEnemyDebuffs']=[event(t,kind,sourceID=source,targetID=target,targetInstance=instance,abilityGameID=sid)
        for t,kind,source,target,instance,sid in [
            (1000,'applydebuff',1,90,1,409560),(1200,'applydebuff',1,90,1,409722),
            (14000,'removedebuff',1,90,1,409560),(14020,'removedebuff',1,90,1,409722),
            (2000,'applydebuff',2,90,1,409560),(16000,'removedebuff',2,90,1,409560),
            (3000,'applydebuff',1,91,1,409560),(9000,'removedebuff',1,91,1,409560),
            (4000,'applydebuff',1,90,2,409560),(10000,'removedebuff',1,90,2,409560)]]
    intervals=analyze(fixture)['timelines'][0]['intervals']
    assert [(r['startTimeMs'],r['endTimeMs'],r['targetID'],r['targetInstance']) for r in intervals]==[(1000,14020,90,1),(3000,9000,91,1),(4000,10000,90,2)]
    assert intervals[0]['auraSpellIDs']==[409560,409722]
    assert all(r['evidence']=='enemy-debuff' for r in intervals)


def test_default_mage_ability_follows_this_fight_spec_and_healing_druid_is_exempt():
    fixture=setup()
    fixture[5]['burstPlan']=''
    fixture[4][1].update(name='三坑不二',localization={'class':{'enUS':'Mage'},'spec':{'enUS':'Arcane'}})
    result=analyze(fixture)
    assert result['timelines'][0]['ability']=='mage.arcane-surge'
    assert next(r for r in result['plan'] if r['player']=='三坑不二')['ability']=='mage.arcane-surge'
    fixture[4][1]['localization']['spec']['enUS']='Frost'
    assert analyze(fixture)['timelines'][0]['ability']=='mage.ray-of-frost'
    fixture[4][1].update(name='贪睡熊熊',localization={'class':{'enUS':'Druid'},'spec':{'enUS':'Restoration'}})
    result=analyze(fixture)
    assert not result['timelines'] and result['count']==0
    assert all('治疗' in r['reason'] for r in result['unresolved'] if r['player']=='贪睡熊熊')
    fixture[4][1]['localization']['spec']['enUS']='Balance'
    assert {r['ability'] for r in analyze(fixture)['timelines']}=={'druid.incarnation-balance','item.offensive-trinket'}


def test_damage_only_ray_does_not_invent_buff_duration_even_with_duration_configuration():
    fixture=setup()
    fixture[5]['burstPlan']=json.dumps([dict(player='Warrior',ability='mage.ray-of-frost',times=[0],durationSeconds=15)])
    event=fixture[-1]
    fixture[2]['guildPlayerCasts']=[event(0,'cast',sourceID=1,abilityGameID=205021)]
    fixture[2]['guildPlayerBuffs']=[event(0,'applybuff',targetID=1,abilityGameID=205021),event(15000,'removebuff',targetID=1,abilityGameID=205021)]
    row=analyze(fixture)['timelines'][0]
    assert row['casts']==[0] and row['intervals']==[] and row['effectKind']=='cast-only'


def test_phase_advance_distinguishes_local_early_finish_and_inherited_start_shift():
    fixture=setup(p1_end=160000,duration=450000)
    fixture[1].insert(2,dict(key='intermission',timeMs=350000))
    fixture[1].insert(3,dict(key='p3',timeMs=385000))
    timing={r['phase']:r for r in analyze(fixture)['phaseTimings']}
    assert timing['p1']['endAdvanceMs']==10000
    assert timing['p2']['startAdvanceMs']==20000
    assert timing['p2']['endAdvanceMs']==12790
    assert timing['p3']['startAdvanceMs']==45000


def test_enemy_aura_transport_is_one_bulk_filtered_stream():
    fixture=setup()
    fixture[5]['burstPlan']=json.dumps([dict(player='Warrior',ability='evoker.breath-of-eons',times=[0])])
    client=Mock();client.events.return_value=[]
    m7._fetch_guild_timeline(client,'R',fixture[0],fixture[3],fixture[2],fixture[5])
    assert client.events.call_count==4
    last=client.events.call_args_list[-1]
    assert last.args[1]=='All' and '409560, 409722' in last.kwargs['filter_expression']
    assert 'hostility_type' not in last.kwargs


def test_p1_hold_window_is_first_hp_crossing_until_245_excluding_legal_damage_after_release():
    fixture=setup(p1_end=169000)
    raw,event=fixture[2],fixture[-1]
    raw['guildBossDamage']=[event(t,sourceID=source,targetID=90,amount=damage,
        targetResources={'hitPoints':hp,'maxHitPoints':10000}) for t,source,damage,hp in [
            (159000,1,10,600),(160000,1,100,400),(161000,20,50,600),
            (164999,1,30,300),(165000,1,999,200),(166000,20,999,100)]]
    raw['guildPlayerCasts']=[event(t,'cast',sourceID=1,targetID=90,abilityGameID=1)
        for t in [159999,160000,161000,164999,165000,166000]]
    result=analyze(fixture);phase=result['phaseControl'][0];row=phase['thresholds']['5'][0]
    assert (row['castCount'],row['damage'],row['petDamage'])==(3,180,50)
    assert phase['thresholdWindows']['5']==dict(startTimeMs=160000,endTimeMs=165000,evidenceEndTimeMs=165000,endExclusive=True)
    assert phase['earliestEndTimeMs']==170000  # Separate, unchanged transition rule.
    assert phase['status']=='early' and result['burstSkipped']


def test_p1_no_hold_fault_when_hp_first_drops_below_threshold_after_245():
    fixture=setup(p1_end=169000);raw,event=fixture[2],fixture[-1]
    raw['guildBossDamage']=[event(166000,sourceID=1,targetID=90,amount=100,
        targetResources={'hitPoints':400,'maxHitPoints':10000})]
    raw['guildPlayerCasts']=[event(166000,'cast',sourceID=1,targetID=90,abilityGameID=1)]
    phase=analyze(fixture)['phaseControl'][0]
    assert phase['thresholds']['5']==[] and phase['thresholdWindows']['5']['startTimeMs'] is None


def comparison_fixture():
    fight=dict(startTime=1000000,endTime=1640000)
    def event(t,sid,kind='cast',source=90):
        return dict(timestamp=1000000+t,abilityGameID=sid,type=kind,sourceID=source,targetID=source)
    buffs=[event(178000,1288624,'applybuff'),event(389000,1304028,'applybuff'),event(427000,1289798,'applybuff')]
    return fight,buffs,event


def test_comparison_uses_aura_boundaries_not_first_fear_bolt():
    fight,buffs,event=comparison_fixture()
    r=m7.build_timeline_comparison_evidence(fight,[event(183000,1307184)],buffs)
    assert [(p['key'],p['timeMs']) for p in r['phaseTimeline']]==[('p1',0),('p2',178000),('intermission',389000),('p3',427000)]
    bind=next(e for e in r['events'] if e['key']=='bind')
    assert (bind['timeMs'],bind['endTimeMs'])==(389000,427000)


def test_comparison_deduplicates_cast_completion_and_grim_start_alias():
    fight,buffs,event=comparison_fixture()
    raw=[event(20000,1299684,'begincast'),event(23000,1299684),
         event(447000,1299266),event(447005,1299267,'begincast'),event(450500,1299267)]
    r=m7.build_timeline_comparison_evidence(fight,raw,buffs)
    assert r['counts']['sever']==1 and r['counts']['grim']==1
    assert next(e['timeMs'] for e in r['events'] if e['key']=='grim')==447000


def test_comparison_retains_nightfall_starts_and_filters_gloom_in_p3():
    fight,buffs,event=comparison_fixture()
    raw=[event(196000,1310882,'begincast'),event(198000,1310882),
         event(248000,1286918,'begincast'),event(468000,1286918,'begincast'),
         event(470000,1310882,'begincast'),event(472000,1310882)]
    r=m7.build_timeline_comparison_evidence(fight,raw,buffs)
    assert r['counts']['night']==2 and r['counts']['gloom']==1
    assert all(e['endTimeMs']==e['timeMs'] for e in r['events'] if e['key']=='night')


def test_comparison_does_not_merge_repeated_instant_casts():
    fight,buffs,event=comparison_fixture()
    r=m7.build_timeline_comparison_evidence(fight,[event(200000,1286441),event(220000,1286441)],buffs)
    assert r['counts']['cackle']==2


def test_icon_evidence_shows_all_observed_bursts_without_planned_markers():
    fixture=setup();raw,event=fixture[2],fixture[-1]
    raw['guildPlayerCasts']=[event(3000,'cast',sourceID=1,abilityGameID=107574),
                            event(5000,'cast',sourceID=1,abilityGameID=1250533),
                            event(6000,'cast',sourceID=1,abilityGameID=395152)]
    result=analyze(fixture)
    rows=result['displayTimelines']
    assert {r['ability'] for r in rows}=={'warrior.avatar','item.1250533','evoker.ebon-might'}
    assert next(r for r in rows if r['ability']=='item.1250533')['plannedWindows']==[]
    avatar=next(r for r in rows if r['ability']=='warrior.avatar')
    assert avatar['plannedWindows']==[]
    assert result['checksEnabled'] and result['actualOnly']
    assert result['timelineViewVersion']=='icons-v1'
    assert result['reference']['p2TimeMs']==177991
