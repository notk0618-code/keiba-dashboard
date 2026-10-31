"""Bet list for review (bets_YYMMDD.html / .csv + bets.html = latest) from a day's prediction_log. Nothing is ever voted:
the page is a checklist the owner reviews before voting by hand or through TARGET/IPATGOX on their own PC.

Rule (v2, 2026-10-31): bet only when the expected value is clearly above 1 at JRA's current odds.
- 単勝: p = ALPHA × model win prob (較正後勝率, normalised per race) + (1-ALPHA) × market prob (1/odds, normalised).
  Live logs 7/26〜10/26 showed the raw model is overconfident where it disagrees with the market (EV>=1 picks: predicted
  19% wins, actual 13.8%), so it is shrunk toward the market. EV = p × 単勝オッズ.
- 複勝: p = ALPHA × recalibrated place_prob (PLACE_CALIB) + (1-ALPHA) × market place prob (1/複勝オッズ中央値, normalised to the number of places paid).
  EV = p × 複勝オッズ下限 (the conservative end of JRA's range).
- Candidate when EV >= EV_MIN (rule 'EV').
Rule 指数穴 (2026-10-31): the raw index (total_score) is in the race's top IDX_TOP while the horse is only POP_MIN-th
favourite or lower at the current odds, 単勝 and 複勝 both. 較正後勝率 is fitted with the odds as an input, so it
follows the market and the EV rule never picks these; on the 7/26〜10/26 logs (指数2位以内・6番人気以下, n=505, 32 days)
単勝 returned 128% (90% interval by day 77〜188%, 97% without the three biggest payouts) and 複勝 100% (75〜129%).
- Stake is a flat UNIT while the rule is being verified; the quarter-Kelly amount for a
  BANKROLL is shown for reference only. No progressive (martingale) staking.
Decisions are frozen per race once its post time has passed: later runs keep those rows, so bets_*.csv records what the
list said before each race, and the page's record is computed from those files and the DB results."""
import os, glob, html, json, datetime as dt
import numpy as np
import pandas as pd

ALPHA = 0.5         # weight of the model vs the market (fitted on the first half of the 7/26〜10/26 logs)
EV_MIN = 1.1        # minimum expected value (payout per yen) to list a bet
UNIT = 100          # yen per bet while verifying
CAPS = {'EV': 3000, '指数穴': 4000}   # yen per day for each rule; past it, the lowest-EV bets are dropped
IDX_TOP = 2         # 指数穴: index rank in the race at most this
POP_MIN = 6         # 指数穴: popularity (by current win odds) at least this
BANKROLL = 10000    # yen, only for the quarter-Kelly reference amount
KELLY_CAP = 1000    # yen, cap on the reference amount
VERSION = 'v2'
# place_prob → actual 3着内 rate, binned on the live logs 7/26〜10/26 (11.9k horses). The raw value runs high for
# long shots (0.10-0.15 → 8%) and favourites (0.6+ → about 60%), which otherwise shows up as fake value
PLACE_CALIB = ([0, .05, .10, .15, .20, .25, .30, .35, .40, .50, .60, .80, 1.0],
               [0, .05, .06, .10, .17, .25, .29, .36, .45, .53, .59, .65, .68])
LABEL = {'EV': '🎯期待値', '指数穴': '🐎指数上位の人気薄'}
JST = dt.timezone(dt.timedelta(hours=9))
COLS = ['発走', '場所', 'R', '券種', '馬番', '馬名', '金額', 'オッズ', '推定確率', '期待値', 'ケリー参考', '根拠', '版']

def _norm(s): return s / s.sum() if s.sum() > 0 else s

