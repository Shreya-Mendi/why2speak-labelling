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

# Each label: emoji, one-line gloss, what it IS, an example, and the key "tell"
# that separates it from the neighbour it's most confused with.
LABELS: dict[str, dict[str, str]] = {
    "Factual Correction": {
        "emoji": "🍂",
        "gloss": "fix something wrong",
        "is": "Someone in the chat said something **incorrect**, and the reasoning "
              "wants to set it straight.",
        "eg": "“They said the moon landing was 1970 — it was actually 1969.”",
        "tell": "There must be an **existing wrong claim** being fixed. "
                "No mistake to correct? → it's not this.",
    },
    "Concept Definition": {
        "emoji": "📖",
        "gloss": "explain what a term means",
        "is": "The reasoning wants to **define or clarify a word, term, or concept** "
              "the group is unsure about or using loosely.",
        "eg": "“By *latency* they really mean the delay before a response starts.”",
        "tell": "It's about the **meaning of an idea/word** — not a number, and not "
                "correcting a mistake.",
    },
    "Data Provision": {
        "emoji": "🔢",
        "gloss": "add a missing number / fact",
        "is": "The group is **missing a specific fact, number, or statistic**, and "
              "the reasoning wants to supply it. **Nobody was wrong** — there's just a gap.",
        "eg": "“Water boils at 100 °C at sea level.” / “The population is about 8 million.”",
        "tell": "Use this **only when filling a gap**. If it's fixing a mistake → "
                "*Factual Correction*. If it's explaining a word → *Concept Definition*. "
                "If it's naming where the fact comes from → *Source Identification*.",
    },
    "Source Identification": {
        "emoji": "🔎",
        "gloss": "point to / ask for a source",
        "is": "The reasoning wants to **cite a source**, or **ask where a claim came "
              "from** — a study, report, link, or reference.",
        "eg": "“That figure is from the 2019 EPA report.” / “What's the source for that?”",
        "tell": "It's about **evidence / where information comes from**, not the fact itself.",
    },
    "Synthesis & Reframing": {
        "emoji": "🌉",
        "gloss": "reconcile / reframe the discussion",
        "is": "The reasoning **steps back** — reconciling opposing views, summarising, "
              "or **reframing** a stuck or circular discussion.",
        "eg": "“You're both right — the real question is whether…”",
        "tell": "It **combines or redirects** the conversation rather than adding one "
                "new fact.",
    },
    "None": {
        "emoji": "🌫️",
        "gloss": "none fit clearly",
        "is": "**No single type fits** — the reasoning is vague, mixed across several "
              "types, or about something outside these five.",
        "eg": "rambling or off-topic reasoning that doesn't commit to one kind.",
        "tell": "Pick this only after the other five genuinely don't fit.",
    },
}
LABEL_KEYS = list(LABELS.keys())

st.set_page_config(page_title="Why2Speak — reasoning labelling",
                   page_icon="🌿", layout="centered")

# --------------------------------------------------------------------------- #
# Ghibli-soft theming, with a day / night toggle
# --------------------------------------------------------------------------- #
PALETTES = {
    "day": dict(   # soft meadow morning
        bg="linear-gradient(180deg,#fcf9f0 0%,#eef5ef 55%,#e7f1f2 100%)",
        sidebar="#f6f1e2", text="#43413a", muted="#8b8676",
        card="#fffdf7", card_border="#e7dec7", accent="#6ba368",
        pill_bg="#e6efe2", pill_text="#4e7a4b", heading="#3c5a3a",
    ),
    "night": dict(  # Totoro dusk
        bg="linear-gradient(180deg,#1f2739 0%,#28304a 60%,#2d2c46 100%)",
        sidebar="#262d40", text="#ece6d8", muted="#a7a292",
        card="#2e3550", card_border="#3d4568", accent="#e0b866",
        pill_bg="#3a4265", pill_text="#e6d3a0", heading="#e9dcb6",
    ),
}


def inject_theme(mode: str) -> None:
    p = PALETTES[mode]
    st.markdown(
        f"""
        <style>
          .stApp {{ background: {p['bg']}; }}
          .stApp, [data-testid="stMarkdownContainer"], p, li, label, .stRadio {{
            color: {p['text']}; }}
          h1, h2, h3, h4 {{ color: {p['heading']} !important;
            font-family: 'Georgia','Iowan Old Style',serif; letter-spacing:.2px; }}
          section[data-testid="stSidebar"] > div {{ background: {p['sidebar']}; }}
          .reason-card {{
            background: {p['card']}; border: 1px solid {p['card_border']};
            border-radius: 18px; padding: 1.2rem 1.4rem; line-height: 1.65;
            font-size: 1.04rem; color: {p['text']};
            max-height: 42vh; overflow-y: auto;
            box-shadow: 0 4px 18px rgba(60,50,30,.08);
          }}
          .pill {{ display:inline-block; padding:.18rem .8rem; border-radius:999px;
            background:{p['pill_bg']}; color:{p['pill_text']}; font-size:.8rem;
            font-weight:600; margin-right:.45rem; }}
          .card {{ background:{p['card']}; border:1px solid {p['card_border']};
            border-radius:14px; padding:.7rem .9rem; margin-bottom:.5rem; }}
          .card b {{ color:{p['heading']}; }}
          .muted {{ color:{p['muted']}; font-size:.85rem; }}
          .rubric td {{ padding:.3rem .5rem; vertical-align:top; font-size:.85rem; }}
          .rubric th {{ text-align:left; padding:.3rem .5rem; font-size:.8rem;
            color:{p['muted']}; }}
          div[role="radiogroup"] label {{ margin-bottom:.35rem; font-size:1.02rem; }}
          div[role="radiogroup"] {{ gap:.2rem; }}
          .stButton button {{ border-radius:12px; }}
          .stButton button[kind="primary"] {{ box-shadow:0 3px 10px rgba(107,163,104,.35); }}
        </style>
        """,
        unsafe_allow_html=True,
    )


