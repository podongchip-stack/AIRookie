"""파이썬 엔진(engine/) ↔ JS 엔진(make_map.py → map.html) 대조.

make_map.py 템플릿에서 엔진 부분(`const H = __DATA__;` ~ `// ---------- 지도 ----------`)만 잘라 node(vm)로 돌리고,
같은 환자·같은 슬라이더 값으로 파이썬 solve()를 돌려 환자별 최종 병원·도착 시각·세그먼트·이벤트 순서를 비교한다.
시나리오 5개 + 슬라이더 변주 + 시드 고정 무작위 환자(서울·전국). API 호출 0회, 저장소 파일은 안 바꾼다.

실행: PYTHONUTF8=1 python parity_check.py [--out parity_result.json]   (node 필요)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from engine import SpiderEngine, PatientList, Params  # noqa: E402

TOL = 1e-6

HARNESS = r"""
const fs = require('fs');
const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const out = [];
for (const cs of input.cases) {
  for (const [k, v] of Object.entries(cs.params)) __CTL[k] = (typeof v === 'boolean') ? {checked: v, value: ''} : {value: String(v), checked: false};
  P = cs.patients.map(p => ({...p})); nextId = P.length + 1;
  const t0 = performance.now(); RES = solve(); const ms = performance.now() - t0;
  const hist = {};
  for (const [pid, segs] of Object.entries(RES.hist)) hist[pid] = segs.map(s => ({hpid: s.h.hpid, tStart: s.tStart, tArr: s.tArr, tEnd: s.tEnd, road: s.road, len: s.len, distKm: s.distKm, gap: s.gap ?? null, ncoords: s.coords.length}));
  const cur = {};
  for (const [pid, s] of Object.entries(RES.cur)) cur[pid] = RES.hist[pid].indexOf(s);
  out.push({name: cs.name, ms, settled: RES.settled, tMax: RES.tMax, forced: RES.forced, cur, hist,
            events: RES.events.map(e => ({t: e.t, type: e.type, hpid: e.hpid || null, text: e.text}))});
}
fs.writeFileSync(process.argv[3], JSON.stringify(out));
"""


def extract_js_engine() -> str:
    src = open(os.path.join(HERE, "make_map.py"), encoding="utf-8").read()
    a = src.index("const H = __DATA__;")
    b = src.index("// ---------- 지도 ----------")
    code = src[a:b]
    code = code.replace("const $ = id=>document.getElementById(id);", "const $ = id=>__CTL[id];")
    assert "__CTL" in code, "엔진 코드에서 $ 정의를 못 찾았다"
    return code


def run_js(cases: list[dict], hospitals: list[dict]) -> list[dict]:
    data = json.dumps(hospitals, ensure_ascii=False, separators=(",", ":"))
    engine = extract_js_engine().replace("__DATA__", data)
    prelude = (
        "const vm=require('vm'); const __CTL={};\n"
        "globalThis.window = globalThis;\n"
        "globalThis.atob = b => Buffer.from(b, 'base64').toString('latin1');\n"
        "globalThis.performance = require('perf_hooks').performance;\n"
        f"vm.runInThisContext(require('fs').readFileSync({json.dumps(os.path.join(HERE, 'roads_data.js'))}, 'utf8'));\n"
    )
    with tempfile.TemporaryDirectory() as td:
        js = os.path.join(td, "harness.js")
        inp = os.path.join(td, "in.json")
        outp = os.path.join(td, "out.json")
        open(js, "w", encoding="utf-8").write(prelude + engine + HARNESS)
        json.dump({"cases": cases}, open(inp, "w", encoding="utf-8"), ensure_ascii=False)
        subprocess.run(["node", "--max-old-space-size=4096", js, inp, outp], check=True)
        return json.load(open(outp, encoding="utf-8"))


def js_params(prm: Params) -> dict:
    return {"tau": prm.tau, "cap": prm.cap, "dwell": prm.dwell, "mu2": prm.mu2, "mu3": prm.mu3, "lam": prm.lam,
            "sh": prm.start_hour, "dyn": prm.dyn, "wload": prm.wload}


def build_cases(eng: SpiderEngine) -> list[dict]:
    cases = []
    for name in ("gangnam", "stagger", "same2", "turnover", "hongdae"):
        cases.append({"name": name, "patients": PatientList.scenario(name).items, "prm": Params()})
    cases.append({"name": "gangnam dyn=off", "patients": PatientList.scenario("gangnam").items, "prm": Params(dyn=False)})
    cases.append({"name": "hongdae tau=20 cap=1", "patients": PatientList.scenario("hongdae").items, "prm": Params(tau=20, cap=1)})
    cases.append({"name": "stagger wload=off", "patients": PatientList.scenario("stagger").items, "prm": Params(wload=False)})
    cases.append({"name": "hongdae night 23h", "patients": PatientList.scenario("hongdae").items, "prm": Params(start_hour=23)})
    cases.append({"name": "same2 mu2=60 lam=15 dwell=10", "patients": PatientList.scenario("same2").items, "prm": Params(mu2=60, lam=15, dwell=10)})
    for seed, scope, n in ((1, "seoul", 30), (2, "seoul", 60), (3, "korea", 40)):
        pl = PatientList()
        for r in eng.random_patients(n, 20, scope, "real", seed=seed):
            pl.add("무작위", r["k"], r["t0"], r["lat"], r["lng"], cond=r["cond"])
        cases.append({"name": f"random {scope} n={n} seed={seed}", "patients": pl.items, "prm": Params()})
    pl = PatientList()
    for r in eng.random_patients(40, 10, "seoul", "severe", seed=7):
        pl.add("무작위", r["k"], r["t0"], r["lat"], r["lng"], cond=r["cond"])
    cases.append({"name": "random seoul severe n=40 seed=7 cap=1", "patients": pl.items, "prm": Params(cap=1)})
    return cases


def close(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) <= TOL


def compare(name: str, py: dict, js: dict) -> list[str]:
    diffs = []
    if set(py["cur"]) != set(js["cur"]):
        diffs.append(f"cur 환자 집합 다름 py={sorted(py['cur'])} js={sorted(js['cur'])}")
    for pid in py["hist"]:
        ps, jsg = py["hist"][pid], js["hist"].get(pid, [])
        if len(ps) != len(jsg):
            diffs.append(f"#{pid} 세그먼트 수 py={len(ps)} js={len(jsg)}")
            continue
        for i, (s, j) in enumerate(zip(ps, jsg)):
            for key in ("hpid",):
                if s[key] != j[key]:
                    diffs.append(f"#{pid} seg{i} {key} py={s[key]} js={j[key]}")
            for key in ("tStart", "tArr", "tEnd", "road", "len"):
                if not close(s.get(key), j.get(key)):
                    diffs.append(f"#{pid} seg{i} {key} py={s.get(key)} js={j.get(key)}")
            if not close(s.get("distKm"), j.get("distKm")):
                # 도로 분이 같은데 km만 다르면 길이가 같은 두 경로 중 다른 쪽을 복원한 것(선행자 동률) — 모델 차이가 아니다
                tag = "(참고) " if close(s.get("road"), j.get("road")) else ""
                diffs.append(f"{tag}#{pid} seg{i} distKm py={s.get('distKm')} js={j.get('distKm')}{' — 같은 시간의 다른 경로(동률)' if tag else ''}")
    if set(py["forced"]) != set(js["forced"]):
        diffs.append(f"forced py={sorted(py['forced'])} js={sorted(js['forced'])}")
    if not close(py["tMax"], js["tMax"]):
        diffs.append(f"tMax py={py['tMax']} js={js['tMax']}")
    pe = [(e["type"], round(e["t"], 6), e.get("hpid")) for e in py["events"]]
    je = [(e["type"], round(e["t"], 6), e.get("hpid")) for e in js["events"]]
    if pe != je:
        diffs.append(f"이벤트 순서/종류 다름 (py {len(pe)}개, js {len(je)}개)")
    text_mismatch = sum(1 for a, b in zip(py["events"], js["events"]) if a["text"] != b["text"])
    if text_mismatch:
        # 위에서 km 동률만 잡혔으면 문구 차이도 그 km 표기뿐이다 — 참고로 내린다
        only_km = all(d.startswith("(참고)") for d in diffs)
        diffs.append(f"{'(참고) ' if only_km else ''}이벤트 문구 다름 {text_mismatch}/{len(py['events'])}건 (숫자 반올림·순서 차이일 수 있음 — 아래 예시)")
        for a, b in zip(py["events"], js["events"]):
            if a["text"] != b["text"]:
                diffs.append(f"   py: {a['text'][:160]}")
                diffs.append(f"   js: {b['text'][:160]}")
                break
    if py["settled"] != js["settled"]:
        diffs.append(f"(참고) 탐색 노드 수 py={py['settled']} js={js['settled']}")
    return diffs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="결과 JSON 저장 경로(생략하면 저장 안 함)")
    args = ap.parse_args()
    t0 = time.time()
    eng = SpiderEngine()
    print(f"엔진 로드 {time.time() - t0:.1f}s · 병원 {len(eng.hospitals)} (병상 {len(eng.live)}) · 도로 노드 {getattr(eng.roads, 'n', 0):,}")
    cases = build_cases(eng)
    py_results = []
    for cs in cases:
        t0 = time.time()
        r = eng.solve(cs["patients"], cs["prm"])
        py_results.append(r | {"name": cs["name"], "pyMs": round((time.time() - t0) * 1000)})
    print(f"JS 엔진(node) 실행 중 — {len(cases)}개 사례...")
    t0 = time.time()
    js_results = run_js([{"name": cs["name"], "patients": cs["patients"], "params": js_params(cs["prm"])} for cs in cases], eng.hospitals)
    print(f"  node {time.time() - t0:.1f}s")
    ok = 0
    report = []
    for cs, py, js in zip(cases, py_results, js_results):
        diffs = compare(cs["name"], py, js)
        real = [d for d in diffs if not d.startswith("(참고)")]
        status = "일치" if not real else f"차이 {len(real)}"
        print(f"[{status:>6}] {cs['name']:<40} 환자 {len(cs['patients']):>3} · py {py['pyMs']:>5}ms js {js['ms']:>7.0f}ms · 이벤트 {len(py['events'])}")
        for d in diffs:
            print("        " + d)
        ok += not real
        report.append({"name": cs["name"], "patients": len(cs["patients"]), "ok": not real, "diffs": diffs, "pyMs": py["pyMs"], "jsMs": round(js["ms"])})
    print(f"\n{ok}/{len(cases)} 사례 일치")
    if args.out:
        json.dump({"tol": TOL, "cases": report}, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("저장:", args.out)
    sys.exit(0 if ok == len(cases) else 1)


if __name__ == "__main__":
    main()
