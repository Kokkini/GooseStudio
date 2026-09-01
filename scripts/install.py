#!/usr/bin/env python3
"""Install or repair Goose Studio in the active Modal workspace."""

import argparse
import json
import os
import queue
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODAL_CLI = Path(os.environ["GOOSE_STUDIO_MODAL_CLI"]) if os.getenv("GOOSE_STUDIO_MODAL_CLI") else None

for stream in (sys.stdout, sys.stderr):
    if stream is not None and hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def run(*args: str, capture: bool = False) -> str:
    environment = os.environ.copy()
    environment.setdefault("PYTHONUTF8", "1")
    environment.setdefault("PYTHONIOENCODING", "utf-8")
    result = subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=capture,
        env=environment,
    )
    return result.stdout.strip() if capture else ""


def run_modal(*args: str, capture: bool = False) -> str:
    command = str(MODAL_CLI) if MODAL_CLI else "modal"
    return run(command, *args, capture=capture)


def run_bootstrap_with_progress() -> None:
    command = [str(MODAL_CLI) if MODAL_CLI else "modal", "run", str(ROOT / "modal" / "bootstrap.py")]
    environment = os.environ.copy()
    environment.setdefault("PYTHONUTF8", "1")
    environment.setdefault("PYTHONIOENCODING", "utf-8")
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
    output_queue: queue.Queue[str | None] = queue.Queue()

    def read_output() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            output_queue.put(line)
        output_queue.put(None)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    captured: list[str] = []
    reader_finished = False
    started = time.monotonic()
    next_heartbeat = started

    while not reader_finished or process.poll() is None:
        while True:
            try:
                line = output_queue.get_nowait()
            except queue.Empty:
                break
            if line is None:
                reader_finished = True
                break
            captured.append(line)
            for output_line in re.split(r"[\r\n]+", line):
                if output_line:
                    print(output_line, flush=True)

        now = time.monotonic()
        if now >= next_heartbeat:
            elapsed = int(now - started)
            duration = f"{elapsed // 60}m elapsed" if elapsed >= 60 else "less than a minute elapsed"
            print(f"[setup] Model download still running ({duration}; progress appears below)", flush=True)
            next_heartbeat = now + 15
        if not reader_finished or process.poll() is None:
            time.sleep(0.25)

    reader.join(timeout=1)
    returncode = process.wait()
    while True:
        try:
            line = output_queue.get_nowait()
        except queue.Empty:
            break
        if line is None:
            continue
        captured.append(line)
        for output_line in re.split(r"[\r\n]+", line):
            if output_line:
                print(output_line, flush=True)
    if returncode:
        raise subprocess.CalledProcessError(returncode, command, output="".join(captured))


def _redact(value: str) -> str:
    redacted = value
    for name in (
        "MODAL_TOKEN_ID",
        "MODAL_TOKEN_SECRET",
        "GOOSE_STUDIO_EXISTING_API_KEY",
        "GOOSE_STUDIO_API_KEY",
    ):
        secret = os.getenv(name)
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    return redacted


def _command_details(error: subprocess.CalledProcessError) -> str:
    parts = []
    for output in (error.stderr, error.stdout, getattr(error, "output", None)):
        if output:
            value = _redact(str(output)).strip()
            if value and value not in parts:
                parts.append(value)
    return "\n".join(parts)


def _failure_summary(error: BaseException) -> str:
    if isinstance(error, subprocess.CalledProcessError):
        details = _command_details(error)
        detail_line = next(
            (
                line.strip()
                for line in details.splitlines()
                if line.strip() and not line.strip().startswith(("Traceback", "File "))
            ),
            "",
        )
        suffix = f": {detail_line}" if detail_line else ""
        return f"Modal command failed with exit code {error.returncode}{suffix}"
    message = _redact(str(error)).strip()
    return f"Setup failed: {message or error.__class__.__name__}"


def _report_failure(error: BaseException) -> None:
    print(f"[error] {_failure_summary(error)}", file=sys.stderr, flush=True)
    if isinstance(error, subprocess.CalledProcessError):
        details = _command_details(error)
        if details:
            print(details, file=sys.stderr, flush=True)


def validate_modal() -> None:
    try:
        run_modal("app", "list", capture=True)
    except FileNotFoundError as exc:
        raise SystemExit(
            "Modal CLI is not installed. Install requirements-setup.txt and try again."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            "Modal rejected the supplied token. Create a new token and paste the complete command."
        ) from exc


def _default_environment_from_settings(value: object) -> str | None:
    if isinstance(value, dict):
        for key in ("default_environment", "defaultEnvironment", "default-environment"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        for nested in value.values():
            result = _default_environment_from_settings(nested)
            if result:
                return result
    elif isinstance(value, list):
        for nested in value:
            result = _default_environment_from_settings(nested)
            if result:
                return result
    return None


def resolve_modal_environment() -> str:
    configured = os.getenv("MODAL_ENVIRONMENT", "").strip()
    if configured:
        return configured
    try:
        settings = json.loads(run_modal("workspace", "settings", "list", "--json", capture=True))
        return _default_environment_from_settings(settings) or "main"
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError, TypeError, ValueError):
        return "main"


def deploy() -> str:
    output = run_modal("deploy", str(ROOT / "modal" / "goose_studio_executor.py"), capture=True)
    print(output, flush=True)
    label = "goose-studio-api"
    match = re.search(rf"https://[^\s]+--{label}\.modal\.run", output)
    if not match:
        raise RuntimeError("Could not discover the deployed Modal endpoint")
    return match.group(0)


