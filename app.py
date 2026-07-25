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


# --------------------------------------------------------------------------- #
# The growing scene — a tiny diorama in the corner that gains one element every
# five labels. Ten stages, then it quietly starts over with a fresh rug.
# Pure inline SVG (+ SMIL <animate>): no JS, no assets, no network.
# --------------------------------------------------------------------------- #
SCENE_EVERY = 5          # labels per stage
SCENE_STAGES = 10        # stages before the cycle repeats

SCENE_TOASTS = {
    1:  "🪞 a rug unrolls",
    2:  "🪵 a little table arrives",
    3:  "🏺 someone sets down a vase",
    4:  "🌱 buds, tucked in",
    5:  "💧 a drink for the flowers",
    6:  "🌸 they bloom!",
    7:  "🐈 a cat wanders in",
    8:  "🐾 the cat gets playful",
    9:  "😿 uh oh — the vase!",
    10: "🐈‍⬛ the cat bolts",
}

# unit vectors for five petals, starting at 12 o'clock
_PETALS = ((0.0, -1.0), (0.951, -0.309), (0.588, 0.809),
           (-0.588, 0.809), (-0.951, -0.309))
_FUR, _PAW, _INK = "#c3bbae", "#dad4cb", "#4a4038"
_WOOD, _WOOD_DK = "#d3b28c", "#bd9866"
_STEM = "#7fbf87"


def scene_stage(done: int) -> int:
    """0 = nothing yet, else 1..10 cycling. k = done // 5; ((k - 1) % 10) + 1."""
    k = done // SCENE_EVERY
    return 0 if k == 0 else ((k - 1) % SCENE_STAGES) + 1


def _flower(cx: float, cy: float, col: str, r: float = 5.6) -> str:
    """An open bloom: five petals around a yellow centre."""
    petals = "".join(
        f"<circle cx='{cx + dx * r * .62:.1f}' cy='{cy + dy * r * .62:.1f}'"
        f" r='{r * .46:.1f}' fill='{col}'/>" for dx, dy in _PETALS
    )
    return petals + f"<circle cx='{cx:.1f}' cy='{cy:.1f}' r='{r * .3:.1f}' fill='#f8c614'/>"


def _bud(cx: float, cy: float) -> str:
    """A closed bud (teardrop) sitting on a stem tip."""
    return (f"<path d='M{cx:.1f} {cy:.1f} C{cx - 3.4:.1f} {cy - .6:.1f}"
            f" {cx - 3.8:.1f} {cy - 6.6:.1f} {cx:.1f} {cy - 10:.1f}"
            f" C{cx + 3.8:.1f} {cy - 6.6:.1f} {cx + 3.4:.1f} {cy - .6:.1f}"
            f" {cx:.1f} {cy:.1f} Z' fill='#a0d4a6'/>"
            f"<path d='M{cx:.1f} {cy - 9.2:.1f} L{cx:.1f} {cy - 1.4:.1f}'"
            f" stroke='{_STEM}' stroke-width='.8' opacity='.65'/>")


def _watering_can(transform: str, pouring: bool) -> str:
    """The can, drawn once in its own coords and placed by `transform`."""
    tilt = "<g transform='rotate(-20 119 42)'>" if pouring else "<g>"
    return (
        f"<g {transform}>{tilt}"
        f"<path d='M116 32 C116 25 130 25 130 32' stroke='#8bc492' stroke-width='2.6'"
        f" fill='none' stroke-linecap='round'/>"
        f"<path d='M110 41 L100 47 L102.6 51.4 L112 46 Z' fill='#8bc492'/>"
        f"<ellipse cx='100.5' cy='48.6' rx='3.1' ry='2.3' fill='#a0d4a6'"
        f" transform='rotate(-32 100.5 48.6)'/>"
        f"<path d='M111 33 h17 a3 3 0 0 1 3 3 v11 a5.5 5.5 0 0 1 -5.5 5.5"
        f" h-12 a5.5 5.5 0 0 1 -5.5 -5.5 v-11 a3 3 0 0 1 3 -3 Z' fill='#a0d4a6'/>"
        f"<rect x='111' y='36.6' width='20' height='2.4' fill='#8bc492' opacity='.75'/>"
        f"</g></g>"
    )


