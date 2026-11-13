/**
 * 台股即時報價中繼（Cloudflare Worker）
 *
 * 瀏覽器無法直接跨網域讀取證交所即時行情 (mis.twse.com.tw)，
 * 這個 Worker 代為查詢並加上 CORS 標頭，只開放給儀表板網址使用。
 *
 * 用法：GET https://<你的worker>.workers.dev/?codes=2330,2317&otc=6488,3105
 *   codes = 上市代號，otc = 上櫃代號（含 5 碼可轉債）
 *   回傳 { time, ver, quotes: [{ c, n, ex, z, y, b, a, o, h, l, v, t, d }] }
 *   一律附帶加權指數 (c = "t00")
 *
 *       GET https://<你的worker>.workers.dev/broker
 *   櫃買中心「熱門股證券商進出排行」（盤中 10:00、11:00、12:00 更新），快取 2 分鐘
 *
 * 排程：Cloudflare 只需設定 1 條 Cron Trigger，頻率選「每 5 分鐘」（Every 5 minutes），
 * 實際要在幾點觸發哪個 GitHub Actions 由下方 SCHEDULE（台北時間）決定；新增排程只要改這張表。
 * （GitHub 自己的排程常延遲數小時，所以由這裡準時觸發）
 * 需在 Worker 設定 Secret：GH_TOKEN（GitHub fine-grained token，僅此 repo、Actions: Read and write）
 */
const REPO = '1793leo/taiwan-market-dashboard';
const SCHEDULE = [   // [台北時間 HH:MM（需為 5 分鐘的倍數）, 星期（1=一 … 5=五）, workflow]
  ['10:10', [1, 2, 3, 4, 5], 'broker.yml'],   // 櫃買熱門股
  ['11:10', [1, 2, 3, 4, 5], 'broker.yml'],
  ['12:10', [1, 2, 3, 4, 5], 'broker.yml'],
  ['15:40', [1, 2, 3, 4, 5], 'update.yml'],   // 盤後更新
  ['16:05', [1, 2, 3, 4, 5], 'update.yml'],   // 盤後定價交易
  ['17:40', [1, 2, 3, 4, 5], 'update.yml'],   // 盤後補抓
  ['21:05', [1, 2, 3, 4, 5], 'update.yml'],   // 鉅額交易
];

function dueWorkflows(scheduledTime) {
  const t = new Date(scheduledTime + 8 * 3600e3);              // 台北時間
  const hm = `${String(t.getUTCHours()).padStart(2, '0')}:${String(t.getUTCMinutes()).padStart(2, '0')}`;
  const dow = t.getUTCDay();
  return [...new Set(SCHEDULE.filter(([at, days]) => at === hm && days.includes(dow)).map((x) => x[2]))];
}

async function dispatch(workflow, env) {
  if (!env.GH_TOKEN) throw new Error('缺少 GH_TOKEN secret');
  const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${workflow}/dispatches`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${env.GH_TOKEN}`,
      'Accept': 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': 'tw-quote-worker',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ ref: 'main' }),
  });
  if (r.status !== 204) throw new Error(`GitHub ${r.status}: ${(await r.text()).slice(0, 200)}`);
}

const VERSION = 6;
const ALLOWED_ORIGINS = [
  'https://1793leo.github.io',
  'http://localhost:8000',
];
const CACHE_MS = 5000;        // 同一組查詢 5 秒內直接回快取，避免對證交所請求過量
const BATCH = 50;             // 每次向證交所查詢的檔數
const MAX_CODES = 300;

const cache = new Map();

function corsHeaders(origin) {
  const allow = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
  return {
    'Access-Control-Allow-Origin': allow,
    'Access-Control-Allow-Methods': 'GET, OPTIONS',
    'Vary': 'Origin',
  };
}

function parseCodes(s) {
  return [...new Set((s || '').split(','))].filter((c) => /^\d{4,6}$/.test(c));   // 股票 4 碼、可轉債 5 碼
}

async function queryMis(channels) {
  const url = 'https://mis.twse.com.tw/stock/api/getStockInfo.jsp?json=1&delay=0&_=' + Date.now()
    + '&ex_ch=' + encodeURIComponent(channels.join('|'));
  const r = await fetch(url, {
    headers: {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36',
      'Referer': 'https://mis.twse.com.tw/stock/index.jsp',
      'Accept': 'application/json',
    },
  });
  if (!r.ok) throw new Error('TWSE HTTP ' + r.status);
  const j = await r.json();
  return j.msgArray || [];
}

