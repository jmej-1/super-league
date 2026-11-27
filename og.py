"""Link previews (iMessage, group chats, social apps).

The site is one page that draws itself with JavaScript, and link-preview bots don't run JavaScript. So every build also
writes, for each shareable address, a tiny HTML file with Open Graph tags (title, description, picture) plus the picture
itself. middleware.js hands those files to preview bots only; people always get the real site.

Files: <out>/og/<key>.html and <out>/og/<key>.jpg (1200x630)."""
import os, re, html, datetime
from PIL import Image, ImageDraw, ImageFont, ImageFilter

VER = __import__('time').strftime('%m%d%H%M')
SITE = "https://superleague.website"
W_, H_ = 1200, 630
NAVY, NAVY2, GOLD, CHALK, MUTE, TURF = (11, 26, 58), (18, 40, 84), (224, 180, 58), (238, 242, 248), (160, 176, 204), (31, 122, 74)
PAGES = {
    "standings": ("Standings", "Records, points and where every team stands."),
    "schedule": ("Schedule", "Every week's matchups, scores and win chances."),
    "playoffs": ("Playoff picture", "Playoff, bye and title odds for all 10 teams."),
    "records": ("Record book", "Single game, season and career records."),
    "teams": ("Teams", "All 10 teams and managers."),
    "players": ("Players", "Every player's points, WAR and starts."),
    "news": ("Super League Desk", "Recaps, previews and features."),
    "races": ("Awards", "MVP, Rookie of the Year and every award race."),
    "trades": ("Trades", "Every trade, graded."),
    "transactions": ("Transactions", "Every add, drop and waiver claim."),
    "draft": ("Draft", "The 2026 draft, graded."),
    "h2h": ("Head to head", "Every manager against every other."),
    "excitement": ("Most exciting games", "Every game ranked by excitement."),
    "analyzer": ("Trade analyzer", "Test a trade before you send it."),
}

def _font(fd, name, size):
    try: return ImageFont.truetype(os.path.join(fd, name), size)
    except OSError: return ImageFont.load_default()

