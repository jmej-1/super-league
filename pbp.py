"""Play-by-play fantasy points and in-game win probability.

ESPN play text names players as "F.Last". Each play is turned into fantasy points for the Super League scoring
(yards, catches, TDs, picks, fumbles, kicks, defense), then every player's running total is anchored to his real
Sleeper final: whatever the text missed (2-pt tries, return yards, stat corrections) is spread evenly over the game clock,
so the end of every game is exact and the swings in between are the real plays."""
import os, re, json, glob, math, datetime as dt
from collections import defaultdict
from scipy.stats import norm

ESPN = {"WSH": "WAS"}
SUF = re.compile(r"\s+(Jr\.?|Sr\.?|II|III|IV|V)$")
YDS = re.compile(r" for (-?\d+) yards?| for no gain")
FGD = re.compile(r"(\d+) yard field goal")
ISO = "%Y-%m-%dT%H:%M:%SZ"

def key_of(full):
    full = SUF.sub("", full.strip())
    if " " not in full: return None
    first, rest = full.split(" ", 1)
    return f"{first[0]}.{rest}"

def tier(pa):
    return 10 if pa == 0 else 7 if pa <= 6 else 4 if pa <= 13 else 1 if pa <= 20 else 0 if pa <= 27 else -1 if pa <= 34 else -4

PA_AVG, PA_SD = 22.0, 10.0                       # an NFL offense scores about 22, give or take 10
_Z = [norm.ppf((k + 0.5) / 41) for k in range(41)]
def exp_tier(pa_now, f):
    """Expected points-allowed bonus at the final, given points allowed so far and the share of the game played."""
    left = max(0.0, 1.0 - f)
    if left <= 0: return float(tier(pa_now))
    m, sd = PA_AVG * left, PA_SD * math.sqrt(left)
    return sum(tier(pa_now + max(0, round(m + z * sd))) for z in _Z) / len(_Z)
E0 = None

def load(D):
    G = {}
    for f in glob.glob(os.path.join(D, "pbp", "*.json")):
        try: g = json.load(open(f))
        except Exception: continue
        g["away"] = ESPN.get(g["away"], g["away"]); g["home"] = ESPN.get(g["home"], g["home"])
        g["tid"] = {k: ESPN.get(v, v) for k, v in (g.get("tid") or {}).items()}
        G[g["id"]] = g
    return G

def frac_of(period, clock):
    return max(0.0, min(1.0, ((period - 1) * 900 + (900 - clock)) / 3600)) if period <= 4 else 1.0

