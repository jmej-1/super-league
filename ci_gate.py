#!/usr/bin/env python3
"""Should this scheduled run do a full update? Every 15 minutes while any NFL game is on (from data/schedule.txt),
otherwise when nothing has been pushed for 90+ minutes. Prints run=1 or run=0 (and writes it to $GITHUB_OUTPUT when set)."""
import os, sys
from datetime import datetime, timedelta, timezone
now = datetime.now(timezone.utc)
live = False
try:
    for l in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "schedule.txt")):
        if l.startswith("#") or not l.strip(): continue
        f = l.split("|"); k = datetime.strptime(f[1], "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
        if k - timedelta(minutes=75) <= now <= k + timedelta(hours=4, minutes=15): live = True; break   # from an hour before kickoff (inactives) to final
except Exception:
    live = True
# Off game days: only when nobody has pushed anything (Jesse and Claude included) for 90+ minutes.
# Any push already rebuilds the site, so the bot just fills the quiet gaps.
stale = True
try:
    import subprocess
    t = subprocess.run(["git", "log", "-1", "--format=%cI"], capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__))).stdout.strip()
    stale = now - datetime.fromisoformat(t) >= timedelta(minutes=90)
except Exception:
    pass
run = live or stale or os.environ.get("FORCE") == "1"
print(f"run={int(run)} live={int(live)}")
if os.environ.get("GITHUB_OUTPUT"):
    open(os.environ["GITHUB_OUTPUT"], "a").write(f"run={int(run)}\n")
