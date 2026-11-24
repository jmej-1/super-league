#!/usr/bin/env python3
"""Convert raw Sleeper JSON (from Jesse's update.sh zip, or individual uploads) into the pipeline's compact data files.

Usage: python3 ingest.py RAW_DIR DATA_DIR
Recognized raw files (any subset): stats_{w}.json, proj_{w}.json, players.json, matchups_{w}.json,
tx_{w}.json, rosters.json. Scoring comes from DATA_DIR/scoring.txt. Existing compact files are
updated only for the weeks/files present in RAW_DIR.
"""
import sys, os, re, json
from collections import defaultdict

RAW, D = sys.argv[1], sys.argv[2]
# --through N: last week whose games are all finished (Monday night done). Later weeks are stored as
# unplayed even if Sleeper already shows partial points (e.g. after Thursday night).
THROUGH = int(sys.argv[sys.argv.index("--through") + 1]) if "--through" in sys.argv else None
rows = lambda p: [l.rstrip("\n").split("|") for l in open(p) if l.strip() and not l.startswith("#")]
SC = {k: float(v) for k, v in rows(f"{D}/scoring.txt")}
score = lambda s: sum(s.get(k, 0) * v for k, v in SC.items())
valid = lambda i: i.isdigit() or (i.isalpha() and i.isupper() and len(i) <= 3)   # players + team DEFs (skip TEAM_xxx team-total rows)
files = {f: os.path.join(RAW, f) for f in os.listdir(RAW)}
# a failed download comes back as "null" or "[]": treat that week's file as missing so old data is kept, never wiped
wk = lambda pat: sorted(int(m.group(1)) for f in files for m in [re.fullmatch(pat, f)] if m and os.path.getsize(files[f]) > 10)
if THROUGH is None:          # no --through given: the last week where ESPN shows every game final (the week is officially over)
    done_wks = []
    for w in wk(r"sched_(\d+)\.json"):
        try: ev = json.load(open(files[f"sched_{w}.json"])).get("events", [])
        except Exception: ev = []
        if ev and all(e["status"]["type"]["name"] == "STATUS_FINAL" for e in ev): done_wks.append(w)
        else: break
    if done_wks: THROUGH = done_wks[-1]; print(f"auto --through {THROUGH} (every game final per ESPN)")

# ---- actual NFL points for every active player (league scoring) -> nfl_points.txt
NP = defaultdict(dict)
if os.path.exists(f"{D}/nfl_points.txt"):
    for w, i, p in rows(f"{D}/nfl_points.txt"):
        if valid(i): NP[int(w)][i] = float(p)
for w in wk(r"stats_(\d+)\.json"):
    st = json.load(open(files[f"stats_{w}.json"]))
    pts = {i: round(score(s), 2) for i, s in st.items() if valid(i) and ((s.get("off_snp") or 0) + (s.get("def_snp") or 0) + (s.get("st_snp") or 0) >= 1 or score(s) or (not i.isdigit() and s.get("gp")))}   # played = at least one snap; dressed and never got in is DNP
    if pts and (THROUGH is None or w <= THROUGH): NP[w] = pts           # skip unplayed / in-progress weeks
fgm = fy = 0; KB = [[0.0] * 3 for _ in range(3)]; KY = [0.0] * 3      # also fit yards-over-30 per FG in each Sleeper distance bucket
for w in wk(r"stats_(\d+)\.json"):
    if THROUGH is not None and w > THROUGH: continue          # in-progress weeks never move the kicker-distance estimate
    for s in json.load(open(files[f"stats_{w}.json"])).values():
        fgm += s.get("fgm", 0); fy += s.get("fgm_yds_over_30", 0)
        if s.get("fgm") and "fgm_yds_over_30" in s:
            v = [s.get("fgm_30_39", 0), s.get("fgm_40_49", 0), s.get("fgm_50p", 0)]
            for a_ in range(3):
                KY[a_] += v[a_] * s["fgm_yds_over_30"]
                for b_ in range(3): KB[a_][b_] += v[a_] * v[b_]
