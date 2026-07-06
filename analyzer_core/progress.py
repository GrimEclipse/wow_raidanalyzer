from contextlib import contextmanager
from contextvars import ContextVar


_progress_callback = ContextVar("progress_callback", default=None)


def emit_progress(message: str, *, percent=None, stage=None, detail=False, payload=None):
    callback = _progress_callback.get()
    if not callback:
        return
    callback({
        "message": message,
        "percent": percent,
        "stage": stage,
        "detail": detail,
        "payload": payload or {},
    })


@contextmanager
def progress_scope(callback):
    token = _progress_callback.set(callback)
    try:
        yield
    finally:
        _progress_callback.reset(token)
