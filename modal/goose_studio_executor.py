"""Generic ComfyUI executor deployed into each customer's Modal workspace."""

import hmac
import hashlib
import importlib.util
import json
import mimetypes
import os
import subprocess
import shutil
import threading
import time
import traceback
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path

import modal

APP_NAME = "goose-studio"
ASSETS_VOLUME_NAME = f"{APP_NAME}-assets"
IO_VOLUME_NAME = f"{APP_NAME}-io"
SECRET_NAME = f"{APP_NAME}-api-key"
RUNTIME_IMAGE = os.getenv(
    "GOOSE_STUDIO_IMAGE",
    "ghcr.io/kokkini/goose-studio-runtime@sha256:ae9b39249e6fc8db305cfeb13c8013552c58481a35f4584c6b24d95c15f2d085",
)
IMAGE_GPU_TYPE = os.getenv("GOOSE_STUDIO_IMAGE_GPU", "L40S")
VIDEO_GPU_TYPE = os.getenv("GOOSE_STUDIO_VIDEO_GPU", "H100")

ASSETS_ROOT = Path("/assets")
IO_ROOT = Path("/io")
COMFYUI_ROOT = Path("/comfyui")
COMFYUI_URL = "http://127.0.0.1:8188"
HUNYUAN_CACHE_ROOT = ASSETS_ROOT / "huggingface" / "hub"
HUNYUAN_ASSET_PATHS_FILE = ASSETS_ROOT / "hunyuan3d-assets.json"
HUNYUAN_SNAPSHOT_IDS = {"hunyuan3d-paint-pbr", "dinov2-giant"}
VOXEL_MIN_RESOLUTION = 1
VOXEL_MAX_RESOLUTION = 256
VOXELIZE_SCRIPT_FILE = Path(__file__).resolve().parents[1] / "tools" / "voxelize_glb.py"
VOXELIZE_SCRIPT_PATH = "/app/voxelize_glb.py"

app = modal.App(APP_NAME)
assets_volume = modal.Volume.from_name(ASSETS_VOLUME_NAME, create_if_missing=True)
io_volume = modal.Volume.from_name(IO_VOLUME_NAME, create_if_missing=True)

worker_image = (
    modal.Image.from_registry(RUNTIME_IMAGE, add_python="3.12")
    .add_local_file(str(VOXELIZE_SCRIPT_FILE), str(VOXELIZE_SCRIPT_PATH))
)
voxel_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "numpy==2.4.3",
        "trimesh==4.12.2",
        "pygltflib==1.16.5",
        "pillow==12.1.1",
    )
    .add_local_file(str(VOXELIZE_SCRIPT_FILE), str(VOXELIZE_SCRIPT_PATH))
)
ALLOWED_NODES_FILE = Path(__file__).resolve().parents[1] / "assets" / "allowed-node-classes.json"
MODEL_MANIFEST_FILE = Path(__file__).resolve().parents[1] / "assets" / "models.json"
HUNYUAN_ASSETS_SCRIPT_FILE = Path(__file__).resolve().with_name("download_hunyuan3d_assets.py")
if not HUNYUAN_ASSETS_SCRIPT_FILE.is_file():
    HUNYUAN_ASSETS_SCRIPT_FILE = Path(__file__).resolve().parents[1] / "scripts" / "download_hunyuan3d_assets.py"
api_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("fastapi[standard]", "python-multipart")
    .add_local_file(str(ALLOWED_NODES_FILE), "/app/allowed-node-classes.json")
    .add_local_file(str(MODEL_MANIFEST_FILE), "/app/models.json")
)
installer_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("huggingface-hub")
    .add_local_file(str(MODEL_MANIFEST_FILE), "/app/models.json")
    .add_local_file(str(HUNYUAN_ASSETS_SCRIPT_FILE), "/app/download_hunyuan3d_assets.py")
)

_COMFY_GENERATION: int | None = None


def _job_dir(job_id: str) -> Path:
    try:
        return IO_ROOT / "jobs" / str(uuid.UUID(job_id))
    except ValueError as exc:
        raise ValueError("Invalid job ID") from exc


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    temporary.replace(path)


def _save_status(job_id: str, value: dict) -> None:
    _atomic_json(_job_dir(job_id) / "status.json", value)


def _load_status(job_id: str) -> dict:
    return json.loads((_job_dir(job_id) / "status.json").read_text(encoding="utf-8"))


