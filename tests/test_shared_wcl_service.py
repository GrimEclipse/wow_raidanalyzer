from concurrent.futures import ThreadPoolExecutor

import pytest

from analyzer_core.analysis_admission import AnalysisUsage
from analyzer_core.analysis_scope import fight_accounting_scope, filter_fights, single_fight_scope
from analyzer_core.wcl_context import WclCredentials, use_wcl_credentials
from analyzer_core.wcl_service import SharedWclService, AdmissionError


def service(rows=None):
    clock = [1000.]
    credentials = WclCredentials('server-test', 'secret-test')
    manager = SharedWclService(rows or [(credentials, 'shared')], clock=lambda:clock[0])
    manager.observe(credentials, {'limitPerHour':18000, 'pointsSpentThisHour':100, 'pointsResetIn':600})
    return manager, credentials, clock


def test_reserve_boundary_admin_only_and_hard_exhaustion():
    manager, cred, _ = service()
    manager.observe(cred, {'limitPerHour':18000, 'pointsSpentThisHour':15000, 'pointsResetIn':600})
    assert manager.acquire() == cred  # Exactly 3000 remains available.
    manager.observe(cred, {'limitPerHour':18000, 'pointsSpentThisHour':15001, 'pointsResetIn':600})
    with pytest.raises(AdmissionError):
        manager.acquire()
    assert manager.acquire(admin=True) == cred
    manager.observe(cred, {'limitPerHour':18000, 'pointsSpentThisHour':18000, 'pointsResetIn':600})
    with pytest.raises(AdmissionError):
        manager.acquire(admin=True)


def test_tokens_sharing_quota_are_counted_once_and_out_of_order_observations_do_not_restore_points():
    a, b = WclCredentials('a','a'), WclCredentials('b','b')
    manager = SharedWclService([(a,'shared'),(b,'shared')],clock=lambda:1000)
    for cred, spent in [(a,100),(b,200),(b,150)]:
        manager.observe(cred, {'limitPerHour':18000,'pointsSpentThisHour':spent,'pointsResetIn':600})
    state = manager.snapshot(refresh=False)
    assert state['limitPerHour']==18000
    assert state['remaining']==17800
    manager.observe(a,status=429)
    assert not manager.snapshot(refresh=False)['adminAvailable']


def test_distinct_verified_quota_groups_aggregate():
    a, b = WclCredentials('a','a'), WclCredentials('b','b')
    manager = SharedWclService([(a,'one'),(b,'two')],clock=lambda:1000)
    for cred in (a,b):
        manager.observe(cred, {'limitPerHour':18000,'pointsSpentThisHour':16000,'pointsResetIn':600})
    assert manager.snapshot(refresh=False)['remaining']==4000
    assert manager.acquire() in (a,b)


def test_unknown_quota_is_not_reported_as_zero_or_admitted(monkeypatch):
    manager, _, clock = service()
    clock[0]+=601
    from analyzer_core.wcl_api import WclClient
    calls=[]
    def unavailable(*args):
        calls.append(1)
        raise RuntimeError('offline')
    monkeypatch.setattr(WclClient,'graphql_data',unavailable)
    assert manager.snapshot()['remaining'] is None
    assert manager.snapshot()['remaining'] is None
    assert len(calls)==1
    with pytest.raises(AdmissionError):
        manager.acquire(admin=True)


def test_admitted_batch_runs_past_thirty_then_blocks_new_jobs_and_survives_restart(tmp_path):
    clock=[1000.];path=tmp_path/'usage.db'
    usage=AnalysisUsage(path,clock=lambda:clock[0]);user={'id':1,'isAdmin':False}
    usage.admit(user,'batch')
    assert usage.snapshot(1)['used']==1
    usage.record('batch','report',[{'id':i} for i in range(1,41)])
    usage.record('batch','report',[{'id':1}])
    usage.finish('batch','done')
    restarted=AnalysisUsage(path,clock=lambda:clock[0])
    assert restarted.snapshot(1)['used']==40
    with pytest.raises(AdmissionError):restarted.admit(user,'next')
    restarted.admit({'id':2,'isAdmin':True},'admin')
    assert restarted.snapshot(2,admin=True)['exempt']
    clock[0]+=3601
    restarted.admit(user,'new-hour')
    assert restarted.snapshot(1)['used']==1


def test_concurrent_admission_cannot_pass_the_same_last_slot(tmp_path):
    usage=AnalysisUsage(tmp_path/'usage.db');user={'id':1,'isAdmin':False}
    for n in range(usage.limit-1):usage.admit(user,str(n))
    def submit(n):
        try:usage.admit(user,'race'+str(n));return True
        except AdmissionError:return False
    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(submit,range(8)))==1
    assert usage.snapshot(1)['used']==usage.limit


def test_accounting_records_only_selected_fights_and_does_not_stop_an_admitted_job():
    calls=[]
    with fight_accounting_scope(lambda report, rows:calls.append((report,rows))), single_fight_scope('r',2):
        assert filter_fights('r',[{'id':1},{'id':2}])==[{'id':2}]
    assert calls==[('r',[{'id':2}])]


