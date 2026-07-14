import argparse
import os
import threading
import webbrowser
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
