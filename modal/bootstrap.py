"""CPU bootstrap for the customer-owned assets Volume."""

import json
import hashlib
import os
import shutil
from pathlib import Path

import modal

APP_NAME = "goose-studio-bootstrap"
VOLUME_NAME = "goose-studio-assets"
ROOT = Path("/assets")
RUNTIME_VERSION = "v1.3.0"

app = modal.App(APP_NAME)
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)
image = modal.Image.debian_slim(python_version="3.12").pip_install("huggingface-hub")


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _download_models(manifest: dict, workflow: str) -> None:
    from huggingface_hub import hf_hub_download, snapshot_download

    required = set(manifest["workflows"][workflow])
    models = [item for item in manifest.get("models", []) if item["id"] in required]
    snapshots = [item for item in manifest.get("snapshots", []) if item["id"] in required]
    total = len(models) + len(snapshots)
    completed = 0
    for model in models:
        destination = ROOT / "models" / model["destination"]
        expected_hash = model.get("sha256")
        if destination.exists() and (not expected_hash or _checksum(destination) == expected_hash):
            completed += 1
            print(f"[bootstrap] Model {completed}/{total} already present: {model['id']}", flush=True)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        print(f"[bootstrap] Downloading model {completed + 1}/{total}: {model['id']}", flush=True)
        downloaded = hf_hub_download(
            repo_id=model["repository"],
            filename=model["filename"],
            revision=model.get("revision"),
            token=os.getenv("HF_TOKEN") or None,
        )
        shutil.copy2(downloaded, destination)

        if expected_hash and _checksum(destination) != expected_hash:
            raise RuntimeError(f"Checksum verification failed for {model['id']}")
        completed += 1
        print(f"[bootstrap] Finished model {completed}/{total}: {model['id']}", flush=True)

    for snapshot in snapshots:
        destination = ROOT / "models" / snapshot["destination"]
        if destination.exists() and any(destination.iterdir()):
            completed += 1
            print(f"[bootstrap] Snapshot {completed}/{total} already present: {snapshot['id']}", flush=True)
            continue
        destination.mkdir(parents=True, exist_ok=True)
        print(f"[bootstrap] Downloading snapshot {completed + 1}/{total}: {snapshot['id']}", flush=True)
        snapshot_download(
            repo_id=snapshot["repository"],
            revision=snapshot.get("revision"),
            allow_patterns=snapshot.get("allow_patterns"),
            local_dir=destination,
            token=os.getenv("HF_TOKEN") or None,
        )
        completed += 1
        print(f"[bootstrap] Finished snapshot {completed}/{total}: {snapshot['id']}", flush=True)


@app.function(
    image=image.add_local_file(
        str(Path(__file__).resolve().parents[1] / "assets" / "models.json"),
        "/bootstrap/models.json",
    ),
    volumes={str(ROOT): volume},
    timeout=7200,
)
def install() -> dict:
    manifest = json.loads(Path("/bootstrap/models.json").read_text(encoding="utf-8"))
    _download_models(manifest, "text-to-image")
    try:
        installation = json.loads((ROOT / "installation.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        installation = {}
    installation = {
        "generation": int(installation.get("generation", 0)) + 1,
        "installed_workflows": sorted(set(installation.get("installed_workflows", [])) | {"text-to-image"}),
        "runtime": RUNTIME_VERSION,
    }
    (ROOT / "installation.json").write_text(json.dumps(installation), encoding="utf-8")
    volume.commit()
    return {
        "status": "installed",
        "workflows": installation["installed_workflows"],
    }


@app.local_entrypoint()
def main():
    print(install.remote())
