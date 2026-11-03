"""地方ダートグレード（交流重賞）の自動予想・答え合わせ。auto.sh から呼ばれる（restore_v7 は使わない）。
  前日〜当日: 出馬表が出ていれば出走馬の過去の地方戦を keiba.duckdb に取り込み → AF換算 → 予想（当日はオッズ込み）
  翌日以降（当日21時以降も）: 結果を取り込み → 答え合わせ（nar_verify）
  毎回: 公開ページ nar.html を作り直す
python3 nar_runner.py --db <keiba.duckdb> --site <clone> [--trial] [--today YYYYMMDD] [--seed parsed.json.gz races.json]"""
import sys, os, argparse, json, gzip, subprocess, html, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import duckdb, nar_lib as L

ap = argparse.ArgumentParser()
ap.add_argument('--db', default='/content/drive/MyDrive/keiba_db/keiba.duckdb')
ap.add_argument('--site', default='/home/user/keiba-dashboard')
ap.add_argument('--trial', action='store_true')
ap.add_argument('--today')
ap.add_argument('--seed', nargs=2, metavar=('PARSED_GZ', 'RACES_JSON'), help='one-off import of the 2026-11-03 backtest data')
a = ap.parse_args()
NOW = L.now()
today = a.today or NOW.strftime('%Y%m%d')
def shift(d, n): return (dt.date(int(d[:4]), int(d[4:6]), int(d[6:])) + dt.timedelta(days=n)).strftime('%Y%m%d')
con = duckdb.connect(a.db); L.init(con)
import atexit
def _close():  # always checkpoint, so writeback never sees a half-written WAL even if a fetch step crashed
    try: con.execute('CHECKPOINT'); con.close()
    except Exception: pass
atexit.register(_close)
RESULT = {'today': today, 'trial': a.trial, 'predicted': [], 'verified': [], 'new_nar_races': 0}

if a.seed:
    P = json.load(gzip.open(a.seed[0], 'rt', encoding='utf-8'))
    G = {r['race_id'] for r in json.load(open(a.seed[1], encoding='utf-8')) if r.get('race_id')}
    for rid, r in P.items():
        if L.have_race(con, rid) or not r['date']: continue
        race = dict(race_id=rid, date=r['date'], venue_code=r['venue'], name=r['name'], surface=r['surf'],
                    distance=r['dist'], baba=r['baba'], laps=json.dumps(r['laps']))
        rows = [dict(race_id=rid, pos=x['pos'], horse=x['name'], horse_id=x['hid'], time_sec=x['t'], odds=x['odds'],
                     popularity=int(x['pop']) if x['pop'] else None) for x in r['rows']]
        L.store_race(con, race, rows, rid in G)
    RESULT['seeded'] = con.execute('SELECT count(*) FROM nar_races').fetchone()[0]

# schedule (this year, plus next year in December)
years = {today[:4]} | ({str(int(today[:4]) + 1)} if today[4:6] == '12' else set())
for y in sorted(years):
    for r in L.schedule(y):
        con.execute('INSERT INTO nar_grade_schedule VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING',
                    [None, r['date'], r['name'], r['venue'], r['distance']])
window = con.execute('SELECT date, name, venue, distance, race_id FROM nar_grade_schedule WHERE date BETWEEN ? AND ? ORDER BY date',
                     [shift(today, -3), shift(today, 1)]).fetchall()
for d, nm, v, dist, rid in window:
    if rid: continue
    rid = L.find_race_id(dict(date=d, name=nm, distance=dist))
    if rid: con.execute('UPDATE nar_grade_schedule SET race_id=? WHERE date=? AND name=?', [rid, d, nm])
window = con.execute('SELECT date, name, venue, distance, race_id FROM nar_grade_schedule WHERE date BETWEEN ? AND ? AND race_id IS NOT NULL ORDER BY date',
                     [shift(today, -3), shift(today, 1)]).fetchall()

