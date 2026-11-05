"""Build TARGET-format result files from JRA's official race-result pages (www.jra.go.jp/JRADB/accessS.html).
Read-only towards JRA; writes CSV files only.

  python3 jra_results.py 20261031 20261101 --out DIR [--db keiba.duckdb]

Writes, for the first date given (the race weekend's start, as in TARGET's file names):
  成績フルセットYYYYMMDD_JRA.csv  80 columns, cp932, no header   (same layout as TARGET 成績フルセット)
  馬別フルセットYYYYMMDD_JRA.csv  56 columns, cp932, header row  (same layout as TARGET 馬別フルセット)
  払戻YYYYMMDD_JRA.csv            every bet type incl. ワイド (utf-8): 年月日,場所,R,券種,組番,払戻,人気

Navigation follows links from the result top page (cname codes carry a checksum). Final win odds come from each
race's オッズ page (最終オッズ), via jra_odds.win_odds. Names and codes are mapped to TARGET's spelling with the DB:
jockey/trainer by code, horse profile (父/母/母父/馬主/生産者/毛色/生年月日) by 血統登録番号, using only rows before
the target date. Horses the DB has never seen are read from their JRA horse page (one request each).
Values TARGET computes itself (補正タイム, 基準タイム, マイニング, 馬印) are left empty, as the model does not use them."""
import re, sys, os, html, time, argparse, datetime as dt
import requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jra_odds

BASE = 'https://www.jra.go.jp'
TOP = 'pw01sli00/AF'
VENUE_CODE = {'札幌': '01', '函館': '02', '福島': '03', '新潟': '04', '東京': '05', '中山': '06', '中京': '07',
              '京都': '08', '阪神': '09', '小倉': '10'}
HORSE_HEADER = ['年', '月', '日', '回次', '場所', '日次', 'レース番号', '略レース名', 'クラスコード', '芝・ダ', 'トラックコード',
                '距離', '馬場状態', '馬名', '性別', '年齢', '騎手', '斤量', '頭数', '馬番', '確定着順', '入線着順', '異常コード',
                '着差タイム', '人気', '走破タイム(秒)', 'タイムS', '補正タイム', '通過順1角', '通過順2角', '通過順3角', '通過順4角',
                '上がり3Fタイム', '馬体重', '調教師', '所属', '賞金', '血統登録番号', '騎手コード', '調教師コード', 'レースID(新)',
                '馬主名', '生産者名', '父馬名', '母馬名', '母の父馬名', '毛色', '生年月日', '単勝オッズ', '馬印1', 'レース印1', 'PCI',
                'レース名', '補9', '基準タイム(秒)', 'レースコメント']
ABNORMAL = {'取消': 1, '除外': 3, '中止': 4, '失格': 5}   # TARGET 異常コード (7 = 降着)
TRACK = {'稍重': '稍', '不良': '不', '良': '良', '重': '重'}
COAT = {'黒鹿毛': '黒鹿', '青鹿毛': '青鹿', '栃栗毛': '栃栗'}

_last = jra_odds._last  # share the one-request-a-second limit with the odds reader

def _req(method, url, **kw):
    cache = os.environ.get('JRA_CACHE')  # testing aid: reuse fetched pages from this folder
    if cache:
        import hashlib
        fp = os.path.join(cache, hashlib.md5(f'{method}{url}{kw.get("data")}'.encode()).hexdigest())
        if os.path.exists(fp): return open(fp, encoding='utf-8').read()
        os.makedirs(cache, exist_ok=True)
        page = _req.__wrapped__(method, url, **kw)
        open(fp, 'w', encoding='utf-8').write(page)
        return page
    return _req.__wrapped__(method, url, **kw)

def _fetch(method, url, **kw):
    for i in range(4):
        time.sleep(max(0, 1.0 - (time.time() - _last[0])))
        _last[0] = time.time()
        try:
            r = requests.request(method, url, timeout=20, **kw)
            r.raise_for_status()
            return r.content.decode('cp932', errors='replace')
        except requests.RequestException as e:
            if i == 3: raise
            print(f'[results] retry {url} {kw.get("data", "")}: {e}', file=sys.stderr); time.sleep(2 ** (i + 1))

_req.__wrapped__ = _fetch

def _odds_page(cname): return _req('POST', jra_odds.URL, data={'cname': cname})

def get_s(cname): return _req('POST', f'{BASE}/JRADB/accessS.html', data={'cname': cname})
def _t(s): return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', s or ''))).strip()
def _num(s):
    s = (s or '').replace(',', '').strip()
    return float(s) if re.fullmatch(r'-?\d+(\.\d+)?', s) else None
def _sec(s):
    m = re.fullmatch(r'(?:(\d+):)?(\d+\.\d)', (s or '').strip())
    return round(int(m.group(1) or 0) * 60 + float(m.group(2)), 1) if m else None
def _zen(s):
    """ASCII → full width, as TARGET writes race names."""
    return ''.join(chr(ord(c) + 0xFEE0) if '!' <= c <= '~' else ('　' if c == ' ' else c) for c in s)
def _nospace(s): return re.sub(r'[\s　]+', '', s or '')

