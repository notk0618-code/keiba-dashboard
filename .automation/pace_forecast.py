"""Pace forecast for the race cards (display only; marks, 指数 and the bet list keep using restore_v7's pace v2).

Model B from the 2026-11-04 pace-model comparison (analysis/pace_model_compare/models.py), fitted live on keiba.duckdb:
  PCI = course effect (empirical Bayes, k=10) + OLS on race conditions (class, head count, age, sex, going, meeting day)
        + field make-up (逃げ/先行 counts and rates of the runners' last 5 runs, gate of the 逃げ horses).
P(ハイ/平均/スロー) = normal around the predicted PCI (residual sd by distance band), cut at the course's PCI terciles.
In the comparison B beat v2 and the course mean on PCI error and 3-class accuracy (turf 45.7% vs 39.6%), and its
probabilities are calibrated, but the most likely class over-picks ハイ (about half of the races) because the middle
band is narrow. So the label is not the arg-max: スロー寄り / ハイ寄り needs that class at P >= LEAN (0.40), else 平均.
Out-of-sample 2021-26 with that rule: turf share ハイ36/平均32/スロー32%, precision スロー 56%; dirt 25/44/30%, スロー 48%.

  python3 pace_forecast.py --db keiba.duckdb --test 2025-01-01   # fit before the date, forecast later races from
                                                                  # the same entry-side features the cards use
"""
import re, time
import numpy as np, pandas as pd
from scipy.stats import norm

LEAN = 0.40          # P(class) needed for スロー寄り / ハイ寄り
K_EB = 10            # course shrinkage (races)
TRAIN_FROM = '2017-01-01'
CLSMAP = {15: '新馬', 7: '未勝利', 23: '1勝', 43: '2勝', 67: '3勝', 115: 'OP', 131: 'OP',
          147: '重賞', 163: '重賞', 179: '重賞', 195: '重賞'}
CATS = ['clsg', 'nhb', 'ageg', 'sexg', 'baba', 'period']
MEM_CAT = ['nn', 'ns']
MEM_NUM = ['exp_lead', 'exp_top2', 'nige_gap_f', 'gap_miss', 'unknown_share', 'nige_inner', 'nige_outer']
LABELS = ['ハイ', '平均', 'スロー']
BABA = {'良': '良', '稍重': '稍', '稍': '稍', '重': '重', '不良': '不', '不': '不'}   # card labels -> DB 馬場状態
num = lambda s: pd.to_numeric(s, errors='coerce')


# ---------- features ----------
def _cond(nh, amax, female_only, nichiji, baba, cls):
    nhb = '8以下' if nh <= 8 else '9-12' if nh <= 12 else '13-15' if nh <= 15 else '16以上'
    ageg = '2歳' if amax <= 2 else '3歳' if amax <= 3 else '古馬混'
    period = '開催前半' if nichiji <= 2 else '中盤' if nichiji <= 8 else '後半'
    return {'clsg': cls, 'nhb': nhb, 'ageg': ageg, 'sexg': '牝馬限定' if female_only else '混合',
            'baba': baba, 'period': period}

def class_from_name(name):
    """Class group from the race name when the card has no クラスコード."""
    s = str(name or '')
    if re.search(r'G[1-3]|GI|Jpn|ＧI|Ｇ[１-３]', s): return '重賞'
    for k in ['新馬', '未勝利', '1勝', '2勝', '3勝']:
        if k in s or k.translate(str.maketrans('123', '１２３')) in s: return k
    return 'OP' if re.search(r'\(L\)|OP|オープン|ステークス|S$', s) else '1勝'