class Cards:
    def __init__(s, S, out, data_dir):
        s.S, s.out, s.D = S, os.path.join(out, "og"), data_dir
        os.makedirs(s.out, exist_ok=True)
        fd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "og_fonts")
        s.disp = lambda n: _font(fd, "big-shoulders-display-latin-800-normal.ttf", n)
        s.bold = lambda n: _font(fd, "instrument-sans-latin-600-normal.ttf", n)
        s.reg = lambda n: _font(fd, "instrument-sans-latin-500-normal.ttf", n)
        s.hist = []
        lh = os.path.join(data_dir, "logo_history.txt")
        if os.path.exists(lh):
            for l in open(lh):
                if l.startswith("#") or not l.strip(): continue
                ts, r, fn = l.rstrip("\n").split("|")[:3]
                s.hist.append((datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%MZ").replace(tzinfo=datetime.timezone.utc), int(r), fn))
        s.hist.sort()
        s._lc = {}
        s.n = 0

    # ---------- pieces
    def logo(s, r, w=None, size=200):
        f = os.path.join(s.D, "logos", f"{s.S.s.M[r]}.png")
        if w is not None:
            at = s.S.wk_start(w)
            if at is not None:
                if at.tzinfo is None: at = at.replace(tzinfo=datetime.timezone.utc)
                for ts, rr, fn in reversed(s.hist):
                    if rr == r and at < ts and os.path.exists(os.path.join(s.D, "logos_old", fn)): f = os.path.join(s.D, "logos_old", fn)
        k = (f, size)
        if k in s._lc: return s._lc[k]
        try: im = Image.open(f).convert("RGBA").resize((size, size), Image.LANCZOS)
        except OSError: im = Image.new("RGBA", (size, size), NAVY2 + (255,))
        m = Image.new("L", (size * 4, size * 4), 0); ImageDraw.Draw(m).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
        im.putalpha(m.resize((size, size), Image.LANCZOS)); s._lc[k] = im
        return im

    def base(s, label):
        im = Image.new("RGB", (W_, H_), NAVY); d = ImageDraw.Draw(im)
        for y in range(H_):                                     # a quiet vertical fade
            t = y / H_; d.line([(0, y), (W_, y)], fill=tuple(int(NAVY[i] * (1 - t * .35) + NAVY2[i] * t * .35) for i in range(3)))
        d.rectangle((0, H_ - 14, W_, H_), fill=GOLD)
        sh = os.path.join(s.D, "brand", "shield.png")
        x = 56
        if os.path.exists(sh):
            g = Image.open(sh).convert("RGBA"); g.thumbnail((46, 46)); im.paste(g, (56, 44), g); x = 56 + g.width + 14
        d.text((x, 50), "Super League", font=s.bold(30), fill=CHALK)
        if label:
            tw = d.textlength(label, font=s.bold(26)); d.text((W_ - 56 - tw, 54), label, font=s.bold(26), fill=GOLD)
        return im, d

    def fit(s, d, text, fontf, size, maxw, minsize=40):
        while size > minsize and d.textlength(text, font=fontf(size)) > maxw: size -= 4
        f = fontf(size)
        if d.textlength(text, font=f) > maxw:
            while text and d.textlength(text + "...", font=f) > maxw: text = text[:-1]
            text = text.rstrip() + "..."
        return text, f

    def wrap(s, d, text, f, maxw, lines=3):
        words, out, cur = text.split(), [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if d.textlength(t, font=f) <= maxw: cur = t
            else:
                if cur: out.append(cur)
                cur = w
        if cur: out.append(cur)
        if len(out) > lines:
            out = out[:lines]; last = out[-1]
            while last and d.textlength(last + "...", font=f) > maxw: last = last[:-1]
            out[-1] = last.rstrip() + "..."
        return out

    def save(s, key, im, title, desc, path):
        im.save(os.path.join(s.out, f"{key}.jpg"), "JPEG", quality=86, optimize=True)
        s.page(key, title, desc, key, path)

    def page(s, key, title, desc, img, path):
        e = lambda v: html.escape(v, quote=True)
        t = f"{title} | Super League" if title != "Super League 2026" else title
        page = (
            f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>{e(t)}</title>'
            f'<meta name="description" content="{e(desc)}"><meta property="og:type" content="website"><meta property="og:site_name" content="Super League">'
            f'<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}"><meta property="og:url" content="{SITE}{e(path)}">'
            f'<meta property="og:image" content="{SITE}/og/{img}.jpg?v={VER}"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">'
            f'<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{e(title)}"><meta name="twitter:description" content="{e(desc)}">'
            f'<meta name="twitter:image" content="{SITE}/og/{img}.jpg?v={VER}"></head><body><a href="{e(path)}">{e(title)}</a></body></html>')
        for k_ in {key, re.sub(r"-([a-z])([a-z]*)$", lambda m: "-" + m.group(1).upper() + m.group(2), key), key.lower()}:   # /week12/Jesse and /week12/jesse alike
            open(os.path.join(s.out, f"{k_}.html"), "w").write(page)
        s.n += 1

    # ---------- cards
    def odds(s):
        try:
            oh = s.S.oh_ext(); return oh[-1][2] if oh else {}
        except Exception: return {}

    def home(s, O):
        S = s.S; im, d = s.base(f"Week {S.s.nxt}" if S.s.nxt else "")
        d.text((56, 130), "Super League 2026", font=s.disp(118), fill=CHALK)
        st = S.stand; sz = 96; gap = (W_ - 112 - sz * 10) / 9
        for k, r in enumerate(st):
            x = int(56 + k * (sz + gap)); lg = s.logo(r, None, sz); im.paste(lg, (x, 330), lg)
            d.text((x + sz / 2, 440), S.rec_str(r), font=s.bold(24), fill=CHALK, anchor="ma")
            d.text((x + sz / 2, 474), f"#{k + 1}", font=s.reg(22), fill=MUTE, anchor="ma")
        lead = st[0]
        s.save("home", im, "Super League 2026", f"{S.TN(lead)} leads at {S.rec_str(lead)}. Standings, odds, records and the weekly Desk.", "/")

    def pagecards(s):
        for k, (t, desc) in PAGES.items():
            im, d = s.base("")
            d.text((56, 190), t, font=s.disp(150), fill=CHALK)
            for j, ln in enumerate(s.wrap(d, desc, s.reg(40), W_ - 112, 2)): d.text((56, 400 + j * 54), ln, font=s.reg(40), fill=MUTE)
            s.save(f"page-{k}", im, t, desc, f"/{k}")

    def team(s, r, O):
        S = s.S; im, d = s.base(f"{S.yr} season")
        lg = s.logo(r, None, 300); im.paste(lg, (56, 150), lg)
        name, f = s.fit(d, S.TN(r), s.disp, 104, W_ - 440)
        d.text((400, 160), name, font=f, fill=CHALK)
        d.text((404, 290), S.s.M[r], font=s.bold(40), fill=GOLD)
        place = S.stand.index(r) + 1
        d.text((404, 360), f"{S.rec_str(r)}, #{place} in the standings", font=s.reg(36), fill=CHALK)
        o = O.get(r) or O.get(str(r))
        if o: d.text((404, 410), f"Playoffs {o[0] * 100:.0f}%   Bye {o[1] * 100:.0f}%   Title {o[2] * 100:.0f}%", font=s.reg(32), fill=MUTE)
        desc = f"{S.s.M[r]}'s team: {S.rec_str(r)}, #{place} in the standings." + (f" {o[0] * 100:.0f}% to make the playoffs." if o else "")
        img = f"team-{S.s.M[r].lower()}"
        im.save(os.path.join(s.out, f"{img}.jpg"), "JPEG", quality=86, optimize=True)
        for path in (f"/{S.s.M[r]}",):
            s.page(img, f"{S.TN(r)} ({S.s.M[r]})", desc, img, path)

    def gstate(s, w, a, b):
        """(points a, points b, win chance a, label)"""
        S = s.S; s_ = S.s
        if w in s_.G:
            sa, sb = s_.G[w]["scores"][a], s_.G[w]["scores"][b]
            return sa, sb, 1.0 if sa > sb else 0.0 if sb > sa else 0.5, "Final"
        A, B = S.upcoming(w, a), S.upcoming(w, b); p = S.win_p(A, B)
        if S.wk_live(w):
            na, nb = S.now_pts(w, a), S.now_pts(w, b)
            if (na or 0) + (nb or 0) > 0: return na, nb, p, "In progress"
        return A[0], B[0], p, "Projected"

    def game(s, w, a, b):
        S = s.S; im, d = s.base(f"Week {w}")
        pa, pb, p, lab = s.gstate(w, a, b)
        for side, r, x, pts, q in ((0, a, 90, pa, p), (1, b, W_ - 90 - 230, pb, 1 - p)):
            lg = s.logo(r, w, 230); im.paste(lg, (x, 140), lg)
            cx = x + 115
            nm, f = s.fit(d, S.TN(r, w), s.bold, 34, 420, 22)
            d.text((cx, 388), nm, font=f, fill=CHALK, anchor="ma")
            d.text((cx, 430), S.s.M[r], font=s.reg(28), fill=MUTE, anchor="ma")
            won = lab == "Final" and q == 1.0
            sc = f"{pts:.2f}".rstrip("0").rstrip(".") if lab == "Final" else f"{pts:.1f}"
            d.text((cx, 478), sc, font=s.disp(84), fill=GOLD if (won or (lab != "Final" and q > .5)) else CHALK, anchor="ma")
        d.text((W_ / 2, 180), lab, font=s.bold(30), fill=GOLD, anchor="mm")
        if lab != "Final":
            d.text((W_ / 2, 275), f"{max(p, 1 - p) * 100:.0f}%", font=s.disp(110), fill=CHALK, anchor="mm")
            d.text((W_ / 2, 350), f"{S.s.M[a] if p >= .5 else S.s.M[b]} to win", font=s.reg(28), fill=MUTE, anchor="mm")
        else:
            d.text((W_ / 2, 300), "vs", font=s.disp(90), fill=MUTE, anchor="mm")
        img = f"g-{w}-{min(a, b)}-{max(a, b)}"
        im.save(os.path.join(s.out, f"{img}.jpg"), "JPEG", quality=86, optimize=True)
        if lab == "Final":
            wi, lo = (a, b) if pa >= pb else (b, a); hi_, lw_ = max(pa, pb), min(pa, pb)
            desc = f"{S.s.M[wi]} beat {S.s.M[lo]} {hi_:.2f} to {lw_:.2f}."
        elif lab == "In progress":
            desc = f"{S.s.M[a]} {pa:.1f}, {S.s.M[b]} {pb:.1f}. {S.s.M[a] if p >= .5 else S.s.M[b]} is {max(p, 1 - p) * 100:.0f}% to win."
        else:
            desc = f"Projected {pa:.1f} to {pb:.1f}. {S.s.M[a] if p >= .5 else S.s.M[b]} is {max(p, 1 - p) * 100:.0f}% to win."
        title = f"{S.s.M[a]} vs {S.s.M[b]}, Week {w}"
        x, y = sorted((a, b))
        s.page(img, title, desc, img, f"/game/w{w}-{x}-{y}")
        for r in (a, b):
            s.page(f"game-{w}-{S.s.M[r].lower()}", title, desc, img, f"/week{w}/{S.s.M[r].lower()}")
        return pa, pb, p, lab

    def week(s, w, pairs):
        S = s.S; im, d = s.base("")
        d.text((56, 110), f"Week {w}", font=s.disp(110), fill=CHALK)
        y = 250; sz = 56
        st = None
        for a, b in pairs:
            pa, pb, p, lab = s.gstate(w, a, b); st = lab
            la, lb = s.logo(a, w, sz), s.logo(b, w, sz)
            im.paste(la, (56, y), la); d.text((130, y + 12), S.s.M[a], font=s.bold(32), fill=CHALK)
            sa = f"{pa:.1f}"; d.text((560, y + 8), sa, font=s.disp(44), fill=GOLD if (pa > pb if lab == "Final" else p > .5) else CHALK, anchor="ra")
            im.paste(lb, (W_ - 56 - sz, y), lb); d.text((W_ - 130, y + 12), S.s.M[b], font=s.bold(32), fill=CHALK, anchor="ra")
            sb = f"{pb:.1f}"; d.text((640, y + 8), sb, font=s.disp(44), fill=GOLD if (pb > pa if lab == "Final" else p < .5) else CHALK)
            d.text((W_ / 2, y + 30), "-", font=s.bold(30), fill=MUTE, anchor="mm")
            y += 70
        if st: d.text((W_ - 56, 140), st if st != "Projected" else "Projected", font=s.bold(30), fill=GOLD, anchor="ra")
        desc = "Final scores for every matchup." if st == "Final" else "Every matchup, scores and win chances."
        s.save(f"week-{w}", im, f"Week {w}", desc, f"/week{w}")

    def story(s, n):
        S = s.S; im, d = s.base(f"Week {n['week']}" if n.get("week") else "Super League Desk")
        d.text((56, 118), "Super League Desk", font=s.bold(28), fill=GOLD)
        ts = [int(t) for t in str(n.get("teams", "")).replace(" ", "").split(",") if t.isdigit()][:4]
        tw = W_ - 112
        f = s.disp(82)
        lines = s.wrap(d, n["title"], f, tw, 3)
        if len(lines) == 3 and ts: f = s.disp(70); lines = s.wrap(d, n["title"], f, tw, 3)
        y = 168
        for ln in lines: d.text((56, y), ln, font=f, fill=CHALK); y += int(f.size * 1.02)
        if ts:
            x = 56; wk = n.get("week")
            for r in ts:
                if r in S.s.M:
                    lg = s.logo(r, int(wk) if str(wk).isdigit() else None, 84); im.paste(lg, (x, H_ - 14 - 40 - 84), lg); x += 100
        key = f"news-{n['slug']}"
        desc = re.sub(r"\{[tpm]:[^}]*\}", "", n.get("dek", "")).strip() or "From the Super League Desk."
        s.save(key, im, n["title"], desc, f"/news/{n['slug']}")

    def players(s):
        S = s.S; s_ = S.s
        try: PD = S.players_data()
        except Exception: return
        own = {}
        for i, dd in PD.items():
            if dd.get("o"): own[i] = int(dd["o"])
        for i, dd in PD.items():
            sea = (dd.get("sea") or {}).get(str(S.yr)) or {}
            sm = sea.get("s") or []
            bits = [dd.get("p") or "", (dd.get("t") or "FA")]
            if i in own: bits.append(S.TN(own[i]))
            desc = ", ".join(b for b in bits if b) + "."
            img = f"team-{s_.M[own[i]].lower()}" if i in own else "home"
            s.page(f"player-{i}", dd.get("n", "Player"), desc, img, f"/player/{i}")

    def run(s):
        S = s.S; s_ = S.s; O = s.odds()
        s.home(O); s.pagecards()
        for r in s_.R: s.team(r, O)
        weeks = {}
        for w, a, b, done in S.games: weeks.setdefault(w, []).append((a, b))
        for w, pairs in sorted(weeks.items()):
            for a, b in pairs: s.game(w, a, b)
            s.week(w, pairs)
        for n in S.news_list():
            try: s.story(n)
            except Exception as ex: print("og story", n.get("slug"), ex)
        s.players()
        return s.n

def make(S, out, data_dir):
    try:
        n = Cards(S, out, data_dir).run(); print(f"og: {n} preview pages")
    except Exception as ex:                       # previews must never break the site build
        import traceback; traceback.print_exc(); print("og: skipped", ex)