# ---------------------------------------------------------------- navigation
def meetings(date):
    """{venue: race-list cname} for date (YYYYMMDD), from the result top page (recent weeks only)."""
    page = get_s(TOP)
    out = {}
    for code, label in re.findall(r"doAction\('/JRADB/accessS\.html',\s*'(pw01srl\d+/\w+)'\);\"[^>]*>(?:<i[^>]*></i>)?([^<]+)<", page):
        if code[-11:-3] == date:
            m = re.match(r'\d+回(\D+?)\d+日', label.strip())
            if m: out[m.group(1)] = code
    return out

def race_codes(list_cname):
    page = get_s(list_cname)
    return sorted(set(re.findall(r"(pw01sde\d{22}/[0-9A-F]{2})", page)), key=lambda c: int(c[19:21]))

# ---------------------------------------------------------------- one race page
def parse_race(page, cname):
    d = cname[7:]  # 10 05 2026 04 08 11 20261024
    race = {'venue_code': d[2:4], 'year': int(d[4:8]), 'kai': int(d[8:10]), 'nichi': int(d[10:12]),
            'R': int(d[12:14]), 'date': d[14:22]}
    hd = page[page.find('race_header'):page.find('<thead')]
    race['weather'] = _t((re.search(r'class="weather".*?class="txt">(.*?)<', hd, re.S) or [None, ''])[1])
    m = re.search(r'class="(turf|durt|dirt)".*?class="txt">(.*?)<', hd, re.S)
    race['going'] = _t(m.group(2)) if m else ''
    nm = re.search(r'class="race_name">(.*?)</span>\s*</span>', hd, re.S) or re.search(r'class="race_name">(.*?)</span>', hd, re.S)
    raw = nm.group(1) if nm else ''
    g = re.search(r'icon_grade_(\w+)\.png', raw)
    race['grade'] = {'LISTED': 'L'}.get(g.group(1).upper(), g.group(1).upper()) if g else ''  # G1/G2/G3/JG1../L
    race['name'] = _t(re.sub(r'<span class="grade_icon.*', '', raw, flags=re.S))
    for k in ('category', 'class', 'rule', 'weight'):
        race[k] = _t((re.search(rf'class="cell {k}">(.*?)</div>', hd, re.S) or [None, ''])[1])
    c = re.search(r'class="cell course">.*?</span>([\d,]+)<span class="unit">メートル</span><span class="detail">(.*?)</span>', hd, re.S)
    race['dist'] = int(c.group(1).replace(',', '')) if c else None
    race['course'] = _t(c.group(2)) if c else ''
    prize = re.search(r'本賞金.*?<ol>(.*?)</ol>', hd, re.S)
    race['prize'] = [_num(x) for x in re.findall(r'class="num">([\d,.]+)<', prize.group(1))] if prize else []
    race['odds_cname'] = (re.search(r"'(pw151ou\w+/\w+)'", page) or [None, None])[1]
    horses = []
    body = page[page.find('<tbody', page.find('<thead')):]
    body = body[:body.find('</tbody>')]
    for row in re.findall(r'<tr>(.*?)</tr>', body, re.S):
        cell = {k: v for k, v in re.findall(r'<td class="(\w+)">(.*?)</td>', row, re.S)}
        if 'horse' not in cell: continue
        hid = re.search(r'pw01dud\d\d(\d{10})/', cell['horse'])
        jk = re.search(r"pw04k(?:mk00|rc01)(\d{4,5})/", cell.get('jockey', ''))
        tr = re.search(r"pw05cmk00(\d{4,5})/", cell.get('trainer', ''))
        corners = {int(n): int(v) for n, v in re.findall(r'title="(\d)コーナー通過順位">\s*(\d+)\s*<', cell.get('corner', ''))}
        hw = re.match(r'\s*(\d+)', _t(cell.get('h_weight', '')))
        sa = re.match(r'([牡牝セせ騸])(\d+)', _t(cell.get('age', '')).replace('せん', 'セ').replace('せ', 'セ').replace('騸', 'セ'))
        horses.append({'place': _t(cell.get('place')), 'waku': int((re.search(r'枠(\d)', cell.get('waku', '')) or [0, 0])[1]),
                       'num': int(_t(cell.get('num')) or 0), 'name': _t(re.sub(r'<span class="horse_icon">.*?</span>', '', cell['horse'], flags=re.S)),
                       'id': hid.group(1) if hid else '', 'horse_url': (re.search(r'href="([^"]+)"', cell['horse']) or [None, None])[1],
                       'sex': (sa.group(1) if sa else ''), 'age': int(sa.group(2)) if sa else None,
                       'weight': _t(cell.get('weight')), 'jockey': re.sub(r'^[△▲☆◇★]\s*', '', _t(cell.get('jockey'))),
                       'jockey_code': jk.group(1).zfill(5) if jk else '', 'time': _sec(_t(cell.get('time'))),
                       'margin': _t(cell.get('margin')), 'corners': corners, 'agari': _num(_t(cell.get('f_time'))),
                       'hweight': int(hw.group(1)) if hw else None, 'trainer': _t(cell.get('trainer')),
                       'trainer_code': tr.group(1).zfill(5) if tr else '', 'pop': int(_t(cell.get('pop'))) if _t(cell.get('pop')).isdigit() else None})
    race['horses'] = horses
    lap = re.search(r'ハロンタイム</th>\s*<td>(.*?)</td>', page, re.S)
    race['laps'] = [float(x) for x in re.findall(r'\d+\.\d', _t(lap.group(1)))] if lap else []
    ag = re.search(r'<th scope="row">上り</th>\s*<td>(.*?)</td>', page, re.S)
    race['agari_txt'] = _t(ag.group(1)) if ag else ''
    race['pays'] = []
    ref = page[page.find('refund_area'):]
    for kind, block in re.findall(r'<dt>(.*?)</dt>\s*<dd>(.*?)</dd>', ref, re.S):
        for num, yen, pop in re.findall(r'class="num">(.*?)</div>\s*<div class="yen">([\d,]+)<.*?class="pop">(\d+)<', block, re.S):
            race['pays'].append((_t(kind), _t(num), int(yen.replace(',', '')), int(pop)))
    return race