def _members(rows):
    """Field make-up from runner states: rows of dicts with known, nige5, top2_5, top4_5, gate ('in'/'out'/None)."""
    known = [r for r in rows if r['known']]
    nige = [r for r in known if r['nige5'] >= 0.4]
    senko = [r for r in known if r['nige5'] < 0.4 and r['top4_5'] >= 0.6]
    top = sorted((r['nige5'] for r in known), reverse=True)
    gap = top[0] - top[1] if len(top) > 1 else np.nan
    return {'n_nige': len(nige), 'n_senko': len(senko), 'exp_lead': sum(r['nige5'] for r in known),
            'exp_top2': sum(r['top2_5'] for r in known), 'nige_gap_f': 0.0 if np.isnan(gap) else gap,
            'gap_miss': int(np.isnan(gap)), 'unknown_share': 1 - len(known) / max(len(rows), 1),
            'nige_inner': sum(r['gate'] == 'in' for r in nige), 'nige_outer': sum(r['gate'] == 'out' for r in nige),
            'nn': str(min(len(nige), 3)), 'ns': str(min(len(senko), 5))}

def load_history(con):
    """Flat-race runs with the first recorded corner position, sorted by horse and date."""
    h = con.execute("""select 年,月,日,trim(場所) 場所,レース番号,馬名,血統登録番号,馬番,頭数,通過順1角,通過順2角,通過順3角,通過順4角,
                              トラックコード,芝ダート,距離,クラスコード,年齢,性別,日次,馬場状態,確定着順 from horse_race_full_named""").df()
    h['date'] = pd.to_datetime(dict(year=num(h['年']) + 2000, month=num(h['月']), day=num(h['日'])), errors='coerce')
    h['R'] = num(h['レース番号']); h['tc'] = num(h['トラックコード'])
    h = h[h['tc'].isin([0, 1, 8]) & h['date'].notna()].copy()
    for c in ['馬番', '頭数', '通過順1角', '通過順2角', '通過順3角', '通過順4角', '年齢', '確定着順']: h[c] = num(h[c])
    first = h['通過順1角'].where(h['通過順1角'] > 0)
    for c in ['通過順2角', '通過順3角', '通過順4角']: first = first.fillna(h[c].where(h[c] > 0))
    h['p1'] = first
    h['ratio'] = (h['p1'] - 1) / (h['頭数'] - 1).clip(lower=1)
    h['surf'] = np.where(h['芝ダート'].str.strip() == '芝', '芝', 'ダ')
    h['d'] = num(h['距離'])
    h['hid'] = h['血統登録番号'].where(h['血統登録番号'].notna() & (h['血統登録番号'].astype(str).str.strip() != ''), h['馬名'])
    h = h.sort_values(['hid', 'date', 'R']).reset_index(drop=True)
    g = h.groupby('hid', sort=False)
    for col, nm in [('p1', 'nige'), ('p1', 'top2'), ('p1', 'top4')]:
        lim = {'nige': 1, 'top2': 2, 'top4': 4}[nm]
        h[f'is_{nm}'] = (h['p1'] <= lim).astype(float).where(h['p1'].notna())
    # state after each run (rolling over the last 5 runs, NaN runs count as runs without a position) ...
    for nm, out in [('is_nige', 'nige5'), ('is_top2', 'top2_5'), ('is_top4', 'top4_5')]:
        h[out + '_post'] = g[nm].rolling(5, min_periods=1).mean().reset_index(level=0, drop=True)
    h['n_post'] = g['p1'].transform(lambda s: s.notna().cumsum())
    # ... and before it (what a card made on race day would have seen)
    for c in ['nige5', 'top2_5', 'top4_5', 'n']:
        h[c + '_pre'] = g[c + '_post'].shift()
    h['n_pre'] = h['n_pre'].fillna(0)
    return h

def _course_key(venue, surf, d, inout, both):
    k = f'{venue}{surf}{int(d)}'
    return k + inout if k in both else k

