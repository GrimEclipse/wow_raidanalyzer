import math
from datetime import datetime, timezone, timedelta

import pytest
from boss_plugins.venomous_abyss import coiledaltar as boss


def fight(day=13, difficulty=5, start=0):
    epoch=int(datetime(2026,10,day,tzinfo=timezone(timedelta(hours=8))).timestamp()*1000)
    return {'startTime':start,'endTime':start+60000,'reportStartTime':epoch,'difficulty':difficulty}


def test_rule_version_depends_on_encounter_date_not_when_analysis_runs():
    before=boss.encounter_tuning(fight(12))
    after=boss.encounter_tuning(fight(13))
    assert [before[k] for k in ['p1InitialOrbCount','p1MutationCount','dreadmarchTargetCount','mutationRadiusYards','nightfallCastMs']]==[10,5,4,8,15000]
    assert [after[k] for k in ['p1InitialOrbCount','p1MutationCount','dreadmarchTargetCount','mutationRadiusYards','nightfallCastMs']]==[8,4,3,6,17000]
    assert not before['manifestDespawnOnTargetDeath'] and after['manifestDespawnOnTargetDeath']
    assert after['manifestWatchHalfAngleDegrees']-before['manifestWatchHalfAngleDegrees']==10
    assert boss.encounter_tuning(fight(12,start=86400000))['key']=='2026-10-13'
    assert boss.encounter_tuning({'startTime':0,'difficulty':5})['mutationRadiusYards']==8


@pytest.mark.parametrize('difficulty',[3,4,5])
def test_shared_nerfs_apply_at_every_difficulty(difficulty):
    rule=boss.encounter_tuning(fight(difficulty=difficulty))
    assert rule['nightfallCastMs']==17000
    assert rule['mutationRadiusYards']==6
    assert rule['manifestImmediateRedGlow']
    if difficulty!=5:
        assert rule['dreadmarchTargetCount'] is None


def test_eight_observed_orbs_are_not_padded_to_the_old_count_and_carry_radius_changes():
    casts=[dict(timestamp=100,type='cast',sourceID=8,abilityGameID=boss.TOXIC_DELUGE)]
    for i in range(8):
        casts.append(dict(timestamp=200+i,type='cast',sourceID=9,sourceInstance=i+1,
            abilityGameID=boss.COALESCED_VENOM_CAST if i<4 else boss.VIRULENT_MUTATION_CAST,
            sourceResources={'x':(i+1)*1000,'y':100}))
    for day,radius in [(12,8),(13,6)]:
        result=boss.analyze_toxic_deluge(fight(day),casts,[],{}, {},{},[{'key':'p1','timeMs':0}])
        assert result['rounds'][0]['spawnCount']==8
        assert result['rounds'][0]['mutationSpawnCount']==4
        assert result['virulentBlastRadiusYards']==radius
        purple=[s for s in result['rounds'][0]['spawns'] if s['venomKind']==boss.VENOM_KIND_MUTATION]
        assert all(s['blastRadiusYards']==radius for s in purple)


@pytest.mark.parametrize('instance',[None,1])
def test_new_ghost_despawns_at_player_death_without_retargeting_the_same_instance(instance):
    actor={9:'Manifestation of Dread',1:'A',2:'B'}
    players={1:{'name':'A'},2:{'name':'B'}}
    catalog=boss.build_actor_catalog([{'id':9,'name':actor[9],'gameID':boss.MANIFEST_NPC_GAME_ID,'type':'NPC'}])
    debuffs=[dict(timestamp=t,type='applydebuff',abilityGameID=boss.FIXATION,
        sourceID=9,sourceInstance=instance,targetID=pid) for t,pid in [(0,1),(1000,2)]]
    def analyze(day):
        return boss.analyze_manifestations(fight(day),debuffs,{},actor,players,catalog,
            [{'key':'p2','timeMs':0}],player_deaths=[{'timestamp':500,'targetID':1}])
    old=analyze(12)['fixations'];new=analyze(13)['fixations']
    assert len(old)==2
    assert len(new)==1
    assert new[0]['despawnTimeMs']==500
    assert new[0]['despawnReason']=='fixated-target-death'


