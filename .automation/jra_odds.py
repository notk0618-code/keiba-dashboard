"""Read JRA's official odds pages (www.jra.go.jp/JRADB/accessO.html) for one race date. Read-only.
The site navigates by POSTing `cname=<code>`; codes carry a checksum, so they are always taken from the links
on the page above (開催選択 → レース選択 → 単勝・複勝). Only days with racing appear on 開催選択.
  python3 jra_odds.py YYYYMMDD           -> post times only (4 requests at most)
  python3 jra_odds.py YYYYMMDD --odds    -> post times + win odds per horse (one request per race)"""
import re, sys, json, time, html, datetime as dt
import requests

URL = 'https://www.jra.go.jp/JRADB/accessO.html'
TOP = 'pw15oli00/6D'
JST = dt.timezone(dt.timedelta(hours=9))
_last = [0.0]

def _get(cname):
    for i in range(4):
        time.sleep(max(0, 1.0 - (time.time() - _last[0])))  # at most one request a second
        _last[0] = time.time()
        try:
            r = requests.post(URL, data={'cname': cname}, timeout=20)
            r.raise_for_status()
            return r.content.decode('cp932', errors='replace')
        except requests.RequestException as e:
            if i == 3: raise
            print(f'[odds] retry {cname}: {e}', file=sys.stderr); time.sleep(2 ** (i + 1))

def _text(s): return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', s))).strip()

def meetings(date):
    """{venue: race-list cname} for `date` (YYYYMMDD); empty when JRA lists no racing that day."""
    page = _get(TOP)
    out = {}
    for code, label in re.findall(r"doAction\('/JRADB/accessO\.html',\s*'(pw15orl\d+/\w+)'\);\"[^>]*>(?:<i[^>]*></i>)?([^<]+)<", page):
        if code[-11:-3] == date:
            m = re.match(r'\d+回(\D+?)\d+日', label.strip())
            if m: out[m.group(1)] = code
    return out

def races(list_cname):
    """{race_no: {'post': 'HH:MM', 'cname': 単勝・複勝 cname}} from one レース選択 page."""
    page = _get(list_cname)
    out = {}
    for row in re.findall(r'<tr>(.*?)</tr>', page, re.S):
        num = re.search(r'alt="(\d+)レース"', row)
        t = re.search(r'(\d{1,2})時(\d{2})分', row)
        c = re.search(r"'(pw151ou\w+/\w+)'", row)
        if num and t:
            out[int(num.group(1))] = {'post': f'{int(t.group(1)):02d}:{t.group(2)}', 'cname': c.group(1) if c else None}
    return out

def win_odds(cname):
    """(as_of 'HH:MM' or '', [{'num', 'waku', 'name', 'odds', 'place'}]); odds is None for 取消/除外 or before sales open,
    place is the 複勝 (min, max) range or None."""
    page = _get(cname)
    m = re.search(r'(\d{1,2})時(\d{2})分現在オッズ', page)
    as_of = f'{int(m.group(1)):02d}:{m.group(2)}' if m else ''
    horses, waku_now = [], None
    for row in re.findall(r'<tr>(.*?)</tr>', page, re.S):
        num = re.search(r'<td class="num">\s*(\d+)\s*</td>', row)
        name = re.search(r'<td class="horse">(.*?)</td>', row, re.S)
        tan = re.search(r'<td class="odds_tan">(.*?)</td>', row, re.S)
        if not (num and name and tan): continue
        waku = re.search(r'alt="枠(\d)', row)  # the 枠 cell spans rows when a 枠 holds two or three horses
        if waku: waku_now = int(waku.group(1))
        o = _text(tan.group(1))
        fk = re.search(r'<td class="odds_fuku">.*?class="min">([\d.]+)<.*?class="max">([\d.]+)<', row, re.S)
        horses.append({'num': int(num.group(1)), 'waku': waku_now,
                       'name': _text(name.group(1)), 'odds': float(o) if re.fullmatch(r'\d+(\.\d+)?', o) else None,
                       'place': (float(fk.group(1)), float(fk.group(2))) if fk else None})
    return as_of, horses

def fetch(date, with_odds=True):
    """{venue: {race_no: {'post', 'as_of', 'horses'}}} for `date` (YYYYMMDD)."""
    out = {}
    for venue, lc in meetings(date).items():
        out[venue] = {}
        for no, r in sorted(races(lc).items()):
            e = {'post': r['post']}
            if with_odds and r['cname']:
                e['as_of'], e['horses'] = win_odds(r['cname'])
            out[venue][no] = e
    return out

def remaining(date, margin_min=5):
    """Races on `date` whose post time is more than `margin_min` minutes from now (JST)."""
    now = dt.datetime.now(JST)
    if now.strftime('%Y%m%d') > date: return []
    left = []
    for venue, rs in fetch(date, with_odds=False).items():
        for no, r in rs.items():
            h, m = map(int, r['post'].split(':'))
            post = dt.datetime(int(date[:4]), int(date[4:6]), int(date[6:]), h, m, tzinfo=JST)
            if post - now > dt.timedelta(minutes=margin_min): left.append((venue, no, r['post']))
    return left

if __name__ == '__main__':
    d = sys.argv[1] if len(sys.argv) > 1 else dt.datetime.now(JST).strftime('%Y%m%d')
    print(json.dumps(fetch(d, '--odds' in sys.argv), ensure_ascii=False, indent=1))
