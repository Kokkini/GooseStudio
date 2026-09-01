#!/usr/bin/env python3
"""Submit one short Wan Character Swap job through the generic Modal API."""

import json
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from smoke_modal import DEFAULT_ENDPOINT, ROOT, _api_key, _multipart, _request

VIDEO = Path("/mnt/e/Documents/projects/ComfyUIService/samples/clothing_review/showcase/input.mp4")
CHARACTER = Path("/mnt/e/Documents/projects/ComfyUIService/samples/clothing_review/showcase/input.webp")


def main() -> None:
    key = _api_key()
    job_id = str(uuid.uuid4())
    video_name = f"{uuid.uuid4().hex}.mp4"
    image_name = f"{uuid.uuid4().hex}.webp"
    body, content_type = _multipart(
        {"job_id": job_id}, [(video_name, VIDEO), (image_name, CHARACTER)]
    )
    print(f"Uploading character-swap inputs for {job_id}...")
    _request(f"{DEFAULT_ENDPOINT}/upload", key, data=body, content_type=content_type)

    workflow = json.loads(
        (ROOT / "web/workflows/wan-character-swap.json").read_text(encoding="utf-8")
    )
    workflow["301"]["inputs"]["video"] = f"{job_id}/{video_name}"
    workflow["360"]["inputs"]["image"] = f"{job_id}/{image_name}"
    workflow["159"]["inputs"]["value"] = 480
    workflow["160"]["inputs"]["value"] = 848
    workflow["548:537"]["inputs"]["seed"] = 42
    workflow["550"]["inputs"]["value"] = 4
    workflow["571"]["inputs"]["value"] = 81
    workflow["548:537"]["inputs"]["cfg"] = 1.0
    workflow["548:537"]["inputs"]["sampler_name"] = "euler"
    workflow["548:537"]["inputs"]["scheduler"] = "simple"
    workflow["548:537"]["inputs"]["denoise"] = 1.0
    workflow["637"]["inputs"]["value"] = 10
    workflow["635"]["inputs"]["value"] = 1
    workflow["605"]["inputs"]["value"] = 0
    workflow["657"]["inputs"]["value"] = False
    workflow["700"]["inputs"]["value"] = 8
    workflow["701"]["inputs"]["value"] = "clothes"
    workflow["753"]["inputs"]["value"] = False
    workflow["751"]["inputs"]["audio"] = f"{job_id}/{video_name}"
    workflow["751"]["inputs"].pop("audioUI", None)
    workflow["757"]["inputs"]["value"] = False
    workflow["787"]["inputs"]["value"] = False
    if "793" in workflow:
        workflow["793"]["inputs"]["value"] = False
    for node in workflow.values():
        prefix = node.get("inputs", {}).get("filename_prefix")
        if isinstance(prefix, str) and prefix.startswith("char_swap/"):
            node["inputs"]["filename_prefix"] = prefix.replace(
                "char_swap/", f"char_swap/{job_id}/", 1
            )

    payload = json.dumps(
        {"job_id": job_id, "workflows": [workflow], "output_node_ids": ["368"]}
    ).encode()
    print("Submitting character-swap workflow...")
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
            destination = ROOT / "build" / f"smoke-character-swap-{output['filename']}"
            urllib.request.urlretrieve(f"{DEFAULT_ENDPOINT}/download?{query}", destination)
            print(f"Downloaded {destination}")
            return
        time.sleep(5)


if __name__ == "__main__":
    main()
