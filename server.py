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
import webbrowser
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlencode, urlparse

from analyzer_core.auth_store import AuthError, default_auth_store, validate_password
from analyzer_core.catalog import find_boss, to_frontend_catalog
from analyzer_core.concurrency import MAX_JOB_THREADS
from analyzer_core.runner import analyze_report
from analyzer_core import loot_store
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
VERDICT_DIR = ROOT / "verdicts"
VERDICT_DIR.mkdir(exist_ok=True)
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
_DESKTOP = Path.home() / "Desktop"
DEFAULT_EXPORT_EXCEL_DIR = _DESKTOP if _DESKTOP.is_dir() else VERDICT_DIR
AUTH = default_auth_store()
SESSION_COOKIE = "wra_session"
MAX_JSON_BODY = 10 * 1024 * 1024
LOGIN_ATTEMPTS: Dict[str, List[float]] = {}
LOGIN_ATTEMPTS_LOCK = threading.Lock()
REGISTRATION_ATTEMPTS: Dict[str, List[float]] = {}
REGISTRATION_ATTEMPTS_LOCK = threading.Lock()
INVITE_CODE = environment_setting("APP_INVITE_CODE")

FIGHT_RE = re.compile(r"分析 Fight .*?\((\d+)/(\d+)\)")
COMPLETED_FIGHTS_RE = re.compile(r"已完成\s+(\d+)/(\d+)\s+场")
MATCHED_FIGHTS_RE = re.compile(r"匹配到\s+(\d+)\s+场")


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


JOBS: Dict[str, Job] = {}
JOBS_LOCK = threading.Lock()
JOB_SEMAPHORE = threading.BoundedSemaphore(MAX_JOB_THREADS)


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
        set_job_progress(job, percent=percent, message=message or job.message, stage=stage or job.stage)
        return

    if "连接 WCL 鉴权端点" in message:
        set_job_progress(job, percent=8, message="连接 WCL 并验证凭据", stage="auth")
        return
    if message.startswith("读取日志"):
        set_job_progress(job, percent=12, message="读取日志基础信息", stage="fetch")
        return

    matched = MATCHED_FIGHTS_RE.search(message)
    if matched:
        set_job_progress(job, percent=18, message=f"匹配到 {matched.group(1)} 场开荒记录", stage="match")
        return

    fight = FIGHT_RE.search(message)
    if fight:
        index = int(fight.group(1))
        total = max(1, int(fight.group(2)))
        percent = 20 + round(index / total * 68)
        set_job_progress(job, percent=percent, message=f"分析战斗 {index}/{total}", stage="analyze")
        return

    completed = COMPLETED_FIGHTS_RE.search(message)
    if completed:
        count = int(completed.group(1))
        total = max(1, int(completed.group(2)))
        percent = 20 + round(count / total * 68)
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
            "resultUrl": f"/api/jobs/{job.id}/result",
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
            "resultUrl": f"/api/jobs/{job.id}/result",
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