def build_races(h, races):
    """Race-level training rows: PCI, course, conditions and pre-race field make-up."""
    K = ['date', '場所', 'R']
    r = races.copy()
    g = h.groupby(K)
    meta = pd.DataFrame({'tc': g['tc'].first(), 'cls': g['クラスコード'].first(), 'nh': g['頭数'].max(),
                         'amax': g['年齢'].max(), 'female_only': g['性別'].apply(lambda s: (s == '牝').all()),
                         'nichiji': g['日次'].first(), 'nfin': g['確定着順'].apply(lambda s: (s > 0).sum())})
    r = r.join(meta, on=K, how='inner')
    r = r[(r['nfin'] >= 5) & r['PCI'].notna()].copy()
    r['inout'] = np.where(r['tc'] == 8, '外', '内')
    both = set(r.groupby('ck0')['inout'].nunique().loc[lambda s: s > 1].index)
    r['course'] = [_course_key(v, s, d, io, both) for v, s, d, io in zip(r['場所'], r['surf'], r['d'], r['inout'])]
    nj = num(r['nichiji'].astype(str).str.strip().replace({'A': '10', 'B': '11', 'C': '12'})).fillna(5)
    r['clsg'] = num(r['cls']).map(CLSMAP)
    cond = [_cond(nh, am, fo, n, b, c) for nh, am, fo, n, b, c in zip(r['nh'], r['amax'], r['female_only'], nj, r['baba'], r['clsg'])]
    r = pd.concat([r.reset_index(drop=True), pd.DataFrame(cond).drop(columns=['clsg', 'baba'])], axis=1)
    # field make-up from the runners' pre-race states
    x = h[['date', '場所', 'R', '馬番', '頭数', 'n_pre', 'nige5_pre', 'top2_5_pre', 'top4_5_pre']].copy()
    x['known'] = x['n_pre'] >= 2
    x['gate'] = np.where(x['馬番'] <= x['頭数'] / 3, 'in', np.where(x['馬番'] > x['頭数'] * 2 / 3, 'out', None))
    mem = {}
    for k, G in x.groupby(K, sort=False):
        mem[k] = _members([{'known': kn, 'nige5': a, 'top2_5': b, 'top4_5': c, 'gate': gt}
                           for kn, a, b, c, gt in zip(G['known'], G['nige5_pre'], G['top2_5_pre'], G['top4_5_pre'], G['gate'])])
    M = pd.DataFrame([dict(zip(K, k), **v) for k, v in mem.items()])
    return r.merge(M, on=K, how='inner'), both


# ---------- model B ----------
def _onehot(df, levels):
    out = {}
    for c in CATS + MEM_CAT:
        for l in levels[c][1:]: out[f'{c}={l}'] = (df[c] == l).astype(float).values
    for c in MEM_NUM: out[c] = df[c].astype(float).values
    return pd.DataFrame(out)

def _ols(X, y):
    Xa = np.column_stack([np.ones(len(X)), X]); return np.linalg.lstsq(Xa, y, rcond=None)[0]

def _eb(df, col):
    mu = df[col].mean(); s = df.groupby('course')[col].agg(['mean', 'count'])
    return mu, (mu + (s['mean'] - mu) * s['count'] / (s['count'] + K_EB)).to_dict()

def _bucket(d): return 'short' if d <= 1200 else 'mid' if d <= 1800 else 'long'

def fit_surface(tr):
    tr = tr.reset_index(drop=True)
    levels = {c: sorted(tr[c].dropna().astype(str).unique()) for c in CATS + MEM_CAT}
    for c in CATS + MEM_CAT: tr[c] = tr[c].astype(str)
    X = _onehot(tr, levels).values; y = tr['PCI'].values; cm_tr = np.zeros(len(tr))
    for _ in range(4):   # backfitting: OLS on conditions/members ⇄ shrunk course means of the residual
        b = _ols(X, y - cm_tr); xb = b[0] + X @ b[1:]
        mu, cm = _eb(tr.assign(_r=y - xb), '_r'); cm_tr = tr['course'].map(cm).fillna(mu).values
    fitted = cm_tr + xb
    bk = tr['d'].map(_bucket)
    sd = pd.Series(y - fitted).groupby(bk.values).std().to_dict()
    bq = tr.groupby(bk)['PCI'].quantile([1 / 3, 2 / 3]).unstack()
    cn = tr.groupby('course').size()
    cq = tr.groupby('course')['PCI'].quantile([1 / 3, 2 / 3]).unstack()[cn >= 30]
    return {'levels': levels, 'b': b, 'mu': mu, 'cm': cm, 'sd': sd,
            'bq': {k: tuple(v) for k, v in bq.iterrows()}, 'cq': {k: tuple(v) for k, v in cq.iterrows()},
            'cols': list(_onehot(tr.head(1), levels).columns), 'n': len(tr)}

