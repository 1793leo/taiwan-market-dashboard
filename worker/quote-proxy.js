/**
 * 台股即時報價中繼（Cloudflare Worker）
 *
 * 瀏覽器無法直接跨網域讀取證交所即時行情 (mis.twse.com.tw)，
 * 這個 Worker 代為查詢並加上 CORS 標頭，只開放給儀表板網址使用。
 *
 * 用法：GET https://<你的worker>.workers.dev/?codes=2330,2317&otc=6488,3105
 *   codes = 上市代號，otc = 上櫃代號
 *   回傳 { time, ver, quotes: [{ c, n, ex, z, y, b, a, o, h, l, v, t, d }] }
 *   一律附帶加權指數 (c = "t00")
 */

const VERSION = 2;
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
  return [...new Set((s || '').split(','))].filter((c) => /^\d{4}$/.test(c));
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

export default {
  async fetch(req) {
    const origin = req.headers.get('Origin') || '';
    const cors = corsHeaders(origin);
    if (req.method === 'OPTIONS') return new Response(null, { headers: cors });
    if (origin && !ALLOWED_ORIGINS.includes(origin)) {
      return new Response('forbidden', { status: 403, headers: cors });
    }

    const url = new URL(req.url);
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
