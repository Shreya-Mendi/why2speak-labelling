"""
Pull labels from the central Postgres store into kappa_results/labels_<name>.csv,
one file per labeller — the exact format score_kappa.py expects.

    python pull_db.py                          # reads url from .streamlit/secrets.toml
    python pull_db.py --url postgresql://...   # or pass it explicitly
    python pull_db.py --status                 # just show per-labeller progress
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
OUT = HERE / "kappa_results"


def secrets_url() -> str | None:
    p = HERE / ".streamlit" / "secrets.toml"
    if not p.exists():
        return None
    try:
        import tomllib
        cfg = tomllib.loads(p.read_text())
    except ModuleNotFoundError:  # py<3.11
        import toml
        cfg = toml.loads(p.read_text())
    return (cfg.get("db") or {}).get("url") or cfg.get("DATABASE_URL")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=None, help="postgres connection string")
    ap.add_argument("--status", action="store_true", help="progress only, no files")
    args = ap.parse_args()

    url = args.url or secrets_url()
    if not url:
        sys.exit("no db url: pass --url or put [db] url=... in .streamlit/secrets.toml")

    import psycopg2
    conn = psycopg2.connect(url, connect_timeout=10)
    df = pd.read_sql(
        "SELECT labeller, item_id AS id, label AS your_label, saved_utc "
        "FROM labels ORDER BY labeller, item_id", conn)
    conn.close()

    if df.empty:
        print("db reachable — 0 labels saved yet")
        return

    print("per-labeller progress:")
    for name, g in df.groupby("labeller"):
        print(f"  {name:14s} {len(g):4d} labels   (latest {g['saved_utc'].max()})")

    if args.status:
        return

    OUT.mkdir(exist_ok=True)
    for name, g in df.groupby("labeller"):
        path = OUT / f"labels_{name}.csv"
        g[["id", "your_label", "labeller", "saved_utc"]].to_csv(path, index=False)
        print(f"wrote {path}")
    print("\nnext: python score_kappa.py --judge ../results/stated_type_for_kappa_base.csv")


if __name__ == "__main__":
    main()
