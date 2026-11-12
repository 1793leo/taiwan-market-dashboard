(async function () {
  const $ = (id) => document.getElementById(id);
  const fmt = (n, d = 2) => n == null || Number.isNaN(n) ? '—' : n.toLocaleString('zh-TW', { minimumFractionDigits: d, maximumFractionDigits: d });
  const sgn = (n, d = 2) => n == null || Number.isNaN(n) ? '—' : (n > 0 ? '+' : n < 0 ? '−' : '') + fmt(Math.abs(n), d);
  const cls = (n) => n > 0 ? 'up' : n < 0 ? 'down' : '';
  const num = (v) => { const n = parseFloat(String(v ?? '').replace(/,/g, '')); return Number.isFinite(n) && n > 0 ? n : null; };
  const first = (s) => num(String(s || '').split('_')[0]);
  const tpe = () => {
    const d = new Date(Date.now() + 8 * 3600e3);
    return { dow: d.getUTCDay(), mins: d.getUTCHours() * 60 + d.getUTCMinutes(), ymd: d.toISOString().slice(0, 10) };
  };

  let cfg = { quoteProxy: '' };
  try { cfg = { ...cfg, ...(await (await fetch('config.json', { cache: 'no-cache' })).json()) }; } catch (e) { /* 無設定 */ }
  let D;
  try { D = await (await fetch('data/cb.json', { cache: 'no-cache' })).json(); }
  catch (e) { $('cb-status').textContent = '尚無可轉債資料'; return; }

  // ---------- 突破轉換價
  function renderBreak(list, mode, label, sub) {
    const st = $('cb-status');
    st.className = 'pill' + (mode === 'live' ? ' live' : '');
    st.innerHTML = label;
    $('cb-time').textContent = sub || '';
    $('cb-pxh').textContent = mode === 'live' ? '現價' : '收盤';
    list.sort((a, b) => (b.p / b.conv) - (a.p / a.conv));
    $('cb-brk').innerHTML = list.length ? list.map((r) => {
      const pct = (r.p / r.prev - 1) * 100, over = (r.p / r.conv - 1) * 100;
      return `<tr>
        <td><b>${r.n}</b><em class="sub">${r.c}</em></td>
        <td><b>${r.sn}</b><em class="sub">${r.s}${r.m === 'otc' ? ' · 櫃' : ''}</em></td>
        <td class="r mono">${fmt(r.conv)}</td><td class="r mono hide-sm">${fmt(r.prev)}</td>
        <td class="r mono b ${cls(pct)}">${fmt(r.p)}</td><td class="r mono hide-sm ${cls(pct)}">${sgn(pct)}%</td>
        <td class="r mono up">+${fmt(over)}%</td>
        <td class="r mono hide-sm">${fmt(100 * r.p / r.conv)}</td><td class="r mono hide-sm">${fmt(r.cb)}</td>
      </tr>`;
    }).join('') : `<tr><td colspan="9" class="none">${mode === 'live' ? '目前沒有今日突破轉換價的標的' : '當日沒有突破轉換價的標的'}</td></tr>`;
  }
  renderBreak([...D.breakout], 'close', `盤後 · ${D.date}`);

  // ---------- 成交量前 30（盤後靜態；10:00 起盤中每 10 分鐘即時排行）
  function renderTop(list, label, live) {
    const q = $('cb-qdate');
    q.className = 'pill' + (live ? ' live' : '');
    q.innerHTML = label;
    $('cb-top').innerHTML = list.map((r, k) => `<tr>
      <td class="muted mono">${k + 1}</td>
      <td><b>${r.n}</b><em class="sub">${r.c}</em></td>
      <td class="r mono b ${cls(r.chg)}">${fmt(r.p)}</td><td class="r mono hide-sm ${cls(r.chg)}">${sgn(r.chg)}</td>
      <td class="r mono b">${fmt(r.v, 0)}</td><td class="r mono hide-sm">${fmt(r.amt / 1e4, 0)}</td>
      <td class="r mono hide-sm">${fmt(r.sp)}</td><td class="r mono hide-sm">${fmt(r.conv)}</td>
      <td class="r mono">${fmt(r.parity)}</td><td class="r mono ${cls(r.prem)}">${r.prem == null ? '—' : sgn(r.prem) + '%'}</td>
    </tr>`).join('') || '<tr><td colspan="10" class="none">目前沒有資料</td></tr>';
  }
  renderTop(D.top, `盤後 · ${D.qdate}`);

  let topLast = 0, topBusy = false, topDone = false;
  const topWindow = () => { const t = tpe(); return t.dow >= 1 && t.dow <= 5 && t.mins >= 600 && D.qdate < t.ymd; };
  async function pollTop(force) {
    if (topBusy || topDone || !cfg.quoteProxy || !topWindow() || !(D.all || []).length) return;
    if (!force && (document.hidden || Date.now() - topLast < 10 * 60 * 1000 - 5000)) return;
    topBusy = true;
    try {
      const proxy = cfg.quoteProxy.replace(/\/$/, '');
      const codes = D.all.map((x) => x[0]);
      const calls = [];
      for (let i = 0; i < codes.length; i += 280) calls.push(`${proxy}/?otc=${codes.slice(i, i + 280).join(',')}`);
      const res = await Promise.all(calls.map((u) => fetch(u, { cache: 'no-store' }).then((r) => r.json())));
      if (res.some((j) => !j.ver || j.ver < 4)) throw new Error('中繼服務需更新為最新版 Worker 才能查可轉債');
      const q = new Map(); let ix = null;
      res.forEach((j) => { if (j.error) throw new Error(j.error); j.quotes.forEach((x) => { if (x.c === 't00') ix = x; else q.set(x.c, x); }); });
      const t = tpe();
      if (!ix || ix.d !== t.ymd.replace(/-/g, '')) { topDone = true; return; }
      const info = new Map(D.all.map((x) => [x[0], x]));
      let list = [];
      for (const [c, x] of q) {
        const v = num(x.v); if (!v) continue;
        const y = num(x.y), b = first(x.b), a = first(x.a);
        const p = num(x.z) ?? (b && a ? (b + a) / 2 : b ?? a) ?? y;
        const h = num(x.h) ?? p, l = num(x.l) ?? p;
        const [, n, conv, s, m] = info.get(c) || [c, x.n, null, null, null];
        list.push({ c, n: n || x.n, p, chg: y && p ? p - y : null, v, amt: v * 1000 * (h + l + p) / 3, s, m, conv });
      }
      list.sort((a, b) => b.v - a.v);
      list = list.slice(0, 30);
      // 標的即時股價 → 轉換價值、溢價率
      const tse = list.filter((r) => r.m === 'tse').map((r) => r.s), otc = list.filter((r) => r.m === 'otc').map((r) => r.s);
      if (tse.length || otc.length) {
        const sj = await (await fetch(`${proxy}/?codes=${tse.join(',')}&otc=${otc.join(',')}`, { cache: 'no-store' })).json();
        const sq = new Map((sj.quotes || []).map((x) => [x.c, x]));
        for (const r of list) {
          const x = r.m && sq.get(r.s); if (!x) continue;
          const b = first(x.b), a = first(x.a);
          r.sp = num(x.z) ?? (b && a ? (b + a) / 2 : b ?? a) ?? num(x.y);
          if (r.sp && r.conv) { r.parity = 100 * r.sp / r.conv; r.prem = (r.p / r.parity - 1) * 100; }
        }
      }
      topLast = Date.now();
      const after = t.mins > 13 * 60 + 30;
      if (after && ix.t >= '13:30') topDone = true;
      renderTop(list, (after ? '今日收盤（即時報價）' : '<span class="dot"></span>盤中即時') + ` · ${ix.t}`, true);
    } catch (e) {
      $('cb-qdate').textContent = `盤後 · ${D.qdate}（即時排行暫時無法取得：${e.message}）`;
      topLast = Date.now();
    } finally {
      topBusy = false;
    }
  }
  pollTop(true);
  setInterval(() => pollTop(false), 30 * 1000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) pollTop(false); });

  // ---------- 盤中即時（每 10 分鐘）
  const LIVE_MS = 10 * 60 * 1000;
  let lastPoll = 0, busy = false, done = false;
  const liveWindow = () => { const t = tpe(); return t.dow >= 1 && t.dow <= 5 && t.mins >= 540 && D.date < t.ymd; };
  async function poll(force) {
    if (busy || done || !cfg.quoteProxy || !liveWindow() || !D.watch.length) return;
    if (!force && (document.hidden || Date.now() - lastPoll < LIVE_MS - 5000)) return;
    busy = true;
    try {
      const proxy = cfg.quoteProxy.replace(/\/$/, '');
      const tse = [...new Set(D.watch.filter((w) => w[4] === 'tse').map((w) => w[2]))];
      const otc = [...new Set(D.watch.filter((w) => w[4] === 'otc').map((w) => w[2]))];
      const calls = [];
      for (let i = 0; i < Math.max(tse.length, otc.length); i += 150) {
        calls.push(`${proxy}/?codes=${tse.slice(i, i + 150).join(',')}&otc=${otc.slice(i, i + 150).join(',')}`);
      }
      const res = await Promise.all(calls.map((u) => fetch(u, { cache: 'no-store' }).then((r) => r.json())));
      const q = new Map(); let ix = null;
      res.forEach((j) => {
        if (j.error) throw new Error(j.error);
        j.quotes.forEach((x) => { if (x.c === 't00') ix = x; else q.set((x.ex || 'tse') + x.c, x); });
      });
      const t = tpe();
      if (!ix || ix.d !== t.ymd.replace(/-/g, '')) { done = true; renderBreak([...D.breakout], 'close', `今日休市 · 顯示 ${D.date}`); return; }
      const list = [];
      for (const [c, n, s, sn, m, conv, prev, cbref] of D.watch) {
        const x = q.get(m + s);
        if (!x || !num(x.v)) continue;
        const b = first(x.b), a = first(x.a);
        const p = num(x.z) ?? (b && a ? (b + a) / 2 : b ?? a);
        if (p && p >= conv) list.push({ c, n, s, sn, m, conv, prev, p, cb: cbref });
      }
      lastPoll = Date.now();
      const after = t.mins > 13 * 60 + 30;
      if (after && ix.t >= '13:30') done = true;
      renderBreak(list, 'live', after ? '今日收盤（即時報價）' : '<span class="dot"></span>盤中即時',
        `報價時間 ${ix.t} · 每 10 分鐘更新 · 監看 ${D.watch.length} 檔（昨收低於轉換價）`);
    } catch (e) {
      $('cb-time').textContent = '即時報價暫時無法取得（' + e.message + '），10 分鐘後重試';
      lastPoll = Date.now();
    } finally {
      busy = false;
    }
  }
  poll(true);
  setInterval(() => poll(false), 30 * 1000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(false); });
})();
