# Streamlit App

A browser-based presentation layer over the composite-ranking analysis, for sharing with the
league (~11 people) without requiring anyone to run a notebook. `composite_ranks.ipynb` remains
the primary tool for iterating on the metric calculations themselves — this app only imports and
calls `metrics/composite.py`'s public functions, it never modifies them.

## Running locally

The app needs its own virtual environment, separate from the global interpreter the rest of this
project's scripts/notebooks use — installing Streamlit's dependency tree into the global
environment previously upgraded `numpy` in a way that broke `pandas`/`metrics/composite.py` for
every other script on the machine. Keep the venv isolated:

```bash
py -m venv .venv-streamlit
.venv-streamlit/Scripts/pip install -r requirements.txt
```

Copy the secrets template and set a local test passphrase:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edit .streamlit/secrets.toml, set APP_PASSPHRASE to whatever you want locally
```

Run it:

```bash
.venv-streamlit/Scripts/streamlit run streamlit_app.py
```

## Data files

The app reads the same `data/processed/*.csv` and `data/reference/overrides.yaml` files the
notebook does, always the latest available (never year-specific `thru_{year}` snapshots — see
the loading comment in `composite_ranks.ipynb`'s first cell for why). For Streamlit Community
Cloud to see current-season data, the relevant `*_thru_{latest_year}.csv` files must actually be
committed to the repo — several of these filenames are normally gitignored (to keep old dated
snapshot variants out of the repo), so a new season's files need `git add -f` each year rather
than just `git add`.

## Secrets: local vs. deployed

- **Local**: `.streamlit/secrets.toml` (gitignored — never commit the real passphrase).
  `.streamlit/secrets.toml.example` is the committed placeholder showing the expected shape.
- **Streamlit Community Cloud**: set via the app's dashboard → Settings → Secrets, in the same
  TOML format. This is separate from the local file — deploying doesn't read your local secrets.

## Deploying / updating

Cloud redeploys automatically on every push to `main`. To stand up a new deployment: push to
GitHub, create the app at share.streamlit.io pointing at this repo/branch with main file
`streamlit_app.py`, set the `APP_PASSPHRASE` secret in the dashboard, and share the resulting URL.
The passphrase gate is a lightweight shared-secret check (`st.session_state`, per browser
session), not real user accounts — appropriate for a small known group, not a public product.

## App structure

```
streamlit_app.py       # entry point: auth gate, sidebar controls, tab layout
app_lib/data.py         # cached CSV/overrides loading (load_all_data, no args)
app_lib/compute.py      # cached wrapper around calculate_composite_ranks
app_lib/reporting.py    # metric_scoreboard / explain_manager_view (ported from the notebook)
app_lib/plots.py        # trend-plot builders (ported from the notebook, return Figure objects)
app_lib/methodology.py  # static methodology markdown
app_lib/auth.py         # passphrase gate
```

Single-file-with-tabs, not Streamlit's native multi-page `pages/` structure — every tab shares
the same sidebar controls and the same computed result, which multi-page apps would need
`st.session_state` bookkeeping to replicate for no benefit here.
