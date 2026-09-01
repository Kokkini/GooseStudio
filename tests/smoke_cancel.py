#!/usr/bin/env python3
"""Verify cancellation after a GPU worker has started."""

import json
import time
import urllib.parse
import uuid
from pathlib import Path

from smoke_modal import ROOT, _api_key, _endpoint, _multipart, _request, _workflow

INPUT = Path("/mnt/e/Documents/projects/ComfyUIService/samples/try_on/showcase/person.webp")


def main() -> None:
    key = _api_key()
    endpoint = _endpoint().rstrip("/")
    job_id = str(uuid.uuid4())
    remote_name = f"{uuid.uuid4().hex}.webp"
    body, content_type = _multipart({"job_id": job_id}, [(remote_name, INPUT)])
    _request(f"{endpoint}/upload", key, data=body, content_type=content_type)
    payload = json.dumps(
        {
            "job_id": job_id,
            "workflows": [_workflow(job_id, remote_name)],
            "output_node_ids": ["472"],
        }
    ).encode()
    _request(f"{endpoint}/submit", key, data=payload, content_type="application/json")

    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        status = _request(
            f"{endpoint}/status?{urllib.parse.urlencode({'job_id': job_id})}", key
        )
        print(status["status"], flush=True)
        if status["status"] == "running":
            break
        if status["status"] in ("completed", "failed"):
            raise RuntimeError(f"Job reached {status['status']} before cancellation")
        time.sleep(1)
    else:
        raise RuntimeError("Job did not start within ten minutes")

    cancel = _request(
        f"{endpoint}/cancel",
        key,
        data=json.dumps({"job_id": job_id}).encode(),
        content_type="application/json",
    )
    if cancel["status"] != "cancelled":
        raise RuntimeError(f"Unexpected cancellation response: {cancel}")
    time.sleep(3)
    status = _request(
        f"{endpoint}/status?{urllib.parse.urlencode({'job_id': job_id})}", key
    )
    if status.get("error") != "cancelled":
        raise RuntimeError(f"Cancellation did not persist: {status}")
    print(f"Active job {job_id} cancelled successfully")


if __name__ == "__main__":
    main()
