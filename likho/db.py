"""SQLite history of every dictation, plus the aggregate stats the dashboard shows."""
import sqlite3
import threading
from datetime import date, datetime, timedelta

from .config import DATA_DIR

DB_PATH = DATA_DIR / "likho.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS transcriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    final_text TEXT NOT NULL,
    duration_sec REAL NOT NULL,
    transcribe_sec REAL NOT NULL,
    word_count INTEGER NOT NULL,
    app_name TEXT,
    model TEXT,
    ai_used INTEGER NOT NULL DEFAULT 0,
    audio_path TEXT
);
CREATE INDEX IF NOT EXISTS idx_created ON transcriptions(created_at);
"""
# Columns added after the first release; older databases get them via ALTER TABLE.
LATER_COLUMNS = {"ai_sec": "REAL", "total_sec": "REAL"}  # AI cleanup time; key release → text typed


class DB:
    def __init__(self):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        have = {r[1] for r in self._conn.execute("PRAGMA table_info(transcriptions)")}
        for col, kind in LATER_COLUMNS.items():
            if col not in have:
                self._conn.execute(f"ALTER TABLE transcriptions ADD COLUMN {col} {kind}")
        self._conn.commit()

    def _q(self, sql, args=()):
        with self._lock:
            cur = self._conn.execute(sql, args)
            self._conn.commit()
            return cur

    def add(self, **row) -> int:
        row.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        return self._q(f"INSERT INTO transcriptions ({cols}) VALUES ({marks})", tuple(row.values())).lastrowid

    def set_audio(self, row_id, path):
        self._q("UPDATE transcriptions SET audio_path=? WHERE id=?", (path, row_id))

    def clear_audio(self):
        self._q("UPDATE transcriptions SET audio_path=NULL")

    def get(self, row_id):
        r = self._q("SELECT * FROM transcriptions WHERE id=?", (row_id,)).fetchone()
        return dict(r) if r else None

    def delete(self, row_id):
        self._q("DELETE FROM transcriptions WHERE id=?", (row_id,))

    def history(self, q="", limit=50, offset=0):
        if q:
            like = f"%{q}%"
            rows = self._q(
                "SELECT * FROM transcriptions WHERE final_text LIKE ? OR raw_text LIKE ? OR app_name LIKE ? "
                "ORDER BY id DESC LIMIT ? OFFSET ?", (like, like, like, limit, offset))
            total = self._q(
                "SELECT COUNT(*) FROM transcriptions WHERE final_text LIKE ? OR raw_text LIKE ? OR app_name LIKE ?",
                (like, like, like)).fetchone()[0]
        else:
            rows = self._q("SELECT * FROM transcriptions ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))
            total = self._q("SELECT COUNT(*) FROM transcriptions").fetchone()[0]
        return {"items": [dict(r) for r in rows], "total": total}

    def stats(self, typing_wpm=40, days=30):
        t = self._q(
            "SELECT COUNT(*) n, COALESCE(SUM(word_count),0) words, COALESCE(SUM(duration_sec),0) secs, "
            "COALESCE(AVG(transcribe_sec),0) latency FROM transcriptions").fetchone()
        words, secs = t["words"], t["secs"]
        wpm = words / (secs / 60) if secs > 0 else 0
        saved_min = max(0.0, words / typing_wpm - secs / 60)

        start = date.today() - timedelta(days=days - 1)
        per_day = {r["d"]: r for r in self._q(
            "SELECT substr(created_at,1,10) d, SUM(word_count) words, COUNT(*) n FROM transcriptions "
            "WHERE created_at >= ? GROUP BY d", (start.isoformat(),))}
        daily = []
        for i in range(days):
            d = (start + timedelta(days=i)).isoformat()
            r = per_day.get(d)
            daily.append({"date": d, "words": r["words"] if r else 0, "sessions": r["n"] if r else 0})

        # streak = consecutive days with at least one dictation, ending today (or yesterday)
        active = {r["d"] for r in self._q("SELECT DISTINCT substr(created_at,1,10) d FROM transcriptions")}
        streak, cur = 0, date.today()
        if cur.isoformat() not in active:
            cur -= timedelta(days=1)
        while cur.isoformat() in active:
            streak += 1
            cur -= timedelta(days=1)

        apps = [dict(r) for r in self._q(
            "SELECT COALESCE(app_name,'Unknown') app, SUM(word_count) words, COUNT(*) n FROM transcriptions "
            "GROUP BY app ORDER BY words DESC LIMIT 6")]
        today = per_day.get(date.today().isoformat())
        return {
            "sessions": t["n"], "words": words, "audio_minutes": round(secs / 60, 1),
            "wpm": round(wpm), "time_saved_minutes": round(saved_min, 1),
            "avg_latency": round(t["latency"], 2), "streak": streak,
            "today_words": today["words"] if today else 0,
            "daily": daily, "apps": apps,
        }
