#!/usr/bin/env python3
"""Submit one Qwen Image Edit job through the deployed generic Modal API."""

import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = Path(
    "/mnt/e/Documents/projects/ComfyUIService/samples/try_on/showcase/person.webp"
)
def _api_key() -> str:
    value = os.getenv("GOOSE_STUDIO_API_KEY", os.getenv("FREE_VIDEO_GEN_API_KEY", ""))
    if value:
        return value
    path = ROOT / ".env.local"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(("GOOSE_STUDIO_API_KEY=", "FREE_VIDEO_GEN_API_KEY=")):
            return line.split("=", 1)[1]
    raise RuntimeError("GOOSE_STUDIO_API_KEY is not configured")


def _endpoint() -> str:
    value = os.getenv("GOOSE_STUDIO_ENDPOINT", os.getenv("FREE_VIDEO_GEN_ENDPOINT", ""))
    if value:
        return value
    path = ROOT / ".env.local"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(("GOOSE_STUDIO_ENDPOINT=", "FREE_VIDEO_GEN_ENDPOINT=")):
            return line.split("=", 1)[1]
    raise RuntimeError("GOOSE_STUDIO_ENDPOINT is not configured")


def _request(url: str, key: str, *, data=None, content_type=None) -> dict:
    headers = {"Authorization": f"Bearer {key}"}
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{exc.code}: {exc.read().decode()}") from exc


def _multipart(fields: dict[str, str], files: list[tuple[str, Path]]) -> tuple[bytes, str]:
    boundary = f"----goose-studio-{uuid.uuid4().hex}"
    chunks = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode(),
                b"\r\n",
            ]
        )
    for filename, path in files:
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="files"; filename="{filename}"\r\n'.encode(),
                f"Content-Type: {mimetypes.guess_type(path.name)[0] or 'application/octet-stream'}\r\n\r\n".encode(),
                path.read_bytes(),
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _workflow(job_id: str, remote_name: str) -> dict:
    workflow = json.loads(
        (ROOT / "web" / "workflows" / "qwen-image-edit.json").read_text(encoding="utf-8")
    )
    workflow["78"]["inputs"]["image"] = f"{job_id}/{remote_name}"
    for node_id in ("433:111", "433:110"):
        workflow[node_id]["inputs"].pop("image2", None)
        workflow[node_id]["inputs"].pop("image3", None)
    workflow.pop("469", None)
    workflow.pop("477", None)
    workflow["433:111"]["inputs"]["prompt"] = "Improve the lighting and use a clean studio background"
    workflow["433:110"]["inputs"]["prompt"] = ""
    workflow["433:436"]["inputs"]["value"] = 4
    workflow["433:443"]["inputs"]["value"] = True
    workflow["433:3"]["inputs"]["seed"] = 42
    for node in workflow.values():
        prefix = node.get("inputs", {}).get("filename_prefix")
        if isinstance(prefix, str) and prefix.startswith("qwen_image_edit/"):
            node["inputs"]["filename_prefix"] = prefix.replace(
                "qwen_image_edit/", f"qwen_image_edit/{job_id}/", 1
            )
    return workflow


def main() -> None:
    endpoint = _endpoint().rstrip("/")
    key = _api_key()
    source = Path(os.getenv("GOOSE_STUDIO_SMOKE_INPUT", str(DEFAULT_INPUT)))
    if not source.is_file():
        raise RuntimeError(f"Smoke input not found: {source}")

    job_id = str(uuid.uuid4())
    remote_name = f"{uuid.uuid4().hex}{source.suffix.lower()}"
    body, content_type = _multipart({"job_id": job_id}, [(remote_name, source)])
    print(f"Uploading input for {job_id}...")
    _request(f"{endpoint}/upload", key, data=body, content_type=content_type)

    payload = json.dumps(
        {
            "job_id": job_id,
            "workflows": [_workflow(job_id, remote_name)],
            "output_node_ids": ["472"],
        }
    ).encode()
    print("Submitting workflow...")
    _request(f"{endpoint}/submit", key, data=payload, content_type="application/json")

    while True:
        query = urllib.parse.urlencode({"job_id": job_id})
        status = _request(f"{endpoint}/status?{query}", key)
        print(status.get("status"), flush=True)
        if status.get("status") == "failed":
            raise RuntimeError(status.get("error", "Modal job failed"))
        if status.get("status") == "completed":
            if not status.get("outputs"):
                raise RuntimeError("Job completed without outputs")
            output = status["outputs"][0]
            download_query = urllib.parse.urlencode(
                {"job_id": job_id, "output_id": output["id"], "api_key": key}
            )
            destination = ROOT / "build" / f"smoke-{output['filename']}"
            destination.parent.mkdir(exist_ok=True)
            urllib.request.urlretrieve(f"{endpoint}/download?{download_query}", destination)
            print(f"Downloaded {destination}")
            return
        time.sleep(5)


if __name__ == "__main__":
    main()
