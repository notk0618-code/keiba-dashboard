"""Monday step: make the weekly 成績フルセット/馬別フルセット from JRA's site when TARGET's files are not on Drive.
  python3 jra_weekly.py            -> build and upload (needs GOOGLE_OAUTH_JSON to create Drive files)
  python3 jra_weekly.py --dry-run  -> build into a temp folder only, upload nothing

1. The newest race weekend whose results are all published (every listed date is before today, JST, and JRA has no
   racing today) is found from JRA's result top page. Its first date names the files, as TARGET's do (成績フルセットYYYYMMDD).
2. If no 成績フルセットYYYYMMDD*.csv is on Drive yet, jra_results.py builds 成績フルセット/馬別フルセット
   YYYYMMDD_JRA.csv plus 払戻YYYYMMDD_JRA.csv (every bet type) and uploads them. The hourly plan then picks them up
   like a TARGET upload (check_needed → weekly_runner).
3. While TARGET is still exported in parallel: when both TARGET's and the JRA files exist for a weekend and there is
   no JRA照合YYYYMMDD.txt yet, both are compared column by column and the report is uploaded.
4. 特別登録: when JRA lists next weekend's special-race nominations and Drive has neither 特別登録YYYYMMDD*.csv nor
   当日出走馬YYYYMMDD*.csv for it, 特別登録YYYYMMDD_JRA.csv (TARGET's 33 columns) is built and uploaded; the hourly
   plan then runs 7-2 (暫定予想・カレンダー) on it as with TARGET's file.
Prints lines starting with [jra-weekly]."""
import sys, os, re, io, csv, json, tempfile, argparse, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gdrive, jra_results
JST = dt.timezone(dt.timedelta(hours=9))

def weekend(today):
    """Dates (YYYYMMDD) of the newest finished race weekend on the result top page, or []."""
    page = jra_results.get_s(jra_results.TOP)
    ds = sorted({c[-11:-3] for c in re.findall(r"pw01srl\d+/\w+", page)} , reverse=True)
    ds = [d for d in ds if d < today]
    if not ds: return []
    out = [ds[0]]
    for d in ds[1:]:
        gap = (dt.date.fromisoformat(f'{out[-1][:4]}-{out[-1][4:6]}-{out[-1][6:]}') - dt.date.fromisoformat(f'{d[:4]}-{d[4:6]}-{d[6:]}')).days
        if gap > 2: break
        out.append(d)
    return sorted(out)

def upload(s, path, name, mime='text/csv'):
    from googleapiclient.http import MediaFileUpload
    m = MediaFileUpload(path, mimetype=mime, resumable=True)
    req = s.files().create(body={'name': name, 'parents': [gdrive.FOLDER]}, media_body=m, supportsAllDrives=True); r = None
    while r is None: _, r = req.next_chunk(num_retries=5)

def compare(target_race, target_horse, jra_race, jra_horse):
    """Plain-text report of the columns where TARGET and the JRA build differ (both TARGET layouts)."""
    import pandas as pd
    def norm(v):
        v = '' if pd.isna(v) else str(v).strip().strip('　')
        try: return f'{float(v):.2f}'
        except ValueError: return v
    rd = lambda p: pd.read_csv(p, encoding='cp932', header=None, dtype=str, keep_default_na=False)
    rt, rj = rd(target_race), rd(jra_race)
    rt = rt[rt[0].str.fullmatch(r'\d{4}')]
    key = lambda d: d[0] + d[1].str.zfill(2) + d[2].str.zfill(2) + d[3].str.strip() + d[4].str.zfill(2)
    rt.index, rj.index = key(rt), key(rj)
    ht, hj = rd(target_horse), rd(jra_horse)
    ht, hj = ht[ht[0].str.fullmatch(r'\d+')], hj[hj[0].str.fullmatch(r'\d+')]
    hkey = lambda d: d[0].str.zfill(2) + d[1].str.zfill(2) + d[2].str.zfill(2) + d[4].str.strip() + d[6].str.zfill(2) + d[19].str.zfill(2)
    ht.index, hj.index = hkey(ht), hkey(hj)
    ht = ht[ht.index.isin(set(hj.index)) | ht.index.str[:6].isin(set(hj.index.str[:6]))]
    rt = rt[rt.index.str[:8].isin(set(rj.index.str[:8]))]
    lines = [f'レース: TARGET {len(rt)} / JRA {len(rj)} / 共通 {len(set(rt.index) & set(rj.index))}',
             f'馬: TARGET {len(ht)} / JRA {len(hj)} / 共通 {len(set(ht.index) & set(hj.index))}']
    names = jra_results.HORSE_HEADER
    for label, a, b, cols in (('成績', rt, rj, range(80)), ('馬別', ht, hj, range(56))):
        ix = sorted(set(a.index) & set(b.index)); bad_cols = 0
        for c in cols:
            if c >= a.shape[1] or c >= b.shape[1]: continue
            x, y = a.loc[ix, c].map(norm), b.loc[ix, c].map(norm); bad = x != y
            if bad.any():
                bad_cols += 1
                ex = '; '.join(f'{k}: {p!r}→{q!r}' for k, p, q in list(zip(x[bad].index, x[bad], y[bad]))[:3])
                lines.append(f'{label} {c}列({names[c] if label == "馬別" else c}) 不一致 {int(bad.sum())}/{len(ix)}  例 {ex}')
        lines.append(f'{label}: {len(list(cols))}列中 {len(list(cols)) - bad_cols}列が全行一致')
    return '\n'.join(lines)

