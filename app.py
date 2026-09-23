"""When2Speak Speak/Silent label audit: the labeller UI.

One question per trial: given only the conversation so far, should the assistant
speak now? The candidate utterance is deliberately NOT shown, so "was this a good
moment" is not confounded with "was the generated text any good", the confound
that made the round-1 preference data uninterpretable.

One click per trial. No confidence rating, no free text: item difficulty is
recovered behaviourally from disagreement, the repeated trials and time-on-item.

Identity is a typed nickname, and nicknames are unique: one that already has a
place is refused, so two people can never become one rater. A new nickname claims
the next free slot in audit_plans.json (people past the last slot get a copy of the
least-finished one) and an opaque resume token that goes in the URL, which is the
only way back. The nickname itself never goes in the URL.
Names starting "test" get a separate test slot (slot_01's plan) that
pull_labels.py leaves out.

Every answer is written to Postgres before the page advances, stamped with the
plan fingerprint. If a write fails the trial stays on screen with an error,
rather than quietly falling back to local disk, which Streamlit Cloud wipes on
every restart.

    study/.venv/bin/streamlit run study/app.py        # uses [db] from secrets.toml
    W2S_FORCE_LOCAL=1 ... streamlit run study/app.py    # test mode, local files, banner shown
    https://<app>/?admin=<admin_key>                    # per-slot progress
Deploy: RUNBOOK section 7.
"""
from __future__ import annotations

import html
import json
import os
import re
import time
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from audit_store import TEST_SLOT, LocalStore, PgStore, plan_fingerprint

HERE = Path(__file__).parent
ITEMS_PATH = HERE / "audit_items_public.json"
PLANS_PATH = HERE / "audit_plans.json"
LOCAL_DIR = Path(os.environ.get("W2S_LOCAL_DIR", HERE))

# Speaker dots, straight off the reference palette; the assistant is always ink.
PALETTE = ["#F37B75", "#6CC2EA", "#EA89B9", "#A0D4A6", "#F8C614", "#B9A3E3"]


# --------------------------------------------------------------------------- #
# data + storage
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner=False)
def load_data():
    items = {it["item_id"]: it for it in json.loads(ITEMS_PATH.read_text())["items"]}
    plans = json.loads(PLANS_PATH.read_text())
    return items, plans["design"], plans["slots"], plan_fingerprint(ITEMS_PATH, PLANS_PATH)


def secret(*path):
    try:
        node = st.secrets
        for p in path:
            node = node[p]
        return node
    except Exception:  # noqa: BLE001  (no secrets file, or key absent)
        return None


def db_url():
    if os.environ.get("W2S_FORCE_LOCAL"):
        return None
    return secret("db", "url") or secret("DATABASE_URL")


def get_store():
    """One store per browser session, so each person holds their own connection."""
    if "_store" not in st.session_state:
        url = db_url()
        st.session_state._store = PgStore(url) if url else LocalStore(LOCAL_DIR)
    return st.session_state._store


@st.cache_resource(show_spinner=False)
def schema_ready(kind: str, where: str) -> bool:
    """Once per server process. Raises (and so is not cached) if the DB is down."""
    (PgStore(where) if kind == "db" else LocalStore(Path(where))).ensure_schema()
    return True


def clean_name(raw: str) -> str:
    return re.sub(r"\s+", " ", raw or "").strip().lower()[:40]


def is_test(name: str) -> bool:
    return name.startswith("test")