def predict_rows(m, rows):
    """rows: DataFrame with course, d and the CATS/MEM columns -> (pci, P[n,3])"""
    rows = rows.reset_index(drop=True).copy()
    for c in CATS + MEM_CAT: rows[c] = rows[c].astype(str)
    X = _onehot(rows, m['levels'])[m['cols']].values
    pci = rows['course'].map(m['cm']).fillna(m['mu']).values + m['b'][0] + X @ m['b'][1:]
    bk = rows['d'].map(_bucket)
    sd = bk.map(m['sd']).values
    q = [m['cq'].get(c) or m['bq'][b] for c, b in zip(rows['course'], bk)]
    q1 = np.array([a for a, _ in q]); q2 = np.array([b for _, b in q])
    p0 = norm.cdf((q1 - pci) / sd); p1 = norm.cdf((q2 - pci) / sd) - p0
    P = np.clip(np.column_stack([p0, p1, 1 - p0 - p1]), 1e-6, 1); P /= P.sum(1, keepdims=True)
    return pci, P

def label(P):
    """0=ハイ寄り 1=平均 2=スロー寄り, from the probabilities (not the arg-max, which over-picks ハイ)."""
    P = np.atleast_2d(P)
    return np.where((P[:, 2] >= LEAN) & (P[:, 2] >= P[:, 0]), 2, np.where(P[:, 0] >= LEAN, 0, 1))


# ---------- live forecaster ----------
def load_races(con):
    r = con.execute("""select 年,月,日,trim(場所) 場所,R,芝ダート,距離,馬場状態,レースPCI from race_summary_full_named""").df()
    r['date'] = pd.to_datetime(dict(year=num(r['年']), month=num(r['月']), day=num(r['日'])), errors='coerce')
    r['R'] = num(r['R']); r['PCI'] = num(r['レースPCI'])
    r['surf'] = r['芝ダート'].str.strip().map({'芝': '芝', 'ダート': 'ダ'})
    r['d'] = num(r['距離']); r['baba'] = r['馬場状態'].str.strip()
    r = r[r['surf'].notna() & r['d'].notna() & r['date'].notna()].copy()
    r['ck0'] = r['場所'] + r['surf'] + r['d'].astype(int).astype(str)
    return r

