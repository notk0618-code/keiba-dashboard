"""Model S badges on the race cards (display only; approved look: 2026/11/10 Taisuke, mock 11/8).

What it adds to restore_v7's race card (generate_mobile_race_card_v10), and nothing else:
  * every runner's line "N人気 ／ odds ／ …" gets " ／ S複勝 58%(S2位)"
  * in the 🎯 自動予想の印 box: the ◎ line gets 「S◎一致」 (◎ is S's place-probability 1st) or 「S評価低」 (S 4th or lower)
  * 「⚠ 過剰人気(参考)」 on the favourite and in the 印 box when the favourite is in the index top 5 but S ranks it 4th or lower
    (post-hoc condition from the S study: 複勝率 54% vs 69% for the other favourites; being checked on the shadow record)
AF, total_score, the marks, bets.html and every log restore_v7 writes are untouched: this only edits the returned HTML and
writes its own log (keiba_db/s_badges_log.csv). Any failure leaves the card exactly as restore_v7 made it.
Off switch: S_BADGES=0 in the environment (keiba_env.load).

S = keiba_db/s_model.py + s_model_v1.0.json + s_jra_weights.py on Drive (copies of the private keiba-research s_shadow/
s_model.py, s_model_v1.0.json, jra_weights.py with the same SHA-256 as the shadow job; the model stays out of this public repo).
Entries come from the converted 当日出走馬 file (as the shadow job), history strictly before the race day, the field is the
runners on the card (取消・除外 already dropped there), and 馬体重 is JRA's announced weight once published on the race day
(jra_weights.py); before that the previous run's weight stands in (bw_source 前走代用), as in the shadow's 暫定 stage.
Races outside S's domain (fewer than 70% of the field with a same-surface AF run, or under 6 runners) get no S display."""
import os, re, sys, glob, html, datetime as dt
import numpy as np, pandas as pd

KDB = '/content/drive/MyDrive/keiba_db'
SDIR = KDB                     # where s_model.py / s_model_v1.0.json / s_jra_weights.py live (the keiba_db mirror)
LOG_PATH = os.path.join(KDB, 's_badges_log.csv')
JST = dt.timezone(dt.timedelta(hours=9))
HURDLE = re.compile(r'障害|ジャンプ|ｼﾞｬﾝﾌﾟ|J[・･]?G[1-3]|Ｊ[・･]?Ｇ|J[・･]?S$|Ｊ[・･]?Ｓ$')
S_LOW = 4                      # S順位がこれ以下(4位以下)なら「S評価低」
FAV_IDX_MAX = 5                # 過剰人気: 1番人気が指数この順位以内 かつ S順位 S_LOW 位以下

MARKS_HEAD = "<div style='font-weight:bold; color:#234;'>🎯 自動予想の印(参考情報)</div>"
MARKS_NOTE = "<div style='color:#999; font-size:10px; margin-top:4px;'>※印は的中の目安です"
HON_LINE = re.compile(r"(<div><b>◎</b> (?:\d+|-)番 (.+?) <span style='color:#666;'>.*?</span>)(</div>)")
PILL = ("<span style='display:inline-block; font-size:11px; font-weight:bold; padding:0 7px; margin-left:4px; border-radius:10px; "
        "border:1px solid {bd}; background:{bg}; color:{fg}; white-space:nowrap;'>{t}</span>")
P_AGREE = PILL.format(bd='#0f7a5c', bg='#e3f4ee', fg='#0f7a5c', t='S◎一致')
P_LOW = PILL.format(bd='#9a5b00', bg='#fff3dc', fg='#9a5b00', t='S評価低')
P_OVER = PILL.format(bd='#c0262d', bg='#fde9ea', fg='#c0262d', t='⚠ 過剰人気(参考)')
NOTE = ("<div style='color:#999; font-size:10px; margin-top:4px;'>Sワッペン(参考・試行中): S複勝はモデルS({ver})の複勝確率と順位。"
        "「S◎一致」は◎がSでも1位、「S評価低」は◎がSで4位以下(過去の検証: ◎の複勝率はS1位で芝66%・ダート69%、S4位以下で芝50%・ダート44%)。"
        "「⚠過剰人気(参考)」は1番人気が指数5位以内なのにSで4位以下(後から見つけた条件で、過去は複勝率54%・それ以外の1番人気69%。記録して再現を確認中)。"
        "{bw}指数・印・買い目には使っていません。的中の目安で、回収率の根拠ではありません。</div>")


