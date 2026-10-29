"""Decide which uploads need processing (read-only). Prints one JSON object:
{"weekly": "<YYYYMMDD>"|null, "daily": [{"kind": "toujitsu"|"tokubetsu", "file": ..., "dates": [...]}]}
- toujitsu: newest 当日出走馬YYYYMMDD*.csv per race date (today or later, JST) that is newer than its prediction_log.
- tokubetsu: newest 特別登録*.csv whose race dates are still ahead, have no 当日出走馬 file yet, and are newer than
  their 当日出走馬YYMMDD_特別登録_分割.csv. Race dates come from the file name (8 digits, or 8+4 for two days)."""
import sys, os, re, json, subprocess, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import gdrive
JST = dt.timezone(dt.timedelta(hours=9))
today = dt.datetime.now(JST).strftime('%Y%m%d')
s = gdrive.svc(); fs = gdrive.list_folder(s)
by = {f['name']: f for f in fs}
mt = lambda n: by[n]['modifiedTime'] if n in by else ''
plan = {'weekly': None, 'daily': []}

chk = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'check_needed.py')],
                     capture_output=True, text=True)
print(f'[plan] {chk.stdout.strip() or chk.stderr.strip()[-300:]}', file=sys.stderr)
if chk.stdout.startswith('NEED'): plan['weekly'] = chk.stdout.split()[1]

SKIP = re.compile(r'_変換済み|_utf8|_特別登録_分割|バックアップ|★')
latest = {}
for f in fs:
    m = re.match(r'当日出走馬(\d{8})(.*)\.csv$', f['name'])
    if not m or SKIP.search(f['name']) or m.group(1) < today: continue
    d = m.group(1)
    if d not in latest or f['modifiedTime'] > latest[d]['modifiedTime']: latest[d] = f
for d, f in sorted(latest.items()):
    if f['modifiedTime'] > mt(f'prediction_log_{d[2:]}.parquet'):
        plan['daily'].append({'kind': 'toujitsu', 'file': f['name'], 'dates': [d]})

def tk_dates(name):
    m = re.match(r'特別登録(\d{8})(\d{4})?', name)
    if not m: return []
    d1 = m.group(1); ds = [d1]
    if m.group(2): ds.append(d1[:4] + m.group(2))
    else:  # one-date name: the week's Saturday file usually also holds Sunday
        ds.append((dt.date(int(d1[:4]), int(d1[4:6]), int(d1[6:])) + dt.timedelta(days=1)).strftime('%Y%m%d'))
    return ds
tks = [f for f in fs if f['name'].startswith('特別登録') and f['name'].endswith('.csv') and not SKIP.search(f['name'])]
for f in sorted(tks, key=lambda f: f['modifiedTime'], reverse=True)[:1]:
    ds = [d for d in tk_dates(f['name']) if d >= today and d not in latest]
    if ds and any(f['modifiedTime'] > mt(f'当日出走馬{d[2:]}_特別登録_分割.csv') for d in ds):
        plan['daily'].append({'kind': 'tokubetsu', 'file': f['name'], 'dates': ds})
if plan['daily'] and not gdrive.can_create():
    # predictions create new Drive files (prediction_log etc.), which only the owner's OAuth token can do
    print(f"[plan] GOOGLE_OAUTH_JSON がないため予想はスキップ: {[j['file'] for j in plan['daily']]}", file=sys.stderr)
    plan['daily'] = []
print(json.dumps(plan, ensure_ascii=False))
