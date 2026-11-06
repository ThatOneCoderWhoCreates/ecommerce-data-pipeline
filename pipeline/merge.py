"""Step 4: Build the Customer 360 dataset.

The primary source (CRM) is the master list of customers. Every other source is
left-joined on customer_id:
- A customer missing from a secondary source is kept, with nulls and a `missing_<source>_record` flag.
- A secondary record whose customer_id is not in the CRM is an orphan: it is quarantined,
  because there's no customer profile to attach it to.
"""

import pandas as pd

from .logger import get_logger

log = get_logger()

OUTPUT_COLUMNS = [
    "customer_id", "name", "email", "city", "registration_date",
    "total_orders", "lifetime_value", "last_order_date",
    "support_tickets", "last_ticket_date",
    "avg_order_value", "days_since_last_order", "segment",
]

DATE_ORDER_CHECKS = [
    ("last_order_date", "order_before_registration"),
    ("last_ticket_date", "ticket_before_registration"),
]


def merge_sources(clean_sources, primary, issues):
    base = clean_sources[primary]
    primary_ids = set(base["customer_id"])
    merged = base.drop(columns=["_record"]).rename(columns={"_flags": f"_flags_{primary}"})

    for name, df in clean_sources.items():
        if name == primary:
            continue
        orphan_mask = ~df["customer_id"].isin(primary_ids)
        for _, row in df[orphan_mask].iterrows():
            issues.add(name, row["_record"], row["customer_id"], "orphan_record", "quarantined")
            issues.quarantine_record(name, row["_record"], "orphan_record", row.to_dict())
            log.warning("[%s] %s is not in %s; quarantined as orphan", name, row["customer_id"], primary)
        sub = df[~orphan_mask].drop(columns=["_record"]).rename(columns={"_flags": f"_flags_{name}"})

        clashes = [c for c in sub.columns if c != "customer_id" and c in merged.columns]
        sub = sub.rename(columns={c: f"{name}_{c}" for c in clashes})

        merged = merged.merge(sub, on="customer_id", how="left", indicator=f"_in_{name}")
        missing = merged[f"_in_{name}"] == "left_only"
        merged[f"_flags_{name}"] = [
            [f"missing_{name}_record"] if miss else (flags or [])
            for miss, flags in zip(missing, merged[f"_flags_{name}"])
        ]
        for cid in merged.loc[missing, "customer_id"]:
            issues.add("merge", None, cid, f"missing_{name}_record", "flagged")
        log.info("Joined %-8s matched=%d missing=%d orphans=%d", name, int((~missing).sum()),
                 int(missing.sum()), int(orphan_mask.sum()))
        merged = merged.drop(columns=[f"_in_{name}"])

    flag_cols = [c for c in merged.columns if c.startswith("_flags_")]
    merged["dq_flags"] = merged[flag_cols].apply(
        lambda r: [f for col in flag_cols for f in (r[col] if isinstance(r[col], list) else [])], axis=1
    )
    merged = merged.drop(columns=flag_cols)
    # Merging can turn None into NaN; restore None so JSON output gets null.
    return merged.astype(object).where(merged.notna(), None)


def add_cross_source_checks(df, issues):
    if "registration_date" not in df.columns:
        return df
    for col, issue in DATE_ORDER_CHECKS:
        if col not in df.columns:
            continue
        for idx in df.index:
            reg, other = df.at[idx, "registration_date"], df.at[idx, col]
            if reg is not None and other is not None and other < reg:
                df.at[idx, "dq_flags"] = df.at[idx, "dq_flags"] + [issue]
                issues.add("merge", None, df.at[idx, "customer_id"], issue, "flagged", col, other)
    return df


def add_derived_fields(df, ref_date):
    def aov(row):
        orders, ltv = row.get("total_orders"), row.get("lifetime_value")
        if orders and ltv is not None:
            return round(ltv / orders, 2)
        return None

    df["avg_order_value"] = pd.Series([aov(row) for _, row in df.iterrows()], index=df.index, dtype=object)
    if "last_order_date" in df.columns:
        df["days_since_last_order"] = [
            (ref_date - d).days if d is not None else None for d in df["last_order_date"]
        ]
    return df


def order_columns(df):
    known = [c for c in OUTPUT_COLUMNS if c in df.columns]
    extras = [c for c in df.columns if c not in known and c != "dq_flags"]
    return df[known + extras + ["dq_flags"]]


def to_json_records(df):
    """Convert a DataFrame to plain Python records: dates to ISO strings, NaN to None."""
    records = []
    for row in df.to_dict(orient="records"):
        clean = {}
        for k, v in row.items():
            if hasattr(v, "isoformat"):
                v = v.isoformat()
            elif isinstance(v, float) and pd.isna(v):
                v = None
            elif hasattr(v, "item"):
                v = v.item()
            clean[k] = v
        records.append(clean)
    return records