def candidates(log, jra):
    """Every bet either rule lists for the races in `log`, using JRA's odds when present (else the log's 単勝オッズ)."""
    h = {(v, no, x['num']): x for v, rs in (jra or {}).items() for no, r in rs.items() for x in r.get('horses', [])}
    rows = []
    for (venue, R), g in log.groupby(['場所', 'R']):
        g = g[g['馬番'].notna()].copy()
        g['num'] = g['馬番'].astype(int)
        j = [h.get((venue, int(R), n)) for n in g['num']]
        g['o'] = [x['odds'] if x and x.get('odds') else o for x, o in zip(j, pd.to_numeric(g['単勝オッズ'], errors='coerce'))]
        g['plo'] = [x['place'][0] if x and x.get('place') else None for x in j]
        g['pmid'] = [sum(x['place']) / 2 if x and x.get('place') else None for x in j]
        g = g[g['o'] > 0]  # 取消・除外
        if len(g) < 2 or g['較正後勝率'].isna().all(): continue
        p_win = ALPHA * _norm(g['較正後勝率'].fillna(0)) + (1 - ALPHA) * _norm(1 / g['o'])
        gap = (g['total_score'].rank(ascending=False, method='first') <= IDX_TOP) & (g['o'].rank(method='min') >= POP_MIN)
        for i, r in g.iterrows():
            rows.append(dict(場所=venue, R=int(R), 券種='単勝', 馬番=r['num'], 馬名=r['馬名'], オッズ=float(r['o']), 推定確率=float(p_win[i]), gap=bool(gap[i])))
        if g['pmid'].notna().all() and g['place_prob'].notna().all():
            places = 2 if len(g) <= 7 else 3
            p_pl = (ALPHA * np.interp(g['place_prob'], *PLACE_CALIB) + (1 - ALPHA) * places * _norm(1 / g['pmid'])).clip(upper=0.95)
            for i, r in g.iterrows():
                rows.append(dict(場所=venue, R=int(R), 券種='複勝', 馬番=r['num'], 馬名=r['馬名'], オッズ=float(r['plo']), 推定確率=float(p_pl[i]), gap=bool(gap[i])))
    df = pd.DataFrame(rows, columns=['場所', 'R', '券種', '馬番', '馬名', 'オッズ', '推定確率', 'gap'])
    df['期待値'] = df['推定確率'] * df['オッズ']
    ev = (df['期待値'] >= EV_MIN) & (df['オッズ'] > 1)
    df['根拠'] = np.where(ev, 'EV', '指数穴')  # a bet both rules pick counts as EV
    df = df[ev | df['gap'].astype(bool)].drop(columns='gap').copy()
    kelly = ((df['推定確率'] * df['オッズ'] - 1) / (df['オッズ'] - 1) / 4).clip(lower=0)
    df['ケリー参考'] = (BANKROLL * kelly).clip(upper=KELLY_CAP).floordiv(100).mul(100).astype(int)
    df['金額'] = UNIT
    df['推定確率'] = df['推定確率'].round(3); df['期待値'] = df['期待値'].round(2)
    return df

def _results(con, date8):
    y, m, d = int(date8[:4]) % 100, int(date8[4:6]), int(date8[6:])
    return con.execute(f"""select 場所, cast(R as int) R, {','.join(f'単勝{i}_馬番, 単勝{i}_配当' for i in range(1, 4))},
        {','.join(f'複勝{i}_馬番, 複勝{i}_配当' for i in range(1, 6))} from race_summary_full_named
        where cast(年 as int)%100={y} and cast(月 as int)={m} and cast(日 as int)={d}""").df()

def _pay(row, res):
    kind = row['券種']
    for i in range(1, 4 if kind == '単勝' else 6):
        b, p = res.get(f'{kind}{i}_馬番'), res.get(f'{kind}{i}_配当')
        if pd.notna(b) and pd.notna(p) and str(b).strip().isdigit() and int(b) == int(row['馬番']): return float(p) * row['金額'] / 100
    return 0.0

def track_record(con, site, date6):
    """{(根拠, 券種): {'n', 'hit', 'stake', 'ret', 'days', 'since'}} from earlier v2 bets_*.csv whose day has results in the DB."""
    out = {}
    for f in sorted(glob.glob(os.path.join(site, 'bets_[0-9][0-9][0-9][0-9][0-9][0-9].csv'))):
        d = os.path.basename(f)[5:11]
        if d >= date6: continue
        b = pd.read_csv(f, encoding='utf-8-sig')
        if '版' not in b.columns or b.empty: continue
        b = b[b['版'] == VERSION]
        res = _results(con, '20' + d)
        if b.empty or res.empty: continue
        res = {(r['場所'], int(r['R'])): r for _, r in res.iterrows()}
        for _, r in b.iterrows():
            rr = res.get((r['場所'], int(r['R'])))
            if rr is None: continue
            t = out.setdefault((r.get('根拠', 'EV'), r['券種']), {'n': 0, 'hit': 0, 'stake': 0, 'ret': 0.0, 'days': set(), 'since': d})
            p = _pay(r, rr)
            t['n'] += 1; t['hit'] += p > 0; t['stake'] += int(r['金額']); t['ret'] += p; t['days'].add(d)
    return out

