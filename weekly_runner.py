"""Run the weekly 0-2 -> 0-3 -> 0-4 sequence of restore_v7.py outside Colab.
Assumes keiba_db is mirrored at /content/drive/MyDrive/keiba_db and the site repo is cloned at --site.
Every GitHub publish is staged into the clone (the cloud proxy only allows git push, not API writes);
one local commit at the end unless --trial (weekly.sh pushes it after the Drive write-back)."""
import sys, os, re, glob, types, argparse, json, time, shutil, subprocess
KDB = '/content/drive/MyDrive/keiba_db'
ap = argparse.ArgumentParser()
ap.add_argument('--trial', action='store_true')
ap.add_argument('--date', help='race weekend start YYYYMMDD (default: newest 成績フルセット)')
ap.add_argument('--steps', default='gov,import,rebuild,review')
ap.add_argument('--site', default='/home/user/keiba-dashboard')
a = ap.parse_args()
os.chdir(KDB)

# --- Colab stand-ins ---
colab = types.ModuleType('google.colab'); colab.drive = types.SimpleNamespace(mount=lambda *x, **k: print('[runner] drive.mount skipped (local mirror)'))
sys.modules['google.colab'] = colab
import getpass; getpass.getpass = lambda prompt='': 'PROXY-AUTH'  # the session proxy authenticates GitHub
STAGED = []
import github as _gh
class _ReadOnlyRepo:
    """Reads pass through; any API write raises so a missed publish path can never half-publish."""
    def __init__(self, real): self._real = real
    def __getattr__(self, n):
        if n.startswith(('create_', 'update_', 'delete_', 'edit')) or n == 'merge':
            raise RuntimeError(f'[runner] blocked direct GitHub API write: repo.{n}')
        return getattr(self._real, n)
_RealGithub = _gh.Github
class _ProxyGithub:
    def __init__(self, *x, **k): self._g = _RealGithub()
    def get_repo(self, name): return _ReadOnlyRepo(self._g.get_repo(name))
_gh.Github = _ProxyGithub

ns = {'__name__': '__main__'}
t0 = time.time()
code = open(f'{KDB}/keiba_dashboard_full_restore_v7.py', encoding='utf-8').read()
exec(compile(code, 'keiba_dashboard_full_restore_v7.py', 'exec'), ns)
print(f'[runner] restore_v7 loaded in {time.time()-t0:.0f}s')
def _stage_bytes(github_filename, data):
    dst = os.path.join(a.site, github_filename); os.makedirs(os.path.dirname(dst) or a.site, exist_ok=True)
    with open(dst, 'wb') as f: f.write(data)
    STAGED.append(github_filename); print(f'[runner] staged: {github_filename} ({len(data)/1e6:.2f}MB)')
def _stage_file(*x, **k):
    # restore_v7 calls these with local_html_path= or local_path=, positionally or by keyword
    path = k.get('local_html_path') or k.get('local_path') or x[0]
    name = k.get('github_filename') or (x[1] if len(x) > 1 else 'index.html')
    _stage_bytes(name, open(path, 'rb').read())
def _stage_batch(files, commit_message, *x, **k):
    for path, text in files.items(): _stage_bytes(path, text.encode('utf-8') if isinstance(text, str) else text)
for fn in ('upload_to_github', 'upload_to_github_v2', 'upload_large_file_via_git_clone', 'upload_binary_to_github'):
    ns[fn] = _stage_file
ns['upload_files_batch_to_github'] = _stage_batch


def import_missing_venue_days(race_csv, horse_csv):
    """Import (date, venue) pairs missing from the DB. import_new_race_data() only checks dates, so a venue
    exported in a separate file (e.g. 成績フルセット20261024（新潟）.csv) is skipped once its dates exist.
    Same transforms as import_new_race_data()."""
    import pandas as pd
    con = ns['con']
    dr = pd.read_csv(race_csv, encoding='cp932', header=None)
    dh = pd.read_csv(horse_csv, encoding='cp932', header=None)
    dr = dr[pd.to_numeric(dr[0], errors='coerce').notna()].copy()
    dh = dh[pd.to_numeric(dh[0], errors='coerce').notna()].copy()
    dr['k'] = list(zip(dr[0].astype(int), dr[1].astype(int), dr[2].astype(int), dr[3].astype(str).str.strip()))
    dh['k'] = list(zip(dh[0].astype(int) % 100 + 2000, dh[1].astype(int), dh[2].astype(int), dh[4].astype(str).str.strip()))
    have = set(map(tuple, con.execute("""SELECT DISTINCT CAST(column00 AS INTEGER), CAST(column01 AS INTEGER),
        CAST(column02 AS INTEGER), TRIM(CAST(column03 AS VARCHAR)) FROM race_summary_full""").fetchall()))
    missing = sorted(set(dr['k']) - have)
    print(f'[runner] 未登録の(日付,会場): {missing}')
    if not missing: return 0
    if 'clear_race_trend_cache' in ns: ns['clear_race_trend_cache']()
    r = dr[dr['k'].isin(missing)].drop(columns=['k']).reset_index(drop=True)
    r.columns = [f'column{str(i).zfill(2)}' for i in range(r.shape[1])]
    r['column12'] = r['column12'].apply(ns['convert_date_format'])
    h = dh[dh['k'].isin(missing)].drop(columns=['k']).reset_index(drop=True)
    ncol = con.execute("SELECT * FROM horse_race_full LIMIT 1").df().shape[1]
    h = h.iloc[:, :ncol]
    for i in range(h.shape[1], ncol): h[i] = None
    h.columns = [f'column{str(i).zfill(2)}' for i in range(h.shape[1])]
    con.register('_rv', r); con.execute("INSERT INTO race_summary_full SELECT * FROM _rv")
    con.register('_hv', h); con.execute("INSERT INTO horse_race_full SELECT * FROM _hv")
    print(f'[runner] 会場別の追加取り込み: レース {len(r)}件 / 馬 {len(h)}件')
    return len(h)

