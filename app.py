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

# Each label: emoji, one-line gloss, what it IS, several examples, and the key
# "tell" that separates it from the neighbour it's most confused with.
LABELS: dict[str, dict] = {
    "Factual Correction": {
        "emoji": "🍂",
        "gloss": "fix something wrong",
        "is": "Someone in the chat said something **incorrect**, and the reasoning "
              "wants to set it straight.",
        "egs": [
            "“They said the moon landing was 1970 — it was actually 1969.”",
            "“That's not right: the capital of Australia is Canberra, not Sydney.”",
            "“Speaker_1 thinks water freezes at 10°C, but it's 0°C.”",
        ],
        "tell": "There must be an **existing wrong claim** being fixed. "
                "No mistake to correct → it's not this.",
    },
    "Concept Definition": {
        "emoji": "📖",
        "gloss": "explain what a term means",
        "is": "The reasoning wants to **define or clarify a word, term, or concept** "
              "the group is unsure about or using loosely.",
        "egs": [
            "“By *latency* they really mean the delay before a response starts.”",
            "“When they say ‘inflation’ they mean the price level, not the rate.”",
            "“Let me clarify — a *byte* is 8 bits.”",
        ],
        "tell": "It's about the **meaning of a word or idea** — not a number, and not "
                "correcting a mistake.",
    },
    "Data Provision": {
        "emoji": "🔢",
        "gloss": "add a missing number / fact",
        "is": "The group is **missing a specific fact, number, or statistic**, and "
              "the reasoning wants to supply it. **Nobody was wrong** — there's just a gap.",
        "egs": [
            "“Water boils at 100°C at sea level.”",
            "“The population of Canada is about 40 million.”",
            "“A marathon is 42.2 km.”",
        ],
        "tell": "Only when **filling a gap**. Fixing a mistake → *Factual Correction*. "
                "Explaining a word → *Concept Definition*. Naming where the fact comes "
                "from → *Source Identification*.",
    },
    "Source Identification": {
        "emoji": "🔎",
        "gloss": "point to / ask for a source",
        "is": "The reasoning wants to **cite a source**, or **ask where a claim came "
              "from** — a study, report, link, or reference.",
        "egs": [
            "“That figure is from the 2019 EPA report.”",
            "“What's the source for that statistic?”",
            "“There's a 2021 Nature study that measured exactly this.”",
        ],
        "tell": "It's about **where information comes from / evidence**, not the fact itself.",
    },
    "Synthesis & Reframing": {
        "emoji": "🌉",
        "gloss": "reconcile / reframe the discussion",
        "is": "The reasoning **steps back** — reconciling opposing views, summarising, "
              "or **reframing** a stuck or circular discussion.",
        "egs": [
            "“You're both right — the real question is whether it scales.”",
            "“Let me tie these two points together…”",
            "“Stepping back, the disagreement is really about definitions.”",
        ],
        "tell": "It **combines or redirects** the conversation rather than adding one "
                "new fact.",
    },
    "None": {
        "emoji": "🌫️",
        "gloss": "none fit clearly",
        "is": "**No single type fits** — the reasoning is vague, mixed across several "
              "types, or about something outside these five.",
        "egs": [
            "Rambling reasoning that never commits to one kind.",
            "Reasoning that mixes correcting AND defining AND providing data.",
            "Off-topic musing that doesn't fit the five categories.",
        ],
        "tell": "Pick this only after the other five genuinely don't fit.",
    },
}
LABEL_KEYS = list(LABELS.keys())

st.set_page_config(page_title="Why2Speak — reasoning labelling",
                   page_icon="🌿", layout="wide")

# --------------------------------------------------------------------------- #
# Ghibli-soft theming, with a day / night toggle
# --------------------------------------------------------------------------- #
# Palette + type from portfoliobyshruti.com: off-white, near-black ink, coral
# accent, warm neutrals; Satoshi / Clash Display / Caveat.
PALETTES = {
    "day": dict(
        bg="#fafafa", sidebar="#f0ede8", text="#1a1a1a", muted="#8a8278",
        card="#ffffff", card_border="#ece7de", accent="#f37b75",
        pill_bg="#fff2f0", pill_text="#d8635c", heading="#1a1a1a",
    ),
    "night": dict(
        bg="#1c1a18", sidebar="#232019", text="#f2ede4", muted="#a79f92",
        card="#26221d", card_border="#37312a", accent="#f37b75",
        pill_bg="#3a2b28", pill_text="#f0a49e", heading="#fff8ee",
    ),
}

