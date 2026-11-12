(async function () {
  const $ = (id) => document.getElementById(id);
  const fmt = (n, d = 0) => n == null || Number.isNaN(n) ? '—' : n.toLocaleString('zh-TW', { minimumFractionDigits: d, maximumFractionDigits: d });
  const sgn = (n, d = 0) => n == null ? '—' : (n > 0 ? '+' : n < 0 ? '−' : '') + fmt(Math.abs(n), d);
  const cls = (n) => n > 0 ? 'up' : n < 0 ? 'down' : '';
  const num = (v) => { const n = parseFloat(String(v ?? '').replace(/,/g, '')); return Number.isFinite(n) && n > 0 ? n : null; };
  const first = (s) => num(String(s || '').split('_')[0]);
  const tpe = () => {
    const d = new Date(Date.now() + 8 * 3600e3);
    return { dow: d.getUTCDay(), mins: d.getUTCHours() * 60 + d.getUTCMinutes(), ymd: d.toISOString().slice(0, 10) };
  };

  // 外資券商（名稱關鍵字）；大和國泰為本國券商，不列入
  const FOREIGN = /美商|港商|新加坡商|英商|法商|德商|瑞士商|日商|荷商|摩根|美林|高盛|瑞銀|花旗|德意志|麥格理|野村|法銀|巴黎|匯豐|瑞信|星展|渣打|里昂|大和(?!國泰)|麥格理|富瑞|傑富瑞|蘇皇|三菱|瑞穗/;
  const isForeign = (b) => FOREIGN.test(b);

  let cfg = { quoteProxy: '' };
  try { cfg = { ...cfg, ...(await (await fetch('config.json', { cache: 'no-cache' })).json()) }; } catch (e) { /* 無設定 */ }
  const proxy = (cfg.quoteProxy || '').replace(/\/$/, '');
  if (!proxy) { $('ob-status').textContent = '尚未設定即時資料來源'; return; }

  let stocks = [], subtitle = '', loadedAt = 0;
  const px = new Map();

  function parse(j) {
    const map = new Map();
    for (const r of j.data) {
      const m = String(r[0]).match(/^(\d+)\s*-\s*(.+)\((\w+)\)$/);
      if (!m) continue;
      const key = m[3];
      if (!map.has(key)) map.set(key, { rank: +m[1], name: m[2].trim(), code: m[3], brokers: [] });
      const buy = +String(r[3]).replace(/,/g, ''), sell = +String(r[4]).replace(/,/g, '');
      map.get(key).brokers.push({ name: String(r[2]).trim(), buy, sell, net: buy - sell, fx: isForeign(String(r[2])) });
    }
    return [...map.values()].sort((a, b) => a.rank - b.rank);
  }

  function render() {
    $('ob-grid').innerHTML = stocks.map((s) => {
      const fx = s.brokers.filter((b) => b.fx);
      const fxNet = fx.reduce((a, b) => a + b.net, 0);
      const badge = fx.length
        ? `<span class="fx-badge ${fxNet > 0 ? 'buy' : fxNet < 0 ? 'sell' : ''}">外資分點 ${fxNet > 0 ? '買超' : fxNet < 0 ? '賣超' : '持平'} ${fmt(Math.abs(fxNet))} 張</span>`
        : '<span class="fx-badge none">前 10 大無外資分點</span>';
      const q = px.get(s.code);
      const price = q ? `<span class="ob-px ${cls(q.pct)}">${fmt(q.p, q.p >= 100 ? 1 : 2)} <i>${sgn(q.pct, 2)}%</i></span>` : '';
      const rows = s.brokers.map((b) => `<tr class="${b.fx ? 'fx' : ''}">
        <td>${b.fx ? '<i class="fx-tag">外</i>' : ''}${b.name}</td>
        <td class="r">${fmt(b.buy)}</td><td class="r">${fmt(b.sell)}</td><td class="r ${cls(b.net)}">${sgn(b.net)}</td></tr>`).join('');
      return `<article class="ob-card">
        <header><span class="ob-rank">${s.rank}</span><div class="ob-name"><b>${s.name}</b><em>${s.code}</em></div>${price}</header>
        ${badge}
        <table class="ob-tbl"><thead><tr><th>券商</th><th class="r">買</th><th class="r">賣</th><th class="r">買賣超</th></tr></thead><tbody>${rows}</tbody></table>
      </article>`;
    }).join('') || '<div class="empty">目前沒有資料</div>';
  }

  async function loadPrices() {
    if (!stocks.length) return;
    try {
      const j = await (await fetch(`${proxy}/?otc=${stocks.map((s) => s.code).join(',')}`, { cache: 'no-store' })).json();
      for (const x of j.quotes || []) {
        if (x.c === 't00') continue;
        const y = num(x.y), b = first(x.b), a = first(x.a);
        const p = num(x.z) ?? (b && a ? (b + a) / 2 : b ?? a) ?? y;
        if (p) px.set(x.c, { p, pct: y ? (p / y - 1) * 100 : null });
      }
      render();
    } catch (e) { /* 股價為輔助資訊，失敗不影響 */ }
  }

  async function load() {
    try {
      const j = await (await fetch(`${proxy}/broker`, { cache: 'no-store' })).json();
      if (j.error || !j.data) throw new Error(j.error || '中繼服務需更新（請部署最新 Worker 程式碼）');
      stocks = parse(j);
      subtitle = j.subtitle;
      loadedAt = Date.now();
      const m = subtitle.match(/截至\s*([\d:]+)\s*止/);
      const d = subtitle.match(/(\d+)年(\d+)月(\d+)日/);
      $('ob-status').className = 'pill live';
      $('ob-status').textContent = d ? `${+d[1] + 1911}-${d[2]}-${d[3]}　截至 ${m ? m[1] : ''}` : subtitle;
      $('ob-time').textContent = `${stocks.length} 檔熱門股 · 整點後 10 分鐘自動更新`;
      render();
      loadPrices();
    } catch (e) {
      $('ob-status').className = 'pill';
      $('ob-status').textContent = '資料暫時無法取得';
      $('ob-time').textContent = e.message;
    }
  }

  // 排程：10:10、11:10、12:10 抓新資料（頁面開著時）；股價每 10 分鐘更新
  const SLOTS = [10 * 60 + 10, 11 * 60 + 10, 12 * 60 + 10];
  const slotOf = (mins) => SLOTS.filter((s) => mins >= s).pop() ?? -1;
  let lastSlot = slotOf(tpe().mins), lastPx = Date.now();
  setInterval(() => {
    const t = tpe();
    if (t.dow < 1 || t.dow > 5) return;
    const s = slotOf(t.mins);
    if (s !== lastSlot) { lastSlot = s; load(); }
    else if (t.mins >= 540 && t.mins <= 13 * 60 + 35 && Date.now() - lastPx > 10 * 60 * 1000) { lastPx = Date.now(); loadPrices(); }
  }, 20 * 1000);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && Date.now() - loadedAt > 10 * 60 * 1000) load();
  });
  load();
})();