def test_server_requests_collect_quota_without_changing_the_original_graphql_shape(monkeypatch):
    from analyzer_core.wcl_api import WclClient
    manager, cred, _ = service()
    client=WclClient();sent=[]
    monkeypatch.setattr(client,'token',lambda:'test-token')
    class Response:
        status_code=200
        def raise_for_status(self):pass
        def json(self):return {'data':{'reportData':{'report':{'title':'ok'}},
            'rateLimitData':{'limitPerHour':18000,'pointsSpentThisHour':200,'pointsResetIn':600}}}
    def post(*args, **kwargs):sent.append(kwargs['json']['query']);return Response()
    monkeypatch.setattr(client,'_post',post)
    with use_wcl_credentials(cred,observer=manager.observe):
        result=client.graphql_data('query { reportData { report(code:"r") { title } } }',{})
    assert 'rateLimitData' in sent[0]
    assert result=={'reportData':{'report':{'title':'ok'}}}
    assert manager.snapshot(refresh=False)['remaining']==17800


def test_server_uses_shared_credentials_and_editor_cannot_use_the_admin_reserve(monkeypatch):
    import server
    manager, cred, _ = service()
    manager.observe(cred, {'limitPerHour':18000,'pointsSpentThisHour':16000,'pointsResetIn':600})
    monkeypatch.setattr(server,'WCL_SERVICE',manager)
    monkeypatch.setattr(server.AUTH,'get_wcl_credentials',lambda *_:pytest.fail('Personal credentials must not be read'))
    handler=server.AnalyzerHandler.__new__(server.AnalyzerHandler)
    replies=[]
    handler.send_response_body=lambda *args,**kwargs:replies.append((args,kwargs))
    assert handler.require_wcl_credentials({'id':1,'role':'editor','isAdmin':False}) is None
    assert replies[0][0][0]==429
    assert int(replies[0][1]['headers']['Retry-After'])>0
    assert handler.require_wcl_credentials({'id':2,'isAdmin':True})==cred


def test_personal_credentials_cannot_be_set_through_the_retired_route():
    import server
    handler=server.AnalyzerHandler.__new__(server.AnalyzerHandler)
    handler.request_path=lambda:'/api/auth/wcl-credentials'
    handler.valid_origin=lambda:True
    handler.require_user=lambda *_:{'id':1,'isAdmin':True}
    handler.json_error=lambda message,status:status
    handler.read_json_body=lambda:pytest.fail('Retired route must not read or save credentials')
    assert handler.do_PUT()==410
    assert handler.do_DELETE()==410


def test_status_exposes_only_the_current_users_usage_and_no_credentials(monkeypatch, tmp_path):
    import json
    import server
    manager, _, _ = service()
    usage=AnalysisUsage(tmp_path/'usage.db')
    usage.admit({'id':2,'isAdmin':False},'other')
    monkeypatch.setattr(server,'WCL_SERVICE',manager)
    monkeypatch.setattr(server,'ANALYSIS_USAGE',usage)
    state=server.service_status({'id':1,'isAdmin':False})
    assert state['analysisUsage']['used']==0
    serialized=json.dumps(state)
    assert 'secret-test' not in serialized and 'server-test' not in serialized
    assert 'analysisUsage' not in server.service_status()


def test_shared_oauth_tokens_are_reused_across_clients(monkeypatch):
    from analyzer_core.wcl_api import WclClient
    monkeypatch.setattr(WclClient,'_shared_tokens',{})
    calls=[]
    class Response:
        status_code=200
        def raise_for_status(self):pass
        def json(self):return {'access_token':'shared-test-token','expires_in':3600}
    def post(*args,**kwargs):calls.append(args[1]);return Response()
    monkeypatch.setattr(WclClient,'_post',post)
    with use_wcl_credentials(WclCredentials('reuse','secret'),observer=lambda *args,**kwargs:None):
        assert WclClient().token()==WclClient().token()=='shared-test-token'
    assert len(calls)==1


def test_shared_account_page_keeps_the_elements_required_by_its_live_actions():
    from html.parser import HTMLParser
    from pathlib import Path
    class AccountElements(HTMLParser):
        def __init__(self):
            super().__init__()
            self.ids=set()
            self.inputs=set()
        def handle_starttag(self, tag, attrs):
            attributes=dict(attrs)
            if attributes.get('id'):
                self.ids.add(attributes['id'])
            if tag=='input':
                self.inputs.add(attributes.get('name'))
    page=AccountElements()
    page.feed((Path(__file__).resolve().parents[1]/'frontend/auth/account.html').read_text(encoding='utf-8'))
    assert {'identity','status','logout','adminLink','wclState','guilds','guildForm','passwordForm'} <= page.ids
    assert not {'clientId','clientSecret'} & page.inputs
