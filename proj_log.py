"""Log every change in the current week's Sleeper projections, so charts can later be redrawn with the starters who
actually played, using what each of them was projected for at every moment of the week.
Format of data/proj_hist.txt: utc|week|player_id|projected points (a row only when the number changes)."""
import os, sys, datetime
D = sys.argv[1] if len(sys.argv) > 1 else "data"
rows = lambda p: [l.rstrip("\n").split("|") for l in open(p) if l.strip() and not l.startswith("#")]
last_done = max([int(r[0]) for r in rows(f"{D}/matchups.txt") if len(r) > 3 and r[3]] or [0])
w = last_done + 1
src = f"{D}/sleeper_proj_{w}.txt"
if not os.path.exists(src): sys.exit(0)
cur = {r[0]: r[1] for r in rows(src)}
H = f"{D}/proj_hist.txt"; prev = {}
if os.path.exists(H):
    for r in rows(H):
        if int(r[1]) == w: prev[r[2]] = r[3]
ts = sys.argv[2] if len(sys.argv) > 2 else datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
new = [(i, v) for i, v in cur.items() if prev.get(i) != v]
if new:
    exists = os.path.exists(H)
    with open(H, "a") as f:
        if not exists: f.write("# utc|week|player_id|projected league points (a row each time a projection changes)\n")
        for i, v in new: f.write(f"{ts}|{w}|{i}|{v}\n")
print(f"proj_log week {w}: {len(new)} changes")
