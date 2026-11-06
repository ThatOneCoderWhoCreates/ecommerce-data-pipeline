"""Step 1: Load data sources.

Each loader returns a pandas DataFrame with object dtype, so values stay exactly as
they were in the file. Type conversion and validation happen later in quality.py.
The file format is picked from the file extension, so adding a source only needs a
config change.
"""

import csv
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

from .logger import get_logger

log = get_logger()


def load_json(path, options=None):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        list_values = [v for v in data.values() if isinstance(v, list)]
        if len(list_values) != 1:
            raise ValueError(f"{path}: expected a list of records or an object with one list of records")
        data = list_values[0]
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a JSON array of records")
    return pd.DataFrame(data, dtype=object)


def load_csv(path, options=None):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return pd.DataFrame(rows, dtype=object)


def load_xml(path, options=None):
    """Reads <record_tag> elements; each child element becomes a column.

    Empty elements such as <customerId /> become None, so they are caught as missing values.
    """
    options = options or {}
    record_tag = options.get("xml_record_tag")
    root = ET.parse(path).getroot()
    records_xml = list(root.iter(record_tag)) if record_tag else list(root)
    records = []
    for rec in records_xml:
        row = {}
        for child in rec:
            text = child.text.strip() if child.text and child.text.strip() else None
            row[child.tag] = text
        row.update({f"@{k}": v for k, v in rec.attrib.items()})
        records.append(row)
    return pd.DataFrame(records, dtype=object)


LOADERS = {".json": load_json, ".csv": load_csv, ".xml": load_xml}


def load_source(path, options=None):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    ext = path.suffix.lower()
    if ext not in LOADERS:
        raise ValueError(f"Unsupported file format '{ext}' for {path.name}. Supported: {sorted(LOADERS)}")
    df = LOADERS[ext](path, options)
    log.info("Loaded %-22s format=%-4s rows=%d columns=%s", path.name, ext[1:], len(df), list(df.columns))
    return df
