// Headless-Chrome check of the Entomology-demo features: MC band, compare side-by-side,
// Colony KPIs tab and the per-parcel popup. Takes screenshots and reports console errors.
// usage: node tools/demo_features_check.mjs http://localhost:32000/ out_prefix
import { spawn } from 'node:child_process';
import { writeFileSync } from 'node:fs';

const [, , url = 'http://localhost:32000/', prefix = 'demo_check', hiveRe = 'hive_1360|hive_2617'] = process.argv;
const HIVES = new RegExp(hiveRe);
const PORT = 9336;
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const profileDir = process.env.TEMP + '/beeview-cdp-demo';

const chrome = spawn(CHROME, [
  '--headless=new', '--disable-gpu', '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
  '--no-first-run', '--no-default-browser-check', `--remote-debugging-port=${PORT}`,
  '--window-size=1600,1000', '--user-data-dir=' + profileDir, 'about:blank',
], { stdio: 'ignore' });
const die = (err) => { console.error(err); try { chrome.kill(); } catch {} process.exit(1); };
process.on('uncaughtException', die);
process.on('unhandledRejection', die);
setTimeout(() => die(new Error('timed out after 600 s')), 600000).unref();

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function pageTarget() {
  for (let i = 0; i < 50; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json();
      const page = list.find((t) => t.type === 'page');
      if (page) return page;
    } catch {}
    await sleep(200);
  }
  throw new Error('no page target');
}
const page = await pageTarget();
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
let id = 0; const pending = new Map(); const errors = [];
ws.onmessage = (m) => {
  const msg = JSON.parse(m.data);
  if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
  else if (msg.method === 'Runtime.exceptionThrown') errors.push(msg.params.exceptionDetails.text + ' ' + (msg.params.exceptionDetails.exception?.description || '').split('\n')[0]);
  else if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') errors.push(msg.params.args.map((a) => a.value ?? a.description).join(' ').slice(0, 300));
};
const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const evaluate = async (expression) => (await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })).result?.result?.value;
const shot = async (name) => { const r = await send('Page.captureScreenshot', { format: 'png' }); writeFileSync(`${prefix}_${name}.png`, Buffer.from(r.result.data, 'base64')); console.log('screenshot', `${prefix}_${name}.png`); };
const clickTab = async (text) => evaluate(`(() => { const b = [...document.querySelectorAll('.tab-button')].find(b => b.textContent.includes(${JSON.stringify(text)})); if (!b) return 'no tab ' + ${JSON.stringify(text)}; b.click(); return 'clicked ' + b.textContent; })()`);
const waitFor = async (expr, ms = 30000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await evaluate(expr)) return true; await sleep(500); } return false; };

await send('Runtime.enable'); await send('Page.enable');
await send('Page.navigate', { url });
await sleep(3000);
await evaluate(`localStorage.removeItem('beeview.ui.v1'); Storage.prototype.setItem = () => {};`);
await send('Page.reload');
console.log('runs picker ready:', await waitFor(`document.querySelectorAll('.view-run-chip').length > 0`, 60000));
console.log('map features ready:', await waitFor(`document.querySelector('.maplibregl-canvas') && !document.body.textContent.includes('Loading landscape')`, 60000));
await sleep(4000);
console.log('chips:', await evaluate(`[...document.querySelectorAll('.view-run-chip')].map(c => c.title).slice(0, 20).join(' | ')`));

// select hive_1360 and hive_2617, all variants
// chips compute the new selection from render-time state, so click them one at a time
const chipTitles = await evaluate(`[...document.querySelectorAll('.view-run-chip')].map(c => c.title)`);
for (const t of chipTitles) {
  if (!HIVES.test(t)) continue;
  await evaluate(`(() => { const c = [...document.querySelectorAll('.view-run-chip')].find(c => c.title === ${JSON.stringify(t)}); if (c && !c.classList.contains('on')) c.click(); })()`);
  await sleep(400);
}
console.log('chips on:', await evaluate(`[...document.querySelectorAll('.view-run-chip.on')].map(c => c.title.split(' · ').slice(0,2).join(' ')).join(' | ')`));
// colony metric layer must be visible for the Bee Population tab
await evaluate(`(() => { const l = [...document.querySelectorAll('label')].find(l => /Total Colony/.test(l.textContent)); const i = l && l.querySelector('input'); if (i && !i.checked) i.click(); return !!i; })()`);
await sleep(1500);

