"""Step 3: Data quality checks and cleaning.

Rule used throughout: if a value can be fixed safely, the record is kept with a flag and
the bad value is set to null. If the record can't be trusted at all (no valid customer ID,
or a conflicting duplicate), it is removed and saved to the quarantine file with the reason.
Every decision is written to the issue log, which feeds the quality report and the dashboard.
"""

import math
import re
from collections import Counter
from datetime import date, datetime

import pandas as pd

from .logger import get_logger

log = get_logger()

NULL_TOKENS = {"", "null", "none", "nan", "n/a", "na", "-", "--"}
DATE_FORMATS = ["%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y%m%d"]

# Count field and its matching date field: a date with a zero count is contradictory.
COUNT_DATE_PAIRS = [
    ("support_tickets", "last_ticket_date", "ticket_date_without_tickets"),
    ("total_orders", "last_order_date", "order_date_without_orders"),
]

ISSUE_CATEGORY = {
    "duplicate_record": "duplicates",
    "conflicting_duplicate_id": "duplicates",
    "missing_customer_id": "invalid_customer_ids",
    "invalid_customer_id": "invalid_customer_ids",
    "invalid_email": "invalid_emails",
    "orphan_record": "orphan_records",
}

REMOVED_ACTIONS = {"dropped", "quarantined"}


def categorize(issue):
    if issue in ISSUE_CATEGORY:
        return ISSUE_CATEGORY[issue]
    if issue.startswith("missing_") and issue.endswith("_record"):
        return "missing_source_records"
    if issue.startswith("missing_"):
        return "missing_fields"
    if issue.startswith("negative_"):
        return "negative_values"
    if issue.startswith("invalid_"):
        return "invalid_values"
    return "inconsistent_values"


class IssueLog:
    """Collects one entry per data quality decision."""

    def __init__(self):
        self.entries = []
        self.quarantine = []

    def add(self, source, record_number, customer_id, issue, action, field=None, value=None):
        record_number = None if record_number is None else int(record_number)
        self.entries.append({
            "source": source,
            "record_number": record_number,
            "customer_id": customer_id,
            "issue": issue,
            "category": categorize(issue),
            "field": field,
            "value": None if value is None else str(value),
            "action": action,
        })

    def quarantine_record(self, source, record_number, reason, record):
        self.quarantine.append({
            "source": source,
            "record_number": int(record_number),
            "reason": reason,
            "record": {k: v for k, v in record.items() if not str(k).startswith("_")},
        })


# ---------- value cleaners ----------