class Forecaster:
    def __init__(self, con, train_until=None, log=print):
        t = time.time()
        self.h = load_history(con)
        races = load_races(con)
        R, self.both = build_races(self.h, races)
        R = R[R['date'] >= TRAIN_FROM]
        if train_until is not None: R = R[R['date'] < train_until]
        self.R = R
        self.models = {s: fit_surface(R[R['surf'] == s]) for s in ['芝', 'ダ']}
        # 内/外 for courses that have both: the usual one for that venue/distance/class in the last 3 years
        rec = R[R['ck0'].isin(self.both) & (R['date'] >= R['date'].max() - pd.Timedelta(days=1100))]
        self.io_cls = rec.groupby(['ck0', 'clsg'])['inout'].agg(lambda s: s.mode().iat[0]).to_dict()
        self.io_any = rec.groupby('ck0')['inout'].agg(lambda s: s.mode().iat[0]).to_dict()
        hh = self.h
        self.last = {}  # horse name -> runs (date, state after the run), for point-in-time lookups
        for name, G in hh.groupby('馬名', sort=False):
            self.last[name] = (G['date'].values, G[['nige5_post', 'top2_5_post', 'top4_5_post', 'n_post']].values)
        # meeting day (日次) history per venue for the period feature
        self.days = hh.drop_duplicates(['場所', 'date'])[['場所', 'date', '日次']].sort_values('date')
        log(f"[pace] model B fitted in {time.time() - t:.0f}s (芝 {self.models['芝']['n']}R, ダ {self.models['ダ']['n']}R)")

    def _state(self, name, date):
        x = self.last.get(name)
        if x is None: return None
        dates, vals = x
        i = np.searchsorted(dates, np.datetime64(date), side='left') - 1   # runs strictly before the race day
        return None if i < 0 else vals[i]

    def _nichiji(self, venue, date):
        """Meeting day: last known 日次 at the venue (same meeting = within 12 days) plus the weekend days since."""
        d = self.days[(self.days['場所'] == venue) & (self.days['date'] < date)]
        if d.empty: return 5
        last = d.iloc[-1]; ld = pd.Timestamp(last['date']); gap = (pd.Timestamp(date) - ld).days
        if gap > 12: return 1
        nj = num(pd.Series([str(last['日次']).strip().replace('A', '10').replace('B', '11').replace('C', '12')])).iat[0]
        days = pd.date_range(ld + pd.Timedelta(days=1), pd.Timestamp(date))
        return int((nj if pd.notna(nj) else 4) + max(1, sum(x.weekday() >= 5 for x in days)))

    def forecast(self, venue, surf, d, cls, entries, baba, date, nichiji=None, race_name=''):
        """entries: [{'name', 'num' (馬番, 0/None if not drawn), 'age', 'sex'}]. Returns a dict for the card."""
        surf = 'ダ' if str(surf).startswith('ダ') else '芝'
        date = pd.Timestamp(date)
        n = len(entries)
        rows, front = [], []
        for e in entries:
            st = self._state(e['name'], date)
            gate = None
            if e.get('num') and e['num'] > 0:
                gate = 'in' if e['num'] <= n / 3 else 'out' if e['num'] > n * 2 / 3 else None
            if st is None or st[3] < 2:
                rows.append({'known': False, 'nige5': 0, 'top2_5': 0, 'top4_5': 0, 'gate': gate}); continue
            r = {'known': True, 'nige5': float(np.nan_to_num(st[0])), 'top2_5': float(np.nan_to_num(st[1])),
                 'top4_5': float(np.nan_to_num(st[2])), 'gate': gate}
            rows.append(r)
            if r['nige5'] >= 0.4: front.append(('逃げ', e, r['nige5']))
            elif r['top4_5'] >= 0.6: front.append(('先行', e, r['top4_5']))
        clsg = CLSMAP.get(int(cls)) if cls is not None and not pd.isna(cls) else None
        clsg = clsg or class_from_name(race_name)
        ck0 = f'{venue}{surf}{int(d)}'
        io = self.io_cls.get((ck0, clsg)) or self.io_any.get(ck0, '内')
        cond = _cond(n, max([e.get('age') or 4 for e in entries] or [4]),
                     bool(entries) and all(e.get('sex') == '牝' for e in entries),
                     nichiji or self._nichiji(venue, date), BABA.get(str(baba).strip(), '良'), clsg)
        row = dict(course=_course_key(venue, surf, d, io, self.both), d=int(d), **cond, **_members(rows))
        pci, P = predict_rows(self.models[surf], pd.DataFrame([row]))
        lab = int(label(P)[0])
        front.sort(key=lambda t: (t[0] != '逃げ', -t[2]))
        return {'pci': float(pci[0]), 'p': [float(v) for v in P[0]], 'label': LABELS[lab], 'lean': lab,
                'nige': [(e.get('num'), e['name']) for k, e, _ in front if k == '逃げ'],
                'senko': [(e.get('num'), e['name']) for k, e, _ in front if k == '先行'],
                'known': sum(r['known'] for r in rows), 'n': n, 'course': row['course']}


