(async function () {
  const $ = (id) => document.getElementById(id);
  const fmt = (n, d = 0) => n == null || Number.isNaN(n) ? '—' : n.toLocaleString('zh-TW', { minimumFractionDigits: d, maximumFractionDigits: d });
  const yi = (v) => { const x = v / 1e8; return (x >= 100 ? fmt(x, 0) : fmt(x, 1)) + ' 億'; };

  let dates;
  try { dates = await (await fetch('data/post_dates.json', { cache: 'no-cache' })).json(); }
  catch (e) { $('pt-date').textContent = '尚無盤後交易資料'; return; }
  if (!dates.length) { $('pt-date').textContent = '尚無盤後交易資料'; return; }

  const sel = $('pt-sel');
  sel.innerHTML = [...dates].reverse().map((d) => `<option value="${d}">${d}</option>`).join('');
  const cache = {};

  function rows(list) {
    return list.map((r, k) => `<tr>
      <td class="muted mono">${k + 1}</td>
      <td><b>${r.n}</b><em class="sub">${r.c}${r.m === 'otc' ? ' · 櫃' : ''}</em></td>
      <td class="r mono">${fmt(r.p, 2)}${r.t ? '' : '<em class="sub">未成交</em>'}</td>
      <td class="r mono">${fmt(r.u)}</td>
      <td class="r mono b">${fmt(r.v / 1e4)}</td>
    </tr>`).join('') || '<tr><td colspan="5" class="none">無資料</td></tr>';
  }

  async function show(d) {
    if (!cache[d]) cache[d] = await (await fetch(`data/post/${d}.json`, { cache: 'no-cache' })).json();
    const j = cache[d];
    const wk = '日一二三四五六'[new Date(d + 'T00:00:00+08:00').getDay()];
    $('pt-date').textContent = `盤後 · ${d}（${wk}）`;
    $('pt-bt').textContent = yi(j.buy_total);
    $('pt-at').textContent = yi(j.sell_total);
    const ratio = j.sell_total ? j.buy_total / j.sell_total : null;
    $('pt-ratio').textContent = ratio == null ? '—' : fmt(ratio, 2) + ' 倍';
    $('pt-ratio').className = 'v ' + (ratio > 1 ? 'up' : ratio < 1 ? 'down' : '');
    $('pt-buy').innerHTML = rows(j.buy);
    $('pt-sell').innerHTML = rows(j.sell);

    // 漲停板
    const L = j.limit || [];
    const tse = L.filter((r) => r.m === 'tse').length;
    $('lu-n').textContent = `${L.length} 家`;
    $('lu-nsub').textContent = `上市 ${tse} · 上櫃 ${L.length - tse}`;
    $('lu-bv').textContent = yi(L.reduce((a, r) => a + r.bv, 0));
    $('lu-top').textContent = L[0] ? L[0].n : '—';
    $('lu-topsub').textContent = L[0] ? `${fmt(L[0].bid)} 張 · ${yi(L[0].bv)}` : '—';
    $('lu-body').innerHTML = L.map((r, k) => `<tr>
      <td class="muted mono">${k + 1}</td>
      <td><b>${r.n}</b><em class="sub">${r.c}${r.m === 'otc' ? ' · 櫃' : ''}</em></td>
      <td class="r mono up b">${fmt(r.p, 2)}</td><td class="r mono up">+${fmt(r.pct, 2)}%</td>
      <td class="r mono">${fmt(r.bid)}</td><td class="r mono b">${fmt(r.bv / 1e4)}</td>
      <td class="r mono hide-sm">${fmt(r.ask)}</td><td class="r mono hide-sm">${fmt(r.vol)}</td>
    </tr>`).join('') || '<tr><td colspan="8" class="none">當日沒有漲停的普通股</td></tr>';
  }
  document.querySelectorAll('#pt-sub button').forEach((b) => b.addEventListener('click', () => {
    document.querySelectorAll('#pt-sub button').forEach((x) => x.classList.toggle('on', x === b));
    $('pt-rank').hidden = b.dataset.s !== 'rank';
    $('pt-limit').hidden = b.dataset.s !== 'limit';
  }));
  sel.addEventListener('change', () => show(sel.value));
  show(dates[dates.length - 1]);
})();