def clean_text(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return None if text.lower() in NULL_TOKENS else text


def clean_customer_id(value):
    value = clean_text(value)
    return re.sub(r"\s+", "", value).upper() if value else None


def parse_number(value, integer=False):
    """Returns (number, error) where error is None, 'invalid' or 'negative'."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        num = float(value)
    else:
        text = re.sub(r"(?i)(rs\.?|inr|₹|\$|,|\s)", "", str(value))
        try:
            num = float(text)
        except ValueError:
            return None, "invalid"
    if math.isnan(num) or math.isinf(num):
        return None, "invalid"
    if integer and not num.is_integer():
        return None, "invalid"
    if num < 0:
        return None, "negative"
    if integer or num.is_integer():
        return int(num), None
    return round(num, 2), None


def parse_date(value):
    if isinstance(value, datetime):
        return value.date(), None
    if isinstance(value, date):
        return value, None
    text = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date(), None
        except ValueError:
            continue
    return None, "invalid"


def make_email_check(pattern):
    regex = re.compile(pattern)

    def check(value):
        email = str(value).strip().lower()
        return (email, None) if regex.match(email) else (None, "invalid")

    return check


def make_city_cleaner(city_aliases):
    aliases = {k.lower(): v for k, v in city_aliases.items()}

    def clean(value):
        city = str(value).strip()
        return aliases.get(city.lower(), city.title()), None

    return clean


def reference_date(cfg):
    ref = cfg.get("validation", {}).get("reference_date")
    return datetime.strptime(ref, "%Y-%m-%d").date() if ref else date.today()


# ---------- per-source validation ----------

def apply_values(series, func):
    """Apply func to each value and keep Python None (pandas map can turn None into NaN)."""
    return pd.Series([func(v) for v in series], index=series.index, dtype=object)


def validate_source(df, source, cfg, issues):
    """Clean one standardized source. Returns a DataFrame with a `_flags` list column."""
    df = df.copy()
    df.insert(0, "_record", range(1, len(df) + 1))
    data_cols = [c for c in df.columns if not c.startswith("_")]
    for col in data_cols:
        df[col] = apply_values(df[col], clean_text)

    mandatory = cfg["mandatory_fields"].get(source, ["customer_id"])
    for field in mandatory:
        if field not in df.columns:
            log.warning("[%s] Mandatory column '%s' is absent; every record will be flagged", source, field)
            df[field] = None
            data_cols.append(field)

    # 1. Customer ID: records without a valid ID can't be merged, so they are quarantined.
    df["customer_id"] = apply_values(df["customer_id"], clean_customer_id)
    id_regex = re.compile(cfg["validation"]["customer_id_pattern"])
    keep = []
    for _, row in df.iterrows():
        cid = row["customer_id"]
        if cid is None:
            reason = "missing_customer_id"
        elif not id_regex.match(cid):
            reason = "invalid_customer_id"
        else:
            keep.append(True)
            continue
        keep.append(False)
        issues.add(source, row["_record"], cid, reason, "quarantined", "customer_id", cid)
        issues.quarantine_record(source, row["_record"], reason, row.to_dict())
        log.warning("[%s] Record %s quarantined: %s", source, row["_record"], reason)
    df = df[keep]

    # 2. Normalize text fields before the duplicate check, so case and spacing differences
    #    don't hide duplicates.
    ftypes = cfg["field_types"]
    text_cleaners = {
        "email": lambda v: str(v).strip().lower(),
        "city": lambda v: make_city_cleaner(cfg.get("city_aliases", {}))(v)[0],
    }
    for col in data_cols:
        cleaner = text_cleaners.get(ftypes.get(col))
        if cleaner:
            df[col] = apply_values(df[col], lambda v, f=cleaner: f(v) if v is not None else None)

    # 3. Duplicates: exact copies are dropped; same ID with different values is quarantined.
    exact_dup = df.duplicated(subset=data_cols, keep="first")
    for _, row in df[exact_dup].iterrows():
        issues.add(source, row["_record"], row["customer_id"], "duplicate_record", "dropped")
        log.info("[%s] Dropped exact duplicate of %s (record %s)", source, row["customer_id"], row["_record"])
    df = df[~exact_dup]
    id_dup = df.duplicated(subset=["customer_id"], keep="first")
    for _, row in df[id_dup].iterrows():
        issues.add(source, row["_record"], row["customer_id"], "conflicting_duplicate_id", "quarantined")
        issues.quarantine_record(source, row["_record"], "conflicting_duplicate_id", row.to_dict())
        log.warning("[%s] %s appears again with different values (record %s); quarantined",
                    source, row["customer_id"], row["_record"])
    df = df[~id_dup].copy()

    # 4. Type conversion and field-level checks.
    parsers = {
        "int": lambda v: parse_number(v, integer=True),
        "money": lambda v: parse_number(v, integer=False),
        "date": parse_date,
        "email": make_email_check(cfg["validation"]["email_pattern"]),
    }
    ref = reference_date(cfg)
    flags = {idx: [] for idx in df.index}

    for col in data_cols:
        if col == "customer_id":
            continue
        parser = parsers.get(ftypes.get(col))
        new_values = {}
        for idx, value in df[col].items():
            cid, rec = df.at[idx, "customer_id"], df.at[idx, "_record"]
            if value is None:
                if col in mandatory:
                    flags[idx].append(f"missing_{col}")
                    issues.add(source, rec, cid, f"missing_{col}", "flagged", col)
                new_values[idx] = None
                continue
            if parser is None:
                new_values[idx] = value
                continue
            parsed, error = parser(value)
            if error:
                issue = "invalid_email" if col == "email" else f"{error}_{col}"
                flags[idx].append(issue)
                issues.add(source, rec, cid, issue, "set_to_null", col, value)
                parsed = None
            elif ftypes.get(col) == "date" and parsed > ref:
                issue = f"future_{col}"
                flags[idx].append(issue)
                issues.add(source, rec, cid, issue, "set_to_null", col, value)
                parsed = None
            new_values[idx] = parsed
        df[col] = pd.Series(new_values, dtype=object)

    # 5. Logical consistency inside the record.
    for count_col, date_col, issue in COUNT_DATE_PAIRS:
        if count_col in df.columns and date_col in df.columns:
            for idx in df.index:
                if df.at[idx, count_col] == 0 and df.at[idx, date_col] is not None:
                    flags[idx].append(issue)
                    issues.add(source, df.at[idx, "_record"], df.at[idx, "customer_id"], issue,
                               "set_to_null", date_col, df.at[idx, date_col])
                    df.at[idx, date_col] = None

    df["_flags"] = pd.Series(flags, dtype=object)
    flagged = sum(1 for f in flags.values() if f)
    log.info("[%s] Validation done: %d records kept (%d with repairs)", source, len(df), flagged)
    return df.reset_index(drop=True)


# ---------- report ----------

def build_quality_report(raw_counts, issues, customer_360, column_mappings, unmapped_columns):
    entries = issues.entries
    record_entries = [e for e in entries if e["source"] in raw_counts]
    total = sum(raw_counts.values())

    removed = {(e["source"], e["record_number"]) for e in record_entries if e["action"] in REMOVED_ACTIONS}
    repaired = {(e["source"], e["record_number"]) for e in record_entries
                if e["action"] not in REMOVED_ACTIONS} - removed

    def records_with(category):
        return len({(e["source"], e["record_number"]) for e in record_entries if e["category"] == category})

    summary = {
        "total_records": total,
        "duplicates": records_with("duplicates"),
        "invalid_customer_ids": records_with("invalid_customer_ids"),
        "invalid_emails": records_with("invalid_emails"),
        "missing_fields": records_with("missing_fields"),
        "negative_revenue": len({(e["source"], e["record_number"]) for e in record_entries
                                 if e["issue"] == "negative_lifetime_value"}),
        "invalid_values": records_with("invalid_values") + records_with("negative_values"),
        "inconsistent_values": records_with("inconsistent_values"),
        "orphan_records": records_with("orphan_records"),
        "removed_records": len(removed),
        "repaired_records": len(repaired),
        "successful_records": total - len(removed) - len(repaired),
    }

    by_source = {}
    for src, count in raw_counts.items():
        src_removed = sum(1 for s, _ in removed if s == src)
        src_repaired = sum(1 for s, _ in repaired if s == src)
        by_source[src] = {
            "records_in": count,
            "removed": src_removed,
            "repaired": src_repaired,
            "clean": count - src_removed - src_repaired,
            "records_out": count - src_removed,
        }

    flags_per_customer = customer_360["dq_flags"].map(len)
    fields = [c for c in customer_360.columns if c != "dq_flags"]
    completeness = {
        f: round(100 * customer_360[f].notna().sum() / max(len(customer_360), 1), 2) for f in fields
    }

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
        "by_source": by_source,
        "issue_breakdown": dict(Counter(e["issue"] for e in entries).most_common()),
        "customer_360": {
            "customers": int(len(customer_360)),
            "customers_without_flags": int((flags_per_customer == 0).sum()),
            "customers_with_flags": int((flags_per_customer > 0).sum()),
            "field_completeness_pct": completeness,
        },
        "column_mappings": column_mappings,
        "unmapped_columns": unmapped_columns,
    }
