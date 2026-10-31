"""Run runbook 1 (当日出走馬 → 予想・公開) or 7-2 (特別登録 → 暫定予想) outside Colab (see keiba_env.py).
Track conditions come from 7-25 predict_track_by_race (JRA 馬場情報 + Open-Meteo; falls back to 良 if unreachable).
For 当日出走馬, win odds/人気 (and 馬番・枠番 when the file has none yet) are replaced by JRA's official odds when
JRA already sells that day (jra_odds.py). kind `odds` is the same run, planned on race days to refresh the odds.
Both also write the review-only bet list (bet_list.py: bets_YYMMDD.html/.csv, bets.html); nothing is voted."""
import sys, os, argparse, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import keiba_env
ap = argparse.ArgumentParser()
ap.add_argument('--kind', choices=['toujitsu', 'tokubetsu', 'odds'], required=True)
ap.add_argument('--file', required=True, help='raw CSV name in keiba_db')
ap.add_argument('--trial', action='store_true')
ap.add_argument('--site', default='/home/user/keiba-dashboard')
a = ap.parse_args()
ns = keiba_env.load(a.site)
RESULT = {'kind': a.kind, 'file': a.file, 'trial': a.trial}

# 7-1: production switches, then calibration models (required after the switches)
ns['enable_af_decay_penalty'](); ns['enable_weight_mult']()
t = time.time()
ns['calib_models'] = ns['build_calibration_models'](train_start='20210101', train_end='20261231')
RESULT['calib_sec'] = round(time.time() - t)
JRA = {}  # JRA's races for the day (post times, 単勝・複勝 odds), kept for the bet list

def apply_jra_odds(csv):
    """Overwrite 本日オッズ/単勝オッズ/本日人気 in the converted CSV with JRA's current odds, matched by (場所, R, 馬名)."""
    import re, unicodedata, pandas as pd, jra_odds
    date = re.search(r'(\d{8})', a.file).group(1)
    try:
        jra = jra_odds.fetch(date)
    except Exception as e:
        print(f'[odds] JRA odds unavailable, keeping the file odds: {e}'); return {'error': str(e)[:200]}
    if not jra: print(f'[odds] JRA lists no racing on {date} yet'); return {}
    JRA.update(jra)
    norm = lambda x: unicodedata.normalize('NFKC', str(x)).replace(' ', '')
    path = f'{keiba_env.KDB}/{csv}'
    df = pd.read_csv(path, encoding='cp932', dtype=str)
    rank = {}
    for v, rs in jra.items():
        for no, r in rs.items():
            sold = sorted(h['odds'] for h in r.get('horses', []) if h['odds'] is not None)
            for h in r.get('horses', []):
                rank[(v, no, norm(h['name']))] = (h, sold.index(h['odds']) + 1 if h['odds'] is not None else None)
    hit = 0
    for i, row in df.iterrows():
        k = (row['場所'], int(row['競走番号']), norm(row['馬名']))
        if k not in rank: continue
        h, pop = rank[k]
        if h['odds'] is not None:
            df.loc[i, ['本日オッズ', '単勝オッズ', '本日人気']] = [f"{h['odds']:.1f}", f"{h['odds']:.1f}", str(pop)]; hit += 1
        if not str(row['馬番']).isdigit():
            df.loc[i, ['馬番', '馬番号']] = str(h['num'])
            if h['waku']: df.loc[i, ['枠番', '枠番号']] = str(h['waku'])
    df.to_csv(path, encoding='cp932', index=False)
    as_of = {v: max((r.get('as_of') or '' for r in rs.values()), default='') for v, rs in jra.items()}
    print(f'[odds] JRA odds applied to {hit}/{len(df)} horses ({as_of})')
    return {'horses': hit, 'rows': len(df), 'as_of': as_of}

if a.kind in ('toujitsu', 'odds'):
    targets = [ns['convert_v02_to_legacy_format'](a.file)]
    RESULT['jra_odds'] = apply_jra_odds(targets[0])
else:
    targets = ns['convert_tokubetsu_toroku_and_split'](a.file)
RESULT['targets'] = list(targets)
RESULT['track'] = {}
for csv in targets:
    tc = ns['predict_track_by_race'](csv)
    # 特別登録 runs days ahead with no post times, so the prediction can come back empty: fall back to 良 per venue,
    # as the runbook's 7-2 example passes it
    import pandas as pd
    for v in pd.read_csv(f'{keiba_env.KDB}/{csv}', encoding='cp932', dtype=str)['場所'].dropna().unique():
        if not any(k == v or k.startswith(f'{v}_') for k in tc): tc[v] = '良'
    RESULT['track'][csv] = {k: v for k, v in tc.items() if '_R' not in k}
    ns['mobile_quick_update'](csv, tc)
ns['rebuild_and_publish_calendar']()
if a.kind in ('toujitsu', 'odds'):
    import re, bet_list
    try:
        RESULT['bets'] = bet_list.build(ns['con'], keiba_env.KDB, a.site, re.search(r'20(\d{6})', a.file).group(1), jra=JRA)
    except Exception as e:  # the bet list is extra: never let it block the predictions from publishing
        print(f'[bets] failed: {e}'); RESULT['bets'] = {'error': str(e)[:200]}
keiba_env.finish(ns, a.site, a.trial, f'{a.kind} {a.file} (cloud)', RESULT)
