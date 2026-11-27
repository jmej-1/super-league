#!/usr/bin/env python3
"""Super League stats pipeline.

Usage:  python3 superleague.py [data_dir] [out_dir]
Reads only the plain-text files in data/ and writes every stats doc to out/.
Nothing league-specific is typed into this file: teams, names, scores, schedule,
trades, replacement levels, points-per-win and model tuning all come from the data.
The CONFIG block holds the few *model assumptions* that can't be fit from one
season of data (they are documented in the docs they affect).
"""
import sys, os, json, math, re
from collections import defaultdict, Counter
import numpy as np
from scipy.stats import norm

CONFIG = dict(
    sims=1000000, seed=11,          # 95% sim error about ±0.1 pts on any displayed %, runs in ~3 s
    injury_mult={"Doubtful": 0.2, "Questionable": 0.85},   # Out/IR/bye players already have no Sleeper projection
    corr_inflation=None,          # None = calibrated from backtest each run
    pickup_min_gain=3.0, pickup_rank=2, pickup_max=2,   # waiver logic in projections
    repl_group=5,
    trade_sims=100000,            # sims per trade in the forward trade analysis (common random numbers)                 # replacement = avg of the N players just below the starting line
    blend_min_gain=0.02,          # own-production blend only used if it beats Sleeper alone by >2% RMSE in the backtest
    out_later_mult=0.6,           # player listed Out this week: chance he's back in later weeks
)
POSLIST = ["QB", "RB", "WR", "TE", "K", "DEF"]

# ----------------------------------------------------------------------------- load
def rows(path):
    for l in open(path):
        l = l.rstrip("\n")
        if l and not l.startswith("#"):
            yield l.split("|")

def load(D):
    L = {"rosters": {}}
    for l in open(f"{D}/league.txt"):
        l = l.strip()
        if not l or l.startswith("#"): continue
        k, v = l.split("=", 1)
        if k == "roster":
            r, real, user, team = v.split("|"); L["rosters"][int(r)] = dict(name=real, user=user, team=team)
        else: L[k] = v
    for k in ("teams", "regular_season_weeks", "playoff_teams", "playoff_byes", "playoff_week_start", "trade_deadline"):
        L[k] = int(L[k])
    L["lineup"] = L["lineup"].split(","); L["flex"] = set(L["flex"].split(","))
    M = {r: v["name"] for r, v in L["rosters"].items()}
    # players
    PL = {}
    for p in rows(f"{D}/players.txt"):
        i, name, pos, team, inj, exp = p[:6]; pall = p[6].split(",") if len(p) > 6 and p[6] else []
        PL[i] = dict(name=name, pos=pos or "DEF", team=team or None, inj=inj or None, exp=int(exp) if exp else None, pall=pall)
    # matchups
    W = defaultdict(dict); FUT = defaultdict(dict)
    def parse(s):
        return [(a, float(b)) for a, b in (x.split("=") for x in s.split(",") if x)] if s else []
    for wk, r, mid, S, B in rows(f"{D}/matchups.txt"):
        wk, r, mid = int(wk), int(r), int(mid)
        if S: W[wk][r] = dict(mid=mid, S=parse(S), B=parse(B))
        else: FUT[wk][r] = mid
    weeks = sorted(W)
    G = {}
    for wk in weeks:
        sc = {r: round(sum(p for _, p in d["S"]), 2) for r, d in W[wk].items()}
        byid = defaultdict(list)
        for r, d in W[wk].items(): byid[d["mid"]].append(r)
        G[wk] = dict(scores=sc, pairs=[tuple(v) for v in byid.values()])
    fut = {}
    for wk in sorted(FUT):
        byid = defaultdict(list)
        for r, m in FUT[wk].items(): byid[m].append(r)
        fut[wk] = [tuple(v) for v in byid.values()]
    draft = [dict(pick=int(p), r=int(r), id=i, name=n, pos=pos) for p, r, i, n, pos in rows(f"{D}/draft.txt")]
    for d in draft:
        PL.setdefault(d["id"], dict(name=d["name"], pos=d["pos"], team=None, inj=None, exp=None))
    tx = []
    for row in rows(f"{D}/transactions.txt"):
        wk, typ, st, rs, adds, drops = row[:6]; when = row[6] if len(row) > 6 else ""
        f = lambda s: [(a, int(b)) for a, b in (x.split(":") for x in s.split(";") if x)]
        tx.append(dict(w=int(wk), type=typ, status=st, rosters=[int(x) for x in rs.split(",")], adds=f(adds), drops=f(drops), when=when))
    rost = {}; reserve = {}
    for x in rows(f"{D}/rosters.txt"):
        rost[int(x[0])] = [i for i in x[1].split(",") if i]
        reserve[int(x[0])] = [i for i in (x[2].split(",") if len(x) > 2 else []) if i]
    reserve_wk = defaultdict(dict)
    if os.path.exists(f"{D}/reserve.txt"):
        for w, r, ids in rows(f"{D}/reserve.txt"): reserve_wk[int(w)][int(r)] = [i for i in ids.split(",") if i]
    byes = {int(w): [t for t in teams.split(",") if t] for w, teams in rows(f"{D}/byes.txt")}
    vegas = {}
    for fn in os.listdir(D):
        m = re.match(r"vegas_(\d+)\.txt", fn)
        if m: vegas[int(m.group(1))] = [(a, h, f, float(s), float(t)) for a, h, f, s, t in rows(f"{D}/{fn}")]
    NP = defaultdict(dict)
    if os.path.exists(f"{D}/nfl_points.txt"):
        for w, i, p in rows(f"{D}/nfl_points.txt"): NP[int(w)][i] = float(p)
    LIVE = None
    if os.path.exists(f"{D}/live.txt"):
        LIVE = dict(week=None, done=set(), lu={}, mid={})
        for l in open(f"{D}/live.txt"):
            l = l.strip()
            if not l or l.startswith("#"): continue
            if l.startswith("week="): LIVE["week"] = int(l[5:]); continue
            if l.startswith("done="): LIVE["done"] = set(x for x in l[5:].split(",") if x); continue
            if l.startswith("ts="): LIVE["ts"] = l[3:].strip(); continue
            if l.startswith("np="): LIVE["np"] = {k: float(v) for k, v in (x.split("=") for x in l[3:].split(",") if x)}; continue
            if l.startswith("prog="): LIVE["prog"] = {k: float(v) for k, v in (x.split("=") for x in l[5:].split(",") if x)}; continue
            r, mid, st = l.split("|"); LIVE["mid"][int(r)] = mid
            LIVE["lu"][int(r)] = [(a, float(b)) for a, b in (x.split("=") for x in st.split(",") if x)]
    NS = defaultdict(dict)
    if os.path.exists(f"{D}/nfl_stats.txt"):
        for w, i, kv in rows(f"{D}/nfl_stats.txt"): NS[int(w)][i] = {k: float(v) for k, v in (x.split("=") for x in kv.split(";") if x)}
    SP = {}
    for fn in os.listdir(D):
        m = re.fullmatch(r"sleeper_proj_(\d+)\.txt", fn)
        if m: SP[int(m.group(1))] = {i: float(p) for i, p in rows(f"{D}/{fn}")}
    phist = defaultdict(lambda: defaultdict(list))       # week -> player -> [(utc, projection)] in time order
    if os.path.exists(f"{D}/proj_hist.txt"):
        for ts, w, i, v in rows(f"{D}/proj_hist.txt"): phist[int(w)][i].append((ts, float(v)))
    projlog = {}
    for fn in os.listdir(D):
        m = re.fullmatch(r"teamproj_(\d+)\.txt", fn)
        if m: projlog[int(m.group(1))] = {int(r): (float(mu), float(sd)) for r, mu, sd in rows(f"{D}/{fn}")}
    lineslog = {}
    for fn in os.listdir(D):
        m = re.fullmatch(r"lines_(\d+)\.txt", fn)
        if m: lineslog[int(m.group(1))] = [(int(f_), int(d_), float(sp), float(tt)) for f_, d_, sp, tt in rows(f"{D}/{fn}")]
    notes = {}
    for fn in os.listdir(D):
        m = re.match(r"notes_(\w+)\.txt", fn)
        if m: notes[m.group(1)] = open(f"{D}/{fn}").read().strip()
    TW = {}                            # (week, player) -> NFL team that week
    if os.path.exists(f"{D}/nfl_team_wk.txt"):
        for w, i, t in rows(f"{D}/nfl_team_wk.txt"): TW[(int(w), i)] = t
    sched = defaultdict(list)          # week -> [(kickoff_utc, away, home, status)]
    if os.path.exists(f"{D}/schedule.txt"):
        for r_ in rows(f"{D}/schedule.txt"):
            w, k, aw, hm, st = r_[:5]; sched[int(w)].append((k, aw, hm, st, (r_[5] if len(r_) > 5 else "0") == "1"))
    NEWS = []
    if os.path.isdir(f"{D}/news"):
        for fn in sorted(os.listdir(f"{D}/news")):
            if not (fn.startswith("week-") and fn.endswith(".md")): continue
            for part in open(f"{D}/news/{fn}").read().split("\n=====\n"):      # one file per week, stories split by =====
                head, sep, body = part.partition("\n---\n")
                if not sep: continue
                m = {k.strip(): v.strip() for k, v in (l.split(":", 1) for l in head.splitlines() if ":" in l and not l.startswith("#"))}
                m["slug"] = m.get("slug") or fn[:-3]; m["body"] = body.strip(); m["week"] = int(m.get("week", 0))
                m["teams"] = [int(x) for x in m.get("teams", "").split(",") if x.strip()]
                NEWS.append(m)
    if os.path.exists(f"{D}/ir_fix.txt"):     # checked by hand in Sleeper: wins over the snapshot (week|roster_id|player ids, blank = nobody)
        for x in rows(f"{D}/ir_fix.txt"): reserve_wk[int(x[0])][int(x[1])] = [i for i in (x[2] if len(x) > 2 else "").split(",") if i]
    reserve_live = defaultdict(lambda: defaultdict(set))    # week -> roster -> IR players locked once their game kicked off
    if os.path.exists(f"{D}/reserve_live.txt"):
        for w, r, i in rows(f"{D}/reserve_live.txt"): reserve_live[int(w)][int(r)].add(i)
    LIVE["reserve_live"] = reserve_live
    return dict(TW=TW, sched=sched, NEWS=NEWS, LIVE=LIVE, NS=NS, L=L, M=M, PL=PL, W=W, G=G, weeks=weeks, fut=fut, draft=draft, tx=tx, rost=rost, reserve=reserve, reserve_wk=reserve_wk, byes=byes, vegas=vegas, notes=notes, projlog=projlog, lineslog=lineslog, NP=NP, SP=SP, phist=phist)

# ----------------------------------------------------------------------------- helpers
class Ctx:
    def __init__(s, d):
        s.__dict__.update(d)
        s.R = sorted(s.M)
        s.last = max(s.weeks); s.nxt = s.last + 1
        s.pos = lambda i: s.PL.get(i, {}).get("pos") or "DEF"
        s.nm = lambda i: (i + " DEF") if not i.isdigit() else s.PL.get(i, {}).get("name", "#" + i)
        s.slots = [s.L["flex"] if x == "FLEX" else {x} for x in s.L["lineup"]]
        s.dpick = {d["id"]: d["pick"] for d in s.draft}
        s.dby = {d["id"]: d["r"] for d in s.draft}
        # weekly points for any player on any roster (starter or bench)
        s.WP = defaultdict(dict); s.ROST = {}
        for w in s.weeks:
            for r, d in s.W[w].items():
                s.ROST[(w, r)] = [i for i, _ in d["S"] + d["B"] if i != "0"]
                for i, p in d["S"] + d["B"]:
                    if i != "0": s.WP[w][i] = p
        allsc = np.array([s.G[w]["scores"][r] for w in s.weeks for r in s.R])
        s.sigma = allsc.std(ddof=1)
        s.wpp = norm.pdf(0) / (s.sigma * math.sqrt(2)); s.ppw = 1 / s.wpp
        s.trades = derive_trades(s)
        s.repl = replacement(s, s.last)

    def best(s, players):
        """players: list of (id,pos,pts) -> (total, chosen ids) best legal lineup"""
        pool = list(players); tot = 0; ch = []
        for ok in s.slots:
            c = [x for x in pool if x[1] in ok]
            if c:
                b = max(c, key=lambda x: x[2]); pool.remove(b); tot += b[2]; ch.append(b[0])
        return tot, ch

    def record(s, upto=None):
        W = Counter(); PF = Counter(); PA = Counter()
        for w in s.weeks:
            if upto and w > upto: continue
            g = s.G[w]
            for a, b in g["pairs"]:
                sa, sb = g["scores"][a], g["scores"][b]
                PF[a] += sa; PF[b] += sb; PA[a] += sb; PA[b] += sa
                if round(sa, 2) > round(sb, 2): W[a] += 1
                elif round(sb, 2) > round(sa, 2): W[b] += 1
                else: W[a] += 0.5; W[b] += 0.5          # tie to the hundredth: half a win each (standings, sims and tiebreaks all use this)
        return W, PF, PA

    def ties(s, upto=None):
        T = Counter()
        for w in s.weeks:
            if upto and w > upto: continue
            g = s.G[w]
            for a, b in g["pairs"]:
                if round(g["scores"][a], 2) == round(g["scores"][b], 2): T[a] += 1; T[b] += 1
        return T

    def rec(s, r, upto=None):
        """W-L, or W-L-T once a team has a tie."""
        W, _, _ = s.record(upto); T = s.ties(upto); n = len([w for w in s.weeks if not upto or w <= upto])
        w_ = int(W[r] - T[r] / 2); t = T[r]; l = n - w_ - t
        return f"{w_}-{l}-{t}" if t else f"{w_}-{l}"

    def pos_median(s, w):
        bp = defaultdict(list)
        for r, d in s.W[w].items():
            for i, p in d["S"]:
                if i != "0": bp[s.pos(i)].append(p)
        return {k: float(np.median(v)) for k, v in bp.items()}

def eff_week(s, t):
    """The first week a move can count in. Sleeper keeps tagging moves with the old week until Wednesday, so a trade made
    after that week's last game ended (kickoff + 4 hours) belongs to the next week. A trade made mid-week counts that week only
    if its players hadn't played yet."""
    import datetime as _dt
    w = t["w"]; when = t.get("when")
    ko = [_dt.datetime.strptime(k, "%Y-%m-%dT%H:%MZ") for k, *_ in getattr(s, "sched", {}).get(w, [])]
    if not when or not ko: return w
    wt = _dt.datetime.strptime(when, "%Y-%m-%dT%H:%MZ")
    if t.get("type") == "trade" and wt >= min(ko):
        # mid-week trade: players whose games hadn't started switch teams right away (Sleeper's frozen week shows them on the new team);
        # if they'd already played, the week stays with the old team and the trade counts from the next week
        if w in getattr(s, "W", {}):
            moved = any(i in {j for j, _ in s.W[w].get(r, {}).get("S", []) + s.W[w].get(r, {}).get("B", [])} for i, r in t["adds"])
            return w if moved else w + 1
        tk = {}
        for k, aw, hm, *_ in getattr(s, "sched", {}).get(w, []):
            tk[aw] = tk[hm] = _dt.datetime.strptime(k, "%Y-%m-%dT%H:%MZ")
        tm = lambda i: (s.PL.get(i, {}).get("team") if i.isdigit() else i)
        kicks = [tk[tm(i)] for i, _ in t["adds"] if tm(i) in tk]
        return w if (kicks and wt < min(kicks)) else w + 1
    return w + 1 if wt > max(ko) + _dt.timedelta(hours=4) else w

