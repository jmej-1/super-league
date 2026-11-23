#!/bin/bash
# One-command update: pull Sleeper + ESPN (and play-by-play), ingest, rebuild the site, check the JS.
# Prints OK and the site path on success. Publishing is done after this, by Claude, to the workshop artifact.
set -e
P="$(cd "$(dirname "$0")" && pwd)"; cd "$P"
TS=$(date +%m%d_%H%M); RAW=/tmp/raw_$TS
bash fetch.sh "$RAW" "$P/data" > /tmp/update_fetch.log 2>&1
[ -n "$CI" ] || cp -r data "$P/../data_bak_$TS"
ls -dt "$P"/../data_bak_* 2>/dev/null | tail -n +8 | xargs -r rm -rf          # keep the last 7 backups
ls -dt /tmp/raw_* | tail -n +4 | xargs -r rm -rf                          # and the last 3 raw pulls
python3 ingest.py "$RAW" data > /tmp/update_ingest.log 2>&1
rm -rf out/site
python3 superleague.py data out > /tmp/update_build.log 2>&1
python3 -c "import re;h=open('out/site/index.html').read();open('/tmp/a.js','w').write('\n;\n'.join(re.findall(r'<script>(.*?)</script>',h,re.S)))"
node --check /tmp/a.js
grep -h "^done=\|^week=" data/live.txt | tr '\n' ' '
echo; echo "OK $P/out/site/index.html"
python3 desk_due.py data || true
mkdir -p site && cp out/site/index.html site/index.html