# --------------------------------------------------------------------------- #
# look and feel: portfoliobyshruti.com
# #FAFAFA ground with a faint dot grid, Clash Display headings, Satoshi body,
# Caveat script, a yellow marker swash, stacked-paper cards, white-outlined
# stickers, beige pill tags, a huge faint counter numeral and a vertical edge tab.
# --------------------------------------------------------------------------- #
CSS = """
<style>
@import url('https://api.fontshare.com/v2/css?f[]=clash-display@400,500,600&f[]=satoshi@400,500,700&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Caveat:wght@500;600;700&display=swap');
:root {
  --bg:#FAFAFA; --paper:#FFFFFF; --ink:#1A1A1A; --warm:#4A4540; --muted:#8A8278;
  --beige:#F0EDE8; --cream:#FDF8F0;
  --coral:#F37B75; --coral-dk:#E4625C; --sky:#6CC2EA; --pink:#EA89B9; --mint:#A0D4A6; --sun:#F8C614;
  --tab:#9FD2D8;
  --line:rgba(26,26,26,.08);
  --soft:0 1px 2px rgba(26,26,26,.04), 0 18px 40px -18px rgba(74,69,64,.32);
  --sticker:0 0 0 1px rgba(26,26,26,.06), 0 10px 22px -8px rgba(74,69,64,.38);
  --display:'Clash Display', 'Satoshi', 'Helvetica Neue', Arial, sans-serif;
  --body:'Satoshi', 'Helvetica Neue', Helvetica, Arial, sans-serif;
  --script:'Caveat', 'Bradley Hand', cursive;
}
.stApp {
  background-color:var(--bg); color:var(--ink);
  background-image:radial-gradient(circle, rgba(26,26,26,.055) 1px, transparent 1.3px);
  background-size:26px 26px;
}
.stApp, .stApp p, .stApp li, .stApp label, .stApp input, .stApp button { font-family:var(--body); }
[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"],
[data-testid="stStatusWidget"], [data-testid="stSidebar"], [data-testid="collapsedControl"],
[data-testid="InputInstructions"], footer, #MainMenu { display:none !important; }
[data-testid="stMainBlockContainer"] { max-width:760px; padding:2.4rem 1.25rem 7rem; }

.display { font-family:var(--display); font-weight:500; font-size:clamp(2.6rem, 9vw, 4.2rem);
  line-height:1.06; letter-spacing:-.028em; color:var(--ink); margin:.15rem 0 .55rem; }
.center { text-align:center; }
.eyebrow { font:500 .74rem/1.6 var(--body); letter-spacing:.14em; text-transform:uppercase; color:var(--muted); }
.script { font-family:var(--script); font-size:1.65rem; font-weight:600; color:var(--coral-dk); }
.hl {
  background-image:
    linear-gradient(104deg, rgba(248,214,70,0) .9%, rgba(248,214,70,.78) 2.4%, rgba(248,214,70,.5) 5.8%,
                    rgba(248,214,70,.24) 93%, rgba(248,214,70,.72) 96%, rgba(248,214,70,0) 98%),
    linear-gradient(183deg, rgba(248,214,70,0) 0%, rgba(248,214,70,.3) 7.9%, rgba(248,214,70,0) 15%);
  padding:.04em .26em; margin:0 -.08em; border-radius:.5em .25em;
  -webkit-box-decoration-break:clone; box-decoration-break:clone;
}
.display .hl, .ask .hl { padding:.02em .12em; margin:0; }

.stack { position:relative; isolation:isolate; margin:.9rem .35rem 1.6rem; }
.stack::before, .stack::after { content:""; position:absolute; inset:0; border-radius:24px;
  border:1px solid var(--line); z-index:-1; }
.stack::before { background:var(--paper); transform:rotate(-1.3deg) translate(-3px, 7px); }
.stack::after  { background:var(--cream); transform:rotate(1deg) translate(5px, 12px); }
.card { position:relative; background:var(--paper); border:1px solid var(--line); border-radius:24px;
  box-shadow:var(--soft); padding:1.5rem 1.6rem; }
.card p { margin:0 0 .8rem; line-height:1.62; }
.card ul { margin:.1rem 0 .9rem 1.1rem; padding:0; }
.card li { margin:.4rem 0; line-height:1.55; }

.tag { display:inline-block; background:var(--beige); color:var(--muted); border-radius:28px;
  padding:.2rem .72rem; margin:.25rem .3rem 0 0; font:500 .64rem/1.5 var(--body);
  letter-spacing:.09em; text-transform:uppercase; }

.stickers { display:flex; justify-content:center; gap:1rem; margin:.2rem 0 .9rem; }
.sticker { display:grid; place-items:center; width:3.2rem; height:3.2rem; font-size:1.6rem;
  background:var(--paper); border-radius:50%; border:3px solid #fff; box-shadow:var(--sticker);
  transform:rotate(var(--r, 0deg)); transition:transform .25s cubic-bezier(.3,1.5,.5,1); }
.sticker:hover { transform:rotate(0deg) scale(1.15); }

.meter { display:flex; align-items:center; gap:.85rem; margin:0 0 .3rem; }
.meter .eyebrow { white-space:nowrap; }
.track { flex:1; height:8px; background:var(--beige); border-radius:99px; overflow:hidden; }
.fill { display:block; height:100%; border-radius:99px; background:linear-gradient(90deg, var(--coral), var(--pink)); }

.turn { margin:0 0 .95rem; }
.turn:last-child { margin-bottom:0; }
.who { display:flex; align-items:center; gap:.45rem; margin:0 0 .32rem .15rem;
  font:700 .66rem/1.2 var(--body); letter-spacing:.11em; text-transform:uppercase; color:var(--warm); }
.who .tag { margin:0 0 0 .2rem; font-size:.56rem; padding:.08rem .5rem; }
.dot { width:.64rem; height:.64rem; border-radius:50%; background:var(--c, var(--muted)); flex:none;
  box-shadow:0 0 0 2px #fff, 0 1px 3px rgba(0,0,0,.25); }
.said { background:var(--bg); border:1px solid var(--line); border-radius:6px 18px 18px 18px;
  padding:.66rem .92rem; font-size:.97rem; line-height:1.6; color:var(--ink); overflow-wrap:anywhere; }
.turn.bot .dot { --c:var(--ink); }
.turn.bot .said { background:var(--ink); border-color:var(--ink); color:var(--cream); }

.ask { font-family:var(--display); font-weight:500; font-size:clamp(1.6rem, 5.5vw, 2.2rem);
  letter-spacing:-.022em; text-align:center; margin:1.5rem 0 1.05rem; color:var(--ink); }

.stButton > button, .stFormSubmitButton > button {
  font-family:var(--body); font-weight:700; font-size:1.02rem; min-height:3.25rem;
  border-radius:999px; background:var(--paper); color:var(--ink);
  border:3px solid #fff; box-shadow:var(--sticker);
  transition:transform .2s cubic-bezier(.3,1.5,.5,1), box-shadow .2s ease, background .2s ease;
}
.stButton > button p, .stFormSubmitButton > button p { font:inherit; color:inherit; }
.stButton > button:hover, .stFormSubmitButton > button:hover {
  transform:translateY(-3px) rotate(-1.5deg) scale(1.03); color:var(--ink); border-color:#fff; }
.stButton > button:focus:not(:active), .stFormSubmitButton > button:focus:not(:active) {
  border-color:#fff; color:inherit; }
.stButton > button:active, .stFormSubmitButton > button:active {
  transform:scale(.98); background:var(--beige); color:var(--ink); border-color:#fff; }
[class*="st-key-speak_"] .stButton > button { background:var(--coral); color:#fff; }
[class*="st-key-speak_"] .stButton > button:hover,
[class*="st-key-speak_"] .stButton > button:active { background:var(--coral-dk); color:#fff; }
[class*="st-key-quiet_"] .stButton > button:hover { transform:translateY(-3px) rotate(1.5deg) scale(1.03); }
.st-key-go .stFormSubmitButton > button, .st-key-resume .stButton > button { background:var(--ink); color:#fff; }
.st-key-go .stFormSubmitButton > button:hover, .st-key-resume .stButton > button:hover,
.st-key-go .stFormSubmitButton > button:active, .st-key-resume .stButton > button:active {
  background:var(--warm); color:#fff; }
.st-key-undo { align-items:center; }
.st-key-undo .stButton > button { background:transparent; border:none; box-shadow:none; min-height:0;
  font-weight:500; font-size:.82rem; color:var(--muted); text-decoration:underline;
  text-underline-offset:3px; padding:.2rem .5rem; }
.st-key-undo .stButton > button:hover, .st-key-undo .stButton > button:active {
  transform:none; background:transparent; color:var(--ink); }

/* the two answers stay side by side on a phone */
.st-key-choices [data-testid="stHorizontalBlock"] { flex-wrap:nowrap !important; gap:.75rem !important; }
.st-key-choices [data-testid="stColumn"] { width:auto !important; min-width:0 !important; flex:1 1 0 !important; }

/* Streamlit 1.63 test ids (read off the live DOM): root box, then the field */
[data-testid="stTextInput"] label p { font:700 .68rem/1.2 var(--body); letter-spacing:.12em;
  text-transform:uppercase; color:var(--muted); }
[data-testid="stTextInputRootElement"] { border-radius:16px !important; border:1px solid var(--line) !important;
  background:var(--paper) !important; box-shadow:var(--soft); overflow:hidden; }
[data-testid="stTextInputField"] { font-size:1.02rem; padding:.8rem 1rem; background:transparent; }

.hint { text-align:center; color:var(--muted); font-size:.8rem; margin:.75rem 0 .1rem; }
.kbd { font:600 .72rem ui-monospace, SFMono-Regular, Menlo, monospace; background:var(--paper);
  border:1px solid var(--line); border-bottom-width:2px; border-radius:6px; padding:.05rem .38rem; color:var(--warm); }
@media (hover:none) { .hint.keys { display:none; } }
.note { border-radius:16px; padding:.7rem 1rem; font-size:.9rem; margin:.3rem 0 1rem; line-height:1.5;
  background:var(--cream); border:1px solid rgba(248,198,20,.5); color:var(--warm); }
.note.bad { background:#FFF2F1; border-color:rgba(243,123,117,.55); }

.bignum { position:fixed; right:1.4rem; bottom:.1rem; z-index:0; pointer-events:none;
  font-family:var(--display); font-weight:600; font-size:clamp(4.5rem, 13vw, 9.5rem);
  line-height:1; letter-spacing:-.04em; color:rgba(26,26,26,.075); }
.edge { position:fixed; right:0; top:34%; z-index:3; width:2.5rem; padding:.85rem 0 1.1rem;
  border-radius:12px 0 0 12px; background:var(--tab); box-shadow:-3px 6px 16px -6px rgba(74,69,64,.35);
  display:flex; flex-direction:column; align-items:center; gap:.9rem; pointer-events:none; }
.edge b { font:600 1rem/1 var(--display); color:#fff; }
.edge span { writing-mode:vertical-rl; transform:rotate(180deg); font:700 .6rem/1 var(--body);
  letter-spacing:.16em; text-transform:uppercase; color:#fff; }
@media (max-width: 900px) { .edge { display:none; } }   /* below this it would sit on the card */

@media (max-width: 700px) {
  [data-testid="stMainBlockContainer"] { padding:1.3rem 1rem 6rem; }
  .card { padding:1.15rem 1.1rem; border-radius:20px; }
  .stack::before, .stack::after { border-radius:20px; }
  .said { font-size:.95rem; }
}
</style>
"""

