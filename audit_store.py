"""Storage for the audit app.

PgStore is the real one (Neon Postgres). LocalStore writes two files and exists
for test mode only. Both expose the same calls, so app.py never branches on
which one is live.

Two tables:
  w2s_slots  one row per labeller: which plan slot they follow, which copy of it,
             and the opaque resume token that goes in their URL (never the name)
  w2s_audit  one row per (labeller, trial_idx), so a retried or repeated save
             never double-counts. Every row carries the plan fingerprint it was
             answered under.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

TEST_SLOT = "test"      # names starting "test" land here; pull_labels.py leaves it out


def plan_fingerprint(items_path, plans_path) -> str:
    """Names the exact stimuli + plan a row was answered under. Item ids are
    positional, so a rebuilt plan reuses them for different chats; pull_labels.py
    and analyze_audit.py refuse any row whose fingerprint is not the current one."""
    h = hashlib.sha256(Path(items_path).read_bytes())
    h.update(b"\0")
    h.update(Path(plans_path).read_bytes())
    return h.hexdigest()[:12]


SCHEMA = (
    """CREATE TABLE IF NOT EXISTS w2s_slots (
           labeller    TEXT PRIMARY KEY,
           slot        TEXT NOT NULL,
           copy        INT  NOT NULL,
           token       TEXT NOT NULL UNIQUE,
           claimed_utc TIMESTAMPTZ NOT NULL DEFAULT now(),
           UNIQUE (slot, copy)
       )""",
    """CREATE TABLE IF NOT EXISTS w2s_audit (
           id         BIGSERIAL PRIMARY KEY,
           labeller   TEXT NOT NULL,
           slot       TEXT,
           trial_idx  INT  NOT NULL,
           item_id    TEXT NOT NULL,
           is_repeat  BOOLEAN NOT NULL DEFAULT FALSE,
           label      TEXT NOT NULL CHECK (label IN ('SPEAK', 'SILENT')),
           ms_on_item INT,
           revised    BOOLEAN NOT NULL DEFAULT FALSE,
           plan_id    TEXT,
           saved_utc  TIMESTAMPTZ NOT NULL DEFAULT now(),
           UNIQUE (labeller, trial_idx)
       )""",
    # A table from an earlier build of this app may predate these columns.
    "ALTER TABLE w2s_audit ADD COLUMN IF NOT EXISTS slot TEXT",
    "ALTER TABLE w2s_audit ADD COLUMN IF NOT EXISTS revised BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE w2s_audit ADD COLUMN IF NOT EXISTS plan_id TEXT",
)

# Re-saving the same item (a retry, or "change my last answer") keeps the first
# latency, which is the one that measures reading it. If the item itself changed,
# which only happens when a plan was swapped mid-study, the row starts over.
UPSERT = """
    INSERT INTO w2s_audit
        (labeller, slot, trial_idx, item_id, is_repeat, label, ms_on_item, revised, plan_id)
    VALUES (%(labeller)s, %(slot)s, %(trial_idx)s, %(item_id)s, %(is_repeat)s,
            %(label)s, %(ms_on_item)s, %(revised)s, %(plan_id)s)
    ON CONFLICT (labeller, trial_idx) DO UPDATE SET
        label      = EXCLUDED.label,
        revised    = CASE WHEN w2s_audit.item_id = EXCLUDED.item_id
                          THEN w2s_audit.revised OR EXCLUDED.revised ELSE EXCLUDED.revised END,
        ms_on_item = CASE WHEN w2s_audit.item_id = EXCLUDED.item_id
                          THEN COALESCE(w2s_audit.ms_on_item, EXCLUDED.ms_on_item)
                          ELSE EXCLUDED.ms_on_item END,
        item_id    = EXCLUDED.item_id,
        is_repeat  = EXCLUDED.is_repeat,
        slot       = EXCLUDED.slot,
        plan_id    = EXCLUDED.plan_id,
        saved_utc  = now()"""

# The slot whose furthest-along claimant has done the least, fewest copies first.
LEAST_FINISHED = """
    SELECT s.slot, MAX(s.copy) AS top, COALESCE(MAX(n.done), 0) AS best
    FROM w2s_slots s
    LEFT JOIN (SELECT labeller, COUNT(*) AS done FROM w2s_audit GROUP BY labeller) n
           ON n.labeller = s.labeller
    WHERE s.slot = ANY(%s)
    GROUP BY s.slot
    ORDER BY best, top, s.slot
    LIMIT 1"""

PROGRESS = """
    SELECT s.slot, s.copy, s.labeller, COUNT(a.id) AS done, MAX(a.saved_utc) AS last_saved
    FROM w2s_slots s
    LEFT JOIN w2s_audit a ON a.labeller = s.labeller
    GROUP BY s.slot, s.copy, s.labeller
    ORDER BY s.slot, s.copy"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _Claims:
    """Slot assignment, shared by both stores. The first free slot goes to each
    new name; once every slot has an owner, a newcomer gets a second copy of the
    least-finished one. Safe under races: the insert is ON CONFLICT DO NOTHING and
    the loop re-reads, so two people arriving at once never share a (slot, copy)."""

    def claim(self, labeller, slot_ids):
        """-> (slot, token, created). created is False when the name already had a
        place, including one claimed a moment ago by someone else under the same
        name (their token is not ours). The app then asks "is that you?" instead of
        silently merging two people into one rater."""
        mine = self.slot_of(labeller)
        if mine:
            return (*mine, False)
        token = secrets.token_urlsafe(8)
        for _ in range(len(slot_ids) + 8):
            taken = self._taken(slot_ids)
            free = [s for s in slot_ids if (s, 0) not in taken]
            slot, copy = (free[0], 0) if free else self._least_finished(slot_ids)
            self._insert_slot(labeller, slot, copy, token)
            mine = self.slot_of(labeller)
            if mine:
                return (*mine, mine[1] == token)
        raise RuntimeError("could not claim a slot, please try again")