def _now() -> int:
    return int(time.time())


def _replace_with_symlink(destination: Path, source: Path) -> None:
    if destination.is_symlink():
        destination.unlink()
    elif destination.exists():
        backup = destination.with_name(f"{destination.name}.orig")
        if not backup.exists():
            destination.rename(backup)
        else:
            if destination.is_dir():
                import shutil

                shutil.rmtree(destination)
            else:
                destination.unlink()
    destination.symlink_to(source, target_is_directory=True)


def _setup_comfyui_paths() -> None:
    models = ASSETS_ROOT / "models"
    inputs = IO_ROOT / "input"
    outputs = IO_ROOT / "output"
    HUNYUAN_CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    for path in (models, inputs, outputs):
        path.mkdir(parents=True, exist_ok=True)
    _replace_with_symlink(COMFYUI_ROOT / "models", models)
    _replace_with_symlink(COMFYUI_ROOT / "input", inputs)
    _replace_with_symlink(COMFYUI_ROOT / "output", outputs)
    try:
        hunyuan_paths = json.loads(HUNYUAN_ASSET_PATHS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        hunyuan_paths = {}
    paint_model = hunyuan_paths.get("paint_model") or str(models / "hunyuan3d-paint")
    dino_model = hunyuan_paths.get("dino_model") or str(models / "dinov2-giant")
    # The Hunyuan 3D paint node loads these two components through diffusers
    # and transformers rather than through ComfyUI's model folders. Point the
    # forked node at the customer-owned assets Volume so a job never needs to
    # download them lazily from Hugging Face.
    os.environ["HF_HUB_CACHE"] = str(HUNYUAN_CACHE_ROOT)
    os.environ["HUNYUAN3D_PAINT_MODEL"] = paint_model
    os.environ["HUNYUAN3D_DINO_MODEL"] = dino_model


def _is_comfyui_running() -> bool:
    try:
        with urllib.request.urlopen(f"{COMFYUI_URL}/system_stats", timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def _start_comfyui() -> None:
    if _is_comfyui_running():
        return
    process = subprocess.Popen(
        ["python", str(COMFYUI_ROOT / "main.py"), "--listen", "127.0.0.1", "--port", "8188"]
    )
    for _ in range(300):
        if _is_comfyui_running():
            return
        if process.poll() is not None:
            raise RuntimeError(f"ComfyUI exited with code {process.returncode}")
        time.sleep(1)
    process.terminate()
    raise RuntimeError("ComfyUI did not start within five minutes")


def _installation() -> dict:
    try:
        return json.loads((ASSETS_ROOT / "installation.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"generation": 0, "installed_workflows": []}


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_hunyuan_asset_downloaders():
    helper_path = Path("/app/download_hunyuan3d_assets.py")
    spec = importlib.util.spec_from_file_location("goose_studio_hunyuan3d_assets", helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load Hunyuan3D asset helper: {helper_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {
        "hunyuan3d-paint-pbr": module.download_hunyuan3d_paint_assets,
        "dinov2-giant": module.download_hunyuan3d_dinov2_assets,
    }


def _save_hunyuan_asset_paths(paths: dict[str, str]) -> None:
    _atomic_json(
        HUNYUAN_ASSET_PATHS_FILE,
        {
            "cache_dir": str(HUNYUAN_CACHE_ROOT),
            **paths,
        },
    )


def _save_install_status(
    state: str,
    workflow: str,
    current: int,
    total: int,
    message: str,
    error: str | None = None,
    detail: str | None = None,
) -> None:
    try:
        previous = json.loads((ASSETS_ROOT / "install-status.json").read_text(encoding="utf-8"))
        details = previous.get("details", []) if previous.get("workflow") == workflow else []
    except (FileNotFoundError, json.JSONDecodeError):
        details = []
    if not details or details[-1] != message:
        details.append(message)
    if detail and details[-1] != detail:
        details.append(detail)
    value = {"state": state, "workflow": workflow, "current": current, "total": total, "message": message, "details": details[-200:]}
    if error:
        value["error"] = error
        value["details"].append(f"Error: {error}")
    _atomic_json(ASSETS_ROOT / "install-status.json", value)
    assets_volume.commit()


def _start_download_heartbeat(workflow: str, current: int, total: int, label: str):
    stop = threading.Event()
    started = time.monotonic()

    def report() -> None:
        while not stop.wait(15):
            elapsed = int(time.monotonic() - started)
            duration = f"{elapsed // 60}m elapsed" if elapsed >= 60 else "less than a minute elapsed"
            try:
                _save_install_status(
                    "running",
                    workflow,
                    current,
                    total,
                    f"Downloading {label}",
                    detail=f"[download] {label} still downloading ({duration})",
                )
            except Exception:
                pass

    thread = threading.Thread(target=report, daemon=True)
    thread.start()
    return stop, thread


@app.function(image=installer_image, volumes={str(ASSETS_ROOT): assets_volume}, timeout=7200, max_containers=1)
def install_workflow(workflow: str) -> None:
    from huggingface_hub import hf_hub_download, snapshot_download

    manifest = json.loads(Path("/app/models.json").read_text(encoding="utf-8"))
    if workflow not in manifest["workflows"]:
        raise ValueError("Unknown workflow")
    required = set(manifest["workflows"][workflow])
    models = [item for item in manifest.get("models", []) if item["id"] in required]
    snapshots = [item for item in manifest.get("snapshots", []) if item["id"] in required]
    total = len(models) + len(snapshots)
    hunyuan_downloaders = _load_hunyuan_asset_downloaders() if required & HUNYUAN_SNAPSHOT_IDS else {}
    hunyuan_asset_paths: dict[str, str] = {}
    try:
        assets_volume.reload()
        _save_install_status("running", workflow, 0, total, "Checking required models")
        for index, model in enumerate(models, 1):
            destination = ASSETS_ROOT / "models" / model["destination"]
            expected_hash = model.get("sha256")
            valid = destination.exists() and (not expected_hash or _checksum(destination) == expected_hash)
            if not valid:
                _save_install_status("running", workflow, index - 1, total, f"Downloading {model['id']}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                stop, thread = _start_download_heartbeat(workflow, index - 1, total, model["id"])
                try:
                    downloaded = hf_hub_download(
                        repo_id=model["repository"], filename=model["filename"], revision=model.get("revision"), token=os.getenv("HF_TOKEN") or None
                    )
                finally:
                    stop.set()
                    thread.join(timeout=2)
                temporary = destination.with_suffix(f"{destination.suffix}.tmp")
                shutil.copy2(downloaded, temporary)
                if expected_hash and _checksum(temporary) != expected_hash:
                    temporary.unlink(missing_ok=True)
                    raise RuntimeError(f"Checksum verification failed for {model['id']}")
                temporary.replace(destination)
            _save_install_status("running", workflow, index, total, f"Ready: {model['id']}")
        for offset, snapshot in enumerate(snapshots, len(models) + 1):
            downloader = hunyuan_downloaders.get(snapshot["id"])
            if downloader:
                _save_install_status("running", workflow, offset - 1, total, f"Downloading {snapshot['id']}")
                stop, thread = _start_download_heartbeat(workflow, offset - 1, total, snapshot["id"])
                try:
                    downloaded_root = Path(
                        downloader(
                            cache_dir=HUNYUAN_CACHE_ROOT,
                            revision=snapshot.get("revision"),
                        )
                    )
                finally:
                    stop.set()
                    thread.join(timeout=2)
                if snapshot["id"] == "hunyuan3d-paint-pbr":
                    # The custom node appends hunyuan3d-paintpbr-v2-1 itself.
                    hunyuan_asset_paths["paint_model"] = str(downloaded_root.parent)
                else:
                    hunyuan_asset_paths["dino_model"] = str(downloaded_root)
                _save_install_status("running", workflow, offset, total, f"Ready: {snapshot['id']}")
                continue
            destination = ASSETS_ROOT / "models" / snapshot["destination"]
            if not destination.exists() or not any(destination.iterdir()):
                _save_install_status("running", workflow, offset - 1, total, f"Downloading {snapshot['id']}")
                destination.mkdir(parents=True, exist_ok=True)
                stop, thread = _start_download_heartbeat(workflow, offset - 1, total, snapshot["id"])
                try:
                    snapshot_download(repo_id=snapshot["repository"], revision=snapshot.get("revision"), allow_patterns=snapshot.get("allow_patterns"), local_dir=destination, token=os.getenv("HF_TOKEN") or None)
                finally:
                    stop.set()
                    thread.join(timeout=2)
            _save_install_status("running", workflow, offset, total, f"Ready: {snapshot['id']}")
        if hunyuan_asset_paths:
            _save_hunyuan_asset_paths(hunyuan_asset_paths)
        installation = _installation()
        installed = set(installation.get("installed_workflows", []))
        installed.add(workflow)
        installation.update({"generation": int(installation.get("generation", 0)) + 1, "installed_workflows": sorted(installed)})
        _atomic_json(ASSETS_ROOT / "installation.json", installation)
        _save_install_status("completed", workflow, total, total, "Workflow installed")
    except Exception as exc:
        _save_install_status("failed", workflow, 0, total, "Installation failed", str(exc))
        raise


def _queue_workflow(workflow: dict) -> str:
    request = urllib.request.Request(
        f"{COMFYUI_URL}/prompt",
        data=json.dumps({"prompt": workflow}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read())
    node_errors = result.get("node_errors", {})
    if node_errors:
        raise RuntimeError(f"ComfyUI rejected workflow outputs: {json.dumps(node_errors)}")
    return result["prompt_id"]


def _wait_for_workflow(prompt_id: str) -> dict:
    while True:
        try:
            with urllib.request.urlopen(f"{COMFYUI_URL}/history/{prompt_id}", timeout=30) as response:
                history = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError):
            time.sleep(2)
            continue
        if prompt_id in history:
            return history[prompt_id]
        time.sleep(2)


def _check_execution(result: dict, prompt_id: str) -> None:
    status = result.get("status", {})
    if status.get("status_str") != "error":
        return
    errors = [
        str(message[1])
        for message in status.get("messages", [])
        if isinstance(message, (list, tuple))
        and len(message) >= 2
        and message[0] in ("execution_error", "execution_interrupted")
    ]
    raise RuntimeError(f"ComfyUI prompt {prompt_id} failed: {'; '.join(errors) or 'unknown error'}")


def _collect_outputs(
    result: dict, job_id: str, start_index: int, output_node_ids: set[str]
) -> list[dict]:
    output_root = (IO_ROOT / "output").resolve()
    collected = []
    seen = set()
    index = start_index

    for node_id, node_output in result.get("outputs", {}).items():
        if output_node_ids and node_id not in output_node_ids:
            continue
        for category in ("images", "gifs", "audio", "meshes"):
            for item in node_output.get(category, []):
                if not isinstance(item, dict) or not item.get("filename"):
                    continue
                relative = Path(item.get("subfolder", "")) / item["filename"]
                path = (output_root / relative).resolve()
                if (
                    path in seen
                    or not path.is_relative_to(output_root)
                    or job_id not in relative.parts
                    or not path.is_file()
                ):
                    continue
                seen.add(path)
                collected.append(
                    {
                        "id": str(index),
                        "node_id": node_id,
                        "filename": item["filename"],
                        "relative_path": str(relative),
                        "content_type": _content_type(path),
                    }
                )
                index += 1
    return collected


def _content_type(path: Path) -> str:
    known = {
        ".glb": "model/gltf-binary",
        ".gltf": "model/gltf+json",
        ".vox": "application/octet-stream",
        ".zip": "application/zip",
        ".obj": "model/obj",
        ".fbx": "application/octet-stream",
        ".stl": "model/stl",
        ".3mf": "model/3mf",
        ".dae": "model/vnd.collada+xml",
        ".usdz": "model/vnd.usdz+zip",
    }
    return known.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _validate_voxel_resolution(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("voxel resolution must be an integer")
    if not VOXEL_MIN_RESOLUTION <= value <= VOXEL_MAX_RESOLUTION:
        raise ValueError(
            f"voxel resolution must be between {VOXEL_MIN_RESOLUTION} and "
            f"{VOXEL_MAX_RESOLUTION}"
        )
    return value


def _validate_postprocess(value) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict) or value.get("type") != "voxelize":
        raise ValueError("Unsupported postprocessing operation")
    return {
        "type": "voxelize",
        "resolution": _validate_voxel_resolution(value.get("resolution")),
    }


def _voxel_input_path(job_id: str, input_name: str) -> Path:
    if not isinstance(input_name, str) or not input_name or "\\" in input_name:
        raise ValueError("input_name must be a relative uploaded GLB filename")
    candidate = Path(input_name)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise ValueError("input_name must be a relative uploaded GLB filename")
    parts = candidate.parts
    if len(parts) == 2 and parts[0] == job_id:
        filename = parts[1]
    elif len(parts) == 1:
        filename = parts[0]
    else:
        raise ValueError("input_name must identify one uploaded file")
    if Path(filename).suffix.lower() != ".glb":
        raise ValueError("voxelization accepts GLB files only")
    input_root = (IO_ROOT / "input" / job_id).resolve()
    path = (input_root / filename).resolve()
    if not path.is_relative_to(input_root):
        raise ValueError("input_name points outside the job input directory")
    return path


def _output_record(path: Path, job_id: str, index: int = 0, node_id: str = "voxelize") -> dict:
    output_root = (IO_ROOT / "output").resolve()
    resolved = path.resolve()
    if (
        not resolved.is_relative_to(output_root)
        or job_id not in resolved.relative_to(output_root).parts
        or not resolved.is_file()
    ):
        raise RuntimeError("Generated output file is outside the job output directory")
    relative = resolved.relative_to(output_root)
    return {
        "id": str(index),
        "node_id": node_id,
        "filename": resolved.name,
        "relative_path": str(relative),
        "content_type": _content_type(resolved),
    }


def _run_voxelizer(source: Path, output: Path, resolution: int) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "python",
            str(VOXELIZE_SCRIPT_PATH),
            "--source",
            str(source),
            "--output",
            str(output),
            "--format",
            "vox",
            "--res",
            str(_validate_voxel_resolution(resolution)),
        ],
        check=True,
    )


def _voxelize_mesh_outputs(outputs: list[dict], job_id: str, resolution: int) -> list[dict]:
    glb_output = next(
        (item for item in outputs if Path(item.get("filename", "")).suffix.lower() == ".glb"),
        None,
    )
    if not glb_output:
        raise RuntimeError("Voxelization requested, but Image to 3D did not produce a GLB file")
    output_root = (IO_ROOT / "output").resolve()
    source = (output_root / glb_output["relative_path"]).resolve()
    if (
        not source.is_relative_to(output_root)
        or job_id not in source.relative_to(output_root).parts
        or not source.is_file()
    ):
        raise RuntimeError("Image to 3D produced an invalid GLB output path")
    vox_path = source.with_suffix(".vox")
    _run_voxelizer(source, vox_path, resolution)
    package_path = source.with_suffix(".zip")
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(source, arcname=source.name)
        archive.write(vox_path, arcname=vox_path.name)
    return [_output_record(package_path, job_id)]


def _process_voxel_job(job_id: str, input_name: str, resolution: int) -> None:
    try:
        io_volume.reload()
        resolution = _validate_voxel_resolution(resolution)
        source = _voxel_input_path(job_id, input_name)
        if not source.is_file():
            raise FileNotFoundError(f"Uploaded GLB not found: {source.name}")
        output_dir = IO_ROOT / "output" / "vox" / job_id
        output_path = output_dir / f"{source.stem}.vox"
        _save_status(
            job_id,
            {"job_id": job_id, "status": "running", "outputs": [], "updated_at": _now()},
        )
        io_volume.commit()
        _run_voxelizer(source, output_path, resolution)
        outputs = [_output_record(output_path, job_id)]
        _save_status(
            job_id,
            {"job_id": job_id, "status": "completed", "outputs": outputs, "updated_at": _now()},
        )
        io_volume.commit()
    except Exception as exc:
        traceback.print_exc()
        _save_status(
            job_id,
            {"job_id": job_id, "status": "failed", "error": str(exc), "updated_at": _now()},
        )
        io_volume.commit()
        raise


def _process_job(
    job_id: str,
    workflows: list[dict],
    output_node_ids: list[str],
    postprocess: dict | None = None,
) -> None:
    global _COMFY_GENERATION
    try:
        io_volume.reload()
        assets_volume.reload()
        generation = int(_installation().get("generation", 0))
        if _COMFY_GENERATION is not None and generation != _COMFY_GENERATION and _is_comfyui_running():
            subprocess.run(["pkill", "-f", str(COMFYUI_ROOT / "main.py")], check=False)
            for _ in range(30):
                if not _is_comfyui_running():
                    break
                time.sleep(1)
        _COMFY_GENERATION = generation
        _setup_comfyui_paths()
        _start_comfyui()
        outputs = []
        _save_status(
            job_id,
            {"job_id": job_id, "status": "running", "outputs": outputs, "updated_at": _now()},
        )
        io_volume.commit()

        for workflow in workflows:
            prompt_id = _queue_workflow(workflow)
            result = _wait_for_workflow(prompt_id)
            _check_execution(result, prompt_id)
            outputs.extend(
                _collect_outputs(result, job_id, len(outputs), set(output_node_ids))
            )
            _save_status(
                job_id,
                {"job_id": job_id, "status": "running", "outputs": outputs, "updated_at": _now()},
            )
            io_volume.commit()

        if postprocess:
            outputs = _voxelize_mesh_outputs(
                outputs,
                job_id,
                postprocess["resolution"],
            )

        _save_status(
            job_id,
            {"job_id": job_id, "status": "completed", "outputs": outputs, "updated_at": _now()},
        )
        io_volume.commit()
    except Exception as exc:
        traceback.print_exc()
        _save_status(
            job_id,
            {"job_id": job_id, "status": "failed", "error": str(exc), "updated_at": _now()},
        )
        io_volume.commit()
        raise


@app.function(
    image=worker_image,
    gpu=IMAGE_GPU_TYPE,
    timeout=7200,
    max_containers=1,
    scaledown_window=60,
    volumes={str(ASSETS_ROOT): assets_volume, str(IO_ROOT): io_volume},
)
def process_image_job(
    job_id: str,
    workflows: list[dict],
    output_node_ids: list[str],
    postprocess: dict | None = None,
) -> None:
    _process_job(job_id, workflows, output_node_ids, postprocess)


@app.function(
    image=worker_image,
    gpu=VIDEO_GPU_TYPE,
    timeout=7200,
    max_containers=1,
    scaledown_window=60,
    volumes={str(ASSETS_ROOT): assets_volume, str(IO_ROOT): io_volume},
)
def process_video_job(
    job_id: str,
    workflows: list[dict],
    output_node_ids: list[str],
    postprocess: dict | None = None,
) -> None:
    _process_job(job_id, workflows, output_node_ids, postprocess)


@app.function(
    image=voxel_image,
    cpu=2,
    timeout=7200,
    max_containers=1,
    scaledown_window=60,
    volumes={str(IO_ROOT): io_volume},
)
def process_voxel_job(job_id: str, input_name: str, resolution: int) -> None:
    _process_voxel_job(job_id, input_name, resolution)


def _api():
    from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse

    api = FastAPI(title="Goose Studio Executor")
    allowed_node_classes = set(
        json.loads(Path("/app/allowed-node-classes.json").read_text(encoding="utf-8"))
    )
    api.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"] ,
        allow_headers=["*"],
    )

    def authorize(authorization: str = Header(default="")) -> None:
        expected = os.environ.get("GOOSE_STUDIO_API_KEY", "")
        provided = authorization.removeprefix("Bearer ")
        if not expected or not hmac.compare_digest(provided, expected):
            raise HTTPException(status_code=401, detail="Invalid application API key")

    @api.get("/health")
    def health():
        return {"status": "ok"}

    @api.get("/auth-check")
    def auth_check(_: None = Depends(authorize)):
        return {"status": "ok"}

    @api.get("/workflows")
    def workflow_status(_: None = Depends(authorize)):
        assets_volume.reload()
        installation = _installation()
        try:
            install_status = json.loads((ASSETS_ROOT / "install-status.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            install_status = {"state": "idle"}
        return {"installed": installation.get("installed_workflows", []), "installation": install_status}

    @api.post("/workflows/install")
    def start_workflow_install(payload: dict, _: None = Depends(authorize)):
        workflow = payload.get("workflow", "")
        manifest = json.loads(Path("/app/models.json").read_text(encoding="utf-8"))
        if workflow not in manifest["workflows"]:
            raise HTTPException(status_code=400, detail="Unknown workflow")
        assets_volume.reload()
        if workflow in _installation().get("installed_workflows", []):
            return {"state": "completed", "workflow": workflow}
        try:
            current = json.loads((ASSETS_ROOT / "install-status.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            current = {"state": "idle"}
        if current.get("state") == "running":
            if current.get("workflow") != workflow:
                raise HTTPException(status_code=409, detail="Another workflow is currently installing")
            return current
        required_count = len(manifest["workflows"][workflow])
        _save_install_status("running", workflow, 0, required_count, "Starting installation")
        call = install_workflow.spawn(workflow)
        return {"state": "running", "workflow": workflow, "call_id": call.object_id}

    @api.post("/upload")
    async def upload(
        job_id: str = Form(...),
        files: list[UploadFile] = File(...),
        _: None = Depends(authorize),
    ):
        job = _job_dir(job_id)
        if len(files) > 3:
            raise HTTPException(status_code=413, detail="A job may upload at most three files")
        input_dir = IO_ROOT / "input" / job_id
        input_dir.mkdir(parents=True, exist_ok=True)
        written = []
        for upload_file in files:
            filename = Path(upload_file.filename or "").name
            if not filename:
                raise HTTPException(status_code=400, detail="Every upload needs a filename")
            destination = input_dir / filename
            size = 0
            with destination.open("wb") as output:
                while chunk := await upload_file.read(1024 * 1024):
                    size += len(chunk)
                    if size > 1024 * 1024 * 1024:
                        destination.unlink(missing_ok=True)
                        raise HTTPException(status_code=413, detail="A file may not exceed 1 GiB")
                    output.write(chunk)
            written.append(filename)
        _atomic_json(job / "upload.json", {"files": written})
        await io_volume.commit.aio()
        return {"job_id": job_id, "files": written}

    @api.post("/voxelize")
    def submit_voxelization(payload: dict, _: None = Depends(authorize)):
        job_id = payload.get("job_id", "")
        input_name = payload.get("input_name", "")
        try:
            _job_dir(job_id)
            resolution = _validate_voxel_resolution(payload.get("resolution"))
            input_path = _voxel_input_path(job_id, input_name)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        io_volume.reload()
        if not input_path.is_file():
            raise HTTPException(status_code=400, detail="Uploaded GLB not found")
        job = _job_dir(job_id)
        _atomic_json(
            job / "operation.json",
            {"operation": "voxelize", "input_name": input_name, "resolution": resolution},
        )
        _save_status(
            job_id,
            {"job_id": job_id, "status": "queued", "outputs": [], "updated_at": _now()},
        )
        io_volume.commit()
        call = process_voxel_job.spawn(job_id, input_name, resolution)
        _atomic_json(job / "call.json", {"call_id": call.object_id})
        io_volume.commit()
        return {"job_id": job_id, "status": "queued"}

    @api.post("/submit")
    def submit(payload: dict, _: None = Depends(authorize)):
        job_id = payload.get("job_id", "")
        workflows = payload.get("workflows")
        output_node_ids = payload.get("output_node_ids", [])
        workload = payload.get("workload", "video")
        try:
            postprocess = _validate_postprocess(payload.get("postprocess"))
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if workload not in {"image", "video"}:
            raise HTTPException(status_code=400, detail="workload must be image or video")
        if postprocess and workload != "image":
            raise HTTPException(status_code=400, detail="Voxelization is available for image jobs only")
        job = _job_dir(job_id)
        if not isinstance(workflows, list) or not workflows or not all(isinstance(item, dict) for item in workflows):
            raise HTTPException(status_code=400, detail="workflows must be a non-empty array")
        if len(workflows) > 6:
            raise HTTPException(status_code=413, detail="A job may contain at most six workflows")
        if sum(len(item) for item in workflows) > 6000:
            raise HTTPException(status_code=413, detail="Workflow contains too many nodes")
        if not isinstance(output_node_ids, list) or not all(
            isinstance(node_id, str) for node_id in output_node_ids
        ):
            raise HTTPException(status_code=400, detail="output_node_ids must be an array of strings")
        submitted_classes = {
            node.get("class_type")
            for workflow in workflows
            for node in workflow.values()
            if isinstance(node, dict)
        }
        disallowed = sorted(
            str(class_name)
            for class_name in submitted_classes
            if not isinstance(class_name, str) or class_name not in allowed_node_classes
        )
        if disallowed:
            raise HTTPException(
                status_code=400,
                detail=f"Workflow uses unapproved node classes: {', '.join(map(str, disallowed))}",
            )
        missing_outputs = sorted(
            node_id
            for node_id in output_node_ids
            if not all(node_id in workflow for workflow in workflows)
        )
        if missing_outputs:
            raise HTTPException(
                status_code=400,
                detail=f"Output nodes are missing from workflow: {', '.join(missing_outputs)}",
            )
        _atomic_json(job / "workflow.json", {"workflows": workflows, "postprocess": postprocess})
        _save_status(
            job_id,
            {"job_id": job_id, "status": "queued", "outputs": [], "updated_at": _now()},
        )
        io_volume.commit()
        process_function = process_image_job if workload == "image" else process_video_job
        call = process_function.spawn(job_id, workflows, output_node_ids, postprocess)
        _atomic_json(job / "call.json", {"call_id": call.object_id})
        io_volume.commit()
        return {"job_id": job_id, "status": "queued"}

    @api.post("/cancel")
    def cancel(payload: dict, _: None = Depends(authorize)):
        job_id = payload.get("job_id", "")
        job = _job_dir(job_id)
        try:
            call_id = json.loads((job / "call.json").read_text(encoding="utf-8"))["call_id"]
        except (FileNotFoundError, KeyError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=404, detail="Running job not found") from exc
        modal.FunctionCall.from_id(call_id).cancel()
        _save_status(
            job_id,
            {"job_id": job_id, "status": "failed", "error": "cancelled", "updated_at": _now()},
        )
        io_volume.commit()
        return {"job_id": job_id, "status": "cancelled"}

    @api.post("/cleanup")
    def cleanup(payload: dict, _: None = Depends(authorize)):
        retention_hours = max(1, min(int(payload.get("retention_hours", 72)), 24 * 30))
        cutoff = _now() - retention_hours * 3600
        jobs_root = IO_ROOT / "jobs"
        removed = []
        io_volume.reload()
        if jobs_root.exists():
            for job in jobs_root.iterdir():
                status_file = job / "status.json"
                try:
                    status_data = json.loads(status_file.read_text(encoding="utf-8"))
                except (FileNotFoundError, json.JSONDecodeError):
                    continue
                if status_data.get("status") not in ("completed", "failed"):
                    continue
                updated_at = int(status_data.get("updated_at", status_file.stat().st_mtime))
                if updated_at >= cutoff:
                    continue
                shutil.rmtree(job, ignore_errors=True)
                shutil.rmtree(IO_ROOT / "input" / job.name, ignore_errors=True)
                for namespace in (IO_ROOT / "output").glob(f"*/{job.name}"):
                    shutil.rmtree(namespace, ignore_errors=True)
                removed.append(job.name)
        io_volume.commit()
        return {"removed": removed, "retention_hours": retention_hours}

    @api.delete("/jobs/{job_id}")
    def delete_job(job_id: str, _: None = Depends(authorize)):
        try:
            job = _job_dir(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid job ID") from exc
        io_volume.reload()
        try:
            status_data = json.loads((job / "status.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            status_data = {}
        if status_data.get("status") in {"queued", "running"}:
            raise HTTPException(status_code=409, detail="Cannot delete a running job")
        shutil.rmtree(job, ignore_errors=True)
        shutil.rmtree(IO_ROOT / "input" / job_id, ignore_errors=True)
        for namespace in (IO_ROOT / "output").glob(f"*/{job_id}"):
            shutil.rmtree(namespace, ignore_errors=True)
        io_volume.commit()
        return {"job_id": job_id, "status": "deleted"}

    @api.get("/status")
    def status(job_id: str, _: None = Depends(authorize)):
        io_volume.reload()
        try:
            return _load_status(job_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc

    @api.get("/download")
    def download(job_id: str, output_id: str, _: None = Depends(authorize)):
        io_volume.reload()
        try:
            job = _load_status(job_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc
        output = next((item for item in job.get("outputs", []) if item["id"] == output_id), None)
        if not output:
            raise HTTPException(status_code=404, detail="Output not found")
        root = (IO_ROOT / "output").resolve()
        path = (IO_ROOT / "output" / output["relative_path"]).resolve()
        if not path.is_relative_to(root) or job_id not in Path(output["relative_path"]).parts or not path.is_file():
            raise HTTPException(status_code=404, detail="Output file not found")
        return FileResponse(path, filename=output["filename"], media_type=output["content_type"])

    return api


@app.function(
    image=api_image,
    secrets=[modal.Secret.from_name(SECRET_NAME)],
    volumes={str(ASSETS_ROOT): assets_volume, str(IO_ROOT): io_volume},
)
@modal.asgi_app()
def api():
    return _api()
