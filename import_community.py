"""Build banks/community_bank.csv from vetted, open-licensed SAA-C03 question sources.

Run with:  python -I import_community.py           (build + validate)
           python -I import_community.py --check   (validate existing CSV only)

Raw downloads in sources/raw/ are untrusted data: they are only parsed (json / text), never executed.
Missing raw files are fetched from the URLs in SOURCES.
"""
import csv
import json
import re
import sys
import random
import zlib
import urllib.request
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE / "sources" / "raw"
OUT = HERE / "banks" / "community_bank.csv"
HEADER = ["source", "source_url", "exam_domain", "question", "options", "correct", "explanation"]
DOMAINS = ["Design Secure Architectures", "Design Resilient Architectures",
           "Design High-Performing Architectures", "Design Cost-Optimized Architectures"]
SEC, RES, PERF, COST = DOMAINS
GH = "https://raw.githubusercontent.com"

# local file -> download URL
FILES = {
    "aws_saa_sample.pdf": "https://d1.awsstatic.com/training-and-certification/docs-sa-assoc/AWS-Certified-Solutions-Architect-Associate_Sample-Questions.pdf",
    "berkay_questions-all.js": f"{GH}/BerkayCakibey/aws-saa-tips/HEAD/website/questions-all.js",
    **{f"elamin_{n}.json": f"{GH}/el-amin-dev/AWS-mock-exams/HEAD/mocks/{n}.json"
       for n in ("building", "topics-advanced", "topics-core-architecture", "topics-foundations")},
    **{f"learnai_SAA-C03-{v}.json": f"{GH}/cuic19053-hue/learnai/HEAD/certifications/questions/SAA-C03-{v}.json"
       for v in ("v1", "v2")},
}


def raw(name):
    p = RAW / name
    if not p.exists():
        RAW.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(FILES[name], timeout=60) as r:
            p.write_bytes(r.read())
    return p


# ---------- domain classifier (stem intent first, then service keywords) ----------
# Intent phrases name what the question optimises for; they are weighted heavily.
INTENT = {
    COST: r"cost[- ]effective|\bcosts?\b|\bbill(s|ed|ing)?\b|\bpa(y|ying|id)\b|charges?|cheap|expensive|"
          r"economical|budget|spend|savings?",
    SEC: r"least[- ]privilege|encrypt|unauthori[sz]ed|complian|secur(e|ity)|credentials?|secrets?|"
         r"sensitive|\bPII\b|regulat|block public|must not be (publicly )?accessible|"
         r"authenticat|authori[sz]|threat|attack|DDoS|exfiltrat|tamper|breach|malicious|"
         r"nothing on the internet|(only|must) .{0,40}(be allowed|access)|grant|permissions?",
    RES: r"highly available|high availability|fault[- ]toleran|disaster recovery|\bRPO\b|\bRTO\b|"
         r"\bfail(s|ed|ure|over)?\b|\bdurab|survive|outage|resilien|data loss|lost|recover|"
         r"unavailable|loss of|impair|unhealthy|keep (serving|running|working)|stay available|"
         r"single point of failure|decoupl|loosely coupled|backup|retry|interrupt|replaced automatically",
    PERF: r"latency|performance|throughput|\bIOPS\b|fast(er|est)?\b|quickly|response time|high[- ]performing|"
          r"scal(e|es|ing|able|ability)|burst|spikes?|bottleneck|real[- ]time|slow|time out|timeouts?|"
          r"keep up|millisecond|throttl|stale reads|globally distributed users|users (around|across) the world",
}
KEYWORDS = {
    COST: r"Reserved Instances?|Savings Plans?|Spot|Glacier|Intelligent-Tiering|lifecycle|right-?siz|"
          r"Cost Explorer|Budgets|Compute Optimizer|One Zone-IA|Standard-IA|gp3|On-Demand|Fargate Spot|idle",
    SEC: r"\bIAM\b|\bKMS\b|\bWAF\b|Shield|GuardDuty|Macie|Inspector|\bMFA\b|\bSCPs?\b|Cognito|Secrets Manager|"
         r"Certificate Manager|\bACM\b|CloudTrail|Security Hub|security groups?|network ACL|VPC endpoint|"
         r"PrivateLink|bucket policy|resource policy|role|SSE-|TLS|HTTPS|Identity Center|Organizations|presigned",
    RES: r"Multi-AZ|multiple Availability Zones|Auto Scaling|Route 53 (health|failover)|cross-Region replication|"
         r"read replica|AWS Backup|snapshots?|SQS|SNS|EventBridge|Step Functions|global tables|Aurora Global|"
         r"pilot light|warm standby|Elastic Disaster Recovery|versioning|health checks?",
    PERF: r"ElastiCache|DAX|CloudFront|Global Accelerator|placement group|Transfer Acceleration|read replicas?|"
          r"Provisioned IOPS|io2|instance store|Kinesis|caching|cache|Enhanced Networking|EFA|multipart|"
          r"compute optimized|memory optimized|Lambda|Aurora Serverless|DynamoDB",
}
TOPIC_HINT = {  # source-provided topic labels, used only as a weak tiebreaker signal
    "security": SEC, "governance": SEC, "cost optimization": COST, "high availability & resilience": RES,
    "decoupling": RES, "performance": PERF,
}


