import argparse
from http.cookies import SimpleCookie
import hmac
import json
import mimetypes
import os
import queue
import re
import threading
import time
import uuid
import warnings
import webbrowser
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlencode, urlparse

from analyzer_core.auth_store import AuthError, default_auth_store, validate_password
from analyzer_core.catalog import find_boss, to_frontend_catalog
from analyzer_core.concurrency import MAX_JOB_THREADS, requests_module
from analyzer_core.runner import analyze_report
from analyzer_core import raid_calendar_store
from analyzer_core.wcl_context import WclCredentials, use_wcl_credentials
from analyzer_core.wcl_paths import iter_wcl_json_files, list_wcl_data_files, write_data_manifest


ROOT = Path(__file__).resolve().parent


def environment_setting(key, default=""):
    """Read one setting from the process environment or the project .env."""
    if key in os.environ:
        return str(os.environ.get(key) or "").strip()
    env_path = ROOT / ".env"
    if env_path.is_file():
        for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() == key:
                return value.strip().strip('"').strip("'")
    return str(default or "").strip()


JOB_DIR = ROOT / ".analysis_jobs"
JOB_DIR.mkdir(exist_ok=True)
SINGLE_FIGHT_CACHE_DIR = ROOT / ".single_fight_cache"
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
EXPORT_DIR = DATA_DIR / "exports"
_DESKTOP = Path.home() / "Desktop"
DEFAULT_EXPORT_EXCEL_DIR = _DESKTOP if _DESKTOP.is_dir() else EXPORT_DIR
AUTH = default_auth_store()
SESSION_COOKIE = "wra_session"
MAX_JSON_BODY = 10 * 1024 * 1024
LOGIN_ATTEMPTS: Dict[str, List[float]] = {}
LOGIN_ATTEMPTS_LOCK = threading.Lock()
REGISTRATION_ATTEMPTS: Dict[str, List[float]] = {}
REGISTRATION_ATTEMPTS_LOCK = threading.Lock()
INVITE_CODE = environment_setting("APP_INVITE_CODE")
JOB_RESULT_TTL_SECONDS = max(1, int(environment_setting("APP_JOB_RESULT_TTL_HOURS", "24"))) * 3600
JOB_RESULT_MAX_BYTES = max(64, int(environment_setting("APP_JOB_RESULT_MAX_MB", "512"))) * 1024 * 1024
SINGLE_CACHE_TTL_SECONDS = max(1, int(environment_setting("APP_SINGLE_CACHE_TTL_DAYS", "30"))) * 86400
SINGLE_CACHE_MAX_BYTES = max(128, int(environment_setting("APP_SINGLE_CACHE_MAX_MB", "2048"))) * 1024 * 1024

FIGHT_RE = re.compile(r"(读取|分析) Fight\s+(\d+).*?[（(](\d+)/(\d+)[）)]")
COMPLETED_FIGHTS_RE = re.compile(r"已完成\s+(\d+)/(\d+)\s+场")
MATCHED_FIGHTS_RE = re.compile(r"匹配(?:到)?[^0-9\n]*?(\d+)\s*场")
WOWHEAD_TOOLTIP_BASE_URL = "https://nether.wowhead.com"
WOWHEAD_TOOLTIP_CACHE_TTL_SECONDS = 24 * 60 * 60
WOWHEAD_TOOLTIP_CACHE: Dict[tuple, tuple] = {}
WOWHEAD_TOOLTIP_CACHE_LOCK = threading.Lock()
JOB_ID_RE = re.compile(r"[a-f0-9]{12}")


def normalize_static_request_path(path):
    """Keep application entry points compatible with optional trailing slashes."""
    return path.rstrip("/") if path != "/" and path.endswith("/") else path


@dataclass
class Job:
    id: str
    owner_user_id: int
    status: str = "queued"
    percent: int = 0
    message: str = "等待开始"
    stage: str = "queued"
    result_path: Optional[Path] = None
    error: str = ""
    events: List[dict] = field(default_factory=list)
    subscribers: List[queue.Queue] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    fight_index: int = 0
    fight_total: int = 0
    report_index: int = 0
    report_total: int = 1


JOBS: Dict[str, Job] = {}
JOBS_LOCK = threading.Lock()
JOB_SEMAPHORE = threading.BoundedSemaphore(MAX_JOB_THREADS)


def job_result_url(job_id: str, *, download=False) -> str:
    suffix = "?download=1" if download else ""
    return f"/api/jobs/{job_id}/result{suffix}"


def stored_job_result(job_id: str, user: dict) -> Optional[Path]:
    """Resolve a completed result without relying on the in-memory job table."""
    if not JOB_ID_RE.fullmatch(str(job_id or "")):
        return None
    own_path = JOB_DIR / str(user["id"]) / f"{job_id}.json"
    if own_path.is_file():
        return own_path
    if user.get("isAdmin"):
        return next(
            (candidate for candidate in JOB_DIR.glob(f"*/{job_id}.json") if candidate.is_file()),
            None,
        )
    return None


