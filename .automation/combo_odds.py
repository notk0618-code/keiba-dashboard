"""Odds of every bet type for the 🎫 馬券を組む panel (betbuilder.js), from JRA's official odds pages. Read-only on JRA.
Writes the site file odds/<netkeiba race_id>.json per race that has not started yet:
  {"asof": "HH:MM", "fetched": "YYYY-MM-DD HH:MM", "o": {"1": {"6": 13.9}, "2": {"6": [2.7, 3.9]}, "4": {"6-10": 63.5},
   "5": {"6-10": [19.6, 21.1]}, "6": {"6-10": 78.1}, "7": {"6-10-13": 210.3}, "8": {"6-10-13": 1495.8}}}
Keys are 馬番 joined with '-' (ascending for 馬連・ワイド・3連複, finishing order for 馬単・3連単); 複勝・ワイド are [min, max].
JRA's pages, one per bet type and race (at most one request a second, as jra_odds): 151 単勝・複勝, 154 馬連, 155 ワイド,
156 馬単, 157 3連複, 158 3連単. Odds are as of the run (hourly on race days), not live.
  python3 combo_odds.py YYYYMMDD SITE_DIR [--races 京都11,東京11]"""
import re, os, sys, json, datetime as dt
import jra_odds
import bet_builder

PAGES = {'4': '154', '5': '155', '6': '156', '7': '157', '8': '158'}
UNORDERED = {'4', '5', '7'}
JST = jra_odds.JST


def _num(s):
    s = re.sub(r'<[^>]+>', '', s).replace('&nbsp;', '').strip()
    return float(s) if re.fullmatch(r'\d+(\.\d+)?', s) else None


def parse_combo(page, kind):
    """{'a-b[-c]': odds or [min, max]} from one JRA combination odds page."""
    t = re.sub(r'\s+', ' ', page)
    i = t.find('id="odds_list"')
    if i < 0: return {}
    out = {}
    for li in re.findall(r'<li>(.*?)</li>', t[i:]):
        heads = re.findall(r'<div class="num">\s*(\d+)\s*</div>', li)
        cap = re.search(r'<caption>\s*(\d+(?:-\d+)*)\s*</caption>', li)
        if cap: heads = cap.group(1).split('-') + heads
        if not heads: continue
        for th, td in re.findall(r'<th scope="row">\s*(\d+)\s*</th>\s*<td[^>]*>(.*?)</td>', li):
            nums = [int(x) for x in heads + [th]]
            if len(set(nums)) < len(nums): continue
            if kind in UNORDERED: nums = sorted(nums)
            mm = re.search(r'class="min">([\d.]+)<.*?class="max">([\d.]+)<', td)
            v = [float(mm.group(1)), float(mm.group(2))] if mm else _num(td)
            if v is not None: out['-'.join(map(str, nums))] = v
    return out


def race_pages(list_cname):
    """{race_no: {type: cname}} from one レース選択 page (3連複 uses its 「すべて」 page, Z99)."""
    page = jra_odds._get(list_cname)
    out = {}
    for c in set(re.findall(r"'(pw15(\d)ouS\d(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})Z(?:99)?/\w+)'", page)):
        cname, typ, R = c[0], c[1], int(c[6])
        out.setdefault(R, {})[typ] = cname
    return out


def fetch_race(pages):
    o = {}
    if '1' in pages:
        as_of, horses = jra_odds.win_odds(pages['1'])
        o['1'] = {str(h['num']): h['odds'] for h in horses if h['odds'] is not None}
        o['2'] = {str(h['num']): list(h['place']) for h in horses if h['place']}
    else:
        as_of = ''
    for kind, typ in PAGES.items():
        if typ[-1] in pages:
            pg = jra_odds._get(pages[typ[-1]])
            o[kind] = parse_combo(pg, kind)
            if not as_of:
                m = re.search(r'(\d{1,2})時(\d{2})分現在オッズ', pg)
                as_of = f'{int(m.group(1)):02d}:{m.group(2)}' if m else ''
    return as_of, o


def build(date, site, only=None, log=print):
    """Write odds/<race_id>.json for the races of date (YYYYMMDD) that have not started. Returns a summary."""
    now = dt.datetime.now(JST)
    pre = bet_builder.meeting_prefixes(date)
    meets = jra_odds.meetings(date)
    if not meets: return {'races': 0, 'note': 'JRA lists no odds for the day'}
    os.makedirs(os.path.join(site, 'odds'), exist_ok=True)
    n, skipped = 0, 0
    for venue, lc in meets.items():
        posts = {no: r['post'] for no, r in jra_odds.races(lc).items()}
        for R, pages in sorted(race_pages(lc).items()):
            if only and f'{venue}{R}' not in only: continue
            rid = bet_builder.race_id(pre, venue, R)
            if not rid: continue
            post = posts.get(R)
            if date == now.strftime('%Y%m%d') and post and post <= now.strftime('%H:%M'):
                skipped += 1; continue
            try:
                as_of, o = fetch_race(pages)
            except Exception as e:
                log(f'[combo_odds] {venue}{R}R failed: {type(e).__name__}: {e}'); continue
            if not o.get('1'): continue          # not on sale yet
            with open(os.path.join(site, 'odds', f'{rid}.json'), 'w', encoding='utf-8') as f:
                json.dump({'asof': as_of, 'fetched': now.strftime('%Y-%m-%d %H:%M'), 'o': o}, f,
                          ensure_ascii=False, separators=(',', ':'))
            n += 1
    log(f'[combo_odds] {date}: {n} races written, {skipped} already started')
    return {'races': n, 'started': skipped}


if __name__ == '__main__':
    only = None
    if '--races' in sys.argv: only = set(sys.argv[sys.argv.index('--races') + 1].split(','))
    print(build(sys.argv[1], sys.argv[2], only))
