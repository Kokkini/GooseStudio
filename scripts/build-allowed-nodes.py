#!/usr/bin/env python3
"""Generate the executor node allowlist from bundled workflow templates."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
classes = set()
for path in (ROOT / "web" / "workflows").glob("*.json"):
    workflow = json.loads(path.read_text(encoding="utf-8"))
    classes.update(node["class_type"] for node in workflow.values())
lite = json.loads((ROOT / "assets" / "lite-workflow.json").read_text(encoding="utf-8"))
classes.update(node["class_type"] for node in lite.values())

destination = ROOT / "assets" / "allowed-node-classes.json"
destination.write_text(json.dumps(sorted(classes), indent=2) + "\n", encoding="utf-8", newline="\n")
print(f"Wrote {len(classes)} classes to {destination}")
