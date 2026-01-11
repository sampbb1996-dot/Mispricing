print("mispricing.py started", flush=True)

import time
import math
import sqlite3
import hashlib
from dataclasses import dataclass
from typing import Dict

DB = "field.db"

POLL_SECONDS = 180          # scan cadence
DECAY = 0.03                # slow drift back to neutral
STEP = 0.12                 # bounded update per observation
SIGNAL_THRESHOLD = 0.55     # notify when |score| exceeds this

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
        """
        Signed relative mispricing.
        Positive = cheap
        Negative = expensive
        """
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
            score REAL NOT NULL
        )
    """)
    con.commit()
    con.close()


def load_scores() -> Dict[str, float]:
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("SELECT key, score FROM field")
    rows = cur.fetchall()
    con.close()
    return {k: v for k, v in rows}


def save_score(key: str, score: float):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("""
        INSERT INTO field (key, score)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET score=excluded.score
    """, (key, score))
    con.commit()
    con.close()


# -------------------- governor --------------------

def update_score(prev: float, err: float) -> float:
    """
    Error-governor update.

    • No notion of correctness
    • False signals still move the field
    • Bounded, damped, symmetric
    """

    # compress error (no blow-ups)
    e = math.tanh(err)

    # bounded step
    delta = STEP * e

    # decay toward neutral
    next_score = prev * (1 - DECAY) + delta

    # hard clamp
    return max(-1.0, min(1.0, next_score))


# -------------------- signal --------------------

def maybe_notify(item: Item, score: float):
    if abs(score) >= SIGNAL_THRESHOLD:
        side = "CHEAP" if score > 0 else "EXPENSIVE"
        print(
            f"[SIGNAL] {item.source} {item.item_id} "
            f"{side} | score={score:.2f}",
            flush=True
        )


# -------------------- example scan --------------------
# Replace this with real marketplace scraping

def scan_market() -> list[Item]:
    """
    Dummy scan to prove the system emits signals immediately.
    """
    return [
        Item("demo", "A", price=70, ref_price=120),
        Item("demo", "B", price=105, ref_price=100),
        Item("demo", "C", price=40, ref_price=90),
    ]


# -------------------- main loop --------------------

def main():
    init_db()
    scores = load_scores()

    print("scan tick", flush=True)

    items = scan_market()

    for item in items:
        key = item.key()
        prev = scores.get(key, 0.0)
        err = item.error()

        score = update_score(prev, err)
        save_score(key, score)

        maybe_notify(item, score)

    print("scan complete", flush=True)


if __name__ == "__main__":
    while True:
        try:
            main()
        except Exception as e:
            print("error:", e, flush=True)
        time.sleep(POLL_SECONDS)
