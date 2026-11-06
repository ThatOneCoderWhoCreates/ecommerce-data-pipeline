"""Step 2: Standardize schemas.

Column names are normalized (lowercase, letters and digits only), so
"customerId", "Cust_ID", "cust-id" and "CUST ID" all become "custid". The
normalized name is then looked up in the alias list from the config to find the
standard column name, for example "customer_id".
"""

import re

from .logger import get_logger

log = get_logger()


def normalize_column_name(name):
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def build_alias_lookup(column_aliases):
    """Map every normalized alias to its standard column name."""
    lookup = {}
    for canonical, aliases in column_aliases.items():
        for alias in [canonical, *aliases]:
            key = normalize_column_name(alias)
            if key in lookup and lookup[key] != canonical:
                raise ValueError(f"Alias '{alias}' is mapped to both '{lookup[key]}' and '{canonical}'")
            lookup[key] = canonical
    return lookup


def standardize_columns(df, column_aliases, source_name):
    """Rename the DataFrame's columns to standard names.

    Returns (renamed_df, mapping, unmapped_columns). Columns that don't match any alias
    are kept but logged. If two columns map to the same standard name, the first wins.
    """
    lookup = build_alias_lookup(column_aliases)
    mapping, used, unmapped = {}, set(), []
    for col in df.columns:
        canonical = lookup.get(normalize_column_name(col))
        if canonical is None:
            unmapped.append(col)
            continue
        if canonical in used:
            log.warning("[%s] Column '%s' also maps to '%s'; keeping the first one", source_name, col, canonical)
            unmapped.append(col)
            continue
        mapping[col] = canonical
        used.add(canonical)

    renamed = df.rename(columns=mapping)
    for original, canonical in mapping.items():
        if original != canonical:
            log.info("[%s] Renamed column '%s' -> '%s'", source_name, original, canonical)
    if unmapped:
        log.warning("[%s] Columns with no matching alias (kept as is): %s", source_name, unmapped)
    if "customer_id" not in renamed.columns:
        raise ValueError(f"[{source_name}] No customer ID column found. Add its name to column_aliases.customer_id")
    return renamed, mapping, unmapped