# Exactly one listener on the parent page, whichever iframe added it last. The
# debounce plus per-trial button keys mean a double press can never answer a
# trial the person has not seen.
KEYS = """
<script>
(function () {
  const w = window.parent, d = w.document;
  if (w.__w2sKeys) d.removeEventListener('keydown', w.__w2sKeys);
  w.__w2sKeys = function (e) {
    if (e.repeat || e.metaKey || e.ctrlKey || e.altKey) return;
    const t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
    const k = (e.key || '').toLowerCase();
    const sel = k === 's' ? '[class*="st-key-speak_"] button'
              : k === 'q' ? '[class*="st-key-quiet_"] button' : null;
    if (!sel) return;
    const now = Date.now();
    if (now - (w.__w2sLast || 0) < 800) return;
    const b = d.querySelector(sel);
    if (!b || b.disabled) return;
    w.__w2sLast = now;
    e.preventDefault();
    b.click();
  };
  d.addEventListener('keydown', w.__w2sKeys);
})();
</script>
"""


def md(s: str):
    st.markdown(s, unsafe_allow_html=True)


def chrome(count=None, part=None):
    bits = []
    if count is not None:
        bits.append(f'<div class="bignum">{count}</div>')
    if part:
        bits.append(f'<div class="edge"><b>w2s.</b><span>{part}</span></div>')
    if bits:
        md("".join(bits))