def entries_file(date):
    fs = [f for f in glob.glob(os.path.join(KDB, f'当日出走馬{date}*.csv')) if not re.search(r'_utf8|_特別登録_分割|バックアップ|★', f)]
    conv = [f for f in fs if '_変換済み' in f]
    return max(conv, key=os.path.getmtime) if conv else None


def entries_from_csv(path, sm):
    """Same as keiba-research s_shadow.entries_from_csv (the shadow's nightly entries)."""
    c = pd.read_csv(path, encoding='cp932', dtype=str)
    d = re.search(r'(20\d{6})', os.path.basename(path)).group(1)
    e = pd.DataFrame({'馬名': c['馬名'].str.strip(), '場所': c['場所'].str.strip(), 'R': c['競走番号'].astype(int),
                      '馬番': pd.to_numeric(c.get('馬番号', c.get('馬番')), errors='coerce'),
                      'surf': np.where(c['芝・ダ'].str.strip() == '芝', '芝', 'ダ'), 'dist': pd.to_numeric(c['距離'], errors='coerce'),
                      'cls': c['レース名'].map(sm.s_class_code), 'age': pd.to_numeric(c['年齢'], errors='coerce'),
                      'kin': pd.to_numeric(c['斤量'], errors='coerce')})
    e['date'] = pd.Timestamp(d); e['m'] = e.date.dt.month
    e['key'] = e['場所'] + '|' + d + '|' + e.R.astype(str)
    hurdle = {(v, int(r)) for v, r, n in c[['場所', '競走番号', 'レース名']].drop_duplicates(['場所', '競走番号']).values if HURDLE.search(str(n))}
    return e[[(v, r) not in hurdle for v, r in zip(e['場所'], e.R)]].copy(), d


class SDay:
    """Raw S features for one race day, computed once per run (about a minute), then scored per card."""
    def __init__(self, ns, date, log=print):
        if SDIR not in sys.path: sys.path.insert(0, SDIR)
        import s_model as sm
        self.sm, self.log, self.date = sm, log, date
        self.model = sm.load_model(os.path.join(SDIR, 's_model_v1.0.json'))
        f = entries_file(date)
        if not f: raise FileNotFoundError(f'当日出走馬{date}…_変換済み.csv not found')
        e, d = entries_from_csv(f, sm)
        if d != date: raise ValueError(f'entries file is for {d}, card is {date}')
        e['bw'] = np.nan; e['bw_pending'] = True; e['eid'] = np.arange(len(e))
        H, X = sm.load_runs(ns['con'], sm.af_from_namespace(ns))
        day = pd.Timestamp(date)
        H = H[H.date < day]; X = X[X.date < day]                     # nothing from the race day on
        self.raw = sm.raw_features(H, X, sm.resolve_hid(H, e))
        self.weights = {}
        if dt.datetime.now(JST).strftime('%Y%m%d') == date:          # JRA publishes 馬体重 on the race day only
            try:
                import s_jra_weights
                w = s_jra_weights.fetch(date)
                if len(w):
                    w = w[w['馬体重'].notna()]
                    self.weights = {(v, int(r), n): float(b) for v, r, n, b in zip(w['場所'], w.R, w['馬名'], w['馬体重'])}
            except Exception as ex:
                log(f'[s_badges] announced 馬体重 unavailable, previous weights stand in: {type(ex).__name__}: {ex}')
        log(f'[s_badges] S {self.model["version"]} ready for {date}: {self.raw.key.nunique()} races, {len(self.raw)} runners, '
            f'announced weights {len(self.weights)}')

    def race(self, venue, race_no, names):
        E = self.raw[(self.raw['場所'] == venue) & (self.raw.R == int(race_no)) & self.raw['馬名'].isin(set(names))].copy()
        if len(E) < 2: return None
        bw = [self.weights.get((venue, int(race_no), n)) for n in E['馬名']]
        E['bw'] = pd.Series(bw, index=E.index, dtype=float); E['bw_pending'] = E.bw.isna()
        return self.sm.score(self.sm.finalize(E, self.model['const']), self.model).set_index('馬名')


