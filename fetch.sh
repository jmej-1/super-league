#!/bin/bash
# Pull a fresh Super League export straight from Sleeper and ESPN into $1 (an empty folder).
set -e
OUT="$1"; DATA="${2:-}"; HERE="$(cd "$(dirname "$0")" && pwd)"; L=1395560684279836672; Y=2026; S=https://api.sleeper.app/v1
mkdir -p "$OUT"; cd "$OUT"
urls=(
  "league.json $S/league/$L" "rosters.json $S/league/$L/rosters" "users.json $S/league/$L/users"
  "drafts.json $S/league/$L/drafts" "state.json $S/state/nfl" "players.json $S/players/nfl"
)
for w in $(seq 1 18); do
  urls+=("stats_$w.json $S/stats/nfl/regular/$Y/$w" "proj_$w.json $S/projections/nfl/regular/$Y/$w"
         "matchups_$w.json $S/league/$L/matchups/$w" "tx_$w.json $S/league/$L/transactions/$w"
         "sched_$w.json https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates=$Y&seasontype=2&week=$w")
done
printf '%s\n' "${urls[@]}" | xargs -P 12 -L 1 sh -c 'curl -sS -f -m 60 --retry 2 -o "$0" "$1"'
ls | wc -l
# play-by-play for every game that has started (finished games are cached in DATA/pbp and not pulled again)
if [ -n "$DATA" ]; then python3 -I "$HERE/pbp_fetch.py" "$OUT" "$DATA"; fi
