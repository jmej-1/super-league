#!/usr/bin/env python3
"""Super League Desk: which stories are due right now.
These are prompts, not a checklist. Results pick the angle and the shape: a big slate is a
normal NFL Sunday piece, a one-game night with few rostered players can be skipped or folded
into the next story, and a wild night can earn more than one story.
Usage: python3 desk_due.py [data_dir] [now_iso]
Reads data/schedule.txt (kickoffs, UTC) and data/news/week-XX.md (slugs, dates).
Prints a game-state line, then DUE lines (window open, story missing) and NEXT lines.
"""
import sys, os, re, glob
from datetime import datetime, timedelta, timezone

ET = timezone(timedelta(hours=-5))  # Nov-Jan is EST
D = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
now = datetime.fromisoformat(sys.argv[2]).astimezone(ET) if len(sys.argv) > 2 else datetime.now(ET)

games = []
for l in open(os.path.join(D, "schedule.txt")):
    if l.startswith("#") or not l.strip(): continue
    w, ts, a, h, st, *_ = l.strip().split("|")
    games.append((int(w), datetime.strptime(ts, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc).astimezone(ET), a, h, st))

stories = {}
for f in glob.glob(os.path.join(D, "news", "week-*.md")):
    for blk in open(f).read().split("\n=====\n"):
        m = re.search(r"^slug: (.+)$", blk, re.M); d = re.search(r"^date: (.+)$", blk, re.M); k = re.search(r"^kind: (.+)$", blk, re.M)
        if m: stories[m.group(1).strip()] = ((d.group(1).strip() if d else ""), (k.group(1).strip() if k else ""))


team_of = {}
for l in open(os.path.join(D, "players.txt")):
    if l.startswith("#"): continue
    f = l.rstrip("\n").split("|")
    if len(f) > 3: team_of[f[0]] = f[3]
owned = []
for l in open(os.path.join(D, "rosters.txt")):
    if l.startswith("#") or not l.strip(): continue
    for pid in l.split("|")[1].split(","):
        owned.append(pid if not pid.isalpha() else None)
        if pid.isalpha(): team_of["D_" + pid] = pid; owned[-1] = "D_" + pid
def rostered(gs):
    ts = {x for g in gs for x in (g[2], g[3])} | {"WSH" if x == "WAS" else x for g in gs for x in (g[2], g[3])}
    return sum(1 for pid in owned if pid and team_of.get(pid) in ts)

# Current week = week of the next game (or one that kicked off in the last 6 hours).
weeks = sorted({g[0] for g in games})
cur = min([g[0] for g in games if g[1] >= now - timedelta(hours=6)] or [weeks[-1]])
prev = cur - 1

def slots(w):
    """(slug, window_open, window_close, what) for week w."""
    gs = sorted([g for g in games if g[0] == w], key=lambda g: g[1])
    if not gs: return []
    out = []
    sun = [g for g in gs if g[1].weekday() == 6]
    mon = [g for g in gs if g[1].weekday() == 0 and g[1] > gs[0][1]]
    last = gs[-1][1]
    pre = {}
    for g in gs:
        if g[1].weekday() in (2, 3, 4, 5): pre.setdefault(g[1].date(), []).append(g)
    for day, dg in sorted(pre.items()):
        nm = dg[0][1].strftime("%A").lower()
        n = rostered(dg); tag = "" if n >= 4 else "OPTIONAL "
        out.append((f"w{w}-{nm}", dg[0][1] - timedelta(hours=6), dg[0][1], f"{tag}{nm.title()} preview: " + ", ".join(g[2] + "@" + g[3] for g in dg) + f" ({n} rostered players)"))
        out.append((f"w{w}-{nm}-recap", dg[-1][1] + timedelta(hours=4), dg[-1][1] + timedelta(hours=18), f"{tag}{nm.title()} recap (fold into the next piece if thin)"))
    early = [g for g in sun if g[1].hour < 15]
    if early:
        k = early[0][1]
        out.append((f"w{w}-sunday-morning", k - timedelta(hours=5), k, "Sunday slate preview"))
    snf = [g for g in sun if g[1].hour >= 19]
    if snf:
        k = snf[0][1]
        out.append((f"w{w}-sunday-night", k - timedelta(minutes=50), k, f"SNF preview {snf[0][2]}@{snf[0][3]} (Sunday afternoon recap folded in)"))
    for i, g in enumerate(mon):
        out.append((f"w{w}-monday-night" + (f"-{i+1}" if i else ""), g[1] - timedelta(hours=6), g[1], f"MNF preview {g[2]}@{g[3]}"))
    out.append((f"w{w}-weekly-recap", last + timedelta(hours=4), last + timedelta(hours=40), "Weekly recap: awards, race changes, comebacks"))
    return out

# Daily feature: only on days with no NFL games and no other story yet (e.g. a weekly recap). Game days are carried by game stories.
# Evergreen ideas waiting for a slow day live in data/news/drafts.md.
def daily_done(day):
    ds = day.strftime("%Y-%m-%d")
    fixed = {s for w in (prev, cur, cur + 1) for s, *_ in slots(w)}
    return any(d.startswith(ds) and s not in fixed and k == "feature" for s, (d, k) in stories.items())

fin = [g for g in games if g[0] == cur and g[4] == "STATUS_FINAL"]
live = [g for g in games if g[0] == cur and g[4] not in ("STATUS_FINAL", "STATUS_SCHEDULED")]
nxt = sorted([g for g in games if g[4] == "STATUS_SCHEDULED" and g[1] > now], key=lambda g: g[1])
print(f"NOW {now:%a %b %d %I:%M %p} ET | week {cur} | final {len(fin)}/{len([g for g in games if g[0]==cur])}"
      + (f" | live: {', '.join(g[2]+'@'+g[3] for g in live)}" if live else "")
      + (f" | next: {nxt[0][2]}@{nxt[0][3]} {nxt[0][1]:%a %I:%M %p}" if nxt else ""))
nn = 0
for w in (prev, cur):
    sl = sorted(slots(w), key=lambda x: x[1])
    for i, (s, a, b, what) in enumerate(sl):
        if s in stories: continue
        if s.endswith("-recap") and any(x[0] in stories for x in sl[i + 1:]): continue  # folded into a later piece
        if a <= now <= b: print(f"DUE  {s}  ({what}) by {b:%a %I:%M %p}")
        elif now < a and w == cur and nn < 2: nn += 1; print(f"NEXT {s}  opens {a:%a %I:%M %p}  ({what})")
game_day = any(g[1].date() == now.date() for g in games)
told = any(d.startswith(now.strftime("%Y-%m-%d")) for d, k in stories.values())
if not game_day and not told and not daily_done(now): print(f"DUE  daily feature for {now:%a %b %d} (trend, emergence, regression, team or player)")