// 1 Bee Population with band mode
console.log(await clickTab('Bee Population'));
await sleep(1500);
console.log('mode buttons:', await evaluate(`[...document.querySelectorAll('.mode-button')].map(b => b.textContent + (b.getAttribute('aria-pressed')==='true'?'*':'')).join(', ')`));
await evaluate(`(() => { const b = [...document.querySelectorAll('.mode-button')].find(b => /Band/i.test(b.textContent)); if (b) b.click(); })()`);
console.log('bands drawn:', await waitFor(`!document.body.textContent.includes('Loading per-run replicate data') && document.querySelectorAll('svg path').length > 4`, 90000));
await sleep(2500);
await shot('band');

// 2 Compare side by side
console.log(await clickTab('Compare'));
console.log('compare toolbar:', await waitFor(`!!document.querySelector('.compare-toolbar')`, 30000));
await sleep(1000);
console.log('compare selects:', await evaluate(`[...document.querySelectorAll('.compare-toolbar select')].map(s => s.options[s.selectedIndex]?.text + ' [' + s.options.length + ']').join(' | ')`));
console.log('compare panels drawn:', await waitFor(`document.querySelectorAll('.compare-toolbar ~ * svg, .compare-toolbar + * svg').length >= 1 || document.querySelectorAll('svg path').length > 8`, 60000));
await sleep(2500);
await shot('compare');

// 3 Colony KPIs
console.log(await clickTab('KPI'));
console.log('kpi panel:', await waitFor(`document.querySelector('.kpi-panel') && document.querySelectorAll('.kpi-tile__value').length > 0`, 60000));
await sleep(1500);
console.log('kpi tiles:', await evaluate(`[...document.querySelectorAll('.kpi-tile')].map(t => t.querySelector('.kpi-tile__label')?.textContent + '=' + t.querySelector('.kpi-tile__value')?.textContent).join(' | ')`));
console.log('kpi charts drawn:', await waitFor(`document.querySelectorAll('.kpi-panel svg path').length > 2`, 60000));
await sleep(2500);
await shot('kpi');

// 4 Parcel popup: click on the map canvas near the hive location
console.log(await clickTab('Nectar'));
await sleep(800);
const rect = await evaluate(`(() => { const c = document.querySelector('.maplibregl-canvas'); const r = c.getBoundingClientRect(); return { x: r.left + r.width * 0.79, y: r.top + r.height * 0.34 }; })()`);
let popup = false;
for (const [dx, dy] of [[0, 0], [30, 25], [-40, 15], [50, -30], [-60, -25], [80, 50], [-20, 60], [20, -60]]) {
  const x = rect.x + dx, y = rect.y + dy;
  await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y });
  await send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 });
  await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 });
  await sleep(1500);
  popup = await evaluate(`!!document.querySelector('.maplibregl-popup')`);
  if (popup) break;
}
console.log('popup open:', popup);
console.log('popup text:', (await evaluate(`document.querySelector('.maplibregl-popup')?.textContent?.slice(0, 400)`)) || '');
await sleep(2000);
await shot('popup');
await evaluate(`(() => { const b = [...document.querySelectorAll('.maplibregl-popup button')].find(b => /pin/i.test(b.textContent)); if (b) b.click(); return !!b; })()`);
await sleep(1500);
await shot('popup_pinned');

console.log(`${errors.length} console errors`); errors.slice(0, 15).forEach((e) => console.log('  ', e));
ws.close(); chrome.kill(); process.exit(0);
