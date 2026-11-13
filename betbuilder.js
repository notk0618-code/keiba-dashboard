/* 🎫 馬券を組む (race cards) — 2026/11/13 Taisuke.
 * Fills each <div class="kb-bet" data-race-id data-anchor data-horses> (added by .automation/bet_builder.py) with a
 * bet builder: pick 券種・方式・馬・金額, add to the list, then 「netkeibaで購入へ」 opens netkeiba's bet page for the
 * race with the bets in the URL hash (#kb=...). The bookmarklet from netkeiba_setup.html copies them into netkeiba's
 * own bet list (browser storage on race.sp.netkeiba.com). Nothing is bought here.
 * Bet ids follow netkeiba's IpatDataModel.js: a{曜日}-{..}-{R}_b{式別}_c0_{組番} (c0 = 通常, one row per combination). */
(function () {
  'use strict';
  if (window.KB_BET_BUILDER) return;
  window.KB_BET_BUILDER = 1;

  var TYPES = [ // [式別 code, label, columns, ordered]
    [1, '単勝', 1, false], [2, '複勝', 1, false], [4, '馬連', 2, false], [5, 'ワイド', 2, false],
    [6, '馬単', 2, true], [7, '3連複', 3, false], [8, '3連単', 3, true]];
  var MARKS = ['◎', '〇', '▲', '△', '☆', '✓'];
  var WAKU = {1: ['#fff', '#000'], 2: ['#000', '#fff'], 3: ['#e33', '#fff'], 4: ['#36c', '#fff'],
              5: ['#fd3', '#000'], 6: ['#3a3', '#fff'], 7: ['#f93', '#000'], 8: ['#f6a', '#000']};
  var NK_BET = 'https://race.sp.netkeiba.com/ipat/bet_list.html?race_id=';
  var MAX_ROWS = 255; // netkeiba: 1度の投票は255組まで
  // iPhone/iPad outside Chrome (Safari, home-screen app): offer to open netkeiba in Chrome via its URL scheme
  var IOS_NOT_CHROME = /iPhone|iPad|iPod/.test(navigator.userAgent) && !/CriOS/.test(navigator.userAgent);
  function useChrome() { var v = ls('kbOpenChrome'); return IOS_NOT_CHROME && v !== 0; }  // default on

  function typeOf(code) { for (var i = 0; i < TYPES.length; i++) if (TYPES[i][0] === code) return TYPES[i]; }
  function ls(k, v) {
    try {
      if (v === undefined) return JSON.parse(localStorage.getItem(k) || 'null');
      if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, JSON.stringify(v));
    } catch (e) { return null; }
  }
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return '&#' + c.charCodeAt(0) + ';'; }); }

  // netkeiba bet_list.min.js make_bet(): a-part from the race_id exactly as netkeiba computes it
  function aPart(rid) {
    var v = new Date(+rid.substr(0, 4), +rid.substr(4, 2) - 1, +rid.substr(6, 2)).getDay();
    return 'a' + v + '-' + rid.substr(8, 2) + '-' + parseInt(rid.substr(10, 2), 10);
  }

  // every combination for one selection; cols = [[馬番...], ...]
  function combos(code, mode, cols) {
    var t = typeOf(code), k = t[2], ordered = t[3], out = [], seen = {};
    function push(arr) {
      if (!ordered) arr = arr.slice().sort(function (a, b) { return a - b; });
      var key = arr.join('_');
      if (!seen[key]) { seen[key] = 1; out.push(arr); }
    }
    if (k === 1) { cols[0].forEach(function (n) { push([n]); }); return out; }
    if (mode === 'box') {
      var h = cols[0].slice().sort(function (a, b) { return a - b; });
      (function rec(start, cur) {
        if (cur.length === k) {
          if (ordered) perms(cur).forEach(push); else push(cur);
          return;
        }
        for (var i = start; i < h.length; i++) rec(i + 1, cur.concat([h[i]]));
      })(0, []);
      return out;
    }
    (function rec(i, cur) {
      if (i === k) { push(cur); return; }
      cols[i].forEach(function (n) { if (cur.indexOf(n) < 0) rec(i + 1, cur.concat([n])); });
    })(0, []);
    return out;
  }
  function perms(a) {
    if (a.length <= 1) return [a];
    var r = [];
    a.forEach(function (x, i) {
      perms(a.slice(0, i).concat(a.slice(i + 1))).forEach(function (p) { r.push([x].concat(p)); });
    });
    return r;
  }
  function betIds(rid, item) {
    var a = aPart(rid);
    return combos(item.t, item.m, item.c).map(function (c) { return a + '_b' + item.t + '_c0_' + c.join('_'); });
  }
  function oddsKey(code, c) { return c.join('-'); } // combos() already sorts unordered types
  function fmtOdds(v) {
    if (v === undefined || v === null) return '票数なし';
    if (Array.isArray(v)) return v[0].toFixed(1) + '〜' + v[1].toFixed(1);
    return v.toFixed(1);
  }
  // [min, max] over the combinations of an item (ranges of 複勝・ワイド included); null when no odds
  function oddsRange(odds, item) {
    var o = odds && odds.o[String(item.t)], lo = Infinity, hi = -Infinity, n = 0;
    if (!o) return null;
    combos(item.t, item.m, item.c).forEach(function (c) {
      var v = o[oddsKey(item.t, c)];
      if (v === undefined || v === null) return;
      var a = Array.isArray(v) ? v : [v, v];
      lo = Math.min(lo, a[0]); hi = Math.max(hi, a[1]); n++;
    });
    return n ? [lo, hi] : null;
  }
  function itemLabel(item) {
    var t = typeOf(item.t), k = t[2];
    if (k === 1) return t[1] + ' ' + item.c[0].join(',');
    if (item.m === 'box') return t[1] + ' BOX ' + item.c[0].join(',');
    return t[1] + ' ' + item.c.slice(0, k).map(function (c) { return c.join(','); }).join(' → ');
  }

  var CSS = '.kbb{margin:8px 10px 10px;border:1px solid #c9d6e8;border-radius:8px;background:#f6f9fd;font-size:13px}' +
    '.kbb>summary{padding:8px 10px;font-weight:bold;color:#1d3f72;cursor:pointer;list-style:none}' +
    '.kbb>summary::-webkit-details-marker{display:none}' +
    '.kbb .kb-in{padding:0 10px 10px}' +
    '.kbb .kb-row{display:flex;flex-wrap:wrap;gap:4px;margin:6px 0}' +
    '.kbb button{font-size:13px;border:1px solid #9fb3cf;background:#fff;color:#1d3f72;border-radius:6px;padding:4px 9px;cursor:pointer}' +
    '.kbb button.on{background:#1d3f72;color:#fff;border-color:#1d3f72}' +
    '.kbb button:disabled{opacity:.4}' +
    '.kbb table{border-collapse:collapse;width:100%;background:#fff;margin-top:4px}' +
    '.kbb th,.kbb td{border-bottom:1px solid #e3e8ef;padding:4px 3px;text-align:center}' +
    '.kbb td.nm{text-align:left;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:9em}' +
    '.kbb .um{display:inline-block;width:20px;height:20px;line-height:20px;border-radius:4px;font-weight:bold;font-size:12px;border:1px solid #999}' +
    '.kbb input[type=checkbox]{width:20px;height:20px}' +
    '.kbb .chips button{padding:1px 6px;font-size:12px}' +
    '.kbb .sum{margin:8px 0;font-weight:bold}' +
    '.kbb ul{list-style:none;margin:6px 0;padding:0}' +
    '.kbb li{display:flex;justify-content:space-between;align-items:center;background:#fff;border:1px solid #e3e8ef;border-radius:6px;padding:5px 8px;margin-bottom:4px}' +
    '.kbb .buy{display:block;text-align:center;background:#e9514e;color:#fff;border-radius:8px;padding:10px;font-weight:bold;text-decoration:none;margin-top:6px}' +
    '.kbb .buy.off{background:#bbb;pointer-events:none}' +
    '.kbb .note{color:#888;font-size:11px;margin-top:6px;line-height:1.5}' +
    '.kbb .od{color:#c0262d;font-weight:bold}' +
    '.kbb li>button{flex-shrink:0;white-space:nowrap;margin-left:6px}' +
    '.kbb li details{font-size:12px;color:#444;margin-top:2px} .kbb li summary{color:#1d3f72;cursor:pointer}' +
    '.kbb .cmb{display:flex;flex-wrap:wrap;gap:2px 10px;margin-top:3px} .kbb .cmb span{white-space:nowrap}';

  function build(el) {
    var rid = el.getAttribute('data-race-id'), anchor = el.getAttribute('data-anchor');
    var horses = JSON.parse(el.getAttribute('data-horses') || '[]').filter(function (h) { return h[0] > 0; });
    var key = 'kbBets_' + rid;
    var st = {t: 1, m: 'form', c: [[], [], []], money: 1};
    var list = ls(key) || [];
    var odds = null, oddsTried = false;
    function loadOdds() {
      if (oddsTried || !window.fetch) return;
      oddsTried = true;
      fetch('odds/' + rid + '.json', {cache: 'no-cache'}).then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) { if (d && d.o) { odds = d; render(); } }).catch(function () {});
    }
    var box = document.createElement('details');
    box.className = 'kbb';
    box.innerHTML = '<summary>🎫 馬券を組む（netkeibaで購入）<span class="kb-cnt"></span></summary><div class="kb-in"></div>';
    el.appendChild(box);
    var inner = box.querySelector('.kb-in');
    if (!horses.length) {
      inner.innerHTML = '<div class="note">馬番が確定すると使えます（枠順発表後に更新されます）。</div>';
      return;
    }
    function mark(name) {
      try { return localStorage.getItem('predMark_' + anchor + '_' + name) || ''; } catch (e) { return ''; }
    }
    function save() { ls(key, list.length ? list : null); }
    function rows() {
      var n = 0;
      list.forEach(function (it) { n += betIds(rid, it).length; });
      return n;
    }
    function render() {
      var t = typeOf(st.t), k = st.m === 'box' && t[2] > 1 ? 1 : t[2];
      var heads = t[2] === 1 ? ['選択'] : st.m === 'box' ? ['BOX'] : (t[3] ? ['1着', '2着', '3着'] : ['1頭目', '2頭目', '3頭目']).slice(0, k);
      var h = '<div class="kb-row">' + TYPES.map(function (x) {
        return '<button data-t="' + x[0] + '" class="' + (x[0] === st.t ? 'on' : '') + '">' + x[1] + '</button>';
      }).join('') + '</div>';
      if (t[2] > 1) h += '<div class="kb-row"><button data-m="form" class="' + (st.m === 'form' ? 'on' : '') +
        '">ながし・フォーメーション</button><button data-m="box" class="' + (st.m === 'box' ? 'on' : '') + '">BOX</button></div>';
      var present = MARKS.filter(function (m) { return horses.some(function (x) { return mark(x[1]) === m; }); });
      if (present.length) {
        h += '<div class="note">印で選ぶ: ' + heads.map(function (hd, ci) {
          return hd + ' <span class="chips">' + present.map(function (m) {
            return '<button data-chip="' + ci + '" data-mk="' + m + '">' + m + '</button>';
          }).join('') + '</span>';
        }).join('　') + '</div>';
      }
      var win = odds && odds.o['1'];
      h += '<table><tr><th>馬番</th><th>印</th><th style="text-align:left">馬名</th>' + (win ? '<th>単勝</th>' : '') +
        heads.map(function (x, ci) { return '<th>' + x + '<br><button data-all="' + ci + '" style="padding:0 4px;font-size:10px">全</button></th>'; }).join('') + '</tr>';
      horses.forEach(function (x) {
        var c = WAKU[x[2]] || ['#888', '#fff'];
        h += '<tr><td><span class="um" style="background:' + c[0] + ';color:' + c[1] + '">' + x[0] + '</span></td><td>' +
          esc(mark(x[1])) + '</td><td class="nm">' + esc(x[1]) + '</td>' +
          (win ? '<td style="font-size:12px">' + (win[String(x[0])] ? win[String(x[0])].toFixed(1) : '-') + '</td>' : '') + heads.map(function (_, ci) {
            return '<td><input type="checkbox" data-col="' + ci + '" data-n="' + x[0] + '"' + (st.c[ci].indexOf(x[0]) >= 0 ? ' checked' : '') + '></td>';
          }).join('') + '</tr>';
      });
      h += '</table>';
      var cur = {t: st.t, m: st.m, c: st.c.slice(0, k)}, n = combos(cur.t, cur.m, cur.c).length;
      var cr = n ? oddsRange(odds, cur) : null;
      h += '<div class="kb-row" style="align-items:center">1点 <input type="number" min="1" step="1" value="' + st.money +
        '" class="kb-money" style="width:4.5em;font-size:14px"> 00円　<b>' + n + '点 / ' + (n * st.money * 100).toLocaleString() + '円</b>' +
        (cr ? '　<span class="od">' + fmtOdds(cr[0] === cr[1] ? cr[0] : cr) + '倍</span>' : '') + '</div>' +
        '<div class="kb-row"><button class="kb-add on"' + (n ? '' : ' disabled') + '>＋ 買い目に追加</button>' +
        '<button class="kb-clr-sel">選択をクリア</button></div>';
      var total = 0, nrows = rows();
      if (list.length) {
        h += '<ul>' + list.map(function (it, i) {
          var c = betIds(rid, it).length, r = oddsRange(odds, it); total += c * it.y;
          var det = '';
          if (odds && odds.o[String(it.t)]) {
            var o = odds.o[String(it.t)];
            det = '<details><summary>組番ごとのオッズ・払戻</summary><div class="cmb">' + combos(it.t, it.m, it.c).map(function (cb) {
              var v = o[oddsKey(it.t, cb)], pay = '';
              if (v !== undefined && v !== null) {
                var a = Array.isArray(v) ? v : [v, v];
                pay = ' (' + Math.floor(a[0] * it.y * 100).toLocaleString() + (a[0] === a[1] ? '' : '〜' + Math.floor(a[1] * it.y * 100).toLocaleString()) + '円)';
              }
              return '<span>' + cb.join(typeOf(it.t)[3] ? '→' : '-') + ' <span class="od">' + fmtOdds(v) + '</span>' + pay + '</span>';
            }).join('') + '</div></details>';
          }
          return '<li><span>' + esc(itemLabel(it)) + (r ? '　<span class="od">' + fmtOdds(r[0] === r[1] ? r[0] : r) + '倍</span>' : '') +
            '<br><small>' + c + '点 × ' + (it.y * 100).toLocaleString() + '円 = ' + (c * it.y * 100).toLocaleString() + '円</small>' + det +
            '</span><button data-del="' + i + '">削除</button></li>';
        }).join('') + '</ul><div class="sum">合計 ' + nrows + '点 / ' + (total * 100).toLocaleString() + '円' +
          (nrows > MAX_ROWS ? '<br><span style="color:#c00">netkeibaは1回255点までです。減らしてください。</span>' : '') + '</div>' +
          '<div class="kb-row"><button class="kb-clr-list">買い目をすべて削除</button><button class="kb-copy">買い目をテキストでコピー</button></div>';
      }
      var ok = list.length && nrows <= MAX_ROWS;
      h += '<div class="note">' + (odds ? 'オッズ: JRA公式 ' + esc(odds.fetched.slice(5).replace('-', '/')) + ' 取得（' + esc(odds.asof) +
        '現在・毎時更新）。最新のオッズはnetkeibaの買い目リストでも確認できます。' : 'オッズはJRAの発売開始後、毎時の更新で表示されます。') + '</div>';
      var url = ok ? buyUrl() : '#', chrome = ok && useChrome();
      if (chrome) url = url.replace(/^https:\/\//, 'googlechromes://');
      h += '<a class="buy' + (ok ? '' : ' off') + '"' + (chrome ? '' : ' target="_blank" rel="noopener"') + ' href="' + esc(url) + '">netkeibaで購入へ ▶' +
        (chrome ? '（Chrome）' : '') + '</a>' +
        (IOS_NOT_CHROME ? '<label class="note" style="display:block"><input type="checkbox" class="kb-chrome"' + (useChrome() ? ' checked' : '') +
          '> Chromeで開く（Chromeが入っていない場合は外してください）</label>' : '') +
        '<div class="note">netkeibaのページが開いたら、ブックマークの「netkeiba登録」をタップすると買い目リストに入ります（' +
        '<a href="netkeiba_setup.html">初回設定のしかた</a>）。購入は「IPAT投票へすすむ」からご自身で行ってください。</div>';
      inner.innerHTML = h;
      box.querySelector('.kb-cnt').textContent = list.length ? '　' + nrows + '点 / ' + (total * 100).toLocaleString() + '円' : '';
    }
    function buyUrl() {
      var b = [];
      list.forEach(function (it) { betIds(rid, it).forEach(function (id) { b.push([id, it.y * 100]); }); });
      return NK_BET + rid + '#kb=' + encodeURIComponent(JSON.stringify({r: rid, b: b}));
    }
    function text() {
      return anchor.replace('_', ' ') + 'R\n' + list.map(function (it) {
        return itemLabel(it) + '　' + betIds(rid, it).length + '点 各' + (it.y * 100) + '円';
      }).join('\n');
    }
    inner.addEventListener('click', function (e) {
      var b = e.target.closest('button');
      if (!b) return;
      e.preventDefault();
      var t = typeOf(st.t);
      if (b.dataset.t) { st.t = +b.dataset.t; st.c = [[], [], []]; if (typeOf(st.t)[2] === 1) st.m = 'form'; }
      else if (b.dataset.m) { st.m = b.dataset.m; st.c = [[], [], []]; }
      else if (b.dataset.chip !== undefined) {
        var ci = +b.dataset.chip, mk = b.dataset.mk;
        horses.forEach(function (x) { if (mark(x[1]) === mk && st.c[ci].indexOf(x[0]) < 0) st.c[ci].push(x[0]); });
      } else if (b.dataset.all !== undefined) {
        var cj = +b.dataset.all;
        st.c[cj] = st.c[cj].length === horses.length ? [] : horses.map(function (x) { return x[0]; });
      } else if (b.classList.contains('kb-add')) {
        var k = st.m === 'box' && t[2] > 1 ? 1 : t[2];
        var it = {t: st.t, m: st.m, c: st.c.slice(0, k).map(function (c) { return c.slice().sort(function (x, y) { return x - y; }); }), y: st.money};
        if (combos(it.t, it.m, it.c).length) { list.push(it); save(); st.c = [[], [], []]; }
      } else if (b.classList.contains('kb-clr-sel')) st.c = [[], [], []];
      else if (b.dataset.del !== undefined) { list.splice(+b.dataset.del, 1); save(); }
      else if (b.classList.contains('kb-clr-list')) { list = []; save(); }
      else if (b.classList.contains('kb-copy')) {
        if (navigator.clipboard) navigator.clipboard.writeText(text()).then(function () { b.textContent = 'コピーしました'; });
        return;
      }
      render();
    });
    inner.addEventListener('change', function (e) {
      var x = e.target;
      if (x.dataset.col !== undefined) {
        var c = st.c[+x.dataset.col], n = +x.dataset.n, i = c.indexOf(n);
        if (x.checked && i < 0) c.push(n); else if (!x.checked && i >= 0) c.splice(i, 1);
      } else if (x.classList.contains('kb-chrome')) ls('kbOpenChrome', x.checked ? 1 : 0);
      else if (x.classList.contains('kb-money')) st.money = Math.max(1, Math.floor(+x.value || 1));
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
  window.KBBetBuilder = {combos: combos, betIds: betIds, aPart: aPart, init: init};
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
