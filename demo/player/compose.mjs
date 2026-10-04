// [demo 브랜치] 합본 영상 — 아키텍처 설명 + 시나리오 01(작동 원리) + 시나리오 03·05(2배속)를 하나로 잇는다.
// ⚠ develop에 병합하지 않는다.
//
//   node demo/player/compose.mjs                → demo/out/goldenlink_overview.mp4   (소개: 아키텍처 + 시나리오)
//   node demo/player/compose.mjs benchmark      → demo/out/goldenlink_benchmark.mp4   (1부: 음성 구조화 AI 성능)
//   node demo/player/compose.mjs reliability    → demo/out/goldenlink_reliability.mp4 (2부: 병상 정보 신뢰도 검증)
//
// 1부는 voice 담당자의 벤치마크 하이라이트(demo/explainer/benchmark_highlight.html, 원본 그대로 — 근거 문서는
// feature/voice의 voice/BENCHMARK.md)를 재생해 녹화한다. 녹화 때만 무대를 화면에 꽉 채우고 머리말·조작 버튼·표·약점 문단을 숨긴다.
//
// 2부는 실서버 대시보드의 /verify/stage(팀원이 만든 10장 자동 순환 화면, 실데이터)를 그대로 녹화한다 —
// start-all.sh로 hub·info·거절 로그 수신구·대시보드가 떠 있어야 한다(DEMO_STAGE_URL로 주소 변경).
//
// 먼저 있어야 하는 영상: demo/out/scenario_01_explain.mp4(./demo/record.sh --explain 01),
// scenario_03_calm.mp4 · scenario_05_calm.mp4(./demo/record.sh --calm 03 05).
// 시나리오 01은 통화 구간(진행기가 남긴 .marks.json의 callStart~callEnd)만 2배속으로 잘라 붙인다.
// 설명 화면(demo/explainer/explainer.html)은 Playwright로 그대로 녹화한다 — 서버가 필요 없다.

import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "playwright-core";
import ffmpeg from "ffmpeg-static";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DEMO = path.resolve(HERE, "..");
const OUT = path.join(DEMO, "out");
const TMP = path.join(OUT, "_compose");

// 합본 구성
const PLANS = {};
PLANS.overview = [
  { page: "arch" },
  { video: "scenario_01_explain.mp4", callSpeed: 2 },
  {
    page: "card",
    data: {
      no: "03 · 05",
      title: "이어서 — 다른 상황 두 가지",
      situation: [
        "시나리오 3 · 교통사고 다발성 외상: 가까운 두 병원이 연달아 거절, 세 번째 병원 수용",
        "시나리오 5 · 흉통: 승인한 병원에 도착했지만 수용 불가 → 그 자리에서 재선택",
      ],
      watch: ["2배속으로 재생합니다", "거절이 이어져도 다시 전화를 돌리지 않는다", "도착 후 실패에도 같은 환자 정보로 바로 다음 병원"],
      holdMs: 7000,
    },
  },
  { video: "scenario_03_calm.mp4", speed: 2 },
  { video: "scenario_05_calm.mp4", speed: 2 },
];
PLANS.benchmark = [
  {
    page: "card",
    data: {
      kicker: "1부 · 음성 구조화 AI 성능",
      title: "통화 한 통, 0.015초 만에 환자 정보로",
      situation: [
        "구급대·병원 통화를 읽고 KTAS·주증상·활력징후 등 15개 항목과 원문 구간 5종을 채우는 과제",
        "학습에 쓰지 않은 합성 통화 100건(AI가 만든 시험지 · 정답은 사람 검수 전)으로 모델 22개를 같은 PC·같은 채점 코드로 비교",
      ],
      watch: ["정확도 — 같은 과제를 학습한 소형 LLM과 비슷", "속도 — 소형 LLM보다 370~460배 빠름", "경량화 — 크기 4~5분의 1 · GPU 메모리 절반(3.3GB)"],
      holdMs: 9000,
      noDisc: true,
    },
  },
  {
    html: "benchmark_highlight.html",
    sec: 44,
    // 무대만 화면 가득(1100px 무대를 1920px로 확대) · 머리말·조작·표·약점 숨김
    css: `.intro, .controls, .below, .weak { display: none !important; }
      html { zoom: 1.7454; } .wrap { max-width: 1100px; padding: 0 !important; gap: 0 !important; }
      .stage { border: 0 !important; border-radius: 0 !important; }`,
  },
];
PLANS.reliability = [
  {
    page: "card",
    data: {
      kicker: "2부 · 병상 정보 신뢰도 검증",
      title: "병상 정보, 믿어도 될까?",
      situation: [
        "응급실 병상 숫자는 국가 API(E-Gen)가 병원 신고를 그대로 알려 준다",
        "그 숫자는 구급차가 가는 동안에도 바뀐다 — 그대로 믿으면 도착해서 거절된다",
      ],
      watch: ["모델이 '언제 틀려질지'를 얼마나 잘 맞히는지", "실제 전국 데이터로 20분마다 채점하는 라이브 화면", "모델이 고른 값만 믿었을 때 얼마나 달라지는지"],
      holdMs: 8000,
      noDisc: true,
    },
  },
  { page: "perf", data: { holdMs: 15000, noDisc: true } },
  { stage: process.env.DEMO_STAGE_URL || "http://localhost:3000/verify/stage", sec: 133 },
];
const PLAN = process.argv[2] || "overview";
if (!PLANS[PLAN]) throw new Error(`알 수 없는 구성: ${PLAN} (overview | benchmark | reliability)`);
const COMPOSE = PLANS[PLAN];