def derive_trades(s):
    """Completed trades, minus any later undone by a commissioner transaction that exactly inverts it."""
    # Sleeper lists each week newest first: flip so trades are numbered in the order they happened
    trades = [t for _, t in sorted(enumerate(s.tx), key=lambda kv: (kv[1]["w"], -kv[0])) if t["type"] == "trade" and t["status"] == "complete"]
    comm = [t for t in s.tx if t["type"] == "commissioner"]
    out = []
    for t in trades:
        inv = {(i, r) for i, r in t["drops"]}; dr = {(i, r) for i, r in t["adds"]}
        vetoed = any({(i, r) for i, r in c["adds"]} == inv and {(i, r) for i, r in c["drops"]} == dr for c in comm)
        sides = {}
        for r in t["rosters"]:
            sides[r] = ([i for i, rr in t["adds"] if rr == r], [i for i, rr in t["drops"] if rr == r])
        out.append(dict(w=eff_week(s, t), sides=sides, vetoed=vetoed, frm={i: r for i, r in t["drops"]}))
    out = sorted(out, key=lambda t: t["w"])
    return out

def flex_share(s):
    c = Counter()
    fi = s.L["lineup"].index("FLEX")
    for w in s.weeks:
        for r, d in s.W[w].items():
            if len(d["S"]) > fi and d["S"][fi][0] != "0": c[s.pos(d["S"][fi][0])] += 1
    n = sum(c.values()) or 1
    return {p: c[p] / n for p in s.L["flex"]}

class Repl(dict):
    """Replacement level. R[pos] = season figure (for forward-looking math); R.at(w, pos) = that week's own figure."""
    def at(self, w, p): return self.wk.get(w, {}).get(p, self.get(p, 0.0))

def replacement(s, upto):
    """Replacement level = what the waiver wire realistically gave you, averaged over the season.
    Each played week: the pool is players on no Super League roster that week (locked; later pickups never touch it).
    Take the 5 with the highest Sleeper projection at each position who actually played (no DNPs), and average their real points.
    The season replacement level is the plain average of those weekly numbers (each week counts equally), used for every week.
    The week in progress counts too, from the games already final, and settles when the week ends."""
    old = replacement_old(s, upto)
    if not s.NP or not s.SP: return dict(val=Repl(old["val"]), line=old["line"])
    N = CONFIG["repl_group"]; raw = {}; picks = {}
    for w in [w for w in s.weeks if w <= upto and w in s.SP]:
        rost = {i for r in s.R for i in s.ROST.get((w, r), s.rost[r])}
        raw[w] = {}; picks[w] = {}
        for p in POSLIST:
            c = sorted([(v, i) for i, v in s.SP[w].items() if s.pos(i) == p and i not in rost and v > 0 and i in s.NP.get(w, {})], reverse=True)[:N]
            picks[w][p] = [(i, v, s.NP[w][i]) for v, i in c]
            if c: raw[w][p] = float(np.mean([s.NP[w][i] for _, i in c]))
    LV = getattr(s, "LIVE", None) or {}; LW = upto + 1     # the week in progress joins as one more week, from the games already final; it settles when the week ends
    if LV.get("np") and LV.get("week") == LW and LW in s.SP:
        rost = {i for r in s.R for i in s.rost.get(r, [])} | {i for lu in LV.get("lu", {}).values() for i, _ in lu}
        raw[LW] = {}; picks[LW] = {}
        for p in POSLIST:
            c = sorted([(v, i) for i, v in s.SP[LW].items() if s.pos(i) == p and i not in rost and v > 0 and i in LV["np"]], reverse=True)[:N]
            picks[LW][p] = [(i, v, LV["np"][i]) for v, i in c]
            if c: raw[LW][p] = float(np.mean([LV["np"][i] for _, i in c]))
    val = Repl({p: float(np.mean([raw[w][p] for w in raw if p in raw[w]])) if any(p in raw[w] for w in raw) else old["val"][p] for p in POSLIST}); val.wk = {}
    return dict(val=val, line={p: "avg of each week's top 5 projected free agents who played" for p in POSLIST}, raw=raw, picks=picks)

def replacement_old(s, upto):
    """Replacement level = avg PPG (season to date, 3+ games active) of the N best players at each position
    who are on NO Super League roster, i.e. what you could actually pick up. Falls back to the
    below-the-starting-line method when only league-roster data is loaded."""
    g = defaultdict(list); N = CONFIG["repl_group"]
    src = s.NP if s.NP else s.WP
    for w in s.weeks:
        if w > upto: continue
        for i, p in src.get(w, {}).items(): g[i].append(p)
    ppg = {i: np.mean(v) for i, v in g.items() if len(v) >= 3}
    out = {}; line = {}
    if s.NP:
        rostered = {i for v in s.rost.values() for i in v}
        for p in POSLIST:
            xs = sorted([v for i, v in ppg.items() if s.pos(i) == p and i not in rostered], reverse=True)
            out[p] = float(np.mean(xs[:N])) if xs else 0.0; line[p] = "best unrostered"
        return dict(val=out, line=line)
    fs = flex_share(s); T = s.L["teams"]
    line = {p: round(T * (s.L["lineup"].count(p) + fs.get(p, 0))) for p in POSLIST}
    for p, n in line.items():
        xs = sorted([v for i, v in ppg.items() if s.pos(i) == p], reverse=True)
        out[p] = float(np.mean(xs[n:n + N])) if len(xs) > n else (float(xs[-1]) if xs else 0.0)
    return dict(val=out, line=line)

def md_table(head, rows_):
    o = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    o += ["| " + " | ".join(str(x) for x in r) + " |" for r in rows_]
    return o

# ----------------------------------------------------------------------------- docs
def doc_season(s):
    W, PF, PA = s.record()
    order = sorted(s.R, key=lambda r: (-W[r], -PF[r]))
    n = len(s.weeks)
    o = [f"# Super League: {s.L['season']} Season", "", f"Through Week {s.last}. Source: Sleeper. Rebuilt by the pipeline.", "", "## Standings", ""]
    o += md_table(["#", "Manager", "Team", "W-L", "PF", "PA"], [(k, s.M[r], s.L["rosters"][r]["team"] or "-", f"{W[r]}-{n - W[r]}", f"{PF[r]:.2f}", f"{PA[r]:.2f}") for k, r in enumerate(order, 1)])
    o += ["", "## Results by week", ""]
    for w in s.weeks:
        g = s.G[w]
        o.append(f"**Week {w}:** " + " · ".join(f"{s.M[a]} {g['scores'][a]:.2f} - {g['scores'][b]:.2f} {s.M[b]}" for a, b in g["pairs"]))
    o += ["", "## Remaining schedule", ""]
    for w, ps in s.fut.items():
        o.append(f"**Week {w}:** " + " · ".join(f"{s.M[a]} vs {s.M[b]}" for a, b in ps))
    return "\n".join(o)

def doc_stats(s):
    n = len(s.weeks); W, PF, PA = s.record()
    S = {r: [s.G[w]["scores"][r] for w in s.weeks] for r in s.R}
    allv = np.array([S[r] for r in s.R]); mu = allv.mean(); sd = (allv - allv.mean(1, keepdims=True)).std(ddof=1)
    x = 4 * mu * norm.pdf(0) / (sd * math.sqrt(2))
    H = {a: {b: [0, 0] for b in s.R} for a in s.R}; med = Counter(); ap = Counter()
    for w in s.weeks:
        g = s.G[w]; m = np.median(list(g["scores"].values()))
        for a, b in g["pairs"]:
            win = a if g["scores"][a] > g["scores"][b] else b; lose = b if win == a else a
            H[win][lose][0] += 1; H[lose][win][1] += 1
        for r in s.R:
            med[r] += g["scores"][r] > m; ap[r] += sum(g["scores"][r] > g["scores"][o_] for o_ in s.R if o_ != r)
    opp = len(s.R) - 1
    o = [f"# Super League: Stats Book", "", f"Through Week {s.last}. Rebuilt weekly.", "",
         "**How to read it**",
         "- **xWins = all-play expected wins.** Your score vs all other teams each week = wins expected against a random opponent. Strips schedule luck (no defense in fantasy).",
         "- **Luck** = actual wins − xWins. **vs Median** = beat the weekly median.",
         f"- **Pyth W** (reference): PF^x/(PF^x+PA^x), x = {x:.2f} derived from this league's score spread.", "",
         f"League avg {mu:.2f} PPG, within-team weekly SD {sd:.1f}.", "", "## Standings & expected records", ""]
    order = sorted(s.R, key=lambda r: (-W[r], -PF[r])); rows_ = []
    for k, r in enumerate(order, 1):
        py = PF[r] ** x / (PF[r] ** x + PA[r] ** x) * n; apct = ap[r] / (opp * n)
        rows_.append((k, s.M[r], f"{W[r]}-{n - W[r]}", f"{PF[r]:.2f}", f"{PA[r]:.2f}", f"{PF[r] / n:.1f}", f"{np.std(S[r], ddof=1):.1f}", f"{max(S[r]):.2f}", f"{min(S[r]):.2f}",
                      f"{ap[r]}-{opp * n - ap[r]}", f"{apct * 100:.1f}%", f"{med[r]}-{n - med[r]}", f"{W[r] + med[r]}-{2 * n - W[r] - med[r]}", f"{apct * n:.1f}", f"{W[r] - apct * n:+.1f}", f"{py:.1f}"))
    o += md_table(["#", "Manager", "W-L", "PF", "PA", "PPG", "SD", "High", "Low", "All-play", "AP %", "vs Median", "H2H+Med", "xWins", "Luck", "Pyth W"], rows_)
    o += ["", "## Luck ranking", ""] + md_table(["#", "Manager", "Record", "xWins", "Luck"], [(k, s.M[r], f"{W[r]}-{n - W[r]}", f"{ap[r] / opp:.1f}", f"{W[r] - ap[r] / opp:+.1f}") for k, r in enumerate(sorted(s.R, key=lambda r: -(W[r] - ap[r] / opp)), 1)])
    o += ["", "## Head-to-head (row's record vs column)", ""]
    o += md_table([""] + [s.M[c] for c in order], [[f"**{s.M[a]}**"] + ["—" if a == b else (f"{H[a][b][0]}-{H[a][b][1]}" if sum(H[a][b]) else "·") for b in order] for a in order])
    o += ["", "## Weekly scores (rank)", ""]
    o += md_table(["Manager"] + [f"W{w}" for w in s.weeks], [[s.M[r]] + [f"{s.G[w]['scores'][r]:.1f} ({sorted(s.G[w]['scores'].values(), reverse=True).index(s.G[w]['scores'][r]) + 1})" for w in s.weeks] for r in order])
    o += ["", "## Weekly high / low / median", ""]
    o += md_table(["Wk", "High", "Low", "Median"], [(w, f"{s.M[max(s.G[w]['scores'], key=s.G[w]['scores'].get)]} {max(s.G[w]['scores'].values()):.2f}", f"{s.M[min(s.G[w]['scores'], key=s.G[w]['scores'].get)]} {min(s.G[w]['scores'].values()):.2f}", f"{np.median(list(s.G[w]['scores'].values())):.2f}") for w in s.weeks])
    gl = []
    for w in s.weeks:
        g = s.G[w]
        for a, b in g["pairs"]:
            sa, sb = g["scores"][a], g["scores"][b]; wi, lo = (a, b) if sa > sb else (b, a)
            gl.append((abs(sa - sb), w, s.M[wi], g["scores"][wi], s.M[lo], g["scores"][lo]))
    gl.sort()
    f = lambda x: f"W{x[1]} {x[2]} {x[3]:.2f}-{x[5]:.2f} {x[4]} ({x[0]:.2f})"
    hl = max(gl, key=lambda x: x[5]); lw = min(gl, key=lambda x: x[3])
    allsc = [(s.G[w]["scores"][r], w, s.M[r]) for w in s.weeks for r in s.R]
    o += ["", "## Records", "", f"- Highest score: {max(allsc)[2]} {max(allsc)[0]:.2f} (W{max(allsc)[1]})", f"- Lowest score: {min(allsc)[2]} {min(allsc)[0]:.2f} (W{min(allsc)[1]})",
          "- Closest games: " + "; ".join(f(x) for x in gl[:3]), "- Biggest blowouts: " + "; ".join(f(x) for x in gl[::-1][:3]),
          f"- Highest score in a loss: W{hl[1]} {hl[4]} {hl[5]:.2f}", f"- Lowest score in a win: W{lw[1]} {lw[2]} {lw[3]:.2f}"]
    st = []
    for r in s.R:
        res = []
        for w in s.weeks:
            for a, b in s.G[w]["pairs"]:
                if r in (a, b): o_ = b if r == a else a; res.append(s.G[w]["scores"][r] > s.G[w]["scores"][o_])
        best = {True: 0, False: 0}; c = 0
        for i in range(len(res)):
            c = c + 1 if i and res[i] == res[i - 1] else 1; best[res[i]] = max(best[res[i]], c)
        k = 1
        while k < len(res) and res[-k - 1] == res[-1]: k += 1
        st.append((s.M[r], best[True], best[False], ("W" if res[-1] else "L") + str(k)))
    o += ["", "## Streaks", ""] + md_table(["Manager", "Longest W", "Longest L", "Current"], st)
    return "\n".join(o)

def doc_transactions(s):
    o = ["# Super League: Transactions", "", f"Through Week {max(t['w'] for t in s.tx)} leg. All players by name. DEF = team defense.", "", "## Trades", ""]
    rows_ = []
    for t in s.trades:
        got = "; ".join(f"{s.M[r]} got {', '.join(s.nm(i) for i in g)}" for r, (g, _) in t["sides"].items())
        rows_.append((t["w"], " / ".join(s.M[r] for r in t["sides"]), got + (" **(VETOED / reversed by commissioner)**" if t["vetoed"] else "")))
    o += md_table(["Wk", "Teams", "Details"], rows_)
    cnt = Counter(); tc = Counter()
    for t in s.tx:
        if t["status"] != "complete": continue
        if t["type"] in ("waiver", "free_agent"): cnt[t["rosters"][0]] += 1
    for t in s.trades:
        if not t["vetoed"]:
            for r in t["sides"]: tc[r] += 1
    o += ["", "## Activity by manager", ""] + md_table(["Manager", "Completed adds/drops", "Trades"], [(s.M[r], cnt[r], tc[r]) for r in sorted(s.R, key=lambda r: -cnt[r])])
    o += ["", "## Full log", ""]
    for w in sorted({t["w"] for t in s.tx}):
        o.append(f"**Week {w}**")
        for t in [t for t in s.tx if t["w"] == w]:
            if t["type"] == "trade": continue
            for r in t["rosters"]:
                a = [s.nm(i) for i, rr in t["adds"] if rr == r]; d_ = [s.nm(i) for i, rr in t["drops"] if rr == r]
                tag = {"waiver": " (waiver)", "free_agent": "", "commissioner": " (commissioner)"}[t["type"]] + (" FAILED" if t["status"] != "complete" else "")
                o.append(f"- {s.M[r]}: " + ("+" + ", +".join(a) if a else "") + (" / " if a and d_ else "") + ("-" + ", -".join(d_) if d_ else "") + tag)
        o.append("")
    return "\n".join(o)

