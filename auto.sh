#!/usr/bin/env bash
# Hourly entry point: find new uploads in keiba_db and run whatever they need, then write back and publish.
#   auto.sh          -> plan, run, write back to Drive, push the site
#   auto.sh trial    -> plan and run, but no write-back or push
# Jobs: 地方ダートグレード開催の前後 → nar_runner (予想・答え合わせ, nar.html);
#       成績フルセット → weekly_runner (0-2〜0-4 + 7-25 verification); 当日出走馬 → daily_runner toujitsu (1.);
#       特別登録 → daily_runner tokubetsu (7-2). One mirror, jobs in that order, one write-back, one push.
set -euo pipefail
MODE=${1:-prod}
HERE=$(cd "$(dirname "$0")" && pwd)
SITE=${SITE:-/home/user/keiba-dashboard}
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

PLAN=${PLAN:-$(python3 "$HERE/plan_jobs.py")}  # PLAN=<json> forces a plan (testing, manual reruns)
echo "[auto] plan $PLAN"
WEEKLY=$(echo "$PLAN" | python3 -c 'import json,sys; print(json.load(sys.stdin)["weekly"] or "")')
JOBS=$(echo "$PLAN" | python3 -c 'import json,sys; [print(j["kind"], j["file"]) for j in json.load(sys.stdin)["daily"]]')
NAR=$(echo "$PLAN" | python3 -c 'import json,sys; print("1" if json.load(sys.stdin).get("nar") else "")')
if [ -z "$WEEKLY" ] && [ -z "$JOBS" ] && [ -z "$NAR" ]; then echo "[auto] nothing to do"; exit 0; fi

git -C "$SITE" fetch -q origin main && git -C "$SITE" checkout -q main && git -C "$SITE" reset -q --hard origin/main
mkdir -p "$(dirname "$KDB")"
python3 "$HERE/mirror.py" "$KDB"
FLAG=""; [ "$MODE" = trial ] && FLAG="--trial"
FILTER='^\[runner\]|🚨|^=== .*振り返り結果|^指数トップ|^堅軸|^予測の一致率|^\[.*\] 起点|Traceback|Error:'
run() {  # run one job; stop everything if it did not reach its RESULT line
  local log="$WORK/run_$1.log"; shift
  python3 "$@" $FLAG --site "$SITE" 2>&1 | tee "$log" | grep -E "$FILTER" || true
  grep -q '^\[runner\] RESULT' "$log" || { echo "[auto] job failed: $*"; tail -30 "$log"; exit 1; }
}
[ -n "$WEEKLY" ] && run "weekly_$WEEKLY" "$HERE/weekly_runner.py" --date "$WEEKLY"
while read -r KIND FILE; do
  [ -z "${KIND:-}" ] && continue
  run "${KIND}_${FILE%.csv}" "$HERE/daily_runner.py" --kind "$KIND" --file "$FILE"
done <<< "$JOBS"
# 地方ダートグレード (nar_runner.py): a failure here must not lose the JRA jobs above, so it only warns
if [ -n "$NAR" ]; then
  NLOG="$WORK/run_nar.log"
  python3 "$HERE/nar_runner.py" --db "$KDB/keiba.duckdb" $FLAG --site "$SITE" 2>&1 | tee "$NLOG" | grep -E '^\[nar\]|^\[runner\]|Traceback|Error' || true
  grep -q '^\[runner\] RESULT' "$NLOG" || { echo "[auto] 🚨 地方グレードの処理に失敗（中央の処理は続行）"; tail -15 "$NLOG"; }
fi

if [ "$MODE" = trial ]; then python3 "$HERE/writeback.py" "$KDB" --dry-run; exit 0; fi
python3 "$HERE/writeback.py" "$KDB"
if [ -n "$(git -C "$SITE" log origin/main..HEAD --oneline)" ]; then
  git -C "$SITE" push origin HEAD:main && echo "[auto] site pushed"
fi
