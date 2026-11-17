(async function () {
  const $ = (id) => document.getElementById(id);
  const fmt = (n, d = 0) => n == null || Number.isNaN(n) ? '—' : n.toLocaleString('zh-TW', { minimumFractionDigits: d, maximumFractionDigits: d });
  const sgn = (n, d = 0) => n == null ? '—' : (n > 0 ? '+' : n < 0 ? '−' : '') + fmt(Math.abs(n), d);
  const cls = (n) => n > 0 ? 'up' : n < 0 ? 'down' : '';
  const yi = (v) => { const x = v / 1e8; return (x >= 1000 ? fmt(x, 0) : fmt(x, 1)) + ' 億'; };

  const CODES = ['0050'];
  const sel = $('etf-sel');
  sel.innerHTML = CODES.map((c) => `<option value="${c}">${c}</option>`).join('');

  let idx = null, code = CODES[0], view = '', selected = '', doc = null;
  let sortKey = 'w', sortDir = -1;
  const cache = {};

  async function loadIndex() {
    try { idx = await (await fetch(`data/etf/${code}/index.json`, { cache: 'no-cache' })).json(); }
    catch (e) { idx = null; $('etf-date').textContent = '尚無紀錄'; return; }
    sel.options[sel.selectedIndex].textContent = `${code} ${idx.name || ''}`;
    selected = idx.dates[idx.dates.length - 1];
    view = selected.slice(0, 7);
    await show(selected);
  }

  function renderCal() {
    const all = idx.dates, first = all[0], last = all[all.length - 1], have = new Set(all);
    const [y, m] = view.split('-').map(Number);
    $('etf-title').textContent = `${y} 年 ${m} 月`;
    $('etf-prev').disabled = view <= first.slice(0, 7);
    $('etf-next').disabled = view >= last.slice(0, 7);
    const start = new Date(Date.UTC(y, m - 1, 1)).getUTCDay(), days = new Date(Date.UTC(y, m, 0)).getUTCDate();
    let html = '<span class="cal-empty"></span>'.repeat(start);
    for (let d = 1; d <= days; d++) {
      const key = `${view}-${String(d).padStart(2, '0')}`;
      html += have.has(key)
        ? `<button class="cal-day ${key === selected ? 'sel' : ''}" data-d="${key}" style="--heat:.25"><b>${d}</b></button>`
        : `<span class="cal-day off"><b>${d}</b></span>`;
    }
    $('etf-days').innerHTML = html;
  }

  async function show(d) {
    selected = d; view = d.slice(0, 7); renderCal();
    const key = `${code}/${d}`;
    if (!cache[key]) cache[key] = await (await fetch(`data/etf/${code}/${d}.json`, { cache: 'no-cache' })).json();
    doc = cache[key];
    const s = doc.summary;
    const wk = '日一二三四五六'[new Date(d + 'T00:00:00+08:00').getDay()];
    $('etf-date').textContent = `${d}（${wk}）`;
    $('etf-upd').textContent = doc.updated ? `元大上傳 ${doc.updated}` : '';
    $('etf-av').textContent = yi(s.totalav);
    $('etf-avsub').textContent = `股票 ${yi(s.stkvalues || 0)} · 期貨 ${yi(s.futvalues || 0)}`;
    $('etf-nav').textContent = fmt(s.nav, 2);
    $('etf-navsub').textContent = '新台幣';
    $('etf-os').textContent = fmt(s.osunit / 1e8, 2) + ' 億單位';
    $('etf-ossub').textContent = `${fmt(s.osunit)} 單位`;
    const flow = s.issuesdiff, units = s.baseunit ? flow / s.baseunit : null;
    $('etf-flow').textContent = flow == null ? '—' : (flow > 0 ? '淨申購 ' : flow < 0 ? '淨贖回 ' : '持平 ') + (Math.abs(flow) >= 1e8 ? fmt(Math.abs(flow) / 1e8, 2) + ' 億單位' : fmt(Math.abs(flow) / 1e4, 0) + ' 萬單位');
    $('etf-flow').className = 'v ' + cls(flow);
    $('etf-flowsub').textContent = flow ? `${fmt(Math.abs(units), 0)} 個申購單位 · 約 ${yi(Math.abs(flow) * s.nav)}` : '—';
    $('etf-ben').textContent = s.beneficiaries ? fmt(s.beneficiaries) + ' 人' : '—';
    $('etf-bensub').textContent = s.ben_month ? `${s.ben_month.slice(0, 4)}/${s.ben_month.slice(4, 6)} 月底` : '—';
    renderStocks(); renderPcf();
  }

  function renderStocks() {
    const first = !doc.prev_date;
    const rows = doc.stocks.map((s, i) => ({ ...s, i: i + 1 }));
    rows.sort((a, b) => {
      const x = a[sortKey], y = b[sortKey];
      if (x == null || y == null) return x == null ? 1 : -1;
      return (typeof x === 'number' ? x - y : String(x).localeCompare(String(y), 'zh-TW')) * sortDir;
    });
    document.querySelectorAll('.etf-table th').forEach((th) => {
      th.classList.toggle('on', th.dataset.k === sortKey);
      th.dataset.dir = th.dataset.k === sortKey ? (sortDir > 0 ? '▲' : '▼') : '';
    });
    $('etf-stocks').innerHTML = rows.map((s) => `<tr class="${s.new ? 'etf-new' : ''}">
      <td class="muted mono">${s.i}</td><td class="mono hide-sm">${s.c}</td>
      <td><b>${s.n}</b>${s.new ? '<span class="drop-tag" style="background:var(--up)">新增</span>' : ''}<em class="sm-code">${s.c}</em></td>
      <td class="r mono">${fmt(s.q)}</td><td class="r mono b">${fmt(s.w, 2)}</td>
      <td class="r mono ${cls(s.dq)}">${first ? '—' : sgn(s.dq)}</td>
      <td class="r mono hide-sm ${cls(s.dw)}">${first ? '—' : sgn(s.dw, 2)}</td></tr>`).join('');
    $('etf-removed').innerHTML = (doc.removed || []).length
      ? `<p class="note"><b class="down">本日剔除：</b>${doc.removed.map((r) => `${r.n}（${r.c}）`).join('、')}</p>` : '';
    $('etf-fut').innerHTML = doc.futures.map((f) => `<tr><td><b>${f.n}</b><em class="sub">${f.c}</em></td>
      <td class="mono">${f.ym ? f.ym.slice(0, 4) + '/' + f.ym.slice(4) : '—'}</td><td class="r mono">${fmt(f.q)}</td><td class="r mono">${fmt(f.w, 2)}</td></tr>`).join('')
      || '<tr><td colspan="4" class="none">無期貨部位</td></tr>';
    if (first) $('etf-removed').innerHTML += '<p class="note">這是第一筆紀錄，股數增減與權重變化從下一個交易日開始顯示。</p>';
  }

  function renderPcf() {
    const s = doc.summary, a = doc.ann_date || '';
    const item = (k, v) => `<div><span>${k}</span><b>${v}</b></div>`;
    $('etf-pcfinfo').innerHTML = `<div class="etf-grid">
      ${item('公告日期（適用申購日）', a ? `${a.slice(0, 4)}/${a.slice(4, 6)}/${a.slice(6)}` : '—')}
      ${item('每實物申購單位之受益權單位數', fmt(s.baseunit))}
      ${item('每實物申購單位約當市值', 'NTD ' + fmt(s.estcvalue))}
      ${item('每實物申購單位估計現金差額', 'NTD ' + fmt(s.estdvalue))}
      ${item('每實物申購單位實際現金差額（前一日）', 'NTD ' + fmt(s.cashdiff))}
      ${item('與前日已發行單位差異數', sgn(s.issuesdiff))}
    </div>`;
    $('etf-kind').innerHTML = doc.inkind.map((k, i) => `<tr><td class="muted mono">${i + 1}</td><td class="mono">${k.c}</td><td><b>${k.n}</b></td>
      <td class="r mono">${fmt(k.q)}</td><td class="r">${k.cash === 'Y' ? '<span class="up">是</span>' : '否'}</td><td class="r">${k.min === 'Y' ? '是' : '否'}</td></tr>`).join('');
  }

  $('etf-days').addEventListener('click', (e) => { const b = e.target.closest('button[data-d]'); if (b) show(b.dataset.d); });
  const shift = (k) => { const [y, m] = view.split('-').map(Number); const d = new Date(Date.UTC(y, m - 1 + k, 1));
    view = `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`; renderCal(); };
  $('etf-prev').addEventListener('click', () => shift(-1));
  $('etf-next').addEventListener('click', () => shift(1));
  document.querySelectorAll('.etf-table th').forEach((th) => th.addEventListener('click', () => {
    const k = th.dataset.k; if (k === sortKey) sortDir = -sortDir; else { sortKey = k; sortDir = ['c', 'n', 'i'].includes(k) ? 1 : -1; }
    renderStocks();
  }));
  document.querySelectorAll('#etf-sub button').forEach((b) => b.addEventListener('click', () => {
    document.querySelectorAll('#etf-sub button').forEach((x) => x.classList.toggle('on', x === b));
    $('etf-hold').hidden = b.dataset.s !== 'hold'; $('etf-pcf').hidden = b.dataset.s !== 'pcf';
  }));
  sel.addEventListener('change', () => { code = sel.value; loadIndex(); });
  loadIndex();
})();
