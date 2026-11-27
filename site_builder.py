"""Builds the Super League website from the pipeline's results.

Output (all relative links, so it works on Netlify, a Claude artifact, or a local folder):
  index.html                       league page
  team/{Manager}.html              one page per team
  game/w{week}-{rid}-{rid}.html    one page per matchup (box score if played, preview if not)
  logos/{Manager}.png              copied by superleague.py
"""
import html, datetime, os, math, re, sys
from collections import defaultdict, Counter
import numpy as np
from scipy.stats import norm

E = html.escape


def ncdf(z):
    """Win chance from a z-score. A game that isn't over is never 0% or 100%: a normal tail rounds to exactly 1.0 past z of about 8."""
    return min(max(float(norm.cdf(z)), 1e-6), 1 - 1e-6)


def pct(p, dp=1):
    """Percent with at most one decimal, no trailing .0 (66.7%, 50%, 100%)."""
    if 0.9995 <= p < 1: return "&gt;99.9%"
    if 0 < p < 0.0005: return "&lt;0.1%"
    return f"{round(p * 100, 1):.1f}".rstrip("0").rstrip(".") + "%"


def fp(v):
    """Fantasy points: two decimals when the hundredths matter, otherwise one (never a trailing zero past the tenths)."""
    r = round(float(v), 2)
    return f"{r:.2f}" if round(r * 100) % 10 else f"{r:.1f}"


def fc(v):
    """Chart labels: up to two decimals, no trailing zeros (25, 25.7, 23.24)."""
    return f"{round(float(v), 2):.2f}".rstrip("0").rstrip(".")


def bar(p, cls=""):
    w = max(0, min(100, p * 100))
    return f'<span class="bar {cls}"><span style="width:{w:.1f}%"></span></span><span class="num">{pct(p)}</span>'


def FONTS(pre):
    ff = [("Big Shoulders Display", "big-shoulders-display", w) for w in (600, 800, 900)] + [("Instrument Sans", "instrument-sans", w) for w in (400, 500, 600, 700)]
    return "<style>" + "".join(f"@font-face{{font-family:'{n}';font-style:normal;font-weight:{w};font-display:swap;src:url({pre}fonts/{f}-latin-{w}-normal.woff2) format('woff2')}}" for n, f, w in ff) + "</style>"

CSS = """
:root{
  /* The field: turf green is the stage for this week's games; everything else sits on chalk.
     Penalty-flag yellow marks only what matters (the playoff line, the leader). */
  --turf:#0B1A36; --turf2:#1C3360; --yard:rgba(226,232,244,.18);
  --chalk:#EEF0F4; --paper:#F8F9FB; --ink:#121826; --mute:#5D6576; --rule:#D5DAE3;
  --flag:#E2AE2A; --loss:#B6412E; --win:#1F7A52;
  --disp:'Big Shoulders Display',Impact,'Arial Narrow',sans-serif; --body:'Instrument Sans',system-ui,sans-serif;
  color-scheme:light;
}
*{box-sizing:border-box} [hidden]{display:none!important}
.cx{position:absolute;top:4px;right:6px;border:0;background:none;color:inherit;font:700 18px/1 var(--body);cursor:pointer;padding:4px 6px;opacity:.75} .cx:hover{opacity:1}
html{scroll-behavior:smooth} @media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
body{margin:0;background:var(--chalk);color:var(--ink);font:16px/1.55 var(--body);font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
a{color:inherit} a:focus-visible{outline:3px solid var(--flag);outline-offset:2px;border-radius:3px}
.wrap{max-width:1080px;margin:0 auto;padding:0 20px}
/* chrome */
.top{background:var(--turf);color:var(--chalk);border-bottom:1px solid var(--yard)}
.top .wrap{display:flex;align-items:center;gap:28px;min-height:60px}
.mark{display:flex;align-items:center;gap:10px;font:900 28px/1 var(--disp);color:var(--flag);text-decoration:none;white-space:nowrap}
.brandlogo{display:inline-block;width:38px;height:38px;background-size:contain;background-repeat:no-repeat;background-position:center;flex:none}
.menu{display:flex;gap:22px;overflow-x:auto;scrollbar-width:none;flex:1}
.menu a{color:#B8C2D6;text-decoration:none;font-weight:500;font-size:15px;white-space:nowrap;padding:18px 0 16px;border-bottom:3px solid transparent}
.menu a:hover{color:#fff} .menu a[aria-current=page]{color:#fff;border-color:var(--flag)}
/* the field (home hero + page heads) */
.field{background:var(--turf);color:var(--chalk);padding:34px 0 40px;
  background-image:repeating-linear-gradient(180deg,transparent 0 119px,rgba(255,255,255,.035) 119px 120px)}
.field h1{font:900 clamp(64px,14vw,148px)/.85 var(--disp);margin:0;letter-spacing:-.01em}
.field .lede{color:#B8C2D6;margin:12px 0 0;max-width:52ch}
.field .back{color:#B8C2D6;text-decoration:none;font-size:14px} .field .back:hover{color:#fff;text-decoration:underline}
.pagehead h1{font-size:clamp(52px,10vw,96px)}
/* face-offs on the field */
.faceoffs{margin-top:28px;border-top:2px solid var(--yard)}
a.fo{display:grid;grid-template-columns:1fr minmax(170px,220px) 1fr;align-items:center;gap:24px;padding:18px 0;border-bottom:2px solid var(--yard);text-decoration:none;color:var(--chalk)}
a.fo:hover .fn{text-decoration:underline;text-decoration-thickness:2px;text-underline-offset:4px}
.ft{display:flex;align-items:center;gap:14px;min-width:0}
.ft.b{flex-direction:row-reverse;text-align:right}
.ft .im{width:52px;height:52px;border-radius:50%;object-fit:cover;flex:none;box-shadow:0 0 0 2px rgba(238,241,234,.35)}
.ft .who{min-width:0;flex:1}
.fn{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;font:800 clamp(20px,2.4vw,26px)/1.02 var(--disp)}
.fm{display:block;color:#B8C2D6;font-size:13px;margin-top:3px}
.fp{font:900 clamp(34px,4.4vw,46px)/1 var(--disp)}
.fp.l{opacity:.5}
.tug{display:flex;flex-direction:column;gap:8px;--ca:var(--flag);--cb:var(--chalk)}
.tug .rope{position:relative;height:16px;display:flex;gap:3px;border-radius:8px}
.tug .rope i{display:block;height:100%}
.tug .rope .ra{width:var(--p);flex:none;background:linear-gradient(90deg,color-mix(in srgb,var(--ca) 70%,#000),var(--ca));border-radius:8px 3px 3px 8px;box-shadow:0 0 14px color-mix(in srgb,var(--ca) 55%,transparent);animation:pull 1.1s cubic-bezier(.2,.8,.2,1) both}
.tug .rope .rb{flex:1;background:linear-gradient(90deg,var(--cb),color-mix(in srgb,var(--cb) 70%,#000));border-radius:3px 8px 8px 3px;box-shadow:0 0 14px color-mix(in srgb,var(--cb) 55%,transparent)}
.tug .mid50{position:absolute;left:50%;top:-5px;bottom:-5px;width:2px;margin-left:-1px;background:var(--chalk);opacity:.55;border-radius:1px}
@keyframes pull{from{width:50%}}
@media (prefers-reduced-motion:reduce){.tug .rope .ra{animation:none}}
.tug .pc{display:flex;justify-content:space-between;align-items:baseline;font:800 15px/1 var(--disp);color:#B8C2D6}
.tug .pc b{font:900 26px/1 var(--disp);display:inline-flex;align-items:center;gap:7px}
.tug .rl{width:22px;height:22px;flex:none} .tug .pc>span{white-space:nowrap;font-size:13px} .tug .pc{gap:8px;min-width:0} @media (max-width:760px){.tug .rl{width:18px;height:18px} .tug .pc b{font-size:22px;gap:5px}} .tug .rl.ra_{box-shadow:0 0 0 2px var(--ca)} .tug .rl.rb_{box-shadow:0 0 0 2px var(--cb)} .tug .pc .pa{color:var(--ca)} .tug .pc .pb{color:var(--cb)}
.fo .final{font:600 13px var(--body);color:#B8C2D6;text-align:center}
/* page body */
main{padding:8px 0 40px}
section{padding:40px 0 0;scroll-margin-top:20px}
h2{font:800 clamp(30px,4vw,40px)/1 var(--disp);margin:0 0 6px}
.intro{color:var(--mute);margin:0 0 18px;max-width:64ch}
h3{font:700 17px/1.3 var(--body);margin:0 0 10px}
h2 small{font:500 15px/1.3 var(--body);color:var(--mute);margin-left:10px;letter-spacing:0}
.more{display:inline-block;margin-top:14px;font-weight:600;color:var(--turf);text-decoration:underline;text-underline-offset:3px}
.cols{display:grid;grid-template-columns:1.25fr 1fr;gap:48px;align-items:start}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:40px;align-items:start}
.note{color:var(--mute);font-size:14px;max-width:70ch;margin:12px 0 0}
.muted{color:var(--mute)} .pos{color:var(--win)} .neg{color:var(--loss)}
/* tables: paper sheet with rules, no boxes */
.scroll{overflow-x:auto;background:var(--paper);border-top:2px solid var(--ink)}
.scroll table{min-width:600px} .wide table{min-width:860px}
table{width:100%;border-collapse:collapse}
th{font:600 13px var(--body);color:var(--mute);text-align:left;padding:10px 12px;border-bottom:1px solid var(--rule);white-space:nowrap}
td{padding:11px 12px;border-bottom:1px solid var(--rule);vertical-align:middle}
td small{display:block;color:var(--mute);font-size:13px}
.r{text-align:right;white-space:nowrap} .c{text-align:center;white-space:nowrap}
.rk{color:var(--mute);width:28px;font:700 17px var(--disp)}
.big{font:800 20px var(--disp)}
table.pt{background:var(--paper);border-top:2px solid var(--ink)}
tr.tstart td{border-top:2px solid var(--rule)}

.stand tr.zb td.rk{box-shadow:inset 4px 0 0 var(--flag)} .stand tr.zp td.rk{box-shadow:inset 4px 0 0 var(--turf)}
.stand td.rk{padding-left:14px}
.zkey{display:flex;gap:16px;margin:0 0 10px;font-size:13px;color:var(--mute)} .zk::before{content:"";display:inline-block;width:14px;height:4px;border-radius:2px;margin-right:6px;vertical-align:middle}
.zk.zb::before{background:var(--flag)} .zk.zs::before{background:var(--turf)} .zk.zn::before{background:#9AA3B5} .zk.zf::before{background:#D3DACF} .zk.zp::before{background:var(--turf)}
.stand tr.out td{color:var(--mute)}
.b{min-width:130px;white-space:nowrap}
.bar{display:inline-block;width:70px;height:8px;border-radius:4px;background:var(--rule);vertical-align:middle;margin-right:8px;overflow:hidden}
.bar span{display:block;height:100%;background:var(--turf)} .bar.b2 span{background:var(--turf2)} .bar.b3 span{background:var(--flag)}
.num{font-weight:600}
.h2hg{table-layout:fixed;min-width:860px} .h2hg col.h2n{width:120px} .h2hg col.h2t{width:72px} .h2hg th,.h2hg td{overflow:hidden;text-overflow:ellipsis} .h2hg{border-collapse:collapse} .h2hg tbody td{border:1px solid var(--ink)} .h2hg thead th:not(:first-child){border-bottom:1px solid var(--ink)} .dboard td.dc{border:1px solid var(--ink)} .dboard thead th:not(:first-child){border-bottom:1px solid var(--ink)}
.kt{white-space:nowrap} .ksep{display:inline-block;width:4px;height:4px;border-radius:50%;background:currentColor;opacity:.55;margin:0 7px;vertical-align:middle} .lu .pl .who small .stg{margin-left:8px} .nflr{margin:0 0 0 5px}
@media (max-width:760px){.lu .kt{display:block;margin:2px 0 0;white-space:normal} .lu .ksep{display:none} .lu .pl .who small .stg{margin-left:0}}
.wpc{position:relative} .wpc .gfv svg{touch-action:pan-y;cursor:crosshair;user-select:none;-webkit-user-select:none} .wphint{margin:2px 0 0;font-size:12px} .wpd{cursor:pointer;outline:none} .wpdv{pointer-events:none} .wpd:hover+.wpdv,.wpd.on+.wpdv{r:7} .wpcard{display:block;background:var(--field,#0b1a3a);color:#EEF2F8;border-radius:12px;padding:10px 14px 8px;margin:10px 0 6px;font-size:14px;display:grid;grid-template-columns:minmax(300px,1fr) minmax(0,1.25fr);gap:0 22px;align-items:stretch}
.wpcard .sbL{display:block;min-width:0}.wpcard .sbpl{display:block;border-left:1px solid rgba(238,242,248,.14);padding-left:20px;height:96px;overflow:hidden;min-width:0}.wpcard .sbpl.none{display:flex;align-items:center;justify-content:center}.wpcard .sbpl.none .sbt{color:#8FA0BC;font-style:italic;padding:0 4px;overflow:visible}
.wpcard .sbg{display:flex;align-items:center;gap:5px;font-size:12px;color:#C7D2E4;white-space:nowrap}.wpcard .sbg .nfl{width:16px;height:16px;margin:0}.wpcard .sbg b{font-weight:700;color:#EEF2F8;margin-right:2px}.wpcard .sbgx{opacity:.6;margin:0 2px}.wpcard .sbq{margin-left:auto;font-weight:700;color:#C9A21A}
.wpcard .sbt{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;font-size:12.5px;line-height:1.35;color:#DCE3F0;margin:4px 0 5px}
.wpcard .sbws{display:flex;gap:6px;overflow:hidden;white-space:nowrap}.wpcard .sbw{display:inline-flex;align-items:center;gap:4px;background:rgba(238,242,248,.08);border-radius:999px;padding:2px 8px 2px 2px;font-size:12px;flex:none}.wpcard .sbw.s0{box-shadow:inset 2px 0 0 #DCE3F0}.wpcard .sbw.s1{box-shadow:inset 2px 0 0 #C9A21A}
.wpcard .sbw .im{width:18px;height:18px}.wpcard .sbw .nfl{width:15px;height:15px;margin:0}.wpcard .sbwn{font-weight:600}.wpcard .sbw b.up{color:#8FD6A4}.wpcard .sbw b.dn{color:#F08F8F}
.wpcard .sbh{display:block;font-size:12px;font-weight:600;color:#AFC0DA;margin-bottom:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.wpcard .sbd{font-size:11.5px;font-weight:700;font-variant-numeric:tabular-nums;text-align:left;color:transparent}.wpcard .sbd.z{color:#8FA0BC}.wpcard .sbw b.z{color:#8FA0BC}.pbtab .pbw b.z{color:var(--mute)}.wpcard .sbd.up{color:#8FD6A4}.wpcard .sbd.dn{color:#F08F8F}
.wpcard .sbtt{margin-right:14px;white-space:nowrap}.wpcard .sbtt b{color:#EEF2F8}.wpcard .sbtt.s0{box-shadow:inset 2px 0 0 #DCE3F0;padding-left:6px}.wpcard .sbtt.s1{box-shadow:inset 2px 0 0 #C9A21A;padding-left:6px}
.wpcard .sbx{display:flex;flex-wrap:wrap;gap:2px 14px;margin-top:5px;font-size:11.5px;color:#8FA0BC}.wpcard .sbx b{font-weight:700;color:#DCE3F0}.wpcard .sbx b.up{color:#8FD6A4}
.wpcard .sbv{display:flex;align-items:baseline;justify-content:flex-end;gap:6px}.wpcard .sbv .sbd{min-width:38px}
.wpcard .sbr{display:grid;grid-template-columns:4px 24px 1fr auto 96px;align-items:center;gap:8px;padding:3px 0}.wpcard .sbc{width:4px;height:22px;border-radius:2px}
.wpcard .sbr .im{width:24px;height:24px}.wpcard .sbn{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;opacity:.85}.wpcard .sbr.lead .sbn{opacity:1}
.wpcard .sbs{font:800 20px/1 var(--disp,inherit);font-variant-numeric:tabular-nums;text-align:right}.wpcard .sbp{text-align:right;font-weight:700;font-variant-numeric:tabular-nums;color:#AFC0DA}.wpcard .sbr.lead .sbp{color:var(--flag,#e0b43a)}
@media (max-width:760px){.wpcard{display:block}.wpcard .sbpl{border-left:0;padding-left:0;border-top:1px solid rgba(238,242,248,.14);margin-top:7px;padding-top:7px;height:98px}.wpcard .sbr{gap:8px;grid-template-columns:4px 24px 1fr auto 56px}.wpcard .sbv{flex-direction:column;align-items:flex-end;gap:1px}.wpcard .sbv .sbd{min-width:0;text-align:right;line-height:1}.wpcard .sbd:empty{display:none}}
.wcr{display:grid;grid-template-columns:1fr auto 64px;gap:10px;align-items:baseline} .wcr i{font-style:normal;color:#C9D1E1} .wcr em{font-style:normal;font:800 17px var(--disp)} .wcr strong{text-align:right;color:var(--flag)}
.wprow{display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:8px;font-size:13px;color:var(--mute)} .wprow span{display:flex;gap:6px;align-items:baseline} .wprow b{color:var(--ink);font-weight:700} .wprow small{font-size:12px}
.nfl{display:inline-block;width:18px;height:18px;background:center/contain no-repeat;vertical-align:-4px;margin-right:5px;flex:none}
a.nfll{white-space:nowrap} .nflh{width:96px;height:96px;margin:0;vertical-align:middle;filter:drop-shadow(0 0 1px rgba(255,255,255,.6))} .nflm{width:22px;height:22px;vertical-align:-5px}
.byec{display:inline-block;vertical-align:middle;font:700 11px/1 var(--body);color:var(--turf);background:#E3E9F5;padding:4px 7px;border-radius:3px;letter-spacing:.03em}td .byec{position:relative;top:-1px}
@media(max-width:560px){.todds{min-width:0!important;width:100%}.todds .bar{display:none}.todds td.tcol,.todds td.b{min-width:0!important;width:auto!important;font-size:13px}.todds td.tcol{font-size:15px}.todds th:nth-child(3),.todds td:nth-child(3){display:none}.todds td,.todds th{padding:8px 3px;font-size:12.5px}.todds td .tl small,.todds td small{display:none}.todds td:nth-child(2) img{width:24px;height:24px}.todds td:nth-child(2){max-width:118px}.todds td:nth-child(2) *{white-space:normal}.todds td.rk{padding-left:6px}}
.todds td.tcol{font-weight:700;font-size:1.05em;min-width:170px} .todds td.tcol .bar{width:110px;height:10px} .todds th:nth-child(4){color:var(--ink)}
/* team labels */
.tl{display:flex;align-items:center;gap:12px;text-decoration:none;min-width:0}
.tl b{white-space:nowrap;font-weight:600} .tl small{display:block;color:var(--mute);font-size:13px}
a.tl:hover b,a.tn:hover{text-decoration:underline;text-underline-offset:3px}
a.tn{text-decoration:none;font-weight:600}
.lg{width:36px;height:36px;border-radius:50%;flex:none;object-fit:cover;background-color:var(--rule)}
.lgs{width:24px;height:24px;border-radius:50%;flex:none;object-fit:cover;background-color:var(--rule)}
.lgb{width:56px;height:56px;border-radius:50%;object-fit:cover;flex:none;background:var(--rule)}
.lgh{width:96px;height:96px;border-radius:50%;object-fit:cover;flex:none;background:var(--rule);box-shadow:0 0 0 3px rgba(238,241,234,.35)}
.im{display:inline-block;border-radius:50%;background-color:var(--rule);background-position:center;background-size:cover;background-repeat:no-repeat;flex:none}
.ph{display:inline-grid;place-items:center;font:800 16px var(--disp);color:var(--mute)}
a.go{font-weight:600;color:var(--turf);white-space:nowrap;text-underline-offset:3px}
/* playoff race (home) */
.race{background:var(--paper);border-top:2px solid var(--ink)}
.race .cs{font:500 10px var(--body);color:#A6ADBB;width:12px;text-align:right;flex:none;align-self:center}
.race a{display:grid;grid-template-columns:28px minmax(0,1fr) 52px 1fr 48px;align-items:center;gap:12px;padding:10px 12px;border-bottom:1px solid var(--rule);text-decoration:none}
.race a:hover{background:#fff}
.race .who{display:flex;align-items:center;gap:10px;min-width:0} .race .who b{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-weight:600}
.race .wl{font:700 18px var(--disp);text-align:right}
.race .po{height:10px;border-radius:5px;background:var(--rule);overflow:hidden} .race .po i{display:block;height:100%;background:var(--turf)}
.race .pv{font:800 18px var(--disp);text-align:right}
.race .line{padding:4px 12px;font-size:13px;font-weight:600;color:var(--ink);background:var(--flag)}
.race a.out{color:var(--mute)} .race a.out .po i{background:#98A1B3}
/* last week */
.results{display:grid;gap:0;background:var(--paper);border-top:2px solid var(--ink)}
a.res{display:grid;grid-template-columns:1fr auto 1fr;gap:10px;align-items:center;padding:10px 12px;border-bottom:1px solid var(--rule);text-decoration:none}
a.res:hover{background:#fff}
a.res .t{display:flex;align-items:center;gap:8px;min-width:0} a.res .t.b{flex-direction:row-reverse;text-align:right}
a.res .t span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
a.res .s{font:800 20px var(--disp);white-space:nowrap} a.res .s .l{color:var(--mute);font-weight:600}
a.res .w{font-weight:600}
.res1{grid-template-columns:1fr 1fr;margin-top:18px}
.potw{margin-top:4px;padding:14px 18px;background:var(--turf);color:var(--chalk);display:grid;grid-template-columns:1fr auto;grid-template-areas:"lab pts" "who pts";gap:2px 16px;align-items:center;text-decoration:none}
.potw .lab{grid-area:lab;font-weight:600;font-size:14px;color:var(--flag)}
.potw .who{grid-area:who} .potw .who b{font:800 28px/1.05 var(--disp);display:block} .potw .who span{color:#B8C2D6;font-size:14px}
.potw .pts{grid-area:pts;font:900 56px/1 var(--disp);color:var(--flag);text-align:right} .potw .pts small{display:block;font:600 14px var(--body);color:#B8C2D6}
.potw:hover .who b{text-decoration:underline}
.potw .who b span.nw{color:inherit;font:inherit;white-space:nowrap} .potw .pnfl{width:30px;height:30px;margin-left:10px;vertical-align:-4px} .potw .ptm{display:inline-flex;align-items:center;gap:7px;margin-top:4px} .potw .ptm .im{width:22px;height:22px}
.mvpl{background:var(--paper);border-top:2px solid var(--ink)}
.mvpl div{display:grid;grid-template-columns:28px 1fr auto;gap:12px;align-items:center;padding:10px 12px;border-bottom:1px solid var(--rule)}
.mvpl .v{font:800 22px var(--disp)}
/* teams strip */
.teams{display:grid;grid-template-columns:repeat(5,1fr);gap:22px 12px}
.teams a{display:flex;flex-direction:column;align-items:center;text-align:center;gap:8px;text-decoration:none}
.teams .im{width:72px;height:72px;border-radius:50%;object-fit:cover;background-color:var(--rule)}
.teams b{font:800 18px/1.1 var(--disp)} .teams small{color:var(--mute);font-size:13px}
.teams a:hover b{text-decoration:underline}
/* schedule */
.chips,.subnav .wrap{display:flex;gap:6px;overflow-x:auto;scrollbar-width:none}
.subnav{background:var(--paper);border-bottom:1px solid var(--rule);position:sticky;top:0;z-index:4}
.subnav .wrap{padding:10px 20px} .subnav.ychips{position:static}
.chips a,.subnav a{font-weight:600;font-size:14px;text-decoration:none;padding:6px 12px;border-radius:999px;color:var(--mute);white-space:nowrap;border:1px solid var(--rule);background:var(--paper)}
.chips a:hover,.subnav a:hover{color:var(--ink);border-color:var(--ink)}
.chips a.nx,.subnav a[aria-current=page]{background:var(--turf);border-color:var(--turf);color:var(--chalk)}
.chips{margin-bottom:22px;flex-wrap:wrap}
.tchips{padding-top:16px}
.wk{margin-bottom:30px;scroll-margin-top:16px}
.wk h3{font:800 26px/1 var(--disp);margin:0 0 10px} .wk h3 span{font:500 14px var(--body);color:var(--mute);margin-left:8px}
.mini{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:0 18px;border-top:2px solid var(--ink)}
a.gm{display:block;padding:10px 2px;border-bottom:1px solid var(--rule);text-decoration:none}
a.gm:hover{background:var(--paper)}
.gm .row{display:flex;align-items:center;gap:8px;padding:2px 0}
.gm .row .t{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.gm .row .s{font:800 19px var(--disp)} .gm .row.l{color:var(--mute)} .gm .row.w .t{font-weight:600}
.gm .foot{font-size:12px;color:var(--mute);margin-top:2px}
.gm.fut .row .s{font-weight:600;color:var(--mute)}
.wkbar{display:flex;align-items:center;gap:10px;margin-bottom:22px}
.wstep{width:44px;height:44px;border-radius:50%;border:1px solid var(--rule);background:var(--paper);font:800 26px/1 var(--disp);color:var(--ink);cursor:pointer}
.wstep:hover{border-color:var(--ink)} .wstep:disabled{opacity:.35;cursor:default}
.wsel{appearance:none;-webkit-appearance:none;font:800 26px/1 var(--disp);color:var(--ink);background:var(--paper) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='9'%3E%3Cpath d='M1 1l6 6 6-6' stroke='%23141A17' stroke-width='2' fill='none'/%3E%3C/svg%3E") no-repeat right 14px center;border:1px solid var(--rule);border-radius:999px;padding:9px 44px 9px 18px;cursor:pointer}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
.wkh{font:800 30px/1 var(--disp);margin:0 0 14px} .wkh span{font:500 15px var(--body);color:var(--mute);margin-left:8px}
.gcards{display:grid;grid-template-columns:1fr 1fr;gap:14px}
a.gcard{display:block;background:var(--paper);border-top:3px solid var(--ink);padding:6px 16px 14px;text-decoration:none}
a.gcard:hover{background:#fff} a.gcard:hover .t b{text-decoration:underline}
.gr{display:flex;align-items:center;gap:12px;padding:9px 0;border-bottom:1px solid var(--rule)}
.gr .t{flex:1;min-width:0} .gr .t b{display:block;font:800 21px/1.1 var(--disp);white-space:nowrap;overflow:hidden;text-overflow:ellipsis} .gr .t small{color:var(--mute);font-size:13px}
.gr .s{font:900 32px/1 var(--disp)} .gr.l{color:var(--mute)} .gr.l .s{color:var(--mute)} .gr .s.p{color:var(--ink)}
.gf{display:flex;justify-content:space-between;align-items:center;margin-top:10px;font-size:13px;color:var(--mute)}
.gf .tug{flex:1;--cb:#A9B1C2} .gf .tug .pc{color:var(--mute)} .gf .tug .pc .pb{color:#6E7689}
.tug.favb{--ca:var(--chalk);--cb:var(--flag)} .gf .tug.favb{--ca:#A9B1C2;--cb:var(--flag)}
.gf .tug.favb .pc .pa{color:#6E7689} .gf .tug.favb .pc .pb{color:var(--flag)}
.tagf{font:800 15px/1 var(--disp);background:var(--flag);color:var(--ink);padding:4px 8px;border-radius:3px}
@media (max-width:760px){.gcards{grid-template-columns:1fr}}
/* records + stats */
.recs{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:0 28px;border-top:2px solid var(--ink)}
.rec{display:flex;flex-direction:column;gap:2px;padding:16px 2px;border-bottom:1px solid var(--rule);text-decoration:none}
a.rec:hover .v{text-decoration:underline}
.rec .k{color:var(--mute);font-size:14px} .rec .v{font:800 24px/1.1 var(--disp)} .rec .w{color:var(--mute);font-size:13px}
.finals{margin:0;padding:0;list-style:none;border-top:2px solid var(--ink)} .finals li{padding:10px 2px;border-bottom:1px solid var(--rule)}
.stats{display:grid;grid-template-columns:repeat(4,1fr);border-top:2px solid var(--ink);background:var(--paper)}
.stat{padding:14px 16px;border-bottom:1px solid var(--rule);border-right:1px solid var(--rule);display:flex;flex-direction:column}
.stat:nth-child(4n){border-right:0}
.stat .k{color:var(--mute);font-size:14px} .stat .v{font:900 38px/1.05 var(--disp)} .stat .w{color:var(--mute);font-size:13px}
.panel{background:var(--paper);border-top:2px solid var(--ink);padding:16px}
.seeds{display:grid;grid-template-columns:repeat(10,1fr);gap:8px;align-items:end;height:130px}
.sd{display:flex;flex-direction:column;align-items:center;justify-content:flex-end;gap:4px;height:100%}
.sb{width:72%;border-radius:3px 3px 0 0;min-height:2px}
.sv{font-size:11px;color:var(--mute)} .sk{font:800 17px var(--disp)}
tr.fut td{background:#fff} tr.bn td{color:var(--mute)} tr.pick td{font-style:italic}
/* team + game heads */
.hero{display:flex;align-items:center;gap:22px;margin-top:16px}
.hero h1{font-size:clamp(46px,9vw,92px);line-height:.95;padding-bottom:.06em}
.hero .sub{color:#B8C2D6;margin-top:8px}
.board{display:grid;grid-template-columns:1fr auto 1fr;gap:16px;align-items:start;margin-top:20px}
.tmw{display:flex;flex-direction:column;align-items:center;gap:10px}
.board .tm{display:flex;flex-direction:column;align-items:center;text-align:center;gap:8px;text-decoration:none;color:var(--chalk)}
.board .tm b{font:800 clamp(22px,3.4vw,34px)/1 var(--disp)}
.board .tm small{color:#B8C2D6;font-size:14px}
a.tm:hover b{text-decoration:underline}
.board .sc{font:900 clamp(48px,11vw,96px)/.9 var(--disp)}
.board .sc.l{opacity:.45}
.board .mid{text-align:center;padding-top:34px;color:#B8C2D6;font-size:14px}
.tag{display:inline-block;font:800 20px/1 var(--disp);padding:6px 12px;border-radius:3px;background:var(--flag);color:var(--ink)}
.tag.soft{background:transparent;color:var(--chalk);box-shadow:inset 0 0 0 2px var(--yard)}
.field .tug{margin-top:22px}
/* box score */
.lu{background:var(--paper);border-top:2px solid var(--ink)}
.lu .ln{display:grid;grid-template-columns:1fr 58px 1fr;border-bottom:1px solid var(--rule);align-items:stretch}
.lu .slot{display:grid;place-items:center;font:800 17px var(--disp);color:var(--chalk);background:var(--turf)}
.lu .pl{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:9px 12px;min-width:0}
.lu .pl.right{flex-direction:row-reverse;text-align:right}
.lu .pl .who{min-width:0} .lu .pl .who b{display:block;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.lu .pl .who small{color:var(--mute);font-size:12px}
.lu .pl .pts{font:800 22px var(--disp);white-space:nowrap} .lu .pl .pts small{display:block;font:500 12px var(--body);color:var(--mute)}
.lu .pl.star{background:#FBEFC4} .lu .pl.dud{background:#F4DDD7}
.lu .ln.tot .pl .pts{font-size:30px}
.vs{display:grid;grid-template-columns:1fr auto 1fr;gap:10px 18px;align-items:center}
.vs .k{text-align:center;color:var(--mute);font-size:14px}.vs .k small{display:block;font-size:11.5px;color:var(--mute);opacity:.8;margin-top:1px}
.vs .a{text-align:right;font:800 24px var(--disp)} .vs .b{font:800 24px var(--disp)}
.vs .better{color:var(--turf);text-decoration:underline;text-decoration-color:var(--flag);text-decoration-thickness:3px;text-underline-offset:4px}
footer{color:var(--mute);font-size:14px;padding:30px 0 50px;margin-top:40px;border-top:1px solid var(--rule)}

/* draft board */
.dboard{min-width:1100px!important;width:100%;table-layout:fixed} .dbwide{width:min(calc(100vw - 32px),1600px);margin-left:50%;transform:translateX(-50%)} .dboard thead th:first-child,.dboard tbody th{width:36px} .dboard td.dc{vertical-align:top;font-size:13px;line-height:1.25;min-width:100px} .dboard .pk{display:block;color:var(--mute);font-size:11px} .dboard td.dc b{display:block;font-weight:600} .dboard td.dc small{font-weight:800;font-size:14px;color:inherit} .dboard td.dc b{color:inherit} .dboard thead th{vertical-align:bottom;font-size:13px}
.draftpg .m{display:none} .draftpg.show-mw .mw,.draftpg.show-mp .mp,.draftpg.show-mr .mr{display:inline} .draftpg td.dc .m{display:none} .draftpg.show-mw td.dc .mw,.draftpg.show-mp td.dc .mp,.draftpg.show-mr td.dc .mr{display:block}
.mtog{position:sticky;top:8px;z-index:3;margin-top:28px}
.explain .steps{display:grid;grid-template-columns:repeat(4,1fr);gap:0 24px;border-top:2px solid var(--ink)} .explain .steps div{padding:14px 2px;border-bottom:1px solid var(--rule)} .explain .steps b{font:800 20px/1.1 var(--disp)} .explain .steps p{margin:6px 0 0;color:var(--mute);font-size:14px}
@media (max-width:760px){.explain .steps{grid-template-columns:1fr}}
/* h2h grid */
.grid th,.grid td{padding:9px 8px;font-size:15px} .grid td.hw{background:#DDEEE3;color:var(--win);font-weight:700} .grid td.hl{background:#F4DDD7;color:var(--loss);font-weight:700}
.tog{display:inline-flex;gap:4px;margin:0 0 14px;padding:4px;background:var(--paper);border:1px solid var(--rule);border-radius:999px}
.tog button{font:600 14px var(--body);border:0;background:none;padding:6px 14px;border-radius:999px;color:var(--mute);cursor:pointer}
.tog button[aria-pressed=true]{background:var(--turf);color:var(--chalk)}
.ttabs{background:var(--paper);border-bottom:1px solid var(--rule);position:sticky;top:0;z-index:4}
.ttabs .wrap{display:flex;gap:22px;overflow-x:auto;scrollbar-width:none}
.ttabs a{font-weight:600;font-size:15px;text-decoration:none;color:var(--mute);padding:14px 0 12px;border-bottom:3px solid transparent;white-space:nowrap}
.ttabs a:hover{color:var(--ink)} .ttabs a[aria-current=true]{color:var(--ink);border-color:var(--turf)}
.herostats{display:flex;flex-wrap:wrap;gap:8px 28px;margin-top:20px}@media(max-width:560px){.herostats{display:grid;grid-template-columns:repeat(3,1fr);gap:12px 10px}.herostats:has(>:nth-child(4):last-child){grid-template-columns:repeat(4,1fr)}.herostats:has(>:nth-child(2):last-child){grid-template-columns:repeat(2,1fr)}}
.herostats span{display:flex;flex-direction:column;color:#B8C2D6;font-size:13px} .herostats b{font:900 30px/1 var(--disp);color:var(--chalk)}
tr.gone td{color:var(--mute)}
.lchart{position:relative} .lchart .hz{cursor:pointer;outline:none}
.lcard{position:absolute;top:10px;transform:translateX(-50%);min-width:210px;max-width:260px;background:var(--ink);color:var(--chalk);padding:10px 12px;border-radius:6px;font-size:13px;line-height:1.35;display:flex;flex-direction:column;gap:2px;box-shadow:0 6px 18px rgba(0,0,0,.18);z-index:2;padding-right:30px}
@media (max-width:760px){.lcard{position:static;transform:none;max-width:none;margin-top:8px;left:auto!important}}
.lcard b{font-weight:700} .lcard > b:first-child{font:800 18px/1.1 var(--disp)} .lcard .pos{color:#7FD6A4} .lcard .neg{color:#F19A8A} .lcard .muted{color:#AEB6C7}
.bx{display:flex;gap:18px;justify-content:center;flex-wrap:wrap}
.bx span{display:flex;flex-direction:column;align-items:center;color:#B8C2D6;font-size:12px} .bx b{font:800 22px/1 var(--disp);color:var(--chalk)}
@media (max-width:760px){.bx{gap:10px;flex-wrap:nowrap} .bx b{font-size:17px} .bx span{font-size:10px}}
.lu .pl.up .pts{color:var(--win)} .lu .pl.up{background:#E7F1EA}
.mvpb{display:inline-block;margin-left:6px;font:800 11px/1 var(--disp);letter-spacing:.04em;background:var(--flag);color:var(--ink);padding:3px 5px;border-radius:3px;vertical-align:2px}
.bench td{padding:9px 10px} .bench td.bp{width:46px;text-align:center;font:800 15px var(--disp);color:var(--chalk);background:var(--turf)}
.sht{font-size:12px;font-weight:600;color:var(--loss)}
.bench tr.ir td{color:var(--loss);background:#FBEDEA} .bench tr.ir td.bp{background:var(--loss);color:#fff} .bench tr.irfirst td{border-top:3px solid var(--loss)}
.drb{display:inline-block;margin-left:6px;font:700 11px/1 var(--body);color:var(--mute);border:1px solid var(--rule);padding:2px 5px;border-radius:3px;vertical-align:2px}
.bench tr.dropx td{background:#F4F5F8} .bench tr.dropx td.bp{background:#8A93A6;color:#fff} .bench tr.ir .drb{border-color:rgba(184,50,30,.35);color:var(--loss)} .bench td b+.irb+.drb,.bench td b+.drb{white-space:nowrap}
.irb{display:inline-block;margin-left:6px;font:800 11px/1 var(--disp);background:var(--loss);color:#fff;padding:3px 5px;border-radius:3px;vertical-align:2px}
.tap{cursor:pointer} .lu .pl.tap:hover .who b,.bench tr.tap:hover b{text-decoration:underline}
.pcard{position:fixed;inset:0;z-index:20;display:grid;place-items:center;background:rgba(20,26,23,.45);padding:20px}
.pcard[hidden]{display:none} .pcard .in{background:var(--paper);border-top:4px solid var(--turf);width:min(380px,100%);padding:18px 18px 14px;display:flex;flex-direction:column;gap:4px;box-shadow:0 18px 40px rgba(0,0,0,.25)}
.pcard .in > b{font:800 26px/1.05 var(--disp)} .pcard .cp{font:900 40px/1 var(--disp);color:var(--turf);margin:6px 0 8px}
.pcard .cr{display:grid;grid-template-columns:96px 1fr auto;gap:8px;padding:7px 0;border-top:1px solid var(--rule);font-size:15px} .pcard .cr i{font-style:normal;color:var(--mute);font-size:13px}
.pcard .cpt{font:800 17px var(--disp);color:var(--turf);text-align:right;white-space:nowrap}
.pcard .x{align-self:flex-end;border:0;background:none;font:600 14px var(--body);color:var(--turf);cursor:pointer;margin-top:8px}
.gstats{padding:6px 16px 10px} .gsh{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--rule)} .gsh b{font:800 18px var(--disp)}
.gsr{display:grid;grid-template-columns:64px 1fr 64px;gap:14px;align-items:center;padding:9px 0;border-bottom:1px solid var(--rule)}
.gv{font:800 22px var(--disp);color:var(--mute)} .gv.r{text-align:right} .gv.lead{color:var(--ink)}
.gsm{display:flex;flex-direction:column;gap:5px} .gl{text-align:center;font-size:13px;color:var(--mute)}
.gsb{height:10px;border-radius:5px;background:#C8CEDA;overflow:hidden} .gsb i{display:block;height:100%;background:var(--turf);border-radius:5px 0 0 5px}
.tip{cursor:help;text-decoration:underline dotted;text-underline-offset:3px}
.tipbox{position:fixed;z-index:40;background:var(--ink);color:var(--chalk);font:500 13px/1.4 var(--body);padding:9px 11px;border-radius:6px;box-shadow:0 6px 18px rgba(0,0,0,.2);pointer-events:none;text-transform:none;letter-spacing:0}
.tipbox[hidden]{display:none} .tipbox.pin{pointer-events:auto;padding-right:30px}
.rhero .wrap{display:flex;align-items:center;gap:22px} .rbig{width:96px;height:96px}
.rhero h1{color:var(--flag)}
.rbar{background:var(--turf);border-top:1px solid var(--yard);position:sticky;top:0;z-index:6}
.rbar .wrap{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;padding:12px 20px}
.rbooks{display:flex;gap:4px;background:rgba(255,255,255,.06);border-radius:999px;padding:4px}
.rbooks button,.rper button{font:800 18px/1 var(--disp);border:0;background:none;color:#B8C2D6;padding:9px 18px;border-radius:999px;cursor:pointer}
.rbooks button[aria-pressed=true],.rper button[aria-pressed=true]{background:var(--flag);color:var(--turf)}
.rfilt{display:flex;gap:10px;align-items:center} .rper{display:flex;gap:2px;background:rgba(255,255,255,.06);border-radius:999px;padding:4px}
.rscope{appearance:none;-webkit-appearance:none;font:800 18px/1 var(--disp);color:var(--chalk);background:rgba(255,255,255,.06) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='9'%3E%3Cpath d='M1 1l6 6 6-6' stroke='%23E2AE2A' stroke-width='2' fill='none'/%3E%3C/svg%3E") no-repeat right 14px center;border:1px solid var(--yard);border-radius:999px;padding:10px 40px 10px 16px;cursor:pointer}
.rscope option{color:var(--ink)}
main.book{background:var(--turf);color:var(--chalk);padding:6px 0 60px}
.book .rposc{margin:22px 0 0} .book .chips a{background:transparent;color:#B8C2D6;border-color:var(--yard)} .book .chips a.nx{background:var(--flag);border-color:var(--flag);color:var(--turf)}
.rsec{padding-top:34px} .rsec h2{color:var(--flag);font-size:clamp(30px,4vw,42px);border-bottom:2px solid var(--flag);padding-bottom:8px;margin-bottom:0;position:sticky;top:var(--rbh,70px);z-index:5;background:var(--turf);padding-top:10px}
.rrow{display:grid;grid-template-columns:200px 52px minmax(0,1fr) 150px 150px;align-items:center;gap:16px;width:100%;padding:16px 4px;border:0;border-bottom:1px solid var(--yard);background:none;color:inherit;font:inherit;text-align:left;cursor:pointer;text-decoration:none}
.rrow:hover{background:rgba(255,255,255,.04)}
.rrow.flash,.ptable tr.flash td{animation:rflash 2.2s ease-out}
a.hrank{display:flex;flex-direction:column;color:#B8C2D6;font-size:13px;text-decoration:none} a.hrank b{font:900 30px/1 var(--disp);color:var(--flag)} a.hrank:hover b{text-decoration:underline} @keyframes rflash{0%,35%{background:rgba(226,174,42,.28)}100%{background:transparent}}
@media (prefers-reduced-motion:reduce){.rrow.flash{animation:none;background:rgba(226,174,42,.2)}} .rrow:hover .rval{color:#fff}
.rlab{font:600 14px var(--body);color:#B8C2D6}.rhold small.rwho{display:flex;flex-wrap:wrap;gap:2px 12px;margin-top:3px}.rhold small.rwho span{white-space:nowrap}.rhold small.rwho b{color:#EEF2F8;font:700 12.5px var(--body);margin-left:2px}.rlab .rhelp{display:block;margin-top:4px;font:500 12px/1.35 var(--body);color:#8C99B3;max-width:220px}
.rcols{display:grid;grid-template-columns:200px 52px minmax(0,1fr) 150px 150px;gap:16px;padding:12px 4px 6px;font:600 12px var(--body);color:#8792A8;border-bottom:1px solid var(--yard)}
.rcols span:nth-child(2){grid-column:2/4} .rcols span:nth-child(3){grid-column:4}
.rrow.rties{grid-template-columns:200px minmax(0,1fr) 150px 150px}
.rholds{display:flex;flex-direction:column;gap:10px;min-width:0} .rtie{display:grid;grid-template-columns:52px minmax(0,1fr);gap:16px;align-items:center}
.ryears{display:flex;flex-direction:column;gap:10px} .ryears .ryear{min-height:52px;display:flex;flex-direction:column;justify-content:center}
.ryears .ryear{align-items:flex-start} .rtie .rlg,.rtie .rhold{grid-area:auto!important}
.tiepill{align-self:flex-start;margin-left:68px;font:700 11px/1 var(--body);color:var(--flag);border:1px solid var(--flag);border-radius:999px;padding:4px 9px}
.rlg{width:52px;height:52px;box-shadow:0 0 0 2px var(--flag)}
.rhold{min-width:0} .rhold b{display:block;font:800 24px/1.05 var(--disp);color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis} .rhold small{display:block;color:#B8C2D6;font-size:13px;margin-top:3px}
.rrow.rties .rholds{grid-column:2/4;grid-row:1} .rrow.rties .rval{grid-column:4;grid-row:1} .rrow.rties .rtie{grid-template-columns:52px minmax(0,1fr) 150px} .ryear{display:inline-flex!important;flex-direction:column;align-items:center!important;justify-self:start;justify-content:center} .ryear small{display:block;color:#fff;font:600 12px var(--body);margin-top:5px;text-align:center}
@media (max-width:760px){.rrow.rties .rholds{grid-column:auto;grid-row:auto} .rrow.rties .rval{grid-column:auto;grid-row:auto} .rrow.rties .rtie{grid-template-columns:36px minmax(0,1fr)} .rrow.rties .rtie .ryear{grid-column:2}}
.rlg2{position:relative;width:52px;height:52px;display:block} .rlg2 .im{position:absolute;width:34px;height:34px;box-shadow:0 0 0 2px var(--turf)} .rlg2 .im:first-child{left:0;top:0} .rlg2 .im:nth-child(2){right:0;bottom:0}
.ryear b{display:inline-block;font:900 20px/1 var(--disp);color:var(--flag);border:2px solid var(--flag);border-radius:4px;padding:4px 8px} .ryear small{display:block;color:#B8C2D6;font-size:12px;margin-top:5px;line-height:1.3}
.rval{font:900 clamp(36px,4.6vw,52px)/1 var(--disp);color:var(--flag);text-align:right;white-space:nowrap}.rval .runit{display:block;font:600 12px var(--body);color:var(--mute);margin-top:4px;letter-spacing:0}
@media (max-width:760px){
  .rcols{display:none} .rrow.rties{grid-template-columns:minmax(0,1fr) auto;grid-template-areas:"lab lab" "hold val" "yrs val"} .rrow.rties .rholds{grid-area:hold} .rrow.rties .ryears{grid-area:yrs;flex-direction:row;flex-wrap:wrap;gap:6px}
  .rrow.rties .ryears .ryear{min-height:0} .rtie{grid-template-columns:36px minmax(0,1fr);gap:10px} .rtie .rlg{width:36px;height:36px} .tiepill{margin-left:46px}
  .rrow{grid-template-columns:44px minmax(0,1fr) auto;grid-template-areas:"lab lab lab" "lg hold val" "lg yr val";gap:4px 12px;padding:14px 2px}
  .rlab{grid-area:lab;margin-bottom:4px} .rlg{grid-area:lg;width:44px;height:44px;align-self:start} .rhold{grid-area:hold} .ryear{grid-area:yr;display:flex;align-items:center;gap:8px;flex-wrap:wrap} .ryear small{margin:0}
  .ryear b{font-size:15px;padding:2px 6px} .rval{grid-area:val;font-size:36px} .rhold b{font-size:20px} .rbooks button,.rper button{font-size:16px;padding:8px 13px}
}
.rmod .in{background:var(--turf);color:var(--chalk);border-top:4px solid var(--flag);width:min(640px,100%);max-height:88vh;overflow:auto}
.rmh b{display:block;font:900 34px/1.05 var(--disp);color:var(--flag);margin-top:2px} .rmod .x{color:var(--flag)}
.rtop{list-style:none;margin:10px 0 0;padding:0} .rtop li{display:flex;align-items:center;gap:10px} .rtop .rk{font:800 18px var(--disp);color:#B8C2D6;width:34px;flex:none}
.rtop .rrow{grid-template-columns:40px minmax(0,1fr) auto auto;grid-template-areas:"lg hold yr val";gap:12px;padding:12px 2px;flex:1}
.rtop .rlab{display:none} .rtop .rlg{grid-area:lg;width:40px;height:40px} .rtop .rhold{grid-area:hold} .rtop .rhold b{font-size:19px} .rtop .ryear{grid-area:yr;width:170px;text-align:right} .rtop .rval{grid-area:val;font-size:30px}
.rtop li.r1 .rval{color:#fff}
.rrow.rna{cursor:default}.rrow.rna .rval{color:#5E6B85}.rrow.rna .rlg{visibility:hidden}.rrow.rna .rhold small{color:#8C99B3}
.rtop .rlg2{grid-area:lg;align-self:center;width:40px;height:40px}.rtop .rlg2 .im{width:27px;height:27px}.rtop .rval{min-width:96px;text-align:right}.rtop .ryear{width:110px!important}
@media (max-width:760px){.rtop .rlg2{width:36px;height:36px;align-self:start}.rtop .rlg2 .im{width:24px;height:24px}.rtop .rval{min-width:0;font-size:24px}.rtop .ryear{width:auto!important}.rtop .rk{width:22px;font-size:15px}.rtop li{gap:6px}}
@media (max-width:760px){.rtop .ryear{width:auto;text-align:left} .rtop .rrow{grid-template-columns:36px minmax(0,1fr) auto;grid-template-areas:"lg hold val" "lg yr val"} .rtop .ryear{display:flex;gap:6px;align-items:center;flex-wrap:wrap}}
b.ldr{font-weight:800;color:var(--ink);box-shadow:inset 0 -3px 0 var(--flag)} i.ldp{font-style:italic;font-weight:700}
.ovw{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.15fr);gap:18px;align-items:start}
.rost .prk{display:inline-block;margin-left:6px;padding:0 5px;border:1px solid var(--rule);border-radius:3px;font:700 11px/16px var(--body);color:var(--mute);vertical-align:1px}
.ovi{background:var(--paper);border-top:2px solid var(--ink)}.ovr{display:grid;grid-template-columns:130px minmax(0,1fr);gap:10px;padding:10px 14px;border-bottom:1px solid var(--rule);font-size:14px;line-height:1.6}
.ovr .k{color:var(--mute);font-size:13px;font-weight:700}.ovr .tn,.mvm .tn{color:var(--ink);text-decoration:none;white-space:nowrap}.ovr .tn b,.mvm .tn b{font:700 15px var(--body)}.ovr .tn i{vertical-align:-5px;margin-right:4px}.ovr b{font:900 20px var(--disp)}
.ovm{display:flex;flex-wrap:wrap;gap:6px 22px;margin:0 0 10px;font-size:14px;align-items:center}.ovm span{display:inline-flex;align-items:center;gap:6px}.ovm small{font-size:12px;font-weight:700;color:var(--mute)}.ovm .tn{color:var(--ink);text-decoration:none;font-weight:700}.ovm .tn b{font:700 14px var(--body)}.ovm .tn i{vertical-align:-5px;margin-right:3px}
.wlos{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:12px 0 0}.wlos.one{grid-template-columns:1fr}.wlo{padding:10px 12px;border:1px solid var(--rule);border-radius:8px;background:var(--paper)}.wlo .k{display:block;font-size:13px;font-weight:700;color:var(--mute)}.wlo b{font:800 22px var(--disp)}.wlo small{display:block;font-size:12.5px;color:var(--mute);line-height:1.35}@media(max-width:420px){.wlos{grid-template-columns:1fr}}
.exctab th.xs{cursor:pointer;user-select:none;white-space:nowrap}.exctab th.xs small{display:block;font-size:10.5px;color:var(--mute);font-weight:600}.exctab th[aria-sort=descending]::after{content:" \\25BE"}.exctab th[aria-sort=ascending]::after{content:" \\25B4"}
.exctab td.xr{padding:6px 4px;white-space:nowrap}.exctab td.xr small{display:block;font-size:11px;color:var(--mute);margin-top:1px}.xring{position:relative;display:inline-block;width:38px;height:38px;vertical-align:middle}.xring svg{display:block}.xring b{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font:800 11.5px var(--body);color:var(--ink)}
.exctab td.rk{counter-increment:exr;color:var(--mute);font-weight:700}.exctab tbody{counter-reset:exr}.exctab td.rk::before{content:counter(exr)}.exctab td small.muted{display:block}
.txg{display:inline-flex;align-items:baseline;gap:4px;margin-left:auto;padding:3px 8px;border-radius:6px;font-size:12px;white-space:nowrap}.txg b{font:800 15px var(--disp)}.txg small{color:var(--mute)}.txg.pos{background:#E7F3EC}.txg.pos b{color:var(--win,#1E7B4A)}.txg.neg{background:#F8E9E6}.txg.neg b{color:var(--loss)}.txg.zero,.txg.na{background:#EEF1F6;color:var(--mute)}.txside .txt{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.txbl{list-style:none;margin:0;padding:0}.txbl li{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--rule)}.txbl li>b{font:800 18px var(--disp)}.txbw{margin-bottom:6px}
.psplit{margin:12px 0 0;padding:12px 14px;background:var(--paper);border:1px solid var(--rule);border-radius:8px}.psh{display:flex;flex-wrap:wrap;justify-content:space-between;gap:4px 14px;font-size:14px;margin-bottom:8px}.psh b{font:800 18px var(--disp)}.plob{color:var(--loss);font-weight:700}.plob small{color:var(--mute);font-weight:400;font-size:13px}
.pbar{display:flex;height:10px;border-radius:5px;overflow:hidden;background:#E9EDF3;gap:2px}.pbar i{display:block;min-width:3px}.pbar i.zs{background:var(--turf)}.pbar i.zn{background:#9AA3B5}.pbar i.zf{background:#D3DACF}.pbar i.zi{background:#E3A99E}.zk.zi::before{background:#E3A99E}.pkey{display:flex;flex-wrap:wrap;gap:4px 14px;margin-top:8px;font-size:12.5px;color:var(--mute)}
.ovs{grid-template-columns:repeat(8,1fr)}.ovs .stat{padding:12px 14px;min-width:0;border-right:1px solid var(--rule)!important}.ovs .stat:nth-child(8n){border-right:0!important}@media(max-width:900px){.ovs .stat:nth-child(4n){border-right:0!important}}@media(max-width:760px){.ovs .stat:nth-child(4n){border-right:1px solid var(--rule)!important}.ovs .stat:nth-child(2n){border-right:0!important}}.ovs .stat .k{white-space:nowrap;font-size:13px}.ovs .stat .v{white-space:nowrap}.ovs .stat .v small{font:600 13px var(--body);color:var(--mute);margin-left:2px}.ovm:empty{display:none}@media(max-width:900px){.ovs{grid-template-columns:repeat(4,1fr)}}.ovs .stat .v{font-size:30px}
@media(max-width:760px){.ovw{grid-template-columns:1fr}.ovr{grid-template-columns:104px minmax(0,1fr);padding:9px 10px}.ovs{grid-template-columns:repeat(2,1fr)}}
.txst{grid-template-columns:repeat(4,1fr);margin-bottom:14px}.txst .stat small{display:block;font-size:11.5px}.txh3{font:700 13px var(--body);color:var(--mute);margin:14px 0 8px}
.txdy{max-width:680px}.txax,.txrow{display:grid;grid-template-columns:38px 1fr 34px;gap:8px;align-items:center}.txax .txtl{height:16px;background:none!important}.txax i{position:absolute;transform:translateX(-50%);font:700 11px var(--body);color:var(--mute);font-style:normal}.txax i:first-child{transform:none}
.txrow{margin:4px 0}.txrow .hd{font:700 12px var(--body);color:var(--mute)}.txrow .hn{font:800 14px var(--body);text-align:right}.txtl{position:relative;height:30px;border-radius:5px;background:#F1F3F7}
.txtl u{position:absolute;top:0;bottom:0;width:1px;background:rgba(255,255,255,.7);text-decoration:none}.txtl b{position:absolute;top:5px;bottom:5px;width:3px;margin-left:-1.5px;border-radius:2px;background:#C98A00;opacity:.4}
.txhm{display:grid;grid-template-columns:38px repeat(8,1fr);gap:3px;max-width:640px}.txhm span{font-size:11px;text-align:center}.txhm .hh,.txhm .hd{color:var(--mute);font-weight:700}.txhm .hd{text-align:left;align-self:center}.txhm .hc{height:30px;border-radius:4px;background:#F1F3F7;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;box-shadow:inset 0 0 0 1px #E6EAF0}
.txwk{display:flex;align-items:flex-end;gap:4px;height:150px;max-width:640px;border-bottom:1px solid var(--rule)}.txb{flex:1;height:100%;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;position:relative}.txb i{display:block;width:100%;background:var(--turf);border-radius:3px 3px 0 0;min-height:0}.txb b{font-size:11px;margin-bottom:2px}.txb span{position:absolute;bottom:-18px;font-size:11px;color:var(--mute)}
.txwk{margin-bottom:24px}@media(max-width:600px){.txst{grid-template-columns:repeat(2,1fr)}.txhm{grid-template-columns:30px repeat(8,1fr)}.txhm .hc{height:26px;font-size:10px}}
.mvl{list-style:none;margin:0;padding:0 0 0 18px;border-left:3px solid #DDE3EC;display:flex;flex-direction:column;gap:12px}
.mvx{position:relative;background:var(--paper);border:1px solid #E3E7EE;border-radius:8px;padding:12px 14px}
.mvx::before{content:'';position:absolute;left:-27px;top:16px;width:13px;height:13px;border-radius:50%;background:var(--c,#9AA5B5);box-shadow:0 0 0 3px #fff}
.mvx.dr{--c:var(--flag)}.mvx.tr{--c:var(--turf)}.mvx.wv,.mvx.fa{--c:var(--win,#1E7B4A)}.mvx.dp{--c:var(--loss,#B03A2E)}
.mvh{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:6px}.mvc{font:800 12px var(--body);color:#fff;background:var(--c);border-radius:999px;padding:3px 10px}.mvx.dr .mvc{color:var(--turf)}
.mvw{font:700 13px var(--body);color:var(--mute)}.mvh time{margin-left:auto;font-size:12px;color:var(--mute)}
.mvm{font-size:15px;line-height:1.7}.mvm .tn{color:var(--ink);text-decoration:none;white-space:nowrap}.mvm .tn i{vertical-align:-6px;margin-right:5px}
.mvd{font-size:14px;margin-top:4px;color:var(--ink)}.mvd a{color:var(--ink);text-decoration:underline;text-decoration-color:#C9D1DE;text-underline-offset:3px}.mvd a:hover{text-decoration-color:var(--ink)}.mvd span{display:inline-block;min-width:58px;color:var(--mute);font-size:12px;font-weight:700;margin-right:6px}
.mvs{margin-top:8px;padding-top:8px;border-top:1px dashed #E3E7EE;font-size:13px}.mvs b{color:var(--mute);font-size:12px;margin-right:6px}
@media(max-width:600px){.mvh time{margin-left:0;width:100%}}
.stint td{font:500 14px var(--body);font-variant-numeric:tabular-nums}.stint th:nth-child(n+3),.stint td:nth-child(n+3){text-align:center}.stint td.big{font:inherit;color:inherit}.stint b.ldr,.stint i.ldp{font-size:inherit;font-family:inherit;line-height:inherit}.stint b.ldr{font-weight:800}.stint tr.sttot td{font-weight:700}.stint tr.stsub2 td{background:#EEF1F5;color:#4A5568;font-weight:500;border-top:1px solid #E1E6ED}.stint tr.stsub2 .tn b{font-weight:600;color:#4A5568}.stint tr.sttot td{background:#fff}.stint .tn{color:var(--ink);text-decoration:none;white-space:nowrap}.stint .tn b{font:700 14px var(--body)}.stint .tn i{vertical-align:-6px;margin-right:6px}.stint .stwk{display:block;font-size:11.5px;margin-left:30px}
.stint .nflm{margin:0 2px}@media(max-width:560px){.stint td,.stint th{padding:8px 4px;font-size:12.5px}.stint th:nth-child(5),.stint td:nth-child(5),.stint th:nth-child(7),.stint td:nth-child(7){display:none}.stint .tn b{font-size:12.5px}.stint td,.stint th{padding:8px 3px}.stint .stwk{margin-left:0}.stint .tn i{display:none}}
.stint tr.stn2{display:none}.stint tbody.open tr.stn2{display:table-row}.stint tr.stn2 td:first-child{padding-left:26px}.stint .tn{color:var(--ink);text-decoration:none;white-space:nowrap}.stint .tn b{font:700 14px var(--body)}.stint .tn i{vertical-align:-6px;margin-right:5px}
.stint .nflm{margin:0 2px}.stint .stsub{display:block;font-size:11.5px;margin:1px 0 0 14px}.stint tr.stn2 .stsub{margin-left:30px}.stint .sml2{font-size:12px;margin-left:8px;font-weight:600}@media(max-width:560px){.stint td,.stint th{padding:8px 4px;font-size:12.5px}.stint tr.stn2 td:first-child{padding-left:10px}.stint td:first-child small{display:block}}
.hrecs{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px}
.hrsec{margin-top:36px;margin-bottom:36px;background:var(--turf);color:var(--chalk);padding:18px 18px 8px;border-top:4px solid var(--flag);border-radius:4px}.hrsec h2{color:var(--flag);border:0;margin-top:0}
.hrstrip{display:flex;gap:28px;margin:0 0 18px;padding-bottom:14px;border-bottom:1px solid rgba(226,174,42,.35)}.hrstrip div{display:flex;align-items:baseline;gap:8px}.hrstrip b{font:900 26px/1 var(--disp);color:var(--chalk)}.hrstrip span{font-size:13px;color:#B8C2D6}
.hrgh{font:700 12px var(--body);color:var(--flag);margin:6px 0 6px;letter-spacing:.02em}.hrl{display:flex;flex-direction:column;margin-bottom:12px}
a.hrr{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:11px 0;border-top:1px solid rgba(255,255,255,.08);text-decoration:none;color:var(--chalk)}a.hrr:hover .hrn b{text-decoration:underline;text-decoration-color:var(--flag)}
.hrn{display:flex;flex-direction:column;min-width:0}.hrn b{font:600 15px var(--body);color:var(--chalk)}.hrn small{font-size:12px;color:#9FAAC0;margin-top:2px;display:flex;align-items:center;gap:8px}.hrtie{font-style:normal;font-weight:700;font-size:11px;color:var(--turf);background:#B8C2D6;border-radius:3px;padding:0 5px}
.hrv{font:800 26px/1 var(--disp);color:var(--flag);white-space:nowrap}
@media(max-width:560px){.hrstrip{gap:16px;flex-wrap:wrap}.hrstrip b{font-size:22px}.hrv{font-size:22px}.hrn b{font-size:14px}}
.hrsec .scroll{background:transparent;border-top:2px solid var(--flag)}.hrsec .hrt{background:transparent}.hrsec .hrt th{color:#B8C2D6;background:transparent}.hrsec .hrt td{color:var(--chalk);border-color:rgba(255,255,255,.1);background:transparent}.hrsec .hrt a.go{color:var(--chalk);text-decoration-color:rgba(226,174,42,.6)}.hrsec .hrt .muted{color:#9FAAC0}.hrsec .hrt td.big{color:var(--flag)}.hrsec .hmk{display:block;font:800 22px/1.1 var(--disp);color:var(--flag);white-space:nowrap}.hrsec .hsc2{display:block;font-size:11.5px;color:#9FAAC0;white-space:nowrap;margin-top:2px}.hrsec .hsc2.lgr{color:var(--flag);font-weight:700}.hrsec .hrt{width:100%;min-width:0!important}.hrsec .hrt td{padding:10px 10px;white-space:normal}.hrsec .hrt td:last-child{width:1%}.hrsec .hrt a.go{white-space:normal}.hrsec .hrt th{white-space:nowrap}.hrsec .scroll{overflow-x:visible}
@media(max-width:560px){.hrstrip{grid-template-columns:repeat(2,1fr)}.hrsec{padding:14px 10px 6px}}
.hrt .hrg{display:block;font-size:11.5px}.hscp{display:inline-block;font:800 11.5px var(--body);padding:2px 8px;border-radius:999px;background:#EEF1F6;color:var(--ink)}.hscp.lgr{background:var(--turf);color:var(--flag)}.hrt td.big{font-size:20px}.hrt td{vertical-align:middle}
@media(max-width:560px){.hrt td,.hrt th{padding:8px 4px;font-size:12.5px}.hrt td.big{font-size:16px}.hrt .hwn{font-size:11.5px}}
a.hrec{display:flex;flex-direction:column;gap:2px;background:var(--turf);color:var(--chalk);padding:14px 16px;border-top:3px solid var(--flag);text-decoration:none}
a.hrec .k{font-size:13px;color:#B8C2D6} a.hrec .v{font:900 40px/1.05 var(--disp);color:var(--flag)} a.hrec .w{font-size:12px;color:#B8C2D6} a.hrec:hover .v{color:#fff}
.bracket{display:grid;grid-template-columns:repeat(3,1fr);grid-template-areas:"h1 h2 h3" "a1 s1 f" "a2 s1 f" "a3 s2 f" "a4 s2 f";gap:12px 18px;margin-top:10px;align-items:start}
.bracket h3{font:800 22px var(--disp);margin:0} .bracket h3 small{font:500 13px var(--body);color:var(--mute);margin-left:6px} .bgame.mid{align-self:center}
.bcol{display:flex;flex-direction:column;justify-content:space-around;gap:14px} .bcol h3{font:800 22px var(--disp);margin:0} .bcol h3 small{font:500 13px var(--body);color:var(--mute);margin-left:6px}
.bgame{display:flex;flex-direction:column;background:var(--paper);border-left:4px solid var(--flag);position:relative}
.bseed{display:flex;align-items:center;gap:10px;padding:10px 12px;text-decoration:none;border-bottom:1px solid var(--rule)} .bseed:last-child{border-bottom:0}
a.bseed:hover b{text-decoration:underline} .bseed .bn{font:900 22px var(--disp);color:var(--flag);width:18px}
.bseed .bt{min-width:0} .bseed .bt b{display:block;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis} .bseed .bt small{color:var(--mute);font-size:12px}
.bseed.byer{min-height:56px;background:repeating-linear-gradient(135deg,transparent 0 8px,rgba(11,31,68,.035) 8px 16px)} .byc{display:inline-flex;align-items:center;justify-content:center;height:24px;padding:0 11px;flex:none;border-radius:12px;background:var(--turf);color:var(--flag);font:900 14px var(--disp);letter-spacing:.6px}
.bseed.tbd .bt b{color:var(--mute);font-weight:600} .bye{font:700 11px var(--body);color:var(--turf);background:#E3E9F5;padding:3px 8px;align-self:flex-start;margin:8px 0 0 12px;border-radius:3px}
.seedgrid td.hm{font-size:13px;font-weight:600;min-width:44px} .seedgrid td.pcut{box-shadow:inset -3px 0 0 var(--turf)}
@media (max-width:760px){.bracket{grid-template-columns:1fr;grid-template-areas:"h1" "a1" "a2" "a3" "a4" "h2" "s1" "s2" "h3" "f"}}
.kick{font:700 12px var(--body);color:var(--flag);letter-spacing:.02em}
.sline{display:block;margin-top:10px;font-size:13px;line-height:1.3;color:var(--ink)} .sline i{font-style:normal;font-weight:700;color:#A8860F;margin-right:6px}
.fo .sline,.field .sline{color:#C9D1E1;text-align:center} .fo .sline i{color:var(--flag)} .fmid{display:flex;flex-direction:column;min-width:0}
.mini .sline{margin-top:4px;font-size:12px}
details.sblock{background:var(--paper);border-top:3px solid var(--flag)} details.sblock>summary{list-style:none;cursor:pointer;display:flex;flex-direction:column;gap:6px;padding:16px 18px}
details.sblock>summary::-webkit-details-marker{display:none} details.sblock>summary b{font:800 clamp(26px,3.6vw,36px)/1.05 var(--disp)} details.sblock>summary .dek{color:var(--mute)}
details.sblock .more{font-weight:700;font-size:14px;color:var(--turf)} details.sblock .more .c{display:none} details.sblock[open] .more .o{display:none} details.sblock[open] .more .c{display:inline}
details.sblock article.story{padding:0 18px 18px;margin:0;max-width:68ch} details.sblock .by{color:var(--mute);font-size:13px}
.wsub{font:800 24px var(--disp);margin:30px 0 10px}
.glist{border-top:2px solid var(--ink);background:var(--paper)} a.grow{display:flex;align-items:center;gap:10px;padding:12px;border-bottom:1px solid var(--rule);text-decoration:none}
a.grow .kick{width:64px;flex:none;color:#A8860F} a.grow b{font-weight:600} a.grow:hover b{text-decoration:underline}
.front{background:var(--turf);color:var(--chalk);padding:26px 0 30px;border-bottom:1px solid var(--yard)}
.front .wrap{display:block}
a.fcover{display:flex;align-items:center;gap:22px;text-decoration:none;color:inherit;padding:22px;background:linear-gradient(160deg,rgba(226,174,42,.16),rgba(255,255,255,.03));border-top:4px solid var(--flag)}
a.fcover b{font:900 clamp(38px,5.4vw,64px)/.95 var(--disp)} a.fcover .dek{color:#C9D1E1;font-size:17px;max-width:56ch} a.fcover .by{color:#9AA3B5;font-size:13px}
a.fcover:hover>b{color:var(--flag)}
.fscore{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 22px;margin-top:auto;padding-top:14px;border-top:1px solid var(--yard);font-size:15px;color:#9AA3B5}
.fscore b{font:900 40px/1 var(--disp);color:#9AA3B5;margin-left:6px} .fscore .w{color:var(--chalk)} .fscore .w b{color:var(--flag)} .fscore small{font-size:12px;width:100%} .flg{display:flex;flex:none} .ftxt{display:flex;flex-direction:column;gap:8px;min-width:0} .flg .lgh{width:64px;height:64px;margin-right:-12px;box-shadow:0 0 0 3px var(--turf)}
.fside{display:flex;flex-direction:column;border-top:1px solid var(--yard)}
a.nside{display:flex;flex-direction:column;gap:4px;padding:14px 4px;border-bottom:1px solid var(--yard);text-decoration:none;color:inherit}
a.nside b{font:800 21px/1.1 var(--disp)} a.nside:hover b{color:var(--flag)} a.nside.issue b{color:var(--flag)}
.ngrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.clipx{display:none!important}.clipbtn{display:block;margin:12px 0 4px;font:700 14px var(--body);padding:9px 16px;border-radius:999px;border:1px solid var(--turf);background:#fff;color:var(--turf);cursor:pointer}
.explain details>summary{list-style:none;cursor:pointer}.explain details>summary::-webkit-details-marker{display:none}.explain summary h2{display:inline-block}.explain summary h2::after{content:' +';color:var(--mute)}.explain details[open] summary h2::after{content:' \2013'}
.pgh2{font-size:clamp(30px,4vw,42px);margin:48px 0 0;padding-top:20px;border-top:3px solid var(--ink)}
.ptable tr.pcutx{display:none}.pg[data-p="excitement"] table{min-width:0!important}.grid2>*{min-width:0}.posrt{margin:0 0 12px}
a.ncard{display:flex;flex-direction:column;gap:6px;background:var(--paper);border-top:3px solid var(--flag);padding:14px 16px;text-decoration:none}
a.ncard b{font:800 23px/1.05 var(--disp)} a.ncard .dek{color:var(--mute);font-size:14px} a.ncard:hover b{text-decoration:underline}
a.ncard.lead{background:var(--turf);color:var(--chalk);padding:22px} a.ncard.lead b{font-size:clamp(34px,4.6vw,52px)} a.ncard.lead .dek{color:#C9D1E1;font-size:16px}
a.ncard.issue{background:var(--turf);color:var(--chalk)} a.ncard.issue .dek{color:#C9D1E1}
.nlg{display:flex;gap:4px;margin-top:2px}
.nhero h1{font-size:clamp(40px,7vw,78px);line-height:.95;margin-top:10px;max-width:20ch} .nhero .kick{margin-top:16px}
.byline{display:flex;align-items:center;gap:12px;margin-top:16px;color:#B8C2D6;font-size:14px} .byline .lgb{width:44px;height:44px;margin-right:-16px;box-shadow:0 0 0 3px var(--turf)} .byline span{margin-left:22px}
article.story{max-width:68ch;margin:0 auto;padding:30px 0 10px;font-size:18px;line-height:1.65}
article.story h2{margin:30px 0 8px;font-size:30px} article.story p{margin:0 0 16px} article.story ul{margin:0 0 16px;padding-left:20px} article.story li{margin:4px 0}
article.story a.pn{border-bottom:2px solid rgba(226,174,42,.6)} article.story a.pn:hover{background:rgba(226,174,42,.15)}
a.nbox{display:flex;flex-wrap:wrap;align-items:center;gap:10px;background:var(--paper);border-left:4px solid var(--flag);padding:12px 16px;margin-bottom:24px;text-decoration:none;font-size:16px}
a.nbox span{font:800 22px var(--disp)} a.nbox .go{margin-left:auto;font:600 14px var(--body)}
a.readstory{display:flex;flex-direction:column;gap:4px;max-width:640px;margin:22px auto 0;padding:12px 16px;border:1px solid var(--yard);text-decoration:none;color:var(--chalk);font:800 22px/1.1 var(--disp);text-align:center}
a.readstory:hover{border-color:var(--flag)}
@media (max-width:760px){a.fcover{flex-direction:column;align-items:flex-start} article.story{font-size:17px}}
.pn{text-decoration:none;color:inherit} a.pn:hover{text-decoration:underline;text-underline-offset:3px}
.psearch{width:100%;font:500 17px var(--body);padding:13px 16px;border:1px solid var(--rule);border-radius:999px;background:var(--paper);margin-bottom:16px}
.plist{border-top:2px solid var(--ink);background:var(--paper)}
a.prow{display:grid;grid-template-columns:46px 1fr auto;gap:12px;align-items:center;padding:10px 12px;border-bottom:1px solid var(--rule);text-decoration:none}
a.prow[hidden]{display:none} a.prow:hover{background:#fff} a.prow:hover b{text-decoration:underline}
.prow .pp{font:800 15px var(--disp);color:var(--chalk);background:var(--turf);text-align:center;padding:4px 0;border-radius:3px}
.prow .pnm b{display:block} .prow .pnm small{color:var(--mute);font-size:13px} .prow .r{font:800 20px var(--disp)} .prow .r small{display:block;font:500 11px var(--body);color:var(--mute)}
.fproj{display:block;font:600 13px/1 var(--body);color:#B8C2D6;margin-top:6px;white-space:nowrap}
.livedot{display:inline-flex;align-items:center;gap:7px;font:800 16px/1 var(--disp);letter-spacing:.04em;color:var(--ink);background:var(--flag);padding:5px 9px;border-radius:3px;vertical-align:middle}
.livedot::before{content:"";width:8px;height:8px;border-radius:50%;background:#C0392B}
.gr .s small{display:block;font:600 12px var(--body);color:var(--mute);text-align:right}
.stg{display:inline-block;margin-left:6px;padding:2px 5px;border-radius:3px;font:700 10px/1.2 var(--body);letter-spacing:.02em;vertical-align:1px;white-space:nowrap}
.stg.fin{background:#DDEEE3;color:var(--win)} .stg.inj{background:#F4DDD7;color:var(--loss)} .stg.pk{background:#FBEFC4;color:#7A5C00}
.lu .pl .pts.pj{color:var(--mute);font-weight:600}
.bpj{color:var(--mute);font-weight:600}.bpj small{font-size:11px;margin-left:3px;font-weight:500} .lu .pl .pts.pj small{font-style:normal}
.pfilt{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:12px} .pfilt .chips{margin:0}
.pown{font:600 14px var(--body);padding:7px 12px;border-radius:999px;border:1px solid var(--rule);background:var(--paper)}
.ptable th.sortable{cursor:pointer;user-select:none;white-space:nowrap} .ptable th.sortable:hover,.ptable th[aria-sort]{color:var(--ink)}
.ptable th[aria-sort=descending]::after{content:" \\25BE"} .ptable th[aria-sort=ascending]::after{content:" \\25B4"}
.ptable th:first-child,.ptable td:first-child{position:sticky;left:0;background:var(--paper);z-index:1;box-shadow:1px 0 0 var(--rule)} .ptable tr[hidden]{display:none} .ptable td{white-space:nowrap}
.stand td.rk{white-space:nowrap} .stand .mv{display:inline-block;min-width:28px;margin-left:6px;font:700 12px var(--body);vertical-align:middle}
.mvu{color:#1E8A4C} .mvd{color:#C0392B} .stand .dlt{display:inline-block;min-width:30px;margin-left:6px;font:700 12px var(--body);text-align:right}
/* franchise */
.seasons{display:flex;gap:6px;margin-top:18px} .seasons a{font:800 18px/1 var(--disp);text-decoration:none;padding:8px 14px;border-radius:3px;color:#B8C2D6;box-shadow:inset 0 0 0 2px var(--yard)}
.seasons a[aria-current]{background:var(--chalk);color:var(--turf);box-shadow:none}
.season-break{margin-top:24px;border-top:6px solid var(--turf);padding-top:26px}
.big2{font-size:clamp(40px,6vw,60px)}
.dir{border-top:2px solid var(--ink);background:var(--paper)}
.dir a{display:grid;grid-template-columns:56px 1fr auto;gap:16px;align-items:center;padding:14px 14px;border-bottom:1px solid var(--rule);text-decoration:none}
.dir a:hover{background:#fff} .dir a:hover b{text-decoration:underline}
.dir .im{width:56px;height:56px}
.dir b{font:800 26px/1.05 var(--disp);display:block} .dir small{color:var(--mute);font-size:14px}
.dir .xr{font:600 14px var(--body);color:var(--mute)}
.dir .yr{text-align:right;font-size:14px;color:var(--mute);white-space:nowrap}
@media (max-width:760px){.dir a{grid-template-columns:44px 1fr auto;gap:12px;padding:12px 10px} .dir .im{width:44px;height:44px} .dir b{font-size:21px} .dir .yr{font-size:12px}} .dir .yr strong{display:block;font:800 22px var(--disp);color:var(--ink)}
/* season awards */
.awards4{display:grid;grid-template-columns:1fr 1fr;gap:44px 48px}
.aw .what{color:var(--mute);margin:0 0 14px;max-width:52ch}
.aw .win{display:flex;align-items:center;gap:16px;background:var(--turf);color:var(--chalk);padding:18px;text-decoration:none}
.aw .win .im{width:64px;height:64px;box-shadow:0 0 0 2px rgba(238,241,234,.35)}
.aw .win .t{flex:1;min-width:0} .aw .win b{display:block;font:800 26px/1.05 var(--disp)} .aw .win small{color:#B8C2D6;font-size:14px}
.aw .win .n{font:900 46px/1 var(--disp);color:var(--flag);white-space:nowrap}
.aw .win .n small{display:block;font:500 13px var(--body);color:#B8C2D6;text-align:right}
.aw ol{list-style:none;margin:0;padding:0;background:var(--paper)}
.aw li{display:grid;grid-template-columns:24px 36px 1fr auto;gap:10px;align-items:center;padding:8px 12px;border-bottom:1px solid var(--rule)}
.aw li .rk{font-size:15px} .aw li .v{font:800 19px var(--disp);white-space:nowrap} .aw li small{color:var(--mute);font-size:13px}
.aw li a{text-decoration:none;min-width:0} .aw li.lead{box-shadow:inset 4px 0 0 var(--flag);background:#fff} .aw .unit{color:var(--ink)}
.aw ol{border-top:2px solid var(--ink)}
.wplg{display:flex;flex-wrap:wrap;gap:6px 18px;margin:6px 0 0;font-size:12px;color:var(--mute)} .wplg span{display:inline-flex;align-items:center;gap:6px}
.wplg .sw{width:16px;height:4px;border-radius:2px;display:inline-block} .wplg .swd{width:18px;height:0;border-top:2px dashed #9AA3B2;display:inline-block}
.stbl{width:auto;min-width:320px;margin:4px 0 18px} .stbl td,.stbl th{padding:6px 14px}table.rost{width:100%}.rost th.pgrp{width:64px}@media(min-width:561px){.rost td.pl{width:24%}.rost td.stn{width:13%}}@media(max-width:760px){.rost .xd{display:none}}@media(max-width:400px){.rost td.r,.rost th.r{padding-left:1px;padding-right:2px}.rost .gsw small{font-size:10.5px}.rost .stn{font-size:11px}.rost th.pgrp,.rost td.pone{width:28px;padding-left:1px;padding-right:1px}.rost td,.rost th{padding-left:2px;padding-right:2px}.rost .stn,.rost .stn span{white-space:normal!important}.rost td.pl{max-width:92px}}.pmode{margin:18px 0 6px}.wkctl{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 12px}.wkctl select{padding:7px 10px;border:1px solid #CBD2DD;border-radius:8px;font:600 14px inherit;background:#fff}.wktab th.srt{cursor:pointer;user-select:none}.wktab th.srt[aria-sort=descending]::after{content:' \\25BE'}.wktab th.srt[aria-sort=ascending]::after{content:' \\25B4'}.wktab td.wst{font-size:13px;min-width:170px}.wktab .wsm{display:none}@media(max-width:700px){.wktab .wst{display:none}.wktab .wsm{display:block;font:400 11px var(--body);color:var(--mute);max-width:110px;margin-left:auto;white-space:normal}.wktab td,.wktab th{padding:8px 3px;font-size:12.5px}.wktab td:nth-child(4),.wktab th:nth-child(4){display:none}.wktab .tl b{display:none}.wktab td.big{font-size:15px}}.srtab th.srt{cursor:pointer;user-select:none}.srtab th.srt[aria-sort=descending]::after{content:' \\25BE'}.srtab th.srt[aria-sort=ascending]::after{content:' \\25B4'}.nflt tr.bn td{color:var(--mute)}.nflt tr.bn td.pos{color:var(--win,#1E7B4A)}.nflt tr.bn td.neg{color:var(--loss)}@media(max-width:560px){.nflt td,.nflt th{padding:8px 3px;font-size:12.5px}.nflt .nx{display:none}.nflt .tl b{display:none}}.pbar-top{margin:22px 0 0!important;padding:0!important}.pbar-top .pmode{margin:0}section.pm-season,section.pm-week{margin-top:14px!important;padding-top:0!important}.pfilt{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:10px 0 14px}.pfilt .chips{margin:0}.pfilt select,.wkctl select{height:36px}.wkctl{margin:0 0 14px}.wkctl .chips{margin:0}.ptable tbody tr.nark td:first-child::before{color:#8A94A6;background:#F1F3F7}.ptable td:first-child::before{content:attr(data-rk);display:inline-block;min-width:26px;padding-left:3px;padding-right:3px;box-sizing:border-box;margin-right:10px;padding:4px 0;border-radius:4px;background:#E9EDF3;font:700 12px/1 var(--body);font-variant-numeric:tabular-nums;color:#4A5568;text-align:center;vertical-align:1px}.ptable th:first-child,.ptable td:first-child,.wktab th:nth-child(2),.wktab td:nth-child(2){position:sticky;left:0;z-index:1;background:var(--paper,#F7F8FA)}.ptable th:first-child,.wktab th:nth-child(2){z-index:2}.ptable td:first-child,.wktab td:nth-child(2){box-shadow:1px 0 0 #E3E7EE}.rkp{display:inline-block;font:700 11.5px/1 var(--body);padding:4px 6px;border-radius:4px;letter-spacing:.02em}.rkp{background:none!important;color:var(--ink,#0B1F44);font:800 15px/1 var(--disp);padding:0}.byec.dnp{background:#F3E8E6;color:#9A3A2E}.rks{display:block;font-size:10.5px;color:var(--mute);margin-top:3px;white-space:nowrap}.glog .grs{display:none}.glog .sml{display:none}@media(max-width:700px){.glog .lgl{display:none}.glog .sml{display:inline}.glog .grk{display:none}.glog .grs{display:block;margin-top:4px}}.dcls td.pl small{display:block;font-size:11px;color:var(--mute)}.dcls tr.gone td{color:var(--mute)}.dcls tr.gone td.pos{color:var(--win,#1E7B4A)}.dcls tr.gone td.neg{color:var(--loss)}@media(max-width:700px){.dcls .xd{display:none}.dcls td,.dcls th{padding:8px 4px;font-size:12.5px}}.ohc{position:relative}.ohtip{position:absolute;z-index:5;width:190px;padding:8px 26px 8px 10px;background:var(--turf);color:var(--chalk);border-radius:6px;font-size:13px;line-height:1.35;box-shadow:0 6px 18px rgba(0,0,0,.25)}.ohtip small{opacity:.8}.ohtip .ohx{position:absolute;top:2px;right:4px;border:0;background:none;color:inherit;font-size:18px;cursor:pointer}
.ohp{cursor:pointer}.ohclr{grid-column:1/-1;padding:9px;border:1px dashed var(--rule);border-radius:6px;background:transparent;font:700 13px var(--body);color:var(--turf);cursor:pointer}
.ohl{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px;margin-top:12px}.ohl>*{min-width:0;overflow:hidden}.ohb{display:flex;align-items:center;gap:8px;border:1px solid #E3E7EE;background:#fff;border-radius:8px;padding:7px 10px;font:600 13px var(--body);cursor:pointer;text-align:left}.ohb i:first-child{width:12px;height:12px;border-radius:3px;flex:none}.ohb span{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.ohb b{font:800 14px var(--disp)}.ohb.on{border-color:var(--navy,#0B1F44);box-shadow:0 0 0 1px var(--navy,#0B1F44)}.ohb.off{opacity:.45}@media(min-width:900px){.ohl{grid-template-columns:repeat(5,minmax(0,1fr))}}.ohk{margin:0 0 10px}.exc{margin-top:10px;display:flex;flex-direction:column;align-items:center}.exc b{font:800 26px/1 var(--disp);color:var(--gold,#C9A227)}.exc small{font-size:11px;color:var(--mute);text-transform:none}.rost th.srt{cursor:pointer;user-select:none}.rost th.srt[aria-sort=descending]::after{content:' \\25BE'}.rost th.srt[aria-sort=ascending]::after{content:' \\25B4'}.rost td.pone{font:800 13px var(--disp);color:var(--mute);text-align:center;width:38px}.rtog{display:flex;gap:6px;margin:0 0 10px}.rtog button{border:1px solid #CBD2DD;background:#fff;border-radius:999px;padding:6px 14px;font:600 13px inherit;cursor:pointer}.rtog button[aria-pressed=true]{background:var(--navy,#0B1F44);color:#fff;border-color:transparent}.rost tr.gone td{color:inherit}.rost tr.gone td.pos{color:var(--win,#1E7B4A)}.rost tr.gone td.neg{color:var(--loss)}.rost tr.gone td.muted{color:var(--mute)}.wpos td.hm{font-variant-numeric:tabular-nums;color:#0B1F44}.wpos th.srt{cursor:pointer;user-select:none}.wpos th.srt[aria-sort=descending]::after{content:' \\25BE'}.wpos th.srt[aria-sort=ascending]::after{content:' \\25B4'}.wpos td.rkn{color:var(--mute);font-weight:700;width:28px}.wpos .tl{display:flex;align-items:center;gap:8px;white-space:nowrap}.wstrip{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin:0 0 18px}.wstrip div{background:#fff;border:1px solid #E3E7EE;border-radius:8px;padding:10px 6px;text-align:center;display:flex;flex-direction:column;gap:2px}.wstrip .p{font:800 15px var(--disp);color:var(--navy,#0B1F44)}.wstrip b{font:800 18px var(--disp)}.wstrip small{font-size:11px;color:var(--mute)}@media(max-width:560px){.wstrip{grid-template-columns:repeat(3,1fr)}.wpos .tl b{display:none}.wpos td,.wpos th{padding:8px 4px;font-size:12.5px}}.pwr td{vertical-align:middle}.pwr td.rk{white-space:nowrap}.pwr .mv{font-size:11px;margin-left:4px}.pwr td.pw{width:34%;min-width:150px}.pwr td.pw b{display:inline-block;width:52px;font:800 20px var(--disp)}.pwr .pbar{display:inline-block;vertical-align:middle;position:relative;width:calc(100% - 60px);height:10px;background:#EEF1F5;border-radius:5px}.pwr .pbar::before{content:'';position:absolute;left:50%;top:-3px;bottom:-3px;width:1px;background:#9AA5B5}.pwr .pbar i{position:absolute;top:0;bottom:0;border-radius:5px}.pwr .pbar i.up{background:var(--win,#1E7B4A)}.pwr .pbar i.dn{background:var(--loss,#B03A2E)}.pwr .sml{display:none}@media(max-width:560px){.pwr td.pw{min-width:0;width:auto}.pwr td.pw b{width:auto;font-size:17px}.pwr .pbar{display:none}.pwr td,.pwr th{padding:8px 2px;font-size:12.5px}.pwr .lgl{display:none}.pwr .sml{display:inline}.pwr td .tl small,.pwr td small{display:none}.pwr .mv{display:block;margin:0}}.stog{display:none}.stand td.b{min-width:0}.stand .bar{width:44px;margin-right:6px}.stand .dlt{min-width:0;margin-left:4px}.stand td,.stand th{padding-left:9px;padding-right:9px}@media(max-width:560px){.stand td.b{min-width:0}.stog{display:flex}.stand{min-width:0!important;width:100%}.stand td,.stand th{padding:9px 3px;font-size:12.5px}.stand td.rk{padding-left:8px}.stand .bar{display:none}.stand .dlt{display:block;min-width:0;margin:1px 0 0;font-size:10px;text-align:left}.stand .mv{display:block;min-width:0;margin:0;font-size:10px}.stand td small{display:none}.stand td:nth-child(2){max-width:128px}.stand td:nth-child(2) *{white-space:normal}.stand td:nth-child(2) img{width:26px;height:26px}.stand .big{font-size:17px}.stand[data-v=odds] .cp{display:none}.stand[data-v=points] .co{display:none}}@media(max-width:380px){.stand td,.stand th{padding:9px 2px;font-size:12px}.stand td:nth-child(2){max-width:112px}}.glog td,.glog th{white-space:nowrap}.glog td.gst{white-space:normal;min-width:180px;font-size:13px}.glog .gsm{display:none}@media(max-width:700px){.glog{min-width:0!important;width:100%}.glog .gst{display:none}.glog .gsm{display:block;font:400 11px var(--body);color:var(--mute);white-space:normal;max-width:120px;margin-left:auto}.glog td,.glog th{padding:8px 3px;font-size:12.5px}.glog .tl b{display:none}.glog td.big{font-size:16px}}.rost .stn{font-size:13px;color:var(--mute);width:1%}.rost .gsw{white-space:nowrap}.rost .gsw .gx{display:block;font-size:10.5px;color:var(--mute)}.rost .gsw small{display:inline;color:var(--mute);font-size:12px}.rost th.pgrp{vertical-align:middle;text-align:center;font:800 26px var(--disp);letter-spacing:.5px;color:var(--navy,#0B1F44);background:#F3F5F9;border-right:1px solid #E3E7EE;padding:10px 5px}.rost tr.gtop td,.rost tr.gtop th{border-top:2px solid #C9D0DB}.rost .stn span{white-space:nowrap}@media(max-width:560px){.rost td,.rost th{padding:8px 3px;font-size:12.5px}.rost th.pgrp{font-size:20px;padding:10px 4px;width:38px}.rost td:first-child{padding-left:0}.rost .stn{font-size:12px}.rost td small{font-size:11px}.rost td:first-child{min-width:0}}@media(max-width:560px){table.grid.stbl{min-width:0!important;width:100%}.stbl td,.stbl th{padding:6px 8px;white-space:normal}} .stbl td.r,.stbl th.r{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}.stbl td.rl{white-space:nowrap}
.bench .swp{color:#9AA3B2;font-size:12px;font-variant-numeric:tabular-nums;white-space:nowrap}
.bench .swp.sh{color:var(--loss);font-weight:800;background:#FBE6E3;padding:2px 6px;border-radius:3px}
.cmpbar{display:flex;align-items:center;gap:12px;margin:0 0 16px} .cmpbar select{font:600 16px var(--body);padding:8px 10px;border:1px solid var(--ink);background:#fff;flex:1;max-width:240px} .vsx{color:var(--mute);font-weight:600}
.cmpo{background:var(--paper);border-top:2px solid var(--ink);padding:18px 16px 8px;max-width:760px}
.chead{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:12px;margin-bottom:8px} .cside{display:flex;flex-direction:column;align-items:center;text-align:center;color:var(--ink);text-decoration:none;gap:4px}
.cside .im{width:64px;height:64px} .cside b{font:800 22px/1.05 var(--disp)} .cside small{color:var(--mute);font-size:13px}
.cser{text-align:center} .cser b{font:900 52px/1 var(--disp);display:block;white-space:nowrap} .cser b span{color:var(--mute);margin:0 4px} .cser small{color:var(--mute);font-size:13px}
.csub{font:800 18px var(--disp);margin:20px 0 4px;text-align:center;color:var(--mute)}
.crow{display:grid;grid-template-columns:1fr auto 1fr;gap:12px;padding:7px 0;border-bottom:1px solid var(--rule);align-items:center} .crow .cl{color:var(--mute);font-size:13px;text-align:center;min-width:120px}
.crow .cv{font:700 18px var(--disp)} .crow .cv.r{text-align:right} .crow .cw{color:var(--turf)} .crow .cw::after{content:"";display:inline-block;width:6px;height:6px;background:var(--flag);border-radius:50%;margin:0 6px;vertical-align:middle} .crow .cv.r.cw::after{display:none} .crow .cv.r.cw::before{content:"";display:inline-block;width:6px;height:6px;background:var(--flag);border-radius:50%;margin:0 6px;vertical-align:middle}
.cgames{display:flex;flex-wrap:wrap;gap:6px;justify-content:center;margin:10px 0 4px} .cgames a{display:flex;gap:6px;align-items:baseline;padding:6px 10px;border:1px solid var(--rule);background:#fff;color:var(--ink);text-decoration:none;font-size:14px} .cgames a span{color:var(--mute);font-size:12px} .cgames i{color:var(--mute);font-style:normal}
@media (max-width:760px){.cside .im{width:48px;height:48px} .cside b{font-size:18px} .cser b{font-size:40px} .crow .cl{min-width:90px}}
.aw li.hst{grid-template-columns:24px 1fr auto;align-items:start;padding:12px} .aw li.hst .rk,.aw li.hst .v{padding-top:6px}
.hst .hm{display:flex;flex-wrap:wrap;align-items:center;gap:6px 8px} .hst .ht{display:inline-flex;align-items:center;gap:6px;color:var(--ink)} .hst .ht .im{width:26px;height:26px}
.hst .ht b{font-weight:700;font-size:15px} .hst .ov{color:var(--mute);font-size:13px} .hst .hw{color:var(--mute);font-size:12px;margin-left:auto;white-space:nowrap}
.hst .hg{display:grid;grid-template-columns:auto 1fr;gap:3px 10px;margin-top:8px;font-size:13px;line-height:1.35} .hst .hl{font-weight:700;white-space:nowrap}
.hst .v small{display:block;font:500 11px var(--body);color:var(--mute);text-align:right}
.trophies{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:0 28px;border-top:2px solid var(--ink)}
.trophy{display:block;padding:16px 2px;border-bottom:1px solid var(--rule);color:inherit;text-decoration:none} a.trophy:hover b{text-decoration:underline} .trophy .go{display:block;color:var(--turf);font-weight:700;margin-top:4px} .trophy b{display:block;font:800 24px/1.1 var(--disp)} .trophy span{color:var(--mute);font-size:14px}
.trophy a{font-weight:600;color:var(--turf);font-size:14px} .aw li a:hover b{text-decoration:underline}
@media (max-width:760px){.awards4{grid-template-columns:1fr;gap:36px} .aw .win .n{font-size:38px}}
@media (max-width:760px){
  .wrap{padding:0 16px}
  .ft .im{width:40px;height:40px}
  .top .wrap{flex-direction:column;align-items:flex-start;gap:0;padding-top:12px}
  .menu{width:100%} .menu a{padding:10px 0 10px}
  .cols,.grid2{grid-template-columns:1fr;gap:8px}
  a.fo{grid-template-columns:1fr;gap:10px;padding:16px 0}
  .ft .im{width:40px;height:40px} .ft.b{flex-direction:row;text-align:left}
  .fo .fmid{order:3}
  .teams{grid-template-columns:repeat(3,1fr)}
  .stats{grid-template-columns:repeat(2,1fr)} .stat:nth-child(4n){border-right:1px solid var(--rule)} .stat:nth-child(2n){border-right:0}
  .seeds{gap:3px} .sv{font-size:9px}
  .lu .ln{grid-template-columns:1fr 42px 1fr} .lu .pl{padding:8px 8px} .lu .pl .who b{font-size:13px;white-space:normal;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;line-height:1.2} .lu .pl .pts{font-size:19px}
  .hero{gap:14px} .lgh{width:68px;height:68px}
  .race a{grid-template-columns:22px minmax(0,1fr) 40px 70px 40px;gap:8px;padding:10px 6px}
  .race .who .im{display:none}
}
"""

CSS += """
@media(min-width:701px){.dcls .mnow{display:none!important}}

.rlg2{position:relative}@media(max-width:760px){.rlg2{grid-area:lg;align-self:start;width:44px;height:44px}.rlg2 .im{width:29px;height:29px}.rtie .rlg2{width:36px;height:36px}.rtie .rlg2 .im{width:24px;height:24px}}.rtie .rlg2{grid-area:auto!important}.rlgn{position:absolute;right:-6px;bottom:-4px;background:var(--flag,#e0b43a);color:#0B1F44;font:800 11px/1 var(--body,inherit);border-radius:9px;padding:3px 5px;box-shadow:0 0 0 2px var(--field,#0b1a3a)}

.stint .ofw{display:inline!important;margin:0!important;font-size:inherit;font-weight:500;color:var(--mute)}.stint td:has(.ofw){white-space:nowrap}

.ncard .kick,a.bseed .bn{color:#8A6A00}.field .ncard .kick,.dk .ncard .kick{color:var(--flag)}

.ptable .psub,.ptable .pnl{display:none}.ptable .nw{white-space:nowrap}@media(max-width:760px){.ptable td:first-child{white-space:normal;min-width:180px;max-width:200px}.ptable .pnl{display:inline-block;vertical-align:-3px;margin-left:6px}.ptable .psub{display:block;color:var(--mute);font-size:12px;font-weight:500;margin-top:2px;white-space:normal;max-width:150px}.ptable th:nth-child(2),.ptable td:nth-child(2),.ptable th:nth-child(3),.ptable td:nth-child(3),.ptable th:nth-child(4),.ptable td:nth-child(4){display:none}}

.top .wrap{flex-wrap:nowrap}.tact{display:flex;gap:6px;margin-left:auto}.tbtn{display:inline-flex;align-items:center;gap:6px;background:transparent;border:1px solid rgba(255,255,255,.18);color:#DCE3F0;border-radius:999px;padding:7px 12px;font:600 14px var(--body,inherit);cursor:pointer}.tbtn:hover,.tbtn:focus-visible{color:#fff;border-color:var(--flag)}
.nvo{position:fixed;inset:0;z-index:60;background:rgba(6,14,34,.55);display:flex;justify-content:flex-end}.nvo[hidden]{display:none}.nvp{width:min(440px,100%);height:100%;background:var(--paper);color:var(--ink);display:flex;flex-direction:column;box-shadow:-10px 0 30px rgba(0,0,0,.25)}
.nvh{display:flex;gap:8px;align-items:center;padding:14px 16px;border-bottom:1px solid var(--rule)}.nvh input{flex:1;font:500 16px inherit;padding:10px 12px;border:1px solid var(--rule);border-radius:8px;background:var(--chalk,#fff);color:var(--ink)}.nvh input:focus{outline:2px solid var(--flag);outline-offset:0}.nvx{background:none;border:0;font-size:26px;line-height:1;color:var(--mute);cursor:pointer;padding:4px 8px}.nvx:hover{color:var(--ink)}
.nvb{overflow-y:auto;padding:8px 16px 24px;flex:1}.nvg h3{font:700 12px inherit;color:var(--mute);margin:18px 0 6px;letter-spacing:.02em}.nvg a,.nvr a{display:flex;align-items:center;gap:10px;padding:10px 8px;border-radius:8px;text-decoration:none;color:var(--ink);font-weight:600}.nvg a:hover,.nvr a:hover,.nvr a.on{background:var(--rule)}.nvg a small,.nvr a small{margin-left:auto;color:var(--mute);font-weight:500;font-size:12px;white-space:nowrap}.nvg a[aria-current=page]{box-shadow:inset 3px 0 0 var(--flag)}.nvr .none{color:var(--mute);padding:14px 8px}.nvr .im{width:24px;height:24px;flex:none}
@media(max-width:760px){.top .wrap{flex-direction:row!important;flex-wrap:wrap!important;align-items:center!important;padding-top:10px}.tact{margin-left:auto}.menu{order:3;width:100%;flex:0 0 100%}.tbtn span{display:none}.tbtn{padding:8px}}

.lu .pl .who > .mvpb{margin:2px 0 1px;vertical-align:0}.lu .pl .who b{white-space:normal;text-overflow:clip;overflow:visible;display:block}
"""
CSS += """
.ttabs .tvw{color:var(--ink);font-weight:700}.ttabs .tvw[aria-current=true]{border-color:var(--flag,#e0b43a)}.ttabs .tsep{flex:0 0 1px;background:var(--rule);margin:12px 0}.unx .faceoffs{background:var(--field,#0b1a3a);border-radius:10px;padding:6px 18px}@media(max-width:640px){.ttabs .wrap{gap:15px}.ttabs a{font-size:14px}}
"""
CSS += """
.fo .fsl{grid-column:1/-1;order:9;display:block;margin-top:10px;color:#fff;font-size:14px;font-weight:600}.fo .fsl i{font-style:normal;color:var(--gold,#e0b43a);font-size:11px;font-weight:700;margin-right:8px;text-transform:none}
"""
CSS += """
.mnow{display:none}@media(max-width:700px){.dcls .mnow{display:block;color:var(--mute)}}
"""
CSS += """

"""
CSS += """
.gbt{display:inline-block;min-width:84px;text-align:center}.swg{display:block;font-size:11px;color:var(--mute);font-weight:500;white-space:nowrap}.nw{white-space:nowrap}.trm{display:none;font-size:13px;margin-top:4px;color:var(--mute)}@media(max-width:640px){.trtab{min-width:0!important}.trtab .trx{display:none}.trtab .trm{display:block}.trtab td.c,.trtab th.c,.trtab td.rk,.trtab th:first-child{display:none}.trtab td.r{white-space:nowrap}}details.how{margin:-4px 0 18px}details.how summary{cursor:pointer;font-weight:600;font-size:14px}@media(max-width:640px){.exctop .exmb{display:none!important}.exctop td,.exctop th{padding-left:6px;padding-right:6px}.exctop td:nth-child(3){font-size:12px;white-space:nowrap}}
"""
CSS += """
/* trade analyzer */
.tapick{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:8px}
.tasel{display:flex;flex-direction:column;gap:6px;margin-bottom:10px}.tasel span{font:700 13px var(--body);color:var(--mute)}
.tasel select{font:600 16px var(--body);padding:10px 12px;border:1px solid var(--rule);border-radius:6px;background:var(--paper);color:var(--ink)}
.tal{display:flex;flex-direction:column;border-top:2px solid var(--ink);background:var(--paper)}
.tarow{border-bottom:1px solid var(--rule)}.tarow.on{background:#FBF1D6}
.tapl{display:grid;width:100%;grid-template-columns:46px minmax(0,1fr) auto;align-items:stretch;gap:0;border:0;background:var(--paper);padding:0;text-align:left;cursor:pointer;font:inherit;color:var(--ink)}
.tapl .tpos{display:flex;align-items:center;justify-content:center;font:800 15px var(--disp);color:var(--chalk);background:var(--turf)}
.tapl .tnm{padding:9px 12px;min-width:0}.tapl .tnm b{font-weight:600}.tapl .tnm small{display:block;color:var(--mute);font-size:12px}
.tapl .tv{padding:9px 12px;text-align:right;font-variant-numeric:tabular-nums}.tapl .tv b{display:block;font:700 18px var(--disp)}.tapl .tv small{color:var(--mute);font-size:12px;white-space:nowrap}
.tapl:hover{background:#EEF1F6}.tapl.on{background:#FBF1D6;box-shadow:inset 4px 0 0 var(--flag)}.tapl.on .tpos{background:var(--flag);color:var(--turf)}
.tapl:focus-visible{outline:2px solid var(--flag);outline-offset:-2px}
.tadeal{margin:22px 0 6px;padding:14px 16px;background:var(--turf);color:var(--chalk);border-radius:4px}.tadeal p{margin:2px 0}.tadeal b{color:var(--flag)}
.tagrid{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:14px}
.tacard h3{display:flex;align-items:center;gap:8px;margin:0 0 10px;font:800 24px var(--disp)}.tacard h3 small{font:500 13px var(--body);color:var(--mute)}
.tacard .pt td,.tacard .pt th{padding:7px 8px}.tadest{display:flex;align-items:center;gap:8px;padding:0 12px 10px 58px;font:600 13px var(--body);color:var(--mute)}
.tadest select{font:600 14px var(--body);padding:6px 8px;border:1px solid var(--rule);border-radius:6px;background:var(--paper);color:var(--ink)}
.tahd{display:flex;align-items:flex-end;gap:10px}.tahd .tasel{flex:1}
.tarm{margin-bottom:10px;padding:10px 12px;border:1px solid var(--rule);border-radius:6px;background:var(--paper);font:600 13px var(--body);color:var(--mute);cursor:pointer}
.taadd{margin:16px 0 0;padding:12px 18px;border:2px dashed var(--turf);border-radius:6px;background:transparent;font:700 15px var(--body);color:var(--turf);cursor:pointer}
.taadd:hover,.tarm:hover{background:#EEF1F6}
.tan{display:flex;align-items:center;gap:6px;margin:4px 0 16px;flex-wrap:wrap}.tan span{font:700 13px var(--body);color:var(--mute);margin-right:6px}
.tan select{font:700 16px var(--body);padding:9px 12px;border:1px solid var(--rule);border-radius:6px;background:var(--paper);color:var(--ink)}
.tal.tcl{max-height:330px;overflow-y:auto;overscroll-behavior:contain}.tal.tcl .talh{position:sticky;top:0;z-index:2;background:var(--paper)}
.tamore{width:100%;padding:10px;border:1px solid var(--rule);border-top:0;background:var(--chalk,#fff);font:700 14px var(--body);color:var(--turf);cursor:pointer}.tamore:hover{background:#EEF1F6}
.tapl .tv small{display:block;line-height:1.3}.tapl .tnm,.tapl .tv{padding-top:8px;padding-bottom:8px}
.tasel2{margin:6px 0 0;font-size:13px;color:var(--mute)}
.omd{margin-top:10px}.omd summary{cursor:pointer;font:700 14px var(--body);color:var(--turf)}
.glog tr.dead td{background:#FBF0EE}.glog tr.dead td:first-child{box-shadow:inset 3px 0 0 var(--loss)}.dnpl{display:block;font:700 10px var(--body);letter-spacing:.04em;color:var(--loss);margin-top:1px}
.gft{margin:0 0 10px;display:flex;align-items:center;flex-wrap:wrap;gap:8px}.wpstep{margin-left:auto;display:inline-flex;gap:6px}.wpstep .wps{font:600 13px var(--body);padding:6px 12px;border-radius:999px;border:1px solid var(--rule);background:var(--paper);color:var(--ink);cursor:pointer}.wpstep .wps:hover{border-color:var(--ink)}.gfh{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;margin:2px 0 8px}.gft1{display:flex;align-items:center;gap:10px}.gft1.r{justify-content:flex-end}.gfh b{display:block;font:800 28px/1 var(--disp)}.gfh small{color:var(--mute);font-size:12px;display:inline-flex;align-items:center;gap:5px}.gfh .r{text-align:right}.gfh .r small{justify-content:flex-end}
.gfm{text-align:center}.gfm b{font-size:22px}.gfl{display:inline-block;width:16px;border-top:3px solid var(--turf)}.gfl.d{border-top:3px dashed #C9A21A}
.xcap{display:flex;align-items:center;gap:8px;margin:10px 0 26px;padding:0 2px;font-size:12px;color:var(--mute)}.xcap b{font:800 15px var(--disp);color:var(--ink)}.xcap small{margin-left:-6px}
.xcap .xbr{flex-basis:100%;display:flex;flex-wrap:wrap;gap:4px 12px;margin-top:6px;font-size:12px;color:var(--mute)}.xcap .xbr i{font-style:normal}.xcap .xbr small{margin-left:3px;font-size:11px}.xcap .xbr b{color:var(--ink)}.exm{width:72px;height:5px;border-radius:3px;background:var(--rule);overflow:hidden}.exm i{display:block;height:100%;background:var(--flag)}.xcap{display:block;margin:12px 0 26px;padding:12px 14px;border:1px solid var(--rule);border-radius:10px;background:var(--paper)}.xcap .xhd{display:flex;align-items:center;gap:12px}.xcap .xl{font-weight:700;font-size:14px;color:var(--ink)}.xcap .xhd b{font:800 26px var(--disp);color:var(--ink);line-height:1}.xcap .exm{flex:1;width:auto;height:10px;border-radius:5px}.xcap .xft{display:flex;flex-wrap:wrap;gap:4px 12px;margin-top:8px;font-size:13px}.xcap .xrk{color:var(--ink)}.xcap .xgo{margin-left:auto;color:var(--mute);text-decoration:underline}.xcap .xgo:hover{color:var(--turf)}.xcap .xdt{margin-top:8px}.xcap .xdt summary{cursor:pointer;font-size:13px;font-weight:600;color:var(--mute)}.xcap .xdt[open] summary{color:var(--ink)}.xcap .xbr{margin-top:8px}.tat2x{display:inline-flex;align-items:center;gap:8px}
.pbtab{margin-top:14px;border-top:1px solid var(--rule);padding-top:10px}.pbtab summary{cursor:pointer;font-weight:600;font-size:14px;color:var(--mute)}.pbtab[open] summary{color:var(--ink)}
.pbsc{max-height:520px;overflow:auto;margin-top:10px;border:1px solid var(--rule);border-radius:8px}.pbtab table{width:100%;min-width:640px;border-collapse:collapse;font-size:13px}
.pbtab thead th{position:sticky;top:0;background:var(--paper);z-index:1;font-size:12px;color:var(--mute);font-weight:600;text-align:left;padding:8px 10px;border-bottom:1px solid var(--rule)}.pbtab th.r,.pbtab td.r{text-align:right}
.pbtab th small,.pbtab td small{display:block;font-size:11.5px;color:var(--mute);font-weight:500}.pbtab td{padding:8px 10px;border-bottom:1px solid var(--rule);vertical-align:top}
.pbtab .pbt{white-space:nowrap;color:var(--ink)}.pbtab .pbg{white-space:nowrap}.pbtab .pbp{min-width:220px;color:var(--ink)}.pbtab .pbws{display:flex;flex-wrap:wrap;gap:3px 10px;margin-top:4px;font-size:12px;color:var(--mute)}.pbtab .pbw{display:inline-flex;align-items:center;gap:4px}.pbtab .pbw .im{width:16px;height:16px}
.pbtab .pbw b.up{color:#1E7A43}.pbtab .pbw b.dn{color:#B23A2E}.pbtab .pbn,.pbtab .pba{white-space:nowrap;font-variant-numeric:tabular-nums;color:var(--mute)}.pbtab .pbn.chg{color:var(--ink);font-weight:700;background:rgba(201,162,26,.12)}.pbtab .pbn.up{color:#1E7A43;font-weight:700}.pbtab .pba{font-weight:700;color:var(--ink)}.pbtab table{min-width:760px}
.omvp{display:flex;align-items:center;gap:12px;padding:14px 16px}.omvp .im{width:34px;height:34px}.omvt{flex:1;min-width:0}.omvt b{display:block;font-size:15px;color:var(--ink)}.omvt small{color:var(--mute);font-size:12.5px}.omvn{display:flex;align-items:baseline;gap:8px;font:800 28px/1 var(--disp)}.omvn span{color:var(--mute);font-size:22px}.omvn i{font-style:normal;color:var(--flag);font-size:20px}.omvn strong{color:var(--ink)}.omvd{min-width:64px;text-align:right;font-weight:700}
.tp .tpc{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(250px,1fr);background:radial-gradient(120% 140% at 100% 0%,#1d2c52 0%,#0f1a33 55%,#0b1428 100%);color:#EEF2F8;border-radius:16px;overflow:hidden;box-shadow:0 10px 30px rgba(11,20,40,.18)}
.tp .tpl{padding:22px 24px 20px}.tp .tpg{display:flex;align-items:center;flex-wrap:wrap;gap:6px;font-size:13px;color:#C7D2E4}.tp .tpg .nfl{width:18px;height:18px;margin:0}.tp .tpg b{color:#EEF2F8;margin-right:2px}.tp .tpat{opacity:.6;margin:0 2px}.tp .tpk{margin-left:10px;padding:2px 8px;border-radius:999px;background:rgba(201,162,26,.16);color:#E2C25A;font-weight:700}.tp .tpw{margin-left:auto;color:#8FA0BC}
.tp .tpx{margin:14px 0 16px;font:800 clamp(22px,3.1vw,31px)/1.08 var(--disp);letter-spacing:.2px;color:#fff;text-wrap:balance}
.tp .tpps{display:flex;flex-wrap:wrap;gap:8px}.tp .tpp{display:inline-flex;align-items:center;gap:6px;padding:4px 12px 4px 4px;border-radius:999px;background:rgba(238,242,248,.09);color:#EEF2F8;text-decoration:none;font-size:13.5px;font-weight:600}.tp .tpp:hover{background:rgba(238,242,248,.16)}.tp .tpp .im{width:22px;height:22px}.tp .tpp .nfl{width:16px;height:16px;margin:0}.tp .tpp b{color:#8FD6A4}
.tp .tpr{padding:22px 24px 20px;background:rgba(201,162,26,.07);border-left:1px solid rgba(238,242,248,.1);display:flex;flex-direction:column;justify-content:center;gap:10px}.tp .tpt{display:flex;align-items:center;gap:8px;font-size:15px}.tp .tpt .im{width:26px;height:26px}
.tp .tpn{display:flex;align-items:baseline;gap:10px;font:800 44px/1 var(--disp)}.tp .tpn span{color:#8FA0BC;font-size:30px}.tp .tpn i{font-style:normal;color:#C9A21A;font-size:26px}.tp .tpn strong{color:#E2C25A}
.tp .tpbar{position:relative;height:10px;border-radius:5px;background:rgba(238,242,248,.12);overflow:hidden}.tp .tpbar i{position:absolute;top:0;bottom:0;left:0}.tp .tpbar .b0{background:rgba(238,242,248,.35)}.tp .tpbar .b1{background:#C9A21A}.tp .tpbar em{position:absolute;top:-2px;bottom:-2px;width:1px;background:rgba(255,255,255,.55)}
.tp .tps{font:800 20px var(--disp);color:#8FD6A4}.tp .tps small{font:600 12px var(--body);color:#8FA0BC;margin-left:4px}.tp .tpf{font-size:12.5px;color:#8FA0BC}
@media (max-width:760px){.tp .tpc{grid-template-columns:1fr}.tp .tpr{border-left:0;border-top:1px solid rgba(238,242,248,.1)}.tp .tpl,.tp .tpr{padding:18px 16px}.tp .tpw{margin-left:0;flex-basis:100%}.tp .tpn{font-size:38px}}
.rhold b{display:inline-block;max-width:calc(100% - 64px);vertical-align:middle}.rnfl{display:inline-flex;align-items:center;gap:4px;margin-left:8px;font:600 12px var(--body);color:#8E99AF;vertical-align:middle}.rnfl .nfl{width:16px;height:16px;margin:0}
.vs .gut{white-space:nowrap}.vs .gut small{font:700 13px var(--body);margin-left:5px}
.gsx{display:flex;justify-content:space-between;gap:12px;margin:0;padding:0 0 10px;font-size:12px;color:var(--mute);border-bottom:1px solid var(--rule)}.gsr:has(+ .gsx){border-bottom:0;padding-bottom:4px}.vs .vsh{display:flex;align-items:center;gap:6px;font:700 13px var(--body);color:var(--mute);justify-content:flex-end}.vs .b.vsh{justify-content:flex-start}
.seedgrid td.imp{color:#B6BFCD;font-weight:700;background:repeating-linear-gradient(135deg,#F3F5F8,#F3F5F8 4px,#ECEFF3 4px,#ECEFF3 8px)}.impk{color:#9AA3B2;font-weight:800}.lt1{font-size:11px;color:var(--mute)}
.seedgrid td.avgs{border-left:2px solid var(--rule)}.sdt{margin:0 0 10px}.sdr{cursor:pointer}.seedsec.iso .sdr:not(.on){opacity:.18}
.nms{display:none}@media(max-width:600px){.nmf{display:none}.nms{display:inline}}
.tawin{margin:16px 0 0;font-size:17px}
.tat3{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px}
.tat2{background:var(--turf);color:var(--chalk);border-radius:4px;padding:10px 12px}.tat2 span{display:block;font:600 12px var(--body);opacity:.8}
.tat2 b{display:block;font:800 30px/1.05 var(--disp);color:var(--flag)}.tat2 small{font-size:12px;opacity:.85}.tat2 .pos{color:#9EE6B3}.tat2 .neg{color:#FFB4A8}.tat2 .muted{color:inherit}
.tapw{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:14px}.tapw>div,.taio>div{border:1px solid var(--rule);border-radius:4px;padding:9px 12px;background:var(--paper)}
.tapw span,.taio span{display:block;font:600 12px var(--body);color:var(--mute)}.tapw b{font:800 22px var(--disp)}
.tacard h4{margin:6px 0 6px;font:800 18px var(--disp)}.tapos tr.chg td{background:#FBF1D6}
.taio{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:12px}.taio b{display:block;font:800 22px var(--disp)}.taio small{color:var(--mute);font-size:12px}
.taoth .tat{display:inline-flex;align-items:center;gap:8px;white-space:nowrap}
.talh{display:flex;justify-content:space-between;padding:6px 12px;font:600 12px var(--body);color:var(--mute);border-bottom:1px solid var(--rule)}
.taoth tr.me td{background:#FBF1D6}.tahint{margin:18px 0}
@media(max-width:700px){.tapick,.tagrid{grid-template-columns:1fr!important}.tasel{min-width:0}.tasel select{width:100%;min-width:0}
.tapl .tv small{white-space:normal;display:block;max-width:92px}.tat2{padding:8px}.tat2 b{font-size:24px}.tapw b,.taio b{font-size:19px}
.taoth{min-width:0!important;font-size:13px}.taoth .tat{white-space:normal}.taoth .tat .lgs{display:none}.taoth td,.taoth th{padding:6px 5px}.tapos td,.tapos th{padding:7px 5px}}
"""

CSS += """
/* jersey badge on player pages */
.jers{position:relative;flex:none;width:clamp(96px,12vw,150px);height:clamp(96px,12vw,150px);align-self:center;margin:0;border-radius:20px;background:var(--jb);display:flex;align-items:center;justify-content:center;overflow:hidden;box-shadow:0 0 0 2px rgba(238,241,234,.22),0 10px 24px rgba(0,0,0,.28)}
.jers::before,.jers::after{content:"";position:absolute;left:0;right:0;background:var(--ja)}
.jers::before{bottom:12%;height:6%}.jers::after{bottom:4.5%;height:3%}
.jers b{position:relative;z-index:1;font:900 clamp(52px,8vw,102px)/1 var(--disp);color:var(--jn);-webkit-text-stroke:4px var(--jo);paint-order:stroke fill;letter-spacing:0;margin-top:2%}
.jers b.sm{font-size:clamp(36px,5.4vw,70px)}
.jers .nflj{position:absolute;z-index:2;left:50%;top:1.5%;transform:translateX(-50%);width:27%;height:27%;margin:0;background-size:contain;background-position:center top;background-repeat:no-repeat;filter:drop-shadow(0 0 1.2px var(--jn)) drop-shadow(0 2px 2px rgba(0,0,0,.55))}
.jers .nflh{width:66%;height:66%;position:relative;z-index:1;margin-top:-10%}
.hero{align-items:center}
.curt{display:inline-flex;align-items:center;gap:6px;vertical-align:middle}.lgc{width:22px;height:22px;border-radius:50%;background-size:cover;display:inline-block}
@media(max-width:600px){.hero{align-items:center}.jers{align-self:center;width:88px;height:88px;margin:0;border-radius:16px}.jers b{font-size:56px;-webkit-text-stroke:3px var(--jo)}.jers b.sm{font-size:38px}}
"""

CSS += """
/* desktop nav: wrap to a second row instead of hiding tabs off the edge */
@media(min-width:701px){.menu{flex-wrap:wrap;gap:0 20px;padding:6px 0}.menu a{padding:8px 0 6px}}
@media(min-width:1121px){.menu{gap:0 18px}.top .wrap{gap:24px}}
@media(min-width:761px) and (max-width:940px){.menu{gap:0 14px;flex-wrap:nowrap!important}.menu a{font-size:14px}.top .wrap{gap:18px}}
@media(min-width:761px) and (max-width:1120px){.tbtn span{display:none}.tbtn{padding:8px}.top .wrap{gap:18px}.menu{gap:0 15px}.menu a{font-size:14.5px}.mark{font-size:24px}}
"""

CSS += """
/* transactions */
.txmore{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:16px 0 8px;padding:14px 0;border-top:1px solid var(--rule)}.txmore span{color:var(--mute);font-size:13px;margin-right:auto}.txmore button{font:700 14px var(--body);padding:9px 16px;border-radius:999px;border:1px solid var(--turf);background:#fff;color:var(--turf);cursor:pointer}.txmore .txmb,.txmore .pmb{background:var(--turf);color:#fff}
.txbar{display:flex;flex-wrap:wrap;align-items:center;gap:10px 14px;margin:22px 0 18px}.txf{margin:0}.txq{flex:1 1 220px;min-width:0;max-width:360px;font:500 15px var(--body);padding:9px 12px;border:1px solid #C9D1DE;border-radius:999px;background:#fff;color:var(--ink)}.txq:focus{outline:2px solid var(--flag);outline-offset:1px}.txwt{flex-wrap:wrap}
.txbar select{font:600 15px var(--body);padding:8px 10px;border:1px solid var(--rule);border-radius:6px;background:var(--paper);color:var(--ink)}
.txl{font:600 14px var(--body);color:var(--mute);display:flex;align-items:center;gap:6px}
.txw{margin:26px 0 8px;font:800 22px var(--disp);color:var(--turf);border-bottom:2px solid var(--ink);padding-bottom:4px}
.txc{background:var(--paper);border:1px solid var(--rule);border-left:4px solid var(--rule);border-radius:4px;margin:0 0 10px;padding:10px 14px}
.txc.trade{border-left-color:var(--flag)}.txc.waiver{border-left-color:var(--turf)}.txc.fa{border-left-color:#3A6EA5}.txc.lost{opacity:.6;border-left-color:var(--loss)}
.txc header{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:6px}
.txk{font:700 11px var(--body);letter-spacing:.02em;padding:3px 8px;border-radius:3px;background:var(--turf);color:var(--chalk)}
.txc.trade .txk{background:var(--flag);color:var(--turf)}.txc.fa .txk{background:#3A6EA5}.txc.lost .txk{background:var(--loss)}
.txh{display:flex;align-items:center;gap:8px;font-size:15px}.txh small{color:var(--mute)}.txh a{color:var(--ink);text-decoration:none}
.txc time{margin-left:auto;font-size:12px;color:var(--mute);white-space:nowrap}
.txc ul{list-style:none;margin:0;padding:0}
.txp{display:grid;grid-template-columns:18px 38px minmax(0,1fr) auto;align-items:center;gap:8px;padding:6px 0;border-top:1px solid #EEF1F6}
.txp .sg{font:900 18px var(--disp);text-align:center}.txp.add .sg{color:var(--win)}.txp.drp .sg{color:var(--loss)}
.txp .ps{font:800 12px var(--disp);text-align:center;background:#EEF1F6;border-radius:3px;padding:2px 0}
.txp .nm small{margin-left:6px;color:var(--mute);font-size:12px}.txp .sn{font-size:12px;color:var(--mute);text-align:right}
.txsides{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:4px 18px}.txt{display:flex;align-items:center;gap:8px;margin:4px 0 2px;font-size:14px}.txt a{color:var(--ink)}
@media(max-width:600px){.txc time{margin-left:0;width:100%}.txp{grid-template-columns:16px 34px minmax(0,1fr)}.txp .sn{grid-column:3;text-align:left;margin-top:-4px}}
"""

def nfl_sched(s):
    """{team: {week: [opponent, home 1/0, team score, opp score, final 1/0]}} from the ESPN schedule and the play-by-play files."""
    import pbp as _pb
    D = getattr(s, "ddir", "data"); out = {}
    fin = {}
    try:
        for g in _pb.load(D).values():
            pl = [p for p in g.get("plays", []) if len(p) > 6]
            if pl: fin[(int(g["w"]), g["away"], g["home"])] = (int(pl[-1][5]), int(pl[-1][6]), bool(g.get("final")))
    except Exception: pass
    fp_ = os.path.join(D, "schedule.txt")
    if not os.path.exists(fp_): return out
    for ln in open(fp_):
        if ln.startswith("#") or not ln.strip(): continue
        r_ = ln.strip().split("|"); w, aw, hm = int(r_[0]), r_[2], r_[3]
        sc = fin.get((w, aw, hm)); done = "FINAL" in r_[4]
        for t, o, h in ((aw, hm, 0), (hm, aw, 1)):
            x = [o, h]
            if sc: x += ([sc[0], sc[1]] if h == 0 else [sc[1], sc[0]]) + [1 if (done or sc[2]) else 0]
            out.setdefault(t, {})[str(w)] = x
    return out


NAV = [("index.html", "Home", "home"), ("news.html", "News", "news"), ("standings.html", "Standings", "standings"), ("schedule.html", "Schedule", "schedule"), ("playoffs.html", "Playoffs", "playoffs"),
       ("teams.html", "Teams", "teams"), ("players.html", "Players", "players"),
       ("races.html", "Awards", "races"), ("records.html", "Records", "records"), ("h2h.html", "Head to head", "h2h"),
       ("transactions.html", "Transactions", "transactions"), ("trades.html", "Trades", "trades"), ("analyzer.html", "Analyzer", "analyzer"), ("draft.html", "Draft", "draft")]   # this week, then people, then honors, then the front office


PRIMARY = ("home", "standings", "schedule", "teams", "players", "records", "news", "transactions")
ICON_S = '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" fill="none" stroke="currentColor" stroke-width="2.2"/><path d="M15.5 15.5 21 21" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>'
ICON_M = '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>'


def page(title, body, pre="", active=None):
    links = [x for x in NAV if x[2] in PRIMARY or x[2] == active]
    nav = "".join(f'<a href="{pre}{u}"{" aria-current=page" if k == active else ""}>{t}</a>' for u, t, k in links)
    return (f'<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{E(title)}</title>{FONTS(pre)}<style>{CSS}</style></head><body>\n'
            f'<div class="top"><div class="wrap"><a class="mark" href="{pre}index.html"><i class="brandlogo" aria-hidden="true"></i>Super League</a><nav class="menu" aria-label="Site">{nav}</nav>'
            f'<div class="tact"><button type="button" class="tbtn tsrch" aria-label="Search">{ICON_S}<span>Search</span></button><button type="button" class="tbtn tmenu" aria-label="All pages">{ICON_M}<span>Menu</span></button></div></div></div>\n{body}\n</body></html>')


NFL_CITY = {"ARI": "Arizona", "ATL": "Atlanta", "BAL": "Baltimore", "BUF": "Buffalo", "CAR": "Carolina", "CHI": "Chicago", "CIN": "Cincinnati", "CLE": "Cleveland",
            "DAL": "Dallas", "DEN": "Denver", "DET": "Detroit", "GB": "Green Bay", "HOU": "Houston", "IND": "Indianapolis", "JAX": "Jacksonville", "KC": "Kansas City",
            "LV": "Las Vegas", "LAC": "Los Angeles", "LAR": "Los Angeles", "MIA": "Miami", "MIN": "Minnesota", "NE": "New England", "NO": "New Orleans", "NYG": "New York",
            "NYJ": "New York", "PHI": "Philadelphia", "PIT": "Pittsburgh", "SEA": "Seattle", "SF": "San Francisco", "TB": "Tampa Bay", "TEN": "Tennessee", "WAS": "Washington"}
NFL_NICK = {"ARI": "Cardinals", "ATL": "Falcons", "BAL": "Ravens", "BUF": "Bills", "CAR": "Panthers", "CHI": "Bears", "CIN": "Bengals", "CLE": "Browns",
            "DAL": "Cowboys", "DEN": "Broncos", "DET": "Lions", "GB": "Packers", "HOU": "Texans", "IND": "Colts", "JAX": "Jaguars", "KC": "Chiefs",
            "LV": "Raiders", "LAC": "Chargers", "LAR": "Rams", "MIA": "Dolphins", "MIN": "Vikings", "NE": "Patriots", "NO": "Saints", "NYG": "Giants",
            "NYJ": "Jets", "PHI": "Eagles", "PIT": "Steelers", "SEA": "Seahawks", "SF": "49ers", "TB": "Buccaneers", "TEN": "Titans", "WAS": "Commanders"}


INJ_SHORT = {"Questionable": "Q", "Doubtful": "D", "Out": "O", "IR": "IR", "PUP": "PUP", "Sus": "SUS", "DNR": "DNR", "NA": "NA", "COV": "COV"}
def stg(kind, txt): return f'<span class="stg {kind}">{E(txt)}</span>'
def inj_tag(inj): return stg("inj", INJ_SHORT.get(inj, inj)) if inj else ""


def stamp():
    from zoneinfo import ZoneInfo
    t = datetime.datetime.now(ZoneInfo("America/New_York"))
    return "Updated " + t.strftime("%b %-d, %-I:%M %p")


from pbp import WP_SD_SCALE as _WPSD

class Site:
    def __init__(s_, s, T, TEAM, SIM, weeks_left, starts_pm, season_pm, logo_dir, proj):
        _nm = s.nm
        s.nm = lambda i: (f"{NFL_NICK[i]} DEF" if i in NFL_NICK else f"{i} DEF") if not i.isdigit() else re.sub(r" III$", "", _nm(i))   # "Kenneth Walker III" -> "Kenneth Walker"   # "MIN DEF" -> "Vikings DEF"
        s_.s = s; s_.T = T; s_.TEAM = TEAM; s_.SIM = SIM; s_.weeks_left = weeks_left; s_.starts_pm = starts_pm; s_.season_pm = season_pm; s_.proj = proj; s_.logo_dir = logo_dir
        from superleague import prov_median as _pm_; s_.prov_median = _pm_
        # Trades list players by what they've meant to the team that got them: WAR in its lineup since the trade, then season WAR
        # (the Trades page rule, used on every page)
        def _imp(w0, r, i):
            Rv = (s.repl or {}).get("val") if getattr(s, "repl", None) else None
            if Rv is None: return (0.0, 0.0)
            war = sum((p - Rv.get(s.pos(i), 0)) * s.wpp for w in s.weeks if w >= w0 for j, p in s.W[w][r]["S"] if j == i)
            tot = sum((p - Rv.get(s.pos(i), 0)) * s.wpp for w in s.weeks for rr in s.R for j, p in s.W[w][rr]["S"] if j == i)
            return (war, tot)
        s_.trade_imp = _imp
        for t_ in s.tx:
            if t_.get("type") == "trade" and t_.get("adds"):
                t_["adds"] = sorted(t_["adds"], key=lambda x: _imp(t_.get("w", 0), x[1], x[0]) if isinstance(x, (list, tuple)) and len(x) > 1 else (0, 0), reverse=True)
        for t_ in getattr(s, "trade_res", []) or []:
            sides_ = t_.get("sides", [])
            for x in sides_:
                if isinstance(x.get("got"), list): x["got"] = sorted(x["got"], key=lambda i: _imp(t_["w"], x["r"], i), reverse=True)
                if isinstance(x.get("gave"), list):
                    rcv = {i: y["r"] for y in sides_ for i in y.get("got", [])}
                    x["gave"] = sorted(x["gave"], key=lambda i: _imp(t_["w"], rcv.get(i, x["r"]), i), reverse=True)
        for t_ in getattr(s, "trades", []) or []:
            sd_ = t_.get("sides")
            if isinstance(sd_, dict): t_["sides"] = {r_: (sorted(pair[0], key=lambda i: _imp(t_["w"], r_, i), reverse=True), sorted(pair[1], key=lambda i: _imp(t_["w"], r_, i)[1], reverse=True)) for r_, pair in sd_.items()}
        sc_f = os.path.join(os.path.dirname(logo_dir), "scoring.txt")
        s_.SC = {k: float(v) for k, v in (l.strip().split("|") for l in open(sc_f) if "|" in l and not l.startswith("#"))} if os.path.exists(sc_f) else {}
        s_.M = s.M; s_.yr = s.L["season"]; s_.f = T["line_factor"]; s_.n = len(s.weeks)
        s_.W0, s_.PF, s_.PA = s.record()
        opp = len(s.R) - 1
        s_.ap = {r: sum(sum(s.G[w]["scores"][r] > s.G[w]["scores"][o] for o in s.R if o != r) for w in s.weeks) for r in s.R}
        s_.xw = {r: s_.ap[r] / opp for r in s.R}
        s_.stand = sorted(s.R, key=lambda r: (-s_.W0[r], -s_.PF[r]))
        s_.has_logo = {r: os.path.exists(f"{logo_dir}/{s.M[r]}.png") for r in s.R}
        s_.lev = {(x["w"], x["r"]): x for x in SIM[3]}
        s_.power = {x["r"]: (k, x) for k, x in enumerate(s.power, 1)}
        s_.bym = {v: r for r, v in s.M.items()}
        # every game this season: (w, a, b, done)
        s_.games = [(w, a, b, True) for w in s.weeks for a, b in s.G[w]["pairs"]]
        s_.games += [(w, a, b, False) for w in weeks_left for a, b in s.fut.get(w, [])]
        s_.game_of = {(w, r): (a, b) for w, a, b, _ in s_.games for r in (a, b)}

    # ---- draft value: each pick vs what that slot is expected to produce
    def draft_vals(s_):
        """Redraft grades, no slot curve.
        val  = fantasy points above replacement, only from weeks the player was in a Super League starting lineup (any team).
        redraft = rank of every drafted player by val (ties take the lower spot). spots = pick - redraft (positive = outplayed his pick).
        Pick grade (gap) = val minus the average val of the players ranked around that pick (5 either side) in the redraft.
        Team grade = sum of its pick grades. own = val only while starting for the team that drafted him (GM of the Year uses it vs league average)."""
        if hasattr(s_, "_dvals"): return s_._dvals
        s = s_.s; R = s.repl["val"]; wpp = s.wpp
        val = Counter(); own = Counter(); gs = Counter()
        for w in s.weeks:
            for x, d in s.W[w].items():
                for i, p in d["S"]:
                    if i == "0" or s.pos(i) not in R: continue
                    v = p - R.at(w, s.pos(i)); val[i] += v * wpp; gs[i] += 1
                    if s.dby.get(i) == x: own[i] += v
        if s_.wk_live(s.nxt):              # this week's starts count once their game is final
            for x in s.R:
                for i, p in s_.live_final(x):
                    if i == "0" or s.pos(i) not in R: continue
                    v = p - R.at(s.nxt, s.pos(i)); val[i] += v * wpp; gs[i] += 1
                    if s.dby.get(i) == x: own[i] += v
        picks = sorted(s.draft, key=lambda d: d["pick"]); T = len(s.R); NP_ = len(picks)
        # redraft pool = every drafted player + every player who started for anyone (waiver/free-agent pickups included)
        pool = set(d["id"] for d in picks) | set(val)
        order = sorted(pool, key=lambda i: -round(val[i], 6))
        rank_of = {}
        for k, i in enumerate(order, 1): rank_of[round(val[i], 6)] = k          # ties end up on the lowest (last) spot
        s_._pool = [(rank_of[round(val[i], 6)], i, val[i], gs[i]) for i in order]
        # the bar for pick p = average production of the players ranked around p in the redraft (p-5 .. p+5)
        sv = [val[i] for i in order]; K = 5
        bar_at = lambda p: max(0.0, float(np.mean(sv[max(0, p - 1 - K):min(len(sv), p + K)])))   # never below 0: the floor is a pick who never starts
        rows = []
        for d in picks:
            i = d["id"]; rr = rank_of[round(val[i], 6)]
            rows.append(dict(pick=d["pick"], rd=(d["pick"] - 1) // T + 1, slot=(d["pick"] - 1) % T + 1, r=d["r"], i=i, val=val[i], gs=gs[i], own=own[i],
                             redraft=rr, rrd=(rr - 1) // T + 1, rslot=(rr - 1) % T + 1, undrafted=rr > NP_, spots=d["pick"] - rr,
                             slotval=bar_at(d["pick"]), gap=round(val[i] - bar_at(d["pick"]), 2) + 0.0))
        team = Counter(); team_own = Counter(); s_._dtotal = Counter()
        for x in rows: team[x["r"]] += x["gap"]; team_own[x["r"]] += x["own"]; s_._dtotal[x["r"]] += x["val"]
        mt = sum(team.values()) / len(s.R)
        team = Counter({r: round(team[r] - mt, 2) + 0.0 for r in s.R})     # vs the league's average draft (waiver gems raise every bar equally)
        avg_own = sum(team_own.values()) / len(s.R)
        gm_draft = {r: (team_own[r] - avg_own) * s.wpp for r in s.R}     # wins vs the league-average draft, for GM of the Year
        s_._dvals = (rows, team, gm_draft); return s_._dvals

    # ---- vetoes: a commissioner move that exactly reverses a trade
    def veto_tx(s_):
        s = s_.s; out = set()
        for t in s.tx:
            if t["type"] != "commissioner": continue
            ca = {(i, r) for i, r in t["adds"]}; cd = {(i, r) for i, r in t["drops"]}
            for tr in s.tx:
                if tr["type"] == "trade" and tr["status"] == "complete" and ca == {(i, r) for i, r in tr["drops"]} and cd == {(i, r) for i, r in tr["adds"]}:
                    out.add(id(t))
        return out

    # ---- roster moves (pickups that paid off, drops that hurt)
    def slot_gain(s_, w, r, i, p):
        """Points team r would have added in week w by starting i (p pts) in place of the right starter, lineup rearranged; 0 if no gain or no slot."""
        s = s_.s; d = s.W[w][r]
        st_ = [(si, s.pos(si), sp) for si, sp in d["S"] if si != "0" and si != i]
        act_ = sum(sp for _, _, sp in st_)
        pools = [st_[:k] + st_[k + 1:] + [(i, s.pos(i), p)] for k in range(len(st_))] + ([st_ + [(i, s.pos(i), p)]] if len(st_) < len(s.slots) else [])
        opts = [v for v, ch in (s.best(x) for x in pools) if i in set(ch)]
        return max(0.0, max(opts) - act_) if opts else 0.0
    def flip(s_, w, r, gain):
        """Wins that gain would have added: a loss turned into a win counts 1, into a tie 0.5; a tie turned into a win 0.5."""
        s = s_.s; g = s_.game_of.get((w, r))
        if not g or gain <= 0 or w not in s.G: return 0.0
        o = g[1] if g[0] == r else g[0]; me = s.G[w]["scores"][r]; op = s.G[w]["scores"][o]
        if me > op: return 0.0
        new = me + gain
        if me == op: return 0.5
        return 1.0 if new > op + 1e-9 else (0.5 if abs(new - op) < 1e-9 else 0.0)
    def bench_by_player(s_):
        """Benchwarmer counts the player, not the stint: every team he sat on the bench for, added up."""
        bc_, _ = s_.cost_rows(); out = {}
        for (i, r), x in bc_.items():
            o = out.setdefault(i, dict(pts=0.0, by=Counter())); o["pts"] += x["pts"]; o["by"][r] += x["pts"]
        return out
    def cost_rows(s_):
        """Benchwarmer and Worst Drop on one scale: what the player would have added to that team's actual lineup, week by week."""
        if getattr(s_, "_cr_k", None) == tuple(s_.s.weeks): return s_._cr
        s = s_.s
        bench = defaultdict(lambda: dict(pts=0.0, wins=0.0, wk=0, fl=[]))
        for w in s.weeks:
            for r, d in s.W[w].items():
                ir = s_.ir_set(r, w, [i for i, _ in d["B"]])
                for i, p in d["B"]:
                    if i == "0" or i in ir: continue
                    g = s_.slot_gain(w, r, i, p)
                    if g <= 0: continue
                    x = bench[(i, r)]; f = s_.flip(w, r, g); x["pts"] += g; x["wk"] += 1; x["wins"] += f
                    if f: x["fl"].append(w)
        _, dv = s_.moves(); drops = {}
        for dd in dv:
            x = dict(pts=0.0, wins=0.0, wk=0, fl=[], d=dd)
            ws = [w for w in s.weeks if w >= dd["w"]]
            started_then = dd["w"] in s.W and any(j == dd["i"] for j, _ in s.W[dd["w"]].get(dd["r"], {}).get("S", []))
            for w in ws:
                if w == dd["w"] and started_then: continue
                if dd.get("back") and w >= dd["back"]: break
                p = s.NP.get(w, {}).get(dd["i"])
                if p is None or dd["r"] not in s.W.get(w, {}): continue
                g = s_.slot_gain(w, dd["r"], dd["i"], p)
                if g <= 0: continue
                f = s_.flip(w, dd["r"], g); x["pts"] += g; x["wk"] += 1; x["wins"] += f
                if f: x["fl"].append(w)
            drops[(dd["w"], dd["r"], dd["i"])] = x
        s_._cr = (bench, drops); s_._cr_k = tuple(s.weeks); return s_._cr
    def moves(s_):
        if getattr(s_, "_mv_k", None) == tuple(s_.s.weeks): return s_._mv
        s = s_.s; R = s.repl["val"]; wpp = s.wpp
        how = {}; drops = []
        for t in sorted(s.tx, key=lambda t: t["w"]):
            if t["status"] != "complete": continue
            for i, r in t["adds"]: how[(i, r)] = (t["w"], t["type"])
            if t["type"] in ("waiver", "free_agent"):
                for i, r in t["drops"]: drops.append((t["w"], r, i, t["type"]))
        pick = defaultdict(lambda: [0.0, 0, 0.0])      # (r, i) -> [WAR, starts, pts]
        for w in s.weeks:
            for r, d in s.W[w].items():
                for i, p in d["S"]:
                    if i == "0": continue
                    src = how.get((i, r))
                    if src and src[0] <= w and src[1] in ("waiver", "free_agent"):
                        x = pick[(r, i)]; x[0] += (p - R.at(w, s.pos(i))) * wpp; x[1] += 1; x[2] += p
        readd = defaultdict(list)
        for t in s.tx:
            if t["status"] == "complete":
                for i, r in t["adds"]: readd[(i, r)].append(t["w"])
        dv = []
        for tw, r, i, typ in drops:
            if s.pos(i) not in R: continue
            started_then = any(j == i for j, _ in s.W.get(tw, {}).get(r, {}).get("S", [])) if tw in s.W else False
            back = [w for w in readd[(i, r)] if w > tw]
            wks = [w for w in s.weeks if w >= tw + (1 if started_then else 0) and (not back or w < min(back))]
            v = sum((s.NP.get(w, {}).get(i, 0.0) - R.at(w, s.pos(i))) * wpp for w in wks if i in s.NP.get(w, {}))
            pts = sum(s.NP.get(w, {}).get(i, 0.0) for w in wks); g = sum(1 for w in wks if i in s.NP.get(w, {}))
            dv.append(dict(w=tw, r=r, i=i, war=v, pts=pts, g=g, back=min(back) if back else None))
        s_._mv = (pick, dv); s_._mv_k = tuple(s.weeks); return s_._mv

    # ---- naming + links
    def pn(s_, i):
        """Player label with position first: 'WR Malik Nabers' (team defenses already read 'SEA DEF')."""
        s = s_.s
        return s.nm(i) if (not i.isdigit() or s.pos(i) == "DEF") else f"{s_.posd(i)} {s.nm(i)}"

    def TN(s_, r, w=None):
        """Team name. With a week (or inside a page for a past week/story), the name it had then; otherwise today's.
        No team name set: the Sleeper username (HC13, JesseMej...)."""
        cur = s_.s.L["rosters"][r]["team"] or s_.s.L["rosters"][r]["user"]
        at = s_.wk_start(w) if w is not None else getattr(s_, "_at", None)
        if at is None: return cur
        for ts, rr, old_, new_ in reversed(s_.name_hist()):
            if rr == r and at < ts: cur = old_ or s_.s.L["rosters"][r]["user"]
        return cur
    def name_hist(s_):
        """[(utc, roster, old name, new name)] from data/team_names.txt, oldest first."""
        if not hasattr(s_, "_nh"):
            s_._nh = []; f = os.path.join(os.path.dirname(s_.logo_dir), "team_names.txt")
            if os.path.exists(f):
                for l in open(f):
                    if l.startswith("#") or not l.strip(): continue
                    ts, rr, o, n = l.rstrip("\n").split("|")[:4]
                    s_._nh.append((datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%MZ"), int(rr), o, n))
            s_._nh.sort()
        return s_._nh
    def logo_hist(s_):
        """[(utc, roster, css class)] logos used before utc, from data/logo_history.txt (utc|roster|file in data/logos_old)."""
        if not hasattr(s_, "_lh"):
            s_._lh = []; f = os.path.join(os.path.dirname(s_.logo_dir), "logo_history.txt")
            if os.path.exists(f):
                for l in open(f):
                    if l.startswith("#") or not l.strip(): continue
                    ts, rr, fn = l.rstrip("\n").split("|")[:3]
                    s_._lh.append((datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%MZ"), int(rr), "L" + rr + "_" + os.path.splitext(fn)[0].replace(".", "_")))
            s_._lh.sort()
        return s_._lh
    def logo_cls(s_, r, w=None):
        at = s_.wk_start(w) if w is not None else getattr(s_, "_at", None); c = f"L{r}"
        if at is not None:
            for ts, rr, cl in reversed(s_.logo_hist()):
                if rr == r and at < ts: c = cl
        return c
    def wk_start(s_, w):
        """First kickoff of week w (UTC). A rename before it shows on that week's games."""
        if not hasattr(s_, "_wks"):
            s_._wks = {}; f = os.path.join(os.path.dirname(s_.logo_dir), "schedule.txt")
            if os.path.exists(f):
                for l in open(f):
                    if l.startswith("#") or not l.strip(): continue
                    ww, ts = l.split("|")[:2]; d = datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%MZ")
                    if int(ww) not in s_._wks or d < s_._wks[int(ww)]: s_._wks[int(ww)] = d
        return s_._wks.get(int(w), datetime.datetime.max)
    def names_js(s_):
        """For the browser: {roster: [[week a name/logo started, name, logo class], ...]} only for teams that changed."""
        out = {}
        for r in s_.s.R:
            ch = sorted({ts for ts, rr, *_ in s_.name_hist() if rr == r} | {ts for ts, rr, _ in s_.logo_hist() if rr == r})
            if not ch: continue
            ws = sorted(s_.s.weeks + [s_.s.nxt]) if hasattr(s_.s, "nxt") else sorted(s_.s.weeks)
            seg = []; prev = None
            for w in range(1, max(ws + [18]) + 1):
                v = (s_.TN(r, w), s_.logo_cls(r, w))
                if v != prev: seg.append([w, v[0], v[1]]); prev = v
            out[r] = seg
        return out
    def turl(s_, r, pre, all_time=False):
        """A team link: this season's page by default, the manager's all-time page with all_time=True."""
        return f"{pre}team/{s_.M[r]}.html" + ("" if all_time else f"#{s_.yr}")
    def gurl(s_, w, a, b, pre):
        a, b = sorted((a, b)); return f"{pre}game/w{w}-{a}-{b}.html"
    def gurl_r(s_, w, r, pre):
        g = s_.game_of.get((w, r)); return s_.gurl(w, g[0], g[1], pre) if g else None
    def logo(s_, r, pre, cls="lg", w=None):
        return f'<i class="im {cls} {s_.logo_cls(r, w)}" role="img" aria-label="{E(s_.TN(r, w))} logo"></i>'
    def tl(s_, r, pre): return f'<a class="tl" href="{s_.turl(r, pre)}">{s_.logo(r, pre)}<span><b>{E(s_.TN(r))}</b><small>{E(s_.M[r])}</small></span></a>'
    def posd(s_, i, sep="/"):
        """Position for display; two-way players show both (WR/DB, or 'WR, DB' on a profile)."""
        pa_ = sorted(s_.s.PL.get(i, {}).get("pall") or [], key=lambda x: (x != s_.s.pos(i), x))       # his fantasy position first: WR, DB
        return sep.join(pa_) if len(pa_) > 1 else s_.s.pos(i)
    def pa(s_, i, label=None):
        """Player name as a link to his page (works from any page depth)."""
        return f'<a class="pn" href="player/{i}.html">{E(label if label is not None else s_.pn(i))}</a>'
    def nl(s_, ab):
        """NFL team abbreviation as a link to its page."""
        return f'<a class="pn nfll" href="nfl/{ab}.html"><i class="nfl N{ab}" aria-hidden="true"></i>{E(ab)}</a>' if ab and ab in NFL_NICK else E(ab or "FA")
    def nl_r(s_, ab):
        """Mirror of nl for the right-hand side: abbreviation, then logo on the outside."""
        return f'<a class="pn nfll" href="nfl/{ab}.html">{E(ab)}<i class="nfl nflr N{ab}" aria-hidden="true"></i></a>' if ab and ab in NFL_NICK else E(ab or "FA")
    def team_at(s_, w, i):
        """The player's NFL team in week w: from that week's snap counts, else the nearest week we know, else today's team."""
        if not i.isdigit(): return i
        TW = getattr(s_.s, "TW", {})
        if w is not None:
            if (w, i) in TW: return TW[(w, i)]
            if w > s_.s.last: return s_.s.PL.get(i, {}).get("team") or "FA"      # newer than any snap data: today's team is the best guess (catches trades)
            for d in range(1, 19):
                if (w - d, i) in TW: return TW[(w - d, i)]
                if (w + d, i) in TW and (w + d) in s_.s.G: return TW[(w + d, i)]
        return s_.s.PL.get(i, {}).get("team") or "FA"
    def kick_str(s_, w, t):
        """Kickoff for team t in week w, short: SUN 1PM, THU 8:15PM."""
        if not hasattr(s_, "_kick"):
            from zoneinfo import ZoneInfo
            ET = ZoneInfo("America/New_York"); s_._kick = {}
            for w_, games in getattr(s_.s, "sched", {}).items():
                for k, aw, hm, st, *nt in games:
                    dt = datetime.datetime.strptime(k, "%Y-%m-%dT%H:%MZ").replace(tzinfo=datetime.timezone.utc).astimezone(ET)
                    txt = dt.strftime("%a ").upper() + (dt.strftime("%-I%p") if dt.minute == 0 else dt.strftime("%-I:%M%p"))
                    neu = bool(nt and nt[0])
                    s_._kick[(w_, aw)] = f"{txt} {'vs' if neu else '@'} {hm}"; s_._kick[(w_, hm)] = f"{txt} vs {aw}"
        return s_._kick.get((w, t), "")
    def plink(s_, i, pre, label=None):
        return f'<a class="pn" href="{pre}player/{i}.html">{E(label if label is not None else s_.pn(i))}</a>'

    def tn(s_, r, pre): return f'<a class="tn" href="{s_.turl(r, pre)}">{E(s_.TN(r))}</a>'
    def who(s_, r): return f"{s_.M[r]} ({s_.TN(r)}, {s_.yr})"     # records: manager first, team + year at the time
    def rec_str(s_, r, upto=None):
        """Record now, or going into a game (upto = the week before it)."""
        if upto is not None and upto < 1: return "0-0"
        return s_.s.rec(r, upto)
    def sigm(s_):
        """Spread of a game's margin this season: how far one player's PAA can move a win."""
        if not hasattr(s_, "_sigm"):
            s = s_.s; mg = [s.G[w]["scores"][a] - s.G[w]["scores"][b] for w in s.weeks for a, b in s.G[w]["pairs"]]
            s_._sigm = math.sqrt(sum(v * v for v in mg) / max(1, len(mg))) or 30.0
        return s_._sigm
    def wi(s_, pm):
        """Win Impact of one start: the win chance his PAA alone gives an otherwise average lineup, minus 50%."""
        return float(norm.cdf(pm / s_.sigm())) - 0.5
    def xrec(s_, r): return f"{s_.xw[r]:.1f}-{s_.n - s_.xw[r]:.1f}"

    # ---- projections
    def pregame(s_, w, r):
        """Completed week: what the starters were projected (Sleeper, league scoring) before kickoff."""
        s = s_.s; T = s_.T
        if w not in s.SP: return None
        st = [i for i, _ in s.W[w][r]["S"] if i != "0"]
        mus = [s.SP[w].get(i, 0.0) for i in st]
        sd = math.sqrt(sum((T["cv"].get(s.pos(i), 0.6) * m) ** 2 for i, m in zip(st, mus))) * T["corr"]
        return sum(mus), sd
    def upcoming(s_, w, r):
        t = s_.TEAM[(w, r)]; return t["mu"] * s_.f, t["sd"] * s_.f
    def live_of(s_, w, r):
        t = s_.TEAM.get((w, r)); return t.get("live") if t else None
    def live_final(s_, r):
        """This week's starters for team r whose NFL game is final: those starts are locked, so they count right away."""
        if not s_.wk_live(s_.s.nxt): return []
        lv = s_.live_of(s_.s.nxt, r)
        if not lv: return []
        return [(i, p) for i, p in lv["played"].items() if i in lv["starters"] and i not in lv.get("inprog", ())]
    def locked_now(s_, r):
        """Team r's players whose NFL game this week has kicked off: Sleeper locks them in place, so this week counts for them now.
        IR players stay counted even if dropped after the lock."""
        s = s_.s; LV = getattr(s, "LIVE", None) or {}
        if LV.get("week") != s.nxt: return []
        kicked = set(LV.get("done") or ()) | set(LV.get("prog") or {})
        tm = lambda i: s_.team_at(s.nxt, i) if i.isdigit() else i
        out = [i for i in s.rost.get(r, []) if tm(i) in kicked or ("TEAM_" + str(tm(i))) in kicked]
        out += [i for i in (LV.get("reserve_live") or {}).get(s.nxt, {}).get(r, set()) if i not in out]
        return out
    def wk_live(s_, w):
        """Game mode: some NFL game in week w has finished, so every matchup that week shows actual score big, projection small."""
        return bool((getattr(s_.s, "LIVE", None) or {}).get("done")) and any((s_.TEAM.get((w, r)) or {}).get("live") for r in s_.s.R)
    def now_pts(s_, w, r):
        lv = s_.live_of(w, r); return lv["locked"] if lv else 0.0

    def win_p(s_, a_mu_sd, b_mu_sd):
        (ma, sa), (mb, sb) = a_mu_sd, b_mu_sd
        if not math.hypot(sa, sb): return 1.0 if ma > mb else (0.0 if mb > ma else 0.5)     # nothing left to play: decided
        return ncdf((ma - mb) / math.hypot(sa, sb))

    # ---- shared bits
    def rope(s_, a, b, pa, label="to win"):
        return (f'<div class="tug{" favb" if pa < 0.5 else ""}"><div class="rope"><i class="ra" style="--p:{pa * 100:.1f}%"></i><i class="rb"></i></div>'
                f'<div class="pc"><b class="pa"><i class="im rl ra_ L{a}" aria-hidden="true"></i>{pct(pa)}</b><span>{label}</span><b class="pb">{pct(1 - pa)}<i class="im rl rb_ L{b}" aria-hidden="true"></i></b></div></div>')

    def faceoff(s_, w, a, b, pre):
        """Home hero row: upcoming game on the field."""
        A, B = s_.upcoming(w, a), s_.upcoming(w, b); pa = s_.win_p(A, B)
        live = s_.wk_live(w)
        def side(r, mu, cls):
            big = fp(s_.now_pts(w, r)) if live else f"{mu:.1f}"
            pj = f'<span class="fproj">Proj {mu:.1f}</span>' if live else ""
            return (f'<div class="ft {cls}">{s_.logo(r, pre, "")}<span class="who"><span class="fn">{E(s_.TN(r))}</span>'
                    f'<span class="fm">{E(s_.M[r])}, {s_.rec_str(r)}</span></span><span class="fp">{big}{pj}</span></div>')
        return (f'<a class="fo" href="{s_.gurl(w, a, b, pre)}" aria-label="{E(s_.TN(a))} vs {E(s_.TN(b))}, preview">{side(a, A[0], "a")}'
                f'<span class="fmid">{s_.rope(a, b, pa, "to win")}</span>'
                f'{side(b, B[0], "b")}{s_.sline(w, a, b).replace("class=\"sline\"", "class=\"sline fsl\"")}</a>')

    matchup_card = faceoff

    def mini_game(s_, w, a, b, done, pre):
        s = s_.s
        if done:
            sa, sb = s.G[w]["scores"][a], s.G[w]["scores"][b]
            row = lambda r, sc, won: f'<div class="row {"w" if won else "l"}">{s_.logo(r, pre, "lgs", w)}<span class="t">{E(s_.TN(r, w))}</span><span class="s">{fp(sc)}</span></div>'
            return f'<a class="gm" href="{s_.gurl(w, a, b, pre)}">{row(a, sa, sa > sb)}{row(b, sb, sb > sa)}<div class="foot">Final</div></a>'
        A, B = s_.upcoming(w, a), s_.upcoming(w, b); pa = s_.win_p(A, B)
        row = lambda r, mu, p: f'<div class="row">{s_.logo(r, pre, "lgs")}<span class="t">{E(s_.TN(r))}</span><span class="s">{pct(p)}</span></div>'
        if s_.wk_live(w):
            row = lambda r, p: f'<div class="row">{s_.logo(r, pre, "lgs")}<span class="t">{E(s_.TN(r))}</span><span class="s">{fp(s_.now_pts(w, r))}</span></div>'
            return f'<a class="gm" href="{s_.gurl(w, a, b, pre)}">{row(a, pa)}{row(b, 1 - pa)}<div class="foot">Live. Proj {A[0]:.1f} to {B[0]:.1f}</div></a>'
        return f'<a class="gm fut" href="{s_.gurl(w, a, b, pre)}">{row(a, A[0], pa)}{row(b, B[0], 1 - pa)}<div class="foot">Projected {A[0]:.1f} to {B[0]:.1f}</div></a>'

    def footer(s_, pre):
        return f'<footer><div class="wrap">Super League {s_.yr}. {stamp()}</div></footer>'

    def team_nav(s_, pre, cur=None):
        return '<nav class="subnav" aria-label="Teams"><div class="wrap">' + "".join(
            f'<a href="{s_.turl(x, pre)}"{" aria-current=page" if x == cur else ""}>{E(s_.M[x])}</a>' for x in s_.s.R) + "</div></nav>"

    def head(s_, title, lede):
        return f'<section class="field pagehead"><div class="wrap"><h1>{title}</h1></div></section>'

    def season_awards(s_, pre=""):
        """Every season award is regular season only."""
        s = s_.s; all_wk = s.weeks; RS = s.L.get("regular_season_weeks", 14)
        s.weeks = [w for w in all_wk if w <= RS]
        try: return s_._season_awards(pre)
        finally: s.weeks = all_wk
    def _season_awards(s_, pre=""):
        s = s_.s; nm = s_.pn; ppw = s.ppw; R = s.repl["val"]; wpp = s.wpp
        def block(title, what, rows, fmt, unit, sub_fn, link_fn):
            li = "".join(f'<li class="{"lead" if j == 1 else ""}"><span class="rk">{j}</span>{sub_fn(k)[0]}<a href="{link_fn(k)}"><b>{sub_fn(k)[1]}</b><br><small>{sub_fn(k)[2]}</small></a><span class="v">{fmt(v)}</span></li>' for j, (k, v) in enumerate(rows, 1))
            return f'<div class="aw"><h2>{title}</h2><p class="what">{what}</p><ol>{li}</ol></div>'
        team_sub = lambda r: (s_.logo(r, pre, "lg"), E(s_.TN(r)), E(s_.M[r]))
        team_link = lambda r: s_.turl(r, pre)
        moy = sorted(((r, v) for r, v in s_.lineup_added().items()), key=lambda x: -x[1])
        b1 = block("Manager of the Year race", "Wins added by going against the projections when setting a lineup.",
                   moy, lambda v: f"{v:+.2f}", "wins added", team_sub, team_link) if moy else ""
        trade = Counter()
        for t in s.trade_res:
            for x in t["sides"]: trade[x["r"]] += x["pts_rs"] / ppw
        # pickups: every waiver and free-agent move, graded like trades (best lineup with it minus without it, regular season)
        MV_ = getattr(s, "mval", {}) or {}; pick = Counter(); best_pick = {}
        for x in s.tx:
            if x["status"] == "complete" and x["type"] in ("waiver", "free_agent") and id(x) in MV_:
                for r, v in MV_[id(x)].items(): pick[r] += v[1] / ppw
        drows, dteam, dteam_own = s_.draft_vals()   # dteam_own = draft wins vs league-average draft
        gm = sorted(((r, trade[r] + pick[r] + dteam_own[r]) for r in s.R), key=lambda x: -x[1])
        def gm_sub(r):
            bp = best_pick.get(r); top = bp.most_common(1)[0] if bp else None
            return (s_.logo(r, pre, "lg"), E(s_.TN(r)), f'Draft {dteam_own[r]:+.1f}, trades {trade[r]:+.1f}, pickups {pick[r]:+.1f}')
        b2 = block("GM of the Year race", "Wins added by the draft, trades and pickups.",
                   gm, lambda v: f"{v:+.1f}", "wins added", gm_sub, team_link)
        heists = []
        for t in s.trade_res:
            sd = sorted(t["sides"], key=lambda x: -x["pts_rs"])
            heists.append(((t, sd[0], sd[-1]), (sd[0]["pts_rs"] - sd[-1]["pts_rs"]) / ppw))
        heists.sort(key=lambda x: -x[1])
        def h_sub(k):
            t, wn, ls = k
            return (s_.logo(wn["r"], pre, "lg", t["w"]), f'{E(s_.TN(wn["r"], t["w"]))} over {E(s_.TN(ls["r"], t["w"]))}',
                    f'Week {t["w"]}: got {", ".join(s_.pa(i, nm(i)) for i in wn["got"])} for {", ".join(s_.pa(i, nm(i)) for i in wn["gave"])}')
        def h_li(j, k, v):
            t, wn, ls = k
            tm = lambda r: f'<a class="ht" href="{s_.turl(r, pre)}">{s_.logo(r, pre, "lg")}<b>{E(s_.TN(r))}</b></a>'
            got = lambda x: ", ".join(s_.pa(i, nm(i)) for i in x["got"]) or "nothing"
            return (f'<li class="hst{" lead" if j == 1 else ""}"><span class="rk">{j}</span><div class="hb">'
                    f'<div class="hm">{tm(wn["r"])}<span class="ov">over</span>{tm(ls["r"])}<span class="hw">Week {t["w"]}</span></div>'
                    f'<div class="hg"><span class="hl pos">{E(s_.M[wn["r"]])} got</span><span>{got(wn)}</span>'
                    f'<span class="hl neg">{E(s_.M[ls["r"]])} got</span><span>{got(ls)}</span></div></div>'
                    f'<span class="v">{v:.1f}<small>wins</small></span></li>')
        b3 = (f'<div class="aw"><h2>Heist of the Year race</h2><p class="what">The win gap between the two sides of a trade.</p>'
              f'<ol>{"".join(h_li(j, k, v) for j, (k, v) in enumerate(heists[:5], 1))}</ol></div>') if heists else ""
        left = Counter()
        for w in s.weeks:
            for r, d in s.W[w].items():
                opt, _ = s.best([(i, s.pos(i), p) for i, p in d["S"] + d["B"] if i != "0"]); left[r] += opt - s.G[w]["scores"][r]
        bw = sorted(left.items(), key=lambda x: -x[1])
        bench_c, drop_c = s_.cost_rows()
        bbp_ = s_.bench_by_player()
        bwl = sorted(((k, x["pts"] * wpp) for k, x in bbp_.items()), key=lambda kv: -kv[1])[:10]
        def bw_sub(i):
            rs = [r for r, _ in bbp_[i]["by"].most_common()]
            return (s_.logo(rs[0], pre, "lg"), E(nm(i)), f"{len(rs)} teams" if len(rs) > 2 else E(" / ".join(s_.TN(r) for r in rs)))
        b4 = block("Benchwarmer of the Year race", "Wins a bench player would have added to the teams he sat on.",
                   bwl, lambda v: f"{v:+.2f}", "wins", bw_sub, lambda i: f"player/{i}.html") if bwl else ""
        PARTS_ = [z for z in (getattr(s, "mparts", []) or []) if z[0]["w"] <= s.L.get("regular_season_weeks", 14)]
        wd = sorted((((z[0]["w"], z[1], z[2]), -z[5] / ppw) for z in PARTS_ if z[3] == "-" and z[5] < -0.05), key=lambda kv: -kv[1])[:10]
        def d_sub(k):
            return (s_.logo(k[1], pre, "lg"), f'{E(s_.TN(k[1]))} cut {E(nm(k[2]))}', f'Cut in Week {k[0]}')
        b5 = block("Worst Drop of the Year race", "Wins the team lost by cutting him: its best lineup with the cut minus without it, every week until he came back.",
                   wd, lambda v: f"{-v:+.2f}", "wins", d_sub, lambda k: f"player/{k[2]}.html") if wd else ""
        pu = sorted((((z[0]["w"], z[1], z[2]), z[5] / ppw) for z in PARTS_ if z[3] == "+" and z[5] > 0.05), key=lambda kv: -kv[1])[:10]
        def p_sub(k):
            return (s_.logo(k[1], pre, "lg"), f'{E(s_.TN(k[1]))} added {E(nm(k[2]))}', f'Picked up in Week {k[0]}')
        b5p = block("Pickup of the Year race", "Wins a pickup added: the team's best lineup with him minus with a replacement-level free agent instead, every week until he was let go.",
                    pu, lambda v: f"{v:+.2f}", "wins", p_sub, lambda k: f"player/{k[2]}.html") if pu else ""
        # Sixth Man: most PAA from a player who started half his rostered weeks or fewer
        sE, sN, sA, sR = Counter(), Counter(), Counter(), {}
        for w in s.weeks:
            if w > s.L.get("regular_season_weeks", 14): continue
            med = s.pos_median(w)
            for r, d in s.W[w].items():
                for i, p in d["S"]:
                    if i != "0": sE[i] += p - med[s.pos(i)]; sN[i] += 1
                for i, _ in d["S"] + d["B"]:
                    if i != "0": sA[i] += 1; sR.setdefault(i, Counter())[r] += 1
        six = sorted(((i, v) for i, v in sE.items() if sN[i] and sN[i] * 2 <= sA[i] and v > 0), key=lambda kv: -kv[1])[:10]
        b6 = block("Sixth Man of the Year race", "Most PAA from a player who started half his rostered weeks or fewer.",
                   six, lambda v: f"{v:+.1f}", "PAA", lambda i: (s_.logo(sR[i].most_common(1)[0][0], pre, "lg"), E(nm(i)), f"Started {sN[i]} of {sA[i]}, " + (f"{len(sR[i])} teams" if len(sR[i]) > 2 else E(" / ".join(s_.TN(r) for r, _ in sR[i].most_common())))),
                   lambda i: f"player/{i}.html") if six else ""
        s_._bench_block = b4 + b6
        dmap2 = {x["pick"]: x for x in drows}
        T_ = len(s.R)
        def pk_sub(k):
            x = dmap2[k]
            return (s_.logo(x["r"], pre, "lg"), E(nm(x["i"])), f'Taken {x["rd"]}.{x["slot"]:02d}, now {s_.now_str(x)}. {E(s_.TN(x["r"]))}')
        steal = sorted(((x["pick"], x["gap"]) for x in drows), key=lambda kv: -kv[1])[:10]
        bust = sorted(((x["pick"], x["gap"]) for x in drows), key=lambda kv: kv[1])[:10]
        b6 = block("Best Draft race", "Each team's pick grades added up, compared with the league's average draft.",
                   sorted(dteam.items(), key=lambda kv: -kv[1]), lambda v: f"{v:+.2f}", "draft grade", team_sub, lambda r: "draft.html")
        b7 = block("Steal of the Draft race", "WAR above what his draft spot should produce.", steal, lambda v: f"{v:+.2f}", "pick grade", pk_sub, lambda k: f"player/{dmap2[k]['i']}.html")
        b8 = block("Bust of the Draft race", "WAR below what his draft spot should produce.", bust, lambda v: f"{v:+.2f}", "pick grade", pk_sub, lambda k: f"player/{dmap2[k]['i']}.html")
        imp = sorted((x for x in s_.improbable() if x["w"] in s.weeks), key=lambda x: x["low"])[:10]
        def im_sub(k):
            x = imp[k]
            return (s_.logo(x["wi"], pre, "lg", x["w"]), f'{E(s_.TN(x["wi"], x["w"]))} over {E(s_.TN(x["lo"], x["w"]))}', f'Week {x["w"]}: down to {pct(x["low"])} {"before kickoff" if x["at"] == "Pregame" else ("at " + x["at"][1:].replace("Live, ", "")) if x["at"].startswith("@") else "after " + ("the " + x["at"] + " games" if ":" in x["at"] else x["at"])}{f", trailed by as much as {x['down']:.1f}" if x["down"] > 0.05 else ""}, won {fp(s.G[x["w"]]["scores"][x["wi"]])} to {fp(s.G[x["w"]]["scores"][x["lo"]])}')
        b9 = block("Comeback of the Year race", "The lowest win chance a winner came back from.",
                   [(k, imp[k]["low"]) for k in range(len(imp))], pct, "lowest win chance", im_sub, lambda k: s_.gurl(imp[k]["w"], imp[k]["wi"], imp[k]["lo"], pre)) if imp else ""
        exl = sorted(((g, s_.excitement(*g)) for g in [(w_, x, y) for w_ in s.weeks for x, y in s.G[w_]["pairs"]] if s_.excitement(*g) is not None), key=lambda kv: -kv[1])[:10]
        def ex_sub(g):
            w_, x, y = g; wi = x if s.G[w_]["scores"][x] > s.G[w_]["scores"][y] else y; lo = y if wi == x else x
            return (s_.logo(wi, pre, "lg", w_), f'{E(s_.TN(wi, w_))} over {E(s_.TN(lo, w_))}', f'Week {w_}, {fp(s.G[w_]["scores"][wi])} to {fp(s.G[w_]["scores"][lo])}')
        b10 = block("Game of the Year race", "The most exciting games, by excitement score.", exl, lambda v: f"{v:.1f}", "excitement", ex_sub, lambda g: s_.gurl(g[0], g[1], g[2], pre)) if exl else ""
        grp = lambda h, *bs: f'<section><h3 class="wsub">{h}</h3><div class="awards4">{"".join(bs)}</div></section>' if any(bs) else ""
        return grp("Managers", b1, b2) + grp("Moves", b3, b5p, b5, b7, b8) + grp("Games", b10, b9)


    def luck_chart(s_, rows, label):
        """rows: list of (week, won(bool), xwin_frac). Cumulative wins vs xWins by games played."""
        n = len(rows); W = [0]; X = [0.0]
        for row in rows: W.append(W[-1] + row[1]); X.append(X[-1] + row[2])
        top = max(max(W), max(X), 1); top = math.ceil(top + 0.5)
        Wd, Hd, L_, R_, T_, B_ = 680, 320, 50, 96, 18, 48
        px = lambda g: L_ + g * (Wd - L_ - R_) / max(n, 1)
        py = lambda v: T_ + (Hd - T_ - B_) * (1 - v / top)
        g = ""
        for v in range(0, top + 1):
            g += f'<line x1="{L_}" x2="{Wd - R_}" y1="{py(v):.1f}" y2="{py(v):.1f}" stroke="var(--rule)" stroke-width="1"/><text x="{L_ - 10}" y="{py(v) + 4:.1f}" text-anchor="end" font-size="16" fill="var(--mute)">{v}</text>'
        for k in range(0, n + 1):
            g += f'<text x="{px(k):.1f}" y="{Hd - B_ + 20}" text-anchor="middle" font-size="16" fill="var(--mute)">{k}</text>'
        g += f'<text x="{(L_ + Wd - R_) / 2:.0f}" y="{Hd - 4}" text-anchor="middle" font-size="16" fill="var(--mute)">Games played</text>'
        g += f'<text x="12" y="{(T_ + Hd - B_) / 2:.0f}" text-anchor="middle" font-size="16" fill="var(--mute)" transform="rotate(-90 12 {(T_ + Hd - B_) / 2:.0f})">Wins</text>'
        # shade the gap: green where actual is ahead (lucky), red where behind (unlucky)
        for k in range(n):
            a0, a1, x0, x1 = W[k], W[k + 1], X[k], X[k + 1]
            ahead = (a0 + a1) / 2 >= (x0 + x1) / 2
            g += (f'<polygon points="{px(k):.1f},{py(a0):.1f} {px(k + 1):.1f},{py(a1):.1f} {px(k + 1):.1f},{py(x1):.1f} {px(k):.1f},{py(x0):.1f}" '
                  f'fill="{"var(--win)" if ahead else "var(--loss)"}" opacity=".13"/>')
        line = lambda arr, col, w: f'<polyline points="{" ".join(f"{px(k):.1f},{py(v):.1f}" for k, v in enumerate(arr))}" fill="none" stroke="{col}" stroke-width="{w}" stroke-linejoin="round" stroke-linecap="round"/>'
        g += line(X, "#C9A21A", 3) + line(W, "var(--turf)", 3.5)
        hz = ""
        for k in range(1, n + 1):
            wk, won, xf = rows[k - 1][:3]; ex_ = rows[k - 1][3] if len(rows[k - 1]) > 3 else None
            if ex_:
                card = (f'<b>Game {k}, Week {wk}</b><span>vs {E(ex_["op"])}</span>'
                        f'<span class="res {"pos" if won else "neg"}">{"W" if won else "L"} {ex_["me"]:.1f} to {ex_["th"]:.1f}</span>'
                        f'<span>Outscored {ex_["ap"]} of {ex_["n"]} teams = <b>{xf:.2f} xWins</b></span>')
                half = (Wd - L_ - R_) / max(n, 1) / 2
                hz += (f'<rect class="hz" x="{px(k) - half:.1f}" y="{T_}" width="{2 * half:.1f}" height="{Hd - T_ - B_}" fill="transparent" '
                       f'data-x="{px(k) / Wd * 100:.2f}" data-card="{E(card)}" tabindex="0"/>')
            g += (f'<circle cx="{px(k):.1f}" cy="{py(X[k]):.1f}" r="4" fill="var(--paper)" stroke="#C9A21A" stroke-width="2.5"><title>After game {k} (Week {wk}): {X[k]:.1f} xWins</title></circle>'
                  f'<circle cx="{px(k):.1f}" cy="{py(W[k]):.1f}" r="4.5" fill="var(--turf)"><title>After game {k} (Week {wk}): {W[k]} wins</title></circle>')
        ex, ew = py(X[-1]), py(W[-1])
        if abs(ex - ew) < 16: ex, ew = (ex - 9, ew + 9) if X[-1] > W[-1] else (ex + 9, ew - 9)
        g += f'<text x="{px(n) + 10:.1f}" y="{ew + 4:.1f}" font-size="17" font-weight="700" fill="var(--turf)">Wins {W[-1]}</text>'
        g += f'<text x="{px(n) + 10:.1f}" y="{ex + 4:.1f}" font-size="17" font-weight="700" fill="#A8860F">xWins {X[-1]:.1f}</text>'
        g += f'<line class="guide" x1="0" x2="0" y1="{T_}" y2="{Hd - B_}" stroke="var(--ink)" stroke-width="1" stroke-dasharray="3 3" opacity="0"/>' + hz
        return f'<div class="panel lchart"><svg viewBox="0 0 {Wd} {Hd}" width="100%" role="img" aria-label="{E(label)}">{g}</svg><div class="lcard" hidden></div><p class="note" style="margin:4px 0 0">Hover or tap a game for details.</p></div>'

    # ------------------------------------------------------------------ news
    KIND = {"cover": "Cover story", "recap": "Recap", "feature": "Feature", "preview": "Preview"}
    def news_list(s_):
        order = {"cover": 0, "recap": 1, "feature": 2, "preview": 3}
        # newest first, by publish time; stories published together keep cover, recap, feature, preview order
        return sorted(getattr(s_.s, "NEWS", []), key=lambda n: (n.get("date", "") or f"{n['week']:02d}", n["week"], -order.get(n.get("kind"), 9)), reverse=True)
    def nurl(s_, n, pre):
        if n.get("kind") not in ("feature", "cover") and n.get("game"):
            w, a, b = (int(x) for x in n["game"].split("-")); return s_.gurl(w, a, b, pre)
        return f"{pre}news/{n['slug']}.html"
    def ndate(s_, n):
        v = n.get("date", "")
        try:
            if len(v) > 10: return datetime.datetime.strptime(v, "%Y-%m-%d %H:%M").strftime("%b %-d, %Y, %-I:%M %p ET")
            return datetime.date.fromisoformat(v).strftime("%b %-d, %Y")
        except ValueError: return ""
    def md(s_, body, pre):
        """Story markdown: ## headings, - lists, **bold**, {p:ID} {t:R} {m:R} links."""
        import re as _re
        s = s_.s
        def inline(t):
            t = E(t)
            t = _re.sub(r"\{p:([\w]+)(?:\|([^}]*))?\}", lambda m: f'<a class="pn" href="{pre}player/{m.group(1)}.html">{m.group(2) or E(s.nm(m.group(1)))}</a>', t)
            t = _re.sub(r"\{t:(\d+)\}", lambda m: f'<a class="pn" href="{s_.turl(int(m.group(1)), pre)}"><b>{E(s_.TN(int(m.group(1))))}</b></a>', t)
            t = _re.sub(r"\{m:(\d+)\}", lambda m: f'<a class="pn" href="{s_.turl(int(m.group(1)), pre)}">{E(s_.M[int(m.group(1))])}</a>', t)
            return _re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
        out = []
        for blk in [b.strip() for b in body.split("\n\n") if b.strip()]:
            lines = blk.splitlines()
            if lines[0].startswith("## "): out.append(f"<h2>{inline(lines[0][3:])}</h2>"); lines = lines[1:]
            if not lines: continue
            if len(lines) >= 2 and all(l.startswith("|") for l in lines):          # a markdown table
                rows = [[c.strip() for c in l.strip().strip("|").split("|")] for l in lines if not _re.fullmatch(r"\|?[\s:|-]+\|?", l.strip())]
                num = lambda c: bool(_re.fullmatch(r"[<>+\-]?[\d.,]+%?", c))
                out.append('<div class="scroll"><table class="grid stbl"><thead><tr>' + "".join(f'<th{" class=r" if k else ""}>{inline(c)}</th>' for k, c in enumerate(rows[0])) + "</tr></thead><tbody>"
                           + "".join("<tr>" + "".join(f'<td{" class=r" if k else " class=rl"}>{inline(c)}</td>' for k, c in enumerate(r)) + "</tr>" for r in rows[1:]) + "</tbody></table></div>")
            elif all(l.startswith("- ") for l in lines): out.append("<ul>" + "".join(f"<li>{inline(l[2:])}</li>" for l in lines) + "</ul>")
            else: out.append(f"<p>{inline(' '.join(lines))}</p>")
        return "".join(out)
    def ncard(s_, n, pre, big=False):
        lg = "".join(s_.logo(r, pre, "lgs") for r in n["teams"][:2])
        return (f'<a class="ncard{" lead" if big else ""}" href="{s_.nurl(n, pre)}"><span class="kick">{s_.KIND.get(n.get("kind"), "Story")}, Week {n["week"]}</span>'
                f'<b>{E(n["title"])}</b><span class="dek">{E(n.get("dek", ""))}</span><span class="nlg">{lg}</span></a>')
    def issue_numbers(s_, w, pre):
        s = s_.s
        if w not in s.G: return ""
        sc = s.G[w]["scores"]; hi = max(sc, key=sc.get); lo = min(sc, key=sc.get)
        gm = [(abs(sc[a] - sc[b]), a, b) for a, b in s.G[w]["pairs"]]; close = min(gm)
        ups = []
        for a, b in s.G[w]["pairs"]:
            A, B = s_.pregame(w, a), s_.pregame(w, b)
            if A and B:
                pa = s_.win_p(A, B); wi = a if sc[a] > sc[b] else b; pw = pa if wi == a else 1 - pa
                ups.append((pw, wi, b if wi == a else a))
        left = {}
        for r in s.R:
            d = s.W[w][r]; o_, _ = s.best([(i, s.pos(i), p) for i, p in d["S"] + d["B"] if i != "0"]); left[r] = o_ - sc[r]
        perfect = [r for r in s.R if left[r] < 0.005]; most = max(left, key=left.get)
        aw = [a for a in getattr(s, "awards", []) if a["w"] == w]
        cells = [("High score", fp(sc[hi]), f"{s_.M[hi]} ({s_.TN(hi)})", s_.gurl_r(w, hi, pre)), ("Low score", fp(sc[lo]), f"{s_.M[lo]} ({s_.TN(lo)})", s_.gurl_r(w, lo, pre))]
        if aw: mi, mr, mp, mpm, _ = aw[0]["mvp"]; cells.append(("Week MVP", fp(mp), f"{s_.pn(mi)}, {s_.M[mr]}", s_.gurl_r(w, mr, pre)))
        if ups: u = min(ups); cells.append(("Biggest upset", pct(u[0]), f"{s_.M[u[1]]} over {s_.M[u[2]]}", s_.gurl(w, u[1], u[2], pre)))
        cells.append(("Closest game", fp(close[0]), f"{s_.M[close[1]]} and {s_.M[close[2]]}", s_.gurl(w, close[1], close[2], pre)))
        cells.append(("Most left on the bench", fp(left[most]), f"{s_.M[most]} ({s_.TN(most)})", s_.gurl_r(w, most, pre)))
        if perfect: cells.append(("Perfect lineups", str(len(perfect)), ("teams" if len(perfect) > 2 else " / ".join(s_.M[r] for r in perfect)), ""))
        return '<div class="recs">' + "".join(f'<a class="rec" href="{u or "#"}"><span class="k">{k}</span><span class="v">{E(v)}</span><span class="w">{E(x)}</span></a>' for k, v, x, u in cells) + "</div>"
    def story_for(s_, w, a, b):
        """The game's story: its recap once final, otherwise its preview."""
        key = (w, min(a, b), max(a, b)); want = "recap" if w in s_.s.G else "preview"
        for n in s_.news_list():
            if n.get("game") and n.get("kind") == want:
                gw, ga, gb = (int(x) for x in n["game"].split("-"))
                if (gw, min(ga, gb), max(ga, gb)) == key: return n
        return None
    def sline(s_, w, a, b):
        n = s_.story_for(w, a, b)
        return f'<span class="sline"><i>{s_.KIND[n["kind"]]}</i>{E(n["title"])}</span>' if n else ""
    def story_block(s_, w, a, b, pre, part="all"):
        """part: 'main' = the recap/preview itself (top of the page), 'more' = the other stories about this game (bottom)."""
        n = s_.story_for(w, a, b)
        more = s_.story_list(s_.stories_for(game=f"{w}-{min(a, b)}-{max(a, b)}", skip=(n["slug"],) if n else ()) + s_.stories_for(game=f"{w}-{max(a, b)}-{min(a, b)}", skip=(n["slug"],) if n else ()), pre, "More on this game")
        if part == "more": return more
        if not n: return "" if part == "main" else more
        return ("" if part == "main" else more) + (f'<section><details class="sblock"><summary><span class="kick">{s_.KIND[n["kind"]]}</span><b>{E(n["title"])}</b>'
                f'<span class="dek">{E(n.get("dek", ""))}</span><span class="by">Super League Desk, {s_.ndate(n)}</span><span class="more"><span class="o">Read the full {n["kind"]}</span><span class="c">Close</span></span></summary>'
                f'<article class="story">{s_.md(n["body"], pre)}</article></details></section>')
    def gut_row(s_, w, a, b):
        """One line: how many gut calls each side made (started someone the projections wouldn't have) and the wins they added."""
        s_.lineup_added()
        la, lb = s_._law.get((w, a)), s_._law.get((w, b)); na, nb = s_._lawn.get((w, a), 0), s_._lawn.get((w, b), 0)
        if la is None or lb is None: return ""
        if na == 0 and nb == 0: return '<div class="a">0</div><div class="k">Gut calls</div><div class="b">0</div>'
        cell = lambda n, v, side: (f'<div class="{side} gut">{n}' + (f'<small class="{"pos" if v > 0.005 else "neg" if v < -0.005 else "muted"}">({v:+.2f})</small>' if n else "") + '</div>')
        return cell(na, la, "a") + '<div class="k">Gut calls (wins added)</div>' + cell(nb, lb, "b")
    def lineup_added(s_):
        """Per team: actual points minus what the projections' best lineup (same players, same week) actually scored. Regular season."""
        if hasattr(s_, "_la"): return s_._la
        from superleague import make_mu
        s = s_.s; RS = s.L.get("regular_season_weeks", 14); out = {}; s_._law = {}; s_._lawn = {}
        for r in s.R:
            tot = 0.0
            for w in s.weeks:
                if w > RS or w not in s.SP: continue
                mu = make_mu(s, w, s_.T["wts"]); d = s.W[w][r]
                act = {i: p for i, p in d["S"] + d["B"] if i != "0"}
                _, pick = s.best([(i, s.pos(i), mu(i)) for i in act])
                g_ = (s.G[w]["scores"][r] - sum(act[i] for i in pick)) / s.ppw; tot += g_; s_._law[(w, r)] = g_
                s_._lawn[(w, r)] = len({i for i, _ in d["S"] if i != "0"} - set(pick))
            out[r] = tot
        s_._la = out; return out
    def features(s_): return [n for n in s_.news_list() if n.get("kind") in ("feature", "cover")]
    def ntags(s_, n):
        """What a story is filed under: its teams/managers, every player it mentions, and its game."""
        import re as _re
        b = n.get("body", "")
        tm = set(n.get("teams", [])) | {int(x) for x in _re.findall(r"\{[tm]:(\d+)\}", b)}
        pl = set(_re.findall(r"\{p:(\w+)", b)) | set(n.get("players", []))
        return tm, pl, n.get("game")
    def stories_for(s_, team=None, player=None, game=None, skip=()):
        out = []
        for n in s_.news_list():
            if n["slug"] in skip: continue
            tm, pl, g = s_.ntags(n)
            if (team is not None and team in tm) or (player is not None and player in pl) or (game is not None and g == game): out.append(n)
        return sorted(out, key=lambda n: (n.get("date", ""), n["week"]), reverse=True)
    def story_list(s_, ns, pre, title="Stories"):
        if not ns: return ""
        return f'<section><h2>{title}</h2><div class="ngrid">{"".join(s_.ncard(n, pre) for n in ns)}</div></section>'
    def week_extras(s_, w, pre):
        """Under a finished week on the schedule: numbers of the week and that week's features."""
        fs = [n for n in s_.features() if n["week"] == w]
        out = ""
        if fs: out += f'<h3 class="wsub">Features</h3><div class="ngrid">{"".join(s_.ncard(n, pre) for n in fs)}</div>'
        if w in s_.s.G: out += f'<h3 class="wsub">Numbers of the week</h3>{s_.issue_numbers(w, pre)}'
        return out
    def news_pages(s_):
        s = s_.s; P = {}; NL = s_.news_list(); yr = s_.yr
        for n in s_.features():
            pre = "../"
            try: s_._at = datetime.datetime.strptime(str(n.get("date", ""))[:16], "%Y-%m-%d %H:%M") + datetime.timedelta(hours=5)   # ET story time to UTC
            except Exception: s_._at = s_.wk_start(n["week"])
            lg = "".join(s_.logo(r, pre, "lgb") for r in n["teams"][:2])
            more = [x for x in s_.features() if x is not n][:6]
            body = (f'<section class="field nhero"><div class="wrap"><a class="back" href="{pre}news.html">News</a>'
                    f'<div class="kick">{s_.KIND.get(n["kind"], "Feature")}, Week {n["week"]}</div><h1>{E(n["title"])}</h1><p class="lede">{E(n.get("dek", ""))}</p>'
                    f'<div class="byline">{lg}<span>Super League Desk, {s_.ndate(n)}</span></div></div></section>'
                    f'<main class="wrap"><article class="story">{s_.md(n["body"], pre)}</article>'
                    + (f'<section><h2>More features</h2><div class="ngrid">{"".join(s_.ncard(x, pre) for x in more)}</div></section>' if more else "")
                    + f'</main>{s_.footer(pre)}')
            P[f"news/{n['slug']}.html"] = page(f"{n['title']}, Super League", body, pre, "news")
            s_._at = None
        pre = ""
        feats = "".join(s_.ncard(n, pre) for n in s_.features())
        weeks = sorted({n["week"] for n in NL if n.get("game")}, reverse=True)
        def grow(n):
            gw, ga, gb = (int(x) for x in n["game"].split("-"))
            return (f'<a class="grow" href="{s_.gurl(gw, ga, gb, pre)}"><span class="kick">{s_.KIND[n["kind"]]}</span>{s_.logo(ga, pre, "lgs", gw)}{s_.logo(gb, pre, "lgs", gw)}'
                    f'<b>{E(n["title"])}</b></a>')
        games = '<div class="gweeks">' + "".join(f'<div><h3 class="wsub">Week {w}</h3><div class="glist">' + "".join(grow(n) for n in NL if n.get("game") and n["week"] == w) + "</div></div>" for w in weeks) + '</div>'
        P["news.html"] = page(f"News, Super League {yr}", s_.head("News", "") +
                              f'<main class="wrap">{f"<section><h2>Features</h2><div class=ngrid>{feats}</div></section>" if feats else ""}'
                              f'<section><h2>Game stories</h2>{games}</section></main>{s_.footer(pre)}', pre, "news")
        return P
    def front(s_):
        """Home headline: the newest feature if it is from the latest week, else the story of the most important game."""
        NL = s_.news_list(); s = s_.s
        if not NL: return ""
        fs = sorted([n for n in s_.features() if n["week"] >= s.last], key=lambda n: str(n.get("date", "")), reverse=True)   # the newest story leads; previews stay on game pages
        pins = [n for n in s_.features() if str(n.get("pin", "")).lower() in ("yes", "true", "1")]   # "pin: yes" keeps a story as the home cover
        if pins: fs = pins[:1] + [n for n in fs if n is not pins[0]]
        if fs:
            n = fs[0]; href = s_.nurl(n, ""); lg = "".join(s_.logo(r, "", "lgh") for r in n["teams"][:2]); kick = s_.KIND.get(n["kind"], "Feature")
        else:
            n = None
            for w in (s.last,):
                for a, b in s_.game_order(w, s.G[w]["pairs"]):
                    n = s_.story_for(w, a, b)
                    if n: break
                if n: break
            if not n: return ""
            gw, ga, gb = (int(x) for x in n["game"].split("-")); href = s_.gurl(gw, ga, gb, ""); lg = s_.logo(ga, "", "lgh") + s_.logo(gb, "", "lgh"); kick = s_.KIND[n["kind"]]
        return (f'<section class="front"><div class="wrap"><a class="fcover" href="{href}"><span class="flg">{lg}</span><span class="ftxt"><span class="kick">{kick}, Week {n["week"]}</span>'
                f'<b>{E(n["title"])}</b><span class="dek">{E(n.get("dek", ""))}</span></span></a></div></section>')

    # ------------------------------------------------------------------ records
    def records_data(s_):
        """Record book data. scope (L or roster id) -> period (season or 'all') -> key -> top 10 entries.
        Entry = [value text, holder roster, player id, other roster, week, year, link, extra]."""
        s = s_.s; yr = s_.yr; R = s.repl["val"]; wpp = s.wpp
        G_ = lambda w, a, b: f"game/w{w}-{min(a, b)}-{max(a, b)}.html"
        E_ = defaultdict(list)
        def add(k, v, t, r, rs, p="", o=0, w=0, u="", x="", only=None, nfl=None, tb=0.0):      # tb: order inside a tie, for show only (it stays a tie)
            # e[9]: the NFL team a player record belongs to (that week's team for one game; for a season or career, the team he did most of it with)
            if p and nfl is None: nfl = s_.team_at(w if w else None, p)
            E_[k].append(dict(v=v, tb=tb, e=[t, r, p, o, w, yr, u, x, round(v, 9), nfl or "", list(dict.fromkeys(rs))], rs=set(rs), y=yr, only=only))
        # ---- team: single game
        for w in s.weeks:
            g = s.G[w]; sc = g["scores"]
            for a, b in g["pairs"]:
                wi, lo = (a, b) if sc[a] > sc[b] else (b, a); m = sc[wi] - sc[lo]; u = G_(w, a, b); res = f"{fp(sc[wi])} to {fp(sc[lo])}"
                for r, o in ((a, b), (b, a)):
                    wl_ = f"{'won' if sc[r] > sc[o] else 'lost' if sc[r] < sc[o] else 'tied'} {fp(sc[r])} to {fp(sc[o])}"
                    add("g_high", sc[r], fp(sc[r]), r, [r], o=o, w=w, u=u, x=wl_)
                    add("g_low", -sc[r], fp(sc[r]), r, [r], o=o, w=w, u=u, x=wl_)
                    d = s.W[w][r]; opt, _ = s.best([(i, s.pos(i), p) for i, p in d["S"] + d["B"] if i != "0"])
                    add("g_bench", opt - sc[r], fp(opt - sc[r]), r, [r], o=o, w=w, u=u, x=f"{fp(sc[r])} of {fp(opt)} possible")
                add("g_blow", m, fp(m), wi, [wi, lo], o=lo, w=w, u=u, x=res)
                add("g_close", -m, fp(m), wi, [wi, lo], o=lo, w=w, u=u, x=res)
                add("g_comb", sc[a] + sc[b], fp(sc[a] + sc[b]), wi, [a, b], o=lo, w=w, u=u, x=res)
                add("g_hiloss", sc[lo], fp(sc[lo]), lo, [lo], o=wi, w=w, u=u, x=f"lost {fp(sc[lo])} to {fp(sc[wi])}")
                add("g_lowin", -sc[wi], fp(sc[wi]), wi, [wi], o=lo, w=w, u=u, x=f"won {res}")
                PA_, PB_ = s_.pregame(w, a), s_.pregame(w, b)
                if PA_ and PB_:
                    pa = s_.win_p(PA_, PB_); pw = pa if wi == a else 1 - pa
                    if pw < 0.5: add("g_upset", -pw, pct(pw), wi, [wi, lo], o=lo, w=w, u=u, x=f"won {res}")
        for w in s.weeks:
            for a, b in s.G[w]["pairs"]:
                ev = s_.excitement(w, a, b)
                if ev is None: continue
                sc_ = s.G[w]["scores"]; wi = a if sc_[a] > sc_[b] else b; lo = b if wi == a else a
                add("g_excite", ev, f"{ev:.1f}", wi, [wi, lo], o=lo, w=w, u=G_(w, wi, lo), x=f'{fp(sc_[wi])} to {fp(sc_[lo])}')
                add("g_dull", -ev, f"{ev:.1f}", wi, [wi, lo], o=lo, w=w, u=G_(w, wi, lo), x=f'{fp(sc_[wi])} to {fp(sc_[lo])}')
                fl_ = (getattr(s_, "_excp", {}).get((w, min(a, b), max(a, b))) or {}).get("leads", 0)
                if fl_: add("g_flips", fl_, str(fl_), wi, [wi, lo], o=lo, w=w, u=G_(w, wi, lo), x=f'{fp(sc_[wi])} to {fp(sc_[lo])}')
        for x in s_.improbable():
            sc_ = s.G[x["w"]]["scores"]
            add("g_improb", -x["low"], pct(x["low"]), x["wi"], [x["wi"]], o=x["lo"], w=x["w"], u=G_(x["w"], x["wi"], x["lo"]), x=(("at " + x["at"][1:].replace("Live, ", "") + ", ") if x["at"].startswith("@") else "") + f'won {fp(sc_[x["wi"]])} to {fp(sc_[x["lo"]])}')
            if x["down"] > 0.05: add("g_down", x["down"], fp(x["down"]), x["wi"], [x["wi"]], o=x["lo"], w=x["w"], u=G_(x["w"], x["wi"], x["lo"]), x=f'won {fp(sc_[x["wi"]])} to {fp(sc_[x["lo"]])}')
            add("g_choke", 1 - x["low"], pct(1 - x["low"]), x["lo"], [x["lo"]], o=x["wi"], w=x["w"], u=G_(x["w"], x["wi"], x["lo"]), x=f'lost {fp(sc_[x["lo"]])} to {fp(sc_[x["wi"]])}')   # the same games from the other side
            if x["down"] > 0.05: add("g_blown", x["down"], fp(x["down"]), x["lo"], [x["lo"]], o=x["wi"], w=x["w"], u=G_(x["w"], x["wi"], x["lo"]), x=f'lost {fp(sc_[x["lo"]])} to {fp(sc_[x["wi"]])}')
        # ---- team: season
        n = len(s.weeks)
        for r in s.R:
            res = []
            for w in s.weeks:
                a, b = s_.game_of[(w, r)]; o = b if r == a else a; res.append(s.G[w]["scores"][r] > s.G[w]["scores"][o])
            pa_ = sum(s.G[w]["scores"][(lambda g: g[0] if g[1] == r else g[1])(s_.game_of[(w, r)])] for w in s.weeks)
            lk = s_.W0[r] - s_.xw[r]; u = s_.turl(r, "") + f"#{yr}"; rec = s_.rec_str(r)
            add("s_wins", s_.W0[r], rec, r, [r], u=u)
            add("s_pct", s_.W0[r] / n, pct(s_.W0[r] / n), r, [r], u=u, x=rec)            # same record = a shared record
            add("s_pctlo", -s_.W0[r] / n, pct(s_.W0[r] / n), r, [r], u=u, x=rec)
            add("s_pf", s_.PF[r], fp(s_.PF[r]), r, [r], u=u, x=f"{s_.PF[r] / n:.1f} a week")
            add("s_pflow", -s_.PF[r], fp(s_.PF[r]), r, [r], u=u, x=f"{s_.PF[r] / n:.1f} a week")
            add("s_pa", pa_, fp(pa_), r, [r], u=u, x=f"{pa_ / n:.1f} a week")
            add("s_xw", s_.xw[r], f"{s_.xw[r]:.1f}", r, [r], u=u, x=rec)
            add("s_lucky", lk, f"{lk:+.1f}", r, [r], u=u, x=f"{rec}, {s_.xw[r]:.1f} xWins")
            add("s_unlucky", -lk, f"{lk:+.1f}", r, [r], u=u, x=f"{rec}, {s_.xw[r]:.1f} xWins")
            for key, want in (("s_wstreak", True), ("s_lstreak", False)):
                best = c = 0; end = 0
                for k_, x in enumerate(res):
                    c = c + 1 if x == want else 0
                    if c > best: best, end = c, k_
                if best: add(key, best, str(best), r, [r], u=u, x=f"Weeks {s.weeks[end - best + 1]}-{s.weeks[end]}" if best > 1 else f"Week {s.weeks[end]}")
        # ---- players
        med = {w: s.pos_median(w) for w in s.weeks}
        # season and career totals: league-wide = the player's whole season (every team he started for);
        # one manager's view = only what he did for that team
        top = defaultdict(Counter)                     # weeks as the #1 starter at his position
        for w in s.weeks:
            best = {}
            for r, d in s.W[w].items():
                for i, p in d["S"]:
                    if i != "0" and p > best.get(s.pos(i), (-1e9, []))[0]: best[s.pos(i)] = (p, [(i, r)])
                    elif i != "0" and p == best.get(s.pos(i), (-1e9, []))[0]: best[s.pos(i)][1].append((i, r))
            for _, (p, who_) in best.items():
                for i, r in who_: top[i][r] += 1
        if yr == s_.yr:                                   # single plays: what each play did to the win chance (WPA) and the title odds (CPA)
            for w, r, o, _u, when, clk, txt, who, wpa, cpa, *_x in s_.play_impacts():
                a_, b_ = s_.game_of[(w, r)]; pid = who[0][0]
                raw_ = _x[4] if len(_x) > 4 else txt
                tx_ = f"{clk}, {s_.play_simple(raw_)}"
                if any(s.pos(i) == "K" and v > 0 for i, v in who) and "extra point is GOOD" in raw_ and "field goal" not in raw_: tx_ += " + XP"
                if any(v > 0 for _, v in who): tx_ += "\n" + ", ".join(f"{s.nm(i)} {fp(v)}" for i, v in who if v > 0)   # always say whose play it was and what each scored
                tp_ = sum(v for _, v in who)                            # the team's single-play marks: everything the play scored for it
                if tp_ > 0: add("t_ppts", tp_, fp(tp_), r, [r], o=o, w=w, u=G_(w, a_, b_), x=tx_)
                if wpa > 0: add("t_wpa", wpa, f"{wpa * 100:+.1f}%", r, [r], o=o, w=w, u=G_(w, a_, b_), x=tx_)
                if cpa > 0: add("t_cpa", cpa, f"{cpa * 100:+.2f}%", r, [r], o=o, w=w, u=G_(w, a_, b_), x=tx_)
                for pid_, v_ in who:
                    if v_ > 0:
                        for P in ("ALL", s.pos(pid_)): add(f"p_ppts_{P}", v_, fp(v_), r, [r], p=pid_, o=o, w=w, u=G_(w, a_, b_), x=tx_)
                for P in ("ALL", s.pos(pid)):
                    if wpa > 0: add(f"p_wpa_{P}", wpa, f"{wpa * 100:+.1f}%", r, [r], p=pid, o=o, w=w, u=G_(w, a_, b_), x=tx_)
                    if cpa > 0: add(f"p_cpa_{P}", cpa, f"{cpa * 100:+.2f}%", r, [r], p=pid, o=o, w=w, u=G_(w, a_, b_), x=tx_)
        new = lambda: dict(pts=0.0, war=0.0, g=0, pm=0.0, wins=0, xw=0.0, ben=0.0, by=Counter(), nfl=Counter(), seq=[])
        agg_t = defaultdict(new); agg_p = defaultdict(new)
        if yr == s_.yr: s_.play_impacts()
        PC_ = getattr(s_, "_pcred", None) or {}; CL_ = getattr(s_, "_clutch", None) or {}
        for w in s.weeks:
            scw = s.G[w]["scores"]
            for r, d in s.W[w].items():
                a, b = s_.game_of[(w, r)]; o = b if r == a else a; won = s.G[w]["scores"][r] > s.G[w]["scores"][o]
                for i, p in d["S"]:
                    if i == "0": continue
                    ps = s.pos(i); pm = p - med[w][ps]; wv = (p - R.at(w, ps)) * wpp
                    for P in ("ALL", ps):
                        add(f"p_start_{P}", p, fp(p), r, [r], p=i, o=o, w=w, u=G_(w, a, b))
                        add(f"p_pm_{P}", pm, f"{pm:+.1f}", r, [r], p=i, o=o, w=w, u=G_(w, a, b), x=f"{fp(p)} pts")
                        add(f"p_war1_{P}", wv, f"{wv:+.2f}", r, [r], p=i, o=o, w=w, u=G_(w, a, b), x=f"{fp(p)} pts")
                        add(f"p_startlo_{P}", -p, fp(p), r, [r], p=i, o=o, w=w, u=G_(w, a, b))
                        add(f"p_pmlo_{P}", -pm, f"{pm:+.1f}", r, [r], p=i, o=o, w=w, u=G_(w, a, b), x=f"{fp(p)} pts")
                        add(f"p_war1lo_{P}", -wv, f"{wv:+.2f}", r, [r], p=i, o=o, w=w, u=G_(w, a, b), x=f"{fp(p)} pts")
                    cr_ = PC_.get((w, r, i)) if yr == s_.yr else None; cl_ = CL_.get((w, r, i)) if yr == s_.yr else None
                    for X in (agg_t[(i, r)], agg_p[i]):
                        if cr_: X["wpa"] = X.get("wpa", 0.0) + cr_[0]; X["cpa"] = X.get("cpa", 0.0) + cr_[1]
                        if cl_: X["cw"] = X.get("cw", 0.0) + cl_[0]; X["ce"] = X.get("ce", 0.0) + cl_[1]; X["hasp"] = X.get("hasp", 0) + 1
                        X["pts"] += p; X["war"] += wv; X["g"] += 1; X["pm"] += pm; X["wins"] += won; X["xw"] += 0.5 + s_.wi(pm); X["by"][r] += 1; X["nfl"][s_.team_at(w, i)] += max(p, 0) + 1e-3; X["seq"].append(s_.team_at(w, i))
                irs_ = set(getattr(s, "reserve_wk", {}).get(w, {}).get(r, []))
                for i, p in d["B"]:
                    if i == "0": continue
                    if i in irs_ and s_.dnp(w, i): continue          # on IR and didn't play: not a bench week at all
                    if p > 0:
                        for P in ("ALL", s.pos(i)): add(f"p_bench_{P}", p, fp(p), r, [r], p=i, o=o, w=w, u=G_(w, a, b))
                    for X in (agg_t[(i, r)], agg_p[i]):
                        X["ben"] += p; X["bn"] = X.get("bn", 0) + (0 if s_.team_at(w, i) in s.byes.get(w, []) else 1); X["by"][r] += 0
                        if s_.team_at(w, i) not in s.byes.get(w, []): X.setdefault("bseq", []).append(s_.team_at(w, i))      # bye weeks don't count as bench weeks
        # ---- the week in progress: anything that only needs a player's own finished game counts now
        LW = s.nxt; PMv = s_.prov_median(s)
        if s_.wk_live(LW):
            for r in s.R:
                lv = s_.live_of(LW, r)
                if not lv: continue
                a, b = s_.game_of.get((LW, r), (r, r)); o = b if r == a else a; u = G_(LW, a, b)
                for i in lv["starters"]:
                    if not i or i == "0" or i not in lv["played"]: continue
                    if i in lv.get("inprog", ()):            # game on now: the start and his points so far count toward totals; single-game marks wait
                        for X in (agg_t[(i, r)], agg_p[i]):
                            X["pts"] += lv["played"][i]; X["g"] += 1; X["gl"] = X.get("gl", 0) + 1; X["by"][r] += 1
                        continue
                    p = lv["played"][i]; ps = s.pos(i); wv = (p - R.at(LW, ps)) * wpp; pm = p - PMv.get(ps, 0)
                    for P in ("ALL", ps):
                        add(f"p_start_{P}", p, fp(p), r, [r], p=i, o=o, w=LW, u=u)
                        add(f"p_pm_{P}", pm, f"{pm:+.1f}", r, [r], p=i, o=o, w=LW, u=u, x=f"{fp(p)} pts")
                        add(f"p_pmlo_{P}", -pm, f"{pm:+.1f}", r, [r], p=i, o=o, w=LW, u=u, x=f"{fp(p)} pts")
                        add(f"p_war1_{P}", wv, f"{wv:+.2f}", r, [r], p=i, o=o, w=LW, u=u, x=f"{fp(p)} pts")
                        add(f"p_startlo_{P}", -p, fp(p), r, [r], p=i, o=o, w=LW, u=u)
                        add(f"p_war1lo_{P}", -wv, f"{wv:+.2f}", r, [r], p=i, o=o, w=LW, u=u, x=f"{fp(p)} pts")
                    for X in (agg_t[(i, r)], agg_p[i]):
                        X["pts"] += p; X["war"] += wv; X["pm"] += pm; X["g"] += 1; X["gl"] = X.get("gl", 0) + 1; X["by"][r] += 1
                st_ = [i for i in lv["starters"] if i and i != "0"]
                if st_ and all(i in lv["played"] and i not in lv.get("inprog", ()) for i in st_):       # every starter has played: the team's score is final
                    tsc = sum(lv["played"][i] for i in st_)
                    add("g_high", tsc, fp(tsc), r, [r], o=o, w=LW, u=u)
                    add("g_low", -tsc, fp(tsc), r, [r], o=o, w=LW, u=u)
        def tot(i, r, rs, X, n1, only):
            u = f"player/{i}.html"; g_ = X["g"]; pts_ = X["pts"]; gw_ = g_ - X.get("gl", 0)     # W-L only from finished weeks
            for P in ("ALL", s.pos(i)):
                for pre_ in ("py", "pc"):       # season, career (the same while there is one season)
                    rs_st = [t_ for t_, c_ in X["by"].most_common() if c_ > 0] or [r]       # starting records: only the teams that started him
                    rs_bn = [t_ for t_, _ in X["by"].most_common()] or [r]                     # bench records: every team he sat on
                    if only == "T": rs_st = rs_bn = [r]
                    A = lambda k, v, t, x, tb=0.0, sq="seq": add(f"{pre_}_{k}_{P}", v, t, r, rs_bn if sq == "bseq" else rs_st, p=i, u=u, x=x, only=only, nfl=s_.nfl_seq(X, i, sq), tb=tb)
                    if g_:
                        gp = g_ * 1e-6          # ties on totals go to fewer games played; ties on rates go to more games played
                        A("pts", pts_ - gp, fp(pts_), f"{g_} starts"); A("pm", X["pm"] - gp, f"{X['pm']:+.1f}", f"{g_} starts"); A("war", X["war"] - gp, f"{X['war']:+.2f}", f"{g_} starts")
                        wl_ = f"{X['wins']}-{gw_ - X['wins']}"; wp_ = X["wins"] / gw_ if gw_ else 0.0; ls_ = gw_ - X["wins"]
                        A("wins", X["wins"] + wp_ * 1e-4, str(X["wins"]), wl_)                 # ties on wins: the better win % holds it
                        A("loss", ls_ + (1 - wp_) * 1e-4, str(ls_), wl_)                       # ties on losses: the worse win % holds it
                        A("gs", g_, str(g_), "", tb=pts_)                                      # a tie stays a tie; listed by points in those starts

                        if g_ >= 4:
                            A("ppg", pts_ / g_ + gp * 1e-2, fp(pts_ / g_), f"{g_} starts"); A("ppglo", -pts_ / g_ + gp * 1e-2, fp(pts_ / g_), f"{g_} starts")
                            A("ptslo", -pts_ + gp, fp(pts_), f"{g_} starts"); A("pmlo", -X["pm"] + gp, f"{X['pm']:+.1f}", f"{g_} starts"); A("warlo", -X["war"] + gp, f"{X['war']:+.2f}", f"{g_} starts")
                        if gw_:                         # no minimum: ties go to more starts
                            A("wpct", X["wins"] / gw_ + gw_ * 1e-6, pct(X["wins"] / gw_), f"{X['wins']}-{gw_ - X['wins']}")
                            A("wpctlo", -X["wins"] / gw_ + gw_ * 1e-6, pct(X["wins"] / gw_), f"{X['wins']}-{gw_ - X['wins']}")
                            lk_ = X["wins"] - X["xw"]; lx_ = f"{wl_} in his starts, {X['xw']:.1f} from his own play"
                            A("luck", lk_ - gp, f"{lk_:+.1f}", lx_); A("unluck", -lk_ - gp, f"{lk_:+.1f}", lx_)
                        wi_ = X["xw"] - 0.5 * gw_ if gw_ else 0.0
                        if gw_: A("wi", wi_ - gp, f"{wi_:+.2f}", f"{gw_} starts"); A("wilo", -wi_ - gp, f"{wi_:+.2f}", f"{gw_} starts")
                        if n1: A("top", n1 - g_ * 1e-4, str(n1), f"of {g_} starts")          # ties: fewer starts wins (a higher rate)
                        if X.get("hasp", 0) >= 4 and pre_ == "py":    # clutch: the wins his plays added beyond what his points alone are worth
                            A("wpa", X["cw"] - gp, f"{X['cw']:+.2f}", f"{g_} starts"); A("wpalo", -X["cw"] - gp, f"{X['cw']:+.2f}", f"{g_} starts")
                            A("cpa", X.get("cpa", 0.0) - gp, f"{X.get('cpa', 0.0) * 100:+.2f}%", f"{g_} starts")
                    bn_ = X.get("bn", 0)
                    if X["ben"] > 0: A("ben", X["ben"] - bn_ * 1e-6, fp(X["ben"]), f"{bn_} week{'' if bn_ == 1 else 's'} on the bench", sq="bseq")
                    if bn_ >= 1: A("benppg", X["ben"] / bn_ + bn_ * 1e-8, fp(X["ben"] / bn_), f"{bn_} week{'' if bn_ == 1 else 's'} on the bench", sq="bseq")
        for i, X in agg_p.items():
            tot(i, X["by"].most_common(1)[0][0], [r for r in X["by"]], X, sum(top[i].values()), "L")
        for (i, r), X in agg_t.items():
            tot(i, r, [r], X, top[i][r], "T")
        # ---- managers
        for r in s.R:
            n_ = len(s.weeks); lk = s_.W0[r] - s_.xw[r]; u = s_.turl(r, "")
            add("f_wins", s_.W0[r] - n_ * 1e-6, str(s_.W0[r]), r, [r], u=u, x=s_.rec_str(r))
            add("f_pct", s_.W0[r] / n_ + n_ * 1e-6, pct(s_.W0[r] / n_), r, [r], u=u, x=s_.rec_str(r))
            add("f_pf", s_.PF[r], fp(s_.PF[r]), r, [r], u=u, x=f"{n_} games")
            add("f_luck", s_.W0[r] - s_.xw[r], f"{lk:+.1f}", r, [r], u=u, x=f"{s_.W0[r]} wins, {s_.xw[r]:.1f} xWins")
        # pickups and drops on their own, graded like trades: best lineup with the move minus without it, every week since
        for x_, r_, i_, sg_, tot_, _rs in (getattr(s, "mparts", []) or []):
            v_ = tot_ / s.ppw
            if sg_ == "+": add("m_pick", v_, f"{v_:+.2f}", r_, [r_], p=i_, w=x_["w"], u=f"player/{i_}.html", x=f"{tot_:+.1f} pts with him vs a replacement")
            elif v_ < -0.0005: add("m_drop", -v_, f"{v_:+.2f}", r_, [r_], p=i_, w=x_["w"], u=f"player/{i_}.html", x=f"{tot_:+.1f} pts since the cut")
        for t in s.trade_res:
            sd = sorted(t["sides"], key=lambda x: -x["pts"]); gap = (sd[0]["pts"] - sd[-1]["pts"]) / s.ppw
            add("m_heist", gap, f"{gap:.2f}", sd[0]["r"], [x["r"] for x in t["sides"]], o=sd[-1]["r"], w=t["w"], u="trades.html",
                x=f"{s.M[sd[0]['r']]} {sd[0]['pts'] / s.ppw:+.2f} wins, {s.M[sd[-1]['r']]} {sd[-1]['pts'] / s.ppw:+.2f} wins")
        drows, dteam, _ = s_.draft_vals()
        for r in s.R: add("m_draft", dteam[r], f"{dteam[r]:+.2f}", r, [r], u="draft.html", x=(f"Picks beat their draft spots by {dteam[r]:.2f} wins" if dteam[r] >= 0 else f"Picks fell short of their draft spots by {-dteam[r]:.2f} wins"))
        ntr = Counter(); nmv = Counter()
        for t in s.trade_res:
            for x in t["sides"]: ntr[x["r"]] += 1
        for t in s.tx:
            if t["status"] == "complete" and t["type"] in ("waiver", "free_agent"): nmv[t["rosters"][0]] += 1
        for r in s.R:
            add("m_trades", ntr[r], str(ntr[r]), r, [r], u=s_.turl(r, "") + f"#{yr}-moves")
            add("m_moves", nmv[r], str(nmv[r]), r, [r], u=s_.turl(r, "") + f"#{yr}-moves")
        # ---- front office, lineups, weekly (one row per manager-season; all-time adds seasons up)
        _, _, gm_draft = s_.draft_vals()
        trw = Counter(); best_tr = []
        for t in s.trade_res:
            for x in t["sides"]:
                v = x["pts"] / s.ppw; trw[x["r"]] += v; best_tr.append((v, t, x))
        for v, t, x in best_tr:
            add("m_besttrade", v, f"{v:+.2f}", x["r"], [x["r"]], w=t["w"], u="trades.html", x="got " + ", ".join(s_.pn(i) for i in x["got"]))
        pk = Counter(); dr = Counter(); MV_ = getattr(s, "mval", {}) or {}
        for x_ in s.tx:            # waiver and free-agent moves, whole move (adds and drops together), graded like trades
            if x_["status"] == "complete" and x_["type"] in ("waiver", "free_agent") and id(x_) in MV_:
                for r_, v_ in MV_[id(x_)].items(): pk[r_] += v_[0] / s.ppw
        for x_, r_, i_, sg_, tot_, _rs in (getattr(s, "mparts", []) or []):
            if sg_ == "-" and tot_ < 0: dr[r_] += -tot_ / s.ppw        # what the cuts cost: each drop on its own
        grd = getattr(s, "grades", {}); gw = getattr(s, "grade_weeks", [])
        s_.lineup_added()
        for (w, r), v in s_._law.items():
            a_, b_ = s_.game_of.get((w, r), (r, r)); o_ = b_ if r == a_ else a_
            add("l_add1", v, f"{v:+.2f}", r, [r], o=o_, w=w, u=s_.gurl(w, a_, b_, ""))
        hi = Counter(); lo = Counter(); mvp = Counter(a["mvp"][1] for a in s.awards)
        for w in s.weeks:
            sc = s.G[w]["scores"]; hi[max(sc, key=sc.get)] += 1; lo[min(sc, key=sc.get)] += 1
        for r in s.R:
            u = s_.turl(r, "") + f"#{yr}"; um = s_.turl(r, "") + f"#{yr}-moves"; ul = s_.turl(r, "") + f"#{yr}-lineups"
            gm = trw[r] + pk[r] + gm_draft[r]
            add("m_gm", gm, f"{gm:+.2f}", r, [r], u=um, x=f"{gm_draft[r]:.2f} wins from the draft, {pk[r]:.2f} from pickups, {trw[r]:.2f} from trades")
            la_ = s_.lineup_added().get(r, 0.0)
            add("l_add", la_, f"{la_:+.2f}", r, [r], u=ul)
            add("m_total", gm + la_, f"{gm + la_:+.2f}", r, [r], u=u, x=f"{gm:.2f} as GM, {la_:.2f} from gut calls")
            add("m_trader", trw[r], f"{trw[r]:+.2f}", r, [r], u=um, x=f"{ntr[r]} trade{'' if ntr[r] == 1 else 's'}")
            add("m_waiver", pk[r], f"{pk[r]:+.2f}", r, [r], u=um, x=f"{nmv[r]} moves")
            add("m_dropcost", dr[r], f"{dr[r]:+.2f}", r, [r], u=um, x="wins his cuts cost him, each graded like a trade")
            # efficiency: wins added per move (minimums keep one lucky move from owning it)
            if ntr[r] >= 2: v = trw[r] / ntr[r]; add("m_treff", v + ntr[r] * 1e-7, f"{v:+.2f}", r, [r], u=um, x=f"{trw[r]:.2f} wins added in {ntr[r]} trades")
            if nmv[r] >= 5: v = pk[r] / nmv[r]; add("m_wveff", v + nmv[r] * 1e-7, f"{v:+.2f}", r, [r], u=um, x=f"{pk[r]:.2f} wins added in {nmv[r]} moves")
            if ntr[r] + nmv[r] >= 5: v = (trw[r] + pk[r]) / (ntr[r] + nmv[r]); add("m_eff", v + (ntr[r] + nmv[r]) * 1e-7, f"{v:+.2f}", r, [r], u=um, x=f"{trw[r] + pk[r]:.2f} wins added in {ntr[r] + nmv[r]} trades and moves")
            opt = act = 0.0; over = 0.0; nproj = 0
            for w in s.weeks:
                d = s.W[w][r]; o_, _ = s.best([(i, s.pos(i), p) for i, p in d["S"] + d["B"] if i != "0"]); opt += o_; act += s.G[w]["scores"][r]
                pg_ = s_.pregame(w, r)
                if pg_: over += s.G[w]["scores"][r] - pg_[0]; nproj += 1
            add("l_eff", act / opt, pct(act / opt), r, [r], u=ul, x=f"{fp(act)} of {fp(opt)}")
            add("l_bench", opt - act, fp(opt - act), r, [r], u=ul, x="")
            if nproj: add("l_over", over, f"{over:+.1f}", r, [r], u=u, x="")
            add("w_high", hi[r], str(hi[r]), r, [r], u=u)
            add("w_low", lo[r], str(lo[r]), r, [r], u=u)
            add("w_mvp", mvp[r], str(mvp[r]), r, [r], u=u)
            add("m_allmv", ntr[r] + nmv[r], str(ntr[r] + nmv[r]), r, [r], u=um if False else u)
        # ---- manager all-time totals: each manager's seasons added up (rates averaged). Shown only in the All-time view.
        for k in ("m_gm", "m_trader", "m_draft", "m_waiver", "m_dropcost", "m_eff", "m_treff", "m_wveff", "l_add", "m_total", "l_eff", "l_bench", "l_over", "w_high", "w_low", "w_mvp", "m_trades", "m_moves", "m_allmv"):
            by = defaultdict(list)
            for e in E_.get(k, []): by[e["e"][1]].append(e)
            for r, es in by.items():
                if len(es) == 1: x0 = dict(es[0]); x0["e"] = list(es[0]["e"]); x0["y"] = "all"; x0["e"][7] = ""; E_["c_" + k].append(x0); continue
                t0 = es[0]["e"][0]; rate = "%" in t0 or k in ("m_eff", "m_treff", "m_wveff"); v = sum(e["v"] for e in es) / (len(es) if rate else 1)
                tx_ = pct(v) if rate else (f"{v:+.2f}" if t0[:1] in "+-" else (fp(abs(v)) if "." in t0 else str(int(round(abs(v))))))
                E_["c_" + k].append(dict(v=v, e=[tx_, r, "", 0, 0, yr, es[0]["e"][6], "", round(v, 9)], rs={r}, y="all", only=None))
        out = {}
        for sc_ in ["L"] + [str(r) for r in s.R]:
            out[sc_] = {}
            for per in [str(yr), "all"]:
                d_ = {}
                for k, L_ in E_.items():
                    xs = [e for e in L_ if (e["only"] != ("T" if sc_ == "L" else "L")) and (sc_ == "L" or int(sc_) in e["rs"]) and (per == "all" or str(e["y"]) == per)]
                    if k.startswith("p_startlo_") and any(e["v"] > 0 for e in xs): xs = [e for e in xs if e["v"] > 0]     # once anyone at this position has gone negative, only negatives count
                    if xs:
                        xs = sorted(xs, key=lambda e: (-e["v"], -e.get("tb", 0.0))); n10 = min(10, len(xs))
                        while n10 < len(xs) and xs[n10]["e"][0] == xs[n10 - 1]["e"][0]: n10 += 1     # a tie at 10th keeps everyone tied
                        d_[k] = [e["e"] for e in xs[:n10]]
                out[sc_][per] = d_
            if out[sc_]["all"] == out[sc_][str(yr)]: out[sc_]["all"] = "="
        return out

    # ------------------------------------------------------------------ league pages
    def build_frags(s_):
        s = s_.s; M = s_.M; nm = s_.pn; out = s_.SIM[0]; n = s_.n; W0, PF = s_.W0, s_.PF; wk0 = s.nxt; pre = ""
        F = {}
        rows = []; PV = getattr(s, "prev", None)
        def mvr(r, k):
            if not PV: return ""
            d = PV["rank"][r] - k
            return f'<span class="mvu">&#9650;{d}</span>' if d > 0 else (f'<span class="mvd">&#9660;{-d}</span>' if d < 0 else "")
        def bmv(r, key, cls=""):
            o = out[r]; h = bar(o[key], cls)
            if not PV: return h
            d = round((o[key] - PV["odds"][r][key]) * 100)
            return h + (f'<span class="dlt {"pos" if d > 0 else "neg"}">{d:+d}</span>' if d else '<span class="dlt"></span>')
        PA0 = Counter()
        for w_ in s.weeks:
            for x_, y_ in s.G[w_]["pairs"]: PA0[x_] += s.G[w_]["scores"][y_]; PA0[y_] += s.G[w_]["scores"][x_]
        for k, r in enumerate(s_.stand, 1):
            o = out[r]; luck = W0[r] - s_.xw[r]
            P_, B_ = s.L["playoff_teams"], s.L["playoff_byes"]
            cls = ("zb " if k <= B_ else "zp " if k <= P_ else "out ") + ("byecut" if k == B_ else "cut" if k == P_ else "")
            rows.append(f'<tr class="{cls}"><td class="rk">{k}<span class="mv">{mvr(r, k)}</span></td><td>{s_.tl(r, pre)}</td><td class="c big">{s_.rec_str(r)}</td>'
                        f'<td class="r cp">{PF[r]:.1f}</td><td class="r cp">{PA0[r]:.1f}</td><td class="r cp">{s_.xw[r]:.1f}</td><td class="r cp {"pos" if luck > 0.25 else "neg" if luck < -0.25 else ""}">{luck:+.1f}</td>'
                        f'<td class="b co">{bmv(r, "po")}</td><td class="b co">{bmv(r, "bye", "b2")}</td><td class="b co">{bmv(r, "ti", "b3")}</td></tr>')
        F["standings"] = (f'<div class="zkey"><span class="zk zb">Bye</span><span class="zk zp">Playoffs</span></div><div class="rtog chips stog" role="group" aria-label="Standings view"><button type="button" data-v="odds" aria-pressed="true">Odds</button><button type="button" data-v="points" aria-pressed="false">Points</button></div>'
                          f'<div class="scroll"><table class="stand" data-v="odds"><thead><tr><th></th><th>Team</th><th class="c">Record</th><th class="r cp">PF</th><th class="r cp">PA</th><th class="r cp">xWins</th>'
                          f'<th class="r cp">Luck</th><th class="co">Playoffs</th><th class="co">Bye</th><th class="co">Title</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
                          '')
        F["finals"] = "".join(f'<li>{s_.tn(a, pre)} vs {s_.tn(b, pre)} <span class="muted">happens {pct(c, 1)} of the time; {E(s_.TN(a))} wins it {pct(p)}</span></li>' for a, b, c, p in s_.SIM[2][:4])
        prow = []; pmx = max([abs(x["pw"]) for x in s.power] + [1])
        for k, x in enumerate(s.power, 1):
            mv = x["st"] - k
            mvh = f'<span class="mv"><span class="pos">&#9650;{mv}</span></span>' if mv > 0 else (f'<span class="mv"><span class="neg">&#9660;{-mv}</span></span>' if mv < 0 else '<span class="mv"></span>')
            wd = abs(x["pw"]) / pmx * 50
            pb_ = (f'<div class="pbar" aria-hidden="true"><i style="{"left:50%" if x["pw"] >= 0 else f"left:{50 - wd:.1f}%"};width:{wd:.1f}%" class="{"up" if x["pw"] >= 0 else "dn"}"></i></div>')
            prow.append(f'<tr><td class="rk">{k}{mvh}</td><td>{s_.tl(x["r"], pre)}</td><td class="pw"><b class="{"pos" if x["pw"] > 0 else "neg"}">{x["pw"]:+.1f}</b>{pb_}</td>'
                        f'<td class="r">{x["ppg"]:.1f}</td><td class="r">{x["l3"]:.1f}</td><td class="r">{x["ros"]:.1f}</td></tr>')
        F["power"] = (f'<div class="scroll"><table class="pwr" style="min-width:0"><thead><tr><th></th><th>Team</th><th>Power</th><th class="r"><span class="lgl">Season avg</span><span class="sml">Avg</span></th><th class="r">Last 3</th><th class="r"><span class="lgl">Projected</span><span class="sml">Proj</span></th></tr></thead><tbody>{"".join(prow)}</tbody></table></div>'
                      '<p class="note">Power = points per week above an average team: 30% season average, 20% last 3 weeks, 50% projected for the rest of the season. Arrows show the difference from the standings.</p>')
        allw = list(s.weeks) + [w for w in s_.weeks_left if w not in s.weeks]
        def gcard(w, a, b, done):
            if done:
                sa, sb = s.G[w]["scores"][a], s.G[w]["scores"][b]
                row = lambda r, sc, won: f'<div class="gr {"w" if won else "l"}">{s_.logo(r, pre, "lg", w)}<span class="t"><b>{E(s_.TN(r, w))}</b><small>{E(s_.M[r])}</small></span><span class="s">{fp(sc)}</span></div>'
                return f'<a class="gcard" href="{s_.gurl(w, a, b, pre)}">{row(a, sa, sa > sb)}{row(b, sb, sb > sa)}<div class="gf"><span class="tagf">Final</span><span>Box score</span></div>{s_.sline(w, a, b)}</a>'
            A, B = s_.upcoming(w, a), s_.upcoming(w, b); pa = s_.win_p(A, B); live = s_.wk_live(w)
            sc = lambda r, mu: f'{fp(s_.now_pts(w, r))}<small>Proj {mu:.1f}</small>' if live else f"{mu:.1f}"
            row = lambda r, mu: f'<div class="gr">{s_.logo(r, pre, "lg")}<span class="t"><b>{E(s_.TN(r))}</b><small>{E(s_.M[r])}, {s_.rec_str(r)}</small></span><span class="s p">{sc(r, mu)}</span></div>'
            return f'<a class="gcard fut" href="{s_.gurl(w, a, b, pre)}">{row(a, A[0])}{row(b, B[0])}<div class="gf">{s_.rope(a, b, pa)}</div>{s_.sline(w, a, b)}</a>'
        opts = "".join(f'<option value="{w}"{" selected" if w == wk0 else ""}>Week {w}{"" if w in s.G else ((" (live)" if s_.wk_live(w) else " (up next)") if w == wk0 else " (upcoming)")}</option>' for w in allw)
        panels = "".join(f'<div class="wkp" data-w="{w}"><div class="gcards">' +
                         "".join(gcard(w, a, b, w in s.G) for a, b in s_.game_order(w, s.G[w]["pairs"] if w in s.G else s.fut.get(w, []))) + f"</div>{s_.week_extras(w, pre)}</div>" for w in allw)
        sched_ui = (f'<div class="wkbar"><button type="button" class="wstep" data-d="-1" aria-label="Previous week">&lsaquo;</button>'
                    f'<label class="wlab"><span class="sr">Week</span><select class="wsel" data-default="{wk0}">{opts}</select></label>'
                    f'<button type="button" class="wstep" data-d="1" aria-label="Next week">&rsaquo;</button></div>{panels}')
        F["schedule"] = sched_ui
        tot, gs, pts, teams, best = s_.season_pm(s)
        F["mvp_order"] = order = sorted(tot, key=lambda i: -tot[i]); F["mvp"] = (tot, gs, pts, teams)
        tlinks = lambda names: f"{len(names)} teams" if len(names) > 2 else " / ".join(s_.tn(s_.bym[t], pre) for t in sorted(names))
        mvp_rows = "".join(f'<tr><td class="rk">{k}</td><td><b>{s_.plink(i, pre)}</b><small>{tlinks(teams[i])}</small></td><td class="r big">{tot[i]:+.1f}</td><td class="r">{gs[i]}</td><td class="r">{pts[i] / gs[i]:.1f}</td></tr>' for k, i in enumerate(order[:10], 1))
        wk_rows = "".join(
            f'<tr><td class="rk">{a["w"]}</td>'
            f'<td><b>{s_.plink(a["mvp"][0], pre)}</b><small>{s_.tn(a["mvp"][1], pre)}, <a class="go" href="{s_.gurl_r(a["w"], a["mvp"][1], pre)}">{fp(a["mvp"][2])} pts</a></small></td><td class="r pos">+{a["mvp"][3]:.1f}</td>'
            f'</tr>'
            for a in reversed(s.awards))
        def mini(pool, k=10, bare=False, key="pm"):
            t_, g_, p_, tm_, _ = s_.season_pm(s, pool, key)
            fmt_ = (lambda v: f"{v:+.1f}") if key == "pm" else fp
            return "".join(f'<tr><td class="rk">{j}</td><td><b>{s_.plink(i, pre, s.nm(i) if bare else None)}</b><small>{tlinks(tm_[i])}</small></td><td class="r big">{fmt_(t_[i])}</td></tr>' for j, i in enumerate(sorted(t_, key=lambda i: -t_[i])[:k], 1))
        rook = {i for i, v in s.PL.items() if v.get("exp") == 0}; und = {i for i in s.PL if i not in s.dpick}
        bbp_ = s_.bench_by_player()
        rlinks = lambda rs: f"{len(rs)} teams" if len(rs) > 2 else " / ".join(s_.tn(r_, pre) for r_ in rs)
        bench_rows = "".join(f'<tr><td class="rk">{j}</td><td><b>{s_.plink(i, pre)}</b><small>{rlinks([r_ for r_, _ in bbp_[i]["by"].most_common()])}</small></td><td class="r big">{v:+.2f}</td></tr>'
                             for j, (i, v) in enumerate(sorted(((k, x["pts"] * s.wpp) for k, x in bbp_.items()), key=lambda kv: -kv[1])[:10], 1))
        avail = {}; availT = {}    # Sixth Man: every week he sat on a Super League roster, and for whom
        for w in s.weeks:
            if w > s.L.get("regular_season_weeks", 14): continue
            for r in s.R:
                for x in s.W[w][r]["S"] + s.W[w][r]["B"]:
                    i = x[0] if isinstance(x, (list, tuple)) else x
                    if i and i != "0": avail[i] = avail.get(i, 0) + 1; availT.setdefault(i, Counter())[r] += 1
        eff = sorted((i for i in tot if 0 < gs[i] and gs[i] * 2 <= avail.get(i, 0) and tot[i] > 0), key=lambda i: -tot[i])[:10]
        six_rows = "".join(f'<tr><td class="rk">{j}</td><td><b>{s_.plink(i, pre)}</b><small>{rlinks([r_ for r_, _ in availT[i].most_common()])}</small></td><td class="r muted">{gs[i]}/{avail[i]}</td><td class="r big">{tot[i]:+.1f}</td></tr>' for j, i in enumerate(eff, 1))
        nrs = len([w for w in s.weeks if w <= s.L.get("regular_season_weeks", 14)]); emin = 1      # Most Efficient: PAA per start, no minimum
        effp = sorted((i for i in tot if gs[i] >= emin), key=lambda i: -tot[i] / gs[i])[:10]
        eff_rows = "".join(f'<tr><td class="rk">{j}</td><td><b>{s_.plink(i, pre)}</b><small>{tlinks(teams[i])}</small></td><td class="r muted">{gs[i]}</td><td class="r big">{tot[i] / gs[i]:+.1f}</td></tr>' for j, i in enumerate(effp, 1))
        vote_ = open(os.path.join(os.path.dirname(s_.logo_dir), "mvp_vote.txt")).read().strip().split("\n")[-1] if os.path.exists(os.path.join(os.path.dirname(s_.logo_dir), "mvp_vote.txt")) else ""
        aw_html = s_.season_awards(pre)
        races_extra = (f'<section><h2>MVP race</h2><p class="intro">PAA. The top 10 go to a league vote after Week 14.'
                       + (f' <b>MVP: {s_.plink(vote_, pre)}</b>' if vote_ in s.PL else "") + f'</p><div class="scroll"><table style="min-width:0"><thead><tr><th></th><th>Player</th><th class="r">PAA</th><th class="r">Starts</th><th class="r">Avg</th></tr></thead><tbody>{mvp_rows}</tbody></table></div></section>'
                       f'<div class="grid2"><section><h2>Rookie of the Year race</h2><p class="intro">PAA, NFL rookies only.</p><table class="pt"><tbody>{mini(rook)}</tbody></table></section>'
                       f'<section><h2>Undrafted Player of the Year race</h2><p class="intro">PAA, undrafted players only.</p><table class="pt"><tbody>{mini(und)}</tbody></table></section></div>'
                       + f'<div class="grid2"><section><h2>Benchwarmer of the Year race</h2><p class="intro">Wins a bench player would have added to the teams he sat on.</p><table class="pt"><tbody>{bench_rows}</tbody></table></section>'
                       + f'<section><h2>Sixth Man of the Year race</h2><p class="intro">PAA, players who started half their rostered weeks or fewer.</p><table class="pt"><tbody>{six_rows}</tbody></table></section></div>'
                       + f'<section><h2>Most Efficient Player race</h2><p class="intro">PAA per start.</p><div class="scroll"><table style="min-width:0"><thead><tr><th></th><th>Player</th><th class="r">Starts</th><th class="r">PAA/start</th></tr></thead><tbody>{eff_rows}</tbody></table></div></section>'

                       + '<section class="posr"><h2>Position of the Year races</h2><p class="intro">PAA, by position.</p><div class="rtog chips posrt" role="group" aria-label="Position">'
                       + "".join(f'<button type="button" data-p="{P}" aria-pressed="{"true" if P == "QB" else "false"}">{P}</button>' for P in ("QB", "RB", "WR", "TE", "K", "DEF")) + '</div>'
                       + "".join(f'<div class="posrv" data-p="{P}"{"" if P == "QB" else " hidden"}><table class="pt"><tbody>{mini({i for i in s.PL if s.pos(i) == P or (not i.isdigit() and P == "DEF")}, 5, True)}</tbody></table></div>'
                                 for P in ("QB", "RB", "WR", "TE", "K", "DEF"))
                       + '</section>')
        F["races"] = races_extra + aw_html
        season_list = [("MVP", "mvp"), ("Rookie of the Year", "roty"), ("Undrafted Player of the Year", "und"), ("Benchwarmer of the Year", "bench"), ("Most Efficient Player", "eff"), ("QB of the Year", "qb"), ("RB of the Year", "rb"), ("WR of the Year", "wr"), ("TE of the Year", "te"), ("K of the Year", "k"), ("DEF of the Year", "def"), ("Manager of the Year", "moy"), ("GM of the Year", "gm"), ("Heist of the Year", "heist"), ("Pickup of the Year", "pickup"), ("Worst Drop of the Year", "drop"), ("Steal of the Draft", "steal"), ("Bust of the Draft", "bust"), ("Game of the Year", "classic"), ("Comeback of the Year", "improb")]
        for t, k in season_list:          # each race is addressable: #/races/<key> lands on it
            F["races"] = F["races"].replace(f"<h2>{t} race</h2>", f'<h2 id="races-{k}" style="scroll-margin-top:70px">{t} race</h2>', 1)
        trophies = "".join(f'<a class="trophy" href="#/races/{k}"><b>{t}</b><span>{"League vote among the top 10, after Week 14." if k == "mvp" else "Regular season only. Final after Week 14."} </span><span class="go">See the race</span></a>' for t, k in season_list)
        F["awards"] = (f'<section><h2>Season awards</h2><p class="intro">Given out once the {s_.yr} season is over. Until then, the races above show who leads each one.</p><div class="trophies">{trophies}</div></section>'
                       f'<section><h2>Weekly MVP</h2><div class="scroll"><table><thead><tr><th>Wk</th><th>MVP</th><th class="r">PAA</th></tr></thead><tbody>{wk_rows}</tbody></table></div></section>')
        Rv = s.repl["val"]
        def imp(t, r, i):          # how much he has mattered to the team that got him: WAR in its lineup since the trade, then season WAR
            war = sum((p - Rv.get(s.pos(i), 0)) * s.wpp for w in s.weeks if w >= t["w"] for j, p in s.W[w][r]["S"] if j == i)
            tot = sum((p - Rv.get(s.pos(i), 0)) * s.wpp for w in s.weeks for rr in s.R for j, p in s.W[w][rr]["S"] if j == i)
            return (war, tot)
        def gotfrom(t, x):          # most important player first; 3-team deals also say who each player came from
            got = sorted(x["got"], key=lambda i: imp(t, x["r"], i), reverse=True)
            if len(t["sides"]) < 3: return ", ".join(s_.pa(i, nm(i)) for i in got)
            by = defaultdict(list)
            for i in got: by[t.get("frm", {}).get(i)].append(i)
            return "<br>".join(f'{", ".join(s_.pa(i, nm(i)) for i in ps)} <span class="muted" style="font-size:13px">(from {E(s_.M[fr]) if fr else "?"})</span>' for fr, ps in by.items())
        trow = []; net = Counter()
        for t in s.trade_res:
            best_r = max(t["sides"], key=lambda x: x["pts"])["r"]
            for j, x in enumerate(t["sides"]):
                wins = x["pts"] / s.ppw; net[x["r"]] += wins
                trow.append(f'<tr class="{"tstart" if j == 0 else ""}"><td class="rk">{t["k"] if j == 0 else ""}</td><td class="c">{"Week " + str(t["w"]) if j == 0 else ""}</td>'
                            f'<td class="trt">{s_.tl(x["r"], pre)}<div class="trm">{("<b>Week " + str(t["w"]) + ":</b> ") if j == 0 else ""}{gotfrom(t, x)}</div></td><td class="muted trx" style="font-size:13px">received</td><td class="trx">{gotfrom(t, x)}</td>{'<td class="r muted" style="font-size:13px">No games yet</td>' if t["w"] > s.last and not (t["w"] == s.nxt and s_.wk_live(s.nxt)) else f'<td class="r big {"pos" if wins > 0 else "neg" if wins < 0 else ""}">{wins:+.1f}</td>'}</tr>')
        vet = [t for t in s.trades if t["vetoed"]]
        def vrow(t):
            tv = dict(w=t["w"], frm=t.get("frm", {}), sides=[dict(r=r, got=got) for r, (got, gave) in t["sides"].items()])
            return "".join(f'<tr class="{"tstart" if j == 0 else ""}"><td class="rk"></td><td class="c">{"Week " + str(t["w"]) if j == 0 else ""}</td>'
                           f'<td>{s_.tl(x["r"], pre)}</td><td class="muted" style="font-size:13px">would have received</td><td>{gotfrom(tv, x)}</td>'
                           f'<td class="r">{"<b class=\"neg\" style=\"font-size:15px\">Vetoed</b>" if j == 0 else ""}</td></tr>' for j, x in enumerate(tv["sides"]))
        vetrows = "".join(vrow(t) for t in vet)
        netrows = "".join(f'<tr><td>{s_.tl(r, pre)}</td><td class="r big {"pos" if v > 0 else "neg"}">{v:+.1f}</td></tr>' for r, v in sorted(net.items(), key=lambda kv: -kv[1]))
        F["trades"] = (f'<section><h2>Every trade</h2>'
                       f'<div class="scroll"><table class="trtab"><thead><tr><th></th><th class="c">When</th><th>Team</th><th class="trx"></th><th class="trx">Players received</th><th class="r">Wins added</th></tr></thead><tbody>{"".join(trow)}</tbody></table></div></section>'
                       + (f'<section><h2>Vetoed trades</h2><p class="intro">Agreed, then undone by the commissioner. Kept for the record; they never count toward anyone\'s trade grade, pickups or cuts.</p><div class="scroll"><table><thead><tr><th></th><th class="c">When</th><th>Team</th><th></th><th>Players</th><th class="r"></th></tr></thead><tbody>{vetrows}</tbody></table></div></section>' if vet else "") +
                       f'<section><h2>Net by team</h2><table class="pt" style="max-width:520px"><tbody>{netrows}</tbody></table></section>')
        allsc = sorted([(s.G[w]["scores"][r], w, r) for w in s.weeks for r in s.R])
        gms = sorted((abs(s.G[w]["scores"][a] - s.G[w]["scores"][b]), w, *((a, b) if s.G[w]["scores"][a] > s.G[w]["scores"][b] else (b, a))) for w in s.weeks for a, b in s.G[w]["pairs"])
        ts = max(((p, w, r, i) for w in s.weeks for r, d in s.W[w].items() for i, p in d["S"] if i != "0"))
        lk = {r: W0[r] - s_.xw[r] for r in s.R}; lu = max(s.R, key=lk.get); un = min(s.R, key=lk.get); yr = s_.yr
        rec = [("Highest score", f"{s_.who(allsc[-1][2])}, {fp(allsc[-1][0])}", f"Week {allsc[-1][1]}, {yr}", s_.gurl_r(allsc[-1][1], allsc[-1][2], pre)),
               ("Lowest score", f"{s_.who(allsc[0][2])}, {fp(allsc[0][0])}", f"Week {allsc[0][1]}, {yr}", s_.gurl_r(allsc[0][1], allsc[0][2], pre)),
               ("Biggest blowout", f"{s_.who(gms[-1][2])} over {s_.who(gms[-1][3])} by {fp(gms[-1][0])}", f"Week {gms[-1][1]}, {yr}", s_.gurl(gms[-1][1], gms[-1][2], gms[-1][3], pre)),
               ("Closest game", f"{s_.who(gms[0][2])} over {s_.who(gms[0][3])} by {fp(gms[0][0])}", f"Week {gms[0][1]}, {yr}", s_.gurl(gms[0][1], gms[0][2], gms[0][3], pre)),
               ("Best single start", f"{s_.who(ts[2])}: {nm(ts[3])}, {fp(ts[0])}", f"Week {ts[1]}, {yr}", s_.gurl_r(ts[1], ts[2], pre)),
               ("Luckiest team", f"{s_.who(lu)}, {lk[lu]:+.1f} wins", f"vs xWins, {yr} through Week {s.last}", s_.turl(lu, pre)),
               ("Unluckiest team", f"{s_.who(un)}, {lk[un]:+.1f} wins", f"vs xWins, {yr} through Week {s.last}", s_.turl(un, pre))]
        F["records"] = '<div class="recs">' + "".join(f'<a class="rec" href="{u}"><span class="k">{E(a)}</span><span class="v">{E(b)}</span><span class="w">{E(c)}</span></a>' for a, b, c, u in rec) + "</div>"
        return F

    def site_pages(s_):
        s = s_.s; F = s_.build_frags(); wk0 = s.nxt; pre = ""; out = s_.SIM[0]; nm = s_.pn; yr = s_.yr
        P = {}
        upd = datetime.date.today().strftime("%B %-d")
        # ---------- home
        faces = "".join(s_.faceoff(wk0, a, b, pre) for a, b in s_.game_order(wk0, s.fut.get(wk0, [])))
        hero = (f'<section class="field"><div class="wrap"><h1>Week {wk0}</h1>'
                f'<p class="lede">{"<span class=livedot>LIVE</span> " if s_.wk_live(wk0) else ""}{stamp()}</p>'
                f'<div class="faceoffs">{faces}</div></div></section>')
        P_ = s.L["playoff_teams"]; race = []
        for k, r in enumerate(sorted(s.R, key=lambda r: (-out[r]["po"], -out[r]["ti"])), 1):
            o = out[r]
            race.append(f'<a href="{s_.turl(r, pre)}" class="{"out" if k > P_ else ""}"><span class="rk">{k}</span><span class="who">{s_.logo(r, pre, "lgs")}<b>{E(s_.TN(r))}</b></span>'
                        f'<span class="wl">{s_.rec_str(r)}</span><span class="po"><i style="width:{o["po"] * 100:.1f}%"></i></span><span class="pv">{pct(o["po"])}</span></a>')
            if k == P_: race.append(f'<div class="line">Playoff line</div>')
        w = s.last
        res = [s_.mini_game(w, a, b, True, pre) for a, b in s_.game_order(w, s.G[w]["pairs"])]
        aw = s.awards[-1]; mi, mr, mp, mpm, _ = aw["mvp"]
        mt_ = s_.team_at(w, mi); mtl = f'<i class="nfl pnfl N{mt_}" role="img" aria-label="{mt_}"></i>' if mt_ in NFL_NICK else ""
        potw = (f'<a class="potw" href="{s_.gurl_r(w, mr, pre)}"><span class="lab">Week {w} MVP</span><span class="who"><b>{E(nm(mi).rsplit(" ", 1)[0])} <span class="nw">{E(nm(mi).rsplit(" ", 1)[-1])}{mtl}</span></b><span class="ptm"><i class="im L{mr}" aria-hidden="true"></i>{E(s_.TN(mr))}</span></span>'
                f'<span class="pts">{fp(mp)}<small>pts</small></span></a>')
        tot, gs, pts_, teams = F["mvp"]
        mvpl = "".join(f'<div><span class="rk">{k}</span><span><b>{s_.pa(i, nm(i))}</b><small class="muted"> {E(s.pos(i))}, {(str(len(teams[i])) + " teams") if len(teams[i]) > 2 else " / ".join(E(s_.TN(s_.bym[t])) for t in sorted(teams[i]))}</small></span><span class="v">{tot[i]:+.0f}</span></div>' for k, i in enumerate(F["mvp_order"][:5], 1))
        teams_strip = "".join(f'<a href="{s_.turl(r, pre)}">{s_.logo(r, pre, "")}<b>{E(s_.TN(r))}</b><small>{E(s_.M[r])}</small></a>' for r in s_.stand)
        body = f"""{s_.front()}{hero}
<main class="wrap">
<div class="cols">
<section><h2>Playoff race</h2><div class="race">{"".join(race)}</div><a class="more" href="standings.html">Full standings and title odds</a></section>
<section><h2>Week {w} results</h2><p class="intro">Tap a game for the box score.</p>{potw}<div class="mini res1">{"".join(res)}</div></section>
</div>
</main>{s_.footer(pre)}"""
        P["index.html"] = page(f"Super League {yr}", body, pre, "home")
        # ---------- inner pages
        P["standings.html"] = page(f"Standings, Super League {yr}", s_.head("Standings", f"Through Week {s.last}") +
                                   f'<main class="wrap"><section>{F["standings"]}</section>'
                                   f'<p class="more"><a class="go" href="playoffs.html">Playoff, bye and title odds, plus the odds tracker</a></p>'
                                   f'<section><h2>Power rankings</h2><p class="intro">Who\'s best right now, regardless of record.</p>{F["power"]}</section>'
                                   f'</main>{s_.footer(pre)}', pre, "standings")
        # ---------- playoffs: picture now, bracket, history
        P_, B_ = s.L["playoff_teams"], s.L["playoff_byes"]; pw0 = s.L["playoff_week_start"]
        seeds = s_.stand[:P_]; left = [w for w in s_.weeks_left]; maxw = {r: s_.W0[r] + len(left) for r in s.R}
        def status(r):
            others_can = sum(1 for x in s.R if x != r and maxw[x] >= s_.W0[r])
            if others_can < P_: return "Clinched"
            if sum(1 for x in s.R if x != r and s_.W0[x] > maxw[r]) >= P_: return "Eliminated"
            return ""
        def seedbox(k, r, sub=""):
            st = status(r)
            return (f'<a class="bseed" href="{s_.turl(r, pre)}"><span class="bn">{k}</span>{s_.logo(r, pre, "lgs")}<span class="bt"><b>{E(s_.TN(r))}</b><small>{E(s_.M[r])}, {s_.rec_str(r)}{(", " + st) if st else ""}</small></span>{sub}</a>')
        sd = {k + 1: r for k, r in enumerate(seeds)}
        def slot(lab): return f'<div class="bseed tbd"><span class="bt"><b>{lab}</b></span></div>'
        bracket = (f'<div class="bracket">'
                   f'<h3 style="grid-area:h1">Round 1 <small>Week {pw0}</small></h3><h3 style="grid-area:h2">Semifinals <small>Week {pw0 + 1}</small></h3><h3 style="grid-area:h3">Final <small>Week {pw0 + 2}</small></h3>'
                   f'<div class="bgame" style="grid-area:a1">{seedbox(1, sd[1])}<div class="bseed byer"><span class="bn"></span><span class="byc">Bye</span><span class="bt"><small>Straight to the semifinals</small></span></div></div>'
                   f'<div class="bgame" style="grid-area:a2">{seedbox(4, sd[4])}{seedbox(5, sd[5])}</div>'
                   f'<div class="bgame" style="grid-area:a3">{seedbox(3, sd[3])}{seedbox(6, sd[6])}</div>'
                   f'<div class="bgame" style="grid-area:a4">{seedbox(2, sd[2])}<div class="bseed byer"><span class="bn"></span><span class="byc">Bye</span><span class="bt"><small>Straight to the semifinals</small></span></div></div>'
                   f'<div class="bgame mid" style="grid-area:s1">{seedbox(1, sd[1])}{slot("Winner 4/5")}</div>'
                   f'<div class="bgame mid" style="grid-area:s2">{seedbox(2, sd[2])}{slot("Winner 3/6")}</div>'
                   f'<div class="bgame mid fin" style="grid-area:f">{slot("Semifinal winner")}{slot("Semifinal winner")}</div></div>')
        orows = "".join(f'<tr><td class="rk">{k}</td><td>{s_.tl(r, pre)}</td><td class="c big">{s_.rec_str(r)}</td>'
                        f'<td class="b tcol">{bar(out[r]["ti"], "b3")}</td><td class="b">{bar(out[r]["fin"], "b3")}</td><td class="b">{bar(out[r]["semi"], "b2")}</td><td class="b">{bar(out[r]["bye"], "b2")}</td><td class="b">{bar(out[r]["po"])}</td></tr>'
                        for k, r in enumerate(sorted(s.R, key=lambda r: (-out[r]["ti"], -out[r]["po"])), 1))
        heat = lambda v: f'background:rgba(226,174,42,{min(1, v * 1.6):.2f})'
        okS = getattr(s, "seedok", {}); avg = {r: sum((k + 1) * v for k, v in enumerate(out[r]["dist"])) for r in s.R}
        cellS = lambda r, k, v: (f'<td class="c hm{" pcut" if k == P_ - 1 else ""} imp" title="Mathematically impossible">×</td>' if okS and (k + 1) not in okS.get(r, set()) else
                                 f'<td class="c hm{" pcut" if k == P_ - 1 else ""}" style="{heat(v)}">{pct(v) if v >= 0.005 else ("<span class=lt1>&lt;1%</span>" if v > 0 else "")}</td>')
        grid = "".join(f'<tr><td>{s_.tl(r, pre)}</td>' + "".join(cellS(r, k, v) for k, v in enumerate(out[r]["dist"])) + f'<td class="c avgs"><b>{avg[r]:.1f}</b></td></tr>'
                       for r in sorted(s.R, key=lambda r: avg[r]))
        nS = len(s.R); Wd, rowh, L0, R0 = 440, 36, 84, 14; Hd = rowh * nS + 40; X = lambda v: L0 + (v - 1) / (nS - 1) * (Wd - L0 - R0)
        sv = "".join(f'<line x1="{X(k):.1f}" x2="{X(k):.1f}" y1="10" y2="{Hd - 26}" stroke="#E3E7EE"/><text x="{X(k):.1f}" y="{Hd - 8}" text-anchor="middle" font-size="13" fill="var(--mute)">{k}</text>' for k in range(1, nS + 1))
        sv += (f'<line x1="{(X(B_) + X(B_ + 1)) / 2:.1f}" x2="{(X(B_) + X(B_ + 1)) / 2:.1f}" y1="6" y2="{Hd - 26}" stroke="var(--flag)" stroke-dasharray="4 3"/>'
               f'<line x1="{(X(P_) + X(P_ + 1)) / 2:.1f}" x2="{(X(P_) + X(P_ + 1)) / 2:.1f}" y1="6" y2="{Hd - 26}" stroke="var(--turf)" stroke-dasharray="4 3"/>')
        for n_, r in enumerate(sorted(s.R, key=lambda r: avg[r])):
            y = 22 + n_ * rowh; pos_ = sorted(okS.get(r, set(range(1, nS + 1)))) or [1, nS]
            sv += (f'<g class="sdr" data-r="{r}"><rect x="0" y="{y - 15}" width="{Wd}" height="30" fill="transparent"/><text x="{L0 - 10}" y="{y + 5}" text-anchor="end" font-size="14" font-weight="600" fill="var(--ink)">{E(s_.M[r])}</text>'
                   f'<line x1="{X(pos_[0]):.1f}" x2="{X(pos_[-1]):.1f}" y1="{y}" y2="{y}" stroke="#C9D1DE" stroke-width="8" stroke-linecap="round"/>'
                   + "".join(f'<rect x="{X(k + 1) - 9:.1f}" y="{y - 4}" width="18" height="8" rx="4" fill="var(--flag)" opacity="{min(1, v * 1.8):.2f}"/>' for k, v in enumerate(out[r]["dist"]) if v >= 0.01)
                   + f'<circle cx="{X(avg[r]):.1f}" cy="{y}" r="7" fill="var(--turf)" stroke="#fff" stroke-width="2"><title>{E(s_.M[r])}: forecast seed {avg[r]:.1f}, possible {pos_[0]} to {pos_[-1]}</title></circle>'
                   f'<text x="{X(avg[r]):.1f}" y="{y - 11}" text-anchor="middle" font-size="12" font-weight="800" fill="var(--turf)">{avg[r]:.1f}</text></g>')
        seedchart = (f'<svg viewBox="0 0 {Wd} {Hd}" width="100%" style="max-width:700px;display:block;margin:0 auto" role="img" aria-label="Average seed and possible range for every team">{sv}</svg>'
                     f'<p class="note">Dot = forecast seed. Gray bar = every seed still mathematically possible; gold = where the simulations land most. Gold dashed line = bye cut, navy = playoff cut. Tap a team to isolate it.</p>')
        P["playoffs.html"] = page(f"Playoffs, Super League {yr}", s_.head("Playoffs", "") +
            f'<main class="wrap"><section><h2>If the season ended today</h2><div class="zkey"><span>Top {B_} get a bye, top {P_} make it</span></div>{bracket}</section>'
            f'<section><h2>Title odds</h2><div class="scroll wide"><table class="todds"><thead><tr><th></th><th>Team</th><th class="c">Record</th><th>Title</th><th>Final</th><th><span class="nmf">Semifinals</span><span class="nms">Semis</span></th><th>Bye</th><th><span class="nmf">Playoffs</span><span class="nms">PO</span></th></tr></thead><tbody>{orows}</tbody></table></div></section>'
            f'<section><h2>Odds tracker</h2><p class="intro">Everyone\'s chances through the season, play by play during each week\'s games. Dots mark the end of each week. Tap a team or its line to isolate it, and tap a point for the number.</p><div class="ohk rtog chips" role="group" aria-label="Odds"><button type="button" data-k="0" aria-pressed="true">Playoffs</button><button type="button" data-k="1" aria-pressed="false">Bye</button><button type="button" data-k="2" aria-pressed="false">Title</button><button type="button" data-k="3" aria-pressed="false">Forecast seed</button></div><div class="panel"><div class="ohc"></div><div class="ohl"></div></div></section>'
            f'<section class="seedsec"><h2>Seed chances</h2><div class="rtog chips sdt" role="group" aria-label="View"><button type="button" data-v="t" aria-pressed="true">Table</button><button type="button" data-v="c" aria-pressed="false">Chart</button></div>'
            f'<div class="sdv" data-v="t"><div class="scroll wide"><table class="seedgrid"><thead><tr><th>Team</th>' + "".join(f'<th class="c">{k}</th>' for k in range(1, len(s.R) + 1)) + f'<th class="c">Forecast</th></tr></thead><tbody>{grid}</tbody></table></div>'
            f'<p class="note"><span class="impk">×</span> = mathematically impossible, whatever happens in the games left. Forecast = each seed weighted by its chance, so 50% 1st and 50% 2nd is 1.5.</p></div>'
            f'<div class="sdv panel" data-v="c" hidden>{seedchart}</div></section>'
            f'<section><h2>Playoff history</h2><div class="recs"><div class="rec"><span class="k">Champions</span><span class="v">None yet</span><span class="w">First postseason: Weeks {pw0}-{pw0 + 2}, {yr}</span></div>'
            f'<div class="rec"><span class="k">Playoff appearances</span><span class="v">None yet</span><span class="w">{yr} field set after Week {s.L["regular_season_weeks"]}</span></div></div></section>'
            f'</main>{s_.footer(pre)}', pre, "playoffs")
        P["schedule.html"] = page(f"Schedule, Super League {yr}", s_.head("Schedule", "Pick a week. Tap a game for the box score or preview.") +
                                  f'<main class="wrap"><section>{F["schedule"]}</section></main>{s_.footer(pre)}', pre, "schedule")
        # draft page: redraft by production, no slot curve
        drows, dteam, _ = s_.draft_vals(); T_ = len(s.R)
        first = {x["slot"]: x["r"] for x in drows if x["rd"] == 1}
        rounds = max(x["rd"] for x in drows)
        cellmap = {(x["rd"], x["r"]): x for x in drows}
        sp = lambda v: f"+{v}" if v > 0 else str(v)
        cap = max(30.0 * s.wpp, float(np.percentile([abs(x["gap"]) for x in drows], 95)))   # scale tops out around the 95th percentile
        def dcell(x):
            v = x["gap"]; t = max(-1.0, min(1.0, v / cap))
            hi = (31, 122, 82) if t > 0 else (182, 65, 46); lo = (255, 255, 255)        # white at 0, deep green / deep red at the extremes
            rgb = tuple(round(lo[c] + (hi[c] - lo[c]) * abs(t) ** 0.8) for c in range(3))
            ink = "#fff" if abs(t) > 0.62 else "var(--ink)"
            return (f'<td class="dc" style="background:rgb{rgb};color:{ink}"><span class="pk" style="color:inherit;opacity:.75">{x["rd"]}.{x["slot"]:02d}</span><b><a class="pn" href="{pre}player/{x["i"]}.html" style="color:inherit">{s_.pa(x["i"], nm(x["i"]))}</a></b>'
                    f'<small>{v:+.2f}</small></td>')
        board = "".join(f'<tr><th class="rk">{rd}</th>' + "".join(dcell(cellmap[(rd, first[k])]) if (rd, first[k]) in cellmap else "<td></td>" for k in range(1, T_ + 1)) + "</tr>" for rd in range(1, rounds + 1))
        bhead = "".join(f'<th class="c"><a class="tn" href="{s_.turl(first[k], pre)}">{s_.logo(first[k], pre, "lgs")}<br>{E(s_.M[first[k]])}</a></th>' for k in range(1, T_ + 1))
        pkl = lambda x: f'{s_.pa(x["i"], nm(x["i"]))} <span class="muted">({x["rd"]}.{x["slot"]:02d})</span>'
        rank_rows = "".join(f'<tr><td class="rk">{j}</td><td>{s_.tl(r, pre)}</td><td class="r big {"pos" if v > 0 else "neg"}">{v:+.2f}</td><td class="r">{s_._dtotal[r]:.2f}</td>'
                            f'<td>{pkl(max((x for x in drows if x["r"] == r), key=lambda x: x["gap"]))}</td><td>{pkl(min((x for x in drows if x["r"] == r), key=lambda x: x["gap"]))}</td></tr>'
                            for j, (r, v) in enumerate(sorted(dteam.items(), key=lambda kv: -kv[1]), 1))
        def pick_list(xs):
            return "".join(f'<tr><td class="rk">{j}</td><td>{s_.logo(x["r"], pre, "lgs")}</td><td><b>{s_.plink(x["i"], pre)}</b><small>Taken {x["rd"]}.{x["slot"]:02d}, now {s_.now_str(x)}, {E(s_.TN(x["r"]))}</small></td>'
                           f'<td class="r big {"pos" if x["gap"] > 0 else "neg" if x["gap"] < 0 else ""}">{x["gap"]:+.2f}</td></tr>' for j, x in enumerate(xs, 1))
        dpick = {x["i"]: x for x in drows}; started_for = defaultdict(set)
        for w in s.weeks:
            for x_, d in s.W[w].items():
                for i, _ in d["S"]: started_for[i].add(x_)
        def rd_row(rk_, i, v, g):
            x = dpick.get(i); spot = f'{(rk_ - 1) // T_ + 1}.{(rk_ - 1) % T_ + 1:02d}'
            how = (f'{E(s_.TN(x["r"]))}, taken {x["rd"]}.{x["slot"]:02d}' if x else (f'Undrafted, started for {len(started_for[i])} teams' if len(started_for[i]) > 2 else f'Undrafted, started for {E(" / ".join(s_.TN(t) for t in sorted(started_for[i])))}'))
            mv = (f'<td class="r {"pos" if x["gap"] > 0 else "neg" if x["gap"] < 0 else "muted"}">{x["gap"]:+.2f}</td>' if x else '<td class="r muted">pickup</td>')
            return f'<tr><td class="rk">{spot}</td><td><b>{s_.plink(i, pre)}</b><small>{how}</small></td><td class="r">{g}</td><td class="r big">{v:+.2f}</td>{mv}</tr>'
        redraft_rows = "".join(rd_row(*t) for t in s_._pool[:30])
        explain = (f'''<section class="explain"><details><summary><h2>How it works</h2></summary><div class="steps">
<div><b>1. WAR</b><p>Wins above replacement: fantasy points scored minus what a replacement-level free agent at the position scores ({E(", ".join(f"{p} {v:.1f}" for p, v in s.repl["val"].items()))} a week), turned into wins (about {s.ppw:.0f} points = 1 win). Only weeks the player was in a Super League starting lineup count, for any team.</p></div>
<div><b>2. Redraft</b><p>Every player who has started in our league, drafted or picked up off waivers, sorted by WAR. That order is where each would go if we redrafted today. Past pick {len(drows)} means he'd go undrafted. Ties take the lower spot.</p></div>
<div><b>3. The bar for each pick</b><p>The average WAR of the players ranked around that spot in the redraft (five either side). Taken 11th: you're measured against what picks 6 through 16 of the redraft actually produced, not one player.</p></div>
<div><b>4. Grades</b><p>Pick grade = his WAR minus that bar. Team grade = all its pick grades added up and compared with the league's average draft, so where you picked is accounted for.</p></div></div></details></section>''')
        P["draft.html"] = page(f"Draft, Super League {yr}", s_.head("Draft", f"Every {yr} pick, re-ranked by what the players have actually produced in our lineups.") +
                               f'<main class="wrap"><section><h2>Draft grades</h2>'
                               f'<div class="scroll"><table><thead><tr><th></th><th>Team</th><th class="r">Draft grade</th><th class="r">Total WAR</th><th>Best pick</th><th>Worst pick</th></tr></thead><tbody>{rank_rows}</tbody></table></div></section>'
                               f'<div class="grid2"><section><h2>Biggest steals</h2><p class="intro">Pick grade: his WAR minus the bar for his draft spot.</p><table class="pt"><tbody>{pick_list(sorted(drows, key=lambda x: -x["gap"])[:10])}</tbody></table></section>'
                               f'<section><h2>Biggest busts</h2><p class="intro">Pick grade: his WAR minus the bar for his draft spot.</p><table class="pt"><tbody>{pick_list(sorted(drows, key=lambda x: x["gap"])[:10])}</tbody></table></section></div>'
                               f'<section><h2>Redraft top 30</h2><p class="intro">Waiver and free-agent pickups included.</p><div class="scroll"><table class="rdraft"><thead><tr><th>Redraft</th><th>Player</th><th class="r">Starts</th><th class="r">WAR</th><th class="r">Pick grade</th></tr></thead><tbody>{redraft_rows}</tbody></table></div></section>'
                               f'<section class="dbwide"><h2>Draft board</h2><p class="intro">Pick grade, from deep red to white to deep green.</p><div class="scroll"><table class="grid dboard"><thead><tr><th>Rd</th>{bhead}</tr></thead><tbody>{board}</tbody></table></div></section>'
                               f'{explain}</main>{s_.footer(pre)}', pre, "draft")
        # all-time head-to-head grid
        H = defaultdict(lambda: [0, 0])
        for w in s.weeks:
            for a, b in s.G[w]["pairs"]:
                sa_, sb_ = round(s.G[w]["scores"][a], 2), round(s.G[w]["scores"][b], 2)
                if sa_ == sb_: H.setdefault(("T", a, b), [0])[0] += 1; H.setdefault(("T", b, a), [0])[0] += 1; continue
                wi, lo = (a, b) if sa_ > sb_ else (b, a)
                H[(wi, lo)][0] += 1; H[(lo, wi)][1] += 1
        order_ = sorted(s.R, key=lambda r: s_.M[r])
        head_ = "".join(f'<th class="c"><a class="tn" href="{s_.turl(c, pre)}">{E(s_.M[c])}</a></th>' for c in order_)
        def cell(a, b):
            if a == b: return '<td class="c muted">·</td>'
            w_, l_ = H[(a, b)]; t_ = H.get(("T", a, b), [0])[0]
            if not w_ + l_ + t_: return '<td class="c muted">0-0</td>'
            return f'<td class="c {"hw" if w_ > l_ else "hl" if l_ > w_ else ""}">{w_}-{l_}{"-" + str(t_) if t_ else ""}</td>'
        grid = "".join(f'<tr><th><a class="tl" href="{s_.turl(a, pre)}">{s_.logo(a, pre, "lgs")}<b>{E(s_.M[a])}</b></a></th>' + "".join(cell(a, b) for b in order_) + f'<td class="r big">{sum(H[(a, b)][0] for b in s.R)}-{sum(H[(a, b)][1] for b in s.R)}</td></tr>' for a in order_)
        import json as _jc
        RSW = s.L.get("regular_season_weeks", 14); NG = Counter(); HI = {}; LO = {}
        for w in s.weeks:
            for r in s.R:
                if w > RSW: continue
                NG[r] += 1; sc = s.G[w]["scores"][r]; HI[r] = max(HI.get(r, 0), sc); LO[r] = min(LO.get(r, 9e9), sc)
        Tt = s.ties()
        CD = {"t": {str(r): dict(n=s_.TN(r), m=s_.M[r], u="#/team/" + s_.M[r],
                                 w=int(s_.W0[r] - Tt[r] / 2), l=NG[r] - int(s_.W0[r] - Tt[r] / 2) - Tt[r], ti=Tt[r], pf=round(s_.PF[r], 2), pa=round(s_.PA[r], 2), g=NG[r],
                                 hi=round(HI.get(r, 0), 2), lo=round(LO.get(r, 0), 2), pw=0, pl=0, pa_=0, ch=0, sz=1) for r in s.R},
              "g": [[w, a, b, round(s.G[w]["scores"][a], 2), round(s.G[w]["scores"][b], 2), "#/" + s_.gurl(w, a, b, "").replace(".html", ""), 1 if w > RSW else 0]
                    for w in s.weeks for a, b in s.G[w]["pairs"]]}
        ropt = "".join(f'<option value="{r}">{E(s_.M[r])}</option>' for r in order_)
        cmp_ = (f'<section class="cmp"><h2>Compare two managers</h2><div class="cmpbar"><select class="cmpa" aria-label="First manager">{ropt}</select><span class="vsx">vs</span>'
                f'<select class="cmpb" aria-label="Second manager">{ropt}</select></div><div class="cmpo"></div>'
                f'<script type="application/json" class="cmpdata">{_jc.dumps(CD, separators=(",", ":"))}</script></section>')
        P["h2h.html"] = page(f"Head to head, Super League {yr}", s_.head("Head to head", "Every manager against every other, all time. Read across a row: that manager's record against each column.") +
                             f'<main class="wrap">{cmp_}<section><h2>Regular season</h2><div class="scroll"><table class="grid h2hg"><colgroup><col class="h2n">{"<col>" * len(order_)}<col class="h2t"></colgroup><thead><tr><th></th>{head_}<th class="r">Total</th></tr></thead><tbody>{grid}</tbody></table></div>'
                             f'<p class="note">Green means they lead the series, red means they trail.</p></section>'
                             f'<section><h2>Playoffs</h2><p class="intro">No playoff games yet. The first postseason starts in Week {s.L["playoff_week_start"]}, and every playoff meeting will show up here and on each team page.</p></section></main>{s_.footer(pre)}', pre, "h2h")
        P["races.html"] = page(f"Awards, Super League {yr}", s_.head("Awards", f"Every season award race through Week {s.last}, then the awards already handed out.") +
                               f'<main class="wrap">{F["races"]}<h2 class="pgh2">Awards handed out</h2>{F["awards"]}</main>{s_.footer(pre)}', pre, "races")
        P["awards.html"] = page(f"Awards, Super League {yr}", s_.head("Awards", "Awards that have actually been handed out.") +
                                f'<main class="wrap">{F["awards"]}</main>{s_.footer(pre)}', pre, "awards")
        P["trades.html"] = page(f"Trades, Super League {yr}", s_.head("Trades", "Who has come out ahead on every deal so far.") +
                                f'<main class="wrap">{F["trades"]}</main>{s_.footer(pre)}', pre, "trades")
        P["excitement.html"] = page(f"Excitement, Super League {yr}", s_.head("Excitement", "Every game ranked, from instant classic to snoozer.") +
                                    f'<main class="wrap">{s_.exc_page(pre)}</main>{s_.footer(pre)}', pre, "races")
        P["transactions.html"] = page(f"Transactions, Super League {yr}", s_.head("Transactions", "Every trade, claim and free-agent move, newest first.") +
                                      f'<main class="wrap">{s_.tx_page(pre)}</main>{s_.footer(pre)}', pre, "transactions")
        P["analyzer.html"] = page(f"Trade analyzer, Super League {yr}", s_.head("Trade analyzer", "Build any trade and see what it does to both teams' rest of the season.") +
                                  '<main class="wrap"><div id="ta"></div></main>' + s_.footer(pre), pre, "analyzer")
        import json as _j
        RD = s_.records_data()
        opts = '<option value="L">Whole league</option>' + "".join(f'<option value="{r}">{E(s_.M[r])}</option>' for r in sorted(s.R, key=lambda r: s_.M[r].lower()))
        ctrl = (f'<div class="rbar"><div class="wrap"><nav class="rbooks" aria-label="Record book">'
                f'<button type="button" data-b="team" aria-pressed="true">Team</button><button type="button" data-b="player" aria-pressed="false">Players</button><button type="button" data-b="mgr" aria-pressed="false">Managers</button></nav>'
                f'<div class="rfilt"><label><span class="sr">Whose records</span><select class="rscope">{opts}</select></label>'
                f'<div class="rper" role="group" aria-label="Period"><button type="button" data-v="all" aria-pressed="true">All-time</button><button type="button" data-v="{yr}" aria-pressed="false">{yr}</button></div></div></div></div>')
        hero = (f'<section class="field rhero"><div class="wrap"><i class="brandlogo rbig" aria-hidden="true"></i><div><h1>Record Book</h1>'
                f'<p class="lede">Super League, since {yr}</p></div></div></section>')
        P["records.html"] = page(f"Record Book, Super League", hero + ctrl +
                                 f'<main class="book"><div class="wrap"><div class="rgroups"></div></div></main>'
                                 f'<script type="application/json" class="rdata">{_j.dumps(RD, separators=(",", ":")).replace("</", "<\\/")}</script>{s_.footer(pre)}', pre, "records")
        dir_rows = "".join(f'<a href="{s_.turl(r, pre, True)}">{s_.logo(r, pre, "")}<b>{E(s_.M[r])}</b><small>{E(s_.TN(r))}</small></a>'
                           for r in sorted(s.R, key=lambda r: s_.M[r].lower()))
        PD = s_.players_data()
        plist = sorted(PD.items(), key=lambda kv: (-(kv[1]["sea"][str(yr)]["s"][1]), kv[1]["n"]))
        N_ = len(s.R); MC_ = s_.mvp_counts()
        def prow_(i, d):
            S_ = d["sea"][str(yr)]; st = S_["s"]; dd = S_["d"]
            per = st[1] / st[0] if st[0] else 0
            pick = (dd[0] - 1) * N_ + dd[1] if dd else 999
            wn = sum(1 for x in S_["w"] if x[2] and x[6] == 1); ls = sum(1 for x in S_["w"] if x[2] and x[6] == 0)
            wp_ = wn / (wn + ls) if wn + ls else 0
            rkey = round(wp_ + (1 if wp_ >= 0.5 else -1) * (wn + ls) * 1e-4, 6)   # win %, then more starts = better at .500 or above, worse below
            q = E((d["n"] + " " + d["p"] + " " + d["t"] + " " + d["tf"] + " " + (s_.TN(d["o"]) + " " + s_.M[d["o"]] if d["o"] else "free agent")).lower())
            cell = lambda v, txt, cls="r", na=False: f'<td class="{cls}" data-v="{v}"{" data-na=1" if na else ""}>{txt}</td>'
            return (f'<tr data-id="{i}" data-q="{q}" data-pos="{d["p"]}" data-own="{1 if d["o"] else 0}">'
                    f'<td data-v="{E(d["n"].lower())}"><a class="pn" href="player/{i}.html"><b>{E(d["n"].rsplit(" ", 1)[0] + " ") if " " in d["n"] else ""}<span class="nw">{E(d["n"].rsplit(" ", 1)[-1])}{f'<i class="nfl N{d["t"]} pnl" aria-hidden="true"></i>' if d["t"] in NFL_NICK else ""}</span></b></a><small class="psub">{E(d["p"])}, {E(s_.TN(d["o"])) if d["o"] else "free agent"}</small></td>{cell(d["p"], E(d["pd"].replace(", ", "/")), "c")}{cell(d["t"], s_.nl(d["t"]), "c")}'
                    f'{cell(E(s_.TN(d["o"]).lower()) if d["o"] else "zzz", s_.tn(d["o"], pre) if d["o"] else "<span class=muted>FA</span>", "")}'
                    f'{cell(st[0], st[0])}{cell(rkey, f"{wn}-{ls}" if wn + ls else "-", "c", na=not (wn + ls))}{cell(st[1], fp(st[1]), "r big")}{cell(st[7], fp(st[7]) if st[7] else "-", na=not st[7])}{cell(st[8], fp(st[8]) if st[8] else "-", na=not st[8])}{cell(st[9], fp(st[9]) if st[9] else "-", na=not st[9])}{cell(st[10], f"+{st[10]:.1f}" if st[10] else "-", na=not st[10])}{cell(round(per, 2), fp(round(per, 2)) if st[0] else "-", na=not st[0])}{cell(st[3], f"{st[3]:+.2f}" if st[0] else "-", na=not st[0])}{cell(st[4], f"{st[4]:+.1f}" if st[0] else "-", na=not st[0])}{cell(round(st[4] / st[0], 2) if st[0] else 0, f"{st[4] / st[0]:+.1f}" if st[0] else "-", na=not st[0])}{cell(st[12], f"{st[12]:+.2f}" if wn + ls else "-", na=not (wn + ls))}{cell(st[13], f"{st[13]:+.1f}" if wn + ls else "-", na=not (wn + ls))}{cell(MC_[0][i], MC_[0][i] or "-")}{cell(MC_[2][i], MC_[2][i] or "-")}'
                    f'{cell(-pick, f"{dd[0]}.{dd[1]:02d}" if dd else "-", na=not dd)}{cell(d["wr"], d["wr"])}{cell(len(S_["irw"]), len(S_["irw"]) or "-")}</tr>')
        # column order by importance: who and where, production, value, results, then the bookkeeping
        PORD = [0, 1, 2, 3, 6, 11, 12, 13, 14, 4, 5, 15, 16, 17, 18, 7, 8, 9, 10, 19, 20, 21]
        def preorder(row):
            i0 = row.index("<td"); head, cells = row[:i0], row[i0:-5].split("<td")[1:]
            return head + "".join("<td" + cells[j] for j in PORD) + "</tr>"
        prow = "".join(preorder(prow_(i, d)) for i, d in plist)
        heads = [("Player", "s"), ("Pos", "s"), ("NFL", "s"), ("Current team", "s"), ("Starts", "n"), ("Record", "n"), ("Pts started", "n"), ("Total pts", "n"), ("Bench pts", "n"), ("FA pts", "n"), ("Left on bench", "n"), ("PPG", "n"), ("WAR", "n"), ("PAA", "n"), ("PAA/start", "n"), ("Win Impact", "n"), ("Support", "n"), ("Week MVPs", "n"), ("Game MVPs", "n"), ("Drafted", "n"), ("Wks rostered", "n"), ("Wks on IR", "n")]
        thead = "".join(f'<th class="{"" if o in (0, 3) else "c" if o in (1, 2, 5) else "r"} sortable"{" aria-sort=descending" if o == 6 else ""} data-k="{k}" data-t="{heads[o][1]}" tabindex="0" role="button">{heads[o][0]}</th>' for k, o in enumerate(PORD))
        filt = ('<div class="pfilt"><div class="chips">' + "".join(f'<a href="#" class="pf{" nx" if p_ == "All" else ""}" data-pos="{p_}">{p_}</a>' for p_ in ["All", "QB", "RB", "WR", "TE", "K", "DEF"]) + '</div>'
                '<select class="pown" aria-label="Roster status"><option value="all">Everyone</option><option value="1">On a roster</option><option value="0">Free agents</option></select></div>')
        P["players.html"] = page(f"Players, Super League {yr}", s_.head("Players", "Everyone who has been on a Super League roster this season.") +
                                 f'<main class="wrap"><section class="pbar-top"><div class="rtog chips pmode" role="group" aria-label="View"><button type="button" data-m="season" aria-pressed="true">Season</button><button type="button" data-m="week" aria-pressed="false">By week</button></div></section>'
                                 f'<section class="pm-season"><input class="psearch" type="search" placeholder="Search players, positions, NFL or fantasy teams" aria-label="Search players">'
                                 f'{filt}<div class="scroll"><table class="ptable"><thead><tr>{thead}</tr></thead><tbody>{prow}</tbody></table></div>'
                                 f'<p class="note">Total pts = every point he scored this season, started or not. It splits into Pts started, Bench pts (on a Super League bench, IR weeks left out) and FA pts (on no roster). Left on bench = points his teams missed by benching him in weeks he should have started.</p></section>'
                                 f'<section class="pm-week" hidden><div class="wkctl"><select class="wk-w" aria-label="Week">{"".join(f'<option value="{w}"{" selected" if w == s.weeks[-1] else ""}>Week {w}</option>' for w in reversed(s.weeks))}</select>'
                                 f'<select class="wk-s" aria-label="Status"><option value="all">Everyone</option><option value="2">Started</option><option value="1">Bench</option><option value="3">IR</option><option value="0">Free agents</option></select>'
                                 f'<div class="chips wk-p">' + "".join(f'<a href="#" class="pf{" nx" if p_ == "All" else ""}" data-pos="{p_}">{p_}</a>' for p_ in ["All", "QB", "RB", "WR", "TE", "K", "DEF"]) + '</div></div>'
                                 f'<div class="scroll"><table class="wktab" style="min-width:0"><thead><tr><th class="c">#</th><th class="srt" data-k="n">Player</th><th class="c srt" data-k="p">Pos</th><th class="c">NFL</th><th class="srt" data-k="t">Team</th><th class="c srt" data-k="st">Status</th><th class="r srt" data-k="pts" aria-sort="descending">Pts</th><th class="r srt" data-k="e">PAA</th><th class="r srt" data-k="war">WAR</th><th class="wst">Stats</th></tr></thead><tbody></tbody></table></div>'
                                 f'<p class="note">PAA and WAR are what that week\'s points were worth, whether or not he started. Free agents are players on no roster that week.</p></section></main>{s_.footer(pre)}', pre, "players")
        P["teams.html"] = page(f"Teams, Super League {yr}", s_.head("Teams", "Every manager, A to Z. Each page has their all-time numbers, with a page for every season.") +
                               f'<main class="wrap"><section><div class="teams">{dir_rows}</div></section>{s_.war_pos_table(pre)}</main>{s_.footer(pre)}', pre, "teams")
        return P


    # ------------------------------------------------------------------ team pages
    def team(s_, r):
        s = s_.s; M = s_.M; nm = s_.pn; out = s_.SIM[0]; n = s_.n; wk0 = s.nxt; yr = s_.yr; pre = "../"
        R = s.repl["val"]; wpp = s.wpp; o = out[r]; T = s_.T
        res = []
        for w in s.weeks:
            a, b = s_.game_of[(w, r)]; op = b if r == a else a
            me, th = s.G[w]["scores"][r], s.G[w]["scores"][op]
            res.append(dict(w=w, op=op, me=me, th=th, win=me > th, med=float(np.median(list(s.G[w]["scores"].values()))),
                            ap=sum(me > s.G[w]["scores"][x] for x in s.R if x != r)))
        PA_ = sum(x["th"] for x in res)
        luck_rows = [(x["w"], x["win"], x["ap"] / (len(s.R) - 1), dict(op=s_.TN(x["op"]), me=x["me"], th=x["th"], ap=x["ap"], n=len(s.R) - 1)) for x in res]
        lk = s_.W0[r] - s_.xw[r]
        lrank = sorted(s.R, key=lambda x: -(s_.W0[x] - s_.xw[x])).index(r) + 1
        # chart
        hi = max(max(x["me"], x["th"]) for x in res) * 1.08; Wd, Hd = 640, 200; bw = Wd / len(res); bars = ""
        for k, x in enumerate(res):
            h = x["me"] / hi * (Hd - 24); X = k * bw + bw * 0.18; u = s_.gurl_r(x["w"], r, pre)
            bars += (f'<a href="{u}"><rect x="{X:.1f}" y="{Hd - 20 - h:.1f}" width="{bw * 0.64:.1f}" height="{h:.1f}" rx="3" fill="{"var(--win)" if x["win"] else "var(--loss)"}"><title>Week {x["w"]}: {fc(x["me"])} vs {fc(x["th"])}</title></rect></a>'
                     f'<rect x="{X - 2:.1f}" y="{Hd - 20 - x["med"] / hi * (Hd - 24):.1f}" width="{bw * 0.64 + 4:.1f}" height="2" fill="var(--ink)" opacity=".55"/>'
                     f'<text x="{X + bw * 0.32:.1f}" y="{Hd - 5}" text-anchor="middle" font-size="11" fill="var(--mute)">W{x["w"]}</text>'
                     f'<text x="{X + bw * 0.32:.1f}" y="{Hd - 24 - h:.1f}" text-anchor="middle" font-size="10" fill="var(--mute)">{fc(x["me"])}</text>')
        chart = f'<div class="panel"><svg viewBox="0 0 {Wd} {Hd}" width="100%" role="img" aria-label="Weekly scores">{bars}</svg><p class="note" style="margin:6px 0 0">Bar = score (green win, red loss), tap one for the box score. The dark tick is the league median that week.</p></div>'
        # schedule (with each week's team MVP / LVP)
        allpm = s_.starts_pm(s); wml = {}
        for w in s.weeks:
            c = [x for x in allpm if x["w"] == w and x["r"] == r]
            if c: wml[w] = (max(c, key=lambda x: x["pm"]), min(c, key=lambda x: x["pm"]))
        pl = lambda x: f'<b class="nw">{s_.pa(x["i"], nm(x["i"]))}</b><small>{fp(x["p"])} pts, {x["pm"]:+.1f}</small>'
        sched = []
        for x in res:
            mv_, lv_ = wml.get(x["w"], (None, None))
            sched.append(f'<tr><td class="c">{x["w"]}</td><td>{s_.tl(x["op"], pre)}</td><td class="c"><b class="{"pos" if x["win"] else "neg"}">{"W" if x["win"] else "L"}</b></td>'
                         f'<td class="r">{fp(x["me"])} - {fp(x["th"])}</td><td>{pl(mv_) if mv_ else ""}</td><td class="r">{x["ap"]} of {len(s.R) - 1}</td><td class="r"><a class="go gbt" href="{s_.gurl_r(x["w"], r, pre)}">Box score</a></td></tr>')
        for w in s_.weeks_left:
            x = s_.lev[(w, r)]; A, B = s_.upcoming(w, r), s_.upcoming(w, x["opp"])
            sched.append(f'<tr class="fut"><td class="c">{w}</td><td>{s_.tl(x["opp"], pre)}</td><td class="c">{pct(s_.win_p(A, B))}<small class="swg">{(x["po_w"] - x["po_l"]) * 100:.0f}% playoff swing</small></td>'
                         f'<td class="r">proj {A[0]:.1f} - {B[0]:.1f}</td><td></td><td></td><td class="r"><a class="go gbt" href="{s_.gurl_r(w, r, pre)}">Preview</a></td></tr>')
        sched_t = (f'<div class="scroll wide"><table><thead><tr><th class="c">Wk</th><th>Opponent</th><th class="c">Result / Win %</th><th class="r">Score</th><th>Team MVP</th>'
                   f'<th class="r">Teams outscored</th><th></th></tr></thead><tbody>{"".join(sched)}</tbody></table></div>'
                   f'<p class="note">Team MVP: best start that week vs the median starter at the position. Teams outscored: how many of the other {len(s.R) - 1} teams they beat on points that week. Playoff swing (upcoming games): playoff odds if they win minus if they lose.</p>')
        # roster
        st = defaultdict(lambda: [0, 0.0, 0.0])
        for w in s.weeks:
            for i, p in s.W[w][r]["S"]:
                if i != "0": st[i][0] += 1; st[i][1] += p; st[i][2] += (p - R.at(w, s.pos(i))) * wpp
        for i, p in s_.live_final(r):
            st[i][0] += 1; st[i][1] += p; st[i][2] += (p - R.at(s.nxt, s.pos(i))) * wpp
        nxt = s_.TEAM.get((wk0, r)); lineup = set(nxt["lineup"]) if nxt else set()
        po = {p: k for k, p in enumerate(["QB", "RB", "WR", "TE", "K", "DEF"])}
        pj = lambda i: s_.proj(i, wk0)[0] if (s_.proj and nxt) else 0
        ros = sorted(s.rost[r], key=lambda i: (i not in lineup, po.get(s.pos(i), 9), -pj(i)))
        rrows = []
        for i in ros:
            P = s.PL.get(i, {}); inj = P.get("inj"); g, pts_, war = st.get(i, [0, 0, 0])
            rrows.append(f'<tr class="{"" if i in lineup else "bn"}"><td><b>{s_.pa(i, nm(i))}</b><small>{s_.nl(P.get("team") if i.isdigit() else i)}{inj_tag(inj)}</small></td>'
                         f'<td class="c">{"Start" if i in lineup else "Bench"}</td><td class="r">{pj(i):.1f}</td><td class="r">{g}</td><td class="r">{(pts_ / g) if g else 0:.1f}</td><td class="r {"pos" if war > 0 else "neg" if war < 0 else ""}">{war:+.2f}</td></tr>')
        for a in (nxt["adds"] if nxt else []):
            rrows.append(f'<tr class="pick"><td><b>{s_.pa(a, nm(a))}</b><small>Projected pickup</small></td><td class="c">Start</td><td class="r">{pj(a):.1f}</td><td class="r">—</td><td class="r">—</td><td class="r">—</td></tr>')
        roster_t = (f'<div class="scroll"><table><thead><tr><th>Player</th><th class="c">Wk {wk0}</th><th class="r">Proj</th><th class="r">GS here</th><th class="r">PPG here</th><th class="r" title="Wins above replacement while starting for this team">WAR here</th></tr></thead><tbody>{"".join(rrows)}</tbody></table></div>'
                    f'<p class="note">Start/Bench = the model\'s best lineup for Week {wk0} (<a class="go" href="{s_.gurl_r(wk0, r, pre)}">see the matchup</a>). GS, PPG and WAR only count starts for this team.</p>')
        contrib = sorted(st.items(), key=lambda kv: -kv[1][2])
        top = "".join(f'<tr><td class="rk">{k}</td><td><b>{s_.pa(i, nm(i))}</b>{"" if i in s.rost[r] else "<small>no longer on team</small>"}</td><td class="r">{v[0]} GS</td><td class="r">{v[1]:.1f}<small>{v[1] / max(v[0], 1):.1f} avg</small></td><td class="r big">{v[2]:+.2f}</td></tr>' for k, (i, v) in enumerate(contrib[:8], 1))
        tr = []
        for t in s.trade_res:
            for x in t["sides"]:
                if x["r"] != r: continue
                wins = x["pts"] / s.ppw
                tr.append(f'<tr><td class="c">{t["w"]}</td><td>{" ".join(s_.tl(y["r"], pre) for y in t["sides"] if y["r"] != r)}</td><td>{", ".join(s_.pa(i, nm(i)) for i in x["got"])}</td><td>{", ".join(s_.pa(i, nm(i)) for i in x["gave"])}</td><td class="r {"pos" if wins > 0 else "neg"}">{wins:+.2f}</td></tr>')
        for t in s.trades:
            if t["vetoed"] and r in t["sides"]:
                got, gave = t["sides"][r]
                tr.append(f'<tr class="bn"><td class="c">{t["w"]}</td><td>{" ".join(s_.tl(x, pre) for x in t["sides"] if x != r)}</td><td>{", ".join(s_.pa(i, nm(i)) for i in got)}</td><td>{", ".join(s_.pa(i, nm(i)) for i in gave)}</td><td class="r"><b>Vetoed</b></td></tr>')
        trades_t = (f'<div class="scroll"><table><thead><tr><th class="c">Wk</th><th>With</th><th>Got</th><th>Gave</th><th class="r">Wins added</th></tr></thead><tbody>{"".join(tr)}</tbody></table></div>') if tr else '<p class="muted">No trades yet.</p>'
        mv = [a for a in s.awards if a["mvp"][1] == r]; lv = [a for a in s.awards if a["lvp"][1] == r]
        tm = Counter(); tlo = Counter()
        for w in s.weeks:
            c = [x for x in allpm if x["w"] == w and x["r"] == r]
            if c: tm[max(c, key=lambda x: x["pm"])["i"]] += 1; tlo[min(c, key=lambda x: x["pm"])["i"]] += 1
        alist = lambda L_, k: ", ".join(f'<a class="go" href="{s_.gurl_r(a["w"], r, pre)}">Wk {a["w"]}</a> {s_.pa(a[k][0], nm(a[k][0]))}' for a in L_) or "—"
        gmc = sorted(((i, c) for (i, r_), c in s_.mvp_counts()[3].items() if r_ == r and c), key=lambda ic: (-ic[1], s.nm(ic[0])))
        topc = gmc[0][1] if gmc else 0; lead = [i for i, c in gmc if c == topc]
        aw = (f'<div class="recs"><div class="rec"><span class="k">League MVPs</span><span class="v">{len(mv)}</span><span class="w">{alist(mv, "mvp")}</span></div>'
              f'<div class="rec"><span class="k">Most game MVPs</span><span class="v">{topc}</span><span class="w">{", ".join(s_.pa(i, nm(i)) for i in lead) or "-"}{" (tied)" if len(lead) > 1 else ""}</span></div></div>'
              + (f'<table class="pt" style="margin-top:12px"><thead><tr><th>Game MVPs <small>best starter in each win, by PAA</small></th><th class="r">Wins</th></tr></thead><tbody>'
                 + "".join(f'<tr><td>{s_.pa(i, nm(i))}</td><td class="r big">{c}</td></tr>' for i, c in gmc) + '</tbody></table>' if gmc else ""))
        h = defaultdict(lambda: [0, 0, 0.0, []])
        for x in res: h[x["op"]][0 if x["win"] else 1] += 1; h[x["op"]][2] += x["me"] - x["th"]; h[x["op"]][3].append(x["w"])
        h2h = ('<thead><tr><th>Opponent</th><th class="c">Regular season</th><th class="c">Playoffs</th><th class="r">Point diff</th><th class="r">Games</th></tr></thead><tbody>' +
               "".join(f'<tr><td>{s_.tl(op, pre)}</td><td class="c big">{h[op][0]}-{h[op][1]}</td><td class="c muted">0-0</td><td class="r {"pos" if h[op][2] > 0 else "neg"}">{h[op][2]:+.1f}</td><td class="r">{" ".join(f"<a class=go href={s_.gurl_r(w, r, pre)}>Wk {w}</a>" for w in h[op][3]) or "<span class=muted>none yet</span>"}</td></tr>'
                       for op in sorted([x for x in s.R if x != r], key=lambda op: (-(h[op][0] - h[op][1]), -h[op][2]))) + "</tbody>")
        dist = o["dist"]; mx = max(dist) or 1
        seeds = "".join(f'<div class="sd"><span class="sb" style="height:{v / mx * 70:.0f}px;background:{"var(--flag)" if k < s.L["playoff_byes"] else "var(--turf)" if k < s.L["playoff_teams"] else "var(--rule)"}"></span><span class="sv">{pct(v)}</span><span class="sk">{k + 1}</span></div>' for k, v in enumerate(dist))
        pw_k, pwx = s_.power[r]; luck = s_.W0[r] - s_.xw[r]; rk = s_.stand.index(r) + 1
        stat = lambda k, v, sub="": f'<div class="stat"><span class="k">{k}</span><span class="v">{v}</span><span class="w">{sub}</span></div>'
        ordn = lambda k: f'{k}{"st" if k % 10 == 1 and k != 11 else "nd" if k % 10 == 2 and k != 12 else "rd" if k % 10 == 3 and k != 13 else "th"}'
        # ---- franchise (all-time; one season so far, built to grow)
        seasons = [yr]
        pick, dv = s_.moves()
        n_tr = sum(1 for t in s.trade_res if any(x["r"] == r for x in t["sides"]))
        n_mv = sum(1 for t in s.tx if t["status"] == "complete" and t["type"] in ("waiver", "free_agent") and r in t["rosters"])
        tr_w = sum(x["pts"] for t in s.trade_res for x in t["sides"] if x["r"] == r) / s.ppw
        fr = (f'<div class="stats">{stat("All-time record", s_.rec_str(r), "regular season")}{stat("Playoff record", "0-0", "first playoffs start Week 15")}'
              f'{stat("Titles", "0", "first one decided Week 17")}{stat("Seasons", str(len(seasons)), "since " + str(seasons[0]))}'
              f'{stat("All-time points", f"{s_.PF[r]:.0f}", f"{s_.PF[r] / n:.1f} per week")}{stat("Trades made", str(n_tr), f"{tr_w:+.1f} wins so far") if n_tr else stat("Trades made", "0", "no trades yet")}'
              f'{stat("Waiver and FA moves", str(n_mv), "completed adds")}{stat("All-time xWins", f"{s_.xw[r]:.1f}", f"luck {s_.W0[r] - s_.xw[r]:+.1f} wins")}{stat("Dead lineup spots", str(sum(len(s_.dead_spots(w, r)) for w in s.weeks)), "empty, on bye or ruled out")}</div>'
              '')
        my_picks = sorted([(i, v) for (x, i), v in pick.items() if x == r], key=lambda kv: -kv[1][0])[:5]
        picks_t = ("".join(f'<tr><td class="rk">{k}</td><td><b>{s_.pa(i, nm(i))}</b><small>{v[1]} start{"" if v[1] == 1 else "s"}, {v[2] / max(v[1], 1):.1f} avg</small></td><td class="r big pos">{v[0]:+.2f}</td></tr>' for k, (i, v) in enumerate(my_picks, 1))
                   or '<tr><td class="muted">No pickups started yet.</td></tr>')
        my_drops = sorted([d for d in dv if d["r"] == r], key=lambda d: -d["war"])[:5]
        drops_t = ("".join(f'<tr><td class="rk">{k}</td><td><b>{s_.pa(d["i"], nm(d["i"]))}</b><small>Cut Week {d["w"]}. Since: {d["pts"]:.1f} pts, {d["g"]} game{"" if d["g"] == 1 else "s"}</small></td><td class="r big {"neg" if d["war"] > 0 else "muted"}">{d["war"]:+.2f}</td></tr>' for k, d in enumerate(my_drops, 1))
                   or '<tr><td class="muted">No drops yet.</td></tr>')
        # ---- lineup report
        g = getattr(s, "grades", {})
        dec_rank = sorted(s.R, key=lambda x: g.get(x, {}).get("dec", 0)).index(r) + 1 if g else None
        left = {}; optsum = {}
        for x in s.R:
            L_ = 0; O_ = 0
            for w in s.weeks:
                d = s.W[w][x]; opt, _ = s.best([(i, s.pos(i), p) for i, p in d["S"] + d["B"] if i != "0"]); L_ += opt - s.G[w]["scores"][x]; O_ += opt
            left[x] = L_; optsum[x] = O_
        bench_rank = sorted(s.R, key=lambda x: -left[x]).index(r) + 1
        eff = s_.PF[r] / optsum[r]
        dec_v = g[r]["dec"] if g else None
        hl = 0
        for x in res:
            d = s.W[x["w"]][r]
            if s.best([(i, s.pos(i), p) for i, p in d["S"] + d["B"] if i != "0"])[0] > x["th"] > x["me"]: hl += 1
        dd_ = [(w, x) for w in s.weeks for x in s_.dead_spots(w, r)]
        lineup = (f'<div class="stats">'
                  f'{stat("Left on bench", f"{left[r]:.1f}", f"pts in hindsight, {ordn(bench_rank)} most")}{stat("Lineup efficiency", pct(eff), "of the perfect lineup")}'
                  f'{stat("Hindsight losses", str(hl), "losses the perfect lineup wins")}{stat("Dead lineup spots", str(len(dd_)), ("empty, on bye or ruled out" + (f", {len({w for w, _ in dd_})} weeks" if dd_ else "")))}</div>')
        # ---- draft class
        war_any = Counter(); gs_any = Counter()
        for w in s.weeks:
            for x, d in s.W[w].items():
                for i, p in d["S"]:
                    if i != "0": war_any[i] += (p - R.at(w, s.pos(i))) * wpp; gs_any[i] += 1
        owner = {i: x for x, v in s.rost.items() for i in v}
        dv_rows, dv_team, _ = s_.draft_vals(); dvp = {x["pick"]: x for x in dv_rows}
        spf = lambda v: f"+{v}" if v > 0 else str(v)
        drank = sorted(s.R, key=lambda x: -dv_team[x]).index(r) + 1
        drows = []
        for d in sorted([d for d in s.draft if d["r"] == r], key=lambda d: d["pick"]):
            i = d["id"]; g_, p_, wr = st.get(i, [0, 0, 0]); now = owner.get(i)
            now_t = ('<span class="muted">Here</span>' if now == r else f'<a class="tn" href="{s_.turl(now, pre)}">{E(s_.TN(now))}</a>') if now else '<span class="muted">Free agent</span>'
            cvd = lambda v: "pos" if v > 0.005 else "neg" if v < -0.005 else "muted"; gp = dvp[d["pick"]]["gap"]
            drows.append(f'<tr class="{"" if now == r else "gone"}"><td class="c">{(d["pick"] - 1) // len(s.R) + 1}.{(d["pick"] - 1) % len(s.R) + 1:02d}</td><td class="pl"><b>{s_.plink(i, pre, s.nm(i))}</b><small>{s.pos(i)}</small><small class="mnow">{"Still here" if now == r else ("Now: " + E(s_.TN(now))) if now else "Now: free agent"}</small></td><td class="xd">{now_t}</td>'
                         f'<td class="r">{g_}</td><td class="r {cvd(wr)}">{wr:+.2f}</td><td class="r xd {cvd(war_any[i])}">{war_any[i]:+.2f}</td><td class="r xd">{s_.now_str(dvp[d["pick"]])}</td><td class="r big {cvd(gp)}">{gp:+.2f}</td></tr>')
        dtot = sum(st.get(d["id"], [0, 0, 0])[2] for d in s.draft if d["r"] == r)
        mine_ = [d for d in s.draft if d["r"] == r]
        draft_t = (f'<div class="stats" style="grid-template-columns:repeat(2,1fr)">{stat("Draft grade", f"{dv_team[r]:+.2f}", f"{ordn(drank)} of {len(s.R)}")}{stat("Picks still here", f"{sum(1 for d in mine_ if owner.get(d[chr(105)+chr(100)]) == r)} of {len(mine_)}")}</div>'
                   f'<div class="scroll"><table class="dcls" style="min-width:0"><thead><tr><th class="c">Pick</th><th>Player</th><th class="xd">Now with</th><th class="r">Starts</th><th class="r">WAR</th><th class="r xd">WAR anywhere</th><th class="r xd">Redraft</th><th class="r">Grade</th></tr></thead><tbody>{"".join(drows)}</tbody></table></div>'
                   f'<p class="note">Starts and WAR are for this team. Grade = WAR above (+) or below (-) what that pick usually produces. Redraft = where he\'d go if every drafted player were re-ranked by production. Gray = no longer here. <a class="go" href="../draft.html">Full draft board</a></p>')
        # ---- moves (waivers, free agents, commissioner)
        mrows = []
        for t in sorted(s.tx, key=lambda t: t["w"]):
            if t["type"] == "trade" or r not in t["rosters"] or t["status"] != "complete": continue
            ad = [nm(i) for i, x in t["adds"] if x == r]; dr = [nm(i) for i, x in t["drops"] if x == r]
            if not ad and not dr: continue
            kind = ("Vetoed trade undone by the commissioner" if id(t) in s_.veto_tx() else
                    {"waiver": "Waiver claim", "free_agent": "Free agent", "commissioner": "Commissioner move"}.get(t["type"], t["type"]))
            mrows.append(f'<tr><td class="c">{t["w"]}</td><td class="pos">{E(", ".join(ad)) or "<span class=muted>none</span>"}</td><td class="neg">{E(", ".join(dr)) or "<span class=muted>none</span>"}</td><td class="muted">{kind}</td></tr>')
        moves_t = (f'<div class="scroll"><table><thead><tr><th class="c">Wk</th><th>Added</th><th>Dropped</th><th>How</th></tr></thead><tbody>{"".join(reversed(mrows))}</tbody></table></div>'
                   f'<p class="note">{len(mrows)} moves, newest first. Commissioner moves (like undoing a vetoed trade) are listed for the record but never count as a pickup or a cut. Trades are listed above.</p>') if mrows else '<p class="muted">No waiver or free-agent moves yet.</p>'
        # ---- team records
        hi_ = max(res, key=lambda x: x["me"]); lo_ = min(res, key=lambda x: x["me"])
        wins_ = [x for x in res if x["win"]]; loss_ = [x for x in res if not x["win"]]
        bs = max(((p, w, i) for w in s.weeks for i, p in s.W[w][r]["S"] if i != "0"))
        trec = [("Highest score", fp(hi_["me"]), hi_["w"]), ("Lowest score", fp(lo_["me"]), lo_["w"])]
        if wins_: bw_ = max(wins_, key=lambda x: x["me"] - x["th"]); trec.append(("Biggest win", f'by {fp(bw_["me"] - bw_["th"])} over {s_.TN(bw_["op"], bw_["w"])}', bw_["w"]))
        if loss_: wl_ = max(loss_, key=lambda x: x["th"] - x["me"]); trec.append(("Worst loss", f'by {fp(wl_["th"] - wl_["me"])} to {s_.TN(wl_["op"], wl_["w"])}', wl_["w"]))
        trec.append(("Best start", f"{nm(bs[2])}, {fp(bs[0])}", bs[1]))
        trecs = '<div class="recs">' + "".join(f'<a class="rec" href="{s_.gurl_r(w, r, pre)}"><span class="k">{E(k)}</span><span class="v">{E(v)}</span><span class="w">Week {w}, {yr}</span></a>' for k, v, w in trec) + "</div>"
        seasons_nav = '<div class="seasons">' + "".join(f'<a href="{s_.turl(r, pre)}" aria-current="page">{y}</a>' for y in seasons) + '</div>'
        upnext = f'<section class="unx"><h2>Up next <small>Week {wk0}</small></h2><div class="faceoffs dk">{s_.faceoff(wk0, *s_.game_of[(wk0, r)], pre)}</div></section>' if (wk0, r) in s_.game_of else ""
        # ---- one season roster: everyone who was on the team this year
        on = defaultdict(list); stw = defaultdict(list); edg = Counter(); hi_ = {}; bpts = Counter()
        for w in s.weeks:
            d = s.W[w][r]; md_ = s.pos_median(w)
            for i, p in d["S"]:
                if i != "0": edg[i] += p - md_[s.pos(i)]; hi_[i] = max(hi_.get(i, -99), p)
            for i, p in d["B"]:
                if i != "0": bpts[i] += p
            for i, _ in d["S"] + d["B"]:
                if i != "0": on[i].append(w)
            for i, _ in d["S"]:
                if i != "0": stw[i].append(w)
        lob = Counter()                      # left on bench: what benching him cost this team in weeks he should have started
        for w in s.weeks:
            for i, g in s_.bench_gain(w, r).items():
                if g > 0: lob[i] += g
        for i, _ in s_.live_final(r): on[i].append(s.nxt)
        for i in s_.locked_now(r):                   # on the bench or in IR when his game kicked off: locked to this team for the week
            if s.nxt not in on[i]: on[i].append(s.nxt)
        for i in s.rost[r]: on.setdefault(i, [])
        def stints(ws, cur):
            if not ws: return f"Wk {s.last + 1}-now" if cur else ""
            out_, a0 = [], ws[0]; prev = ws[0]
            for w in ws[1:] + [None]:
                if w is not None and w == prev + 1: prev = w; continue
                end = "now" if (cur and prev >= s.last) else str(prev)
                out_.append(f"Wk {a0}" if (end == str(a0)) else f"Wk {a0}-{end}")
                if w is not None: a0 = prev = w
            return ", ".join(out_)
        if not hasattr(s_, "_srank"):     # season position rank by points in Super League starts (WR1 = most points started at WR); ties share
            tp_ = Counter()
            for w in s.weeks:
                for r_, d_ in s.W[w].items():
                    for j, v in d_["S"]:
                        if j != "0": tp_[j] += v
            s_._srank = {}; byp_ = defaultdict(list)
            for j, v in tp_.items():
                if v > 0: byp_[s.pos(j)].append((v, j))
            for P, L in byp_.items():
                L.sort(reverse=True); prev, rk = None, 0
                for n, (v, j) in enumerate(L, 1):
                    if round(v, 2) != prev: rk, prev = n, round(v, 2)
                    s_._srank[j] = f"{P}{rk}"
        nxt_ = s_.TEAM.get((wk0, r)); lu_set = set(nxt_["lineup"]) if nxt_ else set()
        ros_rows = []
        key_ = lambda i: (-st.get(i, [0, 0.0, 0.0])[2], -st.get(i, [0, 0.0, 0.0])[1], -len(on[i]), nm(i))
        PO_ = ("QB", "RB", "WR", "TE", "K", "DEF"); MC_ = s_.mvp_counts()
        def avail_(i):              # weeks he could have started: on the roster, not on bye, not on IR
            by_ = [w for w in on[i] if s_.team_at(w, i) in s.byes.get(w, [])]
            ir_ = [w for w in on[i] if w not in by_ and i in s_.ir_set(r, w, [i])]
            return len(on[i]) - len(by_) - len(ir_), len(by_), len(ir_)
        def gsw_(i, g_):
            if not on[i]: return "-"
            av, by_, ir_ = avail_(i); ex = ", ".join(x for x in (f"{by_} bye" if by_ else "", f"{ir_} IR" if ir_ else "") if x)
            return f'{g_} <small>of {av}</small>' + (f'<small class="gx">{ex}</small>' if ex else "")
        for i in sorted(on, key=lambda i: (PO_.index(s.pos(i)) if s.pos(i) in PO_ else 9,) + key_(i)):
            P = s.pos(i); cur = i in s.rost[r]; g_, p_, w_ = st.get(i, [0, 0.0, 0.0]); P_ = s.PL.get(i, {}); inj = P_.get("inj")
            nfl = (P_.get("team") or "FA") if i.isdigit() else i
            tw_ = []                                  # the NFL team(s) he was on while on this team, in order
            for w in on[i]:
                tt = s_.team_at(w, i) if i.isdigit() else i
                if tt and (not tw_ or tw_[-1] != tt): tw_.append(tt)
            dk = (f'data-wmvp="{MC_[1][(i, r)]}" data-gmvp="{MC_[3][(i, r)]}" data-pos="{P}" data-n="{E(s.nm(i))}" data-stint="{on[i][0] if on[i] else 99}" data-war="{w_:.4f}" data-pts="{p_ if g_ else -1:.2f}" data-avg="{(p_ / g_) if g_ else -1:.3f}" '
                  f'data-edge="{edg[i] if g_ else -999:.2f}" data-best="{hi_.get(i, -99):.2f}" data-bench="{bpts[i]:.2f}" data-lob="{lob[i]:.2f}" data-gs="{g_ + avail_(i)[0] / 100:.2f}"')
            ros_rows.append(f'<tr class="{"" if cur else "gone"}" {dk}><td class="pl">{"<b>" if cur else ""}{s_.plink(i, pre, s.nm(i))}{"</b>" if cur else ""}{(f'<span class="prk">{s_._srank[i]}</span>') if i in s_._srank else ""}{(f'<span class="mvpb">MVP{" x" + str(MC_[1][(i, r)]) if MC_[1][(i, r)] > 1 else ""}</span>') if MC_[1][(i, r)] else ""}<small>{" ".join(s_.nl(x) for x in tw_) if tw_ and not cur else s_.nl(nfl)}{inj_tag(inj) if cur else ""}</small></td>'
                            f'<td class="stn">{", ".join(f"<span>{E(x)}</span>" for x in stints(on[i], cur).split(", ")) }</td><td class="r gsw">{gsw_(i, g_)}</td>'
                            f'<td class="r {"pos" if w_ > 0.005 else "neg" if w_ < -0.005 else "muted"}">{w_:+.2f}</td><td class="r">{fp(p_) if g_ else "-"}</td><td class="r">{f"{p_ / g_:.1f}" if g_ else "-"}</td>'
                            f'<td class="r xd {"pos" if edg[i] > 0.05 else "neg" if edg[i] < -0.05 else "muted"}">{f"{edg[i]:+.1f}" if g_ else "-"}</td><td class="r xd">{f"<i>{fp(hi_[i])}</i>" if i in hi_ else "-"}</td><td class="r xd">{fp(bpts[i]) if bpts[i] else "-"}</td><td class="r xd{" neg" if lob[i] > 0.05 else ""}">{f"{lob[i]:.1f}" if lob[i] > 0.05 else "-"}</td><td class="r xd">{MC_[1][(i, r)] or "-"}</td><td class="r xd">{MC_[3][(i, r)] or "-"}</td></tr>')
        th_ = lambda k, lab, c="r": f'<th class="{c} srt" data-k="{k}" tabindex="0" role="button">{lab}</th>'
        roster_all = (f'<div class="rtog chips" role="group" aria-label="Roster view"><button type="button" data-m="pos" aria-pressed="true">By position</button><button type="button" data-m="all" aria-pressed="false">All</button></div>'
                      f'<div class="scroll"><table class="rost" data-m="pos" data-k="war" data-d="-1" style="min-width:0"><thead><tr><th class="pcol srt" data-k="pos" tabindex="0" role="button">Pos</th>{th_("n", "Player", "")}{th_("stint", "Stint", "")}{th_("gs", "Started")}'
                      f'{th_("war", "WAR")}{th_("pts", "Pts")}{th_("avg", "Avg")}{th_("edge", "PAA", "r xd")}{th_("best", "High", "r xd")}{th_("bench", "Bench pts", "r xd")}{th_("lob", "Left on bench", "r xd")}{th_("wmvp", "Wk MVP", "r xd")}{th_("gmvp", "Gm MVP", "r xd")}</tr></thead><tbody>{"".join(ros_rows)}</tbody></table></div>'
                      f'<p class="note">Everyone on the team for at least one week\'s games in {yr} (started or on the bench). Players added and dropped between games are in Moves. Bold = on the roster now. Pts and Avg are from starts. High = his best single start. Left on bench = points the team missed by benching him in weeks he should have started. Wk MVP = Week MVP awards, Gm MVP = top player on the winning side of a game, both for this team. Started = weeks started of the weeks he was available (on the roster, not on bye or IR). Tap a column to sort.</p>')
        tabs = [("overview", "Overview"), ("schedule", "Schedule"), ("roster", "Roster"), ("moves", "Moves"), ("lineups", "Lineups")]
        tu = s_.turl(r, pre, True)
        def chips(cur):
            """One bar for both views: Career, each season, and (on a season) its sections. Same height either way, so switching doesn't jump."""
            yrs_ = "".join(f'<a class="tvw" href="{tu}#{y}"{" aria-current=true" if cur == str(y) else ""}>{y} season</a>' for y in sorted(seasons, reverse=True))
            sec = ('<span class="tsep" aria-hidden="true"></span>' + "".join(f'<a href="{tu}#{yr}-{k}" data-tab="{k}">{t}</a>' for k, t in tabs)) if cur != "all" else ""
            return (f'<nav class="ttabs" aria-label="{E(M[r])} pages"><div class="wrap"><a class="tvw" href="{tu}"{" aria-current=true" if cur == "all" else ""}>Career</a>{yrs_}{sec}</div></nav>')
        tabbar = ""
        names = " / ".join(f"{E(s_.TN(r))} ({y})" for y in sorted(seasons, reverse=True))
        olds = [o for ts, rr, o, n_ in s_.name_hist() if rr == r and o and o != s_.TN(r)]
        if olds: names += ", formerly " + " / ".join(E(o) for o in dict.fromkeys(reversed(olds)))
        hero_all = (f'<section class="field"><div class="wrap"><a class="back" href="../teams.html">All teams</a>'
                    f'<div class="hero">{s_.logo(r, pre, "lgh")}<div><h1>{E(M[r])}</h1><div class="sub">{names}</div></div></div>'
                    f'<div class="herostats"><span><b>{s_.rec_str(r)}</b>record</span>'
                    f'<span><b>{len(seasons)}</b>season{"" if len(seasons) == 1 else "s"}</span><span><b>{s_.xw[r]:.1f}</b>xWins</span><span><b>{lk:+.1f}</b>luck</span></div>'
                    f'</div></section>')
        hero_yr = (f'<section class="field"><div class="wrap"><a class="back" href="../teams.html">All teams</a>'
                   f'<div class="hero">{s_.logo(r, pre, "lgh")}<div><h1>{E(s_.TN(r))}</h1><div class="sub">{E(M[r])}, {yr}{(", formerly " + " / ".join(E(o) for o in dict.fromkeys(reversed([o for ts, rr, o, n_ in s_.name_hist() if rr == r and o and o != s_.TN(r)])))) if any(rr == r for _, rr, *__ in s_.name_hist()) else ""}</div></div></div>'
                   f'<div class="herostats"><span><b>{s_.rec_str(r)}</b>record</span><span><b>{s_.xw[r]:.1f}</b>xWins</span><span><b>{ordn(rk)}</b>standings</span><span><b>{ordn(pw_k)}</b>power</span><span><b>{pct(o["po"])}</b>playoffs</span><span><b>{pct(o["ti"])}</b>title</span></div>'
                   f'</div></section>')
        byseason = (f'<div class="scroll"><table><thead><tr><th>Season</th><th>Team</th><th class="c">Record</th><th class="r">Points</th><th class="r">xWins</th><th class="r">Luck</th><th class="c">Finish</th></tr></thead><tbody>'
                    + "".join(f'<tr><td><a class="go" href="{tu}#{y}">{y}</a></td><td><b>{E(s_.TN(r))}</b></td><td class="c big">{s_.rec_str(r)}</td><td class="r">{s_.PF[r]:.1f}</td>'
                              f'<td class="r">{s_.xw[r]:.1f}</td><td class="r {"pos" if lk > 0.25 else "neg" if lk < -0.25 else ""}">{lk:+.1f}</td><td class="c">{ordn(rk)} <span class="muted">(Wk {s.last})</span></td></tr>' for y in sorted(seasons, reverse=True))
                    + "</tbody></table></div>")
        body = f"""<div class="tview" data-v="all">
{hero_all}
{chips("all")}
<main class="wrap">
<section><h2>Career</h2>{fr}</section>
<section><h2>Seasons</h2>{byseason}</section>
<section><h2>Head to head</h2><div class="scroll"><table>{h2h}</table></div></section>
<section><h2>Personal bests</h2>{trecs}</section>
{"" if len(seasons) == 1 else f'<section><h2>Luck <small>wins vs xWins after every game</small></h2>{s_.luck_chart(luck_rows, f"{M[r]} all-time wins and xWins by game")}</section>'}
{s_.story_list(s_.stories_for(team=r)[:3], "")}
</main>
</div>
<div class="tview" data-v="{yr}" data-cur="1" hidden>
{hero_yr}
{chips(str(yr))}
<main class="wrap">
<div class="tpanel" data-t="overview">
{upnext}
<section><h2>{yr} season</h2>
<div class="stats">{stat("Bye chance", pct(o["bye"]))}{stat("Projected wins", f'{o["pw"]:.1f}', "end of regular season")}{stat("Points for", f"{s_.PF[r]:.1f}", f"{s_.PF[r] / n:.1f} per week")}{stat("Points against", f"{PA_:.1f}", f"{PA_ / n:.1f} per week")}</div></section>
<section><h2>Where they'll finish <small>seed odds</small></h2><div class="panel"><div class="seeds">{seeds}</div></div></section>
<section><h2>Weekly scores</h2>{chart}</section>
<section><h2>Luck <small>wins vs xWins after every game</small></h2><div class="stats" style="grid-template-columns:repeat(3,1fr)">{stat("Wins", str(s_.W0[r]))}{stat("xWins", f"{s_.xw[r]:.1f}")}{stat("Luck", f"{lk:+.1f}", f"{ordn(lrank)} luckiest of {len(s.R)}")}</div>{s_.luck_chart(luck_rows, f"{M[r]} {yr} wins and xWins by game")}</section>
{s_.story_list(s_.stories_for(team=r)[:3], "")}
</div>
<div class="tpanel" data-t="schedule"><section><h2>Schedule</h2>{sched_t}</section></div>
<div class="tpanel" data-t="roster"><section><h2>{yr} roster</h2>{roster_all}</section>
<section><h2>WAR by position</h2>{s_.war_pos_strip(r)}</section>
<section><h2>Draft class</h2>{draft_t}</section></div>
<div class="tpanel" data-t="moves">
<section><h2>Trades</h2>{trades_t}</section>
<div class="grid2"><section><h2>Best pickups</h2><table class="pt"><tbody>{picks_t}</tbody></table></section>
<section><h2>Worst drops</h2><table class="pt"><tbody>{drops_t}</tbody></table></section></div>
<section><h2>Waiver and free-agent log</h2>{moves_t}</section>
</div>
<div class="tpanel" data-t="lineups">
<section><h2>Lineup report</h2>{lineup}</section>
<section><h2>Team awards</h2>{aw}</section>
</div>
</main>
</div>{s_.footer(pre)}"""
        return page(f"{M[r]}, Super League", body, pre, "teams")


    # ---- win probability by NFL time slot
    def slot_label(s_, dt):
        wd = dt.weekday(); hm = dt.strftime("%-I:%M")
        if wd == 6:
            if dt.hour >= 19: return "SNF"
            return hm
        if wd == 0: return "MNF"
        return dt.strftime("%a")
    def pbp_rows(s_, w, A, B):
        """Play-by-play win probability for one matchup: [(iso time, pA, pts so far A, pts so far B)], thinned for the chart."""
        import pbp as _pb
        s = s_.s
        if not hasattr(s_, "_pbpG"): s_._pbpG = _pb.load(getattr(s, "ddir", "data")); s_._pbpP = {}; s_._pbp_end = {}
        if not s_._pbpG: return None
        if w not in s_._pbpP:
            act = dict(s.NP.get(w, {}))
            if w == s.nxt:                                    # live week: finals so far
                for r in s.R:
                    lv = s_.live_of(w, r)
                    if lv: act.update({i: p for i, p in lv["played"].items() if i not in lv.get("inprog", ())})
            tm = lambda i: s_.team_at(w, i)
            ex_ = [i for i, v in s.PL.items() if v.get("team")] if w == s.nxt else ()
            s_._pbpP[w] = _pb.game_paths(s_._pbpG, w, act, tm, s.nm, s.pos, ex_)
            s_._pbp_end[w] = {t: v[0][-1] for t, v in s_._pbpP[w].items() if v[3] and v[0]}
        P = s_._pbpP[w]
        if not P: return None
        ck = (w, tuple(x[0] for x in A), tuple(x[0] for x in B))
        if not hasattr(s_, "_pbpR"): s_._pbpR = {}
        if ck in s_._pbpR: return s_._pbpR[ck]
        team = lambda i: (lambda t: "" if t == "FA" else t)(s_.team_at(w, i))
        side = lambda X: [(i, team(i), pj, act) for i, act, pj in X]
        rows = _pb.wp_timeline((side(A), side(B)), P, None, s_.T["cv"], s_.T["corr"], s.pos)
        if not hasattr(s_, "_pbpF"): s_._pbpF = {}
        s_._pbpF[ck] = rows
        s_._pbpR[ck] = _pb.thin(rows, 60) if rows else None
        return s_._pbpR[ck]

    def oh_ext(s_):
        """The odds tracker with every tracked week filled in play by play: at each play, everyone's odds = each way that week's games
        could finish, weighted by its live chance. Pinned to the logged odds before the week and after it (or now), so the ends match."""
        from zoneinfo import ZoneInfo
        s = s_.s; ET = ZoneInfo("America/New_York"); OH = [list(x) for x in (getattr(s, "ohist", None) or [])]
        if not OH: return OH
        for x in OH:                                       # the log is written in UTC (the update runs on a UTC clock): show it in Eastern
            if re.match(r"\d{4}-\d\d-\d\d \d\d:\d\d$", str(x[1])):
                x[1] = datetime.datetime.strptime(x[1], "%Y-%m-%d %H:%M").replace(tzinfo=datetime.timezone.utc).astimezone(ET).strftime("%Y-%m-%d %H:%M")
        pts_ = lambda ts: datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M").replace(tzinfo=ET) if re.match(r"\d{4}-\d\d-\d\d \d\d:\d\d$", ts) else None
        for k, cond in sorted((getattr(s, "ocond", None) or {}).items()):
            if not cond or not cond["O"]: continue
            gl = cond["games"]; rows = {}; pre = {}
            for gi, (a, b) in enumerate(gl):
                ser = s_.wp_series(k, a, b)
                if not ser: continue
                pre[gi] = ser[0][1]
                A_, B_ = s_._ab.get((k, a, b), (None, None))
                rr = s_.pbp_rows(k, A_, B_) if A_ is not None else None
                if rr: rows[gi] = [(datetime.datetime.strptime(x[0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc).astimezone(ET), x[1]) for x in rr]
            if not rows: continue
            ev = sorted({x[0] for v in rows.values() for x in v})
            cur = {gi: pre.get(gi, 0.5) for gi in range(len(gl))}; ptr = {gi: 0 for gi in rows}
            R = list(next(iter(cond["O"].values())).keys())
            def mix():
                out = {r: [0.0, 0.0, 0.0, 0.0] for r in R}; tot = 0.0
                for c, O in cond["O"].items():
                    pr = 1.0
                    for gi in range(len(gl)):
                        pr *= cur[gi] if (c >> gi) & 1 else 1 - cur[gi]
                    if pr < 1e-9: continue
                    tot += pr
                    for r in R:
                        for j in range(4): out[r][j] += pr * O[r][j]
                return {r: [v / tot for v in out[r]] for r in R} if tot else None
            O0 = mix(); seq = []
            for tm in ev:
                for gi, v in rows.items():
                    while ptr[gi] < len(v) and v[ptr[gi]][0] <= tm: cur[gi] = v[ptr[gi]][1]; ptr[gi] += 1
                m = mix()
                if m: seq.append((tm, m))
            if not seq: continue
            t0, t1 = ev[0], ev[-1]
            # anchors: the logged odds just before the week's first play, every update logged while its games were on (those carry
            # projection and injury changes), and just after it ended (or now). Between two anchors the gap is phased out over time,
            # so the line goes through every number the site actually posted.
            idx_ = [(j, pts_(x[1])) for j, x in enumerate(OH)]
            # pregame updates of this week, redone with the starters who actually played: the same conditional odds, fed the game
            # chances those lineups had at that moment instead of the ones logged (which assumed the best projected lineups)
            wend = max([tt for j, tt in idx_ if tt is not None and OH[j][0] == f"W{k - 1}"] or [None], key=lambda x: x or datetime.datetime.min.replace(tzinfo=ET))
            ml_ = [(datetime.datetime.strptime(r_[0], "%Y-%m-%dT%H:%MZ").replace(tzinfo=datetime.timezone.utc).astimezone(ET), int(r_[2]), int(r_[3]), float(r_[4]))
                   for r_ in (getattr(s, "mlog", []) or []) if int(r_[1]) == k]
            def logged_p(a_, b_, tt):
                v = None
                for tm_, x_, y_, p_ in ml_:
                    if tm_ <= tt and {x_, y_} == {a_, b_}: v = p_ if x_ == a_ else 1 - p_
                return v
            lw_ = [(datetime.datetime.strptime(r_[0], "%Y-%m-%dT%H:%MZ").replace(tzinfo=datetime.timezone.utc).astimezone(ET), int(r_[2]), int(r_[3]), float(r_[4]), float(r_[5]), float(r_[6]))
                   for r_ in (getattr(s, "livewp", []) or []) if int(r_[1]) == k]
            def live_row(a_, b_, tt):
                v = None
                for tm_, x_, y_, p_, sx, sy in lw_:
                    if tm_ <= tt and {x_, y_} == {a_, b_}: v = (p_, sx, sy) if x_ == a_ else (1 - p_, sy, sx)
                return v
            for j, tt in idx_:
                if tt is None or (wend and tt <= wend) or tt >= t1 or OH[j][0] == f"W{k}": continue
                if tt >= t0:                                 # between games: same redo, with the points already banked
                    kk_ = {gi: getattr(s_, "_wkick", {}).get((k, a_, b_)) or getattr(s_, "_wkick", {}).get((k, b_, a_)) or {} for gi, (a_, b_) in enumerate(gl)}
                    if any(any(v_ <= tt < v_ + datetime.timedelta(hours=3.5) for v_ in kk_[gi].values()) for gi in kk_): continue   # mid-game: leave it
                    lr = {gi: live_row(a_, b_, tt) for gi, (a_, b_) in enumerate(gl)}
                    if any(v is None for v in lr.values()): continue
                    cr = {gi: s_.pregame_p(k, a_, b_, tt, lr[gi][1], lr[gi][2], kk_[gi]) for gi, (a_, b_) in enumerate(gl)}
                    cl = {gi: lr[gi][0] for gi in lr}
                else:
                    cr = {gi: s_.pregame_p(k, a_, b_, tt) for gi, (a_, b_) in enumerate(gl)}
                    cl = {gi: logged_p(a_, b_, tt) for gi, (a_, b_) in enumerate(gl)}
                if any(v is None for v in list(cr.values()) + list(cl.values())): continue
                keep_ = dict(cur); cur.update(cr); mr = mix(); cur.update(cl); ml = mix(); cur.clear(); cur.update(keep_)
                if not mr or not ml: continue
                OH[j] = [OH[j][0], OH[j][1], {r: tuple([min(1.0, max(0.0, OH[j][2][r][q] + mr[r][q] - ml[r][q])) for q in range(3)] + list(OH[j][2][r][3:])) if r in mr else OH[j][2][r] for r in OH[j][2]}]
            before = [j for j, tt in idx_ if tt is not None and tt <= t0] or [j for j, x in enumerate(OH) if x[0] in (f"W{k - 1}", f"Pre-W{k}")]
            endw = [j for j, x in enumerate(OH) if x[0] == f"W{k}"]
            if not before: continue
            jb = before[-1]; je = endw[0] if endw else len(OH) - 1
            inside = [j for j, tt in idx_ if tt is not None and t0 < tt < t1 and j != je and OH[j][0] != f"W{k}"]
            def model_at(tt):
                m_ = seq[0][1]
                for tm_, mm in seq:
                    if tm_ <= tt: m_ = mm
                    else: break
                return m_
            anc = [(t0, OH[jb][2], O0)] + [(idx_[j][1], OH[j][2], model_at(idx_[j][1])) for j in inside] + [(t1, OH[je][2], seq[-1][1])]
            off = []                                       # (time, {team: [offsets]})
            for ta, L, M_ in anc:
                d = {}
                for r in R:
                    if r in L and r in M_:
                        d[r] = [L[r][j] - M_[r][j] for j in range(3)] + ([L[r][3] - M_[r][3]] if len(L[r]) > 3 and L[r][3] is not None else [])
                off.append((ta, d))
            def off_at(tt, r):
                for q in range(len(off) - 1):
                    ta, da = off[q]; tb, db = off[q + 1]
                    if ta <= tt <= tb:
                        if r not in da or r not in db: return None
                        lam = (tt - ta).total_seconds() / (((tb - ta).total_seconds()) or 1.0)
                        return [da[r][j] * (1 - lam) + db[r][j] * lam for j in range(min(len(da[r]), len(db[r])))]
                return off[-1][1].get(r)
            new = []
            for tm, m in seq:
                d = {}
                for r in R:
                    o_ = off_at(tm, r)
                    if o_ is None: continue
                    v = [min(1.0, max(0.0, m[r][j] + o_[j])) for j in range(3)]
                    if len(o_) > 3: v.append(m[r][3] + o_[3])
                    d[r] = tuple(v)
                new.append([f"W{k} play", tm.strftime("%Y-%m-%d %H:%M"), d])
            # thin: keep the shape, every big move, and each team's extremes
            if len(new) > 90:
                keep = set(range(0, len(new), max(1, len(new) // 80))) | {len(new) - 1}
                for r in R:
                    po = [x[2].get(r, (0,))[0] for x in new]
                    keep |= {po.index(min(po)), po.index(max(po))}
                    keep |= {j for j in range(1, len(po)) if abs(po[j] - po[j - 1]) > 0.02}
                new = [new[j] for j in sorted(keep)]
            # the logged updates taken while the games were on are now points on the play-by-play line
            OH = [x for j, x in enumerate(OH) if j not in set(inside)]
            at = next((j for j, x in enumerate(OH) if (pts_(x[1]) or t0) > t0 or x[0] == f"W{k}"), len(OH))
            OH[at:at] = new
        return OH

    def wp_series(s_, w, a, b):
        s = s_.s; sch = getattr(s, "sched", {}).get(w)
        if not sch: return None
        from zoneinfo import ZoneInfo
        ET = ZoneInfo("America/New_York")
        kick = {}; fin = {}
        for k, aw, hm, st, *_ in sch:
            dt = datetime.datetime.strptime(k, "%Y-%m-%dT%H:%MZ").replace(tzinfo=datetime.timezone.utc).astimezone(ET)
            for t in (aw, hm): kick[t] = dt; fin[t] = st == "STATUS_FINAL"
        done = w in s.G
        if not hasattr(s_, "_wkick"): s_._wkick = {}
        s_._wkick[(w, a, b)] = dict(kick)
        def side(r):
            out = []
            if done:
                for i, p in s.W[w][r]["S"]:
                    if i != "0": out.append((i, p, s.SP.get(w, {}).get(i, 0.0)))
            else:
                lv = s_.live_of(w, r)
                if not lv: return None
                for i in lv["starters"]:
                    if i and i != "0": out.append((i, lv["played"].get(i, 0.0), s_.proj(i, w)[0]))
            return out
        A, B = side(a), side(b)
        if A is None or B is None: return None
        if not hasattr(s_, "_ab"): s_._ab = {}
        s_._ab[(w, a, b)] = (A, B)
        team = lambda i: (lambda t: "" if t == "FA" else t)(s_.team_at(w, i))
        cv, corr = s_.T["cv"], s_.T["corr"]
        def locked_pts(X, g):
            return sum((act if t in kick else 0.0) for i, act, pj in X for t in [team(i)] if (t not in kick) or (g is not None and kick[t] <= g))
        def state(X, g):
            mu = 0.0; var = 0.0
            for i, act, pj in X:
                t = team(i); locked = (t not in kick) or (g is not None and kick[t] <= g)
                if locked: mu += act if t in kick else 0.0
                else: mu += pj; var += (cv.get(s.pos(i), 0.6) * pj) ** 2
            return mu, math.sqrt(var) * corr * (_WPSD if g is not None else 1.0)
        def p_of(g):
            (ma, sa), (mb, sb) = state(A, g), state(B, g)
            if sa + sb == 0: return 1.0 if ma > mb else (0.0 if mb > ma else 0.5)
            return ncdf((ma - mb) / math.hypot(sa, sb))
        groups = sorted(set(kick.values())); dec = None; fut = []
        # drop time slots that can't matter: no starter on either side plays in them. Before a slot kicks off in a live week,
        # anyone on either roster (not IR) could still be started, so it stays unless nobody on either roster plays then.
        st_t = {team(i) for X in (A, B) for i, *_ in X}; ro_t = set()
        if not done:
            for r in (a, b):
                irr = s_.ir_set(r, None, list(s.rost.get(r, [])))
                ro_t |= {team(i) for i in s.rost.get(r, []) if i not in irr}
        # every kickoff window stays, even ones nobody in this game plays in: same timeline for every game that week
        sc = lambda g: (0.0, 0.0) if g is None else (locked_pts(A, g), locked_pts(B, g))
        pts = [("Pregame", p_of(None), None, sc(None), f"Before kickoff, {groups[0].strftime('%a %b %-d')}" if groups else "Before kickoff")]
        for g in groups:
            if not done and not all(fin[t] for t, k in kick.items() if k <= g):
                # the rest of the week, if everyone scores exactly their projection: a dotted guide, not a forecast of the line
                for g2 in [x for x in groups if x >= g]:
                    def st2(X):
                        mu = 0.0; var = 0.0
                        for i, act, pj in X:
                            t = team(i)
                            if t not in kick: continue
                            if kick[t] <= g2: mu += act if fin[t] else pj
                            else: mu += pj; var += (cv.get(s.pos(i), 0.6) * pj) ** 2
                        return mu, math.sqrt(var) * corr * _WPSD
                    (ma, sa), (mb, sb) = st2(A), st2(B)
                    pf = (1.0 if ma > mb else 0.0 if mb > ma else 0.5) if sa + sb == 0 else ncdf((ma - mb) / math.hypot(sa, sb))
                    lk = lambda X: sum((act if fin[t] else pj) for i, act, pj in X for t in [team(i)] if t in kick and kick[t] <= g2)
                    fut.append((s_.slot_label(g2), pf, g2, (lk(A), lk(B)), sum(1 for t in kick if kick[t] == g2) // 2))
                break
            lab = s_.slot_label(g)
            when = f"After the {g.strftime('%a')} {g.strftime('%-I:%M %p').replace(':00', '')} game{'s' if sum(1 for t in kick if kick[t] == g) > 2 else ''}"
            pts.append((lab, p_of(g), g, sc(g), when))
            if dec is None and state(A, g)[1] == 0 and state(B, g)[1] == 0: dec = len(pts) - 1      # every starter has played: decided here
        # play by play: the real odds after every play, between the time-slot checkpoints
        pb_ = s_.pbp_rows(w, A, B)
        if pb_:
            ET_ = lambda iso: datetime.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc).astimezone(ET)
            rows = [(ET_(r_[0]),) + tuple(r_[1:]) for r_ in pb_]
            gend = s_._pbp_end.get(w, {})                    # team -> time of its game's last play
            E_ = []                                          # time each checkpoint stands for: the end of that slot's last game
            for x in pts:
                g_ = x[2]
                if g_ is None: E_.append(min(kick.values())); continue
                ends = [ET_(gend[t]) for t, k in kick.items() if k == g_ and t in gend]
                E_.append(max(ends) if ends else None)
            for k in range(1, len(E_)):                      # keep it increasing
                if E_[k] is not None and E_[k - 1] is not None and E_[k] < E_[k - 1]: E_[k] = E_[k - 1]
            known = [k for k, e in enumerate(E_) if e is not None]
            def at(tm):
                r_ = None
                for x in rows:
                    if x[0] <= tm: r_ = x
                    else: break
                return r_
            newp = []; pos = []
            for k, x in enumerate(pts):
                if k > 0 and E_[k] is not None and E_[k - 1] is not None:
                    span = (E_[k] - E_[k - 1]).total_seconds() or 1
                    for r_ in rows:
                        if E_[k - 1] < r_[0] <= E_[k]:          # a slot's last play shares its second with the slot's end: keep it
                            newp.append(("·", r_[1], r_[0], (r_[2], r_[3]), f"{r_[0].strftime('%a %-I:%M %p')}", r_[6] if len(r_) > 6 else None)); pos.append(k - 1 + (r_[0] - E_[k - 1]).total_seconds() / span)
                if k > 0 and E_[k] is not None and (done or all(fin[t] for t, kk in kick.items() if kk == x[2])):
                    r_ = at(E_[k])
                    if r_: x = (x[0], r_[1], x[2], (r_[2], r_[3]), x[4])
                newp.append(x); pos.append(float(k))
            if not done:                                     # the week in progress: plays since the last finished slot, out to now
                k0 = max(known) if known else 0
                lastE = E_[k0] if known else None
                tail = [r_ for r_ in rows if lastE is None or r_[0] > lastE]
                if tail:
                    nxt_k = next((k for k in range(k0 + 1, len(pts))), None)
                    for j, r_ in enumerate(tail):
                        newp.insert(len([q for q in pos if q <= k0]) + j, ("·", r_[1], r_[0], (r_[2], r_[3]), f"Live, {r_[0].strftime('%a %-I:%M %p')}", r_[6] if len(r_) > 6 else None))
                        pos.insert(len([q for q in pos if q <= k0]) + j, k0 + 0.9 * (j + 1) / (len(tail) + 1))
            n_in = sum(1 for r_ in rows if len(r_) > 6 and r_[6]); n_out = sum(1 for x in newp if len(x) > 5 and x[5])
            if n_in != n_out:                                # check: every play that scored for someone here is on the chart
                if not hasattr(s_, "_chartmiss"): s_._chartmiss = []
                s_._chartmiss.append(f"W{w} {s_.M[a]} v {s_.M[b]}: {n_in - n_out} scoring play(s) off the chart")
                print("CHART CHECK:", s_._chartmiss[-1])
            for j in range(1, len(pos)):                     # plays in different games at the same second: one after the other, not on top of each other
                if pos[j] <= pos[j - 1] and newp[j][0] == "·": pos[j] = pos[j - 1] + 0.004
            # a time slot nobody in this game plays in (no starter, or in a live week no one on either roster) gets squeezed to a
            # sliver: its tick stays so every game that week shares a timeline, but there's no long flat stretch
            use_t = st_t if done else (st_t | ro_t)
            wt = [1.0] + [(1.0 if (x[2] is None or any(kick.get(t) == x[2] for t in use_t)) else 0.18) for x in pts[1:]]
            cum = [0.0]
            for k in range(1, len(wt)): cum.append(cum[-1] + wt[k])
            def rem(v):
                k = int(math.floor(v)); f_ = v - k
                if k >= len(cum) - 1: return cum[-1] + (v - (len(cum) - 1))
                return cum[k] + f_ * wt[k + 1]
            pos = [rem(v) for v in pos]
            decobj = pts[dec] if dec is not None else None
            pts = newp
            if decobj is not None and decobj in pts: dec = pts.index(decobj)
            elif decobj is not None:
                dec = next((k for k, x in enumerate(pts) if x[2] == decobj[2] and x[0] != "·"), dec)
            if not hasattr(s_, "_wpos"): s_._wpos = {}
            s_._wpos[(w, a, b)] = pos
        lg_ = [] if pb_ else [r for r in getattr(s, "livewp", []) if int(r[1]) == w and {int(r[2]), int(r[3])} == {a, b}]
        if lg_:
            decobj = pts[dec] if dec is not None else None; ins = []
            for r in lg_:
                t_ = datetime.datetime.strptime(r[0], "%Y-%m-%dT%H:%MZ").replace(tzinfo=datetime.timezone.utc).astimezone(ET)
                p_ = float(r[4]) if int(r[2]) == a else 1 - float(r[4]); xa_, xb_ = (float(r[5]), float(r[6])) if int(r[2]) == a else (float(r[6]), float(r[5]))
                after = max(k for k, x in enumerate(pts) if x[2] is None or x[2] + datetime.timedelta(hours=3.5) <= t_)
                if decobj is not None and after >= pts.index(decobj): continue          # already decided: nothing new to show
                ins.append((after, t_, ("·", p_, t_, (xa_, xb_), f"Live, {t_.strftime('%a %-I:%M %p')}")))
            merged = []
            for k, x in enumerate(pts):
                merged.append(x); merged += [y for a_, t_, y in sorted((z for z in ins if z[0] == k), key=lambda z: z[1])]
            pts = merged
            if decobj is not None: dec = pts.index(decobj)
        if done and pb_ and len(pts) > 2:
            decobj_ = pts[dec] if dec is not None else None
            pts = s_.wp_anchor(w, a, b, pts, kick, pts[0][1], pts[-1][1], True)
            if decobj_ is not None:
                dec = next((k for k, x in enumerate(pts) if x[0] == decobj_[0] and x[2] == decobj_[2] and x[0] != "·"), dec)
        if done:
            dec = dec if dec is not None else len(pts) - 1
            fin_p = 1.0 if s.G[w]["scores"][a] > s.G[w]["scores"][b] else 0.0
            pts = pts[:dec] + [(x[0], fin_p, x[2], x[3], x[4] + (", final" if k == 0 else ", already decided")) + tuple(x[5:]) for k, x in enumerate(pts[dec:])]
        else:
            o0, oN = pts[0][1], pts[-1][1]
            PL_ = getattr(s, "projlog", {}).get(w)          # the projection logged before the week started
            if PL_ and a in PL_ and b in PL_:
                pts[0] = ("Pregame", s_.win_p((PL_[a][0] * s_.f, PL_[a][1] * s_.f), (PL_[b][0] * s_.f, PL_[b][1] * s_.f))) + pts[0][2:]
            if len(pts) > 1: pts[-1] = (pts[-1][0], s_.win_p(s_.upcoming(w, a), s_.upcoming(w, b))) + pts[-1][2:]   # latest point = the live number shown everywhere
            if pb_ and len(pts) > 2:
                pts = s_.wp_anchor(w, a, b, pts, kick, o0, oN, done)
        pts, dec = s_.wp_clean(w, a, b, pts, dec)
        if os.environ.get("WPDBG") == f"{w}-{a}-{b}" and not getattr(s_, "_dbgd", 0):
            s_._dbgd = 1; P_ = getattr(s_, "_wpos", {}).get((w, a, b))
            for k, x in enumerate(pts): print("WPDBG", k, P_[k] if P_ else k, x[0], round(x[1], 3), x[2], [round(v, 1) for v in x[3]])
        if not hasattr(s_, "_dec"): s_._dec = {}
        s_._dec[(w, a, b)] = dec
        if not hasattr(s_, "_fut"): s_._fut = {}
        s_._fut[(w, a, b)] = fut
        return pts
    def week_data(s_):
        """Every player who mattered in each finished week: rostered (started, bench, IR) and free agents who scored."""
        s = s_.s; WK = {}; NMX = {}; MED = {}
        for w in s.weeks:
            med = s.pos_median(w); MED[w] = {k: round(v, 2) for k, v in med.items()}; own = {}
            for r, d in s.W[w].items():
                for i, p in d["S"]:
                    if i != "0": own[i] = (r, 2)
                ir = s_.ir_set(r, w, [i for i, _ in d["B"]])
                for i, p in d["B"]:
                    if i != "0": own[i] = (r, 3 if i in ir else 1)
                for i in getattr(s, "reserve_wk", {}).get(w, {}).get(r, []):
                    own.setdefault(i, (r, 3))
            NP = s.NP.get(w, {}); rows = []
            for i in set(own) | {i for i, v in NP.items() if v}:
                P = s.pos(i)
                if P not in med: continue
                r, st = own.get(i, (0, 0)); pts = NP.get(i)
                if pts is None and st == 0: continue
                rows.append([i, r, st, None if pts is None else round(pts, 2), s_.stat_short(w, i) if pts is not None else "", 1 if s_.team_at(w, i) in s.byes.get(w, []) else 0])
                if i not in NMX: NMX[i] = [s.nm(i), P, (s.PL.get(i, {}).get("team") or "FA") if i.isdigit() else i]
            WK[w] = rows
        return dict(WK=WK, NM=NMX, MED=MED, R={k: round(v, 3) for k, v in s.repl["val"].items()}, WPP=s.wpp)
    def ta_data(s_):
        """Everything the trade analyzer needs to re-run the rest of the season in the browser."""
        s = s_.s; T = s_.T; proj = s_.proj; wl = list(s_.weeks_left)
        import superleague as _SL
        C = _SL.CONFIG
        ros = {r: list(s.rost[r]) for r in s.R}; rostered = {i for v in ros.values() for i in v}
        pool = set().union(*[set(v) for v in s.SP.values()]) if s.SP else set()
        FA = [i for i in pool if i not in rostered and s.pos(i) in _SL.POSLIST]
        cand = {}
        for w in wl:
            c_ = []
            for p_ in _SL.POSLIST:
                c = sorted([(proj(i, w)[0], i) for i in FA if s.pos(i) == p_], reverse=True); c = [x for x in c if x[0] > 0]
                c_ += [i for _, i in (c[C["pickup_rank"]:C["pickup_rank"] + 3] if len(c) > C["pickup_rank"] else c[-1:])]
            cand[w] = c_
        ids = rostered | {i for v in cand.values() for i in v}
        RV = s.repl["val"]
        def full(i):      # every game he played, started or not: a fair read on a player whose good weeks sat on a bench
            gw = [(w, s.NP[w][i]) for w in s.weeks if i in s.NP.get(w, {})]; g = [x for _, x in gw]
            return [round(sum(x - RV.at(w, s.pos(i)) for w, x in gw) * s.wpp, 2), len(g), round(sum(g) / len(g), 1) if g else 0]
        P = {i: [s.nm(i), s.pos(i), s_.team_at(s.last, i) if i.isdigit() else i, [round(proj(i, w)[0], 2) for w in wl], s.PL.get(i, {}).get("inj") or ""] + full(i) for i in ids}
        irs = {r: sorted(s_.ir_set(r, None, ros[r])) for r in s.R}
        return dict(R=s.R, N={r: [s_.TN(r), s.M[r]] for r in s.R}, LG={r: s_.logo(r, "", "lgs") for r in s.R}, W={r: s_.W0[r] for r in s.R}, PF={r: round(s_.PF[r], 2) for r in s.R},
                    wk=wl, fut={w: s.fut[w] for w in wl}, byes={w: s.byes.get(w, []) for w in wl}, slots=[sorted(x) for x in s.slots], cv=T["cv"], corr=T["corr"],
                    gain=C["pickup_min_gain"], pmax=C["pickup_max"], cand={w: cand[w] for w in wl}, ros=ros, ir=irs, P=P, po=s.L["playoff_teams"], by=s.L["playoff_byes"],
                    dl=int(s.L.get("trade_deadline", 99)), nxt=s.nxt, yr=s_.yr, f=s_.f,
                    pw={r: [round(float(np.mean([s.G[w]["scores"][r] for w in s.weeks])), 2), round(float(np.mean([s.G[w]["scores"][r] for w in s.weeks][-3:])), 2)] for r in s.R})

    def tx_when(s_):
        """When moves happen: busiest day and hour (ET), a day x time heatmap, and moves per week, for each kind of move."""
        import datetime as _d
        from zoneinfo import ZoneInfo
        s = s_.s; ET = ZoneInfo("America/New_York")
        KIND = {"trade": "Trades", "waiver": "Waivers", "free_agent": "Free agents"}
        mv = []
        for t in s.tx:
            if t.get("status") != "complete" or t["type"] not in KIND or not t.get("when"): continue
            dt = _d.datetime.strptime(t["when"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=_d.timezone.utc).astimezone(ET)
            mv.append((t["type"], dt, t["w"]))
        if not mv: return ""
        DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]; BL = ["12a", "3a", "6a", "9a", "12p", "3p", "6p", "9p"]
        hr = lambda h: f"{(h % 12) or 12} {'am' if h < 12 else 'pm'}"
        weeks = sorted({w for _, _, w in mv}); allw = list(range(1, max(weeks) + 1))
        def panel(key, M):
            if not M: return f'<div class="txw" data-k="{key}" hidden><p class="muted">None yet.</p></div>'
            dc = Counter(dt.weekday() for _, dt, _ in M); hc = Counter(dt.hour for _, dt, _ in M)
            mins = sorted(dt.hour * 60 + dt.minute for _, dt, _ in M); md = mins[len(mins) // 2]
            bd = max(dc, key=lambda d: dc[d]); bh = max(hc, key=lambda h: hc[h])
            tiles = (f'<div class="stat"><span class="k">Moves</span><span class="v">{len(M)}</span></div>'
                     f'<div class="stat"><span class="k">Busiest day</span><span class="v">{DAYS[bd]}</span><small class="muted">{dc[bd]} of {len(M)}</small></div>'
                     f'<div class="stat"><span class="k">Busiest hour</span><span class="v">{hr(bh)}</span><small class="muted">{hc[bh]} of {len(M)}</small></div>'
                     f'<div class="stat"><span class="k">Typical time</span><span class="v">{(md // 60 % 12) or 12}:{md % 60:02d} {"am" if md < 720 else "pm"}</span><small class="muted">median, ET</small></div>')
            # one row per day: the day's count sets its shade, and every move is a tick at its exact time on a 24-hour line
            mxd = max(dc.values())
            hm = '<div class="txdy"><div class="txax"><span></span><div class="txtl">' + "".join(f'<i style="left:{h / 24 * 100:.2f}%">{lab}</i>' for h, lab in [(0, "12a"), (6, "6a"), (12, "12p"), (18, "6p")]) + '</div><span></span></div>'
            for d in range(7):
                n = dc.get(d, 0); a_ = 0 if not n else 0.08 + 0.32 * n / mxd
                ticks = "".join(f'<b style="left:{(dt.hour * 60 + dt.minute) / 1440 * 100:.2f}%" title="{DAYS[d]} {(dt.hour % 12) or 12}:{dt.minute:02d} {"am" if dt.hour < 12 else "pm"}"></b>' for _, dt, _ in M if dt.weekday() == d)
                hm += (f'<div class="txrow"><span class="hd">{DAYS[d]}</span><div class="txtl" style="background:rgba(11,31,68,{a_:.2f})">'
                       + "".join(f'<u style="left:{h / 24 * 100:.2f}%"></u>' for h in (6, 12, 18)) + ticks + f'</div><span class="hn">{n}</span></div>')
            hm += '</div>'
            wc = Counter(w for _, _, w in M); wm = max(wc.values())
            bars = '<div class="txwk">' + "".join(f'<div class="txb" title="Week {w}: {wc.get(w, 0)}"><b>{wc.get(w, 0) or ""}</b><i style="height:{(wc.get(w, 0) / wm * 100):.0f}%"></i><span>{w}</span></div>' for w in allw) + '</div>'
            note = '<p class="note">Waivers run on a set schedule, so their times bunch up at processing time.</p>' if key == "waiver" else ""
            return (f'<div class="txw" data-k="{key}"{"" if key == "all" else " hidden"}><div class="stats txst">{tiles}</div>'
                    f'<h3 class="txh3">By day, every move at its time (ET)</h3>{hm}<h3 class="txh3">Moves by week, {s.L.get("season", "")}</h3>{bars}{note}</div>')
        chips = '<div class="rtog chips txwt" role="group" aria-label="Move type">' + "".join(
            f'<button type="button" data-k="{k}" aria-pressed="{"true" if k == "all" else "false"}">{lab}</button>' for k, lab in [("all", "All moves")] + list(KIND.items())) + '</div>'
        body = panel("all", mv) + "".join(panel(k, [m for m in mv if m[0] == k]) for k in KIND)
        return f'<section><h2>When moves happen</h2><p class="intro">Every completed move by the clock it went through, Eastern time.</p>{chips}{body}</section>'
    def tx_page(s_, pre):
        """Every transaction, newest first: trades, waiver claims (won and lost), free-agent moves."""
        from zoneinfo import ZoneInfo
        s = s_.s; ET = ZoneInfo("America/New_York"); E_ = E
        order = sorted(enumerate(s.tx), key=lambda kv: (kv[1].get("when") or "", kv[1]["w"], -kv[0]), reverse=True)
        from superleague import eff_week
        seq = [x for _, x in sorted(enumerate(s.tx), key=lambda kv: (kv[1].get("when") or "", kv[1]["w"], -kv[0])) if x["status"] == "complete"]
        pos_ = {id(x): n for n, x in enumerate(seq)}
        def until(x, i, r, side):       # first week after this move that the same team loses him again (side="drops") or gets him back (side="adds")
            for y in seq[pos_.get(id(x), len(seq)) + 1:]:
                if (i, r) in y[side]: return eff_week(s, y)
            return 10 ** 6
        def since_add(x, i, r):         # what he's done for the team that got him, until that team lets him go
            w, end = eff_week(s, x), until(x, i, r, "drops")
            st = [p for w_ in s.weeks if w <= w_ < end for j, p in s.W[w_].get(r, {}).get("S", []) if j == i]
            tail = "" if end > s.last + 1 else ", then let go"
            return (f'{len(st)} start{"s" if len(st) != 1 else ""}, {sum(st):.1f} pts for them' if st else ("No starts" if tail else "No starts yet")) + tail
        def pts_for(x, i, r):           # points he started for the team that got him: the order inside a trade
            w, end = eff_week(s, x), until(x, i, r, "drops")
            return sum(p for w_ in s.weeks if w <= w_ < end for j, p in s.W[w_].get(r, {}).get("S", []) if j == i)
        def since_drop(x, i, r):        # what he did anywhere after the drop, until the same team picked him back up
            w, end = eff_week(s, x), until(x, i, r, "adds")
            g = [s.NP[w_][i] for w_ in s.weeks if w <= w_ < end and i in s.NP.get(w_, {}) and i not in {j for j, _ in s.W[w_].get(r, {}).get("S", []) + s.W[w_].get(r, {}).get("B", [])}]
            tail = "" if end > s.last + 1 else ", then picked back up"
            return (f'{sum(g):.1f} pts in {len(g)} game{"s" if len(g) != 1 else ""} since' if g else "No games since") + tail
        def prow(i, sign, note):
            team = s_.team_at(s.last, i)
            return (f'<li class="txp {"add" if sign == "+" else "drp"}"><span class="sg">{sign}</span><span class="ps">{E_(s.pos(i))}</span>'
                    f'<span class="nm"><b>{s_.plink(i, pre, s.nm(i))}</b><small>{E_(team) if i.isdigit() else ""}</small></span><span class="sn">{note}</span></li>')
        MV = getattr(s, "mval", {}) or {}
        def grade(x, r):                # the move's grade for team r: best lineup with it minus without it, every week since
            g_ = MV.get(id(x), {}).get(r)
            if not g_: return ""
            pts, _, n = g_
            if not n: return '<span class="txg na" title="No finished games since this move">No games yet</span>'
            cls = "pos" if pts > 0.05 else "neg" if pts < -0.05 else "zero"
            return (f'<span class="txg {cls}" title="Best lineup with this move minus without it, over {n} week{"s" if n != 1 else ""} since">'
                    f'<b>{pts:+.1f}</b><small>pts, {pts / s.ppw:+.2f} W</small></span>')
        TYP = {"trade": "Trade", "waiver": "Waiver", "free_agent": "Free agent", "commissioner": "Commissioner"}
        cards = []; lastw = None
        for k, x in order:
            if x["type"] == "commissioner" and not x["adds"] and not x["drops"]: continue
            failed = x["status"] != "complete"
            if x["type"] == "trade" and failed: continue
            when = ""
            if x.get("when"):
                dt = datetime.datetime.strptime(x["when"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=datetime.timezone.utc).astimezone(ET)
                when = dt.strftime("%a %b %-d, %-I:%M %p")
            kind = "trade" if x["type"] == "trade" else ("waiver" if x["type"] == "waiver" else "fa")
            rs = sorted(set(x["rosters"]) | {r for _, r in x["adds"]} | {r for _, r in x["drops"]})
            if x["type"] == "trade":
                vet = any(j.get("vetoed") for j in getattr(s, "trades_meta", []) if False)
                body = '<div class="txsides">' + "".join(
                    f'<div class="txside"><div class="txt">{s_.logo(r, pre, "lgs", x["w"])}<a href="{s_.turl(r, pre)}"><b>{E_(s_.TN(r, x["w"]))}</b></a> gets{grade(x, r)}</div><ul>'
                    + "".join(prow(i, "+", since_add(x, i, r)) for i in sorted((i for i, rr in x["adds"] if rr == r), key=lambda i: (-pts_for(x, i, r), -sum(s.NP[w_].get(i, 0) for w_ in s.weeks)))) + '</ul></div>' for r in rs) + '</div>'
                head = " and ".join(E_(s_.M[r]) for r in rs)
            else:
                r = rs[0] if rs else None
                body = '<ul>' + "".join(prow(i, "+", since_add(x, i, r) if not failed else "Claim lost") for i, _ in x["adds"]) + "".join(prow(i, "−", since_drop(x, i, r)) for i, _ in x["drops"] if not failed) + '</ul>'
                head = (f'{s_.logo(r, pre, "lgs", x["w"])}<a href="{s_.turl(r, pre)}"><b>{E_(s_.TN(r, x["w"]))}</b></a><small>{E_(s_.M[r])}</small>' + (grade(x, r) if not failed else "")) if r else ""
            chip = "Lost claim" if failed else TYP.get(x["type"], x["type"].title())
            wk = f'<h3 class="txw">Week {x["w"]}</h3>' if x["w"] != lastw else ""; lastw = x["w"]
            cards.append(f'{wk}<article class="txc {kind}{" lost" if failed else ""}" data-k="{kind}" data-r="{",".join(str(r) for r in rs)}" data-lost="{1 if failed else 0}">'
                         f'<header><span class="txk">{chip}</span><span class="txh">{head}</span><time>{when}</time></header>{body}</article>')
        allg = [(v[0], x, r) for x in s.tx if id(x) in MV for r, v in MV[id(x)].items() if v[2]]
        def mline(v, x, r):
            got = [s.nm(i) for i, rr in x["adds"] if rr == r]; gave = [s.nm(i) for i, rr in x["drops"] if rr == r]
            what = ("+" + ", ".join(got) if got else "") + (" / " if got and gave else "") + ("−" + ", ".join(gave) if gave else "")
            return (f'<li><span class="tat2x">{s_.logo(r, pre, "lgs", x["w"])}<span><b>{E_(s.M[r])}</b> <small class="muted">Week {x["w"]}, {E_(TYP.get(x["type"], ""))}</small><br><small>{E_(what)}</small></span></span>'
                    f'<b class="{"pos" if v > 0 else "neg"}">{v:+.1f}</b></li>')
        best = sorted(allg, key=lambda z: -z[0])[:5]; worst = sorted(allg, key=lambda z: z[0])[:5]
        top = (f'<div class="grid2 txbw" style="margin-top:22px"><section><h2>Best moves</h2><ol class="txbl">{"".join(mline(*z) for z in best)}</ol></section>'
               f'<section><h2>Worst moves</h2><ol class="txbl">{"".join(mline(*z) for z in worst)}</ol></section></div>'
               f'<p class="note">Every move is graded for each team in it: its best possible lineup with the move minus without it, every finished week since. '
               f'Without = what it got is taken out and what it gave is put back (a replacement-level free agent fills an open spot; one too many cuts the least useful bench player). '
               f'A player stops counting the week he is let go. Start/sit doesn\'t count. About {s.ppw:.0f} pts = 1 win.</p>') if allg else ""
        n_tr = sum(1 for x in s.tx if x["type"] == "trade" and x["status"] == "complete"); n_w = sum(1 for x in s.tx if x["type"] == "waiver" and x["status"] == "complete"); n_f = sum(1 for x in s.tx if x["type"] == "free_agent" and x["status"] == "complete")
        opts = "".join(f'<option value="{r}">{E_(s.M[r])} ({E_(s_.TN(r))})</option>' for r in s.R)
        return (f'<div class="txbar"><div class="rtog chips txf" role="group" aria-label="Type"><button type="button" data-f="all" aria-pressed="true">All</button>'
                f'<button type="button" data-f="trade" aria-pressed="false">Trades {n_tr}</button><button type="button" data-f="waiver" aria-pressed="false">Waivers {n_w}</button>'
                f'<button type="button" data-f="fa" aria-pressed="false">Free agents {n_f}</button></div>'
                f'<input type="search" class="txq" placeholder="Search players or teams" aria-label="Search moves">'
                f'<select class="txteam" aria-label="Team"><option value="">All teams</option>{opts}</select>'
                f'<label class="txl"><input type="checkbox" class="txlost"> Show lost claims</label></div>'
                f'<div class="txlist">{"".join(cards)}</div><p class="muted txnone" hidden>No moves match.</p>' + top)

    def nfl_seq(s_, X, i, key="seq"):
        """NFL team(s) a player did a record with: one team, or every stint in order when he started for more than one."""
        sq = X.get(key) or []
        if len(set(sq)) > 1:
            out = []
            for tm in sq:
                if not out or out[-1] != tm: out.append(tm)
            return ",".join(out)
        return X["nfl"].most_common(1)[0][0] if X.get("nfl") else s_.team_at(None, i)
    def inj_snaps(s_):
        """Injury tags by export time: [(utc datetime, {id: status})], oldest first."""
        if hasattr(s_, "_injs"): return s_._injs
        snaps = {}
        try:
            for l in open(os.path.join(os.path.dirname(s_.logo_dir), "inj_snap.txt")):
                if l.startswith("#") or "|" not in l: continue
                ts, i, st = (l.rstrip("\n").split("|") + [""])[:3]
                d = snaps.setdefault(ts, {})
                if i != "*" and st: d[i] = st
        except OSError: pass
        s_._injs = [(datetime.datetime.strptime(k, "%Y-%m-%dT%H:%MZ"), v) for k, v in sorted(snaps.items())]; return s_._injs
    def kick_dt(s_, w, t):
        for k, aw, hm, *_ in getattr(s_.s, "sched", {}).get(w, []):
            if t in (aw, hm): return datetime.datetime.strptime(k, "%Y-%m-%dT%H:%MZ")
        return None
    def gday_inj(s_, w, i):
        """The tag a player carried into his game: the last export before kickoff (within 6 days). '' = no tag, None = no export to tell."""
        k = s_.kick_dt(w, s_.team_at(w, i))
        if k is None: return None
        prev = [d for ts, d in s_.inj_snaps() if ts < k and (k - ts).days < 6]
        return prev[-1].get(i, "") if prev else None
    def dead_spots(s_, w, r):
        """Lineup spots that could not score: left empty, a player on bye, or one already ruled out (projected 0 at kickoff). A surprise DNP does not count."""
        s = s_.s; out = []
        for i, p in s.W[w][r]["S"]:
            if i == "0": out.append((i, "empty"))
            elif s_.team_at(w, i) in s.byes.get(w, []) or (not i.isdigit() and i in s.byes.get(w, [])): out.append((i, "bye"))
            elif s_.dnp(w, i) and s.SP.get(w, {}).get(i, 0.0) <= 0.5: out.append((i, "ruled out"))   # projected 0 at kickoff = ruled out beforehand; a surprise DNP isn't the manager's fault
        return out
    def dnp(s_, w, i):
        """Didn't play: on a team that played, but not one snap. Byes are their own thing."""
        s = s_.s
        return bool(i and i.isdigit() and w in s.NP and s.NP[w] and i not in s.NP[w] and s_.team_at(w, i) not in s.byes.get(w, []))
    def bio(s_):
        if hasattr(s_, "_bio"): return s_._bio
        out = {}
        try:
            for l in open(os.path.join(os.path.dirname(s_.logo_dir), "bio.txt")):
                if l.startswith("#") or "|" not in l: continue
                i, bd, ex, no = (l.rstrip("\n").split("|") + ["", "", ""])[:4]
                out[i] = (bd, int(ex) if ex.strip().isdigit() else None, no.strip())
        except OSError: pass
        s_._bio = out; return out
    def age_of(s_, i):
        bd = s_.bio().get(i, ("", None))[0]
        if not bd: return None
        try:
            y, m, d = (int(x) for x in bd.split("-")[:3]); td = datetime.date.today()
            return td.year - y - ((td.month, td.day) < (m, d))
        except ValueError: return None
    def wk_rank(s_, w, i):
        """Where his points ranked among every NFL player at his position that week, by our scoring."""
        if not hasattr(s_, "_wkr"): s_._wkr = {}
        if w not in s_._wkr:
            s = s_.s; byp = defaultdict(list)
            for j, v in s.NP.get(w, {}).items(): byp[s.pos(j)].append(v)
            s_._wkr[w] = {P: sorted(v, reverse=True) for P, v in byp.items()}
        P = s_.s.pos(i); arr = s_._wkr[w].get(P); p = s_.s.NP.get(w, {}).get(i)
        if p is None and any(j == i for d in s_.s.W.get(w, {}).values() for j, _ in d["S"]):     # started, no snaps: his 0 against everyone who played
            if not arr: return None
            rk = 1 + sum(1 for v in arr if v > 1e-9); return f"T-{rk}" if any(abs(v) < 1e-9 for v in arr) else rk
        if not arr or p is None: return None
        rk = 1 + sum(1 for v in arr if v > p + 1e-9)
        return f"T-{rk}" if sum(1 for v in arr if abs(v - p) < 1e-9) > 1 else rk
    def st_rank(s_, w, i):
        """[rank, count] of his points among Super League starters at his position that week."""
        if not hasattr(s_, "_str"): s_._str = {}
        s = s_.s
        if w not in s_._str:
            byp = defaultdict(list)
            for r, d in s.W.get(w, {}).items():
                for j, p in d["S"]:
                    if j != "0": byp[s.pos(j)].append(p)
            s_._str[w] = byp
        arr = s_._str[w].get(s.pos(i)); p = s.NP.get(w, {}).get(i)
        if p is None and any(j == i for d in s.W.get(w, {}).values() for j, _ in d["S"]): p = 0.0    # started and never played: he still finished among the starters
        if not arr or p is None: return None
        rk = 1 + sum(1 for v in arr if v > p + 1e-9); tie = sum(1 for v in arr if abs(v - p) < 1e-9) > 1
        return [("T-" if tie else "") + str(rk), len(arr)]
    def mvp_counts(s_):
        """Week MVPs (league award) and game MVPs (top starter on each winning team, by points over the position median), per player and per (player, team)."""
        if hasattr(s_, "_mvpc"): return s_._mvpc
        s = s_.s; wk, wkt, gm, gmt = Counter(), Counter(), Counter(), Counter()
        for a_ in s.awards:
            i_, r_ = a_["mvp"][0], a_["mvp"][1]; wk[i_] += 1; wkt[(i_, r_)] += 1
        for w in s.weeks:
            med = s.pos_median(w); sc = s.G[w]["scores"]
            for a_, b_ in s.G[w]["pairs"]:
                for r_ in ([a_] if sc[a_] > sc[b_] else [b_] if sc[b_] > sc[a_] else [a_, b_]):
                    st_ = [(i, p) for i, p in s.W[w][r_]["S"] if i != "0"]
                    if not st_: continue
                    b_ = max(p - med[s.pos(i)] for i, p in st_)
                    for i_, p_ in st_:
                        if abs((p_ - med[s.pos(i_)]) - b_) < 1e-9: gm[i_] += 1; gmt[(i_, r_)] += 1
        s_._mvpc = (wk, wkt, gm, gmt); return s_._mvpc
    def war_pos(s_):
        """Season WAR from starts, by team and position."""
        if hasattr(s_, "_wp"): return s_._wp
        s = s_.s; R = s.repl["val"]; out = {r: Counter() for r in s.R}
        for w in s.weeks:
            for r, d in s.W[w].items():
                for i, p in d["S"]:
                    if i != "0" and s.pos(i) in R: out[r][s.pos(i)] += (p - R.at(w, s.pos(i))) * s.wpp
        s_._wp = out; return out
    def war_pos_table(s_, pre):
        s = s_.s; wp = s_.war_pos(); PO = ("QB", "RB", "WR", "TE", "K", "DEF")
        tot = {r: sum(wp[r].values()) for r in s.R}
        n_ = len(s.R)
        def shade(col, r):          # rank within the column: 1st is darkest, last is lightest
            rk = sorted(s.R, key=lambda x: -col[x]).index(r)
            a_ = 0.62 - 0.58 * rk / max(n_ - 1, 1)
            return f"background:rgba(30,123,74,{a_:.2f});color:#0B1F44"
        cols = {P: {r: wp[r][P] for r in s.R} for P in PO}
        def cell(r, P):
            v = wp[r][P]
            return f'<td class="r hm" style="{shade(cols[P], r)}">{v:+.2f}</td>'
        rows = "".join(f'<tr><td class="c rkn">{k_}</td><td><a class="tl" href="{s_.turl(r, pre)}">{s_.logo(r, pre, "lgs")}<b>{E(s_.TN(r))}</b></a></td>' + "".join(cell(r, P) for P in PO) + f'<td class="r hm" style="{shade(tot, r)}"><b>{tot[r]:+.2f}</b></td></tr>' for k_, r in enumerate(sorted(s.R, key=lambda r: -tot[r]), 1))
        tbl = lambda v, hid: (f'<div class="scroll wpv" data-v="{v}"{" hidden" if hid else ""}><table class="wpos" style="min-width:0"><thead><tr><th class="c">#</th><th class="srt" tabindex="0" role="button">Team</th>'
                + "".join(f'<th class="r srt" tabindex="0" role="button">{P}</th>' for P in PO) + '<th class="r srt" tabindex="0" role="button" aria-sort="descending">Total</th></tr></thead><tbody>' + rows + '</tbody></table></div>')
        seasons_ = [s_.yr]          # one table per season once past seasons are loaded; all-time adds them up
        tog = ('<div class="rtog chips wptog" role="group" aria-label="Season">' + "".join(f'<button type="button" data-v="{y}" aria-pressed="{"true" if k == 0 else "false"}">{y}</button>' for k, y in enumerate(seasons_))
               + '<button type="button" data-v="all" aria-pressed="false">All-time</button></div>')
        return (f'<section><h2>WAR by position</h2><p class="intro">WAR from each team\'s starters.</p>{tog}' + "".join(tbl(y, k > 0) for k, y in enumerate(seasons_)) + tbl("all", True) + '</section>')
    def war_pos_strip(s_, r):
        s = s_.s; wp = s_.war_pos(); PO = ("QB", "RB", "WR", "TE", "K", "DEF")
        rk = lambda P: 1 + sum(1 for x in s.R if wp[x][P] > wp[r][P] + 1e-9)
        ord_ = lambda n: f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"
        return ('<div class="wstrip">' + "".join(f'<div><span class="p">{P}</span><b class="{"pos" if wp[r][P] > 0.005 else "neg" if wp[r][P] < -0.005 else ""}">{wp[r][P]:+.2f}</b><small>{ord_(rk(P))} of {len(s.R)}</small></div>' for P in PO) + '</div>')
    def exc_all(s_):
        """Every finished game with its excitement score, most exciting first."""
        if hasattr(s_, "_exa"): return s_._exa
        s = s_.s
        g = [((w_, x, y), s_.excitement(w_, x, y)) for w_ in s.weeks for x, y in s.G[w_]["pairs"]]
        s_._exa = sorted([kv for kv in g if kv[1] is not None], key=lambda kv: -kv[1]); return s_._exa
    def exc_rank(s_, w, a, b):
        allg = s_.exc_all(); v = s_.excitement(w, a, b)
        rk = 1 + sum(1 for _, x in allg if x > v); tie = sum(1 for _, x in allg if x == v) > 1
        o = lambda n: f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"
        return (("T-" if tie else "") + o(rk), len(allg))
    def exc_table(s_, pre):
        """Every finished game with its six pieces: sortable, each piece drawn as a ring (share of the best ever at that piece)."""
        s = s_.s; allg = s_.exc_all(); P_ = getattr(s_, "_excp", {})
        names = [k for k, _ in s_.EXW]
        terms = {g: dict(s_.exc_terms(P_[(g[0], min(g[1], g[2]), max(g[1], g[2]))])) for g, _ in allg if (g[0], min(g[1], g[2]), max(g[1], g[2])) in P_}
        best = {k: max([terms[g][k] for g in terms] + [1e-9]) for k in names}
        def ring(v, k):
            pc = max(0.0, min(1.0, v / best[k])) if best[k] > 0 else 0.0; C = 2 * math.pi * 15
            return (f'<span class="xring" title="{E(k)} {v:.1f}, {pc * 100:.0f}% of the best ever"><svg viewBox="0 0 36 36" width="38" height="38" aria-hidden="true">'
                    f'<circle cx="18" cy="18" r="15" fill="none" stroke="var(--rule)" stroke-width="4"/>'
                    f'<circle cx="18" cy="18" r="15" fill="none" stroke="var(--flag)" stroke-width="4" stroke-linecap="round" stroke-dasharray="{C * pc:.1f} {C:.1f}" transform="rotate(-90 18 18)"/></svg>'
                    f'<b>{pc * 100:.0f}</b></span><small>{v:.1f}</small>')
        rows = []
        for (w_, x, y), v in allg:
            if (w_, x, y) not in terms: continue
            wi = x if s.G[w_]["scores"][x] > s.G[w_]["scores"][y] else y; lo = y if wi == x else x; T_ = terms[(w_, x, y)]
            rows.append(f'<tr><td class="rk"></td><td data-v="{E(s_.TN(wi, w_).lower())}"><a class="pn" href="{s_.gurl(w_, x, y, pre)}"><b>{E(s_.TN(wi, w_))}</b> over {E(s_.TN(lo, w_))}</a>'
                        f'<small class="muted"> Week {w_}, {fp(s.G[w_]["scores"][wi])}-{fp(s.G[w_]["scores"][lo])}</small></td>'
                        f'<td class="r big" data-v="{v}">{v:.1f}</td>' + "".join(f'<td class="c xr" data-v="{T_[k]:.3f}">{ring(T_[k], k)}</td>' for k in names) + '</tr>')
        th = (f'<th class="c">#</th><th class="xs" data-t="s" tabindex="0" role="button">Game</th><th class="r xs" data-t="n" aria-sort="descending" tabindex="0" role="button">Excitement</th>'
              + "".join(f'<th class="c xs" data-t="n" tabindex="0" role="button">{E(k)}<small>{int(dict(s_.EXW)[k] * 100)}%</small></th>' for k in names))
        return f'<div class="scroll"><table class="pt exctab" style="min-width:0"><thead><tr>{th}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    def exc_page(s_, pre):
        s = s_.s; allg = s_.exc_all()
        if not allg: return '<p class="muted">No finished games yet.</p>'
        def row(k, g, v):
            w_, x, y = g; wi = x if s.G[w_]["scores"][x] > s.G[w_]["scores"][y] else y; lo = y if wi == x else x
            return (f'<tr><td class="rk">{k}</td><td><a class="pn" href="{s_.gurl(w_, x, y, pre)}"><b>{E(s_.TN(wi, w_))}</b> over {E(s_.TN(lo, w_))}</a><small class="muted"> Week {w_}</small></td>'
                    f'<td class="r">{fp(s.G[w_]["scores"][wi])}-{fp(s.G[w_]["scores"][lo])}</td><td class="r"><span class="exm exmb" style="display:inline-block;vertical-align:middle;margin-right:8px" aria-hidden="true"><i style="width:{s_.exc_bar(v)}%"></i></span><b>{v:.1f}</b></td></tr>')
        tbl = lambda rows: f'<div class="scroll"><table class="pt exctop" style="min-width:0"><thead><tr><th></th><th>Game</th><th class="r">Score</th><th class="r">Excitement</th></tr></thead><tbody>{rows}</tbody></table></div>'
        n = len(allg)
        top = "".join(row(k, g, v) for k, (g, v) in enumerate(allg[:5], 1))
        bot = "".join(row(n - k, g, v) for k, (g, v) in enumerate(list(reversed(allg))[:5]))
        full = "".join(row(k, g, v) for k, (g, v) in enumerate(allg, 1))
        per = defaultdict(list)
        for (w_, x, y), v in allg: per[x].append(v); per[y].append(v)
        mg = sorted(s.R, key=lambda r: -(sum(per[r]) / len(per[r]) if per[r] else 0))
        mrows = "".join(f'<tr><td class="rk">{k}</td><td><span class="tat2x">{s_.logo(r, pre, "lgs")}<a href="{s_.turl(r, pre)}"><b>{E(s_.TN(r))}</b></a> <small class="muted">{E(s.M[r])}</small></span></td>'
                        f'<td class="r"><b>{sum(per[r]) / len(per[r]):.1f}</b></td><td class="r">{max(per[r]):.1f}</td><td class="r">{sum(1 for v in per[r] if v >= 60)}</td></tr>'
                        for k, r in enumerate(mg, 1) if per[r])
        return (f'<p class="intro">Every finished game, scored for drama from its play-by-play win chances. About 33 is a typical game, 70 or more is a classic.</p><details class="how"><summary>How it\'s scored</summary><p class="intro">Every finished game, rebuilt play by play. Excitement is a weighted average of six pieces, each a plain formula with no cap: Comeback 25% (60 x log10 of the odds against the winner at his lowest), Finish 20% (40 x win-chance movement in the last quarter of the game), Close 20% (100 minus 2.5 per point of margin), Drama 15% (20 x win-chance movement before that), Lead changes 10% (15 each time the lead in points changes hands) and Scoring 10% (combined points minus 150). About 33 is a typical game, 70 or more a classic, and a blowout can dip below 0.</p></details>'
                f'<div class="grid2"><section><h2>Most exciting</h2>{tbl(top)}</section><section><h2>Least exciting</h2>{tbl(bot)}</section></div>'
                f'<section><h2>Managers <small>average excitement of their games</small></h2><div class="scroll"><table class="pt" style="min-width:0"><thead><tr><th></th><th>Team</th><th class="r">Average</th><th class="r">Best</th><th class="r">60 or higher</th></tr></thead><tbody>{mrows}</tbody></table></div></section>'
                f'<section><h2>Every game</h2><p class="intro">Tap a column to sort. Each ring shows that piece as a share of the best ever in that piece.</p>{s_.exc_table(pre)}</section>')
    def exc_parts(s_, w, a, b):
        """The raw pieces of a finished game's drama, from its full play-by-play win probability:
        swing = total win-probability movement, comeback = how low the winner fell, flips = times it crossed 50%,
        late = movement in the last quarter of the game's plays, close = final margin, points = combined score."""
        s = s_.s; pts = s_.wp_series(w, a, b)
        if not pts or w not in s.G: return None
        A_, B_ = getattr(s_, "_ab", {}).get((w, a, b), (None, None))
        ck = (w, tuple(x[0] for x in A_), tuple(x[0] for x in B_)) if A_ is not None else None
        rows = getattr(s_, "_pbpF", {}).get(ck) if ck else None
        sa, sb = s.G[w]["scores"][a], s.G[w]["scores"][b]
        q = [pts[0][1]] + [r_[1] for r_ in rows] if rows else [x[1] for x in pts]
        fin_ = 1.0 if sa > sb else 0.0 if sb > sa else 0.5
        q = q + [fin_]
        if sa < sb: q = [1 - x for x in q]                 # from the winner's side
        pdef = max([((r_[5] - r_[4]) if sa >= sb else (r_[4] - r_[5])) for r_ in rows if len(r_) > 5] or [0.0])   # winner's worst projected deficit
        mv = [abs(q[k + 1] - q[k]) for k in range(len(q) - 1)]
        n4 = max(1, len(mv) // 4)
        fl, side_ = 0, None                                 # lead changes: the favorite flips (past 55% one way to past 55% the other)
        for x in q:
            sd_ = 1 if x > .55 else -1 if x < .45 else 0
            if sd_ and side_ and sd_ != side_: fl += 1
            if sd_: side_ = sd_
        lc, sg0 = 0, 0                                      # score lead changes: who's ahead in points so far, play by play
        for r_ in (rows or []):
            sg = (r_[2] > r_[3]) - (r_[2] < r_[3])
            if sg and sg0 and sg != sg0: lc += 1
            if sg: sg0 = sg
        return dict(early=sum(mv[:-n4]), swing=sum(mv), low=min(q[:-1]), flips=fl, leads=lc,
                    late=sum(mv[-n4:]), close=-abs(sa - sb), pts=sa + sb, pdef=max(0.0, pdef))
    EXW = (("Comeback", .25), ("Finish", .20), ("Close", .20), ("Drama", .15), ("Lead changes", .10), ("Scoring", .10))
    def exc_terms(s_, p):
        """Excitement pieces. Each one measures something different (no piece double counts another), each is a plain formula
        of a real stat on a scale where about 100 is a great mark, and none is capped either way:
        Comeback      60 x log10 of the odds against the winner at his lowest (5% = 77, 2% = 101; 0 if he never fell below 50%)
        Finish        40 x win-chance movement in the last quarter of the game's plays (2.5 = 100 points of movement)
        Close         100 minus 2.5 per point of final margin (a tie = 100, a 40-point blowout = 0, worse below)
        Drama         20 x win-chance movement before that last quarter (five full swings = 100)
        Lead changes  15 per time the lead in points changed hands, play by play
        Scoring       combined points minus 150 (250 combined = 100)"""
        lo_ = p["low"]
        return [("Comeback", (60 * math.log10((1 - lo_) / lo_) if lo_ < 0.5 else 0.0)), ("Finish", 40 * p["late"]),
                ("Close", 100 + 2.5 * p["close"]), ("Drama", 20 * p.get("early", p["swing"] - p["late"])),
                ("Lead changes", 15 * p["leads"]), ("Scoring", p["pts"] - 150)]
    @staticmethod
    def play_text(t, ks=None):
        """ESPN's play text, trimmed: no formation tags, tacklers, snappers, injury notes, penalty or replay fine print."""
        if re.search(r"the play was REVERSED\.", t or ""): t = re.split(r"the play was REVERSED\.\s*", t, 1)[1] or t   # keep the call that stood
        t = re.split(r"\s\*\*\s|\.?\s*PENALTY on|\.?\s*Penalty on|\.?\s*The Replay Official", t or "")[0]
        t = re.sub(r"\s*\((?:[^()]*)\)", "", t); t = re.sub(r"\s*\[[^\]]*\]", "", t); t = re.sub(r",?\s*Hit (Left|Right) Upright\.?", "", t)
        t = re.sub(r",?\s*(?:Center|Holder)-(?:[A-Z][A-Za-z'\-]*\.)?[A-Za-z'\-]+", "", t)
        NM = r"[A-Z][A-Za-z]*\.\s?[A-Z][A-Za-z'\-\.]*"
        for rx in (r"(?:" + NM + r"(?:\s+and\s+" + NM + r")*)\s+reported in as eligible\.?",   # who reported eligible, who got hurt, replay reviews
                   r"[A-Z]{2,3}-" + NM + r" was injured during the play\.?",
                   r"[A-Z][A-Za-z .]+ challenged the [^.]*?ruling, and the play was (?:Upheld|REVERSED)\.?",
                   r"The ruling on the field (?:stands|was confirmed)\.?",
                   r"The (?:ball spot|penalty|first down|runner's forward progress)[^.]*? (?:was|were) assisted by replay\.?",
                   r"\d+-second runoff avoided\.?",
                   r"Direct snap to " + NM + r"\.",
                   r",?\s*Hit (?:Left|Right) Upright\.?"):
            t = re.sub(r"\s*" + rx, "", t)
        t = re.sub(r"(yards?|gain|loss)\.(?=[A-Z][a-z])", r"\1. ", t); t = re.sub(r"(No Good|BLOCKED)(?![.,])", r"\1.", t)       # "yards.Minnesota" -> "yards. Minnesota"
        return re.sub(r"\s+", " ", t).strip()

    @staticmethod
    def play_simple(t):
        """A play in a few words for the record book: "Purdy to McCaffrey, 66-yd TD + 2-pt run", "Henry 2-yd TD run", "Bates 54-yd FG"."""
        t = re.sub(r"\s*\((?:[^()]*)\)", "", t or ""); t = re.sub(r"\s+", " ", t)
        ln = lambda n: re.sub(r"^[A-Z][a-z]*\.\s?", "", n).rstrip(".")           # "C.McCaffrey" -> "McCaffrey"
        NM = r"(?<![A-Za-z])([A-Z][a-z]{0,2}\.\s?[A-Z][A-Za-z'\-]*(?:(?<=St)\.\s[A-Z][A-Za-z'\-]+)?\.?)"     # "A.St. Brown" stays whole
        main = re.split(r"\s*TWO-POINT CONVERSION ATTEMPT\.|\s*" + NM + r" extra point", t)[0]
        td = "TOUCHDOWN" in main and "NULLIFIED" not in main
        yd = re.search(r"for (-?\d+) yards?", main); n = int(yd.group(1)) if yd else 0
        m = re.search(NM + r" pass [^.]*?to " + NM + r"[^.]*?for (-?\d+) yards?", main)
        if m: out = f"{ln(m.group(1))} to {ln(m.group(2))}, " + (f"{int(m.group(3))}-yd TD" if td else f"{int(m.group(3))} yds")
        elif re.search(r"INTERCEPTED by", main):
            q = re.search(NM + r" pass", main); out = (f"{ln(q.group(1))} " if q else "") + ("pick-six" if td else "intercepted")
        elif re.search(r"field goal is (GOOD|No Good|BLOCKED)", main):
            q = re.search(NM + r" (\d+) yard field goal is (GOOD|No Good|BLOCKED)", main)
            out = f"{ln(q.group(1))} {q.group(2)}-yd FG" + ("" if q.group(3) == "GOOD" else (" missed" if q.group(3) == "No Good" else " blocked")) if q else "Field goal"
        elif "sacked" in main:
            q = re.search(NM + r" sacked", main); out = (f"{ln(q.group(1))} sacked" if q else "Sack") + (", fumble lost" if "RECOVERED by" in main else "")
        elif re.search(r"punts|kicks", main) and td: out = "Return TD"
        else:
            q = re.search(NM + r" (?:scrambles |up the middle|left|right|kneels|pushed)", main) or re.search("^" + NM, main)
            out = (f"{ln(q.group(1))} " if q else "") + (f"{n}-yd TD run" if td else (f"{n}-yd run" if yd else "play"))
            if "FUMBLES" in main and "RECOVERED by" in main: out += ", fumble lost"
        tw = re.search(r"TWO-POINT CONVERSION ATTEMPT\.\s*(.*?)\s*ATTEMPT SUCCEEDS", t)
        if tw:
            q = re.search(NM + r" pass to " + NM, tw.group(1)); r_ = re.search(NM + r" (?:rushes|up the middle|left|right)", tw.group(1))
            out += f" + 2-pt ({ln(q.group(1))} to {ln(q.group(2))})" if q else (f" + 2-pt run ({ln(r_.group(1))})" if r_ else " + 2-pt")
        return out

    def chart_text(s_, t, who):
        import pbp as _pb
        """The play as it reads on ESPN, cut to what matters to this matchup: no tacklers or long snappers, and the extra point or
        two-point try only when someone in the matchup was in it. A kicker or two-point man alone sees just his part."""
        t = s_.play_text(t)                                                        # tags, tacklers, replay and injury notes
        t = re.sub(r"\s*\((?:[^()]*)\)", "", t)
        t = re.sub(r"\s*\[[^\]]*\]", "", t)                                   # [D.Olajiga]
        t = re.sub(r",?\s*Hit (Left|Right) Upright\.?", "", t)
        t = re.sub(r",?\s*(?:Center|Holder)-(?:[A-Z][A-Za-z'\-]*\.)?[A-Za-z'\-]+", "", t)
        t = re.sub(r"\s+", " ", t).strip()
        ks = {k_ for i in who if i.isdigit() for k_ in _pb.keys_of(s_.s.PL.get(i, {}).get("name", ""))}
        has = lambda x: any(re.search(r"(?<![A-Za-z])" + re.escape(k) + r"(?![a-z])", x) for k in ks)
        dfn = any(not i.isdigit() for i in who)
        parts = []
        m2 = re.search(r"TWO-POINT CONVERSION ATTEMPT\.\s*(.*?)\s*ATTEMPT (SUCCEEDS|FAILS)\.?", t)
        mx = re.search(r"(" + _pb.NM_ + r") extra point is (GOOD|No Good|BLOCKED)\.?", t)
        cut = min([m.start() for m in (m2, mx) if m] + [len(t)])
        main = t[:cut].strip()
        if has(main) or dfn or not (m2 or mx): parts.append(main)
        if mx and has(mx.group(0)): parts.append(f"{mx.group(1)} extra point is {mx.group(2)}.")
        if m2 and m2.group(2) == "SUCCEEDS" and (has(m2.group(1)) or not parts): parts.append(f"Two-point try: {m2.group(1).rstrip('.')}, good.")
        t = " ".join(p_ for p_ in parts if p_) or main
        # plain words: no pass direction, run gap or field spot, no trailing period
        t = re.sub(r"\bpass (incomplete )?(?:short|deep)(?: (?:left|right|middle))?(?= to| intended)", lambda m: "pass " + (m.group(1) or ""), t).replace("pass  ", "pass ")
        t = re.sub(r"\bscrambles (?:(?:left|right) (?:end|tackle|guard)|up the middle)", "scrambles", t)
        t = re.sub(r"\b(?:(?:left|right) (?:end|tackle|guard)|up the middle)\b", "runs", t)
        t = re.sub(r"\s+to (?:[A-Z]{2,3} )?-?\d+(?= for)", "", t)
        t = re.sub(r"\s+(?:pushed|ran) ob at (?:[A-Z]{2,3} )?-?\d+", "", t)
        t = re.sub(r",?\s*(?:Wide (?:Left|Right)|Hit (?:Left|Right) Upright)\.?", "", t)
        t = re.sub(r"\s+", " ", t).strip().rstrip(".").replace("., ", ", ")
        return t if len(t) <= 160 else t[:157].rsplit(" ", 1)[0] + "..."

    def play_impacts(s_):
        """Every scoring play of every finished game, with what it did: WPA, the change in the team's chance to win that matchup, and
        CPA, the title odds it added (WPA times what the game was worth: title odds with a win minus with a loss, as of that week's start).
        The clock running and projection changes between plays are left out; nobody gets credit for those.
        One row per team per play: (w, team, opp, game_url, when, quarter/clock text, play text, [(pid, pts)], wpa, cpa)."""
        if getattr(s_, "_pimp", None) is not None: return s_._pimp
        s = s_.s; out = []; TL = getattr(s, "tlev", None) or {}; cred = {}
        reg = s.L.get("regular_season_weeks", 14)
        e_txt = lambda ev: max(ev, key=lambda e: max(abs(q[2]) for q in e["who"]))["txt"] or ""
        for w, a, b, _ in s_.games:
            if w > s.last or w > reg: continue                     # finished weeks only
            pts = s_.wp_series(w, a, b)
            if not pts or (w, a, b) not in getattr(s_, "_wpos", {}): continue
            prow = None                                              # the last play-by-play row: rows share one projection basis,
            for k in range(len(pts)):                                # so row to row is the play alone (check-ins and logged updates don't count)
                x = pts[k]
                if not (x[0] == "·" and len(x) > 5): continue
                y, prow = prow, x
                if not x[5]: continue
                dp = x[1] - y[1] if y is not None else 0.0            # the week's very first row: its points count, its swing can't be measured
                for sd, (r, o) in enumerate(((a, b), (b, a))):
                    who = {}
                    for e in x[5]:
                        for q in e["who"]:
                            if q[1] == sd: who[q[0]] = who.get(q[0], 0.0) + q[2]
                    if not who: continue
                    g = dp if sd == 0 else -dp
                    lv = TL.get((w, r)) or TL.get((w + 1, r)) or TL.get((2, r))     # Week 1 has no earlier state to start from: Week 2's stands in
                    lev = (lv[0] - lv[1]) if lv else 0.0
                    tw = sum(abs(v) for v in who.values()) or 1.0
                    for pid, v in who.items():                                # each player's share of the swing, by his share of the points
                        c = cred.setdefault((w, r, pid), [0.0, 0.0]); c[0] += g * abs(v) / tw; c[1] += g * lev * abs(v) / tw
                    if sum(who.values()) <= 0: continue                       # the play list keeps the side whose player made the play
                    if re.match(r"(Two-Minute Warning|Timeout|End of|END |Official)", e_txt(x[5])): continue
                    e0 = max(x[5], key=lambda e: max(abs(q[2]) for q in e["who"]))
                    q = e0["q"]; qn = f"Q{q}" if q <= 4 else "OT"
                    clk = f"{qn} {int(e0['c']) // 60}:{int(e0['c']) % 60:02d}"
                    ptx = s_.play_text(e0["txt"])
                    if s.pos(max(who, key=lambda z: who[z])) != "K":           # the kick after a touchdown isn't part of the play unless it's his
                        ptx = re.sub(r"\s*TWO-POINT CONVERSION ATTEMPT\..*$", "", re.sub(r"\s*[A-Z][\w'.\-]* extra point is (GOOD|No Good|BLOCKED)\.?", "", ptx)).strip()
                    pb_, pa_ = (y[1], x[1]) if sd == 0 else (1 - y[1], 1 - x[1])
                    sc_ = (e0.get("aw"), e0.get("asc"), e0.get("hm"), e0.get("hsc"))
                    out.append((w, r, o, f"game/w{w}-{min(a, b)}-{max(a, b)}.html", x[4], clk, ptx,
                                sorted(who.items(), key=lambda z: -z[1]), g, g * lev, pb_, pa_, sc_, x[3] if sd == 0 else (x[3][1], x[3][0]), e0["txt"]))
        # What a start's WPA "should" be from its points alone, by position (a straight-line fit over every finished start):
        # the rest is clutch, when the points came and how close the game was. That part is the one that isn't skill.
        st_ = []
        for w in s.weeks:
            if w > s.last or w > reg: continue
            for r, d in s.W[w].items():
                for i, p in d["S"]:
                    if i != "0": st_.append((w, r, i, p, (cred.get((w, r, i)) or [0.0, 0.0])[0]))
        fit = {}
        for ps in {s.pos(x[2]) for x in st_}:
            xs = [x[3] for x in st_ if s.pos(x[2]) == ps]; ys = [x[4] for x in st_ if s.pos(x[2]) == ps]
            if len(xs) < 10: continue
            mx, my = sum(xs) / len(xs), sum(ys) / len(ys); vx = sum((v - mx) ** 2 for v in xs) or 1.0
            b_ = sum((u - mx) * (v - my) for u, v in zip(xs, ys)) / vx; fit[ps] = (my - b_ * mx, b_)
        s_._clutch = {(w, r, i): (wp, fit[s.pos(i)][0] + fit[s.pos(i)][1] * p) for w, r, i, p, wp in st_ if s.pos(i) in fit}
        # Check: every finished start with points should have plays behind them. A miss means the play-by-play couldn't find him
        # (ESPN wrote his name a way we don't know). Logged every build so it gets caught the same day.
        miss = [(w, r, i, p) for w, r, i, p, wp in st_ if abs(p) >= 1 and (w, r, i) not in cred and s.pos(i) != "DEF"]
        import pbp as _pb
        bad = []
        for w, a, b, _ in s_.games:
            if w > s.last or w > reg: continue
            for x in (s_.wp_series(w, a, b) or []):
                if not (x[0] == "·" and len(x) > 5 and x[5]): continue
                for e in x[5]:
                    for q in e["who"]:
                        if not q[0].isdigit(): continue
                        ks = _pb.keys_of(s.PL.get(q[0], {}).get("name", ""))
                        if ks and not any(re.search(r"(?<![A-Za-z])" + re.escape(k) + r"(?![a-z])", e["txt"] or "") for k in ks):
                            bad.append((w, q[0], q[2], (e["txt"] or "")[:90]))
        s_._pbpbad = bad
        # and every player's plays must add up to his final: the sum of what each play gave him vs his box-score points
        psum = defaultdict(float); seenp = set()
        for w, a, b, _ in s_.games:
            if w > s.last or w > reg: continue
            for x in (s_.wp_series(w, a, b) or []):
                if not (x[0] == "·" and len(x) > 5 and x[5]): continue
                for e in x[5]:
                    k_ = (w, e["q"], e["c"], e["txt"])
                    for q in e["who"]:
                        if q[0].isdigit() and (k_, q[0]) not in seenp: seenp.add((k_, q[0])); psum[(w, q[0])] += q[2]
        add_up = []
        for w, r, i, p, wp in st_:
            if not i.isdigit(): continue
            if abs(psum.get((w, i), 0.0) - p) > 0.15: add_up.append((w, i, round(psum.get((w, i), 0.0), 2), p))
        s_._pbpsum = add_up
        s_._pbpmiss = miss
        try:
            with open(os.path.join(getattr(s, "ddir", "data"), "pbp_check.txt"), "w") as f:
                f.write("# finished starts with points but no plays found in the play-by-play (should be empty)\n")
                for w, r, i, p in miss: f.write(f"{w}|{r}|{i}|{s.nm(i)}|{p}\n")
                for w, i, d, t in bad: f.write(f"credit not in play text|{w}|{i}|{s.nm(i)}|{d}|{t}\n")
                for w, i, ps, p in add_up: f.write(f"plays don't add up|{w}|{i}|{s.nm(i)}|plays {ps}|final {p}\n")
        except Exception: pass
        if miss: print(f"PBP CHECK: {len(miss)} start(s) with points but no plays:", ", ".join(f"W{w} {s.nm(i)} {p}" for w, r, i, p in miss[:12]))
        if add_up: print(f"PBP CHECK: {len(add_up)} start(s) where the plays don't add up to the final:", ", ".join(f"W{w} {s.nm(i)} {ps} vs {p}" for w, i, ps, p in add_up[:15]))
        if bad: print(f"PBP CHECK: {len(bad)} play(s) credit a player the text doesn't name:", "; ".join(f"W{w} {s.nm(i)} {d:+} on '{t[:50]}'" for w, i, d, t in bad[:8]))
        s_._pimp = out; s_._pcred = cred
        return out

    def play_of_game(s_, w, a, b):
        """The winner's biggest play: the one that moved the matchup most toward how it ended. (The biggest swing in a game came
        from the team that lost about a third of the time, so it has to be the winner's.)"""
        s = s_.s
        if w > s.last: return None
        sc = s.G[w]["scores"]; win = a if sc[a] > sc[b] else b if sc[b] > sc[a] else None
        if win is None: return None
        c = [x for x in s_.play_impacts() if x[0] == w and x[1] == win and {x[1], x[2]} == {a, b}]
        return max(c, key=lambda x: x[8]) if c else None

    def excitement(s_, w, a, b):
        """Excitement: the weighted average of the pieces (Comeback 25%, Finish 20%, Close 20%, Drama 15%, Lead changes 10%, Scoring 10%).
        Open-ended, one decimal: about 33 is a typical game, 70+ is a top-tenth classic, a blowout can go below 0."""
        s = s_.s
        if not hasattr(s_, "_exc"):
            parts = {}
            for w_ in s.weeks:
                for x, y in s.G[w_]["pairs"]:
                    p_ = s_.exc_parts(w_, x, y)
                    if p_: parts[(w_, min(x, y), max(x, y))] = p_
            wt = dict(s_.EXW)
            s_._exc = {g: round(sum(wt[k] * v for k, v in s_.exc_terms(p)), 1) for g, p in parts.items()}
            s_._excp = parts
        return s_._exc.get((w, min(a, b), max(a, b)))
    def exc_bar(s_, v):
        """Bar width for an excitement score: the most exciting game so far fills it."""
        top = max(list(getattr(s_, "_exc", {}).values()) or [100]); return max(0, min(100, round(100 * v / (top or 1))))
    def improbable(s_):
        """Every finished game: the winner's lowest win probability at any point, play by play."""
        if hasattr(s_, "_impr"): return s_._impr
        s = s_.s; out = []
        for w in s.weeks:
            for a, b in s.G[w]["pairs"]:
                pts = s_.wp_series(w, a, b)
                if not pts: continue
                wi = a if s.G[w]["scores"][a] > s.G[w]["scores"][b] else b; lo = b if wi == a else a
                xs = [(p if wi == a else 1 - p, lab if lab != "·" else "@" + when_) for lab, p, _g, _x, when_, *_e in pts[:-1]]
                low, lab = min(xs)
                df = max(((xb_ - xa_) if wi == a else (xa_ - xb_)) for _, _, _, (xa_, xb_), *_e in pts)     # most points the winner trailed by at any point
                out.append(dict(w=w, wi=wi, lo=lo, low=low, at=lab, down=max(df, 0.0)))
        s_._impr = out; return out
    def slot_end(s_, w, a, b, g):
        """When a time slot's games ended (or should end): the last play of its games, or kickoff + 3:15 for ones not over."""
        from zoneinfo import ZoneInfo
        ET = ZoneInfo("America/New_York"); UTC = datetime.timezone.utc
        K = getattr(s_, "_wkick", {}).get((w, a, b)) or {}
        GE = getattr(s_, "_pbp_end", {}).get(w) or {}
        ends = [datetime.datetime.strptime(GE[tm], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).astimezone(ET) for tm, k in K.items() if k == g and tm in GE]
        n_ = sum(1 for k in K.values() if k == g)
        H3 = datetime.timedelta(hours=3, minutes=15)
        return max(ends) if ends and len(ends) == n_ else max(ends + [g + H3])

    def lineup_now(s_, w, r):
        """Who counts as team r's starters for week w: the real lineup once the week is final; while it's on, everyone locked
        in plus the best projected players for the slots still open."""
        if w in s_.s.G: return [i for i, _ in s_.s.W[w][r]["S"] if i != "0"]
        t = s_.TEAM.get((w, r)) or {}
        return list(t.get("lineup") or [])
    def pregame_p(s_, w, a, b, tm, la=0.0, lb=0.0, kick=None):
        """Win chance for a at moment tm (before kickoff, or between games), redone with today's known lineups: points already
        banked at tm (la, lb), plus every lineup player whose game hadn't started by tm at the projection he had then.
        An empty slot (no one left who can fill it) counts as zero from the start."""
        s = s_.s; PH = (getattr(s, "phist", None) or {}).get(w)
        if not PH or not s_.proj: return None
        tz = tm.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
        cv = s_.T["cv"]; SPn = s.SP.get(w, {}); kick = kick or {}
        def team(r, locked):
            mu = var = 0.0
            for i in s_.lineup_now(w, r):
                ko = kick.get(s_.team_at(w, i))
                if ko is not None and ko <= tm: continue                     # already played by tm: his points are in locked
                now = s_.proj(i, w)[0]; h = PH.get(i)
                then = next((v for t_, v in reversed(h) if t_ <= tz), h[0][1]) if h else SPn.get(i, now)
                m = max(0.0, now + then - SPn.get(i, then)); mu += m; var += (cv.get(s.pos(i), 0.6) * m) ** 2
            return locked + mu * s_.f, math.sqrt(var) * s_.T["corr"] * s_.f
        A, B = team(a, la), team(b, lb)
        if A[0] <= 0 and B[0] <= 0: return None
        if A[1] + B[1] < 1e-6: return 1.0 if A[0] > B[0] else 0.0 if B[0] > A[0] else 0.5
        return s_.win_p(A, B)

    def proj_moves(s_, w, a, b, t0, t1):
        """Why the odds moved between t0 and t1 with no play in between: each lineup player whose projection changed, by how much,
        and each team's projected total then and now. Per-player history starts Week 12; before that, the logged team totals."""
        s = s_.s; PH = (getattr(s, "phist", None) or {}).get(w); U = datetime.timezone.utc
        z = lambda t: t.astimezone(U).strftime("%Y-%m-%dT%H:%MZ") if t is not None else ""
        z0, z1 = z(t0), z(t1)
        if PH and s_.proj:
            SPn = s.SP.get(w, {}); who = []; tot = {}
            for sd, r in enumerate((a, b)):
                T0 = T1 = 0.0
                for i in s_.lineup_now(w, r):
                    now = s_.proj(i, w)[0]; h = PH.get(i)
                    at = lambda zz: (next((v for t_, v in reversed(h) if t_ <= zz), h[0][1]) if h else SPn.get(i, now))
                    m0, m1 = (max(0.0, now + at(zz) - SPn.get(i, at(zz))) for zz in (z0 or "0", z1))
                    T0 += m0; T1 += m1
                    if abs(m1 - m0) * s_.f >= 0.1: who.append((i, sd, m0 * s_.f, m1 * s_.f))
                tot[r] = (T0 * s_.f, T1 * s_.f)
            return who, tot
        L = [x for x in (getattr(s, "mlog", []) or []) if int(x[1]) == w and {int(x[2]), int(x[3])} == {a, b}]
        def row(zz):
            r_ = None
            for x in L:
                if x[0] <= zz: r_ = x
            if not r_: return None
            pa_, pb_ = float(r_[5]), float(r_[6])
            return (pa_, pb_) if int(r_[2]) == a else (pb_, pa_)
        r0, r1 = row(z0) if z0 else None, row(z1)
        if not r1: return [], {}
        r0 = r0 or r1
        return [], {a: (r0[0], r1[0]), b: (r0[1], r1[1])}

    def wp_clean(s_, w, a, b, pts, dec):
        """Catcher for bad rows (late or stale feeds, snapshots that trail the play-by-play): drop any single point that jumps
        and then snaps right back while the score around it doesn't move, or whose score runs backward and then forward again.
        Each drop is printed to the build log as WPFIX so it can be traced."""
        if len(pts) < 4: return pts, dec
        P_ = getattr(s_, "_wpos", {}).get((w, a, b)); drop = set()
        tot = lambda x: (x[3][0] or 0) + (x[3][1] or 0) if x[3] else 0.0
        for k in range(1, len(pts) - 1):
            if k == dec or pts[k][0] != "·": continue         # slot ticks and labelled points stay
            km = next((j for j in range(k - 1, -1, -1) if pts[j][0] == "·"), None); kp = next((j for j in range(k + 1, len(pts)) if pts[j][0] == "·"), None)
            if km is None or kp is None: continue
            if tot(pts[km]) == 0 and tot(pts[kp]) == 0: continue   # before anyone scores, moves are news, not feed errors
            pa, pk, pb = pts[km][1], pts[k][1], pts[kp][1]
            jump, back = pk - pa, pb - pk
            blip = abs(jump) > 0.05 and jump * back < 0 and abs(pb - pa) < 0.35 * abs(jump) and abs(tot(pts[kp]) - tot(pts[km])) < 0.5
            stale = tot(pts[k]) + 1.0 < min(tot(pts[km]), tot(pts[kp])) and abs(tot(pts[kp]) - tot(pts[km])) < 0.1
            if blip or stale:
                drop.add(k); key = (w, a, b, str(pts[k][2]))
                if key not in getattr(s_, "_wpfix", set()):
                    s_.__dict__.setdefault("_wpfix", set()).add(key)
                    print(f"WPFIX week {w} {s_.M[a]} vs {s_.M[b]}: dropped {pts[k][2]} p={pk:.3f} ({'blip' if blip else 'stale score'})", file=sys.stderr)
        if not drop: return pts, dec
        keep = [k for k in range(len(pts)) if k not in drop]
        if P_ and len(P_) == len(pts): s_._wpos[(w, a, b)] = [P_[k] for k in keep]
        if dec is not None: dec = keep.index(dec) if dec in keep else next((j for j, k in enumerate(keep) if k > dec), len(keep) - 1)
        return [pts[k] for k in keep], dec

    def wp_anchor(s_, w, a, b, pts, kick, o0, oN, done):
        """Weave every logged update into the play-by-play line: the pre-kickoff odds from each update during the week
        (projection and injury news), and the live odds from each update during and between games. Each logged number goes on
        the chart at its time, and the play-by-play line is shifted to pass through them (the shift fades in time between two
        updates), so the line goes through every number the site posted and still moves on every play in between."""
        s = s_.s
        from zoneinfo import ZoneInfo
        ET = ZoneInfo("America/New_York"); UTC = datetime.timezone.utc
        k0 = min(kick.values()) if kick else None
        pe = lambda v: datetime.datetime.strptime(v, "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC).astimezone(ET)
        anc = []                                           # (time, p for a, score a, score b, label)
        for r_ in getattr(s, "mlog", []) or []:
            if int(r_[1]) != w or {int(r_[2]), int(r_[3])} != {a, b}: continue
            tm = pe(r_[0])
            if k0 and tm >= k0: continue
            p = float(r_[4]); p = p if int(r_[2]) == a else 1 - p
            anc.append((tm, p, 0.0, 0.0, f"Update, {tm.strftime('%a %-I:%M %p')} (before kickoff)"))
        for r_ in getattr(s, "livewp", []) or []:
            if int(r_[1]) != w or {int(r_[2]), int(r_[3])} != {a, b}: continue
            tm = pe(r_[0]); p = float(r_[4]); fl = int(r_[2]) == a
            if any(kk <= tm < kk + datetime.timedelta(hours=3.5) for kk in kick.values()): continue   # mid-game snapshots lag the play-by-play (Sleeper's points trail by a few plays); the play-by-play line already has it
            sa_, sb_ = (float(r_[5]), float(r_[6])) if fl else (float(r_[6]), float(r_[5]))
            anc.append((tm, p if fl else 1 - p, sa_, sb_, f"Update, {tm.strftime('%a %-I:%M %p')}"))
        anc.sort()
        T_ = lambda x: x[2] if x[0] == "·" else None
        KEY = lambda x: x[2] if x[0] == "·" else (None if x[2] is None else s_.slot_end(w, a, b, x[2]))
        timed = [(T_(x), x) for x in pts]
        def model_at(tm):                                  # the play-by-play line's own value at a moment
            v = o0
            for t_, x in timed:
                if t_ is not None and t_ <= tm: v = x[1]
            return v
        # Pre-kickoff updates were figured on the best projected lineup at the time. Once lineups are revealed (players locked at
        # kickoff, or the week is final), shift them so the last one lands on the model's kickoff number with the real starters:
        # the pregame story keeps its shape (news, waivers, projections) but ends where the actual lineups say it should.
        lg = lambda v: math.log(max(1e-6, min(1 - 1e-6, v)) / (1 - max(1e-6, min(1 - 1e-6, v))))
        ex = lambda v: 1 / (1 + math.exp(-v))
        preA = [x for x in anc if k0 and x[0] < k0]
        if anc and s_.pregame_p(w, a, b, anc[-1][0], anc[-1][2], anc[-1][3], kick) is not None:
            # projection history is on file: redo every logged update (before kickoff and between games) with the starters who
            # actually played or are locked in, each at the projection he had at that moment, the best lineup around them for slots
            # still open, and nothing for a slot nobody can fill. Lineup news then never shows up as a jump on game day.
            anc = [((x[0], (lambda q: x[1] if q is None else q)(s_.pregame_p(w, a, b, x[0], x[2], x[3], kick))) + tuple(x[2:])) for x in anc]
            preA = [x for x in anc if k0 and x[0] < k0]
            pre_shift = (preA[-1][1] - o0) if preA else pts[0][1] - o0
        elif preA:                                         # no projection history: keep the updates' shape, end them on the real lineups
            dl = lg(o0) - lg(preA[-1][1])
            anc = [((x[0], ex(lg(x[1]) + dl)) + tuple(x[2:])) if (k0 and x[0] < k0) else x for x in anc]
            preA = [x for x in anc if k0 and x[0] < k0]
            pre_shift = 0.0
        else: pre_shift = pts[0][1] - o0
        A = [(None, pre_shift)] + [(tm, p - model_at(tm)) for tm, p, *_ in anc if not (k0 and tm < k0)]
        end_t = max((t_ for t_, _ in timed if t_ is not None), default=None)
        A.append((end_t, (pts[-1][1] - oN) if not done else 0.0))
        def off(tm):
            if tm is None: return pre_shift
            prev = (k0, pre_shift)
            for ta, d in A[1:]:
                if ta is None: continue
                if tm <= ta:
                    span = (ta - prev[0]).total_seconds() if prev[0] else 0
                    lam = ((tm - prev[0]).total_seconds() / span) if span > 0 else 1.0
                    return prev[1] * (1 - lam) + d * lam
                prev = (ta, d)
            return prev[1]
        out = [pts[0]]
        for x in pts[1:-1]:
            tm = T_(x)
            if tm is None and x[2] is not None: tm = KEY(x)          # time-slot ticks shift with the line too, so they sit on it
            lo_, hi_ = (1e-4, 1 - 1e-4) if 0 < x[1] < 1 else (0.0, 1.0)   # a shift never turns a live chance into a sure thing
            out.append((x[0], min(hi_, max(lo_, x[1] + off(tm))) if tm is not None else x[1]) + x[2:])
        out.append(pts[-1])
        # logged updates as their own points, in time order among the plays
        npre = 0
        for tm, p, sa_, sb_, lab in anc:
            if done and k0 and tm > max(kick.values()) + datetime.timedelta(hours=5): continue
            xs = (sa_, sb_) if tm >= (k0 or tm) else (0.0, 0.0)
            pt = ("·", p, tm, xs, lab)
            j = next((k for k in range(1, len(out)) if KEY(out[k]) is not None and KEY(out[k]) > tm), None)
            if j is None:
                j = len(out) - 1 if not done else len(out)
            if (k0 and tm < k0) or j == 0: j = 1 + npre; npre += 1      # before kickoff: in time order right after the pregame point
            out.insert(j, pt)
        pre = [p for tm, p, *_ in anc if k0 and tm < k0]
        if pre: out[0] = (out[0][0], pre[0]) + tuple(out[0][2:])     # the line starts where the week's odds started, then follows each update to kickoff
        if not hasattr(s_, "_wpos"): s_._wpos = {}
        s_._wpos[(w, a, b)] = list(range(len(out)))
        return out

    def wp_axis(s_, w, a, b, pts, fut):
        """A real-time x axis: each slot's kickoff is a tick, plays sit at the time they happened, and time with no games on
        (overnight, Friday, Saturday) shrinks to a short gap. Returns (fractions for pts, fractions for fut, ticks)."""
        K = getattr(s_, "_wkick", {}).get((w, a, b)) or {}
        if not K: return None
        from zoneinfo import ZoneInfo
        ET = ZoneInfo("America/New_York"); UTC = datetime.timezone.utc
        GE = {tm: datetime.datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).astimezone(ET) for tm, v in (getattr(s_, "_pbp_end", {}).get(w) or {}).items()}
        H3 = datetime.timedelta(hours=3, minutes=15); GAP = 2400.0
        slots = sorted(set(K.values()))
        def end_of(g):
            ends = [GE[tm] for tm, k in K.items() if k == g and tm in GE]
            return max(ends) if ends and len(ends) == sum(1 for k in K.values() if k == g) else max(ends + [g + H3])
        iv = []
        for g in slots:
            e = end_of(g)
            if iv and g <= iv[-1][1]: iv[-1][1] = max(iv[-1][1], e)
            else: iv.append([g, e])
        # a window nobody in this game plays in is squeezed to a sliver (its tick stays, so every game that week reads alike)
        S_ = s_.s; done_ = w in S_.G and w <= S_.last
        ids_ = ([i for r in (a, b) for i, _ in S_.W[w][r]["S"]] if done_ and w in S_.W else
                [i for r in (a, b) for i in list(s_.lineup_now(w, r)) + list(S_.rost.get(r, []))])
        rel = {s_.team_at(w, i) for i in ids_ if i and i != "0"}
        segs = []; acc = GAP                                   # (start, end, axis offset at start, squeeze)
        for s0, e0 in iv:
            sc_ = 1.0 if any(s0 <= k <= e0 for t, k in K.items() if t in rel) else 0.12
            segs.append((s0, e0, acc, sc_)); acc += (e0 - s0).total_seconds() * sc_ + GAP
        tot = acc
        pre_t = [x[2] for x in pts if x[0] == "·" and x[2] is not None and x[2] < segs[0][0]]
        t_first = min(pre_t) - datetime.timedelta(hours=2) if pre_t else None
        def eff(tm):
            # between games the gap is short, but whatever was posted in it is spread across it by time
            if tm is None: return 0.0
            for k, (s0, e0, o, sc_) in enumerate(segs):
                if tm < s0:
                    if k == 0:
                        if not t_first: return GAP * 0.5
                        return GAP * 0.08 + GAP * 0.84 * max(0.0, (tm - t_first).total_seconds()) / max(1.0, (s0 - t_first).total_seconds())
                    prev = segs[k - 1]; lo = prev[2] + (prev[1] - prev[0]).total_seconds() * prev[3]; pe_ = prev[1]
                    return lo + GAP * (0.08 + 0.84 * (tm - pe_).total_seconds() / max(1.0, (s0 - pe_).total_seconds()))
                if tm <= e0: return o + (tm - s0).total_seconds() * sc_
            last = segs[-1]; lo = last[2] + (last[1] - last[0]).total_seconds() * last[3]
            return min(tot, lo + GAP * 0.5)
        def when_of(x):
            lab, g_ = x[0], x[2]
            if lab == "·": return g_
            if g_ is None: return None
            return s_.slot_end(w, a, b, g_)
        FR = [eff(when_of(x)) / tot for x in pts]
        for k in range(1, len(FR)):
            if FR[k] < FR[k - 1]: FR[k] = FR[k - 1]
        FF = [eff(end_of(f[2])) / tot for f in fut]
        ticks = []
        for g in slots:
            fx = eff(g) / tot
            if ticks and fx - ticks[-1][0] < 0.035: continue        # 4:05 and 4:25 share a tick
            lab_ = g.strftime("%-I:%M %p").replace(":00", "")
            if any(s0 <= g <= e0 and sc_ < 1 for s0, e0, _o, sc_ in segs): lab_ = ""          # a squeezed window: its line, no label
            elif ticks and fx - max([t[0] for t in ticks if t[1]] or [-1]) < 0.06: lab_ = ""
            ticks.append((fx, lab_, g.strftime("%a").upper()))
        return FR, FF, ticks

    def wp_chart(s_, w, a, b, pre):
        def sb(when, xa, xb, p, proj=False, ev=None, nev=None, prv=None, mix=None, pm=None):
            """The scoreboard over the charts: when, both teams' points so far and win chances, what each gained on this play, and the play."""
            inv = {x[1] for e in (ev or []) for x in e["who"]}                 # sides with a player on this play
            def dl(v, f, pctg=False, sd=None):
                if prv is not None and not pctg and sd in inv and abs(v) < 0.005: return f'<small class="sbd z">{0:+.{f}f}</small>'   # on the play, but a wash
                if prv is None or abs(v) < (0.0005 if pctg else 0.005): return '<small class="sbd"></small>'
                return f'<small class="sbd {"up" if v > 0 else "dn"}">{v * 100:+.1f}%</small>' if pctg else f'<small class="sbd {"up" if v > 0 else "dn"}">{v:+.{f}f}</small>'
            def row(r, x, q, col, x0, q0):
                return (f'<span class="sbr{" lead" if q > 0.5 else ""}"><i class="sbc" style="background:{col}"></i>{s_.logo(r, pre, "lgs", w)}'
                        f'<span class="sbn">{E(s_.TN(r, w))}</span><span class="sbv"><b class="sbs">{(f"{x:.1f}" if proj else fp(x))}</b>{dl(x - x0, 2, sd=(0 if r == a else 1)) if prv else dl(0, 2)}</span>'
                        f'<span class="sbv"><span class="sbp">{pct(q)}</span>{dl(q - q0, 1, True) if prv and q > q0 else dl(0, 1, True)}</span></span>')
            xa0, xb0, p0 = prv if prv else (xa, xb, p)
            if ev:                                     # the points this play was worth to each side, same as the chips
                ga = sum(x[2] for e in ev for x in e["who"] if x[1] == 0); gb = sum(x[2] for e in ev for x in e["who"] if x[1] == 1)
                xa0, xb0 = xa - ga, xb - gb
            split = ""
            def part(lbl, d):
                if abs(d) < 0.0005: return ""
                return f'<span>{lbl} <b class="up">{E(s_.M[a] if d > 0 else s_.M[b])} {abs(d) * 100:+.1f}%</b></span>'
            if ev and prv and mix is not None and abs(mix[0]) + abs(mix[1]) >= 0.003:   # the move since the last stop = projections + the clock + this play
                split = f'<span class="sbx">{part("Projections", mix[1])}{part("Clock since last play", mix[0])}{part("This play", mix[2])}</span>'
            elif not ev and not pm and prv and mix is not None and abs(mix[0] + mix[2]) + abs(mix[1]) >= 0.0005:   # a check-in with no play: the clock running out (and any projection news) is the whole move
                split = f'<span class="sbx">{part("Projections", mix[1])}{part("Clock since last play", mix[0] + mix[2])}</span>'
            left = f'<span class="sbL"><span class="sbh">{E(when)}</span>{row(a, xa, p, "#DCE3F0", xa0, p0)}{row(b, xb, 1 - p, "#C9A21A", xb0, 1 - p0)}{split}</span>'
            return left + ((pjblk(pm) if pm else play(ev, nev)) if PBP_ else "")
        def nfl_(t): return f'<i class="nfl N{t}" role="img" aria-label="{t}"></i>' if t in NFL_NICK else ""
        import pbp as _pb
        def ptxt(t, who): return s_.chart_text(t, who)
        def pjblk(pm):
            who, tot = pm
            tl = "".join(f'<span class="sbtt s{sd}">{E(s_.M[r])} <b>{t0:.1f}</b> to <b>{t1:.1f}</b></span>'
                         for sd, r in enumerate((a, b)) if r in tot for t0, t1 in [tot[r]] if abs(t1 - t0) >= 0.05)
            chips = "".join(f'<span class="sbw s{sd}">{s_.logo(a if sd == 0 else b, pre, "lgs", w)}{nfl_(s_.team_at(w, i))}'
                            f'<span class="sbwn">{E(s_.s.nm(i))}</span><b class="{"up" if m1 > m0 else "dn"}">{m0:.1f} to {m1:.1f}</b></span>'
                            for i, sd, m0, m1 in sorted(who, key=lambda z: -abs(z[3] - z[2]))[:6])
            return (f'<span class="sbpl"><span class="sbg"><b>Projection change</b></span>'
                    f'<span class="sbt">{tl or "No projection change"}</span><span class="sbws">{chips}</span></span>')
        def play(ev, nev=None):
            """The play behind this point: the NFL game's score and clock, what happened, and every matchup player it scored for."""
            if not ev: return f'<span class="sbpl none"><span class="sbt">{E(nev or "")}</span></span>'
            g0 = max(ev, key=lambda e: max(abs(x[2]) for x in e["who"]))       # the main play if two land at once
            tot = {}
            for e in ev:
                for pid, sd, d, *tt in e["who"]: tot[(pid, sd, tt[0] if tt else s_.team_at(w, pid))] = tot.get((pid, sd, tt[0] if tt else s_.team_at(w, pid)), 0.0) + d
            q = g0["q"]; qn = f"Q{q}" if q <= 4 else ("OT" if q == 5 else f"{q - 4}OT")
            gl = (f'<span class="sbg">{nfl_(g0["aw"])}<b>{E(g0["aw"])} {g0["asc"]}</b><span class="sbgx">at</span>{nfl_(g0["hm"])}<b>{E(g0["hm"])} {g0["hsc"]}</b>'
                  f'<span class="sbq">{qn} {int(g0["c"]) // 60}:{int(g0["c"]) % 60:02d}</span></span>')
            who = "".join(f'<span class="sbw s{sd}">{s_.logo(a if sd == 0 else b, pre, "lgs", w)}{nfl_(nt)}'
                          f'<span class="sbwn">{E(s_.s.nm(pid))}</span><b class="{"up" if d >= 0.005 else "dn" if d <= -0.005 else "z"}">{d:+.2f}</b></span>'
                          for (pid, sd, nt), d in sorted(tot.items(), key=lambda z: -abs(z[1])))
            return f'<span class="sbpl">{gl}<span class="sbt">{E(ptxt(g0["txt"], [x[0] for x in g0["who"]]))}</span><span class="sbws">{who}</span></span>'
        pts = s_.wp_series(w, a, b)
        PBP_ = (w, a, b) in getattr(s_, "_wpos", {}); PM_ = {}
        if pts:
            isrow = lambda x: x[0] == "·" and len(x) > 5                     # a play-by-play row (a play, or just the clock running)
            shw = [not (PBP_ and isrow(x) and not x[5] and k != len(pts) - 1) for k, x in enumerate(pts)]   # points the drag stops on
            PM_ = [k for k, x in enumerate(pts) if PBP_ and x[0] == "·" and len(x) == 5 and x[2] is not None]   # odds moves with no play: projections
            sh_, last_ = [], None
            for k in range(len(pts)): sh_.append(last_); last_ = k if shw[k] else last_
            MX_ = []                                                         # for each stop: (clock, projections, the play itself) since the last stop
            for k in range(len(pts)):
                j0 = sh_[k]
                if j0 is None or k == 0: MX_.append(None); continue
                ck = pj = 0.0
                for j in range(j0 + 1, k):
                    d = pts[j][1] - pts[j - 1][1]
                    if isrow(pts[j - 1]): ck += d
                    else: pj += d                                            # first play-by-play row after a logged update: today's projections take over
                MX_.append((ck, pj, pts[k][1] - pts[k - 1][1]))
            PM_ = {k: s_.proj_moves(w, a, b, next((pts[j][2] for j in range(k - 1, -1, -1) if pts[j][2] is not None and not isrow(pts[j])), None), pts[k][2])
                   for k in PM_}
        if not pts or len(pts) < 2: return ""
        fut = getattr(s_, "_fut", {}).get((w, a, b), [])
        Wd, Hd, L, R, T_, B_ = 680, 268, 118, 44, 18, 58
        AX = s_.wp_axis(w, a, b, pts, fut)
        POS = getattr(s_, "_wpos", {}).get((w, a, b)) or list(range(len(pts)))
        n = len(pts) - 1; nck = int(round(POS[-1])); N = nck + len(fut)
        if AX:                                                  # real time: kickoffs are the ticks, plays sit where they happened
            FR, FF, TK = AX
            px = lambda q: L + q * (Wd - L - R); POS = FR; QF = FF
        else:
            px = lambda k: L + k * (Wd - L - R) / max(N, 1); QF = [nck + j + 1 for j in range(len(fut))]; TK = None
        py = lambda p: T_ + (Hd - T_ - B_) * (1 - p)
        X = [px(q) for q in POS]; Y = [py(p) for _, p, *_ in pts]
        for k in range(1, len(X)):
            if X[k] <= X[k - 1]: X[k] = X[k - 1] + 0.01
        # monotone cubic (Fritsch-Carlson): smooth, never overshoots 0% or 100%
        d = [(Y[k + 1] - Y[k]) / (X[k + 1] - X[k]) for k in range(n)]
        m = [d[0]] + [0.0 if d[k - 1] * d[k] <= 0 else (d[k - 1] + d[k]) / 2 for k in range(1, n)] + [d[-1]]
        for k in range(n):
            if d[k] == 0: m[k] = m[k + 1] = 0.0
            else:
                al, be = m[k] / d[k], m[k + 1] / d[k]; h = al * al + be * be
                if h > 9: t = 3 / math.sqrt(h); m[k] = t * al * d[k]; m[k + 1] = t * be * d[k]
        path = f"M{X[0]:.1f},{Y[0]:.1f}" + "".join(
            f" C{X[k] + (X[k + 1] - X[k]) / 3:.1f},{Y[k] + m[k] * (X[k + 1] - X[k]) / 3:.1f} {X[k + 1] - (X[k + 1] - X[k]) / 3:.1f},{Y[k + 1] - m[k + 1] * (X[k + 1] - X[k]) / 3:.1f} {X[k + 1]:.1f},{Y[k + 1]:.1f}" for k in range(n))
        if (w, a, b) in getattr(s_, "_wpos", {}):          # play by play: straight segments, every swing as it happened
            path = f"M{X[0]:.1f},{Y[0]:.1f}" + "".join(f" L{X[k]:.1f},{Y[k]:.1f}" for k in range(1, len(X)))
        gid = f"wpg{w}x{a}x{b}"; mid = py(0.5); off = (mid - T_) / (Hd - T_ - B_)
        g = (f'<defs><linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="0" y1="{T_}" x2="0" y2="{Hd - B_}">'
             f'<stop offset="{off:.4f}" stop-color="var(--turf)"/><stop offset="{off:.4f}" stop-color="#C9A21A"/></linearGradient>'
             f'<linearGradient id="{gid}f" gradientUnits="userSpaceOnUse" x1="0" y1="{T_}" x2="0" y2="{Hd - B_}">'
             f'<stop offset="0" stop-color="var(--turf)" stop-opacity=".22"/><stop offset="{off:.4f}" stop-color="var(--turf)" stop-opacity=".04"/>'
             f'<stop offset="{off:.4f}" stop-color="#C9A21A" stop-opacity=".06"/><stop offset="1" stop-color="#C9A21A" stop-opacity=".3"/></linearGradient></defs>')
        for v in (0, 0.25, 0.75, 1):
            g += f'<line x1="{L}" x2="{Wd - R}" y1="{py(v):.1f}" y2="{py(v):.1f}" stroke="var(--rule)" stroke-width="1" stroke-dasharray="4 4"/>'
        g += f'<path d="{path} L{X[-1]:.1f},{mid:.1f} L{X[0]:.1f},{mid:.1f} Z" fill="url(#{gid}f)"/>'
        g += f'<line x1="{L}" x2="{Wd - R}" y1="{mid:.1f}" y2="{mid:.1f}" stroke="#B6412E" stroke-width="2"/>'
        g += f'<text x="{Wd - R + 8}" y="{mid + 5:.1f}" font-size="14" font-weight="800" fill="#B6412E">50%</text>'          # the ends are marked by the logos on the left
        lg = lambda r, y: f'<foreignObject x="2" y="{y - 13:.1f}" width="26" height="26"><i class="im L{r}" style="display:block;width:26px;height:26px" aria-hidden="true"></i></foreignObject>'
        g += (lg(a, py(1)) + f'<text x="33" y="{py(1) + 5:.1f}" font-size="13" font-weight="700" fill="var(--turf)">{E(s_.M[a])}</text>'
              + lg(b, py(0)) + f'<text x="33" y="{py(0) + 5:.1f}" font-size="13" font-weight="700" fill="#A8860F">{E(s_.M[b])}</text>')
        days = []; QP = list(POS) + list(QF)
        if TK:                       # ticks at each kickoff, day bands under them
            for fx, tl, dname in TK:
                g += (f'<line x1="{px(fx):.1f}" x2="{px(fx):.1f}" y1="{T_}" y2="{Hd - B_}" stroke="var(--rule)" stroke-width="1"/>'
                      f'<text x="{px(fx):.1f}" y="{Hd - 34}" text-anchor="middle" font-size="14" fill="var(--mute)">{E(tl)}</text>')
                if days and days[-1][0] == dname: days[-1][2] = fx
                else: days.append([dname, fx, fx])
            days = [[dn, x0, x1, True] for dn, x0, x1 in days]
        else:
            for k, (lab, _, g_, *_r) in enumerate(list(pts) + [(f[0], f[1], f[2]) for f in fut]):
                tl = "Pregame" if g_ is None else g_.strftime("%-I:%M %p").replace(":00", "")          # 9:30 AM, 1 PM, 4:05 PM, 8:20 PM: the day bands below say which day
                if lab != "·": g += f'<text x="{px(QP[k]):.1f}" y="{Hd - 34}" text-anchor="middle" font-size="14" fill="var(--mute)">{E(tl)}</text>'
                if g_ is not None and lab != "·":
                    dname = g_.strftime("%a").upper()
                    if days and days[-1][0] == dname: days[-1][2] = k
                    else: days.append([dname, k, k])
            days = [[dn, QP[k0], QP[k1], True] for dn, k0, k1 in days]
        for dname, q0, q1, _x in days:
            x0, x1 = px(q0) - 14, px(q1) + 14
            g += (f'<line x1="{x0:.1f}" x2="{x1:.1f}" y1="{Hd - 24}" y2="{Hd - 24}" stroke="var(--rule)" stroke-width="2"/>'
                  f'<text x="{(x0 + x1) / 2:.1f}" y="{Hd - 8}" text-anchor="middle" font-size="13" font-weight="700" letter-spacing=".06em" fill="var(--ink)">{dname}</text>')
        if fut:          # projected rest of the week: gray dotted, from the latest real point
            fx = [X[-1]] + [px(q) for q in QF]; fy = [Y[-1]] + [py(f[1]) for f in fut]
            g += f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in zip(fx, fy))}" fill="none" stroke="#9AA3B2" stroke-width="2" stroke-dasharray="3 5" stroke-linecap="round"/>'
            for x, y, f in zip(fx[1:], fy[1:], fut):
                tl_ = f[2].strftime("%-I:%M %p").replace(":00", ""); xa, xb = f[3]
                card = sb(f'After the {tl_} game{"s" if f[4] > 1 else ""}, {f[2].strftime("%a %b %-d")} (projected)', xa, xb, f[1], True)
                g += (f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="var(--paper)" stroke="#9AA3B2" stroke-width="1.5"/>'
                      f'<circle class="wpd" cx="{x:.1f}" cy="{y:.1f}" r="22" fill="transparent" data-x="{x / Wd * 100:.2f}" data-y="{y / Hd * 100:.2f}" data-card="{E(card)}" tabindex="0" role="button"/>')
        g += f'<path d="{path}" fill="none" stroke="url(#{gid})" stroke-width="3.5" stroke-linecap="round"/>'
        dk = s_._dec.get((w, a, b))
        if dk is not None and w in s_.s.G:     # the moment it was over: ring it; the line then rides 100% to the end of the week
            col = "var(--turf)" if pts[dk][1] == 1 else "#C9A21A"; yy = Y[dk]
            g += (f'<circle cx="{X[dk]:.1f}" cy="{yy:.1f}" r="11" fill="none" stroke="{col}" stroke-width="2.5"/>'
                  ''
                  )
        for k, (lab, p, _, (xa, xb), when, *ev_) in enumerate(pts):
            card = sb(when, xa, xb, p, prv=((pts[sh_[k]][3][0], pts[sh_[k]][3][1], pts[sh_[k]][1]) if sh_[k] is not None else None), mix=MX_[k], pm=PM_.get(k), ev=ev_[0] if ev_ else None, nev=("Pregame odds" if k == 0 else "Latest update" if lab == "·" else "Final" if "final" in str(when) else "Final whistle, no time left to score"))
            pl_ = lab == "·" and (w, a, b) in getattr(s_, "_wpos", {})          # a play-by-play point: no dot, a small tap target
            if pl_ and not shw[k]: continue      # nobody in the matchup scored on it: the line keeps it, dragging skips it
            g += (f'<circle class="wpd" cx="{X[k]:.1f}" cy="{Y[k]:.1f}" r="{6 if pl_ else 22}" fill="transparent" '
                  f'data-x="{X[k] / Wd * 100:.2f}" data-y="{Y[k] / Hd * 100:.2f}" data-card="{E(card)}"{"" if pl_ else ' tabindex="0" role="button"'}/>'
                  + ("" if pl_ else f'<circle class="wpdv" cx="{X[k]:.1f}" cy="{Y[k]:.1f}" r="4" fill="{"var(--turf)" if p >= 0.5 else "#C9A21A"}" stroke="var(--paper)" stroke-width="1.5"/>'))
        # ---- game flow: both teams' running totals at the same time slots
        sa_ = [x[3][0] for x in pts]; sb_ = [x[3][1] for x in pts]
        fa_ = [f[3][0] for f in fut]; fb_ = [f[3][1] for f in fut]
        top = max(sa_ + sb_ + fa_ + fb_ + [10]) * 1.08
        fy_ = lambda v: T_ + (Hd - T_ - B_) * (1 - v / top)
        Lf = 30; pxf = (lambda q: Lf + q * (Wd - Lf - R)) if TK else (lambda k: Lf + k * (Wd - Lf - R) / max(N, 1)); XF = [pxf(q) for q in POS]
        h2 = ""
        step = 25 if top < 160 else 50
        for v in range(0, int(top) + 1, step):
            h2 += (f'<line x1="{Lf}" x2="{Wd - R}" y1="{fy_(v):.1f}" y2="{fy_(v):.1f}" stroke="var(--rule)" stroke-dasharray="2 4"/>'
                   f'<text x="{Wd - R + 8}" y="{fy_(v) + 4:.1f}" font-size="12" fill="var(--mute)">{v}</text>')
        if TK:
            for fx_, tl, _d in TK:
                h2 += (f'<line x1="{pxf(fx_):.1f}" x2="{pxf(fx_):.1f}" y1="{T_}" y2="{Hd - B_}" stroke="var(--rule)" stroke-width="1"/>'
                       f'<text x="{pxf(fx_):.1f}" y="{Hd - 34}" text-anchor="middle" font-size="14" fill="var(--mute)">{E(tl)}</text>')
        else:
            for k, (lab, _, g_, *_r) in enumerate(list(pts) + [(f[0], f[1], f[2]) for f in fut]):
                tl = "Pregame" if g_ is None else g_.strftime("%-I:%M %p").replace(":00", "")
                if lab != "·": h2 += f'<text x="{pxf(QP[k]):.1f}" y="{Hd - 34}" text-anchor="middle" font-size="14" fill="var(--mute)">{E(tl)}</text>'
        for dname, q0, q1, _x in days:
            x0, x1 = pxf(q0) - 14, pxf(q1) + 14
            h2 += (f'<line x1="{x0:.1f}" x2="{x1:.1f}" y1="{Hd - 24}" y2="{Hd - 24}" stroke="var(--rule)" stroke-width="2"/>'
                   f'<text x="{(x0 + x1) / 2:.1f}" y="{Hd - 8}" text-anchor="middle" font-size="13" font-weight="700" letter-spacing=".06em" fill="var(--ink)">{dname}</text>')
        ln = lambda vs, xs: " ".join(f"{x:.1f},{fy_(v):.1f}" for x, v in zip(xs, vs))
        if fut:
            fx = [XF[-1]] + [pxf(q) for q in QF]
            h2 += (f'<polyline points="{ln([sa_[-1]] + fa_, fx)}" fill="none" stroke="var(--turf)" stroke-width="2" stroke-dasharray="3 5" opacity=".55"/>'
                   f'<polyline points="{ln([sb_[-1]] + fb_, fx)}" fill="none" stroke="#C9A21A" stroke-width="2" stroke-dasharray="3 5" opacity=".7"/>')
        h2 += (f'<polyline points="{ln(sb_, XF)}" fill="none" stroke="#C9A21A" stroke-width="3" stroke-dasharray="7 4" stroke-linejoin="round"/>'
               f'<polyline points="{ln(sa_, XF)}" fill="none" stroke="var(--turf)" stroke-width="3.2" stroke-linejoin="round"/>')
        for k, (lab, p, _, (xa, xb), when, *ev_) in enumerate(pts):
            card = sb(when, xa, xb, p, prv=((pts[sh_[k]][3][0], pts[sh_[k]][3][1], pts[sh_[k]][1]) if sh_[k] is not None else None), mix=MX_[k], pm=PM_.get(k), ev=ev_[0] if ev_ else None, nev=("Pregame odds" if k == 0 else "Latest update" if lab == "·" else "Final" if "final" in str(when) else "Final whistle, no time left to score"))
            pl_ = lab == "·" and (w, a, b) in getattr(s_, "_wpos", {})
            if pl_ and not shw[k]: continue
            if pl_:                                  # play-by-play points: no dot, but dragging across the chart stops on each one
                h2 += f'<circle class="wpd wpq" cx="{XF[k]:.1f}" cy="{fy_(max(xa, xb)):.1f}" r="0" data-x="{XF[k] / Wd * 100:.2f}" data-card="{E(card)}"/>'
                continue
            for v in (xa, xb):
                h2 += f'<circle class="wpd" cx="{XF[k]:.1f}" cy="{fy_(v):.1f}" r="{5 if pl_ else 16}" fill="transparent" data-x="{XF[k] / Wd * 100:.2f}" data-y="{fy_(v) / Hd * 100:.2f}" data-card="{E(card)}"{"" if pl_ else ' tabindex="0" role="button"'}/>'
            if not pl_:
                h2 += (f'<circle cx="{XF[k]:.1f}" cy="{fy_(xa):.1f}" r="3.5" fill="var(--turf)" stroke="var(--paper)" stroke-width="1.5" pointer-events="none"/>'
                       f'<circle cx="{XF[k]:.1f}" cy="{fy_(xb):.1f}" r="3.5" fill="#C9A21A" stroke="var(--paper)" stroke-width="1.5" pointer-events="none"/>')
        lc, prev = 0, 0
        for xa, xb in zip(sa_, sb_):
            sg = (xa > xb) - (xa < xb)
            if sg and prev and sg != prev: lc += 1
            if sg: prev = sg
        if w in s_.s.G and s_.excitement(w, a, b) is not None: lc = s_._excp[(w, min(a, b), max(a, b))].get("leads", lc)   # every play, same count as the record
        fh = (f'<div class="gfh"><div class="gft1">{s_.logo(a, pre, "lgs")}<div><b>{fp(sa_[-1])}</b><small><i class="gfl"></i>{E(s_.M[a])}</small></div></div>'
              f'<div class="gfm"><b>{lc}</b><small>Lead change{"" if lc == 1 else "s"}</small></div>'
              f'<div class="gft1 r"><div><b>{fp(sb_[-1])}</b><small>{E(s_.M[b])}<i class="gfl d"></i></small></div>{s_.logo(b, pre, "lgs")}</div></div>')
        lows = ""
        if (w, a, b) in getattr(s_, "_wpos", {}) and len(pts) > 2:          # each side's low point, play by play
            body = pts[:-1] if w in s_.s.G else pts
            def low_(sd):
                k = min(range(len(body)), key=lambda k: body[k][1] if sd == a else 1 - body[k][1]); x = body[k]
                pv = x[1] if sd == a else 1 - x[1]; dn = (x[3][1] - x[3][0]) if sd == a else (x[3][0] - x[3][1])
                wh = "before kickoff" if x[0] == "Pregame" else x[4].replace("Live, ", "") if x[0] == "·" else ("after the " + x[0] + " games")
                dmax = max(((y[3][1] - y[3][0]) if sd == a else (y[3][0] - y[3][1])) for y in body)
                return (f'<div class="wlo"><span class="k">{E(s_.M[sd])}</span><b>{pct(pv)}</b><small>lowest win chance, {E(wh)}'
                        + (f'. Trailed by up to {dmax:.1f}' if dmax > 0.05 else ". Never trailed") + '</small></div>')
            if w in s_.s.G:                 # finished: only the winner's low point means anything (the loser's ends at 0%)
                wi_ = a if s_.s.G[w]["scores"][a] > s_.s.G[w]["scores"][b] else b
                lows = f'<div class="wlos one">{low_(wi_)}</div>'
            else: lows = f'<div class="wlos">{low_(a)}{low_(b)}</div>'
        # the whole game as a table, Baseball Reference style: every play that scored for someone in the matchup
        tb_rows = []; prev_ = None; last_sc = None
        for x in pts:
            if not (x[0] == "·" and len(x) > 5): continue
            y_, prev_ = prev_, x
            if not x[5]: continue
            dp_ = (x[1] - y_[1]) if y_ is not None else 0.0
            e0 = max(x[5], key=lambda e: max(abs(q[2]) for q in e["who"]))
            tot_ = {}
            for e in x[5]:
                for q in e["who"]: tot_[(q[0], q[1])] = tot_.get((q[0], q[1]), 0.0) + q[2]
            q_ = e0["q"]; qn_ = f"Q{q_}" if q_ <= 4 else "OT"
            who_ = "".join(f'<span class="pbw s{sd}">{s_.logo(a if sd == 0 else b, pre, "lgs", w)}{E(s_.s.nm(i))} <b class="{"up" if d >= 0.005 else "dn" if d <= -0.005 else "z"}">{d:+.2f}</b></span>'
                           for (i, sd), d in sorted(tot_.items(), key=lambda z: -abs(z[1])))
            ca = last_sc is None or abs(x[3][0] - last_sc[0]) > 1e-6; cb = last_sc is None or abs(x[3][1] - last_sc[1]) > 1e-6; last_sc = x[3]
            ga, gb = dp_ > 0.0005, dp_ < -0.0005                          # who the play moved toward
            tb_rows.append(f'<tr><td class="pbt">{E(str(x[2].strftime("%a %-I:%M %p") if hasattr(x[2], "strftime") else ""))}<small>{qn_} {int(e0["c"]) // 60}:{int(e0["c"]) % 60:02d}</small></td>'
                           f'<td class="pbg">{E(str(e0.get("aw", "")))} {e0.get("asc", "")}-{e0.get("hsc", "")} {E(str(e0.get("hm", "")))}</td>'
                           f'<td class="pbp">{E(s_.play_simple(e0["txt"]))}<div class="pbws">{who_}</div></td>'
                           f'<td class="r pbn{" chg" if ca else ""}">{fp(x[3][0])}</td><td class="r pbn{" chg" if cb else ""}">{fp(x[3][1])}</td>'
                           f'<td class="r pbn{" up" if ga else ""}">{pct(x[1])}</td><td class="r pbn{" up" if gb else ""}">{pct(1 - x[1])}</td>'
                           f'<td class="r pba">{"" if abs(dp_) < 0.0005 else f"{abs(dp_) * 100:+.1f}%"}<small>{"" if abs(dp_) < 0.0005 else E(s_.M[a if ga else b])}</small></td></tr>')
        pbp_tbl = (f'<details class="pbtab"><summary>Every play, as a table</summary><div class="pbsc"><table><thead><tr><th>When</th><th>NFL score</th><th>Play</th>'
                   f'<th class="r">{E(s_.M[a])}</th><th class="r">{E(s_.M[b])}</th><th class="r">{E(s_.M[a])} win %</th><th class="r">{E(s_.M[b])} win %</th><th class="r">Swing</th></tr></thead>'
                   f'<tbody>{"".join(tb_rows)}</tbody></table></div><p class="note" style="margin:6px 0 0">Bold: the score that changed on that play, and the win chance that went up.</p></details>') if tb_rows else ""
        _lp = pts[-1]; _lev = next((x[5] for x in reversed(pts) if len(x) > 5 and x[5]), None)
        sbdef = sb(("Now, " if (w not in s_.s.G and s_.wk_live(w)) else "") + str(_lp[4]), _lp[3][0], _lp[3][1], _lp[1], ev=_lev, nev="Latest", prv=(_lp[3][0], _lp[3][1], _lp[1]) if _lev else None)   # the latest score and odds, with the most recent play
        return (f'<section><h2>Win probability and game flow</h2><div class="panel wpc"><div class="rtog chips gft" role="group" aria-label="Chart">'
                f'<button type="button" data-g="wp" aria-pressed="true">Win probability</button><button type="button" data-g="gf" aria-pressed="false">Game flow</button>'
                f'<span class="wpstep"><button type="button" class="wps" data-d="-1" aria-label="Previous play or update">&#8249; Prev</button><button type="button" class="wps" data-d="1" aria-label="Next play or update">Next &#8250;</button></span></div>'
                f'<div class="wpcard" data-def="{E(sbdef)}">{sbdef}</div><div class="gfv" data-g="wp"><svg viewBox="0 0 {Wd} {Hd}" width="100%" role="img" aria-label="Win probability by game time slot">{g}<line class="wpg" x1="0" x2="0" y1="{T_}" y2="{Hd - B_}" stroke="var(--ink)" stroke-width="1" stroke-dasharray="3 3" opacity="0" pointer-events="none"/></svg><p class="note wphint">Press and drag across either chart to see every play.</p>'
                f'<div class="wplg"><span><i class="sw" style="background:var(--turf)"></i>{E(s_.M[a])} favored</span><span><i class="sw" style="background:#C9A21A"></i>{E(s_.M[b])} favored</span>'
                f'{"<span><i class=swd></i>Projection</span>" if fut else ""}</div>{lows}</div>'
                f'<div class="gfv" data-g="gf" hidden>{fh}<svg viewBox="0 0 {Wd} {Hd}" width="100%" role="img" aria-label="Points by game time slot">{h2}<line class="wpg" x1="0" x2="0" y1="{T_}" y2="{Hd - B_}" stroke="var(--ink)" stroke-width="1" stroke-dasharray="3 3" opacity="0" pointer-events="none"/></svg>'
                f'<p class="note" style="margin:4px 0 0">Points so far, play by play. Drag across it or tap a dot.</p></div>{pbp_tbl}</div></section>')

    # ------------------------------------------------------------------ game pages
    def game_nav(s_, w, a, b, pre):
        s = s_.s; done = w in s.G
        gl = s.G[w]["pairs"] if done else s.fut.get(w, [])
        chips = "".join(f'<a href="{s_.gurl(w, x, y, pre)}"{" aria-current=page" if {x, y} == {a, b} else ""}>{E(s_.M[x])} v {E(s_.M[y])}</a>' for x, y in gl)
        return f'<nav class="subnav" aria-label="Week {w} games"><div class="wrap">{chips}</div></nav>'

    def board(s_, w, a, b, pre, sa, sb, mid, done, extra=None):
        """extra: {r: [(label, value), ...]} shown under each score."""
        def side(r, sc, lost):
            ex = "".join(f'<span><b>{v}</b>{k}</span>' for k, v in (extra or {}).get(r, []))
            return (f'<div class="tmw"><a class="tm" href="{s_.turl(r, pre)}">{s_.logo(r, pre, "lgh")}<b>{E(s_.TN(r))}</b><small>{E(s_.M[r])}, {s_.rec_str(r, w - 1) if done else s_.rec_str(r)}</small></a>'
                    f'<div class="sc {"l" if lost else ""}">{sc}</div>{f"<div class=bx>{ex}</div>" if ex else ""}</div>')
        la = done and float(sa) < float(sb); lb = done and float(sb) < float(sa)
        return f'<div class="board">{side(a, sa, la)}<div class="mid">{mid}</div>{side(b, sb, lb)}</div>'

    def order_slots(s_, rows):
        """rows: [(slot, id, pts, sub, cls)] in Sleeper slot order. Sort repeated slots (RB, WR) by points and label them RB1, RB2..."""
        out_ = []; k = 0
        while k < len(rows):
            j = k
            while j < len(rows) and rows[j][0] == rows[k][0]: j += 1
            grp = sorted(rows[k:j], key=lambda x: -x[2])
            for n_, x in enumerate(grp, 1): out_.append((x[0] + (str(n_) if j - k > 1 else ""),) + tuple(x[1:]))
            k = j
        return out_

    def slot_rows(s_, A, B, total, mvp=None, fmt=None, wk=None, hl=True, kw=None):
        """A, B: aligned lists of (slot, player_id or None, pts, sub, cls). The higher of each pair is highlighted."""
        s = s_.s; wk_ = kw if kw is not None else wk
        def cell(x, right, up):
            _, i, p, sub, cls = x
            if i is None: return f'<div class="pl {"right" if right else ""}"><div class="who"><b class="muted">Empty</b></div><div class="pts">0.0</div></div>'
            team = s_.team_at(wk_, i)
            badge = '<span class="mvpb">MVP</span>' if (mvp and (i in mvp if isinstance(mvp, (set, list, tuple)) else i == mvp)) else ""
            cw = wk if wk is not None else (kw if sub[0] == "final" else None)          # live week: games underway or over have real stats too
            card = f' data-card="{E(s_.statcard(cw, i, p))}" tabindex="0" role="button"' if cw is not None else ""
            kt = s_.kick_str(wk_, team); dot = '<i class="ksep" aria-hidden="true"></i>'
            if team in s.byes.get(wk_, []) and not p:          # bye week: a chip, not 0.0
                return (f'<div class="pl {"right" if right else ""}"><div class="who"><b>{s_.pa(i, s.nm(i))}</b><small>{s_.nl_r(team) if right else s_.nl(team)}</small></div>'
                        f'<div class="pts"><span class="byec">BYE</span></div></div>')
            if wk is not None and sub[0] not in ("proj", "projlive") and s_.dnp(wk, i):          # didn't take a snap: a chip, worth 0
                small_ = (s_.nl_r(team) + sub[1]) if right else (s_.nl(team) + sub[1])
                return (f'<div class="pl {"right" if right else ""}"><div class="who"><b>{s_.pa(i, s.nm(i))}</b><small>{small_}</small></div>'
                        f'<div class="pts"><span class="byec dnp" title="Did not play (0 snaps), 0 points">DNP</span></div></div>')
            small = (s_.nl_r(team) + (f'{dot}<span class="kt">{kt}</span>' if kt else "") + sub[1]) if right else (s_.nl(team) + (f'{dot}<span class="kt">{kt}</span>' if kt else "") + sub[1])   # same order both sides: team, then kickoff
            return (f'<div class="pl {"right" if right else ""} {"up" if up else ""}{" tap" if card else ""}"{card}><div class="who"><b>{s_.pa(i, s.nm(i))}</b>{badge}<small>{small}</small></div>'
                    + (f'<div class="pts pj">{fmt.format(p) if fmt else fp(p)}<small>proj</small></div></div>' if sub[0] == "projlive" else
                       f'<div class="pts">{fp(p) if fmt is None else fmt.format(p)}</div></div>'))
        ok = lambda x, y: hl          # green only on finished games, never on projections or live games
        rows = "".join(f'<div class="ln">{cell(x, False, x[2] > y[2] and ok(x, y))}<div class="slot">{E(x[0])}</div>{cell(y, True, y[2] > x[2] and ok(x, y))}</div>' for x, y in zip(A, B))
        ta, tb = total
        rows += f'<div class="ln tot"><div class="pl"><div class="who"><b>Total</b></div><div class="pts">{ta}</div></div><div class="slot">PTS</div><div class="pl right"><div class="who"><b>Total</b></div><div class="pts">{tb}</div></div></div>'
        return f'<div class="lu">{rows}</div>'

    def bench_gain(s_, w, r):
        """{player: points the lineup gains (+) or loses (-) swapping him in for the best starter to take out}, for team r's bench in finished week w.
        IR and bye weeks are left out: those weren't choices."""
        if not hasattr(s_, "_bg"): s_._bg = {}
        if (w, r) in s_._bg: return s_._bg[(w, r)]
        s = s_.s; out = {}
        if w in s.W and r in s.W[w]:
            d = s.W[w][r]; act_ = sum(sp for si, sp in d["S"] if si != "0"); irs_ = s_.ir_set(r, w, [i for i, _ in d["B"]])
            st_ = [(si, s.pos(si), sp) for si, sp in d["S"] if si != "0"]
            for i, p in d["B"]:
                if i == "0" or i in irs_ or s_.team_at(w, i) in s.byes.get(w, []): continue
                pools = [st_[:k] + st_[k + 1:] + [(i, s.pos(i), p)] for k in range(len(st_))] + ([st_ + [(i, s.pos(i), p)]] if len(st_) < len(s.slots) else [])
                opts = [v for v, ch in (s.best(x) for x in pools) if i in set(ch)]
                if opts: out[i] = round(max(opts) - act_, 2)
        s_._bg[(w, r)] = out; return out

    def dropped_mid(s_, w, r):
        """Players team r dropped during week w after the games began: Sleeper keeps them on that week's team."""
        s = s_.s; ks = [k for k, *_ in s.sched.get(w, [])]
        if not ks or w not in s.W or r not in s.W[w]: return {}
        import datetime as _dt
        a0 = min(ks); a1 = (_dt.datetime.strptime(max(ks), "%Y-%m-%dT%H:%MZ") + _dt.timedelta(hours=5)).strftime("%Y-%m-%dT%H:%MZ")
        on_ = {i for i, _ in s.W[w][r]["S"] + s.W[w][r]["B"]}; out = {}
        for x in s.tx:
            if x["status"] == "complete" and x["type"] != "trade" and x.get("when") and a0 <= x["when"] <= a1:     # a trade waits for the week's games to end, so it never lands mid-week
                for i, rr in x["drops"]:
                    if rr == r and i in on_: out[i] = "Dropped"
        return out

    def bench_tbl(s_, r, items, title, ir=(), wk=None, pts=None, bw=None, lpts=None):
        """items: [(id, value_text, tag_html)] already sorted. Players in the IR slot go last, below a red line, in red."""
        s = s_.s
        reg = [x for x in items if x[0] not in ir]; irs = [x for x in items if x[0] in ir]
        ca = lambda i: (f' class="tap" data-card="{E(s_.statcard(wk, i, pts[i]))}" tabindex="0" role="button"' if (wk is not None and pts) else
                        f' class="tap" data-card="{E(s_.statcard(bw, i, lpts[i]))}" tabindex="0" role="button"' if (lpts and i in lpts) else "")   # live week: his game has started
        ex = any(len(x) > 3 for x in items); xc = lambda x: f'<td class="r">{x[3]}</td>' if ex else ""
        bwk = wk if wk is not None else bw
        if bwk is not None:          # bye week: a chip instead of 0.0
            items = [(x[0], '<span class="byec">BYE</span>' if s_.team_at(bwk, x[0]) in s.byes.get(bwk, []) and x[1] in ("0", "0.0") else
                      '<span class="byec dnp" title="Did not play (0 snaps), 0 points">DNP</span>' if wk is not None and s_.dnp(wk, x[0]) else x[1]) + tuple(x[2:]) for x in items]
            reg = [x for x in items if x[0] not in ir]; irs = [x for x in items if x[0] in ir]
        dm = s_.dropped_mid(wk, r) if wk is not None else {}; V_ = "C"
        reg = [x for x in reg if x[0] not in dm] + [x for x in reg if x[0] in dm]
        dcls = lambda i, k: (f' dropx{" dropfirst" if k == 0 and V_ != "A" else ""}') if i in dm else ""
        dtag = lambda i: f'<span class="drb">{dm[i]}</span>' if i in dm else ""
        rows_ = "".join(f'<tr{ca(x[0]).replace(' class="tap"', '')} class="{"tap" if ca(x[0]) else ""}{dcls(x[0], sum(1 for y in reg[:k] if y[0] in dm))}"><td class="bp">{E(s_.posd(x[0]))}</td><td><b>{s_.pa(x[0], s.nm(x[0]))}</b>{dtag(x[0])}{inj_tag(s_.gday_inj(wk, x[0])) if wk is not None and x[0] not in dm else ""}</td><td class="r big">{x[1]}</td><td class="r">{x[2]}</td>{xc(x)}</tr>' for k, x in enumerate(reg))
        rows_ += "".join(f'<tr class="ir{" irfirst" if k == 0 else ""}"><td class="bp">{E(s_.posd(x[0]))}</td><td><b>{s_.pa(x[0], s.nm(x[0]))}</b><span class="irb">IR</span>{dtag(x[0])}</td><td class="r big">{x[1]}</td><td class="r"></td>{"<td></td>" if ex else ""}</tr>' for k, x in enumerate(irs))
        return f'<h3>{E(title)}</h3><table class="pt bench"><tbody>{rows_ or "<tr><td class=muted>Empty</td></tr>"}</tbody></table>'

    def ir_set(s_, r, w=None, pool=()):
        s = s_.s
        if w is not None and w in s.G:                        # finished week: only a recorded snapshot counts
            return set(getattr(s, "reserve_wk", {}).get(w, {}).get(r, []))
        res = set(getattr(s, "reserve", {}).get(r, []))
        if w is not None and w == s.nxt: res |= set(((getattr(s, "LIVE", None) or {}).get("reserve_live") or {}).get(w, {}).get(r, set()))   # locked in IR this week, even if dropped since
        if res or r in getattr(s, "reserve", {}): return res        # Sleeper says who's in the IR slot (an empty slot is empty): no guessing
        n_ir = int(s.L.get("ir_slots", 1)) if str(s.L.get("ir_slots", "1")).isdigit() else 1
        cand = [i for i in pool if s.PL.get(i, {}).get("inj") in ("IR", "PUP")]
        return set(cand[:n_ir])

    def statcard(s_, w, i, pts):
        """Box-score card for one player-week (HTML), from real NFL stats."""
        s = s_.s; st = getattr(s, "NS", {}).get(w, {}).get(i, {}); g = lambda k: int(st.get(k, 0))
        cp = lambda keys: sum(float(st.get(k, 0)) * s_.SC.get(k, 0.0) for k in keys)
        P = dict(Passing=cp(("pass_yd", "pass_td", "pass_int", "pass_2pt")), Rushing=cp(("rush_yd", "rush_td", "rush_2pt")),
                 Receiving=cp(("rec", "rec_yd", "rec_td", "rec_2pt"))); P["Fumbles lost"] = cp(("fum_lost",))
        rows_ = []
        if g("pass_att"): rows_.append(("Passing", f'{g("pass_cmp")}/{g("pass_att")}, {g("pass_yd")} yds, {g("pass_td")} TD' + (f', {g("pass_int")} INT' if g("pass_int") else "")))
        if g("rush_att") or g("rush_yd"): rows_.append(("Rushing", f'{g("rush_att")} car, {g("rush_yd")} yds' + (f', {g("rush_td")} TD' if g("rush_td") else "")))
        if g("rec_tgt") or g("rec"): rows_.append(("Receiving", f'{g("rec")}/{g("rec_tgt")} tgt, {g("rec_yd")} yds' + (f', {g("rec_td")} TD' if g("rec_td") else "")))
        SCg = lambda k: s_.SC.get(k, 0.0)
        if g("xpa"):
            P["Extra points"] = g("xpm") * SCg("xpm") + (g("xpa") - g("xpm")) * SCg("xpmiss")
        if g("fga"): rows_.append(("Field goals", f'{g("fgm")}/{g("fga")}' + (f', long {g("fgm_lng")}' if g("fgm_lng") else "")))
        if g("xpa"): rows_.append(("Extra points", f'{g("xpm")}/{g("xpa")}'))
        if s.pos(i) == "DEF":
            pa = g("pts_allow")
            tier = next(v for lim, v in ((0, "pts_allow_0"), (6, "pts_allow_1_6"), (13, "pts_allow_7_13"), (20, "pts_allow_14_20"), (27, "pts_allow_21_27"), (34, "pts_allow_28_34"), (999, "pts_allow_35p")) if pa <= lim)
            P["Points allowed"] = SCg(tier); P["Sacks"] = g("sack") * SCg("sack")
            P["Takeaways"] = g("int") * SCg("int") + g("fum_rec") * SCg("fum_rec"); P["Touchdowns"] = (g("def_td") + g("def_st_td")) * 6.0
            rows_.append(("Points allowed", str(pa))); rows_.append(("Sacks", str(g("sack"))))
            rows_.append(("Takeaways", f'{g("int")} INT, {g("fum_rec")} fumble rec'))
            if g("def_td") + g("def_st_td"): rows_.append(("Touchdowns", str(g("def_td") + g("def_st_td"))))
        two = g("pass_2pt") + g("rush_2pt") + g("rec_2pt")
        if two: rows_.append(("2-pt", f"{two} conversion{'s' if two > 1 else ''} (counted above)"))
        if g("fum_lost"): rows_.append(("Fumbles lost", str(g("fum_lost"))))
        if not rows_: rows_.append(("Stats", "Did not record a stat"))
        known = sum(v for v in P.values())
        def ptsof(k):
            if k in P: return P[k]
            if k == "Field goals": return pts - known       # FG distance bonus etc.: whatever the rows above don't explain
            return None
        rows_ = [(k, v, ptsof(k)) for k, v in rows_]
        other = round(pts - known - sum(x[2] for x in rows_ if x[0] == "Field goals" and x[2] is not None), 2)
        if abs(other) >= 0.05 and s.pos(i) != "K": rows_.append(("Other", "forced fumbles, safeties, blocks" if s.pos(i) == "DEF" else "returns, fumble recoveries", other))
        team = s_.team_at(w, i)
        return (f'<b>{E(s.nm(i))}</b><span class="muted">{E(s.pos(i))}, {E(team)}, Week {w}</span><span class="cp">{fp(pts)} pts</span>' +
                "".join(f'<span class="cr"><i>{k}</i>{E(v)}<b class="cpt">{"" if x is None else f"{x:+.2f}".rstrip("0").rstrip(".")}</b></span>' for k, v, x in rows_) + f'<a class="go" href="#/player/{i}" style="margin-top:8px">Player page</a>')

    def team_stats(s_, w, r):
        t = Counter()
        for i, _ in s_.s.W[w][r]["S"]:
            for k, v in getattr(s_.s, "NS", {}).get(w, {}).get(i, {}).items(): t[k] += v
        return t

    def now_str(s_, x):
        return "undrafted" if x["undrafted"] else f'{x["rrd"]}.{x["rslot"]:02d}'

    def game_order(s_, w, pairs):
        """Most important / best game first (not shown on the page).
        Upcoming: what's at stake (playoff, bye and title swings for both teams), then how close it is, then how good both teams are.
        Finished: how good and how close it was (combined score, then margin)."""
        s = s_.s
        def key(ab):
            a, b = ab
            if w in s.G:
                sa, sb = s.G[w]["scores"][a], s.G[w]["scores"][b]
                avg = float(np.mean(list(s.G[w]["scores"].values())))
                return -((sa + sb) / (2 * avg) + (1 - min(abs(sa - sb), 40) / 40))
            la, lb = s_.lev.get((w, a)), s_.lev.get((w, b))
            stake = sum(abs(x["po_w"] - x["po_l"]) + 0.5 * abs(x["by_w"] - x["by_l"]) + abs(x["ti_w"] - x["ti_l"]) for x in (la, lb) if x)
            A, B = s_.upcoming(w, a), s_.upcoming(w, b); p = s_.win_p(A, B)
            close = 1 - abs(2 * p - 1)
            qual = (s_.power[a][1]["pw"] + s_.power[b][1]["pw"]) / 40
            return -(stake + 0.25 * close + 0.1 * qual)
        return sorted(pairs, key=key)

    def stat_short(s_, w, i):
        st = getattr(s_.s, "NS", {}).get(w, {}).get(i, {}); g = lambda k: int(st.get(k, 0)); out_ = []
        if g("pass_att"): out_.append(f'{g("pass_cmp")}/{g("pass_att")} {g("pass_yd")}y {g("pass_td")}TD' + (f' {g("pass_int")}INT' if g("pass_int") else ""))
        if g("rush_att"): out_.append(f'{g("rush_att")}-{g("rush_yd")}' + (f' {g("rush_td")}TD' if g("rush_td") else ""))
        if g("rec_tgt") or g("rec"): out_.append(f'{g("rec")}/{g("rec_tgt")} {g("rec_yd")}y' + (f' {g("rec_td")}TD' if g("rec_td") else ""))
        if g("fga") or g("xpa"): out_.append(f'FG {g("fgm")}/{g("fga")} XP {g("xpm")}/{g("xpa")}')
        if s_.s.pos(i) == "DEF": out_.append(f'{g("pts_allow")} PA {g("sack")} sk {g("int") + g("fum_rec")} TO')
        return ", ".join(out_)

    def players_data(s_):
        """Everything a player page needs, compact (arrays, ints), for every player who was ever on a Super League roster."""
        s = s_.s; R = s.repl["val"]; wpp = s.wpp; yr = s_.yr
        ids = set(d["id"] for d in s.draft) | {i for v in s.rost.values() for i in v}
        for w in s.weeks:
            for r, d in s.W[w].items(): ids |= {i for i, _ in d["S"] + d["B"] if i != "0"}
        ids |= {i for t in s.tx if t["status"] == "complete" for i, _ in t["adds"]}       # added and dropped before ever playing a week still counts
        drows, _, _ = s_.draft_vals(); dmap = {x["i"]: x for x in drows}
        tot, gsn, ptsn, teams, best = s_.season_pm(s)
        mvp_rank = {i: k for k, i in enumerate(sorted(tot, key=lambda i: -tot[i]), 1)}
        wk_mvps = Counter(a["mvp"][0] for a in s.awards)
        owner = {i: r for r, v in s.rost.items() for i in v}
        opp_of = {(w, r): (b if a == r else a) for w, a, b, _ in s_.games for r in (a, b)}
        tx = defaultdict(list)
        # Sleeper lists each week newest first: flip so moves read in the order they happened
        for t in [t for _, t in sorted(enumerate(s.tx), key=lambda kv: (kv[1]["w"], -kv[0]))]:
            if t["status"] != "complete": continue
            kind = {"waiver": "Waiver", "free_agent": "Free agent", "commissioner": "Commissioner", "trade": "Trade"}.get(t["type"], t["type"])
            if t["type"] == "commissioner" and id(t) in s_.veto_tx(): kind = "Veto undone"
            when = ""
            if t.get("when"):
                from zoneinfo import ZoneInfo as _Z
                dt_ = datetime.datetime.strptime(t["when"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=datetime.timezone.utc).astimezone(_Z("America/New_York"))
                when = dt_.strftime("%a %b %-d, %-I:%M %p")
            NP_ = lambda ids: [[j, s.nm(j)] for j in ids]
            if t["type"] == "trade" and kind == "Trade":
                frm = {j: r for j, r in t["drops"]}; to_ = {j: r for j, r in t["adds"]}
                pf_ = lambda j, rr, w0=t["w"]: sum(p for w_ in s.weeks if w_ >= w0 for jj, p in s.W[w_].get(rr, {}).get("S", []) if jj == j)
                NP0 = NP_
                NP_ = lambda ids: NP0(sorted(ids, key=lambda j: -pf_(j, to_.get(j, 0))))     # each side listed by what they've scored for their new team since
                for i, r in t["adds"]:              # one line per trade: where he came from, who came with him, what it cost
                    tx[i].append([t["w"], r, "+", kind, when, frm.get(i, 0),
                                  NP_([j for j, rr in t["adds"] if rr == r and j != i]), NP_([j for j, rr in t["drops"] if rr == r])])
                continue
            for i, r in t["drops"]: tx[i].append([t["w"], r, "-", kind, when, 0, NP_([j for j, rr in t["adds"] if rr == r]), []])     # leaving the old team comes before joining the new one
            for i, r in t["adds"]: tx[i].append([t["w"], r, "+", kind, when, 0, NP_([j for j, rr in t["drops"] if rr == r]), []])
        out = {}
        for i in ids:
            if s.pos(i) not in R: continue
            wk = []
            for w in s.weeks:
                r_on = 0; started = 0
                for r, d in s.W[w].items():
                    if any(j == i for j, _ in d["S"]): r_on, started = r, 1
                    elif any(j == i for j, _ in d["B"]): r_on = r
                pts = None
                if r_on: pts = next(p for j, p in s.W[w][r_on]["S"] + s.W[w][r_on]["B"] if j == i)
                elif i in s.NP.get(w, {}): pts = s.NP[w][i]
                op_ = opp_of.get((w, r_on), 0) if r_on else 0
                won_ = (1 if s.G[w]["scores"][r_on] > s.G[w]["scores"][op_] else 0) if (r_on and op_) else None
                wk.append([w, r_on, started, None if pts is None else round(pts, 2), op_, s_.stat_short(w, i), won_, 1 if s_.team_at(w, i) in s.byes.get(w, []) else 0, 0,
                           round((pts - s.repl["val"].at(w, s.pos(i))) * s.wpp, 3) if started and pts is not None and s.pos(i) in s.repl["val"] else None,
                           round(pts - s.pos_median(w)[s.pos(i)], 2) if started and pts is not None and s.pos(i) in s.pos_median(w) else None,
                           s_.wk_rank(w, i) if pts is not None else None, s_.st_rank(w, i) if started and pts is not None else None,
                           1 if i in s.NP.get(w, {}) else 0, INJ_SHORT.get(s_.gday_inj(w, i) or "", s_.gday_inj(w, i) or ""), s_.team_at(w, i) if i.isdigit() else i,
                           s_.bench_gain(w, r_on).get(i) if (r_on and not started) else None,
                           round(s_.wi(pts - s.pos_median(w)[s.pos(i)]), 3) if started and pts is not None and s.pos(i) in s.pos_median(w) else None])
            LW = s.nxt
            PM_ = s_.prov_median(s) if hasattr(s_, "prov_median") else {}
            if s_.wk_live(LW):          # the week in progress: a start counts once his NFL game is final (PAA against a stand-in median until the week ends); W-L waits
                r_on = 0; started = 0; pts = None; fin = 0
                for r in s.R:
                    lv = s_.live_of(LW, r)
                    if lv and i in lv["starters"]:
                        r_on, started = r, 1
                        if i in lv["played"]: pts = round(lv["played"][i], 2); fin = 0 if i in lv.get("inprog", ()) else 1
                if not r_on: r_on = owner.get(i, 0)
                t_ = s_.team_at(LW, i)
                if r_on and not started and (t_ in (s.LIVE or {}).get("done", ())): fin = 1        # benched and his game is over: that week on the bench is locked too
                wk.append([LW, r_on, started, pts, opp_of.get((LW, r_on), 0) if r_on else 0, s_.stat_short(LW, i) if fin else "", None, 1 if t_ in s.byes.get(LW, []) else 0, 2 if fin else 1,
                           round((pts - s.repl["val"].at(LW, s.pos(i))) * s.wpp, 3) if started and fin and pts is not None and s.pos(i) in s.repl["val"] else None,
                           round(pts - PM_[s.pos(i)], 2) if started and fin and pts is not None and s.pos(i) in PM_ else None, s_.wk_rank(LW, i) if fin and pts is not None else None, None, 1, "", t_, None,
                           round(s_.wi(pts - PM_[s.pos(i)]), 3) if started and fin and pts is not None and s.pos(i) in PM_ else None])
            st_ = [x for x in wk if x[2] and x[3] is not None]                      # starts and points count the moment his game is on
            var = sum((x[3] or 0) - R.at(x[0], s.pos(i)) for x in st_ if x[8] != 1)       # value above replacement waits for the final
            dx = dmap.get(i)
            P_ = s.PL.get(i, {})
            ab = (P_.get("team") or "") if i.isdigit() else i
            out[i] = dict(ns=[[n["title"], n["slug"], n["week"], s_.KIND.get(n.get("kind"), "Story")] for n in s_.stories_for(player=i)], n=s.nm(i), p=s.pos(i), pd=s_.posd(i, ", "), t=(P_.get("team") or "FA") if i.isdigit() else i, tf=(f"{NFL_CITY[ab]} {NFL_NICK[ab]}" if ab in NFL_NICK else ("Free agent" if i.isdigit() else "")),
                          wr=sum(1 for x in wk if x[1]), j=P_.get("inj") or "", rk=1 if P_.get("exp") == 0 else 0, ag=s_.age_of(i), ex=s_.bio().get(i, ("", None))[1], no=(s_.bio().get(i, ("", None, ""))[2:] or [""])[0],
                          o=owner.get(i, 0), ir=1 if i in set().union(*[set(v) for v in getattr(s, "reserve", {}).values()]) else 0,
                          sea={str(yr): dict(
                              d=[dx["rd"], dx["slot"], dx["r"], round(dx["gap"], 2), s_.now_str(dx)] if dx else None,
                              w=wk, irw=[w for w in sorted(getattr(s, "reserve_wk", {})) if any(i in v for v in s.reserve_wk[w].values())], nt=[t for t in dict.fromkeys(s_.team_at(x[0], i) for x in wk) if t in NFL_NICK],
                              x=([[0, dx["r"], "+", "Draft", f'{dx["rd"]}.{dx["slot"]:02d}']] if dx else []) + tx.get(i, []), m=[[a["w"], a["mvp"][1]] for a in s.awards if a["mvp"][0] == i],
                              s=[len(st_), round(sum(x[3] or 0 for x in st_), 2), round(var), round(var * wpp, 2), round(tot.get(i, 0), 1), mvp_rank.get(i, 0), wk_mvps.get(i, 0)] + s_.split_pts(wk, i)
                                + [round(sum(x[17] or 0 for x in wk if x[2] and x[6] is not None), 3),
                                   round(sum((x[6] or 0) - 0.5 - (x[17] or 0) for x in wk if x[2] and x[6] is not None), 3)])})
        # jersey badge snapshot per season (NFL team + number), so an old season keeps the look it had even after a trade or rebrand
        snp = os.path.join(getattr(s, "ddir", "data"), "badge_snap.txt"); keep = {}
        if os.path.exists(snp):
            for l in open(snp):
                f_ = l.rstrip("\n").split("|")
                if len(f_) >= 4 and f_[0].isdigit(): keep[(f_[0], f_[1])] = (f_[2], f_[3])
        for i, d_ in out.items():
            keep[(str(yr), i)] = (d_["t"], str(d_.get("no") or ""))           # the current season always follows today's team and number
            for y_, S_ in d_["sea"].items():
                if (y_, i) in keep: S_["bd"] = list(keep[(y_, i)])
        try:
            with open(snp, "w") as fh:
                fh.write("# season|player|nfl team|jersey number  (current season rewritten each build; past seasons frozen)\n")
                for (y_, i), (tm, no) in sorted(keep.items()): fh.write(f"{y_}|{i}|{tm}|{no}\n")
        except OSError: pass
        return out

    def split_pts(s_, wk, i):
        """[total, bench, free agent, left on bench, times he should have started] from a player's weekly entries.
        Total = every NFL point this season; bench leaves out IR weeks; free agent = weeks on no Super League roster."""
        irw = {w for w in getattr(s_.s, "reserve_wk", {}) if any(i in v for v in s_.s.reserve_wk[w].values())}
        done = [x for x in wk if x[3] is not None]
        tot_ = sum(x[3] for x in done)
        ben = sum(x[3] for x in done if x[1] and not x[2] and x[0] not in irw)
        fa = sum(x[3] for x in done if not x[1])
        g = [x[16] for x in wk if len(x) > 16 and x[16] is not None]
        return [round(tot_, 2), round(ben, 2), round(fa, 2), round(sum(v for v in g if v > 0), 2), sum(1 for v in g if v > 0.005)]

    def pos_key(s_, i):
        order = ["QB", "RB", "WR", "TE", "K", "DEF"]
        p = s_.s.pos(i); return order.index(p) if p in order else 9

    def game_stats_html(s_, w, a, b):
        if not getattr(s_.s, "NS", {}).get(w): return ""
        A, B = s_.team_stats(w, a), s_.team_stats(w, b)
        for X in (A, B):
            X["tot_yd"] = X["pass_yd"] + X["rush_yd"] + X["rec_yd"]
            X["tot_td"] = X["pass_td"] + X["rush_td"] + X["rec_td"] + X["def_td"] + X["def_st_td"] + X["st_td"]
        def sub(X, ks): return " ".join(f'{lab_} {X[k_]:g}' for lab_, k_ in ks if X[k_])
        YD = (("Pass", "pass_yd"), ("Rush", "rush_yd"), ("Rec", "rec_yd")); TD = (("Pass", "pass_td"), ("Rush", "rush_td"), ("Rec", "rec_td"))
        rows_ = [("Total yards", "tot_yd", YD), ("Total TDs", "tot_td", TD), ("Turnovers", None, ())]
        out_ = []
        for lab, k, parts in rows_:
            va = A["pass_int"] + A["fum_lost"] if k is None else A[k]; vb = B["pass_int"] + B["fum_lost"] if k is None else B[k]
            if va == 0 and vb == 0: continue
            low_better = k is None
            sh = va / (va + vb) if va + vb else 0.5
            wa = (va < vb) if low_better else (va > vb); wb = (vb < va) if low_better else (vb > va)
            sa_, sb_ = (sub(A, parts), sub(B, parts)) if parts else ("", "")
            out_.append(f'<div class="gsr"><span class="gv {"lead" if wa else ""}">{va:g}</span><div class="gsm"><span class="gl">{lab}</span><div class="gsb"><i style="width:{sh * 100:.1f}%"></i></div></div>'
                        f'<span class="gv r {"lead" if wb else ""}">{vb:g}</span></div>' + (f'<div class="gsx"><span>{sa_}</span><span>{sb_}</span></div>' if sa_ or sb_ else ""))
        return f'<section><h2>Game stats</h2><div class="panel gstats"><div class="gsh"><b>{E(s_.TN(a))}</b><b>{E(s_.TN(b))}</b></div>{"".join(out_)}</div></section>'

    def potg_html(s_, w, a, b, pre):
        """The turning point: the winner's biggest swing, told like a highlight. The play, the NFL score and clock, the win
        chance before and after, and everyone in the matchup it scored for."""
        x = s_.play_of_game(w, a, b)
        if not x or len(x) < 14: return ""
        w_, r, o, u, when, clk, txt, who, wpa, cpa, pb, pa_, sc, xs = x[:14]
        txt = s_.chart_text(x[14] if len(x) > 14 else txt, [i for i, _ in who])
        aw, asc, hm, hsc = sc
        nfl = lambda t: f'<i class="nfl N{t}" role="img" aria-label="{t}"></i>' if t in NFL_NICK else ""
        chips = "".join(f'<a class="tpp" href="{pre}player/{i}.html">{s_.logo(r, pre, "lgs", w)}{nfl(s_.team_at(w, i))}<span>{E(s_.s.nm(i))}</span><b>{v:+.2f}</b></a>'
                        for i, v in who if v > 0)
        game = f'{nfl(aw)}<b>{E(str(aw))} {asc}</b><span class="tpat">at</span>{nfl(hm)}<b>{E(str(hm))} {hsc}</b>' if aw else ""
        return (f'<section class="tp"><h2>The game-defining play <small>the winner\'s biggest swing</small></h2>'
                f'<div class="tpc"><div class="tpl"><div class="tpg">{game}<span class="tpk">{E(clk)}</span><span class="tpw">{E(str(when))}</span></div>'
                f'<p class="tpx">{E(txt)}</p><div class="tpps">{chips}</div></div>'
                f'<div class="tpr"><div class="tpt">{s_.logo(r, pre, "lgs", w)}<b>{E(s_.TN(r, w))}</b></div>'
                f'<div class="tpn"><span>{pb * 100:.0f}%</span><i aria-hidden="true">&#8594;</i><strong>{pa_ * 100:.0f}%</strong></div>'
                f'<div class="tpbar" aria-hidden="true"><i class="b0" style="width:{pb * 100:.1f}%"></i><i class="b1" style="left:{pb * 100:.1f}%;width:{max(0.0, pa_ - pb) * 100:.1f}%"></i><em style="left:50%"></em></div>'
                f'<div class="tps">{wpa * 100:+.1f}% <small>win chance on one play</small></div>'
                f'<div class="tpf">Fantasy score after it: {fp(xs[0])} to {fp(xs[1])}</div></div></div></section>')

    def game_done(s_, w, a, b):
        s_._at = s_.wk_start(w)
        try: return s_._game_done(w, a, b)
        finally: s_._at = None
    def _game_done(s_, w, a, b):
        s = s_.s; pre = "../"; G = s.G[w]; sa, sb = G["scores"][a], G["scores"][b]; yr = s_.yr
        med = s.pos_median(w); win = a if sa > sb else b
        slots = s.L["lineup"]
        def lineup(r):
            out_ = []
            for k, (i, p) in enumerate(s.W[w][r]["S"]):
                out_.append((slots[k], None if i == "0" else i, p if i != "0" else 0, ("", inj_tag(s_.gday_inj(w, i)) if i != "0" else ""), ""))
            return s_.order_slots(out_)
        LA, LB = lineup(a), lineup(b)
        allst = [x for x in (LA if sa > sb else LB if sb > sa else LA + LB) if x[1]]   # game MVP comes from the winning team
        best_ = max(x[2] - med[s.pos(x[1])] for x in allst)
        star = {x[1] for x in allst if abs((x[2] - med[s.pos(x[1])]) - best_) < 1e-9}   # a tie makes co-MVPs
        lu = s_.slot_rows(LA, LB, (fp(sa), fp(sb)), mvp=star, wk=w)
        opt = {}; chs = {}
        for r in (a, b):
            d = s.W[w][r]; opt[r], ch = s.best([(i, s.pos(i), p) for i, p in d["S"] + d["B"] if i != "0"]); chs[r] = set(ch)
        def bench(r):
            d = s.W[w][r]
            act_ = sum(sp for si, sp in d["S"] if si != "0")
            def swap(i, p):          # points gained (+) or lost (-) swapping him in for the best starter to bench, lineup rearranged (e.g. WR to FLEX, RB from FLEX to RB)
                st_ = [(si, s.pos(si), sp) for si, sp in d["S"] if si != "0"]
                pools = [st_[:k] + st_[k + 1:] + [(i, s.pos(i), p)] for k in range(len(st_))] + ([st_ + [(i, s.pos(i), p)]] if len(st_) < len(s.slots) else [])
                opts = [v for v, ch in (s.best(x) for x in pools) if i in set(ch)]          # he has to actually be in the lineup
                return max(opts) - act_ if opts else None
            irs_ = s_.ir_set(r, w, [i for i, _ in d["B"]])
            sw = {i: swap(i, p) for i, p in d["B"] if i != "0"}
            items = [(i, fp(p), "",
                      "" if i in irs_ or sw[i] is None else f'<span class="swp{" sh" if i in chs[r] else ""}" title="{"Should have started. " if i in chs[r] else ""}Points gained or lost if he had replaced the lowest-scoring starter he could have">{sw[i]:+.1f}</span>')
                     for i, p in sorted([x for x in d["B"] if x[0] != "0"], key=lambda x: -(sw[x[0]] if sw[x[0]] is not None else -999))]
            return s_.bench_tbl(r, items, f"{s_.M[r]}{chr(39) if s_.M[r].endswith('s') else chr(39) + 's'} bench", s_.ir_set(r, w, [i for i, _ in d["B"]]), wk=w, pts={i: p for i, p in d["B"]})
        PA_, PB_ = s_.pregame(w, a), s_.pregame(w, b)
        upset = False; pre_txt = ""
        if PA_ and PB_:
            pa = s_.win_p(PA_, PB_); fav = a if pa >= 0.5 else b; upset = fav != win
            pre_txt = (f'<div class="vs"><div class="a vsh">{s_.logo(a, pre, "lgs")}{E(s_.M[a])}</div><div class="k"></div><div class="b vsh">{E(s_.M[b])}{s_.logo(b, pre, "lgs")}</div>'
                       f'<div class="a">{PA_[0]:.1f}</div><div class="k">Projected</div><div class="b">{PB_[0]:.1f}</div>'
                       f'<div class="a">{pct(pa)}</div><div class="k">Win chance</div><div class="b">{pct(1 - pa)}</div>'
                       f'<div class="a {"pos" if sa - PA_[0] > 0 else "neg"}">{sa - PA_[0]:+.1f}</div><div class="k">vs projection</div><div class="b {"pos" if sb - PB_[0] > 0 else "neg"}">{sb - PB_[0]:+.1f}</div>'
                       + s_.gut_row(w, a, b)
                       + '</div>')
        n9 = len(s.R) - 1
        outsc = lambda r: sum(G["scores"][r] > G["scores"][x] for x in s.R if x != r)
        extra = {r: [("outscored", f"{outsc(r)} of {n9}"), (f"of best possible ({fp(opt[r])})", pct(G["scores"][r] / opt[r] if opt[r] else 1))] for r in (a, b)}
        series = s_.series_html(w, a, b, pre)      # every other meeting this season, played or still to come
        mid = f'<span class="tag">Final</span><div style="margin-top:8px">by {fp(abs(sa - sb))}</div>'
        body = f"""<section class="field"><div class="wrap"><a class="back" href="../schedule.html#wk{w}">Week {w} schedule</a>
{s_.board(w, a, b, pre, fp(sa), fp(sb), mid, True, extra)}</div></section>
{s_.game_nav(w, a, b, pre)}
<main class="wrap">
{s_.story_block(w, a, b, pre, "main")}
<section><h2>Box score</h2>{lu}</section>
<div class="grid2"><section>{bench(a)}</section><section>{bench(b)}</section></div>
{s_.wp_chart(w, a, b, pre)}
{(lambda x_, rk_: f'<div class="xcap"><div class="xhd"><span class="xl">Excitement</span><b>{x_:.1f}</b><span class="exm" aria-hidden="true"><i style="width:{s_.exc_bar(x_)}%"></i></span></div>'
                  + f'<div class="xft"><span class="xrk">{rk_[0]} most exciting of {rk_[1]} games this season</span><a class="xgo" href="#/excitement">All games ranked</a></div>'
                  + '<details class="xdt"><summary>Score breakdown</summary><span class="xbr">' + "".join(f'<i>{E(k_)} <b>{v_:.1f}</b> <small>({int(dict(s_.EXW)[k_] * 100)}%)</small></i>' for k_, v_ in s_.exc_terms(s_._excp[(w, min(a, b), max(a, b))])) + '</span></details></div>')(s_.excitement(w, a, b), s_.exc_rank(w, a, b)) if s_.excitement(w, a, b) is not None else ""}
{s_.potg_html(w, a, b, pre)}
{s_.game_stats_html(w, a, b)}
{f'<section><h2>The pregame line <small>what the model expected before kickoff</small></h2><div class="panel">{pre_txt}</div></section>' if pre_txt else ""}
{s_.odds_moves(w, a, b)}
<section><h2>Season series</h2><div class="mini">{series}</div></section>
{s_.story_block(w, a, b, pre, "more")}
</main>{s_.footer(pre)}"""
        return page(f"Week {w}: {s_.TN(a)} vs {s_.TN(b)}, Super League {yr}", body, pre, "schedule")

    def odds_moves(s_, w, a, b):
        """Before kickoff, simply: the first look at this game and where it stood at kickoff (or now, if it hasn't started)."""
        pts = s_.wp_series(w, a, b)
        if not pts or len(pts) < 2: return ""
        k0 = next((k for k, x in enumerate(pts) if x[0] == "·" and len(x) > 5), None)     # the first play of the week
        pre_ = pts[:k0] if k0 else pts
        if len(pre_) < 2: return ""
        p0, p1 = pre_[0][1], pre_[-1][1]; fav = a if p1 >= 0.5 else b; f0, f1 = (p0, p1) if fav == a else (1 - p0, 1 - p1)
        started = k0 is not None; mv = (f1 - f0) * 100
        return (f'<section class="omv"><h2>Before kickoff</h2><div class="panel omvp">{s_.logo(fav, "../", "lgs", w)}<span class="omvt"><b>{E(s_.TN(fav, w))}</b>'
                f'<small>first look to {"kickoff" if started else "now"}</small></span><span class="omvn"><span>{f0 * 100:.0f}%</span><i aria-hidden="true">&#8594;</i><strong>{f1 * 100:.0f}%</strong></span>'
                f'<span class="omvd {"pos" if mv > 0.5 else "neg" if mv < -0.5 else "muted"}">{"no change" if abs(mv) < 0.5 else f"{mv:+.0f}"}</span></div></section>')

    def game_next(s_, w, a, b):
        s_._at = s_.wk_start(w)
        try: return s_._game_next(w, a, b)
        finally: s_._at = None
    def series_html(s_, w, a, b, pre):
        """Season series on a game page: every other meeting of these two this season, in week order. Played ones show the score;
        ones still to come (or under way) show the week. None: a gray italic line."""
        s = s_.s; cards = []
        wks = sorted({w2 for w2 in s.weeks for g in s.G[w2]["pairs"] if set(g) == {a, b}} | {w2 for w2, ps in s.fut.items() for g in ps if set(g) == {a, b}})
        for w2 in wks:
            if w2 == w: continue
            if w2 in s.G and s.G[w2].get("scores"):
                sc = s.G[w2]["scores"]
                cards.append(f'<a class="gm" href="{s_.gurl(w2, a, b, pre)}"><div class="row {"w" if sc[a] > sc[b] else "l"}">{s_.logo(a, pre, "lgs", w2)}<span class="t">{E(s_.TN(a, w2))}</span><span class="s">{sc[a]:.1f}</span></div>'
                             f'<div class="row {"w" if sc[b] > sc[a] else "l"}">{s_.logo(b, pre, "lgs", w2)}<span class="t">{E(s_.TN(b, w2))}</span><span class="s">{sc[b]:.1f}</span></div><div class="foot">Week {w2}</div></a>')
            else:
                tag = "Live" if (w2 == s.nxt and s_.wk_live(w2)) else "Upcoming"
                cards.append(f'<a class="gm" href="{s_.gurl(w2, a, b, pre)}"><div class="row">{s_.logo(a, pre, "lgs")}<span class="t">{E(s_.TN(a))}</span></div>'
                             f'<div class="row">{s_.logo(b, pre, "lgs")}<span class="t">{E(s_.TN(b))}</span></div><div class="foot">Week {w2}, {tag.lower()}</div></a>')
        return "".join(cards) or '<p class="muted" style="font-style:italic">No other matchups this season.</p>'

    def _game_next(s_, w, a, b):
        s = s_.s; pre = "../"; nm = s_.s.nm; yr = s_.yr; out = s_.SIM[0]
        A, B = s_.upcoming(w, a), s_.upcoming(w, b); pa = s_.win_p(A, B)
        slots = s.L["lineup"]
        def lineup(r):
            t = s_.TEAM[(w, r)]; lv = t.get("live")
            L_ = (list(lv["starters"]) if lv else list(t["lineup"])) + [None] * len(slots); L_ = L_[:len(slots)]; out_ = []
            for k, i in enumerate(L_):
                if i is None or i == "0": out_.append((slots[k], None, 0, ("", ""), "")); continue
                if lv and i in lv["played"]:
                    lvp = i in lv.get("inprog", ())
                    out_.append((slots[k], i, lv["played"][i], ("final", stg("pk", "Live") if lvp else stg("fin", "Final")), "")); continue
                p, why = s_.proj(i, w); inj = s.PL.get(i, {}).get("inj")
                tag = stg("pk", "Pickup") if i in t["adds"] else inj_tag(inj)
                out_.append((slots[k], i, p, ("projlive" if lv else "proj", tag), ""))
            return out_          # before/during the game: plain slots; RB1/RB2 ranking is a postgame look
        live = s_.wk_live(w)
        tot = (lambda r, mu: f'{fp(s_.now_pts(w, r))}<small>Proj {mu:.1f}</small>') if live else (lambda r, mu: f"{mu:.1f}")
        lu = s_.slot_rows(lineup(a), lineup(b), (tot(a, A[0]), tot(b, B[0])), fmt="{:.1f}", hl=False, kw=w)
        LV_ = getattr(s, "LIVE", None) or {}
        def bstate(i):                          # live week: a bench player whose game has started is locked on the bench, with real points
            if not (live and LV_.get("week") == w): return None
            tm_ = s_.team_at(w, i)
            if tm_ in LV_.get("done", ()): return "fin"
            if tm_ in (LV_.get("prog") or {}): return "live"
            return None
        def bench(r):
            t = s_.TEAM[(w, r)]; ch = set(t["live"]["starters"]) if t.get("live") else set(t["lineup"])
            pool = [i for i in t["all"] if i not in ch]; np_ = LV_.get("np") or {}
            lp = {i: np_.get(i, 0.0) for i in pool if bstate(i)}
            def item(i):
                st_ = bstate(i); pj, why = s_.proj(i, w)
                if st_: return (i, f'{fp(lp[i])}', stg("pk", "Live") if st_ == "live" else stg("fin", "Final"))
                return (i, f'<span class="bpj">{pj:.1f}<small>proj</small></span>', (inj_tag(s.PL.get(i, {}).get("inj")) if s.PL.get(i, {}).get("inj") else ("" if why == "bye" else f'<span class="muted">{E(why)}</span>')))
            items = [item(i) for i in sorted(pool, key=lambda i: (s_.pos_key(i), -(lp[i] if i in lp else s_.proj(i, w)[0])))]
            return s_.bench_tbl(r, items, f"{s_.M[r]}{chr(39) if s_.M[r].endswith('s') else chr(39) + 's'} bench", s_.ir_set(r, None, pool), bw=w, lpts=lp)
        la, lb = s_.lev[(w, a)], s_.lev[(w, b)]
        def stakes(r, x):
            row = lambda k, wv, lv: f'<tr><td>{k}</td><td class="r">{pct(wv)}</td><td class="r">{pct(lv)}</td><td class="r {"pos" if wv - lv > 0.005 else "muted"}">{(wv - lv) * 100:+.0f}</td></tr>'
            return (f'<h3>{E(s_.TN(r))}</h3><table class="pt"><thead><tr><th></th><th class="r">If win</th><th class="r">If lose</th><th class="r">Swing</th></tr></thead><tbody>'
                    f'{row("Playoffs", x["po_w"], x["po_l"])}{row("Bye", x["by_w"], x["by_l"])}{row("Title", x["ti_w"], x["ti_l"])}</tbody></table>')
        pw = {r: s_.power[r][1] for r in (a, b)}
        def tape_row(k, va, vb, fmt, hib=True):
            ba = (va > vb) if hib else (va < vb); bb = (vb > va) if hib else (vb < va)
            return f'<div class="a {"better" if ba else ""}">{fmt(va)}</div><div class="k">{k}</div><div class="b {"better" if bb else ""}">{fmt(vb)}</div>'
        rk = lambda r: s_.stand.index(r) + 1
        def h2h_row(k, ws):                                   # their record against each other, not counting this game
            wa = sum(1 for w2 in ws if s.G[w2]["scores"][a] > s.G[w2]["scores"][b]); wb = sum(1 for w2 in ws if s.G[w2]["scores"][b] > s.G[w2]["scores"][a])
            return f'<div class="a {"better" if wa > wb else ""}">{wa}-{wb}</div><div class="k">{k}</div><div class="b {"better" if wb > wa else ""}">{wb}-{wa}</div>'
        tape = ('<div class="vs">' + f'<div class="a {"better" if s_.W0[a] > s_.W0[b] else ""}">{s_.rec_str(a)}</div><div class="k">Record</div><div class="b {"better" if s_.W0[b] > s_.W0[a] else ""}">{s_.rec_str(b)}</div>' + tape_row("Standings", rk(a), rk(b), lambda v: f"#{v}", False)
                + tape_row("Points per week", pw[a]["ppg"], pw[b]["ppg"], lambda v: f"{v:.1f}") + tape_row("Last 3 weeks", pw[a]["l3"], pw[b]["l3"], lambda v: f"{v:.1f}")
                + tape_row("Power", s_.power[a][0], s_.power[b][0], lambda v: f"#{v}", False) + tape_row("xWins", s_.xw[a], s_.xw[b], lambda v: f"{v:.1f}")
                + tape_row("Playoff odds", out[a]["po"], out[b]["po"], pct) + tape_row("Title odds", out[a]["ti"], out[b]["ti"], pct)
                + h2h_row("Head-to-head<small>this season</small>", [w2 for w2 in s.weeks if w2 != w and any(set(g) == {a, b} for g in s.G[w2]["pairs"]) and s.G[w2]["scores"]])
                + h2h_row("Head-to-head<small>all-time</small>", [w2 for w2 in s.weeks if w2 != w and any(set(g) == {a, b} for g in s.G[w2]["pairs"]) and s.G[w2]["scores"]]) + "</div>")
        series = s_.series_html(w, a, b, pre)      # every other meeting this season, played or still to come
        is_live = s_.wk_live(w)
        mid = ('<span class="livedot">LIVE</span>' if is_live else f'<span class="tag soft">{"Up next" if w == s.nxt else "Upcoming"}</span><div style="margin-top:8px">Projected</div>')
        split = s_.rope(a, b, pa, "chance to win")
        bsa, bsb = (fp(s_.now_pts(w, a)), fp(s_.now_pts(w, b))) if is_live else (f"{A[0]:.1f}", f"{B[0]:.1f}")
        bx = {a: [("projected", f"{A[0]:.1f}")], b: [("projected", f"{B[0]:.1f}")]} if is_live else None
        later = "" if w == s.nxt else f'<p class="note">Weeks after the next one use each player\'s recent Sleeper projections, so these firm up as the week gets closer.</p>'
        body = f"""<section class="field"><div class="wrap"><a class="back" href="../schedule.html#wk{w}">Week {w} schedule</a>
{s_.board(w, a, b, pre, bsa, bsb, mid, False, bx)}{split}</div></section>
{s_.game_nav(w, a, b, pre)}
<main class="wrap">
{s_.story_block(w, a, b, pre, "main")}
<section><h2>{"Lineups" if is_live else "Projected lineups"}</h2>{lu}</section>
<div class="grid2"><section>{bench(a)}</section><section>{bench(b)}</section></div>
{s_.wp_chart(w, a, b, pre) if is_live else ""}
<section><h2>What's at stake <small>odds if they win vs lose this game</small></h2><div class="grid2"><div>{stakes(a, la)}</div><div>{stakes(b, lb)}</div></div></section>
{s_.odds_moves(w, a, b)}
<section><h2>Tale of the tape</h2><div class="panel">{tape}</div></section>
<section><h2>Season series</h2><div class="mini">{series}</div></section>
{s_.story_block(w, a, b, pre, "more")}
</main>{s_.footer(pre)}"""
        return page(f"Week {w}: {s_.TN(a)} vs {s_.TN(b)}, Super League {yr}", body, pre, "schedule")


GP_FILES = {}          # game page bodies, fetched when a game is opened


def bundle(files, s, logo_dir, font_dir, site=None):
    """Turn the page set into ONE self-contained index.html: pages switch by #/hash, logos + fonts embedded once."""
    import re, base64
    pid = lambda path: "home" if path == "index.html" else path[:-5]
    order = ["index.html"] + sorted(k for k in files if k != "index.html")
    first = files["index.html"]
    head = first[:first.index("<body>")]
    head = re.sub(r"<style>@font-face.*?</style>", "", head, count=1, flags=re.S)
    ff = ""
    if os.path.isdir(font_dir):
        for fn in sorted(os.listdir(font_dir)):
            m = re.match(r"(big-shoulders-display|instrument-sans|graduate)-latin-(\d+)-normal\.woff2", fn)
            if not m: continue
            fam = {"big-shoulders-display": "Big Shoulders Display", "instrument-sans": "Instrument Sans", "graduate": "Graduate"}[m.group(1)]
            b64 = base64.b64encode(open(f"{font_dir}/{fn}", "rb").read()).decode()
            ff += f"@font-face{{font-family:'{fam}';font-weight:{m.group(2)};font-display:swap;src:url(data:font/woff2;base64,{b64}) format('woff2')}}"
    lg = ""
    for r in s.R:
        f = f"{logo_dir}/{s.M[r]}.png"
        if os.path.exists(f):
            lg += f".L{r}{{background-image:url(data:image/png;base64,{base64.b64encode(open(f, 'rb').read()).decode()})}}"
    lhf = os.path.join(os.path.dirname(logo_dir), "logo_history.txt"); od = os.path.join(os.path.dirname(logo_dir), "logos_old")
    if os.path.exists(lhf):
        for l in open(lhf):
            if l.startswith("#") or not l.strip(): continue
            ts_, rr_, fn_ = l.rstrip("\n").split("|")[:3]
            if os.path.exists(f"{od}/{fn_}"):
                lg += f".L{rr_}_{os.path.splitext(fn_)[0].replace('.', '_')}{{background-image:url(data:image/{'png' if fn_.endswith('.png') else 'jpeg'};base64,{base64.b64encode(open(f'{od}/{fn_}', 'rb').read()).decode()})}}"
    nd = os.path.join(os.path.dirname(logo_dir), "nfl_logos")
    for ab in NFL_NICK:
        if os.path.exists(f"{nd}/{ab}.png"):
            lg += f".N{ab}{{background-image:url(data:image/png;base64,{base64.b64encode(open(f'{nd}/{ab}.png', 'rb').read()).decode()})}}"
    # past seasons' NFL logos: only the ones that differ from today's get their own class (N{team}_{season}), used by season badges
    ad = os.path.join(os.path.dirname(logo_dir), "nfl_logos_archive"); old_ = []
    if os.path.isdir(ad):
        for y_ in sorted(os.listdir(ad)):
            for ab in NFL_NICK:
                f_ = f"{ad}/{y_}/{ab}.png"
                if os.path.exists(f_) and (not os.path.exists(f"{nd}/{ab}.png") or open(f_, "rb").read() != open(f"{nd}/{ab}.png", "rb").read()):
                    lg += f".N{ab}_{y_}{{background-image:url(data:image/png;base64,{base64.b64encode(open(f_, 'rb').read()).decode()})}}"; old_.append(f"{y_}{ab}")
    lg += "/*NLA:" + ",".join(old_) + "*/"
    bd = os.path.join(os.path.dirname(logo_dir), "brand")
    if os.path.exists(f"{bd}/shield.png"):
        lg += f".brandlogo{{background-image:url(data:image/png;base64,{base64.b64encode(open(f'{bd}/shield.png', 'rb').read()).decode()})}}"
    if os.path.exists(f"{bd}/favicon.png"):
        head = head.replace("</title>", f'</title><link rel="icon" type="image/png" href="data:image/png;base64,{base64.b64encode(open(f"{bd}/favicon.png", "rb").read()).decode()}">', 1)
    head = head.replace("</title>", '</title><meta property="og:site_name" content="Super League"><meta property="og:title" content="Super League 2026">'
                        '<meta property="og:description" content="Standings, odds, records and the weekly Desk."><meta property="og:image" content="https://superleague.website/og/home.jpg">'
                        '<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630"><meta name="twitter:card" content="summary_large_image">', 1)
    pages = []
    for path in order:
        h = files[path]; me = pid(path)
        body = h[h.index("<body>") + 6:h.rindex("</body>")]
        title = re.search(r"<title>(.*?)</title>", h).group(1)
        body = re.sub(r'href="(?:\.\./)?player/([\w-]+)\.html"', lambda m: f'href="#/player/{m.group(1)}"', body)
        body = re.sub(r'href="(?:\.\./)?nfl/(\w+)\.html"', lambda m: f'href="#/nfl/{m.group(1)}"', body)
        body = re.sub(r'href="(?:\.\./)?(team|game|news)/([\w-]+)\.html(?:#([\w-]+))?"', lambda m: f'href="#/{m.group(1)}/{m.group(2)}' + (f'/{m.group(3)}' if m.group(3) else "") + '"', body)
        body = re.sub(r'href="(?:\.\./)?(index|news|standings|playoffs|schedule|teams|players|h2h|draft|races|awards|trades|transactions|excitement|analyzer|records)\.html(?:#([\w-]+))?"', lambda m: f'href="#/{"" if m.group(1) == "index" else m.group(1)}' + (f'/{m.group(2)}' if m.group(2) else "") + '"', body)
        body = re.sub(r'href="#([\w-]+)"', lambda m: f'href="#/{me}/{m.group(1)}"', body)
        body = re.sub(r'id="(wk\d+)"', lambda m: f'id="{me.replace("/", "-")}-{m.group(1)}"', body)
        if me.startswith("game/") and "\n" in body.lstrip("\n"):      # game pages load when opened: the chrome stays here, the rest is its own file
            b0 = body.lstrip("\n"); cut = b0.index("\n"); chrome_, rest = b0[:cut + 1], b0[cut + 1:]
            nm_ = me.split("/", 1)[1]; GP_FILES[f"gp/{nm_}.html"] = rest
            import hashlib; v_ = hashlib.md5(rest.encode()).hexdigest()[:8]
            pages.append(f'<div class="pg" data-p="{me}" data-t="{title}" data-src="/gp/{nm_}.html?v={v_}" hidden>{chrome_}<div class="gpb"><main class="wrap"><p class="muted gpl">Loading the game...</p></main></div></div>')
            continue
        pages.append(f'<div class="pg" data-p="{me}" data-t="{title}"{"" if me == "home" else " hidden"}>{body}</div>')
    js = """<script>
(function(){
  // Clean URLs: superleague.website/records. Old #/ links still work and get rewritten on arrival.
  if(/^#\//.test(location.hash)) history.replaceState(null,'',location.hash.slice(1)||'/');
  if(/^\/team\//.test(location.pathname)) history.replaceState(null,'',location.pathname.replace(/^\/team\//,'/'));
  // team pages live at the top level: superleague.website/Jesse
  var TMN={}; Object.keys(TM).forEach(function(r){ TMN[TM[r][1].toLowerCase()]=TM[r][1]; });
  function short(path){ return path.replace(/^\/team\/([^\/]+)/,'/$1'); }
  var TMR={}; Object.keys(TM).forEach(function(r){ TMR[TM[r][1].toLowerCase()]=r; });
  function RH(){ var p=location.pathname.replace(/\/+$/,'');
    var wk=/^\/week(\d+)(?:\/([^\/]+))?$/i.exec(p);           // /week12 = that week's schedule, /week12/jesse = Jesse's game that week
    if(wk){ var r=wk[2]&&TMR[decodeURIComponent(wk[2]).toLowerCase()], o=r&&window.GOF&&GOF[wk[1]]&&GOF[wk[1]][r];
      if(o){ var x=Math.min(+r,+o), y=Math.max(+r,+o); return '#/game/w'+wk[1]+'-'+x+'-'+y; }
      return '#/schedule/wk'+wk[1]; }
    var m=/^\/team\/(.+)$/.exec(p); if(m) p='/'+m[1]; var q=p.split('/'); if(q[1]&&TMN[q[1].toLowerCase()]) p='/team/'+TMN[q[1].toLowerCase()]+(q.length>2?'/'+q.slice(2).join('/'):''); return '#'+(p||'/'); }
  function nav(u,rep){ var path=short(String(u).replace(/^#/,'')); if(path.charAt(0)!=='/') path='/'+path;
    if(path!==location.pathname){ history[rep?'replaceState':'pushState'](null,'',path); }
    window.dispatchEvent(new Event('hashchange')); }
  window.addEventListener('popstate',function(){ window.dispatchEvent(new Event('hashchange')); });
  window.addEventListener('click',function(e){
    if(e.defaultPrevented||e.button>0||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey) return;
    var a=e.target.closest&&e.target.closest('a[href]'); if(!a||a.target==='_blank') return;
    var h=a.getAttribute('href'); if(!/^#\/|^\/(?!\/)/.test(h)) return;
    e.preventDefault(); nav(h); });
  function fixLinks(root){ [].forEach.call((root||document).querySelectorAll('a[href^="#/"]'),function(a){ a.setAttribute('href',short(a.getAttribute('href').slice(1))); }); }
  fixLinks();
  var pgs=[].slice.call(document.querySelectorAll('.pg'));
  function gpLoad(pg,cb){ var src=pg.getAttribute('data-src'); if(!src){ if(cb) cb(); return; }
    if(pg._ld){ if(cb) pg._ld.push(cb); return; } pg._ld=cb?[cb]:[];
    fetch(src).then(function(r){ if(!r.ok) throw new Error(r.status); return r.text(); }).then(function(t){
      if(/^\\s*<!DOCTYPE/i.test(t)) throw new Error('not a game page');          // the site fallback, not the file: don't nest the whole site
      if(!pg.hasAttribute('data-src')) return; var box=pg.querySelector('.gpb'); box.innerHTML=t; pg.removeAttribute('data-src'); fixLinks(box);
      var q=pg._ld; pg._ld=null; q.forEach(function(f){ f(); }); })
    .catch(function(){ pg._ld=null; var l=pg.querySelector('.gpl'); if(l) l.innerHTML='Couldn\\'t load this game. <a href="">Try again</a>'; }); }
  // warm a game page as soon as a link to it is pointed at or touched, so it's usually there by the click
  function gpWarm(e){ var a=e.target.closest&&e.target.closest('a[href]'); if(!a) return; var h=a.getAttribute('href')||'', m=/^\\/?#?\\/?game\\/(w\\d+-\\d+-\\d+)/.exec(h), id=null;
    if(m) id='game/'+m[1]; else { var wk=/^\\/week(\\d+)\\/([^\\/]+)$/i.exec(h); if(wk&&window.GOF){ var r=TMR[decodeURIComponent(wk[2]).toLowerCase()], o=r&&GOF[wk[1]]&&GOF[wk[1]][r]; if(o) id='game/w'+wk[1]+'-'+Math.min(+r,+o)+'-'+Math.max(+r,+o); } }
    if(!id) return; var pg=document.querySelector('.pg[data-p="'+id+'"][data-src]'); if(pg) gpLoad(pg); }
  document.addEventListener('mouseover',gpWarm,{passive:true}); document.addEventListener('touchstart',gpWarm,{passive:true});
  function go(){
    var h=decodeURIComponent(RH().replace(/^#\\/?/,'')), p=h.split('/'), id, sub;
    var tmn=TMN[(p[0]||'').toLowerCase()]; if(tmn){ p=['team',tmn].concat(p.slice(1)); }
    if(p[0]==='news'&&p[1]&&window.NG&&NG[p[1]]){ nav('#/'+NG[p[1]],true); return; }
    if(p[0]==='player'&&window.PD){ renderPlayer(p[1],p[2]); id='player'; }
    else if(p[0]==='nfl'&&window.PD){ var nsame=(window._lastNFL===p[1]); window._lastNFL=p[1]; renderNFL(p[1],p[2]); id='nfl'; if(nsame) window._keepY=1; }
    else if(p[0]==='team'||p[0]==='game'||(p[0]==='news'&&p[1])){id=p[0]+'/'+p[1];sub=p[2];}else{id=p[0]||'home';sub=p[1];}
    var hit=pgs.filter(function(e){return e.getAttribute('data-p')===id;})[0]||pgs[0];
    if(hit.hasAttribute('data-src')){ pgs.forEach(function(e){e.hidden=(e!==hit);}); document.title=hit.getAttribute('data-t'); window.scrollTo({top:0,left:0,behavior:'instant'});
      gpLoad(hit,function(){ window.dispatchEvent(new Event('hashchange')); }); return; }      // a game page: fetch it, then route again
    var same=(window._lastP===hit.getAttribute('data-p')); window._lastP=hit.getAttribute('data-p');
    pgs.forEach(function(e){e.hidden=(e!==hit);});
    if(p[0]==='players'&&p[1]){ var sec=hit.querySelector('.psearch').closest('section');
      sec.querySelector('.psearch').value=''; sec.querySelector('.pown').value='all';
      [].forEach.call(sec.querySelectorAll('.pf'),function(x){x.classList.toggle('nx',x.getAttribute('data-pos')===p[1]);}); pfilter(sec);
      var th=sec.querySelector('.ptable th[data-k="'+(p[2]==='pts'?4:6)+'"]'); th.removeAttribute('aria-sort'); psort(th);
      var row=p[3]&&sec.querySelector('tr[data-id="'+p[3]+'"]');
      if(row){ row.scrollIntoView({block:'center',behavior:'instant'}); row.classList.add('flash'); setTimeout(function(){row.classList.remove('flash');},2200); return; }
      window.scrollTo({top:0,left:0,behavior:'instant'}); return; }
    if(hit.querySelector('.rdata')){
      if(p[1]&&BOOK[p[1]]){ RBOOK=p[1]; var key=p[2]||'', m=/_(ALL|QB|RB|WR|TE|K|DEF)$/.exec(key); if(m) RPOS=m[1];
        [].forEach.call(hit.querySelectorAll('.rbooks button'),function(x){x.setAttribute('aria-pressed',x.getAttribute('data-b')===RBOOK?'true':'false');});
        hit.querySelector('.rscope').value='L';
        [].forEach.call(hit.querySelectorAll('.rper button'),function(x){x.setAttribute('aria-pressed',x.getAttribute('data-v')==='all'?'true':'false');});
        hit.querySelectorAll('.rper button')[0].textContent=RBOOK==='player'?'Career':'All-time';
        hit._done=1; renderRec(hit);
        var row=key&&hit.querySelector('button.rrow[data-k="'+key+'"]');
        if(row){ row.scrollIntoView({block:'center',behavior:'instant'}); row.classList.add('flash'); setTimeout(function(){row.classList.remove('flash');},2200); return; }
        window.scrollTo({top:0,left:0,behavior:'instant'}); return; }
      if(!hit._done){ hit._done=1; renderRec(hit); }
    }
    document.title=hit.getAttribute('data-t');
    var sel=hit.querySelector('.wsel');
    if(sel){var m=sub&&/^wk(\\d+)$/.exec(sub); setWeek(hit, m?m[1]:sel.getAttribute('data-default')); window.scrollTo({top:0,left:0,behavior:'instant'}); return;}
    var views=hit.querySelectorAll('.tview');
    if(views.length){
      var ym=sub&&/^(\\d{4})(?:-(\\w+))?$/.exec(sub), cur=hit.querySelector('.tview[data-cur]');
      var v=ym?ym[1]:((sub||hit.querySelector('.tview[data-solo]'))?cur.getAttribute('data-v'):'all'), tab=ym?ym[2]:sub;
      if(!hit.querySelector('.tview[data-v="'+v+'"]')) v='all';
      [].forEach.call(views,function(x){x.hidden=x.getAttribute('data-v')!==v;});
      var vw=hit.querySelector('.tview[data-v="'+v+'"]'), tp=vw.querySelectorAll('.tpanel');
      if(tp.length){
        var kk=(tab&&vw.querySelector('.tpanel[data-t="'+tab+'"]'))?tab:'overview';
        [].forEach.call(tp,function(x){x.hidden=x.getAttribute('data-t')!==kk;});
        [].forEach.call(vw.querySelectorAll('.ttabs a[data-tab]'),function(x){x.setAttribute('aria-current',x.getAttribute('data-tab')===kk?'true':'false');});
        var tb=vw.querySelector('.ttabs');
      }
      if(!same) window.scrollTo({top:0,left:0,behavior:'instant'}); return;
    }
    var panels=hit.querySelectorAll('.tpanel');
    if(panels.length){
      var k=(sub&&hit.querySelector('.tpanel[data-t="'+sub+'"]'))?sub:'overview';
      [].forEach.call(panels,function(x){x.hidden=x.getAttribute('data-t')!==k;});
      [].forEach.call(hit.querySelectorAll('.ttabs a'),function(x){x.setAttribute('aria-current',x.getAttribute('data-tab')===k?'true':'false');});
      var bar=hit.querySelector('.ttabs');
      if(!same) window.scrollTo({top:0,left:0,behavior:'instant'});
      return;
    }
    if(window._keepY){ window._keepY=0; return; }
    var t=sub&&document.getElementById(hit.getAttribute('data-p').replace('/','-')+'-'+sub);
    if(t){t.scrollIntoView({behavior:'instant'});}else{window.scrollTo({top:0,left:0,behavior:'instant'});}
  }
  function setWeek(pg,w){
    var sel=pg.querySelector('.wsel'); if(!pg.querySelector('.wkp[data-w="'+w+'"]')) w=sel.getAttribute('data-default');
    sel.value=w;
    [].forEach.call(pg.querySelectorAll('.wkp'),function(x){x.hidden=x.getAttribute('data-w')!==String(w);});
    var i=sel.selectedIndex; pg.querySelector('.wstep[data-d="-1"]').disabled=i<=0; pg.querySelector('.wstep[data-d="1"]').disabled=i>=sel.options.length-1;
  }
  function wkUrl(pg,w){ if(pg&&/^schedule/.test(pg.getAttribute('data-p')||'')) history.replaceState(null,'','/week'+w); }
  document.addEventListener('change',function(e){ if(e.target.classList&&e.target.classList.contains('wsel')){ var pg=e.target.closest('.pg'); setWeek(pg,e.target.value); wkUrl(pg,e.target.value); } });
  document.addEventListener('click',function(e){
    var b=e.target.closest&&e.target.closest('.wstep'); if(!b) return;
    var pg=b.closest('.pg'), sel=pg.querySelector('.wsel'), i=sel.selectedIndex+parseInt(b.getAttribute('data-d'),10);
    if(i>=0&&i<sel.options.length){ setWeek(pg, sel.options[i].value); wkUrl(pg, sel.options[i].value); }
  });
  function showCard(hz){
    var box=hz.closest('.lchart'), c=box.querySelector('.lcard'), svg=hz.ownerSVGElement, g=svg.querySelector('.guide');
    var x=parseFloat(hz.getAttribute('data-x')); c.innerHTML=hz.getAttribute('data-card')+'<button type="button" class="cx" aria-label="Close">&times;</button>'; c.hidden=false;
    c.style.left=Math.min(Math.max(x,18),82)+'%';
    var vx=svg.viewBox.baseVal.width*x/100; g.setAttribute('x1',vx); g.setAttribute('x2',vx); g.setAttribute('opacity','.5');
  }
  function hideCard(box){ var c=box.querySelector('.lcard'); c.hidden=true; box.querySelector('.guide').setAttribute('opacity','0'); }
  document.addEventListener('mouseover',function(e){ var hz=e.target.closest&&e.target.closest('.hz'); if(hz) showCard(hz); });
  document.addEventListener('focusin',function(e){ var hz=e.target.closest&&e.target.closest('.hz'); if(hz) showCard(hz); });
  document.addEventListener('mouseout',function(e){ var hz=e.target.closest&&e.target.closest('.hz'); if(hz&&!(e.relatedTarget&&e.relatedTarget.closest&&(e.relatedTarget.closest('.hz')||e.relatedTarget.closest('.lcard')))) hideCard(hz.closest('.lchart')); });
  document.addEventListener('click',function(e){ var hz=e.target.closest&&e.target.closest('.hz'); if(e.target.closest&&e.target.closest('.lcard')&&!e.target.closest('.cx')) return; if(hz){showCard(hz);} else {[].forEach.call(document.querySelectorAll('.lcard:not([hidden])'),function(c){hideCard(c.closest('.lchart'));});} });
  // the scoreboard over the charts: always shows a moment (the latest by default); tapping or dragging picks another
  function sbReset(box){ var c=box.querySelector('.wpcard'); if(c) c.innerHTML=c.getAttribute('data-def');
    [].forEach.call(box.querySelectorAll('.wpd.on'),function(x){x.classList.remove('on');}); [].forEach.call(box.querySelectorAll('.wpg'),function(l){l.setAttribute('opacity','0');}); }
  document.addEventListener('click',function(e){
    if(window._wpSkip) return;
    var d=e.target.closest&&e.target.closest('.wpc .wpd');
    if(!d){ if(!(e.target.closest&&e.target.closest('.wpc'))) [].forEach.call(document.querySelectorAll('.wpc'),sbReset); return; }
    if(d.classList.contains('on')){ sbReset(d.closest('.wpc')); return; }
    showWp(d);
  });
  function showWp(d){
    var box=d.closest('.wpc'), c=box.querySelector('.wpcard');
    [].forEach.call(box.querySelectorAll('.wpd.on'),function(x){x.classList.remove('on');});
    d.classList.add('on'); c.innerHTML=d.getAttribute('data-card');
    var svg=d.ownerSVGElement, gl=svg&&svg.querySelector('.wpg');
    [].forEach.call(box.querySelectorAll('.wpg'),function(l){ if(l!==gl) l.setAttribute('opacity','0'); });
    if(gl){ var vb=svg.viewBox.baseVal, gx=vb.width*parseFloat(d.getAttribute('data-x'))/100; gl.setAttribute('x1',gx); gl.setAttribute('x2',gx); gl.setAttribute('opacity','1'); }
  }
  // press and drag across the win probability chart: the card follows every play
  var scr=null, scrMoved=false;
  // step one stop at a time (plays, projection changes, check-ins): the only way to land on updates packed close together
  // once you're in a chart (clicked, tapped or dragged on it), the left and right arrow keys step one play at a time
  var WPA_BOX=null;
  document.addEventListener('pointerdown',function(e){ WPA_BOX=(e.target.closest&&e.target.closest('.wpc'))||null; },true);
  document.addEventListener('keydown',function(e){
    if(!WPA_BOX||!document.body.contains(WPA_BOX)||(e.key!=='ArrowLeft'&&e.key!=='ArrowRight')) return;
    var t=e.target; if(t&&(t.tagName==='INPUT'||t.tagName==='SELECT'||t.tagName==='TEXTAREA')) return;
    var bt=WPA_BOX.querySelector('.wps[data-d="'+(e.key==='ArrowLeft'?'-1':'1')+'"]'); if(bt){ e.preventDefault(); bt.click(); }
  });
  document.addEventListener('click',function(e){
    var bt=e.target.closest&&e.target.closest('.wps'); if(!bt) return;
    var box=bt.closest('.wpc'), svg=[].filter.call(box.querySelectorAll('.gfv svg'),function(v){return v.getBoundingClientRect().width>0;})[0]; if(!svg) return;
    var ds=[].slice.call(svg.querySelectorAll('.wpd')), seen={}, L=[];
    ds.forEach(function(d){ var c=d.getAttribute('data-card'); if(!seen[c]){seen[c]=1; L.push(d);} });
    if(!L.length) return;
    var cur=svg.querySelector('.wpd.on'), i=cur?L.findIndex(function(d){return d.getAttribute('data-card')===cur.getAttribute('data-card');}):L.length-1;
    i=Math.max(0,Math.min(L.length-1,i+parseInt(bt.getAttribute('data-d'),10))); window._wpSkip=1; setTimeout(function(){window._wpSkip=0;},0); showWp(L[i]);
  });
  function scrubAt(svg,cx){
    var r=svg.getBoundingClientRect(), fx=(cx-r.left)/r.width*100, best=null, bd=1e9;
    [].forEach.call(svg.querySelectorAll('.wpd'),function(d){ var dx=Math.abs(parseFloat(d.getAttribute('data-x'))-fx); if(dx<bd){bd=dx;best=d;} });
    if(best&&!best.classList.contains('on')) showWp(best);
  }
  document.addEventListener('pointerdown',function(e){
    var svg=e.target.closest&&e.target.closest('.wpc .gfv svg'); if(!svg||e.button>0) return;
    scr=svg; scrMoved=false; scr._x0=e.clientX;
  });
  document.addEventListener('pointermove',function(e){
    if(!scr) return;
    if(!scrMoved&&Math.abs(e.clientX-scr._x0)<6) return;
    if(!scrMoved){ scrMoved=true; try{scr.setPointerCapture(e.pointerId);}catch(_){}} 
    e.preventDefault(); scrubAt(scr,e.clientX);
  });
  document.addEventListener('pointerup',function(){ if(scr&&scrMoved){ window._wpSkip=1; setTimeout(function(){window._wpSkip=0;},50); } scr=null; });
  document.addEventListener('pointercancel',function(){ scr=null; });
  document.addEventListener('keydown',function(e){ if((e.key==='Enter'||e.key===' ')&&e.target.classList&&e.target.classList.contains('wpd')){e.preventDefault(); e.target.dispatchEvent(new MouseEvent('click',{bubbles:true}));} });
  var pc=document.createElement('div'); pc.className='pcard'; pc.hidden=true; pc.innerHTML='<div class="in" role="dialog" aria-modal="true"></div>'; document.body.appendChild(pc);
  function openCard(el){ pc.firstChild.innerHTML=el.getAttribute('data-card')+'<button type="button" class="x">Close</button>'; pc.hidden=false; pc.querySelector('.x').focus(); }
  document.addEventListener('click',function(e){
    if(!pc.hidden && (e.target===pc || (e.target.closest&&e.target.closest('.pcard .x')))){pc.hidden=true;return;}
    var t=e.target.closest&&e.target.closest('[data-card].tap'); if(t&&!e.target.closest('a')){openCard(t);}
  });
  document.addEventListener('keydown',function(e){
    if(e.key==='Escape'&&!pc.hidden){pc.hidden=true;return;}
    if((e.key==='Enter'||e.key===' ')&&e.target.matches&&e.target.matches('[data-card].tap')){e.preventDefault();openCard(e.target);}
  });
  window.addEventListener('hashchange',function(){pc.hidden=true;});
  function esc(t){return String(t).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
  function fpt(v){ if(v===null||v===undefined) return '-'; var r=Math.round(v*100)/100; return (Math.round(r*100)%10)?r.toFixed(2):r.toFixed(1); }
  function tmAt(r,w){ var h=TMW[r]; if(!h||!w) return [TM[r][0],'L'+r]; var v=[TM[r][0],'L'+r]; h.forEach(function(s){ if(+w>=s[0]) v=[s[1],s[2]]; }); return v; }   // name and logo a team had in week w
  function tlink(r,w){ var v=r?tmAt(r,w):null; return r? '<a class="tl" href="#/team/'+TM[r][1]+'/'+YR+'"><i class="im lgs '+v[1]+'"></i><b>'+esc(v[0])+'</b></a>' : '<span class="muted">Free agent</span>'; }
  function mv(t){
    var add=t[2]==='+', k=t[3];
    if(k==='Draft') return '<span class="pos">Drafted '+esc(t[4])+'</span>';
    var lab = k==='Trade' ? (add?'Traded For':'Traded Away')
            : k==='Waiver' ? (add?'Waiver Claim':'Dropped')
            : k==='Free agent' ? (add?'Free Agent Add':'Dropped')
            : k==='Veto undone' ? (add?'Returned (Trade Vetoed)':'Removed (Trade Vetoed)')
            : (add?'Commissioner Add':'Commissioner Removal');
    return '<span class="'+(add?'pos':'neg')+'">'+lab+'</span>';
  }
  function plist(L){ return L.map(function(p){ return PD[p[0]]?'<a class="pn" href="#/player/'+p[0]+'">'+esc(p[1])+'</a>':esc(p[1]); }).join(', '); }
  function tnm(r,w){ var v=r?tmAt(r,w):null; return r?'<a class="tn" href="#/team/'+TM[r][1]+'/'+YR+'"><i class="im lgs '+v[1]+'"></i><b>'+esc(v[0])+'</b></a>':'<b>free agency</b>'; }
  // Super League teams like a reference site: one line per season, tap it for every stint (same team and same NFL team, back to back)
  function mvpsHTML(d, ys){
    var M=[]; ys.forEach(function(y){ if(!d.sea[y]) return; d.sea[y].m.forEach(function(m){ var x=d.sea[y].w.filter(function(z){return z[0]===m[0];})[0]; M.push([y,m[0],m[1],x?x[4]:0,x?x[3]:0]); }); });
    if(!M.length) return ''; var h='<section><h2>Weekly MVPs</h2><div class="scroll"><table style="min-width:0"><thead><tr><th>Week</th><th>For</th><th class="r">Pts</th></tr></thead><tbody>';
    M.forEach(function(m){ h+='<tr><td>'+(m[3]?glink(m[1],m[2],m[3],'Week '+m[1]+', '+m[0]):'Week '+m[1]+', '+m[0])+'</td><td>'+tlink(m[2])+'</td><td class="r big">'+fpt(m[4])+'</td></tr>'; });
    return h+'</tbody></table></div></section>';
  }
  function stintsHTML(d, ys, id, car){
    // reference-site style: one row per Super League team each season; a season with 2+ teams gets a total row on top
    var body='', any=false, FL={};
    ys.forEach(function(y){ var S=d.sea[y]; if(!S) return; var runs=[], cur=null;
      S.w.forEach(function(x){ if(!x[1]){ cur=null; return; } var nt=x[15]||'';
        if(cur&&cur.r===x[1]&&x[0]===cur.b+1){ cur.b=x[0]; cur.ws.push(x); }
        else { cur={r:x[1],nts:[],a:x[0],b:x[0],ws:[x]}; runs.push(cur); }
        if(nt&&cur.nts.indexOf(nt)<0) cur.nts.push(nt); });
      // two stints with the same manager are one row, as if the weeks were back to back
      var mg={}; runs=runs.filter(function(u){ var m=mg[u.r]; if(!m){ mg[u.r]=u; return true; } m.ws=m.ws.concat(u.ws); m.b=u.b; u.nts.forEach(function(n){ if(m.nts.indexOf(n)<0) m.nts.push(n); }); return false; });
      if(!runs.length) return; any=true;
      var agg=function(ws){ var st=ws.filter(function(x){return x[2]&&x[3]!=null;}), o={wk:ws.length,gs:st.length,pts:0,war:0,edge:0,wi:0,w:0,l:0};
        st.forEach(function(x){ o.pts+=x[3]||0; o.war+=x[9]||0; o.edge+=x[10]||0; o.wi+=x[17]||0; if(x[6]===1) o.w++; else if(x[6]===0) o.l++; }); return o; };
      var X=pstats(d,y), M_=function(v,txt,k){ return mark(v,txt,k,y,d.p,FL); };
      var cells=function(o,top){ var c=function(v,txt,k){ return top?M_(v,txt,k):txt; };
        return '<td class="c">'+c(X.gs,o.gs,'gs')+'<small class="ofw"> of '+o.wk+'</small></td><td class="c">'+(o.w+o.l?c(X.w,o.w+'-'+o.l,'w'):'-')+'</td>'
        +'<td class="r">'+c(X.pts,fpt(o.pts),'pts')+'</td><td class="r">'+(o.gs?c(X.ppg,fpt(o.pts/o.gs),'ppg'):'-')+'</td>'
        +'<td class="r '+(o.war>0.005?'pos':o.war<-0.005?'neg':'')+'">'+c(X.war,sgn(o.war.toFixed(2)),'war')+'</td><td class="r '+(o.edge>0.05?'pos':o.edge<-0.05?'neg':'')+'">'+c(X.edge,sgn(o.edge.toFixed(1)),'edge')+'</td><td class="r '+(o.wi>0.005?'pos':o.wi<-0.005?'neg':'')+'">'+(o.gs?sgn(o.wi.toFixed(2)):'-')+'</td>'; };
      var lg=function(L){ return L.map(function(t){ return '<a href="#/nfl/'+t+'" title="'+t+'"><i class="nfl nflm N'+t+'"></i></a>'; }).join(''); };
      var tnl=function(r){ return '<a class="tn" href="#/team/'+TM[r][1]+'/'+YR+'"><i class="im lgs L'+r+'"></i><b><span class="nmf">'+esc(TM[r][0])+'</span><span class="nms">'+esc(TM[r][1])+'</span></b></a>'; };
      var yl=ys.length>1?'<a class="go" href="#/player/'+id+'/'+y+'">'+y+'</a>':y;
      if(runs.length>1){ var all=[], rs=[], nts=[]; runs.forEach(function(u){ all=all.concat(u.ws); if(rs.indexOf(u.r)<0) rs.push(u.r); u.nts.forEach(function(n){ if(nts.indexOf(n)<0) nts.push(n); }); });
        body+='<tr class="sttot"><td>'+yl+'</td><td>'+(rs.length>2?rs.length+' teams':rs.map(function(r){return esc(TM[r][1]);}).join(' / '))+'</td><td class="c">'+(nts.length>2?nts.length+' teams':lg(nts))+'</td>'+cells(agg(all),1)+'</tr>';
        // the team rows always add up to the season row exactly: round the parts so they sum to the rounded whole
        var T=agg(all), A=runs.map(function(u){ return agg(u.ws); });
        [['pts',2],['war',2],['edge',1],['wi',2]].forEach(function(kd){ var k=kd[0], f=Math.pow(10,kd[1]);
          var R=A.map(function(o){ return Math.round(o[k]*f); }), diff=Math.round((k==='pts'?T[k]:parseFloat(T[k].toFixed(kd[1])))*f)-R.reduce(function(a,b){return a+b;},0);
          var ord=A.map(function(o,i){ return [o[k]*f-R[i],i]; }).sort(function(a,b){ return diff>0?b[0]-a[0]:a[0]-b[0]; });
          for(var j=0;diff!==0&&j<ord.length*3;j++){ var i=ord[j%ord.length][1], st=diff>0?1:-1; R[i]+=st; diff-=st; }
          A.forEach(function(o,i){ o[k]=R[i]/f; }); });
        runs.forEach(function(u,i){ body+='<tr class="stsub2"><td></td><td>'+tnl(u.r)+'</td><td class="c">'+(nts.length>1?lg(u.nts):'')+'</td>'+cells(A[i])+'</tr>'; }); }
      else { var u=runs[0]; body+='<tr class="sttot"><td>'+yl+'</td><td>'+tnl(u.r)+'</td><td class="c">'+lg(u.nts)+'</td>'+cells(agg(u.ws),1)+'</tr>'; }
    });
    var key=(FL.b||FL.i?'<div class="zkey" style="margin-top:8px">'+(FL.b?'<span><b class="ldr">Bold</b> led the league</span>':'')+(FL.i?'<span><i class="ldp">Italic</i> led all '+esc(d.p)+'s</span>':'')+'</div>':'');
    return any?'<section><h2>'+(car?'By season':'Season')+'</h2><div class="scroll"><table class="stint" style="min-width:0"><thead><tr><th>Year</th><th>Team</th><th class="c">NFL</th><th class="c"><span class="tip" tabindex="0" data-tip="Weeks he started, of the weeks he was on that roster.">Started</span></th><th class="c">Record</th><th class="r">Pts</th><th class="r">PPG</th><th class="r">WAR</th><th class="r">PAA</th><th class="r">Win Impact</th></tr></thead><tbody>'+body+'</tbody></table></div>'+key+'</section>':'';
  }
  document.addEventListener('click',function(e){ var r=e.target.closest&&e.target.closest('tr.sty'); if(!r) return; var b=r.parentNode; b.classList.toggle('open'); r.setAttribute('aria-expanded',b.classList.contains('open')); }, true);
  document.addEventListener('keydown',function(e){ if((e.key==='Enter'||e.key===' ')&&e.target.classList&&e.target.classList.contains('sty')){ e.preventDefault(); e.target.click(); } });
  // a player's moves as a timeline: what happened, who was on the other end, and what he did for that team after
  function movesHTML(d, ys){
    var items=[];
    ys.forEach(function(y){ var S=d.sea[y]; if(!S) return;
      S.x.forEach(function(t,k){
        var nxt=S.x[k+1], end=nxt?nxt[0]:99, add=t[2]==='+', K=t[3], r=t[1];
        var stint='';
        var chip, cls, main, sub='';
        if(K==='Draft'){ chip='Draft'; cls='dr'; main='Drafted by '+tnm(r)+', pick '+esc(t[4]);
          }
        else if(K==='Trade'){ chip='Trade'; cls='tr'; main='Traded to '+tnm(r)+' from '+tnm(t[5]);
          sub=((t[6]||[]).length?'<div class="mvd"><span>With</span>'+plist(t[6])+'</div>':'')+((t[7]||[]).length?'<div class="mvd"><span>For</span>'+plist(t[7])+'</div>':''); }
        else if(!add){ chip='Dropped'; cls='dp'; main='Dropped by '+tnm(r)+(K==='Veto undone'?' when a trade was vetoed':'');
          if((t[6]||[]).length) sub='<div class="mvd"><span>Added</span>'+plist(t[6])+'</div>'; }
        else { chip=K==='Waiver'?'Waiver claim':(K==='Free agent'?'Free agent':(K==='Veto undone'?'Trade vetoed':'Commissioner')); cls=K==='Waiver'?'wv':'fa';
          main=(K==='Waiver'?'Claimed off waivers by ':(K==='Free agent'?'Picked up by ':'Returned to '))+tnm(r);
          if((t[6]||[]).length) sub='<div class="mvd"><span>Dropped</span>'+plist(t[6])+'</div>'; }
        items.push('<li class="mvx '+cls+'"><div class="mvh"><span class="mvc">'+chip+'</span><span class="mvw">'+(t[0]?'Week '+t[0]:'Preseason')+', '+y+'</span>'+(t[4]&&K!=='Draft'?'<time>'+esc(t[4])+'</time>':'')+'</div><div class="mvm">'+main+'</div>'+sub+stint+'</li>');
      }); });
    return items.length?'<section><h2>Moves</h2><ol class="mvl">'+items.reverse().join('')+'</ol></section>':'';
  }
  var INJ={Questionable:'Q',Doubtful:'D',Out:'O',Sus:'SUS'}; function ij(j){return j?' <span class="stg inj">'+esc(INJ[j]||j)+'</span>':'';}
  function ngame(ab,x){ var g=x.y===YR&&window.NSCH&&NSCH[ab]&&NSCH[ab][x.w]; if(!g) return '<span class="muted">-</span>';
    var opp=(g[1]?'vs ':'at ')+'<a href="#/nfl/'+g[0]+'" title="'+esc(NFLN[g[0]]||g[0])+'" style="text-decoration:none"><i class="nfl nflm N'+g[0]+'"></i> '+esc(g[0])+'</a>'; if(g.length<5) return opp;
    var r=g[2]>g[3]?'W':(g[2]<g[3]?'L':'T'); return opp+' <span class="'+(r==='W'?'pos':(r==='L'?'neg':'muted'))+'">'+(g[4]?r+' ':'')+g[2]+'-'+g[3]+'</span>'+(g[4]?'':' <span class="muted">live</span>'); }
  function renderNFLAll(yr){          // every NFL team, sortable, like the Players page
    var el=document.getElementById('nv'), YRS={};
    Object.keys(PD).forEach(function(i){ Object.keys(PD[i].sea).forEach(function(y){ YRS[y]=1; }); });
    var yrs=Object.keys(YRS).sort().reverse(); if(!yr||!YRS[yr]) yr='all';
    var T={}; Object.keys(NFLN).forEach(function(t){ T[t]={on:0,pl:0,gs:0,wr:0,pts:0,war:0,edge:0,top:null}; });
    Object.keys(PD).forEach(function(i){ var d=PD[i], seen={};
      if(d.o&&T[d.t]) T[d.t].on++;
      Object.keys(d.sea).forEach(function(y){ if(yr!=='all'&&y!==yr) return; var S=d.sea[y], x=S.s, nt=(S.nt||[]).length?S.nt:(d.t?[d.t]:[]);
        nt.forEach(function(t){ var a=T[t]; if(!a) return; if(!seen[t]){ seen[t]={war:0}; a.pl++; }
          a.gs+=x[0]; a.pts+=x[1]; a.war+=x[3]; a.edge+=x[4]; a.wr+=S.w.filter(function(q){return q[1];}).length; seen[t].war+=x[3]; }); });
      Object.keys(seen).forEach(function(t){ var a=T[t]; if(seen[t].war&&(!a.top||seen[t].war>a.top[1])) a.top=[i,seen[t].war]; }); });
    var ks=Object.keys(T).sort(function(a,b){ return (T[b].war-T[a].war)||(T[b].pts-T[a].pts); });
    var cv=function(v){ return v>0.005?'pos':(v<-0.005?'neg':'muted'); }, th=function(lab,c,k,def){ return '<th class="'+c+' srt" data-c="'+k+'" data-s="'+(k?'n':'t')+'" tabindex="0" role="button"'+(def?' aria-sort="descending"':'')+'>'+lab+'</th>'; };
    var h='<section class="field"><div class="wrap"><a class="back" href="#/players">All players</a><h1>NFL teams</h1><p class="lede">All 32 teams by what their players have done on Super League rosters. Tap a column to sort.</p></div></section>';
    h+='<div class="tchips wrap"><div class="chips"><a class="'+(yr==='all'?'nx':'')+'" href="#/nfl/all">All-time</a>'+yrs.map(function(y){ return '<a class="'+(yr===y?'nx':'')+'" href="#/nfl/'+y+'">'+y+'</a>'; }).join('')+'</div></div><main class="wrap">';
    h+='<section><div class="scroll"><table class="srtab nflt" style="min-width:0"><thead><tr>'+th('Team','',0)+th('WAR','r',1,1)+th('PAA','r',2)+th('Pts started','r',3)
      +'<th class="r srt" data-c="4" data-s="n" tabindex="0" role="button"><span class="tip" tabindex="0" data-tip="Starts, of the weeks their players spent on Super League rosters.">Started</span></th>'+th('Players','r',5)+th('On rosters now','r',6)+'<th>Best player</th></tr></thead><tbody>';
    ks.forEach(function(t){ var a=T[t], tp=a.top;
      h+='<tr class="'+(a.pl?'':'bn')+'"><td data-v="'+esc(NFLN[t].toLowerCase())+'"><a class="pn" href="#/nfl/'+t+'"><i class="nfl nflm N'+t+'"></i> <b>'+esc(NFLN[t])+'</b></a></td>'
        +'<td class="r '+cv(a.war)+'" data-v="'+a.war+'">'+(a.gs?sgn(+a.war.toFixed(2)):'-')+'</td><td class="r '+cv(a.edge)+'" data-v="'+a.edge+'">'+(a.gs?(a.edge>=0?'+':'')+a.edge.toFixed(1):'-')+'</td>'
        +'<td class="r big" data-v="'+a.pts+'">'+(a.gs?fpt(a.pts):'-')+'</td><td class="r" data-v="'+(a.gs+a.wr/1000)+'">'+(a.wr?a.gs+' of '+a.wr:'-')+'</td>'
        +'<td class="r" data-v="'+a.pl+'">'+a.pl+'</td><td class="r" data-v="'+a.on+'">'+a.on+'</td>'
        +'<td style="white-space:nowrap">'+(tp?'<a class="pn" href="#/player/'+tp[0]+'">'+esc(PD[tp[0]].n)+'</a> <span class="muted">'+sgn(+tp[1].toFixed(2))+' WAR</span>':'<span class="muted">-</span>')+'</td></tr>'; });
    h+='</tbody></table></div><p class="note">Stats count only Super League starts while the player was on that NFL team. </p></section></main><footer><div class="wrap">Super League '+YR+'.</div></footer>';
    el.innerHTML=h; document.querySelector('.pg[data-p="nfl"]').setAttribute('data-t', 'NFL teams, Super League '+YR);
  }
  function renderNFL(ab, sub){
    if(!ab||!NFLN[ab]) return renderNFLAll(ab);
    var el=document.getElementById('nv'), full=(NFLN[ab]||ab), YRS={};
    Object.keys(PD).forEach(function(i){ Object.keys(PD[i].sea).forEach(function(y){ YRS[y]=1; }); });
    var yrs=Object.keys(YRS).sort().reverse(), m=/^(\\d{4}|all)?-?(\\w+)?$/.exec(sub||'')||[], yr=m[1]||'all', tab=m[2]||'players';
    if(yr!=='all'&&!YRS[yr]) yr='all'; if(['players','weekly','teams'].indexOf(tab)<0) tab='players';
    var useY=function(y){ return yr==='all'||y===yr; };
    var inTeam=function(d,y){ var S=d.sea[y]; return S&&((S.nt||[]).indexOf(ab)>=0||(!(S.nt||[]).length&&d.t===ab)); };
    var ids=Object.keys(PD).filter(function(i){ return Object.keys(PD[i].sea).some(function(y){ return useY(y)&&inTeam(PD[i],y); }); });
    var agg={}, st=0, pts=0, war=0, edge=0, wk={}, sl={};
    ids.forEach(function(i){ var d=PD[i], a={gs:0,pts:0,war:0,edge:0,wr:0}; Object.keys(d.sea).forEach(function(y){ if(!useY(y)||!inTeam(d,y)) return; var S=d.sea[y], x=S.s;
        a.gs+=x[0]; a.pts+=x[1]; a.war+=x[3]; a.edge+=x[4]; a.wr+=S.w.filter(function(q){return q[1];}).length;
        S.w.forEach(function(q){ if(!q[1]) return; var k=y+'|'+q[0]; wk[k]=wk[k]||{y:y,w:q[0],gs:0,pts:0,ros:0,top:null}; wk[k].ros++;
          var T=sl[q[1]]=sl[q[1]]||{gs:0,pts:0,war:0,pl:{}}; T.pl[i]=1;
          if(q[2]){ wk[k].gs++; wk[k].pts+=q[3]||0; T.gs++; T.pts+=q[3]||0; T.war+=q[9]||0; if(q[10]!=null&&(!wk[k].top||q[10]>wk[k].top[1])) wk[k].top=[i,q[10],q[3],q[1]]; } }); });
      agg[i]=a; st+=a.gs; pts+=a.pts; war+=a.war; edge+=a.edge; });
    var on=ids.filter(function(i){return PD[i].o&&PD[i].t===ab;}).length;
    var base='#/nfl/'+ab+'/';
    var h='<section class="field"><div class="wrap"><a class="back" href="#/nfl">NFL teams</a><div class="hero"><i class="nfl nflh N'+ab+'"></i><div><h1>'+esc(full)+'</h1><div class="sub">'+esc(ab)+(BY[ab]?', bye Week '+BY[ab]:'')+'</div></div></div>';
    h+='<div class="herostats"><span><b>'+on+'</b>on rosters now</span><span><b>'+ids.length+'</b>Super League players</span><span><b>'+st+'</b>starts</span><span><b>'+fpt(pts)+'</b>pts started</span><span><b>'+sgn(+war.toFixed(2))+'</b>WAR</span><span><b>'+(edge>=0?'+':'')+edge.toFixed(1)+'</b>PAA</span></div></div></section>';
    h+='<div class="tchips wrap"><div class="chips">'+'<a class="'+(yr==='all'?'nx':'')+'" href="'+base+'all-'+tab+'">All-time</a>'+yrs.map(function(y){ return '<a class="'+(yr===y?'nx':'')+'" href="'+base+y+'-'+tab+'">'+y+'</a>'; }).join('')+'</div></div>';
    h+='<nav class="ttabs"><div class="wrap">'+[['players','Players'],['weekly','By week'],['teams','Super League teams']].map(function(x){ return '<a href="'+base+yr+'-'+x[0]+'" data-tab="'+x[0]+'" aria-current="'+(x[0]===tab?'true':'false')+'">'+x[1]+'</a>'; }).join('')+'</div></nav><main class="wrap">';
    var cv=function(v){ return v>0.005?'pos':(v<-0.005?'neg':'muted'); }, th=function(lab,c,k,def){ return '<th class="'+c+' srt" data-c="'+k+'" tabindex="0" role="button"'+(def?' aria-sort="descending"':'')+'>'+lab+'</th>'; };
    if(tab==='players'){
      ids.sort(function(a,b){ return agg[b].war-agg[a].war; });
      h+='<section><div class="scroll"><table class="srtab nflt" style="min-width:0"><thead><tr>'+th('Player','',0)+th('Pos','c',1)+th('Team','',2)+th('WAR','r',3,1)+th('Pts','r',4)+th('Avg','r',5)+th('PAA','r nx',6)+'<th class="r srt" data-c="7" tabindex="0" role="button"><span class="tip" tabindex="0" data-tip="Weeks he started, of the weeks he was on a Super League roster.">Started</span></th></tr></thead><tbody>';
      ids.forEach(function(i){ var d=PD[i], a=agg[i], avg=a.gs?a.pts/a.gs:null, cur=d.o&&d.t===ab;
        h+='<tr class="'+(cur?'':'bn')+'"><td data-v="'+esc(d.n.toLowerCase())+'"><a class="pn" href="#/player/'+i+'">'+(cur?'<b>'+esc(d.n)+'</b>':esc(d.n))+'</a>'+ij(d.j)+'</td><td class="c" data-v="'+['QB','RB','WR','TE','K','DEF'].indexOf(d.p)+'">'+esc(d.p)+'</td>'
          +'<td data-v="'+(d.o?esc(TM[d.o][0].toLowerCase()):'zzz')+'">'+tlink(d.o)+'</td><td class="r '+cv(a.war)+'" data-v="'+a.war+'">'+(a.gs?sgn(+a.war.toFixed(2)):'-')+'</td><td class="r big" data-v="'+a.pts+'">'+(a.gs?fpt(a.pts):'-')+'</td>'
          +'<td class="r" data-v="'+(avg==null?-1:avg)+'">'+(avg==null?'-':avg.toFixed(1))+'</td><td class="r nx '+cv(a.edge)+'" data-v="'+a.edge+'">'+(a.gs?(a.edge>=0?'+':'')+a.edge.toFixed(1):'-')+'</td><td class="r" data-v="'+(a.gs+a.wr/1000)+'">'+(a.wr?a.gs+' of '+a.wr:'-')+'</td></tr>'; });
      if(!ids.length) h+='<tr><td colspan="8" class="muted">No Super League players.</td></tr>';
      h+='</tbody></table></div><p class="note">Every '+esc(full)+' player who has been on a Super League roster. Bold = on a roster now. Stats are from Super League starts.</p></section>';
    } else if(tab==='weekly'){
      var ks=Object.keys(wk).sort(function(a,b){ var x=wk[a], y=wk[b]; return (y.y-x.y)||(y.w-x.w); });
      h+='<section><div class="scroll"><table class="srtab nflt" style="min-width:0"><thead><tr>'+th('Week','c',0)+'<th>Game</th>'+th('Rostered','r',2)+th('Starts','r',3)+th('Pts started','r',4)+'<th>Best start</th></tr></thead><tbody>';
      ks.forEach(function(k){ var x=wk[k], bye=BY[ab]===x.w&&x.y===YR, tp=x.top;
        h+='<tr><td class="c" data-v="'+x.y+String(x.w).padStart(2,'0')+'">'+(yr==='all'&&yrs.length>1?x.y+' ':'')+'W'+x.w+'</td><td>'+ngame(ab,x)+'</td><td class="r" data-v="'+x.ros+'">'+x.ros+'</td><td class="r" data-v="'+x.gs+'">'+(bye?'<span class="byec">BYE</span>':x.gs)+'</td><td class="r big" data-v="'+x.pts+'">'+(x.gs?fpt(x.pts):'-')+'</td>'
          +'<td>'+(tp?'<a class="pn" href="#/player/'+tp[0]+'">'+esc(PD[tp[0]].n)+'</a> <span class="muted">'+fpt(tp[2])+', '+(tp[1]>=0?'+':'')+tp[1].toFixed(1)+' PAA</span>':'<span class="muted">-</span>')+'</td></tr>'; });
      if(!ks.length) h+='<tr><td colspan="6" class="muted">No weeks yet.</td></tr>';
      h+='</tbody></table></div><p class="note">How many '+esc(full)+' players were on Super League rosters and started each week, and the best start by PAA.</p></section>';
    } else {
      var ts=Object.keys(sl).sort(function(a,b){ return sl[b].pts-sl[a].pts; });
      h+='<section><div class="scroll"><table class="srtab nflt" style="min-width:0"><thead><tr>'+th('Team','',0)+th('Players','r',1)+th('Starts','r',2)+th('Pts','r',3,1)+th('WAR','r',4)+'</tr></thead><tbody>';
      ts.forEach(function(r){ var x=sl[r], n=Object.keys(x.pl).length;
        h+='<tr><td data-v="'+esc(TM[r][0].toLowerCase())+'">'+tlink(+r)+'</td><td class="r" data-v="'+n+'">'+n+'</td><td class="r" data-v="'+x.gs+'">'+x.gs+'</td><td class="r big" data-v="'+x.pts+'">'+(x.gs?fpt(x.pts):'-')+'</td><td class="r '+cv(x.war)+'" data-v="'+x.war+'">'+(x.gs?sgn(+x.war.toFixed(2)):'-')+'</td></tr>'; });
      if(!ts.length) h+='<tr><td colspan="5" class="muted">None yet.</td></tr>';
      h+='</tbody></table></div><p class="note">Which Super League teams have leaned on '+esc(full)+' players.</p></section>';
    }
    h+='</main><footer><div class="wrap">Super League '+YR+'.</div></footer>';
    el.innerHTML=h; document.querySelector('.pg[data-p="nfl"]').setAttribute('data-t', full+', Super League '+YR);
  }
  document.addEventListener('click',function(e){ var th=e.target.closest&&e.target.closest('table.srtab th.srt'); if(!th) return;
    var tb=th.closest('table'), c=+th.getAttribute('data-c'), body=tb.tBodies[0], rows=[].slice.call(body.rows), cur=th.getAttribute('aria-sort');
    var txt=th.hasAttribute('data-s')?th.getAttribute('data-s')==='t':(c===0||c===2), d=cur==='descending'?1:(cur==='ascending'?-1:(txt||c===1?1:-1));
    rows.sort(function(a,b){ var x=a.cells[c].getAttribute('data-v'), y=b.cells[c].getAttribute('data-v'); if(!txt){ x=+x; y=+y; return d*(x-y); } return d*(x<y?-1:x>y?1:0); });
    rows.forEach(function(r){ body.appendChild(r); }); [].forEach.call(th.parentNode.children,function(h){ h.removeAttribute('aria-sort'); }); th.setAttribute('aria-sort', d<0?'descending':'ascending'); });
  document.addEventListener('click',function(e){ var th=e.target.closest&&e.target.closest('table.exctab th.xs'); if(!th) return;
    var tb=th.closest('table'), c=[].indexOf.call(th.parentNode.children,th), body=tb.tBodies[0], rows=[].slice.call(body.rows), txt=th.getAttribute('data-t')==='s', cur=th.getAttribute('aria-sort');
    var d=cur==='descending'?1:(cur==='ascending'?-1:(txt?1:-1));
    rows.sort(function(a,b){ var x=a.cells[c].getAttribute('data-v'), y=b.cells[c].getAttribute('data-v'); if(!txt) return d*((+x)-(+y)); return d*(x<y?-1:x>y?1:0); });
    rows.forEach(function(r){ body.appendChild(r); }); [].forEach.call(th.parentNode.children,function(h){ h.removeAttribute('aria-sort'); }); th.setAttribute('aria-sort', d<0?'descending':'ascending'); });
  function fch(v){ return (Math.round(v*100)/100).toFixed(2).replace(/\\.?0+$/,''); }
  function pc1(p){ return (Math.round(p*1000)/10).toFixed(1).replace(/\\.0$/,'')+'%'; }
  function sgn(v){ return (v>0?'+':'')+v; }
  function glink(w,r,o,txt){ var a=Math.min(r,o), b=Math.max(r,o); return '<a class="go" href="#/game/w'+w+'-'+a+'-'+b+'">'+txt+'</a>'; }
  var LEAD={};
  function pstats(d,y){ var S=d.sea[y], st=S.s, w=0, l=0; S.w.forEach(function(x){ if(x[2]&&x[6]!==null&&x[6]!==undefined){ if(x[6]) w++; else l++; } });
    return {gs:st[0], pts:st[1], ppg:st[0]>=4?st[1]/st[0]:null, war:st[3], edge:st[4], w:w, wp:(w+l)>=4?w/(w+l):null}; }
  function leaders(y){ if(LEAD[y]) return LEAD[y]; var L={all:{},pos:{}};
    Object.keys(PD).forEach(function(i){ var d=PD[i]; if(!d.sea[y]) return; var x=pstats(d,y); L.pos[d.p]=L.pos[d.p]||{};
      Object.keys(x).forEach(function(k){ var v=x[k]; if(v===null||!(v>0)) return; if(!(v<=L.all[k])) L.all[k]=v; if(!(v<=L.pos[d.p][k])) L.pos[d.p][k]=v; }); });
    return LEAD[y]=L; }
  function mark(v,txt,k,y,pos,flag){ if(v===null||v===undefined) return txt; var L=leaders(y);
    if(v>0&&Math.abs(v-L.all[k])<1e-9){ flag.b=1; return '<b class="ldr">'+txt+'</b>'; }
    if(v>0&&L.pos[pos]&&Math.abs(v-L.pos[pos][k])<1e-9){ flag.i=1; return '<i class="ldp">'+txt+'</i>'; }
    return txt; }
  // position rank: points in Super League starts (QB8 = 8th-most points started at QB); overall rank: WAR, the one measure across positions
  function prank(id,yr,all,ix){ ix=ix==null?(all?3:1):ix; var d=PD[id], war=function(x){ var t=0,g=0; Object.keys(x.sea).forEach(function(y){ if(!yr||y===yr){ t+=x.sea[y].s[ix]; g+=x.sea[y].s[0]; } }); return g?t:null; };
    var me=war(d); if(me===null) return null; var r=1;
    Object.keys(PD).forEach(function(i){ var x=PD[i]; if(i===id||(!all&&x.p!==d.p)) return; var v=war(x); if(v!==null&&Math.round(v*100)>Math.round(me*100)) r++; });
    return all?r:d.p+r; }
  function gameRecords(pg){       // a game page: every record (top 3, all-time) set in this game, from the Record Book's own data
    var rp=document.querySelector('.pg[data-p="records"]'); if(!rp||typeof BOOK==='undefined') return '';
    var u=pg.getAttribute('data-p')+'.html', D=recData(rp).L, X=D.all==='='?D[Object.keys(D).filter(function(k){return k!=='all';})[0]]:D.all, rows=[], ord=0;
    var nth=function(n){ return n===1?'Record':n===2?'2nd all-time':'3rd all-time'; };
    var scan=function(book,isP){ BOOK[book].forEach(function(g){ if(g[0]!=='Single game'&&g[0]!=='Biggest comebacks') return; g[1].forEach(function(c){
      var keys=isP?['ALL','QB','RB','WR','TE','K','DEF']:[''], got={};
      keys.forEach(function(ps){ var L=X[c[0]+(isP?'_'+ps:'')]; if(!L) return;
        L.forEach(function(e,ix){ if(e[6]!==u) return; var id=(isP?e[2]:e[1])+'|'+c[0]; if(got[id]) return;
          var first=0; while(first<L.length&&tv(L[first])!==tv(e)) first++; var rk=first+1; if(rk>3) return;
          var shared=L.filter(function(x){return tv(x)===tv(e);}).length>1, d=isP&&PD[e[2]], lab=isP&&ps!=='ALL'?c[1].replace('the #1 at his position','the #1 '+ps)+' by a '+ps:c[1];
          if(isP&&ps!=='ALL'&&rk>1) return;
          got[id]=1;
          var who=isP?(d?d.n:'')+' ('+TM[e[1]][1]+')':(OVER[c[0]]&&e[3]?TM[e[1]][1]+(SYM[c[0]]?' vs ':' over ')+TM[e[3]][1]:TM[e[1]][1]);
          rows.push({rk:rk, o:ord++, h:'<a class="hrr" href="#/records/'+book+'/'+c[0]+(isP?'_'+ps:'')+'"><span class="hrn"><b>'+esc(lab)+'</b><small>'+esc(who)+', '+nth(rk)+(shared?'<i class="hrtie">Shared</i>':'')+'</small></span><span class="hrv">'+esc(e[0])+'</span></a>'}); }); }); }); }); };
    scan('team',false); scan('player',true);
    if(!rows.length) return '';
    rows.sort(function(a,b){ return (a.rk-b.rk)||(a.o-b.o); });
    var n1=rows.filter(function(r){return r.rk===1;}).length;
    return '<section class="hrsec grec"><h2>Records from this game</h2><div class="hrstrip"><div><b>'+n1+'</b><span>Records set</span></div><div><b>'+(rows.length-n1)+'</b><span>Top 3 all-time</span></div></div><div class="hrl">'+rows.map(function(r){return r.h;}).join('')+'</div></section>';
  }
  function teamRecords(r){        // a manager page: every Record Book record (all-time #1) this manager holds
    var rp=document.querySelector('.pg[data-p="records"]'); if(!rp||typeof BOOK==='undefined') return '';
    var D=recData(rp).L, X=D.all==='='?D[Object.keys(D).filter(function(k){return k!=='all';})[0]]:D.all, rows=[], seen={};
    ['mgr','team'].forEach(function(book){ if(!BOOK[book]) return; BOOK[book].forEach(function(g){ g[1].forEach(function(c){ var L=X[c[0]]; if(!L||!L.length) return;
      L.forEach(function(e){ if(tv(e)!==tv(L[0])||+e[1]!==+r) return; var shared=L.filter(function(x){return tv(x)===tv(L[0]);}).length>1;
        var when=e[4]?'Week '+e[4]+(e[5]?', '+e[5]:''):(e[5]||''); if(seen[c[1]+'|'+e[0]]) return; seen[c[1]+'|'+e[0]]=1;   // one season so far: season and all-time are the same record
        rows.push({sh:shared, mg:book==='mgr', h:'<a class="hrr" href="#/records/'+book+'/'+c[0]+'"><span class="hrn"><b>'+esc(c[1])+'</b><small>'+esc(g[0])+(when?', '+esc(when):'')+(shared?'<i class="hrtie">Shared</i>':'')+'</small></span><span class="hrv">'+esc(e[0])+'</span></a>'}); }); }); }); });
    if(!rows.length) return '<section class="hrsec"><h2>Records held</h2><p class="intro">None yet.</p></section>';
    var nS=rows.filter(function(x){return x.sh;}).length, nM=rows.filter(function(x){return x.mg;}).length;
    var strip='<div class="hrstrip"><div><b>'+rows.length+'</b><span>Total</span></div><div><b>'+(rows.length-nM)+'</b><span>Team records</span></div><div><b>'+nM+'</b><span>Manager records</span></div>'+(nS?'<div><b>'+nS+'</b><span>Shared</span></div>':'')+'</div>';
    var grp=function(mg,lab){ var L=rows.filter(function(x){return x.mg===mg;}); return L.length?'<h3 class="hrgh">'+lab+'</h3><div class="hrl">'+L.map(function(x){return x.h;}).join('')+'</div>':''; };
    return '<section class="hrsec"><h2>Records held</h2>'+strip+grp(false,'Team records')+grp(true,'Manager records')+'</section>';
  }
  function addTeamRecords(){ var m=/^#\/team\/([^\/]+)$/.exec(RH()); if(!m) return;
    var pg=document.querySelector('.pg[data-p="team/'+m[1]+'"]'); if(!pg||pg._tr) return; var r=Object.keys(TM).filter(function(k){return TM[k][1]===decodeURIComponent(m[1]);})[0]; if(!r) return; pg._tr=1;
    var v=pg.querySelector('.tview[data-v="all"] main'); if(!v) return; var box=document.createElement('div'); box.innerHTML=teamRecords(r);
    var first=v.querySelector('section'); if(first&&first.nextSibling) v.insertBefore(box.firstChild, first.nextSibling); else v.appendChild(box.firstChild); }
  window.addEventListener('hashchange',function(){ setTimeout(addTeamRecords,30); }); setTimeout(addTeamRecords,80);
  function addGameRecords(){ var h=RH().replace(/^#\\//,''); if(!/^game\\/w\\d+-\\d+-\\d+$/.test(h)) return;
    var pg=document.querySelector('.pg[data-p="'+h+'"]'); if(!pg||pg._gr) return; pg._gr=1;
    var x=gameRecords(pg); if(!x) return; var f=pg.querySelector('footer'), box=document.createElement('div'); box.innerHTML=x;
    var sec=box.firstChild; if(f&&f.parentNode) f.parentNode.insertBefore(sec,f); else pg.appendChild(sec); }
  window.addEventListener('hashchange',function(){ setTimeout(addGameRecords,30); }); setTimeout(addGameRecords,80);
  function heldRecords(id,d,yr){
    var pg=document.querySelector('.pg[data-p="records"]'); if(!pg) return '';
    var D=recData(pg).L, X=D.all==='='?D[Object.keys(D).filter(function(k){return k!=='all';})[0]]:D.all;
    var one=D.all==='=', rows=[], PO={'Single game':0,'Season':1,'Career':2}, n=0;
    BOOK.player.forEach(function(g){ if((one||yr)&&g[0]==='Career') return; g[1].forEach(function(c){ n++;
      [['ALL'],[d.p]].some(function(pp){ var L=X[c[0]+'_'+pp[0]]; if(!L||!L.length) return false;
        var lead=L.filter(function(e){return tv(e)===tv(L[0]);}), mine=lead.filter(function(e){return e[2]===id&&(!yr||String(e[5])===String(yr));})[0]; if(!mine) return false;   // same tie rule as the Record Book, from its own data
        var when=g[0]==='Single game'?'Week '+mine[4]+', '+mine[5]:(g[0]==='Season'?mine[5]+' season':'Career');
        rows.push({lg:pp[0]==='ALL', po:PO[g[0]], n:n, tie:lead.length>1, h:'<a class="hrr" href="#/records/player/'+c[0]+'_'+pp[0]+'"><span class="hrn"><b>'+esc(pp[0]==='ALL'?c[1]:c[1].replace('the #1 at his position','the #1 '+d.p))+'</b><small>'+when+(lead.length>1?'<i class="hrtie">Shared</i>':'')+'</small></span><span class="hrv">'+esc(mine[0])+'</span></a>'}); return true; }); }); });
    if(!rows.length) return '';
    rows.sort(function(a,b){ return (b.lg-a.lg)||(a.po-b.po)||(a.n-b.n); });
    var nL=rows.filter(function(r){return r.lg;}).length, nP=rows.length-nL;
    var strip='<div class="hrstrip"><div><b>'+rows.length+'</b><span>Total</span></div><div><b>'+nL+'</b><span>League records</span></div><div><b>'+nP+'</b><span>'+esc(d.p)+' records</span></div></div>';
    var grp=function(lg,lab){ var L=rows.filter(function(r){return r.lg===lg;}); return L.length?'<h3 class="hrgh">'+lab+'</h3><div class="hrl">'+L.map(function(r){return r.h;}).join('')+'</div>':''; };
    return '<section class="hrsec"><h2>Records held</h2>'+strip+grp(true,'League records')+grp(false,esc(d.p)+' records')+'</section>';
  }
  // NFL colors for the jersey badge: [jersey, number, trim]
  var JCOL={ARI:['#97233F','#FFFFFF','#FFFFFF','#000000'],ATL:['#A71930','#FFFFFF','#000000'],BAL:['#241773','#FFFFFF','#9E7C0C'],BUF:['#00338D','#FFFFFF','#C60C30'],CAR:['#0085CA','#FFFFFF','#101820'],
    CHI:['#0B162A','#FFFFFF','#C83803'],CIN:['#FB4F14','#FFFFFF','#000000','#000000'],CLE:['#311D00','#FFFFFF','#FF3C00','#FF3C00'],DAL:['#041E42','#FFFFFF','#869397'],DEN:['#FB4F14','#FFFFFF','#002244'],
    DET:['#0076B6','#FFFFFF','#B0B7BC'],GB:['#203731','#FFFFFF','#FFB612','#FFB612'],HOU:['#03202F','#FFFFFF','#A71930'],IND:['#0E4C96','#FFFFFF','#FFFFFF','#000000'],JAX:['#006778','#FFFFFF','#D7A22A','#000000'],
    KC:['#E31837','#FFFFFF','#FFB81C'],LV:['#000000','#FFFFFF','#A5ACAF'],LAC:['#0080C6','#FFFFFF','#FFC20E'],LAR:['#003594','#FFD100','#FFD100','#FFFFFF'],MIA:['#008E97','#FFFFFF','#FC4C02'],
    MIN:['#4F2683','#FFFFFF','#FFC62F','#FFC62F'],NE:['#002244','#FFFFFF','#C60C30'],NO:['#101820','#D3BC8D','#D3BC8D','#FFFFFF'],NYG:['#0B2265','#FFFFFF','#A71930'],NYJ:['#125740','#FFFFFF','#000000'],
    PHI:['#004C54','#FFFFFF','#FFFFFF','#000000'],PIT:['#101820','#FFFFFF','#FFB612','#FFB612'],SF:['#AA0000','#FFFFFF','#B3995D'],SEA:['#002244','#A5ACAF','#69BE28'],TB:['#D50A0A','#FFFFFF','#34302B'],
    TEN:['#4B92DB','#FFFFFF','#FFFFFF','#C8102E'],WAS:['#5A1414','#FFFFFF','#FFB612','#FFB612']};
  var NLA=(function(){ var m=/\/\*NLA:([^*]*)\*\//.exec(document.head.innerHTML)||/\/\*NLA:([^*]*)\*\//.exec(document.documentElement.innerHTML.slice(0,4e6)); return m&&m[1]?m[1].split(','):[]; })();      // seasons whose logo was archived and later changed
  var JCOLY={'2026':JCOL};      // team colors frozen by season; add a new season's map when a team changes its look
  function renderPlayer(id, yr){
    var d=PD[id], el=document.getElementById('pv'); if(!d){ el.innerHTML='<section class="field pagehead"><div class="wrap"><h1>Not found</h1></div></section>'; return; }
    var yrs=Object.keys(d.sea).sort().reverse(); if(yr&&!d.sea[yr]) yr=null;
    var cur=d.o? '<div class="sub">'+(d.ir?'Current team (IR): ':'Current team: ')+'<a href="#/team/'+TM[d.o][1]+'/'+YR+'" style="color:#fff;font-weight:700" class="curt"><i class="im lgc L'+d.o+'"></i>'+esc(TM[d.o][0])+'</a> ('+esc(TM[d.o][1])+')</div>' : '<div class="sub">Current team: Free agent'+((d.sea&&Object.keys(d.sea).some(function(y){ return (d.sea[y].w||[]).some(function(x){ return x[1]; }); }))?'':', never rostered')+'</div>';
    var by_=yr&&d.sea[yr]&&d.sea[yr].bd?d.sea[yr].bd:[d.t,d.no], bt=by_[0], bno=by_[1];       // a season page shows the badge as it was that season
    var JC=((JCOLY[yr||YR]||JCOL)[bt])||JCOL[bt]||['#2B3A55','#FFFFFF','#E2AE2A'], isd=d.p==='DEF'&&BY[bt]!==undefined;
    var jo=JC[3]?JC[3]:JC[2].toLowerCase()===JC[1].toLowerCase()?(JC[1].toLowerCase()==='#ffffff'?'#000000':'rgba(0,0,0,.55)'):JC[2];
    var badge='<div class="jers" style="--jb:'+JC[0]+';--jn:'+JC[1]+';--ja:'+JC[2]+';--jo:'+jo+'" aria-hidden="true">'+(isd?'<i class="nfl nflh N'+bt+'"></i>':'<b'+(String(bno||d.p).length>2?' class="sm"':'')+'>'+esc(bno!==''&&bno!=null?bno:d.p)+'</b>'+(BY[bt]!==undefined?'<i class="nfl nflj N'+bt+(yr&&NLA.indexOf(yr+bt)>=0?'_'+yr:'')+'"></i>':''))+'</div>';
    var h='<section class="field"><div class="wrap"><a class="back" href="#/players">All players</a><div class="hero">'+badge+'<div><h1>'+esc(d.n)+'</h1><div class="sub">'+esc(d.pd||d.p)+(d.t?', '+(BY[d.t]!==undefined?'<a href="#/nfl/'+d.t+'" style="color:#fff">'+esc(NFLN[d.t]||d.t)+'</a>':esc(d.t)):'')+ij(d.j)+'</div>'+cur+'</div></div>';
    // totals for the hero: one season, or the whole career
    var T=[0,0,0,0,0], nmv=0, teams=[], per={}, WW=0, LL=0;
    yrs.forEach(function(y){ var S=d.sea[y], st=S.s; if(yr&&y!==yr) return;
      T[0]+=st[0]; T[1]+=st[1]; T[2]+=st[2]; T[3]+=st[3]; T[4]+=st[4]; nmv+=st[6];
      S.w.forEach(function(x){ if(x[2]&&x[6]!==null&&x[6]!==undefined){ if(x[6]) WW++; else LL++; } });
      S.w.forEach(function(x){ if(!x[1]) return; var k=x[1]; if(!per[k]){per[k]={wk:0,st:0,pts:0,yrs:{}}; teams.push(k);} per[k].wk++; per[k].yrs[y]=1; if(x[2]){per[k].st++; per[k].pts+=x[3]||0;} }); });
    var rl='#/players/'+d.p+'/pts/'+id;
    var ord=function(n){ var s=['th','st','nd','rd'], v=n%100; return n+(s[(v-20)%10]||s[v]||s[0]); };
    var yrl=function(ex){ return ex===0?'Rookie':ord(ex+1)+' year'; };
    var off_=0, ag_=d.ag!=null?d.ag-off_:null, ex_=d.ex!=null?d.ex-off_:null, rkp=prank(id,yr||null), rko=prank(id,yr||null,1), rlk='#/players/'+d.p+'/pts/'+id;
    var hs=(ag_!=null?'<span><b>'+ag_+'</b>age</span>':'')+(ex_!=null&&ex_>=0?'<span><b>'+(ex_===0?'R':(ex_+1))+'</b>NFL year</span>':'')
      +(function(){ var pp=prank(id,yr||null,0,1), po=prank(id,yr||null,1,1), wp=prank(id,yr||null,0,3), wo=prank(id,yr||null,1,3);    // points started and WAR, at his position and overall
        var c=function(v,lab,href){ return v?'<a class="hrank" href="'+href+'"><b>'+v+'</b>'+lab+'</a>':''; };
        return c(wp,'WAR','#/players/'+d.p+'/war/'+id)+c(wo?'#'+wo:0,'WAR overall','#/players/All/war/'+id)+c(pp,'points','#/players/'+d.p+'/pts/'+id)+c(po?'#'+po:0,'points overall','#/players/All/pts/'+id); })();
    h+='<div class="herostats">'+hs+'</div></div></section>';
    h+='<nav class="subnav" aria-label="Seasons"><div class="wrap"><a href="#/player/'+id+'"'+(yr?'':' aria-current="page"')+'>Career</a>'+yrs.map(function(y){return '<a href="#/player/'+id+'/'+y+'"'+(y===yr?' aria-current="page"':'')+'>'+y+'</a>';}).join('')+'</div></nav>';
    h+='<main class="wrap">';
    // ---- overview: the same card for a season or the whole career, so the top of the page reads the same way
    (function(){
      var Y=yr||null, off=Y?(+YR-(+Y)):0, rp=prank(id,Y), ro=prank(id,Y,1), ns={}, dr=null, fy=yrs[yrs.length-1];
      yrs.forEach(function(y){ if(Y&&y!==Y) return; (d.sea[y].nt||[]).forEach(function(t){ ns[t]=1; }); });
      if(d.sea[Y||fy]&&d.sea[Y||fy].d) dr=d.sea[Y||fy].d;
      var row=function(k,v){ return '<div class="ovr"><span class="k">'+k+'</span><span class="v">'+v+'</span></div>'; };
      var slt=teams.map(function(r){ var x=per[r]; return tnm(r)+' <small class="muted">'+x.wk+' wk'+(x.wk===1?'':'s')+(x.st?', '+x.st+' start'+(x.st===1?'':'s')+', '+fpt(x.pts)+' pts':'')+'</small>'; }).join('<br>')||'<span class="muted">Never rostered</span>';
      var ag=d.ag!=null?d.ag-off:null, ex=d.ex!=null?d.ex-off:null;
      var meta=(Y?'<span><small>Draft</small>'+(dr?dr[0]+'.'+(dr[1]<10?'0':'')+dr[1]+', '+tnm(dr[2]):'Undrafted')+'</span>':'');
      var tile=function(k,v,c){ return '<div class="stat"><span class="k">'+k+'</span><span class="v'+(c?' '+c:'')+'">'+v+'</span></div>'; };
      var tiles=tile('Rostered',teams.reduce(function(a,r){return a+per[r].wk;},0)+'<small> wks</small>')+tile('Starts',T[0])+tile('Record',WW+LL?WW+'-'+LL:'-')+tile('Points',fpt(T[1]))+tile('PPG',T[0]?fpt(T[1]/T[0]):'-')
        +tile('WAR',sgn(T[3].toFixed(2)),T[3]>0?'pos':T[3]<0?'neg':'')+tile('PAA',sgn(T[4].toFixed(1)),T[4]>0?'pos':T[4]<0?'neg':'')+tile('Weekly MVPs',nmv);
      var SP=[0,0,0,0,0,0]; yrs.forEach(function(y){ if(Y&&y!==Y) return; var s_=d.sea[y].s; SP[0]+=s_[7]||0; SP[1]+=s_[1]||0; SP[2]+=s_[8]||0; SP[3]+=s_[9]||0; SP[4]+=s_[10]||0; SP[5]+=s_[11]||0; });
      var spl='';
      if(SP[0]>0){ var oth=Math.max(0,SP[0]-SP[1]-SP[2]-SP[3]), seg=function(v,c,l){ return v>0.05?'<i class="'+c+'" style="flex:'+v.toFixed(2)+'" title="'+l+' '+fpt(v)+'"></i>':''; };
        spl='<div class="psplit"><div class="psh"><span><b>'+fpt(SP[0])+'</b> total pts</span>'+(SP[4]>0.05?'<span class="plob">'+fpt(SP[4])+' left on the bench<small>, should have started '+SP[5]+' time'+(SP[5]===1?'':'s')+'</small></span>':'')+'</div>'
          +'<div class="pbar">'+seg(SP[1],'zs','Started')+seg(SP[2],'zn','Bench')+seg(SP[3],'zf','Free agent')+seg(oth,'zi','IR')+'</div>'
          +'<div class="pkey"><span class="zk zs">Started '+fpt(SP[1])+'</span><span class="zk zn">Bench '+fpt(SP[2])+'</span><span class="zk zf">Free agent '+fpt(SP[3])+'</span>'+(oth>0.05?'<span class="zk zi">IR '+fpt(oth)+'</span>':'')+'</div></div>'; }
      h+='<section><h2>'+(Y?Y+' at a glance':'Career at a glance')+'</h2><div class="ovm">'+(Y?meta:'')+'</div><div class="stats ovs">'+tiles+'</div>'+spl+'</section>';
      if(!Y) h+=stintsHTML(d,yrs,id,1);       // a season page already has its game log; the table lives on Career
      if(!Y) h+=heldRecords(id,d);
    })();
    if(!yr){
      // ---- career
      h+=mvpsHTML(d,yrs);
      if((d.ns||[]).length) h+='<section><h2>Stories</h2><div class="ngrid">'+d.ns.map(function(n){ return '<a class="ncard" href="#/news/'+n[1]+'"><span class="kick">'+esc(n[3])+', Week '+n[2]+'</span><b>'+esc(n[0])+'</b></a>'; }).join('')+'</div></section>';
    } else {
      // ---- one season
      var S=d.sea[yr];
      // the draft lives in the Moves timeline now
      var mx=Math.max.apply(null,S.w.map(function(x){return x[3]||0;}).concat([10]))*1.12, Wd=640, Hd=170, bw=Wd/S.w.length, bars='';
      var bye=function(x){ return x[7]===1; };     // his NFL team that week was on bye (not just his current team)
      S.w.forEach(function(x,k){ var v=Math.max(0,x[3]||0), hh=v/mx*(Hd-30), X=k*bw+bw*.18, col=x[2]?'var(--turf)':(x[1]?'#9AA3B5':'#D3DACF');
        if(!bye(x)&&x[13]===0){ bars+='<rect x="'+(X-2).toFixed(1)+'" y="'+(Hd-36)+'" width="'+(bw*.64+4).toFixed(1)+'" height="16" rx="3" fill="#F3E8E6"/><text x="'+(X+bw*.32).toFixed(1)+'" y="'+(Hd-24.5)+'" text-anchor="middle" font-size="10" font-weight="700" fill="#9A3A2E">DNP</text><text x="'+(X+bw*.32).toFixed(1)+'" y="'+(Hd-5)+'" text-anchor="middle" font-size="11" fill="var(--mute)">W'+x[0]+'</text>'; return; }
        if(bye(x)){ bars+='<rect x="'+(X-2).toFixed(1)+'" y="'+(Hd-36)+'" width="'+(bw*.64+4).toFixed(1)+'" height="16" rx="3" fill="#E3E9F5"/><text x="'+(X+bw*.32).toFixed(1)+'" y="'+(Hd-24.5)+'" text-anchor="middle" font-size="10" font-weight="700" fill="var(--turf)">BYE</text><text x="'+(X+bw*.32).toFixed(1)+'" y="'+(Hd-5)+'" text-anchor="middle" font-size="11" fill="var(--mute)">W'+x[0]+'</text>'; return; }
        bars+='<rect x="'+X.toFixed(1)+'" y="'+(Hd-20-hh).toFixed(1)+'" width="'+(bw*.64).toFixed(1)+'" height="'+hh.toFixed(1)+'" rx="3" fill="'+col+'"><title>Week '+x[0]+': '+fch(x[3])+'</title></rect>';
        bars+='<text x="'+(X+bw*.32).toFixed(1)+'" y="'+(Hd-5)+'" text-anchor="middle" font-size="11" fill="var(--mute)">W'+x[0]+'</text>';
        if(x[3]!==null) bars+='<text x="'+(X+bw*.32).toFixed(1)+'" y="'+(Hd-24-hh).toFixed(1)+'" text-anchor="middle" font-size="10" fill="var(--mute)">'+fch(x[3])+'</text>'; });
      h+='<section><h2>Week by week</h2><div class="panel"><svg viewBox="0 0 '+Wd+' '+Hd+'" width="100%" role="img" aria-label="Points by week">'+bars+'</svg><div class="zkey" style="margin-top:6px"><span class="zk zs">Started</span><span class="zk zn">Bench</span><span class="zk zf">Not rostered</span></div></div>';
      h+='</section><section><h2>Game log</h2><div class="scroll"><table class="glog"><thead><tr><th class="c">Wk</th><th>Team</th><th class="c"><span class="lgl">Result</span><span class="sml">W/L</span></th><th><span class="lgl">Opponent</span><span class="sml">Opp</span></th><th class="c">Status</th><th class="c grk"><span class="tip" tabindex="0" data-tip="Top: where his points ranked among every NFL player at his position that week. Below: where he ranked among Super League starters at his position (1 of 24 = best of 24 started).">Rank</span></th><th class="r">Pts</th><th class="r">PAA</th><th class="r">WAR</th><th class="gst">Stats</th></tr></thead><tbody>';
      var rkc=function(x){ if(!x[11]) return '<span class="muted">-</span>'; var tr=String(x[11]), tie=tr.indexOf('T-')===0, n=+tr.replace('T-',''), c=n<=5?'rk1':(n<=12?'rk2':(n<=24?'rk3':'rk4'));
        return '<span class="rkp '+c+'">'+(tie?'T-':'')+d.p+n+'</span>'+(x[12]?'<small class="rks">('+x[12][0]+' of '+x[12][1]+')</small>':''); };
      var sg=function(v,dp){ return v==null?'<td class="r muted">-</td>':'<td class="r '+(v>0.005?'pos':(v<-0.005?'neg':'muted'))+'">'+(v>=0?'+':'')+v.toFixed(dp)+'</td>'; };
      S.w.slice().reverse().forEach(function(x){ var dead=x[2]&&x[13]===0&&!bye(x);     // started, then never took a snap: a dead start
        var stt=x[2]?'<b class="pos">Started</b>':((S.irw||[]).indexOf(x[0])>=0?'IR':(x[1]?'Bench':'<span class="muted">Not rostered</span>'));
        if(x[14]&&!bye(x)) stt+=' <span class="stg inj" title="Injury tag going into the game">'+esc(x[14])+'</span>';
        if(x[8]) stt+=' <span class="stg '+(x[8]===2?'fin':'pk')+'">'+(x[8]===2?'Final':'Live')+'</span>';
        h+='<tr class="'+(x[2]?'':'bn')+'"><td class="c">'+(x[1]&&x[4]?glink(x[0],x[1],x[4],x[0]):x[0])+'</td><td>'+(x[1]?tlink(x[1],x[0]):'<span class="muted">-</span>')+'</td><td class="c">'+(x[6]===1?'<b class="pos">W</b>':x[6]===0?'<b class="neg">L</b>':(x[8]?'<span class="muted">Live</span>':''))+'</td>'
          +'<td>'+(x[4]?tlink(x[4],x[0]):'')+'</td><td class="c">'+stt+(x[11]?'<small class="grs">'+rkc(x)+'</small>':'')+'</td>'
          +'<td class="c grk">'+rkc(x)+'</td><td class="r big">'+(bye(x)?'<span class="byec">BYE</span>':(x[13]===0?'<span class="byec dnp" title="Did not play, 0 points">DNP</span>':fpt(x[3])))+(x[5]?'<small class="gsm">'+esc(x[5])+'</small>':'')+'</td>'+sg(x[10],1)+sg(x[9],2)+'<td class="muted gst">'+esc(x[5]||'')+'</td></tr>'; });
      h+='</tbody></table></div></section>';
      h+=mvpsHTML(d,[yr]);
      h+=movesHTML(d,[yr]);
      h+=heldRecords(id,d,yr);
      if((d.ns||[]).length) h+='<section><h2>Stories</h2><div class="ngrid">'+d.ns.map(function(n){ return '<a class="ncard" href="#/news/'+n[1]+'"><span class="kick">'+esc(n[3])+', Week '+n[2]+'</span><b>'+esc(n[0])+'</b></a>'; }).join('')+'</div></section>';
    }
    h+='</main><footer><div class="wrap">Super League '+YR+'.</div></footer>';
    el.innerHTML=h; document.querySelector('.pg[data-p="player"]').setAttribute('data-t', d.n+(yr?' '+yr:'')+', Super League');
  }
  function pfilter(sec){
    var q=(sec.querySelector('.psearch').value||'').toLowerCase().trim(), pf=sec.querySelector('.pf.nx'), pos=pf?pf.getAttribute('data-pos'):'All', own=sec.querySelector('.pown').value;
    [].forEach.call(sec.querySelectorAll('.ptable tbody tr'),function(r){
      r.hidden=!!((q&&r.getAttribute('data-q').indexOf(q)<0)||(pos!=='All'&&r.getAttribute('data-pos')!==pos)||(own!=='all'&&r.getAttribute('data-own')!==own)); });
    prk_(sec.querySelector('.ptable'));
  }
  // rank labels for the rows showing: same value in the sorted column = same number (1, 2, 2, 4); NA rows get none
  var PN=25;      // Players table shows 25 at a time
  function prk_(tbl,keep){ if(!tbl) return; if(!keep) PN=25; var th=tbl.querySelector('th[aria-sort]'), k=th?+th.getAttribute('data-k'):-1, n=0, last=null, cur=0, vis=0;
    [].forEach.call(tbl.tBodies[0].rows,function(r){ r.classList.remove('pcutx'); if(r.hidden) return; vis++; if(vis>PN) r.classList.add('pcutx');
      if(r.classList.contains('nark')){ r.cells[0].setAttribute('data-rk','NA'); return; }
      n++; var v=k>=0?r.cells[k].getAttribute('data-v'):n; if(v!==last){ cur=n; last=v; } r.cells[0].setAttribute('data-rk',cur); });
    var box=tbl.closest('.scroll'), mb=box.nextElementSibling; if(!mb||!mb.classList.contains('txmore')){ mb=document.createElement('div'); mb.className='txmore'; box.parentNode.insertBefore(mb,box.nextSibling); }
    mb.innerHTML=vis>PN?'<span>Showing '+PN+' of '+vis+'</span><button type="button" class="pmb">Show 25 more</button><button type="button" class="pma">Show all</button>':(vis>25?'<span>All '+vis+' shown</span><button type="button" class="pmc">Show fewer</button>':''); }
  document.addEventListener('click',function(e){ var x=e.target.closest&&e.target.closest('.pmb,.pma,.pmc'); if(!x) return; var tbl=(x.closest('section')||x.closest('.pg')).querySelector('.ptable'); if(!tbl) return;
    if(x.classList.contains('pmb')) PN+=25; else if(x.classList.contains('pma')) PN=1e9; else { PN=25; tbl.scrollIntoView({block:'start'}); } prk_(tbl,1); });
  // long lists stop early with a "See all" button: stories, award races, every-game lists, the redraft
  var CLIP=[['.ngrid',6],['.pg[data-p="races"] table tbody',5],['.pg[data-p="excitement"] section:last-of-type tbody',10],['table.rdraft tbody',15],['.pg[data-p="races"] .aw ol',5],['.gweeks',2]];
  function clipAll(){ CLIP.forEach(function(c){ [].forEach.call(document.querySelectorAll(c[0]),function(el){ if(el.hasAttribute('data-clip')||!el.offsetParent&&el.tagName!=='TBODY') return;
      var it=[].filter.call(el.children,function(x){return !x.hidden;}); if(it.length<=c[1]+2) return; el.setAttribute('data-clip',c[1]);
      it.forEach(function(x,k){ if(k>=c[1]) x.classList.add('clipx'); });
      var b=document.createElement('button'); b.type='button'; b.className='clipbtn'; b.textContent='See all '+it.length; b._n=it.length;
      var at=el.tagName==='TBODY'?(el.closest('.scroll')||el.closest('table')):el; at.parentNode.insertBefore(b,at.nextSibling); b._el=el; }); }); }
  document.addEventListener('click',function(e){ var b=e.target.closest&&e.target.closest('.clipbtn'); if(!b) return; var el=b._el, open=b.getAttribute('data-open')==='1', n=+el.getAttribute('data-clip');
    [].forEach.call(el.children,function(x,k){ if(!x.hidden) x.classList.toggle('clipx',open&&k>=n); }); b.setAttribute('data-open',open?'0':'1'); b.textContent=open?'See all '+b._n:'Show fewer'; });
  window.addEventListener('hashchange',function(){ setTimeout(clipAll,40); }); setTimeout(clipAll,60);
  document.addEventListener('click',function(e){ var b=e.target.closest&&e.target.closest('.posrt button'); if(!b) return; var s=b.closest('section'), P=b.getAttribute('data-p');
    [].forEach.call(b.parentNode.children,function(x){ x.setAttribute('aria-pressed',x===b?'true':'false'); }); [].forEach.call(s.querySelectorAll('.posrv'),function(v){ v.hidden=v.getAttribute('data-p')!==P; }); });
  document.addEventListener('input',function(e){ if(e.target.classList&&e.target.classList.contains('psearch')) pfilter(e.target.closest('section')); });
  document.addEventListener('change',function(e){ if(e.target.classList&&e.target.classList.contains('pown')) pfilter(e.target.closest('section')); });
  function psort(th){
    var tb=th.closest('table').tBodies[0], k=+th.getAttribute('data-k'), num=th.getAttribute('data-t')==='n';
    var cur=th.getAttribute('aria-sort'), dir=cur==='descending'?1:cur==='ascending'?-1:(num?-1:1);
    [].forEach.call(th.parentNode.children,function(x){x.removeAttribute('aria-sort');}); th.setAttribute('aria-sort',dir<0?'descending':'ascending');
    var rows=[].slice.call(tb.rows); rows.sort(function(a,b){ var na=a.cells[k].hasAttribute('data-na'), nb=b.cells[k].hasAttribute('data-na');
      if(na!==nb) return na?1:-1;            // no starts = no rating: always below everyone who has one
      var x=a.cells[k].getAttribute('data-v'), y=b.cells[k].getAttribute('data-v');
      if(num){x=parseFloat(x);y=parseFloat(y);} return (x<y?-1:x>y?1:0)*dir; }); rows.forEach(function(r){tb.appendChild(r);});
    pnark(th.closest('table'),k,num); prk_(th.closest('table'));
  }
  // players with nothing in the sorted column (no value, or 0 of a counting stat) get "NA" instead of a rank, under everyone ranked
  function pnark(tbl,k,num){ [].forEach.call(tbl.tBodies[0].rows,function(r){ var c=r.cells[k], v=c.getAttribute('data-v');
      var na=c.hasAttribute('data-na')||(num&&parseFloat(v)===0); r.classList.toggle('nark',!!na); });
    if(!num) return; var tb=tbl.tBodies[0], na=[].filter.call(tb.rows,function(r){return r.classList.contains('nark');}); na.forEach(function(r){tb.appendChild(r);}); }
  (function(){ var t=document.querySelector('.ptable'), th=t&&t.querySelector('th[aria-sort]'); if(th) pnark(t,+th.getAttribute('data-k'),th.getAttribute('data-t')==='n'); prk_(t); })();
  document.addEventListener('click',function(e){
    var f=e.target.closest&&e.target.closest('.pf'); if(f){ e.preventDefault(); [].forEach.call(f.parentNode.querySelectorAll('.pf'),function(x){x.classList.toggle('nx',x===f);}); pfilter(f.closest('section')); return; }
    var th=e.target.closest&&e.target.closest('.ptable th.sortable'); if(th) psort(th);
  });
  document.addEventListener('keydown',function(e){ var th=e.target.closest&&e.target.closest('.ptable th.sortable'); if(th&&(e.key==='Enter'||e.key===' ')){ e.preventDefault(); psort(th); } });
  var tipEl=document.createElement('div'); tipEl.className='tipbox'; tipEl.hidden=true; document.body.appendChild(tipEl);
  function showTip(t,pin){ tipEl.textContent=t.getAttribute('data-tip'); if(pin){ tipEl.insertAdjacentHTML('beforeend','<button type="button" class="cx" aria-label="Close">&times;</button>'); } tipEl.classList.toggle('pin',!!pin); tipEl.hidden=false; var r=t.getBoundingClientRect(), w=Math.min(260,window.innerWidth-24);
    tipEl.style.width=w+'px'; tipEl.style.left=Math.max(12,Math.min(window.innerWidth-w-12,r.left+r.width/2-w/2))+'px';
    var inHead=!!t.closest('thead'), top=inHead?r.top-tipEl.offsetHeight-8:r.bottom+8; if(inHead&&top<8) top=r.bottom+8; if(!inHead&&top+tipEl.offsetHeight>window.innerHeight-8) top=r.top-tipEl.offsetHeight-8; tipEl.style.top=top+'px'; }
  document.addEventListener('mouseover',function(e){ var t=e.target.closest&&e.target.closest('.tip'); if(t) showTip(t); });
  document.addEventListener('mouseout',function(e){ var t=e.target.closest&&e.target.closest('.tip'); if(t&&!tipEl.classList.contains('pin')) tipEl.hidden=true; });
  document.addEventListener('click',function(e){ var t=e.target.closest&&e.target.closest('.tip'); if(t&&t.closest('th.sortable,th.srt')){ tipEl.hidden=true; return; } if(t){ showTip(t,1); } else if(!(e.target.closest&&e.target.closest('.tipbox')&&!e.target.closest('.cx'))) tipEl.hidden=true; },true);
  window.addEventListener('scroll',function(){tipEl.hidden=true;},{passive:true}); window.addEventListener('hashchange',function(){tipEl.hidden=true;});
  var BOOK={team:[['Single game',[['g_high','Highest score'],['g_low','Lowest score'],['g_blow','Biggest blowout'],['g_close','Closest game'],['g_comb','Most combined points'],['g_hiloss','Highest score in a loss'],['g_lowin','Lowest score in a win'],['g_upset','Biggest upset'],['g_excite','Most exciting game'],['g_flips','Most lead changes'],['g_dull','Least exciting game'],['g_bench','Most points lost to start/sit']]],
      ['Single play',[['t_ppts','Most points'],['t_wpa','Most win probability added'],['t_cpa','Most championship probability added']]],['Biggest comebacks',[['g_improb','Lowest win chance overcome'],['g_down','Biggest deficit overcome'],['g_choke','Highest win chance lost'],['g_blown','Biggest lead blown']]],
      ['Season',[['s_pct','Best record'],['s_pctlo','Worst record'],['s_wins','Most wins'],['s_pf','Most points'],['s_pflow','Fewest points'],['s_pa','Most points against'],['s_xw','Most xWins'],['s_lucky','Luckiest'],['s_unlucky','Unluckiest'],['s_wstreak','Longest win streak'],['s_lstreak','Longest losing streak']],1]],
    player:[['Single game',[['p_start','Most points'],['p_startlo','Fewest points'],['p_pm','Best PAA'],['p_pmlo','Worst PAA'],['p_war1','Most WAR'],['p_war1lo','Fewest WAR'],['p_bench','Most bench points']]],
      ['Single play',[['p_ppts','Most points'],['p_wpa','Most win probability added'],['p_cpa','Most championship probability added']]],
      ['Season',[['py_pts','Most points'],['py_ppg','Most points per game'],['py_ptslo','Fewest points'],['py_ppglo','Fewest points per game'],['py_pm','Best PAA'],['py_pmlo','Worst PAA'],['py_war','Most WAR'],['py_warlo','Fewest WAR'],['py_wpa','Most win probability added'],['py_wpalo','Least win probability added'],['py_wins','Most wins'],['py_loss','Most losses'],['py_wpct','Best win %'],['py_wpctlo','Worst win %'],['py_wi','Most Win Impact'],['py_wilo','Least Win Impact'],['py_luck','Best supporting cast'],['py_unluck','Worst supporting cast'],['py_gs','Most starts'],['py_top','Most weeks as the #1 at his position'],['py_ben','Most bench points'],['py_benppg','Most bench points per week']]],
      ['Career',[['pc_pts','Most points'],['pc_ppg','Most points per game'],['pc_ptslo','Fewest points'],['pc_ppglo','Fewest points per game'],['pc_pm','Best PAA'],['pc_pmlo','Worst PAA'],['pc_war','Most WAR'],['pc_warlo','Fewest WAR'],['pc_wins','Most wins'],['pc_loss','Most losses'],['pc_wpct','Best win %'],['pc_wpctlo','Worst win %'],['pc_wi','Most Win Impact'],['pc_wilo','Least Win Impact'],['pc_luck','Best supporting cast'],['pc_unluck','Worst supporting cast'],['pc_gs','Most starts'],['pc_top','Most weeks as the #1 at his position'],['pc_ben','Most bench points'],['pc_benppg','Most bench points per week']],0,1]],
    mgr:[['Single week or move',[['l_add1','Most gut-call wins added'],['m_besttrade','Most wins gained in a trade'],['m_heist','Most lopsided trade'],['m_pick','Best pickup'],['m_drop','Worst drop']]],
      ['Season',[['m_total','Most total wins added'],['l_add','Most gut-call wins added'],['m_gm','Best GM'],['m_eff','Most efficient GM'],['m_trader','Best trader'],['m_treff','Most efficient trader'],['m_waiver','Best waiver work'],['m_wveff','Most efficient waiver work'],['m_dropcost','Costliest drops'],['m_draft','Best draft'],['l_eff','Best lineup efficiency'],['l_bench','Most points lost to start/sit'],['l_over','Most points over projection'],['w_high','Most weekly high scores'],['w_low','Most weekly low scores'],['w_mvp','Most weekly MVPs'],['m_trades','Most trades'],['m_moves','Most waiver and free-agent moves'],['m_allmv','Most total moves']],1],
      ['All-time',[['f_pct','Best win %'],['c_m_total','Most total wins added'],['c_l_add','Most gut-call wins added'],['c_m_gm','Best GM'],['c_m_eff','Most efficient GM'],['c_m_trader','Best trader'],['c_m_treff','Most efficient trader'],['c_m_waiver','Best waiver work'],['c_m_wveff','Most efficient waiver work'],['c_m_dropcost','Costliest drops'],['c_m_draft','Best drafter'],['c_l_eff','Best lineup efficiency'],['c_l_bench','Most points lost to start/sit'],['c_l_over','Most points over projection'],['c_w_high','Most weekly high scores'],['c_w_low','Most weekly low scores'],['c_w_mvp','Most weekly MVPs'],['c_m_trades','Most trades'],['c_m_moves','Most waiver and free-agent moves'],['c_m_allmv','Most total moves']],1,1]]};
  var OVER={g_blow:1,g_close:1,g_comb:1,g_upset:1,g_improb:1,g_down:1,g_excite:1,g_dull:1,g_flips:1,m_heist:1}, RBOOK='team', RPOS='ALL';
  function toHash(u){ var m;
    if((m=/^game\\/(.+)\\.html$/.exec(u))) return '#/game/'+m[1];
    if((m=/^player\\/(.+)\\.html$/.exec(u))) return '#/player/'+m[1];
    if((m=/^team\\/([^.#]+)\\.html(?:#(.+))?$/.exec(u))) return '#/team/'+m[1]+(m[2]?'/'+m[2]:'');
    return '#/'+u.replace(/\\.html$/,''); }
  function recData(pg){ if(!pg._rd) pg._rd=JSON.parse(pg.querySelector('.rdata').textContent); return pg._rd; }
  var SYM={g_comb:1,g_close:1,g_flips:1}, RPER='all', RSC='L'; function tv(e){ return e.length>8?e[8]:e[0]; }
  // a season chip only where the record belongs to one season (a game, a season, a trade, a draft); never on all-time totals, and not inside a one-season view
  function yrOf(k){ return RPER==='all' && !/^(pc_|f_|c_)/.test(k); }
  function hold(k,e){ var r=e[1], p=e[2], o=e[3], d=p&&PD[p], tn=function(x){ var nm_=(e[5]==YR&&e[4])?tmAt(x,e[4])[0]:TM[x][0]; return RBOOK==='mgr'?TM[x][1]:nm_+' ('+TM[x][1]+')'; };          // manager records: just the manager
    var pair=!d&&OVER[k]&&o;
    var main = d ? (RPOS==='ALL'&&d.p&&d.p!=='DEF'?(d.pd||d.p).replace(', ','/')+' ':'')+d.n : (pair ? TM[r][1]+(SYM[k]?' vs ':' over ')+TM[o][1] : tn(r));
    var st=yrOf(k)&&/^\\d+ starts?$/.test(e[7]||'') ? e[7] : '';
    var det=[], ym=false;
    if(RSC!=='L'&&!d){          // one manager picked: his name is a given, so lead with when it happened and who it was against
      if(e[4]){ var me=String(r)===String(RSC), x7=e[7]||'', opp=pair?(me?o:r):o;
        main='Week '+e[4]+(opp?' vs '+TM[opp][1]:'');
        var sm=/^(won |lost |tied )?([\d.]+) to ([\d.]+)$/.exec(x7);
        if(sm){ var won=pair?me:(sm[1]==='won '), tie=sm[1]==='tied '||sm[2]===sm[3];      // the final, always from his side (in a pair the record's holder is the winner)
          x7=(pair&&!me)?sm[3]+' to '+sm[2]:sm[2]+' to '+sm[3];
          x7=(tie?'Tied ':won?'Won ':'Lost ')+x7; }
        if(x7) det.push(x7); }
      else { ym=yrOf(k)||RPER!=='all'; main=ym?String(e[5]):'All-time'; if(e[7]) det.push(e[7]); }
      return {main:main, short:main, sub:'', det:det.join(', '), pair:false, st:'', nfl:'', ym:ym, one:1}; }
    var rsl=(d&&e[10]&&e[10].length>1)?e[10]:null;
    if(d&&RSC==='L') det.push(rsl?(rsl.length>2?rsl.length+' teams':rsl.map(function(x){return tn(x);}).join(' / ')):tn(r)); if(e[4]) det.push('Week '+e[4]+(o&&!pair?' vs '+TM[o][1]:'')); if(e[7]&&!st&&!(e[4]&&/^(won |lost |tied )?[\d.]+ to [\d.]+$/.test(e[7]))) det.push(e[7]);     // whole league: the week and opponent are enough, no final score
    var nf=d&&e[9]&&e[9]!=='FA'?e[9]:'';
    var sh=main; if(d&&d.p!=='DEF'){ var nn=d.n.split(' '); if(nn.length>1) sh=main.replace(d.n, nn[0].charAt(0)+'. '+nn.slice(1).join(' ')); }
    return {main:main, short:sh, sub:'', det:det.join(', '), pair:pair, st:st, nfl:nf, rsl:(RSC==='L'?rsl:null)}; }
  function hname(h){ return h.short!==h.main?'<span class="nmf">'+esc(h.main)+'</span><span class="nms">'+esc(h.short)+'</span>':esc(h.main); }
  function nflc(h){ if(!h.nfl) return ''; var ts=String(h.nfl).split(',');
    if(ts.length>1) return '<span class="rnfl" title="'+esc(ts.join(', then '))+'">'+ts.map(function(x){ return '<i class="nfl N'+x+'" aria-hidden="true"></i>'; }).join('')+'</span>';
    return '<span class="rnfl">'+(BY[h.nfl]!==undefined?'<i class="nfl N'+h.nfl+'" aria-hidden="true"></i>':'')+esc(h.nfl)+'</span>'; }
  function ychip(k,e,h){ return yrOf(k)&&!h.ym?'<b>'+e[5]+'</b>'+(h.st?'<small>'+esc(h.st)+'</small>':''):''; }
  function rlogo(k,e,h){ if(h.one) return e[4]&&e[3]?'<i class="im rlg L'+(String(e[1])===String(RSC)?e[3]:e[1])+'"></i>':'<i class="im rlg L'+e[1]+'"></i>'; if(h.rsl) return '<span class="rlg2">'+h.rsl.slice(0,2).map(function(x){return '<i class="im L'+x+'"></i>';}).join('')+(h.rsl.length>2?'<b class="rlgn" title="'+h.rsl.length+' teams">+'+(h.rsl.length-2)+'</b>':'')+'</span>';
    return h.pair?'<span class="rlg2"><i class="im L'+e[1]+'"></i><i class="im L'+e[3]+'"></i></span>':'<i class="im rlg L'+e[1]+'"></i>'; }
  function rsm(h){ var dd=(h.det||'').split('\\n');
    return (h.sub?'<small>'+esc(h.sub)+'</small>':'')+(dd[0]?'<small>'+esc(dd[0])+'</small>':'')+(dd[1]?'<small class="rwho">'+dd[1].split(', ').map(function(x){ var m=/^(.*) (-?[\\d.]+)$/.exec(x); return m?'<span>'+esc(m[1])+' <b>'+esc(m[2])+'</b></span>':''; }).join('')+'</small>':''); }
  function rrow(k,t,e,tag){ var h=hold(k,e);
    return '<'+tag+' class="rrow"'+(tag==='button'?' type="button" data-k="'+k+'" data-t="'+esc(t)+'"':' href="'+toHash(e[6])+'"')+'><span class="rlab">'+esc(t)+(RHELP[rbase(k)]?'<small class="rhelp">'+esc(RHELP[rbase(k)])+'</small>':'')+'</span>'+rlogo(k,e,h)
      +'<span class="rhold"><b>'+hname(h)+'</b>'+nflc(h)+rsm(h)+'</span><span class="ryear">'+ychip(k,e,h)+'</span><span class="rval">'+esc(e[0])+(RUNIT[rbase(k)]?'<small class="runit">'+RUNIT[rbase(k)]+'</small>':'')+'</span></'+tag+'>'; }
  var RUNIT={g_excite:'excitement score',g_dull:'excitement score',g_flips:'lead changes',p_wpa:'win chance',p_cpa:'title odds',t_wpa:'win chance',t_cpa:'title odds',py_wpa:'wins',py_wpalo:'wins'};
  var RHELP={};
  function rbase(k){ return k.replace(/_(ALL|QB|RB|WR|TE|K|DEF)$/,''); }
  function trow(k,t,L){ var T=L.filter(function(e){return tv(e)===tv(L[0]);}), nT=T.length, more=''; T=T.slice(0,4);
    if(nT<2) return rrow(k,t,L[0],'button');
    var hs='', ys='';
    T.forEach(function(e){ var h=hold(k,e); hs+='<span class="rtie">'+rlogo(k,e,h)+'<span class="rhold"><b>'+hname(h)+'</b>'+nflc(h)+rsm(h)+'</span><span class="ryear">'+ychip(k,e,h)+'</span></span>'; });
    return '<button type="button" class="rrow rties" data-k="'+k+'" data-t="'+esc(t)+'"><span class="rlab">'+esc(t)+'</span><span class="rholds">'+hs+'<span class="tiepill">'+nT+more+'-way tie'+(nT>4?', tap for all':'')+'</span></span><span class="rval">'+esc(L[0][0])+'</span></button>'; }
  function renderRec(pg){
    var D=recData(pg), sc=pg.querySelector('.rscope').value, per=pg.querySelector('.rper [aria-pressed="true"]').getAttribute('data-v'); RPER=per; RSC=sc;
    var X=D[sc][per]; if(X==='=') X=D[sc][Object.keys(D[sc]).filter(function(k){return k!=='all';})[0]];
    var h=RBOOK==='player'?'<div class="chips rposc">'+['ALL','QB','RB','WR','TE','K','DEF'].map(function(p){return '<a href="#" class="rpos'+(p===RPOS?' nx':'')+'" data-p="'+p+'">'+(p==='ALL'?'All':p)+'</a>';}).join('')+'</div>':'';
    BOOK[RBOOK].forEach(function(g){ var rows='';
      if(g[3]&&per!=='all') return;
      g[1].forEach(function(c){ var k=c[0]+(RBOOK==='player'?'_'+RPOS:''), L=X[k];
        if(!L||!L.length){ if(sc!=='L'&&!/(^|_)m_(eff|treff|wveff)$/.test(c[0])) rows+='<div class="rrow rna"><span class="rlab">'+esc(c[1])+'</span><i class="rlg"></i><span class="rhold"><small>Not yet</small></span><span class="ryear"></span><span class="rval">N/A</span></div>'; return; }
        // one team picked: every category shows, even with one season (best and worst record are the same season for now)
        rows+=trow(k,RBOOK==='player'&&RPOS!=='ALL'?c[1].replace('the #1 at his position','the #1 '+RPOS):c[1],L); });
      var anyYr=g[1].some(function(c){ return yrOf(c[0]+(RBOOK==='player'?'_'+RPOS:'')); });
      if(rows) h+='<section class="rsec"><h2>'+g[0]+'</h2><div class="rcols"><span>Record</span><span>Holder</span><span>'+(anyYr?'Season':'')+'</span><span></span></div><div class="rlist">'+rows+'</div></section>'; });
    pg.querySelector('.rgroups').innerHTML=h||'<p class="muted">No records yet.</p>'; pg._x=X;
    var rb_=pg.querySelector('.rbar'); if(rb_) pg.style.setProperty('--rbh',(rb_.getBoundingClientRect().height-1)+'px');   // section titles stick just under the controls bar
  }
  var rm=document.createElement('div'); rm.className='pcard rmod'; rm.hidden=true; rm.innerHTML='<div class="in" role="dialog" aria-modal="true"></div>'; document.body.appendChild(rm);
  function openRec(pg,b){ var k=b.getAttribute('data-k'), L=pg._x[k], sc=pg.querySelector('.rscope'), per=pg.querySelector('.rper [aria-pressed="true"]').textContent;
    var h='<div class="rmh"><span class="rlab">'+esc(sc.options[sc.selectedIndex].text)+', '+esc(per)+'</span><b>'+esc(b.getAttribute('data-t'))+'</b></div><ol class="rtop">';
    L.forEach(function(e,i){ var first=L.findIndex(function(x){return tv(x)===tv(e);}), n=L.filter(function(x){return tv(x)===tv(e);}).length;
      h+='<li'+(first===0?' class="r1"':'')+'><span class="rk">'+(n>1?'T':'')+(first+1)+'</span>'+rrow(k,'',e,'a')+'</li>'; });
    rm.firstChild.innerHTML=h+'</ol><button type="button" class="x">Close</button>'; rm.hidden=false; rm.querySelector('.x').focus({preventScroll:true}); rm.firstChild.scrollTop=0; }
  document.addEventListener('click',function(e){
    if(!rm.hidden&&(e.target===rm||(e.target.closest&&e.target.closest('.rmod .x')))){rm.hidden=true;return;}
    var c=e.target.closest&&e.target.closest('button.rrow'); if(c){ openRec(c.closest('.pg'),c); return; }
    var p=e.target.closest&&e.target.closest('.rpos'); if(p){ e.preventDefault(); RPOS=p.getAttribute('data-p'); renderRec(p.closest('.pg')); return; }
    var bk=e.target.closest&&e.target.closest('.rbooks button'); if(bk){ RBOOK=bk.getAttribute('data-b'); [].forEach.call(bk.parentNode.children,function(x){x.setAttribute('aria-pressed',x===bk?'true':'false');});
      var pg=bk.closest('.pg'), bs=pg.querySelectorAll('.rper button'); bs[0].textContent=RBOOK==='player'?'Career':'All-time';
      renderRec(pg); return; }
    var t=e.target.closest&&e.target.closest('.rper button'); if(t){ [].forEach.call(t.parentNode.children,function(x){x.setAttribute('aria-pressed',x===t?'true':'false');}); renderRec(t.closest('.pg')); }
  });
  document.addEventListener('change',function(e){ if(e.target.classList&&e.target.classList.contains('rscope')) renderRec(e.target.closest('.pg')); });
  window.addEventListener('resize',function(){ var pg=document.querySelector('.pg[data-p="records"]'), rb_=pg&&pg.querySelector('.rbar'); if(rb_) pg.style.setProperty('--rbh',(rb_.getBoundingClientRect().height-1)+'px'); });
  // ---- compare two managers
  function cmpRender(sec){ var D=JSON.parse(sec.querySelector('.cmpdata').textContent), a=sec.querySelector('.cmpa').value, b=sec.querySelector('.cmpb').value, o=sec.querySelector('.cmpo');
    if(a===b){ o.innerHTML='<p class="note">Pick two different managers.</p>'; return; }
    var A=D.t[a], B=D.t[b], f2=function(v){ return (Math.round(v*100)%100===0)?String(Math.round(v)):v.toFixed(2).replace(/0$/,''); }, f1=function(v){return v.toFixed(1);};
    var G=D.g.filter(function(g){ return (g[1]==a&&g[2]==b)||(g[1]==b&&g[2]==a); }).map(function(g){ var sa=g[1]==a?g[3]:g[4], sb=g[1]==a?g[4]:g[3]; return {w:g[0],sa:sa,sb:sb,u:g[5],po:g[6]}; });
    var wa=0,wb=0,t=0,pa=0,pb=0,big=null; G.forEach(function(g){ pa+=g.sa; pb+=g.sb; if(g.sa>g.sb) wa++; else if(g.sb>g.sa) wb++; else t++; if(!big||Math.abs(g.sa-g.sb)>Math.abs(big.sa-big.sb)) big=g; });
    var rec=function(x){ return x.w+'-'+x.l+(x.ti?'-'+x.ti:''); }, wp=function(x){ return x.g?(x.w+x.ti/2)/x.g:0; };
    var row=function(lab,va,vb,ka,kb,lowgood){ var c=(ka===kb||ka===null)?'':((lowgood?ka<kb:ka>kb)?'a':'b'); return '<div class="crow"><span class="cv'+(c==='a'?' cw':'')+'">'+va+'</span><span class="cl">'+lab+'</span><span class="cv r'+(c==='b'?' cw':'')+'">'+vb+'</span></div>'; };
    var side=function(r,X,cls){ return '<a class="cside '+cls+'" href="'+X.u+'"><i class="im lgh L'+r+'"></i><b>'+esc(X.n)+'</b><small>'+esc(X.m)+'</small></a>'; };
    var h='<div class="chead">'+side(a,A,'a')+'<div class="cser"><b>'+wa+'<span>-</span>'+wb+'</b><small>'+(G.length?(t?t+(t===1?' tie, ':' ties, '):'')+G.length+' meeting'+(G.length===1?'':'s'):'never played')+'</small></div>'+side(b,B,'b')+'</div>';
    h+='<h3 class="csub">Against each other</h3>';
    if(G.length){ h+=row('Wins',wa,wb,wa,wb)+(t?row('Ties',t,t,null,null):'')+row('Total points',f2(pa),f2(pb),pa,pb)+row('Avg points',f1(pa/G.length),f1(pb/G.length),pa,pb);
      h+='<div class="cgames">'+G.slice().reverse().map(function(g){ var wn=g.sa>g.sb?'a':(g.sb>g.sa?'b':''); return '<a href="'+g.u+'"><span>Week '+g.w+(g.po?' (playoffs)':'')+'</span><b class="'+(wn==='a'?'pos':'')+'">'+f2(g.sa)+'</b><i>-</i><b class="'+(wn==='b'?'pos':'')+'">'+f2(g.sb)+'</b></a>'; }).join('')+'</div>'; }
    else h+='<p class="note">No games against each other yet.</p>';
    h+='<h3 class="csub">Against everyone</h3>'+row('Record',rec(A),rec(B),wp(A),wp(B))+row('Win %',(wp(A)*100).toFixed(1)+'%',(wp(B)*100).toFixed(1)+'%',wp(A),wp(B))
      +row('Points for',f2(A.pf),f2(B.pf),A.pf,B.pf)+row('Points against',f2(A.pa),f2(B.pa),A.pa,B.pa,1)+row('Avg points',f1(A.pf/A.g),f1(B.pf/B.g),A.pf/A.g,B.pf/B.g)
      +row('Highest score',f2(A.hi),f2(B.hi),A.hi,B.hi)+row('Lowest score',f2(A.lo),f2(B.lo),A.lo,B.lo)
      +row('Playoff trips',A.pa_,B.pa_,A.pa_,B.pa_)+row('Playoff record',A.pw+'-'+A.pl,B.pw+'-'+B.pl,A.pw,B.pw)+row('Titles',A.ch,B.ch,A.ch,B.ch)+row('Seasons',A.sz,B.sz,null,null);
    o.innerHTML=h; }
  document.querySelectorAll('.cmp').forEach(function(sec){ var b=sec.querySelector('.cmpb'); if(b.options.length>1) b.selectedIndex=1; cmpRender(sec); });
  document.addEventListener('change',function(e){ if(e.target.classList&&(e.target.classList.contains('cmpa')||e.target.classList.contains('cmpb'))) cmpRender(e.target.closest('.cmp')); });
  document.addEventListener('keydown',function(e){ if(e.key==='Escape') rm.hidden=true; });
  window.addEventListener('hashchange',function(){ rm.hidden=true; var pg=document.querySelector('.pg[data-p="records"]'); if(pg&&!pg.hidden&&!pg._done){pg._done=1; renderRec(pg);} });
  (function(){
    var PO=['QB','RB','WR','TE','K','DEF'];
    function draw(tb){
      var m=tb.getAttribute('data-m'), k=tb.getAttribute('data-k'), d=+tb.getAttribute('data-d'), body=tb.tBodies[0];
      var rows=[].slice.call(body.rows);
      rows.forEach(function(r){ var c=r.querySelector('.pc'); if(c) c.parentNode.removeChild(c); r.classList.remove('gtop'); });
      var val=function(r){ if(k==='pos') return PO.indexOf(r.getAttribute('data-pos')); var v=r.getAttribute('data-'+k); return (k==='n')?v:parseFloat(v); };
      var cmp=function(a,b){ var x=val(a), y=val(b); if(k==='n') return d*(x<y?-1:x>y?1:0); return d*(x-y) || (parseFloat(b.getAttribute('data-war'))-parseFloat(a.getAttribute('data-war'))); };
      var gd=(k==='pos')?d:1, wcmp=function(a,b){ return parseFloat(b.getAttribute('data-war'))-parseFloat(a.getAttribute('data-war')); };
      if(m==='pos') rows.sort(function(a,b){ return gd*(PO.indexOf(a.getAttribute('data-pos'))-PO.indexOf(b.getAttribute('data-pos'))) || (k==='pos'?wcmp(a,b):cmp(a,b)); });
      else rows.sort(cmp);
      rows.forEach(function(r,j){
        var p=r.getAttribute('data-pos');
        if(m==='pos'){
          if(j===0||rows[j-1].getAttribute('data-pos')!==p){ var n=rows.filter(function(x){return x.getAttribute('data-pos')===p;}).length;
            var th=document.createElement('th'); th.className='pgrp pc'; th.rowSpan=n; th.scope='rowgroup'; th.textContent=p; r.insertBefore(th,r.firstChild); r.classList.add('gtop'); }
        } else { var td=document.createElement('td'); td.className='pone pc'; td.textContent=p; r.insertBefore(td,r.firstChild); }
        body.appendChild(r); });
      [].forEach.call(tb.querySelectorAll('th.srt'),function(h){ h.setAttribute('aria-sort', h.getAttribute('data-k')===k ? (d<0?'descending':'ascending') : 'none'); });
    }
    function init(){ [].forEach.call(document.querySelectorAll('table.rost:not([data-i])'),function(tb){ tb.setAttribute('data-i','1'); draw(tb);
      var tog=tb.closest('.scroll').previousElementSibling;
      if(tog&&tog.classList.contains('rtog')) [].forEach.call(tog.querySelectorAll('button'),function(b){ b.addEventListener('click',function(){
        tb.setAttribute('data-m',b.getAttribute('data-m')); [].forEach.call(tog.querySelectorAll('button'),function(x){x.setAttribute('aria-pressed',x===b?'true':'false');}); draw(tb); }); });
      [].forEach.call(tb.querySelectorAll('th.srt'),function(h){ var go=function(){ var k=h.getAttribute('data-k');
        if(tb.getAttribute('data-k')===k) tb.setAttribute('data-d', -(+tb.getAttribute('data-d'))); else { tb.setAttribute('data-k',k); tb.setAttribute('data-d', (k==='n'||k==='stint'||k==='pos')?1:-1); }
        draw(tb); }; h.addEventListener('click',go); h.addEventListener('keydown',function(e){ if(e.key==='Enter'||e.key===' '){ e.preventDefault(); go(); } }); }); }); }
    init();
  })();
  document.addEventListener('click',function(e){ var b=e.target.closest&&e.target.closest('.wptog button'); if(!b) return; var sec=b.closest('section');
    [].forEach.call(sec.querySelectorAll('.wptog button'),function(x){x.setAttribute('aria-pressed',x===b?'true':'false');});
    [].forEach.call(sec.querySelectorAll('.wpv'),function(x){x.hidden=x.getAttribute('data-v')!==b.getAttribute('data-v');}); });
  (function(){
    function sortW(th){ var tb=th.closest('table'), i=[].indexOf.call(th.parentNode.children,th), body=tb.tBodies[0];
      var d=th.getAttribute('aria-sort')==='descending'?1:-1; if(i===1&&!th.getAttribute('aria-sort')) d=1;
      var rows=[].slice.call(body.rows), v=function(r){ var c=r.cells[i]; return i===1?c.innerText.trim().toLowerCase():parseFloat(c.innerText); };
      rows.sort(function(a,b){ var x=v(a), y=v(b); return i===1? d*(x<y?-1:x>y?1:0) : (d===-1?(y-x):(x-y)); });
      rows.forEach(function(r,j){ r.cells[0].textContent=j+1; body.appendChild(r); });
      [].forEach.call(th.parentNode.children,function(h){h.removeAttribute('aria-sort');}); th.setAttribute('aria-sort', d===-1?'descending':'ascending'); }
    document.addEventListener('click',function(e){ var th=e.target.closest&&e.target.closest('table.wpos th.srt'); if(th) sortW(th); });
    document.addEventListener('keydown',function(e){ var th=e.target.closest&&e.target.closest('table.wpos th.srt'); if(th&&(e.key==='Enter'||e.key===' ')){ e.preventDefault(); sortW(th); } });
  })();
  document.addEventListener('click',function(e){ var b=e.target.closest&&e.target.closest('.stog button'); if(!b) return; var g=b.parentNode, tb=g.nextElementSibling.querySelector('table.stand');
    [].forEach.call(g.querySelectorAll('button'),function(x){x.setAttribute('aria-pressed',x===b?'true':'false');}); tb.setAttribute('data-v',b.getAttribute('data-v')); });
  (function(){
    var ST={2:'Started',1:'Bench',3:'IR',0:'<span class="muted">-</span>'};
    var state={k:'pts',d:-1};
    function rowsFor(sec){
      var w=sec.querySelector('.wk-w').value, sf=sec.querySelector('.wk-s').value, pa=sec.querySelector('.wk-p .nx'), pf=pa?pa.getAttribute('data-pos'):'All';
      var med=WKD.MED[w]||{}, out=[];
      (WKD.WK[w]||[]).forEach(function(x){ var nm=WKD.NM[x[0]]; if(!nm) return; var P=nm[1];
        if(pf!=='All'&&P!==pf) return; if(sf!=='all'&&String(x[2])!==sf) return;
        var pts=x[3], e=(pts==null||med[P]==null)?null:pts-med[P], war=(pts==null||WKD.R[P]==null)?null:(pts-WKD.R[P])*WKD.WPP;
        out.push({i:x[0],n:nm[0],p:P,nfl:nm[2],r:x[1],t:x[1]?TM[x[1]][0]:'zzz',st:x[2],pts:pts,e:e,war:war,s:x[4],bye:x[5]}); });
      var k=state.k,d=state.d; out.sort(function(a,b){ var x=a[k],y=b[k]; if(x==null) return 1; if(y==null) return -1; if(typeof x==='string') return d*(x<y?-1:x>y?1:0); return d*(x-y); });
      return out; }
    function sg(v,dp){ return v==null?'<td class="r muted">-</td>':'<td class="r '+(v>0.005?'pos':(v<-0.005?'neg':'muted'))+'">'+(v>=0?'+':'')+v.toFixed(dp)+'</td>'; }
    function draw(sec){ var rs=rowsFor(sec), h='';
      rs.slice(0,300).forEach(function(x,j){ h+='<tr class="'+(x.st===2?'':'bn')+'"><td class="c muted">'+(j+1)+'</td><td><a class="pn" href="#/player/'+x.i+'"><b>'+esc(x.n)+'</b></a></td><td class="c">'+x.p+'</td><td class="c">'+esc(x.nfl)+'</td><td>'+(x.r?tlink(x.r):'<span class="muted">Free agent</span>')+'</td>'
        +'<td class="c">'+(x.st===2?'<b class="pos">Started</b>':ST[x.st])+'</td><td class="r big">'+(x.bye&&x.pts==null?'<span class="byec">BYE</span>':(x.pts==null?'-':fpt(x.pts)))+'<small class="wsm">'+esc(x.s||'')+'</small></td>'+sg(x.e,1)+sg(x.war,2)+'<td class="muted wst">'+esc(x.s||'')+'</td></tr>'; });
      if(!rs.length) h='<tr><td colspan="10" class="muted">No players match.</td></tr>';
      sec.querySelector('.wktab tbody').innerHTML=h;
      [].forEach.call(sec.querySelectorAll('.wktab th.srt'),function(th){ th.setAttribute('aria-sort', th.getAttribute('data-k')===state.k?(state.d<0?'descending':'ascending'):'none'); }); }
    document.addEventListener('click',function(e){
      var b=e.target.closest&&e.target.closest('.pmode button');
      if(b){ var m=b.getAttribute('data-m'), mn=b.closest('main'); [].forEach.call(b.parentNode.querySelectorAll('button'),function(x){x.setAttribute('aria-pressed',x===b?'true':'false');});
        mn.querySelector('.pm-season').hidden=(m!=='season'); var wk=mn.querySelector('.pm-week'); wk.hidden=(m!=='week'); if(m==='week') draw(wk); return; }
      var c=e.target.closest&&e.target.closest('.wk-p a'); if(c){ e.preventDefault(); [].forEach.call(c.parentNode.querySelectorAll('a'),function(x){x.classList.toggle('nx',x===c);}); draw(c.closest('.pm-week')); return; }
      var th=e.target.closest&&e.target.closest('.wktab th.srt'); if(th){ var k=th.getAttribute('data-k'); if(state.k===k) state.d=-state.d; else { state.k=k; state.d=(k==='n'||k==='t'||k==='p')?1:-1; } draw(th.closest('.pm-week')); }
    });
    document.addEventListener('change',function(e){ if(e.target.matches&&e.target.matches('.wk-w,.wk-s')) draw(e.target.closest('.pm-week')); });
  })();
  (function(){
    var COL=['#0B1F44','#C9A227','#1E7B4A','#B03A2E','#3A6EA5','#8E44AD','#E67E22','#16A085','#7F8C8D','#D35480'];
    var st={k:0,iso:{}};
    function isoOn(){ return Object.keys(st.iso).length>0; }
    function wkEnd(lb){ return /^W\d+$/.test(lb); }          // a finished week: gets a dot
    function when(k){ var lb=OH[k][0]; if(/ play$/.test(lb)) return 'during Week '+lb.slice(1,-5)+', '+nice(OH[k][1]); return wkEnd(lb)?'after Week '+lb.slice(1):(lb.replace('Pre-W','before Week ').replace(' live',' (live)'))+', '+nice(OH[k][1]); }
    function tms(ts){ var m=/^(\d{4})-(\d\d)-(\d\d) (\d\d):(\d\d)/.exec(ts); return m?Date.UTC(+m[1],+m[2]-1,+m[3],+m[4],+m[5]):null; }
    function nice(ts){ var m=/^(\d{4})-(\d\d)-(\d\d) (\d\d):(\d\d)/.exec(ts); if(!m) return ts; var h=+m[4], ap=h<12?'AM':'PM'; h=h%12||12;
      return ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][+m[2]-1]+' '+(+m[3])+', '+h+':'+m[5]+' '+ap; }
    function draw(sec){ if(!window.OH||!OH.length) return; var n=OH.length, D=function(k){ return OH[k][2]; };
      // x: each finished week is one step; every update in between sits evenly inside its step
      var anc=[]; for(var k=0;k<n;k++) if(wkEnd(OH[k][0])) anc.push(k); if(!anc.length||anc[0]!==0) anc.unshift(0);
      // inside a week: play-by-play points sit by time across the games; plain updates around them keep their order
      var XU=new Array(n); for(var a=0;a<anc.length;a++){ var s=anc[a], e=a+1<anc.length?anc[a+1]:n, last=a+1>=anc.length, w_=last?0.85:1;
        var pl=[]; for(k=s+1;k<e;k++) if(/ play$/.test(OH[k][0])) pl.push(k);
        if(pl.length>1){ var p0=pl[0], p1=pl[pl.length-1], nb=p0-s, na=e-1-p1, tot=nb+na+4, lo=(nb+1)/tot, hi=1-(na+1)/tot;
          // game time only: a gap with no plays (overnight, Friday, Saturday) shrinks to 45 minutes
          var GT={}, acc=0, pv=tms(OH[p0][1]); for(var q=p0;q<=p1;q++){ var tq=tms(OH[q][1]); acc+=Math.min(Math.max(0,tq-pv),45*60000); pv=tq; GT[q]=acc; }
          var ta=0, tb=acc;
          if(last&&na===0) hi=1;
          for(k=s;k<e;k++){ var f; if(k<=s) f=0; else if(k<p0) f=lo*(k-s)/(p0-s); else if(k<=p1) f=lo+(hi-lo)*((GT[k]-ta)/Math.max(1,tb-ta)); else f=hi+(1-hi)*(k-p1)/Math.max(1,e-p1); XU[k]=a+f*w_; } }
        else for(k=s;k<e;k++) XU[k]=a+(!last?(k-s)/(e-s):(k-s)/Math.max(1,e-s-1)*0.85); }
      var span=Math.max(1,XU[n-1]);
      var R=Object.keys(D(n-1)).map(Number), sm=window.innerWidth<600, Wd=sm?400:720, Hd=sm?330:300, L=38, Rm=14, T=12, B=28,
          X=function(k){ return L+(n>1?XU[k]/span:0.5)*(Wd-L-Rm); }, NR=Object.keys(D(n-1)).length, SD=st.k===3,
          Y=function(v){ return SD?T+(v-1)/(NR-1)*(Hd-T-B):T+(1-v)*(Hd-T-B); }, VAL=function(o){ return o&&o.length>st.k?o[st.k]:null; }, FMT=function(v){ return SD?v.toFixed(1):pc1(v); };
      var g='';
      (SD?[1,2,4,6,8,NR]:[0,.25,.5,.75,1]).forEach(function(v){ g+='<line x1="'+L+'" x2="'+(Wd-Rm)+'" y1="'+Y(v)+'" y2="'+Y(v)+'" stroke="#E3E7EE"/><text x="'+(L-6)+'" y="'+(Y(v)+4)+'" text-anchor="end" font-size="11" fill="var(--mute)">'+(SD?v:(v*100)+'%')+'</text>'; });
      anc.forEach(function(k){ if(wkEnd(OH[k][0])) g+='<line x1="'+X(k)+'" x2="'+X(k)+'" y1="'+T+'" y2="'+(Hd-B)+'" stroke="#EEF1F6"/><text x="'+X(k)+'" y="'+(Hd-8)+'" text-anchor="middle" font-size="11" fill="var(--mute)">'+esc(OH[k][0])+'</text>'; });
      if(!wkEnd(OH[n-1][0])) g+='<text x="'+X(n-1)+'" y="'+(Hd-8)+'" text-anchor="end" font-size="11" fill="var(--mute)">Now</text>';
      var order=R.slice().sort(function(a,b){ return SD?(VAL(D(n-1)[a])-VAL(D(n-1)[b])):(D(n-1)[b][st.k]-D(n-1)[a][st.k]); }), hit='', lnh='';
      order.slice().reverse().sort(function(a,b){ return (st.iso[a]?1:0)-(st.iso[b]?1:0); }).forEach(function(r){ var c=COL[(r-1)%COL.length], on=st.iso[r], dim=isoOn()&&!on, pts=[];
        for(var k=0;k<n;k++){ var o=D(k)[r], vv=VAL(o); if(vv!==null&&vv!==undefined) pts.push([X(k),Y(vv),vv,k]); }
        var op=dim?0.12:1, sw=on?3.5:2.2, pp=pts.map(function(p){return p[0].toFixed(1)+','+p[1].toFixed(1);}).join(' ');
        g+='<polyline fill="none" stroke="'+c+'" stroke-width="'+sw+'" stroke-linejoin="round" opacity="'+op+'" points="'+pp+'"/>';
        lnh+='<polyline class="ohln" data-r="'+r+'" fill="none" stroke="transparent" stroke-width="14" stroke-linejoin="round" points="'+pp+'" style="cursor:pointer"/>';      // tap a line to isolate that team
        pts.forEach(function(p){ var end=wkEnd(OH[p[3]][0])||p[3]===n-1;
          if(end) g+='<circle cx="'+p[0].toFixed(1)+'" cy="'+p[1].toFixed(1)+'" r="'+(on?4.5:3)+'" fill="'+c+'" opacity="'+op+'" pointer-events="none"/>';
          if(!dim) hit+='<circle class="ohp" cx="'+p[0].toFixed(1)+'" cy="'+p[1].toFixed(1)+'" r="9" fill="transparent" data-r="'+r+'" data-k="'+p[3]+'" data-v="'+p[2]+'"/>'; }); });
      sec.querySelector('.ohc').innerHTML='<div class="ohtip" hidden></div><svg viewBox="0 0 '+Wd+' '+Hd+'" width="100%" role="img" aria-label="Odds after every site update">'+g+lnh+hit+'</svg>';
      var lg=''; order.forEach(function(r){ var last=VAL(D(n-1)[r]), c=COL[(r-1)%COL.length];
        lg+='<button type="button" class="ohb'+(st.iso[r]?' on':'')+(isoOn()&&!st.iso[r]?' off':'')+'" data-r="'+r+'" aria-pressed="'+(st.iso[r]?'true':'false')+'"><i style="background:'+c+'"></i><i class="im lgs L'+r+'"></i><span>'+esc(sm?TM[r][1]:TM[r][0])+'</span><b>'+(last===null?'-':FMT(last))+'</b></button>'; });
      sec.querySelector('.ohl').innerHTML=lg+(isoOn()?'<button type="button" class="ohclr">Show all teams</button>':''); }
    document.addEventListener('click',function(e){
      var b=e.target.closest&&e.target.closest('.ohk button'); if(b){ st.k=+b.getAttribute('data-k'); [].forEach.call(b.parentNode.querySelectorAll('button'),function(x){x.setAttribute('aria-pressed',x===b?'true':'false');}); draw(b.closest('section')); return; }
      var ln=e.target.closest&&e.target.closest('.ohln'); if(ln){ var rl=+ln.getAttribute('data-r'); if(st.iso[rl]) delete st.iso[rl]; else st.iso[rl]=1; draw(ln.closest('section')); return; }
      var t=e.target.closest&&e.target.closest('.ohb'); if(t){ var r=+t.getAttribute('data-r'); if(st.iso[r]) delete st.iso[r]; else st.iso[r]=1; draw(t.closest('section')); return; }
      var cl=e.target.closest&&e.target.closest('.ohclr'); if(cl){ st.iso={}; draw(cl.closest('section')); return; }
      var pt=e.target.closest&&e.target.closest('.ohp'), tip;
      [].forEach.call(document.querySelectorAll('.ohtip'),function(x){ if(!pt||!x.parentNode.contains(pt)) x.hidden=true; });
      if(pt){ var box=pt.closest('.ohc'), r2=+pt.getAttribute('data-r'), k2=+pt.getAttribute('data-k'), v=+pt.getAttribute('data-v'), lab=['Playoffs','Bye','Title','Forecast seed'][st.k];
        tip=box.querySelector('.ohtip'); tip.innerHTML='<b>'+esc(TM[r2][0])+'</b> ('+esc(TM[r2][1])+')<br>'+lab+': <b>'+(st.k===3?v.toFixed(1):pc1(v))+'</b><br><small>'+esc(when(k2))+'</small><button type="button" class="ohx" aria-label="Close">×</button>';
        tip.hidden=false; var bb=box.getBoundingClientRect(), pb=pt.getBoundingClientRect(), x=pb.left-bb.left+pb.width/2, y=pb.top-bb.top;
        tip.style.left=Math.max(4,Math.min(bb.width-190,x-95))+'px'; tip.style.top=Math.max(0,y-74)+'px'; } });
    [].forEach.call(document.querySelectorAll('.ohc'),function(c){ draw(c.closest('section')); });
  })();

  (function(){   // menu and search: every page in one panel, plus teams, players, NFL teams, stories and records
    var GR=[['This week',[['','Home'],['news','News'],['schedule','Schedule'],['playoffs','Playoffs']]],
            ['Standings and honors',[['standings','Standings'],['races','Awards'],['records','Records'],['excitement','Excitement']]],
            ['Teams and players',[['teams','Teams'],['players','Players'],['nfl','NFL teams'],['h2h','Head to head']]],
            ['Front office',[['transactions','Transactions'],['trades','Trades'],['analyzer','Trade analyzer'],['draft','Draft']]]];
    var ov=document.createElement('div'); ov.className='nvo'; ov.hidden=true;
    ov.innerHTML='<div class="nvp" role="dialog" aria-modal="true" aria-label="Menu and search"><div class="nvh"><input type="search" placeholder="Search players, teams, pages, stories" aria-label="Search" autocomplete="off"><button type="button" class="nvx" aria-label="Close">&times;</button></div><div class="nvb"><div class="nvr" hidden></div><div class="nvgs"></div></div></div>';
    document.body.appendChild(ov);
    var inp=ov.querySelector('input'), res=ov.querySelector('.nvr'), gs=ov.querySelector('.nvgs');
    function drawGroups(){ var cur=(RH().replace(/^#\\/?/,'').split('/')[0])||'';
      gs.innerHTML=GR.map(function(g){ return '<div class="nvg"><h3>'+g[0]+'</h3>'+g[1].map(function(x){ return '<a href="#/'+x[0]+'"'+(x[0]===cur?' aria-current="page"':'')+'>'+x[1]+'</a>'; }).join('')+'</div>'; }).join(''); }
    var IDX=null;
    function build(){ IDX=[];
      GR.forEach(function(g){ g[1].forEach(function(x){ IDX.push([x[1],'Page','#/'+x[0],'']); }); });
      Object.keys(TM).forEach(function(r){ IDX.push([TM[r][0],'Team, '+TM[r][1],'#/team/'+TM[r][1]+'/'+YR,'<i class="im lgs L'+r+'"></i>',TM[r][1]]); });
      if(window.PD) Object.keys(PD).forEach(function(i){ var d=PD[i]; IDX.push([d.n,(d.p||'')+(d.t?', '+d.t:''),'#/player/'+i,'']); });
      if(window.NFLN) Object.keys(NFLN).forEach(function(t){ IDX.push([NFLN[t],'NFL team','#/nfl/'+t,'',t]); });
      if(window.NWS) NWS.forEach(function(n){ IDX.push([n[0],'Story'+(n[2]?', Week '+n[2]:''),'#/news/'+n[1],'']); });
      if(typeof BOOK!=='undefined') Object.keys(BOOK).forEach(function(b){ BOOK[b].forEach(function(g){ g[1].forEach(function(x){ IDX.push([x[1],'Record','#/records/'+b,'']); }); }); });
    }
    function norm(t){ return String(t).toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g,'').replace(/[^a-z0-9 ]/g,''); }
    function search(){ var q=norm(inp.value).trim(); if(!q){ res.hidden=true; gs.hidden=false; return; }
      if(!IDX) build(); var ws=q.split(/\\s+/), out=[];
      IDX.forEach(function(e){ var hay=norm(e[0]+' '+(e[4]||'')+' '+e[1]); if(ws.every(function(w){return hay.indexOf(w)>=0;})){ var n=norm(e[0]), sc=(n===q?0:n.indexOf(q)===0?1:(' '+n).indexOf(' '+ws[0])>=0?2:3); out.push([sc,e]); } });
      out.sort(function(a,b){return a[0]-b[0]||a[1][0].length-b[1][0].length;}); out=out.slice(0,30);
      res.innerHTML=out.length?out.map(function(x,k){ var e=x[1]; return '<a href="'+e[2]+'"'+(k===0?' class="on"':'')+'>'+e[3]+'<span>'+esc(e[0])+'</span><small>'+esc(e[1])+'</small></a>'; }).join(''):'<div class="none">Nothing matches "'+esc(inp.value)+'"</div>';
      res.hidden=false; gs.hidden=true; }
    function open(focus){ drawGroups(); ov.hidden=false; document.body.style.overflow='hidden'; if(focus){ inp.focus(); } else ov.querySelector('.nvx').focus(); }
    function close(){ ov.hidden=true; document.body.style.overflow=''; inp.value=''; search(); }
    inp.addEventListener('input',search);
    inp.addEventListener('keydown',function(e){ if(e.key==='Enter'){ var a=res.querySelector('a'); if(a){ nav(a.getAttribute('href')); close(); } } });
    document.addEventListener('click',function(e){
      var b=e.target.closest&&e.target.closest('.tbtn'); if(b){ open(b.classList.contains('tsrch')); return; }
      if(ov.hidden) return;
      if(e.target===ov||(e.target.closest&&e.target.closest('.nvx'))){ close(); return; }
      if(e.target.closest&&e.target.closest('.nvo a')) close();
    });
    function navInView(){ setTimeout(function(){ [].forEach.call(document.querySelectorAll('.pg:not([hidden]) .menu a[aria-current=page]'),function(a){ var m=a.parentNode; if(m.scrollWidth>m.clientWidth) m.scrollLeft=Math.max(0,a.offsetLeft-m.offsetLeft-m.clientWidth/2+a.offsetWidth/2); }); },0); }
    window.addEventListener('hashchange',navInView); navInView();
    document.addEventListener('keydown',function(e){
      if(e.key==='Escape'&&!ov.hidden){ close(); return; }
      if(e.key==='/'&&ov.hidden&&!(e.target.matches&&e.target.matches('input,textarea,select'))){ e.preventDefault(); open(true); }
    });
  })();
  window.addEventListener('hashchange',go); go();
  (function(){ var pg=document.querySelector('.pg[data-p="records"]'); if(pg&&!pg.hidden){pg._done=1; renderRec(pg);} })();
  document.addEventListener('click',function(e){
    var mb=e.target.closest&&e.target.closest('.mtog button');
    if(mb){var mg=mb.closest('main'); ['mw','mp','mr'].forEach(function(k){mg.classList.toggle('show-'+k,k===mb.getAttribute('data-m'));});
      [].forEach.call(mb.parentNode.querySelectorAll('button'),function(x){x.setAttribute('aria-pressed',x===mb?'true':'false');}); return;}
    var b=e.target.closest&&e.target.closest('.tog button'); if(!b||b.closest('.rper')) return;
    var sec=b.closest('section'), v=b.getAttribute('data-v');
    [].forEach.call(sec.querySelectorAll('.tog button'),function(x){x.setAttribute('aria-pressed',x===b?'true':'false');});
    [].forEach.call(sec.querySelectorAll('.tv'),function(x){x.hidden=x.getAttribute('data-v')!==v;});
  });
})();
</script>"""
    pdata = ""
    if site is not None:
        import json as _json
        teams = {r: [site.TN(r), s.M[r]] for r in s.R}
        pdata = ("<script>var TA=" + _json.dumps(site.ta_data(), separators=(",", ":")) + ";</script>" + open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ta.js")).read() + "<script>var WKD=" + _json.dumps(site.week_data(), separators=(",", ":")) + ";var PD=" + _json.dumps(site.players_data(), separators=(",", ":")) + ";var TM=" + _json.dumps(teams, separators=(",", ":")) + ";var TMW=" + _json.dumps(site.names_js(), separators=(",", ":")) +
                 ";var NG=" + _json.dumps({n["slug"]: "game/w%s-%s-%s" % ((lambda w, a, b: (w, min(a, b), max(a, b)))(*(int(x) for x in n["game"].split("-")))) for n in site.news_list() if n.get("kind") not in ("feature", "cover") and n.get("game")}, separators=(",", ":")) + ";var NFLN=" + _json.dumps({k: f"{NFL_CITY[k]} {NFL_NICK[k]}" for k in NFL_NICK if k in NFL_CITY}, separators=(",", ":")) + ";var NFLK=" + _json.dumps(NFL_NICK, separators=(",", ":")) + ";var OH=" + _json.dumps([[lab, ts, {str(r): [round(v[0], 4), round(v[1], 4), round(v[2], 4)] + ([round(v[3], 3)] if len(v) > 3 and v[3] is not None else []) for r, v in d.items()}] for lab, ts, d in site.oh_ext()], separators=(",", ":")) + ";var NWS=" + _json.dumps([[n["title"], n["slug"], n.get("week")] for n in site.news_list()], separators=(",", ":")) + ";var GOF=" + _json.dumps({str(w): {str(r): (g[1] if g[0] == r else g[0]) for (w_, r), g in site.game_of.items() if w_ == w} for w in sorted({k[0] for k in site.game_of})}, separators=(",", ":")) + ";var NSCH=" + _json.dumps(nfl_sched(s), separators=(",", ":")) + ";var YR=" + _json.dumps(str(site.yr)) + ";var BY=" + _json.dumps({t: 0 for t in NFL_NICK} | {t: w for w, ts in s.byes.items() for t in ts}) + ";</script>")
        chrome = first[first.index("<body>") + 6:first.index("</div></div></div>", first.index('class="top"')) + 18]
        chrome = re.sub(r' aria-current=page', '', chrome)
        chrome = re.sub(r'href="(index|news|standings|playoffs|schedule|teams|players|h2h|draft|races|awards|trades|transactions|excitement|analyzer|records)\.html"', lambda m: f'href="#/{"" if m.group(1) == "index" else m.group(1)}"', chrome)
        pages.append(f'<div class="pg" data-p="player" data-t="Player" hidden>{chrome}<div id="pv"></div></div>')
        pages.append(f'<div class="pg" data-p="nfl" data-t="NFL team" hidden>{chrome}<div id="nv"></div></div>')
    R_ = s.repl["val"]
    TIPS = {"VAR": f"Value above replacement: points scored in Super League starting lineups minus what the best free agents at his position average ({', '.join(f'{p} {v:.1f}' for p, v in R_.items())} a week). Bench weeks count for nothing.",
            "PAA": "Points Above Average: how many points better than the typical starter at his position that week (the median Super League starter). Added up over his starts. 0 = an average starter.",
            "PAA/start": "PAA divided by starts: how much better than the typical starter at his position he is in an average start.",
            "WAR": f"Wins above replacement: points scored in Super League starting lineups minus what the best free agents at his position average ({', '.join(f'{p} {v:.1f}' for p, v in R_.items())} a week), turned into wins. About {s.ppw:.0f} points = 1 win. Bench weeks count for nothing.",
            "Wins added": "What the trade has been worth in wins: each team's best lineup with the trade versus without it, every week since. Negative = it cost wins.",
            "Best GM": "Wins added by roster moves: draft, trades and waiver or free-agent moves, with every move graded the same way as trades. The same measure as the GM of the Year race.",
            "Most wins gained in a trade": "The most one team has gained from a single trade: its best lineup with the deal versus without it, in wins. The other side can gain too.",
            "Most lopsided trade": "The biggest gap between the two sides of one trade: the winner's wins gained minus the loser's.",
            "Most gut-call wins added": "What your lineup scored above or below the lineup the pregame projections would have started from the same players, in wins.",
            "Most total wins added": "Everything a manager added: draft, trades and pickups (GM) plus gut calls, in wins.",
            "Most efficient GM": "Wins added by trades and waiver or free-agent pickups, divided by how many trades and moves it took. At least 5.",
            "Most efficient trader": "Wins added by trades, per trade. At least 2 trades.",
            "Most efficient waiver work": "Wins added by waiver and free-agent pickups, per move. At least 5 moves.",
            "Best trader": "Wins added by all of a team's trades: best lineup with each deal versus without it, every week since.",
            "Best lineup efficiency": "Points scored as a share of the perfect lineup in hindsight.",
            "Most points over projection": "Points scored minus the pregame projection of the starters, added up.",
            "Costliest drops": "Wins this team lost by cutting players: each drop on its own, its best lineup with the cut minus without it, every week until the player came back.",
            "Best pickup": "Wins one pickup added: the team's best lineup with him minus with a replacement-level free agent instead, every week until he was let go.",
            "Worst drop": "Wins one cut cost: the team's best lineup with the cut minus without it (keeping him, minus its least useful bench player), every week until he came back.",
            "Best waiver work": "Wins added by every waiver and free-agent move (adds and drops together), each graded like a trade: best lineup with the move minus without it.",
            "Best win %": "His fantasy team's record in weeks he started. No minimum; ties go to the player with more starts.",
            "Win Impact": "How much his own play moved the odds of his team winning, in wins. Each start: the win chance his PAA alone gives an otherwise average lineup, minus 50%. An average game is 0, a +20 PAA game about +0.22, a dud about -0.15. Added up over his starts. Big games count less than a straight point total would, because one player can only swing a game so far.",
            "Most Win Impact": "Win Impact added up over his starts: how much his own play moved the odds of his teams winning, in wins.",
            "Least Win Impact": "Win Impact added up over his starts.",
            "Support": "Supporting cast: wins in his starts minus what his own play earned (0.5 a start plus his Win Impact). + means his teammates won games beyond what he gave them; - means he produced and his team lost anyway (Dak and Kittle territory). Not a knock on the player either way.",
            "Best supporting cast": "Wins in his starts minus what his own play earned (0.5 a start plus his Win Impact): how much his teammates won for him.",
            "Worst supporting cast": "Wins in his starts minus what his own play earned: the most he produced in games his team lost anyway.",
            "Best record": "Win % for the season. The same record is a shared record.",
            "Worst record": "Win % for the season. The same record is a shared record.",
            "PPG": "Points per game started, in Super League starting lineups.",
            "Most points per game": "Points per game started. At least 4 starts.",
            "Fewest points per game": "Points per game started. At least 4 starts.",
            "Worst win %": "His fantasy team's record in weeks he started. No minimum; ties go to the player with more starts.",
            "Most weeks as the #1 at his position": "Weeks he outscored every other Super League starter at his position. Ties go to the player with fewer starts.",
            "Most wins": "Games his fantasy team won in weeks he started.",
            "Most bench points per week": "Bench points divided by weeks on a Super League bench. At least 4 bench weeks.",
            "Most improbable win": "The winner's lowest chance to win at any point in the game, rebuilt play by play from every NFL game that week.",
            "Lowest win chance overcome": "The winner's lowest chance to win at any point in the game, rebuilt play by play from every NFL game that week.",
            "Biggest deficit overcome": "The most points the winner trailed by at any point in the game (play by play), and still won.",
            "Pick grade": "His WAR minus the bar for his draft spot: the average WAR of the players ranked around that spot in a redraft."}
    TIPS.update({"WAR here": TIPS["WAR"], "Total WAR": TIPS["WAR"]})
    out = head + f"<style>{ff}{lg}.pg[hidden]{{display:none}}</style></head><body>\n" + "\n".join(pages) + pdata + js + "\n</body></html>"
    for k, v in TIPS.items():
        out = out.replace(f">{k}<", f'><span class="tip" tabindex="0" data-tip="{E(v)}">{k}</span><')
    out = out.replace(">-0.00<", ">+0.00<").replace('"-0.00"', '"+0.00"')      # a rounded zero has no sign
    return out


def build_site(s, T, TEAM, SIM, L, weeks_left, starts_pm, season_pm, logo_dir="data/logos", proj=None, font_dir="data/fonts", single=True):
    global LAST_SITE
    S = Site(s, T, TEAM, SIM, weeks_left, starts_pm, season_pm, logo_dir, proj); LAST_SITE = S
    files = S.site_pages()
    for r in s.R: files[f"team/{s.M[r]}.html"] = S.team(r)
    files.update(S.news_pages())
    for w, a, b, done in S.games:
        x, y = sorted((a, b))
        files[S.gurl(w, a, b, "")] = S.game_done(w, x, y) if done else S.game_next(w, x, y)
    if not single: return files
    GP_FILES.clear(); idx = bundle(files, s, logo_dir, font_dir, S)
    return {"index.html": idx, **GP_FILES}
