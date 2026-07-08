import argparse
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
from urllib.parse import unquote, urlparse

from analyzer_core.catalog import find_boss, to_frontend_catalog
from analyzer_core.concurrency import MAX_JOB_THREADS
from analyzer_core.runner import analyze_report


ROOT = Path(__file__).resolve().parent
JOB_DIR = ROOT / ".analysis_jobs"
JOB_DIR.mkdir(exist_ok=True)

FIGHT_RE = re.compile(r"分析 Fight .*?\((\d+)/(\d+)\)")
COMPLETED_FIGHTS_RE = re.compile(r"已完成\s+(\d+)/(\d+)\s+场")
MATCHED_FIGHTS_RE = re.compile(r"匹配到\s+(\d+)\s+场")


@dataclass
class Job:
    id: str
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


def run_job(job: Job, payload: dict):
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
        output_path = JOB_DIR / f"{job.id}.json"

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
    server_version = "MythicAnalyzer/0.1"

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/catalog":
            return self.send_response_body(*json_bytes(to_frontend_catalog()))
        if path.startswith("/api/jobs/") and path.endswith("/events"):
            return self.handle_events(path)
        if path.startswith("/api/jobs/") and path.endswith("/result"):
            return self.handle_result(path)
        return self.handle_static(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/analyze":
            return self.send_error(HTTPStatus.NOT_FOUND)

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            version = str(payload.get("version") or "").strip()
            raid = str(payload.get("raid") or "").strip()
            boss = str(payload.get("boss") or "").strip()
            report_ids = str(payload.get("reportIds") or "").strip()
            if not all([version, raid, boss, report_ids]):
                raise ValueError("请选择版本、副本、Boss，并填写 WCL report id。")

            entry = find_boss(version, raid, boss)
            if not entry.supported:
                raise ValueError(f"{entry.boss_name} {entry.disabled_reason or '暂未接入在线分析'}")

            job = Job(id=uuid.uuid4().hex[:12])
            with JOBS_LOCK:
                JOBS[job.id] = job
            thread = threading.Thread(target=run_job, args=(job, payload), daemon=True)
            thread.start()
            return self.send_response_body(*json_bytes({
                "jobId": job.id,
                "eventsUrl": f"/api/jobs/{job.id}/events",
                "resultUrl": f"/api/jobs/{job.id}/result",
            }, HTTPStatus.ACCEPTED))
        except Exception as exc:
            return self.send_response_body(*json_bytes({"error": str(exc)}, HTTPStatus.BAD_REQUEST))

    def handle_events(self, path):
        job_id = path.split("/")[3]
        job = JOBS.get(job_id)
        if not job:
            return self.send_error(HTTPStatus.NOT_FOUND)

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

    def handle_result(self, path):
        job_id = path.split("/")[3]
        job = JOBS.get(job_id)
        if not job:
            return self.send_error(HTTPStatus.NOT_FOUND)
        if job.status != "done" or not job.result_path or not job.result_path.exists():
            return self.send_response_body(*json_bytes({"error": "结果尚未生成"}, HTTPStatus.CONFLICT))
        body = job.result_path.read_bytes()
        return self.send_response_body(HTTPStatus.OK, "application/json; charset=utf-8", body)

    def handle_static(self, path):
        route_map = {
            "/": "/index.html",
            "/online": "/online.html",
            "/report": "/report.html",
            "/LuraJudgement.html": "/report.html",
        }
        path = route_map.get(path, path)
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

    def send_response_body(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
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
