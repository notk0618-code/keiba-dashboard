"""地方ダートグレード（交流重賞）予想: データ取得・keiba.duckdb への保存・JRAスケールのAF換算・予想。

AF換算（2026-11-03 バックテスト 126レースで決定）:
  地方戦AF = アンカー + C×(勝ち馬とのタイム差秒)、C=0.9
  アンカー = 着差2秒以内のJRA評価馬について (JRAダートAF評価 − C×タイム差) の中央値（3頭以上）。
             3頭未満なら地方換算済みの評価も使う（2頭以上）。レースは日付順に処理するので評価は連鎖する。
  馬の評価 = 直近365日・直近5走（JRAダート＋地方換算）のうち、対象距離±300mの走りの良い3走平均
             （その距離の走りが無ければ全距離で同じ計算）。AFは小さいほど強い。
  勝率 = 市場確率^0.7 × exp(−0.19×(AF−出走馬の中央値)) を正規化（オッズが無いときは softmax(−AF/0.8)）。
データ源: 日程 keiba.go.jp/dirtgraderace、出馬表・オッズ nar.netkeiba.com、結果・戦績 db.netkeiba.com（EUC-JP）。"""
import re, json, time, math, statistics as st, datetime as dt, subprocess, os
from bs4 import BeautifulSoup

UA = 'Mozilla/5.0'
JRA_VENUES = {'東京', '中山', '京都', '阪神', '中京', '新潟', '福島', '札幌', '函館', '小倉'}
JRA_CODES = {f'{i:02d}' for i in range(1, 11)}
C, WIN, N, K, MAXD, MINJ, DIST_BAND = 0.9, 365, 5, 3, 2.0, 3, 300
A_MKT, B_AF, T_MODEL = 0.7, 0.19, 0.8
HIST_DAYS = 400  # how far back to collect each runner's NAR runs
JST = dt.timezone(dt.timedelta(hours=9))

SCHEMA = """
CREATE TABLE IF NOT EXISTS nar_races (race_id VARCHAR PRIMARY KEY, date VARCHAR, venue_code VARCHAR, name VARCHAR,
  surface VARCHAR, distance INTEGER, baba VARCHAR, laps VARCHAR, graded BOOLEAN, fetched_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS nar_results (race_id VARCHAR, pos INTEGER, horse VARCHAR, horse_id VARCHAR, time_sec DOUBLE,
  odds DOUBLE, popularity INTEGER, PRIMARY KEY (race_id, horse_id));
CREATE TABLE IF NOT EXISTS nar_grade_schedule (race_id VARCHAR, date VARCHAR, name VARCHAR, venue VARCHAR, distance INTEGER,
  PRIMARY KEY (date, name));
CREATE TABLE IF NOT EXISTS nar_predictions (race_id VARCHAR, made_at TIMESTAMP, odds_status VARCHAR, umaban INTEGER,
  horse VARCHAR, horse_id VARCHAR, af DOUBLE, af_all DOUBLE, n_runs INTEGER, odds DOUBLE, popularity INTEGER,
  p_win DOUBLE, p_place DOUBLE, mark VARCHAR, PRIMARY KEY (race_id, horse_id));
CREATE TABLE IF NOT EXISTS nar_verify (race_id VARCHAR PRIMARY KEY, date VARCHAR, name VARCHAR, honmei VARCHAR,
  honmei_pos INTEGER, honmei_odds DOUBLE, marks_top3 INTEGER, winner VARCHAR, winner_mark VARCHAR, checked_at TIMESTAMP);
"""


def now(): return dt.datetime.now(JST).replace(tzinfo=None)


def fetch(url, enc='utf-8', minsize=5000, tries=4):
    """netkeiba sometimes returns empty bodies under load, so fetch slowly and retry."""
    for i in range(tries):
        r = subprocess.run(['curl', '-s', '-L', '-m', '25', '-A', UA, url], capture_output=True)
        time.sleep(1.2 + 2 * i)
        if len(r.stdout) >= minsize: return r.stdout.decode(enc, 'ignore')
    return None


def tsec(x):
    m = re.match(r'(\d+):(\d+\.\d)', x or '')
    if m: return int(m.group(1)) * 60 + float(m.group(2))
    try: return float(x)
    except Exception: return None


def fnum(x):
    try: return float(str(x).replace(',', ''))
    except Exception: return None


def days(a, b):
    return (dt.date(int(a[:4]), int(a[4:6]), int(a[6:])) - dt.date(int(b[:4]), int(b[4:6]), int(b[6:]))).days


