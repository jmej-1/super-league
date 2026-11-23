# Super League 2026

Stats site for the Super League (10-team Sleeper redraft).

- `site/index.html` is the whole website. Vercel serves this folder.
- `.github/workflows/update.yml` pulls Sleeper and ESPN on a schedule, rebuilds, and commits. Every commit redeploys.
- Manual update: Actions tab, "Update Super League", "Run workflow".
- Stories live in `data/news/week-XX.md`. `python3 desk_due.py data` lists which ones are due.
- Local run: `pip install -r requirements.txt && bash update.sh`