def _droplets() -> str:
    """Three staggered droplets falling from the spout onto the buds."""
    out = ["<g fill='#6cc2ea'>"]
    for i, (x0, dur) in enumerate(((97.5, 1.15), (101.0, 1.3), (99.0, 1.05))):
        beg = f"{i * .38:.2f}s"
        out.append(
            f"<ellipse cx='{x0}' cy='55' rx='1.7' ry='2.5'>"
            f"<animate attributeName='cy' values='55;74' dur='{dur}s'"
            f" begin='{beg}' repeatCount='indefinite'/>"
            f"<animate attributeName='cx' values='{x0};{x0 - 3.5}' dur='{dur}s'"
            f" begin='{beg}' repeatCount='indefinite'/>"
            f"<animate attributeName='opacity' values='0;1;1;0' keyTimes='0;.18;.72;1'"
            f" dur='{dur}s' begin='{beg}' repeatCount='indefinite'/></ellipse>"
        )
    out.append("</g>")
    return "".join(out)


def _cat(anxious: bool = False, playing: bool = False) -> str:
    """A sitting cat, facing the table. `anxious` = wide eyes + ears back."""
    parts = []

    # tail (flicks when playing)
    tail = (f"<path d='M144 125.5 C154.5 127.5 159 118 153 111.5' stroke='{_FUR}'"
            f" stroke-width='4.6' fill='none' stroke-linecap='round'/>")
    if playing:
        parts.append(
            f"<g>{tail}<animateTransform attributeName='transform' type='rotate'"
            f" values='0 145 125;11 145 125;-8 145 125;0 145 125' dur='1.9s'"
            f" repeatCount='indefinite'/></g>")
    else:
        parts.append(tail)

    # ears — flattened back when anxious
    ear_l = f"<path d='M129.6 96 L127.2 87.2 L136 92.6 Z' fill='{_FUR}'/>"
    ear_r = f"<path d='M143.4 96 L145.8 87.2 L137 92.6 Z' fill='{_FUR}'/>"
    in_l = "<path d='M130.6 94.6 L129.6 89.9 L134.4 92.8 Z' fill='#f37b75' opacity='.45'/>"
    in_r = "<path d='M142.4 94.6 L143.4 89.9 L138.6 92.8 Z' fill='#f37b75' opacity='.45'/>"
    if anxious:
        parts.append(f"<g transform='rotate(52 130.5 95.5)'>{ear_l}{in_l}</g>"
                     f"<g transform='rotate(-52 142.5 95.5)'>{ear_r}{in_r}</g>")
    else:
        parts.append(ear_l + in_l + ear_r + in_r)

    # body + head
    parts.append(
        f"<path d='M133 127 C125.2 127 124.8 115.6 129.4 108.6 C132.6 104 141 104"
        f" 144.2 108.6 C148.8 115.6 148.4 127 140.6 127 Z' fill='{_FUR}'/>"
        f"<circle cx='136.5' cy='102' r='8.8' fill='{_FUR}'/>")

    # front paws (one lifts when playing)
    parts.append(f"<ellipse cx='139.6' cy='125.4' rx='3.6' ry='2.3' fill='{_PAW}'/>")
    if playing:
        parts.append(
            f"<g><animateTransform attributeName='transform' type='rotate'"
            f" values='0 130.5 123;-26 130.5 123;-5 130.5 123;0 130.5 123'"
            f" keyTimes='0;.35;.7;1' dur='1.5s' repeatCount='indefinite'/>"
            f"<path d='M130.5 123.5 C126.6 119.6 123 115 120.8 110.6' stroke='{_FUR}'"
            f" stroke-width='4.4' fill='none' stroke-linecap='round'/>"
            f"<ellipse cx='119.8' cy='108.8' rx='3.4' ry='2.6' fill='{_PAW}'"
            f" transform='rotate(-34 119.8 108.8)'/></g>")
    else:
        parts.append(f"<ellipse cx='132.2' cy='125.4' rx='3.6' ry='2.3' fill='{_PAW}'/>")

    # face
    parts.append(
        f"<path d='M128.4 103.4 L121.8 101.8 M128.4 105.6 L122.2 106.8' stroke='{_INK}'"
        f" stroke-width='.7' opacity='.5' stroke-linecap='round' fill='none'/>"
        f"<path d='M144.6 103.4 L151.2 101.8 M144.6 105.6 L150.8 106.8' stroke='{_INK}'"
        f" stroke-width='.7' opacity='.5' stroke-linecap='round' fill='none'/>")
    if anxious:
        parts.append(
            f"<circle cx='132.7' cy='101.2' r='3.2' fill='#fffaf2'/>"
            f"<circle cx='140.3' cy='101.2' r='3.2' fill='#fffaf2'/>"
            f"<circle cx='132.9' cy='100.6' r='1.5' fill='{_INK}'/>"
            f"<circle cx='140.5' cy='100.6' r='1.5' fill='{_INK}'/>"
            f"<path d='M134.3 107.2 q1.1 1.3 2.2 0 q1.1 -1.3 2.2 0' stroke='{_INK}'"
            f" stroke-width='.9' fill='none' stroke-linecap='round'/>"
            f"<path d='M149.5 90.5 c-2.6 3.2 -2.6 5.8 0 5.8 c2.6 0 2.6 -2.6 0 -5.8 Z'"
            f" fill='#6cc2ea' opacity='.9'>"
            f"<animate attributeName='opacity' values='.25;.9;.25' dur='1.4s'"
            f" repeatCount='indefinite'/></path>")
    else:
        parts.append(
            f"<circle cx='132.8' cy='101.4' r='1.4' fill='{_INK}'/>"
            f"<circle cx='140.2' cy='101.4' r='1.4' fill='{_INK}'/>"
            f"<path d='M134.9 106.4 q1.6 1.7 3.2 0' stroke='{_INK}' stroke-width='.9'"
            f" fill='none' stroke-linecap='round'/>")
    parts.append(f"<path d='M136.5 105.2 l-1.7 -1.8 h3.4 Z' fill='#f37b75'/>")
    return "".join(parts)


