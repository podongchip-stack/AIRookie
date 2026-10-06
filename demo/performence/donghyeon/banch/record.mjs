// [demo 브랜치] 모델 성능 비교 영상 녹화 — benchmark.html의 render(t)를 1/fps초마다 부르고 한 장씩 찍어 mp4로 묶는다.
// 실시간 녹화가 아니라 프레임 단위라 끊김·타이밍 흔들림이 없다.
//   node demo/banch/record.mjs [--fps 60] [--page benchmark.html] [--out demo/banch/model_benchmark.mp4]
//   v1: --page benchmark_v1.html --out model_benchmark.mp4 · v2(성능 비교·문제 장면 뺀 것): --page benchmark.html --out model_benchmark_v2.mp4
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { createRequire } from "node:module";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(HERE, "..", "package.json")); // demo/node_modules를 쓴다
const { chromium } = require("playwright-core");
const ffmpeg = require("ffmpeg-static");

const args = process.argv.slice(2);
const opt = (k, d) => (args.includes(k) ? args[args.indexOf(k) + 1] : d);
const FPS = Number(opt("--fps", 60));
const OUT = path.resolve(opt("--out", path.join(HERE, "model_benchmark_v2.mp4")));
const PAGE = opt("--page", "benchmark.html");

const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
await page.goto(pathToFileURL(path.join(HERE, PAGE)).href + "?record=1");
await page.evaluate(() => document.fonts.ready);
const duration = await page.evaluate(() => window.DURATION);
const total = Math.round(duration * FPS);
const cdp = await page.context().newCDPSession(page);

const ff = spawn(ffmpeg, ["-v", "error", "-y", "-f", "image2pipe", "-framerate", String(FPS), "-c:v", "png", "-i", "-",
  "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p", "-r", String(FPS), "-movflags", "+faststart", OUT], { stdio: ["pipe", "inherit", "inherit"] });
const exited = once(ff, "exit");
const t0 = Date.now();
for (let i = 0; i < total; i++) {
  await page.evaluate((t) => window.render(t), i / FPS);
  const { data } = await cdp.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  if (!ff.stdin.write(Buffer.from(data, "base64"))) await once(ff.stdin, "drain");
  if (i % (FPS * 10) === 0) console.log(`  ${(i / FPS).toFixed(0)}초 / ${duration}초`);
}
ff.stdin.end();
await exited;
await browser.close();
console.log(`✅ ${OUT} (${total}프레임, ${((Date.now() - t0) / 1000).toFixed(0)}초 걸림)`);