def results_step(s, by, today, dry):
    """成績フルセット/馬別フルセット/払戻 for the last finished weekend (see module doc)."""
    a = argparse.Namespace(dry_run=dry)
    import jra_odds
    if jra_odds.meetings(today):  # racing today: the weekend is not over (Sunday, holiday Monday)
        print(f'[jra-weekly] racing today ({today}); weekend not finished'); return
    dates = weekend(today)
    if not dates: print('[jra-weekly] no finished weekend on JRA'); return
    d0 = dates[0]
    mine = {k: f'{k}{d0}_JRA.csv' for k in ('成績フルセット', '馬別フルセット', '払戻')}
    target = {k: sorted(n for n in by if re.fullmatch(rf'{k}{d0}(（[^）]+）)?\.csv', n)) for k in ('成績フルセット', '馬別フルセット')}
    if mine['成績フルセット'] in by:
        if target['成績フルセット'] and target['馬別フルセット'] and f'JRA照合{d0}.txt' not in by and not a.dry_run and gdrive.can_create():
            tmp = tempfile.mkdtemp(); p = {}
            for n in [target['成績フルセット'][0], target['馬別フルセット'][0], mine['成績フルセット'], mine['馬別フルセット']]:
                p[n] = os.path.join(tmp, n); gdrive.download(s, by[n]['id'], p[n])
            rep = compare(p[target['成績フルセット'][0]], p[target['馬別フルセット'][0]], p[mine['成績フルセット']], p[mine['馬別フルセット']])
            out = os.path.join(tmp, f'JRA照合{d0}.txt'); open(out, 'w', encoding='utf-8').write(rep + '\n')
            upload(s, out, f'JRA照合{d0}.txt', 'text/plain')
            print(f'[jra-weekly] {d0}: compared with TARGET → JRA照合{d0}.txt | ' + ' | '.join(l for l in rep.splitlines() if '全行一致' in l))
        else:
            print(f'[jra-weekly] {d0}: JRA files already on Drive')
        return
    if target['成績フルセット']:
        print(f'[jra-weekly] {d0}: TARGET files on Drive ({target["成績フルセット"][0]}); JRA build skipped'); return
    if not a.dry_run and not gdrive.can_create():
        print('[jra-weekly] GOOGLE_OAUTH_JSON がないためDriveに作成できません'); return
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, 'keiba.duckdb')
    for n in ('keiba.duckdb', 'keiba.duckdb.wal'):
        if n in by: gdrive.download(s, by[n]['id'], os.path.join(tmp, n))
    R, H, P = jra_results.collect(dates, db, log=lambda m: print(m, file=sys.stderr))
    for n in ('keiba.duckdb', 'keiba.duckdb.wal'):  # only needed for the name maps
        if os.path.exists(os.path.join(tmp, n)): os.remove(os.path.join(tmp, n))
    paths = jra_results.write(tmp, d0, R, H, P)
    if a.dry_run:
        print(f'[jra-weekly] {d0}: dry run, {len(R)} races / {len(H)} horses / {len(P)} payouts → {tmp}'); return
    live = {f['name'] for f in gdrive.list_folder(s)}
    if any(re.fullmatch(rf'成績フルセット{d0}.*\.csv', n) for n in live):
        print(f'[jra-weekly] {d0}: a 成績フルセット appeared on Drive meanwhile; nothing uploaded'); return
    for pth in [paths[2], paths[1], paths[0]]:  # 成績フルセット last: it is what the hourly plan looks for
        upload(s, pth, os.path.basename(pth))
    print(f'[jra-weekly] {d0}: uploaded {", ".join(os.path.basename(x) for x in paths)} ({len(R)} races / {len(H)} horses)')


def tokubetsu_step(s, by, today, dry):
    """特別登録YYYYMMDD_JRA.csv for the coming weekend, when Drive has neither a 特別登録 nor a 当日出走馬 for it."""
    import jra_results as jr
    codes = jr.tokubetsu_codes()
    ahead = sorted(d for d in codes if d >= today)
    if not ahead: print('[jra-weekly] 特別登録: JRAに今後の登録なし'); return
    d0 = ahead[0]
    if any(re.fullmatch(rf'特別登録{d0}.*\.csv', n) for n in by):
        print(f'[jra-weekly] 特別登録{d0}: already on Drive'); return
    if any(n.startswith(f'当日出走馬{d0}') for n in by):
        print(f'[jra-weekly] 特別登録{d0}: 当日出走馬 already there; not needed'); return
    if not dry and not gdrive.can_create():
        print('[jra-weekly] GOOGLE_OAUTH_JSON がないためDriveに作成できません'); return
    tmp = tempfile.mkdtemp(); db = os.path.join(tmp, 'keiba.duckdb')
    for n in ('keiba.duckdb', 'keiba.duckdb.wal'):
        if n in by: gdrive.download(s, by[n]['id'], os.path.join(tmp, n))
    dates, rows = jr.collect_tokubetsu(db, log=lambda m: print(m, file=sys.stderr))
    for n in ('keiba.duckdb', 'keiba.duckdb.wal'):
        if os.path.exists(os.path.join(tmp, n)): os.remove(os.path.join(tmp, n))
    path = jr.write_tokubetsu(tmp, dates[0], rows)
    if dry: print(f'[jra-weekly] 特別登録{dates[0]}: dry run, {len(rows)} horses → {path}'); return
    upload(s, path, os.path.basename(path))
    print(f'[jra-weekly] uploaded {os.path.basename(path)} ({len(rows)} horses, {", ".join(dates)})')

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--dry-run', action='store_true'); a = ap.parse_args()
    today = dt.datetime.now(JST).strftime('%Y%m%d')
    s = gdrive.svc(); by = {f['name']: f for f in gdrive.list_folder(s)}
    for step in (results_step, tokubetsu_step):
        try: step(s, by, today, a.dry_run)
        except Exception as e: print(f'[jra-weekly] {step.__name__} failed: {e!r}')
