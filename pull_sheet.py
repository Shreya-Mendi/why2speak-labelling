"""
Pull the central Google Sheet down into per-labeller CSVs that score_kappa.py reads.
Use this when friends labelled on the hosted app (central save) rather than locally.

    python pull_sheet.py --sheet-key <KEY> --creds service_account.json

Writes kappa_results/labels_<name>.csv (last-wins per id), then you run score_kappa.py.
"""
import argparse
from pathlib import Path

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

HERE = Path(__file__).parent
OUT = HERE / "kappa_results"
OUT.mkdir(exist_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet-key", required=True)
    ap.add_argument("--creds", required=True, help="service account JSON")
    args = ap.parse_args()

    creds = Credentials.from_service_account_file(
        args.creds, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    ws = gspread.authorize(creds).open_by_key(args.sheet_key).sheet1
    df = pd.DataFrame(ws.get_all_records())
    if df.empty:
        raise SystemExit("sheet is empty")

    df["id"] = df["id"].astype(str)
    # last-wins per (labeller, id): keep the final append for each cell
    df = df.drop_duplicates(subset=["labeller", "id"], keep="last")
    for name, g in df.groupby("labeller"):
        p = OUT / f"labels_{name.strip().lower().replace(' ', '-')}.csv"
        g[["id", "your_label"]].to_csv(p, index=False)
        print(f"wrote {p}  ({len(g)} rows)")


if __name__ == "__main__":
    main()