def safe(text: str) -> str:
    """Escape for an HTML block. No blank lines (they would end the block and hand
    the rest to the markdown parser) and no bare $ (Streamlit would try LaTeX)."""
    return html.escape(text).replace("\n", "<br>").replace("$", "&#36;")


def turn_html(t: dict) -> str:
    if t["speaker"] == "Assistant":
        return ('<div class="turn bot"><div class="who"><i class="dot"></i>Assistant'
                '<span class="tag">said earlier</span></div>'
                f'<div class="said">{safe(t["text"])}</div></div>')
    m = re.match(r"Speaker_(\d+)", t["speaker"])
    colour = PALETTE[int(m.group(1)) % len(PALETTE)] if m else "#8A8278"    # speakers count from 0
    return (f'<div class="turn"><div class="who"><i class="dot" style="--c:{colour}"></i>'
            f'{safe(t["speaker"].replace("_", " "))}</div>'
            f'<div class="said">{safe(t["text"])}</div></div>')


def duration(design: dict) -> str:
    lo, hi = design["est_minutes"]
    mid = (lo + hi) / 2
    return "about an hour" if 50 <= mid <= 70 else f"about {round(mid / 5) * 5} minutes"


def db_down(err: Exception):
    md('<div class="stack"><div class="card center">'
       '<div class="display" style="font-size:2rem">One sec.</div>'
       '<p>The database isn\'t answering. Nothing you did is lost. Refresh this page in a minute.</p>'
       '</div></div>')
    with st.expander("details"):
        st.code(str(err)[:500])
    st.stop()