def parse_horse_page(page):
    """Profile fields from a JRA horse page (競走馬情報)."""
    s = re.sub(r'\s*\n\s*', '|', re.sub(r'[ \t]+', ' ', html.unescape(re.sub(r'<script.*?</script>|<[^>]+>', '\n', page, flags=re.S))))
    def f(*labels):
        for label in labels:
            m = re.search(rf'\|{label}\|+([^|]+)', s)
            if m: return m.group(1).strip()
        return ''
    aff = re.search(r'\|調教師名\|+[^|]+\|*（(美浦|栗東|地方|外国)）', s)
    b = re.match(r'(\d{4})年(\d+)月(\d+)日', f('生年月日'))
    return {'sire': f('父'), 'dam': re.sub(r'\s*産駒$', '', f('母')), 'damsire': f('母の父'), 'owner': f('馬主名'),
            'breeder': f('生産牧場', '生産者'), 'coat': f('毛色'), 'birth': f'{b.group(1)}{int(b.group(2)):02d}{int(b.group(3)):02d}' if b else '',
            'affil': {'美浦': '美', '栗東': '栗', '地方': '地', '外国': '外'}.get(aff.group(1), '') if aff else '',
            'sex': f('性別').replace('せん', 'セ'), 'trainer': _nospace(re.sub(r'（.*', '', f('調教師名')))}

# ---------------------------------------------------------------- DB name maps (TARGET spelling)
class Names:
    def __init__(self, db, date):
        self.j, self.t, self.h, self.rn, self.jn, self.tn = {}, {}, {}, {}, {}, {}
        if not db or not os.path.exists(db): return
        import duckdb
        c = duckdb.connect(db, read_only=True)
        y, m, d = int(date[2:4]), int(date[4:6]), int(date[6:])
        before = f"(CAST(column00 AS INTEGER)*10000 + CAST(column01 AS INTEGER)*100 + CAST(column02 AS INTEGER)) < {y*10000+m*100+d}"
        order = "CAST(column00 AS INTEGER)*10000 + CAST(column01 AS INTEGER)*100 + CAST(column02 AS INTEGER)"
        for code, name in c.execute(f"SELECT column38, arg_max(column16, {order}) FROM horse_race_full WHERE {before} GROUP BY 1").fetchall():
            if code:
                self.j[str(code)[2:]] = name
                if len(str(code)) == 7: self.jn[_nospace(name)] = str(code)[2:]
        for code, name, aff in c.execute(f"SELECT column39, arg_max(column34, {order}), arg_max(column35, {order}) FROM horse_race_full WHERE {before} GROUP BY 1").fetchall():
            if code:
                self.t[str(code)[2:]] = (name, aff)
                if len(str(code)) == 7: self.tn[_nospace(name)] = str(code)[2:]
        for row in c.execute(f"""SELECT column37, arg_max(column41, {order}), arg_max(column42, {order}), arg_max(column43, {order}),
                arg_max(column44, {order}), arg_max(column45, {order}), arg_max(column46, {order}), arg_max(column47, {order})
                FROM horse_race_full WHERE {before} GROUP BY 1""").fetchall():
            if row[0]: self.h[str(row[0])[2:]] = dict(zip(['owner', 'breeder', 'sire', 'dam', 'damsire', 'coat', 'birth'], [x if x is not None else '' for x in row[1:]]))
        for full, short in c.execute(f"SELECT trim(column52, '　 '), arg_max(column07, {order}) FROM horse_race_full WHERE {before} AND trim(column52, '　 ') != '' GROUP BY 1").fetchall():
            self.rn[full] = short
        c.close()

def _jp_nospace(s):
    """TARGET drops the spaces in Japanese names but keeps them in Latin ones ('吉川 潤'→'吉川潤', 'TO RACING')."""
    s = (s or '').strip().replace('\u3000', ' ')
    return re.sub(r'(?<=[^\x00-\x7F]) +|(?<=[\x00-\x7F]) +(?=[^\x00-\x7F])', '', s)
KANJI = str.maketrans({'髙': '高', '德': '徳', '﨑': '崎', '栁': '柳', '瀨': '瀬'})
def owner_name(s):
    """Owner/breeder in TARGET's spelling: no company-type marks, JIS-common kanji, half-width alphanumerics."""
    import unicodedata
    s = unicodedata.normalize('NFKC', s or '').translate(KANJI)
    return re.sub(r'\((株|有|同|一社|合|社|医|財|公|資|善)\)', '', _jp_nospace(s)).strip()

