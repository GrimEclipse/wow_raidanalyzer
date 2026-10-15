"""Per-request Warcraft Logs credentials for concurrent server jobs."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator, Optional


@dataclass(frozen=True)
class WclCredentials:
    client_id: str
    client_secret: str


_CURRENT_WCL_CREDENTIALS: ContextVar[Optional[WclCredentials]] = ContextVar(
    "current_wcl_credentials",
    default=None,
)
_WCL_OBSERVER = ContextVar('wcl_response_observer', default=None)


def current_wcl_observer():
    return _WCL_OBSERVER.get()


@contextmanager
def use_wcl_credentials(credentials: WclCredentials, *, observer=None) -> Iterator[None]:
    token = _CURRENT_WCL_CREDENTIALS.set(credentials)
    observer_token = _WCL_OBSERVER.set(observer)
    try:
        yield
    finally:
        _CURRENT_WCL_CREDENTIALS.reset(token)
        _WCL_OBSERVER.reset(observer_token)


def resolve_wcl_credentials(
    fallback_client_id: str = "",
    fallback_client_secret: str = "",
) -> WclCredentials:
    credentials = _CURRENT_WCL_CREDENTIALS.get()
    if credentials:
        return credentials
    return WclCredentials(
        client_id=str(fallback_client_id or "").strip(),
        client_secret=str(fallback_client_secret or "").strip(),
    )
