// Checks that deck.gl's viewport agrees with maplibre's under the overlay padding, so a
// hive placed by clicking lands where the click was. Compares deck.unproject and
// map.unproject for several pixels, with the simulation panel open and closed, and
// performs one real placement click. Run with DPR via --dpr 1.5.
// usage: node tools/placement_check.mjs http://localhost:32000/ [--dpr 1.5] [--size 1920x1080]
import { spawn } from 'node:child_process';

const args = process.argv.slice(2);
const url = args.find((a) => a.startsWith('http')) || 'http://localhost:32000/';
const dpr = args.includes('--dpr') ? args[args.indexOf('--dpr') + 1] : '1';
const size = args.includes('--size') ? args[args.indexOf('--size') + 1] : '1600,1000';
const PORT = 9335;
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--no-first-run',
  `--remote-debugging-port=${PORT}`, `--window-size=${size.replace('x', ',')}`, `--force-device-scale-factor=${dpr}`,
  '--user-data-dir=' + process.env.TEMP + '/beeview-cdp-place', 'about:blank'], { stdio: 'ignore' });
const die = (e) => { console.error(e); try { chrome.kill(); } catch {} process.exit(1); };
process.on('uncaughtException', die); process.on('unhandledRejection', die);
setTimeout(() => die(new Error('timeout')), 150000).unref();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let page; for (let i = 0; i < 50 && !page; i++) { try { page = (await (await fetch(`http://127.0.0.1:${PORT}/json`)).json()).find((t) => t.type === 'page'); } catch {} if (!page) await sleep(200); }
const ws = new WebSocket(page.webSocketDebuggerUrl); await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
let id = 0; const pending = new Map();
ws.onmessage = (m) => { const msg = JSON.parse(m.data); if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); } };
const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const evaluate = async (expression) => { const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true }); if (r.result?.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0, 500)); return r.result?.result?.value; };

await send('Page.enable'); await send('Runtime.enable');
await send('Page.navigate', { url }); await sleep(6000);

// the map may still be mounting on a cold cache: retry the discovery
let discovered = null;
for (let i = 0; i < 20 && !discovered; i++) {
  try {
    discovered = await evaluate(`(() => {
  const root = document.getElementById('root');
  const key = Object.keys(root).find((k) => k.startsWith('__reactContainer$'));
  const walk = (fiber, pred, seen = new Set()) => { if (!fiber || seen.has(fiber)) return null; seen.add(fiber); if (pred(fiber)) return fiber; return walk(fiber.child, pred, seen) || walk(fiber.sibling, pred, seen); };
  window.__store = walk(root[key], (f) => f.memoizedProps && f.memoizedProps.store && f.memoizedProps.store.dispatch).memoizedProps.store;
  window.__map = walk(root[key], (f) => f.memoizedProps && f.memoizedProps.value && f.memoizedProps.value.map && f.memoizedProps.value.map.getMap).memoizedProps.value.map.getMap();
  window.__overlay = window.__map._controls.find((c) => c._deck);
  return window.__overlay && window.__overlay._deck ? 'ok' : null;
})()`);
  } catch (e) { discovered = null; if (i === 19) console.error("discovery:", String(e).slice(0, 300)); }
  if (!discovered) await sleep(1500);
}
if (!discovered) throw new Error('store/map not found');
await sleep(2000);

async function compare(label) {
  await sleep(600);
  const r = await evaluate(`(() => {
    const canvas = document.querySelector('.maplibregl-canvas'); const b = canvas.getBoundingClientRect();
    const vp = window.__overlay._deck.getViewports()[0];
    const pts = [[0.3,0.3],[0.5,0.5],[0.7,0.6],[0.85,0.8]].map(([fx,fy]) => {
      const px = b.width * fx, py = b.height * fy;
      const m = window.__map.unproject([px, py]); const d = vp.unproject([px, py]);
      const back = window.__map.project([d[0], d[1]]);
      return { px: Math.round(px), py: Math.round(py), dxPx: Math.round(back.x - px), dyPx: Math.round(back.y - py) };
    });
    return { dpr: window.devicePixelRatio, padding: window.__map.getPadding(), deckSize: [vp.width, vp.height], canvas: [Math.round(b.width), Math.round(b.height)], pts };
  })()`);
  console.log(label, JSON.stringify(r));
}

