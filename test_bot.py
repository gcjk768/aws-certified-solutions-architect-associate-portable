"""python test_bot.py: the bank loads, every question has a real exam domain and a valid answer, the score maths holds.
No Telegram, no Claude."""
import os
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bot  # noqa: E402

Q = bot.QUESTIONS
assert len(Q) > 50, len(Q)
assert sum(bot.WEIGHTS.values()) == 100
assert all(q["domain"] in bot.WEIGHTS for q in Q.values()), {q["domain"] for q in Q.values()} - set(bot.WEIGHTS)
assert all(q["source"] and q["answer"] <= set(q["letters"]) and len(q["letters"]) >= 2 for q in Q.values())
multi = [q for q in Q.values() if len(q["answer"]) > 1]
assert all("select" in q["question"].lower() for q in multi), [q["id"] for q in multi if "select" not in q["question"].lower()][:5]

# predicted score: all first tries right -> 1000, none -> 0
st ={"ok": {}, "bad": {}, "log": [{"id": i, "ok": 1, "first": True, "t": "2026-11-10T09:00"} for i in Q]}
assert bot.metrics(st, datetime(2026, 11, 10, 12))["score"] == 1000
st["log"] = [{**e, "ok": 0} for e in st["log"]]
assert bot.metrics(st, datetime(2026, 11, 10, 12))["score"] == 0
assert f"{bot.PASS}" in bot.report_text(bot.metrics(st, datetime(2026, 11, 10, 12)), datetime(2026, 11, 10, 12))
print(f"ok: {len(Q)} questions, {len(multi)} multi-select, pass {bot.PASS}")