def _ranks(ns, rd):
    """Index rank and popularity exactly as the marks use them (_mk_prepare: runners with odds; win_prob order; odds order)."""
    g = ns['_mk_prepare'](rd) if '_mk_prepare' in ns else None
    if g is None or g.empty: return None
    ix = pd.to_numeric(g['win_prob'], errors='coerce') if 'win_prob' in g.columns else pd.to_numeric(g['total_score'], errors='coerce')
    return pd.DataFrame({'idx_rank': ix.rank(ascending=False, method='first').values,
                         'pop': g['_odds'].rank(method='min').values, 'odds': g['_odds'].values}, index=g['馬名'].values)


def decorate(main, venue, race_no, S, R):
    """Pure HTML step: S = per-horse S (index 馬名: p_place, s_rank_place); R = _ranks() or None. Returns (html, log rows)."""
    rows = []
    hon = None
    m = HON_LINE.search(main)
    if m: hon = html.unescape(m.group(2))
    over = set()
    if R is not None:
        for n, r in R[R['pop'] == 1].iterrows():
            if n in S.index and r.idx_rank <= FAV_IDX_MAX and S.at[n, 's_rank_place'] >= S_LOW: over.add(n)
    # runner lines
    for n, s in S.iterrows():
        i = main.find(f'id="mark_{venue}_{race_no}_{n}"')
        if i < 0: continue
        p = main.find('<div style="font-size:12px; color:#555; margin-top:4px;">', i)
        q = main.find('</div>', p) if p >= 0 else -1
        nxt = main.find('id="mark_', i + 1)
        if q < 0 or (0 <= nxt < q): continue
        tag = f' ／ S複勝 {s.p_place * 100:.0f}%(S{int(s.s_rank_place)}位)'
        if n == hon: tag += P_AGREE if s.s_rank_place == 1 else (P_LOW if s.s_rank_place >= S_LOW else '')
        if n in over: tag += P_OVER
        main = main[:q].rstrip() + tag + '\n          ' + main[q:]
    # 印 box: ◎ badge, 過剰人気 line, note
    if hon is not None and hon in S.index and MARKS_HEAD in main:
        sr = int(S.at[hon, 's_rank_place'])
        pill = P_AGREE if sr == 1 else (P_LOW if sr >= S_LOW else '')
        main = HON_LINE.sub(lambda mm: mm.group(1) + f" <span style='color:#666;'>S複勝{S.at[hon, 'p_place'] * 100:.0f}%(S{sr}位)</span>{pill}" + mm.group(3), main, count=1)
        rows.append(dict(区分='◎', 馬名=hon, ワッペン=('S◎一致' if sr == 1 else ('S評価低' if sr >= S_LOW else ''))))
    if over and MARKS_HEAD in main:
        txt = ''.join(f"<div style='color:#666; font-size:11px; margin-bottom:4px;'>{P_OVER} 1番人気の{html.escape(n)}({R.at[n, 'odds']:.1f}倍)は"
                      f"指数{int(R.at[n, 'idx_rank'])}位・S{int(S.at[n, 's_rank_place'])}位</div>" for n in sorted(over))
        main = main.replace(MARKS_HEAD, MARKS_HEAD + txt, 1)
    for n in sorted(over): rows.append(dict(区分='1番人気', 馬名=n, ワッペン='過剰人気'))
    if R is not None:
        for n, r in R[R['pop'] == 1].iterrows():
            if n not in over and n in S.index: rows.append(dict(区分='1番人気', 馬名=n, ワッペン=''))
    return main, rows