def parse_game(g, cands):
    """cands: {team: [(pid, key)]}. Returns (times, fracs, cum) with cum[pid] = running fantasy points after each play."""
    away, home = g["away"], g["home"]
    keys = {}                                    # key -> [(pid, team)]
    for t in (away, home):
        for pid, k in cands.get(t, []):
            if k: keys.setdefault(k, []).append((pid, t))
    pat = re.compile(r"(?<![A-Za-z])(" + "|".join(sorted((re.escape(k) for k in keys), key=len, reverse=True)) + r")(?![a-z])") if keys else None
    plays = g["plays"]
    # fill missing wall clocks from the neighbours
    last = None
    for p in plays:
        if p[0]: last = p[0]
        elif last: p[0] = last
    first = next((p[0] for p in plays if p[0]), None)
    for p in plays:
        if not p[0]: p[0] = first or g["kick"].replace("Z", ":00Z")
    # ESPN sometimes stamps a game's last plays hours (or a day) late. A jump of more than 50 minutes between plays
    # never happens in a real game (halftime is ~20), so pull everything after it back to a minute after the play before.
    import datetime as _dt
    fmt_ = "%Y-%m-%dT%H:%M:%SZ"; shift = _dt.timedelta(0); prev = None
    for p in plays:
        tt = _dt.datetime.strptime(p[0], fmt_) - shift
        if prev is not None and tt - prev > _dt.timedelta(minutes=50):
            shift += tt - prev - _dt.timedelta(minutes=1); tt = prev + _dt.timedelta(minutes=1)
        p[0] = tt.strftime(fmt_); prev = tt
    run = defaultdict(float); times, fracs, cum, pas = [], [], [], []
    pa = {away: 0, home: 0}                      # points each defense has allowed
    for p in plays:
        wc, per, clk, typ, txt, asc, hsc, ofid = p[:8]; tov = p[8] if len(p) > 8 else 0
        off = g["tid"].get(str(ofid)); dfn = home if off == away else away if off == home else None
        if "No Play" in txt or typ in ("Penalty", "Timeout", "Official Timeout", "End Period", "End of Half", "End of Game", "Two-minute warning"):
            hits = []
        else:
            hits = []
            if pat:
                for m in pat.finditer(txt):
                    opts = keys[m.group(1)]
                    pick = next((x for x in opts if x[1] == off), None) if len(opts) > 1 else opts[0]
                    hits.append((m.start(), (pick or opts[0])[0], (pick or opts[0])[1]))
        yd_m = YDS.search(txt); yd = int(yd_m.group(1)) if (yd_m and yd_m.group(1)) else 0
        td = "TOUCHDOWN" in txt and "NULLIFIED" not in txt
        names = [h[1] for h in hits]
        if typ in ("Pass Reception", "Passing Touchdown") and names:
            qb = names[0]; run[qb] += yd * 0.04 + (4 if td else 0)
            m = re.search(r" to ([A-Z][^ ]*)", txt)
            rc = next((h[1] for h in hits if m and h[0] >= m.start()), names[1] if len(names) > 1 else None)
            if rc and rc != qb: run[rc] += 0.5 + yd * 0.1 + (6 if td else 0)
        elif typ in ("Rush", "Rushing Touchdown") and names:
            run[names[0]] += yd * 0.1 + (6 if td else 0)
        elif typ in ("Pass Interception Return", "Interception Return Touchdown") and names:
            run[names[0]] += -2
            if dfn: run[dfn] += 2 + (6 if td else 0)
        elif typ in ("Sack",) and dfn:
            run[dfn] += 1
        elif typ == "Safety" and dfn:
            run[dfn] += 2 + (1 if "sacked" in txt else 0)
        elif typ == "Field Goal Good" and names:
            m = FGD.search(txt); d_ = int(m.group(1)) if m else 30
            run[names[0]] += 2 + 0.1 * max(0, d_ - 30)
        elif typ in ("Field Goal Missed", "Blocked Field Goal") and names:
            run[names[0]] += -1
            if typ == "Blocked Field Goal" and dfn: run[dfn] += 1
        if "extra point is GOOD" in txt or "extra point is No Good" in txt or "extra point is BLOCKED" in txt:
            m = re.search(r"([A-Z][A-Za-z'\-\. ]{1,25}) extra point is (GOOD|No Good|BLOCKED)", txt)
            kk = next((h[1] for h in hits if m and h[0] >= m.start() - 1 and h[0] <= m.end()), None)
            if kk: run[kk] += 0.5 if m.group(2) == "GOOD" else -1
        if tov and "FUMBLES" in txt and names:
            run[names[0]] += -2
            if dfn: run[dfn] += 2 + (6 if td else 0)
        # a defense's points-allowed bonus is settled at the final, so it isn't counted mid-game: it rides in with the anchor,
        # spread over the game clock, instead of showing up as +10 at kickoff
        pa[home] = asc; pa[away] = hsc                     # points each defense has allowed so far
        times.append(wc); fracs.append(frac_of(per, clk)); cum.append(dict(run)); pas.append(dict(pa))
    # ESPN sometimes leads a game with stray rows stamped at kickoff but carrying a later game clock (halftime, end of game).
    # Drop any row whose clock is ahead of a later row's: the clock only moves forward.
    # Keep the longest run of rows where the clock never goes backward (stray rows at the start or end fall out).
    import bisect
    tails = []; tix = []; par = [-1] * len(fracs)
    for k, f_ in enumerate(fracs):
        j = bisect.bisect_right(tails, f_ + 1e-9)
        if j == len(tails): tails.append(f_); tix.append(k)
        else: tails[j] = f_; tix[j] = k
        par[k] = tix[j - 1] if j else -1
    keep = []; k = tix[-1] if tix else -1
    while k >= 0: keep.append(k); k = par[k]
    keep.reverse()
    if len(keep) < len(fracs):
        times = [times[k] for k in keep]; fracs = [fracs[k] for k in keep]; cum = [cum[k] for k in keep]; pas = [pas[k] for k in keep]
    return times, fracs, cum, pas

