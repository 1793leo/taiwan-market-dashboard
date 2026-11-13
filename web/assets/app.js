(async function () {
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const C = { up: css('--up'), down: css('--down'), b5: css('--b5'), b20: css('--b20'),
    text: css('--text'), muted: css('--muted'), grid: css('--grid'), line: css('--line') };

  // ---------- tabs
  document.querySelectorAll('.tab').forEach((t) => t.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((x) => x.classList.toggle('active', x === t));
    document.querySelectorAll('.panel').forEach((p) => p.classList.toggle('active', p.id === 'tab-' + t.dataset.tab));
  }));

  // ---------- data
  const res = await fetch('data/dashboard.json', { cache: 'no-cache' });
  const D = await res.json();
  document.getElementById('updated').textContent = '更新於 ' + D.updated;

  const T = D.taiex, B = D.breadth;
  // 防護：若最後一筆是今日但還沒有成交金額（盤中未收盤資料），視為尚未收盤，不列入歷史
  {
    const today = new Date(Date.now() + 8 * 3600e3).toISOString().slice(0, 10);
    const n = T.date.length - 1;
    if (n >= 0 && T.date[n] >= today && !T.turnover[n]) for (const k of Object.keys(T)) T[k].pop();
  }
  const bIdx = new Map(B.date.map((d, i) => [d, i]));
  const rows = T.date.map((d, i) => {
    const j = bIdx.get(d);
    return {
      time: d, open: T.open[i], high: T.high[i], low: T.low[i], close: T.close[i],
      vol: T.volume[i], turn: T.turnover[i],
      b5: j == null ? null : B.above5[j], t5: j == null ? null : B.total5[j],
      b20: j == null ? null : B.above20[j], t20: j == null ? null : B.total20[j],
    };
  });
  const byTime = new Map(rows.map((r, i) => [r.time, i]));
  const fmt = (n, d = 2) => n == null ? '—' : n.toLocaleString('zh-TW', { minimumFractionDigits: d, maximumFractionDigits: d });
  const pct = (a, b) => (a == null || !b) ? null : (a / b) * 100;
  const yi = (v) => v / 1e8; // 元 → 億

  // ---------- charts
  const base = {
    layout: { background: { type: 'solid', color: 'transparent' }, textColor: C.muted, fontFamily: 'JetBrains Mono, monospace' },
    grid: { vertLines: { color: C.grid }, horzLines: { color: C.grid } },
    rightPriceScale: { borderColor: C.line, minimumWidth: 70 },
    timeScale: { borderColor: C.line, rightOffset: 3 },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    localization: { locale: 'zh-TW' },
    autoSize: true,
  };
  const ck = LightweightCharts.createChart(document.getElementById('chart-k'), base);
  const cb = LightweightCharts.createChart(document.getElementById('chart-b'), base);

  const candle = ck.addCandlestickSeries({
    upColor: C.up, downColor: C.down, borderUpColor: C.up, borderDownColor: C.down,
    wickUpColor: C.up, wickDownColor: C.down,
  });
  candle.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: 0.26 } });
  candle.setData(rows.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })));

  // 加權指數均線（含盤中即時的今日 K 棒一起計算）
  const MAS = [
    { n: 5, color: '#e0a800' }, { n: 20, color: '#8b5cf6' }, { n: 60, color: '#0ea5e9' },
    { n: 120, color: '#ec4899' }, { n: 240, color: '#64748b' },
  ];
  MAS.forEach((m) => {
    m.series = ck.addLineSeries({ color: m.color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
      crosshairMarkerVisible: false });
  });
  function setMAs() {
    MAS.forEach((m) => {
      let sum = 0;
      m.vals = rows.map((r, i) => {
        sum += r.close;
        if (i >= m.n) sum -= rows[i - m.n].close;
        return i >= m.n - 1 ? sum / m.n : null;
      });
      m.series.setData(rows.map((r, i) => m.vals[i] == null ? { time: r.time } : { time: r.time, value: m.vals[i] }));
    });
  }
  setMAs();

  const vol = ck.addHistogramSeries({ priceScaleId: 'vol', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false });
  ck.priceScale('vol').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
  vol.setData(rows.map((r) => ({ time: r.time, value: yi(r.turn),
    color: (r.close >= r.open ? C.up : C.down) + '66' })));

  const l5 = cb.addLineSeries({ color: C.b5, lineWidth: 2, priceLineVisible: false });
  const l20 = cb.addLineSeries({ color: C.b20, lineWidth: 2, priceLineVisible: false });

  let mode = 'count';
  function setBreadth() {
    const pick = (b, t) => mode === 'pct' ? pct(b, t) : b;
    // 沒有寬度資料的日子放 whitespace，讓兩張圖的 bar index 一致以便同步
    l5.setData(rows.map((r) => r.b5 == null ? { time: r.time } : { time: r.time, value: pick(r.b5, r.t5) }));
    l20.setData(rows.map((r) => r.b20 == null ? { time: r.time } : { time: r.time, value: pick(r.b20, r.t20) }));
    const pf = mode === 'pct' ? { type: 'custom', formatter: (v) => v.toFixed(1) + '%' } : { type: 'custom', formatter: (v) => Math.round(v).toString() };
    l5.applyOptions({ priceFormat: pf }); l20.applyOptions({ priceFormat: pf });
  }
  setBreadth();

  // ---------- sync
  let syncing = false;
  const link = (a, b) => a.timeScale().subscribeVisibleLogicalRangeChange((r) => {
    if (syncing || !r) return; syncing = true; b.timeScale().setVisibleLogicalRange(r); syncing = false;
  });
  link(ck, cb); link(cb, ck);

  const lgK = document.getElementById('lg-k'), lgB = document.getElementById('lg-b');
  function legend(i) {
    const r = rows[i]; if (!r) return;
    const prev = rows[i - 1];
    const chg = prev ? r.close - prev.close : 0;
    const cls = chg >= 0 ? 'up' : 'down';
    lgK.innerHTML = `<b>${r.time}</b><span class="muted">開</span><span class="${cls}">${fmt(r.open)}</span>`
      + `<span class="muted">高</span><span class="${cls}">${fmt(r.high)}</span>`
      + `<span class="muted">低</span><span class="${cls}">${fmt(r.low)}</span>`
      + `<span class="muted">收</span><span class="${cls}">${fmt(r.close)} (${chg >= 0 ? '+' : ''}${fmt(chg)})</span>`
      + (r.live ? `<span class="opt"><span class="muted">盤中 ${r.qt}</span></span>`
        : `<span class="opt"><span class="muted">金額</span><span>${fmt(yi(r.turn), 0)} 億</span>`
        + `<span class="muted">股數</span><span>${fmt(r.vol / 1e6, 0)} 百萬股</span></span>`)
      + `<span class="ma-row">${MAS.map((m) => `<span style="color:${m.color}">MA${m.n} ${fmt(m.vals[i])}</span>`).join('')}</span>`;
    const p5 = pct(r.b5, r.t5), p20 = pct(r.b20, r.t20);
    lgB.innerHTML = `<b>${r.time}</b>`
      + `<span style="color:${C.b5}">● 高於5日均 ${r.b5 ?? '—'}/${r.t5 ?? '—'} (${fmt(p5, 1)}%)</span>`
      + `<span style="color:${C.b20}">● 高於20日均 ${r.b20 ?? '—'}/${r.t20 ?? '—'} (${fmt(p20, 1)}%)</span>`;
  }
  const lastIdx = () => rows.length - 1;
  legend(lastIdx());

  function onMove(src, dst, dstSeries, val) {
    src.subscribeCrosshairMove((p) => {
      if (!p.time) { dst.clearCrosshairPosition(); legend(lastIdx()); return; }
      const i = byTime.get(p.time); legend(i);
      const v = val(rows[i]);
      if (v != null) dst.setCrosshairPosition(v, p.time, dstSeries); else dst.clearCrosshairPosition();
    });
  }
  onMove(ck, cb, l20, (r) => r.b20 == null ? null : (mode === 'pct' ? pct(r.b20, r.t20) : r.b20));
  onMove(cb, ck, candle, (r) => r.close);

  // ---------- controls
  function setRange(n) {
    const len = rows.length;
    const from = n ? Math.max(0, len - n) : 0;
    ck.timeScale().setVisibleLogicalRange({ from, to: len - 1 + 3 });
  }
  document.querySelectorAll('#range button').forEach((b) => b.addEventListener('click', () => {
    document.querySelectorAll('#range button').forEach((x) => x.classList.toggle('on', x === b));
    setRange(+b.dataset.r);
  }));
  document.querySelectorAll('#mode button').forEach((b) => b.addEventListener('click', () => {
    document.querySelectorAll('#mode button').forEach((x) => x.classList.toggle('on', x === b));
    mode = b.dataset.m;
    const r = ck.timeScale().getVisibleLogicalRange();
    setBreadth();
    if (r) ck.timeScale().setVisibleLogicalRange(r);
  }));
  setRange(126);

  // ---------- cards (最新一筆有寬度資料的日子)
  function renderCards() {
  const last = lastIdx();
  const L = rows[last], P = rows[last - 1];
  const chg = P ? L.close - P.close : 0, chgp = P ? chg / P.close * 100 : 0;
  const cc = document.getElementById('c-close');
  cc.textContent = fmt(L.close); cc.className = 'v ' + (chg >= 0 ? 'up' : 'down');
  const cg = document.getElementById('c-chg');
  cg.textContent = `${chg >= 0 ? '▲' : '▼'} ${fmt(Math.abs(chg))} (${fmt(chgp)}%)`; cg.className = 'd ' + (chg >= 0 ? 'up' : 'down');
  document.getElementById('c-turn').textContent = L.live ? '盤中' : fmt(yi(L.turn), 0) + ' 億';
  document.getElementById('c-date').textContent = L.live ? `${L.time} · 收盤後公布` : L.time;
  let k = last; while (k > 0 && rows[k].b5 == null) k--;
  const R = rows[k];
  document.getElementById('c-b5').textContent = R.b5 ?? '—';
  document.getElementById('c-b5p').textContent = `/ ${R.t5 ?? '—'} 家 · ${fmt(pct(R.b5, R.t5), 1)}%` + (k !== last ? ` (${R.time})` : '');
  document.getElementById('c-b20').textContent = R.b20 ?? '—';
  document.getElementById('c-b20p').textContent = `/ ${R.t20 ?? '—'} 家 · ${fmt(pct(R.b20, R.t20), 1)}%` + (k !== last ? ` (${R.time})` : '');
  }
  renderCards();

  // ---------- 盤中即時（每 10 分鐘）
  let cfg = { quoteProxy: '' };
  try { cfg = { ...cfg, ...(await (await fetch('config.json', { cache: 'no-cache' })).json()) }; } catch (e) { /* 無設定 */ }
  const LIVE_MS = 10 * 60 * 1000;
  const tpe = () => {
    const d = new Date(Date.now() + 8 * 3600e3);
    return { dow: d.getUTCDay(), mins: d.getUTCHours() * 60 + d.getUTCMinutes(), ymd: d.toISOString().slice(0, 10) };
  };
  const histLast = T.date[T.date.length - 1];
  const num = (v) => { const n = parseFloat(String(v ?? '').replace(/,/g, '')); return Number.isFinite(n) && n > 0 ? n : null; };
  const first = (s) => { for (const x of String(s || '').split('_')) { const n = num(x); if (n) return n; } return null; };   // 跳過漲跌停鎖死時的市價委託 0
  const status = (html, cls, sub) => {
    const st = document.getElementById('ma-status'); st.className = 'pill' + (cls ? ' ' + cls : ''); st.innerHTML = html;
    document.getElementById('ma-time').textContent = sub || '';
  };
  status(`盤後 · ${histLast}`);

  let TH = null, lastPoll = 0, busy = false, liveDone = false;
  const liveWindow = () => { const t = tpe(); return t.dow >= 1 && t.dow <= 5 && t.mins >= 540 && histLast < t.ymd; };

  async function pollLive(force) {
    if (busy || liveDone || !cfg.quoteProxy || !liveWindow()) return;
    if (!force && (document.hidden || Date.now() - lastPoll < LIVE_MS - 5000)) return;
    busy = true;
    try {
      if (!TH) TH = await (await fetch('data/ma_live.json', { cache: 'no-cache' })).json();
      const proxy = cfg.quoteProxy.replace(/\/$/, '');
      const calls = [];
      for (const [ex, key] of [['tse', 'codes'], ['otc', 'otc']]) {
        const cs = TH[ex].map((x) => x[0]);
        for (let i = 0; i < cs.length; i += 300) calls.push(`${proxy}/?${key}=${cs.slice(i, i + 300).join(',')}`);
      }
      const res = await Promise.all(calls.map((u) => fetch(u, { cache: 'no-store' }).then((r) => r.json())));
      const quotes = new Map();
      let ix = null;
      res.forEach((j) => {
        if (j.error) throw new Error(j.error);
        j.quotes.forEach((q) => { if (q.c === 't00') ix = q; else quotes.set((q.ex || 'tse') + q.c, q); });
      });
      const t = tpe();
      if (!ix || ix.d !== t.ymd.replace(/-/g, '')) { liveDone = true; status(`今日休市 · 顯示 ${histLast} 收盤`); return; }

      let a5 = 0, n5 = 0, a20 = 0, n20 = 0;
      for (const ex of ['tse', 'otc']) {
        for (const [c, t5, t20] of TH[ex]) {
          const q = quotes.get(ex + c);
          if (!q || !num(q.v)) continue;                       // 今日尚未成交者不列入（與盤後口徑一致）
          const b = first(q.b), a = first(q.a);
          const p = num(q.z) ?? (b && a ? (b + a) / 2 : b ?? a);
          if (!p) continue;
          if (t5 != null) { n5++; if (p > t5) a5++; }
          if (t20 != null) { n20++; if (p > t20) a20++; }
        }
      }
      const z = num(ix.z) ?? num(ix.y);
      const row = { time: t.ymd, open: num(ix.o) ?? z, high: num(ix.h) ?? z, low: num(ix.l) ?? z, close: z,
        vol: null, turn: null, b5: a5, t5: n5, b20: a20, t20: n20, live: true, qt: ix.t };
      if (rows[rows.length - 1].time === row.time) rows[rows.length - 1] = row; else rows.push(row);
      byTime.set(row.time, rows.length - 1);

      const r = ck.timeScale().getVisibleLogicalRange();
      candle.update({ time: row.time, open: row.open, high: row.high, low: row.low, close: row.close });
      setMAs();
      vol.update({ time: row.time });
      setBreadth();
      if (r) ck.timeScale().setVisibleLogicalRange(r);
      legend(lastIdx());
      renderCards();
      lastPoll = Date.now();
      const after = t.mins > 13 * 60 + 30;
      if (after && ix.t >= '13:30') liveDone = true;   // 已取得收盤價，等待盤後官方資料
      status(after ? '今日收盤（即時報價）' : '<span class="dot"></span>盤中即時', 'live',
        `報價時間 ${ix.t} · 每 10 分鐘更新` + (after ? ' · 15:40 後換成官方盤後資料' : ''));
    } catch (e) {
      document.getElementById('ma-time').textContent = '即時報價暫時無法取得（' + e.message + '），10 分鐘後重試';
      lastPoll = Date.now();
    } finally {
      busy = false;
    }
  }
  pollLive(true);
  setInterval(() => pollLive(false), 30 * 1000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) pollLive(false); });
})();