def class_code(race):
    cls, g = race['class'], race['grade']
    if g in ('G1', 'JG1'): return '195'
    if g in ('G2', 'JG2'): return '179'
    if g in ('G3', 'JG3'): return '163'
    if g == 'L': return '115'
    if '新馬' in cls: return '15'
    if '未勝利' in cls: return '7'
    for k, v in (('1勝', '23'), ('2勝', '43'), ('3勝', '67'), ('１勝', '23'), ('２勝', '43'), ('３勝', '67')):
        if k in cls: return v
    return '131'  # オープン (障害オープン included)

def _hurdle(race): return race['category'].startswith('障害')

def short_name(race, names):
    """TARGET's 略レース名. Known race names reuse the DB's spelling; otherwise build it the same way."""
    full = target_race_name(race)
    cls, cat, rule = race['class'], race['category'], race['rule']
    sfx = ('・牝' if '牝' in rule else '') + ('・若' if '若手' in rule else '') + ('*' if cat.startswith('2歳') and '新馬' not in cls else '')
    if full and full in names.rn: return names.rn[full]
    if _hurdle(race) and not full: return '障害未勝利' if '未勝利' in cls else '障害・オープ'
    base = {'15': '新馬', '7': '未勝利'}.get(class_code(race))
    if not full and base: return base + sfx
    k = re.search(r'([123])勝', cls)
    if not full: return (_zen(k.group(1)) + '勝ｸﾗｽ' + sfx) if k else 'オープン'
    head = full[:3] + 'Ｈ' if 'ハンデ' in race['weight'] else full[:4]
    g = race['grade']
    if g in ('G1', 'G2', 'G3'): return head + g
    if g.startswith('J'): return head[:3] + 'J' + g[1:]
    if g == 'L': return head + '(L)'
    return head + (f'･{k.group(1)}勝' if k else '') + ('*' if cat.startswith('2歳') and k else '')

def target_race_name(race):
    """TARGET's レース名 (full width, ステークス→Ｓ); empty for races that only carry their condition as a name."""
    n = race['name']
    if not n or n.startswith('メイクデビュー') or re.match(r'(障害)?\d歳', n): return ''
    return _zen(n.replace('ステークス', 'Ｓ').replace('トロフィー', 'Ｔ'))

# ---------------------------------------------------------------- build rows
from decimal import Decimal, ROUND_HALF_UP
def pci(t, ag, dist):
    if not t or not ag or dist <= 600: return None
    return ((t - ag) / (dist - 600) * 600) / ag * 100 - 50
def rnd(x, nd):
    """Round half up (TARGET style), robust to binary float error."""
    return None if x is None else float(Decimal(repr(x)).quantize(Decimal('1e-%d' % nd) if nd else Decimal(1), rounding=ROUND_HALF_UP))
def mean_half_up(xs, nd):
    if not xs: return None
    return float((sum(Decimal(repr(x)) for x in xs) / len(xs)).quantize(Decimal('1e-%d' % nd), rounding=ROUND_HALF_UP))
def f1(x): return '' if x is None else f'{rnd(x, 1):.1f}'
def f2(x): return '' if x is None else f'{x:.2f}'
def _int_or(x): return str(int(x)) if x == int(x) else str(x)

