"""Loads the pipeline configuration and resolves paths relative to the project root."""

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "pipeline_config.json"

REQUIRED_KEYS = ["input_sources", "column_aliases", "field_types", "mandatory_fields", "validation"]


def load_config(config_path=None):
    """Read the JSON config, check required keys, and turn relative paths into absolute ones."""
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)

    missing = [k for k in REQUIRED_KEYS if k not in cfg]
    if missing:
        raise ValueError(f"Config is missing required keys: {missing}")

    primaries = [s for s in cfg["input_sources"] if s.get("primary")]
    if len(primaries) != 1:
        raise ValueError("Exactly one input source must be marked as \"primary\": true")

    for key, default in (("input_dir", "data/raw"), ("output_dir", "output"), ("log_dir", "logs")):
        p = Path(cfg.get(key, default))
        cfg[key] = str(p if p.is_absolute() else PROJECT_ROOT / p)

    cfg.setdefault("city_aliases", {})
    cfg.setdefault("segmentation", {"method": "fixed", "fixed": {"gold_above": 100000, "silver_from": 50000}})
    cfg.setdefault("insights", {"top_n_customers": 10, "high_ticket_threshold": 5})
    cfg["_config_path"] = str(path)
    return cfg
