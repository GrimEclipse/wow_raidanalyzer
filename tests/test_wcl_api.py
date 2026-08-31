import warnings

from urllib3.exceptions import InsecureRequestWarning

import analyzer_core.wcl_api as wcl_api


def test_wcl_client_suppresses_only_loopback_proxy_tls_warning(monkeypatch):
    monkeypatch.setenv("WCL_PROXY", "http://127.0.0.1:7890")
    monkeypatch.delenv("WCL_TLS_VERIFY", raising=False)
    client = wcl_api.WclClient()
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(kwargs)
        warnings.warn("local proxy certificate", InsecureRequestWarning)
        return object()

    monkeypatch.setattr(wcl_api, "request_post", fake_post)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        client._post("https://www.warcraftlogs.com/api/v2/client")

    assert client.verify_tls is False
    assert calls[0]["verify"] is False
    assert not [row for row in caught if issubclass(row.category, InsecureRequestWarning)]


def test_wcl_client_keeps_tls_verification_for_direct_connections(monkeypatch):
    monkeypatch.setenv("WCL_PROXY", "")
    monkeypatch.delenv("WCL_TLS_VERIFY", raising=False)
    client = wcl_api.WclClient()

    assert client.proxies is None
    assert client.verify_tls is True
    assert client._suppress_local_proxy_tls_warning is False


def test_explicit_insecure_remote_proxy_warning_is_not_hidden(monkeypatch):
    monkeypatch.setenv("WCL_PROXY", "http://proxy.example:7890")
    monkeypatch.setenv("WCL_TLS_VERIFY", "false")
    client = wcl_api.WclClient()

    assert client.verify_tls is False
    assert client._suppress_local_proxy_tls_warning is False


def test_event_page_passes_wcl_filter_expression(monkeypatch):
    client = wcl_api.WclClient()
    captured = {}

    def fake_graphql(query, variables):
        captured["query"] = query
        captured["variables"] = variables
        return {"events": {"data": [], "nextPageTimestamp": None}}

    monkeypatch.setattr(client, "graphql", fake_graphql)
    client.event_page(
        "report",
        "All",
        {"id": 1, "startTime": 0, "endTime": 1000},
        filter_expression="source.id = 272110 OR target.id = 272110",
    )

    assert "filterExpression: $filterExpression" in captured["query"]
    assert captured["variables"]["filterExpression"] == "source.id = 272110 OR target.id = 272110"
