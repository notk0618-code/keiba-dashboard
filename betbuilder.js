/* 🎫 馬券を組む (race cards) — 2026/11/13 Taisuke, netkeiba-style screen + 即PATへ送信 2026/11/14.
 * Fills each <div class="kb-bet" data-race-id data-anchor data-horses data-info> (added by .automation/bet_builder.py)
 * with a bet builder: 券種 (8) × 買い方 (通常・BOX・ながし・フォーメーション), the runners with AF印 and 単勝オッズ, a live
 * check of the generated combinations, and a 購入予定 list. 「即PATへ送信」 opens netkeiba's bet page for the race
 * with the bets in the URL hash (#kb=...); the netkeiba_autoreg.user.js userscript (or the bookmarklet as fallback)
 * puts them into netkeiba's own bet list, and netkeiba's IPAT連携 takes them to IPAT's confirm screen.
 * Nothing is bought here and no login data is handled here.
 * Bet ids follow netkeiba's IpatDataModel.js: a{曜日}-{..}-{R}_b{式別}_c{方式}_{組番}: c0 one combination,
 * c1 フォーメーション (columns '_', horses in a column '-'), c2 BOX.
 * Saved per race in localStorage 'kbSlip_<race_id>' in the standard layout (see slip()), not in IPAT's layout. */