def test_new_facing_threshold_stops_a_ghost_that_previously_walked():
    def replay(day):
        mechanics={'combatReplay':{'units':[dict(actorID=1,kind='player',
            samples=[[t,0,0] for t in range(0,2100,100)],
            facingSamples=[[t,math.radians(35)*100] for t in range(0,2100,100)])]},
            'manifestations':{'fixations':[dict(manifest={'sourceID':9,'sourceInstance':1},
                playerID=1,applyTimeMs=0,removeTimeMs=2000,despawnTimeMs=2000)]}}
        raw={'casts':[dict(type='cast',timestamp=0,sourceID=9,sourceInstance=1,
            abilityGameID=boss.FIXATION,sourceResources={'x':1000,'y':0})]}
        return boss._build_manifest_replay(fight(day),mechanics,raw,{1:{'name':'A'}},{1:'A'})
    assert replay(12)['ghosts'][0]['samples'][-1][1]<1000
    assert replay(13)['ghosts'][0]['samples'][-1][1]==1000
    assert replay(13)['immediateRedGlow']


def test_new_nightfall_keeps_actual_interrupt_boundary_inside_a_seventeen_second_cast():
    mechanics={'combatReplay':{'bosses':[{'actorID':9,'casts':[]}]}}
    rows=[dict(type='begincast',timestamp=0,sourceID=9,abilityGameID=boss.ETERNAL_NIGHTFALL),
          dict(type='interrupt',timestamp=16000,sourceID=1,targetID=9,
               abilityGameID=6552,extraAbilityGameID=boss.ETERNAL_NIGHTFALL)]
    boss._apply_altar_nightfall_replay(fight(),mechanics,{'replayEvents':rows},{1:{'name':'A'}},{1:'A'})
    cast=mechanics['combatReplay']['bosses'][0]['casts'][0]
    assert cast['durationMs']==17000
    assert cast['expectedEndTimeMs']==17000
    assert cast['outcome']=='interrupted' and cast['endTimeMs']==16000


def test_unmeasured_wcl_cost_is_unknown_and_per_request_costs_sum_independently():
    from analyzer_core import evidence_cache as cache
    @cache.with_evidence_cache
    def collect():
        cache.record_network(.1)
        assert cache.current_stats()['wclPoints'] is None
        cache.record_wcl_points({'currentRequest':{'total':2.5}})
        assert cache.current_stats()['wclPoints']==2.5
        cache.record_network(.2)
        cache.record_wcl_points({'currentRequest':{'total':1.25}})
        assert cache.current_stats()['wclPoints']==3.75
        assert cache.current_stats()['pointsMeasuredRequests']==2
    collect()


def observed_raw(normal_count, target_count):
    casts=[dict(timestamp=100,type='cast',abilityGameID=boss.TOXIC_DELUGE,sourceID=8),
           dict(timestamp=5000,type='cast',abilityGameID=next(iter(boss.DREADMARCH_CAST_IDS)),sourceID=9)]
    casts.extend(dict(timestamp=500+i*20,type='cast',abilityGameID=boss.COALESCED_VENOM_CAST,
        sourceID=20,sourceInstance=i+1) for i in range(normal_count))
    # WCL logs the first wave's applications about 540 ms after cast completion,
    # with source -1. Do not require a fabricated boss source on the aura.
    debuffs=[dict(timestamp=5540,type='applydebuff',abilityGameID=1297445,sourceID=-1,targetID=i+1)
             for i in range(target_count)]
    return {'casts':casts,'debuffs':debuffs}


