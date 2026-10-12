import importlib


def test_username_accepts_email(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_AUTH_DIR", str(tmp_path))
    import analyzer_core.auth_store as auth_store
    importlib.reload(auth_store)
    assert auth_store.normalize_username("786123813@QQ.com") == "786123813@qq.com"
    assert auth_store.normalize_username("abc") == "abc"
    for bad in ("ab", "a b c", "<script>", "x" * 65):
        try:
            auth_store.normalize_username(bad)
        except auth_store.AuthError:
            continue
        raise AssertionError(bad)


def test_remote_address_uses_real_ip_only_from_loopback():
    import server

    class Fake:
        remote_address = server.AnalyzerHandler.remote_address

    proxied = Fake()
    proxied.client_address = ("127.0.0.1", 5000)
    proxied.headers = {"X-Real-IP": "153.34.249.106"}
    assert proxied.remote_address() == "153.34.249.106"

    direct = Fake()
    direct.client_address = ("8.8.8.8", 5000)
    direct.headers = {"X-Real-IP": "1.2.3.4"}
    assert direct.remote_address() == "8.8.8.8"

    bare = Fake()
    bare.client_address = ("127.0.0.1", 5000)
    bare.headers = {}
    assert bare.remote_address() == "127.0.0.1"
