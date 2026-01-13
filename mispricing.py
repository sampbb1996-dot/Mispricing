print("mispricing.py started", flush=True)

import time
import math
import sqlite3
import hashlib
from dataclasses import dataclass
from typing import Dict

DB = "field.db"

POLL_SECONDS = 180

# --- dynamics ---
STEP = 0.12                 # max update per observation
DECAY = 0.02                # natural decay
INACTION_PENALTY = 0.015    # cost of doing nothing
SIGNAL_THRESHOLD = 0.55

# -------------------- model --------------------

@dataclass
class Item:
    source: str
    item_id: str
    price: float
    ref_price: float

    def key(self) -> str:
        h = hashlib.sha256()
        h.update(f"{self.source}:{self.item_id}".encode())
        return h.hexdigest()

    def error(self) -> float:
        if self.ref_price <= 0:
            return 0.0
        return (self.ref_price - self.price) / self.ref_price


# -------------------- storage --------------------

def init_db():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS field (
            key TEXT PRIMARY KEY,
            score REAL NOT NULL,
            updated INTEGER NOT NULL
        )
    """)
    con.commit()
    con.close()


def load_field() -> Dict[str, float]:
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("SELECT key, score FROM field")
    rows = cur.fetchall()
    con.close()
    return {k: v for k, v in rows}


def save_field(field: Dict[str, float]):
    now = int(time.time())
    con = sqlite3.connect(DB)
    cur = con.cursor()
    for k, v in field.items():
        cur.execute(
            "INSERT OR REPLACE INTO field (key, score, updated) VALUES (?, ?, ?)",
            (k, v, now)
        )
    con.commit()
    con.close()


# -------------------- update logic --------------------

def update_score(prev: float, signal: float | None) -> float:
    """
    Zero / inaction is a liability.
    Absence of signal causes negative drift.
    """

    # bounded signal contribution
    delta = 0.0
    if signal is not None:
        delta = max(-STEP, min(STEP, signal))

    # decay always applies
    prev *= (1 - DECAY)

    # inaction penalty if no meaningful signal
    if signal is None or abs(signal) < 1e-6:
        prev -= INACTION_PENALTY

    # apply signal
    next_score = prev + delta

    # clamp to stability bounds
    return max(-1.0, min(1.0, next_score))


# -------------------- main loop --------------------

def main():
    init_db()
    field = load_field()

    while True:
        observations: list[Item] = get_observations()  # ← your existing source logic

        touched = set()

        for item in observations:
            k = item.key()
            signal = item.error()
            prev = field.get(k, 0.0)

            field[k] = update_score(prev, signal)
            touched.add(k)

            if abs(field[k]) >= SIGNAL_THRESHOLD:
                notify(item, field[k])  # unchanged

        # apply inaction penalty to untouched entries
        for k, prev in field.items():
            if k not in touched:
                field[k] = update_score(prev, None)

        save_field(field)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