try:
    ns['_RACE_ARCHIVE_KEYS_CACHE'] = set(json.load(open(os.path.join(a.site, 'race_archive.json'), encoding='utf-8')).keys())
    print(f"[runner] race_archive keys from clone: {len(ns['_RACE_ARCHIVE_KEYS_CACHE'])}")
except Exception as e:
    sys.exit(f'[runner] cannot read race_archive.json from site clone: {e}')

def pairs_for(date):
    races = sorted(glob.glob(f'{KDB}/成績フルセット{date}*.csv'))
    horses = sorted(glob.glob(f'{KDB}/馬別フルセット{date}*.csv'))
    return races, horses
if not a.date:
    ds = sorted({m.group(1) for f in glob.glob(f'{KDB}/成績フルセット*.csv') if (m := re.match(r'.*成績フルセット(\d{8})', f))})
    a.date = ds[-1]
races, horses = pairs_for(a.date)
print(f'[runner] target {a.date}: races={[os.path.basename(x) for x in races]} horses={[os.path.basename(x) for x in horses]}')
steps = a.steps.split(',')
RESULT = {'date': a.date, 'trial': a.trial}

if 'gov' in steps or 'import' in steps:
    RESULT['gov_before_issue'] = bool(ns['run_data_governance_check']())
if 'import' in steps:
    import pandas as pd
    n0 = ns['con'].execute('select count(*) from horse_race_full').fetchone()[0]
    main = [i for i, f in enumerate(races) if '（' not in os.path.basename(f)] or [0]
    ns['import_new_race_data'](race_csv_path=races[main[0]], horse_csv_path=horses[main[0]])
    for rf, hf in zip(races, horses):  # venue-split files and anything the date check skipped
        import_missing_venue_days(rf, hf)
    n1 = ns['con'].execute('select count(*) from horse_race_full').fetchone()[0]
    RESULT['imported_rows'] = n1 - n0
    RESULT['gov_after_issue'] = bool(ns['run_data_governance_check']())
if 'rebuild' in steps:
    t = time.time(); ns['rebuild_all_derived_data'](); RESULT['rebuild_sec'] = round(time.time() - t)
if 'review' in steps:
    import pandas as pd, datetime as dt
    d0 = dt.date(int(a.date[:4]), int(a.date[4:6]), int(a.date[6:]))
    RESULT['review'] = {}
    for d in [d0 + dt.timedelta(days=i) for i in range(4)]:
        ymd = d.strftime('%Y%m%d'); p = f"{KDB}/prediction_log_{d.strftime('%y%m%d')}.parquet"
        if not os.path.exists(p): continue
        ns['review_and_record_weekly_accuracy'](pd.read_parquet(p), ymd)
        RESULT['review'][ymd] = 'recorded'
ns['con'].execute('CHECKPOINT'); ns['con'].close()
def git(*args): return subprocess.run(['git', '-C', a.site, *args], capture_output=True, text=True)
RESULT['staged_files'] = len(set(STAGED))
changed = [l[3:] for l in git('status', '--porcelain').stdout.splitlines()]
RESULT['site_changed_files'] = len(changed)
RESULT['site_changed_sample'] = changed[:30]
if changed and not a.trial:
    git('add', '-A')
    c = git('commit', '-m', f'weekly update {a.date} (cloud)')
    RESULT['committed'] = c.returncode == 0  # pushed by weekly.sh only after the Drive write-back succeeds
print('[runner] RESULT ' + json.dumps(RESULT, ensure_ascii=False))
