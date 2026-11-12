(async function () {
  const $ = (id) => document.getElementById(id);
  const fmt = (n, d = 0) => n == null ? '—' : n.toLocaleString('zh-TW', { minimumFractionDigits: d, maximumFractionDigits: d });
  const yi = (v) => v / 1e8;
  const fmtYi = (v) => { const x = yi(v); return x >= 100 ? fmt(x, 0) : x >= 10 ? fmt(x, 1) : fmt(x, 2); };
  const fmtPx = (p) => p >= 1000 ? fmt(p, 2) : p >= 100 ? fmt(p, 2) : fmt(p, 2);

  let idx;
  try {
    idx = (await (await fetch('data/block/index.json', { cache: 'no-cache' })).json()).dates;
  } catch (e) {
    $('bk-date').textContent = '尚無鉅額交易資料';
    return;
  }
  const allDates = Object.keys(idx).sort();
  if (!allDates.length) { $('bk-date').textContent = '尚無鉅額交易資料'; return; }

  const months = {};                    // 每月明細快取
  async function loadMonth(ym) {
    if (!months[ym]) {
      try { months[ym] = await (await fetch(`data/block/${ym}.json`, { cache: 'no-cache' })).json(); }
      catch (e) { months[ym] = {}; }
    }
    return months[ym];
  }

  const first = allDates[0], last = allDates[allDates.length - 1];
  let view = last.slice(0, 7);          // 日曆顯示的月份 YYYY-MM
  let selected = last;
  let sortKey = 7, sortDir = 1;         // 預設依市值由小到大
  let rows = [];

  // ---------- calendar
  function renderCal() {
    const [y, m] = view.split('-').map(Number);
    $('cal-title').textContent = `${y} 年 ${m} 月`;
    $('cal-prev').disabled = view <= first.slice(0, 7);
    $('cal-next').disabled = view >= last.slice(0, 7);
    const start = new Date(Date.UTC(y, m - 1, 1)).getUTCDay();
    const days = new Date(Date.UTC(y, m, 0)).getUTCDate();
    const maxV = Math.max(1, ...allDates.filter((d) => d.startsWith(view)).map((d) => idx[d].v));
    let html = '<span class="cal-empty"></span>'.repeat(start);
    for (let d = 1; d <= days; d++) {
      const key = `${view}-${String(d).padStart(2, '0')}`;
      const info = idx[key];
      const cls = ['cal-day'];
      if (!info) cls.push('off');
      else if (!info.n) cls.push('zero');
      if (key === selected) cls.push('sel');
      const heat = info && info.n ? 0.10 + 0.45 * Math.sqrt(info.v / maxV) : 0;
      html += info
        ? `<button class="${cls.join(' ')}" data-d="${key}" style="--heat:${heat.toFixed(2)}"><b>${d}</b></button>`
        : `<span class="${cls.join(' ')}"><b>${d}</b></span>`;
    }
    $('cal-days').innerHTML = html;
  }
  $('cal-days').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-d]');
    if (b) select(b.dataset.d);
  });
  const shiftMonth = (k) => {
    const [y, m] = view.split('-').map(Number);
    const d = new Date(Date.UTC(y, m - 1 + k, 1));
    view = `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
    renderCal();
  };
  $('cal-prev').addEventListener('click', () => shiftMonth(-1));
  $('cal-next').addEventListener('click', () => shiftMonth(1));

  // ---------- table
  async function select(d) {
    selected = d;
    view = d.slice(0, 7);
    renderCal();
    const wk = '日一二三四五六'[new Date(d + 'T00:00:00+08:00').getDay()];
    $('bk-date').textContent = `${d}（${wk}）`;
    rows = (await loadMonth(view))[d] || [];
    renderSummary();
    renderTable();
  }

  function renderSummary() {
    const sum = rows.reduce((a, r) => a + r[5], 0);
    const codes = new Set(rows.map((r) => r[0]));
    $('bk-sum').textContent = rows.length ? fmtYi(sum) + ' 億' : '—';
    $('bk-sumsub').textContent = rows.length ? `${fmt(sum)} 元` : '當日無普通股鉅額交易';
    $('bk-n').textContent = fmt(rows.length);
    $('bk-nsub').textContent = `共 ${codes.size} 檔普通股`;
    const top = rows.reduce((a, r) => (!a || r[5] > a[5] ? r : a), null);
    $('bk-max').textContent = top ? top[1] : '—';
    $('bk-maxsub').textContent = top ? `${top[0]} · ${fmtYi(top[5])} 億 · ${fmt(top[4] / 1000)} 張` : '—';
  }

  function renderTable() {
    const sorted = [...rows].sort((a, b) => {
      const x = a[sortKey], y = b[sortKey];
      if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1;   // 無市值者排最後
      return (typeof x === 'number' ? x - y : String(x).localeCompare(String(y), 'zh-TW')) * sortDir;
    });
    document.querySelectorAll('.bk-table th').forEach((th) => {
      th.classList.toggle('on', +th.dataset.k === sortKey);
      th.dataset.dir = +th.dataset.k === sortKey ? (sortDir > 0 ? '▲' : '▼') : '';
    });
    $('bk-body').innerHTML = sorted.length ? sorted.map((r) => `<tr>
      <td class="mono hide-sm">${r[0]}</td><td><b>${r[1]}</b><em class="sm-code">${r[0]}</em></td><td class="hide-sm muted">${r[2]}</td>
      <td class="r mono">${fmtPx(r[3])}</td><td class="r mono"><span class="full">${fmt(r[4])}</span><span class="short">${fmt(r[4] / 1000)} 張</span></td>
      <td class="r mono b"><span class="full">${fmt(r[5])}</span><span class="short">${fmtYi(r[5])} 億</span></td><td class="r mono hide-sm muted">${r[6] || '—'}</td><td class="r mono">${r[7] == null ? '—' : fmt(r[7], r[7] >= 1000 ? 0 : 1)}</td>
    </tr>`).join('') : '<tr><td colspan="8" class="none">當日無普通股鉅額交易</td></tr>';
  }
  document.querySelectorAll('.bk-table th').forEach((th) => th.addEventListener('click', () => {
    const k = +th.dataset.k;
    if (k === sortKey) sortDir = -sortDir; else { sortKey = k; sortDir = k >= 3 ? -1 : 1; }
    renderTable();
  }));

  select(last);
})();
