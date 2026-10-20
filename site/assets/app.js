/* احتمالات | Ihtimal — static site, no build step.
   Data: always loads the real files under data/ (no mock fallback; a missing file shows the error state, never fake numbers).
   Contract (see data/SCHEMA.md): featured.json, leagues/{spl,epl,laliga,ligue1}.json, matches/<id>.json, record.json, meta.json */
(function () {
  'use strict';
  var TD = window.TeamDict || { find: function () { return null; }, normName: function (s) { return String(s || '').toLowerCase().replace(/[^a-z0-9]/g, ''); } };

  /* ---------- constants ---------- */
  var LEAGUES = [
    { key: 'spl', ar: 'دوري روشن', long: 'دوري روشن السعودي', flag: 'sa' },
    { key: 'epl', ar: 'الإنجليزي', long: 'الدوري الإنجليزي الممتاز', flag: 'gb-eng' },
    { key: 'laliga', ar: 'الإسباني', long: 'الدوري الإسباني', flag: 'es' },
    { key: 'ligue1', ar: 'الفرنسي', long: 'الدوري الفرنسي', flag: 'fr' }
  ];
  var ACCT = '@mo_ai_engineer', TIKTOK = 'https://www.tiktok.com/@mo_ai_engineer';
  var LIVE_MS = 3 * 3600e3; // a game with no recorded result is shown (greyed) for 3 h after kick-off, then dropped from the lists
  var OUT_KEYS = ['H', 'D', 'A'];
  // Matches pinned on top of their league list (besides any row flagged `featured`/`pinned` in the data).
  var PIN_IDS = ['2026-10-23_al-qadsiah-al-hilal', '2026-10-23_alqadsiah-alhilal'];

  /* ---------- tiny DOM helper ---------- */
  // Arabic text containing digits: isolate each number as an LTR run so years / times / percentages never get reordered.
  function richNode(v) {
    v = String(v);
    if (!/[؀-ۿ]/.test(v) || !/\d/.test(v)) return document.createTextNode(v);
    var re = /(?:[A-Za-z]+-)?\d+(?:[.:\-\/,]\d+)*%?/g, last = 0, m, f = document.createDocumentFragment();
    while ((m = re.exec(v))) {
      if (m.index > last) f.appendChild(document.createTextNode(v.slice(last, m.index)));
      var b = document.createElement('bdi'); b.dir = 'ltr'; b.className = 'n'; b.textContent = m[0]; f.appendChild(b);
      last = m.index + m[0].length;
    }
    if (last < v.length) f.appendChild(document.createTextNode(v.slice(last)));
    return f;
  }
  function setText(e, v) { e.appendChild(richNode(v)); }
  function h(tag, props, kids) {
    var e = document.createElement(tag), k, v;
    if (props) for (k in props) {
      v = props[k];
      if (v == null || v === false) continue;
      if (k === 'class') e.className = v;
      else if (k === 'text') setText(e, v);
      else if (k === 'style') e.setAttribute('style', v);
      else if (k.slice(0, 2) === 'on') e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v === true ? '' : v);
    }
    (function add(list) {
      if (list == null) return;
      if (!Array.isArray(list)) list = [list];
      list.forEach(function (c) {
        if (c == null || c === false) return;
        if (Array.isArray(c)) return add(c);
        e.appendChild(typeof c === 'object' ? c : richNode(c));
      });
    })(kids);
    return e;
  }
  function $(sel, root) { return (root || document).querySelector(sel); }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }
  function num(x) { if (x === null || x === undefined || x === '') return null; x = +x; return isFinite(x) ? x : null; }
  function first() { for (var i = 0; i < arguments.length; i++) if (arguments[i] !== undefined && arguments[i] !== null) return arguments[i]; return null; }
  function ltr(text, cls) { return h('bdi', { class: 'n' + (cls ? ' ' + cls : ''), dir: 'ltr' }, String(text)); }

  /* ---------- data loading: data/ only ---------- */
  var cache = {};
  function okJson(r) { if (!r.ok) throw new Error(r.status); return r.json(); }
  function getJSON(path) {
    if (cache[path]) return cache[path];
    cache[path] = fetch('data/' + path, { cache: 'no-cache' }).then(okJson);
    return cache[path];
  }
  function tryJSON(path) { return getJSON(path).catch(function () { return null; }); }

  /* ---------- time ---------- */
  var F_DAY = new Intl.DateTimeFormat('ar-u-nu-latn-ca-gregory', { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'Asia/Riyadh' });
  var F_KSA = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Riyadh' });
  var F_UK = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Europe/London' });
  var F_DAY_UTC = new Intl.DateTimeFormat('ar-u-nu-latn-ca-gregory', { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'UTC' });
  function validDate(d) { return d instanceof Date && !isNaN(d.getTime()); }
  function dayLabel(d) { return validDate(d) ? F_DAY.format(d).replace(/،/g, '') : ''; }
  function dayKey(d) { return validDate(d) ? new Date(d.getTime() + 3 * 3600e3).toISOString().slice(0, 10) : 'x'; }
  function tKSA(d) { return validDate(d) ? F_KSA.format(d) : ''; }
  function tUK(d) { return validDate(d) ? F_UK.format(d) : ''; }
  function utcStamp(iso) { var d = new Date(iso); return validDate(d) ? d.toISOString().slice(0, 16).replace('T', ' ') + ' UTC' : ''; }
  function plural(n, one, two, few, many) {
    n = Math.round(n);
    if (n === 1) return one; if (n === 2) return two;
    return n + ' ' + (n >= 3 && n <= 10 ? few : many);
  }
  function hoursPhrase(ms) {
    var mins = Math.max(0, Math.round(ms / 60000));
    if (mins < 60) return plural(mins, 'دقيقة واحدة', 'دقيقتين', 'دقائق', 'دقيقة');
    var hrs = Math.round(mins / 60);
    if (hrs >= 48) return plural(Math.round(hrs / 24), 'يوم واحد', 'يومين', 'أيام', 'يوماً');
    return plural(hrs, 'ساعة واحدة', 'ساعتين', 'ساعات', 'ساعة');
  }

  /* ---------- normalisation ---------- */
  function dotColour(hex) {
    var m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
    if (!m) return '#7E8CA6';
    var n = parseInt(m[1], 16), r = n >> 16 & 255, g = n >> 8 & 255, b = n & 255;
    function lum(r, g, b) { return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255; }
    var t = 0;
    while (lum(r, g, b) < 0.42 && t < 10) { r += (255 - r) * 0.18; g += (255 - g) * 0.18; b += (255 - b) * 0.18; t++; }
    return 'rgb(' + Math.round(r) + ',' + Math.round(g) + ',' + Math.round(b) + ')';
  }
  function slugify(s) { return TD.normName(s) || 'team'; }
  function teamOf(t) {
    if (typeof t === 'string') t = { en: t, id: t };
    t = t || {};
    var dict = TD.find(t.id, t.en, t.name, t.short);
    var en = t.en || t.name || (dict && dict.en) || t.id || '';
    var ar = t.ar || (dict && dict.ar) || en;
    var id = t.id || slugify(en);
    return { id: id, ar: ar, en: en, colour: dotColour(t.colour || t.color || (dict && dict.colour)), logo: TD.logo(id, en, dict && dict.en), flag: dict && dict.flag || null };
  }
  function readP(o) {
    if (!o) return null;
    var src = o.probs || o.p || o;
    var hh = num(first(src.p_home, src.home, src.h, src.H)), dd = num(first(src.p_draw, src.draw, src.d, src.D)), aa = num(first(src.p_away, src.away, src.a, src.A));
    if (hh === null || dd === null || aa === null) return null;
    var s = hh + dd + aa;
    if (s > 1.5) { hh /= 100; dd /= 100; aa /= 100; s /= 100; }
    if (s <= 0) return null;
    return { h: hh / s, d: dd / s, a: aa / s };
  }
  function scoreArr(x) {
    if (!x) return null;
    if (Array.isArray(x) && x.length >= 2) return [+x[0], +x[1]];
    if (typeof x === 'string') { var m = x.match(/(\d+)\D+(\d+)/); if (m) return [+m[1], +m[2]]; }
    if (typeof x === 'object' && x.home != null) return [+x.home, +x.away];
    return null;
  }
  function outcomeOf(p) { return p.h >= p.d && p.h >= p.a ? 'H' : (p.d >= p.a ? 'D' : 'A'); }
  function outcomeOfScore(s) { return s[0] > s[1] ? 'H' : (s[0] === s[1] ? 'D' : 'A'); }
  function readTop(list) {
    return (Array.isArray(list) ? list : []).map(function (t) {
      var s = scoreArr(first(t.score, t.s, t)); var p = num(first(t.p, t.prob, t.probability));
      if (p !== null && p > 1) p /= 100;
      return s && p !== null ? { s: s, p: p } : null;
    }).filter(Boolean);
  }
  function readPick(o, p, top) {
    var pk = o.pick || {}, s = scoreArr(first(pk.score, o.pick_score)), sp = num(first(pk.p_score, pk.p, o.p_score));
    if (sp !== null && sp > 1) sp /= 100;
    if (!s && top.length) { s = top[0].s; sp = top[0].p; }
    return { o: pk.outcome || (p ? outcomeOf(p) : null), s: s, p: sp };
  }
  function readResult(m) {
    var r = m.result || m.final || m.actual;
    if (!r) return null;
    var s = scoreArr(first(r.score, r.ft, r)) || (r.home_goals != null ? [+r.home_goals, +r.away_goals] : null);
    return s ? { s: s } : null;
  }
  var COMP_AR = { spl: 'دوري روشن', epl: 'الدوري الإنجليزي الممتاز', laliga: 'الدوري الإسباني', ligue1: 'الدوري الفرنسي', ucl: 'دوري أبطال أوروبا' };
  function compObj(c) { if (!c) return {}; if (typeof c === 'string') return { key: c, ar: COMP_AR[c] || c, en: '' }; return c; }
  function stageAr(s) {
    s = String(s || '').trim(); if (!s || /[\u0600-\u06FF]/.test(s)) return s;
    var parts = [], mm = /(?:MD|matchday|round|gw|game ?week)\s*(\d+)/i.exec(s);
    if (/league phase/i.test(s)) parts.push('مرحلة الدوري');
    if (/quarter/i.test(s)) parts.push('ربع النهائي'); else if (/semi/i.test(s)) parts.push('نصف النهائي'); else if (/final/i.test(s)) parts.push('النهائي');
    if (mm) parts.push('الجولة ' + mm[1]);
    return parts.join(' | ');
  }
  function normMatch(m, fallbackComp) {
    if (!m) return null;
    var useAdj = !!(m.adjusted && readP(m.adjusted)) && m.headline !== 'base';
    var head = useAdj ? Object.assign({}, m, m.adjusted) : m;
    var p = readP(head), top = readTop(head.top_scores), pick = readPick(head, p, top);
    var comp = m.competition ? compObj(m.competition) : (fallbackComp || {});
    var base = readP(m.base) ? { p: readP(m.base), lam: lamOf(m.base), pick: readPick(m.base, readP(m.base), readTop(m.base.top_scores)) } : null;
    var res = readResult(m);
    var st = String(m.status || '').toLowerCase();
    var x = {
      id: m.match_id || m.id, raw: m,
      comp: { key: comp.key || '', ar: comp.ar || COMP_AR[comp.key] || comp.en || '', en: comp.en || '', stage: comp.stage_ar || stageAr(comp.stage || m.stage || '') },
      ko: new Date(m.kickoff_utc || m.kickoff), venue: m.venue || '',
      status: st.indexOf('postpon') >= 0 ? 'postponed' : (res ? 'ft' : 'scheduled'),
      home: teamOf(m.home), away: teamOf(m.away), p: p, pick: pick, top: top,
      grid: Array.isArray(head.grid_6x6) ? head.grid_6x6 : (Array.isArray(m.grid_6x6) ? m.grid_6x6 : null), lam: lamOf(head), xgoals: xgOf(head) || xgOf(m),
      base: base, hasAdj: useAdj,
      elo: m.elo || null, adjustments: Array.isArray(m.adjustments) ? m.adjustments : [],
      bench: m.benchmarks || {}, lockedAt: m.locked_at || (m.lock && m.lock.locked_at) || null,
      sha: m.sha256 || (m.lock && m.lock.sha256) || null, result: res, pinned: !!(m.pinned || m.featured || PIN_IDS.indexOf(m.match_id || m.id) >= 0),
      version: m.version || 1, note: m.note_ar || '', why: Array.isArray(m.why) ? m.why : [], adjLabel: m.adjustments_label || null, legs: m.legs || null, cutoff: m.data_cutoff_utc || null, locked: !!(m.locked || m.locked_at), generatedAt: m.generated_at || null, xg: m.xg_factor || null, modelVersion: m.model_version || ''
    };
    return x;
  }
  function xgOf(o) { var e = o && o.expected_goals; return e && num(e.home) !== null ? { h: +e.home, a: +e.away } : null; }
  function lamOf(o) { var a = num(o.lambda_home), b = num(o.lambda_away); return a !== null && b !== null ? { h: a, a: b } : null; }
  function listOf(d) {
    if (Array.isArray(d)) return d;
    if (d && typeof d === 'object') return d.matches || d.fixtures || d.items || d.featured || d.rows || d.entries || [];
    return [];
  }

  /* ---------- loaders ---------- */
  function loadMatch(id) {
    return getJSON('matches/' + encodeURIComponent(id) + '.json').then(function (d) { return normMatch(d); });
  }
  function loadFeatured() {
    return getJSON('featured.json').then(function (d) {
      return Promise.all(listOf(d).map(function (it) {
        if (readP(it && (it.adjusted || it))) return normMatch(it);
        var id = typeof it === 'string' ? it : (it.match_id || it.id);
        return id ? loadMatch(id).catch(function () { return null; }) : null;
      }));
    }).then(function (a) { return a.filter(Boolean); });
  }
  function resultMap(rec) {
    var map = {};
    listOf(rec).forEach(function (r) { var res = readResult(r); if (res && r.match_id) map[r.match_id] = res; });
    return map;
  }
  function attachResults(ms, rmap) {
    ms.forEach(function (m) { if (!m.result && rmap[m.id]) { m.result = rmap[m.id]; m.status = 'ft'; } });
    return ms;
  }
  function loadLeague(key) {
    return Promise.all([tryJSON('leagues/' + key + '.json'), tryJSON('record.json')]).then(function (r) {
      var d = r[0];
      if (!d) return { key: key, matches: [], missing: true };
      var comp = d.league || d.competition || null;
      var ms = listOf(d).map(function (row) { var x = normMatch(row, comp); if (x && !x.comp.key) x.comp.key = key; return x; }).filter(Boolean);
      attachResults(ms, resultMap(r[1]));
      ms.sort(function (a, b) { return a.ko - b.ko; });
      return { key: key, matches: upcoming(ms), generated: d.generated_at || null };
    });
  }
  // Kick-off already passed (compared with the browser's clock) and no result recorded yet:
  // 'live' = kicked off less than 3 h ago, 'over' = older than that, '' = not started / has a result / postponed.
  function startState(m) {
    if (m.result || m.status === 'postponed' || !validDate(m.ko)) return '';
    var d = Date.now() - m.ko.getTime();
    return d < 0 ? '' : (d < LIVE_MS ? 'live' : 'over');
  }
  // Upcoming list: drop games that kicked off more than 3 h ago without a recorded result; the ones just started stay, greyed out.
  function upcoming(ms) {
    return ms.filter(function (m) { return startState(m) !== 'over'; });
  }

  /* ---------- formatting ---------- */
  function round3(p) { // largest-remainder rounding so the three numbers add up to 100
    var v = [p.h, p.d, p.a].map(function (x) { return x * 100; }), f = v.map(Math.floor), left = 100 - f[0] - f[1] - f[2];
    v.map(function (x, i) { return [x - f[i], i]; }).sort(function (a, b) { return b[0] - a[0]; }).slice(0, left).forEach(function (r) { f[r[1]]++; });
    return f;
  }
  function pct(x) { if (x == null) return ''; var v = x * 100; return (v > 0 && v < 1 ? '<1' : Math.round(v)) + '%'; }
  function outcomeLabel(o, m) { return o === 'H' ? 'فوز ' + m.home.ar : (o === 'A' ? 'فوز ' + m.away.ar : 'تعادل'); }
  function rps(p, act) {
    var o = [act === 'H' ? 1 : 0, act === 'D' ? 1 : 0, act === 'A' ? 1 : 0], c1 = p.h - o[0], c2 = p.h + p.d - o[0] - o[1];
    return (c1 * c1 + c2 * c2) / 2;
  }
  function pOf(m, s) { // model probability for an exact score
    if (m.grid && s[0] < m.grid.length && m.grid[s[0]] && s[1] < m.grid[s[0]].length) return num(m.grid[s[0]][s[1]]);
    var t = m.top.filter(function (x) { return x.s[0] === s[0] && x.s[1] === s[1]; })[0];
    return t ? t.p : null;
  }

  /* ---------- components ---------- */
  function flagImg(code, cls) {
    if (!code || !TD.hasFlag(code)) return null;
    return h('img', { class: 'flag' + (cls ? ' ' + cls : ''), src: 'assets/flags/' + code + '.svg', alt: '', width: 20, height: 15, decoding: 'async' });
  }
  // Club crest (assets/logos/<id>.png, ESPN image resized to 96x96); the coloured dot is the fallback when there is no file or it fails to load.
  function crest(t, size) {
    var dot = h('i', { class: 'dot' + (size > 30 ? ' lg' : ''), style: 'background:' + t.colour });
    if (!t.logo) return dot;
    return h('img', { class: 'crest c' + size, src: 'assets/logos/' + encodeURIComponent(t.logo) + '.png', alt: '', width: size, height: size, decoding: 'async',
      onerror: function (e) { var im = e.currentTarget; if (im.parentNode) im.parentNode.replaceChild(dot, im); } });
  }
  // Club column used on the featured card and the match page: crest, Arabic name, English name (+ country flag on Champions League games).
  function clubCol(m, t, cls) {
    var fl = m.comp.key === 'ucl' ? flagImg(t.flag, 'badge') : null;
    return h('div', { class: 'ft ' + cls }, [fl ? h('span', { class: 'crest-wrap' }, [crest(t, 36), fl]) : crest(t, 36), h('b', { text: t.ar }), t.en !== t.ar ? h('small', { text: t.en }) : null]);
  }
  function acctLink(cls) {
    return h('a', { class: 'acct-link n' + (cls ? ' ' + cls : ''), dir: 'ltr', href: TIKTOK, target: '_blank', rel: 'noopener', text: ACCT });
  }
  function leagueFlag(key) {
    var l = LEAGUES.filter(function (x) { return x.key === key; })[0];
    return l ? flagImg(l.flag) : null;
  }
  function teamTag(t, opts) {
    opts = opts || {};
    return h('span', { class: 'tm' }, [
      crest(t, 28),
      h('span', { class: 'tm-t' }, [h('b', { text: t.ar }), (opts.en !== false && t.en && t.en !== t.ar) ? h('small', { text: t.en }) : null])
    ]);
  }
  function scorePill(s, cls) { // RTL flex => home score sits on the right, next to the home team
    return h('span', { class: 'score ' + (cls || '') }, [h('b', { text: s[0] }), h('i', { text: '–' }), h('b', { text: s[1] })]);
  }
  function wdlBar(m, size) {
    if (!m.p) return h('div', { class: 'wdl-na', text: 'لا توجد احتمالات بعد' });
    var r = round3(m.p), vals = [m.p.h, m.p.d, m.p.a], names = ['فوز ' + m.home.ar, 'تعادل', 'فوز ' + m.away.ar];
    var best = outcomeOf(m.p);
    var bar = h('div', { class: 'wdl ' + (size || ''), role: 'img', 'aria-label': names.map(function (n, i) { return n + ' ' + r[i] + '%'; }).join(' | ') },
      OUT_KEYS.map(function (k, i) {
        return h('div', { class: 'seg ' + k.toLowerCase() + (k === best ? ' top' : ''), style: 'flex:' + Math.max(vals[i], 0.02) + ' 1 0' }, [ltr(r[i] + '%')]);
      }));
    if (size !== 'lg') return bar;
    return h('div', { class: 'wdl-wrap' }, [bar, h('div', { class: 'wdl-lbl' }, OUT_KEYS.map(function (k, i) {
      return h('div', { class: 'lbl ' + k.toLowerCase() }, [h('i'), h('span', { text: names[i] })]);
    }))]);
  }
  function legend() {
    return h('div', { class: 'key', 'aria-hidden': 'true' }, [
      h('div', { class: 'key-r' }, [h('span', { class: 'lbl h' }, [h('i'), 'فوز صاحب الأرض']), h('span', { class: 'lbl d' }, [h('i'), 'تعادل']), h('span', { class: 'lbl a' }, [h('i'), 'فوز الضيف'])]),
      h('div', { class: 'key-n', text: 'السطر الأول: صاحب الأرض | الأوقات بتوقيت السعودية' })
    ]);
  }
  function whenLine(m) {
    if (!validDate(m.ko)) return '';
    return [dayLabel(m.ko), ' | ', tKSA(m.ko), ' بتوقيت السعودية | ', tUK(m.ko), ' بريطانيا'].join('');
  }
  var CANON_DROP = { sha256: 1, locked_at: 1, benchmarks: 1, sanity: 1 };
  function canon(o) { // must match model/lockutil.py canonical()
    if (o === null) return 'null';
    if (o === true || o === false) return String(o);
    if (typeof o === 'number') {
      if (Number.isInteger(o)) return String(o);
      var t = o.toFixed(6).replace(/0+$/, '').replace(/\.$/, ''); return (t === '-0' || t === '') ? '0' : t;
    }
    if (typeof o === 'string') return JSON.stringify(o);
    if (Array.isArray(o)) return '[' + o.map(canon).join(',') + ']';
    return '{' + Object.keys(o).sort().map(function (k) { return JSON.stringify(k) + ':' + canon(o[k]); }).join(',') + '}';
  }
  function verifyHash(m) {
    var o = JSON.parse(JSON.stringify(m.raw)); Object.keys(CANON_DROP).forEach(function (k) { delete o[k]; });
    if (o.elo) { delete o.elo.clubelo_home; delete o.elo.clubelo_away; }
    var bytes = new TextEncoder().encode(canon(o));
    return crypto.subtle.digest('SHA-256', bytes).then(function (buf) {
      return Array.prototype.map.call(new Uint8Array(buf), function (b) { return ('0' + b.toString(16)).slice(-2); }).join('') === m.sha;
    });
  }
  function lockLine(m, withVerify) {
    if (!m.lockedAt) return h('div', { class: 'lock off' }, [h('span', { text: 'تنبؤ تلقائي | لم يُقفل بعد' })]);
    var ko = m.ko, lk = new Date(m.lockedAt), pre = validDate(ko) && validDate(lk) ? ko - lk : null;
    var when = pre !== null && pre > 0 ? 'قُفل قبل المباراة ' + (function (t) { return /^\d/.test(t) ? 'بـ ' + t : 'ب' + t; })(hoursPhrase(pre)) : 'قُفل';
    return h('div', { class: 'lock' }, [
      h('span', { class: 'lock-ic', text: '🔒' }),
      h('div', { class: 'lock-t' }, [
        h('div', { class: 'lock-w', text: when }),
        h('div', { class: 'lock-m' }, [ltr(utcStamp(m.lockedAt)), m.sha ? [h('span', { class: 'sep', text: '|' }), h('bdi', { class: 'sha n', dir: 'ltr', title: m.sha }, 'sha256 ' + m.sha.slice(0, 10))] : null]),
        withVerify && m.sha && window.crypto && crypto.subtle ? h('button', { class: 'verify', type: 'button', onclick: function (e) {
          var b = e.currentTarget, out = b.nextSibling; b.disabled = true;
          verifyHash(m).then(function (ok) { out.textContent = ok ? 'البصمة مطابقة: لم يتغيّر هذا الملف منذ قفله.' : 'البصمة لا تطابق الملف الحالي.'; out.className = 'verify-out ' + (ok ? 'ok' : 'no'); }, function () { out.textContent = 'تعذّر التحقق في هذا المتصفح.'; b.disabled = false; });
        }, text: 'تحقق من البصمة في متصفحك' }) : null,
        withVerify && m.sha ? h('div', { class: 'verify-out' }) : null
      ])
    ]);
  }
  function pickLine(m) {
    if (!m.pick.s) return null;
    return h('div', { class: 'pick' }, [
      h('span', { class: 'pick-l', text: 'أرجح نتيجة' }), scorePill(m.pick.s, 'lg'),
      m.pick.p != null ? h('span', { class: 'pick-p' }, ['احتمالها ', ltr(pct(m.pick.p))]) : null
    ]);
  }

  function featuredCard(m) {
    var o = m.p ? outcomeOf(m.p) : null;
    var st = startState(m);
    return h('a', { class: 'card feat' + (st ? ' past' : ''), href: 'match.html?id=' + encodeURIComponent(m.id) }, [
      h('div', { class: 'feat-top' }, [
        h('span', { class: 'chip' }, [leagueFlag(m.comp.key), m.comp.ar + (m.comp.stage ? ' | ' + m.comp.stage : '')]),
        st ? h('span', { class: 'ppd live', text: st === 'live' ? 'بدأت' : 'بانتظار النتيجة' }) : null
      ]),
      h('div', { class: 'feat-when', text: whenLine(m) }),
      h('div', { class: 'feat-teams' }, [
        clubCol(m, m.home, 'home'),
        h('div', { class: 'ft-mid' }, m.pick.s ? [scorePill(m.pick.s, 'xl'), h('small', { text: 'أرجح نتيجة' + (m.pick.p != null ? ' ' + pct(m.pick.p) : '') })] : null),
        clubCol(m, m.away, 'away')
      ]),
      wdlBar(m, 'lg'),
      o ? h('div', { class: 'feat-lean' }, ['النموذج يرجّح: ', h('b', { text: outcomeLabel(o, m) }), ' ', ltr(pct(m.p[o === 'H' ? 'h' : (o === 'D' ? 'd' : 'a')]))]) : null,
      lockLine(m),
      m.result ? h('div', { class: 'feat-res' }, ['النتيجة النهائية ', scorePill(m.result.s)]) : null
    ]);
  }

  function fixtureRow(m, opts) {
    opts = opts || {};
    var pp = m.status === 'postponed', st = startState(m);
    return h('a', { class: 'fx' + (m.pinned && opts.pin ? ' pinned' : '') + (st ? ' past' : ''), href: 'match.html?id=' + encodeURIComponent(m.id) }, [
      m.pinned && opts.pin ? h('span', { class: 'pin', text: 'مباراة مميّزة' }) : null,
      h('div', { class: 'fx-top' }, [
        h('div', { class: 'fx-teams' }, [teamTag(m.home, { en: false }), teamTag(m.away, { en: false })]),
        h('div', { class: 'fx-time' }, pp ? [h('b', { class: 'ppd', text: 'مؤجلة' })] : st === 'live' ? [h('b', { class: 'ppd live', text: 'بدأت' }), h('small', { text: 'النتيجة بعد النهاية' })] :
          st === 'over' ? [h('b', { class: 'ppd', text: 'بانتظار النتيجة' }), h('small', { text: 'بدأت قبل ' + hoursPhrase(Date.now() - m.ko.getTime()) })] :
          m.result ? [scorePill(m.result.s), m.p ? h('small', { class: 'mk ' + (((m.pick.o || outcomeOf(m.p)) === outcomeOfScore(m.result.s)) ? 'ok' : 'no'), text: ((m.pick.o || outcomeOf(m.p)) === outcomeOfScore(m.result.s)) ? '✓ أصاب النموذج' : '✗ لم يصب' }) : h('small', { text: 'انتهت' })] :
          [ltr(tKSA(m.ko), 'big'), h('small', null, [ltr(tUK(m.ko)), ' بريطانيا'])])
      ]),
      pp ? null : wdlBar(m, 'sm')
    ]);
  }

  function groupByDay(ms) {
    var out = [], cur = null;
    ms.forEach(function (m) {
      var k = dayKey(m.ko);
      if (!cur || cur.k !== k) { cur = { k: k, d: m.ko, items: [] }; out.push(cur); }
      cur.items.push(m);
    });
    return out;
  }
  function fixtureList(ms, opts) {
    opts = opts || {};
    var wrap = h('div', { class: 'fxlist' });
    var pinned = opts.pin ? ms.filter(function (m) { return m.pinned; }) : [], rest = opts.pin ? ms.filter(function (m) { return !m.pinned; }) : ms;
    if (!ms.length) return h('div', { class: 'empty', text: 'لا توجد مباريات قادمة في هذا الدوري حالياً.' });
    if (opts.key !== false) wrap.appendChild(legend());
    pinned.forEach(function (m) { wrap.appendChild(fixtureRow(m, { pin: true })); });
    if (opts.limit) {
      rest.slice(0, Math.max(0, opts.limit - pinned.length)).forEach(function (m) { wrap.appendChild(fixtureRow(m)); });
    } else {
      groupByDay(rest).forEach(function (g) {
        wrap.appendChild(h('h3', { class: 'day', text: dayLabel(g.d) }));
        g.items.forEach(function (m) { wrap.appendChild(fixtureRow(m)); });
      });
    }
    return wrap;
  }

  function tabs(active, onPick, hrefFn) {
    return h('div', { class: 'tabs', role: 'tablist' }, LEAGUES.map(function (l) {
      return h('a', { class: 'tab' + (l.key === active ? ' on' : ''), role: 'tab', 'aria-selected': l.key === active ? 'true' : 'false', href: hrefFn(l.key),
        onclick: function (e) { e.preventDefault(); onPick(l.key); } }, [flagImg(l.flag), h('span', { text: l.ar })]);
    }));
  }

  /* ---------- shell: header, footer, banners ---------- */
  function shell(page) {
    var nav = [['index.html', 'الرئيسية', 'home'], ['league.html', 'الدوريات', 'league'], ['record.html', 'السجل', 'record'], ['method.html', 'المنهج', 'method']];
    var hdr = h('div', { class: 'hdr-in' }, [
      h('header', { class: 'top' }, [h('div', { class: 'wrap top-in' }, [
        h('div', { class: 'brand-col' }, [
          h('a', { class: 'brand', href: 'index.html', 'aria-label': 'احتمالات' }, [
            h('span', { class: 'logo', 'aria-hidden': 'true' }, [h('i'), h('i'), h('i')]), h('b', { text: 'احتمالات' })]),
          acctLink('handle')]),
        h('a', { class: 'tt-btn', href: TIKTOK, target: '_blank', rel: 'noopener' }, [h('span', { text: 'تابعني على' }), h('bdi', { dir: 'ltr', text: 'TikTok' })])])]),
      h('div', { class: 'navbar' }, [h('nav', { class: 'wrap nav' }, nav.map(function (n) { return h('a', { href: n[0], class: (page === n[2] || (page === 'match' && n[2] === 'league') || (page === 'team' && n[2] === 'league')) ? 'on' : '' }, n[1]); }))])
    ]);
    var ftr = h('footer', { class: 'foot' }, [h('div', { class: 'wrap' }, [
      h('p', { class: 'disc', text: 'تنبؤات إحصائية للتسلية والتعلّم — ليست نصيحة مراهنة' }),
      h('p', { class: 'disc-en', dir: 'ltr', text: 'Estimated probabilities for education and entertainment. Not betting advice.' }),
      h('p', { class: 'by' }, [h('a', { href: 'method.html', text: 'المنهج والبيانات' }), ' ', h('span', { class: 'sep', text: '|' }), ' ', h('a', { class: 'n', dir: 'ltr', href: TIKTOK, target: '_blank', rel: 'noopener', text: 'by ' + ACCT })])
    ])]);
    $('#hdr').appendChild(hdr); $('#ftr').appendChild(ftr);
  }
  function updatedLine(iso) {
    var d = new Date(iso); if (!validDate(d)) return null;
    return h('p', { class: 'updated' }, ['آخر تحديث: ', dayLabel(d), ' ', ltr(tKSA(d)), ' بتوقيت السعودية']);
  }
  function fail(app) {
    clear(app).appendChild(h('div', { class: 'empty err' }, [h('b', { text: 'تعذّر تحميل البيانات.' }), h('p', { text: 'حدّث الصفحة بعد قليل. إذا استمرت المشكلة فالبيانات لم تُنشر بعد.' })]));
  }
  function section(title, kids, cls) {
    return h('section', { class: 'sec ' + (cls || '') }, [h('div', { class: 'sec-h' }, [h('h2', { text: title })]), kids]);
  }

  /* ---------- record maths ---------- */
  function recEntry(e) {
    var src = e.prediction ? Object.assign({}, e, e.prediction) : Object.assign({}, e);
    if (e.base_prediction) src.base = e.base_prediction;
    delete src.adjusted; delete src.headline;
    var m = normMatch(src); if (!m) return null;
    m.counts = e.counts_in_tally !== undefined ? !!e.counts_in_tally : e.counts !== false;
    m.label = e.label || (e.version && e.version > 1 ? 'تحديث v' + e.version : '');
    m.hitO = null; m.hitS = null; m.rps = null; m.bHitO = null; m.bHitS = null;
    if (m.result && m.p) {
      var act = outcomeOfScore(m.result.s);
      m.hitO = (m.pick.o || outcomeOf(m.p)) === act;
      m.hitS = !!(m.pick.s && m.pick.s[0] === m.result.s[0] && m.pick.s[1] === m.result.s[1]);
      m.rps = rps(m.p, act);
      if (m.base) {
        m.bHitO = (m.base.pick.o || outcomeOf(m.base.p)) === act;
        m.bHitS = !!(m.base.pick.s && m.base.pick.s[0] === m.result.s[0] && m.base.pick.s[1] === m.result.s[1]);
      }
    }
    return m;
  }
  function recStats(list) {
    var sc = list.filter(function (m) { return m.counts && m.result && m.p; });
    var n = sc.length, cnt = function (f) { return sc.filter(f).length; };
    return { n: n, ho: cnt(function (m) { return m.hitO; }), hs: cnt(function (m) { return m.hitS; }), bho: cnt(function (m) { return m.bHitO; }), bhs: cnt(function (m) { return m.bHitS; }),
      homeAlways: cnt(function (m) { return outcomeOfScore(m.result.s) === 'H'; }), rps: n ? sc.reduce(function (t, m) { return t + m.rps; }, 0) / n : null };
  }
  function trackedStats(list) {
    var sc = list.filter(function (m) { return !m.counts && m.result && m.p; }), n = sc.length;
    return { n: n, ho: sc.filter(function (m) { return m.hitO; }).length, hs: sc.filter(function (m) { return m.hitS; }).length };
  }

  /* ---------- pages ---------- */
  var PAGES = {};

  PAGES.home = function (app) {
    return Promise.all([loadFeatured(), Promise.all(LEAGUES.map(function (l) { return loadLeague(l.key); })), tryJSON('record.json'), tryJSON('meta.json')]).then(function (r) {
      var feat = r[0], leagues = r[1], rec = r[2], meta = r[3];
      clear(app);
      app.appendChild(h('section', { class: 'hero' }, [h('div', { class: 'wrap' }, [
        h('p', { class: 'kick', text: 'ihtimal | احتمالات' }),
        h('h1', null, ['نموذج تعلّم آلي ', h('span', { class: 'hl', text: 'يحسب احتمالات' }), ' المباريات']),
        h('p', { class: 'strap', text: 'للتعليم والترفيه. توقّعات المباريات الكبرى تُقفل بختم زمني قبل صافرة البداية، وتُنشر النتائج مع الأخطاء.' }),
        meta && meta.generated_at ? updatedLine(meta.generated_at) : null
      ])]));
      var main = h('div', { class: 'wrap' });
      app.appendChild(main);
      if (feat.length) main.appendChild(section('مباريات كبرى', h('div', { class: 'feat-grid' }, feat.map(featuredCard))));

      var box = h('div', { class: 'tabbox' }), active = 'spl';
      var sec = section('المباريات القادمة', box);
      main.appendChild(sec);
      function draw() {
        clear(box);
        var lg = leagues.filter(function (x) { return x.key === active; })[0] || { matches: [] };
        box.appendChild(tabs(active, function (k) { active = k; draw(); }, function (k) { return 'league.html?l=' + k; }));
        box.appendChild(fixtureList(lg.matches, { pin: true, limit: 6 }));
        var meta2 = LEAGUES.filter(function (l) { return l.key === active; })[0];
        box.appendChild(h('a', { class: 'more', href: 'league.html?l=' + active }, 'كل مباريات ' + meta2.long + ' (' + lg.matches.length + ')'));
      }
      draw();

      var st = rec ? recStats(listOf(rec).map(recEntry).filter(Boolean)) : { n: 0 };
      main.appendChild(h('a', { class: 'recchip', href: 'record.html' }, [
        h('span', { class: 'rc-t' }, st.n ? [ltr(st.n), ' ', st.n === 1 ? 'مباراة كبرى مُقيَّمة' : 'مباريات كبرى مُقيَّمة', ' ', h('span', { class: 'sep', text: '|' }), ' ', st.ho + ' من ' + st.n + ' نتيجة صحيحة'] :
          'السجل العلني: كل توقّع يُسجَّل هنا حتى الأخطاء'),
        h('span', { class: 'rc-a', text: 'افتح السجل' })
      ]));
      var bk = meta && meta.backtest && (meta.backtest.site_leagues_holdout_2025_26 || meta.backtest.europe_holdout_2025_26);
      main.appendChild(h('div', { class: 'how' }, [
        h('b', { text: 'كم هو دقيق؟' }),
        h('p', { text: bk && bk.wdl_accuracy != null ?
          'في اختبار موسم 2025-26 الذي لم يره النموذج أصاب نتيجة المباراة (فوز أو تعادل أو خسارة) في ' + Math.round(bk.wdl_accuracy * 100) + '% من ' + bk.n + ' مباراة' + (meta.backtest.site_leagues_holdout_2025_26 ? ' في الدوري الإنجليزي والإسباني والفرنسي' : ' في الدوريات الأوروبية') + '، والنتيجة الدقيقة تصيب تقريباً مرة من كل ' + Math.round(bk.one_exact_score_in || 9) + '. احتمال لا يعني يقين.' :
          'النموذج يصيب نتيجة المباراة (فوز أو تعادل أو خسارة) في نحو نصف المباريات، والنتيجة الدقيقة تصيب تقريباً مرة من كل 9. احتمال لا يعني يقين.' }),
        h('a', { href: 'method.html', text: 'اقرأ المنهج والاختبار كاملاً' })
      ]));
    });
  };

  PAGES.league = function (app) {
    var q = new URLSearchParams(location.search), active = q.get('l');
    if (!LEAGUES.some(function (l) { return l.key === active; })) active = 'spl';
    return Promise.all(LEAGUES.map(function (l) { return loadLeague(l.key); })).then(function (all) {
      clear(app);
      var main = h('div', { class: 'wrap' }), box = h('div', { class: 'tabbox' });
      app.appendChild(h('section', { class: 'pagehead' }, [h('div', { class: 'wrap' }, [h('h1', { text: 'المباريات القادمة' }), h('p', { class: 'sub', text: 'احتمال فوز صاحب الأرض والتعادل وفوز الضيف لكل مباراة في الأسبوعين القادمين.' })])]));
      app.appendChild(main); main.appendChild(box);
      function draw() {
        clear(box);
        var lg = all.filter(function (x) { return x.key === active; })[0], info = LEAGUES.filter(function (l) { return l.key === active; })[0];
        box.appendChild(tabs(active, function (k) { active = k; history.replaceState(null, '', '?l=' + k); draw(); }, function (k) { return '?l=' + k; }));
        box.appendChild(h('h2', { class: 'lg-title' }, [flagImg(info.flag, 'lg'), h('span', { text: info.long }), h('small', { text: lg.matches.length + ' مباراة' })]));
        box.appendChild(fixtureList(lg.matches, { pin: true }));
        document.title = info.long + ' | احتمالات';
      }
      draw();
    });
  };

  function heat(m) {
    if (!m.grid) return null;
    var n = Math.min(6, m.grid.length), max = 0, i, j;
    for (i = 0; i < n; i++) for (j = 0; j < n; j++) max = Math.max(max, num(m.grid[i][j]) || 0);
    var t = h('table', { class: 'heat' }), head = h('tr', null, [h('th', { class: 'corner' })]);
    for (j = 0; j < n; j++) head.appendChild(h('th', { text: j }));
    t.appendChild(head);
    for (i = 0; i < n; i++) {
      var tr = h('tr', null, [h('th', { text: i })]);
      for (j = 0; j < n; j++) {
        var p = num(m.grid[i][j]) || 0, isPick = m.pick.s && m.pick.s[0] === i && m.pick.s[1] === j, isAct = m.result && m.result.s[0] === i && m.result.s[1] === j;
        tr.appendChild(h('td', { class: (isPick ? 'is-pick ' : '') + (isAct ? 'is-act' : ''), style: 'background:rgba(91,200,245,' + (max ? (0.06 + 0.8 * p / max).toFixed(3) : 0) + ')' }, [ltr((p * 100).toFixed(p >= 0.095 ? 0 : 1))]));
      }
      t.appendChild(tr);
    }
    return h('div', null, [
      h('div', { class: 'heat-ax' }, [h('span', null, ['الصفوف: أهداف ', h('b', { text: m.home.ar })]), h('span', null, ['الأعمدة: أهداف ', h('b', { text: m.away.ar })])]),
      h('div', { class: 'heat-sc' }, [t]), h('p', { class: 'fine', text: 'الأرقام نسب مئوية لكل نتيجة بعينها. الإطار الأزرق: أرجح نتيجة.' })
    ]);
  }

  PAGES.match = function (app) {
    var id = new URLSearchParams(location.search).get('id');
    if (!id) return fail(app);
    return Promise.all([loadMatch(id), tryJSON('record.json'), tryJSON('meta.json')]).then(function (rr) {
      var m = attachResults([rr[0]], resultMap(rr[1]))[0], meta0 = rr[2];
      clear(app);
      document.title = m.home.ar + ' ضد ' + m.away.ar + ' | احتمالات';
      var main = h('div', { class: 'wrap' }); app.appendChild(main);
      main.appendChild(h('div', { class: 'crumbs' }, [
        h('a', { href: 'league.html' + (m.comp.key && LEAGUES.some(function (l) { return l.key === m.comp.key; }) ? '?l=' + m.comp.key : ''), text: 'رجوع إلى المباريات' }),
        h('button', { class: 'share', type: 'button', onclick: function (e) {
          var b = e.currentTarget, url = location.href;
          if (navigator.share) { navigator.share({ title: document.title, url: url }).catch(function () {}); return; }
          if (navigator.clipboard) navigator.clipboard.writeText(url).then(function () { b.textContent = 'نُسخ الرابط'; setTimeout(function () { b.textContent = 'شارك'; }, 1600); });
        }, text: 'شارك' })
      ]));
      /* head */
      var head = h('div', { class: 'card mhead' }, [
        h('span', { class: 'chip' }, [leagueFlag(m.comp.key), m.comp.ar + (m.comp.stage ? ' | ' + m.comp.stage : '')]),
        h('div', { class: 'mteams' }, [
          clubCol(m, m.home, 'home'),
          h('div', { class: 'vs', text: m.result ? '' : 'ضد' }, m.result ? [scorePill(m.result.s, 'xl')] : null),
          clubCol(m, m.away, 'away')
        ]),
        m.status === 'postponed' ? h('p', { class: 'ppd-l', text: 'مؤجلة' }) : h('p', { class: 'when', text: whenLine(m) }),
        m.venue ? h('p', { class: 'venue', text: m.venue }) : null,
        startState(m) ? h('p', { class: 'started', text: 'بدأت هذه المباراة ولم تُسجَّل نتيجتها بعد. الأرقام أدناه توقّع ما قبل صافرة البداية.' }) : null,
        h('p', { class: 'acct' }, ['توقّعات من حساب ', acctLink()])
      ]);
      main.appendChild(head);
      if (!m.p || m.status === 'postponed') {
        main.appendChild(h('div', { class: 'empty', text: m.status === 'postponed' ? 'هذه المباراة مؤجلة. ستظهر الاحتمالات عند تحديد موعد جديد.' : 'لا توجد احتمالات لهذه المباراة بعد.' }));
        return;
      }
      /* probabilities + pick */
      var o = outcomeOf(m.p);
      main.appendChild(h('div', { class: 'card' }, [
        h('h2', { class: 'ch', text: 'الاحتمالات' }), wdlBar(m, 'lg'),
        h('p', { class: 'lean' }, ['النموذج يرجّح: ', h('b', { text: outcomeLabel(o, m) }), ' ', ltr(pct(m.p[o === 'H' ? 'h' : (o === 'D' ? 'd' : 'a')]))]),
        pickLine(m),
        m.pick.s ? h('p', { class: 'fine', text: 'هذا أرجح سيناريو داخل النتيجة الأرجح، لكنه ليس وعداً: النتيجة الدقيقة تصيب تقريباً مرة من كل 9.' }) : null,
        lockLine(m, true)
      ]));
      /* full time */
      if (m.result) {
        var act = outcomeOfScore(m.result.s), pe = pOf(m, m.result.s), hitO = (m.pick.o || o) === act;
        main.appendChild(h('div', { class: 'card res' }, [
          h('h2', { class: 'ch', text: 'بعد صافرة النهاية' }),
          h('div', { class: 'res-row' }, [h('span', { text: 'النتيجة الفعلية' }), scorePill(m.result.s)]),
          h('div', { class: 'res-row' }, [h('span', { text: 'نتيجة المباراة (فوز/تعادل/خسارة)' }), h('b', { class: hitO ? 'hit' : 'miss', text: hitO ? '✓ أصاب' : '✗ لم يصب' })]),
          pe != null ? h('div', { class: 'res-row' }, [h('span', { text: 'كم أعطى النموذج لهذه النتيجة' }), ltr(pct(pe))]) : null,
          h('div', { class: 'res-row' }, [h('span', { text: 'RPS لهذه المباراة (الأقل أفضل)' }), ltr(rps(m.p, act).toFixed(3))])
        ]));
      }
      /* top scores */
      if (m.top.length) {
        var mx = m.top[0].p;
        main.appendChild(h('div', { class: 'card' }, [
          h('h2', { class: 'ch', text: 'أكثر 5 نتائج احتمالاً' }),
          h('ol', { class: 'tops' }, m.top.slice(0, 5).map(function (t) {
            return h('li', { class: m.result && m.result.s[0] === t.s[0] && m.result.s[1] === t.s[1] ? 'act' : '' }, [
              scorePill(t.s), h('span', { class: 'tbar' }, [h('i', { style: 'width:' + Math.max(4, t.p / mx * 100).toFixed(1) + '%' })]), ltr(pct(t.p))]);
          }))
        ]));
      }
      /* heat-map */
      var hm = heat(m);
      if (hm) main.appendChild(h('div', { class: 'card' }, [h('h2', { class: 'ch', text: 'خريطة النتائج' }), hm]));
      /* why */
      var why = [];
      /* our own Elo is shown only where it is part of the model (legs.elo_weight > 0); ClubElo is a separate comparison line added after the lock */
      var eloW = m.legs ? num(m.legs.elo_weight) : null;
      if (eloW !== null && eloW > 0 && m.elo && num(m.elo.home) !== null && num(m.elo.away) !== null) {
        why.push(h('div', { class: 'kv' }, [h('span', { text: 'تقييم Elo في نموذجنا' }), h('span', null, [
          m.home.ar + ' ', ltr(Math.round(m.elo.home)), ' | ', m.away.ar + ' ', ltr(Math.round(m.elo.away))]),
          h('small', { class: 'fine', text: 'تقييمنا الخاص يبدأ من 1500 لكل ناد، فالفرق بين الرقمين هو المهم. يدخل في حساب الأهداف المتوقعة بوزن ' + Math.round(eloW * 100) + '%.' })]));
      }
      if (m.elo && num(m.elo.clubelo_home) !== null && num(m.elo.clubelo_away) !== null) {
        why.push(h('div', { class: 'kv' }, [h('span', { text: 'للمقارنة فقط: ClubElo (أُضيف بعد القفل)' }), h('span', null, [
          m.home.ar + ' ', ltr(Math.round(m.elo.clubelo_home)), ' | ', m.away.ar + ' ', ltr(Math.round(m.elo.clubelo_away))]),
          h('small', { class: 'fine' }, ['لا يدخل في أي حساب. المصدر: ', h('a', { class: 'src n', dir: 'ltr', href: 'https://clubelo.com', rel: 'noopener', target: '_blank', text: 'clubelo.com' })])]));
      }
      var eg = m.xgoals || m.lam;
      if (eg) why.push(h('div', { class: 'kv' }, [h('span', { text: 'الأهداف المتوقعة' }), h('span', null, [m.home.ar + ' ', ltr(eg.h.toFixed(2)), ' | ', m.away.ar + ' ', ltr(eg.a.toFixed(2))])]));
      if (m.legs && m.legs.train_matches) {
        why.push(h('div', { class: 'kv' }, [h('span', { text: 'بيانات التدريب' }), h('span', null, [ltr(m.legs.train_matches), ' مباراة', validDate(new Date(m.cutoff)) ? ' حتى ' + F_DAY_UTC.format(new Date(new Date(m.cutoff).getTime() - 1)).replace(/،/g, '') : ''])]));
      }
      if (m.comp.key === 'ucl') {
        var uc = meta0 && meta0.backtest && meta0.backtest.champions_league_holdout_2025_26, un = uc && uc.n ? uc.n : null;
        why.push(h('p', { class: 'fine', text: 'تنبيه: اختبار النموذج على دوري أبطال أوروبا أصغر' + (un ? ' (' + un + ' مباراة فقط في موسم 2025-26)' : '') + ' وأكثر تذبذباً من الدوريات المحلية، فخذ هذه الأرقام بحذر أكبر.' }));
      }
      if (m.base && m.hasAdj) {
        var br = round3(m.base.p), ar2 = round3(m.p);
        var sens = m.raw && m.raw.sensitivity && m.raw.sensitivity.dc_only_base, sp3 = sens && readP(sens) ? round3(readP(sens)) : null;
        why.push(h('div', { class: 'cmp' }, [
          h('p', { class: 'fine', text: 'النموذج الأساسي (المُختبَر على موسم كامل) والنتيجة بعد تعديل الغيابات والفرص المتوقعة. المعدَّل هو المعتمد في السجل، والأساسي يُقيَّم بجانبه.' }),
          h('table', { class: 'tbl' }, [
            h('tr', null, [h('th'), h('th', { text: 'فوز ' + m.home.ar }), h('th', { text: 'تعادل' }), h('th', { text: 'فوز ' + m.away.ar })]),
            h('tr', null, [h('td', { text: 'الأساسي' }), h('td', null, ltr(br[0] + '%')), h('td', null, ltr(br[1] + '%')), h('td', null, ltr(br[2] + '%'))]),
            sp3 ? h('tr', { class: 'sens' }, [h('td', { text: 'الأساسي بدون Elo' }), h('td', null, ltr(sp3[0] + '%')), h('td', null, ltr(sp3[1] + '%')), h('td', null, ltr(sp3[2] + '%'))]) : null,
            h('tr', { class: 'em' }, [h('td', { text: 'المعدَّل' }), h('td', null, ltr(ar2[0] + '%')), h('td', null, ltr(ar2[1] + '%')), h('td', null, ltr(ar2[2] + '%'))])
          ]),
          sp3 ? h('p', { class: 'fine', text: 'صف «الأساسي بدون Elo» هو النموذج نفسه بعد إيقاف جزء Elo وإبقاء «ديكسون وكولز» وحده. الفرق بين الصفين يعني أن توقّع هذه المباراة حسّاس لهذا الاختيار.' }) : null
        ]));
      }
      var whyLines = m.why.map(function (w) { return typeof w === 'string' ? w : (w.ar || w.en || ''); }).filter(Boolean);
      if (!whyLines.length && m.adjustments.length) whyLines = m.adjustments.map(function (a) { return a.effect_ar || a.note_ar || a.effect || ''; }).filter(Boolean);
      if (m.adjLabel && whyLines.length > 1) why.push(h('h3', { class: 'sub-h', text: 'الغيابات والفرص المتوقعة' }), h('p', { class: 'fine heur', text: m.adjLabel.ar || '' }));
      if (whyLines.length) why.push(h('ul', { class: 'adj' }, whyLines.map(function (t) { return h('li', null, [h('span', { class: 'adj-n', text: t })]); })));
      else why.push(h('p', { class: 'fine', text: m.note || 'بدون تعديل الغيابات: هذه النتيجة من النموذج الأساسي فقط.' }));
      var srcs = {}, srcOrder = [];
      m.adjustments.forEach(function (a) {
        if (!a.source || !/^https?:/.test(a.source)) return;
        var k = a.source.split(' ')[0];
        if (!srcs[k]) { srcs[k] = { url: k, who: [], at: a.checked_at }; srcOrder.push(k); }
        var pn = a.player_ar || a.player;
        if (pn && srcs[k].who.indexOf(pn) < 0) srcs[k].who.push(pn);
      });
      if (srcOrder.length) {
        why.push(h('h3', { class: 'sub-h', text: 'المصادر' }), h('ul', { class: 'srcs' }, srcOrder.map(function (k) {
          var o2 = srcs[k], host = k.replace(/^https?:\/\/(www\.)?/, '').split('/')[0];
          return h('li', null, [h('a', { class: 'n', dir: 'ltr', href: k, rel: 'noopener', target: '_blank', text: host }), o2.who.length ? h('small', { class: 'src-who', text: 'عن: ' + o2.who.join('، ') }) : null]);
        })));
      }
      main.appendChild(h('div', { class: 'card' }, [h('h2', { class: 'ch', text: 'ليش؟' })].concat(why)));
      /* benchmark */
      var op = m.bench && m.bench.opta, opp = op && readP(op);
      var opNote = (m.bench && (m.bench.note_ar || (m.bench.opta && m.bench.opta.note_ar))) || '';
      if (!opp && opNote) {
        main.appendChild(h('div', { class: 'card' }, [h('h2', { class: 'ch', text: 'مقارنة مع أوبتا (Opta)' }), h('p', { class: 'fine', text: opNote })]));
      }
      if (opp) {
        var orr = round3(opp);
        main.appendChild(h('div', { class: 'card' }, [
          h('h2', { class: 'ch', text: 'مقارنة مع أوبتا (Opta)' }),
          h('table', { class: 'tbl' }, [
            h('tr', null, [h('th'), h('th', { text: 'فوز ' + m.home.ar }), h('th', { text: 'تعادل' }), h('th', { text: 'فوز ' + m.away.ar })]),
            h('tr', null, [h('td', { text: 'أوبتا' }), h('td', null, ltr(orr[0] + '%')), h('td', null, ltr(orr[1] + '%')), h('td', null, ltr(orr[2] + '%'))])
          ]),
          h('p', { class: 'fine' }, ['أرقام أوبتا أُضيفت بعد قفل توقّعنا ولم تؤثّر فيه. المصدر: ', op.url ? h('a', { class: 'src n', dir: 'ltr', href: op.url, rel: 'noopener', target: '_blank', text: op.source || 'Opta' }) : (op.source || 'Opta')]),
          op.note ? h('p', { class: 'fine', text: op.note }) : null
        ]));
      }
      main.appendChild(h('p', { class: 'raw' }, [h('a', { href: 'data/matches/' + encodeURIComponent(m.id) + '.json', target: '_blank', rel: 'noopener', text: 'عرض ملف البيانات الخام (JSON)' })]));
    });
  };

  PAGES.team = function (app) {
    var tid = new URLSearchParams(location.search).get('team') || '';
    var key = TD.normName(tid);
    return Promise.all([loadFeatured(), Promise.all(LEAGUES.map(function (l) { return loadLeague(l.key); })), tryJSON('record.json')]).then(function (r) {
      var seen = {}, all = [];
      r[0].concat([].concat.apply([], r[1].map(function (l) { return l.matches; }))).forEach(function (m) { if (!seen[m.id]) { seen[m.id] = 1; all.push(m); } });
      function isT(t) { return key ? (TD.normName(t.id) === key || TD.normName(t.en) === key) : (t.ar === tid.trim()); }
      var mine = all.filter(function (m) { return (isT(m.home) || isT(m.away)) && startState(m) !== 'over'; }).sort(function (a, b) { return a.ko - b.ko; });
      var past = listOf(r[2]).map(recEntry).filter(function (m) { return m && (isT(m.home) || isT(m.away)) && m.result; });
      clear(app);
      var main = h('div', { class: 'wrap' });
      if (!mine.length && !past.length) {
        app.appendChild(h('section', { class: 'pagehead' }, [h('div', { class: 'wrap' }, [h('h1', { text: 'الفريق غير موجود' }), h('p', { class: 'sub', text: 'لم نجد هذا الفريق في الدوريات الأربعة. جرّب من صفحة المباريات.' }), h('a', { class: 'more', href: 'league.html', text: 'كل المباريات' })])]));
        return;
      }
      var t = mine.length ? (isT(mine[0].home) ? mine[0].home : mine[0].away) : (isT(past[0].home) ? past[0].home : past[0].away);
      document.title = t.ar + ' | احتمالات';
      app.appendChild(h('section', { class: 'pagehead' }, [h('div', { class: 'wrap' }, [h('h1', null, [crest(t, 36), h('span', { text: t.ar })]), t.en !== t.ar ? h('p', { class: 'sub n', dir: 'ltr', text: t.en }) : null])]));
      app.appendChild(main);
      main.appendChild(section('المباراة القادمة', mine.length ? h('div', { class: 'fxlist' }, [legend(), fixtureRow(mine[0])]) : h('div', { class: 'empty', text: 'لا توجد مباراة قادمة في الأسبوعين القادمين.' })));
      if (mine.length > 1) main.appendChild(section('بعدها', fixtureList(mine.slice(1), { limit: 8, key: false })));
      if (past.length) main.appendChild(section('توقّعاتنا السابقة', h('div', { class: 'reclist' }, past.map(recRow))));
    });
  };

  function recRow(m) {
    var o = m.pick.o || (m.p ? outcomeOf(m.p) : null);
    return h('a', { class: 'rec' + (m.counts ? '' : ' dim'), href: 'match.html?id=' + encodeURIComponent(m.id) }, [
      h('div', { class: 'rec-top' }, [
        h('div', { class: 'rec-teams' }, [teamTag(m.home, { en: false }), teamTag(m.away, { en: false })]),
        m.result ? h('div', { class: 'rec-res' }, [scorePill(m.result.s), h('small', { text: 'النتيجة' })]) :
          h('div', { class: 'rec-res' }, [ltr(tKSA(m.ko)), h('small', { text: dayLabel(m.ko) })])
      ]),
      m.counts || m.result ? h('div', { class: 'rec-mid' }, [
        m.p && o ? h('span', null, ['النموذج: ', h('b', { text: outcomeLabel(o, m) }), ' ', ltr(pct(m.p[o === 'H' ? 'h' : (o === 'D' ? 'd' : 'a')]))]) : null,
        m.pick.s && m.counts ? h('span', null, ['أرجح نتيجة: ', scorePill(m.pick.s)]) : null
      ]) : null,
      h('div', { class: 'rec-foot' }, [
        m.result ? [h('span', { class: 'mark ' + (m.hitO ? 'ok' : 'no'), text: m.hitO ? '✓ نتيجة المباراة' : '✗ نتيجة المباراة' }),
          m.counts ? h('span', { class: 'mark ' + (m.hitS ? 'ok' : 'no'), text: m.hitS ? '✓ النتيجة الدقيقة' : '✗ النتيجة الدقيقة' }) : null] : null,
        m.result && m.counts && m.base ? h('span', { class: 'tag', text: 'الأساسي: ' + (m.bHitO ? '✓' : '✗') + ' نتيجة | ' + (m.bHitS ? '✓' : '✗') + ' دقيقة' }) : null,
        !m.result && m.counts ? h('span', { class: 'tag', text: 'بانتظار المباراة' }) : null,
        m.label ? h('span', { class: 'tag', text: m.label }) : null,
        m.lockedAt ? h('span', { class: 'rec-lock' }, ['🔒 ', ltr(utcStamp(m.lockedAt))]) : null
      ])
    ]);
  }

  PAGES.record = function (app) {
    return tryJSON('record.json').then(function (rec) {
      clear(app);
      var list = rec ? listOf(rec).map(recEntry).filter(Boolean) : [];
      var tally = list.filter(function (m) { return m.counts; }), tracked = list.filter(function (m) { return !m.counts; });
      var st = recStats(list), ts = trackedStats(list), total = (rec && rec.tally && rec.tally.featured_total) || tally.length;
      app.appendChild(h('section', { class: 'pagehead' }, [h('div', { class: 'wrap' }, [h('h1', { text: 'السجل العلني' }), h('p', { class: 'sub', text: 'كل توقّع قُفل قبل المباراة يظهر هنا مع نتيجته الفعلية. لا نحذف الأخطاء ولا نعدّل توقّعاً مقفلاً.' })])]));
      var main = h('div', { class: 'wrap' }); app.appendChild(main);
      main.appendChild(h('div', { class: 'stats' }, [
        stat(st.n + '/' + total, 'مباريات كبرى مُقيَّمة'),
        stat(st.n ? Math.round(st.ho / st.n * 100) + '%' : '–', 'نتيجة المباراة صحيحة', st.n ? st.ho + ' من ' + st.n : 'فوز / تعادل / خسارة'),
        stat(st.n ? st.hs + '/' + st.n : '–', 'نتيجة دقيقة'),
        stat(st.rps != null ? st.rps.toFixed(3) : '–', 'RPS (الأقل أفضل)')
      ]));
      if (st.n) main.appendChild(h('p', { class: 'fine base' }, ['النموذج الأساسي (قبل التعديل) بجانبه: ' + st.bho + ' من ' + st.n + ' نتيجة صحيحة، و' + st.bhs + ' من ' + st.n + ' دقيقة. ولو اخترنا «فوز صاحب الأرض» دائماً لأصبنا ' + st.homeAlways + ' من ' + st.n + '.']));
      main.appendChild(h('div', { class: 'note' }, [h('b', { text: 'كيف نحسب؟' }), ' يُحتسب هنا التوقّع المعدَّل للمباريات الكبرى المقفلة (النسخة الأولى فقط، ولا تحلّ نسخة لاحقة محلّها). ',
        st.n < 30 ? (st.n ? st.n + ' مباريات لا تثبت شيئاً لا لصالح النموذج ولا ضده، والدليل الحقيقي هو اختبار موسم 2025-26 ثم هذا السجل مع الوقت.' : 'لم تُلعب أي مباراة كبرى مُسجَّلة بعد، وستظهر النتائج بعد صافرة النهاية، الصحيح منها والخاطئ. ثلاث مباريات لا تثبت شيئاً، والدليل الحقيقي هو اختبار موسم 2025-26.') : '']));
      var pend = tally.filter(function (m) { return !m.result; }).sort(function (a, b) { return a.ko - b.ko; });
      var done = tally.filter(function (m) { return m.result; }).sort(function (a, b) { return b.ko - a.ko; });
      if (pend.length) main.appendChild(section('بانتظار المباراة (' + pend.length + ')', h('div', { class: 'reclist' }, pend.map(recRow))));
      if (done.length) main.appendChild(section('النتائج', h('div', { class: 'reclist' }, done.map(recRow))));
      if (tracked.length) {
        var box = h('div', { class: 'fxlist' }, [legend()]), shown = 0, btn;
        var sorted = tracked.slice().sort(function (a, b) { return (a.result ? 0 : 1) - (b.result ? 0 : 1) || (a.result ? b.ko - a.ko : a.ko - b.ko); });
        function more() { sorted.slice(shown, shown + 10).forEach(function (m) { box.appendChild(fixtureRow(m)); }); shown += 10; if (shown >= sorted.length && btn) btn.remove(); }
        btn = h('button', { class: 'more btn', type: 'button', onclick: more, text: 'عرض المزيد' });
        more();
        main.appendChild(section('باقي المباريات (' + tracked.length + ')', [
          h('p', { class: 'fine', text: ts.n ? 'تُتابَع للتوثيق: النموذج الأساسي، غير مقفلة بالبصمة وخارج الحصيلة الرئيسية. أصاب نتيجة المباراة في ' + ts.ho + ' من ' + ts.n + ' مباراة منتهية.' : 'تُتابَع للتوثيق: النموذج الأساسي لكل مباريات الدوريات الأربعة، غير مقفلة بالبصمة وخارج الحصيلة الرئيسية. تظهر نتائجها هنا بعد انتهائها.' }),
          box, shown < sorted.length ? btn : null]));
      }
      if (!list.length) main.appendChild(h('div', { class: 'empty', text: 'السجل فارغ حالياً.' }));
      var upd = rec && rec.updated_at ? updatedLine(rec.updated_at) : null; if (upd) main.appendChild(upd);
    });
  };
  function stat(v, l, sub) { return h('div', { class: 'stat' }, [h('b', null, ltr(v)), h('span', { text: l }), sub ? h('small', { text: sub }) : null]); }

  var BT_BLOCKS = [
    ['site_leagues_holdout_2025_26', 'الإنجليزي والإسباني والفرنسي، موسم 2025-26'],
    ['europe_holdout_2025_26', 'كل الدوريات الأوروبية الكبرى + دوري الأبطال، موسم 2025-26'],
    ['champions_league_holdout_2025_26', 'دوري أبطال أوروبا فقط، موسم 2025-26، عيّنة صغيرة'],
    ['saudi_holdout_2025_26', 'دوري روشن، موسم 2025-26'],
    ['europe_2026_27_to_date', 'أوروبا هذا الموسم حتى الآن، 2026-27'],
    ['saudi_2026_27_to_date', 'دوري روشن هذا الموسم حتى الآن، 2026-27']
  ];
  function ltrYears(text) {
    return String(text).split(/(\d{4}-\d{2})/).map(function (t, i) { return i % 2 ? ltr(t) : t; });
  }
  function pc0(x) { return x == null ? '–' : (x * 100).toFixed(0) + '%'; }
  function f3(x) { return x == null ? '–' : (+x).toFixed(3); }
  function btCard(title, b) {
    var ci = b.rps_diff_vs_base_rates_ci95;
    return h('div', { class: 'bt' }, [
      h('div', { class: 'bt-h' }, [h('b', null, ltrYears(title)), h('small', null, [ltr(b.n), ' مباراة'])]),
      h('div', { class: 'bt-g' }, [
        h('div', null, [h('b', null, ltr(pc0(b.wdl_accuracy))), h('span', { text: 'نتيجة المباراة صحيحة' }), h('small', null, ['«فوز صاحب الأرض دائماً»: ', ltr(pc0(b.home_win_always_accuracy))])]),
        h('div', null, [h('b', null, ltr(b.one_exact_score_in != null ? String(+(+b.one_exact_score_in).toFixed(1)) : '–')), h('span', { text: 'النتيجة الدقيقة تصيب مرة من كل' }), h('small', null, ['نسبة الإصابة ', ltr((b.headline_score_hit * 100).toFixed(1) + '%')])]),
        h('div', null, [h('b', null, ltr(f3(b.rps))), h('span', { text: 'RPS (الأقل أفضل)' }), h('small', null, ['تكرار نتائج الدوري: ', ltr(f3(b.rps_base_rates))]), h('small', null, ['Elo وحده: ', ltr(f3(b.rps_elo_only))])]),
        h('div', null, [h('b', null, ltr(f3(b.log_loss))), h('span', { text: 'Log loss (الأقل أفضل)' }), h('small', null, ['تكرار نتائج الدوري: ', ltr(f3(b.log_loss_base_rates))])])
      ]),
      ci ? h('p', { class: 'fine', text: ci[2] < 0 ? 'أفضل من تكرار نتائج الدوري بفارق حقيقي وليس صدفة (95% ثقة).' : (ci[1] > 0 ? 'أسوأ من تكرار نتائج الدوري بفارق حقيقي (95% ثقة).' : 'الفرق عن تكرار نتائج الدوري ضمن هامش الخطأ في هذه العيّنة.') }) : null
    ]);
  }

  PAGES.method = function (app) {
    return Promise.all([tryJSON('meta.json'), tryJSON('locks.json'), loadFeatured().catch(function () { return []; })]).then(function (rr) {
      var meta = rr[0], locks = rr[1], names = {};
      rr[2].forEach(function (f) { names[f.id] = f.home.ar + ' ضد ' + f.away.ar; });
      clear(app);
      app.appendChild(h('section', { class: 'pagehead' }, [h('div', { class: 'wrap' }, [h('h1', { text: 'كيف يعمل النموذج؟' }), h('p', { class: 'sub', text: 'شرح بسيط وصريح، بما في ذلك حدود النموذج.' })])]));
      var main = h('div', { class: 'wrap prose' }); app.appendChild(main);
      function block(title, kids) { main.appendChild(h('section', { class: 'card pr' }, [h('h2', { class: 'ch', text: title })].concat(kids))); }
      block('ما هذا؟', [h('p', { text: 'نموذج تعلّم آلي يقدّر احتمال فوز كل فريق أو التعادل في كل مباراة، وأرجح نتيجة. هو لا يعرف الغيب: يقول «هذا الأرجح» مع نسبة، وليس «هذا ما سيحدث». الهدف التعليم والترفيه.' })]);
      block('الخطوات الأربع', [h('ol', { class: 'steps' }, [
        h('li', null, [h('b', { text: 'البيانات. ' }), 'آلاف النتائج السابقة من الدوريات الأوروبية الكبرى ودوري أبطال أوروبا ودوري روشن. المباريات الأحدث تزن أكثر من القديمة.']),
        h('li', null, [h('b', { text: 'قوة كل فريق. ' }), 'نموذج «ديكسون وكولز» يقدّر هجوم ودفاع كل فريق ومزيّة اللعب على أرضه. في دوري روشن ودوري أبطال أوروبا نمزج معه تقييم Elo بوزن 70%، لأن المزج حسّن الأرقام في موسم الضبط 2024-25. عيّنة دوري الأبطال صغيرة، ولم يتفوّق المزج هناك على «ديكسون وكولز» وحده في اختبار 2025-26 ولا هذا الموسم. أما الدوريات الإنجليزي والإسباني والفرنسي فلا تستخدم Elo.']),
        h('li', null, [h('b', { text: 'الأهداف المتوقعة. ' }), 'من القوتين نحسب متوسط أهداف كل فريق في هذه المباراة تحديداً.']),
        h('li', null, [h('b', { text: 'شبكة النتائج. ' }), 'نحسب احتمال كل نتيجة ممكنة، ونجمعها لنحصل على فوز/تعادل/خسارة، ثم نختار النتيجة الأرجح، وأرجح نتيجة دقيقة داخلها.'])
      ])]);
      block('التعديلات في المباريات الكبرى فقط', [
        h('p', { text: 'في المباريات الكبرى الثلاث نضيف تعديلاً صغيراً ومحدوداً للغيابات المؤكدة (إيقاف، إصابة) وللفرص المتوقعة (xG). كل تعديل مكتوب مع مصدره في صفحة المباراة تحت «ليش؟».' }),
        h('p', { text: 'هذه التعديلات لم تُختبر على المواسم الماضية، لذلك نعرض النموذج الأساسي (المُختبَر) بجانب المعدَّل. المعدَّل هو الذي يُحتسب في السجل، والأساسي يُقيَّم بجانبه. باقي المباريات بدون أي تعديل.' })]);
      var bt = meta && meta.backtest, cards = [];
      if (bt) BT_BLOCKS.forEach(function (d) { if (bt[d[0]]) cards.push(btCard(d[1], bt[d[0]])); });
      if (cards.length) {
        block('كم هو دقيق فعلاً؟', [
          h('p', { text: 'اختُبر النموذج على موسم 2025-26 كاملاً دون أن يراه أثناء ضبطه. يُعاد تدريبه أسبوعياً بالبيانات السابقة لكل مباراة فقط، فلا يوجد تسريب من المستقبل. وضُبطت إعداداته على موسم 2024-25.' }),
          h('div', { class: 'bts' }, cards),
          h('p', { class: 'fine', text: 'RPS وLog loss: مقياسان لجودة الاحتمالات، وكلما قلّ الرقم كان أفضل. «تكرار نتائج الدوري» أن نعطي كل مباراة نفس النسب العامة بلا أي نموذج. تقييم Elo وحده قريب جداً من نموذجنا، والفرق بينهما ضمن هامش الخطأ.' })
        ]);
      } else {
        block('كم هو دقيق فعلاً؟', [h('p', { text: 'المتوقع لنماذج من هذا النوع: يصيب نتيجة المباراة (فوز/تعادل/خسارة) في نحو 50% إلى 55% من المباريات، والنتيجة الدقيقة تصيب تقريباً مرة من كل 9. ستُنشر أرقام اختبارنا الفعلية هنا.' })]);
      }
      block('حدود النموذج', [h('ul', { class: 'bul' }, [
        h('li', { text: 'كرة القدم عشوائية: نحو نصف النتائج يخالف الأرجح حتى في أفضل النماذج.' }),
        h('li', { text: 'النتيجة الدقيقة نادراً ما تصيب: تقريباً مرة من كل 9 إلى 10.' }),
        h('li', { text: 'ثلاث مباريات أو عشر لا تثبت شيئاً. لذلك نعرض اختبار موسم كامل والسجل العلني.' }),
        h('li', { text: 'لا يعرف النموذج الأخبار الأخيرة ولا التشكيلة النهائية ولا الحالة النفسية، إلا ما أدخلناه يدوياً في المباريات الكبرى.' })])]);
      var lockKids = [h('p', { text: 'كل توقّع في المباريات الكبرى يُحفظ ويُختم ببصمة رقمية (SHA-256) قبل صافرة البداية. أي تصحيح بعد ذلك يظهر كنسخة جديدة معلَّمة، ولا يُستبدل الأصل، والأخطاء تبقى في السجل. أرقام أوبتا ومقارنة ClubElo تُضاف بعد القفل ولا تدخل في البصمة.' })];
      if (locks && locks.matches && locks.matches.length) {
        lockKids.push(h('ul', { class: 'locks' }, locks.matches.map(function (l) {
          return h('li', null, [h('a', { href: 'match.html?id=' + encodeURIComponent(l.match_id), class: 'lk-m' }, names[l.match_id] || l.match_id),
            h('span', { class: 'lk-t' }, ['🔒 ', ltr(utcStamp(l.locked_at_utc || locks.locked_at_utc))]), h('bdi', { class: 'sha n', dir: 'ltr', title: l.sha256 }, 'sha256 ' + String(l.sha256).slice(0, 16))]);
        })));
        lockKids.push(h('p', { class: 'fine', text: 'في صفحة كل مباراة كبرى زر «تحقق من البصمة» يعيد الحساب داخل متصفحك.' }));
        if (locks.relock_history && locks.relock_history.length) {
          lockKids.push(h('p', { class: 'fine' }, ['شفافية: قُفلت هذه التوقّعات أول مرة قبل النشر بحدّ أخطأنا فيه لاعتبار اللاعب «أساسياً» (45% من الدقائق بدل 50% في خطتنا). صُحّح الحدّ وأُعيد القفل قبل نشر أي شيء، والبصمات القديمة محفوظة في ', h('a', { class: 'src n', dir: 'ltr', href: 'data/locks.json', target: '_blank', rel: 'noopener', text: 'locks.json' }), '.']));
        }
      }
      block('قفل التوقّعات', lockKids);
      var src = (meta && meta.sources && meta.sources.length) ? meta.sources : [
        { name: 'openfootball', credit: 'openfootball (github.com/openfootball)', url: 'https://github.com/openfootball', licence: 'public domain (CC0)' },
        { name: 'ESPN', credit: 'ESPN', url: 'https://www.espn.com' },
        { name: 'ClubElo', credit: 'Elo: clubelo.com', url: 'https://clubelo.com' }];
      block('البيانات والشكر', [h('ul', { class: 'bul' }, src.map(function (x) {
        return h('li', null, [h('a', { class: 'n', dir: 'ltr', href: x.url || '#', rel: 'noopener', target: '_blank', text: x.credit || x.name }), x.licence ? h('small', { class: 'lic', text: x.licence }) : null]);
      })), h('p', { class: 'fine' }, ['شعارات الأندية علامات تجارية لأصحابها — للتعريف فقط (الصور من ESPN). الأعلام من مشروع ', h('a', { class: 'src n', dir: 'ltr', href: 'https://github.com/lipis/flag-icons', rel: 'noopener', target: '_blank', text: 'flag-icons' }), ' برخصة MIT. لا نستخدم شعارات الدوريات ولا صور اللاعبين.']),
        meta && meta.generated_at ? updatedLine(meta.generated_at) : null]);
      block('تنبيه', [h('p', { text: 'تنبؤات إحصائية للتسلية والتعلّم — ليست نصيحة مراهنة. لا نعرض أي مقابل مالي ولا نقبل رعاة.' })]);
    });
  };
  /* ---------- boot ---------- */
  function boot() {
    var page = document.body.getAttribute('data-page'), app = $('#app');
    shell(page);
    var run = PAGES[page];
    if (!run) return;
    Promise.resolve().then(function () { return run(app); }).catch(function (e) { if (window.console) console.error(e); fail(app); });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
