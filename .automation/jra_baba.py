"""JRA's live 馬場状態 (track condition) per venue, as the 馬場情報 page shows it after its script runs. Read-only.
www.jra.go.jp/keiba/baba/index*.html keep the Friday-noon 馬場状態 in their static HTML all weekend; the page then
replaces it with the latest announcement from POST /JRADB/accessJ.html (CNAME=pw01iwtS3/CD). Reading the static HTML
alone (restore_v7 fetch_jra_baba_snapshot) therefore misses every race-day change, so this reads the JSON instead.
  python3 jra_baba.py [YYYYMMDD]   -> {venue: {'芝': ..., 'ダ': ..., 'date': ..., 'weather': ...}}"""
import sys, json, time, datetime as dt
import requests

URL = 'https://www.jra.go.jp/JRADB/accessJ.html'
JST = dt.timezone(dt.timedelta(hours=9))
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
           'Referer': 'https://www.jra.go.jp/keiba/baba/', 'X-Requested-With': 'XMLHttpRequest'}


def kaisai_info():
    """The raw kaisai_info list (one entry per venue-day of this weekend)."""
    for i in range(3):
        try:
            r = requests.post(URL, data={'CNAME': 'pw01iwtS3/CD'}, headers=HEADERS, timeout=15)
            r.raise_for_status()
            return json.loads(r.content.decode('cp932', errors='replace'))['kaisai_info']
        except (requests.RequestException, ValueError, KeyError) as e:
            if i == 2: raise
            print(f'[baba] retry: {e}', file=sys.stderr); time.sleep(2 ** (i + 1))


def latest(date):
    """{venue: {'芝', 'ダ', 'date', 'weather'}} for race date `date` (YYYYMMDD).
    A venue racing that day takes that day's announcement; when that day has none yet (e.g. Sunday, read on
    Saturday), the venue's latest earlier announcement this weekend is used, which is newer than Friday noon."""
    out = {}
    for k in sorted(kaisai_info(), key=lambda k: k.get('kaisai_ymd') or ''):
        v, ymd = (k.get('jyoname') or '').strip(), k.get('kaisai_ymd') or ''
        s, d = (k.get('ba_s') or '').strip(), (k.get('ba_d') or '').strip()
        if not v or not (s and d) or ymd > date:
            continue
        out[v] = {'芝': s, 'ダ': d, 'date': ymd, 'weather': (k.get('weather') or '').strip()}
    return out


def anchors(date, now=None):
    """predict_track_by_race(anchor=...) input: the live labels, anchored at the time they were read."""
    now = now or dt.datetime.now(JST)
    t = now.strftime('%Y-%m-%d %H:%M')
    return {v: {'芝': x['芝'], 'ダ': x['ダ'], 'time': t} for v, x in latest(date).items()}


if __name__ == '__main__':
    d = sys.argv[1] if len(sys.argv) > 1 else dt.datetime.now(JST).strftime('%Y%m%d')
    print(json.dumps(latest(d), ensure_ascii=False, indent=1))
