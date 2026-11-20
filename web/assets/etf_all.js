// ETF 持股總表：以個股為主體，加總所有追蹤 ETF 的持股張數與當日增減
(function () {
  const $ = (id) => document.getElementById(id);
  const fmt = (n, d = 0) => n == null ? '—' : n.toLocaleString('zh-TW', { minimumFractionDigits: d, maximumFractionDigits: d });
  const lots = (q) => q == null ? '—' : fmt(q / 1000, Math.abs(q) % 1000 && Math.abs(q) < 100000 ? 1 : 0);
  const sgn = (q) => q == null ? '<span class="muted">—</span>' : q === 0 ? '<span class="muted">0</span>'
    : `<span class="${q > 0 ? 'up' : 'down'}">${q > 0 ? '+' : '−'}${lots(Math.abs(q))}</span>`;
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);

  let loaded = false, doc = null, names = {}, open = new Set();
  let sortKey = '2', sortDir = -1;

  async function init() {
    if (loaded) return;
    loaded = true;
    try {
      const dates = await (await fetch('data/etf/holdings/index.json', { cache: 'no-cache' })).json();
      const wk = (d) => '日一二三四五六'[new Date(d + 'T00:00:00+08:00').getDay()];
      $('ea-date').innerHTML = [...dates].reverse().map((d) => `<option value="${d}">${d}（${wk(d)}）</option>`).join('');
      $('ea-date').addEventListener('change', () => load($('ea-date').value));
      if (dates.length) await load(dates[dates.length - 1]);
    } catch (e) {
      $('ea-body').innerHTML = '<tr><td colspan="7" class="none">尚無資料</td></tr>';
    }
  }

  async function load(d) {
    doc = await (await fetch(`data/etf/holdings/${d}.json`, { cache: 'no-cache' })).json();
    names = Object.fromEntries(doc.etfs.map((e) => [e[0], e[1]]));
    open = new Set();
    const stale = doc.etfs.filter((e) => e[3] !== 'upd');
    $('ea-cover').innerHTML = `${doc.etfs.length} 檔 ETF` + (stale.length
      ? ` · <span class="ea-stale">未計增減：${stale.map((e) => `${e[0]}（${e[3] === 'first' ? '首筆紀錄' : '資料至 ' + e[2].slice(5).replace('-', '/')}）`).join('、')}</span>`
      : ' · 皆已更新');
    const held = doc.rows.filter((r) => r[2] > 0);
    $('ea-n').textContent = `${held.length} 檔`;
    $('ea-nsub').textContent = `${doc.etfs.length} 檔 ETF 的股票持股`;
    const up = doc.rows.reduce((a, r) => (r[3] != null && r[3] > 0 && (!a || r[3] > a[3]) ? r : a), null);
    const dn = doc.rows.reduce((a, r) => (r[3] != null && r[3] < 0 && (!a || r[3] < a[3]) ? r : a), null);
    $('ea-up').textContent = up ? up[1] : '—';
    $('ea-upsub').innerHTML = up ? `${up[0]} · ${sgn(up[3])} 張` : '—';
    $('ea-dn').textContent = dn ? dn[1] : '—';
    $('ea-dnsub').innerHTML = dn ? `${dn[0]} · ${sgn(dn[3])} 張` : '—';
    render();
  }

  function pct(r) {
    if (r[3] == null) return null;
    const before = r[2] - r[3];
    return before > 0 ? r[3] / before * 100 : (r[3] > 0 ? Infinity : null);
  }

  function render() {
    if (!doc) return;
    const q = $('ea-q').value.trim().toLowerCase();
    const onlyChg = $('ea-chg').checked;
    let rows = doc.rows.map((r, i) => ({ r, i }));
    if (q) rows = rows.filter(({ r }) => r[0].toLowerCase().includes(q) || r[1].toLowerCase().includes(q));
    if (onlyChg) rows = rows.filter(({ r }) => r[3]);
    const val = ({ r, i }) => sortKey === 'i' ? i : sortKey === 'p' ? pct(r) : r[+sortKey];
    rows.sort((a, b) => {
      const x = val(a), y = val(b);
      if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1;
      return (typeof x === 'number' ? x - y : String(x).localeCompare(String(y), 'zh-TW')) * sortDir;
    });
    document.querySelectorAll('.ea-table th').forEach((th) => {
      th.classList.toggle('on', th.dataset.k === sortKey);
      th.dataset.dir = th.dataset.k === sortKey ? (sortDir > 0 ? '▲' : '▼') : '';
    });
    $('ea-body').innerHTML = rows.length ? rows.map(({ r, i }, k) => {
      const p = pct(r);
      const ptxt = p == null ? '—' : p === Infinity ? '新增' : `<span class="${p > 0 ? 'up' : p < 0 ? 'down' : 'muted'}">${p > 0 ? '+' : ''}${fmt(p, 2)}%</span>`;
      const det = open.has(r[0]) ? `<tr class="ea-det"><td colspan="7"><table class="ea-sub">${r[5].map((b) => `<tr>
          <td><b>${b[0]}</b> <span class="muted">${esc(names[b[0]] || '')}</span></td>
          <td class="r mono">${lots(b[1])} 張</td><td class="r mono">${sgn(b[2])}</td></tr>`).join('')}</table></td></tr>` : '';
      return `<tr class="ea-row${open.has(r[0]) ? ' open' : ''}" data-c="${r[0]}">
        <td class="muted">${k + 1}</td><td class="mono hide-sm">${r[0]}</td><td><b>${esc(r[1])}</b><em class="sm-code">${r[0]}</em></td>
        <td class="r mono hide-sm">${r[4]}</td><td class="r mono b">${lots(r[2])}</td><td class="r mono b">${sgn(r[3])}</td>
        <td class="r mono hide-sm">${ptxt}</td></tr>${det}`;
    }).join('') : '<tr><td colspan="7" class="none">沒有符合的個股</td></tr>';
  }

  $('ea-body').addEventListener('click', (e) => {
    const tr = e.target.closest('tr.ea-row');
    if (!tr) return;
    const c = tr.dataset.c;
    open.has(c) ? open.delete(c) : open.add(c);
    render();
  });
  document.querySelectorAll('.ea-table th').forEach((th) => th.addEventListener('click', () => {
    const k = th.dataset.k;
    if (k === sortKey) sortDir = -sortDir; else { sortKey = k; sortDir = ['0', '1', 'i'].includes(k) ? 1 : -1; }
    render();
  }));
  $('ea-q').addEventListener('input', render);
  $('ea-chg').addEventListener('change', render);

  // 子分頁切換：持股總表時隱藏單一 ETF 的選單、卡片與日曆
  document.querySelectorAll('#etf-sub button').forEach((b) => b.addEventListener('click', () => {
    const all = b.dataset.s === 'all';
    $('etf-all').hidden = !all;
    document.querySelector('#tab-etf > .etf-cards').hidden = all;
    document.querySelector('#tab-etf > .bk-layout').hidden = all;
    ['etf-sel', 'etf-date', 'etf-upd'].forEach((id) => { $(id).hidden = all; });
    if (all) init();
  }));
})();