def doc_lineups(s):
    rows_ = {r: dict(act=0, opt=0, flips=[], empty=0) for r in s.R}; perf = []; bench = []; log = defaultdict(lambda: [0, 0, 0, 0])
    for w in s.weeks:
        optw = {}
        for r in s.R:
            d = s.W[w][r]; act = sum(p for _, p in d["S"])
            opt, _ = s.best([(i, s.pos(i), p) for i, p in d["S"] + d["B"] if i != "0"]); optw[r] = opt
            R = rows_[r]; R["act"] += act; R["opt"] += opt; R["empty"] += sum(1 for i, _ in d["S"] if i == "0")
            for i, p in d["S"]:
                if i != "0": perf.append((p, w, s.M[r], s.nm(i), s.pos(i))); log[(r, i)][0] += p; log[(r, i)][1] += 1
            for i, p in d["B"]:
                bench.append((p, w, s.M[r], s.nm(i), s.pos(i))); log[(r, i)][2] += p; log[(r, i)][3] += 1
        g = s.G[w]
        for a, b in g["pairs"]:
            for x, y in ((a, b), (b, a)):
                if g["scores"][x] < g["scores"][y] and optw[x] > g["scores"][y]:
                    rows_[x]["flips"].append(f"W{w} vs {s.M[y]} (optimal {optw[x]:.1f} vs {g['scores'][y]:.1f})")
    o = ["# Super League: Lineups & Player Log", "", f"Through Week {s.last}. Optimal = best legal lineup from that week's roster, in hindsight.", "", "## Start/sit efficiency", ""]
    o += md_table(["Manager", "Actual PF", "Optimal PF", "Left on bench", "Efficiency", "Losses the optimal lineup wins", "Empty slots"],
                  [(s.M[r], f"{R['act']:.2f}", f"{R['opt']:.2f}", f"{R['opt'] - R['act']:.2f}", f"{R['act'] / R['opt'] * 100:.1f}%", f"{len(R['flips'])}" + (": " + "; ".join(R["flips"]) if R["flips"] else ""), R["empty"]) for r, R in sorted(rows_.items(), key=lambda kv: -(kv[1]["act"] / kv[1]["opt"]))])
    perf.sort(reverse=True); bench.sort(reverse=True)
    o += ["", "## Top 15 starting performances", ""] + md_table(["Pts", "Wk", "Manager", "Player", "Pos"], [(f"{p:.2f}", w, m, n, ps) for p, w, m, n, ps in perf[:15]])
    o += ["", "## Biggest bench performances", ""] + md_table(["Pts", "Wk", "Manager", "Player", "Pos"], [(f"{p:.2f}", w, m, n, ps) for p, w, m, n, ps in bench[:10]])
    o += ["", "## Worst starts (excl. K/DEF)", ""] + md_table(["Pts", "Wk", "Manager", "Player", "Pos"], [(f"{p:.2f}", w, m, n, ps) for p, w, m, n, ps in sorted(x for x in perf if x[4] not in ("K", "DEF"))[:10]])
    o += ["", "## Player log by manager (started / benched)", ""]
    for r in s.R:
        items = sorted([(v, i) for (rr, i), v in log.items() if rr == r], key=lambda x: -(x[0][0] + x[0][2]))
        o += [f"**{s.M[r]}**"] + [f"- {s.nm(i)} ({s.pos(i)}): {v[0]:.1f} started ({v[1]}g), {v[2]:.1f} benched ({v[3]}g)" for v, i in items] + [""]
    return "\n".join(o)

def prov_median(s):
    """Stand-in for the week in progress: each position's median starter averaged over the finished weeks.
    Swapped for that week's real median the moment the week ends."""
    if not hasattr(s, "_provm"):
        m = [s.pos_median(w) for w in s.weeks]
        s._provm = {p: float(np.mean([x[p] for x in m if p in x])) for p in POSLIST if any(p in x for x in m)}
    return s._provm

def war1(s, w, i, p):
    """One start's WAR: points above a replacement-level player at his position that week, in wins."""
    R = (getattr(s, "repl", None) or {}).get("val")
    return (p - R.at(w, s.pos(i))) * s.wpp if R is not None and getattr(s, "wpp", None) else 0.0

def starts_pm(s, weeks=None):
    """Every start with +/- vs that week's median starter at his real position. With no weeks given, finished starts from
    the week in progress count too, against the stand-in median."""
    out = []
    for w in (weeks or s.weeks):
        med = s.pos_median(w)
        for r, d in s.W[w].items():
            for i, p in d["S"]:
                if i != "0": out.append(dict(w=w, r=r, i=i, p=p, pm=p - med[s.pos(i)], war=war1(s, w, i, p)))
    if weeks is None:
        pm = prov_median(s)
        for r, i, p in getattr(s, "live_fin", []):
            if s.pos(i) in pm: out.append(dict(w=s.nxt, r=r, i=i, p=p, pm=p - pm[s.pos(i)], war=war1(s, s.nxt, i, p), live=1))
    return out

def doc_player_stats(s):
    S = defaultdict(list); B = defaultdict(list); teams = defaultdict(set); pteam = defaultdict(lambda: defaultdict(float)); tp = Counter()
    for w in s.weeks:
        for r, d in s.W[w].items():
            for i, p in d["S"]:
                if i == "0": continue
                S[i].append(p); teams[i].add(s.M[r]); pteam[r][i] += p; tp[r] += p
            for i, p in d["B"]: B[i].append(p)
    rows_ = []
    for i, g in S.items():
        a = np.array(g)
        rows_.append(dict(i=i, n=s.nm(i), pos=s.pos(i), gs=len(a), tot=a.sum(), ppg=a.mean(), sd=a.std(ddof=1) if len(a) > 1 else 0, hi=a.max(), lo=a.min(),
                          boom=(a >= 20).mean(), bust=(a < 5).mean(), teams=sorted(teams[i]), pick=s.dpick.get(i)))
    fmt = lambda x: (x["n"], x["pos"], ", ".join(x["teams"]), x["gs"], f"{x['tot']:.1f}", f"{x['ppg']:.1f}", f"{x['hi']:.1f}", f"{x['boom'] * 100:.0f}%", f"{x['bust'] * 100:.0f}%")
    o = ["# Super League: Player Stats (starts only)", "", f"Through Week {s.last}. Only weeks in a starting lineup. Boom = 20+, Bust = under 5.", "", "## Top 20 by total starting points", ""]
    o += md_table(["#", "Player", "Pos", "Team(s)", "GS", "Pts", "PPG", "High", "Boom %", "Bust %"], [(k,) + fmt(x) for k, x in enumerate(sorted(rows_, key=lambda x: -x["tot"])[:20], 1)])
    for p, n in (("QB", 10), ("RB", 15), ("WR", 15), ("TE", 10), ("K", 10), ("DEF", 10)):
        xs = sorted([x for x in rows_ if x["pos"] == p and x["gs"] >= 3], key=lambda x: -x["ppg"])[:n]
        o += ["", f"## {p} rankings (PPG, min 3 starts)", ""] + md_table(["#", "Player", "Team(s)", "GS", "PPG", "SD", "Floor", "Ceiling", "Boom %", "Bust %"],
                                                                         [(k, x["n"], ", ".join(x["teams"]), x["gs"], f"{x['ppg']:.1f}", f"{x['sd']:.1f}", f"{x['lo']:.1f}", f"{x['hi']:.1f}", f"{x['boom'] * 100:.0f}%", f"{x['bust'] * 100:.0f}%") for k, x in enumerate(xs, 1)])
    cons = [x for x in rows_ if x["gs"] >= 5 and x["pos"] in ("QB", "RB", "WR", "TE") and x["ppg"] >= 10]
    o += ["", "## Most consistent (min 5 starts, PPG ≥ 10)", ""] + md_table(["Player", "Pos", "PPG", "SD", "CV"], [(x["n"], x["pos"], f"{x['ppg']:.1f}", f"{x['sd']:.1f}", f"{x['sd'] / x['ppg']:.2f}") for x in sorted(cons, key=lambda x: x["sd"] / x["ppg"])[:8]])
    o += ["", "## Most volatile (min 5 starts, PPG ≥ 10)", ""] + md_table(["Player", "Pos", "PPG", "SD", "Floor", "Ceiling"], [(x["n"], x["pos"], f"{x['ppg']:.1f}", f"{x['sd']:.1f}", f"{x['lo']:.1f}", f"{x['hi']:.1f}") for x in sorted(cons, key=lambda x: -x["sd"] / x["ppg"])[:8]])
    sp = {x["i"]: x["ppg"] for x in rows_}
    o += ["", "## Most points scored on benches", ""] + md_table(["Player", "Pos", "Benched pts", "Starting PPG"], [(s.nm(i), s.pos(i), f"{t:.1f}", f"{sp.get(i, 0):.1f}") for t, i in sorted([(sum(v), i) for i, v in B.items()], reverse=True)[:10]])
    o += ["", "## Team MVPs (share of starting points)", ""]
    tr = []
    for r in s.R:
        top = sorted(pteam[r].items(), key=lambda kv: -kv[1])
        tr.append((s.M[r], s.nm(top[0][0]), f"{top[0][1]:.1f}", f"{top[0][1] / tp[r] * 100:.1f}%", f"{sum(v for _, v in top[:3]) / tp[r] * 100:.1f}%"))
    o += md_table(["Manager", "Top scorer", "Pts", "Share", "Top-3 share"], tr)
    half = len(s.draft) * 0.4
    o += ["", "## Draft value", "", "**Best values** (drafted after the first 40% of picks, min 3 starts, excl K/DEF)", ""]
    o += md_table(["Player", "Pick", "Drafted by", "GS", "PPG"], [(x["n"], x["pick"], s.M[s.dby[x["i"]]], x["gs"], f"{x['ppg']:.1f}") for x in sorted([x for x in rows_ if x["pick"] and x["pick"] > half and x["gs"] >= 3 and x["pos"] not in ("K", "DEF")], key=lambda x: -x["ppg"])[:10]])
    o += ["", "**Biggest disappointments** (first 30% of picks, by PPG)", ""]
    o += md_table(["Player", "Pick", "Drafted by", "GS", "PPG"], [(x["n"], x["pick"], s.M[s.dby[x["i"]]], x["gs"], f"{x['ppg']:.1f}") for x in sorted([x for x in rows_ if x["pick"] and x["pick"] <= len(s.draft) * 0.3], key=lambda x: x["ppg"])[:8]])
    o += ["", "## Started for 2+ fantasy teams", ""] + [f"- {x['n']}: {', '.join(x['teams'])}" for x in rows_ if len(x["teams"]) > 1]
    return "\n".join(o)

def doc_war(s):
    R = s.repl["val"]; war = Counter(); gs = Counter(); pts = Counter(); teams = defaultdict(set); byt = defaultdict(Counter); empty = Counter()
    for w in s.weeks:
        for r, d in s.W[w].items():
            for i, p in d["S"]:
                if i == "0": empty[r] -= R.at(w, "K") * s.wpp; continue
                x = (p - R.at(w, s.pos(i))) * s.wpp; war[i] += x; gs[i] += 1; pts[i] += p; teams[i].add(s.M[r]); byt[r][i] += x
    o = ["# Super League: WAR & Lineup Timing", "", f"Through Week {s.last}. Starts only.", "", "## How WAR works",
         f"- **Replacement level** = avg PPG (season to date, 3+ games active) of the {CONFIG['repl_group']} best players at each position on **no Super League roster**, i.e. what you could pick up. Uses every NFL player's real 2026 points in league scoring.",
         "- Replacement PPG: " + ", ".join(f"{p} {v:.1f}" for p, v in R.items()),
         f"- **Points per win:** weekly scores SD {s.sigma:.1f} → one point flips a random matchup with prob φ(0)/(σ√2) = {s.wpp:.4f}, so **~{s.ppw:.0f} pts above replacement = 1 win**.",
         "- **WAR** = Σ over starts of (points − replacement) ÷ points-per-win.", "", "## WAR leaderboard", ""]
    o += md_table(["#", "Player", "Pos", "Team(s)", "GS", "Pts", "WAR"], [(k, s.nm(i), s.pos(i), ", ".join(sorted(teams[i])), gs[i], f"{pts[i]:.1f}", f"{war[i]:.2f}") for k, i in enumerate(sorted(war, key=lambda i: -war[i])[:25], 1)])
    o += ["", "## Negative WAR (min 3 starts)", ""] + md_table(["Player", "Pos", "Team(s)", "GS", "PPG", "WAR"], [(s.nm(i), s.pos(i), ", ".join(sorted(teams[i])), gs[i], f"{pts[i] / gs[i]:.1f}", f"{war[i]:.2f}") for i in sorted([i for i in war if gs[i] >= 3], key=lambda i: war[i])[:12]])
    o += ["", "## Team WAR", "", "Wins added over an all-replacement lineup. Empty-slot WAR = cost of leaving a slot empty.", ""]
    tr = []
    for r in sorted(s.R, key=lambda r: -(sum(byt[r].values()) + empty[r])):
        b = byt[r]; top = max(b, key=b.get); low = min(b, key=b.get)
        tr.append((s.M[r], f"{sum(b.values()) + empty[r]:.2f}", f"{s.nm(top)} {b[top]:.2f}", f"{s.nm(low)} {b[low]:.2f}", f"{empty[r]:.2f}"))
    o += md_table(["Manager", "Starter WAR", "Top", "Biggest drag", "Empty-slot WAR"], tr)
    # lineup timing
    sat = defaultdict(lambda: [0, 0.0]); bad = defaultdict(lambda: [0, 0.0]); cost = Counter()
    for w in s.weeks:
        for r, d in s.W[w].items():
            pl = [(i, s.pos(i), p) for i, p in d["S"] + d["B"] if i != "0"]; pt = {i: p for i, _, p in pl}
            _, O = s.best(pl); O = set(O); A = {i for i, _ in d["S"] if i != "0"}
            benched = sorted(O - A, key=lambda i: -pt[i]); started = sorted(A - O, key=lambda i: pt[i])
            for b_ in benched:
                pb = s.pos(b_)
                cand = [x for x in started if s.pos(x) == pb or (pb in s.L["flex"] and s.pos(x) in s.L["flex"])]
                if not cand: continue
                x = min(cand, key=lambda i: pt[i]); started.remove(x); c = pt[b_] - pt[x]
                sat[(b_, r)][0] += 1; sat[(b_, r)][1] += c; bad[(x, r)][0] += 1; bad[(x, r)][1] += c; cost[r] += c
    o += ["", "## Lineup timing", "", "Hindsight: a benched player who belonged in the best lineup **sat when good**; the starter he should have replaced **started when bad**.", "",
          "### Started when bad", ""] + md_table(["Player", "Manager", "Bad starts", "Pts cost"], [(s.nm(i), s.M[r], n, f"{c:.1f}") for (i, r), (n, c) in sorted(bad.items(), key=lambda kv: -kv[1][1])[:12]])
    o += ["", "### Sat when good", ""] + md_table(["Player", "Manager", "Bad sits", "Pts cost"], [(s.nm(i), s.M[r], n, f"{c:.1f}") for (i, r), (n, c) in sorted(sat.items(), key=lambda kv: -kv[1][1])[:12]])
    o += ["", "### Lineup cost by manager (hindsight; includes depth + randomness, see Start/Sit Grades for decision quality)", ""] + md_table(["Manager", "Pts lost", "Wins lost"], [(s.M[r], f"{c:.1f}", f"{c * s.wpp:.2f}") for r, c in sorted(cost.items(), key=lambda kv: -kv[1])])
    return "\n".join(o)

