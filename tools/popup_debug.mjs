// Diagnose parcel picking in headless Chrome: enable debug mode (Ctrl+D), click a few points
// inside the landscape, report console output and whether a popup appears.
// usage: node tools/popup_debug.mjs http://localhost:32000/ out_prefix
import { spawn } from 'node:child_process';
import { writeFileSync } from 'node:fs';

const [, , url = 'http://localhost:32000/', prefix = 'popup_debug'] = process.argv;
const PORT = 9337;
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--no-first-run',
  `--remote-debugging-port=${PORT}`, '--window-size=1600,1000', '--user-data-dir=' + process.env.TEMP + '/beeview-cdp-popup', 'about:blank'], { stdio: 'ignore' });
const die = (err) => { console.error(err); try { chrome.kill(); } catch {} process.exit(1); };
process.on('uncaughtException', die); process.on('unhandledRejection', die);
setTimeout(() => die(new Error('timeout')), 240000).unref();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function pageTarget() { for (let i = 0; i < 50; i++) { try { const l = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json(); const p = l.find((t) => t.type === 'page'); if (p) return p; } catch {} await sleep(200); } throw new Error('no page'); }
const page = await pageTarget(); const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
let id = 0; const pending = new Map(); const logs = [];
ws.onmessage = (m) => { const msg = JSON.parse(m.data); if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
  else if (msg.method === 'Runtime.consoleAPICalled') logs.push(msg.params.type + ': ' + msg.params.args.map((a) => a.value ?? a.description ?? '').join(' ').slice(0, 160));
  else if (msg.method === 'Runtime.exceptionThrown') logs.push('EXC: ' + msg.params.exceptionDetails.text); };
const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const evaluate = async (e) => (await send('Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: true })).result?.result?.value;
const shot = async (n) => { const r = await send('Page.captureScreenshot', { format: 'png' }); writeFileSync(`${prefix}_${n}.png`, Buffer.from(r.result.data, 'base64')); };
await send('Runtime.enable'); await send('Page.enable'); await send('Page.navigate', { url }); await sleep(12000);
console.log('canvases:', await evaluate(`[...document.querySelectorAll('canvas')].map(c => c.className + ' ' + c.width + 'x' + c.height + ' z=' + getComputedStyle(c).zIndex).join(' | ')`));
console.log('webgl:', await evaluate(`(() => { const c = document.createElement('canvas'); const gl = c.getContext('webgl2') || c.getContext('webgl'); return gl ? gl.getParameter(gl.RENDERER) : 'none'; })()`));
// enable debug mode (Ctrl+D)
await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'd', code: 'KeyD', modifiers: 2, windowsVirtualKeyCode: 68 });
await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'd', code: 'KeyD', modifiers: 2, windowsVirtualKeyCode: 68 });
await sleep(500);
console.log('debug badge:', await evaluate(`document.body.textContent.includes('Debug: ON')`));
const rect = await evaluate(`(() => { const r = document.querySelector('.maplibregl-canvas').getBoundingClientRect(); return { l: r.left, t: r.top, w: r.width, h: r.height }; })()`);
console.log('canvas rect', rect);
for (const [fx, fy] of [[0.63, 0.27], [0.66, 0.32], [0.6, 0.35], [0.68, 0.22], [0.58, 0.28]]) {
  const x = Math.round(rect.l + rect.w * fx), y = Math.round(rect.t + rect.h * fy);
  const before = logs.length;
  await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y, pointerType: 'mouse' });
  await sleep(100);
  await send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', buttons: 1, clickCount: 1, pointerType: 'mouse' });
  await sleep(60);
  await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', buttons: 0, clickCount: 1, pointerType: 'mouse' });
  await sleep(1500);
  const popup = await evaluate(`!!document.querySelector('.maplibregl-popup')`);
  console.log('   state.popup =', await evaluate(`JSON.stringify(window.__beeviewStore && window.__beeviewStore.getState().popup)`), 'placement =', await evaluate(`JSON.stringify(window.__beeviewStore && window.__beeviewStore.getState().simulation && window.__beeviewStore.getState().simulation.hivePlacementMode)`));
  console.log(`click ${x},${y}: popup=${popup}, new logs=${logs.length - before}`);
  logs.slice(before, before + 6).forEach((l) => console.log('   ', l));
  if (popup) { await shot('popup'); console.log('popup text:', await evaluate(`document.querySelector('.maplibregl-popup').textContent.slice(0, 300)`)); break; }
}
await shot('end');
ws.close(); chrome.kill(); process.exit(0);