def build(race, names, fetch_horse):
    venue = {v: k for k, v in VENUE_CODE.items()}[race['venue_code']]
    y, mo, da = race['date'][:4], race['date'][4:6], race['date'][6:]
    hurdle = _hurdle(race)
    dirt = 'ダート' in race['course'] and not ('芝' in race['course'] and not hurdle)
    tdc_r = ('障害(直線ダ)' if 'ダート' in race['course'] else '障害') if hurdle else ('ダート' if dirt else '芝')
    tdc_h = 'ダ' if dirt else '芝'
    track_code = ('3' if dirt else '2') if hurdle else ('1' if dirt else ('8' if '外' in race['course'] else '0'))
    dist = race['dist']
    finished = sorted([h for h in race['horses'] if h['place'].isdigit() and h['time']], key=lambda h: int(h['place']))
    times = [h['time'] for h in finished]
    win = times[0] if times else None
    second = times[1] if len(times) > 1 else win
    cc = class_code(race); sn = short_name(race, names); full = target_race_name(race)
    odds = {o['num']: o['odds'] for o in race.get('odds') or []}
    pop = {h['num']: h['pop'] for h in race['horses']}
    # prize per place, split evenly on dead heats
    places = [int(h['place']) for h in finished]
    prize_of = {}
    for p_ in set(places):
        k = places.count(p_)
        xs = [race['prize'][i] if i < len(race['prize']) else 0 for i in range(p_ - 1, p_ - 1 + k)]
        prize_of[p_] = rnd(sum(xs) / k, 1)
    horse_rows = []
    for h in sorted(race['horses'], key=lambda h: h['num']):
        ab = ABNORMAL.get(h['place'], 0)
        place = int(h['place']) if h['place'].isdigit() else 0
        jcode = h['jockey_code'] or names.jn.get(_nospace(h['jockey']), '')
        tcode = h['trainer_code'] or names.tn.get(_nospace(h['trainer']), '')
        prof = names.h.get(h['id']) or fetch_horse(h)
        if tcode in names.t: tname, aff = names.t[tcode]
        else:
            tname = _nospace(h['trainer'])
            aff = prof.get('affil') or fetch_horse(h).get('affil', '') or ('地' if not tcode else '')
        jname = names.j.get(jcode, _nospace(h['jockey']))
        t = h['time'] if place else None
        if place == 1: margin = -rnd(second - win, 1)
        elif place and win is not None: margin = rnd(t - win, 1)
        else: margin = None
        p = pci(t, h['agari'], dist) if place and not hurdle else None  # plain float, printed like TARGET's
        cn = h['corners']
        horse_rows.append([y[2:], mo, da, str(race['kai']), venue, str(race['nichi']), str(race['R']), sn, cc, tdc_h, track_code,
            str(dist), TRACK.get(race['going'], race['going'][:1]), h['name'], h['sex'], str(h['age'] or ''), jname, h['weight'],
            str(len(race['horses'])), str(h['num']), str(place), str(place), str(ab),
            '----' if margin is None else f'{margin:4.1f}', str(h['pop']) if h['pop'] else '',
            f1(t) if t else '0', (f'{int(t // 60)}.{t % 60:04.1f}' if t else '0.00.0'), '',
            *[str(cn.get(i, 0)) for i in (1, 2, 3, 4)], f1(h['agari']) if place else '', str(h['hweight'] or ''),
            tname, aff, _int_or(prize_of.get(place, 0)) if place else '0', f"UX{h['id']}", f"KX{jcode}" if jcode else '',
            f"CX{tcode}" if tcode else '',
            f"RX{y}{mo}{da}{race['venue_code']}{race['kai']:02d}{race['nichi']:02d}{race['R']:02d}{h['num']:02d}",
            owner_name(prof.get('owner', '')), owner_name(prof.get('breeder', '')), prof.get('sire', ''), prof.get('dam', ''),
            prof.get('damsire', ''), COAT.get(prof.get('coat', ''), prof.get('coat', '')), prof.get('birth', ''),
            f1(odds.get(h['num'])), '', '', '' if p is None else f'{p:.1f}', (full + '　' * max(0, 30 - len(full))) if full else '　' * 30, '', '', ''])
    # race row
    pays = race['pays']
    def payline(kind, n):
        xs = [p_ for p_ in pays if p_[0] == kind][:n]
        out = []
        for i in range(n):
            out += [xs[i][1], str(xs[i][2]), str(pop.get(int(xs[i][1]), xs[i][3]) or xs[i][3])] if i < len(xs) else ['', '', '']
        return out
    laps = [] if hurdle else race['laps']
    L = len(laps)
    cum = lambda n: rnd(sum(laps[:n]), 1) if L >= n else None
    tail = lambda n: rnd(sum(laps[-n:]), 1) if L >= n else None
    ag4 = re.search(r'4F\s*([\d.]+)', race['agari_txt']); ag3 = re.search(r'3F\s*([\d.]+)', race['agari_txt'])
    up3, up4 = (tail(3), tail(4)) if laps else (float(ag3.group(1)) if ag3 else None, float(ag4.group(1)) if ag4 else None)
    avg = lambda xs: mean_half_up(xs, 2)
    q = int(rnd(len(times) * 0.25, 0)) if times else 0
    if hurdle:
        mile = re.search(r'1マイル\s*(\d+)分\s*(\d+)秒\s*(\d)', race['agari_txt'])
        pass_txt = f'マイル:{int(mile.group(1)) * 60 + int(mile.group(2))}.{mile.group(3)}' if mile else ''
        up_txt = f'{f1(up4)}-{f1(up3)}' if up3 else ''
        mid = ['0.0', '0.0']
        tailcols = [f1(win), '0.0', '0.0', '0.0', '0.0', '0.0', '0.0']
        diffs = ['', '', '']
    else:
        tops = [float(f"{pci(h['time'], h['agari'], dist):.1f}") for h in finished[:3] if pci(h['time'], h['agari'], dist) is not None]
        pci3 = mean_half_up(tops, 2) if len(tops) == min(3, len(finished)) and tops else None
        rpci = pci(win, up3, dist)
        mid = [f2(pci3), f1(rpci)]
        pass_txt = '-'.join(f1(cum(n)) for n in (3, 4, 5, 6) if n <= L)
        up_txt = '-'.join(f1(tail(n)) for n in (6, 5, 4, 3) if n <= L)
        even = dist % 200 == 0
        diffs = [f'{rnd(tail(n) - cum(n), 1):+.1f}' if even and n < L else '' for n in (3, 4, 5)]
        tailcols = [f1(win), f1(up3), f1(up4), f1(tail(5)), f1(cum(3)), f1(cum(4)), f1(cum(5))]
    w = race['weather']
    rrow = [y, mo, da, venue, str(race['R']), sn, tdc_r, str(dist), f' {w} ' if len(w) == 1 else w,
            TRACK.get(race['going'], race['going'][:1]), str(len(race['horses'])),
            f"RX{race['venue_code']}{y[2:]}{race['kai']}{format(race['nichi'], 'X')}{race['R']:02d}", f'{y}.{int(mo)}.{int(da)}',
            *payline('複勝', 5), *payline('単勝', 3), '0.0', *mid,
            *[f1(laps[i]) if i < L else '' for i in range(25)], f2(avg(times)), f2(avg(times[1:1 + q])), f2(avg(times[:5])),
            pass_txt, up_txt, *diffs, *tailcols]
    assert len(rrow) == 80 and all(len(r) == 56 for r in horse_rows), (len(rrow), venue, race['R'])
    pay_rows = [[race['date'], venue, race['R'], k, n, yen, pp] for k, n, yen, pp in pays]
    return rrow, horse_rows, pay_rows

