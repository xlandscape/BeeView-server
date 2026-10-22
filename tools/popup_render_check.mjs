// Render check of the parcel popup: select runs, dispatch popup/openPopup through the exposed
// store for a given feature and location, screenshot, then exercise "Pin to chart".
// usage: node tools/popup_render_check.mjs http://localhost:32000/ out_prefix featureId lng lat
import { spawn } from 'node:child_process';
import { writeFileSync } from 'node:fs';

const [, , url = 'http://localhost:32000/', prefix = 'popup_render', featureId = '14580', lng = '1.14391', lat = '44.100361'] = process.argv;
const PORT = 9338;
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--no-first-run',
  `--remote-debugging-port=${PORT}`, '--window-size=1600,1000', '--user-data-dir=' + process.env.TEMP + '/beeview-cdp-popup2', 'about:blank'], { stdio: 'ignore' });
const die = (err) => { console.error(err); try { chrome.kill(); } catch {} process.exit(1); };
process.on('uncaughtException', die); process.on('unhandledRejection', die);
setTimeout(() => die(new Error('timeout')), 240000).unref();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function pageTarget() { for (let i = 0; i < 50; i++) { try { const l = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json(); const p = l.find((t) => t.type === 'page'); if (p) return p; } catch {} await sleep(200); } throw new Error('no page'); }
const page = await pageTarget(); const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
let id = 0; const pending = new Map(); const errors = [];
ws.onmessage = (m) => { const msg = JSON.parse(m.data); if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
  else if (msg.method === 'Runtime.exceptionThrown') errors.push('EXC: ' + msg.params.exceptionDetails.text + ' ' + (msg.params.exceptionDetails.exception?.description || '').split('\n')[0]); };
const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const evaluate = async (e) => (await send('Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: true })).result?.result?.value;
const shot = async (n) => { const r = await send('Page.captureScreenshot', { format: 'png' }); writeFileSync(`${prefix}_${n}.png`, Buffer.from(r.result.data, 'base64')); console.log('screenshot', `${prefix}_${n}.png`); };
await send('Runtime.enable'); await send('Page.enable'); await send('Page.navigate', { url }); await sleep(3000);
await evaluate(`localStorage.removeItem('beeview.ui.v1'); Storage.prototype.setItem = () => {};`);
await send('Page.reload'); await sleep(12000);
// select hive_1360 untreated + Dimethoate
for (const re of ['hive_1360 · untreated', 'hive_1360 · Dimethoate']) {
  await evaluate(`(() => { const c = [...document.querySelectorAll('.view-run-chip')].find(c => c.title.startsWith(${JSON.stringify(re)})); if (c && !c.classList.contains('on')) c.click(); })()`);
  await sleep(500);
}
// zoom the map to the parcel so the popup is readable
await evaluate(`window.__beeviewStore.dispatch({ type: 'map/setViewState', payload: { longitude: ${lng}, latitude: ${lat}, zoom: 14 } })`);
await sleep(2500);
await evaluate(`window.__beeviewStore.dispatch({ type: 'popup/openPopup', payload: { featureId: ${Number(featureId)}, lngLat: [${lng}, ${lat}] } })`);
await sleep(4000);
console.log('state.popup =', await evaluate(`JSON.stringify(window.__beeviewStore.getState().popup)`));
console.log('popup in DOM:', await evaluate(`!!document.querySelector('.maplibregl-popup')`));
console.log('popup text:', await evaluate(`(document.querySelector('.maplibregl-popup')?.textContent || '').replace(/\\s+/g, ' ').slice(0, 600)`));
await shot('popup');
const pinned = await evaluate(`(() => { const b = [...document.querySelectorAll('.maplibregl-popup button')].find(b => /pin/i.test(b.textContent)); if (b) { b.click(); return b.textContent; } return null; })()`);
await sleep(2500);
console.log('pin clicked:', pinned, 'selected =', await evaluate(`JSON.stringify(window.__beeviewStore.getState().selection.selectedFeatureIds)`));
await evaluate(`(() => { const b = [...document.querySelectorAll('.tab-button')].find(b => /Nectar/.test(b.textContent)); b && b.click(); })()`);
await evaluate(`(() => { const l = [...document.querySelectorAll('label')].find(l => /^\\s*Nectar\\s*$/.test(l.textContent)); const i = l && l.querySelector('input'); if (i && !i.checked) i.click(); })()`);
await sleep(3000);
await shot('pinned');
console.log(`${errors.length} errors`); errors.slice(0, 10).forEach((e) => console.log('  ', e));
ws.close(); chrome.kill(); process.exit(0);