def _log(date, venue, race_no, S, R, rows, model):
    try:
        L = S[['馬番', 'p_win', 'p_place', 's_rank_place', 'bw_source', 'in_domain']].copy()
        L.insert(0, '馬名', L.index)
        L['指数順位'] = L['馬名'].map(R.idx_rank) if R is not None else np.nan
        L['人気'] = L['馬名'].map(R['pop']) if R is not None else np.nan
        L['単勝オッズ'] = L['馬名'].map(R.odds) if R is not None else np.nan
        tag = {(r['区分'], r['馬名']): r['ワッペン'] for r in rows}
        L['印◎'] = [('◎' if ('◎', n) in tag else '') for n in L['馬名']]
        L['ワッペン'] = ['・'.join(t for t in (tag.get(('◎', n), ''), tag.get(('1番人気', n), '')) if t) for n in L['馬名']]
        L.insert(0, 'R', int(race_no)); L.insert(0, '場所', venue); L.insert(0, 'date', f'{date[:4]}-{date[4:6]}-{date[6:]}')
        L['model_version'] = model['version']; L['model_sha256'] = model['sha256']
        L['created_jst'] = dt.datetime.now(JST).strftime('%Y-%m-%d %H:%M')
        if os.path.exists(LOG_PATH):
            old = pd.read_csv(LOG_PATH)
            old = old[~((old['date'] == L['date'].iloc[0]) & (old['場所'] == venue) & (old['R'] == int(race_no)))]
            L = pd.concat([old, L], ignore_index=True)
        L.to_csv(LOG_PATH, index=False)
    except Exception as ex:
        print(f'[s_badges] log skipped ({venue}{race_no}R): {type(ex).__name__}: {ex}')


def install(ns, log=print):
    """Wrap the race card (after pace_forecast). The card's own output is changed only by decorate()."""
    orig = ns['generate_mobile_race_card_v10']
    state = {}

    def card(venue, race_no, race_results_df, *x, **k):
        main, detail = orig(venue, race_no, race_results_df, *x, **k)
        try:
            if not main: return main, detail
            dl = re.sub(r'\D', '', str(ns.get('_card_date_label') or ''))
            date = dl if len(dl) == 8 else (f'20{dl}' if len(dl) == 6 else '')
            if not date: return main, detail
            if state.get('date') != date:
                state.clear(); state['date'] = date
                try:
                    state['day'] = SDay(ns, date, log)
                except Exception as ex:
                    state['day'] = None; log(f'[s_badges] S not available for {date}: {type(ex).__name__}: {ex}')
            day = state['day']
            if day is None: return main, detail
            rd = race_results_df[(race_results_df['場所'] == venue) & (race_results_df['R'] == race_no)]
            if rd.empty: return main, detail
            od = pd.to_numeric(rd.get('単勝オッズ'), errors='coerce') if '単勝オッズ' in rd.columns else pd.Series(np.nan, index=rd.index)
            if (od > 0).any(): rd = rd[od > 0]                # no odds while the rest of the race has them = 取消・除外 (as the shadow job)
            S = day.race(venue, race_no, rd['馬名'].astype(str).str.strip())
            if S is None or not bool(S.in_domain.iloc[0]): return main, detail
            R = _ranks(ns, rd)
            main, rows = decorate(main, venue, race_no, S, R)
            if MARKS_NOTE in main:
                pend = (S.bw_source != '発表').any()
                bw = '馬体重の発表前は前走の体重で計算し、発表後の更新で正式な値に変わります。' if pend else '馬体重は発表値です。'
                main = main.replace(MARKS_NOTE, NOTE.format(ver=day.model['version'], bw=bw) + MARKS_NOTE, 1)
            _log(date, venue, race_no, S, R, rows, day.model)
        except Exception as e:
            log(f'[s_badges] skipped ({venue}{race_no}R): {type(e).__name__}: {e}')
        return main, detail

    ns['generate_mobile_race_card_v10'] = card