// 배속 표시 글꼴(없으면 표시 없이 배속만)
const FONT = ["C:/Windows/Fonts/malgunbd.ttf", "/System/Library/Fonts/AppleSDGothicNeo.ttc", "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"]
  .find((f) => fs.existsSync(f));

async function recordPage(name, mode, data) {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 1,
    recordVideo: { dir: TMP, size: { width: 1920, height: 1080 } },
  });
  const page = await context.newPage();
  await page.goto(pathToFileURL(path.join(DEMO, "explainer", "explainer.html")).href);
  await page.evaluate(([m, d]) => window.play(m, d), [mode, data]);
  await page.waitForFunction(() => window.done === true, null, { timeout: 0 });
  await page.waitForTimeout(400);
  const video = page.video();
  await context.close();
  await browser.close();
  const out = path.join(TMP, `${name}.webm`);
  fs.renameSync(await video.path(), out);
  console.log(`  설명 화면 녹화: ${name}`);
  return out;
}

// 실서버 /verify/stage 녹화 — 데이터가 다 뜨면 1번 슬라이드부터 다시 시작해 sec초 동안 자동 순환을 담는다.
// 녹화는 페이지가 생길 때 시작되므로, 로딩 구간은 시작 시각을 기록해 뒤에서 잘라낸다.
async function recordStage(name, url, sec) {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 1,
    recordVideo: { dir: TMP, size: { width: 1920, height: 1080 } },
  });
  const page = await context.newPage();
  const t0 = Date.now();
  await page.goto(url, { waitUntil: "networkidle", timeout: 180000 });
  await page.waitForTimeout(10000); // 라이브 채점 집계가 늦게 올 수 있다
  await page.getByRole("button", { name: "1번 슬라이드" }).click();
  const start = (Date.now() - t0) / 1000;
  await page.waitForTimeout(sec * 1000 + 600);
  const end = (Date.now() - t0) / 1000;
  const video = page.video();
  await context.close();
  await browser.close();
  const out = path.join(TMP, `${name}.webm`);
  fs.renameSync(await video.path(), out);
  console.log(`  실제 화면 녹화: ${url} (${sec}초)`);
  return { file: out, from: +start.toFixed(2), to: +end.toFixed(2) };
}