def collect(dates, db=None, log=print):
    names = Names(db, min(dates))
    cache = {}
    def fetch_horse(h):
        if h['id'] in cache: return cache[h['id']]
        prof = {}
        if h.get('horse_url'):
            try: prof = parse_horse_page(_req('GET', BASE + html.unescape(h['horse_url'])))
            except Exception as e: log(f'[results] horse page failed {h["name"]}: {e}')
        cache[h['id']] = prof
        return prof
    R, H, P = [], [], []
    for date in dates:
        ms = meetings(date)
        if not ms: raise SystemExit(f'JRAの結果ページに {date} の開催が見つかりません（直近の開催のみ掲載）')
        for venue, lc in ms.items():
            for code in race_codes(lc):
                race = parse_race(get_s(code), code)
                if race['odds_cname']:
                    try:
                        jra_odds._get = _odds_page  # same pacing/retries, and the test cache
                        race['odds'] = jra_odds.win_odds(race['odds_cname'])[1]
                    except Exception as e: log(f'[results] odds failed {venue}{race["R"]}R: {e}')
                r, hs, ps = build(race, names, fetch_horse)
                R.append(r); H += hs; P += ps
            log(f'[results] {date} {venue}: {sum(1 for r in R if r[3] == venue and r[0] + r[1] + r[2] == date)} races')
    log(f'[results] horse pages fetched: {len(cache)}')
    return R, H, P

# ---------------------------------------------------------------- 特別登録 (special-race nominations)
TK_TOP = 'pw03trl00/29'
TK_HEADER = ['年月日', '場所', '競走番号', '馬番号', 'レース名', '芝・ダ', '距離', '馬名', '性別', '年齢', '騎手名', '斤量', '調教師名',
             '所属', '馬主名', '生産者名', '種牡馬名', '母名', '血統登録番号', '日次', '母父名', '毛色', '枠番号', '前走との間隔',
             '前走人気', '前走着順', '頭数', '本賞金', '収得賞金', '本日人気', '本日オッズ', '本日着順', 'レースID']

def get_t(cname): return _req('POST', f'{BASE}/JRADB/accessT.html', data={'cname': cname})

def tokubetsu_codes():
    """{date: [race cname]} of the special races JRA lists on 特別レース登録馬 (the coming weekend)."""
    out = {}
    for c in sorted(set(re.findall(r"(pw03tde\d{18}/[0-9A-F]{2})", get_t(TK_TOP)))):
        out.setdefault(c[17:25], []).append(c)
    return out

def collect_tokubetsu(db=None, dates=None, log=print):
    """Rows in TARGET's 特別登録 layout for the listed weekend (騎手・枠・オッズ are not known yet, as in TARGET)."""
    codes = tokubetsu_codes()
    dates = sorted(d for d in codes if not dates or d in dates)
    if not dates: return [], []
    first = dt.date(int(dates[0][:4]), int(dates[0][4:6]), int(dates[0][6:]))  # this weekend only (early G1 nominations are listed too)
    dates = [d for d in dates if (dt.date(int(d[:4]), int(d[4:6]), int(d[6:])) - first).days <= 2]
    names = Names(db, min(dates))
    meta = {}
    if db and os.path.exists(db):
        import duckdb
        c = duckdb.connect(db, read_only=True)
        order = "CAST(column00 AS INTEGER)*10000 + CAST(column01 AS INTEGER)*100 + CAST(column02 AS INTEGER)"
        for hid, sex, tr, aff in c.execute(f"""SELECT column37, arg_max(column14, {order}), arg_max(column34, {order}),
                arg_max(column35, {order}) FROM horse_race_full GROUP BY 1""").fetchall():
            if hid: meta[str(hid)[2:]] = (sex, tr, aff)
        c.close()
    rows, fetched = [], 0
    for d in dates:
        for code in codes[d]:
            v, kai, nichi, R = code[9:11], code[11:13], code[13:15], code[15:17]
            page = get_t(code)
            race = parse_race(page, f'pw01sde10{v}{d[:4]}{kai}{nichi}{R}{d}')
            race['horses'] = []  # the list is split over several tables (登録馬名1, 2, ...)
            for row in re.findall(r'<tr>(.*?)</tr>', page[page.find('horse_list_area'):], re.S):
                hc = re.search(r'<td class="horse">(.*?)</td>', row, re.S)
                if not hc: continue
                hid = re.search(r'pw01dud\d\d(\d{10})/', hc.group(1))
                race['horses'].append({'name': _t(hc.group(1)), 'id': hid.group(1) if hid else '',
                    'horse_url': (re.search(r'href="([^"]+)"', hc.group(1)) or [None, ''])[1],
                    'weight': _t((re.search(r'<td class="weight">(.*?)</td>', row, re.S) or [None, ''])[1])})
            venue = {x: k for k, x in VENUE_CODE.items()}[v]
            dirt = 'ダート' in race['course'] and '芝' not in race['course']
            for i, h in enumerate(race['horses'], 1):
                prof = names.h.get(h['id'])
                sex, tr, aff = meta.get(h['id'], ('', '', ''))
                if not prof or not sex:
                    try: hp = parse_horse_page(_req('GET', BASE + html.unescape(h['horse_url']))); fetched += 1
                    except Exception as e: hp = {}; log(f'[tokubetsu] horse page failed {h["name"]}: {e}')
                    prof = prof or hp; sex = sex or hp.get('sex', ''); tr = tr or hp.get('trainer', ''); aff = aff or hp.get('affil', '')
                birth = str(prof.get('birth', '') or '')
                rows.append([d[2:], venue, str(race['R']), f'{i:2d}', short_name(race, names), 'ダ' if dirt else '芝', str(race['dist']),
                    h['name'], sex, str(int(d[:4]) - int(birth[:4])) if birth[:4].isdigit() else '', '', h['weight'], tr, aff,
                    owner_name(prof.get('owner', '')), owner_name(prof.get('breeder', '')), prof.get('sire', ''), prof.get('dam', ''),
                    f"UX{h['id'][2:]}", str(race['nichi']), prof.get('damsire', ''), COAT.get(prof.get('coat', ''), prof.get('coat', '')),
                    '0', '-1', '0', '0', str(len(race['horses'])), '0', '0', '0', '0.0', '0',
                    f"RX{d}{v}{race['kai']:02d}{race['nichi']:02d}{race['R']:02d}{i:02d}"])
            log(f'[tokubetsu] {d} {venue}{race["R"]}R {race["name"]}: {len(race["horses"])}頭')
    log(f'[tokubetsu] horse pages fetched: {fetched}')
    return dates, rows