def prune_json_storage(root: Path, *, max_age_seconds: int, max_bytes: int, now: Optional[float] = None) -> dict:
    """Bound temporary JSON storage by age first and then least-recently-used size."""
    root = Path(root)
    if not root.is_dir():
        return {"removed": 0, "bytes": 0}
    cutoff = float(now if now is not None else time.time()) - max(1, int(max_age_seconds))
    removed = 0
    rows = []
    for path in root.rglob("*.json"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
            if stat.st_mtime < cutoff:
                path.unlink()
                removed += 1
            else:
                rows.append((stat.st_mtime, stat.st_size, path))
        except OSError:
            continue
    total = sum(size for _, size, _ in rows)
    for _, size, path in sorted(rows):
        if total <= max(0, int(max_bytes)):
            break
        try:
            path.unlink()
            total -= size
            removed += 1
        except OSError:
            continue
    return {"removed": removed, "bytes": total}


def prune_analysis_storage():
    prune_json_storage(
        JOB_DIR,
        max_age_seconds=JOB_RESULT_TTL_SECONDS,
        max_bytes=JOB_RESULT_MAX_BYTES,
    )
    prune_json_storage(
        SINGLE_FIGHT_CACHE_DIR,
        max_age_seconds=SINGLE_CACHE_TTL_SECONDS,
        max_bytes=SINGLE_CACHE_MAX_BYTES,
    )


def user_guilds(user_id: int) -> list[dict]:
    guilds = AUTH.list_guilds(user_id)
    if guilds:
        return guilds
    from analyzer_core.single_fight import load_single_fight_config

    fallback = load_single_fight_config()["guild"]
    if int(fallback.get("id") or 0) > 0:
        AUTH.upsert_guild(
            user_id,
            int(fallback["id"]),
            str(fallback.get("name") or f"工会 {fallback['id']}"),
            is_default=True,
        )
    return AUTH.list_guilds(user_id)


def selected_user_guild(user_id: int, requested_id=None) -> dict:
    guilds = user_guilds(user_id)
    if not guilds:
        raise AuthError("请先在账号设置中添加一个 WCL 工会。")
    if requested_id not in (None, ""):
        try:
            selected_id = int(requested_id)
        except (TypeError, ValueError) as error:
            raise AuthError("WCL 工会 ID 必须是正整数。") from error
        selected = next((guild for guild in guilds if guild["id"] == selected_id), None)
        if not selected:
            raise AuthError("所选工会不在当前账号的工会列表中。")
        return selected
    return next((guild for guild in guilds if guild["isDefault"]), guilds[0])


prune_analysis_storage()


def publish(job: Job, event: dict):
    event.setdefault("jobId", job.id)
    event.setdefault("status", job.status)
    event.setdefault("percent", job.percent)
    event.setdefault("message", job.message)
    event.setdefault("stage", job.stage)
    job.events.append(event)
    if len(job.events) > 400:
        del job.events[: len(job.events) - 400]
    for subscriber in list(job.subscribers):
        subscriber.put(event)


def set_job_progress(job: Job, *, percent=None, message=None, stage=None, status=None, force=False):
    if percent is not None:
        job.percent = max(job.percent, min(100, int(percent)))
    if message:
        job.message = message
    if stage:
        job.stage = stage
    if status:
        job.status = status
    event = {
        "type": "progress",
        "status": job.status,
        "percent": job.percent,
        "message": job.message,
        "stage": job.stage,
    }
    if force or not job.events or any(
        event[key] != job.events[-1].get(key)
        for key in ("status", "percent", "message", "stage")
    ):
        publish(job, event)


def translate_plugin_progress(job: Job, raw_event: dict):
    message = raw_event.get("message") or ""
    percent = raw_event.get("percent")
    stage = raw_event.get("stage")

    if percent is not None:
        raw_percent = max(0, min(100, int(percent)))
        if stage == "fetch":
            # WCL event readers report a *single fight* sub-progress (24..88).
            # Treating it as the whole raid-night percentage made the first pull
            # jump to 80% and the remaining pulls appear stalled.
            if job.fight_total:
                completed_before = max(0, job.fight_index - 1)
                mapped = 16 + round(
                    (
                        (max(1, job.report_index) - 1)
                        + (completed_before + raw_percent / 100) / job.fight_total
                    )
                    / max(1, job.report_total)
                    * 78
                )
                mapped = min(94, mapped)
            else:
                mapped = 12 + round(raw_percent * 0.78)
            set_job_progress(
                job,
                percent=mapped,
                message=(
                    f"分析战斗 {job.fight_index}/{job.fight_total} · {message}"
                    if job.fight_total and message else message or job.message
                ),
                stage="fetch",
            )
            return
        set_job_progress(job, percent=raw_percent, message=message or job.message, stage=stage or job.stage)
        return

    if "连接 WCL 鉴权端点" in message:
        set_job_progress(job, percent=8, message="连接 WCL 并验证凭据", stage="auth")
        return
    if message.startswith("读取日志"):
        set_job_progress(job, percent=12, message="读取日志基础信息", stage="fetch")
        return

    matched = MATCHED_FIGHTS_RE.search(message)
    if matched:
        job.report_index = min(job.report_total, job.report_index + 1)
        job.fight_index = 0
        job.fight_total = max(1, int(matched.group(1)))
        percent = 16 + round((job.report_index - 1) / max(1, job.report_total) * 78)
        set_job_progress(job, percent=percent, message=f"匹配到 {matched.group(1)} 场开荒记录", stage="match")
        return

    fight = FIGHT_RE.search(message)
    if fight:
        action = fight.group(1)
        index = int(fight.group(3))
        total = max(1, int(fight.group(4)))
        job.report_index = max(1, job.report_index)
        job.fight_index = max(job.fight_index, index)
        job.fight_total = total
        completed_before = max(0, job.fight_index - 1) if action == "读取" else job.fight_index
        overall = ((job.report_index - 1) + completed_before / total) / max(1, job.report_total)
        percent = 16 + round(overall * 78)
        set_job_progress(job, percent=percent, message=f"分析战斗 {job.fight_index}/{total}", stage="analyze")
        return

    completed = COMPLETED_FIGHTS_RE.search(message)
    if completed:
        count = int(completed.group(1))
        total = max(1, int(completed.group(2)))
        overall = ((max(1, job.report_index) - 1) + count / total) / max(1, job.report_total)
        percent = 16 + round(overall * 78)
        set_job_progress(job, percent=percent, message=f"已完成战斗 {count}/{total}", stage="analyze")
        return

    if "输出完成" in message:
        set_job_progress(job, percent=98, message="写入分析结果", stage="write")
        return

    if not raw_event.get("detail") and message:
        set_job_progress(job, message="处理战斗数据", stage="analyze")


def run_job(job: Job, payload: dict, credentials: WclCredentials):
    acquired = False
    try:
        set_job_progress(job, status="queued", percent=1, message="等待可用分析线程", stage="queued", force=True)
        JOB_SEMAPHORE.acquire()
        acquired = True
        set_job_progress(job, status="running", percent=2, message="任务已开始", stage="queued", force=True)
        version = payload["version"]
        raid = payload["raid"]
        boss = payload["boss"]
        report_ids = payload["reportIds"]
        job.report_total = max(
            1,
            len([value for value in re.split(r"[\s,，;；]+", report_ids) if value]),
        )
        options = payload.get("options") or {}
        output_path = JOB_DIR / str(job.owner_user_id) / f"{job.id}.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with use_wcl_credentials(credentials):
            analyze_report(
                version=version,
                raid_key=raid,
                boss_key=boss,
                report_ids=report_ids,
                output_path=output_path,
                options=options,
                progress_callback=lambda event: translate_plugin_progress(job, event),
            )

        job.result_path = output_path
        job.status = "done"
        job.percent = 100
        job.stage = "done"
        job.message = "分析完成"
        publish(job, {
            "type": "done",
            "status": "done",
            "percent": 100,
            "message": "分析完成",
            "stage": "done",
            "resultUrl": job_result_url(job.id),
            "downloadUrl": job_result_url(job.id, download=True),
        })
    except Exception as exc:
        job.status = "error"
        job.error = str(exc)
        publish(job, {
            "type": "error",
            "status": "error",
            "percent": job.percent,
            "message": str(exc),
            "stage": "error",
        })
    finally:
        if acquired:
            JOB_SEMAPHORE.release()


def run_single_fight_job(job: Job, payload: dict, credentials: WclCredentials):
    acquired = False
    try:
        from analyzer_core.single_fight import analyze_single_fight
        from analyzer_core.progress import progress_scope

        set_job_progress(job, status="queued", percent=1, message="等待可用分析线程", stage="queued", force=True)
        JOB_SEMAPHORE.acquire()
        acquired = True
        set_job_progress(job, status="running", percent=2, message="读取单场战斗", stage="discovery", force=True)
        output_path = JOB_DIR / str(job.owner_user_id) / f"{job.id}.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with use_wcl_credentials(credentials):
            callback = lambda event: translate_plugin_progress(job, event)
            with progress_scope(callback):
                result = analyze_single_fight(
                    report_code=payload["reportCode"],
                    fight_id=int(payload["fightID"]),
                    output_path=output_path,
                    options=payload.get("options") or {},
                    force=bool(payload.get("force")),
                    progress_callback=callback,
                )
        job.result_path = Path(result["path"])
        job.status = "done"
        job.percent = 100
        job.stage = "done"
        job.message = "已从缓存读取" if result.get("cacheHit") else "单场分析完成"
        publish(job, {
            "type": "done", "status": "done", "percent": 100,
            "message": job.message, "stage": "done",
            "resultUrl": job_result_url(job.id),
            "downloadUrl": job_result_url(job.id, download=True),
            "cacheHit": bool(result.get("cacheHit")),
        })
    except Exception as exc:
        job.status = "error"
        job.error = str(exc)
        publish(job, {
            "type": "error", "status": "error", "percent": job.percent,
            "message": str(exc), "stage": "error",
        })
    finally:
        if acquired:
            JOB_SEMAPHORE.release()


def run_latest_single_fight_job(job: Job, payload: dict, credentials: WclCredentials):
    acquired = False
    try:
        from analyzer_core.single_fight import analyze_single_fight, latest_guild_fight
        from analyzer_core.progress import progress_scope
        from analyzer_core.wcl_api import WclClient

        set_job_progress(job, status="queued", percent=1, message="等待可用分析线程", stage="queued", force=True)
        JOB_SEMAPHORE.acquire()
        acquired = True
        set_job_progress(job, status="running", percent=3, message="查找工会最新 Boss 战", stage="discovery", force=True)
        output_path = JOB_DIR / str(job.owner_user_id) / f"{job.id}.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with use_wcl_credentials(credentials):
            latest = latest_guild_fight(
                WclClient(), guild_id=int(payload["guildID"]), report_limit=5
            )
            fight = latest["fight"]
            report = latest["report"]
            boss_name = (fight.get("analysisIdentity") or {}).get("bossName") or fight.get("name") or "Boss"
            if not fight.get("supported"):
                reason = fight.get("disabledReason") or "该 Boss 尚未接入分析规则"
                raise ValueError(
                    f"最新一场是 {boss_name} · Fight {fight['id']}，暂不能分析：{reason}"
                )
            set_job_progress(
                job,
                percent=8,
                message=f"已定位 {boss_name} · Fight {fight['id']}，开始分析",
                stage="discovery",
                force=True,
            )
            callback = lambda event: translate_plugin_progress(job, event)
            with progress_scope(callback):
                result = analyze_single_fight(
                    report_code=report["code"],
                    fight_id=int(fight["id"]),
                    output_path=output_path,
                    options=payload.get("options") or {},
                    force=bool(payload.get("force")),
                    progress_callback=callback,
                )
        job.result_path = Path(result["path"])
        job.status = "done"
        job.percent = 100
        job.stage = "done"
        job.message = "已从缓存读取最新一场" if result.get("cacheHit") else "最新一场分析完成"
        publish(job, {
            "type": "done", "status": "done", "percent": 100,
            "message": job.message, "stage": "done",
            "resultUrl": job_result_url(job.id),
            "downloadUrl": job_result_url(job.id, download=True),
            "cacheHit": bool(result.get("cacheHit")),
            "selection": {
                "guild": latest["guild"], "report": report,
                "fightID": fight["id"], "bossName": boss_name,
            },
        })
    except Exception as exc:
        job.status = "error"
        job.error = str(exc)
        publish(job, {
            "type": "error", "status": "error", "percent": job.percent,
            "message": str(exc), "stage": "error",
        })
    finally:
        if acquired:
            JOB_SEMAPHORE.release()


def json_bytes(data, status=HTTPStatus.OK):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return status, "application/json; charset=utf-8", body


def local_wowhead_data(path):
    """Return the minimum data tables expected by the bundled Wowhead client."""
    data_name_match = re.fullmatch(
        r"/wowhead-tooltip/data/(spell-scaling|item-scaling|spec-spells)(?:&.*)?",
        path,
    )
    if not data_name_match:
        return None

    data_name = data_name_match.group(1)
    if data_name == "spell-scaling":
        return {
            "scalingValue": {},
            "spellInformation": {},
            "randPropPoints": {},
        }
    if data_name == "item-scaling":
        return {
            "staminaByIlvl": {},
            "ratingsToPercentRM": {},
            "ratingsToPercentLT": {},
            "itemScalingValue": {},
            "scalingFactors": {},
            "curvePoints": {},
            "scalingData": {},
            "contentTuningLevels": {},
            "reforgeStats": {},
        }
    return {"specMap": {}, "class": {}, "spec": {}}


def wowhead_static_asset_url(path, query=""):
    """Map the bundled tooltip client's /zamimg asset prefix to its trusted CDN."""
    if not path.startswith("/zamimg/") or "\\" in path:
        return None
    relative_path = path[len("/zamimg/"):]
    if not relative_path or any(part in {"", ".", ".."} for part in relative_path.split("/")):
        return None
    if any(ord(char) < 32 for char in path + query):
        return None
    suffix = f"?{query}" if query else ""
    return f"https://wow.zamimg.com/{relative_path}{suffix}"


def wowhead_spell_tooltip(spell_id, query=""):
    """Fetch the real Chinese Wowhead tooltip, with a local-name fallback.

    The bundled tooltip client deliberately calls this same-origin route.  The
    public ``www.wowhead.com/tooltip`` path returns 404 for current raid spells;
    Wowhead's tooltip client uses ``nether.wowhead.com`` instead.
    """
    from boss_plugins.venomous_abyss.shared import local_spell_tooltip

    spell_id = int(spell_id)
    incoming = parse_qs(query, keep_blank_values=False)
    params = {}
    for key in ("dd", "dataEnv", "locale"):
        value = str((incoming.get(key) or [""])[0]).strip()
        if value.isdigit():
            params[key] = value
    params.setdefault("dataEnv", "1")
    params.setdefault("locale", "4")
    cache_key = (spell_id, tuple(sorted(params.items())))
    now = time.time()
    with WOWHEAD_TOOLTIP_CACHE_LOCK:
        cached = WOWHEAD_TOOLTIP_CACHE.get(cache_key)
        if cached and now - cached[0] < WOWHEAD_TOOLTIP_CACHE_TTL_SECONDS:
            return cached[1]

    url = f"{WOWHEAD_TOOLTIP_BASE_URL}/tooltip/spell/{spell_id}?{urlencode(params)}"
    proxy_url = environment_setting("WCL_PROXY", "http://127.0.0.1:7890")
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
    loopback_proxy = bool(
        proxy_url
        and (urlparse(proxy_url).hostname or "").lower()
        in {"127.0.0.1", "localhost", "::1"}
    )
    verify_tls = environment_setting(
        "WOWHEAD_TLS_VERIFY", "0" if loopback_proxy else "1"
    ).lower() not in {"0", "false", "no", "off"}
    try:
        requests = requests_module()
        if loopback_proxy and not verify_tls:
            from urllib3.exceptions import InsecureRequestWarning

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", InsecureRequestWarning)
                response = requests.get(
                    url,
                    headers={"User-Agent": "MythicAnalyzer/0.2"},
                    proxies=proxies,
                    verify=False,
                    timeout=12,
                )
        else:
            response = requests.get(
                url,
                headers={"User-Agent": "MythicAnalyzer/0.2"},
                proxies=proxies,
                verify=verify_tls,
                timeout=12,
            )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not payload.get("name") or not payload.get("tooltip"):
            raise ValueError("Wowhead tooltip payload is incomplete")
        with WOWHEAD_TOOLTIP_CACHE_LOCK:
            WOWHEAD_TOOLTIP_CACHE[cache_key] = (now, payload)
        return payload
    except Exception:
        return local_spell_tooltip(spell_id)


def safe_redirect_target(value, default="/online"):
    target = str(value or "").strip()
    parsed = urlparse(target)
    if (
        target.startswith("/")
        and not target.startswith("//")
        and "\\" not in target
        and not any(ord(char) < 32 for char in target)
        and not parsed.scheme
        and not parsed.netloc
    ):
        return target
    return default


class AnalyzerHandler(BaseHTTPRequestHandler):
    server_version = "MythicAnalyzer/1.3"

    def do_GET(self):
        path = self.request_path()
        wowhead_asset = wowhead_static_asset_url(path, urlparse(self.path).query)
        if wowhead_asset is not None:
            return self.redirect_resource(wowhead_asset)
        if path == "/favicon.ico":
            return self.send_response_body(HTTPStatus.NO_CONTENT, "image/x-icon", b"")
        if path == "/login":
            if self.current_user():
                return self.redirect("/online")
            return self.handle_static(path, public=True)

        if path == "/api/auth/config":
            return self.send_response_body(*json_bytes({
                "registrationRequiresInvite": bool(INVITE_CODE),
            }))

        wowhead_data = local_wowhead_data(path)
        if wowhead_data is not None:
            return self.send_response_body(*json_bytes(wowhead_data))

        tooltip_match = re.fullmatch(r"/wowhead-tooltip/tooltip/spell/(\d+)", path)
        if tooltip_match:
            return self.send_response_body(*json_bytes(
                wowhead_spell_tooltip(
                    int(tooltip_match.group(1)),
                    urlparse(self.path).query,
                )
            ))

        user = self.require_user(path)
        if not user:
            return None
        if path == "/api/auth/me":
            return self.send_response_body(*json_bytes({
                "user": user,
                "wcl": AUTH.wcl_summary(user["id"]),
                "guilds": user_guilds(user["id"]),
            }))
        if path == "/api/auth/guilds":
            return self.send_response_body(*json_bytes({"guilds": user_guilds(user["id"])}))
        if path == "/api/admin/users":
            if not user["isAdmin"]:
                return self.json_error("仅管理员可以管理账号。", HTTPStatus.FORBIDDEN)
            return self.send_response_body(*json_bytes({"users": AUTH.list_users()}))
        if path == "/api/catalog":
            return self.send_response_body(*json_bytes(to_frontend_catalog()))
        if path == "/api/single-fight/config":
            from analyzer_core.player_abilities import catalog_summary
            from analyzer_core.single_fight import load_single_fight_config

            config = load_single_fight_config()
            guilds = user_guilds(user["id"])
            selected_guild = next((guild for guild in guilds if guild["isDefault"]), guilds[0])
            return self.send_response_body(*json_bytes({
                "schemaVersion": config["schemaVersion"],
                "guild": selected_guild,
                "guilds": guilds,
                "raidNight": config["raidNight"],
                "abilityCatalog": catalog_summary(),
            }))
        if path == "/api/single-fight/reports":
            from analyzer_core.single_fight import recent_guild_reports

            credentials = self.require_wcl_credentials(user)
            if not credentials:
                return None
            query = parse_qs(urlparse(self.path).query)
            selected_date = str((query.get("date") or [""])[0]).strip()
            limit = int((query.get("limit") or ["20"])[0])
            try:
                selected_guild = selected_user_guild(
                    user["id"], str((query.get("guildID") or [""])[0]).strip()
                )
            except AuthError as error:
                return self.json_error(str(error), HTTPStatus.BAD_REQUEST)
            with use_wcl_credentials(credentials):
                return self.send_response_body(*json_bytes(recent_guild_reports(
                    selected_date=selected_date, limit=limit, guild_id=selected_guild["id"],
                )))
        single_report = re.fullmatch(r"/api/single-fight/reports/([A-Za-z0-9]+)", path)
        if single_report:
            from analyzer_core.single_fight import report_overview

            credentials = self.require_wcl_credentials(user)
            if not credentials:
                return None
            with use_wcl_credentials(credentials):
                return self.send_response_body(*json_bytes(report_overview(single_report.group(1))))
        if path == "/api/raid-cooldowns/options":
            from analyzer_core.raid_cooldowns import options_document

            return self.send_response_body(*json_bytes(options_document()))
        if path.startswith("/api/jobs/") and path.endswith("/events"):
            return self.handle_events(path, user)
        if path.startswith("/api/jobs/") and path.endswith("/status"):
            return self.handle_job_status(path, user)
        if path.startswith("/api/jobs/") and path.endswith("/result"):
            return self.handle_result(path, user)
        if path in {"/api/raid-calendar", "/api/loot"}:
            query = parse_qs(urlparse(self.path).query)
            selected_date = (query.get("date") or [None])[0]
            difficulty = (query.get("difficulty") or ["heroic"])[0]
            try:
                document = raid_calendar_store.load_document(selected_date, difficulty)
                document["permissions"] = {"isAdmin": user["isAdmin"], "canModify": user["canModify"]}
                return self.send_response_body(*json_bytes(document))
            except ValueError as error:
                return self.json_error(str(error), HTTPStatus.BAD_REQUEST)
        if path in {"/api/data/list", "/api/data-files"}:
            files = list_wcl_data_files()
            write_data_manifest()
            if path == "/api/data-files":
                return self.send_response_body(*json_bytes({"schemaVersion": 1, "files": files}))
            return self.send_response_body(*json_bytes(files))
        if path == "/api/data/latest":
            files = list(iter_wcl_json_files())
            if not files:
                return self.json_error("no data json", HTTPStatus.NOT_FOUND)
            latest = max(files, key=lambda candidate: candidate.stat().st_mtime)
            data = json.loads(latest.read_text(encoding="utf-8-sig"))
            return self.send_response_body(*json_bytes(data))
        data_file = re.fullmatch(r"/api/data/([^/]+\.json)", path)
        if data_file:
            path_obj = DATA_DIR / data_file.group(1)
            if not path_obj.is_file():
                path_obj = ROOT / data_file.group(1)
            if not path_obj.is_file():
                return self.json_error("not found", HTTPStatus.NOT_FOUND)
            return self.send_response_body(
                HTTPStatus.OK,
                "application/json; charset=utf-8",
                path_obj.read_bytes(),
            )
        if path.startswith("/api/"):
            return self.json_error("not found", HTTPStatus.NOT_FOUND)
        return self.handle_static(path)

    def do_POST(self):
        path = self.request_path()
        if not self.valid_origin():
            return self.json_error("请求来源校验失败。", HTTPStatus.FORBIDDEN)
        if path == "/api/auth/login":
            return self.handle_login()
        if path == "/api/auth/register":
            return self.handle_register()
        user = self.require_user(path)
        if not user:
            return None
        if path == "/api/auth/logout":
            return self.handle_logout()
        admin_reset_match = re.fullmatch(r"/api/admin/users/(\d+)/password", path)
        if admin_reset_match:
            return self.handle_admin_reset_password(user, int(admin_reset_match.group(1)))
        if path == "/api/auth/wcl-credentials/test":
            return self.handle_wcl_credentials_test(user)
        return self.handle_write(path, user)

    def do_PUT(self):
        path = self.request_path()
        if not self.valid_origin():
            return self.json_error("请求来源校验失败。", HTTPStatus.FORBIDDEN)
        user = self.require_user(path)
        if not user:
            return None
        if path == "/api/auth/password":
            return self.handle_change_password(user)
        if path == "/api/auth/wcl-credentials":
            return self.handle_wcl_credentials(user)
        if path == "/api/auth/guilds":
            return self.handle_guild_upsert(user)
        default_guild_match = re.fullmatch(r"/api/auth/guilds/(\d+)/default", path)
        if default_guild_match:
            try:
                guild = AUTH.set_default_guild(user["id"], int(default_guild_match.group(1)))
                return self.send_response_body(*json_bytes({"ok": True, "guild": guild, "guilds": user_guilds(user["id"])}))
            except AuthError as error:
                return self.json_error(str(error), HTTPStatus.BAD_REQUEST)
        admin_match = re.fullmatch(r"/api/admin/users/(\d+)", path)
        if admin_match:
            return self.handle_admin_update(user, int(admin_match.group(1)))
        admin_reset_match = re.fullmatch(r"/api/admin/users/(\d+)/password", path)
        if admin_reset_match:
            return self.handle_admin_reset_password(user, int(admin_reset_match.group(1)))
        return self.handle_write(path, user)

    def do_DELETE(self):
        path = self.request_path()
        if not self.valid_origin():
            return self.json_error("请求来源校验失败。", HTTPStatus.FORBIDDEN)
        user = self.require_user(path)
        if not user:
            return None
        if path == "/api/auth/wcl-credentials":
            AUTH.delete_wcl_credentials(user["id"])
            return self.send_response_body(*json_bytes({"ok": True}))
        guild_match = re.fullmatch(r"/api/auth/guilds/(\d+)", path)
        if guild_match:
            try:
                AUTH.delete_guild(user["id"], int(guild_match.group(1)))
                return self.send_response_body(*json_bytes({"ok": True, "guilds": user_guilds(user["id"])}))
            except AuthError as error:
                return self.json_error(str(error), HTTPStatus.BAD_REQUEST)
        admin_delete_match = re.fullmatch(r"/api/admin/users/(\d+)", path)
        if admin_delete_match:
            return self.handle_admin_delete(user, int(admin_delete_match.group(1)))
        if not user["canModify"]:
            return self.json_error("当前账号只有只读权限。", HTTPStatus.FORBIDDEN)
        allocation_match = re.fullmatch(r"/api/(?:raid-calendar|loot)/allocations/([A-Za-z0-9_-]+)", path)
        if allocation_match:
            try:
                return self.send_response_body(*json_bytes(raid_calendar_store.delete_allocation(allocation_match.group(1))))
            except ValueError as error:
                return self.json_error(str(error), HTTPStatus.NOT_FOUND)
        blackmark_match = re.fullmatch(r"/api/(?:raid-calendar|loot)/blackmarks/([A-Za-z0-9_-]+)", path)
        if blackmark_match:
            try:
                return self.send_response_body(*json_bytes(raid_calendar_store.delete_blackmark(blackmark_match.group(1))))
            except ValueError as error:
                return self.json_error(str(error), HTTPStatus.NOT_FOUND)
        return self.json_error("not found", HTTPStatus.NOT_FOUND)

    def request_path(self):
        return unquote(urlparse(self.path).path)

    def read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("无效的请求长度。") from error
        if length < 0 or length > MAX_JSON_BODY:
            raise ValueError("请求内容过大。")
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        payload = json.loads(raw or "{}")
        if not isinstance(payload, dict):
            raise ValueError("请求内容必须是 JSON 对象。")
        return payload

    def session_token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            return ""
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel else ""

    def current_user(self):
        return AUTH.session_user(self.session_token())

    def require_user(self, path):
        user = self.current_user()
        if user:
            return user
        if path.startswith("/api/"):
            self.json_error("请先登录。", HTTPStatus.UNAUTHORIZED)
        else:
            next_path = path if path.startswith("/") and not path.startswith("//") else "/"
            self.redirect(f"/login?{urlencode({'next': next_path})}")
        return None

    def valid_origin(self):
        origin = self.headers.get("Origin", "").strip()
        if not origin:
            return True
        parsed = urlparse(origin)
        return parsed.netloc.lower() == self.headers.get("Host", "").lower()

    def remote_address(self):
        forwarded = self.headers.get("CF-Connecting-IP", "").strip()
        return forwarded or str(self.client_address[0])

    def login_rate_limited(self, username):
        now = time.time()
        key = f"{self.remote_address()}:{str(username).strip().lower()}"
        with LOGIN_ATTEMPTS_LOCK:
            attempts = [stamp for stamp in LOGIN_ATTEMPTS.get(key, []) if now - stamp < 900]
            LOGIN_ATTEMPTS[key] = attempts
            return len(attempts) >= 5

    def record_login_failure(self, username):
        key = f"{self.remote_address()}:{str(username).strip().lower()}"
        with LOGIN_ATTEMPTS_LOCK:
            LOGIN_ATTEMPTS.setdefault(key, []).append(time.time())

    def clear_login_failures(self, username):
        key = f"{self.remote_address()}:{str(username).strip().lower()}"
        with LOGIN_ATTEMPTS_LOCK:
            LOGIN_ATTEMPTS.pop(key, None)

    def handle_login(self):
        try:
            payload = self.read_json_body()
            username = str(payload.get("username") or "")
            if self.login_rate_limited(username):
                return self.json_error("登录尝试过多，请 15 分钟后再试。", HTTPStatus.TOO_MANY_REQUESTS)
            user = AUTH.authenticate(username, str(payload.get("password") or ""))
            if not user:
                self.record_login_failure(username)
                time.sleep(0.25)
                return self.json_error("用户名或密码不正确。", HTTPStatus.UNAUTHORIZED)
            self.clear_login_failures(username)
            token = AUTH.create_session(
                user["id"],
                remote_address=self.remote_address(),
                user_agent=self.headers.get("User-Agent", ""),
            )
            return self.send_response_body(*json_bytes({
                "ok": True,
                "user": user,
                "redirectTo": safe_redirect_target(payload.get("next")),
            }), cookie=self.cookie_value(token))
        except (AuthError, ValueError, json.JSONDecodeError) as error:
            return self.json_error(str(error), HTTPStatus.BAD_REQUEST)

    def handle_register(self):
        try:
            now = time.time()
            address = self.remote_address()
            with REGISTRATION_ATTEMPTS_LOCK:
                attempts = [
                    stamp
                    for stamp in REGISTRATION_ATTEMPTS.get(address, [])
                    if now - stamp < 3600
                ]
                if len(attempts) >= 5:
                    return self.json_error("注册次数过多，请一小时后再试。", HTTPStatus.TOO_MANY_REQUESTS)
                REGISTRATION_ATTEMPTS[address] = attempts + [now]
            payload = self.read_json_body()
            if INVITE_CODE:
                supplied = str(payload.get("inviteCode") or payload.get("invite_code") or "").strip()
                if not supplied:
                    return self.json_error("请填写邀请码。", HTTPStatus.FORBIDDEN)
                if not hmac.compare_digest(supplied, INVITE_CODE):
                    return self.json_error("邀请码不正确。", HTTPStatus.FORBIDDEN)
            user = AUTH.create_user(
                str(payload.get("username") or ""),
                str(payload.get("password") or ""),
                role="viewer",
            )
            token = AUTH.create_session(
                user["id"],
                remote_address=self.remote_address(),
                user_agent=self.headers.get("User-Agent", ""),
            )
            return self.send_response_body(
                *json_bytes({
                    "ok": True,
                    "user": user,
                    "redirectTo": safe_redirect_target(payload.get("next")),
                }, HTTPStatus.CREATED),
                cookie=self.cookie_value(token),
            )
        except (AuthError, ValueError, json.JSONDecodeError) as error:
            return self.json_error(str(error), HTTPStatus.BAD_REQUEST)

    def handle_logout(self):
        AUTH.delete_session(self.session_token())
        return self.send_response_body(
            *json_bytes({"ok": True}),
            cookie=f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0{self.secure_cookie_suffix()}",
        )

    def handle_change_password(self, user):
        try:
            payload = self.read_json_body()
            AUTH.change_password(
                user["id"],
                str(payload.get("currentPassword") or ""),
                str(payload.get("newPassword") or ""),
            )
            token = AUTH.create_session(
                user["id"],
                remote_address=self.remote_address(),
                user_agent=self.headers.get("User-Agent", ""),
            )
            return self.send_response_body(*json_bytes({"ok": True}), cookie=self.cookie_value(token))
        except (AuthError, ValueError, json.JSONDecodeError) as error:
            return self.json_error(str(error), HTTPStatus.BAD_REQUEST)

    def handle_wcl_credentials(self, user):
        try:
            payload = self.read_json_body()
            AUTH.set_wcl_credentials(
                user["id"],
                str(payload.get("clientId") or ""),
                str(payload.get("clientSecret") or ""),
            )
            return self.send_response_body(*json_bytes({"ok": True, "wcl": AUTH.wcl_summary(user["id"])}))
        except (AuthError, ValueError, json.JSONDecodeError) as error:
            return self.json_error(str(error), HTTPStatus.BAD_REQUEST)

    def handle_guild_upsert(self, user):
        try:
            payload = self.read_json_body()
            guild_id = int(payload.get("guildId") or payload.get("id") or 0)
            if guild_id <= 0:
                raise AuthError("WCL 工会 ID 必须是正整数。")
            credentials = AUTH.get_wcl_credentials(user["id"])
            if not credentials:
                return self.json_error(
                    "请先保存 WCL Client ID 与 Client Secret，再添加工会。",
                    HTTPStatus.BAD_REQUEST,
                )
            from analyzer_core.wcl_api import WclClient

            with use_wcl_credentials(credentials):
                data = WclClient().graphql_data(
                    "query($guildID: Int!) { guildData { guild(id: $guildID) { id name } } }",
                    {"guildID": guild_id},
                )
            resolved = (data.get("guildData") or {}).get("guild") or {}
            if not resolved:
                raise AuthError("WCL 未找到该工会，请检查工会 ID。")
            guild = AUTH.upsert_guild(
                user["id"],
                int(resolved.get("id") or guild_id),
                str(resolved.get("name") or f"工会 {guild_id}"),
                is_default=bool(payload.get("isDefault")),
            )
            return self.send_response_body(*json_bytes({
                "ok": True, "guild": guild, "guilds": user_guilds(user["id"]),
            }))
        except (AuthError, ValueError, json.JSONDecodeError) as error:
            return self.json_error(str(error), HTTPStatus.BAD_REQUEST)
        except Exception as error:
            return self.json_error(f"无法验证工会：{error}", HTTPStatus.BAD_REQUEST)

    def handle_wcl_credentials_test(self, user):
        try:
            credentials = AUTH.get_wcl_credentials(user["id"])
            if not credentials:
                return self.json_error("尚未配置 WCL 凭据，请先保存再测试。", HTTPStatus.BAD_REQUEST)
            from analyzer_core.wcl_api import WclClient
            client = WclClient()
            with use_wcl_credentials(credentials):
                client.token()
                guild_id = int(selected_user_guild(user["id"])["id"])
                data = client.graphql_data(
                    """
                    query($guildID: Int!) {
                      reportData { reports(guildID: $guildID, limit: 1) { data { code title startTime } } }
                      rateLimitData { limitPerHour pointsSpentThisHour }
                    }
                    """,
                    {"guildID": guild_id},
                )
            reports = ((data.get("reportData") or {}).get("reports") or {}).get("data") or []
            last = reports[0] if reports else None
            return self.send_response_body(*json_bytes({
                "ok": True,
                "clientIdHint": AUTH.wcl_summary(user["id"]).get("clientIdHint", ""),
                "guildReport": ({k: last.get(k) for k in ("code", "title", "startTime")}) if last else None,
                "rateLimit": data.get("rateLimitData") or {},
            }))
        except Exception as error:
            return self.json_error(f"API 不可用：{error}", HTTPStatus.BAD_REQUEST)

    def handle_admin_update(self, actor, target_user_id):
        if not actor["isAdmin"]:
            return self.json_error("仅管理员可以管理账号。", HTTPStatus.FORBIDDEN)
        try:
            payload = self.read_json_body()
            target = AUTH.get_user(target_user_id)
            if not target:
                return self.json_error("账号不存在。", HTTPStatus.NOT_FOUND)
            role = str(payload.get("role") or target["role"]).strip().lower()
            disabled = bool(payload.get("disabled", target["disabled"]))
            if actor["id"] == target_user_id and (role != "admin" or disabled):
                raise AuthError("管理员不能降低或禁用自己的账号。")
            if target["isAdmin"] and (role != "admin" or disabled) and AUTH.admin_count() <= 1:
                raise AuthError("不能移除或禁用最后一个管理员。")
            AUTH.set_role(target_user_id, role, actor_user_id=actor["id"])
            AUTH.set_disabled(target_user_id, disabled)
            return self.send_response_body(*json_bytes({"ok": True, "user": AUTH.get_user(target_user_id)}))
        except (AuthError, ValueError, json.JSONDecodeError) as error:
            return self.json_error(str(error), HTTPStatus.BAD_REQUEST)

    def handle_admin_delete(self, actor, target_user_id):
        if not actor["isAdmin"]:
            return self.json_error("仅管理员可以管理账号。", HTTPStatus.FORBIDDEN)
        try:
            AUTH.delete_user(target_user_id, actor_user_id=actor["id"])
            return self.send_response_body(*json_bytes({"ok": True}))
        except AuthError as error:
            status = HTTPStatus.NOT_FOUND if "不存在" in str(error) else HTTPStatus.BAD_REQUEST
            return self.json_error(str(error), status)

    def handle_admin_reset_password(self, actor, target_user_id):
        if not actor["isAdmin"]:
            return self.json_error("仅管理员可以管理账号。", HTTPStatus.FORBIDDEN)
        try:
            payload = self.read_json_body()
            new_password = str(payload.get("newPassword") or "")
            encoded = validate_password(new_password)
            target = AUTH.get_user(target_user_id)
            if not target:
                return self.json_error("账号不存在。", HTTPStatus.NOT_FOUND)
            must_change = bool(payload.get("mustChangePassword", target["id"] != actor["id"]))
            AUTH.reset_password(target_user_id, encoded, must_change_password=must_change)
            summary = AUTH.get_user(target_user_id)
            return self.send_response_body(
                *json_bytes({"ok": True, "user": summary, "temporaryPassword": new_password if must_change else None})
            )
        except (AuthError, ValueError, json.JSONDecodeError) as error:
            return self.json_error(str(error), HTTPStatus.BAD_REQUEST)

    def handle_write(self, path, user):
        if not user["canModify"]:
            return self.json_error("当前账号只有只读权限。", HTTPStatus.FORBIDDEN)
        try:
            if path == "/api/single-fight/latest":
                credentials = self.require_wcl_credentials(user)
                if not credentials:
                    return None
                payload = self.read_json_body()
                guild = selected_user_guild(user["id"], payload.get("guildID"))
                payload["guildID"] = guild["id"]
                prune_analysis_storage()
                job = Job(id=uuid.uuid4().hex[:12], owner_user_id=user["id"])
                with JOBS_LOCK:
                    JOBS[job.id] = job
                thread = threading.Thread(
                    target=run_latest_single_fight_job,
                    args=(job, payload, credentials),
                    daemon=True,
                )
                thread.start()
                return self.send_response_body(*json_bytes({
                    "jobId": job.id,
                    "eventsUrl": f"/api/jobs/{job.id}/events",
                    "statusUrl": f"/api/jobs/{job.id}/status",
                    "resultUrl": job_result_url(job.id),
                    "downloadUrl": job_result_url(job.id, download=True),
                    "guild": guild,
                }, HTTPStatus.ACCEPTED))
            if path in {"/api/raid-calendar/setup", "/api/loot/setup"}:
                return self.send_response_body(*json_bytes(raid_calendar_store.save_setup(self.read_json_body())))
            if path in {"/api/raid-calendar/settings", "/api/loot/settings"}:
                if not user["isAdmin"]:
                    return self.json_error("仅管理员可以修改史诗难度刷新设置。", HTTPStatus.FORBIDDEN)
                return self.send_response_body(*json_bytes(raid_calendar_store.save_settings(self.read_json_body())))
            if path in {"/api/raid-calendar/allocations", "/api/loot/allocations"}:
                return self.send_response_body(*json_bytes(raid_calendar_store.add_allocation(self.read_json_body())))
            if path in {"/api/raid-calendar/blackmarks", "/api/loot/blackmarks"}:
                return self.send_response_body(*json_bytes(raid_calendar_store.add_blackmark(self.read_json_body())))
            if path == "/api/export-verdict-excel":
                return self.handle_export_verdict_excel()
            if path == "/api/raid-cooldowns/search":
                from analyzer_core.raid_cooldowns import search_raid_cooldowns

                credentials = self.require_wcl_credentials(user)
                if not credentials:
                    return None
                with use_wcl_credentials(credentials):
                    result = search_raid_cooldowns(self.read_json_body())
                return self.send_response_body(*json_bytes(result))
            if path == "/api/single-fight/analyze":
                credentials = self.require_wcl_credentials(user)
                if not credentials:
                    return None
                payload = self.read_json_body()
                report_code = str(payload.get("reportCode") or "").strip()
                fight_id = int(payload.get("fightID") or 0)
                if not re.fullmatch(r"[A-Za-z0-9]+", report_code) or fight_id <= 0:
                    raise ValueError("请选择有效的 report 与 Fight。")
                payload["reportCode"] = report_code
                payload["fightID"] = fight_id
                prune_analysis_storage()
                job = Job(id=uuid.uuid4().hex[:12], owner_user_id=user["id"])
                with JOBS_LOCK:
                    JOBS[job.id] = job
                thread = threading.Thread(
                    target=run_single_fight_job,
                    args=(job, payload, credentials),
                    daemon=True,
                )
                thread.start()
                return self.send_response_body(*json_bytes({
                    "jobId": job.id,
                    "eventsUrl": f"/api/jobs/{job.id}/events",
                    "statusUrl": f"/api/jobs/{job.id}/status",
                    "resultUrl": job_result_url(job.id),
                    "downloadUrl": job_result_url(job.id, download=True),
                }, HTTPStatus.ACCEPTED))
            if path != "/api/analyze":
                return self.json_error("not found", HTTPStatus.NOT_FOUND)

            credentials = self.require_wcl_credentials(user)
            if not credentials:
                return None
            payload = self.read_json_body()
            version = str(payload.get("version") or "").strip()
            raid = str(payload.get("raid") or "").strip()
            boss = str(payload.get("boss") or "").strip()
            report_ids = str(payload.get("reportIds") or "").strip()
            if not all([version, raid, boss, report_ids]):
                raise ValueError("请选择版本、副本、Boss，并填写 WCL report id。")
            entry = find_boss(version, raid, boss)
            if not entry.supported:
                raise ValueError(f"{entry.boss_name} {entry.disabled_reason or '暂未接入在线分析'}")

            job = Job(id=uuid.uuid4().hex[:12], owner_user_id=user["id"])
            with JOBS_LOCK:
                JOBS[job.id] = job
            thread = threading.Thread(target=run_job, args=(job, payload, credentials), daemon=True)
            thread.start()
            return self.send_response_body(*json_bytes({
                "jobId": job.id,
                "eventsUrl": f"/api/jobs/{job.id}/events",
                "statusUrl": f"/api/jobs/{job.id}/status",
                "resultUrl": job_result_url(job.id),
                "downloadUrl": job_result_url(job.id, download=True),
            }, HTTPStatus.ACCEPTED))
        except raid_calendar_store.LootConflictWarning as warning:
            return self.send_response_body(*json_bytes({
                "error": "该分配存在需求权提醒，请确认后继续。",
                "requiresConfirmation": True,
                "warnings": warning.warnings,
            }, HTTPStatus.CONFLICT))
        except Exception as exc:
            return self.json_error(str(exc), HTTPStatus.BAD_REQUEST)

    def require_wcl_credentials(self, user):
        credentials = AUTH.get_wcl_credentials(user["id"])
        if not credentials:
            self.json_error("请先在账号设置中保存你自己的 WCL API 凭据。", HTTPStatus.PRECONDITION_REQUIRED)
        return credentials

    def handle_export_verdict_excel(self):
        try:
            from urllib.parse import quote

            from tools.export_verdict_excel import export_verdict_excel, resolve_export_dir

            payload = self.read_json_body()
            out_dir = resolve_export_dir(Path.home() / "Desktop")
            out_path = export_verdict_excel(payload, out_dir, boss_name="宇宙之冕")
            body = out_path.read_bytes()
            # HTTP headers are latin-1 only; keep ASCII filename= and RFC5987 filename*.
            ascii_name = "verdict_export.xlsx"
            disp = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(out_path.name)}"
            self.send_response(HTTPStatus.OK)
            self.send_header(
                "Content-Type",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            self.send_header("Content-Disposition", disp)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            return self.send_response_body(
                *json_bytes({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            )

    def handle_events(self, path, user):
        job_id = path.split("/")[3]
        job = JOBS.get(job_id)
        if not job or (job.owner_user_id != user["id"] and not user["isAdmin"]):
            return self.json_error("not found", HTTPStatus.NOT_FOUND)

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        subscriber = queue.Queue()
        job.subscribers.append(subscriber)
        try:
            for event in job.events:
                self.write_sse(event)
            while job.status in {"queued", "running"}:
                try:
                    event = subscriber.get(timeout=12)
                    self.write_sse(event)
                except queue.Empty:
                    self.write_sse({
                        "type": "heartbeat",
                        "status": job.status,
                        "percent": job.percent,
                        "message": job.message,
                        "stage": job.stage,
                        "jobId": job.id,
                    })
            if job.events:
                self.write_sse(job.events[-1])
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            if subscriber in job.subscribers:
                job.subscribers.remove(subscriber)

    def handle_job_status(self, path, user):
        job_id = path.split("/")[3]
        job = JOBS.get(job_id)
        stored_result = stored_job_result(job_id, user)
        if not job and stored_result:
            return self.send_response_body(*json_bytes({
                "type": "done",
                "jobId": job_id,
                "status": "done",
                "percent": 100,
                "message": "分析结果已从任务缓存恢复",
                "stage": "done",
                "resultUrl": job_result_url(job_id),
                "downloadUrl": job_result_url(job_id, download=True),
            }))
        if not job or (job.owner_user_id != user["id"] and not user["isAdmin"]):
            return self.json_error("not found", HTTPStatus.NOT_FOUND)
        payload = {
            "type": "error" if job.status == "error" else ("done" if job.status == "done" else "progress"),
            "jobId": job.id,
            "status": job.status,
            "percent": job.percent,
            "message": job.error or job.message,
            "stage": job.stage,
        }
        if job.status == "done":
            payload["resultUrl"] = job_result_url(job.id)
            payload["downloadUrl"] = job_result_url(job.id, download=True)
        return self.send_response_body(*json_bytes(payload))

    def handle_result(self, path, user):
        job_id = path.split("/")[3]
        job = JOBS.get(job_id)
        if job and job.owner_user_id != user["id"] and not user["isAdmin"]:
            return self.json_error("not found", HTTPStatus.NOT_FOUND)
        if job and job.status != "done":
            return self.send_response_body(*json_bytes({"error": "结果尚未生成"}, HTTPStatus.CONFLICT))
        result_path = stored_job_result(job_id, user)
        if not result_path and job and job.status == "done" and job.result_path and job.result_path.exists():
            result_path = job.result_path
        if not result_path:
            if not job:
                return self.json_error("not found", HTTPStatus.NOT_FOUND)
            return self.send_response_body(*json_bytes({"error": "结果尚未生成"}, HTTPStatus.CONFLICT))
        body = result_path.read_bytes()
        query = parse_qs(urlparse(self.path).query)
        if (query.get("download") or [""])[0] not in {"1", "true", "yes"}:
            return self.send_response_body(HTTPStatus.OK, "application/json; charset=utf-8", body)
        filename = f"wcl-analysis-{job_id}.json"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_security_headers()
        self.end_headers()
        self.wfile.write(body)

    def handle_static(self, path, public=False):
        path = normalize_static_request_path(path)
        route_map = {
            "/": "/index.html",
            "/login": "/frontend/auth/login.html",
            "/account": "/frontend/auth/account.html",
            "/online": "/frontend/tools/analysis-runner/index.html",
            "/single-fight": "/frontend/tools/single-fight/index.html",
            "/spec-compare": "/frontend/tools/spec-comparison/index.html",
            "/report": "/frontend/report/index.html",
            "/raid-calendar": "/frontend/tools/raid-calendar/index.html",
            "/loot": "/frontend/tools/raid-calendar/index.html",
            "/cooldowns": "/frontend/tools/raid-cooldowns/index.html",
            "/mythic-dungeon": "/frontend/tools/mythic-dungeon/index.html",
            "/raid-guide": "/frontend/tools/raid-guide/index.html",
            "/frontend/tools/raid-guide": "/frontend/tools/raid-guide/index.html",
            "/audit": "/frontend/report/plugins/void_spire/crown_of_the_cosmos/audit.html",
            "/LuraJudgement.html": "/frontend/report/index.html",
        }
        path = route_map.get(path, path)
        allowed = (
            path in {"/index.html", "/boss_catalog.json", "/spec_catalog.json"}
            or path.startswith("/assets/")
            or (
                path.startswith("/boss_plugins/assets/")
                and Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}
            )
            or path.startswith("/frontend/")
            or path.startswith("/data/")
        )
        if public and path != "/frontend/auth/login.html":
            allowed = False
        if not allowed or any(part.startswith(".") for part in Path(path).parts):
            return self.send_error(HTTPStatus.NOT_FOUND)
        target = (ROOT / path.lstrip("/")).resolve()
        if ROOT not in target.parents and target != ROOT:
            return self.send_error(HTTPStatus.FORBIDDEN)
        if not target.exists() or not target.is_file():
            return self.send_error(HTTPStatus.NOT_FOUND)
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        return self.send_response_body(HTTPStatus.OK, content_type, target.read_bytes())

    def write_sse(self, event):
        self.wfile.write(f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8"))
        self.wfile.flush()

    def secure_cookie_suffix(self):
        forwarded_proto = self.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip().lower()
        return "; Secure" if forwarded_proto == "https" else ""

    def cookie_value(self, token):
        max_age = AUTH.session_seconds
        return (
            f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; "
            f"Max-Age={max_age}{self.secure_cookie_suffix()}"
        )

    def redirect(self, location):
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.send_security_headers()
        self.end_headers()

    def redirect_resource(self, location):
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "public, max-age=3600")
        self.send_security_headers()
        self.end_headers()

    def json_error(self, message, status):
        return self.send_response_body(*json_bytes({"error": str(message)}, status))

    def send_security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")

    def send_response_body(self, status, content_type, body, cookie=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Cache-Control", "no-store" if "html" in content_type or "json" in content_type else "private, max-age=300")
        self.send_security_headers()
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"[server] {self.address_string()} {fmt % args}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Mythic Analyzer web application server")
    parser.add_argument(
        "--host",
        default=environment_setting("APP_HOST", "0.0.0.0"),
        help="监听地址；默认读取 APP_HOST，并监听所有网络接口",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(environment_setting("APP_PORT", environment_setting("PORT", "8765"))),
        help="监听端口；默认读取 APP_PORT/PORT，回退到 8765",
    )
    parser.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    args = parser.parse_args()

    httpd = ThreadingHTTPServer((args.host, args.port), AnalyzerHandler)
    browser_host = "127.0.0.1" if args.host in {"0.0.0.0", "::"} else args.host
    url = f"http://{browser_host}:{args.port}/"
    print(f"完整 Web 服务已启动：{url}（监听 {args.host}:{args.port}）", flush=True)
    if args.open:
        webbrowser.open(url)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
