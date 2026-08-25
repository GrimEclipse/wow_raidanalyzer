"""Small shared Warcraft Logs v2 client used by isolated boss plugins."""

from __future__ import annotations

import json
import os
import time
import warnings
from pathlib import Path
from urllib.parse import urlparse

from urllib3.exceptions import InsecureRequestWarning

from analyzer_core.concurrency import MAX_REQUEST_RETRIES, REQUEST_RETRY_BASE_SECONDS, request_post
from analyzer_core.wcl_context import resolve_wcl_credentials


def load_project_env() -> None:
    for directory in (Path.cwd(), Path(__file__).resolve().parents[1]):
        env_path = directory / ".env"
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        break


load_project_env()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    return value not in {"0", "false", "no", "off"}


def _is_loopback_proxy(proxy_url: str) -> bool:
    if not proxy_url:
        return False
    return (urlparse(proxy_url).hostname or "").lower() in {"127.0.0.1", "localhost", "::1"}


class WclClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("WCL_BASE_URL", "https://www.warcraftlogs.com").rstrip("/")
        proxy_url = os.getenv("WCL_PROXY", "http://127.0.0.1:7890").strip()
        self.proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
        self.verify_tls = _env_bool("WCL_TLS_VERIFY", default=not _is_loopback_proxy(proxy_url))
        # The default local proxy commonly terminates TLS with its own certificate.
        # Silence only that known loopback-proxy warning; remote/direct insecure TLS
        # remains visible so a real certificate problem is not hidden.
        self._suppress_local_proxy_tls_warning = not self.verify_tls and _is_loopback_proxy(proxy_url)
        if self._suppress_local_proxy_tls_warning:
            # catch_warnings() is not reliable across the parallel Fight worker
            # threads. This process-wide rule is deliberately restricted to the
            # exact loopback-host urllib3 message, so remote TLS warnings remain.
            warnings.filterwarnings(
                "ignore",
                message=r"Unverified HTTPS request is being made to host '(?:127\.0\.0\.1|localhost|::1)'.*",
                category=InsecureRequestWarning,
            )
        self.client_id = os.getenv("WCL_CLIENT_ID", "")
        self.client_secret = os.getenv("WCL_CLIENT_SECRET", "")
        self._token = None

    def _post(self, *args, **kwargs):
        kwargs["verify"] = self.verify_tls
        if not self._suppress_local_proxy_tls_warning:
            return request_post(*args, **kwargs)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", InsecureRequestWarning)
            return request_post(*args, **kwargs)

    def token(self) -> str:
        if self._token:
            return self._token
        credentials = resolve_wcl_credentials(self.client_id, self.client_secret)
        if not credentials.client_id or not credentials.client_secret:
            raise RuntimeError("请先配置 WCL_CLIENT_ID 和 WCL_CLIENT_SECRET。")
        response = self._post(
            f"{self.base_url}/oauth/token",
            data={"grant_type": "client_credentials"},
            auth=(credentials.client_id, credentials.client_secret),
            proxies=self.proxies,
            timeout=30,
        )
        if response.status_code == 401:
            raise RuntimeError("WCL API Client ID / Secret 无效。")
        response.raise_for_status()
        self._token = response.json()["access_token"]
        return self._token

    def graphql_data(self, query: str, variables: dict) -> dict:
        response = self._post(
            f"{self.base_url}/api/v2/client",
            json={"query": query, "variables": variables},
            headers={"Authorization": f"Bearer {self.token()}"},
            proxies=self.proxies,
            timeout=90,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("errors"):
            raise RuntimeError(json.dumps(payload["errors"], ensure_ascii=False))
        return payload["data"]

    def graphql(self, query: str, variables: dict) -> dict:
        return self.graphql_data(query, variables)["reportData"]["report"]

    def report_fights(self, report_id: str) -> dict:
        query = """
        query($code: String!) {
          reportData { report(code: $code) {
            title startTime
            fights { id name encounterID difficulty kill startTime endTime bossPercentage fightPercentage }
          } }
        }
        """
        return self.graphql(query, {"code": report_id})

    def actors(self, report_id: str) -> list:
        def read(fields):
            query = """
            query($code: String!) {
              reportData { report(code: $code) {
                masterData { actors { __FIELDS__ } }
              } }
            }
            """.replace("__FIELDS__", fields)
            return self.graphql(query, {"code": report_id})["masterData"]["actors"]

        try:
            return read("id name type subType gameID petOwner")
        except RuntimeError as error:
            if "subType" not in str(error) and "gameID" not in str(error):
                raise
            return read("id name type petOwner")

    def event_page(
        self,
        report_id: str,
        data_type: str,
        fight: dict,
        *,
        start_time=None,
        end_time=None,
        ability_id=None,
        hostility_type=None,
        include_resources=False,
        source_id=None,
        target_id=None,
    ) -> dict:
        optional_args = []
        optional_filters = []
        variables = {
            "code": report_id,
            "dataType": data_type,
            "startTime": float(start_time if start_time is not None else fight["startTime"]),
            "endTime": float(end_time if end_time is not None else fight["endTime"]),
            "fightIDs": [fight["id"]],
        }
        if ability_id is not None:
            optional_args.append("$abilityID: Float")
            optional_filters.append("abilityID: $abilityID")
            variables["abilityID"] = float(ability_id)
        if hostility_type:
            optional_args.append("$hostilityType: HostilityType")
            optional_filters.append("hostilityType: $hostilityType")
            variables["hostilityType"] = hostility_type
        if include_resources:
            optional_args.append("$includeResources: Boolean")
            optional_filters.append("includeResources: $includeResources")
            variables["includeResources"] = True
        if source_id is not None:
            optional_args.append("$sourceID: Int")
            optional_filters.append("sourceID: $sourceID")
            variables["sourceID"] = int(source_id)
        if target_id is not None:
            optional_args.append("$targetID: Int")
            optional_filters.append("targetID: $targetID")
            variables["targetID"] = int(target_id)
        args = ", " + ", ".join(optional_args) if optional_args else ""
        filters = ", " + ", ".join(optional_filters) if optional_filters else ""
        query = f"""
        query($code: String!, $dataType: EventDataType!, $startTime: Float!, $endTime: Float!, $fightIDs: [Int]{args}) {{
          reportData {{ report(code: $code) {{
            events(dataType: $dataType, startTime: $startTime, endTime: $endTime,
                   fightIDs: $fightIDs, limit: 10000{filters}) {{ data nextPageTimestamp }}
          }} }}
        }}
        """
        for attempt in range(1, MAX_REQUEST_RETRIES + 1):
            result = self.graphql(query, variables).get("events")
            if result is not None:
                return result
            if attempt < MAX_REQUEST_RETRIES:
                time.sleep(REQUEST_RETRY_BASE_SECONDS * (2 ** (attempt - 1)))
        return {"data": [], "nextPageTimestamp": None}

    def events(self, report_id: str, data_type: str, fight: dict, **kwargs) -> list:
        rows = []
        current = kwargs.pop("start_time", None)
        current = fight["startTime"] if current is None else current
        end_time = kwargs.pop("end_time", None)
        end_time = fight["endTime"] if end_time is None else end_time
        while current < end_time:
            page = self.event_page(
                report_id,
                data_type,
                fight,
                start_time=current,
                end_time=end_time,
                **kwargs,
            )
            rows.extend(page.get("data") or [])
            next_page = page.get("nextPageTimestamp")
            if not next_page or next_page <= current:
                break
            current = next_page
        return rows

    def interrupt_table(self, report_id: str, fight_id: int) -> dict:
        query = """
        query($code: String!, $fightIDs: [Int]) {
          reportData { report(code: $code) {
            table(dataType: Interrupts, fightIDs: $fightIDs, hostilityType: Enemies)
          } }
        }
        """
        return self.graphql(query, {"code": report_id, "fightIDs": [fight_id]}).get("table") or {}