(function () {
  'use strict';
  if (window.KB_BET_BUILDER) return;
  window.KB_BET_BUILDER = 1;

  var TYPES = [ // [式別 code, label, columns, ordered, standard name]
    [1, '単勝', 1, false, 'win'], [2, '複勝', 1, false, 'place'], [3, '枠連', 2, false, 'bracket_quinella'],
    [4, '馬連', 2, false, 'quinella'], [5, 'ワイド', 2, false, 'quinella_place'], [6, '馬単', 2, true, 'exacta'],
    [7, '3連複', 3, false, 'trio'], [8, '3連単', 3, true, 'trifecta']];
  var METHODS = [['normal', '通常'], ['box', 'BOX'], ['nagashi', 'ながし'], ['formation', 'フォーメーション']];
  var MARKS = ['◎', '〇', '▲', '△', '☆', '✓'];
  var WAKU = {1: ['#fff', '#000'], 2: ['#000', '#fff'], 3: ['#e33', '#fff'], 4: ['#36c', '#fff'],
              5: ['#fd3', '#000'], 6: ['#3a3', '#fff'], 7: ['#f93', '#000'], 8: ['#f6a', '#000']};
  var NK_BET = 'https://race.sp.netkeiba.com/ipat/bet_list.html?race_id=';
  var MAX_ROWS = 255; // netkeiba: 1度の投票は255組まで
  var UA = navigator.userAgent, IOS = /iPhone|iPad|iPod/.test(UA), IOS_CHROME = IOS && /CriOS/.test(UA);
  // iPhone Chrome has no extensions: send to Safari (x-safari-https://, iOS 17+) where the userscript runs. Default on.
  function viaSafari() { return IOS_CHROME && ls('kbViaSafari') !== 0; }

  function typeOf(code) { for (var i = 0; i < TYPES.length; i++) if (TYPES[i][0] === code) return TYPES[i]; }
  function typeByName(n) { for (var i = 0; i < TYPES.length; i++) if (TYPES[i][4] === n) return TYPES[i]; }
  function methodLabel(m) { for (var i = 0; i < METHODS.length; i++) if (METHODS[i][0] === m) return METHODS[i][1]; return m; }
  function ls(k, v) {
    try {
      if (v === undefined) return JSON.parse(localStorage.getItem(k) || 'null');
      if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, JSON.stringify(v));
    } catch (e) { return null; }
  }
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return '&#' + c.charCodeAt(0) + ';'; }); }
  function num(a) { return a.slice().sort(function (x, y) { return x - y; }); }
  function yen(v) { return v.toLocaleString() + '円'; }

  // netkeiba bet_list.min.js make_bet(): a-part from the race_id exactly as netkeiba computes it
  function aPart(rid) {
    var v = new Date(+rid.substr(0, 4), +rid.substr(4, 2) - 1, +rid.substr(6, 2)).getDay();
    return 'a' + v + '-' + rid.substr(8, 2) + '-' + parseInt(rid.substr(10, 2), 10);
  }

  // ながし → formation columns. Unordered: 軸 then 相手 (2軸 3連複: 軸, 軸, 相手). Ordered: 軸 at its 着順, 相手 elsewhere.
  function nagashiCols(code, axis, partners, pos) {
    var t = typeOf(code), k = t[2], cols = [];
    if (!t[3]) {
      axis.forEach(function (a) { cols.push([a]); });
      while (cols.length < k) cols.push(partners.slice());
      return cols.slice(0, k);
    }
    for (var i = 0; i < k; i++) cols.push(i === pos ? axis.slice(0, 1) : partners.slice());
    return cols;
  }
  function perms(a) {
    if (a.length <= 1) return [a];
    var r = [];
    a.forEach(function (x, i) {
      perms(a.slice(0, i).concat(a.slice(i + 1))).forEach(function (p) { r.push([x].concat(p)); });
    });
    return r;
  }
  // every combination of one bet. wc = {枠: horses} (枠連 ゾロ目 only where the 枠 has 2+ horses)
  function combos(b, wc) {
    var t = typeOf(b.code), k = t[2], ordered = t[3], out = [], seen = {}, cols = b.selections;
    if (b.method === 'list') return b.combinations.map(function (c) { return c.slice(); });
    var zoro = function (n) { return b.code === 3 && wc && wc[n] >= 2; };
    function push(arr) {
      if (!ordered) arr = num(arr);
      var key = arr.join('_');
      if (!seen[key]) { seen[key] = 1; out.push(arr); }
    }
    if (!cols || !cols.length) return out;
    if (k === 1) { cols[0].forEach(function (n) { push([n]); }); return out; }
    if (b.method === 'box') {
      var h = num(cols[0]);
      (function rec(start, cur) {
        if (cur.length === k) { if (ordered) perms(cur).forEach(push); else push(cur); return; }
        for (var i = start; i < h.length; i++) rec(i + 1, cur.concat([h[i]]));
      })(0, []);
      if (b.code === 3) h.forEach(function (n) { if (zoro(n)) push([n, n]); });
      return out;
    }
    (function rec(i, cur) {
      if (i === k) { push(cur); return; }
      (cols[i] || []).forEach(function (n) { if (cur.indexOf(n) < 0 || zoro(n)) rec(i + 1, cur.concat([n])); });
    })(0, []);
    return out;
  }
  // netkeiba's grouped form when the whole bet is one block; one c0 row per combination otherwise
  function groupIds(rid, b, wc) {
    var a = aPart(rid) + '_b' + b.code, cs = combos(b, wc), k = typeOf(b.code)[2];
    var col = function (c) { return num(c).join('-'); };
    if (!cs.length) return [];
    if (cs.length === 1 || b.code === 3 || b.method === 'list')
      return cs.map(function (c) { return a + '_c0_' + c.join('_'); });
    if (k === 1) return [a + '_c1_' + col(b.selections[0])];
    if (b.method === 'box') return [a + '_c2_' + col(b.selections[0])];
    return [a + '_c1_' + b.selections.slice(0, k).map(col).join('_')];
  }
  function fmtOdds(v) {
    if (v === undefined || v === null) return '票数なし';
    if (Array.isArray(v)) return v[0].toFixed(1) + '〜' + v[1].toFixed(1);
    return v.toFixed(1);
  }
  function oddsRange(odds, b, wc) {
    var o = odds && odds.o[String(b.code)], lo = Infinity, hi = -Infinity, n = 0;
    if (!o) return null;
    combos(b, wc).forEach(function (c) {
      var v = o[c.join('-')];
      if (v === undefined || v === null) return;
      var a = Array.isArray(v) ? v : [v, v];
      lo = Math.min(lo, a[0]); hi = Math.max(hi, a[1]); n++;
    });
    return n ? (lo === hi ? lo : [lo, hi]) : null;
  }
  function label(b) {
    var t = typeOf(b.code), k = t[2], sep = t[3] ? '→' : '-', l;
    if (k === 1) l = b.selections[0].join(',');
    else if (b.method === 'normal') l = b.selections.map(function (c) { return c[0]; }).join(sep);
    else if (b.method === 'box') l = 'BOX ' + b.selections[0].join(',');
    else if (b.method === 'nagashi')
      l = (t[3] ? (b.axis_position + 1) + '着' : '') + 'ながし 軸' + b.axis.join(',') + ' → 相手 ' + b.partners.join(',');
    else if (b.method === 'list') l = b.base_label || '';
    else l = 'フォーメーション ' + b.selections.map(function (c) { return c.join(','); }).join(' / ');
    return t[1] + ' ' + l + (b.note ? '（' + b.note + '）' : '');
  }

  var CSS = '.kbb{margin:8px 10px 10px;border:1px solid #c9d6e8;border-radius:8px;background:#f6f9fd;font-size:13px;color:#1c1f24}' +
    '.kbb>summary{padding:10px;font-weight:bold;color:#1d3f72;cursor:pointer;list-style:none}' +
    '.kbb>summary::-webkit-details-marker{display:none}' +
    '.kbb .kb-in{padding:0 10px}' +
    '.kbb .kb-sec{background:#fff;border:1px solid #e3e8ef;border-radius:8px;padding:8px;margin:8px 0}' +
    '.kbb .kb-h{font-weight:bold;color:#1d3f72;margin-bottom:4px}' +
    '.kbb .kb-info{font-size:12px;color:#555}' +
    '.kbb .kb-row{display:flex;flex-wrap:wrap;gap:4px;margin:4px 0;align-items:center}' +
    '.kbb .kb-tabs{display:flex;gap:4px;overflow-x:auto;padding-bottom:2px;-webkit-overflow-scrolling:touch}' +
    '.kbb button{font-size:13px;border:1px solid #9fb3cf;background:#fff;color:#1d3f72;border-radius:6px;padding:6px 9px;cursor:pointer;min-height:32px}' +
    '.kbb .kb-tabs button{flex:0 0 auto}' +
    '.kbb .kb-modes{display:grid;grid-template-columns:repeat(4,1fr);gap:4px}' +
    '.kbb .kb-modes button{padding:6px 2px;font-size:12px}' +
    '.kbb button.on{background:#1d3f72;color:#fff;border-color:#1d3f72}' +
    '.kbb button:disabled{opacity:.35;border-style:dashed}' +
    '.kbb button.s{min-height:0;padding:2px 7px;font-size:12px}' +
    '.kbb table{border-collapse:collapse;width:100%;background:#fff}' +
    '.kbb th,.kbb td{border-bottom:1px solid #e3e8ef;padding:4px 2px;text-align:center}' +
    '.kbb th{font-size:11px;color:#555}' +
    '.kbb td.nm{text-align:left;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:8.5em}' +
    '.kbb td.nm small{white-space:normal;color:#555}' +
    '.kbb .um{display:inline-block;min-width:22px;height:22px;line-height:20px;border-radius:4px;font-weight:bold;font-size:12px;border:1px solid #999}' +
    '.kbb .mk{font-weight:bold;color:#c0262d}' +
    '.kbb input[type=checkbox]{width:22px;height:22px;margin:0}' +
    '.kbb .chips button{padding:1px 7px;font-size:12px;min-height:0}' +
    '.kbb .kv{display:grid;grid-template-columns:5.2em 1fr;gap:3px 6px;font-size:13px}' +
    '.kbb .kv>b{color:#666;font-weight:normal}' +
    '.kbb .cmb{display:flex;flex-wrap:wrap;gap:2px 10px} .kbb .cmb span{white-space:nowrap}' +
    '.kbb .od{color:#c0262d;font-weight:bold}' +
    '.kbb .amt{display:inline-flex;align-items:center;gap:3px}' +
    '.kbb .amt input{width:4em;font-size:15px;padding:3px;text-align:right;border:1px solid #9fb3cf;border-radius:6px}' +
    '.kbb .msg{font-size:12px;margin-top:4px;color:#b45309}' +
    '.kbb .grp{border-top:1px solid #e3e8ef;margin-top:6px;padding-top:6px}' +
    '.kbb .grp:first-of-type{border-top:0;margin-top:0;padding-top:0}' +
    '.kbb .gh{display:flex;justify-content:space-between;align-items:center;font-weight:bold}' +
    '.kbb .it{display:flex;justify-content:space-between;align-items:flex-start;gap:6px;padding:6px 0;border-bottom:1px dashed #e3e8ef}' +
    '.kbb .it>div{flex:1;min-width:0}' +
    '.kbb .it details{font-size:12px;color:#444;margin-top:2px} .kbb .it summary{color:#1d3f72;cursor:pointer}' +
    '.kbb .note{color:#777;font-size:11px;margin:6px 0;line-height:1.5}' +
    '.kbb .bar{position:sticky;bottom:0;z-index:5;display:flex;align-items:center;gap:8px;background:#1d3f72;color:#fff;' +
      'margin:8px -10px 0;padding:8px 10px calc(8px + env(safe-area-inset-bottom));border-radius:0 0 8px 8px}' +
    '.kbb .bar .tot{flex:1;font-size:12px;line-height:1.3} .kbb .bar .tot b{font-size:16px}' +
    '.kbb .buy{display:inline-block;background:#e9514e;color:#fff;border-radius:8px;padding:10px 12px;font-weight:bold;text-decoration:none;white-space:nowrap}' +
    '.kbb .buy.off{background:#8a96a8;pointer-events:none}';

  function build(el) {
    var rid = el.getAttribute('data-race-id'), anchor = el.getAttribute('data-anchor');
    var horses = JSON.parse(el.getAttribute('data-horses') || '[]').filter(function (h) { return h[0] > 0; });
    var info = {};
    try { info = JSON.parse(el.getAttribute('data-info') || '{}') || {}; } catch (e) {}
    var wc = {};  // 枠 → number of horses
    horses.forEach(function (h) { if (h[2] >= 1 && h[2] <= 8) wc[h[2]] = (wc[h[2]] || 0) + 1; });
    var wakus = Object.keys(wc).map(Number).sort(function (a, b) { return a - b; });
    var key = 'kbSlip_' + rid;
    var bets = load();
    var st = {code: 1, method: 'normal', cols: [[], [], []], axis: [], partners: [], pos: 0, amt: 100, msg: '', showAll: false};
    var odds = null, oddsTried = false;

    function load() {
      var s = ls(key);
      if (s && s.bets) return s.bets.map(fromStd).filter(Boolean);
      var old = ls('kbBets_' + rid);  // 11/13 layout {t, m: form|box, c, y}
      if (!old || !old.length) return [];
      var out = old.map(function (o) {
        var k = typeOf(o.t) ? typeOf(o.t)[2] : 0;
        if (!k) return null;
        return {code: o.t, method: k === 1 ? 'normal' : (o.m === 'box' ? 'box' : 'formation'), selections: o.c, amount: (o.y || 1) * 100};
      }).filter(Boolean);
      return out;
    }
    function fromStd(s) {
      var t = typeByName(s.bet_type);
      if (!t) return null;
      return {code: t[0], method: s.method, selections: s.selections || [], axis: s.axis, partners: s.partners,
              axis_position: s.axis_position || 0, combinations: s.combinations, base_label: s.base_label, note: s.note,
              amount: Math.max(100, Math.floor((+s.amount_per_ticket || 100) / 100) * 100)};
    }
    // the standard layout (kept apart from netkeiba/IPAT ids, which are made only when sending)
    function slip() {
      var tp = 0, ta = 0;
      var out = bets.map(function (b) {
        var cs = combos(b, wc), s = {bet_type: typeOf(b.code)[4], bet_type_label: typeOf(b.code)[1], method: b.method,
          selections: b.selections, combinations: cs, points: cs.length, amount_per_ticket: b.amount, total_amount: cs.length * b.amount};
        if (b.method === 'nagashi') { s.axis = b.axis; s.partners = b.partners; s.axis_position = b.axis_position; }
        if (b.base_label) s.base_label = b.base_label;
        if (b.note) s.note = b.note;
        tp += s.points; ta += s.total_amount;
        return s;
      });
      return {version: 1, race: {date: info.d || '', venue: info.v || '', race_number: info.r || +rid.substr(10, 2), race_id: rid,
              race_name: info.n || ''}, bets: out, total_points: tp, total_amount: ta, updated_at: new Date().toISOString()};
    }
    function save() {
      ls(key, bets.length ? slip() : null);
      ls('kbBets_' + rid, null);
    }
    function loadOdds() {
      if (oddsTried || !window.fetch) return;
      oddsTried = true;
      fetch('odds/' + rid + '.json', {cache: 'no-cache'}).then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) { if (d && d.o) { odds = d; render(); } }).catch(function () {});
    }
    function mark(name) {
      try { return localStorage.getItem('predMark_' + anchor + '_' + name) || ''; } catch (e) { return ''; }
    }

    var box = document.createElement('details');
    box.className = 'kbb';
    box.innerHTML = '<summary>🎫 馬券を組む（即PATへ送信）<span class="kb-cnt"></span></summary><div class="kb-in"></div>';
    el.appendChild(box);
    var inner = box.querySelector('.kb-in');
    if (!horses.length) {
      inner.innerHTML = '<div class="note">馬番が確定すると使えます（枠順発表後に更新されます）。</div>';
      return;
    }

    function k() { return typeOf(st.code)[2]; }
    function allowed(m) { return k() === 1 ? m === 'normal' : true; }
    function maxAxis() { var t = typeOf(st.code); return t[2] === 3 && !t[3] ? 2 : 1; }
    function heads() {  // column titles of the runner table for the current 券種・買い方
      var t = typeOf(st.code);
      if (t[2] === 1) return ['選択'];
      if (st.method === 'box') return ['BOX'];
      if (st.method === 'nagashi') return ['軸', '相手'];
      return (t[3] ? ['1着', '2着', '3着'] : ['1頭目', '2頭目', '3頭目']).slice(0, t[2]);
    }
    function colList(ci) { return st.method === 'nagashi' ? (ci === 0 ? st.axis : st.partners) : st.cols[ci]; }
    function current() {
      var b = {code: st.code, method: st.method, amount: st.amt}, n = k();
      if (st.method === 'nagashi') {
        b.axis = num(st.axis); b.partners = num(st.partners); b.axis_position = typeOf(st.code)[3] ? st.pos : 0;
        b.selections = b.axis.length ? nagashiCols(st.code, b.axis, b.partners, b.axis_position) : [];
        if (!typeOf(st.code)[3] && b.axis.length > n - 1) b.selections = [];
      } else if (st.method === 'box' || n === 1) b.selections = [num(st.cols[0])];
      else b.selections = st.cols.slice(0, n).map(num);
      return b;
    }
    function existing(code) {
      var s = {};
      bets.forEach(function (b) { if (b.code === code) combos(b, wc).forEach(function (c) { s[c.join('_')] = 1; }); });
      return s;
    }
    function totals() {
      var p = 0, a = 0;
      bets.forEach(function (b) { var n = combos(b, wc).length; p += n; a += n * b.amount; });
      return [p, a];
    }

    function rowsHtml(hs) {
      var win = odds && odds.o['1'], isW = st.code === 3, h = '';
      var colsTh = hs.map(function (x) { return '<th>' + x + '</th>'; }).join('');
      h += '<table><tr><th>' + (isW ? '枠' : '馬番') + '</th>' + (isW ? '' : '<th>印</th>') + '<th style="text-align:left">' +
        '馬名' + '</th>' + (!isW && win ? '<th>単勝</th>' : '') + colsTh + '</tr>';
      var rows = isW ? wakus.map(function (w) {
        return {n: w, w: w, name: horses.filter(function (x) { return x[2] === w; }).map(function (x) {
          var m = mark(x[1]); return x[0] + (m ? m : '') + ' ' + x[1]; }).join('・')};
      }) : horses.map(function (x) { return {n: x[0], w: x[2], name: x[1], mk: mark(x[1])}; });
      rows.forEach(function (r) {
        var c = WAKU[r.w] || ['#888', '#fff'];
        h += '<tr><td><span class="um" style="background:' + c[0] + ';color:' + c[1] + '">' + r.n + '</span></td>' +
          (isW ? '' : '<td class="mk">' + esc(r.mk) + '</td>') +
          '<td class="nm">' + (isW ? '<small>' + esc(r.name) + '</small>' : esc(r.name)) + '</td>' +
          (!isW && win ? '<td style="font-size:12px">' + (win[String(r.n)] ? win[String(r.n)].toFixed(1) : '-') + '</td>' : '') +
          hs.map(function (_, ci) {
            return '<td><input type="checkbox" aria-label="' + hs[ci] + ' ' + r.n + '" data-col="' + ci + '" data-n="' + r.n + '"' +
              (colList(ci).indexOf(r.n) >= 0 ? ' checked' : '') + '></td>';
          }).join('') + '</tr>';
      });
      return h + '</table>';
    }

    function render() {
      var t = typeOf(st.code), hs = heads(), h = '';
      // 1 レース情報
      var d = info.d ? info.d.slice(5).replace('-', '/') + ' ' : '';
      h += '<div class="kb-sec"><div class="kb-info">' + esc(d + (info.v || '') + (info.r || '') + 'R' + (info.n ? '　' + info.n : '') +
        (info.s || info.m ? '　' + (info.s || '') + (info.m || '') + (info.m ? 'm' : '') : '') + (info.p ? '　' + info.p + '発走' : '') +
        '　' + horses.length + '頭') + (odds ? '<br>オッズ ' + esc(odds.asof) + '時点（JRA公式・毎時更新）' : '') + '</div></div>';
      // 2 券種 3 買い方
      h += '<div class="kb-sec"><div class="kb-tabs">' + TYPES.map(function (x) {
        return '<button data-t="' + x[0] + '" class="' + (x[0] === st.code ? 'on' : '') + '">' + x[1] + '</button>';
      }).join('') + '</div><div class="kb-modes" style="margin-top:6px">' + METHODS.map(function (m) {
        var ok = allowed(m[0]);
        return '<button data-m="' + m[0] + '" class="' + (m[0] === st.method ? 'on' : '') + '"' + (ok ? '' : ' disabled') + '>' + m[1] + '</button>';
      }).join('') + '</div>';
      if (st.method === 'nagashi' && t[3]) {
        h += '<div class="kb-row">軸の着順: ' + [0, 1, 2].slice(0, t[2]).map(function (p) {
          return '<button class="s' + (st.pos === p ? ' on' : '') + '" data-pos="' + p + '">' + (p + 1) + '着</button>';
        }).join('') + '</div>';
      }
      if (st.method === 'nagashi') h += '<div class="note" style="margin:2px 0">軸は' + (maxAxis() === 2 ? '1〜2頭' : '1頭') + '、相手は何頭でも選べます。</div>';
      if (st.method === 'normal' && t[2] > 1) h += '<div class="note" style="margin:2px 0">各列で1頭ずつ選びます。</div>';
      h += '</div>';
      // 4 出走馬
      var present = st.code === 3 ? [] : MARKS.filter(function (m) { return horses.some(function (x) { return mark(x[1]) === m; }); });
      h += '<div class="kb-sec"><div class="kb-h">出走馬</div>';
      h += hs.map(function (hd, ci) {
        return '<div class="kb-row"><b style="min-width:3.2em">' + hd + '</b>' +
          (st.method === 'normal' && t[2] > 1 || (st.method === 'nagashi' && ci === 0) ? '' : '<button class="s" data-all="' + ci + '">全選択</button>') +
          '<button class="s" data-none="' + ci + '">選択解除</button>' +
          (present.length ? '<span class="chips">' + present.map(function (m) {
            return '<button data-chip="' + ci + '" data-mk="' + m + '">' + m + '</button>';
          }).join('') + '</span>' : '') + '</div>';
      }).join('');
      h += rowsHtml(hs) + '</div>';
      // 5 買い目確認
      var cur = current(), cs = combos(cur, wc), have = existing(st.code), dup = cs.filter(function (c) { return have[c.join('_')]; }).length;
      var cr = cs.length ? oddsRange(odds, cur, wc) : null, o = odds && odds.o[String(st.code)];
      var shown = st.showAll ? cs : cs.slice(0, 20), sep = t[3] ? '→' : '-';
      h += '<div class="kb-sec"><div class="kb-h">買い目の確認</div><div class="kv">' +
        '<b>券種</b><span>' + t[1] + '</span><b>買い方</b><span>' + methodLabel(st.method) + '</span>' +
        '<b>選択</b><span>' + (hs.map(function (hd, ci) { var l = colList(ci); return l.length ? hd + ' ' + num(l).join(',') : ''; })
          .filter(Boolean).join(' / ') || '—') + '</span>' +
        '<b>買い目</b><span class="cmb">' + (shown.map(function (c) {
          var v = o ? o[c.join('-')] : undefined;
          return '<span' + (have[c.join('_')] ? ' style="text-decoration:line-through;color:#999"' : '') + '>' + c.join(sep) +
            (o ? ' <span class="od">' + fmtOdds(v) + '</span>' : '') + '</span>';
        }).join('') || '—') + (cs.length > 20 ? ' <button class="s kb-all">' + (st.showAll ? '閉じる' : 'すべて表示（' + cs.length + '点）') + '</button>' : '') + '</span>' +
        '<b>点数</b><span>' + cs.length + '点' + (dup ? '（うち' + dup + '点は購入予定に入っています）' : '') + '</span>' +
        '<b>1点金額</b><span class="amt"><button class="s" data-step="-1">−</button><input type="number" inputmode="numeric" min="1" step="1" class="kb-money" value="' +
          (st.amt / 100) + '">00円<button class="s" data-step="1">＋</button></span>' +
        '<b>合計</b><span><b style="font-size:15px">' + yen((cs.length - dup) * st.amt) + '</b>' + (cr !== null ? '　<span class="od">' + fmtOdds(cr) + '倍</span>' : '') + '</span>' +
        '</div><div class="kb-row" style="margin-top:6px"><button class="on kb-add"' + (cs.length - dup > 0 ? '' : ' disabled') + '>＋ 購入予定に追加</button>' +
        '<button class="kb-clr-sel">選択をクリア</button></div>' + (st.msg ? '<div class="msg">' + esc(st.msg) + '</div>' : '') + '</div>';
      // 6 購入予定
      var tt = totals();
      h += '<div class="kb-sec"><div class="kb-h">購入予定</div>';
      if (!bets.length) h += '<div class="note">まだありません。上で買い目を選んで「購入予定に追加」を押してください。</div>';
      TYPES.forEach(function (x) {
        var idx = [];
        bets.forEach(function (b, i) { if (b.code === x[0]) idx.push(i); });
        if (!idx.length) return;
        var sp = 0, sa = 0;
        idx.forEach(function (i) { var n = combos(bets[i], wc).length; sp += n; sa += n * bets[i].amount; });
        h += '<div class="grp"><div class="gh"><span>' + x[1] + '　' + sp + '点 ' + yen(sa) + '</span><button class="s" data-deltype="' + x[0] + '">この券種を削除</button></div>';
        idx.forEach(function (i) {
          var b = bets[i], bc = combos(b, wc), r = oddsRange(odds, b, wc), ob = odds && odds.o[String(b.code)], det = '';
          if (ob) {
            det = '<details><summary>組番ごとのオッズ・払戻</summary><div class="cmb">' + bc.map(function (c) {
              var v = ob[c.join('-')], pay = '';
              if (v !== undefined && v !== null) {
                var a = Array.isArray(v) ? v : [v, v];
                pay = ' (' + Math.floor(a[0] * b.amount).toLocaleString() + (a[0] === a[1] ? '' : '〜' + Math.floor(a[1] * b.amount).toLocaleString()) + '円)';
              }
              return '<span>' + c.join(typeOf(b.code)[3] ? '→' : '-') + ' <span class="od">' + fmtOdds(v) + '</span>' + pay + '</span>';
            }).join('') + '</div></details>';
          }
          h += '<div class="it"><div>' + esc(label(b)) + (r !== null ? '　<span class="od">' + fmtOdds(r) + '倍</span>' : '') +
            '<br><small>' + bc.length + '点 × </small><span class="amt"><input type="number" inputmode="numeric" min="1" step="1" data-amt="' + i +
            '" value="' + (b.amount / 100) + '">00円</span><small> = ' + yen(bc.length * b.amount) + '</small>' + det +
            '</div><button class="s" data-del="' + i + '">削除</button></div>';
        });
        h += '</div>';
      });
      if (bets.length) h += '<div class="kb-row" style="justify-content:space-between;margin-top:6px"><button class="s kb-copy">買い目をテキストでコピー</button>' +
        '<button class="s kb-clr-list">全クリア</button></div>' +
        (tt[0] > MAX_ROWS ? '<div class="msg" style="color:#c00">netkeibaは1回255点までです。減らしてください。</div>' : '');
      h += '</div>';
      // notes + fixed bar
      var ok = bets.length && tt[0] <= MAX_ROWS, url = ok ? sendUrl() : '#', saf = ok && viaSafari();
      if (saf) url = 'x-safari-' + url;
      h += '<div class="note">「即PATへ送信」で、このレースのnetkeiba購入ページが' + (viaSafari() ? 'Safariで' : '') + '開き、' +
        '買い目が自動で買い目リストに入ります（<a href="netkeiba_setup.html">初回設定</a>が必要です）。そのあと「IPAT投票へすすむ」→ IPATの確認画面で、' +
        '内容を確かめてご自身で投票してください。このページでは購入もログインもしません。</div>' +
        (IOS_CHROME ? '<label class="note" style="display:block"><input type="checkbox" class="kb-saf"' + (viaSafari() ? ' checked' : '') +
          ' style="width:16px;height:16px;vertical-align:-3px"> 購入はSafariで開く（自動登録。外すとChromeで開き、ブックマークで登録）</label>' : '');
      h += '<div class="bar"><div class="tot">購入予定<br><b>' + tt[0] + '点 ' + yen(tt[1]) + '</b></div>' +
        '<a class="buy' + (ok ? '' : ' off') + '"' + (saf ? '' : ' target="_blank" rel="noopener"') + ' href="' + esc(url) + '">即PATへ送信 ▶</a></div>';
      inner.innerHTML = h;
      box.querySelector('.kb-cnt').textContent = bets.length ? '　' + tt[0] + '点 / ' + yen(tt[1]) : '';
    }
    function sendUrl() {
      var b = [];
      bets.forEach(function (x) { groupIds(rid, x, wc).forEach(function (id) { b.push([id, x.amount]); }); });
      return NK_BET + rid + '#kb=' + encodeURIComponent(JSON.stringify({r: rid, b: b}));
    }
    function text() {
      var tt = totals();
      return (info.d ? info.d.slice(5).replace('-', '/') + ' ' : '') + anchor.replace('_', ' ') + 'R\n' + bets.map(function (b) {
        return label(b) + '　' + combos(b, wc).length + '点 各' + b.amount + '円';
      }).join('\n') + '\n合計 ' + tt[0] + '点 ' + tt[1] + '円';
    }
    function resetSel() { st.cols = [[], [], []]; st.axis = []; st.partners = []; st.showAll = false; }
    function toggle(ci, n, on) {
      var t = typeOf(st.code);
      if (st.method === 'nagashi' && ci === 0) {
        var a = st.axis, i = a.indexOf(n);
        if (on && i < 0) { a.push(n); while (a.length > maxAxis()) a.shift(); }
        else if (!on && i >= 0) a.splice(i, 1);
        var j = st.partners.indexOf(n); if (on && j >= 0) st.partners.splice(j, 1);
        return;
      }
      var c = colList(ci), x = c.indexOf(n);
      if (st.method === 'normal' && t[2] > 1) { c.length = 0; if (on) c.push(n); return; }
      if (on && x < 0) c.push(n); else if (!on && x >= 0) c.splice(x, 1);
      if (st.method === 'nagashi' && on) { var y = st.axis.indexOf(n); if (y >= 0) st.axis.splice(y, 1); }
    }
    function add() {
      var b = current(), cs = combos(b, wc), have = existing(b.code);
      var fresh = cs.filter(function (c) { return !have[c.join('_')]; });
      if (!cs.length) return;
      if (!fresh.length) { st.msg = 'すべて購入予定に入っている買い目です。追加しませんでした（金額は購入予定で変更できます）。'; return; }
      if (fresh.length < cs.length) {  // keep only the new combinations, sent one row each
        b = {code: b.code, method: 'list', combinations: fresh, base_label: label(b).replace(/^\S+ /, ''),
             note: (cs.length - fresh.length) + '点重複のため除外', selections: [], amount: b.amount};
        st.msg = (cs.length - fresh.length) + '点は購入予定と重複するため除き、' + fresh.length + '点を追加しました。';
      } else st.msg = cs.length + '点を購入予定に追加しました。';
      bets.push(b); save(); resetSel();
    }
    inner.addEventListener('click', function (e) {
      var b = e.target.closest('button');
      if (!b) return;
      e.preventDefault();
      var msg = '';
      if (b.dataset.t) {
        st.code = +b.dataset.t; resetSel(); st.pos = 0;
        if (!allowed(st.method)) st.method = 'normal';
      } else if (b.dataset.m) { st.method = b.dataset.m; resetSel(); }
      else if (b.dataset.pos !== undefined) st.pos = +b.dataset.pos;
      else if (b.dataset.chip !== undefined) {
        var ci = +b.dataset.chip, mk = b.dataset.mk;
        horses.forEach(function (x) { if (mark(x[1]) === mk && colList(ci).indexOf(x[0]) < 0) toggle(ci, x[0], true); });
      } else if (b.dataset.all !== undefined) {
        var cj = +b.dataset.all, all = st.code === 3 ? wakus : horses.map(function (x) { return x[0]; });
        all.forEach(function (n) { if (colList(cj).indexOf(n) < 0) toggle(cj, n, true); });
      } else if (b.dataset.none !== undefined) colList(+b.dataset.none).length = 0;
      else if (b.dataset.step) st.amt = Math.max(100, st.amt + 100 * +b.dataset.step);
      else if (b.classList.contains('kb-all')) st.showAll = !st.showAll;
      else if (b.classList.contains('kb-add')) { add(); msg = st.msg; }
      else if (b.classList.contains('kb-clr-sel')) resetSel();
      else if (b.dataset.del !== undefined) { bets.splice(+b.dataset.del, 1); save(); }
      else if (b.dataset.deltype !== undefined) { var c = +b.dataset.deltype; bets = bets.filter(function (x) { return x.code !== c; }); save(); }
      else if (b.classList.contains('kb-clr-list')) {
        if (b.dataset.sure) { bets = []; save(); } else { b.dataset.sure = 1; b.textContent = 'もう一度押すと全部消します'; return; }
      } else if (b.classList.contains('kb-copy')) {
        if (navigator.clipboard) navigator.clipboard.writeText(text()).then(function () { b.textContent = 'コピーしました'; });
        return;
      }
      st.msg = msg;
      render();
    });
    inner.addEventListener('change', function (e) {
      var x = e.target;
      if (x.dataset.col !== undefined) toggle(+x.dataset.col, +x.dataset.n, x.checked);
      else if (x.classList.contains('kb-saf')) ls('kbViaSafari', x.checked ? 1 : 0);
      else if (x.classList.contains('kb-money')) st.amt = Math.max(1, Math.floor(+x.value || 1)) * 100;
      else if (x.dataset.amt !== undefined) { bets[+x.dataset.amt].amount = Math.max(1, Math.floor(+x.value || 1)) * 100; save(); }
      st.msg = '';
      render();
    });
    // marks changed in the card's own selects → refresh the 印 column
    var card = document.getElementById(anchor);
    if (card) card.addEventListener('change', function (e) { if (e.target.id && e.target.id.indexOf('mark_') === 0) render(); });
    box.addEventListener('toggle', function () { if (box.open) { loadOdds(); render(); } });
    render();
  }

  function init() {
    var els = document.querySelectorAll('.kb-bet:not([data-kb-done])');
    if (!els.length) return;
    if (!document.getElementById('kbb-css')) {
      var s = document.createElement('style'); s.id = 'kbb-css'; s.textContent = CSS; document.head.appendChild(s);
    }
    Array.prototype.forEach.call(els, function (el) {
      el.setAttribute('data-kb-done', '1');
      try { build(el); } catch (e) { if (window.console) console.error('[betbuilder]', e); }
    });
  }
  window.KBBetBuilder = {combos: combos, groupIds: groupIds, nagashiCols: nagashiCols, aPart: aPart, label: label, init: init};
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
