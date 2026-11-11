(async function () {
  const $ = (id) => document.getElementById(id);
  const SHOW = 20;
  const expanded = { pos: false, neg: false };

  let cfg = { quoteProxy: '', pollSeconds: 15 };
  try { cfg = { ...cfg, ...(await (await fetch('config.json', { cache: 'no-cache' })).json()) }; } catch (e) { /* 沿用預設 */ }

  let base;
  try {
    base = await (await fetch('data/contribution.json', { cache: 'no-cache' })).json();
  } catch (e) {
    $('ct-status').textContent = '尚無貢獻點數資料';
    return;
  }

  // ---------- helpers
  const num = (v) => { const n = parseFloat(String(v ?? '').replace(/,/g, '')); return Number.isFinite(n) && n > 0 ? n : null; };
  const first = (s) => num(String(s || '').split('_')[0]);
  const fmt = (n, d = 2) => n == null ? '—' : n.toLocaleString('zh-TW', { minimumFractionDigits: d, maximumFractionDigits: d });
  const sgn = (n, d = 2) => n == null ? '—' : (n > 0 ? '+' : n < 0 ? '−' : '') + fmt(Math.abs(n), d);
  const cls = (n) => n > 0 ? 'up' : n < 0 ? 'down' : '';
  const fmtPx = (p) => p >= 1000 ? fmt(p, 0) : p >= 100 ? fmt(p, 1) : fmt(p, 2);
  const tpe = () => {
    const d = new Date(Date.now() + 8 * 3600e3);
    return { dow: d.getUTCDay(), mins: d.getUTCHours() * 60 + d.getUTCMinutes(), ymd: d.toISOString().slice(0, 10) };
  };
  // 盤中即時：週一～五 9:00 後，且盤後資料尚未更新為今日
  const liveWindow = () => { const t = tpe(); return t.dow >= 1 && t.dow <= 5 && t.mins >= 540 && base.date < t.ymd; };
  const inSession = () => { const t = tpe(); return t.mins >= 540 && t.mins <= 13 * 60 + 30; };

  // ---------- 盤後狀態
  function closeState() {
    return {
      mode: 'close', date: base.date, idx: base.index_close, idxChg: base.index_chg,
      items: base.items.map((i) => ({ ...i, pct: i.ref ? (i.chg / i.ref) * 100 : 0 })),
    };
  }

  // ---------- 盤中即時
  const lastPx = {};
  let lastLive = null, busy = false;
  async function poll() {
    if (busy || !cfg.quoteProxy || document.hidden || !liveWindow()) return;
    if (!$('tab-contrib').classList.contains('active') && lastLive) return;
    busy = true;
    try {
      const codes = base.items.map((i) => i.c).join(',');
      const r = await fetch(cfg.quoteProxy.replace(/\/$/, '') + '/?codes=' + codes, { cache: 'no-store' });
      const j = await r.json();
      if (j.error) throw new Error(j.error);
      const q = new Map(j.quotes.map((x) => [x.c, x]));
      const ix = q.get('t00');
      if (!ix || ix.d !== tpe().ymd.replace(/-/g, '')) { // 今日休市
        render(closeState(), '今日休市 · 顯示 ' + base.date + ' 收盤');
        return;
      }
      const items = base.items.map((i) => {
        const x = q.get(i.c);
        if (!x) return { ...i, pct: 0, chg: 0, pts: 0 };
        const y = num(x.y) ?? i.p;
        const z = num(x.z);
        if (z) lastPx[i.c] = z;
        const p = z ?? lastPx[i.c] ?? first(x.b) ?? first(x.a) ?? y;
        const chg = p - y;
        return { c: i.c, n: x.n || i.n, s: i.s, ref: y, p, chg, pct: (chg / y) * 100, pts: chg * i.s / base.divisor_next };
      });
      const idxNow = num(ix.z) ?? lastPx.t00 ?? num(ix.y);
      if (num(ix.z)) lastPx.t00 = num(ix.z);
      lastLive = { mode: 'live', time: ix.t, idx: idxNow, idxChg: idxNow - num(ix.y), items };
      render(lastLive);
    } catch (e) {
      $('ct-time').textContent = '即時報價暫時無法取得（' + e.message + '），稍後自動重試';
    } finally {
      busy = false;
    }
  }

  // ---------- render
  function row(i, rank, max) {
    const w = Math.max(1.5, (Math.abs(i.pts) / max) * 100);
    return `<li>
      <span class="rk">${rank}</span>
      <span class="nm"><b>${i.n}</b><em>${i.c}</em></span>
      <span class="px">${fmtPx(i.p)}<i class="${cls(i.chg)}">${sgn(i.pct)}%</i></span>
      <span class="bar ${cls(i.pts)}"><span style="width:${w}%"></span></span>
      <span class="pt ${cls(i.pts)}">${sgn(i.pts)}</span>
    </li>`;
  }
  function list(key, arr, max) {
    const ol = $('ct-' + key), btn = $('ct-' + key + '-more');
    const shown = expanded[key] ? arr : arr.slice(0, SHOW);
    ol.innerHTML = shown.length ? shown.map((i, k) => row(i, k + 1, max)).join('') : '<li class="none">無</li>';
    const rest = arr.length - SHOW;
    btn.hidden = rest <= 0;
    btn.textContent = expanded[key] ? '收合' : `展開其餘 ${rest} 檔`;
  }
  let current = null;
  function render(s, label) {
    current = s;
    const pos = s.items.filter((i) => i.pts > 0.0005).sort((a, b) => b.pts - a.pts);
    const neg = s.items.filter((i) => i.pts < -0.0005).sort((a, b) => a.pts - b.pts);
    const flat = s.items.length - pos.length - neg.length;
    const sumTop = s.items.reduce((a, i) => a + i.pts, 0);
    const max = Math.max(...s.items.map((i) => Math.abs(i.pts)), 1e-9);

    const st = $('ct-status');
    if (s.mode === 'live') {
      const open = inSession();
      st.className = 'pill live';
      st.innerHTML = open ? '<span class="dot"></span>盤中即時' : '今日收盤（即時報價）';
      $('ct-time').textContent = `報價時間 ${s.time} · 每 ${cfg.pollSeconds} 秒更新`;
    } else {
      st.className = 'pill';
      st.textContent = label || `盤後 · ${s.date}`;
      const t = tpe();
      $('ct-time').textContent = (!cfg.quoteProxy && t.dow >= 1 && t.dow <= 5 && inSession())
        ? '尚未設定即時報價來源，目前顯示上一交易日收盤結果' : '';
    }

    $('ct-idx').textContent = fmt(s.idx);
    $('ct-idx').className = 'v ' + cls(s.idxChg);
    $('ct-idxchg').textContent = `${sgn(s.idxChg)} 點`;
    $('ct-idxchg').className = 'd ' + cls(s.idxChg);
    $('ct-top').textContent = sgn(sumTop) + ' 點';
    $('ct-top').className = 'v ' + cls(sumTop);
    $('ct-topsub').textContent = `正貢獻 ${pos.length} · 負貢獻 ${neg.length} · 平盤 ${flat}`;
    const other = s.idxChg - sumTop;
    $('ct-other').textContent = sgn(other) + ' 點';
    $('ct-other').className = 'v ' + cls(other);
    const big = [...s.items].sort((a, b) => Math.abs(b.pts) - Math.abs(a.pts))[0];
    if (big) {
      $('ct-max').textContent = big.n;
      $('ct-maxsub').innerHTML = `<span class="${cls(big.pts)}">${sgn(big.pts)} 點</span> · 占大盤 ${s.idxChg ? fmt(big.pts / s.idxChg * 100, 0) : '—'}%`;
    }
    $('ct-pos-sum').textContent = sgn(pos.reduce((a, i) => a + i.pts, 0)) + ' 點';
    $('ct-neg-sum').textContent = sgn(neg.reduce((a, i) => a + i.pts, 0)) + ' 點';
    list('pos', pos, max);
    list('neg', neg, max);
  }

  ['pos', 'neg'].forEach((k) => $('ct-' + k + '-more').addEventListener('click', () => {
    expanded[k] = !expanded[k];
    if (current) render(current);
  }));
  document.querySelector('.tab[data-tab="contrib"]').addEventListener('click', () => poll());
  document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });

  render(closeState());
  poll();
  setInterval(poll, Math.max(5, cfg.pollSeconds) * 1000);
})();
