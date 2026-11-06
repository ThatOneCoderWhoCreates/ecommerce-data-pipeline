"""Streamlit dashboard for the Customer 360 pipeline.

Run from the project root:
    streamlit run dashboard/app.py
"""

import json
import sys
from itertools import count
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.config import load_config  # noqa: E402
from pipeline.insights import activity_status  # noqa: E402
from pipeline.run import run_pipeline  # noqa: E402

st.set_page_config(page_title="Customer 360 Dashboard", page_icon="📊", layout="wide",
                   initial_sidebar_state="collapsed")

# ---------- theme ----------

IS_DARK = getattr(st.context.theme, "type", None) == "dark"
ACCENT = "#14B8A6" if IS_DARK else "#0D9488"
MUTED = "#4B5563" if IS_DARK else "#CBD5E1"
INK_STRONG = "#F3F4F6" if IS_DARK else "#111827"
INK = "#9CA3AF" if IS_DARK else "#6B7280"
GRID = "#262B33" if IS_DARK else "#EEF0F3"
CARD_BG = "rgba(255,255,255,0.035)" if IS_DARK else "#FFFFFF"
CARD_BORDER = "rgba(255,255,255,0.08)" if IS_DARK else "rgba(15,23,42,0.08)"
HEAT_RANGE = ["#132B29", "#2DD4BF"] if IS_DARK else ["#E6F4F2", "#0F766E"]

SEGMENT_ORDER = ["Gold", "Silver", "Bronze", "Unknown"]
SEGMENT_COLORS = ["#D4A23A", "#8396B0", "#B06A3E", "#6B7280"]
ACTIVITY_ORDER = ["Active", "Cooling", "Inactive", "Unknown"]
ACTIVITY_COLORS = ["#1BAF7A", "#EDA100", "#E34948", "#6B7280"]

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, .stApp {{ font-family: 'Inter', sans-serif; }}
.stApp *:not([data-testid="stIconMaterial"]):not(code):not(pre):not(pre *):not(code *) {{ font-family: 'Inter', sans-serif; }}
.block-container {{ padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1440px; }}
h1 {{ font-size: 1.85rem !important; font-weight: 700 !important; letter-spacing: -0.02em; padding-bottom: 0 !important; }}

/* cards */
[class*="st-key-card"] {{
    background: {CARD_BG};
    border: 1px solid {CARD_BORDER};
    border-radius: 16px;
    padding: 1.05rem 1.15rem 0.8rem 1.15rem;
    box-shadow: {"none" if IS_DARK else "0 1px 2px rgba(15,23,42,0.04), 0 4px 16px rgba(15,23,42,0.04)"};
}}
.stMarkdown p.card-title {{ font-size: 0.95rem !important; font-weight: 600; color: {INK_STRONG};
    margin: 0 !important; line-height: 1.35; }}
.stMarkdown p.card-sub {{ font-size: 0.78rem !important; color: {INK}; margin: 0.15rem 0 0.35rem 0 !important;
    line-height: 1.35; }}

/* KPI tiles */
[data-testid="stMetric"] {{
    background: {CARD_BG}; border: 1px solid {CARD_BORDER} !important; border-radius: 16px !important;
    padding: 0.9rem 1rem !important;
}}
[data-testid="stMetricLabel"] p {{ font-size: 0.74rem !important; text-transform: uppercase;
    letter-spacing: 0.05em; color: {INK} !important; font-weight: 500; }}
[data-testid="stMetricValue"] {{ font-size: 1.65rem !important; font-weight: 600; letter-spacing: -0.02em; }}

/* pill tabs */
div[data-baseweb="tab-list"] {{ gap: 0.35rem; }}
button[data-baseweb="tab"] {{ border-radius: 999px; padding: 0.35rem 0.95rem !important; height: auto; }}
button[data-baseweb="tab"][aria-selected="true"] {{ background: {ACCENT}22; }}
div[data-baseweb="tab-highlight"], div[data-baseweb="tab-border"] {{ display: none; }}

/* highlight rows */
.hl {{ display: flex; gap: 0.75rem; align-items: flex-start; padding: 0.55rem 0;
      border-bottom: 1px solid {CARD_BORDER}; }}
