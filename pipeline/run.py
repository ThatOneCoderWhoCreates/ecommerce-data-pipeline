"""Pipeline entry point: load -> standardize -> validate -> merge -> insights -> write outputs."""

import argparse
import json
import time
from pathlib import Path

from .config import PROJECT_ROOT, load_config
from .insights import add_segments, generate_insights
from .loaders import load_source
from .logger import setup_logging
from .merge import add_cross_source_checks, add_derived_fields, merge_sources, order_columns, to_json_records
from .quality import IssueLog, build_quality_report, reference_date, validate_source
from .schema import standardize_columns


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False, default=str)


def run_pipeline(config_path=None):
    cfg = load_config(config_path)
    log, log_file = setup_logging(cfg["log_dir"], cfg.get("log_level", "INFO"))
    start = time.perf_counter()
    log.info("Pipeline started with config %s", cfg["_config_path"])

    issues = IssueLog()
    raw_counts, clean_sources, mappings, unmapped = {}, {}, {}, {}
    primary = next(s["name"] for s in cfg["input_sources"] if s.get("primary"))

    # Steps 1 to 3, per source.
    for source in cfg["input_sources"]:
        name = source["name"]
        raw = load_source(Path(cfg["input_dir"]) / source["file"], source)
        raw_counts[name] = len(raw)
        standardized, mapping, extra = standardize_columns(raw, cfg["column_aliases"], name)
        mappings[name], unmapped[name] = mapping, extra
        clean_sources[name] = validate_source(standardized, name, cfg, issues)

    # Step 4: merge.
    c360 = merge_sources(clean_sources, primary, issues)
    for col in cfg["column_aliases"]:
        if col not in c360.columns:
            log.warning("No source provided '%s'; the column is added with null values", col)
            c360[col] = None
    c360 = add_cross_source_checks(c360, issues)
    c360 = add_derived_fields(c360, reference_date(cfg))
    c360, seg_info = add_segments(c360, cfg["segmentation"])
    c360 = order_columns(c360).sort_values("customer_id").reset_index(drop=True)

    # Step 5: insights and reports.
    insights = generate_insights(c360, seg_info, cfg["insights"])
    report = build_quality_report(raw_counts, issues, c360, mappings, unmapped)
    try:
        report["log_file"] = str(Path(log_file).relative_to(PROJECT_ROOT))
    except ValueError:
        report["log_file"] = str(log_file)

    out = Path(cfg["output_dir"])
    write_json(out / "customer_360.json", to_json_records(c360))
    write_json(out / "data_quality_report.json", report)
    write_json(out / "data_quality_issues.json", issues.entries)
    write_json(out / "quarantine.json", issues.quarantine)
    write_json(out / "insights.json", insights)

    s = report["summary"]
    log.info("Quality summary: total=%d removed=%d repaired=%d successful=%d",
             s["total_records"], s["removed_records"], s["repaired_records"], s["successful_records"])
    log.info("Wrote %d customer profiles and reports to %s", len(c360), out)
    log.info("Pipeline finished in %.2f s", time.perf_counter() - start)
    return {"customer_360": c360, "report": report, "insights": insights, "issues": issues}


def main():
    parser = argparse.ArgumentParser(description="Run the Customer 360 data pipeline")
    parser.add_argument("--config", default=None, help="Path to the pipeline config JSON")
    args = parser.parse_args()
    run_pipeline(args.config)


if __name__ == "__main__":
    main()
