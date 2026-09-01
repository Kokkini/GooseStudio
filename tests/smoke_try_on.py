#!/usr/bin/env python3
"""Submit one Virtual Try-On job through the deployed generic Modal API."""

import json
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from smoke_modal import DEFAULT_ENDPOINT, ROOT, _api_key, _multipart, _request

PERSON = Path("/mnt/e/Documents/projects/ComfyUIService/samples/try_on/showcase/person.webp")
CLOTHES = Path("/mnt/e/Documents/projects/ComfyUIService/samples/try_on/showcase/clothes.webp")


def main() -> None:
    key = _api_key()
    job_id = str(uuid.uuid4())
    person_name = f"{uuid.uuid4().hex}.webp"
    clothes_name = f"{uuid.uuid4().hex}.webp"
    body, content_type = _multipart(
        {"job_id": job_id}, [(person_name, PERSON), (clothes_name, CLOTHES)]
    )
    print(f"Uploading try-on inputs for {job_id}...")
    _request(f"{DEFAULT_ENDPOINT}/upload", key, data=body, content_type=content_type)

    workflow = json.loads(
        (ROOT / "web/workflows/qwen-virtual-try-on.json").read_text(encoding="utf-8")
    )
    workflow["78"]["inputs"]["image"] = f"{job_id}/{person_name}"
    workflow["469"]["inputs"]["image"] = f"{job_id}/{clothes_name}"
    workflow["433:436"]["inputs"]["value"] = 4
    workflow["433:443"]["inputs"]["value"] = True
    workflow["433:3"]["inputs"]["seed"] = 43
    for node in workflow.values():
        prefix = node.get("inputs", {}).get("filename_prefix")
        if isinstance(prefix, str) and prefix.startswith("qwen_image_edit/"):
            node["inputs"]["filename_prefix"] = prefix.replace(
                "qwen_image_edit/", f"qwen_image_edit/{job_id}/", 1
            )

    payload = json.dumps(
        {"job_id": job_id, "workflows": [workflow], "output_node_ids": ["472"]}
    ).encode()
    print("Submitting try-on workflow...")
    _request(f"{DEFAULT_ENDPOINT}/submit", key, data=payload, content_type="application/json")

    while True:
        status = _request(
            f"{DEFAULT_ENDPOINT}/status?{urllib.parse.urlencode({'job_id': job_id})}", key
        )
        print(status.get("status"), flush=True)
        if status.get("status") == "failed":
            raise RuntimeError(status.get("error", "Modal job failed"))
        if status.get("status") == "completed":
            output = status["outputs"][0]
            query = urllib.parse.urlencode(
                {"job_id": job_id, "output_id": output["id"], "api_key": key}
            )
            destination = ROOT / "build" / f"smoke-try-on-{output['filename']}"
            urllib.request.urlretrieve(f"{DEFAULT_ENDPOINT}/download?{query}", destination)
            print(f"Downloaded {destination}")
            return
        time.sleep(5)


if __name__ == "__main__":
    main()