def classify(stem, correct_text, topic=""):
    sentences = re.split(r"(?<=[.?!])\s+", stem.strip())
    ask = " ".join(sentences[-2:])  # requirement + question sentence
    score = Counter()
    for d, rx in INTENT.items():
        score[d] += 3 * len(re.findall(rx, ask, re.I)) + len(re.findall(rx, stem, re.I))
    for d, rx in KEYWORDS.items():  # services in the chosen answer, not the scenario background
        score[d] += len(re.findall(rx, correct_text, re.I))
    if topic.lower() in TOPIC_HINT:
        score[TOPIC_HINT[topic.lower()]] += 2
    # ponytail: keyword heuristic, ties broken by exam weighting order; swap for an LLM pass if accuracy matters
    return max(DOMAINS, key=lambda d: (score[d], -DOMAINS.index(d)))


# ---------- normalisation shared by all loaders ----------
COUNT = {2: "TWO", 3: "THREE", 4: "FOUR"}


def ws(s):
    return re.sub(r"\s+", " ", s or "").strip()


def make_row(source, url, stem, options, correct_idx, explanation, topic="", shuffle=False):
    stem, options = ws(stem), [ws(o) for o in options]
    correct_idx = sorted(set(correct_idx))
    if shuffle:  # source always puts the answer first; deterministic shuffle per question
        order = list(range(len(options)))
        random.Random(zlib.crc32(stem.encode())).shuffle(order)
        options = [options[i] for i in order]
        correct_idx = sorted(order.index(i) for i in correct_idx)
    n = len(correct_idx)
    stated = re.search(r"\((?:select|choose) (two|three|four)\.?\)", stem, re.I)
    if n > 1:
        stem = re.sub(r"\s*\((?:select|choose) (?:two|three|four)\.?\)", "", stem, flags=re.I).strip()
        stem += f" (Select {COUNT[n]}.)"
    elif stated:
        return None  # stem asks for several answers but source gives one: unresolved
    if len(stem) < 60 or len(options) < 4 or len(options) > 6 or not correct_idx \
            or max(correct_idx) >= len(options) or any(not o for o in options):
        return None
    letters = "ABCDEF"
    correct_text = " ".join(options[i] for i in correct_idx)
    return {
        "source": source, "source_url": url,
        "exam_domain": classify(stem, correct_text, topic),
        "question": stem,
        "options": "\n".join(f"{letters[i]}. {o}" for i, o in enumerate(options)),
        "correct": ",".join(letters[i] for i in correct_idx),
        "explanation": (explanation or "").strip(),
    }


# ---------- loaders ----------
def load_aws_official():
    import pypdf  # installed; only used for the official AWS PDF
    pdf = raw("aws_saa_sample.pdf")
    lines = []
    for page in pypdf.PdfReader(str(pdf)).pages:
        for ln in page.extract_text().splitlines():
            if re.search(r"Sample Exam Questions|Associate \(SAA-C03\)|All rights reserved|P a g e", ln):
                continue
            lines.append(ln.rstrip())
    text = "\n".join(lines)
    body, answers = text.split("\nAnswers", 1)
    fix = lambda s: re.sub(r"\b(t) (he|o)\b|(endpoint) (s)\b|(re) (-provision)|(\S) +(\.)",
                           lambda m: "".join(g for g in m.groups() if g), ws(s)).replace(" ,", ",")
    ans = {int(m[1]): (m[2], fix(m[3])) for m in
           re.finditer(r"^(\d+)\) ([A-F](?:, [A-F])*) – (.*?)(?=^\d+\) |\Z)", answers, re.S | re.M)}
    rows = []
    for m in re.finditer(r"^(\d+)\) (.*?)(?=^\d+\) |\Z)", body, re.S | re.M):
        num, chunk = int(m[1]), m[2]
        parts = re.split(r"^([A-F])\) ", chunk, flags=re.M)
        stem, opts = parts[0], [fix(parts[i + 1]) for i in range(1, len(parts) - 1, 2)]
        letters, expl = ans[num]
        rows.append(make_row("AWS official SAA-C03 sample questions", FILES["aws_saa_sample.pdf"],
                             fix(stem), opts, ["ABCDEF".index(x) for x in letters.split(", ")], expl))
    return rows


def load_berkay():
    src = raw("berkay_questions-all.js").read_text(encoding="utf-8")
    qs = json.loads(src[src.index("["):src.rindex("];") + 1])  # file is a JSON array assigned to a const
    url = "https://github.com/BerkayCakibey/aws-saa-tips"
    rows = []
    for q in qs:
        corr = q["correct"] if isinstance(q["correct"], list) else [q["correct"]]
        expl = q.get("explanation", "")
        if q.get("keyRule"):
            expl += f"\nKey rule: {q['keyRule']}"
        rows.append(make_row("BerkayCakibey/aws-saa-tips (MIT)", url, q["q"], q["options"], corr,
                             expl, q.get("topic", ""), shuffle=True))
    return rows


