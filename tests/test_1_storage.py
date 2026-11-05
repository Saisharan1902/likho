"""Section 1 — settings + history database."""
from datetime import date, datetime, timedelta

from likho.config import Config
from likho.db import DB


def test_config_defaults_and_persist(tmp_data):
    cfg = Config()
    assert cfg["hotkey"] == "right_option"
    assert cfg["ai_enabled"] is False

    seen = []
    cfg.on_change(seen.append)
    cfg.update({"hotkey": "fn", "not_a_setting": 1})
    assert seen == [{"hotkey": "fn", "not_a_setting": 1}]

    # a fresh Config reads what was saved; unknown keys are ignored
    again = Config()
    assert again["hotkey"] == "fn"
    assert "not_a_setting" not in again.all()


def _row(db, text, secs=5.0, app="Notes", when=None):
    return db.add(raw_text=text, final_text=text, duration_sec=secs, transcribe_sec=0.4,
                  word_count=len(text.split()), app_name=app, model="test",
                  created_at=(when or datetime.now()).isoformat(timespec="seconds"))


def test_history_add_search_delete(tmp_data):
    db = DB()
    a = _row(db, "hello world from notes")
    _row(db, "send the invoice tomorrow", app="Mail")

    assert db.history()["total"] == 2
    found = db.history(q="invoice")
    assert found["total"] == 1 and found["items"][0]["app_name"] == "Mail"
    assert db.history(q="Mail")["total"] == 1  # search also matches app name

    db.delete(a)
    assert db.get(a) is None
    assert db.history()["total"] == 1


def test_stats(tmp_data):
    db = DB()
    yesterday = datetime.now() - timedelta(days=1)
    _row(db, " ".join(["word"] * 60), secs=30, app="Slack")           # 60 words in 30s today
    _row(db, " ".join(["word"] * 40), secs=30, app="Mail", when=yesterday)

    s = db.stats(typing_wpm=40)
    assert s["sessions"] == 2
    assert s["words"] == 100
    assert s["wpm"] == 100                       # 100 words / 1 minute
    assert s["time_saved_minutes"] == 1.5        # 2.5 min to type at 40wpm − 1 min speaking
    assert s["streak"] == 2
    assert s["today_words"] == 60
    assert s["daily"][-1] == {"date": date.today().isoformat(), "words": 60, "sessions": 1}
    assert len(s["daily"]) == 30
    assert s["apps"][0]["app"] == "Slack"


def test_stats_empty(tmp_data):
    s = DB().stats()
    assert s["words"] == 0 and s["wpm"] == 0 and s["streak"] == 0


def test_old_database_gets_new_columns(tmp_data):
    import sqlite3

    import likho.db as dbmod
    old = sqlite3.connect(dbmod.DB_PATH)  # a database created before ai_sec / total_sec existed
    old.executescript(dbmod.SCHEMA)
    old.execute("INSERT INTO transcriptions (created_at, raw_text, final_text, duration_sec, transcribe_sec, "
                "word_count) VALUES ('2026-10-01T10:00:00', 'hi', 'hi', 1, 0.1, 1)")
    old.commit()
    old.close()
    db = DB()
    rid = db.add(raw_text="x", final_text="x", duration_sec=1, transcribe_sec=0.1, word_count=1,
                 ai_sec=0.3, total_sec=0.9)
    assert db.get(rid)["total_sec"] == 0.9 and db.get(1)["ai_sec"] is None
