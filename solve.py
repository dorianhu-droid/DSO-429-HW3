#!/usr/bin/env python3
"""DSO 429 HW3 - Hourly Quiz solver.

Downloads questions.csv, answers every round that has no file in answers/
yet, writes answers/round-XXXX.json, and (with --push) commits and pushes.

Every question type is ordinary business arithmetic, so each answer is
computed in Python and matched to the closest option. No API key needed.

Usage (run from inside your DSO-429-HW3 repo folder):
    python3 solve.py --check        # score yourself against practice keys 1-48
    python3 solve.py                # write missing or out-of-date round files
    python3 solve.py --push         # write missing files, then git commit + push
    python3 solve.py --all --push   # rewrite every round file, then push
"""
import argparse
import csv
import datetime as dt
import io
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/FaisalXL/dso429-hourly-quiz-2/main/"
QUESTIONS_URL = BASE + "questions.csv"
KEYS_URL = BASE + "practice_keys.csv"
LETTERS = "ABCD"
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def fetch_csv(url):
    with urllib.request.urlopen(url, timeout=60) as resp:
        text = resp.read().decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def nums(text):
    """All numbers in a string, with $ and commas stripped."""
    return [float(n.replace(",", "")) for n in re.findall(r"-?\d[\d,]*(?:\.\d+)?", text)]


def to_number(option):
    found = nums(option)
    return found[0] if found else None


# ---------- one function per question type: returns the correct value ----------

def compound(q):
    p, rate, years = nums(q)
    return p * (1 + rate / 100) ** years


def gross_margin(q):
    revenue, cogs = nums(q)
    return (revenue - cogs) / revenue * 100


def next_in_series(q):
    s = nums(q)
    diffs = {s[i + 1] - s[i] for i in range(len(s) - 1)}
    if len(diffs) == 1:                       # arithmetic: 13, 18, 23 ...
        return s[-1] + diffs.pop()
    ratios = {round(s[i + 1] / s[i], 9) for i in range(len(s) - 1) if s[i]}
    if len(ratios) == 1:                      # geometric: 2, 4, 8 ...
        return s[-1] * ratios.pop()
    second = {(s[i + 2] - s[i + 1]) - (s[i + 1] - s[i]) for i in range(len(s) - 2)}
    if len(second) == 1:                      # differences grow steadily
        return s[-1] + (s[-1] - s[-2]) + second.pop()
    raise ValueError("unrecognised series")


def discount(q):
    price, pct = nums(q)
    return price * (1 - pct / 100)


def pct_change(q):
    old, new = nums(q)
    return (new - old) / old * 100


def break_even(q):
    fixed, price, variable = nums(q)
    return round(fixed / (price - variable))


def ratio_split(q):
    budget, a, b = nums(q)
    return budget * a / (a + b)


def weighted_avg(q):
    n1, avg1, n2, avg2 = nums(q)
    return (n1 * avg1 + n2 * avg2) / (n1 + n2)


def fx(q):
    usd, rate = nums(q)
    return usd * rate


def probability(q):
    billing, technical, account = nums(q)
    return billing / (billing + technical + account) * 100


def revenue(q):
    units, price = nums(q)
    return units * price


def settle_date(q):
    m = re.search(r"signed on (\d+) (\w+) (\d{4}) has a (\d+)-day", q)
    day, month, year, days = m.groups()
    start = dt.date(int(year), MONTHS.index(month) + 1, int(day))
    end = start + dt.timedelta(days=int(days))
    return f"{end.day} {MONTHS[end.month - 1]} {end.year}"


RULES = [
    ("compounded annually", compound),
    ("gross margin", gross_margin),
    ("series runs", next_in_series),
    ("is discounted by", discount),
    ("percentage change", pct_change),
    ("break even", break_even),
    ("in the ratio", ratio_split),
    ("overall average order value", weighted_avg),
    ("converted to euros", fx),
    ("probability", probability),
    ("total revenue", revenue),
    ("settlement period", settle_date),
]


def answer(row):
    """Return (letter, confident) for one question row."""
    q = row["question_text"]
    options = [row["option_a"], row["option_b"], row["option_c"], row["option_d"]]
    for phrase, fn in RULES:
        if phrase in q.lower():
            target = fn(q)
            if isinstance(target, str):                     # dates: exact text match
                for i, opt in enumerate(options):
                    if opt.strip() == target:
                        return LETTERS[i], True
                return "A", False
            values = [to_number(o) for o in options]
            gaps = [abs(v - target) if v is not None else float("inf") for v in values]
            best = min(range(4), key=lambda i: gaps[i])
            # confident if the best option is within rounding distance
            return LETTERS[best], gaps[best] <= max(0.051, abs(target) * 0.001)
    return "A", False                                       # unknown question type


def solve_round(rows):
    answers, unsure = {}, []
    for r in sorted(rows, key=lambda r: int(r["q_index"])):
        letter, ok = answer(r)
        answers[f"q{int(r['q_index'])}"] = letter
        if not ok:
            unsure.append(f"q{r['q_index']}: {r['question_text'][:70]}")
    return answers, unsure


def group_by_round(rows):
    rounds = {}
    for r in rows:
        rounds.setdefault(int(r["round_id"]), []).append(r)
    return rounds


def check(rounds):
    keys = {(int(k["round_id"]), int(k["q_index"])): k["answer"] for k in fetch_csv(KEYS_URL)}
    right = total = 0
    for rid in sorted(rounds):
        if rid > 48:
            continue
        answers, _ = solve_round(rounds[rid])
        for qname, letter in answers.items():
            total += 1
            expected = keys.get((rid, int(qname[1:])))
            if letter == expected:
                right += 1
            else:
                print(f"  round {rid} {qname}: got {letter}, key says {expected}")
    print(f"Practice score: {right}/{total} ({right / total:.1%})")


def git(*args):
    subprocess.run(["git", *args], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="score against practice keys and stop")
    ap.add_argument("--push", action="store_true", help="git commit and push new files")
    ap.add_argument("--all", action="store_true", help="rewrite files that already exist")
    args = ap.parse_args()

    rounds = group_by_round(fetch_csv(QUESTIONS_URL))
    if args.check:
        check(rounds)
        return

    out_dir = Path("answers")
    out_dir.mkdir(exist_ok=True)
    written = []
    for rid in sorted(rounds):
        path = out_dir / f"round-{rid:04d}.json"
        if len(rounds[rid]) != 25:
            print(f"round {rid}: only {len(rounds[rid])} questions so far, skipping")
            continue
        answers, unsure = solve_round(rounds[rid])
        content = json.dumps({"round_id": rid, "answers": answers}, indent=2) + "\n"
        # Skip only if the file already holds exactly these answers; a stale or
        # wrong file gets overwritten.
        if path.exists() and path.read_text() == content and not args.all:
            continue
        path.write_text(content)
        written.append(path)
        for u in unsure:
            print(f"round {rid} needs a look -> {u}")

    print(f"Wrote {len(written)} round file(s).")
    if args.push and written:
        git("add", *[str(p) for p in written])
        git("commit", "-m", f"Answers for {len(written)} round(s)")
        git("push", "origin", "main")
        print("Pushed to GitHub.")


if __name__ == "__main__":
    sys.exit(main())
