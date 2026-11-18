(async function () {
  const $ = (id) => document.getElementById(id);
  const yi = (v) => v == null ? '—' : (v >= 1e8 ? fmt(v / 1e8, 2) + ' 億' : fmt(v / 1e4, 0) + ' 萬');
  const fmt = (n, d = 0) => n == null ? '—' : n.toLocaleString('zh-TW', { minimumFractionDigits: d, maximumFractionDigits: d });
  const px = (p) => p == null ? '—' : fmt(p, p >= 1000 ? 0 : 2);
  const chg = (c) => c == null ? '—' : `<span class="${c > 0 ? 'up' : c < 0 ? 'down' : ''}">${c > 0 ? '+' : ''}${fmt(c, Math.abs(c) >= 100 ? 0 : 2)}</span>`;

  let idx;
  try {
    idx = (await (await fetch('data/trust/index.json', { cache: 'no-cache' })).json()).dates;
  } catch (e) {
    $('tr-date').textContent = '尚無資料';
    return;
  }
  const allDates = Object.keys(idx).sort();
  if (!allDates.length) { $('tr-date').textContent = '尚無資料'; return; }

  const months = {};
  async function loadMonth(ym) {
    if (!months[ym]) {
      try { months[ym] = await (await fetch(`data/trust/${ym}.json`, { cache: 'no-cache' })).json(); }
      catch (e) { months[ym] = {}; }
    }
    return months[ym];
  }

  const first = allDates[0], last = allDates[allDates.length - 1];
  let view = last.slice(0, 7), selected = last;
  let sortKey = 8, sortDir = -1;        // 預設依投信賣超金額由大到小
  let rows = [];

  function renderCal() {
    const [y, m] = view.split('-').map(Number);
    $('tr-title').textContent = `${y} 年 ${m} 月`;
    $('tr-prev').disabled = view <= first.slice(0, 7);
    $('tr-next').disabled = view >= last.slice(0, 7);
    const start = new Date(Date.UTC(y, m - 1, 1)).getUTCDay();
    const days = new Date(Date.UTC(y, m, 0)).getUTCDate();
    const maxN = Math.max(1, ...allDates.filter((d) => d.startsWith(view)).map((d) => idx[d].n));
    let html = '<span class="cal-empty"></span>'.repeat(start);
    for (let d = 1; d <= days; d++) {
      const key = `${view}-${String(d).padStart(2, '0')}`;
      const info = idx[key];
      const cls = ['cal-day'];
      if (!info) cls.push('off');
      else if (!info.n) cls.push('zero');
      if (key === selected) cls.push('sel');
      const heat = info && info.n ? 0.10 + 0.45 * Math.sqrt(info.n / maxN) : 0;
      html += info
        ? `<button class="${cls.join(' ')}" data-d="${key}" style="--heat:${heat.toFixed(2)}"><b>${d}</b><i>${info.pending ? '…' : info.n}</i></button>`
        : `<span class="${cls.join(' ')}"><b>${d}</b></span>`;
    }
    $('tr-days').innerHTML = html;
  }
  $('tr-days').addEventListener('click', (e) => { const b = e.target.closest('button[data-d]'); if (b) select(b.dataset.d); });
  const shiftMonth = (k) => {
    const [y, m] = view.split('-').map(Number);
    const d = new Date(Date.UTC(y, m - 1 + k, 1));
    view = `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
    renderCal();
  };
  $('tr-prev').addEventListener('click', () => shiftMonth(-1));
  $('tr-next').addEventListener('click', () => shiftMonth(1));

  async function select(d) {
    selected = d;
    view = d.slice(0, 7);
    renderCal();
    const wk = '日一二三四五六'[new Date(d + 'T00:00:00+08:00').getDay()];
    $('tr-date').textContent = `${d}（${wk}）`;
    rows = (await loadMonth(view))[d] || [];
    renderSummary();
    renderTable();
  }

  function renderSummary() {
    const info = idx[selected] || {};
    const tw = rows.filter((r) => r[2] === '上市').length;
    $('tr-n').textContent = `${rows.length} 檔`;
    $('tr-nsub').textContent = info.pending ? '個股成交量尚未更新' : `上市 ${tw} · 上櫃 ${rows.length - tw}`;
    const sum = rows.reduce((a, r) => a + (r[8] || 0), 0);
    $('tr-sum').textContent = rows.length ? yi(sum) : '—';
    $('tr-sumsub').textContent = rows.length ? `${fmt(rows.reduce((a, r) => a + r[3], 0))} 張 · 符合條件個股合計` : '—';
    const top = rows.reduce((a, r) => (!a || (r[8] || 0) > (a[8] || 0) ? r : a), null);
    $('tr-max').textContent = top ? top[1] : '—';
    $('tr-maxsub').textContent = top ? `${top[0]} · ${yi(top[8])} · 占成交量 ${fmt(top[5], 1)}%` : '—';
  }

  function renderTable() {
    const sorted = [...rows].sort((a, b) => {
      const x = a[sortKey], y = b[sortKey];
      if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1;
      return (typeof x === 'number' ? x - y : String(x).localeCompare(String(y), 'zh-TW')) * sortDir;
    });
    document.querySelectorAll('.tr-table th').forEach((th) => {
      th.classList.toggle('on', +th.dataset.k === sortKey);
      th.dataset.dir = +th.dataset.k === sortKey ? (sortDir > 0 ? '▲' : '▼') : '';
    });
    const info = idx[selected] || {};
    const empty = info.pending ? '個股成交量尚未更新，稍後重新整理' : '當日沒有投信賣超超過成交量 10% 的普通股';
    $('tr-body').innerHTML = sorted.length ? sorted.map((r) => `<tr>
      <td class="mono hide-sm">${r[0]}</td><td><b>${r[1]}</b><em class="sm-code">${r[0]}</em></td><td class="hide-sm muted">${r[2]}</td>
      <td class="r mono b down">${yi(r[8])}</td><td class="r mono">${fmt(r[3])}</td><td class="r mono hide-sm">${fmt(r[4])}</td>
      <td class="r mono b">${fmt(r[5], 1)}%</td><td class="r mono hide-sm">${px(r[6])}</td><td class="r mono">${chg(r[7])}</td>
    </tr>`).join('') : `<tr><td colspan="9" class="none">${empty}</td></tr>`;
  }
  document.querySelectorAll('.tr-table th').forEach((th) => th.addEventListener('click', () => {
    const k = +th.dataset.k;
    if (k === sortKey) sortDir = -sortDir; else { sortKey = k; sortDir = k >= 3 ? -1 : 1; }
    renderTable();
  }));

  select(last);
})();
