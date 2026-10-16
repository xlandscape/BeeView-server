// Headless-Chrome page-load profile for BeeView via the DevTools protocol.
// usage: node _cdp_profile.mjs http://localhost:32000 out_prefix
import { spawn } from 'node:child_process';
import { writeFileSync } from 'node:fs';

const [, , url = 'http://localhost:32000/', prefix = 'beeview'] = process.argv;
const PORT = 9333;
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';

const chrome = spawn(CHROME, [
  '--headless=new', '--disable-gpu', '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
  '--no-first-run', '--no-default-browser-check', `--remote-debugging-port=${PORT}`,
  '--window-size=1600,1000', '--user-data-dir=' + process.env.TEMP + '/beeview-cdp-profile', 'about:blank',
], { stdio: 'ignore' });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const die = (err) => { console.error(err); try { chrome.kill(); } catch {} process.exit(1); };
process.on('uncaughtException', die);
process.on('unhandledRejection', die);
setTimeout(() => die(new Error('profile timed out after 150 s')), 150000).unref();

async function targets() {
  for (let i = 0; i < 50; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json`);
      const list = await r.json();
      const page = list.find((t) => t.type === 'page');
      if (page) return page;
    } catch {}
    await sleep(200);
  }
  throw new Error('chrome did not expose a page target');
}

const page = await targets();
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });

let id = 0;
const pending = new Map();
const events = [];
ws.onmessage = (m) => {
  const msg = JSON.parse(m.data);
  if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
  else if (msg.method) events.push(msg);
};
const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });

await send('Network.enable');
await send('Page.enable');
await send('Runtime.enable');
await send('Log.enable');
await send('Performance.enable');

const t0 = Date.now();
await send('Page.navigate', { url });

// wait until no network activity for 4 s (or 60 s cap)
let lastNet = Date.now();
const netMethods = new Set(['Network.requestWillBeSent', 'Network.loadingFinished', 'Network.loadingFailed']);
while (Date.now() - t0 < 60000) {
  await sleep(500);
  const latest = events.filter((e) => netMethods.has(e.method)).length;
  if (latest !== lastNet) { lastNet = latest; var lastChange = Date.now(); }
  if (lastChange && Date.now() - lastChange > 4000) break;
}
const loadMs = (lastChange || Date.now()) - t0;

// requests summary
const reqs = new Map();
for (const e of events) {
  if (e.method === 'Network.requestWillBeSent') reqs.set(e.params.requestId, { url: e.params.request.url, start: e.params.timestamp, bytes: 0 });
  if (e.method === 'Network.responseReceived' && reqs.has(e.params.requestId)) {
    const r = reqs.get(e.params.requestId); r.status = e.params.response.status; r.fromCache = e.params.response.fromDiskCache;
  }
  if (e.method === 'Network.loadingFinished' && reqs.has(e.params.requestId)) {
    const r = reqs.get(e.params.requestId); r.bytes = e.params.encodedDataLength; r.end = e.params.timestamp;
  }
  if (e.method === 'Network.loadingFailed' && reqs.has(e.params.requestId)) reqs.get(e.params.requestId).failed = e.params.errorText;
}
const rows = [...reqs.values()].map((r) => ({ ...r, ms: r.end && r.start ? Math.round((r.end - r.start) * 1000) : null }));
rows.sort((a, b) => (b.bytes || 0) - (a.bytes || 0));
console.log(`navigation -> network idle: ${loadMs} ms, ${rows.length} requests, ${(rows.reduce((s, r) => s + (r.bytes || 0), 0) / 1024 / 1024).toFixed(2)} MB on the wire`);
for (const r of rows) console.log(`${String(r.status ?? '-').padStart(4)} ${String(r.ms ?? '-').padStart(6)} ms ${((r.bytes || 0) / 1024).toFixed(1).padStart(9)} KB  ${r.url.replace(url.replace(/\/$/, ''), '')}${r.failed ? '  FAILED ' + r.failed : ''}`);

// console errors / exceptions
const errors = events.filter((e) => (e.method === 'Runtime.exceptionThrown') || (e.method === 'Runtime.consoleAPICalled' && e.params.type === 'error') || (e.method === 'Log.entryAdded' && e.params.entry.level === 'error'));
console.log(`\n${errors.length} console errors/exceptions`);
for (const e of errors.slice(0, 15)) {
  if (e.method === 'Runtime.exceptionThrown') console.log('  EXC', e.params.exceptionDetails.text, e.params.exceptionDetails.exception?.description?.split('\n')[0]);
  else if (e.method === 'Runtime.consoleAPICalled') console.log('  ERR', e.params.args.map((a) => a.value ?? a.description).join(' ').slice(0, 300));
  else console.log('  LOG', e.params.entry.text.slice(0, 300));
}

const metrics = (await send('Performance.getMetrics')).result.metrics;
const pick = (n) => metrics.find((m) => m.name === n)?.value;
console.log(`\nJSHeapUsed ${(pick('JSHeapUsedSize') / 1048576).toFixed(0)} MB, DOM nodes ${pick('Nodes')}, ScriptDuration ${pick('ScriptDuration')?.toFixed(2)} s, LayoutDuration ${pick('LayoutDuration')?.toFixed(2)} s`);

async function shot(name) {
  const r = await send('Page.captureScreenshot', { format: 'png' });
  writeFileSync(`${prefix}_${name}.png`, Buffer.from(r.result.data, 'base64'));
  console.log(`screenshot ${prefix}_${name}.png`);
}
await sleep(1500);
await shot('overview');

// zoom into the map centre via the NavigationControl button to inspect polygon edges
for (let i = 0; i < 5; i++) {
  await send('Runtime.evaluate', { expression: `document.querySelector('.maplibregl-ctrl-zoom-in')?.click()` });
  await sleep(600);
}
await sleep(3000);
await shot('zoomed');

ws.close();
chrome.kill();
process.exit(0);
