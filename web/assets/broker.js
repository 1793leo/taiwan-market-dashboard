(async function () {
  const $ = (id) => document.getElementById(id);
  const fmt = (n, d = 0) => n == null || Number.isNaN(n) ? '—' : n.toLocaleString('zh-TW', { minimumFractionDigits: d, maximumFractionDigits: d });
  const sgn = (n, d = 0) => n == null ? '—' : (n > 0 ? '+' : n < 0 ? '−' : '') + fmt(Math.abs(n), d);
  const cls = (n) => n > 0 ? 'up' : n < 0 ? 'down' : '';
  const num = (v) => { const n = parseFloat(String(v ?? '').replace(/,/g, '')); return Number.isFinite(n) && n > 0 ? n : null; };
  const first = (s) => { for (const x of String(s || '').split('_')) { const n = num(x); if (n) return n; } return null; };   // 跳過漲跌停鎖死時的市價委託 0
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

  let stocks = [], subtitle = '', loadedAt = 0, asof = '';
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
    $('ob-grid').innerHTML = stocks.map((s, i) => {
      const fx = s.brokers.filter((b) => b.fx);
      const fxNet = fx.reduce((a, b) => a + b.net, 0);
      const side = !fx.length ? 'none' : fxNet > 0 ? 'buy' : fxNet < 0 ? 'sell' : 'flat';
      const badge = !fx.length ? '<b>無外資分點</b>'
        : `<b>外資${fxNet > 0 ? '買超' : fxNet < 0 ? '賣超' : '持平'}</b><span>${fmt(Math.abs(fxNet))} 張</span>`;
      const q = px.get(s.code);
      return `<button class="ob-card ${side}" data-i="${i}">
        <div class="ob-top"><span class="ob-rank">${s.rank}</span><b class="ob-nm">${s.name}</b><em>${s.code}</em></div>
        <div class="ob-mid ${q ? cls(q.pct) : ''}">${q ? `<span>${fmt(q.p, q.p >= 100 ? 1 : 2)}</span><span>${sgn(q.pct, 2)}%</span>` : '<span>—</span>'}</div>
        <div class="fx-badge ${side}">${badge}</div>
      </button>`;
    }).join('') || '<div class="empty">目前沒有資料</div>';
  }

  // 點卡片顯示前 10 大券商明細
  function detail(i) {
    const s = stocks[i]; if (!s) return;
    const fx = s.brokers.filter((b) => b.fx), fxNet = fx.reduce((a, b) => a + b.net, 0);
    const q = px.get(s.code);
    const rows = s.brokers.map((b) => `<tr class="${b.fx ? 'fx' : ''}">
      <td>${b.fx ? '<i class="fx-tag">外</i>' : ''}${b.name}</td>
      <td class="r">${fmt(b.buy)}</td><td class="r">${fmt(b.sell)}</td><td class="r ${cls(b.net)}">${sgn(b.net)}</td></tr>`).join('');
    $('ob-modal-body').innerHTML = `
      <header><span class="ob-rank">${s.rank}</span><div class="ob-name"><b>${s.name}</b><em>${s.code}</em></div>
        ${q ? `<span class="ob-px ${cls(q.pct)}">${fmt(q.p, q.p >= 100 ? 1 : 2)}<i>${sgn(q.pct, 2)}%</i></span>` : ''}</header>
      <div class="fx-badge big ${!fx.length ? 'none' : fxNet > 0 ? 'buy' : fxNet < 0 ? 'sell' : 'flat'}">${fx.length
        ? `外資分點 ${fxNet > 0 ? '買超' : fxNet < 0 ? '賣超' : '持平'} ${fmt(Math.abs(fxNet))} 張` : '前 10 大無外資分點'}</div>
      <table class="ob-tbl"><thead><tr><th>券商</th><th class="r">買</th><th class="r">賣</th><th class="r">買賣超</th></tr></thead><tbody>${rows}</tbody></table>`;
    $('ob-modal').hidden = false;
  }
  $('ob-grid').addEventListener('click', (e) => { const c = e.target.closest('.ob-card'); if (c) detail(+c.dataset.i); });
  $('ob-modal').addEventListener('click', (e) => { if (e.target.id === 'ob-modal' || e.target.closest('.ob-close')) $('ob-modal').hidden = true; });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') $('ob-modal').hidden = true; });

  async function loadPrices() {
    if (!stocks.length || !proxy) return;
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
      const j = await (await fetch(`data/broker.json?t=${Date.now()}`, { cache: 'no-store' })).json();
      if (!j.data) throw new Error('尚無資料');
      asof = j.date + j.asof;
      stocks = parse(j);
      subtitle = j.subtitle;
      loadedAt = Date.now();
      const m = subtitle.match(/截至\s*([\d:]+)\s*止/);
      const d = subtitle.match(/(\d+)年(\d+)月(\d+)日/);
      $('ob-status').className = 'pill live';
      $('ob-status').textContent = d ? `${+d[1] + 1911}-${d[2]}-${d[3]}　截至 ${m ? m[1] : ''}` : subtitle;
      $('ob-time').textContent = `${stocks.length} 檔熱門股 · 10:10／11:10／12:10 自動更新`;
      render();
      loadPrices();
    } catch (e) {
      $('ob-status').className = 'pill';
      $('ob-status').textContent = '資料暫時無法取得';
      $('ob-time').textContent = e.message;
    }
  }

  // 資料於 10:10、11:10、12:10 由排程抓取並部署（可能延遲數分鐘）
  // 網頁在每個時段開始後每 2 分鐘檢查一次，取得該時段資料即停止；股價每 10 分鐘更新
  const SLOTS = [10 * 60 + 10, 11 * 60 + 10, 12 * 60 + 10];
  const want = (mins) => { const s = SLOTS.filter((x) => mins >= x).pop(); return s ? String(Math.floor((s - 10) / 60)).padStart(2, '0') + ':00' : null; };
  let lastCheck = 0, lastPx = Date.now();
  setInterval(() => {
    const t = tpe();
    if (t.dow < 1 || t.dow > 5) return;
    const w = want(t.mins);
    const fresh = asof.startsWith(t.ymd) && w && asof.slice(10) >= w;   // asof = 日期 + 截至時間
    if (w && !fresh && t.mins <= 13 * 60 + 30 && Date.now() - lastCheck > 2 * 60 * 1000) { lastCheck = Date.now(); load(); }
    else if (t.mins >= 540 && t.mins <= 13 * 60 + 35 && Date.now() - lastPx > 10 * 60 * 1000) { lastPx = Date.now(); loadPrices(); }
  }, 20 * 1000);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && Date.now() - loadedAt > 10 * 60 * 1000) load();
  });
  load();
})();
