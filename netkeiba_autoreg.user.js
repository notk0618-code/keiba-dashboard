// ==UserScript==
// @name         AF Keiba DATA → netkeiba 買い目自動登録
// @namespace    https://notk0618-code.github.io/keiba-dashboard/
// @version      1.1.0
// @description  AF Keiba DATA の「即PATへ送信」で開いた netkeiba 購入ページに、組んだ買い目を自動で登録します（購入はしません）。
// @match        https://race.sp.netkeiba.com/ipat/bet_list.html*
// @match        https://race.netkeiba.com/ipat/bet_list.html*
// @run-at       document-start
// @grant        none
// @noframes
// ==/UserScript==
/* Runs only on netkeiba's bet page, and only when the URL carries #kb=... made by betbuilder.js on AF Keiba DATA.
 * It writes the bets into netkeiba's own bet list (browser storage 'ndi::bet_<race_id>', the same place netkeiba's
 * page keeps it) and nothing else: no login, no purchase, no network request. Buying stays netkeiba's
 * 「IPAT投票へすすむ」 → IPAT → the user's own confirm. Same checks as netkeiba_bookmarklet.js (kept as the fallback). */
(function () {
  'use strict';
  var m = location.hash.match(/[#&]kb=([^&]+)/);
  if (!m) return;
  var MSG = 'kbAutoregMsg';
  function done(text, ok) {
    try { sessionStorage.setItem(MSG, JSON.stringify([text, ok ? 1 : 0])); } catch (e) {}
  }
  try {
    var d = JSON.parse(decodeURIComponent(m[1]));
    var q = location.search.match(/race_id=(\d{12})/);
    // drop the hash first so a reload or back/forward never registers the same bets again
    history.replaceState(null, '', location.pathname + location.search);
    if (!q || !d || q[1] !== d.r || !Array.isArray(d.b)) {
      done('AF Keiba DATA: 開いているレースと買い目のレースが違うため、登録しませんでした。', false);
    } else {
      var k = 'ndi::bet_' + d.r, s = null;
      try { s = JSON.parse(localStorage.getItem(k)); } catch (e) {}
      if (!s || typeof s !== 'object' || !s.list) s = {list: {}, uptime: null};
      // netkeiba keys its own rows '<race_id>_<32 hex>'; use the same shape (derived from the bet id, so sending
      // the same bet again overwrites it) and drop rows left by v1.0 ('<race_id>_kb_<bet id>'), which IPAT rejected (120)
      var hx = function (str, seed) {
        var h = seed >>> 0;
        for (var i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
        return ('0000000' + h.toString(16)).slice(-8);
      };
      var key = function (id) { return d.r + '_' + hx(id, 2166136261) + hx(id, 1) + hx(id, 2) + hx(id, 3); };
      Object.keys(s.list).forEach(function (x) { if (x.indexOf(d.r + '_kb_') === 0) delete s.list[x]; });
      var n = 0, bad = 0;
      d.b.slice(0, 255).forEach(function (x) {
        if (Array.isArray(x) && /^a\d-\d{2}-\d{1,2}_b[1-8]_c[0-8](_\d{1,2}(-\d{1,2})*){1,3}(_1)?$/.test(x[0]) &&
            x[1] >= 100 && x[1] % 100 === 0 && x[1] <= 1000000) {
          s.list[key(x[0])] = {bet_id: x[0], bet_money: x[1]}; n++;
        } else bad++;
      });
      var t = new Date(), p = function (v) { return ('0' + v).slice(-2); };
      s.uptime = t.getFullYear() + '-' + p(t.getMonth() + 1) + '-' + p(t.getDate()) + ' ' + p(t.getHours()) + ':' +
        p(t.getMinutes()) + ':' + p(t.getSeconds());
      localStorage.setItem(k, JSON.stringify(s));
      done('AF Keiba DATA: ' + n + '件を買い目リストに登録しました' + (bad ? '（' + bad + '件は形式が正しくないため除外）' : '') +
        '。金額を確認して「IPAT投票へすすむ」へ。', n > 0);
      // netkeiba's page reads the list when it loads; if it has already loaded, load it again once
      if (document.readyState !== 'loading') { location.reload(); return; }
    }
  } catch (e) {
    done('AF Keiba DATA: 買い目を登録できませんでした（' + e.message + '）。', false);
  }
})();
(function () {
  'use strict';
  function show() {
    var v = null;
    try { v = JSON.parse(sessionStorage.getItem('kbAutoregMsg')); sessionStorage.removeItem('kbAutoregMsg'); } catch (e) {}
    if (!v || !document.body) return;
    var b = document.createElement('div');
    b.setAttribute('role', 'status');
    b.style.cssText = 'position:fixed;left:8px;right:8px;top:8px;z-index:2147483647;padding:10px 36px 10px 12px;border-radius:10px;' +
      'font:bold 14px/1.5 -apple-system,sans-serif;box-shadow:0 2px 10px rgba(0,0,0,.25);color:#fff;background:' + (v[1] ? '#1d6f42' : '#b3261e');
    b.textContent = v[0];
    var x = document.createElement('button');
    x.textContent = '×';
    x.setAttribute('aria-label', '閉じる');
    x.style.cssText = 'position:absolute;right:6px;top:6px;border:0;background:transparent;color:#fff;font-size:20px;line-height:1;padding:4px 8px';
    x.onclick = function () { b.remove(); };
    b.appendChild(x);
    document.body.appendChild(b);
    if (v[1]) setTimeout(function () { b.remove(); }, 8000);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', show); else show();
})();
