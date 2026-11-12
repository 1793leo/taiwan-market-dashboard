(async function () {
  const $ = (id) => document.getElementById(id);
  const fmt = (n, d = 2) => n == null || Number.isNaN(n) ? '—' : n.toLocaleString('zh-TW', { minimumFractionDigits: d, maximumFractionDigits: d });
  const sgn = (n) => n == null ? '—' : (n > 0 ? '+' : n < 0 ? '−' : '') + fmt(Math.abs(n));
  const cls = (n) => n > 0 ? 'up' : n < 0 ? 'down' : '';

  let H;
  try { H = await (await fetch('data/cb_hist.json', { cache: 'no-cache' })).json(); }
  catch (e) { $('cbh-date').textContent = '尚無紀錄'; return; }
  const all = Object.keys(H.dates).sort();
  if (!all.length) { $('cbh-date').textContent = '尚無紀錄'; return; }
  const first = all[0], last = all[all.length - 1];
  const withHits = all.filter((d) => H.dates[d] > 0);
  let view = last.slice(0, 7), selected = withHits[withHits.length - 1] || last;

  function renderCal() {
    const [y, m] = view.split('-').map(Number);
    $('cbh-title').textContent = `${y} 年 ${m} 月`;
    $('cbh-prev').disabled = view <= first.slice(0, 7);
    $('cbh-next').disabled = view >= last.slice(0, 7);
    const start = new Date(Date.UTC(y, m - 1, 1)).getUTCDay();
    const days = new Date(Date.UTC(y, m, 0)).getUTCDate();
    const maxN = Math.max(1, ...all.filter((d) => d.startsWith(view)).map((d) => H.dates[d]));
    let html = '<span class="cal-empty"></span>'.repeat(start);
    for (let d = 1; d <= days; d++) {
      const key = `${view}-${String(d).padStart(2, '0')}`;
      const n = H.dates[key];
      const c = ['cal-day'];
      if (n == null) c.push('off'); else if (!n) c.push('zero');
      if (key === selected && !query) c.push('sel');
      const heat = n ? 0.18 + 0.5 * Math.sqrt(n / maxN) : 0;
      html += n != null
        ? `<button class="${c.join(' ')}" data-d="${key}" style="--heat:${heat.toFixed(2)}" title="${n} 檔"><b>${d}</b></button>`
        : `<span class="${c.join(' ')}"><b>${d}</b></span>`;
    }
    $('cbh-days').innerHTML = html;
  }

  function rowHtml(d, r) {
    const [c, n, s, sn, m, conv, prev, p, cb] = r;
    const pct = (p / prev - 1) * 100;
    return `<tr><td class="mono muted">${d.slice(5)}</td>
      <td><b>${n}</b><em class="sub">${c}</em></td>
      <td><b>${sn}</b><em class="sub">${s}${m === 'otc' ? ' · 櫃' : ''}</em></td>
      <td class="r mono">${fmt(conv)}</td><td class="r mono hide-sm">${fmt(prev)}</td>
      <td class="r mono b up">${fmt(p)}</td><td class="r mono hide-sm ${cls(pct)}">${sgn(pct)}%</td>
      <td class="r mono hide-sm">${fmt(cb)}</td></tr>`;
  }

  let query = '';
  function renderTable() {
    if (query) {
      const q = query.toLowerCase();
      const hits = [];
      for (const d of [...withHits].reverse()) for (const r of H.rows[d] || []) {
        if ([r[0], r[1], r[2], r[3]].some((x) => String(x).toLowerCase().includes(q))) hits.push(rowHtml(d, r));
      }
      $('cbh-date').textContent = `搜尋「${query}」· ${hits.length} 筆`;
      $('cbh-body').innerHTML = hits.join('') || '<tr><td colspan="8" class="none">2026 年以來沒有符合的突破紀錄</td></tr>';
      return;
    }
    const wk = '日一二三四五六'[new Date(selected + 'T00:00:00+08:00').getDay()];
    const rows = H.rows[selected] || [];
    $('cbh-date').textContent = `${selected}（${wk}）· ${rows.length} 檔`;
    $('cbh-body').innerHTML = rows.map((r) => rowHtml(selected, r)).join('')
      || '<tr><td colspan="8" class="none">當日沒有突破轉換價的標的</td></tr>';
  }

  $('cbh-days').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-d]'); if (!b) return;
    selected = b.dataset.d; query = ''; $('cbh-q').value = ''; renderCal(); renderTable();
  });
  const shift = (k) => {
    const [y, m] = view.split('-').map(Number);
    const d = new Date(Date.UTC(y, m - 1 + k, 1));
    view = `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`; renderCal();
  };
  $('cbh-prev').addEventListener('click', () => shift(-1));
  $('cbh-next').addEventListener('click', () => shift(1));
  $('cbh-q').addEventListener('input', (e) => { query = e.target.value.trim(); renderCal(); renderTable(); });

  view = selected.slice(0, 7);
  renderCal(); renderTable();
})();