# ---- projection model (shared by backtest, grades, projections)
def own_rate(s, i, before, hl=4):
    """Recency-weighted average of a player's actual league points in active games before `before`."""
    pts = [(w, s.NP[w][i]) for w in sorted(s.NP) if w < before and i in s.NP[w]]
    if not pts: return None
    wt = [0.5 ** ((before - 1 - w) / hl) for w, _ in pts]
    return sum(a * p for (w, p), a in zip(pts, wt)) / sum(wt)

def sleeper_base(s, i, w):
    """Sleeper projection for week w if that file exists (absent = Out/IR/bye/not playing = 0);
    otherwise the player's average of his last 3 Sleeper projections (future weeks)."""
    if w in s.SP: return s.SP[w].get(i, 0.0)
    past = [s.SP[x][i] for x in sorted(s.SP) if x <= max(s.SP) and i in s.SP[x]][-3:]
    return float(np.mean(past)) if past else 0.0

def make_mu(s, before, wts):
    """Projection for week `before` using only information available then."""
    def mu(i):
        S = s.SP.get(before, {}).get(i, 0.0)
        wS = wts.get(s.pos(i), 1.0)
        if wS >= 1.0 or S == 0: return S
        O = own_rate(s, i, before); return S if O is None else wS * S + (1 - wS) * O
    return mu

def tune(s):
    """Walk-forward backtest on every week with both Sleeper projections and results."""
    ev = sorted(w for w in s.SP if w in s.NP and w in s.G and w >= 2)
    rmse = lambda e: math.sqrt((np.array(e) ** 2).mean()) if len(e) else float("nan")
    table = {}; wts = {}; cv = {}
    for p in POSLIST:
        R = [(s.SP[w][i], s.NP[w].get(i, 0.0), own_rate(s, i, w)) for w in ev for i in s.SP[w] if s.pos(i) == p and s.SP[w][i] > 2]
        if not R: wts[p] = 1.0; cv[p] = 0.7; continue
        eS = [a - S for S, a, O in R]; eO = [a - (O if O is not None else S) for S, a, O in R]
        best = (rmse(eS), 1.0)
        for wS in np.linspace(0, 0.95, 20):
            e = [a - (wS * S + (1 - wS) * (O if O is not None else S)) for S, a, O in R]
            if rmse(e) < best[0]: best = (rmse(e), float(wS))
        use = best[1] if best[0] < rmse(eS) * (1 - CONFIG["blend_min_gain"]) else 1.0   # only blend if it clearly helps
        wts[p] = use; cv[p] = rmse(eS) / np.mean([S for S, _, _ in R])
        table[p] = dict(n=len(R), S=rmse(eS), Sb=np.mean(eS), O=rmse(eO), Ob=np.mean(eO), bw=best[1], b=best[0], use=use)
    e = []; z = []; po = []; ac = []
    for W in ev:
        mu = make_mu(s, W, wts)
        for r, d in s.W[W].items():
            st = [i for i, _ in d["S"] if i != "0"]; m = sum(mu(i) for i in st)
            sd = math.sqrt(sum((cv[s.pos(i)] * mu(i)) ** 2 for i in st)) or 1
            e.append(s.G[W]["scores"][r] - m); z.append((s.G[W]["scores"][r] - m) / sd)
            po.append(s.best([(i, s.pos(i), mu(i)) for i, _ in d["S"] + d["B"] if i != "0"])[0]); ac.append(s.G[W]["scores"][r])
    naive = []
    for W in ev:
        if W < 2: continue
        for r in s.R:
            prev = [s.G[w]["scores"][r] for w in s.weeks if w < W]
            if prev: naive.append(s.G[W]["scores"][r] - np.mean(prev))
    return dict(weeks=ev, table=table, wts=wts, cv=cv, rmse=rmse(e), bias=float(np.mean(e)), zsd=float(np.std(z)), naive=rmse(naive),
                corr=CONFIG["corr_inflation"] or float(np.std(z)), line_factor=float(np.sum(ac) / np.sum(po)), line_n=len(po))

def doc_grades(s, T):
    res = defaultdict(lambda: dict(dec=0, luck=0, hind=0, calls=[]))
    gwk = sorted(w for w in s.SP if w in s.G)          # every finished week that has a pregame projection, Week 1 included
    for W in gwk:
        mu_ = make_mu(s, W, T["wts"]); NPw = s.NP.get(W, {})
        mu = lambda i, mu_=mu_, NPw=NPw: mu_(i) if (i in NPw or not NPw) else 0.0     # didn't play (DNP / inactive) = projected 0, so benching a late scratch never costs you
        for r, d in s.W[W].items():
            act = {i: p for i, p in d["S"] + d["B"] if i != "0"}; started = [i for i, _ in d["S"] if i != "0"]
            avail = list(act)
            _, popt = s.best([(i, s.pos(i), mu(i)) for i in avail]); _, hopt = s.best([(i, s.pos(i), act[i]) for i in act])
            R = res[r]; R["dec"] += sum(mu(i) for i in popt) - sum(mu(i) for i in started)
            R["luck"] += sum(act[i] for i in started) - sum(act[i] for i in popt); R["hind"] += sum(act[i] for i in hopt) - sum(act[i] for i in started)
            for j in sorted(set(popt) - set(started)):
                for i in sorted(set(started) - set(popt)):
                    pi, pj = s.pos(i), s.pos(j)
                    if pi == pj or {pi, pj} <= s.L["flex"]:
                        R["calls"].append((mu(j) - mu(i), W, s.nm(i), mu(i), act[i], s.nm(j), mu(j), act[j])); break
    s.grades = {r: dict(dec=R["dec"], luck=R["luck"], hind=R["hind"]) for r, R in res.items()}; s.grade_weeks = gwk
    o = ["# Super League: Start/Sit Decision Grades (ex-ante)", "", f"Weeks {gwk[0]}-{gwk[-1]}. Each lineup vs what was knowable **before kickoff**.", "",
         "- Projection = that week's Sleeper projection rescored in league scoring (the same model the projections doc uses), so it already knew byes, injuries and matchups.",
         "- **Decision cost** = projected pts of model's lineup − projected pts of your lineup. **Lineup luck** = your lineup's actual − model lineup's actual.",
         "- A player who didn't play that week (inactive or DNP) counts as projected 0, so benching a late scratch never costs you.",
         "- Caveat: other late news (weather, a role change) after the projection was made shows up as 'luck'.", ""]
    o += md_table(["Manager", "Decision cost (pts)", "Decision cost (wins)", "Lineup luck", "Hindsight cost"], [(s.M[r], f"{R['dec']:.1f}", f"{R['dec'] * s.wpp:.2f}", f"{R['luck']:+.1f}", f"{R['hind']:.1f}") for r, R in sorted(res.items(), key=lambda kv: kv[1]["dec"])])
    allc = [(c, r) for r, R in res.items() for c in R["calls"]]; seen = set(); rows_ = []
    for c, r in sorted(allc, key=lambda x: -x[0][0]):
        if (c[1], r, c[2]) in seen or (c[1], r, c[5]) in seen or len(rows_) >= 12: continue
        seen |= {(c[1], r, c[2]), (c[1], r, c[5])}; g, W, a, ma, aa, b, mb, ab = c
        rows_.append((W, s.M[r], a, f"{ma:.1f} / {aa:.1f}", b, f"{mb:.1f} / {ab:.1f}"))
    o += ["", "## Biggest ex-ante misses", ""] + md_table(["Wk", "Manager", "Started", "Proj / Actual", "Over", "Proj / Actual"], rows_)
    return "\n".join(o)

def doc_awards(s):
    s.awards = []
    o = ["# Super League: Weekly Awards (MVP / LVP)", "", "## Rules",
         "- Every starter vs a **replacement-level player at his position that same week** (what's free on waivers; the same baseline as WAR). Uses only that week's games, so awards never change once given.",
         "- **League MVP** = highest +/- among starters on **winning** teams. **LVP** = lowest +/- in the league. **Team MVP / LVP** = highest / lowest on each team. Empty slots excluded.",
         "- **Decisive** = MVP's +/- > his team's margin of victory; LVP's shortfall > his team's margin of defeat.", "", "## League awards", ""]
    lr = []; weekly = []; lm = Counter(); ll = Counter(); tm = Counter(); tl = Counter(); medtab = []
    for w in s.weeks:
        g = s.G[w]; res = {}
        for a, b in g["pairs"]:
            res[a] = (g["scores"][a] - g["scores"][b], b); res[b] = (g["scores"][b] - g["scores"][a], a)
        med = s.pos_median(w); medtab.append([w] + [f"{med.get(p, 0):.1f}" for p in POSLIST])
        Rv = s.repl["val"]
        c = [(p - Rv.at(w, s.pos(i)), p, i, r) for r, d in s.W[w].items() for i, p in d["S"] if i != "0"]   # points above replacement: WAR's order
        cw = [x for x in c if res[x[3]][0] > 0] or [x for x in c if res[x[3]][0] >= 0] or c          # MVP has to come from a winning team
        b = max(cw); l = min(c)
        def tag(x, mvp):
            mg = res[x[3]][0]
            if mvp: return "decisive" if mg > 0 and x[0] > mg else ("in a loss" if mg < 0 else "")
            return "decisive" if mg < 0 and -x[0] > -mg else ("in a win" if mg > 0 else "")
        lr.append((w, f"{s.nm(b[2])} ({s.M[b[3]]})", f"{b[1]:.1f}", f"+{b[0]:.1f}", tag(b, 1), f"{s.nm(l[2])} ({s.M[l[3]]})", f"{l[1]:.1f}", f"{l[0]:.1f}", tag(l, 0)))
        lm[b[3]] += 1; ll[l[3]] += 1; tr = []
        s.awards = getattr(s, "awards", []) + [dict(w=w, mvp=(b[2], b[3], b[1], b[0], tag(b, 1)), lvp=(l[2], l[3], l[1], l[0], tag(l, 0)))]
        for r in s.R:
            cc = [x for x in c if x[3] == r]; hi = max(cc); lo = min(cc); mg, opp = res[r]
            tm[(r, hi[2])] += 1; tl[(r, lo[2])] += 1
            tr.append((s.M[r], f"{'W' if mg > 0 else 'L'} {g['scores'][r]:.1f}-{g['scores'][r] - mg:.1f} vs {s.M[opp]}", f"{s.nm(hi[2])} {hi[1]:.1f} ({hi[0]:+.1f})", f"{s.nm(lo[2])} {lo[1]:.1f} ({lo[0]:+.1f})"))
        weekly += [f"### Week {w}", ""] + md_table(["Team", "Result", "Team MVP (+/-)", "Team LVP (+/-)"], tr) + [""]
    o += md_table(["Wk", "MVP", "Pts", "+/-", "", "LVP", "Pts", "+/-", ""], lr)
    o += ["", "**League MVPs:** " + ", ".join(f"{s.M[r]} {c}" for r, c in lm.most_common()) + "  ", "**League LVPs:** " + ", ".join(f"{s.M[r]} {c}" for r, c in ll.most_common()), "", "## Team MVP / LVP leaders", ""]
    for r in s.R:
        top = sorted([(i, c) for (rr, i), c in tm.items() if rr == r], key=lambda x: -x[1]); low = sorted([(i, c) for (rr, i), c in tl.items() if rr == r], key=lambda x: -x[1])
        o.append(f"- **{s.M[r]}:** MVP {', '.join(f'{s.nm(i)} {c}' for i, c in top[:3])} | LVP {', '.join(f'{s.nm(i)} {c}' for i, c in low[:2])}")
    o += ["", "## Median starter by position each week", ""] + md_table(["Wk"] + POSLIST, medtab) + ["", "## Team awards by week", ""] + weekly
    return "\n".join(o)

def season_pm(s, pool=None, key="war"):
    """Season totals over starts. Awards that compare positions use WAR (key="war"): value over what's free on waivers.
    Awards inside one position use points (key="p")."""
    tot = Counter(); gs = Counter(); pts = Counter(); teams = defaultdict(set); best = defaultdict(float)
    for x in starts_pm(s):
        if pool is not None and x["i"] not in pool: continue
        if x.get("w", 0) > s.L.get("regular_season_weeks", 14): continue      # MVP / ROTY / Best Undrafted are regular season only
        v = x.get(key, x["pm"]); tot[x["i"]] += v; gs[x["i"]] += 1; pts[x["i"]] += x["p"]; teams[x["i"]].add(s.M[x["r"]]); best[x["i"]] = max(best[x["i"]], v)
    return tot, gs, pts, teams, best

