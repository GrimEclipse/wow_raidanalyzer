from copy import deepcopy
import json
from unittest.mock import patch

import pytest

from analyzer_core.config import resolve_analysis_options
from analyzer_core.catalog import find_boss
from analyzer_core.single_fight import _cache_key
from analyzer_core import single_fight
from analyzer_core.wcl_context import WclCredentials, use_wcl_credentials
from boss_plugins.venomous_abyss import sszorak, coiledaltar, vashnik, lostexplorers, twinfangs, ulatek


class Client:
    def __init__(self, encounter):
        self.encounter = encounter
        self.requests = []

    def events(self, report, kind, fight, **kwargs):
        self.requests.append((kind, kwargs))
        return []

    def report_fights(self, report):
        return {'startTime':0, 'fights':[{'id':1,'encounterID':self.encounter,'startTime':0,'endTime':60000,'difficulty':4}]}

    def actors(self, report):
        return [{'id':10,'name':"Zul'jan",'gameID':257347,'type':'NPC'}, {'id':11,'name':'Manifestation','gameID':coiledaltar.MANIFEST_NPC_GAME_ID,'type':'NPC'}]


@pytest.mark.parametrize('selected,expected', [('coiledPreyReviewEnabled', {'Casts','Deaths','CombatantInfo','All'}), ('motherWrathReviewEnabled', {'Casts','Deaths','CombatantInfo','All','DamageTaken'})])
def test_ulatek_critical_suboptions_skip_unselected_queries_and_spatial_computation(selected, expected):
    client = Client(3492)
    options = {row['key']: False for row in ulatek.CONFIG_SCHEMA}
    options.update(criticalReviewEnabled=True, **{selected: True})
    with patch('boss_plugins.venomous_abyss.runtime.WclClient', return_value=client), patch.object(ulatek, '_analyze_serpent_bites', side_effect=AssertionError('unselected spatial analysis')):
        result = ulatek.build_aggregated_json('A'*16, options)
    assert {kind for kind, _ in client.requests} == expected
    assert not any(kwargs.get('include_resources') for _, kwargs in client.requests)
    critical = result['data']['page1_wipeAnalysis'][0]['ulatek']['critical']
    assert [key for key, enabled in critical['enabledItems'].items() if enabled] == [ulatek.CRITICAL_FIELDS[selected][0]]


@pytest.mark.parametrize('module,encounter', [(vashnik,3455),(lostexplorers,3497),(sszorak,3420),(twinfangs,3421),(ulatek,3492)])
def test_survival_only_skips_mechanic_requests_and_preserves_shared_defaults(module,encounter):
    client = Client(encounter)
    before = deepcopy(module.BOSS_CONFIG)
    options = {row['key']:False for row in module.CONFIG_SCHEMA if row['type'] == 'boolean'}
    with patch('boss_plugins.venomous_abyss.runtime.WclClient',return_value=client):
        result = module.build_aggregated_json('A'*16,options)
    assert {kind for kind,_ in client.requests} == {'Casts','Deaths','CombatantInfo'}
    assert len(client.requests) == 3
    assert result['meta']['tabDefinitions'] == [{'key':'survival','label':'全场存活情况'}]
    assert result['meta']['analysisConfig'] == resolve_analysis_options(module.CONFIG_SCHEMA, options)
    assert result['meta']['skippedAnalyses']
    assert result['data']['mechanicOverview']['metrics'] == []
    assert 'survival' in result['data']['page1_wipeAnalysis'][0]
    assert module.BOSS_CONFIG == before


def test_sszorak_field_off_skips_coordinates_and_replay_computation():
    client = Client(3420)
    with patch('boss_plugins.venomous_abyss.runtime.WclClient',return_value=client), patch.object(sszorak,'build_position_index',side_effect=AssertionError('must skip positions')), patch.object(sszorak,'_player_positions_over_window',side_effect=AssertionError('must skip interpolation')):
        result = sszorak.build_aggregated_json('A'*16,{'fieldReplayEnabled':False,'cystsReviewEnabled':False,'crosswindsReviewEnabled':False,'serpentsFuryReviewEnabled':False})
    assert not any(kind in {'Resources','DamageDone'} for kind,_ in client.requests)
    assert result['meta']['features']['fieldReplay'] is False
    assert [row['key'] for row in result['data']['mechanicOverview']['metrics']] == ['stormApplications','stormDispels']


