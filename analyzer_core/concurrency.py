import os
import threading
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from contextvars import copy_context


def env_setting(name, default=""):
    if name in os.environ:
        return os.environ[name].strip()
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            key, separator, value = line.strip().partition("=")
            if separator and key.strip() == name:
                return value.strip().strip('"').strip("'")
    return str(default)


def env_int(name, default, minimum=1):
    raw = env_setting(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, value)


MAX_JOB_THREADS = env_int("WCL_MAX_JOB_THREADS", 4)
MAX_USER_JOB_THREADS = env_int("WCL_MAX_USER_JOB_THREADS", 1)
MAX_FIGHT_THREADS = env_int("WCL_MAX_FIGHT_THREADS", 4)
MAX_REQUEST_THREADS = env_int("WCL_MAX_REQUEST_THREADS", 6)
MAX_REQUEST_RETRIES = env_int("WCL_MAX_REQUEST_RETRIES", 3)
REQUEST_RETRY_BASE_SECONDS = float(os.getenv("WCL_REQUEST_RETRY_BASE_SECONDS", "0.8") or 0.8)

_REQUEST_SEMAPHORE = threading.BoundedSemaphore(MAX_REQUEST_THREADS)


class JobSlots:
    """Bound jobs globally and per owner, admitting the oldest eligible waiter."""

    def __init__(self, capacity, per_owner=1):
        self.capacity = max(1, capacity)
        self.per_owner = max(1, per_owner)
        self._condition = threading.Condition()
        self._active = {}
        self._waiting = []

    def _queue_snapshot(self, ticket):
        """Called under the condition lock; expose counts, never other owners."""
        owner = ticket[1]
        position = self._waiting.index(ticket) + 1
        running = sum(self._active.values())
        own_running = self._active.get(owner, 0)
        return {
            "running": running,
            "capacity": self.capacity,
            "waiting": len(self._waiting),
            "position": position,
            "ahead": position - 1,
            "ownRunning": own_running,
            "ownLimit": self.per_owner,
            "ownAhead": sum(item[1] == owner for item in self._waiting[:position - 1]),
            "reason": ("account_limit" if own_running >= self.per_owner else
                       "global_capacity" if running >= self.capacity else "queue_order"),
        }

    def acquire(self, owner, *, on_wait=None):
        """Report changed queue snapshots while waiting.

        on_wait runs under the scheduler lock: it must be nonblocking and must
        not call back into this scheduler. Admission returns without a callback.
        """
        ticket = (object(), owner)
        last_snapshot = None
        with self._condition:
            self._waiting.append(ticket)
            self._condition.notify_all()
            try:
                while True:
                    eligible = next((item for item in self._waiting
                                     if self._active.get(item[1], 0) < self.per_owner), None)
                    if sum(self._active.values()) < self.capacity and eligible == ticket:
                        self._waiting.remove(ticket)
                        self._active[owner] = self._active.get(owner, 0) + 1
                        self._condition.notify_all()
                        return
                    if on_wait is not None:
                        snapshot = self._queue_snapshot(ticket)
                        if snapshot != last_snapshot:
                            on_wait(snapshot)
                            last_snapshot = snapshot
                    self._condition.wait()
            except BaseException:
                self._waiting.remove(ticket)
                self._condition.notify_all()
                raise

    def release(self, owner):
        with self._condition:
            count = self._active.get(owner, 0)
            if not count:
                raise ValueError("No active job for owner")
            if count == 1:
                del self._active[owner]
            else:
                self._active[owner] = count - 1
            self._condition.notify_all()
# WCL/Cloudflare 偶尔会在有效 OAuth 凭据和充足额度下瞬时返回 403。
# 401 仍然不重试（凭据错误），403 则按与 429/5xx 相同的短退避重试。
_RETRY_STATUSES = {403, 429, 500, 502, 503, 504}


def requests_module():
    try:
        import requests
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 requests 依赖，请先在当前 Python 环境执行：python -m pip install -r requirements.txt") from exc
    return requests


@contextmanager
def wcl_request_slot():
    _REQUEST_SEMAPHORE.acquire()
    try:
        yield
    finally:
        _REQUEST_SEMAPHORE.release()


def request_post(*args, **kwargs):
    requests = requests_module()
    last_error = None
    for attempt in range(1, MAX_REQUEST_RETRIES + 1):
        try:
            with wcl_request_slot():
                response = requests.post(*args, **kwargs)
            if response.status_code not in _RETRY_STATUSES or attempt >= MAX_REQUEST_RETRIES:
                return response
            last_error = None
        except requests.RequestException as error:
            last_error = error
            if attempt >= MAX_REQUEST_RETRIES:
                raise
        time.sleep(REQUEST_RETRY_BASE_SECONDS * (2 ** (attempt - 1)))
    if last_error:
        raise last_error
    return response


def run_parallel_indexed(items, worker, *, max_workers=None, on_complete=None):
    items = list(items)
    if not items:
        return []
    workers = max(1, min(max_workers or MAX_FIGHT_THREADS, len(items)))
    if workers == 1:
        results = []
        for item in items:
            result = worker(item)
            results.append(result)
            if on_complete:
                on_complete(len(results), len(items), result)
        return results
    results = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_item = {
            executor.submit(copy_context().run, worker, item): item
            for item in items
        }
        for future in as_completed(future_to_item):
            result = future.result()
            results.append(result)
            if on_complete:
                on_complete(len(results), len(items), result)
    return sorted(results, key=lambda item: item[0])
