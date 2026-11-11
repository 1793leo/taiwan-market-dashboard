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
      + `<span class="opt"><span class="muted">金額</span><span>${fmt(yi(r.turn), 0)} 億</span>`
      + `<span class="muted">股數</span><span>${fmt(r.vol / 1e6, 0)} 百萬股</span></span>`;
    const p5 = pct(r.b5, r.t5), p20 = pct(r.b20, r.t20);
    lgB.innerHTML = `<b>${r.time}</b>`
      + `<span style="color:${C.b5}">● 高於5日均 ${r.b5 ?? '—'}/${r.t5 ?? '—'} (${fmt(p5, 1)}%)</span>`
      + `<span style="color:${C.b20}">● 高於20日均 ${r.b20 ?? '—'}/${r.t20 ?? '—'} (${fmt(p20, 1)}%)</span>`;
  }
  const last = rows.length - 1;
  legend(last);

  function onMove(src, dst, dstSeries, val) {
    src.subscribeCrosshairMove((p) => {
      if (!p.time) { dst.clearCrosshairPosition(); legend(last); return; }
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
  const L = rows[last], P = rows[last - 1];
  const chg = P ? L.close - P.close : 0, chgp = P ? chg / P.close * 100 : 0;
  const cc = document.getElementById('c-close');
  cc.textContent = fmt(L.close); cc.className = 'v ' + (chg >= 0 ? 'up' : 'down');
  const cg = document.getElementById('c-chg');
  cg.textContent = `${chg >= 0 ? '▲' : '▼'} ${fmt(Math.abs(chg))} (${fmt(chgp)}%)`; cg.className = 'd ' + (chg >= 0 ? 'up' : 'down');
  document.getElementById('c-turn').textContent = fmt(yi(L.turn), 0) + ' 億';
  document.getElementById('c-date').textContent = L.time;
  let k = last; while (k > 0 && rows[k].b5 == null) k--;
  const R = rows[k];
  document.getElementById('c-b5').textContent = R.b5 ?? '—';
  document.getElementById('c-b5p').textContent = `/ ${R.t5 ?? '—'} 家 · ${fmt(pct(R.b5, R.t5), 1)}%` + (k !== last ? ` (${R.time})` : '');
  document.getElementById('c-b20').textContent = R.b20 ?? '—';
  document.getElementById('c-b20p').textContent = `/ ${R.t20 ?? '—'} 家 · ${fmt(pct(R.b20, R.t20), 1)}%` + (k !== last ? ` (${R.time})` : '');
})();
