"""Pull ESPN play-by-play for every NFL game that has started, trimmed to what the win-probability rebuild needs.
usage: python3 pbp_fetch.py RAW_DIR DATA_DIR
RAW_DIR has the sched_{w}.json files; trimmed games go to DATA_DIR/pbp/{event}.json. A game already saved as final is skipped."""
import sys, os, json, glob, subprocess, tempfile
from concurrent.futures import ThreadPoolExecutor

RAW, D = sys.argv[1], sys.argv[2]
OUT = os.path.join(D, "pbp"); os.makedirs(OUT, exist_ok=True)
URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={}"

todo = []
for f in glob.glob(os.path.join(RAW, "sched_*.json")):
    w = int(os.path.basename(f)[6:-5])
    for e in json.load(open(f)).get("events", []):
        st = e["status"]["type"]["name"]
        if st == "STATUS_SCHEDULED": continue
        p = os.path.join(OUT, f"{e['id']}.json")
        if os.path.exists(p):
            try:
                if json.load(open(p)).get("final"): continue
            except Exception: pass
        c = e["competitions"][0]["competitors"]
        home = next(x for x in c if x["homeAway"] == "home")["team"]["abbreviation"]
        away = next(x for x in c if x["homeAway"] == "away")["team"]["abbreviation"]
        todo.append((w, e["id"], away, home, e["date"], st == "STATUS_FINAL"))

def clock_s(v):
    try: m, s = v.split(":"); return int(m) * 60 + int(float(s))
    except Exception: return 0

def get(job):
    w, eid, away, home, kick, fin = job
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as t: tmp = t.name
    try:
        subprocess.run(["curl", "-sS", "-f", "-m", "60", "--retry", "2", "-o", tmp, URL.format(eid)], check=True, capture_output=True)
        d = json.load(open(tmp))
    except Exception as ex:
        return f"{eid}: {ex}"
    finally:
        try: os.remove(tmp)
        except OSError: pass
    plays = []
    for dr in (d.get("drives") or {}).get("previous", []) + ([d["drives"]["current"]] if (d.get("drives") or {}).get("current") else []):
        for p in dr.get("plays", []):
            plays.append([p.get("wallclock") or "", (p.get("period") or {}).get("number", 1), clock_s((p.get("clock") or {}).get("displayValue", "0:00")),
                          (p.get("type") or {}).get("text", ""), p.get("text", ""), p.get("awayScore", 0), p.get("homeScore", 0),
                          ((p.get("start") or {}).get("team") or {}).get("id", ""), 1 if p.get("isTurnover") else 0])
    seen = set(); uniq = []
    for p in sorted(plays, key=lambda p: (p[0], p[1], -p[2])):
        k = (p[0], p[4])
        if k not in seen: seen.add(k); uniq.append(p)
    tid = {}
    for c in ((d.get("header") or {}).get("competitions") or [{}])[0].get("competitors", []):
        tid[c["team"]["id"]] = c["team"]["abbreviation"]
    json.dump(dict(w=w, id=eid, away=away, home=home, kick=kick, final=fin, tid=tid, plays=uniq), open(os.path.join(OUT, f"{eid}.json"), "w"), separators=(",", ":"))
    return None

with ThreadPoolExecutor(10) as ex:
    errs = [r for r in ex.map(get, todo) if r]
print(f"pbp: {len(todo) - len(errs)} games saved, {len(errs)} failed" + (f" ({errs[:3]})" if errs else ""))
