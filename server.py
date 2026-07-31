import argparse
from http.cookies import SimpleCookie
import json
import mimetypes
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
from urllib.parse import unquote, urlencode, urlparse

from analyzer_core.auth_store import AuthError, default_auth_store
from analyzer_core.catalog import find_boss, to_frontend_catalog
from analyzer_core.concurrency import MAX_JOB_THREADS
from analyzer_core.runner import analyze_report
from analyzer_core import notebook_store
from analyzer_core.wcl_context import WclCredentials, use_wcl_credentials


ROOT = Path(__file__).resolve().parent
JOB_DIR = ROOT / ".analysis_jobs"
JOB_DIR.mkdir(exist_ok=True)
VERDICT_DIR = ROOT / "verdicts"
VERDICT_DIR.mkdir(exist_ok=True)
SCOREBOARD_DIR = ROOT / "scoreboard"
SCOREBOARD_DIR.mkdir(exist_ok=True)
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


def json_bytes(data, status=HTTPStatus.OK):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return status, "application/json; charset=utf-8", body


class AnalyzerHandler(BaseHTTPRequestHandler):
    server_version = "MythicAnalyzer/0.2"

    def do_GET(self):
        path = self.request_path()
        if path == "/login":
            if self.current_user():
                return self.redirect("/")
            return self.handle_static(path, public=True)

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
        if path == "/api/raid-cooldowns/options":
            from analyzer_core.raid_cooldowns import options_document

            return self.send_response_body(*json_bytes(options_document()))
        if path.startswith("/api/jobs/") and path.endswith("/events"):
            return self.handle_events(path, user)
        if path.startswith("/api/jobs/") and path.endswith("/status"):
            return self.handle_job_status(path, user)
        if path.startswith("/api/jobs/") and path.endswith("/result"):
            return self.handle_result(path, user)
        if path in {"/api/notebook", "/api/scoreboard"}:
            return self.send_response_body(*json_bytes(notebook_store.load_store()))
        if path in {"/api/data/list", "/api/data-files"}:
            files = notebook_store.list_data_files()
            if path == "/api/data-files":
                return self.send_response_body(*json_bytes({"schemaVersion": 1, "files": files}))
            return self.send_response_body(*json_bytes(files))
        if path == "/api/data/latest":
            data = notebook_store.read_latest_data()
            if data is None:
                return self.json_error("no data json", HTTPStatus.NOT_FOUND)
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
        day_match = re.fullmatch(r"/api/(?:notebook|scoreboard)/(\d{4}-\d{2}-\d{2})", path)
        if day_match:
            day = notebook_store.get_day(day_match.group(1))
            if day is None:
                return self.json_error("day not found", HTTPStatus.NOT_FOUND)
            return self.send_response_body(*json_bytes(day))
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
        if not user["canModify"]:
            return self.json_error("当前账号只有只读权限。", HTTPStatus.FORBIDDEN)
        day_match = re.fullmatch(r"/api/(?:notebook|scoreboard)/(\d{4}-\d{2}-\d{2})", path)
        if day_match:
            return self.send_response_body(*json_bytes(notebook_store.delete_day(day_match.group(1))))
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
            return self.send_response_body(*json_bytes({"ok": True, "user": user}), cookie=self.cookie_value(token))
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
                *json_bytes({"ok": True, "user": user}, HTTPStatus.CREATED),
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

    def handle_write(self, path, user):
        if not user["canModify"]:
            return self.json_error("当前账号只有只读权限。", HTTPStatus.FORBIDDEN)
        try:
            if path == "/api/verdicts":
                return self.handle_save_verdict()
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
            if path in {"/api/notebook", "/api/scoreboard", "/api/notebook/store", "/api/scoreboard/store"}:
                return self.send_response_body(*json_bytes(notebook_store.save_store(self.read_json_body())))
            day_match = re.fullmatch(r"/api/(?:notebook|scoreboard)/(\d{4}-\d{2}-\d{2})", path)
            if day_match:
                return self.send_response_body(*json_bytes(notebook_store.put_day(day_match.group(1), self.read_json_body())))
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

    def handle_save_verdict(self):
        try:
            payload = self.read_json_body()
            date = str(payload.get("progressDate") or payload.get("date") or "").strip()
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
                raise ValueError("progressDate 必须是 YYYY-MM-DD")
            # Prefer notebook DB day upsert when payload looks like scoreboard day
            if payload.get("players") and any(isinstance(p, dict) and p.get("mechanics") for p in payload.get("players") or []):
                return self.send_response_body(*json_bytes(notebook_store.put_day(date, payload)))
            slim = {
                "schemaVersion": 2,
                "module": "final_verdict",
                "progressDate": date,
                "date": date,
                "sourceReports": payload.get("sourceReports") or [],
                "sourceFile": payload.get("sourceFile") or "",
                "pointsPerCount": payload.get("pointsPerCount") or 10,
                "updatedAt": payload.get("updatedAt") or time.strftime("%Y-%m-%dT%H:%M:%S"),
                "players": [
                    {
                        "name": row.get("name"),
                        "recognitionCount": row.get("recognitionCount") or 0,
                        "recognitionReasons": row.get("recognitionReasons") or "",
                        "appealAcquittalCount": row.get("appealAcquittalCount") or 0,
                        "appealAcquittalReasons": row.get("appealAcquittalReasons") or "",
                        "iqLoss": row.get("iqLoss") or 0,
                    }
                    for row in (payload.get("players") or [])
                    if row.get("name")
                ],
            }
            path = VERDICT_DIR / f"verdict-{date}.json"
            path.write_text(json.dumps(slim, ensure_ascii=False, indent=2), encoding="utf-8")
            notebook_store.put_day(date, {
                "date": date,
                "sourceReports": slim["sourceReports"],
                "pointsPerCount": slim["pointsPerCount"],
                "tankMultiplier": 0.5,
                "updatedAt": slim["updatedAt"],
                "players": [],
                "legacyVerdict": slim["players"],
            })
            return self.send_response_body(*json_bytes({"ok": True, "path": str(path.relative_to(ROOT)).replace("\\", "/")}))
        except Exception as exc:
            return self.send_response_body(*json_bytes({"error": str(exc)}, HTTPStatus.BAD_REQUEST))

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
            "/report": "/frontend/report/index.html",
            "/scoreboard": "/frontend/tools/iq-notebook/index.html",
            "/verdict": "/frontend/tools/iq-notebook/index.html",
            "/cooldowns": "/frontend/tools/raid-cooldowns/index.html",
            "/raid-guide": "/frontend/tools/raid-guide/index.html",
            "/audit": "/frontend/report/plugins/void_spire/crown_of_the_cosmos/audit.html",
            "/LuraJudgement.html": "/frontend/report/index.html",
        }
        path = route_map.get(path, path)
        allowed = (
            path in {"/index.html", "/boss_catalog.json"}
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
    parser = argparse.ArgumentParser(description="Mythic Analyzer local web server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    args = parser.parse_args()

    httpd = ThreadingHTTPServer((args.host, args.port), AnalyzerHandler)
    url = f"http://{args.host}:{args.port}/"
    print(f"服务已启动：{url}", flush=True)
    if args.open:
        webbrowser.open(url)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
