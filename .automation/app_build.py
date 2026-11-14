"""New mobile UI data (app.html): split each recent dashboard_YYMMDD.html into one JSON per race under appdata/.
Run at the end of every daily_runner job (APP_BUILD=0 turns it off). The old pages are not touched.
A race whose post time has passed keeps the JSON written before the start, so its marks and odds stay
visible after the odds refresh drops them from the dashboard page.
  python3 app_build.py SITE_DIR [YYMMDD ...]"""
import os, re, sys, json, glob, datetime
from bs4 import BeautifulSoup

ROMA = {'東京': 'tokyo', '京都': 'kyoto', '福島': 'fukushima', '中山': 'nakayama', '阪神': 'hanshin',
        '新潟': 'niigata', '中京': 'chukyo', '札幌': 'sapporo', '函館': 'hakodate', '小倉': 'kokura'}
MK = '◎○〇▲△☆✓'
JST = datetime.timezone(datetime.timedelta(hours=9))


def log(*a): print('[app]', *a, flush=True)
def txt(e): return re.sub(r'\s+', ' ', e.get_text(' ', strip=True))
def inner(e): return ''.join(str(c) for c in e.contents)


def soup_of(path):
    html = open(path, encoding='utf-8').read()
    try: return BeautifulSoup(html, 'lxml')
    except Exception: return BeautifulSoup(html, 'html.parser')


def parse_day(path, d):
    soup = soup_of(path)
    toc = soup.find(id='toc')
    if toc is None: return []
    races, venue = [], None
    for el in toc.children:
        if getattr(el, 'name', None) != 'div': continue
        if el.find('a') is None: venue = txt(el); continue
        for a in el.find_all('a'):
            sp = [txt(x) for x in a.find_all('span')]
            if len(sp) < 4: continue
            races.append(dict(anchor=a['href'][1:], venue=venue, r=int(sp[0].rstrip('R')), time=sp[1], course=sp[2], cls=sp[3]))
    out = []
    for rc in races:
        card = soup.find(id=rc['anchor'])
        if card is None or rc['venue'] not in ROMA: continue
        name_div = card.find('div', style=re.compile('font-size:19px; font-weight:bold; line-height'))
        g = name_div.find('span') if name_div else None
        grade = txt(g) if g else ''
        a = name_div.find('a') if name_div else None
        rname = txt(a) if a else (txt(name_div).replace(grade, '').strip() if name_div else rc['cls'])
        meta = txt(name_div.find_next_sibling('div')) if name_div else ''
        heads = re.search(r'(\d+)頭', meta)
        blocks = {}
        for ch in card.find_all('div', recursive=False):
            t = txt(ch)[:30]
            if '自動予想の印' in t: blocks['marks'] = inner(ch)
            elif 'レース傾向' in t: blocks['trend'] = inner(ch)
            elif 'pace-forecast' in (ch.get('class') or []) or 'ペース予想' in t: blocks['pace'] = inner(ch)
            elif t.startswith('想定'): blocks['cond'] = txt(ch.find('span')) if ch.find('span') else ''
        pf = card.find(class_='pace-forecast')
        if pf and 'pace' not in blocks: blocks['pace'] = inner(pf)
        auto = {}
        for m, no in re.findall(r'<b>([%s])</b>\s*(\d+)番' % MK, blocks.get('marks', '')): auto[int(no)] = m.replace('〇', '○')
        kb = card.find(class_='kb-bet')
        wk = {h[0]: h[2] for h in json.loads(kb['data-horses'])} if kb else {}
        horses = []
        for sel in card.find_all('select', id=re.compile('^mark_')):
            blk = sel.find_parent('div').find_parent('div')
            link = blk.find('a'); box = link.find('span') if link else None
            if not link or not box or not txt(box).isdigit(): continue
            no = int(txt(box)); lt = txt(link)
            m = re.search(r'(\d+)位\s+(.+?)\((.+?)\)', lt)
            lines = [txt(x) for x in blk.find_all('div', recursive=False)[1:]]
            info = lines[0] if lines else ''
            parts = [p.strip() for p in info.split('／')]
            def pick(rx):
                for p in parts:
                    mm = re.search(rx, p)
                    if mm: return mm.group(1)
                return ''
            sm = re.search(r'S複勝\s*(\d+)%', info); srk = re.search(r'S複勝\s*\d+%\(S(\d+)位\)', info)
            fit = re.search(r'fit補正後\s*(\d+)位', ' '.join(lines))
            mk = blocks.get('marks', '')
            warn = '人気先行' in (mk.split(f'{no}番')[1][:120] if f'{no}番' in mk else '')
            det = soup.find(id=link['href'][1:]) if link.get('href', '').startswith('#') else None
            sel.decompose()
            horses.append(dict(no=no, waku=wk.get(no, 0), rank=int(m.group(1)) if m else None, name=m.group(2) if m else lt,
                               sa=m.group(3) if m else '', icons=''.join(re.findall(r'[🔥👑📐☠💎⚡🌟⭐🆕]', lt)),
                               ninki=pick(r'^(\d+)人気'), odds=pick(r'^([\d.]+)倍'), kin=pick(r'^([\d.]+)kg'),
                               jockey=parts[3] if len(parts) > 3 and not re.search(r'kg|倍|人気', parts[3]) else '',
                               style=pick(r'^(逃げ|先行|差し|追込)'), s=int(sm.group(1)) if sm else None,
                               srank=int(srk.group(1)) if srk else None, fit=int(fit.group(1)) if fit else None,
                               auto=auto.get(no, ''), warn=warn, block=inner(blk), detail=inner(det) if det else ''))
        out.append(dict(date=d, anchor=rc['anchor'], venue=rc['venue'], r=rc['r'], time=rc['time'], course=rc['course'], cls=rc['cls'],
                        name=rname, grade=grade, graded=a['href'] if a and a.get('href') else None,
                        heads=int(heads.group(1)) if heads else len(horses), cond=blocks.get('cond', ''),
                        rid=kb['data-race-id'] if kb else '', hasMarks='marks' in blocks,
                        upset='⚠ 波乱含み<' in blocks.get('marks', ''), marks=blocks.get('marks', ''),
                        trend=blocks.get('trend', ''), pace=blocks.get('pace', ''), kb=str(kb) if kb else '', horses=horses))
    return out


