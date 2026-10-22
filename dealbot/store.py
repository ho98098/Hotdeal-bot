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
        self.compact()

    def compact(self):
        """예전 방식(5분마다 저장)으로 쌓인 같은 가격 연속 기록을 지움 (가격이 바뀐 시점만 남김)."""
        drop, last = [], {}
        for rowid, key, price in self.db.execute("SELECT rowid, key, price FROM prices ORDER BY key, ts"):
            if last.get(key) == price:
                drop.append((rowid,))
            last[key] = price
        if drop:
            self.db.executemany("DELETE FROM prices WHERE rowid=?", drop)
            self.db.commit()

    # --- 이미 본 글 ---
    def is_seen(self, item_id):
        return self.db.execute("SELECT 1 FROM seen WHERE id=?", (item_id,)).fetchone() is not None

    def mark_seen(self, item_id):
        self.db.execute("INSERT OR IGNORE INTO seen VALUES(?,?)", (item_id, time.time()))
        self.db.commit()

    # --- 가격 기록 ---
    def add_price(self, key, price, ts=None):
        """가격이 직전 기록과 다를 때만 저장. 저장했으면 True."""
        last = self.db.execute("SELECT price FROM prices WHERE key=? ORDER BY ts DESC LIMIT 1", (key,)).fetchone()
        if last and last[0] == int(price):
            return False
        self.db.execute("INSERT INTO prices VALUES(?,?,?)", (key, int(price), ts or time.time()))
        self.db.commit()
        return True

    def price_periods(self, key, since=None, now=None):
        """기록을 [(시작, 끝, 가격)] 구간으로. 각 가격은 다음 변동 전까지 유지된 것으로 봄."""
        now = now or time.time()
        rows = self.db.execute("SELECT ts, price FROM prices WHERE key=? ORDER BY ts", (key,)).fetchall()
        out = []
        for i, (ts, p) in enumerate(rows):
            end = rows[i + 1][0] if i + 1 < len(rows) else now
            start = max(ts, since) if since else ts
            if end > start:
                out.append((start, end, p))
        return out

    def history_median(self, key, days=30, min_span_days=1):
        """최근 N일 동안 가격이 유지된 시간을 반영한 중앙값. 기록 기간이 하루 미만이면 None."""
        now = time.time()
        periods = self.price_periods(key, now - days * 86400, now)
        if not periods or now - periods[0][0] < min_span_days * 86400:
            return None
        total = sum(e - s for s, e, _ in periods)
        acc = 0
        for s, e, p in sorted(periods, key=lambda x: x[2]):
            acc += e - s
            if acc >= total / 2:
                return int(p)
        return int(periods[-1][2])

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
        self.db.execute("DELETE FROM meta WHERE k IN (?,?,?)", (f"pin:{name}", f"lastalert:{name}", f"atl:{name}"))
        self.db.execute("DELETE FROM prices WHERE key=?", (f"watch:{name}",))
        self.db.commit()
        return cur.rowcount > 0

    def watch_list(self):
        return self.db.execute("SELECT name, last_alert FROM watch ORDER BY name").fetchall()

    def watch_set_alert(self, name, price):
        self.db.execute("UPDATE watch SET last_alert=? WHERE name=?", (price, name))
        self.db.commit()

    def clear_prices(self, key):
        self.db.execute("DELETE FROM prices WHERE key=?", (key,))
        self.db.commit()

    # --- 기타 상태 ---
    def get_meta(self, k, default=None):
        row = self.db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return row[0] if row else default

    def set_meta(self, k, v):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (k, str(v)))
        self.db.commit()