# the site's playful "sticker" palette — one hue per label (also a visual aid)
LABEL_COLORS = {
    "Factual Correction":    "#f37b75",  # coral
    "Concept Definition":    "#6cc2ea",  # sky
    "Data Provision":        "#f8c614",  # yellow
    "Source Identification": "#a0d4a6",  # sage
    "Synthesis & Reframing": "#b79ce0",  # lilac
    "None":                  "#c3bbae",  # warm grey
}


def inject_theme(mode: str) -> None:
    p = PALETTES[mode]
    st.markdown(
        f"""
        <style>
          @import url('https://api.fontshare.com/v2/css?f[]=satoshi@400,500,700&f[]=clash-display@500,600&display=swap');
          @import url('https://fonts.googleapis.com/css2?family=Caveat:wght@600&display=swap');
          html, body, .stApp, [class^="st-"], [class*=" st-"],
          button, input, textarea, select, [data-testid="stMarkdownContainer"] {{
            font-family: 'Satoshi','Helvetica Neue',sans-serif !important; }}
          html {{ font-size: 17px; }}
          [data-testid="stIconMaterial"],
          span[class*="material-symbols"] {{
            font-family: 'Material Symbols Rounded' !important; }}
          [data-testid="stMarkdownContainer"] p,
          [data-testid="stMarkdownContainer"] li {{ line-height: 1.65; }}
          h1, h2, h3, h4 {{ font-family:'Clash Display','Satoshi',sans-serif !important;
            color: {p['heading']} !important; letter-spacing:.01em;
            margin-top:.6rem !important; }}
          .stApp {{ background: {p['bg']}; }}
          .stApp, [data-testid="stMarkdownContainer"], p, li, label, .stRadio {{
            color: {p['text']}; }}
          .block-container {{ padding-top: 2.2rem; max-width: 1250px; }}
          section[data-testid="stSidebar"] > div {{ background: {p['sidebar']}; }}
          .guide-title {{ font-family:'Caveat',cursive; font-weight:600;
            font-size:1.5rem; color:{p['accent']}; }}
          details.lbl {{ background:{p['card']}; border:1px solid {p['card_border']};
            border-left:4px solid var(--lc,{p['card_border']});
            border-radius:12px; padding:.75rem 1rem; margin-bottom:.65rem; }}
          details.lbl summary {{ cursor:pointer; font-weight:600; list-style:none;
            color:{p['heading']}; line-height:1.5; }}
          details.lbl summary::-webkit-details-marker {{ display:none; }}
          details.lbl[open] summary {{ margin-bottom:.55rem; }}
          details.lbl ul {{ margin:.4rem 0 .35rem 1.1rem; padding:0; }}
          details.lbl li {{ margin:.3rem 0; font-size:.92rem; line-height:1.55; }}
          details.lbl .muted {{ line-height:1.55; }}
          .reason-card {{
            background: {p['card']}; border: 1px solid {p['card_border']};
            border-radius: 18px; padding: 1.4rem 1.6rem; line-height: 1.75;
            font-size: 1.05rem; color: {p['text']};
            max-width: 72ch;
            box-shadow: 0 4px 18px rgba(60,50,30,.08);
          }}
          .reason-card p {{ margin: 0 0 .85rem 0; }}
          .reason-card p:last-child {{ margin-bottom: 0; }}
          .lead-tip {{ background:{p['pill_bg']}; color:{p['pill_text']};
            border-radius:10px; padding:.5rem .8rem; font-size:.88rem;
            margin:.4rem 0 .2rem 0; }}
          .pill {{ display:inline-block; padding:.18rem .8rem; border-radius:999px;
            background:{p['pill_bg']}; color:{p['pill_text']}; font-size:.8rem;
            font-weight:600; margin-right:.45rem; }}
          .card {{ background:{p['card']}; border:1px solid {p['card_border']};
            border-radius:14px; padding:.7rem .9rem; margin-bottom:.5rem; }}
          .card b {{ color:{p['heading']}; }}
          .muted {{ color:{p['muted']}; font-size:.88rem; }}
          .rubric td {{ padding:.3rem .5rem; vertical-align:top; font-size:.85rem; }}
          .rubric th {{ text-align:left; padding:.3rem .5rem; font-size:.8rem;
            color:{p['muted']}; }}
          div[role="radiogroup"] label {{ margin-bottom:.55rem; font-size:1.03rem;
            line-height:1.5; }}
          div[role="radiogroup"] {{ gap:.35rem; }}
          .stButton button, .stDownloadButton button {{ border-radius:12px;
            background:{p['card']} !important; color:{p['text']} !important;
            border:1px solid {p['card_border']} !important; font-weight:600; }}
          .stButton button:hover, .stDownloadButton button:hover {{
            border-color:{p['accent']} !important; color:{p['accent']} !important; }}
          .stButton button[kind="primary"] {{ background:{p['accent']} !important;
            color:#fff !important; border:none !important;
            box-shadow:0 3px 12px rgba(243,123,117,.4); }}
          .stButton button[kind="primary"]:hover {{ color:#fff !important; }}
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


# ---- central store #1: Postgres (Vercel/Neon) — survives redeploys --------- #
def _db_url() -> str | None:
    try:
        if "db" in st.secrets and st.secrets["db"].get("url"):
            return st.secrets["db"]["url"]
        if "DATABASE_URL" in st.secrets:
            return st.secrets["DATABASE_URL"]
    except Exception:
        pass
    return None


def _db_conn():
    """Fresh short-lived connection per operation (plays nice with serverless
    Postgres that suspends between uses). Returns None if unconfigured/down."""
    url = _db_url()
    if not url:
        return None
    try:
        import psycopg2
        conn = psycopg2.connect(url, connect_timeout=8)
        conn.autocommit = True
        return conn
    except Exception as e:
        st.session_state.setdefault("_db_error", str(e))
        return None


@st.cache_resource
def _db_ready() -> bool:
    """Create the labels table once per app process; cache the outcome."""
    conn = _db_conn()
    if conn is None:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS labels (
                       labeller  TEXT NOT NULL,
                       item_id   TEXT NOT NULL,
                       label     TEXT NOT NULL,
                       saved_utc TIMESTAMPTZ NOT NULL DEFAULT now(),
                       PRIMARY KEY (labeller, item_id)
                   )"""
            )
        return True
    except Exception as e:
        st.session_state.setdefault("_db_error", str(e))
        return False
    finally:
        conn.close()