def started(d, tm, now):
    try:
        t = datetime.datetime.strptime('20' + d + tm, '%Y%m%d%H:%M').replace(tzinfo=JST)
    except ValueError: return False
    return now >= t


def summary(r):
    hon = [h for h in r['horses'] if h['auto'] == '◎']
    ana = [h for h in r['horses'] if h['auto'] == '▲' and h['ninki'].isdigit() and int(h['ninki']) >= 6]
    return dict(file=f"appdata/{r['date']}_{ROMA[r['venue']]}_{r['r']}.json", venue=r['venue'], r=r['r'], time=r['time'],
                course=r['course'], cls=r['cls'], name=r['name'], grade=r['grade'], heads=r['heads'], upset=r['upset'],
                hon=dict(no=hon[0]['no'], name=hon[0]['name'], ninki=hon[0]['ninki'], odds=hon[0]['odds']) if hon else None,
                ana=[dict(no=h['no'], name=h['name'], ninki=h['ninki'], odds=h['odds'], rank=h['rank']) for h in ana])


def build(site, dates=None, now=None):
    now = now or datetime.datetime.now(JST)
    today = now.strftime('%y%m%d')
    lo = (now - datetime.timedelta(days=1)).strftime('%y%m%d'); hi = (now + datetime.timedelta(days=9)).strftime('%y%m%d')
    if not dates:
        dates = sorted(m.group(1) for f in glob.glob(f'{site}/dashboard_*.html')
                       if (m := re.search(r'dashboard_(\d{6})\.html$', f)) and lo <= m.group(1) <= hi)
    out_dir = f'{site}/appdata'; os.makedirs(out_dir, exist_ok=True)
    res = {'dates': [], 'written': 0, 'kept': 0}
    idx_path = f'{out_dir}/index.json'
    try: index = {x['date']: x for x in json.load(open(idx_path, encoding='utf-8'))}
    except Exception: index = {}
    for d in dates:
        try: races = parse_day(f'{site}/dashboard_{d}.html', d)
        except Exception as e: log(f'{d}: parse failed: {type(e).__name__}: {e}'); continue
        if not races: continue
        summ = []
        for r in races:
            fn = f"{out_dir}/{d}_{ROMA[r['venue']]}_{r['r']}.json"
            if os.path.exists(fn) and started(d, r['time'], now):
                try:
                    old = json.load(open(fn, encoding='utf-8'))
                    summ.append(summary(old)); res['kept'] += 1; continue
                except Exception: pass
            with open(fn, 'w', encoding='utf-8') as f: json.dump(r, f, ensure_ascii=False, separators=(',', ':'))
            summ.append(summary(r)); res['written'] += 1
        index[d] = dict(date=d, races=summ); res['dates'].append(d)
    keep = sorted(k for k in index if k >= lo)[-4:]
    with open(idx_path, 'w', encoding='utf-8') as f:
        json.dump([index[k] for k in keep], f, ensure_ascii=False, separators=(',', ':'))
    old_lo = (now - datetime.timedelta(days=8)).strftime('%y%m%d')
    for f in glob.glob(f'{out_dir}/[0-9]*_*.json'):
        if os.path.basename(f)[:6] < old_lo: os.remove(f)
    log(f"dates {res['dates']}: {res['written']} races written, {res['kept']} started races kept; index {keep}")
    return res


if __name__ == '__main__':
    build(sys.argv[1], sys.argv[2:] or None)