class PgStore(_Claims):
    kind = "db"

    def __init__(self, url=None, connect=None):
        self._url, self._connect_fn, self._conn = url, connect, None

    def _connect(self):
        if self._connect_fn:
            return self._connect_fn()
        import psycopg

        last = None
        for timeout in (10, 20):        # a suspended Neon compute takes a few seconds to wake
            try:
                return psycopg.connect(self._url, connect_timeout=timeout, autocommit=True)
            except psycopg.OperationalError as e:
                last = e
        raise last

    def _run(self, sql, params=None, fetch=False):
        import psycopg

        for attempt in (0, 1):
            try:
                if self._conn is None or self._conn.closed:
                    self._conn = self._connect()
                with self._conn.cursor() as cur:
                    cur.execute(sql, params)
                    return cur.fetchall() if fetch else None
            except (psycopg.OperationalError, psycopg.InterfaceError):
                # Neon suspends an idle compute and a held connection comes back
                # dead. Every statement here is idempotent: reconnect, retry once.
                self._conn = None
                if attempt:
                    raise

    def ensure_schema(self):
        for stmt in SCHEMA:
            self._run(stmt)

    def slot_of(self, labeller):
        r = self._run("SELECT slot, token FROM w2s_slots WHERE labeller = %s", (labeller,), fetch=True)
        return (r[0][0], r[0][1]) if r else None

    def by_token(self, token):
        r = self._run("SELECT labeller, slot FROM w2s_slots WHERE token = %s", (token,), fetch=True)
        return (r[0][0], r[0][1]) if r else None

    def _taken(self, slot_ids):
        rows = self._run("SELECT slot, copy FROM w2s_slots WHERE slot = ANY(%s)", (list(slot_ids),), fetch=True)
        return {(s, c) for s, c in rows}

    def _least_finished(self, slot_ids):
        slot, top, _ = self._run(LEAST_FINISHED, (list(slot_ids),), fetch=True)[0]
        return slot, top + 1

    def _insert_slot(self, labeller, slot, copy, token):
        self._run("INSERT INTO w2s_slots (labeller, slot, copy, token) VALUES (%s, %s, %s, %s) "
                  "ON CONFLICT DO NOTHING", (labeller, slot, copy, token))

    def done(self, labeller):
        rows = self._run("SELECT trial_idx FROM w2s_audit WHERE labeller = %s", (labeller,), fetch=True)
        return {r[0] for r in rows}

    def save(self, row):
        self._run(UPSERT, row)

    def progress(self):
        keys = ("slot", "copy", "labeller", "done", "last_saved")
        return [dict(zip(keys, r)) for r in self._run(PROGRESS, fetch=True)]


class LocalStore(_Claims):
    """Test mode. Same merge rules as the Postgres upsert."""
    kind = "local"

    def __init__(self, folder):
        self.dir = Path(folder)
        self.labels_path = self.dir / "local_labels.jsonl"
        self.slots_path = self.dir / "local_slots.json"

    def ensure_schema(self):
        self.dir.mkdir(parents=True, exist_ok=True)

    def _slots(self):
        return json.loads(self.slots_path.read_text()) if self.slots_path.exists() else {}

    def _labels(self):
        out = {}
        if self.labels_path.exists():
            for line in self.labels_path.open():
                r = json.loads(line)
                k = (r["labeller"], r["trial_idx"])
                old = out.get(k)
                if old and old["item_id"] == r["item_id"]:
                    r["revised"] = old["revised"] or r["revised"]
                    if old["ms_on_item"] is not None:
                        r["ms_on_item"] = old["ms_on_item"]
                out[k] = r
        return out

    def slot_of(self, labeller):
        s = self._slots().get(labeller)
        return (s["slot"], s["token"]) if s else None

    def by_token(self, token):
        for who, s in self._slots().items():
            if s["token"] == token:
                return who, s["slot"]
        return None

    def _taken(self, slot_ids):
        return {(s["slot"], s["copy"]) for s in self._slots().values() if s["slot"] in slot_ids}

    def _least_finished(self, slot_ids):
        done = Counter(who for who, _ in self._labels())
        best, top = {}, {}
        for who, s in self._slots().items():
            if s["slot"] in slot_ids:
                best[s["slot"]] = max(best.get(s["slot"], 0), done[who])
                top[s["slot"]] = max(top.get(s["slot"], -1), s["copy"])
        slot = min(best, key=lambda k: (best[k], top[k], k))
        return slot, top[slot] + 1

    def _insert_slot(self, labeller, slot, copy, token):
        slots = self._slots()
        if labeller in slots or any(v["slot"] == slot and v["copy"] == copy for v in slots.values()):
            return
        slots[labeller] = {"slot": slot, "copy": copy, "token": token, "claimed_utc": _now()}
        self.slots_path.write_text(json.dumps(slots, indent=1))

    def done(self, labeller):
        return {t for who, t in self._labels() if who == labeller}

    def save(self, row):
        with self.labels_path.open("a") as fh:
            fh.write(json.dumps({**row, "saved_utc": _now()}) + "\n")

    def progress(self):
        done, last = Counter(), {}
        for (who, _), r in self._labels().items():
            done[who] += 1
            last[who] = max(last.get(who, ""), r["saved_utc"])
        return [{"slot": s["slot"], "copy": s["copy"], "labeller": who, "done": done[who],
                 "last_saved": last.get(who)}
                for who, s in sorted(self._slots().items(), key=lambda kv: (kv[1]["slot"], kv[1]["copy"]))]