def _db_load(name: str) -> dict[str, str] | None:
    if not _db_ready():
        return None
    conn = _db_conn()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT item_id, label FROM labels WHERE labeller = %s",
                        (slug(name),))
            return {str(i): str(l) for i, l in cur.fetchall()}
    except Exception as e:
        st.session_state.setdefault("_db_error", str(e))
        return None
    finally:
        conn.close()


def _db_save(name: str, item_id: str, label: str) -> bool:
    if not _db_ready():
        return False
    conn = _db_conn()
    if conn is None:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO labels (labeller, item_id, label, saved_utc)
                   VALUES (%s, %s, %s, now())
                   ON CONFLICT (labeller, item_id)
                   DO UPDATE SET label = EXCLUDED.label, saved_utc = now()""",
                (slug(name), str(item_id), label),
            )
        return True
    except Exception as e:
        st.session_state.setdefault("_db_error", str(e))
        return False
    finally:
        conn.close()


# ---- central store #2 (legacy): Google Sheet (append-only log, last-wins) --- #
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


def storage_mode() -> str:
    """'db' | 'gsheets' | 'local' — which store is live right now."""
    if _db_ready():
        return "db"
    if _worksheet() is not None:
        return "gsheets"
    return "local"


def load_progress(name: str) -> dict[str, str]:
    got = _db_load(name)
    if got is not None:
        return got
    ws = _worksheet()
    if ws is not None:
        recs = ws.get_all_records()  # list[dict]
        # last-wins: later rows override earlier for the same (labeller, id)
        return {str(r["id"]): str(r["your_label"]) for r in recs
                if str(r.get("labeller", "")).strip().lower() == name.strip().lower()}
    p = out_path(name)
    if not p.exists():
        return {}
    # keep_default_na=False so the label "None" is read as the string "None",
    # not as a missing value (pandas treats bare None/NA/null as NaN by default).
    prev = pd.read_csv(p, dtype={"id": str}, keep_default_na=False)
    return dict(zip(prev["id"], prev["your_label"]))


def save_one(name: str, item_id: str, label: str) -> None:
    """Autosave one label. Postgres first, sheet as legacy fallback; a local
    CSV is always written too (backup + the sidebar download button)."""
    st.session_state.labels[item_id] = label
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if not _db_save(name, item_id, label):
        ws = _worksheet()
        if ws is not None:
            try:
                ws.append_row([name, str(item_id), label, ts])  # append-only log
            except Exception as e:
                st.warning(f"Central save failed (kept a local backup): {e}")
    # local backup — full map, always consistent
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
    _mode = storage_mode()
    if _mode == "db":
        st.caption("☁️ Progress saves to the shared database — safe to close anytime.")
    elif _mode == "gsheets":
        st.caption("📄 Progress saves to the shared sheet — safe to close anytime.")
    else:
        st.caption("⚠️ Saving locally only — please Download your answers when you "
                   "stop, or progress may be lost.")

    st.markdown("### How to choose")
    st.markdown(
        "- Judge only what the passage **claims**, not whether it's correct.\n"
        "- Pick **one** label per passage.\n"
        "- When torn between two, choose the one it **leads with**.\n"
        "- The **guide on the left** has examples — tap any label to expand it."
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

guide_col, task_col = st.columns([1, 1.35], gap="large")

# ---- left: always-visible rubric; tap a label for multiple examples --------- #
def rich(s: str) -> str:
    """markdown **bold** / *italic* -> HTML (raw HTML blocks don't get markdown)."""
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"\*(.+?)\*", r"<i>\1</i>", s)
    return s