def test_same_day_pre_maintenance_counts_keep_legacy_rules():
    ruled=boss._with_observed_tuning(fight(),observed_raw(5,4))
    tuning=boss.encounter_tuning(ruled)
    assert tuning['key']=='before-2026-10-13'
    assert tuning['evidence']=='observed-pre-hotfix-counts'
    assert tuning['mutationRadiusYards']==8 and tuning['nightfallCastMs']==15000
    # Subsequent recycled drop casts cannot multiply the initial count.
    raw=observed_raw(4,3)
    raw['casts'].append(dict(timestamp=1000,type='cast',abilityGameID=boss.COALESCED_VENOM_CAST,
                            sourceID=20,sourceInstance=1))
    assert boss.encounter_tuning(boss._with_observed_tuning(fight(),raw))['evidence']=='observed-post-hotfix-counts'


def test_new_counts_confirm_tuning_but_incomplete_counts_are_not_called_verified():
    ruled=boss.encounter_tuning(boss._with_observed_tuning(fight(),observed_raw(4,3)))
    assert ruled['evidence']=='observed-post-hotfix-counts'
    assert ruled['mutationRadiusYards']==6
    partial=boss.encounter_tuning(boss._with_observed_tuning(fight(),observed_raw(2,0)))
    assert partial['evidence']=='date-candidate-not-event-confirmed'
    old=boss.encounter_tuning(boss._with_observed_tuning(fight(12),observed_raw(4,3)))
    assert old['key']=='before-2026-10-13'


def test_soulbind_channel_uses_self_aura_end_and_does_not_duplicate_target_or_p3_aura():
    scene={'combatReplay':{'bosses':[{'actorID':9,'gameID':259854,'casts':[]},
                                   {'actorID':8,'gameID':257911,'casts':[]}]}}
    raw={'casts':[dict(type='cast',timestamp=1000,sourceID=9,targetID=-1,abilityGameID=1304032)],
         'enemyBuffs':[
             dict(type='applybuff',timestamp=1000,sourceID=9,targetID=9,abilityGameID=1304032),
             dict(type='applybuff',timestamp=1229,sourceID=9,targetID=8,abilityGameID=1304032),
             dict(type='removebuff',timestamp=36015,sourceID=9,targetID=9,abilityGameID=1304032),
             dict(type='applybuff',timestamp=36015,sourceID=9,targetID=9,abilityGameID=1289798)]}
    result=boss._apply_altar_soulbind_replay(fight(),scene,raw)
    assert len(result['channels'])==1
    channel=result['channels'][0]
    assert channel['durationMs']==35000 and channel['phase']=='channel'
    assert channel['startTimeMs']==1000 and channel['endTimeMs']==36015
    assert channel['outcome']=='completed'
    assert len(scene['combatReplay']['bosses'][0]['casts'])==1
    assert scene['combatReplay']['bosses'][1]['casts']==[]


def test_soulbind_self_aura_is_enough_but_phase_marker_alone_never_invents_a_channel():
    scene={'combatReplay':{'bosses':[{'actorID':9,'gameID':259854,'casts':[]}]}}
    raw={'enemyBuffs':[dict(type='applybuff',timestamp=1000,sourceID=9,targetID=9,abilityGameID=1304032)],
         'enemyDeaths':[{'timestamp':8000,'targetID':9}]}
    channel=boss._apply_altar_soulbind_replay(fight(),scene,raw)['channels'][0]
    assert channel['endTimeMs']==8000 and channel['outcome']=='cancelled'
    scene['phaseTimeline']=[{'key':'intermission','timeMs':1000}]
    assert not boss._apply_altar_soulbind_replay(fight(),scene,{})['channels']


def test_selected_today_preview_is_public_without_exposing_generated_data_folder():
    from server import AnalyzerHandler
    assert AnalyzerHandler.is_public_page('/assets/demos/coiledaltar_today_check.json')
    assert not AnalyzerHandler.is_public_page('/data/coiledaltar-today-validation.json')