if "theme" not in st.session_state:
    st.session_state.theme = "day"
inject_theme(st.session_state.theme)


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
    st.title("🌿 Why2Speak — label the reasoning")
    st.write(
        "You'll read a little passage of **reasoning** — the thinking written *before* "
        "deciding whether to speak up in a group chat — and say **what kind of point "
        "it's trying to make**. About **120 short passages, ~30–45 min**. Your progress "
        "saves automatically, so you can stop and come back anytime. 🍵"
    )
    with st.form("who"):
        name = st.text_input("First name or nickname (just to save your progress)",
                             max_chars=40, placeholder="e.g. sam")
        go = st.form_submit_button("Start →", type="primary")
    if go and name.strip():
        st.session_state.name = name.strip()
        st.session_state.labels = load_progress(name.strip())
        # jump to first unlabelled item
        done = st.session_state.labels
        first = next((k for k in range(N) if items.iloc[k]["id"] not in done), N - 1)
        st.session_state.idx = first
        st.rerun()
    st.info("Please answer on your own — don't discuss individual rows with anyone "
            "else. Independent judgement is what makes this useful.")
    st.stop()

name = st.session_state.name
labels = st.session_state.labels

# --------------------------------------------------------------------------- #
# Sidebar: rubric (always visible) + progress
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.markdown(f"🧑‍🌾 **{name}**")
    night = st.toggle("🌙 Night mode", value=st.session_state.theme == "night")
    new_theme = "night" if night else "day"
    if new_theme != st.session_state.theme:
        st.session_state.theme = new_theme
        st.rerun()

    done = len(labels)
    st.progress(done / N, text=f"{done} / {N} done")

    st.markdown("### 🌸 The six labels")
    for k, d in LABELS.items():
        st.markdown(
            f"<div class='card'><b>{d['emoji']} {k}</b><br>"
            f"<span class='muted'>{d['gloss']}</span></div>",
            unsafe_allow_html=True,
        )
    st.caption("Full guide with examples is on the main page 👉")

    st.markdown("### How to choose")
    st.markdown(
        "- Judge only what the passage **claims**, not whether it's correct.\n"
        "- Pick **one** label per passage.\n"
        "- When torn between two, choose the one it **leads with**."
    )
    st.divider()
    if st.button("↪︎ Go to my next unlabelled row", use_container_width=True):
        nxt = next((k for k in range(N) if items.iloc[k]["id"] not in labels), None)
        if nxt is None:
            st.toast("All rows done 🎉")
        else:
            st.session_state.idx = nxt
            st.rerun()
    st.download_button(
        "⬇︎ Download my answers",
        data=(out_path(name).read_bytes() if out_path(name).exists() else b"id,your_label\n"),
        file_name=f"answers_{slug(name)}.csv",
        mime="text/csv",
        use_container_width=True,
        help="When you finish, download this and send it back.",
    )

# --------------------------------------------------------------------------- #
# Main: one item
# --------------------------------------------------------------------------- #
idx = max(0, min(st.session_state.idx, N - 1))
row = items.iloc[idx]
item_id = row["id"]
current = labels.get(item_id)

st.markdown(
    f"<span class='pill'>row {idx + 1} of {N}</span>"
    + ("<span class='pill'>✓ answered</span>" if current else
       "<span class='pill'>· not yet answered</span>"),
    unsafe_allow_html=True,
)

st.markdown("#### 🍃 The reasoning")
st.markdown(f"<div class='reason-card'>{row['reasoning_text']}</div>",
            unsafe_allow_html=True)
st.caption("Some passages cut off mid-thought — that's expected; just judge what's shown.")

st.markdown("#### What kind of point is this reasoning trying to make?")
choice = st.radio(
    "label",
    LABEL_KEYS,
    index=LABEL_KEYS.index(current) if current in LABEL_KEYS else None,
    format_func=lambda k: f"{LABELS[k]['emoji']}  {k} — {LABELS[k]['gloss']}",
    label_visibility="collapsed",
)

with st.expander("📖 Label guide — examples & how to tell them apart", expanded=False):
    st.markdown(
        "**Quick test when you're stuck** — go down this list and stop at the first *yes*:\n"
        "1. Is it **fixing a mistake** someone made? → 🍂 **Factual Correction**\n"
        "2. Is it **explaining what a word/idea means**? → 📖 **Concept Definition**\n"
        "3. Is it **adding a missing fact or number** (nobody was wrong)? → 🔢 **Data Provision**\n"
        "4. Is it about **where a fact comes from** (a source)? → 🔎 **Source Identification**\n"
        "5. Is it **tying the discussion together / reframing** it? → 🌉 **Synthesis & Reframing**\n"
        "6. None of these fit cleanly? → 🌫️ **None**"
    )
    st.info(
        "🔢 **Data Provision is the most over-used label.** Only pick it when the "
        "reasoning simply *supplies a missing fact* and **no one made a mistake**. "
        "If it's fixing an error → *Factual Correction*. If it's explaining a term → "
        "*Concept Definition*. If it's naming a source → *Source Identification*."
    )
    for k, d in LABELS.items():
        st.markdown(
            f"<div class='card'><b>{d['emoji']} {k}</b><br>{d['is']}<br>"
            f"<span class='muted'>e.g. {d['eg']}</span><br>"
            f"<span class='muted'>↳ {d['tell']}</span></div>",
            unsafe_allow_html=True,
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
        f"🎉 All {N} rows done — thank you so much! Click **⬇︎ Download my answers** "
        f"in the sidebar and send the file back. That's everything."
    )
