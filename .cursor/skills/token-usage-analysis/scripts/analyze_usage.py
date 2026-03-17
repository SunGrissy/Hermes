"""Cursor token usage analyzer. No third-party dependencies required."""

import csv
import sys
from datetime import datetime, timedelta, timezone
from collections import defaultdict

UTC8 = timezone(timedelta(hours=8))


def _parse_int(val, default=0):
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _parse_requests(val):
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return max(1, 0)


def load_csv(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("Kind", "") == "Errored, No Charge":
                continue
            total = _parse_int(r.get("Total Tokens"))
            if total <= 0:
                continue
            dt = datetime.fromisoformat(r["Date"].replace("Z", "+00:00"))
            rows.append({
                "date": dt,
                "local": dt.astimezone(UTC8),
                "user": r.get("User", ""),
                "kind": r.get("Kind", ""),
                "model": r.get("Model", ""),
                "max_mode": r.get("Max Mode", "No"),
                "input_w": _parse_int(r.get("Input (w/ Cache Write)")),
                "input_wo": _parse_int(r.get("Input (w/o Cache Write)")),
                "cache": _parse_int(r.get("Cache Read")),
                "output": _parse_int(r.get("Output Tokens")),
                "total": total,
                "requests": _parse_requests(r.get("Requests", "1")),
            })
    return rows


def analyze(rows, focus_user=None):
    if not rows:
        print("No valid records found.")
        return

    print(f"=== Cursor Token Usage Analysis ===")
    print(f"Records: {len(rows)}  |  "
          f"Range: {rows[-1]['local']:%Y-%m-%d %H:%M} ~ {rows[0]['local']:%Y-%m-%d %H:%M}")
    print()

    # --- 1. User summary ---
    users = defaultdict(lambda: {"total": 0, "requests": 0, "count": 0})
    for r in rows:
        u = users[r["user"]]
        u["total"] += r["total"]
        u["requests"] += r["requests"]
        u["count"] += 1

    print("--- 1. USER SUMMARY ---")
    fmt = "{:<40} {:>15} {:>10} {:>8} {:>12}"
    print(fmt.format("User", "Total Tokens", "Requests", "Records", "Avg/Req"))
    for user, s in sorted(users.items(), key=lambda x: -x[1]["total"]):
        avg = s["total"] // max(s["requests"], 1)
        print(fmt.format(user, f'{s["total"]:,}', f'{s["requests"]:,}',
                         f'{s["count"]:,}', f'{avg:,}'))
    print()

    if focus_user is None:
        focus_user = max(users, key=lambda u: users[u]["total"])
    my = [r for r in rows if r["user"] == focus_user]
    total_all = sum(r["total"] for r in my)
    print(f"--- Focus: {focus_user} ({len(my)} records, {total_all:,} tokens) ---")
    print()

    # --- 2. Model breakdown ---
    models = defaultdict(lambda: {"total": 0, "req": 0, "cache": 0, "inw": 0, "out": 0, "n": 0})
    for r in my:
        m = models[r["model"]]
        m["total"] += r["total"]; m["req"] += r["requests"]
        m["cache"] += r["cache"]; m["inw"] += r["input_w"]
        m["out"] += r["output"]; m["n"] += 1

    print("--- 2. MODEL BREAKDOWN ---")
    fmt2 = "{:<42} {:>15} {:>6} {:>10} {:>12} {:>8}"
    print(fmt2.format("Model", "Total Tokens", "%", "Requests", "Avg/Req", "Cache%"))
    for model, s in sorted(models.items(), key=lambda x: -x[1]["total"]):
        pct = s["total"] / total_all * 100
        avg = s["total"] // max(s["req"], 1)
        ti = s["inw"] + s["cache"]
        cp = s["cache"] / ti * 100 if ti else 0
        print(fmt2.format(model, f'{s["total"]:,}', f'{pct:.1f}%',
                          f'{s["req"]:,}', f'{avg:,}', f'{cp:.1f}%'))
    print()

    # --- 3. Daily breakdown ---
    days = defaultdict(lambda: {"total": 0, "req": 0, "n": 0, "models": defaultdict(int)})
    for r in my:
        day = r["local"].strftime("%Y-%m-%d")
        d = days[day]
        d["total"] += r["total"]; d["req"] += r["requests"]; d["n"] += 1
        d["models"][r["model"]] += r["total"]

    print("--- 3. DAILY BREAKDOWN ---")
    fmt3 = "{:<12} {:>15} {:>10} {:>8} {:>12} {}"
    print(fmt3.format("Date", "Total Tokens", "Requests", "Records", "Avg/Req", "Top Model"))
    for day in sorted(days):
        s = days[day]
        avg = s["total"] // max(s["req"], 1)
        top = max(s["models"], key=s["models"].get)
        tp = s["models"][top] / s["total"] * 100 if s["total"] else 0
        print(fmt3.format(day, f'{s["total"]:,}', f'{s["req"]:,}',
                          f'{s["n"]:,}', f'{avg:,}', f'{top} ({tp:.0f}%)'))
    print()

    # --- 4. Hourly pattern (UTC+8) ---
    hours = defaultdict(lambda: {"total": 0, "req": 0, "n": 0})
    for r in my:
        h = r["local"].hour
        hours[h]["total"] += r["total"]; hours[h]["req"] += r["requests"]; hours[h]["n"] += 1

    print("--- 4. HOURLY PATTERN (UTC+8) ---")
    max_h = max((hours[h]["total"] for h in hours), default=1)
    fmt4 = "{:<6} {:>15} {:>10} {:>8} {:>12} {}"
    print(fmt4.format("Hour", "Total Tokens", "Requests", "Records", "Avg/Req", "Bar"))
    for h in range(24):
        s = hours.get(h, {"total": 0, "req": 0, "n": 0})
        avg = s["total"] // max(s["req"], 1)
        bar = "#" * int(s["total"] / max_h * 40) if max_h else ""
        print(fmt4.format(f'{h:02d}:00', f'{s["total"]:,}', f'{s["req"]:,}',
                          f'{s["n"]:,}', f'{avg:,}', bar))
    print()

    # --- 5. Top 20 expensive requests ---
    print("--- 5. TOP 20 MOST EXPENSIVE REQUESTS ---")
    fmt5 = "{:<18} {:<40} {:>12} {:>12} {:>12} {:>10}"
    print(fmt5.format("Date(UTC+8)", "Model", "Total", "Input+CW", "CacheRead", "Output"))
    for r in sorted(my, key=lambda x: -x["total"])[:20]:
        print(fmt5.format(f'{r["local"]:%m-%d %H:%M}', r["model"],
                          f'{r["total"]:,}', f'{r["input_w"]:,}',
                          f'{r["cache"]:,}', f'{r["output"]:,}'))
    print()

    # --- 6. Cache efficiency ---
    tw = sum(r["input_w"] for r in my)
    two = sum(r["input_wo"] for r in my)
    tc = sum(r["cache"] for r in my)
    to = sum(r["output"] for r in my)

    print("--- 6. CACHE EFFICIENCY ---")
    print(f"Total tokens:              {total_all:>15,}")
    print(f"  Input (w/ cache write):  {tw:>15,}  ({tw/total_all*100:.1f}%)")
    print(f"  Input (w/o cache write): {two:>15,}  ({two/total_all*100:.1f}%)")
    print(f"  Cache Read:              {tc:>15,}  ({tc/total_all*100:.1f}%)")
    print(f"  Output:                  {to:>15,}  ({to/total_all*100:.1f}%)")
    cr = tc / (tw + tc) * 100 if (tw + tc) else 0
    print(f"Cache hit ratio:           {cr:.1f}%")
    print(f"Output efficiency:         {to/total_all*100:.2f}% (higher = more productive)")
    print()

    # --- 7. Request size distribution ---
    buckets = [(0, 10_000, "<10K"), (10_000, 50_000, "10-50K"),
               (50_000, 100_000, "50-100K"), (100_000, 500_000, "100-500K"),
               (500_000, 1_000_000, "500K-1M"), (1_000_000, 3_000_000, "1-3M"),
               (3_000_000, float("inf"), "3M+")]
    print("--- 7. REQUEST SIZE DISTRIBUTION ---")
    for lo, hi, label in buckets:
        sub = [r for r in my if lo <= r["total"] < hi]
        st = sum(r["total"] for r in sub)
        pct = st / total_all * 100 if total_all else 0
        print(f"  {label:<10} {len(sub):>5} records  {st:>15,} tokens  ({pct:>5.1f}%)")
    print()

    # --- 8. Max Mode ---
    print("--- 8. MAX MODE ---")
    mm = defaultdict(lambda: {"total": 0, "req": 0, "n": 0})
    for r in my:
        mm[r["max_mode"]]["total"] += r["total"]
        mm[r["max_mode"]]["req"] += r["requests"]; mm[r["max_mode"]]["n"] += 1
    for mode, s in sorted(mm.items(), key=lambda x: -x[1]["total"]):
        pct = s["total"] / total_all * 100
        print(f'  {mode:<10} {s["n"]:>6} records  {s["total"]:>15,} tokens  ({pct:>5.1f}%)')
    print()

    # --- 9. Session analysis ---
    print("--- 9. SESSION ANALYSIS (gap > 30min = new session) ---")
    my_sorted = sorted(my, key=lambda x: x["date"])
    sessions = []
    cur = {"start": my_sorted[0]["date"], "end": my_sorted[0]["date"],
           "total": 0, "req": 0, "n": 0}
    for r in my_sorted:
        gap = (r["date"] - cur["end"]).total_seconds()
        if gap > 1800:
            sessions.append(cur)
            cur = {"start": r["date"], "end": r["date"], "total": 0, "req": 0, "n": 0}
        cur["end"] = r["date"]
        cur["total"] += r["total"]; cur["req"] += r["requests"]; cur["n"] += 1
    sessions.append(cur)

    stokens = sorted([s["total"] for s in sessions], reverse=True)
    print(f"Sessions: {len(sessions)}  |  "
          f"Avg: {sum(stokens)//len(sessions):,}  |  "
          f"Median: {stokens[len(stokens)//2]:,}")
    print()
    print("Top 10 heaviest sessions:")
    fmt9 = "{:<18} {:>10} {:>15} {:>10} {:>8}"
    print(fmt9.format("Start(UTC+8)", "Duration", "Tokens", "Requests", "Records"))
    for s in sorted(sessions, key=lambda x: -x["total"])[:10]:
        dur = int((s["end"] - s["start"]).total_seconds() / 60)
        local_start = s["start"].astimezone(UTC8)
        print(fmt9.format(f'{local_start:%m-%d %H:%M}', f'{dur}min',
                          f'{s["total"]:,}', f'{s["req"]:,}', f'{s["n"]:,}'))
    print()

    # --- 10. Kind breakdown ---
    print("--- 10. KIND BREAKDOWN ---")
    kinds = defaultdict(lambda: {"total": 0, "req": 0, "n": 0})
    for r in my:
        kinds[r["kind"]]["total"] += r["total"]
        kinds[r["kind"]]["req"] += r["requests"]; kinds[r["kind"]]["n"] += 1
    for kind, s in sorted(kinds.items(), key=lambda x: -x[1]["total"]):
        pct = s["total"] / total_all * 100
        print(f'  {kind:<25} {s["n"]:>6} records  {s["total"]:>15,} tokens  ({pct:>5.1f}%)')
    print()

    # --- Recommendations ---
    print("=== OPTIMIZATION SIGNALS ===")
    print()

    opus_t = sum(s["total"] for m, s in models.items() if "opus" in m.lower())
    opus_p = opus_t / total_all * 100 if total_all else 0
    big = [r for r in my if r["total"] >= 1_000_000]
    big_t = sum(r["total"] for r in big)
    big_p = big_t / total_all * 100 if total_all else 0
    late = sum(hours.get(h, {"total": 0})["total"] for h in [0, 1, 2, 3, 4, 5])
    late_p = late / total_all * 100 if total_all else 0
    max_t = mm.get("Yes", {"total": 0})["total"]
    max_p = max_t / total_all * 100 if total_all else 0
    od = kinds.get("On-Demand", {"total": 0})["total"]
    od_p = od / total_all * 100 if total_all else 0
    out_p = to / total_all * 100 if total_all else 0

    signals = [
        f"Opus usage:       {opus_p:5.1f}%  {'[HIGH - consider Sonnet for routine tasks]' if opus_p > 70 else '[OK]'}",
        f">=1M requests:    {big_p:5.1f}%  {'[HIGH - shorten sessions]' if big_p > 50 else '[OK]'}",
        f"Cache hit ratio:  {cr:5.1f}%",
        f"Output efficiency: {out_p:4.2f}%  {'[LOW - most tokens spent re-feeding context]' if out_p < 1 else '[OK]'}",
        f"Late night(00-06):{late_p:5.1f}%  {'[NOTABLE]' if late_p > 10 else '[OK]'}",
        f"Max Mode usage:   {max_p:5.1f}%  {'[HIGH - evaluate necessity]' if max_p > 30 else '[OK]'}",
        f"On-Demand ratio:  {od_p:5.1f}%  {'[HIGH - plan quota mostly exceeded]' if od_p > 80 else '[OK]'}",
    ]
    for s in signals:
        print(f"  {s}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: py {sys.argv[0]} <csv_path> [user_email]")
        sys.exit(1)
    data = load_csv(sys.argv[1])
    user = sys.argv[2] if len(sys.argv) > 2 else None
    analyze(data, user)
