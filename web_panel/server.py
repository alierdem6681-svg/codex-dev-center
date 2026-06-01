from __future__ import annotations

import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "web_panel" / "static"


class PanelHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self) -> None:
        if self.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            payload = {
                "system_state": read_json(ROOT / "state" / "system_state.json", {}),
                "workers": read_json(ROOT / "state" / "workers.json", {}),
                "tasks": read_json(ROOT / "state" / "task_queue.json", {"tasks": []}),
            }
            self.wfile.write(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
            return
        super().do_GET()


def read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8080), PanelHandler)
    print("Codex Dev Center panel: http://127.0.0.1:8080")
    server.serve_forever()


if __name__ == "__main__":
    main()