def doc_season_mvp(s):
    tot, gs, pts, teams, best = season_pm(s); wm = Counter(); tmv = Counter()
    for w in s.weeks:
        c = [(x["pm"], x["i"], x["r"]) for x in starts_pm(s, [w])]; wm[max(c)[1]] += 1
        for r in s.R: tmv[max(y for y in c if y[2] == r)[1]] += 1
    H = ["#", "Player", "Pos", "Team(s)", "Season +/-", "GS", "+/- per start", "PPG", "Best week", "League MVPs", "Team MVPs"]
    row = lambda k, i: (k, s.nm(i), s.pos(i), ", ".join(sorted(teams[i])), f"{tot[i]:+.1f}", gs[i], f"{tot[i] / gs[i]:+.1f}", f"{pts[i] / gs[i]:.1f}", f"{best[i]:+.1f}", wm[i], tmv[i])
    order = sorted(tot, key=lambda i: -tot[i])
    o = ["# Super League: Season MVP Race", "", f"Through Week {s.last}. Updated weekly with the awards.", "", "## How it's measured",
         "- **Season +/-** = sum over every week a player **started** of his points minus the median starter at his real position that week. Rewards quality and availability. Totals, not averages.", "", "## Top 10", ""]
    o += md_table(H, [row(k, i) for k, i in enumerate(order[:10], 1)])
    for p in POSLIST:
        o += ["", f"## Top 3 {p}", ""] + md_table(H, [row(k, i) for k, i in enumerate([i for i in order if s.pos(i) == p][:3], 1)])
    run = Counter(); lead = []
    for w in s.weeks:
        for x in starts_pm(s, [w]): run[x["i"]] += x["pm"]
        L_ = max(run, key=run.get); lead.append((w, s.nm(L_), f"{run[L_]:+.1f}"))
    o += ["", "## Leader after each week", ""] + md_table(["After Wk", "Leader", "Season +/-"], lead)
    return "\n".join(o)

def doc_roty(s):
    rook = {i for i, v in s.PL.items() if v.get("exp") == 0}; und = {i for i in s.PL if i not in s.dpick}
    o = ["# Super League: ROTY & Undrafted Races", "", f"Through Week {s.last}. Same measure as the Season MVP (WAR over starts). Top 10 each.", ""]
    for pool, title, note in ((rook, "Rookie of the Year race", "2026 NFL rookies only (Sleeper years_exp = 0)."), (und, "Undrafted race", "Players nobody drafted in Super League (incl. DEF/K).")):
        tot, gs, pts, teams, _ = season_pm(s, pool)
        o += [f"## {title}", note, ""] + md_table(["#", "Player", "Pos", "Team(s)", "Season +/-", "GS", "+/- per start", "PPG"],
                                                  [(k, s.nm(i), s.pos(i), ", ".join(sorted(teams[i])), f"{tot[i]:+.2f}", gs[i], f"{tot[i] / gs[i]:+.2f}", f"{pts[i] / gs[i]:.1f}") for k, i in enumerate(sorted(tot, key=lambda i: -tot[i])[:10], 1)]) + [""]
    return "\n".join(o)

def doc_trades(s):
    R = s.repl["val"]; gpick = s.dpick
    LV = getattr(s, "LIVE", None) or {}
    LW = s.nxt if (LV.get("week") == s.nxt and LV.get("np")) else None      # the week in progress counts too, from games already final
    def lineup(ids, w, extra=()):
        src = (LV.get("np") or {}) if w == LW else (s.NP.get(w) if s.NP else s.WP[w])          # a replacement-level free agent can always fill a slot (same as every other move)
        return s.best([(i, s.pos(i), src.get(i, 0)) for i in ids] + [(f"_r{n}", p, R[p]) for n, p in enumerate(extra)] + [(f"_w{p}", p, R[p]) for p in POSLIST if p in R])[0]
    o = []; net = Counter(); summ = []; k = 0; s.trade_res = []
    for t in s.trades:
        if t["vetoed"]: continue
        k += 1; lw = t["w"]; vals = []; s.trade_res.append(dict(k=k, w=lw, sides=[], frm=t.get("frm", {})))
        o += [f"### Trade {k}: Week {lw}, {' / '.join(s.M[r] for r in t['sides'])}", ""]
        tr = []
        for r, (got, gave) in t["sides"].items():
            def cfr(w):
                act = s.ROST.get((w, r)) or (list(s.rost.get(r, [])) if w == LW else []); cf = [i for i in act if i not in got] + [i for i in gave if i not in act]; diff = len(cf) - len(act)
                for _ in range(max(diff, 0)):
                    cand = [i for i in cf if i not in gave]
                    cf.remove(max(cand, key=lambda i: (round(lineup([x for x in cf if x != i], w), 2), gpick.get(i, 999))))
                return act, cf, max(-diff, 0)
            wk = [w for w in s.weeks if w >= lw] + ([LW] if LW and LW >= lw else []); nopen = max((cfr(w)[2] for w in wk), default=0); fix = []          # a trade made this week has no finished weeks yet
            for _ in range(nopen):
                fix.append(max(POSLIST, key=lambda p: sum(lineup(cfr(w)[1], w, tuple(fix + [p])[:cfr(w)[2]]) for w in wk)))
            tot = sum(lineup(cfr(w)[0], w) - lineup(cfr(w)[1], w, tuple(fix[:cfr(w)[2]])) for w in wk)
            RSW = s.L.get("regular_season_weeks", 14)
            rs = sum(lineup(cfr(w)[0], w) - lineup(cfr(w)[1], w, tuple(fix[:cfr(w)[2]])) for w in wk if w <= RSW)
            vals.append((tot, r)); net[r] += tot; s.trade_res[-1]["sides"].append(dict(r=r, got=got, gave=gave, pts=tot, pts_rs=rs))
            tr.append((s.M[r], ", ".join(s.nm(i) for i in got), ", ".join(s.nm(i) for i in gave), f"{tot:+.1f}", f"{tot / s.ppw:+.2f}"))
        o += md_table(["Team", "Got", "Gave", "Pts with − without", "Wins"], tr)
        vals.sort(reverse=True); o += ["", f"**Winner so far: {s.M[vals[0][1]]}**", ""]
        summ.append((k, f"W{lw} {' / '.join(s.M[r] for r in t['sides'])}", s.M[vals[0][1]], ", ".join(f"{s.M[r]} {v:+.1f}" for v, r in vals)))
    head = ["# Super League: Trade Scorecard", "", f"Through Week {s.last}. **Part 1** = how every trade has gone so far (actual results). **Part 2** = the projected rest of the season.", "", "# Part 1: So far", "", "## Summary", ""] + md_table(["#", "Trade", "Winner", "Value by team (pts)"], summ)
    head += ["", "## Net trade value by manager", ""] + md_table(["Manager", "Pts", "Wins"], [(s.M[r], f"{v:+.1f}", f"{v / s.ppw:+.2f}") for r, v in sorted(net.items(), key=lambda kv: -kv[1])])
    head += ["", "## How trades are scored", "Every team in every trade, every week since: **value = best lineup *with* the trade − best lineup *without* it.**",
             "- **With:** actual roster. **Without:** received players out, sent players back (their real points wherever they're rostered).",
             "- **Legal rosters:** too big (you sent more than you got) → cut the bench player whose loss hurts that week's lineup least. Too small (you got more) → a replacement-level waiver player (" + ", ".join(f"{p} {v:.1f}" for p, v in R.items()) + ") at the one position that helps most over the stretch.",
             "- Best lineup both ways (start/sit doesn't count), and a replacement-level free agent can always fill a slot nobody better can. Every other move held fixed; flipped players' value passes to the later trade. Totals since the trade. Commissioner-reversed trades excluded.",
             f"- {s.ppw:.0f} pts ≈ 1 win. Players' real NFL points are used even after they leave Super League rosters.", ""]
    return "\n".join(head + o)

def move_values(s):
    """Every completed add, drop, claim and trade, graded the same way as the trade scorecard, for each team in it:
    value = that team's best lineup WITH the move minus WITHOUT it, every finished week from the move on.
    Without: what it got is taken out and what it gave is put back. Short a player -> a replacement-level free agent at the
    position that helps most; one too many -> the bench player whose loss hurts least is cut. Every other move stays as it
    happened, so a player's value stops the week he is let go (or comes back). Best lineups both ways, so start/sit is not
    part of it. Returns {id(move): {team: (pts, pts in the regular season, weeks counted)}}."""
    R = s.repl["val"]; gpick = s.dpick; RSW = s.L.get("regular_season_weeks", 14)
    LV = getattr(s, "LIVE", None) or {}
    LW = s.nxt if (LV.get("week") == s.nxt and LV.get("np")) else None      # the week in progress counts too, from games already final
    def lineup(ids, w, extra=()):
        # the waiver wire is always there: any slot the roster can't fill with someone better gets a replacement-level free agent,
        # in both worlds, so a move isn't credited (or blamed) for an empty QB slot on a bye week
        src = (LV.get("np") or {}) if w == LW else (s.NP.get(w) or {})
        return s.best([(i, s.pos(i), src.get(i, 0)) for i in ids] + [(f"_r{n}", p, R[p]) for n, p in enumerate(extra)] + [(f"_w{p}", p, R[p]) for p in POSLIST if p in R])[0]
    def val(r, got, gave, wk):
        def cfr(w):
            act = s.ROST.get((w, r)) or (list(s.rost.get(r, [])) if w == LW else []); cf = [i for i in act if i not in got] + [i for i in gave if i not in act]; diff = len(cf) - len(act)
            for _ in range(max(diff, 0)):
                cand = [i for i in cf if i not in gave] or cf
                cf.remove(max(cand, key=lambda i: (round(lineup([y for y in cf if y != i], w), 2), gpick.get(i, 999))))
            return act, cf, max(-diff, 0)
        C = {w: cfr(w) for w in wk}; nopen = max((C[w][2] for w in wk), default=0); fix = []
        for _ in range(nopen):
            fix.append(max(POSLIST, key=lambda p: sum(lineup(C[w][1], w, tuple(fix + [p])[:C[w][2]]) for w in wk)))
        d = {w: lineup(C[w][0], w) - lineup(C[w][1], w, tuple(fix[:C[w][2]])) for w in wk}
        return sum(d.values()), sum(v for w, v in d.items() if w <= RSW)
    out = {}; s.mparts = []                       # s.mparts: each player in a waiver or free-agent move on his own: (move, team, player, "+" or "-", pts, regular-season pts)
    for x in s.tx:
        if x["status"] != "complete" or x["type"] not in ("waiver", "free_agent", "trade"): continue
        w0 = eff_week(s, x); wk = [w for w in s.weeks if w >= w0] + ([LW] if LW and LW >= w0 else [])
        res = {}
        for r in set(x["rosters"]) | {rr for _, rr in x["adds"]} | {rr for _, rr in x["drops"]}:
            got = [i for i, rr in x["adds"] if rr == r]; gave = [i for i, rr in x["drops"] if rr == r]
            if not got and not gave: continue
            tot, rs = val(r, got, gave, wk)
            res[r] = (tot, rs, len(wk))
            if x["type"] != "trade" and wk:        # the pickup alone (vs a replacement-level free agent) and the drop alone (vs the least useful bench player)
                for i in got: s.mparts.append((x, r, i, "+") + val(r, [i], [], wk))
                for i in gave: s.mparts.append((x, r, i, "-") + val(r, [], [i], wk))
        out[id(x)] = res
    return out

def undo_trade(s, t, T, proj, weeks_left):
    """Current rosters with trade t undone (every side). A player only moves back if he is still on the team
    that received him; flipped/dropped players stay where they are. Oversize rosters cut their lowest
    rest-of-season projection; undersize rosters are left open (the projection model's waiver logic fills them)."""
    rost = {r: list(v) for r, v in s.rost.items()}; moved = []
    for r, (got, gave) in t["sides"].items():
        for i in got:
            src = [x for x, (g2, _) in t["sides"].items() if i in t["sides"][x][1]]
            if i in rost[r] and src:
                rost[r].remove(i); rost[src[0]].append(i); moved.append((i, r, src[0]))
    size = {r: len(v) for r, v in s.rost.items()}
    ros = lambda i: sum(proj(i, w)[0] for w in weeks_left)
    for r in rost:
        while len(rost[r]) > size[r]:
            cand = [i for i in rost[r] if not any(m[0] == i and m[2] == r for m in moved)]
            rost[r].remove(min(cand, key=ros))
    return rost, moved

def doc_trades_forward(s, T, TEAM, proj, weeks_left, SIM):
    sims = CONFIG["trade_sims"]; f = T["line_factor"]
    base = simulate(s, TEAM, weeks_left, sims)[0]
    o = ["", "# Part 2: Projected rest of season (Weeks " + f"{weeks_left[0]}-{weeks_left[-1]} + playoffs)", "",
         "For each trade: rerun the projections and the full season sim with that trade **undone**, and compare with today.",
         "- **Proj pts** = each team's projected optimal lineup with vs without the trade over the remaining regular season (× line factor " + f"{f:.3f}" + "), including modeled waiver pickups both ways.",
         "- **Playoff / Title** = change in odds vs the no-trade world (same random draws both ways, " + f"{sims:,} sims).",
         "- A player only goes back if he's still on the team that got him; anyone later flipped or dropped stays put (that value belongs to the later move). Oversize rosters cut their lowest-projected player; open spots get filled by the waiver logic.", ""]
    summ = []; k = 0
    for t in s.trades:
        if t["vetoed"]: continue
        k += 1
        rost, moved = undo_trade(s, t, T, proj, weeks_left)
        TEAM2, _, _, _ = projections(s, T, rost)
        alt = simulate(s, TEAM2, weeks_left, sims)[0]
        rows_ = []
        for r in t["sides"]:
            dp = sum(TEAM[(w, r)]["mu"] - TEAM2[(w, r)]["mu"] for w in weeks_left) * f
            rows_.append((s.M[r], f"{dp:+.1f}", f"{dp / s.ppw:+.2f}", f"{(base[r]['po'] - alt[r]['po']) * 100:+.1f}", f"{(base[r]['ti'] - alt[r]['ti']) * 100:+.1f}"))
            summ.append((k, s.M[r], dp, base[r]["ti"] - alt[r]["ti"]))
        still = [s.nm(i) for i, r, src in moved]
        o += [f"### Trade {k}: Week {t['w']}, {' / '.join(s.M[r] for r in t['sides'])}", ""]
        o += md_table(["Team", "Proj pts ROS", "Proj wins", "Playoff % change", "Title % change"], rows_)
        gone = [s.nm(i) for r, (g, _) in t["sides"].items() for i in g if not any(m[0] == i for m in moved)]
        o += ["", f"Still in play: {', '.join(still) if still else 'none'}." + (f" Already flipped/dropped (value moved to later moves): {', '.join(gone)}." if gone else ""), ""]
    agg = defaultdict(lambda: [0.0, 0.0])
    for k_, m, dp, dt in summ: agg[m][0] += dp; agg[m][1] += dt
    o[7:7] = ["", "## Forward net by manager", ""] + md_table(["Manager", "Proj pts ROS", "Title % change"], [(m, f"{v[0]:+.1f}", f"{v[1] * 100:+.1f}") for m, v in sorted(agg.items(), key=lambda kv: -kv[1][1])]) + [""]
    return "\n".join(o)

