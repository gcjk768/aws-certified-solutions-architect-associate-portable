#!/usr/bin/env python3
"""Merge banks/*.csv + sources/*_bank.csv into data/questions.csv (bot schema) + data/domains.json (id -> exam domain).
Usage: python -I build_csv.py
Input rows: source,source_url,exam_domain,question,options,correct,explanation (one file per source).
Ids are stable: a stem already in data/questions.csv keeps its id, so progress in state.json survives a rebuild.
In the output, `domain` holds the source name (the bot moves it to q["source"]); the exam domain is in domains.json.
Exits non-zero on a malformed row."""
import csv
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
PREFIX = {"saac03": "SAA", "rtt": "RTT"}[re.search(r'getLogger\("(\w+)"\)', (HERE / "bot.py").read_text(encoding="utf-8"))[1]]
FIELDS = ["id", "domain", "question", "options", "correct", "explanation"]
WEIGHTS = {}
exec(re.search(r"^WEIGHTS = \{.*?\}", (HERE / "bot.py").read_text(encoding="utf-8"), re.M | re.S)[0], {}, WEIGHTS)
WEIGHTS = WEIGHTS["WEIGHTS"]


def norm(s: str) -> str:
    return re.sub(r"\W+", " ", s.lower()).strip()[:100]


def check(r: dict) -> str:
    letters = [l[0] for l in r["options"].splitlines() if l[1:3] == ". "]
    if len(letters) < 2 or letters != list("ABCDEFGH"[:len(letters)]):
        return "options must be A. B. C. ..."
    if not r["correct"] or not set(r["correct"].split(",")) <= set(letters):
        return f"correct {r['correct']!r} not in {letters}"
    if r["exam_domain"] not in WEIGHTS:
        return f"unknown exam_domain {r['exam_domain']!r}"
    return ""


def main() -> int:
    csv.field_size_limit(10 ** 9)
    old = {}
    if (DATA / "questions.csv").exists():
        with (DATA / "questions.csv").open(encoding="utf-8") as f:
            old = {norm(r["question"]): r["id"] for r in csv.DictReader(f)}
    nxt = max([int(i.split("-")[1]) for i in old.values()] + [0]) + 1
    out, dom, seen, bad = [], {}, set(), 0
    # banks/ = open-licensed or self-written (committed); sources/ = private, e.g. Tutorials Dojo (gitignored, never uploaded)
    for path in sorted((HERE / "banks").glob("*.csv")) + sorted((HERE / "sources").glob("*_bank.csv")):
        with path.open(encoding="utf-8") as f:
            for n, r in enumerate(csv.DictReader(f), 2):
                r = {k: (v or "").strip() for k, v in r.items()}
                err = check(r)
                if err:
                    print(f"{path.name}:{n}: {err}")
                    bad += 1
                    continue
                k = norm(r["question"])
                if k in seen:
                    continue
                seen.add(k)
                qid = old.get(k)
                if not qid:
                    qid, nxt = f"{PREFIX}-{nxt:04d}", nxt + 1
                out.append({"id": qid, "domain": r["source"], "question": r["question"], "options": r["options"],
                            "correct": r["correct"], "explanation": r["explanation"]})
                dom[qid] = r["exam_domain"]
    if bad:
        print(f"{bad} malformed rows")
        return 1
    out.sort(key=lambda r: r["id"])
    DATA.mkdir(exist_ok=True)
    with (DATA / "questions.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(out)
    (DATA / "domains.json").write_text(json.dumps(dom, indent=0), encoding="utf-8")
    by = {}
    for r in out:
        by.setdefault((r["domain"], dom[r["id"]]), 0)
        by[(r["domain"], dom[r["id"]])] += 1
    for (s, d), c in sorted(by.items()):
        print(f"{c:5d}  {s}  |  {d}")
    print(f"{len(out)} questions -> data/questions.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
