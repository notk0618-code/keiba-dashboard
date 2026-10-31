"""Bet list for review (bets_YYMMDD.html / .csv + bets.html = latest) from a day's prediction_log. Nothing is ever voted:
the page is a checklist the owner reviews before voting by hand or through TARGET/IPATGOX on their own PC.
Rules come straight from the existing marks: 単勝 = 狙い目EV (較正後EV>=0.95 and top EV in the race by a gap),
複勝 = 狙い目本命 (guardrail pick). Each rule shows its live record from every earlier prediction_log with results in the DB,
so the page says plainly when a rule has not been beating the takeout."""
import os, glob, html, json, datetime as dt
import pandas as pd

UNIT = 100          # yen per bet
DAILY_CAP = 3000    # yen per day; past it, the weakest bets are dropped (lowest 較正後EV / 本命自信度 first)
RULES = [('単勝', '狙い目EV', '🎯狙い目（単勝の妙味）'), ('複勝', '狙い目本命', '🔥狙い目本命（複勝の堅さ）')]
SHORT = {'狙い目EV': '🎯狙い目', '狙い目本命': '🔥本命'}

def _results(con, years):
    yrs = ','.join(str(y % 100) for y in years)
    h = con.execute(f"""select 2000+cast(年 as int)%100 y, cast(月 as int) m, cast(日 as int) dd, 場所, cast(レース番号 as int) R, 馬名,
        try_cast(馬番 as int) ban, try_cast(確定着順 as int) pos from horse_race_full_named where cast(年 as int)%100 in ({yrs})""").df()
    r = con.execute(f"""select 2000+cast(年 as int)%100 y, cast(月 as int) m, cast(日 as int) dd, 場所, cast(R as int) R,
        {','.join(f'単勝{i}_馬番, 単勝{i}_配当' for i in range(1, 4))}, {','.join(f'複勝{i}_馬番, 複勝{i}_配当' for i in range(1, 6))}
        from race_summary_full_named where cast(年 as int)%100 in ({yrs})""").df()
    return h.merge(r, on=['y', 'm', 'dd', '場所', 'R'], how='left')

def _pay(row, kind):
    for i in range(1, 4 if kind == '単勝' else 6):
        b, p = row.get(f'{kind}{i}_馬番'), row.get(f'{kind}{i}_配当')
        if pd.notna(b) and pd.notna(p) and str(b).strip().isdigit() and int(b) == row['ban']: return float(p)
    return 0.0

def track_record(con, kdb, date6):
    """{rule column: {'n', 'hit', 'roi', 'days', 'since'}} over earlier days that already have results."""
    logs = []
    for f in sorted(glob.glob(f'{kdb}/prediction_log_[0-9][0-9][0-9][0-9][0-9][0-9].parquet')):
        d = os.path.basename(f)[15:21]
        if d >= date6: continue
        df = pd.read_parquet(f)
        if not all(c in df.columns for _, c, _ in RULES): continue  # logs from before the rules existed
        df = df[['場所', 'R', '馬名'] + [c for _, c, _ in RULES]].copy()
        df['y'], df['m'], df['dd'], df['d'] = 2000 + int(d[:2]), int(d[2:4]), int(d[4:]), d
        logs.append(df)
    if not logs: return {}
    L = pd.concat(logs, ignore_index=True)
    M = L.merge(_results(con, sorted(L['y'].unique())), on=['y', 'm', 'dd', '場所', 'R', '馬名'])
    M = M[M['pos'].notna()]
    out = {}
    for kind, col, _ in RULES:
        s = M[M[col] == True]
        if s.empty: continue
        pays = s.apply(lambda r: _pay(r, kind), axis=1)
        out[col] = {'n': len(s), 'hit': float((pays > 0).mean()), 'roi': float(pays.sum() / len(s)),
                    'days': int(s['d'].nunique()), 'since': s['d'].min()}
    return out

def candidates(log, posts):
    rows = []
    for kind, col, label in RULES:
        for _, r in log[log[col] == True].iterrows():
            odds = pd.to_numeric(r.get('単勝オッズ'), errors='coerce')
            if pd.isna(odds) or odds <= 0 or pd.isna(r.get('馬番')): continue  # 取消・除外, or no odds yet
            key = r['較正後EV'] if kind == '単勝' else r['本命自信度']
            rows.append({'発走': posts.get((r['場所'], int(r['R'])), ''), '場所': r['場所'], 'R': int(r['R']), '券種': kind,
                         '馬番': int(r['馬番']), '馬名': r['馬名'], '金額': UNIT, '単勝オッズ': float(odds),
                         '根拠': SHORT[col] + (f"・{r['狙い目EV確度']}" if kind == '単勝' and r.get('狙い目EV確度') else ''),
                         '較正後EV': round(float(r['較正後EV']), 3) if pd.notna(r.get('較正後EV')) else None,
                         '複勝確率': round(float(r['place_prob']), 3) if pd.notna(r.get('place_prob')) else None,
                         '_key': float(key) if pd.notna(key) else 0.0})
    df = pd.DataFrame(rows)
    if df.empty: return df, 0
    df = df.sort_values('_key', ascending=False)
    keep = df[df['金額'].cumsum() <= DAILY_CAP] if DAILY_CAP else df
    return keep.sort_values(['発走', '場所', 'R', '券種']).drop(columns='_key'), len(df) - len(keep)

