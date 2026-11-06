import pandas as pd
import pytest

from pipeline.loaders import load_source
from pipeline.schema import build_alias_lookup, normalize_column_name, standardize_columns


@pytest.mark.parametrize("name", ["customer_id", "customerId", "CUSTOMER ID", "Customer-Id", "customer__id"])
def test_normalize_column_name_variants(name):
    assert normalize_column_name(name) == "customerid"


@pytest.mark.parametrize("col", ["customerId", "cust_id", "Cust_ID", "C_ID", "CID", "cust-id", "Customer_Number"])
def test_customer_id_aliases_map_to_standard_name(cfg, col):
    df = pd.DataFrame({col: ["C0001"], "LTV": ["100"]})
    out, mapping, unmapped = standardize_columns(df, cfg["column_aliases"], "test")
    assert "customer_id" in out.columns
    assert "lifetime_value" in out.columns
    assert unmapped == []


def test_unknown_columns_are_kept_and_reported(cfg):
    df = pd.DataFrame({"cust_id": ["C0001"], "loyalty_points": [10]})
    out, _, unmapped = standardize_columns(df, cfg["column_aliases"], "test")
    assert "loyalty_points" in out.columns
    assert unmapped == ["loyalty_points"]


def test_missing_id_column_raises(cfg):
    with pytest.raises(ValueError, match="No customer ID column"):
        standardize_columns(pd.DataFrame({"name": ["A"]}), cfg["column_aliases"], "test")


def test_conflicting_alias_config_raises():
    with pytest.raises(ValueError):
        build_alias_lookup({"customer_id": ["id"], "order_id": ["id"]})


def test_load_json_list_and_wrapped_object(tmp_path):
    (tmp_path / "a.json").write_text('[{"customer_id": "C0001"}]')
    (tmp_path / "b.json").write_text('{"customers": [{"customer_id": "C0001"}, {"customer_id": "C0002"}]}')
    assert len(load_source(tmp_path / "a.json")) == 1
    assert len(load_source(tmp_path / "b.json")) == 2


def test_load_csv(tmp_path):
    (tmp_path / "o.csv").write_text("cust_id,total_orders\nC0001,5\nC0002,\n")
    df = load_source(tmp_path / "o.csv")
    assert list(df.columns) == ["cust_id", "total_orders"]
    assert df.iloc[1]["total_orders"] == ""


def test_load_xml_empty_element_becomes_none(tmp_path):
    (tmp_path / "s.xml").write_text(
        "<customers><customer><customerId>C0001</customerId><tickets>4</tickets></customer>"
        "<customer><customerId /><tickets>2</tickets></customer></customers>"
    )
    df = load_source(tmp_path / "s.xml", {"xml_record_tag": "customer"})
    assert len(df) == 2
    assert df.iloc[1]["customerId"] is None


def test_unsupported_format_raises(tmp_path):
    (tmp_path / "x.txt").write_text("hi")
    with pytest.raises(ValueError, match="Unsupported"):
        load_source(tmp_path / "x.txt")