def load_elamin():
    rows = []
    for n in ("building", "topics-foundations", "topics-core-architecture", "topics-advanced"):
        d = json.loads(raw(f"elamin_{n}.json").read_text(encoding="utf-8"))
        url = f"https://github.com/el-amin-dev/AWS-mock-exams/blob/main/mocks/{n}.json"
        for q in d["questions"]:
            opts = q["options"]
            expl = "\n".join(f"{'ABCDEF'[i]}. {ws(o.get('why', ''))}" for i, o in enumerate(opts) if o.get("why"))
            rows.append(make_row("el-amin-dev/AWS-mock-exams (MIT)", url, q["stem"], [o["text"] for o in opts],
                                 [i for i, o in enumerate(opts) if o["correct"]], expl, q.get("topic", "")))
    return rows


def load_learnai():
    rows = []
    for v in ("v1", "v2"):
        url = f"https://github.com/cuic19053-hue/learnai/blob/main/certifications/questions/SAA-C03-{v}.json"
        for q in json.loads(raw(f"learnai_SAA-C03-{v}.json").read_text(encoding="utf-8-sig")):
            strip = lambda o: re.sub(r"^[A-F][.)]\s*", "", o)
            opts = [strip(o) for o in q["options"]]
            corr = [i for i, o in enumerate(q["options"]) if ws(o) == ws(q["correct"])]
            rows.append(make_row("cuic19053-hue/learnai (Apache-2.0)", url, q["question"], opts, corr,
                                 q.get("explanation", ""), shuffle=True))
    return rows


LOADERS = [load_aws_official, load_berkay, load_elamin, load_learnai]


# ---------- build + validate ----------
def build():
    rows, seen, dropped = [], set(), Counter()
    for loader in LOADERS:
        for r in loader():
            if r is None:
                dropped[loader.__name__ + " invalid"] += 1
                continue
            key = r["question"][:80].lower()
            if key in seen:
                dropped[loader.__name__ + " duplicate"] += 1
                continue
            seen.add(key)
            rows.append(r)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        w.writerows(rows)
    print("dropped:", dict(dropped) or "none")


def validate():
    with OUT.open(encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        assert rd.fieldnames == HEADER, rd.fieldnames
        rows = list(rd)
    errors, keys = [], set()
    for n, r in enumerate(rows, 2):
        opts = r["options"].split("\n")
        letters = [o[0] for o in opts]
        corr = r["correct"].split(",")
        problems = [
            r["exam_domain"] not in DOMAINS and "bad domain",
            letters != list("ABCDEF"[:len(opts)]) and "option letters",
            not all(re.match(r"^[A-F]\. \S", o) for o in opts) and "option format",
            len(opts) < 4 and "<4 options",
            not all(c in letters for c in corr) and "correct letter missing",
            len(r["question"]) < 60 and "short stem",
            len(corr) > 1 and f"(Select {COUNT.get(len(corr))}.)" not in r["question"] and "multi-select tag",
            r["question"][:80].lower() in keys and "duplicate",
            not r["source"] or not r["source_url"].startswith("https://") and "source",
        ]
        keys.add(r["question"][:80].lower())
        errors += [f"line {n}: {p}" for p in problems if p]
    print(f"rows: {len(rows)}  errors: {len(errors)}")
    for e in errors[:20]:
        print("  ", e)
    print("per source:")
    for k, v in Counter(r["source"] for r in rows).most_common():
        print(f"  {v:4d}  {k}")
    print("per domain:")
    for d in DOMAINS:
        print(f"  {sum(r['exam_domain'] == d for r in rows):4d}  {d}")
    print("multi-select:", sum("," in r["correct"] for r in rows),
          " answer letters:", dict(sorted(Counter(c for r in rows for c in r["correct"].split(",")).items())))
    return not errors


def check_classifier():
    """Sanity check: agreement of classify() with el-amin's own domain labels (not used for output)."""
    label = {"Secure": SEC, "Resilient": RES, "High-Performing": PERF, "Cost-Optimized": COST}
    hit = tot = 0
    for n in ("building", "topics-foundations", "topics-core-architecture", "topics-advanced"):
        for q in json.loads(raw(f"elamin_{n}.json").read_text(encoding="utf-8"))["questions"]:
            ct = " ".join(o["text"] for o in q["options"] if o["correct"])
            hit += classify(q["stem"], ct) == label[q["domain"]]
            tot += 1
    print(f"classifier vs el-amin author labels: {hit}/{tot} agree ({hit / tot:.0%})")


if __name__ == "__main__":
    if "--check" not in sys.argv:
        build()
        check_classifier()
    sys.exit(0 if validate() else 1)