# --------------------------------------------------------------------------- #
st.set_page_config(page_title="When2Speak", page_icon="💬", layout="centered",
                   initial_sidebar_state="collapsed")
md(CSS)
items, design, slots, PLAN_ID = load_data()
SLOT_IDS = sorted(slots)
store = get_store()
# Fail closed. With no database configured, answers would land on Streamlit
# Cloud's own disk, which is wiped on every restart. Only the local test-mode
# launcher (W2S_FORCE_LOCAL) may run without one.
if store.kind == "local" and not os.environ.get("W2S_FORCE_LOCAL"):
    md('<div class="stack"><div class="card center">'
       '<div class="display" style="font-size:2rem">Not <span class="hl">connected.</span></div>'
       "<p>This app has no database set up yet, so answers would be lost. "
       "Please don't start. Message Shreya instead.</p>"
       '<p style="color:var(--muted)">Shreya: paste the secrets under Settings, Secrets.</p>'
       "</div></div>")
    st.stop()
try:
    schema_ready(store.kind, db_url() or str(LOCAL_DIR))
except Exception as e:  # noqa: BLE001
    db_down(e)
qp = st.query_params

# ---- admin: per-slot progress ------------------------------------------------ #
if "admin" in qp:
    key = secret("admin_key")
    if not key or qp.get("admin") != str(key):
        md('<div class="note bad">Nothing here.</div>')
        st.stop()
    try:
        rows = store.progress()
    except Exception as e:  # noqa: BLE001
        db_down(e)
    per = design["trials_per_slot"]
    real = [r for r in rows if r["slot"] != TEST_SLOT]
    where = "saving to the shared database" if store.kind == "db" else "TEST MODE, local files only"
    md(f'<div class="display">Progress</div><div class="eyebrow">{where} · {len(real)} people signed in · '
       f'{sum(1 for r in real if r["done"] >= per)} finished · {sum(r["done"] for r in real)} answers · '
       f'{len({r["slot"] for r in real} & set(SLOT_IDS))} of {len(SLOT_IDS)} slots claimed · '
       f'test names excluded · plan {PLAN_ID}</div>')
    st.dataframe([{**r, "of": per} for r in rows], hide_index=True, width="stretch")
    st.stop()

# ---- who is this ------------------------------------------------------------ #
try:
    if "labeller" not in st.session_state and qp.get("k"):
        found = store.by_token(qp.get("k"))
        if found:
            st.session_state.labeller = found[0]
except Exception as e:  # noqa: BLE001
    db_down(e)

