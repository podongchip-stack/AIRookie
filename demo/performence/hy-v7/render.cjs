// 결정적 렌더: 헤드리스 Chrome에서 Film.seek(t) → 캔버스 JPEG → ffmpeg. 오디오 없음.
// 영상:   node render.cjs video out.mp4 [fps=60] [scale=2]
// 스틸:   node render.cjs stills <출력폴더> t1,t2,... [scale=1]
const { spawn } = require('node:child_process');
const path = require('node:path'), fs = require('node:fs'), os = require('node:os');
const [mode = 'video', outArg = 'export/film.mp4', a3, a4] = process.argv.slice(2);
const dir = __dirname, PORT = 9350, HTTP = 8797;
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const server = spawn('python3', ['-m', 'http.server', String(HTTP), '--bind', '127.0.0.1', '--directory', dir], { stdio: 'ignore' });
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'hy-chrome-'));
  const chrome = spawn(CHROME, [`--remote-debugging-port=${PORT}`, '--headless=new', '--hide-scrollbars', '--mute-audio', '--no-first-run', '--disable-background-timer-throttling', '--disable-renderer-backgrounding', `--user-data-dir=${profile}`, '--window-size=1280,800', 'about:blank'], { stdio: 'ignore' });
  const kill = () => { try { chrome.kill(); } catch { } try { server.kill(); } catch { } };
  let targets; for (let i = 0; i < 80; i++) { try { targets = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json(); if (targets.length) break; } catch { } await sleep(250); }
  const page = targets.find(t => t.type === 'page'); const ws = new WebSocket(page.webSocketDebuggerUrl); await new Promise(r => ws.onopen = r);
  let id = 0; const pend = new Map(); ws.onmessage = m => { const d = JSON.parse(m.data); if (d.id && pend.has(d.id)) { pend.get(d.id)(d); pend.delete(d.id); } };
  const cdp = (method, params = {}) => new Promise((res, rej) => { const n = ++id; pend.set(n, d => d.error ? rej(new Error(method + ': ' + d.error.message)) : res(d.result)); ws.send(JSON.stringify({ id: n, method, params })); });
  const ev = async e => { const r = await cdp('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true }); if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 400)); return r.result.value; };
  const scale = Number(mode === 'video' ? (a4 || 2) : (a4 || 1));
  await cdp('Page.enable');
  for (let i = 0; i < 40; i++) { try { await fetch(`http://127.0.0.1:${HTTP}/index.html`); break; } catch { await sleep(250); } }
  await cdp('Page.navigate', { url: `http://127.0.0.1:${HTTP}/index.html?render=1&scale=${scale}` });
  for (let i = 0; i < 80; i++) { if (await ev('!!(window.Film&&Film.ready)').catch(() => false)) break; await sleep(250); }
  await ev('document.fonts.ready.then(()=>1)'); await sleep(300);
  const grab = async (t, q) => { await ev(`Film.seek(${t.toFixed(5)});1`); const d = await ev(`Film.frame(${q})`); return Buffer.from(d.split(',')[1], 'base64'); };
  if (mode === 'stills') {
    const out = path.resolve(outArg); fs.mkdirSync(out, { recursive: true });
    for (const t of a3.split(',').map(Number)) { fs.writeFileSync(path.join(out, `t${t.toFixed(1).padStart(6, '0')}.jpg`), await grab(t, .9)); }
    console.log('stills ->', out); kill(); process.exit(0);
  }
  const fps = Number(a3 || 60), dur = await ev('Film.duration'), frames = Math.floor(dur * fps) + 1, out = path.resolve(outArg);
  fs.mkdirSync(path.dirname(out), { recursive: true });
  const ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(fps), '-c:v', 'mjpeg', '-i', '-', '-c:v', 'libx264', '-preset', 'slow', '-crf', '14', '-pix_fmt', 'yuv420p', '-tune', 'animation', '-movflags', '+faststart', out], { stdio: ['pipe', 'inherit', 'inherit'] });
  const done = new Promise(r => ff.on('close', r)); const t0 = Date.now();
  for (let i = 0; i < frames; i++) {
    const buf = await grab(i / fps, .97);
    if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
    if (i % 300 === 0) console.log(`frame ${i}/${frames}  ${((Date.now() - t0) / 1000).toFixed(0)}s`);
  }
  ff.stdin.end(); const code = await done; kill(); console.log('ffmpeg exit', code, '->', out); process.exit(code);
})().catch(e => { console.error('FAIL', e); process.exit(1); });