def test_coiledaltar_field_off_skips_npc_fetches_and_all_spatial_adjudication():
    client = Client(3429)
    with patch.object(coiledaltar,'WclClient',return_value=client), patch.object(coiledaltar,'build_position_index',side_effect=AssertionError('positions called')), patch.object(coiledaltar,'build_field_audit',side_effect=AssertionError('field called')), patch.object(coiledaltar,'analyze_cone_sever',side_effect=AssertionError('cone called')):
        options = {row['key']: False for row in coiledaltar.CONFIG_SCHEMA}
        options.update(dreadmarchReviewEnabled=True,graveboundReviewEnabled=True,eternalNightfallReviewEnabled=True)
        result = coiledaltar.build_aggregated_json('A'*16,options)
    assert not any(kind in {'Resources','All','DamageDone','Healing'} for kind,_ in client.requests)
    assert not any(kwargs.get('include_resources') for _,kwargs in client.requests)
    assert result['meta']['features']['fieldReplay'] is False
    assert [row['key'] for row in result['data']['mechanicOverview']['metrics']] == ['regularDreadmarch','graveboundDeaths']
    assert result['data']['page1_wipeAnalysis'][0]['coiledaltar']['fieldAudit'] == {}


def test_single_fight_cache_separates_options_and_credentials():
    entry = find_boss('12.1','venomous_abyss','sszorak')
    with use_wcl_credentials(WclCredentials('a','test')):
        first = _cache_key('A'*16,1,entry,{'fieldReplayEnabled':False})
        full = _cache_key('A'*16,1,entry,{'fieldReplayEnabled':True})
    with use_wcl_credentials(WclCredentials('b','test')):
        second = _cache_key('A'*16,1,entry,{'fieldReplayEnabled':False})
    assert len({first,full,second}) == 3


def test_all_venomous_bosses_expose_configuration():
    for key in ['nakzali','sentinels','vashnik','lostexplorers','sszorak','twinfangs','coiledaltar','ulatek']:
        assert find_boss('12.1','venomous_abyss',key).config_schema


def test_single_fight_normalizes_options_and_keeps_selected_and_full_caches_separate(tmp_path):
    calls = []
    fight = {'id':1,'name':'Sszorak','encounterID':3420,'raidNightDate':'2026-09-08',
             'startTimeIso':'2026-09-08T12:00:00+08:00','abilitySelection':{}}
    overview = {'fights':[fight],'guild':{}}

    def analyze(**kwargs):
        calls.append(kwargs['options'])
        kwargs['output_path'].write_text(json.dumps({'code':200,'meta':{'bossKey':'sszorak','analysisConfig':kwargs['options']},'data':{'page1_wipeAnalysis':[]}}),encoding='utf-8')

    with patch.object(single_fight,'CACHE_DIR',tmp_path/'cache'), patch.object(single_fight,'WclClient'), patch.object(single_fight,'report_overview',return_value=overview), patch.object(single_fight,'analyze_report',side_effect=analyze):
        light = single_fight.analyze_single_fight(report_code='A'*16,fight_id=1,output_path=tmp_path/'light.json',options={'fieldReplayEnabled':False})
        assert calls[-1] == {row['key']: row['key'] != 'fieldReplayEnabled' for row in sszorak.CONFIG_SCHEMA}
        repeated = single_fight.analyze_single_fight(report_code='A'*16,fight_id=1,output_path=tmp_path/'same.json',options={'fieldReplayEnabled':False})
        assert repeated['cacheHit'] is True
        assert repeated['cacheKey'] == light['cacheKey']
        full = single_fight.analyze_single_fight(report_code='A'*16,fight_id=1,output_path=tmp_path/'full.json')
        assert full['cacheHit'] is False
        assert full['cacheKey'] != light['cacheKey']
        assert len(calls) == 2
    assert not list((tmp_path/'cache').rglob('*.tmp'))
    assert all(json.loads(path.read_text(encoding='utf-8')) for path in (tmp_path/'cache').rglob('*.json'))


def test_ulatek_rage_keeps_add_damage_when_wave_review_is_disabled():
    client = Client(3492)
    client.actors = lambda _: [{'id':99,'name':'Add','gameID':267460,'type':'NPC'}]
    with patch('boss_plugins.venomous_abyss.runtime.WclClient',return_value=client):
        ulatek.build_aggregated_json('A'*16,{'wavesReviewEnabled':False})
    assert any(kind == 'DamageDone' and kwargs.get('target_id') == 99 for kind,kwargs in client.requests)


