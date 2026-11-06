"""Step 5: Customer segmentation and business insights."""

import pandas as pd

from .logger import get_logger

log = get_logger()

SEGMENT_ORDER = ["Gold", "Silver", "Bronze", "Unknown"]


def segment_thresholds(values, seg_cfg):
    """Return (gold_above, silver_from) cut-offs for the chosen method."""
    method = seg_cfg.get("method", "fixed")
    if method == "fixed":
        fixed = seg_cfg["fixed"]
        return float(fixed["gold_above"]), float(fixed["silver_from"])
    if method == "percentile":
        pct = seg_cfg["percentile"]
        valid = pd.Series([v for v in values if v is not None], dtype=float)
        if valid.empty:
            return float("inf"), float("inf")
        gold_q = 1 - pct["gold_top_pct"] / 100
        silver_q = gold_q - pct["silver_next_pct"] / 100
        return float(valid.quantile(gold_q)), float(valid.quantile(silver_q))
    raise ValueError(f"Unknown segmentation method: {method}")


def assign_segment(value, gold_above, silver_from):
    """Gold: above gold_above. Silver: silver_from to gold_above (inclusive). Bronze: below silver_from."""
    if value is None or pd.isna(value):
        return "Unknown"
    if value > gold_above:
        return "Gold"
    if value >= silver_from:
        return "Silver"
    return "Bronze"


def add_segments(df, seg_cfg):
    gold_above, silver_from = segment_thresholds(df["lifetime_value"].tolist(), seg_cfg)
    df["segment"] = [assign_segment(v, gold_above, silver_from) for v in df["lifetime_value"]]
    info = {"method": seg_cfg.get("method", "fixed"), "gold_above": round(gold_above, 2),
            "silver_from": round(silver_from, 2)}
    log.info("Segmentation (%s): Gold > %.0f, Silver %.0f to %.0f, Bronze < %.0f",
             info["method"], gold_above, silver_from, gold_above, silver_from)
    return df, info


ACTIVITY_ORDER = ["Active", "Cooling", "Inactive", "Unknown"]


def activity_status(days, active_within=90, cooling_within=180):
    """Active: ordered within active_within days. Cooling: up to cooling_within. Inactive: longer ago."""
    if days is None or pd.isna(days):
        return "Unknown"
    if days <= active_within:
        return "Active"
    if days <= cooling_within:
        return "Cooling"
    return "Inactive"


def behavior_insights(df, insight_cfg):
    """Customer behavior and spending patterns. Expects the numeric helper columns from generate_insights."""
    days_cfg = insight_cfg.get("activity_days", {"active_within": 90, "cooling_within": 180})
    active_within, cooling_within = days_cfg["active_within"], days_cfg["cooling_within"]
    df = df.copy()
    df["activity"] = [activity_status(d, active_within, cooling_within) for d in df["days_since_last_order"]]
    df["aov"] = _num(df["avg_order_value"])
    total_revenue = df["ltv"].sum()
    present = [s for s in ACTIVITY_ORDER if s in set(df["activity"])]

    activity = (df.groupby("activity").agg(customers=("customer_id", "count"), revenue=("ltv", "sum"))
                .reindex(present).reset_index())
    activity["customer_share_pct"] = (100 * activity["customers"] / len(df)).round(2)
    activity["revenue_share_pct"] = (100 * activity["revenue"] / total_revenue).round(2)

    by_segment = pd.crosstab(df["segment"], df["activity"]).reindex(columns=present, fill_value=0)
    win_back = df[(df["activity"] == "Inactive") & (df["segment"] == "Gold")].sort_values("ltv", ascending=False)

    reg = pd.to_datetime(pd.Series(df["registration_date"]), errors="coerce")
    df["reg_year"] = reg.dt.year
    cohorts = (df.dropna(subset=["reg_year"]).groupby("reg_year")
               .agg(customers=("customer_id", "count"), avg_lifetime_value=("ltv", "mean"),
                    avg_orders=("orders", "mean")).round(2).reset_index())
    cohorts["reg_year"] = cohorts["reg_year"].astype(int)
    quarters = reg.dropna().dt.to_period("Q").astype(str).value_counts().sort_index()

    corr = df[["orders", "ltv", "tickets", "aov"]].corr().round(2)

    return {
        "activity_rules": {"active_within_days": active_within, "cooling_within_days": cooling_within},
        "activity_summary": _records(activity),
        "activity_by_segment": {seg: {k: int(v) for k, v in row.items()} for seg, row in by_segment.iterrows()},
        "inactive_gold_count": int(len(win_back)),
        "inactive_gold_revenue": round(float(win_back["ltv"].sum()), 2),
        "inactive_gold_customers": _records(win_back[["customer_id", "name", "city", "lifetime_value",
                                                      "last_order_date", "days_since_last_order"]]),
        "avg_order_value_by_city": {k: round(float(v), 2) for k, v in
                                    df.groupby("city")["aov"].mean().sort_values(ascending=False).items()},
        "avg_order_value_by_segment": {k: (None if pd.isna(v) else round(float(v), 2)) for k, v in
                                       df.groupby("segment")["aov"].mean().items()},
        "correlations": {
            "revenue_vs_orders": float(corr.loc["ltv", "orders"]),
            "revenue_vs_avg_order_value": float(corr.loc["ltv", "aov"]),
            "revenue_vs_tickets": float(corr.loc["ltv", "tickets"]),
            "orders_vs_tickets": float(corr.loc["orders", "tickets"]),
        },
        "registration_cohorts": _records(cohorts),
        "registrations_by_quarter": {k: int(v) for k, v in quarters.items()},
    }


