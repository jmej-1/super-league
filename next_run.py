"""Next automatic update time (Eastern). Built from the real NFL schedule:
- for every kickoff time (each slate): an hour before, at about halftime (+1:20) and right after it ends (+3:15)
- otherwise every 8 hours (2 AM, 10 AM, 6 PM), plus 3:30 AM Wednesday right after waivers clear
The play-by-play rebuilds everything that happened in between, so updates during games don't need to be frequent.
Prints an ISO time with the zone in brackets, ready for send_later."""
import datetime as dt, glob, json, os
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York"); UTC = dt.timezone.utc
now = dt.datetime.now(ET)

kicks = set()
raws = sorted(glob.glob("/tmp/raw_*"), key=os.path.getmtime)
if raws:
    for f in glob.glob(os.path.join(raws[-1], "sched_*.json")):
        try:
            for e in json.load(open(f)).get("events", []):
                k = dt.datetime.strptime(e["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC).astimezone(ET)
                if now - dt.timedelta(hours=4) < k < now + dt.timedelta(days=8): kicks.add(k)
        except Exception: pass

cand = []; over = []
# a game that should be over but isn't (overtime, long game): check again in 20 minutes
if raws:
    for f in glob.glob(os.path.join(raws[-1], "sched_*.json")):
        try:
            for e in json.load(open(f)).get("events", []):
                k = dt.datetime.strptime(e["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC).astimezone(ET)
                if e["status"]["type"]["name"] == "STATUS_IN_PROGRESS" and now > k + dt.timedelta(minutes=190):
                    over.append(now + dt.timedelta(minutes=20))
        except Exception: pass
for k in kicks:
    cand += [k - dt.timedelta(minutes=60), k + dt.timedelta(minutes=80), k + dt.timedelta(minutes=195)]
day = now.replace(minute=0, second=0, microsecond=0)
for d in range(0, 8):
    dd = day + dt.timedelta(days=d)
    for h in (2, 10, 18):
        cand.append(dd.replace(hour=h, minute=7))
    if dd.weekday() == 2: cand.append(dd.replace(hour=3, minute=30))      # waivers clear early Wednesday (midnight Pacific)
game = sorted(c for c in cand if c.minute != 7)
cand = sorted(c for c in cand if not (c.minute == 7 and any(abs((c - g).total_seconds()) < 5400 for g in game)))   # a routine run next to a game run is dropped
keep = []
for c in cand:                                   # slates 20 minutes apart (4:05 and 4:25) share one run
    if not keep or (c - keep[-1]).total_seconds() >= 40 * 60 or (c.weekday() == 2 and c.hour == 3): keep.append(c)
keep = [c for c in keep if c > now + dt.timedelta(minutes=10)]
nxt = min(keep[:1] + over)
print(nxt.strftime("%Y-%m-%dT%H:%M:00") + "[America/New_York]")