# ---- projections
def projections(s, T, rost=None):
    rost = rost or s.rost
    wk0 = s.nxt; weeks_left = [w for w in sorted(s.fut) if w <= s.L["regular_season_weeks"]]; cv = T["cv"]
    def proj(i, w):
        P = s.PL.get(i, {}); tm = P.get("team") if i.isdigit() else i
        if not tm: return 0.0, "FA"
        if tm in s.byes.get(w, []): return 0.0, "bye"
        inj = P.get("inj")
        if w in s.SP:
            base = s.SP[w].get(i, 0.0)
            if base == 0: return 0.0, (inj or "not projected")
            m = CONFIG["injury_mult"].get(inj, 1.0) if inj in ("Questionable", "Doubtful") else 1.0
        else:
            base = sleeper_base(s, i, w)
            m = 0 if inj in ("IR", "PUP", "DNR", "Sus") else (CONFIG["out_later_mult"] if inj == "Out" else 1.0)
        wS = T["wts"].get(s.pos(i), 1.0)
        if wS < 1.0:
            O = own_rate(s, i, s.nxt)
            if O is not None: base = wS * base + (1 - wS) * O
        return base * m, ""
    rostered = {i for v in rost.values() for i in v}
    pool = set().union(*[set(v) for v in s.SP.values()]) if s.SP else set()
    FA = [i for i in pool if i not in rostered and s.pos(i) in POSLIST]
    TEAM = {}
    for w in weeks_left:
        RP = {}
        for p in POSLIST:
            c = sorted([(proj(i, w)[0], i) for i in FA if s.pos(i) == p], reverse=True)
            c = [x for x in c if x[0] > 0]
            RP[p] = [i for _, i in (c[CONFIG["pickup_rank"]:CONFIG["pickup_rank"] + 3] if len(c) > CONFIG["pickup_rank"] else c[-1:])]
        cands = [i for v in RP.values() for i in v]
        for r in s.R:
            pl = [(i, s.pos(i), proj(i, w)[0]) for i in rost[r]]
            base, _ = s.best(pl); added = []; cur = base
            for _ in range(CONFIG["pickup_max"]):
                bst = None
                for c in cands:
                    if c in added: continue
                    v = s.best(pl + [(x, s.pos(x), proj(x, w)[0]) for x in added + [c]])[0]
                    if v - cur >= CONFIG["pickup_min_gain"] and (bst is None or v > bst[0]): bst = (v, c)
                if not bst: break
                added.append(bst[1]); cur = bst[0]
            tot, ch = s.best(pl + [(x, s.pos(x), proj(x, w)[0]) for x in added])
            sd = math.sqrt(sum((cv[s.pos(i)] * proj(i, w)[0]) ** 2 for i in ch)) * T["corr"]
            TEAM[(w, r)] = dict(mu=tot, sd=sd, base=base, lineup=ch, adds=added, all=rost[r])
    return TEAM, proj, weeks_left, {}

def apply_live(s, T, TEAM, proj):
    """In-progress week. Any starter whose NFL game has kicked off is locked into his slot (real points, even 0);
    any bench player whose game has kicked off can no longer be used. The open slots are re-filled with the best
    projected lineup from players still to play. Nothing counts toward season stats until the week is final."""
    LV = getattr(s, "LIVE", None)
    if not LV or LV["week"] != s.nxt: return
    w = s.nxt; f = T["line_factor"]; cv = T["cv"]
    from pbp import script_mult, live_margins, WP_SD_SCALE
    script_sd = lambda: WP_SD_SCALE
    LM = live_margins(os.path.join(globals().get("DATA_DIR", "data"), "pbp"))
    ir = set().union(*[set(v) for v in getattr(s, "reserve", {}).values()]) if getattr(s, "reserve", None) else set()
    tm_of = lambda i: (s.PL.get(i, {}).get("team") if i.isdigit() else i) or ""
    for r, lu in LV["lu"].items():
        if (w, r) not in TEAM: continue
        t = TEAM[(w, r)]
        locked = 0.0; played = {}; slots = [None] * len(s.slots); open_ = []; part = 0.0; pvar = 0.0
        prog = LV.get("prog", {}); inprog = set()
        for k, (i, p) in enumerate(lu[:len(s.slots)]):
            if i != "0" and tm_of(i) in LV["done"]: locked += p; played[i] = p; slots[k] = i
            elif i != "0" and tm_of(i) in prog:         # game under way: points so far, plus his projection for the time that's left
                left = 1 - prog[tm_of(i)]; pj = proj(i, w)[0]
                mg, fr = LM.get(tm_of(i), (0, 1 - left)); m = script_mult(s.pos(i), mg, fr)     # late, close game: trailing teams throw more
                locked += p; part += pj * left * m; pvar += (cv.get(s.pos(i), 0.6) * pj * m) ** 2 * left; played[i] = p; slots[k] = i; inprog.add(i)
            else: open_.append(k)
        open_ += [k for k in range(len(lu), len(s.slots))]
        pool = [i for i in dict.fromkeys(list(s.rost.get(r, [])) + [i for i, _ in lu if i != "0" and (i in played or i in s.rost.get(r, []))] + list(t.get("adds", [])))
                if i not in played and i not in ir and tm_of(i) not in LV["done"] and tm_of(i) not in prog]     # a bench player whose game has started is locked out
        cand = [(i, s.pos(i), proj(i, w)[0]) for i in pool]
        pu = part; var = pvar
        for k in open_:
            c = [x for x in cand if x[1] in s.slots[k]]
            if not c: continue
            b = max(c, key=lambda x: x[2]); cand.remove(b); slots[k] = b[0]; pu += b[2]; var += (cv.get(b[1], 0.6) * b[2]) ** 2
        t["live"] = dict(locked=locked, played=played, inprog=inprog, starters=[i or "0" for i in slots], actual=[i for i, _ in lu if i != "0"])
        t["mu"] = (locked + f * pu) / f                    # site multiplies by f again: shows locked + f * projection still to play
        t["sd"] = math.sqrt(var) * T["corr"] * (script_sd() if (played or inprog) else 1.0)     # wider spread only once his games are under way
        t["lineup"] = [i for i in slots if i]

def live_history(s, T, TEAM, path):
    """Every update during a week in progress: each game's live win chance and score, so the chart and the comeback math
    see more than the time-slot checkpoints. Line format: utc_time|week|roster_a|roster_b|win_prob_a|score_a|score_b"""
    rows_ = [l.rstrip("\n").split("|") for l in open(path) if l.strip() and not l.startswith("#")] if os.path.exists(path) else []
    LV = getattr(s, "LIVE", None) or {}; w = s.nxt; ts = LV.get("ts")
    if ts and LV.get("week") == w and (LV.get("done") or LV.get("prog")) and w in s.fut:
        new = []
        for a, b in s.fut[w]:
            A, B = TEAM.get((w, a)), TEAM.get((w, b))
            if not A or not B or "live" not in A or "live" not in B: continue
            p = float(norm.cdf((A["mu"] - B["mu"]) / (math.hypot(A["sd"], B["sd"]) or 1)))
            la, lb = A["live"]["locked"], B["live"]["locked"]
            last = [r for r in rows_ if int(r[1]) == w and {int(r[2]), int(r[3])} == {a, b}]
            if last and last[-1][0] == ts: continue
            new.append([ts, str(w), str(a), str(b), f"{p:.4f}", f"{la:.2f}", f"{lb:.2f}"])
        if new:
            rows_ += new
            with open(path, "w") as fh:
                fh.write("# utc_time|week|roster_a|roster_b|win_prob_a|score_a|score_b   (live odds at every update during a week in progress)\n")
                for r in rows_: fh.write("|".join(r) + "\n")
    return rows_

def match_history(s, T, TEAM, path, now=None):
    """Next week's head-to-head odds, saved on every update until the week's first kickoff.
    Line format: utc_time|week|roster_a|roster_b|win_prob_a|proj_a|proj_b"""
    import datetime as _dt
    now = now or _dt.datetime.utcnow()
    rows_ = [l.rstrip("\n").split("|") for l in open(path) if l.strip() and not l.startswith("#")] if os.path.exists(path) else []
    w = s.nxt
    ko = [_dt.datetime.strptime(k, "%Y-%m-%dT%H:%MZ") for k, *_ in getattr(s, "sched", {}).get(w, [])]
    if w in s.fut and ko and now < min(ko):
        f = T["line_factor"]; ts = now.strftime("%Y-%m-%dT%H:%MZ"); new = []
        for a, b in s.fut[w]:
            A, B = TEAM[(w, a)], TEAM[(w, b)]
            p = float(norm.cdf((A["mu"] - B["mu"]) / (math.hypot(A["sd"], B["sd"]) or 1)))
            last = [r for r in rows_ if int(r[1]) == w and {int(r[2]), int(r[3])} == {a, b}]
            prev = None if not last else (float(last[-1][4]) if int(last[-1][2]) == a else 1 - float(last[-1][4]))
            if prev is None or abs(prev - p) > 0.0005:
                new.append([ts, str(w), str(a), str(b), f"{p:.4f}", f"{A['mu'] * f:.1f}", f"{B['mu'] * f:.1f}"])
        if new:
            rows_ += new
            with open(path, "w") as fh:
                fh.write("# utc_time|week|roster_a|roster_b|win_prob_a|proj_a|proj_b   (pre-kickoff head-to-head odds, one line per game per update)\n")
                for r in rows_: fh.write("|".join(r) + "\n")
    return rows_

def prev_week(s, T):
    """Standings rank and playoff odds as they stood one week earlier, so the site can show movement."""
    if len(s.weeks) < 2: return None
    lw = s.last
    d = {k: v for k, v in s.__dict__.items() if k in ("NS", "L", "M", "PL", "draft", "tx", "reserve", "reserve_wk", "byes", "vegas", "notes", "projlog", "lineslog", "NP", "SP")}
    d["LIVE"] = None; d["weeks"] = [w for w in s.weeks if w < lw]
    d["W"] = {w: v for w, v in s.W.items() if w < lw}; d["G"] = {w: v for w, v in s.G.items() if w < lw}
    d["fut"] = dict(s.fut); d["fut"][lw] = [tuple(p) for p in s.G[lw]["pairs"]]
    d["rost"] = {r: [i for i, _ in s.W[lw][r]["S"] + s.W[lw][r]["B"] if i != "0"] for r in s.R}
    d["tx"] = [t for t in s.tx if t["w"] < lw]
    s0 = Ctx(d)
    TEAM0, _, wl0, _ = projections(s0, T)
    SIM0 = simulate(s0, TEAM0, wl0)
    W0, PF0, _ = s0.record()
    order = sorted(s.R, key=lambda r: (-W0[r], -PF0[r]))
    return dict(week=lw - 1, rank={r: k for k, r in enumerate(order, 1)}, odds=SIM0[0])

def odds_at(s, T, k, sims=200000):
    """Playoff, bye and title odds as they stood after week k (rosters as of the next week's lineups."""
    d = {kk: v for kk, v in s.__dict__.items() if kk in ("NS", "L", "M", "PL", "draft", "tx", "reserve", "reserve_wk", "byes", "vegas", "notes", "projlog", "lineslog", "NP", "SP")}
    d["LIVE"] = None; d["weeks"] = [w for w in s.weeks if w <= k]
    d["W"] = {w: v for w, v in s.W.items() if w <= k}; d["G"] = {w: v for w, v in s.G.items() if w <= k}
    d["fut"] = dict(s.fut)
    for w in s.weeks:
        if w > k: d["fut"][w] = [tuple(p) for p in s.G[w]["pairs"]]
    nw = k + 1
    d["rost"] = ({r: [i for i, _ in s.W[nw][r]["S"] + s.W[nw][r]["B"] if i != "0"] for r in s.R} if nw in s.W else dict(s.rost))
    d["tx"] = [t for t in s.tx if t["w"] <= k]
    s0 = Ctx(d)
    TEAM0, _, wl0, _ = projections(s0, T)
    return simulate(s0, TEAM0, wl0, sims=sims)[0]

def fseed(o):
    """Forecast seed: every seed weighted by its chance."""
    d = o.get("dist"); return sum((k + 1) * v for k, v in enumerate(d)) if d else None

def odds_history(s, T, SIM, path):
    """Running log of everyone's playoff, bye and title odds. A new snapshot is saved whenever an update changes them.
    The log starts after Week 9; earlier weeks are left out because they could only be rebuilt with hindsight."""
    import datetime as _dt
    snaps = []                                   # [label, ts, {r: (po, bye, ti)}]
    if os.path.exists(path):
        cur = None
        for l in open(path):
            if l.startswith("#") or "|" not in l: continue
            x = l.rstrip("\n").split("|"); ts, lab, r, po, by, ti = x[:6]; fs = float(x[6]) if len(x) > 6 and x[6] else None
            if not snaps or snaps[-1][1] != ts: snaps.append([lab, ts, {}])
            snaps[-1][2][int(r)] = (float(po), float(by), float(ti), fs)
    if not snaps and s.last >= 9:               # seed: the state after Week 9, rebuilt once from that week's rosters
        o = odds_at(s, T, 9) if s.last > 9 else SIM[0]
        snaps.append(["W9", "seed-9", {r: (o[r]["po"], o[r]["bye"], o[r]["ti"], fseed(o[r])) for r in s.R}])
    now = {r: (SIM[0][r]["po"], SIM[0][r]["bye"], SIM[0][r]["ti"], fseed(SIM[0][r])) for r in s.R}
    live = bool(getattr(s, "LIVE", None) and (s.LIVE or {}).get("done"))
    lab = f"W{s.nxt} live" if live else (f"Pre-W{s.nxt}" if any(x[0] == f"W{s.last}" for x in snaps) else f"W{s.last}")
    last = snaps[-1][2] if snaps else {}
    if any(abs(now[r][k] - last.get(r, (-1, -1, -1, None))[k]) > 0.0005 for r in s.R for k in range(3)):
        ts = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        snaps.append([lab, ts, now])                 # every update is kept (trades and waivers between weeks show as Pre-W)
    with open(path, "w") as f:
        f.write("# timestamp|label|roster_id|playoffs|bye|title|forecast_seed   (a row set per update)\n")
        for lab_, ts_, d in snaps:
            for r in sorted(d): f.write(f"{ts_}|{lab_}|{r}|{d[r][0]:.4f}|{d[r][1]:.4f}|{d[r][2]:.4f}|{'' if d[r][3] is None else f'{d[r][3]:.3f}'}\n")
    return snaps

def seed_possible(s, weeks_left):
    """Which final seeds each team can still mathematically reach. Every win/loss combination of the remaining games is checked;
    points-for (the tiebreaker) can still go any way, so within a group tied on wins any order counts. Ties in games are left out."""
    R = s.R; idx = {r: n for n, r in enumerate(R)}; W0, _, _ = s.record()
    games = [(idx[a], idx[b]) for w in weeks_left if w <= s.L.get("regular_season_weeks", 14) for a, b in s.fut.get(w, [])]
    nR = len(R); ok = {r: set() for r in R}
    if len(games) > 20:            # too many to enumerate exactly: use win bounds (who is sure to finish ahead or behind)
        left = {r: 0 for r in R}
        for a, b in games: left[R[a]] += 1; left[R[b]] += 1
        for r in R:
            hi = W0[r] + left[r]; lo = W0[r]
            ahead = sum(1 for o in R if o != r and W0[o] > hi)
            behind = sum(1 for o in R if o != r and W0[o] + left[o] < lo)
            ok[r] = set(range(ahead + 1, nR - behind + 1))
        return ok
    base = np.array([W0[r] for r in R], float); G = len(games)
    out = np.arange(2 ** G, dtype=np.int64)
    Wm = np.tile(base, (2 ** G, 1))
    for k, (a, b) in enumerate(games):
        bit = (out >> k) & 1
        Wm[:, a] += bit; Wm[:, b] += 1 - bit
    for r in R:
        i = idx[r]; me = Wm[:, i:i + 1]
        hi = (Wm > me).sum(1) + 1; lo = (Wm >= me).sum(1)          # best and worst seed this result allows
        pairs = np.unique(np.stack([hi, lo], 1), axis=0)
        for h, l in pairs: ok[r] |= set(range(int(h), int(l) + 1))
    return ok