def _solve(A, y):                                              # 3x3 least squares (normal equations), no numpy needed
    import copy; M = copy.deepcopy(A); y = y[:]
    for c in range(3):
        pv = max(range(c, 3), key=lambda r: abs(M[r][c]))
        if abs(M[pv][c]) < 1e-9: return None
        M[c], M[pv] = M[pv], M[c]; y[c], y[pv] = y[pv], y[c]
        for r in range(3):
            if r != c:
                f_ = M[r][c] / M[c][c]
                for k in range(3): M[r][k] -= f_ * M[c][k]
                y[r] -= f_ * y[c]
    return [y[i] / M[i][i] for i in range(3)]
if NP:
    with open(f"{D}/nfl_points.txt", "w") as f:
        f.write("# week|player_id|league_points (every NFL player who was active; rescored from Sleeper stats)\n")
        for w in sorted(NP):
            for i, p in sorted(NP[w].items()): f.write(f"{w}|{i}|{p}\n")
# kicker distance: Sleeper projections omit fgm_yds_over_30, so use the season's actual yards-over-30 per FG made
kbonus = None; kbk = None
if fgm and len([w for w in wk(r"stats_(\d+)\.json") if THROUGH is None or w <= THROUGH]) >= 3:   # only re-estimate from a real sample of weeks
    kbonus = fy / fgm; kbk = _solve(KB, KY)
    if kbk and not all(x > 0 for x in kbk): kbk = None
    open(f"{D}/kicker_distance.txt", "w").write(f"# avg fgm_yds_over_30 per FG made, 2026 actual (fallback); then yards over 30 per FG made at 30-39, 40-49, 50+ (fit from 2026 actuals)\n{kbonus:.4f}\n" + (f"{kbk[0]:.4f}|{kbk[1]:.4f}|{kbk[2]:.4f}\n" if kbk else ""))
elif os.path.exists(f"{D}/kicker_distance.txt"):
    R_ = rows(f"{D}/kicker_distance.txt"); kbonus = float(R_[0][0])
    if len(R_) > 1 and len(R_[1]) == 3: kbk = [float(x) for x in R_[1]]

