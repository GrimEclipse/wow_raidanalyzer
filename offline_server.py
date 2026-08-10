import argparse
import json
import os
import threading
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
ROUTES = {
    "/": "frontend/offline/index.html" if (ROOT / "frontend/offline/index.html").exists() else "index.html",
    "/report": "frontend/report/index.html",
    "/audit": "frontend/report/plugins/void_spire/crown_of_the_cosmos/audit.html",
    "/scoreboard": "frontend/tools/iq-notebook/index.html",
    "/verdict": "frontend/tools/iq-notebook/index.html",
    "/loot": "frontend/tools/raid-loot/index.html",
    "/recruitment": "frontend/tools/recruitment/index.html",
    "/cooldowns": "frontend/tools/raid-cooldowns/index.html",
    "/raid-guide": "frontend/tools/raid-guide/index.html",
}
VERDICT_DIR = ROOT / "verdicts"
VERDICT_DIR.mkdir(exist_ok=True)

# 默认写桌面；不可写时由 resolve_export_dir 回退到项目 verdicts/
DEFAULT_EXPORT_EXCEL_DIR = Path.home() / "Desktop"


class OfflineHandler(SimpleHTTPRequestHandler):
    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/raid-cooldowns/search":
            try:
                content_len = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(content_len) if content_len > 0 else b"{}"
                payload = json.loads(raw.decode("utf-8"))
                from analyzer_core.raid_cooldowns import search_raid_cooldowns

                body = json.dumps(
                    search_raid_cooldowns(payload),
                    ensure_ascii=False,
                ).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            except Exception as e:
                msg = json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8")
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)
                return
        if parsed.path == "/api/export-verdict-excel":
            try:
                content_len = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(content_len) if content_len > 0 else b"{}"
                payload = json.loads(raw.decode("utf-8"))
                from tools.export_verdict_excel import export_verdict_excel, resolve_export_dir

                from urllib.parse import quote

                out_path = export_verdict_excel(
                    payload,
                    resolve_export_dir(DEFAULT_EXPORT_EXCEL_DIR),
                    boss_name="宇宙之冕",
                )
                body = out_path.read_bytes()
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
                return
            except Exception as e:
                msg = json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8")
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)
                return
        return super().do_POST()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/raid-cooldowns/options":
            from analyzer_core.raid_cooldowns import options_document

            body = json.dumps(options_document(), ensure_ascii=False).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/data-files":
            try:
                from analyzer_core.wcl_paths import list_wcl_data_files
                files = list_wcl_data_files()
            except Exception:
                files = self._list_data_files_fallback()
            body = json.dumps({"schemaVersion": 1, "files": files}, ensure_ascii=False).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()

    def _list_data_files_fallback(self):
        files = []
        data_dir = ROOT / "data"
        if data_dir.is_dir():
            for path in sorted(data_dir.glob("wcl_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
                stat = path.stat()
                files.append({
                    "path": f"data/{path.name}",
                    "name": path.name,
                    "label": path.name,
                    "size": stat.st_size,
                    "mtime": int(stat.st_mtime),
                })
        files.sort(key=lambda row: row["mtime"], reverse=True)
        return files

    def translate_path(self, path):
        route = ROUTES.get(urlparse(path).path)
        if route:
            path = "/" + route
        return super().translate_path(path)

    def log_message(self, fmt, *args):
        print("[offline]", fmt % args)


def main():
    parser = argparse.ArgumentParser(description="WoW Raid Analyzer offline viewer")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    os.chdir(ROOT)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), OfflineHandler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Offline server at {url}")
    print(f"终审 Excel 导出目录: {DEFAULT_EXPORT_EXCEL_DIR}")
    if not args.no_open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