def game_paths(G, w, actual, team_of, name_of, pos_of, extra=()):
    """For every NFL game in week w: {team: (times, fracs, {pid: [cum...]})} anchored to actual finals.
    actual: {pid: final pts} (players who played that week). team_of(pid) -> NFL team."""
    cands = defaultdict(list)
    for pid in set(actual) | set(extra):          # extra: everyone on an NFL roster, for games still in progress (no finals yet)
        t = team_of(pid)
        if not t: continue
        cands[t].append((pid, key_of(name_of(pid)) if pid.isdigit() else None))
    out = {}
    for g in G.values():
        if g["w"] != w: continue
        times, fracs, cum, pas = parse_game(g, cands)
        if not times: continue
        ids = {pid for t in (g["away"], g["home"]) for pid, _ in cands.get(t, [])} | {g["away"], g["home"]}
        paths = {}
        last_f = fracs[-1] if g.get("final") else None
        for pid in ids:
            seq = [c.get(pid, 0.0) for c in cum]
            if pid in actual and g.get("final"):          # anchor: the miss is spread over the game clock
                miss = actual[pid] - seq[-1] - (tier(pas[-1].get(pid, 0)) if not pid.isdigit() else 0)   # a defense's final bonus is added live, below
                seq = [v + miss * (f / (last_f or 1.0)) for v, f in zip(seq, fracs)]
            paths[pid] = seq
        for t_ in (g["away"], g["home"]): paths[("pa", t_)] = [x.get(t_, 0) for x in pas]
        paths[("opp", g["away"])] = g["home"]; paths[("opp", g["home"])] = g["away"]
        rec = (times, fracs, paths, g.get("final"))
        out[g["away"]] = rec; out[g["home"]] = rec
    return out

SCRIPT_START = float(os.environ.get("SL_SCRIPT_START", "0.5"))     # fraction of the game played when the effect starts
SCRIPT_SCALE = float(os.environ.get("SL_SCRIPT_SCALE", "1.5"))     # 1 = the sizes below at the final whistle. 1.5 fit best on Weeks 1-11 (calibration, Nov 24)
WP_SD_SCALE = float(os.environ.get("SL_WP_SD", "1.1"))            # in-week win chances: spread x1.1. Fixes underdogs coming back more often than the model said, with no loss in overall accuracy (Weeks 1-11)

def script_mult(pos, margin, f):
    """Game script, late and close. Second half only, ramping to full strength at the final whistle.
    Trailing by 1-16: passing game (QB/WR/TE) up to +20%, RB -10%, K +10%. Leading by 1-16: RB +10%, passing game -10%.
    Blowouts (17+) get half of that. Tied, first half, defenses: no change."""
    st, S = SCRIPT_START, SCRIPT_SCALE
    if S == 0 or f <= st or margin == 0 or pos not in ("QB", "WR", "TE", "RB", "K"): return 1.0
    late = min(1.0, (f - st) / (1 - st)) * (0.5 if abs(margin) > 16 else 1.0) * S
    if margin < 0: d = {"QB": .20, "WR": .20, "TE": .20, "RB": -.10, "K": .10}[pos]
    else: d = {"QB": -.10, "WR": -.10, "TE": -.10, "RB": .10, "K": 0.0}[pos]
    return 1.0 + d * late

