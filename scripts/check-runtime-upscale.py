#!/usr/bin/env python3
"""Submit the bundled upscale workflow to a locally running ComfyUI runtime."""

import argparse
import json
import time
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def request_json(url: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://127.0.0.1:18188")
    parser.add_argument("--input-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()

    workflow = json.loads((ROOT / "assets" / "lite-workflow.json").read_text(encoding="utf-8"))
    workflow["1"]["inputs"]["image"] = args.input_file.name
    workflow["4"]["inputs"]["filename_prefix"] = "lite/StandaloneTest"
    result = request_json(f"{args.endpoint}/prompt", {"prompt": workflow})
    prompt_id = result["prompt_id"]

    deadline = time.monotonic() + args.timeout
    history = None
    while time.monotonic() < deadline:
        history = request_json(f"{args.endpoint}/history/{prompt_id}").get(prompt_id)
        if history:
            break
        time.sleep(1)
    if not history:
        raise TimeoutError(f"Upscale workflow did not finish within {args.timeout} seconds")

    status = history.get("status", {})
    if status.get("status_str") != "success":
        raise RuntimeError(f"Upscale workflow failed: {status}")
    image = history["outputs"]["4"]["images"][0]
    output = args.output_dir / image.get("subfolder", "") / image["filename"]
    with Image.open(args.input_file) as source, Image.open(output) as generated:
        expected = (source.width * 4, source.height * 4)
        if generated.size != expected:
            raise RuntimeError(f"Expected {expected}, got {generated.size}")
        print(json.dumps({
            "prompt_id": prompt_id,
            "input_size": source.size,
            "output_size": generated.size,
            "output": str(output),
        }))


if __name__ == "__main__":
    main()
