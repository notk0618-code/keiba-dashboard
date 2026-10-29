"""Run runbook 1 (当日出走馬 → 予想・公開) or 7-2 (特別登録 → 暫定予想) outside Colab (see keiba_env.py).
Track conditions come from 7-25 predict_track_by_race (JRA 馬場情報 + Open-Meteo; falls back to 良 if unreachable)."""
import sys, os, argparse, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import keiba_env
ap = argparse.ArgumentParser()
ap.add_argument('--kind', choices=['toujitsu', 'tokubetsu'], required=True)
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

if a.kind == 'toujitsu':
    targets = [ns['convert_v02_to_legacy_format'](a.file)]
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
keiba_env.finish(ns, a.site, a.trial, f'{a.kind} {a.file} (cloud)', RESULT)
