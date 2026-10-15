"""Server-owned WCL credential pools and admission-only point reserves."""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass

from analyzer_core.wcl_context import WclCredentials, use_wcl_credentials


class AdmissionError(ValueError):
    def __init__(self, message, retry_after=60, status=429):
        super().__init__(message)
        self.retry_after = max(1, int(retry_after))
        self.status = status


@dataclass
class Pool:
    credentials: WclCredentials
    group: str
    limit: float | None = None
    spent: float = 0
    reset_at: float = 0
    checked_at: float = 0
    blocked_until: float = 0
    failed: bool = False


class SharedWclService:
    def __init__(self, credentials, *, reserve=3000, refresh_seconds=30, clock=time.time):
        self.pools = [Pool(cred, group) for cred, group in credentials]
        self.reserve = max(0, int(reserve))
        self.refresh_seconds = max(5, int(refresh_seconds))
        self.clock = clock
        self.lock = threading.RLock()

    @classmethod
    def from_settings(cls, setting):
        primary = WclCredentials(setting('WCL_CLIENT_ID'), setting('WCL_CLIENT_SECRET'))
        rows = [(primary, 'shared')] if primary.client_id and primary.client_secret else []
        extra = setting('WCL_SHARED_POOLS')
        if extra:
            try:
                for entry in json.loads(extra):
                    cred = WclCredentials(str(entry['clientId']).strip(), str(entry['clientSecret']).strip())
                    if cred.client_id and cred.client_secret and not any(c.client_id == cred.client_id for c, _ in rows):
                        rows.append((cred, str(entry.get('quotaGroup') or 'shared')))
            except (ValueError, KeyError, TypeError):
                raise RuntimeError('WCL_SHARED_POOLS 配置无效。') from None
        return cls(rows, reserve=setting('WCL_RESERVE_POINTS', '3000'))

    def observe(self, credentials, rate=None, status=200):
        now = self.clock()
        with self.lock:
            for pool in self.pools:
                if pool.credentials != credentials:
                    continue
                if status == 429:
                    for shared in self.pools:
                        if shared.group == pool.group:
                            shared.blocked_until = now + 60
                    return
                if status in (401, 403):
                    pool.failed = True
                    pool.checked_at = now
                if not rate:
                    return
                limit = float(rate['limitPerHour'])
                spent = float(rate['pointsSpentThisHour'])
                reset_at = now + max(0, int(rate['pointsResetIn']))
                same_window = pool.reset_at > now and abs(pool.reset_at-reset_at) < 5
                pool.limit = limit
                pool.spent = max(pool.spent, spent) if same_window else spent
                pool.reset_at, pool.checked_at, pool.failed = reset_at, now, False

    def refresh(self, *, max_age=None):
        from analyzer_core.wcl_api import WclClient
        with self.lock:
            now = self.clock()
            for pool in self.pools:
                age_limit = self.refresh_seconds if max_age is None or pool.failed else max_age
                if pool.checked_at and now-pool.checked_at < age_limit and (pool.failed or pool.reset_at > now):
                    continue
                try:
                    with use_wcl_credentials(pool.credentials, observer=self.observe):
                        data = WclClient().graphql_data(
                            'query { rateLimitData { limitPerHour pointsSpentThisHour pointsResetIn } }', {})
                    self.observe(pool.credentials, data.get('rateLimitData'))
                    if not data.get('rateLimitData'):
                        pool.failed = True
                        pool.checked_at = now
                except Exception:
                    pool.failed, pool.checked_at = True, now

    def _available(self):
        now = self.clock()
        return [p for p in self.pools if p.limit is not None and p.reset_at > now
                and not p.failed and p.blocked_until <= now]

    def _summary(self):
        now = self.clock()
        groups = {}
        for pool in self._available():
            remaining = max(0, pool.limit-pool.spent)
            old = groups.get(pool.group)
            if old is None or remaining < old['remaining']:
                groups[pool.group] = {'limit':pool.limit, 'remaining':remaining, 'resetAt':pool.reset_at}
        limit = sum(g['limit'] for g in groups.values())
        remaining = sum(g['remaining'] for g in groups.values()) if groups else None
        reset = min((g['resetAt'] for g in groups.values()), default=None)
        return {'configured':bool(self.pools), 'mode':'shared', 'limitPerHour':limit or None,
                'remaining':remaining, 'spent':limit-remaining if remaining is not None else None,
                'reservePoints':self.reserve, 'resetAt':reset,
                'pointsResetIn':max(0, int(reset-now)) if reset else None,
                'checkedAt':max((p.checked_at for p in self.pools),default=None),
                'available':remaining is not None and remaining >= self.reserve,
                'adminAvailable':remaining is not None and remaining > 0,
                'status':'unconfigured' if not self.pools else 'unavailable' if remaining is None
                         else 'exhausted' if remaining <= 0 else 'reserved' if remaining < self.reserve else 'ready'}

    def snapshot(self, *, refresh=True):
        if refresh:
            # Normal analysis responses update usage immediately. Idle page
            # polling must not consume one of the owner's points every 30 sec.
            self.refresh(max_age=300)
        with self.lock:
            return self._summary()

    def acquire(self, *, admin=False):
        self.refresh()
        with self.lock:
            state = self._summary()
            if not state['configured']:
                raise AdmissionError('服务器尚未配置共享 WCL 服务。', status=503)
            if not state['adminAvailable']:
                raise AdmissionError('WCL 共享额度暂不可用，请稍后重试。', state['pointsResetIn'] or 60, 503)
            if not admin and not state['available']:
                raise AdmissionError('共享额度低于保留额度，暂时仅 admin 可发起新请求。', state['pointsResetIn'] or 60)
            return max(self._available(), key=lambda p:p.limit-p.spent).credentials