# ---- Sleeper projections rescored -> sleeper_proj_{w}.txt
for w in wk(r"proj_(\d+)\.json"):
    pr = json.load(open(files[f"proj_{w}.json"])); out = []
    for i, s in pr.items():
        p = score(s)
        if "fgm_yds_over_30" not in s and s.get("fgm"):
            if kbk and any(k in s for k in ("fgm_30_39", "fgm_40_49", "fgm_50p")):        # this kicker's own projected distance mix
                p += (s.get("fgm_30_39", 0) * kbk[0] + s.get("fgm_40_49", 0) * kbk[1] + s.get("fgm_50p", 0) * kbk[2]) * SC.get("fgm_yds_over_30", 0)
            elif kbonus: p += s["fgm"] * kbonus * SC.get("fgm_yds_over_30", 0)
        if p > 0 and valid(i): out.append((i, round(p, 2)))
    # Sleeper keeps re-running projections after kickoff, so a later pull can differ from what managers saw. Freeze each player
    # at the value from the last pull before his game kicked off: once his game has started, an existing value is never replaced.
    old = {r[0]: float(r[1]) for r in rows(f"{D}/sleeper_proj_{w}.txt")} if os.path.exists(f"{D}/sleeper_proj_{w}.txt") else {}
    if old and f"sched_{w}.json" in files:
        import datetime as _dt
        pulled = _dt.datetime.fromtimestamp(os.path.getmtime(files[f"proj_{w}.json"]), _dt.timezone.utc)
        kick = {}
        try:
            for e in json.load(open(files[f"sched_{w}.json"])).get("events", []):
                k = _dt.datetime.strptime(e["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=_dt.timezone.utc)
                for x in e["competitions"][0]["competitors"]: kick[{"WSH": "WAS"}.get(x["team"]["abbreviation"], x["team"]["abbreviation"])] = k
        except Exception: kick = {}
        if not hasattr(sys.modules[__name__], "_PT"):
            _PT = {}
            if "players.json" in files:
                for i, v in json.load(open(files["players.json"])).items(): _PT[i] = v.get("team")
        tm = lambda i: i if not i.isdigit() else _PT.get(i)
        started = lambda i: tm(i) in kick and kick[tm(i)] <= pulled
        new = dict(out)
        merged = {i: (old[i] if (i in old and started(i)) else new.get(i)) for i in set(old) | set(new)}
        merged.update({i: old[i] for i in old if started(i)})
        out = sorted((i, p) for i, p in merged.items() if p is not None and (i in new or started(i)))
    if out:
        with open(f"{D}/sleeper_proj_{w}.txt", "w") as f:
            f.write(f"# player_id|projected league points (Sleeper projected stats, rescored; Week {w})\n" + "\n".join(f"{i}|{p}" for i, p in sorted(out)) + "\n")

# ---- league matchups -> matchups.txt (replace weeks present)
mw = wk(r"matchups_(\d+)\.json")
if mw:
    keep = [r for r in rows(f"{D}/matchups.txt") if int(r[0]) not in mw]
    new = []
    for w in mw:
        for m in json.load(open(files[f"matchups_{w}.json"])) or []:
            pp = m.get("players_points") or {}; pl = set(m.get("players") or []); st = [i if (not pl or i in pl) else "0" for i in (m.get("starters") or [])]   # a traded player left in the old lineup is an empty slot
            played = bool(pp) and (m.get("points") or 0) != 0 and (THROUGH is None or w <= THROUGH)
            S = ",".join(f"{i}={pp.get(i, 0.0)}" for i in st) if played else ""
            B = ",".join(f"{i}={pp.get(i, 0.0)}" for i in (m.get("players") or []) if i not in st) if played else ""
            new.append([str(w), str(m["roster_id"]), str(m.get("matchup_id")), S, B])
    allr = sorted(keep + new, key=lambda r: (int(r[0]), int(r[1])))
    with open(f"{D}/matchups.txt", "w") as f:
        f.write("# week|roster_id|matchup_id|starters (id=pts, lineup order QB,RB,RB,WR,WR,TE,FLEX,K,DEF; 0=empty)|bench (id=pts)\n")
        for r in allr: f.write("|".join(r) + "\n")

# ---- live week (in progress): starters with points for players whose NFL game is done -> live.txt
if THROUGH and f"matchups_{THROUGH + 1}.json" in files:
    LW = THROUGH + 1
    done = set()
    if f"stats_{LW}.json" in files and os.path.exists(f"{D}/players.txt"):
        team_of = {r[0]: r[3] for r in rows(f"{D}/players.txt")}
        for i, v in json.load(open(files[f"stats_{LW}.json"])).items():
            if v.get("gms_active") or v.get("gp"): done.add(team_of.get(i) or (i if not i.isdigit() else ""))
    done.discard("")
    if f"sched_{LW}.json" in files:          # ESPN says exactly which games are final; stats alone can't tell in-progress from final
        try:
            fin = set()
            for e in json.load(open(files[f"sched_{LW}.json"])).get("events", []):
                if e["status"]["type"]["name"] == "STATUS_FINAL":
                    for x in e["competitions"][0]["competitors"]:
                        t = {"WSH": "WAS"}.get(x["team"]["abbreviation"], x["team"]["abbreviation"]); fin |= {t, f"TEAM_{t}"}
            done = fin
        except Exception: pass
    prog = {}            # games in progress: share of the game played so far (period and clock from ESPN)
    if f"sched_{LW}.json" in files:
        try:
            for e in json.load(open(files[f"sched_{LW}.json"])).get("events", []):
                stt = e["status"]; nm_ = stt["type"]["name"]
                if nm_ in ("STATUS_IN_PROGRESS", "STATUS_END_PERIOD", "STATUS_HALFTIME"):
                    per = int(stt.get("period") or 1); mm, _, ss = (stt.get("displayClock") or "0:00").partition(":")
                    left = int(mm or 0) + int(ss or 0) / 60
                    frac = min(0.99, ((min(per, 4) - 1) * 15 + (15 - left if per <= 4 else 15)) / 60) if nm_ != "STATUS_HALFTIME" else 0.5
                    for x in e["competitions"][0]["competitors"]:
                        tm = {"WSH": "WAS"}.get(x["team"]["abbreviation"], x["team"]["abbreviation"]); prog[tm] = round(max(0.0, frac), 3)
        except Exception: pass
    with open(f"{D}/live.txt", "w") as f:
        f.write(f"# live week|teams whose games are final: {','.join(sorted(done))}\n")
        import datetime as _dtl
        f.write(f"week={LW}\nts={_dtl.datetime.utcfromtimestamp(os.path.getmtime(files['players.json'])).strftime('%Y-%m-%dT%H:%MZ') if 'players.json' in files else ''}\n")
        f.write(f"done={','.join(sorted(done))}\nprog={','.join(f'{k}={v}' for k, v in sorted(prog.items()))}\n")
        if f"stats_{LW}.json" in files and os.path.exists(f"{D}/players.txt"):     # every player whose game is final: feeds this week's replacement slice right away
            tof = {r[0]: r[3] for r in rows(f"{D}/players.txt")}
            npl = {i: round(score(v), 2) for i, v in json.load(open(files[f"stats_{LW}.json"])).items()
                   if valid(i) and (tof.get(i) if i.isdigit() else i) in done
                   and ((v.get("off_snp") or 0) + (v.get("def_snp") or 0) + (v.get("st_snp") or 0) >= 1 or score(v) or (not i.isdigit() and v.get("gp")))}
            f.write("np=" + ",".join(f"{i}={p}" for i, p in sorted(npl.items())) + "\n")
        for m in json.load(open(files[f"matchups_{LW}.json"])) or []:
            pp = m.get("players_points") or {}; pl = set(m.get("players") or [])
            st = [i if (not pl or i in pl) else "0" for i in (m.get("starters") or [])]     # a traded player left in the old lineup is an empty slot
            f.write(f"{m['roster_id']}|{m.get('matchup_id')}|{','.join(i + '=' + str(pp.get(i, 0.0)) for i in st)}\n")
elif THROUGH and os.path.exists(f"{D}/live.txt"):
    os.remove(f"{D}/live.txt")

# ---- NFL kickoff times (ESPN scoreboard) -> schedule.txt  week|kickoff_utc|away|home|status
sw_ = wk(r"sched_(\d+)\.json")
if sw_:
    ESPN = {"WSH": "WAS"}
    keep = [r for r in rows(f"{D}/schedule.txt") if int(r[0]) not in sw_] if os.path.exists(f"{D}/schedule.txt") else []
    new = []
    for w in sw_:
        try: ev = json.load(open(files[f"sched_{w}.json"])).get("events", [])
        except Exception: ev = []
        for e in ev:
            c = e["competitions"][0]["competitors"]; side = {x["homeAway"]: ESPN.get(x["team"]["abbreviation"], x["team"]["abbreviation"]) for x in c}
            new.append([str(w), e["date"], side.get("away", ""), side.get("home", ""), e["status"]["type"]["name"], "1" if e["competitions"][0].get("neutralSite") else "0"])
    with open(f"{D}/schedule.txt", "w") as f:
        f.write("# week|kickoff_utc|away|home|status|neutral (ESPN)\n")
        for r in sorted(keep + new, key=lambda r: (int(r[0]), r[1])): f.write("|".join(r) + "\n")

# ---- each player's NFL team in each week, read from team snap counts (teammates share tm_off/def/st_snp) -> nfl_team_wk.txt
stw = wk(r"stats_(\d+)\.json")
if stw and os.path.exists(f"{D}/players.txt"):
    from collections import Counter as _C
    cur = {r[0]: r[3] for r in rows(f"{D}/players.txt")}
    league = set()
    for r in rows(f"{D}/matchups.txt"):
        for part in r[3:5]: league |= {x.split("=")[0] for x in part.split(",") if x}
    keep = [r for r in rows(f"{D}/nfl_team_wk.txt") if int(r[0]) not in stw] if os.path.exists(f"{D}/nfl_team_wk.txt") else []
    new = []
    for w in stw:
        st = json.load(open(files[f"stats_{w}.json"])); grp = defaultdict(list)
        for i, v in st.items():
            k = (v.get("tm_off_snp"), v.get("tm_def_snp"), v.get("tm_st_snp"))
            if i.isdigit() and k[0]: grp[k].append(i)
        for k, ids in grp.items():
            # two teams can share the exact same snap counts, so a group can hold more than one roster:
            # every team with 3+ current players in it is a real cluster, and its own players keep it
            c = _C(cur.get(i) for i in ids if cur.get(i)); clusters = [t for t, n in c.items() if n >= 3]
            if not clusters: continue          # too few known teammates to name the team
            for i in ids:
                if i not in league: continue
                if cur.get(i) in clusters: new.append([str(w), i, cur[i]])
                elif len(clusters) == 1: new.append([str(w), i, clusters[0]])          # traded since: the one roster he was part of
                # otherwise ambiguous: leave it, and the site falls back to his nearest known week
    with open(f"{D}/nfl_team_wk.txt", "w") as f:
        f.write("# week|player_id|NFL team that week (from shared team snap counts)\n")
        for r in sorted(keep + new, key=lambda r: (int(r[0]), r[1])): f.write("|".join(r) + "\n")

# ---- transactions -> transactions.txt (replace weeks present)
tw = wk(r"tx_(\d+)\.json")
if tw:
    keep = [r for r in rows(f"{D}/transactions.txt") if int(r[0]) not in tw]
    new = []
    for w in tw:
        for t in json.load(open(files[f"tx_{w}.json"])) or []:
            ad = ";".join(f"{i}:{r}" for i, r in (t.get("adds") or {}).items()); dr = ";".join(f"{i}:{r}" for i, r in (t.get("drops") or {}).items())
            ms = t.get("status_updated") or t.get("created") or 0
            when = __import__("datetime").datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%dT%H:%MZ") if ms else ""
            new.append([str(w), t["type"], t["status"], ",".join(str(x) for x in t.get("roster_ids") or []), ad, dr, when])
    with open(f"{D}/transactions.txt", "w") as f:
        f.write("# week|type|status|roster_ids|adds (player:roster;...)|drops (player:roster;...)|processed (UTC)   (newest first within a week, as Sleeper returns them)\n")
        for r in sorted(keep, key=lambda r: int(r[0])) + new: f.write("|".join(r) + "\n")

# ---- rosters
if "rosters.json" in files:
    with open(f"{D}/rosters.txt", "w") as f:
        f.write("# roster_id|player_ids (current rosters)|IR-slot player ids\n")
        RJ = json.load(open(files["rosters.json"]))
        for r in RJ: f.write(f"{r['roster_id']}|{','.join(r.get('players') or [])}|{','.join(r.get('reserve') or [])}\n")
    # IR-slot snapshot for the last finished week (Sleeper only exposes the current IR slot, so record it every update)
    if THROUGH:
        keep = rows(f"{D}/reserve.txt") if os.path.exists(f"{D}/reserve.txt") else []
        # a player sitting in the IR slot once his NFL game has kicked off is locked there for the week, even if he's dropped later:
        # every update during a week records those, and they join that week's snapshot
        import datetime as _dt
        LWk = THROUGH + 1; now_ = _dt.datetime.utcfromtimestamp(os.path.getmtime(files["players.json"])) if "players.json" in files else _dt.datetime.utcnow(); lpath = f"{D}/reserve_live.txt"
        lk = rows(lpath) if os.path.exists(lpath) else []
        if f"sched_{LWk}.json" in files and os.path.exists(f"{D}/players.txt"):
            ko_ = {}
            for e in json.load(open(files[f"sched_{LWk}.json"])).get("events", []):
                for c in e["competitions"][0]["competitors"]: ko_[c["team"]["abbreviation"]] = _dt.datetime.strptime(e["date"], "%Y-%m-%dT%H:%MZ")
            tof = {x[0]: x[3] for x in rows(f"{D}/players.txt")}
            have = {(x[0], x[1], x[2]) for x in lk}
            for r in RJ:
                for i in r.get("reserve") or []:
                    k_ = ko_.get(tof.get(i) if i.isdigit() else i)
                    if k_ and now_ >= k_ and (str(LWk), str(r["roster_id"]), i) not in have: lk.append([str(LWk), str(r["roster_id"]), i])
            with open(lpath, "w") as f:
                f.write("# week|roster_id|player id locked in the IR slot during that week (seen at an update after his game kicked off)\n")
                for x in lk: f.write("|".join(x) + "\n")
        if not any(int(x[0]) == THROUGH for x in keep):          # first snapshot after a week stays; later updates don't overwrite it
            lk_ = defaultdict(set)
            for w_, r_, i_ in lk:
                if int(w_) == THROUGH: lk_[r_].add(i_)
            keep += [[str(THROUGH), str(r["roster_id"]), ",".join(list(r.get("reserve") or []) + sorted(lk_[str(r["roster_id"])] - set(r.get("reserve") or [])))] for r in RJ]
        with open(f"{D}/reserve.txt", "w") as f:
            f.write("# week|roster_id|IR-slot player ids (snapshot taken at the update after that week)\n")
            for x in sorted(keep, key=lambda x: (int(x[0]), int(x[1]))): f.write("|".join(x) + "\n")

# ---- players: every id seen anywhere (league data, NFL points, projections)
if "players.json" in files or os.path.exists(f"{D}/players.txt"):
    old = {r[0]: r for r in rows(f"{D}/players.txt")} if os.path.exists(f"{D}/players.txt") else {}
    nfl = json.load(open(files["players.json"])) if "players.json" in files else {}
    ids = set(old)
    for w in NP: ids |= set(NP[w])
    for fn in os.listdir(D):
        if fn.startswith("sleeper_proj_"): ids |= {r[0] for r in rows(f"{D}/{fn}")}
    for fn in ("matchups.txt", "transactions.txt", "rosters.txt", "draft.txt"):
        if os.path.exists(f"{D}/{fn}"):
            ids |= set(re.findall(r"(?<![\w.])(\d{2,6}|[A-Z]{2,3})(?=[=:,|]|$)", open(f"{D}/{fn}").read().replace("\n", "|")))
    out = ["# player_id|name|pos|nfl_team|injury_status|years_exp   (from Sleeper players file)"]
    for i in sorted(ids, key=lambda x: (not x.isdigit(), int(x) if x.isdigit() else 0, x)):
        if not i.isdigit():
            if len(i) <= 3: out.append(f"{i}|{i} DEF|DEF|{i}||")
            continue
        p = nfl.get(i)
        if p: out.append(f"{i}|{p.get('full_name') or (p.get('first_name', '') + ' ' + p.get('last_name', '')).strip() or i}|{next((x for x in (p.get('fantasy_positions') or []) if x in ('QB', 'RB', 'WR', 'TE', 'K', 'DEF')), p.get('position') or '')}|{p.get('team') or ''}|{p.get('injury_status') or ''}|{'' if p.get('years_exp') is None else p.get('years_exp')}|{','.join(p.get('fantasy_positions') or []) if len(p.get('fantasy_positions') or []) > 1 else ''}")
        elif i in old: out.append("|".join(old[i]))
    open(f"{D}/players.txt", "w").write("\n".join(out) + "\n")
    if nfl:          # injury log: every export adds a snapshot, so each game can show the tag a player carried into it
        import datetime as _dt
        ts = _dt.datetime.utcfromtimestamp(os.path.getmtime(files["players.json"])).strftime("%Y-%m-%dT%H:%MZ")   # the export's clock, as kept by unzip, in UTC
        keep = [l for l in open(f"{D}/inj_snap.txt") if l.strip() and not l.startswith("#") and not l.startswith(ts + "|")] if os.path.exists(f"{D}/inj_snap.txt") else []
        new = [f"{ts}|*|\n"] + [f"{ts}|{k}|{v.get('injury_status')}\n" for k, v in sorted(nfl.items()) if v.get("injury_status") and v.get("team")]
        open(f"{D}/inj_snap.txt", "w").write("# utc_time|player_id|injury_status   (one block per export; '*' marks a snapshot with no tag = healthy)\n" + "".join(sorted(keep + new)))
    bio = ["# player_id|birth_date|years_exp|jersey_number   (from Sleeper players file)"]
    for i in sorted(ids):
        p = nfl.get(i) if i.isdigit() else None
        if p and (p.get("birth_date") or p.get("years_exp") is not None or p.get("number") is not None):
            bio.append(f"{i}|{p.get('birth_date') or ''}|{'' if p.get('years_exp') is None else p.get('years_exp')}|{'' if p.get('number') is None else p.get('number')}")
    open(f"{D}/bio.txt", "w").write("\n".join(bio) + "\n")
# ---- box-score stat lines for every league-rostered player each week -> nfl_stats.txt
KEEP = ["pass_att", "pass_cmp", "pass_yd", "pass_td", "pass_int", "pass_2pt", "rush_att", "rush_yd", "rush_td", "rush_2pt", "rec_tgt", "rec", "rec_yd", "rec_td", "rec_2pt",
        "fum_lost", "fgm", "fga", "fgm_lng", "xpm", "xpa", "sack", "int", "fum_rec", "def_td", "def_st_td", "st_td", "safe", "pts_allow", "yds_allow", "blk_kick"]
sw = wk(r"stats_(\d+)\.json")
if sw and os.path.exists(f"{D}/matchups.txt"):
    lg = defaultdict(set)
    for r in rows(f"{D}/matchups.txt"):
        for part in (r[3], r[4]):
            for x in part.split(","):
                if "=" in x: lg[int(r[0])].add(x.split("=")[0])
    if THROUGH and os.path.exists(f"{D}/live.txt"):        # the week in progress: its starters' lines too
        for l in open(f"{D}/live.txt"):
            if "|" in l and not l.startswith("#"):
                for x in l.rstrip("\n").split("|")[2].split(","):
                    if "=" in x: lg[THROUGH + 1].add(x.split("=")[0])
    # every player who has ever been on a Super League roster gets his line every week, so his page shows what he did
    # in weeks he was a free agent too (before a pickup, after a drop)
    ever = set().union(*lg.values()) if lg else set()
    if os.path.exists(f"{D}/rosters.txt"):
        for r in rows(f"{D}/rosters.txt"): ever |= {y for y in (r[1] + "," + (r[2] if len(r) > 2 else "")).split(",") if y}
    if os.path.exists(f"{D}/draft.txt"):
        for r in rows(f"{D}/draft.txt"): ever.add(r[2])
    for w in sw: lg[w] = lg.get(w, set()) | ever
    old = [r for r in rows(f"{D}/nfl_stats.txt") if int(r[0]) not in sw] if os.path.exists(f"{D}/nfl_stats.txt") else []
    new = []
    for w in sw:
        st = json.load(open(files[f"stats_{w}.json"]))
        for i in sorted(lg.get(w, ())):
            line = st.get(i) or {}
            kv = ";".join(f"{k}={line[k]:g}" for k in KEEP if line.get(k))
            if kv: new.append([str(w), i, kv])
    with open(f"{D}/nfl_stats.txt", "w") as f:
        f.write("# week|player_id|stat=value;... (box-score lines for league-rostered players)\n")
        for r in sorted(old + new, key=lambda r: (int(r[0]), r[1])): f.write("|".join(r) + "\n")

# team names follow Sleeper: a rename shows up everywhere, and data/team_names.txt keeps the history (UTC date|roster|old name|new name)
if "users.json" in files and os.path.exists(f"{D}/league.txt"):
    import datetime as _dt
    tn_ = {u.get("display_name"): ((u.get("metadata") or {}).get("team_name") or "").strip() for u in json.load(open(files["users.json"]))}
    L_ = open(f"{D}/league.txt").read().split("\n"); hist = []
    for k_, l_ in enumerate(L_):
        if l_.startswith("roster="):
            f_ = l_.split("|")
            if len(f_) >= 4 and f_[2] in tn_ and tn_[f_[2]] != f_[3]:
                hist.append(f"{_dt.datetime.utcnow():%Y-%m-%dT%H:%MZ}|{f_[0].split('=')[1]}|{f_[3]}|{tn_[f_[2]]}"); f_[3] = tn_[f_[2]]; L_[k_] = "|".join(f_)
    if hist:
        open(f"{D}/league.txt", "w").write("\n".join(L_))
        new_ = not os.path.exists(f"{D}/team_names.txt")
        with open(f"{D}/team_names.txt", "a") as fh:
            if new_: fh.write("# utc|roster|old name|new name\n")
            fh.write("\n".join(hist) + "\n")
        print("renamed:", hist)

# team logos: when a manager's Sleeper avatar changes, the old logo is kept in data/logos_old (listed in data/logo_history.txt,
# used for his games before the change) and the new one becomes data/logos/{Manager}.png. data/logo_urls.txt remembers each avatar URL.
avd = os.path.join(RAW, "avatars")
if os.path.exists(os.path.join(avd, "urls.txt")) and os.path.exists(f"{D}/league.txt"):
    import datetime as _dt, shutil
    urls = dict(l.split(" ", 1) for l in open(os.path.join(avd, "urls.txt")).read().split("\n") if " " in l)
    urls = {k: v.strip() for k, v in urls.items()}
    mgr = {}
    for l_ in open(f"{D}/league.txt"):
        if l_.startswith("roster="):
            f_ = l_.rstrip("\n").split("|"); mgr[f_[2]] = (f_[0].split("=")[1], f_[1])
    known = {}
    if os.path.exists(f"{D}/logo_urls.txt"):
        for l_ in open(f"{D}/logo_urls.txt"):
            if "|" in l_: u_, url_ = l_.rstrip("\n").split("|", 1); known[u_] = url_
    first = not known; now_ = _dt.datetime.utcnow(); changed = []
    for user, url in urls.items():
        if user not in mgr: continue
        r_, m_ = mgr[user]; img = os.path.join(avd, user + ".img")
        if known.get(user) == url: continue
        if not os.path.exists(img): continue                 # changed, but the new image could not be downloaded: try again next update
        try:
            from PIL import Image, ImageChops
            im = Image.open(img).convert("RGBA"); im.thumbnail((256, 256))
        except Exception: continue
        cur = f"{D}/logos/{m_}.png"
        if first and os.path.exists(cur):                    # first look: only a logo that really differs from the one on file counts as a change
            try:
                from PIL import ImageDraw
                mk = Image.new("L", (48, 48), 0); ImageDraw.Draw(mk).ellipse((6, 6, 42, 42), fill=255)     # compare inside the circle the site shows
                a_ = Image.open(cur).convert("RGB").resize((48, 48)); b_ = im.convert("RGB").resize((48, 48))
                px = [v for v, m in zip(ImageChops.difference(a_, b_).convert("L").getdata(), mk.getdata()) if m]
                diff = sum(px) / max(1, len(px))
            except Exception: diff = 0
            if diff < 25: known[user] = url; continue
        if os.path.exists(cur):
            os.makedirs(f"{D}/logos_old", exist_ok=True); old_ = f"{m_}_{now_:%Y%m%d%H%M}.png"
            shutil.copy(cur, f"{D}/logos_old/{old_}")
            new_ = not os.path.exists(f"{D}/logo_history.txt")
            with open(f"{D}/logo_history.txt", "a") as fh:
                if new_: fh.write("# utc the logo was replaced|roster|old logo file in data/logos_old\n")
                fh.write(f"{now_:%Y-%m-%dT%H:%MZ}|{r_}|{old_}\n")
        im.save(cur); known[user] = url; changed.append(m_)
    open(f"{D}/logo_urls.txt", "w").write("".join(f"{k}|{v}\n" for k, v in sorted(known.items())))
    if changed: print("new logos:", changed)

print("ingested:", {"stats": wk(r"stats_(\d+)\.json"), "proj": wk(r"proj_(\d+)\.json"), "matchups": mw, "tx": tw, "rosters": "rosters.json" in files, "players": "players.json" in files, "kicker_distance": kbonus})
