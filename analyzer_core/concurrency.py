import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from contextvars import copy_context


def env_int(name, default, minimum=1):
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, value)


MAX_JOB_THREADS = env_int("WCL_MAX_JOB_THREADS", 1)
MAX_FIGHT_THREADS = env_int("WCL_MAX_FIGHT_THREADS", 4)
MAX_REQUEST_THREADS = env_int("WCL_MAX_REQUEST_THREADS", 6)
MAX_REQUEST_RETRIES = env_int("WCL_MAX_REQUEST_RETRIES", 3)
REQUEST_RETRY_BASE_SECONDS = float(os.getenv("WCL_REQUEST_RETRY_BASE_SECONDS", "0.8") or 0.8)

_REQUEST_SEMAPHORE = threading.BoundedSemaphore(MAX_REQUEST_THREADS)
_RETRY_STATUSES = {429, 500, 502, 503, 504}


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