# ---------------- schedule ----------------
def schedule(year):
    """Graded dirt races held at NAR tracks in `year`: [{date, name, venue, distance}]."""
    t = fetch(f'https://www.keiba.go.jp/dirtgraderace/{year}/racelist/index.html')
    if not t: return []
    s = re.sub(r'\s+', ' ', re.sub(r'<script.*?</script>|<[^>]+>', ' ', t, flags=re.S))
    out = []
    for m in re.finditer(r'(\d+)月(\d+)日\([^)]*\) (\S+) (\S+) [右左直](\d+)m', s):
        mo, d, nm, v, dist = m.groups()
        if v not in JRA_VENUES:
            out.append(dict(date=f'{year}{int(mo):02d}{int(d):02d}', name=nm, venue=v, distance=int(dist)))
    return out


def find_race_id(r):
    """Match a schedule row to its nar.netkeiba race_id via that day's race list (grade label + distance + name)."""
    t = fetch(f"https://nar.netkeiba.com/top/race_list_sub.html?kaisai_date={r['date']}")
    if not t: return None
    cands = []
    for m in re.finditer(r'race_id=(\d+)[^>]*>(.*?)</a>', t, re.S):
        x = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', m.group(2))).strip()
        if re.search(r'Jpn|GI', x) and f"{r['distance']}m" in x: cands.append((m.group(1), x))
    nm = r['name'].replace('JBC', '')
    key = nm[:3]
    zen = key.translate(str.maketrans('0123456789', '０１２３４５６７８９'))
    best = [c for c in cands if key in c[1] or zen in c[1]] or cands
    return best[0][0] if best else None


# ---------------- parsing ----------------
def parse_result(rid, html):
    """db.netkeiba.com race page -> (race row, result rows)."""
    s = BeautifulSoup(html, 'lxml')
    tb = s.select_one('table.race_table_01')
    if not tb: return None, []
    intro = s.select_one('div.data_intro'); it = intro.text if intro else ''
    m = re.search(r'(芝|ダ)[^\d]{0,4}(\d+)m', it)
    d = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', s.text)
    nm = s.select_one('div.data_intro h1')
    lap = re.search(r'ラップ\s*([\d\.\s\-]+)', s.text)
    race = dict(race_id=rid, date=f'{d.group(1)}{int(d.group(2)):02d}{int(d.group(3)):02d}' if d else None,
                venue_code=rid[4:6], name=nm.text.strip() if nm else rid, surface=m.group(1) if m else None,
                distance=int(m.group(2)) if m else None,
                baba=(re.search(r'(?:ダート|芝) : (\S)', it) or [None, None])[1],
                laps=json.dumps([float(x) for x in re.findall(r'\d+\.\d', lap.group(1))]) if lap else '[]')
    rows = []
    for tr in tb.select('tr')[1:]:
        td = [c.text.strip() for c in tr.select('td')]
        a = tr.select_one('a[href*="/horse/"]')
        if not a or len(td) < 18: continue
        rows.append(dict(race_id=rid, pos=int(td[0]) if td[0].isdigit() else None, horse=td[3],
                         horse_id=re.search(r'horse/(\w+)', a['href']).group(1), time_sec=tsec(td[7]),
                         odds=fnum(td[16]), popularity=int(fnum(td[17])) if fnum(td[17]) else None))
    return race, rows


def horse_nar_runs(hid):
    """[(date, race_id)] of a horse's NAR runs from its db.netkeiba result page."""
    t = fetch(f'https://db.netkeiba.com/horse/result/{hid}/', enc='euc-jp', minsize=20000)
    if not t: return None
    return [(y + m + d, rid) for y, m, d, rid in re.findall(r'(\d{4})/(\d{2})/(\d{2}).*?/race/(\d{12})/', t, re.S)
            if rid[4:6] not in JRA_CODES]


def shutuba(rid):
    """nar.netkeiba entries: ([{umaban, horse, horse_id}], 'HH:MM' post time or None); empty until the card is out."""
    t = fetch(f'https://nar.netkeiba.com/race/shutuba.html?race_id={rid}')
    if not t: return [], None
    s = BeautifulSoup(t, 'lxml'); out = []
    rd = s.select_one('.RaceData01'); pm = re.search(r'(\d{1,2}:\d{2})発走', rd.text if rd else '')
    for tr in s.select('tr.HorseList'):
        td = [c.text.strip() for c in tr.select('td')]
        a = tr.select_one('a[href*="/horse/"]')
        if not a or len(td) < 4 or not td[1].isdigit(): continue
        if '取消' in tr.text or '除外' in tr.text: continue
        out.append(dict(umaban=int(td[1]), horse=a.text.strip() or td[3], horse_id=re.search(r'horse/(\w+)', a['href']).group(1)))
    return out, pm.group(1) if pm else None


