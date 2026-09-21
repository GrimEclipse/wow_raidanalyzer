import json
from unittest.mock import Mock, patch

import pytest

from analyzer_core import wcl_paths
from server import AnalyzerHandler


def test_report_discovery_accepts_custom_names_but_excludes_non_report_json(tmp_path):
    report = {'meta': {'bossKey': 'ulatek'}, 'data': {'page1_wipeAnalysis': []}}
    (tmp_path / 'ulatek_nightly_latest.json').write_text(json.dumps(report))
    (tmp_path / 'skills.json').write_text('{"skills": []}')
    (tmp_path / 'broken.json').write_text('{')
    (tmp_path / 'manifest.json').write_text(json.dumps(report))
    with patch.object(wcl_paths, 'DATA_DIR', tmp_path), patch.object(wcl_paths, 'LEGACY_WCL_JSON', tmp_path/'missing.json'):
        assert [p.name for p in wcl_paths.iter_wcl_json_files()] == ['ulatek_nightly_latest.json']
        # A later rewrite must invalidate metadata-based discovery cache.
        (tmp_path / 'skills.json').write_text(json.dumps(report))
        assert len(list(wcl_paths.iter_wcl_json_files())) == 2


@pytest.mark.parametrize('role,allowed', [('admin', True), ('editor', True), ('viewer', False)])
def test_server_report_listing_checks_edit_permission(role, allowed):
    handler = object.__new__(AnalyzerHandler)
    handler.path = '/api/data-files'
    handler.request_path = Mock(return_value=handler.path)
    handler.require_user = Mock(return_value={'id': 1, 'isAdmin': role == 'admin', 'canModify': role != 'viewer'})
    handler.send_response_body = Mock()
    handler.json_error = Mock()
    with patch('server.list_wcl_data_files', return_value=[]) as listing, patch('server.write_data_manifest'):
        handler.do_GET()
    assert listing.called == allowed
    if allowed:
        assert handler.send_response_body.call_args.args[0] == 200
    else:
        assert handler.json_error.call_args.args[1] == 403
