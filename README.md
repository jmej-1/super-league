# Super League 2026

Stats site for the Super League (10-team Sleeper redraft).

- Vercel builds the site (`python3 superleague.py data out`) from `data/` on every push and serves `site/index.html`.
- `.github/workflows/update.yml` runs every 15 minutes. `ci_gate.py` lets it through while an NFL game is on, otherwise once an hour. It pulls Sleeper and ESPN, rebuilds, and commits only `data/`.
- Manual update: Actions tab, "Update Super League", "Run workflow" (runs even with no game on).
- Stories live in `data/news/week-XX.md`. `python3 desk_due.py data` lists which ones are due.
- Local run: `pip install -r requirements.txt && bash update.sh`
