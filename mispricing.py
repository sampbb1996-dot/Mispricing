print("mispricing.py started", flush=True)
# field_bot_min.py
import time, math, sqlite3, hashlib
from dataclasses import dataclass
from typing import Dict

DB = "field.db"
POLL = 180
NOTIFY_THRESHOLD = 0.7
DECAY = 0.05          # daily decay toward 0
STEP = 0.08           # bounded update
COOLDOWN = 3600

# ---------- model ----------

@dataclass
class Item:
    source: str
    id: str
    title: str
    price: float | None
    created_ts: float

# ---------- utils ----------

def now(): return time.time()
def clamp(x,a,b): return max(a,min(b,x))
def sig(x): return 1/(1+math.exp(-x))

# ---------- db ----------

def db():
    c = sqlite3.connect(DB)
    c.execute("PRAGMA journal_mode=WAL;")
    return c

def init():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS w(k TEXT PRIMARY KEY,v REAL,t REAL);
        CREATE TABLE IF NOT EXISTS cd(k TEXT PRIMARY KEY,u REAL);
        CREATE TABLE IF NOT EXISTS seen(s TEXT,i TEXT,PRIMARY KEY(s,i));
        """)

def weight(k):
    with db() as c:
        r = c.execute("SELECT v,t FROM w WHERE k=?", (k,)).fetchone()
        if not r: return 0.0
        v,t = r
        days = (now()-t)/86400
        return v*((1-DECAY)**max(days,0))

def set_weight(k,v):
    with db() as c:
        c.execute(
            "INSERT INTO w VALUES(?,?,?) ON CONFLICT(k) DO UPDATE SET v=?,t=?",
            (k,v,now(),v,now())
        )

def cooldown(k):
    with db() as c:
        r = c.execute("SELECT u FROM cd WHERE k=?", (k,)).fetchone()
        return r and now()<r[0]

def set_cd(k):
    with db() as c:
        c.execute(
            "INSERT INTO cd VALUES(?,?) ON CONFLICT(k) DO UPDATE SET u=?",
            (k,now()+COOLDOWN,now()+COOLDOWN)
        )

def seen(item):
    with db() as c:
        r = c.execute("SELECT 1 FROM seen WHERE s=? AND i=?", (item.source,item.id)).fetchone()
        if r: return True
        c.execute("INSERT INTO seen VALUES(?,?)", (item.source,item.id))
        return False

# ---------- field logic ----------

def keys(item: Item) -> Dict[str,str]:
    major = item.title.lower().split()[0] if item.title else "x"
    return {
        "src": f"s:{item.source}",
        "maj": f"m:{major}",
    }

def base_exc(item: Item) -> float:
    b = 0.0
    if item.price is not None:
        b += clamp(1/(1+item.price),0,0.25)
    age_h = (now()-item.created_ts)/3600
    b += clamp(math.exp(-age_h/12)*0.25,0,0.25)
    return b

def excitation(item: Item) -> float:
    x = base_exc(item)
    damp = 1.0
    for k in keys(item).values():
        if cooldown(k): damp *= 0.5
        x += clamp(weight(k), -0.35, 0.35)
    return clamp(sig(3*(x-0.35))*damp,0,1)

# ---------- outcomes ----------

def outcome(item: Item, win: bool):
    for k in keys(item).values():
        w = weight(k)
        if win:
            set_weight(k, clamp(w+STEP,-1,1))
        else:
            set_weight(k, clamp(w-STEP,-1,1))
            set_cd(k)

# ---------- loop ----------

def fetch_items():  # REPLACE with real source
    t = now()
    return [Item("demo", hashlib.md5(str(int(t//600)).encode()).hexdigest(),
                 "digital asset !!!", 9.0, t-1800)]

def run():
    init()
    while True:
        for it in fetch_items():
            if seen(it): continue
            exc = excitation(it)
            if exc >= NOTIFY_THRESHOLD:
                print(f"[NOTIFY] exc={exc:.2f} {it.title}")
        time.sleep(POLL)

if __name__ == "__main__":
    run()
