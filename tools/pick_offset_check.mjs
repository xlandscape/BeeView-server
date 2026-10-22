// Diagnose picking offset and popup stacking: compares deck.gl's viewport with maplibre's,
// reports canvas geometry / z-order, and picks at a few points with window.__deckOverlay.
// usage: node tools/pick_offset_check.mjs http://localhost:32000/ out_prefix [deviceScaleFactor]
import { spawn } from 'node:child_process';
import { writeFileSync } from 'node:fs';

const [, , url = 'http://localhost:32000/', prefix = 'pick_check', dsf = '1'] = process.argv;
const PORT = 9339;
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--no-first-run',
  `--remote-debugging-port=${PORT}`, '--window-size=1600,1000', `--force-device-scale-factor=${dsf}`, '--user-data-dir=' + process.env.TEMP + '/beeview-cdp-pick', 'about:blank'], { stdio: 'ignore' });
const die = (err) => { console.error(err); try { chrome.kill(); } catch {} process.exit(1); };
process.on('uncaughtException', die); process.on('unhandledRejection', die);
setTimeout(() => die(new Error('timeout')), 240000).unref();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function pageTarget() { for (let i = 0; i < 50; i++) { try { const l = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json(); const p = l.find((t) => t.type === 'page'); if (p) return p; } catch {} await sleep(200); } throw new Error('no page'); }
const page = await pageTarget(); const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
let id = 0; const pending = new Map();
ws.onmessage = (m) => { const msg = JSON.parse(m.data); if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); } };
const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const evaluate = async (e) => { const r = await send('Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: true }); return r.result?.result?.value ?? (r.result?.exceptionDetails ? 'EXC ' + r.result.exceptionDetails.text : undefined); };
const shot = async (n) => { const r = await send('Page.captureScreenshot', { format: 'png' }); writeFileSync(`${prefix}_${n}.png`, Buffer.from(r.result.data, 'base64')); console.log('screenshot', `${prefix}_${n}.png`); };
await send('Runtime.enable'); await send('Page.enable'); await send('Page.navigate', { url }); await sleep(14000);

console.log('dpr:', await evaluate('window.devicePixelRatio'));
console.log('geometry:', await evaluate(`(() => {
  const d = window.__deckOverlay && window.__deckOverlay._deck; const map = d && window.__deckOverlay._map;
  const c = d && d.canvas; const r = c && c.getBoundingClientRect(); const mc = map && map.getContainer().getBoundingClientRect();
  const mlc = document.querySelector('.maplibregl-canvas').getBoundingClientRect();
  return JSON.stringify({ deck: d ? { w: d.width, h: d.height, canvasCss: [r.left, r.top, r.width, r.height], canvasPx: [c.width, c.height], parent: c.parentElement.className, z: getComputedStyle(c).zIndex, parentZ: getComputedStyle(c.parentElement).zIndex, pointerEvents: getComputedStyle(c).pointerEvents } : null,
    mapContainer: mc && [mc.left, mc.top, mc.width, mc.height], maplibreCanvas: [mlc.left, mlc.top, mlc.width, mlc.height], padding: map && map.getPadding(),
    canvasContainerChildren: [...document.querySelector('.maplibregl-canvas-container').children].map(e => (e.tagName + '.' + e.className + ' z=' + getComputedStyle(e).zIndex)),
    mapChildren: [...map.getContainer().children].map(e => e.tagName + '.' + e.className + ' z=' + getComputedStyle(e).zIndex) });
})()`));
// viewport comparison at several screen points
console.log('unproject diff (deck vs maplibre), px error:', await evaluate(`(() => {
  const d = window.__deckOverlay._deck, map = window.__deckOverlay._map; const vp = d.getViewports()[0];
  const out = [];
  for (const [x, y] of [[300, 200], [800, 300], [1000, 250], [1100, 450], [600, 500]]) {
    const a = vp.unproject([x, y]); const b = map.unproject([x, y]);
    const back = map.project([a[0], a[1]]);
    out.push({ x, y, deck: [a[0].toFixed(5), a[1].toFixed(5)], ml: [b.lng.toFixed(5), b.lat.toFixed(5)], pxErr: [(back.x - x).toFixed(1), (back.y - y).toFixed(1)] });
  }
  return JSON.stringify(out);
})()`));
// picking test: pick at a point, then project the picked feature's first ring vertex set bbox centre back to screen
console.log('pick test:', await evaluate(`(() => {
  const d = window.__deckOverlay._deck, map = window.__deckOverlay._map; const out = [];
  for (const [x, y] of [[1000, 250], [1050, 300], [950, 320], [1100, 220]]) {
    const info = d.pickObject({ x, y, radius: 0 });
    if (!info || !info.object) { out.push({ x, y, hit: null }); continue; }
    const g = info.object.geometry; const ring = g.type === 'Polygon' ? g.coordinates[0] : g.coordinates[0][0];
    let sx = 0, sy = 0; ring.forEach(([lng, lat]) => { const p = map.project([lng, lat]); sx += p.x; sy += p.y; });
    const cx = sx / ring.length, cy = sy / ring.length;
    const lngLat = map.unproject([x, y]); const inside = (() => { let c = false; for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) { const [xi, yi] = ring[i], [xj, yj] = ring[j]; if (((yi > lngLat.lat) !== (yj > lngLat.lat)) && (lngLat.lng < (xj - xi) * (lngLat.lat - yi) / (yj - yi) + xi)) c = !c; } return c; })();
    out.push({ x, y, id: info.object.id, centroidPx: [cx.toFixed(0), cy.toFixed(0)], cursorInsidePolygon: inside, pickedPx: [info.x, info.y] });
  }
  return JSON.stringify(out);
})()`));
// open popup via store at a cursor position and report stacking
await evaluate(`window.__beeviewStore.dispatch({ type: 'popup/openPopup', payload: { featureId: 14582, lngLat: [1.144182, 44.099287] } })`);
await sleep(2500);
console.log('popup stacking:', await evaluate(`(() => { const p = document.querySelector('.maplibregl-popup'); if (!p) return 'no popup'; const r = p.getBoundingClientRect(); const el = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return JSON.stringify({ popupZ: getComputedStyle(p).zIndex, parent: p.parentElement.className, rect: [r.left, r.top, r.width, r.height], topElementAtCentre: el && (el.tagName + '.' + el.className), popupIsAncestor: !!(el && p.contains(el)) }); })()`));
await shot('popup');
ws.close(); chrome.kill(); process.exit(0);