.hl:last-child {{ border-bottom: none; }}
.hl-dot {{ width: 8px; height: 8px; border-radius: 50%; margin-top: 0.42rem; flex: none; }}
.hl-label {{ font-size: 0.76rem; color: {INK}; text-transform: uppercase; letter-spacing: 0.04em; }}
.hl-value {{ font-size: 0.95rem; color: {INK_STRONG}; font-weight: 500; }}
</style>
""", unsafe_allow_html=True)

_card_ids = count()


def card(title, subtitle=None):
    """A rounded card container with a small title, used to group each chart or table."""
    box = st.container(key=f"card_{next(_card_ids)}")
    sub = f'<p class="card-sub">{subtitle}</p>' if subtitle else '<p class="card-sub"></p>'
    box.markdown(f'<p class="card-title">{title}</p>{sub}', unsafe_allow_html=True)
    return box


def style(chart):
    """Shared chart styling: no frame, light grid, muted axis text, Inter font."""
    return (chart.configure(font="Inter", background="transparent")
            .configure_view(strokeWidth=0)
            .configure_axis(domain=False, ticks=False, grid=True, gridColor=GRID, labelColor=INK, titleColor=INK,
                            labelFontSize=11, titleFontSize=11, titleFontWeight=400, labelPadding=6)
            .configure_legend(labelColor=INK, titleColor=INK, labelFontSize=11, titleFontSize=11,
                              symbolType="circle", symbolSize=90))


def show(chart):
    chart = chart.properties(padding={"left": 30, "right": 10, "top": 6, "bottom": 4})
    st.altair_chart(style(chart), width="stretch", theme=None)


# ---------- data ----------

@st.cache_data(show_spinner=False)
def load_outputs(output_dir):
    out = Path(output_dir)
    files = ["customer_360", "data_quality_report", "data_quality_issues", "quarantine", "insights"]
    if not all((out / f"{name}.json").exists() for name in files):
        run_pipeline()
    data = {name: json.loads((out / f"{name}.json").read_text(encoding="utf-8")) for name in files}
    c360 = pd.DataFrame(data["customer_360"])
    for col in ("registration_date", "last_order_date", "last_ticket_date"):
        c360[col] = pd.to_datetime(c360[col], errors="coerce")
    for col in ("total_orders", "lifetime_value", "support_tickets", "avg_order_value"):
        c360[col] = pd.to_numeric(c360[col], errors="coerce")
    c360["flag_count"] = c360["dq_flags"].map(len)
    data["c360"] = c360
    return data


def inr(value):
    """Format rupees in Indian units: crore (Cr) and lakh (L)."""
    if value is None or pd.isna(value):
        return "n/a"
    if abs(value) >= 1e7:
        return f"₹{value / 1e7:,.2f} Cr"
    if abs(value) >= 1e5:
        return f"₹{value / 1e5:,.2f} L"
    return f"₹{value:,.0f}"


MONEY_LABELS = ("datum.value == 0 ? '0' : datum.value >= 1e7 ? format(datum.value / 1e7, '.1f') + ' Cr'"
                " : format(datum.value / 1e5, '.1~f') + ' L'")


def money_axis():
    return alt.Axis(labelExpr=MONEY_LABELS, tickCount=5)


def hbar(df, x, y, x_title, tooltip, color=ACCENT, sort="-x", height=None, money=False):
    chart = (alt.Chart(df).mark_bar(cornerRadiusEnd=5, color=color, height={"band": 0.62})
             .encode(x=alt.X(x, title=x_title, axis=money_axis() if money else alt.Axis(tickCount=5)),
                     y=alt.Y(y, sort=sort, title=None, axis=alt.Axis(labelLimit=240, grid=False)),
                     tooltip=tooltip))
    return chart.properties(height=height or max(200, 34 * len(df)))


def color_bar(df, x, y, field, order, colors, x_title, tooltip, money=False, labels=None, legend=False):
    chart = (alt.Chart(df).mark_bar(cornerRadiusEnd=5, height={"band": 0.62})
             .encode(x=alt.X(x, title=x_title, axis=money_axis() if money else alt.Axis(tickCount=5)),
                     y=alt.Y(y, sort=order, title=None, axis=alt.Axis(grid=False)),
                     color=alt.Color(field, scale=alt.Scale(domain=order, range=colors),
                                     legend=alt.Legend(title=None, orient="top") if legend else None),
                     tooltip=tooltip))
    if labels:
        chart = chart + chart.mark_text(align="left", dx=6, fontSize=11, color=INK).encode(text=labels, color=alt.value(INK))
    return chart.properties(height=max(160, 40 * len(df)))


cfg = load_config()
data = load_outputs(cfg["output_dir"])
c360_all = data["c360"]
report = data["data_quality_report"]
rules = data["insights"]["segmentation"]["rules"]
days_cfg = cfg["insights"].get("activity_days", {"active_within": 90, "cooling_within": 180})

# ---------- header and filters ----------


def _set_all(key, options, value):
    for option in options:
        st.session_state[f"{key}::{option}"] = value


def dropdown_multiselect(label, options, key):
    """A compact dropdown with a checkbox per option, plus Select all and Clear."""
    for option in options:
        st.session_state.setdefault(f"{key}::{option}", True)
    chosen = [o for o in options if st.session_state[f"{key}::{o}"]]
    if len(chosen) == len(options):
        summary = "All"
    elif not chosen:
        summary = "None"
    elif len(chosen) <= 2:
        summary = ", ".join(chosen)
    else:
        summary = f"{len(chosen)} selected"
    with st.popover(f"{label}: {summary}", width="stretch", key=f"{key}_popover"):
        left, right = st.columns(2)
        left.button("Select all", key=f"{key}_all", type="tertiary", on_click=_set_all, args=(key, options, True))
        right.button("Clear", key=f"{key}_none", type="tertiary", on_click=_set_all, args=(key, options, False))
        for option in options:
            st.checkbox(option, key=f"{key}::{option}")
    return [o for o in options if st.session_state[f"{key}::{o}"]]


cities = sorted(c360_all["city"].dropna().unique())
segments = [s for s in SEGMENT_ORDER if s in set(c360_all["segment"])]

head_left, head_right = st.columns([3, 1], vertical_alignment="bottom")
with head_left:
    st.title("Customer 360")
    st.caption("Unified customer view from CRM (JSON), Order Management (CSV) and Customer Support (XML)")
with head_right:
    st.caption(f"Pipeline last run · {report['generated_at'].replace('T', ' ')}")
    if st.button("Re-run pipeline", icon=":material/refresh:", width="stretch"):
        with st.spinner("Running pipeline..."):
            run_pipeline()
        load_outputs.clear()
        st.rerun()

f_city, f_seg, f_reset, f_info = st.columns([2, 2, 1, 3], vertical_alignment="center")
with f_city:
    sel_cities = dropdown_multiselect("City", cities, "city")
with f_seg:
    sel_segments = dropdown_multiselect("Segment", segments, "segment")
with f_reset:
    st.button("Reset", icon=":material/restart_alt:", type="tertiary",
              on_click=lambda: (_set_all("city", cities, True), _set_all("segment", segments, True)))

c360 = c360_all[c360_all["city"].isin(sel_cities) & c360_all["segment"].isin(sel_segments)].copy()
with f_info:
    st.caption(f"Showing {len(c360)} of {len(c360_all)} customers",
               help="Filters apply to every tab except Data Quality, which always shows the full pipeline run.")

if c360.empty:
    st.warning("No customers match the current filters.")
    st.stop()

c360["activity"] = [activity_status(d, days_cfg["active_within"], days_cfg["cooling_within"])
                    for d in c360["days_since_last_order"]]

tabs = st.tabs(["Overview", "Revenue & Segments", "Customer Behavior", "Support", "Regional", "Data Quality",
               "Customer Lookup"])

# ---------- Overview ----------

with tabs[0]:
    revenue = c360["lifetime_value"].sum()
    inactive = c360[c360["activity"] == "Inactive"]
    k = st.columns(6)
    k[0].metric("Customers", f"{len(c360):,}")
    k[1].metric("Total revenue", inr(revenue))
    k[2].metric("Avg lifetime value", inr(c360["lifetime_value"].mean()))
    k[3].metric("Avg order value", inr(c360["avg_order_value"].mean()))
    k[4].metric("Inactive customers", f"{100 * len(inactive) / len(c360):.0f}%",
                help=f"No order in more than {days_cfg['cooling_within']} days.")
    k[5].metric("Clean profiles", f"{100 * (c360['flag_count'] == 0).mean():.1f}%",
                help="Customer profiles with no data quality flags.")

    left, right = st.columns([3, 2])
    with left:
        with card("Revenue by city", "Lifetime value of all customers in each city"):
            city_rev = c360.groupby("city", as_index=False)["lifetime_value"].sum()
            city_rev["label"] = city_rev["lifetime_value"].map(inr)
            show(hbar(city_rev, "lifetime_value:Q", "city:N", None,
                      [alt.Tooltip("city:N", title="City"), alt.Tooltip("label:N", title="Revenue")], money=True))
    with right:
        with card("Revenue share by segment", "Share of lifetime value held by each tier"):
            seg = c360.groupby("segment", as_index=False).agg(revenue=("lifetime_value", "sum"),
                                                              customers=("customer_id", "count"))
            seg = seg[seg["revenue"] > 0]
            seg["share"] = seg["revenue"] / seg["revenue"].sum()
            seg["legend"] = [f"{name}  {share:.0%}" for name, share in zip(seg["segment"], seg["share"])]
            seg["revenue_label"] = seg["revenue"].map(inr)
            seg["order"] = seg["segment"].map({s: i for i, s in enumerate(SEGMENT_ORDER)})
            legend_order = seg.sort_values("order")["legend"].tolist()
            legend_colors = [SEGMENT_COLORS[SEGMENT_ORDER.index(s)] for s in seg.sort_values("order")["segment"]]
            donut = (alt.Chart(seg).mark_arc(innerRadius=70, outerRadius=104, cornerRadius=5, padAngle=0.02)
                     .encode(theta=alt.Theta("revenue:Q", stack=True),
                             color=alt.Color("legend:N", scale=alt.Scale(domain=legend_order, range=legend_colors),
                                             legend=alt.Legend(title=None, orient="bottom", direction="horizontal",
                                                             labelFontSize=12, columnPadding=18)),
                             order=alt.Order("order:Q"),
                             tooltip=[alt.Tooltip("segment:N", title="Segment"),
                                      alt.Tooltip("revenue_label:N", title="Revenue"),
                                      alt.Tooltip("customers:Q", title="Customers"),
                                      alt.Tooltip("share:Q", title="Share", format=".1%")]))
            center = pd.DataFrame({"t": [inr(revenue)], "s": ["total revenue"]})
            big = alt.Chart(center).mark_text(fontSize=20, fontWeight=600, color=INK_STRONG, dy=-6).encode(text="t:N")
            small = alt.Chart(center).mark_text(fontSize=11, color=INK, dy=14).encode(text="s:N")
            show((donut + big + small).properties(height=270))

    left, right = st.columns([3, 2])
    with left:
        with card("Top 5 customers", "Highest lifetime value"):
            top5 = c360.dropna(subset=["lifetime_value"]).nlargest(5, "lifetime_value")
            ltv_max = float(c360["lifetime_value"].max()) if c360["lifetime_value"].notna().any() else 1.0
            st.dataframe(top5[["customer_id", "name", "city", "segment", "lifetime_value", "total_orders"]],
                         hide_index=True,
                         column_config={"customer_id": "ID", "name": "Name", "city": "City", "segment": "Segment",
                                        "lifetime_value": st.column_config.ProgressColumn(
                                            "Revenue (₹)", format="%,d", min_value=0,
                                            max_value=ltv_max),
                                        "total_orders": "Orders"})
    with right:
        with card("Highlights", "What stands out in the current selection"):
            city_top = city_rev.sort_values("lifetime_value", ascending=False).iloc[0]
            win_back = c360[(c360["activity"] == "Inactive") & (c360["segment"] == "Gold")]
            at_risk = c360[(c360["support_tickets"] > cfg["insights"]["high_ticket_threshold"]) &
                           (c360["segment"] == "Gold")]
            rows = [
                (ACCENT, "Top city", f"{city_top['city']} · {inr(city_top['lifetime_value'])}"),
                ("#E34948", "Win-back opportunity", f"{len(win_back)} inactive Gold · {inr(win_back['lifetime_value'].sum())}"),
                ("#EDA100", "Gold with many tickets", f"{len(at_risk)} customers · {inr(at_risk['lifetime_value'].sum())}"),
                ("#8396B0", "Data quality", f"{report['summary']['successful_records']:,} of "
                                            f"{report['summary']['total_records']:,} records clean as-is"),
            ]
            st.markdown("".join(
                f'<div class="hl"><span class="hl-dot" style="background:{c}"></span>'
                f'<div><div class="hl-label">{label}</div><div class="hl-value">{value}</div></div></div>'
                for c, label, value in rows), unsafe_allow_html=True)

# ---------- Revenue & Segments ----------

with tabs[1]:
    seg = (c360.groupby("segment")
           .agg(customers=("customer_id", "count"), revenue=("lifetime_value", "sum"),
                avg_lifetime_value=("lifetime_value", "mean"), avg_orders=("total_orders", "mean"),
                avg_order_value=("avg_order_value", "mean"), avg_tickets=("support_tickets", "mean"))
           .reindex([s for s in SEGMENT_ORDER if s in set(c360["segment"])]).reset_index())
    seg["customer_share_%"] = (100 * seg["customers"] / seg["customers"].sum()).round(1)
    seg["revenue_share_%"] = (100 * seg["revenue"] / seg["revenue"].sum()).round(1)
    seg["revenue_label"] = seg["revenue"].map(inr)

    left, right = st.columns(2)
    with left:
        with card("Customers by segment",
                  f"Gold > {inr(rules['gold_above'])} · Silver {inr(rules['silver_from'])} to "
                  f"{inr(rules['gold_above'])} · Bronze < {inr(rules['silver_from'])}"):
            show(color_bar(seg, "customers:Q", "segment:N", "segment:N", SEGMENT_ORDER, SEGMENT_COLORS, None,
                           [alt.Tooltip("segment:N", title="Segment"), alt.Tooltip("customers:Q", title="Customers"),
                            alt.Tooltip("customer_share_%:Q", title="Share (%)")], labels="customers:Q"))
    with right:
        with card("Revenue by segment", "Lifetime value per tier"):
            show(color_bar(seg, "revenue:Q", "segment:N", "segment:N", SEGMENT_ORDER, SEGMENT_COLORS, None,
                           [alt.Tooltip("segment:N", title="Segment"), alt.Tooltip("revenue_label:N", title="Revenue"),
                            alt.Tooltip("revenue_share_%:Q", title="Share (%)")], money=True, labels="revenue_label:N"))

    top = c360.dropna(subset=["lifetime_value"]).nlargest(10, "lifetime_value").copy()
    top["label"] = top["customer_id"] + " · " + top["name"]
    top["revenue"] = top["lifetime_value"].map(inr)
    left, right = st.columns([5, 4])
    with left:
        with card("Top 10 customers by revenue"):
            show(hbar(top, "lifetime_value:Q", "label:N", None,
                      [alt.Tooltip("label:N", title="Customer"), alt.Tooltip("city:N", title="City"),
                       alt.Tooltip("revenue:N", title="Revenue"), alt.Tooltip("total_orders:Q", title="Orders")],
                      money=True))
    with right:
        with card("Top 10 details"):
            st.dataframe(top[["customer_id", "name", "city", "lifetime_value", "total_orders"]], hide_index=True,
                         height=388,
                         column_config={"customer_id": "ID", "name": "Name", "city": "City",
                                        "lifetime_value": st.column_config.NumberColumn("Revenue (₹)", format="%,d"),
                                        "total_orders": "Orders"})

    with card("Lifetime value distribution", "Dashed lines mark the Silver and Gold cut-offs"):
        hist = (alt.Chart(c360.dropna(subset=["lifetime_value"]))
                .mark_bar(color=ACCENT, cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
                .encode(x=alt.X("lifetime_value:Q", bin=alt.Bin(step=10000), title="Lifetime value",
                                axis=money_axis()),
                        y=alt.Y("count():Q", title="Customers"),
                        tooltip=[alt.Tooltip("lifetime_value:Q", bin=alt.Bin(step=10000), title="Range (₹)"),
                                 alt.Tooltip("count():Q", title="Customers")]))
        cuts = pd.DataFrame({"x": [rules["silver_from"], rules["gold_above"]], "rule": ["Silver from", "Gold above"]})
        lines = alt.Chart(cuts).mark_rule(strokeDash=[4, 4], color=INK, strokeWidth=1.5).encode(
            x="x:Q", tooltip=["rule:N", alt.Tooltip("x:Q", format=",.0f")])
        show((hist + lines).properties(height=240))

    with card("Segment summary"):
        st.dataframe(seg.drop(columns=["revenue_label"]).round(1), hide_index=True,
                     column_config={"revenue": st.column_config.NumberColumn("revenue (₹)", format="%,d"),
                                    "avg_lifetime_value": st.column_config.NumberColumn(format="%,d"),
                                    "avg_order_value": st.column_config.NumberColumn(format="%,d")})

# ---------- Customer Behavior ----------

with tabs[2]:
    beh = c360
    win_back = beh[(beh["activity"] == "Inactive") & (beh["segment"] == "Gold")].sort_values(
        "lifetime_value", ascending=False)
    inactive = beh[beh["activity"] == "Inactive"]

    k = st.columns(4)
    k[0].metric("Active", f"{(beh['activity'] == 'Active').sum():,}",
                help=f"Ordered within {days_cfg['active_within']} days.")
    k[1].metric("Cooling", f"{(beh['activity'] == 'Cooling').sum():,}",
                help=f"Last order {days_cfg['active_within'] + 1} to {days_cfg['cooling_within']} days ago.")
    k[2].metric("Inactive", f"{len(inactive):,}",
                help=f"No order in more than {days_cfg['cooling_within']} days.")
    k[3].metric("Inactive Gold (win-back)", f"{len(win_back):,} · {inr(win_back['lifetime_value'].sum())}")

    corr_orders = beh["lifetime_value"].corr(beh["total_orders"])
    corr_aov = beh["lifetime_value"].corr(beh["avg_order_value"])
    corr_tickets = beh["lifetime_value"].corr(beh["support_tickets"])
    aov_seg = beh.groupby("segment")["avg_order_value"].mean()
    with card("Key findings"):
        findings = [
            ("#E34948", "Inactive customers",
             f"{100 * len(inactive) / len(beh):.0f}% have not ordered in more than {days_cfg['cooling_within']} days "
             f"and hold {inr(inactive['lifetime_value'].sum())} of lifetime revenue."),
            (ACCENT, "Spending pattern",
             f"High-value customers spend more per order, not more often (revenue vs orders r = {corr_orders:.2f}, "
             f"revenue vs average order value r = {corr_aov:.2f})."),
            ("#D4A23A", "Order size by tier",
             f"Gold customers spend about {inr(aov_seg.get('Gold'))} per order, compared with "
             f"{inr(aov_seg.get('Bronze'))} for Bronze."),
            ("#8396B0", "Support vs spend",
             f"Support tickets are not linked to spending (r = {corr_tickets:.2f}), so ticket volume is similar "
             f"across tiers."),
        ]
        st.markdown("".join(
            f'<div class="hl"><span class="hl-dot" style="background:{c}"></span>'
            f'<div><div class="hl-label">{label}</div><div class="hl-value">{text}</div></div></div>'
            for c, label, text in findings), unsafe_allow_html=True)

    left, right = st.columns(2)
    with left:
        with card("Customers by activity status",
                  f"Active ≤ {days_cfg['active_within']} days · Cooling ≤ {days_cfg['cooling_within']} days · "
                  f"Inactive > {days_cfg['cooling_within']} days since last order"):
            act = (beh.groupby("activity", as_index=False)
                   .agg(customers=("customer_id", "count"), revenue=("lifetime_value", "sum")))
            act["revenue_label"] = act["revenue"].map(inr)
            show(color_bar(act, "customers:Q", "activity:N", "activity:N", ACTIVITY_ORDER, ACTIVITY_COLORS, None,
                           [alt.Tooltip("activity:N", title="Status"), alt.Tooltip("customers:Q", title="Customers"),
                            alt.Tooltip("revenue_label:N", title="Lifetime revenue")], labels="customers:Q"))
    with right:
        with card("Activity status by segment", "Share of each tier's customers"):
            mix = beh.groupby(["segment", "activity"], as_index=False).agg(customers=("customer_id", "count"))
            mix["order"] = mix["activity"].map({a: i for i, a in enumerate(ACTIVITY_ORDER)})
            chart = (alt.Chart(mix).mark_bar(height={"band": 0.62})
                     .encode(x=alt.X("customers:Q", stack="normalize", title=None,
                                     axis=alt.Axis(format="%", tickCount=5)),
                             y=alt.Y("segment:N", sort=SEGMENT_ORDER, title=None, axis=alt.Axis(grid=False)),
                             color=alt.Color("activity:N", scale=alt.Scale(domain=ACTIVITY_ORDER, range=ACTIVITY_COLORS),
                                             legend=alt.Legend(title=None, orient="top")),
                             order=alt.Order("order:Q"),
                             tooltip=[alt.Tooltip("segment:N", title="Segment"),
                                      alt.Tooltip("activity:N", title="Status"),
                                      alt.Tooltip("customers:Q", title="Customers")]))
            show(chart.properties(height=190))

    left, right = st.columns(2)
    with left:
        with card("Average order value by segment"):
            aov_s = beh.groupby("segment", as_index=False)["avg_order_value"].mean().dropna()
            aov_s["label"] = aov_s["avg_order_value"].map(inr)
            show(color_bar(aov_s, "avg_order_value:Q", "segment:N", "segment:N", SEGMENT_ORDER, SEGMENT_COLORS, None,
                           [alt.Tooltip("segment:N", title="Segment"), alt.Tooltip("label:N", title="Avg order value")],
                           labels="label:N"))
    with right:
        with card("Average order value by city"):
            aov_c = beh.groupby("city", as_index=False)["avg_order_value"].mean()
            aov_c["label"] = aov_c["avg_order_value"].map(inr)
            show(hbar(aov_c, "avg_order_value:Q", "city:N", None,
                      [alt.Tooltip("city:N", title="City"), alt.Tooltip("label:N", title="Avg order value")]))

    left, right = st.columns(2)
    with left:
        with card("Orders vs lifetime value", f"Each dot is a customer · correlation {corr_orders:.2f}"):
            pts = beh.dropna(subset=["lifetime_value", "total_orders"])
            scatter = (alt.Chart(pts).mark_circle(size=55, opacity=0.55, color=ACCENT)
                       .encode(x=alt.X("total_orders:Q", title="Total orders"),
                               y=alt.Y("lifetime_value:Q", title="Lifetime value", axis=money_axis()),
                               tooltip=[alt.Tooltip("customer_id:N", title="Customer"),
                                        alt.Tooltip("total_orders:Q", title="Orders"),
                                        alt.Tooltip("lifetime_value:Q", title="Lifetime value (₹)", format=",.0f")]))
            show(scatter.properties(height=270))
    with right:
        with card("New registrations by quarter"):
            reg = beh["registration_date"].dropna().dt.to_period("Q").astype(str).value_counts().sort_index().reset_index()
            reg.columns = ["quarter", "customers"]
            chart = (alt.Chart(reg).mark_bar(color=ACCENT, cornerRadiusTopLeft=5, cornerRadiusTopRight=5,
                                             width={"band": 0.6})
                     .encode(x=alt.X("quarter:O", title=None, axis=alt.Axis(labelAngle=0, grid=False)),
                             y=alt.Y("customers:Q", title="New customers", axis=alt.Axis(tickCount=4)),
                             tooltip=[alt.Tooltip("quarter:O", title="Quarter"),
                                      alt.Tooltip("customers:Q", title="New customers")]))
            show(chart.properties(height=270))

    with card("Win-back list", "Inactive Gold customers, highest value first"):
        cols = ["customer_id", "name", "city", "lifetime_value", "total_orders", "last_order_date",
                "days_since_last_order"]
        st.dataframe(win_back[cols], hide_index=True, height=320,
                     column_config={"last_order_date": st.column_config.DateColumn(format="YYYY-MM-DD"),
                                    "lifetime_value": st.column_config.NumberColumn("Revenue (₹)", format="%,d")})
        st.download_button("Download win-back list (CSV)", win_back[cols].to_csv(index=False),
                           "inactive_gold_customers.csv", "text/csv", icon=":material/download:")

# ---------- Support ----------

with tabs[3]:
    threshold = st.slider("Ticket threshold", 0, int(c360_all["support_tickets"].max() or 10),
                          int(cfg["insights"]["high_ticket_threshold"]))
    high = c360[c360["support_tickets"] > threshold].sort_values(["support_tickets", "lifetime_value"],
                                                                  ascending=False)
    at_risk = high[high["segment"] == "Gold"]
    k = st.columns(4)
    k[0].metric(f"Customers with > {threshold} tickets", f"{len(high):,}")
    k[1].metric("Share of customers", f"{100 * len(high) / len(c360):.1f}%")
    k[2].metric("Gold among them", f"{len(at_risk):,}",
                help="High-value customers with many tickets: the main retention risk.")
    k[3].metric("Revenue at risk (Gold)", inr(at_risk["lifetime_value"].sum()))

    left, right = st.columns(2)
    with left:
        with card("Ticket distribution", f"Customers above the threshold are highlighted"):
            dist = c360["support_tickets"].dropna().astype(int).value_counts().sort_index().reset_index()
            dist.columns = ["tickets", "customers"]
            dist["group"] = dist["tickets"].map(
                lambda t: f"More than {threshold}" if t > threshold else f"{threshold} or fewer")
            chart = (alt.Chart(dist).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, width={"band": 0.7})
                     .encode(x=alt.X("tickets:O", title="Tickets per customer", axis=alt.Axis(labelAngle=0, grid=False)),
                             y=alt.Y("customers:Q", title="Customers", axis=alt.Axis(tickCount=4)),
                             color=alt.Color("group:N", scale=alt.Scale(
                                 domain=[f"{threshold} or fewer", f"More than {threshold}"], range=[MUTED, ACCENT]),
                                 legend=alt.Legend(title=None, orient="top")),
                             tooltip=[alt.Tooltip("tickets:O", title="Tickets"),
                                      alt.Tooltip("customers:Q", title="Customers")]))
            show(chart.properties(height=250))
    with right:
        with card("Average tickets by segment"):
            avg_t = (c360.groupby("segment", as_index=False)["support_tickets"].mean()
                     .rename(columns={"support_tickets": "avg_tickets"}))
            avg_t["avg_tickets"] = avg_t["avg_tickets"].round(2)
            show(color_bar(avg_t, "avg_tickets:Q", "segment:N", "segment:N", SEGMENT_ORDER, SEGMENT_COLORS, None,
                           [alt.Tooltip("segment:N", title="Segment"), alt.Tooltip("avg_tickets:Q", title="Avg tickets")],
                           labels="avg_tickets:Q"))

    with card(f"Customers with more than {threshold} tickets", "Sorted by tickets, then revenue"):
        cols = ["customer_id", "name", "city", "support_tickets", "last_ticket_date", "lifetime_value", "segment"]
        st.dataframe(high[cols], hide_index=True, height=360,
                     column_config={"last_ticket_date": st.column_config.DateColumn(format="YYYY-MM-DD"),
                                    "lifetime_value": st.column_config.NumberColumn("Revenue (₹)", format="%,d")})
        st.download_button("Download list (CSV)", high[cols].to_csv(index=False), "high_ticket_customers.csv",
                           "text/csv", icon=":material/download:")

# ---------- Regional ----------

with tabs[4]:
    city = (c360.groupby("city")
            .agg(customers=("customer_id", "count"), revenue=("lifetime_value", "sum"),
                 avg_lifetime_value=("lifetime_value", "mean"), avg_orders=("total_orders", "mean"),
                 avg_tickets=("support_tickets", "mean"))
            .sort_values("revenue", ascending=False).reset_index())
    city["revenue_label"] = city["revenue"].map(inr)
    left, right = st.columns(2)
    with left:
        with card("Revenue by city"):
            show(hbar(city, "revenue:Q", "city:N", None,
                      [alt.Tooltip("city:N", title="City"), alt.Tooltip("revenue_label:N", title="Revenue")],
                      money=True))
    with right:
        with card("Customer count by city"):
            show(hbar(city, "customers:Q", "city:N", None,
                      [alt.Tooltip("city:N", title="City"), alt.Tooltip("customers:Q", title="Customers")]))

    with card("Customers by city and segment", "Stronger color means more customers"):
        mix = c360.groupby(["city", "segment"], as_index=False).agg(customers=("customer_id", "count"))
        cutoff = mix["customers"].max() * 0.55
        base = alt.Chart(mix).encode(
            x=alt.X("segment:N", sort=SEGMENT_ORDER, title=None, axis=alt.Axis(orient="top", grid=False, labelAngle=0)),
            y=alt.Y("city:N", sort=city["city"].tolist(), title=None, axis=alt.Axis(grid=False)))
        heat = base.mark_rect(cornerRadius=6, stroke="#FFFFFF" if not IS_DARK else "#16181D", strokeWidth=3).encode(
            color=alt.Color("customers:Q", scale=alt.Scale(range=HEAT_RANGE), legend=None),
            tooltip=[alt.Tooltip("city:N", title="City"), alt.Tooltip("segment:N", title="Segment"),
                     alt.Tooltip("customers:Q", title="Customers")])
        text = base.mark_text(fontSize=12, fontWeight=500).encode(
            text="customers:Q",
            color=alt.condition(alt.datum.customers > cutoff, alt.value("#FFFFFF" if not IS_DARK else "#0B1F1D"),
                                alt.value(INK_STRONG)))
        show((heat + text).properties(height=34 * len(city) + 30))

    with card("City summary"):
        st.dataframe(city.drop(columns=["revenue_label"]).round(2), hide_index=True,
                     column_config={"revenue": st.column_config.NumberColumn("revenue (₹)", format="%,d"),
                                    "avg_lifetime_value": st.column_config.NumberColumn(format="%,d")})

# ---------- Data Quality ----------

with tabs[5]:
    s = report["summary"]
    row1 = st.columns(4)
    row1[0].metric("Total records", f"{s['total_records']:,}")
    row1[1].metric("Clean as-is", f"{s['successful_records']:,}")
    row1[2].metric("Repaired and kept", f"{s['repaired_records']:,}",
                   help="Kept with a flag; the bad value was set to null.")
    row1[3].metric("Removed", f"{s['removed_records']:,}", help="Dropped duplicates plus quarantined records.")
    row2 = st.columns(6)
    for col, (label, key) in zip(row2, [("Duplicates", "duplicates"), ("Invalid IDs", "invalid_customer_ids"),
                                         ("Invalid emails", "invalid_emails"), ("Missing fields", "missing_fields"),
                                         ("Negative revenue", "negative_revenue"),
                                         ("Inconsistent values", "inconsistent_values")]):
        col.metric(label, s[key])

    left, right = st.columns(2)
    with left:
        with card("Records by source"):
            src = pd.DataFrame(report["by_source"]).T.reset_index().rename(columns={"index": "source"})
            st.dataframe(src, hide_index=True)
        with card("Issues found", "Each record is counted once per issue"):
            br = pd.DataFrame(list(report["issue_breakdown"].items()), columns=["issue", "count"])
            show(hbar(br, "count:Q", "issue:N", None,
                      [alt.Tooltip("issue:N", title="Issue"), alt.Tooltip("count:Q", title="Count")]))
    with right:
        with card("Field completeness", "Share of Customer 360 profiles with a value in each field"):
            comp = pd.DataFrame(list(report["customer_360"]["field_completeness_pct"].items()),
                                columns=["field", "complete_pct"])
            chart = (alt.Chart(comp).mark_bar(cornerRadiusEnd=5, color=ACCENT, height={"band": 0.62})
                     .encode(x=alt.X("complete_pct:Q", title="Complete (%)", scale=alt.Scale(domain=[0, 100]),
                                     axis=alt.Axis(tickCount=5)),
                             y=alt.Y("field:N", sort=comp["field"].tolist(), title=None, axis=alt.Axis(grid=False)),
                             tooltip=[alt.Tooltip("field:N", title="Field"),
                                      alt.Tooltip("complete_pct:Q", title="Complete (%)")]))
            show(chart.properties(height=30 * len(comp)))

    with card("Column mapping", "How each source's column names were standardized"):
        mapping_rows = [{"source": src_name, "original_column": orig, "standard_column": std}
                        for src_name, m in report["column_mappings"].items() for orig, std in m.items()]
        st.dataframe(pd.DataFrame(mapping_rows), hide_index=True)

    with card("Quarantined records", "Records removed because they could not be trusted"):
        q = data["quarantine"]
        if q:
            st.dataframe(pd.DataFrame([{**{k: v for k, v in r.items() if k != "record"},
                                        "record": json.dumps(r["record"])} for r in q]), hide_index=True)
        else:
            st.success("No records were quarantined.")

    with card("Issue log", "Every data quality decision the pipeline made"):
        log_df = pd.DataFrame(data["data_quality_issues"])
        log_df["record_number"] = pd.to_numeric(log_df["record_number"], errors="coerce").astype("Int64")
        pick = st.multiselect("Filter by issue", sorted(log_df["issue"].unique()))
        st.dataframe(log_df[log_df["issue"].isin(pick)] if pick else log_df, hide_index=True, height=320)
        with st.expander("Raw data quality report (JSON)"):
            st.json(report)

# ---------- Customer Lookup ----------

with tabs[6]:
    ids = c360["customer_id"].tolist()
    cid = st.selectbox("Customer ID", ids, index=0)
    raw = next(r for r in data["customer_360"] if r["customer_id"] == cid)
    k = st.columns(5)
    k[0].metric("Segment", raw["segment"])
    k[1].metric("Lifetime value", inr(raw["lifetime_value"]))
    k[2].metric("Orders", raw["total_orders"] if raw["total_orders"] is not None else "n/a")
    k[3].metric("Support tickets", raw["support_tickets"] if raw["support_tickets"] is not None else "n/a")
    k[4].metric("Days since last order", raw.get("days_since_last_order") or "n/a")
    if raw["dq_flags"]:
        st.warning("Data quality flags: " + ", ".join(raw["dq_flags"]))
    else:
        st.success("No data quality issues for this customer.")
    with card(f"{raw['name']} · {raw['city']}", "Full Customer 360 profile"):
        st.json(raw)