def json_bytes(data, status=HTTPStatus.OK):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return status, "application/json; charset=utf-8", body


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
    server_version = "MythicAnalyzer/0.2"

    def do_GET(self):
        path = self.request_path()
        if path == "/login":
            if self.current_user():
                return self.redirect("/online")
            return self.handle_static(path, public=True)

        if path == "/api/auth/config":
            return self.send_response_body(*json_bytes({
                "registrationRequiresInvite": bool(INVITE_CODE),
            }))

        tooltip_match = re.fullmatch(r"/wowhead-tooltip/tooltip/spell/(\d+)", path)
        if tooltip_match:
            from boss_plugins.venomous_abyss.shared import local_spell_tooltip

            return self.send_response_body(*json_bytes(
                local_spell_tooltip(int(tooltip_match.group(1)))
            ))

        user = self.require_user(path)
        if not user:
            return None
        if path == "/api/auth/me":
            return self.send_response_body(*json_bytes({
                "user": user,
                "wcl": AUTH.wcl_summary(user["id"]),
            }))
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
            return self.send_response_body(*json_bytes({
                "schemaVersion": config["schemaVersion"],
                "guild": config["guild"],
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
            with use_wcl_credentials(credentials):
                return self.send_response_body(*json_bytes(recent_guild_reports(
                    selected_date=selected_date, limit=limit,
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
        if path == "/api/loot":
            query = parse_qs(urlparse(self.path).query)
            selected_date = (query.get("date") or [None])[0]
            difficulty = (query.get("difficulty") or ["heroic"])[0]
            try:
                document = loot_store.load_document(selected_date, difficulty)
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
        admin_delete_match = re.fullmatch(r"/api/admin/users/(\d+)", path)
        if admin_delete_match:
            return self.handle_admin_delete(user, int(admin_delete_match.group(1)))
        if not user["canModify"]:
            return self.json_error("当前账号只有只读权限。", HTTPStatus.FORBIDDEN)
        allocation_match = re.fullmatch(r"/api/loot/allocations/([A-Za-z0-9_-]+)", path)
        if allocation_match:
            try:
                return self.send_response_body(*json_bytes(loot_store.delete_allocation(allocation_match.group(1))))
            except ValueError as error:
                return self.json_error(str(error), HTTPStatus.NOT_FOUND)
        blackmark_match = re.fullmatch(r"/api/loot/blackmarks/([A-Za-z0-9_-]+)", path)
        if blackmark_match:
            try:
                return self.send_response_body(*json_bytes(loot_store.delete_blackmark(blackmark_match.group(1))))
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

    def handle_wcl_credentials_test(self, user):
        try:
            credentials = AUTH.get_wcl_credentials(user["id"])
            if not credentials:
                return self.json_error("尚未配置 WCL 凭据，请先保存再测试。", HTTPStatus.BAD_REQUEST)
            from analyzer_core.single_fight import load_single_fight_config
            from analyzer_core.wcl_api import WclClient
            client = WclClient()
            with use_wcl_credentials(credentials):
                client.token()
                guild_id = int(load_single_fight_config()["guild"]["id"])
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
            if path == "/api/loot/setup":
                return self.send_response_body(*json_bytes(loot_store.save_setup(self.read_json_body())))
            if path == "/api/loot/settings":
                if not user["isAdmin"]:
                    return self.json_error("仅管理员可以修改史诗难度刷新设置。", HTTPStatus.FORBIDDEN)
                return self.send_response_body(*json_bytes(loot_store.save_settings(self.read_json_body())))
            if path == "/api/loot/allocations":
                return self.send_response_body(*json_bytes(loot_store.add_allocation(self.read_json_body())))
            if path == "/api/loot/blackmarks":
                return self.send_response_body(*json_bytes(loot_store.add_blackmark(self.read_json_body())))
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
                    "resultUrl": f"/api/jobs/{job.id}/result",
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
                "resultUrl": f"/api/jobs/{job.id}/result",
            }, HTTPStatus.ACCEPTED))
        except loot_store.LootConflictWarning as warning:
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
            payload["resultUrl"] = f"/api/jobs/{job.id}/result"
        return self.send_response_body(*json_bytes(payload))

    def handle_result(self, path, user):
        job_id = path.split("/")[3]
        job = JOBS.get(job_id)
        if not job or (job.owner_user_id != user["id"] and not user["isAdmin"]):
            return self.json_error("not found", HTTPStatus.NOT_FOUND)
        if job.status != "done" or not job.result_path or not job.result_path.exists():
            return self.send_response_body(*json_bytes({"error": "结果尚未生成"}, HTTPStatus.CONFLICT))
        body = job.result_path.read_bytes()
        return self.send_response_body(HTTPStatus.OK, "application/json; charset=utf-8", body)

    def handle_static(self, path, public=False):
        route_map = {
            "/": "/index.html",
            "/login": "/frontend/auth/login.html",
            "/account": "/frontend/auth/account.html",
            "/online": "/frontend/tools/analysis-runner/index.html",
            "/single-fight": "/frontend/tools/single-fight/index.html",
            "/spec-compare": "/frontend/tools/spec-comparison/index.html",
            "/report": "/frontend/report/index.html",
            "/loot": "/frontend/tools/raid-loot/index.html",
            "/cooldowns": "/frontend/tools/raid-cooldowns/index.html",
            "/mythic-dungeon": "/frontend/tools/mythic-dungeon/index.html",
            "/raid-guide": "/frontend/tools/raid-guide/index.html",
            "/audit": "/frontend/report/plugins/void_spire/crown_of_the_cosmos/audit.html",
            "/LuraJudgement.html": "/frontend/report/index.html",
        }
        path = route_map.get(path, path)
        allowed = (
            path in {"/index.html", "/boss_catalog.json", "/spec_catalog.json"}
            or path.startswith("/assets/")
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
