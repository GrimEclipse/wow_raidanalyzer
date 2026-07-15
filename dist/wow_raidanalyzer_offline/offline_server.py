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
    "/": "offline_index.html" if (ROOT / "offline_index.html").exists() else "index.html",
    "/report": "report.html",
    "/verdict": "verdict.html",
    "/audit": "crown-fight-audit.html",
}


class OfflineHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
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
        legacy = ROOT / "wcl_hardcore_api.json"
        if legacy.is_file():
            stat = legacy.stat()
            files.append({
                "path": "wcl_hardcore_api.json",
                "name": legacy.name,
                "label": "wcl_hardcore_api.json（兼容默认）",
                "size": stat.st_size,
                "mtime": int(stat.st_mtime),
            })
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
    url = f"http://127.0.0.1:{args.port}/"
    if not args.no_open:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    print(f"Offline viewer: {url}")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), OfflineHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Offline viewer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