def simulate(s, TEAM, weeks_left, sims=None, joint=False):
    R = s.R; idx = {r: n for n, r in enumerate(R)}; N = sims or CONFIG["sims"]; rng = np.random.default_rng(CONFIG["seed"]); jw = []
    W0, PF0, _ = s.record(); W = np.tile(np.array([W0[r] for r in R], float), (N, 1)); PF = np.tile(np.array([PF0[r] for r in R], float), (N, 1))
    res = {}; games = []
    for w in weeks_left:
        mu = np.array([TEAM[(w, r)]["mu"] for r in R]); sd = np.array([TEAM[(w, r)]["sd"] for r in R])
        sc = mu + rng.normal(size=(N, len(R))) * sd; PF += sc
        for a, b in s.fut[w]:
            i, j = idx[a], idx[b]; win = sc[:, i] > sc[:, j]; W[:, i] += win; W[:, j] += ~win
            res[(w, a)] = (win, b); res[(w, b)] = (~win, a)
            if joint and w == weeks_left[0]: jw.append((a, b, win))
            games.append((w, a, mu[i], b, mu[j], norm.cdf((mu[i] - mu[j]) / math.hypot(sd[i], sd[j]))))
    order = np.argsort(-(W * 1e5 + PF), axis=1); seed = np.empty_like(order); seed[np.arange(N)[:, None], order] = np.arange(len(R))
    full = max(weeks_left, key=lambda w: len(s.byes.get(w, [])) == 0)  # a bye-free week ≈ playoff strength
    full = [w for w in weeks_left if not s.byes.get(w)] or weeks_left
    mu = np.array([np.mean([TEAM[(w, r)]["mu"] for w in full]) for r in R]); sd = np.array([np.mean([TEAM[(w, r)]["sd"] for w in full]) for r in R])
    g = lambda t: mu[t] + rng.normal(size=N) * sd[t]; play = lambda a, b: np.where(g(a) > g(b), a, b)
    P_, B_ = s.L["playoff_teams"], s.L["playoff_byes"]
    sd_ = [order[:, k] for k in range(P_)]
    # bracket: top B_ seeds bye; remaining seeds play high vs low; bye seeds meet the lowest remaining
    if P_ == 6 and B_ == 2:
        q1 = play(sd_[3], sd_[4]); q2 = play(sd_[2], sd_[5]); f1 = play(sd_[0], q1); f2 = play(sd_[1], q2); ch = play(f1, f2)
    else:
        raise NotImplementedError("bracket for this playoff format")
    out = {}
    for r in R:
        i = idx[r]
        out[r] = dict(pw=W[:, i].mean(), po=(seed[:, i] < P_).mean(), bye=(seed[:, i] < B_).mean(), s1=(seed[:, i] == 0).mean(), fin=((f1 == i) | (f2 == i)).mean(), semi=((seed[:, i] < B_) | (q1 == i) | (q2 == i)).mean(), ti=(ch == i).mean(),
                      dist=[(seed[:, i] == k).mean() for k in range(len(R))])
    pairs = Counter(zip(np.minimum(f1, f2), np.maximum(f1, f2))); finals = []
    for (a, b), c in pairs.most_common(6):
        m = ((f1 == a) & (f2 == b)) | ((f1 == b) & (f2 == a)); finals.append((R[a], R[b], c / N, (ch[m] == a).mean()))
    lev = []
    for (w, r), (win, opp) in res.items():
        i = idx[r]; po = seed[:, i] < P_; by = seed[:, i] < B_; ti = ch == i
        lev.append(dict(w=w, r=r, opp=opp, pw=win.mean(), po_w=po[win].mean(), po_l=po[~win].mean(), by_w=by[win].mean(), by_l=by[~win].mean(), ti_w=ti[win].mean(), ti_l=ti[~win].mean()))
    if joint:          # everyone's odds under each way the first week's games can finish: lets odds move play by play during that week
        code = np.zeros(N, dtype=np.int64)
        for g_, (_, _, win) in enumerate(jw): code |= (win.astype(np.int64) << g_)
        cond = {}
        for c in np.unique(code):
            m = code == c
            cond[int(c)] = {r: ((seed[m, idx[r]] < P_).mean(), (seed[m, idx[r]] < B_).mean(), (ch[m] == idx[r]).mean(), (seed[m, idx[r]] + 1).mean()) for r in R}
        return out, games, finals, lev, dict(games=[(a, b) for a, b, _ in jw], O=cond)
    return out, games, finals, lev

def odds_cond(s, T, k, sims=120000):
    """Week k's conditional odds table, as things stood before its games: {games, O: {outcome bits: {team: (po, bye, title, seed)}}}."""
    d = {kk: v for kk, v in s.__dict__.items() if kk in ("NS", "L", "M", "PL", "draft", "tx", "reserve", "reserve_wk", "byes", "vegas", "notes", "projlog", "lineslog", "NP", "SP")}
    d["LIVE"] = None; d["weeks"] = [w for w in s.weeks if w < k]
    d["W"] = {w: v for w, v in s.W.items() if w < k}; d["G"] = {w: v for w, v in s.G.items() if w < k}
    d["fut"] = dict(s.fut)
    for w in s.weeks:
        if w >= k: d["fut"][w] = [tuple(p) for p in s.G[w]["pairs"]]
    d["rost"] = ({r: [i for i, _ in s.W[k][r]["S"] + s.W[k][r]["B"] if i != "0"] for r in s.R} if k in s.W else dict(s.rost))
    d["tx"] = [t_ for t_ in s.tx if t_["w"] < k]
    s0 = Ctx(d)
    TEAM0, _, wl0, _ = projections(s0, T)
    if not wl0 or wl0[0] != k: return None
    return simulate(s0, TEAM0, wl0, sims=sims, joint=True)[4]

def title_leverage(s, T, path, sims=40000):
    """Each finished regular-season week, as it stood before its games: every team's title and playoff odds with a win and with a loss.
    It's what a game was worth, so a play's swing in win chance times this is the title odds it added (CPA).
    Saved once per week (it only depends on how things stood then), so a build only simulates a week the first time."""
    have = {}
    if os.path.exists(path):
        for l in open(path):
            if l.startswith("#") or "|" not in l: continue
            w, r, tw, tl, pw, pl = l.rstrip("\n").split("|")[:6]; have[(int(w), int(r))] = (float(tw), float(tl), float(pw), float(pl))
    reg = s.L.get("regular_season_weeks", 14); new = False
    for k in [w for w in s.weeks if w <= min(s.last, reg)]:
        if all((k, r) in have for r in s.R): continue
        d = {kk: v for kk, v in s.__dict__.items() if kk in ("NS", "L", "M", "PL", "draft", "tx", "reserve", "reserve_wk", "byes", "vegas", "notes", "projlog", "lineslog", "NP", "SP")}
        d["LIVE"] = None; d["weeks"] = [w for w in s.weeks if w < k]
        d["W"] = {w: v for w, v in s.W.items() if w < k}; d["G"] = {w: v for w, v in s.G.items() if w < k}
        d["fut"] = dict(s.fut)
        for w in s.weeks:
            if w >= k: d["fut"][w] = [tuple(p) for p in s.G[w]["pairs"]]
        d["rost"] = {r: [i for i, _ in s.W[k][r]["S"] + s.W[k][r]["B"] if i != "0"] for r in s.R}
        d["tx"] = [t_ for t_ in s.tx if t_["w"] < k]
        try:
            s0 = Ctx(d); TEAM0, _, wl0, _ = projections(s0, T)
            if not wl0 or wl0[0] != k: continue
            for x in simulate(s0, TEAM0, wl0, sims=sims)[3]:
                if x["w"] == k: have[(k, x["r"])] = (x["ti_w"], x["ti_l"], x["po_w"], x["po_l"]); new = True
        except Exception as ex: print("title_leverage", k, ex)
    if new:
        with open(path, "w") as f:
            f.write("# week|roster_id|title odds with a win|with a loss|playoff odds with a win|with a loss   (before that week's games)\n")
            for (w, r), v in sorted(have.items()): f.write(f"{w}|{r}|{v[0]:.4f}|{v[1]:.4f}|{v[2]:.4f}|{v[3]:.4f}\n")
    return have

def american(p):
    if p >= 0.999: return "off the board"
    if p <= 0.001: return "off the board"
    v = -p / (1 - p) * 100 if p >= 0.5 else (1 - p) / p * 100
    r = 100 if abs(v) > 3000 else 10 if abs(v) > 1000 else 1
    v = round(v / r) * r
    return f"{int(v)}" if p >= 0.5 else f"+{int(v)}"

def doc_projections(s, T, TEAM, proj, weeks_left, IT, SIM):
    out, games, finals, _ = SIM; wk0 = s.nxt; W0, _, _ = s.record(); n = len(s.weeks)
    o = [f"# Super League: Projections (Week {wk0} edition)", "", f"Built after Week {s.last}. Rebuilt every week.", "", "## Model",
         f"- **Player projection:** Sleeper's projected stats for the week, **rescored in this league's settings** (kicker FG distance from each kicker's own projected 30-39 / 40-49 / 50+ mix, with yards per bucket fit from 2026 actuals). Sleeper already builds in matchups, Vegas, depth charts and injuries; Out/IR/bye players get no projection. Weeks without a Sleeper file use each player's last 3 Sleeper projections.",
         f"- **Why Sleeper alone:** walk-forward backtest, Weeks {T['weeks'][0]}-{T['weeks'][-1]}. A blend with each player's own 2026 average is only used if it beats Sleeper by >{CONFIG['blend_min_gain'] * 100:.0f}% RMSE (it doesn't yet; table below). Vegas isn't applied again on top, since Sleeper already uses it.",
         f"- **Extra injury discounts:** {CONFIG['injury_mult']}.",
         f"- **Waiver pickups:** free agents = every projected player not on a roster; model uses the 3rd-best at each position and adds only for a {CONFIG['pickup_min_gain']}+ pt lineup gain, max {CONFIG['pickup_max']}/week.",
         f"- **Uncertainty:** player SD = position error rate from the backtest (" + ", ".join(f"{p} {v:.2f}" for p, v in T["cv"].items()) + f" × projection) × {T['corr']:.2f} team factor (calibrated so backtest z-SD = 1).",
         f"- **Backtest, team level (actual starters):** RMSE {T['rmse']:.1f} vs naive team-average {T['naive']:.1f}; bias {T['bias']:+.1f}.",
         f"- **Sim:** {CONFIG['sims']:,} seasons, {s.L['playoff_teams']}-team playoffs, top {s.L['playoff_byes']} bye, {s.L['tiebreaker']} tiebreaker.", "",
         "### Backtest by position (RMSE, bias)", ""] + md_table(["Pos", "Player-weeks", "Sleeper", "Own 2026 avg", "Best blend (Sleeper wt)", "Used"], [(p, x["n"], f"{x['S']:.2f} ({x['Sb']:+.2f})", f"{x['O']:.2f} ({x['Ob']:+.2f})", f"{x['b']:.2f} ({x['bw']:.2f})", "Sleeper" if x["use"] >= 1 else f"blend {x['use']:.2f}") for p, x in T["table"].items()]) + ["", "## Rest-of-season odds", ""]
    order = sorted(s.R, key=lambda r: (-out[r]["po"], -out[r]["ti"]))
    o += md_table(["Team", "Rec", "Proj W", "Playoffs", "Bye", "#1 seed", "Final", "Title"], [(s.M[r], s.rec(r), f"{out[r]['pw']:.1f}", f"{out[r]['po'] * 100:.1f}%", f"{out[r]['bye'] * 100:.1f}%", f"{out[r]['s1'] * 100:.1f}%", f"{out[r]['fin'] * 100:.1f}%", f"{out[r]['ti'] * 100:.1f}%") for r in order])
    o += ["", "## Fair betting odds (no vig)", ""] + md_table(["Team", "Make playoffs", "Bye", "Title"], [(s.M[r], american(out[r]["po"]), american(out[r]["bye"]), american(out[r]["ti"])) for r in order])
    o += ["", "## Most likely finals", ""] + md_table(["Final", "Chance", "Winner"], [(f"{s.M[a]} vs {s.M[b]}", f"{c * 100:.1f}%", f"{s.M[a]} {p * 100:.0f}%") for a, b, c, p in finals])
    o += ["", "## Seed distribution (%)", ""] + md_table(["Team"] + [str(k) for k in range(1, len(s.R) + 1)], [[s.M[r]] + [f"{x * 100:.0f}" for x in out[r]["dist"]] for r in order])
    o += ["", f"## Week {wk0} matchups", ""] + md_table(["Matchup", "Proj", "Win %"], [(f"{s.M[a]} vs {s.M[b]}", f"{ma:.1f} - {mb:.1f}", f"{p * 100:.0f}% / {100 - p * 100:.0f}%") for w, a, ma, b, mb, p in games if w == wk0])
    o += ["", f"## Week {wk0} optimal lineups (start/sit)", "", "(pickup) = free agent the model assumes you add.", ""]
    for r in s.R:
        t = TEAM[(wk0, r)]; ch = set(t["lineup"])
        o.append(f"**{s.M[r]}** ({t['mu']:.1f}): " + ", ".join(f"{s.nm(i)} {proj(i, wk0)[0]:.1f}" + (" (pickup)" if i in t["adds"] else "") for i in t["lineup"]))
        o.append("- Bench: " + ", ".join(f"{s.nm(i)} {proj(i, wk0)[0]:.1f}" + (f" ({s.PL[i]['inj']})" if s.PL.get(i, {}).get("inj") else "") + (f" ({proj(i, wk0)[1]})" if proj(i, wk0)[1] and proj(i, wk0)[1] != s.PL.get(i, {}).get("inj") else "") for i in sorted(t["all"], key=lambda i: -proj(i, wk0)[0]) if i not in ch))
    o += ["", "## Assumed pickups", ""] + md_table(["Wk", "Team", "Add", "Proj without → with"], [(w, s.M[r], ", ".join(f"{s.nm(i)} ({s.pos(i)})" for i in TEAM[(w, r)]["adds"]), f"{TEAM[(w, r)]['base']:.1f} → {TEAM[(w, r)]['mu']:.1f}") for w in weeks_left for r in s.R if TEAM[(w, r)]["adds"]])
    o += ["", "## Later matchups", ""] + md_table(["Wk", "Matchup", "Proj", "Win %"], [(w, f"{s.M[a]} vs {s.M[b]}", f"{ma:.1f} - {mb:.1f}", f"{p * 100:.0f}% / {100 - p * 100:.0f}%") for w, a, ma, b, mb, p in games if w > wk0])
    if "projections" in s.notes: o += ["", "## Why the odds look like this", "", s.notes["projections"]]
    acc = []
    for w in sorted(s.projlog):
        if w not in s.G: continue
        for r in s.R:
            mu_, sd_ = s.projlog[w][r]; a = s.G[w]["scores"][r]; acc.append((w, s.M[r], f"{mu_:.1f}", f"{a:.1f}", f"{a - mu_:+.1f}", f"{(a - mu_) / sd_:+.2f}"))
    o += ["", "## Accuracy log (projected vs actual)", ""]
    if acc:
        e = np.array([float(x[4]) for x in acc]); z = np.array([float(x[5]) for x in acc])
        o += [f"All weeks logged: RMSE {math.sqrt((e ** 2).mean()):.1f}, bias {e.mean():+.1f}, z-SD {z.std():.2f} (1.00 = ranges well calibrated).", ""] + md_table(["Wk", "Team", "Proj", "Actual", "Error", "z"], acc)
    else:
        o.append(f"First logged week is Week {s.nxt}; it fills in after that week is played.")
    return "\n".join(o)

