#!/usr/bin/env python3
"""Verify the isolated Lite installation and four-node upscale workflow."""

import json
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from smoke_modal import ROOT, _api_key, _multipart, _request

INPUT = Path("/mnt/e/Documents/projects/ComfyUIService/samples/try_on/showcase/person.webp")


def main() -> None:
    config = {}
    for line in (ROOT / ".env.local").read_text(encoding="utf-8").splitlines():
        key, value = line.split("=", 1)
        config[key] = value
    endpoint = config.get("GOOSE_STUDIO_ENDPOINT", config.get("FREE_VIDEO_GEN_ENDPOINT", ""))
    key = _api_key()
    job_id = str(uuid.uuid4())
    filename = f"{uuid.uuid4().hex}.webp"
    body, content_type = _multipart({"job_id": job_id}, [(filename, INPUT)])
    _request(f"{endpoint}/upload", key, data=body, content_type=content_type)

    workflow = json.loads((ROOT / "assets/lite-workflow.json").read_text(encoding="utf-8"))
    workflow["1"]["inputs"]["image"] = f"{job_id}/{filename}"
    workflow["4"]["inputs"]["filename_prefix"] = f"lite/{job_id}/Final"
    payload = json.dumps(
        {"job_id": job_id, "workflows": [workflow], "output_node_ids": ["4"]}
    ).encode()
    _request(f"{endpoint}/submit", key, data=payload, content_type="application/json")

    while True:
        status = _request(
            f"{endpoint}/status?{urllib.parse.urlencode({'job_id': job_id})}", key
        )
        print(status["status"], flush=True)
        if status["status"] == "failed":
            raise RuntimeError(status.get("error", "Lite job failed"))
        if status["status"] == "completed":
            output = status["outputs"][0]
            query = urllib.parse.urlencode(
                {"job_id": job_id, "output_id": output["id"], "api_key": key}
            )
            destination = ROOT / "build" / f"smoke-lite-{output['filename']}"
            urllib.request.urlretrieve(f"{endpoint}/download?{query}", destination)
            print(f"Downloaded {destination}")
            return
        time.sleep(3)


if __name__ == "__main__":
    main()
