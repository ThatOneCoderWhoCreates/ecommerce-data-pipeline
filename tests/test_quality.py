from datetime import date

import pandas as pd
import pytest

from pipeline.quality import parse_date, parse_number, validate_source


@pytest.mark.parametrize("raw, expected", [
    ("1,200", (1200, None)), ("₹ 5,000", (5000, None)), ("Rs. 99.5", (99.5, None)),
    (250, (250, None)), ("-5000", (None, "negative")), ("abc", (None, "invalid")),
])
def test_parse_money(raw, expected):
    assert parse_number(raw) == expected


def test_parse_int_rejects_fractions():
    assert parse_number("12", integer=True) == (12, None)
    assert parse_number("12.5", integer=True) == (None, "invalid")


@pytest.mark.parametrize("raw", ["2024-01-05", "05-01-2024", "05/01/2024", "2024/01/05"])
def test_parse_date_formats(raw):
    assert parse_date(raw) == (date(2024, 1, 5), None)


def test_parse_date_invalid():
    assert parse_date("31-31-2024") == (None, "invalid")


def crm_frame(rows):
    return pd.DataFrame(rows, columns=["customer_id", "name", "email", "city", "registration_date"], dtype=object)


def test_crm_checks(cfg, issues):
    df = crm_frame([
        ["C0001", "Amit", "amit@gmail.com", "mumbai", "2024-01-05"],
        ["c0001 ", "Amit", "AMIT@gmail.com", "Mumbai", "2024-01-05"],
        ["C0002", "Priya", "priya.yahoo.com", "Bangalore", "2024-01-12"],
        ["C0002", "Priya N", "priya@yahoo.com", "Pune", "2024-01-12"],
        ["", "Ghost", "g@x.com", "Delhi", "2024-01-01"],
        ["X12", "Bad", "b@x.com", "Delhi", "2024-01-01"],
        ["C0003", None, "r@x.com", "Delhi", "2099-01-01"],
    ])
    out = validate_source(df, "crm", cfg, issues).set_index("customer_id")
    counts = pd.Series([e["issue"] for e in issues.entries]).value_counts().to_dict()

    assert list(out.index) == ["C0001", "C0002", "C0003"]
    assert counts["duplicate_record"] == 1
    assert counts["conflicting_duplicate_id"] == 1
    assert counts["missing_customer_id"] == 1
    assert counts["invalid_customer_id"] == 1
    assert len(issues.quarantine) == 3

    assert out.loc["C0001", "city"] == "Mumbai"
    assert out.loc["C0002", "email"] is None
    assert out.loc["C0002", "city"] == "Bengaluru"
    assert "invalid_email" in out.loc["C0002", "_flags"]
    assert out.loc["C0003", "registration_date"] is None
    assert set(out.loc["C0003", "_flags"]) == {"missing_name", "future_registration_date"}


def test_orders_checks(cfg, issues):
    df = pd.DataFrame({
        "customer_id": ["C0001", "C0002", "C0003"],
        "total_orders": ["5", "", "abc"],
        "lifetime_value": ["1,000", "-5000", "300"],
        "last_order_date": ["2026-01-01", "2026-02-01", "2026-03-01"],
    }, dtype=object)
    out = validate_source(df, "orders", cfg, issues).set_index("customer_id")
    assert out.loc["C0001", "lifetime_value"] == 1000
    assert out.loc["C0002", "lifetime_value"] is None
    assert set(out.loc["C0002", "_flags"]) == {"missing_total_orders", "negative_lifetime_value"}
    assert out.loc["C0003", "_flags"] == ["invalid_total_orders"]


def test_ticket_date_without_tickets_is_cleared(cfg, issues):
    df = pd.DataFrame({"customer_id": ["C0001", "C0002"], "support_tickets": ["0", "3"],
                       "last_ticket_date": ["2026-05-01", "2026-05-02"]}, dtype=object)
    out = validate_source(df, "support", cfg, issues).set_index("customer_id")
    assert out.loc["C0001", "last_ticket_date"] is None
    assert out.loc["C0001", "_flags"] == ["ticket_date_without_tickets"]
    assert out.loc["C0002", "_flags"] == []
