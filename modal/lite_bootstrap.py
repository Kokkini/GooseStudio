"""Install the single Lite Mode model directly from Hugging Face."""

import hashlib
import json
import shutil
from pathlib import Path

import modal

ROOT = Path("/assets")
DESTINATION = ROOT / "models" / "upscale_models" / "4x-UltraSharp.pth"
EXPECTED_SHA256 = "a5812231fc936b42af08a5edba784195495d303d5b3248c24489ef0c4021fe01"

app = modal.App("goose-studio-lite-bootstrap")
volume = modal.Volume.from_name("goose-studio-lite-assets", create_if_missing=True)
image = modal.Image.debian_slim(python_version="3.12").pip_install("huggingface-hub")


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


@app.function(image=image, volumes={str(ROOT): volume}, timeout=1800)
def install() -> dict:
    from huggingface_hub import hf_hub_download

    print('[progress] {"stage":"models","current":0,"total":1,"message":"Downloading 4x-UltraSharp (67 MB)"}', flush=True)
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    if not DESTINATION.exists() or checksum(DESTINATION) != EXPECTED_SHA256:
        downloaded = hf_hub_download(repo_id="uwg/upscaler", filename="ESRGAN/4x-UltraSharp.pth")
        shutil.copy2(downloaded, DESTINATION)
    if checksum(DESTINATION) != EXPECTED_SHA256:
        raise RuntimeError("Downloaded model checksum does not match")
    print('[progress] {"stage":"models","current":1,"total":1,"message":"Model downloaded and verified"}', flush=True)
    (ROOT / "installation.json").write_text(json.dumps({"mode": "lite", "models": ["4x-UltraSharp.pth"]}), encoding="utf-8")
    volume.commit()
    return {"status": "installed", "models": 1}


@app.local_entrypoint()
def main():
    print(install.remote())
