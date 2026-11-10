"""Parse Tutorials Dojo SAA-C03 review-mode PDF printouts into sources/td_bank.csv.

Private study material: never commit the PDFs or the CSV.

How the answer is found (from the PDF drawing layer, not the text):
  - every option sits in its own rounded box in the option column;
  - the correct option box is filled green (0.11, 0.85, 0.57);
  - an option the user ticked has a blue checkbox; a wrong tick gets a red outline.
    A *correct* tick is NOT green, so correct = green + (ticked - red).
The layout answer is cross-checked against the explanation's
"the correct answer is: ..." sentence; disagreements are dropped.

Usage: python parse_td.py [--sample N]
"""
import csv, difflib, glob, os, random, re, sys
from collections import Counter

import pymupdf

SRC = r"C:/Users/<USER>\OneDrive\Desktop\SAA-C03"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources", "td_bank.csv")
HEADER = ["source", "source_url", "exam_domain", "question", "options", "correct", "explanation"]

GREEN, RED, BLUE = (0.11, 0.85, 0.57), (0.94, 0.24, 0.27), (0.0, 0.49, 1.0)
PUA = re.compile("[\ue000-\uf8ff\x00]")
DOMAINS = {"secure": "Design Secure Architectures", "resilient": "Design Resilient Architectures",
           "high-performing": "Design High-Performing Architectures",
           "cost": "Design Cost-Optimized Architectures"}
KWORDS = {"TWO": 2, "THREE": 3, "FOUR": 4}
EXPL_STOP = re.compile(r"^(References?:|Check out this|Comparison of AWS Services)", re.I)
ANSWER_PHRASE = re.compile(r"correct (?:answers?|choices?|options?|solutions?) (?:is|are)\b:?", re.I)


def near(c, ref):
    return bool(c) and all(abs(a - b) < 0.03 for a, b in zip(c, ref))


def page_lines(page, pno):
    """Text rows of one page, each tagged with the option box (if any) it sits in."""
    boxes, ticks = [], []
    for d in page.get_drawings():
        r = d["rect"]
        if 150 < r.x0 < 180 and 330 < r.width < 370 and r.height < 700:
            # whole boxes are stroked outlines; green = correct, red = wrong tick.
            # Boxes cut by a page break are printed as plain fills (grey, or green/red).
            col = d.get("color") if d["type"] == "s" else d.get("fill")
            flag = {"green"} if near(col, GREEN) else {"red"} if near(col, RED) else set()
            boxes.append([r.y0, r.y1, flag])
        elif 8 < r.width < 18 and 8 < r.height < 18 and 160 < r.x0 < 200:
            # ticked: blue checkbox outline (multi-select) or blue radio dot (single)
            ticks.append(((r.y0 + r.y1) / 2, near(d.get("color"), BLUE) or near(d.get("fill"), BLUE)))
    merged = []  # several drawings can make up one box
    for b in sorted(boxes):
        if merged and b[0] < merged[-1][1] - 5:
            merged[-1][1] = max(merged[-1][1], b[1])
            merged[-1][2] |= b[2]
        else:
            merged.append(b)
    for b in merged:
        if any(blue for y, blue in ticks if b[0] <= y <= b[1]):
            b[2].add("ticked")

    raw = []
    for blk in page.get_text("dict")["blocks"]:
        for ln in blk.get("lines", []):
            t = PUA.sub("", "".join(s["text"] for s in ln["spans"]))
            if t.strip():
                x0, y0, x1, y1 = ln["bbox"]
                raw.append([y0, y1, x0, x1, t])
    raw.sort(key=lambda r: ((r[0] + r[1]) / 2, r[2]))
    rows = []
    for r in raw:  # merge fragments that share a baseline
        if rows and abs((rows[-1][0] + rows[-1][1]) / 2 - (r[0] + r[1]) / 2) < 4:
            prev = rows[-1]
            gap = "" if (prev[4].endswith((" ", "\xa0")) or r[4].startswith((" ", "\xa0")) or r[2] - prev[3] < 1.5) else " "
            prev[4] += gap + r[4]
            prev[1], prev[3] = max(prev[1], r[1]), r[3]
        else:
            rows.append(list(r))
    out = []
    for y0, y1, x0, x1, t in rows:
        yc, box = (y0 + y1) / 2, None
        for i, b in enumerate(merged):
            if b[0] - 1 <= yc <= b[1] + 1 and x0 > 175:
                box = (pno, i)
                break
        out.append({"t": " ".join(t.replace("\xa0", " ").split()), "y0": y0, "y1": y1, "page": pno,
                    "h": page.rect.height, "box": box, "binfo": merged[box[1]] if box else None})
    return out


def join(lines):
    s = ""
    for l in lines:
        if s.endswith("-") and len(s) > 1 and s[-2].isalpha():
            s += l
        else:
            s += (" " if s else "") + l
    return s.strip()


def norm(s):
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s.lower().replace("’", "'")).split())


def answers_from_explanation(options, explanation, k):
    """Read the k options quoted right after 'the correct answer is:' (empty set if unsure).

    Walks the answer sentence left to right: each answer must start within a few
    words of where the previous one ended and fuzzy-match an option at >= 0.8."""
    am = ANSWER_PHRASE.search(explanation)
    if not am:
        return set()
    words = norm(explanation[am.end():am.end() + 3000]).split()
    opts = [norm(o).split() for o in options]
    chosen, p = [], 0
    for _ in range(k):
        best = (0.0, None, None)
        for start in range(p, min(p + 5, len(words))):
            for j, o in enumerate(opts):
                if j not in chosen and o:
                    r = difflib.SequenceMatcher(None, " ".join(o), " ".join(words[start:start + len(o)])).ratio()
                    if r > best[0]:
                        best = (r, j, start + len(o))
        if best[0] < 0.8:
            return set()
        chosen.append(best[1])
        p = best[2]
    return set(chosen)


