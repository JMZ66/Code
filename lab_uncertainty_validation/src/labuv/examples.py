"""Load the shipped examples. JSON files are the editable copies."""

from __future__ import annotations

import json

from labuv.paths import examples_dir


def load_example(name: str) -> dict:
    path = examples_dir() / name
    return json.loads(path.read_text(encoding="utf-8"))