# results + verification (past days, or today after 21:00 JST)
for d, nm, v, dist, rid in window:
    if d > today or (d == today and NOW.hour < 21): continue
    if not L.have_race(con, rid) and L.ingest_race(con, rid, graded=True):
        con.execute('UPDATE nar_races SET graded=TRUE WHERE race_id=?', [rid])
    if L.have_race(con, rid) and not con.execute('SELECT count(*) FROM nar_verify WHERE race_id=?', [rid]).fetchone()[0]:
        row = L.verify(con, rid)
        if row: RESULT['verified'].append(dict(race=nm, honmei=row[3], pos=row[4], marks_top3=row[6], winner=row[7], winner_mark=row[8]))

# predictions (tomorrow = 前日版, today until post time = オッズ版)
todo = [(d, nm, v, dist, rid) for d, nm, v, dist, rid in window if d >= today and not L.have_race(con, rid)]
entries = {}
for d, nm, v, dist, rid in todo:
    e, post = L.shutuba(rid)
    if not e: print(f'[nar] {nm}: 出馬表なし'); continue
    if d == today and post and NOW.strftime('%H:%M') >= post:  # keep the last pre-race prediction for verification
        print(f'[nar] {nm}: 発走{post}を過ぎたので予想は更新しない'); continue
    entries[rid] = e
    made = con.execute('SELECT max(made_at) FROM nar_predictions WHERE race_id=?', [rid]).fetchone()[0]
    if made is None or made.strftime('%Y%m%d') < today:  # refresh each runner's NAR history once a day
        n = L.collect_history(con, e, d); RESULT['new_nar_races'] += n; print(f'[nar] {nm}: 地方戦 {n} レース取り込み')
if entries:
    R = L.Ratings(con, a.site)
    for d, nm, v, dist, rid in todo:
        if rid not in entries: continue
        status, om = L.odds(rid) if d == today else (None, {})
        rows, used = L.predict(entries[rid], R, d, dist, om)
        L.store_prediction(con, rid, rows, status if used else 'none')
        RESULT['predicted'].append(dict(race=nm, date=d, odds=status if used else 'none',
                                        marks={r['mark']: r['horse'] for r in rows if r['mark'] in ('◎', '○', '▲')},
                                        unrated=sum(r['af'] is None for r in rows)))

# ---------------- page ----------------
VN = {'30': '門別', '35': '盛岡', '36': '水沢', '42': '浦和', '43': '船橋', '44': '大井', '45': '川崎', '46': '金沢',
      '47': '笠松', '48': '名古屋', '50': '園田', '51': '姫路', '54': '高知', '55': '佐賀'}
e = html.escape
def f(x, n=2): return '' if x is None else f'{x:.{n}f}'
sch = con.execute("""SELECT s.date, s.name, s.venue, s.distance, s.race_id FROM nar_grade_schedule s
    WHERE s.race_id IN (SELECT race_id FROM nar_predictions) ORDER BY s.date DESC""").fetchall()
cards = []
for d, nm, v, dist, rid in sch:
    pr = con.execute("""SELECT p.umaban, p.mark, p.horse, p.af, p.af_all, p.n_runs, p.odds, p.popularity, p.p_win, p.p_place,
        r.pos, p.odds_status, p.made_at FROM nar_predictions p LEFT JOIN nar_results r ON r.race_id=p.race_id AND r.horse_id=p.horse_id
        WHERE p.race_id=? ORDER BY p.p_win DESC""", [rid]).fetchall()
    vf = con.execute('SELECT honmei, honmei_pos, marks_top3, winner, winner_mark FROM nar_verify WHERE race_id=?', [rid]).fetchone()
    ost = pr[0][11]; made = pr[0][12]
    head = f'{d[:4]}/{d[4:6]}/{d[6:]} {e(v)} ダ{dist}m <b>{e(nm)}</b>'
    sub = (f'オッズ込み（{made:%m/%d %H:%M}時点）' if ost not in (None, 'none') else f'前日版・オッズなし（{made:%m/%d %H:%M}作成）')
    res = (f'<div class="res">結果: 1着 {e(vf[3] or "")}（{e(vf[4] or "無印")}）／◎{e(vf[0] or "")} {vf[1] or "-"}着／印馬の3着内 {vf[2]}頭</div>' if vf else '')
    trs = ''.join(f'<tr><td>{u}</td><td class="mk">{e(m or "")}</td><td class="n">{e(h)}</td><td>{f(af)}</td><td>{f(aa)}</td><td>{n}</td>'
                  f'<td>{f(o,1)}</td><td>{pp or ""}</td><td>{f(pw*100,1)}%</td><td>{f(pl*100,1)}%</td><td>{pos or ""}</td></tr>'
                  for u, m, h, af, aa, n, o, pp, pw, pl, pos, _, _ in pr)
    cards.append(f'<section><h2>{head}</h2><div class="note">{sub}</div>{res}<div class="wrap"><table><tr><th>馬番</th><th>印</th><th>馬名</th>'
                 f'<th>AF(距離)</th><th>AF(全)</th><th>走数</th><th>単勝</th><th>人気</th><th>勝率</th><th>複勝率</th><th>着</th></tr>{trs}</table></div></section>')