await compare('panel closed');
// window resize after load (user maximises the browser): does deck follow maplibre?
const { result: { windowId } } = await send('Browser.getWindowForTarget');
await send('Browser.setWindowBounds', { windowId, bounds: { width: 1300, height: 800 } });
await sleep(1500);
await compare('after shrink ');
await send('Browser.setWindowBounds', { windowId, bounds: { width: 2000, height: 1207 } });
await sleep(1500);
await compare('after grow   ');
await evaluate(`window.__store.dispatch({ type: 'simulation/toggleSimulationPanel' }); window.__store.dispatch({ type: 'simulation/setHivePlacementMode', payload: true }); 'ok'`);
await compare('panel open   ');

// emulate the user's situation: left drawer 300 px, map centred and zoomed on the scenario, click its centre
await evaluate(`window.__store.dispatch({ type: 'ui/setDrawerSize', payload: { side: 'left', size: 300 } }); window.__map.jumpTo({ center: [1.1445, 44.1105], zoom: 10.3 }); 'ok'`);
await sleep(1500);
await compare('user layout  ');
const centre = await evaluate(`(() => { const b = document.querySelector('.maplibregl-canvas').getBoundingClientRect(); const p = window.__map.project([1.1445, 44.1105]); return { px: Math.round(p.x + b.left), py: Math.round(p.y + b.top) }; })()`);
await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: centre.px, y: centre.py, button: 'left', clickCount: 1 });
await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: centre.px, y: centre.py, button: 'left', clickCount: 1 });
await sleep(800);
const fc = await evaluate(`(() => { const f = window.__store.getState().simulation.form; return { x: Number(f.BeeHaveMapCenterPointX), y: Number(f.BeeHaveMapCenterPointY) }; })()`);
console.log(`scenario-centre click at (${centre.px},${centre.py}) -> stored X/Y ${fc.x} ${fc.y} (expected ~127407 5482560)`);
await evaluate(`window.__store.dispatch({ type: 'simulation/setHivePlacementMode', payload: true }); 'ok'`);
// real click
const c = await evaluate(`(() => { const b = document.querySelector('.maplibregl-canvas').getBoundingClientRect(); const px = Math.round(b.left + b.width*0.45), py = Math.round(b.top + b.height*0.4); const ll = window.__map.unproject([px-b.left, py-b.top]); return { px, py, lng: ll.lng, lat: ll.lat }; })()`);
await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: c.px, y: c.py, button: 'left', clickCount: 1 });
await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: c.px, y: c.py, button: 'left', clickCount: 1 });
await sleep(800);
const f = await evaluate(`(() => { const f = window.__store.getState().simulation.form; return { x: Number(f.BeeHaveMapCenterPointX), y: Number(f.BeeHaveMapCenterPointY) }; })()`);
const lng = (f.x / 20037508.34) * 180, lat = (180 / Math.PI) * (2 * Math.atan(Math.exp((f.y / 20037508.34) * Math.PI)) - Math.PI / 2);
const back = await evaluate(`(() => { const p = window.__map.project([${lng}, ${lat}]); const b = document.querySelector('.maplibregl-canvas').getBoundingClientRect(); return [Math.round(p.x + b.left), Math.round(p.y + b.top)]; })()`);
console.log(`click at (${c.px},${c.py}) -> stored point projects to (${back[0]},${back[1]}), offset (${back[0]-c.px},${back[1]-c.py}) px; maplibre lon/lat at click ${c.lng.toFixed(5)},${c.lat.toFixed(5)} vs stored ${lng.toFixed(5)},${lat.toFixed(5)}`);
ws.close(); chrome.kill(); process.exit(0);
