// Headless-Chrome check of the map-first layout: toggles drawers and header,
// verifies persisted state after reload, takes screenshots.
// usage: node tools/layout_check.mjs http://localhost:32000/ out_prefix
import { spawn } from 'node:child_process';
import { writeFileSync } from 'node:fs';

const [, , url = 'http://localhost:32000/', prefix = 'layout_check'] = process.argv;
const PORT = 9334;
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const profileDir = process.env.TEMP + '/beeview-cdp-layout';

const chrome = spawn(CHROME, [
  '--headless=new', '--disable-gpu', '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
  '--no-first-run', '--no-default-browser-check', `--remote-debugging-port=${PORT}`,
  '--window-size=1600,1000', '--user-data-dir=' + profileDir, 'about:blank',
], { stdio: 'ignore' });
const die = (err) => { console.error(err); try { chrome.kill(); } catch {} process.exit(1); };
process.on('uncaughtException', die);
process.on('unhandledRejection', die);
setTimeout(() => die(new Error('timed out after 180 s')), 180000).unref();

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
  else if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') errors.push(msg.params.args.map((a) => a.value ?? a.description).join(' ').slice(0, 200));
};
const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const evaluate = async (expression) => (await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })).result?.result?.value;
const shot = async (name) => { const r = await send('Page.captureScreenshot', { format: 'png' }); writeFileSync(`${prefix}_${name}.png`, Buffer.from(r.result.data, 'base64')); console.log('screenshot', `${prefix}_${name}.png`); };
const state = () => evaluate(`JSON.stringify({
  left: document.querySelector('.drawer--left')?.className, leftW: document.querySelector('.drawer--left')?.getBoundingClientRect().width,
  right: document.querySelector('.drawer--right')?.className, rightW: document.querySelector('.drawer--right')?.getBoundingClientRect().width,
  bottom: document.querySelector('.drawer--bottom')?.className, bottomH: document.querySelector('.drawer--bottom')?.getBoundingClientRect().height,
  header: !!document.querySelector('.topbar'), handle: !!document.querySelector('.topbar-handle'),
  navTop: document.querySelector('.maplibregl-ctrl-top-left')?.getBoundingClientRect().top,
  navLeft: document.querySelector('.maplibregl-ctrl-top-left')?.getBoundingClientRect().left,
  insets: ['top','left','right','bottom'].map(k => getComputedStyle(document.querySelector('.app-shell')).getPropertyValue('--inset-' + k).trim()),
  stored: localStorage.getItem('beeview.ui.v1'),
  slider: document.querySelector('.day-slider input')?.value,
})`).then(JSON.parse);

await send('Runtime.enable'); await send('Page.enable');
await send('Page.navigate', { url });
await sleep(3000);
// clear persisted layout on the app's origin, then load fresh defaults (the app
// re-saves on pagehide, so block setItem for this unload)
await evaluate(`localStorage.removeItem('beeview.ui.v1'); Storage.prototype.setItem = () => {};`);
await send('Page.reload');
await sleep(9000);
console.log('1 defaults:', await state());
await shot('defaults');

await evaluate(`document.querySelector('.drawer--left .drawer__toggle').click()`);
await evaluate(`document.querySelector('.drawer--right .drawer__toggle').click()`);
await evaluate(`document.querySelector('.drawer--bottom .drawer__toggle').click()`);
await sleep(400);
console.log('2 all collapsed:', await state());
await shot('collapsed');

// slider still works while the chart drawer is collapsed
await evaluate(`(() => { const i = document.querySelector('.day-slider input'); const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; setter.call(i, '120'); i.dispatchEvent(new Event('input', { bubbles: true })); })()`);
await sleep(300);
console.log('3 slider -> day:', await evaluate(`document.querySelector('.day-slider__label')?.textContent`));

await evaluate(`document.querySelector('.header-icon-button[title="Hide header"]').click()`);
await sleep(300);
console.log('4 header hidden:', await state());

// drag the left drawer open again and resize it via pointer events on the resizer
await evaluate(`document.querySelector('.drawer--left .drawer__tab').click()`);
await sleep(300);
await evaluate(`(() => {
  const r = document.querySelector('.drawer--left .drawer__resizer'); const b = r.getBoundingClientRect();
  const x = b.left + 3, y = b.top + 100;
  const ev = (type, cx) => r.dispatchEvent(new PointerEvent(type, { bubbles: true, cancelable: true, pointerId: 1, pointerType: 'mouse', button: 0, buttons: 1, clientX: cx, clientY: y }));
  r.setPointerCapture = () => {}; r.releasePointerCapture = () => {};
  ev('pointerdown', x); ev('pointermove', x + 60); ev('pointermove', x + 120); ev('pointerup', x + 120);
})()`);
await sleep(800);
console.log('5 after drag (+120):', await state());

await sleep(600); // let the debounced save run
await send('Page.reload');
await sleep(9000);
console.log('6 after reload:', await state());
await shot('reloaded');
console.log(`${errors.length} console errors`); errors.slice(0, 10).forEach((e) => console.log('  ', e));
ws.close(); chrome.kill(); process.exit(0);