if "labeller" not in st.session_state:
    first_plan = slots[SLOT_IDS[0]]
    n_trials, n_parts = first_plan["n_trials"], len(first_plan["sittings"])
    dur = duration(design)

    chrome(count=n_trials)
    md('<div class="stickers">'
       '<span class="sticker" style="--r:-8deg">💬</span>'
       '<span class="sticker" style="--r:6deg">🤫</span>'
       '<span class="sticker" style="--r:-4deg">🙋</span>'
       '<span class="sticker" style="--r:9deg">☕</span></div>'
       '<div class="display center">When2<span class="hl">Speak.</span></div>'
       f'<div class="eyebrow center">a label audit · {n_trials} short chats · {dur} · {n_parts} parts</div>')
    md('<div class="stack"><div class="card">'
       "<p>You'll read short group chats. An AI assistant is in each one, listening. "
       "<b>Decide whether it should speak up at that exact moment, or stay quiet.</b></p>"
       "<ul>"
       "<li>Go with your gut. There's no right answer and no trick.</li>"
       "<li>You won't see what it would have said. "
       '<span class="hl">Judge the moment, not the wording.</span></li>'
       "<li>Dark bubbles are things the assistant already said earlier in that chat.</li>"
       f"<li>{n_trials} chats in {n_parts} parts, {dur} in all. Every click saves. Bookmark this page: "
       "the link in your address bar is how you come back.</li>"
       "<li>Please answer on your own, and don't compare notes on specific chats.</li>"
       "</ul>"
       '<span class="tag">one click each</span><span class="tag">saves as you go</span>'
       '<span class="tag">coming back? your link</span>'
       "</div></div>")
    if st.session_state.get("name_taken"):
        md(f'<div class="note"><b>{safe(st.session_state.name_taken)}</b> is taken, so pick a different '
           "nickname. If that one is yours and you lost your link, message Shreya and she will send it.</div>")
    with st.form("who", border=False):
        raw = st.text_input("Your nickname", max_chars=40, placeholder="a nickname you will remember")
        with st.container(key="go"):
            go = st.form_submit_button("Let's go", width="stretch")
    if go:
        name = clean_name(raw)
        if len(name) < 2:
            md('<div class="note bad">Type your name first, so your answers can be saved.</div>')
            st.stop()
        try:
            _, _, created = store.claim(name, [TEST_SLOT] if is_test(name) else SLOT_IDS)
        except Exception as e:  # noqa: BLE001
            db_down(e)
        st.session_state.pop("name_taken", None)
        if created:
            st.session_state.labeller = name
        else:
            st.session_state.name_taken = name     # nicknames are unique: no resume by name
        st.rerun()
    st.stop()

# ---- their plan ------------------------------------------------------------- #
labeller = st.session_state.labeller
try:
    mine = store.slot_of(labeller)
    done = store.done(labeller)
except Exception as e:  # noqa: BLE001
    db_down(e)
if not mine:
    del st.session_state["labeller"]
    st.rerun()
slot, token = mine
if slot != TEST_SLOT and slot not in slots:
    md('<div class="note bad">Your place belongs to an older version of this study. '
       "Please message Shreya before going on.</div>")
    st.stop()
if qp.get("k") != token:
    qp["k"] = token                     # resume link; opaque, never the name
plan = slots[SLOT_IDS[0]] if slot == TEST_SLOT else slots[slot]
seq = plan["sequence"]
n = len(seq)
bounds, acc = [], 0
for block in plan["sittings"][:-1]:
    acc += len(block)
    bounds.append(acc)
n_parts = len(bounds) + 1

redo = st.session_state.get("redo")
last = st.session_state.get("last_trial")
remaining = [i for i in range(n) if i not in done]

# ---- finished --------------------------------------------------------------- #
if redo is None and not remaining:
    chrome(count=n)
    md('<div class="stack"><div class="card center">'
       '<div class="display" style="font-size:clamp(2.2rem,7vw,3.2rem)">That\'s <span class="hl">everything.</span></div>'
       '<div class="script">thank you, truly</div>'
       f'<p style="color:var(--muted);margin-top:.8rem">{n} answers saved. You can close this tab.</p>'
       "</div></div>")
    if last is not None:
        with st.container(key="undo"):
            if st.button("Change my last answer", key="undo_btn"):
                st.session_state.redo = last
                st.rerun()
    st.stop()

