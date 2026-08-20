"""
Loads configs/paths.yaml and resolves the ${data_root} placeholders,
with an environment-variable override so the exact same code runs
locally and on Kaggle without editing the YAML file.

Usage:
    On Kaggle, before importing anything else in a notebook cell:
        import os
        os.environ["FRI_DATA_ROOT"] = "/kaggle/working/data"
    Locally: leave unset, defaults to "data" (relative to cwd) as
    specified in paths.yaml's roots.data_root.

Note on Kaggle's read-only /kaggle/input: this resolves ONE data_root
for interim/processed/duckdb output (must be writable, so always
/kaggle/working/... on Kaggle). Raw input path is handled separately
via `raw_override`, since on Kaggle raw data lives in a different,
read-only mount (/kaggle/input/<dataset-name>/) that doesn't share a
root with the writable output paths.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


def load_config(
    config_path: str = "configs/paths.yaml",
    raw_override: str | None = None,
) -> dict[str, Any]:
    raw_yaml = Path(config_path).read_text()
    cfg = yaml.safe_load(raw_yaml)

    data_root = os.environ.get("FRI_DATA_ROOT", cfg["roots"]["data_root"])

    resolved_paths = {}
    for key, template in cfg["paths"].items():
        resolved_paths[key] = template.replace("${data_root}", data_root)

    # Raw path gets its own override since on Kaggle it's a different,
    # read-only mount than the writable working directory.
    if raw_override:
        resolved_paths["raw"] = raw_override
    elif os.environ.get("FRI_RAW_ROOT"):
        resolved_paths["raw"] = os.environ["FRI_RAW_ROOT"]

    cfg["resolved_paths"] = resolved_paths
    cfg["data_root"] = data_root
    return cfg