def ml(p):
    p = min(max(p, 0.001), 0.999)
    return f"{-round(p / (1 - p) * 100)}" if p >= 0.5 else f"+{round((1 - p) / p * 100)}"

def half(x): return round(x * 2) / 2

def make_lines(s, T, TEAM):
    wk0 = s.nxt; f = T["line_factor"]; out = []
    for a, b in s.fut.get(wk0, []):
        ma, mb = TEAM[(wk0, a)]["mu"] * f, TEAM[(wk0, b)]["mu"] * f; sa, sb = TEAM[(wk0, a)]["sd"] * f, TEAM[(wk0, b)]["sd"] * f
        fav, dog = (a, b) if ma >= mb else (b, a); m = abs(ma - mb); sdm = math.hypot(sa, sb); p = norm.cdf(m / sdm) if sdm > 0 else (1.0 if m > 0 else 0.5)          # both teams done: it's decided
        out.append(dict(a=a, b=b, ma=ma, mb=mb, fav=fav, dog=dog, spread=half(m), total=half(ma + mb), p=p, sd_m=math.hypot(sa, sb)))
    return out

def doc_lines(s, T, TEAM, proj):
    wk0 = s.nxt; L = make_lines(s, T, TEAM)
    o = [f"# Super League: Week {wk0} Lines", "", f"Built after Week {s.last}. Fair lines (no vig): each side is a 50/50 bet.", "", "## How they're set",
         f"- Each team = the projections' **optimal lineup** (incl. modeled pickups) × the **line factor {T['line_factor']:.3f}**.",
         f"- **Line factor** = actual points ÷ projected optimal lineup, backtested over Weeks 4-{s.last} ({T['line_n']} team-games). It covers lineup mistakes and model bias in one number, and is recalculated every week.",
         "- **Spread** = projected margin, **O/U** = projected combined score, both rounded to the half point. **Win %** from the projected margin and each team's uncertainty.", "",
         "## Lines", ""]
    o += md_table(["Matchup", "Spread", "O/U", "Win %", "Proj score"],
                  [(f"{s.M[x['a']]} vs {s.M[x['b']]}", f"{s.M[x['fav']]} -{x['spread']:.1f}" if x["spread"] > 0 else "PK", f"{x['total']:.1f}",
                    f"{s.M[x['fav']]} {x['p'] * 100:.0f}% / {s.M[x['dog']]} {100 - round(x['p'] * 100)}%", f"{s.M[x['a']]} {x['ma']:.1f} - {x['mb']:.1f} {s.M[x['b']]}") for x in L])
    if "lines" in s.notes: o += ["", "## What's driving the lines", "", s.notes["lines"]]
    # grading of past weeks' lines
    g = []
    for w in sorted(s.lineslog):
        if w not in s.G: continue
        for fav, dog, sp, tot in s.lineslog[w]:
            sf, sd_ = s.G[w]["scores"][fav], s.G[w]["scores"][dog]; marg = sf - sd_; t = sf + sd_
            g.append((w, f"{s.M[fav]} -{sp} vs {s.M[dog]}", f"{marg:+.1f}", "cover" if marg > sp else ("push" if marg == sp else "no cover"), tot, f"{t:.1f}", "over" if t > tot else ("push" if t == tot else "under"), marg - sp, t - tot))
    o += ["", "## Line grading (past weeks)", ""]
    if g:
        cov = sum(x[3] == "cover" for x in g); ov = sum(x[6] == "over" for x in g); n = len(g)
        o += [f"Favorites covered {cov}/{n}; overs {ov}/{n}. Avg spread miss {np.mean([abs(x[7]) for x in g]):.1f}, avg total miss {np.mean([abs(x[8]) for x in g]):.1f}, total bias {np.mean([x[8] for x in g]):+.1f} (0 = right on average).", ""]
        o += md_table(["Wk", "Line", "Fav margin", "ATS", "Total", "Actual", "O/U"], [x[:7] for x in g])
    else:
        o.append(f"First graded week is Week {wk0}.")
    return "\n".join(o), L

def doc_leverage(s, SIM):
    _, _, _, lev = SIM; wk0 = s.nxt
    o = ["# Super League: Playoff Leverage", "", "Odds if you win − odds if you lose, from the projections sim.", "", f"## Week {wk0}: every team", ""]
    o += md_table(["Team", "Opp", "Win %", "Playoffs if W", "if L", "Swing", "Bye if W", "if L", "Swing"],
                  [(s.M[x["r"]], s.M[x["opp"]], f"{x['pw'] * 100:.0f}%", f"{x['po_w'] * 100:.1f}%", f"{x['po_l'] * 100:.1f}%", f"{(x['po_w'] - x['po_l']) * 100:+.1f}", f"{x['by_w'] * 100:.1f}%", f"{x['by_l'] * 100:.1f}%", f"{(x['by_w'] - x['by_l']) * 100:+.1f}") for x in sorted([x for x in lev if x["w"] == wk0], key=lambda x: -x["po_w"])])
    gm = Counter()
    for x in lev: gm[(x["w"], tuple(sorted([x["r"], x["opp"]])))] += abs(x["po_w"] - x["po_l"])
    o += ["", "## Biggest games left (combined playoff swing)", ""] + md_table(["Wk", "Game", "Swing"], [(w, f"{s.M[a]} vs {s.M[b]}", f"{v * 100:.1f} pts") for (w, (a, b)), v in gm.most_common(10)])
    o += ["", "## Every team, every game", ""]
    for r in s.R:
        o += [f"### {s.M[r]}", ""] + md_table(["Wk", "Opp", "Win %", "Playoffs W → L", "Bye W → L", "Title W → L"], [(x["w"], s.M[x["opp"]], f"{x['pw'] * 100:.0f}%", f"{x['po_w'] * 100:.1f}% → {x['po_l'] * 100:.1f}%", f"{x['by_w'] * 100:.1f}% → {x['by_l'] * 100:.1f}%", f"{x['ti_w'] * 100:.1f}% → {x['ti_l'] * 100:.1f}%") for x in sorted([x for x in lev if x["r"] == r], key=lambda x: x["w"])]) + [""]
    return "\n".join(o)

def doc_power(s, TEAM, weeks_left, SIM):
    out = SIM[0]; n = len(s.weeks); W0, PF, _ = s.record()
    sc = {r: [s.G[w]["scores"][r] for w in s.weeks] for r in s.R}
    ppg = {r: np.mean(sc[r]) for r in s.R}; l3 = {r: np.mean(sc[r][-3:]) for r in s.R}; ros = {r: np.mean([TEAM[(w, r)]["mu"] for w in weeks_left]) for r in s.R}
    opp = len(s.R) - 1; ap = {r: sum(sum(s.G[w]["scores"][r] > s.G[w]["scores"][o_] for o_ in s.R if o_ != r) for w in s.weeks) / (opp * n) for r in s.R}
    c = lambda d: {k: v - np.mean(list(d.values())) for k, v in d.items()}
    cp, cl, cr = c(ppg), c(l3), c(ros); pw = {r: 0.5 * cr[r] + 0.3 * cp[r] + 0.2 * cl[r] for r in s.R}
    order = sorted(s.R, key=lambda r: -pw[r]); stand = sorted(s.R, key=lambda r: (-W0[r], -PF[r]))
    s.power = [dict(r=r, pw=pw[r], st=stand.index(r) + 1, ros=ros[r], ppg=ppg[r], l3=l3[r], ap=ap[r]) for r in order]
    o = [f"# Super League: Power Rankings (pre-Week {s.nxt})", "", "**Standings** = what happened. **Power** = who's best right now (who you'd pick in a neutral game this week).", "",
         "Power = points/week better than an average team: 50% rest-of-season projection, 30% season PPG, 20% last 3 weeks. ↑/↓ = spots vs standings.", ""]
    rows_ = []
    for k, r in enumerate(order, 1):
        st = stand.index(r) + 1; mv = st - k
        rows_.append((k, s.M[r], f"{pw[r]:+.1f}", f"{st} ({'↑' + str(mv) if mv > 0 else ('↓' + str(-mv) if mv < 0 else '–')})", s.rec(r), f"{ros[r]:.1f}", f"{ppg[r]:.1f}", f"{l3[r]:.1f}", f"{ap[r] * 100:.0f}%", f"{out[r]['ti'] * 100:.1f}%"))
    o += md_table(["Rank", "Team", "Power", "Standing", "Record", "ROS proj", "Season PPG", "Last 3", "All-play", "Title %"], rows_)
    if "power" in s.notes: o += ["", s.notes["power"]]
    return "\n".join(o)

# ----------------------------------------------------------------------------- main
def main():
    D = sys.argv[1] if len(sys.argv) > 1 else "data"; O = sys.argv[2] if len(sys.argv) > 2 else "out"
    globals()["DATA_DIR"] = D
    os.makedirs(O, exist_ok=True)
    s = Ctx(load(D)); s.ddir = D
    # sanity: starter sums are the scores by construction; flag duplicate pairings
    for w in s.weeks:
        assert all(len(p) == 2 for p in s.G[w]["pairs"]), f"bad pairing week {w}"
    T = tune(s)
    TEAM, proj, weeks_left, IT = projections(s, T)
    s.prev = prev_week(s, T)
    apply_live(s, T, TEAM, proj)
    s.live_fin = []          # this week's starts whose NFL game is final: they count now
    if (getattr(s, "LIVE", None) or {}).get("done"):
        for r in s.R:
            lv = (TEAM.get((s.nxt, r)) or {}).get("live")
            if lv: s.live_fin += [(r, i, p) for i, p in lv["played"].items() if i in lv["starters"] and i not in lv.get("inprog", ())]
    SIM = simulate(s, TEAM, weeks_left)
    s.ohist = odds_history(s, T, SIM, os.path.join(D, "odds_log.txt"))
    s.ocond = {}                  # play-by-play odds tracker: each tracked week's conditional odds table
    for k in sorted({int(x[0][1:].split()[0].replace("-W", "")) for x in s.ohist if x[0].startswith("W")} | {s.nxt}):
        if k in s.weeks or k == s.nxt:
            if k == 9: continue
            try: s.ocond[k] = odds_cond(s, T, k)
            except Exception as ex: print("odds_cond", k, ex)
    s.tlev = title_leverage(s, T, os.path.join(D, "title_lev.txt"))
    s.mlog = match_history(s, T, TEAM, os.path.join(D, "match_log.txt"))
    s.livewp = live_history(s, T, TEAM, os.path.join(D, "live_wp.txt"))
    s.seedok = seed_possible(s, weeks_left)
    docs = {
        "3-season-2026": doc_season(s), "5-transactions-2026": doc_transactions(s), "7-stats-book": doc_stats(s),
        "8-lineups-and-player-log": doc_lineups(s), "10-projections": doc_projections(s, T, TEAM, proj, weeks_left, IT, SIM),
        "11-player-stats": doc_player_stats(s), "12-war-and-lineup-timing": doc_war(s), 
        "14-playoff-leverage": doc_leverage(s, SIM), "15-power-rankings": doc_power(s, TEAM, weeks_left, SIM), "16-weekly-mvp": doc_awards(s),
        "17-season-mvp": doc_season_mvp(s), "18-roty-and-undrafted": doc_roty(s), "19-trade-scorecard": doc_trades(s) + "\n" + doc_trades_forward(s, T, TEAM, proj, weeks_left, SIM),
    }
    docs["20-weekly-lines"], L = doc_lines(s, T, TEAM, proj)
    for k, v in docs.items(): open(f"{O}/{k}.md", "w").write(v + "\n")
    try:
        import site_builder
        os.makedirs(f"{O}/site/team", exist_ok=True); os.makedirs(f"{O}/site/game", exist_ok=True)
        s.mval = move_values(s)       # every move graded: best lineup with it minus without it, each week since
        for fn, page in site_builder.build_site(s, T, TEAM, SIM, L, weeks_left, starts_pm, season_pm, f"{D}/logos", proj, f"{D}/fonts").items():
            open(f"{O}/site/{fn}", "w").write(page)
        import og; og.make(site_builder.LAST_SITE, f"{O}/site", D)
        import shutil; shutil.copytree(f"{D}/logos", f"{O}/site/logos", dirs_exist_ok=True) if os.path.isdir(f"{D}/logos") else None
        shutil.copytree(f"{D}/fonts", f"{O}/site/fonts", dirs_exist_ok=True) if os.path.isdir(f"{D}/fonts") else None
    except ImportError:
        pass
    open(f"{O}/lines_{s.nxt}.txt", "w").write(f"# favorite_roster|underdog_roster|spread|total  (Week {s.nxt})\n" + "\n".join(f"{x['fav']}|{x['dog']}|{x['spread']}|{x['total']}" for x in L) + "\n")
    # store this week's team projections so next week's run can grade them (save to data/ with the other files)
    open(f"{O}/teamproj_{s.nxt}.txt", "w").write(f"# roster_id|projected|sd  (Week {s.nxt}, made after Week {s.last})\n" + "\n".join(f"{r}|{TEAM[(s.nxt, r)]['mu']:.2f}|{TEAM[(s.nxt, r)]['sd']:.2f}" for r in s.R) + "\n")
    print(f"weeks {s.weeks[0]}-{s.last}, next {s.nxt}; trades {len(s.trades)} ({sum(t['vetoed'] for t in s.trades)} vetoed); repl {({k: round(v, 1) for k, v in s.repl['val'].items()})}; ppw {s.ppw:.1f}; model {({k: (round(v, 3) if isinstance(v, float) else v) for k, v in T.items() if k in ('rmse', 'bias', 'zsd', 'naive', 'corr', 'line_factor', 'line_n', 'wts')})}")

if __name__ == "__main__":
    main()
