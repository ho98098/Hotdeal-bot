"""SQLite 저장소: 이미 본 글, 가격 기록, 관심 제품."""
import sqlite3
import statistics
import time


class Store:
    def __init__(self, path="dealbot.db"):
        self.db = sqlite3.connect(path)
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS seen(id TEXT PRIMARY KEY, ts REAL);
            CREATE TABLE IF NOT EXISTS prices(key TEXT, price INTEGER, ts REAL);
            CREATE INDEX IF NOT EXISTS idx_prices ON prices(key, ts);
            CREATE TABLE IF NOT EXISTS watch(name TEXT PRIMARY KEY, last_alert INTEGER);
            CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
            """
        )

    # --- 이미 본 글 ---
    def is_seen(self, item_id):
        return self.db.execute("SELECT 1 FROM seen WHERE id=?", (item_id,)).fetchone() is not None

    def mark_seen(self, item_id):
        self.db.execute("INSERT OR IGNORE INTO seen VALUES(?,?)", (item_id, time.time()))
        self.db.commit()

    # --- 가격 기록 ---
    def add_price(self, key, price, ts=None):
        self.db.execute("INSERT INTO prices VALUES(?,?,?)", (key, int(price), ts or time.time()))
        self.db.commit()

    def history_median(self, key, days=30, min_samples=5):
        """최근 N일 가격의 중앙값. 표본이 부족하면 None."""
        since = time.time() - days * 86400
        rows = self.db.execute(
            "SELECT price FROM prices WHERE key=? AND ts>=?", (key, since)
        ).fetchall()
        if len(rows) < min_samples:
            return None
        return int(statistics.median(r[0] for r in rows))

    def price_series(self, key, days=None):
        q, a = "SELECT ts, price FROM prices WHERE key=?", [key]
        if days:
            q += " AND ts>=?"
            a.append(time.time() - days * 86400)
        return self.db.execute(q + " ORDER BY ts", a).fetchall()

    # --- 관심 제품 ---
    def watch_add(self, name):
        self.db.execute("INSERT OR IGNORE INTO watch VALUES(?,NULL)", (name,))
        self.db.commit()

    def watch_remove(self, name):
        cur = self.db.execute("DELETE FROM watch WHERE name=?", (name,))
        self.db.commit()
        return cur.rowcount > 0

    def watch_list(self):
        return self.db.execute("SELECT name, last_alert FROM watch ORDER BY name").fetchall()

    def watch_set_alert(self, name, price):
        self.db.execute("UPDATE watch SET last_alert=? WHERE name=?", (price, name))
        self.db.commit()

    # --- 기타 상태 ---
    def get_meta(self, k, default=None):
        row = self.db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return row[0] if row else default

    def set_meta(self, k, v):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (k, str(v)))
        self.db.commit()