def parse_file(path):
    doc = pymupdf.open(path)
    lines = [l for pno in range(len(doc)) for l in page_lines(doc[pno], pno)]
    if not lines:
        return [], Counter({"no text layer (vector glyphs / image print), needs OCR": 1})
    starts = [i for i, l in enumerate(lines) if re.fullmatch(r"\d+\. QUESTION", l["t"])]
    qs, skips = [], Counter()
    for si, s in enumerate(starts):
        block = lines[s + 1: starts[si + 1] if si + 1 < len(starts) else len(lines)]
        q, why = parse_question(block)
        if q:
            qs.append(q)
        else:
            skips[why] += 1
    return qs, skips


def parse_question(block):
    i, domain = 0, None
    if block and block[0]["t"].startswith("Category:"):
        cat = block[0]["t"].lower()
        domain = next((v for k, v in DOMAINS.items() if k in cat), None)
        i = 1
    stem = []
    while i < len(block) and block[i]["box"] is None and block[i]["t"] not in ("Correct", "Incorrect"):
        stem.append(block[i]["t"])
        i += 1
    opts, prev = [], None   # each opt: [lines, flags, last line]
    while i < len(block) and block[i]["t"] not in ("Correct", "Incorrect"):
        l = block[i]
        if l["box"] is None:
            return None, "text outside option boxes"
        if l["box"] != prev:
            b = l["binfo"]
            last = opts[-1] if opts else None
            # one option box cut by a page break: runs to the bottom clip of page p
            # (13.5-13.9 pt from the edge; whole boxes stop >= 14.2 pt short)
            # and restarts at the top clip of page p+1
            split = (last and l["page"] == last[2]["page"] + 1 and b[0] < 14.4
                     and last[2]["binfo"][1] > last[2]["h"] - 14.1)
            if split:
                last[1] |= b[2]
            else:
                opts.append([[], set(b[2]), l])
            prev = l["box"]
        opts[-1][0].append(l["t"])
        opts[-1][2] = l
        i += 1
    if i >= len(block):
        return None, "no Correct/Incorrect marker"
    expl_lines, last = [], None
    for l in block[i + 1:]:
        if EXPL_STOP.match(l["t"]):
            break
        t = re.sub(r"https?://\S+", "", l["t"]).strip()
        if not t:
            continue
        new_para = last is not None and l["page"] == last["page"] and l["y0"] - last["y1"] > 10
        if new_para or t.startswith(("–", "- ", "•")) or not expl_lines:
            expl_lines.append([t])
        else:
            expl_lines[-1].append(t)
        last = l
    explanation = "\n".join(join(p) for p in expl_lines)

    question = join(stem)
    if not question:
        return None, "empty stem"
    m = re.search(r"\(Select (TWO|THREE|FOUR)\b", question, re.I)
    k = KWORDS[m.group(1).upper()] if m else 1
    options = [join(o[0]) for o in opts]
    if len(options) < k + 2 or len(options) > 6:
        return None, f"option count {len(options)} for select-{k}"

    layout = {j for j, o in enumerate(opts) if "green" in o[1] or ("ticked" in o[1] and "red" not in o[1])}
    expl_set = answers_from_explanation(options, explanation, k)
    if len(layout) == k and (not expl_set or expl_set == layout):
        correct = layout
    elif len(layout) < k and len(expl_set) == k and layout <= expl_set:
        correct = expl_set
    elif len(layout) != k:
        return None, f"layout gives {len(layout)} answers for select-{k}"
    else:
        return None, "layout answer disagrees with explanation"
    return {"source": "Tutorials Dojo", "source_url": "", "exam_domain": domain, "question": question,
            "options": "\n".join(f"{chr(65 + j)}. {o}" for j, o in enumerate(options)),
            "correct": ",".join(chr(65 + j) for j in sorted(correct)), "explanation": explanation}, None


def main():
    files = sorted(glob.glob(os.path.join(SRC, "*.pdf")), key=lambda f: ("Randomized" in f, f))
    seen, rows, total_skips = set(), [], Counter()
    for f in files:
        qs, skips = parse_file(f)
        dups = new = 0
        for q in qs:
            key = " ".join(q["question"].lower().split())[:100]
            if key in seen:
                dups += 1
            elif not q["exam_domain"]:   # randomized sets print no Category line
                skips["no Category line, not in any categorized set"] += 1
            else:
                seen.add(key)
                rows.append(q)
                new += 1
        total_skips += skips
        print(f"{os.path.basename(f)[:60]:60} kept {new:3}  dup {dups:3}  "
              f"skipped {sum(skips.values()):3} {dict(skips) if skips else ''}")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=HEADER)
        w.writeheader()
        w.writerows(rows)
    print(f"\nTOTAL rows {len(rows)} -> {OUT}")
    print("per domain:", dict(Counter(r["exam_domain"] for r in rows)))
    print("skips:", dict(total_skips))
    if "--sample" in sys.argv:
        n = int(sys.argv[sys.argv.index("--sample") + 1])
        for r in random.Random(7).sample(rows, n):
            print("\n" + "=" * 80 + f"\n[{r['exam_domain']}] {r['question']}\n{r['options']}\nANSWER {r['correct']}\n"
                  f"EXPL: {r['explanation'][:600]}")


if __name__ == "__main__":
    main()
