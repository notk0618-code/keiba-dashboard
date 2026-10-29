#!/usr/bin/env bash
# Weekly keiba_db update in a Claude cloud session (env "keiba", GOOGLE_SERVICE_ACCOUNT_JSON set).
#   weekly.sh check    -> read-only: is there new TARGET data?
#   weekly.sh trial    -> full run, but no Drive write-back and no site push
#   weekly.sh prod     -> full run, Drive write-back, then push the site
# Needs the site repo cloned at $SITE (default /home/user/keiba-dashboard).
set -euo pipefail
MODE=${1:?check|trial|prod}
HERE=$(cd "$(dirname "$0")" && pwd)
SITE=${SITE:-$(cd "$HERE/.." && pwd)}   # the repo this folder lives in
WORK=${WORK:-/tmp/keiba-work}; mkdir -p "$WORK"
DUCK="$WORK/duckdb-1.3.2"   # matches the DB's storage format and stays readable by Colab's duckdb 1.x
KDB=/content/drive/MyDrive/keiba_db

if [ ! -f "$WORK/.deps" ]; then
  pip install -q google-auth google-api-python-client "pandas>=2.2,<2.4" pyarrow requests scikit-learn \
      ipython ipywidgets beautifulsoup4 PyGithub 2>&1 | grep -v -i warning || true
  pip install -q --target "$DUCK" duckdb==1.3.2 2>&1 | grep -v -i warning || true
  touch "$WORK/.deps"
fi
export PYTHONPATH="$DUCK" PYTHONUNBUFFERED=1
cd "$WORK"

CHECK=$(python3 "$HERE/check_needed.py")
echo "[weekly] $CHECK"
[ "$MODE" = check ] && exit 0
case "$CHECK" in NEED*) ;; *) [ "$MODE" = prod ] && exit 0 ;; esac
DATE=$(echo "$CHECK" | awk '{print $2}')

git -C "$SITE" fetch -q origin main && git -C "$SITE" checkout -q main && git -C "$SITE" reset -q --hard origin/main
mkdir -p "$(dirname "$KDB")"
python3 "$HERE/mirror.py" "$KDB"
FLAG=""; [ "$MODE" = trial ] && FLAG="--trial"
python3 "$HERE/weekly_runner.py" $FLAG --date "$DATE" --site "$SITE" 2>&1 | tee "$WORK/run_$DATE.log" | grep -E "^\[runner\]|🚨|^=== .*振り返り結果|^指数トップ|^堅軸|Traceback|Error:" || true
grep -q '^\[runner\] RESULT' "$WORK/run_$DATE.log" || { echo "[weekly] runner failed; see $WORK/run_$DATE.log"; tail -30 "$WORK/run_$DATE.log"; exit 1; }
if [ "$MODE" = prod ]; then
  python3 "$HERE/writeback.py" "$KDB"
  if [ -n "$(git -C "$SITE" log origin/main..HEAD --oneline)" ]; then
    git -C "$SITE" push origin HEAD:main && echo "[weekly] site pushed"
  fi
else
  python3 "$HERE/writeback.py" "$KDB" --dry-run
fi