# ---------- card HTML ----------
def _names(lst):
    return '、'.join((f'{int(no)}' + ' ' if no else '') + nm for no, nm in lst) if lst else 'なし'

def card_html(fc):
    ph, pa, ps = (round(v * 100) for v in fc['p'])
    color = {'スロー': '#2e7d32', 'ハイ': '#c62828', '平均': '#555'}[fc['label']]
    head = f"{fc['label']}寄り" if fc['label'] != '平均' else '平均'
    note = '' if fc['known'] >= fc['n'] * 0.6 else '<span style="color:#999;">（過去の位置取りが少ない馬が多く参考程度）</span>'
    bar = (f'<div style="display:flex; height:6px; border-radius:3px; overflow:hidden; margin:3px 0 4px 0;">'
           f'<div style="width:{ph}%; background:#ef9a9a;"></div><div style="width:{pa}%; background:#cfd8dc;"></div>'
           f'<div style="width:{ps}%; background:#a5d6a7;"></div></div>')
    return (f'<div class="pace-forecast" style="margin:0 10px 8px 10px; font-size:12px; background:#f7f9fb; border:1px solid #d5dde5; '
            f'border-radius:6px; padding:6px 10px; line-height:1.5;">'
            f'<div><b>🏇 ペース予想</b> <b style="color:{color};">{head}</b>'
            f'<span style="color:#666;">（スロー {ps}%・平均 {pa}%・ハイ {ph}%）</span></div>{bar}'
            f'<div style="color:#444;">逃げ: {_names(fc["nige"])}／先行: {_names(fc["senko"])}</div>'
            f'<div style="font-size:10px; color:#999;">参考表示です。印・指数には使っていません。{note}</div></div>')

FOOTER = '<div style="background:#eef2f7; color:#555; padding:4px 10px; font-size:11px;">'

def install(ns, log=print):
    """Wrap restore_v7's race card (generate_mobile_race_card_v10) to add the pace forecast panel.
    Everything else on the card is untouched; any failure leaves the card as it was."""
    orig = ns['generate_mobile_race_card_v10']
    state = {}

    def card(venue, race_no, race_results_df, *x, **k):
        main, detail = orig(venue, race_no, race_results_df, *x, **k)
        try:
            if not main or FOOTER not in main: return main, detail
            if 'fc' not in state:
                state['fc'] = None
                state['fc'] = Forecaster(ns['con'], log=log)
            if state['fc'] is None: return main, detail
            rd = race_results_df[(race_results_df['場所'] == venue) & (race_results_df['R'] == race_no)]
            if rd.empty: return main, detail
            r0 = rd.iloc[0]
            if '障' in str(r0.get('芝・ダ')): return main, detail
            dl = str(ns.get('_card_date_label') or '')
            date = pd.to_datetime(dl if len(dl) == 8 else f'20{dl}', format='%Y%m%d', errors='coerce')
            if pd.isna(date): return main, detail
            tc = x[3] if len(x) > 3 else k.get('track_conditions')
            baba = ns['get_track_label'](tc, venue, r0['芝・ダ'], race_no=race_no)
            ents = [{'name': nm, 'num': int(no) if pd.notna(no) and str(no).replace('.0', '').isdigit() else 0,
                     'age': int(a) if str(a).isdigit() else None, 'sex': s}
                    for nm, no, a, s in zip(rd['馬名'], num(rd['馬番']), rd['年齢'].astype(str), rd['性別'])]
            if len(ents) > 18:   # 特別登録 with more horses than the gate holds: the field make-up is not known yet
                note = (f'<div class="pace-forecast" style="margin:0 10px 8px 10px; font-size:11px; color:#777;">🏇 ペース予想は'
                        f'登録{len(ents)}頭（フルゲート超）のため、出走馬が決まってから表示します。</div>')
                main = main.replace(FOOTER, note + FOOTER, 1)
                return re.sub(r'(想定: [^<]*?馬場)・[^<]*?ペース', r'\1', main, count=1), detail
            fc = state['fc'].forecast(venue, r0['芝・ダ'], r0['距離'], num(pd.Series([r0.get('クラスコード')])).iat[0],
                                      ents, baba, date, race_name=x[2] if len(x) > 2 else k.get('race_name', ''))
            main = main.replace(FOOTER, card_html(fc) + FOOTER, 1)
            # the footer showed pace v2's label; the card now shows the forecast above, so keep only the going there
            main = re.sub(r'(想定: [^<]*?馬場)・[^<]*?ペース', r'\1', main, count=1)
        except Exception as e:
            log(f'[pace] forecast skipped ({venue}{race_no}R): {type(e).__name__}: {e}')
        return main, detail

    ns['generate_mobile_race_card_v10'] = card