def _page(date6, bets, dropped, rec, as_of):
    e = html.escape
    day = f'20{date6[:2]}/{date6[2:4]}/{date6[4:]}'
    recs = ''
    for rule, kind in [(r, k) for r in CAPS for k in ('単勝', '複勝')]:
        t = rec.get((rule, kind))
        if not t: recs += f'<li>{LABEL[rule]} {kind}: まだ結果の出た記録がありません（記録は2026/11/1から）</li>'; continue
        roi = t['ret'] / t['stake'] * 100
        warn = ' <b style="color:#c00;">100%未満</b>' if roi < 100 else ''
        recs += (f"<li>{LABEL[rule]} {kind}: {t['n']}点（{len(t['days'])}日分・20{t['since'][:2]}/{t['since'][2:4]}/{t['since'][4:]}〜）"
                 f" 的中{t['hit']}点・投資{t['stake']:,}円・払戻{t['ret']:,.0f}円・回収率{roi:.0f}%{warn}</li>")
    trs = ''
    for _, b in bets.iterrows():
        trs += (f"<tr data-post='{e(str(b['発走']))}'><td>{e(str(b['発走']))}</td><td>{e(b['場所'])}{b['R']}R</td><td>{b['券種']}</td>"
                f"<td class='n'><b>{b['馬番']}</b> {e(b['馬名'])}</td><td>{b['金額']:,}円</td><td>{b['オッズ']:.1f}</td>"
                f"<td>{b['推定確率']:.0%}</td><td><b>{b['期待値']:.2f}</b></td><td>{b['ケリー参考']:,}円</td><td>{LABEL.get(b['根拠'], e(str(b['根拠'])))}</td></tr>")
    total = int(bets['金額'].sum()) if len(bets) else 0
    asof = '、'.join(f'{e(v)} {e(t)}' for v, t in (as_of or {}).items() if t)
    asof = f'JRA {asof}時点' if asof else '直近の取得分'
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>買い目リスト {day}</title><style>
body{{font-family:sans-serif;margin:0;padding:12px 16px;background:#fff;color:#111;max-width:820px}}
h1{{font-size:18px;margin:4px 0}} .note{{font-size:12px;color:#555;line-height:1.6}} ul{{font-size:13px;padding-left:18px}}
table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{border-bottom:1px solid #ddd;padding:6px 4px;text-align:left;white-space:nowrap}} td.n{{white-space:normal}}
th{{background:#111;color:#fff;position:sticky;top:0}} tr.done td{{color:#bbb;text-decoration:line-through}}
.wrap{{overflow-x:auto}} .warn{{background:#fff4e5;border:1px solid #f0b060;border-radius:6px;padding:8px;font-size:12px;margin:8px 0}}
</style></head><body>
<a href="index.html" style="font-size:12px;">← ダッシュボード</a>
<h1>買い目リスト {day}（確認用）</h1>
<div class="warn">これは投票候補の一覧です。自動では投票しません。オッズは{asof}です。締切までにオッズは動くので、条件を満たしたままか確認し、納得したものだけをご自身で投票してください。</div>
<div class="note">{LABEL['EV']}: 期待値（推定確率×オッズ）が{EV_MIN:.1f}以上。推定確率はモデルと市場（オッズ）を{ALPHA:.0%}ずつ混ぜた値、複勝のオッズは下限です。<br>
{LABEL['指数穴']}: 指数がレース内{IDX_TOP}位以内なのに、現在のオッズで{POP_MIN}番人気以下の馬（単勝と複勝）。両方に当てはまる馬は🎯として数えます。<br>
検証中のため1点{UNIT:,}円・1日の上限は🎯{CAPS['EV']:,}円・🐎{CAPS['指数穴']:,}円。合計 <b>{len(bets)}点 {total:,}円</b>{f'（上限を超えたため期待値の低い順に{dropped}点を外しています）' if dropped else ''}。
「ケリー参考」は資金{BANKROLL:,}円で1/4ケリーにした場合の金額（上限{KELLY_CAP:,}円）で、参考表示です。負けを取り戻すために賭け金を増やす買い方はしません。</div>
<div class="note">これまでの実績（各レースの発走前に出していた候補を、確定払戻で集計）</div><ul>{recs}</ul>
<div class="wrap"><table><tr><th>発走</th><th>レース</th><th>券種</th><th>馬番 馬名</th><th>金額</th><th>オッズ</th><th>推定確率</th><th>期待値</th><th>ケリー参考</th><th>根拠</th></tr>{trs or '<tr><td colspan=10>本日の候補はありません</td></tr>'}</table></div>
<div class="note" style="margin-top:8px;">CSV: <a href="bets_{date6}.csv">bets_{date6}.csv</a>。発走時刻を過ぎた行は薄く表示され、その時点の内容で記録に残ります。</div>
<script>(function(){{  // grey out rows whose post time has passed (JST)
var n=new Date(Date.now()+9*3600e3),z=function(x){{return String(x).padStart(2,'0')}};
var today=n.getUTCFullYear()+'/'+z(n.getUTCMonth()+1)+'/'+z(n.getUTCDate()),hm=z(n.getUTCHours())+':'+z(n.getUTCMinutes());
if(today<'{day}')return;
document.querySelectorAll('tr[data-post]').forEach(function(r){{var p=r.getAttribute('data-post');if(today>'{day}'||(p&&p<=hm))r.className='done'}})}})();</script>
</body></html>"""

def build(con, kdb, site, date6, jra=None, now=None):
    """Write bets_{date6}.html/.csv and bets.html into the site clone. Returns a summary dict for the runner RESULT."""
    path = f'{kdb}/prediction_log_{date6}.parquet'
    if not os.path.exists(path): return {'error': f'no {os.path.basename(path)}'}
    jra = jra or {}
    try:  # post times saved by the predictions (keyed '場所_R'); JRA's current list wins
        saved = json.load(open(f'{kdb}/post_time_history.json', encoding='utf-8')).get(f'20{date6}', {})
    except Exception:
        saved = {}
    posts = {(k.rsplit('_', 1)[0], int(k.rsplit('_', 1)[1])): t for k, t in saved.items() if '_' in k}
    posts.update({(v, no): r['post'] for v, rs in jra.items() for no, r in rs.items() if r.get('post')})
    now = now or dt.datetime.now(JST)
    today, hm = now.strftime('%y%m%d'), now.strftime('%H:%M')
    closed = lambda v, R: date6 < today or (date6 == today and posts.get((v, R), '99:99') <= hm)

    # races whose post time has passed keep the rows an earlier run wrote for them
    csv_path = os.path.join(site, f'bets_{date6}.csv')
    kept = None
    if os.path.exists(csv_path):
        old = pd.read_csv(csv_path, encoding='utf-8-sig')
        if '版' in old.columns:
            kept = old[(old['版'] == VERSION) & np.array([closed(v, int(R)) for v, R in zip(old['場所'], old['R'])], dtype=bool)]
    log = pd.read_parquet(path)
    log = log[[not closed(v, int(R)) for v, R in zip(log['場所'], log['R'])]]
    new = candidates(log, jra)
    new['発走'] = [posts.get((v, R), '') for v, R in zip(new['場所'], new['R'])]
    new['版'] = VERSION

    if kept is not None and '根拠' not in kept.columns: kept = kept.assign(根拠='EV')
    new = new.sort_values('期待値', ascending=False)
    parts = []
    for rule, cap in CAPS.items():
        spent = int(kept.loc[kept['根拠'] == rule, '金額'].sum()) if kept is not None else 0
        n = new[new['根拠'] == rule]
        parts.append(n[n['金額'].cumsum() <= cap - spent])
    keep_new = pd.concat(parts)
    dropped = len(new) - len(keep_new)
    bets = pd.concat([x for x in (kept, keep_new[COLS]) if x is not None and len(x)] or [keep_new[COLS]], ignore_index=True).sort_values(['発走', '場所', 'R', '券種'])
    bets['R'] = bets['R'].astype(int); bets['馬番'] = bets['馬番'].astype(int)
    bets['金額'] = bets['金額'].astype(int); bets['ケリー参考'] = bets['ケリー参考'].astype(int)
    try:
        rec = track_record(con, site, date6)
    except Exception as ex:
        print(f'[bets] track record unavailable: {ex}'); rec = {}
    as_of = {v: max((r.get('as_of') or '' for r in rs.values()), default='') for v, rs in jra.items()}
    page = _page(date6, bets, dropped, rec, as_of)
    for name in (f'bets_{date6}.html', 'bets.html'):
        open(os.path.join(site, name), 'w', encoding='utf-8').write(page)
    bets[COLS].to_csv(csv_path, index=False, encoding='utf-8-sig')
    out = {'bets': len(bets), 'kept': 0 if kept is None else len(kept), 'yen': int(bets['金額'].sum()), 'dropped': dropped,
           'by_rule': bets.groupby('根拠').size().to_dict(),
           'record': {'/'.join(k): {'n': v['n'], 'roi': round(v['ret'] / v['stake'] * 100)} for k, v in rec.items()}}
    print(f'[bets] bets_{date6}.html ' + json.dumps(out, ensure_ascii=False))
    return out