let brokerCache = { time: 0, body: '' };
async function brokerVol(cors) {
  const headers = { ...cors, 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' };
  if (Date.now() - brokerCache.time < 120000) return new Response(brokerCache.body, { headers });
  try {
    const r = await fetch('https://www.tpex.org.tw/www/zh-tw/mostActive/brokerVol', {
      method: 'POST',
      body: 'response=json',
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Referer': 'https://www.tpex.org.tw/zh-tw/mainboard/trading/realtime/broker-vol.html',
        'X-Requested-With': 'XMLHttpRequest',
      },
    });
    const text = await r.text();
    if (!r.ok || !text.trim().startsWith('{')) throw new Error('TPEx HTTP ' + r.status);
    const j = JSON.parse(text);
    const t = (j.tables || [])[0] || {};
    const body = JSON.stringify({ ver: VERSION, time: Date.now(), subtitle: t.subtitle || '', fields: t.fields || [], data: t.data || [] });
    brokerCache = { time: Date.now(), body };
    return new Response(body, { headers });
  } catch (e) {
    return new Response(JSON.stringify({ error: String(e) }), { status: 502, headers });
  }
}

export default {
  async scheduled(event, env, ctx) {
    for (const wf of dueWorkflows(event.scheduledTime)) {
      ctx.waitUntil(dispatch(wf, env)
        .then(() => console.log(`已觸發 ${wf}`))
        .catch((e) => console.log(`觸發 ${wf} 失敗：${e.message}`)));
    }
  },

  async fetch(req, env) {
    const origin = req.headers.get('Origin') || '';
    const cors = corsHeaders(origin);
    if (req.method === 'OPTIONS') return new Response(null, { headers: cors });
    if (origin && !ALLOWED_ORIGINS.includes(origin)) {
      return new Response('forbidden', { status: 403, headers: cors });
    }

    const url = new URL(req.url);
    if (url.pathname.replace(/\/$/, '') === '/broker') return brokerVol(cors);
    // 自我檢查（唯讀，不會觸發任何工作）：版本、時間表、GH_TOKEN 是否有效
    if (url.pathname.replace(/\/$/, '') === '/status') {
      let gh = '未設定 GH_TOKEN';
      if (env.GH_TOKEN) {
        const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/broker.yml`, {
          headers: { 'Authorization': `Bearer ${env.GH_TOKEN}`, 'Accept': 'application/vnd.github+json', 'User-Agent': 'tw-quote-worker' },
        });
        gh = r.status === 200 ? 'OK（權杖有效，可存取 repo）' : `GitHub 回應 ${r.status}（權杖無效或權限不足）`;
      }
      const now = Date.now();
      return new Response(JSON.stringify({ ver: VERSION, github: gh, schedule: SCHEDULE.map((x) => x[0] + ' ' + x[2]),
        due_now: dueWorkflows(now - (now % 300000)) }, null, 2),
        { headers: { ...cors, 'Content-Type': 'application/json; charset=utf-8' } });
    }
    const tse = parseCodes(url.searchParams.get('codes'));
    const otc = parseCodes(url.searchParams.get('otc'));
    const channels = ['tse_t00.tw', ...tse.map((c) => `tse_${c}.tw`), ...otc.map((c) => `otc_${c}.tw`)]
      .slice(0, MAX_CODES + 1);
    const key = channels.join('|');
    const now = Date.now();
    const headers = { ...cors, 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' };

    const hit = cache.get(key);
    if (hit && now - hit.time < CACHE_MS) return new Response(hit.body, { headers });

    const batches = [];
    for (let i = 0; i < channels.length; i += BATCH) batches.push(channels.slice(i, i + BATCH));

    try {
      const results = (await Promise.all(batches.map(queryMis))).flat();
      const quotes = results.map((q) => ({
        c: q.c, n: q.n, ex: q.ex, z: q.z, y: q.y, b: q.b, a: q.a,
        o: q.o, h: q.h, l: q.l, v: q.v, t: q.t, d: q.d,
      }));
      const body = JSON.stringify({ time: now, ver: VERSION, quotes });
      if (cache.size > 20) cache.clear();
      cache.set(key, { time: now, body });
      return new Response(body, { headers });
    } catch (e) {
      return new Response(JSON.stringify({ error: String(e) }), { status: 502, headers });
    }
  },
};
