"""Section 6 manual check: open the dashboard.

    .venv/bin/python scripts/try_dashboard.py          # your real data (empty until Section 7 is wired up)
    .venv/bin/python scripts/try_dashboard.py demo     # a separate demo folder with ~3 weeks of sample dictations
"""
import os
import random
import sys
import time
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = len(sys.argv) > 1 and sys.argv[1] == "demo"
if DEMO:
    os.environ["LIKHO_DATA_DIR"] = str(ROOT / "data-demo")
sys.path.insert(0, str(ROOT))

from likho.config import Config  # noqa: E402
from likho.db import DB  # noqa: E402
from likho.server import DashboardServer  # noqa: E402

cfg, db = Config(), DB()

SAMPLES = [
    ("Slack", "um hey can you send me the uh deck before the standup tomorrow",
     "Hey, can you send me the deck before the standup tomorrow?"),
    ("Mail", "hi priya thanks for the quick turnaround no wait thanks for the detailed review i'll update the doc today",
     "Hi Priya, thanks for the detailed review. I'll update the doc today."),
    ("Code", "add a retry with exponential backoff to the upload function", None),
    ("Notes", "groceries milk eggs spinach and like the good coffee", "Groceries: milk, eggs, spinach, and the good coffee."),
    ("ChatGPT", "explain the difference between a process and a thread with an example", None),
    ("Messages", "running ten minutes late see you at the cafe", "Running 10 minutes late, see you at the café."),
]

if DEMO and db.history()["total"] == 0:
    rnd = random.Random(7)
    for day in range(21, -1, -1):
        if day > 4 and rnd.random() < 0.2:
            continue  # some days off, but keep a current streak
        midnight = datetime.now().replace(hour=0, minute=0, second=0) - timedelta(days=day)
        latest = min(datetime.now(), midnight + timedelta(hours=22))
        for _ in range(rnd.randint(2, 9)):
            app, raw, clean = rnd.choice(SAMPLES)
            words = len((clean or raw).split())
            when = midnight + (latest - midnight) * rnd.random()
            db.add(created_at=when.isoformat(timespec="seconds"), raw_text=raw, final_text=clean or raw,
                   duration_sec=round(words / rnd.uniform(1.8, 2.6), 1), transcribe_sec=round(rnd.uniform(0.2, 0.6), 2),
                   word_count=words, app_name=app, model=cfg["model"], ai_used=int(clean is not None))
    cfg.update({"dictionary": ["Priya", "Kubernetes", "PostgreSQL"],
                "replacements": [{"from": "my email", "to": "ada@example.com"}]})
    print("Seeded demo data into data-demo/")

srv = DashboardServer(cfg, db, port=int(os.environ.get("LIKHO_PORT", 8765)), status=lambda: {"message": "Dashboard preview" + (" · demo data" if DEMO else "")}).start()
print(f"Dashboard: {srv.url}   (Ctrl+C to stop)")
webbrowser.open(srv.url)
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    srv.stop()