// 정적 HTML 장면(팀원 하이라이트 등) 녹화 — 스타일을 덧입힌 뒤 "처음부터"로 다시 재생해 sec초를 담는다
async function recordHtml(name, file, sec, extraCss) {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 1,
    colorScheme: "light",
    recordVideo: { dir: TMP, size: { width: 1920, height: 1080 } },
  });
  const page = await context.newPage();
  const t0 = Date.now();
  await page.goto(pathToFileURL(path.join(DEMO, "explainer", file)).href, { waitUntil: "networkidle" });
  if (extraCss) await page.addStyleTag({ content: extraCss });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(800);
  await page.evaluate(() => document.getElementById("replay")?.click());
  const start = (Date.now() - t0) / 1000;
  await page.waitForTimeout(sec * 1000 + 1500); // 마지막 장면을 잠깐 더
  const end = (Date.now() - t0) / 1000;
  const video = page.video();
  await context.close();
  await browser.close();
  const out = path.join(TMP, `${name}.webm`);
  fs.renameSync(await video.path(), out);
  console.log(`  HTML 장면 녹화: ${file} (${sec}초)`);
  return { file: out, from: +start.toFixed(2), to: +end.toFixed(2) };
}

async function main() {
  fs.mkdirSync(TMP, { recursive: true });
  const parts = []; // {file, speed}
  for (const [i, item] of COMPOSE.entries()) {
    if (item.page) {
      parts.push({ file: await recordPage(`${item.page}_${i}`, item.page, item.data) });
    } else if (item.html) {
      parts.push(await recordHtml(`html_${i}`, item.html, item.sec, item.css));
    } else if (item.stage) {
      parts.push(await recordStage(`stage_${i}`, item.stage, item.sec));
    } else {
      const file = path.join(OUT, item.video);
      if (!fs.existsSync(file)) throw new Error(`${file} 가 없습니다 — ./demo/record.sh 로 먼저 녹화하세요`);
      const marksFile = file.replace(/\.mp4$/, ".marks.json");
      const marks = fs.existsSync(marksFile) ? JSON.parse(fs.readFileSync(marksFile, "utf8")) : {};
      if (item.callSpeed && marks.callStart != null && marks.callEnd != null) {
        // 통화 앞 · 통화(배속) · 통화 뒤 세 조각으로 나눈다
        parts.push({ file, to: marks.callStart });
        parts.push({ file, from: marks.callStart, to: marks.callEnd, speed: item.callSpeed });
        parts.push({ file, from: marks.callEnd });
      } else {
        parts.push({ file, speed: item.speed || 1 });
      }
    }
  }
  // 형식(크기·초당 프레임·화소 형식)을 맞추고, 배속 구간은 빠르게 + 위쪽 가운데에 "N배속" 표시
  const fontArg = FONT ? FONT.replace(/\\/g, "/").replace(/:/g, "\\:") : null;
  const norm = parts
    .map(({ speed = 1, from, to }, i) => {
      let f = `[${i}:v]`;
      if (from != null || to != null) f += `trim=${from != null ? `start=${from}` : "start=0"}${to != null ? `:end=${to}` : ""},setpts=PTS-STARTPTS,`;
      if (speed !== 1) f += `setpts=PTS/${speed},`;
      f += "fps=25,scale=1920:1080,setsar=1,format=yuv420p";
      if (speed !== 1 && fontArg) {
        f += `,drawtext=fontfile='${fontArg}':text='▶▶ ${speed}배속':x=(w-text_w)/2:y=20:fontsize=30:fontcolor=white:box=1:boxcolor=0x0E9F6E@0.95:boxborderw=12`;
      }
      return `${f}[v${i}]`;
    })
    .join(";");
  const cat = parts.map((_, i) => `[v${i}]`).join("") + `concat=n=${parts.length}:v=1:a=0[out]`;
  const out = path.join(OUT, `goldenlink_${PLAN}.mp4`);
  console.log(`  이어 붙이는 중… (${parts.length}개)`);
  execFileSync(
    ffmpeg,
    ["-v", "error", "-y", ...parts.flatMap((p) => ["-i", p.file]), "-filter_complex", `${norm};${cat}`, "-map", "[out]",
      "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out],
    { stdio: "inherit" },
  );
  fs.rmSync(TMP, { recursive: true, force: true });
  console.log(`✅ ${out}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