def odds(rid):
    t = fetch(f'https://nar.netkeiba.com/api/api_get_nar_odds.html?race_id={rid}&type=1&action=update', minsize=20)
    try:
        j = json.loads(t)
        o = {int(k): (fnum(v.get('Odds')), v.get('Ninki')) for k, v in (j.get('ary_odds') or {}).items()}
        return j.get('odds_status'), {k: v for k, v in o.items() if v[0]}
    except Exception:
        return None, {}


# ---------------- DB ----------------
def init(con):
    for q in SCHEMA.strip().split(';'):
        if q.strip(): con.execute(q)


def have_race(con, rid):
    return con.execute('SELECT count(*) FROM nar_results WHERE race_id=?', [rid]).fetchone()[0] > 0


def store_race(con, race, rows, graded=False):
    con.execute('DELETE FROM nar_races WHERE race_id=?', [race['race_id']])
    con.execute('DELETE FROM nar_results WHERE race_id=?', [race['race_id']])
    con.execute('INSERT INTO nar_races VALUES (?,?,?,?,?,?,?,?,?,?)',
                [race['race_id'], race['date'], race['venue_code'], race['name'], race['surface'], race['distance'],
                 race['baba'], race['laps'], graded, now()])
    seen = set()
    for r in rows:
        if r['horse_id'] in seen: continue
        seen.add(r['horse_id'])
        con.execute('INSERT INTO nar_results VALUES (?,?,?,?,?,?,?)',
                    [r['race_id'], r['pos'], r['horse'], r['horse_id'], r['time_sec'], r['odds'], r['popularity']])


def ingest_race(con, rid, graded=False, log=print):
    html = fetch(f'https://db.netkeiba.com/race/{rid}/', enc='euc-jp', minsize=20000)
    if not html: log(f'[nar] fetch failed {rid}'); return False
    race, rows = parse_result(rid, html)
    if not race or not rows: return False
    store_race(con, race, rows, graded); return True


def collect_history(con, entries, race_date, log=print):
    """Store every NAR run of the entries within HIST_DAYS before the race (skips races already stored)."""
    new = 0
    for e in entries:
        runs = horse_nar_runs(e['horse_id'])
        if runs is None: log(f"[nar] horse page failed {e['horse']}"); continue
        for d, rid in runs:
            if d < race_date and days(race_date, d) <= HIST_DAYS and not have_race(con, rid):
                new += ingest_race(con, rid, log=log)
    return new


# ---------------- ratings ----------------
def load_jra(site):
    JR = {}
    for f in ('horse_data.json', 'horse_data_archive.json'):
        p = os.path.join(site, f)
        if not os.path.exists(p): continue
        for h, v in json.load(open(p, encoding='utf-8')).items():
            for r in v:
                if r[7] == 'ダート' and r[8] is not None: JR.setdefault(h, []).append((r[0].replace('-', ''), r[8], r[2]))
    return JR


class Ratings:
    def __init__(self, con, site):
        self.JR = load_jra(site); self.NAR = {}; self.anchor = {}
        races = con.execute("""SELECT race_id, date, distance FROM nar_races WHERE surface='ダ' AND date IS NOT NULL
                               ORDER BY date, race_id""").fetchall()
        res = {}
        for rid, h, t in con.execute('SELECT race_id, horse, time_sec FROM nar_results WHERE time_sec IS NOT NULL').fetchall():
            res.setdefault(rid, []).append((h, t))
        for rid, d, dist in races:
            rows = res.get(rid)
            if not rows: continue
            t0 = min(t for _, t in rows)
            aj = [self.rating(h, d, True) for h, _ in rows]
            aj = [a - C * (t - t0) for a, (h, t) in zip(aj, rows) if a is not None and t - t0 < MAXD]
            if len(aj) >= MINJ: anc = aj
            else:
                al = [self.rating(h, d) for h, _ in rows]
                anc = [a - C * (t - t0) for a, (h, t) in zip(al, rows) if a is not None and t - t0 < MAXD]
            if len(anc) < 2: continue
            a = st.median(anc); self.anchor[rid] = (a, len(anc), len(aj) >= MINJ)
            for h, t in rows: self.NAR.setdefault(h, []).append((d, a + C * (t - t0), dist))

    def runs(self, h, d, jra_only=False):
        rs = [x for x in self.JR.get(h, []) if x[0] < d and days(d, x[0]) <= WIN]
        if not jra_only: rs += [x for x in self.NAR.get(h, []) if x[0] < d and days(d, x[0]) <= WIN]
        return sorted(rs, reverse=True)[:N]

    def rating(self, h, d, jra_only=False, dist=None):
        rs = self.runs(h, d, jra_only)
        if not rs: return None
        if dist:
            near = [x[1] for x in rs if x[2] and abs(x[2] - dist) <= DIST_BAND]
            if near: v = sorted(near)[:K]; return sum(v) / len(v)
        v = sorted(x[1] for x in rs)[:K]; return sum(v) / len(v)


