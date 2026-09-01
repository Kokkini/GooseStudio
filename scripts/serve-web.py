#!/usr/bin/env python3
"""Serve the prototype UI and its localhost-only Modal setup bridge."""

import json
import os
import subprocess
import threading
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
ROOT = WEB.parent
SETUP = {"state": "idle", "lines": [], "returncode": None, "progress": None, "error": None}
SETUP_LOCK = threading.Lock()
APP_LOG_PATH = ROOT / "logs" / "goose-studio.log"
APP_LOG_LOCK = threading.Lock()
APP_LOG_MAX_BYTES = 2 * 1024 * 1024
APP_LOG_KEEP_CHARS = 1536 * 1024


def _redact_log(value: str) -> str:
    redacted = value
    for name in ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET", "GOOSE_STUDIO_EXISTING_API_KEY", "GOOSE_STUDIO_API_KEY"):
        secret = os.getenv(name)
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    return redacted


def append_app_log(message: str) -> None:
    clean = _redact_log(message.replace("\x00", "").rstrip())
    if not clean.strip():
        return
    entry = f"{datetime.now(timezone.utc).isoformat()} {clean}\n"
    try:
        with APP_LOG_LOCK:
            APP_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with APP_LOG_PATH.open("a", encoding="utf-8") as destination:
                destination.write(entry)
            if APP_LOG_PATH.stat().st_size > APP_LOG_MAX_BYTES:
                content = APP_LOG_PATH.read_text(encoding="utf-8")
                APP_LOG_PATH.write_text(content[-APP_LOG_KEEP_CHARS:], encoding="utf-8")
    except OSError:
        pass


def read_app_log() -> str:
    try:
        return APP_LOG_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except OSError:
        return ""


def runtime_config() -> dict:
    config = {"baseUrl": "", "apiKey": "", "modalWorkspace": "", "modalEnvironment": ""}
    env_file = ROOT / ".env.local"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith(("GOOSE_STUDIO_API_KEY=", "FREE_VIDEO_GEN_API_KEY=")):
                config["apiKey"] = line.split("=", 1)[1]
            elif line.startswith(("GOOSE_STUDIO_ENDPOINT=", "FREE_VIDEO_GEN_ENDPOINT=")):
                config["baseUrl"] = line.split("=", 1)[1]
            elif line.startswith("GOOSE_STUDIO_WORKSPACE="):
                config["modalWorkspace"] = line.split("=", 1)[1]
            elif line.startswith("GOOSE_STUDIO_ENVIRONMENT="):
                config["modalEnvironment"] = line.split("=", 1)[1]
    config["baseUrl"] = os.getenv("GOOSE_STUDIO_ENDPOINT", os.getenv("FREE_VIDEO_GEN_ENDPOINT", config["baseUrl"]))
    config["modalWorkspace"] = os.getenv("GOOSE_STUDIO_WORKSPACE", config["modalWorkspace"])
    config["modalEnvironment"] = os.getenv("GOOSE_STUDIO_ENVIRONMENT", os.getenv("MODAL_ENVIRONMENT", config["modalEnvironment"])) or "main"
    return config


def run_setup(token_id: str, token_secret: str, workspace: str, force_assets: bool) -> None:
    command = [os.sys.executable, str(ROOT / "scripts" / "install.py")]
    environment = os.environ.copy()
    environment["MODAL_TOKEN_ID"] = token_id
    environment["MODAL_TOKEN_SECRET"] = token_secret
    environment["GOOSE_STUDIO_WORKSPACE"] = workspace
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    if force_assets:
        command.append("--force-assets")
    try:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            append_app_log(line)
            with SETUP_LOCK:
                SETUP["lines"].append(line.rstrip())
                SETUP["lines"] = SETUP["lines"][-200:]
                if line.startswith("[error] "):
                    SETUP["error"] = line.removeprefix("[error] ").strip()
                if line.startswith("[progress] "):
                    try:
                        SETUP["progress"] = json.loads(line.removeprefix("[progress] "))
                    except json.JSONDecodeError:
                        pass
        returncode = process.wait()
        with SETUP_LOCK:
            SETUP["returncode"] = returncode
            SETUP["state"] = "completed" if returncode == 0 else "failed"
            if returncode != 0 and not SETUP["error"]:
                SETUP["error"] = f"Setup process exited with code {returncode}"
    except Exception as exc:
        append_app_log(f"Modal setup failed: {exc}")
        with SETUP_LOCK:
            SETUP["lines"].append(str(exc))
            SETUP["returncode"] = 1
            SETUP["state"] = "failed"
            SETUP["error"] = str(exc)


class Handler(SimpleHTTPRequestHandler):
    def send_json(self, value: dict, status: int = 200) -> None:
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/runtime-config.json":
            self.send_json(runtime_config())
            return
        if self.path == "/app-log":
            self.send_json({"content": read_app_log()})
            return
        if self.path == "/setup-status":
            with SETUP_LOCK:
                self.send_json(dict(SETUP))
            return
        super().do_GET()

    def do_POST(self):
        if self.path == "/app-log":
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 16 * 1024:
                self.send_json({"error": "Invalid app log entry"}, 400)
                return
            try:
                payload = json.loads(self.rfile.read(length))
                message = payload.get("message", "")
                if not isinstance(message, str):
                    raise ValueError
            except (json.JSONDecodeError, AttributeError, ValueError):
                self.send_json({"error": "Invalid app log entry"}, 400)
                return
            append_app_log(message)
            self.send_json({"state": "ok"})
            return
        if self.path != "/setup":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 64 * 1024:
            self.send_json({"error": "Invalid setup request"}, 400)
            return
        try:
            payload = json.loads(self.rfile.read(length))
            token_id = payload["tokenId"].strip()
            token_secret = payload["tokenSecret"].strip()
            if not token_id or not token_secret:
                raise ValueError
        except (json.JSONDecodeError, KeyError, AttributeError, ValueError):
            self.send_json({"error": "Modal token ID and secret are required"}, 400)
            return
        workspace = payload.get("workspace", "")
        if not isinstance(workspace, str):
            workspace = ""
        with SETUP_LOCK:
            if SETUP["state"] == "running":
                self.send_json({"error": "Setup is already running"}, 409)
                return
            SETUP.update({"state": "running", "lines": [], "returncode": None, "progress": {"stage": "credentials", "current": 0, "total": 1, "message": "Validating Modal credentials"}, "error": None})
        threading.Thread(
            target=run_setup,
            args=(token_id, token_secret, workspace.strip(), False),
            daemon=True,
        ).start()
        self.send_json({"state": "running"}, 202)


append_app_log("Goose Studio browser development bridge started")
print("Goose Studio setup bridge: http://localhost:4174")
ThreadingHTTPServer(("127.0.0.1", 4174), Handler).serve_forever()