def paragraphize(text: str, per_para: int = 3) -> str:
    """Break a wall-of-text reasoning trace into small paragraphs for readability.
    Pure formatting: sentence order and content untouched (no bias to labels)."""
    sents = re.split(r"(?<=[.!?])\s+", text.strip())
    paras = [" ".join(sents[i:i + per_para]) for i in range(0, len(sents), per_para)]
    return "".join(f"<p>{p}</p>" for p in paras if p)


with guide_col:
    st.markdown("<div class='guide-title'>📖 Label guide — tap one for examples</div>",
                unsafe_allow_html=True)
    for k, d in LABELS.items():
        egs = "".join(f"<li>{e}</li>" for e in d["egs"])
        lc = LABEL_COLORS[k]
        st.markdown(
            f"<details class='lbl' style='--lc:{lc}'>"
            f"<summary>{d['emoji']} {k} <span style='color:{lc};font-weight:600'>—"
            f" {d['gloss']}</span></summary>"
            f"<div class='muted'>{rich(d['is'])}</div>"
            f"<div style='margin-top:.35rem;font-size:.82rem;opacity:.75'>Examples:</div>"
            f"<ul>{egs}</ul>"
            f"<div class='muted'>↳ {rich(d['tell'])}</div></details>",
            unsafe_allow_html=True,
        )
    st.markdown(
        "<div class='card'>🔢 <b>Heads-up:</b> <span class='muted'>Data Provision is "
        "the most over-picked label. Use it only when a fact is simply <i>missing</i> "
        "and no one was wrong.</span></div>",
        unsafe_allow_html=True,
    )

# ---- right: the passage + the choice ---------------------------------------- #
with task_col:
    st.markdown(
        f"<span class='pill'>row {idx + 1} of {N}</span>"
        + ("<span class='pill'>✓ answered</span>" if current else
           "<span class='pill'>· not yet answered</span>"),
        unsafe_allow_html=True,
    )
    st.markdown("#### 🍃 The reasoning")
    st.markdown(
        "<div class='lead-tip'>💡 Long one? You usually don't need every word — "
        "the label is what the reasoning <b>leads with</b>, and that's typically "
        "clear within the first few sentences.</div>",
        unsafe_allow_html=True,
    )
    st.markdown(f"<div class='reason-card'>{paragraphize(row['reasoning_text'])}</div>",
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
