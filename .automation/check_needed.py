"""Decide whether a weekly run is needed: is any (date, venue) in the newest 成績フルセット files missing from the DB?
Prints 'NEED <YYYYMMDD>' or 'NONE <reason>'. Read-only."""
import sys, os, re, io, tempfile, shutil
sys.path.insert(0, os.path.dirname(__file__)); import gdrive
import pandas as pd, duckdb
s = gdrive.svc(); fs = gdrive.list_folder(s)
races = [f for f in fs if re.match(r'成績フルセット(\d{8})', f['name'])]
if not races: print('NONE no 成績フルセット files'); sys.exit()
date = max(re.match(r'成績フルセット(\d{8})', f['name']).group(1) for f in races)
tmp = tempfile.mkdtemp()
for f in fs:
    if f['name'] in ('keiba.duckdb', 'keiba.duckdb.wal'): gdrive.download(s, f['id'], os.path.join(tmp, f['name']))
pairs = set()
for f in races:
    if f['name'].startswith(f'成績フルセット{date}'):
        p = os.path.join(tmp, 'r.csv'); gdrive.download(s, f['id'], p)
        d = pd.read_csv(p, encoding='cp932', header=None); d = d[pd.to_numeric(d[0], errors='coerce').notna()]
        pairs |= set(zip(d[0].astype(int), d[1].astype(int), d[2].astype(int), d[3].astype(str).str.strip()))
horse_ok = any(f['name'].startswith(f'馬別フルセット{date}') for f in fs)
con = duckdb.connect(os.path.join(tmp, 'keiba.duckdb'))
have = set(map(tuple, con.execute("""SELECT DISTINCT CAST(column00 AS INTEGER), CAST(column01 AS INTEGER),
    CAST(column02 AS INTEGER), TRIM(CAST(column03 AS VARCHAR)) FROM race_summary_full""").fetchall()))
con.close(); shutil.rmtree(tmp)
missing = sorted(pairs - have)
if not missing: print(f'NONE {date} already in DB')
elif not horse_ok: print(f'NONE {date} waiting for 馬別フルセット (missing {missing})')
else: print(f'NEED {date} missing={missing}')