def write_tokubetsu(out, d0, rows):
    import csv
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f'特別登録{d0}_JRA.csv')
    with open(path, 'w', encoding='cp932', errors='replace', newline='') as f:
        w = csv.writer(f, lineterminator='\r\n'); w.writerow(TK_HEADER); w.writerows(rows)
    return path

# ---------------------------------------------------------------- 出馬表 → 当日出走馬 (TARGET's v02 layout)
DE_TOP = 'pw01dli00/F3'
TD_HEADER = ['場 R', 'レース名', '芝ダ', '距離', '発走時刻', '馬番', '馬名S', 'Ｃ', '馬印1', '馬印2', '馬印3', '性', '齢', '騎手', '斤量',
             'マイニング値', 'マイニング順位', '単オッズ', '人気', '複勝オッズ下', '上', '着', '所属', '調教師', '馬体重', '増減', '種牡馬',
             '父タイプ名', '母父名', '母父タイプ名', '母母父名', '母母父タイプ名']
VENUE_PREFIX = {'札幌': '札', '函館': '函', '福島': '福', '新潟': '新', '東京': '東', '中山': '中', '中京': '名', '京都': '京',
                '阪神': '阪', '小倉': '小'}
DIVISION = {'美浦': '(美)', '栗東': '(栗)', '地方': '[地]', '外国': '[外]'}

def get_d(cname): return _req('POST', f'{BASE}/JRADB/accessD.html', data={'cname': cname})

def shutsuba_codes():
    """{date: [meeting cname]} of the race days JRA's 出馬表 lists (Thursday evening on: the coming weekend)."""
    out = {}
    for c in sorted(set(re.findall(r"(pw01drl00\d{18}/[0-9A-F]{2})", get_d(DE_TOP)))):
        out.setdefault(c[-11:-3], []).append(c)
    return out

def shutsuba_race_codes(list_cname):
    return sorted(set(re.findall(r"(pw01dde\d{22}/[0-9A-F]{2})", get_d(list_cname))), key=lambda c: int(c[19:21]))

def parse_shutsuba(page, cname):
    """Race header (as on the result page) plus the runners of one 出馬表 page. 枠・馬番 are 0 until the draw (Friday)."""
    race = parse_race(page, 'pw01sde10' + cname[9:])
    pt = re.search(r'発走時刻：<strong>(\d+)時(\d+)分', page)
    race['post'] = f'{int(pt.group(1)):02d}:{pt.group(2)}' if pt else ''
    body = page[page.find('<tbody', page.find('<thead')):]
    body = body[:body.find('</tbody>')]
    hs = []
    for row in re.findall(r'<tr>(.*?)</tr>', body, re.S):
        cell = {k: v for k, v in re.findall(r'<td class="(\w+)">(.*?)</td>', row, re.S)}
        if 'horse' not in cell or 'jockey' not in cell: continue
        hc, jc = cell['horse'], cell['jockey']
        f = lambda pat, s: _t((re.search(pat, s, re.S) or [None, ''])[1])
        hid = re.search(r'pw01dud\d\d(\d{10})/', hc)
        tr = re.search(r'class="trainer">(.*?)<span class="division">[（(](.*?)[）)]', hc, re.S)
        sa = re.match(r'([牡牝セせ騸])(\d+)', f(r'class="age">(.*?)</p>', jc).replace('せん', 'セ').replace('せ', 'セ').replace('騸', 'セ'))
        jk = re.search(r"pw04k(?:mk00|rc01)(\d{4,5})/", jc)
        tc = re.search(r"pw05cmk00(\d{4,5})/", hc)
        num = _t(cell.get('num', ''))
        hs.append({'name': f(r'class="name">(.*?)</div>', hc), 'id': hid.group(1) if hid else '',
                   'waku': int((re.search(r'枠(\d)', cell.get('waku', '')) or [0, 0])[1]), 'num': int(num) if num.isdigit() else 0,
                   'trainer': _t(tr.group(1)) if tr else '', 'division': _t(tr.group(2)) if tr else '',
                   'trainer_code': tc.group(1).zfill(5) if tc else '',
                   'sire': f(r'class="sire"><span>父：</span>(.*?)</li>', hc), 'damsire': f(r'母の父：(.*?)[)）]', hc),
                   'sex': sa.group(1) if sa else '', 'age': sa.group(2) if sa else '',
                   'weight': _num(f(r'class="weight">(.*?)<span', jc)), 'mark': f(r'class="mark jockey">(.*?)</span>', jc),
                   'jockey': f(r'class="jockey">(?:<span[^>]*>.*?</span>)?(.*?)</p>', jc), 'jockey_code': jk.group(1).zfill(5) if jk else ''})
    race['horses'] = hs
    return race