def volume_has_installation(volume_name: str) -> bool:
    try:
        run_modal("volume", "ls", volume_name, "/installation.json", capture=True)
        return True
    except subprocess.CalledProcessError:
        return False


def volume_exists(volume_name: str) -> bool:
    try:
        run_modal("volume", "ls", volume_name, "/", capture=True)
        return True
    except subprocess.CalledProcessError:
        return False


def migrate_volume(old_name: str, new_name: str) -> bool:
    if volume_exists(new_name) or not volume_exists(old_name):
        return False
    print(f"[setup] Renaming existing Volume {old_name} to {new_name}...", flush=True)
    run_modal("volume", "rename", "--yes", old_name, new_name)
    return True


def create_application_secret(name: str, api_key: str) -> None:
    path = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as destination:
            json.dump({"GOOSE_STUDIO_API_KEY": api_key}, destination)
            path = Path(destination.name)
        path.chmod(0o600)
        run_modal("secret", "create", "--force", name, "--from-json", str(path))
    finally:
        if path:
            path.unlink(missing_ok=True)


def write_local_config(endpoint: str, api_key: str, workspace: str, environment: str) -> None:
    path = ROOT / ".env.local"
    path.write_text(
        f"GOOSE_STUDIO_ENDPOINT={endpoint}\nGOOSE_STUDIO_API_KEY={api_key}\n"
        f"GOOSE_STUDIO_WORKSPACE={workspace}\nGOOSE_STUDIO_ENVIRONMENT={environment}\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def check_endpoint(endpoint: str) -> None:
    with urllib.request.urlopen(f"{endpoint}/health", timeout=30) as response:
        if json.load(response).get("status") != "ok":
            raise RuntimeError("Deployed endpoint health check failed")


def main() -> None:
    global ROOT, MODAL_CLI
    parser = argparse.ArgumentParser()
    parser.add_argument("--force-assets", action="store_true")
    parser.add_argument("--resource-root", type=Path)
    parser.add_argument("--modal-cli", type=Path)
    parser.add_argument("--emit-config", action="store_true")
    args = parser.parse_args()
    if args.resource_root:
        ROOT = args.resource_root.resolve()
    if args.modal_cli:
        MODAL_CLI = args.modal_cli.resolve()
    required = (ROOT / "modal" / "bootstrap.py", ROOT / "modal" / "goose_studio_executor.py", ROOT / "assets" / "models.json", ROOT / "assets" / "allowed-node-classes.json", ROOT / "tools" / "voxelize_glb.py")
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        parser.error(f"Missing packaged resources: {', '.join(missing)}")
    if MODAL_CLI and not MODAL_CLI.is_file():
        parser.error(f"Modal CLI not found: {MODAL_CLI}")
    app_name = "goose-studio"

    print('[progress] {"stage":"credentials","current":0,"total":1,"message":"Validating Modal credentials"}', flush=True)
    validate_modal()
    print('[progress] {"stage":"credentials","current":1,"total":1,"message":"Modal credentials verified"}', flush=True)
    api_key = os.getenv("GOOSE_STUDIO_EXISTING_API_KEY") or secrets.token_urlsafe(32)
    workspace = os.getenv("GOOSE_STUDIO_WORKSPACE", "").strip()
    environment = resolve_modal_environment()
    os.environ["MODAL_ENVIRONMENT"] = environment

    print('[progress] {"stage":"resources","current":0,"total":1,"message":"Preparing your Modal resources"}', flush=True)
    print("[setup] Creating application credentials...", flush=True)
    create_application_secret(f"{app_name}-api-key", api_key)

    renamed_volumes = []
    try:
        for suffix in ("assets", "io"):
            old_name = f"free-video-gen-{suffix}"
            new_name = f"{app_name}-{suffix}"
            if migrate_volume(old_name, new_name):
                renamed_volumes.append((old_name, new_name))

        should_bootstrap = args.force_assets or not volume_has_installation(f"{app_name}-assets")
        print('[progress] {"stage":"resources","current":1,"total":1,"message":"Modal resources ready"}', flush=True)
        if should_bootstrap:
            print('[progress] {"stage":"models","current":0,"total":1,"message":"Starting model download in Modal"}', flush=True)
            run_bootstrap_with_progress()
            print('[progress] {"stage":"models","current":1,"total":1,"message":"Models downloaded and verified"}', flush=True)
        else:
            print("[setup] Assets already installed; skipping model bootstrap.", flush=True)

        print('[progress] {"stage":"deploy","current":0,"total":1,"message":"Deploying your GPU app"}', flush=True)
        endpoint = deploy()
        print("[setup] Verifying the deployed endpoint...", flush=True)
        check_endpoint(endpoint)
    except Exception:
        for old_name, new_name in reversed(renamed_volumes):
            if volume_exists(new_name) and not volume_exists(old_name):
                print(f"[setup] Restoring Volume name {old_name} after setup failure...", flush=True)
                run_modal("volume", "rename", "--yes", new_name, old_name)
        raise
    print('[progress] {"stage":"deploy","current":1,"total":1,"message":"GPU app deployed and verified"}', flush=True)
    if args.emit_config:
        print(f"[result] {json.dumps({'endpoint': endpoint, 'apiKey': api_key, 'workspace': workspace, 'environment': environment})}", flush=True)
    else:
        write_local_config(endpoint, api_key, workspace, environment)
    print(f"[setup] Installed successfully: {endpoint}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(f"[error] {_redact(exc.code)}", file=sys.stderr, flush=True)
            raise SystemExit(1)
        raise
    except Exception as exc:
        _report_failure(exc)
        raise SystemExit(1)