def _num(series):
    return pd.to_numeric(series, errors="coerce")


def _records(df):
    out = []
    for row in df.to_dict(orient="records"):
        out.append({k: (None if isinstance(v, float) and pd.isna(v) else
                        v.isoformat() if hasattr(v, "isoformat") else
                        v.item() if hasattr(v, "item") else v) for k, v in row.items()})
    return out


def generate_insights(c360, seg_info, insight_cfg):
    df = c360.copy()
    df["ltv"] = _num(df["lifetime_value"])
    df["orders"] = _num(df["total_orders"])
    df["tickets"] = _num(df["support_tickets"])
    total_revenue = df["ltv"].sum()
    top_n = insight_cfg.get("top_n_customers", 10)
    ticket_threshold = insight_cfg.get("high_ticket_threshold", 5)

    kpis = {
        "total_customers": int(len(df)),
        "total_revenue": round(float(total_revenue), 2),
        "avg_lifetime_value": round(float(df["ltv"].mean()), 2),
        "median_lifetime_value": round(float(df["ltv"].median()), 2),
        "avg_orders_per_customer": round(float(df["orders"].mean()), 2),
        "avg_order_value": round(float(total_revenue / df.loc[df["ltv"].notna(), "orders"].sum()), 2),
        "avg_tickets_per_customer": round(float(df["tickets"].mean()), 2),
    }

    top = (df[df["ltv"].notna()].sort_values("ltv", ascending=False).head(top_n)
           [["customer_id", "name", "city", "lifetime_value", "total_orders", "segment"]])
    top.insert(0, "rank", range(1, len(top) + 1))

    seg = (df.groupby("segment").agg(customers=("customer_id", "count"), revenue=("ltv", "sum"),
                                     avg_lifetime_value=("ltv", "mean"), avg_orders=("orders", "mean"),
                                     avg_tickets=("tickets", "mean"))
           .reindex([s for s in SEGMENT_ORDER if s in set(df["segment"])]).reset_index())
    seg["customer_share_pct"] = (100 * seg["customers"] / len(df)).round(2)
    seg["revenue_share_pct"] = (100 * seg["revenue"] / total_revenue).round(2)
    seg = seg.round(2)

    high = df[df["tickets"] > ticket_threshold].sort_values(["tickets", "ltv"], ascending=False)
    high_cols = ["customer_id", "name", "city", "support_tickets", "last_ticket_date", "lifetime_value", "segment"]
    at_risk = high[high["segment"] == "Gold"]
    tickets_by_segment = (df.groupby("segment")["tickets"].mean().round(2)
                          .reindex([s for s in SEGMENT_ORDER if s in set(df["segment"])]))
    distribution = df["tickets"].dropna().astype(int).value_counts().sort_index()

    city = (df.groupby("city").agg(customers=("customer_id", "count"), revenue=("ltv", "sum"),
                                   avg_lifetime_value=("ltv", "mean"), avg_orders=("orders", "mean"),
                                   avg_tickets=("tickets", "mean"))
            .sort_values("revenue", ascending=False).reset_index())
    city["revenue_share_pct"] = (100 * city["revenue"] / total_revenue).round(2)
    city = city.round(2)
    city_segments = (df.pivot_table(index="city", columns="segment", values="customer_id",
                                    aggfunc="count", fill_value=0).reset_index())

    reg = pd.to_datetime(pd.Series(df["registration_date"]), errors="coerce").dropna()
    registrations = reg.dt.to_period("M").astype(str).value_counts().sort_index()

    insights = {
        "kpis": kpis,
        "top_customers": _records(top),
        "segmentation": {"rules": seg_info, "summary": _records(seg)},
        "support": {
            "high_ticket_threshold": ticket_threshold,
            "customers_above_threshold": int(len(high)),
            "share_above_threshold_pct": round(100 * len(high) / max(len(df), 1), 2),
            "high_value_at_risk_count": int(len(at_risk)),
            "high_value_at_risk_revenue": round(float(at_risk["ltv"].sum()), 2),
            "avg_tickets_by_segment": {k: (None if pd.isna(v) else float(v)) for k, v in tickets_by_segment.items()},
            "ticket_distribution": {str(k): int(v) for k, v in distribution.items()},
            "customers": _records(high[high_cols]),
        },
        "regional": {
            "by_city": _records(city),
            "segments_by_city": _records(city_segments),
        },
        "registrations_by_month": {k: int(v) for k, v in registrations.items()},
        "behavior": behavior_insights(df, insight_cfg),
    }
    log.info("Insights: revenue=%.0f, top customer=%s, %d customers with more than %d tickets",
             total_revenue, top.iloc[0]["customer_id"] if len(top) else None, len(high), ticket_threshold)
    return insights
