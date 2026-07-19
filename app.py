"""
Why2Speak — human κ-labelling interface.

Shows each labeller a model's chain-of-thought (the reasoning it produced *before*
choosing to speak) and asks: which kind of intervention does the reasoning CLAIM to
make? One of six labels. Blind to the GPT-5 judge's answers; autosaves per labeller.

Run locally:      streamlit run app.py
Deploy (free):    push this folder to GitHub -> share.streamlit.io -> pick app.py
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
HERE = Path(__file__).parent
DATA = HERE / "results" / "kappa_labelling_sheet.csv"
OUT_DIR = HERE / "kappa_results"
OUT_DIR.mkdir(exist_ok=True)

# label -> (short gloss, example cue). Order == the six radio options.
LABELS: dict[str, tuple[str, str]] = {
    "Factual Correction":    ("Fix a wrong claim someone made",
                              "“that’s actually false / it was 1969, not 1970…”"),
    "Concept Definition":    ("Define or clarify a term the group is misusing",
                              "“by <em>latency</em> they really mean…”"),
    "Data Provision":        ("Supply a number, statistic, or concrete fact the group lacks",
                              "“the boiling point is 100 °C…”"),
    "Source Identification": ("Point to, or demand, a source / citation / study",
                              "“that comes from the 2019 EPA report…”"),
    "Synthesis & Reframing": ("Step back, reconcile the sides, reframe a stuck discussion",
                              "“you’re both right — the real question is…”"),
    "None":                  ("No single clear type — vague, mixed, or off-taxonomy",
                              "reasoning that doesn’t commit to one kind"),
}
LABEL_KEYS = list(LABELS.keys())

st.set_page_config(page_title="Why2Speak — reasoning labelling",
                   page_icon="🗣️", layout="wide")

# --------------------------------------------------------------------------- #
# Styling
# --------------------------------------------------------------------------- #
st.markdown(
    """
    <style>
      .reason-card {
        background: rgba(130,150,255,.07);
        border: 1px solid rgba(130,150,255,.25);
        border-radius: 12px; padding: 1.1rem 1.3rem; line-height: 1.55;
        font-size: 1.02rem; max-height: 46vh; overflow-y: auto;
      }
      .pill { display:inline-block; padding:.12rem .6rem; border-radius:999px;
        background:rgba(130,150,255,.15); font-size:.8rem; margin-right:.4rem; }
      .rubric td { padding:.28rem .5rem; vertical-align:top; font-size:.86rem; }
      .rubric th { text-align:left; padding:.28rem .5rem; font-size:.82rem; opacity:.75; }
      .muted { opacity:.65; font-size:.85rem; }
      div[role="radiogroup"] label { margin-bottom:.15rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- #
# Data + persistence
# --------------------------------------------------------------------------- #
@st.cache_data
def load_items() -> pd.DataFrame:
    df = pd.read_csv(DATA, dtype={"id": str})
    return df[["id", "reasoning_text"]].reset_index(drop=True)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "anon"


def out_path(name: str) -> Path:
    return OUT_DIR / f"labels_{slug(name)}.csv"


# ---- optional central store: Google Sheet (append-only log, last-wins) ------ #
@st.cache_resource
def _worksheet():
    """Return a gspread worksheet if [gsheets] secrets are set, else None.

    Enables central save so multiple remote labellers write to one place (no
    download step). Falls back silently to local CSV when unconfigured.
    """
    try:
        if "gsheets" not in st.secrets:
            return None
        import gspread
        from google.oauth2.service_account import Credentials
        cfg = st.secrets["gsheets"]
        creds = Credentials.from_service_account_info(
            dict(cfg["service_account"]),
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        sh = gspread.authorize(creds).open_by_key(cfg["sheet_key"])
        ws = sh.sheet1
        if ws.row_count == 0 or not ws.get_all_values():
            ws.append_row(["labeller", "id", "your_label", "saved_utc"])
        return ws
    except Exception as e:  # never let a cloud hiccup block labelling
        st.session_state.setdefault("_gs_error", str(e))
        return None


def load_progress(name: str) -> dict[str, str]:
    ws = _worksheet()
    if ws is not None:
        recs = ws.get_all_records()  # list[dict]
        # last-wins: later rows override earlier for the same (labeller, id)
        out = {str(r["id"]): str(r["your_label"]) for r in recs
               if str(r.get("labeller", "")).strip().lower() == name.strip().lower()}
        return out
    p = out_path(name)
    if not p.exists():
        return {}
    # keep_default_na=False so the label "None" is read as the string "None",
    # not as a missing value (pandas treats bare None/NA/null as NaN by default).
    prev = pd.read_csv(p, dtype={"id": str}, keep_default_na=False)
    return dict(zip(prev["id"], prev["your_label"]))


def save_one(name: str, item_id: str, label: str) -> None:
    """Autosave one label. Central sheet if configured; always local CSV too."""
    st.session_state.labels[item_id] = label
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ws = _worksheet()
    if ws is not None:
        try:
            ws.append_row([name, str(item_id), label, ts])  # append-only log
        except Exception as e:
            st.warning(f"Central save failed (kept a local backup): {e}")
    # local backup / primary — full map, always consistent
    rows = [{"id": i, "your_label": l, "labeller": name, "saved_utc": ts}
            for i, l in st.session_state.labels.items()]
    pd.DataFrame(rows).to_csv(out_path(name), index=False)


# --------------------------------------------------------------------------- #
# Session bootstrap
# --------------------------------------------------------------------------- #
items = load_items()
N = len(items)

if "name" not in st.session_state:
    st.session_state.name = ""
if "idx" not in st.session_state:
    st.session_state.idx = 0
if "labels" not in st.session_state:
    st.session_state.labels = {}


# ---- Welcome / name gate -------------------------------------------------- #
if not st.session_state.name:
    st.title("🗣️ Why2Speak — label the reasoning")
    st.write(
        "You'll read a model's **chain of thought** — the reasoning it wrote *before* "
        "it decided to speak up in a group chat — and say **what kind of intervention "
        "the reasoning claims to make**. About **120 rows, ~30–45 min**. Your progress "
        "saves automatically and you can stop and resume anytime."
    )
    with st.form("who"):
        name = st.text_input("First name or nickname (used to save your labels)",
                             max_chars=40, placeholder="e.g. sam")
        go = st.form_submit_button("Start labelling →", type="primary")
    if go and name.strip():
        st.session_state.name = name.strip()
        st.session_state.labels = load_progress(name.strip())
        # jump to first unlabelled item
        done = st.session_state.labels
        first = next((k for k in range(N) if items.iloc[k]["id"] not in done), N - 1)
        st.session_state.idx = first
        st.rerun()
    st.info("Tip: everyone should use the **same** app so we can compare labels. "
            "Please don't discuss individual rows with the other labellers — the "
            "whole point is independent judgement.")
    st.stop()

name = st.session_state.name
labels = st.session_state.labels

# --------------------------------------------------------------------------- #
# Sidebar: rubric (always visible) + progress
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.markdown(f"**Labeller:** `{name}`")
    done = len(labels)
    st.progress(done / N, text=f"{done} / {N} labelled")

    st.markdown("### The six labels")
    rubric = "<table class='rubric'><tr><th>label</th><th>the reasoning wants to…</th></tr>"
    for k, (gloss, cue) in LABELS.items():
        rubric += (f"<tr><td><b>{k}</b></td><td>{gloss}<br>"
                   f"<span class='muted'><i>{cue}</i></span></td></tr>")
    rubric += "</table>"
    st.markdown(rubric, unsafe_allow_html=True)

    st.markdown("### Rules")
    st.markdown(
        "- Judge only what the text **claims**, not whether it's correct.\n"
        "- **One** label per row.\n"
        "- When torn between two, pick the one the reasoning **leads with**.\n"
        "- Blind: don't look at the model-judge's answers until everyone's done."
    )
    st.divider()
    if st.button("↪︎ Jump to next unlabelled"):
        nxt = next((k for k in range(N) if items.iloc[k]["id"] not in labels), None)
        if nxt is None:
            st.toast("All rows labelled 🎉")
        else:
            st.session_state.idx = nxt
            st.rerun()
    st.download_button(
        "⬇︎ Download my labels (backup)",
        data=(out_path(name).read_bytes() if out_path(name).exists() else b"id,your_label\n"),
        file_name=f"labels_{slug(name)}.csv",
        mime="text/csv",
        help="Send this file back if the app is hosted (its disk may reset).",
    )
    if st.button("Switch labeller"):
        st.session_state.name = ""
        st.rerun()

# --------------------------------------------------------------------------- #
# Main: one item
# --------------------------------------------------------------------------- #
idx = max(0, min(st.session_state.idx, N - 1))
row = items.iloc[idx]
item_id = row["id"]
current = labels.get(item_id)

top = st.columns([3, 1])
with top[0]:
    st.markdown(
        f"<span class='pill'>row {idx + 1} of {N}</span>"
        f"<span class='pill'>id {item_id}</span>"
        + ("<span class='pill'>✓ labelled</span>" if current else
           "<span class='pill'>· unlabelled</span>"),
        unsafe_allow_html=True,
    )
with top[1]:
    jump = st.number_input("go to row", 1, N, idx + 1, label_visibility="collapsed")
    if jump - 1 != idx:
        st.session_state.idx = int(jump - 1)
        st.rerun()

st.markdown("#### The model's reasoning")
st.markdown(f"<div class='reason-card'>{row['reasoning_text']}</div>",
            unsafe_allow_html=True)
st.caption("Some traces are cut off mid-thought — that's expected; judge what's shown.")

st.markdown("#### What kind of intervention does this reasoning claim to make?")
choice = st.radio(
    "label",
    LABEL_KEYS,
    index=LABEL_KEYS.index(current) if current in LABEL_KEYS else None,
    format_func=lambda k: f"{k} — {LABELS[k][0]}",
    label_visibility="collapsed",
)

nav = st.columns([1, 1, 4, 2])
with nav[0]:
    if st.button("← Back", disabled=idx == 0, use_container_width=True):
        st.session_state.idx = idx - 1
        st.rerun()
with nav[1]:
    if st.button("Skip →", disabled=idx >= N - 1, use_container_width=True):
        st.session_state.idx = idx + 1
        st.rerun()
with nav[3]:
    if st.button("Save & next →", type="primary", use_container_width=True,
                 disabled=choice is None):
        save_one(name, item_id, choice)
        st.session_state.idx = min(idx + 1, N - 1)
        st.rerun()

# completion banner
if len(labels) >= N:
    st.success(
        f"🎉 All {N} rows labelled. Click **Download my labels** in the sidebar and "
        f"send the file back — then we compute Cohen's κ against the model judge."
    )