vs = con.execute('SELECT count(*), sum(honmei_pos=1), sum(honmei_pos<=3), sum(CASE WHEN honmei_pos=1 THEN honmei_odds ELSE 0 END) FROM nar_verify').fetchone()
summary = (f'これまでの成績（自動予想を出したレース）: {vs[0]}レース、◎ 勝率 {vs[1]/vs[0]*100:.0f}%・複勝率 {vs[2]/vs[0]*100:.0f}%・単勝回収率 {vs[3]/vs[0]*100:.0f}%'
           if vs[0] else 'これまでの成績: まだ答え合わせしたレースがありません。')
page = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>地方ダートグレード予想</title><style>
body{{font-family:sans-serif;margin:0;padding:12px 16px;background:#fff;color:#111;max-width:820px}}
h1{{font-size:18px;margin:4px 0}} h2{{font-size:15px;margin:18px 0 4px}} .note{{font-size:12px;color:#555;line-height:1.6}}
.res{{font-size:13px;background:#eef6ee;border-radius:6px;padding:6px 8px;margin:6px 0}}
table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{border-bottom:1px solid #ddd;padding:6px 4px;text-align:left;white-space:nowrap}}
td.n{{white-space:normal}} td.mk{{font-weight:bold;color:#c00}} th{{background:#111;color:#fff}} .wrap{{overflow-x:auto}}
</style></head><body><a href="index.html" style="font-size:12px;">← ダッシュボード</a>
<h1>地方ダートグレード予想（交流重賞）</h1>
<div class="note">地方戦のAFは、同じレースに出たJRA馬のAFを基準に着差から換算しています（小さいほど強い）。AF(距離)は今回の距離±300mの走り、AF(全)は全距離の評価です（直近1年・5走のうち良い3走の平均）。
勝率はオッズとAFを組み合わせた推定値で、前日版はAFだけの推定です。印: ◎勝率最大・○複勝率最大・▲指数2位以内の6番人気以下（いなければ複勝率順）・△その次。<br>{summary}</div>
{''.join(cards) or '<p class="note">予想を出したレースはまだありません。</p>'}
<div class="note">更新 {NOW:%Y/%m/%d %H:%M}</div></body></html>"""
out = os.path.join(a.site, 'nar.html')
old = open(out, encoding='utf-8').read() if os.path.exists(out) else ''
import re as _re
strip = lambda s: _re.sub(r'更新 \d{4}/\d\d/\d\d \d\d:\d\d', '', s)
if cards and strip(old) != strip(page): open(out, 'w', encoding='utf-8').write(page); RESULT['page'] = 'nar.html'

_close()
def git(*x): return subprocess.run(['git', '-C', a.site, *x], capture_output=True, text=True)
if RESULT.get('page') and not a.trial:
    git('add', 'nar.html'); RESULT['committed'] = git('commit', '-m', f'nar grade predictions {today} (cloud)').returncode == 0
print('[runner] RESULT ' + json.dumps(RESULT, ensure_ascii=False))