@pytest.mark.parametrize('module,encounter,key', [
    (module, encounter, row['key'])
    for module,encounter in [(vashnik,3455),(lostexplorers,3497),(sszorak,3420),(twinfangs,3421),(coiledaltar,3429),(ulatek,3492)]
    for row in module.CONFIG_SCHEMA if row['type'] == 'boolean'
])
def test_each_analysis_can_run_alone_in_nightly_pipeline(module,encounter,key):
    client = Client(encounter)
    # Exercise multiple pulls, not single-fight routing.
    original = client.report_fights
    def fights(report):
        result = original(report)
        result['fights'] *= 3
        return result
    client.report_fights = fights
    options = {row['key']:row['key'] == key for row in module.CONFIG_SCHEMA if row['type'] == 'boolean'}
    target = 'boss_plugins.venomous_abyss.coiledaltar.WclClient' if module is coiledaltar else 'boss_plugins.venomous_abyss.runtime.WclClient'
    with patch(target,return_value=client):
        result = module.build_aggregated_json('A'*16, options)
    assert len(result['data']['page1_wipeAnalysis']) == 3
    assert result['meta']['analysisConfig'] == resolve_analysis_options(module.CONFIG_SCHEMA, options)
    assert len(result['meta']['skippedAnalyses']) == len(options)-1
    assert all(row['default'] is True for row in module.CONFIG_SCHEMA if row['type'] == 'boolean')


def test_coiledaltar_soul_review_keeps_manifest_evidence_without_field_diagrams():
    client = Client(3429)
    options = {row['key']: row['key'] == 'soulSeverReviewEnabled' for row in coiledaltar.CONFIG_SCHEMA}
    with patch.object(coiledaltar,'WclClient',return_value=client), patch.object(coiledaltar,'build_field_audit',side_effect=AssertionError('diagram called')), patch.object(coiledaltar,'analyze_gloombomb',side_effect=AssertionError('bomb called')), patch.object(coiledaltar,'analyze_manifestations',wraps=coiledaltar.analyze_manifestations) as evidence, patch.object(coiledaltar,'analyze_soul_sever',wraps=coiledaltar.analyze_soul_sever) as soul:
        result = coiledaltar.build_aggregated_json('A'*16,options)
    evidence.assert_called_once()
    soul.assert_called_once()
    assert any(kind == 'Resources' for kind,_ in client.requests)
    mechanics = result['data']['page1_wipeAnalysis'][0]['coiledaltar']
    assert mechanics['fieldAudit'] == {}
    assert mechanics['manifestations'] == {}
    assert [row['key'] for row in result['data']['mechanicOverview']['metrics']] == ['unclearedSouls']


def test_lost_interrupt_only_skips_positions_crates_and_other_mechanics():
    client = Client(3497)
    options = {row['key']: row['key'] == 'interruptReviewEnabled' for row in lostexplorers.CONFIG_SCHEMA}
    with patch('boss_plugins.venomous_abyss.runtime.WclClient',return_value=client), patch.object(lostexplorers,'analyze_throw_junk',side_effect=AssertionError('crate called')), patch.object(lostexplorers,'_mushroom_activations',side_effect=AssertionError('mushroom called')), patch.object(lostexplorers,'_shell_spin_rounds',side_effect=AssertionError('shell called')):
        result = lostexplorers.build_aggregated_json('A'*16,options)
    assert not any(kind in {'Resources','All','DamageTaken','Debuffs','Buffs'} for kind,_ in client.requests)
    assert result['data']['mechanicOverview']['metrics'] == []


def test_sszorak_replay_off_keeps_cyst_wind_evidence_but_skips_replay_frames():
    fight = {'startTime':0,'endTime':60000}
    raw = {key:[] for key in ['casts','damage','debuffs','deaths','resources','friendlyCasts']}
    raw['casts'] = [{'timestamp':1000,'abilityGameID':1286033,'type':'cast'}]
    raw['analysisOptions'] = {row['key']:row['key'] == 'cystsReviewEnabled' for row in sszorak.CONFIG_SCHEMA}
    with patch.object(sszorak,'_player_positions_over_window',return_value=[]) as frames, patch.object(sszorak,'_sszorak_crosswind_waves',side_effect=AssertionError('crosswind review called')):
        result = sszorak.analyze_sszorak(fight,{}, {}, raw)
    # Only the wind inference window is sampled; the separate replay window is skipped.
    frames.assert_called_once()
    assert len(result['cysts']['rounds']) == 1
    assert result['fieldReplay']['rounds'] == []
    assert result['crosswinds'] == {'enabled':False}