def scene_svg(done: int, p: dict) -> str:
    """Inline SVG diorama for the current progress. Built cumulatively."""
    stage = scene_stage(done)
    s: list[str] = []

    if stage >= 1:  # ---- the rug ----------------------------------------- #
        s.append(
            f"<ellipse cx='85' cy='131' rx='71' ry='15' fill='{p['card_border']}'"
            f" opacity='.5'/>"
            f"<ellipse cx='85' cy='128' rx='62' ry='14' fill='#f37b75'/>"
            f"<ellipse cx='85' cy='128' rx='50' ry='10.8' fill='none' stroke='#f8c614'"
            f" stroke-width='2.2' opacity='.85'/>"
            f"<ellipse cx='85' cy='128' rx='38' ry='7.6' fill='none' stroke='#fff8ee'"
            f" stroke-width='1.5' opacity='.5'/>"
            f"<ellipse cx='85' cy='128' rx='26' ry='4.8' fill='#b79ce0' opacity='.55'/>")

    if stage >= 2:  # ---- the table --------------------------------------- #
        s.append(
            f"<path d='M60 103 L56.5 124' stroke='{_WOOD_DK}' stroke-width='4.2'"
            f" stroke-linecap='round'/>"
            f"<path d='M102 103 L105.5 124' stroke='{_WOOD_DK}' stroke-width='4.2'"
            f" stroke-linecap='round'/>"
            f"<path d='M59 114.5 L103 114.5' stroke='{_WOOD_DK}' stroke-width='2.4'"
            f" stroke-linecap='round' opacity='.85'/>"
            f"<rect x='53' y='96.5' width='56' height='6.8' rx='3.4' fill='{_WOOD}'/>"
            f"<rect x='53' y='101' width='56' height='2.3' rx='1.1' fill='{_WOOD_DK}'"
            f" opacity='.55'/>")

    fallen = stage >= 9

    if stage >= 3 and not fallen:  # ---- the vase (standing) --------------- #
        s.append(
            f"<path d='M77.4 78 C76 85 71.4 86 71.4 90.6 C71.4 95 76 96.8 81 96.8"
            f" C86 96.8 90.6 95 90.6 90.6 C90.6 86 86 85 84.6 78 Z' fill='#6cc2ea'/>"
            f"<ellipse cx='81' cy='78' rx='3.7' ry='1.5' fill='#4fb0dd'/>"
            f"<ellipse cx='76.4' cy='89.5' rx='1.9' ry='3.4' fill='#fff' opacity='.32'/>")

    if stage >= 4 and not fallen:  # ---- flowers in the vase ---------------- #
        stems = (
            f"<path d='M81 79 C79.4 69 74 63 70 55.6' stroke='{_STEM}' stroke-width='1.9'"
            f" fill='none' stroke-linecap='round'/>"
            f"<path d='M81 79 C81.6 69 81.4 60 81 51.6' stroke='{_STEM}'"
            f" stroke-width='1.9' fill='none' stroke-linecap='round'/>"
            f"<path d='M81 79 C82.8 69 88.4 63 92.6 56.4' stroke='{_STEM}'"
            f" stroke-width='1.9' fill='none' stroke-linecap='round'/>"
            f"<ellipse cx='76' cy='69' rx='3.6' ry='2' fill='#a0d4a6'"
            f" transform='rotate(-38 76 69)'/>"
            f"<ellipse cx='86.6' cy='71' rx='3.6' ry='2' fill='#a0d4a6'"
            f" transform='rotate(36 86.6 71)'/>")
        if stage >= 6:   # bloomed
            heads = (_flower(70, 51.5, "#b79ce0") + _flower(81, 47.5, "#f37b75", 6.2)
                     + _flower(92.6, 52.5, "#f8c614"))
            sway = ("<animateTransform attributeName='transform' type='rotate'"
                    " values='0 81 79;1.8 81 79;-1.8 81 79;0 81 79' dur='5.5s'"
                    " repeatCount='indefinite'/>")
        else:            # still closed
            heads = _bud(70, 55.6) + _bud(81, 51.6) + _bud(92.6, 56.4)
            sway = ""
        s.append(f"<g>{sway}{stems}{heads}</g>")

    if stage == 5:  # ---- someone waters them ----------------------------- #
        s.append(_watering_can("", pouring=True))
        s.append(_droplets())
    elif stage >= 6:  # the can is set down on the rug afterwards
        s.append(_watering_can("transform='translate(33,113) scale(.74)"
                               " translate(-119,-42)'", pouring=False))

    if fallen:  # ---- the vase falls: tipped pot, puddle, scattered blooms - #
        s.append(
            # water pooling on the tabletop, then dripping over the near edge
            f"<ellipse cx='62' cy='98.6' rx='13' ry='2.6' fill='#6cc2ea' opacity='.5'/>"
            f"<path d='M54 99.6 C50.4 105 51.8 111.4 54.6 115.6' stroke='#6cc2ea'"
            f" stroke-width='1.8' fill='none' opacity='.55' stroke-linecap='round'/>"
            f"<ellipse cx='56' cy='120.5' rx='9' ry='3' fill='#6cc2ea' opacity='.4'/>"
            # the pot on its side, mouth toward the table's left edge
            f"<g transform='translate(-9,2) rotate(-104 81 87.4)'>"
            f"<path d='M77.4 78 C76 85 71.4 86 71.4 90.6 C71.4 95 76 96.8 81 96.8"
            f" C86 96.8 90.6 95 90.6 90.6 C90.6 86 86 85 84.6 78 Z' fill='#6cc2ea'/>"
            f"<ellipse cx='81' cy='78' rx='3.7' ry='1.5' fill='#4fb0dd'/></g>"
            # blooms thrown clear — one still on the table, two on the rug
            + f"<path d='M100 94.4 C104 94.8 107 95.6 109.5 96.6' stroke='{_STEM}'"
              f" stroke-width='1.7' fill='none' stroke-linecap='round'/>"
            + _flower(97, 93, "#b79ce0", 5.2)
            + f"<path d='M66 122.4 C62 123 58.6 124 55.6 125.4' stroke='{_STEM}'"
              f" stroke-width='1.7' fill='none' stroke-linecap='round'/>"
            + _flower(70, 121, "#f37b75", 5.4)
            + f"<path d='M105 123.6 C109 124 112.4 125 115 126.2' stroke='{_STEM}'"
              f" stroke-width='1.7' fill='none' stroke-linecap='round'/>"
            + _flower(101, 122.4, "#f8c614", 5.2))

    if stage >= 7:  # ---- the cat ------------------------------------------ #
        if stage == 10:                       # bolts away
            s.append(
                "<g>"
                "<animateTransform attributeName='transform' type='translate'"
                " values='0,0;0,2;16,-22;36,-8;62,-24;96,-6' keyTimes='0;.14;.34;.52;.74;1'"
                " dur='2.3s' repeatCount='indefinite'/>"
                "<animate attributeName='opacity' values='1;1;1;0' keyTimes='0;.5;.78;1'"
                " dur='2.3s' repeatCount='indefinite'/>"
                "<g><animateTransform attributeName='transform' type='rotate'"
                " values='0 136 114;-13 136 114;7 136 114;-13 136 114;4 136 114'"
                " keyTimes='0;.3;.52;.74;1' dur='2.3s' repeatCount='indefinite'/>"
                + _cat(anxious=True) + "</g></g>")
        else:
            s.append(_cat(anxious=(stage == 9), playing=(stage == 8)))

    return ("<svg viewBox='0 0 170 150' xmlns='http://www.w3.org/2000/svg'"
            " role='img' aria-label='a little scene that grows as you label'>"
            + "".join(s) + "</svg>")


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

          /* ---- the growing scene, parked in the bottom-right corner -------- */
          /* pointer-events:none is load-bearing: it must never eat a tap. */
          .scene-corner {{ position:fixed; bottom:14px; right:14px; width:170px;
            z-index:5; pointer-events:none; }}
          .scene-corner svg {{ display:block; width:100%; height:auto; }}

          /* ---- phones ------------------------------------------------------ */
          @media (max-width: 640px) {{
            html {{ font-size: 15px; }}
            .block-container {{ padding-top:1.1rem !important;
              padding-left:.85rem !important; padding-right:.85rem !important;
              padding-bottom: calc(6.5rem + env(safe-area-inset-bottom, 0px)) !important; }}
            /* passage + answers first, label guide underneath */
            .st-key-mainsplit [data-testid="stHorizontalBlock"] {{ flex-wrap:wrap; }}
            .st-key-mainsplit [data-testid="stHorizontalBlock"]
              > [data-testid="stColumn"]:nth-of-type(1) {{ order:2; }}
            .st-key-mainsplit [data-testid="stHorizontalBlock"]
              > [data-testid="stColumn"]:nth-of-type(2) {{ order:1; }}
            .st-key-mainsplit [data-testid="stColumn"] {{ width:100% !important;
              flex:1 1 100% !important; min-width:100% !important; }}
            .reason-card {{ max-width:100% !important; padding:1.05rem 1.1rem;
              font-size:1rem; border-radius:14px; }}
            h1 {{ font-size:1.6rem !important; }}
            h4 {{ font-size:1.05rem !important; }}
            .guide-title {{ font-size:1.3rem; }}
            div[role="radiogroup"] label {{ font-size:1rem; margin-bottom:.7rem; }}
            .stButton button, .stDownloadButton button {{ min-height:44px;
              width:100% !important; }}
            [data-testid="stHorizontalBlock"]:has(.stButton) {{ row-gap:.45rem; }}
            /* keep the scene small + out of the way of "Save & next" */
            .scene-corner {{ width:100px; opacity:.8; right:6px;
              bottom: calc(6px + env(safe-area-inset-bottom, 0px)); }}
            /* nothing may push the page sideways at 375px */
            .stApp, .block-container {{ overflow-x:hidden; }}
            [data-testid="stMarkdownContainer"] {{ overflow-wrap:anywhere; }}
          }}
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
    Postgres that suspends between uses). Returns None if unconfigured/down.

    Uses psycopg 3 (`psycopg[binary]`) — psycopg2-binary has no wheels for
    Python 3.14, which is what Streamlit Cloud runs. Retries once because a
    suspended Neon endpoint can take a few seconds to wake on first contact.
    """
    url = _db_url()
    if not url:
        return None
    try:
        import psycopg
    except Exception as e:
        st.session_state["_db_error"] = f"driver import failed: {e}"
        return None
    last = None
    for timeout in (10, 20):  # cold-start friendly
        try:
            return psycopg.connect(url, connect_timeout=timeout, autocommit=True)
        except Exception as e:
            last = e
    st.session_state["_db_error"] = str(last)
    return None


def _db_ready() -> bool:
    """Ensure the labels table exists. Cached only on SUCCESS, so a cold-start
    failure never permanently pins the app into local-only mode."""
    if st.session_state.get("_db_ok"):
        return True
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
        st.session_state["_db_ok"] = True
        return True
    except Exception as e:
        st.session_state["_db_error"] = str(e)
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
        if st.session_state.get("_db_error"):
            with st.expander("why?"):
                st.code(st.session_state["_db_error"][:400])

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

# keyed container -> Streamlit stamps a `.st-key-mainsplit` class on the wrapper,
# which is what the mobile CSS uses to flip the column order (and only here — the
# nav row is a stHorizontalBlock too, and must keep its own order).
with st.container(key="mainsplit"):
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

# --------------------------------------------------------------------------- #
# The growing scene (labelling screen only) + a toast when a new bit appears
# --------------------------------------------------------------------------- #
_scene_done = len(labels)
_stage = scene_stage(_scene_done)
if "_scene_stage" not in st.session_state:
    st.session_state["_scene_stage"] = _stage          # silent on first render
elif _stage != st.session_state["_scene_stage"]:
    st.session_state["_scene_stage"] = _stage
    if _stage in SCENE_TOASTS:
        st.toast(SCENE_TOASTS[_stage])
st.markdown(
    f"<div class='scene-corner'>"
    f"{scene_svg(_scene_done, PALETTES[st.session_state.theme])}</div>",
    unsafe_allow_html=True,
)

# completion banner
if len(labels) >= N:
    st.success(
        f"🎉 All {N} rows done — thank you so much! Click **⬇︎ Download my answers** "
        f"in the sidebar and send the file back. That's everything."
    )
