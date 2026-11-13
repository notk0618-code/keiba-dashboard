"""Bet builder on the race cards (display only; 2026/11/13 Taisuke).

What it adds to restore_v7's race card (generate_mobile_race_card_v10), and nothing else:
  * an empty <div class="kb-bet"> at the end of the card with the netkeiba race_id and the runners (馬番, 馬名).
    betbuilder.js (site root, loaded from the shared header by keiba_env) turns it into the 「🎫 馬券を組む」 panel:
    the user picks 券種・馬・金額 there, and 「netkeibaで購入へ」 opens netkeiba's bet page for the race.
    The netkeiba_setup.html bookmarklet then copies the picked bets into netkeiba's own bet list.
Nothing is bought here: purchase stays netkeiba → IPAT login → the user's own confirm.

netkeiba race_id = 年(4) + 場コード(2) + 回(2) + 日(2) + R(2). 年・場・回・日 come from JRA's 出馬表 meeting codes
(pw01drl00 + 場 + 年 + 回 + 日 + YYYYMMDD), which JRA lists from Thursday evening through the race day. Days JRA no
longer lists (past dates) get no panel. Any failure leaves the card exactly as restore_v7 made it.
Off switch: BET_BUILDER=0 in the environment (keiba_env.load)."""
import re, json, html

VENUE_CODE = {'札幌': '01', '函館': '02', '福島': '03', '新潟': '04', '東京': '05',
              '中山': '06', '中京': '07', '京都': '08', '阪神': '09', '小倉': '10'}
CODE_VENUE = {v: k for k, v in VENUE_CODE.items()}


def meeting_prefixes(date, codes=None):
    """{venue: 'YYYY場回日'} for date (YYYYMMDD) from JRA's 出馬表 meeting codes; {} when JRA does not list the day."""
    if codes is None:
        import jra_results
        codes = jra_results.shutsuba_codes()
    out = {}
    for c in codes.get(date) or []:
        m = re.match(r'pw01drl00(\d{2})(\d{4})(\d{2})(\d{2})(\d{8})/', c)
        if m and m.group(5) == date and m.group(1) in CODE_VENUE:
            out[CODE_VENUE[m.group(1)]] = m.group(2) + m.group(1) + m.group(3) + m.group(4)
    return out


def race_id(prefixes, venue, race_no):
    p = prefixes.get(venue)
    return f'{p}{int(race_no):02d}' if p else None


def runners(rd):
    """[[馬番, 馬名, 枠番], ...] in 馬番 order; 馬番・枠番 are 0 before the draw."""
    def num(v):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return 0
    out = [[num(r.get('馬番')), str(r['馬名']), num(r.get('枠番'))] for _, r in rd.iterrows()]
    return sorted(out, key=lambda x: (x[0] == 0, x[0]))


def race_info(rd, date, venue, race_no):
    """{'d': 'YYYY-MM-DD', 'v': venue, 'r': R, 'n': レース名, 's': 芝/ダ, 'm': 距離, 'p': 発走} for the panel header;
    fields the data does not have are left out."""
    info = {'d': f'{date[:4]}-{date[4:6]}-{date[6:]}', 'v': venue, 'r': int(race_no)}
    row = rd.iloc[0]
    for key, cols in (('n', ['レース名']), ('s', ['芝ダ', '芝・ダ']), ('m', ['距離']), ('p', ['発走時刻', '発走'])):
        for c in cols:
            v = row.get(c) if c in rd.columns else None
            if v is not None and str(v).strip() not in ('', 'nan', 'None'):
                v = str(v).strip()
                if key == 'm': v = re.sub(r'\.0$', '', v)
                info[key] = v; break
    return info


def panel(rid, anchor, horses, info=None):
    data = html.escape(json.dumps(horses, ensure_ascii=False), quote=True)
    extra = f' data-info="{html.escape(json.dumps(info, ensure_ascii=False), quote=True)}"' if info else ''
    return (f'<div class="kb-bet" data-race-id="{rid}" data-anchor="{html.escape(anchor, quote=True)}" '
            f'data-horses="{data}"{extra}></div>')


def insert(main, block):
    """Put block just inside the card's closing </div>."""
    i = main.rstrip().rfind('</div>')
    return main if i < 0 else main[:i] + block + main[i:]


def install(ns, log=print):
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
                    state['pre'] = meeting_prefixes(date)
                except Exception as ex:
                    state['pre'] = {}; log(f'[bet_builder] JRA meeting codes not available for {date}: {type(ex).__name__}: {ex}')
                if not state['pre']: log(f'[bet_builder] {date}: no netkeiba race_id (JRA does not list the day); no bet panel')
            rid = race_id(state['pre'], venue, race_no)
            if not rid: return main, detail
            rd = race_results_df[(race_results_df['場所'] == venue) & (race_results_df['R'] == race_no)]
            if rd.empty: return main, detail
            try:
                info = race_info(rd, date, venue, race_no)
            except Exception:
                info = None
            main = insert(main, panel(rid, f'{venue}_{race_no}', runners(rd), info))
        except Exception as e:
            log(f'[bet_builder] skipped ({venue}{race_no}R): {type(e).__name__}: {e}')
        return main, detail

    ns['generate_mobile_race_card_v10'] = card