def live_margins(pbp_dir):
    """{team: (own score - opponent score, fraction of game played)} for games in progress, from the latest play."""
    out = {}
    for fn in glob.glob(os.path.join(pbp_dir, "*.json")):
        try: g = json.load(open(fn))
        except Exception: continue
        if g.get("final") or not g.get("plays"): continue
        p = g["plays"][-1]; a, h = p[5], p[6]
        per, clk = p[1], p[2]
        f = min(1.0, ((min(per, 4) - 1) * 900 + (900 - clk)) / 3600) if per else 0.0
        out[g["away"]] = (a - h, f); out[g["home"]] = (h - a, f)
        for x, y in (("WSH", "WAS"), ("WAS", "WSH")):
            if x in out and y not in out: out[y] = out[x]
    return out

def wp_timeline(sides, paths, kick, cv, corr, pos_of):
    """sides: (A, B) lists of (pid, team, proj, actual or None). Returns [(iso time, pA, ptsA, ptsB)] at every play that moves either side,
    plus kickoffs and finals. Before kickoff a player is his projection; during his game, points so far plus the share of his projection left;
    after the final, his real points."""
    # collect (time, team, index) for teams in play
    tl = []
    seen_t = set()
    for X in sides:
        for pid, t, pj, act in X:
            if t in paths and t not in seen_t:
                seen_t.add(t)
                for k, tm in enumerate(paths[t][0]): tl.append((tm, t, k))
    tl.sort()
    st = {}                                       # team -> index of last play seen
    def side_state(X):
        mu = var = lk = 0.0
        for pid, t, pj, act in X:
            k = st.get(t)
            if t not in paths or k is None:
                mu += pj; var += (cv.get(pos_of(pid), 0.6) * pj) ** 2
                continue
            times, fracs, pp, fin = paths[t]
            cur = pp.get(pid, [0.0] * len(times))[k]
            f = fracs[k]
            if fin and k == len(times) - 1: f = 1.0
            left = max(0.0, 1.0 - f)
            if not pid.isdigit() and ("pa", pid) in pp:     # a defense: its points-allowed bonus is the expected one at the final, from the real score and time left
                global E0
                if E0 is None: E0 = exp_tier(0, 0.0)
                et = exp_tier(pp[("pa", pid)][k], f)
                mu += cur + et + (pj - E0) * left; var += (cv.get(pos_of(pid), 0.6) * pj) ** 2 * left; lk += cur + tier(pp[("pa", pid)][k])
            else:
                o = pp.get(("opp", t)); mg = (pp[("pa", o)][k] - pp[("pa", t)][k]) if o else 0
                m = script_mult(pos_of(pid), mg, f)
                mu += cur + pj * left * m; var += (cv.get(pos_of(pid), 0.6) * pj * m) ** 2 * left; lk += cur
        return mu, math.sqrt(var) * corr * (WP_SD_SCALE if st else 1.0), lk     # wider spread only once the week's games are under way
    out = []; prev = None
    for j, (tm, t, k) in enumerate(tl):
        st[t] = k
        if j + 1 < len(tl) and tl[j + 1][0] == tm: continue      # several plays at the same instant: one point, after all of them
        (ma, sa, la), (mb, sb, lb) = side_state(sides[0]), side_state(sides[1])
        p = (1.0 if ma > mb else 0.0 if mb > ma else 0.5) if sa + sb == 0 else float(norm.cdf((ma - mb) / math.hypot(sa, sb)))
        row = (tm, p, la, lb, ma, mb)              # time, A's win chance, points so far, projected finals
        if prev is None or abs(p - prev[1]) > 1e-4 or abs(la - prev[2]) > 1e-6 or abs(lb - prev[3]) > 1e-6: out.append(row); prev = row
    return out

def thin(rows, n=160):
    """Keep the shape (and both extremes) with at most about n points."""
    if len(rows) <= n: return rows
    lo = min(range(len(rows)), key=lambda k: rows[k][1]); hi = max(range(len(rows)), key=lambda k: rows[k][1])
    step = len(rows) / n
    keep = {int(k * step) for k in range(n)} | {0, len(rows) - 1, lo, hi}
    # keep big jumps too
    for k in range(1, len(rows)):
        if abs(rows[k][1] - rows[k - 1][1]) > 0.04: keep |= {k - 1, k}
    return [rows[k] for k in sorted(keep)]