trial_idx = redo if redo is not None else remaining[0]
part = 1 + sum(1 for b in bounds if b <= trial_idx)

# ---- break between sittings ------------------------------------------------- #
if redo is None and trial_idx in bounds and not st.session_state.get(f"past_{trial_idx}"):
    chrome(count=len(done), part=f"part {part - 1} done")
    md('<div class="stack"><div class="card center">'
       f'<div class="display" style="font-size:clamp(2.2rem,7vw,3.2rem)">Part {part - 1} <span class="hl">done.</span></div>'
       '<div class="script">stretch, grab a chai, your place is saved</div>'
       f'<p style="color:var(--muted);margin-top:.8rem">{len(done)} of {n} finished. '
       "Keep going now, or close the tab and come back later with this same link.</p>"
       "</div></div>")
    with st.container(key="resume"):
        if st.button("Keep going", width="stretch"):
            st.session_state[f"past_{trial_idx}"] = True
            st.rerun()
    st.stop()

# ---- the trial -------------------------------------------------------------- #
trial = seq[trial_idx]
item = items[trial.removesuffix("#r")]
shown_key = (labeller, trial_idx, redo is not None)
if st.session_state.get("shown_key") != shown_key:     # time from first render, not last click
    st.session_state.shown_key = shown_key
    st.session_state.shown_at = time.time()

chrome(count=len(done), part=f"part {part} of {n_parts}")
md(f'<div class="meter"><span class="eyebrow">part {part} of {n_parts} · {len(done)} of {n}</span>'
   f'<span class="track"><i class="fill" style="width:{len(done) / n * 100:.1f}%"></i></span></div>')
if store.kind == "local":
    md('<div class="note">Test mode: no database connected, answers stay on this computer.</div>')
if slot == TEST_SLOT:
    md('<div class="note">Test name: these answers are kept out of the analysis.</div>')
if redo is not None:
    md('<div class="note">Changing your answer to the chat you just did.</div>')
if st.session_state.get("save_error"):
    md('<div class="note bad">That one didn\'t save, the database didn\'t answer. '
       "Nothing is lost. Click your answer again.</div>")

md('<div class="stack"><div class="card">' + "".join(turn_html(t) for t in item["turns"]) + "</div></div>")
md('<div class="ask">Should it <span class="hl">speak now?</span></div>')


def record(label: str):
    row = {
        "labeller": labeller, "slot": slot, "trial_idx": trial_idx, "item_id": item["item_id"],
        "is_repeat": trial.endswith("#r"), "label": label, "revised": redo is not None,
        "ms_on_item": int((time.time() - st.session_state.shown_at) * 1000),
        "plan_id": PLAN_ID,
    }
    try:
        store.save(row)
    except Exception as e:  # noqa: BLE001  stay on this trial, never advance unsaved
        st.session_state.save_error = str(e)
        st.rerun()
    st.session_state.pop("save_error", None)
    st.session_state.last_trial = trial_idx
    st.session_state.redo = None
    st.rerun()


tag = f"{trial_idx}{'r' if redo is not None else ''}"
with st.container(key="choices"):
    left, right = st.columns(2, gap="small")
    with left, st.container(key=f"speak_{tag}"):
        if st.button("Speak up", key=f"b_speak_{tag}", width="stretch"):
            record("SPEAK")
    with right, st.container(key=f"quiet_{tag}"):
        if st.button("Stay quiet", key=f"b_quiet_{tag}", width="stretch"):
            record("SILENT")

md('<div class="hint keys">or press <span class="kbd">S</span> to speak up, '
   '<span class="kbd">Q</span> to stay quiet</div>')
with st.container(key="undo"):
    if redo is not None:
        if st.button("Never mind, keep my answer", key="cancel_redo"):
            st.session_state.redo = None
            st.rerun()
    elif last is not None:
        if st.button("Change my last answer", key="undo_btn"):
            st.session_state.redo = last
            st.rerun()
components.html(KEYS, height=0)