def _page(date6, bets, dropped, rec, as_of):
    e = html.escape
    day = f'20{date6[:2]}/{date6[2:4]}/{date6[4:]}'
    recs = ''
    for kind, col, label in RULES:
        t = rec.get(col)
        if not t: recs += f'<li>{e(label)}: まだ結果のある記録がありません</li>'; continue
        warn = ' <b style="color:#c00;">100%未満（買い続けると減る見込み）</b>' if t['roi'] < 100 else ''
        recs += (f"<li>{e(label)} {kind}: {t['n']}点（{t['days']}日分・20{t['since'][:2]}/{t['since'][2:4]}/{t['since'][4:]}〜）"
                 f" 的中率{t['hit']:.0%}・回収率{t['roi']:.0f}%{warn}</li>")
    trs = ''
    for _, b in bets.iterrows():
        trs += (f"<tr data-post='{e(b['発走'])}'><td>{e(b['発走'])}</td><td>{e(b['場所'])}{b['R']}R</td><td>{b['券種']}</td>"
                f"<td class='n'><b>{b['馬番']}</b> {e(b['馬名'])}</td><td>{b['金額']:,}円</td><td>{b['単勝オッズ']:.1f}</td><td>{e(b['根拠'])}</td></tr>")
    total = int(bets['金額'].sum()) if len(bets) else 0
    asof = '、'.join(f'{e(v)} {e(t)}' for v, t in (as_of or {}).items() if t) or '取得時刻不明'
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>買い目リスト {day}</title><style>
body{{font-family:sans-serif;margin:0;padding:12px 16px;background:#fff;color:#111;max-width:760px}}
h1{{font-size:18px;margin:4px 0}} .note{{font-size:12px;color:#555;line-height:1.6}} ul{{font-size:13px;padding-left:18px}}
table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{border-bottom:1px solid #ddd;padding:6px 4px;text-align:left;white-space:nowrap}} td.n{{white-space:normal}}
th{{background:#111;color:#fff;position:sticky;top:0}} tr.done td{{color:#bbb;text-decoration:line-through}}
.wrap{{overflow-x:auto}} .warn{{background:#fff4e5;border:1px solid #f0b060;border-radius:6px;padding:8px;font-size:12px;margin:8px 0}}
</style></head><body>
<a href="index.html" style="font-size:12px;">← ダッシュボード</a>
<h1>買い目リスト {day}（確認用）</h1>
<div class="warn">これは投票候補の一覧です。自動では投票しません。オッズは{asof}時点です。締切前にJRAの最新オッズと出走取消を確認し、納得したものだけをご自身で投票してください。</div>
<div class="note">1点{UNIT:,}円・1日の上限{DAILY_CAP:,}円。合計 <b>{len(bets)}点 {total:,}円</b>{f'（上限を超えたため弱い順に{dropped}点を外しています）' if dropped else ''}。発走時刻を過ぎた行は薄く表示されます。</div>
<div class="note">これまでの実績（予想時点のオッズで選んだ候補、確定払戻で集計）</div><ul>{recs}</ul>
<div class="wrap"><table><tr><th>発走</th><th>レース</th><th>券種</th><th>馬番 馬名</th><th>金額</th><th>単勝</th><th>根拠</th></tr>{trs or '<tr><td colspan=7>本日の候補はありません</td></tr>'}</table></div>
<div class="note" style="margin-top:8px;">CSV: <a href="bets_{date6}.csv">bets_{date6}.csv</a></div>
<script>(function(){{  // grey out rows whose post time has passed (JST)
var n=new Date(Date.now()+9*3600e3),z=function(x){{return String(x).padStart(2,'0')}};
var today=n.getUTCFullYear()+'/'+z(n.getUTCMonth()+1)+'/'+z(n.getUTCDate()),hm=z(n.getUTCHours())+':'+z(n.getUTCMinutes());
if(today<'{day}')return;
document.querySelectorAll('tr[data-post]').forEach(function(r){{var p=r.getAttribute('data-post');if(today>'{day}'||(p&&p<=hm))r.className='done'}})}})();</script>
</body></html>"""

def build(con, kdb, site, date6, posts=None, as_of=None):
    """Write bets_{date6}.html/.csv and bets.html into the site clone. Returns a summary dict for the runner RESULT."""
    path = f'{kdb}/prediction_log_{date6}.parquet'
    if not os.path.exists(path): return {'error': f'no {os.path.basename(path)}'}
    try:  # post times saved by the predictions (keyed '場所_R'); JRA's current list, when given, wins
        saved = json.load(open(f'{kdb}/post_time_history.json', encoding='utf-8')).get(f'20{date6}', {})
    except Exception:
        saved = {}
    posts = {**{(k.rsplit('_', 1)[0], int(k.rsplit('_', 1)[1])): t for k, t in saved.items() if '_' in k}, **(posts or {})}
    bets, dropped = candidates(pd.read_parquet(path), posts)
    try:
        rec = track_record(con, kdb, date6)
    except Exception as ex:
        print(f'[bets] track record unavailable: {ex}'); rec = {}
    page = _page(date6, bets, dropped, rec, as_of)
    for name in (f'bets_{date6}.html', 'bets.html'):
        open(os.path.join(site, name), 'w', encoding='utf-8').write(page)
    bets.to_csv(os.path.join(site, f'bets_{date6}.csv'), index=False, encoding='utf-8-sig')
    out = {'bets': len(bets), 'yen': int(bets['金額'].sum()) if len(bets) else 0, 'dropped': dropped,
           'record': {k: {'n': v['n'], 'roi': round(v['roi'])} for k, v in rec.items()}}
    print(f'[bets] bets_{date6}.html ' + json.dumps(out, ensure_ascii=False))
    return out