def _kin(w, mark):
    """斤量 as TARGET writes it: ' 55 ', '57.5', '53▲'."""
    if w is None: return ''
    s = str(int(w)) if w == int(w) else f'{w:g}'
    return s + mark if mark else (f' {s} ' if w == int(w) else s)

def jockey_name(h, names):
    code = h['jockey_code'] or names.jn.get(_nospace(h['jockey']), '')
    if code in names.j: return names.j[code]
    return re.sub(r'^[A-Za-zＡ-Ｚ][.．]', '', _nospace(h['jockey']))[:4]  # TARGET: 4 characters ('A.プーシャン' → 'プーシャ')

def shutsuba_rows(race, names):
    venue = {v: k for k, v in VENUE_CODE.items()}[race['venue_code']]
    hurdle = _hurdle(race)
    dirt = 'ダート' in race['course'] and not ('芝' in race['course'] and not hurdle)
    sn = short_name(race, names)
    rows = []
    for h in race['horses']:
        prof = names.h.get(h['id'], {})
        tcode = h['trainer_code'] or names.tn.get(_nospace(h['trainer']), '')
        tname = names.t[tcode][0] if tcode in names.t else _nospace(h['trainer'])
        rows.append([f"{VENUE_PREFIX[venue]}{race['R']}", sn, 'ダ' if dirt else '芝', str(race['dist']), race['post'],
                     str(h['num']) if h['num'] else '未', h['name'], '', '', '', '', h['sex'], h['age'], jockey_name(h, names),
                     _kin(h['weight'], h['mark']), '', '', '', '', '', '', '', DIVISION.get(h['division'], ''), tname, '', '',
                     prof.get('sire') or h['sire'], '', prof.get('damsire') or h['damsire'], '', '', ''])
    return rows

def collect_shutsuba(date, db=None, log=print):
    """Rows in TARGET's 当日出走馬 layout for one race day, from JRA's 出馬表 (None if JRA does not list the day)."""
    codes = shutsuba_codes().get(date)
    if not codes: return None
    names = Names(db, date)
    rows = []
    for lc in codes:
        for code in shutsuba_race_codes(lc):
            race = parse_shutsuba(get_d(code), code)
            rows += shutsuba_rows(race, names)
        log(f'[shutsuba] {date} {lc[9:11]}: {len(rows)} horses so far')
    return rows

def drawn(date):
    """True when JRA's 出馬表 for the day already shows 馬番 (checked on the day's first race)."""
    codes = shutsuba_codes().get(date)
    if not codes: return False
    rc = shutsuba_race_codes(codes[0])
    return bool(rc) and any(h['num'] for h in parse_shutsuba(get_d(rc[0]), rc[0])['horses'])

def write_toujitsu(out, date, rows):
    import csv
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f'当日出走馬{date}_JRA.csv')
    with open(path, 'w', encoding='cp932', errors='replace', newline='') as f:
        w = csv.writer(f, lineterminator='\r\n'); w.writerow(TD_HEADER); w.writerows(rows)
    return path


def write(out, start, R, H, P):
    import csv
    os.makedirs(out, exist_ok=True)
    paths = [os.path.join(out, f'成績フルセット{start}_JRA.csv'), os.path.join(out, f'馬別フルセット{start}_JRA.csv'),
             os.path.join(out, f'払戻{start}_JRA.csv')]
    with open(paths[0], 'w', encoding='cp932', errors='replace', newline='') as f: csv.writer(f, lineterminator='\r\n').writerows(R)
    with open(paths[1], 'w', encoding='cp932', errors='replace', newline='') as f:
        w = csv.writer(f, lineterminator='\r\n'); w.writerow(HORSE_HEADER); w.writerows(H)
    with open(paths[2], 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f); w.writerow(['年月日', '場所', 'R', '券種', '組番', '払戻', '人気']); w.writerows(P)
    return paths

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('dates', nargs='+')
    ap.add_argument('--out', required=True)
    ap.add_argument('--db')
    a = ap.parse_args()
    R, H, P = collect(a.dates, a.db, log=lambda s: print(s, file=sys.stderr))
    for p in write(a.out, min(a.dates), R, H, P): print(p)
