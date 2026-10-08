"""Credential-scoped WCL evidence cache, independent of Boss configuration."""

from contextvars import ContextVar
from functools import wraps
from pathlib import Path
import hashlib
import json
import os
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1] / ".single_fight_cache" / "evidence"
TTL_SECONDS = 1800
_scope = ContextVar("wcl_evidence_cache", default=None)


class EvidenceScope:
    def __init__(self, force=False):
        self.force = force
        self.stats = {"cacheHits": 0, "networkRequests": 0, "networkSeconds": 0.0}
        self.lock = threading.Lock()

    def record(self, **values):
        with self.lock:
            for key, value in values.items():
                self.stats[key] += value


def with_evidence_cache(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        token = _scope.set(EvidenceScope(bool(kwargs.get("force"))))
        try:
            return function(*args, **kwargs)
        finally:
            _scope.reset(token)
    return wrapped


def current_stats():
    scope = _scope.get()
    return {key: round(value, 3) if isinstance(value, float) else value for key, value in scope.stats.items()} if scope else {}


def query_cache_path(base_url, credentials, query, variables):
    scope = _scope.get()
    # Only single-report reads with credentials; never guild/account/rate-limit
    # queries or mutations. Every paging/filter/resource variable enters the key.
    if not scope or not credentials.client_id or not credentials.client_secret or "reportData" not in query or "mutation" in query.lower() or not variables.get("code") or "rateLimitData" in query:
        return None
    credential_hash = hashlib.sha256((base_url + "\0" + credentials.client_id + "\0" + credentials.client_secret).encode()).hexdigest()
    digest = hashlib.sha256(json.dumps(["wcl-evidence-v1", query, variables], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return ROOT / credential_hash / (digest + ".json")


def read_cached(path, max_age=TTL_SECONDS):
    scope = _scope.get()
    if path is None or scope.force:
        return None
    try:
        if time.time() - path.stat().st_mtime > max_age:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
    except (OSError, ValueError):
        return None
    scope.record(cacheHits=1)
    return payload


def write_cached(path, payload):
    if path is None:
        return
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            file.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
        os.replace(temporary, path)
    except OSError:
        # A full/read-only cache cannot prevent the analysis from finishing.
        pass
    finally:
        if temporary:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def record_network(seconds):
    scope = _scope.get()
    if scope:
        scope.record(networkRequests=1, networkSeconds=seconds)
