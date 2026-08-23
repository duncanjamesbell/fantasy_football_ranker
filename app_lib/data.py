"""
Cached data loading for the Streamlit app.

Mirrors composite_ranks.ipynb's own loading cell exactly: always load the
latest available files (not year-specific "thru_{year}" snapshots), and let
calculate_composite_ranks's thru_year parameter cap the analysis. Loading a
year-specific snapshot instead would silently miss bug fixes applied to the
current data (see the notebook's own comment on this).
"""

import streamlit as st
import pandas as pd

from config import (
    CONSOLIDATED_MASTER_PATH, OVERRIDES_PATH, DRAFT_DF_PATH,
    rs_matchups_path, playoffs_path, faab_path, SEASONS,
)
from metrics.composite import load_overrides


@st.cache_data
def load_all_data() -> dict:
    """
    Loads once per app process (no arguments -> single cache entry, shared
    across every user session on a deployed instance). Returns a dict rather
    than a tuple so call sites are self-documenting.
    """
    latest_year = max(SEASONS)
    return {
        "master": pd.read_csv(CONSOLIDATED_MASTER_PATH),
        "rs_matchups": pd.read_csv(rs_matchups_path(latest_year)),
        "draft": pd.read_csv(DRAFT_DF_PATH),
        "faab": pd.read_csv(faab_path(latest_year)),
        "playoffs": pd.read_csv(playoffs_path(latest_year)),
        "overrides": load_overrides(OVERRIDES_PATH),
        "latest_year": latest_year,
    }
