"""
Compute Cohen's κ between each human labeller and the GPT-5 judge, and (if >1 human)
inter-human agreement. Drop-in for the paper's two red marks.

    python score_kappa.py --judge ../results/stated_type_for_kappa_base.csv

Human label files are read from kappa_results/labels_*.csv (written by app.py).
The judge CSV must have columns: id, <a column holding the judge's stated type>.
"""
import argparse
import glob
from itertools import combinations
from pathlib import Path

import pandas as pd
from sklearn.metrics import cohen_kappa_score

HERE = Path(__file__).parent


def norm(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower()


def find_label_col(df: pd.DataFrame) -> str:
    for c in df.columns:
        if c.lower() in {"stated_type", "stated", "judge_label", "label", "type", "your_label"}:
            return c
    # fall back to the last non-id column
    return [c for c in df.columns if c.lower() != "id"][-1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", required=True, help="GPT-5 judge CSV (id,stated_type)")
    ap.add_argument("--humans", default=str(HERE / "kappa_results" / "labels_*.csv"))
    args = ap.parse_args()

    # keep_default_na=False: "None" is a real label, not a missing value.
    judge = pd.read_csv(args.judge, dtype={"id": str}, keep_default_na=False)
    jcol = find_label_col(judge)
    judge = judge[["id", jcol]].rename(columns={jcol: "judge"})
    judge["id"] = judge["id"].astype(str)

    files = sorted(glob.glob(args.humans))
    if not files:
        raise SystemExit(f"no human label files matched {args.humans}")

    humans: dict[str, pd.DataFrame] = {}
    for f in files:
        name = Path(f).stem.replace("labels_", "")
        h = pd.read_csv(f, dtype={"id": str}, keep_default_na=False)[["id", "your_label"]]
        humans[name] = h.rename(columns={"your_label": name})

    print(f"judge column: '{jcol}'  |  humans: {', '.join(humans)}\n")

    # human vs judge
    print("=== Cohen's κ: human vs GPT-5 judge ===")
    ks = []
    for name, h in humans.items():
        m = h.merge(judge, on="id")
        m = m[(m[name].str.strip() != "") & (m["judge"].str.strip() != "")]
        if m.empty:
            print(f"  {name:12s}  (no overlapping labelled ids)"); continue
        k = cohen_kappa_score(norm(m[name]), norm(m["judge"]))
        ks.append(k)
        print(f"  {name:12s}  κ = {k:.3f}   (n={len(m)})")
    if ks:
        print(f"\n  mean human–judge κ = {sum(ks)/len(ks):.3f}"
              f"   -> {'VALIDATED' if sum(ks)/len(ks) >= 0.6 else 'below 0.6'}")

    # inter-human (if >=2)
    if len(humans) >= 2:
        print("\n=== Cohen's κ: human vs human ===")
        for a, b in combinations(humans, 2):
            m = humans[a].merge(humans[b], on="id")
            m = m[(m[a].str.strip() != "") & (m[b].str.strip() != "")]
            if m.empty:
                continue
            k = cohen_kappa_score(norm(m[a]), norm(m[b]))
            print(f"  {a} ↔ {b}:  κ = {k:.3f}   (n={len(m)})")


if __name__ == "__main__":
    main()
