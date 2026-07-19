# Why2Speak — human κ-labelling app

A friendlier version of the CSV: each labeller reads a model's reasoning trace and
picks **which kind of intervention the reasoning claims to make** (6 labels). The
rubric is always on-screen, progress autosaves, and it's blind to the GPT-5 judge.

## Run locally
```bash
cd kappa_app
pip install -r requirements.txt
streamlit run app.py
```
Opens at http://localhost:8501. Each person enters a name; their labels save to
`kappa_results/labels_<name>.csv` and resume automatically.

## Share with friends (free hosting)
1. Push this `kappa_app/` folder to a GitHub repo.
2. Go to https://share.streamlit.io → **New app** → point it at `app.py`.
3. Send everyone the URL.

**Persistence — two modes:**
- **Local CSV (default, zero setup).** Community Cloud's disk is ephemeral, so each
  friend clicks **⬇︎ Download my labels** when done and sends you the file.
- **Central Google Sheet (recommended for remote labelling).** Set `[gsheets]`
  secrets (see `.streamlit/secrets.toml.example`) and everyone writes to one sheet —
  no download step. Pull it down with `python pull_sheet.py --sheet-key <KEY>
  --creds service_account.json`, which writes the per-labeller CSVs for scoring.

## How many labellers / items?
- **n=120 items is enough** for a validation footnote (κ≈0.6 → SE≈0.06). Adding items
  mostly just tightens the CI; diminishing returns past ~150.
- **A 2nd/3rd labeller on the *same* 120 is the high-value add** — it gives you
  *inter-human* κ (the achievable ceiling) next to human–judge κ. If human–judge ≈
  human–human, your claim becomes "the judge agrees with a human about as well as two
  humans agree," which is the strong form reviewers want.
- To add more items, just append rows (`id,reasoning_text`) to
  `results/kappa_labelling_sheet.csv` — the app reads whatever length it finds.

## Score it
Collect everyone's `labels_*.csv` into `kappa_results/` (or run `pull_sheet.py`), then:
```bash
python score_kappa.py --judge ../results/stated_type_for_kappa_base.csv
```
Prints each labeller's Cohen's κ vs the GPT-5 judge **and** inter-human κ if ≥2 people.
The `None` label is preserved (it is a real category, not a missing value).
Mean κ ≥ ~0.6 validates the judge → fills the paper's two remaining red marks.

## Files
| file | what |
|---|---|
| `app.py` | the labelling interface |
| `results/kappa_labelling_sheet.csv` | the 120 items (id, reasoning_text) |
| `kappa_results/` | per-labeller output (autosaved) |
| `score_kappa.py` | Cohen's κ scorer |
