// 從元大投信 PCF 頁面 HTML（stdin）取出 window.__NUXT__ 內的 pcfData，輸出 JSON
const vm = require('vm');
let html = '';
process.stdin.on('data', (d) => { html += d; });
process.stdin.on('end', () => {
  const m = html.match(/<script>(window\.__NUXT__=[\s\S]*?)<\/script>/);
  if (!m) { console.error('NO_NUXT'); process.exit(2); }
  const ctx = { window: {} };
  vm.runInNewContext(m[1], ctx, { timeout: 5000 });
  const data = ctx.window.__NUXT__.data || [];
  const pcf = (data.find((x) => x && x.pcfData) || {}).pcfData;
  if (!pcf) { console.error('NO_PCF'); process.exit(3); }
  process.stdout.write(JSON.stringify(pcf));
});