# ---------- backtest of the live path ----------
if __name__ == '__main__':
    import argparse, duckdb
    ap = argparse.ArgumentParser(); ap.add_argument('--db', required=True); ap.add_argument('--test', default='2025-01-01')
    a = ap.parse_args()
    con = duckdb.connect(a.db, read_only=True)
    F = Forecaster(con, train_until=a.test)
    h = F.h; races = load_races(con)
    R, _ = build_races(h, races)
    te = R[R['date'] >= a.test]
    by = {k: G for k, G in h[h['date'] >= a.test].groupby(['date', '場所', 'R'])}
    out = []
    for _, r in te.iterrows():
        G = by[(r['date'], r['場所'], r['R'])]
        ents = [{'name': nm, 'num': int(no) if pd.notna(no) else 0, 'age': int(ag) if pd.notna(ag) else None, 'sex': sx}
                for nm, no, ag, sx in zip(G['馬名'], G['馬番'], G['年齢'], G['性別'])]
        fc = F.forecast(r['場所'], r['surf'], r['d'], num(pd.Series([r['cls']])).iat[0], ents, r['baba'], r['date'])
        m = F.models[r['surf']]; q = m['cq'].get(r['course']) or m['bq'][_bucket(r['d'])]
        y = 0 if r['PCI'] <= q[0] else 1 if r['PCI'] <= q[1] else 2
        out.append(dict(surf=r['surf'], y=y, lean=fc['lean'], am=int(np.argmax(fc['p'])), ll=-np.log(fc['p'][y]),
                        err=fc['pci'] - r['PCI'], ps=fc['p'][2], cm=fc['course'] == r['course']))
    O = pd.DataFrame(out)
    for s, x in O.groupby('surf'):
        print(s, len(x), 'MAE', round(x['err'].abs().mean(), 3), 'LL3', round(x['ll'].mean(), 4),
              'acc(lean)', round((x['y'] == x['lean']).mean(), 3), 'acc(argmax)', round((x['y'] == x['am']).mean(), 3),
              'course match', round(x['cm'].mean(), 3))
        print('  true', (np.bincount(x['y'], minlength=3) / len(x)).round(3), 'lean', (np.bincount(x['lean'], minlength=3) / len(x)).round(3),
              'argmax', (np.bincount(x['am'], minlength=3) / len(x)).round(3))
        print('  precision by lean', [round((x[x['lean'] == k]['y'] == k).mean(), 3) for k in range(3)])
        x = x.assign(b=pd.cut(x['ps'], [0, .2, .3, .4, .5, .6, 1]))
        print('  P(スロー) calibration', x.groupby('b', observed=True).agg(n=('y', 'size'), pred=('ps', 'mean'), obs=('y', lambda v: (v == 2).mean())).round(3).to_dict('index'))
