(async function () {
  const $ = (id) => document.getElementById(id);
  const TOP = 30;

  let cfg = { quoteProxy: '', pollSeconds: 15 };
  try { cfg = { ...cfg, ...(await (await fetch('config.json', { cache: 'no-cache' })).json()) }; } catch (e) { /* 沿用預設 */ }

  let base;
  try {
    base = await (await fetch('data/hot.json', { cache: 'no-cache' })).json();
  } catch (e) {
    $('hot-status').textContent = '尚無成交重心股資料';
    return;
  }

  // ---------- helpers
  const num = (v) => { const n = parseFloat(String(v ?? '').replace(/,/g, '')); return Number.isFinite(n) && n > 0 ? n : null; };
  const first = (s) => { for (const x of String(s || '').split('_')) { const n = num(x); if (n) return n; } return null; };   // 跳過漲跌停鎖死時的市價委託 0
  const fmt = (n, d = 2) => n == null ? '—' : n.toLocaleString('zh-TW', { minimumFractionDigits: d, maximumFractionDigits: d });
  const sgn = (n, d = 2) => n == null ? '—' : (n > 0 ? '+' : n < 0 ? '−' : '') + fmt(Math.abs(n), d);
  const cls = (n) => n > 0 ? 'up' : n < 0 ? 'down' : '';
  const fmtPx = (p) => p == null ? '—' : p >= 1000 ? fmt(p, 0) : p >= 100 ? fmt(p, 1) : fmt(p, 2);
  const yi = (v) => v / 1e8;
  const tpe = () => {
    const d = new Date(Date.now() + 8 * 3600e3);
    return { dow: d.getUTCDay(), mins: d.getUTCHours() * 60 + d.getUTCMinutes(), ymd: d.toISOString().slice(0, 10) };
  };
  const liveWindow = () => { const t = tpe(); return t.dow >= 1 && t.dow <= 5 && t.mins >= 540 && base.date < t.ymd; };
  const inSession = () => { const t = tpe(); return t.mins >= 540 && t.mins <= 13 * 60 + 30; };

  const closeState = () => ({ mode: 'close', date: base.date, items: base.top });
  // 比較基準：盤中 → 最新盤後資料（即昨日）前 30 名；盤後 → 前一交易日前 30 名
  const prevSet = (mode) => new Set(mode === 'live' ? base.top.map((i) => i.c) : (base.prev || []));

  // ---------- 盤中即時
  const lastPx = {};
  let lastLive = null, busy = false, oldProxy = false;
  async function poll() {
    if (busy || !cfg.quoteProxy || document.hidden || !liveWindow()) return;
    if (!$('tab-hot').classList.contains('active') && lastLive) return;
    busy = true;
    try {
      const tse = base.pool.filter((p) => p.m === 'tse').map((p) => p.c).join(',');
      const otc = base.pool.filter((p) => p.m === 'otc').map((p) => p.c).join(',');
      const r = await fetch(`${cfg.quoteProxy.replace(/\/$/, '')}/?codes=${tse}&otc=${otc}`, { cache: 'no-store' });
      const j = await r.json();
      if (j.error) throw new Error(j.error);
      oldProxy = !j.ver;
      const ix = j.quotes.find((x) => x.c === 't00');
      if (!ix || ix.d !== tpe().ymd.replace(/-/g, '')) {
        render(closeState(), '今日休市 · 顯示 ' + base.date + ' 收盤');
        return;
      }
      const items = j.quotes.filter((x) => x.c !== 't00').map((x) => {
        const key = (x.ex || 'tse') + x.c;
        const y = num(x.y);
        const z = num(x.z);
        if (z) lastPx[key] = z;
        const p = z ?? lastPx[key] ?? first(x.b) ?? first(x.a) ?? y;
        const h = num(x.h) ?? p, l = num(x.l) ?? p;
        const v = num(x.v) ?? 0;                           // 累積成交量（張）
        const tv = p ? v * 1000 * (h + l + p) / 3 : 0;      // 估算成交值（元）
        return { c: x.c, n: x.n, m: x.ex === 'otc' ? 'otc' : 'tse', p, pct: y && p ? (p / y - 1) * 100 : null, v, tv };
      }).filter((i) => i.tv > 0);
      items.sort((a, b) => b.tv - a.tv);
      lastLive = { mode: 'live', time: ix.t, items: items.slice(0, TOP) };
      render(lastLive);
    } catch (e) {
      $('hot-time').textContent = '即時報價暫時無法取得（' + e.message + '），稍後自動重試';
    } finally {
      busy = false;
    }
  }

  // ---------- render
  function render(s, label) {
    const items = s.items;
    const prev = prevSet(s.mode);
    const isNew = (i) => prev.size > 0 && !prev.has(i.c);
    const sum = items.reduce((a, i) => a + i.tv, 0);
    const up = items.filter((i) => i.pct > 0).length, dn = items.filter((i) => i.pct < 0).length;
    const tseN = items.filter((i) => i.m === 'tse').length;

    const st = $('hot-status');
    if (s.mode === 'live') {
      st.className = 'pill live';
      st.innerHTML = inSession() ? '<span class="dot"></span>盤中即時' : '今日收盤（即時報價）';
      $('hot-time').textContent = `報價時間 ${s.time} · 每 ${cfg.pollSeconds} 秒更新`
        + (oldProxy ? ' · ⚠ 中繼服務為舊版，目前只排名上市股票（請更新 Worker 程式碼）' : '');
    } else {
      st.className = 'pill';
      st.textContent = label || `盤後 · ${s.date}`;
      const t = tpe();
      $('hot-time').textContent = (!cfg.quoteProxy && t.dow >= 1 && t.dow <= 5 && inSession())
        ? '尚未設定即時報價來源，目前顯示上一交易日收盤結果' : '';
    }

    $('hot-sum').textContent = fmt(yi(sum), 0) + ' 億';
    $('hot-sumsub').textContent = s.mode === 'live' ? '盤中估算' : '官方成交金額';
    $('hot-ud').innerHTML = `<span class="up">${up}</span> / <span class="down">${dn}</span> / ${items.length - up - dn}`;
    $('hot-mk').textContent = `${tseN} / ${items.length - tseN}`;
    const newN = items.filter(isNew).length;
    $('hot-sumsub').textContent += ` · ★ 新上榜 ${newN} 檔`;
    if (items[0]) {
      $('hot-first').textContent = items[0].n;
      $('hot-firstsub').innerHTML = `${fmt(yi(items[0].tv), 0)} 億 · <span class="${cls(items[0].pct)}">${sgn(items[0].pct)}%</span>`;
    }

    $('hot-list').innerHTML = items.map((i, k) => `<li class="hot-row${isNew(i) ? ' new' : ''}">
      <span class="rk">${k + 1}</span>
      <span class="nm"><b>${isNew(i) ? '<span class="star" title="今日新上榜">★</span>' : ''}<span class="txt">${i.n}</span></b><em>${i.c}<i class="mk ${i.m}">${i.m === 'tse' ? '市' : '櫃'}</i></em></span>
      <span class="r mono ${cls(i.pct)}">${fmtPx(i.p)}</span>
      <span class="r mono ${cls(i.pct)}">${sgn(i.pct)}%</span>
      <span class="r mono b">${fmt(yi(i.tv), 1)}</span>
      <span class="r mono hide-sm">${fmt(i.v, 0)}</span>
    </li>`).join('');
  }

  document.querySelector('.tab[data-tab="hot"]').addEventListener('click', () => poll());
  document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });

  render(closeState());
  poll();
  setInterval(poll, Math.max(5, cfg.pollSeconds) * 1000);
})();
