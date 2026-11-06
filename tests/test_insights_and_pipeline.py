import json
from pathlib import Path

import pytest

from pipeline.insights import assign_segment, segment_thresholds
from pipeline.run import run_pipeline

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


@pytest.mark.parametrize("value, expected", [
    (250000, "Gold"), (100001, "Gold"), (100000, "Silver"), (50000, "Silver"),
    (49999, "Bronze"), (0, "Bronze"), (None, "Unknown"),
])
def test_fixed_segment_boundaries(value, expected):
    assert assign_segment(value, 100000, 50000) == expected


def test_percentile_thresholds():
    values = list(range(1, 101))
    gold, silver = segment_thresholds(values, {"method": "percentile",
                                               "percentile": {"gold_top_pct": 20, "silver_next_pct": 30}})
    segments = [assign_segment(v, gold, silver) for v in values]
    assert segments.count("Gold") == 20
    assert segments.count("Silver") == 30
    assert segments.count("Bronze") == 50


def test_end_to_end_on_provided_data(make_config):
    result = run_pipeline(make_config(RAW_DIR))
    s = result["report"]["summary"]
    assert s["total_records"] == 1501
    assert s["duplicates"] == 1
    assert s["invalid_customer_ids"] == 1
    assert s["invalid_emails"] == 3
    assert s["missing_fields"] == 1
    assert s["negative_revenue"] == 1
    assert s["inconsistent_values"] == 35
    assert s["removed_records"] == 2
    assert s["successful_records"] == 1501 - 2 - 40

    out_dir = Path(result["report"]["log_file"]).parent.parent / "output"
    customers = json.loads((out_dir / "customer_360.json").read_text())
    by_id = {c["customer_id"]: c for c in customers}
    assert len(customers) == 500
    assert len(by_id) == 500
    assert by_id["C0420"]["lifetime_value"] is None
    assert by_id["C0420"]["segment"] == "Unknown"
    assert by_id["C0450"]["dq_flags"] == ["missing_support_record"]
    assert by_id["C0125"]["email"] is None

    expected_fields = {"customer_id", "name", "email", "city", "registration_date", "total_orders",
                       "lifetime_value", "last_order_date", "support_tickets", "last_ticket_date"}
    assert expected_fields <= set(customers[0])

    insights = json.loads((out_dir / "insights.json").read_text())
    assert len(insights["top_customers"]) == 10
    values = [c["lifetime_value"] for c in insights["top_customers"]]
    assert values == sorted(values, reverse=True)


def test_end_to_end_with_renamed_columns_and_orphans(tmp_path, make_config):
    src = tmp_path / "in"
    src.mkdir()
    (src / "crm.json").write_text(json.dumps([
        {"Cust_ID": "C0001", "Full_Name": "A", "Email_Address": "a@x.com", "Location": "Pune", "Signup_Date": "2024-01-01"},
        {"Cust_ID": "C0002", "Full_Name": "B", "Email_Address": "b@x.com", "Location": "Delhi", "Signup_Date": "2024-01-01"},
    ]))
    (src / "orders.csv").write_text("C_ID,Order_Count,Revenue,Last_Order\nC0001,3,60000,2026-01-01\nC0009,1,10,2026-01-01\n")
    (src / "support.xml").write_text("<r><c><CustomerID>C0002</CustomerID><Tickets>7</Tickets></c></r>")
    config = make_config(src, sources=[
        {"name": "crm", "file": "crm.json", "primary": True},
        {"name": "orders", "file": "orders.csv"},
        {"name": "support", "file": "support.xml", "xml_record_tag": "c"},
    ])
    result = run_pipeline(config)
    c360 = result["customer_360"].set_index("customer_id")

    assert list(c360.index) == ["C0001", "C0002"]
    assert c360.loc["C0001", "segment"] == "Silver"
    assert "missing_orders_record" in c360.loc["C0002", "dq_flags"]
    assert "missing_support_record" in c360.loc["C0001", "dq_flags"]
    assert result["report"]["summary"]["orphan_records"] == 1


@pytest.mark.parametrize("days, expected", [
    (0, "Active"), (90, "Active"), (91, "Cooling"), (180, "Cooling"), (181, "Inactive"), (None, "Unknown"),
])
def test_activity_status_boundaries(days, expected):
    from pipeline.insights import activity_status
    assert activity_status(days, 90, 180) == expected