# ---------------- prediction ----------------
def harville_place(p, k=3):
    n = len(p); out = [0.0] * n
    def rec(prob, used, depth):
        if depth == k: return
        rest = 1 - sum(p[j] for j in used)
        for i in range(n):
            if i in used or rest <= 0: continue
            q = prob * p[i] / rest; out[i] += q
            if depth + 1 < k: rec(q, used | {i}, depth + 1)
    rec(1.0, frozenset(), 0)
    return out


def predict(entries, R, race_date, dist, odds_map):
    rows = []
    for e in entries:
        af = R.rating(e['horse'], race_date, dist=dist); af_all = R.rating(e['horse'], race_date)
        o, pop = odds_map.get(e['umaban'], (None, None))
        rows.append(dict(e, af=af, af_all=af_all, n_runs=len(R.runs(e['horse'], race_date)), odds=o, popularity=pop))
    rated = [r['af'] for r in rows if r['af'] is not None]
    med = st.median(rated) if rated else 0; fill = (max(rated) + 0.5) if rated else 0
    use_mkt = all(r['odds'] for r in rows)
    u = []
    for r in rows:
        x = (r['af'] if r['af'] is not None else fill) - med
        u.append(A_MKT * math.log(1 / r['odds']) - B_AF * x if use_mkt else -x / T_MODEL)
    mx = max(u); e = [math.exp(v - mx) for v in u]; s = sum(e)
    p = [v / s for v in e]; pl = harville_place(p)
    for r, a, b in zip(rows, p, pl): r['p_win'], r['p_place'] = a, b
    marks(rows)
    return rows, use_mkt


def marks(rows):
    """◎ 勝率最大 / ○ 残りで複勝率最大 / ▲ 指数2位以内・6番人気以下（無ければ複勝率3位）/ △ 次の2頭（複勝率順）。"""
    for r in rows: r['mark'] = ''
    if not rows: return
    by_af = sorted([r for r in rows if r['af'] is not None], key=lambda r: r['af'])
    af_rank = {id(r): i + 1 for i, r in enumerate(by_af)}
    hon = max(rows, key=lambda r: r['p_win']); hon['mark'] = '◎'
    rest = sorted([r for r in rows if not r['mark']], key=lambda r: -r['p_place'])
    if rest: rest[0]['mark'] = '○'
    ana = [r for r in rows if not r['mark'] and af_rank.get(id(r), 99) <= 2 and (r['popularity'] or 0) >= 6]
    ana.sort(key=lambda r: af_rank[id(r)])
    rest = sorted([r for r in rows if not r['mark']], key=lambda r: -r['p_place'])
    if ana: ana[0]['mark'] = '▲'
    elif rest: rest.pop(0)['mark'] = '▲'
    rest = [r for r in rest if not r['mark']]
    for r in rest[:2]: r['mark'] = '△'


def store_prediction(con, rid, rows, status):
    con.execute('DELETE FROM nar_predictions WHERE race_id=?', [rid])
    t = now()
    for r in rows:
        con.execute('INSERT INTO nar_predictions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    [rid, t, status, r['umaban'], r['horse'], r['horse_id'], r['af'], r['af_all'], r['n_runs'],
                     r['odds'], r['popularity'], r['p_win'], r['p_place'], r['mark']])


def verify(con, rid):
    pr = con.execute('SELECT horse_id, horse, mark FROM nar_predictions WHERE race_id=?', [rid]).fetchall()
    res = {h: (pos, o) for h, pos, o in con.execute('SELECT horse_id, pos, odds FROM nar_results WHERE race_id=?', [rid]).fetchall()}
    if not pr or not res: return None
    mk = {h: (n, m) for h, n, m in pr}
    hon = [h for h, (n, m) in mk.items() if m == '◎']
    win = [h for h, (p, o) in res.items() if p == 1]
    meta = con.execute('SELECT date, name FROM nar_races WHERE race_id=?', [rid]).fetchone()
    hp, ho = res.get(hon[0], (None, None)) if hon else (None, None)
    top3 = sum(1 for h, (n, m) in mk.items() if m and (res.get(h, (99,))[0] or 99) <= 3)
    row = [rid, meta[0], meta[1], mk[hon[0]][0] if hon else None, hp, ho, top3,
           con.execute('SELECT horse FROM nar_results WHERE race_id=? AND pos=1', [rid]).fetchone()[0] if win else None,
           mk.get(win[0], (None, ''))[1] if win else None, now()]
    con.execute('DELETE FROM nar_verify WHERE race_id=?', [rid])
    con.execute('INSERT INTO nar_verify VALUES (?,?,?,?,?,?,?,?,?,?)', row)
    return row
